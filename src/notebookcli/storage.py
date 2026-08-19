from __future__ import annotations

import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

import nbformat
from nbformat import NotebookNode

from .model import Cell, CellType, DisplayOutput, ErrorOutput, Notebook, Output, StreamOutput


_NOTEBOOK_KEYS = {"cells", "metadata", "nbformat", "nbformat_minor"}
_CELL_KEYS = {"cell_type", "source", "metadata", "id", "execution_count", "outputs"}


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return deepcopy(value)


def output_from_node(node: NotebookNode) -> Output:
    raw = _plain(node)
    output_type = str(raw.pop("output_type"))
    metadata = raw.pop("metadata", {})
    if output_type == "stream":
        return StreamOutput(output_type=output_type, metadata=metadata,
                            name=raw.pop("name", "stdout"), text=raw.pop("text", ""), extra=raw)
    if output_type in {"display_data", "execute_result"}:
        return DisplayOutput(output_type=output_type, metadata=metadata,
                             data=raw.pop("data", {}),
                             execution_count=raw.pop("execution_count", None), extra=raw)
    if output_type == "error":
        return ErrorOutput(output_type=output_type, metadata=metadata,
                           ename=raw.pop("ename", "Error"), evalue=raw.pop("evalue", ""),
                           traceback=raw.pop("traceback", []), extra=raw)
    return Output(output_type=output_type, metadata=metadata, extra=raw)


def output_to_node(output: Output) -> NotebookNode:
    raw: Dict[str, Any] = deepcopy(output.extra)
    raw["output_type"] = output.output_type
    if output.metadata or output.output_type in {"display_data", "execute_result"}:
        raw["metadata"] = deepcopy(output.metadata)
    if isinstance(output, StreamOutput):
        raw.update(name=output.name, text=output.text)
    elif isinstance(output, DisplayOutput):
        raw["data"] = deepcopy(output.data)
        if output.output_type == "execute_result":
            raw["execution_count"] = output.execution_count
    elif isinstance(output, ErrorOutput):
        raw.update(ename=output.ename, evalue=output.evalue, traceback=list(output.traceback))
    return nbformat.from_dict(raw)


def load_notebook(path: Path) -> Notebook:
    path = Path(path)
    node = nbformat.read(path, as_version=4)
    cells = []
    for raw_node in node.cells:
        raw = _plain(raw_node)
        cell_type = CellType(raw.pop("cell_type"))
        source = raw.pop("source", "")
        metadata = raw.pop("metadata", {})
        cell_id = raw.pop("id", None)
        execution_count = raw.pop("execution_count", None)
        outputs = [output_from_node(item) for item in raw.pop("outputs", [])]
        cells.append(Cell(cell_type=cell_type, source=source, metadata=metadata,
                          cell_id=cell_id, execution_count=execution_count,
                          outputs=outputs, extra=raw))
    top = _plain(node)
    extra = {key: value for key, value in top.items() if key not in _NOTEBOOK_KEYS}
    return Notebook(path=path, cells=cells, metadata=_plain(node.metadata),
                    nbformat=node.nbformat, nbformat_minor=node.nbformat_minor, extra=extra)


def to_node(notebook: Notebook) -> NotebookNode:
    raw: Dict[str, Any] = deepcopy(notebook.extra)
    raw.update(metadata=deepcopy(notebook.metadata), nbformat=notebook.nbformat,
               nbformat_minor=notebook.nbformat_minor, cells=[])
    for cell in notebook.cells:
        item = deepcopy(cell.extra)
        item.update(cell_type=cell.cell_type.value, source=cell.source,
                    metadata=deepcopy(cell.metadata))
        if cell.cell_id is not None:
            item["id"] = cell.cell_id
        if cell.cell_type == CellType.CODE:
            item["execution_count"] = cell.execution_count
            item["outputs"] = [output_to_node(output) for output in cell.outputs]
        raw["cells"].append(item)
    return nbformat.from_dict(raw)


def save_notebook(notebook: Notebook, path: Optional[Path] = None) -> None:
    target = Path(path or notebook.path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    node = to_node(notebook)
    nbformat.validate(node)
    serialized = nbformat.writes(node, version=nbformat.NO_CONVERT)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        nbformat.read(temporary, as_version=4)
        os.replace(temporary, target)
        notebook.path = target
        notebook.dirty = False
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def new_notebook(path: Path) -> Notebook:
    cell = Cell(cell_type=CellType.CODE, source="", metadata={}, cell_id=uuid.uuid4().hex[:8])
    return Notebook(path=Path(path), cells=[cell], metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    })
