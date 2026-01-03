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

    # Phase-gating: on persistent Redis, we may see older messages when using group fallback.
    # Never act on a prompt that doesn't match the current game phase.
    from uuid import UUID

    state = get_game(r=r, game_id=UUID(game_id))
    if state is None:
        return False

    if msg_type == "prompt_murder_pick":
        if state.phase.value != "setup_awaiting_murder_pick":
            return False

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

    if msg_type == "prompt_fs_scene_pick":
        if state.phase.value != "setup_awaiting_fs_scene_pick":
            return False

        gid = UUID(game_id)

        location_ids = [s for s in (fields.get("location_ids") or "").split(",") if s]
        cause_ids = [s for s in (fields.get("cause_ids") or "").split(",") if s]

        # Optional: the chosen solution (if provided) so the FS can pick a coherent scene.
        clue_id = fields.get("clue_id") or None
        means_id = fields.get("means_id") or None

        # Backstop: if mailbox payload didn't include these (or older messages are being replayed),
        # use the persisted game solution.
        if (clue_id is None or means_id is None) and state.solution is not None:
            clue_id = clue_id or state.solution.clue_id
            means_id = means_id or state.solution.means_id

        # If assets don't include the expected tile categories, don't crash the agent runner.
        # We'll simply leave the game in the awaiting phase for manual handling.
        if not location_ids or not cause_ids:
            return False

        location_id, cause_id = await decide_and_pick_fs_scene_via_llm(
            r=r,
            game_id=game_id,
            fs_id=player_id,
            location_ids=location_ids or None,
            cause_ids=cause_ids or None,
            clue_id=clue_id,
            means_id=means_id,
        )

        await dispatch_action_async(
            r=r,
            game_id=gid,
            player_id=player_id,
            action="fs_scene",
            payload={"player_id": player_id, "location": location_id, "cause": cause_id},
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

    def _read(start_id: str):
        return r_sync.xreadgroup(group, consumer, {stream_key: start_id}, count=cfg.count, block=cfg.block_ms)

    # Read new messages (">" means never-delivered messages).
    resp = _read(">")

    # If nothing was returned but the stream has entries, we may be in a situation where
    # messages are pending/claimed by the group from a previous run (common with persistent
    # Redis in env-gated integration tests). Do a single fallback read from "0".
    if not resp:
        try:
            if r_sync.xlen(stream_key) > 0:
                resp = _read("0")
        except Exception:
            # If xlen/xreadgroup fails for any reason, keep original behavior.
            resp = resp

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

    Deterministic behavior: handle at most ONE prompt per invocation.

    Returns True if any agent handled a prompt.
    """

    from uuid import UUID

    state = get_game(r=r, game_id=UUID(game_id))
    if state is None:
        return False

    # Only try to run agents that are relevant to the current setup phase.
    # This ensures a single call doesn't advance through multiple phases.
    if state.phase.value == "setup_awaiting_murder_pick":
        murderer = next((p for p in state.players if p.role == "murderer" and p.is_ai), None)
        if murderer is None:
            return False
        return await run_agent_step(r=r, game_id=game_id, player_id=murderer.player_id, config=config)

    if state.phase.value == "setup_awaiting_fs_scene_pick":
        fs = next((p for p in state.players if p.role == "forensic_scientist" and p.is_ai), None)
        if fs is None:
            return False
        return await run_agent_step(r=r, game_id=game_id, player_id=fs.player_id, config=config)

    # In other phases (discussion/completed), do nothing for now.
    return False


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


async def decide_and_pick_fs_scene_via_llm(
    *,
    r: redis.Redis,
    game_id: str,
    fs_id: str,
    location_ids: list[str] | None = None,
    cause_ids: list[str] | None = None,
    clue_id: str | None = None,
    means_id: str | None = None,
) -> tuple[str, str]:
    """Use the FS agent to pick Location + Cause of Death from allowed IDs.

    If clue_id/means_id are given (e.g., from the mailbox prompt), we incorporate them into the
    FS prompt so the decision is explicitly conditioned on the selected solution.
    """

    from uuid import UUID

    from app.agents.scene_picker import pick_scene_with_agent
    from app.game_store import _cause_ids_from_assets, _location_ids_from_assets

    state = get_game(r=r, game_id=UUID(game_id))
    if state is None:
        raise ValueError("Game not found")

    fs = next(p for p in state.players if p.player_id == fs_id)

    all_location_ids = _location_ids_from_assets()
    all_cause_ids = _cause_ids_from_assets()

    allowed_locations = location_ids if location_ids is not None else all_location_ids
    allowed_causes = cause_ids if cause_ids is not None else all_cause_ids

    base = make_base_player_context(system_prefix="")
    extra = ""
    if clue_id and means_id:
        extra = (
            "\n\nThe murderer has already selected the true solution. "
            f"Selected clue_id={clue_id} and means_id={means_id}. "
            "Pick a Location and Cause of Death that best fit this selection."
        )

    player_ctx = PlayerContext(
        player_id=fs.player_id,
        display_name=f"Seat {fs.seat} (Forensic Scientist)",
        prompt=(
            "You are the Forensic Scientist. Choose the Location and Cause of Death "
            "from the allowed IDs provided." + extra
        ),
    )
    role_ctx = make_role_context(RoleName.forensic_scientist)
    ctx = compose_context(base=base, player=player_ctx, role=role_ctx)

    agent = create_default_agent(name=f"fs-{fs.player_id}")

    picked = await pick_scene_with_agent(
        agent=agent,
        ctx=ctx,
        location_ids=list(allowed_locations),
        cause_ids=list(allowed_causes),
    )

    return picked.location, picked.cause
