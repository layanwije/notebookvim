"""Static, non-executing source flow visualization."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .workspace import IGNORED_DIRECTORIES


class ExecutionTreeError(ValueError):
    """Raised when a source file cannot be visualized."""


@dataclass(frozen=True)
class PythonCall:
    name: str
    line: int
    resolved: str | None = None


@dataclass(frozen=True)
class PythonFunction:
    name: str
    line: int
    calls: tuple[PythonCall, ...]


@dataclass(frozen=True)
class PythonExecutionTree:
    path: Path
    module_calls: tuple[PythonCall, ...]
    functions: tuple[PythonFunction, ...]
    graph: str
    unreachable: tuple[str, ...]


@dataclass(frozen=True)
class PythonEntryPoint:
    path: Path
    line: int
    symbol: str
    kind: str
    confidence: str


@dataclass(frozen=True)
class PythonEntrySearch:
    root: Path
    entries: tuple[PythonEntryPoint, ...]
    skipped: tuple[Path, ...]
    diagnostics: tuple[str, ...]


def _call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return "<dynamic call>"


class _DirectCalls(ast.NodeVisitor):
    """Collect calls in a body without descending into nested definitions."""

    def __init__(self) -> None:
        self.calls: list[PythonCall] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(PythonCall(_call_name(node), node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _calls(nodes: list[ast.stmt]) -> tuple[PythonCall, ...]:
    visitor = _DirectCalls()
    for node in nodes:
        visitor.visit(node)
    return tuple(visitor.calls)


def _functions(tree: ast.Module) -> list[PythonFunction]:
    found: list[PythonFunction] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(PythonFunction(node.name, node.lineno, _calls(node.body)))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append(
                        PythonFunction(
                            f"{node.name}.{child.name}", child.lineno, _calls(child.body)
                        )
                    )
    return found


def _resolve(call: PythonCall, current: str, known: dict[str, PythonFunction]) -> PythonCall:
    resolved = None
    if call.name in known:
        resolved = call.name
    elif "." in current and call.name.startswith("self."):
        candidate = current.rsplit(".", 1)[0] + "." + call.name.removeprefix("self.")
        if candidate in known:
            resolved = candidate
    return PythonCall(call.name, call.line, resolved)


def visualize_python(path: Path) -> PythonExecutionTree:
    """Build a downward static call tree for one Python source file."""
    path = Path(path).resolve()
    if path.suffix.lower() != ".py":
        raise ExecutionTreeError("Open a Python (.py) file before visualizing execution")
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExecutionTreeError(f"Could not read {path}: {exc}") from exc
    try:
        syntax = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        raise ExecutionTreeError(f"Invalid Python at {location}: {exc.msg}") from exc

    functions = _functions(syntax)
    known = {item.name: item for item in functions}
    module_body = [
        node
        for node in syntax.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    module_calls = tuple(_resolve(call, "<module>", known) for call in _calls(module_body))
    resolved_functions = tuple(
        PythonFunction(
            item.name,
            item.line,
            tuple(_resolve(call, item.name, known) for call in item.calls),
        )
        for item in functions
    )
    known = {item.name: item for item in resolved_functions}
    reached: set[str] = set()
    lines = [f"{path.name}", "└── <module>"]

    def render_calls(calls: tuple[PythonCall, ...], prefix: str, stack: tuple[str, ...]) -> None:
        for index, call in enumerate(calls):
            last = index == len(calls) - 1
            branch = "└── " if last else "├── "
            continuation = "    " if last else "│   "
            label = f"{call.name}()  L{call.line}"
            if call.resolved in stack:
                lines.append(prefix + branch + label + "  ↻ recursive")
                continue
            if call.resolved is None:
                lines.append(prefix + branch + label + "  · external/dynamic")
                continue
            reached.add(call.resolved)
            lines.append(prefix + branch + label)
            render_calls(known[call.resolved].calls, prefix + continuation, (*stack, call.resolved))

    render_calls(module_calls, "    ", ("<module>",))
    unreachable = tuple(item.name for item in resolved_functions if item.name not in reached)
    return PythonExecutionTree(
        path=path,
        module_calls=module_calls,
        functions=resolved_functions,
        graph="\n".join(lines),
        unreachable=unreachable,
    )


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    values = (test.left, test.comparators[0])
    return any(isinstance(item, ast.Name) and item.id == "__name__" for item in values) and any(
        isinstance(item, ast.Constant) and item.value == "__main__" for item in values
    )


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    )


def _console_scripts(root: Path) -> list[tuple[str, str]]:
    """Read simple PEP 621 script declarations without requiring a TOML dependency."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    section = re.search(r"(?ms)^\[project\.scripts\]\s*$([\s\S]*?)(?=^\[|\Z)", text)
    if section is None:
        return []
    scripts: list[tuple[str, str]] = []
    for match in re.finditer(r'(?m)^\s*([A-Za-z0-9_.-]+)\s*=\s*["\']([^"\']+)["\']', section.group(1)):
        scripts.append((match.group(1), match.group(2)))
    return scripts


def _module_path(root: Path, module: str) -> Path | None:
    relative = Path(*module.split(".")).with_suffix(".py")
    candidates = (root / relative, root / "src" / relative)
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def find_python_entry_points(root: Path) -> PythonEntrySearch:
    """Find and rank likely Python entry points throughout a project."""
    root = Path(root).resolve()
    entries: list[PythonEntryPoint] = []
    skipped: list[Path] = []
    diagnostics: list[str] = []
    seen: set[tuple[Path, int, str]] = set()

    def add(path: Path, line: int, symbol: str, kind: str, confidence: str) -> None:
        key = (path.resolve(), line, symbol)
        if key not in seen:
            seen.add(key)
            entries.append(PythonEntryPoint(path.resolve(), line, symbol, kind, confidence))

    # In a Databricks project orchestration is the entry point. Root job tasks
    # run first even when their Python sources intentionally define no main().
    from .databricks_bundle import BundleError, visualize_bundle

    bundle_files = sorted(
        path
        for path in root.rglob("databricks.yml")
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts)
    )
    console_scripts = dict(_console_scripts(root))
    for bundle_path in bundle_files:
        try:
            bundle = visualize_bundle(bundle_path)
        except BundleError as exc:
            diagnostics.append(f"{bundle_path.relative_to(root)}: {exc}")
            continue
        for task in bundle.tasks:
            if task.depends_on:
                continue
            if task.entry_point:
                target = console_scripts.get(task.entry_point)
                if target is None:
                    diagnostics.append(
                        f"{task.job_key}.{task.task_key}: wheel entry point `{task.entry_point}` was not found in [project.scripts]"
                    )
                    continue
                module, separator, symbol = target.partition(":")
                source_path = _module_path(root, module)
                if source_path is None:
                    diagnostics.append(
                        f"{task.job_key}.{task.task_key}: module for wheel entry point not found: {module}"
                    )
                    continue
                add(
                    source_path,
                    1,
                    symbol if separator else "<module>",
                    f"Databricks root task `{task.job_key}.{task.task_key}`",
                    "certain",
                )
                continue
            if task.source == "—" or "${" in task.source:
                continue
            source_base = task.defined_in.parent if task.defined_in is not None else bundle_path.parent
            source_path = (source_base / task.source).resolve()
            if not source_path.suffix and source_path.with_suffix(".py").is_file():
                source_path = source_path.with_suffix(".py")
            if source_path.suffix.lower() != ".py":
                continue
            if not source_path.is_file():
                diagnostics.append(
                    f"{task.job_key}.{task.task_key}: Python source not found: {task.source}"
                )
                continue
            symbol = "<module>"
            line = 1
            try:
                flow = visualize_python(source_path)
                first_local = next(
                    (call for call in flow.module_calls if call.resolved is not None), None
                )
                if first_local is not None:
                    symbol = first_local.resolved or "<module>"
                    line = first_local.line
            except ExecutionTreeError:
                pass
            add(
                source_path,
                line,
                symbol,
                f"Databricks root task `{task.job_key}.{task.task_key}`",
                "certain",
            )

    for command, target in console_scripts.items():
        module, separator, symbol = target.partition(":")
        path = _module_path(root, module)
        if path is not None:
            line = 1
            try:
                syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                match = next(
                    (
                        node
                        for node in syntax.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == symbol
                    ),
                    None,
                )
                if match is not None:
                    line = match.lineno
            except (OSError, SyntaxError):
                pass
            add(path, line, symbol if separator else "<module>", f"console script `{command}`", "certain")

    for path in _python_files(root):
        try:
            syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            skipped.append(path)
            continue
        if path.name == "__main__.py":
            add(path, 1, "<module>", "package __main__.py", "high")
        for node in syntax.body:
            if isinstance(node, ast.If) and _is_main_guard(node):
                add(path, node.lineno, "<module>", "__name__ main guard", "high")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "main",
                "cli",
            }:
                add(path, node.lineno, node.name, f"conventional {node.name}() function", "possible")

    rank = {"certain": 0, "high": 1, "possible": 2}
    entries.sort(key=lambda item: (rank[item.confidence], str(item.path), item.line))
    return PythonEntrySearch(root, tuple(entries), tuple(skipped), tuple(diagnostics))
