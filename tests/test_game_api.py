from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_redis
from app.assets.singleton import init_assets
from app.main import app


@pytest.fixture(autouse=True, scope="session")
def _init_assets_for_tests() -> None:
    # Ensure create_game can deal cards.
    init_assets(project_root=Path(__file__).resolve().parents[1])


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


def test_post_game_creates_and_persists_state(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    data = resp.json()

    assert "game_id" in data
    assert data["num_ai_players"] == 3
    assert data["num_human_players"] == 1
    assert data["created_at"]
    assert data["last_updated_at"]
    assert isinstance(data["seed"], int)

    # Roles: total=4 => murderer, forensic_scientist, 2 investigators
    roles = sorted(p["role"] for p in data["players"])
    assert roles.count("murderer") == 1
    assert roles.count("forensic_scientist") == 1
    assert roles.count("investigator") == 2

    fs = _find_player(data, "forensic_scientist")
    murderer = _find_player(data, "murderer")

    # FS has no hand
    assert fs["hand"]["means_ids"] == []
    assert fs["hand"]["clue_ids"] == []

    # Everyone else has 4+4
    for p in data["players"]:
        if p["role"] == "forensic_scientist":
            continue
        assert len(p["hand"]["means_ids"]) == 4
        assert len(p["hand"]["clue_ids"]) == 4

    # Solution exists and must come from murderer's cards
    assert murderer["knows_solution"] is True
    sol = murderer["solution"]
    assert sol is not None
    assert sol["means_id"] == murderer["hand"]["means_ids"][0]
    assert sol["clue_id"] == murderer["hand"]["clue_ids"][0]

    # Only FS + murderer know solution in 4-player game
    for p in data["players"]:
        if p["role"] in {"forensic_scientist", "murderer"}:
            assert p["knows_solution"] is True
            assert p["solution"] is not None
        else:
            assert p["knows_solution"] is False
            assert p["solution"] is None

    # GET by id
    gid = data["game_id"]
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
    sol = murderer["solution"]
    assert sol["means_id"] == murderer["hand"]["means_ids"][0]
    assert sol["clue_id"] == murderer["hand"]["clue_ids"][0]

    for p in data["players"]:
        if p["role"] in {"forensic_scientist", "murderer", "accomplice", "witness"}:
            assert p["knows_solution"] is True
            assert p["solution"] is not None
        else:
            assert p["knows_solution"] is False
            assert p["solution"] is None


def test_post_game_validation(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 1, "num_human_players": 1})
    assert resp.status_code == 422

    resp2 = client.post("/game", json={"num_ai_players": 12, "num_human_players": 1})
    assert resp2.status_code == 422


def test_get_game_404(client: TestClient) -> None:
    resp = client.get("/game/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
