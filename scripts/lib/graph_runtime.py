"""Durable Graph Runtime primitives for v4.2.x.

This module deliberately exposes small compare-and-set operations.  A
Scheduler may call them repeatedly after a crash; committed state is guarded
by attempt fencing and immutable state events.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import connection
from . import graph_state
from . import graph_event_contract
from . import graph_scheduler
from .graph_contracts import worker_matches

TERMINAL_RUNS = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"})
LEASE_OPERATIONS = frozenset({"claim", "heartbeat", "checkpoint", "complete", "fail"})


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default if default is not None else value
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    result = {str(k).lower(): v for k, v in dict(row).items()}
    for key in (
        "input_state_json", "output_state_json", "state_json", "delta_json", "budget_json",
        "budget_usage_json", "plan_json", "capability_json", "scope_json", "operations_json",
        "payload_json", "evidence_json", "detail_json", "metadata_json", "inputs_json",
        "reducer_json", "mapping_json", "required_capability_json",
    ):
        if key in result:
            result[key.removesuffix("_json")] = _json(result[key], {})
    return result


def _rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _redact(value: Any) -> Any:
    # Keep every trace, checkpoint, API response, and evidence path on the
    # same recursive redaction implementation.  A shallow redaction would
    # leak credentials nested inside a model result or artifact metadata.
    return graph_state.redact_state(value, allow_secrets=False)


def _limit(value: Any, default: int = 100, maximum: int = 500) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _db_timestamp(value: Any) -> Any:
    """Normalize portable ISO timestamps before binding to database TIMESTAMP columns."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return value


def _trace_tx(tx, run_id: str, event_type: str, *, node_run_id: Optional[str] = None,
              attempt_id: Optional[str] = None, transition_id: Optional[str] = None,
              status: Optional[str] = None, retry_no: int = 0, duration_ms: Optional[int] = None,
              token_count: Optional[int] = None, estimated_cost: Optional[float] = None,
              payload_ref: Optional[str] = None, detail: Optional[Dict[str, Any]] = None) -> str:
    trace_id = _id("TRACE")
    tx.execute(
        "INSERT INTO GRAPH_TRACES (TRACE_ID, RUN_ID, NODE_RUN_ID, ATTEMPT_ID, TRANSITION_ID, "
        "EVENT_TYPE, STATUS, RETRY_NO, DURATION_MS, TOKEN_COUNT, ESTIMATED_COST, PAYLOAD_REF, DETAIL_JSON, CREATED_AT) "
        "VALUES (:trace_id, :run_id, :node_run_id, :attempt_id, :transition_id, :event_type, :status, "
        ":retry_no, :duration_ms, :token_count, :estimated_cost, :payload_ref, :detail_json, CURRENT_TIMESTAMP)",
        {"trace_id": trace_id, "run_id": run_id, "node_run_id": node_run_id,
         "attempt_id": attempt_id, "transition_id": transition_id, "event_type": event_type[:64],
         "status": status, "retry_no": int(retry_no or 0), "duration_ms": duration_ms,
         "token_count": token_count, "estimated_cost": estimated_cost, "payload_ref": payload_ref,
         "detail_json": _canonical(_redact(detail or {}))},
    )
    return trace_id


def _budget_completion_increment(evidence: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Normalize worker evidence to the portable budget metric names."""
    evidence = evidence or {}
    increment: Dict[str, float] = {}
    for source, target in (("token_count", "tokens"), ("estimated_cost", "cost")):
        value = evidence.get(source)
        if isinstance(value, (int, float)) and value >= 0:
            increment[target] = float(value)
    duration_ms = evidence.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        increment["duration_seconds"] = float(duration_ms) / 1000.0
    return increment


def _record_budget_completion_tx(tx, run_id: str, evidence: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    increment = _budget_completion_increment(evidence)
    if not increment:
        return {"allowed": True, "hard_exceeded": [], "soft_exceeded": [], "usage": {}}
    from . import graph_governance
    row = tx.query_one("SELECT BUDGET_JSON, BUDGET_USAGE_JSON FROM GRAPH_RUNS WHERE RUN_ID = :run_id", {"run_id": run_id}) or {}
    budget = _json(row.get("budget_json"), {}) or {}
    usage = _json(row.get("budget_usage_json"), {}) or {}
    decision = graph_governance.budget_decision(budget, usage, increment)
    tx.execute(
        "UPDATE GRAPH_RUNS SET BUDGET_USAGE_JSON = :budget_usage_json, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE RUN_ID = :run_id", {"run_id": run_id, "budget_usage_json": _canonical(decision["usage"])},
    )
    return decision


def _intervention_tx(tx, run_id: str, action_name: str, actor_id: str, reason: str,
                     node_run_id: Optional[str] = None, evidence: Optional[Dict[str, Any]] = None) -> str:
    if not str(reason or "").strip():
        raise ValueError("Graph intervention requires a non-empty reason")
    intervention_id = _id("INT")
    tx.execute(
        "INSERT INTO GRAPH_INTERVENTIONS (INTERVENTION_ID, RUN_ID, NODE_RUN_ID, ACTION_NAME, ACTOR_ID, REASON, EVIDENCE_JSON, STATUS, CREATED_AT) "
        "VALUES (:intervention_id, :run_id, :node_run_id, :action_name, :actor_id, :reason, :evidence_json, 'APPLIED', CURRENT_TIMESTAMP)",
        {"intervention_id": intervention_id, "run_id": run_id, "node_run_id": node_run_id,
         "action_name": str(action_name or "CONTROL").upper()[:64], "actor_id": actor_id,
         "reason": str(reason)[:2000], "evidence_json": _canonical(_redact(evidence or {}))},
    )
    return intervention_id


def _insert_ready_tx(tx, run_id: str, node_key: str, *, iteration_no: int = 0,
                     branch_key: Optional[str] = None, join_key: Optional[str] = None,
                     checkpoint_id: Optional[str] = None, priority: int = 5,
                     available_at: Optional[Any] = None, deadline_at: Optional[Any] = None,
                     required_capabilities: Optional[Iterable[str]] = None,
                     resource_class: Optional[str] = None, status: str = "READY") -> Dict[str, str]:
    """Create one durable Node Run and Ready entry.

    The lookup makes retries and repeated event delivery idempotent.  The
    database unique key remains the final race barrier for concurrent
    schedulers.
    """
    available_at = _db_timestamp(available_at)
    deadline_at = _db_timestamp(deadline_at)
    existing = tx.query_one(
        "SELECT nr.NODE_RUN_ID, rn.READY_ID FROM GRAPH_NODE_RUNS nr JOIN GRAPH_READY_NODES rn "
        "ON rn.NODE_RUN_ID = nr.NODE_RUN_ID WHERE nr.RUN_ID = :run_id AND nr.NODE_KEY = :node_key "
        "AND nr.ITERATION_NO = :iteration_no AND (nr.BRANCH_KEY = :branch_key OR (nr.BRANCH_KEY IS NULL AND :branch_key IS NULL)) "
        "AND rn.STATUS IN ('READY','CLAIMED','WAITING')",
        {"run_id": run_id, "node_key": node_key, "iteration_no": iteration_no, "branch_key": branch_key},
    )
    if existing:
        return {"node_run_id": existing["node_run_id"], "ready_id": existing["ready_id"], "created": False}
    node_run_id = _id("NR")
    ready_id = _id("READY")
    tx.execute(
        "INSERT INTO GRAPH_NODE_RUNS (NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, BRANCH_KEY, JOIN_KEY, "
        "ITERATION_NO, INPUT_CHECKPOINT_ID, CREATED_AT, UPDATED_AT) VALUES (:node_run_id, :run_id, :node_key, "
        ":status, :branch_key, :join_key, :iteration_no, :checkpoint_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"node_run_id": node_run_id, "run_id": run_id, "node_key": node_key, "status": status,
         "branch_key": branch_key, "join_key": join_key, "iteration_no": iteration_no,
         "checkpoint_id": checkpoint_id},
    )
    ready_params = {"ready_id": ready_id, "node_run_id": node_run_id, "run_id": run_id, "node_key": node_key,
                    "status": status, "priority": max(-100, min(int(priority), 100)),
                    "deadline_at": deadline_at, "required_capability_json": _canonical(list(required_capabilities or [])),
                    "resource_class": resource_class}
    if available_at is None:
        ready_sql = (
            "INSERT INTO GRAPH_READY_NODES (READY_ID, NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, PRIORITY, "
            "AVAILABLE_AT, DEADLINE_AT, REQUIRED_CAPABILITY_JSON, RESOURCE_CLASS, CREATED_AT) VALUES "
            "(:ready_id, :node_run_id, :run_id, :node_key, :status, :priority, CURRENT_TIMESTAMP, "
            ":deadline_at, :required_capability_json, :resource_class, CURRENT_TIMESTAMP)"
        )
    else:
        ready_params["available_at"] = available_at
        ready_sql = (
            "INSERT INTO GRAPH_READY_NODES (READY_ID, NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, PRIORITY, "
            "AVAILABLE_AT, DEADLINE_AT, REQUIRED_CAPABILITY_JSON, RESOURCE_CLASS, CREATED_AT) VALUES "
            "(:ready_id, :node_run_id, :run_id, :node_key, :status, :priority, :available_at, "
            ":deadline_at, :required_capability_json, :resource_class, CURRENT_TIMESTAMP)"
        )
    tx.execute(ready_sql, ready_params)
    return {"node_run_id": node_run_id, "ready_id": ready_id, "created": True}


def register_worker(worker_id: str, runtime: str, capabilities: Optional[List[str]] = None,
                    agent_id: Optional[str] = None, node_id: Optional[str] = None) -> bool:
    if not worker_id or not runtime:
        raise ValueError("worker_id and runtime are required")
    existing = connection.execute_query_one(
        "SELECT WORKER_ID, AGENT_ID, NODE_ID, STATUS FROM GRAPH_WORKERS WHERE WORKER_ID = :worker_id",
        {"worker_id": worker_id},
    )
    if existing:
        if str(existing.get("status") or "").upper() in {"REVOKED", "DISABLED"}:
            return False
        if agent_id and existing.get("agent_id") and str(agent_id) != str(existing["agent_id"]):
            raise PermissionError("worker identity cannot be changed during claim")
        if node_id and existing.get("node_id") and str(node_id) != str(existing["node_id"]):
            raise PermissionError("worker node identity cannot be changed during claim")
        effective_agent_id = agent_id if agent_id is not None else existing.get("agent_id")
        effective_node_id = node_id if node_id is not None else existing.get("node_id")
        return connection.execute(
            "UPDATE GRAPH_WORKERS SET RUNTIME = :runtime, CAPABILITY_JSON = :capability_json, "
            "AGENT_ID = :agent_id, NODE_ID = :node_id, STATUS = 'ACTIVE', LAST_HEARTBEAT_AT = CURRENT_TIMESTAMP "
            "WHERE WORKER_ID = :worker_id AND STATUS NOT IN ('REVOKED','DISABLED')",
            {"worker_id": worker_id, "runtime": runtime, "capability_json": _canonical(capabilities or []), "agent_id": effective_agent_id, "node_id": effective_node_id},
        ) > 0
    connection.execute(
        "INSERT INTO GRAPH_WORKERS (WORKER_ID, AGENT_ID, RUNTIME, CAPABILITY_JSON, STATUS, LAST_HEARTBEAT_AT, NODE_ID) "
        "VALUES (:worker_id, :agent_id, :runtime, :capability_json, 'ACTIVE', CURRENT_TIMESTAMP, :node_id)",
        {"worker_id": worker_id, "agent_id": agent_id, "runtime": runtime, "capability_json": _canonical(capabilities or []), "node_id": node_id},
    )
    return True


def create_run(graph_version_id: str, plan_id: str, actor_id: str,
               initial_state: Optional[Dict[str, Any]] = None,
               budget: Optional[Dict[str, Any]] = None,
               idempotency_key: Optional[str] = None) -> str:
    if not graph_version_id or not plan_id or not actor_id:
        raise ValueError("graph_version_id, plan_id, and actor_id are required")
    version = connection.execute_query_one(
        "SELECT STATUS FROM GRAPH_VERSIONS WHERE GRAPH_VERSION_ID = :graph_version_id",
        {"graph_version_id": graph_version_id},
    )
    if not version or str(version.get("status") or "").upper() not in {"PUBLISHED", "DEPRECATED"}:
        raise ValueError("Graph Run requires a published Graph Version")
    if idempotency_key:
        existing = connection.execute_query_one(
            "SELECT RUN_ID FROM GRAPH_RUNS WHERE GRAPH_VERSION_ID = :graph_version_id AND IDEMPOTENCY_KEY = :idempotency_key",
            {"graph_version_id": graph_version_id, "idempotency_key": idempotency_key},
        )
        if existing:
            return existing["run_id"]
    run_id = _id("RUN")
    node_run_id = _id("NR")
    ready_id = _id("READY")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    plan_row = connection.execute_query_one("SELECT PLAN_JSON FROM GRAPH_COMPILE_PLANS WHERE PLAN_ID = :plan_id", {"plan_id": plan_id})
    plan = _json((plan_row or {}).get("plan_json"), {}) or {}
    entry = plan.get("entry_node")
    if not entry:
        raise ValueError("compiled plan has no entry node")
    effective_budget = budget or plan.get("budget") or {}
    statements = [(
        "INSERT INTO GRAPH_RUNS (RUN_ID, GRAPH_VERSION_ID, PLAN_ID, STATUS, ACTOR_ID, IDEMPOTENCY_KEY, INPUT_STATE_JSON, BUDGET_JSON, BUDGET_USAGE_JSON, CREATED_AT, UPDATED_AT) "
        "VALUES (:run_id, :graph_version_id, :plan_id, 'RUNNING', :actor_id, :idempotency_key, :input_state_json, :budget_json, :budget_usage_json, :created_at, :updated_at)",
        {"run_id": run_id, "graph_version_id": graph_version_id, "plan_id": plan_id, "actor_id": actor_id,
         # Some Oracle-compatible engines treat NULLs in composite unique
         # constraints as equal.  An internal key keeps independent Runs
         # portable while an external key remains unchanged when supplied.
         "idempotency_key": idempotency_key or f"__run_{run_id}",
         "input_state_json": _canonical(graph_state.encode_secret_state(initial_state or {})),
         "budget_json": _canonical(effective_budget), "budget_usage_json": _canonical({}), "created_at": now, "updated_at": now},
    ), (
        "INSERT INTO GRAPH_NODE_RUNS (NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, ITERATION_NO, CREATED_AT, UPDATED_AT) "
        "VALUES (:node_run_id, :run_id, :node_key, 'READY', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"node_run_id": node_run_id, "run_id": run_id, "node_key": entry},
    ), (
        "INSERT INTO GRAPH_READY_NODES (READY_ID, NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, PRIORITY, AVAILABLE_AT, CREATED_AT) "
        "VALUES (:ready_id, :node_run_id, :run_id, :node_key, 'READY', 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"ready_id": ready_id, "node_run_id": node_run_id, "run_id": run_id, "node_key": entry},
    )]
    try:
        connection.execute_transaction(statements)
    except Exception:
        # The unique key is the authoritative race barrier.  A concurrent
        # request with the same key returns the already committed Run.
        if idempotency_key:
            existing = connection.execute_query_one(
                "SELECT RUN_ID FROM GRAPH_RUNS WHERE GRAPH_VERSION_ID = :graph_version_id AND IDEMPOTENCY_KEY = :idempotency_key",
                {"graph_version_id": graph_version_id, "idempotency_key": idempotency_key},
            )
            if existing:
                return existing["run_id"]
        raise
    return run_id


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT RUN_ID, GRAPH_VERSION_ID, PLAN_ID, STATUS, ACTOR_ID, IDEMPOTENCY_KEY, INPUT_STATE_JSON, CURRENT_CHECKPOINT_ID, BUDGET_JSON, BUDGET_USAGE_JSON, ERROR_CODE, ERROR_MESSAGE, CREATED_AT, UPDATED_AT, COMPLETED_AT FROM GRAPH_RUNS WHERE RUN_ID = :run_id",
        {"run_id": run_id},
    ))


def list_runs(status: Optional[str] = None, actor_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conditions = ["1 = 1"]
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if status:
        conditions.append("STATUS = :status")
        params["status"] = status.upper()
    if actor_id:
        conditions.append("ACTOR_ID = :actor_id")
        params["actor_id"] = actor_id
    return _rows(connection.execute_query(
        "SELECT RUN_ID, GRAPH_VERSION_ID, PLAN_ID, STATUS, ACTOR_ID, CURRENT_CHECKPOINT_ID, ERROR_CODE, ERROR_MESSAGE, CREATED_AT, UPDATED_AT, COMPLETED_AT FROM GRAPH_RUNS WHERE " + " AND ".join(conditions) + " ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    ))


def _state_for_run(run_id: str) -> Dict[str, Any]:
    row = connection.execute_query_one(
        "SELECT STATE_JSON FROM GRAPH_CHECKPOINTS WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY", {"run_id": run_id}
    )
    if row:
        return _json(row.get("state_json"), {}) or {}
    run = get_run(run_id)
    return (run or {}).get("input_state") or {}


def recover_state(run_id: str) -> Dict[str, Any]:
    """Reconstruct state from the latest checkpoint plus immutable events."""
    state = _state_for_run(run_id)
    checkpoint = connection.execute_query_one(
        "SELECT CHECKPOINT_ID, SEQ_NO FROM GRAPH_CHECKPOINTS WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY", {"run_id": run_id}
    )
    seq = int((checkpoint or {}).get("seq_no") or 0)
    events = connection.execute_query(
        "SELECT SEQ_NO, DELTA_JSON FROM GRAPH_STATE_EVENTS WHERE RUN_ID = :run_id AND SEQ_NO > :seq_no ORDER BY SEQ_NO", {"run_id": run_id, "seq_no": seq}
    )
    for event in events:
        delta = _json(event.get("delta_json"), {}) or {}
        if isinstance(delta, dict):
            state.update(delta)
    return state


def _recover_state_tx(tx, run_id: str) -> Dict[str, Any]:
    """Recover state without leaving the transaction-bound connection."""
    checkpoint = tx.query_one(
        "SELECT CHECKPOINT_ID, SEQ_NO, STATE_JSON FROM GRAPH_CHECKPOINTS "
        "WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY",
        {"run_id": run_id},
    )
    if checkpoint:
        state = _json(checkpoint.get("state_json"), {}) or {}
        seq = int(checkpoint.get("seq_no") or 0)
    else:
        run = tx.query_one("SELECT INPUT_STATE_JSON FROM GRAPH_RUNS WHERE RUN_ID = :run_id", {"run_id": run_id})
        state = _json((run or {}).get("input_state_json"), {}) or {}
        seq = 0
    for event in tx.query(
        "SELECT DELTA_JSON FROM GRAPH_STATE_EVENTS WHERE RUN_ID = :run_id AND SEQ_NO > :seq_no ORDER BY SEQ_NO",
        {"run_id": run_id, "seq_no": seq},
    ):
        delta = _json(event.get("delta_json"), {}) or {}
        if isinstance(delta, dict):
            state.update(delta)
    return state


def _write_checkpoint_tx(tx, run_id: str, delta: Dict[str, Any], actor_id: str,
                         source_attempt_id: Optional[str] = None,
                         snapshot_kind: str = "DELTA",
                         reducer_evidence: Optional[Dict[str, Any]] = None,
                         reducers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    previous = tx.query_one(
        "SELECT CHECKPOINT_ID, SEQ_NO FROM GRAPH_CHECKPOINTS WHERE RUN_ID = :run_id "
        "ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY", {"run_id": run_id},
    )
    previous_state = _recover_state_tx(tx, run_id)
    # Checkpoints retain encrypted SECRET values for recovery while every
    # outward-facing return path remains recursively redacted.
    safe_delta = graph_state.encode_secret_state(delta or {})
    next_state = dict(previous_state)
    reducer_map = dict(reducers or (reducer_evidence or {}).get("reducers") or {})
    for key, value in safe_delta.items():
        reducer = reducer_map.get(key)
        if reducer:
            previous_value = next_state.get(key)
            values = [value] if key not in next_state or previous_value is None else [previous_value, value]
            next_state[key] = graph_state.reduce_values(str(reducer), values)
        else:
            next_state[key] = value
    seq = int((previous or {}).get("seq_no") or 0) + 1
    checkpoint_id = _id("CP")
    event_id = _id("SE")
    state_hash = _hash(next_state)
    tx.execute(
        "INSERT INTO GRAPH_STATE_EVENTS (EVENT_ID, RUN_ID, SEQ_NO, CHECKPOINT_ID, "
        "PRIOR_CHECKPOINT_ID, SOURCE_ATTEMPT_ID, DELTA_JSON, REDUCER_JSON, STATE_HASH, CREATED_AT) "
        "VALUES (:event_id, :run_id, :seq_no, :checkpoint_id, :prior_checkpoint_id, "
        ":source_attempt_id, :delta_json, :reducer_json, :state_hash, CURRENT_TIMESTAMP)",
        {"event_id": event_id, "run_id": run_id, "seq_no": seq, "checkpoint_id": checkpoint_id,
         "prior_checkpoint_id": (previous or {}).get("checkpoint_id"), "source_attempt_id": source_attempt_id,
         "delta_json": _canonical(safe_delta), "reducer_json": _canonical(_redact({**(reducer_evidence or {}), "reducers": reducer_map})),
         "state_hash": state_hash},
    )
    tx.execute(
        "INSERT INTO GRAPH_CHECKPOINTS (CHECKPOINT_ID, RUN_ID, SEQ_NO, PARENT_CHECKPOINT_ID, "
        "STATE_JSON, STATE_HASH, SNAPSHOT_KIND, ACTOR_ID, CREATED_AT) VALUES "
        "(:checkpoint_id, :run_id, :seq_no, :parent_checkpoint_id, :state_json, :state_hash, "
        ":snapshot_kind, :actor_id, CURRENT_TIMESTAMP)",
        {"checkpoint_id": checkpoint_id, "run_id": run_id, "seq_no": seq,
         "parent_checkpoint_id": (previous or {}).get("checkpoint_id"),
         "state_json": _canonical(next_state), "state_hash": state_hash,
         "snapshot_kind": snapshot_kind, "actor_id": actor_id},
    )
    tx.execute(
        "UPDATE GRAPH_RUNS SET CURRENT_CHECKPOINT_ID = :checkpoint_id, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE RUN_ID = :run_id", {"checkpoint_id": checkpoint_id, "run_id": run_id},
    )
    return {"checkpoint_id": checkpoint_id, "event_id": event_id, "seq_no": seq,
            "state": _redact(next_state), "state_hash": state_hash}


def append_checkpoint(run_id: str, delta: Dict[str, Any], actor_id: str,
                      source_attempt_id: Optional[str] = None,
                      snapshot_kind: str = "DELTA",
                      reducer_evidence: Optional[Dict[str, Any]] = None,
                      reducers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return connection.execute_transaction_callback(
        lambda tx: _write_checkpoint_tx(tx, run_id, delta, actor_id, source_attempt_id,
                                         snapshot_kind, reducer_evidence, reducers)
    )


def rotate_run_state(run_id: str, actor_id: str, reason: str,
                     old_keyring: graph_state.StateKeyring,
                     new_keyring: graph_state.StateKeyring) -> Dict[str, Any]:
    """Re-encrypt the current state in a new immutable checkpoint.

    Historical checkpoints and events are never rewritten.  The new FULL
    checkpoint becomes the recovery base, while old key versions remain
    necessary only for historical evidence until the configured retention
    window expires.
    """
    if not run_id or not actor_id or not str(reason or "").strip():
        raise ValueError("state rotation requires run_id, actor_id, and reason")
    if not isinstance(old_keyring, graph_state.StateKeyring) or not isinstance(new_keyring, graph_state.StateKeyring):
        raise TypeError("state rotation requires StateKeyring instances")

    def _rotate(tx):
        run = tx.query_one(
            "SELECT RUN_ID, INPUT_STATE_JSON, CURRENT_CHECKPOINT_ID FROM GRAPH_RUNS WHERE RUN_ID = :run_id",
            {"run_id": run_id},
        )
        if not run:
            raise ValueError("Graph Run not found")
        checkpoint = tx.query_one(
            "SELECT CHECKPOINT_ID, SEQ_NO, STATE_JSON FROM GRAPH_CHECKPOINTS "
            "WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY",
            {"run_id": run_id},
        )
        if checkpoint:
            current = _json(checkpoint.get("state_json"), {}) or {}
            parent_id = checkpoint.get("checkpoint_id")
            seq = int(checkpoint.get("seq_no") or 0)
        else:
            current = _json(run.get("input_state_json"), {}) or {}
            parent_id = None
            seq = 0
        rotated = graph_state.rotate_secret_state(current, old_keyring, new_keyring)
        checkpoint_id = _id("CP")
        event_id = _id("SE")
        state_hash = _hash(rotated)
        metadata = {
            "operation": "STATE_KEY_ROTATION",
            "from_key_versions": old_keyring.versions(),
            "to_key_version": new_keyring.active_version,
        }
        tx.execute(
            "INSERT INTO GRAPH_STATE_EVENTS (EVENT_ID, RUN_ID, SEQ_NO, CHECKPOINT_ID, "
            "PRIOR_CHECKPOINT_ID, DELTA_JSON, REDUCER_JSON, STATE_HASH, CREATED_AT) "
            "VALUES (:event_id, :run_id, :seq_no, :checkpoint_id, :prior_checkpoint_id, "
            ":delta_json, :reducer_json, :state_hash, CURRENT_TIMESTAMP)",
            {"event_id": event_id, "run_id": run_id, "seq_no": seq + 1,
             "checkpoint_id": checkpoint_id, "prior_checkpoint_id": parent_id,
             "delta_json": _canonical(rotated), "reducer_json": _canonical(metadata),
             "state_hash": state_hash},
        )
        tx.execute(
            "INSERT INTO GRAPH_CHECKPOINTS (CHECKPOINT_ID, RUN_ID, SEQ_NO, PARENT_CHECKPOINT_ID, "
            "STATE_JSON, STATE_HASH, SNAPSHOT_KIND, ACTOR_ID, CREATED_AT) VALUES "
            "(:checkpoint_id, :run_id, :seq_no, :parent_checkpoint_id, :state_json, :state_hash, "
            "'FULL', :actor_id, CURRENT_TIMESTAMP)",
            {"checkpoint_id": checkpoint_id, "run_id": run_id, "seq_no": seq + 1,
             "parent_checkpoint_id": parent_id, "state_json": _canonical(rotated),
             "state_hash": state_hash, "actor_id": actor_id},
        )
        tx.execute(
            "UPDATE GRAPH_RUNS SET INPUT_STATE_JSON = :input_state_json, CURRENT_CHECKPOINT_ID = :checkpoint_id, "
            "UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id",
            {"input_state_json": _canonical(rotated), "checkpoint_id": checkpoint_id, "run_id": run_id},
        )
        _intervention_tx(tx, run_id, "ROTATE_STATE_KEY", actor_id, reason,
                         evidence={"checkpoint_id": checkpoint_id, "key_version": new_keyring.active_version})
        _trace_tx(tx, run_id, "STATE_KEY_ROTATED", status="APPLIED",
                  detail={"checkpoint_id": checkpoint_id, "key_version": new_keyring.active_version})
        return {
            "run_id": run_id, "checkpoint_id": checkpoint_id, "event_id": event_id,
            "state_hash": state_hash, "key_version": new_keyring.active_version,
            "state": _redact(rotated),
        }

    return connection.execute_transaction_callback(_rotate)


def rotate_run_state_from_environment(run_id: str, actor_id: str, reason: str) -> Dict[str, Any]:
    """Rotate persisted state using the configured active/retained keyring."""
    keyring = graph_state.StateKeyring.from_environment()
    return rotate_run_state(run_id, actor_id, reason, keyring, keyring)


def _lease_expiry(ttl_seconds: int) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(
        seconds=max(10, min(int(ttl_seconds), 3600))
    )).replace(tzinfo=None)


def _issue_lease_tx(tx, attempt_id: str, worker_id: str, fencing_token: int,
                    scope: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    lease_id = _id("LEASE")
    expires = _lease_expiry(ttl_seconds)
    tx.execute(
        "INSERT INTO GRAPH_LEASE_TOKENS (LEASE_ID, ATTEMPT_ID, WORKER_ID, TOKEN_HASH, FENCING_TOKEN, "
        "OPERATIONS_JSON, SCOPE_JSON, EXPIRES_AT, CREATED_AT) VALUES (:lease_id, :attempt_id, "
        ":worker_id, :token_hash, :fencing_token, :operations_json, :scope_json, :expires_at, CURRENT_TIMESTAMP)",
        {"lease_id": lease_id, "attempt_id": attempt_id, "worker_id": worker_id,
         "token_hash": token_hash, "fencing_token": fencing_token,
         "operations_json": _canonical(sorted(LEASE_OPERATIONS)), "scope_json": _canonical(scope),
         "expires_at": expires},
    )
    return {"token": token, "lease_id": lease_id, "expires_at": expires}


def _verify_lease(token: str, operation: str) -> Optional[Dict[str, Any]]:
    if not token or operation not in LEASE_OPERATIONS:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    lease = _row(connection.execute_query_one(
        "SELECT l.LEASE_ID, l.ATTEMPT_ID, l.WORKER_ID, l.TOKEN_HASH, l.FENCING_TOKEN, l.OPERATIONS_JSON, l.SCOPE_JSON, l.EXPIRES_AT, l.REVOKED_AT, "
        "a.RUN_ID, a.NODE_RUN_ID, nr.NODE_KEY FROM GRAPH_LEASE_TOKENS l "
        "JOIN GRAPH_ATTEMPTS a ON a.ATTEMPT_ID = l.ATTEMPT_ID "
        "JOIN GRAPH_NODE_RUNS nr ON nr.NODE_RUN_ID = a.NODE_RUN_ID "
        "WHERE l.TOKEN_HASH = :token_hash AND a.STATUS = 'RUNNING' "
        "AND a.FENCING_TOKEN = l.FENCING_TOKEN", {"token_hash": token_hash}
    ))
    if not lease or lease.get("revoked_at"):
        return None
    operations = lease.get("operations") or []
    if operation not in operations:
        return None
    expires = lease.get("expires_at")
    if isinstance(expires, datetime):
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return None
    elif expires:
        try:
            parsed = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed <= datetime.now(timezone.utc):
                return None
        except ValueError:
            return None
    return lease


def claim_ready(worker_id: str, runtime: str, capabilities: Optional[List[str]] = None,
                lease_seconds: int = 120, agent_id: Optional[str] = None,
                node_id: Optional[str] = None, node_key: Optional[str] = None,
                scheduler_id: Optional[str] = None, scheduler_lease: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if scheduler_lease:
        if not scheduler_id or not graph_scheduler.verify_scheduler_lease(
            str(scheduler_lease.get("lease_id") or ""), scheduler_id,
            int(scheduler_lease.get("fencing_token") or 0),
        ):
            return None
    if not register_worker(worker_id, runtime, capabilities, agent_id, node_id):
        return None
    capability_set = {str(item) for item in (capabilities or [])}

    def _claim(tx):
        worker = tx.query_one(
            "SELECT WORKER_ID, AGENT_ID, NODE_ID, STATUS FROM GRAPH_WORKERS "
            "WHERE WORKER_ID = :worker_id", {"worker_id": worker_id}
        )
        if not worker or str(worker.get("status") or "").upper() != "ACTIVE":
            return None
        ready_conditions = [
            "rn.STATUS = 'READY'",
            "rn.AVAILABLE_AT <= CURRENT_TIMESTAMP",
            "r.STATUS = 'RUNNING'",
        ]
        ready_params: Dict[str, Any] = {}
        if node_key:
            ready_conditions.append("rn.NODE_KEY = :node_key")
            ready_params["node_key"] = str(node_key)
        candidates = tx.query(
            "SELECT rn.READY_ID, rn.NODE_RUN_ID, rn.RUN_ID, rn.NODE_KEY, rn.PRIORITY, "
            "rn.REQUIRED_CAPABILITY_JSON, rn.RESOURCE_CLASS, rn.DEADLINE_AT "
            "FROM GRAPH_READY_NODES rn JOIN GRAPH_RUNS r ON r.RUN_ID = rn.RUN_ID WHERE "
            + " AND ".join(ready_conditions) + " "
            "ORDER BY rn.PRIORITY DESC, rn.AVAILABLE_AT, rn.READY_ID FETCH FIRST 100 ROWS ONLY",
            ready_params,
        )
        ready = None
        node_policy = None
        for candidate in candidates:
            required = _json(candidate.get("required_capability_json"), []) or []
            if not worker_matches(required, capability_set, candidate.get("resource_class"), runtime):
                continue
            deadline = candidate.get("deadline_at")
            if deadline is not None:
                parsed_deadline = _db_timestamp(deadline)
                if isinstance(parsed_deadline, datetime) and parsed_deadline <= datetime.now(timezone.utc).replace(tzinfo=None):
                    tx.execute(
                        "UPDATE GRAPH_READY_NODES SET STATUS = 'CANCELLED' WHERE READY_ID = :ready_id AND STATUS = 'READY'",
                        {"ready_id": candidate["ready_id"]},
                    )
                    tx.execute(
                        "UPDATE GRAPH_NODE_RUNS SET STATUS = 'REVIEW_REQUIRED', UPDATED_AT = CURRENT_TIMESTAMP "
                        "WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('READY','PENDING')",
                        {"node_run_id": candidate["node_run_id"]},
                    )
                    tx.execute(
                        "UPDATE GRAPH_RUNS SET STATUS = 'REVIEW_REQUIRED', ERROR_CODE = 'NODE_DEADLINE_EXPIRED', "
                        "ERROR_MESSAGE = 'Ready Node deadline expired before claim', UPDATED_AT = CURRENT_TIMESTAMP "
                        "WHERE RUN_ID = :run_id AND STATUS = 'RUNNING'", {"run_id": candidate["run_id"]},
                    )
                    _trace_tx(tx, candidate["run_id"], "NODE_DEADLINE_EXPIRED",
                              status="REVIEW_REQUIRED", detail={"node_key": candidate["node_key"]})
                    continue
            policy = tx.query_one(
                "SELECT r.GRAPH_VERSION_ID, r.ACTOR_ID, n.RESOURCE_SCOPE_JSON, n.BUDGET_JSON AS NODE_BUDGET_JSON, "
                "n.INPUT_SCHEMA_JSON, n.OUTPUT_SCHEMA_JSON, n.CONFIG_JSON, n.CAPABILITY_JSON, "
                "n.SIDE_EFFECT_CLASS, r.ACTOR_ID "
                "FROM GRAPH_NODE_RUNS nr JOIN GRAPH_RUNS r ON r.RUN_ID = nr.RUN_ID "
                "JOIN GRAPH_NODES n ON n.GRAPH_VERSION_ID = r.GRAPH_VERSION_ID AND n.NODE_KEY = nr.NODE_KEY "
                "WHERE nr.NODE_RUN_ID = :node_run_id", {"node_run_id": candidate["node_run_id"]}
            )
            if policy:
                scope = _json(policy.get("resource_scope_json"), {}) or {}
                effective_actor = str(worker.get("agent_id") or agent_id or policy.get("actor_id") or "")
                from . import graph_governance
                decision = graph_governance.authorize_node(effective_actor, scope)
                if str(decision.get("decision") or "ALLOW").upper() not in {"ALLOW", "APPROVED"}:
                    continue
                state = _recover_state_tx(tx, candidate["run_id"])
                input_state, input_errors = graph_state.project_state(
                    state, _json(policy.get("input_schema_json"), {}) or {}, scope,
                )
                if input_errors:
                    tx.execute(
                        "UPDATE GRAPH_READY_NODES SET STATUS = 'CANCELLED' WHERE READY_ID = :ready_id AND STATUS = 'READY'",
                        {"ready_id": candidate["ready_id"]},
                    )
                    tx.execute(
                        "UPDATE GRAPH_NODE_RUNS SET STATUS = 'REVIEW_REQUIRED', UPDATED_AT = CURRENT_TIMESTAMP "
                        "WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('READY','PENDING')",
                        {"node_run_id": candidate["node_run_id"]},
                    )
                    tx.execute(
                        "UPDATE GRAPH_RUNS SET STATUS = 'REVIEW_REQUIRED', ERROR_CODE = 'INPUT_SCHEMA_INVALID', "
                        "ERROR_MESSAGE = :error_message, UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id "
                        "AND STATUS = 'RUNNING'", {"run_id": candidate["run_id"], "error_message": _canonical(input_errors)[:2000]},
                    )
                    _trace_tx(tx, candidate["run_id"], "INPUT_SCHEMA_REJECTED",
                              status="REVIEW_REQUIRED", detail={"node_key": candidate["node_key"], "errors": input_errors})
                    return None
                node_config = _json(policy.get("config_json"), {}) or {}
                scheduler_policy = node_config.get("scheduler_policy") or node_config.get("scheduling") or {}
                scope_values = dict(scope)
                scope_values.update({
                    "run": candidate["run_id"],
                    "graph": policy.get("graph_version_id"),
                    "agent": effective_actor,
                })
                if scheduler_lease:
                    scope_values["scheduler_group"] = scheduler_lease.get("group_id")
                    persisted_policy = graph_scheduler.load_quota_policy(
                        str(scheduler_lease.get("group_id") or ""), scope_values,
                    )
                    if persisted_policy:
                        scheduler_policy = dict(scheduler_policy or {})
                        scheduler_policy["quotas"] = {
                            **(scheduler_policy.get("quotas") or {}),
                            **(persisted_policy.get("quotas") or {}),
                        }
                if scheduler_policy:
                    queue_count = tx.query_one(
                        "SELECT COUNT(*) AS QUEUE_COUNT FROM GRAPH_READY_NODES WHERE RUN_ID = :run_id AND STATUS = 'READY'",
                        {"run_id": candidate["run_id"]},
                    )
                    active_count = tx.query_one(
                        "SELECT COUNT(*) AS ACTIVE_COUNT FROM GRAPH_ATTEMPTS WHERE RUN_ID = :run_id AND STATUS IN ('CLAIMED','RUNNING','WAITING')",
                        {"run_id": candidate["run_id"]},
                    )
                    recent_rows = tx.query(
                        "SELECT STARTED_AT FROM GRAPH_ATTEMPTS WHERE RUN_ID = :run_id ORDER BY STARTED_AT DESC FETCH FIRST 500 ROWS ONLY",
                        {"run_id": candidate["run_id"]},
                    )
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    recent_count = 0
                    for recent in recent_rows:
                        started = _db_timestamp(recent.get("started_at"))
                        if isinstance(started, datetime) and (now - started).total_seconds() <= 60:
                            recent_count += 1
                    decision = graph_scheduler.admission_decision(
                        scheduler_policy,
                        queue_depth=int((queue_count or {}).get("queue_count") or 0),
                        active_count=int((active_count or {}).get("active_count") or 0),
                        recent_count=recent_count,
                        scopes=scope_values,
                        scope_counts={
                            f"{kind.lower()}:{value}": {
                                "queue_depth": int((queue_count or {}).get("queue_count") or 0),
                                "active_count": int((active_count or {}).get("active_count") or 0),
                                "recent_count": recent_count,
                            }
                            for kind, value in scope_values.items() if value is not None
                        },
                    )
                    if not decision["allowed"]:
                        available_at = now + timedelta(seconds=max(0.1, float(decision.get("retry_after_seconds") or 1)))
                        tx.execute(
                            "UPDATE GRAPH_READY_NODES SET AVAILABLE_AT = :available_at WHERE READY_ID = :ready_id AND STATUS = 'READY'",
                            {"available_at": available_at, "ready_id": candidate["ready_id"]},
                        )
                        _trace_tx(
                            tx, candidate["run_id"], "SCHEDULER_BACKPRESSURE",
                            status="READY", detail={"node_key": candidate["node_key"], "reason": decision["reason"]},
                        )
                        continue
                ready = candidate
                node_policy = policy
                ready["input_state"] = input_state
                ready["worker_agent_id"] = effective_actor
                break
        if not ready:
            return None
        ready_id = ready["ready_id"]
        # The conditional update is the database-level claim barrier.  Two
        # workers may read the same candidate, but only one can continue.
        if tx.execute(
            "UPDATE GRAPH_READY_NODES SET STATUS = 'CLAIMED', CLAIMED_AT = CURRENT_TIMESTAMP "
            "WHERE READY_ID = :ready_id AND STATUS = 'READY' AND AVAILABLE_AT <= CURRENT_TIMESTAMP",
            {"ready_id": ready_id},
        ) != 1:
            return None
        # Claim and budget reservation share this transaction. The conditional
        # Ready update is the race barrier; the usage update is committed only
        # when this worker owns that barrier.
        budget_row = tx.query_one(
            "SELECT BUDGET_JSON, BUDGET_USAGE_JSON, STATUS FROM GRAPH_RUNS WHERE RUN_ID = :run_id",
            {"run_id": ready["run_id"]},
        )
        run_budget = _json((budget_row or {}).get("budget_json"), {}) or {}
        if node_policy:
            run_budget.update(_json(node_policy.get("node_budget_json"), {}) or {})
        run_usage = _json((budget_row or {}).get("budget_usage_json"), {}) or {}
        from . import graph_governance
        reservation = graph_governance.budget_decision(
            run_budget, run_usage, {"calls": 1, "iterations": 1},
        )
        if not reservation["allowed"]:
            tx.execute(
                "UPDATE GRAPH_READY_NODES SET STATUS = 'WAITING', CLAIMED_AT = NULL "
                "WHERE READY_ID = :ready_id AND STATUS = 'CLAIMED'", {"ready_id": ready_id},
            )
            tx.execute(
                "UPDATE GRAPH_RUNS SET STATUS = 'REVIEW_REQUIRED', ERROR_CODE = 'BUDGET_EXCEEDED', "
                "ERROR_MESSAGE = :message, UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id "
                "AND STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
                {"run_id": ready["run_id"], "message": _canonical(reservation["hard_exceeded"])[:2000]},
            )
            _trace_tx(tx, ready["run_id"], "BUDGET_BLOCKED", status="REVIEW_REQUIRED",
                      detail={"hard_exceeded": reservation["hard_exceeded"], "node_key": ready["node_key"]})
            return None
        tx.execute(
            "UPDATE GRAPH_RUNS SET BUDGET_USAGE_JSON = :budget_usage_json, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE RUN_ID = :run_id AND STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
            {"run_id": ready["run_id"], "budget_usage_json": _canonical(reservation["usage"])},
        )
        previous = tx.query_one(
            "SELECT COALESCE(MAX(FENCING_TOKEN), 0) AS FENCING_TOKEN FROM GRAPH_ATTEMPTS "
            "WHERE NODE_RUN_ID = :node_run_id", {"node_run_id": ready["node_run_id"]}
        )
        fencing = int((previous or {}).get("fencing_token") or 0) + 1
        attempt_id = _id("ATT")
        expires = _lease_expiry(lease_seconds)
        input_state = ready.get("input_state") or _redact(_recover_state_tx(tx, ready["run_id"]))
        tx.execute(
            "INSERT INTO GRAPH_ATTEMPTS (ATTEMPT_ID, NODE_RUN_ID, RUN_ID, WORKER_ID, STATUS, "
            "FENCING_TOKEN, LEASE_EXPIRES_AT, INPUT_STATE_JSON, IDEMPOTENCY_KEY, STARTED_AT) VALUES "
            "(:attempt_id, :node_run_id, :run_id, :worker_id, 'RUNNING', :fencing_token, "
            ":lease_expires_at, :input_state_json, :idempotency_key, CURRENT_TIMESTAMP)",
            {"attempt_id": attempt_id, "node_run_id": ready["node_run_id"], "run_id": ready["run_id"],
             "worker_id": worker_id, "fencing_token": fencing, "lease_expires_at": expires,
             "input_state_json": _canonical(input_state), "idempotency_key": attempt_id},
        )
        if tx.execute(
            "UPDATE GRAPH_NODE_RUNS SET STATUS = 'RUNNING', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('READY','PENDING')",
            {"node_run_id": ready["node_run_id"]},
        ) != 1:
            raise RuntimeError("ready node changed state during claim")
        lease = _issue_lease_tx(
            tx, attempt_id, worker_id, fencing,
            {
                "run_id": ready["run_id"], "node_run_id": ready["node_run_id"],
                "node_key": ready["node_key"],
                "agent_id": ready.get("worker_agent_id"),
                "state_fields": (_json(node_policy.get("resource_scope_json"), {}) or {}).get("state_fields") if node_policy else None,
            },
            lease_seconds,
        )
        return {"attempt_id": attempt_id, "lease_token": lease["token"], "run_id": ready["run_id"],
                "node_run_id": ready["node_run_id"], "node_key": ready["node_key"],
                "fencing_token": fencing, "input_state": input_state,
                "lease_expires_at": lease["expires_at"]}

    return connection.execute_transaction_callback(_claim)


def heartbeat(lease_token: str, lease_seconds: int = 120) -> bool:
    lease = _verify_lease(lease_token, "heartbeat")
    if not lease:
        return False
    expires = _lease_expiry(lease_seconds)

    def _heartbeat(tx):
        updated = tx.execute(
            "UPDATE GRAPH_ATTEMPTS SET LEASE_EXPIRES_AT = :expires_at WHERE ATTEMPT_ID = :attempt_id "
            "AND FENCING_TOKEN = :fencing_token AND STATUS = 'RUNNING'",
            {"expires_at": expires, "attempt_id": lease["attempt_id"], "fencing_token": lease["fencing_token"]},
        )
        if updated:
            tx.execute(
                "UPDATE GRAPH_LEASE_TOKENS SET EXPIRES_AT = :expires_at WHERE LEASE_ID = :lease_id "
                "AND ATTEMPT_ID = :attempt_id AND FENCING_TOKEN = :fencing_token AND REVOKED_AT IS NULL",
                {"expires_at": expires, "lease_id": lease["lease_id"], "attempt_id": lease["attempt_id"],
                 "fencing_token": lease["fencing_token"]},
            )
        return updated > 0

    return bool(connection.execute_transaction_callback(_heartbeat))


def _plan_for_run(run_id: str) -> Dict[str, Any]:
    row = connection.execute_query_one(
        "SELECT p.PLAN_JSON FROM GRAPH_RUNS r JOIN GRAPH_COMPILE_PLANS p ON p.PLAN_ID = r.PLAN_ID WHERE r.RUN_ID = :run_id", {"run_id": run_id}
    )
    return _json((row or {}).get("plan_json"), {}) or {}


def _selected_edges(plan: Dict[str, Any], node_key: str, state: Dict[str, Any], run_id: str) -> List[Dict[str, Any]]:
    from .graph_compiler import evaluate_expression_ast
    selected = []
    for edge in plan.get("edges", []):
        if edge.get("source_node_key") != node_key:
            continue
        config = edge.get("config") or {}
        if config.get("enabled") is False:
            continue
        decision = str(edge.get("decision_type") or "FIXED").upper()
        context = {"state": state, "run": {"run_id": run_id}, "node": {"node_key": node_key}}
        if decision in {"EXPRESSION", "RULES"}:
            if decision == "RULES":
                rules = config.get("rules") or edge.get("condition") or []
                if isinstance(rules, dict):
                    rules = [rules]
                if not any(evaluate_expression_ast(rule.get("when") or rule.get("condition") or {}, context) for rule in rules if isinstance(rule, dict)):
                    continue
            elif not evaluate_expression_ast(edge.get("condition") or {}, context):
                continue
        selected.append(edge)
    return selected


def _node_from_plan(plan: Dict[str, Any], node_key: str) -> Dict[str, Any]:
    indexed = plan.get("node_index") or {}
    if node_key in indexed:
        return indexed[node_key] or {}
    return next((node for node in plan.get("nodes", []) if node.get("node_key") == node_key), {})


def _ensure_join_state_tx(tx, run_id: str, node_key: str, join_key: str,
                          strategy: str, expected_count: int, required_count: int,
                          edge_id: str, contribution: Dict[str, Any], reducer: str) -> Dict[str, Any]:
    join_id = _hash({"run_id": run_id, "node_key": node_key, "join_key": join_key})[:128]
    dialect = str(getattr(connection, "DATABASE_DIALECT", "") or "").lower()
    params = {"join_id": join_id, "run_id": run_id, "node_key": node_key, "join_key": join_key,
              "strategy": strategy, "expected_count": max(1, expected_count),
              "required_count": max(1, required_count)}
    if dialect == "postgresql":
        tx.execute(
            "INSERT INTO GRAPH_JOIN_STATES (JOIN_ID, RUN_ID, NODE_KEY, JOIN_KEY, STRATEGY, REQUIRED_COUNT, EXPECTED_COUNT, INPUTS_JSON, REDUCER_JSON) "
            "VALUES (:join_id, :run_id, :node_key, :join_key, :strategy, :required_count, :expected_count, :inputs_json, :reducer_json) "
            "ON CONFLICT (JOIN_ID) DO NOTHING",
            {**params, "inputs_json": _canonical({}), "reducer_json": _canonical({"reducer": reducer})},
        )
    else:
        tx.execute(
            "MERGE INTO GRAPH_JOIN_STATES dst USING (SELECT :join_id AS JOIN_ID" + connection.merge_scalar_suffix() + ") src ON (dst.JOIN_ID = src.JOIN_ID) "
            "WHEN NOT MATCHED THEN INSERT (JOIN_ID, RUN_ID, NODE_KEY, JOIN_KEY, STRATEGY, REQUIRED_COUNT, EXPECTED_COUNT, INPUTS_JSON, REDUCER_JSON) "
            "VALUES (:join_id, :run_id, :node_key, :join_key, :strategy, :required_count, :expected_count, :inputs_json, :reducer_json)",
            {**params, "inputs_json": _canonical({}), "reducer_json": _canonical({"reducer": reducer})},
        )
    row = tx.query_one(
        "SELECT JOIN_ID, RUN_ID, NODE_KEY, JOIN_KEY, STRATEGY, REQUIRED_COUNT, EXPECTED_COUNT, ACCEPTED_COUNT, STATUS, INPUTS_JSON, REDUCER_JSON "
        "FROM GRAPH_JOIN_STATES WHERE JOIN_ID = :join_id", {"join_id": join_id},
    )
    if not row:
        raise RuntimeError("join state could not be created")
    inputs = _json(row.get("inputs_json"), {}) or {}
    inputs[str(edge_id)] = _redact(contribution)
    accepted = len(inputs)
    strategy = str(row.get("strategy") or strategy).upper()
    required = int(row.get("required_count") or required_count or 1)
    expected = int(row.get("expected_count") or expected_count or 1)
    ready = {
        "ALL": accepted >= expected,
        "ANY": accepted >= 1,
        "N_OF_M": accepted >= required,
        "QUORUM": accepted >= max(required, (expected // 2) + 1),
        "FIRST_SUCCESS": accepted >= 1,
    }.get(strategy, False)
    status = "READY" if ready else "WAITING"
    tx.execute(
        "UPDATE GRAPH_JOIN_STATES SET ACCEPTED_COUNT = :accepted_count, INPUTS_JSON = :inputs_json, STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE JOIN_ID = :join_id AND STATUS NOT IN ('COMMITTED','CANCELLED')",
        {"accepted_count": accepted, "inputs_json": _canonical(inputs), "status": status, "join_id": join_id},
    )
    row.update({"inputs_json": _canonical(inputs), "inputs": inputs, "accepted_count": accepted, "status": status,
                "join_id": join_id, "strategy": strategy})
    return row


def _ensure_branch_tx(tx, run_id: str, parent_node_run_id: str, branch_key: str,
                      edge_id: Optional[str], node_key: str, checkpoint_id: Optional[str]) -> None:
    branch_id = _hash({"run_id": run_id, "branch_key": branch_key, "node_key": node_key})[:128]
    dialect = str(getattr(connection, "DATABASE_DIALECT", "") or "").lower()
    params = {"branch_id": branch_id, "run_id": run_id, "parent_node_run_id": parent_node_run_id,
              "branch_key": branch_key, "source_edge_id": edge_id, "node_key": node_key,
              "checkpoint_id": checkpoint_id, "metadata_json": _canonical({})}
    if dialect == "postgresql":
        tx.execute(
            "INSERT INTO GRAPH_RUN_BRANCHES (BRANCH_ID, RUN_ID, PARENT_NODE_RUN_ID, BRANCH_KEY, SOURCE_EDGE_ID, NODE_KEY, INPUT_CHECKPOINT_ID, METADATA_JSON) "
            "VALUES (:branch_id, :run_id, :parent_node_run_id, :branch_key, :source_edge_id, :node_key, :checkpoint_id, :metadata_json) "
            "ON CONFLICT (BRANCH_ID) DO NOTHING", params,
        )
    else:
        tx.execute(
            "MERGE INTO GRAPH_RUN_BRANCHES dst USING (SELECT :branch_id AS BRANCH_ID" + connection.merge_scalar_suffix() + ") src ON (dst.BRANCH_ID = src.BRANCH_ID) "
            "WHEN NOT MATCHED THEN INSERT (BRANCH_ID, RUN_ID, PARENT_NODE_RUN_ID, BRANCH_KEY, SOURCE_EDGE_ID, NODE_KEY, INPUT_CHECKPOINT_ID, METADATA_JSON) "
            "VALUES (:branch_id, :run_id, :parent_node_run_id, :branch_key, :source_edge_id, :node_key, :checkpoint_id, :metadata_json)", params,
        )


def _activate_downstream_tx(tx, run_id: str, node_run_id: str, checkpoint_id: str,
                            state: Dict[str, Any], actor_id: str,
                            evidence: Dict[str, Any], attempt_id: Optional[str] = None,
                            forced_edge_id: Optional[str] = None) -> None:
    node = tx.query_one(
        "SELECT NODE_KEY, ITERATION_NO, BRANCH_KEY, JOIN_KEY, STATUS FROM GRAPH_NODE_RUNS WHERE NODE_RUN_ID = :node_run_id",
        {"node_run_id": node_run_id},
    )
    if not node:
        return
    plan_row = tx.query_one(
        "SELECT p.PLAN_JSON FROM GRAPH_RUNS r JOIN GRAPH_COMPILE_PLANS p ON p.PLAN_ID = r.PLAN_ID "
        "WHERE r.RUN_ID = :run_id", {"run_id": run_id}
    )
    plan = _json((plan_row or {}).get("plan_json"), {}) or {}
    selected = _selected_edges(plan, node["node_key"], state, run_id)
    if forced_edge_id:
        selected = [edge for edge in plan.get("edges", [])
                    if edge.get("source_node_key") == node["node_key"]
                    and str(edge.get("edge_id")) == str(forced_edge_id)]
    source_plan_node = _node_from_plan(plan, node["node_key"])
    for edge_index, edge in enumerate(selected):
        target = edge.get("target_node_key")
        if not target:
            continue
        target_node = _node_from_plan(plan, target)
        config = edge.get("config") or {}
        cycle_target = target in set(plan.get("cycle_nodes") or []) and (
            node["node_key"] in set(plan.get("cycle_nodes") or []) or edge.get("edge_kind") == "CYCLE"
        )
        iteration_no = int(node.get("iteration_no") or 0) + (1 if cycle_target else 0)
        branch_key = config.get("branch_key") or node.get("branch_key")
        if len(selected) > 1 or edge.get("edge_kind") in {"BRANCH", "FAN_OUT"}:
            branch_key = branch_key or f"{node_run_id}:{edge.get('edge_id') or edge_index}"
        join_spec = (plan.get("join_specs") or {}).get(target)
        join_state = None
        if join_spec:
            join_key = str(edge.get("join_key") or config.get("join_key") or join_spec.get("join_key"))
            strategy = str(config.get("join_strategy") or join_spec.get("strategy") or "ALL").upper()
            required = int(config.get("n") or config.get("required_count") or join_spec.get("required_count") or 1)
            join_state = _ensure_join_state_tx(
                tx, run_id, target, join_key, strategy, int(join_spec.get("expected_count") or 1), required,
                str(edge.get("edge_id") or ""), {"state": state, "edge_id": edge.get("edge_id"), "branch_key": branch_key},
                str(config.get("reducer") or join_spec.get("reducer") or "REPLACE").upper(),
            )
            if str(join_state.get("status") or "") != "READY":
                continue
            # A committed Join is a one-shot barrier.  Late branches are still
            # traced but cannot replace the accepted result.
            tx.execute("UPDATE GRAPH_JOIN_STATES SET STATUS = 'COMMITTED', UPDATED_AT = CURRENT_TIMESTAMP WHERE JOIN_ID = :join_id AND STATUS = 'READY'", {"join_id": join_state["join_id"]})
            branch_key = join_key
        if branch_key:
            _ensure_branch_tx(tx, run_id, node_run_id, str(branch_key), edge.get("edge_id"), target, checkpoint_id)
        wait_kind = str(config.get("wait_kind") or target_node.get("node_type") or "").upper()
        is_wait = wait_kind in {"EVENT", "TIMER", "HUMAN"} or str(edge.get("decision_type") or "").upper() in {"EVENT", "HUMAN"}
        deadline = None
        timeout_seconds = config.get("timeout_seconds") or target_node.get("config", {}).get("timeout_seconds")
        if timeout_seconds:
            deadline = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(1, int(timeout_seconds)))
        created = _insert_ready_tx(
            tx, run_id, target, iteration_no=iteration_no, branch_key=branch_key,
            join_key=(join_state or {}).get("join_key") or edge.get("join_key"), checkpoint_id=checkpoint_id,
            priority=int(config.get("priority", 5) or 5), deadline_at=deadline,
            required_capabilities=config.get("required_capabilities") or target_node.get("capabilities") or [],
            resource_class=config.get("resource_class"), status="WAITING" if is_wait else "READY",
        )
        if is_wait:
            existing_wait = tx.query_one(
                "SELECT WAIT_ID FROM GRAPH_WAIT_SUBSCRIPTIONS WHERE NODE_RUN_ID = :node_run_id",
                {"node_run_id": created["node_run_id"]},
            )
            if not existing_wait:
                wait_id = _id("WAIT")
                tx.execute(
                    "INSERT INTO GRAPH_WAIT_SUBSCRIPTIONS (WAIT_ID, RUN_ID, NODE_RUN_ID, WAIT_KIND, EVENT_TYPE, CORRELATION_KEY, STATUS, DEADLINE_AT, PAYLOAD_JSON, CREATED_AT) "
                    "VALUES (:wait_id, :run_id, :node_run_id, :wait_kind, :event_type, :correlation_key, 'WAITING', :deadline_at, :payload_json, CURRENT_TIMESTAMP)",
                    {"wait_id": wait_id, "run_id": run_id, "node_run_id": created["node_run_id"], "wait_kind": wait_kind,
                     "event_type": config.get("event_type"), "correlation_key": config.get("correlation_key"),
                     "deadline_at": deadline, "payload_json": _canonical({"join": (join_state or {}).get("inputs", {})})},
                )
            tx.execute("UPDATE GRAPH_RUNS SET STATUS = 'WAITING', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'RUNNING'", {"run_id": run_id})
        tx.execute(
            "INSERT INTO GRAPH_TRANSITIONS (TRANSITION_ID, RUN_ID, NODE_RUN_ID, ATTEMPT_ID, FROM_NODE_KEY, "
            "TO_NODE_KEY, EDGE_ID, TRANSITION_TYPE, STATUS, CHECKPOINT_ID, FENCING_TOKEN, EVIDENCE_JSON, "
            "ACTOR_ID, CREATED_AT) VALUES (:transition_id, :run_id, :node_run_id, :attempt_id, "
            ":from_node_key, :to_node_key, :edge_id, 'EDGE', 'COMMITTED', :checkpoint_id, "
            ":fencing_token, :evidence_json, :actor_id, CURRENT_TIMESTAMP)",
            {"transition_id": _id("TR"), "run_id": run_id, "node_run_id": node_run_id,
             "attempt_id": attempt_id if edge_index == 0 else None, "from_node_key": node["node_key"], "to_node_key": target,
             "edge_id": edge.get("edge_id"), "checkpoint_id": checkpoint_id,
             "fencing_token": None, "evidence_json": _canonical(_redact(evidence or {})), "actor_id": actor_id},
        )
        _trace_tx(tx, run_id, "EDGE_SELECTED", node_run_id=node_run_id, attempt_id=attempt_id,
                  status="WAITING" if is_wait else "READY", detail={"edge_id": edge.get("edge_id"), "target": target,
                                                                     "join": (join_state or {}).get("join_id")})
    if not selected and node["node_key"] in set(plan.get("exit_nodes") or []):
        tx.execute(
            "UPDATE GRAPH_RUNS SET STATUS = 'SUCCEEDED', UPDATED_AT = CURRENT_TIMESTAMP, "
            "COMPLETED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS NOT IN "
            "('FAILED','CANCELLED','SUCCEEDED')", {"run_id": run_id},
        )
    elif not selected:
        tx.execute(
            "UPDATE GRAPH_RUNS SET STATUS = 'REVIEW_REQUIRED', ERROR_CODE = 'NO_ROUTE', ERROR_MESSAGE = 'No eligible outgoing edge', UPDATED_AT = CURRENT_TIMESTAMP, COMPLETED_AT = CURRENT_TIMESTAMP "
            "WHERE RUN_ID = :run_id AND STATUS NOT IN ('FAILED','CANCELLED','SUCCEEDED')", {"run_id": run_id},
        )


def complete_attempt(lease_token: str, output_state: Optional[Dict[str, Any]], actor_id: str,
                     evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lease = _verify_lease(lease_token, "complete")
    if not lease:
        raise PermissionError("invalid, expired, or revoked lease token")
    def _complete(tx):
        attempt = tx.query_one(
            "SELECT ATTEMPT_ID, NODE_RUN_ID, RUN_ID, FENCING_TOKEN, STATUS, WORKER_ID FROM GRAPH_ATTEMPTS "
            "WHERE ATTEMPT_ID = :attempt_id", {"attempt_id": lease["attempt_id"]}
        )
        if not attempt or attempt.get("status") != "RUNNING" or int(attempt.get("fencing_token") or 0) != int(lease.get("fencing_token") or 0):
            raise RuntimeError("stale attempt fencing token")
        node_policy = tx.query_one(
            "SELECT n.OUTPUT_SCHEMA_JSON, n.CONFIG_JSON, n.RESOURCE_SCOPE_JSON, n.SIDE_EFFECT_CLASS "
            "FROM GRAPH_NODE_RUNS nr JOIN GRAPH_RUNS r ON r.RUN_ID = nr.RUN_ID "
            "JOIN GRAPH_NODES n ON n.GRAPH_VERSION_ID = r.GRAPH_VERSION_ID AND n.NODE_KEY = nr.NODE_KEY "
            "WHERE nr.NODE_RUN_ID = :node_run_id", {"node_run_id": attempt["node_run_id"]}
        ) or {}
        node_config = _json(node_policy.get("config_json"), {}) or {}
        result_limit = node_config.get("max_output_bytes", node_config.get("result_max_bytes"))
        safe_output, output_errors = graph_state.prepare_output(
            output_state or {}, _json(node_policy.get("output_schema_json"), {}) or {}, result_limit,
        )
        if output_errors:
            raise ValueError(_canonical(output_errors)[:4000])
        checkpoint = _write_checkpoint_tx(
            tx, attempt["run_id"], safe_output, actor_id, attempt["attempt_id"],
            reducer_evidence=evidence or {}, reducers=(evidence or {}).get("reducers"),
        )
        if tx.execute(
            "UPDATE GRAPH_ATTEMPTS SET STATUS = 'SUCCEEDED', OUTPUT_STATE_JSON = :output_state_json, "
            "COMPLETED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id AND STATUS = 'RUNNING' "
            "AND FENCING_TOKEN = :fencing_token",
            {"attempt_id": attempt["attempt_id"], "output_state_json": _canonical(safe_output),
             "fencing_token": lease["fencing_token"]},
        ) != 1:
            raise RuntimeError("attempt completion lost fencing race")
        if tx.execute(
            "UPDATE GRAPH_NODE_RUNS SET STATUS = 'SUCCEEDED', OUTPUT_CHECKPOINT_ID = :checkpoint_id, "
            "UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'RUNNING'",
            {"node_run_id": attempt["node_run_id"], "checkpoint_id": checkpoint["checkpoint_id"]},
        ) != 1:
            raise RuntimeError("node run completion lost state race")
        tx.execute(
            "UPDATE GRAPH_READY_NODES SET STATUS = 'DONE' WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'CLAIMED'",
            {"node_run_id": attempt["node_run_id"]},
        )
        budget_result = _record_budget_completion_tx(tx, attempt["run_id"], evidence)
        if not budget_result["allowed"]:
            tx.execute(
                "UPDATE GRAPH_RUNS SET STATUS = 'REVIEW_REQUIRED', ERROR_CODE = 'BUDGET_EXCEEDED', "
                "ERROR_MESSAGE = :message, COMPLETED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE RUN_ID = :run_id AND STATUS NOT IN ('CANCELLED','SUCCEEDED','FAILED')",
                {"run_id": attempt["run_id"], "message": _canonical(budget_result["hard_exceeded"])[:2000]},
            )
            _trace_tx(tx, attempt["run_id"], "BUDGET_BLOCKED", node_run_id=attempt["node_run_id"],
                      attempt_id=attempt["attempt_id"], status="REVIEW_REQUIRED",
                      detail={"hard_exceeded": budget_result["hard_exceeded"]})
        run_status = tx.query_one("SELECT STATUS FROM GRAPH_RUNS WHERE RUN_ID = :run_id", {"run_id": attempt["run_id"]})
        if budget_result["allowed"] and str((run_status or {}).get("status") or "").upper() not in {"CANCELLED", "PAUSED", "REVIEW_REQUIRED"}:
            _activate_downstream_tx(tx, attempt["run_id"], attempt["node_run_id"], checkpoint["checkpoint_id"],
                                    safe_output, actor_id, evidence or {}, attempt["attempt_id"])
        _trace_tx(
            tx, attempt["run_id"], "ATTEMPT_COMPLETED", node_run_id=attempt["node_run_id"],
            attempt_id=attempt["attempt_id"], status="SUCCEEDED", token_count=(evidence or {}).get("token_count"),
            estimated_cost=(evidence or {}).get("estimated_cost"), detail=evidence or {},
        )
        tx.execute(
            "UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id "
            "AND FENCING_TOKEN = :fencing_token AND REVOKED_AT IS NULL",
            {"attempt_id": attempt["attempt_id"], "fencing_token": lease["fencing_token"]},
        )
        return {"attempt_id": attempt["attempt_id"], "checkpoint": checkpoint,
                "status": "SUCCEEDED" if budget_result["allowed"] else "REVIEW_REQUIRED",
                "worker_id": attempt.get("worker_id")}

    return connection.execute_transaction_callback(_complete)


def _activate_downstream(run_id: str, node_run_id: str, checkpoint_id: str, state: Dict[str, Any], actor_id: str, evidence: Dict[str, Any]) -> None:
    """Compatibility wrapper for callers outside the completion path."""
    return connection.execute_transaction_callback(
        lambda tx: _activate_downstream_tx(tx, run_id, node_run_id, checkpoint_id, state, actor_id, evidence)
    )


def fail_attempt(lease_token: str, error_code: str, error_message: str, actor_id: str) -> bool:
    lease = _verify_lease(lease_token, "fail")
    if not lease:
        raise PermissionError("invalid lease token")
    def _fail(tx):
        attempt = tx.query_one(
            "SELECT ATTEMPT_ID, NODE_RUN_ID, RUN_ID, FENCING_TOKEN, STATUS, WORKER_ID FROM GRAPH_ATTEMPTS WHERE ATTEMPT_ID = :attempt_id",
            {"attempt_id": lease["attempt_id"]},
        )
        if not attempt or attempt.get("status") != "RUNNING" or int(attempt.get("fencing_token") or 0) != int(lease.get("fencing_token") or 0):
            return False
        updated = tx.execute(
            "UPDATE GRAPH_ATTEMPTS SET STATUS = 'FAILED', ERROR_CODE = :error_code, "
            "ERROR_MESSAGE = :error_message, COMPLETED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id "
            "AND STATUS = 'RUNNING' AND FENCING_TOKEN = :fencing_token",
            {"error_code": error_code, "error_message": str(error_message or "")[:2000], "attempt_id": lease["attempt_id"],
             "fencing_token": lease["fencing_token"]},
        )
        if not updated:
            return False
        if attempt:
            plan_row = tx.query_one(
                "SELECT p.PLAN_JSON FROM GRAPH_RUNS r JOIN GRAPH_COMPILE_PLANS p ON p.PLAN_ID = r.PLAN_ID WHERE r.RUN_ID = :run_id",
                {"run_id": attempt["run_id"]},
            )
            plan = _json((plan_row or {}).get("plan_json"), {}) or {}
            node = _node_from_plan(plan, str(lease.get("node_key") or ""))
            if not node:
                node_row = tx.query_one(
                    "SELECT NODE_KEY FROM GRAPH_NODE_RUNS WHERE NODE_RUN_ID = :node_run_id",
                    {"node_run_id": attempt["node_run_id"]},
                )
                node = _node_from_plan(plan, str((node_row or {}).get("node_key") or ""))
            retry = (node.get("config") or {}).get("retry_policy") or {}
            max_attempts = int(retry.get("max_attempts") or (int(retry.get("max_retries") or 0) + 1) or 1)
            attempts_used = int((tx.query_one(
                "SELECT COUNT(*) AS ATTEMPT_COUNT FROM GRAPH_ATTEMPTS WHERE NODE_RUN_ID = :node_run_id",
                {"node_run_id": attempt["node_run_id"]},
            ) or {}).get("attempt_count") or 0)
            side_effect = str(node.get("side_effect_class") or "NONE").upper()
            # A confirmation or compensation policy describes how a human may
            # resolve the uncertainty; it never makes an automatic repeat of
            # a non-idempotent external effect safe.
            safe_retry = side_effect != "NON_IDEMPOTENT"
            uncertain = str(error_code or "").upper() in {
                "UNCERTAIN_OUTCOME", "OUTCOME_UNKNOWN", "NON_IDEMPOTENT_UNCERTAIN",
            }
            if attempts_used < max_attempts and safe_retry:
                tx.execute(
                    "UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id",
                    {"node_run_id": attempt["node_run_id"]},
                )
                tx.execute(
                    "UPDATE GRAPH_READY_NODES SET STATUS = 'READY', CLAIMED_AT = NULL, AVAILABLE_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('CLAIMED','WAITING')",
                    {"node_run_id": attempt["node_run_id"]},
                )
                tx.execute(
                    "UPDATE GRAPH_RUNS SET STATUS = 'RUNNING', ERROR_CODE = NULL, ERROR_MESSAGE = NULL, UPDATED_AT = CURRENT_TIMESTAMP, COMPLETED_AT = NULL WHERE RUN_ID = :run_id AND STATUS NOT IN ('CANCELLED','SUCCEEDED')",
                    {"run_id": attempt["run_id"]},
                )
                _trace_tx(tx, attempt["run_id"], "RETRY_SCHEDULED", node_run_id=attempt["node_run_id"],
                          attempt_id=attempt["attempt_id"], status="READY", retry_no=attempts_used,
                          detail={"error_code": error_code, "reason": str(error_message or "")[:500]})
            else:
                terminal_status = "REVIEW_REQUIRED" if uncertain else "FAILED"
                tx.execute(
                    "UPDATE GRAPH_NODE_RUNS SET STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id",
                    {"node_run_id": attempt["node_run_id"], "status": terminal_status},
                )
                tx.execute(
                    "UPDATE GRAPH_RUNS SET STATUS = :status, ERROR_CODE = :error_code, ERROR_MESSAGE = :error_message, "
                    "UPDATED_AT = CURRENT_TIMESTAMP, COMPLETED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id "
                    "AND STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
                    {"run_id": attempt["run_id"], "status": terminal_status, "error_code": error_code,
                     "error_message": str(error_message or "")[:2000]},
                )
                _trace_tx(tx, attempt["run_id"], "ATTEMPT_FAILED", node_run_id=attempt["node_run_id"],
                          attempt_id=attempt["attempt_id"], status=terminal_status, retry_no=attempts_used,
                          detail={"error_code": error_code, "error_message": str(error_message or "")[:500],
                                  "uncertain_outcome": uncertain, "automatic_retry": False if side_effect == "NON_IDEMPOTENT" else None})
        tx.execute(
            "UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id "
            "AND FENCING_TOKEN = :fencing_token AND REVOKED_AT IS NULL",
            {"attempt_id": lease["attempt_id"], "fencing_token": lease["fencing_token"]},
        )
        return True

    return bool(connection.execute_transaction_callback(_fail))


def reap_expired_leases(limit: int = 100) -> int:
    """Fence expired attempts and put recoverable node work back in READY."""
    limit = max(1, min(int(limit), 1000))

    def _reap(tx):
        attempts = tx.query(
            "SELECT ATTEMPT_ID, NODE_RUN_ID, RUN_ID, FENCING_TOKEN FROM GRAPH_ATTEMPTS "
            "WHERE STATUS = 'RUNNING' AND LEASE_EXPIRES_AT <= CURRENT_TIMESTAMP "
            "ORDER BY LEASE_EXPIRES_AT FETCH FIRST :limit ROWS ONLY", {"limit": limit}
        )
        count = 0
        for attempt in attempts:
            if tx.execute(
                "UPDATE GRAPH_ATTEMPTS SET STATUS = 'STALE', ERROR_CODE = 'LEASE_EXPIRED', "
                "ERROR_MESSAGE = 'Worker lease expired; work is eligible for recovery', "
                "COMPLETED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id "
                "AND STATUS = 'RUNNING' AND FENCING_TOKEN = :fencing_token",
                {"attempt_id": attempt["attempt_id"], "fencing_token": attempt["fencing_token"]},
            ) != 1:
                continue
            tx.execute(
                "UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'RUNNING'",
                {"node_run_id": attempt["node_run_id"]},
            )
            tx.execute(
                "UPDATE GRAPH_READY_NODES SET STATUS = 'READY', CLAIMED_AT = NULL "
                "WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'CLAIMED'",
                {"node_run_id": attempt["node_run_id"]},
            )
            tx.execute(
                "UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id "
                "AND FENCING_TOKEN = :fencing_token AND REVOKED_AT IS NULL",
                {"attempt_id": attempt["attempt_id"], "fencing_token": attempt["fencing_token"]},
            )
            _trace_tx(tx, attempt["run_id"], "LEASE_EXPIRED", node_run_id=attempt["node_run_id"],
                      attempt_id=attempt["attempt_id"], status="READY")
            count += 1
        expired_waits = tx.query(
            "SELECT WAIT_ID, RUN_ID, NODE_RUN_ID FROM GRAPH_WAIT_SUBSCRIPTIONS WHERE STATUS = 'WAITING' "
            "AND DEADLINE_AT IS NOT NULL AND DEADLINE_AT <= CURRENT_TIMESTAMP FETCH FIRST :limit ROWS ONLY",
            {"limit": limit},
        )
        for wait in expired_waits:
            tx.execute(
                "UPDATE GRAPH_WAIT_SUBSCRIPTIONS SET STATUS = 'EXPIRED', RESOLVED_AT = CURRENT_TIMESTAMP WHERE WAIT_ID = :wait_id AND STATUS = 'WAITING'",
                {"wait_id": wait["wait_id"]},
            )
            tx.execute(
                "UPDATE GRAPH_NODE_RUNS SET STATUS = 'FAILED', UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'WAITING'",
                {"node_run_id": wait["node_run_id"]},
            )
            tx.execute(
                "UPDATE GRAPH_READY_NODES SET STATUS = 'DONE' WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'WAITING'",
                {"node_run_id": wait["node_run_id"]},
            )
            tx.execute(
                "UPDATE GRAPH_RUNS SET STATUS = 'FAILED', ERROR_CODE = 'WAIT_TIMEOUT', ERROR_MESSAGE = 'Graph wait deadline expired', UPDATED_AT = CURRENT_TIMESTAMP, COMPLETED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS IN ('WAITING','RUNNING')",
                {"run_id": wait["run_id"]},
            )
            _trace_tx(tx, wait["run_id"], "WAIT_EXPIRED", node_run_id=wait["node_run_id"], status="FAILED")
            count += 1
        return count

    return int(connection.execute_transaction_callback(_reap) or 0)


def cancel_run(run_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("cancellation reason is required")
    def _cancel(tx):
        changed = tx.execute(
            "UPDATE GRAPH_RUNS SET STATUS = 'CANCELLED', ERROR_CODE = 'CANCELLED', ERROR_MESSAGE = :reason, UPDATED_AT = CURRENT_TIMESTAMP, COMPLETED_AT = CURRENT_TIMESTAMP "
            "WHERE RUN_ID = :run_id AND STATUS NOT IN ('SUCCEEDED','FAILED','CANCELLED')",
            {"run_id": run_id, "reason": str(reason)[:2000]},
        )
        if not changed:
            return False
        tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'CANCELLED' WHERE RUN_ID = :run_id AND STATUS IN ('READY','WAITING','CLAIMED')", {"run_id": run_id})
        tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'CANCELLED', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS IN ('PENDING','READY','WAITING','RUNNING')", {"run_id": run_id})
        tx.execute("UPDATE GRAPH_ATTEMPTS SET STATUS = 'CANCELLED', ERROR_CODE = 'RUN_CANCELLED', ERROR_MESSAGE = :reason, COMPLETED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS IN ('CLAIMED','RUNNING','WAITING')", {"run_id": run_id, "reason": str(reason)[:2000]})
        tx.execute("UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID IN (SELECT ATTEMPT_ID FROM GRAPH_ATTEMPTS WHERE RUN_ID = :run_id) AND REVOKED_AT IS NULL", {"run_id": run_id})
        tx.execute("UPDATE GRAPH_WAIT_SUBSCRIPTIONS SET STATUS = 'CANCELLED', RESOLVED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'WAITING'", {"run_id": run_id})
        _intervention_tx(tx, run_id, "CANCEL", actor_id, reason)
        _trace_tx(tx, run_id, "RUN_CANCELLED", status="CANCELLED", detail={"reason": reason})
        return True
    return bool(connection.execute_transaction_callback(_cancel))


def pause_run(run_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("pause reason is required")
    def _pause(tx):
        changed = tx.execute("UPDATE GRAPH_RUNS SET STATUS = 'PAUSED', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS IN ('RUNNING','WAITING')", {"run_id": run_id})
        if not changed:
            return False
        tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'WAITING' WHERE RUN_ID = :run_id AND STATUS = 'READY'", {"run_id": run_id})
        _intervention_tx(tx, run_id, "PAUSE", actor_id, reason)
        _trace_tx(tx, run_id, "RUN_PAUSED", status="PAUSED", detail={"reason": reason})
        return True
    return bool(connection.execute_transaction_callback(_pause))


def resume_run(run_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("resume reason is required")
    def _resume(tx):
        changed = tx.execute("UPDATE GRAPH_RUNS SET STATUS = 'RUNNING', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'PAUSED'", {"run_id": run_id})
        if not changed:
            return False
        tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'READY', AVAILABLE_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'WAITING'", {"run_id": run_id})
        tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'WAITING'", {"run_id": run_id})
        _intervention_tx(tx, run_id, "RESUME", actor_id, reason)
        _trace_tx(tx, run_id, "RUN_RESUMED", status="RUNNING", detail={"reason": reason})
        return True
    return bool(connection.execute_transaction_callback(_resume))


def retry_node(run_id: str, node_run_id: str, actor_id: str, reason: str,
               confirmation: Optional[Dict[str, Any]] = None) -> bool:
    if not str(reason or "").strip():
        raise ValueError("retry reason is required")
    confirmation = confirmation if isinstance(confirmation, dict) else {}
    plan = _plan_for_run(run_id)
    def _retry(tx):
        node = tx.query_one("SELECT NODE_RUN_ID, NODE_KEY, STATUS FROM GRAPH_NODE_RUNS WHERE RUN_ID = :run_id AND NODE_RUN_ID = :node_run_id", {"run_id": run_id, "node_run_id": node_run_id})
        if not node or node.get("status") not in {"FAILED", "REVIEW_REQUIRED"}:
            return False
        definition = _node_from_plan(plan, str(node.get("node_key") or ""))
        side_effect = str(definition.get("side_effect_class") or "NONE").upper()
        if side_effect == "NON_IDEMPOTENT":
            if confirmation.get("outcome_confirmed") is not True:
                raise ValueError("non-idempotent retry requires explicit outcome confirmation")
            if not str(confirmation.get("evidence") or confirmation.get("reference") or "").strip():
                raise ValueError("non-idempotent retry requires confirmation evidence")
        tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id", {"node_run_id": node_run_id})
        changed = tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'READY', CLAIMED_AT = NULL, AVAILABLE_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS <> 'DONE'", {"node_run_id": node_run_id})
        if not changed:
            _insert_ready_tx(tx, run_id, node["node_key"], status="READY")
        tx.execute("UPDATE GRAPH_RUNS SET STATUS = 'RUNNING', ERROR_CODE = NULL, ERROR_MESSAGE = NULL, COMPLETED_AT = NULL, UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS NOT IN ('CANCELLED','SUCCEEDED')", {"run_id": run_id})
        _intervention_tx(tx, run_id, "RETRY", actor_id, reason, node_run_id,
                         {"confirmation": confirmation} if confirmation else None)
        _trace_tx(tx, run_id, "MANUAL_RETRY", node_run_id=node_run_id, status="READY",
                  detail={"reason": reason, "side_effect_class": side_effect,
                          "confirmation": confirmation})
        return True
    return bool(connection.execute_transaction_callback(_retry))


def reassign_attempt(attempt_id: str, actor_id: str, reason: str, worker_id: Optional[str] = None) -> bool:
    if not str(reason or "").strip():
        raise ValueError("reassign reason is required")
    def _reassign(tx):
        attempt = tx.query_one("SELECT ATTEMPT_ID, RUN_ID, NODE_RUN_ID, FENCING_TOKEN, STATUS FROM GRAPH_ATTEMPTS WHERE ATTEMPT_ID = :attempt_id", {"attempt_id": attempt_id})
        if not attempt or attempt.get("status") not in {"CLAIMED", "RUNNING", "WAITING"}:
            return False
        tx.execute("UPDATE GRAPH_ATTEMPTS SET STATUS = 'STALE', ERROR_CODE = 'REASSIGNED', ERROR_MESSAGE = :reason, COMPLETED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id AND STATUS IN ('CLAIMED','RUNNING','WAITING')", {"attempt_id": attempt_id, "reason": reason[:2000]})
        tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'READY', CLAIMED_AT = NULL, AVAILABLE_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('CLAIMED','WAITING')", {"node_run_id": attempt["node_run_id"]})
        tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('RUNNING','WAITING')", {"node_run_id": attempt["node_run_id"]})
        tx.execute("UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE ATTEMPT_ID = :attempt_id AND FENCING_TOKEN = :fencing_token AND REVOKED_AT IS NULL", {"attempt_id": attempt_id, "fencing_token": attempt["fencing_token"]})
        _intervention_tx(tx, attempt["run_id"], "REASSIGN", actor_id, reason, attempt["node_run_id"], {"worker_id": worker_id})
        _trace_tx(tx, attempt["run_id"], "ATTEMPT_REASSIGNED", node_run_id=attempt["node_run_id"], attempt_id=attempt_id, status="READY", detail={"worker_id": worker_id})
        return True
    return bool(connection.execute_transaction_callback(_reassign))


def skip_node(run_id: str, node_run_id: str, actor_id: str, reason: str,
              output_state: Optional[Dict[str, Any]] = None) -> bool:
    if not str(reason or "").strip():
        raise ValueError("skip reason is required")
    def _skip(tx):
        node = tx.query_one("SELECT NODE_RUN_ID, STATUS FROM GRAPH_NODE_RUNS WHERE RUN_ID = :run_id AND NODE_RUN_ID = :node_run_id", {"run_id": run_id, "node_run_id": node_run_id})
        if not node or node.get("status") in {"SUCCEEDED", "SKIPPED", "CANCELLED"}:
            return False
        checkpoint = _write_checkpoint_tx(tx, run_id, output_state or {}, actor_id, snapshot_kind="INTERVENTION")
        tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'SKIPPED', OUTPUT_CHECKPOINT_ID = :checkpoint_id, UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id", {"node_run_id": node_run_id, "checkpoint_id": checkpoint["checkpoint_id"]})
        tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'DONE' WHERE NODE_RUN_ID = :node_run_id AND STATUS IN ('READY','WAITING','CLAIMED')", {"node_run_id": node_run_id})
        _activate_downstream_tx(tx, run_id, node_run_id, checkpoint["checkpoint_id"], output_state or {}, actor_id, {"intervention": "SKIP"})
        _intervention_tx(tx, run_id, "SKIP", actor_id, reason, node_run_id)
        _trace_tx(tx, run_id, "NODE_SKIPPED", node_run_id=node_run_id, status="SKIPPED", detail={"reason": reason})
        return True
    return bool(connection.execute_transaction_callback(_skip))


def force_route(run_id: str, node_run_id: str, edge_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("force-route reason is required")
    def _force(tx):
        node = tx.query_one("SELECT NODE_RUN_ID, STATUS FROM GRAPH_NODE_RUNS WHERE RUN_ID = :run_id AND NODE_RUN_ID = :node_run_id", {"run_id": run_id, "node_run_id": node_run_id})
        if not node or node.get("status") not in {"READY", "WAITING", "FAILED", "RUNNING"}:
            return False
        checkpoint = tx.query_one("SELECT CHECKPOINT_ID FROM GRAPH_CHECKPOINTS WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST 1 ROWS ONLY", {"run_id": run_id})
        if not checkpoint:
            checkpoint = _write_checkpoint_tx(tx, run_id, {}, actor_id, snapshot_kind="INTERVENTION")
        _activate_downstream_tx(tx, run_id, node_run_id, checkpoint.get("checkpoint_id"), _recover_state_tx(tx, run_id), actor_id, {"intervention": "FORCE_ROUTE", "edge_id": edge_id}, forced_edge_id=edge_id)
        _intervention_tx(tx, run_id, "FORCE_ROUTE", actor_id, reason, node_run_id, {"edge_id": edge_id})
        _trace_tx(tx, run_id, "ROUTE_FORCED", node_run_id=node_run_id, status="READY", detail={"edge_id": edge_id, "reason": reason})
        return True
    return bool(connection.execute_transaction_callback(_force))


def compensate(run_id: str, node_run_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("compensation reason is required")
    plan = _plan_for_run(run_id)
    node = connection.execute_query_one("SELECT NODE_KEY FROM GRAPH_NODE_RUNS WHERE RUN_ID = :run_id AND NODE_RUN_ID = :node_run_id", {"run_id": run_id, "node_run_id": node_run_id})
    edge = next((item for item in plan.get("edges", []) if item.get("source_node_key") == (node or {}).get("node_key") and str(item.get("edge_kind")) == "COMPENSATION"), None)
    if not edge:
        raise ValueError("no compensation edge is registered for the node")
    return force_route(run_id, node_run_id, str(edge.get("edge_id")), actor_id, reason)


def fork_run(run_id: str, actor_id: str, reason: str, idempotency_key: Optional[str] = None) -> str:
    if not str(reason or "").strip():
        raise ValueError("fork reason is required")
    run = get_run(run_id)
    if not run:
        raise ValueError("Graph Run not found")
    plan = _plan_for_run(run_id)
    child_id = create_run(run["graph_version_id"], run["plan_id"], actor_id, recover_state(run_id), run.get("budget") or {}, idempotency_key or f"fork:{run_id}:{_hash(reason)[:16]}")
    append_checkpoint(child_id, recover_state(run_id), actor_id, snapshot_kind="FORK", reducer_evidence={"parent_run_id": run_id, "reason": reason})
    connection.execute("UPDATE GRAPH_RUNS SET ERROR_MESSAGE = :reason, UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id", {"run_id": child_id, "reason": f"Forked from {run_id}: {reason}"})
    return child_id


def resolve_waits(event_type: str, payload: Optional[Dict[str, Any]] = None,
                  correlation_key: Optional[str] = None, limit: int = 100) -> int:
    payload = payload or {}
    limit = _limit(limit)
    def _resolve(tx):
        params = {"event_type": event_type, "limit": limit}
        condition = "EVENT_TYPE = :event_type"
        if correlation_key:
            condition += " AND CORRELATION_KEY = :correlation_key"
            params["correlation_key"] = correlation_key
        waits = tx.query(
            "SELECT WAIT_ID, RUN_ID, NODE_RUN_ID FROM GRAPH_WAIT_SUBSCRIPTIONS WHERE STATUS = 'WAITING' AND "
            + condition + " ORDER BY CREATED_AT FETCH FIRST :limit ROWS ONLY", params,
        )
        count = 0
        for wait in waits:
            if tx.execute("UPDATE GRAPH_WAIT_SUBSCRIPTIONS SET STATUS = 'RESOLVED', PAYLOAD_JSON = :payload_json, RESOLVED_AT = CURRENT_TIMESTAMP WHERE WAIT_ID = :wait_id AND STATUS = 'WAITING'", {"wait_id": wait["wait_id"], "payload_json": _canonical(_redact(payload))}) != 1:
                continue
            checkpoint = _write_checkpoint_tx(tx, wait["run_id"], {"event": _redact(payload)}, "event", snapshot_kind="DELTA")
            tx.execute("UPDATE GRAPH_NODE_RUNS SET STATUS = 'READY', INPUT_CHECKPOINT_ID = :checkpoint_id, UPDATED_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'WAITING'", {"node_run_id": wait["node_run_id"], "checkpoint_id": checkpoint["checkpoint_id"]})
            tx.execute("UPDATE GRAPH_READY_NODES SET STATUS = 'READY', AVAILABLE_AT = CURRENT_TIMESTAMP WHERE NODE_RUN_ID = :node_run_id AND STATUS = 'WAITING'", {"node_run_id": wait["node_run_id"]})
            remaining = tx.query_one(
                "SELECT WAIT_ID FROM GRAPH_WAIT_SUBSCRIPTIONS WHERE RUN_ID = :run_id AND STATUS = 'WAITING' FETCH FIRST 1 ROWS ONLY",
                {"run_id": wait["run_id"]},
            )
            if not remaining:
                tx.execute("UPDATE GRAPH_RUNS SET STATUS = 'RUNNING', UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS = 'WAITING'", {"run_id": wait["run_id"]})
            _trace_tx(tx, wait["run_id"], "WAIT_RESOLVED", node_run_id=wait["node_run_id"], status="READY", detail={"event_type": event_type})
            count += 1
        return count
    return int(connection.execute_transaction_callback(_resolve) or 0)


def migrate_run(run_id: str, target_version_id: str, actor_id: str, reason: str,
                mapping: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not str(reason or "").strip():
        raise ValueError("run migration reason is required")
    target = connection.execute_query_one(
        "SELECT GRAPH_VERSION_ID, STATUS FROM GRAPH_VERSIONS WHERE GRAPH_VERSION_ID = :version_id",
        {"version_id": target_version_id},
    )
    if not target or str(target.get("status") or "").upper() not in {"PUBLISHED", "DEPRECATED"}:
        raise ValueError("target Graph Version must be published")
    target_plan = connection.execute_query_one(
        "SELECT PLAN_ID FROM GRAPH_COMPILE_PLANS WHERE GRAPH_VERSION_ID = :version_id",
        {"version_id": target_version_id},
    )
    if not target_plan:
        raise ValueError("target Graph Version has no compiled plan")
    def _migrate(tx):
        run = tx.query_one("SELECT RUN_ID, GRAPH_VERSION_ID, PLAN_ID, STATUS, CURRENT_CHECKPOINT_ID FROM GRAPH_RUNS WHERE RUN_ID = :run_id", {"run_id": run_id})
        if not run:
            raise ValueError("Graph Run not found")
        if run.get("status") not in {"PAUSED", "WAITING"}:
            raise ValueError("run migration requires a paused or waiting quiescence barrier")
        active = tx.query_one("SELECT ATTEMPT_ID FROM GRAPH_ATTEMPTS WHERE RUN_ID = :run_id AND STATUS IN ('CLAIMED','RUNNING','WAITING') FETCH FIRST 1 ROWS ONLY", {"run_id": run_id})
        if active:
            raise ValueError("run migration requires no active attempts")
        pre = _write_checkpoint_tx(tx, run_id, {}, actor_id, snapshot_kind="MIGRATION", reducer_evidence={"target_version_id": target_version_id})
        migration_id = _id("MIG")
        tx.execute(
            "INSERT INTO GRAPH_RUN_MIGRATIONS (MIGRATION_ID, RUN_ID, FROM_VERSION_ID, TO_VERSION_ID, FROM_PLAN_ID, TO_PLAN_ID, PRECHECKPOINT_ID, STATUS, MAPPING_JSON, ACTOR_ID, REASON, CREATED_AT) "
            "VALUES (:migration_id, :run_id, :from_version_id, :to_version_id, :from_plan_id, :to_plan_id, :precheckpoint_id, 'APPLIED', :mapping_json, :actor_id, :reason, CURRENT_TIMESTAMP)",
            {"migration_id": migration_id, "run_id": run_id, "from_version_id": run["graph_version_id"], "to_version_id": target_version_id,
             "from_plan_id": run["plan_id"], "to_plan_id": target_plan["plan_id"], "precheckpoint_id": pre["checkpoint_id"],
             "mapping_json": _canonical(mapping or {}), "actor_id": actor_id, "reason": reason[:2000]},
        )
        tx.execute("UPDATE GRAPH_RUNS SET GRAPH_VERSION_ID = :version_id, PLAN_ID = :plan_id, CURRENT_CHECKPOINT_ID = :checkpoint_id, UPDATED_AT = CURRENT_TIMESTAMP WHERE RUN_ID = :run_id AND STATUS IN ('PAUSED','WAITING')", {"version_id": target_version_id, "plan_id": target_plan["plan_id"], "checkpoint_id": pre["checkpoint_id"], "run_id": run_id})
        _intervention_tx(tx, run_id, "MIGRATE", actor_id, reason, evidence={"from_version_id": run["graph_version_id"], "to_version_id": target_version_id, "migration_id": migration_id})
        _trace_tx(tx, run_id, "RUN_MIGRATED", status=run["status"], detail={"migration_id": migration_id, "from": run["graph_version_id"], "to": target_version_id})
        return {"migration_id": migration_id, "run_id": run_id, "status": "APPLIED", "checkpoint_id": pre["checkpoint_id"]}
    return connection.execute_transaction_callback(_migrate)


def record_trace(run_id: str, event_type: str, **kwargs: Any) -> str:
    return connection.execute_transaction_callback(
        lambda tx: _trace_tx(tx, run_id, event_type, **kwargs)
    )


def list_node_runs(run_id: str, status: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    condition = "RUN_ID = :run_id"
    params = {"run_id": run_id, "limit": _limit(limit)}
    if status:
        condition += " AND STATUS = :status"
        params["status"] = str(status).upper()
    return _rows(connection.execute_query(
        "SELECT NODE_RUN_ID, RUN_ID, NODE_KEY, STATUS, BRANCH_KEY, JOIN_KEY, ITERATION_NO, INPUT_CHECKPOINT_ID, OUTPUT_CHECKPOINT_ID, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_NODE_RUNS WHERE " + condition + " ORDER BY CREATED_AT FETCH FIRST :limit ROWS ONLY", params,
    ))


def list_attempts(run_id: str, node_run_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    condition = "RUN_ID = :run_id"
    params = {"run_id": run_id, "limit": _limit(limit)}
    if node_run_id:
        condition += " AND NODE_RUN_ID = :node_run_id"
        params["node_run_id"] = node_run_id
    return _rows(connection.execute_query(
        "SELECT ATTEMPT_ID, NODE_RUN_ID, RUN_ID, WORKER_ID, STATUS, FENCING_TOKEN, LEASE_EXPIRES_AT, INPUT_STATE_JSON, OUTPUT_STATE_JSON, RESULT_ARTIFACT_ID, IDEMPOTENCY_KEY, ERROR_CODE, ERROR_MESSAGE, STARTED_AT, COMPLETED_AT "
        "FROM GRAPH_ATTEMPTS WHERE " + condition + " ORDER BY STARTED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    ))


def list_checkpoints(run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT CHECKPOINT_ID, RUN_ID, SEQ_NO, PARENT_CHECKPOINT_ID, STATE_JSON, STATE_HASH, SNAPSHOT_KIND, BRANCH_ID, ACTOR_ID, CREATED_AT "
        "FROM GRAPH_CHECKPOINTS WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_state_events(run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT EVENT_ID, RUN_ID, SEQ_NO, CHECKPOINT_ID, PRIOR_CHECKPOINT_ID, SOURCE_ATTEMPT_ID, DELTA_JSON, REDUCER_JSON, STATE_HASH, CREATED_AT "
        "FROM GRAPH_STATE_EVENTS WHERE RUN_ID = :run_id ORDER BY SEQ_NO DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_transitions(run_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT TRANSITION_ID, RUN_ID, NODE_RUN_ID, ATTEMPT_ID, EDGE_ID, FROM_NODE_KEY, TO_NODE_KEY, TRANSITION_TYPE, STATUS, CHECKPOINT_ID, STATE_EVENT_ID, FENCING_TOKEN, EVIDENCE_JSON, ACTOR_ID, REASON, CREATED_AT "
        "FROM GRAPH_TRANSITIONS WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_traces(run_id: str, event_type: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    condition = "RUN_ID = :run_id"
    params = {"run_id": run_id, "limit": _limit(limit)}
    if event_type:
        condition += " AND EVENT_TYPE = :event_type"
        params["event_type"] = event_type.upper()
    return _rows(connection.execute_query(
        "SELECT TRACE_ID, RUN_ID, NODE_RUN_ID, ATTEMPT_ID, TRANSITION_ID, EVENT_TYPE, STATUS, RETRY_NO, DURATION_MS, TOKEN_COUNT, ESTIMATED_COST, PAYLOAD_REF, DETAIL_JSON, CREATED_AT "
        "FROM GRAPH_TRACES WHERE " + condition + " ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    ))


def list_evaluations(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT EVALUATION_ID, RUN_ID, NODE_RUN_ID, EVALUATOR_NAME, EVALUATOR_VERSION, LEVEL_NAME, INPUT_JSON, RESULT_JSON, ROUTE_DECISION, CREATED_AT "
        "FROM GRAPH_EVALUATIONS WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_interventions(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT INTERVENTION_ID, RUN_ID, NODE_RUN_ID, ACTION_NAME, ACTOR_ID, REASON, EVIDENCE_JSON, STATUS, CREATED_AT "
        "FROM GRAPH_INTERVENTIONS WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_join_states(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT JOIN_ID, RUN_ID, NODE_KEY, JOIN_KEY, STRATEGY, REQUIRED_COUNT, EXPECTED_COUNT, ACCEPTED_COUNT, STATUS, INPUTS_JSON, REDUCER_JSON, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_JOIN_STATES WHERE RUN_ID = :run_id ORDER BY UPDATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_branches(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT BRANCH_ID, RUN_ID, PARENT_NODE_RUN_ID, BRANCH_KEY, SOURCE_EDGE_ID, NODE_KEY, STATUS, INPUT_CHECKPOINT_ID, OUTPUT_CHECKPOINT_ID, METADATA_JSON, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_RUN_BRANCHES WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_waits(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT WAIT_ID, RUN_ID, NODE_RUN_ID, WAIT_KIND, EVENT_TYPE, CORRELATION_KEY, STATUS, DEADLINE_AT, PAYLOAD_JSON, CREATED_AT, RESOLVED_AT "
        "FROM GRAPH_WAIT_SUBSCRIPTIONS WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"run_id": run_id, "limit": _limit(limit)},
    ))


def list_migrations(run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT MIGRATION_ID, RUN_ID, FROM_VERSION_ID, TO_VERSION_ID, FROM_PLAN_ID, TO_PLAN_ID, "
        "PRECHECKPOINT_ID, STATUS, MAPPING_JSON, ACTOR_ID, REASON, ERROR_MESSAGE, CREATED_AT, "
        "COMPLETED_AT FROM GRAPH_RUN_MIGRATIONS WHERE RUN_ID = :run_id ORDER BY CREATED_AT DESC "
        "FETCH FIRST :limit ROWS ONLY", {"run_id": run_id, "limit": _limit(limit)},
    ))


def get_run_snapshot(run_id: str, limit: int = 100) -> Dict[str, Any]:
    run = get_run(run_id)
    if not run:
        return {}
    return {"run": run, "state": _redact(recover_state(run_id)), "nodes": list_node_runs(run_id, limit=limit),
            "attempts": list_attempts(run_id, limit=limit), "checkpoints": list_checkpoints(run_id, limit=limit),
            "transitions": list_transitions(run_id, limit=limit), "trace": list_traces(run_id, limit=limit),
            "joins": list_join_states(run_id, limit=limit), "branches": list_branches(run_id, limit=limit),
            "waits": list_waits(run_id, limit=limit), "interventions": list_interventions(run_id, limit=limit),
            "evaluations": list_evaluations(run_id, limit=limit), "migrations": list_migrations(run_id, limit=limit)}


def ingest_event(source_ref: str, event_type: str, schema_version: str, idempotency_key: str,
                 payload: Dict[str, Any], authentication: Optional[Dict[str, Any]] = None,
                 *, trusted_subject: Optional[str] = None) -> Dict[str, Any]:
    if not source_ref or not event_type or not schema_version or not idempotency_key:
        raise ValueError("source_ref, event_type, schema_version, and idempotency_key are required")
    auth = authentication if isinstance(authentication, dict) else {}
    validation_errors = graph_event_contract.validate_event(
        source_ref, event_type, schema_version, idempotency_key, payload,
    )
    # Missing identity fields cannot be stored safely in the Inbox.  Other
    # validly keyed malformed events are retained as poison/dead-letter rows.
    if any(item.get("code") in {"EVENT_SOURCE_INVALID", "EVENT_IDEMPOTENCY_INVALID"}
           for item in validation_errors):
        raise ValueError(_canonical(validation_errors)[:4000])
    safe_payload = _redact(payload if isinstance(payload, dict) else {})
    event_hash = graph_event_contract.payload_hash(payload) if isinstance(payload, dict) else None
    supplied_subject = str(auth.get("subject") or auth.get("agent_id") or "")
    effective_subject = str(trusted_subject or supplied_subject)
    auth_errors: List[Dict[str, Any]] = []
    authenticated = False
    if auth.get("signature"):
        # Database adapters do not receive signing key material.  A trusted
        # HTTP/API boundary may mark the principal after verifying its token;
        # unsigned direct calls retain the legacy subject-only behavior.
        if trusted_subject and supplied_subject and supplied_subject != trusted_subject:
            auth_errors.append({"code": "EVENT_SUBJECT_MISMATCH"})
        if not auth.get("verified"):
            auth_errors.append({"code": "EVENT_SIGNATURE_UNVERIFIED"})
        authenticated = bool(trusted_subject and not auth_errors)
    else:
        authenticated = bool(trusted_subject or supplied_subject)
    auth_metadata = {
        key: (effective_subject if key in {"subject", "agent_id"} and effective_subject else auth.get(key))
        for key in ("subject", "agent_id", "issuer", "schema")
        if (effective_subject if key in {"subject", "agent_id"} else auth.get(key)) is not None
    }
    if auth.get("signature"):
        auth_metadata["signature_hash"] = _hash(str(auth["signature"]))
    if event_hash:
        auth_metadata["payload_hash"] = event_hash
    auth_result = graph_event_contract.classify_event(
        validation_errors=validation_errors,
        authentication={"authenticated": authenticated, "errors": auth_errors},
    )
    inbox_id = _id("INBOX")
    try:
        connection.execute(
            "INSERT INTO GRAPH_INBOX (INBOX_ID, SOURCE_REF, EVENT_TYPE, SCHEMA_VERSION, IDEMPOTENCY_KEY, AUTHENTICATION_JSON, PAYLOAD_JSON, STATUS, ERROR_MESSAGE) "
            "VALUES (:inbox_id, :source_ref, :event_type, :schema_version, :idempotency_key, :authentication_json, :payload_json, :status, :error_message)",
            {"inbox_id": inbox_id, "source_ref": source_ref, "event_type": str(event_type).upper(),
             "schema_version": schema_version, "idempotency_key": idempotency_key,
             "authentication_json": _canonical(auth_metadata), "payload_json": _canonical(safe_payload),
             "status": auth_result["status"],
             "error_message": _canonical(auth_result["errors"])[:2000] if auth_result["errors"] else None},
        )
    except Exception:
        existing = connection.execute_query_one(
            "SELECT INBOX_ID, STATUS, PAYLOAD_JSON, AUTHENTICATION_JSON FROM GRAPH_INBOX "
            "WHERE SOURCE_REF = :source_ref AND IDEMPOTENCY_KEY = :idempotency_key",
            {"source_ref": source_ref, "idempotency_key": idempotency_key},
        )
        if existing:
            recorded_auth = _json(existing.get("authentication_json"), {}) or {}
            recorded_hash = recorded_auth.get("payload_hash")
            if event_hash and recorded_hash and str(recorded_hash) != event_hash:
                raise ValueError("event idempotency key was reused with a different payload")
            if _json(existing.get("payload_json"), {}) != safe_payload:
                raise ValueError("event idempotency key was reused with a different payload")
            return {"inbox_id": existing.get("inbox_id"), "duplicate": True, "status": "DUPLICATE"}
        raise
    resolved = 0
    if auth_result["activation_allowed"]:
        resolved = resolve_waits(
            event_type, payload, payload.get("correlation_key") if isinstance(payload, dict) else None,
        )
        connection.execute(
            "UPDATE GRAPH_INBOX SET STATUS = 'PROCESSED', PROCESSED_AT = CURRENT_TIMESTAMP "
            "WHERE INBOX_ID = :inbox_id AND STATUS = 'RECEIVED'", {"inbox_id": inbox_id},
        )
    return {"inbox_id": inbox_id, "duplicate": False,
            "status": auth_result["status"],
            "activation_blocked": not auth_result["activation_allowed"],
            "poison": auth_result["poison"], "errors": auth_result["errors"],
            "waits_resolved": resolved}


def enqueue_outbox(run_id: Optional[str], event_type: str, idempotency_key: str, payload: Dict[str, Any]) -> str:
    outbox_id = _id("OUTBOX")
    safe_payload = _redact(payload or {})
    try:
        connection.execute("INSERT INTO GRAPH_OUTBOX (OUTBOX_ID, RUN_ID, EVENT_TYPE, IDEMPOTENCY_KEY, PAYLOAD_JSON) VALUES (:outbox_id, :run_id, :event_type, :idempotency_key, :payload_json)", {"outbox_id": outbox_id, "run_id": run_id, "event_type": event_type, "idempotency_key": idempotency_key, "payload_json": _canonical(safe_payload)})
    except Exception:
        existing = connection.execute_query_one("SELECT OUTBOX_ID, PAYLOAD_JSON FROM GRAPH_OUTBOX WHERE EVENT_TYPE = :event_type AND IDEMPOTENCY_KEY = :idempotency_key", {"event_type": event_type, "idempotency_key": idempotency_key})
        if existing:
            if _json(existing.get("payload_json"), {}) != safe_payload:
                raise ValueError("outbox idempotency key was reused with a different payload")
            return str(existing["outbox_id"])
        raise
    return outbox_id


def put_artifact(content: bytes, owner_ref: str, media_type: str = "application/octet-stream", classification: str = "INTERNAL") -> Dict[str, Any]:
    content_hash = hashlib.sha256(content).hexdigest()
    existing = _row(connection.execute_query_one("SELECT ARTIFACT_ID, CONTENT_HASH, CONTENT_SIZE, MEDIA_TYPE, OWNER_REF, CLASSIFICATION, LEGAL_HOLD, RETENTION_UNTIL, CREATED_AT FROM GRAPH_ARTIFACTS WHERE CONTENT_HASH = :content_hash", {"content_hash": content_hash}))
    if existing:
        return existing
    artifact_id = _id("ART")
    connection.execute("INSERT INTO GRAPH_ARTIFACTS (ARTIFACT_ID, CONTENT_HASH, MEDIA_TYPE, CONTENT_SIZE, CONTENT_BLOB, OWNER_REF, CLASSIFICATION) VALUES (:artifact_id, :content_hash, :media_type, :content_size, :content_blob, :owner_ref, :classification)", {"artifact_id": artifact_id, "content_hash": content_hash, "media_type": media_type, "content_size": len(content), "content_blob": content, "owner_ref": owner_ref, "classification": classification})
    return {"artifact_id": artifact_id, "content_hash": content_hash, "content_size": len(content), "media_type": media_type, "owner_ref": owner_ref, "classification": classification, "legal_hold": "N"}


def get_artifact(artifact_id: str, include_content: bool = False, max_bytes: int = 10 * 1024 * 1024) -> Optional[Dict[str, Any]]:
    """Return governed Artifact metadata; content is opt-in and size-bounded."""
    columns = "ARTIFACT_ID, CONTENT_HASH, CONTENT_SIZE, MEDIA_TYPE, STORAGE_URI, OWNER_REF, CLASSIFICATION, ENCRYPTION_KEY_REF, RETENTION_UNTIL, LEGAL_HOLD, CREATED_AT"
    if include_content:
        columns += ", CONTENT_BLOB"
    row = _row(connection.execute_query_one(
        f"SELECT {columns} FROM GRAPH_ARTIFACTS WHERE ARTIFACT_ID = :artifact_id",
        {"artifact_id": artifact_id},
    ))
    if not row:
        return None
    if include_content:
        size = int(row.get("content_size") or 0)
        if size > max(1, min(int(max_bytes), 50 * 1024 * 1024)):
            raise ValueError("artifact exceeds the requested content limit")
        content = row.pop("content_blob", None)
        if isinstance(content, memoryview):
            content = content.tobytes()
        row["content"] = content
    return row


def list_artifacts(owner_ref: Optional[str] = None, classification: Optional[str] = None,
                   include_held: bool = True, limit: int = 100) -> List[Dict[str, Any]]:
    conditions = ["1 = 1"]
    params: Dict[str, Any] = {"limit": _limit(limit)}
    if owner_ref:
        conditions.append("OWNER_REF = :owner_ref")
        params["owner_ref"] = owner_ref
    if classification:
        conditions.append("CLASSIFICATION = :classification")
        params["classification"] = str(classification).upper()
    if not include_held:
        conditions.append("LEGAL_HOLD = 'N'")
    return _rows(connection.execute_query(
        "SELECT ARTIFACT_ID, CONTENT_HASH, CONTENT_SIZE, MEDIA_TYPE, STORAGE_URI, OWNER_REF, "
        "CLASSIFICATION, RETENTION_UNTIL, LEGAL_HOLD, CREATED_AT FROM GRAPH_ARTIFACTS WHERE "
        + " AND ".join(conditions) + " ORDER BY CREATED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    ))


def set_artifact_retention(artifact_id: str, retention_until: Optional[Any], actor_id: str,
                           reason: str) -> bool:
    if not actor_id or not str(reason or "").strip():
        raise ValueError("artifact retention requires actor_id and reason")
    return connection.execute(
        "UPDATE GRAPH_ARTIFACTS SET RETENTION_UNTIL = :retention_until WHERE ARTIFACT_ID = :artifact_id",
        {"artifact_id": artifact_id, "retention_until": _db_timestamp(retention_until)},
    ) > 0


def set_artifact_legal_hold(artifact_id: str, enabled: bool, actor_id: str, reason: str) -> bool:
    if not actor_id or not str(reason or "").strip():
        raise ValueError("legal hold requires actor_id and reason")
    if enabled:
        sql = (
            "UPDATE GRAPH_ARTIFACTS SET LEGAL_HOLD = 'Y', LEGAL_HOLD_ACTOR = :actor_id, "
            "LEGAL_HOLD_REASON = :reason, LEGAL_HOLD_AT = CURRENT_TIMESTAMP, "
            "RELEASED_BY = NULL, RELEASE_REASON = NULL, RELEASED_AT = NULL WHERE ARTIFACT_ID = :artifact_id"
        )
    else:
        sql = (
            "UPDATE GRAPH_ARTIFACTS SET LEGAL_HOLD = 'N', RELEASED_BY = :actor_id, "
            "RELEASE_REASON = :reason, RELEASED_AT = CURRENT_TIMESTAMP WHERE ARTIFACT_ID = :artifact_id"
        )
    return connection.execute(sql, {"artifact_id": artifact_id, "actor_id": actor_id, "reason": str(reason)[:2000]}) > 0


def purge_expired_artifacts(actor_id: str, limit: int = 100) -> int:
    if not actor_id:
        raise ValueError("artifact purge requires actor_id")
    return connection.execute(
        "DELETE FROM GRAPH_ARTIFACTS WHERE ARTIFACT_ID IN (SELECT ARTIFACT_ID FROM GRAPH_ARTIFACTS "
        "WHERE RETENTION_UNTIL IS NOT NULL AND RETENTION_UNTIL <= CURRENT_TIMESTAMP AND LEGAL_HOLD = 'N' "
        "FETCH FIRST :limit ROWS ONLY)", {"limit": _limit(limit)},
    )
