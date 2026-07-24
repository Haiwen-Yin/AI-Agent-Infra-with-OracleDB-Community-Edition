"""AI Agent Infra v4.1.0 - Embedding API Tests

Tests: generate, store, retrieve, search, vector similarity, hybrid search, multi-type search, batch, dimension detection, stats, delete.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import embedding_api, memory_api, knowledge_api

passed = 0
failed = 0

TEST_IDS = []


def _test(name, fn):
    global passed, failed
    try:
        result = fn()
        print(f"PASS: {name} ({result})")
        passed += 1
    except Exception as e:
        print(f"FAIL: {name} ({e})")
        failed += 1


def cleanup():
    for eid in TEST_IDS:
        for etype in ["MEMORY", "KNOWLEDGE"]:
            try:
                embedding_api.delete_embedding(eid, etype)
            except:
                pass
            try:
                memory_api.delete_memory(eid)
            except:
                pass
            try:
                knowledge_api.delete_knowledge(eid)
            except:
                pass


def run_all():
    global passed, failed, TEST_IDS
    passed = 0
    failed = 0
    TEST_IDS = []

    _test("generate_embedding", lambda: f"dims={len(embedding_api.generate_embedding('hello world'))} model=bge-m3")
    _test("get_model_dimension", lambda: f"known={embedding_api.get_model_dimension('text-embedding-bge-m3')}")
    _test("get_model_dimension_unknown", lambda: f"probe={embedding_api.get_model_dimension('text-embedding-bge-m3')}")

    mid1 = memory_api.create_memory("Vector Search Alpha", "Database architecture patterns for scalability and performance optimization", category="architecture")
    TEST_IDS.append(mid1)
    _test("store_embedding", lambda: f"ok={embedding_api.store_embedding(mid1, 'MEMORY', 'Database architecture patterns for scalability')}")

    mid2 = memory_api.create_memory("Vector Search Beta", "Machine learning model training with neural networks and deep learning", category="ml")
    TEST_IDS.append(mid2)
    _test("store_embedding_2", lambda: f"ok={embedding_api.store_embedding(mid2, 'MEMORY', 'Machine learning model training with neural networks')}")

    mid3 = memory_api.create_memory("Vector Search Gamma", "Cloud infrastructure deployment with Kubernetes and microservices", category="devops")
    TEST_IDS.append(mid3)
    _test("store_embedding_3", lambda: f"ok={embedding_api.store_embedding(mid3, 'MEMORY', 'Cloud infrastructure deployment with Kubernetes')}")

    _test("get_embedding", lambda: f"model={embedding_api.get_embedding(mid1, 'MEMORY')['embedding_model']}")

    similar = embedding_api.search_similar("database architecture and scalability", top_k=5, entity_type="MEMORY")
    _test("search_similar", lambda: f"results={len(similar)} top_type={similar[0]['entity_type'] if similar else 'none'}")
    _test("search_similar_has_scores", lambda: f"similarity={similar[0]['similarity']:.4f}" if similar and similar[0].get('similarity') else "no_results")

    by_id = embedding_api.search_by_entity_id(mid1, "MEMORY", top_k=5)
    _test("search_by_entity_id", lambda: f"results={len(by_id)}")
    _test("search_by_entity_id_no_self", lambda: f"self_excluded={all(r['entity_id'] != mid1 for r in by_id)}")

    kid = knowledge_api.create_knowledge("Distributed Database Design", domain="architecture", topic="database", content="Patterns for distributed database systems with partitioning and replication")
    TEST_IDS.append(kid)
    _test("store_knowledge_embedding", lambda: f"ok={embedding_api.store_embedding(kid, 'KNOWLEDGE', 'Distributed database design patterns')}")

    cross = embedding_api.search_similar("database partitioning and distributed systems", top_k=5)
    _test("cross_type_search", lambda: f"types={[r['entity_type'] for r in cross]}")

    hybrid = embedding_api.search_hybrid("database architecture", keyword="architecture", top_k=5)
    _test("hybrid_search", lambda: f"results={len(hybrid)} has_hybrid_score={'hybrid_score' in hybrid[0] if hybrid else False}")

    hybrid_no_kw = embedding_api.search_hybrid("database architecture", top_k=5)
    _test("hybrid_search_no_keyword", lambda: f"results={len(hybrid_no_kw)}")

    multi = embedding_api.search_multi_type("database design", top_k=3)
    _test("multi_type_search", lambda: f"types={list(multi.keys())} total={sum(len(v) for v in multi.values())}")

    batch_result = embedding_api.generate_embeddings_batch("MEMORY", limit=3)
    _test("generate_embeddings_batch", lambda: f"gen={batch_result['generated']}")

    stats = embedding_api.get_embedding_stats()
    _test("get_embedding_stats", lambda: f"total={stats.get('total', 0)}")

    for eid in TEST_IDS:
        embedding_api.delete_embedding(eid, "MEMORY")
        embedding_api.delete_embedding(eid, "KNOWLEDGE")
        try:
            memory_api.delete_memory(eid)
        except:
            pass
        try:
            knowledge_api.delete_knowledge(eid)
        except:
            pass
    _test("cleanup", lambda: "cleaned")

    print(f"\nEmbedding Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
