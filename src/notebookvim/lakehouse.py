"""Read-only Parquet metadata and local Delta transaction-log inspection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pyarrow.parquet as pq


MAX_REPORT_ROWS = 500
_COMMIT_NAME = re.compile(r"^(\d{20})\.json$")
_CHECKPOINT_NAME = re.compile(r"^(\d{20})\.checkpoint(?:\.\d+\.\d+)?\.parquet$")


class InspectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class InspectionReport:
    title: str
    columns: list[str]
    rows: list[list[str]]
    details: list[str] = field(default_factory=list)


@dataclass
class DeltaSnapshot:
    root: Path
    version: int
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    protocol: dict[str, Any] = field(default_factory=dict)
    cdc_files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def paths(self) -> list[Path]:
        return [self.root / unquote(path) for path in sorted(self.files)]


def find_delta_root(path: Path) -> Path | None:
    current = path.resolve() if path.is_dir() else path.resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "_delta_log").is_dir():
            return candidate
    return None


class LakehouseInspector:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()

    @property
    def delta_root(self) -> Path | None:
        return find_delta_root(self.path)

    def parquet(self, operation: str) -> InspectionReport:
        if self.path.suffix.lower() not in {".parquet", ".parq", ".pq"}:
            raise InspectionError("Open a Parquet file before using :inspect parquet")
        handlers = {
            "describe": self._parquet_describe,
            "schema": self._parquet_schema,
            "rowgroups": self._parquet_rowgroups,
            "partitions": self._parquet_partitions,
            "files": self._parquet_files,
            "history": self._parquet_history,
        }
        try:
            return handlers[operation]()
        except KeyError as exc:
            raise InspectionError(f"Unknown Parquet inspection: {operation}") from exc

    def delta(self, operation: str, version: int | None = None) -> InspectionReport:
        root = self.delta_root
        if root is None:
            raise InspectionError("The active file is not inside a Delta table")
        log = DeltaLog(root)
        target = log.latest_version if version is None else version
        snapshot = log.snapshot(target)
        if operation in {"describe", "version", "time travel"}:
            return self._delta_describe(snapshot, time_travel=version is not None)
        if operation == "schema":
            return self._delta_schema(snapshot)
        if operation == "partitions":
            return self._delta_partitions(snapshot)
        if operation == "files":
            return self._delta_files(snapshot)
        if operation == "rowgroups":
            return self._delta_rowgroups(snapshot)
        if operation == "history":
            return log.history()
        if operation == "properties":
            return self._delta_properties(snapshot)
        if operation in {"cdf", "change data feed"}:
            return self._delta_cdf(snapshot, log)
        raise InspectionError(f"Unknown Delta inspection: {operation}")

    def delta_files(self, version: int | None = None) -> list[Path]:
        root = self.delta_root
        if root is None:
            raise InspectionError("The active file is not inside a Delta table")
        snapshot = DeltaLog(root).snapshot(version)
        if any(action.get("deletionVector") for action in snapshot.files.values()):
            raise InspectionError(
                "Delta profiling is disabled for snapshots with deletion vectors "
                "because direct Parquet reads would include logically deleted rows"
            )
        return snapshot.paths

    def _parquet_describe(self) -> InspectionReport:
        parquet = pq.ParquetFile(self.path)
        metadata = parquet.metadata
        compression = sorted(
            {
                str(metadata.row_group(group).column(column).compression)
                for group in range(metadata.num_row_groups)
                for column in range(metadata.num_columns)
            }
        )
        return InspectionReport(
            f"Parquet describe · {self.path.name}",
            ["property", "value"],
            [
                ["path", str(self.path)],
                ["size", _bytes(self.path.stat().st_size)],
                ["rows", f"{metadata.num_rows:,}"],
                ["columns", str(metadata.num_columns)],
                ["row groups", str(metadata.num_row_groups)],
                ["format version", str(metadata.format_version)],
                ["created by", str(metadata.created_by or "—")],
                ["compression", ", ".join(compression) or "—"],
                ["serialized metadata", _bytes(metadata.serialized_size)],
            ],
        )

    def _parquet_schema(self) -> InspectionReport:
        schema = pq.ParquetFile(self.path).schema_arrow
        rows = []
        for field in schema:
            rows.extend(_arrow_field_rows(field))
        return InspectionReport(
            f"Parquet schema · {self.path.name}",
            ["field", "type", "nullable", "metadata"],
            rows,
        )

    def _parquet_rowgroups(self) -> InspectionReport:
        metadata = pq.ParquetFile(self.path).metadata
        rows = []
        for group_index in range(metadata.num_row_groups):
            group = metadata.row_group(group_index)
            rows.append([
                str(group_index), f"{group.num_rows:,}", _bytes(group.total_byte_size),
                str(group.num_columns),
                ", ".join(sorted({str(group.column(i).compression) for i in range(group.num_columns)})),
            ])
        return InspectionReport(
            f"Parquet row groups · {self.path.name}",
            ["row group", "rows", "uncompressed", "columns", "compression"],
            rows,
        )

    def _parquet_partitions(self) -> InspectionReport:
        values = _hive_partitions(self.path.parent)
        rows = [[name, value] for name, value in values.items()]
        return InspectionReport(
            f"Parquet partitions · {self.path.name}",
            ["column", "value"],
            rows,
            [] if rows else ["No Hive-style key=value partitions were found in the file path"],
        )

    def _parquet_files(self) -> InspectionReport:
        files = sorted(
            item for item in self.path.parent.rglob("*")
            if item.is_file() and item.suffix.lower() in {".parquet", ".parq", ".pq"}
        )
        rows = [[str(item.relative_to(self.path.parent)), _bytes(item.stat().st_size)] for item in files[:MAX_REPORT_ROWS]]
        details = [f"Showing {MAX_REPORT_ROWS} of {len(files)} files"] if len(files) > MAX_REPORT_ROWS else []
        return InspectionReport(
            f"Parquet files · {self.path.parent.name}", ["file", "size"], rows, details
        )

    def _parquet_history(self) -> InspectionReport:
        stat = self.path.stat()
        return InspectionReport(
            f"Parquet history · {self.path.name}",
            ["property", "value"],
            [["filesystem modified", _timestamp(stat.st_mtime * 1000)]],
            ["Parquet files do not contain transaction history; use Delta for versioned history"],
        )

    def _delta_describe(self, snapshot: DeltaSnapshot, time_travel: bool = False) -> InspectionReport:
        record_count = 0
        known_records = True
        total_bytes = 0
        for action in snapshot.files.values():
            total_bytes += int(action.get("size") or 0)
            try:
                record_count += int(json.loads(action.get("stats") or "{}")["numRecords"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                known_records = False
        metadata = snapshot.metadata
        deletion_vectors = sum(
            bool(action.get("deletionVector")) for action in snapshot.files.values()
        )
        return InspectionReport(
            f"Delta {'time travel' if time_travel else 'describe'} · {snapshot.root.name}",
            ["property", "value"],
            [
                ["path", str(snapshot.root)],
                ["version", str(snapshot.version)],
                ["table ID", str(metadata.get("id") or "—")],
                ["name", str(metadata.get("name") or "—")],
                ["description", str(metadata.get("description") or "—")],
                ["active files", f"{len(snapshot.files):,}"],
                ["rows from statistics", f"{record_count:,}" if known_records else "incomplete"],
                ["data size", _bytes(total_bytes)],
                ["deletion vectors", str(deletion_vectors)],
                ["partitions", ", ".join(metadata.get("partitionColumns") or []) or "none"],
                ["minimum reader", str(snapshot.protocol.get("minReaderVersion") or "—")],
                ["minimum writer", str(snapshot.protocol.get("minWriterVersion") or "—")],
            ],
        )

    def _delta_schema(self, snapshot: DeltaSnapshot) -> InspectionReport:
        raw = snapshot.metadata.get("schemaString")
        if not raw:
            raise InspectionError("Delta metadata does not contain a schema")
        schema = json.loads(raw)
        rows: list[list[str]] = []
        _delta_schema_rows(schema, rows)
        return InspectionReport(
            f"Delta schema · version {snapshot.version}",
            ["field", "type", "nullable", "metadata"], rows,
        )

    def _delta_partitions(self, snapshot: DeltaSnapshot) -> InspectionReport:
        columns = snapshot.metadata.get("partitionColumns") or []
        counts: dict[tuple[tuple[str, str], ...], int] = {}
        for action in snapshot.files.values():
            values = tuple(sorted((action.get("partitionValues") or {}).items()))
            counts[values] = counts.get(values, 0) + 1
        rows = [[json.dumps(dict(values), sort_keys=True), str(count)] for values, count in sorted(counts.items())]
        return InspectionReport(
            f"Delta partitions · version {snapshot.version}",
            ["partition values", "files"], rows,
            [f"Partition columns: {', '.join(columns) or 'none'}"],
        )

    def _delta_files(self, snapshot: DeltaSnapshot) -> InspectionReport:
        rows = []
        for path, action in sorted(snapshot.files.items())[:MAX_REPORT_ROWS]:
            stats = _json_object(action.get("stats"))
            rows.append([
                unquote(path), _bytes(int(action.get("size") or 0)),
                str(stats.get("numRecords", "—")),
                json.dumps(action.get("partitionValues") or {}, sort_keys=True),
                _timestamp(action.get("modificationTime")),
                "yes" if action.get("deletionVector") else "no",
            ])
        details = [f"Showing {MAX_REPORT_ROWS} of {len(snapshot.files)} active files"] if len(snapshot.files) > MAX_REPORT_ROWS else []
        return InspectionReport(
            f"Delta files · version {snapshot.version}",
            ["file", "size", "rows", "partitions", "modified", "deletion vector"], rows, details,
        )

    def _delta_rowgroups(self, snapshot: DeltaSnapshot) -> InspectionReport:
        rows = []
        for path in snapshot.paths:
            if not path.exists():
                continue
            metadata = pq.ParquetFile(path).metadata
            for group_index in range(metadata.num_row_groups):
                group = metadata.row_group(group_index)
                rows.append([
                    str(path.relative_to(snapshot.root)), str(group_index),
                    f"{group.num_rows:,}", _bytes(group.total_byte_size),
                ])
                if len(rows) >= MAX_REPORT_ROWS:
                    break
            if len(rows) >= MAX_REPORT_ROWS:
                break
        return InspectionReport(
            f"Delta row groups · version {snapshot.version}",
            ["file", "row group", "rows", "uncompressed"], rows,
            [f"Limited to {MAX_REPORT_ROWS} row groups"] if len(rows) >= MAX_REPORT_ROWS else [],
        )

    def _delta_properties(self, snapshot: DeltaSnapshot) -> InspectionReport:
        properties = snapshot.metadata.get("configuration") or {}
        return InspectionReport(
            f"Delta properties · version {snapshot.version}",
            ["property", "value"],
            [[str(key), str(value)] for key, value in sorted(properties.items())],
            [] if properties else ["No table properties are set"],
        )

    def _delta_cdf(self, snapshot: DeltaSnapshot, log: "DeltaLog") -> InspectionReport:
        properties = snapshot.metadata.get("configuration") or {}
        enabled = str(properties.get("delta.enableChangeDataFeed", "false")).lower() == "true"
        cdc = log.cdc_history()
        return InspectionReport(
            f"Delta change data feed · version {snapshot.version}",
            ["version", "change files", "bytes"],
            [[str(version), str(count), _bytes(size)] for version, count, size in cdc],
            [
                f"Enabled in current metadata: {'yes' if enabled else 'no'}",
                "Insert-only commits may be represented by ordinary add actions instead of change files.",
            ],
        )


class DeltaLog:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.log = self.root / "_delta_log"
        if not self.log.is_dir():
            raise InspectionError(f"Not a Delta table: {self.root}")

    @property
    def latest_version(self) -> int:
        versions = [version for path in self.log.iterdir() if (version := _version(path)) is not None]
        if not versions:
            raise InspectionError("No Delta transaction versions were found")
        return max(versions)

    def snapshot(self, version: int | None = None) -> DeltaSnapshot:
        target = self.latest_version if version is None else version
        if target < 0 or target > self.latest_version:
            raise InspectionError(f"Delta version {target} does not exist")
        snapshot = DeltaSnapshot(self.root, target)
        checkpoint_version = self._load_checkpoint(snapshot, target)
        start = 0 if checkpoint_version is None else checkpoint_version + 1
        for current in range(start, target + 1):
            commit = self.log / f"{current:020d}.json"
            if not commit.exists():
                raise InspectionError(
                    f"Cannot reconstruct version {target}: commit {current} and a usable checkpoint are unavailable"
                )
            with commit.open(encoding="utf-8") as handle:
                for line in handle:
                    self._apply(snapshot, json.loads(line))
        return snapshot

    def history(self) -> InspectionReport:
        rows = []
        commits = sorted(
            (path for path in self.log.glob("*.json") if _COMMIT_NAME.match(path.name)),
            reverse=True,
        )
        for path in commits[:MAX_REPORT_ROWS]:
            version = int(path.stem)
            info: dict[str, Any] = {}
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    action = json.loads(line)
                    if "commitInfo" in action:
                        info = action["commitInfo"]
                        break
            rows.append([
                str(version), _timestamp(info.get("inCommitTimestamp") or info.get("timestamp") or path.stat().st_mtime * 1000),
                str(info.get("operation") or "—"), str(info.get("userName") or "—"),
                json.dumps(info.get("operationParameters") or {}, sort_keys=True),
                json.dumps(info.get("operationMetrics") or {}, sort_keys=True),
            ])
        return InspectionReport(
            f"Delta history · {self.root.name}",
            ["version", "timestamp", "operation", "user", "parameters", "metrics"], rows,
            ["History is limited to retained JSON commits in _delta_log."],
        )

    def cdc_history(self) -> list[tuple[int, int, int]]:
        result = []
        for path in sorted(self.log.glob("*.json")):
            match = _COMMIT_NAME.match(path.name)
            if not match:
                continue
            count = size = 0
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    cdc = json.loads(line).get("cdc")
                    if cdc:
                        count += 1
                        size += int(cdc.get("size") or 0)
            if count:
                result.append((int(match.group(1)), count, size))
        return result

    def _load_checkpoint(self, snapshot: DeltaSnapshot, target: int) -> int | None:
        grouped: dict[int, list[Path]] = {}
        for path in self.log.glob("*.checkpoint*.parquet"):
            match = _CHECKPOINT_NAME.match(path.name)
            if match and int(match.group(1)) <= target:
                grouped.setdefault(int(match.group(1)), []).append(path)
        if not grouped:
            return None
        version = max(grouped)
        for checkpoint in sorted(grouped[version]):
            for action in pq.read_table(checkpoint).to_pylist(maps_as_pydicts="lossy"):
                self._apply(snapshot, {key: value for key, value in action.items() if value is not None})
                sidecar = action.get("sidecar")
                if sidecar and sidecar.get("path"):
                    sidecar_path = self.log / "_sidecars" / sidecar["path"]
                    if sidecar_path.exists():
                        for item in pq.read_table(sidecar_path).to_pylist(maps_as_pydicts="lossy"):
                            self._apply(snapshot, {key: value for key, value in item.items() if value is not None})
        return version

    @staticmethod
    def _apply(snapshot: DeltaSnapshot, action: dict[str, Any]) -> None:
        if action.get("metaData"):
            snapshot.metadata = action["metaData"]
        if action.get("protocol"):
            snapshot.protocol = action["protocol"]
        if action.get("add"):
            snapshot.files[action["add"]["path"]] = action["add"]
        if action.get("remove"):
            snapshot.files.pop(action["remove"]["path"], None)
        if action.get("cdc"):
            snapshot.cdc_files.append(action["cdc"])


def _version(path: Path) -> int | None:
    commit = _COMMIT_NAME.match(path.name)
    if commit:
        return int(commit.group(1))
    checkpoint = _CHECKPOINT_NAME.match(path.name)
    return int(checkpoint.group(1)) if checkpoint else None


def _arrow_field_rows(field, prefix: str = "") -> list[list[str]]:
    name = f"{prefix}.{field.name}" if prefix else field.name
    metadata = {
        key.decode(errors="replace"): value.decode(errors="replace")
        for key, value in (field.metadata or {}).items()
    }
    rows = [[name, str(field.type), "yes" if field.nullable else "no", json.dumps(metadata, sort_keys=True)]]
    if hasattr(field.type, "num_fields"):
        for index in range(field.type.num_fields):
            rows.extend(_arrow_field_rows(field.type.field(index), name))
    return rows


def _delta_schema_rows(schema: dict[str, Any], rows: list[list[str]], prefix: str = "") -> None:
    for field in schema.get("fields", []):
        name = f"{prefix}.{field['name']}" if prefix else field["name"]
        data_type = field.get("type")
        label = data_type.get("type") if isinstance(data_type, dict) else data_type
        rows.append([
            name, json.dumps(data_type, sort_keys=True) if isinstance(data_type, dict) else str(label),
            "yes" if field.get("nullable", True) else "no",
            json.dumps(field.get("metadata") or {}, sort_keys=True),
        ])
        if isinstance(data_type, dict) and data_type.get("type") == "struct":
            _delta_schema_rows(data_type, rows, name)


def _hive_partitions(path: Path) -> dict[str, str]:
    values = {}
    for part in path.parts:
        if "=" in part:
            name, value = part.split("=", 1)
            if name:
                values[unquote(name)] = unquote(value)
    return values


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _timestamp(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return datetime.fromtimestamp(float(value) / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def _bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(value)
