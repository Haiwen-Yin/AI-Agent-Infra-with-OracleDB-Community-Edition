"""AI Agent Infra v4.4.1 - Community Edition - Memory API

Unified memory management using oracledb with bind variables.
Operates on the ENTITIES table (ENTITY_TYPE='MEMORY').
"""

import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id
from . import memory_lifecycle

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
        VALUES (AI_NEW_ID(), 'MEMORY', :title, :content, :summary, :category,
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
    entity_id = execute_insert_returning_id(sql, params)
    # v4.3.2 retains the external entity ID but adopts it into a stable
    # family immediately. A transient adoption failure does not hide a
    # successfully committed legacy write; the additive migration can retry.
    try:
        memory_lifecycle.adopt_legacy_memory(str(entity_id), actor=source_agent)
    except Exception:
        logger.exception("memory lifecycle adoption deferred for %s", entity_id)
    return entity_id


def get_memory(entity_id: str) -> Optional[Dict[str, Any]]:
    try:
        family_id = f"MF-{entity_id}"
        detail = memory_lifecycle.get_family(family_id)
        if detail and detail.get("current"):
            return detail["current"]
    except Exception:
        # Pre-upgrade installations continue through the legacy read below.
        pass
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
    try:
        family_id = memory_lifecycle.adopt_legacy_memory(str(entity_id))
        detail = memory_lifecycle.get_family(str(family_id)) if family_id else None
        current = detail.get("current") if detail else None
        if current:
            request = {
                "title": kwargs.get("title", current.get("title")),
                "body": kwargs.get("content", current.get("content") or ""),
                "memory_type": kwargs.get("memory_type", current.get("memory_type") or current.get("category") or "EPISODIC"),
                "memory_scope": kwargs.get("memory_scope", current.get("memory_scope") or "AGENT_MEMORY"),
                "classification": kwargs.get("classification", current.get("classification") or "INTERNAL"),
                "owner_agent_id": current.get("owner_agent_id") or current.get("owned_by_agent"),
                "workspace_id": current.get("workspace_id"),
                "valid_until": kwargs.get("expires_at", current.get("valid_until")),
                "reason": kwargs.get("reason", "legacy update compatibility"),
            }
            memory_lifecycle.create_successor(str(family_id), str(current["version_id"]), request, actor="LEGACY_COMPAT")
            return True
    except memory_lifecycle.MemoryLifecycleError:
        return False
    except Exception:
        logger.exception("memory lifecycle update deferred for %s", entity_id)
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
    set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
    updates["id"] = entity_id

    sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'MEMORY'"
    return execute(sql, updates) > 0


def delete_memory(entity_id: str) -> bool:
    """Compatibility delete: retire from ordinary retrieval, never erase evidence."""
    try:
        family_id = memory_lifecycle.adopt_legacy_memory(str(entity_id))
        if family_id:
            memory_lifecycle.mark_unavailable(
                str(family_id), actor="LEGACY_COMPAT",
                reason="Legacy delete request: logical unavailability",
            )
            return True
    except Exception:
        logger.exception("logical memory retirement unavailable for %s", entity_id)
        return False
    # A pre-v4.3.2 schema has no governed lifecycle. Do not fall back to a
    # destructive write: callers must upgrade before deleting memory.
    return False


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
    try:
        return memory_lifecycle.current_memories(
            keyword=keyword, memory_type=category, workspace_id=workspace_id,
            owner_agent_id=owned_by_agent, limit=limit, offset=offset,
        )
    except Exception:
        # The legacy projection is retained only while an additive migration
        # has not yet completed.
        logger.debug("using pre-v4.3.2 memory search compatibility", exc_info=True)
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
    try:
        return memory_lifecycle.current_memories(owner_agent_id=agent_id, limit=limit)
    except Exception:
        logger.debug("using pre-v4.3.2 agent-memory compatibility", exc_info=True)
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
    try:
        return len(memory_lifecycle.current_memories(memory_type=category, limit=500))
    except Exception:
        logger.debug("using pre-v4.3.2 count compatibility", exc_info=True)
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
            USING (SELECT :tag_name AS TAG_NAME) src
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
            SELECT :eid, 'MEMORY', :tid
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


# -- D4: Advanced Memory Management (v3.7.5) --

def consolidate_branch_memories(branch_id: str, target_workspace_id: str) -> Dict[str, Any]:
    """Stage branch-to-workspace promotion candidates; never copy silently."""
    memories = execute_query(
        """SELECT e.ENTITY_ID, e.TITLE FROM ENTITIES e
           JOIN WORKSPACES w ON w.WORKSPACE_ID=e.WORKSPACE_ID
           WHERE e.ENTITY_TYPE='MEMORY' AND w.BRANCH_ID=:bid
           FETCH FIRST :lim ROWS ONLY""",
        {"bid": branch_id, "lim": 200},
    )
    candidates, skipped = 0, 0
    for memory in memories:
        try:
            family_id = memory_lifecycle.adopt_legacy_memory(str(memory["entity_id"]), actor="LEGACY_COMPAT")
            detail = memory_lifecycle.get_family(str(family_id)) if family_id else None
            current = detail.get("current") if detail else None
            if not current:
                skipped += 1
                continue
            memory_lifecycle.create_candidate(
                "PROMOTE", str(current["version_id"]),
                {"workspace_id": target_workspace_id, "memory_scope": "WORKSPACE_MEMORY", "source_branch_id": branch_id},
                actor="LEGACY_COMPAT", reason="Branch consolidation requires governed workspace promotion",
                idempotency_key=f"branch-promote:{branch_id}:{target_workspace_id}:{current['version_id']}",
            )
            candidates += 1
        except Exception:
            logger.exception("unable to stage branch memory promotion for %s", memory.get("entity_id"))
            skipped += 1
    return {"merged": 0, "candidates": candidates, "skipped": skipped, "total": len(memories), "requires_review": True}


def promote_to_semantic(memory_id: str) -> Optional[str]:
    """Stage an enterprise-knowledge promotion for governed review.

    The return value is a Memory Candidate ID for callers to track, not a
    silently created Knowledge record or broadened data scope.
    """
    try:
        family_id = memory_lifecycle.adopt_legacy_memory(str(memory_id), actor="LEGACY_COMPAT")
        detail = memory_lifecycle.get_family(str(family_id)) if family_id else None
        current = detail.get("current") if detail else None
        if not current:
            return None
        candidate = memory_lifecycle.create_candidate(
            "PROMOTE", str(current["version_id"]),
            {"memory_scope": "ENTERPRISE_KNOWLEDGE", "promotion_target": "KNOWLEDGE"},
            actor="LEGACY_COMPAT", reason="Semantic knowledge promotion requires review",
            idempotency_key=f"semantic-promote:{current['version_id']}",
        )
        return str(candidate["candidate_id"])
    except Exception:
        logger.exception("unable to stage semantic promotion for %s", memory_id)
        return None


def schedule_consolidation(agent_id: str, interval_hours: int = 24) -> bool:
    """Create a portable dry-run consolidation Job instead of vendor scheduling.

    A node scheduler may submit this durable Job at the requested interval, but
    scheduling policy is intentionally outside this legacy compatibility call.
    """
    try:
        memory_lifecycle.create_job(
            "CONSOLIDATE", actor="LEGACY_COMPAT",
            scope={"owner_agent_id": agent_id, "requested_interval_hours": max(1, int(interval_hours))},
            dry_run=True, reason="Legacy consolidation schedule requested; review dry-run before execution",
            idempotency_key=f"legacy-consolidation:{agent_id}:{max(1, int(interval_hours))}",
        )
        return True
    except Exception:
        logger.exception("unable to create durable consolidation request for %s", agent_id)
        return False
