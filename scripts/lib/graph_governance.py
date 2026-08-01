"""Graph-specific authorization, budgets, evaluation, and interventions."""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import connection


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


_MISSING_EVENT_TABLE = (
    "graph_governance_events", "undefined table", "table or view does not exist",
    "invalid object name", "relation does not exist",
)


def _redact(value: Any) -> Any:
    """Keep governance detail bounded and free of secret-shaped fields."""
    sensitive = {"password", "secret", "token", "api_key", "apikey", "credential",
                 "authorization", "cookie", "payload", "content"}
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if any(part in str(key).lower() for part in sensitive)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    return value


def governance_event_document(event_type: str, actor_id: str, reason: str, *,
                              run_id: Optional[str] = None,
                              artifact_id: Optional[str] = None,
                              detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the canonical Graph governance event before persistence."""
    actor = str(actor_id or "").strip()
    event_reason = str(reason or "").strip()
    if not actor or not event_reason:
        raise ValueError("Graph governance event requires actor_id and reason")
    bounded_detail = _redact(detail or {})
    return {
        "event_id": _id("GEVENT"),
        "run_id": run_id,
        "artifact_id": artifact_id,
        "event_type": str(event_type or "GRAPH").upper()[:64],
        "actor_id": actor[:256],
        "reason": event_reason[:2000],
        "detail": bounded_detail,
        "detail_hash": hashlib.sha256(_json(bounded_detail).encode("utf-8")).hexdigest(),
    }


def record_governance_event(event_type: str, actor_id: str, reason: str, *,
                            run_id: Optional[str] = None,
                            artifact_id: Optional[str] = None,
                            detail: Optional[Dict[str, Any]] = None,
                            tx: Any = None,
                            mirror_audit: bool = True) -> Optional[str]:
    """Persist Graph governance evidence and mirror it to Enterprise Audit.

    ``tx`` is used by atomic Runtime transitions.  The Enterprise audit mirror
    is intentionally performed only for standalone calls because invoking the
    global governance connection from inside a transaction would split one
    operation into two commits.  The Graph event remains the authoritative
    join key in both cases.
    """
    document = governance_event_document(
        event_type, actor_id, reason, run_id=run_id, artifact_id=artifact_id, detail=detail,
    )
    params = {
        "event_id": document["event_id"], "run_id": run_id, "artifact_id": artifact_id,
        "event_type": document["event_type"], "actor_id": document["actor_id"],
        "reason": document["reason"], "detail_json": _json(document["detail"]),
    }
    target = tx or connection
    execute_fn = target.execute
    savepoint = None
    # PostgreSQL marks the whole transaction aborted when an optional table is
    # missing.  Probe the insert inside a savepoint so v4.2.x compatibility
    # operations can continue without discarding their earlier writes.
    if tx is not None and str(getattr(connection, "DATABASE_DIALECT", "")).lower() == "postgresql":
        savepoint = "cx_graph_governance_event"
        execute_fn(f"SAVEPOINT {savepoint}")
    try:
        execute_fn(
            "INSERT INTO GRAPH_GOVERNANCE_EVENTS "
            "(EVENT_ID, RUN_ID, ARTIFACT_ID, EVENT_TYPE, ACTOR_ID, REASON, DETAIL_JSON, CREATED_AT) "
            "VALUES (:event_id, :run_id, :artifact_id, :event_type, :actor_id, :reason, :detail_json, CURRENT_TIMESTAMP)",
            params,
        )
    except Exception as exc:
        if any(fragment in str(exc).lower() for fragment in _MISSING_EVENT_TABLE):
            if savepoint:
                execute_fn(f"ROLLBACK TO SAVEPOINT {savepoint}")
                execute_fn(f"RELEASE SAVEPOINT {savepoint}")
            return None
        if savepoint:
            try:
                execute_fn(f"ROLLBACK TO SAVEPOINT {savepoint}")
                execute_fn(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                pass
        raise
    if savepoint:
        execute_fn(f"RELEASE SAVEPOINT {savepoint}")

    if tx is None and mirror_audit:
        try:
            from . import governance_api
            governance_api.record_audit(
                document["actor_id"], f"GRAPH_{document['event_type']}",
                run_id or artifact_id, "ALLOW", "GRAPH_EVENT_RECORDED",
                correlation_id=document["event_id"], detail={
                    "event_type": document["event_type"],
                    "detail_hash": document["detail_hash"],
                }, level="BOUNDED",
            )
        except (ImportError, AttributeError):
            # Community editions do not carry the Enterprise audit module.
            pass
        except Exception as exc:
            if not any(fragment in str(exc).lower() for fragment in _MISSING_EVENT_TABLE):
                raise
    return document["event_id"]


def governance_event_available() -> bool:
    """Probe the optional Graph governance table without masking DB failures."""
    try:
        connection.execute_query_one(
            "SELECT EVENT_ID FROM GRAPH_GOVERNANCE_EVENTS FETCH FIRST 1 ROWS ONLY"
        )
        return True
    except Exception as exc:
        if any(fragment in str(exc).lower() for fragment in _MISSING_EVENT_TABLE):
            return False
        raise


def budget_decision(budget: Dict[str, Any], usage: Dict[str, Any], increment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    increment = increment or {}
    projected = dict(usage or {})
    for key, value in increment.items():
        if isinstance(value, (int, float)):
            projected[key] = projected.get(key, 0) + value
    hard_exceeded = []
    soft_exceeded = []
    for key, limit in (budget or {}).items():
        if not key.startswith("max_") or not isinstance(limit, (int, float)):
            continue
        metric = key[4:]
        current = projected.get(metric, 0)
        if current > limit:
            hard_exceeded.append({"metric": metric, "limit": limit, "value": current})
        elif current >= limit * 0.8:
            soft_exceeded.append({"metric": metric, "limit": limit, "value": current})
    return {"allowed": not hard_exceeded, "hard_exceeded": hard_exceeded, "soft_exceeded": soft_exceeded, "usage": projected}


def record_evaluation(run_id: str, evaluator_name: str, level_name: str,
                      result: Dict[str, Any], node_run_id: Optional[str] = None,
                      input_data: Optional[Dict[str, Any]] = None,
                      route_decision: Optional[str] = None,
                      evaluator_version: str = "1.0") -> str:
    evaluation_id = _id("EVAL")
    connection.execute(
        "INSERT INTO GRAPH_EVALUATIONS (EVALUATION_ID, RUN_ID, NODE_RUN_ID, EVALUATOR_NAME, EVALUATOR_VERSION, LEVEL_NAME, INPUT_JSON, RESULT_JSON, ROUTE_DECISION, CREATED_AT) VALUES (:evaluation_id, :run_id, :node_run_id, :evaluator_name, :evaluator_version, :level_name, :input_json, :result_json, :route_decision, CURRENT_TIMESTAMP)",
        {"evaluation_id": evaluation_id, "run_id": run_id, "node_run_id": node_run_id, "evaluator_name": evaluator_name, "evaluator_version": evaluator_version, "level_name": level_name, "input_json": _json(input_data), "result_json": _json(result), "route_decision": route_decision},
    )
    return evaluation_id


def intervention(run_id: str, action_name: str, actor_id: str, reason: str,
                 node_run_id: Optional[str] = None, evidence: Optional[Dict[str, Any]] = None) -> str:
    if not str(reason or "").strip():
        raise ValueError("Graph intervention requires a non-empty reason")
    intervention_id = _id("INT")
    connection.execute(
        "INSERT INTO GRAPH_INTERVENTIONS (INTERVENTION_ID, RUN_ID, NODE_RUN_ID, ACTION_NAME, ACTOR_ID, REASON, EVIDENCE_JSON, STATUS, CREATED_AT) VALUES (:intervention_id, :run_id, :node_run_id, :action_name, :actor_id, :reason, :evidence_json, 'APPLIED', CURRENT_TIMESTAMP)",
        {"intervention_id": intervention_id, "run_id": run_id, "node_run_id": node_run_id, "action_name": action_name.upper(), "actor_id": actor_id, "reason": reason[:2000], "evidence_json": _json(evidence)},
    )
    return intervention_id


def authorize_node(actor_id: str, resource_scope: Optional[Dict[str, Any]] = None,
                   action: str = "EXECUTE", purpose: str = "GRAPH_RUN") -> Dict[str, Any]:
    """Recheck Enterprise grants when the optional governance module exists."""
    scope = resource_scope or {}
    resource_id = scope.get("resource_id")
    if not resource_id:
        return {"decision": "ALLOW", "reason_code": "NO_GOVERNED_RESOURCE"}
    try:
        from . import governance_api
        result = governance_api.evaluate_access(
            agent_id=actor_id, resource_id=resource_id, action=action,
            classification=scope.get("classification", "INTERNAL"), purpose=purpose,
            environment=scope.get("environment", "PRODUCTION"), correlation_id=scope.get("correlation_id"),
        )
        return result
    except ImportError:
        # Community packages intentionally omit Enterprise governance.  A
        # graph with no governed resource remains executable; a governed
        # resource is rejected only when the Enterprise policy surface exists
        # but cannot be evaluated.
        return {"decision": "ALLOW", "reason_code": "GOVERNANCE_NOT_INCLUDED"}
    except AttributeError:
        return {"decision": "DENY", "reason_code": "GOVERNANCE_UNAVAILABLE"}
