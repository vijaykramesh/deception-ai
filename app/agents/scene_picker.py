from __future__ import annotations

import json
from dataclasses import dataclass

from app.agents.base import Agent
from app.agents.json_schema import JsonSchema
from app.core.context import RenderedContext


@dataclass(frozen=True, slots=True)
class PickedScene:
    location: str
    cause: str


class ScenePickError(RuntimeError):
    pass


def parse_picked_scene(text: str) -> PickedScene:
    """Parse strict JSON output for FS scene selection.

    Expected JSON object. We accept canonical keys:
        {"location": "<id>", "cause": "<id>"}
    and common variants:
        {"location_id": "<id>", "cause_id": "<id>"}
    """

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ScenePickError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ScenePickError("Expected a JSON object")

    location = data.get("location")
    cause = data.get("cause")

    if location is None:
        location = data.get("location_id")
    if cause is None:
        cause = data.get("cause_id")

    if not isinstance(location, str) or not location.strip():
        raise ScenePickError("Missing/invalid 'location' field")
    if not isinstance(cause, str) or not cause.strip():
        raise ScenePickError("Missing/invalid 'cause' field")

    return PickedScene(location=location.strip(), cause=cause.strip())


_SCENE_SCHEMA = JsonSchema(
    name="pick_scene",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "location": {"type": "string"},
            "cause": {"type": "string"},
            # Accept common variants.
            "location_id": {"type": "string"},
            "cause_id": {"type": "string"},
        },
        "anyOf": [
            {"required": ["location", "cause"]},
            {"required": ["location_id", "cause_id"]},
        ],
    },
    strict=True,
)


async def pick_scene_with_agent(
    *,
    agent: Agent,
    ctx: RenderedContext,
    location_ids: list[str],
    cause_ids: list[str],
    max_attempts: int = 3,
) -> PickedScene:
    """Ask an agent to pick a location + cause from allowed IDs.

    Validates strict JSON and membership in allowed lists.
    """

    prompt = (
        "You are the Forensic Scientist selecting the murder scene setup before discussion begins.\n"
        "Choose exactly ONE Location tile option and ONE Cause-of-Death tile option from the allowed IDs below.\n\n"
        "Return ONLY strict JSON matching the required schema. No explanation.\n\n"
        "Allowed location_ids:\n"
        f"{location_ids}\n\n"
        "Allowed cause_ids:\n"
        f"{cause_ids}\n"
    )

    last_err: Exception | None = None
    for _ in range(max_attempts):
        propose = getattr(agent, "propose_action")
        try:
            action = await propose(prompt=prompt, ctx=ctx, structured_output=_SCENE_SCHEMA)  # type: ignore[arg-type]
        except TypeError:
            action = await propose(prompt=prompt, ctx=ctx)  # type: ignore[misc]

        try:
            picked = parse_picked_scene(action.content)
        except Exception as e:
            last_err = e
            continue

        if picked.location not in location_ids:
            last_err = ScenePickError("Chosen location is not in allowed location_ids")
            continue
        if picked.cause not in cause_ids:
            last_err = ScenePickError("Chosen cause is not in allowed cause_ids")
            continue

        return picked

    raise ScenePickError(f"Failed to pick a valid scene after {max_attempts} attempts: {last_err}")

