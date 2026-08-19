import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nbcli.lakehouse import DeltaLog, LakehouseInspector, find_delta_root


def write_actions(path: Path, actions: list[dict]) -> None:
    path.write_text("".join(json.dumps(action) + "\n" for action in actions), encoding="utf-8")


def delta_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "sales"
    log = root / "_delta_log"
    partition = root / "region=eu"
    log.mkdir(parents=True)
    partition.mkdir()
    first = partition / "part-000.parquet"
    second = partition / "part-001.parquet"
    pq.write_table(pa.table({"id": [1, 2], "region": ["eu", "eu"]}), first)
    pq.write_table(pa.table({"id": [3, 4, 5], "region": ["eu", "eu", "eu"]}), second)
    schema = {
        "type": "struct",
        "fields": [
            {"name": "id", "type": "long", "nullable": False, "metadata": {}},
            {"name": "region", "type": "string", "nullable": True, "metadata": {}},
        ],
    }
    write_actions(
        log / "00000000000000000000.json",
        [
            {"protocol": {"minReaderVersion": 1, "minWriterVersion": 2}},
            {"metaData": {
                "id": "table-id", "name": "sales", "description": "Sales table",
                "format": {"provider": "parquet", "options": {}},
                "schemaString": json.dumps(schema), "partitionColumns": ["region"],
                "configuration": {"delta.enableChangeDataFeed": "true"},
            }},
            {"add": {
                "path": "region=eu/part-000.parquet", "size": first.stat().st_size,
                "partitionValues": {"region": "eu"}, "modificationTime": 1000,
                "stats": json.dumps({"numRecords": 2}),
            }},
            {"commitInfo": {"timestamp": 1000, "operation": "WRITE", "userName": "test"}},
        ],
    )
    write_actions(
        log / "00000000000000000001.json",
        [
            {"remove": {"path": "region=eu/part-000.parquet", "deletionTimestamp": 2000}},
            {"add": {
                "path": "region=eu/part-001.parquet", "size": second.stat().st_size,
                "partitionValues": {"region": "eu"}, "modificationTime": 2000,
                "stats": json.dumps({"numRecords": 3}),
            }},
            {"cdc": {"path": "_change_data/cdc-1.parquet", "size": 128}},
            {"commitInfo": {
                "timestamp": 2000, "operation": "MERGE", "userName": "test",
                "operationMetrics": {"numOutputRows": "3"},
            }},
        ],
    )
    return root, first, second


def test_parquet_inspection_reports_metadata_schema_partitions_and_rowgroups(tmp_path):
    partition = tmp_path / "region=eu"
    partition.mkdir()
    path = partition / "data.parquet"
    pq.write_table(pa.table({"id": [1, 2, 3], "label": ["a", "b", "c"]}), path, row_group_size=2)
    inspector = LakehouseInspector(path)

    describe = inspector.parquet("describe")
    assert ["rows", "3"] in describe.rows
    assert ["row groups", "2"] in describe.rows
    assert inspector.parquet("schema").rows[0][0] == "id"
    assert inspector.parquet("partitions").rows == [["region", "eu"]]
    assert len(inspector.parquet("rowgroups").rows) == 2
    assert inspector.parquet("files").rows[0][0] == "data.parquet"
    assert "do not contain transaction history" in inspector.parquet("history").details[0]


def test_delta_log_replays_snapshots_and_time_travel(tmp_path):
    root, first, second = delta_fixture(tmp_path)
    log = DeltaLog(root)

    assert log.latest_version == 1
    assert log.snapshot(0).paths == [first]
    snapshot = log.snapshot()
    assert snapshot.paths == [second]
    assert snapshot.metadata["partitionColumns"] == ["region"]
    assert find_delta_root(second) == root

    inspector = LakehouseInspector(second)
    assert ["version", "1"] in inspector.delta("describe").rows
    assert ["active files", "1"] in inspector.delta("describe").rows
    assert ["rows from statistics", "3"] in inspector.delta("describe").rows
    assert ["version", "0"] in inspector.delta("time travel", 0).rows
    assert inspector.delta("schema").rows[0][:3] == ["id", "long", "no"]
    assert inspector.delta("partitions").rows == [['{"region": "eu"}', "1"]]
    assert inspector.delta("files").rows[0][0] == "region=eu/part-001.parquet"
    assert inspector.delta("properties").rows == [["delta.enableChangeDataFeed", "true"]]


def test_delta_history_cdf_and_rowgroups(tmp_path):
    _, _, active = delta_fixture(tmp_path)
    inspector = LakehouseInspector(active)

    history = inspector.delta("history")
    assert history.rows[0][0] == "1"
    assert history.rows[0][2] == "MERGE"
    cdf = inspector.delta("cdf")
    assert cdf.rows == [["1", "1", "128 B"]]
    assert "yes" in cdf.details[0]
    rowgroups = inspector.delta("rowgroups")
    assert rowgroups.rows[0][0] == "region=eu/part-001.parquet"


def test_delta_snapshot_can_start_from_parquet_checkpoint(tmp_path):
    root, _, active = delta_fixture(tmp_path)
    log = root / "_delta_log"
    schema_string = json.loads(
        next(
            json.loads(line)["metaData"]["schemaString"]
            for line in (log / "00000000000000000000.json").read_text().splitlines()
            if "metaData" in json.loads(line)
        )
    )
    protocol_type = pa.struct([
        ("minReaderVersion", pa.int32()), ("minWriterVersion", pa.int32())
    ])
    metadata_type = pa.struct([
        ("id", pa.string()), ("name", pa.string()), ("description", pa.string()),
        ("schemaString", pa.string()), ("partitionColumns", pa.list_(pa.string())),
        ("configuration", pa.map_(pa.string(), pa.string())),
    ])
    add_type = pa.struct([
        ("path", pa.string()), ("size", pa.int64()),
        ("partitionValues", pa.map_(pa.string(), pa.string())),
        ("modificationTime", pa.int64()), ("stats", pa.string()),
    ])
    checkpoint = pa.table({
        "protocol": pa.array([
            {"minReaderVersion": 1, "minWriterVersion": 2}, None, None
        ], type=protocol_type),
        "metaData": pa.array([
            None,
            {
                "id": "table-id", "name": "sales", "description": "Sales table",
                "schemaString": json.dumps(schema_string), "partitionColumns": ["region"],
                "configuration": [("delta.enableChangeDataFeed", "true")],
            },
            None,
        ], type=metadata_type),
        "add": pa.array([
            None, None,
            {
                "path": "region=eu/part-001.parquet", "size": active.stat().st_size,
                "partitionValues": [("region", "eu")], "modificationTime": 2000,
                "stats": json.dumps({"numRecords": 3}),
            },
        ], type=add_type),
    })
    pq.write_table(checkpoint, log / "00000000000000000001.checkpoint.parquet")
    (log / "00000000000000000000.json").unlink()
    (log / "00000000000000000001.json").unlink()

    snapshot = DeltaLog(root).snapshot()

    assert snapshot.version == 1
    assert snapshot.paths == [active]
    assert snapshot.metadata["configuration"]["delta.enableChangeDataFeed"] == "true"
