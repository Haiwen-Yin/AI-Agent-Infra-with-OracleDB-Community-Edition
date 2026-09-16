"""Typed native links retain history without becoming access grants."""
import pytest
from lib import continuity_work as work,continuity_handoff as handoff
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database,request
from .test_continuity_handoff import fixture,offer_request,decision


@pytest.fixture
def linked_db(fixture):
    db,_=fixture
    db.executescript('''
      CREATE TABLE WORKSPACES(WORKSPACE_ID TEXT PRIMARY KEY,CURRENT_AGENT_ID TEXT,OWNER_USER_ID TEXT);
      CREATE TABLE TASK_PLANS(PLAN_ID TEXT PRIMARY KEY,AGENT_ID TEXT,STATUS TEXT);
      CREATE TABLE GRAPH_RUNS(RUN_ID TEXT PRIMARY KEY,ACTOR_ID TEXT);
      CREATE TABLE CX_HUMAN_IDENTITIES(PRINCIPAL_ID TEXT,USERNAME TEXT,IDENTITY_TYPE TEXT,STATUS TEXT);
      CREATE TABLE SYSTEM_USERS(USER_ID TEXT PRIMARY KEY,USERNAME TEXT);
      CREATE TABLE CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID TEXT,AGENT_ID TEXT,PRINCIPAL_ID TEXT,RELATIONSHIP_ROLE TEXT,STATUS TEXT,ENDED_AT TIMESTAMP);
      INSERT INTO WORKSPACES VALUES('1','agent','user');
      INSERT INTO SYSTEM_USERS VALUES('user','owner-login');
      INSERT INTO CX_HUMAN_IDENTITIES VALUES('owner','owner-login','LOCAL','ACTIVE');
      INSERT INTO TASK_PLANS VALUES('2','agent','PENDING');
      INSERT INTO GRAPH_RUNS VALUES('graph','agent');
      INSERT INTO CX_AGENT_RELATIONSHIPS VALUES('relationship','agent','owner','PRIMARY_OWNER','ACTIVE',NULL);
    ''')
    return db


def linked_request(key='linked'):
    return dict(request(key),workspace_id='1',task_id='2',graph_run_id='graph')


def test_three_native_links_and_task_status_changes(linked_db):
    created=work.create_work('owner',linked_request())
    wid=created['work_contract_id']
    links=work.read_work('owner',wid)['execution_links']
    assert {row['link_kind'] for row in links}=={'WORKSPACE','TASK','GRAPH'}
    assert work.create_work('owner',linked_request())['replayed']
    linked_db.execute("UPDATE TASK_PLANS SET STATUS='RUNNING' WHERE PLAN_ID='2'")
    linked_db.commit()
    assert work.read_work('owner',wid)['execution_links']==links
    assert work.read_work('agent',wid)['execution_links']==links
    with pytest.raises(PermissionError):
        work.read_work('reader',wid)


def test_native_revocation_blocks_reads_mutations_and_retries(linked_db):
    wid=work.create_work('owner',linked_request())['work_contract_id']
    linked_db.execute("UPDATE CX_AGENT_RELATIONSHIPS SET STATUS='REVOKED'")
    linked_db.commit()
    with pytest.raises(PermissionError):
        work.read_work('owner',wid)
    with pytest.raises(PermissionError):
        work.create_work('owner',linked_request())
    with pytest.raises(PermissionError):
        work.revise_work('owner',wid,dict(expected_version=1,content=request()['content'],reason='test',idempotency_key='revise'))
    with pytest.raises(PermissionError):
        work.change_work_state('owner',wid,dict(expected_version=1,status='IN_PROGRESS',reason='test',idempotency_key='state'))
    assert linked_db.execute('SELECT COUNT(*) FROM CX_WORK_EXECUTION_LINKS').fetchone()[0]==3


def test_source_owner_change_and_missing_resource_roll_back(linked_db):
    before=linked_db.execute('SELECT COUNT(*) FROM CX_WORK_CONTRACTS').fetchone()[0]
    with pytest.raises(PermissionError):
        work.create_work('owner',dict(linked_request(),graph_run_id='missing'))
    assert linked_db.execute('SELECT COUNT(*) FROM CX_WORK_CONTRACTS').fetchone()[0]==before
    assert linked_db.execute('SELECT COUNT(*) FROM CX_WORK_EXECUTION_LINKS').fetchone()[0]==0
    wid=work.create_work('owner',linked_request())['work_contract_id']
    linked_db.execute("UPDATE GRAPH_RUNS SET ACTOR_ID='owner'")
    linked_db.commit()
    with pytest.raises(ContinuityConflict,match='responsibility'):
        work.read_work('owner',wid)


def test_handoff_recipient_rechecks_linked_resource(linked_db):
    wid=work.create_work('owner',linked_request())['work_contract_id']
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    linked_db.execute("UPDATE WORKSPACES SET CURRENT_AGENT_ID=NULL WHERE WORKSPACE_ID='1'")
    linked_db.commit()
    with pytest.raises(PermissionError):
        handoff.decide('agent',hid,decision())
    assert linked_db.execute('SELECT STATUS FROM CX_HANDOFFS WHERE HANDOFF_ID=?',(hid,)).fetchone()[0]=='OFFERED'


def test_graph_link_requires_graph_authority_not_just_task_access(linked_db,monkeypatch):
    wid=work.create_work('owner',linked_request())['work_contract_id']
    monkeypatch.setattr(work.identity_api,'effective_access',lambda actor,action,**kwargs:
                        {'decision':'DENY' if action=='graphs.read' else 'ALLOW'})
    with pytest.raises(PermissionError):
        work.read_work('owner',wid)
