from nbcli.terminal import VSCODE_DARK_TERMINAL_THEME, terminal_text


def test_terminal_text_preserves_ansi_colors_and_removes_title_sequence():
    rendered = terminal_text("\x1b]0;secret title\x07\x1b[31mred\x1b[0m")

    assert rendered.plain == "red"
    assert rendered.spans


def test_vscode_terminal_palette_has_expected_defaults():
    assert tuple(VSCODE_DARK_TERMINAL_THEME.background_color) == (24, 24, 24)
    assert tuple(VSCODE_DARK_TERMINAL_THEME.foreground_color) == (204, 204, 204)
    assert VSCODE_DARK_TERMINAL_THEME.ansi_colors[1] == (205, 49, 49)
    assert VSCODE_DARK_TERMINAL_THEME.ansi_colors[15] == (229, 229, 229)
