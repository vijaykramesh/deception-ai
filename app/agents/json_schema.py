from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JsonSchema:
    """Minimal JSON Schema wrapper for OpenAI-style structured outputs."""

    name: str
    schema: dict[str, Any]
    strict: bool = True

