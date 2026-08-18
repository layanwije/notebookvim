"""Project discovery for the workspace navigator."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
}

TEXT_LANGUAGES: dict[str, str | None] = {
    ".bash": "bash",
    ".cfg": None,
    ".csv": None,
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".ini": None,
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".log": None,
    ".md": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "javascript",
    ".txt": None,
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}
MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024


@dataclass
class TextBuffer:
    path: Path
    text: str
    dirty: bool = False

    @property
    def language(self) -> str | None:
        return TEXT_LANGUAGES.get(self.path.suffix.lower())


def is_supported_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_LANGUAGES or not path.suffix


def load_text_buffer(path: Path) -> TextBuffer:
    path = Path(path).resolve()
    size = path.stat().st_size
    if size > MAX_TEXT_FILE_BYTES:
        raise ValueError(f"Refusing to open {path.name}: file is larger than 2 MiB")
    data = path.read_bytes()
    if b"\0" in data:
        raise ValueError(f"Refusing to open {path.name}: file appears to be binary")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Refusing to open {path.name}: file is not UTF-8 text") from exc
    return TextBuffer(path=path, text=text)


def save_text_buffer(buffer: TextBuffer) -> None:
    target = buffer.path.resolve()
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(buffer.text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
        buffer.dirty = False
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def project_files(root: Path) -> list[Path]:
    """Return visible project files in a stable, searchable order."""
    root = Path(root).resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: str(path.relative_to(root)).lower())


def notebook_files(root: Path) -> list[Path]:
    return [path for path in project_files(root) if path.suffix.lower() == ".ipynb"]
