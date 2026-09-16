"""Immutable typed execution links; links never delegate native resource access."""
from . import identity_api,connection
from .continuity_state import ContinuityConflict,ContinuityError

KINDS={'WORKSPACE':('WORKSPACES','WORKSPACE_ID','CURRENT_AGENT_ID','workspaces.read'),
       'TASK':('TASK_PLANS','PLAN_ID','AGENT_ID','tasks.read'),
       'GRAPH':('GRAPH_RUNS','RUN_ID','ACTOR_ID','graphs.read')}


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    return ["CREATE TABLE CX_WORK_EXECUTION_LINKS (WORK_CONTRACT_ID VARCHAR(128) NOT NULL REFERENCES CX_WORK_CONTRACTS(WORK_CONTRACT_ID), "
            "LINK_KIND VARCHAR(16) NOT NULL CHECK(LINK_KIND IN ('WORKSPACE','TASK','GRAPH')), "
            "ENTITY_ID VARCHAR(128) NOT NULL, SOURCE_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
            "CREATED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
            "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, PRIMARY KEY(WORK_CONTRACT_ID,LINK_KIND))"]


def authorize(tx,actor,domain,kind,entity_id):
    table,key,owner_column,action=KINDS[kind]
    try:
        native_id=getattr(connection,'normalize_execution_reference',lambda kind,value:value)(kind,entity_id)
    except ValueError as exc:
        raise ContinuityError('INVALID_REFERENCE','Invalid native execution identifier') from exc
    # Identifiers come only from the fixed mapping. Native Task IDs remain
    # locators, not status-dependent foreign keys into partitioned task rows.
    row=tx.query_one(f'SELECT {owner_column} AS OWNER_ID'+(',OWNER_USER_ID' if kind=='WORKSPACE' else '')+
                     f' FROM {table} WHERE {key}=:entity',{'entity':native_id})
    if not row:
        raise PermissionError('Execution resource access denied')
    principal=row['owner_id']
    if kind=='WORKSPACE' and row['owner_user_id'] is not None:
        identities=tx.query("SELECT DISTINCT h.PRINCIPAL_ID FROM CX_HUMAN_IDENTITIES h JOIN SYSTEM_USERS u "
                            "ON u.USERNAME=h.USERNAME JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=h.PRINCIPAL_ID "
                            "WHERE u.USER_ID=:user_id AND h.IDENTITY_TYPE='LOCAL' AND h.STATUS='ACTIVE' AND p.STATUS='ACTIVE'",
                            {'user_id':row['owner_user_id']})
        if len(identities)!=1:
            raise PermissionError('Execution resource owner unavailable')
        principal=identities[0]['principal_id']
    if not principal:
        raise PermissionError('Execution resource owner unavailable')
    owner=tx.query_one("SELECT p.PRINCIPAL_ID FROM CX_PRINCIPALS p JOIN CX_DOMAIN_MEMBERS m ON m.PRINCIPAL_ID=p.PRINCIPAL_ID "
                       "WHERE p.PRINCIPAL_ID=:owner AND p.STATUS='ACTIVE' AND m.SECURITY_DOMAIN_ID=:domain "
                       "AND m.STATUS='ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)",
                       {'owner':principal,'domain':domain})
    if not owner or identity_api.effective_access(actor,action,resource={'security_domain_id':domain}).get('decision')!='ALLOW':
        raise PermissionError('Execution resource access denied')
    if actor!=principal:
        relationship=tx.query_one("SELECT RELATIONSHIP_ID FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID=:owner AND PRINCIPAL_ID=:actor "
                                  "AND RELATIONSHIP_ROLE='PRIMARY_OWNER' AND STATUS='ACTIVE' AND ENDED_AT IS NULL",
                                  {'owner':principal,'actor':actor})
        # Workspace ownership is a Human responsibility. Its currently assigned
        # Agent may read only while its own workspace grant and domain hold.
        assigned=kind=='WORKSPACE' and row['owner_id']==actor
        if not relationship and not assigned:
            raise PermissionError('Execution resource access denied')
    return str(principal)


def bind(tx,actor,domain,work_id,request):
    for kind,value in (('WORKSPACE',request.workspace_id),('TASK',request.task_id),('GRAPH',request.graph_run_id)):
        if value is None:
            continue
        principal=authorize(tx,actor,domain,kind,value)
        tx.execute("INSERT INTO CX_WORK_EXECUTION_LINKS(WORK_CONTRACT_ID,LINK_KIND,ENTITY_ID,SOURCE_PRINCIPAL_ID,CREATED_BY) "
                   "VALUES(:work,:kind,:entity,:owner,:actor)",
                   {'work':work_id,'kind':kind,'entity':value,'owner':principal,'actor':actor})


def read(tx,actor,domain,work_id):
    rows=tx.query("SELECT LINK_KIND,ENTITY_ID,SOURCE_PRINCIPAL_ID FROM CX_WORK_EXECUTION_LINKS WHERE WORK_CONTRACT_ID=:work ORDER BY LINK_KIND",{'work':work_id})
    for row in rows:
        current=authorize(tx,actor,domain,row['link_kind'],row['entity_id'])
        if current!=row['source_principal_id']:
            raise ContinuityConflict('EXECUTION_OWNER_CHANGED','The linked execution resource changed responsibility')
    return rows
