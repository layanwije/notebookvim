"""Built-in project scaffolds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATA_ENGINEERING_FILES = {
    "README.md": """# Data engineering project

Databricks workspace project organized around the medallion architecture.

- `notebooks/bronze`: ingestion and raw-data normalization
- `notebooks/silver`: validation, cleansing, and conformance
- `notebooks/gold`: business-facing aggregates and outputs
- `src`: reusable Python modules
- `sql`: reusable SQL and data-quality checks
- `tests`: local unit tests
""",
    ".gitignore": """.databricks/
.nbcli/
.pytest_cache/
.venv/
__pycache__/
*.py[cod]
""",
    "requirements.txt": """# Add project-specific runtime dependencies here.
pytest
""",
    "notebooks/bronze/ingest.py": """# Databricks notebook source
# TODO: Read source data and write validated Bronze Delta tables.

from src.config import CATALOG, SCHEMA

print(f\"Bronze target: {CATALOG}.{SCHEMA}\")
""",
    "notebooks/silver/transform.py": """# Databricks notebook source
# TODO: Clean, deduplicate, and conform Bronze data into Silver tables.

from src.config import CATALOG, SCHEMA

print(f\"Silver target: {CATALOG}.{SCHEMA}\")
""",
    "notebooks/gold/publish.py": """# Databricks notebook source
# TODO: Publish business-ready Gold tables and aggregates.

from src.config import CATALOG, SCHEMA

print(f\"Gold target: {CATALOG}.{SCHEMA}\")
""",
    "src/__init__.py": "",
    "src/config.py": """import os


CATALOG = os.getenv(\"DATABRICKS_CATALOG\", \"main\")
SCHEMA = os.getenv(\"DATABRICKS_SCHEMA\", \"default\")
""",
    "sql/quality_checks.sql": """-- Add project-level data-quality assertions here.
-- Example: SELECT count(*) AS invalid_rows FROM catalog.schema.table WHERE id IS NULL;
""",
    "tests/test_config.py": """from src.config import CATALOG, SCHEMA


def test_default_target_is_configured():
    assert CATALOG
    assert SCHEMA
""",
}


@dataclass(frozen=True)
class ScaffoldResult:
    created: tuple[Path, ...]
    skipped: tuple[Path, ...]


def init_data_engineering_scaffold(root: Path) -> ScaffoldResult:
    """Create missing scaffold files without modifying anything that exists."""
    root = Path(root).resolve()
    created: list[Path] = []
    skipped: list[Path] = []
    for relative_name, content in DATA_ENGINEERING_FILES.items():
        path = root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            skipped.append(path)
        else:
            created.append(path)
    return ScaffoldResult(tuple(created), tuple(skipped))
