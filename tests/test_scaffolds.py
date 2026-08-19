from pathlib import Path

from notebookvim.scaffolds import DATA_ENGINEERING_FILES, init_data_engineering_scaffold


def test_data_engineering_scaffold_creates_expected_files(tmp_path):
    result = init_data_engineering_scaffold(tmp_path)

    assert {path.relative_to(tmp_path) for path in result.created} == {
        Path(name) for name in DATA_ENGINEERING_FILES
    }
    assert not result.skipped
    assert (tmp_path / "notebooks" / "bronze" / "ingest.py").read_text().startswith(
        "# Databricks notebook source"
    )


def test_data_engineering_scaffold_never_overwrites_existing_files(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("keep me\n", encoding="utf-8")

    result = init_data_engineering_scaffold(tmp_path)

    assert readme.read_text(encoding="utf-8") == "keep me\n"
    assert readme in result.skipped
