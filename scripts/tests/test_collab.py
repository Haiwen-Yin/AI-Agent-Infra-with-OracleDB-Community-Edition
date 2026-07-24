"""AI Agent Infra v4.1.0 - Collaboration Group API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.collab_api import (
    create_collab_group, get_collab_group, update_collab_group,
    add_group_member, remove_group_member, list_group_members,
    get_agent_groups, share_memory_to_group, get_group_shared_memories,
    delete_collab_group
)
from lib.agent_api import register_agent
from lib.connection import close_pool

_group_id = None


def _ensure_agents():
    for aid, name in [("collab-lead", "Collab Lead"), ("collab-member", "Collab Member"), ("collab-observer", "Collab Observer")]:
        try:
            register_agent(aid, name, agent_type="test")
        except Exception:
            pass


def test_create_collab_group():
    global _group_id
    _ensure_agents()
    _group_id = create_collab_group(
        name="Test Collab Group",
        group_type="PROJECT",
        description="A test collaboration group",
        coordinator_agent_id="collab-lead",
        sharing_policy="OPEN",
    )
    assert isinstance(_group_id, (int, str))
    assert _group_id > 0 if isinstance(_group_id, int) else len(_group_id) > 0
    print(f"PASS: test_create_collab_group (id={_group_id})")


def test_get_collab_group():
    group = get_collab_group(_group_id)
    assert group is not None
    assert group["group_name"] == "Test Collab Group"
    assert group["workspace_id"] is not None
    print(f"PASS: test_get_collab_group (name={group['group_name']})")


def test_update_collab_group():
    ok = update_collab_group(_group_id, description="Updated description")
    assert ok
    group = get_collab_group(_group_id)
    assert group["description"] == "Updated description"
    print("PASS: test_update_collab_group")


def test_add_member_lead():
    mid = add_group_member(_group_id, "collab-lead", role="LEAD")
    assert isinstance(mid, (int, str))
    assert mid > 0 if isinstance(mid, int) else len(mid) > 0
    group = get_collab_group(_group_id)
    members = group.get("members", [])
    lead = [m for m in members if m.get("agent_id") == "collab-lead"]
    assert len(lead) >= 1
    assert lead[0].get("personal_workspace_id") is not None
    print(f"PASS: test_add_member_lead (mid={mid})")


def test_add_member_contributor():
    mid = add_group_member(_group_id, "collab-member", role="CONTRIBUTOR")
    assert isinstance(mid, (int, str))
    print(f"PASS: test_add_member_contributor (mid={mid})")


def test_add_member_observer():
    mid = add_group_member(_group_id, "collab-observer", role="OBSERVER")
    assert isinstance(mid, (int, str))
    print(f"PASS: test_add_member_observer (mid={mid})")


def test_list_group_members():
    members = list_group_members(_group_id)
    assert len(members) >= 3
    print(f"PASS: test_list_group_members (count={len(members)})")


def test_get_agent_groups():
    groups = get_agent_groups("collab-lead")
    assert len(groups) >= 1
    print(f"PASS: test_get_agent_groups (found={len(groups)})")


def test_share_memory_to_group():
    entity_id = share_memory_to_group(
        agent_id="collab-lead",
        group_id=_group_id,
        title="Shared Memory Test",
        content="This is a shared memory item",
        category="test-collab",
        importance=5,
    )
    assert isinstance(entity_id, (int, str))
    assert entity_id > 0 if isinstance(entity_id, int) else len(entity_id) > 0
    print(f"PASS: test_share_memory_to_group (id={entity_id})")


def test_get_group_shared_memories():
    memories = get_group_shared_memories(_group_id)
    assert len(memories) >= 1
    print(f"PASS: test_get_group_shared_memories (found={len(memories)})")


def test_remove_member():
    ok = remove_group_member(_group_id, "collab-observer")
    assert ok
    members = list_group_members(_group_id)
    active = [m for m in members if m.get("status") != "LEFT"]
    assert len(active) < 3
    print("PASS: test_remove_member")


def test_delete_collab_group():
    ok = delete_collab_group(_group_id)
    assert ok
    group = get_collab_group(_group_id)
    assert group is None
    print("PASS: test_delete_collab_group")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_create_collab_group,
        test_get_collab_group,
        test_update_collab_group,
        test_add_member_lead,
        test_add_member_contributor,
        test_add_member_observer,
        test_list_group_members,
        test_get_agent_groups,
        test_share_memory_to_group,
        test_get_group_shared_memories,
        test_remove_member,
        test_delete_collab_group,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nCollab Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
