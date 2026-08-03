"""Pure Dynamic Graph v1 operation tests."""

import pytest

from lib.graph_dynamic import _child_topology, apply_operations, assess_risk, normalize_operations


def _source():
    return {"nodes": [{"node_key": "start", "node_type": "START"}, {"node_key": "end", "node_type": "END"}],
            "edges": [{"edge_id": "e1", "source_node_key": "start", "target_node_key": "end"}], "budget": {"max_calls": 2}}


def test_dynamic_operations_create_new_topology_without_mutating_source():
    source = _source()
    target = apply_operations(source, [{"op": "ADD_NODE", "node": {"node_key": "review", "node_type": "HUMAN"}},
                                       {"op": "REPLACE_EDGE", "edge_id": "e1", "edge": {"source_node_key": "start", "target_node_key": "review"}},
                                       {"op": "ADD_EDGE", "edge": {"edge_id": "e2", "source_node_key": "review", "target_node_key": "end"}}])
    assert len(source["nodes"]) == 2
    assert {item["node_key"] for item in target["nodes"]} == {"start", "review", "end"}
    assert {item["edge_id"] for item in target["edges"]} == {"e1", "e2"}


def test_dynamic_risk_requires_governance_for_scope_or_effect_expansion():
    target = apply_operations(_source(), [{"op": "REPLACE_NODE", "node_key": "start", "node": {"node_type": "AGENT", "side_effect_class": "NON_IDEMPOTENT", "resource_scope": {"classification": "RESTRICTED"}}}])
    risk = assess_risk(_source(), target)
    assert risk["level"] == "HIGH"
    assert risk["requires_approval"] is True


def test_dynamic_child_removes_global_storage_ids():
    nodes, edges = _child_topology({"nodes": [{"node_id": "old-node", "node_key": "start"}],
                                    "edges": [{"edge_id": "old-edge", "source_node_key": "start", "target_node_key": "end"}]})
    assert nodes[0]["node_key"] == "start" and "node_id" not in nodes[0]
    assert edges[0]["source_node_key"] == "start" and "edge_id" not in edges[0]


def test_dynamic_operations_reject_unknown_or_unsafe_shape():
    with pytest.raises(ValueError):
        normalize_operations([{"op": "EXECUTE_PYTHON", "code": "x"}])
    with pytest.raises(ValueError):
        apply_operations(_source(), [{"op": "REMOVE_NODE", "node_key": "missing"}])
