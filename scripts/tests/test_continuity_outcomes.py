"""Outcome proposal authorization, immutable provenance and atomicity."""
import pytest
from lib import continuity_outcomes as outcomes,continuity_candidates as candidates,continuity_handoff as handoff
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database
from .test_continuity_handoff import fixture,decision
from .test_continuity_candidates import candidate_db,PROPOSALS


def completed(candidate_db):
    db,source=candidate_db
    hid=source['entity_id']
    handoff.decide('agent',hid,decision())
    handoff.decide('agent',hid,decision(2,'IN_PROGRESS','start'))
    handoff.submit_outcome('agent',hid,dict(expected_version=3,expected_revision_no=1,result='COMPLETED',
        summary='Verified synthetic result',satisfied_criteria=['one'],reason='Observed',idempotency_key='outcome'))
    read=handoff.read_outcome('owner',hid)
    return db,hid,dict(expected_outcome_id=read['outcome_id'],expected_digest=read['content_digest'],
                      content=PROPOSALS[2],reason='Explicit proposal',idempotency_key='proposal')


def test_outcome_proposal_pins_result_and_never_auto_promotes(candidate_db):
    db,hid,request=completed(candidate_db)
    result=outcomes.propose_experience('owner',hid,request)
    assert outcomes.propose_experience('owner',hid,request)['replayed']
    candidate=candidates.read_candidate('agent',result['candidate_id'])
    assert candidate['status']=='PENDING'
    source=candidate['payload']['sources'][0]
    assert source['family']=='HANDOFF_OUTCOME' and source['entity_id']==request['expected_outcome_id']
    assert source['content_digest']==request['expected_digest']
    assert db.execute('SELECT COUNT(*) FROM ENTITIES').fetchone()[0]==0
    with pytest.raises(ContinuityConflict):
        outcomes.propose_experience('owner',hid,dict(request,expected_digest='0'*64))
    with pytest.raises(ContinuityConflict):
        outcomes.propose_experience('owner',hid,dict(request,content=dict(PROPOSALS[2],title='Changed')))


def test_outcome_proposal_rechecks_participant_and_rolls_back(candidate_db,monkeypatch):
    db,hid,request=completed(candidate_db)
    with pytest.raises(PermissionError):
        outcomes.propose_experience('reader',hid,request)
    def failed(*args):
        raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(candidates.identity_api,'_audit_tx',failed)
    with pytest.raises(RuntimeError):
        outcomes.propose_experience('owner',hid,request)
    assert db.execute('SELECT COUNT(*) FROM CX_ARTIFACT_CANDIDATES').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM CX_CANDIDATE_SOURCES').fetchone()[0]==0
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        outcomes.propose_experience('owner',hid,request)
