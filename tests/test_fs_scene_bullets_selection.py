import pytest

from app.api.models import GamePhase
from app.assets.singleton import get_assets
from app.game_store import create_game, set_fs_scene_bullets_selection, set_fs_scene_selection, set_murder_solution


def _pick_any_location_and_cause_ids(*, state) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    loc_tile = getattr(state, "fs_location_tile", None)
    cause_tile = getattr(state, "fs_cause_tile", None)
    if not loc_tile or not cause_tile:
        raise RuntimeError("Game state is missing fs_location_tile/fs_cause_tile")

    loc_opt = next(iter(lcd.options_for(loc_tile)), None)
    cause_opt = next(iter(lcd.options_for(cause_tile)), None)
    if not loc_opt or not cause_opt:
        raise RuntimeError("No options found for dealt Location/Cause of Death tiles")

    loc_id = lcd.resolve_id(loc_tile, loc_opt)
    cause_id = lcd.resolve_id(cause_tile, cause_opt)
    if not loc_id or not cause_id:
        raise RuntimeError("Failed to resolve tile option IDs")

    return loc_id, cause_id


def _pick_valid_scene_bullets(*, state) -> dict[str, str]:  # type: ignore[no-untyped-def]
    assets = get_assets()
    scene = assets.scene_tiles
    if len(state.fs_scene_tiles) != 4:
        raise RuntimeError("Expected 4 dealt scene tiles")

    picks: dict[str, str] = {}
    for tile in state.fs_scene_tiles:
        opt = next(iter(scene.options_for(tile)), None)
        if not opt:
            raise RuntimeError(f"No options for dealt scene tile: {tile}")
        picks[tile] = opt

    return picks


@pytest.mark.asyncio
async def test_fs_scene_bullets_selection_happy_path(client_and_redis) -> None:
    _client, r = client_and_redis

    state = await create_game(r=r, num_ai_players=4, num_human_players=0)
    murderer = next(p for p in state.players if p.role == "murderer")

    state = await set_murder_solution(
        r=r,
        game_id=state.game_id,
        player_id=murderer.player_id,
        clue_id=murderer.hand.clue_ids[0],
        means_id=murderer.hand.means_ids[0],
    )

    fs = next(p for p in state.players if p.role == "forensic_scientist")
    loc, cause = _pick_any_location_and_cause_ids(state=state)

    state = await set_fs_scene_selection(
        r=r,
        game_id=state.game_id,
        player_id=fs.player_id,
        location_id=loc,
        cause_id=cause,
    )
    assert state.phase == GamePhase.setup_awaiting_fs_scene_bullets_pick

    picks = _pick_valid_scene_bullets(state=state)

    state = await set_fs_scene_bullets_selection(
        r=r,
        game_id=state.game_id,
        player_id=fs.player_id,
        picks=picks,
    )

    assert state.phase == GamePhase.discussion
    assert state.fs_scene_bullets == picks


@pytest.mark.asyncio
async def test_fs_scene_bullets_selection_rejects_wrong_role(client_and_redis) -> None:
    _client, r = client_and_redis

    state = await create_game(r=r, num_ai_players=4, num_human_players=0)
    murderer = next(p for p in state.players if p.role == "murderer")

    state = await set_murder_solution(
        r=r,
        game_id=state.game_id,
        player_id=murderer.player_id,
        clue_id=murderer.hand.clue_ids[0],
        means_id=murderer.hand.means_ids[0],
    )

    fs = next(p for p in state.players if p.role == "forensic_scientist")
    loc, cause = _pick_any_location_and_cause_ids(state=state)

    state = await set_fs_scene_selection(
        r=r,
        game_id=state.game_id,
        player_id=fs.player_id,
        location_id=loc,
        cause_id=cause,
    )

    picks = _pick_valid_scene_bullets(state=state)
    not_fs = next(p for p in state.players if p.role != "forensic_scientist")

    with pytest.raises(ValueError):
        await set_fs_scene_bullets_selection(
            r=r,
            game_id=state.game_id,
            player_id=not_fs.player_id,
            picks=picks,
        )


@pytest.mark.asyncio
async def test_fs_scene_bullets_selection_rejects_invalid_option(client_and_redis) -> None:
    _client, r = client_and_redis

    state = await create_game(r=r, num_ai_players=4, num_human_players=0)
    murderer = next(p for p in state.players if p.role == "murderer")

    state = await set_murder_solution(
        r=r,
        game_id=state.game_id,
        player_id=murderer.player_id,
        clue_id=murderer.hand.clue_ids[0],
        means_id=murderer.hand.means_ids[0],
    )

    fs = next(p for p in state.players if p.role == "forensic_scientist")
    loc, cause = _pick_any_location_and_cause_ids(state=state)

    state = await set_fs_scene_selection(
        r=r,
        game_id=state.game_id,
        player_id=fs.player_id,
        location_id=loc,
        cause_id=cause,
    )

    picks = _pick_valid_scene_bullets(state=state)
    # Break one tile.
    picks[state.fs_scene_tiles[0]] = "NOT A REAL OPTION"

    with pytest.raises(ValueError):
        await set_fs_scene_bullets_selection(
            r=r,
            game_id=state.game_id,
            player_id=fs.player_id,
            picks=picks,
        )

