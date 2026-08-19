"""Application, editor, and terminal palettes for nbcli."""

from __future__ import annotations

from rich.style import Style
from rich.terminal_theme import TerminalTheme
from textual._text_area_theme import TextAreaTheme
from textual.theme import Theme

from .terminal import VSCODE_DARK_TERMINAL_THEME


THEME_NAMES = (
    "default",
    "vscode-dark",
    "vscode-light",
    "databricks-light",
    "snowflake",
)


APP_THEMES = {
    "default": Theme(
        name="default",
        primary="#0178D4",
        secondary="#004578",
        accent="#FFA62B",
        warning="#FFA62B",
        error="#BA3C5B",
        success="#4EBF71",
        foreground="#E0E0E0",
        dark=True,
        variables={
            "terminal-background": "#181818",
            "terminal-foreground": "#CCCCCC",
            "status-background": "#004578",
            "status-foreground": "#FFFFFF",
        },
    ),
    "vscode-dark": Theme(
        name="vscode-dark",
        primary="#0078D4",
        secondary="#0E639C",
        accent="#007ACC",
        warning="#CCA700",
        error="#F14C4C",
        success="#89D185",
        foreground="#CCCCCC",
        background="#181818",
        surface="#1F1F1F",
        panel="#252526",
        dark=True,
        luminosity_spread=0.08,
        variables={
            "border": "#3C3C3C",
            "border-blurred": "#2B2B2B",
            "input-selection-background": "#264F78",
            "block-cursor-background": "#AEAFAD",
            "block-cursor-foreground": "#181818",
            "footer-background": "#181818",
            "terminal-background": "#181818",
            "terminal-foreground": "#CCCCCC",
            "status-background": "#007ACC",
            "status-foreground": "#FFFFFF",
        },
    ),
    "vscode-light": Theme(
        name="vscode-light",
        primary="#005FB8",
        secondary="#0078D4",
        accent="#005FB8",
        warning="#BF8803",
        error="#A1260D",
        success="#388A34",
        foreground="#3B3B3B",
        background="#FFFFFF",
        surface="#F3F3F3",
        panel="#F8F8F8",
        dark=False,
        luminosity_spread=0.06,
        variables={
            "border": "#D4D4D4",
            "border-blurred": "#E5E5E5",
            "input-selection-background": "#ADD6FF",
            "block-cursor-background": "#000000",
            "block-cursor-foreground": "#FFFFFF",
            "footer-background": "#F3F3F3",
            "terminal-background": "#FFFFFF",
            "terminal-foreground": "#333333",
            "status-background": "#005FB8",
            "status-foreground": "#FFFFFF",
        },
    ),
    "databricks-light": Theme(
        name="databricks-light",
        primary="#FF3621",
        secondary="#1B3139",
        accent="#2272B4",
        warning="#FFAB00",
        error="#C82D22",
        success="#00875A",
        foreground="#1B3139",
        background="#F7F7F7",
        surface="#FFFFFF",
        panel="#F2F5F7",
        dark=False,
        luminosity_spread=0.05,
        variables={
            "border": "#DCE0E2",
            "border-blurred": "#E8EAEB",
            "input-selection-background": "#CFE8FA",
            "block-cursor-background": "#2272B4",
            "block-cursor-foreground": "#FFFFFF",
            "footer-background": "#1B3139",
            "footer-foreground": "#FFFFFF",
            "terminal-background": "#FFFFFF",
            "terminal-foreground": "#1B3139",
            "status-background": "#1B3139",
            "status-foreground": "#FFFFFF",
        },
    ),
    "snowflake": Theme(
        name="snowflake",
        primary="#29B5E8",
        secondary="#7D44CF",
        accent="#11567F",
        warning="#E9A23B",
        error="#D64545",
        success="#168A72",
        foreground="#172B4D",
        background="#F7FAFC",
        surface="#FFFFFF",
        panel="#EDF6FA",
        dark=False,
        luminosity_spread=0.05,
        variables={
            "border": "#D8E5EC",
            "border-blurred": "#E7F0F4",
            "input-selection-background": "#CDEFFA",
            "block-cursor-background": "#11567F",
            "block-cursor-foreground": "#FFFFFF",
            "footer-background": "#0F2E3D",
            "footer-foreground": "#FFFFFF",
            "terminal-background": "#FCFEFF",
            "terminal-foreground": "#172B4D",
            "status-background": "#0F2E3D",
            "status-foreground": "#FFFFFF",
        },
    ),
}


def _editor_theme(
    name: str,
    *,
    background: str,
    foreground: str,
    gutter: str,
    active_line: str,
    selection: str,
    cursor: str,
    comment: str,
    keyword: str,
    string: str,
    number: str,
    function: str,
    type_color: str,
) -> TextAreaTheme:
    return TextAreaTheme(
        name=name,
        base_style=Style(color=foreground, bgcolor=background),
        gutter_style=Style(color=gutter, bgcolor=background),
        cursor_style=Style(color=background, bgcolor=cursor),
        cursor_line_style=Style(bgcolor=active_line),
        cursor_line_gutter_style=Style(color=foreground, bgcolor=active_line),
        bracket_matching_style=Style(bgcolor=selection, bold=True),
        selection_style=Style(bgcolor=selection),
        syntax_styles={
            "comment": Style(color=comment),
            "string": Style(color=string),
            "string.documentation": Style(color=string),
            "keyword": Style(color=keyword),
            "keyword.function": Style(color=keyword),
            "keyword.return": Style(color=keyword),
            "keyword.operator": Style(color=keyword),
            "conditional": Style(color=keyword),
            "repeat": Style(color=keyword),
            "exception": Style(color=keyword),
            "include": Style(color=keyword),
            "operator": Style(color=foreground),
            "number": Style(color=number),
            "float": Style(color=number),
            "boolean": Style(color=keyword),
            "constant.builtin": Style(color=keyword),
            "class": Style(color=type_color),
            "type": Style(color=type_color),
            "type.class": Style(color=type_color),
            "type.builtin": Style(color=type_color),
            "function": Style(color=function),
            "function.call": Style(color=function),
            "method": Style(color=function),
            "method.call": Style(color=function),
            "variable.builtin": Style(color=type_color),
            "heading": Style(color=keyword, bold=True),
            "heading.marker": Style(color=gutter),
            "tag": Style(color=keyword),
            "json.label": Style(color=function),
            "yaml.field": Style(color=function),
        },
    )


EDITOR_THEMES = {
    "vscode-light": _editor_theme(
        "nbcli-vscode-light",
        background="#FFFFFF", foreground="#3B3B3B", gutter="#237893",
        active_line="#F5F5F5", selection="#ADD6FF", cursor="#000000",
        comment="#008000", keyword="#0000FF", string="#A31515",
        number="#098658", function="#795E26", type_color="#267F99",
    ),
    "databricks-light": _editor_theme(
        "nbcli-databricks-light",
        background="#FFFFFF", foreground="#1B3139", gutter="#6B7780",
        active_line="#F5F7F8", selection="#CFE8FA", cursor="#2272B4",
        comment="#587246", keyword="#9C2B80", string="#A31515",
        number="#1750A5", function="#7A3E9D", type_color="#006D77",
    ),
    "snowflake": _editor_theme(
        "nbcli-snowflake",
        background="#FCFEFF", foreground="#172B4D", gutter="#78909C",
        active_line="#F0F8FB", selection="#CDEFFA", cursor="#11567F",
        comment="#5C7A82", keyword="#6F42C1", string="#087F5B",
        number="#0B6FA4", function="#9C4A1A", type_color="#006D8F",
    ),
}


EDITOR_THEME_NAMES = {
    "default": "monokai",
    "vscode-dark": "vscode_dark",
    "vscode-light": "nbcli-vscode-light",
    "databricks-light": "nbcli-databricks-light",
    "snowflake": "nbcli-snowflake",
}


RICH_SYNTAX_THEMES = {
    "default": "ansi_dark",
    "vscode-dark": "github-dark",
    "vscode-light": "vs",
    "databricks-light": "friendly",
    "snowflake": "xcode",
}


def _terminal(background: tuple[int, int, int], foreground: tuple[int, int, int]) -> TerminalTheme:
    return TerminalTheme(
        background=background,
        foreground=foreground,
        normal=[
            (0, 0, 0), (205, 49, 49), (13, 188, 121), (181, 137, 0),
            (36, 114, 200), (188, 63, 188), (17, 145, 175), (210, 210, 210),
        ],
        bright=[
            (102, 102, 102), (241, 76, 76), (35, 209, 139), (193, 156, 0),
            (59, 142, 234), (170, 75, 190), (41, 184, 219), (245, 245, 245),
        ],
    )


TERMINAL_THEMES = {
    "default": VSCODE_DARK_TERMINAL_THEME,
    "vscode-dark": VSCODE_DARK_TERMINAL_THEME,
    "vscode-light": _terminal((255, 255, 255), (51, 51, 51)),
    "databricks-light": _terminal((255, 255, 255), (27, 49, 57)),
    "snowflake": _terminal((252, 254, 255), (23, 43, 77)),
}
