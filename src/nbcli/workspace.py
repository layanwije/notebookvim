"""Project discovery for the workspace navigator."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nbcli",
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
    ".r": None,
    ".scala": None,
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
PARQUET_SUFFIXES = {".parquet", ".parq", ".pq"}


@dataclass(frozen=True)
class ParquetPreview:
    """A small, read-only sample of a Parquet file."""

    path: Path
    columns: list[str]
    rows: list[list[object]]
    total_rows: int
    statistics_columns: list[str] = field(default_factory=list)
    statistics_rows: list[list[object]] = field(default_factory=list)


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


def is_parquet_file(path: Path) -> bool:
    return path.suffix.lower() in PARQUET_SUFFIXES


def load_parquet_preview(path: Path, limit: int = 25) -> ParquetPreview:
    """Read at most ``limit`` rows without materializing the entire data set."""
    path = Path(path).resolve()
    with path.open("rb") as handle:
        prefix = handle.read(512).lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html")):
        raise ValueError(
            f"{path.name} is an HTML page, not a Parquet file. "
            "If it came from GitHub, download the Raw file instead."
        )

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError("Parquet previews require the optional pyarrow dependency") from exc

    parquet = pq.ParquetFile(path)
    columns = list(parquet.schema_arrow.names)
    rows: list[list[object]] = []
    if parquet.metadata.num_rows:
        for batch in parquet.iter_batches(batch_size=limit):
            data = batch.to_pylist()
            rows = [[record.get(column) for column in columns] for record in data[:limit]]
            break
    statistic_indices = [
        index
        for index, schema_field in enumerate(parquet.schema_arrow)
        if (
            pa.types.is_integer(schema_field.type)
            or pa.types.is_floating(schema_field.type)
            or pa.types.is_decimal(schema_field.type)
            or pa.types.is_string(schema_field.type)
            or pa.types.is_large_string(schema_field.type)
        )
        and not pa.types.is_boolean(schema_field.type)
    ]
    statistics_columns = [columns[index] for index in statistic_indices]
    states = [
        {
            "numeric": not (
                pa.types.is_string(parquet.schema_arrow[index].type)
                or pa.types.is_large_string(parquet.schema_arrow[index].type)
            ),
            "count": 0,
            "mean": 0.0,
            "m2": 0.0,
            "min": None,
            "max": None,
        }
        for index in statistic_indices
    ]
    for batch in parquet.iter_batches(batch_size=65_536):
        for state, index in zip(states, statistic_indices):
            for value in batch.column(index).to_pylist():
                if value is None:
                    continue
                state["count"] += 1
                if state["min"] is None or value < state["min"]:
                    state["min"] = value
                if state["max"] is None or value > state["max"]:
                    state["max"] = value
                if state["numeric"]:
                    number = float(value)
                    delta = number - state["mean"]
                    state["mean"] += delta / state["count"]
                    state["m2"] += delta * (number - state["mean"])

    statistics_rows: list[list[object]] = [
        ["count", *(state["count"] for state in states)],
        [
            "mean",
            *(state["mean"] if state["numeric"] and state["count"] else None for state in states),
        ],
        [
            "stddev",
            *(
                (state["m2"] / (state["count"] - 1)) ** 0.5
                if state["numeric"] and state["count"] > 1
                else None
                for state in states
            ),
        ],
        ["min", *(state["min"] for state in states)],
        ["max", *(state["max"] for state in states)],
    ]
    return ParquetPreview(
        path=path,
        columns=columns,
        rows=rows,
        total_rows=parquet.metadata.num_rows,
        statistics_columns=statistics_columns,
        statistics_rows=statistics_rows,
    )


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
    """Return project files, including dotfiles, in a stable searchable order."""
    root = Path(root).resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: str(path.relative_to(root)).lower())


def notebook_files(root: Path) -> list[Path]:
    return [path for path in project_files(root) if path.suffix.lower() == ".ipynb"]
