from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _load_dotenv_for_tests() -> None:
    """Load repo .env for local runs (PyCharm/CLI).

    This makes OPENAI_BASE_URL / OPENAI_MODEL available to tests without needing
    to manually export them in your shell.
    """

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path, override=False)

    # If using a local OpenAI-compatible endpoint, some clients require a key string.
    if os.environ.get("OPENAI_BASE_URL") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "ollama"


@pytest.fixture()
def client_and_redis():
    """Shared fixture for tests that need both a FastAPI TestClient and fakeredis.

    Several test modules define a local version of this fixture; this global version
    lets new tests use it without importing across test modules.
    """

    from collections.abc import Generator

    import fakeredis
    from fastapi.testclient import TestClient

    from app.api.deps import get_redis
    from app.main import app

    r = fakeredis.FakeRedis(decode_responses=True)

    def _override() -> Generator[fakeredis.FakeRedis, None, None]:
        yield r

    app.dependency_overrides[get_redis] = _override
    with TestClient(app) as c:
        yield c, r
    app.dependency_overrides.clear()

