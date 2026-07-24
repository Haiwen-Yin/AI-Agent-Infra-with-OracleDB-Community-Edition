"""AI Agent Infra v4.1.0 - Knowledge API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.knowledge_api import (
    create_knowledge, get_knowledge, update_knowledge, delete_knowledge,
    add_edge, get_edges, search_knowledge,
    add_knowledge_tags, get_knowledge_tags, remove_knowledge_tag,
    record_review, get_due_reviews
)
from lib.connection import close_pool


def _test_create_knowledge():
    entity_id = create_knowledge(
        title="Python Decorators",
        content="Decorators are a powerful feature in Python",
        domain="programming",
        topic="python",
        difficulty="ADVANCED",
    )
    assert isinstance(entity_id, (int, str))
    assert entity_id > 0 if isinstance(entity_id, int) else len(entity_id) > 0
    print(f"PASS: _test_create_knowledge (id={entity_id})")
    return entity_id


def _test_get_knowledge(entity_id):
    k = get_knowledge(entity_id)
    assert k is not None
    assert k["domain"] == "programming"
    assert k["topic"] == "python"
    assert k["difficulty"] == "ADVANCED"
    print(f"PASS: _test_get_knowledge (domain={k['domain']})")


def _test_update_knowledge(entity_id):
    ok = update_knowledge(entity_id, domain="software", topic="decorators")
    assert ok
    k = get_knowledge(entity_id)
    assert k["domain"] == "software"
    assert k["topic"] == "decorators"
    print("PASS: _test_update_knowledge")


def _test_knowledge_tags(entity_id):
    added = add_knowledge_tags(entity_id, ["python", "v2.1"])
    assert added == 2
    tags = get_knowledge_tags(entity_id)
    assert len(tags) == 2
    tag_id = tags[0]["tag_id"]
    ok = remove_knowledge_tag(entity_id, tag_id)
    assert ok
    tags = get_knowledge_tags(entity_id)
    assert len(tags) == 1
    print("PASS: _test_knowledge_tags")


def _test_record_review(entity_id):
    k = get_knowledge(entity_id)
    count_before = k["review_count"]
    ok = record_review(entity_id)
    assert ok
    k = get_knowledge(entity_id)
    assert k["review_count"] > count_before
    print(f"PASS: _test_record_review (count={k['review_count']})")


def _test_knowledge_edges(entity_id):
    target_id = create_knowledge(
        title="Python Generators",
        content="Generators produce items lazily",
        domain="programming",
        topic="python",
        difficulty="INTERMEDIATE",
    )
    edge_id = add_edge(
        source_id=entity_id,
        source_type="KNOWLEDGE",
        target_id=target_id,
        edge_type="RELATED_TO",
        strength=0.8,
        confidence=0.9,
    )
    assert isinstance(edge_id, (int, str))
    assert edge_id > 0 if isinstance(edge_id, int) else len(edge_id) > 0
    edges = get_edges(entity_id, direction="outgoing")
    assert len(edges) >= 1
    print(f"PASS: _test_knowledge_edges (edges={len(edges)})")
    delete_knowledge(target_id)


def _test_search_knowledge():
    results = search_knowledge(domain="software")
    assert len(results) >= 1
    print(f"PASS: _test_search_knowledge (found={len(results)})")


def _test_delete_knowledge(entity_id):
    ok = delete_knowledge(entity_id)
    assert ok
    k = get_knowledge(entity_id)
    assert k is None
    print("PASS: _test_delete_knowledge")


def run_all():
    passed = 0
    failed = 0
    entity_id = None
    try:
        entity_id = _test_create_knowledge()
        passed += 1
    except Exception as e:
        print(f"FAIL: _test_create_knowledge - {e}")
        failed += 1
        close_pool()
        return False

    for test_fn in [
        lambda: _test_get_knowledge(entity_id),
        lambda: _test_update_knowledge(entity_id),
        lambda: _test_knowledge_tags(entity_id),
        lambda: _test_record_review(entity_id),
        lambda: _test_knowledge_edges(entity_id),
        _test_search_knowledge,
        lambda: _test_delete_knowledge(entity_id),
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__ if hasattr(test_fn, '__name__') else 'test'} - {e}")
            failed += 1

    close_pool()
    print(f"\nKnowledge Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
