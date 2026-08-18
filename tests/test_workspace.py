import pytest

from nbcli.workspace import (
    load_text_buffer,
    notebook_files,
    project_files,
    save_text_buffer,
)


def test_project_files_are_sorted_and_ignore_generated_directories(tmp_path):
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "analysis.ipynb").write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("", encoding="utf-8")
    (tmp_path / ".hidden").write_text("", encoding="utf-8")

    relative = [path.relative_to(tmp_path) for path in project_files(tmp_path)]

    assert relative == [tmp_path.joinpath("notebooks/analysis.ipynb").relative_to(tmp_path),
                        tmp_path.joinpath("README.md").relative_to(tmp_path)]
    assert notebook_files(tmp_path) == [tmp_path / "notebooks" / "analysis.ipynb"]


def test_text_buffer_loads_utf8_and_saves_atomically(tmp_path):
    path = tmp_path / "example.py"
    path.write_text("value = 1\n", encoding="utf-8")

    buffer = load_text_buffer(path)
    buffer.text = "value = 2\n"
    buffer.dirty = True
    save_text_buffer(buffer)

    assert buffer.language == "python"
    assert buffer.dirty is False
    assert path.read_text(encoding="utf-8") == "value = 2\n"


def test_text_buffer_rejects_binary_files(tmp_path):
    path = tmp_path / "image.txt"
    path.write_bytes(b"text\0binary")

    with pytest.raises(ValueError, match="binary"):
        load_text_buffer(path)
