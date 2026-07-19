"""AI Agent Infra v4.0.0 - Property Graph API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.graph_api import (
    get_neighbors, get_graph_stats, graph_search,
    get_entity_context, get_reachable, get_subgraph,
    find_communities, find_similar_entities,
)
from lib.memory_api import create_memory, delete_memory
from lib.knowledge_api import create_knowledge, delete_knowledge, add_edge
from lib.connection import close_pool, execute


_test_ids = []


def test_graph_stats():
    stats = get_graph_stats()
    assert "vertex_count" in stats
    assert "edge_count" in stats
    assert "avg_degree" in stats
    assert "entity_type_distribution" in stats
    assert "edge_type_distribution" in stats
    assert stats["vertex_count"] >= 0
    print(f"PASS: test_graph_stats (vertices={stats['vertex_count']}, edges={stats['edge_count']})")


def test_graph_search():
    results = graph_search(entity_type="MEMORY", limit=5)
    assert len(results) >= 1
    print(f"PASS: test_graph_search (found={len(results)})")


def test_neighbors():
    m1 = create_memory("Neighbor Test A", "content a", category="graph-test", importance=8, owned_by_agent="graph-tester")
    m2 = create_memory("Neighbor Test B", "content b", category="graph-test", importance=6, owned_by_agent="graph-tester")
    k1 = create_knowledge("Neighbor Knowledge", "knowledge content", domain="test", topic="graph", difficulty="BEGINNER", owned_by_agent="graph-tester")
    _test_ids.extend([m1, m2, k1])

    add_edge(m1, "MEMORY", k1, "DERIVED_FROM", 0.9, 0.85)
    add_edge(m2, "MEMORY", k1, "RELATED_TO", 0.7, 0.8)
    add_edge(m1, "MEMORY", m2, "SIMILAR_TO", 0.8, 0.9)

    out_nbrs = get_neighbors(m1, direction="outgoing")
    assert len(out_nbrs) >= 2
    out_types = {n["edge_type"] for n in out_nbrs}
    assert "DERIVED_FROM" in out_types or "SIMILAR_TO" in out_types

    in_nbrs = get_neighbors(k1, direction="incoming")
    assert len(in_nbrs) >= 2

    all_nbrs = get_neighbors(m1, direction="both")
    assert len(all_nbrs) >= 2

    filtered = get_neighbors(m1, direction="outgoing", edge_type="SIMILAR_TO")
    assert len(filtered) >= 1
    assert all(n["edge_type"] == "SIMILAR_TO" for n in filtered)

    print(f"PASS: test_neighbors (out={len(out_nbrs)}, in={len(in_nbrs)}, both={len(all_nbrs)})")


def test_entity_context():
    m = _test_ids[0] if _test_ids else None
    if not m:
        m = create_memory("Context Test", "content", category="graph-test", importance=5, owned_by_agent="graph-tester")
        _test_ids.append(m)

    ctx = get_entity_context(m)
    assert ctx is not None
    assert "entity_id" in ctx
    assert "neighbors" in ctx
    assert "neighbor_count" in ctx
    assert "neighbors_by_type" in ctx
    assert "neighbors_by_edge" in ctx
    print(f"PASS: test_entity_context (neighbors={ctx['neighbor_count']})")


def test_reachable():
    m = _test_ids[0] if _test_ids else None
    if not m:
        print("SKIP: test_reachable (no test entity)")
        return

    reachable = get_reachable(m, max_hops=2, limit=10)
    assert isinstance(reachable, list)
    print(f"PASS: test_reachable (found={len(reachable)})")


def test_subgraph():
    ids = _test_ids[:3] if len(_test_ids) >= 3 else _test_ids
    if not ids:
        print("SKIP: test_subgraph (no test entities)")
        return

    sub = get_subgraph(ids)
    assert "vertices" in sub
    assert "edges" in sub
    assert len(sub["vertices"]) >= 1
    print(f"PASS: test_subgraph (vertices={len(sub['vertices'])}, edges={len(sub['edges'])})")


def test_find_similar():
    m = _test_ids[0] if _test_ids else None
    if not m:
        print("SKIP: test_find_similar (no test entity)")
        return

    similar = find_similar_entities(m, max_hops=2, limit=10)
    assert isinstance(similar, list)
    print(f"PASS: test_find_similar (found={len(similar)})")


def test_find_communities():
    communities = find_communities(min_connections=1, limit=10)
    assert isinstance(communities, list)
    print(f"PASS: test_find_communities (found={len(communities)})")


def _cleanup():
    for eid in _test_ids:
        try:
            execute("DELETE FROM ENTITY_TAGS WHERE ENTITY_ID = :id", {"id": eid})
        except Exception:
            pass
    for eid in _test_ids:
        try:
            execute("DELETE FROM ENTITY_EDGES WHERE SOURCE_ID = :id OR TARGET_ID = :id", {"id": eid})
        except Exception:
            pass
    for eid in list(reversed(_test_ids)):
        try:
            delete_knowledge(eid)
        except Exception:
            pass
    for eid in list(reversed(_test_ids)):
        try:
            delete_memory(eid)
        except Exception:
            pass
    _test_ids.clear()


def run_all():
    passed = 0
    failed = 0
    tests = [
        test_graph_stats,
        test_graph_search,
        test_neighbors,
        test_entity_context,
        test_reachable,
        test_subgraph,
        test_find_similar,
        test_find_communities,
    ]
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} - {e}")
            failed += 1

    _cleanup()
    close_pool()
    print(f"\nGraph Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
