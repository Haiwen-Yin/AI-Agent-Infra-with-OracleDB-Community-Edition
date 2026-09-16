"""Real transaction unit harness; database adapter acceptance is separate."""
from datetime import datetime, timedelta, timezone

import pytest

from lib import continuity_handoff as handoff, continuity_work as work
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database, request


@pytest.fixture
def fixture(database):
    database.execute("ALTER TABLE CX_PRINCIPALS ADD COLUMN PRINCIPAL_TYPE TEXT DEFAULT 'HUMAN'")
    database.execute("INSERT INTO CX_PRINCIPALS VALUES('agent','ACTIVE','AGENT')")
    database.execute("INSERT INTO CX_DOMAIN_MEMBERS VALUES('domain','agent','ACTIVE','MEMBER',NULL)")
    for statement in handoff.schema_statements('pg'):
        # Migration 94 retires the serial-only uniqueness constraint.
        database.execute(statement.replace('ACTIVE_WORK_ID VARCHAR(128) UNIQUE','ACTIVE_WORK_ID VARCHAR(128)'))
    from lib import continuity_bindings
    for statement in continuity_bindings.schema_statements('pg'):
        database.execute(statement)
    database.commit()
    return database, work.create_work('owner', request())['work_contract_id']


def offer_request(key='offer'):
    return dict(expected_work_version=1,recipient_principal_id='agent',kind='HUMAN_TO_AGENT',
                expires_at=datetime.now(timezone.utc)+timedelta(hours=1),reason='transfer',idempotency_key=key,
                content=dict(summary='继续验证',next_actions=[dict(action_id='a1',description='verify',
                    responsible_principal_id='agent',acceptance='tests pass',prerequisites=['configuration ready'])]))


def decision(version=1, state='ACKNOWLEDGED', key='ack'):
    return dict(expected_version=version,expected_revision_no=1,decision=state,reason='accept',idempotency_key=key)


def test_ack_transfers_with_immutable_responsibility_history(fixture):
    db, wid = fixture
    value = offer_request()
    hid = handoff.offer('owner',wid,value)['handoff_id']
    assert handoff.read_handoff('agent',hid)['content']['summary']=='继续验证'
    assert handoff.decide('agent',hid,decision())['version']==2
    assert handoff.decide('agent',hid,decision())['replayed']
    assert handoff.offer('owner',wid,value)['replayed']
    current = work.read_work('agent',wid)
    assert current['version']==2 and current['owner_principal_id']=='agent'
    assert current['revision_owner_principal_id']=='agent'
    assert work.read_work('owner',wid,1)['revision_owner_principal_id']=='owner'
    ack = db.execute('SELECT ACK_AT FROM CX_HANDOFF_ASSIGNMENTS').fetchone()[0]
    handoff.decide('agent',hid,decision(2,'IN_PROGRESS','start'))
    assert db.execute('SELECT ACK_AT FROM CX_HANDOFF_ASSIGNMENTS').fetchone()[0]==ack
    outcome = dict(expected_version=3,expected_revision_no=1,result='COMPLETED',summary='verified',
                   satisfied_criteria=['one'],reason='tested',idempotency_key='outcome')
    assert handoff.submit_outcome('agent',hid,outcome)['version']==4
    assert handoff.submit_outcome('agent',hid,outcome)['replayed']
    assert handoff.read_handoff('agent',hid)['status']=='COMPLETED'
    assert not handoff.read_handoff('agent',hid)['executable']


def test_changed_work_cannot_be_accepted_as_original_offer(fixture):
    db,wid = fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    work.revise_work('owner',wid,dict(expected_version=1,content=request(objective='changed')['content'],
                                    reason='change',idempotency_key='revision'))
    with pytest.raises(ContinuityConflict,match='resource changed'):
        handoff.decide('agent',hid,decision())
    assert work.read_work('owner',wid)['owner_principal_id']=='owner'
    assert handoff.read_handoff('agent',hid)['version']==1


def test_ack_audit_failure_rolls_back_owner_revision_and_receipt(fixture,monkeypatch):
    db,wid=fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    def fail(*args):
        raise RuntimeError('audit failed')
    monkeypatch.setattr(handoff.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError,match='audit failed'):
        handoff.decide('agent',hid,decision())
    current=work.read_work('owner',wid)
    assert current['version']==1 and current['owner_principal_id']=='owner'
    assert db.execute('SELECT COUNT(*) FROM CX_WORK_REVISION_STATES').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFF_REQUESTS').fetchone()[0]==1
    assert handoff.read_handoff('agent',hid)['status']=='OFFERED'


def test_expired_metadata_and_reclamation(fixture):
    db,wid=fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    with pytest.raises(ContinuityConflict):
        handoff.offer('owner',wid,offer_request('other'))
    db.execute("UPDATE CX_HANDOFFS SET EXPIRES_AT='2000-01-01 00:00:00'")
    db.commit()
    record=handoff.read_handoff('agent',hid)
    assert record['expired'] and not record['executable'] and 'content' not in record
    with pytest.raises(ContinuityConflict):
        handoff.decide('agent',hid,decision())
    second=handoff.offer('owner',wid,offer_request('replacement'))
    assert second['handoff_id']!=hid
    assert handoff.read_handoff('owner',hid)['status']=='EXPIRED'


def test_participant_authorization_and_revocation(fixture):
    db,wid=fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    with pytest.raises(PermissionError):
        handoff.decide('owner',hid,decision())
    with pytest.raises(PermissionError):
        handoff.read_handoff('reader',hid)
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'")
    db.commit()
    with pytest.raises(PermissionError):
        handoff.decide('agent',hid,decision())


def test_unaccepted_or_incomplete_outcome_rejected(fixture):
    db,wid=fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    value=dict(expected_version=1,expected_revision_no=1,result='FAILED',summary='failed',reason='test',idempotency_key='out')
    with pytest.raises(ContinuityConflict,match='accepted'):
        handoff.submit_outcome('agent',hid,value)
    handoff.decide('agent',hid,decision())
    handoff.decide('agent',hid,decision(2,'IN_PROGRESS','start'))
    with pytest.raises(ContinuityConflict,match='every offered'):
        handoff.submit_outcome('agent',hid,dict(value,expected_version=3,result='COMPLETED'))
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFF_OUTCOMES').fetchone()[0]==0


def test_offer_revision_requires_new_ack_and_preserves_work_binding(fixture):
    db,wid=fixture
    value=offer_request()
    hid=handoff.offer('owner',wid,value)['handoff_id']
    work.revise_work('owner',wid,dict(expected_version=1,content=request(objective='updated')['content'],
                                    reason='refine',idempotency_key='work-refine'))
    updated=dict(expected_version=1,expected_revision_no=1,expected_work_version=2,
                 content=dict(value['content'],summary='修订交接'),reason='refine',idempotency_key='refine')
    assert handoff.revise_handoff('owner',hid,updated)['version']==2
    assert handoff.revise_handoff('owner',hid,updated)['replayed']
    old=handoff.read_handoff('agent',hid,1)
    assert old['content']['summary']=='继续验证' and old['work_revision_no']==1
    assert not old['executable']
    assert handoff.read_handoff('agent',hid)['work_revision_no']==2
    with pytest.raises(ContinuityConflict):
        handoff.decide('agent',hid,decision(2))
    handoff.decide('agent',hid,dict(decision(2),expected_revision_no=2))
    assert work.read_work('agent',wid)['version']==3
    with pytest.raises(ContinuityConflict):
        handoff.revise_handoff('owner',hid,dict(updated,expected_version=3,expected_revision_no=2,idempotency_key='late'))


def test_rejection_does_not_record_acknowledgement(fixture):
    db,wid=fixture
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    handoff.decide('agent',hid,decision(state='REJECTED'))
    assert db.execute('SELECT ACK_AT,ACK_REVISION_NO FROM CX_HANDOFF_ASSIGNMENTS').fetchone()[:]==(None,None)
    assert work.read_work('owner',wid)['version']==1


def completed_outcome_fixture(wid):
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    ref=dict(family='HANDOFF',entity_id=hid,revision_id='1',content_digest=handoff.read_handoff('agent',hid)['content_digest'])
    handoff.decide('agent',hid,decision())
    handoff.decide('agent',hid,decision(2,'IN_PROGRESS','start'))
    outcome=dict(expected_version=3,expected_revision_no=1,result='COMPLETED',summary='Verified with exact evidence',
                 satisfied_criteria=['one'],evidence=[ref],reason='Observed result',idempotency_key='evidenced-outcome')
    return hid,outcome


def test_outcome_exact_evidence_and_current_access(fixture):
    db,wid=fixture
    hid,value=completed_outcome_fixture(wid)
    handoff.submit_outcome('agent',hid,value)
    result=handoff.read_outcome('owner',hid)
    assert result['evidence']==value['evidence'] and result['satisfied_criteria']==['one']
    assert result['summary']==value['summary']
    assert handoff.submit_outcome('agent',hid,value)['replayed']
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFF_OUTCOME_EVIDENCE').fetchone()[0]==1
    with pytest.raises(PermissionError):
        handoff.read_outcome('reader',hid)
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'")
    db.commit()
    with pytest.raises(PermissionError):
        handoff.read_outcome('agent',hid)
    db.execute("UPDATE CX_HANDOFFS SET EXPIRES_AT='2000-01-01 00:00:00'")
    db.commit()
    with pytest.raises((PermissionError,ContinuityConflict)):
        handoff.read_outcome('owner',hid)


def test_outcome_evidence_failure_preserves_active_work(fixture):
    from lib.continuity_state import ContinuityError
    db,wid=fixture
    hid,value=completed_outcome_fixture(wid)
    with pytest.raises(ContinuityConflict):
        handoff.submit_outcome('agent',hid,dict(value,evidence=[dict(value['evidence'][0],content_digest='0'*64)]))
    with pytest.raises(ContinuityError,match='unique exact'):
        handoff.submit_outcome('agent',hid,dict(value,evidence=value['evidence']*2))
    assert handoff.read_handoff('agent',hid)['status']=='IN_PROGRESS'
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFF_OUTCOMES').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFF_OUTCOME_EVIDENCE').fetchone()[0]==0


def test_outcome_evidence_audit_failure_rolls_back(fixture,monkeypatch):
    db,wid=fixture
    hid,value=completed_outcome_fixture(wid)
    def fail(*args):
        raise RuntimeError('audit failed')
    monkeypatch.setattr(handoff.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError,match='audit failed'):
        handoff.submit_outcome('agent',hid,value)
    assert handoff.read_handoff('agent',hid)['status']=='IN_PROGRESS'
    for table in ('CX_HANDOFF_OUTCOMES','CX_HANDOFF_OUTCOME_EVIDENCE','CX_HANDOFF_OUTCOME_CRITERIA'):
        assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
