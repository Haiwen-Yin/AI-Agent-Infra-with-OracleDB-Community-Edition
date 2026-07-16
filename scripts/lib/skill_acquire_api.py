"""AI Agent Infra v3.10.2 - Community Edition - Skill Acquisition API

Agent-facing interface for discovering and acquiring skills.
- Community Edition: direct access, no token required
- Admin API mode: Business Agent acquires skills via Admin Agent HTTP API
"""

import io
import zipfile
from typing import Any, Dict, List, Optional

from .connection import execute_query, execute_query_one
from .skill_api import get_skill, list_skills
from .skill_storage import read_resource_content, _get_skill_dir


def discover_skills(
    skill_type: Optional[str] = None,
    runtime: Optional[str] = None,
    skill_format: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Discover available skills matching criteria.
    
    Returns a list of skill metadata (no resource content).
    Agent uses this to find relevant skills.
    """
    conditions = ["e.ENTITY_TYPE = 'SKILL'", "sm.SKILL_STATUS = 'ACTIVE'"]
    params: Dict[str, Any] = {"lim": 50, "off": 0}

    if skill_type:
        conditions.append("sm.SKILL_TYPE = :vstype")
        params["vstype"] = skill_type
    if runtime:
        conditions.append("sm.RUNTIME = :vruntime")
        params["vruntime"] = runtime
    if skill_format:
        conditions.append("sm.SKILL_FORMAT = :vsformat")
        params["vsformat"] = skill_format
    if keyword:
        conditions.append("(UPPER(sm.SKILL_NAME) LIKE UPPER(:vkw) OR UPPER(e.TITLE) LIKE UPPER(:vkw) OR UPPER(sm.SKILL_DESCRIPTION) LIKE UPPER(:vkw))")
        params["vkw"] = f"%{keyword}%"

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.TITLE, e.CATEGORY, e.STATUS,
               e.VISIBILITY, e.OWNED_BY_AGENT,
               sm.SKILL_NAME, sm.SKILL_VERSION, sm.SKILL_TYPE, sm.SKILL_FORMAT,
               sm.RUNTIME, sm.SKILL_STATUS, sm.SKILL_DESCRIPTION,
               sm.RESOURCE_URI, sm.RESOURCE_FILENAME, sm.RESOURCE_SIZE
        FROM ENTITIES e
        JOIN SKILL_META sm ON sm.ENTITY_ID = e.ENTITY_ID AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    rows = execute_query(sql, params)
    return rows


def acquire_skill_text(skill_id: str) -> Optional[Dict[str, Any]]:
    """Acquire a skill's text content (SKILL.md).
    
    This is always available without token - it returns the
    skill metadata + text_content (the SKILL.md markdown).
    Resource files require separate acquisition.
    
    Returns dict with: skill_name, version, format, runtime,
    text_content, description, parameters, dependencies.
    """
    skill = get_skill(skill_id)
    if skill is None:
        return None
    if skill.get("skill_status") != "ACTIVE":
        return None

    return {
        "skill_id": skill_id,
        "skill_name": skill.get("skill_name"),
        "skill_version": skill.get("skill_version"),
        "skill_type": skill.get("skill_type"),
        "skill_format": skill.get("skill_format"),
        "runtime": skill.get("runtime"),
        "title": skill.get("title"),
        "description": skill.get("skill_description"),
        "text_content": skill.get("text_content"),
        "parameters": skill.get("parameters"),
        "dependencies": skill.get("dependencies"),
        "has_resource": bool(skill.get("resource_uri")),
        "resource_size": skill.get("resource_size"),
        "resource_filename": skill.get("resource_filename"),
    }


def acquire_skill_resource(skill_id: str, agent_id: Optional[str] = None, session_id: Optional[str] = None) -> Optional[bytes]:
    """Acquire a skill's resource files as a ZIP archive.
    
    Community Edition: Direct access, no token required.
    
    Args:
        skill_id: The skill entity ID
        agent_id: Agent requesting access (used for ENT token flow)
        session_id: Optional session ID (ENT only)
    
    Returns:
        ZIP archive bytes containing all resource files, or None if no resource.
    """
    skill = get_skill(skill_id)
    if skill is None or not skill.get("resource_uri"):
        return None

    content = read_resource_content(skill_id)
    if content is None:
        return None

    return content


def acquire_skill_full(skill_id: str, agent_id: Optional[str] = None, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Acquire full skill: metadata + text + resource ZIP.
    
    This is the primary Agent entry point for getting a complete skill.
    
    Args:
        skill_id: The skill entity ID
        agent_id: Agent requesting access (ENT only, for audit)
        session_id: Optional session ID (ENT only)
    
    Returns:
        Dict with all skill metadata, text_content, and resource_zip (bytes).
    """
    text_result = acquire_skill_text(skill_id)
    if text_result is None:
        return None

    resource_zip = None
    if text_result.get("has_resource"):
        resource_zip = acquire_skill_resource(skill_id, agent_id, session_id)

    result = {**text_result, "resource_zip": resource_zip}

    # v3.7.5: Auto-trigger validation loop if defined in skill metadata
    try:
        from .loop_api import create_validation_loop_for_skill
        validation_loop_id = create_validation_loop_for_skill(skill_id, agent_id or 'system')
    except Exception:
        pass

    return result


import json as _json
from urllib.request import Request as _Request, urlopen as _urlopen
from urllib.error import HTTPError as _HTTPError, URLError as _URLError


def _admin_api_get(url: str, timeout: int = 30) -> dict:
    req = _Request(url, headers={"Accept": "application/json"}, method="GET")
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


def discover_skills_via_admin(
    admin_url: str,
    admin_token: str,
    skill_type: Optional[str] = None,
    runtime: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    url = f"{admin_url.rstrip('/')}/api/admin/skill/list?admin_token={admin_token}"
    if skill_type:
        url += f"&type={skill_type}"
    if runtime:
        url += f"&runtime={runtime}"
    if keyword:
        url += f"&keyword={keyword}"
    result = _admin_api_get(url)
    return result.get("skills", [])


def acquire_skill_via_admin(
    admin_url: str,
    admin_token: str,
    skill_id: str,
    include_resource: bool = False,
) -> Optional[Dict[str, Any]]:
    url = f"{admin_url.rstrip('/')}/api/admin/skill/{skill_id}/acquire?admin_token={admin_token}"
    if include_resource:
        url += "&resource=1"
    result = _admin_api_get(url)
    if "error" in result:
        return None
    if include_resource and result.get("resource_encoding") == "base64" and result.get("resource_zip"):
        import base64
        result["resource_zip"] = base64.b64decode(result["resource_zip"])
        result.pop("resource_encoding", None)

    # v3.7.5: Auto-trigger validation loop if defined in skill metadata
    try:
        from .loop_api import create_validation_loop_for_skill
        validation_loop_id = create_validation_loop_for_skill(skill_id, 'system')
    except Exception:
        pass

    return result
