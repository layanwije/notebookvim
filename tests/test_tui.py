import asyncio
from pathlib import Path

import pytest

from nbcli.workspace import ParquetPreview
from nbcli.kernel import ExecutionUpdate
from nbcli.databricks import DatabricksConnection
from nbcli.model import Cell, CellType, ExecutionState, Notebook, StreamOutput
from nbcli.remote import RemoteMapping, SyncStatus
from nbcli.storage import load_notebook, new_notebook, save_notebook
from nbcli.terminal import TerminalInput, TerminalPane
from nbcli.tui import InspectionModal, NotebookApp, TabBar


@pytest.mark.asyncio
async def test_navigation_and_editing():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[
            Cell(CellType.CODE, "value = 1", cell_id="cell0001"),
            Cell(CellType.MARKDOWN, "# Notes", cell_id="cell0002"),
        ],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert app.selected == 0
        await pilot.press("j")
        assert app.selected == 1
        await pilot.press("k", "i")
        assert app.editor is not None
        assert app.editor.language == "python"
        assert app.editor.theme == "monokai"
        app.editor.text = "value = 2"
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert app.editor is None
        assert notebook.cells[0].source == "value = 2"
        assert notebook.dirty


@pytest.mark.asyncio
async def test_notebook_vim_normal_mode_cell_operations():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[
            Cell(CellType.CODE, "first", cell_id="cell0001"),
            Cell(CellType.CODE, "second", cell_id="cell0002"),
        ],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter")
        assert app.editor is not None
        assert app.editor.vim_mode == "normal"
        assert app.editor.read_only

        await pilot.press("i")
        assert app.editor.vim_mode == "insert"
        await pilot.press("escape")
        assert app.editor is not None
        assert app.editor.vim_mode == "normal"
        await pilot.press("escape")
        assert app.editor is None

        await pilot.press("y", "y", "p")
        await pilot.pause()
        assert [cell.source for cell in notebook.cells] == ["first", "first", "second"]

        await pilot.press("d", "d")
        await pilot.pause()
        assert [cell.source for cell in notebook.cells] == ["first", "second"]

        await pilot.press("u")
        await pilot.pause()
        assert [cell.source for cell in notebook.cells] == ["first", "first", "second"]

        await pilot.press("ctrl+r", "shift+g")
        await pilot.pause()
        assert [cell.source for cell in notebook.cells] == ["first", "second"]
        assert app.selected == 1

        await pilot.press("g", "g")
        assert app.selected == 0


@pytest.mark.asyncio
async def test_app_themes_switch_chrome_editor_and_syntax_palette():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "value = 1", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        assert app.theme == "default"
        assert app.syntax_theme == "ansi_dark"

        for name in (
            "vscode-dark", "vscode-light", "databricks-light", "snowflake"
        ):
            await app._dispatch_command(f"theme {name}")
            await pilot.pause()
            assert app.theme == name
            assert app._nbcli_theme == name

        assert not app.current_theme.dark
        await pilot.press("enter")
        assert app.editor is not None
        assert app.editor.theme == "nbcli-snowflake"

        await app._dispatch_command("theme default")
        assert app.editor is not None
        assert app.editor.theme == "monokai"
        assert app.current_theme.dark


@pytest.mark.asyncio
async def test_run_binding_executes_selected_cell():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "40 + 2", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)

    class FakeKernel:
        async def execute(self, cell, update):
            cell.execution_state = ExecutionState.SUCCEEDED
            cell.execution_count = 1
            await update(ExecutionUpdate(ExecutionState.SUCCEEDED, execution_count=1))
            return True

        async def shutdown(self):
            return None

        async def interrupt(self):
            return None

    app.kernel = FakeKernel()

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("r")
        await app.workers.wait_for_complete()
        assert notebook.cells[0].execution_state is ExecutionState.SUCCEEDED
        assert notebook.cells[0].execution_count == 1
        assert not app._running_cells


@pytest.mark.asyncio
async def test_run_cell_number_command_executes_one_based_cell():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[
            Cell(CellType.CODE, "first = 1", cell_id="cell0001"),
            Cell(CellType.CODE, "second = 2", cell_id="cell0002"),
        ],
    )
    app = NotebookApp(notebook)
    executed = []

    class FakeKernel:
        async def execute(self, cell, update):
            executed.append(cell.source)
            cell.execution_state = ExecutionState.SUCCEEDED
            await update(ExecutionUpdate(ExecutionState.SUCCEEDED))
            return True

        async def shutdown(self):
            return None

        async def interrupt(self):
            return None

    app.kernel = FakeKernel()

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("colon")
        command = app.query_one("#command")
        command.value = "run cell 2"
        await pilot.press("enter")
        await app.workers.wait_for_complete()

        assert executed == ["second = 2"]
        assert app.selected == 1


@pytest.mark.asyncio
async def test_sql_workspace_runs_query_and_profiles_result(tmp_path):
    notebook = Notebook(
        path=tmp_path / "example.ipynb",
        cells=[Cell(CellType.CODE, "", cell_id="cell0001")],
    )
    app = NotebookApp(notebook, workspace_root=tmp_path)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("colon")
        app.query_one("#command").value = "sql"
        await pilot.press("enter")
        await pilot.pause()

        assert app.sql_editor is not None
        assert app.sql_editor.language == "sql"
        app.sql_editor.text = "select 42 as answer, 'ready' as status"
        await pilot.press("escape", "colon")
        app.query_one("#command").value = "sql run"
        await pilot.press("enter")
        await pilot.pause()

        assert app.sql_document is not None
        assert app.sql_document.result is not None
        assert app.sql_document.result.rows == [[42, "ready"]]

        app._save_sql_query()
        query_path = tmp_path / "queries" / "query-1.sql"
        tree = app.query_one("#files")
        queries_node = next(node for node in tree.root.children if node.label.plain == "queries")
        assert query_path.resolve() in [node.data for node in queries_node.children]
        assert query_path.resolve() in app.project_paths

        await pilot.press("escape", "colon")
        app.query_one("#command").value = "profile"
        await pilot.press("enter")
        await pilot.pause()

        assert app.dataset_profile is not None
        assert app.dataset_profile.row_count == 1
        assert app.dataset_profile.column_count == 2


@pytest.mark.asyncio
async def test_add_cell_above_and_below():
    original = Cell(CellType.CODE, "original = True", cell_id="cell0001")
    notebook = Notebook(path=Path("example.ipynb"), cells=[original])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert len(notebook.cells) == 2
        assert app.selected == 1
        assert notebook.cells[0] is original
        assert notebook.cells[1].source == ""

        await pilot.press("escape", "escape", "shift+o")
        await pilot.pause()
        assert len(notebook.cells) == 3
        assert app.selected == 1
        assert notebook.cells[2] is not original
        assert notebook.dirty
        assert len({cell.cell_id for cell in notebook.cells}) == 3


@pytest.mark.asyncio
async def test_output_clear_command_clears_only_selected_cell():
    first = Cell(
        CellType.CODE,
        "print('first')",
        outputs=[StreamOutput(output_type="stream", text="first\n")],
        cell_id="cell0001",
    )
    second = Cell(
        CellType.CODE,
        "print('second')",
        outputs=[StreamOutput(output_type="stream", text="second\n")],
        cell_id="cell0002",
    )
    notebook = Notebook(path=Path("example.ipynb"), cells=[first, second])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press(":")
        await pilot.pause()
        command = app.query_one("#command")
        assert command.display
        command.value = "output clear"
        await pilot.press("enter")
        await pilot.pause()

        assert first.outputs == []
        assert len(second.outputs) == 1
        assert notebook.dirty
        assert not command.display


@pytest.mark.asyncio
async def test_toggle_code_cell_to_rendered_markdown_and_back():
    cell = Cell(
        CellType.CODE,
        "# Spark quickstart",
        execution_count=4,
        outputs=[StreamOutput(output_type="stream", text="old output\n")],
        cell_id="cell0001",
    )
    notebook = Notebook(path=Path("example.ipynb"), cells=[cell])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("m")
        await pilot.pause()
        assert cell.cell_type is CellType.MARKDOWN
        assert cell.execution_count is None
        assert cell.outputs == []
        assert notebook.dirty

        await pilot.press("i")
        assert app.editor is not None
        assert app.editor.language is None
        await pilot.press("escape", "escape")

        await pilot.press("m")
        await pilot.pause()
        assert cell.cell_type is CellType.CODE


@pytest.mark.asyncio
async def test_platform_style_editor_cursor_shortcuts():
    cell = Cell(CellType.CODE, "alpha beta\ngamma", cell_id="cell0001")
    notebook = Notebook(path=Path("example.ipynb"), cells=[cell])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("i")
        assert app.editor is not None

        app.editor.move_cursor((0, 3))
        await pilot.press("super+right")
        assert app.editor.cursor_location == (0, 10)

        await pilot.press("super+left")
        assert app.editor.cursor_location == (0, 0)

        await pilot.press("ctrl+right")
        assert 0 < app.editor.cursor_location[1] < 10

        await pilot.press("ctrl+down")
        assert app.editor.cursor_location == (1, 5)

        await pilot.press("super+up")
        assert app.editor.cursor_location == (0, 0)


@pytest.mark.asyncio
async def test_python_cell_offers_and_accepts_local_completion():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("i", "p", "r", "i")
        await app.workers.wait_for_complete()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert app.completion_menu is not None
        await pilot.press("tab")
        assert app.editor is not None
        assert app.editor.text == "print"


@pytest.mark.asyncio
async def test_workspace_fuzzy_finder_opens_another_notebook(tmp_path):
    first_path = tmp_path / "first.ipynb"
    second_path = tmp_path / "nested" / "second.ipynb"
    save_notebook(new_notebook(first_path))
    save_notebook(new_notebook(second_path))
    app = NotebookApp(new_notebook(first_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.press("ctrl+p", "s", "e", "c")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert app.notebook.path == second_path.resolve()
        assert app.query_one("#files").display


@pytest.mark.asyncio
async def test_workspace_tree_uses_neovim_navigation_toggle(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        tree = app.query_one("#files")
        assert tree.display and not tree.has_focus

        await pilot.press("ctrl+b", "j")
        assert tree.has_focus
        assert tree.cursor_line > 0

        await pilot.press("ctrl+b")
        assert not tree.display


@pytest.mark.asyncio
async def test_workspace_does_not_discard_dirty_notebook(tmp_path):
    first_path = tmp_path / "first.ipynb"
    second_path = tmp_path / "second.ipynb"
    first = new_notebook(first_path)
    save_notebook(first)
    save_notebook(new_notebook(second_path))
    first.dirty = True
    app = NotebookApp(first, workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)):
        await app._open_project_file(second_path)

        assert app.notebook.path == first_path.resolve()


@pytest.mark.asyncio
async def test_workspace_opens_parquet_as_a_read_only_preview(tmp_path, monkeypatch):
    notebook_path = tmp_path / "notes.ipynb"
    parquet_path = tmp_path / "events.parquet"
    save_notebook(new_notebook(notebook_path))
    parquet_path.write_bytes(b"placeholder")
    preview = ParquetPreview(
        path=parquet_path.resolve(),
        columns=["event", "count"],
        rows=[["opened", 1]],
        total_rows=1,
    )
    monkeypatch.setattr("nbcli.tui.load_parquet_preview", lambda path: preview)
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)):
        await app._open_project_file(parquet_path)

        assert app.parquet_preview == preview
        assert app.query_one("#parquet-preview").preview.rows == [["opened", 1]]
        assert "PARQUET" in str(app.query_one("#status").render())


@pytest.mark.asyncio
async def test_parquet_inspect_is_contextual_and_opens_report(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    notebook_path = tmp_path / "notes.ipynb"
    parquet_path = tmp_path / "events.parquet"
    save_notebook(new_notebook(notebook_path))
    pq.write_table(pa.table({"event": ["open", "save"], "count": [1, 2]}), parquet_path)
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 34)) as pilot:
        await app._open_project_file(parquet_path)
        assert app._contextual_command_suggestions()[0] == "inspect parquet describe"

        await pilot.press("colon")
        command = app.query_one("#command")
        command.value = "inspect"
        await pilot.pause()
        assert command._suggestion == "inspect parquet"

        await pilot.press("tab")
        assert command.value == "inspect parquet"
        command.value = "inspect parquet d"
        await pilot.pause()
        assert command._suggestion == "inspect parquet describe"

        command.value = "inspect parquet describe"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, InspectionModal)
        assert app.screen.report.title == "Parquet describe · events.parquet"
        assert ["rows", "2"] in app.screen.report.rows
        assert len(app.tabs) == 1
        assert app._active_path == parquet_path.resolve()

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, InspectionModal)
        assert app.parquet_preview is not None

        await submit_command(app, pilot, "inspect parquet schema side")
        pane = app.query_one("#inspection-pane")
        assert pane.display
        assert pane.report.title == "Parquet schema · events.parquet"
        assert app.query_one("#document-column").has_class("inspection-side")

        await pilot.press("escape")
        assert not pane.display
        assert app.parquet_preview is not None

        await submit_command(app, pilot, "inspect parquet rowgroups below")
        assert pane.display
        assert pane.report.title == "Parquet row groups · events.parquet"
        assert app.query_one("#document-column").has_class("inspection-below")

        await app._dispatch_command("inspect close")
        assert not pane.display


@pytest.mark.asyncio
async def test_workspace_opens_edits_and_saves_python_file(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("answer = 40\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(python_path)
        assert app.text_buffer is not None
        assert app.text_editor is not None
        assert app.text_editor.language == "python"

        app.text_editor.text = "answer = 42\n"
        await pilot.pause()
        assert app.text_buffer.dirty
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert python_path.read_text(encoding="utf-8") == "answer = 42\n"
        assert not app.text_buffer.dirty

        await app._open_project_file(notebook_path)
        assert app.text_buffer is None
        assert app.text_editor is None
        assert app.notebook.path == notebook_path.resolve()


@pytest.mark.asyncio
async def test_workspace_does_not_discard_dirty_text_file(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("answer = 40\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(python_path)
        assert app.text_editor is not None
        app.text_editor.text = "changed = True\n"
        await pilot.pause()
        await app._open_project_file(notebook_path)

        assert app.text_buffer is not None
        assert app.text_buffer.path == python_path.resolve()


@pytest.mark.asyncio
async def test_python_text_file_has_intellisense_and_undo(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(python_path)
        assert app.text_editor is not None
        assert app.text_editor.vim_mode == "normal"
        assert app.text_editor.read_only
        await pilot.press("i", "p", "r", "i")
        await app.workers.wait_for_complete()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert app.completion_menu is not None

        await pilot.press("tab")
        assert app.text_editor.text == "print"
        await pilot.press("ctrl+z")
        assert app.text_editor.text == "pri"


@pytest.mark.asyncio
async def test_text_file_vim_modes_and_line_operations(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("one\ntwo\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(python_path)
        editor = app.text_editor
        assert editor is not None
        assert editor.vim_mode == "normal"
        assert editor.read_only

        await pilot.press("c")
        assert editor.text == "one\ntwo\n"

        await pilot.press("i", "z", "escape")
        assert editor.text == "zone\ntwo\n"
        assert editor.vim_mode == "normal"
        assert editor.read_only

        await pilot.press("d", "d")
        assert editor.text == "two\n"
        await pilot.press("u")
        assert editor.text == "zone\ntwo\n"


@pytest.mark.asyncio
async def test_markdown_text_file_uses_markdown_highlighting(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    markdown_path = tmp_path / "README.md"
    save_notebook(new_notebook(notebook_path))
    markdown_path.write_text("# Project\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)):
        await app._open_project_file(markdown_path)

        assert app.text_editor is not None
        assert app.text_editor.language == "markdown"


@pytest.mark.asyncio
async def test_text_file_escape_exposes_commands_and_i_resumes_editing(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("answer = 40\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(python_path)
        assert app.text_editor is not None
        app.text_editor.text = "answer = 42\n"
        await pilot.pause()

        await pilot.press("escape", "colon")
        command = app.query_one("#command")
        assert command.display and command.has_focus
        command.value = "w"
        await pilot.press("enter")
        await pilot.pause()
        assert python_path.read_text(encoding="utf-8") == "answer = 42\n"

        await pilot.press("escape")
        await pilot.press("i")
        assert app.text_editor.has_focus
        assert app.text_editor.vim_mode == "insert"
        assert not app.text_editor.read_only


@pytest.mark.asyncio
async def test_file_browser_opens_tabs_and_shortcuts_switch_focus_and_tabs(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    markdown_path = tmp_path / "README.md"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("answer = 42\n", encoding="utf-8")
    markdown_path.write_text("# Notes\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 32)) as pilot:
        tree = app.query_one("#files")
        await pilot.press("ctrl+tab")
        assert tree.has_focus

        python_node = next(node for node in tree.root.children if node.data == python_path.resolve())
        tree.move_cursor(python_node)
        await pilot.press("alt+enter")
        await app.workers.wait_for_complete()
        assert len(app.tabs) == 2
        assert app._active_path == python_path.resolve()

        await pilot.press("ctrl+tab")
        assert tree.has_focus
        markdown_node = next(
            node for node in tree.root.children if node.data == markdown_path.resolve()
        )
        tree.move_cursor(markdown_node)
        await pilot.press("alt+enter")
        await app.workers.wait_for_complete()
        assert len(app.tabs) == 3
        assert app._active_path == markdown_path.resolve()

        await pilot.press("shift+tab")
        await app.workers.wait_for_complete()
        assert app._active_path == notebook_path.resolve()


@pytest.mark.asyncio
async def test_workspace_supports_many_open_file_tabs(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    text_paths = [tmp_path / f"file-{index}.py" for index in range(6)]
    for index, path in enumerate(text_paths):
        path.write_text(f"value = {index}\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(55, 26)):
        for path in text_paths:
            await app._open_project_file(path, new_tab=True)

        tab_bar = app.query_one("#tabs", TabBar)
        assert len(app.tabs) == 7
        assert tab_bar.tab_count == 7
        assert tab_bar.active == "document-tab-6"
        assert app._active_path == text_paths[-1].resolve()


@pytest.mark.asyncio
async def test_tab_close_activates_neighbor_and_reindexes_tabs(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    save_notebook(new_notebook(notebook_path))
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 2\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(first, new_tab=True)
        await app._open_project_file(second, new_tab=True)
        assert app._active_path == second.resolve()

        await pilot.press("ctrl+w")
        await app.workers.wait_for_complete()

        assert len(app.tabs) == 2
        assert app._active_path == first.resolve()
        tab_bar = app.query_one("#tabs", TabBar)
        assert tab_bar.tab_count == 2
        assert tab_bar.active == "document-tab-1"

        await pilot.press("escape")
        await submit_command(app, pilot, "tab close")
        assert len(app.tabs) == 1
        assert app._active_path == notebook_path.resolve()


@pytest.mark.asyncio
async def test_tab_close_requires_confirmation_for_unsaved_changes(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    text_path = tmp_path / "draft.py"
    save_notebook(new_notebook(notebook_path))
    text_path.write_text("value = 1\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)):
        await app._open_project_file(text_path, new_tab=True)
        assert app.text_buffer is not None
        app.text_buffer.dirty = True

        await app._close_active_tab()
        assert len(app.tabs) == 2

        await app._close_active_tab()
        assert len(app.tabs) == 1
        assert app._active_path == notebook_path.resolve()


@pytest.mark.asyncio
async def test_q_command_and_escape_q_close_active_tab(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    save_notebook(new_notebook(notebook_path))
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 2\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(100, 30)) as pilot:
        await app._open_project_file(first, new_tab=True)
        await submit_command(app, pilot, "q")
        assert app._active_path == notebook_path.resolve()

        await app._open_project_file(second, new_tab=True)
        await pilot.press("escape", "q")
        await app.workers.wait_for_complete()
        assert app._active_path == notebook_path.resolve()


@pytest.mark.asyncio
async def test_exit_command_requests_program_exit():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)
    called = False

    async def request_exit():
        nonlocal called
        called = True

    app.action_request_quit = request_exit
    await app._dispatch_command("exit")
    assert called


@pytest.mark.asyncio
async def test_terminal_safe_file_tab_shortcuts(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    python_path = tmp_path / "helpers.py"
    markdown_path = tmp_path / "README.md"
    save_notebook(new_notebook(notebook_path))
    python_path.write_text("answer = 42\n", encoding="utf-8")
    markdown_path.write_text("# Notes\n", encoding="utf-8")
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 32)) as pilot:
        tree = app.query_one("#files")
        await pilot.press("ctrl+b")
        python_node = next(node for node in tree.root.children if node.data == python_path.resolve())
        tree.move_cursor(python_node)
        await pilot.press("t")
        await app.workers.wait_for_complete()
        assert app._active_path == python_path.resolve()

        await pilot.press("escape", "left_square_bracket")
        await app.workers.wait_for_complete()
        assert app._active_path == notebook_path.resolve()
        await pilot.press("right_square_bracket")
        await app.workers.wait_for_complete()
        assert app._active_path == python_path.resolve()

        await pilot.press("ctrl+b")
        markdown_node = next(
            node for node in tree.root.children if node.data == markdown_path.resolve()
        )
        tree.move_cursor(markdown_node)
        await pilot.press("escape", "enter")
        await app.workers.wait_for_complete()
        assert app._active_path == markdown_path.resolve()


async def submit_command(app, pilot, value):
    await pilot.press(":")
    command = app.query_one("#command")
    command.value = value
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_cell_structure_and_type_commands():
    first = Cell(
        CellType.CODE,
        "value = 1",
        outputs=[StreamOutput(output_type="stream", text="one\n")],
        cell_id="cell0001",
    )
    second = Cell(CellType.CODE, "value = 2", cell_id="cell0002")
    notebook = Notebook(path=Path("example.ipynb"), cells=[first, second])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await submit_command(app, pilot, "cell duplicate")
        assert len(notebook.cells) == 3
        assert app.selected == 1
        assert notebook.cells[1].cell_id != first.cell_id

        await submit_command(app, pilot, "cell output collapse")
        assert app._view(1).output_collapsed
        await submit_command(app, pilot, "cell output expand")
        assert not app._view(1).output_collapsed

        await submit_command(app, pilot, "cell move down")
        assert app.selected == 2
        await submit_command(app, pilot, "cell type markdown")
        assert notebook.cells[2].cell_type is CellType.MARKDOWN
        assert notebook.cells[2].outputs == []

        await submit_command(app, pilot, "cell move up")
        assert app.selected == 1
        await submit_command(app, pilot, "cell delete")
        assert len(notebook.cells) == 2
        assert notebook.dirty


@pytest.mark.asyncio
async def test_notebook_run_and_output_commands():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[
            Cell(CellType.CODE, "first", cell_id="cell0001"),
            Cell(CellType.MARKDOWN, "# Notes", cell_id="cell0002"),
            Cell(CellType.CODE, "second", cell_id="cell0003"),
        ],
    )
    executed = []
    app = NotebookApp(notebook)

    class FakeKernel:
        alive = True

        async def execute(self, cell, update):
            executed.append(cell.source)
            cell.outputs.append(StreamOutput(output_type="stream", text=cell.source))
            cell.execution_state = ExecutionState.SUCCEEDED
            await update(ExecutionUpdate(ExecutionState.SUCCEEDED))
            return True

        async def shutdown(self):
            return None

        async def interrupt(self):
            return None

    app.kernel = FakeKernel()

    async with app.run_test(size=(100, 32)) as pilot:
        await submit_command(app, pilot, "run all")
        await app.workers.wait_for_complete()
        assert executed == ["first", "second"]
        assert len(notebook.cells[0].outputs) == 1
        assert len(notebook.cells[2].outputs) == 1

        await submit_command(app, pilot, "notebook output clear")
        assert all(cell.outputs == [] for cell in notebook.cells)


@pytest.mark.asyncio
async def test_command_intellisense_from_open_and_prefix():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "pass", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press(":")
        await pilot.pause()
        command = app.query_one("#command")
        assert command._suggestion == "cell run"

        command.value = "cell o"
        command.cursor_position = len(command.value)
        await pilot.pause()
        assert command._suggestion == "cell output clear"

        await pilot.press("tab")
        assert command.value == "cell output clear"


@pytest.mark.asyncio
async def test_terminal_commands_open_run_and_close_split(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 34)) as pilot:
        pane = app.query_one("#terminal-pane", TerminalPane)
        assert not pane.display

        await submit_command(app, pilot, "terminal open")
        terminal_input = pane.query_one("#terminal-input", TerminalInput)
        assert pane.display
        assert terminal_input.has_focus
        assert app.terminal_placement == "side"
        assert app.query_one("#document-column").has_class("terminal-side")

        terminal_input.value = "printf terminal-ok"
        await pilot.press("enter")
        await pane.workers.wait_for_complete()
        assert "terminal-ok" in pane.transcript

        await pilot.press("escape")
        await submit_command(app, pilot, "terminal close")
        assert not pane.display
        assert app._view(app.selected).has_focus


@pytest.mark.asyncio
async def test_terminal_can_open_below_and_return_to_default_side(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)

    async with app.run_test(size=(110, 34)) as pilot:
        document = app.query_one("#document-column")
        await submit_command(app, pilot, "terminal open below")
        assert app.terminal_placement == "below"
        assert document.has_class("terminal-below")

        await pilot.press("escape")
        await submit_command(app, pilot, "terminal")
        assert app.terminal_placement == "side"
        assert document.has_class("terminal-side")
        assert not document.has_class("terminal-below")


@pytest.mark.asyncio
async def test_databricks_connect_configures_notebook_kernel(tmp_path, monkeypatch):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    app = NotebookApp(new_notebook(notebook_path), workspace_root=tmp_path)
    connection = DatabricksConnection(
        profile="MyProfile",
        host="https://example.cloud.databricks.com",
        user_name="user@example.com",
    )
    monkeypatch.setattr("nbcli.tui.connect_databricks", lambda profile: connection)

    async with app.run_test(size=(110, 34)) as pilot:
        await submit_command(app, pilot, "databricks connect MyProfile")

        assert app.databricks_connection == connection
        assert app.kernel.initialization_code is not None
        assert "WorkspaceClient(profile='MyProfile')" in app.kernel.initialization_code
        assert "dbutils = workspace.dbutils" in app.kernel.initialization_code


@pytest.mark.asyncio
async def test_remote_sync_commands_create_status_report(tmp_path):
    notebook_path = tmp_path / "notes.ipynb"
    save_notebook(new_notebook(notebook_path))
    app = NotebookApp(load_notebook(notebook_path), workspace_root=tmp_path)
    app.databricks_connection = DatabricksConnection(
        profile="Test", host="https://example.cloud.databricks.com", user_name="user"
    )
    calls = []

    class FakeRemote:
        def configure(self, path, remote_path, strip_outputs=False):
            calls.append(("configure", path, remote_path, strip_outputs))
            return RemoteMapping("databricks", remote_path)

        def push(self, path, local_content=None, force=False):
            calls.append(("push", path))
            return SyncStatus(path, "/Workspace/notes", False, False, 123, True)

        def status(self, path, local_content=None):
            calls.append(("status", path))
            return SyncStatus(path, "/Workspace/notes", False, False, 123, True)

    app.remote = FakeRemote()

    async with app.run_test(size=(110, 34)) as pilot:
        await submit_command(app, pilot, "databricks sync set /Workspace/notes")
        await submit_command(app, pilot, "databricks sync push")
        await submit_command(app, pilot, "databricks sync status")

        assert [call[0] for call in calls] == ["configure", "push", "status"]
        assert app.remote_report is not None
        assert app.remote_report.title == "Remote status · synchronized"
