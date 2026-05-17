"""Oracle Memory System v2.0.0 - Harness Template API

Templates are reusable agent execution blueprints stored as ENTITIES
with ENTITY_TYPE='HARNESS_TEMPLATE'.
"""

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)

_SLOT_RE = re.compile(r"\{(\w+)\}")

BUILTIN_TOOL_SETS: Dict[str, List[Dict[str, str]]] = {
    "memory_tools": [
        {"name": "memory_search", "access": "read"},
        {"name": "memory_create", "access": "write"},
        {"name": "memory_update", "access": "write"},
        {"name": "memory_delete", "access": "write"},
    ],
    "knowledge_tools": [
        {"name": "knowledge_search", "access": "read"},
        {"name": "knowledge_create", "access": "write"},
        {"name": "knowledge_update", "access": "write"},
        {"name": "knowledge_graph_query", "access": "read"},
    ],
    "agent_tools": [
        {"name": "agent_register", "access": "write"},
        {"name": "session_create", "access": "write"},
        {"name": "collaboration_request", "access": "write"},
    ],
    "security_tools": [
        {"name": "data_mask", "access": "read"},
        {"name": "data_unmask", "access": "read"},
    ],
    "task_tools": [
        {"name": "task_plan_create", "access": "write"},
        {"name": "task_step_execute", "access": "write"},
        {"name": "task_status_query", "access": "read"},
    ],
}

BUILTIN_GUARDRAIL_PRESETS: Dict[str, Dict[str, Any]] = {
    "conservative": {
        "max_iterations": 5,
        "max_execution_time": 60,
        "context_window_strategy": "sliding",
        "content_moderation": True,
        "pii_filtering": True,
        "max_retry_limit": 1,
    },
    "balanced": {
        "max_iterations": 15,
        "max_execution_time": 300,
        "context_window_strategy": "summarize",
        "content_moderation": True,
        "pii_filtering": True,
        "max_retry_limit": 3,
    },
    "aggressive": {
        "max_iterations": 50,
        "max_execution_time": 900,
        "context_window_strategy": "truncate",
        "content_moderation": False,
        "pii_filtering": False,
        "max_retry_limit": 5,
    },
}


def create_template(
    name: str,
    description: Optional[str] = None,
    prompt_templates: Optional[Dict[str, str]] = None,
    tool_bindings: Optional[List[Dict[str, str]]] = None,
    tool_sets: Optional[List[str]] = None,
    memory_access: Optional[Dict[str, Any]] = None,
    guardrails: Optional[Dict[str, Any]] = None,
    guardrail_preset: Optional[str] = None,
    evaluation: Optional[Dict[str, Any]] = None,
    variables: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
    parent_template_id: Optional[int] = None,
) -> int:
    merged_bindings = list(tool_bindings or [])
    if tool_sets:
        for ts in tool_sets:
            if ts in BUILTIN_TOOL_SETS:
                merged_bindings.extend(BUILTIN_TOOL_SETS[ts])

    if guardrail_preset and not guardrails:
        guardrails = copy.deepcopy(BUILTIN_GUARDRAIL_PRESETS.get(guardrail_preset, BUILTIN_GUARDRAIL_PRESETS["balanced"]))

    if not memory_access:
        memory_access = {"short_term": True, "long_term": True, "compaction": True, "access_policy": "read_write"}

    if not guardrails:
        guardrails = copy.deepcopy(BUILTIN_GUARDRAIL_PRESETS["balanced"])

    props = _sanitize_decimals({
        "prompt_templates": prompt_templates or {},
        "tool_bindings": merged_bindings,
        "memory_access": memory_access,
        "guardrails": guardrails,
        "evaluation": evaluation or {},
        "variables": variables or {},
    })

    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY,
                              PRIORITY, STATUS, TAGS, METADATA,
                              OWNED_BY_AGENT, VISIBILITY)
        VALUES ('HARNESS_TEMPLATE', :name, :description, :category,
                1, 'ACTIVE', :tags, :metadata,
                :owned_by_agent, :visibility)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_params = {
        "name": name[:500],
        "description": description,
        "category": category,
        "tags": json.dumps(tags or []),
        "metadata": json.dumps(metadata or props),
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
    }
    entity_id = execute_insert_returning_id(entity_sql, entity_params)

    meta_sql = """
        INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS,
                                  VARIABLES, CHANGELOG)
        VALUES (:eid, 1, 'DRAFT', :variables, :changelog)
    """
    execute(meta_sql, {
        "eid": entity_id,
        "variables": json.dumps(variables or {}),
        "changelog": json.dumps([{"action": "created", "timestamp": None}]),
    })

    if parent_template_id:
        edge_sql = """
            INSERT INTO ENTITY_EDGES (SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, PROPERTIES)
            VALUES (:source_id, :target_id, 'DERIVES_FROM', 1.0, 1.0, :properties)
            RETURNING EDGE_ID INTO :ret_id
        """
        execute_insert_returning_id(edge_sql, {
            "source_id": entity_id,
            "target_id": parent_template_id,
            "properties": json.dumps({}),
        })

    return entity_id


def get_template(entity_id: int) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.NAME, e.DESCRIPTION, e.CONTENT, e.CATEGORY,
               e.TAGS, e.METADATA, e.OWNED_BY_AGENT, e.VISIBILITY,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               hm.TEMPLATE_VERSION, hm.TEMPLATE_STATUS,
               hm.VARIABLES, hm.CHANGELOG
        FROM ENTITIES e
        LEFT JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
    """
    row = execute_query_one(sql, {"id": entity_id})
    if row is None:
        return None
    return _decorate_template(row)


def list_templates(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'HARNESS_TEMPLATE'"]
    params: Dict[str, Any] = {"lim": limit}

    if category:
        conditions.append("e.CATEGORY = :cat")
        params["cat"] = category
    if status:
        conditions.append("hm.TEMPLATE_STATUS = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.NAME, e.DESCRIPTION, e.CATEGORY,
               e.TAGS, e.METADATA, e.OWNED_BY_AGENT, e.VISIBILITY,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               hm.TEMPLATE_VERSION, hm.TEMPLATE_STATUS,
               hm.VARIABLES, hm.CHANGELOG
        FROM ENTITIES e
        LEFT JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return [_decorate_template(r) for r in execute_query(sql, params)]


def update_template(entity_id: int, **kwargs) -> bool:
    entity_fields = {"name", "description", "category", "tags", "metadata", "visibility", "status"}
    meta_fields = {"template_status", "changelog"}

    entity_updates = {}
    meta_updates = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields:
            if lk in ("tags", "metadata") and isinstance(v, (list, dict)):
                v = json.dumps(v)
            entity_updates[lk] = v
        elif lk in meta_fields:
            if lk == "changelog" and isinstance(v, (list, dict)):
                v = json.dumps(v)
            meta_updates[lk] = v

    affected = 0
    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = SYSTIMESTAMP")
        entity_updates["id"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'HARNESS_TEMPLATE'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE HARNESS_META SET {set_clause} WHERE ENTITY_ID = :eid"
        affected += execute(sql, meta_updates)

    return affected > 0


def delete_template(entity_id: int) -> bool:
    execute("DELETE FROM HARNESS_META WHERE ENTITY_ID = :eid", {"eid": entity_id})
    execute("DELETE FROM ENTITY_EDGES WHERE SOURCE_ID = :id OR TARGET_ID = :id", {"id": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'HARNESS_TEMPLATE'"
    return execute(sql, {"id": entity_id}) > 0


def get_template_lineage(entity_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT eg.EDGE_ID, eg.SOURCE_ID, eg.TARGET_ID, eg.EDGE_TYPE, eg.STRENGTH,
               e.NAME, e.CATEGORY,
               hm.TEMPLATE_VERSION, hm.TEMPLATE_STATUS,
               TO_CHAR(eg.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITY_EDGES eg
        JOIN ENTITIES e ON e.ENTITY_ID = eg.TARGET_ID
        LEFT JOIN HARNESS_META hm ON hm.ENTITY_ID = eg.TARGET_ID
        WHERE eg.SOURCE_ID = :id AND eg.EDGE_TYPE = 'DERIVES_FROM'
        ORDER BY eg.CREATED_AT DESC
    """
    return execute_query(sql, {"id": entity_id})


def resolve_template(entity_id: int) -> Optional[Dict[str, Any]]:
    tpl = get_template(entity_id)
    if tpl is None:
        return None

    incoming = _get_incoming_edges(entity_id)
    parent_edge = None
    for edge in incoming:
        if edge.get("edge_type") == "DERIVES_FROM":
            parent_edge = edge
            break

    if parent_edge is None:
        return tpl

    parent = resolve_template(parent_edge["source_id"])
    if parent is None:
        return tpl

    parent_props = _extract_harness_props(parent)
    child_props = _extract_harness_props(tpl)
    merged_props = _deep_merge(parent_props, child_props)

    for k, v in merged_props.items():
        tpl[k] = v

    return tpl


def instantiate_template(
    template_id: int,
    variables: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    tpl = resolve_template(template_id)
    if tpl is None:
        return None

    merged_vars = dict(tpl.get("variables", {}))
    if variables:
        merged_vars.update(variables)

    prompt_templates = dict(tpl.get("prompt_templates", {}))
    for key, prompt in prompt_templates.items():
        if isinstance(prompt, str):
            prompt_templates[key] = _SLOT_RE.sub(
                lambda m: str(merged_vars.get(m.group(1), m.group(0))), prompt
            )
    tpl["prompt_templates"] = prompt_templates

    if overrides:
        tpl = _deep_merge(tpl, overrides)

    tpl["instance_meta"] = {
        "source_template_id": template_id,
        "agent_id": agent_id,
    }

    for field in ("variables", "entity_id", "template_version", "template_status", "changelog"):
        tpl.pop(field, None)

    return tpl


def derive_template(
    parent_id: int,
    name: str,
    description: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
    category: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
) -> Optional[int]:
    parent = get_template(parent_id)
    if parent is None:
        return None

    parent_props = _extract_harness_props(parent)
    if overrides:
        merged_props = _deep_merge(parent_props, overrides)
    else:
        merged_props = copy.deepcopy(parent_props)

    return create_template(
        name=name,
        description=description or parent.get("description"),
        prompt_templates=merged_props.get("prompt_templates"),
        tool_bindings=merged_props.get("tool_bindings"),
        tool_sets=None,
        memory_access=merged_props.get("memory_access"),
        guardrails=merged_props.get("guardrails"),
        guardrail_preset=None,
        evaluation=merged_props.get("evaluation"),
        variables=merged_props.get("variables"),
        category=category or parent.get("category"),
        tags=parent.get("tags"),
        metadata=_sanitize_decimals(parent.get("metadata")) if parent.get("metadata") else None,
        owned_by_agent=owned_by_agent or parent.get("owned_by_agent"),
        visibility=visibility,
        parent_template_id=parent_id,
    )


def validate_template(entity_id: int) -> Dict[str, Any]:
    tpl = get_template(entity_id)
    if tpl is None:
        return {"valid": False, "errors": ["Template not found"], "warnings": [], "template_id": entity_id, "template_name": None}

    errors = []
    warnings = []

    prompt_templates = tpl.get("prompt_templates", {})
    if not prompt_templates:
        errors.append("prompt_templates is empty")
    elif "system" not in prompt_templates:
        errors.append("prompt_templates missing required 'system' key")

    declared_vars = set(tpl.get("variables", {}).keys())
    found_vars = set()
    for prompt in prompt_templates.values():
        if isinstance(prompt, str):
            found_vars.update(_SLOT_RE.findall(prompt))

    undefined = found_vars - declared_vars
    if undefined:
        errors.append(f"Undefined variables in prompts: {sorted(undefined)}")

    tool_bindings = tpl.get("tool_bindings", [])
    tool_names = [t.get("name") for t in tool_bindings if isinstance(t, dict)]
    if len(tool_names) != len(set(tool_names)):
        errors.append("Duplicate tool bindings detected")

    guardrails = tpl.get("guardrails", {})
    max_iterations = guardrails.get("max_iterations", 0)
    if not isinstance(max_iterations, (int, float)) or max_iterations <= 0:
        errors.append("guardrails.max_iterations must be > 0")

    memory_access = tpl.get("memory_access", {})
    if not any(memory_access.get(k) for k in ("short_term", "long_term", "compaction")):
        warnings.append("No memory type enabled in memory_access")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "template_id": entity_id,
        "template_name": tpl.get("name"),
    }


def publish_template(entity_id: int) -> bool:
    return update_template(entity_id, template_status="PUBLISHED")


def deprecate_template(entity_id: int, reason: Optional[str] = None) -> bool:
    tpl = get_template(entity_id)
    if tpl is None:
        return False

    changelog = list(tpl.get("changelog", []))
    changelog.append({"action": "deprecated", "reason": reason})

    return update_template(entity_id, template_status="DEPRECATED", changelog=changelog)


def _extract_harness_props(tpl: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    for key in ("prompt_templates", "tool_bindings", "memory_access", "guardrails", "evaluation", "variables"):
        if key in tpl:
            result[key] = _sanitize_decimals(copy.deepcopy(tpl[key]))
    return result


def _get_incoming_edges(entity_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT EDGE_ID, SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, PROPERTIES,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITY_EDGES
        WHERE TARGET_ID = :id
        ORDER BY CREATED_AT DESC
    """
    rows = execute_query(sql, {"id": entity_id})
    for r in rows:
        if isinstance(r.get("properties"), str):
            try:
                r["properties"] = json.loads(r["properties"])
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _sanitize_decimals(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_decimals(v) for v in obj]
    try:
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
    except ImportError:
        pass
    return obj


def _decorate_template(row: Dict[str, Any]) -> Dict[str, Any]:
    for json_col in ("tags", "metadata", "variables", "changelog"):
        val = row.get(json_col)
        if isinstance(val, str):
            try:
                row[json_col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[json_col] = val

    if "template_version" in row:
        try:
            from decimal import Decimal
            if isinstance(row["template_version"], Decimal):
                row["template_version"] = int(row["template_version"])
        except ImportError:
            pass

    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        for key in ("prompt_templates", "tool_bindings", "memory_access", "guardrails", "evaluation", "variables"):
            if key in metadata:
                row[key] = _sanitize_decimals(metadata[key])

    return row
