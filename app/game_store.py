from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis

from app.api.models import GameState
from app.assets.singleton import get_assets
from app.game_setup import build_initial_players, deal_hands_and_solution


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
    await deal_hands_and_solution(assets=assets, players=players, rng=rng)

    state = GameState(
        game_id=game_id,
        num_ai_players=num_ai_players,
        num_human_players=num_human_players,
        created_at=now,
        last_updated_at=now,
        seed=seed,
        players=players,
    )

    key = _game_key(game_id)
    r.set(key, state.model_dump_json())
    r.sadd(GAMES_SET_KEY, str(game_id))

    return state


def get_game(*, r: redis.Redis, game_id: UUID) -> GameState | None:
    raw = r.get(_game_key(game_id))
    if not raw:
        return None
    return GameState.model_validate_json(raw)


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
