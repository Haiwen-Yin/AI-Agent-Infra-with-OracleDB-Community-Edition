"""Exact memory lineage and body checks cannot be bypassed by a source pointer."""
import pytest

from lib import continuity_sources as sources, memory_lifecycle as memory
from lib.continuity_state import ContinuityError
from .test_continuity_work import database


@pytest.fixture
def memory_source(database,monkeypatch):
    db=database
    db.execute('CREATE TABLE CX_MEMORY_FAMILIES(FAMILY_ID TEXT,CURRENT_VERSION_ID TEXT)')
    db.execute('CREATE TABLE CX_MEMORY_VERSIONS(VERSION_ID TEXT,FAMILY_ID TEXT,TITLE TEXT,BODY_TEXT TEXT,CONTENT_DIGEST TEXT,'
               'MEMORY_TYPE TEXT,MEMORY_SCOPE TEXT,CLASSIFICATION TEXT,LIFECYCLE_STATE TEXT,SECURITY_DOMAIN_ID TEXT,OWNER_PRINCIPAL_ID TEXT,VALID_UNTIL TIMESTAMP)')
    digest=memory._digest('Fact','Synthetic body','FACT','AGENT_MEMORY','INTERNAL')
    db.execute("INSERT INTO CX_MEMORY_VERSIONS VALUES('v1','f1','Fact','Synthetic body',?,'FACT','AGENT_MEMORY','INTERNAL','ACTIVE','domain','owner',NULL)",(digest,))
    db.execute("INSERT INTO CX_MEMORY_FAMILIES VALUES('f1','v1')")
    db.commit()
    # Use the real memory authorization implementation with its DB query routed
    # to this unit transaction fixture. Only role decisions are fixture inputs.
    def query_one(sql,params):
        result=db.execute(sql,params).fetchone()
        return {key.lower():result[key] for key in result.keys()} if result else None
    monkeypatch.setattr(memory,'execute_query_one',query_one)
    value=dict(family='MEMORY',entity_id='f1',revision_id='v1',content_digest=digest)
    def read(actor='owner',source=None):
        return sources.work.connection.execute_transaction_callback(lambda tx:sources.resolve(tx,actor,'domain',source or value))
    return db,value,read


def test_memory_exact_body_and_family(memory_source):
    db,value,read=memory_source
    assert 'Synthetic body' in read()['text']
    with pytest.raises(PermissionError):
        read(source=dict(value,entity_id='another-family'))
    with pytest.raises(ContinuityError):
        read(source=dict(value,content_digest='0'*64))
    with pytest.raises(PermissionError):
        read('reader')


def test_memory_body_corruption_and_current_family_revocation(memory_source):
    db,value,read=memory_source
    db.execute("UPDATE CX_MEMORY_VERSIONS SET BODY_TEXT='corrupt'")
    db.commit()
    with pytest.raises(ContinuityError,match='integrity'):
        read()
    db.execute("UPDATE CX_MEMORY_VERSIONS SET BODY_TEXT='Synthetic body'")
    db.execute("INSERT INTO CX_MEMORY_VERSIONS(VERSION_ID,FAMILY_ID,LIFECYCLE_STATE) VALUES('v2','f1','QUARANTINED')")
    db.execute("UPDATE CX_MEMORY_FAMILIES SET CURRENT_VERSION_ID='v2'")
    db.commit()
    with pytest.raises(PermissionError):
        read()
