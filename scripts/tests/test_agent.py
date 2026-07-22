"""AI Agent Infra v4.0.1 - Agent API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.agent_api import (
    register_agent, get_agent, heartbeat,
    create_session, end_session, get_active_sessions,
    log_access, get_access_log,
    create_collaboration, get_collaborations
)
from lib.memory_api import create_memory, delete_memory
from lib.connection import close_pool

TEST_AGENT = "test-agent-1"
TEST_AGENT_2 = "test-agent-2"


def test_register_agent():
    agent_id = register_agent(
        agent_id=TEST_AGENT,
        agent_name="Test Agent",
        agent_type="test",
    )
    assert isinstance(agent_id, str)
    assert agent_id == TEST_AGENT
    print("PASS: test_register_agent")


def test_get_agent():
    agent = get_agent(TEST_AGENT)
    assert agent is not None
    assert agent["agent_name"] == "Test Agent"
    print(f"PASS: test_get_agent (name={agent['agent_name']})")


def test_heartbeat():
    ok = heartbeat(TEST_AGENT)
    assert ok
    print("PASS: test_heartbeat")


def test_create_session():
    session_id = create_session(TEST_AGENT)
    assert isinstance(session_id, (int, str))
    assert session_id > 0 if isinstance(session_id, int) else len(session_id) > 0
    print(f"PASS: test_create_session (id={session_id})")


def test_active_sessions():
    sessions = get_active_sessions(agent_id=TEST_AGENT)
    assert len(sessions) >= 1
    print(f"PASS: test_active_sessions (found={len(sessions)})")


def test_log_access():
    entity_id = create_memory("Access Test", "content", category="test")
    log_id = log_access(TEST_AGENT, entity_id, "READ")
    assert isinstance(log_id, (int, str))
    assert log_id > 0 if isinstance(log_id, int) else len(log_id) > 0
    history = get_access_log(entity_id=entity_id, limit=5)
    assert len(history) >= 1
    print(f"PASS: test_log_access (log_id={log_id})")
    from lib.connection import execute
    execute("DELETE FROM ENTITY_ACCESS_LOG WHERE ENTITY_ID = :id", {"id": entity_id})
    delete_memory(entity_id)


def test_end_session():
    session_id = create_session(TEST_AGENT)
    ok = end_session(session_id)
    assert ok
    print("PASS: test_end_session")


def test_collaboration():
    register_agent(TEST_AGENT_2, "Second Test Agent", agent_type="test")
    col_id = create_collaboration(
        source_agent_id=TEST_AGENT,
        target_agent_id=TEST_AGENT_2,
        col_type="SHARING",
    )
    assert isinstance(col_id, (int, str))
    assert col_id > 0 if isinstance(col_id, int) else len(col_id) > 0
    collabs = get_collaborations(agent_id=TEST_AGENT)
    assert len(collabs) >= 1
    print(f"PASS: test_collaboration (col_id={col_id})")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_register_agent,
        test_get_agent,
        test_heartbeat,
        test_create_session,
        test_active_sessions,
        test_log_access,
        test_end_session,
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
