"""A2A 1.0.1 preview mapping over the durable Graph Runtime.

This is a protocol adapter, not an execution engine.  A2A task lifecycle is
persisted as a mapping to one Graph Run and always uses current platform
authorization before a caller can retrieve, cancel, or subscribe to it.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, List, Optional

from . import connection, graph_runtime, profile_api


PROTOCOL_VERSION = "1.0.1"
PREVIEW_PROFILES = frozenset({"development", "experimental-4.2"})


def _id() -> str:
    return "a2a_" + uuid.uuid4().hex


def enabled() -> bool:
    return profile_api.current_profile() in PREVIEW_PROFILES


def require_enabled() -> None:
    if not enabled():
        raise PermissionError("A2A gateway is disabled by the active runtime profile")


def negotiate(versions: Iterable[str]) -> str:
    offered = {str(value) for value in versions or []}
    if PROTOCOL_VERSION not in offered:
        raise ValueError("A2A protocol version 1.0.1 is required")
    return PROTOCOL_VERSION


def agent_card(agent: Dict[str, Any], *, authenticated: bool = False) -> Dict[str, Any]:
    """Produce a bounded Agent Card; no database credential can be disclosed."""
    card = {
        "protocolVersion": PROTOCOL_VERSION,
        "name": str(agent.get("name") or agent.get("agent_name") or "Graph Agent")[:256],
        "description": str(agent.get("description") or "")[:1000],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "skills": [{"id": str(item.get("id") or item.get("skill_id") or "")[:128],
                    "name": str(item.get("name") or item.get("skill_name") or "")[:256]}
                   for item in (agent.get("skills") or []) if isinstance(item, dict)],
    }
    if authenticated:
        card["supportedInterfaces"] = ["tasks/send", "tasks/get", "tasks/cancel", "tasks/subscribe"]
    return card


def create_task(graph_version_id: str, plan_id: str, principal_id: str, *,
                input_state: Optional[Dict[str, Any]] = None, budget: Optional[Dict[str, Any]] = None,
                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    require_enabled()
    if not str(principal_id or "").strip():
        raise ValueError("A2A principal is required")
    task_id = str(idempotency_key or _id())[:256]
    run_id = graph_runtime.create_run(graph_version_id, plan_id, principal_id, input_state or {}, budget or {}, "a2a:" + task_id)
    def _persist(tx: Any) -> None:
        tx.execute(
            "INSERT INTO GRAPH_PROTOCOL_TASKS (PROTOCOL_TASK_ID, PROTOCOL_VERSION, RUN_ID, PRINCIPAL_ID, STATUS, CURSOR_SEQ, CREATED_AT, UPDATED_AT) "
            "VALUES (:task_id, :version, :run_id, :principal_id, 'WORKING', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            {"task_id": task_id, "version": PROTOCOL_VERSION, "run_id": run_id, "principal_id": principal_id},
        )
    connection.execute_transaction_callback(_persist)
    return {"id": task_id, "status": "working", "run_id": run_id, "protocolVersion": PROTOCOL_VERSION}


def get_task(task_id: str, principal_id: str) -> Optional[Dict[str, Any]]:
    require_enabled()
    row = connection.execute_query_one(
        "SELECT t.PROTOCOL_TASK_ID, t.RUN_ID, t.PRINCIPAL_ID, t.STATUS, t.CURSOR_SEQ, r.STATUS AS RUN_STATUS, r.UPDATED_AT "
        "FROM GRAPH_PROTOCOL_TASKS t JOIN GRAPH_RUNS r ON r.RUN_ID = t.RUN_ID "
        "WHERE t.PROTOCOL_TASK_ID = :task_id AND t.PRINCIPAL_ID = :principal_id",
        {"task_id": task_id, "principal_id": principal_id},
    )
    if not row:
        return None
    value = {str(key).lower(): item for key, item in dict(row).items()}
    run_status = str(value.get("run_status") or "").upper()
    state = "completed" if run_status == "SUCCEEDED" else ("failed" if run_status in {"FAILED", "CANCELLED", "REVIEW_REQUIRED"} else "working")
    return {"id": value["protocol_task_id"], "status": state, "run_id": value["run_id"], "cursor": value.get("cursor_seq", 0), "updated_at": value.get("updated_at")}


def cancel_task(task_id: str, principal_id: str, reason: str) -> bool:
    require_enabled()
    task = get_task(task_id, principal_id)
    if not task:
        return False
    if not str(reason or "").strip():
        raise ValueError("A2A cancellation reason is required")
    changed = graph_runtime.cancel_run(str(task["run_id"]), principal_id, reason)
    if changed:
        connection.execute(
            "UPDATE GRAPH_PROTOCOL_TASKS SET STATUS = 'CANCELLED', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PROTOCOL_TASK_ID = :task_id AND PRINCIPAL_ID = :principal_id",
            {"task_id": task_id, "principal_id": principal_id},
        )
    return changed
