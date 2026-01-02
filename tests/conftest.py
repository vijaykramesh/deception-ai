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
    if not env_path.exists():
        return

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=env_path, override=False)

    # If using a local OpenAI-compatible endpoint, some clients require a key string.
    if os.environ.get("OPENAI_BASE_URL") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "ollama"
