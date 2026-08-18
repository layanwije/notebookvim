import json

import nbformat

from nbcli.model import CellType, DisplayOutput, StreamOutput
from nbcli.storage import load_notebook, new_notebook, save_notebook, to_node


def test_round_trip_preserves_unknown_metadata_and_outputs(tmp_path):
    path = tmp_path / "sample.ipynb"
    original = {
        "cells": [{
            "cell_type": "code",
            "execution_count": 3,
            "id": "abc12345",
            "metadata": {"vscode": {"languageId": "python"}},
            "outputs": [{
                "output_type": "execute_result",
                "execution_count": 3,
                "data": {"text/plain": ["42"], "application/x-custom": "opaque"},
                "metadata": {"needs_background": "light"},
            }],
            "source": ["x = 40\n", "x + 2"],
        }],
        "metadata": {"kernelspec": {
            "name": "python3", "display_name": "Python 3", "language": "python"
        }, "vendor": {"keep": True}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    notebook = load_notebook(path)
    save_notebook(notebook)
    result = json.loads(path.read_text(encoding="utf-8"))

    assert result["metadata"]["vendor"] == {"keep": True}
    assert result["cells"][0]["metadata"]["vscode"]["languageId"] == "python"
    assert result["cells"][0]["outputs"][0]["data"]["application/x-custom"] == "opaque"
    source = result["cells"][0]["source"]
    normalized_source = "".join(source) if isinstance(source, list) else source
    assert normalized_source == "x = 40\nx + 2"


def test_new_notebook_is_valid_and_atomic_save_clears_dirty(tmp_path):
    path = tmp_path / "new.ipynb"
    notebook = new_notebook(path)
    notebook.dirty = True

    save_notebook(notebook)

    assert path.exists()
    assert notebook.dirty is False
    loaded = nbformat.read(path, as_version=4)
    nbformat.validate(loaded)
    assert loaded.cells[0].cell_type == "code"


def test_internal_model_is_independent_of_nbformat_nodes(tmp_path):
    path = tmp_path / "new.ipynb"
    notebook = new_notebook(path)
    notebook.cells[0].source = "print('hello')"
    notebook.cells[0].outputs = [StreamOutput(output_type="stream", name="stdout", text="hello\n")]

    node = to_node(notebook)

    assert notebook.cells[0].cell_type is CellType.CODE
    assert node.cells[0].outputs[0].text == "hello\n"
