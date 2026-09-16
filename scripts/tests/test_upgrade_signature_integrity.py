"""Real cryptographic package verification without trusted-state fixtures."""
import base64
import hashlib
import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lib import admin_management as management


def archive(key,*,payload=b'original skill',tamper=None):
    files={'build-manifest.json':json.dumps({'schema':'ai-agent-infra-build/v1','version':'4.4.15',
                                           'edition':'Community','database':{'key':'pg'}}).encode(),
           'SKILL.md':payload}
    manifest=''.join(hashlib.sha256(value).hexdigest()+'  '+name+'\n' for name,value in sorted(files.items())).encode()
    digest=hashlib.sha256(manifest).hexdigest()
    envelope={'schema':'chuanxu-release-signature/v1','algorithm':'ED25519','signed_object':'package-files.sha256',
              'digest':digest,'signature':base64.urlsafe_b64encode(key.sign(b'chuanxu-release-manifest/v1\n'+digest.encode())).decode()}
    files.update({'package-files.sha256':manifest,'release-signature.json':json.dumps(envelope).encode()})
    if tamper=='payload':
        files['SKILL.md']=b'changed skill'
    elif tamper=='manifest':
        files['SKILL.md']=b'changed skill'
        files['package-files.sha256']=manifest.replace(hashlib.sha256(payload).hexdigest().encode(),hashlib.sha256(files['SKILL.md']).hexdigest().encode())
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as zipped:
        for name,value in files.items():
            zipped.writestr('package/'+name,value)
        if tamper=='extra_root':
            zipped.writestr('outside.py',b'not listed')
        if tamper=='duplicate':
            zipped.writestr('package/SKILL.md',payload)
    output.seek(0)
    return zipfile.ZipFile(output)


@pytest.fixture
def signing_key(monkeypatch):
    key=Ed25519PrivateKey.generate()
    monkeypatch.setenv('CX_RELEASE_SIGNING_PUBLIC_KEY',base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode())
    return key


def test_signed_archive_is_constructible_and_verified(signing_key):
    with archive(signing_key) as zipped:
        _,root=management._verify_package_manifest(zipped)
        assert management._verify_release_signature(zipped,root,'separate-transport-digest')[0]=='VERIFIED'


@pytest.mark.parametrize('tamper',['payload','extra_root','duplicate'])
def test_payload_or_archive_structure_tampering_is_rejected(signing_key,tamper):
    with archive(signing_key,tamper=tamper) as zipped:
        with pytest.raises(management.ManagementError):
            management._verify_package_manifest(zipped)


def test_rehashing_tampered_payload_does_not_repair_signature(signing_key):
    with archive(signing_key,tamper='manifest') as zipped:
        _,root=management._verify_package_manifest(zipped)
        assert management._verify_release_signature(zipped,root,'transport')[0]=='UNTRUSTED'


def test_another_signing_key_is_not_trusted(signing_key):
    with archive(Ed25519PrivateKey.generate()) as zipped:
        _,root=management._verify_package_manifest(zipped)
        assert management._verify_release_signature(zipped,root,'transport')[0]=='UNTRUSTED'


def test_client_metadata_cannot_mark_a_package_verified(monkeypatch):
    monkeypatch.setattr(management,'_require_manage',lambda *_:None)
    monkeypatch.setattr(management.connection,'execute',lambda *_:pytest.fail('Metadata must not create trusted plans'))
    with pytest.raises(management.ManagementError):
        management.stage_upgrade('admin','4.4.15','Community','a'*64,'VERIFIED','Synthetic request')


@pytest.mark.parametrize('changed',['archive','key',None])
def test_staged_bytes_and_current_trust_are_rechecked(signing_key,monkeypatch,tmp_path,changed):
    with archive(signing_key) as zipped:
        content=zipped.fp.getvalue()
    digest=hashlib.sha256(content).hexdigest()
    path=tmp_path/(digest+'.zip')
    path.write_bytes(content+b'changed' if changed=='archive' else content)
    monkeypatch.setattr(management,'_staging_directory',lambda:tmp_path)
    monkeypatch.setattr(management.connection,'execute_query_one',lambda *_:{'package_digest':digest})
    if changed=='key':
        monkeypatch.setenv('CX_RELEASE_SIGNING_PUBLIC_KEY',base64.urlsafe_b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode())
    if changed:
        with pytest.raises(management.ManagementError):
            management._package_manifest_for_upgrade('fixture')
    else:
        assert management._package_manifest_for_upgrade('fixture')[2]==digest


def test_operator_signing_command_produces_verifiable_archive(signing_key,tmp_path):
    from cryptography.hazmat.primitives import serialization
    from pathlib import Path
    import subprocess
    import sys
    source=tmp_path/'unsigned.zip'
    destination=tmp_path/'signed.zip'
    keyfile=tmp_path/'synthetic-key.pem'
    keyfile.write_bytes(signing_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    keyfile.chmod(0o600)
    with archive(signing_key) as original,zipfile.ZipFile(source,'w') as unsigned:
        for name in original.namelist():
            if not name.endswith('/release-signature.json'):
                unsigned.writestr(name,original.read(name))
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'tools/sign_release_archive.py'),
             '--input',str(source),'--output',str(destination),'--private-key',str(keyfile),'--key-id','synthetic-test']
    completed=subprocess.run(command,capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    with zipfile.ZipFile(destination) as signed:
        _,root=management._verify_package_manifest(signed)
        assert management._verify_release_signature(signed,root,'transport')[0]=='VERIFIED'
        assert all('PRIVATE KEY' not in signed.read(name).decode('utf-8','replace') for name in signed.namelist())
    before=destination.read_bytes()
    assert subprocess.run(command,capture_output=True).returncode!=0
    assert destination.read_bytes()==before


def test_distinct_archives_of_same_version_keep_separate_trust(signing_key,monkeypatch,tmp_path):
    import sqlite3
    db=sqlite3.connect(':memory:')
    db.row_factory=sqlite3.Row
    db.executescript('''
        CREATE TABLE CX_MANAGEMENT_ARTIFACTS(ARTIFACT_ID TEXT PRIMARY KEY,ARTIFACT_KEY TEXT,ARTIFACT_VERSION TEXT,
          ARTIFACT_KIND TEXT,CONTENT_DIGEST TEXT,SIGNATURE TEXT,CLASSIFICATION TEXT,SECRET_FREE TEXT,STATUS TEXT,
          STORAGE_ADAPTER TEXT,CREATED_BY TEXT,UNIQUE(ARTIFACT_KEY,ARTIFACT_VERSION));
        CREATE TABLE CX_UPGRADE_PLANS(UPGRADE_ID TEXT PRIMARY KEY,PACKAGE_VERSION TEXT,EDITION TEXT,PACKAGE_DIGEST TEXT,
          SIGNATURE_STATE TEXT,PREFLIGHT_STATE TEXT,STATUS TEXT,REASON TEXT,CREATED_BY TEXT);
    ''')
    class Tx:
        def execute(self,sql,params):
            return db.execute(sql,params).rowcount
        def query_one(self,sql,params):
            row=db.execute(sql.replace(' FOR UPDATE',''),params).fetchone()
            return {key.lower():row[key] for key in row.keys()} if row else None
    def transaction(callback):
        with db:
            return callback(Tx())
    monkeypatch.setattr(management,'_require_manage',lambda *_:None)
    monkeypatch.setattr(management,'_staging_directory',lambda:tmp_path)
    monkeypatch.setattr(management.connection,'execute_transaction_callback',transaction)
    monkeypatch.setattr(management.identity_api,'_audit_tx',lambda *_:None)
    monkeypatch.setattr(management,'auto_schedule_upgrade',lambda *_:{'automation_state':'UNIT_TEST_NO_SCHEDULING'})
    results=[]
    for key in (Ed25519PrivateKey.generate(),signing_key):
        with archive(key) as zipped:
            content=zipped.fp.getvalue()
        result=management.stage_upgrade_archive('admin','synthetic.zip',content,'Synthetic acceptance')
        results.append(result)
        assert management.stage_upgrade_archive('admin','synthetic.zip',content,'Same request')['upgrade_id']==result['upgrade_id']
    assert [item['signature_state'] for item in results]==['UNTRUSTED','VERIFIED']
    assert results[0]['upgrade_id']!=results[1]['upgrade_id']
    assert db.execute('SELECT COUNT(*) FROM CX_MANAGEMENT_ARTIFACTS').fetchone()[0]==2
    db.close()
