"""Selection must not turn name lookup into a directory or domain-access bypass."""
import sqlite3
import pytest
from lib import identity_api as identity


@pytest.fixture
def catalog(monkeypatch):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT,PRINCIPAL_TYPE TEXT,DISPLAY_NAME TEXT,STATUS TEXT);
      CREATE TABLE CX_HUMAN_IDENTITIES(PRINCIPAL_ID TEXT,IDENTITY_TYPE TEXT,USERNAME TEXT,STATUS TEXT);
      CREATE TABLE CX_DOMAIN_MEMBERS(PRINCIPAL_ID TEXT,SECURITY_DOMAIN_ID TEXT,STATUS TEXT,VALID_UNTIL TEXT);
      CREATE TABLE CX_CHANNEL_MEMBERS(PRINCIPAL_ID TEXT,CHANNEL_ID TEXT,STATUS TEXT,VALID_UNTIL TEXT);
      INSERT INTO CX_PRINCIPALS VALUES ('self','HUMAN','Owner','ACTIVE'),('h','HUMAN','Same name','ACTIVE'),
        ('a','AGENT','Same name','ACTIVE'),('expired','AGENT','Expired','ACTIVE'),('disabled','AGENT','Disabled','DISABLED');
      INSERT INTO CX_HUMAN_IDENTITIES VALUES ('self','LOCAL','owner','ACTIVE'),('h','LOCAL','same_user','ACTIVE');
      INSERT INTO CX_DOMAIN_MEMBERS VALUES ('a','d','ACTIVE',NULL),('h','other','ACTIVE',NULL),
        ('expired','d','ACTIVE','2000-01-01'),('disabled','d','ACTIVE',NULL);
    ''')
    monkeypatch.setattr(identity, '_limit_clause', lambda: 'LIMIT :limit')
    monkeypatch.setattr(identity, '_required_query', lambda sql, params: [
        {key.lower(): row[key] for key in row.keys()} for row in db.execute(sql, params)])
    monkeypatch.setattr(identity, 'effective_access', lambda *_: {'decision': 'DENY'})
    yield db
    db.close()


def test_no_read_permission_only_exposes_self(catalog):
    assert [r['principal_id'] for r in identity.principal_options('self')['items']] == ['self']
    assert identity.principal_options('self', kind='AGENT')['items'] == []


def test_channel_names_do_not_bypass_domain_or_expiry(catalog, monkeypatch):
    monkeypatch.setattr(identity, '_assert_channel_member', lambda *args: {'security_domain_id': 'd'})
    result = identity.principal_options('self', channel_id='c', query='Same name')
    assert [r['principal_id'] for r in result['items']] == ['a']
    catalog.execute("INSERT INTO CX_CHANNEL_MEMBERS VALUES ('a','c','ACTIVE',NULL)")
    assert identity.principal_options('self', channel_id='c')['items'] == []


def test_channel_authorization_precedes_lookup(catalog, monkeypatch):
    def deny(*args):
        raise PermissionError('not a channel manager')
    monkeypatch.setattr(identity, '_assert_channel_member', deny)
    with pytest.raises(PermissionError):
        identity.principal_options('self', channel_id='secret')


def test_search_treats_wildcards_as_literal_and_preserves_ids(catalog, monkeypatch):
    monkeypatch.setattr(identity, 'effective_access', lambda *_: {'decision': 'ALLOW'})
    monkeypatch.setattr(identity, '_principal_visibility_clause', lambda *_: '1=1')
    monkeypatch.setattr(identity, '_agent_visibility_clause', lambda *_: '1=1')
    assert identity.principal_options('self', query='%')['items'] == []
    assert identity.principal_options('self', query='same_user')['items'][0]['principal_id'] == 'h'
    assert identity.principal_options('self', query='Same name', kind='AGENT')['items'][0]['principal_id'] == 'a'
