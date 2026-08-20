"""Textual conversation pane backed by provider-neutral AI adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from .ai import AIProvider, create_provider
from .rendering import safe_text


class AIInput(Input):
    BINDINGS = [
        Binding("escape", "leave_ai", "Editor", priority=True),
        Binding("ctrl+c", "cancel_ai", "Cancel", priority=True),
    ]

    @property
    def pane(self) -> "AIPane":
        assert isinstance(self.parent, AIPane)
        return self.parent

    def action_leave_ai(self) -> None:
        self.app.focus_document_from_ai()  # type: ignore[attr-defined]

    def action_cancel_ai(self) -> None:
        self.pane.cancel()


class AIPane(Vertical):
    """A small streaming chat surface shared by all providers."""

    def __init__(
        self,
        workspace_root: Path,
        provider: str = "codex",
        model: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.workspace_root = Path(workspace_root).resolve()
        self.provider_name = provider
        self.provider: AIProvider = create_provider(provider, model=model)

    def compose(self) -> ComposeResult:
        yield Static(id="ai-header")
        yield RichLog(max_lines=5_000, wrap=True, markup=False, id="ai-output")
        yield AIInput(placeholder="Ask about the current workspace…", id="ai-input")

    def on_mount(self) -> None:
        self._update_header()
        self._write("Ask about the current file, cell, error, or workspace.", "dim")

    def _update_header(self) -> None:
        status = "available" if self.provider.available else "not installed"
        model = getattr(self.provider, "model", None)
        model_label = f" · {model}" if model else ""
        self.query_one("#ai-header", Static).update(
            f" AI · {self.provider.name}{model_label} · {status} · read-only"
        )

    def _write(self, value: str, style: str = "") -> None:
        clean = safe_text(value)
        if clean:
            self.query_one("#ai-output", RichLog).write(Text(clean, style=style))

    def _write_markdown(self, value: str) -> None:
        clean = safe_text(value).strip()
        if clean:
            self.query_one("#ai-output", RichLog).write(
                Markdown(
                    clean,
                    code_theme=getattr(self.app, "syntax_theme", "ansi_dark"),
                )
            )

    def set_provider(self, name: str, model: Optional[str] = None) -> None:
        self.cancel()
        self.provider_name = name
        self.provider = create_provider(name, model=model)
        self._update_header()
        selected_model = getattr(self.provider, "model", None)
        suffix = f" ({selected_model})" if selected_model else ""
        self._write(f"Provider changed to {self.provider.name}{suffix}", "bold cyan")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "ai-input":
            return
        event.stop()
        prompt = event.value.strip()
        event.input.value = ""
        if prompt:
            self.ask(prompt)

    @work(exclusive=True)
    async def ask(self, prompt: str) -> None:
        ai_input = self.query_one("#ai-input", AIInput)
        ai_input.disabled = True
        self._write(f"You: {prompt}", "bold")
        context = self.app.ai_context()  # type: ignore[attr-defined]
        request = f"{context}\n\nUser request:\n{prompt}" if context else prompt
        response_parts: list[str] = []
        response_rendered = False
        try:
            async for event in self.provider.run(request, self.workspace_root):
                if event.kind == "error":
                    self._write(event.text, "bold red")
                elif event.kind == "completed":
                    if response_parts:
                        self._write("AI:", "bold cyan")
                        self._write_markdown("\n".join(response_parts))
                        response_rendered = True
                    self._write(event.text, "dim green")
                else:
                    text = event.text.strip("\r\n")
                    if text and (not response_parts or text != response_parts[-1]):
                        response_parts.append(text)
        finally:
            if response_parts and not response_rendered:
                self._write("AI:", "bold cyan")
                self._write_markdown("\n".join(response_parts))
            ai_input.disabled = False
            ai_input.focus()

    def cancel(self) -> bool:
        """Interrupt the active provider process, returning whether one existed."""
        interrupted = self.provider.cancel()
        if interrupted:
            self._write("Interrupt requested", "yellow")
        return interrupted

    async def shutdown(self) -> None:
        self.cancel()
        if self.provider.process is not None:
            try:
                await self.provider.process.wait()
            except ProcessLookupError:
                pass
