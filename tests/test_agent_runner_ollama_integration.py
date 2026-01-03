from __future__ import annotations

import os

import pytest

from app.agent_runner import AgentRunnerConfig, run_game_agents_once
from app.api.models import GamePhase
from app.assets.singleton import init_assets
from app.game_store import create_game, get_game


def _ollama_ready() -> bool:
    # Same gating as other integration tests
    return bool(os.environ.get("OPENAI_BASE_URL") and os.environ.get("OPENAI_MODEL"))


@pytest.mark.asyncio
async def test_agent_runner_ollama_env_gated() -> None:
    """Integration test: agent runner consumes prompt_murder_pick and uses LLM to pick.

    Required env vars (example for Ollama):
      - OPENAI_BASE_URL=http://127.0.0.1:11434/v1
      - OPENAI_MODEL=gpt-oss:20b
      - OPENAI_API_KEY=ollama
    """

    if not _ollama_ready():
        pytest.skip("Missing OPENAI_BASE_URL/OPENAI_MODEL")

    import redis

    init_assets(project_root=__import__("pathlib").Path(__file__).resolve().parents[1])

    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

    # Create 4 AI players so murderer is AI.
    state = await create_game(r=r, num_ai_players=4, num_human_players=0)

    # Run the agents once; murderer should pick and move phase to FS scene pick.
    handled = await run_game_agents_once(r=r, game_id=str(state.game_id), config=AgentRunnerConfig(block_ms=100, count=10))
    assert handled is True

    updated = get_game(r=r, game_id=state.game_id)
    assert updated is not None
    assert updated.phase == GamePhase.setup_awaiting_fs_scene_pick
    assert updated.solution is not None

