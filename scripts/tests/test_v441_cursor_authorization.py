"""Authorization contracts for the v4.4.1 cursor inventory endpoints."""

import pytest

from lib import (
    cursor_pagination,
    knowledge_api,
    memory_lifecycle,
    monitor_api,
    skill_api,
    spec_api,
    task_plan_api,
)


@pytest.fixture
def delegated_scope(monkeypatch):
    """Use a deterministic delegated scope and capture the generated query."""
    captured = []
    monkeypatch.setattr(cursor_pagination, "resolve", lambda *_args: {
        "position": {}, "page_size": 20, "filter_digest": "scope-test",
    })
    monkeypatch.setattr(cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    for module in (knowledge_api, memory_lifecycle, skill_api, spec_api, task_plan_api):
        monkeypatch.setattr(module.identity_api, "effective_access", lambda *_args: {"decision": "DENY"})
        monkeypatch.setattr(module.identity_api, "_agent_visibility_clause", lambda *_args: "SCOPE_CLAUSE(:principal_id)")
        monkeypatch.setattr(module, "execute_query", lambda sql, params, captured=captured: captured.append((sql, params)) or [])
        monkeypatch.setattr(module, "execute_query_one", lambda *_args: {"cnt": 0})
    return captured


@pytest.mark.parametrize("inventory", [
    lambda: task_plan_api.list_plans_cursor("human-1"),
    lambda: knowledge_api.search_knowledge_cursor("human-1"),
    lambda: memory_lifecycle.current_memories_cursor("human-1"),
    lambda: skill_api.list_skills_cursor("human-1"),
    lambda: spec_api.list_specs_cursor("human-1"),
])
def test_delegated_inventory_query_includes_agent_scope(delegated_scope, inventory):
    inventory()
    assert len(delegated_scope) == 1
    sql, params = delegated_scope[0]
    assert "SCOPE_CLAUSE" in sql
    assert params["principal_id"] == "human-1"


def test_administrator_inventory_omits_delegated_scope(monkeypatch):
    captured = []
    monkeypatch.setattr(cursor_pagination, "resolve", lambda *_args: {
        "position": {}, "page_size": 20, "filter_digest": "admin-test",
    })
    monkeypatch.setattr(cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    monkeypatch.setattr(task_plan_api.identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(task_plan_api, "execute_query", lambda sql, params: captured.append((sql, params)) or [])

    task_plan_api.list_plans_cursor("system-admin")

    assert "CX_PRINCIPALS" not in captured[0][0]
    assert "principal_id" not in captured[0][1]


def test_monitor_scope_service_failure_fails_closed(monkeypatch):
    captured = []
    monkeypatch.setattr(cursor_pagination, "resolve", lambda *_args: {
        "position": {}, "page_size": 20, "filter_digest": "monitor-test",
    })
    monkeypatch.setattr(cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    from lib import identity_api
    monkeypatch.setattr(identity_api, "effective_access", lambda *_args: (_ for _ in ()).throw(RuntimeError("scope unavailable")))
    monkeypatch.setattr(monitor_api, "execute_query", lambda sql, params: captured.append((sql, params)) or [])

    monitor_api.get_agent_health_cursor("human-1")

    assert "1=0" in captured[0][0]


def test_cursor_rejects_a_different_authenticated_principal(monkeypatch):
    monkeypatch.setattr(cursor_pagination.connection, "execute_query_one", lambda *_args: None)

    with pytest.raises(cursor_pagination.CursorError, match="authorized inventory"):
        cursor_pagination.resolve("human-2", "skills", {}, "entity_id:asc", 20, "CUR_from_human_1")
