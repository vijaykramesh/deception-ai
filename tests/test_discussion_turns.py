from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent_runner import run_game_agents_once
from app.api.models import DiscussionComment, GamePhase, GameState, PlayerHand, PlayerState


class _DummyRedis:
    """Small stub; we monkeypatch game_store.get_game and actions.dispatch_action_async."""


def _dummy_redis() -> object:
    # Keep typing quiet in tests; runtime doesn't care because we stub out all redis usage.
    return _DummyRedis()


@pytest.mark.asyncio
async def test_run_game_agents_once_discussion_posts_comment_for_ai_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import cast

    import redis

    game_id = uuid4()

    players = [
        PlayerState(player_id="p1", seat=1, is_ai=True, role="investigator", display_name="Seat 1", hand=PlayerHand()),
        PlayerState(player_id="p2", seat=2, is_ai=False, role="investigator", display_name="Seat 2", hand=PlayerHand()),
    ]

    state = GameState(
        game_id=game_id,
        num_ai_players=1,
        num_human_players=1,
        created_at=datetime.now(tz=UTC),
        last_updated_at=datetime.now(tz=UTC),
        seed=123,
        players=players,
        phase=GamePhase.discussion,
        discussion=[],
    )

    # Current turn is derived from discussion length => first turn should be p1.
    monkeypatch.setattr("app.agent_runner.get_game", lambda *, r, game_id: state)

    # Avoid pulling real assets / board rendering.
    monkeypatch.setattr("app.assets.singleton.get_assets", lambda: object())
    monkeypatch.setattr(
        "app.turn_processing.board_context.visible_board_context",
        lambda *, state, viewer_player_id, assets: "BOARD CONTEXT\n(no-op)",
    )

    async def _fake_propose(*, agent, ctx, prompt: str) -> str:  # noqa: ARG001
        return "I think the cause of death narrows the means. Any thoughts?"

    monkeypatch.setattr("app.agent_runner.propose_discussion_with_agent", _fake_propose)

    calls: list[tuple[str, str]] = []

    async def _fake_dispatch(*, r, game_id, player_id, action, payload):  # noqa: ARG001
        assert action == "discuss"
        calls.append((player_id, str(payload.get("comments"))))
        # Mimic real behavior: discuss appends to discussion (which advances turn order).
        state.discussion.append(
            DiscussionComment(
                seq=len(state.discussion) + 1,
                player_id=player_id,
                created_at=datetime.now(tz=UTC),
                comments=str(payload.get("comments")),
            )
        )
        return type("_Res", (), {"state": state})

    monkeypatch.setattr("app.agent_runner.dispatch_action_async", _fake_dispatch)

    r = cast(redis.Redis, _dummy_redis())

    did = await run_game_agents_once(r=r, game_id=str(game_id))
    assert did is True
    assert calls == [("p1", "I think the cause of death narrows the means. Any thoughts?")]

    # After one discuss, turn should advance to p2; agent runner should do nothing (human turn).
    did2 = await run_game_agents_once(r=r, game_id=str(game_id))
    assert did2 is False

