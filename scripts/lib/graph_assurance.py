"""Test-gated reliability controls and evidence for the Graph Runtime.

The database remains the authority for Graph state.  This module deliberately
does not offer HTTP, Skill, MCP, or Agent entry points: failpoints are only
available to an in-process test which explicitly enables them.  Recovery
evidence is durable when the v4.3.3 schema is present and never changes a
committed Runtime outcome.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional

from . import connection


class FailpointTriggered(RuntimeError):
    """A deterministic, test-only simulated process failure."""


_LOCK = threading.Lock()
_FAILPOINTS: Dict[str, int] = {}
_ALLOWED_FAILPOINTS = frozenset({
    "before_claim", "after_claim", "before_completion", "after_checkpoint",
    "after_completion", "before_reap", "after_reap",
})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _enabled() -> bool:
    return os.environ.get("CX_GRAPH_TEST_MODE", "").strip() == "1"


def arm_failpoint_for_test(name: str, hits: int = 1) -> None:
    """Arm a bounded failpoint in a test process.

    Production processes cannot arm failpoints even if a request supplies a
    similarly named value, because this method has no remotely reachable
    caller and requires the explicit test-mode environment boundary.
    """
    normalized = str(name or "").strip().lower()
    if not _enabled():
        raise PermissionError("Graph failpoints require CX_GRAPH_TEST_MODE=1")
    if normalized not in _ALLOWED_FAILPOINTS:
        raise ValueError("unknown Graph failpoint")
    count = int(hits)
    if count < 1 or count > 16:
        raise ValueError("failpoint hits must be between 1 and 16")
    with _LOCK:
        _FAILPOINTS[normalized] = count


def clear_failpoints_for_test() -> None:
    with _LOCK:
        _FAILPOINTS.clear()


@contextmanager
def failpoint_for_test(name: str, hits: int = 1) -> Iterator[None]:
    arm_failpoint_for_test(name, hits)
    try:
        yield
    finally:
        clear_failpoints_for_test()


def checkpoint(name: str) -> None:
    """Raise only from an explicitly armed in-process test failpoint."""
    normalized = str(name or "").strip().lower()
    with _LOCK:
        remaining = _FAILPOINTS.get(normalized, 0)
        if remaining <= 0:
            return
        if remaining == 1:
            _FAILPOINTS.pop(normalized, None)
        else:
            _FAILPOINTS[normalized] = remaining - 1
    raise FailpointTriggered("graph failpoint triggered: " + normalized)


def _id() -> str:
    return "GAE_" + uuid.uuid4().hex


def record_evidence_tx(tx: Any, evidence_type: str, status: str, *,
                       run_id: Optional[str] = None, actor_id: Optional[str] = None,
                       detail: Optional[Dict[str, Any]] = None) -> str:
    """Write bounded, redacted operational evidence in the caller transaction."""
    evidence_id = _id()
    tx.execute(
        "INSERT INTO GRAPH_ASSURANCE_EVIDENCE "
        "(EVIDENCE_ID, RUN_ID, EVIDENCE_TYPE, STATUS, ACTOR_ID, DETAIL_JSON, CREATED_AT) "
        "VALUES (:evidence_id, :run_id, :evidence_type, :status, :actor_id, :detail_json, CURRENT_TIMESTAMP)",
        {"evidence_id": evidence_id, "run_id": run_id, "evidence_type": str(evidence_type)[:64],
         "status": str(status)[:32], "actor_id": actor_id,
         "detail_json": _canonical(detail or {})},
    )
    return evidence_id


def list_evidence(run_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Return evidence without treating a missing v4.3.3 migration as empty."""
    value = max(1, min(int(limit), 500))
    where = ""
    params: Dict[str, Any] = {"limit": value}
    if run_id:
        where = " WHERE RUN_ID = :run_id"
        params["run_id"] = run_id
    rows = connection.execute_query(
        "SELECT EVIDENCE_ID, RUN_ID, EVIDENCE_TYPE, STATUS, ACTOR_ID, DETAIL_JSON, CREATED_AT "
        "FROM GRAPH_ASSURANCE_EVIDENCE" + where + " ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        params,
    )
    result = []
    for row in rows:
        item = {str(key).lower(): value for key, value in dict(row).items()}
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except (TypeError, ValueError):
            item["detail"] = {}
        result.append(item)
    return result


def invariant_scan() -> Dict[str, Any]:
    """Scan portable relational invariants used by failure-recovery tests."""
    checks = {
        "orphan_ready_nodes": "SELECT COUNT(*) AS COUNT FROM GRAPH_READY_NODES rn LEFT JOIN GRAPH_NODE_RUNS nr ON nr.NODE_RUN_ID = rn.NODE_RUN_ID WHERE nr.NODE_RUN_ID IS NULL",
        "duplicate_transitions": "SELECT COUNT(*) AS COUNT FROM (SELECT ATTEMPT_ID FROM GRAPH_TRANSITIONS WHERE ATTEMPT_ID IS NOT NULL GROUP BY ATTEMPT_ID HAVING COUNT(*) > 1) duplicates",
        "conflicting_current_attempts": "SELECT COUNT(*) AS COUNT FROM (SELECT NODE_RUN_ID FROM GRAPH_ATTEMPTS WHERE STATUS = 'RUNNING' GROUP BY NODE_RUN_ID HAVING COUNT(*) > 1) duplicates",
        "stale_active_leases": "SELECT COUNT(*) AS COUNT FROM GRAPH_ATTEMPTS WHERE STATUS = 'RUNNING' AND LEASE_EXPIRES_AT <= CURRENT_TIMESTAMP",
        "missing_output_checkpoints": "SELECT COUNT(*) AS COUNT FROM GRAPH_NODE_RUNS nr LEFT JOIN GRAPH_CHECKPOINTS cp ON cp.CHECKPOINT_ID = nr.OUTPUT_CHECKPOINT_ID WHERE nr.STATUS = 'SUCCEEDED' AND (nr.OUTPUT_CHECKPOINT_ID IS NULL OR cp.CHECKPOINT_ID IS NULL)",
        "terminal_run_active_nodes": "SELECT COUNT(*) AS COUNT FROM GRAPH_RUNS r JOIN GRAPH_NODE_RUNS nr ON nr.RUN_ID = r.RUN_ID WHERE r.STATUS IN ('SUCCEEDED','FAILED','CANCELLED') AND nr.STATUS IN ('READY','RUNNING','WAITING')",
    }
    findings: Dict[str, int] = {}
    for name, sql in checks.items():
        row = connection.execute_query_one(sql) or {}
        findings[name] = int(dict(row).get("count") or dict(row).get("COUNT") or 0)
    return {"healthy": not any(findings.values()), "findings": findings}


def recover_runtime(actor_id: str, *, worker_id: str = "", limit: int = 100) -> Dict[str, Any]:
    """Recover stale work after a local Runtime replacement.

    The function intentionally delegates lease fencing to ``graph_runtime``;
    it does not fabricate a new lease or repeat a side effect.  The caller is
    expected to authenticate the replacing runtime through the existing
    gateway/worker registration flow before claiming recovered work.
    """
    if not str(actor_id or "").strip():
        raise ValueError("recovery actor is required")
    from . import graph_runtime
    reaped = graph_runtime.reap_expired_leases(limit)

    def _record(tx: Any) -> Dict[str, Any]:
        evidence_id = record_evidence_tx(
            tx, "AGENT_RUNTIME_RECOVERED", "RECORDED", actor_id=actor_id,
            detail={"worker_id": str(worker_id)[:256], "reaped_attempts": reaped,
                    "authority": "DATABASE_LEASE_AND_FENCING"},
        )
        return {"evidence_id": evidence_id, "reaped_attempts": reaped}

    return connection.execute_transaction_callback(_record)
