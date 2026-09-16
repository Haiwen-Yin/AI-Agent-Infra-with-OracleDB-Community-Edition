"""Signed installation, real process safe points and durable retry boundaries."""
import base64
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import time
import zipfile
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lib.skill_runtime_installation import SkillRuntime,SkillRuntimeError


@pytest.fixture
def packages(tmp_path):
    key=Ed25519PrivateKey.generate()
    public=base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode('ascii')
    def create(text,symlink=False):
        files={'SKILL.md':text.encode(),'build-manifest.json':json.dumps(dict(schema='ai-agent-infra-build/v1',version='4.4.15',edition='Community',database={'key':'pg'})).encode()}
        manifest=''.join(hashlib.sha256(content).hexdigest()+'  '+name+'\n' for name,content in sorted(files.items())).encode()
        digest=hashlib.sha256(manifest).hexdigest()
        envelope=dict(schema='chuanxu-release-signature/v1',algorithm='ED25519',signed_object='package-files.sha256',digest=digest,
            signature=base64.urlsafe_b64encode(key.sign(b'chuanxu-release-manifest/v1\n'+digest.encode())).decode())
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name,content in files.items():
                info=zipfile.ZipInfo('package/'+name)
                if symlink and name=='SKILL.md': info.external_attr=0o120777<<16
                archive.writestr(info,content)
            archive.writestr('package/package-files.sha256',manifest)
            archive.writestr('package/release-signature.json',json.dumps(envelope))
        content=buffer.getvalue();digest=hashlib.sha256(content).hexdigest()
        path=tmp_path/(digest+'.zip');path.write_bytes(content)
        return path,digest
    return public,create


def test_atomic_switch_keeps_old_files_and_checks_current_authority(tmp_path,packages):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    old,old_digest=create('old Skill')
    new,new_digest=create('new Skill')
    runtime.receive(old,public,old_digest)
    runtime.activate(old_digest,authorize=lambda _:True)
    runtime.receive(new,public,new_digest)
    with pytest.raises(SkillRuntimeError,match='CURRENT_DISTRIBUTION_DENIED'):
        runtime.activate(new_digest,authorize=lambda _:False)
    with runtime.read_turn() as turn: assert turn['skill_path'].read_text()=='old Skill'
    runtime.activate(new_digest,authorize=lambda _:True)
    with runtime.read_turn() as turn: assert turn['skill_path'].read_text()=='new Skill'
    assert (runtime.root/'versions'/old_digest/'payload/SKILL.md').read_text()=='old Skill'


def test_other_process_turn_blocks_switch_and_crash_releases_lock(tmp_path,packages):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    old,old_digest=create('old');new,new_digest=create('new')
    runtime.receive(old,public,old_digest);runtime.receive(new,public,new_digest)
    runtime.activate(old_digest,authorize=lambda _:True)
    code="from lib.skill_runtime_installation import SkillRuntime; import sys; r=SkillRuntime(sys.argv[1],sys.argv[2]); ctx=r.read_turn(); turn=ctx.__enter__(); print(turn['skill_path'].read_text(),flush=True); sys.stdin.read()"
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process=subprocess.Popen([sys.executable,'-c',code,str(runtime.root),public],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,env=env)
    try:
        assert process.stdout.readline().strip()=='old'
        with pytest.raises(SkillRuntimeError,match='RUNTIME_BUSY'):
            runtime.activate(new_digest,authorize=lambda _:True)
    finally:
        process.kill();process.wait(timeout=10)
    runtime.activate(new_digest,authorize=lambda _:True)
    with runtime.read_turn() as turn: assert turn['skill_path'].read_text()=='new'


def test_launched_turn_retains_lock_after_wrapper_crash(tmp_path,packages):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    archive,digest=create('active')
    runtime.receive(archive,public,digest);runtime.activate(digest,authorize=lambda _:True)
    pin=tmp_path/'public-key';pin.write_text(public)
    ready=tmp_path/'child-ready'
    code="import os,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); sys.stdin.read()"
    script=Path(__file__).resolve().parents[1]/'tools/skill_runtime.py'
    process=subprocess.Popen([sys.executable,str(script),'--root',str(runtime.root),'--public-key-file',str(pin),'run','--',sys.executable,'-c',code,str(ready)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    child=None
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(.01)
        assert ready.exists(),'Managed child did not start'
        child=int(ready.read_text())
        process.kill();process.wait(timeout=10)
        with pytest.raises(SkillRuntimeError,match='RUNTIME_BUSY'):
            runtime.activate(digest,authorize=lambda _:True)
    finally:
        if child:
            try: os.kill(child,signal.SIGTERM)
            except ProcessLookupError: pass
        if process.poll() is None: process.kill();process.wait(timeout=10)
        process.stdin.close()
    deadline=time.monotonic()+5
    while True:
        try: runtime.activate(digest,authorize=lambda _:True);break
        except SkillRuntimeError:
            if time.monotonic()>deadline: raise
            time.sleep(.01)


def test_tampered_receipt_cannot_reauthorize_changed_installed_bytes(tmp_path,packages):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    archive,digest=create('trusted')
    runtime.receive(archive,public,digest);runtime.activate(digest,authorize=lambda _:True)
    folder=runtime.root/'versions'/digest
    path=folder/'payload/SKILL.md';path.chmod(0o600);path.write_text('forged')
    receipt=json.loads((folder/'receipt.json').read_text())
    receipt['files']['SKILL.md']=hashlib.sha256(b'forged').hexdigest()
    (folder/'receipt.json').write_text(json.dumps(receipt))
    with pytest.raises(SkillRuntimeError,match='INVALID_INSTALLATION_RECEIPT'):
        with runtime.read_turn(): pass


def test_symlink_payload_and_wrong_digest_do_not_publish_installations(tmp_path,packages):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    archive,digest=create('/etc/passwd',symlink=True)
    with pytest.raises(SkillRuntimeError,match='UNSAFE_ARCHIVE_ENTRY'): runtime.receive(archive,public,digest)
    assert not list((runtime.root/'versions').iterdir())
    assert not list((runtime.root/'staging').iterdir())
    archive,digest=create('regular')
    with pytest.raises(ValueError): runtime.receive(archive,public,'0'*64)
    assert not list((runtime.root/'versions').iterdir())


def test_nonempty_or_shared_root_is_preserved(tmp_path,packages):
    public,_=packages
    existing=tmp_path/'existing';existing.mkdir(mode=0o700);(existing/'important').write_text('preserve')
    with pytest.raises(SkillRuntimeError,match='NONEMPTY_RUNTIME_ROOT'): SkillRuntime(existing,public)
    assert sorted(path.name for path in existing.iterdir())==['important']
    shared=tmp_path/'shared';shared.mkdir(mode=0o755)
    with pytest.raises(SkillRuntimeError,match='PRIVATE_RUNTIME_ROOT_REQUIRED'): SkillRuntime(shared,public)


@pytest.mark.parametrize('entry',['archive.zip','payload'])
def test_installed_archive_and_payload_cannot_be_replaced_by_symlinks(tmp_path,packages,entry):
    public,create=packages
    runtime=SkillRuntime(tmp_path/'runtime',public)
    archive,digest=create('trusted')
    runtime.receive(archive,public,digest);runtime.activate(digest,authorize=lambda _:True)
    installed=runtime.root/'versions'/digest/entry
    original=tmp_path/('original-'+entry)
    installed.rename(original)
    installed.symlink_to(original,target_is_directory=original.is_dir())
    with pytest.raises(SkillRuntimeError,match='INSTALLED_FILES_CHANGED'):
        with runtime.read_turn(): pass
    assert original.exists()


@pytest.mark.parametrize('failure',[None,'revalidation','final_ack'])
def test_sync_current_trust_and_uncertain_ack_recovery(tmp_path,packages,monkeypatch,failure):
    public,create=packages
    path=Path(__file__).resolve().parents[1]/'tools/skill_runtime.py'
    spec=importlib.util.spec_from_file_location('managed_skill_tool',path)
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    runtime=SkillRuntime(tmp_path/'runtime',public)
    old,old_digest=create('old');new,new_digest=create('new')
    runtime.receive(old,public,old_digest);runtime.activate(old_digest,authorize=lambda _:True)
    state=dict(active=False,downloads=0,failed=False)
    def handle(request):
        assert request.headers['Authorization']=='Bearer synthetic'
        if request.url.path.endswith('/skill-pending'):
            return httpx.Response(200,json={'items':[] if state['active'] else [dict(upgrade_id='synthetic',package_digest=new_digest,skill_version='4.4.15')]})
        if request.url.path.endswith('/skill-archive'):
            state['downloads']+=1
            if failure=='revalidation' and state['downloads']==2: return httpx.Response(409)
            return httpx.Response(200,content=new.read_bytes())
        if request.url.path.endswith('/skill-ack'):
            body=json.loads(request.content)
            assert body['received_digest']==new_digest
            if body['safe_point']:
                state['active']=True
                if failure=='final_ack' and not state['failed']:
                    state['failed']=True
                    return httpx.Response(503)
            elif state['active']: return httpx.Response(409)
            return httpx.Response(200,json={'activation_state':'ACTIVE' if state['active'] else 'OLD_VERSION'})
        raise AssertionError('Unexpected request')
    original=httpx.Client
    monkeypatch.setattr(tool.httpx,'Client',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handle)))
    def sync():
        return tool.sync(runtime,gateway='http://synthetic/api/agent-gateway',actor='synthetic',instance='instance',token='synthetic',
                         upgrade_id='synthetic',public_key=public,database='pg',edition='community')
    if failure:
        with pytest.raises(SkillRuntimeError,match='CURRENT_DISTRIBUTION_DENIED' if failure=='revalidation' else 'LOCAL_ACTIVE_SERVER_ACK_PENDING'):
            sync()
        with runtime.read_turn() as turn:
            assert turn['receipt']['received_digest']==(old_digest if failure=='revalidation' else new_digest)
    result=sync()
    assert result['received_digest']==new_digest and result['server_acknowledgement']=='ACTIVE'
    assert sync()['received_digest']==new_digest
