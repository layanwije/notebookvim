from nbcli.commands import COMMAND_SUGGESTIONS, normalize_command


def test_command_aliases_are_normalized():
    assert normalize_command(":w") == "notebook save"
    assert normalize_command("  :output   clear ") == "cell output clear"
    assert normalize_command(":run all") == "notebook run all"
    assert normalize_command(":cell markdown") == "cell type markdown"
    assert normalize_command(":q") == "tab close"
    assert normalize_command(":quit") == "tab close"
    assert normalize_command(":wq") == "write close"
    assert normalize_command(":exit") == "exit"
    assert normalize_command(":run cell 2") == "cell run 2"
    assert normalize_command(":cell run 12") == "cell run 12"
    assert normalize_command(":file open Reports/My File.py") == "file open Reports/My File.py"
    assert normalize_command(":tab open Reports/My File.py") == "tab open Reports/My File.py"
    assert normalize_command(":databricks connect MyProfile") == "databricks connect MyProfile"
    assert normalize_command(":git profile use Work") == "git profile use Work"
    assert normalize_command(
        ':git profile add Work github octocat octo@example.com "Octo Cat"'
    ) == 'git profile add Work github octocat octo@example.com "Octo Cat"'


def test_completion_catalog_contains_full_commands_and_aliases():
    assert "cell output clear" in COMMAND_SUGGESTIONS
    assert "kernel restart" in COMMAND_SUGGESTIONS
    assert "wq" in COMMAND_SUGGESTIONS
    assert "exit" in COMMAND_SUGGESTIONS
    assert "run cell 1" in COMMAND_SUGGESTIONS
    assert "terminal open" in COMMAND_SUGGESTIONS
    assert "terminal close" in COMMAND_SUGGESTIONS
    assert "terminal open side" in COMMAND_SUGGESTIONS
    assert "terminal open below" in COMMAND_SUGGESTIONS
    assert "databricks connect" in COMMAND_SUGGESTIONS
    assert "databricks status" in COMMAND_SUGGESTIONS
    assert "git profile add" in COMMAND_SUGGESTIONS
    assert "git status" in COMMAND_SUGGESTIONS
    assert "git push" in COMMAND_SUGGESTIONS
    assert "databricks sync set" in COMMAND_SUGGESTIONS
    assert "databricks sync diff" in COMMAND_SUGGESTIONS
    assert "databricks jobs running" in COMMAND_SUGGESTIONS
    assert "inspect parquet describe" in COMMAND_SUGGESTIONS
    assert "inspect delta time travel" in COMMAND_SUGGESTIONS
    assert "theme default" in COMMAND_SUGGESTIONS
    assert "theme vscode-dark" in COMMAND_SUGGESTIONS
    assert "theme databricks-light" in COMMAND_SUGGESTIONS
    assert "theme databricks-dark" in COMMAND_SUGGESTIONS
    assert "theme snowflake-light" in COMMAND_SUGGESTIONS
    assert "theme snowflake-dark" in COMMAND_SUGGESTIONS
    assert "file open" in COMMAND_SUGGESTIONS


def test_remote_command_arguments_preserve_case():
    assert normalize_command(":databricks sync set /Workspace/Users/Me/Analysis") == (
        "databricks sync set /Workspace/Users/Me/Analysis"
    )
    assert normalize_command(":databricks run 12 --param Date=2026-08-19") == (
        "databricks run 12 --param Date=2026-08-19"
    )
