"""Tool import and invocation contracts."""

import json
import socket
from pathlib import Path

import pytest

from lib import tool_registry

ROOT = Path(__file__).resolve().parents[2]


def _spec(server="https://api.example.com/v1"):
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1.2.3"},
        "paths": {
            "/customers/{customer_id}": {
                "get": {
                    "operationId": "get_customer",
                    "summary": "读取客户",
                    "parameters": [
                        {"name": "customer_id", "in": "path", "required": True},
                        {"name": "fields", "in": "query"},
                    ],
                    "responses": {"200": {"content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            }
        },
    }
    if server:
        spec["servers"] = [{"url": server}]
    return spec


def test_openapi_import_binds_server_and_is_idempotent(monkeypatch):
    inserts = []
    updates = []
    existing = {"value": None}
    monkeypatch.setattr(tool_registry, "execute_query_one", lambda *_a, **_k: existing["value"])
    monkeypatch.setattr(tool_registry, "execute_insert_returning_id", lambda _sql, values: inserts.append(values) or "T1")
    monkeypatch.setattr(tool_registry, "execute", lambda sql, values: updates.append((sql, values)) or 1)

    assert tool_registry.import_openapi(_spec(), "crm") == ["T1"]
    schema = json.loads(inserts[0]["in_schema"])
    assert schema["base_url"] == "https://api.example.com/v1"
    assert schema["method"] == "GET"

    existing["value"] = {"tool_id": "T1"}
    assert tool_registry.import_openapi(_spec(), "crm") == ["T1"]
    assert len(inserts) == 1
    assert updates[0][1]["tool_id"] == "T1"


@pytest.mark.parametrize("namespace", ["", " space", "a/b", "x" * 65])
def test_openapi_import_rejects_invalid_namespace_before_write(monkeypatch, namespace):
    monkeypatch.setattr(tool_registry, "execute_insert_returning_id", lambda *_a, **_k: pytest.fail("database write"))
    with pytest.raises(ValueError, match="namespace"):
        tool_registry.import_openapi(_spec(), namespace)


def test_url_import_rejects_private_destination_before_network(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
    ])
    monkeypatch.setattr(tool_registry.urllib.request, "build_opener", lambda *_a: pytest.fail("network opened"))
    with pytest.raises(ValueError, match="Non-public destination"):
        tool_registry.import_from_url("http://localhost/openapi.json", "demo")


def test_invoke_uses_bound_server_and_encodes_parameters(monkeypatch):
    monkeypatch.setattr(tool_registry, "get_tool", lambda _tool_id: {
        "status": "ACTIVE",
        "input_schema": {
            "base_url": "https://api.example.com/v1",
            "path": "/customers/{customer_id}",
            "method": "GET",
            "parameters": [
                {"name": "customer_id", "in": "path"},
                {"name": "fields", "in": "query"},
            ],
        },
    })
    from lib import connection, execution_control
    monkeypatch.setattr(connection, "get_current_agent_id", lambda: "A1")
    monkeypatch.setattr(execution_control, "enqueue_job", lambda _kind, payload, *_a, **_k: {"job_id": "J1", "payload": payload})
    result = tool_registry.invoke_tool("T1", {"customer_id": "a/b", "fields": "name & status"})
    assert result["url"] == "https://api.example.com/v1/customers/a%2Fb?fields=name+%26+status"


def test_tool_import_ui_submits_dashboard_csrf_token():
    source = (ROOT / "shared/web/src/ToolsCatalog.tsx").read_text(encoding="utf-8")
    assert 'localStorage.getItem("cxDashboardCsrf")' in source
    assert 'headers.set("X-CSRF-Token", csrf)' in source
    assert 'fetch("/api/tools/import-openapi"' in source
    assert 'fetch("/api/tools/import-url"' in source


def test_update_tool_validates_status_and_preserves_contract_identity(monkeypatch):
    updates = []
    monkeypatch.setattr(tool_registry, "execute", lambda sql, values: updates.append((sql, values)) or 1)
    assert tool_registry.update_tool("T1", description=" Updated ", status="deprecated")
    sql, values = updates[0]
    assert "TOOL_NAME" not in sql
    assert values == {"description": "Updated", "status": "DEPRECATED", "tool_id": "T1"}
    with pytest.raises(ValueError, match="status"):
        tool_registry.update_tool("T1", description="", status="RETIRED")


def test_tool_catalog_exposes_existing_tool_actions():
    source = (ROOT / "shared/web/src/ToolsCatalog.tsx").read_text(encoding="utf-8")
    assert 'method: "PATCH"' in source
    assert 'method: "DELETE"' in source
    assert 'aria-label={text("查看详情", "View details")}' in source
    assert 'aria-label={text("编辑工具", "Edit tool")}' in source
    assert 'aria-label={text("停用工具", "Retire tool")}' in source
