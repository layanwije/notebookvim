from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class CellType(str, Enum):
    CODE = "code"
    MARKDOWN = "markdown"
    RAW = "raw"


class ExecutionState(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class Output:
    output_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamOutput(Output):
    name: str = "stdout"
    text: str = ""


@dataclass
class DisplayOutput(Output):
    data: Dict[str, Any] = field(default_factory=dict)
    execution_count: Optional[int] = None


@dataclass
class ErrorOutput(Output):
    ename: str = "Error"
    evalue: str = ""
    traceback: List[str] = field(default_factory=list)


@dataclass
class Cell:
    cell_type: CellType
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    cell_id: Optional[str] = None
    execution_count: Optional[int] = None
    outputs: List[Output] = field(default_factory=list)
    execution_state: ExecutionState = ExecutionState.IDLE
    execution_duration: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Notebook:
    path: Path
    cells: List[Cell]
    metadata: Dict[str, Any] = field(default_factory=dict)
    nbformat: int = 4
    nbformat_minor: int = 5
    extra: Dict[str, Any] = field(default_factory=dict)
    dirty: bool = False

    @property
    def kernel_name(self) -> str:
        kernelspec = self.metadata.get("kernelspec", {})
        return str(kernelspec.get("name") or "python3")

    @property
    def language(self) -> str:
        language_info = self.metadata.get("language_info", {})
        return str(language_info.get("name") or "python")

