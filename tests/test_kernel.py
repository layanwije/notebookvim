import pytest

from notebookvim.kernel import Kernel, kernel_environment
from notebookvim.model import Cell, CellType, DisplayOutput, ExecutionState


@pytest.mark.asyncio
async def test_kernel_preserves_state_between_cells():
    kernel = Kernel(timeout=30)
    updates = []

    async def update(event):
        updates.append(event)

    first = Cell(CellType.CODE, "answer = 40")
    second = Cell(CellType.CODE, "answer + 2")
    try:
        assert await kernel.execute(first, update)
        assert await kernel.execute(second, update)
    finally:
        await kernel.shutdown()

    assert second.execution_state is ExecutionState.SUCCEEDED
    results = [output for output in second.outputs if isinstance(output, DisplayOutput)]
    assert results[-1].data["text/plain"] == "42"


def test_kernel_discovers_spark_python_paths(tmp_path, monkeypatch):
    install_root = tmp_path / "spark"
    spark_home = install_root / "libexec"
    spark_submit = install_root / "bin" / "spark-submit"
    pyspark = spark_home / "python" / "pyspark"
    py4j = spark_home / "python" / "lib" / "py4j-test.zip"
    spark_submit.parent.mkdir(parents=True)
    spark_submit.touch()
    pyspark.mkdir(parents=True)
    py4j.parent.mkdir(parents=True)
    py4j.touch()

    monkeypatch.delenv("SPARK_HOME", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr("notebookvim.kernel.shutil.which", lambda command: str(spark_submit))

    environment = kernel_environment()

    assert environment["SPARK_HOME"] == str(spark_home)
    paths = environment["PYTHONPATH"].split(":")
    assert str(spark_home / "python") in paths
    assert str(py4j) in paths
