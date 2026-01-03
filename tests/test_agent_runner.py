from __future__ import annotations

from collections.abc import Generator

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_redis
from app.main import app


def _find_player(data: dict, role: str) -> dict:
    for p in data["players"]:
        if p["role"] == role:
            return p
    raise AssertionError(f"role not found: {role}")


@pytest.mark.asyncio
async def test_agent_runner_consumes_prompt_and_submits_murder_action(
    client_and_redis: tuple[TestClient, fakeredis.FakeRedis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, r = client_and_redis

    # Create a game with at least one AI player.
    resp = client.post("/game", json={"num_ai_players": 3, "num_human_players": 1})
    assert resp.status_code == 201
    state = resp.json()

    murderer = _find_player(state, "murderer")

    # Stub LLM decision to pick first cards.
    import app.agent_runner as ar

    async def _fake_pick(*, r, game_id, murderer_id, clue_ids=None, means_ids=None):  # type: ignore[no-untyped-def]
        from uuid import UUID
        from app.game_store import get_game

        s = get_game(r=r, game_id=UUID(game_id))
        assert s is not None
        m = next(p for p in s.players if p.player_id == murderer_id)
        # If caller provided allowed lists, respect them.
        if clue_ids:
            c = clue_ids[0]
        else:
            c = m.hand.clue_ids[0]
        if means_ids:
            me = means_ids[0]
        else:
            me = m.hand.means_ids[0]
        return c, me

    monkeypatch.setattr(ar, "decide_and_pick_solution_via_llm", _fake_pick)

    # Run agent step for the murderer (note: murderer might be human in random role assignment).
    # If murderer is human, pick an AI murderer game by forcing all players to AI.
    if not murderer["is_ai"]:
        resp2 = client.post("/game", json={"num_ai_players": 4, "num_human_players": 0})
        assert resp2.status_code == 201
        state = resp2.json()
        murderer = _find_player(state, "murderer")
        assert murderer["is_ai"] is True

    handled = await ar.run_agent_step(r=r, game_id=state["game_id"], player_id=murderer["player_id"], config=ar.AgentRunnerConfig(block_ms=0, count=10))
    assert handled is True

    # Game should now be awaiting forensic scientist scene pick.
    resp3 = client.get(f"/game/{state['game_id']}")
    assert resp3.status_code == 200
    updated = resp3.json()
    assert updated["phase"] == "setup_awaiting_fs_scene_pick"
    assert updated["solution"] is not None
