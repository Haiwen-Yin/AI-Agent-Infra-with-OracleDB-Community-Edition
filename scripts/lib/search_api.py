"""AI Agent Infra v4.0.0 - Enterprise Edition - Unified Search API

Single entry point for AI agents to search across all data types and modalities.
Agents choose search strategy based on scenario:

- "vector"       - Semantic similarity via VECTOR_DISTANCE (best for meaning/concept search)
- "fulltext"     - Oracle Text CONTAINS+SCORE (best for exact keyword/phrase search)
- "keyword"      - SQL LIKE pattern matching (best for partial/wildcard match)
- "graph"        - Property graph traversal (best for relationship/neighborhood queries)
- "hybrid"       - Vector + Fulltext dual scoring (best for general semantic+lexical)
- "unified"      - 5-signal fusion: vector+fulltext+relational+tag+graph (comprehensive)
- "unified_sql"  - Single-SQL CTE 5-signal fusion (same as unified, low-latency single query)
- "relational"   - Structured metadata filter on domain/category/tags/importance
- "multi_type"   - Cross-type vector search (MEMORY/KNOWLEDGE/SPEC in one call)
- "auto"         - Automatically selects strategy based on query characteristics

Usage:
    from lib.search_api import search, list_search_strategies, describe_search_strategy

    results = search("database partitioning", strategy="unified", top_k=10)
    results = search("encryption", strategy="fulltext", entity_type="KNOWLEDGE")
    results = search("partition*", strategy="keyword")
    results = search("architecture", strategy="vector", domain="database")
    results = search("security", strategy="auto")
    results = search("memory leak", strategy="hybrid", explain=True)  # add _explanation per hit
"""

import logging
from typing import Any, Dict, List, Optional

from . import embedding_api, memory_api, knowledge_api, graph_api
from .connection import execute_query, execute_query_one

logger = logging.getLogger(__name__)

STRATEGIES = {
    "vector": {
        "name": "Vector Similarity Search",
        "description": "Semantic similarity via VECTOR_DISTANCE(COSINE). Best for meaning/concept search, finding related content even without exact keyword match.",
        "signals": ["vector"],
        "best_for": ["semantic search", "concept matching", "finding similar content", "cross-lingual", "paraphrase detection"],
        "requires_embedding": True,
        "supports_filters": ["entity_type", "workspace_id"],
        "speed": "medium",
        "precision": "high",
    },
    "fulltext": {
        "name": "Oracle Text Full-Text Search",
        "description": "Oracle Text CONTAINS with SCORE ranking. Best for exact keyword/phrase search with linguistic features (stemming, boolean, fuzzy).",
        "signals": ["fulltext"],
        "best_for": ["exact keyword", "phrase search", "boolean queries (AND/OR/NOT)", "stemmed forms", "large corpus ranking"],
        "requires_embedding": False,
        "supports_filters": ["entity_type", "category", "workspace_id"],
        "speed": "fast",
        "precision": "high",
    },
    "keyword": {
        "name": "SQL LIKE Pattern Matching",
        "description": "Simple SQL LIKE pattern matching on title/content. Best for partial match, wildcard, or when Oracle Text index is unavailable.",
        "signals": ["keyword"],
        "best_for": ["partial match", "wildcard patterns", "simple filtering", "small result sets"],
        "requires_embedding": False,
        "supports_filters": ["entity_type", "category", "workspace_id", "visibility", "owned_by_agent"],
        "speed": "slow",
        "precision": "low",
    },
    "graph": {
        "name": "Property Graph Search",
        "description": "Graph traversal via edge BFS. Best for finding connected entities, neighborhood exploration, path finding.",
        "signals": ["graph"],
        "best_for": ["relationship queries", "neighborhood exploration", "path finding", "community detection", "influence analysis"],
        "requires_embedding": False,
        "supports_filters": ["entity_type", "edge_type", "min_strength", "depth"],
        "speed": "medium",
        "precision": "medium",
    },
    "hybrid": {
        "name": "Vector + Fulltext Hybrid",
        "description": "Combines vector similarity with Oracle Text scoring. Best for general-purpose search needing both semantic and lexical signals.",
        "signals": ["vector", "fulltext"],
        "best_for": ["general search", "semantic + keyword", "best of both worlds", "balanced relevance"],
        "requires_embedding": True,
        "supports_filters": ["entity_type", "workspace_id", "vector_weight", "fulltext_weight"],
        "speed": "medium",
        "precision": "high",
    },
    "unified": {
        "name": "5-Signal Unified Search",
        "description": "Full fusion: vector + fulltext + relational metadata + tag + graph proximity. Best for comprehensive multi-dimensional retrieval.",
        "signals": ["vector", "fulltext", "relational", "tag", "graph"],
        "best_for": ["comprehensive search", "multi-dimensional ranking", "domain-specific retrieval", "context-aware search", "AI agent decision making"],
        "requires_embedding": True,
        "supports_filters": ["entity_type", "workspace_id", "domain", "category", "tags", "graph_seed_entity_id", "all weights"],
        "speed": "slow",
        "precision": "very high",
    },
    "unified_sql": {
        "name": "Single-SQL 5-Signal Unified Search",
        "description": "Same 5-signal fusion as 'unified' but executed as a single CTE-based SQL statement. Eliminates multi-round Python-SQL round trips. Best for low-latency production scenarios.",
        "signals": ["vector", "fulltext", "relational", "tag", "graph"],
        "best_for": ["production search", "low-latency retrieval", "single-query fusion", "server-side scoring"],
        "requires_embedding": True,
        "supports_filters": ["entity_type", "workspace_id", "domain", "category", "tags", "graph_seed_entity_id", "all weights"],
        "speed": "fast",
        "precision": "very high",
    },
    "relational": {
        "name": "Relational Metadata Search",
        "description": "Structured query on KNOWLEDGE_META(domain,topic,difficulty), SPEC_META(scope,complexity), ENTITIES(category,importance). Best for categorical/filter-based retrieval.",
        "signals": ["relational"],
        "best_for": ["domain filtering", "category browsing", "difficulty levels", "structured metadata", "taxonomy navigation"],
        "requires_embedding": False,
        "supports_filters": ["domain", "category", "entity_type", "importance", "difficulty"],
        "speed": "fast",
        "precision": "high",
    },
    "multi_type": {
        "name": "Cross-Type Vector Search",
        "description": "Vector similarity across multiple entity types (MEMORY/KNOWLEDGE/SPEC) simultaneously. Best for finding related content regardless of type.",
        "signals": ["vector", "multi_type"],
        "best_for": ["cross-type discovery", "finding specs related to memories", "holistic knowledge retrieval", "type-agnostic search"],
        "requires_embedding": True,
        "supports_filters": ["entity_types", "workspace_id"],
        "speed": "medium",
        "precision": "high",
    },
    "auto": {
        "name": "Auto Strategy Selection",
        "description": "Automatically selects the best search strategy based on query characteristics (length, special chars, boolean operators, domain hints).",
        "signals": ["auto"],
        "best_for": ["unknown query type", "mixed intent", "convenient single entry point"],
        "requires_embedding": False,
        "supports_filters": ["all"],
        "speed": "varies",
        "precision": "varies",
    },
}


def list_search_strategies() -> List[Dict[str, Any]]:
    return [
        {
            "strategy": key,
            "name": val["name"],
            "description": val["description"],
            "signals": val["signals"],
            "best_for": val["best_for"],
            "requires_embedding": val["requires_embedding"],
            "speed": val["speed"],
            "precision": val["precision"],
        }
        for key, val in STRATEGIES.items()
    ]


def describe_search_strategy(strategy: str) -> Optional[Dict[str, Any]]:
    info = STRATEGIES.get(strategy)
    if not info:
        return None
    return {
        "strategy": strategy,
        **info,
        "parameters": _get_strategy_params(strategy),
    }

def _get_strategy_params(strategy: str) -> List[Dict[str, str]]:
    params = {
        "vector": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query text (will be embedded)"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 10)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type (MEMORY/KNOWLEDGE/SPEC)"},
            {"name": "workspace_id", "type": "str", "required": "False", "description": "Filter by workspace"},
        ],
        "fulltext": [
            {"name": "query", "type": "str", "required": "True", "description": "Oracle Text query (supports AND/OR/NOT, $fuzzy, stemming)"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 20)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type"},
            {"name": "category", "type": "str", "required": "False", "description": "Filter by category"},
        ],
        "keyword": [
            {"name": "keyword", "type": "str", "required": "True", "description": "LIKE pattern (e.g. partition%)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type (MEMORY/KNOWLEDGE)"},
            {"name": "category", "type": "str", "required": "False", "description": "Filter by category"},
            {"name": "limit", "type": "int", "required": "False", "description": "Max results (default 100)"},
        ],
        "graph": [
            {"name": "entity_id", "type": "str", "required": "True", "description": "Seed entity ID for graph traversal"},
            {"name": "entity_type", "type": "str", "required": "True", "description": "Seed entity type"},
            {"name": "direction", "type": "str", "required": "False", "description": "outgoing/incoming/both (default both)"},
            {"name": "edge_type", "type": "str", "required": "False", "description": "Filter by edge type"},
            {"name": "limit", "type": "int", "required": "False", "description": "Max neighbors (default 100)"},
        ],
        "hybrid": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query (embedded + fulltext)"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 10)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type"},
            {"name": "vector_weight", "type": "float", "required": "False", "description": "Vector signal weight (default 0.7)"},
            {"name": "fulltext_weight", "type": "float", "required": "False", "description": "Fulltext signal weight (default 0.3)"},
        ],
        "unified": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 20)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type"},
            {"name": "domain", "type": "str", "required": "False", "description": "Filter by knowledge domain"},
            {"name": "category", "type": "str", "required": "False", "description": "Filter by category"},
            {"name": "tags", "type": "list[str]", "required": "False", "description": "Filter by tags"},
            {"name": "graph_seed_entity_id", "type": "str", "required": "False", "description": "Seed entity for graph proximity"},
            {"name": "vector_weight", "type": "float", "required": "False", "description": "Vector weight (default 0.4)"},
            {"name": "fulltext_weight", "type": "float", "required": "False", "description": "Fulltext weight (default 0.25)"},
            {"name": "relational_weight", "type": "float", "required": "False", "description": "Relational weight (default 0.2)"},
            {"name": "graph_weight", "type": "float", "required": "False", "description": "Graph weight (default 0.15)"},
        ],
        "unified_sql": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 20)"},
            {"name": "entity_type", "type": "str", "required": "False", "description": "Filter by entity type"},
            {"name": "domain", "type": "str", "required": "False", "description": "Filter by knowledge domain"},
            {"name": "category", "type": "str", "required": "False", "description": "Filter by category"},
            {"name": "tags", "type": "list[str]", "required": "False", "description": "Filter by tags"},
            {"name": "graph_seed_entity_id", "type": "str", "required": "False", "description": "Seed entity for graph proximity"},
            {"name": "vector_weight", "type": "float", "required": "False", "description": "Vector weight (default 0.4)"},
            {"name": "fulltext_weight", "type": "float", "required": "False", "description": "Fulltext weight (default 0.25)"},
            {"name": "relational_weight", "type": "float", "required": "False", "description": "Relational weight (default 0.2)"},
            {"name": "graph_weight", "type": "float", "required": "False", "description": "Graph weight (default 0.15)"},
        ],
        "relational": [
            {"name": "entity_type", "type": "str", "required": "False", "description": "Entity type (KNOWLEDGE/SPEC)"},
            {"name": "domain", "type": "str", "required": "False", "description": "Knowledge domain filter"},
            {"name": "category", "type": "str", "required": "False", "description": "Category filter"},
            {"name": "min_importance", "type": "int", "required": "False", "description": "Minimum importance threshold"},
            {"name": "limit", "type": "int", "required": "False", "description": "Max results (default 50)"},
        ],
        "multi_type": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query (will be embedded)"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Results per type (default 10)"},
            {"name": "entity_types", "type": "list[str]", "required": "False", "description": "Types to search (default [MEMORY,KNOWLEDGE,SPEC])"},
        ],
        "auto": [
            {"name": "text", "type": "str", "required": "True", "description": "Search query (strategy auto-detected)"},
            {"name": "top_k", "type": "int", "required": "False", "description": "Number of results (default 10)"},
            {"name": "strategy_hint", "type": "str", "required": "False", "description": "Optional hint to influence auto selection"},
        ],
    }
    return params.get(strategy, [])


def _detect_strategy(text: str, **kwargs) -> str:
    if kwargs.get("entity_id") and not text:
        return "graph"
    if any(op in text.upper() for op in [" AND ", " OR ", " NOT "]):
        return "fulltext"
    if "$" in text or "~" in text:
        return "fulltext"
    if "%" in text or "_" in text:
        return "keyword"
    if kwargs.get("domain") or kwargs.get("tags"):
        return "unified"
    if kwargs.get("graph_seed_entity_id"):
        return "unified"
    if len(text.split()) <= 2:
        return "fulltext"
    if len(text.split()) >= 5:
        return "unified"
    return "hybrid"

def search(
    text: str,
    strategy: str = "auto",
    top_k: int = 10,
    entity_type: Optional[str] = None,
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    graph_seed_entity_id: Optional[str] = None,
    graph_seed_entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_types: Optional[List[str]] = None,
    min_importance: Optional[int] = None,
    vector_weight: Optional[float] = None,
    fulltext_weight: Optional[float] = None,
    relational_weight: Optional[float] = None,
    graph_weight: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    if strategy == "auto":
        strategy = _detect_strategy(text, **kwargs)

    result = {
        "strategy": strategy,
        "query": text,
        "results": [],
        "count": 0,
        "explain": bool(kwargs.get("explain", False)),
    }

    try:
        if strategy == "vector":
            result["results"] = embedding_api.search_similar(
                text, top_k=top_k, entity_type=entity_type, workspace_id=workspace_id,
            )

        elif strategy == "fulltext":
            result["results"] = embedding_api.search_fulltext(
                text, top_k=top_k, entity_type=entity_type, category=category, workspace_id=workspace_id,
            )

        elif strategy == "keyword":
            if entity_type == "KNOWLEDGE" or (not entity_type):
                kw_results = knowledge_api.search_knowledge(
                    keyword=text, domain=domain, limit=top_k,
                )
                result["results"].extend(kw_results)
            if entity_type == "MEMORY" or (not entity_type):
                mem_results = memory_api.search_memories(
                    keyword=text, category=category, workspace_id=workspace_id, limit=top_k,
                )
                result["results"].extend(mem_results)
            result["results"] = result["results"][:top_k]

        elif strategy == "graph":
            seed_id = entity_id or graph_seed_entity_id
            if seed_id:
                result["results"] = graph_api.get_neighbors(
                    seed_id, direction=kwargs.get("direction", "both"),
                    edge_type=kwargs.get("edge_type"), limit=top_k,
                )

        elif strategy == "hybrid":
            result["results"] = embedding_api.search_hybrid(
                text, keyword=kwargs.get("keyword"), top_k=top_k,
                entity_type=entity_type, workspace_id=workspace_id,
                vector_weight=vector_weight or 0.7,
            )

        elif strategy == "unified":
            uw = {
                "vector_weight": vector_weight or 0.4,
                "fulltext_weight": fulltext_weight or 0.25,
                "relational_weight": relational_weight or 0.2,
                "graph_weight": graph_weight or 0.15,
            }
            result["results"] = embedding_api.search_unified(
                text, top_k=top_k, entity_type=entity_type, workspace_id=workspace_id,
                domain=domain, category=category, tags=tags,
                graph_seed_entity_id=graph_seed_entity_id,
                graph_seed_entity_type=graph_seed_entity_type,
                **uw,
            )

        elif strategy == "unified_sql":
            uw = {
                "vector_weight": vector_weight or 0.4,
                "fulltext_weight": fulltext_weight or 0.25,
                "relational_weight": relational_weight or 0.2,
                "graph_weight": graph_weight or 0.15,
            }
            result["results"] = embedding_api.search_unified_sql(
                text, top_k=top_k, entity_type=entity_type, workspace_id=workspace_id,
                domain=domain, category=category, tags=tags,
                graph_seed_entity_id=graph_seed_entity_id,
                graph_seed_entity_type=graph_seed_entity_type,
                **uw,
            )

        elif strategy == "relational":
            result["results"] = _search_relational(
                entity_type=entity_type, domain=domain, category=category,
                min_importance=min_importance, limit=top_k,
            )

        elif strategy == "multi_type":
            mt = embedding_api.search_multi_type(
                text, top_k=top_k, entity_types=entity_types, workspace_id=workspace_id,
            )
            if isinstance(mt, dict):
                flat = []
                for etype, items in mt.items():
                    for item in items:
                        item["_source_type"] = etype
                        flat.append(item)
                result["results"] = flat
            else:
                result["results"] = mt

        else:
            logger.warning(f"Unknown strategy: {strategy}, falling back to unified")
            result["strategy"] = "unified"
            result["results"] = embedding_api.search_unified(text, top_k=top_k)

    except Exception as e:
        logger.error(f"Search failed (strategy={strategy}): {e}")
        result["error"] = str(e)

    if result.get("explain"):
        try:
            for item in result["results"]:
                eid = item.get("entity_id") if isinstance(item, dict) else None
                if eid:
                    item["_explanation"] = _explain_results(eid, text, strategy)
        except Exception as e:
            logger.debug(f"Explain annotation failed: {e}")

    result["count"] = len(result["results"])
    return result


def _explain_results(entity_id: str, query_text: str, strategy: str) -> Dict[str, Any]:
    """Return per-result explanation: vector_score, text_score, graph_path.

    Reads stored explanation rows from SEARCH_EXPLANATIONS view when present;
    falls back to computing each score on demand. Strategy gates which fields
    are populated so unrelated signals are left as None.
    """
    explanation: Dict[str, Any] = {
        "vector_score": None,
        "text_score": None,
        "graph_path": None,
    }

    try:
        row = execute_query_one(
            """SELECT VECTOR_SCORE, TEXT_SCORE, GRAPH_PATH
               FROM SEARCH_EXPLANATIONS
               WHERE ENTITY_ID = :eid AND QUERY_TEXT = :qt
               FETCH FIRST 1 ROWS ONLY""",
            {"eid": entity_id, "qt": query_text[:500]},
        )
    except Exception as e:
        logger.debug(f"SEARCH_EXPLANATIONS view read failed: {e}")
        row = None

    if row:
        if row.get("vector_score") is not None:
            try:
                explanation["vector_score"] = round(float(row["vector_score"]), 4)
            except (TypeError, ValueError):
                pass
        if row.get("text_score") is not None:
            try:
                explanation["text_score"] = round(float(row["text_score"]), 4)
            except (TypeError, ValueError):
                pass
        if row.get("graph_path"):
            explanation["graph_path"] = row["graph_path"]
        return explanation

    # Fallback: compute on demand based on strategy
    try:
        if strategy in ("vector", "hybrid", "unified", "unified_sql", "multi_type"):
            sim_rows = embedding_api.search_similar(query_text, top_k=50)
            for r in sim_rows:
                if r.get("entity_id") == entity_id and r.get("similarity") is not None:
                    explanation["vector_score"] = round(float(r["similarity"]), 4)
                    break

        if strategy in ("fulltext", "hybrid", "unified", "unified_sql"):
            ft_rows = embedding_api.search_fulltext(query_text, top_k=50)
            for r in ft_rows:
                if r.get("entity_id") == entity_id and r.get("ft_score") is not None:
                    explanation["text_score"] = round(float(r["ft_score"]), 4)
                    break

        if strategy in ("graph", "unified", "unified_sql"):
            try:
                path = graph_api.get_reachable(entity_id, max_hops=2, limit=5)
                explanation["graph_path"] = [p.get("entity_id") for p in path if p.get("entity_id")]
            except Exception as e:
                logger.debug(f"Graph path computation failed: {e}")
    except Exception as e:
        logger.debug(f"_explain_results computation failed: {e}")

    return explanation


def _search_relational(
    entity_type: Optional[str] = None,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    min_importance: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"lim": limit}
    conditions = []

    if entity_type:
        conditions.append("AND e.ENTITY_TYPE = :etype")
        params["etype"] = entity_type
    if domain:
        conditions.append("AND km.DOMAIN = :dom")
        params["dom"] = domain
    if category:
        conditions.append("AND e.CATEGORY = :cat")
        params["cat"] = category
    if min_importance:
        conditions.append("AND e.IMPORTANCE >= :imp")
        params["imp"] = min_importance

    where = " ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CATEGORY, e.IMPORTANCE,
               km.DOMAIN, km.TOPIC, km.DIFFICULTY,
               sm.SPEC_SCOPE, sm.COMPLEXITY, sm.SPEC_STATUS
        FROM ENTITIES e
        LEFT JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID AND km.ENTITY_TYPE = e.ENTITY_TYPE
        LEFT JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE 1=1 {where}
        ORDER BY e.IMPORTANCE DESC
        FETCH FIRST :lim ROWS ONLY
    """

    try:
        rows = execute_query(sql, params)
        results = []
        for r in rows:
            results.append({
                "entity_id": r["entity_id"],
                "entity_type": r["entity_type"],
                "title": r.get("title", ""),
                "category": r.get("category", ""),
                "importance": int(r["importance"]) if r.get("importance") else None,
                "km_domain": r.get("domain"),
                "km_topic": r.get("topic"),
                "km_difficulty": r.get("difficulty"),
                "sm_scope": r.get("spec_scope"),
                "sm_complexity": r.get("complexity"),
                "sm_spec_status": r.get("spec_status"),
            })
        return results
    except Exception as e:
        logger.error(f"Relational search failed: {e}")
        return []
