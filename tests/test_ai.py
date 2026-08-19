import json
import signal
from pathlib import Path

from notebookcli.ai import ClaudeProvider, CodexProvider, OllamaProvider, create_provider


def test_provider_commands_use_safe_non_interactive_modes():
    root = Path("/workspace")
    codex = CodexProvider().command("help", root)
    claude = ClaudeProvider().command("help", root)

    assert codex[:2] == ["codex", "exec"]
    assert "--json" in codex
    assert codex[codex.index("--sandbox") + 1] == "read-only"
    assert "--print" in claude
    assert claude[claude.index("--permission-mode") + 1] == "plan"


def test_codex_jsonl_message_is_normalized():
    line = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Hello"}})
    assert CodexProvider().parse_line(line)[0].text == "Hello"


def test_claude_stream_message_is_normalized():
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}})
    assert ClaudeProvider().parse_line(line)[0].text == "Hi"


def test_ollama_model_can_be_configured(monkeypatch):
    monkeypatch.setenv("NBCLI_OLLAMA_MODEL", "qwen2.5-coder")
    assert OllamaProvider().command("help", Path("/workspace"))[:3] == [
        "ollama", "run", "qwen2.5-coder"
    ]
    command = OllamaProvider().command("help", Path("/workspace"))
    assert "--hidethinking" in command
    assert "--nowordwrap" in command


def test_provider_factory_rejects_unknown_provider():
    try:
        create_provider("missing")
    except ValueError as exc:
        assert "Unknown AI provider" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_provider_factory_passes_ollama_model():
    provider = create_provider("ollama", model="qwen2.5-coder:7b")
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5-coder:7b"


def test_provider_cancel_interrupts_running_process(monkeypatch):
    provider = OllamaProvider()

    class Process:
        pid = 123

    provider.process = Process()  # type: ignore[assignment]
    calls = []
    monkeypatch.setattr("notebookcli.ai.os.killpg", lambda pid, sig: calls.append((pid, sig)))

    assert provider.cancel() is True
    assert calls == [(123, signal.SIGINT)]
