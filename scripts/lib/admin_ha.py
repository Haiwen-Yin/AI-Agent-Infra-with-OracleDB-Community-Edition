"""Pure v4.4.1 Admin Agent quorum and Leader fencing contracts.

The database service is responsible for transactions and persistence.  This
module contains only deterministic decisions so every database adapter and
test suite uses the same safety rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


class AdminHAError(ValueError):
    """Invalid or unsafe Admin Agent group configuration."""


@dataclass(frozen=True)
class WeightValidation:
    valid: bool
    code: str
    message: str
    total_weight: int = 0
    member_count: int = 0


def validate_weights(members: Iterable[Mapping[str, Any]], *, production: bool = True) -> WeightValidation:
    """Validate positive, distinct weights and the three-member failure rule."""
    rows = [item for item in members if str(item.get("status", "ACTIVE")).upper() in {"ACTIVE", "HEALTHY", "VOTING"}]
    values: list[tuple[str, int]] = []
    for item in rows:
        member_id = str(item.get("member_id") or item.get("agent_id") or "").strip()
        try:
            weight = int(item.get("weight"))
        except (TypeError, ValueError):
            return WeightValidation(False, "WEIGHT_INVALID", "Admin Agent weight must be an integer", 0, len(rows))
        if not member_id or weight <= 0:
            return WeightValidation(False, "WEIGHT_INVALID", "Admin Agent weight must be positive", 0, len(rows))
        values.append((member_id, weight))
    weights = [weight for _, weight in values]
    if len(weights) != len(set(weights)):
        return WeightValidation(False, "DUPLICATE_WEIGHT", "Active voting Admin Agents must have different weights", sum(weights), len(rows))
    if production and len(weights) == 3:
        ordered = sorted(weights)
        if ordered[0] + ordered[1] <= ordered[2]:
            return WeightValidation(False, "DOMINANT_WEIGHT", "The two smaller weights must together exceed the largest weight", sum(weights), len(rows))
    return WeightValidation(True, "VALID", "Admin Agent weights are valid", sum(weights), len(rows))


def quorum(snapshot: Iterable[Mapping[str, Any]], approvals: Iterable[Mapping[str, Any]], proposer_id: str = "") -> dict[str, Any]:
    """Require strict count and strict weight majority from one snapshot."""
    members = [item for item in snapshot if str(item.get("status", "ACTIVE")).upper() in {"ACTIVE", "HEALTHY", "VOTING"}]
    validation = validate_weights(members)
    if not validation.valid:
        return {"allowed": False, "code": "CONFIGURATION_INVALID", "validation": validation.code}
    by_id = {str(item.get("member_id") or item.get("agent_id")): int(item["weight"]) for item in members}
    accepted: set[str] = set()
    for item in approvals:
        member_id = str(item.get("member_id") or item.get("agent_id") or "")
        decision = str(item.get("decision") or "").upper()
        if decision in {"APPROVE", "APPROVED", "ALLOW"} and member_id in by_id and member_id != proposer_id:
            accepted.add(member_id)
    count = len(accepted)
    weight = sum(by_id[item] for item in accepted)
    return {
        "allowed": count * 2 > len(by_id) and weight * 2 > validation.total_weight,
        "code": "QUORUM_REACHED" if count * 2 > len(by_id) and weight * 2 > validation.total_weight else "QUORUM_PENDING",
        "approved_count": count, "eligible_count": len(by_id),
        "approved_weight": weight, "total_weight": validation.total_weight,
    }


def leader_candidate(members: Iterable[Mapping[str, Any]]) -> str:
    """Return a deterministic candidate; invalid configurations return empty."""
    rows = list(members)
    if not validate_weights(rows).valid:
        return ""
    eligible = [item for item in rows if str(item.get("status", "")).upper() in {"ACTIVE", "HEALTHY", "VOTING"}]
    ordered = sorted(eligible, key=lambda item: (-int(item["weight"]), str(item.get("member_id") or item.get("agent_id"))))
    return str(ordered[0].get("member_id") or ordered[0].get("agent_id") or "") if ordered else ""


def accept_write(*, current_term: int, current_fencing: int, write_term: int, write_fencing: int, lease_valid: bool) -> bool:
    """Reject stale Leader writes after lease expiry or succession."""
    return bool(lease_valid and write_term == current_term and write_fencing == current_fencing)
