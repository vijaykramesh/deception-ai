from __future__ import annotations

import time
from contextlib import contextmanager

import redis


@contextmanager
def game_lock(*, r: redis.Redis, game_id: str, ttl_ms: int = 5_000):
    """Best-effort per-game lock.

    This is basic scaffolding for single-process tests/dev.
    For production you'd want:
    - unique lock tokens
    - safe release via Lua
    - retries/backoff
    """

    key = f"lock:game:{game_id}"
    acquired = r.set(key, "1", nx=True, px=ttl_ms)
    if not acquired:
        raise ValueError("Game is busy")
    try:
        yield
    finally:
        # Only safe in our single-holder test scenario.
        r.delete(key)
        # small yield to avoid tight contention in tests
        time.sleep(0)

