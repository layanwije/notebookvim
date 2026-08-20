from types import SimpleNamespace
import base64
import io

import pytest

from notebookvim.catalog import CatalogItem, DatabricksCatalog, validate_table_name
from notebookvim.remote import RemoteError


def item(**values):
    return SimpleNamespace(**values)


class Collection:
    def __init__(self, values=None, value=None):
        self.values = values or []
        self.value = value
        self.calls = []

    def list(self, *args, **kwargs):
        self.calls.append(args or kwargs)
        return self.values

    def get(self, name):
        self.calls.append(name)
        return self.value


def test_catalog_lists_the_hierarchy_and_preserves_full_names():
    client = item(
        catalogs=Collection([item(name="main")]),
        schemas=Collection([item(name="analytics")]),
        tables=Collection(
            [
                item(
                    name="customers",
                    full_name="main.analytics.customers",
                    table_type="MANAGED",
                )
            ]
        ),
    )
    catalog = DatabricksCatalog(client)

    assert catalog.catalogs()[0].full_name == "main"
    assert catalog.schemas("main")[0].full_name == "main.analytics"
    assert catalog.tables("main.analytics")[0].full_name == "main.analytics.customers"
    assert client.schemas.calls == [{"catalog_name": "main"}]
    assert client.tables.calls == [
        {"catalog_name": "main", "schema_name": "analytics"}
    ]


def test_catalog_describe_returns_column_metadata():
    table = item(
        columns=[item(name="id", type_text="BIGINT", nullable=False, comment="key")],
        table_type="MANAGED",
        owner="data",
        data_source_format="DELTA",
        storage_location="s3://bucket/table",
        comment="Customers",
    )
    catalog = DatabricksCatalog(item(tables=Collection(value=table)))

    report = catalog.describe("main.analytics.customers")

    assert report.rows == [["id", "BIGINT", "no", "key"]]
    assert "Owner: data" in report.details


def test_explorer_lists_workspace_items_and_jobs():
    client = item(
        workspace=Collection(
            [
                item(path="/Shared", object_type="DIRECTORY"),
                item(path="/Repos/team/project", object_type="REPO"),
                item(path="/Shared/analysis.py", object_type="FILE"),
            ]
        ),
        jobs=Collection(
            [item(job_id=42, settings=item(name="Daily ingestion"))]
        ),
    )
    explorer = DatabricksCatalog(client)

    workspace = explorer.workspace_items("/")
    jobs = explorer.jobs()

    assert [entry.kind for entry in workspace] == [
        "workspace_directory", "workspace_directory", "workspace_item"
    ]
    assert jobs[0].full_name == "42"
    assert jobs[0].name == "Daily ingestion"


def test_explorer_lists_compute_and_pipelines():
    client = item(
        clusters=Collection(
            [
                item(
                    cluster_id="cluster-1",
                    cluster_name="Development",
                    state="RUNNING",
                    spark_version="17.3.x",
                    creator_user_name="user@example.com",
                    data_security_mode="SINGLE_USER",
                )
            ]
        ),
        warehouses=Collection(
            [
                item(
                    id="warehouse-1",
                    name="Analytics",
                    state="RUNNING",
                    cluster_size="Small",
                    warehouse_type="PRO",
                )
            ]
        ),
        pipelines=item(
            list_pipelines=lambda **kwargs: [
                item(
                    pipeline_id="pipeline-1",
                    name="Bronze ingestion",
                    state="IDLE",
                    creator_user_name="user@example.com",
                )
            ]
        ),
    )
    explorer = DatabricksCatalog(client)

    assert explorer.clusters()[0].details["state"] == "RUNNING"
    assert explorer.warehouses()[0].name == "Analytics"
    assert explorer.pipelines()[0].full_name == "pipeline-1"


def test_explorer_exports_workspace_notebook_source():
    class Workspace:
        def export(self, path, *, format):
            self.call = (path, format.value)
            return item(content=base64.b64encode(b"SELECT 1\n").decode())

    workspace = Workspace()
    explorer = DatabricksCatalog(item(workspace=workspace))
    remote = CatalogItem(
        "workspace_item",
        "Query",
        "/Shared/Query",
        {"object type": "NOTEBOOK", "language": "SQL"},
    )

    assert explorer.export_workspace_item(remote) == b"SELECT 1\n"
    assert workspace.call == ("/Shared/Query", "SOURCE")


def test_explorer_downloads_workspace_file_with_files_api():
    class Files:
        def download(self, path):
            self.path = path
            return item(contents=io.BytesIO(b"SELECT 2\n"))

    files = Files()
    explorer = DatabricksCatalog(item(files=files))
    remote = CatalogItem(
        "workspace_item",
        "query.sql",
        "/Users/me/query.sql",
        {"object type": "FILE", "language": ""},
    )

    assert explorer.export_workspace_item(remote) == b"SELECT 2\n"
    assert files.path == "/Workspace/Users/me/query.sql"


@pytest.mark.parametrize("name", ["table", "schema.table", "a.b.c.d", "a..c"])
def test_validate_table_name_requires_three_parts(name):
    with pytest.raises(RemoteError):
        validate_table_name(name)
