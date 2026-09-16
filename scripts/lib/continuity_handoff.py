"""Transactional, recipient-bound work handoffs backed by normalized entities."""
from datetime import datetime, timezone

from . import connection, identity_api
from . import continuity_work as work
from .continuity_contracts import NewHandoff, HandoffDecision, HandoffRevision, HandoffOutcome, HandoffContent, WorkContent, content_digest, request_digest
from .continuity_state import (ContinuityError, ContinuityConflict, acknowledge_handoff,
                              require_version, require_not_expired, require_transition, require_idempotent_request)

ACTIVE = {'DRAFT', 'OFFERED', 'ACKNOWLEDGED', 'IN_PROGRESS'}
SECTION_FIELDS = {'DECISION':'decisions', 'CONSTRAINT':'constraints', 'QUESTION':'open_questions', 'RISK':'risks_and_blockers'}


def schema_statements(dialect):
    if dialect not in {'oracle','yashandb','pg','postgresql'}:
        raise ValueError('unsupported database adapter')
    text = 'TEXT' if dialect in {'pg','postgresql'} else 'CLOB'
    return [
        "CREATE TABLE CX_HANDOFFS (HANDOFF_ID VARCHAR(128) PRIMARY KEY, "
        "WORK_CONTRACT_ID VARCHAR(128) NOT NULL REFERENCES CX_WORK_CONTRACTS(WORK_CONTRACT_ID), "
        "FROM_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "TO_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "HANDOFF_KIND VARCHAR(32) NOT NULL CHECK(HANDOFF_KIND IN ('HUMAN_TO_AGENT','AGENT_TO_AGENT','AGENT_TO_HUMAN','WORKER_REPLACEMENT')), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('DRAFT','OFFERED','ACKNOWLEDGED','IN_PROGRESS','COMPLETED','REJECTED','EXPIRED')), "
        "VERSION INTEGER NOT NULL CHECK(VERSION>0), CURRENT_REVISION_NO INTEGER NOT NULL CHECK(CURRENT_REVISION_NO>0), "
        "WORK_REVISION_NO INTEGER NOT NULL, EXPIRES_AT TIMESTAMP NOT NULL, ACTIVE_WORK_ID VARCHAR(128) UNIQUE, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "FOREIGN KEY(WORK_CONTRACT_ID,WORK_REVISION_NO) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO), "
        "CHECK ((STATUS IN ('DRAFT','OFFERED','ACKNOWLEDGED','IN_PROGRESS') AND ACTIVE_WORK_ID IS NOT NULL AND ACTIVE_WORK_ID=WORK_CONTRACT_ID) "
        "OR (STATUS IN ('COMPLETED','REJECTED','EXPIRED') AND ACTIVE_WORK_ID IS NULL)))",
        "CREATE TABLE CX_HANDOFF_REVISIONS (HANDOFF_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFFS(HANDOFF_ID), "
        f"REVISION_NO INTEGER NOT NULL CHECK(REVISION_NO>0), SUMMARY {text} NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "WORK_CONTRACT_ID VARCHAR(128) NOT NULL, WORK_REVISION_NO INTEGER NOT NULL, "
        f"CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), REASON {text} NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, PRIMARY KEY(HANDOFF_ID,REVISION_NO), "
        "FOREIGN KEY(WORK_CONTRACT_ID,WORK_REVISION_NO) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_SECTIONS (HANDOFF_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        "SECTION_KIND VARCHAR(24) NOT NULL CHECK(SECTION_KIND IN ('DECISION','CONSTRAINT','QUESTION','RISK')), "
        f"ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), CONTENT_TEXT {text} NOT NULL, "
        "PRIMARY KEY(HANDOFF_ID,REVISION_NO,SECTION_KIND,ITEM_NO), "
        "FOREIGN KEY(HANDOFF_ID,REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_ACTIONS (HANDOFF_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, ACTION_ID VARCHAR(128) NOT NULL, "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), RESPONSIBLE_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        f"DESCRIPTION {text} NOT NULL, ACCEPTANCE {text} NOT NULL, PRIMARY KEY(HANDOFF_ID,REVISION_NO,ACTION_ID), "
        "UNIQUE(HANDOFF_ID,REVISION_NO,ITEM_NO), FOREIGN KEY(HANDOFF_ID,REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_PREREQUISITES (HANDOFF_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, ACTION_ID VARCHAR(128) NOT NULL, "
        f"ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), CONTENT_TEXT {text} NOT NULL, PRIMARY KEY(HANDOFF_ID,REVISION_NO,ACTION_ID,ITEM_NO), "
        "FOREIGN KEY(HANDOFF_ID,REVISION_NO,ACTION_ID) REFERENCES CX_HANDOFF_ACTIONS(HANDOFF_ID,REVISION_NO,ACTION_ID))",
        "CREATE TABLE CX_HANDOFF_ASSIGNMENTS (HANDOFF_ID VARCHAR(128) PRIMARY KEY REFERENCES CX_HANDOFFS(HANDOFF_ID), "
        "RECIPIENT_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('OFFERED','ACKNOWLEDGED','IN_PROGRESS','COMPLETED','REJECTED','EXPIRED')), "
        "OFFERED_REVISION_NO INTEGER NOT NULL, ACK_REVISION_NO INTEGER, ACK_AT TIMESTAMP, "
        "FOREIGN KEY(HANDOFF_ID,OFFERED_REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO), "
        "FOREIGN KEY(HANDOFF_ID,ACK_REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_OUTCOMES (OUTCOME_ID VARCHAR(128) PRIMARY KEY, HANDOFF_ID VARCHAR(128) NOT NULL UNIQUE, "
        "REVISION_NO INTEGER NOT NULL, SUBMITTED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        f"RESULT VARCHAR(24) NOT NULL CHECK(RESULT IN ('COMPLETED','BLOCKED','FAILED')), SUMMARY {text} NOT NULL, REASON {text} NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, FOREIGN KEY(HANDOFF_ID,REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_OUTCOME_CRITERIA (OUTCOME_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFF_OUTCOMES(OUTCOME_ID), "
        "WORK_CONTRACT_ID VARCHAR(128) NOT NULL, WORK_REVISION_NO INTEGER NOT NULL, CRITERION_ID VARCHAR(128) NOT NULL, "
        "PRIMARY KEY(OUTCOME_ID,CRITERION_ID), "
        "FOREIGN KEY(WORK_CONTRACT_ID,WORK_REVISION_NO,CRITERION_ID) REFERENCES CX_WORK_CRITERIA(WORK_CONTRACT_ID,REVISION_NO,CRITERION_ID))",
        "CREATE TABLE CX_HANDOFF_OUTCOME_EVIDENCE (OUTCOME_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFF_OUTCOMES(OUTCOME_ID), "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), FAMILY VARCHAR(24) NOT NULL, ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, PUBLICATION_ID VARCHAR(128), "
        "PRIMARY KEY(OUTCOME_ID,ITEM_NO), UNIQUE(OUTCOME_ID,FAMILY,ENTITY_ID,SOURCE_REVISION_ID))",
        "CREATE TABLE CX_HANDOFF_REQUESTS (ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "OPERATION VARCHAR(64) NOT NULL, IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "HANDOFF_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFFS(HANDOFF_ID), RESOURCE_VERSION INTEGER NOT NULL CHECK(RESOURCE_VERSION>0), "
        "PRIMARY KEY(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY))",
    ]


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    # These new entity columns store UTC-naive values, never legacy local time.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _lock_work(tx, actor, work_id, write=True):
    work._lock_actor(tx,actor)
    row = tx.query_one("SELECT WORK_CONTRACT_ID,SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,VERSION,STATUS FROM CX_WORK_CONTRACTS "
                       "WHERE WORK_CONTRACT_ID=:work_id"+(' FOR UPDATE' if write else ''), {'work_id':work_id})
    if not row:
        raise PermissionError('Handoff access denied')
    work._authorize(tx, actor, row['security_domain_id'], write=write)
    from .continuity_execution_links import read
    read(tx,actor,row['security_domain_id'],work_id)
    return row


def _lock_handoff(tx, actor, handoff_id, *, write=True):
    location = tx.query_one("SELECT WORK_CONTRACT_ID FROM CX_HANDOFFS WHERE HANDOFF_ID=:handoff_id", {'handoff_id':handoff_id})
    if not location:
        raise PermissionError('Handoff access denied')
    root = _lock_work(tx, actor, location['work_contract_id'], write=write)
    row = tx.query_one("SELECT HANDOFF_ID,WORK_CONTRACT_ID,FROM_PRINCIPAL_ID,TO_PRINCIPAL_ID,STATUS,VERSION,CURRENT_REVISION_NO,"
                       "WORK_REVISION_NO,EXPIRES_AT FROM CX_HANDOFFS WHERE HANDOFF_ID=:handoff_id"+(' FOR UPDATE' if write else ''), {'handoff_id':handoff_id})
    if actor not in {row['from_principal_id'],row['to_principal_id']}:
        raise PermissionError('Handoff access denied')
    return root, row


def _receipt(tx, actor, operation, request, *, handoff_id=None, work_id=None):
    row = tx.query_one("SELECT r.REQUEST_DIGEST,r.HANDOFF_ID,r.RESOURCE_VERSION,h.WORK_CONTRACT_ID FROM CX_HANDOFF_REQUESTS r "
                       "JOIN CX_HANDOFFS h ON h.HANDOFF_ID=r.HANDOFF_ID WHERE r.ACTOR_ID=:actor AND r.OPERATION=:operation "
                       "AND r.IDEMPOTENCY_KEY=:idem_key", {'actor':actor,'operation':operation,'idem_key':request.idempotency_key})
    if not row:
        return None
    require_idempotent_request(row['request_digest'], request_digest(actor, operation, request))
    if (handoff_id and handoff_id!=row['handoff_id']) or (work_id and work_id!=row['work_contract_id']):
        raise ContinuityConflict('IDEMPOTENCY_CONFLICT','The request key belongs to another resource')
    return {'handoff_id':row['handoff_id'],'version':int(row['resource_version']),'replayed':True}


def _record(tx, actor, operation, request, handoff_id, version):
    from .continuity_bindings import record_transport
    record_transport(tx,actor,handoff_id,operation,version)
    tx.execute("INSERT INTO CX_HANDOFF_REQUESTS(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY,REQUEST_DIGEST,HANDOFF_ID,RESOURCE_VERSION) "
               "VALUES(:actor,:operation,:idem_key,:digest,:handoff_id,:version)",
               {'actor':actor,'operation':operation,'idem_key':request.idempotency_key,
                'digest':request_digest(actor,operation,request),'handoff_id':handoff_id,'version':version})
    identity_api._audit_tx(tx, actor, operation, 'HANDOFF', handoff_id, 'ALLOW', request.reason)
    return {'handoff_id':handoff_id,'version':version,'replayed':False}


def _member(tx, principal, domain):
    row = tx.query_one("SELECT p.PRINCIPAL_TYPE FROM CX_PRINCIPALS p JOIN CX_DOMAIN_MEMBERS m ON m.PRINCIPAL_ID=p.PRINCIPAL_ID "
                       "WHERE p.PRINCIPAL_ID=:principal AND p.STATUS='ACTIVE' AND m.SECURITY_DOMAIN_ID=:domain "
                       "AND m.STATUS='ACTIVE' AND m.MEMBERSHIP_TIER IN ('OWNER','ADMIN','MEMBER') "
                       "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)", {'principal':principal,'domain':domain})
    if not row:
        raise PermissionError('Handoff participant is unavailable')
    return row['principal_type']


def _write_content(tx, actor, handoff_id, revision, content, reason, domain, work_id, work_revision):
    from .continuity_sources import resolve
    evidence=[]
    seen=set()
    for source in content.evidence:
        key=(source.family.value,source.entity_id,source.revision_id)
        if key in seen:
            raise ContinuityError('DUPLICATE_SOURCE','Handoff evidence must reference unique exact versions')
        seen.add(key)
        if source.family.value=='HANDOFF' and source.entity_id==handoff_id:
            raise ContinuityError('CYCLIC_SOURCE','A handoff cannot cite itself')
        evidence.append((source,resolve(tx,actor,domain,source,purpose='HANDOFF_CONTEXT')))
    tx.execute("INSERT INTO CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO,SUMMARY,CONTENT_DIGEST,CREATED_BY,REASON,WORK_CONTRACT_ID,WORK_REVISION_NO) "
               "VALUES(:handoff_id,:revision,:summary,:digest,:actor,:reason,:work_id,:work_revision)",
               {'handoff_id':handoff_id,'revision':revision,'summary':content.summary,'digest':content_digest(content),'actor':actor,'reason':reason,
                'work_id':work_id,'work_revision':work_revision})
    for item_no,(source,resolved) in enumerate(evidence,1):
        tx.execute("INSERT INTO CX_HANDOFF_EVIDENCE(HANDOFF_ID,REVISION_NO,ITEM_NO,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,PUBLICATION_ID) "
                   "VALUES(:handoff_id,:revision,:item_no,:family,:entity,:source_revision,:digest,:publication)",
                   {'handoff_id':handoff_id,'revision':revision,'item_no':item_no,'family':source.family.value,
                    'entity':source.entity_id,'source_revision':source.revision_id,'digest':source.content_digest,
                    'publication':resolved.get('publication_id')})
    for kind, field in SECTION_FIELDS.items():
        for item_no, text in enumerate(getattr(content,field),1):
            tx.execute("INSERT INTO CX_HANDOFF_SECTIONS(HANDOFF_ID,REVISION_NO,SECTION_KIND,ITEM_NO,CONTENT_TEXT) "
                       "VALUES(:handoff_id,:revision,:kind,:item_no,:body)",
                       {'handoff_id':handoff_id,'revision':revision,'kind':kind,'item_no':item_no,'body':text})
    for item_no, action in enumerate(content.next_actions,1):
        _member(tx,action.responsible_principal_id,domain)
        tx.execute("INSERT INTO CX_HANDOFF_ACTIONS(HANDOFF_ID,REVISION_NO,ACTION_ID,ITEM_NO,RESPONSIBLE_PRINCIPAL_ID,DESCRIPTION,ACCEPTANCE) "
                   "VALUES(:handoff_id,:revision,:action_id,:item_no,:principal,:body,:acceptance)",
                   {'handoff_id':handoff_id,'revision':revision,'action_id':action.action_id,'item_no':item_no,
                    'principal':action.responsible_principal_id,'body':action.description,'acceptance':action.acceptance})
        for prerequisite_no, text in enumerate(action.prerequisites,1):
            tx.execute("INSERT INTO CX_HANDOFF_PREREQUISITES(HANDOFF_ID,REVISION_NO,ACTION_ID,ITEM_NO,CONTENT_TEXT) "
                       "VALUES(:handoff_id,:revision,:action_id,:item_no,:body)",
                       {'handoff_id':handoff_id,'revision':revision,'action_id':action.action_id,'item_no':prerequisite_no,'body':text})


def _expire_active(tx,work_id):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    tx.execute("UPDATE CX_HANDOFF_ASSIGNMENTS SET STATUS='EXPIRED' WHERE HANDOFF_ID IN "
               "(SELECT HANDOFF_ID FROM CX_HANDOFFS WHERE WORK_CONTRACT_ID=:work_id AND ACTIVE_WORK_ID IS NOT NULL AND EXPIRES_AT<=:now)",
               {'work_id':work_id,'now':now})
    tx.execute("UPDATE CX_HANDOFFS SET STATUS='EXPIRED',ACTIVE_WORK_ID=NULL,VERSION=VERSION+1 "
               "WHERE WORK_CONTRACT_ID=:work_id AND ACTIVE_WORK_ID IS NOT NULL AND EXPIRES_AT<=:now",{'work_id':work_id,'now':now})


def offer(actor, work_id, value):
    request = value if isinstance(value,NewHandoff) else NewHandoff.model_validate(value)
    def perform(tx):
        root = _lock_work(tx,actor,work_id)
        prior = _receipt(tx,actor,'HANDOFF_OFFER',request,work_id=work_id)
        if prior:
            return prior
        require_version(int(root['version']),request.expected_work_version)
        if root['owner_principal_id']!=actor or root['status'] not in {'OPEN','IN_PROGRESS','BLOCKED'}:
            raise PermissionError('Only the current owner can offer active work')
        sender_type = _member(tx,actor,root['security_domain_id'])
        recipient_type = _member(tx,request.recipient_principal_id,root['security_domain_id'])
        expected_kind = sender_type+'_TO_'+recipient_type
        if request.kind == 'WORKER_REPLACEMENT':
            if sender_type!='AGENT' or request.recipient_principal_id!=actor:
                raise ContinuityError('INVALID_KIND','Worker replacement must preserve the Agent principal')
        elif request.kind!=expected_kind or request.recipient_principal_id==actor:
            raise ContinuityError('INVALID_KIND','Handoff kind does not match independent participant types')
        now = datetime.now(timezone.utc)
        require_not_expired(request.expires_at,now)
        # Reclaim only expired handoffs of this locked work root.
        _expire_active(tx,work_id)
        from .continuity_policy import read as read_policy
        policy=read_policy(tx,work_id,request.expected_work_version)
        active=tx.query('SELECT TO_PRINCIPAL_ID FROM CX_HANDOFFS WHERE ACTIVE_WORK_ID=:work_id',{'work_id':work_id})
        if len(active)>=policy['max_active_recipients'] or any(item['to_principal_id']==request.recipient_principal_id for item in active):
            raise ContinuityConflict('ACTIVE_RECIPIENT','The handoff limit or recipient assignment is already active')
        handoff_id = work._id('HO')
        tx.execute("INSERT INTO CX_HANDOFFS(HANDOFF_ID,WORK_CONTRACT_ID,FROM_PRINCIPAL_ID,TO_PRINCIPAL_ID,HANDOFF_KIND,STATUS,VERSION,"
                   "CURRENT_REVISION_NO,WORK_REVISION_NO,EXPIRES_AT,ACTIVE_WORK_ID) VALUES(:handoff_id,:work_id,:actor,:recipient,:kind,'OFFERED',1,1,:work_version,:expires,:work_id)",
                   {'handoff_id':handoff_id,'work_id':work_id,'actor':actor,'recipient':request.recipient_principal_id,'kind':request.kind,
                    'work_version':request.expected_work_version,'expires':request.expires_at.replace(tzinfo=None)})
        _write_content(tx,actor,handoff_id,1,request.content,request.reason,root['security_domain_id'],work_id,request.expected_work_version)
        from .continuity_bindings import bind_instances
        bind_instances(tx,actor,handoff_id,root['security_domain_id'],request)
        tx.execute("INSERT INTO CX_HANDOFF_ASSIGNMENTS(HANDOFF_ID,RECIPIENT_ID,STATUS,OFFERED_REVISION_NO) VALUES(:handoff_id,:recipient,'OFFERED',1)",
                   {'handoff_id':handoff_id,'recipient':request.recipient_principal_id})
        return _record(tx,actor,'HANDOFF_OFFER',request,handoff_id,1)
    return connection.execute_transaction_callback(perform)


def decide(actor,handoff_id,value):
    request = value if isinstance(value,HandoffDecision) else HandoffDecision.model_validate(value)
    def perform(tx):
        root,row = _lock_handoff(tx,actor,handoff_id)
        if row['to_principal_id']!=actor:
            raise PermissionError('Only the recipient can decide this handoff')
        prior = _receipt(tx,actor,'HANDOFF_DECIDE',request,handoff_id=handoff_id)
        if prior:
            return prior
        require_version(int(row['version']),request.expected_version)
        require_version(int(row['current_revision_no']),request.expected_revision_no)
        require_not_expired(_utc(row['expires_at']),datetime.now(timezone.utc))
        if request.decision!='REJECTED':
            _handoff_payload(tx,row,request.expected_revision_no,actor=actor,domain=root['security_domain_id'])
            from .continuity_bindings import recipient_current
            if not recipient_current(tx,handoff_id,root['security_domain_id']):
                raise ContinuityConflict('INSTANCE_CHANGED','The bound recipient instance is no longer current')
        require_transition('HANDOFF',row['status'],request.decision)
        if request.decision!='REJECTED' and root['status'] in {'COMPLETED','CANCELLED','EXPIRED'}:
            raise ContinuityConflict('TERMINAL_WORK','Closed work cannot be executed')
        if request.decision=='ACKNOWLEDGED':
            acknowledge_handoff(actor=actor,recipient=row['to_principal_id'],status=row['status'],version=int(row['version']),
                expected_version=request.expected_version,revision_no=int(row['current_revision_no']),expected_revision_no=request.expected_revision_no,
                expires_at=_utc(row['expires_at']),now=datetime.now(timezone.utc))
            if root['owner_principal_id']!=row['from_principal_id']:
                raise ContinuityConflict('OWNER_CHANGED','The work owner changed before acknowledgement')
            require_version(int(root['version']),int(row['work_revision_no']))
            from .continuity_policy import read as read_policy
            if read_policy(tx,row['work_contract_id'],int(row['work_revision_no']))['max_active_recipients']==1:
                current = work._read_work(tx,actor,row['work_contract_id'],int(row['work_revision_no']))
                work._content(tx,row['work_contract_id'],int(root['version'])+1,
                              WorkContent.model_validate(current['content']),actor,request.reason,owner=actor)
                tx.execute("UPDATE CX_WORK_CONTRACTS SET OWNER_PRINCIPAL_ID=:actor,VERSION=VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP "
                           "WHERE WORK_CONTRACT_ID=:work_id",{'actor':actor,'work_id':row['work_contract_id']})
        params={'handoff_id':handoff_id,'status':request.decision,'version':request.expected_version+1,
                'active_work':row['work_contract_id'] if request.decision in ACTIVE else None}
        tx.execute("UPDATE CX_HANDOFFS SET STATUS=:status,VERSION=:version,ACTIVE_WORK_ID=:active_work WHERE HANDOFF_ID=:handoff_id",params)
        tx.execute("UPDATE CX_HANDOFF_ASSIGNMENTS SET STATUS=:status WHERE HANDOFF_ID=:handoff_id",
                   {'status':request.decision,'handoff_id':handoff_id})
        if request.decision=='ACKNOWLEDGED':
            tx.execute("UPDATE CX_HANDOFF_ASSIGNMENTS SET ACK_REVISION_NO=:revision,ACK_AT=:now WHERE HANDOFF_ID=:handoff_id",
                       {'revision':request.expected_revision_no,'now':datetime.now(timezone.utc).replace(tzinfo=None),'handoff_id':handoff_id})
        return _record(tx,actor,'HANDOFF_DECIDE',request,handoff_id,params['version'])
    return connection.execute_transaction_callback(perform)


def revise_handoff(actor,handoff_id,value):
    request = value if isinstance(value,HandoffRevision) else HandoffRevision.model_validate(value)
    def perform(tx):
        root,row = _lock_handoff(tx,actor,handoff_id)
        if row['from_principal_id']!=actor:
            raise PermissionError('Only the sender can revise the offer')
        prior = _receipt(tx,actor,'HANDOFF_REVISE',request,handoff_id=handoff_id)
        if prior:
            return prior
        if row['status']!='OFFERED' or root['owner_principal_id']!=actor:
            raise ContinuityConflict('OFFER_CLOSED','Only an unaccepted offer may be revised')
        if root['status'] in {'COMPLETED','CANCELLED','EXPIRED'}:
            raise ContinuityConflict('TERMINAL_WORK','Closed work cannot be offered')
        require_version(int(row['version']),request.expected_version)
        require_version(int(row['current_revision_no']),request.expected_revision_no)
        require_version(int(root['version']),request.expected_work_version)
        require_not_expired(_utc(row['expires_at']),datetime.now(timezone.utc))
        revision=request.expected_revision_no+1
        _write_content(tx,actor,handoff_id,revision,request.content,request.reason,root['security_domain_id'],row['work_contract_id'],request.expected_work_version)
        tx.execute("UPDATE CX_HANDOFFS SET CURRENT_REVISION_NO=:revision,WORK_REVISION_NO=:work_revision,VERSION=VERSION+1 "
                   "WHERE HANDOFF_ID=:handoff_id",{'revision':revision,'work_revision':request.expected_work_version,'handoff_id':handoff_id})
        tx.execute("UPDATE CX_HANDOFF_ASSIGNMENTS SET OFFERED_REVISION_NO=:revision WHERE HANDOFF_ID=:handoff_id",
                   {'revision':revision,'handoff_id':handoff_id})
        return _record(tx,actor,'HANDOFF_REVISE',request,handoff_id,request.expected_version+1)
    return connection.execute_transaction_callback(perform)


def submit_outcome(actor,handoff_id,value):
    request = value if isinstance(value,HandoffOutcome) else HandoffOutcome.model_validate(value)
    def perform(tx):
        root,row = _lock_handoff(tx,actor,handoff_id)
        if row['to_principal_id']!=actor:
            raise PermissionError('Only the recipient can submit the outcome')
        prior = _receipt(tx,actor,'HANDOFF_OUTCOME',request,handoff_id=handoff_id)
        if prior:
            return prior
        require_version(int(row['version']),request.expected_version)
        require_version(int(row['current_revision_no']),request.expected_revision_no)
        require_not_expired(_utc(row['expires_at']),datetime.now(timezone.utc))
        if row['status'] not in {'ACKNOWLEDGED','IN_PROGRESS'}:
            raise ContinuityConflict('NOT_ACCEPTED','An outcome requires an accepted handoff')
        from .continuity_bindings import recipient_current
        if not recipient_current(tx,handoff_id,root['security_domain_id']):
            raise ContinuityConflict('INSTANCE_CHANGED','The bound recipient instance is no longer current')
        _handoff_payload(tx,row,request.expected_revision_no,actor=actor,domain=root['security_domain_id'])
        from .continuity_policy import read as read_policy
        policy=read_policy(tx,row['work_contract_id'],int(row['work_revision_no']))
        expected_owner=actor if policy['max_active_recipients']==1 else row['from_principal_id']
        if root['owner_principal_id']!=expected_owner:
            raise ContinuityConflict('OWNER_CHANGED','The work owner changed before outcome submission')
        target = 'COMPLETED' if request.result=='COMPLETED' else 'REJECTED'
        require_transition('HANDOFF',row['status'],target)
        from .continuity_sources import resolve
        evidence=[]
        seen=set()
        for source in request.evidence:
            key=(source.family,source.entity_id,source.revision_id)
            if key in seen:
                raise ContinuityError('DUPLICATE_SOURCE','Outcome evidence must reference unique exact versions')
            seen.add(key)
            evidence.append((source,resolve(tx,actor,root['security_domain_id'],source,purpose='HANDOFF_OUTCOME')))
        criteria = {item['criterion_id'] for item in tx.query("SELECT CRITERION_ID FROM CX_WORK_CRITERIA "
                    "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision",{'work_id':row['work_contract_id'],'revision':row['work_revision_no']})}
        reported = set(request.satisfied_criteria)
        if len(reported)!=len(request.satisfied_criteria) or not reported.issubset(criteria):
            raise ContinuityError('INVALID_CRITERIA','Outcome criteria do not match the offered work revision')
        if request.result=='COMPLETED' and reported!=criteria:
            raise ContinuityConflict('UNMET_CRITERIA','Completion must account for every offered acceptance criterion')
        outcome_id = work._id('OUT')
        tx.execute("INSERT INTO CX_HANDOFF_OUTCOMES(OUTCOME_ID,HANDOFF_ID,REVISION_NO,SUBMITTED_BY,RESULT,SUMMARY,REASON) "
                   "VALUES(:outcome_id,:handoff_id,:revision,:actor,:result,:summary,:reason)",
                   {'outcome_id':outcome_id,'handoff_id':handoff_id,'revision':request.expected_revision_no,'actor':actor,
                    'result':request.result,'summary':request.summary,'reason':request.reason})
        for criterion in request.satisfied_criteria:
            tx.execute("INSERT INTO CX_HANDOFF_OUTCOME_CRITERIA(OUTCOME_ID,WORK_CONTRACT_ID,WORK_REVISION_NO,CRITERION_ID) "
                       "VALUES(:outcome_id,:work_id,:revision,:criterion)",
                       {'outcome_id':outcome_id,'work_id':row['work_contract_id'],'revision':row['work_revision_no'],'criterion':criterion})
        for index,(source,resolved) in enumerate(evidence,1):
            tx.execute("INSERT INTO CX_HANDOFF_OUTCOME_EVIDENCE(OUTCOME_ID,ITEM_NO,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,PUBLICATION_ID) "
                       "VALUES(:outcome_id,:item_no,:family,:entity,:revision,:digest,:publication)",
                       {'outcome_id':outcome_id,'item_no':index,'family':source.family.value,'entity':source.entity_id,
                        'revision':source.revision_id,'digest':source.content_digest,'publication':resolved.get('publication_id')})
        tx.execute("UPDATE CX_HANDOFFS SET STATUS=:status,VERSION=VERSION+1,ACTIVE_WORK_ID=NULL WHERE HANDOFF_ID=:handoff_id",{'status':target,'handoff_id':handoff_id})
        tx.execute("UPDATE CX_HANDOFF_ASSIGNMENTS SET STATUS=:status WHERE HANDOFF_ID=:handoff_id",{'status':target,'handoff_id':handoff_id})
        return _record(tx,actor,'HANDOFF_OUTCOME',request,handoff_id,request.expected_version+1)
    return connection.execute_transaction_callback(perform)


def read_outcome(actor,handoff_id):
    """Participant access plus current independent authority over each evidence item."""
    return connection.execute_transaction_callback(lambda tx:_read_outcome(tx,actor,handoff_id))


def _read_outcome(tx,actor,handoff_id):
        from .continuity_sources import resolve
        root,handoff=_lock_handoff(tx,actor,handoff_id,write=False)
        row=tx.query_one("SELECT OUTCOME_ID,REVISION_NO,SUBMITTED_BY,RESULT,SUMMARY,CREATED_AT FROM CX_HANDOFF_OUTCOMES WHERE HANDOFF_ID=:handoff_id",
                         {'handoff_id':handoff_id})
        if not row:
            raise ContinuityError('OUTCOME_UNAVAILABLE','No outcome has been recorded')
        items=tx.query("SELECT FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,PUBLICATION_ID FROM CX_HANDOFF_OUTCOME_EVIDENCE "
                       "WHERE OUTCOME_ID=:outcome_id ORDER BY ITEM_NO",{'outcome_id':row['outcome_id']})
        evidence=[]
        for item in items:
            source=dict(family=item['family'],entity_id=item['entity_id'],revision_id=item['source_revision_id'],content_digest=item['content_digest'])
            resolve(tx,actor,root['security_domain_id'],source,purpose='HANDOFF_OUTCOME',publication_id=item['publication_id'])
            evidence.append(source)
        criteria=tx.query("SELECT CRITERION_ID FROM CX_HANDOFF_OUTCOME_CRITERIA WHERE OUTCOME_ID=:outcome_id ORDER BY CRITERION_ID",{'outcome_id':row['outcome_id']})
        summary=row['summary'].read() if hasattr(row['summary'],'read') else row['summary']
        payload=dict(outcome_id=row['outcome_id'],revision_no=int(row['revision_no']),submitted_by=row['submitted_by'],
                     result=row['result'],summary=summary,handoff_id=handoff_id,evidence=evidence,
                     satisfied_criteria=[item['criterion_id'] for item in criteria])
        from .continuity_contracts import content_digest,OutcomeContent
        return dict(payload,created_at=row['created_at'],content_digest=content_digest(OutcomeContent.model_validate(payload)))


def _read_handoff(tx,actor,handoff_id,revision=None):
        root,row = _lock_handoff(tx,actor,handoff_id,write=False)
        return _handoff_payload(tx,row,revision,actor=actor,domain=root['security_domain_id'])


def _handoff_payload(tx,row,revision=None,*,actor,domain):
        """Reconstruct only after caller checked participant or publication authority."""
        handoff_id=row['handoff_id']
        expired = _utc(row['expires_at']) <= datetime.now(timezone.utc)
        if expired:
            # Current authorization still applies; expired text is not usable as
            # execution context. Preserve minimal audit metadata for participants.
            return {'handoff_id':handoff_id,'work_contract_id':row['work_contract_id'],
                    'version':int(row['version']),'revision_no':int(row['current_revision_no']),
                    'status':row['status'],'expired':True,'executable':False}
        selected=int(row['current_revision_no']) if revision is None else revision
        require_version(selected,selected)
        params={'handoff_id':handoff_id,'revision':selected}
        record=tx.query_one("SELECT SUMMARY,CONTENT_DIGEST,WORK_CONTRACT_ID,WORK_REVISION_NO FROM CX_HANDOFF_REVISIONS WHERE HANDOFF_ID=:handoff_id AND REVISION_NO=:revision",params)
        if not record:
            raise ContinuityConflict('REVISION_UNAVAILABLE','The requested revision is unavailable')
        def text(value):
            return value.read() if hasattr(value,'read') else value
        content={'summary':text(record['summary']),'next_actions':[]}
        for kind,field in SECTION_FIELDS.items():
            content[field]=[text(item['content_text']) for item in tx.query("SELECT CONTENT_TEXT FROM CX_HANDOFF_SECTIONS "
                "WHERE HANDOFF_ID=:handoff_id AND REVISION_NO=:revision AND SECTION_KIND=:kind ORDER BY ITEM_NO",dict(params,kind=kind))]
        for item in tx.query("SELECT ACTION_ID,RESPONSIBLE_PRINCIPAL_ID,DESCRIPTION,ACCEPTANCE FROM CX_HANDOFF_ACTIONS "
                             "WHERE HANDOFF_ID=:handoff_id AND REVISION_NO=:revision ORDER BY ITEM_NO",params):
            item={key:text(value) for key,value in item.items()}
            item['prerequisites']=[text(p['content_text']) for p in tx.query("SELECT CONTENT_TEXT FROM CX_HANDOFF_PREREQUISITES "
                "WHERE HANDOFF_ID=:handoff_id AND REVISION_NO=:revision AND ACTION_ID=:action_id ORDER BY ITEM_NO",dict(params,action_id=item['action_id']))]
            content['next_actions'].append(item)
        from .continuity_sources import resolve
        content['evidence']=[]
        for item in tx.query("SELECT FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,PUBLICATION_ID FROM CX_HANDOFF_EVIDENCE "
                             "WHERE HANDOFF_ID=:handoff_id AND REVISION_NO=:revision ORDER BY ITEM_NO",params):
            source=dict(family=item['family'],entity_id=item['entity_id'],revision_id=item['source_revision_id'],content_digest=item['content_digest'])
            resolve(tx,actor,domain,source,purpose='HANDOFF_CONTEXT',publication_id=item['publication_id'])
            content['evidence'].append(source)
        validated=HandoffContent.model_validate(content)
        if content_digest(validated)!=record['content_digest']:
            raise ContinuityError('INTEGRITY_ERROR','Stored handoff revision failed integrity validation')
        if record['work_contract_id']!=row['work_contract_id']:
            raise ContinuityError('INTEGRITY_ERROR','Stored handoff revision has an invalid work binding')
        from .continuity_bindings import recipient_current
        current_instance=recipient_current(tx,handoff_id,domain)
        instance_bindings=tx.query("SELECT PARTICIPANT_SIDE,PRINCIPAL_ID,INSTANCE_ID,FENCING_TOKEN FROM CX_HANDOFF_INSTANCE_BINDINGS "
                                   "WHERE HANDOFF_ID=:handoff ORDER BY PARTICIPANT_SIDE",{'handoff':handoff_id})
        return {'handoff_id':handoff_id,'work_contract_id':row['work_contract_id'],'version':int(row['version']),
                'from_principal_id':row['from_principal_id'],'to_principal_id':row['to_principal_id'],
                'work_revision_no':int(record['work_revision_no']),
                'revision_no':selected,'status':row['status'],'expired':False,
                'executable':row['status'] in ACTIVE and selected==int(row['current_revision_no']) and current_instance,
                'instance_bindings':instance_bindings,
                'content':validated.model_dump(mode='json'),'content_digest':record['content_digest']}


def read_handoff(actor,handoff_id,revision=None):
    return connection.execute_transaction_callback(lambda tx: _read_handoff(tx,actor,handoff_id,revision))


def history(actor,handoff_id):
    def perform(tx):
        root,row=_lock_handoff(tx,actor,handoff_id,write=False)
        revisions=tx.query("SELECT REVISION_NO,WORK_REVISION_NO,CONTENT_DIGEST,CREATED_BY,CREATED_AT "
                           "FROM CX_HANDOFF_REVISIONS WHERE HANDOFF_ID=:handoff_id ORDER BY REVISION_NO",
                           {'handoff_id':handoff_id})
        return {'handoff_id':handoff_id,'work_contract_id':row['work_contract_id'],'version':int(row['version']),
                'status':row['status'],'expired':handoff_expired(row),'revisions':revisions}
    return connection.execute_transaction_callback(perform)


def handoff_expired(row):
    return _utc(row['expires_at'])<=datetime.now(timezone.utc)
