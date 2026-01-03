from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.models import GamePhase
from app.turn_processing.validators import ValidationContext, pipeline_for_action


def test_phase_validator_denies_wrong_phase() -> None:
    # Any action pipeline should deny if the current phase doesn't match allowed.
    state = {
        "game_id": uuid4(),
        "num_ai_players": 1,
        "num_human_players": 3,
        "created_at": "2025-01-01T00:00:00Z",
        "last_updated_at": "2025-01-01T00:00:00Z",
        "seed": 123,
        "players": [],
        "phase": GamePhase.discussion,
    }

    from app.api.models import GameState

    gs = GameState.model_validate(state)
    ctx = ValidationContext(game_id=str(gs.game_id), player_id="p1", action="murder")

    with pytest.raises(ValueError) as e:
        pipeline_for_action("murder").validate(ctx=ctx, state=gs)

    assert "not allowed" in str(e.value)
    assert "discussion" in str(e.value)


def test_discuss_denied_if_completed() -> None:
    from app.api.models import GameState

    gs = GameState.model_validate(
        {
            "game_id": uuid4(),
            "num_ai_players": 1,
            "num_human_players": 3,
            "created_at": "2025-01-01T00:00:00Z",
            "last_updated_at": "2025-01-01T00:00:00Z",
            "seed": 123,
            "players": [],
            "phase": GamePhase.completed,
        }
    )
    ctx = ValidationContext(game_id=str(gs.game_id), player_id="p1", action="discuss")

    with pytest.raises(ValueError) as e:
        pipeline_for_action("discuss").validate(ctx=ctx, state=gs)

    assert str(e.value) == "Game is completed"


def test_unknown_action_pipeline_raises() -> None:
    with pytest.raises(ValueError) as e:
        pipeline_for_action("nope")
    assert "Unknown action" in str(e.value)


def test_role_validator_denies_wrong_role() -> None:
    from app.api.models import GameState

    gs = GameState.model_validate(
        {
            "game_id": uuid4(),
            "num_ai_players": 0,
            "num_human_players": 4,
            "created_at": "2025-01-01T00:00:00Z",
            "last_updated_at": "2025-01-01T00:00:00Z",
            "seed": 123,
            "phase": GamePhase.setup_awaiting_murder_pick,
            "players": [
                {
                    "player_id": "p1",
                    "seat": 1,
                    "is_ai": False,
                    "role": "investigator",
                    "display_name": None,
                    "hand": {"means_ids": [], "clue_ids": []},
                }
            ],
        }
    )

    ctx = ValidationContext(game_id=str(gs.game_id), player_id="p1", action="murder")
    with pytest.raises(ValueError) as e:
        pipeline_for_action("murder").validate(ctx=ctx, state=gs)

    assert "not allowed for role" in str(e.value)
    assert "investigator" in str(e.value)
