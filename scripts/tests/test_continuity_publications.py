"""Cross-domain publication authority, exact grants, purpose and revocation."""
from datetime import datetime,timedelta,timezone

import pytest

from lib import continuity_publications as pubs,continuity_assembly as assembly,continuity_handoff as handoff
from lib import continuity_sources as sources
from lib.continuity_state import ContinuityConflict
from .test_continuity_work import database
from .test_continuity_handoff import fixture,offer_request
from .test_continuity_handoff import decision
from .test_continuity_work import request as work_request
from .test_continuity_assembly import context_db


@pytest.fixture
def publication_db(context_db):
    db,wid=context_db
    for sql in pubs.schema_statements('pg'):
        db.execute(sql)
    db.execute("INSERT INTO CX_SECURITY_DOMAINS VALUES('target','ACTIVE','INTERNAL')")
    db.execute("INSERT INTO CX_DOMAIN_MEMBERS VALUES('target','owner','ACTIVE','OWNER',NULL)")
    db.execute("INSERT INTO CX_DOMAIN_MEMBERS VALUES('target','outsider','ACTIVE','MEMBER',NULL)")
    db.commit()
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    source=dict(family='HANDOFF',entity_id=hid,revision_id='1',content_digest=handoff.read_handoff('owner',hid)['content_digest'])
    return db,source


def publication(source,key='publication',**kwargs):
    return dict(source=source,target_security_domain_id='target',purpose='ACCEPTANCE',classification='INTERNAL',
                expires_at=datetime.now(timezone.utc)+timedelta(hours=1),reason='Explicit source sharing',idempotency_key=key,**kwargs)


def prepare(source,key='assembly',purpose='ACCEPTANCE'):
    return assembly.assemble('outsider',dict(request_id=key,security_domain_id='target',sources=[source],purpose=purpose,idempotency_key=key))


def test_no_cross_domain_access_without_grant_or_with_wrong_purpose(publication_db):
    db,source=publication_db
    with pytest.raises(PermissionError):
        prepare(source)
    request=publication(source)
    created=pubs.publish('owner',request)
    assert pubs.publish('owner',request)['replayed']
    result=prepare(source)
    assert result['item_count']==1
    assert db.execute('SELECT PUBLICATION_ID FROM CX_CONTEXT_ITEM_GRANTS').fetchone()[0]==created['publication_id']
    with pytest.raises(PermissionError):
        prepare(source,'wrong-purpose','UNRELATED_PURPOSE')
    with pytest.raises(PermissionError):
        handoff.read_handoff('outsider',source['entity_id'])


def test_revocation_invalidates_prepared_context_and_pins_original_grant(publication_db):
    db,source=publication_db
    created=pubs.publish('owner',publication(source))
    prepared=prepare(source)
    request=dict(expected_version=1,reason='Revoke exact grant',idempotency_key='revoke')
    assert pubs.revoke('owner',created['publication_id'],request)['version']==2
    assert pubs.revoke('owner',created['publication_id'],request)['replayed']
    with pytest.raises(PermissionError):
        assembly.read_assembly('outsider',prepared['assembly_id'])
    pubs.publish('owner',publication(source,'new-grant'))
    assert prepare(source,'new-assembly')['item_count']==1
    with pytest.raises(PermissionError):
        assembly.read_assembly('outsider',prepared['assembly_id'])


@pytest.mark.parametrize('mutation',[
    "UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner' AND SECURITY_DOMAIN_ID='domain'",
    "UPDATE CX_PRINCIPALS SET STATUS='DISABLED' WHERE PRINCIPAL_ID='owner'",
    "UPDATE CX_SECURITY_DOMAINS SET STATUS='SUSPENDED' WHERE SECURITY_DOMAIN_ID='domain'",
    "UPDATE CX_CONTEXT_PUBLICATIONS SET EXPIRES_AT='2000-01-01 00:00:00'",
])
def test_publisher_and_source_authority_rechecked_on_every_read(publication_db,mutation):
    db,source=publication_db
    pubs.publish('owner',publication(source))
    prepared=prepare(source)
    db.execute(mutation)
    db.commit()
    with pytest.raises(PermissionError):
        assembly.read_assembly('outsider',prepared['assembly_id'])


def test_reader_cannot_republish_and_classification_cannot_be_downgraded(publication_db):
    db,source=publication_db
    with pytest.raises(PermissionError):
        pubs.publish('agent',publication(source))
    with pytest.raises(PermissionError):
        pubs.publish('owner',dict(publication(source),classification='PUBLIC'))
    db.execute("UPDATE CX_SECURITY_DOMAINS SET CLASSIFICATION='PUBLIC' WHERE SECURITY_DOMAIN_ID='target'")
    db.commit()
    with pytest.raises(PermissionError):
        pubs.publish('owner',publication(source))
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_PUBLICATIONS').fetchone()[0]==0


def test_publication_and_audit_rollback_together(publication_db,monkeypatch):
    db,source=publication_db
    def fail(*args):
        raise RuntimeError('Audit failed')
    monkeypatch.setattr(pubs.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        pubs.publish('owner',publication(source))
    assert db.execute('SELECT COUNT(*) FROM CX_CONTEXT_PUBLICATIONS').fetchone()[0]==0
    assert db.execute('SELECT COUNT(*) FROM CX_PUBLICATION_EVENTS').fetchone()[0]==0


def test_outcome_pins_publication_and_never_substitutes_a_replacement(publication_db):
    from lib import continuity_work as work
    db,source=publication_db
    db.execute("UPDATE CX_PRINCIPALS SET PRINCIPAL_TYPE='AGENT' WHERE PRINCIPAL_ID='outsider'")
    db.commit()
    wid=work.create_work('owner',dict(work_request('target-work'),security_domain_id='target'))['work_contract_id']
    offered=offer_request('target-offer')
    offered.update(recipient_principal_id='outsider',content=dict(summary='Target-domain work',next_actions=[dict(
        action_id='one',description='Verify published evidence',responsible_principal_id='outsider',acceptance='Exact evidence')]))
    hid=handoff.offer('owner',wid,offered)['handoff_id']
    handoff.decide('outsider',hid,decision())
    handoff.decide('outsider',hid,decision(2,'IN_PROGRESS','start'))
    outcome=dict(expected_version=3,expected_revision_no=1,result='COMPLETED',summary='Published evidence verified',
                 satisfied_criteria=['one'],evidence=[source],reason='Observed result',idempotency_key='outcome')
    with pytest.raises(PermissionError):
        handoff.submit_outcome('outsider',hid,outcome)
    grant=pubs.publish('owner',dict(publication(source),purpose='HANDOFF_OUTCOME'))
    handoff.submit_outcome('outsider',hid,outcome)
    assert handoff.read_outcome('outsider',hid)['evidence']==[source]
    assert db.execute('SELECT PUBLICATION_ID FROM CX_HANDOFF_OUTCOME_EVIDENCE').fetchone()[0]==grant['publication_id']
    pubs.revoke('owner',grant['publication_id'],dict(expected_version=1,reason='Revocation',idempotency_key='revoke'))
    pubs.publish('owner',dict(publication(source,'replacement'),purpose='HANDOFF_OUTCOME'))
    with pytest.raises(PermissionError):
        handoff.read_outcome('outsider',hid)


def test_publication_query_binds_match_selected_sql(publication_db,monkeypatch):
    """Oracle/Yashan reject unused binds that PostgreSQL/SQLite tolerate."""
    import re
    db,source=publication_db
    execute=pubs.connection.execute_transaction_callback
    def strict_transaction(callback):
        def checked(tx):
            original=tx.query
            def query(sql,params):
                assert set(re.findall(r':([a-z_]+)',sql))==set(params)
                return original(sql,params)
            tx.query=query
            return callback(tx)
        return execute(checked)
    monkeypatch.setattr(pubs.connection,'execute_transaction_callback',strict_transaction)
    pubs.publish('owner',publication(source))
    result=prepare(source)
    assert assembly.read_assembly('outsider',result['assembly_id'])['item_count']==1
