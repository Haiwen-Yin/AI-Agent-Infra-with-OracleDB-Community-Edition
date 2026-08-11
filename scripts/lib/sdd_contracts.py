"""Pure validation contracts for the native governed SDD control plane.

The helpers in this module intentionally do not access a database, SCM, a
model, or process state.  Services persist their returned decisions as audit
events and use them consistently across Oracle, PostgreSQL and YashanDB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence


REVISION_STATES = frozenset({
    "SOURCE_SNAPSHOT", "WORKING_REVISION", "APPROVED_BASELINE", "AMENDMENT",
    "SUPERSEDED_BASELINE", "RETIRED",
})
REVISION_TRANSITIONS = {
    "SOURCE_SNAPSHOT": frozenset({"WORKING_REVISION", "RETIRED"}),
    "WORKING_REVISION": frozenset({"APPROVED_BASELINE", "RETIRED"}),
    "APPROVED_BASELINE": frozenset({"AMENDMENT", "SUPERSEDED_BASELINE"}),
    "AMENDMENT": frozenset({"WORKING_REVISION", "APPROVED_BASELINE", "RETIRED"}),
    "SUPERSEDED_BASELINE": frozenset(),
    "RETIRED": frozenset(),
}

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
GLOBAL_PAUSE_AREAS = frozenset({
    "SECURITY", "PERMISSION", "PUBLIC_API", "DATA_MODEL",
    "EMBEDDING_CONTRACT", "ACCEPTANCE_BASELINE", "IRREVERSIBLE_EFFECT",
})
BUILTIN_ROLES = {
    "REQUIREMENTS": {"max_risk": "MEDIUM", "review": "REVIEWER"},
    "ARCHITECT": {"max_risk": "HIGH", "review": "REVIEWER"},
    "PLANNER": {"max_risk": "MEDIUM", "review": "REVIEWER"},
    "CODING": {"max_risk": "MEDIUM", "review": "CODE_REVIEW"},
    "DATABASE_MIGRATION": {"max_risk": "HIGH", "review": "HUMAN_APPROVAL"},
    "TESTING": {"max_risk": "MEDIUM", "review": "INDEPENDENT_EVIDENCE"},
    "SECURITY_REVIEW": {"max_risk": "HIGH", "review": "HUMAN_APPROVAL"},
    "CODE_REVIEW": {"max_risk": "HIGH", "review": "REVIEWER"},
    "RELEASE": {"max_risk": "HIGH", "review": "HUMAN_APPROVAL"},
}


@dataclass(frozen=True)
class SddDecision:
    allowed: bool
    code: str
    message: str
    details: Mapping[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "code": self.code,
                "message": self.message, "details": dict(self.details)}


def _value(value: Any) -> str:
    return str(value or "").strip().upper()


def revision_transition(current: Any, requested: Any, *, reason: str = "") -> SddDecision:
    source, target = _value(current), _value(requested)
    if source not in REVISION_STATES or target not in REVISION_STATES:
        return SddDecision(False, "SDD_REVISION_STATE_INVALID", "Unknown revision state", {"from": source, "to": target})
    if target not in REVISION_TRANSITIONS[source]:
        return SddDecision(False, "SDD_REVISION_TRANSITION_DENIED", "Revision transition is not permitted", {"from": source, "to": target})
    if not str(reason or "").strip():
        return SddDecision(False, "SDD_REASON_REQUIRED", "A reason is required", {"from": source, "to": target})
    return SddDecision(True, "SDD_REVISION_TRANSITION_ALLOWED", "Revision transition is permitted", {"from": source, "to": target})


def patch_decision(revision_state: Any, expected_version: Any, actual_version: Any, *, actor_is_authorized: bool) -> SddDecision:
    state = _value(revision_state)
    if not actor_is_authorized:
        return SddDecision(False, "SDD_PATCH_DENIED", "Actor is not authorized to patch this revision", {})
    if state != "WORKING_REVISION":
        return SddDecision(False, "SDD_BASELINE_IMMUTABLE", "Only a working revision can be patched", {"state": state})
    try:
        matches = int(expected_version) == int(actual_version)
    except (TypeError, ValueError):
        matches = False
    if not matches:
        return SddDecision(False, "SDD_VERSION_CONFLICT", "The revision changed; reload and merge before retrying", {"expected": expected_version, "actual": actual_version})
    return SddDecision(True, "SDD_PATCH_ALLOWED", "Patch may be applied", {"version": actual_version})


def baseline_decision(*, unresolved_fragments: Iterable[Mapping[str, Any]], required_reviews_complete: bool,
                      required_approvals_complete: bool, acceptance_complete: bool) -> SddDecision:
    blockers = []
    for item in unresolved_fragments:
        area = _value(item.get("area") or item.get("fragment_kind"))
        waived = bool(item.get("waived"))
        if area in {"REQUIREMENT", "ACCEPTANCE", "SECURITY", "API", "DATA", "MIGRATION"} and not waived:
            blockers.append(area)
    if blockers:
        return SddDecision(False, "SDD_UNRESOLVED_FRAGMENT", "Blocking source fragments must be resolved", {"areas": sorted(set(blockers))})
    if not required_reviews_complete or not required_approvals_complete:
        return SddDecision(False, "SDD_REVIEW_OR_APPROVAL_REQUIRED", "Required review or approval is incomplete", {})
    if not acceptance_complete:
        return SddDecision(False, "SDD_ACCEPTANCE_INCOMPLETE", "Required acceptance criteria are incomplete", {})
    return SddDecision(True, "SDD_BASELINE_ALLOWED", "Approved execution baseline may be created", {})


def graph_contract_decision(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]], *, budget: Mapping[str, Any] | None = None) -> SddDecision:
    keys = [str(node.get("node_key") or "").strip() for node in nodes]
    if not keys or any(not key for key in keys) or len(keys) != len(set(keys)):
        return SddDecision(False, "SDD_GRAPH_NODE_INVALID", "Nodes need unique node keys", {})
    known = set(keys)
    errors = []
    outgoing = {key: 0 for key in known}
    incoming = {key: 0 for key in known}
    for edge in edges:
        source, target = str(edge.get("source_node_key") or ""), str(edge.get("target_node_key") or "")
        if source not in known or target not in known:
            errors.append("UNKNOWN_EDGE_ENDPOINT")
            continue
        outgoing[source] += 1
        incoming[target] += 1
        if edge.get("guard") is not None and not str(edge.get("guard")).strip():
            errors.append("EMPTY_GUARD")
    starts = [key for key in known if incoming[key] == 0]
    ends = [key for key in known if outgoing[key] == 0]
    if not starts:
        errors.append("NO_START")
    if not ends:
        errors.append("NO_END")
    for node in nodes:
        key = str(node.get("node_key"))
        if node.get("node_type", "").upper() not in {"START", "END"} and not node.get("role_key"):
            errors.append("ROLE_MISSING:" + key)
        if node.get("read_set") is None or node.get("write_set") is None:
            errors.append("RESOURCE_SET_MISSING:" + key)
    if budget:
        for name, value in budget.items():
            if isinstance(value, (int, float)) and value < 0:
                errors.append("NEGATIVE_BUDGET:" + str(name))
    return SddDecision(not errors, "SDD_GRAPH_VALID" if not errors else "SDD_GRAPH_INVALID",
                       "Execution graph is valid" if not errors else "Execution graph contract is incomplete",
                       {"errors": sorted(set(errors)), "starts": starts, "ends": ends})


def risk_pause_decision(risk: Any, changed_areas: Iterable[Any]) -> SddDecision:
    level = _value(risk) or "LOW"
    areas = {_value(area) for area in changed_areas}
    global_pause = bool(areas & GLOBAL_PAUSE_AREAS)
    if level not in RISK_ORDER:
        return SddDecision(False, "SDD_RISK_INVALID", "Unknown risk level", {"risk": level})
    return SddDecision(True, "SDD_GLOBAL_PAUSE" if global_pause else "SDD_LOCAL_PAUSE",
                       "Whole Run pause required" if global_pause else "Affected subgraph pause required",
                       {"risk": level, "changed_areas": sorted(areas), "requires_human": RISK_ORDER[level] >= RISK_ORDER["HIGH"]})


def role_decision(role_key: Any, requested_risk: Any, *, registered: Mapping[str, Mapping[str, Any]] | None = None) -> SddDecision:
    role = _value(role_key)
    registry = dict(BUILTIN_ROLES)
    registry.update({str(key).upper(): dict(value) for key, value in (registered or {}).items()})
    definition = registry.get(role)
    if not definition:
        return SddDecision(False, "SDD_ROLE_UNREGISTERED", "Role is not registered", {"role": role})
    risk, maximum = _value(requested_risk) or "LOW", _value(definition.get("max_risk")) or "LOW"
    if risk not in RISK_ORDER or maximum not in RISK_ORDER or RISK_ORDER[risk] > RISK_ORDER[maximum]:
        return SddDecision(False, "SDD_ROLE_RISK_DENIED", "Role cannot accept this risk", {"role": role, "risk": risk, "max_risk": maximum})
    return SddDecision(True, "SDD_ROLE_ALLOWED", "Role may execute the task", {"role": role, "review": definition.get("review")})

