from __future__ import annotations

from uuid import UUID

import redis

from app.api.models import GameState
from app.game_store import require_game, require_player, save_game


def current_turn_player_id(*, state: GameState) -> str:
    """Return which player_id should act next during the discussion phase.

    Policy (simple + deterministic): round-robin by seat, derived from how many
    discussion comments exist so far. Each discussion comment advances the turn.

    This is intentionally minimal scaffolding until we add an explicit turn pointer.
    """

    if not state.players:
        raise ValueError("No players")

    ordered = sorted(state.players, key=lambda p: p.seat)
    idx = len(state.discussion) % len(ordered)
    return ordered[idx].player_id


def assert_is_players_turn(*, state: GameState, player_id: str) -> None:
    expected = current_turn_player_id(state=state)
    if player_id != expected:
        raise ValueError(f"Not your turn (expected player_id={expected})")


def advance_turn_after_discuss(*, r: redis.Redis, game_id: UUID, player_id: str) -> None:
    """Placeholder hook for future explicit turn state.

    Today, turn order is derived from discussion length, so no state mutation is needed.
    This function exists so callers can evolve without touching action handlers.
    """

    state = require_game(r=r, game_id=game_id)
    require_player(state=state, player_id=player_id)
    save_game(r=r, state=state)
