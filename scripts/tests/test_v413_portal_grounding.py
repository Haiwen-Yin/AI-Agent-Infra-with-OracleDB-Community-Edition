"""No fallback, user/Agent scope intersection and fresh citation checks."""
from unittest.mock import Mock
from decimal import Decimal
import pytest
from lib import portal_grounding as portal, knowledge_grounding as knowledge


def test_policy_version_is_json_serializable_across_drivers(monkeypatch):
    import json
    monkeypatch.setattr(portal.connection, "execute_query_one", lambda *_: {
        "mode": "KNOWLEDGE_FIRST", "version": Decimal("7"), "disclosure_profiles_json": "[]",
        "allow_model_supplement": "N"})
    result = portal.policy()
    assert type(result["version"]) is int
    assert json.loads(json.dumps(result))["version"] == 7


@pytest.fixture
def flow(monkeypatch):
    policy = {"version": 1, "mode": "KNOWLEDGE_FIRST", "allow_model_supplement": "N", "disclosure_profiles": []}
    monkeypatch.setattr(portal, "policy", lambda: policy)
    monkeypatch.setattr(knowledge, "require_reader", Mock())
    retrieval = Mock(return_value={"status": "NO_MATCH", "items": []})
    monkeypatch.setattr(knowledge, "search", retrieval)
    source = Mock()
    monkeypatch.setattr(knowledge, "citation", source)
    model = Mock(return_value={"content": "Authorized answer [1]"})
    monkeypatch.setattr(portal.native_runtime, "_call_llm", model)
    return policy, retrieval, source, model


def call(**kwargs):
    return portal.answer({"principal_id": "human", "agent_id": "agent"}, "政策是什么", {"profile_id": "model"}, **kwargs)


def test_no_match_does_not_silently_use_model(flow):
    policy, _, _, model = flow
    assert call()["answer_source"] == "INSUFFICIENT_KNOWLEDGE"
    assert call(supplement=True)["answer_source"] == "INSUFFICIENT_KNOWLEDGE"
    model.assert_not_called()
    policy["allow_model_supplement"] = "Y"
    assert call(supplement=True)["answer_source"] == "MODEL_SUPPLEMENT"


def test_retrieval_error_is_not_no_match(flow):
    _, retrieval, _, model = flow
    retrieval.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError): call()
    model.assert_not_called()


def test_unapproved_model_receives_no_enterprise_content(flow):
    _, retrieval, source, model = flow
    retrieval.return_value = {"status": "MATCHED", "items": [{"entity_id": "k1", "title": "公司制度", "content": "内部政策正文", "digest": "d1"}]}
    result = call()
    assert result["answer_source"] == "KNOWLEDGE_EXTRACTS"
    model.assert_not_called()
    source.assert_called_once_with("human", "agent", "k1", "d1")


def test_permission_or_version_revocation_discards_answer(flow):
    policy, retrieval, source, _ = flow
    policy["disclosure_profiles"] = ["model"]
    retrieval.return_value = {"status": "MATCHED", "items": [{"entity_id": "k1", "title": "公司制度", "content": "内部政策正文", "digest": "d1"}]}
    source.side_effect = PermissionError("revoked")
    with pytest.raises(PermissionError): call()


def test_knowledge_extract_requires_no_model_profile(flow):
    _, retrieval, _, model = flow
    retrieval.return_value = {"status": "MATCHED", "items": [{"entity_id": "k1", "title": "Policy", "content": "Company policy", "digest": "d1"}]}
    result = portal.answer({"principal_id": "human", "agent_id": "agent"}, "policy", {})
    assert result["answer_source"] == "KNOWLEDGE_EXTRACTS"
    model.assert_not_called()


def test_model_failure_never_becomes_simulated_success(flow):
    policy, retrieval, _, model = flow
    policy["disclosure_profiles"] = ["model"]
    retrieval.return_value = {"status": "MATCHED", "items": [{"entity_id": "k1", "title": "公司制度", "content": "内部政策正文", "digest": "d1"}]}
    model.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError): call()


def test_query_has_both_acl_predicates(monkeypatch):
    monkeypatch.setattr(knowledge, "require_reader", Mock())
    query = Mock(return_value=[])
    monkeypatch.setattr(knowledge.connection, "execute_query", query)
    result = knowledge.search("human", "agent", "年假")
    sql, params = query.call_args.args
    assert params["actor"] == "human" and params["agent"] == "agent"
    assert "kap.PRINCIPAL_ID=:actor" in sql and "kap.PRINCIPAL_ID=:agent" in sql
    assert "e.STATUS='ACTIVE'" in sql and "e.EXPIRES_AT>CURRENT_TIMESTAMP" in sql
    assert result["status"] == "NO_MATCH"


@pytest.mark.parametrize("changes", [
    {"mode": "MODEL_ONLY"}, {"mode": "KNOWLEDGE_ONLY", "allow_model_supplement": True},
    {"allow_model_supplement": "false"}, {"expected_version": True},
    {"expected_version": 0}, {"disclosure_profiles": "model"},
    {"disclosure_profiles": [None]}, {"disclosure_profiles": [""]}, {"reason": "  "},
])
def test_policy_rejects_invalid_settings_before_database(monkeypatch, changes):
    monkeypatch.setattr(portal.identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    database = Mock()
    monkeypatch.setattr(portal.connection, "execute_transaction_callback", database)
    settings = dict(mode="KNOWLEDGE_FIRST", allow_model_supplement=False,
                    disclosure_profiles=[], expected_version=1, reason="reviewed")
    settings.update(changes)
    with pytest.raises(ValueError): portal.set_policy("admin", **settings)
    database.assert_not_called()


def test_policy_rejects_stale_version_without_write(monkeypatch):
    monkeypatch.setattr(portal.identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    tx = Mock(query_one=Mock(return_value={"VERSION": 2}))
    monkeypatch.setattr(portal.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(knowledge.GroundingError):
        portal.set_policy("admin", "KNOWLEDGE_FIRST", False, [], 1, "reviewed")
    tx.execute.assert_not_called()


def test_policy_updates_version_and_audit_in_same_transaction(monkeypatch):
    monkeypatch.setattr(portal.identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    tx = Mock(query_one=Mock(side_effect=[{"VERSION": 2}, {"PROFILE_ID": "model"}]), execute=Mock(return_value=1))
    audit = Mock()
    monkeypatch.setattr(portal.identity_api, "_audit_tx", audit)
    monkeypatch.setattr(portal.connection, "execute_transaction_callback", lambda fn: fn(tx))
    result = portal.set_policy("admin", "KNOWLEDGE_ONLY", False, ["model"], 2, "reviewed")
    assert result["version"] == 3
    assert tx.execute.call_args.args[1]["expected"] == 2
    audit.assert_called_once()
    assert audit.call_args.args[0] is tx
