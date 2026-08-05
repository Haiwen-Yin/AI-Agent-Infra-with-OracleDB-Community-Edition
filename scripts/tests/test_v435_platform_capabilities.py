"""Focused v4.3.5 database-authoritative capability boundary tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lib import platform_capabilities


class _Tx:
    def __init__(self, rows: dict[str, str], version: int = 1) -> None:
        self.rows = rows
        self.version = version
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def query_one(self, sql: str, params: dict[str, Any]):
        key = str(params["key"])
        enabled = self.rows.get(key)
        if enabled is None:
            return None
        if "VERSION" in sql:
            return {"capability_key": key, "enabled": enabled, "mandatory": "N", "version": self.version}
        return {"enabled": enabled}

    def execute(self, sql: str, params: dict[str, Any]):
        self.executed.append((sql, params))
        if sql.startswith("UPDATE CX_PLATFORM_CAPABILITIES"):
            self.rows[str(params["key"])] = str(params["enabled"])
        return 1


def test_mandatory_capability_cannot_be_disabled(monkeypatch):
    with pytest.raises(platform_capabilities.CapabilityError, match="Mandatory"):
        platform_capabilities.set_enabled("admin", "security", False, "security must remain", 1)


def test_dependent_capability_blocks_prerequisite_disable(monkeypatch):
    tx = _Tx({"tasks": "Y", "branches": "Y", "loops": "N", "graph": "N"})
    monkeypatch.setattr(platform_capabilities.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(platform_capabilities.CapabilityConflict, match="branches"):
        platform_capabilities.set_enabled("admin", "tasks", False, "reduce product scope", 1)


def test_enable_requires_enabled_dependencies(monkeypatch):
    tx = _Tx({"branches": "N", "tasks": "N", "workspaces": "Y"})
    monkeypatch.setattr(platform_capabilities.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(platform_capabilities.CapabilityConflict, match="tasks"):
        platform_capabilities.set_enabled("admin", "branches", True, "enable branches", 1)


def test_optimistic_version_conflict_is_rejected(monkeypatch):
    tx = _Tx({"monitor": "Y"}, version=3)
    monkeypatch.setattr(platform_capabilities.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(platform_capabilities.CapabilityConflict, match="concurrently"):
        platform_capabilities.set_enabled("admin", "monitor", False, "reduce product scope", 2)


def test_state_history_and_security_audit_share_one_transaction(monkeypatch):
    tx = _Tx({"monitor": "Y"})
    monkeypatch.setattr(platform_capabilities.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(platform_capabilities.identity_api, "_audit_tx", lambda *args: tx.executed.append(("AUDIT", {})))
    monkeypatch.setattr(platform_capabilities, "list_capabilities", lambda limit=20: {"items": [{"capability_key": "monitor", "effective_enabled": False}]})
    result = platform_capabilities.set_enabled("admin", "monitor", False, "customer scope change", 1)
    sql = [statement for statement, _ in tx.executed]
    assert any("CX_PLATFORM_CAPABILITY_HISTORY" in statement for statement in sql)
    assert sql[-1] == "AUDIT"
    assert result["effective_enabled"] is False


def test_edition_unavailable_capability_cannot_be_enabled(monkeypatch):
    monkeypatch.setattr(platform_capabilities, "_edition_available", lambda key: key != "compliance")
    with pytest.raises(platform_capabilities.CapabilityError, match="unavailable"):
        platform_capabilities.set_enabled("admin", "compliance", True, "attempt edition escape", 1)


def test_page_states_uses_one_authoritative_database_read(monkeypatch):
    calls = []
    rows = [{"capability_key": key, "enabled": "Y"} for key in platform_capabilities.REGISTRY]
    monkeypatch.setattr(platform_capabilities.connection, "execute_query", lambda sql: calls.append(sql) or rows)
    states = platform_capabilities.page_states()
    assert states["monitor"] is True and states["platform"] is True
    assert len(calls) == 1


def test_audit_failure_propagates_and_prevents_false_success(monkeypatch):
    tx = _Tx({"monitor": "Y"})
    monkeypatch.setattr(platform_capabilities.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(platform_capabilities.identity_api, "_audit_tx", lambda *args: (_ for _ in ()).throw(RuntimeError("audit unavailable")))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        platform_capabilities.set_enabled("admin", "monitor", False, "audited state change", 1)


def test_migrations_define_history_dependencies_and_no_secret_values():
    for database in ("oracle", "pg", "yashandb"):
        test_root = Path(__file__).resolve()
        source_path = next(
            candidate for candidate in (
                test_root.parents[2] / "adapters" / database / "deploy" / "31_v4_3_5_platform_capabilities.sql",
                test_root.parents[1] / "deploy" / "31_v4_3_5_platform_capabilities.sql",
            ) if candidate.is_file()
        )
        source = source_path.read_text(encoding="utf-8").upper()
        assert "CX_PLATFORM_CAPABILITIES" in source
        assert "CX_PLATFORM_CAPABILITY_DEPENDENCIES" in source
        assert "CX_PLATFORM_CAPABILITY_HISTORY" in source
        assert "PRIVATE_KEY" not in source and "CLIENT_SECRET" not in source and "PASSWORD" not in source


def test_dashboard_exposes_bilingual_protected_configuration_page():
    test_root = Path(__file__).resolve()
    source_path = next(
        candidate for candidate in (
            test_root.parents[1] / "web" / "src" / "App.tsx",
            test_root.parents[2] / "web" / "src" / "App.tsx",
        ) if candidate.is_file()
    )
    source = source_path.read_text(encoding="utf-8")
    assert '["platform", "功能配置", "Capabilities", Settings2]' in source
    assert 'role="switch"' in source
    assert "受保护视图" in source
    assert "expected_version" in source
    assert "变更原因（必填）" in source
