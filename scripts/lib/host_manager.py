"""Root-owned structured host operations for Agent runtime provisioning.

The module is intentionally transport-neutral. A systemd service can expose it
through a protected Unix socket; callers never submit shell text or host paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Any, Mapping


HOST_MANAGER_PROTOCOL = "chuanxu-host-manager/v1"
SUPPORTED_ACTIONS = frozenset({"preflight", "provision", "release", "revoke", "status"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MIN_GLIBC = (2, 34)


class HostManagerError(ValueError):
    pass


def _identifier(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise HostManagerError(f"invalid {field}")
    return text


def _glibc_version() -> tuple[int, int] | None:
    name, version = platform.libc_ver()
    match = re.match(r"^(\d+)\.(\d+)", version or "")
    return (int(match.group(1)), int(match.group(2))) if name.lower() == "glibc" and match else None


def _os_release(path: str = "/etc/os-release") -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def collect_preflight() -> dict[str, Any]:
    """Collect deterministic host capability evidence without changing state."""
    glibc = _glibc_version()
    release = _os_release()
    cgroup = Path("/sys/fs/cgroup/cgroup.controllers")
    controllers = set(cgroup.read_text(encoding="ascii").split()) if cgroup.is_file() else set()
    commands = {
        name: bool(shutil.which(name))
        for name in ("systemctl", "systemd-run", "bwrap")
    }
    try:
        ctypes.CDLL("libseccomp.so.2")
        seccomp = True
    except OSError:
        seccomp = False
    checks = {
        "linux_x86_64": platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"},
        "glibc_2_34": bool(glibc and glibc >= _MIN_GLIBC),
        "systemd": commands["systemctl"] and commands["systemd-run"] and Path("/run/systemd/system").is_dir(),
        "cgroup_v2": {"cpu", "memory", "pids"}.issubset(controllers),
        "bubblewrap": commands["bwrap"],
        "libseccomp": seccomp,
    }
    return {
        "protocol": HOST_MANAGER_PROTOCOL,
        "supported_baseline": "RHEL 9.8+ (Oracle Linux 9.8+) or equivalent",
        "os_id": release.get("ID", ""),
        "os_version": release.get("VERSION_ID", ""),
        "kernel": platform.release(),
        "glibc": ".".join(map(str, glibc)) if glibc else "unknown",
        "controllers": sorted(controllers),
        "checks": checks,
        "passed": all(checks.values()),
    }


@dataclass(frozen=True)
class HostManagerConfig:
    runtime_root: Path = Path("/var/lib/chuanxu-runtime")
    uid_min: int = 200000
    uid_max: int = 299999

    def validate_identity(self, uid: int, gid: int) -> None:
        if uid != gid or not self.uid_min <= uid <= self.uid_max:
            raise HostManagerError("UID/GID is outside the reserved runtime range")


class HostManager:
    def __init__(self, config: HostManagerConfig | None = None) -> None:
        self.config = config or HostManagerConfig()

    def _instance_dir(self, agent_id: str, instance_id: str) -> Path:
        agent = _identifier(agent_id, "agent_id")
        instance = _identifier(instance_id, "instance_id")
        return self.config.runtime_root / "agents" / agent / instance

    @staticmethod
    def _require_root() -> None:
        if os.geteuid() != 0:
            raise PermissionError("host mutation requires the root-owned Host Manager")

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("protocol") != HOST_MANAGER_PROTOCOL:
            raise HostManagerError("unsupported Host Manager protocol")
        action = str(request.get("action") or "").lower()
        if action not in SUPPORTED_ACTIONS:
            raise HostManagerError("unsupported Host Manager action")
        request_id = _identifier(request.get("request_id"), "request_id")
        idempotency_key = _identifier(request.get("idempotency_key"), "idempotency_key")
        if action == "preflight":
            result = collect_preflight()
        else:
            self._require_root()
            handler = getattr(self, f"_{action}")
            result = handler(request)
        return {"protocol": HOST_MANAGER_PROTOCOL, "request_id": request_id,
                "idempotency_key": idempotency_key, "action": action,
                "status": "SUCCEEDED", "result": result}

    def _provision(self, request: Mapping[str, Any]) -> dict[str, Any]:
        uid, gid = int(request.get("uid") or 0), int(request.get("gid") or 0)
        self.config.validate_identity(uid, gid)
        target = self._instance_dir(str(request.get("agent_id") or ""), str(request.get("instance_id") or ""))
        for name, mode in (("workspace", 0o700), ("tmp", 0o700), ("secrets", 0o700), ("logs", 0o700)):
            path = target / name
            path.mkdir(mode=mode, parents=True, exist_ok=True)
            os.chmod(path, mode)
            os.chown(path, uid, gid)
        marker = target / ".chuanxu-runtime.json"
        marker.write_text(json.dumps({"agent_id": request["agent_id"], "instance_id": request["instance_id"],
                                      "uid": uid, "gid": gid}, sort_keys=True) + "\n", encoding="ascii")
        os.chmod(marker, 0o600)
        os.chown(marker, uid, gid)
        return {"runtime_dir": str(target), "uid": uid, "gid": gid, "state": "PROVISIONED"}

    def _status(self, request: Mapping[str, Any]) -> dict[str, Any]:
        target = self._instance_dir(str(request.get("agent_id") or ""), str(request.get("instance_id") or ""))
        marker = target / ".chuanxu-runtime.json"
        return {"runtime_dir": str(target), "provisioned": marker.is_file()}

    def _revoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        from .linux_runtime_backend import safe_unit_name
        agent = _identifier(request.get("agent_id"), "agent_id")
        instance = _identifier(request.get("instance_id"), "instance_id")
        unit = safe_unit_name(agent, instance)
        subprocess.run(["/usr/bin/systemctl", "stop", unit], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return {"unit": unit, "state": "REVOKED"}

    def _release(self, request: Mapping[str, Any]) -> dict[str, Any]:
        target = self._instance_dir(str(request.get("agent_id") or ""), str(request.get("instance_id") or ""))
        marker = target / ".chuanxu-runtime.json"
        if not marker.is_file():
            return {"runtime_dir": str(target), "state": "RELEASED", "idempotent": True}
        shutil.rmtree(target)
        return {"runtime_dir": str(target), "state": "RELEASED"}
