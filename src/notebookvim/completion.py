"""Local Python completion support for notebook cells."""

from __future__ import annotations

from pathlib import Path

import jedi


def python_completions(source: str, path: Path, line: int, column: int) -> list[str]:
    """Return unique Python completions for a zero-based editor position.

    Jedi runs in-process, so this intentionally makes no connection to a
    language server or a Jupyter kernel.
    """
    try:
        script = jedi.Script(code=source, path=str(path))
        completions = script.complete(line=line + 1, column=column)
    except Exception:
        # A cell is often incomplete while it is being typed.
        # Jedi also delegates some introspection to a local subprocess; a
        # completion failure should never interrupt editing.
        return []

    seen: set[str] = set()
    return [
        completion.name
        for completion in completions
        if completion.name not in seen and not seen.add(completion.name)
    ][:12]
