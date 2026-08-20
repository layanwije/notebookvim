import pytest

from notebookvim.execution_tree import (
    ExecutionTreeError,
    find_python_entry_points,
    visualize_python,
)


def test_visualize_python_builds_downward_tree_and_marks_unreached(tmp_path):
    path = tmp_path / "pipeline.py"
    path.write_text(
        """def extract():
    print("extract")

def transform():
    extract()
    save()

def unused():
    return 42

transform()
""",
        encoding="utf-8",
    )

    result = visualize_python(path)

    assert "pipeline.py\n└── <module>" in result.graph
    assert "transform()  L11" in result.graph
    assert "extract()  L5" in result.graph
    assert "print()  L2  · external/dynamic" in result.graph
    assert "save()  L6  · external/dynamic" in result.graph
    assert result.unreachable == ("unused",)


def test_visualize_python_resolves_self_method_and_recursion(tmp_path):
    path = tmp_path / "worker.py"
    path.write_text(
        """class Worker:
    def run(self):
        self.retry()

    def retry(self):
        self.retry()

Worker().run()
""",
        encoding="utf-8",
    )

    result = visualize_python(path)

    # The constructor/method chain is dynamic, while method bodies are still inventoried.
    assert "Worker.run" in [item.name for item in result.functions]
    retry = next(item for item in result.functions if item.name == "Worker.retry")
    assert retry.calls[0].resolved == "Worker.retry"


def test_visualize_python_rejects_invalid_source(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n", encoding="utf-8")

    with pytest.raises(ExecutionTreeError, match="Invalid Python"):
        visualize_python(path)


def test_find_python_entry_points_ranks_project_scripts_and_main_guards(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\nsample = "sample.cli:main"\n', encoding="utf-8"
    )
    (package / "cli.py").write_text(
        """def main():
    return 0

if __name__ == "__main__":
    main()
""",
        encoding="utf-8",
    )
    (package / "helpers.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (package / "__main__.py").write_text("from .cli import main\nmain()\n", encoding="utf-8")

    result = find_python_entry_points(tmp_path)

    assert result.entries[0].confidence == "certain"
    assert result.entries[0].path.name == "cli.py"
    assert result.entries[0].symbol == "main"
    assert any(item.kind == "__name__ main guard" for item in result.entries)
    assert any(item.kind == "package __main__.py" for item in result.entries)
    assert any(item.path.name == "helpers.py" and item.confidence == "possible" for item in result.entries)


def test_find_python_entry_points_uses_databricks_root_task_without_main(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    (tmp_path / "databricks.yml").write_text(
        """bundle:
  name: analytics
include:
  - resources/*.yml
""",
        encoding="utf-8",
    )
    (resources / "jobs.yml").write_text(
        """resources:
  jobs:
    daily:
      tasks:
        - task_key: ingest
          spark_python_task:
            python_file: ../ingest.py
        - task_key: publish
          depends_on:
            - task_key: ingest
          spark_python_task:
            python_file: ../publish.py
""",
        encoding="utf-8",
    )
    (tmp_path / "ingest.py").write_text(
        """def start_ingestion():
    print("start")

start_ingestion()
""",
        encoding="utf-8",
    )
    (tmp_path / "publish.py").write_text("print('publish')\n", encoding="utf-8")

    result = find_python_entry_points(tmp_path)

    entry = result.entries[0]
    assert entry.confidence == "certain"
    assert entry.path.name == "ingest.py"
    assert entry.symbol == "start_ingestion"
    assert entry.line == 4
    assert entry.kind == "Databricks root task `daily.ingest`"
    assert not any(item.path.name == "publish.py" for item in result.entries)


def test_find_python_entry_points_resolves_databricks_wheel_task(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\nrun-sample = "sample.cli:run"\n', encoding="utf-8"
    )
    (tmp_path / "databricks.yml").write_text(
        """bundle:
  name: sample
resources:
  jobs:
    wheel_job:
      tasks:
        - task_key: first
          python_wheel_task:
            package_name: sample
            entry_point: run-sample
""",
        encoding="utf-8",
    )
    (package / "cli.py").write_text("def run():\n    pass\n", encoding="utf-8")

    result = find_python_entry_points(tmp_path)

    entry = next(item for item in result.entries if item.kind.startswith("Databricks"))
    assert entry.path == (package / "cli.py").resolve()
    assert entry.symbol == "run"
    assert entry.kind == "Databricks root task `wheel_job.first`"
