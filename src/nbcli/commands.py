from __future__ import annotations

import re


COMMANDS = (
    "cell run",
    "run cell 1",
    "cell run advance",
    "cell output clear",
    "cell output collapse",
    "cell output expand",
    "cell add above",
    "cell add below",
    "cell delete",
    "cell duplicate",
    "cell move up",
    "cell move down",
    "cell type code",
    "cell type markdown",
    "cell type raw",
    "notebook save",
    "notebook run all",
    "notebook run above",
    "notebook run below",
    "notebook output clear",
    "kernel info",
    "kernel interrupt",
    "kernel restart",
    "kernel shutdown",
    "tab open",
    "tab next",
    "tab previous",
    "files focus",
    "help",
    "quit",
    "write quit",
)


ALIASES = {
    "run": "cell run",
    "run advance": "cell run advance",
    "output clear": "cell output clear",
    "output collapse": "cell output collapse",
    "output expand": "cell output expand",
    "delete": "cell delete",
    "run all": "notebook run all",
    "run above": "notebook run above",
    "run below": "notebook run below",
    "cell code": "cell type code",
    "cell markdown": "cell type markdown",
    "cell raw": "cell type raw",
    "w": "notebook save",
    "write": "notebook save",
    "tabs": "tab next",
    "q": "quit",
    "wq": "write quit",
}

COMMAND_SUGGESTIONS = (*COMMANDS, *ALIASES.keys())


def normalize_command(value: str) -> str:
    command = " ".join(value.strip().lstrip(":").lower().split())
    numbered_run = re.fullmatch(r"(?:run cell|cell run) (\d+)", command)
    if numbered_run:
        return f"cell run {numbered_run.group(1)}"
    return ALIASES.get(command, command)
