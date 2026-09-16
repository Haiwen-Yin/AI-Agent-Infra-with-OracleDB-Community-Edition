"""Parallel recipients retain coordinator ownership and exact policy history."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from lib import continuity_policy as policy,continuity_work as work,continuity_handoff as handoff
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database,request
from .test_continuity_handoff import fixture,offer_request,decision


def change(limit=2,version=1,key='parallel'):
    return dict(expected_version=version,max_active_recipients=limit,reason='Explicit parallel collaboration',idempotency_key=key)


def offer(recipient,version=2,key=None):
    value=deepcopy(offer_request(key or recipient))
    value['expected_work_version']=version
    value['recipient_principal_id']=recipient
    value['content']['next_actions'][0]['responsible_principal_id']=recipient
    return value


def add_agent(db,name):
    db.execute('INSERT INTO CX_PRINCIPALS VALUES(?,?,?)',(name,'ACTIVE','AGENT'))
    db.execute("INSERT INTO CX_DOMAIN_MEMBERS VALUES('domain',?,'ACTIVE','MEMBER',NULL)",(name,))
    db.commit()


def test_parallel_recipients_ack_and_complete_without_ownership_collision(fixture):
    db,wid=fixture
    add_agent(db,'agent2')
    policy.change('owner',wid,change())
    first=handoff.offer('owner',wid,offer('agent'))['handoff_id']
    second=handoff.offer('owner',wid,offer('agent2'))['handoff_id']
    for actor,hid in [('agent',first),('agent2',second)]:
        handoff.decide(actor,hid,decision())
        assert work.read_work(actor,wid)['owner_principal_id']=='owner'
        handoff.decide(actor,hid,decision(2,'IN_PROGRESS','start'))
        result=dict(expected_version=3,expected_revision_no=1,result='COMPLETED',summary='verified',
                    satisfied_criteria=['one'],reason='tested',idempotency_key='outcome')
        handoff.submit_outcome(actor,hid,result)
    assert work.read_work('owner',wid)['version']==2
    assert handoff.read_handoff('agent',first)['status']=='COMPLETED'
    assert handoff.read_handoff('agent2',second)['status']=='COMPLETED'
    policy.change('owner',wid,change(1,2,'serial'))
    assert work.read_work('owner',wid,2)['handoff_policy']['max_active_recipients']==2
    assert work.read_work('owner',wid)['handoff_policy']['max_active_recipients']==1


def test_parallel_limits_duplicates_and_active_policy_changes_are_rejected(fixture):
    db,wid=fixture
    for actor in ['agent2','agent3']:
        add_agent(db,actor)
    policy.change('owner',wid,change())
    handoff.offer('owner',wid,offer('agent'))
    with pytest.raises(ContinuityConflict):
        handoff.offer('owner',wid,offer('agent',key='duplicate'))
    with pytest.raises(ContinuityConflict):
        policy.change('owner',wid,change(3,2,'active'))
    handoff.offer('owner',wid,offer('agent2'))
    with pytest.raises(ContinuityConflict):
        handoff.offer('owner',wid,offer('agent3'))
    assert db.execute('SELECT COUNT(*) FROM CX_HANDOFFS').fetchone()[0]==2


def test_policy_replay_owner_scope_and_audit_rollback(fixture,monkeypatch):
    db,wid=fixture
    with pytest.raises(PermissionError):
        policy.change('agent',wid,change())
    policy.change('owner',wid,change())
    assert policy.change('owner',wid,change())['replayed']
    with pytest.raises(ContinuityConflict):
        policy.change('owner',wid,change(3))
    def fail(*_):
        raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(work.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        policy.change('owner',wid,change(3,2,'rollback'))
    assert work.read_work('owner',wid)['version']==2
    assert db.execute('SELECT COUNT(*) FROM CX_WORK_HANDOFF_POLICIES').fetchone()[0]==2


@pytest.mark.parametrize('limit',[True,0,17,'2'])
def test_policy_requires_bounded_explicit_integer(limit):
    with pytest.raises(ValidationError):
        policy.HandoffPolicyChange.model_validate(change(limit))
