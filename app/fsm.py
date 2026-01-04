from __future__ import annotations

from dataclasses import dataclass

from statemachine import State, StateMachine

from app.api.models import GamePhase, GameState


@dataclass(frozen=True, slots=True)
class AppliedEvent:
    """Result of applying an event.

    - `state_changed`: if the authoritative game state mutated.
    - `stream_messages`: outbox entries to publish to Redis Streams.
    """

    state_changed: bool
    stream_messages: list["StreamMessage"]


@dataclass(frozen=True, slots=True)
class StreamMessage:
    stream_key: str
    fields: dict[str, str]


class GameFSM(StateMachine):
    """FSM wrapper around GameState.

    This is intentionally minimal scaffolding:
    - phases: awaiting murderer pick -> awaiting FS scene pick -> awaiting FS scene bullets pick -> discussion -> completed
    - actions are applied by service layer; FSM only guards transitions.
    """

    awaiting_murder_pick = State(
        GamePhase.setup_awaiting_murder_pick.value,
        value=GamePhase.setup_awaiting_murder_pick.value,
        initial=True,
    )
    awaiting_fs_scene_pick = State(
        GamePhase.setup_awaiting_fs_scene_pick.value,
        value=GamePhase.setup_awaiting_fs_scene_pick.value,
    )
    awaiting_fs_scene_bullets_pick = State(
        GamePhase.setup_awaiting_fs_scene_bullets_pick.value,
        value=GamePhase.setup_awaiting_fs_scene_bullets_pick.value,
    )
    discussion = State(GamePhase.discussion.value, value=GamePhase.discussion.value)
    completed = State(GamePhase.completed.value, value=GamePhase.completed.value, final=True)

    murder_picked = awaiting_murder_pick.to(awaiting_fs_scene_pick)
    fs_scene_picked = awaiting_fs_scene_pick.to(awaiting_fs_scene_bullets_pick)
    fs_scene_bullets_picked = awaiting_fs_scene_bullets_pick.to(discussion)
    finish = discussion.to(completed)

    def __init__(self, game: GameState):
        self.game = game
        super().__init__(start_value=game.phase.value)

    def sync_phase_to_model(self) -> None:
        self.game.phase = GamePhase(str(self.current_state.value))
