"""Compatibility mappings for the v4.2 Graph execution kernel.

The v4.1 domain APIs remain the public vocabulary for existing clients.  This
module provides lossless, in-memory wrapper definitions for new work and
honest read-only references for legacy history.  It deliberately does not
invent edges from display order when the deployed legacy schema did not store
them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
import math
from typing import Any, Dict, Iterable, List, Optional

try:
    from . import connection
except ImportError:  # Source-only compiler and compatibility tests have no adapter overlay.
    connection = None

COMPAT_SCHEMA = "graph-runtime-compatibility/1"

LEGACY_STATUS_MAP = {
    "PENDING": "READY",
    "RUNNING": "RUNNING",
    "PAUSED": "PAUSED",
    "SUCCESS": "SUCCEEDED",
    "SUCCEEDED": "SUCCEEDED",
    "COMPLETED": "SUCCEEDED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
    "STOPPED": "CANCELLED",
    "TIMEOUT": "FAILED",
    "REVIEW_REQUIRED": "REVIEW_REQUIRED",
}


def graph_status(legacy_status: Any, default: str = "REVIEW_REQUIRED") -> str:
    return LEGACY_STATUS_MAP.get(str(legacy_status or "").upper(), default)


def _node(node_key: str, node_type: str, *, config: Optional[Dict[str, Any]] = None,
          side_effect_class: str = "NONE", budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_type = str(node_type or "CONTROL").upper()
    normalized_config = dict(config or {})
    normalized_config.setdefault("executor", {
        "START": "CONTROL", "END": "CONTROL", "CONTROL": "CONTROL",
        "HUMAN": "HUMAN_WAIT", "TIMER": "TIMER_WAIT", "EVENT": "EVENT_WAIT",
    }.get(normalized_type, "WORKER"))
    return {
        "node_key": node_key,
        "node_type": normalized_type,
        "type_version": "1.0",
        "config": normalized_config,
        "input_schema": {},
        "output_schema": {},
        "side_effect_class": side_effect_class,
        "capabilities": [],
        "resource_scope": {},
        "budget": budget or {},
    }


def _edge(edge_id: str, source: str, target: str, *, edge_kind: str = "NORMAL",
          config: Optional[Dict[str, Any]] = None, order_index: int = 0) -> Dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_key": source,
        "target_node_key": target,
        "edge_kind": edge_kind,
        "decision_type": "FIXED",
        "condition": {},
        "config": config or {},
        "order_index": order_index,
        "join_key": None,
    }


def task_plan_definition(plan: Dict[str, Any], steps: Iterable[Dict[str, Any]],
                         dependencies: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Build a new Task Plan wrapper definition.

    New Task Plans have an explicit sequence based on ``step_order``.  If
    plan-level dependencies are supplied, they are represented as branch
    edges; otherwise the ordered step chain is the declared Plan contract.
    """
    ordered = sorted((dict(step) for step in steps), key=lambda item: (
        int(item.get("step_order") or 0), str(item.get("step_id") or "")
    ))
    nodes = [_node("start", "START", config={"entry": True})]
    edges: List[Dict[str, Any]] = []
    previous = "start"
    for index, step in enumerate(ordered):
        step_id = str(step.get("step_id") or f"step_{index + 1}")
        node_key = f"task:{step_id}"
        tool = str(step.get("tool_name") or "").strip()
        node_type = "TOOL" if tool else "AGENT"
        nodes.append(_node(
            node_key, node_type,
            config={
                "legacy_kind": "TASK_STEP",
                "legacy_id": step_id,
                "description": str(step.get("description") or ""),
                "tool_name": tool or None,
                "assigned_agent_id": step.get("assigned_agent_id"),
            },
            side_effect_class="IDEMPOTENT_EXTERNAL" if tool else "NONE",
        ))
        edges.append(_edge(f"task-edge:{index + 1}", previous, node_key, order_index=index))
        previous = node_key
    nodes.append(_node("end", "END", config={"exit": True}))
    edges.append(_edge(f"task-edge:end", previous, "end", order_index=len(edges)))
    return {
        "schema_version": "1.0",
        "compatibility": {"kind": "TASK_PLAN", "legacy_id": plan.get("plan_id"), "schema": COMPAT_SCHEMA},
        "input_schema": {},
        "output_schema": {},
        "budget": {},
        "nodes": nodes,
        "edges": edges,
    }


def loop_definition(loop: Dict[str, Any]) -> Dict[str, Any]:
    """Build a standalone Loop wrapper with its goal/evaluator as config."""
    loop_id = str(loop.get("loop_id") or loop.get("entity_id") or "loop")
    stop = _portable_json_value(loop.get("stop_conditions") or {})
    budget = {}
    for source, target in (
        ("max_iterations", "max_iterations"),
        ("max_tokens", "max_tokens"),
        ("max_duration_seconds", "max_duration_seconds"),
    ):
        if stop.get(source) is not None:
            budget[target] = stop[source]
    return {
        "schema_version": "1.0",
        "compatibility": {"kind": "LOOP", "legacy_id": loop_id, "schema": COMPAT_SCHEMA},
        "input_schema": {},
        "output_schema": {},
        "budget": budget,
        "nodes": [
            _node("start", "START", config={"entry": True}),
            _node("loop", "LOOP", config={
                "legacy_id": loop_id,
                "goal_definition": _portable_json_value(loop.get("goal_definition") or {}),
                "stop_conditions": stop,
                "evaluation_config": _portable_json_value(loop.get("evaluation_config") or {}),
                "trigger_config": _portable_json_value(loop.get("trigger_config") or {}),
            }, budget=budget),
            _node("end", "END", config={"exit": True}),
        ],
        "edges": [
            _edge("loop-edge:start", "start", "loop"),
            {
                **_edge("loop-edge:repeat", "loop", "loop", edge_kind="CYCLE"),
                "decision_type": "EXPRESSION",
                "condition": {
                    "op": "eq",
                    "left": {"op": "ref", "path": "state.loop_continue"},
                    "right": {"op": "literal", "value": True},
                },
            },
            {
                **_edge("loop-edge:end", "loop", "end"),
                "decision_type": "EXPRESSION",
                "condition": {
                    "op": "ne",
                    "left": {"op": "ref", "path": "state.loop_continue"},
                    "right": {"op": "literal", "value": True},
                },
            },
        ],
    }


def skill_node(skill_id: str, *, version: str = "1.0", tool: bool = False) -> Dict[str, Any]:
    return _node(
        f"skill:{skill_id}", "TOOL" if tool else "SKILL",
        config={"legacy_kind": "SKILL", "legacy_id": skill_id, "version": version},
        side_effect_class="IDEMPOTENT_EXTERNAL",
    )


def tool_node(tool_id: str, *, version: str = "1.0") -> Dict[str, Any]:
    return _node(
        f"tool:{tool_id}", "TOOL",
        config={"legacy_kind": "TOOL", "legacy_id": tool_id, "version": version},
        side_effect_class="IDEMPOTENT_EXTERNAL",
    )


def human_wait_node(resource_ref: str, *, approval: bool = True) -> Dict[str, Any]:
    return _node(
        f"human:{resource_ref}", "HUMAN",
        config={"legacy_kind": "APPROVAL" if approval else "HUMAN_WAIT", "resource_ref": resource_ref,
                "wait_kind": "HUMAN"},
    )


def capability_definition(kind: str, legacy_id: str, node_type: str = "AGENT",
                          config: Optional[Dict[str, Any]] = None,
                          *, side_effect_class: str = "NONE") -> Dict[str, Any]:
    """Build the common linear Graph wrapper for Skill, Tool, approval, and Job work."""
    normalized_kind = str(kind or "CAPABILITY").upper()
    normalized_type = str(node_type or "AGENT").upper()
    if normalized_type == "HUMAN":
        node = human_wait_node(str(legacy_id), approval=normalized_kind == "APPROVAL")
        node["config"].update(config or {})
    else:
        node = _node(
            f"{normalized_kind.lower()}:{legacy_id}", normalized_type,
            config={"legacy_kind": normalized_kind, "legacy_id": str(legacy_id), **(config or {})},
            side_effect_class=side_effect_class,
        )
    node_key = node["node_key"]
    return {
        "schema_version": "1.0",
        "compatibility": {"kind": normalized_kind, "legacy_id": str(legacy_id), "schema": COMPAT_SCHEMA},
        "input_schema": {}, "output_schema": {}, "budget": {},
        "nodes": [_node("start", "START", config={"entry": True}), node,
                  _node("end", "END", config={"exit": True})],
        "edges": [_edge(f"{normalized_kind.lower()}-edge:start", "start", node_key),
                  _edge(f"{normalized_kind.lower()}-edge:end", node_key, "end")],
    }


def ensure_skill_graph(skill: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    skill = dict(skill or {})
    skill_id = str(skill.get("entity_id") or skill.get("skill_id") or "")
    if not skill_id:
        return None
    return _ensure_wrapper(
        "SKILL", skill_id, str(skill.get("title") or skill.get("skill_name") or f"Skill {skill_id}"),
        str(skill.get("owned_by_agent") or "system"),
        capability_definition("SKILL", skill_id, "SKILL", {"version": skill.get("skill_version") or "1.0"}),
        {"skill_name": str(skill.get("skill_name") or "")},
    )


def ensure_tool_graph(tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tool = dict(tool or {})
    tool_id = str(tool.get("tool_id") or tool.get("entity_id") or "")
    if not tool_id:
        return None
    return _ensure_wrapper(
        "TOOL", tool_id, str(tool.get("tool_name") or f"Tool {tool_id}"),
        str(tool.get("owned_by_agent") or "system"),
        capability_definition("TOOL", tool_id, "TOOL", {"version": tool.get("tool_version") or "1.0"},
                              side_effect_class="IDEMPOTENT_EXTERNAL"),
        {"tool_type": str(tool.get("tool_type") or "")},
    )


def ensure_approval_graph(approval: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    approval = dict(approval or {})
    approval_id = str(approval.get("approval_id") or "")
    if not approval_id:
        return None
    return _ensure_wrapper(
        "APPROVAL", approval_id, f"Approval {approval_id}",
        str(approval.get("requested_by") or "system"),
        capability_definition("APPROVAL", approval_id, "HUMAN", {
            "resource_ref": approval.get("entity_id"),
            "event_type": "APPROVAL_DECIDED",
            "correlation_key": approval_id,
            "wait_kind": "HUMAN",
        }),
        {"entity_type": approval.get("entity_type"), "entity_id": approval.get("entity_id")},
    )


def ensure_durable_job_graph(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    job = dict(job or {})
    job_id = str(job.get("job_id") or "")
    if not job_id:
        return None
    return _ensure_wrapper(
        "DURABLE_JOB", job_id, str(job.get("job_type") or f"Job {job_id}"),
        str(job.get("agent_id") or "system"),
        capability_definition("DURABLE_JOB", job_id, "AGENT", {
            "job_type": job.get("job_type"), "requires_approval": job.get("requires_approval") in {"Y", True},
        }, side_effect_class="IDEMPOTENT_EXTERNAL"),
        {"authoritative_runtime": "GRAPH_RUNTIME", "legacy_job_status": job.get("status")},
    )


def start_capability_run(kind: str, resource: Dict[str, Any], actor_id: str,
                         initial_state: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Start Skill/Tool/Approval/Job work through the durable Graph boundary."""
    normalized = str(kind or "").upper()
    ensure = {
        "SKILL": ensure_skill_graph,
        "TOOL": ensure_tool_graph,
        "APPROVAL": ensure_approval_graph,
        "DURABLE_JOB": ensure_durable_job_graph,
    }.get(normalized)
    if ensure is None:
        raise ValueError(f"unsupported Graph compatibility capability: {normalized}")
    resource = dict(resource or {})
    legacy_id = str(resource.get("approval_id") or resource.get("job_id") or
                     resource.get("tool_id") or resource.get("skill_id") or resource.get("entity_id") or "")
    binding = ensure(resource)
    if not binding or not legacy_id:
        return None
    return _start_graph_run(normalized, legacy_id, binding, actor_id, initial_state or {})


def legacy_history_reference(kind: str, legacy_id: str, status: Any, *, graph_version_id: Optional[str] = None,
                             topology: str = "UNKNOWN") -> Dict[str, Any]:
    """Describe old history without claiming replayable Graph semantics."""
    known_topology = topology.upper() in {"EXPLICIT", "COMPAT_WRAPPER"}
    return {
        "compatibility_schema": COMPAT_SCHEMA,
        "legacy_kind": str(kind).upper(),
        "legacy_id": str(legacy_id),
        "graph_version_id": graph_version_id,
        "status": graph_status(status),
        "history_class": "READ_ONLY_LEGACY",
        "topology_status": "KNOWN" if known_topology else "REVIEW_REQUIRED",
        "replay_supported": bool(known_topology and graph_version_id),
        "migration_note": (
            "The deployed legacy record did not store enough topology to infer Graph edges."
            if not known_topology else "Graph references are available for this compatibility wrapper."
        ),
    }


def migration_review(kind: str, legacy_id: str, reason: str, *, source_checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "status": "REVIEW_REQUIRED",
        "legacy_kind": str(kind).upper(),
        "legacy_id": str(legacy_id),
        "source_checkpoint_id": source_checkpoint_id,
        "reason": str(reason or "Unknown legacy topology"),
        "inferred_edges": False,
        "read_only": True,
    }


def optional_graph_fields(graph_version_id: Optional[str] = None, run_id: Optional[str] = None,
                          node_run_id: Optional[str] = None) -> Dict[str, Any]:
    """Return additive API fields without changing the v4.1 response shape."""
    return {
        "graph_version_id": graph_version_id,
        "graph_run_id": run_id,
        "graph_node_run_id": node_run_id,
        "graph_compatibility": COMPAT_SCHEMA,
    }


# ---------------------------------------------------------------------------
# Persistent compatibility bridge
# ---------------------------------------------------------------------------

_COMPAT_GRAPH_PREFIX = "COMPAT_"
_COMPAT_WORKER_PREFIX = "compat-worker-"


def _compat_graph_id(kind: str, legacy_id: str) -> str:
    digest = hashlib.sha256(f"{kind}:{legacy_id}".encode("utf-8")).hexdigest()
    return f"{_COMPAT_GRAPH_PREFIX}{digest[:112]}"


def _compat_worker_id(kind: str, legacy_id: str) -> str:
    digest = hashlib.sha256(f"{kind}:{legacy_id}".encode("utf-8")).hexdigest()
    return f"{_COMPAT_WORKER_PREFIX}{digest[:48]}"


def graph_runtime_available() -> bool:
    """Return whether the v4.2 compatibility ledger is installed.

    v4.1 stable packages intentionally do not contain Graph tables.  The
    bridge therefore probes one v4.2-only object and becomes a no-op there;
    all other database errors are handled by the caller as real failures.
    """
    if connection is None:
        return False
    try:
        connection.execute_query_one(
            "SELECT BINDING_ID FROM GRAPH_COMPAT_BINDINGS FETCH FIRST 1 ROWS ONLY"
        )
        return True
    except Exception as exc:
        message = str(exc).lower()
        if any(fragment in message for fragment in (
            "graph_compat_bindings", "undefined table", "table or view does not exist",
            "invalid object name",
        )):
            return False
        raise


def _binding_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    result = {str(key).lower(): value for key, value in dict(row).items()}
    metadata = result.get("metadata_json")
    if isinstance(metadata, str):
        try:
            result["metadata"] = json.loads(metadata)
        except (TypeError, ValueError):
            result["metadata"] = {}
    return result


def get_binding(kind: str, legacy_id: str) -> Optional[Dict[str, Any]]:
    if not graph_runtime_available():
        return None
    return _binding_row(connection.execute_query_one(
        "SELECT BINDING_ID, LEGACY_KIND, LEGACY_ID, GRAPH_ID, GRAPH_VERSION_ID, GRAPH_RUN_ID, "
        "STATUS, TOPOLOGY_STATUS, READ_ONLY, REVIEW_REASON, METADATA_JSON, CREATED_AT, "
        "UPDATED_AT, LAST_SYNC_AT FROM GRAPH_COMPAT_BINDINGS "
        "WHERE LEGACY_KIND = :legacy_kind AND LEGACY_ID = :legacy_id",
        {"legacy_kind": str(kind).upper(), "legacy_id": str(legacy_id)},
    ))


def _upsert_binding(kind: str, legacy_id: str, graph_id: str, *,
                    graph_version_id: Optional[str] = None,
                    graph_run_id: Optional[str] = None,
                    status: str = "ACTIVE", topology_status: str = "KNOWN",
                    read_only: str = "N", review_reason: Optional[str] = None,
                    metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = {
        "binding_id": f"BIND_{uuid.uuid4().hex}",
        "legacy_kind": str(kind).upper(), "legacy_id": str(legacy_id),
        "graph_id": graph_id, "graph_version_id": graph_version_id,
        "graph_run_id": graph_run_id, "status": str(status).upper(),
        "topology_status": str(topology_status).upper(), "read_only": str(read_only).upper(),
        "review_reason": review_reason, "metadata_json": json.dumps(metadata or {}, sort_keys=True),
    }
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() == "postgresql":
        connection.execute(
            "INSERT INTO GRAPH_COMPAT_BINDINGS "
            "(BINDING_ID, LEGACY_KIND, LEGACY_ID, GRAPH_ID, GRAPH_VERSION_ID, GRAPH_RUN_ID, "
            "STATUS, TOPOLOGY_STATUS, READ_ONLY, REVIEW_REASON, METADATA_JSON, CREATED_AT, UPDATED_AT, LAST_SYNC_AT) "
            "VALUES (:binding_id, :legacy_kind, :legacy_id, :graph_id, :graph_version_id, :graph_run_id, "
            ":status, :topology_status, :read_only, :review_reason, :metadata_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (LEGACY_KIND, LEGACY_ID) DO UPDATE SET GRAPH_ID = EXCLUDED.GRAPH_ID, "
            "GRAPH_VERSION_ID = EXCLUDED.GRAPH_VERSION_ID, GRAPH_RUN_ID = EXCLUDED.GRAPH_RUN_ID, "
            "STATUS = EXCLUDED.STATUS, TOPOLOGY_STATUS = EXCLUDED.TOPOLOGY_STATUS, READ_ONLY = EXCLUDED.READ_ONLY, "
            "REVIEW_REASON = EXCLUDED.REVIEW_REASON, METADATA_JSON = EXCLUDED.METADATA_JSON, "
            "UPDATED_AT = CURRENT_TIMESTAMP, LAST_SYNC_AT = CURRENT_TIMESTAMP",
            params,
        )
    else:
        connection.execute(
            "MERGE INTO GRAPH_COMPAT_BINDINGS dst "
            "USING (SELECT :legacy_kind AS LEGACY_KIND, :legacy_id AS LEGACY_ID" + connection.merge_scalar_suffix() + ") src "
            "ON (dst.LEGACY_KIND = src.LEGACY_KIND AND dst.LEGACY_ID = src.LEGACY_ID) "
            "WHEN MATCHED THEN UPDATE SET GRAPH_ID = :graph_id, GRAPH_VERSION_ID = :graph_version_id, "
            "GRAPH_RUN_ID = :graph_run_id, STATUS = :status, TOPOLOGY_STATUS = :topology_status, "
            "READ_ONLY = :read_only, REVIEW_REASON = :review_reason, METADATA_JSON = :metadata_json, "
            "UPDATED_AT = CURRENT_TIMESTAMP, LAST_SYNC_AT = CURRENT_TIMESTAMP "
            "WHEN NOT MATCHED THEN INSERT "
            "(BINDING_ID, LEGACY_KIND, LEGACY_ID, GRAPH_ID, GRAPH_VERSION_ID, GRAPH_RUN_ID, STATUS, "
            "TOPOLOGY_STATUS, READ_ONLY, REVIEW_REASON, METADATA_JSON, CREATED_AT, UPDATED_AT, LAST_SYNC_AT) "
            "VALUES (:binding_id, :legacy_kind, :legacy_id, :graph_id, :graph_version_id, :graph_run_id, :status, "
            ":topology_status, :read_only, :review_reason, :metadata_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            params,
        )
    return get_binding(kind, legacy_id) or params


def _portable_json_value(value: Any) -> Any:
    """Convert driver-specific numeric values to deterministic JSON values."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Graph compatibility definitions cannot contain non-finite Decimal values")
        if value == value.to_integral_value():
            return int(value)
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("Graph compatibility Decimal is outside the portable JSON range")
        return converted
    if isinstance(value, dict):
        return {key: _portable_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable_json_value(item) for item in value]
    return value


def _portable_digest(definition: Dict[str, Any]) -> str:
    """Hash topology without volatile database IDs or timestamps."""
    nodes = []
    for node in definition.get("nodes") or []:
        nodes.append({
            "node_key": str(node.get("node_key") or node.get("id") or ""),
            "node_type": str(node.get("node_type") or node.get("type") or "CONTROL").upper(),
            "type_version": str(node.get("type_version") or "1.0"),
            "config": _portable_json_value(node.get("config") or {}),
            "input_schema": _portable_json_value(node.get("input_schema") or {}),
            "output_schema": _portable_json_value(node.get("output_schema") or {}),
            "side_effect_class": str(node.get("side_effect_class") or "NONE").upper(),
            "capabilities": _portable_json_value(node.get("capabilities") or []),
            "resource_scope": _portable_json_value(node.get("resource_scope") or {}),
            "budget": _portable_json_value(node.get("budget") or {}),
        })
    edges = []
    for edge in definition.get("edges") or []:
        edges.append({
            "edge_id": str(edge.get("edge_id") or edge.get("id") or ""),
            "source_node_key": str(edge.get("source_node_key") or edge.get("source") or ""),
            "target_node_key": str(edge.get("target_node_key") or edge.get("target") or ""),
            "edge_kind": str(edge.get("edge_kind") or "NORMAL").upper(),
            "decision_type": str(edge.get("decision_type") or "FIXED").upper(),
            "condition": _portable_json_value(edge.get("condition") or {}),
            "config": _portable_json_value(edge.get("config") or {}),
            "order_index": int(edge.get("order_index") or 0), "join_key": edge.get("join_key"),
        })
    payload = {
        "schema_version": definition.get("schema_version") or "1.0",
        "input_schema": _portable_json_value(definition.get("input_schema") or {}),
        "output_schema": _portable_json_value(definition.get("output_schema") or {}),
        "budget": _portable_json_value(definition.get("budget") or {}),
        "nodes": sorted(nodes, key=lambda item: item["node_key"]),
        "edges": sorted(edges, key=lambda item: (item["source_node_key"], item["order_index"], item["edge_id"])),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _ensure_wrapper(kind: str, legacy_id: str, name: str, owner_ref: str,
                    definition: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not graph_runtime_available():
        return None
    from . import graph_compiler, graph_definition_api

    kind = str(kind).upper()
    legacy_id = str(legacy_id)
    # Oracle/YashanDB can return NUMBER values as Decimal from legacy JSON
    # projections. Normalize before the definition is persisted as JSON.
    definition = _portable_json_value(definition)
    binding = get_binding(kind, legacy_id)
    graph_id = (binding or {}).get("graph_id") or _compat_graph_id(kind, legacy_id)
    if not graph_definition_api.get_graph(graph_id):
        graph_definition_api.create_graph(
            name[:256], owner_ref, description=f"Compatibility Graph for {kind} {legacy_id}",
            graph_id=graph_id,
            metadata={"compatibility": COMPAT_SCHEMA, "legacy_kind": kind, "legacy_id": legacy_id, **(metadata or {})},
        )
    desired_digest = _portable_digest(definition)
    current_version_id = (binding or {}).get("graph_version_id")
    if current_version_id:
        current = graph_definition_api.get_version(current_version_id, include_topology=True)
        if current and str(current.get("status") or "").upper() in {"PUBLISHED", "DEPRECATED"}:
            try:
                if graph_definition_api.export_version(current_version_id)["definition"]["definition_digest"] == desired_digest:
                    return _upsert_binding(kind, legacy_id, graph_id, graph_version_id=current_version_id,
                                            graph_run_id=(binding or {}).get("graph_run_id"), metadata=metadata)
            except Exception:
                pass
    version_id = graph_definition_api.create_version(
        graph_id, definition.get("nodes") or [], definition.get("edges") or [],
        version_label=f"{kind.lower()}-{legacy_id[:80]}", parent_version_id=current_version_id,
        actor_id=owner_ref, reason=f"Create v4.2 compatibility wrapper for {kind} {legacy_id}",
        input_schema=definition.get("input_schema") or {}, output_schema=definition.get("output_schema") or {},
        budget=definition.get("budget") or {},
    )
    compiled = graph_compiler.compile_and_publish(
        version_id, owner_ref, f"Compile v4.2 compatibility wrapper for {kind} {legacy_id}"
    )
    if not compiled.get("valid") or not compiled.get("published"):
        raise ValueError({"compatibility": kind, "legacy_id": legacy_id, "diagnostics": compiled.get("diagnostics")})
    return _upsert_binding(kind, legacy_id, graph_id, graph_version_id=version_id,
                           graph_run_id=(binding or {}).get("graph_run_id"), metadata=metadata)


def ensure_task_plan_graph(plan: Dict[str, Any], steps: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    plan = dict(plan or {})
    plan_id = str(plan.get("plan_id") or "")
    if not plan_id:
        return None
    return _ensure_wrapper(
        "TASK_PLAN", plan_id, str(plan.get("goal") or f"Task Plan {plan_id}"),
        str(plan.get("agent_id") or "system"), task_plan_definition(plan, steps),
        {"goal": str(plan.get("goal") or "")},
    )


def ensure_loop_graph(loop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    loop = dict(loop or {})
    loop_id = str(loop.get("loop_id") or loop.get("entity_id") or "")
    if not loop_id:
        return None
    return _ensure_wrapper(
        "LOOP", loop_id, str(loop.get("title") or f"Loop {loop_id}"),
        str(loop.get("owned_by_agent") or "system"), loop_definition(loop),
        {"title": str(loop.get("title") or "")},
    )


def _drain_control_nodes(run_id: str, actor_id: str, worker_id: str) -> None:
    """Advance only START/END control nodes; business nodes need real Workers."""
    from . import graph_runtime
    for control_key in ("start", "end"):
        for _ in range(2):
            task = graph_runtime.claim_ready(
                worker_id, "compatibility", [], 120, actor_id, None, node_key=control_key
            )
            if not task:
                break
            graph_runtime.complete_attempt(
                task["lease_token"], {"compatibility_control": control_key}, actor_id,
                {"compatibility": True, "token_count": 0, "duration_ms": 0},
            )


def _start_graph_run(kind: str, legacy_id: str, binding: Dict[str, Any], actor_id: str,
                     initial_state: Optional[Dict[str, Any]] = None) -> Optional[str]:
    from . import graph_definition_api, graph_runtime
    version = graph_definition_api.get_version(str(binding.get("graph_version_id")), include_topology=True)
    if not version or not version.get("plan_id"):
        raise ValueError(f"compatibility wrapper for {kind} {legacy_id} has no compiled plan")
    current_run_id = binding.get("graph_run_id")
    if current_run_id:
        current_run = graph_runtime.get_run(str(current_run_id))
        if current_run and str(current_run.get("status") or "").upper() not in {"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
            return str(current_run_id)
    run_id = graph_runtime.create_run(
        str(binding["graph_version_id"]), str(version["plan_id"]), actor_id,
        initial_state=initial_state or {}, budget=version.get("budget") or {},
        idempotency_key=f"compat:{kind}:{legacy_id}:{uuid.uuid4().hex}",
    )
    _upsert_binding(kind, legacy_id, str(binding["graph_id"]),
                    graph_version_id=str(binding["graph_version_id"]), graph_run_id=run_id,
                    metadata={"authoritative_runtime": "GRAPH_RUNTIME"})
    _drain_control_nodes(run_id, actor_id, _compat_worker_id(kind, legacy_id))
    return run_id


def start_task_plan(plan: Dict[str, Any], steps: Iterable[Dict[str, Any]], actor_id: str) -> Optional[str]:
    binding = ensure_task_plan_graph(plan, steps)
    if not binding:
        return None
    return _start_graph_run("TASK_PLAN", str(plan["plan_id"]), binding, actor_id,
                            {"legacy_kind": "TASK_PLAN", "legacy_id": str(plan["plan_id"])})


def _complete_compat_node(kind: str, legacy_id: str, node_key: str, actor_id: str,
                          output_state: Dict[str, Any], *, failed: bool = False,
                          error_message: str = "") -> bool:
    binding = get_binding(kind, legacy_id)
    if not binding or not binding.get("graph_run_id"):
        return True
    from . import graph_runtime
    run = graph_runtime.get_run(str(binding["graph_run_id"]))
    if not run or str(run.get("status") or "").upper() in {"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
        return False
    worker_id = _compat_worker_id(kind, legacy_id)
    task = graph_runtime.claim_ready(worker_id, "compatibility", [], 120, actor_id, None, node_key=node_key)
    if not task:
        return False
    if failed:
        return graph_runtime.fail_attempt(task["lease_token"], "LEGACY_EXECUTION_FAILED", error_message, actor_id)
    graph_runtime.complete_attempt(
        task["lease_token"], output_state, actor_id,
        {"compatibility": True, "token_count": output_state.get("token_count", 0), "duration_ms": output_state.get("duration_ms", 0)},
    )
    _drain_control_nodes(str(binding["graph_run_id"]), actor_id, worker_id)
    return True


def sync_task_step(step: Dict[str, Any], status: str, actor_id: str, output: Optional[Dict[str, Any]] = None) -> bool:
    if str(status or "").upper() not in {"SUCCESS", "FAILED", "SKIPPED"}:
        return True
    step = dict(step or {})
    plan_id = str(step.get("plan_id") or "")
    if not plan_id or not graph_runtime_available():
        return True
    binding = get_binding("TASK_PLAN", plan_id)
    if not binding or not binding.get("graph_run_id"):
        return True
    return _complete_compat_node(
        "TASK_PLAN", plan_id, f"task:{step.get('step_id')}", actor_id,
        {"legacy_step_id": step.get("step_id"), "status": str(status).upper(), **(output or {})},
        failed=str(status).upper() == "FAILED", error_message=str((output or {}).get("error") or ""),
    )


def start_loop_run(run: Dict[str, Any], loop: Dict[str, Any], actor_id: str) -> Optional[str]:
    binding = ensure_loop_graph(loop)
    if not binding:
        return None
    legacy_run_id = str(run["run_id"])
    previous = get_binding("LOOP_RUN", legacy_run_id)
    run_binding = _upsert_binding(
        "LOOP_RUN", legacy_run_id, str(binding["graph_id"]),
        graph_version_id=str(binding["graph_version_id"]),
        graph_run_id=(previous or {}).get("graph_run_id"),
        metadata={"loop_id": str(loop.get("loop_id") or "")},
    )
    return _start_graph_run(
        "LOOP_RUN", legacy_run_id, run_binding, actor_id,
        {"legacy_kind": "LOOP_RUN", "legacy_id": legacy_run_id, "loop_continue": True},
    )


def sync_loop_iteration(run_id: str, iteration: Dict[str, Any], continue_running: bool,
                        actor_id: str) -> bool:
    binding = get_binding("LOOP_RUN", str(run_id))
    if not binding or not binding.get("graph_run_id"):
        return True
    return _complete_compat_node(
        "LOOP_RUN", str(run_id), "loop", actor_id,
        {"loop_continue": bool(continue_running), "iteration_id": iteration.get("iteration_id"),
         "evaluation": iteration.get("evaluation") or {}, "status": iteration.get("status")},
    )


def _legacy_graph_run(kind: str, legacy_id: str):
    """Return the compatibility binding and Graph Run, if v4.2 is installed."""
    binding = get_binding(kind, str(legacy_id))
    if not binding or not binding.get("graph_run_id"):
        return binding, None
    from . import graph_runtime
    return binding, graph_runtime.get_run(str(binding["graph_run_id"]))


def pause_legacy_run(kind: str, legacy_id: str, actor_id: str, reason: str) -> bool:
    binding, run = _legacy_graph_run(kind, legacy_id)
    if not binding or not run:
        return True
    from . import graph_runtime
    if str(run.get("status") or "").upper() in {"PAUSED", "SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
        return str(run.get("status") or "").upper() == "PAUSED"
    return graph_runtime.pause_run(str(binding["graph_run_id"]), actor_id, reason or "Legacy run paused")


def resume_legacy_run(kind: str, legacy_id: str, actor_id: str, reason: str) -> bool:
    binding, run = _legacy_graph_run(kind, legacy_id)
    if not binding or not run:
        return True
    from . import graph_runtime
    if str(run.get("status") or "").upper() in {"RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
        return str(run.get("status") or "").upper() == "RUNNING"
    return graph_runtime.resume_run(str(binding["graph_run_id"]), actor_id, reason or "Legacy run resumed")


def complete_legacy_run(kind: str, legacy_id: str, actor_id: str, reason: str) -> bool:
    """Finish a compatibility run through its declared control-flow edges."""
    binding, run = _legacy_graph_run(kind, legacy_id)
    if not binding or not run:
        return True
    from . import graph_runtime
    graph_run_id = str(binding["graph_run_id"])
    status = str(run.get("status") or "").upper()
    if status in {"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
        return status == "SUCCEEDED"

    worker_id = _compat_worker_id(kind, legacy_id)
    _drain_control_nodes(graph_run_id, actor_id, worker_id)
    run = graph_runtime.get_run(graph_run_id) or run
    if str(run.get("status") or "").upper() in {"SUCCEEDED", "FAILED", "CANCELLED", "REVIEW_REQUIRED"}:
        return str(run.get("status") or "").upper() == "SUCCEEDED"

    active_nodes = [
        node for node in graph_runtime.list_node_runs(graph_run_id)
        if str(node.get("status") or "").upper() in {"READY", "WAITING", "RUNNING"}
    ]
    # A legacy Loop has one business node.  Skipping it with an explicit
    # false continuation value selects the compiled END edge and preserves
    # the normal transition/checkpoint/trace path.
    loop_node = next((node for node in active_nodes if node.get("node_key") == "loop"), None)
    if loop_node:
        graph_runtime.skip_node(
            graph_run_id, str(loop_node["node_run_id"]), actor_id,
            reason or "Legacy run completed",
            {"loop_continue": False, "legacy_completion": True},
        )
    else:
        start_node = next((node for node in active_nodes if node.get("node_key") == "start"), None)
        if start_node:
            _complete_compat_node(
                kind, str(legacy_id), "start", actor_id,
                {"loop_continue": False, "legacy_completion": True},
            )
    _drain_control_nodes(graph_run_id, actor_id, worker_id)
    final = graph_runtime.get_run(graph_run_id) or {}
    return str(final.get("status") or "").upper() == "SUCCEEDED"


def finish_legacy_run(kind: str, legacy_id: str, actor_id: str, reason: str, *, success: bool = False) -> bool:
    binding = get_binding(kind, str(legacy_id))
    if not binding or not binding.get("graph_run_id"):
        return True
    if success:
        return complete_legacy_run(kind, legacy_id, actor_id, reason or "Legacy run completed")
    from . import graph_runtime
    return graph_runtime.cancel_run(str(binding["graph_run_id"]), actor_id, reason or "Legacy execution stopped")
