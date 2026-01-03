import pytest

from app.api.models import GamePhase
from app.assets.singleton import get_assets
from app.game_store import create_game, set_fs_scene_selection, set_murder_solution


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


@pytest.mark.asyncio
async def test_fs_scene_selection_happy_path(client_and_redis) -> None:
    _client, r = client_and_redis

    state = await create_game(r=r, num_ai_players=4, num_human_players=0)
    murderer = next(p for p in state.players if p.role == "murderer")

    # murder pick
    state = await set_murder_solution(
        r=r,
        game_id=state.game_id,
        player_id=murderer.player_id,
        clue_id=murderer.hand.clue_ids[0],
        means_id=murderer.hand.means_ids[0],
    )
    assert state.phase == GamePhase.setup_awaiting_fs_scene_pick

    fs = next(p for p in state.players if p.role == "forensic_scientist")
    loc, cause = _pick_any_location_and_cause_ids(state=state)

    state = await set_fs_scene_selection(
        r=r,
        game_id=state.game_id,
        player_id=fs.player_id,
        location_id=loc,
        cause_id=cause,
    )

    assert state.phase == GamePhase.discussion
    assert state.fs_location_id == loc
    assert state.fs_cause_id == cause


@pytest.mark.asyncio
async def test_fs_scene_selection_wrong_role_rejected(client_and_redis) -> None:
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

    loc, cause = _pick_any_location_and_cause_ids(state=state)
    not_fs = next(p for p in state.players if p.role != "forensic_scientist")

    with pytest.raises(ValueError):
        await set_fs_scene_selection(
            r=r,
            game_id=state.game_id,
            player_id=not_fs.player_id,
            location_id=loc,
            cause_id=cause,
        )
