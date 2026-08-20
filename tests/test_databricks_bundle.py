from pathlib import Path

import pytest

from notebookvim.databricks_bundle import BundleError, visualize_bundle


def test_visualize_bundle_resolves_includes_dependencies_and_default_target(tmp_path):
    (tmp_path / "databricks.yml").write_text(
        """bundle:
  name: sales
include:
  - resources/*.yml
targets:
  dev:
    default: true
    resources:
      jobs:
        refresh:
          tasks:
            - task_key: publish
              depends_on:
                - task_key: transform
              notebook_task:
                notebook_path: ../publish.py
""",
        encoding="utf-8",
    )
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "jobs.yml").write_text(
        """resources:
  jobs:
    refresh:
      tasks:
        - task_key: extract
          notebook_task:
            notebook_path: ../extract.py
        - task_key: transform
          depends_on:
            - task_key: extract
          spark_python_task:
            python_file: ../transform.py
  pipelines:
    customer_pipeline:
      name: Customer pipeline
""",
        encoding="utf-8",
    )

    result = visualize_bundle(tmp_path / "databricks.yml")

    assert result.name == "sales"
    assert result.target == "dev"
    assert [task.task_key for task in result.tasks] == ["publish"]
    assert result.tasks[0].depends_on == ("transform",)
    assert result.graph == "refresh\n└── publish  [notebook]"
    assert result.pipelines == ("customer_pipeline",)
    assert [path.name for path in result.files] == ["databricks.yml", "jobs.yml"]
    assert result.warnings == ("refresh.publish depends on missing task transform",)


def test_visualize_bundle_uses_base_tasks_and_reports_missing_dependency(tmp_path):
    path = tmp_path / "databricks.yml"
    path.write_text(
        """bundle:
  name: sample
resources:
  jobs:
    workflow:
      tasks:
        - task_key: load
          depends_on:
            - task_key: absent
          notebook_task:
            notebook_path: ./load.py
""",
        encoding="utf-8",
    )

    result = visualize_bundle(path)

    assert result.target is None
    assert result.tasks[0].source == "./load.py"
    assert result.warnings == ("workflow.load depends on missing task absent",)


def test_visualize_bundle_requires_root_filename(tmp_path):
    path = tmp_path / "bundle.yml"
    path.write_text("bundle: {name: sample}\n", encoding="utf-8")

    with pytest.raises(BundleError, match="databricks.yml"):
        visualize_bundle(path)
