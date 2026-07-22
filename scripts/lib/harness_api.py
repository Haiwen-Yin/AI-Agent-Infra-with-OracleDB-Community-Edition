"""AI Agent Infra v4.0.1 - Enterprise Edition - Harness API

Templates are reusable agent execution blueprints stored as ENTITIES
with ENTITY_TYPE='HARNESS_TEMPLATE' and extended via HARNESS_META.
"""

import json
import re
from typing import Any, Dict, List, Optional, Set

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

_SLOT_RE = re.compile(r"\{(\w+)\}")


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for json_col in ("input_schema", "output_schema"):
        val = result.get(json_col)
        if isinstance(val, str):
            try:
                result[json_col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def create_harness_template(
    title: str,
    summary: Optional[str] = None,
    content: Optional[str] = None,
    category: Optional[str] = None,
    input_schema: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    execution_mode: str = "SEQUENTIAL",
    importance: int = 5,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
) -> str:
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              STATUS, IMPORTANCE, OWNED_BY_AGENT, SOURCE_AGENT,
                              VISIBILITY, RETRIEVAL_COUNT)
        VALUES (AI_NEW_ID(), 'HARNESS_TEMPLATE', :title, :content, :summary, :category,
                'ACTIVE', :importance, :owned_by_agent, :source_agent,
                :visibility, 0)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_params = {
        "title": title,
        "content": content,
        "summary": summary,
        "category": category,
        "importance": importance,
        "owned_by_agent": owned_by_agent,
        "source_agent": owned_by_agent,
        "visibility": visibility,
    }
    entity_id = execute_insert_returning_id(entity_sql, entity_params)

    meta_sql = """
        INSERT INTO HARNESS_META (ENTITY_ID, ENTITY_TYPE, TEMPLATE_VERSION,
                                  INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE)
        VALUES (:eid, 'HARNESS_TEMPLATE', 1, :input_schema, :output_schema, :execution_mode)
    """
    execute(meta_sql, {
        "eid": entity_id,
        "input_schema": json.dumps(input_schema) if input_schema else None,
        "output_schema": json.dumps(output_schema) if output_schema else None,
        "execution_mode": execution_mode,
    })

    return entity_id


def get_harness_template(entity_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY,
               e.CATEGORY, e.STATUS, e.IMPORTANCE, e.OWNED_BY_AGENT,
               e.SOURCE_AGENT, e.VISIBILITY, e.RETRIEVAL_COUNT,
               TO_CHAR(e.EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               hm.TEMPLATE_VERSION, hm.INPUT_SCHEMA, hm.OUTPUT_SCHEMA,
               hm.EXECUTION_MODE, hm.PARENT_TEMPLATE_ID
        FROM ENTITIES e
        JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
                             AND hm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
    """
    try:
        row = execute_query_one(sql, {"id": entity_id})
    except Exception:
        # PARENT_TEMPLATE_ID column missing on older deployments — use legacy SQL.
        legacy_sql = """
            SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY,
                   e.CATEGORY, e.STATUS, e.IMPORTANCE, e.OWNED_BY_AGENT,
                   e.SOURCE_AGENT, e.VISIBILITY, e.RETRIEVAL_COUNT,
                   TO_CHAR(e.EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT,
                   TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   hm.TEMPLATE_VERSION, hm.INPUT_SCHEMA, hm.OUTPUT_SCHEMA,
                   hm.EXECUTION_MODE
            FROM ENTITIES e
            JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
                                 AND hm.ENTITY_TYPE = e.ENTITY_TYPE
            WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
        """
        try:
            row = execute_query_one(legacy_sql, {"id": entity_id})
        except Exception:
            return None
    if row is None:
        return None
    return _row_to_dict(row)


def update_harness_template(entity_id: str, **kwargs) -> bool:
    entity_fields = {"title", "content", "summary", "category", "status",
                     "importance", "owned_by_agent", "source_agent",
                     "visibility", "retrieval_count", "expires_at"}
    meta_fields = {"template_version", "input_schema", "output_schema", "execution_mode"}

    entity_updates: Dict[str, Any] = {}
    meta_updates: Dict[str, Any] = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields:
            entity_updates[lk] = v
        elif lk in meta_fields:
            if lk in ("input_schema", "output_schema") and isinstance(v, dict):
                v = json.dumps(v)
            meta_updates[lk] = v

    affected = 0
    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
        entity_updates["id"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'HARNESS_TEMPLATE'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE HARNESS_META SET {set_clause} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'HARNESS_TEMPLATE'"
        affected += execute(sql, meta_updates)

    return affected > 0


def delete_harness_template(entity_id: str) -> bool:
    execute("DELETE FROM HARNESS_META WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'HARNESS_TEMPLATE'", {"eid": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'HARNESS_TEMPLATE'"
    return execute(sql, {"id": entity_id}) > 0


def list_harness_templates(
    category: Optional[str] = None,
    execution_mode: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'HARNESS_TEMPLATE'"]
    params: Dict[str, Any] = {"lim": limit, "off": offset}

    if category:
        conditions.append("e.CATEGORY = :cat")
        params["cat"] = category
    if execution_mode:
        conditions.append("hm.EXECUTION_MODE = :emode")
        params["emode"] = execution_mode

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.SUMMARY, e.CATEGORY,
               e.STATUS, e.IMPORTANCE, e.OWNED_BY_AGENT, e.VISIBILITY,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               hm.TEMPLATE_VERSION, hm.EXECUTION_MODE
        FROM ENTITIES e
        JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
                             AND hm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, params)]


def get_template_with_variables(entity_id: str) -> Optional[Dict[str, Any]]:
    tpl = get_harness_template(entity_id)
    if tpl is None:
        return None

    input_schema = tpl.get("input_schema")
    variables: List[Dict[str, Any]] = []
    if isinstance(input_schema, dict):
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        for var_name, var_def in properties.items():
            entry = {"name": var_name}
            if isinstance(var_def, dict):
                entry["type"] = var_def.get("type", "string")
                entry["description"] = var_def.get("description", "")
                if "default" in var_def:
                    entry["default"] = var_def["default"]
            entry["required"] = var_name in required
            variables.append(entry)

    tpl["variables"] = variables
    return tpl


def instantiate_harness_template(
    entity_id: str,
    variable_values: Dict[str, str],
    agent_id: str,
) -> str:
    tpl = get_harness_template(entity_id)
    if tpl is None:
        raise ValueError(f"Harness template {entity_id} not found")

    content = tpl.get("content") or ""
    instantiated_content = _SLOT_RE.sub(
        lambda m: str(variable_values.get(m.group(1), m.group(0))), content
    )

    title = f"Instance of {tpl.get('title', entity_id)}"

    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              STATUS, IMPORTANCE, OWNED_BY_AGENT, SOURCE_AGENT,
                              VISIBILITY, RETRIEVAL_COUNT)
        VALUES (AI_NEW_ID(), 'TASK_OUTPUT', :title, :content, :summary, :category,
                'ACTIVE', :importance, :owned_by_agent, :source_agent,
                :visibility, 0)
        RETURNING ENTITY_ID INTO :ret_id
    """
    instance_id = execute_insert_returning_id(entity_sql, {
        "title": title,
        "content": instantiated_content,
        "summary": tpl.get("summary"),
        "category": tpl.get("category"),
        "importance": tpl.get("importance", 5),
        "owned_by_agent": agent_id,
        "source_agent": agent_id,
        "visibility": tpl.get("visibility", "SHARED"),
    })

    edge_sql = """
        INSERT INTO ENTITY_EDGES (EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE)
        VALUES ('E_' || AI_NEW_ID(), :source_id, 'TASK_OUTPUT', :target_id, 'USES_HARNESS', 1.0, 1.0)
        RETURNING EDGE_ID INTO :ret_id
    """
    execute_insert_returning_id(edge_sql, {
        "source_id": str(instance_id),
        "target_id": str(entity_id),
    })

    return instance_id


def count_harness_templates(category: Optional[str] = None) -> int:
    conditions = ["e.ENTITY_TYPE = 'HARNESS_TEMPLATE'"]
    params: Dict[str, Any] = {}

    if category:
        conditions.append("e.CATEGORY = :cat")
        params["cat"] = category

    where = " AND ".join(conditions)
    sql = f"""
        SELECT COUNT(*) AS CNT
        FROM ENTITIES e
        JOIN HARNESS_META hm ON hm.ENTITY_ID = e.ENTITY_ID
                             AND hm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE {where}
    """
    row = execute_query_one(sql, params)
    if row is None:
        return 0
    return int(row.get("cnt", 0))

def instantiate_harness_in_branch(entity_id: str, variable_values: Dict[str, str],
                                   agent_id: str, branch_id: str) -> str:
    """Instantiate a harness template within a branch context. Returns instance ENTITY_ID."""
    instance_id = instantiate_harness_template(entity_id, variable_values, agent_id)
    if instance_id and branch_id:
        from . import workspace_api
        branch = None
        from . import branch_api
        branch = branch_api.get_branch(branch_id)
        if branch:
            workspace_api.save_context(
                workspace_id=branch.get("workspace_id"),
                agent_id=agent_id,
                context_type="CHECKPOINT",
                context_data={"harness_instance_id": instance_id, "template_id": entity_id},
                branch_id=branch_id,
            )
    return instance_id

def share_harness_to_group(entity_id: str, group_id: str) -> Dict[str, Any]:
    """Share a harness template to a collaboration group workspace."""
    from . import collab_api
    group = collab_api.get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group {group_id} not found")
    tpl = get_harness_template(entity_id)
    if tpl is None:
        raise ValueError(f"Harness template {entity_id} not found")
    from . import workspace_api
    workspace_api.save_context(
        workspace_id=group["workspace_id"],
        agent_id=group.get("coordinator_agent_id", "SYSTEM"),
        context_type="AUTO_SAVE",
        context_data={
            "shared_harness": entity_id,
            "template_title": tpl.get("title"),
            "execution_mode": tpl.get("execution_mode"),
        },
    )
    return {"entity_id": entity_id, "group_id": group_id, "shared": True}


def instantiate_harness_for_member(entity_id: str, member_agent_id: str,
                                   variable_values: Dict[str, str],
                                   group_id: str) -> str:
    """Instantiate a harness for a specific group member in their branch."""
    from . import collab_api
    members = collab_api.get_member_branches(group_id)
    branch_id = None
    for m in members:
        if m["agent_id"] == member_agent_id:
            branch_id = m.get("branch_id")
            break
    if not branch_id:
        instance_id = instantiate_harness_template(entity_id, variable_values, member_agent_id)
    else:
        instance_id = instantiate_harness_in_branch(entity_id, variable_values, member_agent_id, branch_id)
    return instance_id


# ---------------------------------------------------------------------------
# D3: Harness Template Inheritance
# ---------------------------------------------------------------------------

def _ensure_parent_template_column() -> None:
    """PARENT_TEMPLATE_ID is installed by the versioned database migration."""


def create_derived_template(
    name: str,
    parent_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
    category: Optional[str] = None,
    importance: Optional[int] = None,
    owned_by_agent: Optional[str] = None,
    visibility: Optional[str] = None,
) -> Optional[str]:
    """Create a new harness template derived from a parent template.

    Merges parent fields with override values (overrides take precedence),
    then creates a new template row with PARENT_TEMPLATE_ID set.
    """
    overrides = overrides or {}

    parent = get_harness_template(parent_id)
    if parent is None:
        raise ValueError(f"Parent harness template {parent_id} not found")

    # Ensure PARENT_TEMPLATE_ID column exists before writing to it.
    _ensure_parent_template_column()

    # --- Merge parent fields with overrides ---
    merged_title = overrides.get("title", name)
    merged_summary = overrides.get("summary", summary or parent.get("summary"))
    merged_content = overrides.get("content", parent.get("content"))
    merged_category = overrides.get("category", category or parent.get("category"))
    merged_importance = overrides.get("importance", importance or parent.get("importance", 5))
    merged_visibility = overrides.get("visibility", visibility or parent.get("visibility", "SHARED"))
    merged_execution_mode = overrides.get("execution_mode", parent.get("execution_mode", "SEQUENTIAL"))
    merged_owned_by = overrides.get("owned_by_agent", owned_by_agent or parent.get("owned_by_agent"))

    # Deep-merge JSON schemas (override keys win over parent keys)
    parent_input = parent.get("input_schema") or {}
    override_input = overrides.get("input_schema") or {}
    merged_input = {**parent_input, **override_input} if (parent_input or override_input) else None

    parent_output = parent.get("output_schema") or {}
    override_output = overrides.get("output_schema") or {}
    merged_output = {**parent_output, **override_output} if (parent_output or override_output) else None

    # --- Create new entity + meta with PARENT_TEMPLATE_ID set ---
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              STATUS, IMPORTANCE, OWNED_BY_AGENT, SOURCE_AGENT,
                              VISIBILITY, RETRIEVAL_COUNT)
        VALUES (AI_NEW_ID(), 'HARNESS_TEMPLATE', :title, :content, :summary, :category,
                'ACTIVE', :importance, :owned_by_agent, :source_agent,
                :visibility, 0)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_id = execute_insert_returning_id(entity_sql, {
        "title": merged_title,
        "content": merged_content,
        "summary": merged_summary,
        "category": merged_category,
        "importance": merged_importance,
        "owned_by_agent": merged_owned_by,
        "source_agent": merged_owned_by,
        "visibility": merged_visibility,
    })

    meta_sql = """
        INSERT INTO HARNESS_META (ENTITY_ID, ENTITY_TYPE, TEMPLATE_VERSION,
                                  INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE,
                                  PARENT_TEMPLATE_ID)
        VALUES (:eid, 'HARNESS_TEMPLATE', 1, :input_schema, :output_schema,
                :execution_mode, :parent_id)
    """
    try:
        execute(meta_sql, {
            "eid": entity_id,
            "input_schema": json.dumps(merged_input) if merged_input else None,
            "output_schema": json.dumps(merged_output) if merged_output else None,
            "execution_mode": merged_execution_mode,
            "parent_id": parent_id,
        })
    except Exception:
        # Fallback: PARENT_TEMPLATE_ID column missing — insert without it.
        meta_sql_fb = """
            INSERT INTO HARNESS_META (ENTITY_ID, ENTITY_TYPE, TEMPLATE_VERSION,
                                      INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE)
            VALUES (:eid, 'HARNESS_TEMPLATE', 1, :input_schema, :output_schema,
                    :execution_mode)
        """
        execute(meta_sql_fb, {
            "eid": entity_id,
            "input_schema": json.dumps(merged_input) if merged_input else None,
            "output_schema": json.dumps(merged_output) if merged_output else None,
            "execution_mode": merged_execution_mode,
        })

    return entity_id


def get_template_inheritance_chain(entity_id: str) -> List[Dict[str, Any]]:
    """Walk PARENT_TEMPLATE_ID links from a template up to its root.

    Returns a list ordered from the given template to the root ancestor.
    Cycle-safe: stops if a cycle or missing parent is detected.
    """
    chain: List[Dict[str, Any]] = []
    visited: Set[str] = set()
    current_id: Optional[str] = entity_id

    while current_id and current_id not in visited:
        visited.add(current_id)
        tpl = get_harness_template(current_id)
        if tpl is None:
            break
        chain.append(tpl)
        current_id = tpl.get("parent_template_id")

    return chain


def resolve_template(entity_id: str) -> Optional[Dict[str, Any]]:
    """Walk up the inheritance chain and return merged effective fields.

    Parent values form the base; descendants override them. JSON schemas
    (input_schema / output_schema) are deep-merged by top-level keys.
    """
    chain = get_template_inheritance_chain(entity_id)
    if not chain:
        return None

    # Chain is ordered [descendant ... root]; merge from root → descendant
    # so descendant overrides win.
    merged: Dict[str, Any] = {}
    for tpl in reversed(chain):
        for field in ("title", "summary", "content", "category", "status",
                      "importance", "owned_by_agent", "source_agent",
                      "visibility", "execution_mode"):
            val = tpl.get(field)
            if val is not None:
                merged[field] = val
        for schema_field in ("input_schema", "output_schema"):
            schema_val = tpl.get(schema_field)
            if isinstance(schema_val, dict):
                merged.setdefault(schema_field, {})
                merged[schema_field] = {**merged[schema_field], **schema_val}
            elif schema_val is not None:
                merged[schema_field] = schema_val

    merged["entity_id"] = entity_id
    merged["inheritance_chain"] = [t.get("entity_id") for t in chain]
    return merged
