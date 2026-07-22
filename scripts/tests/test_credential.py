"""AI Agent Infra v4.0.1 - Credential & Pool Agent Tests"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import time
from datetime import datetime, timedelta
from lib.agent_api import (
    register_agent, get_agent, issue_credential, verify_credential,
    get_credentials_for_user, revoke_credential,
    hibernate_agent, wake_agent, register_pool_agent, assign_pool_agent
)
from lib.connection import close_pool

USER = "cred-test-user"
AGENT = "cred-test-agent"
POOL_AGENT = "pool-test-agent"
POOL_TEST_SKILL = "credential-pool-test"


CRED_ID = None


def test_register_agents():
    register_agent(AGENT, "Cred Test Agent", agent_type="test")
    register_agent(POOL_AGENT, "Pool Test Agent", agent_type="test")
    try:
        from lib.connection import execute
        execute("INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, STATUS, ROLE, AUTH_SOURCE, CREATED_AT, UPDATED_AT) VALUES (:uid, :uname, 'SHA256:placeholder', 'ACTIVE', 'USER', 'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", {"uid": USER, "uname": "cred_test_user"})
    except Exception:
        pass
    print("PASS: test_register_agents")


def test_issue_credential():
    global CRED_ID
    scope = {"access_level": "FULL", "restricted_domains": [], "max_clearance": "TOP_SECRET"}
    CRED_ID = issue_credential(AGENT, USER, scope)
    assert isinstance(CRED_ID, (int, str))
    assert CRED_ID > 0 if isinstance(CRED_ID, int) else len(CRED_ID) > 0
    print(f"PASS: test_issue_credential (id={CRED_ID})")


def test_verify_credential():
    result = verify_credential(CRED_ID)
    assert result is not None
    assert result["scope"]["access_level"] == "FULL"
    print(f"PASS: test_verify_credential (scope={result['scope']})")


def test_get_credentials():
    creds = get_credentials_for_user(USER)
    assert len(creds) >= 1
    print(f"PASS: test_get_credentials (found={len(creds)})")


def test_revoke_credential():
    ok = revoke_credential(CRED_ID)
    assert ok
    result = verify_credential(CRED_ID)
    assert result is None
    print("PASS: test_revoke_credential")


def test_hibernate_agent():
    from lib.connection import execute
    execute("UPDATE AGENT_REGISTRY SET STATUS = 'ACTIVE' WHERE AGENT_ID = :aid", {"aid": AGENT})
    ok = hibernate_agent(AGENT)
    assert ok
    agent = get_agent(AGENT)
    assert agent["status"] == "POOL"
    print("PASS: test_hibernate_agent")


def test_wake_agent():
    result = wake_agent(AGENT, user_id=USER)
    assert result is not None
    agent = get_agent(AGENT)
    assert agent["status"] == "ACTIVE"
    print(f"PASS: test_wake_agent (status={agent['status']})")


def test_register_pool_agent():
    pool_config = {"max_idle_minutes": 60, "skills_tags": [POOL_TEST_SKILL], "auto_wake": False}
    ok = register_pool_agent(POOL_AGENT, pool_config)
    assert ok
    agent = get_agent(POOL_AGENT)
    assert agent["status"] == "POOL"
    print("PASS: test_register_pool_agent")


def test_assign_pool_agent():
    register_agent("pool-assigner", "Pool Assigner", agent_type="test")
    result = assign_pool_agent(USER, required_skills=[POOL_TEST_SKILL])
    try:
        assert result is not None
        assert result["agent_id"] == POOL_AGENT
        assert result["status"] == "ACTIVE"
        print(f"PASS: test_assign_pool_agent (assigned={result['agent_id']})")
    finally:
        assigned = get_agent(POOL_AGENT)
        if assigned and assigned["status"] == "ACTIVE":
            hibernate_agent(POOL_AGENT)
    assert get_agent(POOL_AGENT)["status"] == "POOL"


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_register_agents,
        test_issue_credential,
        test_verify_credential,
        test_get_credentials,
        test_revoke_credential,
        test_hibernate_agent,
        test_wake_agent,
        test_register_pool_agent,
        test_assign_pool_agent,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nCredential Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
