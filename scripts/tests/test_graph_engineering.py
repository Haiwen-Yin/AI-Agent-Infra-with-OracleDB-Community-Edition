"""Pure v4.2 Graph Engineering contract tests."""

from decimal import Decimal

import pytest

from lib.graph_compiler import (
    compile_definition,
    evaluate_expression_ast,
    validate_expression_ast,
)
from lib.graph_compat import (
    _portable_digest,
    graph_status,
    legacy_history_reference,
    loop_definition,
    task_plan_definition,
)


def _linear_graph(**overrides):
    definition = {
        "graph_version_id": "GV_TEST",
        "budget": {},
        "nodes": [
            {"node_key": "start", "node_type": "START"},
            {"node_key": "work", "node_type": "AGENT", "side_effect_class": "NONE"},
            {"node_key": "end", "node_type": "END"},
        ],
        "edges": [
            {"edge_id": "e1", "source_node_key": "start", "target_node_key": "work"},
            {"edge_id": "e2", "source_node_key": "work", "target_node_key": "end"},
        ],
    }
    definition.update(overrides)
    return definition


def test_valid_graph_compiles_deterministically():
    first = compile_definition(_linear_graph())
    second = compile_definition(_linear_graph())
    assert first["valid"] is True
    assert first["definition_digest"] == second["definition_digest"]
    assert first["plan_digest"] == second["plan_digest"]
    assert first["plan"]["entry_node"] == "start"


def test_unreachable_and_dead_end_nodes_are_rejected():
    result = compile_definition(_linear_graph(nodes=[
        {"node_key": "start", "node_type": "START"},
        {"node_key": "end", "node_type": "END"},
        {"node_key": "orphan", "node_type": "AGENT"},
    ], edges=[{"edge_id": "e1", "source_node_key": "start", "target_node_key": "end"}]))
    codes = {item["code"] for item in result["diagnostics"]}
    assert "NODE_UNREACHABLE" in codes
    assert "NODE_DEAD_END" in codes


def test_cycle_requires_hard_budget():
    graph = _linear_graph(
        budget={"max_iterations": 4},
        edges=[
            {"edge_id": "e1", "source_node_key": "start", "target_node_key": "work"},
            {"edge_id": "e2", "source_node_key": "work", "target_node_key": "work"},
            {"edge_id": "e3", "source_node_key": "work", "target_node_key": "end"},
        ],
    )
    assert compile_definition(graph)["valid"] is True
    graph["budget"] = {}
    invalid = compile_definition(graph)
    assert any(item["code"] == "CYCLE_UNBOUNDED" for item in invalid["diagnostics"])


def test_expression_ast_rejects_code_execution_surfaces():
    invalid = {"op": "eq", "left": {"op": "ref", "path": "environment.SECRET"}, "right": {"op": "literal", "value": "x"}}
    diagnostics = validate_expression_ast(invalid)
    assert any(item["code"] == "EXPRESSION_REF_SCOPE" for item in diagnostics)
    unsafe = {"op": "literal", "value": "sql:select * from secrets"}
    assert any(item["code"] == "EXPRESSION_FORBIDDEN" for item in validate_expression_ast(unsafe))


def test_expression_ast_is_typed_and_context_scoped():
    expression = {
        "op": "and",
        "args": [
            {"op": "eq", "left": {"op": "ref", "path": "state.status"}, "right": {"op": "literal", "value": "READY"}},
            {"op": "gte", "left": {"op": "ref", "path": "budget.calls"}, "right": {"op": "literal", "value": 1}},
        ],
    }
    assert validate_expression_ast(expression) == []
    assert evaluate_expression_ast(expression, {"state": {"status": "READY"}, "budget": {"calls": 2}}) is True


def test_non_idempotent_effect_is_high_risk():
    result = compile_definition(_linear_graph(nodes=[
        {"node_key": "start", "node_type": "START"},
        {"node_key": "charge", "node_type": "HTTP_API", "side_effect_class": "NON_IDEMPOTENT"},
        {"node_key": "end", "node_type": "END"},
    ], edges=[
        {"edge_id": "e1", "source_node_key": "start", "target_node_key": "charge"},
        {"edge_id": "e2", "source_node_key": "charge", "target_node_key": "end"},
    ]))
    assert result["valid"] is True
    assert result["risk_level"] == "HIGH"


def test_legacy_status_and_history_mapping_is_conservative():
    assert graph_status("COMPLETED") == "SUCCEEDED"
    assert graph_status("unknown-old-status") == "REVIEW_REQUIRED"
    reference = legacy_history_reference("TASK_PLAN", "PLAN_OLD", "COMPLETED")
    assert reference["status"] == "SUCCEEDED"
    assert reference["history_class"] == "READ_ONLY_LEGACY"
    assert reference["topology_status"] == "REVIEW_REQUIRED"
    assert reference["replay_supported"] is False
    assert "infer Graph edges" in reference["migration_note"]


def test_task_plan_wrapper_has_explicit_compatibility_topology():
    definition = task_plan_definition(
        {"plan_id": "PLAN_1", "goal": "ship", "agent_id": "AGENT_1"},
        [
            {"step_id": "STEP_2", "step_order": 2, "description": "second"},
            {"step_id": "STEP_1", "step_order": 1, "description": "first", "tool_name": "lint"},
        ],
    )
    assert [node["node_key"] for node in definition["nodes"]] == [
        "start", "task:STEP_1", "task:STEP_2", "end"
    ]
    assert [(edge["source_node_key"], edge["target_node_key"]) for edge in definition["edges"]] == [
        ("start", "task:STEP_1"), ("task:STEP_1", "task:STEP_2"), ("task:STEP_2", "end")
    ]


def test_loop_wrapper_declares_bounded_cycle_and_end_route():
    definition = loop_definition({
        "loop_id": "LOOP_1",
        "goal_definition": {"goal": "review"},
        "stop_conditions": {"max_iterations": 3},
        "evaluation_config": {"eval_type": "MANUAL"},
    })
    assert definition["budget"] == {"max_iterations": 3}
    cycle = next(edge for edge in definition["edges"] if edge["edge_kind"] == "CYCLE")
    end = next(edge for edge in definition["edges"] if edge["target_node_key"] == "end")
    assert cycle["source_node_key"] == cycle["target_node_key"] == "loop"
    assert end["decision_type"] == "EXPRESSION"


def test_loop_wrapper_evaluator_metadata_is_not_execution_code():
    result = compile_definition(loop_definition({
        "loop_id": "LOOP_EVALUATOR",
        "goal_definition": {"goal": "review"},
        "stop_conditions": {"max_iterations": 3},
        "evaluation_config": {"eval_type": "TEST", "success_exit_code": 0},
    }))
    assert result["valid"] is True


def test_compatibility_digest_normalizes_nested_driver_decimals():
    decimal_definition = {
        "schema_version": "1.0",
        "input_schema": {"minimum": Decimal("3.00")},
        "output_schema": {},
        "budget": {"max_cost": Decimal("12.5000")},
        "nodes": [{
            "node_key": "work", "node_type": "AGENT",
            "config": {"threshold": Decimal("0.1250")},
            "input_schema": {}, "output_schema": {}, "capabilities": [],
            "resource_scope": {}, "budget": {"max_calls": Decimal("4.00")},
        }],
        "edges": [{
            "edge_id": "edge", "source_node_key": "work", "target_node_key": "work",
            "condition": {"limit": Decimal("2.50")}, "config": {}, "order_index": Decimal("0"),
        }],
    }
    json_definition = {
        **decimal_definition,
        "input_schema": {"minimum": 3},
        "budget": {"max_cost": 12.5},
        "nodes": [{
            **decimal_definition["nodes"][0],
            "config": {"threshold": 0.125},
            "budget": {"max_calls": 4},
        }],
        "edges": [{
            **decimal_definition["edges"][0],
            "condition": {"limit": 2.5}, "order_index": 0,
        }],
    }
    assert _portable_digest(decimal_definition) == _portable_digest(json_definition)


def test_compatibility_digest_rejects_non_finite_decimal():
    with pytest.raises(ValueError, match="non-finite"):
        _portable_digest({"budget": {"max_cost": Decimal("NaN")}})


def test_loop_wrapper_normalizes_driver_decimal_budgets_before_persistence():
    definition = loop_definition({
        "loop_id": "LOOP_DECIMAL",
        "stop_conditions": {
            "max_iterations": Decimal("2.00"),
            "max_duration_seconds": Decimal("3600"),
        },
    })
    assert definition["budget"] == {"max_iterations": 2, "max_duration_seconds": 3600}
    assert isinstance(definition["nodes"][1]["config"]["stop_conditions"]["max_iterations"], int)
