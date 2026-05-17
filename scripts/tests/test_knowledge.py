"""Oracle Memory System v2.0.0 - Knowledge API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.knowledge_api import (
    create_concept, get_concept, update_concept, delete_concept,
    create_relationship, get_relationships, delete_relationship,
    search_concepts, get_statistics, get_concept_neighbors
)
from lib.connection import close_pool


def test_create_concept():
    entity_id = create_concept(
        name="Test Concept",
        concept_type="principle",
        description="A test knowledge concept",
        category="testing",
        content="Detailed content about this concept",
        source_type="MANUAL",
        confidence=0.9,
        tags=["test", "v2"],
    )
    assert entity_id > 0
    print(f"PASS: test_create_concept (id={entity_id})")
    return entity_id


def test_get_concept(entity_id):
    concept = get_concept(entity_id)
    assert concept is not None
    assert concept["name"] == "Test Concept"
    assert concept["validation_status"] == "PENDING"
    assert concept["confidence"] == 0.9
    print(f"PASS: test_get_concept (name={concept['name']})")


def test_update_concept(entity_id):
    ok = update_concept(entity_id, description="Updated description", confidence=0.95)
    assert ok
    concept = get_concept(entity_id)
    assert concept["description"] == "Updated description"
    print("PASS: test_update_concept")


def test_create_relationship_and_query(entity_id):
    target_id = create_concept(
        name="Related Concept",
        concept_type="fact",
        description="Another concept for relationship testing",
        category="testing",
    )
    edge_id = create_relationship(
        source_id=entity_id,
        target_id=target_id,
        edge_type="RELATED_TO",
        strength=0.8,
        confidence=0.9,
    )
    assert edge_id > 0
    print(f"PASS: test_create_relationship (edge_id={edge_id})")

    rels = get_relationships(entity_id, direction="outgoing")
    assert len(rels) >= 1
    print(f"PASS: test_get_relationships (found={len(rels)})")

    neighbors = get_concept_neighbors(entity_id)
    assert len(neighbors) >= 1
    print(f"PASS: test_get_concept_neighbors (found={len(neighbors)})")

    ok = delete_relationship(edge_id)
    assert ok
    print("PASS: test_delete_relationship")

    delete_concept(target_id)
    return target_id


def test_search_concepts():
    results = search_concepts(keyword="Test", limit=10)
    assert len(results) >= 1
    print(f"PASS: test_search_concepts (found={len(results)})")


def test_get_statistics():
    stats = get_statistics()
    assert "total_concepts" in stats
    assert "total_edges" in stats
    assert "total_memories" in stats
    print(f"PASS: test_get_statistics (concepts={stats['total_concepts']}, memories={stats['total_memories']})")


def test_delete_concept(entity_id):
    ok = delete_concept(entity_id)
    assert ok
    concept = get_concept(entity_id)
    assert concept is None
    print("PASS: test_delete_concept")


def run_all():
    entity_id = None
    passed = 0
    failed = 0
    try:
        entity_id = test_create_concept()
        passed += 1
    except Exception as e:
        print(f"FAIL: test_create_concept - {e}")
        failed += 1
        close_pool()
        return False

    for test_fn in [
        lambda: test_get_concept(entity_id),
        lambda: test_update_concept(entity_id),
        lambda: test_create_relationship_and_query(entity_id),
        test_search_concepts,
        test_get_statistics,
        lambda: test_delete_concept(entity_id),
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {e}")
            failed += 1

    close_pool()
    print(f"\nKnowledge Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
