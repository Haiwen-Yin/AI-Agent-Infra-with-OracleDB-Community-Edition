from typing import Any

import pytest

from lib import platform_governance_graph


class ProjectionDb:
    DATABASE_DIALECT = "postgresql"

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        if "COUNT(*) AS CNT" in sql:
            return {"cnt": 2}
        return {}


def test_projection_is_permission_checked_and_bounded(monkeypatch):
    monkeypatch.setattr(platform_governance_graph, "connection", ProjectionDb())
    monkeypatch.setattr(platform_governance_graph.identity_api, "effective_access", lambda *_args, **_kwargs: {"decision": "DENY"})
    with pytest.raises(PermissionError):
        platform_governance_graph.governance_projection("user")

    monkeypatch.setattr(platform_governance_graph.identity_api, "effective_access", lambda *_args, **_kwargs: {"decision": "ALLOW"})
    monkeypatch.setattr(platform_governance_graph.platform_agent_pool, "safe_autonomy_policy", lambda: {"state": "DISABLED"})
    with pytest.raises(ValueError, match="1, 3, 5, or 10"):
        platform_governance_graph.governance_projection("admin", 2)
    result = platform_governance_graph.governance_projection("admin", 5)
    assert result["read_only"] is True
    assert result["refresh_interval_seconds"] == 5
    assert result["metrics"]["managed_nodes"] == 2
    assert {node["key"] for node in result["nodes"]} >= {"platform", "agent_pool", "graph"}


def test_web_route_uses_module_alias_instead_of_function_self_reference():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    web_path = root / "shared" / "web_app.py"
    if not web_path.is_file():
        web_path = root / "scripts" / "web_app.py"
    web = web_path.read_text(encoding="utf-8")
    route = web.split("def platform_governance_graph(", 1)[1].split("def platform_capability_configuration", 1)[0]
    assert "governance_graph_module.governance_projection" in route
