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


def test_databricks_kernel_code_configures_serverless_connect():
    code = databricks_kernel_code("Team", compute="serverless")

    assert "from databricks.connect import DatabricksSession" in code
    assert "DatabricksSession.builder.profile('Team').serverless().getOrCreate()" in code


def test_databricks_kernel_code_configures_classic_cluster_connect():
    code = databricks_kernel_code("Team", compute="0123-456789-test")

    assert ".profile('Team').clusterId('0123-456789-test').getOrCreate()" in code


def test_databricks_kernel_code_configures_browser_oauth_for_connect():
    code = databricks_kernel_code(
        None, "https://example.cloud.databricks.com", "external-browser", "serverless"
    )

    assert (
        "Config(host='https://example.cloud.databricks.com', auth_type='external-browser')"
        in code
    )
    assert ".serverless().getOrCreate()" in code
