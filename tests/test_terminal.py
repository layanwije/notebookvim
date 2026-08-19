import os
from pathlib import Path

from notebookvim.terminal import TerminalPane, VSCODE_DARK_TERMINAL_THEME, terminal_text


def test_terminal_text_preserves_ansi_colors_and_removes_title_sequence():
    rendered = terminal_text("\x1b]0;secret title\x07\x1b[31mred\x1b[0m")

    assert rendered.plain == "red"
    assert rendered.spans


def test_vscode_terminal_palette_has_expected_defaults():
    assert tuple(VSCODE_DARK_TERMINAL_THEME.background_color) == (24, 24, 24)
    assert tuple(VSCODE_DARK_TERMINAL_THEME.foreground_color) == (204, 204, 204)
    assert VSCODE_DARK_TERMINAL_THEME.ansi_colors[1] == (205, 49, 49)
    assert VSCODE_DARK_TERMINAL_THEME.ansi_colors[15] == (229, 229, 229)


def test_running_process_input_is_forwarded_to_pty():
    read_fd, write_fd = os.pipe()
    pane = TerminalPane(Path.cwd())
    pane.master_fd = write_fd
    pane.process = object()  # type: ignore[assignment]
    try:
        assert pane.send_input("yes\n") is True
        assert os.read(read_fd, 4) == b"yes\n"
    finally:
        os.close(read_fd)
        os.close(write_fd)
