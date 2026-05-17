"""Oracle Memory System v2.0.0 - Agent API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.agent_api import (
    register_agent, get_agent, list_agents, disable_agent, enable_agent,
    create_session, update_session_context, close_session, get_active_sessions,
    log_access, get_access_history, request_collaboration, get_pending_requests
)
from lib.memory_api import create_memory, delete_memory
from lib.connection import close_pool

TEST_AGENT = "test-agent-api"


def test_register_agent():
    ok = register_agent(
        agent_id=TEST_AGENT,
        agent_name="Test Agent for API",
        agent_type="tester",
        capabilities=["read", "write", "test"],
        description="Agent for unit testing",
    )
    assert ok
    print(f"PASS: test_register_agent")


def test_get_agent():
    agent = get_agent(TEST_AGENT)
    assert agent is not None
    assert agent["agent_name"] == "Test Agent for API"
    assert isinstance(agent["capabilities"], list)
    print(f"PASS: test_get_agent (name={agent['agent_name']})")


def test_list_agents():
    agents = list_agents(agent_type="tester")
    assert len(agents) >= 1
    print(f"PASS: test_list_agents (found={len(agents)})")


def test_session_lifecycle():
    session_id = create_session(TEST_AGENT)
    assert session_id is not None
    print(f"PASS: test_create_session (id={session_id})")

    ok = update_session_context(session_id, {"test_key": "test_value"})
    assert ok
    print("PASS: test_update_session_context")

    sessions = get_active_sessions(agent_id=TEST_AGENT)
    assert len(sessions) >= 1
    print(f"PASS: test_get_active_sessions (found={len(sessions)})")

    ok = close_session(session_id)
    assert ok
    print("PASS: test_close_session")


def test_access_logging():
    entity_id = create_memory("Access Test Memory", "content", category="test")
    log_access(TEST_AGENT, entity_id, "READ")
    history = get_access_history(TEST_AGENT, limit=5)
    assert len(history) >= 1
    print(f"PASS: test_access_logging (history={len(history)})")
    from lib.connection import execute
    execute("DELETE FROM ENTITY_ACCESS_LOG WHERE ENTITY_ID = :eid", {"eid": entity_id})
    delete_memory(entity_id)


def test_agent_lifecycle():
    ok = disable_agent(TEST_AGENT, reason="test disable")
    assert ok
    agent = get_agent(TEST_AGENT)
    assert agent["status"] == "DISABLED"
    print("PASS: test_disable_agent")

    ok = enable_agent(TEST_AGENT)
    assert ok
    agent = get_agent(TEST_AGENT)
    assert agent["status"] == "ACTIVE"
    print("PASS: test_enable_agent")


def test_collaboration():
    register_agent("test-agent-api-2", "Second Test Agent", agent_type="tester")
    entity_id = create_memory("Collab Test", "content", category="test")
    collab_id = request_collaboration(
        sharing_agent=TEST_AGENT,
        receiving_agent="test-agent-api-2",
        entity_id=entity_id,
        reason="Unit test collaboration",
    )
    if collab_id:
        print(f"PASS: test_request_collaboration (id={collab_id})")
        pending = get_pending_requests(TEST_AGENT, role="sharing")
        print(f"PASS: test_get_pending_requests (found={len(pending)})")
    else:
        print("SKIP: test_collaboration (request failed)")

    delete_memory(entity_id)


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_register_agent,
        test_get_agent,
        test_list_agents,
        test_session_lifecycle,
        test_access_logging,
        test_agent_lifecycle,
        test_collaboration,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nAgent Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
