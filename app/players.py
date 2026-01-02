from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import Agent
from app.core.context import PlayerContext, RoleContext
from app.roles import RoleName, make_role_context


@dataclass(slots=True)
class PlayerSpec:
    player: PlayerContext
    role: RoleContext
    agent: Agent


def make_player_spec(
    *,
    player_id: str,
    display_name: str,
    agent: Agent,
    role: RoleName | str,
    player_prompt: str = "",
    asset_text: str = "",
) -> PlayerSpec:
    """Create a PlayerSpec with a loaded role prompt.

    This is a convenience helper for wiring up example games/tests.
    """

    player = PlayerContext(
        player_id=player_id,
        display_name=display_name,
        prompt=player_prompt,
        asset_text=asset_text,
    )
    role_ctx = make_role_context(role)
    return PlayerSpec(player=player, role=role_ctx, agent=agent)

