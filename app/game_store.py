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


def _location_ids_from_assets() -> list[str]:
    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    # Real datasets often have multiple location tiles (e.g., "Location 1", "Location 2", ...).
    # We treat any tile whose canonical name starts with "Location" as a valid Location tile.
    location_tiles = [t for t in lcd.by_tile.keys() if t.casefold().startswith("location")]

    ids: list[str] = []
    for tile in sorted(location_tiles):
        allowed_options = set(lcd.options_for(tile))
        ids.extend([o.id for o in lcd.by_id.values() if o.tile == tile and o.option in allowed_options])

    # Stable order for determinism.
    return sorted(set(ids))


def _cause_ids_from_assets() -> list[str]:
    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    # Some datasets may have multiple cause tiles too (e.g., "Cause of Death 1").
    cause_tiles = [t for t in lcd.by_tile.keys() if t.casefold().startswith("cause of death")]

    ids: list[str] = []
    for tile in sorted(cause_tiles):
        allowed_options = set(lcd.options_for(tile))
        ids.extend([o.id for o in lcd.by_id.values() if o.tile == tile and o.option in allowed_options])

    return sorted(set(ids))


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

    # Next: Forensic Scientist selects the (public) Location + Cause-of-Death tiles.
    state.phase = GamePhase.setup_awaiting_fs_scene_pick

    save_game(r=r, state=state)

    # Enqueue prompt to the FS (AI FS can act on this via agent_runner).
    fs = next((p for p in state.players if p.role == "forensic_scientist"), None)
    if fs is not None:
        location_ids = _location_ids_from_assets()
        cause_ids = _cause_ids_from_assets()

        publish_to_mailbox(
            r=r,
            mailbox=Mailbox(game_id=str(game_id), player_id=fs.player_id),
            fields={
                "type": "prompt_fs_scene_pick",
                "game_id": str(game_id),
                "player_id": fs.player_id,
                "phase": state.phase.value,
                "location_ids": ",".join(location_ids),
                "cause_ids": ",".join(cause_ids),
            },
        )

    return state


async def set_fs_scene_selection(
    *,
    r: redis.Redis,
    game_id: UUID,
    player_id: str,
    location_id: str,
    cause_id: str,
) -> GameState:
    state = require_game(r=r, game_id=game_id)
    pidx = require_player(state=state, player_id=player_id)
    player = state.players[pidx]

    if state.phase != GamePhase.setup_awaiting_fs_scene_pick:
        raise ValueError("Game is not awaiting forensic scientist scene selection")

    if player.role != "forensic_scientist":
        raise ValueError("Only the forensic scientist can set the scene selection")

    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    allowed_locations = set(_location_ids_from_assets())
    allowed_causes = set(_cause_ids_from_assets())

    if location_id not in allowed_locations:
        raise ValueError("location must be a valid Location tile option id")
    if cause_id not in allowed_causes:
        raise ValueError("cause must be a valid Cause of Death tile option id")

    state.fs_location_id = location_id
    state.fs_cause_id = cause_id

    # After scene selection, the table discussion begins.
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
        fs_location_id=None,
        fs_cause_id=None,
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
