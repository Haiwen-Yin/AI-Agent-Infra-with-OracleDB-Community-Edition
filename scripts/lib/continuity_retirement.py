"""Explicit logical retirement of promoted artifacts; retain revision history."""
from . import connection, identity_api, continuity_work as work
from .continuity_contracts import ArtifactRetirement, request_digest
from .continuity_state import ContinuityConflict, require_version, require_idempotent_request


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    return [
        "CREATE TABLE CX_ARTIFACT_RETIREMENTS (RETIREMENT_ID VARCHAR(128) PRIMARY KEY, "
        "FAMILY VARCHAR(24) NOT NULL CHECK(FAMILY IN ('MEMORY','KNOWLEDGE','EXPERIENCE','SKILL')), ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, VERSION INTEGER NOT NULL CHECK(VERSION>0), "
        "ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "REASON VARCHAR(1000) NOT NULL, IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(FAMILY,ENTITY_ID), UNIQUE(ACTOR_ID,IDEMPOTENCY_KEY))",
    ]


def retire(actor,value):
    request=value if isinstance(value,ArtifactRetirement) else ArtifactRetirement.model_validate(value)
    source=request.source
    family=source.family.value
    def perform(tx):
        work._lock_actor(tx,actor)
        if family=='MEMORY':
            root=tx.query_one("SELECT OWNER_PRINCIPAL_ID,SECURITY_DOMAIN_ID,CURRENT_VERSION_ID AS CURRENT_REVISION_ID,ROW_VERSION AS VERSION,FAMILY_STATE AS STATUS "
                              "FROM CX_MEMORY_FAMILIES WHERE FAMILY_ID=:entity FOR UPDATE",{'entity':source.entity_id})
        else:
            root=tx.query_one("SELECT OWNER_PRINCIPAL_ID,SECURITY_DOMAIN_ID,CURRENT_REVISION_ID,VERSION,STATUS FROM CX_CONTINUITY_ARTIFACTS "
                              "WHERE ARTIFACT_ID=:entity AND FAMILY=:family FOR UPDATE",{'entity':source.entity_id,'family':family})
        if not root:
            raise PermissionError('Artifact retirement denied')
        work._authorize(tx,actor,root['security_domain_id'],write=True)
        action={'MEMORY':'memory.write','KNOWLEDGE':'knowledge.write','EXPERIENCE':'knowledge.write','SKILL':'skills.write'}[family]
        if actor!=root['owner_principal_id'] or identity_api.effective_access(actor,action,resource={'security_domain_id':root['security_domain_id']}).get('decision')!='ALLOW':
            raise PermissionError('Artifact retirement requires the current authorized owner')
        digest=request_digest(actor,'ARTIFACT_RETIRE',request)
        prior=tx.query_one("SELECT RETIREMENT_ID,FAMILY,ENTITY_ID,VERSION,REQUEST_DIGEST FROM CX_ARTIFACT_RETIREMENTS WHERE ACTOR_ID=:actor AND IDEMPOTENCY_KEY=:key",
                           {'actor':actor,'key':request.idempotency_key})
        if prior:
            require_idempotent_request(prior['request_digest'],digest)
            return dict(retirement_id=prior['retirement_id'],family=prior['family'],entity_id=prior['entity_id'],version=int(prior['version']),status='RETIRED',replayed=True)
        require_version(int(root['version']),request.expected_version)
        if root['status']!='ACTIVE' or root['current_revision_id']!=source.revision_id:
            raise ContinuityConflict('STALE_SOURCE','Retirement requires the current active revision')
        promoted=tx.query_one("SELECT CANDIDATE_ID FROM CX_ARTIFACT_CANDIDATES WHERE FAMILY=:family AND RESULT_ENTITY_ID=:entity AND RESULT_REVISION_ID=:revision",
                              {'family':family,'entity':source.entity_id,'revision':source.revision_id})
        if not promoted:
            raise PermissionError('This retirement operation requires a promoted artifact')
        from .continuity_sources import resolve
        resolve(tx,actor,root['security_domain_id'],source,purpose='ARTIFACT_RETIRE')
        if family=='MEMORY':
            # Availability is lifecycle metadata; immutable bodies/digests stay
            # intact. Every old version must stop contributing to context too.
            tx.execute("UPDATE CX_MEMORY_FAMILIES SET FAMILY_STATE='UNAVAILABLE',ROW_VERSION=ROW_VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE FAMILY_ID=:entity",{'entity':source.entity_id})
            tx.execute("UPDATE CX_MEMORY_VERSIONS SET LIFECYCLE_STATE='UNAVAILABLE' WHERE FAMILY_ID=:entity",{'entity':source.entity_id})
            from .memory_lifecycle import _outbox
            _outbox(tx,'FAMILY',source.entity_id,'RETIRED',{'family_id':source.entity_id,'version_id':source.revision_id,'actor':actor,'reason':request.reason})
        else:
            revisions=tx.query("SELECT NATIVE_ENTITY_ID FROM CX_CONTINUITY_ARTIFACT_REVS WHERE ARTIFACT_ID=:entity",{'entity':source.entity_id})
            for revision in revisions:
                native=int(revision['native_entity_id']) if connection.DATABASE_DIALECT in {'pg','postgresql'} else revision['native_entity_id']
                tx.execute("UPDATE ENTITIES SET STATUS='ARCHIVED' WHERE ENTITY_ID=:entity AND ENTITY_TYPE=:family",{'entity':native,'family':family})
                if family=='SKILL':
                    tx.execute("UPDATE SKILL_META SET SKILL_STATUS='DISABLED' WHERE ENTITY_ID=:entity",{'entity':native})
            tx.execute("UPDATE CX_CONTINUITY_ARTIFACTS SET STATUS='RETIRED',VERSION=VERSION+1 WHERE ARTIFACT_ID=:entity",{'entity':source.entity_id})
        retirement_id=work._id('RT')
        tx.execute("INSERT INTO CX_ARTIFACT_RETIREMENTS(RETIREMENT_ID,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,VERSION,ACTOR_ID,SECURITY_DOMAIN_ID,REASON,IDEMPOTENCY_KEY,REQUEST_DIGEST) "
                   "VALUES(:retirement,:family,:entity,:revision,:digest,:version,:actor,:domain,:reason,:key,:request_digest)",
                   {'retirement':retirement_id,'family':family,'entity':source.entity_id,'revision':source.revision_id,'digest':source.content_digest,
                    'version':request.expected_version+1,'actor':actor,'domain':root['security_domain_id'],'reason':request.reason,'key':request.idempotency_key,'request_digest':digest})
        identity_api._audit_tx(tx,actor,'ARTIFACT_RETIRE',family,source.entity_id,'ALLOW',request.reason)
        return dict(retirement_id=retirement_id,family=family,entity_id=source.entity_id,version=request.expected_version+1,status='RETIRED',replayed=False)
    return connection.execute_transaction_callback(perform)
