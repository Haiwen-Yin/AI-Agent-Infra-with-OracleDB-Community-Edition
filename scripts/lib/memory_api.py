"""Oracle Memory System v2.0.0 - Memory API

Unified memory management using oracledb with bind variables.
Operates on the ENTITIES table (ENTITY_TYPE='MEMORY').
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def create_memory(
    name: str,
    content: str,
    category: str = "general",
    memory_type: str = "TEXT",
    priority: int = 2,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
    accessible_to: Optional[List[str]] = None,
) -> int:
    sql = """
        INSERT INTO ENTITIES (ENTITY_TYPE, NAME, CONTENT, CATEGORY, PRIORITY, STATUS,
                              TAGS, METADATA, OWNED_BY_AGENT, VISIBILITY, ACCESSIBLE_TO)
        VALUES ('MEMORY', :name, :content, :category, :priority, 'ACTIVE',
                :tags, :metadata, :owned_by_agent, :visibility, :accessible_to)
        RETURNING ENTITY_ID INTO :ret_id
    """
    params = {
        "name": name[:500],
        "content": content,
        "category": category,
        "priority": priority,
        "tags": json.dumps(tags or []),
        "metadata": json.dumps(metadata or {}),
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
        "accessible_to": json.dumps(accessible_to or []),
    }
    return execute_insert_returning_id(sql, params)


def get_memory(entity_id: int) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT ENTITY_ID, NAME, CONTENT, CATEGORY, PRIORITY, STATUS,
               TAGS, METADATA, OWNED_BY_AGENT, VISIBILITY, ACCESSIBLE_TO,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               TO_CHAR(EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT
        FROM ENTITIES
        WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'
    """
    row = execute_query_one(sql, {"id": entity_id})
    if row is None:
        return None
    return _decorate_memory(row)


def update_memory(entity_id: int, **kwargs) -> bool:
    allowed = {"name", "content", "category", "priority", "status", "tags",
               "metadata", "visibility", "accessible_to", "expires_at"}
    updates = {}
    for k, v in kwargs.items():
        lk = k.lower()
        if lk not in allowed:
            continue
        if lk in ("tags", "metadata", "accessible_to") and isinstance(v, (list, dict)):
            v = json.dumps(v)
        updates[lk] = v

    if not updates:
        return False

    set_parts = [f"{k} = :{k}" for k in updates]
    set_parts.append("UPDATED_AT = SYSTIMESTAMP")
    updates["id"] = entity_id

    sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'"
    return execute(sql, updates) > 0


def delete_memory(entity_id: int) -> bool:
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'"
    return execute(sql, {"id": entity_id}) > 0


def search_memories(
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    visibility: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conditions = ["ENTITY_TYPE = 'MEMORY'"]
    params: Dict[str, Any] = {"lim": limit, "off": offset}

    if keyword:
        conditions.append("UPPER(NAME) LIKE UPPER(:kw) OR UPPER(CONTENT) LIKE UPPER(:kw)")
        params["kw"] = f"%{keyword}%"
    if category:
        conditions.append("CATEGORY = :cat")
        params["cat"] = category
    if visibility:
        conditions.append("VISIBILITY = :vis")
        params["vis"] = visibility
    if owned_by_agent:
        conditions.append("(OWNED_BY_AGENT = :agent OR VISIBILITY = 'SHARED')")
        params["agent"] = owned_by_agent

    where = " AND ".join(conditions)
    sql = f"""
        SELECT ENTITY_ID, NAME, CONTENT, CATEGORY, PRIORITY, STATUS,
               OWNED_BY_AGENT, VISIBILITY,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES
        WHERE {where}
        ORDER BY CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    return [_decorate_memory(r) for r in execute_query(sql, params)]


def get_agent_memories(agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    sql = """
        SELECT ENTITY_ID, NAME, CONTENT, CATEGORY, PRIORITY, VISIBILITY,
               OWNED_BY_AGENT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES
        WHERE ENTITY_TYPE = 'MEMORY'
          AND (
              VISIBILITY = 'SHARED'
              OR OWNED_BY_AGENT = :agent
              OR (VISIBILITY = 'COLLABORATIVE'
                  AND EXISTS (
                      SELECT 1 FROM JSON_TABLE(ACCESSIBLE_TO, '$[*]' COLUMNS(
                          aid VARCHAR2(64) PATH '$'
                      )) jt WHERE jt.aid = :agent
                  ))
          )
        ORDER BY CREATED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return [_decorate_memory(r) for r in execute_query(sql, {"agent": agent_id, "lim": limit})]


def count_memories(category: Optional[str] = None) -> int:
    sql = "SELECT COUNT(*) AS CNT FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY'"
    params: Dict[str, Any] = {}
    if category:
        sql += " AND CATEGORY = :cat"
        params["cat"] = category
    row = execute_query_one(sql, params)
    return row["cnt"] if row else 0


def _decorate_memory(row: Dict[str, Any]) -> Dict[str, Any]:
    for json_col in ("tags", "metadata", "accessible_to"):
        val = row.get(json_col)
        if isinstance(val, str):
            try:
                row[json_col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[json_col] = val
    return row
