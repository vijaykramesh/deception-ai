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


def test_mailbox_endpoint_returns_messages(client: TestClient) -> None:
    resp = client.post("/game", json={"num_ai_players": 4, "num_human_players": 0})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    resp2 = client.get(f"/games/{state['game_id']}/players/{murderer['player_id']}/mailbox?count=50")
    assert resp2.status_code == 200
    data = resp2.json()

    assert data["stream"].startswith(f"mailbox:{state['game_id']}")
    assert any(m["fields"].get("type") == "prompt_murder_pick" for m in data["messages"])

