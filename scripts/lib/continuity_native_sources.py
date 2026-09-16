"""Immutable, typed snapshots of authorized native execution projections.

Snapshot relations preserve history without changing native object deletion
semantics. Native identifiers remain typed locators; every read must also
authorize the current original object. No arbitrary table or JSON body input
is accepted from callers.
"""
import hashlib
import json
from datetime import datetime,timezone
from typing import Literal
from . import connection,identity_api,continuity_work as work
from .continuity_contracts import Contract,Identifier,Reason,SourceRef,request_digest
from .continuity_state import ContinuityConflict,ContinuityError
from . import continuity_execution_links as links


class CaptureRequest(Contract):
    family: Literal['TASK','GRAPH','DB4A2A','AUDIT']
    entity_id: Identifier
    security_domain_id: Identifier
    reason: Reason
    idempotency_key: Identifier


# Column definitions are shared by the typed persistence and native projection.
# The native table and its locator never come from request text.
PROJECTIONS={
    'TASK':('TASK_PLANS','PLAN_ID','AGENT_ID','tasks.read',{
        'goal':'TEXT','status':'VARCHAR(32)','priority':'INTEGER','strategy':'VARCHAR(128)','result_summary':'TEXT'}),
    'GRAPH':('GRAPH_RUNS','RUN_ID','ACTOR_ID','graphs.read',{
        'graph_version_id':'VARCHAR(128)','plan_id':'VARCHAR(128)','status':'VARCHAR(32)',
        'current_checkpoint_id':'VARCHAR(128)','error_code':'VARCHAR(128)','error_message':'VARCHAR(2000)'}),
    'DB4A2A':('CX_DB4A2A_DISPATCHES','DISPATCH_ID','SENDER_PRINCIPAL_ID','tasks.read',{
        'task_id':'VARCHAR(256)','receiver_agent_id':'VARCHAR(128)','context_ref':'VARCHAR(256)',
        'snapshot_digest':'VARCHAR(256)','expected_version':'BIGINT','scope_ref':'VARCHAR(256)',
        'source_branch':'VARCHAR(256)','branch_policy':'VARCHAR(32)','transport':'VARCHAR(32)',
        'status':'VARCHAR(32)','child_branch_id':'VARCHAR(128)'}),
    'AUDIT':('CX_SECURITY_EVENTS','EVENT_ID','PRINCIPAL_ID','audit.read',{
        'actor_type':'VARCHAR(16)','action_name':'VARCHAR(128)','resource_type':'VARCHAR(64)',
        'resource_id':'VARCHAR(128)','outcome':'VARCHAR(32)','reason':'VARCHAR(2000)'}),
}
CHILDREN={
    'TASK':('TASK_STEPS','PLAN_ID','STEP_ID',{'step_order':'INTEGER','description':'TEXT','tool_name':'VARCHAR(128)','status':'VARCHAR(32)'}),
    'GRAPH':('GRAPH_NODE_RUNS','RUN_ID','NODE_RUN_ID',{'node_key':'VARCHAR(256)','status':'VARCHAR(32)',
        'branch_key':'VARCHAR(256)','join_key':'VARCHAR(256)','iteration_no':'INTEGER',
        'input_checkpoint_id':'VARCHAR(128)','output_checkpoint_id':'VARCHAR(128)'}),
}


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('Unsupported adapter')
    statements=["CREATE TABLE CX_NATIVE_CONTEXT_REVISIONS (REVISION_ID VARCHAR(128) PRIMARY KEY, "
        "FAMILY VARCHAR(16) NOT NULL CHECK(FAMILY IN ('TASK','GRAPH','DB4A2A','AUDIT')), ENTITY_ID VARCHAR(128) NOT NULL, "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "SOURCE_PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "CAPTURED_BY VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "REASON VARCHAR(1000) NOT NULL, IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UNIQUE(CAPTURED_BY,IDEMPOTENCY_KEY), UNIQUE(REVISION_ID,FAMILY))"]
    def sql_type(kind):
        if dialect not in {'pg','postgresql'}:
            return {'TEXT':'CLOB','BIGINT':'NUMBER(19)'}.get(kind,kind)
        return kind
    for family,(_,_,_,_,fields) in PROJECTIONS.items():
        statements.append('CREATE TABLE CX_'+family+'_CONTEXT_REVISIONS (REVISION_ID VARCHAR(128) PRIMARY KEY, '+
                          "FAMILY VARCHAR(16) DEFAULT '"+family+"' NOT NULL CHECK(FAMILY='"+family+"'), "+
                          ', '.join(name.upper()+' '+sql_type(kind) for name,kind in fields.items())+
                          ', FOREIGN KEY(REVISION_ID,FAMILY) REFERENCES CX_NATIVE_CONTEXT_REVISIONS(REVISION_ID,FAMILY))')
    for family,(_,_,_,fields) in CHILDREN.items():
        statements.append('CREATE TABLE CX_'+family+'_CONTEXT_ITEMS (REVISION_ID VARCHAR(128) NOT NULL REFERENCES CX_'+family+'_CONTEXT_REVISIONS(REVISION_ID), '
                          'ITEM_ID VARCHAR(128) NOT NULL, '+', '.join(name.upper()+' '+sql_type(kind) for name,kind in fields.items())+', PRIMARY KEY(REVISION_ID,ITEM_ID))')
    return statements


def _native_id(family,entity):
    if family=='TASK':
        try: return getattr(connection,'normalize_execution_reference',lambda *_:entity)('TASK',entity)
        except ValueError as exc: raise ContinuityError('INVALID_REFERENCE','Invalid native Task identifier') from exc
    return entity


def _authorize(tx,actor,domain,family,entity):
    work._authorize(tx,actor,domain,write=False)
    if family in {'TASK','GRAPH'}:
        return links.authorize(tx,actor,domain,family,entity)
    table,key,owner,action,_=PROJECTIONS[family]
    row=tx.query_one(f'SELECT {owner} AS OWNER_ID'+(',RECEIVER_AGENT_ID' if family=='DB4A2A' else '')+
                     f' FROM {table} WHERE {key}=:entity',{'entity':entity})
    if not row or not row['owner_id']:
        raise PermissionError('Native context source unavailable')
    if identity_api.effective_access(actor,action,resource={'security_domain_id':domain}).get('decision')!='ALLOW':
        raise PermissionError('Native source permission denied')
    participants={row['owner_id']}
    if family=='DB4A2A': participants.add(row['receiver_agent_id'])
    if actor not in participants:
        raise PermissionError('Native source participant permission denied')
    work._authorize(tx,row['owner_id'],domain,write=False)
    return str(row['owner_id'])


def _values(row,fields,prefix=''):
    values={}
    for name,kind in fields.items():
        value=row.get(prefix+name)
        if hasattr(value,'read'): value=value.read()
        if value is not None:
            value=int(value) if kind in {'INTEGER','BIGINT'} else str(value) or None
        values[name]=value
    return values


def _render(payload):
    return json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _capture(tx,family,entity,owner):
    table,key,owner_column,_,fields=PROJECTIONS[family]
    columns=[f'p.{owner_column} AS SOURCE_OWNER']+[f'p.{name.upper()} AS P_{name.upper()}' for name in fields]
    params={'entity':_native_id(family,entity),'page_limit':1001}
    query=f' FROM {table} p '
    if family in CHILDREN:
        child,parent,child_key,child_fields=CHILDREN[family]
        columns+=[f'c.{child_key} AS ITEM_ID']+[f'c.{name.upper()} AS C_{name.upper()}' for name in child_fields]
        query+=f'LEFT JOIN {child} c ON c.{parent}=p.{key} '
    # One native SELECT gives a single statement-consistent parent/child view.
    query='SELECT '+','.join(columns)+query+f'WHERE p.{key}=:entity '
    if family in CHILDREN: query+=f'ORDER BY c.{child_key} '
    rows=tx.query(query+identity_api._limit_clause('page_limit'),params)
    if not rows or str(rows[0]['source_owner'])!=owner:
        raise PermissionError('Native source responsibility changed')
    if len(rows)>1000:
        raise ContinuityError('SOURCE_TOO_LARGE','Native source exceeds 1000 child records')
    payload={'family':family,'entity_id':entity,'source_principal_id':owner,'fields':_values(rows[0],fields,'p_'),'items':[]}
    if family in CHILDREN:
        for row in rows:
            if row['item_id'] is not None:
                payload['items'].append(dict(item_id=str(row['item_id']),**_values(row,child_fields,'c_')))
    # Native numeric item identifiers sort identically after storing as text.
    payload['items'].sort(key=lambda item:item['item_id'])
    if len(_render(payload).encode('utf-8'))>256*1024:
        raise ContinuityError('SOURCE_TOO_LARGE','Native source exceeds the snapshot budget')
    return payload


def capture(actor,value):
    request=CaptureRequest.model_validate(value)
    def perform(tx):
        work._lock_actor(tx,actor)
        work._authorize(tx,actor,request.security_domain_id,write=True)
        owner=_authorize(tx,actor,request.security_domain_id,request.family,request.entity_id)
        digest=request_digest(actor,'NATIVE_CONTEXT_CAPTURE',request)
        previous=tx.query_one('SELECT REVISION_ID,REQUEST_DIGEST,CONTENT_DIGEST FROM CX_NATIVE_CONTEXT_REVISIONS WHERE CAPTURED_BY=:actor AND IDEMPOTENCY_KEY=:key',{'actor':actor,'key':request.idempotency_key})
        if previous:
            if previous['request_digest']!=digest:
                raise ContinuityConflict('IDEMPOTENCY_CONFLICT','Capture request key changed')
            source=dict(family=request.family,entity_id=request.entity_id,revision_id=previous['revision_id'],content_digest=previous['content_digest'])
            resolve(tx,actor,request.security_domain_id,source)
            return dict(source=source,replayed=True)
        payload=_capture(tx,request.family,request.entity_id,owner)
        revision=work._id('NS')
        # Oracle's default datetime bind is DATE (whole seconds). Use the same
        # explicit precision on every adapter so the persisted time retains
        # the exact digest without relying on driver-specific bind inference.
        captured=datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)
        payload.update(revision_id=revision,captured_at=_timestamp(captured))
        encoded=_render(payload).encode('utf-8')
        if len(encoded)>256*1024:
            raise ContinuityError('SOURCE_TOO_LARGE','Native source exceeds the snapshot budget')
        content_digest=hashlib.sha256(encoded).hexdigest()
        tx.execute('INSERT INTO CX_NATIVE_CONTEXT_REVISIONS(REVISION_ID,FAMILY,ENTITY_ID,SECURITY_DOMAIN_ID,SOURCE_PRINCIPAL_ID,CAPTURED_BY,CONTENT_DIGEST,REASON,IDEMPOTENCY_KEY,REQUEST_DIGEST,CREATED_AT) '
                   'VALUES(:revision,:family,:entity,:domain,:owner,:actor,:digest,:reason,:key,:request_digest,:captured)',
                   {'revision':revision,'family':request.family,'entity':request.entity_id,'domain':request.security_domain_id,'owner':owner,'actor':actor,
                    'digest':content_digest,'reason':request.reason,'key':request.idempotency_key,'request_digest':digest,'captured':captured})
        def insert(table,fields):
            values={'revision_id':revision,**fields}
            tx.execute('INSERT INTO '+table+'('+','.join(name.upper() for name in values)+') VALUES('+','.join(':'+name for name in values)+')',values)
        insert('CX_'+request.family+'_CONTEXT_REVISIONS',payload['fields'])
        for item in payload['items']:
            insert('CX_'+request.family+'_CONTEXT_ITEMS',item)
        identity_api._audit_tx(tx,actor,'NATIVE_CONTEXT_CAPTURED','CONTEXT_SOURCE',revision,'ALLOW',request.reason)
        return dict(source=dict(family=request.family,entity_id=request.entity_id,revision_id=revision,content_digest=content_digest),replayed=False)
    return connection.execute_transaction_callback(perform)


def locate(tx,source):
    source=SourceRef.model_validate(source)
    return tx.query_one('SELECT r.SECURITY_DOMAIN_ID,r.SOURCE_PRINCIPAL_ID AS OWNER_PRINCIPAL_ID,d.CLASSIFICATION '
        'FROM CX_NATIVE_CONTEXT_REVISIONS r JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID=r.SECURITY_DOMAIN_ID '
        'WHERE r.REVISION_ID=:revision AND r.FAMILY=:family AND r.ENTITY_ID=:entity',
        {'revision':source.revision_id,'family':source.family.value,'entity':source.entity_id})


def _timestamp(value):
    if isinstance(value,str): value=datetime.fromisoformat(value)
    if value.tzinfo is not None: value=value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec='microseconds')+'Z'


def resolve(tx,actor,domain,value):
    source=SourceRef.model_validate(value)
    family=source.family.value
    if family not in PROJECTIONS:
        raise ValueError('Unsupported native source family')
    metadata=locate(tx,source)
    if not metadata or metadata['security_domain_id']!=domain:
        raise PermissionError('Native sources require their original domain')
    owner=_authorize(tx,actor,domain,family,source.entity_id)
    if owner!=metadata['owner_principal_id']:
        raise PermissionError('Native source responsibility changed')
    root=tx.query_one('SELECT CONTENT_DIGEST,CREATED_AT FROM CX_NATIVE_CONTEXT_REVISIONS WHERE REVISION_ID=:revision',{'revision':source.revision_id})
    fields=tx.query_one('SELECT * FROM CX_'+family+'_CONTEXT_REVISIONS WHERE REVISION_ID=:revision',{'revision':source.revision_id})
    if not fields:
        raise ContinuityError('INTEGRITY_ERROR','Native source projection missing')
    items=[]
    if family in CHILDREN:
        for row in tx.query('SELECT * FROM CX_'+family+'_CONTEXT_ITEMS WHERE REVISION_ID=:revision ORDER BY ITEM_ID',{'revision':source.revision_id}):
            items.append(dict(item_id=row['item_id'],**_values(row,CHILDREN[family][3])))
    payload=dict(family=family,entity_id=source.entity_id,source_principal_id=owner,fields=_values(fields,PROJECTIONS[family][4]),items=items,
                 revision_id=source.revision_id,captured_at=_timestamp(root['created_at']))
    text=_render(payload)
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
    if digest!=root['content_digest'] or digest!=source.content_digest:
        raise ContinuityConflict('STALE_CONTENT','Native source digest mismatch')
    return dict(source=source.model_dump(mode='json'),text=text,content_digest=digest,authorized_scope=domain)
