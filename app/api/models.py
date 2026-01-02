from __future__ import annotations

from datetime import datetime
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


class PlayerState(BaseModel):
    player_id: str
    seat: int
    is_ai: bool
    role: str

    # Cards are face-up for everyone except the owning player (game UI rule);
    # we still store them here for state queries.
    hand: PlayerHand = Field(default_factory=PlayerHand)

    # Secrets to be injected into prompts for specific roles.
    knows_solution: bool = False
    solution: Solution | None = None


class GameState(BaseModel):
    game_id: UUID
    num_ai_players: int
    num_human_players: int
    created_at: datetime
    last_updated_at: datetime

    # For reproducibility/debugging.
    seed: int

    players: list[PlayerState]


class GameListResponse(BaseModel):
    games: list[GameState]


class GameIdResponse(BaseModel):
    game_id: UUID
