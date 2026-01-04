from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, cast

import redis


@dataclass(frozen=True, slots=True)
class Mailbox:
    game_id: str
    player_id: str

    @property
    def key(self) -> str:
        return f"mailbox:{self.game_id}:{self.player_id}"


def publish_to_mailbox(*, r: redis.Redis, mailbox: Mailbox, fields: Mapping[str, str]) -> str:
    """Append an entry to a player's mailbox stream."""

    # redis-py stubs expect field/value unions; in our app we only use string fields/values.
    stream_id = r.xadd(mailbox.key, {str(k): str(v) for k, v in fields.items()})
    return cast(str, stream_id)


def publish_many(*, r: redis.Redis, entries: Sequence[tuple[str, Mapping[str, str]]]) -> list[str]:
    ids: list[str] = []
    for key, fields in entries:
        stream_id = r.xadd(key, {str(k): str(v) for k, v in fields.items()})
        ids.append(cast(str, stream_id))
    return ids
