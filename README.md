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

### Parquet and Delta inspection

With a Parquet file open, typing `:inspect` prioritizes contextual
`inspect parquet …` completions. Available metadata views are:

```text
:inspect parquet describe
:inspect parquet profile
:inspect parquet partitions
:inspect parquet rowgroups
:inspect parquet schema
:inspect parquet files
:inspect parquet history
```

Describe shows physical format, dimensions, compression, producer, and metadata
size. Schema includes nested fields and field metadata; row groups include row
counts and sizes; partitions recognize Hive-style `key=value` paths. Plain
Parquet has no transaction history, so its history view reports filesystem
modification information and explains that limitation.

If the open Parquet file is below a Delta table root containing `_delta_log`,
Delta completions are added automatically:

```text
:inspect delta describe
:inspect delta profile
:inspect delta version
:inspect delta schema
:inspect delta partitions
:inspect delta rowgroups
:inspect delta history
:inspect delta files
:inspect delta properties
:inspect delta cdf
:inspect delta time travel 12
```

The inspector reconstructs snapshots from retained JSON commits and Parquet
checkpoints, including multipart checkpoints and referenced V2 sidecars. It
replays add/remove actions for current or historical versions and exposes table
metadata, protocol versions, active files, per-file statistics, commit
operations, properties, and change-data-file actions. Reports are read-only and
limited to 500 rows where a table may contain many files or row groups.

Delta profiling uses DuckDB over the active snapshot files. It deliberately
refuses snapshots containing deletion vectors because a direct Parquet scan
would otherwise include logically deleted rows.

Inspection metadata opens in a scrollable overlay by default. Press `Escape`
to close it and return to the same file and cursor context; inspection does not
create or switch document tabs. Append `side` or `below` to keep a report next
to the source while working, and close a pinned report with `Escape` or
`:inspect close`:

```text
:inspect parquet schema side
:inspect parquet rowgroups below
:inspect delta history side
:inspect close
```

The terminal and inspection report share the auxiliary split area, so opening
one closes the other instead of squeezing the source into three panes.

### Local SQL and dataset profiles

Open a syntax-highlighted, entirely local DuckDB workspace with `:sql`. Enter
SQL, press `Escape`, and use these commands:

```text
:sql                 Open the existing SQL tab, or create one
:sql new             Open another SQL tab
:sql run             Run the current query (up to 200 displayed rows)
:sql explain         Show the DuckDB query plan
:sql history         Show recent session queries
:sql save            Save the query under queries/
:sql cancel          Cancel a running query (Ctrl+C also works)
```

DuckDB can query project data directly without starting Python, Spark, or a
server—for example, `SELECT * FROM read_parquet('data/sales.parquet')` or
`SELECT * FROM read_csv_auto('data/sales.csv')`. Results remain attached to the
SQL tab and include execution time and a truncation marker when more rows exist.

From a Parquet preview or SQL workspace, use `:profile` (or `:profile current`)
to open a profile tab. It shows shape, types, null rates, approximate distinct
counts, min/max, mean, standard deviation, quartiles, common values, inferred
identifier/timestamp/categorical roles, and available Parquet metadata. Use
`:profile save` or `Ctrl+S` from the profile tab to export the result as JSON in
the project root. Profiling uses DuckDB summaries and bounded top-value checks;
it does not load the whole dataset into application memory.

Project editing shortcuts:

```text
Ctrl+Tab        Move between the file browser and active editor
Option+Enter    Open the selected browser file in a new tab (Alt+Enter in terminals)
Shift+Tab       Move to the next open tab
Ctrl+Shift+Tab  Move to the previous open tab
Ctrl+W          Close the active tab (`:tab close` also works)
Escape, then q  Close the active file/tab
Ctrl+B, then t  Terminal-safe way to focus the browser and open a file in a tab
Escape, then ]/[ Terminal-safe next / previous tab
u / Ctrl+R      Undo / redo in Normal mode
:               Open commands in Normal mode
```

The status bar keeps the essential controls visible: `:` for commands,
`:help`, `Ctrl+B` for files, `i` to edit, `Ctrl+S` to save, and `Ctrl+Q` to
exit. Closing the final tab leaves the project browser and command system open
and shows the Notebook CLI welcome screen. From there, open another file or use
`Esc`, then `:` to enter a command, just as you would return to commands in Vim.

Python text files and Python notebook cells receive local Jedi completions;
press `Tab` to accept a displayed completion. Markdown and other supported text
files retain syntax highlighting without Python completions.

Switch the entire interface palette at runtime with `:theme NAME`. The theme
updates application chrome, notebook cells, editors, syntax colors, selections,
overlays, tables, and the integrated terminal together. Seven themes are built in:

```text
:theme default             Original nbcli appearance
:theme vscode-dark         VS Code Dark Modern-inspired dark palette
:theme vscode-light        VS Code Light Modern-inspired light palette
:theme databricks-light    Databricks workspace-inspired light palette
:theme databricks-dark     Databricks navy-and-lava dark palette
:theme snowflake-light     Snowflake Workspaces-inspired airy light palette
:theme snowflake-dark      Snowflake-inspired deep navy editor palette
```

Use `:theme` without a name to see the active theme and available choices.
The last selected theme is saved in the user-level nbcli settings file and is
restored the next time the application starts. Set `NBCLI_CONFIG_HOME` to use a
custom settings directory.
The Python and SQL editors use a dedicated token palette for every named theme,
including theme-specific colors for keywords, strings, numbers, functions,
types, variables, fields, comments, punctuation, and built-ins.

nbcli cannot change the font face from inside a terminal: the terminal performs
font rendering for the entire character grid. `:theme` therefore reports the
recommended terminal-profile font for the selected theme: the platform VS Code
default (Menlo, Consolas, or Droid Sans Mono), DM Mono for Databricks, and
JetBrains Mono or Apercu Mono for Snowflake. Configure that face in Terminal,
iTerm2, Windows Terminal, or the VS Code integrated-terminal profile.

Editable files open in Vim-style Normal mode and cannot be changed until you
press `i`, `a`, `I`, `A`, `o`, or `O`. The status bar shows `NORMAL`, `INSERT`,
or `VISUAL`. In a text file, Normal mode supports `h`/`j`/`k`/`l`, `w`/`b`,
`0`/`$`, `gg`/`G`, `dd`, `yy`, `x`, `p`/`P`, `u`, `Ctrl+R`, and character-wise
Visual mode with `v`. Press `Escape` to return to Normal mode. Python files
keep local completions in Insert mode, and `Tab` accepts a suggestion.

Platform-style cursor shortcuts work alongside Vim motions. On macOS,
`Command+Left/Right` goes to the start/end of a line and
`Command+Up/Down` goes to the start/end of the document. On Windows and Linux,
`Ctrl+Left/Right` moves by word and `Ctrl+Up/Down` moves to the start/end of the
document. Add `Shift` to extend the selection. `Option+Left/Right` also moves by
word on macOS. Command-key delivery depends on the terminal exposing enhanced
keyboard events; Home/End and the Vim motions remain available everywhere.

Notebook cells use the same modal idea. Press `Enter` on a selected cell to
open it in cell-Normal mode, then `i` to edit. The first `Escape` returns from
Insert to cell-Normal mode; a second `Escape` commits the cell and returns to
notebook navigation. Pressing `i` from notebook navigation remains a shortcut
that opens the cell directly in Insert mode. Use `j`/`k` to select cells,
`o`/`O` to create and edit a cell below/above, `dd` to delete, `yy` to copy,
`p`/`P` to paste below/above, `u`/`Ctrl+R` to undo/redo, `gg`/`G` for the
first/last cell, `J`/`K` to move a cell, `m` to switch code/Markdown, and
`r`/`R` to run or run-and-advance. Arrow keys remain available. `Enter` does
not enter Insert mode.

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
Use `:help` in the application for the complete list. `:q` closes the active
file/tab—including the final tab—while `:wq` saves and closes it. `:exit` exits nbcli after the usual
unsaved-work confirmation. Other short aliases include `:run`,
`:output clear`, and `:w`.

The command bar shows matching commands in a selectable list as you type. Use
Up/Down to choose an option, Tab to fill it, and Enter to run it. This includes
command arguments such as every available option after `:theme`. Open a project
file by its workspace-relative path with `:file open reports/sales.py`, or open
it in a new tab with `:tab open reports/sales.py`; both commands complete file
paths from the current project, including subdirectories.

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

### Remote notebook synchronization

After connecting to Databricks, map the active local notebook or source file to
a workspace notebook:

```text
:databricks sync set /Workspace/Users/me@example.com/Analysis
:databricks sync set /Workspace/Users/me@example.com/Analysis --strip-outputs
:databricks sync status
:databricks sync diff
:databricks sync pull
:databricks sync push
```

Supported working-copy formats are `.ipynb`, `.py`, `.sql`, `.scala`, and `.r`.
Mappings and the last synchronized content hash live under `.nbcli/`, which is
hidden from the project browser. Jupyter notebooks use the native Jupyter
workspace format so notebook and cell metadata survive round trips. Source
notebooks use the matching Databricks language.

Safety rules are deliberately strict:

- Pull never overwrites unsaved editor changes.
- Pull also stops when the saved local file changed since synchronization.
- Push stops when the remote content changed since synchronization.
- `:databricks sync diff` displays source changes by notebook cell.
- Resolve a reviewed conflict with `:databricks sync resolve local` (force
  push) or `:databricks sync resolve remote` (force pull). Both require saved
  local work.
- `--strip-outputs` removes code outputs and execution counts from uploaded
  Jupyter notebooks while leaving the local file unchanged.

You may also provide the mapping on the first operation, such as
`:databricks sync push /Workspace/Users/me@example.com/Analysis`.

### Remote jobs and logs

Databricks jobs use the same authenticated connection:

```text
:databricks jobs
:databricks jobs running
:databricks run 12345 --param date=2026-08-19 --param region=eu
:databricks logs 98765
:databricks logs follow 98765
:databricks cancel 98765
:databricks rerun 98765
```

The job and run views show identifiers, state, result, start time, duration,
parameters, compute ID, and the Databricks run link. A run ID can be omitted
from logs, cancel, and rerun immediately after `:databricks run`; nbcli remembers
the most recently started run. Follow mode refreshes every two seconds until a
terminal state is reported.

Databricks returns standard-stream driver logs for supported non-notebook task
types and notebook exit values or failures for notebook tasks. It does not
return notebook driver stdout through the Jobs output endpoint; complete
cluster logs require a log destination configured on the Databricks job.

This initial remote provider is Databricks. The synchronization and report
models are provider-neutral, but Microsoft Fabric authentication, definition
conversion, job execution, and log retrieval still require a Fabric adapter.

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
