"""Guarded Databricks notebook synchronization and remote job operations."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nbformat


class RemoteError(RuntimeError):
    pass


@dataclass
class RemoteMapping:
    provider: str
    remote_path: str
    base_hash: str | None = None
    remote_modified_at: int | None = None
    strip_outputs: bool = False


@dataclass(frozen=True)
class SyncStatus:
    local_path: Path
    remote_path: str
    local_changed: bool
    remote_changed: bool
    remote_modified_at: int | None
    synchronized: bool
    remote_exists: bool = True

    @property
    def label(self) -> str:
        if self.synchronized:
            return "synchronized"
        if not self.remote_exists:
            return "not uploaded"
        if self.local_changed and self.remote_changed:
            return "conflict"
        if self.local_changed:
            return "local changes"
        if self.remote_changed:
            return "remote changes"
        return "untracked"


@dataclass(frozen=True)
class RemoteJob:
    job_id: int
    name: str


@dataclass(frozen=True)
class RemoteRun:
    run_id: int
    job_id: int | None
    name: str
    state: str
    result: str
    start_time: str
    duration: str
    parameters: dict[str, str] = field(default_factory=dict)
    compute: str = ""
    url: str = ""


@dataclass(frozen=True)
class RemoteReport:
    title: str
    columns: list[str]
    rows: list[list[str]]
    details: list[str] = field(default_factory=list)


class DatabricksRemote:
    def __init__(self, root: Path, client: Any) -> None:
        self.root = Path(root).resolve()
        self.client = client
        self.state_path = self.root / ".notebookvim" / "remotes.json"

    def mapping(self, local_path: Path) -> RemoteMapping | None:
        raw = self._load_state().get(self._key(local_path))
        return RemoteMapping(**raw) if raw else None

    def configure(
        self, local_path: Path, remote_path: str, strip_outputs: bool = False
    ) -> RemoteMapping:
        mapping = RemoteMapping("databricks", remote_path, strip_outputs=strip_outputs)
        state = self._load_state()
        state[self._key(local_path)] = asdict(mapping)
        self._save_state(state)
        return mapping

    def status(self, local_path: Path, local_content: bytes | None = None) -> SyncStatus:
        mapping = self._require_mapping(local_path)
        local = local_content if local_content is not None else local_path.read_bytes()
        try:
            remote, modified_at = self._download(mapping, local_path)
            remote_exists = True
        except Exception as exc:
            if not _is_not_found(exc):
                raise
            remote, modified_at, remote_exists = b"", None, False
        local_hash = _digest(_normalized(local, local_path, mapping.strip_outputs))
        remote_hash = _digest(_normalized(remote, local_path, mapping.strip_outputs))
        base = mapping.base_hash
        return SyncStatus(
            local_path=local_path,
            remote_path=mapping.remote_path,
            local_changed=base is None or local_hash != base,
            remote_changed=remote_exists and (base is None or remote_hash != base),
            remote_modified_at=modified_at,
            synchronized=base is not None and local_hash == remote_hash == base,
            remote_exists=remote_exists,
        )

    def diff(self, local_path: Path, local_content: bytes | None = None) -> list[str]:
        mapping = self._require_mapping(local_path)
        local = local_content if local_content is not None else local_path.read_bytes()
        remote, _ = self._download(mapping, local_path)
        if local_path.suffix.lower() == ".ipynb":
            return _notebook_diff(local, remote)
        return list(
            difflib.unified_diff(
                remote.decode("utf-8").splitlines(),
                local.decode("utf-8").splitlines(),
                fromfile=f"remote:{mapping.remote_path}",
                tofile=f"local:{local_path.name}",
                lineterm="",
            )
        ) or ["No differences"]

    def pull(
        self, local_path: Path, *, dirty: bool, force: bool = False
    ) -> SyncStatus:
        if dirty:
            raise RemoteError("Pull stopped: the active file has unsaved local edits")
        mapping = self._require_mapping(local_path)
        remote, modified_at = self._download(mapping, local_path)
        local = local_path.read_bytes()
        local_hash = _digest(_normalized(local, local_path, mapping.strip_outputs))
        if mapping.base_hash is None and local_hash != _digest(
            _normalized(remote, local_path, mapping.strip_outputs)
        ) and not force:
            raise RemoteError(
                "Pull would replace local content; use :databricks sync resolve remote to confirm"
            )
        if mapping.base_hash is not None and local_hash != mapping.base_hash and not force:
            raise RemoteError(
                "Saved local changes exist; inspect :databricks sync diff, then resolve"
            )
        _atomic_write(local_path, remote)
        base_hash = _digest(_normalized(remote, local_path, mapping.strip_outputs))
        self._update_mapping(local_path, mapping, base_hash, modified_at)
        return self.status(local_path)

    def push(
        self, local_path: Path, local_content: bytes | None = None, *, force: bool = False
    ) -> SyncStatus:
        mapping = self._require_mapping(local_path)
        local = local_content if local_content is not None else local_path.read_bytes()
        try:
            remote, modified_at = self._download(mapping, local_path)
        except Exception as exc:
            if not _is_not_found(exc):
                raise
            remote, modified_at = b"", None
        remote_hash = _digest(_normalized(remote, local_path, mapping.strip_outputs))
        if remote and mapping.base_hash is None and not force:
            raise RemoteError(
                "Remote notebook already exists; inspect :databricks sync diff, "
                "then :databricks sync resolve local"
            )
        if mapping.base_hash is not None and remote_hash != mapping.base_hash and not force:
            raise RemoteError("Remote changed since the last sync; push stopped")
        content = _normalized(local, local_path, mapping.strip_outputs)
        format_, language = _workspace_format(local_path)
        self.client.workspace.upload(
            mapping.remote_path,
            content,
            format=format_,
            language=language,
            overwrite=bool(remote),
        )
        status = self.client.workspace.get_status(mapping.remote_path)
        self._update_mapping(local_path, mapping, _digest(content), status.modified_at)
        return self.status(local_path, local)

    def list_jobs(self) -> list[RemoteJob]:
        jobs = []
        for item in self.client.jobs.list(limit=100):
            job_id = int(item.job_id)
            name = getattr(item.settings, "name", None) or f"Job {job_id}"
            jobs.append(RemoteJob(job_id, name))
        return jobs

    def list_runs(self, active_only: bool = False) -> list[RemoteRun]:
        return [
            _remote_run(item)
            for item in self.client.jobs.list_runs(active_only=active_only, limit=100)
        ]

    def run_job(self, job_id: int, parameters: dict[str, str]) -> int:
        wait = self.client.jobs.run_now(job_id, job_parameters=parameters or None)
        run_id = getattr(wait.response, "run_id", None) or getattr(wait, "run_id", None)
        if run_id is None:
            raise RemoteError("Databricks did not return a run ID")
        return int(run_id)

    def get_run(self, run_id: int) -> RemoteRun:
        return _remote_run(self.client.jobs.get_run(run_id))

    def logs(self, run_id: int) -> RemoteReport:
        run = self.client.jobs.get_run(run_id)
        task_ids = [int(task.run_id) for task in (run.tasks or []) if task.run_id]
        if not task_ids:
            task_ids = [run_id]
        details: list[str] = []
        for task_id in task_ids:
            try:
                output = self.client.jobs.get_run_output(task_id)
            except Exception as exc:
                details.append(f"Task {task_id}: output unavailable ({exc})")
                continue
            details.append(f"Task {task_id}")
            for value in (output.logs, output.error, output.error_trace, output.info):
                if value:
                    details.append(str(value))
            notebook_output = getattr(output, "notebook_output", None)
            if notebook_output and notebook_output.result:
                details.append(str(notebook_output.result))
        current = _remote_run(run)
        return RemoteReport(
            title=f"Run {run_id} · {current.state}",
            columns=["run", "job", "state", "result", "started", "duration", "compute"],
            rows=[_run_row(current)],
            details=details or ["No task output is available yet", current.url],
        )

    def cancel(self, run_id: int) -> None:
        self.client.jobs.cancel_run(run_id)

    def rerun(self, run_id: int) -> int:
        run = self.client.jobs.get_run(run_id)
        if run.job_id is None:
            raise RemoteError("This run is not attached to a reusable job")
        parameters = {
            str(item.name): str(item.value)
            for item in (run.job_parameters or [])
            if item.name is not None and item.value is not None
        }
        return self.run_job(int(run.job_id), parameters)

    def _download(self, mapping: RemoteMapping, local_path: Path) -> tuple[bytes, int | None]:
        format_, _ = _workspace_format(local_path, export=True)
        with self.client.workspace.download(mapping.remote_path, format=format_) as handle:
            content = handle.read()
        status = self.client.workspace.get_status(mapping.remote_path)
        return content, status.modified_at

    def _require_mapping(self, local_path: Path) -> RemoteMapping:
        mapping = self.mapping(local_path)
        if mapping is None:
            raise RemoteError(
                "No remote mapping. Use :databricks sync set /Workspace/path first"
            )
        return mapping

    def _key(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.state_path, (json.dumps(state, indent=2) + "\n").encode())

    def _update_mapping(
        self, local_path: Path, mapping: RemoteMapping, base_hash: str, modified_at: int | None
    ) -> None:
        mapping.base_hash = base_hash
        mapping.remote_modified_at = modified_at
        state = self._load_state()
        state[self._key(local_path)] = asdict(mapping)
        self._save_state(state)


def _workspace_format(path: Path, export: bool = False):
    from databricks.sdk.service.workspace import ExportFormat, ImportFormat, Language

    if path.suffix.lower() == ".ipynb":
        return (ExportFormat.JUPYTER if export else ImportFormat.JUPYTER), None
    language = {
        ".py": Language.PYTHON,
        ".sql": Language.SQL,
        ".scala": Language.SCALA,
        ".r": Language.R,
    }.get(path.suffix.lower())
    return (ExportFormat.SOURCE if export else ImportFormat.SOURCE), language


def _normalized(content: bytes, path: Path, strip_outputs: bool) -> bytes:
    if path.suffix.lower() != ".ipynb" or not strip_outputs:
        return content
    node = nbformat.reads(content.decode("utf-8"), as_version=4)
    for cell in node.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    return nbformat.writes(node, version=nbformat.NO_CONVERT).encode()


def _notebook_diff(local: bytes, remote: bytes) -> list[str]:
    local_node = nbformat.reads(local.decode("utf-8"), as_version=4)
    remote_node = nbformat.reads(remote.decode("utf-8"), as_version=4)
    lines: list[str] = []
    count = max(len(local_node.cells), len(remote_node.cells))
    for index in range(count):
        left = remote_node.cells[index] if index < len(remote_node.cells) else None
        right = local_node.cells[index] if index < len(local_node.cells) else None
        left_source = left.source.splitlines() if left else []
        right_source = right.source.splitlines() if right else []
        left_type = left.cell_type if left else "missing"
        right_type = right.cell_type if right else "missing"
        if left_source == right_source and left_type == right_type:
            continue
        lines.append(f"Cell {index + 1}: remote {left_type} → local {right_type}")
        lines.extend(
            difflib.unified_diff(
                left_source, right_source,
                fromfile=f"remote cell {index + 1}", tofile=f"local cell {index + 1}",
                lineterm="",
            )
        )
    return lines or ["No cell source differences"]


def _remote_run(item: Any) -> RemoteRun:
    status = _enum_text(getattr(getattr(item, "status", None), "state", None))
    legacy = getattr(item, "state", None)
    state = status or _enum_text(getattr(legacy, "life_cycle_state", None)) or "UNKNOWN"
    result = _enum_text(getattr(legacy, "result_state", None))
    if not result:
        termination = getattr(getattr(item, "status", None), "termination_details", None)
        result = _enum_text(getattr(termination, "code", None))
    parameters = {
        str(value.name): str(value.value)
        for value in (getattr(item, "job_parameters", None) or [])
        if value.name is not None and value.value is not None
    }
    cluster = getattr(item, "cluster_instance", None)
    compute = getattr(cluster, "cluster_id", None) or getattr(cluster, "spark_context_id", None) or ""
    return RemoteRun(
        run_id=int(item.run_id),
        job_id=int(item.job_id) if item.job_id is not None else None,
        name=item.run_name or f"Run {item.run_id}",
        state=state,
        result=result,
        start_time=_timestamp(item.start_time),
        duration=_duration(item.run_duration or item.execution_duration),
        parameters=parameters,
        compute=str(compute),
        url=item.run_page_url or "",
    )


def _run_row(run: RemoteRun) -> list[str]:
    return [str(run.run_id), str(run.job_id or "—"), run.state, run.result or "—", run.start_time, run.duration, run.compute or "—"]


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _timestamp(value: int | None) -> str:
    if not value:
        return "—"
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _duration(value: int | None) -> str:
    if value is None:
        return "—"
    seconds = value / 1000
    return f"{seconds:.1f}s" if seconds < 60 else f"{seconds / 60:.1f}m"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _is_not_found(exc: Exception) -> bool:
    return exc.__class__.__name__ in {"NotFound", "ResourceDoesNotExist"} or "not found" in str(exc).lower()
