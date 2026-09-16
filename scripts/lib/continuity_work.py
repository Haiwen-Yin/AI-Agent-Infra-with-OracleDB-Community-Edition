"""Database-backed work contracts with immutable, normalized content revisions.

The runtime migration and public entrypoints are integrated separately. Every
operation here uses the existing Principal/domain authority and one adapter
transaction. No source reference grants read permission.
"""
import secrets

from . import connection, identity_api
from .continuity_contracts import NewWork, WorkRevision, WorkStateChange, WorkContent, content_digest, request_digest
from .continuity_state import ContinuityError, ContinuityConflict, require_version, require_idempotent_request, require_transition


def _id(prefix):
    return prefix + '_' + secrets.token_hex(20)


def schema_statements(dialect):
    """Work-contract foundation DDL; does not run implicitly during requests."""
    if dialect not in {'oracle', 'yashandb', 'pg', 'postgresql'}:
        raise ValueError('unsupported database adapter')
    body_type = 'TEXT' if dialect in {'pg', 'postgresql'} else 'CLOB'
    return [
        "CREATE TABLE CX_WORK_CONTRACTS (WORK_CONTRACT_ID VARCHAR(128) PRIMARY KEY, "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "OWNER_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "VERSION INTEGER NOT NULL CHECK (VERSION>0), STATUS VARCHAR(24) NOT NULL "
        "CHECK (STATUS IN ('OPEN','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED','EXPIRED')), "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        f"CREATE TABLE CX_WORK_REVISIONS (WORK_CONTRACT_ID VARCHAR(128) NOT NULL REFERENCES CX_WORK_CONTRACTS(WORK_CONTRACT_ID), "
        f"REVISION_NO INTEGER NOT NULL CHECK (REVISION_NO>0), OBJECTIVE {body_type} NOT NULL, "
        "CONTENT_DIGEST VARCHAR(64) NOT NULL, CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        f"REASON {body_type} NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "PRIMARY KEY (WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_WORK_REVISION_STATES (WORK_CONTRACT_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        "OWNER_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), STATUS VARCHAR(24) NOT NULL "
        "CHECK (STATUS IN ('OPEN','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED','EXPIRED')), "
        "PRIMARY KEY (WORK_CONTRACT_ID,REVISION_NO), FOREIGN KEY (WORK_CONTRACT_ID,REVISION_NO) "
        "REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_WORK_CRITERIA (WORK_CONTRACT_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        f"CRITERION_ID VARCHAR(128) NOT NULL, ITEM_NO INTEGER NOT NULL CHECK (ITEM_NO>0), DESCRIPTION {body_type} NOT NULL, VERIFICATION {body_type} NOT NULL, "
        "PRIMARY KEY (WORK_CONTRACT_ID,REVISION_NO,CRITERION_ID), UNIQUE (WORK_CONTRACT_ID,REVISION_NO,ITEM_NO), "
        "FOREIGN KEY (WORK_CONTRACT_ID,REVISION_NO) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_WORK_SOURCES (WORK_CONTRACT_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), FAMILY VARCHAR(24) NOT NULL, ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "PRIMARY KEY(WORK_CONTRACT_ID,REVISION_NO,ITEM_NO), "
        "FOREIGN KEY(WORK_CONTRACT_ID,REVISION_NO) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_WORK_CONSTRAINTS (WORK_CONTRACT_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        f"ITEM_NO INTEGER NOT NULL CHECK (ITEM_NO>0), CONSTRAINT_TEXT {body_type} NOT NULL, "
        "PRIMARY KEY (WORK_CONTRACT_ID,REVISION_NO,ITEM_NO), "
        "FOREIGN KEY (WORK_CONTRACT_ID,REVISION_NO) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
        "CREATE TABLE CX_WORK_REQUESTS (ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "OPERATION VARCHAR(64) NOT NULL, IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "WORK_CONTRACT_ID VARCHAR(128) NOT NULL, RESOURCE_VERSION INTEGER NOT NULL, "
        "PRIMARY KEY (ACTOR_ID,OPERATION,IDEMPOTENCY_KEY), "
        "FOREIGN KEY (WORK_CONTRACT_ID,RESOURCE_VERSION) REFERENCES CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO))",
    ]


def _lock_actor(tx, actor):
    # Global order: acting Principal, Work root, Handoff root. Reads and writes
    # use the same order, including nested operations within one transaction.
    principal = tx.query_one("SELECT STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor FOR UPDATE", {'actor': actor})
    if not principal or principal['status'] != 'ACTIVE':
        raise PermissionError('Work contract access denied')


def _authorize(tx, actor, domain, *, write):
    # A boundary ID never confers authority, including for an administrator.
    _lock_actor(tx, actor)
    decision = identity_api.effective_access(actor, 'workspaces.write' if write else 'workspaces.read',
                                             resource={'security_domain_id': domain})
    if decision.get('decision') != 'ALLOW':
        raise PermissionError('Work contract access denied')
    boundary = tx.query_one("SELECT STATUS FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID=:domain", {'domain': domain})
    membership = tx.query_one(
        "SELECT MEMBERSHIP_TIER FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain AND PRINCIPAL_ID=:actor "
        "AND STATUS='ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)", {'domain': domain, 'actor': actor})
    if not boundary or boundary['status'] != 'ACTIVE' or not membership:
        raise PermissionError('Work contract access denied')
    if write and membership['membership_tier'] not in {'OWNER', 'ADMIN', 'MEMBER'}:
        raise PermissionError('Work contract access denied')


def _receipt(tx, actor, operation, request):
    stored = tx.query_one("SELECT REQUEST_DIGEST,WORK_CONTRACT_ID,RESOURCE_VERSION FROM CX_WORK_REQUESTS "
                          "WHERE ACTOR_ID=:actor AND OPERATION=:operation AND IDEMPOTENCY_KEY=:idem_key",
                          {'actor': actor, 'operation': operation, 'idem_key': request.idempotency_key})
    if stored:
        require_idempotent_request(stored['request_digest'], request_digest(actor, operation, request))
        return {'work_contract_id': stored['work_contract_id'], 'version': int(stored['resource_version']), 'replayed': True}
    return None


def _record(tx, actor, operation, request, work_id, version):
    tx.execute("INSERT INTO CX_WORK_REQUESTS(ACTOR_ID,OPERATION,IDEMPOTENCY_KEY,REQUEST_DIGEST,WORK_CONTRACT_ID,RESOURCE_VERSION) "
               "VALUES(:actor,:operation,:idem_key,:digest,:work_id,:revision)",
               {'actor': actor, 'operation': operation, 'idem_key': request.idempotency_key,
                'digest': request_digest(actor, operation, request), 'work_id': work_id, 'revision': version})
    identity_api._audit_tx(tx, actor, operation, 'WORK_CONTRACT', work_id, 'ALLOW', request.reason)
    return {'work_contract_id': work_id, 'version': version, 'replayed': False}


def _content(tx, work_id, revision, content, actor, reason, *, owner=None, status=None, max_active_recipients=None):
    root = tx.query_one("SELECT OWNER_PRINCIPAL_ID,STATUS,SECURITY_DOMAIN_ID FROM CX_WORK_CONTRACTS WHERE WORK_CONTRACT_ID=:work_id", {'work_id': work_id})
    if content.sources:
        from .continuity_sources import resolve
        for source in content.sources:
            resolve(tx,actor,root['security_domain_id'],source,purpose='WORK_CONTEXT')
    params = {'work_id': work_id, 'revision': revision, 'objective': content.objective,
              'digest': content_digest(content), 'actor': actor, 'reason': reason}
    tx.execute("INSERT INTO CX_WORK_REVISIONS(WORK_CONTRACT_ID,REVISION_NO,OBJECTIVE,CONTENT_DIGEST,CREATED_BY,REASON) "
               "VALUES(:work_id,:revision,:objective,:digest,:actor,:reason)", params)
    tx.execute("INSERT INTO CX_WORK_REVISION_STATES(WORK_CONTRACT_ID,REVISION_NO,OWNER_PRINCIPAL_ID,STATUS) "
               "VALUES(:work_id,:revision,:owner,:status)",
               {'work_id': work_id, 'revision': revision, 'owner': owner or root['owner_principal_id'],
                'status': status or root['status']})
    from .continuity_policy import snapshot
    snapshot(tx,work_id,revision,max_active_recipients)
    for item_no, source in enumerate(content.sources,1):
        tx.execute("INSERT INTO CX_WORK_SOURCES(WORK_CONTRACT_ID,REVISION_NO,ITEM_NO,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST) "
                   "VALUES(:work_id,:revision,:item_no,:family,:entity_id,:source_revision,:digest)",
                   {'work_id':work_id,'revision':revision,'item_no':item_no,'family':source.family.value,
                    'entity_id':source.entity_id,'source_revision':source.revision_id,'digest':source.content_digest})
    for item_no, item in enumerate(content.criteria, 1):
        tx.execute("INSERT INTO CX_WORK_CRITERIA(WORK_CONTRACT_ID,REVISION_NO,CRITERION_ID,ITEM_NO,DESCRIPTION,VERIFICATION) "
                   "VALUES(:work_id,:revision,:criterion,:item_no,:description,:verification)",
                   {'work_id': work_id, 'revision': revision, 'criterion': item.criterion_id, 'item_no': item_no,
                    'description': item.description, 'verification': item.verification})
    for item_no, text in enumerate(content.constraints, 1):
        tx.execute("INSERT INTO CX_WORK_CONSTRAINTS(WORK_CONTRACT_ID,REVISION_NO,ITEM_NO,CONSTRAINT_TEXT) "
                   "VALUES(:work_id,:revision,:item_no,:content)",
                   {'work_id': work_id, 'revision': revision, 'item_no': item_no, 'content': text})


def create_work(actor, value):
    request = value if isinstance(value, NewWork) else NewWork.model_validate(value)
    def create(tx):
        _authorize(tx, actor, request.security_domain_id, write=True)
        if request.owner_principal_id != actor:
            raise PermissionError('Create under the current owner; transfer through a governed handoff')
        receipt = _receipt(tx, actor, 'WORK_CREATE', request)
        if receipt:
            from .continuity_execution_links import read
            read(tx,actor,request.security_domain_id,receipt['work_contract_id'])
            return receipt
        work_id = _id('WC')
        tx.execute("INSERT INTO CX_WORK_CONTRACTS(WORK_CONTRACT_ID,SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,CREATED_BY,VERSION,STATUS) "
                   "VALUES(:work_id,:domain,:actor,:actor,1,'OPEN')",
                   {'work_id': work_id, 'domain': request.security_domain_id, 'actor': actor})
        _content(tx, work_id, 1, request.content, actor, request.reason)
        from .continuity_execution_links import bind
        bind(tx,actor,request.security_domain_id,work_id,request)
        return _record(tx, actor, 'WORK_CREATE', request, work_id, 1)
    return connection.execute_transaction_callback(create)


def revise_work(actor, work_id, value):
    request = value if isinstance(value, WorkRevision) else WorkRevision.model_validate(value)
    def revise(tx):
        _lock_actor(tx, actor)
        work = tx.query_one("SELECT SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,VERSION,STATUS FROM CX_WORK_CONTRACTS "
                            "WHERE WORK_CONTRACT_ID=:work_id FOR UPDATE", {'work_id': work_id})
        if not work:
            raise PermissionError('Work contract access denied')
        _authorize(tx, actor, work['security_domain_id'], write=True)
        from .continuity_execution_links import read
        read(tx,actor,work['security_domain_id'],work_id)
        # A replay must still identify this target, not merely the same actor.
        operation = 'WORK_REVISE'
        receipt = _receipt(tx, actor, operation, request)
        if receipt:
            if receipt['work_contract_id'] != work_id:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT', 'The key belongs to another work contract')
            return receipt
        if work['owner_principal_id'] != actor:
            raise PermissionError('Only the current owner can revise this work contract')
        require_version(int(work['version']), request.expected_version)
        if work['status'] in {'COMPLETED', 'CANCELLED', 'EXPIRED'}:
            raise ContinuityConflict('TERMINAL_WORK', 'A closed work contract cannot be revised')
        revision = request.expected_version + 1
        _content(tx, work_id, revision, request.content, actor, request.reason)
        changed = tx.execute("UPDATE CX_WORK_CONTRACTS SET VERSION=:revision,UPDATED_AT=CURRENT_TIMESTAMP "
                             "WHERE WORK_CONTRACT_ID=:work_id AND VERSION=:expected",
                             {'work_id': work_id, 'revision': revision, 'expected': request.expected_version})
        if changed != 1:
            raise ContinuityConflict('STALE_VERSION', 'The work contract changed')
        return _record(tx, actor, operation, request, work_id, revision)
    return connection.execute_transaction_callback(revise)


def change_work_state(actor, work_id, value):
    request = value if isinstance(value, WorkStateChange) else WorkStateChange.model_validate(value)
    def perform(tx):
        _lock_actor(tx, actor)
        root = tx.query_one("SELECT SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,VERSION,STATUS FROM CX_WORK_CONTRACTS "
                            "WHERE WORK_CONTRACT_ID=:work_id FOR UPDATE", {'work_id':work_id})
        if not root:
            raise PermissionError('Work contract access denied')
        _authorize(tx, actor, root['security_domain_id'], write=True)
        from .continuity_execution_links import read
        read(tx,actor,root['security_domain_id'],work_id)
        receipt = _receipt(tx, actor, 'WORK_STATE', request)
        if receipt:
            if receipt['work_contract_id'] != work_id:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT', 'The key belongs to another work contract')
            return receipt
        if root['owner_principal_id'] != actor:
            raise PermissionError('Only the current owner can change work status')
        require_version(int(root['version']), request.expected_version)
        require_transition('WORK', root['status'], request.status)
        current = _read_work(tx, actor, work_id)
        version = request.expected_version + 1
        _content(tx, work_id, version, WorkContent.model_validate(current['content']), actor, request.reason, status=request.status)
        tx.execute("UPDATE CX_WORK_CONTRACTS SET STATUS=:status,VERSION=:version,UPDATED_AT=CURRENT_TIMESTAMP "
                   "WHERE WORK_CONTRACT_ID=:work_id", {'status':request.status,'version':version,'work_id':work_id})
        return _record(tx, actor, 'WORK_STATE', request, work_id, version)
    return connection.execute_transaction_callback(perform)


def _read_work(tx, actor, work_id, revision=None):
        work = tx.query_one("SELECT WORK_CONTRACT_ID,SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,VERSION,STATUS "
                            "FROM CX_WORK_CONTRACTS WHERE WORK_CONTRACT_ID=:work_id", {'work_id': work_id})
        if not work:
            raise PermissionError('Work contract access denied')
        _authorize(tx, actor, work['security_domain_id'], write=False)
        from .continuity_execution_links import read
        execution_links=read(tx,actor,work['security_domain_id'],work_id)
        selected = int(work['version']) if revision is None else revision
        require_version(selected, selected)
        params = {'work_id': work_id, 'revision': selected}
        record = tx.query_one("SELECT OBJECTIVE,CONTENT_DIGEST,CREATED_BY,REASON FROM CX_WORK_REVISIONS "
                              "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision", params)
        if not record:
            raise ContinuityConflict('REVISION_UNAVAILABLE', 'The requested revision is unavailable')
        criteria = tx.query("SELECT CRITERION_ID,DESCRIPTION,VERIFICATION FROM CX_WORK_CRITERIA "
                            "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision ORDER BY ITEM_NO", params)
        constraints = tx.query("SELECT CONSTRAINT_TEXT FROM CX_WORK_CONSTRAINTS "
                               "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision ORDER BY ITEM_NO", params)
        def text(value):
            return value.read() if hasattr(value, 'read') else value
        content = WorkContent(objective=text(record['objective']),
            criteria=[{key: text(value) for key, value in item.items()} for item in criteria],
            constraints=[text(item['constraint_text']) for item in constraints],
            sources=tx.query("SELECT FAMILY,ENTITY_ID,SOURCE_REVISION_ID AS REVISION_ID,CONTENT_DIGEST FROM CX_WORK_SOURCES "
                             "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision ORDER BY ITEM_NO",params))
        if content_digest(content) != record['content_digest']:
            raise ContinuityError('INTEGRITY_ERROR', 'Stored work revision failed integrity validation')
        if content.sources:
            from .continuity_sources import resolve
            for source in content.sources:
                resolve(tx,actor,work['security_domain_id'],source,purpose='WORK_CONTEXT')
        snapshot = tx.query_one("SELECT OWNER_PRINCIPAL_ID,STATUS FROM CX_WORK_REVISION_STATES "
                                "WHERE WORK_CONTRACT_ID=:work_id AND REVISION_NO=:revision", params)
        if not snapshot:
            raise ContinuityError('REVISION_STATE_UNAVAILABLE', 'The requested responsibility snapshot is unavailable')
        from .continuity_policy import read as read_policy
        policy=read_policy(tx,work_id,selected)
        return dict(work, handoff_policy=policy, execution_links=execution_links, revision_no=selected, revision_owner_principal_id=snapshot['owner_principal_id'],
                    revision_status=snapshot['status'], content=content.model_dump(mode='json'), content_digest=record['content_digest'])


def read_work(actor, work_id, revision=None):
    return connection.execute_transaction_callback(lambda tx: _read_work(tx, actor, work_id, revision))
