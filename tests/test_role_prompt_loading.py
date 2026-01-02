from __future__ import annotations

from app.contexts import make_base_player_context
from app.core.context import PlayerContext, compose_context
from app.roles import RoleName, make_role_context


def test_load_player_with_investigator_role_prompt() -> None:
    base = make_base_player_context(system_prefix="SYSTEM")

    player = PlayerContext(
        player_id="p1",
        display_name="Alice",
        prompt="You are playing as Alice.",
    )

    role = make_role_context(RoleName.investigator)

    rendered = compose_context(base=base, player=player, role=role)
    sys_prompt = rendered.system_prompt

    # Base rules are present
    assert "Deception" in sys_prompt
    assert "Forensic Scientist" in sys_prompt

    # Role prompt is present
    assert "You are an Investigator" in sys_prompt
    assert "You do not know the solution" in sys_prompt

    # The role name and player name are still injected structurally
    assert "role: investigator" in sys_prompt
    assert "Alice" in sys_prompt

