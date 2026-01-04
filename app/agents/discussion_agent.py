from __future__ import annotations

import json
from typing import Any, cast

from app.agents.base import Agent
from app.agents.json_schema import JsonSchema
from app.core.context import RenderedContext


DISCUSSION_RESPONSE_SCHEMA = JsonSchema(
    name="discussion_response",
    schema={
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "A few sentences of discussion: observation, suggestion, or question.",
                "minLength": 1,
                "maxLength": 2000,
            }
        },
        "required": ["response"],
        "additionalProperties": False,
    },
    strict=True,
)


async def propose_discussion_with_agent(*, agent: Agent, ctx: RenderedContext, prompt: str) -> str:
    """Ask an agent for a discussion message and return the text.

    Uses structured outputs when possible; falls back to best-effort parsing.
    """

    # Agent Protocol doesn't declare structured_output, but our default agent supports it.
    agent_any = cast(Any, agent)
    if "structured_output" in getattr(agent_any.propose_action, "__code__").co_varnames:  # type: ignore[attr-defined]
        action = await agent_any.propose_action(prompt=prompt, ctx=ctx, structured_output=DISCUSSION_RESPONSE_SCHEMA)
    else:
        action = await agent_any.propose_action(prompt=prompt, ctx=ctx)

    # Preferred: strict JSON string.
    try:
        parsed = json.loads(action.content)
        if isinstance(parsed, dict):
            resp = parsed.get("response")
            if isinstance(resp, str) and resp.strip():
                return resp.strip()
    except Exception:
        pass

    # Fallback: treat raw content as the response.
    return action.content.strip()
