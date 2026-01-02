from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.context import RenderedContext


@dataclass(frozen=True, slots=True)
class AgentAction:
    kind: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    async def propose_action(self, *, prompt: str, ctx: RenderedContext) -> AgentAction:  # pragma: no cover
        ...

