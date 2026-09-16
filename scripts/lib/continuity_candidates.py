"""Typed candidate revisions and independently authorized review transactions.

Formal objects are written by continuity_promotions in this same transaction;
pending candidate rows never enter the ordinary artifact retrieval APIs.
"""
from pydantic import TypeAdapter

from . import connection, identity_api, continuity_work as work
from .continuity_contracts import (NewCandidate, CandidateRevision, CandidatePayload, CandidateReview,
                                  CandidatePromotion, Proposal, content_digest, request_digest)
from .continuity_state import ContinuityError, ContinuityConflict, require_version, require_idempotent_request
from .continuity_sources import resolve

FIELDS={
    'MEMORY':('TITLE','BODY','MEMORY_TYPE'),
    'KNOWLEDGE':('TITLE','BODY'),
    'EXPERIENCE':('TITLE','PROBLEM','SOLUTION','VALIDATION','APPLICABILITY'),
    'SKILL':('TITLE','INSTRUCTIONS','INPUT_CONTRACT','OUTPUT_CONTRACT'),
}
ACTIONS={'MEMORY':'memory.write','KNOWLEDGE':'knowledge.write','EXPERIENCE':'knowledge.write','SKILL':'skills.write'}


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    body='TEXT' if dialect in {'pg','postgresql'} else 'CLOB'
    ddl=[
        "CREATE TABLE CX_ARTIFACT_CANDIDATES (CANDIDATE_ID VARCHAR(128) PRIMARY KEY, "
        "FAMILY VARCHAR(24) NOT NULL CHECK(FAMILY IN ('MEMORY','KNOWLEDGE','EXPERIENCE','SKILL')), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "PROPOSED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PENDING','REVIEWING','APPROVED','REJECTED','EXPIRED','SUPERSEDED')), "
        "VERSION INTEGER NOT NULL CHECK(VERSION>0), CURRENT_REVISION_NO INTEGER NOT NULL CHECK(CURRENT_REVISION_NO>0), "
        "REVIEWED_BY VARCHAR(128) REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "RESULT_ENTITY_ID VARCHAR(128), RESULT_REVISION_ID VARCHAR(128), "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        "CREATE TABLE CX_CANDIDATE_REVISIONS (CANDIDATE_ID VARCHAR(128) NOT NULL REFERENCES CX_ARTIFACT_CANDIDATES(CANDIDATE_ID), "
        "REVISION_NO INTEGER NOT NULL CHECK(REVISION_NO>0), CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "REPLACES_ENTITY_ID VARCHAR(128), REPLACES_REVISION_ID VARCHAR(128), REPLACES_DIGEST VARCHAR(64), "
        f"CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), REASON {body} NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, PRIMARY KEY(CANDIDATE_ID,REVISION_NO), "
        "CHECK((REPLACES_ENTITY_ID IS NULL AND REPLACES_REVISION_ID IS NULL AND REPLACES_DIGEST IS NULL) OR "
        "(REPLACES_ENTITY_ID IS NOT NULL AND REPLACES_REVISION_ID IS NOT NULL AND REPLACES_DIGEST IS NOT NULL)))",
        "CREATE TABLE CX_CANDIDATE_SOURCES (CANDIDATE_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), FAMILY VARCHAR(24) NOT NULL, ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, PRIMARY KEY(CANDIDATE_ID,REVISION_NO,ITEM_NO), "
        "FOREIGN KEY(CANDIDATE_ID,REVISION_NO) REFERENCES CX_CANDIDATE_REVISIONS(CANDIDATE_ID,REVISION_NO))",
        "CREATE TABLE CX_CANDIDATE_REVIEWS (REVIEW_ID VARCHAR(128) PRIMARY KEY, CANDIDATE_ID VARCHAR(128) NOT NULL, "
        "REVISION_NO INTEGER NOT NULL, REVIEWER_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "DECISION VARCHAR(24) NOT NULL CHECK(DECISION IN ('APPROVED','REJECTED')), CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        f"REASON {body} NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(CANDIDATE_ID,REVISION_NO), "
        "FOREIGN KEY(CANDIDATE_ID,REVISION_NO) REFERENCES CX_CANDIDATE_REVISIONS(CANDIDATE_ID,REVISION_NO))",
        "CREATE TABLE CX_CANDIDATE_REQUESTS (ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "OPERATION VARCHAR(64) NOT NULL, IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CANDIDATE_ID VARCHAR(128) NOT NULL REFERENCES CX_ARTIFACT_CANDIDATES(CANDIDATE_ID), RESOURCE_VERSION INTEGER NOT NULL CHECK(RESOURCE_VERSION>0), "
        "PRIMARY KEY(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY))",
    ]
    for family,fields in FIELDS.items():
        ddl.append(f"CREATE TABLE CX_CANDIDATE_{family} (CANDIDATE_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "+
                   ', '.join(field+' '+('VARCHAR(24)' if field=='MEMORY_TYPE' else body)+' NOT NULL' for field in fields)+
                   ", PRIMARY KEY(CANDIDATE_ID,REVISION_NO), FOREIGN KEY(CANDIDATE_ID,REVISION_NO) REFERENCES CX_CANDIDATE_REVISIONS(CANDIDATE_ID,REVISION_NO))")
    ddl.append("CREATE TABLE CX_CANDIDATE_SKILL_ACTIONS (CANDIDATE_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
               "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), RESOURCE_ACTION VARCHAR(128) NOT NULL, PRIMARY KEY(CANDIDATE_ID,REVISION_NO,ITEM_NO), "
               "FOREIGN KEY(CANDIDATE_ID,REVISION_NO) REFERENCES CX_CANDIDATE_SKILL(CANDIDATE_ID,REVISION_NO))")
    return ddl


def _payload(request):
    return CandidatePayload(content=request.content,sources=request.sources,replaces=request.replaces)


def _authority(tx,actor,domain,family,*,review=False):
    work._authorize(tx,actor,domain,write=True)
    action=ACTIONS[family] if review else 'actions.propose'
    if identity_api.effective_access(actor,action,resource={'security_domain_id':domain}).get('decision')!='ALLOW':
        raise PermissionError('Candidate operation denied')
    if review:
        member=tx.query_one("SELECT MEMBERSHIP_TIER FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain AND PRINCIPAL_ID=:actor",
                            {'domain':domain,'actor':actor})
        if member['membership_tier'] not in {'OWNER','ADMIN'}:
            raise PermissionError('Candidate review requires a domain administrator')


def _sources(tx,actor,domain,payload):
    for source in payload.sources:
        resolve(tx,actor,domain,source,purpose='CANDIDATE_REVIEW')
    if payload.replaces:
        resolve(tx,actor,domain,payload.replaces,purpose='CANDIDATE_REVIEW')


def _receipt(tx,actor,operation,request,candidate_id=None):
    row=tx.query_one("SELECT REQUEST_DIGEST,CANDIDATE_ID,RESOURCE_VERSION FROM CX_CANDIDATE_REQUESTS "
                     "WHERE ACTOR_ID=:actor AND OPERATION=:operation AND IDEMPOTENCY_KEY=:key",
                     {'actor':actor,'operation':operation,'key':request.idempotency_key})
    if not row:
        return None
    require_idempotent_request(row['request_digest'],request_digest(actor,operation,request))
    if candidate_id is not None and candidate_id!=row['candidate_id']:
        raise ContinuityConflict('IDEMPOTENCY_CONFLICT','The key belongs to another candidate')
    return {'candidate_id':row['candidate_id'],'version':int(row['resource_version']),'replayed':True}


def _record(tx,actor,operation,request,candidate_id,version):
    tx.execute("INSERT INTO CX_CANDIDATE_REQUESTS(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY,REQUEST_DIGEST,CANDIDATE_ID,RESOURCE_VERSION) "
               "VALUES(:actor,:operation,:key,:digest,:candidate,:version)",
               {'actor':actor,'operation':operation,'key':request.idempotency_key,'digest':request_digest(actor,operation,request),
                'candidate':candidate_id,'version':version})
    identity_api._audit_tx(tx,actor,operation,'ARTIFACT_CANDIDATE',candidate_id,'ALLOW',request.reason)
    return {'candidate_id':candidate_id,'version':version,'replayed':False}


def _write(tx,actor,candidate_id,revision,payload,reason):
    old=payload.replaces
    tx.execute("INSERT INTO CX_CANDIDATE_REVISIONS(CANDIDATE_ID,REVISION_NO,CONTENT_DIGEST,REPLACES_ENTITY_ID,REPLACES_REVISION_ID,REPLACES_DIGEST,CREATED_BY,REASON) "
               "VALUES(:candidate,:revision,:digest,:entity,:old_revision,:old_digest,:actor,:reason)",
               {'candidate':candidate_id,'revision':revision,'digest':content_digest(payload),'entity':old.entity_id if old else None,
                'old_revision':old.revision_id if old else None,'old_digest':old.content_digest if old else None,'actor':actor,'reason':reason})
    family=payload.content.family
    fields=FIELDS[family]
    params={name.lower():getattr(payload.content,name.lower()) for name in fields}
    params.update(candidate=candidate_id,revision=revision)
    tx.execute(f"INSERT INTO CX_CANDIDATE_{family}(CANDIDATE_ID,REVISION_NO,"+','.join(fields)+") VALUES(:candidate,:revision,"+
               ','.join(':v_'+field.lower() for field in fields)+')',
               {'candidate':candidate_id,'revision':revision,**{'v_'+field.lower():params[field.lower()] for field in fields}})
    if family=='SKILL':
        for index,action in enumerate(payload.content.required_actions,1):
            tx.execute("INSERT INTO CX_CANDIDATE_SKILL_ACTIONS(CANDIDATE_ID,REVISION_NO,ITEM_NO,RESOURCE_ACTION) VALUES(:candidate,:revision,:item_no,:action)",
                       {'candidate':candidate_id,'revision':revision,'item_no':index,'action':action})
    for index,source in enumerate(payload.sources,1):
        tx.execute("INSERT INTO CX_CANDIDATE_SOURCES(CANDIDATE_ID,REVISION_NO,ITEM_NO,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST) "
                   "VALUES(:candidate,:revision,:item_no,:family,:entity,:source_revision,:digest)",
                   {'candidate':candidate_id,'revision':revision,'item_no':index,'family':source.family.value,'entity':source.entity_id,
                    'source_revision':source.revision_id,'digest':source.content_digest})


def _read(tx,root,revision=None):
    selected=int(root['current_revision_no']) if revision is None else revision
    require_version(selected,selected)
    params={'candidate':root['candidate_id'],'revision':selected}
    record=tx.query_one("SELECT * FROM CX_CANDIDATE_REVISIONS WHERE CANDIDATE_ID=:candidate AND REVISION_NO=:revision",params)
    if not record:
        raise ContinuityConflict('REVISION_UNAVAILABLE','Candidate revision unavailable')
    fields=FIELDS[root['family']]
    typed=tx.query_one('SELECT '+','.join(fields)+f" FROM CX_CANDIDATE_{root['family']} WHERE CANDIDATE_ID=:candidate AND REVISION_NO=:revision",params)
    if not typed:
        raise ContinuityError('INTEGRITY_ERROR','Candidate type content is missing')
    values={key:(value.read() if hasattr(value,'read') else value) for key,value in typed.items()}
    if root['family']=='SKILL':
        values['required_actions']=[row['resource_action'] for row in tx.query("SELECT RESOURCE_ACTION FROM CX_CANDIDATE_SKILL_ACTIONS "
            "WHERE CANDIDATE_ID=:candidate AND REVISION_NO=:revision ORDER BY ITEM_NO",params)]
    content=TypeAdapter(Proposal).validate_python(dict(values,family=root['family']))
    sources=tx.query("SELECT FAMILY,ENTITY_ID,SOURCE_REVISION_ID AS REVISION_ID,CONTENT_DIGEST FROM CX_CANDIDATE_SOURCES "
                     "WHERE CANDIDATE_ID=:candidate AND REVISION_NO=:revision ORDER BY ITEM_NO",params)
    old=None if record['replaces_entity_id'] is None else dict(family=root['family'],entity_id=record['replaces_entity_id'],
         revision_id=record['replaces_revision_id'],content_digest=record['replaces_digest'])
    payload=CandidatePayload(content=content,sources=sources,replaces=old)
    if content_digest(payload)!=record['content_digest']:
        raise ContinuityError('INTEGRITY_ERROR','Candidate revision failed integrity validation')
    return payload,record['content_digest']


def _lock(tx,actor,candidate_id,*,write=True):
    work._lock_actor(tx,actor)
    root=tx.query_one("SELECT * FROM CX_ARTIFACT_CANDIDATES WHERE CANDIDATE_ID=:candidate"+(' FOR UPDATE' if write else ''),{'candidate':candidate_id})
    if not root:
        raise PermissionError('Candidate access denied')
    work._authorize(tx,actor,root['security_domain_id'],write=write)
    return root


def create_candidate(actor,value):
    request=value if isinstance(value,NewCandidate) else NewCandidate.model_validate(value)
    return connection.execute_transaction_callback(lambda tx:_create_candidate(tx,actor,request))


def _create_candidate(tx,actor,request):
        _authority(tx,actor,request.security_domain_id,request.content.family)
        payload=_payload(request)
        _sources(tx,actor,request.security_domain_id,payload)
        prior=_receipt(tx,actor,'CANDIDATE_CREATE',request)
        if prior:
            return prior
        candidate_id=work._id('AC')
        tx.execute("INSERT INTO CX_ARTIFACT_CANDIDATES(CANDIDATE_ID,FAMILY,SECURITY_DOMAIN_ID,PROPOSED_BY,STATUS,VERSION,CURRENT_REVISION_NO) "
                   "VALUES(:candidate,:family,:domain,:actor,'PENDING',1,1)",
                   {'candidate':candidate_id,'family':request.content.family,'domain':request.security_domain_id,'actor':actor})
        _write(tx,actor,candidate_id,1,payload,request.reason)
        return _record(tx,actor,'CANDIDATE_CREATE',request,candidate_id,1)


def read_candidate(actor,candidate_id,revision=None):
    def perform(tx):
        root=_lock(tx,actor,candidate_id,write=False)
        if actor!=root['proposed_by']:
            _authority(tx,actor,root['security_domain_id'],root['family'],review=True)
        payload,digest=_read(tx,root,revision)
        _sources(tx,actor,root['security_domain_id'],payload)
        return {'candidate_id':candidate_id,'version':int(root['version']),'revision_no':int(root['current_revision_no']) if revision is None else revision,
                'current_revision_no':int(root['current_revision_no']),'proposed_by':root['proposed_by'],
                'security_domain_id':root['security_domain_id'],
                'status':root['status'],'payload':payload.model_dump(mode='json'),'content_digest':digest,
                'result_entity_id':root['result_entity_id'],'result_revision_id':root['result_revision_id']}
    return connection.execute_transaction_callback(perform)


def revise_candidate(actor,candidate_id,value):
    request=value if isinstance(value,CandidateRevision) else CandidateRevision.model_validate(value)
    def perform(tx):
        root=_lock(tx,actor,candidate_id)
        _authority(tx,actor,root['security_domain_id'],root['family'])
        if actor!=root['proposed_by'] or request.security_domain_id!=root['security_domain_id'] or request.content.family!=root['family']:
            raise PermissionError('Candidate ownership, domain and family cannot change')
        prior=_receipt(tx,actor,'CANDIDATE_REVISE',request,candidate_id)
        if prior:
            return prior
        require_version(int(root['version']),request.expected_version)
        if root['status']!='PENDING':
            raise ContinuityConflict('CANDIDATE_CLOSED','Only pending candidates can be revised')
        payload=_payload(request)
        _sources(tx,actor,root['security_domain_id'],payload)
        _write(tx,actor,candidate_id,int(root['current_revision_no'])+1,payload,request.reason)
        tx.execute("UPDATE CX_ARTIFACT_CANDIDATES SET VERSION=VERSION+1,CURRENT_REVISION_NO=CURRENT_REVISION_NO+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE CANDIDATE_ID=:candidate",{'candidate':candidate_id})
        return _record(tx,actor,'CANDIDATE_REVISE',request,candidate_id,request.expected_version+1)
    return connection.execute_transaction_callback(perform)


def review_candidate(actor,candidate_id,value):
    request=value if isinstance(value,CandidateReview) else CandidateReview.model_validate(value)
    def perform(tx):
        root=_lock(tx,actor,candidate_id)
        _authority(tx,actor,root['security_domain_id'],root['family'],review=True)
        if actor==root['proposed_by']:
            raise PermissionError('A proposer cannot review their own candidate')
        prior=_receipt(tx,actor,'CANDIDATE_REVIEW',request,candidate_id)
        if prior:
            return prior
        require_version(int(root['version']),request.expected_version)
        if root['status'] not in {'PENDING','REVIEWING'}:
            raise ContinuityConflict('CANDIDATE_CLOSED','The candidate has already been decided')
        payload,digest=_read(tx,root)
        if digest!=request.expected_digest:
            raise ContinuityConflict('STALE_CONTENT','Review must match the exact candidate revision')
        _sources(tx,actor,root['security_domain_id'],payload)
        tx.execute("INSERT INTO CX_CANDIDATE_REVIEWS(REVIEW_ID,CANDIDATE_ID,REVISION_NO,REVIEWER_ID,DECISION,CONTENT_DIGEST,REASON) "
                   "VALUES(:review_id,:candidate,:revision,:actor,:decision,:digest,:reason)",
                   {'review_id':work._id('CR'),'candidate':candidate_id,'revision':root['current_revision_no'],'actor':actor,
                    'decision':request.decision,'digest':digest,'reason':request.reason})
        tx.execute("UPDATE CX_ARTIFACT_CANDIDATES SET STATUS=:status,REVIEWED_BY=:actor,VERSION=VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE CANDIDATE_ID=:candidate",
                   {'status':request.decision,'actor':actor,'candidate':candidate_id})
        return _record(tx,actor,'CANDIDATE_REVIEW',request,candidate_id,request.expected_version+1)
    return connection.execute_transaction_callback(perform)


def promote_candidate(actor,candidate_id,value):
    request=value if isinstance(value,CandidatePromotion) else CandidatePromotion.model_validate(value)
    def perform(tx):
        root=_lock(tx,actor,candidate_id)
        _authority(tx,actor,root['security_domain_id'],root['family'],review=True)
        if actor==root['proposed_by']:
            raise PermissionError('A proposer cannot promote their own candidate')
        prior=_receipt(tx,actor,'CANDIDATE_PROMOTE',request,candidate_id)
        if prior:
            return dict(prior,result_entity_id=root['result_entity_id'],result_revision_id=root['result_revision_id'])
        require_version(int(root['version']),request.expected_version)
        if root['status']!='APPROVED' or root['result_entity_id'] is not None:
            raise ContinuityConflict('NOT_APPROVED','An unpromoted approved candidate is required')
        payload,digest=_read(tx,root)
        if digest!=request.expected_digest:
            raise ContinuityConflict('STALE_CONTENT','Promotion must match the approved revision')
        review=tx.query_one("SELECT REVIEWER_ID,CONTENT_DIGEST FROM CX_CANDIDATE_REVIEWS WHERE CANDIDATE_ID=:candidate AND REVISION_NO=:revision AND DECISION='APPROVED'",
                            {'candidate':candidate_id,'revision':root['current_revision_no']})
        if not review or review['content_digest']!=digest:
            raise ContinuityConflict('REVIEW_UNAVAILABLE','Matching approval is required')
        reviewer=tx.query_one("SELECT p.PRINCIPAL_ID FROM CX_PRINCIPALS p JOIN CX_DOMAIN_MEMBERS m ON m.PRINCIPAL_ID=p.PRINCIPAL_ID "
                              "WHERE p.PRINCIPAL_ID=:reviewer AND p.STATUS='ACTIVE' AND m.SECURITY_DOMAIN_ID=:domain AND m.STATUS='ACTIVE' "
                              "AND m.MEMBERSHIP_TIER IN ('OWNER','ADMIN') AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)",
                              {'reviewer':review['reviewer_id'],'domain':root['security_domain_id']})
        if not reviewer or identity_api.effective_access(review['reviewer_id'],ACTIONS[root['family']],
                resource={'security_domain_id':root['security_domain_id']}).get('decision')!='ALLOW':
            raise PermissionError('The approval no longer has an authorized reviewer')
        # No sender identity is used to read source text. The promoter must
        # independently have access to every exact source at promotion time.
        _sources(tx,actor,root['security_domain_id'],payload)
        from .continuity_promotions import promote
        result=promote(tx,actor,root,payload,request.reason)
        tx.execute("UPDATE CX_ARTIFACT_CANDIDATES SET RESULT_ENTITY_ID=:entity,RESULT_REVISION_ID=:revision,VERSION=VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP "
                   "WHERE CANDIDATE_ID=:candidate",{'entity':result['entity_id'],'revision':result['revision_id'],'candidate':candidate_id})
        return dict(_record(tx,actor,'CANDIDATE_PROMOTE',request,candidate_id,request.expected_version+1),
                    result_entity_id=result['entity_id'],result_revision_id=result['revision_id'])
    return connection.execute_transaction_callback(perform)
