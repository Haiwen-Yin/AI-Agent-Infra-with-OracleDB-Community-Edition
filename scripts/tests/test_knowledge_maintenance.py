"""Knowledge/role repairs preserve custom data and reject stale review."""
import json
import sqlite3

import pytest
from lib import knowledge_maintenance as maintenance


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
      CREATE TABLE ENTITIES(ENTITY_ID TEXT, ENTITY_TYPE TEXT,TITLE TEXT,SUMMARY TEXT,CONTENT TEXT,UPDATED_AT TEXT,VISIBILITY TEXT);
      INSERT INTO ENTITIES VALUES ('k','KNOWLEDGE','old','summary','old facts',NULL,'PRIVATE');
      INSERT INTO ENTITIES VALUES ('custom','KNOWLEDGE','custom','custom','custom facts',NULL,'PRIVATE');
      CREATE TABLE CX_ROLE_TEMPLATES(ROLE_CODE TEXT,PERMISSIONS_JSON TEXT,VERSION INTEGER,UPDATED_AT TEXT);
      INSERT INTO CX_ROLE_TEMPLATES VALUES ('AGENT','["custom.read"]',7,NULL);
      CREATE TABLE EVENTS(ACTION TEXT);
    ''')
    class Tx:
        def query_one(self, sql, params):
            row = conn.execute(sql.replace(' FOR UPDATE', ''), params).fetchone()
            return dict(row) if row else None
        def execute(self, sql, params):
            return conn.execute(sql, params).rowcount
    def transaction(fn):
        with conn:
            return fn(Tx())
    monkeypatch.setattr(maintenance.connection, 'execute_transaction_callback', transaction)
    monkeypatch.setattr(maintenance.identity_api, '_require', lambda *a: None)
    monkeypatch.setattr(maintenance.identity_api, '_audit_tx', lambda tx, actor, action, *a: tx.execute('INSERT INTO EVENTS VALUES(:action)', {'action': action}))
    yield conn
    conn.close()


def plan(db):
    row = {key.lower(): value for key, value in dict(db.execute("SELECT * FROM ENTITIES WHERE ENTITY_ID='k'").fetchone()).items()}
    return [{'entity_id': 'k', 'expected_digest': maintenance.digest(row),
             'title': 'current', 'summary': 'current summary', 'content': 'reviewed facts'}]


def test_refresh_keeps_scope_custom_entities_and_permissions(db):
    maintenance.repair('admin', plan(db), grant_agent_read=True, reason='Reviewed correction')
    assert db.execute("SELECT VISIBILITY FROM ENTITIES WHERE ENTITY_ID='k'").fetchone()[0] == 'PRIVATE'
    assert db.execute("SELECT CONTENT FROM ENTITIES WHERE ENTITY_ID='custom'").fetchone()[0] == 'custom facts'
    permissions, version = db.execute('SELECT PERMISSIONS_JSON,VERSION FROM CX_ROLE_TEMPLATES').fetchone()
    assert json.loads(permissions) == ['custom.read', 'knowledge.read']
    assert version == 8
    assert db.execute('SELECT COUNT(*) FROM EVENTS').fetchone()[0] == 2
    assert not maintenance.repair('admin', [], grant_agent_read=True, reason='Retry')['role_changed']


def test_stale_review_prevents_changes(db):
    reviewed = plan(db)
    db.execute("UPDATE ENTITIES SET CONTENT='edited by user' WHERE ENTITY_ID='k'")
    db.commit()
    with pytest.raises(ValueError, match='changed since review'):
        maintenance.repair('admin', reviewed, grant_agent_read=True, reason='Reviewed correction')
    assert db.execute('SELECT VERSION FROM CX_ROLE_TEMPLATES').fetchone()[0] == 7
    assert db.execute('SELECT COUNT(*) FROM EVENTS').fetchone()[0] == 0


def test_audit_failure_rolls_back(db, monkeypatch):
    def fail(*a):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(maintenance.identity_api, '_audit_tx', fail)
    with pytest.raises(RuntimeError):
        maintenance.repair('admin', plan(db), grant_agent_read=True, reason='Reviewed correction')
    assert db.execute("SELECT CONTENT FROM ENTITIES WHERE ENTITY_ID='k'").fetchone()[0] == 'old facts'
