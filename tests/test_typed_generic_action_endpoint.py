from __future__ import annotations

import pytest

from fastapi.testclient import TestClient


def _find_player(data: dict, role: str) -> dict:
    for p in data["players"]:
        if p["role"] == role:
            return p
    raise AssertionError(f"role not found: {role}")


def test_typed_generic_actions_endpoint_accepts_discriminated_body(client_and_redis) -> None:
    client, _r = client_and_redis

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


def test_typed_generic_actions_endpoint_rejects_missing_fields(client_and_redis) -> None:
    client, _r = client_and_redis

    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    # Missing required fields for murder (clue/means)
    body = {"action": "murder", "player_id": murderer["player_id"]}
    resp2 = client.post(f"/games/{state['game_id']}/actions", json=body)

    # Pydantic validation error
    assert resp2.status_code == 422

