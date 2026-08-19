"""Application, editor, and terminal palettes for notebookvim."""

from __future__ import annotations

from rich.style import Style
from rich.syntax import PygmentsSyntaxTheme
from rich.terminal_theme import TerminalTheme
from pygments.style import Style as PygmentsStyle
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, Text
from textual._text_area_theme import TextAreaTheme
from textual.theme import Theme

from .terminal import VSCODE_DARK_TERMINAL_THEME


THEME_NAMES = (
    "default",
    "vscode-dark",
    "vscode-light",
    "databricks-light",
    "databricks-dark",
    "snowflake-light",
    "snowflake-dark",
)


THEME_FONTS = {
    "default": "your terminal profile font",
    "vscode-dark": "Menlo (macOS) / Consolas (Windows) / Droid Sans Mono (Linux)",
    "vscode-light": "Menlo (macOS) / Consolas (Windows) / Droid Sans Mono (Linux)",
    "databricks-light": "DM Mono",
    "databricks-dark": "DM Mono",
    "snowflake-light": "JetBrains Mono or Apercu Mono",
    "snowflake-dark": "JetBrains Mono or Apercu Mono",
}


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
    "databricks-dark": Theme(
        name="databricks-dark",
        primary="#FF3621",
        secondary="#8BD3E6",
        accent="#5BA7D1",
        warning="#FFB84D",
        error="#FF6B5B",
        success="#52C7A5",
        foreground="#F9F7F4",
        background="#08191F",
        surface="#0B2026",
        panel="#16343D",
        dark=True,
        luminosity_spread=0.06,
        variables={
            "border": "#2A4A53",
            "border-blurred": "#1D3942",
            "input-selection-background": "#214E60",
            "block-cursor-background": "#FF7B6B",
            "block-cursor-foreground": "#08191F",
            "footer-background": "#08191F",
            "footer-foreground": "#F9F7F4",
            "terminal-background": "#08191F",
            "terminal-foreground": "#E8EFED",
            "status-background": "#08191F",
            "status-foreground": "#F9F7F4",
        },
    ),
    "snowflake-light": Theme(
        name="snowflake-light",
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
    "snowflake-dark": Theme(
        name="snowflake-dark",
        primary="#29B5E8",
        secondary="#9B7AD7",
        accent="#56C7EE",
        warning="#F0B45A",
        error="#FF6B6B",
        success="#50C9A7",
        foreground="#D9EDF4",
        background="#0B1720",
        surface="#10242F",
        panel="#153541",
        dark=True,
        luminosity_spread=0.06,
        variables={
            "border": "#244957",
            "border-blurred": "#193642",
            "input-selection-background": "#1C5267",
            "block-cursor-background": "#29B5E8",
            "block-cursor-foreground": "#071219",
            "footer-background": "#071219",
            "footer-foreground": "#D9EDF4",
            "terminal-background": "#071219",
            "terminal-foreground": "#D9EDF4",
            "status-background": "#071219",
            "status-foreground": "#D9EDF4",
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
    variable: str,
    field: str,
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
            "string.escape": Style(color=keyword, bold=True),
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
            "constant": Style(color=number),
            "none": Style(color=keyword),
            "class": Style(color=type_color),
            "type": Style(color=type_color),
            "type.class": Style(color=type_color),
            "type.builtin": Style(color=type_color),
            "type.definition": Style(color=type_color),
            "type.qualifier": Style(color=type_color),
            "constructor": Style(color=type_color),
            "function": Style(color=function),
            "function.call": Style(color=function),
            "method": Style(color=function),
            "method.call": Style(color=function),
            "variable.builtin": Style(color=type_color),
            "variable": Style(color=variable),
            "parameter": Style(color=variable),
            "field": Style(color=field),
            "attribute": Style(color=field),
            "attribute.builtin": Style(color=type_color),
            "function.builtin": Style(color=function),
            "storageclass": Style(color=keyword),
            "preproc": Style(color=keyword),
            "punctuation.bracket": Style(color=foreground),
            "punctuation.delimiter": Style(color=foreground),
            "punctuation.special": Style(color=keyword),
            "error": Style(color="#F14C4C", underline=True),
            "heading": Style(color=keyword, bold=True),
            "heading.marker": Style(color=gutter),
            "tag": Style(color=keyword),
            "json.label": Style(color=function),
            "yaml.field": Style(color=function),
        },
    )


EDITOR_THEMES = {
    "vscode-dark": _editor_theme(
        "notebookvim-vscode-dark",
        background="#1F1F1F", foreground="#D4D4D4", gutter="#858585",
        active_line="#2A2D2E", selection="#264F78", cursor="#AEAFAD",
        comment="#6A9955", keyword="#C586C0", string="#CE9178",
        number="#B5CEA8", function="#DCDCAA", type_color="#4EC9B0",
        variable="#9CDCFE", field="#9CDCFE",
    ),
    "vscode-light": _editor_theme(
        "notebookvim-vscode-light",
        background="#FFFFFF", foreground="#3B3B3B", gutter="#237893",
        active_line="#F5F5F5", selection="#ADD6FF", cursor="#000000",
        comment="#008000", keyword="#0000FF", string="#A31515",
        number="#098658", function="#795E26", type_color="#267F99",
        variable="#001080", field="#001080",
    ),
    "databricks-light": _editor_theme(
        "notebookvim-databricks-light",
        background="#FFFFFF", foreground="#1B3139", gutter="#6B7780",
        active_line="#F5F7F8", selection="#CFE8FA", cursor="#2272B4",
        comment="#587246", keyword="#9C2B80", string="#A31515",
        number="#1750A5", function="#7A3E9D", type_color="#006D77",
        variable="#1B3139", field="#2272B4",
    ),
    "databricks-dark": _editor_theme(
        "notebookvim-databricks-dark",
        background="#0B2026", foreground="#E8EFED", gutter="#769098",
        active_line="#14313A", selection="#214E60", cursor="#FF7B6B",
        comment="#8AA29D", keyword="#FF7B6B", string="#A7D8A0",
        number="#8BC8FF", function="#D6B4FC", type_color="#72D6C9",
        variable="#E8EFED", field="#8BC8FF",
    ),
    "snowflake-light": _editor_theme(
        "notebookvim-snowflake-light",
        background="#FCFEFF", foreground="#172B4D", gutter="#78909C",
        active_line="#F0F8FB", selection="#CDEFFA", cursor="#11567F",
        comment="#5C7A82", keyword="#6F42C1", string="#087F5B",
        number="#0B6FA4", function="#9C4A1A", type_color="#006D8F",
        variable="#172B4D", field="#0B6FA4",
    ),
    "snowflake-dark": _editor_theme(
        "notebookvim-snowflake-dark",
        background="#0D1F29", foreground="#D9EDF4", gutter="#698692",
        active_line="#132C38", selection="#1C5267", cursor="#29B5E8",
        comment="#7097A3", keyword="#C792EA", string="#A8D8A0",
        number="#82CCEB", function="#FFD580", type_color="#56D4DD",
        variable="#D9EDF4", field="#82CCEB",
    ),
}


EDITOR_THEME_NAMES = {
    "default": "monokai",
    "vscode-dark": "notebookvim-vscode-dark",
    "vscode-light": "notebookvim-vscode-light",
    "databricks-light": "notebookvim-databricks-light",
    "databricks-dark": "notebookvim-databricks-dark",
    "snowflake-light": "notebookvim-snowflake-light",
    "snowflake-dark": "notebookvim-snowflake-dark",
}


def _rich_syntax_theme(
    *, background: str, foreground: str, comment: str, keyword: str,
    string: str, number: str, function: str, type_color: str, variable: str,
) -> PygmentsSyntaxTheme:
    class Palette(PygmentsStyle):
        background_color = background
        default_style = ""
        styles = {
            Text: foreground,
            Comment: f"italic {comment}",
            Keyword: keyword,
            Keyword.Type: type_color,
            String: string,
            String.Escape: f"bold {keyword}",
            Number: number,
            Name: foreground,
            Name.Function: function,
            Name.Class: type_color,
            Name.Builtin: type_color,
            Name.Variable: variable,
            Name.Attribute: variable,
            Name.Constant: number,
            Operator: foreground,
            Punctuation: foreground,
        }

    return PygmentsSyntaxTheme(Palette)


RICH_SYNTAX_THEMES = {
    "default": "ansi_dark",
    "vscode-dark": _rich_syntax_theme(
        background="#1F1F1F", foreground="#D4D4D4", comment="#6A9955",
        keyword="#C586C0", string="#CE9178", number="#B5CEA8",
        function="#DCDCAA", type_color="#4EC9B0", variable="#9CDCFE",
    ),
    "vscode-light": _rich_syntax_theme(
        background="#FFFFFF", foreground="#3B3B3B", comment="#008000",
        keyword="#0000FF", string="#A31515", number="#098658",
        function="#795E26", type_color="#267F99", variable="#001080",
    ),
    "databricks-light": _rich_syntax_theme(
        background="#FFFFFF", foreground="#1B3139", comment="#587246",
        keyword="#9C2B80", string="#A31515", number="#1750A5",
        function="#7A3E9D", type_color="#006D77", variable="#1B3139",
    ),
    "databricks-dark": _rich_syntax_theme(
        background="#0B2026", foreground="#E8EFED", comment="#8AA29D",
        keyword="#FF7B6B", string="#A7D8A0", number="#8BC8FF",
        function="#D6B4FC", type_color="#72D6C9", variable="#E8EFED",
    ),
    "snowflake-light": _rich_syntax_theme(
        background="#FCFEFF", foreground="#172B4D", comment="#5C7A82",
        keyword="#6F42C1", string="#087F5B", number="#0B6FA4",
        function="#9C4A1A", type_color="#006D8F", variable="#172B4D",
    ),
    "snowflake-dark": _rich_syntax_theme(
        background="#0D1F29", foreground="#D9EDF4", comment="#7097A3",
        keyword="#C792EA", string="#A8D8A0", number="#82CCEB",
        function="#FFD580", type_color="#56D4DD", variable="#D9EDF4",
    ),
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
    "databricks-dark": _terminal((8, 25, 31), (232, 239, 237)),
    "snowflake-light": _terminal((252, 254, 255), (23, 43, 77)),
    "snowflake-dark": _terminal((7, 18, 25), (217, 237, 244)),
}
