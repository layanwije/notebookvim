# nbcli

`nbcli` is a keyboard-driven notebook for the terminal. Version 0.1 focuses on
the essential loop: open a Jupyter notebook, navigate and edit cells, execute
them in one persistent kernel, inspect output, and save.

## Install for development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Use

```bash
cd path/to/project
nbcli

nbcli new experiment.ipynb
nbcli experiment.ipynb
nbcli path/to/project
```

Opening `nbcli` without a path starts a project workspace in the current
directory. Use `Ctrl+B` to toggle the project tree and `Ctrl+P` to fuzzy-find a
file. Selecting a notebook or supported UTF-8 text file opens it without leaving
the application. Python, Markdown, JSON, TOML, YAML, SQL, shell, and other common
source files receive syntax highlighting; use `Ctrl+S` to save and `Ctrl+Q` to
quit from the text editor. Generated
directories such as `.git`, `.venv`, `node_modules`, and `__pycache__` are
hidden from the navigator.

Selecting a `.parquet`, `.parq`, or `.pq` file opens a read-only preview of its
first 25 rows followed by Spark-style `count`, `mean`, `stddev`, `min`, and
`max` summary statistics. Statistics are calculated directly with PyArrow;
Spark is not started.

Project editing shortcuts:

```text
Ctrl+Tab        Move between the file browser and active editor
Option+Enter    Open the selected browser file in a new tab (Alt+Enter in terminals)
Shift+Tab       Move to the next open tab
Ctrl+Shift+Tab  Move to the previous open tab
Ctrl+B, then t  Terminal-safe way to focus the browser and open a file in a tab
Escape, then ]/[ Terminal-safe next / previous tab
Ctrl+Z / Ctrl+Y Undo / redo text edits
Escape, then :  Open commands from a text file; Enter resumes editing
```

Python text files and Python notebook cells receive local Jedi completions;
press `Tab` to accept a displayed completion. Markdown and other supported text
files retain syntax highlighting without Python completions.

Navigation mode uses `j`/`k` (or arrows), `Enter` to edit, `r` to run, `R` to
run and advance, `Ctrl+S` to save, and `q` to quit. In edit mode, use `Escape`
to return to navigation.

Press `:` in navigation mode for commands. Selected-cell commands include:

```text
:cell run                  :run cell 2
:cell output clear
:cell add above            :cell add below
:cell delete               :cell duplicate
:cell move up              :cell move down
:cell type code            :cell type markdown
```

Displayed cell numbers are one-based and include every code and Markdown cell.
For example, `:run cell 2` selects and executes the second cell when it is a
code cell.

Notebook and kernel commands include `:notebook run all`, `:notebook save`,
`:kernel info`, `:kernel interrupt`, `:kernel restart`, and `:kernel shutdown`.
Use `:help` in the application for the complete list. Short aliases such as
`:run`, `:output clear`, `:w`, `:q`, and `:wq` are also supported.

Open a workspace terminal beside the active document with `:terminal`,
`:terminal open`, or `:terminal open side`. Use `:terminal open below` for a
lower split and hide either layout with `:terminal close`. The terminal keeps its current
directory and command history while hidden. Use Up/Down for history, Ctrl+L to
clear its output, Ctrl+C to interrupt a running command, and Escape to return
focus to the editor. It uses a VS Code-style dark terminal background,
foreground, and 16-color ANSI palette. It is a lightweight command shell for builds, tests, and
project commands; full-screen interactive terminal programs are not supported.
Commands run through the configured macOS login shell in interactive mode, so
normal shell startup files and aliases are loaded. ANSI and true-color output
is preserved inside the terminal frame.

### Databricks

Authenticate with the Databricks CLI, then connect the current nbcli session:

```text
:databricks connect
:databricks connect MyProfile
:databricks connect https://your-workspace.cloud.databricks.com
:databricks status
```

Passing a workspace URL opens browser-based OAuth, which is the easiest route
for Databricks Free Edition. With no argument, nbcli uses default unified
authentication; a non-URL argument selects a named Databricks profile.

After connecting, Python notebook cells automatically receive `workspace` (a
Databricks `WorkspaceClient`) and `dbutils`. Local use of `dbutils` supports the
utility groups exposed by the Databricks SDK, including `fs`, `secrets`,
`widgets`, and `jobs`. For example:

```python
for item in dbutils.fs.ls("/"):
    print(item.path)
```

Credentials remain in the standard Databricks authentication configuration and
are not written into notebook files. This connection provides workspace
utilities; notebook cells still execute in the local Python kernel.

### Git profiles

Named Git profiles keep commit identity and provider account selection together.
Credentials remain in GitHub CLI, Git Credential Manager, or the operating
system credential store; nbcli never stores access tokens or passwords.

```text
:git profile add personal github laivw me@example.com "My Name"
:git profile add work azure me@company.com me@company.com "My Name"
:git profile list
:git profile use personal
:git login personal
:git status
:git pull
:git push
```

GitHub browser login requires `gh` or Git Credential Manager. Azure DevOps
browser login requires Git Credential Manager and uses Microsoft OAuth. Profile
selection writes the profile's author name and email to the current repository,
so it does not change the identity of unrelated projects.

Other commands:

```bash
nbcli run experiment.ipynb
nbcli info experiment.ipynb
nbcli --help
```

## Development

```bash
pytest
```
