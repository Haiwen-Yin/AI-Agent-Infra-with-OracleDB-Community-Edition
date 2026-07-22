"""AI Agent Infra v4.0.1 - Enterprise Edition - Knowledge API

Knowledge CRUD, graph edges, spaced-review, and tagging.
Operates on ENTITIES (ENTITY_TYPE='KNOWLEDGE') + KNOWLEDGE_META + ENTITY_EDGES.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import (
    DATABASE_DIALECT, execute, execute_query, execute_query_one,
    execute_insert_returning_id,
)

logger = logging.getLogger(__name__)


def create_knowledge(
    title: str,
    content: str,
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    difficulty: str = "INTERMEDIATE",
    category: Optional[str] = None,
    importance: int = 5,
    summary: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "PRIVATE",
    workspace_id: Optional[str] = None,
) -> str:
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
                              IMPORTANCE, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
                              WORKSPACE_ID)
        VALUES (AI_NEW_ID(), 'KNOWLEDGE', :title, :content, :summary, :category,
                :importance, 'ACTIVE', :owned_by_agent, NULL, :visibility,
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
        "visibility": visibility,
        "wsid": workspace_id,
    }
    entity_id = execute_insert_returning_id(entity_sql, params)

    next_review = "CURRENT_TIMESTAMP + INTERVAL '7 days'" if DATABASE_DIALECT == "postgresql" else "CURRENT_TIMESTAMP + 7"
    meta_sql = f"""
        INSERT INTO KNOWLEDGE_META (ENTITY_ID, ENTITY_TYPE, DOMAIN, TOPIC, DIFFICULTY,
                                    REVIEW_COUNT, NEXT_REVIEW)
        VALUES (:eid, 'KNOWLEDGE', :domain, :topic, :difficulty, 0, {next_review})
    """
    execute(meta_sql, {
        "eid": entity_id,
        "domain": domain,
        "topic": topic,
        "difficulty": difficulty,
    })
    return entity_id


def get_knowledge(entity_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.EXPIRES_AT, 'YYYY-MM-DD HH24:MI:SS') AS EXPIRES_AT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'KNOWLEDGE'
    """
    row = execute_query_one(sql, {"id": entity_id})
    if row is None:
        return None
    return _row_to_dict(row)


def update_knowledge(entity_id: str, **kwargs) -> bool:
    entity_fields = {"title", "content", "summary", "category", "importance",
                     "status", "visibility", "expires_at"}
    meta_fields = {"domain", "topic", "difficulty"}

    entity_updates = {}
    meta_updates = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields:
            entity_updates[lk] = v
        elif lk in meta_fields:
            meta_updates[lk] = v

    affected = 0

    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
        entity_updates["id"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE KNOWLEDGE_META SET {set_clause} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE'"
        affected += execute(sql, meta_updates)

    return affected > 0


def delete_knowledge(entity_id: str) -> bool:
    execute("DELETE FROM ENTITY_TAGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    execute("DELETE FROM KNOWLEDGE_META WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    execute("DELETE FROM ENTITY_EDGES WHERE (SOURCE_ID = :id AND SOURCE_TYPE = 'KNOWLEDGE') OR TARGET_ID = :id", {"id": str(entity_id)})
    execute("DELETE FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'", {"id": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
    return execute(sql, {"id": entity_id}) > 0


def search_knowledge(
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    keyword: Optional[str] = None,
    difficulty: Optional[str] = None,
    workspace_id: Optional[str] = None,
    isolation_mode: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'KNOWLEDGE'"]
    params: Dict[str, Any] = {"lim": limit, "off": offset}

    if domain:
        conditions.append("km.DOMAIN = :domain")
        params["domain"] = domain
    if topic:
        conditions.append("km.TOPIC = :topic")
        params["topic"] = topic
    if difficulty:
        conditions.append("km.DIFFICULTY = :difficulty")
        params["difficulty"] = difficulty
    if keyword:
        conditions.append("(UPPER(e.TITLE) LIKE UPPER(:kw) OR UPPER(e.CONTENT) LIKE UPPER(:kw))")
        params["kw"] = f"%{keyword}%"
    if isolation_mode == 'SHARED':
        conditions.append("e.WORKSPACE_ID IS NULL")
    elif isolation_mode == 'ISOLATED' and workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    elif workspace_id:
        conditions.append("e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, params)]


def get_due_reviews(limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY, e.CATEGORY,
               e.IMPORTANCE, e.STATUS, e.OWNED_BY_AGENT, e.SOURCE_AGENT, e.VISIBILITY,
               e.RETRIEVAL_COUNT,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY, km.REVIEW_COUNT,
               TO_CHAR(km.LAST_REVIEWED, 'YYYY-MM-DD HH24:MI:SS') AS LAST_REVIEWED,
               TO_CHAR(km.NEXT_REVIEW, 'YYYY-MM-DD HH24:MI:SS') AS NEXT_REVIEW
        FROM ENTITIES e
        JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
                               AND km.ENTITY_TYPE = 'KNOWLEDGE'
        WHERE km.NEXT_REVIEW <= CURRENT_TIMESTAMP AND e.STATUS = 'ACTIVE'
        ORDER BY km.NEXT_REVIEW ASC
        FETCH FIRST :lim ROWS ONLY
    """
    return [_row_to_dict(r) for r in execute_query(sql, {"lim": limit})]


def record_review(entity_id: str) -> bool:
    review_interval = (
        "CURRENT_TIMESTAMP + LEAST(POWER(2, REVIEW_COUNT + 1), 30) * INTERVAL '1 day'"
        if DATABASE_DIALECT == "postgresql"
        else "CURRENT_TIMESTAMP + LEAST(POWER(2, REVIEW_COUNT + 1), 30)"
    )
    sql = f"""
        UPDATE KNOWLEDGE_META
        SET REVIEW_COUNT = REVIEW_COUNT + 1,
            LAST_REVIEWED = CURRENT_TIMESTAMP,
            NEXT_REVIEW = {review_interval}
        WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE'
    """
    return execute(sql, {"eid": entity_id}) > 0


def add_knowledge_tags(entity_id: str, tag_names: List[str]) -> int:
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
            SELECT :eid, 'KNOWLEDGE', :tid
            WHERE NOT EXISTS (
                SELECT 1 FROM ENTITY_TAGS
                WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'KNOWLEDGE' AND TAG_ID = :tid
            )
        """
        if execute(insert_sql, {"eid": entity_id, "tid": tag_id}) > 0:
            added += 1
    return added


def get_knowledge_tags(entity_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT t.TAG_ID, t.TAG_NAME, t.TAG_GROUP
        FROM ENTITY_TAGS et
        JOIN TAGS t ON et.TAG_ID = t.TAG_ID
        WHERE et.ENTITY_ID = :id AND et.ENTITY_TYPE = 'KNOWLEDGE'
    """
    rows = execute_query(sql, {"id": entity_id})
    return [
        {"tag_id": r["tag_id"], "tag_name": r["tag_name"], "tag_group": r.get("tag_group")}
        for r in rows
    ]


def remove_knowledge_tag(entity_id: str, tag_id: int) -> bool:
    sql = """
        DELETE FROM ENTITY_TAGS
        WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE' AND TAG_ID = :tag_id
    """
    return execute(sql, {"id": entity_id, "tag_id": tag_id}) > 0


def add_edge(
    source_id: str,
    source_type: str,
    target_id: str,
    edge_type: str,
    strength: float = 1.0,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    sql = """
        INSERT INTO ENTITY_EDGES (EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                                  STRENGTH, CONFIDENCE, METADATA)
        VALUES ('E_' || AI_NEW_ID(), :source_id, :source_type, :target_id, :edge_type,
                :strength, :confidence, :metadata)
        RETURNING EDGE_ID INTO :ret_id
    """
    params = {
        "source_id": source_id,
        "source_type": source_type,
        "target_id": target_id,
        "edge_type": edge_type,
        "strength": strength,
        "confidence": confidence,
        "metadata": json.dumps(metadata) if metadata else None,
    }
    return execute_insert_returning_id(sql, params, id_column="EDGE_ID")


def get_edges(entity_id: str, direction: str = "both") -> List[Dict[str, Any]]:
    if direction == "outgoing":
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM ENTITY_EDGES
            WHERE SOURCE_ID = :id
            ORDER BY CREATED_AT DESC
        """
    elif direction == "incoming":
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM ENTITY_EDGES
            WHERE TARGET_ID = :id
            ORDER BY CREATED_AT DESC
        """
    else:
        sql = """
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   'outgoing' AS DIRECTION
            FROM ENTITY_EDGES
            WHERE SOURCE_ID = :id
            UNION ALL
            SELECT EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE,
                   STRENGTH, CONFIDENCE, METADATA,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   'incoming' AS DIRECTION
            FROM ENTITY_EDGES
            WHERE TARGET_ID = :id
            ORDER BY CREATED_AT DESC
        """
    rows = execute_query(sql, {"id": entity_id})
    result = []
    for r in rows:
        edge = {
            "edge_id": r.get("edge_id"),
            "source_id": r.get("source_id"),
            "source_type": r.get("source_type"),
            "target_id": r.get("target_id"),
            "edge_type": r.get("edge_type"),
            "strength": r.get("strength"),
            "confidence": r.get("confidence"),
            "metadata": r.get("metadata"),
            "created_at": r.get("created_at"),
        }
        if direction == "both":
            edge["direction"] = r.get("direction")
        if isinstance(edge["metadata"], str):
            try:
                edge["metadata"] = json.loads(edge["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(edge)
    return result


def count_knowledge(domain: Optional[str] = None) -> int:
    if domain:
        sql = """
            SELECT COUNT(*) AS CNT
            FROM ENTITIES e
            JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID AND km.ENTITY_TYPE = 'KNOWLEDGE'
            WHERE e.ENTITY_TYPE = 'KNOWLEDGE' AND km.DOMAIN = :domain
        """
        row = execute_query_one(sql, {"domain": domain})
    else:
        sql = "SELECT COUNT(*) AS CNT FROM ENTITIES WHERE ENTITY_TYPE = 'KNOWLEDGE'"
        row = execute_query_one(sql)
    return row["cnt"] if row else 0


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
        "expires_at": row.get("expires_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "domain": row.get("domain"),
        "topic": row.get("topic"),
        "difficulty": row.get("difficulty"),
        "review_count": row.get("review_count"),
        "last_reviewed": row.get("last_reviewed"),
        "next_review": row.get("next_review"),
    }


# -- D4: Advanced Knowledge Management (v3.7.5) --

def merge_knowledge(source_id: str, target_id: str, strategy: str = "UNION") -> Dict[str, Any]:
    """Merge two knowledge entries using the specified strategy."""
    source = get_knowledge(source_id)
    target = get_knowledge(target_id)
    if not source or not target:
        return {"error": "Source or target not found"}

    if strategy == "OVERWRITE":
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": source.get("content", ""), "tid": target_id},
        )
        execute("UPDATE ENTITIES SET VISIBILITY = 'PRIVATE' WHERE ENTITY_ID = :sid", {"sid": source_id})
        return {"strategy": strategy, "target_id": target_id, "source_archived": True}

    elif strategy == "UNION":
        merged_content = (target.get("content", "") or "") + "\n\n---\n\n" + (source.get("content", "") or "")
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": merged_content, "tid": target_id},
        )
        execute("UPDATE ENTITIES SET VISIBILITY = 'PRIVATE' WHERE ENTITY_ID = :sid", {"sid": source_id})
        return {"strategy": strategy, "target_id": target_id, "merged_length": len(merged_content)}

    elif strategy == "WEIGHTED":
        source_strength = float(source.get("metadata", {}).get("strength", 0.5)) if isinstance(source.get("metadata"), dict) else 0.5
        target_strength = float(target.get("metadata", {}).get("strength", 0.5)) if isinstance(target.get("metadata"), dict) else 0.5
        total = source_strength + target_strength
        if total == 0:
            total = 1
        merged_content = source.get("content", "") or ""
        execute(
            "UPDATE ENTITIES SET CONTENT = :content, UPDATED_AT = CURRENT_TIMESTAMP WHERE ENTITY_ID = :tid",
            {"content": merged_content, "tid": target_id},
        )
        return {"strategy": strategy, "target_id": target_id, "source_weight": source_strength / total}

    return {"error": f"Unknown strategy: {strategy}"}


def detect_knowledge_conflicts(workspace_id: str) -> List[Dict[str, Any]]:
    """Detect knowledge entries with similar titles but different content in the same workspace."""
    rows = execute_query(
        """SELECT a.ENTITY_ID as id_a, a.TITLE as title_a, a.CONTENT as content_a,
                  b.ENTITY_ID as id_b, b.TITLE as title_b, b.CONTENT as content_b
           FROM ENTITIES a
           JOIN ENTITIES b ON a.ENTITY_ID < b.ENTITY_ID
           WHERE a.ENTITY_TYPE = 'KNOWLEDGE' AND b.ENTITY_TYPE = 'KNOWLEDGE'
             AND a.WORKSPACE_ID = :wid AND b.WORKSPACE_ID = :wid
             AND (UPPER(a.TITLE) = UPPER(b.TITLE)
                  OR DBMS_LOB.GETLENGTH(a.CONTENT) > 0 AND DBMS_LOB.GETLENGTH(b.CONTENT) > 0
                  AND DBMS_LOB.SUBSTR(a.CONTENT, 200, 1) = DBMS_LOB.SUBSTR(b.CONTENT, 200, 1))
           FETCH FIRST 50 ROWS ONLY""",
        {"wid": workspace_id},
    )
    conflicts = []
    for r in rows:
        if r.get("content_a") != r.get("content_b"):
            conflicts.append({
                "id_a": r["id_a"], "id_b": r["id_b"],
                "title": r.get("title_a") or r.get("title_b"),
                "conflict_type": "content_mismatch",
            })
    return conflicts
