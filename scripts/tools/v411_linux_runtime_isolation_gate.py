#!/usr/bin/env python3.14
"""Exercise the v4.4.11 Linux runtime adapter on a dedicated test host."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import pwd
import grp
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.lib.deployment_adapters import LinuxRuntimeAdapter, LinuxSandboxSpec


BINARIES = ("/bin/bash", "/usr/bin/cat", "/usr/bin/sleep", "/usr/bin/strace", "/usr/bin/touch")


def dependencies(binary: str) -> set[str]:
    output = subprocess.run(["ldd", binary], check=True, capture_output=True, text=True).stdout
    return set(re.findall(r"(?:=>\s+)?(/[^^\s()]+)", output))


def copy_runtime(rootfs: Path) -> None:
    for relative in ("tmp", "workspace", "proc", "dev", "run/secrets", "etc"):
        (rootfs / relative).mkdir(parents=True, exist_ok=True)
    files = set(BINARIES)
    for binary in BINARIES:
        files.update(dependencies(binary))
    for source_text in sorted(files):
        source = Path(source_text)
        if not source.exists():
            continue
        target = rootfs / source.relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.resolve(), target)
    manifest = []
    for path in sorted(item for item in rootfs.rglob("*") if item.is_file()):
        manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  /{path.relative_to(rootfs)}")
    (rootfs / ".cx-rootfs-manifest.sha256").write_text("\n".join(manifest) + "\n", encoding="ascii")


def ensure_identity(uid: int, name: str) -> None:
    try:
        grp.getgrgid(uid)
    except KeyError:
        subprocess.run(["groupadd", "--gid", str(uid), name], check=True)
    try:
        pwd.getpwuid(uid)
    except KeyError:
        subprocess.run(["useradd", "--uid", str(uid), "--gid", str(uid), "--no-create-home",
                        "--shell", "/sbin/nologin", name], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="4.4.11")
    parser.add_argument("--base", type=Path, default=Path("/var/lib/chuanxu-runtime-gate"))
    parser.add_argument("--output", type=Path, default=Path("/tmp/v4.4.11-linux-runtime-isolation.json"))
    parser.add_argument(
        "--network-probe", default="192.0.2.1:9",
        help="host:port used only to prove the sandbox's default-deny network",
    )
    args = parser.parse_args()
    try:
        probe_host, probe_port_text = args.network_probe.rsplit(":", 1)
        probe_port = int(probe_port_text)
    except (ValueError, TypeError) as exc:
        raise SystemExit("--network-probe must use host:port") from exc
    if not re.fullmatch(r"[A-Za-z0-9.-]+", probe_host) or not 1 <= probe_port <= 65535:
        raise SystemExit("--network-probe contains an invalid host or port")
    base = args.base.resolve()
    ensure_identity(10001, "cxgatea")
    ensure_identity(10002, "cxgateb")
    rootfs, work, secrets = base / "rootfs", base / "work-agent-a", base / "secret-agent-a"
    work_b, secrets_b = base / "work-agent-b", base / "secret-agent-b"
    for path in (rootfs, work, secrets, work_b, secrets_b):
        path.mkdir(parents=True, exist_ok=True)
    copy_runtime(rootfs)
    os.chmod(work, 0o770)
    os.chmod(secrets, 0o700)
    os.chmod(work_b, 0o770)
    os.chmod(secrets_b, 0o700)
    os.chown(work, 10001, 10001)
    os.chown(secrets, 10001, 10001)
    os.chown(work_b, 10002, 10002)
    os.chown(secrets_b, 10002, 10002)
    token = secrets / "token"
    token.write_text("agent-a-only\n", encoding="ascii")
    os.chown(token, 10001, 10001)
    os.chmod(token, 0o400)
    token_b = secrets_b / "token"
    token_b.write_text("agent-b-only\n", encoding="ascii")
    os.chown(token_b, 10002, 10002)
    os.chmod(token_b, 0o400)
    host_pid = os.getpid()
    script = f"""
set +e
exec > /workspace/gate-result
test ! -e /proc/{host_pid} && echo process=PASS || echo process=FAIL
test "$(cat /run/secrets/token 2>/dev/null)" = agent-a-only && echo credential=PASS || echo credential=FAIL
touch /etc/cx-forbidden 2>/dev/null && echo filesystem=FAIL || echo filesystem=PASS
echo probe >/dev/tcp/{probe_host}/{probe_port} 2>/dev/null && echo network=FAIL || echo network=PASS
sleep 15 & child=$!
strace -p "$child" -o /workspace/ptrace.trace 2>/workspace/ptrace.error
test $? -ne 0 && echo ptrace=PASS || echo ptrace=FAIL
kill "$child" 2>/dev/null
echo ready=PASS
sleep 30
"""
    spec = LinuxSandboxSpec(
        "GATE_AGENT_A", "GATE_INSTANCE_A", ("/bin/bash", "-c", script),
        10001, 10001, workdir=str(work), rootfs=str(rootfs), credential_dir=str(secrets),
        memory_bytes=64 * 1024 * 1024, pids=16, cpu_seconds=60,
    )
    execution = {"execution_id": "GATE_EXECUTION_A", "sandbox_spec": spec}
    adapter = LinuxRuntimeAdapter()
    started = adapter.activate(execution)
    deadline = time.monotonic() + 10
    result_file = work / "gate-result"
    while time.monotonic() < deadline:
        if result_file.exists() and "ready=PASS" in result_file.read_text(encoding="ascii", errors="replace"):
            break
        time.sleep(0.1)
    evidence = adapter.evidence(execution).evidence
    checks = {
        "adapter_verified": started.status == "ACTIVE" and evidence.get("verified") is True,
        "seccomp_filter": evidence.get("seccomp") is True,
        "no_new_privileges": evidence.get("no_new_privileges") is True,
        "capabilities_dropped": evidence.get("cap_eff") == "0000000000000000",
        "namespaces_private": all((evidence.get("private_namespaces") or {}).values()),
        "rootfs_readonly": evidence.get("readonly_rootfs") is True,
        "network_default_deny": evidence.get("network_default_deny") is True,
        "memory_limit": (evidence.get("cgroup_limits") or {}).get("memory.max") == str(64 * 1024 * 1024),
        "pids_limit": (evidence.get("cgroup_limits") or {}).get("pids.max") == "16",
        "cpu_limit": bool((evidence.get("cgroup_limits") or {}).get("cpu.max")),
        "ptrace_denied": "Operation not permitted" in (work / "ptrace.error").read_text(encoding="utf-8", errors="replace"),
    }
    direct_results = result_file.read_text(encoding="ascii", errors="replace") if result_file.exists() else ""
    for name in ("process", "credential", "filesystem", "network", "ptrace", "ready"):
        checks[f"negative_{name}"] = f"{name}=PASS" in direct_results
    script_b = f"""
set +e
exec > /workspace/gate-result-b
test ! -e /proc/{evidence.get('pid')} && echo cross_process=PASS || echo cross_process=FAIL
test "$(cat /run/secrets/token 2>/dev/null)" = agent-b-only && echo own_credential=PASS || echo own_credential=FAIL
test ! -e /workspace/gate-result && echo cross_workspace=PASS || echo cross_workspace=FAIL
sleep 20
"""
    spec_b = LinuxSandboxSpec(
        "GATE_AGENT_B", "GATE_INSTANCE_B", ("/bin/bash", "-c", script_b),
        10002, 10002, workdir=str(work_b), rootfs=str(rootfs), credential_dir=str(secrets_b),
        memory_bytes=64 * 1024 * 1024, pids=16, cpu_seconds=60,
    )
    execution_b = {"execution_id": "GATE_EXECUTION_B", "sandbox_spec": spec_b}
    started_b = adapter.activate(execution_b)
    deadline = time.monotonic() + 5
    result_b = work_b / "gate-result-b"
    while time.monotonic() < deadline and not result_b.exists():
        time.sleep(0.1)
    direct_b = result_b.read_text(encoding="ascii", errors="replace") if result_b.exists() else ""
    checks["cross_agent_verified"] = started_b.status == "ACTIVE"
    checks["cross_agent_process"] = "cross_process=PASS" in direct_b
    checks["cross_agent_credential"] = "own_credential=PASS" in direct_b
    checks["cross_agent_workspace"] = "cross_workspace=PASS" in direct_b
    adapter.revoke(execution_b, "cross-Agent isolation gate complete")
    adapter.revoke(execution, "isolation gate complete")
    stopped = subprocess.run(["systemctl", "is-active", str(evidence.get("unit"))],
                             check=False, capture_output=True, text=True).stdout.strip() != "active"
    checks["revocation_stops_unit"] = stopped
    payload = {
        "schema": "chuanxu-v411-linux-runtime-isolation/v1", "version": args.version,
        "generated_at": datetime.now(timezone.utc).isoformat(), "host": os.uname().nodename,
        "checks": checks, "evidence": evidence, "passed": all(checks.values()),
        "capacity_claim": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "passed": payload["passed"], "checks": checks}, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
