from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.api.models import GamePhase, GameState, PlayerHand, PlayerState, Solution
from app.turn_processing.board_context import visible_board_context


class _Cards:
    def __init__(self, mapping: dict[str, str]):
        self._m = mapping

    def get(self, k: str):
        name = self._m.get(k)
        if name is None:
            return None
        return type("_Card", (), {"name": name})


class _LCD:
    def get(self, k: str):
        return type("_Opt", (), {"option": k})


class _SceneTiles:
    def options_for(self, tile: str):
        return ("opt1", "opt2")


class _Assets:
    def __init__(self):
        self.means_cards = _Cards({"m1": "Rope", "m2": "Belt"})
        self.clue_cards = _Cards({"c1": "Fiber", "c2": "Glove"})
        self.location_and_cause_of_death_tiles = _LCD()
        self.scene_tiles = _SceneTiles()


def test_visible_board_context_includes_public_table_excluding_viewer_hand() -> None:
    from typing import cast

    from app.assets.registry import GameAssets

    game_id = uuid4()
    now = datetime.now(tz=UTC)

    # Viewer p1 cannot see their own hand, but can see p2's.
    p1 = PlayerState(
        player_id="p1",
        seat=1,
        is_ai=True,
        role="investigator",
        display_name="P1",
        hand=PlayerHand(means_ids=["m1"], clue_ids=["c1"]),
    )
    p2 = PlayerState(
        player_id="p2",
        seat=2,
        is_ai=True,
        role="investigator",
        display_name="P2",
        hand=PlayerHand(means_ids=["m2"], clue_ids=["c2"]),
    )

    state = GameState(
        game_id=game_id,
        num_ai_players=2,
        num_human_players=0,
        created_at=now,
        last_updated_at=now,
        seed=1,
        players=[p1, p2],
        phase=GamePhase.discussion,
        fs_location_id="Bank",
        fs_cause_id="Suffocation",
        fs_scene_tiles=["tile-a", "tile-b", "tile-c", "tile-d"],
        fs_scene_bullets={"tile-a": "opt1"},
        # Even if solution exists in server state, investigator POV must not see it.
        solution=Solution(means_id="m2", clue_id="c2"),
    )

    ctx = visible_board_context(
        state=state,
        viewer_player_id="p1",
        assets=cast(GameAssets, cast(object, _Assets())),
    )

    # Should include p2's public cards.
    assert "PUBLIC TABLE (all hands visible; grouped by seat):" in ctx
    assert "- seat 2: P2" in ctx
    assert "  - Means: ['Belt']" in ctx
    assert "  - Clues: ['Glove']" in ctx

    # Should ALSO include p1's own cards (all hands are visible).
    assert "- seat 1: P1" in ctx
    assert "  - Means: ['Rope']" in ctx
    assert "  - Clues: ['Fiber']" in ctx

    # Should include scene tile bullet info.
    assert "SCENE TILES (public):" in ctx
    assert "1. tile-a -> bullet: 'opt1'" in ctx

    # Must NOT leak hidden role identities or the secret solution to investigators.
    assert "Murderer:" not in ctx
    assert "Accomplice:" not in ctx
    assert "Witness:" not in ctx
    assert "Murder solution (secret):" not in ctx
