"""Bounded participant metadata inventories; body reads authorize sources."""
from . import connection,identity_api,continuity_work as work
from .continuity_contracts import InventoryRequest,InventoryPage


def choices(actor,value,kind):
    """Select current memberships using work authority, without channel grants."""
    request=(InventoryPage if kind=='domain' else InventoryRequest).model_validate(value)
    def perform(tx):
        params={'actor':actor,'page_limit':request.limit+1}
        if kind=='domain':
            work._lock_actor(tx,actor)
            if identity_api.effective_access(actor,'workspaces.read').get('decision')!='ALLOW':
                raise PermissionError('Work contract access denied')
            key='security_domain_id'
            identifier='d.SECURITY_DOMAIN_ID'
            query=("SELECT d.SECURITY_DOMAIN_ID,d.DOMAIN_NAME,d.STATUS FROM CX_SECURITY_DOMAINS d "
                   "WHERE d.STATUS='ACTIVE' AND EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS m "
                   "WHERE m.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID AND m.PRINCIPAL_ID=:actor "
                   "AND m.STATUS='ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)) ")
        else:
            work._authorize(tx,actor,request.security_domain_id,write=False)
            params={'domain':request.security_domain_id,'page_limit':request.limit+1}
            key='principal_id'
            identifier='p.PRINCIPAL_ID'
            query=("SELECT p.PRINCIPAL_ID,p.PRINCIPAL_TYPE,p.DISPLAY_NAME,p.STATUS FROM CX_PRINCIPALS p "
                   "WHERE p.STATUS='ACTIVE' AND EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS m "
                   "WHERE m.PRINCIPAL_ID=p.PRINCIPAL_ID AND m.SECURITY_DOMAIN_ID=:domain "
                   "AND m.STATUS='ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP) "
                   "AND m.MEMBERSHIP_TIER IN ('OWNER','ADMIN','MEMBER')) ")
        if request.cursor is not None:
            query+='AND '+identifier+'>:cursor '
            params['cursor']=request.cursor
        rows=tx.query(query+'ORDER BY '+identifier+' '+identity_api._limit_clause('page_limit'),params)
        items=rows[:request.limit]
        return {'items':items,'next_cursor':items[-1][key] if len(rows)>request.limit else None}
    return connection.execute_transaction_callback(perform)


def list_domains(actor,value):
    return choices(actor,value,'domain')


def list_recipients(actor,value):
    return choices(actor,value,'recipient')


def inventory(actor,value,kind):
    request=InventoryRequest.model_validate(value)
    if kind not in {'work','handoff'}:
        raise ValueError('Unsupported inventory')
    def perform(tx):
        work._authorize(tx,actor,request.security_domain_id,write=False)
        params={'actor':actor,'domain':request.security_domain_id,'page_limit':request.limit+1}
        if kind=='work':
            identifier='w.WORK_CONTRACT_ID'
            query="SELECT w.WORK_CONTRACT_ID,w.OWNER_PRINCIPAL_ID,w.CREATED_BY,w.VERSION,w.STATUS FROM CX_WORK_CONTRACTS w "
            query+="WHERE w.SECURITY_DOMAIN_ID=:domain AND (w.OWNER_PRINCIPAL_ID=:actor OR w.CREATED_BY=:actor) "
            key='work_contract_id'
        else:
            identifier='h.HANDOFF_ID'
            query="SELECT h.HANDOFF_ID,h.WORK_CONTRACT_ID,h.FROM_PRINCIPAL_ID,h.TO_PRINCIPAL_ID,h.STATUS,h.VERSION,h.CURRENT_REVISION_NO,h.EXPIRES_AT "
            query+="FROM CX_HANDOFFS h JOIN CX_WORK_CONTRACTS w ON w.WORK_CONTRACT_ID=h.WORK_CONTRACT_ID "
            query+="WHERE w.SECURITY_DOMAIN_ID=:domain AND (h.FROM_PRINCIPAL_ID=:actor OR h.TO_PRINCIPAL_ID=:actor) "
            key='handoff_id'
        if request.cursor is not None:
            query+='AND '+identifier+'>:cursor '
            params['cursor']=request.cursor
        rows=tx.query(query+'ORDER BY '+identifier+' '+identity_api._limit_clause('page_limit'),params)
        items=rows[:request.limit]
        return {'items':items,'next_cursor':items[-1][key] if len(rows)>request.limit else None}
    return connection.execute_transaction_callback(perform)


def list_work(actor,value):
    return inventory(actor,value,'work')


def list_handoffs(actor,value):
    return inventory(actor,value,'handoff')


def list_candidates(actor,value):
    """List bounded metadata for proposers or currently authorized reviewers.

    Titles and source bodies remain behind the exact candidate reader.
    Review eligibility alone does not authorize reading the sources.
    """
    request=InventoryRequest.model_validate(value)
    def perform(tx):
        work._authorize(tx,actor,request.security_domain_id,write=False)
        from .continuity_candidates import _authority,ACTIONS
        allowed=[]
        for family in ACTIONS:
            try:
                _authority(tx,actor,request.security_domain_id,family,review=True)
            except PermissionError:
                continue
            allowed.append(family)
        params={'actor':actor,'domain':request.security_domain_id,'page_limit':request.limit+1}
        visibility='PROPOSED_BY=:actor'
        if allowed:
            placeholders=[]
            for index,family in enumerate(allowed):
                key='family_'+str(index)
                placeholders.append(':'+key)
                params[key]=family
            visibility+=' OR FAMILY IN ('+','.join(placeholders)+')'
        query=('SELECT CANDIDATE_ID,FAMILY,PROPOSED_BY,STATUS,VERSION,CURRENT_REVISION_NO '
               'FROM CX_ARTIFACT_CANDIDATES WHERE SECURITY_DOMAIN_ID=:domain AND ('+visibility+') ')
        if request.cursor is not None:
            query+='AND CANDIDATE_ID>:cursor '
            params['cursor']=request.cursor
        rows=tx.query(query+'ORDER BY CANDIDATE_ID '+identity_api._limit_clause('page_limit'),params)
        items=rows[:request.limit]
        return {'items':items,'next_cursor':items[-1]['candidate_id'] if len(rows)>request.limit else None}
    return connection.execute_transaction_callback(perform)


def list_assemblies(actor,value):
    request=InventoryRequest.model_validate(value)
    def perform(tx):
        work._authorize(tx,actor,request.security_domain_id,write=False)
        params={'actor':actor,'domain':request.security_domain_id,'page_limit':request.limit+1}
        query=('SELECT ASSEMBLY_ID,REQUEST_ID,STATUS,CONTENT_DIGEST,EXPIRES_AT FROM CX_CONTEXT_ASSEMBLIES '
               'WHERE PRINCIPAL_ID=:actor AND SECURITY_DOMAIN_ID=:domain ')
        if request.cursor is not None:
            query+='AND ASSEMBLY_ID>:cursor '
            params['cursor']=request.cursor
        rows=tx.query(query+'ORDER BY ASSEMBLY_ID '+identity_api._limit_clause('page_limit'),params)
        items=rows[:request.limit]
        return {'items':items,'next_cursor':items[-1]['assembly_id'] if len(rows)>request.limit else None}
    return connection.execute_transaction_callback(perform)


def list_publications(actor,value):
    request=InventoryRequest.model_validate(value)
    def perform(tx):
        from .continuity_publications import _admin
        work._lock_actor(tx,actor)
        _admin(tx,actor,request.security_domain_id)
        params={'domain':request.security_domain_id,'page_limit':request.limit+1}
        query=('SELECT PUBLICATION_ID,FAMILY,ENTITY_ID,SOURCE_REVISION_ID,CONTENT_DIGEST,'
               'TARGET_SECURITY_DOMAIN_ID,PURPOSE,CLASSIFICATION,EXPIRES_AT,STATUS,VERSION '
               'FROM CX_CONTEXT_PUBLICATIONS WHERE SOURCE_SECURITY_DOMAIN_ID=:domain ')
        if request.cursor is not None:
            query+='AND PUBLICATION_ID>:cursor '
            params['cursor']=request.cursor
        rows=tx.query(query+'ORDER BY PUBLICATION_ID '+identity_api._limit_clause('page_limit'),params)
        items=rows[:request.limit]
        return {'items':items,'next_cursor':items[-1]['publication_id'] if len(rows)>request.limit else None}
    return connection.execute_transaction_callback(perform)
