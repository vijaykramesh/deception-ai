from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class GameWebSocketHub:
    """In-process WebSocket pub/sub keyed by game_id.

    Contract:
      - assign connection to a game_id via `connect(game_id, websocket)`.
      - broadcast lightweight events with `broadcast(game_id, payload)`.

    Payloads should be JSON-serializable dicts.

    Note: this is intentionally minimal. If we later run multiple API replicas,
    this should move to Redis pub/sub.
    """

    def __init__(self) -> None:
        self._by_game: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, game_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._by_game[game_id].add(websocket)

    async def disconnect(self, game_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._by_game.get(game_id)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._by_game.pop(game_id, None)

    async def broadcast(self, game_id: str, payload: dict[str, object]) -> None:
        async with self._lock:
            conns = list(self._by_game.get(game_id, set()))

        if not conns:
            return

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._by_game.get(game_id, set()).discard(ws)


hub = GameWebSocketHub()

