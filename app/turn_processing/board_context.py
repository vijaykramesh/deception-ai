from __future__ import annotations

from app.api.models import GameState
from app.assets.registry import GameAssets
from app.core.game_state_text import game_state_to_paragraph


def _pov_for_role(role: str) -> str:
    # POV values expected by `game_state_to_paragraph`.
    if role == "forensic_scientist":
        return "fs"
    if role == "murderer":
        return "murderer"
    if role == "accomplice":
        return "accomplice"
    if role == "witness":
        return "witness"
    return "investigator"


def _scene_bullets_section(*, state: GameState, assets: GameAssets) -> str:
    if not state.fs_scene_tiles:
        return "SCENE TILES: (not dealt yet)"

    lines: list[str] = ["SCENE TILES (public):"]

    for idx, tile in enumerate(state.fs_scene_tiles, start=1):
        picked = state.fs_scene_bullets.get(tile)
        if picked:
            # picked is an option name (not id) for Scene tiles.
            lines.append(f"{idx}. {tile} -> bullet: '{picked}'")
        else:
            # Provide available options to avoid agents inventing options.
            opts = list(assets.scene_tiles.options_for(tile))
            if opts:
                lines.append(f"{idx}. {tile} -> bullet: (not selected yet); options={opts}")
            else:
                lines.append(f"{idx}. {tile} -> bullet: (not selected yet)")

    return "\n".join(lines).strip()


def visible_board_context(*, state: GameState, viewer_player_id: str, assets: GameAssets) -> str:
    """Return a role-scoped board summary plus discussion history.

    This is intended for LLM prompts and redacts hidden information based on role.
    """

    viewer = next((p for p in state.players if p.player_id == viewer_player_id), None)
    role = viewer.role if viewer is not None else "investigator"

    pov = _pov_for_role(role)
    board = game_state_to_paragraph(state=state, assets=assets, pov=pov, viewer_player_id=viewer_player_id)
    bullets = _scene_bullets_section(state=state, assets=assets)

    if state.discussion:
        history_lines = [
            f"{c.seq}. {c.player_id}: {c.comments.strip()}" for c in state.discussion if c.comments.strip()
        ]
        history = "\n".join(history_lines)
    else:
        history = "(no discussion yet)"

    return "\n\n".join(
        [
            "BOARD CONTEXT (visible to you):",
            board.strip(),
            bullets.strip(),
            "DISCUSSION HISTORY (chronological):",
            history.strip(),
        ]
    ).strip()
