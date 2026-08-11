"""Database-free v4.4 SDD contract tests."""

from lib.sdd_contracts import (
    baseline_decision,
    graph_contract_decision,
    patch_decision,
    revision_transition,
    risk_pause_decision,
    role_decision,
)


def test_baseline_requires_resolved_security_fragment():
    result = baseline_decision(
        unresolved_fragments=[{"area": "SECURITY", "waived": False}],
        required_reviews_complete=True,
        required_approvals_complete=True,
        acceptance_complete=True,
    )
    assert not result.allowed
    assert result.code == "SDD_UNRESOLVED_FRAGMENT"


def test_baseline_is_allowed_after_review_and_approval():
    result = baseline_decision(
        unresolved_fragments=[{"area": "EXPLANATORY", "waived": False}],
        required_reviews_complete=True,
        required_approvals_complete=True,
        acceptance_complete=True,
    )
    assert result.allowed


def test_approved_baseline_is_append_only():
    result = revision_transition("APPROVED_BASELINE", "WORKING_REVISION", reason="edit")
    assert not result.allowed
    assert result.code == "SDD_REVISION_TRANSITION_DENIED"


def test_expected_version_fences_concurrent_patch():
    result = patch_decision("WORKING_REVISION", 3, 4, actor_is_authorized=True)
    assert not result.allowed
    assert result.code == "SDD_VERSION_CONFLICT"


def test_graph_requires_resource_sets_and_end():
    result = graph_contract_decision(
        [{"node_key": "start", "node_type": "START", "read_set": [], "write_set": []},
         {"node_key": "worker", "node_type": "AGENT", "role_key": "CODING", "read_set": ["src"], "write_set": ["src"]},
         {"node_key": "end", "node_type": "END", "read_set": [], "write_set": []}],
        [{"source_node_key": "start", "target_node_key": "worker"},
         {"source_node_key": "worker", "target_node_key": "end"}],
    )
    assert result.allowed


def test_permission_change_requires_global_pause():
    result = risk_pause_decision("HIGH", ["PERMISSION"])
    assert result.allowed
    assert result.code == "SDD_GLOBAL_PAUSE"
    assert result.details["requires_human"]


def test_role_registry_cannot_self_escalate():
    assert role_decision("CODING", "LOW").allowed
    assert not role_decision("CODING", "HIGH").allowed
