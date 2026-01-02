from __future__ import annotations

from app.core.context import BaseAgentContext, PlayerContext, RoleContext, compose_context


def test_compose_context_includes_layers() -> None:
    base = BaseAgentContext(system_prompt="BASE")
    player = PlayerContext(player_id="p1", display_name="Alice", prompt="PLAYER")
    role = RoleContext(role_name="investigator", prompt="ROLE")

    rendered = compose_context(base=base, player=player, role=role)
    text = rendered.system_prompt

    assert "BASE" in text
    assert "PLAYER CONTEXT" in text
    assert "Alice" in text
    assert "ROLE CONTEXT" in text
    assert "investigator" in text


def test_compose_context_includes_assets_when_present() -> None:
    base = BaseAgentContext(system_prompt="BASE")
    player = PlayerContext(
        player_id="p1",
        display_name="Alice",
        prompt="PLAYER",
        asset_text="Some PDF-derived content",
    )
    role = RoleContext(role_name="witness", prompt="ROLE")

    rendered = compose_context(base=base, player=player, role=role)
    assert "PLAYER ASSETS" in rendered.system_prompt
    assert "Some PDF-derived content" in rendered.system_prompt
