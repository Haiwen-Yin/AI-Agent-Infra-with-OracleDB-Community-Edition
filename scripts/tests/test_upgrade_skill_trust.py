"""Signed Skill download, deferred activation and audit rollback boundaries."""
import hashlib
import sqlite3
import pytest
from lib import admin_management as management
from .test_upgrade_signature_integrity import archive,signing_key


@pytest.fixture
def fixture(monkeypatch,tmp_path,signing_key):
    with archive(signing_key) as zipped:
        content=zipped.fp.getvalue()
    digest=hashlib.sha256(content).hexdigest()
    (tmp_path/(digest+'.zip')).write_bytes(content)
    db=sqlite3.connect(':memory:')
    db.row_factory=sqlite3.Row
    db.executescript('''
        CREATE TABLE CX_UPGRADE_PLANS(UPGRADE_ID TEXT,PACKAGE_VERSION TEXT,PACKAGE_DIGEST TEXT,SIGNATURE_STATE TEXT,STATUS TEXT);
        CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT,PRINCIPAL_TYPE TEXT,STATUS TEXT);
        CREATE TABLE CX_SKILL_DISTRIBUTION(UPGRADE_ID TEXT,AGENT_ID TEXT,SKILL_VERSION TEXT,MESSAGE_STATE TEXT,
            ACKNOWLEDGEMENT_STATE TEXT,ACTIVATION_STATE TEXT,DRIFT_STATE TEXT,EVIDENCE_JSON TEXT,UPDATED_AT TIMESTAMP);
        INSERT INTO CX_PRINCIPALS VALUES('agent','AGENT','ACTIVE');
        INSERT INTO CX_SKILL_DISTRIBUTION VALUES('upgrade','agent','4.4.15','SENT','PENDING','OLD_VERSION','UNKNOWN',NULL,CURRENT_TIMESTAMP);
    ''')
    db.execute("INSERT INTO CX_UPGRADE_PLANS VALUES('upgrade','4.4.15',?,'VERIFIED','SKILL_DISTRIBUTION')",(digest,))
    db.commit()
    class Tx:
        def execute(self,sql,params): return db.execute(sql,params).rowcount
        def query_one(self,sql,params):
            row=db.execute(sql.replace(' FOR UPDATE',''),params).fetchone()
            return {key.lower():row[key] for key in row.keys()} if row else None
    def transaction(callback):
        with db: return callback(Tx())
    monkeypatch.setattr(management,'_staging_directory',lambda:tmp_path)
    monkeypatch.setattr(management.connection,'execute_transaction_callback',transaction)
    monkeypatch.setattr(management.connection,'execute_query_one',Tx().query_one)
    monkeypatch.setattr(management.identity_api,'_audit_tx',lambda *_:None)
    yield db,digest,content,tmp_path
    db.close()


def test_exact_download_and_deferred_activation(fixture):
    db,digest,content,_=fixture
    assert management.download_upgrade_skill('agent','upgrade','4.4.15')==content
    result=management.acknowledge_upgrade_skill('agent','upgrade','4.4.15',False,True,received_digest=digest)
    assert result['acknowledgement_state']=='ACKNOWLEDGED' and result['activation_state']=='OLD_VERSION'
    result=management.acknowledge_upgrade_skill('agent','upgrade','4.4.15',True,True,received_digest=digest)
    assert result['activation_state']=='ACTIVE'
    assert management.acknowledge_upgrade_skill('agent','upgrade','4.4.15',True,True,received_digest=digest)['replayed']
    with pytest.raises(management.ManagementError):
        management.acknowledge_upgrade_skill('agent','upgrade','4.4.15',False,False)
    assert db.execute('SELECT ACTIVATION_STATE FROM CX_SKILL_DISTRIBUTION').fetchone()[0]=='ACTIVE'


@pytest.mark.parametrize('attack',['wrong-recipient','wrong-version','missing-digest','changed-archive','revoked-trust','inactive'])
def test_ack_cannot_replace_server_trust(fixture,monkeypatch,attack):
    db,digest,content,path=fixture
    actor='stranger' if attack=='wrong-recipient' else 'agent'
    version='4.4.14' if attack=='wrong-version' else '4.4.15'
    if attack=='changed-archive': (path/(digest+'.zip')).write_bytes(content+b'changed')
    if attack=='revoked-trust': monkeypatch.delenv('CX_RELEASE_SIGNING_PUBLIC_KEY')
    if attack=='inactive':
        db.execute("UPDATE CX_PRINCIPALS SET STATUS='SUSPENDED'")
        db.commit()
    with pytest.raises(management.ManagementError):
        management.acknowledge_upgrade_skill(actor,'upgrade',version,True,True,received_digest='' if attack=='missing-digest' else digest)
    if attack!='missing-digest':
        with pytest.raises(management.ManagementError):
            management.download_upgrade_skill(actor,'upgrade',version)
    assert db.execute('SELECT ACKNOWLEDGEMENT_STATE FROM CX_SKILL_DISTRIBUTION').fetchone()[0]=='PENDING'


def test_ack_audit_failure_rolls_back_activation(fixture,monkeypatch):
    db,digest,_,_=fixture
    def fail(*_): raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(management.identity_api,'_audit_tx',fail)
    with pytest.raises(RuntimeError):
        management.acknowledge_upgrade_skill('agent','upgrade','4.4.15',True,True,received_digest=digest)
    assert db.execute('SELECT ACTIVATION_STATE FROM CX_SKILL_DISTRIBUTION').fetchone()[0]=='OLD_VERSION'


@pytest.mark.parametrize('invalid',[None,'key','digest'])
def test_independent_verifier_uses_local_pin(fixture,signing_key,tmp_path,invalid):
    import base64
    import subprocess
    import sys
    from pathlib import Path
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _,digest,_,path=fixture
    key=Ed25519PrivateKey.generate() if invalid=='key' else signing_key
    public=tmp_path/'trusted-public-key.txt'
    public.write_text(base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode())
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools/verify_release_archive.py'),
        '--input',str(path/(digest+'.zip')),'--public-key-file',str(public),'--expected-digest','0'*64 if invalid=='digest' else digest],
        capture_output=True,text=True)
    assert result.returncode==(1 if invalid else 0)
    assert ('RELEASE_VERIFICATION_FAILED' in result.stdout)==bool(invalid)


@pytest.mark.parametrize('existing',[0,1,2])
def test_upsert_binds_only_placeholders_in_each_statement(existing):
    calls=[]
    class Tx:
        def execute(self,sql,params):
            calls.append((sql,params))
            assert params==({'value':'new','key':'record'} if sql.startswith('UPDATE') else {'id':'new-id','value':'new','key':'record'})
            return existing if sql.startswith('UPDATE') else 1
    update="UPDATE fixture SET value=:value WHERE key=:key AND label='literal:id' /* ignored :id */"
    insert='INSERT INTO fixture(id,key,value) VALUES(:id,:key,:value)'
    if existing==2:
        with pytest.raises(management.ManagementError):
            management._update_or_insert(Tx(),update,insert,{'id':'new-id','key':'record','value':'new'})
    else:
        management._update_or_insert(Tx(),update,insert,{'id':'new-id','key':'record','value':'new'})
    assert len(calls)==(2 if existing==0 else 1)
