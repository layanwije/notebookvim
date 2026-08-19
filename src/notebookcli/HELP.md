# NotebookCLI Guide

NotebookCLI is a keyboard-driven notebook, code editor, data explorer, terminal,
and AI workspace for the command line. It opens Jupyter notebooks and common
text files without taking you out of the terminal.

This guide is read-only. Scroll with the arrow keys, Page Up/Page Down, `j`/`k`,
`gg`, and `G`. Close it with `:tab close`, `Ctrl+W`, or `Esc` followed by `q`.

## Quick start

```bash
pipx install notebookcli
cd path/to/project
notebookcli
```

Useful ways to launch:

```bash
notebookcli                         # start without an open project
notebookcli .                       # open the current folder
notebookcli path/to/project         # open a folder
notebookcli analysis.ipynb          # open a notebook
notebookcli new analysis.ipynb      # create a notebook
notebookcli run analysis.ipynb      # run every code cell
notebookcli info analysis.ipynb     # inspect notebook metadata
```

Inside NotebookCLI, press `Esc`, then `:` to enter a command. Start with:

```text
:folder open path       Open a project folder
:file open path         Open a file in the current tab
:file new path          Create an empty file in the project
:file create path       Alias for :file new
:tab open path          Open a file in a new tab
:terminal               Open the integrated terminal
:ai                     Open the AI pane
:ai open below          Open the AI pane below the document
:help                   Open this guide
```

Paths may be absolute or relative to the current project. Folder commands do
not scan the filesystem for suggestions, so type or paste the desired path.

## Moving around

| Key | Action |
| --- | --- |
| `Ctrl+E` | Focus the file explorer; press it again to hide the explorer |
| `Ctrl+P` | Find a file in the current project |
| `Ctrl+Tab` | Move between the explorer and active editor |
| `Shift+Tab` | Next open tab |
| `Ctrl+Shift+Tab` | Previous open tab |
| `Ctrl+W` | Close the active tab |
| `Ctrl+S` | Save the active notebook or text file |
| `Ctrl+Q` | Exit NotebookCLI |
| `Esc`, then `:` | Open the command line |
| `Esc`, then `q` | Close the active tab |

The editor starts in Vim-like Normal mode. Press `i`, `a`, `I`, `A`, `o`, or
`O` to edit. Press `Esc` to return to Normal mode. Normal mode supports
`h`/`j`/`k`/`l`, `w`/`b`, `0`/`$`, `gg`/`G`, `dd`, `yy`, `x`, `p`/`P`,
`u`, `Ctrl+R`, and character-wise Visual mode with `v`.

## Projects, files, and tabs

```text
:folder open PATH       Open or switch to a project folder
:folder close           Close the current project
:project open PATH      Alias for :folder open
:project close          Alias for :folder close
:project scaffold init data-engineering
                        Add a Databricks data-engineering starter structure
:file open PATH         Replace the active tab with a project file
:file new PATH          Create an empty project file (also: :file create PATH)
:tab open PATH          Open a project file in a new tab
:tab next               Select the next tab
:tab previous           Select the previous tab
:tab close              Close the active tab
:files focus            Focus the file explorer
```

Unsaved work must be saved or closed before switching projects. The explorer
hides generated folders such as `.git`, `.venv`, `node_modules`, and
`__pycache__`.

## Notebooks

Jupyter notebooks keep one persistent Python kernel per notebook tab, so values
defined in one cell remain available to later cells.

Notebook navigation:

| Key | Action |
| --- | --- |
| `j` / `k` | Select the next or previous cell |
| `Enter` | Open the selected cell in Normal mode |
| `i` | Open the selected cell directly in Insert mode |
| `o` / `O` | Add a cell below or above |
| `dd` | Delete the selected cell |
| `yy` | Copy the selected cell |
| `p` / `P` | Paste below or above |
| `u` / `Ctrl+R` | Undo or redo |
| `gg` / `G` | First or last cell |

Notebook commands:

```text
:cell run               Run the selected cell
:cell run advance       Run the cell and move to the next one
:cell add above         Add a cell above
:cell add below         Add a cell below
:cell delete            Delete the selected cell
:cell duplicate         Duplicate the selected cell
:cell move up           Move the selected cell up
:cell move down         Move the selected cell down
:cell type code         Change the cell to code
:cell type markdown     Change the cell to Markdown
:cell type raw          Change the cell to raw content
:cell output clear      Clear the selected cell output
:cell output collapse   Collapse the selected cell output
:cell output expand     Expand the selected cell output
:notebook save          Save the notebook
:notebook run all       Run every code cell
:notebook run above     Run code cells above the selection
:notebook run below     Run code cells below the selection
:notebook output clear  Clear all notebook output
```

Kernel commands:

```text
:kernel info
:kernel interrupt
:kernel restart
:kernel shutdown
```

## Integrated terminal

The terminal runs in the current project directory.

```text
:terminal               Open beside the editor
:terminal open          Open beside the editor
:terminal open side     Open beside the editor
:terminal open below    Open below the editor
:terminal close         Close the terminal pane
```

Press `Escape` in the terminal to return to the document. Opening the AI or
inspection pane closes the terminal pane so the document remains usable.

## AI assistant

NotebookCLI can stream responses from an installed AI command-line tool. The
supported providers are Ollama, OpenAI Codex, and Claude Code.

```text
:ai                              Open the AI pane
:ai ask PROMPT                   Ask from the command line
:ai status                       Show installed providers
:ai provider ollama              Use Ollama with the default model
:ai provider ollama MODEL        Use a particular Ollama model
:ai provider codex               Use OpenAI Codex
:ai provider claude              Use Claude Code
:ai interrupt                    Stop the current response
:ai close                        Close the AI pane
```

The active file or selected notebook cell is included as bounded context. The
Codex integration runs in read-only sandbox mode, and Claude Code runs in plan
mode. Review any suggested changes before applying them.

### Ollama: local models

Ollama runs models locally and is available for macOS, Windows, and Linux.
Download it from <https://ollama.com/download>. On Linux, the official installer
is:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama if it is not already running, then download the default model:

```bash
ollama serve
ollama pull llama3.2
```

In NotebookCLI:

```text
:ai provider ollama llama3.2
:ai
```

You can select any locally installed Ollama model, for example:

```text
:ai provider ollama qwen2.5-coder:7b
```

Large models need more memory. If a model is slow or fails to load, choose a
smaller model. See <https://docs.ollama.com/quickstart>.

### OpenAI Codex

On macOS or Linux, install the Codex CLI with OpenAI's official installer:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex
```

Run `codex` once and follow the sign-in flow, then select it in NotebookCLI:

```text
:ai provider codex
:ai
```

Official guide: <https://developers.openai.com/codex/cli>

### Claude Code

Install Claude Code using one of Anthropic's supported methods. The npm method
requires Node.js 18 or newer:

```bash
npm install -g @anthropic-ai/claude-code
claude
```

Authenticate on first launch, then select it in NotebookCLI:

```text
:ai provider claude
:ai
```

Official guide:
<https://docs.anthropic.com/en/docs/claude-code/getting-started>

## Local SQL and data profiles

Use the DuckDB workspace to query local CSV, JSON, and Parquet data without
starting Python or Spark.

```text
:sql                 Open the current SQL workspace
:sql new             Open another SQL tab
:sql run             Run the current query
:sql explain         Show the query plan
:sql history         Show session query history
:sql save            Save the query under queries/
:sql cancel          Cancel a running query
:profile             Profile the current dataset
:profile save        Export the profile as JSON
```

Example:

```sql
SELECT *
FROM read_parquet('data/sales.parquet')
LIMIT 100;
```

Opening a Parquet file shows a read-only preview and summary statistics. Delta
tables can be inspected from their transaction log.

```text
:inspect parquet describe
:inspect parquet profile
:inspect parquet schema
:inspect parquet partitions
:inspect parquet rowgroups
:inspect parquet files
:inspect delta describe
:inspect delta version
:inspect delta schema
:inspect delta history
:inspect delta files
:inspect delta properties
:inspect delta time travel VERSION
:inspect close
```

Add `side` or `below` to an inspection command to pin the report beside the
source, for example `:inspect parquet schema side`.

## Databricks

Authenticate with the Databricks CLI first, then connect the current session:

```text
:databricks connect [PROFILE]
:databricks status
:databricks sync set LOCAL REMOTE
:databricks sync status
:databricks sync diff
:databricks sync pull
:databricks sync push
:databricks jobs
:databricks jobs running
:databricks run
:databricks logs
:databricks logs follow
:databricks cancel
:databricks rerun
```

Remote mappings are stored under `.nbcli/` in the project. Credentials remain
in the Databricks configuration or system credential store.

## Git

```text
:git status
:git pull
:git push
:git login
:git profile list
:git profile use NAME
```

Use `:git profile add` to register an identity for a provider/account, then
activate it with `:git profile use NAME`.

## Themes

```text
:theme
:theme default
:theme vscode-dark
:theme vscode-light
:theme databricks-light
:theme databricks-dark
:theme snowflake-light
:theme snowflake-dark
```

## Saving, closing, and exiting

```text
:w                  Save
:write              Save
:wq                 Save and close the active tab
:q                  Close the active tab
:exit               Exit NotebookCLI
```

NotebookCLI warns before replacing, closing, or exiting with unsaved work.

## Troubleshooting

- Run `notebookcli --version` to confirm which executable is active.
- If `pipx install nbcli` was used, uninstall it; that PyPI package is an
  unrelated NetBox tool. Install `notebookcli` instead.
- Run `:ai status` to confirm that an AI provider executable is on `PATH`.
- For Ollama, verify `ollama list` works and that the selected model is present.
- If a kernel is stuck, use `:kernel interrupt`, then `:kernel restart`.
- If a file is missing from the explorer, use `Ctrl+P` or reopen the project.
- Use `:help` at any time to return to this guide.
