from __future__ import annotations

import json
from dataclasses import dataclass

from app.agents.base import Agent
from app.agents.json_schema import JsonSchema
from app.core.context import RenderedContext


@dataclass(frozen=True, slots=True)
class PickedSceneBullets:
    """Picked bullet option IDs for each dealt scene tile.

    `picks` maps scene tile name -> chosen option within that tile.
    """

    picks: dict[str, str]


class SceneBulletsPickError(RuntimeError):
    pass


def parse_picked_scene_bullets(text: str) -> PickedSceneBullets:
    """Parse strict JSON output for FS scene bullet selection.

    Expected JSON object, with one of:
        {"picks": {"<tile>": "<option>", ...}}
    or
        {"bullets": {"<tile>": "<option>", ...}}
    or directly:
        {"<tile>": "<option>", ...}

    We also tolerate markdown fenced blocks.
    """

    raw = text.strip()

    if raw.startswith("```"):
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].rstrip().endswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SceneBulletsPickError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise SceneBulletsPickError("Expected a JSON object")

    # Prefer nested key.
    picks = data.get("picks")
    if picks is None:
        picks = data.get("bullets")
    if picks is None:
        # If the object looks like a mapping tile->option, treat it as picks.
        picks = data

    if not isinstance(picks, dict):
        raise SceneBulletsPickError("Expected 'picks' to be an object")

    out: dict[str, str] = {}
    for k, v in picks.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, str) or not v.strip():
            continue
        out[k.strip()] = v.strip()

    if not out:
        raise SceneBulletsPickError("No valid picks found")

    return PickedSceneBullets(picks=out)


_SCENE_BULLETS_SCHEMA = JsonSchema(
    name="pick_scene_bullets",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "picks": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "bullets": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "anyOf": [
            {"required": ["picks"]},
            {"required": ["bullets"]},
        ],
    },
    strict=True,
)


async def pick_scene_bullets_with_agent(
    *,
    agent: Agent,
    ctx: RenderedContext,
    dealt_tiles: list[str],
    options_by_tile: dict[str, list[str]],
    max_attempts: int = 3,
) -> PickedSceneBullets:
    """Ask FS agent to pick one bullet option per dealt scene tile.

    Validates strict JSON and ensures:
    - exactly one choice for each dealt tile
    - choice is within the allowed options for that tile
    """

    parts: list[str] = []
    parts.append(
        "You are the Forensic Scientist. You must remain silent and communicate only by selecting one bullet per dealt Scene tile."
    )
    parts.append("Return ONLY strict JSON matching the output schema. No extra commentary.")
    parts.append("")
    parts.append("Dealt scene tiles (choose 1 option for each tile):")

    for tile in dealt_tiles:
        opts = options_by_tile.get(tile, [])
        parts.append(f"- {tile}: {opts}")

    parts.append("")
    parts.append("Output JSON must be: {\"picks\": {\"<tile>\": \"<option>\", ...}}")

    prompt = "\n".join(parts).strip() + "\n"

    last_err: Exception | None = None
    for _ in range(max_attempts):
        propose = getattr(agent, "propose_action")
        try:
            action = await propose(prompt=prompt, ctx=ctx, structured_output=_SCENE_BULLETS_SCHEMA)  # type: ignore[arg-type]
        except TypeError:
            action = await propose(prompt=prompt, ctx=ctx)  # type: ignore[misc]

        try:
            picked = parse_picked_scene_bullets(action.content)
        except Exception as e:
            last_err = e
            continue

        # Normalize membership checks.
        normalized: dict[str, str] = {}
        for tile in dealt_tiles:
            if tile not in picked.picks:
                last_err = SceneBulletsPickError(f"Missing pick for tile: {tile}")
                break
            opt = picked.picks[tile]
            allowed = options_by_tile.get(tile, [])
            if opt not in allowed:
                last_err = SceneBulletsPickError(f"Invalid option for tile '{tile}': '{opt}'")
                break
            normalized[tile] = opt
        else:
            return PickedSceneBullets(picks=normalized)

    raise SceneBulletsPickError(f"Failed to pick valid scene bullets after {max_attempts} attempts: {last_err}")

