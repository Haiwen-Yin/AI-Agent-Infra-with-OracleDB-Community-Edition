"""MCP exposure tests for the versioned Memory lifecycle boundary."""

from __future__ import annotations

import asyncio

import pytest

from lib import mcp_server


def test_owned_memory_version_rejects_cross_agent_read(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "execute_query",
        lambda _sql, _params: [{"owner_agent_id": "AGENT-OTHER"}],
    )
    with pytest.raises(PermissionError, match="outside the authenticated Agent scope"):
        mcp_server._owned_memory_version("MV-OTHER-1", "AGENT-CURRENT")


def test_owned_memory_version_accepts_owner(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "execute_query",
        lambda _sql, _params: [{"owner_agent_id": "AGENT-CURRENT"}],
    )
    mcp_server._owned_memory_version("MV-CURRENT-1", "AGENT-CURRENT")


def test_default_mcp_tools_expose_governed_memory_lifecycle(monkeypatch):
    monkeypatch.setattr(mcp_server, "_load_dynamic_tools", lambda: [])
    monkeypatch.setattr(mcp_server, "_authenticated_mcp_agent", lambda: "AGENT-CURRENT")
    tools = asyncio.run(mcp_server.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "memory_lifecycle_create",
        "memory_lifecycle_chain",
        "memory_lifecycle_feedback",
        "memory_lifecycle_candidate",
    } <= names


def test_lifecycle_create_rejects_non_agent_scope(monkeypatch):
    monkeypatch.setattr(mcp_server, "_authenticated_mcp_agent", lambda: "AGENT-CURRENT")
    response = asyncio.run(mcp_server.call_tool("memory_lifecycle_create", {
        "title": "cross scope", "body": "not permitted", "memory_scope": "ENTERPRISE_KNOWLEDGE",
    }))
    assert "limited to Agent-owned scopes" in response[0].text
