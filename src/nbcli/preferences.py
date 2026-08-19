"""Small, dependency-free user preferences for nbcli."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_directory() -> Path:
    override = os.environ.get("NBCLI_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "nbcli"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "nbcli"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "nbcli"


def preferences_path() -> Path:
    return config_directory() / "settings.json"


def load_theme(default: str = "default") -> str:
    try:
        value = json.loads(preferences_path().read_text(encoding="utf-8")).get("theme")
    except (OSError, ValueError, TypeError, AttributeError):
        return default
    # Preserve the rename made when the dark Snowflake variant was introduced.
    return "snowflake-light" if value == "snowflake" else value if isinstance(value, str) else default


def save_theme(theme: str) -> None:
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"theme": theme}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
