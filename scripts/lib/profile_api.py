"""Database-backed runtime Profile preflight and controlled activation."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List

from . import connection, governed_contracts, identity_api


PROFILES = {"production", "graph-preview", "development", "experimental-4.2"}
PROFILE_CAPABILITIES = {
    "graph-preview": ("graph", "graph-preview", "channel-graph", "graph-dynamic"),
    "development": ("graph", "graph-preview", "channel-graph", "graph-dynamic", "a2a-gateway", "otel-export", "fault-injection"),
    "experimental-4.2": ("graph", "graph-preview", "channel-graph", "graph-dynamic", "a2a-gateway", "otel-export", "experimental"),
}


def current_profile(default: str = "production") -> str:
    value = str(os.environ.get("CX_RUNTIME_PROFILE", default) or default).strip().lower()
    return value if value in PROFILES else str(default).lower()


def _id() -> str:
    import secrets
    return "PC_" + secrets.token_hex(20)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{str(key).lower(): value for key, value in dict(row).items()} for row in rows]


def _row(row: Dict[str, Any] | None) -> Dict[str, Any] | None:
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None


def active_work() -> List[Dict[str, Any]]:
    """Collect only bounded active work needed for a profile impact check."""
    records: List[Dict[str, Any]] = []
    queries = (
        ("GRAPH_RUNS", "SELECT RUN_ID AS WORK_ID, STATUS, 'graph' AS CAPABILITY FROM GRAPH_RUNS WHERE STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')"),
        ("LOOP_RUNS", "SELECT RUN_ID AS WORK_ID, STATUS, 'loop' AS CAPABILITY FROM LOOP_RUNS WHERE STATUS IN ('RUNNING','PAUSED','WAITING')"),
    )
    for _, query in queries:
        # A profile change is a control-plane mutation.  Missing tables,
        # revoked grants, and connection failures must block the mutation
        # rather than being interpreted as an empty workload.
        records.extend(_rows(connection.execute_query(query)))
    return records


def _active_work_tx(tx: Any) -> List[Dict[str, Any]]:
    """Read active work on the transaction connection for activation fencing."""
    records: List[Dict[str, Any]] = []
    for query in (
        "SELECT RUN_ID AS WORK_ID, STATUS, 'graph' AS CAPABILITY FROM GRAPH_RUNS WHERE STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
        "SELECT RUN_ID AS WORK_ID, STATUS, 'loop' AS CAPABILITY FROM LOOP_RUNS WHERE STATUS IN ('RUNNING','PAUSED','WAITING')",
    ):
        # Both tables are part of the v4.3 runtime contract.  Do not fail open
        # on an absent object or an authorization/connection error: the caller
        # must be unable to activate a profile while active-work fencing is
        # incomplete.  Adapter-specific exceptions are intentionally allowed
        # to reach the transaction wrapper so the entire operation rolls back.
        records.extend(_rows(tx.query(query)))
    return records


def preflight(requested_by: str, target_profile: str, reason: str) -> Dict[str, Any]:
    if not str(requested_by or "").strip() or not str(reason or "").strip():
        raise ValueError("profile actor and reason are required")
    target = str(target_profile or "").strip().lower()
    decision = governed_contracts.profile_change_preflight(
        current_profile(), target, authorized=True, reason=reason, active_work=active_work(),
        capability_dependencies=governed_contracts.DEFAULT_CAPABILITY_DEPENDENCIES,
        restart_available=True, controlled_activation_available=True,
    )
    impact = dict(decision.get("impact", {}))
    result = {
        "current_profile": impact.get("current_profile", current_profile()),
        "target_profile": impact.get("target_profile", target),
        "changed": bool(impact.get("requires_restart")),
        "affected_work": impact.get("impacted_work", []),
        "activation": "CONTROLLED_RESTART" if impact.get("requires_restart") else "NOOP",
        "safe_to_activate": bool(decision.allowed),
        "requires_audit": True,
        "decision": decision.as_dict(),
    }
    change_id = _id()
    def _persist(tx: Any) -> None:
        tx.execute(
            "INSERT INTO CX_RUNTIME_PROFILE_CHANGES(CHANGE_ID, REQUESTED_BY, CURRENT_PROFILE, TARGET_PROFILE, "
            "IMPACT_JSON, STATUS, REASON) VALUES (:change_id, :requested_by, :current_profile, :target_profile, "
            ":impact_json, 'PREFLIGHT', :reason)",
            {"change_id": change_id, "requested_by": requested_by, "current_profile": result["current_profile"],
             "target_profile": result["target_profile"], "impact_json": _json(result), "reason": reason[:2000]},
        )
        identity_api._audit_tx(
            tx, requested_by, "RUNTIME_PROFILE_PREFLIGHT", "RUNTIME_PROFILE",
            change_id, "ALLOW" if result["safe_to_activate"] else "BLOCKED", reason,
        )

    connection.execute_transaction_callback(_persist)
    return {"change_id": change_id, **result, "reason": reason[:2000]}


def activate(change_id: str, actor: str, reason: str) -> Dict[str, Any]:
    if not str(change_id or "").strip() or not str(actor or "").strip() or not str(reason or "").strip():
        raise ValueError("profile activation fields are required")
    def _activate(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one(
            "SELECT CHANGE_ID, CURRENT_PROFILE, TARGET_PROFILE, IMPACT_JSON, STATUS "
            "FROM CX_RUNTIME_PROFILE_CHANGES WHERE CHANGE_ID = :change_id FOR UPDATE",
            {"change_id": change_id},
        ))
        if not row:
            raise ValueError("profile change not found")
        if str(row.get("status") or "").upper() != "PREFLIGHT":
            raise ValueError("profile change is not pending")
        try:
            impact = json.loads(row.get("impact_json") or "{}")
        except (TypeError, ValueError):
            impact = {}
        if not bool(impact.get("safe_to_activate")):
            raise ValueError("active work must be paused or migrated before activation")
        if _active_work_tx(tx):
            raise ValueError("active work must be paused or migrated before activation")
        changed = tx.execute(
            "UPDATE CX_RUNTIME_PROFILE_CHANGES SET STATUS = 'ACTIVATED', ACTIVATED_AT = CURRENT_TIMESTAMP, "
            "REASON = :reason WHERE CHANGE_ID = :change_id AND STATUS = 'PREFLIGHT'",
            {"change_id": change_id, "reason": reason[:2000]},
        ) > 0
        if not changed:
            raise ValueError("profile change was updated concurrently")
        identity_api._audit_tx(
            tx, actor, "RUNTIME_PROFILE_ACTIVATE", "RUNTIME_PROFILE",
            change_id, "ALLOW", reason,
        )
        return {"change_id": change_id, "status": "ACTIVATED",
                "target_profile": row.get("target_profile"), "restart_required": True}

    # The environment variable remains the process restart boundary.  The DB
    # record is the authority for the requested transition and its evidence.
    return connection.execute_transaction_callback(_activate)


def list_changes(requested_by: str, limit: int = 100) -> List[Dict[str, Any]]:
    rows = _rows(connection.execute_query(
        "SELECT CHANGE_ID, REQUESTED_BY, CURRENT_PROFILE, TARGET_PROFILE, STATUS, REASON, ACTIVATED_AT, CREATED_AT "
        "FROM CX_RUNTIME_PROFILE_CHANGES WHERE REQUESTED_BY = :requested_by ORDER BY CREATED_AT DESC "
        + ("LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"} else "FETCH FIRST :limit ROWS ONLY"),
        {"requested_by": requested_by, "limit": max(1, min(int(limit), 500))},
    ))
    return rows
