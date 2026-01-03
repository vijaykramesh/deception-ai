from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
import redis
from typing import Any

from app.actions import ActionName, dispatch_action_async
from app.agent_runner import AgentRunnerConfig, run_game_agents_once
from app.api.deps import get_redis
from app.api.models import DiscussRequest, GameCreateRequest, GameListResponse, GameState, MurderPickRequest, SolveRequest
from app.game_store import (
    add_discussion_comment,
    create_game,
    get_game,
    list_games,
    set_murder_solution,
    submit_solution_guess,
)

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


@router.post("/game/{game_id}/player/{player_id}/murder", response_model=GameState)
async def murder_pick_route(
    game_id: UUID,
    player_id: str,
    payload: MurderPickRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        return await set_murder_solution(r=r, game_id=game_id, player_id=player_id, clue_id=payload.clue, means_id=payload.means)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@router.post("/game/{game_id}/player/{player_id}/discuss", response_model=GameState)
async def discuss_route(
    game_id: UUID,
    player_id: str,
    payload: DiscussRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        return add_discussion_comment(r=r, game_id=game_id, player_id=player_id, comments=payload.comments)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@router.post("/game/{game_id}/player/{player_id}/solve", response_model=GameState)
async def solve_route(
    game_id: UUID,
    player_id: str,
    payload: SolveRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        return submit_solution_guess(
            r=r,
            game_id=game_id,
            player_id=player_id,
            murderer_id=payload.murderer,
            clue_id=payload.clue,
            means_id=payload.means,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@router.post("/games/{game_id}/actions/{action}", response_model=GameState)
async def generic_action_route(
    game_id: UUID,
    action: str,
    body: dict[str, Any],
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        if action not in {"murder", "discuss", "solve"}:
            raise ValueError(f"Unknown action: {action}")
        act: ActionName = action  # type: ignore[assignment]
        pid = body.get("player_id")
        if not pid:
            raise ValueError("player_id is required")
        result = await dispatch_action_async(r=r, game_id=game_id, player_id=str(pid), action=act, payload=body)
        return result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e


@router.get("/games/{game_id}/players/{player_id}/mailbox")
async def get_player_mailbox_route(
    game_id: UUID,
    player_id: str,
    count: int = 20,
    start: str = "-",
    end: str = "+",
    r: redis.Redis = Depends(get_redis),
) -> dict[str, object]:
    """Debug endpoint: read a player's mailbox Redis Stream.

    Intended for local/dev testing when redis-cli isn't available.
    """

    if count < 1 or count > 200:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="count must be between 1 and 200")

    stream_key = f"mailbox:{game_id}:{player_id}"
    try:
        entries = r.xrange(stream_key, min=start, max=end, count=count)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    messages = [{"id": mid, "fields": fields} for mid, fields in entries]
    return {"game_id": str(game_id), "player_id": player_id, "stream": stream_key, "messages": messages}


@router.post("/games/{game_id}/agents/run_once")
async def run_agents_once_route(
    game_id: UUID,
    block_ms: int = 0,
    count: int = 10,
    r: redis.Redis = Depends(get_redis),
) -> dict[str, object]:
    """Dev endpoint: poll all AI players once for this game and handle any mailbox prompts.

    This is useful for manual testing without running a separate worker process.
    """

    if block_ms < 0 or block_ms > 10_000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="block_ms must be 0..10000")
    if count < 1 or count > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="count must be 1..100")

    handled = await run_game_agents_once(
        r=r,
        game_id=str(game_id),
        config=AgentRunnerConfig(block_ms=block_ms, count=count),
    )
    return {"game_id": str(game_id), "handled": handled}
