"""Typed candidate transactions with actual relational writes in a unit DB."""
import pytest

from lib import continuity_candidates as candidates, continuity_promotions as promotions, continuity_handoff as handoff
from lib import continuity_sources as sources
from lib.continuity_contracts import SourceRef
from lib.continuity_state import ContinuityError, ContinuityConflict
from .test_continuity_work import database
from .test_continuity_handoff import fixture, offer_request

PROPOSALS=[
    dict(family='MEMORY',title='Validated fact',body='A verified synthetic fact.',memory_type='FACT'),
    dict(family='KNOWLEDGE',title='Knowledge',body='Verified synthetic knowledge.'),
    dict(family='EXPERIENCE',title='Experience',problem='Old state',solution='Revision check',validation='Tests passed',applicability='Concurrent edits'),
    dict(family='SKILL',title='Inspect state',instructions='Read the current authorized state.',input_contract='Work ID',output_contract='Current status',required_actions=['workspaces.read']),
]


@pytest.fixture
def candidate_db(fixture,monkeypatch):
    db,wid=fixture
    monkeypatch.setattr(candidates.connection,'DATABASE_DIALECT','oracle')
    monkeypatch.setattr(candidates.identity_api,'effective_access',lambda *a,**k:{'decision':'ALLOW','scopes':['ALL']})
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET MEMBERSHIP_TIER='ADMIN' WHERE PRINCIPAL_ID='agent'")
    for statement in candidates.schema_statements('pg')+promotions.schema_statements('pg'):
        db.execute(statement)
    db.executescript('''
        CREATE TABLE ENTITIES(ENTITY_ID TEXT PRIMARY KEY,ENTITY_TYPE TEXT,TITLE TEXT,CONTENT TEXT,STATUS TEXT,OWNED_BY_AGENT TEXT,VISIBILITY TEXT,EXPIRES_AT TIMESTAMP);
        CREATE TABLE KNOWLEDGE_META(ENTITY_ID TEXT PRIMARY KEY REFERENCES ENTITIES(ENTITY_ID),ENTITY_TYPE TEXT,REVIEW_COUNT INTEGER);
        CREATE TABLE CX_KNOWLEDGE_ACCESS_POLICIES(POLICY_ID TEXT,ENTITY_ID TEXT,SCOPE_TYPE TEXT,PRINCIPAL_ID TEXT,CREATED_BY TEXT,REASON TEXT,STATUS TEXT DEFAULT 'ACTIVE',VALID_FROM TIMESTAMP DEFAULT CURRENT_TIMESTAMP,VALID_UNTIL TIMESTAMP,ORGANIZATION_ID TEXT,HIERARCHY_DEPTH INTEGER);
        CREATE TABLE CX_ORGANIZATION_MEMBERS(PRINCIPAL_ID TEXT,ORGANIZATION_ID TEXT,STATUS TEXT,VALID_FROM TIMESTAMP,VALID_UNTIL TIMESTAMP);
        CREATE TABLE CX_ORGANIZATION_CLOSURE(ANCESTOR_ID TEXT,DESCENDANT_ID TEXT,DEPTH INTEGER);
        CREATE TABLE CX_ORGANIZATIONS(ORGANIZATION_ID TEXT,STATUS TEXT,VALID_FROM TIMESTAMP,VALID_UNTIL TIMESTAMP);
        CREATE TABLE CX_AGENT_RELATIONSHIPS(AGENT_ID TEXT,PRINCIPAL_ID TEXT,RELATIONSHIP_ROLE TEXT,STATUS TEXT,ENDED_AT TIMESTAMP);
        CREATE TABLE SKILL_META(ENTITY_ID TEXT PRIMARY KEY REFERENCES ENTITIES(ENTITY_ID),SKILL_NAME TEXT,SKILL_VERSION TEXT,SKILL_TYPE TEXT,SKILL_FORMAT TEXT,TEXT_CONTENT TEXT,RESOURCE_CHECKSUM TEXT,SKILL_DESCRIPTION TEXT,RUNTIME TEXT,PARAMETERS TEXT,DEPENDENCIES TEXT,SKILL_STATUS TEXT);
        CREATE TABLE CX_MEMORY_FAMILIES(FAMILY_ID TEXT PRIMARY KEY,CURRENT_VERSION_ID TEXT,FAMILY_STATE TEXT,OWNER_PRINCIPAL_ID TEXT,SECURITY_DOMAIN_ID TEXT,CLASSIFICATION TEXT,ROW_VERSION INTEGER DEFAULT 1,UPDATED_AT TIMESTAMP);
        CREATE TABLE CX_MEMORY_VERSIONS(VERSION_ID TEXT PRIMARY KEY,FAMILY_ID TEXT REFERENCES CX_MEMORY_FAMILIES(FAMILY_ID),VERSION_NUMBER INTEGER,TITLE TEXT,BODY_TEXT TEXT,CONTENT_DIGEST TEXT,MEMORY_TYPE TEXT,MEMORY_SCOPE TEXT,LIFECYCLE_STATE TEXT,CLASSIFICATION TEXT,SOURCE_REF TEXT,SOURCE_DIGEST TEXT,OWNER_PRINCIPAL_ID TEXT,OWNER_AGENT_ID TEXT,WORKSPACE_ID TEXT,SECURITY_DOMAIN_ID TEXT,VALID_UNTIL TIMESTAMP,POLICY_VERSION TEXT,CREATED_BY TEXT,REASON TEXT,METADATA_JSON TEXT);
        CREATE TABLE CX_MEMORY_REPRESENTATIONS(REPRESENTATION_ID TEXT,VERSION_ID TEXT REFERENCES CX_MEMORY_VERSIONS(VERSION_ID),REPRESENTATION_TYPE TEXT,BODY_TEXT TEXT,CONTENT_DIGEST TEXT,TOKEN_COUNT INTEGER,GENERATION_METHOD TEXT,SOURCE_VERSION_IDS_JSON TEXT);
        CREATE TABLE CX_MEMORY_PROJECTION_OUTBOX(OUTBOX_ID TEXT,AGGREGATE_TYPE TEXT,AGGREGATE_ID TEXT,EVENT_TYPE TEXT,PAYLOAD_JSON TEXT);
        CREATE TABLE CX_MEMORY_RELATIONS(RELATION_ID TEXT,SOURCE_VERSION_ID TEXT,TARGET_VERSION_ID TEXT,RELATION_TYPE TEXT,RELATION_STATE TEXT,DETERMINISTIC TEXT,METHOD TEXT,EVIDENCE_JSON TEXT,CREATED_BY TEXT);
    ''')
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    digest=handoff.read_handoff('owner',hid)['content_digest']
    return db,dict(family='HANDOFF',entity_id=hid,revision_id='1',content_digest=digest)


def new_candidate(source,content=PROPOSALS[0],key='candidate'):
    return dict(security_domain_id='domain',content=content,sources=[source],reason='Verified proposal',idempotency_key=key)


def approve(cid):
    read=candidates.read_candidate('agent',cid)
    value=dict(expected_version=read['version'],expected_digest=read['content_digest'],decision='APPROVED',reason='Independent review',idempotency_key='review-'+cid)
    candidates.review_candidate('agent',cid,value)
    return dict(expected_version=read['version']+1,expected_digest=read['content_digest'],reason='Explicit promotion',idempotency_key='promote-'+cid)


@pytest.mark.parametrize('proposal',PROPOSALS,ids=lambda item:item['family'])
def test_all_families_promote_to_native_entities_and_replay(candidate_db,proposal):
    db,source=candidate_db
    request=new_candidate(source,proposal)
    cid=candidates.create_candidate('owner',request)['candidate_id']
    assert candidates.create_candidate('owner',request)['replayed']
    assert db.execute('SELECT COUNT(*) FROM ENTITIES').fetchone()[0]==0
    value=approve(cid)
    result=candidates.promote_candidate('agent',cid,value)
    assert candidates.promote_candidate('agent',cid,value)['replayed']
    assert result['version']==3
    if proposal['family']=='MEMORY':
        assert db.execute('SELECT COUNT(*) FROM CX_MEMORY_FAMILIES').fetchone()[0]==1
        digest=db.execute('SELECT CONTENT_DIGEST FROM CX_MEMORY_VERSIONS').fetchone()[0]
    else:
        assert db.execute('SELECT ENTITY_TYPE FROM ENTITIES').fetchone()[0]==proposal['family']
        digest=db.execute('SELECT CONTENT_DIGEST FROM CX_CONTINUITY_ARTIFACT_REVS').fetchone()[0]
    ref=SourceRef(family=proposal['family'],entity_id=result['result_entity_id'],revision_id=result['result_revision_id'],content_digest=digest)
    resolved=candidates.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,'owner','domain',ref))
    assert proposal['title'] in resolved['text']


def test_self_approval_stale_content_and_post_review_mutation_denied(candidate_db):
    db,source=candidate_db
    request=new_candidate(source)
    cid=candidates.create_candidate('owner',request)['candidate_id']
    detail=candidates.read_candidate('owner',cid)
    review=dict(expected_version=1,expected_digest=detail['content_digest'],decision='APPROVED',reason='Review',idempotency_key='review')
    with pytest.raises(PermissionError):
        candidates.review_candidate('owner',cid,review)
    with pytest.raises(ContinuityConflict):
        candidates.review_candidate('agent',cid,dict(review,expected_digest='0'*64))
    changed=dict(request,expected_version=1,content=dict(request['content'],body='Changed fact'),idempotency_key='change')
    candidates.revise_candidate('owner',cid,changed)
    assert candidates.read_candidate('owner',cid,1)['payload']['content']['body']==request['content']['body']
    with pytest.raises(ContinuityConflict):
        candidates.review_candidate('agent',cid,review)
    approve(cid)
    with pytest.raises(ContinuityConflict):
        candidates.revise_candidate('owner',cid,dict(changed,expected_version=3,idempotency_key='late'))


@pytest.mark.parametrize('proposal',PROPOSALS,ids=lambda item:item['family'])
def test_promotion_audit_failure_rolls_back_every_native_object(candidate_db,monkeypatch,proposal):
    db,source=candidate_db
    cid=candidates.create_candidate('owner',new_candidate(source,proposal))['candidate_id']
    value=approve(cid)
    def fail(*args):
        raise RuntimeError('Audit failed')
    monkeypatch.setattr(candidates.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        candidates.promote_candidate('agent',cid,value)
    for table in ['ENTITIES','CX_MEMORY_FAMILIES','CX_MEMORY_VERSIONS','CX_MEMORY_REPRESENTATIONS','CX_MEMORY_PROJECTION_OUTBOX',
                  'CX_CONTINUITY_ARTIFACTS','CX_CONTINUITY_ARTIFACT_REVS','SKILL_META','KNOWLEDGE_META','CX_EXPERIENCE_META']:
        assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    row=db.execute('SELECT VERSION,RESULT_ENTITY_ID FROM CX_ARTIFACT_CANDIDATES').fetchone()
    assert row[:]==(2,None)


def test_revoked_source_prevents_approval_and_promotion(candidate_db):
    db,source=candidate_db
    cid=candidates.create_candidate('owner',new_candidate(source))['candidate_id']
    value=approve(cid)
    db.execute("UPDATE CX_HANDOFFS SET EXPIRES_AT='2000-01-01 00:00:00'")
    db.commit()
    with pytest.raises(ContinuityConflict):
        candidates.promote_candidate('agent',cid,value)
    assert db.execute('SELECT COUNT(*) FROM CX_MEMORY_FAMILIES').fetchone()[0]==0
