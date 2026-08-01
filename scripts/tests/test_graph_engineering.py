"""Pure v4.2 Graph Engineering contract tests."""

from decimal import Decimal

import pytest
import re

from lib.graph_compiler import (
    compile_definition,
    ExpressionContractError,
    evaluate_expression_ast,
    validate_expression_ast,
)
from lib.graph_definition_api import _is_version_number_conflict, _prepare_topology_inputs
from lib.graph_contracts import CompletionContractError, completion_request_digest
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


def test_expression_ast_rejects_ignored_fields_and_string_type_coercion():
    extra = {"op": "eq", "left": {"op": "literal", "value": 1},
             "right": {"op": "literal", "value": 1}, "metadata": "ignored"}
    assert any(item["code"] == "EXPRESSION_FIELD_UNSUPPORTED" for item in validate_expression_ast(extra))
    starts_with_number = {
        "op": "starts_with", "left": {"op": "literal", "value": 12},
        "right": {"op": "literal", "value": "1"},
    }
    assert any(item["code"] == "EXPRESSION_TYPE_MISMATCH" for item in validate_expression_ast(starts_with_number))


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


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ({"op": "eq"}, "EXPRESSION_OPERAND_MISSING"),
        ({"op": "eq", "left": {}, "right": {"op": "literal", "value": 1}}, "EXPRESSION_CHILD"),
        ({"op": "and", "args": ["READY"]}, "EXPRESSION_CHILD"),
        ({"op": "in", "left": {"op": "literal", "value": "READY"},
          "right": {"op": "literal", "value": None}}, "EXPRESSION_CONTAINER_INVALID"),
        ({"op": "eq", "left": {"op": "literal", "value": 1},
          "right": {"op": "literal", "value": "1"}}, "EXPRESSION_TYPE_MISMATCH"),
        ({"op": "div", "left": {"op": "literal", "value": 1},
          "right": {"op": "literal", "value": 0}}, "EXPRESSION_DIVISION_BY_ZERO"),
    ],
)
def test_expression_ast_rejects_invalid_arity_types_and_containers(expression, code):
    assert any(item["code"] == code for item in validate_expression_ast(expression))


def test_expression_evaluation_wraps_native_type_errors_in_graph_contract_error():
    with pytest.raises(ExpressionContractError) as error:
        evaluate_expression_ast(
            {"op": "in", "left": {"op": "ref", "path": "state.value"},
             "right": {"op": "ref", "path": "state.missing"}},
            {"state": {"value": "READY", "missing": None}},
        )
    assert error.value.diagnostic["code"] == "EXPRESSION_CONTAINER_INVALID"
    with pytest.raises(ExpressionContractError) as error:
        evaluate_expression_ast(
            {"op": "gt", "left": {"op": "ref", "path": "state.value"},
             "right": {"op": "literal", "value": 1}},
            {"state": {"value": "READY"}},
        )
    assert error.value.diagnostic["code"] == "EXPRESSION_TYPE_MISMATCH"


@pytest.mark.parametrize(
    ("nodes", "edges", "message"),
    [
        ([{"node_key": "a"}, "bad"], [], "nodes[1]"),
        ([{"node_key": "a", "node_id": "N1"}, {"node_key": "b", "node_id": "N1"}], [], "node_id"),
        ([{"node_key": "a"}], [{"edge_id": "E1", "source_node_key": "a", "target_node_key": "a"},
                                {"edge_id": "E1", "source_node_key": "a", "target_node_key": "a"}], "edge_id"),
        ([{"node_key": "a"}], [{"edge_id": "E1", "source_node_key": "a", "target_node_key": "missing"}], "unknown node"),
        ([{"node_key": "a"}], [{"edge_id": "E1", "source_node_key": "a", "target_node_key": "a", "order_index": 1.5}], "order_index"),
    ],
)
def test_definition_topology_rejects_invalid_identity_and_order(nodes, edges, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        _prepare_topology_inputs(nodes, edges)


def test_completion_digest_is_order_stable_and_changes_for_different_evidence():
    first = completion_request_digest({"result": 1, "meta": {"a": True, "b": 2}}, {"tokens": 3})
    second = completion_request_digest({"meta": {"b": 2, "a": True}, "result": 1}, {"tokens": 3})
    different = completion_request_digest({"result": 1}, {"tokens": 4})
    assert first == second
    assert first != different


def test_completion_digest_rejects_non_json_and_non_object_payloads():
    with pytest.raises(CompletionContractError) as error:
        completion_request_digest({"value": float("nan")}, {})
    assert error.value.diagnostic["code"] == "COMPLETION_PAYLOAD_NOT_JSON"
    with pytest.raises(CompletionContractError) as error:
        completion_request_digest([], {})
    assert error.value.diagnostic["code"] == "COMPLETION_OUTPUT_OBJECT_REQUIRED"


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


@pytest.mark.parametrize(
    "message",
    [
        'duplicate key value violates unique constraint "graph_versions_graph_id_version_no_key"',
        'ORA-00001: unique constraint (AIADMIN.UK_GRAPH_VERSION_NO) violated',
        'unique violation on GRAPH_ID, VERSION_NO',
    ],
)
def test_definition_retry_only_accepts_version_number_races(message):
    assert _is_version_number_conflict(Exception(message)) is True


def test_definition_retry_does_not_hide_other_unique_errors():
    assert _is_version_number_conflict(
        Exception('duplicate key value violates unique constraint "graph_nodes_node_id_key"')
    ) is False
