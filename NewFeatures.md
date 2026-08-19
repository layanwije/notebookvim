# Proposed Features

## Codex integration

Embed a local Codex coding agent directly in nbcli. The recommended foundation
is [Codex App Server](https://learn.chatgpt.com/docs/app-server), the protocol
used to power rich Codex clients such as the VS Code extension. It supports
authentication, persistent conversations, streamed agent events, command and
file-change approvals, and thread history.

### Proposed user experience

```text
:codex
:codex open side
:codex open below
:codex close
:codex new
:codex resume
```

Example requests:

```text
Explain cell 3
Fix the error in cell 5
Add a Markdown explanation below this cell
Review the current notebook
Run the tests and fix failures
```

### Implementation

1. **Codex process bridge**

   Launch `codex app-server` locally and communicate through its JSONL protocol
   over standard input and output. Handle initialization, request IDs, threads,
   turns, streamed events, cancellation, process failure, and restart.

2. **Codex panel**

   Add a side or lower split containing conversation history, prompt input,
   streaming responses, command status, file-change summaries, approval
   controls, and stop/new/resume actions.

3. **Project and notebook context**

   Start each Codex thread at the project root and provide the active file,
   selected cell number and type, current cell source, unsaved state, and
   Databricks connection status. Never include credentials or secret values.

4. **Notebook-aware operations**

   Provide safe application-level operations so Codex does not need to edit raw
   notebook JSON:

   - Read a cell and its output
   - Replace cell source
   - Insert a cell above or below
   - Change a cell type
   - Run a cell
   - Save the notebook

5. **Approvals and security**

   - Restrict file access to the current workspace
   - Ask before commands with side effects
   - Ask before applying notebook or file changes
   - Display a diff before accepting changes
   - Allow the user to decline or cancel requests
   - Keep OpenAI and Databricks credentials out of prompts and notebook files

6. **Editing-conflict protection**

   Codex must not overwrite unsaved notebook or text-editor changes. Prefer
   changes through nbcli's in-memory document model. If a file changes outside
   the app, show a reload or merge prompt.

7. **Conversation persistence**

   Store the Codex thread ID per project so a later `:codex resume` can continue
   the previous conversation. Support starting, resuming, and eventually
   forking threads.

### Delivery stages

#### Stage 1: Codex panel MVP

- Project-aware chat
- Streaming responses
- Start, resume, and cancel turns
- Persistent thread IDs
- Command and file-change approval prompts
- Basic error and process-restart handling

Estimated effort: **3–5 development days**.

#### Stage 2: Notebook-native agent

- Cell-aware context
- Safe cell editing and insertion
- Cell execution and output inspection
- File diffs and notebook change previews
- Unsaved-change conflict protection

Estimated effort: **3–5 additional development days**.

#### Stage 3: Polished integrated experience

- Rich command and diff rendering
- Thread browser and conversation management
- Configurable model and permissions
- Keyboard shortcuts and context actions
- Robust recovery, testing, and UX refinement

Estimated total for a polished VS Code-like integration: **2–3 weeks**.

### Technical direction

Use Codex App Server for the primary integration because nbcli is a Python and
Textual application and needs streamed events, approvals, authentication, and
conversation history. The [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)
is useful for simpler programmatic workflows but currently requires a
TypeScript/Node.js integration.

## Data-professional workbench

With notebook editing, Parquet display, an integrated terminal, Databricks
utilities, and the proposed Codex integration, nbcli can grow into a compact
local-first data workbench. The next features should make it possible to query,
inspect, validate, visualize, and operationalize data without leaving the app.

### 1. Embedded DuckDB SQL workspace

**Implemented (initial version):** local SQL tabs, syntax highlighting, bounded
result tables, query timing, history, saved `.sql` queries, query plans, and
cancellation. Catalog-aware completion and interactive result paging remain
future refinements.

Open Parquet, CSV, JSON, or DuckDB files and query them directly with SQL.

```text
:sql
:sql new
:sql explain
:sql history
```

Example:

```sql
SELECT region, SUM(revenue)
FROM read_parquet('sales/*.parquet')
WHERE order_date >= '2026-01-01'
GROUP BY region;
```

The SQL workspace should provide syntax highlighting, completion for tables and
columns, result paging, cancellation, query timing, saved queries, and query
plans. DuckDB can query Parquet directly with projection and filter pushdown,
which avoids loading unnecessary rows and columns.

Reference: [DuckDB Parquet documentation](https://duckdb.org/docs/current/guides/file_formats/query_parquet)

### 2. Dataset profiler

**Implemented (initial version):** Parquet files and DuckDB query results can be
profiled in dedicated tabs and exported as JSON. Profiles include shape, types,
null rates, approximate cardinality, ranges, quartiles, averages, standard
deviation, common values, semantic-role hints, and Parquet metadata. Richer
string-pattern and histogram visualizations remain future refinements.

### Parquet and Delta lakehouse inspection

**Implemented:** contextual `:inspect parquet …` and `:inspect delta …`
commands now expose physical metadata, schemas, partitions, row groups, files,
Delta transaction history, versions, time-travel snapshots, properties, and
change data feed information. Delta snapshots are reconstructed from retained
JSON commits and checkpoints. Profiling is blocked for deletion-vector
snapshots until a deletion-vector-aware reader is added.

Add a `:profile` command for files, query results, and active dataframes.

```text
:profile
:profile current
:profile save
```

Display:

- Row and column counts
- Data types and nested types
- Null counts and percentages
- Approximate distinct counts
- Minimum, maximum, mean, and quantiles
- Top and bottom values
- String lengths and patterns
- Numeric distributions and outliers
- Suspected identifiers, timestamps, and categorical columns
- Parquet row groups, compression, file size, and partition information

Profiling should work on bounded samples or metadata where possible so large
datasets do not need to be loaded fully into memory.

### 3. Interactive dataframe explorer

Provide a consistent explorer for pandas, Polars, PySpark, and DuckDB results.

Capabilities:

- Sort and filter columns
- Search values
- Select, resize, reorder, hide, and freeze columns
- Page or stream through large results
- Expand nested structs, lists, maps, and JSON values
- Copy selected cells, rows, or columns
- Export the current filtered selection
- Jump from a result to the cell or query that produced it
- Show the source dataframe or query name in the tab

### 4. Variable and object explorer

Inspect objects in the active Python kernel.

```text
:variables
:inspect df
:inspect spark
:inspect variable_name
```

Show object names, Python types, dimensions, estimated memory use, dataframe
schemas, collection sizes, and safe previews. Dataframe objects should open in
the interactive explorer.

### 5. Charts from data and query results

Create charts from selected dataframe columns or SQL results:

- Histograms
- Time-series plots
- Scatter plots
- Bar and stacked-bar charts
- Box plots
- Correlation heatmaps
- Missing-value charts
- Distribution comparisons

Support a small chart configuration panel and commands such as:

```text
:chart
:chart histogram revenue
:chart line order_date revenue by region
:chart save
```

Charts should be reproducible by generating Python or declarative chart code
that can be inserted into a notebook cell.

### 6. Data-quality rules and validation

Create validation rules directly from a dataset, schema, or selected columns.

```text
:validate
:validate infer
:validate save
:validate run
```

Rules should cover:

- Required and nullable columns
- Data types
- Unique and composite keys
- Accepted values
- Numeric and date ranges
- String patterns
- Cross-column conditions
- Row-count and freshness expectations
- Custom Python checks

Display all failures together with example failing rows. Validation definitions
should be exportable as Python and reusable in automated pipelines. Pandera is
a possible backend because it supports pandas, Polars, PySpark, and Ibis.

Reference: [Pandera documentation](https://pandera.readthedocs.io/en/stable/)

### 7. Schema comparison and drift detection

Compare two files, dataframe versions, tables, or snapshots.

```text
:schema compare current previous.parquet
:schema compare table_a table_b
:drift current baseline.parquet
```

Highlight:

- Added, removed, and reordered columns
- Type and nullability changes
- New or removed categorical values
- Distribution and quantile changes
- Unexpected row-count movement
- Key uniqueness changes
- Timestamp freshness changes
- Partition and Parquet metadata changes

Allow a comparison to be saved as a baseline for future checks.

### 8. Connection and catalog browser

Provide one browser for local and remote data systems:

- Databricks
- Microsoft Fabric
- PostgreSQL
- Snowflake
- BigQuery
- DuckDB
- S3-compatible storage
- Azure Data Lake Storage
- Local CSV, JSON, Arrow, and Parquet datasets

Browse connections, catalogs, databases, schemas, tables, views, volumes,
columns, and saved queries. Connection profiles should keep credentials in the
platform's standard secure configuration rather than notebook files.

### 9. Polars lazy execution support

Treat Polars `LazyFrame` objects as first-class objects. Provide schema preview,
optimized and unoptimized query plans, streaming execution, cancellation, and
materialization into the data explorer.

```text
:inspect lazy_frame
:plan lazy_frame
:collect lazy_frame
```

Polars supports lazy scanning for formats including CSV, IPC, Parquet, and JSON,
with query optimization and larger-than-memory streaming.

Reference: [Polars lazy API](https://docs.pola.rs/user-guide/lazy/using/)

### 10. Export and format conversion

Export a complete result, selected rows, or the current filtered view.

```text
:export csv
:export parquet
:export json
:export xlsx
:export clipboard
:convert parquet
```

Support compression, overwrite confirmation, partitioning, delimiter and
encoding options, and predictable handling of nested values and timestamps.

## Codex tools for data work

Codex should use structured, narrowly scoped data tools rather than receiving
unrestricted access to complete datasets.

Proposed tools:

- `inspect_schema`
- `profile_dataset`
- `sample_rows`
- `run_duckdb_query`
- `explain_query_plan`
- `inspect_dataframe`
- `compare_schemas`
- `validate_dataset`
- `create_chart`
- `export_result`
- `replace_cell`
- `insert_cell`
- `run_cell`
- `read_cell_output`

Example requests:

```text
Why are these two datasets producing different totals?
Profile this file and identify suspicious columns.
Write a DuckDB query that joins every Parquet file in this folder.
Optimize this Polars transformation.
Generate validation rules from the observed schema.
Explain why cell 7 uses so much memory.
Chart monthly revenue by region.
Compare this month's schema with the saved baseline.
```

### Data privacy and approvals

- Provide schema, statistics, and a small redacted sample by default
- Never send a complete dataset unless the user explicitly approves it
- Detect or mask likely credentials and sensitive values
- Show the exact sample or query result that will be included in model context
- Require approval before running mutating queries or exporting data
- Require approval before uploading or exposing data to a remote service
- Keep OpenAI, database, cloud, and Databricks credentials out of prompts
- Record which tools and data samples were used during each Codex turn

## Longer-term professional features

### Parameterized and repeatable notebook runs

- Define notebook parameters and defaults
- Run parameter sets locally or remotely
- Save run configurations
- Compare outputs between runs
- Execute from the CLI or a schedule

### Cell dependencies and data lineage

- Detect variables, files, tables, and cells consumed or produced by each cell
- Display a dependency graph
- Trace a result back to its input cells and source datasets
- Mark stale downstream cells after an upstream edit
- Export lineage metadata

### Git-aware notebook workflows

- Cell-aware notebook diffs
- Output-aware diff filtering
- Side-by-side comparison
- Notebook merge assistance
- Ignore or strip outputs before committing
- Review Codex changes before applying them

### Reproducible environments and execution snapshots

- Select and display the Python environment
- Capture installed package versions
- Record kernel, Python, Spark, and Java versions
- Save environment metadata with a run
- Restore or recreate an environment
- Snapshot cell inputs, outputs, duration, and execution order

### Query history and saved snippets

- Searchable SQL and Python execution history
- Favorite and tag snippets
- Parameterized saved queries
- Re-run against a different connection
- Insert a saved query into a notebook cell

### Background jobs and notifications

- Run long notebooks or queries without blocking the editor
- Display progress, logs, duration, and resource status
- Cancel or retry runs
- Notify when a run succeeds, fails, or requires approval
- Reopen the notebook at the failing cell

### dbt support

- Browse dbt projects, models, sources, tests, and exposures
- Read `manifest.json` and `catalog.json`
- Display model lineage
- Run or test selected models
- Jump between compiled SQL and source SQL
- Show failed tests and affected downstream models

### Pipeline and DAG view

- Visualize notebook, job, and dbt dependencies
- Show execution state and duration
- Run selected nodes or downstream branches
- Inspect logs and outputs by node
- Export pipeline definitions where supported

### Credentials and secret handling

- Named connection profiles
- Environment-variable and system-keychain integration
- Secret redaction in logs, outputs, and Codex context
- Connection testing without displaying secret values
- Clear separation between local, development, and production profiles

### Remote execution

**Implemented for Databricks (initial version):** guarded local working-copy
synchronization, cell-aware notebook diffs, remote revision detection, optional
output stripping, conflict resolution, jobs and active-run lists, parameterized
runs, task outputs, log following, cancellation, and reruns. The same internal
models are ready for another provider; the Microsoft Fabric API adapter remains
future work.

- Databricks notebook and job execution
- Microsoft Fabric notebook execution
- Remote Spark sessions
- Remote SQL warehouse execution
- Upload, download, and synchronization workflows
- Clear visual distinction between local and remote execution
- Cost, quota, and cancellation visibility where APIs provide it

### Dataset navigation

- Bookmarks and favorites
- Recently opened files and tables
- Search across catalogs and project data files
- Dataset descriptions and user notes
- Related datasets and saved joins

## Recommended implementation order

1. Embedded DuckDB SQL workspace
2. Dataset profiler
3. Interactive dataframe and variable explorer
4. Export and format conversion
5. Charts from results
6. Data-quality validation
7. Codex data tools and privacy controls
8. Schema comparison and drift detection
9. Connection and catalog browser
10. Remote Databricks and Fabric execution
11. Reproducibility, lineage, Git-aware diffs, and pipeline workflows
