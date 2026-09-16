"""Atomic candidate promotion into existing, typed artifact business entities."""
import json
import secrets

from . import connection, continuity_work as work, identity_api
from .continuity_contracts import content_digest, KnowledgeProposal, SkillProposal, ExperienceProposal
from .continuity_state import ContinuityError, ContinuityConflict


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    body='TEXT' if dialect in {'pg','postgresql'} else 'CLOB'
    return [
        "CREATE TABLE CX_CONTINUITY_ARTIFACTS (ARTIFACT_ID VARCHAR(128) PRIMARY KEY, FAMILY VARCHAR(24) NOT NULL "
        "CHECK(FAMILY IN ('KNOWLEDGE','EXPERIENCE','SKILL')), OWNER_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "CURRENT_REVISION_ID VARCHAR(128) NOT NULL, VERSION INTEGER NOT NULL CHECK(VERSION>0), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('ACTIVE','RETIRED')), CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        "CREATE TABLE CX_CONTINUITY_ARTIFACT_REVS (ARTIFACT_ID VARCHAR(128) NOT NULL REFERENCES CX_CONTINUITY_ARTIFACTS(ARTIFACT_ID), "
        "REVISION_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL CHECK(REVISION_NO>0), NATIVE_ENTITY_ID VARCHAR(128) NOT NULL UNIQUE, "
        "CONTENT_DIGEST VARCHAR(64) NOT NULL, CANDIDATE_ID VARCHAR(128) NOT NULL, CANDIDATE_REVISION_NO INTEGER NOT NULL, "
        "CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "PRIMARY KEY(ARTIFACT_ID,REVISION_ID), UNIQUE(ARTIFACT_ID,REVISION_NO), UNIQUE(CANDIDATE_ID,CANDIDATE_REVISION_NO), "
        "FOREIGN KEY(CANDIDATE_ID,CANDIDATE_REVISION_NO) REFERENCES CX_CANDIDATE_REVISIONS(CANDIDATE_ID,REVISION_NO))",
        f"CREATE TABLE CX_EXPERIENCE_META (ENTITY_ID VARCHAR(128) PRIMARY KEY, PROBLEM {body} NOT NULL, SOLUTION {body} NOT NULL, "
        f"VALIDATION {body} NOT NULL, APPLICABILITY {body} NOT NULL)",
        f"CREATE TABLE CX_SKILL_CONTRACTS (ENTITY_ID VARCHAR(128) PRIMARY KEY, INPUT_CONTRACT {body} NOT NULL, OUTPUT_CONTRACT {body} NOT NULL)",
        "CREATE TABLE CX_SKILL_REQUIRED_ACTIONS (ENTITY_ID VARCHAR(128) NOT NULL REFERENCES CX_SKILL_CONTRACTS(ENTITY_ID), "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), RESOURCE_ACTION VARCHAR(128) NOT NULL, PRIMARY KEY(ENTITY_ID,ITEM_NO))",
    ]


def _promote_memory(tx,actor,root,payload,reason,classification):
    from . import memory_lifecycle as memory
    proposed=payload.content
    request=memory._request(dict(title=proposed.title,body=proposed.body,memory_type=proposed.memory_type,
        memory_scope='AGENT_MEMORY',classification=classification,security_domain_id=root['security_domain_id'],
        owner_principal_id=root['proposed_by'],source_ref='CANDIDATE:'+root['candidate_id']+':'+str(root['current_revision_no']),
        source_digest=content_digest(payload),reason=reason))
    findings=memory.inspect_ingestion(request.body)
    if findings['quarantine_recommended']:
        raise ContinuityConflict('INGESTION_REVIEW_REQUIRED','Candidate contains content requiring ingestion review')
    digest=memory._digest(request.title,request.body,request.memory_type,request.memory_scope,request.classification)
    old=payload.replaces
    family_id=old.entity_id if old else memory._id('MF')
    version_id=memory._id('MV')
    version=1
    if old:
        current=tx.query_one("SELECT CURRENT_VERSION_ID,OWNER_PRINCIPAL_ID,SECURITY_DOMAIN_ID,ROW_VERSION,FAMILY_STATE FROM CX_MEMORY_FAMILIES "
                             "WHERE FAMILY_ID=:family FOR UPDATE",{'family':family_id})
        if not current or current['current_version_id']!=old.revision_id or current['family_state']!='ACTIVE':
            raise ContinuityConflict('STALE_SOURCE','The replacement source changed')
        if current['owner_principal_id']!=root['proposed_by'] or current['security_domain_id']!=root['security_domain_id']:
            raise PermissionError('Replacement cannot change source ownership or domain')
        previous=tx.query_one("SELECT VERSION_NUMBER FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:revision",{'revision':old.revision_id})
        version=int(previous['version_number'])+1
    else:
        tx.execute("INSERT INTO CX_MEMORY_FAMILIES(FAMILY_ID,CURRENT_VERSION_ID,FAMILY_STATE,OWNER_PRINCIPAL_ID,SECURITY_DOMAIN_ID,CLASSIFICATION) "
                   "VALUES(:family,:revision,'ACTIVE',:owner,:domain,:classification)",
                   {'family':family_id,'revision':version_id,'owner':root['proposed_by'],'domain':root['security_domain_id'],'classification':classification})
    memory._insert_version(tx,version_id,family_id,version,request,digest,actor)
    memory._insert_source_representation(tx,version_id,request.body,digest)
    if old:
        tx.execute("UPDATE CX_MEMORY_FAMILIES SET CURRENT_VERSION_ID=:revision,FAMILY_STATE='ACTIVE',ROW_VERSION=ROW_VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP "
                   "WHERE FAMILY_ID=:family",{'revision':version_id,'family':family_id})
        tx.execute("UPDATE CX_MEMORY_VERSIONS SET LIFECYCLE_STATE='SUPERSEDED' WHERE VERSION_ID=:revision",{'revision':old.revision_id})
        memory._relation(tx,old.revision_id,version_id,'SUPERSEDES',deterministic=True,actor=actor)
    memory._outbox(tx,'FAMILY',family_id,'CURRENT_VERSION_CHANGED',{'family_id':family_id,'version_id':version_id,
        'candidate_id':root['candidate_id'],'candidate_revision_no':root['current_revision_no']})
    return {'entity_id':family_id,'revision_id':version_id,'content_digest':digest}


def _native_entity(tx,actor,root,payload,reason):
    content=payload.content
    pg=connection.DATABASE_DIALECT in {'pg','postgresql'}
    entity_id=secrets.randbelow(2**61)+2**61 if pg else work._id('ENT')
    principal=tx.query_one("SELECT PRINCIPAL_TYPE FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:owner",{'owner':root['proposed_by']})
    owner_agent=root['proposed_by'] if principal and principal['principal_type']=='AGENT' else None
    if owner_agent is not None and len(owner_agent)>64:
        raise ContinuityError('INVALID_OWNER','Agent identity exceeds the native entity owner limit')
    body=(content.body if content.family=='KNOWLEDGE' else content.instructions if content.family=='SKILL'
          else '\n\n'.join([content.problem,content.solution,content.validation,content.applicability]))
    tx.execute("INSERT INTO ENTITIES(ENTITY_ID,ENTITY_TYPE,TITLE,CONTENT,STATUS,OWNED_BY_AGENT,VISIBILITY) "+
               ('OVERRIDING SYSTEM VALUE ' if pg else '')+"VALUES(:entity,:family,:title,:body,'ACTIVE',:owner,'PRIVATE')",
               {'entity':entity_id,'family':content.family,'title':content.title[:500],'body':body,'owner':owner_agent})
    # Do not silently truncate an approved title: native title width is smaller
    # than the generic text DTO and must be validated before creating anything.
    if len(content.title)>500:
        raise ContinuityError('TITLE_TOO_LONG','Artifact titles are limited to 500 characters')
    if content.family=='KNOWLEDGE':
        tx.execute("INSERT INTO KNOWLEDGE_META(ENTITY_ID,ENTITY_TYPE,REVIEW_COUNT) VALUES(:entity,'KNOWLEDGE',0)",{'entity':entity_id})
        tx.execute("INSERT INTO CX_KNOWLEDGE_ACCESS_POLICIES(POLICY_ID,ENTITY_ID,SCOPE_TYPE,PRINCIPAL_ID,CREATED_BY,REASON) "
                   "VALUES(:policy,:entity,'PRINCIPAL_PRIVATE',:owner,:actor,:reason)",
                   {'policy':work._id('KAP'),'entity':str(entity_id),'owner':root['proposed_by'],'actor':actor,'reason':reason})
    elif content.family=='SKILL':
        native_digest=content_digest(content)
        tx.execute("INSERT INTO SKILL_META(ENTITY_ID,SKILL_NAME,SKILL_VERSION,SKILL_TYPE,SKILL_FORMAT,TEXT_CONTENT,RESOURCE_CHECKSUM,"
                   "SKILL_DESCRIPTION,RUNTIME,PARAMETERS,DEPENDENCIES,SKILL_STATUS) "
                   "VALUES(:entity,:name,'1.0.0','CUSTOM','TEXT',:body,:digest,:description,'OTHER',:parameters,:dependencies,'ACTIVE')",
                   {'entity':entity_id,'name':'candidate-'+root['candidate_id'],'body':content.instructions,'digest':native_digest,
                    'description':content.title[:500],'parameters':json.dumps({'input_contract':content.input_contract,'output_contract':content.output_contract}),
                    'dependencies':json.dumps({'required_actions':list(content.required_actions)})})
        tx.execute("INSERT INTO CX_SKILL_CONTRACTS(ENTITY_ID,INPUT_CONTRACT,OUTPUT_CONTRACT) VALUES(:entity,:input_contract,:output_contract)",
                   {'entity':str(entity_id),'input_contract':content.input_contract,'output_contract':content.output_contract})
        for index,action in enumerate(content.required_actions,1):
            tx.execute("INSERT INTO CX_SKILL_REQUIRED_ACTIONS(ENTITY_ID,ITEM_NO,RESOURCE_ACTION) VALUES(:entity,:item_no,:action)",
                       {'entity':str(entity_id),'item_no':index,'action':action})
    else:
        tx.execute("INSERT INTO CX_EXPERIENCE_META(ENTITY_ID,PROBLEM,SOLUTION,VALIDATION,APPLICABILITY) VALUES(:entity,:problem,:solution,:validation,:applicability)",
                   {'entity':str(entity_id),'problem':content.problem,'solution':content.solution,'validation':content.validation,'applicability':content.applicability})
    return str(entity_id)


def promote(tx,actor,root,payload,reason):
    domain=tx.query_one("SELECT CLASSIFICATION FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID=:domain",{'domain':root['security_domain_id']})
    if not domain or domain['classification'] not in {'PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED'}:
        raise PermissionError('A classified active domain is required')
    if len(payload.content.title)>500:
        raise ContinuityError('TITLE_TOO_LONG','Artifact titles are limited to 500 characters')
    if payload.content.family=='MEMORY':
        return _promote_memory(tx,actor,root,payload,reason,domain['classification'])
    old=payload.replaces
    family_id=old.entity_id if old else work._id('AF')
    revision=work._id('AR')
    version=1
    if old:
        previous=tx.query_one("SELECT * FROM CX_CONTINUITY_ARTIFACTS WHERE ARTIFACT_ID=:artifact FOR UPDATE",{'artifact':family_id})
        if not previous or previous['current_revision_id']!=old.revision_id or previous['status']!='ACTIVE':
            raise ContinuityConflict('STALE_SOURCE','The replacement source changed')
        if previous['owner_principal_id']!=root['proposed_by'] or previous['security_domain_id']!=root['security_domain_id'] or previous['family']!=root['family']:
            raise PermissionError('Replacement cannot change source ownership, family or domain')
        version=int(previous['version'])+1
    else:
        tx.execute("INSERT INTO CX_CONTINUITY_ARTIFACTS(ARTIFACT_ID,FAMILY,OWNER_PRINCIPAL_ID,SECURITY_DOMAIN_ID,CURRENT_REVISION_ID,VERSION,STATUS) "
                   "VALUES(:artifact,:family,:owner,:domain,:revision,1,'ACTIVE')",
                   {'artifact':family_id,'family':root['family'],'owner':root['proposed_by'],'domain':root['security_domain_id'],'revision':revision})
    entity=_native_entity(tx,actor,root,payload,reason)
    digest=content_digest(payload.content)
    tx.execute("INSERT INTO CX_CONTINUITY_ARTIFACT_REVS(ARTIFACT_ID,REVISION_ID,REVISION_NO,NATIVE_ENTITY_ID,CONTENT_DIGEST,CANDIDATE_ID,CANDIDATE_REVISION_NO,CREATED_BY) "
               "VALUES(:artifact,:revision,:version,:entity,:digest,:candidate,:candidate_revision,:actor)",
               {'artifact':family_id,'revision':revision,'version':version,'entity':entity,'digest':digest,'candidate':root['candidate_id'],
                'candidate_revision':root['current_revision_no'],'actor':actor})
    if old:
        tx.execute("UPDATE CX_CONTINUITY_ARTIFACTS SET CURRENT_REVISION_ID=:revision,VERSION=:version WHERE ARTIFACT_ID=:artifact",
                   {'revision':revision,'version':version,'artifact':family_id})
    return {'entity_id':family_id,'revision_id':revision,'content_digest':digest}


def resolve_artifact(tx,actor,domain,source):
    from .continuity_sources import _render
    work._authorize(tx,actor,domain,write=False)
    root=tx.query_one("SELECT * FROM CX_CONTINUITY_ARTIFACTS WHERE ARTIFACT_ID=:artifact AND FAMILY=:family AND STATUS='ACTIVE'",
                      {'artifact':source.entity_id,'family':source.family.value})
    if not root or root['security_domain_id']!=domain:
        raise PermissionError('Source access denied')
    action={'KNOWLEDGE':'knowledge.read','EXPERIENCE':'knowledge.read','SKILL':'skills.read'}[source.family.value]
    access=identity_api.effective_access(actor,action,resource={'security_domain_id':domain})
    if access.get('decision')!='ALLOW' or (actor!=root['owner_principal_id'] and 'ALL' not in access.get('scopes',[])):
        raise PermissionError('Source access denied')
    if source.family.value=='KNOWLEDGE':
        from .knowledge_api import knowledge_access_predicate
        revision=tx.query_one("SELECT NATIVE_ENTITY_ID FROM CX_CONTINUITY_ARTIFACT_REVS WHERE ARTIFACT_ID=:artifact AND REVISION_ID=:revision",
                              {'artifact':source.entity_id,'revision':source.revision_id})
        if not revision:
            raise PermissionError('Source access denied')
        entity_id=int(revision['native_entity_id']) if connection.DATABASE_DIALECT in {'pg','postgresql'} else revision['native_entity_id']
        allowed=tx.query_one("SELECT e.ENTITY_ID FROM ENTITIES e WHERE e.ENTITY_ID=:entity AND e.ENTITY_TYPE='KNOWLEDGE' AND "+
                             knowledge_access_predicate('e',':actor'),{'entity':entity_id,'actor':actor})
        if not allowed:
            raise PermissionError('Source access denied')
    return _artifact_payload(tx,source,domain)


def _artifact_payload(tx,source,domain):
    """Read native fields after ordinary-reader or publication authorization."""
    from .continuity_sources import _render
    revision=tx.query_one("SELECT * FROM CX_CONTINUITY_ARTIFACT_REVS WHERE ARTIFACT_ID=:artifact AND REVISION_ID=:revision",
                          {'artifact':source.entity_id,'revision':source.revision_id})
    if not revision or revision['content_digest']!=source.content_digest:
        raise ContinuityConflict('STALE_SOURCE','The exact artifact revision is unavailable')
    native=revision['native_entity_id']
    entity_id=int(native) if connection.DATABASE_DIALECT in {'pg','postgresql'} else native
    entity=tx.query_one("SELECT TITLE,CONTENT FROM ENTITIES WHERE ENTITY_ID=:entity AND ENTITY_TYPE=:family AND STATUS='ACTIVE' "
                        "AND (EXPIRES_AT IS NULL OR EXPIRES_AT>CURRENT_TIMESTAMP)",{'entity':entity_id,'family':source.family.value})
    if not entity:
        raise PermissionError('Source access denied')
    def text(value):
        return value.read() if hasattr(value,'read') else value
    title=text(entity['title'])
    if source.family.value=='KNOWLEDGE':
        content=KnowledgeProposal(family='KNOWLEDGE',title=title,body=text(entity['content']))
    elif source.family.value=='SKILL':
        meta=tx.query_one("SELECT TEXT_CONTENT,RESOURCE_CHECKSUM FROM SKILL_META WHERE ENTITY_ID=:entity AND SKILL_STATUS='ACTIVE'",{'entity':entity_id})
        contract=tx.query_one("SELECT INPUT_CONTRACT,OUTPUT_CONTRACT FROM CX_SKILL_CONTRACTS WHERE ENTITY_ID=:entity",{'entity':native})
        if not meta or not contract:
            raise PermissionError('Source access denied')
        actions=tx.query("SELECT RESOURCE_ACTION FROM CX_SKILL_REQUIRED_ACTIONS WHERE ENTITY_ID=:entity ORDER BY ITEM_NO",{'entity':native})
        content=SkillProposal(family='SKILL',title=title,instructions=text(meta['text_content']),input_contract=text(contract['input_contract']),
                              output_contract=text(contract['output_contract']),required_actions=[row['resource_action'] for row in actions])
        if content_digest(content)!=meta['resource_checksum']:
            raise ContinuityError('INTEGRITY_ERROR','Native Skill checksum is inconsistent')
    else:
        meta=tx.query_one("SELECT PROBLEM,SOLUTION,VALIDATION,APPLICABILITY FROM CX_EXPERIENCE_META WHERE ENTITY_ID=:entity",{'entity':native})
        if not meta:
            raise PermissionError('Source access denied')
        content=ExperienceProposal(family='EXPERIENCE',title=title,**{key:text(value) for key,value in meta.items()})
    if content_digest(content)!=source.content_digest:
        raise ContinuityError('INTEGRITY_ERROR','Native artifact failed integrity validation')
    return {'source':source.model_dump(mode='json'),'text':_render(content.model_dump(mode='json')),
            'content_digest':source.content_digest,'authorized_scope':domain}
