from __future__ import annotations

from app.prompts import load_prompt


def test_load_base_player_prompt() -> None:
    text = load_prompt("base_player.txt")
    assert "Deception" in text
    assert "Forensic Scientist" in text

