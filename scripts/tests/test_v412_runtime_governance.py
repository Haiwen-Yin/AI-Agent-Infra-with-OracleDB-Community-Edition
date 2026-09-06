"""Startup mode must not certify or override database governance."""

import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib import platform_capabilities as pc


@pytest.fixture
def states(monkeypatch):
    rows = [{"CAPABILITY_KEY": key, "ENABLED": "Y", "MANDATORY": "Y" if meta.get("mandatory") else "N"}
            for key, meta in pc.REGISTRY.items()]
    monkeypatch.setattr(pc.connection, "execute_query", lambda *a, **k: rows)
    monkeypatch.setattr(pc, "_edition_available", lambda key: True)
    return rows


def test_complete_registry_is_loaded_not_production_certified(states):
    result = pc.governance_status()
    assert result["status"] == "available"
    assert "production_ready" not in result
    assert result["summary"]["total"] == len(pc.REGISTRY)
    assert result["summary"]["required_enabled"] == result["summary"]["required_total"]
    assert result["summary"]["enabled"] == len(pc.REGISTRY)


@pytest.mark.parametrize("change", ["missing", "invalid", "duplicate", "database"])
def test_unreadable_registry_is_unavailable(states, monkeypatch, change):
    if change == "missing":
        states.pop()
    elif change == "invalid":
        states[0]["ENABLED"] = None
    elif change == "duplicate":
        states.append(states[0])
    else:
        def fail(*a, **k):
            raise RuntimeError("private connection detail")
        monkeypatch.setattr(pc.connection, "execute_query", fail)
    with pytest.raises(pc.CapabilityServiceUnavailable) as caught:
        pc.governance_status()
    assert caught.value.reason_code == {"missing": "registry_incomplete", "duplicate": "registry_incomplete", "invalid": "registry_invalid", "database": "database_unavailable"}[change]


@pytest.mark.parametrize("key", ["identity", "tasks"])
def test_disabled_mandatory_or_dependency_is_degraded(states, key):
    next(row for row in states if row["CAPABILITY_KEY"] == key)["ENABLED"] = "N"
    result = pc.governance_status()
    assert result["status"] == "degraded"
    if key == "tasks":
        graph = next(item for item in result["items"] if item["capability_key"] == "graph")
        assert graph["missing_dependencies"] == ["tasks"]
    else:
        assert result["summary"]["required_enabled"] == result["summary"]["required_total"] - 1


def test_optional_disabled_and_edition_restrictions_are_separate(states, monkeypatch):
    next(row for row in states if row["CAPABILITY_KEY"] == "monitor")["ENABLED"] = "N"
    monkeypatch.setattr(pc, "_edition_available", lambda key: key != "approvals")
    result = pc.governance_status()
    assert result["status"] == "available"
    assert result["summary"]["disabled"] == 1
    assert result["summary"]["edition_unavailable"] == 1
    assert result["summary"]["enabled"] + 2 == result["summary"]["total"]
    assert result["summary"]["dependency_issues"] == 0


@pytest.mark.parametrize("unavailable", [False, True])
def test_production_startup_cannot_promote_database_capabilities(states, monkeypatch, unavailable):
    for row in states:
        if row["CAPABILITY_KEY"] in {"channels", "barriers", "graph"}:
            row["ENABLED"] = "N"
    if unavailable:
        states.clear()
    path = Path(__file__).resolve().parents[1] / "web_app.py"
    node = next(n for n in ast.parse(path.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == "runtime_profile")
    node.decorator_list = []
    node.returns = None
    namespace = {"_runtime_profile": lambda: "production",
                 "_edition_features": lambda: SimpleNamespace(GRAPH_ENGINEERING_ENABLED=True),
                 "_schema_owner_context": nullcontext, "platform_capabilities": pc}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    result = namespace["runtime_profile"]()
    assert result["startup_mode"] == "production"
    assert result["capabilities"]["production_ready"] is None
    assert all(result["capabilities"][key] is False for key in ("channels", "barriers", "graph_engineering", "graph_preview"))
    if unavailable:
        assert result["governance"] == {"source": "database", "status": "unavailable", "reason_code": "registry_incomplete"}
