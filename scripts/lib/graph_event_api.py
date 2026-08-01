"""Durable Graph Inbox/Outbox and wait-event helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import connection, graph_runtime
from . import graph_definition_api, graph_event_contract


DEFAULT_MAX_ATTEMPTS = 5
MAX_RETRY_DELAY_SECONDS = 3600


def retry_delay_seconds(attempts: int, *, base_seconds: int = 5,
                        cap_seconds: int = MAX_RETRY_DELAY_SECONDS) -> int:
    """Return a deterministic bounded exponential backoff for a delivery."""
    try:
        attempt = max(1, int(attempts))
    except (TypeError, ValueError):
        attempt = 1
    try:
        base = max(1, int(base_seconds))
        cap = max(base, min(int(cap_seconds), MAX_RETRY_DELAY_SECONDS))
    except (TypeError, ValueError):
        base, cap = 5, MAX_RETRY_DELAY_SECONDS
    return min(cap, base * (2 ** min(attempt - 1, 20)))


def _retry_at(attempts: int, *, now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return (current + timedelta(seconds=retry_delay_seconds(attempts))).replace(tzinfo=None)


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
        "SELECT INBOX_ID, SOURCE_REF, EVENT_TYPE, SCHEMA_VERSION, IDEMPOTENCY_KEY, STATUS, ATTEMPTS, AVAILABLE_AT, "
        "RECEIVED_AT, PROCESSED_AT, ERROR_MESSAGE FROM GRAPH_INBOX "
        "WHERE STATUS = 'RECEIVED' AND AVAILABLE_AT <= CURRENT_TIMESTAMP "
        "ORDER BY RECEIVED_AT FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )
    return [dict(row) for row in rows]


def dead_letters(limit: int = 100) -> List[Dict[str, Any]]:
    rows = connection.execute_query(
        "SELECT INBOX_ID, SOURCE_REF, EVENT_TYPE, SCHEMA_VERSION, IDEMPOTENCY_KEY, STATUS, "
        "ATTEMPTS, AVAILABLE_AT, RECEIVED_AT, PROCESSED_AT, ERROR_MESSAGE "
        "FROM GRAPH_INBOX WHERE STATUS = 'DEAD_LETTER' "
        "ORDER BY RECEIVED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )
    return [dict(row) for row in rows]


def replay_dead_letter(inbox_id: str, actor_id: str, reason: str) -> Dict[str, Any]:
    return graph_runtime.replay_dead_letter(inbox_id, actor_id, reason)


def claim_inbox(inbox_id: str, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> bool:
    """Claim one ready Inbox event for an external consumer."""
    maximum = max(1, min(int(max_attempts), 100))
    claimed = connection.execute(
        "UPDATE GRAPH_INBOX SET STATUS = 'PROCESSING', ATTEMPTS = ATTEMPTS + 1 "
        "WHERE INBOX_ID = :inbox_id AND STATUS = 'RECEIVED' "
        "AND AVAILABLE_AT <= CURRENT_TIMESTAMP AND ATTEMPTS < :max_attempts",
        {"inbox_id": inbox_id, "max_attempts": maximum},
    ) > 0
    if claimed:
        return True
    # Do not leave an exhausted event in RECEIVED forever.  This update is
    # conditional as well, so a concurrent claimant remains the sole owner.
    connection.execute(
        "UPDATE GRAPH_INBOX SET STATUS = 'DEAD_LETTER', ERROR_MESSAGE = 'Inbox retry limit exhausted', "
        "PROCESSED_AT = CURRENT_TIMESTAMP WHERE INBOX_ID = :inbox_id AND STATUS = 'RECEIVED' "
        "AND ATTEMPTS >= :max_attempts",
        {"inbox_id": inbox_id, "max_attempts": maximum},
    )
    return False


def mark_inbox(inbox_id: str, status: str, error_message: Optional[str] = None,
               *, retry_after_seconds: Optional[int] = None,
               max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> bool:
    allowed = {"PROCESSING", "PROCESSED", "DUPLICATE", "DEAD_LETTER", "RETRY"}
    status = str(status or "").upper()
    if status not in allowed:
        raise ValueError(f"invalid Inbox status: {status}")
    if status == "RETRY":
        row = connection.execute_query_one(
            "SELECT ATTEMPTS FROM GRAPH_INBOX WHERE INBOX_ID = :inbox_id",
            {"inbox_id": inbox_id},
        )
        if not row:
            return False
        attempts = int(row.get("attempts") or 0)
        maximum = max(1, min(int(max_attempts), 100))
        if attempts >= maximum:
            status = "DEAD_LETTER"
            available_at = None
        else:
            status = "RECEIVED"
            if retry_after_seconds is None:
                available_at = _retry_at(attempts, now=datetime.now(timezone.utc))
            else:
                delay = max(1, min(int(retry_after_seconds), MAX_RETRY_DELAY_SECONDS))
                available_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(tzinfo=None)
        return connection.execute(
            "UPDATE GRAPH_INBOX SET STATUS = :status, ERROR_MESSAGE = :error_message, "
            "AVAILABLE_AT = COALESCE(:available_at, AVAILABLE_AT), "
            "PROCESSED_AT = CASE WHEN :status IN ('PROCESSED','DUPLICATE','DEAD_LETTER') "
            "THEN CURRENT_TIMESTAMP ELSE NULL END WHERE INBOX_ID = :inbox_id "
            "AND STATUS = 'PROCESSING'",
            {"status": status, "error_message": error_message, "available_at": available_at,
             "inbox_id": inbox_id},
        ) > 0
    return connection.execute(
        "UPDATE GRAPH_INBOX SET STATUS = :status, ERROR_MESSAGE = :error_message, "
        "PROCESSED_AT = CASE WHEN :status IN ('PROCESSED','DUPLICATE','DEAD_LETTER') "
        "THEN CURRENT_TIMESTAMP ELSE PROCESSED_AT END WHERE INBOX_ID = :inbox_id "
        "AND STATUS = 'PROCESSING'",
        {"status": status, "error_message": error_message, "inbox_id": inbox_id},
    ) > 0


def enqueue(run_id: Optional[str], event_type: str, idempotency_key: str,
            payload: Dict[str, Any], max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
    return graph_runtime.enqueue_outbox(
        run_id, event_type, idempotency_key, payload, max_attempts=max_attempts,
    )


def pending_outbox(limit: int = 100) -> List[Dict[str, Any]]:
    return [dict(row) for row in connection.execute_query(
        "SELECT OUTBOX_ID, RUN_ID, EVENT_TYPE, IDEMPOTENCY_KEY, PAYLOAD_JSON, STATUS, ATTEMPTS, MAX_ATTEMPTS, "
        "AVAILABLE_AT, LAST_ERROR, CREATED_AT "
        "FROM GRAPH_OUTBOX WHERE STATUS = 'PENDING' AND AVAILABLE_AT <= CURRENT_TIMESTAMP ORDER BY CREATED_AT FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )]


def mark_outbox(outbox_id: str, status: str, error_message: Optional[str] = None,
                *, retry_after_seconds: Optional[int] = None,
                max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> bool:
    status = str(status or "").upper()
    if status not in {"DISPATCHING", "SENT", "RETRY", "DEAD_LETTER"}:
        raise ValueError(f"invalid Outbox status: {status}")
    if status == "RETRY":
        row = connection.execute_query_one(
            "SELECT ATTEMPTS, MAX_ATTEMPTS FROM GRAPH_OUTBOX WHERE OUTBOX_ID = :outbox_id",
            {"outbox_id": outbox_id},
        )
        if not row:
            return False
        attempts = int(row.get("attempts") or 0)
        maximum = int(row.get("max_attempts") or max_attempts or DEFAULT_MAX_ATTEMPTS)
        maximum = max(1, min(maximum, 100))
        if attempts >= maximum:
            return connection.execute(
                "UPDATE GRAPH_OUTBOX SET STATUS = :status, LAST_ERROR = :error_message "
                "WHERE OUTBOX_ID = :outbox_id AND STATUS = 'DISPATCHING'",
                {"status": "DEAD_LETTER", "error_message": error_message, "outbox_id": outbox_id},
            ) > 0
        if retry_after_seconds is None:
            available_at = _retry_at(attempts)
        else:
            delay = max(1, min(int(retry_after_seconds), MAX_RETRY_DELAY_SECONDS))
            available_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).replace(tzinfo=None)
        return connection.execute(
            "UPDATE GRAPH_OUTBOX SET STATUS = 'PENDING', LAST_ERROR = :error_message, "
            "AVAILABLE_AT = :available_at WHERE OUTBOX_ID = :outbox_id "
            "AND STATUS = 'DISPATCHING'",
            {"error_message": error_message, "available_at": available_at,
             "outbox_id": outbox_id},
        ) > 0
    if status == "DISPATCHING":
        return connection.execute(
            "UPDATE GRAPH_OUTBOX SET STATUS = 'DISPATCHING', ATTEMPTS = ATTEMPTS + 1 "
            "WHERE OUTBOX_ID = :outbox_id AND STATUS = 'PENDING' "
            "AND AVAILABLE_AT <= CURRENT_TIMESTAMP AND ATTEMPTS < :max_attempts",
            {"outbox_id": outbox_id, "max_attempts": max(1, min(int(max_attempts), 100))},
        ) > 0
    return connection.execute(
        "UPDATE GRAPH_OUTBOX SET STATUS = :status, LAST_ERROR = :error_message, "
        "ATTEMPTS = CASE WHEN STATUS = 'PENDING' THEN ATTEMPTS + 1 ELSE ATTEMPTS END, "
        "SENT_AT = CASE WHEN :status = 'SENT' THEN CURRENT_TIMESTAMP ELSE SENT_AT END "
        "WHERE OUTBOX_ID = :outbox_id AND STATUS = 'DISPATCHING'",
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
