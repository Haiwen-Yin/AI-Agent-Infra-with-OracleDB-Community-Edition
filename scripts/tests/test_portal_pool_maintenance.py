"""Explicit pool repair preserves occupied, external and revoked identities."""
import sqlite3
import pytest
from lib import portal_pool_maintenance as pool


@pytest.fixture
def db(monkeypatch):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE AGENT_REGISTRY(AGENT_ID TEXT PRIMARY KEY,AGENT_NAME TEXT,AGENT_TYPE TEXT,STATUS TEXT,CURRENT_USER_ID TEXT,PORTAL_NODE_ID TEXT);
      CREATE TABLE AGENT_REGISTRATIONS(AGENT_ID TEXT PRIMARY KEY,STATUS TEXT);
      CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT PRIMARY KEY,PRINCIPAL_TYPE TEXT,DISPLAY_NAME TEXT,STATUS TEXT,PERMISSION_VERSION INTEGER);
      CREATE TABLE AUDIT(AGENT_ID TEXT);
      INSERT INTO AGENT_REGISTRY VALUES ('pool','Portal helper','PORTAL_MANAGED','POOL',NULL,NULL);
      INSERT INTO AGENT_REGISTRATIONS VALUES ('pool','ACTIVE');
    ''')
    class Tx:
        def query_one(self, sql, params):
            row = db.execute(sql.replace(' FOR UPDATE', ''), params).fetchone()
            return dict(row) if row else None
        def execute(self, sql, params):
            return db.execute(sql, params).rowcount
    def transaction(fn):
        with db:
            return fn(Tx())
    monkeypatch.setattr(pool.connection, 'execute_transaction_callback', transaction)
    monkeypatch.setattr(pool.identity_api, '_require', lambda *_: None)
    monkeypatch.setattr(pool.identity_api, '_audit_tx', lambda tx, actor, action, kind, key, outcome, reason:
                        tx.execute('INSERT INTO AUDIT VALUES (:id)', {'id': key}))
    yield db
    db.close()


def test_explicit_adoption_is_audited_and_idempotent(db):
    assert pool.adopt_idle_agents('admin', ['pool'], 'repair legacy pool')['adopted'] == ['pool']
    assert pool.adopt_idle_agents('admin', ['pool'], 'repeat repair')['adopted'] == []
    assert db.execute('SELECT COUNT(*) FROM AUDIT').fetchone()[0] == 1
    assert db.execute('SELECT STATUS FROM AGENT_REGISTRY').fetchone()[0] == 'POOL'


@pytest.mark.parametrize('change', [
    "UPDATE AGENT_REGISTRY SET AGENT_TYPE='external-skill'",
    "UPDATE AGENT_REGISTRY SET STATUS='ACTIVE'",
    "UPDATE AGENT_REGISTRY SET CURRENT_USER_ID='user'",
    "UPDATE AGENT_REGISTRY SET PORTAL_NODE_ID='other-node'",
    "UPDATE AGENT_REGISTRATIONS SET STATUS='DISABLED'",
    "DELETE FROM AGENT_REGISTRATIONS",
    "INSERT INTO CX_PRINCIPALS VALUES ('pool','AGENT','revoked','DISABLED',1)",
    "INSERT INTO CX_PRINCIPALS VALUES ('pool','HUMAN','conflict','ACTIVE',1)",
])
def test_ineligible_pool_entry_is_not_adopted(db, change):
    db.execute(change)
    with pytest.raises(ValueError):
        pool.adopt_idle_agents('admin', ['pool'], 'repair request')
    assert db.execute('SELECT COUNT(*) FROM AUDIT').fetchone()[0] == 0


def test_invalid_later_target_rolls_back_entire_batch(db):
    with pytest.raises(ValueError):
        pool.adopt_idle_agents('admin', ['pool', 'zz_missing'], 'repair request')
    assert db.execute('SELECT COUNT(*) FROM CX_PRINCIPALS').fetchone()[0] == 0


def test_unauthorized_operator_cannot_adopt(db, monkeypatch):
    def deny(*args):
        raise PermissionError('denied')
    monkeypatch.setattr(pool.identity_api, '_require', deny)
    with pytest.raises(PermissionError):
        pool.adopt_idle_agents('ordinary-user', ['pool'], 'repair request')
    assert db.execute('SELECT COUNT(*) FROM CX_PRINCIPALS').fetchone()[0] == 0
