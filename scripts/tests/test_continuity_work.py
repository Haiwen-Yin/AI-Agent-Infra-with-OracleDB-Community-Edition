"""Transactional work service tests; SQLite is a unit harness, not adapter acceptance."""
import sqlite3

import pytest

from lib import continuity_work as work
from lib.continuity_state import ContinuityError, ContinuityConflict


@pytest.fixture
def database(monkeypatch):
    db = sqlite3.connect(':memory:',check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
        CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT PRIMARY KEY,STATUS TEXT);
        CREATE TABLE CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID TEXT PRIMARY KEY,STATUS TEXT);
        CREATE TABLE CX_DOMAIN_MEMBERS(SECURITY_DOMAIN_ID TEXT,PRINCIPAL_ID TEXT,STATUS TEXT,MEMBERSHIP_TIER TEXT,VALID_UNTIL TIMESTAMP);
        CREATE TABLE AUDIT(WORK_ID TEXT,ACTOR TEXT,ACTION TEXT);
        INSERT INTO CX_PRINCIPALS VALUES('owner','ACTIVE'),('reader','ACTIVE'),('outsider','ACTIVE');
        INSERT INTO CX_SECURITY_DOMAINS VALUES('domain','ACTIVE');
        INSERT INTO CX_DOMAIN_MEMBERS VALUES('domain','owner','ACTIVE','OWNER',NULL),('domain','reader','ACTIVE','VIEWER',NULL);
    ''')
    db.execute("ALTER TABLE CX_SECURITY_DOMAINS ADD COLUMN CLASSIFICATION TEXT DEFAULT 'INTERNAL'")
    for statement in work.schema_statements('pg'):
        db.execute(statement)
    from lib.continuity_execution_links import schema_statements
    for statement in schema_statements('pg'):
        db.execute(statement)
    from lib.continuity_policy import schema_statements
    for statement in schema_statements('pg'):
        db.execute(statement)
    from lib.continuity_native_sources import schema_statements
    for statement in schema_statements('pg'):
        db.execute(statement)
    db.commit()
    class Transaction:
        def execute(self, statement, params):
            return db.execute(statement.replace(' FOR UPDATE', ''), params).rowcount
        def query(self, statement, params):
            return [{key.lower(): row[key] for key in row.keys()}
                    for row in db.execute(statement.replace(' FOR UPDATE', ''), params)]
        def query_one(self, statement, params):
            rows = self.query(statement, params)
            return rows[0] if rows else None
    def transaction(callback):
        try:
            result = callback(Transaction())
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
    monkeypatch.setattr(work.connection, 'execute_transaction_callback', transaction)
    # This fixture executes SQLite SQL even inside a vendor package. Native
    # scalar SELECT syntax is exercised separately by six-database gates.
    monkeypatch.setattr(work.connection, 'scalar_select_suffix', lambda: '')
    monkeypatch.setattr(work.identity_api, 'effective_access', lambda *args, **kwargs: {'decision':'ALLOW'})
    def audit(tx, actor, action, family, resource, outcome, reason):
        tx.execute('INSERT INTO AUDIT VALUES(:resource,:actor,:action)', {'resource':resource,'actor':actor,'action':action})
    monkeypatch.setattr(work.identity_api, '_audit_tx', audit)
    yield db
    db.close()


def request(key='first', objective='finish task'):
    return dict(security_domain_id='domain', owner_principal_id='owner', reason='test', idempotency_key=key,
        content=dict(objective=objective, criteria=[dict(criterion_id='one',description='success',verification='live test')],
                     constraints=['preserve existing data']))


def test_create_read_and_exact_historical_revision(database):
    created = work.create_work('owner', request())
    value = work.read_work('reader', created['work_contract_id'])
    assert value['content']['objective'] == 'finish task'
    revised = work.revise_work('owner', created['work_contract_id'], dict(expected_version=1,
        content=request(objective='updated task')['content'], reason='update', idempotency_key='update'))
    assert revised['version'] == 2
    assert work.read_work('owner', created['work_contract_id'])['content']['objective'] == 'updated task'
    assert work.read_work('owner', created['work_contract_id'], 1)['content']['objective'] == 'finish task'
    assert database.execute('SELECT COUNT(*) FROM AUDIT').fetchone()[0] == 2


def test_stale_revision_and_same_key_different_content_are_rejected(database):
    created = work.create_work('owner', request())
    assert work.create_work('owner', request())['replayed']
    with pytest.raises(ContinuityConflict):
        work.create_work('owner', request(objective='different'))
    change = dict(expected_version=1, content=request()['content'], reason='revise', idempotency_key='revise')
    work.revise_work('owner', created['work_contract_id'], change)
    assert work.revise_work('owner', created['work_contract_id'], change)['replayed']
    with pytest.raises(ContinuityConflict):
        work.revise_work('owner', created['work_contract_id'], dict(change, idempotency_key='stale'))
    assert database.execute('SELECT COUNT(*) FROM CX_WORK_REVISIONS').fetchone()[0] == 2


def test_retry_and_read_recheck_current_authority(database):
    created = work.create_work('owner', request())
    with pytest.raises(PermissionError):
        work.read_work('outsider', created['work_contract_id'])
    database.execute("UPDATE CX_DOMAIN_MEMBERS SET STATUS='REVOKED' WHERE PRINCIPAL_ID='owner'")
    database.commit()
    with pytest.raises(PermissionError):
        work.create_work('owner', request())
    with pytest.raises(PermissionError):
        work.read_work('owner', created['work_contract_id'])


def test_revision_and_audit_commit_or_rollback_together(database, monkeypatch):
    created = work.create_work('owner', request())
    def fail(*args):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(work.identity_api, '_audit_tx', fail)
    with pytest.raises(RuntimeError):
        work.revise_work('owner', created['work_contract_id'], dict(expected_version=1,
            content=request(objective='must roll back')['content'], reason='revise', idempotency_key='failure'))
    assert work.read_work('owner', created['work_contract_id'])['version'] == 1
    assert database.execute('SELECT COUNT(*) FROM CX_WORK_REVISIONS').fetchone()[0] == 1
    assert database.execute('SELECT COUNT(*) FROM CX_WORK_REQUESTS').fetchone()[0] == 1


def test_no_unverified_sources_or_unrelated_owner_assignment(database):
    value = request()
    value['content']['sources'] = [dict(family='GRAPH', entity_id='secret', revision_id='r1', content_digest='a'*64)]
    with pytest.raises(PermissionError, match='Source access denied'):
        work.create_work('owner', value)
    assert database.execute('SELECT COUNT(*) FROM CX_WORK_CONTRACTS').fetchone()[0] == 0
    with pytest.raises(PermissionError):
        work.create_work('owner', dict(request(), owner_principal_id='outsider'))


def test_corrupt_revision_is_not_returned_as_valid_content(database):
    created = work.create_work('owner', request())
    database.execute("UPDATE CX_WORK_REVISIONS SET OBJECTIVE='tampered'")
    database.commit()
    with pytest.raises(ContinuityError, match='integrity'):
        work.read_work('owner', created['work_contract_id'])


def test_work_state_versions_history_and_terminal_guard(database):
    wid = work.create_work('owner', request())['work_contract_id']
    value = dict(expected_version=1,status='IN_PROGRESS',reason='start',idempotency_key='start')
    assert work.change_work_state('owner',wid,value)['version']==2
    assert work.change_work_state('owner',wid,value)['replayed']
    assert work.read_work('owner',wid,1)['revision_status']=='OPEN'
    assert work.read_work('owner',wid)['revision_status']=='IN_PROGRESS'
    work.change_work_state('owner',wid,dict(value,expected_version=2,status='COMPLETED',idempotency_key='done'))
    with pytest.raises(ContinuityConflict):
        work.change_work_state('owner',wid,dict(value,expected_version=3,idempotency_key='reopen'))
