from __future__ import annotations

import csv
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def _slug_id(s: str) -> str:
    s = s.strip().casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dataclass(frozen=True, slots=True)
class TileOption:
    id: str
    tile: str
    option: str


@dataclass(frozen=True, slots=True)
class TileSet:
    """Scene / location / cause-of-death tiles.

    Canonical data is stored by id, while lookups are convenient/forgiving.
    """

    by_id: dict[str, TileOption]
    by_tile: dict[str, tuple[str, ...]]
    _tile_key_to_tile: dict[str, str]
    _options_key_to_option: dict[str, dict[str, str]]
    _pair_key_to_id: dict[tuple[str, str], str]

    @staticmethod
    def from_rows(rows: list[TileOption]) -> "TileSet":
        by_id: dict[str, TileOption] = {}
        by_tile_build: dict[str, list[str]] = {}

        for r in rows:
            if r.id in by_id:
                raise AssetLoadError(f"Duplicate tile option id: {r.id}")
            by_id[r.id] = r
            by_tile_build.setdefault(r.tile, []).append(r.option)

        by_tile = {k: tuple(v) for k, v in by_tile_build.items()}
        tile_key_to_tile = {_norm_key(t): t for t in by_tile.keys()}
        options_key_to_option: dict[str, dict[str, str]] = {}
        pair_key_to_id: dict[tuple[str, str], str] = {}

        for tile, options in by_tile.items():
            options_key_to_option[tile] = {_norm_key(o): o for o in options}

        for opt in rows:
            pair_key_to_id[(_norm_key(opt.tile), _norm_key(opt.option))] = opt.id

        return TileSet(
            by_id=by_id,
            by_tile=by_tile,
            _tile_key_to_tile=tile_key_to_tile,
            _options_key_to_option=options_key_to_option,
            _pair_key_to_id=pair_key_to_id,
        )

    def get(self, id: str) -> TileOption | None:
        return self.by_id.get(id)

    def resolve_tile(self, tile: str) -> str | None:
        return self._tile_key_to_tile.get(_norm_key(tile))

    def resolve_option(self, tile: str, option: str) -> str | None:
        tile_canonical = self.resolve_tile(tile)
        if not tile_canonical:
            return None
        return self._options_key_to_option.get(tile_canonical, {}).get(_norm_key(option))

    def resolve_id(self, tile: str, option: str) -> str | None:
        return self._pair_key_to_id.get((_norm_key(tile), _norm_key(option)))

    def options_for(self, tile: str) -> tuple[str, ...]:
        tile_canonical = self.resolve_tile(tile)
        if not tile_canonical:
            return ()
        return self.by_tile.get(tile_canonical, ())

    def has_option(self, tile: str, option: str) -> bool:
        return self.resolve_id(tile, option) is not None


@dataclass(frozen=True, slots=True)
class Card:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class CardList:
    """Deck-like list of cards.

    IDs are canonical (for persistence/network). Names are for display.
    """

    cards: tuple[Card, ...]
    _id_to_card: dict[str, Card]
    _key_to_id: dict[str, str]

    @staticmethod
    def from_rows(rows: list[Card]) -> "CardList":
        id_to_card: dict[str, Card] = {}
        key_to_id: dict[str, str] = {}
        for c in rows:
            if c.id in id_to_card:
                raise AssetLoadError(f"Duplicate card id: {c.id}")
            id_to_card[c.id] = c
            key_to_id[_norm_key(c.name)] = c.id
        return CardList(cards=tuple(rows), _id_to_card=id_to_card, _key_to_id=key_to_id)

    def get(self, id: str) -> Card | None:
        return self._id_to_card.get(id)

    def resolve_id(self, name: str) -> str | None:
        return self._key_to_id.get(_norm_key(name))

    def __contains__(self, item: object) -> bool:
        return isinstance(item, str) and (item in self._id_to_card or self.resolve_id(item) is not None)

    def deal_ids(self, *, n: int, seed: int | str | None = None, without_replacement: bool = True) -> tuple[str, ...]:
        if n < 0:
            raise ValueError("n must be >= 0")
        if n == 0:
            return ()

        rng = random.Random(seed)
        population = [c.id for c in self.cards]

        if without_replacement:
            if n > len(population):
                raise ValueError("Cannot deal more cards than exist without replacement")
            return tuple(rng.sample(population, k=n))

        return tuple(rng.choice(population) for _ in range(n))

    def deal_names(self, *, n: int, seed: int | str | None = None, without_replacement: bool = True) -> tuple[str, ...]:
        ids = self.deal_ids(n=n, seed=seed, without_replacement=without_replacement)
        return tuple(self._id_to_card[i].name for i in ids)


@dataclass(frozen=True, slots=True)
class GameAssets:
    scene_tiles: TileSet
    location_and_cause_of_death_tiles: TileSet
    means_cards: CardList
    clue_cards: CardList

    def validate_scene_selection(self, *, tile: str, option: str) -> bool:
        return self.scene_tiles.has_option(tile, option)

    def deal_means_ids(self, *, n: int, seed: int | str | None = None) -> tuple[str, ...]:
        return self.means_cards.deal_ids(n=n, seed=seed, without_replacement=True)

    def deal_clues_ids(self, *, n: int, seed: int | str | None = None) -> tuple[str, ...]:
        return self.clue_cards.deal_ids(n=n, seed=seed, without_replacement=True)

    def deal_means(self, *, n: int, seed: int | str | None = None) -> tuple[str, ...]:
        return self.means_cards.deal_names(n=n, seed=seed, without_replacement=True)

    def deal_clues(self, *, n: int, seed: int | str | None = None) -> tuple[str, ...]:
        return self.clue_cards.deal_names(n=n, seed=seed, without_replacement=True)


class AssetLoadError(RuntimeError):
    pass


def _read_csv_rows(path: Path) -> list[list[str]]:
    try:
        raw = path.read_text(encoding="utf-8-sig", newline="")
    except FileNotFoundError as e:
        raise AssetLoadError(f"Asset file not found: {path}") from e

    reader = csv.reader(raw.splitlines())
    rows = [[c.strip() for c in row if c is not None] for row in reader]
    return [row for row in rows if any(cell.strip() for cell in row)]


def load_tile_csv(path: Path) -> TileSet:
    rows = _read_csv_rows(path)
    if not rows:
        raise AssetLoadError(f"Empty tile CSV: {path}")

    header = [c.casefold() for c in rows[0]]
    if header[:3] != ["id", "tile", "option"]:
        raise AssetLoadError(f"Unexpected header in {path}: {rows[0]}")

    out: list[TileOption] = []
    for row in rows[1:]:
        if len(row) < 3:
            continue
        rid, tile, option = row[0].strip(), row[1].strip(), row[2].strip()
        if not tile or not option:
            continue
        if not rid:
            rid = f"{_slug_id(tile)}__{_slug_id(option)}"
        out.append(TileOption(id=rid, tile=tile, option=option))

    return TileSet.from_rows(out)


def load_card_list_csv(path: Path) -> CardList:
    rows = _read_csv_rows(path)
    if not rows:
        raise AssetLoadError(f"Empty card CSV: {path}")

    header = [c.casefold() for c in rows[0]]
    if header[:2] != ["id", "name"]:
        raise AssetLoadError(f"Unexpected header in {path}: {rows[0]}")

    out: list[Card] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        rid, name = row[0].strip(), row[1].strip()
        if not name:
            continue
        if not rid:
            rid = _slug_id(name)
        out.append(Card(id=rid, name=name))

    return CardList.from_rows(out)


def _fallback_game_assets() -> GameAssets:
    """Small non-copyrighted dummy dataset for tests/CI.

    This is used when real asset CSVs are missing. It is intentionally tiny but
    includes the values referenced by tests (e.g., Corpse Condition / Decayed).
    """

    scene_rows = [
        TileOption(id="corpse-condition__decayed", tile="Corpse Condition", option="Decayed"),
        TileOption(id="corpse-condition__fresh", tile="Corpse Condition", option="Fresh"),
        TileOption(id="crime-scene__indoors", tile="Crime Scene", option="Indoors"),
    ]

    lcd_rows = [
        TileOption(id="cause-of-death__poisoning", tile="Cause of Death", option="Poisoning"),
        TileOption(id="cause-of-death__stabbing", tile="Cause of Death", option="Stabbing"),
        TileOption(id="location__kitchen", tile="Location", option="Kitchen"),
    ]

    # Include enough cards for worst-case dealing.
    # For 12 players, 11 non-FS * 4 = 44 cards are required in each deck.

    means_rows = [Card(id=f"means-{i}", name=f"Means {i}") for i in range(1, 61)]
    # Preserve a few human-friendly names that tests/fixtures rely on.
    means_rows[0] = Card(id="axe", name="Axe")
    means_rows[1] = Card(id="poison", name="Poison")
    means_rows[2] = Card(id="rope", name="Rope")
    means_rows[3] = Card(id="knife", name="Knife")

    clue_rows = [Card(id=f"clue-{i}", name=f"Clue {i}") for i in range(1, 61)]
    clue_rows[0] = Card(id="blood", name="Blood")
    clue_rows[1] = Card(id="footprints", name="Footprints")
    clue_rows[2] = Card(id="receipt", name="Receipt")
    clue_rows[3] = Card(id="note", name="Note")

    return GameAssets(
        scene_tiles=TileSet.from_rows(scene_rows),
        location_and_cause_of_death_tiles=TileSet.from_rows(lcd_rows),
        means_cards=CardList.from_rows(means_rows),
        clue_cards=CardList.from_rows(clue_rows),
    )


def load_game_assets(*, root: Path) -> GameAssets:
    assets_dir = root / "assets"

    # Default behavior: fall back to a tiny dummy dataset when files are missing.
    # You can force strict behavior by setting DECEPTION_AI_STRICT_ASSETS=1.
    strict = os.getenv("DECEPTION_AI_STRICT_ASSETS", "").strip().lower() in {"1", "true", "yes"}

    try:
        return GameAssets(
            scene_tiles=load_tile_csv(assets_dir / "scene_tiles.csv"),
            location_and_cause_of_death_tiles=load_tile_csv(assets_dir / "location_and_cause_of_death_tiles.csv"),
            means_cards=load_card_list_csv(assets_dir / "means_cards.csv"),
            clue_cards=load_card_list_csv(assets_dir / "clue_cards.csv"),
        )
    except AssetLoadError:
        if strict:
            raise
        return _fallback_game_assets()
