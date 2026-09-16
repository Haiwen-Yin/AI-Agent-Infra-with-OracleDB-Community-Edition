"""Short-lived, budgeted context assemblies with exact input-use receipts.

The prepared rows are not long-term memory and are not delivery evidence.
Only consume() passes a freshly authorized payload to a trusted model adapter.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from . import connection, identity_api, continuity_work as work, continuity_handoff as handoff
from .continuity_contracts import AssemblyRequest, request_digest
from .continuity_sources import resolve
from .continuity_state import ContinuityError, ContinuityConflict, require_not_expired, require_idempotent_request


def schema_statements(dialect):
    if dialect not in {'pg','postgresql','oracle','yashandb'}:
        raise ValueError('unsupported database adapter')
    return [
        "CREATE TABLE CX_CONTEXT_ASSEMBLIES (ASSEMBLY_ID VARCHAR(128) PRIMARY KEY, REQUEST_ID VARCHAR(128) NOT NULL, "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "POLICY_VERSION INTEGER NOT NULL, RETRIEVAL_POLICY VARCHAR(64) NOT NULL, TOKEN_BUDGET INTEGER NOT NULL CHECK(TOKEN_BUDGET>0), "
        "ENTRY_LIMIT INTEGER NOT NULL CHECK(ENTRY_LIMIT>=0), CONTENT_DIGEST VARCHAR(64) NOT NULL, "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PREPARED','SENDING','SENT','UNOBSERVED')), "
        "PURPOSE VARCHAR(1000) NOT NULL, EXPIRES_AT TIMESTAMP NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, UNIQUE(PRINCIPAL_ID,IDEMPOTENCY_KEY))",
        "CREATE TABLE CX_CONTEXT_ASSEMBLY_ITEMS (ASSEMBLY_ID VARCHAR(128) NOT NULL REFERENCES CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID), "
        "ITEM_NO INTEGER NOT NULL CHECK(ITEM_NO>0), FAMILY VARCHAR(24) NOT NULL, ENTITY_ID VARCHAR(128) NOT NULL, "
        "REVISION_ID VARCHAR(128) NOT NULL, CONTENT_DIGEST VARCHAR(64) NOT NULL, RENDERED_DIGEST VARCHAR(64) NOT NULL, "
        "RENDERED_TOKENS INTEGER NOT NULL CHECK(RENDERED_TOKENS>=0), AUTHORIZED_SCOPE VARCHAR(128) NOT NULL, "
        "SELECTION_REASON VARCHAR(64) NOT NULL, RANK_SCORE INTEGER NOT NULL, REDACTION_STATE VARCHAR(24) NOT NULL, "
        "PRIMARY KEY(ASSEMBLY_ID,ITEM_NO))",
        "CREATE TABLE CX_CONTEXT_ITEM_GRANTS (ASSEMBLY_ID VARCHAR(128) NOT NULL, ITEM_NO INTEGER NOT NULL, "
        "PUBLICATION_ID VARCHAR(128) NOT NULL, PRIMARY KEY(ASSEMBLY_ID,ITEM_NO), "
        "FOREIGN KEY(ASSEMBLY_ID,ITEM_NO) REFERENCES CX_CONTEXT_ASSEMBLY_ITEMS(ASSEMBLY_ID,ITEM_NO))",
        "CREATE TABLE CX_CONTEXT_INPUT_USES (USE_ID VARCHAR(128) PRIMARY KEY, "
        "ASSEMBLY_ID VARCHAR(128) NOT NULL UNIQUE REFERENCES CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID), "
        "PRINCIPAL_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "CONTENT_DIGEST VARCHAR(64) NOT NULL, ITEM_COUNT INTEGER NOT NULL CHECK(ITEM_COUNT>=0), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('SENDING','SENT','UNOBSERVED')), "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, COMPLETED_AT TIMESTAMP)",
    ]


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _render(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _item(family,entity,revision,digest,text,domain):
    return dict(family=family,entity_id=entity,revision_id=str(revision),content_digest=digest,text=text,
                authorized_scope=domain,rendered_digest=_digest(text),rendered_tokens=len(text.encode('utf-8')))


def _work_item(tx,actor,domain,work_id,revision=None):
    record=work._read_work(tx,actor,work_id,revision)
    if record['security_domain_id']!=domain:
        raise PermissionError('An explicit context publication is required')
    return _item('WORK',work_id,record['revision_no'],record['content_digest'],_render(record['content']),domain)


def _handoff_item(tx,actor,domain,handoff_id,revision=None):
    record=handoff._read_handoff(tx,actor,handoff_id,revision)
    if record['expired']:
        raise ContinuityConflict('EXPIRED','The handoff expired')
    source=dict(family='HANDOFF',entity_id=handoff_id,revision_id=str(record['revision_no']),content_digest=record['content_digest'])
    resolved=resolve(tx,actor,domain,source)
    return _item('HANDOFF',handoff_id,record['revision_no'],record['content_digest'],resolved['text'],domain)


def assemble(actor,value,*,transaction=None):
    request=value if isinstance(value,AssemblyRequest) else AssemblyRequest.model_validate(value)
    def perform(tx):
        work._authorize(tx,actor,request.security_domain_id,write=False)
        existing=tx.query_one("SELECT ASSEMBLY_ID,REQUEST_DIGEST FROM CX_CONTEXT_ASSEMBLIES WHERE PRINCIPAL_ID=:actor AND IDEMPOTENCY_KEY=:key",
                              {'actor':actor,'key':request.idempotency_key})
        if existing:
            require_idempotent_request(existing['request_digest'],request_digest(actor,'CONTEXT_ASSEMBLE',request))
            # Replay cannot extend TTL or bypass current source authorization.
            return dict(_read(tx,actor,existing['assembly_id']),replayed=True)
        available=[]
        if request.work_contract_id:
            available.append(_work_item(tx,actor,request.security_domain_id,request.work_contract_id))
        if request.handoff_id:
            available.append(_handoff_item(tx,actor,request.security_domain_id,request.handoff_id))
        for source in request.sources:
            resolved=resolve(tx,actor,request.security_domain_id,source,purpose=request.purpose)
            available.append(dict(_item(source.family.value,source.entity_id,source.revision_id,source.content_digest,
                                   resolved['text'],request.security_domain_id),publication_id=resolved.get('publication_id')))
        selected=[]
        seen=set()
        used=0
        for item in available:
            key=(item['family'],item['entity_id'],item['revision_id'])
            cost=item['rendered_tokens']+(2 if selected else 0)
            if key in seen or len(selected)>=request.entry_limit or used+cost>request.token_budget:
                continue
            selected.append(item)
            seen.add(key)
            used+=cost
        body='\n\n'.join(item['text'] for item in selected)
        assembly_id=work._id('CA')
        policy=tx.query_one("SELECT PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor",{'actor':actor})
        tx.execute("INSERT INTO CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID,REQUEST_ID,PRINCIPAL_ID,SECURITY_DOMAIN_ID,POLICY_VERSION,RETRIEVAL_POLICY,"
                   "TOKEN_BUDGET,ENTRY_LIMIT,CONTENT_DIGEST,STATUS,PURPOSE,EXPIRES_AT,IDEMPOTENCY_KEY,REQUEST_DIGEST) "
                   "VALUES(:assembly,:request_id,:actor,:domain,:policy,'EXPLICIT_ORDER_UTF8_UPPER_BOUND',:budget,:entries,:digest,'PREPARED',:purpose,:expires,:key,:request_digest)",
                   {'assembly':assembly_id,'request_id':request.request_id,'actor':actor,'domain':request.security_domain_id,
                    'policy':int(policy['permission_version']),'budget':request.token_budget,'entries':request.entry_limit,'digest':_digest(body),
                    'purpose':request.purpose,'expires':(datetime.now(timezone.utc)+timedelta(seconds=request.ttl_seconds)).replace(tzinfo=None),
                    'key':request.idempotency_key,'request_digest':request_digest(actor,'CONTEXT_ASSEMBLE',request)})
        for number,item in enumerate(selected,1):
            tx.execute("INSERT INTO CX_CONTEXT_ASSEMBLY_ITEMS(ASSEMBLY_ID,ITEM_NO,FAMILY,ENTITY_ID,REVISION_ID,CONTENT_DIGEST,RENDERED_DIGEST,"
                       "RENDERED_TOKENS,AUTHORIZED_SCOPE,SELECTION_REASON,RANK_SCORE,REDACTION_STATE) "
                       "VALUES(:assembly,:v_item_no,:family,:entity,:revision,:digest,:rendered,:tokens,:scope,'EXPLICIT_REQUEST',:v_rank_score,'NONE')",
                       {'assembly':assembly_id,'v_item_no':number,'family':item['family'],'entity':item['entity_id'],'revision':item['revision_id'],
                        'digest':item['content_digest'],'rendered':item['rendered_digest'],'tokens':item['rendered_tokens'],
                        'scope':item['authorized_scope'],'v_rank_score':len(selected)-number+1})
            if item.get('publication_id'):
                tx.execute("INSERT INTO CX_CONTEXT_ITEM_GRANTS(ASSEMBLY_ID,ITEM_NO,PUBLICATION_ID) VALUES(:assembly,:item_no,:publication)",
                           {'assembly':assembly_id,'item_no':number,'publication':item['publication_id']})
        identity_api._audit_tx(tx,actor,'CONTEXT_PREPARED','CONTEXT_ASSEMBLY',assembly_id,'ALLOW',request.purpose)
        return {'assembly_id':assembly_id,'status':'PREPARED','content_digest':_digest(body),'item_count':len(selected),
                'rendered_tokens':used,'token_count_method':'UTF8_UPPER_BOUND','replayed':False}
    return perform(transaction) if transaction is not None else connection.execute_transaction_callback(perform)


def _read(tx,actor,assembly_id):
    work._lock_actor(tx,actor)
    record=tx.query_one("SELECT * FROM CX_CONTEXT_ASSEMBLIES WHERE ASSEMBLY_ID=:assembly AND PRINCIPAL_ID=:actor",
                        {'assembly':assembly_id,'actor':actor})
    if not record:
        raise PermissionError('Context assembly access denied')
    work._authorize(tx,actor,record['security_domain_id'],write=False)
    require_not_expired(handoff._utc(record['expires_at']),datetime.now(timezone.utc))
    items=tx.query("SELECT * FROM CX_CONTEXT_ASSEMBLY_ITEMS WHERE ASSEMBLY_ID=:assembly ORDER BY ITEM_NO",{'assembly':assembly_id})
    texts=[]
    for item in items:
        if item['authorized_scope']!=record['security_domain_id']:
            raise ContinuityError('INTEGRITY_ERROR','Stored assembly scope is inconsistent')
        if item['family']=='WORK':
            resolved=_work_item(tx,actor,record['security_domain_id'],item['entity_id'],int(item['revision_id']))
        else:
            source={name:item[name] for name in ['family','entity_id','revision_id','content_digest']}
            grant=tx.query_one("SELECT PUBLICATION_ID FROM CX_CONTEXT_ITEM_GRANTS WHERE ASSEMBLY_ID=:assembly AND ITEM_NO=:item_no",
                               {'assembly':assembly_id,'item_no':item['item_no']})
            resolved=resolve(tx,actor,record['security_domain_id'],source,purpose=record['purpose'],
                             publication_id=grant['publication_id'] if grant else None)
        text=resolved['text']
        if resolved['content_digest']!=item['content_digest'] or _digest(text)!=item['rendered_digest'] or len(text.encode('utf-8'))!=int(item['rendered_tokens']):
            raise ContinuityError('INTEGRITY_ERROR','Stored assembly item failed integrity validation')
        texts.append(text)
    body='\n\n'.join(texts)
    if _digest(body)!=record['content_digest'] or len(items)>int(record['entry_limit']) or len(body.encode('utf-8'))>int(record['token_budget']):
        raise ContinuityError('INTEGRITY_ERROR','Stored assembly failed integrity validation')
    return {'assembly_id':assembly_id,'status':record['status'],'content_digest':record['content_digest'],
            'request_id':record['request_id'],'expires_at':record['expires_at'],'purpose':record['purpose'],
            'policy_version':int(record['policy_version']),'retrieval_policy':record['retrieval_policy'],
            'token_budget':int(record['token_budget']),'entry_limit':int(record['entry_limit']),
            'item_count':len(items),'items':items,'text':body,'token_count_method':'UTF8_UPPER_BOUND'}


def read_assembly(actor,assembly_id):
    return connection.execute_transaction_callback(lambda tx:_read(tx,actor,assembly_id))


def consume(actor,assembly_id,send,*,authorize=None,on_reserved=None):
    """Call a trusted adapter with the exact freshly authorized context text.

    send is server code, never a user-supplied URL or executable. A send failure
    leaves UNOBSERVED because the remote service may have received the request.
    It is deliberately not automatically retried under a new receipt.
    """
    def reserve(tx):
        if authorize is not None:
            authorize(tx)
        record=_read(tx,actor,assembly_id)
        changed=tx.execute("UPDATE CX_CONTEXT_ASSEMBLIES SET STATUS='SENDING' WHERE ASSEMBLY_ID=:assembly AND STATUS='PREPARED'",
                           {'assembly':assembly_id})
        if changed!=1:
            raise ContinuityConflict('CONTEXT_ALREADY_USED','The assembly already has a model-input attempt')
        use_id=work._id('CU')
        tx.execute("INSERT INTO CX_CONTEXT_INPUT_USES(USE_ID,ASSEMBLY_ID,PRINCIPAL_ID,CONTENT_DIGEST,ITEM_COUNT,STATUS) "
                   "VALUES(:use_id,:assembly,:actor,:digest,:count,'SENDING')",
                   {'use_id':use_id,'assembly':assembly_id,'actor':actor,'digest':record['content_digest'],'count':record['item_count']})
        identity_api._audit_tx(tx,actor,'CONTEXT_INPUT_RESERVED','CONTEXT_ASSEMBLY',assembly_id,'ALLOW','Exact context input reserved')
        if on_reserved is not None:
            on_reserved(tx,record,use_id)
        return record,use_id
    record,use_id=connection.execute_transaction_callback(reserve)
    def finish(status):
        def commit(tx):
            tx.execute("UPDATE CX_CONTEXT_ASSEMBLIES SET STATUS=:status WHERE ASSEMBLY_ID=:assembly AND STATUS='SENDING'",
                       {'assembly':assembly_id,'status':status})
            tx.execute("UPDATE CX_CONTEXT_INPUT_USES SET STATUS=:status,COMPLETED_AT=CURRENT_TIMESTAMP WHERE USE_ID=:use_id AND STATUS='SENDING'",
                       {'use_id':use_id,'status':status})
            identity_api._audit_tx(tx,actor,'CONTEXT_INPUT_'+status,'CONTEXT_ASSEMBLY',assembly_id,'ALLOW','Context delivery observation')
        connection.execute_transaction_callback(commit)
    try:
        result=send(record['text'])
    except Exception:
        finish('UNOBSERVED')
        raise
    finish('SENT')
    return {'assembly_id':assembly_id,'use_id':use_id,'status':'SENT','content_digest':record['content_digest'],'result':result}
