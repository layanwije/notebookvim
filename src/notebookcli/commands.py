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
    "folder open",
    "folder close",
    "project open",
    "project close",
    "project scaffold init data-engineering",
    "file open",
    "file new",
    "file create",
    "tab open",
    "tab next",
    "tab previous",
    "tab close",
    "files focus",
    "terminal",
    "terminal open",
    "terminal open side",
    "terminal open below",
    "terminal close",
    "ai",
    "ai open",
    "ai open side",
    "ai open below",
    "ai close",
    "ai interrupt",
    "ai status",
    "ai provider codex",
    "ai provider claude",
    "ai provider ollama",
    "ai provider ollama llama3.2",
    "ai ask",
    "sql",
    "sql new",
    "sql run",
    "sql explain",
    "sql history",
    "sql save",
    "sql cancel",
    "profile",
    "profile current",
    "profile save",
    "inspect parquet describe",
    "inspect parquet profile",
    "inspect parquet partitions",
    "inspect parquet rowgroups",
    "inspect parquet schema",
    "inspect parquet history",
    "inspect parquet files",
    "inspect delta describe",
    "inspect delta profile",
    "inspect delta version",
    "inspect delta schema",
    "inspect delta partitions",
    "inspect delta rowgroups",
    "inspect delta history",
    "inspect delta files",
    "inspect delta properties",
    "inspect delta cdf",
    "inspect delta time travel",
    "inspect close",
    "theme",
    "theme default",
    "theme vscode-dark",
    "theme vscode-light",
    "theme databricks-light",
    "theme databricks-dark",
    "theme snowflake-light",
    "theme snowflake-dark",
    "databricks connect",
    "databricks status",
    "databricks sync set",
    "databricks sync status",
    "databricks sync diff",
    "databricks sync pull",
    "databricks sync push",
    "databricks sync resolve local",
    "databricks sync resolve remote",
    "databricks jobs",
    "databricks jobs running",
    "databricks run",
    "databricks logs",
    "databricks logs follow",
    "databricks cancel",
    "databricks rerun",
    "git profile add",
    "git profile list",
    "git profile use",
    "git login",
    "git status",
    "git pull",
    "git push",
    "help",
    "exit",
    "write close",
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
    "q": "tab close",
    "quit": "tab close",
    "wq": "write close",
}

COMMAND_SUGGESTIONS = (*COMMANDS, *ALIASES.keys())


def normalize_command(value: str) -> str:
    original = " ".join(value.strip().lstrip(":").split())
    path_open = re.fullmatch(
        r"(folder open|project open|file open|file new|file create|tab open)(?: (.+))?",
        original,
        re.IGNORECASE,
    )
    if path_open:
        operation = path_open.group(1).lower()
        path = path_open.group(2)
        return operation + (f" {path}" if path else "")
    profile_connect = re.fullmatch(r"databricks connect(?: (.+))?", original, re.IGNORECASE)
    if profile_connect:
        profile = profile_connect.group(1)
        return "databricks connect" + (f" {profile}" if profile else "")
    git_arguments = re.fullmatch(
        r"git (profile (?:add|use)|login)(?: (.+))?", original, re.IGNORECASE
    )
    if git_arguments:
        operation = git_arguments.group(1).lower()
        arguments = git_arguments.group(2)
        return f"git {operation}" + (f" {arguments}" if arguments else "")
    remote_arguments = re.fullmatch(
        r"databricks (sync (?:set|pull|push)|run|logs(?: follow)?|cancel|rerun)(?: (.+))?",
        original,
        re.IGNORECASE,
    )
    if remote_arguments:
        operation = remote_arguments.group(1).lower()
        arguments = remote_arguments.group(2)
        return f"databricks {operation}" + (f" {arguments}" if arguments else "")
    ai_prompt = re.fullmatch(r"ai ask(?: (.+))?", original, re.IGNORECASE)
    if ai_prompt:
        prompt = ai_prompt.group(1)
        return "ai ask" + (f" {prompt}" if prompt else "")
    ai_provider = re.fullmatch(r"ai provider (codex|claude|ollama)(?: (\S+))?", original, re.IGNORECASE)
    if ai_provider:
        provider = ai_provider.group(1).lower()
        model = ai_provider.group(2)
        return f"ai provider {provider}" + (f" {model}" if model else "")
    command = original.lower()
    numbered_run = re.fullmatch(r"(?:run cell|cell run) (\d+)", command)
    if numbered_run:
        return f"cell run {numbered_run.group(1)}"
    return ALIASES.get(command, command)
