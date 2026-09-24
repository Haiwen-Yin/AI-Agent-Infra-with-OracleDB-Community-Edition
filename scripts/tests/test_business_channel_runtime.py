"""Exercise real source/mention binding and revocation against a tiny SQL store."""
import json
import sqlite3

import pytest

from lib import business_channel_runtime as business, identity_api, native_agent_api, native_runtime


@pytest.fixture
def store(monkeypatch):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT,PRINCIPAL_TYPE TEXT,STATUS TEXT);
      CREATE TABLE CX_CHANNELS(CHANNEL_ID TEXT,SECURITY_DOMAIN_ID TEXT,CLASSIFICATION TEXT,STATUS TEXT);
      CREATE TABLE CX_CHANNEL_MEMBERS(MEMBER_ID TEXT,CHANNEL_ID TEXT,PRINCIPAL_ID TEXT,MEMBER_ROLE TEXT,STATUS TEXT,VALID_UNTIL TEXT);
      CREATE TABLE CX_DOMAIN_MEMBERS(MEMBERSHIP_ID TEXT,SECURITY_DOMAIN_ID TEXT,PRINCIPAL_ID TEXT,STATUS TEXT,VALID_UNTIL TEXT);
      CREATE TABLE CX_CHANNEL_THREADS(THREAD_ID TEXT,CHANNEL_ID TEXT,THREAD_TYPE TEXT,STATUS TEXT);
      CREATE TABLE CX_CHANNEL_THREAD_MEMBERS(THREAD_MEMBER_ID TEXT,THREAD_ID TEXT,PRINCIPAL_ID TEXT,STATUS TEXT,VALID_UNTIL TEXT);
      CREATE TABLE CX_CHANNEL_MESSAGES(MESSAGE_ID TEXT,CHANNEL_ID TEXT,PRINCIPAL_ID TEXT,BODY_TEXT TEXT,THREAD_TYPE TEXT,THREAD_ID TEXT,REFERENCE_JSON TEXT,REDACTED_AT TEXT,MESSAGE_TYPE TEXT);
      CREATE TABLE CX_NATIVE_AGENTS(AGENT_ID TEXT,SOURCE TEXT,AGENT_KIND TEXT,IS_PROTECTED TEXT,STATUS TEXT,ACTIVATION_STATE TEXT,LLM_PROFILE_ID TEXT,DEPLOYMENT_TARGET_ID TEXT,TEMPLATE_ID TEXT);
      CREATE TABLE CX_AGENT_TEMPLATES(TEMPLATE_ID TEXT,STATUS TEXT,CONTENT_JSON TEXT);
      CREATE TABLE CX_RUNTIME_EXECUTIONS(EXECUTION_ID TEXT PRIMARY KEY,AGENT_ID TEXT,TARGET_ID TEXT,ISOLATION_LEVEL TEXT,STATUS TEXT,INPUT_JSON TEXT,CONTEXT_DIGEST TEXT);
      CREATE TABLE CX_PORTAL_KNOWLEDGE_POLICY(POLICY_ID TEXT,MODE TEXT,ALLOW_MODEL_SUPPLEMENT TEXT,DISCLOSURE_PROFILES_JSON TEXT,VERSION INTEGER);
      INSERT INTO CX_PORTAL_KNOWLEDGE_POLICY VALUES ('DEFAULT','KNOWLEDGE_FIRST','Y','["model"]',1);
      INSERT INTO CX_PRINCIPALS VALUES ('human','HUMAN','ACTIVE'),('agent','AGENT','ACTIVE');
      INSERT INTO CX_CHANNELS VALUES ('channel','domain','INTERNAL','ACTIVE');
      INSERT INTO CX_CHANNEL_MEMBERS VALUES ('cm1','channel','human','MEMBER','ACTIVE',NULL),('cm2','channel','agent','MEMBER','ACTIVE',NULL);
      INSERT INTO CX_DOMAIN_MEMBERS VALUES ('dm1','domain','human','ACTIVE',NULL),('dm2','domain','agent','ACTIVE',NULL);
      INSERT INTO CX_NATIVE_AGENTS VALUES ('agent','PLATFORM_CREATED','BUSINESS','N','ACTIVE','ACTIVE','model','target','template');
      INSERT INTO CX_AGENT_TEMPLATES VALUES ('template','PUBLISHED','{"isolation_level":"DOMAIN_ISOLATED"}');
      INSERT INTO CX_CHANNEL_MESSAGES VALUES ('message','channel','human','Please answer','CHANNEL',NULL,'{"mentions":["agent"]}',NULL,'TEXT');
    ''')
    class Tx:
        def query_one(self, sql, params=None):
            row = db.execute(sql.replace(' FOR UPDATE', ''), params or {}).fetchone()
            return {k.lower(): row[k] for k in row.keys()} if row else None

        def execute(self, sql, params=None):
            return db.execute(sql, params or {}).rowcount
    tx = Tx()
    monkeypatch.setattr(business.connection, 'execute_query_one', tx.query_one)
    monkeypatch.setattr(business.connection, 'execute_query', lambda sql, params=None: [dict(row) for row in db.execute(sql, params or {}).fetchall()])
    monkeypatch.setattr(business.connection, 'execute_transaction_callback', lambda fn: fn(tx))
    monkeypatch.setattr(identity_api, '_require', lambda *_: None)
    monkeypatch.setattr(identity_api, 'effective_access', lambda *_: {'decision': 'DENY'})
    monkeypatch.setattr(native_agent_api, '_audit', lambda *_: None)
    yield db
    db.close()


def enqueue():
    return business.enqueue('human', 'channel', 'message', 'agent', 'CHANNEL', '', 'en')


def test_explicit_human_mention_queues_once_and_preserves_source(store):
    result = enqueue()
    assert not result['idempotent']
    assert enqueue()['idempotent']
    row = store.execute('SELECT * FROM CX_RUNTIME_EXECUTIONS').fetchone()
    payload = json.loads(row['INPUT_JSON'])
    assert payload['messages'][-1] == {'role': 'user', 'content': 'Please answer'}
    assert native_runtime._channel_dispatch(payload)['kind'] == 'BUSINESS_MENTION'
    assert store.execute('SELECT COUNT(*) FROM CX_RUNTIME_EXECUTIONS').fetchone()[0] == 1


def test_channel_includes_governed_knowledge_context_when_available(store, monkeypatch):
    monkeypatch.setattr(identity_api, 'effective_access', lambda *_: {'decision': 'ALLOW'})
    monkeypatch.setattr(business.knowledge_grounding, 'search', lambda *args, **kwargs: {
        'status': 'MATCHED', 'items': [{'entity_id': 'K1', 'title': '川序介绍',
        'content': '川序是数据库智能平台。', 'digest': 'd1'}]})
    monkeypatch.setattr(business.knowledge_grounding, 'citation', lambda *args: {})
    enqueue()
    payload = json.loads(store.execute('SELECT INPUT_JSON FROM CX_RUNTIME_EXECUTIONS').fetchone()[0])
    assert payload['knowledge_citations'][0]['entity_id'] == 'K1'
    assert payload['messages'][1]['content'].startswith('Authorized knowledge references.')


@pytest.mark.parametrize('sql', [
    "UPDATE CX_CHANNEL_MESSAGES SET REFERENCE_JSON='{}'",
    "UPDATE CX_CHANNEL_MESSAGES SET REDACTED_AT=CURRENT_TIMESTAMP",
    "UPDATE CX_CHANNEL_MESSAGES SET PRINCIPAL_ID='agent'",
    "UPDATE CX_CHANNEL_MESSAGES SET MESSAGE_TYPE='AGENT_RESPONSE'",
    "UPDATE CX_CHANNEL_MESSAGES SET THREAD_ID='secret',THREAD_TYPE='PRIVATE'",
    "UPDATE CX_PRINCIPALS SET STATUS='DISABLED' WHERE PRINCIPAL_ID='human'",
    "UPDATE CX_CHANNELS SET STATUS='ARCHIVED'",
    "UPDATE CX_CHANNEL_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'",
    "UPDATE CX_CHANNEL_MEMBERS SET VALID_UNTIL='2000-01-01' WHERE PRINCIPAL_ID='human'",
    "UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'",
    "UPDATE CX_DOMAIN_MEMBERS SET VALID_UNTIL='2000-01-01' WHERE PRINCIPAL_ID='human'",
    "UPDATE CX_NATIVE_AGENTS SET STATUS='DISABLED'",
    "UPDATE CX_NATIVE_AGENTS SET SOURCE='EXTERNAL'",
    "UPDATE CX_NATIVE_AGENTS SET IS_PROTECTED='Y'",
    "UPDATE CX_NATIVE_AGENTS SET LLM_PROFILE_ID=NULL",
])
def test_invalid_or_revoked_source_cannot_enqueue(store, sql):
    store.execute(sql)
    with pytest.raises((PermissionError, native_agent_api.NativeAgentError)):
        enqueue()
    assert store.execute('SELECT COUNT(*) FROM CX_RUNTIME_EXECUTIONS').fetchone()[0] == 0


def test_revoke_after_enqueue_blocks_streaming_response(store):
    result = enqueue()
    store.execute("UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='CLAIMED'")
    business.validate_response('agent', 'channel', result['execution_id'], 'CHANNEL', '')
    store.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'")
    with pytest.raises(PermissionError):
        business.validate_response('agent', 'channel', result['execution_id'])


def test_response_cannot_be_redirected_or_used_before_claim(store):
    result = enqueue()
    with pytest.raises(PermissionError):
        business.validate_response('agent', 'channel', result['execution_id'])
    store.execute("UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='CLAIMED'")
    for channel, kind, thread in [('other', 'CHANNEL', ''), ('channel', 'PRIVATE', 'secret')]:
        with pytest.raises(PermissionError):
            business.validate_response('agent', channel, result['execution_id'], kind, thread)


def test_private_thread_requires_agent_membership(store):
    store.execute("UPDATE CX_CHANNEL_MESSAGES SET THREAD_ID='private',THREAD_TYPE='PRIVATE'")
    store.execute("INSERT INTO CX_CHANNEL_THREADS VALUES('private','channel','PRIVATE','ACTIVE')")
    store.execute("INSERT INTO CX_CHANNEL_THREAD_MEMBERS VALUES('th','private','human','ACTIVE',NULL)")
    with pytest.raises(PermissionError):
        business.enqueue('human', 'channel', 'message', 'agent', 'PRIVATE', 'private')
    store.execute("INSERT INTO CX_CHANNEL_THREAD_MEMBERS VALUES('ta','private','agent','ACTIVE',NULL)")
    assert business.enqueue('human', 'channel', 'message', 'agent', 'PRIVATE', 'private')['status'] == 'PENDING'


def test_stronger_template_isolation_is_not_downgraded(store):
    store.execute('UPDATE CX_AGENT_TEMPLATES SET CONTENT_JSON=?', (json.dumps({'isolation_level': 'DEDICATED_RUNTIME'}),))
    enqueue()
    assert store.execute('SELECT ISOLATION_LEVEL FROM CX_RUNTIME_EXECUTIONS').fetchone()[0] == 'DEDICATED_RUNTIME'


def test_business_bridge_cannot_invoke_management_channel(store):
    with pytest.raises(PermissionError):
        business.enqueue('human', 'CH_PLATFORM_ADMINISTRATION', 'message', 'agent', 'CHANNEL', '')


def test_runtime_admission_failure_keeps_reply_binding(store, monkeypatch):
    enqueue()
    raw = store.execute('SELECT * FROM CX_RUNTIME_EXECUTIONS').fetchone()
    execution = {key.lower(): raw[key] for key in raw.keys()}
    monkeypatch.setattr(native_agent_api, 'claim_runtime', lambda *a, **kw: [execution])
    def deny(*args):
        raise RuntimeError('Deployment target is unavailable')
    monkeypatch.setattr(native_runtime, '_admit_execution', deny)
    monkeypatch.setattr(native_runtime, '_finish', lambda *a, **kw: None)
    replies = []
    monkeypatch.setattr(native_runtime, '_write_channel_response', lambda *a, **kw: replies.append(a))
    result = native_runtime.execute_one('worker','node')
    assert result['status'] == 'FAILED'
    assert replies[0][0] == 'agent'
    assert replies[0][2]['channel_dispatch']['message_id'] == 'message'


def test_isolation_denial_reports_runtime_requirement_not_model_failure(monkeypatch):
    from lib import runtime_isolation
    assert native_runtime._failure_code(runtime_isolation.IsolationError('unverified')) == 'RUNTIME_ISOLATION_UNAVAILABLE'
    replies = []
    monkeypatch.setattr(identity_api, 'post_channel_agent_response', lambda *a, **kw: replies.append(a))
    native_runtime._write_channel_response('agent','execution',{'response_language':'zh','channel_dispatch':{
        'kind':'BUSINESS_MENTION','channel_id':'channel'}},failure='RUNTIME_ISOLATION_UNAVAILABLE')
    assert '尚未调用模型' in replies[0][2]
    assert '模型配置' not in replies[0][2]
