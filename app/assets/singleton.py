from __future__ import annotations

from pathlib import Path

from app.assets.registry import GameAssets, load_game_assets


_ASSETS: GameAssets | None = None


def init_assets(*, project_root: Path) -> GameAssets:
    """Load assets once and cache them.

    Safe to call multiple times; subsequent calls return the already loaded instance.
    """

    global _ASSETS
    if _ASSETS is None:
        _ASSETS = load_game_assets(root=project_root)
    return _ASSETS


def get_assets() -> GameAssets:
    if _ASSETS is None:
        raise RuntimeError("Assets not initialized. Call init_assets() at startup.")
    return _ASSETS

