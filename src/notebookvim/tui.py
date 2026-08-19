from __future__ import annotations

import asyncio
import copy
import json
import shlex
import uuid
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Optional

from rich.console import Group
from rich.table import Table
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester, SuggestFromList
from textual.widgets import Footer, Header, Input, OptionList, Static, Tab, Tabs, TextArea, Tree

from .commands import COMMANDS, COMMAND_SUGGESTIONS, normalize_command
from .ai import provider_statuses
from .ai_pane import AIInput, AIPane
from .completion import python_completions
from .databricks import (
    DatabricksConnection,
    connect_databricks,
    databricks_client,
    databricks_kernel_code,
)
from .data_workspace import DatasetProfile, DuckDBWorkspace, QueryResult, SqlDocument
from .kernel import ExecutionUpdate, Kernel
from .lakehouse import InspectionError, InspectionReport, LakehouseInspector, find_delta_root
from .git import GitError, GitProfile, GitService
from .model import Cell, CellType, Notebook
from .preferences import DEFAULT_THEME, load_ai_model, load_ai_provider, load_theme, save_ai_provider, save_theme
from .rendering import render_cell
from .remote import DatabricksRemote, RemoteError, RemoteReport, SyncStatus
from .scaffolds import init_data_engineering_scaffold
from .storage import load_notebook, new_notebook, save_notebook, to_node
from .terminal import TerminalInput, TerminalPane
from .themes import (
    APP_THEMES,
    EDITOR_THEMES,
    EDITOR_THEME_NAMES,
    RICH_SYNTAX_THEMES,
    TERMINAL_THEMES,
    THEME_FONTS,
    THEME_NAMES,
)
from .workspace import (
    TextBuffer,
    ParquetPreview,
    is_parquet_file,
    is_supported_text_file,
    load_parquet_preview,
    load_text_buffer,
    notebook_files,
    project_directories,
    project_files,
    save_text_buffer,
)


class CellView(Static, can_focus=True):
    def __init__(self, notebook: Notebook, index: int, output_collapsed: bool = False) -> None:
        super().__init__(id=f"cell-{index}")
        self.notebook = notebook
        self.index = index
        self.output_collapsed = output_collapsed

    def render(self):
        return render_cell(
            self.notebook.cells[self.index],
            self.index,
            show_output=not self.output_collapsed,
            syntax_theme=getattr(self.app, "syntax_theme", "ansi_dark"),
        )


class EmptyWorkspace(Static, can_focus=True):
    def __init__(self) -> None:
        super().__init__(
            "[bold]NotebookVim[/bold]\n"
            "Vim-like experience for the World of Data\n\n"
            "Press [bold]Esc[/bold], then [bold]:[/bold] for commands\n"
            "Use [bold]:help[/bold] for the command reference\n\n"
            "Open a folder:        [bold]:folder open path[/bold]\n"
            "Open the terminal:    [bold]:terminal[/bold]\n"
            "Open the AI terminal: [bold]:ai[/bold]\n"
            "Focus file explorer:  [bold]Ctrl+E[/bold]",
            id="empty-workspace",
        )


class ParquetPreviewView(Static, can_focus=True):
    def __init__(self, preview: ParquetPreview) -> None:
        super().__init__(id="parquet-preview")
        self.preview = preview

    def render(self) -> Group:
        table = Table(title=f"Top {len(self.preview.rows)} rows of {self.preview.total_rows}")
        for column in self.preview.columns:
            table.add_column(column, overflow="ellipsis", max_width=30)
        for row in self.preview.rows:
            table.add_row(*("null" if value is None else str(value) for value in row))
        statistics = Table(title="Summary statistics")
        statistics.add_column("summary", style="bold")
        for column in self.preview.statistics_columns:
            statistics.add_column(column, overflow="ellipsis", max_width=30)
        for row in self.preview.statistics_rows:
            statistics.add_row(
                str(row[0]),
                *(
                    "null"
                    if value is None
                    else f"{value:.6g}"
                    if isinstance(value, float)
                    else str(value)
                    for value in row[1:]
                ),
            )
        return Group(table, "", statistics)


def _display_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


class QueryResultView(Static, can_focus=True):
    def __init__(self, result: QueryResult | None) -> None:
        super().__init__(id="sql-result")
        self.result = result

    def render(self):
        if self.result is None:
            return "Run the current query with :sql run"
        result = self.result
        table = Table()
        for column in result.columns:
            table.add_column(column, overflow="ellipsis", max_width=30)
        for row in result.rows:
            table.add_row(*(_display_value(value) for value in row))
        suffix = "+" if result.truncated else ""
        summary = (
            f"{len(result.rows)}{suffix} row(s) · {result.elapsed_seconds:.3f}s"
            if result.columns
            else f"Completed · {result.elapsed_seconds:.3f}s"
        )
        return Group(table, "", summary)


class DatasetProfileView(Static, can_focus=True):
    def __init__(self, profile: DatasetProfile) -> None:
        super().__init__(id="dataset-profile")
        self.profile = profile

    def render(self) -> Group:
        profile = self.profile
        overview = Table(title="Dataset profile", show_header=False)
        overview.add_column("Metric", style="bold")
        overview.add_column("Value")
        overview.add_row("Source", profile.source)
        overview.add_row("Shape", f"{profile.row_count:,} rows × {profile.column_count} columns")
        overview.add_row("Profile time", f"{profile.elapsed_seconds:.3f}s")
        for key, value in profile.metadata.items():
            overview.add_row(key.replace("_", " ").title(), _display_value(value))

        columns = Table(title="Column statistics")
        for heading in (
            "column", "type", "role", "nulls", "distinct≈", "min", "q25", "median",
            "q75", "max", "mean", "top values",
        ):
            columns.add_column(heading, overflow="ellipsis", max_width=24)
        for item in profile.columns:
            top = ", ".join(f"{_display_value(value)} ({count})" for value, count in item.top_values)
            columns.add_row(
                item.name,
                item.data_type,
                item.role or "—",
                f"{item.null_count:,} ({item.null_percentage:.1f}%)",
                _display_value(item.approximate_distinct),
                _display_value(item.minimum),
                _display_value(item.q25),
                _display_value(item.median),
                _display_value(item.q75),
                _display_value(item.maximum),
                _display_value(item.mean),
                top or "—",
            )
        return Group(overview, "", columns)


class RemoteReportView(Static, can_focus=True):
    def __init__(self, report: RemoteReport) -> None:
        super().__init__(id="remote-report")
        self.report = report

    def render(self) -> Group:
        table = Table(title=self.report.title)
        for column in self.report.columns:
            table.add_column(column, overflow="ellipsis", max_width=32)
        for row in self.report.rows:
            table.add_row(*row)
        return Group(table, *(f"\n{detail}" for detail in self.report.details))


class InspectionReportView(Static, can_focus=True):
    def __init__(self, report: InspectionReport, widget_id: str = "inspection-report") -> None:
        super().__init__(id=widget_id)
        self.report = report

    def render(self) -> Group:
        table = Table(title=self.report.title)
        for column in self.report.columns:
            table.add_column(column, overflow="ellipsis", max_width=36)
        for row in self.report.rows:
            table.add_row(*row)
        return Group(table, *(f"\n{detail}" for detail in self.report.details))


class InspectionPane(InspectionReportView):
    BINDINGS = [Binding("escape", "close", "Close inspection", priority=True)]

    def __init__(self) -> None:
        super().__init__(InspectionReport("Inspection", [], []), widget_id="inspection-pane")

    def action_close(self) -> None:
        self.app.action_inspection_close()  # type: ignore[attr-defined]


class InspectionModal(ModalScreen[None]):
    CSS = """
    InspectionModal { align: center middle; background: rgba(0, 0, 0, 0.65); }
    #inspection-modal {
        width: 92%; height: 88%; padding: 1 2;
        background: $surface; border: round $accent;
    }
    #inspection-modal-report { width: auto; height: auto; }
    """
    BINDINGS = [Binding("escape", "close", "Close", priority=True)]

    def __init__(self, report: InspectionReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(
            InspectionReportView(self.report, widget_id="inspection-modal-report"),
            id="inspection-modal",
        )

    def action_close(self) -> None:
        self.dismiss()


class NewFileModal(ModalScreen[Optional[str]]):
    CSS = """
    NewFileModal { align: center middle; background: rgba(0, 0, 0, 0.65); }
    #new-file-modal {
        width: 64; height: auto; padding: 1 2;
        background: $surface; border: round $accent;
    }
    #new-file-folder { margin-bottom: 1; color: $text-muted; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, folder: Path, workspace_root: Path) -> None:
        super().__init__()
        self.folder = folder
        self.workspace_root = workspace_root

    def compose(self) -> ComposeResult:
        relative_folder = self.folder.relative_to(self.workspace_root)
        location = str(relative_folder) if relative_folder.parts else "."
        with Vertical(id="new-file-modal"):
            yield Static(f"Create a new file in {location}", id="new-file-folder")
            yield Input(placeholder="Filename", id="new-file-name")

    def on_mount(self) -> None:
        self.query_one("#new-file-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass
class DocumentTab:
    path: Path
    notebook: Optional[Notebook] = None
    text_buffer: Optional[TextBuffer] = None
    parquet_preview: Optional[ParquetPreview] = None
    sql_document: Optional[SqlDocument] = None
    dataset_profile: Optional[DatasetProfile] = None
    remote_report: Optional[RemoteReport] = None
    inspection_report: Optional[InspectionReport] = None
    kernel: Optional[Kernel] = None
    read_only: bool = False
    selected: int = 0
    collapsed_outputs: set[str] = field(default_factory=set)
    notebook_undo: list[tuple[list[Cell], int]] = field(default_factory=list)
    notebook_redo: list[tuple[list[Cell], int]] = field(default_factory=list)

    @property
    def dirty(self) -> bool:
        if self.text_buffer is not None:
            return self.text_buffer.dirty
        return bool(self.notebook and self.notebook.dirty)

    @property
    def display_name(self) -> str:
        if self.sql_document is not None:
            return self.sql_document.name
        if self.dataset_profile is not None:
            return f"Profile · {Path(self.dataset_profile.source).name}"
        if self.remote_report is not None:
            return self.remote_report.title
        if self.inspection_report is not None:
            return self.inspection_report.title
        return self.path.name


class TextFileEditor(TextArea):
    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("super+left", "cursor_line_start", "Line start", priority=True),
        Binding("super+right", "cursor_line_end", "Line end", priority=True),
        Binding("super+up", "cursor_document_start", "Document start", priority=True),
        Binding("super+down", "cursor_document_end", "Document end", priority=True),
        Binding("super+shift+left", "cursor_line_start(True)", "Select to line start", priority=True),
        Binding("super+shift+right", "cursor_line_end(True)", "Select to line end", priority=True),
        Binding("super+shift+up", "cursor_document_start(True)", "Select to document start", priority=True),
        Binding("super+shift+down", "cursor_document_end(True)", "Select to document end", priority=True),
        Binding("ctrl+left", "cursor_word_left", "Previous word", priority=True),
        Binding("ctrl+right", "cursor_word_right", "Next word", priority=True),
        Binding("ctrl+up", "cursor_document_start", "Document start", priority=True),
        Binding("ctrl+down", "cursor_document_end", "Document end", priority=True),
        Binding("ctrl+shift+left", "cursor_word_left(True)", "Select previous word", priority=True),
        Binding("ctrl+shift+right", "cursor_word_right(True)", "Select next word", priority=True),
        Binding("ctrl+shift+up", "cursor_document_start(True)", "Select to document start", priority=True),
        Binding("ctrl+shift+down", "cursor_document_end(True)", "Select to document end", priority=True),
        Binding("alt+left", "cursor_word_left", "Previous word", priority=True),
        Binding("alt+right", "cursor_word_right", "Next word", priority=True),
        Binding("alt+shift+left", "cursor_word_left(True)", "Select previous word", priority=True),
        Binding("alt+shift+right", "cursor_word_right(True)", "Select next word", priority=True),
        Binding("escape", "leave_edit", "Normal mode", priority=True),
        Binding("tab", "complete_or_indent", "Complete", priority=True),
    ]

    def __init__(self, *args, editable: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.editable = editable
        self.vim_mode = "normal"
        self._vim_pending = ""
        self.read_only = True

    def action_leave_edit(self) -> None:
        self.app.arm_escape_close()  # type: ignore[attr-defined]
        self.enter_normal_mode()

    def action_complete_or_indent(self) -> None:
        if self.vim_mode != "insert":
            return
        accepted = self.app.accept_completion()  # type: ignore[attr-defined]
        if not accepted:
            self.insert("    ")

    def on_mount(self) -> None:
        self.read_only = True

    def enter_normal_mode(self) -> None:
        self.vim_mode = "normal"
        self.read_only = True
        self._vim_pending = ""
        self.app._update_status()  # type: ignore[attr-defined]

    def action_cursor_document_start(self, select: bool = False) -> None:
        self.move_cursor((0, 0), select=select)

    def action_cursor_document_end(self, select: bool = False) -> None:
        last_row = max(0, self.document.line_count - 1)
        self.move_cursor((last_row, len(self.document[last_row])), select=select)

    def enter_insert_mode(self, placement: str = "i") -> None:
        if not self.editable:
            return
        self.read_only = False
        if placement == "a":
            self.action_cursor_right()
        elif placement == "I":
            self.action_cursor_line_start()
        elif placement == "A":
            self.action_cursor_line_end()
        elif placement in {"o", "O"}:
            row, _ = self.cursor_location
            if placement == "o":
                self.action_cursor_line_end()
                self.insert("\n")
            else:
                self.move_cursor((row, 0))
                self.insert("\n")
                self.move_cursor((row, 0))
        self.vim_mode = "insert"
        self.read_only = False
        self._vim_pending = ""
        self.app._update_status()  # type: ignore[attr-defined]

    def _delete_current_line(self, yank: bool = True) -> None:
        row, _ = self.cursor_location
        lines = self.text.splitlines(keepends=True)
        if not lines:
            return
        row = min(row, len(lines) - 1)
        content = lines[row]
        if yank:
            self.app.vim_register = content  # type: ignore[attr-defined]
            self.app.vim_register_linewise = True  # type: ignore[attr-defined]
        self.read_only = False
        try:
            if row < len(lines) - 1:
                self.delete((row, 0), (row + 1, 0))
            else:
                self.delete((row, 0), (row, len(content.rstrip("\n"))))
                if row and self.text.endswith("\n"):
                    self.delete((row - 1, len(lines[row - 1].rstrip("\n"))), (row, 0))
        finally:
            self.read_only = True
        self.move_cursor((min(row, max(0, len(self.text.splitlines()) - 1)), 0))

    def _yank_current_line(self) -> None:
        row, _ = self.cursor_location
        lines = self.text.splitlines(keepends=True)
        if lines:
            self.app.vim_register = lines[min(row, len(lines) - 1)]  # type: ignore[attr-defined]
            self.app.vim_register_linewise = True  # type: ignore[attr-defined]

    def _paste(self, before: bool = False) -> None:
        value = self.app.vim_register  # type: ignore[attr-defined]
        if not value:
            return
        self.read_only = False
        try:
            if self.app.vim_register_linewise:  # type: ignore[attr-defined]
                row, _ = self.cursor_location
                lines = self.text.splitlines()
                target = row if before else min(row + 1, len(lines))
                self.insert(value if value.endswith("\n") else value + "\n", (target, 0))
                self.move_cursor((target, 0))
            else:
                self.insert(value)
        finally:
            self.read_only = True

    def _visual_action(self, operation: str) -> None:
        selection = self.selection
        selected = self.get_selection(selection)
        if selected:
            self.app.vim_register = selected  # type: ignore[attr-defined]
            self.app.vim_register_linewise = False  # type: ignore[attr-defined]
            if operation == "delete":
                self.read_only = False
                try:
                    self.delete(selection.start, selection.end)
                finally:
                    self.read_only = True
        self.enter_normal_mode()

    async def on_key(self, event: events.Key) -> None:
        if self.vim_mode == "insert":
            return
        key = event.key
        if not self.editable and key in {
            "i", "a", "shift+i", "shift+a", "o", "shift+o",
            "d", "x", "p", "shift+p", "u", "ctrl+r",
        }:
            event.stop()
            event.prevent_default()
            return
        if key == "q" and self.app._escape_close_armed:  # type: ignore[attr-defined]
            event.stop()
            event.prevent_default()
            self.app._escape_close_armed = False  # type: ignore[attr-defined]
            self.app.action_close_tab()  # type: ignore[attr-defined]
            return
        if key != "escape":
            self.app._escape_close_armed = False  # type: ignore[attr-defined]
        if key in {"left", "right", "up", "down", "pageup", "pagedown"}:
            return
        if key in {
            "colon", "ctrl+s", "ctrl+p", "ctrl+e", "ctrl+tab", "ctrl+shift+tab",
            "shift+tab", "ctrl+w", "ctrl+q", "left_square_bracket",
            "right_square_bracket",
        }:
            return
        event.stop()
        event.prevent_default()
        select = self.vim_mode == "visual"
        motions = {
            "h": lambda: self.action_cursor_left(select),
            "j": lambda: self.action_cursor_down(select),
            "k": lambda: self.action_cursor_up(select),
            "l": lambda: self.action_cursor_right(select),
            "w": lambda: self.action_cursor_word_right(select),
            "b": lambda: self.action_cursor_word_left(select),
            "0": lambda: self.action_cursor_line_start(select),
            "dollar_sign": lambda: self.action_cursor_line_end(select),
            "$": lambda: self.action_cursor_line_end(select),
        }
        if key in motions:
            motions[key]()
            self._vim_pending = ""
        elif key in {"i", "a", "shift+i", "shift+a", "o", "shift+o"}:
            self.enter_insert_mode({"shift+i": "I", "shift+a": "A", "shift+o": "O"}.get(key, key))
        elif key == "g":
            if self._vim_pending == "g":
                self.action_cursor_document_start()
                self._vim_pending = ""
            else:
                self._vim_pending = "g"
        elif key == "shift+g":
            self.action_cursor_document_end()
            self._vim_pending = ""
        elif key == "d":
            if self.vim_mode == "visual":
                self._visual_action("delete")
            elif self._vim_pending == "d":
                self._delete_current_line()
                self._vim_pending = ""
            else:
                self._vim_pending = "d"
        elif key == "y":
            if self.vim_mode == "visual":
                self._visual_action("yank")
            elif self._vim_pending == "y":
                self._yank_current_line()
                self._vim_pending = ""
            else:
                self._vim_pending = "y"
        elif key == "x":
            self.read_only = False
            try:
                self.action_delete_right()
            finally:
                self.read_only = True
            self._vim_pending = ""
        elif key in {"p", "shift+p"}:
            self._paste(before=key == "shift+p")
            self._vim_pending = ""
        elif key == "u":
            self.action_undo()
        elif key == "ctrl+r":
            self.action_redo()
        elif key == "v":
            self.vim_mode = "normal" if self.vim_mode == "visual" else "visual"
            self.app._update_status()  # type: ignore[attr-defined]
        elif key == "escape":
            self.enter_normal_mode()
        else:
            self._vim_pending = ""


class CellEditor(TextFileEditor):
    async def action_leave_edit(self) -> None:
        self.app.arm_escape_close()  # type: ignore[attr-defined]
        if self.vim_mode == "insert":
            self.enter_normal_mode()
        else:
            await self.app._finish_edit()  # type: ignore[attr-defined]


class SqlEditor(TextArea):
    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("escape", "leave_edit", "Commands", priority=True),
    ]

    def action_leave_edit(self) -> None:
        self.app.leave_sql_editor()  # type: ignore[attr-defined]


class CommandInput(Input):
    BINDINGS = [
        Binding("escape", "cancel_command", "Cancel", priority=True),
        Binding("up", "previous_option", "Previous option", show=False, priority=True),
        Binding("down", "next_option", "Next option", show=False, priority=True),
        Binding("tab", "accept_suggestion", "Complete", priority=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(
            suggester=SuggestFromList(COMMAND_SUGGESTIONS, case_sensitive=False),
            **kwargs,
        )

    def action_cancel_command(self) -> None:
        self.app.close_command()  # type: ignore[attr-defined]

    def on_focus(self) -> None:
        if not self.value:
            self._suggestion = COMMAND_SUGGESTIONS[0]

    def action_accept_suggestion(self) -> None:
        self.app._accept_command_option()  # type: ignore[attr-defined]

    def action_previous_option(self) -> None:
        self.app._move_command_option(-1)  # type: ignore[attr-defined]

    def action_next_option(self) -> None:
        self.app._move_command_option(1)  # type: ignore[attr-defined]


class FuzzyFileSuggester(Suggester):
    def __init__(self, paths: list[str]) -> None:
        super().__init__(case_sensitive=False)
        self.paths = paths

    async def get_suggestion(self, value: str) -> Optional[str]:
        if not self.paths:
            return None
        if not value:
            return self.paths[0]

        def score(candidate: str) -> Optional[tuple[int, int, str]]:
            folded = candidate.casefold()
            positions = []
            offset = 0
            for character in value:
                position = folded.find(character, offset)
                if position < 0:
                    return None
                positions.append(position)
                offset = position + 1
            span = positions[-1] - positions[0]
            prefix_penalty = 0 if folded.startswith(value) else 1
            return prefix_penalty, span + len(candidate), folded

        matches = ((candidate, score(candidate)) for candidate in self.paths)
        ranked = [(candidate, rank) for candidate, rank in matches if rank is not None]
        return min(ranked, key=lambda item: item[1])[0] if ranked else None


class ContextualCommandSuggester(Suggester):
    """Complete the inspection kind before suggesting a specific operation."""

    def __init__(
        self, suggestions: tuple[str, ...], inspection_prefix: Optional[str] = None
    ) -> None:
        super().__init__(case_sensitive=False)
        self.suggestions = suggestions
        self.inspection_prefix = inspection_prefix

    async def get_suggestion(self, value: str) -> Optional[str]:
        folded = value.casefold()
        if self.inspection_prefix is not None:
            prefix = self.inspection_prefix.casefold()
            if folded.strip() == "inspect" and not value.endswith(" "):
                return self.inspection_prefix
            if folded == prefix:
                return None
        return next(
            (
                suggestion
                for suggestion in self.suggestions
                if suggestion.casefold().startswith(folded)
                and suggestion.casefold() != folded
            ),
            None,
        )


class ProjectFileInput(Input):
    BINDINGS = [
        Binding("escape", "cancel_file_picker", "Cancel", priority=True),
        Binding("tab", "accept_suggestion", "Complete", priority=True),
    ]

    def __init__(self, suggestions: list[str], **kwargs) -> None:
        super().__init__(
            suggester=FuzzyFileSuggester(suggestions),
            **kwargs,
        )

    def action_cancel_file_picker(self) -> None:
        self.app.close_file_picker()  # type: ignore[attr-defined]

    def action_accept_suggestion(self) -> None:
        if self._suggestion:
            self.value = self._suggestion
            self.cursor_position = len(self.value)


class ProjectTree(Tree[Path]):
    BINDINGS = [
        *Tree.BINDINGS,
        Binding("j", "cursor_down", "Next", show=False),
        Binding("k", "cursor_up", "Previous", show=False),
        Binding("h", "collapse_or_parent", "Collapse", show=False),
        Binding("l", "expand_or_open", "Expand", show=False),
        Binding("t", "open_in_tab", "Open in tab", show=False),
        Binding("alt+enter", "open_in_tab", "Open in tab", show=False, priority=True),
        Binding("escape", "arm_option_enter", "Option prefix", show=False, priority=True),
        Binding("enter", "select_or_open_tab", "Open", show=False, priority=True),
    ]

    _option_enter_armed = False

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is not None and node.is_expanded:
            node.collapse()
        else:
            self.action_cursor_parent()

    def action_expand_or_open(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand:
            node.expand()
        else:
            self.action_select_cursor()

    def action_open_in_tab(self) -> None:
        node = self.cursor_node
        if node is not None and node.data is not None and Path(node.data).is_file():
            self.app.open_project_file_in_tab(Path(node.data))  # type: ignore[attr-defined]

    def action_arm_option_enter(self) -> None:
        # Terminals without an enhanced keyboard protocol encode Option+Enter
        # as Escape followed by Enter rather than a distinct Alt+Enter key.
        self._option_enter_armed = True
        self.set_timer(0.35, self._disarm_option_enter)

    def _disarm_option_enter(self) -> None:
        self._option_enter_armed = False

    def action_select_or_open_tab(self) -> None:
        if self._option_enter_armed:
            self._option_enter_armed = False
            self.action_open_in_tab()
        else:
            self.action_select_cursor()

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 3 and "line" in event.style.meta:
            node = self.get_node_at_line(event.style.meta["line"])
            if node is not None and node.data is not None:
                self.move_cursor(node)
                path = Path(node.data)
                folder = path if path.is_dir() else path.parent
                self.app.prompt_new_file(folder)  # type: ignore[attr-defined]
                event.stop()
                return
        await super()._on_mouse_down(event)


class TabBar(Tabs):
    async def _on_tab_clicked(self, event: Tab.Clicked) -> None:
        await super()._on_tab_clicked(event)
        if event.tab.id is None:
            return
        try:
            index = int(event.tab.id.removeprefix("document-tab-"))
        except ValueError:
            return
        await self.app._activate_tab(index)  # type: ignore[attr-defined]


class NotebookApp(App[None]):
    TITLE = "notebookvim"
    CSS = """
    Screen { background: $surface; }
    #workspace { height: 1fr; }
    #tabs {
        height: 2;
        background: $surface-lighten-1; color: $text-muted;
    }
    #files {
        width: 32; min-width: 20; height: 100%;
        border-right: solid $surface-lighten-2;
        background: $surface-darken-1;
    }
    #document-column { width: 1fr; height: 100%; layout: horizontal; }
    #notebook { width: 1fr; height: 100%; padding: 1 2; }
    #empty-workspace {
        width: 100%; height: 100%;
        content-align: center middle; text-align: center; color: $text-muted;
    }
    #terminal-pane {
        width: 45%; min-width: 30; height: 100%; min-height: 8;
        border-left: solid $surface-lighten-2;
        background: $terminal-background; color: $terminal-foreground;
    }
    #document-column.terminal-below { layout: vertical; }
    #document-column.terminal-below #notebook { width: 100%; height: 1fr; }
    #document-column.terminal-below #terminal-pane {
        width: 100%; min-width: 0; height: 40%;
        border-left: none; border-top: solid $surface-lighten-2;
    }
    #terminal-output {
        height: 1fr; padding: 0 1;
        background: $terminal-background; color: $terminal-foreground;
    }
    #terminal-input {
        height: 3; border: tall $surface-lighten-2; padding: 0 1;
        background: $terminal-background; color: $terminal-foreground;
    }
    #ai-pane {
        width: 45%; min-width: 32; height: 100%; min-height: 8;
        border-left: solid $surface-lighten-2; background: $surface-darken-1;
    }
    #ai-header { height: 3; padding: 1; background: $panel; color: $text-muted; }
    #ai-output { height: 1fr; padding: 1 2; }
    #ai-input { height: 3; border: tall $accent; padding: 0 1; }
    #document-column.ai-below { layout: vertical; }
    #document-column.ai-below #notebook { width: 100%; height: 1fr; }
    #document-column.ai-below #ai-pane {
        width: 100%; min-width: 0; height: 42%;
        border-left: none; border-top: solid $surface-lighten-2;
    }
    #inspection-pane {
        width: 45%; min-width: 32; height: 100%; padding: 1;
        border-left: solid $surface-lighten-2; background: $surface-darken-1;
    }
    #document-column.inspection-below { layout: vertical; }
    #document-column.inspection-below #notebook { width: 100%; height: 1fr; }
    #document-column.inspection-below #inspection-pane {
        width: 100%; min-width: 0; height: 42%;
        border-left: none; border-top: solid $surface-lighten-2;
    }
    CellView {
        width: 100%; height: auto; min-height: 5;
        margin: 0 0 1 0; padding: 1 2;
        border: round $surface-lighten-2;
        background: $surface-darken-1;
    }
    CellView.selected {
        background: $panel; border: round $accent;
    }
    CellView.running { border: round $warning; }
    TextArea.cell-editor {
        width: 100%; min-height: 6; height: auto;
        margin-bottom: 1; border: round $accent;
    }
    TextArea.text-file-editor {
        width: 100%; height: 100%; border: none;
    }
    TextArea.sql-editor {
        width: 100%; height: 45%; min-height: 8;
        margin-bottom: 1; border: round $accent;
    }
    QueryResultView { width: 100%; height: auto; min-height: 8; padding: 1; }
    DatasetProfileView { width: 100%; height: auto; padding: 1; }
    RemoteReportView { width: 100%; height: auto; padding: 1; }
    InspectionReportView { width: 100%; height: auto; padding: 1; }
    #completion-menu {
        width: 48; height: auto; max-height: 8;
        margin: -1 0 1 4; padding: 0 1;
        background: $panel; border: round $accent;
    }
    #status {
        dock: bottom; height: 1; padding: 0 1;
        background: $status-background; color: $status-foreground;
    }
    #command {
        dock: bottom; height: 3; border: tall $accent; padding: 0 1;
    }
    #command-suggestions {
        dock: bottom; width: 100%; height: auto; max-height: 7;
        border: round $accent; background: $panel;
    }
    #file-picker {
        dock: top; height: 3; border: tall $accent; padding: 0 1;
    }
    """
    BINDINGS = [
        ("down", "next_cell", "Next"),
        ("up", "previous_cell", "Previous"),
        ("colon", "command", "Command"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+c", "interrupt", "Interrupt"),
        Binding("ctrl+e", "toggle_files", "Files", priority=True),
        Binding("ctrl+p", "find_file", "Find", priority=True),
        Binding("ctrl+tab", "toggle_file_focus", "Files/editor", priority=True),
        Binding("shift+tab", "next_tab", "Next tab", priority=True),
        Binding("ctrl+shift+tab", "previous_tab", "Previous tab", priority=True),
        Binding("ctrl+w", "close_tab", "Close tab", priority=True),
        Binding("left_square_bracket", "previous_tab", "Previous tab"),
        Binding("right_square_bracket", "next_tab", "Next tab"),
        Binding("ctrl+q", "request_quit", "Quit", priority=True),
    ]

    def __init__(
        self,
        notebook: Notebook,
        workspace_root: Optional[Path] = None,
        initial_path: Optional[Path] = None,
        project_open: bool = True,
    ) -> None:
        super().__init__()
        for app_theme in APP_THEMES.values():
            self.register_theme(app_theme)
        saved_theme = load_theme()
        self._notebookvim_theme = saved_theme if saved_theme in THEME_NAMES else DEFAULT_THEME
        self.syntax_theme = RICH_SYNTAX_THEMES[self._notebookvim_theme]
        self.theme = self._notebookvim_theme
        terminal_theme = TERMINAL_THEMES[self._notebookvim_theme]
        self.ansi_theme_dark = terminal_theme
        self.ansi_theme_light = terminal_theme
        self.notebook = notebook
        self.workspace_root = Path(workspace_root or notebook.path.parent).resolve()
        self.project_open = project_open
        self.initial_path = Path(initial_path).resolve() if initial_path is not None else None
        self.project_paths = project_files(self.workspace_root) if project_open else []
        self.selected = 0
        self.editor: Optional[CellEditor] = None
        self.text_buffer: Optional[TextBuffer] = None
        self.text_editor: Optional[TextArea] = None
        self.parquet_preview: Optional[ParquetPreview] = None
        self.sql_document: Optional[SqlDocument] = None
        self.sql_editor: Optional[TextArea] = None
        self.dataset_profile: Optional[DatasetProfile] = None
        self.remote_report: Optional[RemoteReport] = None
        self.inspection_report: Optional[InspectionReport] = None
        self.completion_menu: Optional[Static] = None
        self._completion_revision = 0
        self._completions: list[str] = []
        self._command_option_values: list[str] = []
        self.kernel = Kernel(notebook.kernel_name)
        self.tabs = ([
            DocumentTab(
                path=notebook.path.resolve(),
                notebook=notebook,
                kernel=self.kernel,
            )
        ] if project_open else [])
        self.active_tab_index = 0 if project_open else -1
        self._tab_activation_lock = asyncio.Lock()
        self._running_cells: set[int] = set()
        self._collapsed_outputs: set[str] = set()
        self._quit_armed = False
        self._close_armed_tab: Optional[DocumentTab] = None
        self.terminal_pane = TerminalPane(self.workspace_root, id="terminal-pane")
        self.ai_pane = AIPane(
            self.workspace_root,
            provider=load_ai_provider(),
            model=load_ai_model(),
            id="ai-pane",
        )
        self.inspection_pane = InspectionPane()
        self.terminal_placement = "side"
        self.databricks_connection: Optional[DatabricksConnection] = None
        self.git = GitService(self.workspace_root)
        self.data_workspace: Optional[DuckDBWorkspace] = None
        self.remote: Optional[DatabricksRemote] = None
        self.last_remote_run_id: Optional[int] = None
        self.vim_register = ""
        self.vim_register_linewise = False
        self._vim_cell_register: Optional[Cell] = None
        self._vim_pending_key = ""
        self._escape_close_armed = False
        self._sql_document_count = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield TabBar(
            *(Tab(tab.display_name, id=f"document-tab-{index}") for index, tab in enumerate(self.tabs)),
            id="tabs",
        )
        yield ProjectFileInput(
            [str(path.relative_to(self.workspace_root)) for path in self.project_paths],
            placeholder="Find project file",
            id="file-picker",
        )
        with Horizontal(id="workspace"):
            yield self._project_tree()
            with Vertical(id="document-column"):
                with VerticalScroll(id="notebook"):
                    for index in range(len(self.notebook.cells) if self.tabs else 0):
                        yield self._new_view(index)
                yield self.terminal_pane
                yield self.ai_pane
                yield self.inspection_pane
        yield Static(id="status")
        yield OptionList(id="command-suggestions", compact=True)
        yield CommandInput(placeholder="Command", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self._update_sub_title()
        if self.tabs:
            self._select(0)
        self.query_one("#command", CommandInput).display = False
        self.query_one("#command-suggestions", OptionList).display = False
        self.query_one("#file-picker", ProjectFileInput).display = False
        self.query_one("#terminal-pane", TerminalPane).display = False
        self.query_one("#ai-pane", AIPane).display = False
        self.query_one("#inspection-pane", InspectionPane).display = False
        self.query_one("#document-column", Vertical).add_class("terminal-side")
        self._refresh_tabs()
        self._update_status("IDLE")
        if not self.project_open:
            self.run_worker(self._show_empty_workspace())
        if self.initial_path is not None and self.initial_path != self.notebook.path.resolve():
            self.run_worker(self._open_project_file(self.initial_path))

    def _configure_editor_theme(self, editor: TextArea) -> None:
        custom_theme = EDITOR_THEMES.get(self._notebookvim_theme)
        if custom_theme is not None:
            editor.register_theme(copy.deepcopy(custom_theme))
        editor.theme = EDITOR_THEME_NAMES[self._notebookvim_theme]

    def action_set_app_theme(self, name: str) -> None:
        normalized = name.strip().lower()
        if normalized not in THEME_NAMES:
            self.notify(
                f"Unknown theme: {name or '—'}\nAvailable: {', '.join(THEME_NAMES)}",
                title="Theme",
                severity="warning",
            )
            return
        self._notebookvim_theme = normalized
        self.syntax_theme = RICH_SYNTAX_THEMES[normalized]
        terminal_theme = TERMINAL_THEMES[normalized]
        self.ansi_theme_dark = terminal_theme
        self.ansi_theme_light = terminal_theme
        self.theme = normalized
        palette = APP_THEMES[normalized].variables
        status = self.query_one("#status", Static)
        status.styles.background = palette["status-background"]
        status.styles.color = palette["status-foreground"]
        for editor in self.query(TextArea):
            self._configure_editor_theme(editor)
        for view in self.query(CellView):
            view.refresh(layout=True)
        self.terminal_pane.refresh(layout=True)
        try:
            save_theme(normalized)
        except OSError as exc:
            self.notify(f"Theme changed, but preference could not be saved: {exc}", severity="warning")
        self.notify(
            f"Theme: {normalized}\nFont: {THEME_FONTS[normalized]} "
            "(configure in terminal profile)",
            title="Appearance",
        )

    def _project_tree(self) -> ProjectTree:
        label = self.workspace_root.name if self.project_open else "No project"
        tree = ProjectTree(label, self.workspace_root, id="files")
        self._populate_project_tree(tree)
        return tree

    def _populate_project_tree(self, tree: ProjectTree) -> None:
        structure = {"directories": {}, "files": []}
        for file_path in self.project_paths:
            relative = file_path.relative_to(self.workspace_root)
            current = structure
            for part in relative.parts[:-1]:
                directories = current["directories"]
                if part not in directories:
                    directories[part] = {"directories": {}, "files": []}
                current = directories[part]
            current["files"].append(file_path)

        def add_children(parent: Tree.Node[Path], branch: dict, relative: Path) -> None:
            for name in sorted(branch["directories"], key=str.lower):
                child_relative = relative / name
                child = parent.add(name, self.workspace_root / child_relative)
                add_children(child, branch["directories"][name], child_relative)
            for file_path in sorted(
                branch["files"], key=lambda path: path.name.lower()
            ):
                parent.add_leaf(file_path.name, file_path)

        add_children(tree.root, structure, Path())
        tree.root.expand()

    def _refresh_project_files(self) -> None:
        """Rescan files created while notebookvim is running and rebuild navigation."""
        self.project_paths = project_files(self.workspace_root)
        tree = self.query_one("#files", ProjectTree)
        tree.root.remove_children()
        self._populate_project_tree(tree)
        tree.refresh(layout=True)
        suggestions = [
            str(path.relative_to(self.workspace_root)) for path in self.project_paths
        ]
        picker = self.query_one("#file-picker", ProjectFileInput)
        picker.suggester = FuzzyFileSuggester(suggestions)
        picker._suggestion = None

    def _update_sub_title(self) -> None:
        if not self.tabs:
            self.sub_title = "No file open"
            return
        path = self._active_path
        try:
            self.sub_title = str(path.resolve().relative_to(self.workspace_root))
        except ValueError:
            self.sub_title = path.name

    @property
    def _active_tab(self) -> DocumentTab:
        return self.tabs[self.active_tab_index]

    def _refresh_tabs(self) -> None:
        tab_bar = self.query_one("#tabs", TabBar)
        if not self.tabs:
            return
        rendered_tabs = list(tab_bar.query(Tab))
        for index, tab in enumerate(self.tabs):
            marker = "●" if tab.dirty else ""
            if index < len(rendered_tabs):
                rendered_tabs[index].label = f" {tab.display_name}{marker} "
        active_id = f"document-tab-{self.active_tab_index}"
        if tab_bar.active != active_id:
            tab_bar.active = active_id

    def _sync_active_tab(self) -> None:
        if not self.tabs:
            return
        tab = self._active_tab
        if tab.sql_document is not None and self.sql_editor is not None:
            tab.sql_document.query = self.sql_editor.text
        if tab.notebook is not None and self.text_buffer is None:
            tab.selected = self.selected
            tab.collapsed_outputs = set(self._collapsed_outputs)

    def action_toggle_file_focus(self) -> None:
        if self.editor is not None:
            return
        tree = self.query_one("#files", Tree)
        if tree.has_focus:
            self._focus_document()
        else:
            tree.display = True
            tree.focus()

    def action_next_tab(self) -> None:
        self._queue_tab_switch(1)

    def action_previous_tab(self) -> None:
        self._queue_tab_switch(-1)

    def action_close_tab(self) -> None:
        self.run_worker(self._close_active_tab())

    def arm_escape_close(self) -> None:
        self._escape_close_armed = True

    async def _close_active_tab(self) -> None:
        async with self._tab_activation_lock:
            if not self.tabs:
                return
            if self._running_cells:
                self.notify("Wait for execution to finish before closing this tab", severity="warning")
                return
            if self.editor is not None:
                await self._finish_edit()
            self._sync_active_tab()
            closing = self._active_tab
            if closing.dirty and self._close_armed_tab is not closing:
                self._close_armed_tab = closing
                self.notify(
                    "Unsaved changes — save first, or close the tab again to discard them",
                    severity="warning",
                )
                return
            closing_index = self.active_tab_index
            if closing.kernel is not None:
                await closing.kernel.shutdown()
            self.tabs.pop(closing_index)
            self._close_armed_tab = None
            self.active_tab_index = min(closing_index, len(self.tabs) - 1)
            tab_bar = self.query_one("#tabs", TabBar)
            await tab_bar.clear()
            if not self.tabs:
                self.active_tab_index = -1
                await self._show_empty_workspace()
                return
            for index, tab in enumerate(self.tabs):
                await tab_bar.add_tab(Tab(tab.display_name, id=f"document-tab-{index}"))
            await self._activate_tab_unlocked(self.active_tab_index, force=True)

    def action_open_selected_in_tab(self) -> None:
        tree = self.query_one("#files", ProjectTree)
        node = tree.cursor_node
        if node is not None and node.data is not None and Path(node.data).is_file():
            self.open_project_file_in_tab(Path(node.data))
        else:
            self.notify("Select a file in the browser first", severity="warning")

    def _queue_tab_switch(self, offset: int) -> None:
        if len(self.tabs) < 2 or self.editor is not None:
            return
        target = (self.active_tab_index + offset) % len(self.tabs)
        self.run_worker(self._activate_tab(target))

    async def _activate_tab(self, index: int, force: bool = False) -> None:
        async with self._tab_activation_lock:
            await self._activate_tab_unlocked(index, force)

    async def _activate_tab_unlocked(self, index: int, force: bool = False) -> None:
        if not 0 <= index < len(self.tabs):
            return
        if index == self.active_tab_index and not force:
            self._focus_document()
            return
        if self._running_cells:
            self.notify("Wait for execution to finish before switching tabs", severity="warning")
            return
        if self.editor is not None:
            await self._finish_edit()
        await self._clear_completions()
        if not force:
            self._sync_active_tab()
        self.active_tab_index = index
        tab = self._active_tab
        notebook_view = self.query_one("#notebook", VerticalScroll)
        await notebook_view.remove_children()
        self.sql_document = None
        self.sql_editor = None
        self.dataset_profile = None
        self.remote_report = None
        self.inspection_report = None
        if tab.text_buffer is not None:
            self.text_buffer = tab.text_buffer
            self.parquet_preview = None
            self.text_editor = await self._mount_text_editor(
                notebook_view, tab.text_buffer, read_only=tab.read_only
            )
            self.text_editor.focus()
        elif tab.parquet_preview is not None:
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = tab.parquet_preview
            preview = ParquetPreviewView(tab.parquet_preview)
            await notebook_view.mount(preview)
            preview.focus()
        elif tab.sql_document is not None:
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = None
            self.sql_document = tab.sql_document
            editor = SqlEditor.code_editor(
                tab.sql_document.query, language="sql", id="sql-editor"
            )
            self._configure_editor_theme(editor)
            editor.add_class("sql-editor")
            editor.border_title = "DuckDB SQL"
            self.sql_editor = editor
            await notebook_view.mount(editor, QueryResultView(tab.sql_document.result))
            editor.focus()
        elif tab.dataset_profile is not None:
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = None
            self.dataset_profile = tab.dataset_profile
            view = DatasetProfileView(tab.dataset_profile)
            await notebook_view.mount(view)
            view.focus()
        elif tab.remote_report is not None:
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = None
            self.remote_report = tab.remote_report
            view = RemoteReportView(tab.remote_report)
            await notebook_view.mount(view)
            view.focus()
        elif tab.inspection_report is not None:
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = None
            self.inspection_report = tab.inspection_report
            view = InspectionReportView(tab.inspection_report)
            await notebook_view.mount(view)
            view.focus()
        else:
            assert tab.notebook is not None
            self.text_buffer = None
            self.text_editor = None
            self.parquet_preview = None
            self.notebook = tab.notebook
            if tab.kernel is None:
                tab.kernel = Kernel(self.notebook.kernel_name)
                self._configure_databricks_kernel(tab.kernel)
            self.kernel = tab.kernel
            self.selected = tab.selected
            self._collapsed_outputs = set(tab.collapsed_outputs)
            await notebook_view.mount(
                *(self._new_view(cell_index) for cell_index in range(len(self.notebook.cells)))
            )
            self._select(self.selected)
        self._quit_armed = False
        self._close_armed_tab = None
        self._update_sub_title()
        self._refresh_tabs()
        self._update_status()

    @property
    def _notebook_active(self) -> bool:
        return bool(self.tabs and self._active_tab.notebook is not None)

    @property
    def _document_dirty(self) -> bool:
        if not self.tabs:
            return False
        if self.text_buffer is not None:
            return self.text_buffer.dirty
        return bool(self._active_tab.notebook and self.notebook.dirty)

    @property
    def _active_path(self) -> Path:
        if not self.tabs:
            return self.workspace_root
        if self.text_buffer is not None:
            return self.text_buffer.path
        return self._active_tab.path.resolve()

    def _focus_document(self) -> None:
        if not self.tabs:
            empty = self.query_one("#empty-workspace", EmptyWorkspace)
            empty.focus()
            return
        if self.text_editor is not None:
            self.text_editor.focus()
        elif self.sql_editor is not None:
            self.sql_editor.focus()
        elif self.dataset_profile is not None:
            self.query_one("#dataset-profile", DatasetProfileView).focus(scroll_visible=True)
        elif self.remote_report is not None:
            self.query_one("#remote-report", RemoteReportView).focus(scroll_visible=True)
        elif self.inspection_report is not None:
            self.query_one("#inspection-report", InspectionReportView).focus(scroll_visible=True)
        elif self.parquet_preview is not None:
            self.query_one("#parquet-preview", ParquetPreviewView).focus(scroll_visible=True)
        else:
            self._view(self.selected).focus(scroll_visible=True)

    async def _show_empty_workspace(self) -> None:
        notebook_view = self.query_one("#notebook", VerticalScroll)
        await notebook_view.remove_children()
        self.text_buffer = None
        self.text_editor = None
        self.parquet_preview = None
        self.sql_document = None
        self.sql_editor = None
        self.dataset_profile = None
        self.remote_report = None
        self.inspection_report = None
        self.editor = None
        empty = EmptyWorkspace()
        await notebook_view.mount(empty)
        self.sub_title = "No file open"
        empty.focus()
        self._update_status()

    def action_terminal_open(self, placement: str = "side") -> None:
        if placement not in {"side", "below"}:
            placement = "side"
        self.action_inspection_close(focus_document=False)
        self.action_ai_close(focus_document=False)
        document = self.query_one("#document-column", Vertical)
        document.remove_class("terminal-side", "terminal-below")
        document.add_class(f"terminal-{placement}")
        self.terminal_placement = placement
        pane = self.query_one("#terminal-pane", TerminalPane)
        pane.display = True
        pane.query_one("#terminal-input", TerminalInput).focus()
        self.query_one("#status", Static).update(
            f" TERMINAL {placement.upper()} │ Escape: editor │ Up/Down: history │ "
            "Ctrl+L: clear │ Ctrl+C: interrupt"
        )

    def action_terminal_close(self) -> None:
        self.query_one("#terminal-pane", TerminalPane).display = False
        self._focus_document()
        self._update_status()

    def action_ai_open(self, placement: str = "side") -> None:
        if placement not in {"side", "below"}:
            placement = "side"
        self.action_terminal_close()
        self.action_inspection_close(focus_document=False)
        document = self.query_one("#document-column", Vertical)
        document.remove_class(
            "terminal-side", "terminal-below", "inspection-side", "inspection-below",
            "ai-side", "ai-below",
        )
        document.add_class(f"ai-{placement}")
        pane = self.query_one("#ai-pane", AIPane)
        pane.display = True
        pane.query_one("#ai-input", AIInput).focus()
        self.query_one("#status", Static).update(
            f" AI {placement.upper()} · {pane.provider.name} │ Enter: send │ "
            "Ctrl+C: cancel │ Escape: editor"
        )

    def action_ai_close(self, focus_document: bool = True) -> None:
        pane = self.query_one("#ai-pane", AIPane)
        pane.display = False
        document = self.query_one("#document-column", Vertical)
        document.remove_class("ai-side", "ai-below")
        if focus_document:
            self._focus_document()
            self._update_status()

    def focus_document_from_ai(self) -> None:
        self._focus_document()
        self._update_status()

    def ai_context(self) -> str:
        """Return a bounded snapshot of the active document for an AI prompt."""
        if not self.tabs:
            return f"Workspace: {self.workspace_root}"
        path = self._active_path
        parts = [f"Workspace: {self.workspace_root}", f"Active file: {path}"]
        if self._notebook_active and self.notebook.cells:
            cell = self.notebook.cells[self.selected]
            source = self.editor.text if self.editor is not None else cell.source
            parts.extend(
                [f"Selected cell: {self.selected + 1} ({cell.cell_type.value})", source[:12_000]]
            )
        elif self.text_buffer is not None:
            text = self.text_editor.text if self.text_editor is not None else self.text_buffer.text
            parts.append(text[:12_000])
        elif self.sql_document is not None:
            query = self.sql_editor.text if self.sql_editor is not None else self.sql_document.query
            parts.append(query[:12_000])
        return "\n".join(parts)

    def action_inspection_close(self, focus_document: bool = True) -> None:
        pane = self.query_one("#inspection-pane", InspectionPane)
        pane.display = False
        document = self.query_one("#document-column", Vertical)
        document.remove_class("inspection-side", "inspection-below")
        if focus_document:
            self._focus_document()
            self._update_status()

    def _open_inspection_pane(self, report: InspectionReport, placement: str) -> None:
        self.action_terminal_close()
        self.action_ai_close(focus_document=False)
        document = self.query_one("#document-column", Vertical)
        document.remove_class("terminal-side", "terminal-below", "inspection-side", "inspection-below")
        document.add_class(f"inspection-{placement}")
        pane = self.query_one("#inspection-pane", InspectionPane)
        pane.report = report
        pane.display = True
        pane.refresh(layout=True)
        pane.focus()
        self.query_one("#status", Static).update(
            f" INSPECT {placement.upper()} │ Escape: close │ arrows/Page Up/Page Down: scroll"
        )

    def focus_document_from_terminal(self) -> None:
        self._focus_document()
        self._update_status()

    def leave_text_editor(self) -> None:
        if self.text_editor is None or self.text_buffer is None:
            return
        if isinstance(self.text_editor, TextFileEditor):
            self.text_editor.enter_normal_mode()

    def leave_sql_editor(self) -> None:
        if self.sql_editor is None or self.sql_document is None:
            return
        self.sql_document.query = self.sql_editor.text
        self.query_one("#tabs", TabBar).focus()
        self._update_status()

    def _view(self, index: int) -> CellView:
        return self.query_one(f"#cell-{index}", CellView)

    def _cell_key(self, index: int) -> str:
        return self.notebook.cells[index].cell_id or f"cell-{index}"

    def _new_view(self, index: int) -> CellView:
        return CellView(
            self.notebook,
            index,
            output_collapsed=self._cell_key(index) in self._collapsed_outputs,
        )

    async def _rebuild_cells(self, selected: int) -> None:
        notebook_view = self.query_one("#notebook", VerticalScroll)
        await notebook_view.remove_children()
        await notebook_view.mount(
            *(self._new_view(index) for index in range(len(self.notebook.cells)))
        )
        self.selected = max(0, min(selected, len(self.notebook.cells) - 1))
        self._select(self.selected)

    def _select(self, index: int) -> None:
        if not self.notebook.cells:
            return
        self._view(self.selected).remove_class("selected")
        self.selected = max(0, min(index, len(self.notebook.cells) - 1))
        view = self._view(self.selected)
        view.add_class("selected")
        view.focus(scroll_visible=True)
        self._update_status()

    def _update_status(self, kernel_state: Optional[str] = None) -> None:
        self._refresh_tabs()
        if not self.tabs:
            self.query_one("#status", Static).update(self._shortcut_status("READY"))
            return
        if self.text_buffer is not None:
            dirty = " ●" if self.text_buffer.dirty else ""
            mode = (
                self.text_editor.vim_mode.upper()
                if isinstance(self.text_editor, TextFileEditor)
                else "NORMAL"
            )
            self.query_one("#status", Static).update(
                f" {mode} TEXT │ Ctrl+S: save │ Ctrl+P: find │ "
                f"{self.text_buffer.path.name}{dirty}"
            )
            self.query_one("#status", Static).update(self._shortcut_status(f"{mode} TEXT"))
            return
        if self.parquet_preview is not None:
            self.query_one("#status", Static).update(self._shortcut_status("PARQUET"))
            return
        if self.sql_document is not None:
            self.query_one("#status", Static).update(self._shortcut_status("SQL"))
            return
        if self.dataset_profile is not None:
            self.query_one("#status", Static).update(self._shortcut_status("PROFILE"))
            return
        if self.remote_report is not None:
            self.query_one("#status", Static).update(self._shortcut_status("DATABRICKS"))
            return
        if self.inspection_report is not None:
            self.query_one("#status", Static).update(self._shortcut_status("INSPECT"))
            return
        if self.editor is not None:
            mode = self.editor.vim_mode.upper()
            self.query_one("#status", Static).update(self._shortcut_status(f"{mode} CELL"))
            return
        self.query_one("#status", Static).update(self._shortcut_status("NORMAL"))

    @staticmethod
    def _shortcut_status(mode: str) -> str:
        return (
            f" {mode} │ : cmd │ :help │ Ctrl+E files │ i edit │ "
            "Ctrl+S save │ Ctrl+Q exit"
        )

    def action_toggle_files(self) -> None:
        if self.editor is not None:
            return
        tree = self.query_one("#files", Tree)
        if not tree.display:
            tree.display = True
            tree.focus()
        elif not tree.has_focus:
            tree.focus()
        else:
            tree.display = False
            self._focus_document()

    def action_find_file(self) -> None:
        if self.editor is not None:
            return
        if not self.project_open:
            self.notify("Open a project first with :project open path", severity="warning")
            return
        picker = self.query_one("#file-picker", ProjectFileInput)
        picker.value = ""
        picker.display = True
        picker.focus()
        self.query_one("#status", Static).update(
            " FIND FILE │ Type a relative path │ Tab: complete │ Escape: cancel"
        )

    def close_file_picker(self) -> None:
        picker = self.query_one("#file-picker", ProjectFileInput)
        picker.value = ""
        picker.display = False
        self._focus_document()
        self._update_status()

    async def on_tree_node_selected(self, event: Tree.NodeSelected[Path]) -> None:
        if event.control.id != "files" or event.node.data is None:
            return
        path = Path(event.node.data)
        if path.is_dir():
            return
        await self._open_project_file(path)

    def open_project_file_in_tab(self, path: Path) -> None:
        self.run_worker(self._open_project_file(path, new_tab=True))

    async def _open_file_from_command(self, relative_path: str, new_tab: bool = False) -> None:
        if not self.project_open:
            self.notify("Open a project first with :project open path", severity="warning")
            return
        relative_path = relative_path.strip()
        if (
            len(relative_path) >= 2
            and relative_path[0] == relative_path[-1]
            and relative_path[0] in {"'", '"'}
        ):
            relative_path = relative_path[1:-1]
        path = (self.workspace_root / relative_path).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            self.notify("Use a path inside the current project", severity="warning")
            return
        if not path.is_file():
            self.notify(f"File not found: {relative_path}", severity="warning")
            return
        await self._open_project_file(path, new_tab=new_tab)

    def prompt_new_file(self, folder: Path) -> None:
        if not self.project_open:
            self.notify("Open a project first with :project open path", severity="warning")
            return

        def create_from_name(name: Optional[str]) -> None:
            if name:
                relative_folder = folder.resolve().relative_to(self.workspace_root)
                self._create_project_file(str(relative_folder / name))

        self.push_screen(NewFileModal(folder.resolve(), self.workspace_root), create_from_name)

    def _create_project_file(self, relative_path: str) -> Optional[Path]:
        if not self.project_open:
            self.notify("Open a project first with :project open path", severity="warning")
            return None
        relative_path = relative_path.strip()
        if (
            len(relative_path) >= 2
            and relative_path[0] == relative_path[-1]
            and relative_path[0] in {"'", '"'}
        ):
            relative_path = relative_path[1:-1]
        if not relative_path:
            self.notify("Provide a filename", severity="warning")
            return None
        path = (self.workspace_root / relative_path).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            self.notify("Use a path inside the current project", severity="warning")
            return None
        if not path.parent.is_dir():
            self.notify(f"Folder not found: {path.parent}", severity="warning")
            return None
        if path.exists():
            self.notify(f"File already exists: {relative_path}", severity="warning")
            return None
        try:
            path.touch(exist_ok=False)
        except OSError as exc:
            self.notify(f"Could not create file: {exc}", severity="error")
            return None
        self._refresh_project_files()
        self.notify(f"Created {path.relative_to(self.workspace_root)}")
        return path

    async def _open_project_from_command(self, folder: str) -> None:
        folder = folder.strip()
        if (
            len(folder) >= 2
            and folder[0] == folder[-1]
            and folder[0] in {"'", '"'}
        ):
            folder = folder[1:-1]
        candidate = Path(folder).expanduser()
        target = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace_root / candidate).resolve()
        )
        if not target.is_dir():
            self.notify(f"Folder not found: {folder}", severity="warning")
            return
        if self.project_open and target == self.workspace_root:
            self.notify("That project is already open")
            return
        if self._running_cells:
            self.notify("Wait for execution to finish before switching projects", severity="warning")
            return
        if self.editor is not None:
            await self._finish_edit()
        self._sync_active_tab()
        if any(tab.dirty for tab in self.tabs):
            self.notify(
                "Save or close unsaved files before switching projects",
                severity="warning",
            )
            return
        await self._shutdown_all_kernels()
        if self.data_workspace is not None:
            self.data_workspace.close()
            self.data_workspace = None
        self.tabs.clear()
        self.active_tab_index = -1
        self.workspace_root = target
        self.project_open = True
        self.project_paths = project_files(target)
        self.git = GitService(target)
        self.remote = None
        self._sql_document_count = 0
        self.terminal_pane.set_workspace(target)
        self.ai_pane.workspace_root = target
        tree = self.query_one("#files", ProjectTree)
        tree.reset(target.name, target)
        self._populate_project_tree(tree)
        tree.root.expand()
        tree.refresh(layout=True)
        picker = self.query_one("#file-picker", ProjectFileInput)
        picker.suggester = FuzzyFileSuggester(
            [str(path.relative_to(target)) for path in self.project_paths]
        )
        picker._suggestion = None
        await self.query_one("#tabs", TabBar).clear()
        await self._show_empty_workspace()
        self.notify(f"Opened project: {target}", title="Project")

    async def _close_project(self) -> None:
        if not self.project_open:
            self.notify("No project is open")
            return
        if self._running_cells:
            self.notify("Wait for execution to finish before closing the project", severity="warning")
            return
        if self.editor is not None:
            await self._finish_edit()
        self._sync_active_tab()
        if any(tab.dirty for tab in self.tabs):
            self.notify(
                "Save or close unsaved files before closing the project",
                severity="warning",
            )
            return
        await self._shutdown_all_kernels()
        if self.data_workspace is not None:
            self.data_workspace.close()
            self.data_workspace = None
        self.tabs.clear()
        self.active_tab_index = -1
        self.project_paths = []
        self.project_open = False
        self.remote = None
        self._sql_document_count = 0
        tree = self.query_one("#files", ProjectTree)
        tree.reset("No project", self.workspace_root)
        tree.refresh(layout=True)
        picker = self.query_one("#file-picker", ProjectFileInput)
        picker.suggester = FuzzyFileSuggester([])
        picker._suggestion = None
        await self.query_one("#tabs", TabBar).clear()
        await self._show_empty_workspace()
        self.notify("Project closed", title="Project")

    async def _open_project_file(self, path: Path, new_tab: bool = False) -> None:
        path = path.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            self.notify("That file is outside the current project", severity="error")
            return
        existing = next((index for index, tab in enumerate(self.tabs) if tab.path == path), None)
        if existing is not None:
            await self._activate_tab(existing)
            return
        if self.editor is not None:
            await self._finish_edit()
        if not new_tab and self._document_dirty:
            self.notify(
                "Save the current file before opening another file",
                severity="warning",
            )
            return
        if self._running_cells:
            self.notify("Wait for execution to finish before switching files", severity="warning")
            return
        try:
            if path.suffix.lower() == ".ipynb":
                notebook = load_notebook(path)
                tab = DocumentTab(
                    path=path,
                    notebook=notebook,
                    kernel=Kernel(notebook.kernel_name),
                )
                self._configure_databricks_kernel(tab.kernel)
            elif is_supported_text_file(path):
                buffer = load_text_buffer(path)
                tab = DocumentTab(path=path, text_buffer=buffer)
            elif is_parquet_file(path):
                preview = await asyncio.to_thread(load_parquet_preview, path)
                tab = DocumentTab(path=path, parquet_preview=preview)
            else:
                self.notify(f"Unsupported file type: {path.name}", severity="warning")
                return
        except Exception as exc:
            self.notify(str(exc), title="Open failed", severity="error")
            return
        if not self.tabs:
            self.tabs.append(tab)
            self.active_tab_index = 0
            await self.query_one("#tabs", TabBar).add_tab(
                Tab(path.name, id="document-tab-0")
            )
            await self._activate_tab(0, force=True)
        elif new_tab:
            self.tabs.append(tab)
            target = len(self.tabs) - 1
            await self.query_one("#tabs", TabBar).add_tab(
                Tab(path.name, id=f"document-tab-{target}")
            )
            await self._activate_tab(target)
        else:
            self._sync_active_tab()
            old_tab = self._active_tab
            if old_tab.kernel is not None:
                await old_tab.kernel.shutdown()
            self.tabs[self.active_tab_index] = tab
            await self._activate_tab(self.active_tab_index, force=True)
        self.notify(f"Opened {path.relative_to(self.workspace_root)}")

    async def _mount_text_editor(
        self, notebook_view: VerticalScroll, buffer: TextBuffer, read_only: bool = False
    ) -> TextArea:
        editor = TextFileEditor.code_editor(
            buffer.text,
            language=buffer.language,
            id="text-file-editor",
        )
        editor.editable = not read_only
        self._configure_editor_theme(editor)
        editor.add_class("text-file-editor")
        await notebook_view.mount(editor)
        return editor

    async def _open_help(self) -> None:
        existing = next(
            (
                index
                for index, tab in enumerate(self.tabs)
                if tab.read_only and tab.path.name == "HELP.md"
            ),
            None,
        )
        if existing is not None:
            await self._activate_tab(existing)
            return
        help_text = files("notebookvim").joinpath("HELP.md").read_text(encoding="utf-8")
        await self._append_tab(
            DocumentTab(
                path=Path("HELP.md"),
                text_buffer=TextBuffer(path=Path("HELP.md"), text=help_text),
                read_only=True,
            )
        )

    def _duckdb(self) -> DuckDBWorkspace:
        if self.data_workspace is None:
            self.data_workspace = DuckDBWorkspace()
        return self.data_workspace

    async def _append_tab(self, tab: DocumentTab) -> None:
        self.tabs.append(tab)
        target = len(self.tabs) - 1
        await self.query_one("#tabs", TabBar).add_tab(
            Tab(tab.display_name, id=f"document-tab-{target}")
        )
        await self._activate_tab(target)

    async def _open_sql_workspace(self, always_new: bool = False) -> None:
        if not always_new:
            existing = next(
                (index for index, tab in enumerate(self.tabs) if tab.sql_document is not None),
                None,
            )
            if existing is not None:
                await self._activate_tab(existing)
                return
        try:
            self._duckdb()
        except Exception as exc:
            self.notify(str(exc), title="SQL workspace", severity="error")
            return
        self._sql_document_count += 1
        name = "SQL" if self._sql_document_count == 1 else f"SQL {self._sql_document_count}"
        document = SqlDocument(name=name)
        await self._append_tab(
            DocumentTab(
                path=self.workspace_root / f".notebookvim-sql-{self._sql_document_count}.sql",
                sql_document=document,
            )
        )

    async def _run_sql(self, explain: bool = False) -> None:
        if self.sql_document is None or self.sql_editor is None:
            self.notify("Open a SQL workspace with :sql first", severity="warning")
            return
        self.sql_document.query = self.sql_editor.text
        operation = "Explaining" if explain else "Running"
        self.notify(f"{operation} query…", title="DuckDB")
        try:
            engine = self._duckdb()
            if explain:
                result = await asyncio.to_thread(engine.explain, self.sql_document.query)
            else:
                result = await asyncio.to_thread(engine.execute, self.sql_document.query)
        except Exception as exc:
            self.notify(str(exc), title="SQL failed", severity="error", timeout=15)
            return
        self.sql_document.result = result
        result_view = self.query_one("#sql-result", QueryResultView)
        result_view.result = result
        result_view.refresh(layout=True)
        self.notify(
            f"Returned {len(result.rows)} row(s) in {result.elapsed_seconds:.3f}s",
            title="DuckDB",
        )

    def _show_sql_history(self) -> None:
        try:
            history = self._duckdb().history
        except Exception as exc:
            self.notify(str(exc), title="SQL workspace", severity="error")
            return
        if not history:
            self.notify("No queries have run in this session", title="SQL history")
            return
        lines = [f"{index}. {query}" for index, query in enumerate(history[-10:], 1)]
        self.notify("\n\n".join(lines), title="Recent SQL", timeout=20)

    def _save_sql_query(self) -> None:
        if self.sql_document is None or self.sql_editor is None:
            self.notify("Open a SQL workspace with :sql first", severity="warning")
            return
        self.sql_document.query = self.sql_editor.text
        queries = self.workspace_root / "queries"
        queries.mkdir(exist_ok=True)
        counter = 1
        while (queries / f"query-{counter}.sql").exists():
            counter += 1
        path = queries / f"query-{counter}.sql"
        path.write_text(self.sql_document.query.rstrip() + "\n", encoding="utf-8")
        self._refresh_project_files()
        self.notify(f"Saved {path.relative_to(self.workspace_root)}", title="SQL workspace")

    async def _profile_current(self) -> None:
        try:
            engine = self._duckdb()
            if self.parquet_preview is not None:
                profile = await asyncio.to_thread(
                    engine.profile_parquet, self.parquet_preview.path
                )
            elif self.sql_document is not None:
                if self.sql_editor is not None:
                    self.sql_document.query = self.sql_editor.text
                profile = await asyncio.to_thread(
                    engine.profile_query,
                    self.sql_document.query,
                    self.sql_document.name,
                )
            else:
                self.notify(
                    "Profiling currently supports an active Parquet preview or SQL query",
                    severity="warning",
                )
                return
        except Exception as exc:
            self.notify(str(exc), title="Profile failed", severity="error", timeout=15)
            return
        await self._append_tab(
            DocumentTab(
                path=self.workspace_root / f".notebookvim-profile-{len(self.tabs)}.json",
                dataset_profile=profile,
            )
        )

    def _save_profile(self) -> None:
        if self.dataset_profile is None:
            self.notify("Open a profile first with :profile", severity="warning")
            return
        source_name = Path(self.dataset_profile.source).stem
        if not source_name or source_name == ".":
            source_name = "dataset"
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in source_name
        ).strip("-") or "dataset"
        path = self.workspace_root / f"{safe_name}.profile.json"
        try:
            self.dataset_profile.save(path)
        except Exception as exc:
            self.notify(str(exc), title="Profile save failed", severity="error")
            return
        self._refresh_project_files()
        self.notify(f"Saved {path.name}", title="Dataset profile")

    def _inspection_source_path(self) -> Path:
        if not self.tabs:
            raise InspectionError("Open a Parquet file before using :inspect")
        if self.parquet_preview is not None:
            return self.parquet_preview.path
        path = self._active_tab.path
        if path.suffix.lower() in {".parquet", ".parq", ".pq"}:
            return path
        raise InspectionError("Open a Parquet file before using :inspect")

    def _contextual_command_suggestions(self) -> tuple[str, ...]:
        try:
            path = self._inspection_source_path()
        except InspectionError:
            return COMMAND_SUGGESTIONS
        parquet = tuple(item for item in COMMANDS if item.startswith("inspect parquet "))
        delta = (
            tuple(item for item in COMMANDS if item.startswith("inspect delta "))
            if find_delta_root(path) is not None
            else ()
        )
        remaining = tuple(item for item in COMMAND_SUGGESTIONS if item not in parquet + delta)
        return parquet + delta + remaining

    def _inspection_completion_prefix(self) -> Optional[str]:
        try:
            self._inspection_source_path()
        except InspectionError:
            return None
        return "inspect parquet"

    async def _show_inspection_report(
        self, report: InspectionReport, placement: Optional[str] = None
    ) -> None:
        if placement in {"side", "below"}:
            self._open_inspection_pane(report, placement)
            return
        self.action_inspection_close(focus_document=False)
        await self.push_screen(InspectionModal(report))

    async def _dispatch_inspect_command(self, command: str) -> None:
        try:
            arguments = shlex.split(command)
            if arguments == ["inspect", "close"]:
                self.action_inspection_close()
                return
            if len(arguments) < 3 or arguments[0] != "inspect":
                raise InspectionError("Use :inspect parquet … or :inspect delta …")
            placement = arguments.pop() if arguments[-1] in {"side", "below"} else None
            source = self._inspection_source_path()
            inspector = LakehouseInspector(source)
            kind = arguments[1]
            operation = " ".join(arguments[2:])
            if kind == "parquet" and operation == "profile":
                await self._profile_current()
                return
            if kind == "delta" and operation == "profile":
                files = await asyncio.to_thread(inspector.delta_files)
                profile = await asyncio.to_thread(
                    self._duckdb().profile_files,
                    files,
                    f"Delta table {inspector.delta_root}",
                )
                await self._append_tab(
                    DocumentTab(
                        path=self.workspace_root / f".notebookvim-profile-{len(self.tabs)}.json",
                        dataset_profile=profile,
                    )
                )
                return
            version = None
            if kind == "delta" and arguments[2:4] == ["time", "travel"]:
                if len(arguments) != 5 or not arguments[4].isdigit():
                    raise InspectionError("Usage: :inspect delta time travel VERSION")
                operation = "time travel"
                version = int(arguments[4])
            if kind == "parquet":
                report = await asyncio.to_thread(inspector.parquet, operation)
            elif kind == "delta":
                report = await asyncio.to_thread(inspector.delta, operation, version)
            else:
                raise InspectionError("Inspection type must be parquet or delta")
            await self._show_inspection_report(report, placement)
        except Exception as exc:
            self.notify(str(exc), title="Inspection failed", severity="error", timeout=15)

    def _remote_service(self) -> DatabricksRemote:
        if self.databricks_connection is None:
            raise RemoteError("Connect first with :databricks connect [profile]")
        if self.remote is None:
            self.remote = DatabricksRemote(
                self.workspace_root, databricks_client(self.databricks_connection)
            )
        return self.remote

    def _remote_local_path(self) -> Path:
        tab = self._active_tab
        if tab.notebook is None and tab.text_buffer is None:
            raise RemoteError("Remote sync requires an active notebook or source file")
        if tab.path.suffix.lower() not in {".ipynb", ".py", ".sql", ".scala", ".r"}:
            raise RemoteError("Remote sync supports .ipynb, .py, .sql, .scala, and .r files")
        return tab.path.resolve()

    def _remote_local_bytes(self) -> bytes:
        tab = self._active_tab
        if tab.notebook is not None:
            import nbformat

            return nbformat.writes(to_node(tab.notebook), version=nbformat.NO_CONVERT).encode()
        assert tab.text_buffer is not None
        return tab.text_buffer.text.encode("utf-8")

    async def _show_remote_report(self, report: RemoteReport) -> None:
        await self._append_tab(
            DocumentTab(
                path=self.workspace_root / f".notebookvim-remote-{uuid.uuid4().hex}.txt",
                remote_report=report,
            )
        )

    async def _reload_active_remote_file(self, path: Path) -> None:
        tab = self._active_tab
        if tab.path.resolve() != path.resolve():
            return
        if tab.notebook is not None:
            if tab.kernel is not None:
                await tab.kernel.shutdown()
            notebook = load_notebook(path)
            tab.notebook = notebook
            tab.kernel = Kernel(notebook.kernel_name)
        elif tab.text_buffer is not None:
            tab.text_buffer = load_text_buffer(path)
        await self._activate_tab(self.active_tab_index, force=True)

    async def _dispatch_remote_command(self, command: str) -> None:
        try:
            arguments = shlex.split(command)
        except ValueError as exc:
            self.notify(str(exc), title="Remote command", severity="error")
            return
        try:
            service = self._remote_service()
            if arguments[:2] == ["remote", "set"]:
                if len(arguments) < 3:
                    raise RemoteError(
                        "Usage: :databricks sync set /Workspace/path [--strip-outputs]"
                    )
                path = self._remote_local_path()
                strip_outputs = "--strip-outputs" in arguments[3:]
                mapping = await asyncio.to_thread(
                    service.configure, path, arguments[2], strip_outputs
                )
                self.notify(
                    f"{path.name} ↔ {mapping.remote_path}", title="Remote mapping"
                )
            elif arguments and arguments[0] in {"status", "pull", "push"}:
                path = self._remote_local_path()
                if len(arguments) > 1:
                    await asyncio.to_thread(service.configure, path, arguments[1], False)
                if arguments[0] == "status":
                    status = await asyncio.to_thread(
                        service.status, path, self._remote_local_bytes()
                    )
                    await self._show_sync_status(status)
                elif arguments[0] == "pull":
                    status = await asyncio.to_thread(
                        service.pull, path, dirty=self._active_tab.dirty
                    )
                    await self._reload_active_remote_file(path)
                    self.notify(f"Pulled {status.remote_path}", title="Remote sync")
                else:
                    if self._active_tab.dirty:
                        raise RemoteError("Save local edits before pushing")
                    status = await asyncio.to_thread(service.push, path)
                    self.notify(f"Pushed {status.remote_path}", title="Remote sync")
            elif arguments == ["diff", "remote"]:
                path = self._remote_local_path()
                lines = await asyncio.to_thread(
                    service.diff, path, self._remote_local_bytes()
                )
                mapping = service.mapping(path)
                await self._show_remote_report(
                    RemoteReport(
                        title=f"Remote diff · {path.name}",
                        columns=["local", "remote"],
                        rows=[[path.name, mapping.remote_path if mapping else "—"]],
                        details=lines,
                    )
                )
            elif arguments and arguments[0] == "resolve":
                if len(arguments) != 2 or arguments[1] not in {"local", "remote"}:
                    raise RemoteError(
                        "Use :databricks sync resolve local to force push or "
                        ":databricks sync resolve remote to force pull"
                    )
                path = self._remote_local_path()
                if self._active_tab.dirty:
                    raise RemoteError("Save or undo local edits before resolving")
                if arguments[1] == "local":
                    await asyncio.to_thread(service.push, path, None, force=True)
                    self.notify("Conflict resolved using the local version", title="Remote sync")
                else:
                    await asyncio.to_thread(service.pull, path, dirty=False, force=True)
                    await self._reload_active_remote_file(path)
                    self.notify("Conflict resolved using the remote version", title="Remote sync")
            elif arguments in (["jobs"], ["jobs", "running"]):
                if len(arguments) == 1:
                    jobs = await asyncio.to_thread(service.list_jobs)
                    report = RemoteReport(
                        "Databricks jobs", ["job ID", "name"],
                        [[str(item.job_id), item.name] for item in jobs],
                    )
                else:
                    runs = await asyncio.to_thread(service.list_runs, True)
                    report = self._runs_report("Running Databricks jobs", runs)
                await self._show_remote_report(report)
            elif arguments[:2] == ["run", "remote"]:
                if len(arguments) < 3 or not arguments[2].isdigit():
                    raise RemoteError("Usage: :databricks run JOB_ID [--param name=value]")
                parameters: dict[str, str] = {}
                index = 3
                while index < len(arguments):
                    if arguments[index] != "--param" or index + 1 >= len(arguments):
                        raise RemoteError("Parameters use --param name=value")
                    name, separator, value = arguments[index + 1].partition("=")
                    if not separator or not name:
                        raise RemoteError("Parameters use --param name=value")
                    parameters[name] = value
                    index += 2
                run_id = await asyncio.to_thread(service.run_job, int(arguments[2]), parameters)
                self.last_remote_run_id = run_id
                self.notify(f"Started run {run_id}", title="Databricks job")
            elif arguments and arguments[0] in {"logs", "cancel", "rerun"}:
                follow = arguments[:2] == ["logs", "follow"]
                id_index = 2 if follow else 1
                run_id = (
                    int(arguments[id_index])
                    if len(arguments) > id_index and arguments[id_index].isdigit()
                    else self.last_remote_run_id
                )
                if run_id is None:
                    raise RemoteError("Provide a RUN_ID or start a run first")
                if arguments[0] == "logs":
                    report = await asyncio.to_thread(service.logs, run_id)
                    await self._show_remote_report(report)
                    if follow:
                        self.run_worker(self._follow_remote_logs(run_id), group="remote-logs", exclusive=True)
                elif arguments[0] == "cancel":
                    await asyncio.to_thread(service.cancel, run_id)
                    self.notify(f"Cancellation requested for run {run_id}", title="Databricks job")
                else:
                    new_run_id = await asyncio.to_thread(service.rerun, run_id)
                    self.last_remote_run_id = new_run_id
                    self.notify(f"Started rerun {new_run_id}", title="Databricks job")
            else:
                raise RemoteError("Unknown remote command")
        except Exception as exc:
            self.notify(str(exc), title="Remote operation failed", severity="error", timeout=18)

    async def _show_sync_status(self, status: SyncStatus) -> None:
        modified = str(status.remote_modified_at or "—")
        await self._show_remote_report(
            RemoteReport(
                title=f"Remote status · {status.label}",
                columns=["local", "remote", "local changed", "remote changed", "modified"],
                rows=[[
                    status.local_path.name, status.remote_path,
                    "yes" if status.local_changed else "no",
                    "yes" if status.remote_changed else "no",
                    modified if status.remote_exists else "not uploaded",
                ]],
            )
        )

    def _runs_report(self, title: str, runs) -> RemoteReport:
        return RemoteReport(
            title,
            ["run", "job", "name", "state", "result", "started", "duration", "parameters", "compute", "link"],
            [[
                str(run.run_id), str(run.job_id or "—"), run.name, run.state, run.result or "—",
                run.start_time, run.duration, json.dumps(run.parameters), run.compute or "—", run.url,
            ] for run in runs],
        )

    async def _follow_remote_logs(self, run_id: int) -> None:
        terminal_states = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR", "SUCCESS", "FAILED", "CANCELED"}
        while True:
            try:
                run = await asyncio.to_thread(self._remote_service().get_run, run_id)
                report = await asyncio.to_thread(self._remote_service().logs, run_id)
                if self.remote_report is not None and self.remote_report.title.startswith(f"Run {run_id}"):
                    self.remote_report = report
                    self._active_tab.remote_report = report
                    view = self.query_one("#remote-report", RemoteReportView)
                    view.report = report
                    view.refresh(layout=True)
                if run.state in terminal_states or run.result:
                    self.notify(f"Run {run_id}: {run.result or run.state}", title="Databricks job")
                    return
                await asyncio.sleep(2)
            except Exception as exc:
                self.notify(str(exc), title="Log follow stopped", severity="error")
                return

    def action_next_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(self.selected + 1)

    def action_previous_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(self.selected - 1)

    async def action_edit_cell(self, insert: bool = True) -> None:
        if self.text_editor is not None:
            self.text_editor.focus()
            if isinstance(self.text_editor, TextFileEditor):
                self.text_editor.enter_insert_mode("i")
            return
        if not self._notebook_active or self.editor is not None:
            return
        cell = self.notebook.cells[self.selected]
        language = "python" if cell.cell_type == CellType.CODE else None
        editor = CellEditor.code_editor(cell.source, language=language, id="cell-editor")
        self._configure_editor_theme(editor)
        editor.add_class("cell-editor")
        editor.border_title = f"Cell {self.selected + 1} · Edit"
        self.editor = editor
        view = self._view(self.selected)
        view.display = False
        await view.parent.mount(editor, before=view)
        editor.focus()
        if insert:
            editor.enter_insert_mode("i")
        else:
            editor.enter_normal_mode()

    async def action_open_cell(self, above: bool = False) -> None:
        if self.text_editor is not None:
            if isinstance(self.text_editor, TextFileEditor):
                self.text_editor.enter_insert_mode("O" if above else "o")
            return
        await self.action_insert_cell(above)
        await self.action_edit_cell()

    def _record_notebook_undo(self) -> None:
        if not self._notebook_active:
            return
        tab = self._active_tab
        tab.notebook_undo.append((copy.deepcopy(self.notebook.cells), self.selected))
        if len(tab.notebook_undo) > 100:
            tab.notebook_undo.pop(0)
        tab.notebook_redo.clear()

    async def action_vim_undo(self) -> None:
        if not self._notebook_active or self.editor is not None:
            return
        tab = self._active_tab
        if not tab.notebook_undo:
            return
        tab.notebook_redo.append((copy.deepcopy(self.notebook.cells), self.selected))
        cells, selected = tab.notebook_undo.pop()
        self.notebook.cells = copy.deepcopy(cells)
        self.notebook.dirty = True
        await self._rebuild_cells(selected)

    async def action_vim_redo(self) -> None:
        if not self._notebook_active or self.editor is not None:
            return
        tab = self._active_tab
        if not tab.notebook_redo:
            return
        tab.notebook_undo.append((copy.deepcopy(self.notebook.cells), self.selected))
        cells, selected = tab.notebook_redo.pop()
        self.notebook.cells = copy.deepcopy(cells)
        self.notebook.dirty = True
        await self._rebuild_cells(selected)

    def action_yank_cell(self) -> None:
        if not self._notebook_active or self.editor is not None:
            return
        self._vim_cell_register = copy.deepcopy(self.notebook.cells[self.selected])
        self.notify(f"Yanked cell {self.selected + 1}")

    async def action_paste_cell(self, above: bool = False) -> None:
        if not self._notebook_active or self.editor is not None or self._vim_cell_register is None:
            return
        self._record_notebook_undo()
        cell = copy.deepcopy(self._vim_cell_register)
        cell.cell_id = uuid.uuid4().hex[:8]
        index = self.selected if above else self.selected + 1
        self.notebook.cells.insert(index, cell)
        self.notebook.dirty = True
        await self._rebuild_cells(index)

    async def action_vim_delete_cell(self) -> None:
        if not self._notebook_active or self.editor is not None:
            return
        self._vim_cell_register = copy.deepcopy(self.notebook.cells[self.selected])
        await self.action_delete_cell()

    def action_first_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(0)

    def action_last_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(len(self.notebook.cells) - 1)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Request suggestions without blocking interactive editing."""
        if event.text_area is self.text_editor and self.text_buffer is not None:
            if self.text_buffer.text != event.text_area.text:
                self.text_buffer.text = event.text_area.text
                self.text_buffer.dirty = True
                self._quit_armed = False
                self._update_status()
                self._refresh_tabs()
            if event.text_area.language == "python":
                self._completion_revision += 1
                revision = self._completion_revision
                line, column = event.text_area.cursor_location
                self._request_completions(
                    revision, event.text_area.text, self.text_buffer.path, line, column
                )
            return
        if event.text_area is self.sql_editor and self.sql_document is not None:
            self.sql_document.query = event.text_area.text
            return
        if event.text_area is not self.editor or self.editor.language != "python":
            return
        self._completion_revision += 1
        revision = self._completion_revision
        line, column = self.editor.cursor_location
        self._request_completions(
            revision, self.editor.text, self.notebook.path, line, column
        )

    @work(exclusive=True)
    async def _request_completions(
        self, revision: int, source: str, path: Path, line: int, column: int
    ) -> None:
        # Let a short burst of typing settle before asking Jedi to parse it.
        await asyncio.sleep(0.12)
        suggestions = await asyncio.to_thread(
            python_completions, source, path, line, column
        )
        await self._show_completions(revision, suggestions)

    async def _show_completions(self, revision: int, suggestions: list[str]) -> None:
        target = self.editor or self.text_editor
        if revision != self._completion_revision or target is None:
            return
        self._completions = suggestions
        if self.completion_menu is not None:
            await self.completion_menu.remove()
            self.completion_menu = None
        if not suggestions:
            return
        menu = Static("\\n".join(f"› {item}" for item in suggestions), id="completion-menu")
        self.completion_menu = menu
        if self.editor is not None:
            await self.editor.parent.mount(menu, before=self._view(self.selected))
        else:
            await target.parent.mount(menu)

    async def _clear_completions(self) -> None:
        self._completions = []
        if self.completion_menu is not None:
            await self.completion_menu.remove()
            self.completion_menu = None

    def accept_completion(self) -> bool:
        target = self.editor or self.text_editor
        if target is None or not self._completions:
            return False
        line, column = target.cursor_location
        prefix_start = column
        lines = target.text.splitlines()
        current_line = lines[line] if line < len(lines) else ""
        while prefix_start and (current_line[prefix_start - 1].isalnum() or current_line[prefix_start - 1] == "_"):
            prefix_start -= 1
        target.replace(self._completions[0], (line, prefix_start), (line, column))
        self._completion_revision += 1
        self.run_worker(self._clear_completions())
        return True

    async def on_key(self, event: events.Key) -> None:
        if self.editor is not None or self.sql_editor is not None:
            return
        if self.text_editor is not None and self.text_editor.has_focus:
            return
        if not self._notebook_active:
            return
        if not isinstance(self.focused, CellView):
            return

        key = event.key
        if key == "q" and self._escape_close_armed:
            event.stop()
            event.prevent_default()
            self._escape_close_armed = False
            self.action_close_tab()
            return
        if key == "escape":
            self.arm_escape_close()
        else:
            self._escape_close_armed = False
        if key == "ctrl+r":
            event.stop()
            event.prevent_default()
            await self.action_vim_redo()
            return
        if key in {
            "down", "up", "colon", "left_square_bracket", "right_square_bracket",
            "shift+tab",
        } or key.startswith("ctrl+"):
            return
        event.stop()
        event.prevent_default()
        if key == "j":
            self.action_next_cell()
        elif key == "k":
            self.action_previous_cell()
        elif key == "i":
            await self.action_edit_cell()
        elif key == "enter":
            await self.action_edit_cell(insert=False)
        elif key in {"o", "shift+o"}:
            await self.action_open_cell(above=key == "shift+o")
        elif key == "r":
            self.action_run_cell(False)
        elif key == "shift+r":
            self.action_run_cell(True)
        elif key == "shift+j":
            await self.action_move_cell(1)
        elif key == "shift+k":
            await self.action_move_cell(-1)
        elif key == "m":
            self.action_toggle_cell_type()
        elif key == "u":
            await self.action_vim_undo()
        elif key in {"p", "shift+p"}:
            await self.action_paste_cell(above=key == "shift+p")
        elif key == "shift+g":
            self.action_last_cell()
            self._vim_pending_key = ""
        elif key == "g":
            if self._vim_pending_key == "g":
                self.action_first_cell()
                self._vim_pending_key = ""
            else:
                self._vim_pending_key = "g"
        elif key == "d":
            if self._vim_pending_key == "d":
                await self.action_vim_delete_cell()
                self._vim_pending_key = ""
            else:
                self._vim_pending_key = "d"
        elif key == "y":
            if self._vim_pending_key == "y":
                self.action_yank_cell()
                self._vim_pending_key = ""
            else:
                self._vim_pending_key = "y"
        elif key == "escape":
            self._vim_pending_key = ""
        else:
            self._vim_pending_key = ""

    async def _finish_edit(self) -> None:
        assert self.editor is not None
        editor = self.editor
        await self._clear_completions()
        cell = self.notebook.cells[self.selected]
        if cell.source != editor.text:
            self._record_notebook_undo()
            cell.source = editor.text
            self.notebook.dirty = True
            self._refresh_tabs()
        await editor.remove()
        self.editor = None
        view = self._view(self.selected)
        view.display = True
        view.refresh(layout=True)
        view.focus(scroll_visible=True)
        self._update_status()

    async def action_insert_cell(self, above: bool = False) -> None:
        if not self._notebook_active:
            return
        if self.editor is not None:
            await self._finish_edit()
        if self._running_cells:
            self.notify("Wait for execution to finish before changing cell structure", severity="warning")
            return
        self._record_notebook_undo()
        insert_at = self.selected if above else self.selected + 1
        self.notebook.cells.insert(
            insert_at,
            Cell(CellType.CODE, "", cell_id=uuid.uuid4().hex[:8]),
        )
        self.notebook.dirty = True
        await self._rebuild_cells(insert_at)

    async def action_delete_cell(self) -> None:
        if not self._notebook_active:
            return
        if self.editor is not None:
            await self._finish_edit()
        if self._running_cells:
            self.notify("Wait for execution to finish before deleting cells", severity="warning")
            return
        if len(self.notebook.cells) == 1:
            self.notify("A notebook must contain at least one cell", severity="warning")
            return
        self._record_notebook_undo()
        removed = self.notebook.cells.pop(self.selected)
        if removed.cell_id:
            self._collapsed_outputs.discard(removed.cell_id)
        self.notebook.dirty = True
        await self._rebuild_cells(min(self.selected, len(self.notebook.cells) - 1))
        self.notify("Cell deleted")

    async def action_duplicate_cell(self) -> None:
        if not self._notebook_active:
            return
        if self.editor is not None:
            await self._finish_edit()
        if self._running_cells:
            self.notify("Wait for execution to finish before duplicating cells", severity="warning")
            return
        self._record_notebook_undo()
        duplicate = copy.deepcopy(self.notebook.cells[self.selected])
        duplicate.cell_id = uuid.uuid4().hex[:8]
        insert_at = self.selected + 1
        self.notebook.cells.insert(insert_at, duplicate)
        self.notebook.dirty = True
        await self._rebuild_cells(insert_at)
        self.notify("Cell duplicated")

    async def action_move_cell(self, direction: int) -> None:
        if not self._notebook_active:
            return
        if self.editor is not None:
            await self._finish_edit()
        if self._running_cells:
            self.notify("Wait for execution to finish before moving cells", severity="warning")
            return
        destination = self.selected + direction
        if not 0 <= destination < len(self.notebook.cells):
            return
        self._record_notebook_undo()
        self.notebook.cells[self.selected], self.notebook.cells[destination] = (
            self.notebook.cells[destination], self.notebook.cells[self.selected]
        )
        self.notebook.dirty = True
        await self._rebuild_cells(destination)

    def action_toggle_cell_type(self) -> None:
        if not self._notebook_active or self.editor is not None or self.selected in self._running_cells:
            return
        cell = self.notebook.cells[self.selected]
        self._record_notebook_undo()
        if cell.cell_type == CellType.CODE:
            cell.cell_type = CellType.MARKDOWN
            cell.execution_count = None
            cell.execution_duration = None
            cell.outputs.clear()
            self._collapsed_outputs.discard(self._cell_key(self.selected))
            label = "Markdown"
        else:
            cell.cell_type = CellType.CODE
            label = "Code"
        self.notebook.dirty = True
        self._view(self.selected).refresh(layout=True)
        self._update_status()
        self.notify(f"Cell changed to {label}")

    def action_set_cell_type(self, cell_type: str) -> None:
        if not self._notebook_active or self.editor is not None or self.selected in self._running_cells:
            return
        try:
            target = CellType(cell_type)
        except ValueError:
            self.notify(f"Unknown cell type: {cell_type}", severity="warning")
            return
        cell = self.notebook.cells[self.selected]
        if cell.cell_type == target:
            return
        cell.cell_type = target
        if target != CellType.CODE:
            cell.execution_count = None
            cell.execution_duration = None
            cell.outputs.clear()
            self._collapsed_outputs.discard(self._cell_key(self.selected))
        self.notebook.dirty = True
        self._view(self.selected).refresh(layout=True)
        self._update_status()
        self.notify(f"Cell changed to {target.value.title()}")

    def action_cell_output(self, operation: str) -> None:
        if not self._notebook_active:
            return
        cell = self.notebook.cells[self.selected]
        key = self._cell_key(self.selected)
        if operation == "clear":
            if cell.outputs:
                cell.outputs.clear()
                self._collapsed_outputs.discard(key)
                self.notebook.dirty = True
                self.notify("Cell output cleared")
        elif operation == "collapse":
            self._collapsed_outputs.add(key)
        elif operation == "expand":
            self._collapsed_outputs.discard(key)
        else:
            self.notify(f"Unknown output command: {operation}", severity="warning")
            return
        self._view(self.selected).output_collapsed = key in self._collapsed_outputs
        self._view(self.selected).refresh(layout=True)
        self._update_status()

    def action_clear_all_outputs(self) -> None:
        if not self._notebook_active:
            return
        changed = False
        for cell in self.notebook.cells:
            if cell.outputs:
                cell.outputs.clear()
                changed = True
        self._collapsed_outputs.clear()
        if changed:
            self.notebook.dirty = True
            for view in self.query(CellView):
                view.output_collapsed = False
                view.refresh(layout=True)
            self._update_status()
        self.notify("Notebook outputs cleared")

    def action_command(self) -> None:
        text_in_insert = (
            isinstance(self.text_editor, TextFileEditor)
            and self.text_editor.has_focus
            and self.text_editor.vim_mode == "insert"
        )
        if text_in_insert:
            return
        if self.editor is not None:
            if self.editor.vim_mode == "insert":
                return
            self.run_worker(self._finish_edit_then_command())
        if self.editor is not None or text_in_insert:
            return
        self._show_command()

    async def _finish_edit_then_command(self) -> None:
        await self._finish_edit()
        self._show_command()

    def _show_command(self) -> None:
        command = self.query_one("#command", CommandInput)
        suggestions = self._contextual_command_suggestions()
        inspection_prefix = self._inspection_completion_prefix()
        command.suggester = ContextualCommandSuggester(suggestions, inspection_prefix)
        command.value = ""
        command.display = True
        command.focus()
        self._update_command_options("")
        self.call_after_refresh(
            lambda: setattr(command, "_suggestion", inspection_prefix or suggestions[0])
            if command.display and not command.value
            else None
        )
        self.query_one("#status", Static).update(
            " COMMAND │ Tab: complete │ :help lists commands │ Escape: cancel"
        )

    def _command_option_candidates(self, value: str) -> list[str]:
        typed = value.strip().lstrip(":")
        folded = typed.casefold()
        for operation in ("folder open", "project open"):
            if folded == operation or folded.startswith(f"{operation} "):
                # Folder paths may start from very large directories (including
                # the user's home), so never crawl the filesystem for options.
                return []
        for operation in ("file open", "tab open"):
            if folded == operation or folded.startswith(f"{operation} "):
                partial = typed[len(operation):].strip().casefold()
                candidates = [
                    f"{operation} {path.relative_to(self.workspace_root)}"
                    for path in self.project_paths
                    if not partial
                    or str(path.relative_to(self.workspace_root)).casefold().startswith(partial)
                ]
                return candidates[:80]
        suggestions = self._contextual_command_suggestions()
        return [
            suggestion for suggestion in suggestions
            if suggestion.casefold().startswith(folded)
            and suggestion.casefold() != folded
        ][:80]

    def _update_command_options(self, value: str) -> None:
        options = self._command_option_candidates(value)
        self._command_option_values = options
        dropdown = self.query_one("#command-suggestions", OptionList)
        dropdown.set_options(options)
        dropdown.display = bool(options)
        command = self.query_one("#command", CommandInput)
        inspection_prefix = self._inspection_completion_prefix()
        if value.strip().lstrip(":").casefold() == "inspect" and inspection_prefix:
            command._suggestion = inspection_prefix
        else:
            command._suggestion = options[0] if options else ""

    def _move_command_option(self, offset: int) -> None:
        if not self._command_option_values:
            return
        dropdown = self.query_one("#command-suggestions", OptionList)
        current = dropdown.highlighted if dropdown.highlighted is not None else 0
        dropdown.highlighted = (current + offset) % len(self._command_option_values)

    def _accept_command_option(self, index: Optional[int] = None) -> None:
        if not self._command_option_values:
            return
        dropdown = self.query_one("#command-suggestions", OptionList)
        selected = index if index is not None else dropdown.highlighted
        command = self.query_one("#command", CommandInput)
        if selected is None and command._suggestion:
            value = command._suggestion
        else:
            value = self._command_option_values[selected if selected is not None else 0]
        command.value = value
        command.cursor_position = len(value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command":
            self._update_command_options(event.value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "command-suggestions":
            self._accept_command_option(event.option_index)

    def close_command(self) -> None:
        command = self.query_one("#command", CommandInput)
        command.value = ""
        command.display = False
        self.query_one("#command-suggestions", OptionList).display = False
        self._command_option_values = []
        self._focus_document()
        self._update_status()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-picker":
            value = event.value.strip()
            picker = self.query_one("#file-picker", ProjectFileInput)
            if value and not (self.workspace_root / value).exists() and picker._suggestion:
                value = picker._suggestion
            self.close_file_picker()
            if not value:
                return
            await self._open_project_file(self.workspace_root / value)
            return
        if event.input.id != "command":
            return
        command = normalize_command(event.value)
        self.close_command()
        await self._dispatch_command(command)

    async def _dispatch_command(self, command: str) -> None:
        if command == "cell run":
            self.action_run_cell(False)
        elif command.startswith("cell run "):
            if not self._notebook_active:
                self.notify("Cell commands require an active notebook", severity="warning")
                return
            value = command.removeprefix("cell run ")
            if not value.isdigit():
                self.notify("Cell number must be a positive integer", severity="warning")
                return
            index = int(value) - 1
            if not 0 <= index < len(self.notebook.cells):
                self.notify(
                    f"Cell {value} does not exist; choose 1–{len(self.notebook.cells)}",
                    severity="warning",
                )
                return
            if self.notebook.cells[index].cell_type != CellType.CODE:
                self.notify(f"Cell {value} is not a code cell", severity="warning")
                return
            self._select(index)
            self.run_cell_sequence([index])
        elif command == "cell run advance":
            self.action_run_cell(True)
        elif command.startswith("cell output "):
            self.action_cell_output(command.removeprefix("cell output "))
        elif command == "cell add above":
            await self.action_insert_cell(True)
        elif command == "cell add below":
            await self.action_insert_cell(False)
        elif command == "cell delete":
            await self.action_delete_cell()
        elif command == "cell duplicate":
            await self.action_duplicate_cell()
        elif command == "cell move up":
            await self.action_move_cell(-1)
        elif command == "cell move down":
            await self.action_move_cell(1)
        elif command.startswith("cell type "):
            self.action_set_cell_type(command.removeprefix("cell type "))
        elif command == "notebook save":
            self.action_save()
        elif command == "notebook run all":
            self.run_cell_sequence(list(range(len(self.notebook.cells))))
        elif command == "notebook run above":
            self.run_cell_sequence(list(range(self.selected)))
        elif command == "notebook run below":
            self.run_cell_sequence(list(range(self.selected + 1, len(self.notebook.cells))))
        elif command == "notebook output clear":
            self.action_clear_all_outputs()
        elif command == "kernel info":
            state = "ALIVE" if self.kernel.alive else "NOT STARTED"
            self.notify(f"{self.notebook.kernel_name} · {state}", title="Kernel")
        elif command == "kernel interrupt":
            self.action_interrupt()
        elif command == "kernel restart":
            self.action_restart_kernel()
        elif command == "kernel shutdown":
            self.action_shutdown_kernel()
        elif command.startswith("folder open "):
            await self._open_project_from_command(command.removeprefix("folder open "))
        elif command.startswith("project open "):
            await self._open_project_from_command(command.removeprefix("project open "))
        elif command == "project scaffold init data-engineering":
            if not self.project_open:
                self.notify("Open a project before initializing a scaffold", severity="warning")
                return
            try:
                result = init_data_engineering_scaffold(self.workspace_root)
            except OSError as exc:
                self.notify(f"Could not initialize scaffold: {exc}", severity="error")
                return
            self._refresh_project_files()
            message = f"Created {len(result.created)} files"
            if result.skipped:
                message += f"; kept {len(result.skipped)} existing files"
            self.notify(message, title="Data engineering scaffold")
        elif command in {"folder close", "project close"}:
            await self._close_project()
        elif command in {"folder open", "project open"}:
            self.notify("Use :project open relative/path/to/folder", severity="warning")
        elif command.startswith("file open "):
            await self._open_file_from_command(command.removeprefix("file open "))
        elif command == "file open":
            self.notify("Use :file open relative/path/to/file", severity="warning")
        elif command.startswith(("file new ", "file create ")):
            operation = "file new " if command.startswith("file new ") else "file create "
            self._create_project_file(command.removeprefix(operation))
        elif command in {"file new", "file create"}:
            self.notify("Use :file new relative/path/to/file", severity="warning")
        elif command.startswith("tab open "):
            await self._open_file_from_command(
                command.removeprefix("tab open "), new_tab=True
            )
        elif command == "tab open":
            self.action_open_selected_in_tab()
        elif command == "tab next":
            self.action_next_tab()
        elif command == "tab previous":
            self.action_previous_tab()
        elif command == "tab close":
            await self._close_active_tab()
        elif command == "files focus":
            self.action_toggle_file_focus()
        elif command in {"terminal", "terminal open", "terminal open side"}:
            self.action_terminal_open("side")
        elif command == "terminal open below":
            self.action_terminal_open("below")
        elif command == "terminal close":
            self.action_terminal_close()
        elif command in {"ai", "ai open", "ai open side"}:
            self.action_ai_open("side")
        elif command == "ai open below":
            self.action_ai_open("below")
        elif command == "ai close":
            self.action_ai_close()
        elif command == "ai interrupt":
            if self.ai_pane.cancel():
                self.notify("Interrupt requested", title="AI")
            else:
                self.notify("No AI request is running", title="AI")
        elif command == "ai status":
            states = provider_statuses()
            self.notify(
                "\n".join(
                    f"{name}: {'available' if available else 'not installed'}"
                    for name, available in states.items()
                ),
                title="AI providers",
            )
        elif command.startswith("ai provider "):
            arguments = command.removeprefix("ai provider ").split(maxsplit=1)
            provider = arguments[0]
            model = arguments[1] if len(arguments) == 2 else None
            if model and provider != "ollama":
                self.notify(
                    "A model can currently be specified only for Ollama",
                    title="AI provider",
                    severity="warning",
                )
                return
            try:
                self.ai_pane.set_provider(provider, model=model)
                selected_model = getattr(self.ai_pane.provider, "model", None)
                save_ai_provider(provider, selected_model)
            except (ValueError, OSError) as exc:
                self.notify(str(exc), title="AI provider", severity="error")
            else:
                self.action_ai_open("side")
        elif command.startswith("ai ask "):
            prompt = command.removeprefix("ai ask ").strip()
            self.action_ai_open("side")
            if prompt:
                self.ai_pane.ask(prompt)
        elif command == "ai ask":
            self.action_ai_open("side")
        elif command == "sql":
            await self._open_sql_workspace()
        elif command == "sql new":
            await self._open_sql_workspace(always_new=True)
        elif command == "sql run":
            await self._run_sql()
        elif command == "sql explain":
            await self._run_sql(explain=True)
        elif command == "sql history":
            self._show_sql_history()
        elif command == "sql save":
            self._save_sql_query()
        elif command == "sql cancel":
            if self.data_workspace is not None:
                self.data_workspace.interrupt()
                self.notify("Cancellation requested", title="DuckDB")
        elif command in {"profile", "profile current"}:
            await self._profile_current()
        elif command == "profile save":
            self._save_profile()
        elif command.startswith("inspect "):
            await self._dispatch_inspect_command(command)
        elif command == "theme":
            self.notify(
                f"Current: {self._notebookvim_theme}\n"
                f"Recommended font: {THEME_FONTS[self._notebookvim_theme]}\n"
                f"Available: {', '.join(THEME_NAMES)}",
                title="Theme",
            )
        elif command.startswith("theme "):
            self.action_set_app_theme(command.removeprefix("theme "))
        elif command == "databricks connect" or command.startswith("databricks connect "):
            profile = command.removeprefix("databricks connect").strip() or None
            await self._connect_databricks(profile)
        elif command == "databricks status":
            self._show_databricks_status()
        elif command.startswith("databricks "):
            operation = command.removeprefix("databricks ")
            if operation.startswith("sync set"):
                remote_command = "remote set" + operation.removeprefix("sync set")
            elif operation == "sync status":
                remote_command = "status"
            elif operation == "sync diff":
                remote_command = "diff remote"
            elif operation.startswith("sync pull"):
                remote_command = "pull" + operation.removeprefix("sync pull")
            elif operation.startswith("sync push"):
                remote_command = "push" + operation.removeprefix("sync push")
            elif operation.startswith("sync resolve"):
                remote_command = "resolve" + operation.removeprefix("sync resolve")
            elif operation.startswith("run"):
                remote_command = "run remote" + operation.removeprefix("run")
            else:
                remote_command = operation
            await self._dispatch_remote_command(remote_command)
        elif command.startswith("git "):
            await self._dispatch_git_command(command)
        elif command == "help":
            await self._open_help()
        elif command == "exit":
            await self.action_request_quit()
        elif command == "write close":
            if self._save():
                await self._close_active_tab()
        elif command:
            self.notify(f"Unknown command: {command}", severity="warning")

    async def _dispatch_git_command(self, command: str) -> None:
        try:
            arguments = shlex.split(command)
        except ValueError as exc:
            self.notify(str(exc), title="Git command", severity="error")
            return
        try:
            if arguments[:3] == ["git", "profile", "add"]:
                if len(arguments) < 8:
                    raise GitError(
                        "Usage: :git profile add NAME PROVIDER ACCOUNT EMAIL AUTHOR_NAME"
                    )
                profile = GitProfile(
                    name=arguments[3],
                    provider=arguments[4].lower(),
                    account=arguments[5],
                    email=arguments[6],
                    author_name=" ".join(arguments[7:]),
                )
                await asyncio.to_thread(self.git.add_profile, profile)
                self.notify(f"Saved Git profile {profile.name}", title="Git")
            elif arguments[:3] == ["git", "profile", "list"]:
                profiles = await asyncio.to_thread(self.git.profiles)
                active = await asyncio.to_thread(self.git.active_profile_name)
                if not profiles:
                    self.notify("No Git profiles configured", title="Git profiles")
                    return
                lines = [
                    f"{'●' if item.name == active else ' '} {item.name} · "
                    f"{item.provider} · {item.account} · {item.email}"
                    for item in profiles
                ]
                self.notify("\n".join(lines), title="Git profiles", timeout=15)
            elif arguments[:3] == ["git", "profile", "use"] and len(arguments) == 4:
                profile = await asyncio.to_thread(self.git.use_profile, arguments[3])
                self.notify(
                    f"Using {profile.name} · {profile.account}\n"
                    f"Commits: {profile.author_name} <{profile.email}>",
                    title="Git profile",
                )
            elif arguments[:2] == ["git", "login"] and len(arguments) == 3:
                login = await asyncio.to_thread(self.git.login_command, arguments[2])
                self.action_terminal_open("side")
                self.terminal_pane.run_command(login)
            elif arguments == ["git", "status"]:
                output = await asyncio.to_thread(self.git.status)
                self.notify(output, title="Git status", timeout=15)
            elif arguments == ["git", "pull"]:
                output = await asyncio.to_thread(self.git.pull)
                self.notify(output, title="Git pull", timeout=15)
            elif arguments == ["git", "push"]:
                output = await asyncio.to_thread(self.git.push)
                self.notify(output, title="Git push", timeout=15)
            else:
                raise GitError(
                    "Use :git profile add/list/use, :git login PROFILE, "
                    ":git status, :git pull, or :git push"
                )
        except GitError as exc:
            self.notify(str(exc), title="Git", severity="error", timeout=15)

    def _configure_databricks_kernel(self, kernel: Optional[Kernel]) -> None:
        if kernel is None or self.databricks_connection is None:
            return
        kernel.set_initialization_code(
            databricks_kernel_code(
                self.databricks_connection.profile,
                self.databricks_connection.host,
                self.databricks_connection.auth_type,
            )
        )

    async def _connect_databricks(self, profile: Optional[str]) -> None:
        target_label = profile or "default authentication"
        self.notify(f"Connecting with {target_label}…", title="Databricks")
        try:
            connection = await asyncio.to_thread(connect_databricks, profile)
        except Exception as exc:
            self.notify(
                f"{exc}\nConfigure authentication with `databricks auth login` and try again.",
                title="Databricks connection failed",
                severity="error",
                timeout=15,
            )
            return
        self.databricks_connection = connection
        self.remote = None
        kernels = {id(tab.kernel): tab.kernel for tab in self.tabs if tab.kernel is not None}
        kernels[id(self.kernel)] = self.kernel
        for kernel in kernels.values():
            self._configure_databricks_kernel(kernel)
        self.notify(
            f"{connection.user_name} · {connection.host}\n"
            "Python cells now include `workspace` and `dbutils`.",
            title="Databricks connected",
            timeout=12,
        )

    def _show_databricks_status(self) -> None:
        connection = self.databricks_connection
        if connection is None:
            self.notify(
                "Not connected. Use :databricks connect [profile].",
                title="Databricks",
            )
            return
        profile = connection.profile or connection.auth_type or "default authentication"
        self.notify(
            f"{connection.user_name} · {connection.host}\nProfile: {profile}",
            title="Databricks connected",
        )

    @work(exclusive=False)
    async def action_run_cell(self, advance: bool = False) -> None:
        if not self._notebook_active:
            return
        if self.editor is not None:
            await self._finish_edit()
        index = self.selected
        await self._execute_cell(index)
        if advance:
            self._select(index + 1)

    @work(exclusive=False)
    async def run_cell_sequence(self, indices: list[int]) -> None:
        if not self._notebook_active:
            return
        for index in indices:
            if self.notebook.cells[index].cell_type == CellType.CODE:
                await self._execute_cell(index)

    async def _execute_cell(self, index: int) -> None:
        cell = self.notebook.cells[index]
        if cell.cell_type != CellType.CODE or index in self._running_cells:
            return
        self._running_cells.add(index)
        self._view(index).add_class("running")
        self._update_status("BUSY")

        async def update(_: ExecutionUpdate) -> None:
            self.notebook.dirty = True
            self._view(index).refresh(layout=True)
            self._update_status("BUSY")

        try:
            await self.kernel.execute(cell, update)
        except Exception as exc:
            self.notify(str(exc), title="Kernel error", severity="error")
        finally:
            self._running_cells.discard(index)
            self._view(index).remove_class("running")
            self._view(index).refresh(layout=True)
            self._update_status()

    def action_save(self) -> None:
        self._save()

    def _save(self) -> bool:
        if not self.tabs:
            self.notify("There is no open file to save")
            return True
        if self.parquet_preview is not None:
            self.notify("Parquet previews are read-only")
            return True
        if self.sql_document is not None:
            self.notify("SQL workspace queries live for this session; copy them to a .sql file to save")
            return True
        if self.dataset_profile is not None:
            self._save_profile()
            return True
        if self.remote_report is not None:
            self.notify("Remote reports are read-only")
            return True
        if self.inspection_report is not None:
            self.notify("Inspection reports are read-only")
            return True
        if self.text_buffer is not None:
            if self._active_tab.read_only:
                self.notify("Help is read-only")
                return True
            if self.text_editor is not None:
                self.text_buffer.text = self.text_editor.text
            try:
                save_text_buffer(self.text_buffer)
                self._quit_armed = False
                self.notify(f"Saved {self.text_buffer.path.name}")
                self._refresh_project_files()
                self._refresh_tabs()
                self._update_status()
                return True
            except Exception as exc:
                self.notify(str(exc), title="Save failed", severity="error")
                return False
        if self.editor is not None:
            cell = self.notebook.cells[self.selected]
            if cell.source != self.editor.text:
                cell.source = self.editor.text
                self.notebook.dirty = True
        try:
            save_notebook(self.notebook)
            self._quit_armed = False
            self.notify(f"Saved {self.notebook.path.name}")
            self._refresh_project_files()
            self._refresh_tabs()
            self._update_status()
            return True
        except Exception as exc:
            self.notify(str(exc), title="Save failed", severity="error")
            return False

    @work(exclusive=True)
    async def action_interrupt(self) -> None:
        if self.sql_document is not None and self.data_workspace is not None:
            self.data_workspace.interrupt()
            self.notify("SQL cancellation requested")
            return
        await self.kernel.interrupt()
        self.notify("Kernel interrupted")

    @work(exclusive=True)
    async def action_restart_kernel(self) -> None:
        try:
            await self.kernel.restart()
            self.notify("Kernel restarted; runtime state was cleared")
        except Exception as exc:
            self.notify(str(exc), title="Kernel restart failed", severity="error")

    @work(exclusive=True)
    async def action_shutdown_kernel(self) -> None:
        try:
            await self.kernel.shutdown()
            self.notify("Kernel shut down")
            self._update_status("DEAD")
        except Exception as exc:
            self.notify(str(exc), title="Kernel shutdown failed", severity="error")

    async def action_request_quit(self) -> None:
        if self.editor is not None:
            return
        if any(tab.dirty for tab in self.tabs):
            if not self._quit_armed:
                self._quit_armed = True
                self.notify(
                    "Unsaved changes — Ctrl+S to save, invoke :exit again to discard",
                    severity="warning",
                )
                return
        await self._shutdown_all_kernels()
        self.exit()

    async def on_unmount(self) -> None:
        await self.terminal_pane.shutdown()
        await self.ai_pane.shutdown()
        await self._shutdown_all_kernels()
        if self.data_workspace is not None:
            self.data_workspace.close()

    async def _shutdown_all_kernels(self) -> None:
        kernels = {id(tab.kernel): tab.kernel for tab in self.tabs if tab.kernel is not None}
        for kernel in kernels.values():
            await kernel.shutdown()


def run_tui(
    notebook: Notebook,
    workspace_root: Optional[Path] = None,
    initial_path: Optional[Path] = None,
    project_open: bool = True,
) -> None:
    NotebookApp(
        notebook,
        workspace_root=workspace_root,
        initial_path=initial_path,
        project_open=project_open,
    ).run()


def run_workspace(root: Path, initial_path: Optional[Path] = None) -> None:
    root = Path(root).resolve()
    notebooks = notebook_files(root)
    notebook = load_notebook(notebooks[0]) if notebooks else new_notebook(root / "untitled.ipynb")
    run_tui(notebook, workspace_root=root, initial_path=initial_path)


def run_empty_workspace(root: Optional[Path] = None) -> None:
    root = Path(root or Path.cwd()).resolve()
    run_tui(new_notebook(root / "untitled.ipynb"), workspace_root=root, project_open=False)
