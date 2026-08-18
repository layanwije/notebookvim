"""A lightweight workspace shell pane for the terminal UI."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, RichLog

from .rendering import safe_text


class TerminalInput(Input):
    BINDINGS = [
        Binding("escape", "leave_terminal", "Editor", priority=True),
        Binding("up", "previous_command", "Previous", priority=True),
        Binding("down", "next_command", "Next", priority=True),
        Binding("ctrl+l", "clear_terminal", "Clear", priority=True),
        Binding("ctrl+c", "interrupt_terminal", "Interrupt", priority=True),
    ]

    @property
    def terminal(self) -> "TerminalPane":
        assert isinstance(self.parent, TerminalPane)
        return self.parent

    def action_leave_terminal(self) -> None:
        self.app.focus_document_from_terminal()  # type: ignore[attr-defined]

    def action_previous_command(self) -> None:
        self.value = self.terminal.previous_command()
        self.cursor_position = len(self.value)

    def action_next_command(self) -> None:
        self.value = self.terminal.next_command()
        self.cursor_position = len(self.value)

    def action_clear_terminal(self) -> None:
        self.terminal.clear()

    def action_interrupt_terminal(self) -> None:
        self.terminal.interrupt()


class TerminalPane(Vertical):
    def __init__(self, workspace_root: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cwd = Path(workspace_root).resolve()
        self.previous_cwd = self.cwd
        self.history: list[str] = []
        self.history_index = 0
        self.process: Optional[asyncio.subprocess.Process] = None
        self.transcript: list[str] = []

    def compose(self) -> ComposeResult:
        yield RichLog(max_lines=5_000, wrap=True, markup=False, id="terminal-output")
        yield TerminalInput(id="terminal-input")

    def on_mount(self) -> None:
        self._write(f"nbcli terminal · {self.cwd}", style="bold cyan")
        self._update_prompt()

    def _update_prompt(self) -> None:
        self.query_one("#terminal-input", TerminalInput).placeholder = f"{self.cwd}  $"

    def _write(self, value: str, style: str = "") -> None:
        clean = safe_text(value)
        self.transcript.append(clean)
        self.query_one("#terminal-output", RichLog).write(Text(clean, style=style))

    def clear(self) -> None:
        self.transcript.clear()
        self.query_one("#terminal-output", RichLog).clear()

    def previous_command(self) -> str:
        if not self.history:
            return ""
        self.history_index = max(0, self.history_index - 1)
        return self.history[self.history_index]

    def next_command(self) -> str:
        if not self.history:
            return ""
        self.history_index = min(len(self.history), self.history_index + 1)
        return "" if self.history_index == len(self.history) else self.history[self.history_index]

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "terminal-input":
            return
        event.stop()
        command = event.value.strip()
        event.input.value = ""
        if not command:
            return
        if self.process is not None:
            self._write("A command is already running; press Ctrl+C to interrupt it", "yellow")
            return
        self.history.append(command)
        self.history_index = len(self.history)
        self._write(f"$ {command}", style="bold")
        if self._change_directory(command):
            return
        if command == "clear":
            self.clear()
            return
        self.run_command(command)

    def _change_directory(self, command: str) -> bool:
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            self._write(str(exc), "red")
            return True
        if not parts or parts[0] != "cd":
            return False
        if len(parts) > 2:
            self._write("cd: too many arguments", "red")
            return True
        if len(parts) == 1:
            target = Path.home()
        elif parts[1] == "-":
            target = self.previous_cwd
        else:
            candidate = Path(parts[1]).expanduser()
            target = candidate if candidate.is_absolute() else self.cwd / candidate
        target = target.resolve()
        if not target.is_dir():
            self._write(f"cd: no such directory: {target}", "red")
            return True
        self.previous_cwd, self.cwd = self.cwd, target
        self._update_prompt()
        self._write(str(self.cwd), "cyan")
        return True

    @work(exclusive=True)
    async def run_command(self, command: str) -> None:
        terminal_input = self.query_one("#terminal-input", TerminalInput)
        terminal_input.placeholder = f"{self.cwd}  running…  (Ctrl+C to interrupt)"
        shell = os.environ.get("SHELL") or "/bin/sh"
        try:
            self.process = await asyncio.create_subprocess_exec(
                shell,
                "-lc",
                command,
                cwd=str(self.cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert self.process.stdout is not None
            while line := await self.process.stdout.readline():
                self._write(line.decode("utf-8", errors="replace").rstrip("\n"))
            return_code = await self.process.wait()
            if return_code:
                self._write(f"exit {return_code}", "red")
        except Exception as exc:
            self._write(str(exc), "red")
        finally:
            self.process = None
            self._update_prompt()
            if self.display:
                terminal_input.focus()

    def interrupt(self) -> None:
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass

    async def shutdown(self) -> None:
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            await self.process.wait()
            self.process = None
