from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
import redis

from app.api.deps import get_redis
from app.api.models import GameCreateRequest, GameListResponse, GameState
from app.game_store import create_game, get_game, list_games

router = APIRouter()


@router.get("/healthcheck")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/game", response_model=GameState, status_code=status.HTTP_201_CREATED)
async def create_game_route(payload: GameCreateRequest, r: redis.Redis = Depends(get_redis)) -> GameState:
    try:
        state = await create_game(
            r=r,
            num_ai_players=payload.num_ai_players,
            num_human_players=payload.num_human_players,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    return state


@router.get("/game", response_model=GameListResponse)
async def list_games_route(r: redis.Redis = Depends(get_redis)) -> GameListResponse:
    return GameListResponse(games=list_games(r=r))


@router.get("/game/{game_id}", response_model=GameState)
async def get_game_route(game_id: UUID, r: redis.Redis = Depends(get_redis)) -> GameState:
    state = get_game(r=r, game_id=game_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return state
