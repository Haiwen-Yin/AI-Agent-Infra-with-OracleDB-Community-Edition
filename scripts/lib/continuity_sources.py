"""Exact-version continuity source reads; locators never grant authority.

Resolvers run in the caller's transaction. Families without an integrated
versioned reader are rejected explicitly rather than copying ungoverned text.
"""
import json
from contextvars import ContextVar

from .continuity_contracts import SourceRef
from .continuity_state import ContinuityError, ContinuityConflict
from . import continuity_work as work

_resolving=ContextVar('continuity_source_resolution_stack',default=())


def _render(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def resolve(tx, actor, domain, value, *, purpose=None, publication_id=None):
    source=value if isinstance(value,SourceRef) else SourceRef.model_validate(value)
    key=(source.family.value,source.entity_id,source.revision_id)
    stack=_resolving.get()
    if key in stack or len(stack)>=32:
        raise ContinuityError('CYCLIC_SOURCE','Source references contain a cycle or exceed the nesting limit')
    token=_resolving.set(stack+(key,))
    try:
        return _resolve(tx,actor,domain,source,purpose=purpose,publication_id=publication_id)
    finally:
        _resolving.reset(token)


def _resolve(tx,actor,domain,source,*,purpose=None,publication_id=None):
    # Cross-domain access is a separate explicit grant, evaluated for the
    # current recipient. It never substitutes a sender's session identity.
    metadata=locate(tx,source)
    if source.family.value in {'TASK','GRAPH','DB4A2A','AUDIT'}:
        if metadata['security_domain_id']!=domain or publication_id is not None:
            raise PermissionError('Native source snapshots require their original domain')
        from .continuity_native_sources import resolve as native_resolve
        return native_resolve(tx,actor,domain,source)
    if source.family.value=='HANDOFF_OUTCOME':
        if metadata['security_domain_id']!=domain or publication_id is not None:
            raise PermissionError('Outcome evidence is limited to its original domain participants')
        from .continuity_handoff import _read_outcome
        record=_read_outcome(tx,actor,metadata['handoff_id'])
        if str(record['revision_no'])!=source.revision_id or record['content_digest']!=source.content_digest:
            raise ContinuityConflict('STALE_CONTENT','The outcome source revision or digest does not match')
        payload={key:value for key,value in record.items() if key not in {'created_at','content_digest'}}
        return {'source':source.model_dump(mode='json'),'text':_render(payload),
                'content_digest':record['content_digest'],'authorized_scope':domain}
    if metadata['security_domain_id']!=domain or publication_id is not None:
        from .continuity_publications import resolve_publication
        return resolve_publication(tx,actor,domain,source,metadata,purpose=purpose,publication_id=publication_id)
    if source.family.value=='HANDOFF':
        from .continuity_handoff import _read_handoff
        if not source.revision_id.isascii() or not source.revision_id.isdecimal() or str(int(source.revision_id))!=source.revision_id:
            raise ContinuityError('INVALID_REVISION','Handoff revisions require canonical positive integers')
        record=_read_handoff(tx,actor,source.entity_id,int(source.revision_id))
        root=tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_WORK_CONTRACTS WHERE WORK_CONTRACT_ID=:work_id",
                          {'work_id':record['work_contract_id']})
        if root['security_domain_id']!=domain:
            raise PermissionError('An explicit context publication is required')
        if record['expired']:
            raise ContinuityConflict('EXPIRED','The referenced handoff expired')
        if record['content_digest']!=source.content_digest:
            raise ContinuityConflict('STALE_CONTENT','The referenced content digest does not match')
        return {'source':source.model_dump(mode='json'),'text':_render(record['content']),
                'content_digest':record['content_digest'],'authorized_scope':domain}
    if source.family.value=='MEMORY':
        from . import memory_lifecycle as memory
        record=tx.query_one("SELECT * FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:revision AND FAMILY_ID=:family "
                            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
                            {'revision':source.revision_id,'family':source.entity_id})
        if not record:
            raise PermissionError('Source access denied')
        current=tx.query_one("SELECT v.LIFECYCLE_STATE FROM CX_MEMORY_FAMILIES f JOIN CX_MEMORY_VERSIONS v "
                             "ON v.VERSION_ID=f.CURRENT_VERSION_ID WHERE f.FAMILY_ID=:family",{'family':source.entity_id})
        if not current or current['lifecycle_state'] not in memory.ORDINARY_VISIBLE_STATES:
            raise PermissionError('Source access denied')
        try:
            memory._require_memory_access(actor,record,purpose='RUNTIME_CONTEXT')
        except memory.MemoryLifecycleError as exc:
            raise PermissionError('Source access denied') from exc
        if record.get('security_domain_id')!=domain:
            raise PermissionError('An explicit context publication is required')
        work._authorize(tx,actor,domain,write=False)
        if record['content_digest']!=source.content_digest:
            raise ContinuityConflict('STALE_CONTENT','The referenced content digest does not match')
        def text(value):
            return value.read() if hasattr(value,'read') else value
        fields={name:text(record[name]) for name in ['title','body_text','memory_type','memory_scope','classification']}
        actual=memory._digest(*(fields[name] for name in ['title','body_text','memory_type','memory_scope','classification']))
        if actual!=source.content_digest:
            raise ContinuityError('INTEGRITY_ERROR','Stored source failed integrity validation')
        return {'source':source.model_dump(mode='json'),'text':_render(fields),
                'content_digest':actual,'authorized_scope':domain}
    if source.family.value in {'KNOWLEDGE','EXPERIENCE','SKILL'}:
        from .continuity_promotions import resolve_artifact
        return resolve_artifact(tx,actor,domain,source)
    raise ContinuityError('SOURCE_RESOLVER_UNAVAILABLE','This source family has no integrated exact-version reader')


def locate(tx,source):
    """Read locator metadata only; callers must authorize before body access."""
    family=source.family.value
    if family in {'TASK','GRAPH','DB4A2A','AUDIT'}:
        from .continuity_native_sources import locate as native_locate
        row=native_locate(tx,source)
    elif family=='MEMORY':
        row=tx.query_one("SELECT v.SECURITY_DOMAIN_ID,v.OWNER_PRINCIPAL_ID,v.CLASSIFICATION FROM CX_MEMORY_VERSIONS v "
                         "WHERE v.FAMILY_ID=:entity AND v.VERSION_ID=:revision",{'entity':source.entity_id,'revision':source.revision_id})
    elif family=='HANDOFF_OUTCOME':
        row=tx.query_one("SELECT w.SECURITY_DOMAIN_ID,o.SUBMITTED_BY AS OWNER_PRINCIPAL_ID,d.CLASSIFICATION,h.HANDOFF_ID "
                         "FROM CX_HANDOFF_OUTCOMES o JOIN CX_HANDOFFS h ON h.HANDOFF_ID=o.HANDOFF_ID "
                         "JOIN CX_WORK_CONTRACTS w ON w.WORK_CONTRACT_ID=h.WORK_CONTRACT_ID "
                         "JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID=w.SECURITY_DOMAIN_ID WHERE o.OUTCOME_ID=:entity",
                         {'entity':source.entity_id})
    elif family=='HANDOFF':
        row=tx.query_one("SELECT w.SECURITY_DOMAIN_ID,h.FROM_PRINCIPAL_ID AS OWNER_PRINCIPAL_ID,d.CLASSIFICATION "
                         "FROM CX_HANDOFFS h JOIN CX_WORK_CONTRACTS w ON w.WORK_CONTRACT_ID=h.WORK_CONTRACT_ID "
                         "JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID=w.SECURITY_DOMAIN_ID WHERE h.HANDOFF_ID=:entity",
                         {'entity':source.entity_id})
    elif family in {'KNOWLEDGE','EXPERIENCE','SKILL'}:
        row=tx.query_one("SELECT a.SECURITY_DOMAIN_ID,a.OWNER_PRINCIPAL_ID,d.CLASSIFICATION FROM CX_CONTINUITY_ARTIFACTS a "
                         "JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID=a.SECURITY_DOMAIN_ID "
                         "WHERE a.ARTIFACT_ID=:entity AND a.FAMILY=:family AND a.STATUS='ACTIVE'",
                         {'entity':source.entity_id,'family':family})
    else:
        raise ContinuityError('SOURCE_RESOLVER_UNAVAILABLE','This source family has no integrated exact-version reader')
    if not row or not row['security_domain_id'] or not row['owner_principal_id']:
        raise PermissionError('Source access denied')
    return row


def publication_payload(tx,source,domain,*,actor):
    """Reconstruct an exact source only after explicit publication authorization."""
    if source.family.value=='HANDOFF':
        from .continuity_handoff import _handoff_payload
        if not source.revision_id.isascii() or not source.revision_id.isdecimal() or str(int(source.revision_id))!=source.revision_id:
            raise ContinuityError('INVALID_REVISION','Invalid Handoff revision')
        row=tx.query_one("SELECT * FROM CX_HANDOFFS WHERE HANDOFF_ID=:entity",{'entity':source.entity_id})
        if not row:
            raise PermissionError('Source access denied')
        record=_handoff_payload(tx,row,int(source.revision_id),actor=actor,domain=domain)
        if record['expired']:
            raise ContinuityConflict('EXPIRED','Published source expired')
        if record['content_digest']!=source.content_digest:
            raise ContinuityConflict('STALE_CONTENT','Published source changed')
        return {'source':source.model_dump(mode='json'),'text':_render(record['content']),'content_digest':source.content_digest,'authorized_scope':domain}
    if source.family.value=='MEMORY':
        from . import memory_lifecycle as memory
        record=tx.query_one("SELECT v.* FROM CX_MEMORY_VERSIONS v JOIN CX_MEMORY_FAMILIES f ON f.FAMILY_ID=v.FAMILY_ID "
                            "JOIN CX_MEMORY_VERSIONS current_v ON current_v.VERSION_ID=f.CURRENT_VERSION_ID "
                            "WHERE v.FAMILY_ID=:entity AND v.VERSION_ID=:revision AND v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED') "
                            "AND current_v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED') "
                            "AND (v.VALID_UNTIL IS NULL OR v.VALID_UNTIL>CURRENT_TIMESTAMP)",{'entity':source.entity_id,'revision':source.revision_id})
        if not record:
            raise PermissionError('Source access denied')
        fields={key:(record[key].read() if hasattr(record[key],'read') else record[key]) for key in ['title','body_text','memory_type','memory_scope','classification']}
        digest=memory._digest(*(fields[key] for key in ['title','body_text','memory_type','memory_scope','classification']))
        if digest!=source.content_digest or record['content_digest']!=source.content_digest:
            raise ContinuityError('INTEGRITY_ERROR','Published source failed integrity validation')
        return {'source':source.model_dump(mode='json'),'text':_render(fields),'content_digest':digest,'authorized_scope':domain}
    from .continuity_promotions import _artifact_payload
    return _artifact_payload(tx,source,domain)
