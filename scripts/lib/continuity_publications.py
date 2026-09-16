"""Explicit exact-version publication grants with live revocation checks.

Publication does not copy body text and never uses the publisher's identity as
the recipient's database session. Private source ownership must authorize the
grant; both domain administration and classification boundaries are checked.
"""
from datetime import datetime,timezone

from . import connection,identity_api,continuity_work as work
from .continuity_contracts import NewPublication,PublicationRevocation,request_digest,SourceRef
from .continuity_state import ContinuityError,ContinuityConflict,require_version,require_not_expired,require_idempotent_request
from .continuity_handoff import _utc

LEVELS={'PUBLIC':0,'INTERNAL':1,'CONFIDENTIAL':2,'RESTRICTED':3}
READ_ACTION={'HANDOFF':'workspaces.read','MEMORY':'memory.read','KNOWLEDGE':'knowledge.read','EXPERIENCE':'knowledge.read','SKILL':'skills.read'}
WRITE_ACTION={key:value.replace('.read','.write') for key,value in READ_ACTION.items()}


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    return [
        "CREATE TABLE CX_CONTEXT_PUBLICATIONS (PUBLICATION_ID VARCHAR(128) PRIMARY KEY, FAMILY VARCHAR(24) NOT NULL "
        "CHECK(FAMILY IN ('MEMORY','KNOWLEDGE','EXPERIENCE','SKILL','HANDOFF')), ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "SOURCE_SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "TARGET_SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "PUBLISHED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), PURPOSE VARCHAR(1000) NOT NULL, "
        "CLASSIFICATION VARCHAR(24) NOT NULL CHECK(CLASSIFICATION IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')), "
        "EXPIRES_AT TIMESTAMP NOT NULL, STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PUBLISHED','REVOKED')), "
        "VERSION INTEGER NOT NULL CHECK(VERSION>0), IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(PUBLISHED_BY,IDEMPOTENCY_KEY))",
        "CREATE TABLE CX_PUBLICATION_EVENTS (EVENT_ID VARCHAR(128) PRIMARY KEY, "
        "PUBLICATION_ID VARCHAR(128) NOT NULL REFERENCES CX_CONTEXT_PUBLICATIONS(PUBLICATION_ID), "
        "VERSION INTEGER NOT NULL CHECK(VERSION>0), ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "OPERATION VARCHAR(24) NOT NULL CHECK(OPERATION IN ('PUBLISH','REVOKE')), REASON VARCHAR(1000) NOT NULL, "
        "IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(PUBLICATION_ID,VERSION), UNIQUE(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY))",
    ]


def _admin(tx,actor,domain):
    # No second Principal lock when a recipient revalidates a publisher grant.
    row=tx.query_one("SELECT d.CLASSIFICATION FROM CX_PRINCIPALS p JOIN CX_DOMAIN_MEMBERS m ON m.PRINCIPAL_ID=p.PRINCIPAL_ID "
                     "JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID=m.SECURITY_DOMAIN_ID "
                     "WHERE p.PRINCIPAL_ID=:actor AND p.STATUS='ACTIVE' AND d.SECURITY_DOMAIN_ID=:domain AND d.STATUS='ACTIVE' "
                     "AND m.STATUS='ACTIVE' AND m.MEMBERSHIP_TIER IN ('OWNER','ADMIN') AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)",
                     {'actor':actor,'domain':domain})
    if not row or identity_api.effective_access(actor,'workspaces.write',resource={'security_domain_id':domain}).get('decision')!='ALLOW':
        raise PermissionError('Publication administration denied')
    return row['classification']


def _publisher(tx,actor,source,metadata,target,classification):
    if metadata['owner_principal_id']!=actor:
        raise PermissionError('Only the source owner can publish this private source')
    _admin(tx,actor,metadata['security_domain_id'])
    target_class=_admin(tx,actor,target)
    if (metadata['classification'] not in LEVELS or target_class not in LEVELS or classification not in LEVELS
            or not LEVELS[metadata['classification']]<=LEVELS[classification]<=LEVELS[target_class]):
        raise PermissionError('Publication classification exceeds the target or downgrades its source')
    if identity_api.effective_access(actor,WRITE_ACTION[source.family.value],resource={'security_domain_id':metadata['security_domain_id']}).get('decision')!='ALLOW':
        raise PermissionError('Source publication denied')
    if source.family.value=='KNOWLEDGE':
        # Revoking the native private policy must also invalidate its grants.
        row=tx.query_one("SELECT r.NATIVE_ENTITY_ID FROM CX_CONTINUITY_ARTIFACT_REVS r JOIN CX_KNOWLEDGE_ACCESS_POLICIES p "
                         "ON p.ENTITY_ID=r.NATIVE_ENTITY_ID WHERE r.ARTIFACT_ID=:entity AND r.REVISION_ID=:revision "
                         "AND p.PRINCIPAL_ID=:actor AND p.SCOPE_TYPE='PRINCIPAL_PRIVATE' AND p.STATUS='ACTIVE' "
                         "AND p.VALID_FROM<=CURRENT_TIMESTAMP AND (p.VALID_UNTIL IS NULL OR p.VALID_UNTIL>CURRENT_TIMESTAMP)",
                         {'entity':source.entity_id,'revision':source.revision_id,'actor':actor})
        if not row:
            raise PermissionError('Native source policy no longer permits publication')


def _event(tx,actor,publication_id,version,operation,request):
    event_id=work._id('PE')
    tx.execute("INSERT INTO CX_PUBLICATION_EVENTS(EVENT_ID,PUBLICATION_ID,VERSION,ACTOR_ID,OPERATION,REASON,IDEMPOTENCY_KEY,REQUEST_DIGEST) "
               "VALUES(:event,:publication,:version,:actor,:operation,:reason,:key,:digest)",
               {'event':event_id,'publication':publication_id,'version':version,'actor':actor,'operation':operation,'reason':request.reason,
                'key':request.idempotency_key,'digest':request_digest(actor,'CONTEXT_'+operation,request)})
    identity_api._audit_tx(tx,actor,'CONTEXT_'+operation,'CONTEXT_PUBLICATION',publication_id,'ALLOW',request.reason)
    return {'publication_id':publication_id,'version':version,'publication_event_id':event_id,'replayed':False}


def publish(actor,value):
    request=value if isinstance(value,NewPublication) else NewPublication.model_validate(value)
    def perform(tx):
        from .continuity_sources import locate,resolve
        work._lock_actor(tx,actor)
        source=request.source
        if source.family.value not in WRITE_ACTION:
            raise ContinuityError('PUBLICATION_UNAVAILABLE','This source family cannot be published across domains')
        metadata=locate(tx,source)
        _publisher(tx,actor,source,metadata,request.target_security_domain_id,request.classification)
        resolve(tx,actor,metadata['security_domain_id'],source)
        existing=tx.query_one("SELECT PUBLICATION_ID,REQUEST_DIGEST,EXPIRES_AT,STATUS FROM CX_CONTEXT_PUBLICATIONS WHERE PUBLISHED_BY=:actor AND IDEMPOTENCY_KEY=:key",
                              {'actor':actor,'key':request.idempotency_key})
        if existing:
            require_idempotent_request(existing['request_digest'],request_digest(actor,'CONTEXT_PUBLISH',request))
            require_not_expired(_utc(existing['expires_at']),datetime.now(timezone.utc))
            return {'publication_id':existing['publication_id'],'version':1,'replayed':True,'status':existing['status']}
        require_not_expired(request.expires_at,datetime.now(timezone.utc))
        publication_id=work._id('CP')
        tx.execute("INSERT INTO CX_CONTEXT_PUBLICATIONS(PUBLICATION_ID,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,SOURCE_SECURITY_DOMAIN_ID,"
                   "TARGET_SECURITY_DOMAIN_ID,PUBLISHED_BY,PURPOSE,CLASSIFICATION,EXPIRES_AT,STATUS,VERSION,IDEMPOTENCY_KEY,REQUEST_DIGEST) "
                   "VALUES(:publication,:family,:entity,:revision,:digest,:source_domain,:target_domain,:actor,:purpose,:classification,:expires,'PUBLISHED',1,:key,:request_digest)",
                   {'publication':publication_id,'family':source.family.value,'entity':source.entity_id,'revision':source.revision_id,'digest':source.content_digest,
                    'source_domain':metadata['security_domain_id'],'target_domain':request.target_security_domain_id,'actor':actor,
                    'purpose':request.purpose,'classification':request.classification,'expires':request.expires_at.replace(tzinfo=None),
                    'key':request.idempotency_key,'request_digest':request_digest(actor,'CONTEXT_PUBLISH',request)})
        return _event(tx,actor,publication_id,1,'PUBLISH',request)
    return connection.execute_transaction_callback(perform)


def revoke(actor,publication_id,value):
    request=value if isinstance(value,PublicationRevocation) else PublicationRevocation.model_validate(value)
    def perform(tx):
        work._lock_actor(tx,actor)
        row=tx.query_one("SELECT * FROM CX_CONTEXT_PUBLICATIONS WHERE PUBLICATION_ID=:publication FOR UPDATE",{'publication':publication_id})
        if not row:
            raise PermissionError('Publication access denied')
        _admin(tx,actor,row['source_security_domain_id'])
        prior=tx.query_one("SELECT PUBLICATION_ID,VERSION,EVENT_ID,REQUEST_DIGEST FROM CX_PUBLICATION_EVENTS WHERE ACTOR_ID=:actor AND OPERATION='REVOKE' AND IDEMPOTENCY_KEY=:key",
                           {'actor':actor,'key':request.idempotency_key})
        if prior:
            require_idempotent_request(prior['request_digest'],request_digest(actor,'CONTEXT_REVOKE',request))
            if prior['publication_id']!=publication_id:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT','The key belongs to another publication')
            return {'publication_id':publication_id,'version':int(prior['version']),'publication_event_id':prior['event_id'],'replayed':True}
        require_version(int(row['version']),request.expected_version)
        if row['status']!='PUBLISHED':
            raise ContinuityConflict('PUBLICATION_REVOKED','The publication is already revoked')
        tx.execute("UPDATE CX_CONTEXT_PUBLICATIONS SET STATUS='REVOKED',VERSION=VERSION+1 WHERE PUBLICATION_ID=:publication",{'publication':publication_id})
        return _event(tx,actor,publication_id,request.expected_version+1,'REVOKE',request)
    return connection.execute_transaction_callback(perform)


def resolve_publication(tx,actor,target,source,metadata,*,purpose=None,publication_id=None):
    from .continuity_sources import publication_payload
    work._authorize(tx,actor,target,write=False)
    if not purpose:
        raise PermissionError('Published context requires an explicit use purpose')
    if identity_api.effective_access(actor,READ_ACTION[source.family.value],resource={'security_domain_id':target}).get('decision')!='ALLOW':
        raise PermissionError('Published source access denied')
    rows=tx.query("SELECT PUBLICATION_ID,PUBLISHED_BY,CLASSIFICATION,SOURCE_SECURITY_DOMAIN_ID FROM CX_CONTEXT_PUBLICATIONS "
                  "WHERE FAMILY=:family AND ENTITY_ID=:entity AND SOURCE_REVISION_ID=:revision AND CONTENT_DIGEST=:digest "
                  "AND TARGET_SECURITY_DOMAIN_ID=:target_domain AND PURPOSE=:purpose AND STATUS='PUBLISHED' AND EXPIRES_AT>:now "
                  +("AND PUBLICATION_ID=:publication " if publication_id is not None else '')+"ORDER BY CREATED_AT",
                  {'family':source.family.value,'entity':source.entity_id,'revision':source.revision_id,'digest':source.content_digest,
                   'target_domain':target,'purpose':purpose,'now':datetime.now(timezone.utc).replace(tzinfo=None),
                   **({'publication':publication_id} if publication_id is not None else {})})
    for row in rows:
        if row['source_security_domain_id']!=metadata['security_domain_id']:
            continue
        try:
            _publisher(tx,row['published_by'],source,metadata,target,row['classification'])
        except PermissionError:
            continue
        result=publication_payload(tx,source,target,actor=actor)
        return dict(result,publication_id=row['publication_id'])
    raise PermissionError('No current publication authorizes this exact source')
