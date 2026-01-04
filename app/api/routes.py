from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
import redis

from app.actions import ActionName, dispatch_action_async
from app.agent_runner import AgentRunnerConfig, run_game_agents_once
from app.api.deps import get_redis
from app.api.models import (
    DiscussRequest,
    FsScenePickRequest,
    GameCreateRequest,
    GameListResponse,
    GameState,
    MurderPickRequest,
    SolveRequest,
    GenericActionRequest,
    GenericFsSceneBulletsActionRequest,
)
from app.game_store import create_game, get_game, list_games
from app.websocket_hub import hub

router = APIRouter()


@router.websocket("/ws/game/{game_id}")
async def game_updates_ws(websocket: WebSocket, game_id: UUID) -> None:
    gid = str(game_id)
    await hub.connect(gid, websocket)

    try:
        # Keep the socket open; client can optionally send pings.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(gid, websocket)
    except Exception:
        await hub.disconnect(gid, websocket)
        raise


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

    # Kick off the setup flow by enqueuing the initial murderer prompt.
    from app.actions import enqueue_setup_prompts_on_create
    from app.streams import publish_many

    publish_many(r=r, entries=enqueue_setup_prompts_on_create(state=state))

    await hub.broadcast(str(state.game_id), {"type": "game_updated", "game_id": str(state.game_id)})
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
        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=player_id,
            action="murder",
            payload={"player_id": player_id, "clue": payload.clue, "means": payload.means},
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state


@router.post("/game/{game_id}/player/{player_id}/discuss", response_model=GameState)
async def discuss_route(
    game_id: UUID,
    player_id: str,
    payload: DiscussRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=player_id,
            action="discuss",
            payload={"player_id": player_id, "comments": payload.comments},
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state


@router.post("/game/{game_id}/player/{player_id}/solve", response_model=GameState)
async def solve_route(
    game_id: UUID,
    player_id: str,
    payload: SolveRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=player_id,
            action="solve",
            payload={
                "player_id": player_id,
                "murderer": payload.murderer,
                "clue": payload.clue,
                "means": payload.means,
            },
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state


@router.post("/game/{game_id}/player/{player_id}/fs_scene", response_model=GameState)
async def fs_scene_pick_route(
    game_id: UUID,
    player_id: str,
    payload: FsScenePickRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=player_id,
            action="fs_scene",
            payload={"player_id": player_id, "location": payload.location, "cause": payload.cause},
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state


@router.post("/game/{game_id}/player/{player_id}/fs_scene_bullets", response_model=GameState)
async def fs_scene_bullets_pick_route(
    game_id: UUID,
    player_id: str,
    payload: GenericFsSceneBulletsActionRequest,
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    try:
        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=player_id,
            action="fs_scene_bullets",
            payload={"player_id": player_id, "picks": payload.picks},
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state


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

    if handled:
        await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})

    return {"game_id": str(game_id), "handled": handled}


@router.post("/games/{game_id}/actions", response_model=GameState)
async def generic_action_route(
    game_id: UUID,
    body: GenericActionRequest = Body(..., discriminator="action"),
    r: redis.Redis = Depends(get_redis),
) -> GameState:
    """Generic action endpoint (dev/test convenience).

    This is typed via a discriminated union on the `action` field.

    Note: this intentionally routes through the same dispatcher as the typed endpoints
    and is safe for agent usage (it still shows up in the same logs).
    """

    try:
        # `action` becomes authoritative via discriminated union.
        action = body.action
        act: ActionName = action  # type: ignore[assignment]

        result = await dispatch_action_async(
            r=r,
            game_id=game_id,
            player_id=body.player_id,
            action=act,
            payload=body.model_dump(),
        )
        state = result.state
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    await hub.broadcast(str(game_id), {"type": "game_updated", "game_id": str(game_id)})
    return state

