from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from jupyter_client import AsyncKernelManager

from .model import Cell, DisplayOutput, ErrorOutput, ExecutionState, Output, StreamOutput


@dataclass
class ExecutionUpdate:
    state: ExecutionState
    output: Optional[Output] = None
    execution_count: Optional[int] = None


UpdateCallback = Callable[[ExecutionUpdate], Awaitable[None]]


def kernel_environment() -> dict:
    """Build a kernel environment, including an installed local Spark runtime."""
    environment = os.environ.copy()
    spark_home = environment.get("SPARK_HOME")

    candidates = []
    if spark_home:
        candidates.append(Path(spark_home))
    spark_submit = shutil.which("spark-submit")
    if spark_submit:
        install_root = Path(spark_submit).resolve().parent.parent
        candidates.extend((install_root, install_root / "libexec"))
    candidates.extend((
        Path("/opt/homebrew/opt/apache-spark/libexec"),
        Path("/usr/local/opt/apache-spark/libexec"),
    ))

    discovered_spark = next(
        (candidate for candidate in candidates if (candidate / "python" / "pyspark").is_dir()),
        None,
    )
    if discovered_spark is not None:
        environment["SPARK_HOME"] = str(discovered_spark)
        python_dir = discovered_spark / "python"
        py4j_archives = sorted((python_dir / "lib").glob("py4j*.zip"))
        python_paths = [str(python_dir), *(str(path) for path in py4j_archives)]
        if environment.get("PYTHONPATH"):
            python_paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)

    if not environment.get("JAVA_HOME"):
        java_homes = []
        for root in (Path("/opt/homebrew/opt"), Path("/usr/local/opt")):
            java_homes.extend(sorted(root.glob("openjdk*/libexec/openjdk.jdk/Contents/Home"), reverse=True))
        java_home = next((path for path in java_homes if (path / "bin" / "java").is_file()), None)
        if java_home is not None:
            environment["JAVA_HOME"] = str(java_home)

    return environment


class Kernel:
    """Persistent Jupyter kernel with semantic execution updates."""

    def __init__(self, kernel_name: str = "python3", timeout: float = 120.0) -> None:
        self.kernel_name = kernel_name
        self.timeout = timeout
        self.manager: Optional[AsyncKernelManager] = None
        self.client = None
        self._execute_lock = asyncio.Lock()
        self.initialization_code: Optional[str] = None
        self._initialized = False

    @property
    def alive(self) -> bool:
        return self.manager is not None

    async def start(self) -> None:
        if self.manager is not None:
            return
        manager = AsyncKernelManager(kernel_name=self.kernel_name)
        await manager.start_kernel(env=kernel_environment())
        client = manager.client()
        client.start_channels()
        try:
            await client.wait_for_ready(timeout=30)
        except BaseException:
            client.stop_channels()
            await manager.shutdown_kernel(now=True)
            raise
        self.manager, self.client = manager, client

    def set_initialization_code(self, code: Optional[str]) -> None:
        self.initialization_code = code
        self._initialized = False

    async def _initialize(self) -> None:
        if self._initialized or not self.initialization_code:
            return
        assert self.client is not None
        message_id = self.client.execute(
            self.initialization_code,
            silent=True,
            store_history=False,
            allow_stdin=False,
            stop_on_error=True,
        )
        error = None
        while True:
            message = await self.client.get_iopub_msg(timeout=self.timeout)
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue
            content = message.get("content", {})
            if message.get("msg_type") == "error":
                error = f"{content.get('ename', 'Error')}: {content.get('evalue', '')}"
            if message.get("msg_type") == "status" and content.get("execution_state") == "idle":
                break
        if error:
            raise RuntimeError(f"Kernel initialization failed: {error}")
        self._initialized = True

    async def execute(self, cell: Cell, update: UpdateCallback) -> bool:
        async with self._execute_lock:
            await self.start()
            await self._initialize()
            assert self.client is not None
            cell.outputs.clear()
            cell.execution_state = ExecutionState.RUNNING
            started = time.monotonic()
            await update(ExecutionUpdate(ExecutionState.RUNNING))
            message_id = self.client.execute(cell.source, allow_stdin=False, stop_on_error=True)
            success = True
            try:
                while True:
                    message = await self.client.get_iopub_msg(timeout=self.timeout)
                    if message.get("parent_header", {}).get("msg_id") != message_id:
                        continue
                    msg_type = message.get("msg_type")
                    content = message.get("content", {})
                    if msg_type == "execute_input":
                        cell.execution_count = content.get("execution_count")
                    elif msg_type == "stream":
                        output = StreamOutput(output_type="stream", name=content.get("name", "stdout"),
                                              text=content.get("text", ""))
                        cell.outputs.append(output)
                        await update(ExecutionUpdate(ExecutionState.RUNNING, output))
                    elif msg_type in {"display_data", "execute_result"}:
                        output = DisplayOutput(output_type=msg_type, data=content.get("data", {}),
                                               metadata=content.get("metadata", {}),
                                               execution_count=content.get("execution_count"))
                        cell.outputs.append(output)
                        await update(ExecutionUpdate(ExecutionState.RUNNING, output))
                    elif msg_type == "error":
                        output = ErrorOutput(output_type="error", ename=content.get("ename", "Error"),
                                             evalue=content.get("evalue", ""),
                                             traceback=content.get("traceback", []))
                        cell.outputs.append(output)
                        success = False
                        await update(ExecutionUpdate(ExecutionState.RUNNING, output))
                    elif msg_type == "status" and content.get("execution_state") == "idle":
                        break
            except asyncio.TimeoutError:
                success = False
                output = ErrorOutput(output_type="error", ename="TimeoutError",
                                     evalue=f"Cell exceeded {self.timeout:g} seconds")
                cell.outputs.append(output)
                await update(ExecutionUpdate(ExecutionState.RUNNING, output))
            cell.execution_duration = time.monotonic() - started
            cell.execution_state = ExecutionState.SUCCEEDED if success else ExecutionState.FAILED
            await update(ExecutionUpdate(cell.execution_state, execution_count=cell.execution_count))
            return success

    async def interrupt(self) -> None:
        if self.manager is not None:
            await self.manager.interrupt_kernel()

    async def restart(self) -> None:
        if self.manager is None:
            await self.start()
            return
        await self.manager.restart_kernel(now=True)
        assert self.client is not None
        await self.client.wait_for_ready(timeout=30)
        self._initialized = False

    async def shutdown(self) -> None:
        if self.manager is None:
            return
        if self.client is not None:
            self.client.stop_channels()
        await self.manager.shutdown_kernel(now=True)
        self.manager = None
        self.client = None
        self._initialized = False
