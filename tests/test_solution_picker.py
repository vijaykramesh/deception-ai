from __future__ import annotations

import pytest

from app.agents.solution_picker import SolutionPickError, parse_picked_solution


def test_parse_picked_solution_requires_strict_json() -> None:
    with pytest.raises(SolutionPickError):
        parse_picked_solution("green")

    picked = parse_picked_solution('{"clue": "c1", "means": "m1"}')
    assert picked.clue == "c1"
    assert picked.means == "m1"

    picked2 = parse_picked_solution('{"clue_id": "c2", "means_id": "m2"}')
    assert picked2.clue == "c2"
    assert picked2.means == "m2"

    with pytest.raises(SolutionPickError):
        parse_picked_solution('{"clue": "c1"}')
