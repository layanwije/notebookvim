from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from notebookcli.data_workspace import DuckDBWorkspace


def test_duckdb_workspace_runs_bounded_queries_and_tracks_history():
    workspace = DuckDBWorkspace()

    result = workspace.execute("select range as value from range(5)", limit=3)

    assert result.columns == ["value"]
    assert result.rows == [[0], [1], [2]]
    assert result.truncated
    assert workspace.history == ["select range as value from range(5)"]


def test_dataset_profiler_reports_shape_nulls_quantiles_and_metadata(tmp_path: Path):
    path = tmp_path / "sample.parquet"
    pq.write_table(
        pa.table(
            {
                "customer_id": [1, 2, 3, 4],
                "segment": ["business", "consumer", "consumer", None],
                "revenue": [10.0, 20.0, 30.0, 40.0],
            }
        ),
        path,
        row_group_size=2,
    )

    profile = DuckDBWorkspace().profile_parquet(path)
    columns = {column.name: column for column in profile.columns}

    assert profile.row_count == 4
    assert profile.column_count == 3
    assert profile.metadata["row_groups"] == 2
    assert columns["customer_id"].role == "identifier"
    assert columns["segment"].null_count == 1
    assert columns["segment"].null_percentage == 25.0
    assert columns["segment"].role == "categorical"
    assert columns["revenue"].median == "25.0"
    assert columns["revenue"].mean == "25.0"


def test_profile_can_be_exported_as_json(tmp_path: Path):
    workspace = DuckDBWorkspace()
    profile = workspace.profile_query("select 1 as id, 'ready' as status")
    output = tmp_path / "profile.json"

    profile.save(output)

    text = output.read_text(encoding="utf-8")
    assert '"row_count": 1' in text
    assert '"name": "status"' in text
