"""Oracle Memory System v2.0.0 - Knowledge API

Knowledge concept CRUD, graph operations, versioning, distillation.
Operates on ENTITIES (ENTITY_TYPE='KNOWLEDGE') + KNOWLEDGE_META + ENTITY_EDGES.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def create_concept(
    name: str,
    concept_type: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
    content: Optional[str] = None,
    source_type: str = "MANUAL",
    source_entity_ids: Optional[List[int]] = None,
    confidence: float = 0.8,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
) -> int:
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_TYPE, NAME, DESCRIPTION, CONTENT, CATEGORY,
                              PRIORITY, STATUS, TAGS, METADATA,
                              OWNED_BY_AGENT, VISIBILITY)
        VALUES ('KNOWLEDGE', :name, :description, :content, :category,
                1, 'ACTIVE', :tags, :metadata,
                :owned_by_agent, :visibility)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_params = {
        "name": name[:500],
        "description": description,
        "content": content,
        "category": category,
        "tags": json.dumps(tags or []),
        "metadata": json.dumps(metadata or {}),
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
    }
    entity_id = execute_insert_returning_id(entity_sql, entity_params)

    meta_sql = """
        INSERT INTO KNOWLEDGE_META (ENTITY_ID, SOURCE_TYPE, SOURCE_ENTITY_IDS,
                                    VALIDATION_STATUS, CONFIDENCE, VERSION, IS_CURRENT)
        VALUES (:eid, :source_type, :source_ids, 'PENDING', :confidence, 1, 'Y')
    """
    execute(meta_sql, {
        "eid": entity_id,
        "source_type": source_type,
        "source_ids": json.dumps(source_entity_ids or []),
        "confidence": confidence,
    })
    return entity_id


def get_concept(entity_id: int) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT e.ENTITY_ID, e.NAME, e.DESCRIPTION, e.CONTENT, e.CATEGORY,
               e.TAGS, e.METADATA, e.OWNED_BY_AGENT, e.VISIBILITY,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               km.SOURCE_TYPE, km.SOURCE_ENTITY_IDS,
               km.VALIDATION_STATUS, km.CONFIDENCE,
               km.VERSION, km.IS_CURRENT,
               TO_CHAR(km.VALIDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS VALIDATED_AT,
               TO_CHAR(km.DEPRECATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS DEPRECATED_AT
        FROM ENTITIES e
        LEFT JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'KNOWLEDGE'
    """
    row = execute_query_one(sql, {"id": entity_id})
    if row is None:
        return None
    return _decorate_concept(row)


def update_concept(entity_id: int, **kwargs) -> bool:
    entity_fields = {"name", "description", "content", "category", "tags", "metadata"}
    meta_fields = {"validation_status", "confidence", "is_current", "source_type"}

    entity_updates = {}
    meta_updates = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields:
            if lk in ("tags", "metadata") and isinstance(v, (list, dict)):
                v = json.dumps(v)
            entity_updates[lk] = v
        elif lk in meta_fields:
            meta_updates[lk] = v

    affected = 0
    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = SYSTIMESTAMP")
        entity_updates["id"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE KNOWLEDGE_META SET {set_clause} WHERE ENTITY_ID = :eid"
        affected += execute(sql, meta_updates)

    return affected > 0


def delete_concept(entity_id: int) -> bool:
    execute("DELETE FROM KNOWLEDGE_META WHERE ENTITY_ID = :eid", {"eid": entity_id})
    execute("DELETE FROM ENTITY_EDGES WHERE SOURCE_ID = :id OR TARGET_ID = :id", {"id": entity_id})
    sql = "DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'KNOWLEDGE'"
    return execute(sql, {"id": entity_id}) > 0


def create_relationship(
    source_id: int,
    target_id: int,
    edge_type: str,
    strength: float = 1.0,
    confidence: float = 0.8,
    properties: Optional[Dict[str, Any]] = None,
) -> int:
    sql = """
        INSERT INTO ENTITY_EDGES (SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, PROPERTIES)
        VALUES (:source_id, :target_id, :edge_type, :strength, :confidence, :properties)
        RETURNING EDGE_ID INTO :ret_id
    """
    params = {
        "source_id": source_id,
        "target_id": target_id,
        "edge_type": edge_type,
        "strength": strength,
        "confidence": confidence,
        "properties": json.dumps(properties or {}),
    }
    return execute_insert_returning_id(sql, params)


def get_relationships(entity_id: int, direction: str = "both") -> List[Dict[str, Any]]:
    if direction == "outgoing":
        where = "SOURCE_ID = :id"
    elif direction == "incoming":
        where = "TARGET_ID = :id"
    else:
        where = "(SOURCE_ID = :id OR TARGET_ID = :id)"

    sql = f"""
        SELECT EDGE_ID, SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, PROPERTIES,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITY_EDGES
        WHERE {where}
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


def delete_relationship(edge_id: int) -> bool:
    return execute("DELETE FROM ENTITY_EDGES WHERE EDGE_ID = :id", {"id": edge_id}) > 0


def search_concepts(
    keyword: Optional[str] = None,
    concept_type: Optional[str] = None,
    category: Optional[str] = None,
    validation_status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    conditions = ["e.ENTITY_TYPE = 'KNOWLEDGE'"]
    params: Dict[str, Any] = {"lim": limit}

    if keyword:
        conditions.append("(UPPER(e.NAME) LIKE UPPER(:kw) OR UPPER(e.DESCRIPTION) LIKE UPPER(:kw))")
        params["kw"] = f"%{keyword}%"
    if concept_type:
        conditions.append("e.CATEGORY = :ctype")
        params["ctype"] = concept_type
    if category:
        conditions.append("e.CATEGORY = :cat")
        params["cat"] = category
    if validation_status:
        conditions.append("km.VALIDATION_STATUS = :vstatus")
        params["vstatus"] = validation_status

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.NAME, e.CATEGORY, e.DESCRIPTION,
               km.VALIDATION_STATUS, km.CONFIDENCE,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES e
        LEFT JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return execute_query(sql, params)


def get_statistics() -> Dict[str, Any]:
    sql = """
        SELECT
            (SELECT COUNT(*) FROM ENTITIES WHERE ENTITY_TYPE = 'KNOWLEDGE') AS total_concepts,
            (SELECT COUNT(*) FROM ENTITY_EDGES) AS total_edges,
            (SELECT COUNT(*) FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY') AS total_memories,
            (SELECT COUNT(*) FROM KNOWLEDGE_META WHERE VALIDATION_STATUS = 'VALIDATED') AS validated_concepts
        FROM DUAL
    """
    row = execute_query_one(sql)
    return row or {}


def get_concept_neighbors(entity_id: int, max_depth: int = 2) -> List[Dict[str, Any]]:
    sql = """
        SELECT DISTINCT
            e.ENTITY_ID, e.NAME, e.CATEGORY,
            eg.EDGE_TYPE, eg.STRENGTH,
            CASE WHEN eg.SOURCE_ID = :id THEN 'outgoing' ELSE 'incoming' END AS direction
        FROM ENTITY_EDGES eg
        JOIN ENTITIES e ON (e.ENTITY_ID = CASE WHEN eg.SOURCE_ID = :id THEN eg.TARGET_ID ELSE eg.SOURCE_ID END)
        WHERE (eg.SOURCE_ID = :id OR eg.TARGET_ID = :id)
        ORDER BY eg.STRENGTH DESC
    """
    return execute_query(sql, {"id": entity_id})


def _decorate_concept(row: Dict[str, Any]) -> Dict[str, Any]:
    for json_col in ("tags", "metadata", "source_entity_ids"):
        val = row.get(json_col)
        if isinstance(val, str):
            try:
                row[json_col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                row[json_col] = val
    return row
