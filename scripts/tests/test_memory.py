"""AI Agent Infra v4.1.0 - Memory API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.memory_api import (
    create_memory, get_memory, update_memory, delete_memory,
    search_memories, get_agent_memories, count_memories,
    add_memory_tags, get_memory_tags, remove_memory_tag
)
from lib.connection import close_pool


def _test_create_memory():
    entity_id = create_memory(
        title="Test Memory",
        content="test content",
        category="test",
        importance=7,
        owned_by_agent="test-agent",
    )
    assert isinstance(entity_id, (int, str))
    assert entity_id > 0 if isinstance(entity_id, int) else len(entity_id) > 0
    print(f"PASS: _test_create_memory (id={entity_id})")
    return entity_id


def _test_get_memory(entity_id):
    mem = get_memory(entity_id)
    assert mem is not None
    assert mem["title"] == "Test Memory"
    assert mem["category"] == "test"
    assert mem["importance"] == 7
    print(f"PASS: _test_get_memory (title={mem['title']})")


def _test_update_memory(entity_id):
    ok = update_memory(entity_id, title="Updated Memory", importance=3)
    assert ok
    mem = get_memory(entity_id)
    assert mem["title"] == "Updated Memory"
    assert mem["importance"] == 3
    print("PASS: _test_update_memory")


def _test_search_memories():
    results = search_memories(keyword="Memory", category="test")
    assert len(results) >= 1
    print(f"PASS: _test_search_memories (found={len(results)})")


def _test_get_agent_memories():
    results = get_agent_memories("test-agent")
    assert len(results) >= 1
    print(f"PASS: _test_get_agent_memories (found={len(results)})")


def _test_count_memories():
    count = count_memories(category="test")
    assert count >= 1
    print(f"PASS: _test_count_memories (count={count})")


def _test_memory_tags(entity_id):
    added = add_memory_tags(entity_id, ["unit-test", "v2.1"])
    assert added == 2
    tags = get_memory_tags(entity_id)
    assert len(tags) == 2
    tag_id = tags[0]["tag_id"]
    ok = remove_memory_tag(entity_id, tag_id)
    assert ok
    tags = get_memory_tags(entity_id)
    assert len(tags) == 1
    print("PASS: _test_memory_tags")


def _test_delete_memory(entity_id):
    ok = delete_memory(entity_id)
    assert ok
    mem = get_memory(entity_id)
    assert mem is None
    print("PASS: _test_delete_memory")


def run_all():
    passed = 0
    failed = 0
    entity_id = None
    try:
        entity_id = _test_create_memory()
        passed += 1
    except Exception as e:
        print(f"FAIL: _test_create_memory - {e}")
        failed += 1
        close_pool()
        return False

    for test_fn in [
        lambda: _test_get_memory(entity_id),
        lambda: _test_update_memory(entity_id),
        _test_search_memories,
        _test_get_agent_memories,
        _test_count_memories,
        lambda: _test_memory_tags(entity_id),
        lambda: _test_delete_memory(entity_id),
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__ if hasattr(test_fn, '__name__') else 'test'} - {e}")
            failed += 1

    close_pool()
    print(f"\nMemory Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
