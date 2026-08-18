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
