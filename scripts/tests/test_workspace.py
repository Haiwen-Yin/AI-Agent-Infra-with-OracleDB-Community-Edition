"""AI Agent Infra v4.1.0 - Workspace API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib import workspace_api
from lib import agent_api
from lib import memory_api
from lib import task_plan_api
from lib.connection import execute, close_pool

user_ws_id = None
system_ws_id = None
isolated_ws_id = None
handoff_session_id = None
test_plan_id = None
test_entity_id = None

TEST_AGENT_1 = "ws-test-agent-1"
TEST_AGENT_2 = "ws-test-agent-2"


def test_create_workspace_user_owned():
    global user_ws_id
    user_ws_id = workspace_api.create_workspace(
        owner_user_id='admin',
        name='User Workspace',
        workspace_type='CONVERSATION',
    )
    assert isinstance(user_ws_id, (int, str))
    assert user_ws_id > 0 if isinstance(user_ws_id, int) else user_ws_id.startswith('WS_')
    print(f"PASS: test_create_workspace_user_owned (id={user_ws_id})")


def test_create_workspace_system_owned():
    global system_ws_id
    system_ws_id = workspace_api.create_workspace(
        owner_user_id=None,
        name='System Workspace',
        workspace_type='AUTONOMOUS',
    )
    assert isinstance(system_ws_id, (int, str))
    assert system_ws_id > 0 if isinstance(system_ws_id, int) else system_ws_id.startswith('WS_')
    print(f"PASS: test_create_workspace_system_owned (id={system_ws_id})")


def test_get_workspace():
    ws = workspace_api.get_workspace(user_ws_id)
    assert ws is not None
    assert ws['workspace_name'] == 'User Workspace'
    assert ws['status'] == 'ACTIVE'
    assert ws['isolation_mode'] == 'SHARED'
    print(f"PASS: test_get_workspace (name={ws['workspace_name']}, status={ws['status']})")


def test_get_user_workspaces():
    workspaces = workspace_api.get_user_workspaces('admin')
    assert len(workspaces) >= 1
    print(f"PASS: test_get_user_workspaces (found={len(workspaces)})")


def test_update_workspace():
    ok = workspace_api.update_workspace(
        user_ws_id,
        status='PAUSED',
        summary='Test summary',
    )
    assert ok
    ws = workspace_api.get_workspace(user_ws_id)
    assert ws['status'] == 'PAUSED'
    assert ws['summary'] == 'Test summary'
    print("PASS: test_update_workspace")


def test_save_checkpoint():
    agent_api.register_agent(TEST_AGENT_1, 'WS Test Agent 1')
    ctx_id = workspace_api.save_context(
        workspace_id=user_ws_id,
        agent_id=TEST_AGENT_1,
        context_type='CHECKPOINT',
        context_data={
            "conversation": [{"role": "user", "content": "hello"}],
            "working_memory": {"findings": ["test"]},
        },
    )
    assert isinstance(ctx_id, (int, str))
    assert ctx_id > 0 if isinstance(ctx_id, int) else ctx_id.startswith('CTX_')
    print(f"PASS: test_save_checkpoint (id={ctx_id})")


def test_get_context_chain():
    workspace_api.save_context(
        workspace_id=user_ws_id,
        agent_id=TEST_AGENT_1,
        context_type='HANDOFF',
        context_data={"info": "handoff data"},
    )
    workspace_api.save_context(
        workspace_id=user_ws_id,
        agent_id=TEST_AGENT_1,
        context_type='SUMMARY',
        context_data={"summary": "final summary"},
    )
    chain = workspace_api.get_context_chain(user_ws_id)
    assert len(chain) == 3
    types = [c['context_type'] for c in chain]
    assert set(types) == {'CHECKPOINT', 'HANDOFF', 'SUMMARY'}
    print(f"PASS: test_get_context_chain (count={len(chain)})")


def test_get_latest_context():
    latest = workspace_api.get_latest_context(user_ws_id)
    assert latest is not None
    assert latest['context_type'] in ('CHECKPOINT', 'HANDOFF', 'SUMMARY')
    print(f"PASS: test_get_latest_context (type={latest['context_type']})")


def test_create_handoff_session():
    global handoff_session_id
    session_id = agent_api.create_session(
        agent_id=TEST_AGENT_1,
        workspace_id=user_ws_id,
        owner_user_id='admin',
    )
    workspace_api.update_workspace(
        user_ws_id,
        current_agent_id=TEST_AGENT_1,
        current_session_id=session_id,
    )
    agent_api.register_agent(TEST_AGENT_2, 'WS Test Agent 2')
    handoff_session_id = workspace_api.create_handoff_session(
        workspace_id=user_ws_id,
        new_agent_id=TEST_AGENT_2,
        handoff_data={'reason': 'test'},
    )
    assert isinstance(handoff_session_id, (int, str))
    assert handoff_session_id > 0 if isinstance(handoff_session_id, int) else len(handoff_session_id) > 0
    ws = workspace_api.get_workspace(user_ws_id)
    assert ws['current_agent_id'] == TEST_AGENT_2
    print(f"PASS: test_create_handoff_session (session={handoff_session_id})")


def test_recover_workspace():
    recovery = workspace_api.recover_workspace(user_ws_id)
    assert isinstance(recovery, dict)
    assert 'workspace' in recovery
    assert 'context_chain' in recovery
    assert 'active_tasks' in recovery
    assert 'recent_sessions' in recovery
    print("PASS: test_recover_workspace")


def test_link_task():
    global test_plan_id
    test_plan_id = task_plan_api.create_plan(
        agent_id=TEST_AGENT_1,
        goal='Test task for workspace link',
    )
    ok = workspace_api.link_task_to_workspace(user_ws_id, test_plan_id)
    assert ok
    tasks = workspace_api.get_workspace_tasks(user_ws_id)
    assert len(tasks) >= 1
    linked_ids = [t['plan_id'] for t in tasks]
    assert test_plan_id in linked_ids
    print(f"PASS: test_link_task (plan_id={test_plan_id})")


def test_entity_isolation():
    global isolated_ws_id, test_entity_id
    isolated_ws_id = workspace_api.create_workspace(
        owner_user_id='admin',
        name='Isolated Workspace',
        workspace_type='CONVERSATION',
        isolation_mode='ISOLATED',
    )
    test_entity_id = memory_api.create_memory(
        'Isolation Test', 'content for isolation', category='test',
    )
    execute(
        "UPDATE ENTITIES SET WORKSPACE_ID = :wid WHERE ENTITY_ID = :eid",
        {"wid": isolated_ws_id, "eid": test_entity_id},
    )
    from lib.connection import execute_query_one
    row = execute_query_one(
        "SELECT WORKSPACE_ID FROM ENTITIES WHERE ENTITY_ID = :eid",
        {"eid": test_entity_id},
    )
    assert row is not None
    assert row['workspace_id'] == isolated_ws_id
    print(f"PASS: test_entity_isolation (ws_id={isolated_ws_id})")


def _cleanup():
    if test_entity_id:
        memory_api.delete_memory(test_entity_id)
    if test_plan_id:
        execute(
            "DELETE FROM WORKSPACE_TASKS WHERE PLAN_ID = :pid",
            {"pid": test_plan_id},
        )
        task_plan_api.delete_plan(test_plan_id)
    for ws_id in [user_ws_id, system_ws_id, isolated_ws_id]:
        if ws_id:
            execute(
                "DELETE FROM WORKSPACE_CONTEXT WHERE WORKSPACE_ID = :wid",
                {"wid": ws_id},
            )
            execute(
                "DELETE FROM WORKSPACE_TASKS WHERE WORKSPACE_ID = :wid",
                {"wid": ws_id},
            )
            execute(
                "DELETE FROM AGENT_SESSION WHERE WORKSPACE_ID = :wid",
                {"wid": ws_id},
            )
            execute(
                "DELETE FROM WORKSPACES WHERE WORKSPACE_ID = :wid",
                {"wid": ws_id},
            )
    for agent_id in [TEST_AGENT_1, TEST_AGENT_2]:
        execute(
            "DELETE FROM AGENT_SESSION WHERE AGENT_ID = :aid",
            {"aid": agent_id},
        )
        execute(
            "DELETE FROM AGENT_COLLABORATION WHERE SOURCE_AGENT_ID = :aid OR TARGET_AGENT_ID = :aid",
            {"aid": agent_id},
        )
        execute(
            "DELETE FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
            {"aid": agent_id},
        )


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_create_workspace_user_owned,
        test_create_workspace_system_owned,
        test_get_workspace,
        test_get_user_workspaces,
        test_update_workspace,
        test_save_checkpoint,
        test_get_context_chain,
        test_get_latest_context,
        test_create_handoff_session,
        test_recover_workspace,
        test_link_task,
        test_entity_isolation,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    _cleanup()
    close_pool()
    print(f"\nWorkspace Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
