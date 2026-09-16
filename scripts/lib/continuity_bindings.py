"""Additional typed relations, installed after continuity migration 86."""
from contextlib import contextmanager
from contextvars import ContextVar

_transport=ContextVar('continuity_authenticated_transport',default=None)


@contextmanager
def authenticated_transport(context):
    token=_transport.set(context)
    try:
        yield
    finally:
        _transport.reset(token)


def schema_statements(dialect):
    if dialect not in {'oracle','pg','postgresql','yashandb'}:
        raise ValueError('Unsupported database adapter')
    return [
        "CREATE TABLE CX_HANDOFF_EVIDENCE (HANDOFF_ID VARCHAR(128) NOT NULL, REVISION_NO INTEGER NOT NULL, "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), FAMILY VARCHAR(24) NOT NULL, ENTITY_ID VARCHAR(128) NOT NULL, "
        "SOURCE_REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "PUBLICATION_ID VARCHAR(128) REFERENCES CX_CONTEXT_PUBLICATIONS(PUBLICATION_ID), "
        "PRIMARY KEY(HANDOFF_ID,REVISION_NO,ITEM_NO), UNIQUE(HANDOFF_ID,REVISION_NO,FAMILY,ENTITY_ID,SOURCE_REVISION_ID), "
        "FOREIGN KEY(HANDOFF_ID,REVISION_NO) REFERENCES CX_HANDOFF_REVISIONS(HANDOFF_ID,REVISION_NO))",
        "CREATE TABLE CX_HANDOFF_INSTANCE_BINDINGS (HANDOFF_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFFS(HANDOFF_ID), "
        "PARTICIPANT_SIDE VARCHAR(16) NOT NULL CHECK(PARTICIPANT_SIDE IN ('SENDER','RECIPIENT')), "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "INSTANCE_ID VARCHAR(128) NOT NULL REFERENCES CX_AGENT_INSTANCES(INSTANCE_ID), "
        "FENCING_TOKEN INTEGER NOT NULL CHECK(FENCING_TOKEN>0), CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "PRIMARY KEY(HANDOFF_ID,PARTICIPANT_SIDE))",
        "CREATE TABLE CX_HANDOFF_CREDENTIAL_USES (HANDOFF_ID VARCHAR(128) NOT NULL REFERENCES CX_HANDOFFS(HANDOFF_ID), "
        "RESOURCE_VERSION INTEGER NOT NULL CHECK(RESOURCE_VERSION>0), OPERATION VARCHAR(64) NOT NULL, "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "INSTANCE_ID VARCHAR(128) NOT NULL REFERENCES CX_AGENT_INSTANCES(INSTANCE_ID), "
        "TOKEN_DIGEST VARCHAR(64) NOT NULL REFERENCES CX_AGENT_ACCESS_TOKENS(TOKEN_DIGEST), "
        "FENCING_TOKEN INTEGER NOT NULL CHECK(FENCING_TOKEN>0), CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "PRIMARY KEY(HANDOFF_ID,RESOURCE_VERSION))",
    ]


def bind_instances(tx,actor,handoff_id,domain,request):
    from .continuity_state import ContinuityError
    context=_transport.get()
    if context is not None and request.kind!='WORKER_REPLACEMENT' and request.sender_instance_id is not None and request.sender_instance_id!=context['instance_id']:
        raise PermissionError('The sender instance must match the authenticated transport')
    if request.kind=='WORKER_REPLACEMENT' and (
        not request.sender_instance_id or not request.recipient_instance_id
        or request.sender_instance_id==request.recipient_instance_id
    ):
        raise ContinuityError('INVALID_INSTANCE_REPLACEMENT','Replacement requires distinct old and new instances')
    for side,principal,instance in (('SENDER',actor,request.sender_instance_id),
                                    ('RECIPIENT',request.recipient_principal_id,request.recipient_instance_id)):
        if not instance:
            continue
        # A dead worker can be the source of a replacement. Its identity and
        # original fencing value remain historical; the new recipient must live.
        active=not(side=='SENDER' and request.kind=='WORKER_REPLACEMENT')
        row=tx.query_one("SELECT FENCING_TOKEN FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance AND AGENT_ID=:principal "
                         "AND SECURITY_DOMAIN_ID=:domain "+("AND STATUS='ACTIVE' AND REVOKED_AT IS NULL AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP " if active else ''),
                         {'instance':instance,'principal':principal,'domain':domain})
        if not row:
            raise PermissionError('Handoff instance access denied')
        tx.execute("INSERT INTO CX_HANDOFF_INSTANCE_BINDINGS(HANDOFF_ID,PARTICIPANT_SIDE,PRINCIPAL_ID,INSTANCE_ID,FENCING_TOKEN) "
                   "VALUES(:handoff,:side,:principal,:instance,:fence)",
                   {'handoff':handoff_id,'side':side,'principal':principal,'instance':instance,'fence':int(row['fencing_token'])})


def recipient_current(tx,handoff_id,domain):
    bound=tx.query_one("SELECT PRINCIPAL_ID,INSTANCE_ID,FENCING_TOKEN FROM CX_HANDOFF_INSTANCE_BINDINGS "
                       "WHERE HANDOFF_ID=:handoff AND PARTICIPANT_SIDE='RECIPIENT'",{'handoff':handoff_id})
    if not bound:
        return True
    context=_transport.get()
    if context is not None and (context['instance_id']!=bound['instance_id'] or int(context['fencing_token'])!=int(bound['fencing_token'])):
        return False
    return bool(tx.query_one("SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance AND AGENT_ID=:principal "
                             "AND SECURITY_DOMAIN_ID=:domain AND FENCING_TOKEN=:fence AND STATUS='ACTIVE' "
                             "AND REVOKED_AT IS NULL AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
                             {'instance':bound['instance_id'],'principal':bound['principal_id'],'fence':bound['fencing_token'],'domain':domain}))


def record_transport(tx,actor,handoff_id,operation,version):
    context=_transport.get()
    if context is None:
        return
    params={'actor':actor,'instance':context['instance_id'],'digest':context['token_digest'],'fence':int(context['fencing_token'])}
    valid=tx.query_one("SELECT t.TOKEN_DIGEST FROM CX_AGENT_ACCESS_TOKENS t JOIN CX_AGENT_INSTANCES i ON i.INSTANCE_ID=t.INSTANCE_ID "
                       "WHERE t.TOKEN_DIGEST=:digest AND t.AGENT_ID=:actor AND t.INSTANCE_ID=:instance AND t.FENCING_TOKEN=:fence "
                       "AND t.REVOKED_AT IS NULL AND t.EXPIRES_AT>CURRENT_TIMESTAMP AND i.AGENT_ID=t.AGENT_ID "
                       "AND i.STATUS='ACTIVE' AND i.REVOKED_AT IS NULL AND i.LEASE_EXPIRES_AT>CURRENT_TIMESTAMP AND i.FENCING_TOKEN=t.FENCING_TOKEN",params)
    if not valid:
        raise PermissionError('Handoff transport credential is no longer current')
    tx.execute("INSERT INTO CX_HANDOFF_CREDENTIAL_USES(HANDOFF_ID,RESOURCE_VERSION,OPERATION,PRINCIPAL_ID,INSTANCE_ID,TOKEN_DIGEST,FENCING_TOKEN) "
               "VALUES(:handoff,:version,:operation,:actor,:instance,:digest,:fence)",dict(params,handoff=handoff_id,version=version,operation=operation))
