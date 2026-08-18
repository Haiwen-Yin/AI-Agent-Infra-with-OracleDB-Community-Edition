from typing import Any

import pytest

from lib import native_agent_api


class KnowledgeConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self, row: dict[str, Any] | None):
        self.row = row
        self.query_one_calls: list[tuple[str, dict[str, Any]]] = []

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        self.query_one_calls.append((sql, dict(params or {})))
        return self.row


@pytest.fixture
def authorized(monkeypatch):
    monkeypatch.setattr(
        native_agent_api.identity_api, "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(native_agent_api.identity_api, "_audit", lambda *_args, **_kwargs: None)


def test_scoped_knowledge_migration_is_idempotent_and_digest_checked():
    content = {"scope": "database_control_plane"}
    digest = native_agent_api._digest(content)

    class Tx:
        def __init__(self):
            self.inserts = []

        def query_one(self, sql, params):
            if "CX_NATIVE_MANIFESTS" in sql:
                return {"manifest_id": "AM", "content_json": native_agent_api._json(content),
                        "content_digest": digest, "signature": "BUILTIN-SHA256:" + digest,
                        "signature_status": "VERIFIED_BUILTIN", "status": "PUBLISHED", "managed": "Y"}
            return None

        def execute(self, sql, params):
            self.inserts.append((sql, params))

    tx = Tx()
    result = native_agent_api._ensure_platform_knowledge(tx)
    assert result["status"] == "MIGRATED"
    assert len(tx.inserts) == 1

    class ExistingTx(Tx):
        def query_one(self, sql, params):
            if "CX_PLATFORM_KNOWLEDGE" in sql:
                return {"knowledge_id": result["knowledge_id"], "content_digest": digest}
            return super().query_one(sql, params)

    existing = ExistingTx()
    assert native_agent_api._ensure_platform_knowledge(existing)["status"] == "MIGRATED"
    assert not existing.inserts


def test_knowledge_read_is_agent_and_scope_filtered(authorized, monkeypatch):
    content = {"scope": "database_control_plane"}
    db = KnowledgeConnection({"content_json": native_agent_api._json(content),
                              "content_digest": native_agent_api._digest(content),
                              "signature_status": "VERIFIED_BUILTIN"})
    monkeypatch.setattr(native_agent_api, "connection", db)
    result = native_agent_api.management_template_knowledge(
        "admin", native_agent_api.PLATFORM_ADMIN_AGENT_ID, "zh",
    )
    assert result["response_language"] == "zh"
    sql, params = db.query_one_calls[0]
    assert "CX_PLATFORM_KNOWLEDGE" in sql
    assert params["knowledge_key"] == "platform-admin-knowledge"
    assert params["audience"] == "MANAGEMENT_AGENTS"
    assert params["scope"] == "MANAGEMENT_AGENT"


def test_compliance_knowledge_is_exactly_role_scoped(authorized, monkeypatch):
    content = {"scope": "compliance_control_plane"}
    db = KnowledgeConnection({"content_json": native_agent_api._json(content),
                              "content_digest": native_agent_api._digest(content),
                              "signature_status": "VERIFIED_BUILTIN"})
    monkeypatch.setattr(native_agent_api, "connection", db)
    native_agent_api.management_template_knowledge(
        "admin", native_agent_api.COMPLIANCE_ADMIN_AGENT_ID, "zh",
    )
    sql, params = db.query_one_calls[0]
    assert params["knowledge_key"] == "compliance-admin-knowledge"
    assert params["version"] == 1
    assert params["audience"] == "COMPLIANCE_ADMIN"
    assert params["scope"] == "COMPLIANCE_AGENT"
    assert "AUDIENCE IN" not in sql


def test_projection_is_source_only_and_fails_closed(authorized, monkeypatch):
    content = {"scope": "compliance_control_plane"}
    db = KnowledgeConnection(None)
    monkeypatch.setattr(native_agent_api, "connection", db)
    with pytest.raises(native_agent_api.NativeAgentError, match="not initialized"):
        native_agent_api.management_knowledge_projection(
            "admin", native_agent_api.COMPLIANCE_ADMIN_AGENT_ID,
        )

    db.row = {"content_json": native_agent_api._json(content),
              "content_digest": native_agent_api._digest(content),
              "signature_status": "VERIFIED_BUILTIN"}
    projection = native_agent_api.management_knowledge_projection(
        "admin", native_agent_api.COMPLIANCE_ADMIN_AGENT_ID,
    )
    assert projection["projection_mode"] == "SIGNED_SOURCE_ONLY"
    assert projection["chunk_projection"] == "UNAVAILABLE"
    assert projection["vector_projection"] == "UNAVAILABLE"


def test_knowledge_read_rejects_invalid_digest(authorized, monkeypatch):
    content = {"scope": "database_control_plane"}
    db = KnowledgeConnection({"content_json": native_agent_api._json(content),
                              "content_digest": "0" * 64,
                              "signature_status": "VERIFIED_BUILTIN"})
    monkeypatch.setattr(native_agent_api, "connection", db)
    with pytest.raises(native_agent_api.NativeAgentError, match="not verified"):
        native_agent_api.management_template_knowledge(
            "admin", native_agent_api.PLATFORM_ADMIN_AGENT_ID,
        )


def test_knowledge_read_rejects_non_management_agent(authorized):
    with pytest.raises(native_agent_api.NativeAgentError, match="limited to built-in management"):
        native_agent_api.management_template_knowledge("admin", "PA_BUSINESS")
