"""Graph-specific authorization, budgets, evaluation, and interventions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import connection


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


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
