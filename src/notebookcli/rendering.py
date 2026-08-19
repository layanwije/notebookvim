from __future__ import annotations

import re
from typing import Iterable

from rich.console import Group
from rich.markdown import Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .model import Cell, CellType, DisplayOutput, ErrorOutput, Output, StreamOutput


_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_])")
# Preserve tabs and newlines, but strip carriage returns and terminal controls.
# Static widgets cannot safely interpret cursor movement intended for a terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_OUTPUT_CHARS = 100_000


class LeftHeading(Heading):
    LEVEL_ALIGN = {f"h{level}": "left" for level in range(1, 7)}


class LeftMarkdown(Markdown):
    elements = {**Markdown.elements, "heading_open": LeftHeading}

    def __init__(self, markup: str) -> None:
        super().__init__(markup, justify="left")


def safe_text(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    clean = _CONTROL.sub("", _ANSI.sub("", text))
    if len(clean) > MAX_OUTPUT_CHARS:
        return clean[:MAX_OUTPUT_CHARS] + "\n… output truncated by nbcli …"
    return clean


def render_output(output: Output):
    if isinstance(output, StreamOutput):
        style = "red" if output.name == "stderr" else "default"
        return Text(safe_text(output.text).rstrip("\n"), style=style)
    if isinstance(output, ErrorOutput):
        traceback = "\n".join(output.traceback) or f"{output.ename}: {output.evalue}"
        return Text.from_ansi(safe_text(traceback), no_wrap=False)
    if isinstance(output, DisplayOutput):
        data = output.data
        if "text/markdown" in data:
            return LeftMarkdown(safe_text(data["text/markdown"]))
        if "text/plain" in data:
            return Text(safe_text(data["text/plain"]))
        if "application/json" in data:
            return Syntax(safe_text(data["application/json"]), "json", word_wrap=True)
        return Text("[rich output unavailable in this terminal]", style="dim")
    return Text(f"[{output.output_type} output]", style="dim")


def render_cell(
    cell: Cell,
    index: int,
    show_output: bool = True,
    syntax_theme: str = "ansi_dark",
):
    count = " " if cell.execution_count is None else str(cell.execution_count)
    kind = "Python" if cell.cell_type == CellType.CODE else cell.cell_type.value.title()
    header = Text()
    header.append(f" Cell {index + 1} ", style="bold reverse cyan")
    header.append(f"  {kind}", style="bold")
    if cell.execution_state.value != "idle":
        state_style = {
            "running": "bold yellow",
            "succeeded": "bold green",
            "failed": "bold red",
            "interrupted": "bold red",
        }.get(cell.execution_state.value, "dim")
        header.append(f"  {cell.execution_state.value.upper()}", style=state_style)
    parts: list = [header]
    if cell.cell_type == CellType.MARKDOWN:
        parts.append(LeftMarkdown(cell.source or " "))
    elif cell.cell_type == CellType.CODE:
        parts.append(Syntax(cell.source or " ", "python", theme=syntax_theme, line_numbers=False,
                            word_wrap=False, background_color="default"))
    else:
        parts.append(Text(cell.source or " ", style="dim"))

    if cell.execution_count is not None or cell.execution_duration is not None:
        metadata = Text()
        if cell.execution_count is not None:
            metadata.append(f"In [{count}]", style="cyan")
        if cell.execution_duration is not None:
            elapsed = (
                f"{cell.execution_duration:.2f} s"
                if cell.execution_duration >= 1
                else f"{cell.execution_duration * 1000:.0f} ms"
            )
            if metadata:
                metadata.append("  ·  ", style="dim")
            metadata.append(elapsed, style="dim")
        parts.append(metadata)
    if cell.outputs and not show_output:
        parts.append(Text("▸ Output collapsed", style="dim green"))
    elif cell.outputs:
        has_error = any(
            isinstance(output, ErrorOutput)
            or (isinstance(output, StreamOutput) and output.name == "stderr")
            for output in cell.outputs
        )
        has_result = any(
            isinstance(output, DisplayOutput) and output.output_type == "execute_result"
            for output in cell.outputs
        )
        output_title = f"Output · Out [{count}]" if has_result else "Output"
        output_group = Group(*(render_output(output) for output in cell.outputs))
        parts.append(
            Panel(
                output_group,
                title=output_title,
                title_align="left",
                border_style="red" if has_error else "green",
                padding=(0, 1),
            )
        )
    return Group(*parts)
