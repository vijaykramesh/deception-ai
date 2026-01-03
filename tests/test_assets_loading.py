from __future__ import annotations

from pathlib import Path

import pytest

from app.assets.registry import load_game_assets


def test_assets_load_and_lookup() -> None:
    root = Path(__file__).resolve().parent
    assets = load_game_assets(root=root)

    # Tilesets (exact)
    assert assets.scene_tiles.has_option("Corpse Condition", "Decayed")
    assert assets.location_and_cause_of_death_tiles.has_option("Cause of Death", "Poisoning")

    # Tilesets (normalized lookup: case + whitespace)
    assert assets.scene_tiles.has_option("  corpse   condition ", " decayed ")
    assert assets.location_and_cause_of_death_tiles.has_option("cause of death", "poisoning")

    # ID-based lookup (stable / canonical)
    corpse_decayed_id = assets.scene_tiles.resolve_id("corpse condition", "decayed")
    assert corpse_decayed_id == "corpse-condition__decayed"
    assert assets.scene_tiles.get("corpse-condition__decayed") is not None

    # Cards: membership supports name or id
    assert "Axe" in assets.means_cards
    assert "axe" in assets.means_cards
    assert "axe" in assets.means_cards  # also a valid id
    assert assets.means_cards.get("axe") is not None


def test_deterministic_deal_with_seed() -> None:
    root = Path(__file__).resolve().parent
    assets = load_game_assets(root=root)

    a1 = assets.deal_means_ids(n=5, seed=123)
    a2 = assets.deal_means_ids(n=5, seed=123)
    b = assets.deal_means_ids(n=5, seed=456)

    assert a1 == a2
    assert a1 != b
    assert len(set(a1)) == 5  # without replacement

    # Can map dealt ids back to names
    names = tuple(assets.means_cards.get(i).name for i in a1)  # type: ignore[union-attr]
    assert len(names) == 5

    with pytest.raises(ValueError):
        assets.means_cards.deal_ids(n=len(assets.means_cards.cards) + 1, seed=1, without_replacement=True)
