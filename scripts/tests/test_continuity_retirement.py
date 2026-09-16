"""Formal retirement retains exact history and atomically disables use."""
import pytest

from lib import continuity_retirement as retirement,continuity_candidates as candidates,continuity_sources as sources
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database
from .test_continuity_handoff import fixture
from .test_continuity_candidates import candidate_db,PROPOSALS,new_candidate,approve


@pytest.fixture
def retirement_db(candidate_db):
    db,source=candidate_db
    for statement in retirement.schema_statements('pg'):
        db.execute(statement)
    db.commit()
    return db,source


def promoted(db,source,proposal):
    cid=candidates.create_candidate('owner',new_candidate(source,proposal))['candidate_id']
    result=candidates.promote_candidate('agent',cid,approve(cid))
    if proposal['family']=='MEMORY':
        digest=db.execute('SELECT CONTENT_DIGEST FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=?',(result['result_revision_id'],)).fetchone()[0]
    else:
        digest=db.execute('SELECT CONTENT_DIGEST FROM CX_CONTINUITY_ARTIFACT_REVS WHERE REVISION_ID=?',(result['result_revision_id'],)).fetchone()[0]
    return dict(family=proposal['family'],entity_id=result['result_entity_id'],revision_id=result['result_revision_id'],content_digest=digest)


@pytest.mark.parametrize('proposal',PROPOSALS,ids=lambda item:item['family'])
def test_retirement_preserves_history_denies_reads_and_replays(retirement_db,proposal):
    db,source=retirement_db
    ref=promoted(db,source,proposal)
    request=dict(source=ref,expected_version=1,reason='Explicit retirement',idempotency_key='retire')
    with pytest.raises(PermissionError):
        retirement.retire('agent',request)
    with pytest.raises(ContinuityConflict):
        retirement.retire('owner',dict(request,expected_version=2))
    result=retirement.retire('owner',request)
    assert result['status']=='RETIRED' and result['version']==2
    assert retirement.retire('owner',request)['replayed']
    with pytest.raises(ContinuityConflict):
        retirement.retire('owner',dict(request,reason='Different request'))
    with pytest.raises((PermissionError,ContinuityConflict)):
        retirement.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,'owner','domain',ref))
    if proposal['family']=='MEMORY':
        assert db.execute('SELECT LIFECYCLE_STATE,CONTENT_DIGEST FROM CX_MEMORY_VERSIONS').fetchone()[:]==('UNAVAILABLE',ref['content_digest'])
        assert db.execute("SELECT COUNT(*) FROM CX_MEMORY_PROJECTION_OUTBOX WHERE EVENT_TYPE='RETIRED'").fetchone()[0]==1
    else:
        assert db.execute('SELECT STATUS FROM ENTITIES').fetchone()[0]=='ARCHIVED'
        assert db.execute('SELECT CONTENT_DIGEST FROM CX_CONTINUITY_ARTIFACT_REVS').fetchone()[0]==ref['content_digest']
        if proposal['family']=='SKILL':
            assert db.execute('SELECT SKILL_STATUS FROM SKILL_META').fetchone()[0]=='DISABLED'
    assert db.execute('SELECT COUNT(*) FROM CX_ARTIFACT_RETIREMENTS').fetchone()[0]==1
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        retirement.retire('owner',request)


@pytest.mark.parametrize('proposal',PROPOSALS,ids=lambda item:item['family'])
def test_retirement_audit_failure_preserves_active_native_state(retirement_db,proposal,monkeypatch):
    db,source=retirement_db
    ref=promoted(db,source,proposal)
    def fail(*args):
        raise RuntimeError('Audit failed')
    monkeypatch.setattr(retirement.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        retirement.retire('owner',dict(source=ref,expected_version=1,reason='Explicit retirement',idempotency_key='retire'))
    assert retirement.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,'owner','domain',ref))['text']
    assert db.execute('SELECT COUNT(*) FROM CX_ARTIFACT_RETIREMENTS').fetchone()[0]==0
    if proposal['family']=='MEMORY':
        assert db.execute('SELECT FAMILY_STATE,ROW_VERSION FROM CX_MEMORY_FAMILIES').fetchone()[:]==('ACTIVE',1)
    else:
        assert db.execute('SELECT STATUS,VERSION FROM CX_CONTINUITY_ARTIFACTS').fetchone()[:]==('ACTIVE',1)
        assert db.execute('SELECT STATUS FROM ENTITIES').fetchone()[0]=='ACTIVE'


def test_memory_replacement_cannot_reactivate_retirement_after_source_check(retirement_db,monkeypatch):
    from lib import continuity_promotions as promotions
    db,source=retirement_db
    ref=promoted(db,source,PROPOSALS[0])
    proposal=dict(PROPOSALS[0],body='A newer verified fact')
    cid=candidates.create_candidate('owner',dict(new_candidate(source,proposal,'successor'),replaces=ref))['candidate_id']
    request=approve(cid)
    original=promotions.promote
    def concurrent_retirement(tx,actor,root,payload,reason):
        # Model retirement committing between source validation and family lock.
        tx.execute("UPDATE CX_MEMORY_FAMILIES SET FAMILY_STATE='UNAVAILABLE' WHERE FAMILY_ID=:family",{'family':ref['entity_id']})
        return original(tx,actor,root,payload,reason)
    monkeypatch.setattr(promotions,'promote',concurrent_retirement)
    with pytest.raises(ContinuityConflict,match='replacement source changed'):
        candidates.promote_candidate('agent',cid,request)
    assert db.execute('SELECT COUNT(*) FROM CX_MEMORY_VERSIONS').fetchone()[0]==1


@pytest.mark.parametrize('proposal',PROPOSALS,ids=lambda item:item['family'])
def test_replacement_preserves_identity_and_retirement_disables_history(retirement_db,proposal):
    db,source=retirement_db
    ref=promoted(db,source,proposal)
    if proposal['family']=='KNOWLEDGE':
        # Domain reviewer status alone does not grant private Knowledge access.
        # The fixture owner explicitly shares this native entity with reviewer.
        native=db.execute('SELECT NATIVE_ENTITY_ID FROM CX_CONTINUITY_ARTIFACT_REVS WHERE REVISION_ID=?',(ref['revision_id'],)).fetchone()[0]
        db.execute("INSERT INTO CX_KNOWLEDGE_ACCESS_POLICIES(POLICY_ID,ENTITY_ID,SCOPE_TYPE,PRINCIPAL_ID,CREATED_BY,REASON) VALUES('review-grant',?,'PRINCIPAL_PRIVATE','agent','owner','Explicit independent review')",(native,))
        db.commit()
    revisions=[]
    for index in (1,2):
        candidate=candidates.create_candidate('owner',dict(new_candidate(source,dict(proposal,title='Replacement '+str(index)),key='replacement-'+str(index)),replaces=ref))['candidate_id']
        revisions.append((candidate,approve(candidate)))
    result=candidates.promote_candidate('agent',*revisions[0])
    assert result['result_entity_id']==ref['entity_id'] and result['result_revision_id']!=ref['revision_id']
    with pytest.raises((PermissionError,ContinuityConflict)):
        candidates.promote_candidate('agent',*revisions[1])
    table='CX_MEMORY_VERSIONS' if proposal['family']=='MEMORY' else 'CX_CONTINUITY_ARTIFACT_REVS'
    column='VERSION_ID' if proposal['family']=='MEMORY' else 'REVISION_ID'
    digest=db.execute('SELECT CONTENT_DIGEST FROM '+table+' WHERE '+column+'=?',(result['result_revision_id'],)).fetchone()[0]
    current=dict(ref,revision_id=result['result_revision_id'],content_digest=digest)
    assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==2
    retirement.retire('owner',dict(source=current,expected_version=2,reason='Retire all versions',idempotency_key='retire'))
    for version in (ref,current):
        with pytest.raises((PermissionError,ContinuityConflict)):
            retirement.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,'owner','domain',version))
    assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==2
