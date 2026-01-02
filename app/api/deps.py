from __future__ import annotations

from collections.abc import Generator

import redis

from app.infra.redis_client import create_redis


def get_redis() -> Generator[redis.Redis, None, None]:
    client = create_redis()
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            # Some redis client versions don't require explicit close.
            pass

