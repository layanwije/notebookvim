"""Provider-neutral streaming adapters for local AI command-line tools."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional


@dataclass(frozen=True)
class AIEvent:
    """A normalized event emitted by an AI provider."""

    kind: str
    text: str


class AIProvider(ABC):
    """Base class for an installed AI CLI."""

    name: str
    executable: str

    def __init__(self) -> None:
        self.process: Optional[asyncio.subprocess.Process] = None

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    @abstractmethod
    def command(self, prompt: str, workspace: Path) -> list[str]:
        """Return the command used for one prompt."""

    def parse_line(self, line: str) -> list[AIEvent]:
        return [AIEvent("message", line)] if line else []

    async def run(self, prompt: str, workspace: Path) -> AsyncIterator[AIEvent]:
        if not self.available:
            yield AIEvent("error", f"{self.name} is not installed or is not on PATH")
            return
        environment = os.environ.copy()
        environment.setdefault("NO_COLOR", "1")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command(prompt, workspace),
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
            assert self.process.stdout is not None
            while line := await self.process.stdout.readline():
                decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
                for event in self.parse_line(decoded):
                    yield event
            return_code = await self.process.wait()
            if return_code:
                yield AIEvent("error", f"{self.name} exited with status {return_code}")
            else:
                yield AIEvent("completed", "Done")
        except asyncio.CancelledError:
            self.cancel()
            raise
        except OSError as exc:
            yield AIEvent("error", str(exc))
        finally:
            self.process = None

    def cancel(self) -> bool:
        if self.process is None:
            return False
        try:
            os.killpg(self.process.pid, signal.SIGINT)
        except ProcessLookupError:
            return False
        return True


class CodexProvider(AIProvider):
    name = "Codex"
    executable = "codex"

    def command(self, prompt: str, workspace: Path) -> list[str]:
        return [
            self.executable,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            str(workspace),
            prompt,
        ]

    def parse_line(self, line: str) -> list[AIEvent]:
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return super().parse_line(line)
        event_type = str(payload.get("type", ""))
        item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        text = item.get("text") or item.get("message") or payload.get("message")
        if not isinstance(text, str) or not text.strip():
            return []
        kind = "error" if "error" in event_type else "message"
        return [AIEvent(kind, text)]


class ClaudeProvider(AIProvider):
    name = "Claude Code"
    executable = "claude"

    def command(self, prompt: str, workspace: Path) -> list[str]:
        return [
            self.executable,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "plan",
            prompt,
        ]

    def parse_line(self, line: str) -> list[AIEvent]:
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return super().parse_line(line)
        if payload.get("type") == "result" and isinstance(payload.get("result"), str):
            return [AIEvent("message", payload["result"])]
        message = payload.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        events = []
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                events.append(AIEvent("message", str(block["text"])))
        return events


class OllamaProvider(AIProvider):
    name = "Ollama"
    executable = "ollama"

    def __init__(self, model: Optional[str] = None) -> None:
        super().__init__()
        self.model = model or os.environ.get("NOTEBOOKVIM_OLLAMA_MODEL", "llama3.2")

    def command(self, prompt: str, workspace: Path) -> list[str]:
        # Suppress Ollama's cursor-driven thinking display and host-width wrapping;
        # both are intended for a real terminal rather than a static RichLog.
        return [
            self.executable,
            "run",
            self.model,
            "--hidethinking",
            "--nowordwrap",
            prompt,
        ]


PROVIDER_TYPES = {
    "codex": CodexProvider,
    "claude": ClaudeProvider,
    "ollama": OllamaProvider,
}


def create_provider(name: str, model: Optional[str] = None) -> AIProvider:
    try:
        provider_type = PROVIDER_TYPES[name.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown AI provider: {name}") from exc
    return provider_type(model=model) if provider_type is OllamaProvider else provider_type()


def provider_statuses() -> dict[str, bool]:
    return {name: provider().available for name, provider in PROVIDER_TYPES.items()}
