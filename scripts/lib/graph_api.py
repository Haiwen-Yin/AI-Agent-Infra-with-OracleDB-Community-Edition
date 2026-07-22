"""AI Agent Infra v4.0.1 - Property Graph API

Database-neutral relational edge traversal, path finding, community detection,
and graph analytics over the shared entity graph contract.
v3.10.0: Universal Property Graph expansion - 30+ functions across 8 domains.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .connection import DATABASE_DIALECT, execute, execute_query, execute_query_one

logger = logging.getLogger(__name__)

GRAPH_NAME = "ORACLE_MEMORY_GRAPH"


def _relational_neighbors(entity_id, direction, edge_type, min_strength, limit):
    results: List[Dict[str, Any]] = []
    if direction in ("outgoing", "both"):
        edge_source = "edge.SOURCE_ID = :eid"
        target_join = "target.ENTITY_ID = edge.TARGET_ID"
        if DATABASE_DIALECT == "postgresql":
            edge_source = "edge.SOURCE_ID = CAST(:eid AS TEXT)"
            target_join = "CAST(target.ENTITY_ID AS TEXT) = edge.TARGET_ID"
        conditions = [edge_source, "edge.STRENGTH >= :strength"]
        params: Dict[str, Any] = {"eid": entity_id, "strength": min_strength, "lim": limit}
        if edge_type:
            conditions.append("edge.EDGE_TYPE = :edge_type")
            params["edge_type"] = edge_type
        rows = execute_query(f"""
            SELECT target.ENTITY_ID AS NEIGHBOR_ID, target.ENTITY_TYPE AS NEIGHBOR_TYPE,
                   target.TITLE AS NEIGHBOR_TITLE, edge.EDGE_ID, edge.EDGE_TYPE,
                   edge.STRENGTH, edge.CONFIDENCE
              FROM ENTITY_EDGES edge
              JOIN ENTITIES target ON {target_join}
             WHERE {' AND '.join(conditions)}
             ORDER BY edge.STRENGTH DESC FETCH FIRST :lim ROWS ONLY
        """, params)
        for row in rows:
            item = _row_to_dict(row)
            item["direction"] = "outgoing"
            results.append(item)
    if direction in ("incoming", "both"):
        edge_target = "edge.TARGET_ID = :eid"
        source_join = "source.ENTITY_ID = edge.SOURCE_ID"
        if DATABASE_DIALECT == "postgresql":
            edge_target = "edge.TARGET_ID = CAST(:eid AS TEXT)"
            source_join = "CAST(source.ENTITY_ID AS TEXT) = edge.SOURCE_ID"
        conditions = [edge_target, "edge.STRENGTH >= :strength"]
        params = {"eid": entity_id, "strength": min_strength, "lim": limit}
        if edge_type:
            conditions.append("edge.EDGE_TYPE = :edge_type")
            params["edge_type"] = edge_type
        rows = execute_query(f"""
            SELECT source.ENTITY_ID AS NEIGHBOR_ID, source.ENTITY_TYPE AS NEIGHBOR_TYPE,
                   source.TITLE AS NEIGHBOR_TITLE, edge.EDGE_ID, edge.EDGE_TYPE,
                   edge.STRENGTH, edge.CONFIDENCE
              FROM ENTITY_EDGES edge
              JOIN ENTITIES source ON {source_join}
             WHERE {' AND '.join(conditions)}
             ORDER BY edge.STRENGTH DESC FETCH FIRST :lim ROWS ONLY
        """, params)
        for row in rows:
            item = _row_to_dict(row)
            item["direction"] = "incoming"
            results.append(item)
    return results[:limit]


def get_neighbors(
    entity_id: str,
    direction: str = "both",
    edge_type: Optional[str] = None,
    min_strength: float = 0.0,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return _relational_neighbors(entity_id, direction, edge_type, min_strength, limit)

    results = []

    if direction in ("outgoing", "both"):
        conditions = ["a.ENTITY_ID = :eid"]
        if edge_type:
            conditions.append("e.EDGE_TYPE = :edge_type")
        if min_strength > 0:
            conditions.append("e.STRENGTH >= :min_strength")
        full_where = " AND ".join(conditions)

        sql = f"""
            SELECT gt.neighbor_id, gt.neighbor_type, gt.neighbor_title,
                   gt.edge_id, gt.edge_type, gt.strength, gt.confidence
            FROM GRAPH_TABLE({GRAPH_NAME}
              MATCH (a IS ENTITIES)-[e]->(b IS ENTITIES)
              WHERE {full_where}
              COLUMNS(
                b.ENTITY_ID AS neighbor_id,
                b.ENTITY_TYPE AS neighbor_type,
                b.TITLE AS neighbor_title,
                e.EDGE_ID AS edge_id,
                e.EDGE_TYPE AS edge_type,
                e.STRENGTH AS strength,
                e.CONFIDENCE AS confidence
              )
            ) gt
            ORDER BY gt.strength DESC
            FETCH FIRST :lim ROWS ONLY
        """
        params: Dict[str, Any] = {"eid": entity_id, "lim": limit}
        if edge_type:
            params["edge_type"] = edge_type
        if min_strength > 0:
            params["min_strength"] = min_strength

        for r in execute_query(sql, params):
            d = _row_to_dict(r)
            d["direction"] = "outgoing"
            results.append(d)

    if direction in ("incoming", "both"):
        conditions = ["a.ENTITY_ID = :eid"]
        if edge_type:
            conditions.append("e.EDGE_TYPE = :edge_type")
        if min_strength > 0:
            conditions.append("e.STRENGTH >= :min_strength")
        full_where = " AND ".join(conditions)

        sql = f"""
            SELECT gt.neighbor_id, gt.neighbor_type, gt.neighbor_title,
                   gt.edge_id, gt.edge_type, gt.strength, gt.confidence
            FROM GRAPH_TABLE({GRAPH_NAME}
              MATCH (a IS ENTITIES)<-[e]-(b IS ENTITIES)
              WHERE {full_where}
              COLUMNS(
                b.ENTITY_ID AS neighbor_id,
                b.ENTITY_TYPE AS neighbor_type,
                b.TITLE AS neighbor_title,
                e.EDGE_ID AS edge_id,
                e.EDGE_TYPE AS edge_type,
                e.STRENGTH AS strength,
                e.CONFIDENCE AS confidence
              )
            ) gt
            ORDER BY gt.strength DESC
            FETCH FIRST :lim ROWS ONLY
        """
        params = {"eid": entity_id, "lim": limit}
        if edge_type:
            params["edge_type"] = edge_type
        if min_strength > 0:
            params["min_strength"] = min_strength

        for r in execute_query(sql, params):
            d = _row_to_dict(r)
            d["direction"] = "incoming"
            results.append(d)

    return results


def get_reachable(
    entity_id: str,
    max_hops: int = 3,
    edge_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    frontier = [entity_id]
    visited = {entity_id}
    result: List[Dict[str, Any]] = []
    for _ in range(max(1, min(int(max_hops), 6))):
        next_frontier = []
        for current in frontier:
            for item in _relational_neighbors(current, "outgoing", edge_type, 0.0, limit):
                neighbor_id = item.get("neighbor_id")
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                next_frontier.append(neighbor_id)
                result.append(item)
                if len(result) >= limit:
                    return result
        frontier = next_frontier
        if not frontier:
            break
    return result

    conditions = [f"a.ENTITY_ID = :eid"]
    if edge_type:
        conditions.append(f"e.EDGE_TYPE = :edge_type")
    full_where = " AND ".join(conditions)

    sql = f"""
        SELECT gt.ENTITY_ID, gt.TITLE, gt.ENTITY_TYPE
        FROM GRAPH_TABLE({GRAPH_NAME}
          MATCH (a IS ENTITIES)-[e]->{{1,{max_hops}}}(v IS ENTITIES)
          WHERE {full_where}
          COLUMNS(v.ENTITY_ID, v.TITLE, v.ENTITY_TYPE)
        ) gt
        FETCH FIRST :lim ROWS ONLY
    """
    params: Dict[str, Any] = {"eid": entity_id, "lim": limit}
    if edge_type:
        params["edge_type"] = edge_type

    return execute_query(sql, params)


def get_shortest_path(
    source_id: str,
    target_id: str,
    max_hops: int = 5,
) -> Optional[List[Dict[str, Any]]]:
    frontier = [(source_id, [{"entity_id": source_id}])]
    visited = {source_id}
    for _ in range(max(1, min(int(max_hops), 6))):
        next_frontier = []
        for current, path in frontier:
            for edge in _relational_neighbors(current, "outgoing", None, 0.0, 100):
                neighbor = edge.get("neighbor_id")
                new_path = path + [{"edge_type": edge.get("edge_type"),
                                    "strength": edge.get("strength")},
                                   {"entity_id": neighbor, "title": edge.get("neighbor_title"),
                                    "entity_type": edge.get("neighbor_type")}]
                if str(neighbor) == str(target_id):
                    return new_path
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append((neighbor, new_path))
        frontier = next_frontier
    return None

    if max_hops < 1:
        max_hops = 1
    if max_hops > 6:
        max_hops = 6

    path_cols = []
    join_clauses = []
    for i in range(1, max_hops + 1):
        path_cols.append(f"v{i}.ENTITY_ID AS hop{i}_id")
        path_cols.append(f"v{i}.TITLE AS hop{i}_title")
        path_cols.append(f"v{i}.ENTITY_TYPE AS hop{i}_type")
        if i < max_hops:
            path_cols.append(f"e{i}.EDGE_TYPE AS hop{i}_edge")
            path_cols.append(f"e{i}.STRENGTH AS hop{i}_strength")

    match_parts = ["(a IS ENTITIES)"]
    for i in range(1, max_hops + 1):
        match_parts.append(f"-[e{i}]->(v{i} IS ENTITIES)")
    match_pattern = "".join(match_parts)

    where_parts = [f"a.ENTITY_ID = :src", f"v{max_hops}.ENTITY_ID = :tgt"]
    full_where = " AND ".join(where_parts)

    sql = f"""
        SELECT {', '.join(path_cols)}
        FROM GRAPH_TABLE({GRAPH_NAME}
          MATCH {match_pattern}
          WHERE {full_where}
          COLUMNS({', '.join(path_cols)})
        ) gt
        FETCH FIRST 1 ROWS ONLY
    """
    params = {"src": source_id, "tgt": target_id}
    row = execute_query_one(sql, params)
    if row is None:
        return None

    path = []
    for i in range(1, max_hops + 1):
        hop_id = row.get(f"hop{i}_id")
        if hop_id is None:
            break
        path.append({
            "entity_id": hop_id,
            "title": row.get(f"hop{i}_title"),
            "entity_type": row.get(f"hop{i}_type"),
        })
        if i < max_hops:
            edge = row.get(f"hop{i}_edge")
            if edge is not None:
                path.append({
                    "edge_type": edge,
                    "strength": row.get(f"hop{i}_strength"),
                })

    return path


def find_similar_entities(
    entity_id: str,
    max_hops: int = 2,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    return get_reachable(entity_id, max_hops=max_hops, limit=limit)

    sql = f"""
        SELECT gt.ENTITY_ID, gt.TITLE, gt.ENTITY_TYPE,
               gt.CATEGORY, gt.IMPORTANCE
        FROM GRAPH_TABLE({GRAPH_NAME}
          MATCH (a IS ENTITIES)-[e]->{{1,{max_hops}}}(v IS ENTITIES)
          WHERE a.ENTITY_ID = :eid AND v.ENTITY_ID <> :eid
          COLUMNS(v.ENTITY_ID, v.TITLE, v.ENTITY_TYPE,
                  v.CATEGORY, v.IMPORTANCE)
        ) gt
        ORDER BY gt.IMPORTANCE DESC
        FETCH FIRST :lim ROWS ONLY
    """
    rows = execute_query(sql, {"eid": entity_id, "lim": limit})
    return [_row_to_dict(r) for r in rows]


def get_entity_context(
    entity_id: str,
    depth: int = 1,
) -> Dict[str, Any]:
    entity = execute_query_one("""
        SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
               IMPORTANCE, VISIBILITY, OWNED_BY_AGENT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM ENTITIES
        WHERE ENTITY_ID = :eid
    """, {"eid": entity_id})

    if entity is None:
        return None

    result = _row_to_dict(entity)

    neighbors = get_neighbors(entity_id, direction="both", limit=50)
    result["neighbors"] = neighbors
    result["neighbor_count"] = len(neighbors)

    neighbor_by_type: Dict[str, List] = {}
    neighbor_by_edge: Dict[str, List] = {}
    for n in neighbors:
        ntype = n.get("neighbor_type", "UNKNOWN")
        neighbor_by_type.setdefault(ntype, []).append(n)
        etype = n.get("edge_type", "UNKNOWN")
        neighbor_by_edge.setdefault(etype, []).append(n)

    result["neighbors_by_type"] = neighbor_by_type
    result["neighbors_by_edge"] = neighbor_by_edge

    return result


def get_graph_stats() -> Dict[str, Any]:
    vertex_count = execute_query_one(
        "SELECT COUNT(*) AS CNT FROM ENTITIES"
    )["cnt"]

    edge_count_row = execute_query_one(
        "SELECT COUNT(*) AS CNT FROM ENTITY_EDGES"
    )
    edge_count = edge_count_row["cnt"] if edge_count_row else 0

    type_dist = execute_query("""
        SELECT ENTITY_TYPE, COUNT(*) AS CNT FROM ENTITIES GROUP BY ENTITY_TYPE
        ORDER BY CNT DESC
    """)

    edge_dist = execute_query("""
        SELECT EDGE_TYPE, COUNT(*) AS CNT
        FROM ENTITY_EDGES
        GROUP BY EDGE_TYPE
        ORDER BY CNT DESC
    """)

    avg_degree_row = execute_query_one("""
        SELECT COALESCE(AVG(deg), 0) AS AVG_DEG FROM (
            SELECT ENTITY_ID, COUNT(*) AS deg
            FROM (
                SELECT SOURCE_ID AS ENTITY_ID FROM ENTITY_EDGES
                UNION ALL
                SELECT TARGET_ID AS ENTITY_ID FROM ENTITY_EDGES
            )
            GROUP BY ENTITY_ID
        )
    """)
    avg_degree = float(avg_degree_row["avg_deg"]) if avg_degree_row else 0.0

    return {
        "vertex_count": vertex_count,
        "edge_count": edge_count,
        "avg_degree": round(avg_degree, 2),
        "entity_type_distribution": {r["entity_type"]: r["cnt"] for r in type_dist},
        "edge_type_distribution": {r["edge_type"]: r["cnt"] for r in edge_dist},
    }


def get_subgraph(
    entity_ids: List[str],
    include_intermediate: bool = False,
) -> Dict[str, Any]:
    if not entity_ids:
        return {"vertices": [], "edges": []}

    placeholders = ", ".join([f":id{i}" for i in range(len(entity_ids))])
    src_placeholders = ", ".join([f":sid{i}" for i in range(len(entity_ids))])
    tgt_placeholders = ", ".join([f":tid{i}" for i in range(len(entity_ids))])
    params = {f"id{i}": eid for i, eid in enumerate(entity_ids)}

    vertices = execute_query(f"""
        SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
               IMPORTANCE, VISIBILITY, OWNED_BY_AGENT
        FROM ENTITIES
        WHERE ENTITY_ID IN ({placeholders})
        ORDER BY ENTITY_TYPE, TITLE
    """, params)

    edge_ids = [str(eid) for eid in entity_ids] if DATABASE_DIALECT == "postgresql" else entity_ids
    edge_params = {**{f"sid{i}": eid for i, eid in enumerate(edge_ids)},
                   **{f"tid{i}": eid for i, eid in enumerate(edge_ids)}}
    edges = execute_query(f"""
        SELECT e.EDGE_ID, e.SOURCE_ID, e.SOURCE_TYPE, e.TARGET_ID,
               e.EDGE_TYPE, e.STRENGTH, e.CONFIDENCE
        FROM ENTITY_EDGES e
        WHERE e.SOURCE_ID IN ({src_placeholders})
           OR e.TARGET_ID IN ({tgt_placeholders})
        ORDER BY e.STRENGTH DESC
    """, edge_params)

    if include_intermediate:
        extra_ids = set()
        for e in edges:
            if e["source_id"] not in entity_ids:
                extra_ids.add(e["source_id"])
            if e["target_id"] not in entity_ids:
                extra_ids.add(e["target_id"])
        if extra_ids:
            extra_ph = ", ".join([f":xid{i}" for i, _ in enumerate(extra_ids)])
            extra_params = {f"xid{i}": eid for i, eid in enumerate(extra_ids)}
            extra_verts = execute_query(f"""
                SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                       IMPORTANCE, VISIBILITY, OWNED_BY_AGENT
                FROM ENTITIES
                WHERE ENTITY_ID IN ({extra_ph})
            """, extra_params)
            vertices.extend(extra_verts)

    return {
        "vertices": [_row_to_dict(v) for v in vertices],
        "edges": [_row_to_dict(e) for e in edges],
    }


def find_communities(
    entity_type: Optional[str] = None,
    min_connections: int = 2,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    type_condition = f"AND e.ENTITY_TYPE = :etype" if entity_type else ""

    source_join = "e2.SOURCE_ID = v.ENTITY_ID"
    target_join = "e3.TARGET_ID = v.ENTITY_ID"
    if DATABASE_DIALECT == "postgresql":
        source_join = "e2.SOURCE_ID = CAST(v.ENTITY_ID AS TEXT)"
        target_join = "e3.TARGET_ID = CAST(v.ENTITY_ID AS TEXT)"
    sql = f"""
        SELECT v.ENTITY_ID, v.TITLE, v.ENTITY_TYPE, v.CATEGORY,
               COUNT(DISTINCT e2.TARGET_ID) + COUNT(DISTINCT e3.SOURCE_ID) AS connection_count
        FROM ENTITIES v
        LEFT JOIN ENTITY_EDGES e2 ON {source_join}
        LEFT JOIN ENTITY_EDGES e3 ON {target_join}
        WHERE 1=1 {type_condition}
        GROUP BY v.ENTITY_ID, v.TITLE, v.ENTITY_TYPE, v.CATEGORY
        HAVING COUNT(DISTINCT e2.TARGET_ID) + COUNT(DISTINCT e3.SOURCE_ID) >= :min_conn
        ORDER BY connection_count DESC
        FETCH FIRST :lim ROWS ONLY
    """
    params: Dict[str, Any] = {"min_conn": min_connections, "lim": limit}
    if entity_type:
        params["etype"] = entity_type

    rows = execute_query(sql, params)
    return [_row_to_dict(r) for r in rows]


def graph_search(
    keyword: Optional[str] = None,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    min_importance: int = 1,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    conditions = ["IMPORTANCE >= :min_imp"]
    params: Dict[str, Any] = {"min_imp": min_importance, "lim": limit}
    if keyword:
        conditions.append("UPPER(TITLE) LIKE UPPER(:kw)")
        params["kw"] = f"%{keyword}%"
    if entity_type:
        conditions.append("ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if category:
        conditions.append("CATEGORY = :cat")
        params["cat"] = category
    rows = execute_query(f"""
        SELECT ENTITY_ID, TITLE, ENTITY_TYPE, CATEGORY, IMPORTANCE, STATUS, VISIBILITY
          FROM ENTITIES WHERE {' AND '.join(conditions)}
         ORDER BY IMPORTANCE DESC FETCH FIRST :lim ROWS ONLY
    """, params)
    return [_row_to_dict(row) for row in rows]

    conditions = [f"a.IMPORTANCE >= :min_imp"]
    params: Dict[str, Any] = {"min_imp": min_importance, "lim": limit}

    if keyword:
        conditions.append("UPPER(a.TITLE) LIKE UPPER(:kw)")
        params["kw"] = f"%{keyword}%"
    if entity_type:
        conditions.append("a.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if category:
        conditions.append("a.CATEGORY = :cat")
        params["cat"] = category

    full_where = " AND ".join(conditions)

    sql = f"""
        SELECT gt.ENTITY_ID, gt.TITLE, gt.ENTITY_TYPE, gt.CATEGORY,
               gt.IMPORTANCE, gt.STATUS, gt.VISIBILITY
        FROM GRAPH_TABLE({GRAPH_NAME}
          MATCH (a IS ENTITIES)
          WHERE {full_where}
          COLUMNS(a.ENTITY_ID, a.TITLE, a.ENTITY_TYPE, a.CATEGORY,
                  a.IMPORTANCE, a.STATUS, a.VISIBILITY)
        ) gt
        ORDER BY gt.IMPORTANCE DESC
        FETCH FIRST :lim ROWS ONLY
    """
    rows = execute_query(sql, params)
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    for k, v in row.items():
        if hasattr(v, 'read'):
            try:
                v = v.read()
            except Exception:
                v = str(v)
        if isinstance(v, bytes):
            try:
                v = v.decode('utf-8')
            except Exception:
                v = v.hex()
        result[k] = v
    return result


# ============================================================
# v3.10.0: Universal Property Graph Expansion
# ============================================================

# --- Generic edge operations ---

def add_edge(source_id, source_type, target_id, edge_type, strength=1.0, confidence=1.0, metadata=None):
    from .connection import execute_insert_returning_id, execute_query_one, execute
    import json as _json
    meta_str = _json.dumps(metadata) if metadata else None
    # v3.10.0: Auto-register source and target as entities if they don't exist (for non-entity types like AGENT_REGISTRY, TASK_STEPS, etc.)
    for eid, etype in [(source_id, source_type), (target_id, source_type)]:
        check = execute_query_one("SELECT ENTITY_ID FROM ENTITIES WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :et", {"eid": str(eid), "et": etype})
        if not check:
            try:
                execute(
                    "INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, SUMMARY, STATUS, VISIBILITY, IMPORTANCE, CREATED_AT, UPDATED_AT) VALUES (:eid, :et, :title, :sum, 'ACTIVE', 'PRIVATE', 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    {"eid": str(eid), "et": etype, "title": str(eid)[:100], "sum": f"Auto-registered {etype}"},
                )
            except Exception:
                pass  # May already exist or partition issue, continue
    return execute_insert_returning_id(
        "INSERT INTO ENTITY_EDGES (EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, METADATA) VALUES ('E_' || AI_NEW_ID(), :sid, :st, :tid, :et, :str, :conf, :meta) RETURNING EDGE_ID INTO :ret_id",
        {"sid": source_id, "st": source_type, "tid": target_id, "et": edge_type, "str": strength, "conf": confidence, "meta": meta_str},
    )

def remove_edge(edge_id):
    from .connection import execute
    return execute("DELETE FROM ENTITY_EDGES WHERE EDGE_ID = :eid", {"eid": edge_id}) > 0

def _get_entity_type(entity_id):
    row = execute_query_one("SELECT ENTITY_TYPE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": entity_id})
    return row["entity_type"] if row else "UNKNOWN"


def _walk_incoming(entity_id: str, edge_types: List[str], depth: int = 3) -> List[Dict[str, Any]]:
    """Database-neutral bounded traversal over ENTITY_EDGES."""
    depth = max(1, min(int(depth), 6))
    frontier = [entity_id]
    visited = {entity_id}
    results: List[Dict[str, Any]] = []
    for hop in range(1, depth + 1):
        next_frontier = []
        for target_id in frontier:
            placeholders = ", ".join(f":type{i}" for i in range(len(edge_types)))
            params = {"target": target_id, **{f"type{i}": value for i, value in enumerate(edge_types)}}
            rows = execute_query(f"""
                SELECT edge.EDGE_ID, edge.SOURCE_ID, edge.SOURCE_TYPE,
                       edge.TARGET_ID, edge.EDGE_TYPE, edge.STRENGTH,
                       entity.TITLE AS SOURCE_TITLE
                  FROM ENTITY_EDGES edge
                  LEFT JOIN ENTITIES entity
                    ON entity.ENTITY_ID = edge.SOURCE_ID
                   AND entity.ENTITY_TYPE = edge.SOURCE_TYPE
                 WHERE edge.TARGET_ID = :target
                   AND edge.EDGE_TYPE IN ({placeholders})
                 ORDER BY edge.STRENGTH DESC
            """, params)
            for row in rows:
                item = _row_to_dict(row)
                item["depth"] = hop
                results.append(item)
                source_id = item.get("source_id")
                if source_id is not None and source_id not in visited:
                    visited.add(source_id)
                    next_frontier.append(source_id)
        frontier = next_frontier
        if not frontier:
            break
    return results


def find_causes(entity_id: str, depth: int = 3) -> List[Dict[str, Any]]:
    return _walk_incoming(entity_id, ["CAUSES", "DEPENDS_ON", "DERIVED_FROM"], depth)


def find_contradictions(entity_id: str) -> List[Dict[str, Any]]:
    rows = execute_query("""
        SELECT edge.EDGE_ID, edge.SOURCE_ID, edge.SOURCE_TYPE, edge.TARGET_ID,
               edge.EDGE_TYPE, edge.STRENGTH, entity.TITLE AS RELATED_TITLE
          FROM ENTITY_EDGES edge
          LEFT JOIN ENTITIES entity
            ON entity.ENTITY_ID = CASE WHEN edge.SOURCE_ID = :eid
                                      THEN edge.TARGET_ID ELSE edge.SOURCE_ID END
         WHERE edge.EDGE_TYPE = 'CONTRADICTS'
           AND (edge.SOURCE_ID = :eid OR edge.TARGET_ID = :eid)
         ORDER BY edge.STRENGTH DESC
    """, {"eid": entity_id})
    return [_row_to_dict(row) for row in rows]


def trace_provenance(entity_id: str, depth: int = 6) -> List[Dict[str, Any]]:
    return _walk_incoming(entity_id, ["DERIVED_FROM", "EXTRACTED_FROM", "CREATED_FROM"], depth)


def trace_data_lineage(entity_id: str) -> Dict[str, Any]:
    access = execute_query("""
        SELECT AGENT_ID, ACCESS_TYPE, ACCESS_TIME
          FROM ENTITY_ACCESS_LOG WHERE ENTITY_ID = :eid
         ORDER BY ACCESS_TIME DESC FETCH FIRST 100 ROWS ONLY
    """, {"eid": entity_id})
    return {
        "entity_id": entity_id,
        "provenance": trace_provenance(entity_id),
        "access_history": [_row_to_dict(row) for row in access],
    }


def get_trusted_agents(agent_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"aid": agent_id}
    group_join = ""
    group_filter = ""
    if group_id:
        group_join = " JOIN COLLAB_GROUP_MEMBERS member ON member.AGENT_ID = related.AGENT_ID "
        group_filter = " AND member.GROUP_ID = :gid AND member.STATUS = 'ACTIVE'"
        params["gid"] = group_id
    rows = execute_query(f"""
        SELECT related.AGENT_ID, related.AGENT_NAME, relation.STRENGTH,
               relation.COL_TYPE, relation.STATUS
          FROM AGENT_COLLABORATION relation
          JOIN AGENT_REGISTRY related
            ON related.AGENT_ID = CASE WHEN relation.SOURCE_AGENT_ID = :aid
                                      THEN relation.TARGET_AGENT_ID ELSE relation.SOURCE_AGENT_ID END
          {group_join}
         WHERE (relation.SOURCE_AGENT_ID = :aid OR relation.TARGET_AGENT_ID = :aid)
           AND relation.STATUS = 'ACTIVE' {group_filter}
         ORDER BY relation.STRENGTH DESC
         FETCH FIRST 50 ROWS ONLY
    """, params)
    return [_row_to_dict(row) for row in rows]


def recommend_collaborators(agent_id: str, group_id: Optional[str] = None) -> List[Dict[str, Any]]:
    trusted = get_trusted_agents(agent_id, group_id)
    existing = {row.get("agent_id") for row in trusted}
    rows = execute_query("""
        SELECT registry.AGENT_ID, registry.AGENT_NAME,
               COALESCE(AVG(capability.CONFIDENCE), 0) AS CAPABILITY_SCORE
          FROM AGENT_REGISTRY registry
          LEFT JOIN AGENT_CAPABILITY_INDEX capability
            ON capability.AGENT_ID = registry.AGENT_ID
         WHERE registry.STATUS = 'ACTIVE' AND registry.AGENT_ID <> :aid
         GROUP BY registry.AGENT_ID, registry.AGENT_NAME
         ORDER BY CAPABILITY_SCORE DESC
         FETCH FIRST 50 ROWS ONLY
    """, {"aid": agent_id})
    return [_row_to_dict(row) for row in rows if row.get("agent_id") not in existing][:10]


def detect_communities():
    """Simple community detection by entity_type grouping."""
    try:
        rows = execute_query(
            "SELECT ENTITY_TYPE, COUNT(*) AS MEMBER_COUNT FROM ENTITIES GROUP BY ENTITY_TYPE ORDER BY MEMBER_COUNT DESC"
        )
        communities = []
        for idx, r in enumerate(rows):
            communities.append({
                "community_id": f"type_{r.get('entity_type', idx)}",
                "label": r.get("entity_type"),
                "member_count": int(r.get("member_count", 0) or 0),
            })
        return communities
    except Exception as e:
        logger.error(f"detect_communities failed: {e}")
        return []


def pagerank(iterations=20, damping=0.85):
    """Compute PageRank scores for all entities using in-memory iteration."""
    try:
        entities = execute_query("SELECT ENTITY_ID, ENTITY_TYPE, TITLE FROM ENTITIES WHERE STATUS = 'ACTIVE'")
        if not entities:
            return []
        
        entity_ids = [e.get('entity_id') or e.get('entity_id') or e.get('ENTITY_ID') for e in entities]
        N = len(entity_ids)
        scores = {eid: 1.0 / N for eid in entity_ids}
        
        for _ in range(iterations):
            new_scores = {}
            for eid in entity_ids:
                incoming = execute_query(
                    'SELECT SOURCE_ID FROM ENTITY_EDGES WHERE TARGET_ID = :tid',
                    {'tid': eid}
                )
                rank_sum = 0.0
                for inc in incoming:
                    src = inc.get('source_id') or inc.get('SOURCE_ID')
                    if src in scores:
                        out_count = execute_query_one(
                            'SELECT COUNT(*) AS cnt FROM ENTITY_EDGES WHERE SOURCE_ID = :sid',
                            {'sid': src}
                        )
                        out_deg = max((out_count.get('cnt') or out_count.get('CNT') or 1) if out_count else 1, 1)
                        rank_sum += scores[src] / out_deg
                new_scores[eid] = (1 - damping) / N + damping * rank_sum
            scores = new_scores
        
        entity_map = {e.get('entity_id') or e.get('entity_id') or e.get('ENTITY_ID'): e for e in entities}
        results = []
        for eid in sorted(entity_ids, key=lambda x: scores[x], reverse=True):
            e = entity_map[eid]
            results.append({
                'ENTITY_ID': eid,
                'ENTITY_TYPE': e.get('entity_type') or e.get('ENTITY_TYPE'),
                'TITLE': e.get('title') or e.get('TITLE'),
                'RANK_SCORE': round(scores[eid], 6),
            })
        return results
    except Exception as e:
        logger.error(f'pagerank failed: {e}')
        return []


# Alias for backward compatibility
shortest_path = get_shortest_path
