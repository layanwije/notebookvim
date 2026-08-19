"""Databricks workspace authentication and notebook-kernel setup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DatabricksConnection:
    profile: Optional[str]
    host: str
    user_name: str
    auth_type: Optional[str] = None


def connect_databricks(target: Optional[str] = None) -> DatabricksConnection:
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
    )


def databricks_kernel_code(
    profile: Optional[str], host: Optional[str] = None, auth_type: Optional[str] = None
) -> str:
    """Return silent initialization code that exposes workspace and dbutils."""
    if profile:
        constructor = f"WorkspaceClient(profile={profile!r})"
    elif host and auth_type:
        constructor = f"WorkspaceClient(host={host!r}, auth_type={auth_type!r})"
    else:
        constructor = "WorkspaceClient()"
    return (
        "from databricks.sdk import WorkspaceClient\n"
        f"workspace = {constructor}\n"
        "dbutils = workspace.dbutils"
    )
