from __future__ import annotations

import os

import httpx
import pytest

from app.agent_runner import AgentRunnerConfig, run_game_agents_once
from app.api.models import GamePhase
from app.game_store import create_game, get_game


def _ollama_ready() -> bool:
    base = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL")
    if not base or not model:
        return False

    # quick reachability probe (matches other env-gated tests)
    try:
        httpx.get(base.rstrip("/") + "/models", timeout=1.5)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_agent_runner_ollama_env_gated() -> None:
    """Integration test: agent runner consumes setup prompts and uses an LLM to progress setup.

    This test expects setup to progress in three discrete steps (one agent-run per step):
      1) Murderer picks the solution -> phase becomes `setup_awaiting_fs_scene_pick`.
      2) Forensic Scientist (FS) picks scene (location + cause) -> phase becomes
         `setup_awaiting_fs_scene_bullets_pick`.
      3) FS picks bullets -> phase becomes `discussion`.

    Required env vars (example for Ollama):
      - OPENAI_BASE_URL=http://127.0.0.1:11434/v1
      - OPENAI_MODEL=gpt-oss:20b
      - OPENAI_API_KEY=ollama
    """

    if not _ollama_ready():
        pytest.skip("Ollama not reachable or missing OPENAI_BASE_URL/OPENAI_MODEL")

    import redis

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

    # Create 4 AI players so murderer + FS are AI.
    state = await create_game(r=r, num_ai_players=4, num_human_players=0)

    cfg = AgentRunnerConfig(block_ms=100, count=10)

    # Run once: murderer should pick and move phase to awaiting FS scene pick.
    handled = await run_game_agents_once(r=r, game_id=str(state.game_id), config=cfg)
    assert handled is True

    updated = get_game(r=r, game_id=state.game_id)
    assert updated is not None
    assert updated.solution is not None
    assert updated.phase == GamePhase.setup_awaiting_fs_scene_pick

    # Run again: FS should pick and move to awaiting bullets pick.
    handled2 = await run_game_agents_once(r=r, game_id=str(state.game_id), config=cfg)
    assert handled2 is True

    updated2 = get_game(r=r, game_id=state.game_id)
    assert updated2 is not None
    assert updated2.phase == GamePhase.setup_awaiting_fs_scene_bullets_pick
    assert updated2.fs_location_id is not None
    assert updated2.fs_cause_id is not None

    # Run again: FS should pick bullets and move to discussion.
    handled3 = await run_game_agents_once(r=r, game_id=str(state.game_id), config=cfg)
    assert handled3 is True

    updated3 = get_game(r=r, game_id=state.game_id)
    assert updated3 is not None
    assert updated3.phase == GamePhase.discussion
