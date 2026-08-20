import pytest

from lib.execution_evidence import (
    ExecutionEvidenceError,
    build_execution_evidence,
    controlled_capability_admission,
    validate_execution_evidence,
)


def test_execution_evidence_contains_typed_runtime_facts_and_digest():
    record = build_execution_evidence(
        execution_id="RUN-1", kind="maintenance", input={"command": "check"},
        graph_run_id="GRAPH-1", fencing_token=3,
        capability_proof={"capability": "maintenance.read", "verified": True},
        budget={"max_attempts": 3, "tokens": 500},
        attempt={"number": 1}, lease={"owner": "worker", "expires_at": "2026-01-01T00:00:00Z"},
        side_effect_class="READ_ONLY", human_takeover={"available": True},
        model_provider={"provider": "test", "mode": "offline"}, model_id="model-1",
        token_budget=500, cost_budget={"currency": "USD", "maximum": 1},
        output_provenance={"digest": "a" * 64, "source": "worker"},
    )
    assert record["kind"] == "MAINTENANCE"
    assert record["graph_run_id"] == "GRAPH-1"
    assert len(record["evidence_digest"]) == 64
    assert record["model_id"] == "model-1"


def test_execution_evidence_rejects_missing_or_invalid_fencing():
    with pytest.raises(ExecutionEvidenceError):
        validate_execution_evidence({"execution_id": "x"})
    with pytest.raises(ExecutionEvidenceError):
        build_execution_evidence(execution_id="x", kind="TASK", input={}, fencing_token=-1)


def test_execution_evidence_rejects_untyped_model_budget():
    with pytest.raises(ExecutionEvidenceError):
        build_execution_evidence(execution_id="x", kind="AGENT", input={}, token_budget="unbounded")


def _controlled_proofs(capability="graph.replay"):
    commit = "a" * 40
    return {
        "configuration": {"capability": capability, "state": "CONTROLLED", "enabled": True, "configuration_version": "7"},
        "authorization": {"capability": capability, "allowed": True, "principal_id": "P1", "decision_id": "AUTH-1"},
        "live_evidence": {"capability": capability, "passed": True, "status": "HEALTHY", "evidence_digest": "b" * 64},
        "release_evidence": {"capability": capability, "passed": True, "source_commit": commit, "reviewed_source_commit": commit, "evidence_digest": "c" * 64},
    }


def test_controlled_capability_requires_all_four_independent_proofs():
    proofs = _controlled_proofs()
    decision = controlled_capability_admission("graph.replay", **proofs)
    assert decision["admitted"] is True
    assert decision["decision"] == "ADMIT"
    assert len(decision["decision_digest"]) == 64
    assert set(decision["proof_digests"]) == {
        "configuration", "authorization", "live_evidence", "release_evidence",
    }


@pytest.mark.parametrize(
    ("proof", "field", "value", "reason"),
    [
        ("configuration", "enabled", False, "CONFIGURATION_NOT_PROVEN"),
        ("authorization", "allowed", False, "AUTHORIZATION_NOT_PROVEN"),
        ("live_evidence", "status", "STALE", "LIVE_EVIDENCE_NOT_PROVEN"),
        ("release_evidence", "reviewed_source_commit", "d" * 40, "RELEASE_EVIDENCE_NOT_PROVEN"),
    ],
)
def test_controlled_capability_fails_closed_when_any_proof_is_invalid(proof, field, value, reason):
    proofs = _controlled_proofs()
    proofs[proof][field] = value
    decision = controlled_capability_admission("graph.replay", **proofs)
    assert decision["admitted"] is False
    assert decision["decision"] == "DENY"
    assert reason in decision["reasons"]


def test_controlled_capability_rejects_cross_capability_evidence():
    proofs = _controlled_proofs()
    proofs["authorization"]["capability"] = "graph.inspect"
    decision = controlled_capability_admission("graph.replay", **proofs)
    assert decision["admitted"] is False
    assert decision["reasons"] == ["AUTHORIZATION_NOT_PROVEN"]
