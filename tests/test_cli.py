import subprocess
import sys

from typer.testing import CliRunner

from notebookvim import cli


def test_new_and_info_commands(tmp_path):
    path = tmp_path / "cli.ipynb"
    created = subprocess.run(
        [sys.executable, "-m", "notebookvim", "new", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = subprocess.run(
        [sys.executable, "-m", "notebookvim", "info", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Created" in created.stdout
    assert "Kernel: python3" in inspected.stdout
    assert "Cells: 1 (1 code)" in inspected.stdout


def test_workspace_paths_are_routed_to_open_command(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "run_workspace", lambda path: opened.append(path))

    result = CliRunner().invoke(cli.app, ["open", str(tmp_path)])

    assert result.exit_code == 0
    assert opened == [tmp_path]
    assert cli._normalized_cli_args([]) == ["open"]
    assert cli._normalized_cli_args(["."]) == ["open", "."]


def test_no_argument_launches_an_empty_project(monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "run_empty_workspace", lambda: opened.append(True))

    result = CliRunner().invoke(cli.app, ["open"])

    assert result.exit_code == 0
    assert opened == [True]


def test_text_file_path_opens_inside_its_workspace(tmp_path, monkeypatch):
    path = tmp_path / "example.py"
    path.write_text("print('hello')\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr(
        cli,
        "run_workspace",
        lambda root, initial_path=None: opened.append((root, initial_path)),
    )

    result = CliRunner().invoke(cli.app, ["open", str(path)])

    assert result.exit_code == 0
    assert opened == [(tmp_path, path)]
