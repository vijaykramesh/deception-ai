from __future__ import annotations

import os

import httpx
import pytest

from app.agents.ag2_backend import Ag2ChatAgent
from app.core.context import BaseAgentContext, PlayerContext, RoleContext, compose_context


def _ollama_healthy(base_url: str) -> bool:
    # base_url might be http://127.0.0.1:11434/v1
    root = base_url.removesuffix("/v1")
    try:
        r = httpx.get(f"{root}/api/tags", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_ag2_layers_integration_env_gated() -> None:
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    if not (api_key or base_url):
        pytest.skip("Set OPENAI_API_KEY or OPENAI_BASE_URL")

    if base_url and not _ollama_healthy(base_url):
        pytest.skip("Ollama not reachable at OPENAI_BASE_URL")

    base = BaseAgentContext(
        system_prompt=(
            "You are a helpful assistant. Always respond with exactly one line of plain text."
        )
    )

    player = PlayerContext(
        player_id="p1",
        display_name="Alice",
        prompt="If asked for a color, answer 'blue'.",
    )

    role = RoleContext(
        role_name="witness",
        prompt="If asked for a color, override and answer 'green'.",
    )

    ctx = compose_context(base=base, player=player, role=role)
    agent = Ag2ChatAgent(name="ag2-test", model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))

    action = await agent.propose_action(prompt="What color should you answer with?", ctx=ctx)
    assert action.content

    lowered = action.content.lower()
    assert ("green" in lowered) or ("blue" in lowered)
