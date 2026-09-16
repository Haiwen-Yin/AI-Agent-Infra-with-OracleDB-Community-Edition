"""Exact handoff evidence and instance fencing preserve historical authority."""
import pytest

from lib import continuity_handoff as handoff,continuity_work as work,continuity_publications as pubs
from lib.continuity_state import ContinuityError,ContinuityConflict
from .test_continuity_work import database,request as work_request
from .test_continuity_handoff import fixture,offer_request,decision
from .test_continuity_assembly import context_db
from .test_continuity_publications import publication_db,publication


def test_handoff_body_pins_publication_and_revocation_blocks_read_and_acceptance(publication_db):
    db,source=publication_db
    db.execute("UPDATE CX_PRINCIPALS SET PRINCIPAL_TYPE='AGENT' WHERE PRINCIPAL_ID='outsider'")
    db.commit()
    wid=work.create_work('owner',dict(work_request('target-work'),security_domain_id='target'))['work_contract_id']
    value=offer_request('with-evidence')
    value['recipient_principal_id']='outsider'
    value['content']['next_actions'][0]['responsible_principal_id']='outsider'
    value['content']['evidence']=[source]
    with pytest.raises(PermissionError):
        handoff.offer('owner',wid,value)
    grant=pubs.publish('owner',dict(publication(source),purpose='HANDOFF_CONTEXT'))
    hid=handoff.offer('owner',wid,value)['handoff_id']
    assert handoff.read_handoff('outsider',hid)['content']['evidence']==[source]
    assert db.execute('SELECT PUBLICATION_ID FROM CX_HANDOFF_EVIDENCE').fetchone()[0]==grant['publication_id']
    pubs.revoke('owner',grant['publication_id'],dict(expected_version=1,reason='Revoke evidence',idempotency_key='revoke'))
    pubs.publish('owner',dict(publication(source,'replacement'),purpose='HANDOFF_CONTEXT'))
    with pytest.raises(PermissionError):
        handoff.read_handoff('outsider',hid)
    with pytest.raises(PermissionError):
        handoff.decide('outsider',hid,decision())
    assert work.read_work('owner',wid)['owner_principal_id']=='owner'
    assert handoff.decide('outsider',hid,decision(state='REJECTED',key='reject'))['version']==2


def test_duplicate_handoff_evidence_rolls_back_the_whole_offer(publication_db):
    db,source=publication_db
    wid=work.create_work('owner',work_request('second-work'))['work_contract_id']
    value=offer_request('duplicate')
    value['content']['evidence']=[source,source]
    before=db.execute('SELECT COUNT(*) FROM CX_HANDOFFS').fetchone()[0]
    with pytest.raises(ContinuityError,match='unique exact versions'):
        handoff.offer('owner',wid,value)
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFFS').fetchone()[0]==before


@pytest.fixture
def instance_db(fixture):
    db,wid=fixture
    db.execute('CREATE TABLE CX_AGENT_INSTANCES(INSTANCE_ID TEXT PRIMARY KEY,AGENT_ID TEXT,SECURITY_DOMAIN_ID TEXT,FENCING_TOKEN INTEGER,STATUS TEXT,REVOKED_AT TEXT,LEASE_EXPIRES_AT TEXT)')
    db.execute("INSERT INTO CX_AGENT_INSTANCES VALUES('old','agent','domain',1,'REVOKED','2020-01-01','2020-01-01'),('new','agent','domain',2,'ACTIVE',NULL,'2099-01-01')")
    db.commit()
    return db,wid


def test_recipient_fencing_change_blocks_acceptance_but_keeps_history(instance_db):
    db,wid=instance_db
    hid=handoff.offer('owner',wid,dict(offer_request(),recipient_instance_id='new'))['handoff_id']
    assert handoff.read_handoff('agent',hid)['executable']
    db.execute("UPDATE CX_AGENT_INSTANCES SET FENCING_TOKEN=3 WHERE INSTANCE_ID='new'")
    db.commit()
    history=handoff.read_handoff('agent',hid)
    assert not history['executable'] and history['instance_bindings'][0]['fencing_token']==2
    with pytest.raises(ContinuityConflict,match='no longer current'):
        handoff.decide('agent',hid,decision())
    assert work.read_work('owner',wid)['owner_principal_id']=='owner'


def test_worker_replacement_binds_distinct_instances_of_same_principal(instance_db):
    db,wid=instance_db
    wid=work.create_work('agent',dict(work_request('agent-work'),owner_principal_id='agent'))['work_contract_id']
    value=dict(offer_request('replacement'),kind='WORKER_REPLACEMENT',sender_instance_id='old',recipient_instance_id='new')
    with pytest.raises(ContinuityError,match='distinct old and new'):
        handoff.offer('agent',wid,dict(value,sender_instance_id='new'))
    hid=handoff.offer('agent',wid,value)['handoff_id']
    handoff.decide('agent',hid,decision())
    assert work.read_work('agent',wid)['owner_principal_id']=='agent'
    assert {item['instance_id'] for item in handoff.read_handoff('agent',hid)['instance_bindings']}=={'old','new'}


def test_wrong_instance_principal_or_domain_cannot_be_bound(instance_db):
    db,wid=instance_db
    with pytest.raises(PermissionError):
        handoff.offer('owner',wid,dict(offer_request(),sender_instance_id='new'))
    db.execute("UPDATE CX_AGENT_INSTANCES SET SECURITY_DOMAIN_ID='different' WHERE INSTANCE_ID='new'")
    db.commit()
    with pytest.raises(PermissionError):
        handoff.offer('owner',wid,dict(offer_request(),recipient_instance_id='new'))
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFFS').fetchone()[0]==0
