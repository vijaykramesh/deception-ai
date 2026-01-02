from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autogen import ConversableAgent

from app.agents.autogen_config import llm_config_from_env
from app.agents.base import AgentAction
from app.agents.json_schema import JsonSchema
from app.core.context import RenderedContext


def _extract_last_content(messages: object) -> str:
    """Extract the last message content from AG2 chat history."""

    if not isinstance(messages, list):
        return ""

    for msg in reversed(messages):
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


@dataclass(slots=True)
class Ag2ChatAgent:
    """AG2 agent wrapper using the documented `autogen` API.

    This wrapper is intentionally small:
    - Context stacking is handled by our code (RenderedContext).
    - LLM transport/config is handled by AG2 (`autogen`).

    Environment variables supported:
    - OPENAI_MODEL
    - OPENAI_API_KEY (optional if OPENAI_BASE_URL is set)
    - OPENAI_BASE_URL (for OpenAI-compatible servers like Ollama, e.g. http://127.0.0.1:11434/v1)
    """

    name: str
    model: str

    async def propose_action(
        self,
        *,
        prompt: str,
        ctx: RenderedContext,
        structured_output: JsonSchema | None = None,
    ) -> AgentAction:
        """Send a prompt using the stacked system context.

        If structured_output is provided, we attempt to request OpenAI-style structured JSON output.
        (Ollama gpt-oss:20b supports this.)
        """

        llm_config = llm_config_from_env(default_model=self.model)

        agent = ConversableAgent(
            name=self.name,
            system_message=ctx.system_prompt,
            llm_config=llm_config,
            human_input_mode="NEVER",
        )

        # OpenAI-style structured outputs: pass response_format in the message config.
        # AG2 will forward unknown kwargs through to the OpenAI client.
        extra: dict[str, Any] = {}
        if structured_output is not None:
            extra["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structured_output.name,
                    "schema": structured_output.schema,
                    "strict": structured_output.strict,
                },
            }

        result = agent.run(message=prompt, max_turns=1, **extra)
        result.process()

        text = _extract_last_content(list(result.messages))
        if not text:
            # Fallback: attempt to use summary if provided.
            summary = result.summary
            if isinstance(summary, str):
                text = summary.strip()

        return AgentAction(kind="chat", content=text, metadata={"model": self.model, **({"structured": True} if structured_output else {})})
