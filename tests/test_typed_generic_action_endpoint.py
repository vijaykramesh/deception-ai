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
    init_assets(project_root=Path(__file__).resolve().parents[1])


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


def test_typed_generic_actions_endpoint_accepts_discriminated_body(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    body = {
        "action": "murder",
        "player_id": murderer["player_id"],
        "clue": murderer["hand"]["clue_ids"][0],
        "means": murderer["hand"]["means_ids"][0],
    }

    resp2 = client.post(f"/games/{state['game_id']}/actions", json=body)
    assert resp2.status_code == 200
    updated = resp2.json()
    assert updated["phase"] == "setup_awaiting_fs_scene_pick"


def test_typed_generic_actions_endpoint_rejects_missing_fields(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    # Missing required fields for murder (clue/means)
    body = {"action": "murder", "player_id": murderer["player_id"]}
    resp2 = client.post(f"/games/{state['game_id']}/actions", json=body)

    # Pydantic validation error
    assert resp2.status_code == 422

