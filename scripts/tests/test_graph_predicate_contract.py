"""Parity and injection tests for the Graph predicate pushdown boundary."""

import importlib
import sys

from lib.graph_compiler import evaluate_expression_ast


def _load_adapter(name):
    if name == "package":
        return importlib.import_module("lib.graph_adapter")
    path = {
        "oracle": "adapters.oracle.graph_adapter",
        "pg": "adapters.pg.graph_adapter",
        "yashandb": "adapters.yashandb.graph_adapter",
    }[name]
    return importlib.import_module(path)


def _expression():
    return {
        "op": "and",
        "args": [
            {"op": "eq", "left": {"op": "ref", "path": "state.status"},
             "right": {"op": "literal", "value": "READY"}},
            {"op": "in", "left": {"op": "ref", "path": "state.kind"},
             "right": {"op": "literal", "value": ["AGENT", "TOOL"]}},
        ],
    }


def test_all_adapters_compile_the_same_safe_logical_predicate():
    expression = _expression()
    context = {"state": {"status": "READY", "kind": "TOOL"}}
    assert evaluate_expression_ast(expression, context) is True
    try:
        importlib.import_module("adapters.oracle.graph_adapter")
    except ModuleNotFoundError:
        adapter_names = ("package",)
    else:
        adapter_names = ("oracle", "pg", "yashandb")
    compiled = [_load_adapter(name).compile_predicate(expression) for name in adapter_names]
    assert all(item["supported"] for item in compiled)
    assert {item["ast_digest"] for item in compiled} == {compiled[0]["ast_digest"]}
    assert all("READY" not in item["sql"] and "AGENT" not in item["sql"] for item in compiled)
    assert all(len(item["params"]) == 3 for item in compiled)


def test_unsupported_or_untrusted_predicates_fall_back_without_sql_text():
    unsafe = {"op": "literal", "value": "sql:select * from secrets"}
    unsupported = {"op": "add", "left": {"op": "literal", "value": 1},
                   "right": {"op": "literal", "value": 2}}
    try:
        importlib.import_module("adapters.oracle.graph_adapter")
    except ModuleNotFoundError:
        adapter_names = ("package",)
    else:
        adapter_names = ("oracle", "pg", "yashandb")
    for name in adapter_names:
        adapter = _load_adapter(name)
        for expression in (unsafe, unsupported):
            result = adapter.compile_predicate(expression)
            assert result["supported"] is False
            assert result["sql"] is None
            assert result["params"] == {}


def test_invalid_property_path_never_becomes_executable_sql():
    expression = {"op": "eq", "left": {"op": "ref", "path": "state.status');DROP TABLE graph_runs;--"},
                  "right": {"op": "literal", "value": "READY"}}
    try:
        importlib.import_module("adapters.oracle.graph_adapter")
    except ModuleNotFoundError:
        adapter_names = ("package",)
    else:
        adapter_names = ("oracle", "pg", "yashandb")
    for name in adapter_names:
        result = _load_adapter(name).compile_predicate(expression)
        assert result["supported"] is False
        assert "DROP TABLE" not in str(result)
