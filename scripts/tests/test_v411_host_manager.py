import json
from pathlib import Path

import pytest

from shared.lib import host_manager
from shared.lib import host_provisioning


def request(action, **values):
    return {
        "protocol": host_manager.HOST_MANAGER_PROTOCOL,
        "action": action,
        "request_id": "request-123",
        "idempotency_key": "idempotency-123",
        **values,
    }


def test_host_manager_rejects_shell_and_unknown_actions(tmp_path):
    manager = host_manager.HostManager(host_manager.HostManagerConfig(tmp_path, 200000, 200999))
    with pytest.raises(host_manager.HostManagerError, match="unsupported"):
        manager.execute(request("shell", command="rm -rf /"))
    with pytest.raises(host_manager.HostManagerError, match="agent_id"):
        manager._instance_dir("../../root", "instance-1")


def test_provision_derives_paths_and_enforces_reserved_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(host_manager.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host_manager.os, "chown", lambda *_args: None)
    manager = host_manager.HostManager(host_manager.HostManagerConfig(tmp_path, 200000, 200999))
    response = manager.execute(request(
        "provision", agent_id="AGENT-1", instance_id="INSTANCE-1",
        uid=200001, gid=200001,
    ))
    runtime = tmp_path / "agents" / "AGENT-1" / "INSTANCE-1"
    assert response["result"]["runtime_dir"] == str(runtime)
    assert {item.name for item in runtime.iterdir()} == {
        "workspace", "tmp", "secrets", "logs", ".chuanxu-runtime.json"
    }
    marker = json.loads((runtime / ".chuanxu-runtime.json").read_text())
    assert marker["uid"] == 200001
    with pytest.raises(host_manager.HostManagerError, match="reserved"):
        manager.execute(request(
            "provision", request_id="request-124", idempotency_key="idempotency-124",
            agent_id="AGENT-2", instance_id="INSTANCE-2", uid=1001, gid=1001,
        ))


def test_release_is_bounded_to_managed_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(host_manager.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host_manager.os, "chown", lambda *_args: None)
    manager = host_manager.HostManager(host_manager.HostManagerConfig(tmp_path, 200000, 200999))
    manager.execute(request("provision", agent_id="AGENT-1", instance_id="INSTANCE-1", uid=200001, gid=200001))
    released = manager.execute(request(
        "release", request_id="request-125", idempotency_key="idempotency-125",
        agent_id="AGENT-1", instance_id="INSTANCE-1",
    ))
    assert released["result"]["state"] == "RELEASED"
    assert not (tmp_path / "agents" / "AGENT-1" / "INSTANCE-1").exists()


def test_preflight_response_has_all_required_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(host_manager, "_glibc_version", lambda: (2, 34))
    monkeypatch.setattr(host_manager, "_os_release", lambda path="": {"ID": "ol", "VERSION_ID": "9.8"})
    monkeypatch.setattr(host_manager.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(host_manager.ctypes, "CDLL", lambda name: object())
    original_is_file = Path.is_file
    original_is_dir = Path.is_dir
    original_read = Path.read_text
    monkeypatch.setattr(Path, "is_file", lambda self: True if str(self).endswith("cgroup.controllers") else original_is_file(self))
    monkeypatch.setattr(Path, "is_dir", lambda self: True if str(self) == "/run/systemd/system" else original_is_dir(self))
    monkeypatch.setattr(Path, "read_text", lambda self, **kwargs: "cpu memory pids" if str(self).endswith("cgroup.controllers") else original_read(self, **kwargs))
    result = host_manager.collect_preflight()
    assert result["passed"] is True
    assert all(result["checks"].values())


class _ReceiptTx:
    def __init__(self):
        self.statements = []

    def query_one(self, sql, params=None):
        return None

    def execute(self, sql, params=None):
        self.statements.append((sql, params or {}))


def test_token_authenticated_receipt_requires_full_lifecycle(monkeypatch):
    evidence = {
        "passed": True,
        "checks": {name: True for name in (
            "linux_x86_64", "glibc_2_34", "systemd", "cgroup_v2", "bubblewrap", "libseccomp"
        )},
    }
    with pytest.raises(host_provisioning.HostProvisioningError, match="lifecycle"):
        host_provisioning.record_authenticated_host_receipt(
            "NODE-1", evidence, lifecycle_passed=False,
            root_remote_login="DISABLED", recovery_channel="console:vm-1",
            host_manager_version="v4.4.11",
        )
    tx = _ReceiptTx()
    monkeypatch.setattr(host_provisioning.connection, "execute_transaction_callback", lambda callback: callback(tx))
    monkeypatch.setattr(host_provisioning, "_audit", lambda *args: None)
    result = host_provisioning.record_authenticated_host_receipt(
        "NODE-1", evidence, lifecycle_passed=True,
        root_remote_login="DISABLED", recovery_channel="console:vm-1",
        host_manager_version="v4.4.11",
    )
    assert result["bootstrap_state"] == "VERIFIED"
    assert any("CX_RUNTIME_HOST_PROFILES" in sql for sql, _ in tx.statements)
    assert any("RUNTIME_VERIFIED" in sql for sql, _ in tx.statements)
