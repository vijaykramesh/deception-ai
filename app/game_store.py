from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis

from app.api.models import GamePhase, GameState, Solution
from app.assets.singleton import get_assets
from app.game_setup import apply_solution_and_secrets, build_initial_players, deal_hands
from app.streams import Mailbox, publish_to_mailbox


GAMES_SET_KEY = "deception:games"
GAME_KEY_PREFIX = "deception:game:"  # + {uuid}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _game_key(game_id: UUID) -> str:
    return f"{GAME_KEY_PREFIX}{game_id}"


def validate_player_counts(
    *,
    num_ai_players: int,
    num_human_players: int,
    min_players: int = 4,
    max_players: int = 12,
) -> None:
    total = num_ai_players + num_human_players
    if total < min_players:
        raise ValueError(f"At least {min_players} total players required")
    if total > max_players:
        raise ValueError(f"At most {max_players} total players allowed")
    if num_ai_players <= 0 and num_human_players <= 0:
        raise ValueError("At least one player is required")


def save_game(*, r: redis.Redis, state: GameState) -> None:
    # redis-py is synchronous; explicit cast helps some IDEs avoid thinking these are coroutines.
    r_sync = r  # type: ignore[assignment]
    state.last_updated_at = _now()
    r_sync.set(_game_key(state.game_id), state.model_dump_json())


def get_game(*, r: redis.Redis, game_id: UUID) -> GameState | None:
    raw = r.get(_game_key(game_id))
    if not raw:
        return None
    return GameState.model_validate_json(raw)


def require_game(*, r: redis.Redis, game_id: UUID) -> GameState:
    state = get_game(r=r, game_id=game_id)
    if state is None:
        raise ValueError("Game not found")
    return state


def require_player(*, state: GameState, player_id: str) -> int:
    for idx, p in enumerate(state.players):
        if p.player_id == player_id:
            return idx
    raise ValueError("Player not found")


async def set_murder_solution(
    *,
    r: redis.Redis,
    game_id: UUID,
    player_id: str,
    clue_id: str,
    means_id: str,
) -> GameState:
    state = require_game(r=r, game_id=game_id)
    pidx = require_player(state=state, player_id=player_id)
    player = state.players[pidx]

    if state.phase != GamePhase.setup_awaiting_murder_pick:
        raise ValueError("Game is not awaiting murder selection")

    if player.role != "murderer":
        raise ValueError("Only the murderer can set the solution")

    if clue_id not in player.hand.clue_ids:
        raise ValueError("clue must be chosen from the murderer's dealt clue cards")
    if means_id not in player.hand.means_ids:
        raise ValueError("means must be chosen from the murderer's dealt means cards")

    sol = Solution(means_id=means_id, clue_id=clue_id)
    apply_solution_and_secrets(state=state, solution=sol)
    state.phase = GamePhase.discussion

    save_game(r=r, state=state)
    return state


def add_discussion_comment(*, r: redis.Redis, game_id: UUID, player_id: str, comments: str) -> GameState:
    state = require_game(r=r, game_id=game_id)
    require_player(state=state, player_id=player_id)

    if state.phase == GamePhase.completed:
        raise ValueError("Game is completed")

    seq = (state.discussion[-1].seq + 1) if state.discussion else 1
    from app.api.models import DiscussionComment

    state.discussion.append(DiscussionComment(seq=seq, player_id=player_id, created_at=_now(), comments=comments))
    save_game(r=r, state=state)
    return state


def submit_solution_guess(
    *,
    r: redis.Redis,
    game_id: UUID,
    player_id: str,
    murderer_id: str,
    clue_id: str,
    means_id: str,
) -> GameState:
    state = require_game(r=r, game_id=game_id)
    pidx = require_player(state=state, player_id=player_id)
    player = state.players[pidx]

    if state.phase != GamePhase.discussion:
        raise ValueError("Game is not in discussion phase")

    if player.role != "investigator":
        raise ValueError("Only an investigator can submit a solve")

    if not player.has_badge:
        raise ValueError("Investigator has no badge and cannot solve")

    if state.solution is None:
        raise ValueError("Solution not set yet")

    correct = (
        murderer_id == next((p.player_id for p in state.players if p.role == "murderer"), None)
        and clue_id == state.solution.clue_id
        and means_id == state.solution.means_id
    )

    if correct:
        state.phase = GamePhase.completed
        state.winning_investigator_id = player.player_id
    else:
        player.has_badge = False
        state.players[pidx] = player

    save_game(r=r, state=state)
    return state


async def create_game(
    *,
    r: redis.Redis,
    num_ai_players: int,
    num_human_players: int,
    min_players: int = 4,
    max_players: int = 12,
) -> GameState:
    validate_player_counts(
        num_ai_players=num_ai_players,
        num_human_players=num_human_players,
        min_players=min_players,
        max_players=max_players,
    )

    game_id = uuid4()
    now = _now()

    seed = random.SystemRandom().randint(1, 2**31 - 1)
    rng = random.Random(seed)

    players = build_initial_players(num_ai_players=num_ai_players, num_human_players=num_human_players, rng=rng)

    assets = get_assets()
    await deal_hands(assets=assets, players=players, rng=rng)

    state = GameState(
        game_id=game_id,
        num_ai_players=num_ai_players,
        num_human_players=num_human_players,
        created_at=now,
        last_updated_at=now,
        seed=seed,
        players=players,
        phase=GamePhase.setup_awaiting_murder_pick,
        solution=None,
        winning_investigator_id=None,
        discussion=[],
    )

    r_sync = r  # type: ignore[assignment]
    key = _game_key(game_id)
    r_sync.set(key, state.model_dump_json())
    r_sync.sadd(GAMES_SET_KEY, str(game_id))

    # Enqueue initial prompt to the murderer.
    murderer = next((p for p in state.players if p.role == "murderer"), None)
    if murderer is not None:
        publish_to_mailbox(
            r=r,
            mailbox=Mailbox(game_id=str(game_id), player_id=murderer.player_id),
            fields={
                "type": "prompt_murder_pick",
                "game_id": str(game_id),
                "player_id": murderer.player_id,
                "phase": state.phase.value,
                "clue_ids": ",".join(murderer.hand.clue_ids),
                "means_ids": ",".join(murderer.hand.means_ids),
            },
        )

    return state


def list_games(*, r: redis.Redis) -> list[GameState]:
    ids = sorted(r.smembers(GAMES_SET_KEY))
    out: list[GameState] = []
    for sid in ids:
        try:
            gid = UUID(sid)
        except ValueError:
            continue
        state = get_game(r=r, game_id=gid)
        if state is not None:
            out.append(state)
    out.sort(key=lambda s: s.created_at, reverse=True)
    return out
