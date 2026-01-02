from __future__ import annotations

from app.core.context import BaseAgentContext
from app.prompts import load_prompt


def make_base_player_context(*, system_prefix: str = "") -> BaseAgentContext:
    """Construct the base shared context for all players.

    The shared context includes the global game rules overview from prompts/base_player.txt.
    You can optionally prepend extra system-level instructions via system_prefix.
    """

    base_rules = load_prompt("base_player.txt")
    parts: list[str] = []
    if system_prefix.strip():
        parts.append(system_prefix.strip())
    parts.append(base_rules.strip())

    return BaseAgentContext(system_prompt="\n\n".join(parts).strip())

