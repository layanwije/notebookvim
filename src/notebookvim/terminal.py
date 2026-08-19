"""A lightweight workspace shell pane for the terminal UI."""

from __future__ import annotations

import asyncio
import errno
import os
import pty
import re
import shlex
import signal
from pathlib import Path
from typing import Optional

from rich.text import Text
from rich.terminal_theme import TerminalTheme
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, RichLog

from .rendering import safe_text


_OSC_SEQUENCE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")

# The familiar palette used by VS Code's integrated terminal in its default
# dark appearance. True-color escape sequences continue to use their exact RGB.
VSCODE_DARK_TERMINAL_THEME = TerminalTheme(
    background=(24, 24, 24),
    foreground=(204, 204, 204),
    normal=[
        (0, 0, 0),
        (205, 49, 49),
        (13, 188, 121),
        (229, 229, 16),
        (36, 114, 200),
        (188, 63, 188),
        (17, 168, 205),
        (229, 229, 229),
    ],
    bright=[
        (102, 102, 102),
        (241, 76, 76),
        (35, 209, 139),
        (245, 245, 67),
        (59, 142, 234),
        (214, 112, 214),
        (41, 184, 219),
        (229, 229, 229),
    ],
)


def terminal_text(value: str, style: str = "") -> Text:
    """Render shell ANSI colors while discarding terminal title sequences."""
    sanitized = _OSC_SEQUENCE.sub("", value).replace("\r", "")
    return Text.from_ansi(sanitized, style=style, no_wrap=False)


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
        self.master_fd: Optional[int] = None
        self.transcript: list[str] = []

    def compose(self) -> ComposeResult:
        yield RichLog(max_lines=5_000, wrap=True, markup=False, id="terminal-output")
        yield TerminalInput(id="terminal-input")

    def on_mount(self) -> None:
        self._write(f"notebookvim terminal · {self.cwd}", style="bold cyan")
        self._update_prompt()

    def _update_prompt(self) -> None:
        self.query_one("#terminal-input", TerminalInput).placeholder = f"{self.cwd}  $"

    def set_workspace(self, workspace_root: Path) -> None:
        """Use a project folder as the default directory for later commands."""
        self.previous_cwd = self.cwd
        self.cwd = Path(workspace_root).resolve()
        self._update_prompt()
        self._write(f"notebookvim workspace · {self.cwd}", style="bold cyan")

    def _write(self, value: str, style: str = "") -> None:
        clean = safe_text(value)
        self.transcript.append(clean)
        self.query_one("#terminal-output", RichLog).write(terminal_text(value, style))

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
        raw_value = event.value
        command = raw_value.strip()
        event.input.value = ""
        if self.process is not None:
            self.send_input(raw_value + "\n")
            return
        if not command:
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

    def send_input(self, value: str) -> bool:
        """Forward user input to the foreground process through its PTY."""
        if self.process is None or self.master_fd is None:
            return False
        try:
            os.write(self.master_fd, value.encode("utf-8"))
        except OSError as exc:
            self._write(f"terminal input: {exc}", "red")
            return False
        return True

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
        terminal_input.placeholder = "Send input to running process…  (Ctrl+C to interrupt)"
        shell = os.environ.get("SHELL") or "/bin/sh"
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        environment = os.environ.copy()
        environment.setdefault("TERM", "xterm-256color")
        environment.setdefault("COLORTERM", "truecolor")
        environment.setdefault("CLICOLOR", "1")
        try:
            self.process = await asyncio.create_subprocess_exec(
                shell,
                "-lic",
                command,
                cwd=str(self.cwd),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=environment,
                start_new_session=True,
            )
            os.close(slave_fd)
            slave_fd = -1
            while True:
                try:
                    chunk = await asyncio.to_thread(os.read, master_fd, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                self._write(chunk.decode("utf-8", errors="replace").rstrip("\n"))
            return_code = await self.process.wait()
            if return_code:
                self._write(f"exit {return_code}", "red")
        except Exception as exc:
            self._write(str(exc), "red")
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)
            if self.master_fd is not None:
                os.close(self.master_fd)
                self.master_fd = None
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
