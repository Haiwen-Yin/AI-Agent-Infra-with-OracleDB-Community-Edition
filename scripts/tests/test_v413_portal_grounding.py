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


def test_general_answer_sends_only_question_without_enterprise_sources(flow):
    policy, _, _, model = flow
    policy['allow_model_supplement'] = 'Y'
    result = call(supplement=True)
    assert result['answer_source'] == 'MODEL_SUPPLEMENT'
    assert result['citations'] == []
    messages = model.call_args.args[1]
    assert len(messages) == 2
    assert messages[1] == {'role': 'user', 'content': '政策是什么'}
    assert 'general model knowledge' in messages[0]['content']


def test_knowledge_only_blocks_even_when_supplement_requested(flow):
    policy, _, _, model = flow
    policy.update(mode='KNOWLEDGE_ONLY', allow_model_supplement='N')
    assert call(supplement=True)['answer_source'] == 'INSUFFICIENT_KNOWLEDGE'
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


def test_english_filler_does_not_match_unrelated_sources(monkeypatch):
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    query = Mock(return_value=[])
    monkeypatch.setattr(knowledge.connection, 'execute_query', query)
    assert knowledge.search('human', 'agent', 'Explain quantum tunneling in one sentence.')['status'] == 'NO_MATCH'
    params = query.call_args.args[1]
    assert {v for k, v in params.items() if k.startswith('q')} == {'%quantum%', '%tunneling%'}


def test_only_filler_never_becomes_unfiltered_inventory(monkeypatch):
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    query = Mock()
    monkeypatch.setattr(knowledge.connection, 'execute_query', query)
    assert knowledge.search('human', 'agent', 'Please explain!')['items'] == []
    query.assert_not_called()


def test_subject_terms_after_filler_are_preserved():
    assert knowledge._search_terms('Please could you tell me what is the Oracle database') == ['oracle', 'database']
    assert knowledge._search_terms('量子隧穿') == ['量子隧穿']


@pytest.mark.parametrize('question', ['甲骨文公司', '请介绍一下甲骨文公司', '我想了解甲骨文公司的基本情况'])
def test_chinese_company_query_does_not_match_generic_company_text(monkeypatch, question):
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE ENTITIES (ENTITY_ID TEXT, ENTITY_TYPE TEXT, STATUS TEXT, EXPIRES_AT TEXT, TITLE TEXT, SUMMARY TEXT, CONTENT TEXT, UPDATED_AT TEXT)')
    db.executemany('INSERT INTO ENTITIES VALUES (?, ?, ?, NULL, ?, ?, ?, ?)', [
        ('unrelated', 'KNOWLEDGE', 'ACTIVE', '川序数据库事实与安全边界', '', '公司知识通过数据库权限隔离。', '2026-09-23'),
        ('product', 'KNOWLEDGE', 'ACTIVE', '川序平台', '', '平台功能介绍', '2026-09-23')])
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    monkeypatch.setattr(knowledge.knowledge_api, 'knowledge_access_predicate', lambda *_: '1=1')
    monkeypatch.setattr(knowledge.connection, 'DATABASE_DIALECT', 'pg')
    monkeypatch.setattr(knowledge.connection, 'execute_query', lambda sql, params: [dict(row) for row in db.execute(sql, params)])
    source = Mock(side_effect=lambda actor, agent, entity_id: dict(db.execute('SELECT ENTITY_ID AS entity_id, TITLE AS title, CONTENT AS content FROM ENTITIES WHERE ENTITY_ID=?', (entity_id,)).fetchone()))
    monkeypatch.setattr(knowledge, 'citation', source)
    try:
        assert knowledge.search('human', 'agent', question)['status'] == 'NO_MATCH'
        source.assert_not_called()
        db.execute('INSERT INTO ENTITIES VALUES (?, ?, ?, NULL, ?, ?, ?, ?)',
                   ('relevant', 'KNOWLEDGE', 'ACTIVE', '甲骨文公司简介', '', '数据库厂商简介', '2026-09-23'))
        result = knowledge.search('human', 'agent', question)
        assert [item['entity_id'] for item in result['items']] == ['relevant']
        assert {item['entity_id'] for item in knowledge.search('human', 'agent', '请介绍一下川序')['items']} == {'product', 'unrelated'}
    finally:
        db.close()


def test_chinese_filler_alone_does_not_search_inventory(monkeypatch):
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    query = Mock()
    monkeypatch.setattr(knowledge.connection, 'execute_query', query)
    assert knowledge.search('human', 'agent', '请介绍一下')['status'] == 'NO_MATCH'
    query.assert_not_called()


@pytest.mark.parametrize('question,unrelated,relevant', [
    ('Acme 公司', '公司政策', 'Acme 公司简介'),
    ('Oracle revenue', 'Oracle database platform', 'Oracle annual revenue'),
    ('AI', 'The company said this.', 'AI platform'),
    ('team_alpha', 'teamXalpha teamalpha', 'team_alpha policy'),
    ('quantum tunneling', 'quantum databases', 'quantum tunneling explained'),
    ('川序 安全', '川序功能介绍', '川序安全治理'),
    ('a' * 41, 'a' * 40, 'a' * 41),
])
def test_complete_subject_sql_and_source_boundaries(monkeypatch, question, unrelated, relevant):
    import sqlite3
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE ENTITIES (ENTITY_ID TEXT, ENTITY_TYPE TEXT, STATUS TEXT, EXPIRES_AT TEXT, TITLE TEXT, SUMMARY TEXT, CONTENT TEXT, UPDATED_AT TEXT)')
    for key, title, summary in [('wrong', unrelated, ''), ('summary_only', 'Unrelated source', relevant), ('right', relevant, '')]:
        db.execute("INSERT INTO ENTITIES VALUES (?, 'KNOWLEDGE', 'ACTIVE', NULL, ?, ?, '', '2026-09-23')", (key, title, summary))
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    monkeypatch.setattr(knowledge.knowledge_api, 'knowledge_access_predicate', lambda *_: '1=1')
    monkeypatch.setattr(knowledge.connection, 'DATABASE_DIALECT', 'pg')
    monkeypatch.setattr(knowledge.connection, 'execute_query', lambda sql, params: [dict(row) for row in db.execute(sql, params)])
    monkeypatch.setattr(knowledge, 'citation', lambda actor, agent, key: dict(db.execute('SELECT ENTITY_ID AS entity_id, TITLE AS title, CONTENT AS content FROM ENTITIES WHERE ENTITY_ID=?', (key,)).fetchone()))
    try:
        result = knowledge.search('human', 'agent', question)
        assert [item['entity_id'] for item in result['items']] == ['right']
    finally:
        db.close()


def test_excessive_subject_terms_are_not_silently_truncated(monkeypatch):
    monkeypatch.setattr(knowledge, 'require_reader', Mock())
    query = Mock(); monkeypatch.setattr(knowledge.connection, 'execute_query', query)
    question = ' '.join('subject' + str(i) for i in range(25))
    assert knowledge.search('human', 'agent', question)['status'] == 'NO_MATCH'
    query.assert_not_called()


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
