"""Source and adapter contract tests for v4.3.6 native Agent provisioning."""

from pathlib import Path
from typing import Any

import pytest

from lib import native_agent_api
from lib import deployment_adapters


class _Tx:
    def __init__(self, state: str = "ENABLED", version: int = 1) -> None:
        self.state = state
        self.version = version
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def query_one(self, sql: str, params: dict[str, Any]):
        text = sql.upper()
        if "CX_EXTERNAL_AGENT_POLICY" in text:
            return {"policy_key": "external_agent_registration", "state": self.state, "version": self.version}
        return None

    def execute(self, sql: str, params: dict[str, Any]):
        self.executed.append((sql, params))
        if sql.startswith("UPDATE CX_EXTERNAL_AGENT_POLICY"):
            self.state = str(params["state"])
            self.version += 1
        return 1


def test_registration_policy_rejects_stale_version(monkeypatch):
    tx = _Tx(version=4)
    monkeypatch.setattr(native_agent_api.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(native_agent_api.NativeAgentConflict, match="concurrently"):
        native_agent_api.set_external_registration_policy("admin", "DISABLED", "stop enrollment", 3)


def test_registration_policy_writes_history_and_audit(monkeypatch):
    tx = _Tx()
    monkeypatch.setattr(native_agent_api.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(native_agent_api, "_audit", lambda *args: tx.executed.append(("AUDIT", {})))
    result = native_agent_api.set_external_registration_policy("admin", "APPROVAL_ONLY", "require review", 1)
    assert result["state"] == "APPROVAL_ONLY"
    sql = "\n".join(item[0] for item in tx.executed)
    assert "CX_EXTERNAL_AGENT_POLICY_HISTORY" in sql
    assert "AUDIT" in sql


def test_runtime_pool_uses_database_fencing_and_fresh_input():
    source = (Path(__file__).resolve().parents[1] / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    runtime = (Path(__file__).resolve().parents[1] / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    assert "FENCING_TOKEN=FENCING_TOKEN+1" in source
    assert "INPUT_JSON" in source
    assert "fresh in-memory message list" in runtime
    assert "API_KEY_CIPHER" in runtime
    assert "logger.info(\"Native execution failed: %s\", type(exc).__name__)" in runtime
    assert "messages" not in runtime.split("logger.info(\"Native execution failed", 1)[1]


def test_all_adapters_ship_v436_migration_without_plaintext_secret_columns():
    root = Path(__file__).resolve().parents[2]
    if (root / "adapters").is_dir():
        paths = [root / "adapters" / database / "deploy" / "32_v4_3_6_native_agents.sql" for database in ("oracle", "pg", "yashandb")]
    else:
        paths = [Path(__file__).resolve().parents[1] / "deploy" / "32_v4_3_6_native_agents.sql"]
    for path in paths:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8").upper()
        for token in ("CX_NATIVE_BOOTSTRAP", "CX_AGENT_TEMPLATES", "CX_NATIVE_MANIFESTS", "CX_NATIVE_AGENTS",
                      "CX_LLM_PROVIDER_PROFILES", "CX_DEPLOYMENT_TARGETS",
                      "CX_NATIVE_PROVISION_REQUESTS", "CX_RUNTIME_WORKERS",
                      "CX_RUNTIME_EXECUTIONS", "CX_EXTERNAL_AGENT_POLICY"):
            assert token in text
        assert "PRIVATE_KEY" not in text
        assert "PASSWORD" not in text


def test_builtin_templates_include_sensitive_profiles_and_locked_fields():
    keys = {item[0] for item in native_agent_api.BUILTIN_TEMPLATES}
    assert {"platform-admin", "compliance-admin", "code-development", "production-operations"} <= keys
    for _, _, _, content in native_agent_api.BUILTIN_TEMPLATES:
        assert content["locked_fields"]
        assert content["isolation_level"] in native_agent_api.ISOLATION_LEVELS
    assert {item[0] for item in native_agent_api.BUILTIN_MANIFESTS} >= {
        "platform-admin-tools", "restricted-agent-skills", "platform-admin-knowledge",
    }


def test_dashboard_exposes_governed_deployment_and_native_agents_to_platform_administrators():
    source = (Path(__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    assert '"deployment": "platform.manage"' in source
    assert '"native-agents": "platform.manage"' in source


def test_native_agent_and_embedding_forms_expose_guarded_configuration_controls():
    root = Path(__file__).resolve().parents[1] / "web" / "src"
    ui = (root / "App.tsx").read_text(encoding="utf-8")
    css = (root / "app.css").read_text(encoding="utf-8")
    assert "leave empty to test and save without an API key" in ui
    assert 'name="distance_metric"' in ui
    assert all(metric in ui for metric in ("COSINE", "EUCLIDEAN", "DOT_PRODUCT"))
    assert "config-multiline" in ui
    assert "this does not make Agents produce identical vectors" in ui
    assert "Configure built-in Agent model" in ui
    assert "Configure and activate" in ui
    assert ".configuration-form" in css and ".policy-form" in css
    assert ".config-field.config-multiline" in css


def test_reference_deployment_adapters_share_lifecycle_without_granting_authority():
    adapters = deployment_adapters.reference_adapters()
    assert set(adapters) == set(deployment_adapters.TARGET_TYPES)
    execution = {"execution_id": "EXE_test", "target_id": "DT_test", "isolation_level": "DOMAIN_ISOLATED"}
    for adapter in adapters.values():
        assert adapter.prepare(execution).status == "READY"
        assert adapter.activate(execution).status == "ACTIVE"
        assert adapter.health(execution).status == "UNKNOWN"
        assert adapter.evidence(execution).evidence["authority"] == "database"
        with pytest.raises(ValueError):
            adapter.cancel(execution, "")


def test_runtime_claim_keeps_select_and_update_bind_sets_separate(monkeypatch):
    calls = []

    class _Connection:
        def execute_query(self, sql, params):
            calls.append(("select", dict(params)))
            return [{"execution_id": "EXE_test", "fencing_token": 4}]

        def execute(self, sql, params):
            calls.append(("update", dict(params)))
            return 1

    fake = _Connection()
    monkeypatch.setattr(native_agent_api, "connection", fake)
    rows = native_agent_api.claim_runtime("worker-1", "node-1", 1)
    assert rows[0]["fencing_token"] == 5
    assert calls[0][0] == "select"
    assert set(calls[0][1]) == {"limit"}
    assert set(calls[1][1]) == {"worker", "node", "id"}


def test_yashandb_runtime_claim_uses_timestamp_compatible_expression(monkeypatch):
    monkeypatch.setattr(native_agent_api.connection, "DATABASE_DIALECT", "yashandb")
    assert native_agent_api._lease_started_sql() == "NVL(STARTED_AT,CURRENT_TIMESTAMP)"
