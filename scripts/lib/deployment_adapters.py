"""Reference DeploymentTarget adapters for v4.3.6.

These adapters define the product boundary for customer infrastructure.  They
do not make vendor-specific calls and never grant authority from a callback.
Each customer connector can implement the same lifecycle with its own
credential and network policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Protocol, Sequence
import hashlib
import os
import shutil
from pathlib import Path

from .linux_runtime_backend import LinuxRuntimeBackend, LinuxRuntimeBackendError


TARGET_TYPES = frozenset({
    "LOCAL_MANAGED", "REMOTE_WORKER", "CONTAINER_MANAGED", "WEBHOOK_MANAGED",
})
TENANT_TARGET_TYPES = frozenset({"KUBERNETES", "MAAS", "SAAS"})
FORBIDDEN_HOST_PATHS = frozenset({"/", "/proc", "/sys", "/dev", "/run", "/var/run"})
_FORBIDDEN_SOCKETS = ("docker.sock", "containerd.sock", "crio.sock")


@dataclass(frozen=True)
class AdapterResult:
    operation: str
    target_type: str
    status: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(Protocol):
    target_type: str

    def prepare(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def activate(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def health(self, execution: Dict[str, Any]) -> AdapterResult: ...
    def cancel(self, execution: Dict[str, Any], reason: str) -> AdapterResult: ...
    def revoke(self, execution: Dict[str, Any], reason: str) -> AdapterResult: ...
    def evidence(self, execution: Dict[str, Any]) -> AdapterResult: ...


@dataclass(frozen=True)
class LinuxSandboxSpec:
    """Explicit, portable inputs for a local Linux Agent sandbox."""

    agent_id: str
    instance_id: str
    command: tuple[str, ...]
    uid: int
    gid: int
    workdir: str = "/var/lib/ai-agent/work"
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 300
    cpu_quota_percent: int = 100
    pids: int = 128
    egress: tuple[str, ...] = ()
    rootfs: str = "/var/lib/ai-agent/rootfs"
    credential_dir: str = ""

    def __post_init__(self) -> None:
        if not self.agent_id.strip() or not self.instance_id.strip():
            raise ValueError("agent and instance are required")
        if not self.command or any(not str(arg) for arg in self.command):
            raise ValueError("command must be a non-empty argument array")
        if self.uid < 1 or self.gid < 1:
            raise ValueError("sandbox UID/GID must be non-root")
        if (self.memory_bytes < 16 * 1024 * 1024 or self.cpu_seconds < 1 or self.pids < 1
                or not 1 <= self.cpu_quota_percent <= 1000):
            raise ValueError("sandbox resource limits are invalid")
        for path in (self.workdir, self.rootfs):
            normalized = os.path.abspath(path)
            if normalized in FORBIDDEN_HOST_PATHS:
                raise ValueError("unrestricted host path is forbidden")
        if self.credential_dir and os.path.abspath(self.credential_dir) in FORBIDDEN_HOST_PATHS:
            raise ValueError("unrestricted credential path is forbidden")
        for value in self.egress:
            if not str(value).strip() or " " in str(value):
                raise ValueError("egress entries must be non-empty host or CIDR values")


@dataclass(frozen=True)
class LinuxSandboxCommand:
    argv: tuple[str, ...]
    policy_digest: str
    backend: str = "bwrap"


def build_linux_sandbox_command(spec: LinuxSandboxSpec, *, bwrap: str | None = None) -> LinuxSandboxCommand:
    """Build an argv-only bubblewrap command; no shell interpolation is allowed."""
    binary = bwrap or shutil.which("bwrap")
    if not binary:
        raise RuntimeError("bwrap is unavailable; Linux sandbox is UNVERIFIED")
    workdir = os.path.abspath(spec.workdir)
    rootfs = os.path.abspath(spec.rootfs)
    args: list[str] = [binary, "--die-with-parent", "--new-session", "--unshare-pid",
                       "--unshare-uts", "--unshare-ipc", "--unshare-net", "--unshare-user",
                       "--uid", str(spec.uid), "--gid", str(spec.gid), "--ro-bind", rootfs, "/",
                       "--tmpfs", "/tmp", "--bind", workdir, "/workspace", "--chdir", "/workspace",
                       "--proc", "/proc", "--dev", "/dev", "--cap-drop", "ALL", "--seccomp", "0", "--clearenv",
                       "--setenv", "PATH", "/usr/bin:/bin"]
    if spec.credential_dir:
        args[args.index("--proc"):args.index("--proc")] = ["--ro-bind", os.path.abspath(spec.credential_dir), "/run/secrets"]
    # Network is denied by --unshare-net. Egress allowlists are carried in
    # evidence and must be enforced by a privileged host firewall backend.
    args.extend(spec.command)
    digest = hashlib.sha256("\0".join(args[1:] + list(spec.egress)).encode()).hexdigest()
    return LinuxSandboxCommand(tuple(args), "sha256:" + digest)


def verify_linux_sandbox_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Validate evidence before promoting a local runtime to VERIFIED."""
    required = {"process", "filesystem", "ipc", "network", "resource", "credential"}
    boundaries = {str(x).lower() for x in evidence.get("boundaries", ())}
    checks = {
        "backend": str(evidence.get("backend") or "") == "bwrap",
        "uid_non_root": str(evidence.get("uid") or "0") not in {"", "0"},
        "gid_non_root": str(evidence.get("gid") or "0") not in {"", "0"},
        "seccomp": bool(evidence.get("seccomp")),
        "readonly_rootfs": bool(evidence.get("readonly_rootfs")),
        "private_proc": bool(evidence.get("private_proc")),
        "private_namespaces": all(bool((evidence.get("private_namespaces") or {}).get(name))
                                  for name in ("pid", "mnt", "net", "user", "ipc", "uts")),
        "no_new_privileges": bool(evidence.get("no_new_privileges")),
        "capabilities_dropped": str(evidence.get("cap_eff") or "") in {"0", "0000000000000000"},
        "resource_limits": all(bool((evidence.get("cgroup_limits") or {}).get(name))
                               for name in ("memory.max", "pids.max")),
        "network_default_deny": bool(evidence.get("network_default_deny")),
        "boundaries": required.issubset(boundaries),
        "evidence_ref": bool(str(evidence.get("evidence_ref") or "").strip()),
    }
    return {"verified": all(checks.values()), "checks": checks,
            "enforcement_mode": "VERIFIED" if all(checks.values()) else "UNVERIFIED"}


class LinuxRuntimeAdapter:
    """Local Linux adapter. It prepares a hardened command and never fakes evidence."""

    target_type = "LOCAL_LINUX_SANDBOX"
    _backend = LinuxRuntimeBackend()

    @staticmethod
    def _key(execution: Mapping[str, Any]) -> str:
        key = str(execution.get("execution_id") or execution.get("instance_id") or "").strip()
        if not key:
            raise ValueError("execution_id is required")
        return key

    @staticmethod
    def _rootfs_digest(rootfs: str) -> str:
        path = Path(rootfs)
        manifest = path / ".cx-rootfs-manifest.sha256"
        if not path.is_dir() or not manifest.is_file():
            raise ValueError("rootfs requires .cx-rootfs-manifest.sha256")
        return "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()

    def prepare(self, execution: Dict[str, Any]) -> AdapterResult:
        spec = execution.get("sandbox_spec")
        if not isinstance(spec, LinuxSandboxSpec):
            raise ValueError("sandbox_spec must be LinuxSandboxSpec")
        command = build_linux_sandbox_command(spec)
        return AdapterResult("PREPARE", self.target_type, "READY", {
            "backend": command.backend, "argv": list(command.argv),
            "policy_digest": command.policy_digest, "enforcement_mode": "UNVERIFIED",
            "isolation_level": "DEDICATED_RUNTIME", "egress": list(spec.egress),
        })

    def activate(self, execution: Dict[str, Any]) -> AdapterResult:
        prepared = self.prepare(execution)
        spec = execution["sandbox_spec"]
        evidence = self._backend.start(
            self._key(execution), agent_id=spec.agent_id, instance_id=spec.instance_id,
            sandbox_argv=prepared.evidence["argv"], memory_bytes=spec.memory_bytes,
            pids=spec.pids, runtime_seconds=spec.cpu_seconds,
            cpu_quota_percent=spec.cpu_quota_percent,
            policy_digest=prepared.evidence["policy_digest"],
            rootfs_digest=self._rootfs_digest(spec.rootfs), egress=spec.egress,
            uid=spec.uid, gid=spec.gid,
        )
        verified = verify_linux_sandbox_evidence(evidence)
        evidence.update(verified)
        return AdapterResult("ACTIVATE", self.target_type,
                             "ACTIVE" if verified["verified"] else "UNVERIFIED", evidence)

    def health(self, execution: Dict[str, Any]) -> AdapterResult:
        try:
            evidence = self._backend.evidence(self._key(execution))
        except LinuxRuntimeBackendError:
            evidence = dict(execution.get("evidence") or {})
        result = verify_linux_sandbox_evidence(evidence)
        return AdapterResult("HEALTH", self.target_type, "HEALTHY" if result["verified"] else "UNVERIFIED", result)

    def cancel(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("cancellation reason is required")
        self._backend.stop(self._key(execution))
        return AdapterResult("CANCEL", self.target_type, "CANCELLED", {"reason": reason})

    def revoke(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("revocation reason is required")
        self._backend.stop(self._key(execution))
        return AdapterResult("REVOKE", self.target_type, "REVOKED", {"reason": reason})

    def evidence(self, execution: Dict[str, Any]) -> AdapterResult:
        try:
            evidence = self._backend.evidence(self._key(execution))
        except LinuxRuntimeBackendError:
            evidence = dict(execution.get("evidence") or {})
        result = verify_linux_sandbox_evidence(evidence)
        evidence.update(result)
        evidence.update({"backend": evidence.get("backend", "bwrap"), "authority": "host-observation"})
        return AdapterResult("EVIDENCE", self.target_type, result["enforcement_mode"], evidence)


@dataclass(frozen=True)
class TenantRuntimeBinding:
    """Portable isolation fields required from Kubernetes/MaaS/SaaS adapters."""

    target_type: str
    tenant_id: str
    namespace: str
    service_account: str
    network_policy: str
    resource_quota: str
    storage_binding: str
    kms_key_ref: str
    worker_pool: str = ""
    host_paths: tuple[str, ...] = ()
    socket_mounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        target = str(self.target_type or "").upper()
        if target not in TENANT_TARGET_TYPES:
            raise ValueError("unsupported tenant runtime target type")
        object.__setattr__(self, "target_type", target)
        required = {
            "tenant_id": self.tenant_id, "namespace": self.namespace,
            "service_account": self.service_account, "network_policy": self.network_policy,
            "resource_quota": self.resource_quota, "storage_binding": self.storage_binding,
            "kms_key_ref": self.kms_key_ref,
        }
        missing = sorted(key for key, value in required.items() if not str(value or "").strip())
        if missing:
            raise ValueError("tenant runtime binding is incomplete: " + ",".join(missing))
        normalized_paths = {str(value or "").rstrip("/") or "/" for value in self.host_paths}
        if normalized_paths.intersection(FORBIDDEN_HOST_PATHS):
            raise ValueError("unrestricted host path is forbidden")
        sockets = {str(value or "").lower() for value in self.socket_mounts}
        if any("docker.sock" in value or "containerd.sock" in value or "crio.sock" in value for value in sockets):
            raise ValueError("container runtime socket is forbidden")


def tenant_binding_capabilities(binding: TenantRuntimeBinding) -> Dict[str, Any]:
    """Return admission capabilities without claiming vendor-side creation."""
    return {
        "target_type": binding.target_type,
        "tenant_id": binding.tenant_id,
        "max_isolation_level": "DEDICATED_CONTAINER",
        "enforcement_mode": "UNVERIFIED",
        "required_bindings_present": True,
        "vendor_provisioning_verified": False,
    }


class ReferenceRuntimeAdapter:
    """A non-networking lifecycle reference with fail-closed evidence."""

    def __init__(self, target_type: str) -> None:
        if target_type not in TARGET_TYPES:
            raise ValueError("unsupported deployment target type")
        self.target_type = target_type

    def _result(self, operation: str, status: str, execution: Dict[str, Any]) -> AdapterResult:
        return AdapterResult(
            operation=operation,
            target_type=self.target_type,
            status=status,
            evidence={
                "execution_id": str(execution.get("execution_id") or ""),
                "target_id": str(execution.get("target_id") or ""),
                "isolation_level": str(execution.get("isolation_level") or ""),
                "enforcement_mode": "UNVERIFIED",
                "max_isolation_level": "DOMAIN_ISOLATED",
                "boundaries": [],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "authority": "database",
            },
        )

    def prepare(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("PREPARE", "READY", execution)

    def activate(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("ACTIVATE", "ACTIVE", execution)

    def health(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("HEALTH", "UNKNOWN", execution)

    def cancel(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("cancellation reason is required")
        return self._result("CANCEL", "CANCELLED", execution)

    def revoke(self, execution: Dict[str, Any], reason: str) -> AdapterResult:
        if len(str(reason or "").strip()) < 3:
            raise ValueError("revocation reason is required")
        return self._result("REVOKE", "REVOKED", execution)

    def evidence(self, execution: Dict[str, Any]) -> AdapterResult:
        return self._result("EVIDENCE", "RECORDED", execution)


def reference_adapters() -> Dict[str, RuntimeAdapter]:
    return {target_type: ReferenceRuntimeAdapter(target_type) for target_type in sorted(TARGET_TYPES)}


def local_runtime_adapters() -> Dict[str, RuntimeAdapter]:
    """Adapters available on this host; cloud/container/VM remain contracts only."""
    return {"LOCAL_LINUX_SANDBOX": LinuxRuntimeAdapter()}


def describe_reference_adapters() -> list[Dict[str, Any]]:
    references = [
        {
            "target_type": target_type,
            "reference": True,
            "network_calls": False,
            "enforcement_mode": "UNVERIFIED",
            "max_isolation_level": "DOMAIN_ISOLATED",
            "lifecycle": ["prepare", "activate", "health", "cancel", "revoke", "evidence"],
            "security_note": "参考适配器不创建 OS/容器隔离；权限、凭证和最终状态仍由平台数据库与 Gateway 决定",
        }
        for target_type in sorted(TARGET_TYPES)
    ]
    references.extend({
        "target_type": target_type,
        "reference": True,
        "network_calls": False,
        "enforcement_mode": "UNVERIFIED",
        "max_isolation_level": "DOMAIN_ISOLATED",
        "required_binding_fields": ["tenant_id", "namespace", "service_account", "network_policy",
                                    "resource_quota", "storage_binding", "kms_key_ref"],
        "security_note": "租户字段只定义准入合同；客户适配器仍须提供可验证的容器或 VM 隔离证据",
    } for target_type in sorted(TENANT_TARGET_TYPES))
    return references
