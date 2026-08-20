"""Databricks workspace authentication and notebook-kernel setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class DatabricksConnection:
    profile: Optional[str]
    host: str
    user_name: str
    auth_type: Optional[str] = None
    compute: Optional[str] = None
    client: Any = field(default=None, repr=False, compare=False)


def connect_databricks(
    target: Optional[str] = None, compute: Optional[str] = None
) -> DatabricksConnection:
    """Connect with Databricks unified authentication and verify the identity."""
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:
        raise RuntimeError(
            "Databricks support is not installed; run `pip install databricks-sdk`"
        ) from exc

    is_workspace_url = bool(target and target.lower().startswith(("https://", "http://")))
    if is_workspace_url:
        client = WorkspaceClient(host=target, auth_type="external-browser")
        profile = None
        auth_type = "external-browser"
    else:
        profile = target
        auth_type = None
        client = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    current_user = client.current_user.me()
    return DatabricksConnection(
        profile=profile,
        host=client.config.host or "unknown workspace",
        user_name=current_user.user_name or current_user.display_name or "unknown user",
        auth_type=auth_type,
        compute=compute,
        client=client,
    )


def databricks_client(connection: DatabricksConnection):
    """Return the authenticated SDK client retained by a connection."""
    if connection.client is not None:
        return connection.client
    from databricks.sdk import WorkspaceClient

    if connection.profile:
        return WorkspaceClient(profile=connection.profile)
    if connection.host and connection.auth_type:
        return WorkspaceClient(host=connection.host, auth_type=connection.auth_type)
    return WorkspaceClient()


def databricks_kernel_code(
    profile: Optional[str],
    host: Optional[str] = None,
    auth_type: Optional[str] = None,
    compute: Optional[str] = None,
) -> str:
    """Return silent initialization code for workspace APIs and remote Spark."""
    if profile:
        constructor = f"WorkspaceClient(profile={profile!r})"
    elif host and auth_type:
        constructor = f"WorkspaceClient(host={host!r}, auth_type={auth_type!r})"
    else:
        constructor = "WorkspaceClient()"
    code = (
        "from databricks.sdk import WorkspaceClient\n"
        f"workspace = {constructor}\n"
        "dbutils = workspace.dbutils"
    )
    if compute is None:
        return code

    if profile:
        spark_builder = f"DatabricksSession.builder.profile({profile!r})"
    elif host and auth_type:
        spark_builder = (
            "DatabricksSession.builder.sdkConfig("
            f"Config(host={host!r}, auth_type={auth_type!r}))"
        )
    else:
        spark_builder = "DatabricksSession.builder"
    if compute == "serverless":
        spark_builder += ".serverless()"
    else:
        spark_builder += f".clusterId({compute!r})"
    return (
        code
        + "\ntry:\n"
        + "    from databricks.connect import DatabricksSession\n"
        + "except ImportError as exc:\n"
        + "    raise RuntimeError(\n"
        + "        'Databricks Connect is not installed. Install a databricks-connect '\n"
        + "        'version matching the target Databricks Runtime.'\n"
        + "    ) from exc\n"
        + "from databricks.sdk.core import Config\n"
        + f"spark = {spark_builder}.getOrCreate()"
    )
