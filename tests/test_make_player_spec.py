from __future__ import annotations

from app.agents.base import Agent, AgentAction
from app.core.context import RenderedContext
from app.players import make_player_spec


class _DummyAgent(Agent):
    name = "dummy"

    async def propose_action(self, *, prompt: str, ctx: RenderedContext) -> AgentAction:
        return AgentAction(kind="noop", content="ok", metadata={})


def test_make_player_spec_loads_role_prompt() -> None:
    spec = make_player_spec(
        player_id="p1",
        display_name="Alice",
        agent=_DummyAgent(),
        role="investigator",
        player_prompt="Hello",
    )

    assert spec.player.display_name == "Alice"
    assert spec.role.role_name == "investigator"
    assert spec.role.prompt.strip()
