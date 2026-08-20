import pytest

from notebookvim.spark_evaluator import SparkEvaluationError, evaluate_spark


def test_evaluate_spark_classifies_transformations_shuffles_and_actions(tmp_path):
    path = tmp_path / "job.py"
    path.write_text(
        """def transform(spark):
    customers = spark.table("customers").filter("active")
    orders = spark.read.parquet("orders")
    result = customers.join(orders, "customer_id").groupBy("region").count()
    result.repartition(8).write.format("delta").save("output")
    return result
""",
        encoding="utf-8",
    )

    result = evaluate_spark(path)

    by_name = [(item.name, item.category, item.shuffle, item.execution) for item in result.operations]
    assert ("table()", "source", "none", "lazy") in by_name
    assert ("filter()", "narrow transformation", "none", "lazy") in by_name
    assert ("join()", "join", "probable", "lazy") in by_name
    assert ("count()", "wide transformation", "definite", "lazy") in by_name
    assert ("repartition()", "partitioning", "definite", "lazy") in by_name
    assert ("save()", "action", "none", "action") in by_name
    assert result.likely_shuffles == 3
    assert result.actions == 1
    assert "⇄ probable shuffle" in result.graph
    assert "▶ action" in result.graph


def test_evaluate_spark_marks_embedded_sql_shuffle_as_probable(tmp_path):
    path = tmp_path / "query.py"
    path.write_text(
        'result = spark.sql("SELECT region, count(*) FROM sales GROUP BY region")\n',
        encoding="utf-8",
    )

    result = evaluate_spark(path)

    assert result.operations[0].category == "SQL"
    assert result.operations[0].shuffle == "probable"


def test_evaluate_spark_requires_python_file(tmp_path):
    path = tmp_path / "query.sql"
    path.write_text("SELECT 1\n", encoding="utf-8")

    with pytest.raises(SparkEvaluationError, match="Python"):
        evaluate_spark(path)


def test_evaluate_spark_ignores_similarly_named_regular_python_calls(tmp_path):
    path = tmp_path / "mixed.py"
    path.write_text(
        "values = [1, 2, 3]\n"
        "ordinary_count = values.count(1)\n"
        "df = spark.table('sales')\n"
        "spark_count = df.count()\n",
        encoding="utf-8",
    )

    result = evaluate_spark(path)

    assert [item.name for item in result.operations].count("count()") == 1
