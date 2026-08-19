"""Local DuckDB queries and bounded dataset profiling."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


RESULT_LIMIT = 200
TOP_VALUE_LIMIT = 5


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    elapsed_seconds: float
    truncated: bool = False
    statement: str = ""


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    data_type: str
    count: int
    null_count: int
    null_percentage: float
    approximate_distinct: int | None
    minimum: Any = None
    maximum: Any = None
    mean: Any = None
    standard_deviation: Any = None
    q25: Any = None
    median: Any = None
    q75: Any = None
    top_values: list[tuple[Any, int]] = field(default_factory=list)
    role: str = ""


@dataclass(frozen=True)
class DatasetProfile:
    source: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    elapsed_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str) + "\n", encoding="utf-8")


@dataclass
class SqlDocument:
    name: str
    query: str = ""
    result: QueryResult | None = None


class DuckDBWorkspace:
    """One in-memory DuckDB connection shared by the current notebookvim session."""

    def __init__(self) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency/install failure
            raise RuntimeError("The SQL workspace requires DuckDB. Reinstall notebookvim to add it.") from exc
        self._connection = duckdb.connect(":memory:")
        self._lock = threading.Lock()
        self.history: list[str] = []

    def execute(self, statement: str, limit: int = RESULT_LIMIT) -> QueryResult:
        statement = statement.strip()
        if not statement:
            raise ValueError("Enter a SQL query first")
        started = time.perf_counter()
        with self._lock:
            cursor = self._connection.execute(statement)
            columns = [item[0] for item in (cursor.description or [])]
            fetched = cursor.fetchmany(limit + 1) if columns else []
        self.history.append(statement)
        return QueryResult(
            columns=columns,
            rows=[list(row) for row in fetched[:limit]],
            elapsed_seconds=time.perf_counter() - started,
            truncated=len(fetched) > limit,
            statement=statement,
        )

    def explain(self, statement: str) -> QueryResult:
        return self.execute(f"EXPLAIN {statement.strip()}")

    def interrupt(self) -> None:
        self._connection.interrupt()

    def close(self) -> None:
        self._connection.close()

    def profile_parquet(self, path: Path) -> DatasetProfile:
        resolved = path.resolve()
        source_sql = f"SELECT * FROM read_parquet({_sql_literal(str(resolved))})"
        metadata: dict[str, Any] = {"file_size_bytes": resolved.stat().st_size}
        try:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(resolved)
            metadata.update(
                {
                    "row_groups": parquet.metadata.num_row_groups,
                    "format": parquet.metadata.format_version,
                    "created_by": parquet.metadata.created_by,
                }
            )
        except Exception:
            pass
        return self._profile(source_sql, str(resolved), metadata)

    def profile_query(self, statement: str, source: str = "SQL result") -> DatasetProfile:
        cleaned = statement.strip().rstrip(";")
        if not cleaned:
            raise ValueError("Run or enter a SQL query before profiling")
        return self._profile(f"SELECT * FROM ({cleaned}) AS notebookvim_profile_source", source, {})

    def profile_files(self, paths: list[Path], source: str) -> DatasetProfile:
        if not paths:
            raise ValueError("The Delta snapshot contains no active data files")
        values = ", ".join(_sql_literal(str(path.resolve())) for path in paths)
        return self._profile(f"SELECT * FROM read_parquet([{values}])", source, {
            "active_files": len(paths)
        })

    def _profile(
        self, source_sql: str, source: str, metadata: dict[str, Any]
    ) -> DatasetProfile:
        started = time.perf_counter()
        with self._lock:
            row_count = int(
                self._connection.execute(
                    f"SELECT count(*) FROM ({source_sql}) AS notebookvim_count_source"
                ).fetchone()[0]
            )
            cursor = self._connection.execute(f"SUMMARIZE {source_sql}")
            names = [item[0] for item in cursor.description]
            summaries = [dict(zip(names, row)) for row in cursor.fetchall()]

            columns: list[ColumnProfile] = []
            for summary in summaries:
                name = str(summary["column_name"])
                null_percentage = float(summary.get("null_percentage") or 0)
                null_count = round(row_count * null_percentage / 100)
                non_null_count = max(0, row_count - null_count)
                approximate_distinct = _optional_int(summary.get("approx_unique"))
                top_values: list[tuple[Any, int]] = []
                if approximate_distinct is not None and approximate_distinct <= 100:
                    identifier = _quote_identifier(name)
                    top_rows = self._connection.execute(
                        f"SELECT {identifier}, count(*) AS frequency "
                        f"FROM ({source_sql}) AS notebookvim_top_source "
                        f"GROUP BY {identifier} ORDER BY frequency DESC, {identifier} "
                        f"LIMIT {TOP_VALUE_LIMIT}"
                    ).fetchall()
                    top_values = [(row[0], int(row[1])) for row in top_rows]
                columns.append(
                    ColumnProfile(
                        name=name,
                        data_type=str(summary["column_type"]),
                        count=non_null_count,
                        null_count=null_count,
                        null_percentage=null_percentage,
                        approximate_distinct=approximate_distinct,
                        minimum=summary.get("min"),
                        maximum=summary.get("max"),
                        mean=summary.get("avg"),
                        standard_deviation=summary.get("std"),
                        q25=summary.get("q25"),
                        median=summary.get("q50"),
                        q75=summary.get("q75"),
                        top_values=top_values,
                        role=_infer_role(name, str(summary["column_type"]), approximate_distinct, row_count),
                    )
                )
        return DatasetProfile(
            source=source,
            row_count=row_count,
            column_count=len(columns),
            columns=columns,
            elapsed_seconds=time.perf_counter() - started,
            metadata=metadata,
        )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _infer_role(name: str, data_type: str, distinct: int | None, rows: int) -> str:
    folded_name = name.casefold()
    folded_type = data_type.casefold()
    if "timestamp" in folded_type or "date" in folded_type:
        return "timestamp"
    if folded_name == "id" or folded_name.endswith("_id"):
        return "identifier"
    if distinct is not None and rows and distinct == rows and any(
        marker in folded_name for marker in ("key", "uuid", "guid", "code")
    ):
        return "identifier"
    if (
        distinct is not None
        and any(marker in folded_type for marker in ("char", "string", "bool", "enum"))
        and distinct <= min(100, max(10, rows // 20))
    ):
        return "categorical"
    return ""


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
