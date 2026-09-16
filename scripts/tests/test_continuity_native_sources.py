"""Typed source snapshots preserve history while current native authority holds."""
import json
import sqlite3
import pytest
from lib import continuity_native_sources as sources
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database


@pytest.fixture
def native_sources(database,monkeypatch):
    db=database
    db.executescript('''
      CREATE TABLE CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID TEXT,AGENT_ID TEXT,PRINCIPAL_ID TEXT,RELATIONSHIP_ROLE TEXT,STATUS TEXT,ENDED_AT TIMESTAMP);
      CREATE TABLE TASK_PLANS(PLAN_ID TEXT PRIMARY KEY,AGENT_ID TEXT,GOAL TEXT,STATUS TEXT,PRIORITY INTEGER,STRATEGY TEXT,RESULT_SUMMARY TEXT);
      CREATE TABLE TASK_STEPS(STEP_ID TEXT PRIMARY KEY,PLAN_ID TEXT,STEP_ORDER INTEGER,DESCRIPTION TEXT,TOOL_NAME TEXT,STATUS TEXT);
      CREATE TABLE GRAPH_RUNS(RUN_ID TEXT PRIMARY KEY,ACTOR_ID TEXT,GRAPH_VERSION_ID TEXT,PLAN_ID TEXT,STATUS TEXT,CURRENT_CHECKPOINT_ID TEXT,ERROR_CODE TEXT,ERROR_MESSAGE TEXT);
      CREATE TABLE GRAPH_NODE_RUNS(NODE_RUN_ID TEXT PRIMARY KEY,RUN_ID TEXT,NODE_KEY TEXT,STATUS TEXT,BRANCH_KEY TEXT,JOIN_KEY TEXT,ITERATION_NO INTEGER,INPUT_CHECKPOINT_ID TEXT,OUTPUT_CHECKPOINT_ID TEXT);
      CREATE TABLE CX_DB4A2A_DISPATCHES(DISPATCH_ID TEXT PRIMARY KEY,SENDER_PRINCIPAL_ID TEXT,TASK_ID TEXT,RECEIVER_AGENT_ID TEXT,CONTEXT_REF TEXT,SNAPSHOT_DIGEST TEXT,EXPECTED_VERSION INTEGER,SCOPE_REF TEXT,SOURCE_BRANCH TEXT,BRANCH_POLICY TEXT,TRANSPORT TEXT,STATUS TEXT,CHILD_BRANCH_ID TEXT);
      CREATE TABLE CX_SECURITY_EVENTS(EVENT_ID TEXT PRIMARY KEY,PRINCIPAL_ID TEXT,ACTOR_TYPE TEXT,ACTION_NAME TEXT,RESOURCE_TYPE TEXT,RESOURCE_ID TEXT,OUTCOME TEXT,REASON TEXT);
      INSERT INTO TASK_PLANS VALUES('1','owner','Validate the typed task','RUNNING',5,NULL,NULL);
      INSERT INTO TASK_STEPS VALUES('10','1',1,'First step',NULL,'SUCCESS');
      INSERT INTO TASK_STEPS VALUES('20','1',2,'Second step','synthetic','RUNNING');
      INSERT INTO GRAPH_RUNS VALUES('graph','owner','version','plan','RUNNING',NULL,NULL,NULL);
      INSERT INTO GRAPH_NODE_RUNS VALUES('node','graph','start','RUNNING',NULL,NULL,0,NULL,NULL);
      INSERT INTO CX_DB4A2A_DISPATCHES VALUES('dispatch','owner','1','reader','context','sha256:old',1,'workspace:1',NULL,'READ_ONLY','DB_MEDIATED','PENDING',NULL);
      INSERT INTO CX_SECURITY_EVENTS VALUES('event','owner','HUMAN','READ','WORKSPACE','1','ALLOW','Authorized read');
    ''')
    db.commit()
    monkeypatch.setattr(sources.identity_api,'_limit_clause',lambda key:'LIMIT :'+key)
    return db


def request(family):
    return dict(family=family,entity_id={'TASK':'1','GRAPH':'graph','DB4A2A':'dispatch','AUDIT':'event'}[family],
                security_domain_id='domain',reason='Explicit snapshot',idempotency_key='snapshot')


def read(db,source,actor='owner',domain='domain'):
    return sources.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,actor,domain,source))


@pytest.mark.parametrize('family',['TASK','GRAPH','DB4A2A','AUDIT'])
def test_exact_snapshot_and_replay_survive_native_updates(native_sources,family):
    db=native_sources
    receipt=sources.capture('owner',request(family))
    original=read(db,receipt['source'])
    payload=json.loads(original['text'])
    assert payload['captured_at'].endswith('Z') and payload['revision_id']==receipt['source']['revision_id']
    assert payload['captured_at'].endswith('.000000Z')
    assert len(payload['items'])==({'TASK':2,'GRAPH':1}.get(family,0))
    table,_,_,_,fields=sources.PROJECTIONS[family]
    field='outcome' if family=='AUDIT' else 'status'
    db.execute('UPDATE '+table+' SET '+field+"='CHANGED'")
    db.commit()
    assert sources.capture('owner',request(family))==dict(source=receipt['source'],replayed=True)
    assert read(db,receipt['source'])==original
    newer=sources.capture('owner',{**request(family),'idempotency_key':'new'})
    assert newer['source']['content_digest']!=receipt['source']['content_digest']
    assert json.loads(read(db,newer['source'])['text'])['fields'][field]=='CHANGED'


@pytest.mark.parametrize('family',['TASK','GRAPH','DB4A2A','AUDIT'])
def test_capture_audit_failure_is_atomic(native_sources,monkeypatch,family):
    db=native_sources
    def fail(*_): raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(sources.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError): sources.capture('owner',request(family))
    for statement in sources.schema_statements('pg'):
        assert db.execute('SELECT COUNT(*) FROM '+statement.split()[2]).fetchone()[0]==0


@pytest.mark.parametrize('family',['TASK','GRAPH','DB4A2A','AUDIT'])
def test_source_deletion_revokes_access_without_erasing_history(native_sources,family):
    db=native_sources
    receipt=sources.capture('owner',request(family))
    db.execute('DELETE FROM '+sources.PROJECTIONS[family][0]);db.commit()
    with pytest.raises(PermissionError): read(db,receipt['source'])
    assert db.execute('SELECT COUNT(*) FROM CX_NATIVE_CONTEXT_REVISIONS').fetchone()[0]==1


@pytest.mark.parametrize('family',['TASK','GRAPH','DB4A2A','AUDIT'])
def test_digest_and_current_domain_authority_are_required(native_sources,family):
    db=native_sources
    receipt=sources.capture('owner',request(family))
    with pytest.raises(PermissionError): read(db,receipt['source'],actor='outsider')
    with pytest.raises(PermissionError): read(db,receipt['source'],domain='other')
    with pytest.raises(ContinuityConflict): read(db,{**receipt['source'],'content_digest':'0'*64})
    with pytest.raises(ContinuityConflict): sources.capture('owner',{**request(family),'reason':'Changed request'})
    field='outcome' if family=='AUDIT' else 'status'
    db.execute('UPDATE CX_'+family+'_CONTEXT_REVISIONS SET '+field+"='TAMPERED'");db.commit()
    with pytest.raises(ContinuityConflict): read(db,receipt['source'])


def test_wrong_typed_projection_cannot_reference_another_family(native_sources):
    db=native_sources
    receipt=sources.capture('owner',request('TASK'))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO CX_GRAPH_CONTEXT_REVISIONS(REVISION_ID) VALUES(?)',(receipt['source']['revision_id'],))
    db.rollback()


def test_participant_and_owner_changes_revoke_snapshot(native_sources):
    db=native_sources
    task=sources.capture('owner',request('TASK'))['source']
    with pytest.raises(PermissionError): read(db,task,actor='reader')
    dispatch=sources.capture('owner',{**request('DB4A2A'),'idempotency_key':'dispatch'})['source']
    assert read(db,dispatch,actor='reader')['content_digest']==dispatch['content_digest']
    db.execute("UPDATE CX_DB4A2A_DISPATCHES SET RECEIVER_AGENT_ID='outsider'");db.commit()
    with pytest.raises(PermissionError): read(db,dispatch,actor='reader')
    db.execute("UPDATE TASK_PLANS SET AGENT_ID='reader'");db.commit()
    with pytest.raises(PermissionError): read(db,task,actor='owner')
