from __future__ import annotations

import os

import redis


def get_redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def create_redis() -> redis.Redis:
    # decode_responses=True => strings in/out instead of bytes
    return redis.Redis.from_url(get_redis_url(), decode_responses=True)

