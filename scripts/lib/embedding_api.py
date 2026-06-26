"""AI Agent Infra v3.5.0 - Community Edition - Embedding API

Generate, store, and search vector embeddings for entities.
Uses external Embedding API (OpenAI-compatible) + Oracle TO_VECTOR() for storage.
Auto-detects vector dimension from model response.
5-signal unified hybrid search: vector + fulltext (Oracle Text) + relational metadata + graph proximity.
Single-SQL CTE fusion search available via search_unified_sql().
"""

import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one
from .config import get_config

logger = logging.getLogger(__name__)

MODEL_DIMENSIONS = {
    "text-embedding-bge-m3": 1024,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "text-embedding-bge-large-en-v1.5": 1024,
    "text-embedding-bge-small-en-v1.5": 384,
    "all-MiniLM-L6-v2": 384,
    "nomic-embed-text": 768,
    "mxbai-embed-large-v1": 1024,
}


def _get_api_config() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "api_url": cfg.embedding.api_url,
        "model": cfg.embedding.model,
        "dimension": cfg.embedding.dimension,
    }


def _detect_dimension(model: str, api_url: str) -> int:
    if model in MODEL_DIMENSIONS:
        return MODEL_DIMENSIONS[model]
    if not api_url or not model:
        raise ValueError(
            "Embedding model not configured. "
            "Please set embedding.api_url and embedding.model in config.json. "
            "Supported models: " + ", ".join(sorted(MODEL_DIMENSIONS.keys()))
        )
    try:
        result = generate_embedding("dimension probe", api_url=api_url, model=model)
        return len(result)
    except Exception as e:
        logger.warning(f"Cannot auto-detect dimension for {model}: {e}")
        return 1024


def generate_embedding(
    text: str,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 30,
) -> List[float]:
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    cfg = _get_api_config()
    api_url = api_url or cfg["api_url"]
    model = model or cfg["model"]

    payload = json.dumps({"model": model, "input": text}).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))

            if "data" in result and len(result["data"]) > 0:
                embedding = result["data"][0]["embedding"]
                logger.debug(f"Generated embedding: {len(embedding)} dims for '{text[:50]}...'")
                return embedding
            else:
                raise Exception(f"Unexpected API response format: {list(result.keys())}")
    except urllib.error.URLError as e:
        raise Exception(f"Embedding API connection error ({api_url}): {e}")
    except Exception as e:
        raise Exception(f"Error generating embedding: {e}")


def store_embedding(
    entity_id: str,
    entity_type: str,
    text: str,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> bool:
    embedding = generate_embedding(text, api_url=api_url, model=model)

    cfg = _get_api_config()
    model = model or cfg["model"]
    dimension = len(embedding)

    vec_str = json.dumps(embedding)

    sql_check = """
        SELECT COUNT(*) AS C FROM ENTITY_EMBEDDINGS
        WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype
    """
    try:
        row = execute_query_one(sql_check, {"eid": entity_id, "etype": entity_type})
        count = int(list(row.values())[0]) if row else 0

        if count > 0:
            sql = """
                UPDATE ENTITY_EMBEDDINGS
                SET EMBEDDING = TO_VECTOR(:vec),
                    EMBEDDING_MODEL = :model,
                    EMBEDDING_DIM = :dim
                WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype
            """
            execute(sql, {"vec": vec_str, "model": model, "dim": dimension, "eid": entity_id, "etype": entity_type})
        else:
            from .connection import get_connection
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ENTITY_EMBEDDINGS (ENTITY_ID, ENTITY_TYPE, EMBEDDING, EMBEDDING_MODEL, EMBEDDING_DIM, CREATED_AT)
                        VALUES (:eid, :etype, TO_VECTOR(:vec), :model, :dim, SYSTIMESTAMP)
                    """, {"eid": entity_id, "etype": entity_type, "vec": vec_str, "model": model, "dim": dimension})
                    conn.commit()
        logger.info(f"Stored embedding for {entity_type}:{entity_id} ({dimension}d, {model})")
        return True
    except Exception as e:
        logger.error(f"Failed to store embedding for {entity_id}: {e}")
        return False


def store_embedding_vector(
    entity_id: str,
    entity_type: str,
    embedding: List[float],
    model: Optional[str] = None,
) -> bool:
    cfg = _get_api_config()
    model = model or cfg["model"]
    dimension = len(embedding)
    vec_str = json.dumps(embedding)

    sql_check = """
        SELECT COUNT(*) AS C FROM ENTITY_EMBEDDINGS
        WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype
    """
    try:
        row = execute_query_one(sql_check, {"eid": entity_id, "etype": entity_type})
        count = int(list(row.values())[0]) if row else 0

        if count > 0:
            sql = """
                UPDATE ENTITY_EMBEDDINGS
                SET EMBEDDING = TO_VECTOR(:vec),
                    EMBEDDING_MODEL = :model,
                    EMBEDDING_DIM = :dim
                WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype
            """
            execute(sql, {"vec": vec_str, "model": model, "dim": dimension, "eid": entity_id, "etype": entity_type})
        else:
            from .connection import get_connection
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO ENTITY_EMBEDDINGS (ENTITY_ID, ENTITY_TYPE, EMBEDDING, EMBEDDING_MODEL, EMBEDDING_DIM, CREATED_AT)
                        VALUES (:eid, :etype, TO_VECTOR(:vec), :model, :dim, SYSTIMESTAMP)
                    """, {"eid": entity_id, "etype": entity_type, "vec": vec_str, "model": model, "dim": dimension})
                    conn.commit()
        logger.info(f"Stored embedding vector for {entity_type}:{entity_id} ({dimension}d)")
        return True
    except Exception as e:
        logger.error(f"Failed to store embedding vector: {e}")
        return False


def get_embedding(entity_id: str, entity_type: str = "MEMORY") -> Optional[Dict]:
    sql = """
        SELECT ENTITY_ID, ENTITY_TYPE, EMBEDDING_MODEL, EMBEDDING_DIM, CREATED_AT
        FROM ENTITY_EMBEDDINGS
        WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype
    """
    try:
        row = execute_query_one(sql, {"eid": entity_id, "etype": entity_type})
        if row and row.get("entity_id"):
            return {
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "embedding_model": row["embedding_model"],
                "embedding_dim": int(row["embedding_dim"]) if row["embedding_dim"] else None,
                "created_at": str(row["created_at"]) if row.get("created_at") else None,
            }
        return None
    except Exception as e:
        logger.error(f"Failed to get embedding for {entity_id}: {e}")
        return None


def delete_embedding(entity_id: str, entity_type: str = "MEMORY") -> bool:
    sql = "DELETE FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype"
    try:
        execute(sql, {"eid": entity_id, "etype": entity_type})
        return True
    except Exception as e:
        logger.error(f"Failed to delete embedding: {e}")
        return False


def search_similar(
    text: str,
    top_k: int = 10,
    entity_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict]:
    embedding = generate_embedding(text, api_url=api_url, model=model)
    vec_str = json.dumps(embedding)

    conditions = []
    params = {"vec": vec_str, "k": top_k}
    if entity_type:
        conditions.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if workspace_id:
        conditions.append("AND e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    where = " ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CATEGORY,
               VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE) AS distance
        FROM ENTITY_EMBEDDINGS em
        JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID AND e.ENTITY_TYPE = em.ENTITY_TYPE
        WHERE 1=1 {where}
        ORDER BY distance ASC
        FETCH FIRST :k ROWS ONLY
    """

    try:
        rows = execute_query(sql, params)
        results = []
        for row in rows:
            dist = float(row["distance"]) if row.get("distance") is not None else None
            results.append({
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "title": row.get("title", ""),
                "category": row.get("category", ""),
                "distance": dist,
                "similarity": round(1.0 - dist, 4) if dist is not None else None,
            })
        return results
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return []


def generate_embeddings_batch(
    entity_type: str = "MEMORY",
    limit: int = 100,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict:
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT
        FROM ENTITIES e
        WHERE e.ENTITY_TYPE = :etype
          AND NOT EXISTS (
            SELECT 1 FROM ENTITY_EMBEDDINGS em
            WHERE em.ENTITY_ID = e.ENTITY_ID AND em.ENTITY_TYPE = e.ENTITY_TYPE
          )
          AND e.TITLE IS NOT NULL
        ORDER BY e.CREATED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """

    try:
        rows = execute_query(sql, {"etype": entity_type, "lim": limit})
        generated = 0
        failed = 0

        for row in rows:
            eid = row["entity_id"]
            etype = row["entity_type"]
            text = (row.get("title", "") or "") + " " + (row.get("content", "") or "")
            text = text.strip()[:8000]

            if not text:
                continue

            try:
                ok = store_embedding(eid, etype, text, api_url=api_url, model=model)
                if ok:
                    generated += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Batch embedding failed for {eid}: {e}")
                failed += 1

        return {"generated": generated, "failed": failed, "total_candidates": len(rows)}
    except Exception as e:
        logger.error(f"Batch embedding generation failed: {e}")
        return {"generated": 0, "failed": 0, "error": str(e)}


def get_embedding_stats() -> Dict:
    try:
        row = execute_query_one("""
            SELECT COUNT(*) AS total,
                   COUNT(CASE WHEN EMBEDDING IS NOT NULL THEN 1 END) AS with_vector,
                   COUNT(DISTINCT EMBEDDING_MODEL) AS model_count
            FROM ENTITY_EMBEDDINGS
        """)
        if row:
            return {
                "total": int(list(row.values())[0]) if row else 0,
                "with_vector": int(list(row.values())[1]) if row else 0,
                "model_count": int(list(row.values())[2]) if row else 0,
            }
        return {"total": 0, "with_vector": 0, "model_count": 0}
    except Exception as e:
        logger.error(f"Failed to get embedding stats: {e}")
        return {"error": str(e)}


def get_model_dimension(model: Optional[str] = None) -> int:
    cfg = _get_api_config()
    model = model or cfg["model"]

    if model in MODEL_DIMENSIONS:
        return MODEL_DIMENSIONS[model]

    return _detect_dimension(model, cfg["api_url"])


def search_by_entity_id(
    entity_id: str,
    entity_type: str = "MEMORY",
    top_k: int = 10,
    workspace_id: Optional[str] = None,
) -> List[Dict]:
    sql_check = "SELECT COUNT(*) AS C FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype"
    try:
        row = execute_query_one(sql_check, {"eid": entity_id, "etype": entity_type})
        count = int(list(row.values())[0]) if row else 0
        if count == 0:
            return []

        ws_filter = "AND e.WORKSPACE_ID = :wsid" if workspace_id else ""
        sql = f"""
            SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CATEGORY,
                   VECTOR_DISTANCE(em.EMBEDDING,
                       (SELECT EMBEDDING FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype),
                       COSINE) AS distance
            FROM ENTITY_EMBEDDINGS em
            JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID AND e.ENTITY_TYPE = em.ENTITY_TYPE
            WHERE em.ENTITY_ID != :eid {ws_filter}
            ORDER BY distance ASC
            FETCH FIRST :k ROWS ONLY
        """
        params = {"eid": entity_id, "etype": entity_type, "k": top_k}
        if workspace_id:
            params["wsid"] = workspace_id

        rows = execute_query(sql, params)
        results = []
        for r in rows:
            dist = float(r["distance"]) if r.get("distance") is not None else None
            results.append({
                "entity_id": r["entity_id"],
                "entity_type": r["entity_type"],
                "title": r.get("title", ""),
                "category": r.get("category", ""),
                "distance": dist,
                "similarity": round(1.0 - dist, 4) if dist is not None else None,
            })
        return results
    except Exception as e:
        logger.error(f"Entity-based vector search failed: {e}")
        return []


def search_hybrid(
    text: str,
    keyword: Optional[str] = None,
    top_k: int = 10,
    entity_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    vector_weight: float = 0.7,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict]:
    embedding = generate_embedding(text, api_url=api_url, model=model)
    vec_str = json.dumps(embedding)

    conditions = []
    params = {"vec": vec_str, "k": top_k}
    if entity_type:
        conditions.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if workspace_id:
        conditions.append("AND e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id
    if keyword:
        conditions.append("AND (UPPER(e.TITLE) LIKE '%' || UPPER(:kw) || '%' OR UPPER(e.CATEGORY) LIKE '%' || UPPER(:kw) || '%')")
        params["kw"] = keyword.upper()

    where = " ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CATEGORY,
               VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE) AS distance
        FROM ENTITY_EMBEDDINGS em
        JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID AND e.ENTITY_TYPE = em.ENTITY_TYPE
        WHERE 1=1 {where}
        ORDER BY distance ASC
        FETCH FIRST :k ROWS ONLY
    """

    try:
        rows = execute_query(sql, params)
        results = []
        for r in rows:
            dist = float(r["distance"]) if r.get("distance") is not None else None
            vec_score = max(0, 1.0 - dist) * vector_weight if dist is not None else 0
            kw_score = (1.0 - vector_weight) if keyword and (
                keyword.upper() in (r.get("title", "") or "").upper() or
                keyword.upper() in (r.get("category", "") or "").upper()
            ) else 0
            results.append({
                "entity_id": r["entity_id"],
                "entity_type": r["entity_type"],
                "title": r.get("title", ""),
                "category": r.get("category", ""),
                "distance": dist,
                "vector_score": round(vec_score, 4),
                "keyword_score": round(kw_score, 4),
                "hybrid_score": round(vec_score + kw_score, 4),
            })
        results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return results
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        return []


def search_multi_type(
    text: str,
    entity_types: Optional[List[str]] = None,
    top_k: int = 10,
    workspace_id: Optional[str] = None,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    if entity_types is None:
        entity_types = ["MEMORY", "KNOWLEDGE", "SPEC"]

    results = {}
    for etype in entity_types:
        results[etype] = search_similar(
            text, top_k=top_k, entity_type=etype, workspace_id=workspace_id,
            api_url=api_url, model=model,
        )
    return results


def search_fulltext(
    query: str,
    top_k: int = 20,
    entity_type: Optional[str] = None,
    category: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> List[Dict]:
    if not query or not query.strip():
        return []

    params: Dict[str, Any] = {"ftq": query, "k": top_k}
    conditions = []

    if entity_type:
        conditions.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if category:
        conditions.append("AND e.CATEGORY = :cat")
        params["cat"] = category
    if workspace_id:
        conditions.append("AND e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    where = " ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.CATEGORY,
               SCORE(1) AS ft_score
        FROM ENTITIES e
        WHERE CONTAINS(e.TITLE, :ftq, 1) > 0 {where}
        ORDER BY ft_score DESC
        FETCH FIRST :k ROWS ONLY
    """

    try:
        rows = execute_query(sql, params)
        results = []
        for r in rows:
            score = float(r["ft_score"]) if r.get("ft_score") else 0
            results.append({
                "entity_id": r["entity_id"],
                "entity_type": r["entity_type"],
                "title": r.get("title", ""),
                "content": r.get("content", "")[:200] if r.get("content") else "",
                "category": r.get("category", ""),
                "ft_score": round(score / 100.0, 4),
            })
        return results
    except Exception as e:
        logger.error(f"Full-text search failed: {e}")
        return []


def search_unified(
    text: str,
    top_k: int = 20,
    entity_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    graph_seed_entity_id: Optional[str] = None,
    graph_seed_entity_type: Optional[str] = None,
    graph_depth: int = 2,
    vector_weight: float = 0.4,
    fulltext_weight: float = 0.25,
    relational_weight: float = 0.2,
    graph_weight: float = 0.15,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict]:
    embedding = generate_embedding(text, api_url=api_url, model=model)
    vec_str = json.dumps(embedding)

    params: Dict[str, Any] = {"vec": vec_str, "ftq": text, "k": top_k * 3}
    conditions = []

    if entity_type:
        conditions.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if workspace_id:
        conditions.append("AND e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    where = " ".join(conditions)

    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.CATEGORY, e.IMPORTANCE,
               e.WORKSPACE_ID,
               VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE) AS vec_distance,
               CASE WHEN CONTAINS(e.TITLE, :ftq, 1) > 0 THEN SCORE(1) ELSE 0 END AS ft_score,
               km.DOMAIN AS km_domain, km.TOPIC AS km_topic, km.DIFFICULTY AS km_difficulty,
               sm.SPEC_SCOPE AS sm_scope, sm.COMPLEXITY AS sm_complexity, sm.SPEC_STATUS AS sm_spec_status
        FROM ENTITY_EMBEDDINGS em
        JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID AND e.ENTITY_TYPE = em.ENTITY_TYPE
        LEFT JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID AND km.ENTITY_TYPE = e.ENTITY_TYPE
        LEFT JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE 1=1 {where}
        ORDER BY vec_distance ASC
        FETCH FIRST :k ROWS ONLY
    """

    try:
        rows = execute_query(sql, params)
    except Exception as e:
        logger.error(f"Unified search vector+fulltext phase failed: {e}")
        return []

    eid_set = {r["entity_id"] for r in rows}
    eid_list = list(eid_set)

    tag_map: Dict[str, List[str]] = {}
    if eid_list and tags:
        tag_pairs = _batch_get_tags(eid_list)
        for eid, tag_name in tag_pairs:
            tag_map.setdefault(eid, []).append(tag_name)

    graph_neighbors: Dict[str, float] = {}
    if graph_seed_entity_id and eid_list:
        graph_neighbors = _batch_graph_proximity(graph_seed_entity_id, graph_seed_entity_type or "MEMORY", eid_list, graph_depth)

    edge_counts: Dict[str, int] = {}
    if eid_list:
        edge_counts = _batch_edge_counts(eid_list)

    results = []
    text_lower = text.lower()

    for r in rows:
        eid = r["entity_id"]
        etype = r["entity_type"]

        vec_dist = float(r["vec_distance"]) if r.get("vec_distance") is not None else 1.0
        vec_score = max(0.0, 1.0 - vec_dist)

        ft_raw = float(r["ft_score"]) if r.get("ft_score") else 0
        ft_score = min(ft_raw / 100.0, 1.0)

        rel_score = _relational_score(
            r.get("km_domain"), r.get("km_topic"), r.get("km_difficulty"),
            r.get("sm_scope"), r.get("sm_complexity"), r.get("sm_spec_status"),
            r.get("category"), r.get("importance"),
            domain, category, text_lower,
        )

        tag_score = _tag_score(tag_map.get(eid, []), tags or [], text_lower)

        graph_score = graph_neighbors.get(eid, 0.0)

        connectivity_boost = min(edge_counts.get(eid, 0) / 10.0, 0.1)

        final_score = (
            vector_weight * vec_score
            + fulltext_weight * ft_score
            + relational_weight * (rel_score + tag_score) / 2.0
            + graph_weight * (graph_score + connectivity_boost) / 2.0
        )
        final_score = min(final_score, 1.0)

        results.append({
            "entity_id": eid,
            "entity_type": etype,
            "title": r.get("title", ""),
            "category": r.get("category", ""),
            "importance": int(r["importance"]) if r.get("importance") else None,
            "workspace_id": r.get("workspace_id"),
            "km_domain": r.get("km_domain"),
            "km_topic": r.get("km_topic"),
            "km_difficulty": r.get("km_difficulty"),
            "sm_scope": r.get("sm_scope"),
            "sm_complexity": r.get("sm_complexity"),
            "tags": tag_map.get(eid, []),
            "edge_count": edge_counts.get(eid, 0),
            "graph_proximity": round(graph_score, 4),
            "scores": {
                "vector": round(vec_score, 4),
                "fulltext": round(ft_score, 4),
                "relational": round(rel_score, 4),
                "tag": round(tag_score, 4),
                "graph": round(graph_score, 4),
            },
            "final_score": round(final_score, 4),
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:top_k]


def search_unified_sql(
    text: str,
    top_k: int = 20,
    entity_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    graph_seed_entity_id: Optional[str] = None,
    graph_seed_entity_type: Optional[str] = None,
    graph_depth: int = 2,
    vector_weight: float = 0.4,
    fulltext_weight: float = 0.25,
    relational_weight: float = 0.2,
    graph_weight: float = 0.15,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict]:
    embedding = generate_embedding(text, api_url=api_url, model=model)
    vec_str = json.dumps(embedding)

    params: Dict[str, Any] = {
        "vec": vec_str,
        "ftq": text,
        "k": top_k * 3,
        "topk": top_k,
        "vw": vector_weight,
        "fw": fulltext_weight,
        "rw": relational_weight,
        "gw": graph_weight,
    }

    filter_conds = []
    if entity_type:
        filter_conds.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if workspace_id:
        filter_conds.append("AND e.WORKSPACE_ID = :wsid")
        params["wsid"] = workspace_id

    filter_where = " ".join(filter_conds)

    tag_join_cte = ""
    tag_select_score = "0 AS tag_score"

    if tags:
        tag_placeholders = ", ".join([f":tg{i}" for i in range(len(tags))])
        for i, t in enumerate(tags):
            params[f"tg{i}"] = t

        tag_join_cte = f""",
tag_scores AS (
    SELECT et.ENTITY_ID,
           COUNT(CASE WHEN t.TAG_NAME IN ({tag_placeholders}) THEN 1 END) AS matched_tags,
           COUNT(*) AS total_tags
    FROM ENTITY_TAGS et
    JOIN TAGS t ON t.TAG_ID = et.TAG_ID
    WHERE et.ENTITY_ID IN (SELECT ENTITY_ID FROM candidates)
    GROUP BY et.ENTITY_ID
)"""
        tag_select_score = "CASE WHEN ts.total_tags > 0 THEN NVL(ts.matched_tags, 0) / ts.total_tags ELSE 0 END AS tag_score"

    graph_cte = ""
    graph_join = ""
    graph_select = "0 AS graph_proximity"

    if graph_seed_entity_id:
        params["gsid"] = graph_seed_entity_id
        depth2_join = ""
        if graph_depth >= 2:
            depth2_join = """
            UNION ALL
            SELECT e2.TARGET_ID AS ENTITY_ID, 0.5 AS proximity
            FROM ENTITY_EDGES e1
            JOIN ENTITY_EDGES e2 ON e2.SOURCE_ID = e1.TARGET_ID
            WHERE e1.SOURCE_ID = :gsid
              AND e2.TARGET_ID IN (SELECT ENTITY_ID FROM candidates)
              AND e2.TARGET_ID != :gsid"""

        graph_cte = f""",
graph_prox AS (
    SELECT TARGET_ID AS ENTITY_ID, 1.0 AS proximity
    FROM ENTITY_EDGES
    WHERE SOURCE_ID = :gsid
      AND TARGET_ID IN (SELECT ENTITY_ID FROM candidates){depth2_join}
)"""
        graph_join = "LEFT JOIN (SELECT ENTITY_ID, MAX(proximity) AS proximity FROM graph_prox GROUP BY ENTITY_ID) gp ON gp.ENTITY_ID = c.ENTITY_ID"
        graph_select = "NVL(gp.proximity, 0) AS graph_proximity"

    tag_join_left = "LEFT JOIN tag_scores ts ON ts.ENTITY_ID = c.ENTITY_ID" if tags else ""
    graph_join_left = graph_join if graph_seed_entity_id else ""

    rel_score_expr = "0"
    if domain:
        params["fdomain"] = domain.lower()
        rel_score_expr = f"CASE WHEN LOWER(c.km_domain) = :fdomain THEN 0.5 ELSE 0 END"
    if category:
        params["fcat"] = category.lower()
        existing = rel_score_expr
        rel_score_expr = f"{existing} + CASE WHEN LOWER(c.CATEGORY) = :fcat THEN 0.3 ELSE 0 END"

    importance_part = "NVL(c.IMPORTANCE, 0) / 100.0"
    rel_score_expr = f"LEAST({rel_score_expr} + {importance_part}, 1.0)"

    tag_final_expr = tag_select_score if tags else "0 AS tag_score"
    graph_final_expr = graph_select if graph_seed_entity_id else "0 AS graph_proximity"

    final_score_expr = (
        f":vw * (1 - c.vec_distance)"
        f" + :fw * CASE WHEN c.ft_raw > 0 THEN LEAST(c.ft_raw / 100.0, 1.0) ELSE 0 END"
        f" + :rw * ({rel_score_expr} + {tag_final_expr.replace(' AS tag_score', '')}) / 2.0"
        f" + :gw * ({graph_final_expr.replace(' AS graph_proximity', '')} + LEAST(NVL(ec.edge_count, 0) / 10.0, 0.1)) / 2.0"
    )

    sql = f"""
WITH candidates AS (
    SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.CATEGORY, e.IMPORTANCE,
           e.WORKSPACE_ID,
           VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE) AS vec_distance,
           CASE WHEN CONTAINS(e.TITLE, :ftq, 1) > 0 THEN SCORE(1) ELSE 0 END AS ft_raw,
           km.DOMAIN AS km_domain, km.TOPIC AS km_topic, km.DIFFICULTY AS km_difficulty,
           sm.SPEC_SCOPE AS sm_scope, sm.COMPLEXITY AS sm_complexity, sm.SPEC_STATUS AS sm_spec_status
    FROM ENTITY_EMBEDDINGS em
    JOIN ENTITIES e ON e.ENTITY_ID = em.ENTITY_ID AND e.ENTITY_TYPE = em.ENTITY_TYPE
    LEFT JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID AND km.ENTITY_TYPE = e.ENTITY_TYPE
    LEFT JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID AND sm.ENTITY_TYPE = e.ENTITY_TYPE
    WHERE 1=1 {filter_where}
    ORDER BY vec_distance ASC
    FETCH FIRST :k ROWS ONLY
),
edge_counts AS (
    SELECT SOURCE_ID AS ENTITY_ID, COUNT(*) AS edge_count
    FROM ENTITY_EDGES
    WHERE SOURCE_ID IN (SELECT ENTITY_ID FROM candidates)
    GROUP BY SOURCE_ID
){tag_join_cte}{graph_cte}
SELECT c.ENTITY_ID, c.ENTITY_TYPE, c.TITLE, c.CATEGORY, c.IMPORTANCE,
       c.WORKSPACE_ID, c.km_domain, c.km_topic, c.km_difficulty,
       c.sm_scope, c.sm_complexity, c.sm_spec_status,
       (1 - c.vec_distance) AS vec_score,
       CASE WHEN c.ft_raw > 0 THEN LEAST(c.ft_raw / 100.0, 1.0) ELSE 0 END AS ft_score,
       LEAST({rel_score_expr}, 1.0) AS rel_score,
       {tag_final_expr},
       NVL(ec.edge_count, 0) AS edge_count,
       {graph_final_expr},
       LEAST({final_score_expr}, 1.0) AS final_score
FROM candidates c
LEFT JOIN edge_counts ec ON ec.ENTITY_ID = c.ENTITY_ID
{tag_join_left}
{graph_join_left}
ORDER BY final_score DESC
FETCH FIRST :topk ROWS ONLY
"""

    try:
        rows = execute_query(sql, params)
    except Exception as e:
        logger.error(f"search_unified_sql failed: {e}")
        return []

    tag_map: Dict[str, List[str]] = {}
    if rows and tags:
        eid_list = [r["entity_id"] for r in rows]
        tag_pairs = _batch_get_tags(eid_list)
        for eid, tag_name in tag_pairs:
            tag_map.setdefault(eid, []).append(tag_name)

    results = []
    for r in rows:
        eid = r["entity_id"]
        vec_score = float(r.get("vec_score", 0) or 0)
        ft_score = float(r.get("ft_score", 0) or 0)
        rel_score = float(r.get("rel_score", 0) or 0)
        tg_score = float(r.get("tag_score", 0) or 0)
        graph_prox = float(r.get("graph_proximity", 0) or 0)
        final_score = float(r.get("final_score", 0) or 0)

        results.append({
            "entity_id": eid,
            "entity_type": r.get("entity_type", ""),
            "title": r.get("title", ""),
            "category": r.get("category", ""),
            "importance": int(r["importance"]) if r.get("importance") else None,
            "workspace_id": r.get("workspace_id"),
            "km_domain": r.get("km_domain"),
            "km_topic": r.get("km_topic"),
            "km_difficulty": r.get("km_difficulty"),
            "sm_scope": r.get("sm_scope"),
            "sm_complexity": r.get("sm_complexity"),
            "tags": tag_map.get(eid, []),
            "edge_count": int(r.get("edge_count", 0) or 0),
            "graph_proximity": round(graph_prox, 4),
            "scores": {
                "vector": round(vec_score, 4),
                "fulltext": round(ft_score, 4),
                "relational": round(rel_score, 4),
                "tag": round(tg_score, 4),
                "graph": round(graph_prox, 4),
            },
            "final_score": round(final_score, 4),
            "engine": "single_sql",
        })

    return results


def _keyword_score(query_lower: str, query_words: set, title: str, content: str, category: str) -> float:
    title_lower = (title or "").lower()
    content_lower = (content or "").lower()
    category_lower = (category or "").lower()

    score = 0.0
    matched = 0
    for w in query_words:
        if len(w) < 2:
            continue
        if w in title_lower:
            score += 0.5
            matched += 1
        elif w in content_lower:
            score += 0.2
            matched += 1
        if w in category_lower:
            score += 0.3
            matched += 1

    if not query_words:
        return 0.0
    coverage = matched / (len(query_words) * 3) if query_words else 0
    return min(score / len(query_words), 1.0) * 0.7 + coverage * 0.3


def _relational_score(
    km_domain: Optional[str], km_topic: Optional[str], km_difficulty: Optional[str],
    sm_scope: Optional[str], sm_complexity: Optional[str], sm_spec_status: Optional[str],
    category: Optional[str], importance: Optional[Any],
    filter_domain: Optional[str], filter_category: Optional[str],
    query_lower: str,
) -> float:
    score = 0.0

    if filter_domain:
        if km_domain and km_domain.lower() == filter_domain.lower():
            score += 0.4
        if sm_scope and sm_scope.lower() == filter_domain.lower():
            score += 0.4

    if filter_category:
        if category and category.lower() == filter_category.lower():
            score += 0.3

    if km_domain and km_domain.lower() in query_lower:
        score += 0.2
    if km_topic and km_topic.lower() in query_lower:
        score += 0.2
    if sm_scope and sm_scope.lower() in query_lower:
        score += 0.2

    if importance:
        try:
            score += min(int(importance) / 10.0, 1.0) * 0.1
        except (ValueError, TypeError):
            pass

    return min(score, 1.0)


def _tag_score(entity_tags: List[str], filter_tags: List[str], query_lower: str) -> float:
    if not entity_tags and not filter_tags:
        return 0.0

    score = 0.0
    if filter_tags:
        filter_lower = {t.lower() for t in filter_tags}
        entity_lower = {t.lower() for t in entity_tags}
        overlap = len(filter_lower & entity_lower)
        if overlap > 0:
            score += min(overlap / len(filter_lower), 1.0) * 0.5

    for tag in entity_tags:
        if tag.lower() in query_lower:
            score += 0.3
            break

    return min(score, 1.0)


def _batch_get_tags(entity_ids: List[str]) -> List[tuple]:
    if not entity_ids:
        return []
    try:
        placeholders = ", ".join([f":eid{i}" for i in range(len(entity_ids))])
        params = {f"eid{i}": eid for i, eid in enumerate(entity_ids)}
        sql = f"""
            SELECT et.ENTITY_ID, t.TAG_NAME
            FROM ENTITY_TAGS et
            JOIN TAGS t ON t.TAG_ID = et.TAG_ID
            WHERE et.ENTITY_ID IN ({placeholders})
        """
        rows = execute_query(sql, params)
        return [(r["entity_id"], r["tag_name"]) for r in rows]
    except Exception as e:
        logger.debug(f"Batch tag query failed: {e}")
        return []


def _batch_graph_proximity(
    seed_id: str, seed_type: str, candidate_ids: List[str], max_depth: int = 2
) -> Dict[str, float]:
    if not candidate_ids:
        return {}
    try:
        proximity: Dict[str, float] = {}
        candidate_set = set(candidate_ids)
        visited = set()
        current_frontier = {seed_id}

        for depth in range(1, max_depth + 1):
            next_frontier = set()
            if not current_frontier:
                break

            placeholders = ", ".join([f":fid{i}" for i in range(len(current_frontier))])
            params = {f"fid{i}": fid for i, fid in enumerate(current_frontier)}

            sql = f"""
                SELECT SOURCE_ID, TARGET_ID FROM ENTITY_EDGES
                WHERE SOURCE_ID IN ({placeholders})
            """
            try:
                rows = execute_query(sql, params)
            except Exception:
                break

            for r in rows:
                src = r.get("source_id")
                tgt = r.get("target_id")
                if src and src not in visited:
                    next_frontier.add(src)
                if tgt and tgt in candidate_set and tgt not in visited:
                    old = proximity.get(tgt, 0)
                    score = 1.0 / depth
                    proximity[tgt] = max(old, score)
                if tgt and tgt not in visited:
                    next_frontier.add(tgt)

            visited.update(current_frontier)
            current_frontier = next_frontier - visited

        return proximity
    except Exception as e:
        logger.debug(f"Graph proximity computation failed: {e}")
        return {}


def _batch_edge_counts(entity_ids: List[str]) -> Dict[str, int]:
    if not entity_ids:
        return {}
    try:
        placeholders = ", ".join([f":eid{i}" for i in range(len(entity_ids))])
        params = {f"eid{i}": eid for i, eid in enumerate(entity_ids)}
        sql = f"""
            SELECT SOURCE_ID AS ENTITY_ID, COUNT(*) AS CNT
            FROM ENTITY_EDGES WHERE SOURCE_ID IN ({placeholders})
            GROUP BY SOURCE_ID
        """
        rows = execute_query(sql, params)
        return {r["entity_id"]: int(list(r.values())[1]) for r in rows}
    except Exception as e:
        logger.debug(f"Batch edge count query failed: {e}")
        return {}


# -- D4: Advanced Embedding Management (v3.7.4) --

def reindex_entity(entity_id: str) -> bool:
    """Re-generate embedding for a single entity."""
    from .connection import execute_query_one, execute
    entity = execute_query_one(
        "SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT FROM ENTITIES WHERE ENTITY_ID = :eid",
        {"eid": entity_id},
    )
    if not entity:
        return False
    text = (entity.get("title", "") + " " + entity.get("content", "")).strip()
    if not text:
        return False
    try:
        embedding = generate_embedding(text)
        store_embedding(entity_id, entity.get("entity_type", "MEMORY"), embedding)
        return True
    except Exception as e:
        logger.error("reindex_entity failed for %s: %s", entity_id, e)
        return False


def queue_reindex(entity_id: str, priority: int = 0) -> bool:
    """Queue an entity for re-indexing."""
    from .connection import execute_insert
    execute_insert(
        """INSERT INTO SYSTEM_CONFIG (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
           VALUES (:key, :val, :desc)""",
        {"key": f"reindex_{entity_id}", "val": str(priority),
         "desc": f"Pending reindex for entity {entity_id}"},
    )
    return True


def reindex_batch(entity_ids: List[str]) -> Dict[str, int]:
    """Re-index multiple entities."""
    success = 0
    failed = 0
    for eid in entity_ids:
        if reindex_entity(eid):
            success += 1
        else:
            failed += 1
    return {"success": success, "failed": failed}
