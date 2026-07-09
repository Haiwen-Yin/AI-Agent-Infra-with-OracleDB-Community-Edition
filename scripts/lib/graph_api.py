"""AI Agent Infra v3.10.0 - Community Edition - Property Graph API

Core graph operations using GRAPH_TABLE SQL operator against ORACLE_MEMORY_GRAPH.
Provides neighbor traversal, path finding, community detection, and graph analytics.
v3.10.0: Universal Property Graph expansion - 30+ functions across 8 domains.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from .connection import execute, execute_query, execute_query_one

logger = logging.getLogger(__name__)

GRAPH_NAME = "ORACLE_MEMORY_GRAPH"


def get_neighbors(
    entity_id: str,
    direction: str = "both",
    edge_type: Optional[str] = None,
    min_strength: float = 0.0,
    limit: int = 100,
) -> List[Dict[str, Any]]:
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
        SELECT ENTITY_TYPE, COUNT(*) AS CNT
        FROM ENTITIES
        GROUP BY ENTITY_TYPE
        ORDER BY CNT DESC
    """)

    edge_dist = execute_query("""
        SELECT EDGE_TYPE, COUNT(*) AS CNT
        FROM ENTITY_EDGES
        GROUP BY EDGE_TYPE
        ORDER BY CNT DESC
    """)

    avg_degree_row = execute_query_one("""
        SELECT NVL(AVG(deg), 0) AS AVG_DEG FROM (
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

    edge_params = {**{f"sid{i}": eid for i, eid in enumerate(entity_ids)},
                   **{f"tid{i}": eid for i, eid in enumerate(entity_ids)}}
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

    sql = f"""
        SELECT v.ENTITY_ID, v.TITLE, v.ENTITY_TYPE, v.CATEGORY,
               COUNT(DISTINCT e2.TARGET_ID) + COUNT(DISTINCT e3.SOURCE_ID) AS connection_count
        FROM ENTITIES v
        LEFT JOIN ENTITY_EDGES e2 ON e2.SOURCE_ID = v.ENTITY_ID
        LEFT JOIN ENTITY_EDGES e3 ON e3.TARGET_ID = v.ENTITY_ID
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
                    "INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, SUMMARY, STATUS, VISIBILITY, IMPORTANCE, CREATED_AT, UPDATED_AT) VALUES (:eid, :et, :title, :sum, 'ACTIVE', 'PRIVATE', 5, SYSTIMESTAMP, SYSTIMESTAMP)",
                    {"eid": str(eid), "et": etype, "title": str(eid)[:100], "sum": f"Auto-registered {etype}"},
                )
            except Exception:
                pass  # May already exist or partition issue, continue
    return execute_insert_returning_id(
        "INSERT INTO ENTITY_EDGES (EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, METADATA) VALUES ('E_' || RAWTOHEX(SYS_GUID()), :sid, :st, :tid, :et, :str, :conf, :meta) RETURNING EDGE_ID INTO :ret_id",
        {"sid": source_id, "st": source_type, "tid": target_id, "et": edge_type, "str": strength, "conf": confidence, "meta": meta_str},
    )

def remove_edge(edge_id):
    from .connection import execute
    return execute("DELETE FROM ENTITY_EDGES WHERE EDGE_ID = :eid", {"eid": edge_id}) > 0

def _get_entity_type(entity_id):
    row = execute_query_one("SELECT ENTITY_TYPE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": entity_id})
    return row.get("entity_type") if row else None

def _get_trust_config():
    configs = {}
    for key in ['trust_success_delta', 'trust_failure_delta', 'trust_min_threshold', 'trust_max_value', 'trust_initial_coordinator', 'trust_initial_member']:
        row = execute_query_one("SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = :k", {"k": key})
        if row:
            try: configs[key] = float(row.get('config_value', 0))
            except: configs[key] = 0.0
    return configs


# --- 1. Knowledge Causal Graph ---

def add_causal_edge(source_id, target_id, edge_type="CAUSES", metadata=None):
    st = _get_entity_type(source_id) or "KNOWLEDGE"
    return add_edge(source_id, st, target_id, edge_type, strength=0.9, metadata=metadata)

def find_causes(entity_id, depth=3):
    rows = execute_query(
        "SELECT e.TARGET_ID, e.EDGE_TYPE, e.STRENGTH, e.METADATA, e.CREATED_AT, ent.TITLE, ent.ENTITY_TYPE FROM ENTITY_EDGES e JOIN ENTITIES ent ON ent.ENTITY_ID = e.SOURCE_ID WHERE e.TARGET_ID = :eid AND e.EDGE_TYPE = 'CAUSES' FETCH FIRST :limit ROWS ONLY",
        {"eid": entity_id, "limit": depth * 20},
    )
    results = [_row_to_dict(r) for r in rows] if rows else []
    if depth > 1 and results:
        for r in results:
            r['root_causes'] = find_causes(r.get('target_id', ''), depth - 1)
    return results

def find_contradictions(entity_id):
    rows = execute_query(
        "SELECT e.SOURCE_ID, e.TARGET_ID, e.METADATA, e.CREATED_AT, ent.TITLE, ent.ENTITY_TYPE FROM ENTITY_EDGES e JOIN ENTITIES ent ON ent.ENTITY_ID = e.SOURCE_ID WHERE (e.SOURCE_ID = :eid OR e.TARGET_ID = :eid) AND e.EDGE_TYPE = 'CONTRADICTS'",
        {"eid": entity_id},
    )
    return [_row_to_dict(r) for r in rows] if rows else []

def trace_provenance(entity_id, depth=5):
    chain = []
    current_id = entity_id
    for _ in range(depth):
        rows = execute_query(
            "SELECT e.SOURCE_ID, e.EDGE_TYPE, ent.TITLE, ent.ENTITY_TYPE, ent.CATEGORY FROM ENTITY_EDGES e JOIN ENTITIES ent ON ent.ENTITY_ID = e.SOURCE_ID WHERE e.TARGET_ID = :eid AND e.EDGE_TYPE IN ('DERIVED_FROM', 'DERIVED_FROM_DATA', 'SUPERSEDES', 'SUPERSEDED_BY') FETCH FIRST 1 ROWS ONLY",
            {"eid": current_id},
        )
        if not rows:
            break
        r = _row_to_dict(rows[0])
        chain.append(r)
        current_id = str(r.get('source_id', ''))
    return chain

def supersede_knowledge(old_id, new_id, reason=""):
    return add_edge(old_id, "KNOWLEDGE", new_id, "SUPERSEDES", strength=1.0, metadata={"reason": reason} if reason else None)


# --- 2. Agent Collaboration Graph ---

def init_group_trust(agent_id, group_id, coordinator_id, members):
    cfg = _get_trust_config()
    count = 0
    if agent_id != coordinator_id:
        add_edge(agent_id, "AGENT", coordinator_id, "TRUSTS", strength=cfg.get('trust_initial_coordinator', 0.5), metadata={"group_id": group_id})
        count += 1
    for mid in members:
        if mid != agent_id and mid != coordinator_id:
            add_edge(agent_id, "AGENT", mid, "TRUSTS", strength=cfg.get('trust_initial_member', 0.3), metadata={"group_id": group_id})
            count += 1
    return count

def get_trusted_agents(agent_id, group_id, min_strength=None):
    cfg = _get_trust_config()
    if min_strength is None:
        min_strength = cfg.get('trust_min_threshold', 0.3)
    rows = execute_query(
        "SELECT e.TARGET_ID AS agent_id, e.STRENGTH, e.METADATA, e.CREATED_AT FROM ENTITY_EDGES e WHERE e.SOURCE_ID = :aid AND e.EDGE_TYPE = 'TRUSTS' AND e.STRENGTH >= :min_str ORDER BY e.STRENGTH DESC",
        {"aid": agent_id, "min_str": min_strength},
    )
    if not rows:
        return []
    import json as _json
    results = []
    for r in rows:
        d = _row_to_dict(r)
        meta = d.get('metadata', {})
        if isinstance(meta, str):
            try: meta = _json.loads(meta)
            except: meta = {}
        if isinstance(meta, dict) and meta.get('group_id') == group_id:
            if meta.get('status') == 'inactive':
                continue
            results.append(d)
    return results

def update_trust(agent_id, target_id, group_id, success):
    cfg = _get_trust_config()
    delta = cfg.get('trust_success_delta', 0.1) if success else -cfg.get('trust_failure_delta', 0.15)
    max_val = cfg.get('trust_max_value', 1.0)
    row = execute_query_one("SELECT EDGE_ID, STRENGTH FROM ENTITY_EDGES WHERE SOURCE_ID = :aid AND TARGET_ID = :tid AND EDGE_TYPE = 'TRUSTS' AND ROWNUM = 1", {"aid": agent_id, "tid": target_id})
    if not row:
        return False
    new_strength = max(0.0, min(max_val, (row.get('strength') or 0.5) + delta))
    from .connection import execute
    return execute("UPDATE ENTITY_EDGES SET STRENGTH = :str WHERE EDGE_ID = :eid", {"str": new_strength, "eid": row.get('edge_id')}) > 0

def recommend_collaborators(agent_id, group_id, skills=None):
    trusted = get_trusted_agents(agent_id, group_id)
    if not trusted:
        return []
    results = []
    for t in trusted:
        score = t.get('strength', 0.3)
        results.append({"agent_id": t.get('agent_id'), "score": score, "trust": t.get('strength')})
    results.sort(key=lambda x: x['score'], reverse=True)
    return results

def record_delegation(from_agent, to_agent, task_id, group_id=None):
    meta = {"task_id": task_id}
    if group_id: meta["group_id"] = group_id
    return add_edge(from_agent, "AGENT", to_agent, "DELEGATED_TO", metadata=meta)

def find_complementary_agents(agent_id, group_id, skills):
    rows = execute_query("SELECT DISTINCT e.TARGET_ID AS agent_id, e.METADATA FROM ENTITY_EDGES e WHERE e.SOURCE_ID = :aid AND e.EDGE_TYPE = 'COMPLEMENTS_SKILL'", {"aid": agent_id})
    return [_row_to_dict(r) for r in rows] if rows else []


# --- 3. Task Orchestration Graph ---

def record_task_dependency(step_a_id, step_b_id, dependency_type="FEEDS_INTO"):
    return add_edge(step_a_id, "TASK_STEP", step_b_id, dependency_type)

def get_task_lineage(entity_id):
    chain = []
    current_id = entity_id
    for _ in range(10):
        rows = execute_query(
            "SELECT e.SOURCE_ID, e.EDGE_TYPE, ent.TITLE, ent.ENTITY_TYPE FROM ENTITY_EDGES e JOIN ENTITIES ent ON ent.ENTITY_ID = e.SOURCE_ID WHERE e.TARGET_ID = :eid AND e.EDGE_TYPE IN ('PRODUCED_ARTIFACT', 'CONSUMED_ARTIFACT', 'FEEDS_INTO') FETCH FIRST 1 ROWS ONLY",
            {"eid": current_id},
        )
        if not rows: break
        r = _row_to_dict(rows[0])
        chain.append(r)
        current_id = str(r.get('source_id', ''))
    return chain

def find_affected_steps(failed_step_id):
    affected = set()
    queue = [failed_step_id]
    while queue:
        current = queue.pop(0)
        rows = execute_query("SELECT TARGET_ID FROM ENTITY_EDGES WHERE SOURCE_ID = :sid AND EDGE_TYPE = 'FEEDS_INTO'", {"sid": current})
        if rows:
            for r in rows:
                tid = str(r.get('target_id', ''))
                if tid and tid not in affected:
                    affected.add(tid)
                    queue.append(tid)
    return list(affected)

def get_artifact_chain(step_id):
    produced = execute_query("SELECT TARGET_ID, METADATA FROM ENTITY_EDGES WHERE SOURCE_ID = :sid AND EDGE_TYPE = 'PRODUCED_ARTIFACT'", {"sid": step_id})
    consumed = execute_query("SELECT TARGET_ID, METADATA FROM ENTITY_EDGES WHERE SOURCE_ID = :sid AND EDGE_TYPE = 'CONSUMED_ARTIFACT'", {"sid": step_id})
    return {"step_id": step_id, "produced": [_row_to_dict(r) for r in produced] if produced else [], "consumed": [_row_to_dict(r) for r in consumed] if consumed else []}


# --- 4. Skill Dependency Graph ---

def add_skill_dependency(skill_id, required_skill_id):
    source_type = _get_entity_type(skill_id) or "SKILL"
    return add_edge(skill_id, source_type, required_skill_id, "REQUIRES", strength=1.0)

def get_required_skills(skill_id, depth=5):
    required = set()
    queue = [skill_id]
    for _ in range(depth):
        if not queue: break
        current = queue.pop(0)
        rows = execute_query("SELECT TARGET_ID FROM ENTITY_EDGES WHERE SOURCE_ID = :sid AND EDGE_TYPE = 'REQUIRES'", {"sid": current})
        if rows:
            for r in rows:
                tid = str(r.get('target_id', ''))
                if tid and tid not in required:
                    required.add(tid)
                    queue.append(tid)
    return list(required)

def find_skill_gaps(agent_id):
    agent_skills = execute_query("SELECT DISTINCT e.TARGET_ID AS skill_id FROM ENTITY_EDGES e WHERE e.SOURCE_ID = :aid AND e.EDGE_TYPE = 'HAS_SKILL'", {"aid": agent_id})
    if not agent_skills: return []
    gaps = []
    for s in agent_skills:
        sid = str(s.get('skill_id', ''))
        for req_id in get_required_skills(sid):
            has_row = execute_query("SELECT 1 FROM ENTITY_EDGES WHERE SOURCE_ID = :aid AND TARGET_ID = :rid AND EDGE_TYPE = 'HAS_SKILL'", {"aid": agent_id, "rid": req_id})
            if not has_row:
                gaps.append({"missing_skill_id": req_id, "required_by": sid})
    return gaps


# --- 5. Approval Propagation Graph ---

def add_approval_block(approval_id, step_ids):
    count = 0
    for step_id in step_ids:
        add_edge(approval_id, "APPROVAL", step_id, "BLOCKS")
        count += 1
    return count

def cascade_reject(approval_id):
    rows = execute_query("SELECT TARGET_ID FROM ENTITY_EDGES WHERE SOURCE_ID = :aid AND EDGE_TYPE = 'BLOCKS'", {"aid": approval_id})
    if not rows: return []
    from .connection import execute
    blocked = []
    for r in rows:
        step_id = str(r.get('target_id', ''))
        if step_id:
            execute("UPDATE STEP_EXECUTION_PLAN SET STATUS = 'SKIPPED' WHERE STEP_ID = :sid", {"sid": step_id})
            blocked.append(step_id)
    return blocked

def find_approval_bottlenecks(group_id=None):
    rows = execute_query("SELECT e.SOURCE_ID AS approval_id, COUNT(*) AS blocked_count FROM ENTITY_EDGES e WHERE e.EDGE_TYPE = 'BLOCKS' GROUP BY e.SOURCE_ID ORDER BY blocked_count DESC FETCH FIRST 10 ROWS ONLY", {})
    return [_row_to_dict(r) for r in rows] if rows else []


# --- 6. Data Flow (DERIVED_FROM_DATA + existing audit tables) ---

def trace_data_lineage(entity_id):
    graph_chain = trace_provenance(entity_id, depth=5)
    try:
        audit_rows = execute_query("SELECT ACCESSOR_ID, ACCESS_TYPE, ACCESSED_AT FROM ENTITY_ACCESS_AUDIT WHERE ENTITY_ID = :eid ORDER BY ACCESSED_AT DESC FETCH FIRST 20 ROWS ONLY", {"eid": entity_id})
    except Exception:
        audit_rows = None
    return {"entity_id": entity_id, "derivation_chain": graph_chain, "access_history": [_row_to_dict(r) for r in audit_rows] if audit_rows else []}

def find_data_paths(source_agent, target_entity):
    try:
        access_rows = execute_query("SELECT ENTITY_ID, ACCESS_TYPE, ACCESSED_AT FROM ENTITY_ACCESS_AUDIT WHERE ACCESSOR_ID = :aid ORDER BY ACCESSED_AT DESC FETCH FIRST 50 ROWS ONLY", {"aid": source_agent})
    except Exception:
        access_rows = None
    return [_row_to_dict(r) for r in access_rows] if access_rows else []


# --- 7. Memory Evolution Graph ---

def record_promotion(memory_id, knowledge_id):
    return add_edge(memory_id, "MEMORY", knowledge_id, "PROMOTED_TO", strength=1.0)

def record_merge(source_ids, target_id):
    count = 0
    for sid in source_ids:
        add_edge(sid, "MEMORY", target_id, "MERGED_INTO", strength=1.0)
        count += 1
    return count

def trace_memory_origin(entity_id):
    chain = []
    current_id = entity_id
    for _ in range(10):
        rows = execute_query(
            "SELECT e.SOURCE_ID, e.EDGE_TYPE, ent.TITLE, ent.ENTITY_TYPE FROM ENTITY_EDGES e JOIN ENTITIES ent ON ent.ENTITY_ID = e.SOURCE_ID WHERE e.TARGET_ID = :eid AND e.EDGE_TYPE IN ('PROMOTED_TO', 'MERGED_INTO', 'SUPERSEDED_BY') FETCH FIRST 1 ROWS ONLY",
            {"eid": current_id},
        )
        if not rows: break
        r = _row_to_dict(rows[0])
        chain.append(r)
        current_id = str(r.get('source_id', ''))
    return chain


# --- 8. Loop Iteration Graph ---

def record_iteration_link(iter_from, iter_to, link_type="BUILDS_ON", metadata=None):
    return add_edge(str(iter_from), "LOOP_ITERATION", str(iter_to), link_type, metadata=metadata)

def get_iteration_graph(run_id):
    rows = execute_query(
        "SELECT e.SOURCE_ID AS from_iter, e.TARGET_ID AS to_iter, e.EDGE_TYPE, e.METADATA FROM ENTITY_EDGES e WHERE e.EDGE_TYPE IN ('BUILDS_ON', 'INFORMS', 'CORRECTS') AND (e.SOURCE_ID IN (SELECT ITERATION_ID FROM LOOP_ITERATIONS WHERE RUN_ID = :rid) OR e.TARGET_ID IN (SELECT ITERATION_ID FROM LOOP_ITERATIONS WHERE RUN_ID = :rid))",
        {"rid": run_id},
    )
    return [_row_to_dict(r) for r in rows] if rows else []

def find_key_iterations(run_id):
    rows = execute_query(
        "SELECT e.SOURCE_ID AS iteration_id, COUNT(*) AS influence_count FROM ENTITY_EDGES e WHERE e.EDGE_TYPE IN ('INFORMS', 'CORRECTS') AND e.SOURCE_ID IN (SELECT ITERATION_ID FROM LOOP_ITERATIONS WHERE RUN_ID = :rid) GROUP BY e.SOURCE_ID ORDER BY influence_count DESC FETCH FIRST 5 ROWS ONLY",
        {"rid": run_id},
    )
    return [_row_to_dict(r) for r in rows] if rows else []
