"""Actual isolated Agent worker with a single, bound host model gateway."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import tempfile

from . import deployment_adapters as adapters, runtime_isolation
from .isolated_channel_worker import receive, send


def verify_rootfs(rootfs):
    root = Path(rootfs)
    if not root.is_absolute() or root.is_symlink() or root == Path('/'):
        raise ValueError('invalid sandbox rootfs')
    manifest = root / '.cx-rootfs-manifest.sha256'
    for directory in [root, *root.parents]:
        info = directory.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('sandbox rootfs path must be root-owned and immutable')
    entries = {}
    for line in manifest.read_text().splitlines():
        digest, relative = line.split('  ', 1)
        path = root / relative.lstrip('/')
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise PermissionError('invalid rootfs manifest path')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError('rootfs file is not immutable')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise PermissionError('rootfs digest mismatch')
        entries[relative.lstrip('/')] = digest
    worker = Path(__file__).with_name('isolated_channel_worker.py')
    if entries.get('opt/isolated_channel_worker.py') != hashlib.sha256(worker.read_bytes()).hexdigest():
        raise PermissionError('sandbox Agent worker differs from the current package')
    return 'sha256:' + hashlib.sha256(manifest.read_bytes()).hexdigest()


class ChannelWorker:
    def __init__(self, execution, config):
        self.execution = execution
        self.config = config
        self.adapter = adapters.LinuxRuntimeAdapter()
        self.listener = None
        self.client = None
        self.workspace = None
        self.used = False
        self.peer_pid = None

    def start(self):
        rootfs = str(self.config.get('rootfs') or '')
        self.rootfs_digest = verify_rootfs(rootfs)
        uid, gid = int(self.config['uid']), int(self.config['gid'])
        if uid < 1 or gid < 1 or self.config.get('egress'):
            raise PermissionError('sandbox requires non-root identity and no direct network')
        base = Path('/var/lib/chuanxu/isolated-executions')
        base.mkdir(mode=0o711, parents=True, exist_ok=True)
        info = base.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or base.is_symlink():
            raise PermissionError('unsafe execution directory')
        self.workspace = Path(tempfile.mkdtemp(prefix='run-', dir=base))
        os.chown(self.workspace, uid, gid)
        self.listener = socket.socket(socket.AF_UNIX)
        self.listener.settimeout(15)
        self.listener.bind(str(self.workspace / 'broker.sock'))
        os.chmod(self.workspace / 'broker.sock', 0o600)
        os.chown(self.workspace / 'broker.sock', uid, gid)
        self.listener.listen(1)
        spec = adapters.LinuxSandboxSpec(
            agent_id=str(self.execution['agent_id']), instance_id=str(self.execution['execution_id']) + '-' + str(self.execution.get('fencing_token', 0)),
            command=('/usr/bin/python3', '-I', '-B', '/opt/isolated_channel_worker.py'),
            uid=uid, gid=gid, rootfs=rootfs, workdir=str(self.workspace),
            memory_bytes=256 * 1024 * 1024, cpu_seconds=180, pids=32, cpu_quota_percent=100,
        )
        self.run = {**self.execution, 'execution_id': spec.instance_id, 'sandbox_spec': spec}
        try:
            started = self.adapter.activate(self.run)
            if started.status != 'ACTIVE':
                raise runtime_isolation.IsolationError('Agent worker isolation is unverified')
            self.client, _ = self.listener.accept()
            self.client.settimeout(180)
            self.peer_pid, peer_uid, peer_gid = struct.unpack('3i', self.client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if (peer_uid, peer_gid) != (uid, gid) or receive(self.client).get('op') != 'ready':
                raise PermissionError('sandbox worker identity mismatch')
            return self.evidence()
        except BaseException:
            self.close()
            raise

    def evidence(self):
        evidence = self.adapter._backend.evidence(self.adapter._key(self.run), workload_pid=self.peer_pid)
        evidence.update(adapters.verify_linux_sandbox_evidence(evidence))
        if evidence.get('verified') is not True or evidence.get('pid') != self.peer_pid:
            raise runtime_isolation.IsolationError('model gateway peer is not the verified Agent worker')
        limits = evidence.get('cgroup_limits') or {}
        if limits.get('memory.max') != str(256 * 1024 * 1024) or limits.get('pids.max') != '32' or limits.get('cpu.max') != '100000 100000':
            raise runtime_isolation.IsolationError('Agent worker resource limits changed')
        evidence.update(workload='isolated_channel_worker.py', model_gateway='one-bound-call-no-credentials',
                        max_isolation_level='DEDICATED_CONTAINER', rootfs_digest=self.rootfs_digest)
        return evidence

    def model(self, profile, messages, call, authorize):
        if self.used:
            raise PermissionError('sandbox model request already consumed')
        self.used = True
        self.evidence()
        authorize()
        binding = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        send(self.client, {'binding': binding, 'messages': messages})
        request = receive(self.client)
        if request != {'op': 'model', 'binding': binding, 'messages': messages}:
            raise PermissionError('sandbox model request differs from authorized input')
        self.evidence()
        authorize()
        result = call(profile, messages)
        self.evidence()
        authorize()
        send(self.client, {'content': str(result.get('content') or '')})
        reply = receive(self.client)
        if reply != {'op': 'result', 'binding': binding, 'content': str(result.get('content') or '').strip()}:
            raise PermissionError('sandbox result binding mismatch')
        self.evidence()
        return {**result, 'content': reply['content']}

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
        if self.listener:
            self.listener.close()
            self.listener = None
        if hasattr(self, 'run'):
            self.adapter.cancel(self.run, 'Isolated execution completed or failed')
        if self.workspace and self.workspace.is_relative_to('/var/lib/chuanxu/isolated-executions'):
            shutil.rmtree(self.workspace)
            self.workspace = None
