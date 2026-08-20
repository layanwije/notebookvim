"""Static Spark operation and shuffle evaluation without starting Spark."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class SparkEvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class SparkOperation:
    scope: str
    line: int
    name: str
    category: str
    shuffle: str
    execution: str
    note: str


@dataclass(frozen=True)
class SparkEvaluation:
    path: Path
    operations: tuple[SparkOperation, ...]

    @property
    def likely_shuffles(self) -> int:
        return sum(item.shuffle in {"definite", "probable"} for item in self.operations)

    @property
    def actions(self) -> int:
        return sum(item.execution == "action" for item in self.operations)

    @property
    def graph(self) -> str:
        if not self.operations:
            return f"{self.path.name}\n└── No recognized Spark operations"
        lines = [self.path.name]
        scopes: dict[str, list[SparkOperation]] = {}
        for operation in self.operations:
            scopes.setdefault(operation.scope, []).append(operation)
        for scope_index, (scope, operations) in enumerate(scopes.items()):
            scope_last = scope_index == len(scopes) - 1
            scope_branch = "└── " if scope_last else "├── "
            scope_prefix = "    " if scope_last else "│   "
            lines.append(scope_branch + scope)
            stage = 1
            for index, operation in enumerate(operations):
                last = index == len(operations) - 1
                branch = "└── " if last else "├── "
                label = f"L{operation.line} {operation.name}  [{operation.category}]"
                if operation.shuffle in {"definite", "probable"}:
                    label += f"  ⇄ {operation.shuffle} shuffle · stage {stage}→{stage + 1}"
                    stage += 1
                elif operation.execution == "action":
                    label += "  ▶ action"
                lines.append(scope_prefix + branch + label)
        return "\n".join(lines)


NARROW = {
    "select", "selectExpr", "filter", "where", "withColumn", "withColumns",
    "drop", "withColumnRenamed", "alias", "limit", "sample", "map", "flatMap",
    "mapPartitions", "union", "unionByName",
}
WIDE = {"agg", "distinct", "dropDuplicates", "orderBy", "sort"}
ACTIONS = {
    "collect", "count", "show", "first", "head", "take", "toPandas", "foreach",
    "foreachPartition", "save", "saveAsTable", "insertInto", "start",
}
SOURCES = {"table", "load", "csv", "json", "parquet", "orc", "jdbc", "text"}
CACHE = {"cache", "persist", "checkpoint", "localCheckpoint", "unpersist"}


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return "<dynamic>"


def _classify(name: str, node: ast.Call) -> tuple[str, str, str, str] | None:
    if name in SOURCES:
        return "source", "none", "lazy", "Data source or table read"
    if name in NARROW:
        return "narrow transformation", "none", "lazy", "Partition-local transformation"
    if name in WIDE:
        return "wide transformation", "definite", "lazy", "Redistribution or global ordering likely required"
    if name in {"groupBy", "groupby"}:
        return "grouping", "none", "lazy", "Defines grouping; its aggregation creates the shuffle boundary"
    if name == "count" and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
        if _call_name(node.func.value) in {"groupBy", "groupby"}:
            return "wide transformation", "definite", "lazy", "Grouped aggregation requires redistribution"
    if name in {"repartition", "repartitionByRange"}:
        return "partitioning", "definite", "lazy", "Explicit repartition"
    if name == "coalesce":
        return "partitioning", "conditional", "lazy", "Usually narrows partitions; shuffle depends on usage"
    if name in {"join", "cogroup"}:
        return "join", "probable", "lazy", "Strategy depends on hints, sizes, statistics, and AQE"
    if name == "crossJoin":
        return "join", "definite", "lazy", "Cartesian join can expand data dramatically"
    if name == "broadcast":
        return "join hint", "none", "lazy", "Requests broadcast; Spark may reject unsupported strategy"
    if name == "over":
        return "window", "probable", "lazy", "Window partitioning or ordering commonly shuffles"
    if name in CACHE:
        return "persistence", "none", "lazy", "Affects reuse; materialized only by an action"
    if name in ACTIONS:
        note = "Moves data to the driver" if name in {"collect", "toPandas"} else "Triggers Spark execution"
        return "action", "none", "action", note
    if name in {"write", "writeStream"}:
        return "write builder", "none", "lazy", "A later save/start call triggers execution"
    if name == "sql" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        sql = node.args[0].value.upper()
        shuffle = "probable" if any(word in sql for word in (" JOIN ", " GROUP BY ", " ORDER BY ", " DISTINCT ")) else "runtime-dependent"
        return "SQL", shuffle, "lazy", "Embedded SQL; exact plan requires Spark analysis"
    return None


class _SparkVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope = "<module>"
        self.operations: list[SparkOperation] = []
        self.spark_values: set[str] = {"spark", "sc", "sqlContext"}

    def _root_name(self, node: ast.AST) -> str | None:
        while isinstance(node, (ast.Call, ast.Attribute, ast.Subscript)):
            if isinstance(node, ast.Call):
                node = node.func
            elif isinstance(node, ast.Attribute):
                node = node.value
            else:
                node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def _spark_expression(self, node: ast.AST) -> bool:
        root = self._root_name(node)
        return bool(
            root in self.spark_values
            or root in {"Window", "F", "functions"}
            or (root and root.lower().endswith(("df", "dataframe", "rdd")))
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        if self._spark_expression(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.spark_values.add(target.id)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            if isinstance(node.target, ast.Name) and self._spark_expression(node.value):
                self.spark_values.add(node.target.id)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.scope
        self.scope = f"{node.name}()"
        for statement in node.body:
            self.visit(statement)
        self.scope = previous

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Post-order makes chained calls appear in receiver-to-result order.
        self.generic_visit(node)
        name = _call_name(node)
        if not self._spark_expression(node) and not (
            name == "broadcast"
            and node.args
            and self._spark_expression(node.args[0])
        ):
            return
        classification = _classify(name, node)
        if classification is not None:
            category, shuffle, execution, note = classification
            self.operations.append(
                SparkOperation(self.scope, node.lineno, f"{name}()", category, shuffle, execution, note)
            )


def evaluate_spark(path: Path) -> SparkEvaluation:
    path = Path(path).resolve()
    if path.suffix.lower() != ".py":
        raise SparkEvaluationError("Open a Python (.py) file containing Spark code")
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SparkEvaluationError(f"Could not read {path}: {exc}") from exc
    try:
        syntax = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise SparkEvaluationError(f"Invalid Python at line {exc.lineno}: {exc.msg}") from exc
    visitor = _SparkVisitor()
    visitor.visit(syntax)
    return SparkEvaluation(path, tuple(visitor.operations))
