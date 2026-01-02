from __future__ import annotations

import os
from typing import cast

from app.agents.ag2_backend import Ag2ChatAgent
from app.agents.base import Agent


def create_default_agent(*, name: str) -> Agent:
    """Create the default LLM-backed agent.

    Currently uses AG2/autogen and reads model configuration from env.
    """

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return cast(Agent, Ag2ChatAgent(name=name, model=model))
