"""Durable Graph Inbox/Outbox and wait-event helpers."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from . import connection, graph_runtime
from . import graph_definition_api, graph_event_contract


def receive(source_ref: str, event_type: str, schema_version: str,
            idempotency_key: str, payload: Dict[str, Any],
            authentication: Optional[Dict[str, Any]] = None,
            *, trusted_subject: Optional[str] = None) -> Dict[str, Any]:
    return graph_runtime.ingest_event(
        source_ref, event_type, schema_version, idempotency_key, payload, authentication,
        trusted_subject=trusted_subject,
    )


def pending_inbox(limit: int = 100) -> List[Dict[str, Any]]:
    rows = connection.execute_query(
        "SELECT INBOX_ID, SOURCE_REF, EVENT_TYPE, SCHEMA_VERSION, IDEMPOTENCY_KEY, STATUS, RECEIVED_AT, PROCESSED_AT, ERROR_MESSAGE "
        "FROM GRAPH_INBOX WHERE STATUS = 'RECEIVED' ORDER BY RECEIVED_AT FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )
    return [dict(row) for row in rows]


def mark_inbox(inbox_id: str, status: str, error_message: Optional[str] = None) -> bool:
    allowed = {"PROCESSING", "PROCESSED", "DUPLICATE", "DEAD_LETTER"}
    status = str(status or "").upper()
    if status not in allowed:
        raise ValueError(f"invalid Inbox status: {status}")
    return connection.execute(
        "UPDATE GRAPH_INBOX SET STATUS = :status, ERROR_MESSAGE = :error_message, PROCESSED_AT = CASE WHEN :status IN ('PROCESSED','DUPLICATE','DEAD_LETTER') THEN CURRENT_TIMESTAMP ELSE PROCESSED_AT END WHERE INBOX_ID = :inbox_id",
        {"status": status, "error_message": error_message, "inbox_id": inbox_id},
    ) > 0


def enqueue(run_id: Optional[str], event_type: str, idempotency_key: str,
            payload: Dict[str, Any]) -> str:
    return graph_runtime.enqueue_outbox(run_id, event_type, idempotency_key, payload)


def pending_outbox(limit: int = 100) -> List[Dict[str, Any]]:
    return [dict(row) for row in connection.execute_query(
        "SELECT OUTBOX_ID, RUN_ID, EVENT_TYPE, IDEMPOTENCY_KEY, PAYLOAD_JSON, STATUS, ATTEMPTS, AVAILABLE_AT, LAST_ERROR, CREATED_AT "
        "FROM GRAPH_OUTBOX WHERE STATUS = 'PENDING' AND AVAILABLE_AT <= CURRENT_TIMESTAMP ORDER BY CREATED_AT FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )]


def mark_outbox(outbox_id: str, status: str, error_message: Optional[str] = None) -> bool:
    status = str(status or "").upper()
    if status not in {"DISPATCHING", "SENT", "DEAD_LETTER"}:
        raise ValueError(f"invalid Outbox status: {status}")
    return connection.execute(
        "UPDATE GRAPH_OUTBOX SET STATUS = :status, LAST_ERROR = :error_message, ATTEMPTS = ATTEMPTS + 1, SENT_AT = CASE WHEN :status = 'SENT' THEN CURRENT_TIMESTAMP ELSE SENT_AT END WHERE OUTBOX_ID = :outbox_id AND STATUS IN ('PENDING','DISPATCHING')",
        {"status": status, "error_message": error_message, "outbox_id": outbox_id},
    ) > 0


def register_trigger(graph_version_id: str, kind: str, config: Dict[str, Any],
                     actor_id: str, reason: str, graph_id: Optional[str] = None) -> str:
    """Bind one validated trigger to a published Graph Version."""
    if not graph_version_id or not actor_id or not str(reason or "").strip():
        raise ValueError("Graph trigger requires version, actor, and reason")
    trigger = graph_event_contract.normalize_trigger(kind, config or {})
    version = graph_definition_api.get_version(graph_version_id, include_topology=False)
    if not version or str(version.get("status") or "").upper() not in {"PUBLISHED", "DEPRECATED"}:
        raise ValueError("Graph trigger requires a published Graph Version")
    if graph_id and str(version.get("graph_id") or "") != str(graph_id):
        raise ValueError("Graph trigger version does not belong to the requested Graph")
    trigger_id = "TRIGGER_" + uuid.uuid4().hex
    connection.execute(
        "INSERT INTO GRAPH_TRIGGERS (TRIGGER_ID, GRAPH_VERSION_ID, TRIGGER_KIND, CONFIG_JSON, STATUS, ACTOR_ID, REASON, CREATED_AT, UPDATED_AT) "
        "VALUES (:trigger_id, :graph_version_id, :trigger_kind, :config_json, 'ACTIVE', :actor_id, :reason, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"trigger_id": trigger_id, "graph_version_id": graph_version_id,
         "trigger_kind": trigger["kind"], "config_json": json.dumps(trigger["config"], ensure_ascii=True, sort_keys=True),
         "actor_id": actor_id, "reason": str(reason)[:2000]},
    )
    return trigger_id


def list_triggers(graph_version_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conditions = ["STATUS = 'ACTIVE'"]
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if graph_version_id:
        conditions.append("GRAPH_VERSION_ID = :graph_version_id")
        params["graph_version_id"] = graph_version_id
    rows = connection.execute_query(
        "SELECT TRIGGER_ID, GRAPH_VERSION_ID, TRIGGER_KIND, CONFIG_JSON, STATUS, ACTOR_ID, REASON, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_TRIGGERS WHERE " + " AND ".join(conditions) +
        " ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    )
    result = []
    for row in rows:
        item = {str(key).lower(): value for key, value in dict(row).items()}
        raw = item.get("config_json")
        try:
            item["config"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            item["config"] = {}
        item.pop("config_json", None)
        result.append(item)
    return result


def fire_trigger(trigger_id: str, payload: Optional[Dict[str, Any]], actor_id: str,
                 authentication: Optional[Dict[str, Any]] = None,
                 idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Deliver a trigger and idempotently create its Graph Run when configured."""
    row = connection.execute_query_one(
        "SELECT TRIGGER_ID, GRAPH_VERSION_ID, TRIGGER_KIND, CONFIG_JSON, STATUS "
        "FROM GRAPH_TRIGGERS WHERE TRIGGER_ID = :trigger_id", {"trigger_id": trigger_id},
    )
    if not row or str(row.get("status") or "").upper() != "ACTIVE":
        raise ValueError("Graph trigger is unavailable")
    raw_config = row.get("config_json")
    try:
        config = json.loads(raw_config) if isinstance(raw_config, str) else (raw_config or {})
    except (TypeError, ValueError) as exc:
        raise ValueError("Graph trigger configuration is invalid") from exc
    trigger = graph_event_contract.normalize_trigger(row.get("trigger_kind"), config)
    body = payload if isinstance(payload, dict) else {}
    event_type = str(trigger["config"].get("event_type") or f"GRAPH_TRIGGER:{trigger['kind']}").upper()
    delivery_key = str(idempotency_key or graph_event_contract.payload_hash(body))
    receipt = receive(
        f"trigger:{trigger_id}", event_type, "1", delivery_key, body,
        authentication, trusted_subject=actor_id,
    )
    result = {"trigger_id": trigger_id, "receipt": receipt, "run_id": None}
    if receipt.get("poison") or receipt.get("activation_blocked"):
        return result
    if trigger["config"].get("start_run", True) is False:
        return result
    version = graph_definition_api.get_version(str(row.get("graph_version_id") or ""), include_topology=True) or {}
    plan_id = version.get("plan_id")
    if not plan_id:
        raise ValueError("Graph trigger version has no compiled plan")
    result["run_id"] = graph_runtime.create_run(
        str(row.get("graph_version_id") or ""), plan_id, actor_id,
        initial_state=body, budget=trigger["config"].get("budget") or {},
        idempotency_key=f"trigger:{trigger_id}:{delivery_key}",
    )
    return result
