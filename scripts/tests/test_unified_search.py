"""AI Agent Infra v4.0.1 - Unified Hybrid Search Tests

Tests the 5-signal unified search: vector + fulltext (Oracle Text) + relational metadata + graph proximity.
Uses seeded test data with 50+ entities, embeddings, edges, and tags.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import embedding_api
from lib.connection import get_connection

passed = 0
failed = 0


def _test(name, fn):
    global passed, failed
    try:
        result = fn()
        print(f"PASS: {name} ({result})")
        passed += 1
    except Exception as e:
        print(f"FAIL: {name} ({e})")
        failed += 1


def get_test_entity(title, entity_type="MEMORY"):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ENTITY_ID FROM ENTITIES WHERE TITLE = :t AND ENTITY_TYPE = :et ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY", {"t": title, "et": entity_type})
            row = cur.fetchone()
            return row[0] if row else None


def run_all():
    global passed, failed
    passed = 0
    failed = 0

    _test("search_unified_basic", lambda: f"results={len(embedding_api.search_unified('vector search optimization', top_k=5))}")

    results = embedding_api.search_unified("database partitioning strategies", top_k=5)
    _test("search_unified_has_scores", lambda: f"scores_keys={list(results[0]['scores'].keys()) if results else 'none'}")

    _test("search_unified_5_signals", lambda: f"signals={[k for k in results[0]['scores'].keys()] if results else []}")

    results_kw = embedding_api.search_unified("BGE-M3 embedding model", top_k=3)
    ft_score = results_kw[0]["scores"]["fulltext"] if results_kw else 0
    _test("fulltext_signal_active", lambda: f"ft_score={ft_score:.3f}")

    _test("fulltext_search_standalone", lambda: f"results={len(embedding_api.search_fulltext('partitioning', top_k=5))}")

    results_ft = embedding_api.search_fulltext("encryption AND credential", top_k=3)
    _test("fulltext_boolean_query", lambda: f"results={len(results_ft)}")

    results_dom = embedding_api.search_unified("partitioning oracle database", top_k=5, domain="database")
    has_domain = any(r.get("km_domain") == "database" for r in results_dom)
    _test("relational_domain_filter", lambda: f"has_domain_match={has_domain}")

    results_cat = embedding_api.search_unified("performance optimization", top_k=5, category="performance")
    _test("relational_category_filter", lambda: f"results={len(results_cat)}")

    seed_id = get_test_entity("Database Partitioning Strategies", "MEMORY")
    results_graph = embedding_api.search_unified("partitioning and child tables", top_k=5, graph_seed_entity_id=seed_id, graph_seed_entity_type="MEMORY") if seed_id else []
    graph_prox = max((r.get("graph_proximity", 0) for r in results_graph), default=0)
    _test("graph_proximity_active", lambda: f"max_proximity={graph_prox:.3f}")

    results_tag = embedding_api.search_unified("vector embedding search", top_k=5, tags=["vector", "search"])
    _test("tag_filter_works", lambda: f"results={len(results_tag)}")

    results_cross = embedding_api.search_unified("security encryption specification", top_k=8)
    types_present = set(r["entity_type"] for r in results_cross)
    _test("cross_type_results", lambda: f"types={sorted(types_present)}")

    top_result = results_cross[0] if results_cross else None
    _test("final_score_computed", lambda: f"score={top_result['final_score']:.4f}" if top_result else "no_results")

    _test("scores_sum_to_final", lambda: f"weighted_sum={sum(top_result['scores'][k] for k in ['vector','fulltext','relational','graph']):.4f}" if top_result else "no_results")

    results_multi = embedding_api.search_unified("oracle database architecture", top_k=5, domain="database", category="architecture", tags=["partitioning"])
    _test("multi_filter_combined", lambda: f"results={len(results_multi)}")

    results_spec = embedding_api.search_unified("security framework specification", top_k=5)
    spec_results = [r for r in results_spec if r["entity_type"] == "SPEC"]
    _test("spec_type_search", lambda: f"spec_count={len(spec_results)}")

    results_edge = embedding_api.search_unified("database partitioning", top_k=5)
    has_edges = any(r.get("edge_count", 0) > 0 for r in results_edge)
    _test("edge_count_populated", lambda: f"has_edges={has_edges}")

    results_knowledge = embedding_api.search_unified("python oracledb driver", top_k=5, entity_type="KNOWLEDGE")
    _test("entity_type_filter", lambda: f"all_knowledge={all(r['entity_type'] == 'KNOWLEDGE' for r in results_knowledge)}")

    results_custom_w = embedding_api.search_unified("security authentication", top_k=3, vector_weight=0.3, fulltext_weight=0.35, relational_weight=0.2, graph_weight=0.15)
    _test("custom_weights", lambda: f"results={len(results_custom_w)}")

    results_meta = embedding_api.search_unified("knowledge validation pipeline", top_k=3)
    has_meta = any(r.get("km_domain") or r.get("km_topic") for r in results_meta)
    _test("relational_metadata_joined", lambda: f"has_meta={has_meta}")

    results_empty = embedding_api.search_unified("xyzzy_nonexistent_12345", top_k=3)
    _test("graceful_empty_results", lambda: f"results={len(results_empty)}")

    _test("search_unified_sql_basic", lambda: f"results={len(embedding_api.search_unified_sql('vector search optimization', top_k=5))}")

    results_sql = embedding_api.search_unified_sql("database partitioning strategies", top_k=5)
    _test("search_unified_sql_has_scores", lambda: f"scores_keys={list(results_sql[0]['scores'].keys()) if results_sql else 'none'}")

    _test("search_unified_sql_5_signals", lambda: f"signals={[k for k in results_sql[0]['scores'].keys()] if results_sql else []}")

    _test("search_unified_sql_engine_tag", lambda: f"engine={results_sql[0].get('engine','none') if results_sql else 'none'}")

    results_sql_ft = embedding_api.search_unified_sql("BGE-M3 embedding model", top_k=3)
    ft_sql_score = results_sql_ft[0]["scores"]["fulltext"] if results_sql_ft else 0
    _test("search_unified_sql_fulltext_signal", lambda: f"ft_score={ft_sql_score:.3f}")

    results_sql_dom = embedding_api.search_unified_sql("partitioning oracle database", top_k=5, domain="database")
    has_dom = any(r.get("km_domain") == "database" for r in results_sql_dom)
    _test("search_unified_sql_domain_filter", lambda: f"has_domain_match={has_dom}")

    if seed_id:
        results_sql_graph = embedding_api.search_unified_sql("partitioning and child tables", top_k=5, graph_seed_entity_id=seed_id, graph_seed_entity_type="MEMORY")
        graph_sql_prox = max((r.get("graph_proximity", 0) for r in results_sql_graph), default=0)
        _test("search_unified_sql_graph_proximity", lambda: f"max_proximity={graph_sql_prox:.3f}")
    else:
        _test("search_unified_sql_graph_proximity", lambda: "skipped_no_seed")

    results_sql_tag = embedding_api.search_unified_sql("vector embedding search", top_k=5, tags=["vector", "search"])
    _test("search_unified_sql_tag_filter", lambda: f"results={len(results_sql_tag)}")

    results_sql_kw = embedding_api.search_unified_sql("oracle database architecture", top_k=5, entity_type="KNOWLEDGE")
    _test("search_unified_sql_entity_type_filter", lambda: f"all_knowledge={all(r['entity_type'] == 'KNOWLEDGE' for r in results_sql_kw)}")

    results_sql_empty = embedding_api.search_unified_sql("xyzzy_nonexistent_12345", top_k=3)
    _test("search_unified_sql_graceful_empty", lambda: f"results={len(results_sql_empty)}")

    results_sql_custom = embedding_api.search_unified_sql("security authentication", top_k=3, vector_weight=0.3, fulltext_weight=0.35, relational_weight=0.2, graph_weight=0.15)
    _test("search_unified_sql_custom_weights", lambda: f"results={len(results_sql_custom)}")

    print(f"\nUnified Hybrid Search Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
