"""Unity Catalog navigation and metadata reports."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from .remote import RemoteError, RemoteReport


@dataclass(frozen=True)
class CatalogItem:
    kind: str
    name: str
    full_name: str
    details: dict[str, str] = field(default_factory=dict)


class DatabricksCatalog:
    """Small, UI-independent adapter around the Unity Catalog SDK APIs."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def catalogs(self) -> list[CatalogItem]:
        return sorted(
            (
                CatalogItem("catalog", item.name, item.name)
                for item in self.client.catalogs.list()
                if item.name
            ),
            key=lambda item: item.name.casefold(),
        )

    def workspace_items(self, path: str = "/") -> list[CatalogItem]:
        items = []
        for item in self.client.workspace.list(path):
            remote_path = item.path or ""
            kind = _label(getattr(item, "object_type", None) or "file").lower()
            if kind in {"directory", "repo"}:
                kind = "workspace_directory"
            else:
                kind = "workspace_item"
            items.append(
                CatalogItem(
                    kind,
                    remote_path.rstrip("/").rsplit("/", 1)[-1] or remote_path,
                    remote_path,
                    {
                        "object type": _label(
                            getattr(item, "object_type", None) or "file"
                        ),
                        "language": _label(getattr(item, "language", None) or ""),
                    },
                )
            )
        return sorted(items, key=lambda item: (item.kind != "workspace_directory", item.name.casefold()))

    def export_workspace_item(self, item: CatalogItem) -> bytes:
        from databricks.sdk.service.workspace import ExportFormat

        object_type = item.details.get("object type", "").upper()
        if object_type == "NOTEBOOK":
            response = self.client.workspace.export(
                item.full_name, format=ExportFormat.SOURCE
            )
            if not response.content:
                raise RemoteError("Databricks returned no notebook content")
            return base64.b64decode(response.content)

        file_path = item.full_name
        if not file_path.startswith(("/Workspace/", "/Volumes/")):
            file_path = "/Workspace" + file_path
        response = self.client.files.download(file_path)
        if response.contents is None:
            raise RemoteError("Databricks returned no file content")
        return response.contents.read()

    def jobs(self) -> list[CatalogItem]:
        items = []
        for job in self.client.jobs.list(limit=100):
            job_id = str(job.job_id)
            name = getattr(getattr(job, "settings", None), "name", None) or f"Job {job_id}"
            items.append(CatalogItem("job", name, job_id, {"job ID": job_id}))
        return sorted(items, key=lambda item: item.name.casefold())

    def clusters(self) -> list[CatalogItem]:
        items = []
        for cluster in self.client.clusters.list():
            cluster_id = cluster.cluster_id or ""
            items.append(
                CatalogItem(
                    "cluster",
                    cluster.cluster_name or cluster_id,
                    cluster_id,
                    {
                        "state": _label(getattr(cluster, "state", None) or "unknown"),
                        "runtime": getattr(cluster, "spark_version", None) or "—",
                        "creator": getattr(cluster, "creator_user_name", None) or "—",
                        "access mode": _label(
                            getattr(cluster, "data_security_mode", None) or "—"
                        ),
                    },
                )
            )
        return sorted(items, key=lambda item: item.name.casefold())

    def warehouses(self) -> list[CatalogItem]:
        items = []
        for warehouse in self.client.warehouses.list():
            warehouse_id = warehouse.id or ""
            items.append(
                CatalogItem(
                    "warehouse",
                    warehouse.name or warehouse_id,
                    warehouse_id,
                    {
                        "state": _label(getattr(warehouse, "state", None) or "unknown"),
                        "size": getattr(warehouse, "cluster_size", None) or "—",
                        "type": _label(
                            getattr(warehouse, "warehouse_type", None) or "—"
                        ),
                    },
                )
            )
        return sorted(items, key=lambda item: item.name.casefold())

    def pipelines(self) -> list[CatalogItem]:
        items = []
        for pipeline in self.client.pipelines.list_pipelines(max_results=100):
            pipeline_id = pipeline.pipeline_id or ""
            items.append(
                CatalogItem(
                    "pipeline",
                    pipeline.name or pipeline_id,
                    pipeline_id,
                    {
                        "state": _label(getattr(pipeline, "state", None) or "unknown"),
                        "creator": getattr(pipeline, "creator_user_name", None) or "—",
                    },
                )
            )
        return sorted(items, key=lambda item: item.name.casefold())

    def runs(self, job_id: str) -> list[CatalogItem]:
        items = []
        for run in self.client.jobs.list_runs(job_id=int(job_id), limit=25):
            run_id = str(run.run_id)
            state = getattr(run, "state", None)
            lifecycle = _label(getattr(state, "life_cycle_state", None) or "unknown")
            result = _label(getattr(state, "result_state", None) or "")
            label = f"{run_id} · {result or lifecycle}"
            items.append(
                CatalogItem(
                    "run",
                    label,
                    run_id,
                    {"run ID": run_id, "state": lifecycle, "result": result or "—"},
                )
            )
        return items

    def item_report(self, item: CatalogItem) -> RemoteReport:
        return RemoteReport(
            f"Databricks · {item.name}",
            ["property", "value"],
            [["type", item.kind], ["identifier", item.full_name]]
            + [[key, value] for key, value in item.details.items()],
        )

    def schemas(self, catalog: str) -> list[CatalogItem]:
        return sorted(
            (
                CatalogItem("schema", item.name, f"{catalog}.{item.name}")
                for item in self.client.schemas.list(catalog_name=catalog)
                if item.name
            ),
            key=lambda item: item.name.casefold(),
        )

    def tables(self, schema_name: str) -> list[CatalogItem]:
        catalog, schema = _schema_parts(schema_name)
        return sorted(
            (
                CatalogItem(
                    _label(getattr(item, "table_type", None) or "table").lower(),
                    item.name,
                    getattr(item, "full_name", None) or f"{catalog}.{schema}.{item.name}",
                    {"resource": "table"},
                )
                for item in self.client.tables.list(
                    catalog_name=catalog, schema_name=schema
                )
                if item.name
            ),
            key=lambda item: item.name.casefold(),
        )

    def describe(self, table_name: str) -> RemoteReport:
        table = self.client.tables.get(table_name)
        rows = [
            [
                column.name or "—",
                str(
                    getattr(column, "type_text", None)
                    or getattr(column, "type_name", None)
                    or "—"
                ),
                "yes" if getattr(column, "nullable", True) else "no",
                getattr(column, "comment", None) or "",
            ]
            for column in (table.columns or [])
        ]
        details = [
            f"Type: {_label(getattr(table, 'table_type', None) or '—')}",
            f"Owner: {getattr(table, 'owner', None) or '—'}",
            f"Format: {_label(getattr(table, 'data_source_format', None) or '—')}",
        ]
        if getattr(table, "storage_location", None):
            details.append(f"Location: {table.storage_location}")
        if getattr(table, "comment", None):
            details.append(f"Comment: {table.comment}")
        return RemoteReport(
            f"Table · {table_name}", ["column", "type", "nullable", "comment"], rows, details
        )


def _schema_parts(value: str) -> tuple[str, str]:
    parts = value.split(".")
    if len(parts) != 2 or not all(parts):
        raise RemoteError("Use a catalog.schema name")
    return parts[0], parts[1]


def _label(value: Any) -> str:
    return str(getattr(value, "value", value))


def validate_table_name(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3 or not all(parts):
        raise RemoteError("Use a catalog.schema.table name")
    return ".".join(parts)
