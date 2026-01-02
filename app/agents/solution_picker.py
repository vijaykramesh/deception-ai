from __future__ import annotations

import json
from dataclasses import dataclass

from app.agents.base import Agent
from app.agents.json_schema import JsonSchema
from app.core.context import RenderedContext


@dataclass(frozen=True, slots=True)
class PickedSolution:
    clue: str
    means: str


class SolutionPickError(RuntimeError):
    pass


def parse_picked_solution(text: str) -> PickedSolution:
    """Parse the model output for a solution pick.

    Expected strict JSON object. We accept either canonical keys:
        {"clue": "<id>", "means": "<id>"}
    or common variants:
        {"clue_id": "<id>", "means_id": "<id>"}

    We intentionally reject non-JSON output.
    """

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SolutionPickError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise SolutionPickError("Expected a JSON object")

    clue = data.get("clue")
    means = data.get("means")

    if clue is None:
        clue = data.get("clue_id")
    if means is None:
        means = data.get("means_id")

    if not isinstance(clue, str) or not clue.strip():
        raise SolutionPickError("Missing/invalid 'clue' field")
    if not isinstance(means, str) or not means.strip():
        raise SolutionPickError("Missing/invalid 'means' field")

    return PickedSolution(clue=clue.strip(), means=means.strip())


_PICK_SCHEMA = JsonSchema(
    name="pick_solution",
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "clue": {"type": "string"},
            "means": {"type": "string"},
            # Accept common variants some models prefer.
            "clue_id": {"type": "string"},
            "means_id": {"type": "string"},
        },
        "anyOf": [
            {"required": ["clue", "means"]},
            {"required": ["clue_id", "means_id"]},
        ],
    },
    strict=True,
)


async def pick_solution_with_agent(
    *,
    agent: Agent,
    ctx: RenderedContext,
    clue_ids: list[str],
    means_ids: list[str],
    max_attempts: int = 3,
) -> PickedSolution:
    """Ask an agent to pick a narrative-consistent means+clue pair.

    Validates the response is strict JSON and the chosen IDs are within the provided lists.
    """

    prompt = (
        "You are choosing the true Means of Murder and the Key Evidence.\n"
        "Choose exactly ONE Means card and ONE Clue card from the allowed IDs below,\n"
        "so that together they form a coherent, plausible murder story.\n\n"
        "Return ONLY JSON matching the required schema. No explanation.\n\n"
        "Allowed clue_ids:\n"
        f"{clue_ids}\n\n"
        "Allowed means_ids:\n"
        f"{means_ids}\n"
    )

    last_err: Exception | None = None
    for _ in range(max_attempts):
        # If the agent supports structured output, pass schema; otherwise rely on prompt+parser.
        propose = getattr(agent, "propose_action")
        try:
            action = await propose(prompt=prompt, ctx=ctx, structured_output=_PICK_SCHEMA)  # type: ignore[arg-type]
        except TypeError:
            action = await propose(prompt=prompt, ctx=ctx)  # type: ignore[misc]

        try:
            picked = parse_picked_solution(action.content)
        except Exception as e:
            last_err = e
            continue

        if picked.clue not in clue_ids:
            last_err = SolutionPickError("Chosen clue is not in allowed clue_ids")
            continue
        if picked.means not in means_ids:
            last_err = SolutionPickError("Chosen means is not in allowed means_ids")
            continue

        return picked

    raise SolutionPickError(f"Failed to pick a valid solution after {max_attempts} attempts: {last_err}")
