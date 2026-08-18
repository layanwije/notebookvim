from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .kernel import ExecutionUpdate, Kernel
from .model import CellType
from .storage import load_notebook, new_notebook, save_notebook
from .tui import run_tui, run_workspace
from .workspace import is_supported_text_file

app = typer.Typer(add_completion=False, no_args_is_help=False,
                  help="A terminal-native interactive notebook.")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nbcli {__version__}")
        raise typer.Exit()


@app.callback()
def root_command(
    version: bool = typer.Option(False, "--version", callback=version_callback,
                                 is_eager=True, help="Show the version and exit."),
) -> None:
    """A terminal-native notebook and project workspace.

    Run nbcli without arguments to browse the current project, or pass a
    directory, notebook, or supported text-file path directly.
    """


@app.command("open", hidden=True)
def open_command(
    target: Path = typer.Argument(Path("."), help="Project directory or supported file path."),
) -> None:
    """Open a project, notebook, or text file in the interactive terminal UI."""
    if not target.exists():
        raise typer.BadParameter(f"Path does not exist: {target}")
    if target.is_dir():
        run_workspace(target)
    elif target.suffix.lower() == ".ipynb":
        run_tui(load_notebook(target), workspace_root=target.parent)
    elif is_supported_text_file(target):
        run_workspace(target.parent, initial_path=target)
    else:
        raise typer.BadParameter(f"Unsupported file type: {target}")


@app.command("new")
def create(path: Path) -> None:
    """Create a new Python notebook."""
    if path.exists():
        raise typer.BadParameter(f"Refusing to overwrite existing file: {path}")
    notebook = new_notebook(path)
    save_notebook(notebook)
    typer.echo(f"Created {path}")


@app.command("info")
def info(path: Path) -> None:
    """Print notebook metadata."""
    notebook = load_notebook(path)
    code = sum(cell.cell_type == CellType.CODE for cell in notebook.cells)
    typer.echo(f"Path: {notebook.path}")
    typer.echo(f"Format: {notebook.nbformat}.{notebook.nbformat_minor}")
    typer.echo(f"Kernel: {notebook.kernel_name}")
    typer.echo(f"Cells: {len(notebook.cells)} ({code} code)")


async def _run_notebook(path: Path, output: Optional[Path], no_save: bool, timeout: float) -> bool:
    notebook = load_notebook(path)
    kernel = Kernel(notebook.kernel_name, timeout)
    success = True

    async def update(_: ExecutionUpdate) -> None:
        return None

    try:
        for index, cell in enumerate(notebook.cells, start=1):
            if cell.cell_type != CellType.CODE:
                continue
            typer.echo(f"Running cell {index}/{len(notebook.cells)}")
            if not await kernel.execute(cell, update):
                success = False
                break
        if not no_save:
            save_notebook(notebook, output or path)
    finally:
        await kernel.shutdown()
    return success


@app.command("run")
def run(
    path: Path,
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    no_save: bool = typer.Option(False, "--no-save"),
    timeout: float = typer.Option(300.0, min=0.1),
) -> None:
    """Execute code cells sequentially in one kernel."""
    success = asyncio.run(_run_notebook(path, output, no_save, timeout))
    if not success:
        raise typer.Exit(1)


def _normalized_cli_args(args: list[str]) -> list[str]:
    # Preserve the canonical `nbcli notebook.ipynb` interface while retaining
    # an unambiguous command tree for Typer/Click.
    args = list(args)
    commands = {"new", "info", "run", "open"}
    if not args:
        args = ["open", "."]
    elif not args[0].startswith("-") and args[0] not in commands:
        args.insert(0, "open")
    return args


def main() -> None:
    args = _normalized_cli_args(sys.argv[1:])
    app(args=args, prog_name="nbcli")
