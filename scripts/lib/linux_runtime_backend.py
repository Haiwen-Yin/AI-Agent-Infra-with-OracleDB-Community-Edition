"""Linux sandbox execution backend for the v4.4.11 local runtime adapter."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


DENIED_SYSCALLS = (
    "acct", "add_key", "bpf", "delete_module", "finit_module", "init_module",
    "io_pgetevents", "ioperm", "iopl", "kexec_file_load", "kexec_load",
    "keyctl", "lookup_dcookie", "mount", "move_mount", "name_to_handle_at",
    "open_by_handle_at", "open_tree", "perf_event_open", "pivot_root",
    "process_vm_readv", "process_vm_writev", "ptrace", "quotactl",
    "reboot", "request_key", "setns", "swapoff", "swapon", "syslog",
    "umount2", "unshare", "userfaultfd",
)
SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000


class LinuxRuntimeBackendError(RuntimeError):
    pass


def build_seccomp_bpf(denied: Sequence[str] = DENIED_SYSCALLS) -> bytes:
    """Build a default-allow BPF filter with explicit high-risk denials."""
    try:
        library = ctypes.CDLL("libseccomp.so.2")
    except OSError as exc:
        raise LinuxRuntimeBackendError("libseccomp.so.2 is unavailable") from exc
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_export_bpf.restype = ctypes.c_int
    context = library.seccomp_init(SCMP_ACT_ALLOW)
    if not context:
        raise LinuxRuntimeBackendError("seccomp filter allocation failed")
    read_fd, write_fd = os.pipe()
    try:
        action = SCMP_ACT_ERRNO | errno.EPERM
        for name in denied:
            number = library.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0:
                continue
            rc = library.seccomp_rule_add(context, action, number, 0)
            if rc != 0:
                raise LinuxRuntimeBackendError(f"seccomp rule failed for {name}: {rc}")
        rc = library.seccomp_export_bpf(context, write_fd)
        if rc != 0:
            raise LinuxRuntimeBackendError(f"seccomp export failed: {rc}")
    finally:
        os.close(write_fd)
        library.seccomp_release(context)
    chunks = []
    try:
        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(read_fd)
    payload = b"".join(chunks)
    if not payload:
        raise LinuxRuntimeBackendError("seccomp filter is empty")
    return payload


def safe_unit_name(agent_id: str, instance_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"cx-agent-{agent_id}-{instance_id}").strip("-.")
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{value[:160]}-{digest}.service"


def systemd_command(unit: str, sandbox_argv: Sequence[str], *, memory_bytes: int,
                    pids: int, runtime_seconds: int, cpu_quota_percent: int,
                    uid: int, gid: int) -> tuple[str, ...]:
    return (
        "/usr/bin/systemd-run", "--quiet", "--wait", "--collect", "--pipe",
        "--unit", unit, "--property", "Type=exec", "--property", "KillMode=mixed",
        "--property", "NoNewPrivileges=yes", "--property", f"MemoryMax={memory_bytes}",
        "--property", f"TasksMax={pids}", "--property", f"RuntimeMaxSec={runtime_seconds}",
        "--property", f"CPUQuota={cpu_quota_percent}%",
        "--property", f"User={uid}", "--property", f"Group={gid}",
        "--property", "UMask=0077", "--", *sandbox_argv,
    )


def _systemctl_properties(unit: str) -> dict[str, str]:
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", unit, "--property=MainPID,ControlGroup,ActiveState,SubState,Result"],
        check=False, capture_output=True, text=True, timeout=5,
    )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _status_fields(pid: int) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii", errors="replace").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return fields


def select_sandbox_process(
    candidates: Sequence[int],
    host_namespaces: Mapping[str, str],
    *,
    status_reader: Any = _status_fields,
    namespace_reader: Any = None,
) -> tuple[int, dict[str, str], dict[str, str]]:
    """Select the cgroup process carrying the strongest sandbox evidence."""
    if namespace_reader is None:
        namespace_reader = lambda pid, name: os.readlink(f"/proc/{pid}/ns/{name}")
    selected: tuple[int, dict[str, str], dict[str, str]] | None = None
    selected_score = -1
    for candidate in dict.fromkeys(candidates):
        try:
            candidate_status = status_reader(candidate)
            candidate_ns = {
                name: namespace_reader(candidate, name) for name in host_namespaces
            }
        except OSError:
            continue
        score = sum(
            value != host_namespaces[name] for name, value in candidate_ns.items()
        )
        score += 2 if candidate_status.get("Seccomp") == "2" else 0
        if score > selected_score:
            selected = (candidate, candidate_status, candidate_ns)
            selected_score = score
    if selected is None:
        raise LinuxRuntimeBackendError("sandbox process evidence is unavailable")
    return selected


def collect_process_evidence(unit: str, *, policy_digest: str, rootfs_digest: str,
                             egress: Sequence[str]) -> dict[str, Any]:
    properties = _systemctl_properties(unit)
    pid = int(properties.get("MainPID") or 0)
    if pid <= 0 or not Path(f"/proc/{pid}").is_dir():
        raise LinuxRuntimeBackendError("sandbox process is unavailable")
    cgroup_path = properties.get("ControlGroup") or ""
    cgroup_root = Path("/sys/fs/cgroup") / cgroup_path.lstrip("/")
    host_namespaces = {name: os.readlink(f"/proc/1/ns/{name}") for name in ("pid", "mnt", "net", "user", "ipc", "uts")}
    candidates = [pid]
    try:
        candidates.extend(int(value) for value in (cgroup_root / "cgroup.procs").read_text().split())
    except (OSError, ValueError):
        pass
    pid, status, namespaces = select_sandbox_process(candidates, host_namespaces)
    limits = {}
    for name in ("memory.max", "pids.max", "cpu.max"):
        try:
            limits[name] = (cgroup_root / name).read_text(encoding="ascii").strip()
        except OSError:
            limits[name] = ""
    root_readonly = False
    try:
        for line in Path(f"/proc/{pid}/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) > 5 and fields[4] == "/":
                root_readonly = "ro" in fields[5].split(",")
                break
    except OSError:
        pass
    uid_parts = (status.get("Uid") or "").split()
    gid_parts = (status.get("Gid") or "").split()
    evidence_ref = f"systemd://{unit}/{pid}"
    return {
        "backend": "bwrap", "unit": unit, "pid": pid,
        "runtime_identity": f"unit:{unit}:pid:{pid}", "evidence_ref": evidence_ref,
        "uid": uid_parts[0] if uid_parts else "", "gid": gid_parts[0] if gid_parts else "",
        "namespaces": namespaces,
        "private_namespaces": {name: value != host_namespaces[name] for name, value in namespaces.items()},
        "seccomp": status.get("Seccomp") == "2", "no_new_privileges": status.get("NoNewPrivs") == "1",
        "cap_eff": status.get("CapEff") or "", "readonly_rootfs": root_readonly, "private_proc": namespaces["pid"] != host_namespaces["pid"],
        "cgroup_path": cgroup_path, "cgroup_limits": limits,
        "policy_digest": policy_digest, "rootfs_digest": rootfs_digest,
        "egress": list(egress), "network_default_deny": not egress,
        "boundaries": ["process", "filesystem", "ipc", "network", "resource", "credential"],
    }


class LinuxRuntimeProcess:
    def __init__(self, unit: str, process: subprocess.Popen[bytes], policy_digest: str,
                 rootfs_digest: str, egress: Sequence[str], log_handle: Any, log_path: str) -> None:
        self.unit = unit
        self.process = process
        self.policy_digest = policy_digest
        self.rootfs_digest = rootfs_digest
        self.egress = tuple(egress)
        self.log_handle = log_handle
        self.log_path = log_path

    def wait_until_active(self, timeout: float = 10) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            properties = _systemctl_properties(self.unit)
            if int(properties.get("MainPID") or 0) > 0 and properties.get("ActiveState") == "active":
                return collect_process_evidence(self.unit, policy_digest=self.policy_digest,
                                                rootfs_digest=self.rootfs_digest, egress=self.egress)
            if self.process.poll() is not None:
                self.log_handle.flush()
                detail = Path(self.log_path).read_text(encoding="utf-8", errors="replace")[-1000:]
                raise LinuxRuntimeBackendError(f"sandbox exited during startup: {self.process.returncode}: {detail}")
            time.sleep(0.1)
        raise LinuxRuntimeBackendError("sandbox startup timed out")

    def stop(self) -> None:
        subprocess.run(["/usr/bin/systemctl", "stop", self.unit], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.log_handle.close()


class LinuxRuntimeBackend:
    """Stateful launcher for local Linux Agent processes."""

    def __init__(self) -> None:
        self._processes: dict[str, LinuxRuntimeProcess] = {}
        self._lock = threading.Lock()

    def start(self, key: str, *, agent_id: str, instance_id: str, sandbox_argv: Sequence[str],
              memory_bytes: int, pids: int, runtime_seconds: int, policy_digest: str,
              rootfs_digest: str, egress: Sequence[str], uid: int, gid: int,
              cpu_quota_percent: int) -> dict[str, Any]:
        if egress:
            raise LinuxRuntimeBackendError("egress allowlist backend is not configured")
        unit = safe_unit_name(agent_id, instance_id)
        command = systemd_command(unit, sandbox_argv, memory_bytes=memory_bytes,
                                  pids=pids, runtime_seconds=runtime_seconds,
                                  cpu_quota_percent=cpu_quota_percent, uid=uid, gid=gid)
        seccomp = build_seccomp_bpf()
        log_dir = Path("/var/log/chuanxu-runtime")
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_path = str(log_dir / f"{unit}.log")
        log_handle = open(log_path, "ab", buffering=0)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=log_handle, close_fds=True)
        assert process.stdin is not None
        process.stdin.write(seccomp)
        process.stdin.close()
        runtime = LinuxRuntimeProcess(unit, process, policy_digest, rootfs_digest, egress,
                                      log_handle, log_path)
        try:
            evidence = runtime.wait_until_active()
        except Exception:
            runtime.stop()
            raise
        with self._lock:
            previous = self._processes.pop(key, None)
            self._processes[key] = runtime
        if previous:
            previous.stop()
        return evidence

    def evidence(self, key: str) -> dict[str, Any]:
        with self._lock:
            runtime = self._processes.get(key)
        if not runtime:
            raise LinuxRuntimeBackendError("sandbox execution is unavailable")
        return collect_process_evidence(runtime.unit, policy_digest=runtime.policy_digest,
                                        rootfs_digest=runtime.rootfs_digest, egress=runtime.egress)

    def stop(self, key: str) -> None:
        with self._lock:
            runtime = self._processes.pop(key, None)
        if runtime:
            runtime.stop()
