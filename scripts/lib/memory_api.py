"""AI Agent Infra v3.2.0 - Community Edition - Memory API

Unified memory management using oracledb with bind variables.
Operates on the ENTITIES table (ENTITY_TYPE='MEMORY').
"""

import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def create_memory(
    title: str,
    content: str,
    category: str = "general",
    importance: int = 5,
    summary: Optional[str] = None,
    source_agent: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "PRIVATE",
    workspace_id: Optional[str] = None,
) -> str:
    sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
                              WORKSPACE_ID)
        VALUES (RAWTOHEX(SYS_GUID()), 'MEMORY', :title, :content, :summary, :category,
                :importance, 'ACTIVE', :owned_by_agent, :source_agent, :visibility,
                :wsid)
        RETURNING ENTITY_ID INTO :ret_id
    """
    params = {
        "title": title[:500],
        "content": content,
        "summary": summary,
        "category": category,
        "importance": importance,
        "owned_by_agent": owned_by_agent,
        "source_agent": source_agent,
        "visibility": visibility,
        "wsid": workspace_id,
    }
    return execute_insert_returning_id(sql, params)


def get_memory(entity_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
               IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
               RETRIEVAL_COUNT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               TO_CHAR(EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT
        FROM ENTITIES
        WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'
    """
    row = execute_query_one(sql, {"id": entity_id})
    if row is None:
        return None
    return _row_to_dict(row)


def update_memory(entity_id: str, **kwargs) -> bool:
    allowed = {"title", "content", "summary", "category", "importance",
               "status", "visibility", "expires_at"}
    updates = {}
    for k, v in kwargs.items():
        lk = k.lower()
        if lk not in allowed:
            continue
        updates[lk] = v

    if not updates:
        return False

    set_parts = [f"{k} = :{k}" for k in updates]
    set_parts.append("UPDATED_AT = SYSTIMESTAMP")
    updates["id"] = entity_id

    sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'"
    return execute(sql, updates) > 0


def delete_memory(entity_id: str) -> bool:
    execute("DELETE FROM ENTITY_TAGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'", {"id": entity_id})
    execute("DELETE FROM ENTITY_EDGES WHERE SOURCE_ID = :id AND SOURCE_TYPE = 'MEMORY'", {"id": entity_id})
    execute("DELETE FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'", {"id": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'"
    return execute(sql, {"id": entity_id}) > 0


def search_memories(
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    visibility: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    workspace_id: Optional[str] = None,
    isolation_mode: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conditions = ["ENTITY_TYPE = 'MEMORY'"]
    params: Dict[str, Any] = {"lim": limit, "off": offset}

    if keyword:
        conditions.append("(UPPER(TITLE) LIKE UPPER(:kw) OR UPPER(CONTENT) LIKE UPPER(:kw))")
        params["kw"] = f"%{keyword}%"
    if category:
        conditions.append("CATEGORY = :cat")
        params["cat"] = category
    if visibility:
        conditions.append("VISIBILITY = :vis")
        params["vis"] = visibility
    if owned_by_agent:
        conditions.append("OWNED_BY_AGENT = :agent")
        params["agent"] = owned_by_agent
    if isolation_mode == 'SHARED':
        conditions.append("WORKSPACE_ID IS NULL")
    elif isolation_mode == 'ISOLATED' and workspace_id:
        conditions.append("WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    elif workspace_id:
        conditions.append("WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    where = " AND ".join(conditions)
    sql = f"""
        SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
               IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
               RETRIEVAL_COUNT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES
        WHERE {where}
        ORDER BY CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, params)]


def get_agent_memories(agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    sql = """
        SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
               IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
               RETRIEVAL_COUNT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES
        WHERE ENTITY_TYPE = 'MEMORY'
          AND (VISIBILITY = 'SHARED' OR VISIBILITY = 'PUBLIC' OR OWNED_BY_AGENT = :agent)
        ORDER BY CREATED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, {"agent": agent_id, "lim": limit})]


def count_memories(category: Optional[str] = None) -> int:
    sql = "SELECT COUNT(*) AS CNT FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY'"
    params: Dict[str, Any] = {}
    if category:
        sql += " AND CATEGORY = :cat"
        params["cat"] = category
    row = execute_query_one(sql, params)
    return row["cnt"] if row else 0


def add_memory_tags(entity_id: str, tag_names: List[str]) -> int:
    added = 0
    for tag_name in tag_names:
        merge_sql = """
            MERGE INTO TAGS t
            USING (SELECT :tag_name AS TAG_NAME FROM DUAL) src
            ON (t.TAG_NAME = src.TAG_NAME)
            WHEN NOT MATCHED THEN INSERT (TAG_NAME) VALUES (src.TAG_NAME)
        """
        execute(merge_sql, {"tag_name": tag_name})

        tag_row = execute_query_one(
            "SELECT TAG_ID FROM TAGS WHERE TAG_NAME = :tag_name",
            {"tag_name": tag_name},
        )
        if tag_row is None:
            continue

        tag_id = tag_row["tag_id"]
        insert_sql = """
            INSERT INTO ENTITY_TAGS (ENTITY_ID, ENTITY_TYPE, TAG_ID)
            SELECT :eid, 'MEMORY', :tid FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM ENTITY_TAGS
                WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'MEMORY' AND TAG_ID = :tid
            )
        """
        if execute(insert_sql, {"eid": entity_id, "tid": tag_id}) > 0:
            added += 1
    return added


def get_memory_tags(entity_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT t.TAG_ID, t.TAG_NAME, t.TAG_GROUP
        FROM ENTITY_TAGS et
        JOIN TAGS t ON et.TAG_ID = t.TAG_ID
        WHERE et.ENTITY_ID = :id AND et.ENTITY_TYPE = 'MEMORY'
    """
    rows = execute_query(sql, {"id": entity_id})
    return [
        {"tag_id": r["tag_id"], "tag_name": r["tag_name"], "tag_group": r.get("tag_group")}
        for r in rows
    ]


def remove_memory_tag(entity_id: str, tag_id: int) -> bool:
    sql = """
        DELETE FROM ENTITY_TAGS
        WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY' AND TAG_ID = :tag_id
    """
    return execute(sql, {"id": entity_id, "tag_id": tag_id}) > 0


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entity_id": row.get("entity_id"),
        "entity_type": row.get("entity_type"),
        "title": row.get("title"),
        "content": row.get("content"),
        "summary": row.get("summary"),
        "category": row.get("category"),
        "importance": row.get("importance"),
        "status": row.get("status"),
        "owned_by_agent": row.get("owned_by_agent"),
        "source_agent": row.get("source_agent"),
        "visibility": row.get("visibility"),
        "retrieval_count": row.get("retrieval_count"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "expires_at": row.get("expires_at"),
    }
