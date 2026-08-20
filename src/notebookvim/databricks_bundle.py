"""Load and summarize local Databricks bundle configuration."""

from __future__ import annotations

import copy
import glob
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class BundleError(ValueError):
    """Raised when a bundle cannot be resolved or visualized."""


@dataclass(frozen=True)
class BundleTask:
    job_key: str
    task_key: str
    task_type: str
    depends_on: tuple[str, ...]
    source: str
    entry_point: str | None = None
    defined_in: Path | None = None


@dataclass(frozen=True)
class BundleVisualization:
    name: str
    target: str | None
    files: tuple[Path, ...]
    tasks: tuple[BundleTask, ...]
    pipelines: tuple[str, ...]
    resources: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]

    @property
    def graph(self) -> str:
        if not self.tasks:
            return "No job tasks are defined."
        lines: list[str] = []
        jobs: dict[str, list[BundleTask]] = {}
        for task in self.tasks:
            jobs.setdefault(task.job_key, []).append(task)
        for job_index, (job_key, tasks) in enumerate(jobs.items()):
            if job_index:
                lines.append("")
            lines.append(job_key)
            by_key = {task.task_key: task for task in tasks}
            children: dict[str, list[BundleTask]] = {key: [] for key in by_key}
            for task in tasks:
                for dependency in task.depends_on:
                    if dependency in children:
                        children[dependency].append(task)
            roots = [task for task in tasks if not task.depends_on]
            if not roots:
                roots = tasks[:1]
            rendered: set[str] = set()

            def render_task(
                task: BundleTask, prefix: str, last: bool, stack: tuple[str, ...]
            ) -> None:
                branch = "└── " if last else "├── "
                continuation = "    " if last else "│   "
                label = f"{task.task_key}  [{task.task_type}]"
                if task.task_key in stack:
                    lines.append(prefix + branch + label + "  ↻ cycle")
                    return
                if task.task_key in rendered:
                    lines.append(prefix + branch + label + "  ↳ shared")
                    return
                rendered.add(task.task_key)
                lines.append(prefix + branch + label)
                descendants = children.get(task.task_key, [])
                for index, child in enumerate(descendants):
                    render_task(
                        child,
                        prefix + continuation,
                        index == len(descendants) - 1,
                        (*stack, task.task_key),
                    )

            for index, root in enumerate(roots):
                render_task(root, "", index == len(roots) - 1, ())
            for task in tasks:
                if task.task_key not in rendered:
                    render_task(task, "", True, ())
        return "\n".join(lines)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BundleError(f"{label} must be a YAML mapping")
    return value


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BundleError(f"Could not read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise BundleError(f"Invalid YAML in {path.name}: {exc}") from exc
    return _mapping(value, path.name)


def _included_files(root: Path, patterns: Any) -> list[Path]:
    if patterns is None:
        return []
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise BundleError("include must be a list of path patterns")
    found: list[Path] = []
    for pattern in patterns:
        matches = sorted(Path(item).resolve() for item in glob.glob(str(root.parent / pattern), recursive=True))
        matches = [item for item in matches if item.is_file() and item != root]
        if not matches:
            raise BundleError(f"Include pattern matched no files: {pattern}")
        for match in matches:
            if match not in found:
                found.append(match)
    return found


def _task_type(task: dict[str, Any]) -> str:
    for key in task:
        if key.endswith("_task"):
            return key.removesuffix("_task").replace("_", " ")
    if "for_each_task" in task:
        return "for each"
    return "task"


def _task_source(task: dict[str, Any]) -> str:
    for key, value in task.items():
        if not key.endswith("_task") or not isinstance(value, dict):
            continue
        for source_key in ("notebook_path", "python_file", "file", "path", "pipeline_id"):
            if source_key in value:
                return str(value[source_key])
    return "—"


def _task_entry_point(task: dict[str, Any]) -> str | None:
    wheel = task.get("python_wheel_task")
    if isinstance(wheel, dict) and wheel.get("entry_point"):
        return str(wheel["entry_point"])
    return None


def visualize_bundle(path: Path, target: str | None = None) -> BundleVisualization:
    """Resolve includes and return a target-aware local bundle summary."""
    path = Path(path).resolve()
    if path.name != "databricks.yml":
        raise BundleError("Open the bundle's databricks.yml before visualizing")
    root = _load_yaml(path)
    included = _included_files(path, root.get("include"))
    documents = [(included_path, _load_yaml(included_path)) for included_path in included]
    documents.append((path, root))
    merged: dict[str, Any] = {}
    for _, document in documents:
        merged = _merge(merged, document)

    targets = _mapping(merged.get("targets"), "targets")
    selected_target = target
    if selected_target is None:
        defaults = [name for name, settings in targets.items() if isinstance(settings, dict) and settings.get("default") is True]
        if len(defaults) > 1:
            raise BundleError("Only one bundle target can be marked as default")
        selected_target = defaults[0] if defaults else None
    if selected_target is not None:
        if selected_target not in targets:
            raise BundleError(f"Unknown bundle target: {selected_target}")
        merged = _merge(merged, _mapping(targets[selected_target], f"target {selected_target}"))

    task_origins: dict[tuple[str, str], Path] = {}
    for document_path, document in documents:
        resource_sets = [document.get("resources")]
        if selected_target is not None:
            document_targets = document.get("targets")
            if isinstance(document_targets, dict):
                selected = document_targets.get(selected_target)
                if isinstance(selected, dict):
                    resource_sets.append(selected.get("resources"))
        for raw_resource_set in resource_sets:
            if not isinstance(raw_resource_set, dict):
                continue
            raw_jobs = raw_resource_set.get("jobs")
            if not isinstance(raw_jobs, dict):
                continue
            for origin_job_key, origin_job in raw_jobs.items():
                if not isinstance(origin_job, dict) or not isinstance(origin_job.get("tasks"), list):
                    continue
                for origin_task in origin_job["tasks"]:
                    if isinstance(origin_task, dict) and origin_task.get("task_key"):
                        task_origins[(str(origin_job_key), str(origin_task["task_key"]))] = document_path

    resources = _mapping(merged.get("resources"), "resources")
    jobs = _mapping(resources.get("jobs"), "resources.jobs")
    warnings: list[str] = []
    tasks: list[BundleTask] = []
    for job_key, raw_job in jobs.items():
        job = _mapping(raw_job, f"job {job_key}")
        raw_tasks = job.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise BundleError(f"tasks for job {job_key} must be a list")
        known_keys = {str(item.get("task_key")) for item in raw_tasks if isinstance(item, dict) and item.get("task_key")}
        for raw_task in raw_tasks:
            task = _mapping(raw_task, f"task in job {job_key}")
            task_key = task.get("task_key")
            if not isinstance(task_key, str) or not task_key:
                warnings.append(f"Job {job_key} contains a task without task_key")
                continue
            raw_dependencies = task.get("depends_on", [])
            dependencies = tuple(
                str(item.get("task_key"))
                for item in raw_dependencies
                if isinstance(item, dict) and item.get("task_key")
            ) if isinstance(raw_dependencies, list) else ()
            for dependency in dependencies:
                if dependency not in known_keys:
                    warnings.append(f"{job_key}.{task_key} depends on missing task {dependency}")
            tasks.append(
                BundleTask(
                    str(job_key),
                    task_key,
                    _task_type(task),
                    dependencies,
                    _task_source(task),
                    _task_entry_point(task),
                    task_origins.get((str(job_key), task_key), path),
                )
            )

    pipelines = tuple(str(key) for key in _mapping(resources.get("pipelines"), "resources.pipelines"))
    counts = tuple(
        (str(kind).replace("_", " "), len(value))
        for kind, value in resources.items()
        if isinstance(value, dict) and value
    )
    bundle = _mapping(merged.get("bundle"), "bundle")
    return BundleVisualization(
        name=str(bundle.get("name") or path.parent.name),
        target=selected_target,
        files=tuple([path, *included]),
        tasks=tuple(tasks),
        pipelines=pipelines,
        resources=counts,
        warnings=tuple(warnings),
    )
