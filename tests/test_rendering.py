from rich.console import Console

from notebookvim.model import Cell, CellType, DisplayOutput, ErrorOutput, StreamOutput
from notebookvim.rendering import render_cell, safe_text


def test_safe_text_removes_terminal_control_sequences():
    value = "safe\x1b[2J\x1b]0;owned\x07 text\x00\r"
    assert safe_text(value) == "safe text"


def test_safe_text_truncates_large_output():
    result = safe_text("x" * 100_001)
    assert len(result) < 100_100
    assert "truncated" in result


def test_cell_source_and_output_have_distinct_labels():
    cell = Cell(
        CellType.CODE,
        "21 * 2",
        execution_count=3,
        outputs=[
            DisplayOutput(
                output_type="execute_result",
                execution_count=3,
                data={"text/plain": "42"},
            )
        ],
    )
    console = Console(width=60, color_system=None, force_terminal=False)
    with console.capture() as capture:
        console.print(render_cell(cell, 0))

    rendered = capture.get()
    assert "Cell 1" in rendered
    assert "Python" in rendered
    assert "In [3]" in rendered
    assert "Out [3]" in rendered
    assert "21 * 2" in rendered
    assert "42" in rendered


def test_cell_uses_one_based_display_number():
    cell = Cell(CellType.CODE, "pass")
    console = Console(width=60, color_system=None, force_terminal=False)
    with console.capture() as capture:
        console.print(render_cell(cell, 4))

    assert "Cell 5" in capture.get()


def test_markdown_headings_are_left_aligned():
    cell = Cell(CellType.MARKDOWN, "# Left aligned heading\n\nParagraph")
    console = Console(width=60, color_system=None, force_terminal=False)
    with console.capture() as capture:
        console.print(render_cell(cell, 0))

    lines = capture.get().splitlines()
    heading_line = next(line for line in lines if "Left aligned heading" in line)
    paragraph_line = next(line for line in lines if "Paragraph" in line)
    assert heading_line.startswith("Left aligned heading")
    assert paragraph_line.startswith("Paragraph")
