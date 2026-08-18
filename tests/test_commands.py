from nbcli.commands import COMMAND_SUGGESTIONS, normalize_command


def test_command_aliases_are_normalized():
    assert normalize_command(":w") == "notebook save"
    assert normalize_command("  :output   clear ") == "cell output clear"
    assert normalize_command(":run all") == "notebook run all"
    assert normalize_command(":cell markdown") == "cell type markdown"
    assert normalize_command(":wq") == "write quit"
    assert normalize_command(":run cell 2") == "cell run 2"
    assert normalize_command(":cell run 12") == "cell run 12"


def test_completion_catalog_contains_full_commands_and_aliases():
    assert "cell output clear" in COMMAND_SUGGESTIONS
    assert "kernel restart" in COMMAND_SUGGESTIONS
    assert "wq" in COMMAND_SUGGESTIONS
    assert "run cell 1" in COMMAND_SUGGESTIONS
