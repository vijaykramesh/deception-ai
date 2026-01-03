from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class GameCreateRequest(BaseModel):
    num_ai_players: int = Field(..., ge=0, le=12)
    num_human_players: int = Field(..., ge=0, le=12)


class Solution(BaseModel):
    means_id: str
    clue_id: str


class PlayerHand(BaseModel):
    means_ids: list[str] = Field(default_factory=list)
    clue_ids: list[str] = Field(default_factory=list)


class DiscussionComment(BaseModel):
    seq: int
    player_id: str
    created_at: datetime
    comments: str


class MurderPickRequest(BaseModel):
    clue: str
    means: str


class FsScenePickRequest(BaseModel):
    location: str
    cause: str


class DiscussRequest(BaseModel):
    comments: str = Field(..., min_length=1, max_length=4000)


class SolveRequest(BaseModel):
    murderer: str
    clue: str
    means: str


class PlayerState(BaseModel):
    player_id: str
    seat: int
    is_ai: bool
    role: str

    # Human-friendly name for UI.
    display_name: str | None = None

    # Cards are face-up for everyone except the owning player (game UI rule);
    # we still store them here for state queries.
    hand: PlayerHand = Field(default_factory=PlayerHand)

    # Secrets to be injected into prompts for specific roles.
    knows_solution: bool = False
    solution: Solution | None = None

    # Investigators start with a badge; if they guess wrong they lose it.
    has_badge: bool = True

    # Witness-only secret: knows murderer/accomplice identity but not solution.
    knows_identities: bool = False
    known_murderer_id: str | None = None
    known_accomplice_id: str | None = None


class GamePhase(StrEnum):
    setup_awaiting_murder_pick = "setup_awaiting_murder_pick"
    setup_awaiting_fs_scene_pick = "setup_awaiting_fs_scene_pick"
    discussion = "discussion"
    completed = "completed"


class GameState(BaseModel):
    game_id: UUID
    num_ai_players: int
    num_human_players: int
    created_at: datetime
    last_updated_at: datetime

    # For reproducibility/debugging.
    seed: int

    players: list[PlayerState]

    phase: GamePhase = GamePhase.setup_awaiting_murder_pick

    # Global hidden solution (server truth). Only some players get it copied into their player state.
    solution: Solution | None = None

    # Forensic Scientist pre-discussion scene setup.
    # We first deal the *tile cards* (one Location card and one Cause-of-Death card),
    # then the FS chooses a specific option id from each.
    fs_location_tile: str | None = None
    fs_cause_tile: str | None = None

    fs_location_id: str | None = None
    fs_cause_id: str | None = None

    # When completed.
    winning_investigator_id: str | None = None

    # Discussion / chat log.
    discussion: list[DiscussionComment] = Field(default_factory=list)


class GameListResponse(BaseModel):
    games: list[GameState]


class GameIdResponse(BaseModel):
    game_id: UUID
