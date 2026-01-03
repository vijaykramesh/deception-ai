from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis

from app.api.models import GamePhase, GameState, Solution
from app.assets.singleton import get_assets
from app.game_setup import apply_solution_and_secrets, build_initial_players, deal_hands


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

    # NOTE: We intentionally do not publish any mailbox prompts here.
    # Setup flow prompts are emitted by the action dispatcher (app/actions.py)
    # to ensure consistent ordering across human + AI actions.

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

    # Allowed options come only from the dealt tile cards.
    # Backwards-compat: if tiles aren't set (older games/tests), allow any valid option ids.
    if state.fs_location_tile:
        allowed_locations = {o.id for o in lcd.by_id.values() if o.tile == state.fs_location_tile}
    else:
        allowed_locations = set(_location_ids_from_assets())

    if state.fs_cause_tile:
        allowed_causes = {o.id for o in lcd.by_id.values() if o.tile == state.fs_cause_tile}
    else:
        allowed_causes = set(_cause_ids_from_assets())

    if location_id not in allowed_locations:
        raise ValueError("location must be a valid option id")
    if cause_id not in allowed_causes:
        raise ValueError("cause must be a valid option id")

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

    # Deal hands (4 means + 4 clues) to everyone except the forensic scientist.
    await deal_hands(assets=get_assets(), players=players, rng=rng)

    # Pre-select which public tile cards the FS will use.
    # We pick exactly one Location tile card and exactly one Cause-of-Death tile card.
    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    location_tiles = sorted([t for t in lcd.by_tile.keys() if t.casefold().startswith("location")])
    cause_tiles = sorted([t for t in lcd.by_tile.keys() if t.casefold().startswith("cause of death")])

    selected_location_tile = rng.choice(location_tiles) if location_tiles else None
    selected_cause_tile = rng.choice(cause_tiles) if cause_tiles else None

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
        fs_location_tile=selected_location_tile,
        fs_cause_tile=selected_cause_tile,
    )

    # redis-py is synchronous. Some IDEs confuse `redis.Redis` with async variants,
    # so we route through getattr to avoid incorrect "coroutine not awaited" diagnostics.
    r_sync: redis.Redis = r  # type: ignore[assignment]

    # --- Option B: cleanup any stale mailbox streams/groups for this game id (persistent Redis).
    # This keeps test/dev runs deterministic without flushing the whole Redis DB.
    try:
        pattern = f"mailbox:{game_id}:*"
        for key in getattr(r_sync, "scan_iter")(match=pattern):
            # key is str with decode_responses=True, bytes otherwise
            skey = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
            # Best-effort destroy consumer group first (if any), then delete stream.
            try:
                getattr(r_sync, "xgroup_destroy")(skey, f"agents:{game_id}")
            except Exception:
                pass
            try:
                getattr(r_sync, "delete")(skey)
            except Exception:
                pass
    except Exception:
        # Swallow cleanup errors; game creation must still work.
        pass

    key = _game_key(game_id)
    getattr(r_sync, "set")(key, state.model_dump_json())
    getattr(r_sync, "sadd")(GAMES_SET_KEY, str(game_id))

    # Kick off setup for callers that don't go through the API layer (e.g. integration tests)
    # by publishing the initial murderer prompt.
    from app.actions import enqueue_setup_prompts_on_create
    from app.streams import publish_many

    publish_many(r=r_sync, entries=enqueue_setup_prompts_on_create(state=state))

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
