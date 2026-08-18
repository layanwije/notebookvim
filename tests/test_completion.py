from pathlib import Path

from nbcli.completion import python_completions


def test_python_completions_are_local_and_include_standard_library_names():
    suggestions = python_completions("pri", Path("example.py"), 0, 3)

    assert "print" in suggestions


def test_python_completions_tolerate_incomplete_cells():
    assert isinstance(python_completions("def broken(", Path("example.ipynb"), 0, 11), list)
