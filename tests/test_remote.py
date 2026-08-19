from __future__ import annotations

import io
from types import SimpleNamespace

import nbformat
import pytest

from notebookcli.remote import DatabricksRemote, RemoteError


def notebook_bytes(source: str) -> bytes:
    node = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)])
    return nbformat.writes(node).encode()


class FakeWorkspace:
    def __init__(self):
        self.files = {}
        self.modified = {}

    def download(self, path, format=None):
        if path not in self.files:
            raise RuntimeError("not found")
        return io.BytesIO(self.files[path])

    def upload(self, path, content, format=None, language=None, overwrite=False):
        if path in self.files and not overwrite:
            raise RuntimeError("already exists")
        self.files[path] = bytes(content)
        self.modified[path] = self.modified.get(path, 0) + 1

    def get_status(self, path):
        if path not in self.files:
            raise RuntimeError("not found")
        return SimpleNamespace(modified_at=self.modified[path])


class FakeJobs:
    def __init__(self):
        self.cancelled = []
        self.started = []

    def list(self, limit=None):
        return [SimpleNamespace(job_id=7, settings=SimpleNamespace(name="Daily sales"))]

    def list_runs(self, active_only=False, limit=None):
        return [self.get_run(71)]

    def run_now(self, job_id, job_parameters=None):
        self.started.append((job_id, job_parameters))
        return SimpleNamespace(response=SimpleNamespace(run_id=72))

    def get_run(self, run_id):
        state = SimpleNamespace(life_cycle_state=SimpleNamespace(value="RUNNING"), result_state=None)
        return SimpleNamespace(
            run_id=run_id, job_id=7, run_name="Daily sales", state=state, status=None,
            start_time=1_750_000_000_000, run_duration=12_000, execution_duration=12_000,
            job_parameters=[SimpleNamespace(name="date", value="2026-08-19")],
            cluster_instance=SimpleNamespace(cluster_id="cluster-1", spark_context_id=None),
            run_page_url="https://example/#job/7/run/71",
            tasks=[SimpleNamespace(run_id=711)],
        )

    def get_run_output(self, run_id):
        return SimpleNamespace(
            logs="driver output", error=None, error_trace=None, info=None,
            notebook_output=None,
        )

    def cancel_run(self, run_id):
        self.cancelled.append(run_id)


class FakeClient:
    def __init__(self):
        self.workspace = FakeWorkspace()
        self.jobs = FakeJobs()


def test_remote_sync_guards_local_and_remote_changes(tmp_path):
    path = tmp_path / "analysis.ipynb"
    path.write_bytes(notebook_bytes("value = 1"))
    client = FakeClient()
    remote = DatabricksRemote(tmp_path, client)
    remote.configure(path, "/Workspace/analysis")

    status = remote.push(path)
    assert status.synchronized

    path.write_bytes(notebook_bytes("value = 2"))
    status = remote.status(path)
    assert status.local_changed
    assert not status.remote_changed

    client.workspace.files["/Workspace/analysis"] = notebook_bytes("value = 3")
    client.workspace.modified["/Workspace/analysis"] += 1
    with pytest.raises(RemoteError, match="Remote changed"):
        remote.push(path)
    with pytest.raises(RemoteError, match="unsaved"):
        remote.pull(path, dirty=True)


def test_notebook_diff_is_cell_aware_and_resolve_remote_pulls(tmp_path):
    path = tmp_path / "analysis.ipynb"
    path.write_bytes(notebook_bytes("local = True"))
    client = FakeClient()
    client.workspace.files["/Workspace/analysis"] = notebook_bytes("remote = True")
    client.workspace.modified["/Workspace/analysis"] = 5
    remote = DatabricksRemote(tmp_path, client)
    remote.configure(path, "/Workspace/analysis")

    lines = remote.diff(path)
    assert lines[0].startswith("Cell 1")
    assert any("remote = True" in line for line in lines)
    assert any("local = True" in line for line in lines)

    remote.pull(path, dirty=False, force=True)
    assert "remote = True" in path.read_text(encoding="utf-8")
    assert remote.status(path).synchronized


def test_jobs_runs_logs_cancel_and_rerun(tmp_path):
    client = FakeClient()
    remote = DatabricksRemote(tmp_path, client)

    assert remote.list_jobs()[0].name == "Daily sales"
    run = remote.list_runs(active_only=True)[0]
    assert run.run_id == 71
    assert run.state == "RUNNING"
    assert run.parameters == {"date": "2026-08-19"}
    assert run.compute == "cluster-1"

    assert remote.run_job(7, {"date": "2026-08-19"}) == 72
    report = remote.logs(71)
    assert "driver output" in report.details

    remote.cancel(71)
    assert client.jobs.cancelled == [71]
    assert remote.rerun(71) == 72
    assert client.jobs.started[-1] == (7, {"date": "2026-08-19"})
