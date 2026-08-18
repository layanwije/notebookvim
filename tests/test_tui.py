import asyncio
from pathlib import Path

import pytest

from nbcli.kernel import ExecutionUpdate
from nbcli.model import Cell, CellType, ExecutionState, Notebook, StreamOutput
from nbcli.storage import new_notebook, save_notebook
from nbcli.tui import NotebookApp


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
        await pilot.press("k", "enter")
        assert app.editor is not None
        assert app.editor.language == "python"
        assert app.editor.theme == "monokai"
        app.editor.text = "value = 2"
        await pilot.press("escape")
        await pilot.pause()
        assert app.editor is None
        assert notebook.cells[0].source == "value = 2"
        assert notebook.dirty


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
async def test_add_cell_above_and_below():
    original = Cell(CellType.CODE, "original = True", cell_id="cell0001")
    notebook = Notebook(path=Path("example.ipynb"), cells=[original])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert len(notebook.cells) == 2
        assert app.selected == 1
        assert notebook.cells[0] is original
        assert notebook.cells[1].source == ""

        await pilot.press("shift+a")
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

        await pilot.press("enter")
        assert app.editor is not None
        assert app.editor.language is None
        await pilot.press("escape")

        await pilot.press("m")
        await pilot.pause()
        assert cell.cell_type is CellType.CODE


@pytest.mark.asyncio
async def test_mac_style_editor_cursor_shortcuts():
    cell = Cell(CellType.CODE, "alpha beta\ngamma", cell_id="cell0001")
    notebook = Notebook(path=Path("example.ipynb"), cells=[cell])
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter")
        assert app.editor is not None

        app.editor.move_cursor((0, 3))
        await pilot.press("ctrl+right")
        assert app.editor.cursor_location == (0, 10)

        await pilot.press("ctrl+left")
        assert app.editor.cursor_location == (0, 0)

        await pilot.press("alt+right")
        assert 0 < app.editor.cursor_location[1] < 10


@pytest.mark.asyncio
async def test_python_cell_offers_and_accepts_local_completion():
    notebook = Notebook(
        path=Path("example.ipynb"),
        cells=[Cell(CellType.CODE, "", cell_id="cell0001")],
    )
    app = NotebookApp(notebook)

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter", "p", "r", "i")
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
        await pilot.press("p", "r", "i")
        await app.workers.wait_for_complete()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert app.completion_menu is not None

        await pilot.press("tab")
        assert app.text_editor.text == "print"
        await pilot.press("ctrl+z")
        assert app.text_editor.text == "pri"


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
async def test_text_file_escape_exposes_colon_commands_and_enter_resumes_editing(tmp_path):
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
        await pilot.press("enter")
        assert app.text_editor.has_focus


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
