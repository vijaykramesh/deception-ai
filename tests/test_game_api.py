from __future__ import annotations

from collections.abc import Generator

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_redis
from app.main import app



@pytest.fixture(autouse=True)
def _stub_solution_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force choose_solution_from_murderer_via_llm to pick the first means/clue in the murderer's hand.
    import app.game_setup as gs

    async def _fake_choose_solution_from_murderer_via_llm(*, players, rng):  # type: ignore[no-untyped-def]
        murderer = next(p for p in players if p.role == "murderer")
        return gs.Solution(means_id=murderer.hand.means_ids[0], clue_id=murderer.hand.clue_ids[0])

    monkeypatch.setattr(gs, "choose_solution_from_murderer_via_llm", _fake_choose_solution_from_murderer_via_llm)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    r = fakeredis.FakeRedis(decode_responses=True)

    def _override() -> Generator[fakeredis.FakeRedis, None, None]:
        yield r

    app.dependency_overrides[get_redis] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _find_player(data: dict, role: str) -> dict:
    for p in data["players"]:
        if p["role"] == role:
            return p
    raise AssertionError(f"role not found: {role}")


def _pick_any_location_and_cause_ids(*, data: dict | None = None) -> tuple[str, str]:
    """Pick valid location/cause option ids.

    If `data` contains `fs_location_tile/fs_cause_tile` (returned by the API),
    pick options from those dealt tile cards. Otherwise fall back to the first
    location/cause tiles in the assets (legacy behavior).
    """

    from app.assets.singleton import get_assets

    assets = get_assets()
    lcd = assets.location_and_cause_of_death_tiles

    loc_tiles = sorted([t for t in lcd.by_tile.keys() if t.casefold().startswith("location")])
    cause_tiles = sorted([t for t in lcd.by_tile.keys() if t.casefold().startswith("cause of death")])

    if not loc_tiles or not cause_tiles:
        raise RuntimeError("Missing Location/Cause of Death tiles in assets")

    loc_tile = None
    cause_tile = None
    if data is not None:
        loc_tile = data.get("fs_location_tile")
        cause_tile = data.get("fs_cause_tile")

    # Fallback to deterministic tiles if API/game state doesn't expose dealt tiles.
    if not isinstance(loc_tile, str) or not loc_tile:
        loc_tile = loc_tiles[0]
    if not isinstance(cause_tile, str) or not cause_tile:
        cause_tile = cause_tiles[0]

    loc_opt = next(iter(lcd.options_for(loc_tile)), None)
    cause_opt = next(iter(lcd.options_for(cause_tile)), None)
    if not loc_opt or not cause_opt:
        raise RuntimeError("No options found for Location/Cause of Death tiles")

    loc_id = lcd.resolve_id(loc_tile, loc_opt)
    cause_id = lcd.resolve_id(cause_tile, cause_opt)
    if not loc_id or not cause_id:
        raise RuntimeError("Failed to resolve tile option IDs")

    return loc_id, cause_id


def test_post_game_creates_and_persists_state(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    data = resp.json()

    # New flow: game starts awaiting murderer pick.
    assert data["phase"] == "setup_awaiting_murder_pick"
    assert data["solution"] is None

    murderer = _find_player(data, "murderer")

    # Murderer submits the hidden solution (must come from their hand)
    pick = {"clue": murderer["hand"]["clue_ids"][0], "means": murderer["hand"]["means_ids"][0]}
    resp_pick = client.post(f"/game/{data['game_id']}/player/{murderer['player_id']}/murder", json=pick)
    assert resp_pick.status_code == 200
    data2 = resp_pick.json()

    assert data2["phase"] == "setup_awaiting_fs_scene_pick"
    assert data2["solution"] == {"clue_id": pick["clue"], "means_id": pick["means"]}

    # FS submits the public scene selection (location + cause of death)
    loc, cause = _pick_any_location_and_cause_ids(data=data2)

    fs_player = _find_player(data2, "forensic_scientist")
    resp_scene = client.post(
        f"/game/{data2['game_id']}/player/{fs_player['player_id']}/fs_scene",
        json={"location": loc, "cause": cause},
    )
    assert resp_scene.status_code == 200
    data2b = resp_scene.json()

    assert data2b["phase"] == "discussion"
    assert data2b["fs_location_id"] == loc
    assert data2b["fs_cause_id"] == cause

    fs = _find_player(data2b, "forensic_scientist")
    murderer2 = _find_player(data2b, "murderer")

    # FS + murderer know solution.
    assert fs["knows_solution"] is True
    assert fs["solution"] is not None
    assert murderer2["knows_solution"] is True
    assert murderer2["solution"] is not None

    # No witness/accomplice in 4-player game.
    for p in data2b["players"]:
        assert p["knows_identities"] is False
        assert p["known_murderer_id"] is None
        assert p["known_accomplice_id"] is None

    # Discuss
    inv = _find_player(data2b, "investigator")
    resp_discuss = client.post(f"/game/{data2b['game_id']}/player/{inv['player_id']}/discuss", json={"comments": "Hello"})
    assert resp_discuss.status_code == 200
    data3 = resp_discuss.json()
    assert data3["discussion"][0]["seq"] == 1
    assert data3["discussion"][0]["player_id"] == inv["player_id"]
    assert data3["discussion"][0]["comments"] == "Hello"

    # Wrong solve: lose badge.
    wrong = {"murderer": "p999", "clue": "nope", "means": "nope"}
    resp_solve = client.post(f"/game/{data2b['game_id']}/player/{inv['player_id']}/solve", json=wrong)
    assert resp_solve.status_code == 200
    data4 = resp_solve.json()
    inv2 = next(p for p in data4["players"] if p["player_id"] == inv["player_id"])
    assert inv2["has_badge"] is False
    assert data4["phase"] == "discussion"

    # Second solve attempt should be rejected.
    resp_solve2 = client.post(f"/game/{data2b['game_id']}/player/{inv['player_id']}/solve", json=wrong)
    assert resp_solve2.status_code == 422

    # GET by id
    gid = data2b["game_id"]
    resp2 = client.get(f"/game/{gid}")
    assert resp2.status_code == 200
    assert resp2.json()["game_id"] == gid

    # List includes it
    resp3 = client.get("/game")
    assert resp3.status_code == 200
    games = resp3.json()["games"]
    assert len(games) == 1
    assert games[0]["game_id"] == gid


def test_post_game_roles_with_witness_and_accomplice(client: TestClient) -> None:
    # total=6 => includes accomplice + witness
    resp = client.post("/game", json={"num_ai_players": 4, "num_human_players": 2})
    assert resp.status_code == 201
    data = resp.json()

    roles = sorted(p["role"] for p in data["players"])
    assert roles.count("murderer") == 1
    assert roles.count("forensic_scientist") == 1
    assert roles.count("accomplice") == 1
    assert roles.count("witness") == 1
    assert roles.count("investigator") == 2

    murderer = _find_player(data, "murderer")
    pick = {"clue": murderer["hand"]["clue_ids"][0], "means": murderer["hand"]["means_ids"][0]}
    resp_pick = client.post(f"/game/{data['game_id']}/player/{murderer['player_id']}/murder", json=pick)
    assert resp_pick.status_code == 200
    data2 = resp_pick.json()

    accomplice = _find_player(data2, "accomplice")
    witness = _find_player(data2, "witness")

    # Accomplice knows solution
    assert accomplice["knows_solution"] is True
    assert accomplice["solution"] is not None

    # Witness knows identities but not solution
    assert witness["knows_solution"] is False
    assert witness["solution"] is None
    assert witness["knows_identities"] is True
    assert witness["known_murderer_id"] == murderer["player_id"]
    assert witness["known_accomplice_id"] == accomplice["player_id"]

    # Need FS scene selection before solving.
    loc, cause = _pick_any_location_and_cause_ids(data=data2)

    fs_player = _find_player(data2, "forensic_scientist")
    resp_scene = client.post(
        f"/game/{data2['game_id']}/player/{fs_player['player_id']}/fs_scene",
        json={"location": loc, "cause": cause},
    )
    assert resp_scene.status_code == 200
    data2b = resp_scene.json()
    assert data2b["phase"] == "discussion"

    # Correct solve ends game
    inv = _find_player(data2b, "investigator")
    correct = {"murderer": murderer["player_id"], "clue": pick["clue"], "means": pick["means"]}
    resp_solve = client.post(f"/game/{data2b['game_id']}/player/{inv['player_id']}/solve", json=correct)
    assert resp_solve.status_code == 200
    done = resp_solve.json()
    assert done["phase"] == "completed"
    assert done["winning_investigator_id"] == inv["player_id"]


def test_post_game_validation(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 1, "num_human_players": 1})
    assert resp.status_code == 422

    resp2 = client.post("/game", json={"num_ai_players": 12, "num_human_players": 1})
    assert resp2.status_code == 422


def test_get_game_404(client: TestClient) -> None:
    resp = client.get("/game/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
