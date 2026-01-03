"""Generate obfuscated CSV fixtures under `tests/assets/`.

Contract
- Inputs: real CSVs under `<repo>/assets/`.
- Outputs: obfuscated CSVs under `<repo>/tests/assets/`.
- Preserves:
  - headers + row counts
  - all tile names (game logic groups by tile like "Location 1")
  - a few sentinel values referenced by tests
- Obfuscates:
  - card ids + display names
  - tile option ids + most option text

Usage:
    uv run python scripts/generate_test_assets.py

This script is deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CsvSpec:
    src: str
    dst: str


SPECS: tuple[CsvSpec, ...] = (
    CsvSpec("clue_cards.csv", "clue_cards.csv"),
    CsvSpec("means_cards.csv", "means_cards.csv"),
    CsvSpec("scene_tiles.csv", "scene_tiles.csv"),
    CsvSpec("location_and_cause_of_death_tiles.csv", "location_and_cause_of_death_tiles.csv"),
)


def _stable_token(prefix: str, i: int) -> str:
    return f"{prefix}-{i:04d}"


def _slugify(s: str) -> str:
    s = s.strip().casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _tile_option_id(tile: str, option: str) -> str:
    return f"{_slugify(tile)}__{_slugify(option)}"


def _obfuscate_cards(df: pd.DataFrame, *, keep_by_id: dict[str, str]) -> pd.DataFrame:
    """Obfuscate cards.

    - id becomes slugified from obfuscated name (e.g., Card-0001 -> card-0001)
    - name becomes synthetic (except sentinels)

    `keep_by_id` maps canonical ids that must remain stable to their required names.
    """

    out = df.copy()

    names = out["name"].astype(str).tolist()
    ids = out["id"].astype(str).tolist()

    new_names: list[str] = []
    new_ids: list[str] = []

    for idx, (rid, name) in enumerate(zip(ids, names, strict=True)):
        if rid in keep_by_id:
            req_name = keep_by_id[rid]
            new_ids.append(rid)
            new_names.append(req_name)
        else:
            ob_name = _stable_token("Card", idx + 1)
            new_names.append(ob_name)
            new_ids.append(_slugify(ob_name))

    out["id"] = new_ids
    out["name"] = new_names
    return out


def _obfuscate_tiles_keep_tile_names(
    df: pd.DataFrame,
    *,
    keep_pairs: set[tuple[str, str]],
    keep_ids: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """Obfuscate tile options while preserving tile names.

    - Tile names are kept as-is (logic depends on "Location" / "Cause of Death" grouping)
    - Option text is obfuscated (except sentinel pairs)
    - id is regenerated from (Tile, Option) to avoid English slugs

    `keep_ids` maps canonical ids that must remain stable to their (Tile, Option) pair.
    """

    out = df.copy()

    tiles = out["Tile"].astype(str).tolist()
    opts = out["Option"].astype(str).tolist()
    ids = out["id"].astype(str).tolist()

    new_opts: list[str] = []
    new_ids: list[str] = []

    for idx, (rid, tile, opt) in enumerate(zip(ids, tiles, opts, strict=True)):
        if rid in keep_ids:
            kept_tile, kept_opt = keep_ids[rid]
            new_opts.append(kept_opt)
            new_ids.append(rid)
            continue

        if (tile, opt) in keep_pairs:
            ob_opt = opt
        else:
            if tile.casefold().startswith("location"):
                ob_opt = _stable_token("Location", idx + 1)
            elif tile.casefold().startswith("cause of death"):
                ob_opt = _stable_token("Cause", idx + 1)
            else:
                ob_opt = _stable_token("Option", idx + 1)

        new_opts.append(ob_opt)
        new_ids.append(_tile_option_id(tile, ob_opt))

    out["Option"] = new_opts
    out["id"] = new_ids
    return out


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "assets"
    dst_dir = repo_root / "tests" / "assets"
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Sentinel values/ids referenced by tests.
    # Cards
    keep_means_by_id = {
        "axe": "Axe",
    }

    # Tiles
    keep_scene_ids = {
        "corpse-condition__decayed": ("Corpse Condition", "Decayed"),
    }
    keep_lcd_ids = {
        "cause-of-death__poisoning": ("Cause of Death", "Poisoning"),
        # Used by tests/test_scene_picker.py (pure parse tests with hard-coded ids)
        "cause-of-death__stabbing": ("Cause of Death", "Stabbing"),
        "location__kitchen": ("Location", "Kitchen"),
    }

    # Also preserve the human-readable pair-based sentinels referenced by tests.
    keep_scene_pairs = {("Corpse Condition", "Decayed")}
    keep_lcd_pairs = {("Cause of Death", "Poisoning")}

    for spec in SPECS:
        src = src_dir / spec.src
        dst = dst_dir / spec.dst

        if not src.exists():
            raise FileNotFoundError(f"Missing source asset: {src}")

        df = pd.read_csv(src)

        if spec.src in {"clue_cards.csv", "means_cards.csv"}:
            if list(df.columns) != ["id", "name"]:
                raise ValueError(f"Unexpected columns in {spec.src}: {list(df.columns)}")

            keep = keep_means_by_id if spec.src == "means_cards.csv" else {}
            out = _obfuscate_cards(df, keep_by_id=keep)

        else:
            if list(df.columns) != ["id", "Tile", "Option"]:
                raise ValueError(f"Unexpected columns in {spec.src}: {list(df.columns)}")

            if spec.src == "scene_tiles.csv":
                out = _obfuscate_tiles_keep_tile_names(
                    df, keep_pairs=keep_scene_pairs, keep_ids=keep_scene_ids
                )
            elif spec.src == "location_and_cause_of_death_tiles.csv":
                out = _obfuscate_tiles_keep_tile_names(
                    df, keep_pairs=keep_lcd_pairs, keep_ids=keep_lcd_ids
                )
            else:
                out = _obfuscate_tiles_keep_tile_names(df, keep_pairs=set(), keep_ids={})

        out.to_csv(dst, index=False)


if __name__ == "__main__":
    main()
