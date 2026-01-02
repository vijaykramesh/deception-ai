from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autogen import LLMConfig


@dataclass(frozen=True, slots=True)
class OpenAICompatibleSettings:
    model: str
    base_url: str | None
    api_key: str | None


def settings_from_env(*, default_model: str) -> OpenAICompatibleSettings:
    return OpenAICompatibleSettings(
        model=os.environ.get("OPENAI_MODEL", default_model),
        # For Ollama, typically http://127.0.0.1:11434/v1
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )


def llm_config_from_env(*, default_model: str) -> LLMConfig:
    s = settings_from_env(default_model=default_model)

    # Many OpenAI-compatible servers ignore the key but some SDKs require it.
    api_key = s.api_key or ("ollama" if s.base_url else None)

    if not api_key:
        raise RuntimeError(
            "Set OPENAI_API_KEY for hosted OpenAI, or set OPENAI_BASE_URL for a local OpenAI-compatible server"
        )

    # AG2 expects a 'config_list' similar to OAI_CONFIG_LIST.
    config: dict[str, Any] = {"model": s.model, "api_key": api_key}
    if s.base_url:
        config["base_url"] = s.base_url

    return LLMConfig(config_list=[config])


def llm_config_from_oai_config_list(path: Path) -> LLMConfig:
    # Matches AG2 docs: LLMConfig.from_json(path="OAI_CONFIG_LIST")
    return LLMConfig.from_json(path=str(path))


def write_oai_config_list(path: Path, *, model: str, api_key: str, base_url: str | None = None) -> None:
    items: list[dict[str, Any]] = [{"model": model, "api_key": api_key}]
    if base_url:
        items[0]["base_url"] = base_url
    path.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
