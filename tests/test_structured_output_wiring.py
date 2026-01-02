from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import AgentAction
from app.agents.json_schema import JsonSchema
from app.agents.solution_picker import pick_solution_with_agent
from app.core.context import RenderedContext


@dataclass
class _StructuredCapAgent:
    name: str = "cap"
    seen_schema: JsonSchema | None = None

    async def propose_action(self, *, prompt: str, ctx: RenderedContext, structured_output: JsonSchema | None = None) -> AgentAction:  # type: ignore[override]
        self.seen_schema = structured_output
        return AgentAction(kind="chat", content='{"clue":"c1","means":"m1"}', metadata={})


async def test_solution_picker_passes_schema_when_supported() -> None:
    a = _StructuredCapAgent()
    ctx = RenderedContext(system_prompt="x")
    picked = await pick_solution_with_agent(agent=a, ctx=ctx, clue_ids=["c1"], means_ids=["m1"])
    assert picked.clue == "c1"
    assert picked.means == "m1"
    assert a.seen_schema is not None
    assert a.seen_schema.name == "pick_solution"

