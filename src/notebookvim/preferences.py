"""Small, dependency-free user preferences for notebookvim."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

DEFAULT_THEME = "databricks-dark"


def config_directory() -> Path:
    override = os.environ.get("NOTEBOOKVIM_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "notebookvim"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "notebookvim"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "notebookvim"


def preferences_path() -> Path:
    return config_directory() / "settings.json"


def _load_preferences() -> dict:
    try:
        value = json.loads(preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_preferences(changes: dict) -> None:
    settings = _load_preferences()
    settings.update(changes)
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_theme(default: str = DEFAULT_THEME) -> str:
    try:
        value = _load_preferences().get("theme")
    except AttributeError:
        return default
    # Preserve the rename made when the dark Snowflake variant was introduced.
    return "snowflake-light" if value == "snowflake" else value if isinstance(value, str) else default


def save_theme(theme: str) -> None:
    _save_preferences({"theme": theme})


def load_ai_provider(default: str = "codex") -> str:
    value = _load_preferences().get("ai_provider")
    return value if value in {"codex", "claude", "ollama"} else default


def load_ai_model(default: Optional[str] = None) -> Optional[str]:
    value = _load_preferences().get("ai_model")
    return value if isinstance(value, str) and value.strip() else default


def save_ai_provider(provider: str, model: Optional[str] = None) -> None:
    if provider not in {"codex", "claude", "ollama"}:
        raise ValueError(f"Unknown AI provider: {provider}")
    changes = {"ai_provider": provider}
    if provider == "ollama" and model:
        changes["ai_model"] = model
    _save_preferences(changes)
