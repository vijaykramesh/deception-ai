from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

EventType = Literal[
    "TURN_STARTED",
    "ACTION_PROPOSED",
    "ACTION_COMMITTED",
    "TURN_ENDED",
]


@dataclass(frozen=True, slots=True)
class GameEvent:
    type: EventType
    turn_id: int
    payload: dict[str, Any]
    ts: datetime

    @staticmethod
    def now(*, type: EventType, turn_id: int, payload: dict[str, Any]) -> "GameEvent":
        return GameEvent(type=type, turn_id=turn_id, payload=payload, ts=datetime.now(timezone.utc))

