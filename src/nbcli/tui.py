from __future__ import annotations

import asyncio
import copy
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.suggester import Suggester, SuggestFromList
from textual.widgets import Footer, Header, Input, Static, TextArea, Tree

from .commands import COMMANDS, COMMAND_SUGGESTIONS, normalize_command
from .completion import python_completions
from .kernel import ExecutionUpdate, Kernel
from .model import Cell, CellType, Notebook
from .rendering import render_cell
from .storage import load_notebook, new_notebook, save_notebook
from .workspace import (
    TextBuffer,
    is_supported_text_file,
    load_text_buffer,
    notebook_files,
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
            self.notebook.cells[self.index], self.index, show_output=not self.output_collapsed
        )


@dataclass
class DocumentTab:
    path: Path
    notebook: Optional[Notebook] = None
    text_buffer: Optional[TextBuffer] = None
    kernel: Optional[Kernel] = None
    selected: int = 0
    collapsed_outputs: set[str] = field(default_factory=set)

    @property
    def dirty(self) -> bool:
        if self.text_buffer is not None:
            return self.text_buffer.dirty
        return bool(self.notebook and self.notebook.dirty)


class CellEditor(TextArea):
    BINDINGS = [
        Binding("escape", "finish_edit", "Navigation", priority=True),
        Binding("ctrl+left", "cursor_line_start", "Line start", priority=True),
        Binding("ctrl+right", "cursor_line_end", "Line end", priority=True),
        Binding("ctrl+shift+left", "cursor_line_start(True)", "Select to line start", priority=True),
        Binding("ctrl+shift+right", "cursor_line_end(True)", "Select to line end", priority=True),
        Binding("alt+left", "cursor_word_left", "Previous word", priority=True),
        Binding("alt+right", "cursor_word_right", "Next word", priority=True),
        Binding("alt+shift+left", "cursor_word_left(True)", "Select previous word", priority=True),
        Binding("alt+shift+right", "cursor_word_right(True)", "Select next word", priority=True),
        Binding("tab", "accept_completion", "Complete", priority=True),
    ]

    async def action_finish_edit(self) -> None:
        await self.app._finish_edit()  # type: ignore[attr-defined]

    def action_accept_completion(self) -> None:
        self.app.accept_completion()  # type: ignore[attr-defined]


class TextFileEditor(TextArea):
    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("escape", "leave_edit", "Normal mode", priority=True),
        Binding("tab", "complete_or_indent", "Complete", priority=True),
    ]

    def action_leave_edit(self) -> None:
        self.app.leave_text_editor()  # type: ignore[attr-defined]

    def action_complete_or_indent(self) -> None:
        accepted = self.app.accept_completion()  # type: ignore[attr-defined]
        if not accepted:
            self.insert("    ")


class CommandInput(Input):
    BINDINGS = [
        Binding("escape", "cancel_command", "Cancel", priority=True),
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
        if self._suggestion:
            self.value = self._suggestion
            self.cursor_position = len(self.value)


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


class TabBar(Static, can_focus=True):
    pass


class NotebookApp(App[None]):
    TITLE = "nbcli"
    CSS = """
    Screen { background: $surface; }
    #workspace { height: 1fr; }
    #tabs {
        height: 1; padding: 0 1;
        background: $surface-lighten-1; color: $text-muted;
    }
    #files {
        width: 32; min-width: 20; height: 100%;
        border-right: solid $surface-lighten-2;
        background: $surface-darken-1;
    }
    #notebook { padding: 1 2; }
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
    #completion-menu {
        width: 48; height: auto; max-height: 8;
        margin: -1 0 1 4; padding: 0 1;
        background: $panel; border: round $accent;
    }
    #status { dock: bottom; height: 1; padding: 0 1; background: $primary-darken-2; }
    #command {
        dock: bottom; height: 3; border: tall $accent; padding: 0 1;
    }
    #file-picker {
        dock: top; height: 3; border: tall $accent; padding: 0 1;
    }
    """
    BINDINGS = [
        ("j,down", "next_cell", "Next"),
        ("k,up", "previous_cell", "Previous"),
        ("enter", "edit_cell", "Edit"),
        ("r", "run_cell(False)", "Run"),
        ("shift+r", "run_cell(True)", "Run + next"),
        ("a", "insert_cell(False)", "Add below"),
        ("shift+a", "insert_cell(True)", "Add above"),
        ("m", "toggle_cell_type", "Code/Markdown"),
        ("colon", "command", "Command"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+c", "interrupt", "Interrupt"),
        Binding("ctrl+b", "toggle_files", "Files", priority=True),
        Binding("ctrl+p", "find_file", "Find", priority=True),
        Binding("ctrl+tab", "toggle_file_focus", "Files/editor", priority=True),
        Binding("shift+tab", "next_tab", "Next tab", priority=True),
        Binding("ctrl+shift+tab", "previous_tab", "Previous tab", priority=True),
        Binding("left_square_bracket", "previous_tab", "Previous tab"),
        Binding("right_square_bracket", "next_tab", "Next tab"),
        Binding("ctrl+q", "request_quit", "Quit", priority=True),
        Binding("q", "request_quit", "Quit", show=False),
    ]

    def __init__(
        self,
        notebook: Notebook,
        workspace_root: Optional[Path] = None,
        initial_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.notebook = notebook
        self.workspace_root = Path(workspace_root or notebook.path.parent).resolve()
        self.initial_path = Path(initial_path).resolve() if initial_path is not None else None
        self.project_paths = project_files(self.workspace_root)
        self.selected = 0
        self.editor: Optional[CellEditor] = None
        self.text_buffer: Optional[TextBuffer] = None
        self.text_editor: Optional[TextArea] = None
        self.completion_menu: Optional[Static] = None
        self._completion_revision = 0
        self._completions: list[str] = []
        self.kernel = Kernel(notebook.kernel_name)
        self.tabs = [
            DocumentTab(
                path=notebook.path.resolve(),
                notebook=notebook,
                kernel=self.kernel,
            )
        ]
        self.active_tab_index = 0
        self._running_cells: set[int] = set()
        self._collapsed_outputs: set[str] = set()
        self._quit_armed = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield TabBar(id="tabs")
        yield ProjectFileInput(
            [str(path.relative_to(self.workspace_root)) for path in self.project_paths],
            placeholder="Find project file",
            id="file-picker",
        )
        with Horizontal(id="workspace"):
            yield self._project_tree()
            with VerticalScroll(id="notebook"):
                for index in range(len(self.notebook.cells)):
                    yield self._new_view(index)
        yield Static(id="status")
        yield CommandInput(placeholder="Command", id="command")
        yield Footer()

    def on_mount(self) -> None:
        self._update_sub_title()
        self._select(0)
        self.query_one("#command", CommandInput).display = False
        self.query_one("#file-picker", ProjectFileInput).display = False
        self._refresh_tabs()
        self._update_status("IDLE")
        if self.initial_path is not None and self.initial_path != self.notebook.path.resolve():
            self.run_worker(self._open_project_file(self.initial_path))

    def _project_tree(self) -> ProjectTree:
        tree = ProjectTree(self.workspace_root.name, self.workspace_root, id="files")
        nodes = {Path(): tree.root}
        for file_path in self.project_paths:
            relative = file_path.relative_to(self.workspace_root)
            current = Path()
            for part in relative.parts[:-1]:
                parent = nodes[current]
                current /= part
                if current not in nodes:
                    nodes[current] = parent.add(part, self.workspace_root / current)
            nodes[current].add_leaf(relative.name, file_path)
        tree.root.expand()
        return tree

    def _update_sub_title(self) -> None:
        path = self.text_buffer.path if self.text_buffer is not None else self.notebook.path
        try:
            self.sub_title = str(path.resolve().relative_to(self.workspace_root))
        except ValueError:
            self.sub_title = path.name

    @property
    def _active_tab(self) -> DocumentTab:
        return self.tabs[self.active_tab_index]

    def _refresh_tabs(self) -> None:
        line = Text()
        for index, tab in enumerate(self.tabs):
            if index:
                line.append(" │ ", style="dim")
            marker = "●" if tab.dirty else ""
            label = f" {tab.path.name}{marker} "
            line.append(label, style="reverse bold" if index == self.active_tab_index else "")
        self.query_one("#tabs", Static).update(line)

    def _sync_active_tab(self) -> None:
        tab = self._active_tab
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
        if tab.text_buffer is not None:
            self.text_buffer = tab.text_buffer
            self.text_editor = await self._mount_text_editor(notebook_view, tab.text_buffer)
            self.text_editor.focus()
        else:
            assert tab.notebook is not None
            self.text_buffer = None
            self.text_editor = None
            self.notebook = tab.notebook
            if tab.kernel is None:
                tab.kernel = Kernel(self.notebook.kernel_name)
            self.kernel = tab.kernel
            self.selected = tab.selected
            self._collapsed_outputs = set(tab.collapsed_outputs)
            await notebook_view.mount(
                *(self._new_view(cell_index) for cell_index in range(len(self.notebook.cells)))
            )
            self._select(self.selected)
        self._quit_armed = False
        self._update_sub_title()
        self._refresh_tabs()
        self._update_status()

    @property
    def _notebook_active(self) -> bool:
        return self.text_buffer is None

    @property
    def _document_dirty(self) -> bool:
        return self.text_buffer.dirty if self.text_buffer is not None else self.notebook.dirty

    @property
    def _active_path(self) -> Path:
        return self.text_buffer.path if self.text_buffer is not None else self.notebook.path.resolve()

    def _focus_document(self) -> None:
        if self.text_editor is not None:
            self.text_editor.focus()
        else:
            self._view(self.selected).focus(scroll_visible=True)

    def leave_text_editor(self) -> None:
        if self.text_editor is None or self.text_buffer is None:
            return
        self.query_one("#tabs", TabBar).focus()
        dirty = " ●" if self.text_buffer.dirty else ""
        self.query_one("#status", Static).update(
            f" NORMAL TEXT │ Enter: edit │ : commands │ {self.text_buffer.path.name}{dirty}"
        )

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
        if self.text_buffer is not None:
            dirty = " ●" if self.text_buffer.dirty else ""
            self.query_one("#status", Static).update(
                f" TEXT │ Ctrl+S: save │ Ctrl+P: find │ {self.text_buffer.path.name}{dirty}"
            )
            return
        dirty = " ●" if self.notebook.dirty else ""
        state = kernel_state or ("BUSY" if self._running_cells else "IDLE")
        text = (f" NORMAL │ {self.notebook.kernel_name} · {state} │ "
                f"Cell {self.selected + 1}/{len(self.notebook.cells)} │ {self.notebook.path.name}{dirty}")
        self.query_one("#status", Static).update(text)

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
            elif is_supported_text_file(path):
                buffer = load_text_buffer(path)
                tab = DocumentTab(path=path, text_buffer=buffer)
            else:
                self.notify(f"Unsupported file type: {path.name}", severity="warning")
                return
        except Exception as exc:
            self.notify(str(exc), title="Open failed", severity="error")
            return
        if new_tab:
            self.tabs.append(tab)
            target = len(self.tabs) - 1
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
        self, notebook_view: VerticalScroll, buffer: TextBuffer
    ) -> TextArea:
        editor = TextFileEditor.code_editor(
            buffer.text,
            language=buffer.language,
            id="text-file-editor",
        )
        editor.add_class("text-file-editor")
        await notebook_view.mount(editor)
        return editor

    def action_next_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(self.selected + 1)

    def action_previous_cell(self) -> None:
        if self._notebook_active and self.editor is None:
            self._select(self.selected - 1)

    async def action_edit_cell(self) -> None:
        if self.text_editor is not None:
            self.text_editor.focus()
            self._update_status()
            return
        if not self._notebook_active or self.editor is not None:
            return
        cell = self.notebook.cells[self.selected]
        language = "python" if cell.cell_type == CellType.CODE else None
        editor = CellEditor.code_editor(cell.source, language=language, id="cell-editor")
        editor.add_class("cell-editor")
        editor.border_title = f"Cell {self.selected + 1} · Edit"
        self.editor = editor
        view = self._view(self.selected)
        view.display = False
        await view.parent.mount(editor, before=view)
        editor.focus()
        self.query_one("#status", Static).update(" EDIT │ Escape: navigation │ Ctrl+S: save")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Request suggestions without blocking interactive editing."""
        if event.text_area is self.text_editor and self.text_buffer is not None:
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
        if event.key == "escape" and self.editor is not None:
            event.stop()
            await self._finish_edit()

    async def _finish_edit(self) -> None:
        assert self.editor is not None
        editor = self.editor
        await self._clear_completions()
        cell = self.notebook.cells[self.selected]
        if cell.source != editor.text:
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
        self.notebook.cells[self.selected], self.notebook.cells[destination] = (
            self.notebook.cells[destination], self.notebook.cells[self.selected]
        )
        self.notebook.dirty = True
        await self._rebuild_cells(destination)

    def action_toggle_cell_type(self) -> None:
        if not self._notebook_active or self.editor is not None or self.selected in self._running_cells:
            return
        cell = self.notebook.cells[self.selected]
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
        if self.editor is not None or (self.text_editor is not None and self.text_editor.has_focus):
            return
        command = self.query_one("#command", CommandInput)
        command.value = ""
        command.display = True
        command.focus()
        self.call_after_refresh(
            lambda: setattr(command, "_suggestion", COMMAND_SUGGESTIONS[0])
            if command.display and not command.value
            else None
        )
        self.query_one("#status", Static).update(
            " COMMAND │ Tab: complete │ :help lists commands │ Escape: cancel"
        )

    def close_command(self) -> None:
        command = self.query_one("#command", CommandInput)
        command.value = ""
        command.display = False
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
        elif command == "tab open":
            self.action_open_selected_in_tab()
        elif command == "tab next":
            self.action_next_tab()
        elif command == "tab previous":
            self.action_previous_tab()
        elif command == "files focus":
            self.action_toggle_file_focus()
        elif command == "help":
            self.notify("\n".join(f":{item}" for item in COMMANDS), title="Commands", timeout=15)
        elif command == "quit":
            await self.action_request_quit()
        elif command == "write quit":
            if self._save():
                if any(tab.dirty for tab in self.tabs):
                    self.notify(
                        "Other tabs have unsaved changes; save them before quitting",
                        severity="warning",
                    )
                else:
                    await self._shutdown_all_kernels()
                    self.exit()
        elif command:
            self.notify(f"Unknown command: {command}", severity="warning")

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
        if self.text_buffer is not None:
            if self.text_editor is not None:
                self.text_buffer.text = self.text_editor.text
            try:
                save_text_buffer(self.text_buffer)
                self._quit_armed = False
                self.notify(f"Saved {self.text_buffer.path.name}")
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
            self._refresh_tabs()
            self._update_status()
            return True
        except Exception as exc:
            self.notify(str(exc), title="Save failed", severity="error")
            return False

    @work(exclusive=True)
    async def action_interrupt(self) -> None:
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
                    "Unsaved changes — Ctrl+S to save, invoke quit again to discard",
                    severity="warning",
                )
                return
        await self._shutdown_all_kernels()
        self.exit()

    async def on_unmount(self) -> None:
        await self._shutdown_all_kernels()

    async def _shutdown_all_kernels(self) -> None:
        kernels = {id(tab.kernel): tab.kernel for tab in self.tabs if tab.kernel is not None}
        for kernel in kernels.values():
            await kernel.shutdown()


def run_tui(
    notebook: Notebook,
    workspace_root: Optional[Path] = None,
    initial_path: Optional[Path] = None,
) -> None:
    NotebookApp(notebook, workspace_root=workspace_root, initial_path=initial_path).run()


def run_workspace(root: Path, initial_path: Optional[Path] = None) -> None:
    root = Path(root).resolve()
    notebooks = notebook_files(root)
    notebook = load_notebook(notebooks[0]) if notebooks else new_notebook(root / "untitled.ipynb")
    run_tui(notebook, workspace_root=root, initial_path=initial_path)
