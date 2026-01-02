from __future__ import annotations

from pathlib import Path

from app.assets.singleton import init_assets


def init_assets_for_app() -> None:
    # project root is two levels up from this file: app/assets/startup.py
    project_root = Path(__file__).resolve().parents[2]
    init_assets(project_root=project_root)

