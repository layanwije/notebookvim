from nbcli.themes import (
    APP_THEMES,
    EDITOR_THEMES,
    EDITOR_THEME_NAMES,
    TERMINAL_THEMES,
    THEME_FONTS,
    THEME_NAMES,
)


def _rgb(style):
    assert style is not None and style.color is not None
    return tuple(style.color.triplet)


def test_theme_catalogs_and_font_recommendations_stay_in_sync():
    names = set(THEME_NAMES)
    assert names == set(APP_THEMES)
    assert names == set(EDITOR_THEME_NAMES)
    assert names == set(TERMINAL_THEMES)
    assert names == set(THEME_FONTS)
    assert "snowflake-light" in names
    assert "snowflake-dark" in names
    assert "databricks-dark" in names
    assert "snowflake" not in names
    assert APP_THEMES["snowflake-dark"].dark
    assert not APP_THEMES["snowflake-light"].dark
    assert APP_THEMES["databricks-dark"].dark


def test_python_and_sql_capture_colors_follow_named_editor_themes():
    vscode = EDITOR_THEMES["vscode-dark"]
    assert _rgb(vscode.get_highlight("keyword")) == (197, 134, 192)
    assert _rgb(vscode.get_highlight("string")) == (206, 145, 120)
    assert _rgb(vscode.get_highlight("function.call")) == (220, 220, 170)
    assert _rgb(vscode.get_highlight("field")) == (156, 220, 254)

    snowflake = EDITOR_THEMES["snowflake-dark"]
    assert _rgb(snowflake.get_highlight("keyword")) == (199, 146, 234)
    assert _rgb(snowflake.get_highlight("number")) == (130, 204, 235)
    assert _rgb(snowflake.get_highlight("function.call")) == (255, 213, 128)

    databricks = EDITOR_THEMES["databricks-dark"]
    assert _rgb(databricks.get_highlight("keyword")) == (255, 123, 107)
    assert _rgb(databricks.get_highlight("string")) == (167, 216, 160)
    assert _rgb(databricks.get_highlight("field")) == (139, 200, 255)
