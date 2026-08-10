"""Focused source and service tests for v4.3.7 deployment and Embedding governance."""

from __future__ import annotations

import json
from pathlib import Path
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
