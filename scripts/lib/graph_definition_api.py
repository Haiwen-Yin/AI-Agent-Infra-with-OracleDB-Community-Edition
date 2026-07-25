"""Versioned execution-graph definition service for v4.2.x.

The existing ``ENTITIES``/``ENTITY_EDGES`` graph remains the domain graph.
This module owns the separate, versioned execution graph used by the compiler
and runtime.  Definitions are deliberately JSON-shaped at the service edge so
the same contract can be used by REST, Skill clients, and the Web editor.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import connection, graph_adapter
from .graph_contracts import is_valid_status_transition

GRAPH_SCHEMA_VERSION = "1.0"
GRAPH_EXPORT_FORMAT = "chuanxu-graph-definition"
GRAPH_EXPORT_VERSION = "1"
GRAPH_STATUSES = frozenset({"DRAFT", "VALIDATED", "PUBLISHED", "DEPRECATED", "ARCHIVED"})
MUTABLE_VERSION_STATUSES = frozenset({"DRAFT"})
NODE_SIDE_EFFECT_CLASSES = frozenset({
    "NONE", "DB_TRANSACTIONAL", "IDEMPOTENT_EXTERNAL", "NON_IDEMPOTENT",
})


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> datetime:
    """Return a DB-driver-friendly UTC timestamp without an offset.

    The Graph tables use ``TIMESTAMP`` (rather than ``TIMESTAMP WITH TIME
    ZONE``) on all three adapters.  Binding an ISO-8601 string with ``+00:00``
    makes Oracle apply its session date format and fail before the transaction
    starts; a naive UTC datetime is accepted consistently by all drivers.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default if default is not None else value
    return value


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    result = {str(k).lower(): v for k, v in dict(row).items()}
    for key in (
        "input_schema_json", "output_schema_json", "config_json", "capability_json",
        "resource_scope_json", "budget_json", "condition_json", "metadata_json",
        "manifest_json", "dependencies_json", "diff_json", "diagnostics_json",
        "plan_json", "schema_json",
    ):
        if key in result:
            result[key.removesuffix("_json")] = _json(result[key], {})
    return result


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _assert_mutable(version: Dict[str, Any]) -> None:
    status = str(version.get("status") or "").upper()
    if status not in MUTABLE_VERSION_STATUSES:
        raise ValueError(f"Graph Version {version.get('graph_version_id')} is {status}; create a new Draft")


def _assert_status_transition(old: str, new: str) -> None:
    if not is_valid_status_transition(old, new):
        raise ValueError(f"Invalid Graph Version lifecycle transition: {old} -> {new}")




def create_graph(
    name: str,
    owner_ref: str,
    description: Optional[str] = None,
    graph_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    if not str(name or "").strip():
        raise ValueError("graph name is required")
    if not str(owner_ref or "").strip():
        raise ValueError("owner_ref is required")
    graph_id = graph_id or _id("GRAPH")
    connection.execute(
        "INSERT INTO GRAPH_DEFINITIONS "
        "(GRAPH_ID, GRAPH_NAME, DESCRIPTION, OWNER_REF, STATUS, METADATA_JSON) "
        "VALUES (:graph_id, :graph_name, :description, :owner_ref, 'ACTIVE', :metadata_json)",
        {
            "graph_id": graph_id,
            "graph_name": name.strip(),
            "description": description,
            "owner_ref": owner_ref,
            "metadata_json": canonical_json(metadata or {}),
        },
    )
    return graph_id


def get_graph(graph_id: str) -> Optional[Dict[str, Any]]:
    row = connection.execute_query_one(
        "SELECT GRAPH_ID, GRAPH_NAME, DESCRIPTION, OWNER_REF, STATUS, METADATA_JSON, "
        "CREATED_AT, UPDATED_AT FROM GRAPH_DEFINITIONS WHERE GRAPH_ID = :graph_id",
        {"graph_id": graph_id},
    )
    return _row(row)


def list_graphs(status: Optional[str] = None, owner_ref: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conditions = ["1 = 1"]
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if status:
        conditions.append("STATUS = :status")
        params["status"] = status.upper()
    if owner_ref:
        conditions.append("OWNER_REF = :owner_ref")
        params["owner_ref"] = owner_ref
    rows = connection.execute_query(
        "SELECT GRAPH_ID, GRAPH_NAME, DESCRIPTION, OWNER_REF, STATUS, METADATA_JSON, "
        "CREATED_AT, UPDATED_AT FROM GRAPH_DEFINITIONS WHERE " + " AND ".join(conditions) +
        " ORDER BY UPDATED_AT DESC FETCH FIRST :limit ROWS ONLY", params,
    )
    return _rows(rows)


def create_version(
    graph_id: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    *,
    version_label: Optional[str] = None,
    parent_version_id: Optional[str] = None,
    actor_id: str = "system",
    reason: Optional[str] = None,
    source_run_id: Optional[str] = None,
    source_checkpoint_id: Optional[str] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    budget: Optional[Dict[str, Any]] = None,
    version_id: Optional[str] = None,
) -> str:
    """Create a Draft and its topology atomically.

    Structural validation is delegated to the Compiler, but identity and
    duplicate-key checks happen before any database write.
    """
    graph = get_graph(graph_id)
    if not graph:
        raise ValueError(f"Graph {graph_id} not found")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("nodes and edges must be arrays")
    node_keys = [str(node.get("node_key") or node.get("id") or "") for node in nodes]
    if any(not key for key in node_keys):
        raise ValueError("every node requires node_key")
    if len(node_keys) != len(set(node_keys)):
        raise ValueError("node_key values must be unique")
    for edge in edges:
        if not edge.get("source_node_key") or not edge.get("target_node_key"):
            raise ValueError("every edge requires source_node_key and target_node_key")

    version_id = version_id or _id("GV")
    version_row = connection.execute_query_one(
        "SELECT COALESCE(MAX(VERSION_NO), 0) AS VERSION_NO FROM GRAPH_VERSIONS WHERE GRAPH_ID = :graph_id",
        {"graph_id": graph_id},
    )
    version_no = int((version_row or {}).get("version_no") or 0) + 1
    created_at = _now()
    projection_nodes: List[Dict[str, Any]] = []
    statements: List[tuple[str, Optional[Dict[str, Any]]]] = [(
        "INSERT INTO GRAPH_VERSIONS "
        "(GRAPH_VERSION_ID, GRAPH_ID, VERSION_NO, VERSION_LABEL, STATUS, PARENT_VERSION_ID, "
        "SCHEMA_VERSION, INPUT_SCHEMA_JSON, OUTPUT_SCHEMA_JSON, BUDGET_JSON, ACTOR_ID, REASON, "
        "SOURCE_RUN_ID, SOURCE_CHECKPOINT_ID, CREATED_AT, UPDATED_AT) "
        "VALUES (:version_id, :graph_id, :version_no, :version_label, 'DRAFT', :parent_version_id, "
        ":schema_version, :input_schema_json, :output_schema_json, :budget_json, :actor_id, :reason, "
        ":source_run_id, :source_checkpoint_id, :created_at, :updated_at)",
        {
            "version_id": version_id, "graph_id": graph_id, "version_no": version_no,
            "version_label": version_label or f"v{version_no}", "parent_version_id": parent_version_id,
            "schema_version": GRAPH_SCHEMA_VERSION,
            "input_schema_json": canonical_json(input_schema or {}),
            "output_schema_json": canonical_json(output_schema or {}),
            "budget_json": canonical_json(budget or {}), "actor_id": actor_id,
            "reason": reason or "Initial Draft", "source_run_id": source_run_id,
            "source_checkpoint_id": source_checkpoint_id, "created_at": created_at, "updated_at": created_at,
        },
    )]
    for node in nodes:
        node_id = str(node.get("node_id") or _id("GN"))
        node_key = str(node.get("node_key") or node.get("id"))
        side_effect = str(node.get("side_effect_class") or "NONE").upper()
        if side_effect not in NODE_SIDE_EFFECT_CLASSES:
            raise ValueError(f"unsupported side_effect_class: {side_effect}")
        statements.append((
            "INSERT INTO GRAPH_NODES "
            "(NODE_ID, GRAPH_VERSION_ID, NODE_KEY, NODE_TYPE, TYPE_VERSION, CONFIG_JSON, "
            "INPUT_SCHEMA_JSON, OUTPUT_SCHEMA_JSON, SIDE_EFFECT_CLASS, CAPABILITY_JSON, "
            "RESOURCE_SCOPE_JSON, BUDGET_JSON, CREATED_AT) VALUES "
            "(:node_id, :version_id, :node_key, :node_type, :type_version, :config_json, "
            ":input_schema_json, :output_schema_json, :side_effect_class, :capability_json, "
            ":resource_scope_json, :budget_json, :created_at)",
            {
                "node_id": node_id, "version_id": version_id, "node_key": node_key,
                "node_type": str(node.get("node_type") or node.get("type") or "CONTROL"),
                "type_version": str(node.get("type_version") or "1.0"),
                "config_json": canonical_json(node.get("config") or {}),
                "input_schema_json": canonical_json(node.get("input_schema") or {}),
                "output_schema_json": canonical_json(node.get("output_schema") or {}),
                "side_effect_class": side_effect,
                "capability_json": canonical_json(node.get("capabilities") or []),
                "resource_scope_json": canonical_json(node.get("resource_scope") or {}),
                "budget_json": canonical_json(node.get("budget") or {}),
                "created_at": created_at,
            },
        ))
        projection_nodes.append({**node, "node_id": node_id, "node_key": node_key,
                                 "node_type": str(node.get("node_type") or node.get("type") or "CONTROL")})
    for edge in edges:
        statements.append((
            "INSERT INTO GRAPH_EDGES "
            "(EDGE_ID, GRAPH_VERSION_ID, SOURCE_NODE_KEY, TARGET_NODE_KEY, EDGE_KIND, "
            "DECISION_TYPE, CONDITION_JSON, CONFIG_JSON, ORDER_INDEX, JOIN_KEY, CREATED_AT) VALUES "
            "(:edge_id, :version_id, :source_node_key, :target_node_key, :edge_kind, "
            ":decision_type, :condition_json, :config_json, :order_index, :join_key, :created_at)",
            {
                "edge_id": str(edge.get("edge_id") or _id("GE")), "version_id": version_id,
                "source_node_key": str(edge["source_node_key"]),
                "target_node_key": str(edge["target_node_key"]),
                "edge_kind": str(edge.get("edge_kind") or "NORMAL").upper(),
                "decision_type": str(edge.get("decision_type") or "FIXED").upper(),
                "condition_json": canonical_json(edge.get("condition") or {}),
                "config_json": canonical_json(edge.get("config") or {}),
                "order_index": int(edge.get("order_index") or 0),
                "join_key": edge.get("join_key"), "created_at": created_at,
            },
        ))
    # Adapter-specific native graph projection is part of this transaction.
    # Oracle/YashanDB read the dedicated tables directly; PostgreSQL uses AGE.
    statements.extend(graph_adapter.projection_statements(version_id, projection_nodes, edges))
    # VERSION_NO is allocated optimistically.  The unique key remains the
    # authoritative concurrency barrier; retrying after a collision avoids
    # publishing duplicate version numbers under parallel editors.
    for attempt in range(3):
        try:
            connection.execute_transaction(statements)
            return version_id
        except Exception:
            if attempt == 2:
                raise
            version_row = connection.execute_query_one(
                "SELECT COALESCE(MAX(VERSION_NO), 0) AS VERSION_NO FROM GRAPH_VERSIONS WHERE GRAPH_ID = :graph_id",
                {"graph_id": graph_id},
            )
            version_no = int((version_row or {}).get("version_no") or 0) + 1
            statements[0][1]["version_no"] = version_no
            if not version_label:
                statements[0][1]["version_label"] = f"v{version_no}"


def get_version(version_id: str, include_topology: bool = True) -> Optional[Dict[str, Any]]:
    row = connection.execute_query_one(
        "SELECT GRAPH_VERSION_ID, GRAPH_ID, VERSION_NO, VERSION_LABEL, STATUS, PARENT_VERSION_ID, "
        "SCHEMA_VERSION, INPUT_SCHEMA_JSON, OUTPUT_SCHEMA_JSON, BUDGET_JSON, DEFINITION_DIGEST, "
        "SIGNATURE, VALIDATION_DIAGNOSTICS_JSON, RISK_LEVEL, ACTOR_ID, REASON, SOURCE_RUN_ID, "
        "SOURCE_CHECKPOINT_ID, CREATED_AT, UPDATED_AT FROM GRAPH_VERSIONS "
        "WHERE GRAPH_VERSION_ID = :version_id", {"version_id": version_id},
    )
    result = _row(row)
    if not result or not include_topology:
        return result
    plan_row = connection.execute_query_one(
        "SELECT PLAN_ID FROM GRAPH_COMPILE_PLANS WHERE GRAPH_VERSION_ID = :version_id",
        {"version_id": version_id},
    )
    if plan_row:
        result["plan_id"] = plan_row.get("plan_id")
    result["nodes"] = _rows(connection.execute_query(
        "SELECT NODE_ID, GRAPH_VERSION_ID, NODE_KEY, NODE_TYPE, TYPE_VERSION, CONFIG_JSON, "
        "INPUT_SCHEMA_JSON, OUTPUT_SCHEMA_JSON, SIDE_EFFECT_CLASS, CAPABILITY_JSON, "
        "RESOURCE_SCOPE_JSON, BUDGET_JSON, CREATED_AT FROM GRAPH_NODES "
        "WHERE GRAPH_VERSION_ID = :version_id ORDER BY NODE_KEY", {"version_id": version_id}))
    result["edges"] = _rows(connection.execute_query(
        "SELECT EDGE_ID, GRAPH_VERSION_ID, SOURCE_NODE_KEY, TARGET_NODE_KEY, EDGE_KIND, "
        "DECISION_TYPE, CONDITION_JSON, CONFIG_JSON, ORDER_INDEX, JOIN_KEY, CREATED_AT "
        "FROM GRAPH_EDGES WHERE GRAPH_VERSION_ID = :version_id "
        "ORDER BY SOURCE_NODE_KEY, ORDER_INDEX, EDGE_ID", {"version_id": version_id}))
    return result


def list_versions(graph_id: str, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conditions = ["GRAPH_ID = :graph_id"]
    params: Dict[str, Any] = {"graph_id": graph_id, "limit": max(1, min(int(limit), 500))}
    if status:
        conditions.append("STATUS = :status")
        params["status"] = status.upper()
    rows = connection.execute_query(
        "SELECT GRAPH_VERSION_ID, GRAPH_ID, VERSION_NO, VERSION_LABEL, STATUS, PARENT_VERSION_ID, "
        "SCHEMA_VERSION, DEFINITION_DIGEST, SIGNATURE, VALIDATION_DIAGNOSTICS_JSON, RISK_LEVEL, "
        "ACTOR_ID, REASON, SOURCE_RUN_ID, SOURCE_CHECKPOINT_ID, CREATED_AT, UPDATED_AT "
        "FROM GRAPH_VERSIONS WHERE " + " AND ".join(conditions) +
        " ORDER BY VERSION_NO DESC FETCH FIRST :limit ROWS ONLY", params,
    )
    return _rows(rows)


def _public_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Return the stable exchange shape without database timestamps or IDs."""
    return {
        "node_key": str(node.get("node_key") or node.get("id") or ""),
        "node_type": str(node.get("node_type") or node.get("type") or "CONTROL").upper(),
        "type_version": str(node.get("type_version") or "1.0"),
        "config": node.get("config") or {},
        "input_schema": node.get("input_schema") or {},
        "output_schema": node.get("output_schema") or {},
        "side_effect_class": str(node.get("side_effect_class") or "NONE").upper(),
        "capabilities": node.get("capabilities") or [],
        "resource_scope": node.get("resource_scope") or {},
        "budget": node.get("budget") or {},
    }


def _public_edge(edge: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "edge_id": str(edge.get("edge_id") or edge.get("id") or ""),
        "source_node_key": str(edge.get("source_node_key") or edge.get("source") or ""),
        "target_node_key": str(edge.get("target_node_key") or edge.get("target") or ""),
        "edge_kind": str(edge.get("edge_kind") or "NORMAL").upper(),
        "decision_type": str(edge.get("decision_type") or "FIXED").upper(),
        "condition": edge.get("condition") or {},
        "config": edge.get("config") or {},
        "order_index": int(edge.get("order_index") or 0),
        "join_key": edge.get("join_key"),
    }


def export_version(version_id: str, *, include_status: bool = False) -> Dict[str, Any]:
    """Export a redacted, canonical Graph Definition exchange document.

    Published database identifiers, timestamps, actor attribution, and
    signatures are metadata rather than topology.  They are omitted from the
    portable definition so importing a document always creates a new Draft and
    never overwrites an immutable published version.
    """
    version = get_version(version_id, include_topology=True)
    if not version:
        raise ValueError(f"Graph Version {version_id} not found")
    graph = get_graph(str(version.get("graph_id") or "")) or {}
    definition = {
        "schema_version": version.get("schema_version") or GRAPH_SCHEMA_VERSION,
        "graph": {
            "name": graph.get("graph_name") or "Imported Graph",
            "description": graph.get("description"),
            "metadata": graph.get("metadata") or {},
        },
        "version": {
            "label": version.get("version_label") or f"v{version.get('version_no') or 1}",
            "input_schema": version.get("input_schema") or {},
            "output_schema": version.get("output_schema") or {},
            "budget": version.get("budget") or {},
            "nodes": [_public_node(node) for node in version.get("nodes") or []],
            "edges": [_public_edge(edge) for edge in version.get("edges") or []],
        },
    }
    definition["definition_digest"] = digest_json({
        "schema_version": definition["schema_version"],
        **definition["version"],
    })
    document = {
        "format": GRAPH_EXPORT_FORMAT,
        "format_version": GRAPH_EXPORT_VERSION,
        "definition": definition,
        "source": {
            "graph_id": version.get("graph_id"),
            "graph_version_id": version.get("graph_version_id"),
            "plan_id": version.get("plan_id"),
            "status": version.get("status") if include_status else "REDACTED",
            "definition_digest": version.get("definition_digest"),
        },
    }
    document["export_digest"] = digest_json(document)
    return document


def import_version(document: Dict[str, Any], actor_id: str, *, target_graph_id: Optional[str] = None,
                   reason: str = "Imported Graph Definition") -> Dict[str, Any]:
    """Import a canonical document as a new Draft.

    The source status and IDs are intentionally ignored.  This makes import
    safe for published definitions and prevents accidental overwrite when an
    Agent replays an export into another workspace.
    """
    if not isinstance(document, dict):
        raise ValueError("Graph import document must be an object")
    if document.get("format") != GRAPH_EXPORT_FORMAT:
        raise ValueError("unsupported Graph import format")
    if str(document.get("format_version")) != GRAPH_EXPORT_VERSION:
        raise ValueError("unsupported Graph import format version")
    definition = document.get("definition") or {}
    version_data = definition.get("version") or {}
    nodes = version_data.get("nodes") or []
    edges = version_data.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Graph import nodes and edges must be arrays")
    graph_data = definition.get("graph") or {}
    graph_id = target_graph_id
    if graph_id:
        if not get_graph(graph_id):
            raise ValueError(f"target Graph {graph_id} not found")
    else:
        graph_id = create_graph(
            str(graph_data.get("name") or "Imported Graph")[:256], actor_id,
            str(graph_data.get("description") or "")[:2000] or None,
            metadata=graph_data.get("metadata") if isinstance(graph_data.get("metadata"), dict) else {},
        )
    version_id = create_version(
        graph_id, nodes, edges,
        version_label=str(version_data.get("label") or "Imported Draft")[:128],
        actor_id=actor_id, reason=str(reason or "Imported Graph Definition")[:2000],
        input_schema=version_data.get("input_schema") if isinstance(version_data.get("input_schema"), dict) else {},
        output_schema=version_data.get("output_schema") if isinstance(version_data.get("output_schema"), dict) else {},
        budget=version_data.get("budget") if isinstance(version_data.get("budget"), dict) else {},
    )
    imported = get_version(version_id, include_topology=True) or {}
    return {
        "graph_id": graph_id,
        "graph_version_id": version_id,
        "status": "DRAFT",
        "source_definition_digest": (definition.get("definition_digest") or
                                      (document.get("source") or {}).get("definition_digest")),
        "definition": imported,
    }


def transition_version(version_id: str, new_status: str, actor_id: str, reason: str) -> bool:
    version = get_version(version_id, include_topology=False)
    if not version:
        raise ValueError(f"Graph Version {version_id} not found")
    old_status = str(version.get("status") or "").upper()
    new_status = str(new_status or "").upper()
    _assert_status_transition(old_status, new_status)
    if not str(reason or "").strip():
        raise ValueError("lifecycle transition reason is required")
    if new_status == "PUBLISHED" and not version.get("definition_digest"):
        raise ValueError("Graph Version must be compiled and validated before publication")
    return connection.execute(
        "UPDATE GRAPH_VERSIONS SET STATUS = :new_status, ACTOR_ID = :actor_id, REASON = :reason, "
        "UPDATED_AT = CURRENT_TIMESTAMP WHERE GRAPH_VERSION_ID = :version_id AND STATUS = :old_status",
        {"new_status": new_status, "actor_id": actor_id, "reason": reason, "version_id": version_id, "old_status": old_status},
    ) > 0


def set_validation_result(version_id: str, digest: str, diagnostics: Dict[str, Any], risk_level: str) -> bool:
    return connection.execute(
        "UPDATE GRAPH_VERSIONS SET STATUS = 'VALIDATED', DEFINITION_DIGEST = :digest, "
        "VALIDATION_DIAGNOSTICS_JSON = :diagnostics_json, RISK_LEVEL = :risk_level, "
        "UPDATED_AT = CURRENT_TIMESTAMP WHERE GRAPH_VERSION_ID = :version_id AND STATUS = 'DRAFT'",
        {"digest": digest, "diagnostics_json": canonical_json(diagnostics), "risk_level": risk_level, "version_id": version_id},
    ) > 0


def set_compiled_plan(version_id: str, compiler_version: str, definition_digest: str,
                      plan: Dict[str, Any], plan_digest: str, diagnostics: Dict[str, Any],
                      risk_level: str) -> str:
    plan_id = _id("PLAN")
    connection.execute_transaction([
        ("DELETE FROM GRAPH_COMPILE_PLANS WHERE GRAPH_VERSION_ID = :version_id", {"version_id": version_id}),
        ("INSERT INTO GRAPH_COMPILE_PLANS "
         "(PLAN_ID, GRAPH_VERSION_ID, COMPILER_VERSION, DEFINITION_DIGEST, PLAN_JSON, "
         "PLAN_DIGEST, DIAGNOSTICS_JSON, RISK_LEVEL, CREATED_AT) VALUES "
         "(:plan_id, :version_id, :compiler_version, :definition_digest, :plan_json, "
         ":plan_digest, :diagnostics_json, :risk_level, CURRENT_TIMESTAMP)",
         {"plan_id": plan_id, "version_id": version_id, "compiler_version": compiler_version,
          "definition_digest": definition_digest, "plan_json": canonical_json(plan),
          "plan_digest": plan_digest, "diagnostics_json": canonical_json(diagnostics), "risk_level": risk_level}),
    ])
    return plan_id


def get_published_version(graph_id: str, version_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if version_id:
        row = connection.execute_query_one(
            "SELECT GRAPH_VERSION_ID FROM GRAPH_VERSIONS WHERE GRAPH_ID = :graph_id "
            "AND GRAPH_VERSION_ID = :version_id AND STATUS IN ('PUBLISHED', 'DEPRECATED')",
            {"graph_id": graph_id, "version_id": version_id},
        )
    else:
        row = connection.execute_query_one(
            "SELECT GRAPH_VERSION_ID FROM GRAPH_VERSIONS WHERE GRAPH_ID = :graph_id "
            "AND STATUS = 'PUBLISHED' ORDER BY VERSION_NO DESC FETCH FIRST 1 ROWS ONLY",
            {"graph_id": graph_id},
        )
    return get_version(row["graph_version_id"] if row else "") if row else None


def set_alias(graph_id: str, alias_name: str, version_id: str, actor_id: str, reason: str) -> bool:
    if not str(reason or "").strip():
        raise ValueError("alias movement reason is required")
    version = get_version(version_id, include_topology=False)
    if not version or version.get("graph_id") != graph_id or version.get("status") not in {"PUBLISHED", "DEPRECATED"}:
        raise ValueError("alias must point to a published Graph Version")
    statements = [(
        "DELETE FROM GRAPH_ALIASES WHERE GRAPH_ID = :graph_id AND ALIAS_NAME = :alias_name",
        {"graph_id": graph_id, "alias_name": alias_name},
    ), (
        "INSERT INTO GRAPH_ALIASES (GRAPH_ID, ALIAS_NAME, GRAPH_VERSION_ID, ACTOR_ID, REASON, UPDATED_AT) "
        "VALUES (:graph_id, :alias_name, :version_id, :actor_id, :reason, CURRENT_TIMESTAMP)",
        {"graph_id": graph_id, "alias_name": alias_name, "version_id": version_id, "actor_id": actor_id, "reason": reason},
    )]
    connection.execute_transaction(statements)
    return True


def get_alias(graph_id: str, alias_name: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT GRAPH_ID, ALIAS_NAME, GRAPH_VERSION_ID, ACTOR_ID, REASON, UPDATED_AT "
        "FROM GRAPH_ALIASES WHERE GRAPH_ID = :graph_id AND ALIAS_NAME = :alias_name",
        {"graph_id": graph_id, "alias_name": alias_name},
    ))


def list_aliases(graph_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    return _rows(connection.execute_query(
        "SELECT GRAPH_ID, ALIAS_NAME, GRAPH_VERSION_ID, ACTOR_ID, REASON, UPDATED_AT "
        "FROM GRAPH_ALIASES WHERE GRAPH_ID = :graph_id ORDER BY ALIAS_NAME "
        "FETCH FIRST :limit ROWS ONLY",
        {"graph_id": graph_id, "limit": max(1, min(int(limit), 500))},
    ))


def list_types(type_kind: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    conditions = ["STATUS = 'ACTIVE'"]
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if type_kind:
        conditions.append("TYPE_KIND = :type_kind")
        params["type_kind"] = str(type_kind).upper()
    return _rows(connection.execute_query(
        "SELECT TYPE_ID, TYPE_KIND, TYPE_NAME, TYPE_VERSION, MANIFEST_JSON, STATUS, ACTOR_ID, CREATED_AT "
        "FROM GRAPH_TYPE_REGISTRY WHERE " + " AND ".join(conditions) +
        " ORDER BY TYPE_KIND, TYPE_NAME, TYPE_VERSION FETCH FIRST :limit ROWS ONLY", params,
    ))


def register_type(type_kind: str, type_name: str, type_version: str, manifest: Dict[str, Any], actor_id: str = "system") -> str:
    if str(type_kind or "").upper() == "EVALUATOR":
        from .graph_evaluators import validate_manifest
        evaluator_manifest = dict(manifest or {})
        evaluator_manifest.setdefault("name", type_name)
        evaluator_manifest.setdefault("version", type_version)
        errors = validate_manifest(evaluator_manifest)
        if errors:
            raise ValueError(canonical_json(errors))
    type_id = _id("GT")
    connection.execute(
        "INSERT INTO GRAPH_TYPE_REGISTRY "
        "(TYPE_ID, TYPE_KIND, TYPE_NAME, TYPE_VERSION, MANIFEST_JSON, STATUS, ACTOR_ID, CREATED_AT) "
        "VALUES (:type_id, :type_kind, :type_name, :type_version, :manifest_json, 'ACTIVE', :actor_id, CURRENT_TIMESTAMP)",
        {"type_id": type_id, "type_kind": type_kind.upper(), "type_name": type_name,
         "type_version": type_version, "manifest_json": canonical_json(manifest), "actor_id": actor_id},
    )
    return type_id


def get_registered_type(type_kind: str, type_name: str, type_version: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT TYPE_ID, TYPE_KIND, TYPE_NAME, TYPE_VERSION, MANIFEST_JSON, STATUS, ACTOR_ID, CREATED_AT "
        "FROM GRAPH_TYPE_REGISTRY WHERE TYPE_KIND = :type_kind AND TYPE_NAME = :type_name "
        "AND TYPE_VERSION = :type_version AND STATUS = 'ACTIVE'",
        {"type_kind": type_kind.upper(), "type_name": type_name, "type_version": type_version},
    ))


def ensure_builtin_types() -> None:
    builtins = [
        ("NODE", "START", "1.0", {"input_schema": {}, "output_schema": {}}),
        ("NODE", "END", "1.0", {"input_schema": {}, "output_schema": {}}),
        ("NODE", "AGENT", "1.0", {"side_effect_class": "NONE"}),
        ("NODE", "MODEL", "1.0", {"side_effect_class": "NONE"}),
        ("NODE", "LOOP", "1.0", {"side_effect_class": "NONE"}),
        ("NODE", "SKILL", "1.0", {"side_effect_class": "IDEMPOTENT_EXTERNAL"}),
        ("NODE", "TOOL", "1.0", {"side_effect_class": "IDEMPOTENT_EXTERNAL"}),
        ("NODE", "HUMAN", "1.0", {"side_effect_class": "NONE"}),
        ("NODE", "TIMER", "1.0", {"side_effect_class": "NONE"}),
        ("NODE", "SUBGRAPH", "1.0", {"side_effect_class": "NONE"}),
        ("DECISION", "FIXED", "1.0", {}),
        ("DECISION", "EXPRESSION", "1.0", {"ast": True}),
        ("REDUCER", "REPLACE", "1.0", {"deterministic": True}),
        ("REDUCER", "APPEND", "1.0", {"deterministic": True}),
        ("REDUCER", "SET_UNION", "1.0", {"deterministic": True}),
        ("REDUCER", "SUM", "1.0", {"deterministic": True}),
    ]
    from .graph_evaluators import builtin_evaluator_manifests
    builtins.extend(
        ("EVALUATOR", item["name"], item["version"], item)
        for item in builtin_evaluator_manifests()
    )
    for kind, name, version, manifest in builtins:
        if not get_registered_type(kind, name, version):
            register_type(kind, name, version, manifest)
