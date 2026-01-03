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
def client_and_redis() -> Generator[tuple[TestClient, fakeredis.FakeRedis], None, None]:
    r = fakeredis.FakeRedis(decode_responses=True)

    def _override() -> Generator[fakeredis.FakeRedis, None, None]:
        yield r

    app.dependency_overrides[get_redis] = _override
    with TestClient(app) as c:
        yield c, r
    app.dependency_overrides.clear()


def _find_player(data: dict, role: str) -> dict:
    for p in data["players"]:
        if p["role"] == role:
            return p
    raise AssertionError(f"role not found: {role}")


def test_generic_action_endpoint_publishes_mailbox_state_changed(client_and_redis: tuple[TestClient, fakeredis.FakeRedis]) -> None:
    client, r = client_and_redis

    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    # Game creation should enqueue a prompt for the murderer to pick the solution.
    mbox = f"mailbox:{state['game_id']}:{murderer['player_id']}"
    entries0 = r.xrange(mbox)
    assert len(entries0) >= 1
    _, fields0 = entries0[-1]
    assert fields0["type"] == "prompt_murder_pick"

    # Use the typed generic endpoint for murder.
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

    # Every player should have received a state_changed stream message.
    gid = updated["game_id"]
    for p in updated["players"]:
        key = f"mailbox:{gid}:{p['player_id']}"
        entries = r.xrange(key)
        assert len(entries) >= 1
        _, fields = entries[-1]
        assert fields["type"] in {
            "state_changed",
            "murder_solution_chosen",
            "witness_identities_revealed",
            "prompt_fs_scene_pick",
        }

    # Murderer should also have a murder_solution_chosen message.
    m_entries = r.xrange(f"mailbox:{gid}:{murderer['player_id']}")
    assert any(f.get("type") == "murder_solution_chosen" for _, f in m_entries)

    # FS prompt should include the selected clue/means and arrive after secrets.
    fs = _find_player(updated, "forensic_scientist")
    fs_entries = r.xrange(f"mailbox:{gid}:{fs['player_id']}")
    fs_prompt = next((f for _, f in fs_entries if f.get("type") == "prompt_fs_scene_pick"), None)
    assert fs_prompt is not None
    assert fs_prompt.get("clue_id") == body["clue"]
    assert fs_prompt.get("means_id") == body["means"]

    # FS should be restricted to exactly one dealt Location tile card and one Cause-of-Death card.
    assert fs_prompt.get("location_tile")
    assert fs_prompt.get("cause_tile")

    fs_location_ids = [s for s in (fs_prompt.get("location_ids") or "").split(",") if s]
    fs_cause_ids = [s for s in (fs_prompt.get("cause_ids") or "").split(",") if s]
    assert fs_location_ids
    assert fs_cause_ids

    # Should only include one location tile group.
    tiles = {lid.split("__")[0] for lid in fs_location_ids}
    assert len(tiles) == 1
