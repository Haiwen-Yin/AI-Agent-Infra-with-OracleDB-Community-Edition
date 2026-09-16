"""Context budgets, current authorization and observed input transaction tests."""
import pytest

from lib import continuity_assembly as assembly, continuity_work as work, continuity_handoff as handoff
from lib.continuity_state import ContinuityConflict
from .test_continuity_handoff import fixture, offer_request
from .test_continuity_work import database, request


@pytest.fixture
def context_db(fixture):
    db,wid=fixture
    db.execute('ALTER TABLE CX_PRINCIPALS ADD COLUMN PERMISSION_VERSION INTEGER DEFAULT 1')
    for statement in assembly.schema_statements('pg'):
        db.execute(statement)
    db.commit()
    return db,wid


def assembly_request(wid=None,**kwargs):
    return dict(request_id='request',security_domain_id='domain',work_contract_id=wid,
                purpose='test context',idempotency_key='assembly',**kwargs)


def test_empty_and_budget_exclusions_are_real_empty_context(context_db):
    db,wid=context_db
    empty=assembly.assemble('owner',assembly_request())
    assert empty['item_count']==0
    assert assembly.read_assembly('owner',empty['assembly_id'])['text']==''
    small=assembly.assemble('owner',dict(assembly_request(wid,token_budget=1),idempotency_key='small'))
    assert small['item_count']==0
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_INPUT_USES').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM CX_WORK_CONTRACTS').fetchone()[0]==1


def test_assembly_pins_history_and_rechecks_authorization(context_db):
    db,wid=context_db
    result=assembly.assemble('owner',assembly_request(wid))
    old=assembly.read_assembly('owner',result['assembly_id'])
    assert old['item_count']==1 and 'finish task' in old['text']
    work.revise_work('owner',wid,dict(expected_version=1,content=request(objective='later')['content'],reason='revise',idempotency_key='revise'))
    assert assembly.read_assembly('owner',result['assembly_id'])['text']==old['text']
    assert assembly.assemble('owner',assembly_request(wid))['replayed']
    with pytest.raises(PermissionError):
        assembly.read_assembly('agent',result['assembly_id'])
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        assembly.read_assembly('owner',result['assembly_id'])


def test_only_consumed_context_produces_observed_receipt(context_db):
    db,wid=context_db
    result=assembly.assemble('owner',assembly_request(wid))
    received=[]
    def send(text):
        received.append(text)
        return 'response'
    sent=assembly.consume('owner',result['assembly_id'],send)
    assert sent['status']=='SENT' and sent['result']=='response'
    assert received==[assembly.read_assembly('owner',result['assembly_id'])['text']]
    with pytest.raises(ContinuityConflict):
        assembly.consume('owner',result['assembly_id'],send)
    assert len(received)==1
    assert db.execute('SELECT STATUS FROM CX_CONTEXT_INPUT_USES').fetchone()[0]=='SENT'


def test_provider_failure_not_claimed_as_sent_or_blindly_retried(context_db):
    db,wid=context_db
    result=assembly.assemble('owner',assembly_request(wid))
    def fail(text):
        raise RuntimeError('transport unavailable')
    with pytest.raises(RuntimeError):
        assembly.consume('owner',result['assembly_id'],fail)
    assert assembly.read_assembly('owner',result['assembly_id'])['status']=='UNOBSERVED'
    with pytest.raises(ContinuityConflict):
        assembly.consume('owner',result['assembly_id'],fail)


def test_expired_context_neither_replayed_nor_sent(context_db):
    db,wid=context_db
    result=assembly.assemble('owner',assembly_request(wid))
    db.execute("UPDATE CX_CONTEXT_ASSEMBLIES SET EXPIRES_AT='2000-01-01 00:00:00'")
    db.commit()
    calls=[]
    with pytest.raises(ContinuityConflict):
        assembly.consume('owner',result['assembly_id'],lambda text:calls.append(text))
    with pytest.raises(ContinuityConflict):
        assembly.assemble('owner',assembly_request(wid))
    assert not calls


def test_handoff_source_rechecks_participant_not_just_domain(context_db):
    db,wid=context_db
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    record=handoff.read_handoff('agent',hid)
    source=dict(family='HANDOFF',entity_id=hid,revision_id='1',content_digest=record['content_digest'])
    result=assembly.assemble('agent',assembly_request(sources=[source]))
    assert result['item_count']==1
    with pytest.raises(PermissionError):
        assembly.assemble('reader',assembly_request(sources=[source]))
    db.execute("UPDATE CX_HANDOFFS SET EXPIRES_AT='2000-01-01 00:00:00'")
    db.commit()
    with pytest.raises(ContinuityConflict):
        assembly.read_assembly('agent',result['assembly_id'])


def test_preparation_audit_failure_has_no_partial_items(context_db,monkeypatch):
    db,wid=context_db
    def fail(*args):
        raise RuntimeError('audit failure')
    monkeypatch.setattr(assembly.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        assembly.assemble('owner',assembly_request(wid))
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_ASSEMBLIES').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_ASSEMBLY_ITEMS').fetchone()[0]==0
