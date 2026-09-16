"""Product Worker context provenance, fencing, atomicity and uncertain sends."""
from datetime import datetime,timedelta
import pytest
from lib import continuity_runtime as runtime,continuity_assembly as assembly,native_runtime
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database
from .test_continuity_handoff import fixture
from .test_continuity_assembly import context_db,assembly_request


@pytest.fixture
def runtime_db(context_db,monkeypatch):
    db,wid=context_db
    db.executescript('''
        CREATE TABLE CX_AGENT_INSTANCES(INSTANCE_ID TEXT PRIMARY KEY,AGENT_ID TEXT,STATUS TEXT,
          LEASE_EXPIRES_AT TIMESTAMP,FENCING_TOKEN INTEGER,SECURITY_DOMAIN_ID TEXT);
        CREATE TABLE CX_AGENT_ACCESS_TOKENS(TOKEN_DIGEST TEXT PRIMARY KEY,AGENT_ID TEXT,INSTANCE_ID TEXT,
          SCOPE_JSON TEXT,LEASE_DIGEST TEXT,FENCING_TOKEN INTEGER,EXPIRES_AT TIMESTAMP,REVOKED_AT TIMESTAMP);
        CREATE TABLE CX_RUNTIME_ISOLATION_CONTRACTS(AGENT_ID TEXT,INSTANCE_ID TEXT,STATUS TEXT);
        CREATE TABLE CX_NATIVE_AGENTS(AGENT_ID TEXT PRIMARY KEY,STATUS TEXT,DEPLOYMENT_TARGET_ID TEXT,LLM_PROFILE_ID TEXT);
        INSERT INTO CX_NATIVE_AGENTS VALUES('agent','ACTIVE','target','profile');
        CREATE TABLE CX_RUNTIME_EXECUTIONS(EXECUTION_ID TEXT PRIMARY KEY,AGENT_ID TEXT,TARGET_ID TEXT,
          ISOLATION_LEVEL TEXT,STATUS TEXT,INPUT_JSON TEXT,CONTEXT_DIGEST TEXT,WORKER_ID TEXT,NODE_ID TEXT,
          FENCING_TOKEN INTEGER DEFAULT 0,LEASE_EXPIRES_AT TIMESTAMP,OUTPUT_JSON TEXT,FAILURE_REASON TEXT,
          COMPLETED_AT TIMESTAMP,UPDATED_AT TIMESTAMP);
    ''')
    for sql in runtime.schema_statements('pg'): db.execute(sql)
    for sql in runtime.credential_schema_statements('pg'): db.execute(sql)
    db.commit()
    monkeypatch.setattr(runtime.identity_api,'_agent_visible_to',lambda actor,agent:actor=='owner' and agent=='agent')
    def query(sql,params):
        row=db.execute(sql,params).fetchone()
        return {key.lower():row[key] for key in row.keys()} if row else None
    monkeypatch.setattr(runtime.connection,'execute_query_one',query)
    monkeypatch.setattr(runtime.connection,'execute',lambda sql,params:db.execute(sql,params).rowcount)
    return db,wid


def request(wid):
    return dict(agent_id='agent',messages=[dict(role='user',content='Use the reference to answer.')],
                context=assembly_request(wid),reason='Explicit context execution',idempotency_key='execution')


def claimed(db,receipt,fence=1):
    db.execute("UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='CLAIMED',WORKER_ID='worker',NODE_ID='node',FENCING_TOKEN=?,LEASE_EXPIRES_AT=? WHERE EXECUTION_ID=?",
               (fence,datetime.now()+timedelta(minutes=5),receipt['execution_id']))
    db.commit()
    return dict(execution_id=receipt['execution_id'],agent_id='agent',worker_id='worker',node_id='node',fencing_token=fence)


def test_enqueue_and_actual_inputs_have_one_relational_receipt(runtime_db):
    db,wid=runtime_db
    receipt=runtime.enqueue('owner',request(wid))
    assert runtime.enqueue('owner',request(wid))['replayed']
    current=claimed(db,receipt)
    seen=[]
    result=runtime.execute(current,runtime.binding(receipt['execution_id']),lambda messages:seen.append(messages) or {'content':'observed'})
    assert result=={'content':'observed'}
    assert seen[0][0]['content']=='Use the reference to answer.'
    assert seen[0][-1]['role']=='user' and 'finish task' in seen[0][-1]['content']
    assert db.execute('SELECT STATUS FROM CX_CONTEXT_INPUT_USES').fetchone()[0]=='SENT'
    assert db.execute('SELECT FENCING_TOKEN FROM CX_RUNTIME_CONTEXT_ATTEMPTS').fetchone()[0]==1
    with pytest.raises(ContinuityConflict): runtime.execute(current,runtime.binding(receipt['execution_id']),lambda _:pytest.fail('Duplicate send'))


@pytest.mark.parametrize('change',['none','revoked','fenced','domain','scope','expired','isolation','replacement'])
def test_original_gateway_credential_is_rechecked_before_worker_send(runtime_db,monkeypatch,change):
    from lib import agent_gateway_api as gateway
    from lib.continuity_bindings import authenticated_transport
    db,wid=runtime_db
    monkeypatch.setattr(gateway,'_compliance_allows',lambda *_:True)
    db.execute("INSERT INTO CX_AGENT_INSTANCES VALUES('instance','owner','ACTIVE','2099-01-01',1,'domain')")
    db.execute("INSERT INTO CX_AGENT_ACCESS_TOKENS VALUES('original','owner','instance','[\"agents.operate\"]','lease',1,'2099-01-01',NULL)")
    db.commit()
    with authenticated_transport(dict(instance_id='instance',token_digest='original',fencing_token=1)):
        receipt=runtime.enqueue('owner',request(wid))
    current=claimed(db,receipt)
    if change in {'revoked','replacement'}:
        db.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP")
    if change=='replacement':
        db.execute("INSERT INTO CX_AGENT_ACCESS_TOKENS VALUES('new','owner','instance','[\"agents.operate\"]','lease',1,'2099-01-01',NULL)")
    if change=='fenced': db.execute('UPDATE CX_AGENT_INSTANCES SET FENCING_TOKEN=2')
    if change=='domain': db.execute("UPDATE CX_AGENT_INSTANCES SET SECURITY_DOMAIN_ID='other'")
    if change=='scope': db.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET SCOPE_JSON='[]'")
    if change=='expired': db.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET EXPIRES_AT='2000-01-01'")
    if change=='isolation': db.execute("INSERT INTO CX_RUNTIME_ISOLATION_CONTRACTS VALUES('owner','instance','REVOKED')")
    db.commit()
    seen=[]
    if change=='none':
        runtime.execute(current,runtime.binding(receipt['execution_id']),lambda messages:seen.append(messages) or 'ok')
        assert len(seen)==1
    else:
        with pytest.raises(PermissionError):
            runtime.execute(current,runtime.binding(receipt['execution_id']),lambda _:pytest.fail('Revoked credential sent'))
        assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_INPUT_USES').fetchone()[0]==0
    assert db.execute('SELECT TOKEN_DIGEST FROM CX_RUNTIME_CONTEXT_CREDENTIALS').fetchone()[0]=='original'


@pytest.mark.parametrize('change',['scope','domain','fenced'])
def test_gateway_rejection_leaves_no_partial_execution(runtime_db,monkeypatch,change):
    from lib import agent_gateway_api as gateway
    from lib.continuity_bindings import authenticated_transport
    db,wid=runtime_db
    monkeypatch.setattr(gateway,'_compliance_allows',lambda *_:True)
    db.execute("INSERT INTO CX_AGENT_INSTANCES VALUES('instance','owner','ACTIVE','2099-01-01',1,'domain')")
    db.execute("INSERT INTO CX_AGENT_ACCESS_TOKENS VALUES('original','owner','instance','[\"agents.operate\"]','lease',1,'2099-01-01',NULL)")
    if change=='scope': db.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET SCOPE_JSON='[\"workspaces.write\"]'")
    if change=='domain': db.execute("UPDATE CX_AGENT_INSTANCES SET SECURITY_DOMAIN_ID='other'")
    db.commit()
    with authenticated_transport(dict(instance_id='instance',token_digest='original',fencing_token=2 if change=='fenced' else 1)):
        with pytest.raises(PermissionError): runtime.enqueue('owner',request(wid))
    for table in ('CX_CONTEXT_ASSEMBLIES','CX_RUNTIME_EXECUTIONS','CX_RUNTIME_CONTEXT_BINDINGS','CX_RUNTIME_CONTEXT_CREDENTIALS'):
        assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


@pytest.mark.parametrize('when',['enqueue','send','read'])
def test_target_agent_read_permission_does_not_replace_requester_permission(runtime_db,monkeypatch,when):
    db,wid=runtime_db
    if when!='enqueue':
        receipt=runtime.enqueue('owner',request(wid))
        current=claimed(db,receipt)
    if when=='read':
        runtime.execute(current,runtime.binding(receipt['execution_id']),lambda _:{'content':'source-derived response'})
        assert native_runtime.get_execution('owner',receipt['execution_id'])['input_receipt']['status']=='SENT'
    original=assembly._work_item
    def denied(tx,actor,*args,**kwargs):
        if actor=='owner': raise PermissionError('Requester source access revoked')
        return original(tx,actor,*args,**kwargs)
    monkeypatch.setattr(assembly,'_work_item',denied)
    with pytest.raises(PermissionError):
        if when=='enqueue': runtime.enqueue('owner',request(wid))
        elif when=='send': runtime.execute(current,runtime.binding(receipt['execution_id']),lambda _:pytest.fail('Private source forwarded'))
        else: native_runtime.get_execution('owner',receipt['execution_id'])
    if when=='enqueue': assert db.execute('SELECT COUNT(*) FROM CX_RUNTIME_EXECUTIONS').fetchone()[0]==0
    if when=='send': assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_INPUT_USES').fetchone()[0]==0


def test_unrelated_operator_cannot_read_bound_execution(runtime_db):
    db,wid=runtime_db
    receipt=runtime.enqueue('owner',request(wid))
    with pytest.raises(PermissionError): runtime.read_execution('reader',receipt['execution_id'])


@pytest.mark.parametrize('failure',['audit','permission','target'])
def test_enqueue_failure_leaves_no_assembly_queue_or_binding(runtime_db,monkeypatch,failure):
    db,wid=runtime_db
    if failure=='audit':
        previous=runtime.identity_api._audit_tx
        def audit(*args):
            if args[2]=='CONTEXT_RUNTIME_QUEUED': raise RuntimeError('Synthetic audit failure')
            return previous(*args)
        monkeypatch.setattr(runtime.identity_api,'_audit_tx',audit)
    elif failure=='permission':
        monkeypatch.setattr(runtime.identity_api,'effective_access',lambda *args,**kwargs:{'decision':'DENY' if args[1]=='agents.operate' else 'ALLOW'})
    else:
        db.execute("UPDATE CX_NATIVE_AGENTS SET STATUS='SUSPENDED'")
        db.commit()
    with pytest.raises((RuntimeError,PermissionError)): runtime.enqueue('owner',request(wid))
    for table in ('CX_CONTEXT_ASSEMBLIES','CX_RUNTIME_EXECUTIONS','CX_RUNTIME_CONTEXT_BINDINGS'):
        assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


@pytest.mark.parametrize('change',['input','fence','domain','requestor'])
def test_worker_rechecks_current_claim_input_and_authority(runtime_db,change):
    db,wid=runtime_db
    receipt=runtime.enqueue('owner',request(wid))
    current=claimed(db,receipt)
    if change=='input': db.execute("UPDATE CX_RUNTIME_EXECUTIONS SET INPUT_JSON='{}'")
    if change=='fence': db.execute('UPDATE CX_RUNTIME_EXECUTIONS SET FENCING_TOKEN=2')
    if change=='domain': db.execute("UPDATE CX_SECURITY_DOMAINS SET STATUS='REVOKED'")
    if change=='requestor': db.execute("UPDATE CX_PRINCIPALS SET STATUS='SUSPENDED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError): runtime.execute(current,runtime.binding(receipt['execution_id']),lambda _:pytest.fail('Unauthorized model send'))
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_INPUT_USES').fetchone()[0]==0


def test_worker_crash_after_reservation_is_not_automatically_resent(runtime_db):
    db,wid=runtime_db
    receipt=runtime.enqueue('owner',request(wid))
    old=claimed(db,receipt)
    class Crash(BaseException): pass
    def crash(_): raise Crash()
    with pytest.raises(Crash): runtime.execute(old,runtime.binding(receipt['execution_id']),crash)
    assert db.execute('SELECT STATUS FROM CX_CONTEXT_INPUT_USES').fetchone()[0]=='SENDING'
    replacement=claimed(db,receipt,2)
    with pytest.raises(ContinuityConflict): runtime.execute(replacement,runtime.binding(receipt['execution_id']),lambda _:pytest.fail('Uncertain send retried'))
    assert db.execute('SELECT STATUS FROM CX_CONTEXT_INPUT_USES').fetchone()[0]=='UNOBSERVED'
    assert db.execute('SELECT COUNT(*) FROM CX_RUNTIME_CONTEXT_ATTEMPTS').fetchone()[0]==1


@pytest.mark.parametrize('revoked',[False,True])
def test_product_worker_calls_model_with_bound_context(runtime_db,monkeypatch,revoked):
    db,wid=runtime_db
    receipt=runtime.enqueue('owner',request(wid))
    current=claimed(db,receipt)
    current['input_json']=db.execute('SELECT INPUT_JSON FROM CX_RUNTIME_EXECUTIONS').fetchone()[0]
    monkeypatch.setattr(native_runtime.native_agent_api,'claim_runtime',lambda *args,**kwargs:[current])
    monkeypatch.setattr(native_runtime,'_admit_execution',lambda *_:None)
    monkeypatch.setattr(native_runtime,'_llm_profile',lambda *_:{'profile_id':'profile'})
    health=[]
    monkeypatch.setattr(native_runtime,'_set_profile_health',lambda *args:health.append(args))
    seen=[]
    monkeypatch.setattr(native_runtime,'_call_llm',lambda _profile,messages:seen.append(messages) or {'content':'Observed by test adapter'})
    if revoked:
        db.execute("UPDATE CX_SECURITY_DOMAINS SET STATUS='REVOKED'")
        db.commit()
    result=native_runtime.execute_one('worker','node')
    if revoked:
        assert result['status']=='FAILED' and seen==[] and health==[]
        return
    assert result['status']=='COMPLETED'
    assert 'finish task' in seen[0][-1]['content']
    assert db.execute('SELECT STATUS FROM CX_RUNTIME_EXECUTIONS').fetchone()[0]=='COMPLETED'
    assert db.execute('SELECT STATUS FROM CX_CONTEXT_INPUT_USES').fetchone()[0]=='SENT'
