from __future__ import annotations

from dataclasses import dataclass

import redis

from app.actions import dispatch_action_async
from app.game_store import get_game
from app.streams import Mailbox


@dataclass(frozen=True, slots=True)
class AgentRunnerConfig:
    # How long to block waiting for a mailbox message.
    block_ms: int = 250
    # Max messages to read per iteration.
    count: int = 10


def _group_name_for(*, game_id: str) -> str:
    return f"agents:{game_id}"


def _consumer_name_for(*, player_id: str) -> str:
    return f"agent:{player_id}"


def ensure_mailbox_group(*, r: redis.Redis, stream_key: str, group: str) -> None:
    """Ensure a consumer group exists for the given stream.

    Uses MKSTREAM so missing streams are created.
    """

    try:
        r.xgroup_create(stream_key, group, id="0", mkstream=True)
    except Exception as e:
        # BUSYGROUP is expected if it already exists.
        if "BUSYGROUP" not in str(e):
            raise


async def handle_mailbox_entry(
    *,
    r: redis.Redis,
    game_id: str,
    player_id: str,
    fields: dict[str, str],
) -> bool:
    """Handle a single mailbox message.

    Returns True if it performed an action.
    """

    msg_type = fields.get("type")

    if msg_type == "prompt_murder_pick":
        from uuid import UUID

        gid = UUID(game_id)

        # Use the allowed IDs from the prompt message if present (preferred),
        # so the decision is fully driven by what the agent was told.
        clue_ids = [s for s in (fields.get("clue_ids") or "").split(",") if s]
        means_ids = [s for s in (fields.get("means_ids") or "").split(",") if s]

        clue_id, means_id = await decide_and_pick_solution_via_llm(
            r=r,
            game_id=game_id,
            murderer_id=player_id,
            clue_ids=clue_ids or None,
            means_ids=means_ids or None,
        )

        await dispatch_action_async(
            r=r,
            game_id=gid,
            player_id=player_id,
            action="murder",
            payload={"player_id": player_id, "clue": clue_id, "means": means_id},
        )
        return True

    # For now, ignore other mailbox message types.
    return False


async def run_agent_step(*, r: redis.Redis, game_id: str, player_id: str, config: AgentRunnerConfig | None = None) -> bool:
    """Run one poll/step for a single AI player.

    - Ensures consumer group exists for their mailbox stream
    - Reads up to `config.count` messages
    - Handles supported prompts
    - Acks processed messages

    Returns True if any prompt was handled.
    """

    # redis-py is synchronous; explicit alias helps some IDEs.
    r_sync = r  # type: ignore[assignment]

    cfg = config or AgentRunnerConfig()
    stream_key = Mailbox(game_id=game_id, player_id=player_id).key
    group = _group_name_for(game_id=game_id)
    consumer = _consumer_name_for(player_id=player_id)

    ensure_mailbox_group(r=r_sync, stream_key=stream_key, group=group)

    # Read new messages (">" means never-delivered messages).
    resp = r_sync.xreadgroup(group, consumer, {stream_key: ">"}, count=cfg.count, block=cfg.block_ms)
    if not resp:
        return False

    handled_any = False

    for _stream, messages in resp:
        for msg_id, fields in messages:
            did = await handle_mailbox_entry(r=r_sync, game_id=game_id, player_id=player_id, fields=fields)
            # Ack regardless; mailbox is an append-only history so we don't want to reprocess.
            r_sync.xack(stream_key, group, msg_id)
            handled_any = handled_any or did

    return handled_any


async def run_game_agents_once(*, r: redis.Redis, game_id: str, config: AgentRunnerConfig | None = None) -> bool:
    """Run one scan over all AI players in a given game.

    Returns True if any agent handled a prompt.
    """

    from uuid import UUID

    state = get_game(r=r, game_id=UUID(game_id))
    if state is None:
        return False

    handled_any = False
    for p in state.players:
        if not p.is_ai:
            continue
        handled_any = (await run_agent_step(r=r, game_id=game_id, player_id=p.player_id, config=config)) or handled_any

    return handled_any


# ---- LLM decision helper (kept separate so tests can monkeypatch it) ----

from app.agents.factory import create_default_agent
from app.agents.solution_picker import pick_solution_with_agent
from app.contexts import make_base_player_context
from app.core.context import PlayerContext, compose_context
from app.roles import RoleName, make_role_context


async def decide_and_pick_solution_via_llm(
    *,
    r: redis.Redis,
    game_id: str,
    murderer_id: str,
    clue_ids: list[str] | None = None,
    means_ids: list[str] | None = None,
) -> tuple[str, str]:
    """Use the murderer agent to pick clue/means from allowed IDs.

    If `clue_ids/means_ids` are provided (e.g., from mailbox prompt payload), we use them.
    Otherwise we fall back to loading the murderer hand from game state.
    """

    from uuid import UUID

    state = get_game(r=r, game_id=UUID(game_id))
    if state is None:
        raise ValueError("Game not found")

    murderer = next(p for p in state.players if p.player_id == murderer_id)

    allowed_clues = clue_ids if clue_ids is not None else list(murderer.hand.clue_ids)
    allowed_means = means_ids if means_ids is not None else list(murderer.hand.means_ids)

    base = make_base_player_context(system_prefix="")
    player_ctx = PlayerContext(
        player_id=murderer.player_id,
        display_name=f"Seat {murderer.seat} (Murderer)",
        prompt=(
            "You are the Murderer. Choose the true Means of Murder and Key Evidence "
            "from the allowed IDs provided."
        ),
    )
    role_ctx = make_role_context(RoleName.murderer)
    ctx = compose_context(base=base, player=player_ctx, role=role_ctx)

    agent = create_default_agent(name=f"murderer-{murderer.player_id}")

    picked = await pick_solution_with_agent(
        agent=agent,
        ctx=ctx,
        clue_ids=allowed_clues,
        means_ids=allowed_means,
    )

    return picked.clue, picked.means
