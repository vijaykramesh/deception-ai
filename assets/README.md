# `assets/`

This folder is for **local-only game content data** used by the service at runtime (cards/tiles text, instructions, etc.).

## Legal / licensing notice

The game content for *Deception: Murder in Hong Kong* may be copyrighted by **Grey Fox Games** (and/or other rights holders).

This repository **must not distribute** that copyrighted content.

- Only someone with a **legitimate license / lawful right** to use the content should provide these files locally.
- Do **not** commit, upload, or publish the original card text, scans, transcriptions, or other proprietary material.

The codebase can load and use these assets, but the files themselves should remain **untracked** and **local-only**.

---

## Expected files and formats

The app loads several CSV files at startup and normalizes them into in-memory registries/singletons.

General CSV requirements:

- UTF-8
- Comma-separated
- First row is a header
- One record per row

### `clue_cards.csv`

Represents the “Clue” cards.

Required columns:

- `id`: unique identifier (string or integer)
- `text`: the card text

Optional columns (if present are loaded and preserved):

- `category`
- `subcategory`
- `tags` (comma separated)

### `means_cards.csv`

Represents the “Means of Murder” cards.

Required columns:

- `id`
- `text`

Optional columns:

- `category`
- `subcategory`
- `tags`

### `scene_tiles.csv`

Represents the Scene tiles.

Common columns:

- `id`
- `category` (e.g., “corpse_condition”, “crime_scene”, etc.)
- `text` (the option text)

If your dataset uses different headers, update the loader mapping in code.

### `location_and_cause_of_death_tiles.csv`

Represents tiles used by the Forensic Scientist to declare:

- Location of the crime
- Cause of death

Common columns:

- `id`
- `type` (e.g., `location` or `cause_of_death`)
- `text`

### `instructions.txt`

Plain text rules/instructions used as a source for summarization and/or prompting.

---

## Git policy for this folder

Only this documentation file should be tracked:

- `assets/README.md` (tracked)

All other files in `assets/` should be **ignored** by git so they remain local.

> Note: The test suite uses **separate** tracked fixtures under `tests/assets/`.
> Those fixtures are intentionally minimal/obfuscated so tests and CI can run
> without requiring (or distributing) the original game content.

## Tests & CI assets (`tests/assets`)

Tests run in **strict assets** mode and load data from `tests/assets/` (not from
this `assets/` folder).

- The pytest session fixture in `tests/conftest.py` sets `DECEPTION_AI_STRICT_ASSETS=1`.
- It initializes the asset registry with a **fake project root** of `tests/`, so the loader
  finds CSVs at `tests/assets/*.csv`.

This keeps tests hermetic and prevents coupling to local licensed files.

### Strict mode

To force *strict* behavior (error if any asset CSV is missing), set:

- `DECEPTION_AI_STRICT_ASSETS=1`

### Regenerating test fixtures

If you update your local runtime CSVs in `assets/` and need to refresh the obfuscated
test fixtures under `tests/assets/`, use:

- `scripts/generate_test_assets.py`

This script reads from `assets/` (local-only) and produces deterministic, sanitized
CSVs for `tests/assets/` that preserve a small set of sentinel names/values used by tests.
