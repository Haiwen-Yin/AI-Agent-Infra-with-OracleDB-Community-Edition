"""Focused source and service tests for v4.3.7 deployment and Embedding governance."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

from lib import connection_crypto, deployment_orchestrator, embedding_governance


class _Tx:
    strict_audit = True

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def query_one(self, sql: str, params: dict[str, Any]):
        if "CX_EMBEDDING_PROFILES" in sql:
            return None
        return None

    def execute(self, sql: str, params: dict[str, Any]):
        self.executed.append((sql, dict(params)))
        return 1


def test_embedding_api_key_is_encrypted_in_config(tmp_path, monkeypatch):
    key = b"k" * 32
    monkeypatch.setattr(connection_crypto, "get_master_key", lambda: key)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "embedding": {"api_url": "https://embedding.example/v1", "api_key": "secret-value", "model": "m", "dimension": 8},
        "llm": {"api_key": "llm-secret"},
    }), encoding="utf-8")

    assert connection_crypto.auto_encrypt_config(config) is True
    raw = json.loads(config.read_text(encoding="utf-8"))
    assert "api_key" not in raw["embedding"]
    assert raw["embedding"]["_encrypted"].startswith(connection_crypto.ENVELOPE_PREFIX)
    assert connection_crypto.decrypt_embedding_section(raw["embedding"])["api_key"] == "secret-value"


def test_profile_persists_model_fingerprint_and_never_returns_cipher(monkeypatch):
    tx = _Tx()
    monkeypatch.setattr(embedding_governance.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(embedding_governance.identity_api, "_audit_tx", lambda *args: None)
    monkeypatch.setattr(embedding_governance, "_dialect", lambda: "postgresql")
    result = embedding_governance.upsert_profile(
        "admin", profile_key="enterprise-default", provider_url="https://embedding.example/v1",
        model_id="embedding-v1", execution_mode="ENTERPRISE_DIRECT", dimension=1024,
        reason="configure the governed profile", model_fingerprint="sha256:model-v1",
    )
    assert result["profile_key"] == "enterprise-default"
    statement, params = next((item for item in tx.executed if "INSERT INTO CX_EMBEDDING_PROFILES" in item[0]))
    assert "MODEL_FINGERPRINT" in statement
    assert params["model_fingerprint"] == "sha256:model-v1"
    assert "api_key" not in result


def test_manifest_has_deterministic_base_actions_for_all_databases():
    root = Path(__file__).resolve().parents[2]
    for database in ("oracle", "pg", "yashandb"):
        actions = deployment_orchestrator.manifest(database, "enterprise", root)
        assert actions and all(item.path.is_file() for item in actions)
        assert [item.key for item in actions] == sorted(item.key for item in actions)


def test_precomputed_import_and_none_do_not_need_platform_provider():
    assert embedding_governance._validated_dimension(1024, "PRECOMPUTED_IMPORT") == 1024
    assert embedding_governance._validated_dimension(0, "NONE") == 0
    with pytest.raises(embedding_governance.EmbeddingGovernanceError):
        embedding_governance._validated_dimension(0, "ENTERPRISE_DIRECT")


def test_draft_embedding_probe_never_persists_or_returns_api_key(monkeypatch):
    tx = _Tx()
    audit: list[tuple[Any, ...]] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _amount):
            return json.dumps({"model": "embedding-v1", "data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()

    monkeypatch.setattr(embedding_governance.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(embedding_governance.identity_api, "_audit_tx", lambda *args: audit.append(args))
    monkeypatch.setattr(embedding_governance, "_physical_dimension", lambda _profile: None)
    monkeypatch.setattr(embedding_governance.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    result = embedding_governance.probe_draft(
        "admin", profile_key="draft-profile", provider_url="https://embedding.example/v1",
        model_id="embedding-v1", execution_mode="PLATFORM_MANAGED", dimension=3,
        distance_metric="COSINE", normalize_vectors=True, api_key="never-persist-this",
        secret_reference="", reason="verify before creation",
    )

    assert result["status"] == "VERIFIED"
    assert "never-persist-this" not in json.dumps(result)
    assert "never-persist-this" not in repr(audit)
    assert not tx.executed


def test_platform_embedding_activation_only_binds_parameters_used_by_sql(monkeypatch):
    """Oracle rejects surplus named binds, so activation statements must be exact."""
    tx = _Tx()
    monkeypatch.setattr(embedding_governance.connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(embedding_governance.identity_api, "_audit_tx", lambda *args: None)
    monkeypatch.setattr(
        embedding_governance,
        "probe_draft",
        lambda *_args, **_kwargs: {
            "status": "VERIFIED",
            "result": {
                "observed_dimension": 3,
                "observed_model": "embedding-v1",
                "response_digest": "a" * 64,
            },
        },
    )

    result = embedding_governance.activate_platform_embedding(
        "admin", profile_key="platform-default", provider_url="https://embedding.example/v1",
        model_id="embedding-v1", execution_mode="PLATFORM_MANAGED", dimension=3,
        reason="activate verified platform embedding",
    )

    assert result["validation_state"] == "VERIFIED"
    profile_sql, profile_params = next(item for item in tx.executed if "INSERT INTO CX_EMBEDDING_PROFILES" in item[0])
    placeholders = set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", profile_sql))
    assert set(profile_params) == placeholders
    assert "normalize_value" not in profile_params

    contract_sql, contract_params = next(item for item in tx.executed if "INSERT INTO CX_EMBEDDING_CONTRACTS" in item[0])
    contract_placeholders = set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", contract_sql))
    assert set(contract_params) == contract_placeholders
    # Oracle reserves MODE in bind contexts (ORA-01745). Keep the portable
    # SQL explicit about the semantic field rather than using a short alias.
    assert ":mode" not in contract_sql
    assert ":execution_mode" in contract_sql


def test_shared_runtime_sql_does_not_use_known_oracle_reserved_binds():
    root = Path(__file__).resolve().parents[1]
    for name, reserved in (
        ("embedding_api.py", ("mode", "desc")),
        ("embedding_governance.py", ("mode",)),
        ("identity_api.py", ("mode",)),
        ("deployment_orchestrator.py", ("mode", "order")),
    ):
        source = (root / "lib" / name).read_text(encoding="utf-8")
        for bind in reserved:
            assert not re.search(rf":{bind}\b", source)


def test_dashboard_uses_draft_probe_before_enabling_embedding_profile_creation():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    app = (root / "web_app.py").read_text(encoding="utf-8")
    assert "/api/embedding/profiles/probe-draft" in ui
    assert "testedDraftVersion !== draftVersion" in ui
    assert '@app.post("/api/embedding/profiles/probe-draft")' in app


def test_embedding_readiness_returns_display_key_and_dashboard_wraps_internal_ids():
    root = Path(__file__).resolve().parents[1]
    governance = (root / "lib" / "embedding_governance.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert "SELECT SPACE_ID,SPACE_KEY,CONTRACT_ID" in governance
    assert '"space_key": default.get("space_key")' in governance
    assert 'className="metric-value metric-identifier"' in ui
    assert 'className="cx-form-hint metric-metadata"' in ui
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert ".metric-metadata code" in css


def test_deployed_platform_embedding_is_runtime_immutable_and_dashboard_is_read_only():
    root = Path(__file__).resolve().parents[1]
    governance = (root / "lib" / "embedding_governance.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "Platform Embedding is already deployed; redeploy the platform" in governance
    assert '"platform_deployed": deployed' in governance
    assert "const embeddingDeployed = Boolean(readiness.platform_deployed);" in ui
    assert "canManage && !embeddingDeployed" in ui
    assert "统一 Embedding 已完成配置" in ui
    assert "通过重新部署完成变更" in ui


def test_all_adapters_declare_fingerprint_and_space_isolation():
    root = Path(__file__).resolve().parents[2]
    adapters = root / "adapters"
    scripts = (
        [adapters / database / "deploy" / "33_v4_3_7_bootstrap_embedding.sql" for database in ("oracle", "pg", "yashandb")]
        if adapters.is_dir()
        else [root / "scripts" / "deploy" / "33_v4_3_7_bootstrap_embedding.sql"]
    )
    for script in scripts:
        source = script.read_text(encoding="utf-8").upper()
        for marker in ("CX_DEPLOYMENT_RUNS", "CX_EMBEDDING_PROFILES", "MODEL_FINGERPRINT", "EMBEDDING_SPACE_ID", "EMBEDDING_CONTRACT_ID"):
            assert marker in source
