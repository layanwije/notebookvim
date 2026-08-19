from notebookcli.preferences import (
    load_ai_provider,
    load_ai_model,
    load_theme,
    preferences_path,
    save_ai_provider,
    save_theme,
)


def test_theme_preference_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("NBCLI_CONFIG_HOME", str(tmp_path))
    save_theme("snowflake-dark")

    assert load_theme() == "snowflake-dark"
    assert preferences_path().read_text(encoding="utf-8") == '{\n  "theme": "snowflake-dark"\n}\n'


def test_missing_or_invalid_preferences_use_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NBCLI_CONFIG_HOME", str(tmp_path))
    assert load_theme() == "databricks-dark"

    preferences_path().write_text("not json", encoding="utf-8")
    assert load_theme() == "databricks-dark"


def test_old_snowflake_name_migrates_to_light(tmp_path, monkeypatch):
    monkeypatch.setenv("NBCLI_CONFIG_HOME", str(tmp_path))
    preferences_path().write_text('{"theme": "snowflake"}', encoding="utf-8")
    assert load_theme() == "snowflake-light"


def test_ai_provider_round_trip_preserves_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("NBCLI_CONFIG_HOME", str(tmp_path))
    save_theme("vscode-dark")
    save_ai_provider("ollama", "qwen2.5-coder:7b")

    assert load_theme() == "vscode-dark"
    assert load_ai_provider() == "ollama"
    assert load_ai_model() == "qwen2.5-coder:7b"
