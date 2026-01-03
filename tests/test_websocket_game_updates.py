from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_ws_game_updates_broadcast() -> None:
    with TestClient(app) as client:
        # Create game via REST
        state = client.post("/game", json={"num_ai_players": 4, "num_human_players": 0}).json()
        game_id = state["game_id"]

        with client.websocket_connect(f"/ws/game/{game_id}") as ws:
            # Trigger a state change (discussion comment)
            pid = state["players"][0]["player_id"]
            res = client.post(f"/game/{game_id}/player/{pid}/discuss", json={"comments": "hello"})
            assert res.status_code == 200

            msg = ws.receive_json()
            assert msg["type"] == "game_updated"
            assert msg["game_id"] == game_id

