from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient


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


@pytest.mark.asyncio
async def test_agent_runner_consumes_fs_scene_bullets_prompt_and_submits_action(
    client_and_redis: tuple[TestClient, fakeredis.FakeRedis],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, r = client_and_redis

    # In this test we keep everything AI so the prompt chain can be consumed.
    resp = client.post("/game", json={"num_ai_players": 4, "num_human_players": 0})
    assert resp.status_code == 201
    state = resp.json()

    import app.agent_runner as ar

    murderer = _find_player(state, "murderer")
    fs = _find_player(state, "forensic_scientist")

    async def _fake_pick_solution(*, r, game_id, murderer_id, clue_ids=None, means_ids=None):  # type: ignore[no-untyped-def]
        from uuid import UUID
        from app.game_store import get_game

        s = get_game(r=r, game_id=UUID(game_id))
        assert s is not None
        m = next(p for p in s.players if p.player_id == murderer_id)
        return (clue_ids[0] if clue_ids else m.hand.clue_ids[0], means_ids[0] if means_ids else m.hand.means_ids[0])

    async def _fake_pick_scene(*, r, game_id, fs_id, location_ids=None, cause_ids=None, clue_id=None, means_id=None):  # type: ignore[no-untyped-def]
        # Always pick the first allowed ids.
        assert location_ids and cause_ids
        return location_ids[0], cause_ids[0]

    async def _fake_pick_bullets(*, r, game_id, fs_id, dealt_tiles, options_by_tile):  # type: ignore[no-untyped-def]
        out: dict[str, str] = {}
        for t in dealt_tiles:
            out[t] = options_by_tile[t][0]
        return out

    monkeypatch.setattr(ar, "decide_and_pick_solution_via_llm", _fake_pick_solution)
    monkeypatch.setattr(ar, "decide_and_pick_fs_scene_via_llm", _fake_pick_scene)
    monkeypatch.setattr(ar, "decide_and_pick_fs_scene_bullets_via_llm", _fake_pick_bullets)

    # 1) murder pick
    handled = await ar.run_agent_step(
        r=r,
        game_id=state["game_id"],
        player_id=murderer["player_id"],
        config=ar.AgentRunnerConfig(block_ms=0, count=10),
    )
    assert handled is True

    # 2) fs scene pick
    handled2 = await ar.run_agent_step(
        r=r,
        game_id=state["game_id"],
        player_id=fs["player_id"],
        config=ar.AgentRunnerConfig(block_ms=0, count=10),
    )
    assert handled2 is True

    # 3) fs bullets pick
    handled3 = await ar.run_agent_step(
        r=r,
        game_id=state["game_id"],
        player_id=fs["player_id"],
        config=ar.AgentRunnerConfig(block_ms=0, count=10),
    )
    assert handled3 is True

    resp2 = client.get(f"/game/{state['game_id']}")
    assert resp2.status_code == 200
    updated = resp2.json()
    assert updated["phase"] == "discussion"
    assert updated.get("fs_scene_bullets")
