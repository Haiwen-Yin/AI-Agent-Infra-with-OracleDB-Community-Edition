"""Cooperative Linux Skill runtime: verified files and process-held safe points.

All runtime turns must hold read_turn() for their full lifetime. This cannot
isolate a process that bypasses the adapter and does not claim remote runtime
observation. Database distribution/authorization remains server authoritative.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile


class SkillRuntimeError(ValueError):
    pass


def _digest(value):
    if not re.fullmatch('[0-9a-f]{64}',str(value)):
        raise SkillRuntimeError('INVALID_DIGEST')
    return value


class SkillRuntime:
    def __init__(self,root,public_key):
        self.public_key=public_key
        path=Path(root).absolute()
        if path.is_symlink(): raise SkillRuntimeError('UNSAFE_RUNTIME_ROOT')
        path.mkdir(mode=0o700,parents=False,exist_ok=True)
        info=path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise SkillRuntimeError('PRIVATE_RUNTIME_ROOT_REQUIRED')
        self.root=path.resolve()
        marker=self.root/'runtime-format.json'
        if not marker.exists() and any(self.root.iterdir()):
            raise SkillRuntimeError('NONEMPTY_RUNTIME_ROOT')
        for name in ('versions','staging'):
            folder=self.root/name
            if folder.is_symlink(): raise SkillRuntimeError('UNSAFE_RUNTIME_LAYOUT')
            folder.mkdir(mode=0o700,exist_ok=True)
        if marker.exists():
            if self._read_json(marker)!={'schema':'chuanxu-skill-runtime/v1'}:
                raise SkillRuntimeError('UNKNOWN_RUNTIME_FORMAT')
        else:
            with self._lock(exclusive=True):
                if any(item.name not in {'versions','staging','runtime.lock'} for item in self.root.iterdir()):
                    raise SkillRuntimeError('NONEMPTY_RUNTIME_ROOT')
                self._atomic_json(marker,{'schema':'chuanxu-skill-runtime/v1'})

    @contextmanager
    def _lock(self,*,exclusive):
        descriptor=os.open(self.root/'runtime.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try: fcntl.flock(descriptor,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
            except BlockingIOError as exc: raise SkillRuntimeError('RUNTIME_BUSY') from exc
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _read_json(path):
        if path.is_symlink(): raise SkillRuntimeError('UNSAFE_RUNTIME_LAYOUT')
        return json.loads(path.read_text())

    @staticmethod
    def _sync(path):
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)

    def _atomic_json(self,path,value):
        descriptor,temp=tempfile.mkstemp(prefix='.receipt-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w') as stream:
                json.dump(value,stream,sort_keys=True)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
            self._sync(path.parent)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def receive(self,archive_path,public_key,expected_digest):
        """Verify a private copy and extract plain files; never execute payloads."""
        from .release_archive_verification import verify
        if public_key!=self.public_key: raise SkillRuntimeError('TRUSTED_KEY_MISMATCH')
        digest=_digest(expected_digest)
        with self._lock(exclusive=True):
            existing=self.root/'versions'/digest
            with tempfile.TemporaryDirectory(prefix='receive-',dir=self.root/'staging') as temp:
                folder=Path(temp)
                copied=folder/'archive.zip'
                with Path(archive_path).open('rb') as source,copied.open('xb') as destination:
                    shutil.copyfileobj(source,destination)
                    destination.flush();os.fsync(destination.fileno())
                metadata=verify(copied,public_key,digest)
                if existing.exists():
                    self._verify_installed(digest)
                    return self._read_json(existing/'receipt.json')
                payload=folder/'payload';payload.mkdir(mode=0o700)
                files={}
                with zipfile.ZipFile(copied) as archive:
                    root=next(item for item in archive.namelist() if item.endswith('/build-manifest.json')).rsplit('/',1)[0]+'/'
                    for info in archive.infolist():
                        if info.is_dir(): continue
                        mode=info.external_attr>>16
                        relative=info.filename[len(root):]
                        parts=PurePosixPath(relative).parts
                        if (not parts or PurePosixPath(relative).as_posix()!=relative or any(part in {'.','..'} for part in parts)
                            or stat.S_IFMT(mode) not in {0,stat.S_IFREG}):
                            raise SkillRuntimeError('UNSAFE_ARCHIVE_ENTRY')
                        path=payload.joinpath(*parts)
                        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                        with archive.open(info) as source,path.open('xb') as destination:
                            shutil.copyfileobj(source,destination)
                            destination.flush();os.fsync(destination.fileno())
                        path.chmod(0o400)
                        with path.open('rb') as stream: files[relative]=hashlib.file_digest(stream,'sha256').hexdigest()
                receipt=dict(schema='chuanxu-skill-installation/v1',**metadata,files=files)
                self._atomic_json(folder/'receipt.json',receipt)
                # Each directory entry is durable before publishing the version.
                for parent,_,_ in os.walk(payload,topdown=False): self._sync(parent)
                self._sync(folder)
                os.rename(folder,existing)
                self._sync(existing.parent)
            return receipt

    def _verify_installed(self,digest):
        from .release_archive_verification import verify
        digest=_digest(digest)
        folder=self.root/'versions'/digest
        if folder.is_symlink() or not folder.is_dir(): raise SkillRuntimeError('VERSION_NOT_INSTALLED')
        if (folder/'archive.zip').is_symlink(): raise SkillRuntimeError('INSTALLED_FILES_CHANGED')
        receipt=self._read_json(folder/'receipt.json')
        if receipt.get('schema')!='chuanxu-skill-installation/v1' or receipt.get('received_digest')!=digest:
            raise SkillRuntimeError('INVALID_INSTALLATION_RECEIPT')
        files=receipt.get('files')
        if not isinstance(files,dict) or 'SKILL.md' not in files:
            raise SkillRuntimeError('INVALID_INSTALLATION_RECEIPT')
        verified=verify(folder/'archive.zip',self.public_key,digest)
        if any(receipt.get(key)!=value for key,value in verified.items()):
            raise SkillRuntimeError('INVALID_INSTALLATION_RECEIPT')
        with zipfile.ZipFile(folder/'archive.zip') as archive:
            root=next(item for item in archive.namelist() if item.endswith('/build-manifest.json')).rsplit('/',1)[0]+'/'
            signed={item.filename[len(root):]:hashlib.sha256(archive.read(item)).hexdigest() for item in archive.infolist() if not item.is_dir()}
        if files!=signed: raise SkillRuntimeError('INVALID_INSTALLATION_RECEIPT')
        payload=folder/'payload'
        if payload.is_symlink() or not payload.is_dir(): raise SkillRuntimeError('INSTALLED_FILES_CHANGED')
        actual=set()
        for parent,dirs,names in os.walk(payload,followlinks=False):
            for name in dirs+names:
                if (Path(parent)/name).is_symlink(): raise SkillRuntimeError('INSTALLED_FILES_CHANGED')
            for name in names:
                path=Path(parent)/name
                relative=path.relative_to(payload).as_posix();actual.add(relative)
                with path.open('rb') as stream: digest_now=hashlib.file_digest(stream,'sha256').hexdigest()
                if files.get(relative)!=digest_now: raise SkillRuntimeError('INSTALLED_FILES_CHANGED')
        if actual!=set(files): raise SkillRuntimeError('INSTALLED_FILES_CHANGED')
        return receipt

    def activate(self,digest,*,authorize):
        """Switch only while no managed turn is running and authorization holds.

        authorize is the trusted adapter's current server check, not a payload
        callback. Keep the old version; crash before/after the atomic pointer
        replacement leaves either complete version available for recovery.
        """
        digest=_digest(digest)
        with self._lock(exclusive=True):
            receipt=self._verify_installed(digest)
            if authorize(receipt) is not True: raise SkillRuntimeError('CURRENT_DISTRIBUTION_DENIED')
            self._atomic_json(self.root/'active.json',dict(received_digest=digest))
            return dict(received_digest=digest,package_version=receipt['package_version'],activation_state='ACTIVE',
                        observation='LOCAL_COOPERATIVE_RUNTIME')

    @contextmanager
    def read_turn(self):
        """Pin verified Skill files for the entire calling runtime turn."""
        with self._lock(exclusive=False) as descriptor:
            current=self._read_json(self.root/'active.json')
            digest=current['received_digest']
            receipt=self._verify_installed(digest)
            yield dict(receipt=receipt,skill_path=self.root/'versions'/digest/'payload/SKILL.md',lock_fd=descriptor)
