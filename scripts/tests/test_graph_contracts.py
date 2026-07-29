"""Pure contract coverage for the v4.2 Graph Engineering boundary."""

import random

import pytest

from lib.graph_compiler import compile_definition
from lib.graph_contracts import is_valid_status_transition, worker_matches
from lib.graph_evaluators import (
    builtin_evaluator_manifests, compute_metrics, evaluate_observation,
    normalize_config, validate_manifest,
)


def _graph(nodes, edges, **extra):
    result = {
        "schema_version": "1.0",
        "graph_version_id": "CONTRACT_TEST",
        "budget": {},
        "nodes": nodes,
        "edges": edges,
    }
    result.update(extra)
    return result


def _node(key, node_type="AGENT", **extra):
    value = {"node_key": key, "node_type": node_type}
    value.update(extra)
    return value


def _edge(edge_id, source, target, **extra):
    value = {"edge_id": edge_id, "source_node_key": source, "target_node_key": target}
    value.update(extra)
    return value


def test_compiler_accepts_sequence_branch_join_cycle_and_human_shapes():
    definition = _graph(
        [_node("start", "START"), _node("left"), _node("right"),
         _node("join", "HUMAN"), _node("loop"), _node("end", "END")],
        [_edge("start-left", "start", "left", edge_kind="FAN_OUT"),
         _edge("start-right", "start", "right", edge_kind="FAN_OUT"),
         _edge("left-join", "left", "join", edge_kind="FAN_IN", join_key="j",
               config={"join_strategy": "ALL", "reducer": "APPEND"}),
         _edge("right-join", "right", "join", edge_kind="FAN_IN", join_key="j",
               config={"join_strategy": "ALL", "reducer": "APPEND"}),
         _edge("join-loop", "join", "loop"),
         _edge("loop-repeat", "loop", "loop", edge_kind="CYCLE"),
         _edge("loop-end", "loop", "end", decision_type="EXPRESSION", condition={
             "op": "ne", "left": {"op": "ref", "path": "state.repeat"},
             "right": {"op": "literal", "value": True},
         })],
        budget={"max_iterations": 3},
    )
    result = compile_definition(definition)
    assert result["valid"] is True
    assert result["plan"]["join_specs"]["join"]["strategy"] == "ALL"
    assert result["plan"]["cycle_nodes"] == ["loop"]


def test_compiler_accepts_normalized_builtin_executor_registry():
    definition = _graph(
        [_node("start", "START"), _node("work"), _node("end", "END")],
        [_edge("start-work", "start", "work"), _edge("work-end", "work", "end")],
    )
    registry = list(__import__("lib.graph_compiler", fromlist=["builtin_type_registry"]).builtin_type_registry().values())
    result = compile_definition(definition, registry=registry)
    assert result["valid"] is True


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda graph: graph["nodes"].append(_node("orphan")), "NODE_UNREACHABLE"),
        (lambda graph: graph["edges"].append(_edge("bad", "start", "missing")), "EDGE_NODE_MISSING"),
        (lambda graph: graph["edges"].append(_edge("cycle", "work", "work", edge_kind="CYCLE")), "CYCLE_UNBOUNDED"),
        (lambda graph: graph["edges"].append(_edge("unsafe", "start", "work", decision_type="EXPRESSION", condition={"op": "ref", "path": "environment.secret"})), "EXPRESSION_REF_SCOPE"),
    ],
)
def test_compiler_rejects_structural_and_security_mutations(mutation, code):
    graph = _graph(
        [_node("start", "START"), _node("work"), _node("end", "END")],
        [_edge("start-work", "start", "work"), _edge("work-end", "work", "end")],
    )
    mutation(graph)
    result = compile_definition(graph)
    assert any(item["code"] == code for item in result["diagnostics"])


def test_compiler_digest_is_stable_for_randomized_insertion_order():
    base_nodes = [_node("start", "START"), _node("a"), _node("b"), _node("end", "END")]
    base_edges = [_edge("e1", "start", "a"), _edge("e2", "a", "b"), _edge("e3", "b", "end")]
    expected = compile_definition(_graph(base_nodes, base_edges))["plan_digest"]
    randomizer = random.Random(42)
    for _ in range(25):
        nodes = list(base_nodes)
        edges = list(base_edges)
        randomizer.shuffle(nodes)
        randomizer.shuffle(edges)
        assert compile_definition(_graph(nodes, edges))["plan_digest"] == expected


def test_lifecycle_is_forward_only_after_publication():
    assert is_valid_status_transition("DRAFT", "VALIDATED")
    assert is_valid_status_transition("VALIDATED", "PUBLISHED")
    assert is_valid_status_transition("PUBLISHED", "DEPRECATED")
    assert is_valid_status_transition("DEPRECATED", "ARCHIVED")
    assert not is_valid_status_transition("PUBLISHED", "DRAFT")
    assert not is_valid_status_transition("ARCHIVED", "PUBLISHED")
    assert not is_valid_status_transition("DRAFT", "PUBLISHED")


def test_worker_match_requires_all_capabilities_and_resource_class():
    assert worker_matches(["graph", "gpu"], ["graph", "gpu"], "gpu", "python")
    assert worker_matches(["graph"], ["graph"], "python", "python")
    assert not worker_matches(["graph", "gpu"], ["graph"], "gpu", "python")
    assert not worker_matches(["graph"], ["graph"], "gpu", "python")


@pytest.mark.parametrize("evaluator", ["MANUAL", "TEST", "DIFF", "LLM_JUDGE", "SPEC_VALIDATION", "AGGREGATE"])
def test_loop_evaluator_types_have_one_versioned_contract(evaluator):
    contract = normalize_config({"eval_type": evaluator, "level": "OUTCOME"})
    assert contract["type_name"] == evaluator
    assert contract["type_version"] == "1.0"


def test_builtin_evaluator_manifests_are_complete_and_versioned():
    manifests = builtin_evaluator_manifests()
    assert {item["name"] for item in manifests} == {
        "MANUAL", "TEST", "DIFF", "LLM_JUDGE", "SPEC_VALIDATION", "AGGREGATE",
    }
    assert all(validate_manifest(item) == [] for item in manifests)
    assert validate_manifest({"name": "CUSTOM", "version": "1.0"})


def test_evaluator_requires_governed_observation_and_never_executes_code():
    assert evaluate_observation({"eval_type": "TEST"}, {})["pending"] is True
    assert evaluate_observation({"eval_type": "TEST", "success_exit_code": 0}, {"exit_code": 0})["passed"] is True
    assert evaluate_observation({"eval_type": "LLM_JUDGE", "min_score": 8}, {"score": 7})["passed"] is False
    with pytest.raises(ValueError):
        normalize_config({"eval_type": "PYTHON_EXEC"})


def test_evaluator_metrics_are_bounded_and_explainable():
    metrics = compute_metrics(
        transitions=[{"status": "COMMITTED"}, {"status": "COMMITTED"}, {"status": "FAILED"}],
        attempts=[{"node_run_id": "n1", "status": "SUCCEEDED"},
                  {"node_run_id": "n2", "status": "FAILED"},
                  {"node_run_id": "n2", "status": "SUCCEEDED"}],
        interventions=[{"action_name": "PAUSE"}],
        budget={"max_tokens": 1000}, usage={"tokens": 250}, planned_nodes=4,
    )
    assert metrics["path_efficiency"] == 0.5
    assert metrics["retry_count"] == 1
    assert metrics["reliability"] == round(2 / 3, 6)
    assert metrics["intervention_count"] == 1
    assert metrics["budget_utilization"] == {"tokens": 0.25}
