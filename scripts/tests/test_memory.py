"""Oracle Memory System v2.0.0 - Memory API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.memory_api import (
    create_memory, get_memory, update_memory, delete_memory,
    search_memories, get_agent_memories, count_memories
)
from lib.connection import close_pool


def test_create_memory():
    entity_id = create_memory(
        name="Test Memory",
        content="This is a test memory content",
        category="test",
        tags=["unit-test", "v2"],
        metadata={"source": "test"},
        owned_by_agent="test-agent",
    )
    assert entity_id > 0
    print(f"PASS: test_create_memory (id={entity_id})")
    return entity_id


def test_get_memory(entity_id):
    mem = get_memory(entity_id)
    assert mem is not None
    assert mem["name"] == "Test Memory"
    assert mem["category"] == "test"
    assert isinstance(mem["tags"], list)
    print(f"PASS: test_get_memory (name={mem['name']})")


def test_update_memory(entity_id):
    ok = update_memory(entity_id, name="Updated Test Memory", priority=1)
    assert ok
    mem = get_memory(entity_id)
    assert mem["name"] == "Updated Test Memory"
    assert mem["priority"] == 1
    print("PASS: test_update_memory")


def test_search_memories():
    results = search_memories(keyword="Test", category="test", limit=10)
    assert len(results) >= 1
    print(f"PASS: test_search_memories (found={len(results)})")


def test_get_agent_memories():
    results = get_agent_memories("test-agent", limit=10)
    assert len(results) >= 1
    print(f"PASS: test_get_agent_memories (found={len(results)})")


def test_count_memories():
    count = count_memories(category="test")
    assert count >= 1
    print(f"PASS: test_count_memories (count={count})")


def test_delete_memory(entity_id):
    ok = delete_memory(entity_id)
    assert ok
    mem = get_memory(entity_id)
    assert mem is None
    print("PASS: test_delete_memory")


def run_all():
    passed = 0
    failed = 0
    entity_id = None
    try:
        entity_id = test_create_memory()
        passed += 1
    except Exception as e:
        print(f"FAIL: test_create_memory - {e}")
        failed += 1
        close_pool()
        return False

    for test_fn in [
        lambda: test_get_memory(entity_id),
        lambda: test_update_memory(entity_id),
        test_search_memories,
        test_get_agent_memories,
        test_count_memories,
        lambda: test_delete_memory(entity_id),
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
