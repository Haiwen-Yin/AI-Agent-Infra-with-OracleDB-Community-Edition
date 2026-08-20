"""Typed, database-independent execution evidence for Agent and Graph work."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


REQUIRED_FIELDS = frozenset({
    "execution_id", "kind", "input_schema_version", "output_schema_version",
    "input", "output", "capability_proof", "budget", "attempt", "lease",
    "fencing_token", "side_effect_class", "compensation", "human_takeover",
})
OPTIONAL_PROVENANCE_FIELDS = frozenset({
    "model_provider", "model_id", "token_budget", "cost_budget", "output_provenance",
})
ALLOWED_KINDS = frozenset({"AGENT", "TASK", "LOOP", "MAINTENANCE", "REMEDIATION"})


class ExecutionEvidenceError(ValueError):
    pass


def controlled_capability_admission(
    capability: str,
    *,
    configuration: Mapping[str, Any] | None,
    authorization: Mapping[str, Any] | None,
    live_evidence: Mapping[str, Any] | None,
    release_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Require all four independent proofs before a CONTROLLED capability runs.

    Evidence is deliberately evaluated here rather than inferred from a UI
    capability label.  Callers persist the returned decision with the work;
    the decision itself does not grant database authority.
    """
    capability = str(capability or "").strip()
    reasons: list[str] = []
    proofs = {
        "configuration": dict(configuration or {}),
        "authorization": dict(authorization or {}),
        "live_evidence": dict(live_evidence or {}),
        "release_evidence": dict(release_evidence or {}),
    }
    if not capability:
        reasons.append("CAPABILITY_REQUIRED")
    configured = proofs["configuration"]
    if (
        configured.get("capability") != capability
        or str(configured.get("state") or "").upper() != "CONTROLLED"
        or configured.get("enabled") is not True
        or not str(configured.get("configuration_version") or "").strip()
    ):
        reasons.append("CONFIGURATION_NOT_PROVEN")
    authorized = proofs["authorization"]
    if (
        authorized.get("capability") != capability
        or authorized.get("allowed") is not True
        or not str(authorized.get("principal_id") or "").strip()
        or not str(authorized.get("decision_id") or "").strip()
    ):
        reasons.append("AUTHORIZATION_NOT_PROVEN")
    live = proofs["live_evidence"]
    if (
        live.get("capability") != capability
        or live.get("passed") is not True
        or str(live.get("status") or "").upper() not in {"HEALTHY", "PASS"}
        or not str(live.get("evidence_digest") or "").strip()
    ):
        reasons.append("LIVE_EVIDENCE_NOT_PROVEN")
    release = proofs["release_evidence"]
    source_commit = str(release.get("source_commit") or "").strip()
    if (
        release.get("capability") != capability
        or release.get("passed") is not True
        or not source_commit
        or source_commit != str(release.get("reviewed_source_commit") or "").strip()
        or not str(release.get("evidence_digest") or "").strip()
    ):
        reasons.append("RELEASE_EVIDENCE_NOT_PROVEN")
    decision = {
        "capability": capability,
        "admitted": not reasons,
        "decision": "ADMIT" if not reasons else "DENY",
        "reasons": reasons,
        "proof_digests": {
            name: hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
            for name, value in proofs.items()
        },
    }
    decision["decision_digest"] = evidence_digest(decision)
    return decision


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def evidence_digest(record: Mapping[str, Any]) -> str:
    payload = dict(record)
    payload.pop("evidence_digest", None)
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def validate_execution_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a normalized copy without granting authority."""
    missing = sorted(REQUIRED_FIELDS - set(record))
    if missing:
        raise ExecutionEvidenceError(f"missing execution evidence fields: {', '.join(missing)}")
    normalized = dict(record)
    normalized["kind"] = str(normalized["kind"]).upper()
    if normalized["kind"] not in ALLOWED_KINDS:
        raise ExecutionEvidenceError("unsupported execution evidence kind")
    for field in ("input", "output", "capability_proof", "budget", "attempt", "lease", "compensation", "human_takeover"):
        if not isinstance(normalized[field], dict):
            raise ExecutionEvidenceError(f"{field} must be an object")
    if not isinstance(normalized["fencing_token"], int) or normalized["fencing_token"] < 0:
        raise ExecutionEvidenceError("fencing_token must be a non-negative integer")
    if not str(normalized["side_effect_class"] or "").strip():
        raise ExecutionEvidenceError("side_effect_class is required")
    if "model_provider" in normalized and not isinstance(normalized["model_provider"], dict):
        raise ExecutionEvidenceError("model_provider must be an object")
    for field in ("token_budget", "cost_budget"):
        if field in normalized and not isinstance(normalized[field], (int, float, dict)):
            raise ExecutionEvidenceError(f"{field} must be numeric or an object")
    if "output_provenance" in normalized and not isinstance(normalized["output_provenance"], dict):
        raise ExecutionEvidenceError("output_provenance must be an object")
    normalized["evidence_digest"] = evidence_digest(normalized)
    return normalized


def build_execution_evidence(*, execution_id: str, kind: str, input: Mapping[str, Any], output: Mapping[str, Any] | None = None,
                             graph_run_id: str | None = None, input_schema_version: str = "1.0",
                             output_schema_version: str = "1.0", capability_proof: Mapping[str, Any] | None = None,
                             budget: Mapping[str, Any] | None = None, attempt: Mapping[str, Any] | None = None,
                             lease: Mapping[str, Any] | None = None, fencing_token: int = 0,
                             side_effect_class: str = "READ_ONLY", compensation: Mapping[str, Any] | None = None,
                             human_takeover: Mapping[str, Any] | None = None,
                             model_provider: Mapping[str, Any] | None = None, model_id: str | None = None,
                             token_budget: int | float | Mapping[str, Any] | None = None,
                             cost_budget: int | float | Mapping[str, Any] | None = None,
                             output_provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    record = {
        "execution_id": str(execution_id), "graph_run_id": graph_run_id,
        "kind": kind, "input_schema_version": input_schema_version,
        "output_schema_version": output_schema_version, "input": dict(input),
        "output": dict(output or {}), "capability_proof": dict(capability_proof or {}),
        "budget": dict(budget or {}), "attempt": dict(attempt or {}),
        "lease": dict(lease or {}), "fencing_token": fencing_token,
        "side_effect_class": side_effect_class, "compensation": dict(compensation or {}),
        "human_takeover": dict(human_takeover or {}),
    }
    if model_provider is not None:
        record["model_provider"] = dict(model_provider)
    if model_id is not None:
        record["model_id"] = str(model_id)
    if token_budget is not None:
        record["token_budget"] = token_budget
    if cost_budget is not None:
        record["cost_budget"] = cost_budget
    if output_provenance is not None:
        record["output_provenance"] = dict(output_provenance)
    return validate_execution_evidence(record)
