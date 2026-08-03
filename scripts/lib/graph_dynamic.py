"""Governed Dynamic Graph v1.

Dynamic changes create a child Draft from an immutable source Definition.
They are data-only canonical operations; no user expression, Python, SQL, or
connector code is evaluated by this module.  Publication and Run migration
remain subject to the normal Compiler, approval, and lease-fencing controls.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, List, Optional

from . import connection, graph_compiler, graph_definition_api, profile_api


OPERATIONS = frozenset({"ADD_NODE", "REMOVE_NODE", "REPLACE_NODE", "ADD_EDGE", "REMOVE_EDGE", "REPLACE_EDGE", "SET_BUDGET", "STATE_MAP"})
PREVIEW_PROFILES = frozenset({"graph-preview", "development", "experimental-4.2"})


def _id() -> str:
    return "GDP_" + uuid.uuid4().hex


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def require_preview() -> None:
    if profile_api.current_profile() not in PREVIEW_PROFILES:
        raise PermissionError("Dynamic Graph is disabled outside the graph-preview capability")


def normalize_operations(operations: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(operations or []):
        if not isinstance(raw, dict):
            raise ValueError(f"dynamic operation {index} must be an object")
        kind = str(raw.get("op") or raw.get("operation") or "").upper()
        if kind not in OPERATIONS:
            raise ValueError(f"unsupported dynamic operation: {kind}")
        result = {"op": kind}
        if kind in {"ADD_NODE", "REPLACE_NODE"}:
            if not isinstance(raw.get("node"), dict):
                raise ValueError(f"{kind} requires a node object")
            result["node"] = dict(raw["node"])
            if kind == "REPLACE_NODE":
                result["node_key"] = str(raw.get("node_key") or result["node"].get("node_key") or "")
        elif kind in {"REMOVE_NODE", "REMOVE_EDGE"}:
            key = "node_key" if kind == "REMOVE_NODE" else "edge_id"
            result[key] = str(raw.get(key) or "")
        elif kind in {"ADD_EDGE", "REPLACE_EDGE"}:
            if not isinstance(raw.get("edge"), dict):
                raise ValueError(f"{kind} requires an edge object")
            result["edge"] = dict(raw["edge"])
            if kind == "REPLACE_EDGE":
                result["edge_id"] = str(raw.get("edge_id") or result["edge"].get("edge_id") or "")
        elif kind == "SET_BUDGET":
            if not isinstance(raw.get("budget"), dict):
                raise ValueError("SET_BUDGET requires a budget object")
            result["budget"] = dict(raw["budget"])
        else:
            if not isinstance(raw.get("mapping"), dict):
                raise ValueError("STATE_MAP requires a mapping object")
            result["mapping"] = dict(raw["mapping"])
        for key in ("node_key", "edge_id"):
            if key in result and not result[key]:
                raise ValueError(f"{kind} requires {key}")
        normalized.append(result)
    if not normalized:
        raise ValueError("at least one dynamic operation is required")
    return normalized


def apply_operations(source: Dict[str, Any], operations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply canonical operations to a copy of a source topology."""
    result = {
        "nodes": [dict(item) for item in (source.get("nodes") or [])],
        "edges": [dict(item) for item in (source.get("edges") or [])],
        "budget": dict(source.get("budget") or {}),
        "state_mapping": {},
    }
    for operation in normalize_operations(operations):
        kind = operation["op"]
        if kind == "ADD_NODE":
            key = str(operation["node"].get("node_key") or operation["node"].get("id") or "")
            if not key or any(str(item.get("node_key") or item.get("id") or "") == key for item in result["nodes"]):
                raise ValueError("ADD_NODE requires a unique node_key")
            result["nodes"].append(operation["node"])
        elif kind == "REMOVE_NODE":
            key = operation["node_key"]
            if not any(str(item.get("node_key") or item.get("id") or "") == key for item in result["nodes"]):
                raise ValueError("REMOVE_NODE references an unknown node_key")
            result["nodes"] = [item for item in result["nodes"] if str(item.get("node_key") or item.get("id") or "") != key]
            result["edges"] = [item for item in result["edges"] if str(item.get("source_node_key") or item.get("source") or "") != key and str(item.get("target_node_key") or item.get("target") or "") != key]
        elif kind == "REPLACE_NODE":
            key = operation["node_key"]
            replacements = [item for item in result["nodes"] if str(item.get("node_key") or item.get("id") or "") == key]
            if len(replacements) != 1:
                raise ValueError("REPLACE_NODE references an unknown node_key")
            replacement = dict(operation["node"])
            replacement["node_key"] = key
            result["nodes"] = [replacement if str(item.get("node_key") or item.get("id") or "") == key else item for item in result["nodes"]]
        elif kind == "ADD_EDGE":
            edge_id = str(operation["edge"].get("edge_id") or operation["edge"].get("id") or "")
            if not edge_id or any(str(item.get("edge_id") or item.get("id") or "") == edge_id for item in result["edges"]):
                raise ValueError("ADD_EDGE requires a unique edge_id")
            result["edges"].append(operation["edge"])
        elif kind == "REMOVE_EDGE":
            edge_id = operation["edge_id"]
            if not any(str(item.get("edge_id") or item.get("id") or "") == edge_id for item in result["edges"]):
                raise ValueError("REMOVE_EDGE references an unknown edge_id")
            result["edges"] = [item for item in result["edges"] if str(item.get("edge_id") or item.get("id") or "") != edge_id]
        elif kind == "REPLACE_EDGE":
            edge_id = operation["edge_id"]
            if not any(str(item.get("edge_id") or item.get("id") or "") == edge_id for item in result["edges"]):
                raise ValueError("REPLACE_EDGE references an unknown edge_id")
            replacement = dict(operation["edge"])
            replacement["edge_id"] = edge_id
            result["edges"] = [replacement if str(item.get("edge_id") or item.get("id") or "") == edge_id else item for item in result["edges"]]
        elif kind == "SET_BUDGET":
            result["budget"] = dict(operation["budget"])
        else:
            result["state_mapping"].update(operation["mapping"])
    return result


def assess_risk(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    source_nodes = {str(item.get("node_key") or item.get("id") or ""): item for item in source.get("nodes") or []}
    target_nodes = {str(item.get("node_key") or item.get("id") or ""): item for item in target.get("nodes") or []}
    changes: List[str] = []
    if set(target_nodes) - set(source_nodes):
        changes.append("NODE_ADDED")
    if set(source_nodes) - set(target_nodes):
        changes.append("NODE_REMOVED")
    for key in set(source_nodes) & set(target_nodes):
        old = source_nodes[key]
        new = target_nodes[key]
        if str(old.get("side_effect_class") or "NONE").upper() != str(new.get("side_effect_class") or "NONE").upper():
            changes.append("SIDE_EFFECT_CHANGED")
        if _canonical(old.get("resource_scope") or {}) != _canonical(new.get("resource_scope") or {}):
            changes.append("SCOPE_CHANGED")
    if _canonical(source.get("budget") or {}) != _canonical(target.get("budget") or {}):
        changes.append("BUDGET_CHANGED")
    high = {"SIDE_EFFECT_CHANGED", "SCOPE_CHANGED", "NODE_REMOVED"}
    return {"level": "HIGH" if high.intersection(changes) else ("MEDIUM" if changes else "LOW"),
            "changes": sorted(set(changes)), "requires_approval": bool(high.intersection(changes))}


def _child_topology(target: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Drop source-version physical IDs before inserting an immutable child.

    ``NODE_ID`` and ``EDGE_ID`` are global storage identities, not stable
    authoring identifiers. Carrying them into a child version would collide
    with the source version on every adapter. ``node_key`` remains stable for
    mapping and migration; the definition service allocates new physical IDs.
    """
    nodes = [{key: value for key, value in graph_definition_api._public_node(node).items() if key != "node_id"}
             for node in target.get("nodes") or []]
    edges = [{key: value for key, value in graph_definition_api._public_edge(edge).items() if key != "edge_id"}
             for edge in target.get("edges") or []]
    return nodes, edges


def create_draft(source_version_id: str, operations: Iterable[Dict[str, Any]], actor_id: str, reason: str,
                 *, run_id: str = "", checkpoint_id: str = "", expected_version: str = "") -> Dict[str, Any]:
    require_preview()
    if not str(actor_id or "").strip() or not str(reason or "").strip():
        raise ValueError("dynamic proposal actor and reason are required")
    source = graph_definition_api.get_version(source_version_id, include_topology=True)
    if not source:
        raise ValueError("source Graph Version not found")
    if expected_version and expected_version != source_version_id:
        raise ValueError("source Graph Version fence does not match")
    target = apply_operations(source, operations)
    risk = assess_risk(source, target)
    child_nodes, child_edges = _child_topology(target)
    version_id = graph_definition_api.create_version(
        str(source["graph_id"]), child_nodes, child_edges,
        version_label="Dynamic Draft", parent_version_id=source_version_id, actor_id=actor_id, reason=reason,
        source_run_id=run_id or None, source_checkpoint_id=checkpoint_id or None,
        input_schema=source.get("input_schema") or {}, output_schema=source.get("output_schema") or {}, budget=target["budget"],
    )
    compilation = graph_compiler.compile_version(version_id, persist=True)
    if not compilation.get("valid"):
        raise ValueError("dynamic operations do not compile: " + _canonical(compilation.get("diagnostics") or [])[:2000])
    proposal_id = _id()
    approval_id = ""
    if risk["requires_approval"]:
        try:
            from . import governance_api
            approval = governance_api.create_approval_request(
                actor_id, proposal_id, "DYNAMIC_GRAPH_PUBLISH", required_approvals=2,
                eligible_groups=("SECURITY", "APPROVAL"), prohibited_combinations=("REQUESTER",),
                reason=reason, idempotency_key="dynamic:" + proposal_id,
            )
            approval_id = str(approval.get("approval_id") or "")
        except ImportError:
            # Community has no approval surface.  A high-risk proposal stays
            # non-publishable rather than silently lowering its requirement.
            approval_id = "UNAVAILABLE"
    def _persist(tx: Any) -> None:
        tx.execute(
            "INSERT INTO GRAPH_DYNAMIC_PROPOSALS (PROPOSAL_ID, SOURCE_VERSION_ID, TARGET_VERSION_ID, RUN_ID, CHECKPOINT_ID, "
            "OPERATIONS_JSON, STATE_MAPPING_JSON, RISK_JSON, STATUS, APPROVAL_ID, EXPECTED_VERSION, ACTOR_ID, REASON, CREATED_AT, UPDATED_AT) "
            "VALUES (:proposal_id, :source_version_id, :target_version_id, :run_id, :checkpoint_id, :operations_json, "
            ":state_mapping_json, :risk_json, :status, :approval_id, :expected_version, :actor_id, :reason, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            {"proposal_id": proposal_id, "source_version_id": source_version_id, "target_version_id": version_id,
             "run_id": run_id or None, "checkpoint_id": checkpoint_id or None,
             "operations_json": _canonical(normalize_operations(operations)), "state_mapping_json": _canonical(target["state_mapping"]),
             "risk_json": _canonical(risk), "status": "PENDING_APPROVAL" if risk["requires_approval"] else "DRAFT",
             "approval_id": approval_id or None, "expected_version": expected_version or source_version_id, "actor_id": actor_id, "reason": reason[:2000]},
        )
    connection.execute_transaction_callback(_persist)
    return {"proposal_id": proposal_id, "source_version_id": source_version_id, "target_version_id": version_id,
            "status": "PENDING_APPROVAL" if risk["requires_approval"] else "DRAFT", "risk": risk,
            "approval_id": approval_id or None, "compilation": compilation}


def publishable(target_version_id: str) -> bool:
    """Recheck approval state at publication time, not only at draft creation."""
    proposal = connection.execute_query_one(
        "SELECT STATUS, APPROVAL_ID FROM GRAPH_DYNAMIC_PROPOSALS WHERE TARGET_VERSION_ID = :version_id",
        {"version_id": target_version_id},
    )
    if not proposal:
        return True
    status = str(proposal.get("status") or "").upper()
    if status == "DRAFT":
        return True
    if status != "PENDING_APPROVAL" or not proposal.get("approval_id"):
        return False
    try:
        row = connection.execute_query_one(
            "SELECT STATUS FROM GOV_APPROVAL_REQUESTS WHERE APPROVAL_ID = :approval_id",
            {"approval_id": proposal["approval_id"]},
        )
    except Exception:
        return False
    if not row or str(row.get("status") or "").upper() != "APPROVED":
        return False
    return connection.execute(
        "UPDATE GRAPH_DYNAMIC_PROPOSALS SET STATUS = 'APPROVED', UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE TARGET_VERSION_ID = :version_id AND STATUS = 'PENDING_APPROVAL'",
        {"version_id": target_version_id},
    ) > 0


def list_proposals(limit: int = 100) -> List[Dict[str, Any]]:
    rows = connection.execute_query(
        "SELECT PROPOSAL_ID, SOURCE_VERSION_ID, TARGET_VERSION_ID, RUN_ID, STATUS, APPROVAL_ID, RISK_JSON, ACTOR_ID, REASON, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_DYNAMIC_PROPOSALS ORDER BY UPDATED_AT DESC FETCH FIRST :limit ROWS ONLY",
        {"limit": max(1, min(int(limit), 500))},
    )
    result = []
    for row in rows:
        item = {str(key).lower(): value for key, value in dict(row).items()}
        try:
            item["risk"] = json.loads(item.pop("risk_json") or "{}")
        except (TypeError, ValueError):
            item["risk"] = {}
        result.append(item)
    return result
