"""AI Agent Infra v4.0.1 - Skill Storage & Distribution API

Supports direct database access and Admin API mode for Business Agents.
"""

import json
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)
from .skill_storage import save_resource, delete_resource, get_resource_info, resource_exists

_JSON_COLUMNS = {"parameters", "dependencies"}
_ALLOWED_UPDATE_FIELDS = {
    "skill_name", "skill_version", "text_content", "resource_uri",
    "resource_filename", "resource_size", "resource_mime_type",
    "resource_checksum", "skill_description", "parameters", "dependencies", "skill_status",
}


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = sanitize_row(row)
    for col in _JSON_COLUMNS:
        val = result.get(col)
        if isinstance(val, str):
            try:
                result[col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def register_skill(
    title: str,
    skill_name: str,
    skill_version: str = "1.0.0",
    skill_type: str = "CUSTOM",
    skill_format: str = "TEXT",
    text_content: Optional[str] = None,
    resource_uri: Optional[str] = None,
    resource_checksum: Optional[str] = None,
    skill_description: Optional[str] = None,
    runtime: str = "PYTHON",
    parameters: Optional[Any] = None,
    dependencies: Optional[Any] = None,
    category: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
    workspace_id: Optional[str] = None,
) -> str:
    existing = execute_query_one(
        """SELECT sm.ENTITY_ID, sm.RESOURCE_CHECKSUM
             FROM SKILL_META sm
            WHERE sm.SKILL_NAME = :skill_name AND sm.SKILL_VERSION = :skill_version""",
        {"skill_name": skill_name, "skill_version": skill_version},
    )
    if existing:
        existing_checksum = existing.get("resource_checksum")
        if resource_checksum and existing_checksum == resource_checksum:
            return existing["entity_id"]
        raise ValueError(f"Immutable Skill version conflict: {skill_name}@{skill_version}")

    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                              OWNED_BY_AGENT, VISIBILITY, WORKSPACE_ID)
        VALUES ('ENT_' || AI_NEW_ID(), 'SKILL', :title, :category, 'ACTIVE',
                :owned_by_agent, :visibility, :workspace_id)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_id = execute_insert_returning_id(entity_sql, {
        "title": title,
        "category": category,
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
        "workspace_id": workspace_id,
    })

    params_val = json.dumps(parameters) if parameters and not isinstance(parameters, str) else parameters
    deps_val = json.dumps(dependencies) if dependencies and not isinstance(dependencies, str) else dependencies

    meta_sql = """
        INSERT INTO SKILL_META (ENTITY_ID, SKILL_NAME, SKILL_VERSION, SKILL_TYPE,
                                SKILL_FORMAT, TEXT_CONTENT, RESOURCE_URI,
                                RESOURCE_CHECKSUM, SKILL_DESCRIPTION, RUNTIME, PARAMETERS,
                                DEPENDENCIES, SKILL_STATUS)
        VALUES (:eid, :skill_name, :skill_version, :skill_type, :skill_format,
                :text_content, :resource_uri, :resource_checksum, :skill_description, :runtime,
                :parameters, :dependencies, 'ACTIVE')
    """
    execute(meta_sql, {
        "eid": entity_id,
        "skill_name": skill_name,
        "skill_version": skill_version,
        "skill_type": skill_type,
        "skill_format": skill_format,
        "text_content": text_content,
        "resource_uri": resource_uri,
        "resource_checksum": resource_checksum,
        "skill_description": skill_description,
        "runtime": runtime,
        "parameters": params_val,
        "dependencies": deps_val,
    })

    return entity_id


def get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.TITLE, e.CATEGORY, e.STATUS, e.VISIBILITY,
               e.WORKSPACE_ID,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               sm.SKILL_NAME, sm.SKILL_VERSION, sm.SKILL_TYPE, sm.SKILL_FORMAT,
               sm.TEXT_CONTENT, sm.RESOURCE_URI, sm.RESOURCE_FILENAME,
               sm.RESOURCE_SIZE, sm.RESOURCE_MIME_TYPE, sm.RESOURCE_CHECKSUM,
               sm.RESOURCE_SERVER_HOST,
               sm.SKILL_DESCRIPTION,
               sm.RUNTIME, sm.PARAMETERS, sm.DEPENDENCIES, sm.SKILL_STATUS
        FROM ENTITIES e
        JOIN SKILL_META sm ON sm.ENTITY_ID = e.ENTITY_ID
        WHERE e.ENTITY_ID = :eid AND e.ENTITY_TYPE = 'SKILL'
    """
    row = execute_query_one(sql, {"eid": skill_id})
    if row is None:
        return None
    return _row_to_dict(row)


def list_skills(
    skill_type: Optional[str] = None,
    runtime: Optional[str] = None,
    skill_status: str = "ACTIVE",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'SKILL'"]
    params: Dict[str, Any] = {"lim": limit, "off": 0}

    if skill_type:
        conditions.append("sm.SKILL_TYPE = :skill_type")
        params["skill_type"] = skill_type
    if runtime:
        conditions.append("sm.RUNTIME = :runtime")
        params["runtime"] = runtime
    if skill_status:
        conditions.append("(sm.SKILL_STATUS = :skill_status)")
        params["skill_status"] = skill_status

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.TITLE, e.CATEGORY, e.STATUS, e.VISIBILITY,
               e.WORKSPACE_ID,
               sm.SKILL_NAME, sm.SKILL_VERSION, sm.SKILL_TYPE, sm.SKILL_FORMAT,
               sm.RUNTIME, sm.SKILL_STATUS,
               sm.RESOURCE_FILENAME, sm.RESOURCE_SIZE, sm.RESOURCE_MIME_TYPE,
               sm.RESOURCE_URI, sm.RESOURCE_SERVER_HOST
        FROM ENTITIES e
        JOIN SKILL_META sm ON sm.ENTITY_ID = e.ENTITY_ID
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    try:
        rows = execute_query(sql, params)
        return [sanitize_row(r) for r in rows]
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"list_skills Oracle-schema query failed: {e}")
    sql_pg = f"""
        SELECT sm.SKILL_ID AS ENTITY_ID, sm.SKILL_NAME AS TITLE, sm.CATEGORY, sm.STATUS,
               sm.VISIBILITY, CAST(NULL AS VARCHAR) AS WORKSPACE_ID,
               sm.SKILL_NAME, sm.SKILL_VERSION, sm.SKILL_TYPE,
               CAST(NULL AS VARCHAR) AS SKILL_FORMAT,
               CAST(NULL AS VARCHAR) AS RUNTIME, sm.STATUS AS SKILL_STATUS,
               CAST(NULL AS VARCHAR) AS RESOURCE_FILENAME,
               CAST(NULL AS INTEGER) AS RESOURCE_SIZE,
               CAST(NULL AS VARCHAR) AS RESOURCE_MIME_TYPE,
               sm.RESOURCE_PATH AS RESOURCE_URI,
               CAST(NULL AS VARCHAR) AS RESOURCE_SERVER_HOST
        FROM SKILL_META sm
        WHERE sm.STATUS = :skill_status
        ORDER BY sm.CREATED_AT DESC
        LIMIT :lim OFFSET :off
    """
    try:
        return [sanitize_row(r) for r in execute_query(sql_pg, params)]
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"list_skills PG fallback failed: {e}")
        return []


def update_skill(skill_id: str, **kwargs: Any) -> bool:
    title = kwargs.get("title")
    if title:
        execute(
            "UPDATE ENTITIES SET TITLE = :vtitle, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :veid AND ENTITY_TYPE = 'SKILL'",
            {"vtitle": title, "veid": skill_id},
        )

    updates: Dict[str, Any] = {}
    for k, v in kwargs.items():
        lk = k.lower()
        if lk == "title":
            continue
        if lk in _ALLOWED_UPDATE_FIELDS and v is not None:
            if lk in _JSON_COLUMNS and not isinstance(v, str):
                updates[lk] = json.dumps(v)
            else:
                updates[lk] = v

    if not updates:
        return bool(title)

    set_parts = [f"{k.upper()} = :{k}" for k in updates]
    updates["eid"] = skill_id
    sql = f"UPDATE SKILL_META SET {', '.join(set_parts)} WHERE ENTITY_ID = :eid"
    affected = execute(sql, updates)

    execute(
        "UPDATE ENTITIES SET UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SKILL'",
        {"eid": skill_id},
    )

    return affected > 0


def delete_skill(skill_id: str) -> bool:
    delete_resource(skill_id)
    affected = execute(
        "DELETE FROM ENTITIES WHERE ENTITY_ID = :veid AND ENTITY_TYPE = 'SKILL'",
        {"veid": skill_id},
    )
    return affected > 0


def upload_skill_resource(skill_id: str, filename: str, content: bytes) -> Optional[Dict[str, Any]]:
    skill = get_skill(skill_id)
    if skill is None:
        return None
    return save_resource(skill_id, filename, content)


def get_skill_resource_info(skill_id: str) -> Optional[Dict[str, Any]]:
    skill = get_skill(skill_id)
    if skill is None:
        return None
    info = get_resource_info(skill_id)
    if info is None:
        return {"skill_id": skill_id, "has_resource": False}
    info["skill_id"] = skill_id
    info["has_resource"] = bool(info.get("resource_uri"))
    return info


def delete_skill_resource(skill_id: str) -> bool:
    skill = get_skill(skill_id)
    if skill is None:
        return False
    return delete_resource(skill_id)


def resolve_dependencies(skill_id: str) -> List[Dict[str, Any]]:
    row = execute_query_one(
        "SELECT DEPENDENCIES FROM SKILL_META WHERE ENTITY_ID = :eid",
        {"eid": skill_id},
    )
    if row is None:
        return []

    deps = row["dependencies"]
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(deps, list):
        return []

    resolved = []
    for dep_id in deps:
        skill = get_skill(dep_id)
        if skill is not None:
            resolved.append(skill)
    return resolved


def validate_skill(skill_id: str) -> Dict[str, Any]:
    skill = get_skill(skill_id)
    errors: List[str] = []
    if skill is None:
        return {"valid": False, "errors": [f"Skill {skill_id} not found"]}
    if not skill.get("skill_name"):
        errors.append("SKILL_NAME is required")
    return {"valid": len(errors) == 0, "errors": errors}


def deprecate_skill(skill_id: str) -> bool:
    meta_affected = execute(
        "UPDATE SKILL_META SET SKILL_STATUS = 'DEPRECATED' WHERE ENTITY_ID = :eid",
        {"eid": skill_id},
    )
    execute(
        "UPDATE ENTITIES SET STATUS = 'ARCHIVED', UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SKILL'",
        {"eid": skill_id},
    )
    return meta_affected > 0


import json as _json
from urllib.request import Request as _Request, urlopen as _urlopen
from urllib.error import HTTPError as _HTTPError, URLError as _URLError


def _admin_api_call(url: str, data: Optional[Dict] = None, timeout: int = 30) -> dict:
    body = _json.dumps(data).encode("utf-8") if data else None
    req = _Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    try:
        with _urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))
    except _HTTPError as e:
        try:
            return _json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except _URLError as e:
        return {"error": f"Connection failed: {e}"}


def register_skill_via_admin(
    admin_url: str,
    admin_token: str,
    title: str,
    skill_name: str,
    **kwargs,
) -> Optional[str]:
    url = f"{admin_url.rstrip('/')}/api/admin/skill/create"
    payload = {
        "admin_token": admin_token,
        "title": title,
        "skill_name": skill_name,
        **kwargs,
    }
    result = _admin_api_call(url, payload)
    if "error" in result:
        return None
    return result.get("skill_id")


def update_skill_via_admin(
    admin_url: str,
    admin_token: str,
    skill_id: str,
    **kwargs,
) -> bool:
    url = f"{admin_url.rstrip('/')}/api/admin/skill/update"
    payload = {
        "admin_token": admin_token,
        "skill_id": skill_id,
        **kwargs,
    }
    result = _admin_api_call(url, payload)
    return "skill" in result


def delete_skill_via_admin(
    admin_url: str,
    admin_token: str,
    skill_id: str,
) -> bool:
    url = f"{admin_url.rstrip('/')}/api/admin/skill/delete"
    payload = {"admin_token": admin_token, "skill_id": skill_id}
    result = _admin_api_call(url, payload)
    return result.get("deleted", False)


def upload_skill_resource_via_admin(
    admin_url: str,
    admin_token: str,
    skill_id: str,
    filename: str,
    content: bytes,
) -> Optional[Dict[str, Any]]:
    import base64
    url = f"{admin_url.rstrip('/')}/api/admin/skill/upload"
    payload = {
        "admin_token": admin_token,
        "skill_id": skill_id,
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    result = _admin_api_call(url, payload)
    if "error" in result:
        return None
    return result.get("upload")
