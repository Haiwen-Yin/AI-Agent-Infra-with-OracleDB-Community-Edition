import json
from unittest.mock import Mock
import pytest
from lib import builtin_knowledge as knowledge

@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(knowledge.identity_api, "effective_access", lambda *_: {"decision":"ALLOW"})
    tx = Mock(query_one=Mock(return_value=None), execute=Mock(return_value=1))
    monkeypatch.setattr(knowledge.connection, "execute_transaction_callback", lambda fn: fn(tx))
    return tx

def test_publish_is_idempotent_and_signed(db):
    result = knowledge.publish("admin", "public-runbook", {"answer":"verified"}, audience="PUBLIC", scope_type="PUBLIC", version=1, reason="seed")
    assert result["status"] == "PUBLISHED" and len(result["digest"]) == 64
    knowledge_calls = [call.args for call in db.execute.call_args_list if "CX_PLATFORM_KNOWLEDGE(" in call.args[0]]
    assert knowledge_calls
    sql, params = knowledge_calls[0]
    assert "VERIFIED_BUILTIN" in sql and params["signature"].startswith("LOCAL-SHA256:")
    chunk_call = next(call.args for call in db.execute.call_args_list if "CX_PLATFORM_KNOWLEDGE_CHUNKS" in call.args[0])
    assert ":chunk_no" in chunk_call[0] and ":number" not in chunk_call[0]
    assert chunk_call[1]["chunk_no"] == 1

def test_immutable_version_rejects_tampering(monkeypatch):
    monkeypatch.setattr(knowledge.identity_api, "effective_access", lambda *_: {"decision":"ALLOW"})
    tx = Mock(query_one=Mock(return_value={"KNOWLEDGE_ID":"k1","CONTENT_DIGEST":"0"*64,"STATUS":"PUBLISHED"}))
    monkeypatch.setattr(knowledge.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(knowledge.KnowledgeLifecycleError): knowledge.publish("admin", "k", {"changed":True}, audience="PUBLIC", scope_type="PUBLIC", version=1, reason="tamper")
    tx.execute.assert_not_called()

def test_withdraw_revokes_chunks_and_is_audited(db):
    result = knowledge.withdraw("admin", "k1", "retire")
    assert result["status"] == "REVOKED"
    sqls = [call.args[0] for call in db.execute.call_args_list]
    assert any("CX_PLATFORM_KNOWLEDGE_CHUNKS" in sql for sql in sqls)
    assert any("STATUS='REVOKED'" in sql for sql in sqls)

def test_invalid_package_rejected_before_write(db):
    with pytest.raises(knowledge.KnowledgeLifecycleError): knowledge.publish("admin", "", [], audience="PUBLIC", scope_type="PUBLIC", version=1, reason="x")
    db.execute.assert_not_called()

@pytest.mark.parametrize("changed", [
    {"dialect": "oracle"}, {"edition": "enterprise"},
    {"audience": "MANAGEMENT_AGENTS"}, {"scope_type": "PLATFORM_GLOBAL"},
])
def test_metadata_cannot_change_on_published_version(db, changed):
    args = dict(audience="PUBLIC", scope_type="PUBLIC", version=1, reason="seed")
    initial = knowledge.publish("admin", "metadata", {"answer": "verified"}, **args)
    db.query_one.return_value = {"KNOWLEDGE_ID": initial["knowledge_id"],
                                "CONTENT_DIGEST": initial["digest"], "STATUS": "PUBLISHED"}
    db.execute.reset_mock()
    with pytest.raises(knowledge.KnowledgeLifecycleError):
        knowledge.publish("admin", "metadata", {"answer": "verified"}, **(args | changed))
    db.execute.assert_not_called()

@pytest.mark.parametrize("key", [" padded", "x" * 129])
def test_invalid_key_does_not_alias_existing_package(db, key):
    with pytest.raises(knowledge.KnowledgeLifecycleError):
        knowledge.publish("admin", key, {}, audience="PUBLIC", scope_type="PUBLIC", version=1, reason="seed")
    db.execute.assert_not_called()

def test_unsupported_audience_rejected_before_write(db):
    with pytest.raises(knowledge.KnowledgeLifecycleError):
        knowledge.publish("admin", "invalid-audience", {}, audience="PORTAL", scope_type="PUBLIC", version=1, reason="seed")
    db.execute.assert_not_called()

def test_reindex_repairs_only_published_packages(monkeypatch):
    monkeypatch.setattr(knowledge.identity_api, "effective_access", lambda *_: {"decision":"ALLOW"})
    monkeypatch.setattr(knowledge.connection, "execute_query", lambda *_: [{"KNOWLEDGE_ID":"k1","CONTENT_JSON":'{"content":{"answer":"one"}}',"AUDIENCE":"PUBLIC","SCOPE_TYPE":"PUBLIC"}])
    calls = []
    monkeypatch.setattr(knowledge.connection, "execute", lambda sql, params: calls.append((sql, params)) or 1)
    assert knowledge.reindex_packages("admin") == {"scanned": 1, "indexed": 1}
    assert len(calls) == 1 and "CX_PLATFORM_KNOWLEDGE_CHUNKS" in calls[0][0]
    assert ":chunk_no" in calls[0][0] and calls[0][1]["chunk_no"] == 1
