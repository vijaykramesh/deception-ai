from __future__ import annotations

from pathlib import Path


class PromptLoadError(RuntimeError):
    pass


def project_root() -> Path:
    # app/prompts.py -> app/ -> project root
    return Path(__file__).resolve().parents[1]


def load_prompt(name: str) -> str:
    """Load a prompt text file from the repo `prompts/` directory.

    Example:
        load_prompt("base_player.txt")
    """

    path = project_root() / "prompts" / name
    try:
        return path.read_text(encoding="utf-8").strip() + "\n"
    except FileNotFoundError as e:
        raise PromptLoadError(f"Prompt not found: {path}") from e

