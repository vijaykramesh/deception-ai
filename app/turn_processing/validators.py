from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod

from app.api.models import GamePhase, GameState


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Inputs available to validators.

    Keep this tight and serializable-ish so we can safely log it.
    """

    game_id: str
    player_id: str
    action: str


class TurnValidator(ABC):
    """A small, composable validation unit for an incoming action."""

    @abstractmethod
    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PhaseValidator(TurnValidator):
    """Validates current game phase for a given action.

    This only checks *phase*, but the pipeline makes it easy to add future validators:
    - role-based permissions
    - payload schema checks beyond Pydantic
    - per-phase move legality (e.g., badge availability)
    """

    allowed_phases: set[GamePhase]

    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        if state.phase not in self.allowed_phases:
            allowed = ",".join(sorted(p.value for p in self.allowed_phases))
            raise ValueError(f"Action '{ctx.action}' not allowed in phase '{state.phase.value}' (allowed: {allowed})")


@dataclass(frozen=True, slots=True)
class CompletedGameValidator(TurnValidator):
    """Deny almost all actions after the game is completed."""

    allow_actions: frozenset[str] = frozenset()

    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        if state.phase == GamePhase.completed and ctx.action not in self.allow_actions:
            raise ValueError("Game is completed")


@dataclass(frozen=True, slots=True)
class RoleValidator(TurnValidator):
    """Validate that the acting player has an allowed role for this action."""

    allowed_roles: set[str]

    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        player = next((p for p in state.players if p.player_id == ctx.player_id), None)
        if player is None:
            raise ValueError("Player not found")

        if player.role not in self.allowed_roles:
            allowed = ",".join(sorted(self.allowed_roles))
            raise ValueError(f"Action '{ctx.action}' not allowed for role '{player.role}' (allowed: {allowed})")


@dataclass(frozen=True, slots=True)
class DiscussionTurnValidator(TurnValidator):
    """When in discussion phase, enforce that only the current turn player may act."""

    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        if state.phase != GamePhase.discussion:
            return

        from app.turn_processing.turns import assert_is_players_turn

        assert_is_players_turn(state=state, player_id=ctx.player_id)


@dataclass(frozen=True, slots=True)
class ValidatorPipeline:
    validators: tuple[TurnValidator, ...]

    def validate(self, *, ctx: ValidationContext, state: GameState) -> None:
        for v in self.validators:
            v.validate(ctx=ctx, state=state)


# Default pipeline for today. Phase rules are explicit and easy to expand.
DEFAULT_ACTION_PIPELINES: dict[str, ValidatorPipeline] = {
    "murder": ValidatorPipeline(
        validators=(
            PhaseValidator(allowed_phases={GamePhase.setup_awaiting_murder_pick}),
            RoleValidator(allowed_roles={"murderer"}),
        )
    ),
    "fs_scene": ValidatorPipeline(
        validators=(
            PhaseValidator(allowed_phases={GamePhase.setup_awaiting_fs_scene_pick}),
            RoleValidator(allowed_roles={"forensic_scientist"}),
        )
    ),
    "fs_scene_bullets": ValidatorPipeline(
        validators=(
            PhaseValidator(allowed_phases={GamePhase.setup_awaiting_fs_scene_bullets_pick}),
            RoleValidator(allowed_roles={"forensic_scientist"}),
        )
    ),
    "solve": ValidatorPipeline(
        validators=(
            PhaseValidator(allowed_phases={GamePhase.discussion}),
            RoleValidator(allowed_roles={"investigator"}),
        )
    ),
    "discuss": ValidatorPipeline(
        validators=(
            CompletedGameValidator(),
            DiscussionTurnValidator(),
        )
    ),
}


def pipeline_for_action(action: str) -> ValidatorPipeline:
    pipe = DEFAULT_ACTION_PIPELINES.get(action)
    if pipe is None:
        raise ValueError(f"Unknown action: {action}")
    return pipe
