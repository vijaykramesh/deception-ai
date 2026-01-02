from __future__ import annotations

import os
from typing import cast

import httpx
import pytest

from app.agents.ag2_backend import Ag2ChatAgent
from app.agents.base import Agent
from app.agents.solution_picker import pick_solution_with_agent
from app.core.context import RenderedContext


def _ollama_ready() -> bool:
    base = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL")
    if not base or not model:
        return False

    # quick reachability probe
    try:
        httpx.get(base.rstrip("/") + "/models", timeout=1.5)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_ollama_structured_output_pick_solution_env_gated() -> None:
    """Integration test: verify Ollama (OpenAI-compatible) can return schema-constrained JSON.

    Required env vars:
      - OPENAI_BASE_URL=http://127.0.0.1:11434/v1
      - OPENAI_MODEL=gpt-oss:20b
      - OPENAI_API_KEY=ollama (or anything; Ollama ignores but SDK may require)
    """

    if not _ollama_ready():
        pytest.skip("Ollama not reachable or missing OPENAI_BASE_URL/OPENAI_MODEL")

    # Use real IDs from our CSVs.
    clue_ids = ["blood"]
    means_ids = ["axe"]

    ctx = RenderedContext(
        system_prompt=(
            "You must follow instructions exactly. "
            "When asked for JSON, output only JSON and nothing else."
        )
    )

    agent = cast(Agent, cast(object, Ag2ChatAgent(name="ollama-structured-test", model=os.environ.get("OPENAI_MODEL", "gpt-oss:20b"))))

    picked = await pick_solution_with_agent(agent=agent, ctx=ctx, clue_ids=clue_ids, means_ids=means_ids)
    assert picked.clue == "blood"
    assert picked.means == "axe"
