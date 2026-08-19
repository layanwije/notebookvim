from notebookvim.databricks import databricks_kernel_code


def test_databricks_kernel_code_uses_default_authentication():
    code = databricks_kernel_code(None)

    assert "workspace = WorkspaceClient()" in code
    assert "dbutils = workspace.dbutils" in code


def test_databricks_kernel_code_quotes_profile_safely():
    code = databricks_kernel_code("team's profile")

    assert 'WorkspaceClient(profile="team\'s profile")' in code


def test_databricks_kernel_code_supports_browser_oauth():
    code = databricks_kernel_code(
        None,
        "https://example.cloud.databricks.com",
        "external-browser",
    )

    assert "host='https://example.cloud.databricks.com'" in code
    assert "auth_type='external-browser'" in code
