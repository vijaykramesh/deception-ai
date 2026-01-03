from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _load_dotenv_for_tests() -> None:
    """Load repo .env for local runs (PyCharm/CLI).

    This makes OPENAI_BASE_URL / OPENAI_MODEL available to tests without needing
    to manually export them in your shell.

    In CI, we *don't* auto-load `.env` by default, so integration tests that require
    a live Ollama instance stay skipped unless explicitly opted-in.
    """

    # Don't implicitly enable external integration tests in CI.
    # Opt-in locally with: DECEPTION_AI_LOAD_DOTENV_FOR_TESTS=1
    if os.environ.get("CI") and os.environ.get("DECEPTION_AI_LOAD_DOTENV_FOR_TESTS") != "1":
        return

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path, override=False)

    # If using a local OpenAI-compatible endpoint, some clients require a key string.
    if os.environ.get("OPENAI_BASE_URL") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "ollama"


@pytest.fixture(scope="session", autouse=True)
def _init_assets_from_test_fixtures() -> None:
    """Initialize assets from `tests/assets` and forbid production asset loading.

    This keeps tests hermetic and prevents coupling to the repo's real game assets.
    """

    os.environ["DECEPTION_AI_STRICT_ASSETS"] = "1"

    from app.assets.singleton import init_assets, reset_assets_for_tests

    reset_assets_for_tests()

    # Point the asset loader at a fake project root: tests/ contains an assets/ dir.
    test_root = Path(__file__).resolve().parent
    init_assets(project_root=test_root)


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
