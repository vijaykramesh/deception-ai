from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BaseAgentContext:
    """Global, shared instructions for all agents."""

    system_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlayerContext:
    """Per-player context: player profile + optional asset text."""

    player_id: str
    display_name: str
    prompt: str = ""
    asset_text: str = ""


@dataclass(frozen=True, slots=True)
class RoleContext:
    """Role overlay: private goals, constraints, and secrets."""

    role_name: str
    prompt: str


@dataclass(frozen=True, slots=True)
class RenderedContext:
    """Final, merged context passed into the LLM agent."""

    system_prompt: str

    def as_messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}]


def compose_context(*, base: BaseAgentContext, player: PlayerContext, role: RoleContext) -> RenderedContext:
    parts: list[str] = []
    parts.append(base.system_prompt.strip())

    parts.append(
        "\n".join(
            [
                "PLAYER CONTEXT:",
                f"- player_id: {player.player_id}",
                f"- display_name: {player.display_name}",
                "- player_prompt:",
                player.prompt.strip(),
            ]
        ).strip()
    )

    if player.asset_text.strip():
        parts.append("PLAYER ASSETS (verbatim text):\n" + player.asset_text.strip())

    parts.append(
        "\n".join(
            [
                "ROLE CONTEXT:",
                f"- role: {role.role_name}",
                "- role_prompt:",
                role.prompt.strip(),
            ]
        ).strip()
    )

    system_prompt = "\n\n".join([p for p in parts if p.strip()]).strip()
    return RenderedContext(system_prompt=system_prompt)
