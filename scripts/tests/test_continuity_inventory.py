"""Inventories expose participant metadata without bypassing source reads."""
import pytest

from lib import continuity_inventory as inventory,continuity_work as work,continuity_handoff as handoff
from .test_continuity_work import database,request
from .test_continuity_handoff import fixture,offer_request
from .test_continuity_candidates import candidate_db,new_candidate,PROPOSALS
from .test_continuity_assembly import context_db,assembly_request
from .test_continuity_publications import publication_db,publication


@pytest.fixture
def inventory_db(fixture,monkeypatch):
    monkeypatch.setattr(inventory.identity_api,'_limit_clause',lambda name: 'LIMIT :'+name)
    return fixture


def test_inventory_is_owned_bounded_and_contains_no_body(inventory_db):
    db,wid=inventory_db
    second=work.create_work('owner',request('second',objective='Confidential objective'))['work_contract_id']
    first=inventory.list_work('owner',{'security_domain_id':'domain','limit':1})
    assert len(first['items'])==1 and first['next_cursor']
    next_page=inventory.list_work('owner',{'security_domain_id':'domain','limit':1,'cursor':first['next_cursor']})
    assert len(next_page['items'])==1 and next_page['next_cursor'] is None
    assert {first['items'][0]['work_contract_id'],next_page['items'][0]['work_contract_id']}=={wid,second}
    assert 'objective' not in str(first) and 'Confidential' not in str(next_page)
    assert inventory.list_work('reader',{'security_domain_id':'domain'})['items']==[]


def test_handoff_inventory_requires_current_participation_and_domain(inventory_db):
    db,wid=inventory_db
    hid=handoff.offer('owner',wid,offer_request())['handoff_id']
    assert inventory.list_handoffs('agent',{'security_domain_id':'domain'})['items'][0]['handoff_id']==hid
    assert inventory.list_handoffs('reader',{'security_domain_id':'domain'})['items']==[]
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='agent'")
    db.commit()
    with pytest.raises(PermissionError):
        inventory.list_handoffs('agent',{'security_domain_id':'domain'})


def test_inventory_cannot_take_another_identity_or_unbounded_limit(inventory_db):
    from pydantic import ValidationError
    for value in ({'principal_id':'owner'},{'limit':10000},{'limit':0}):
        with pytest.raises(ValidationError):
            inventory.list_work('reader',dict(security_domain_id='domain',**value))


def test_domain_and_recipient_choices_use_current_membership_without_channels(inventory_db,monkeypatch):
    db,_=inventory_db
    db.execute("ALTER TABLE CX_SECURITY_DOMAINS ADD COLUMN DOMAIN_NAME TEXT DEFAULT 'Test domain'")
    db.execute("ALTER TABLE CX_PRINCIPALS ADD COLUMN DISPLAY_NAME TEXT DEFAULT 'Test principal'")
    db.commit()
    actions=[]
    def authorize(actor,action,**kwargs):
        actions.append(action)
        return {'decision':'ALLOW' if action=='workspaces.read' else 'DENY'}
    monkeypatch.setattr(inventory.identity_api,'effective_access',authorize)
    assert inventory.list_domains('reader',{})['items'][0]['security_domain_id']=='domain'
    assert inventory.list_domains('outsider',{})['items']==[]
    result=inventory.list_recipients('reader',{'security_domain_id':'domain','limit':1})
    assert len(result['items'])==1 and result['next_cursor']
    result2=inventory.list_recipients('reader',{'security_domain_id':'domain','limit':1,'cursor':result['next_cursor']})
    assert {result['items'][0]['principal_id'],result2['items'][0]['principal_id']}=={'owner','agent'}
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET VALID_UNTIL='2000-01-01' WHERE PRINCIPAL_ID='agent'")
    db.commit()
    assert [x['principal_id'] for x in inventory.list_recipients('reader',{'security_domain_id':'domain'})['items']]==['owner']
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='reader'")
    db.commit()
    assert inventory.list_domains('reader',{})['items']==[]
    with pytest.raises(PermissionError):
        inventory.list_recipients('reader',{'security_domain_id':'domain'})
    assert set(actions)=={'workspaces.read'}


def test_candidate_inventory_checks_current_family_review_authority(candidate_db,monkeypatch):
    from lib import continuity_candidates as candidates
    db,source=candidate_db
    monkeypatch.setattr(inventory.identity_api,'_limit_clause',lambda name:'LIMIT :'+name)
    first=candidates.create_candidate('owner',new_candidate(source,PROPOSALS[0],key='memory'))['candidate_id']
    second=candidates.create_candidate('owner',new_candidate(source,PROPOSALS[3],key='skill'))['candidate_id']
    def access(actor,action,**kwargs):
        return {'decision':'DENY' if actor=='agent' and action=='skills.write' else 'ALLOW'}
    monkeypatch.setattr(inventory.identity_api,'effective_access',access)
    request={'security_domain_id':'domain','limit':1}
    owner=inventory.list_candidates('owner',request)
    assert len(owner['items'])==1 and owner['next_cursor']
    tail=inventory.list_candidates('owner',dict(request,cursor=owner['next_cursor']))
    assert {owner['items'][0]['candidate_id'],tail['items'][0]['candidate_id']}=={first,second}
    reviewer=inventory.list_candidates('agent',request)
    assert [item['candidate_id'] for item in reviewer['items']]==[first]
    assert reviewer['next_cursor'] is None
    assert 'payload' not in str(reviewer) and 'title' not in str(reviewer)
    assert inventory.list_candidates('reader',request)['items']==[]
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET MEMBERSHIP_TIER='MEMBER' WHERE PRINCIPAL_ID='agent'")
    db.commit()
    assert inventory.list_candidates('agent',request)['items']==[]
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        inventory.list_candidates('owner',request)


def test_assembly_inventory_excludes_other_principals_and_retains_expired_metadata(context_db,monkeypatch):
    from lib import continuity_assembly as assembly
    db,wid=context_db
    monkeypatch.setattr(inventory.identity_api,'_limit_clause',lambda name:'LIMIT :'+name)
    value=assembly.assemble('owner',assembly_request(wid))
    request={'security_domain_id':'domain'}
    assert inventory.list_assemblies('agent',request)['items']==[]
    db.execute("UPDATE CX_CONTEXT_ASSEMBLIES SET EXPIRES_AT='2000-01-01'")
    db.commit()
    result=inventory.list_assemblies('owner',request)
    assert result['items'][0]['assembly_id']==value['assembly_id']
    assert 'text' not in result['items'][0] and 'items' not in result['items'][0]
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        inventory.list_assemblies('owner',request)


def test_publication_inventory_requires_source_domain_administration(publication_db,monkeypatch):
    from lib import continuity_publications as pubs
    db,source=publication_db
    monkeypatch.setattr(inventory.identity_api,'_limit_clause',lambda name:'LIMIT :'+name)
    value=pubs.publish('owner',publication(source))
    result=inventory.list_publications('owner',{'security_domain_id':'domain'})
    assert result['items'][0]['publication_id']==value['publication_id']
    assert result['items'][0]['version']==1 and 'summary' not in str(result)
    for actor in ('agent','reader','outsider'):
        with pytest.raises(PermissionError):
            inventory.list_publications(actor,{'security_domain_id':'domain'})
    pubs.revoke('owner',value['publication_id'],dict(expected_version=1,reason='Stop grant',idempotency_key='revoke'))
    row=inventory.list_publications('owner',{'security_domain_id':'domain'})['items'][0]
    assert row['status']=='REVOKED' and row['version']==2
    db.execute("UPDATE CX_DOMAIN_MEMBERS SET MEMBERSHIP_TIER='MEMBER' WHERE PRINCIPAL_ID='owner'")
    db.commit()
    with pytest.raises(PermissionError):
        inventory.list_publications('owner',{'security_domain_id':'domain'})
