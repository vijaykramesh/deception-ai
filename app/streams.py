from __future__ import annotations

from dataclasses import dataclass

import redis


@dataclass(frozen=True, slots=True)
class Mailbox:
    game_id: str
    player_id: str

    @property
    def key(self) -> str:
        return f"mailbox:{self.game_id}:{self.player_id}"


def publish_to_mailbox(*, r: redis.Redis, mailbox: Mailbox, fields: dict[str, str]) -> str:
    """Append an entry to a player's mailbox stream."""

    return r.xadd(mailbox.key, fields)


def publish_many(*, r: redis.Redis, entries: list[tuple[str, dict[str, str]]]) -> list[str]:
    ids: list[str] = []
    for key, fields in entries:
        ids.append(r.xadd(key, fields))
    return ids

