from pathlib import Path

import pytest

from nbcli.workspace import (
    is_parquet_file,
    load_parquet_preview,
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


def test_parquet_extensions_are_recognized():
    assert is_parquet_file(Path("data.parquet"))
    assert is_parquet_file(Path("data.PQ"))
    assert not is_parquet_file(Path("data.csv"))


def test_parquet_preview_explains_html_downloads(tmp_path):
    path = tmp_path / "sample.parquet"
    path.write_text("<!DOCTYPE html><title>GitHub</title>", encoding="utf-8")

    with pytest.raises(ValueError, match="HTML page.*Raw file"):
        load_parquet_preview(path)


def test_parquet_preview_includes_spark_style_statistics(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "sample.parquet"
    pq.write_table(
        pa.table(
            {
                "value": [1, 2, 3, None],
                "label": ["beta", "alpha", None, "gamma"],
            }
        ),
        path,
    )

    preview = load_parquet_preview(path)

    assert preview.statistics_columns == ["value", "label"]
    statistics = {row[0]: row[1:] for row in preview.statistics_rows}
    assert statistics["count"] == [3, 3]
    assert statistics["mean"] == [2.0, None]
    assert statistics["stddev"][0] == pytest.approx(1.0)
    assert statistics["stddev"][1] is None
    assert statistics["min"] == [1, "alpha"]
    assert statistics["max"] == [3, "gamma"]
