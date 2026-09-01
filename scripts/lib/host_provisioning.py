"""Governed host bootstrap state and per-Agent UID/GID leases."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Mapping

from . import connection, identity_api


class HostProvisioningError(ValueError):
    pass


def _row(value: Any) -> dict[str, Any]:
    return identity_api._row(value) or {}


def _rows(values: Any) -> list[dict[str, Any]]:
    return [identity_api._row(value) for value in (values or [])]


def _require(actor: str, action: str = "hosts.manage") -> None:
    if identity_api.effective_access(actor, action).get("decision") != "ALLOW":
        raise PermissionError("host provisioning permission denied")


def _audit(tx: Any, actor: str, action: str, resource_type: str,
           resource_id: str, decision: str, reason: str) -> None:
    identity_api._audit_tx(tx, actor, action, resource_type, resource_id,
                           decision, reason[:2000])


def list_runtime_hosts(actor: str) -> list[dict[str, Any]]:
    _require(actor, "hosts.read")
    return _rows(connection.execute_query(
        "SELECT p.NODE_ID,n.NODE_KEY,n.HOST_REFERENCE,p.HOST_MANAGER_VERSION,p.BOOTSTRAP_STATE,"
        "p.ROOT_REMOTE_LOGIN,p.RECOVERY_CHANNEL,p.UID_MIN,p.UID_MAX,p.PREFLIGHT_DIGEST,"
        "p.LAST_PREFLIGHT_AT,p.UPDATED_AT FROM CX_RUNTIME_HOST_PROFILES p "
        "JOIN CX_MANAGED_NODES n ON n.NODE_ID=p.NODE_ID WHERE n.STATUS<>'RETIRED' ORDER BY n.NODE_KEY"
    ))


def record_preflight(actor: str, node_id: str, evidence: Mapping[str, Any],
                     reason: str) -> dict[str, Any]:
    _require(actor)
    why = str(reason or "").strip()
    if len(why) < 3:
        raise HostProvisioningError("preflight reason is required")
    checks = evidence.get("checks")
    if not isinstance(checks, Mapping):
        raise HostProvisioningError("structured preflight checks are required")
    required = {"linux_x86_64", "glibc_2_34", "systemd", "cgroup_v2", "bubblewrap", "libseccomp"}
    passed = evidence.get("passed") is True and all(checks.get(name) is True for name in required)
    digest = "sha256:" + hashlib.sha256(
        json.dumps(dict(evidence), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    state = "PREFLIGHT_PASSED" if passed else "PREFLIGHT_FAILED"

    def work(tx: Any) -> None:
        node = _row(tx.query_one("SELECT NODE_ID FROM CX_MANAGED_NODES WHERE NODE_ID=:id FOR UPDATE", {"id": node_id}))
        if not node:
            raise HostProvisioningError("managed node is unavailable")
        existing = _row(tx.query_one("SELECT NODE_ID FROM CX_RUNTIME_HOST_PROFILES WHERE NODE_ID=:id", {"id": node_id}))
        values = {"id": node_id, "version": str(evidence.get("protocol") or "")[:128],
                  "state": state, "digest": digest, "actor": actor}
        if existing:
            tx.execute("UPDATE CX_RUNTIME_HOST_PROFILES SET HOST_MANAGER_VERSION=:version,BOOTSTRAP_STATE=:state,"
                       "PREFLIGHT_DIGEST=:digest,LAST_PREFLIGHT_AT=CURRENT_TIMESTAMP,UPDATED_BY=:actor,"
                       "UPDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:id", values)
        else:
            tx.execute("INSERT INTO CX_RUNTIME_HOST_PROFILES(NODE_ID,HOST_MANAGER_VERSION,BOOTSTRAP_STATE,"
                       "ROOT_REMOTE_LOGIN,UID_MIN,UID_MAX,PREFLIGHT_DIGEST,CREATED_BY,UPDATED_BY,LAST_PREFLIGHT_AT) "
                       "VALUES (:id,:version,:state,'ENABLED',200000,299999,:digest,:actor,:actor,CURRENT_TIMESTAMP)", values)
        _audit(tx, actor, "RUNTIME_HOST_PREFLIGHT", "MANAGED_NODE", node_id,
               "ALLOW" if passed else "ERROR", why)
    connection.execute_transaction_callback(work)
    return {"node_id": node_id, "bootstrap_state": state,
            "preflight_digest": digest, "passed": passed}


def complete_bootstrap(actor: str, node_id: str, *, host_manager_version: str,
                       recovery_channel: str, root_remote_login: str,
                       uid_min: int = 200000, uid_max: int = 299999,
                       reason: str) -> dict[str, Any]:
    _require(actor)
    why = str(reason or "").strip()
    recovery = str(recovery_channel or "").strip()
    root_state = str(root_remote_login or "").upper()
    if len(why) < 3 or len(recovery) < 3:
        raise HostProvisioningError("reason and recovery channel are required")
    if root_state != "DISABLED":
        raise HostProvisioningError("remote root login must be disabled before bootstrap completion")
    if uid_min < 100000 or uid_max <= uid_min or uid_max - uid_min < 999:
        raise HostProvisioningError("a reserved UID/GID range of at least 1000 identities is required")

    def work(tx: Any) -> None:
        profile = _row(tx.query_one(
            "SELECT NODE_ID,BOOTSTRAP_STATE FROM CX_RUNTIME_HOST_PROFILES WHERE NODE_ID=:id FOR UPDATE",
            {"id": node_id}))
        if not profile or str(profile.get("bootstrap_state") or "") != "PREFLIGHT_PASSED":
            raise HostProvisioningError("a passing host preflight is required")
        tx.execute("UPDATE CX_RUNTIME_HOST_PROFILES SET HOST_MANAGER_VERSION=:version,"
                   "BOOTSTRAP_STATE='VERIFIED',ROOT_REMOTE_LOGIN='DISABLED',RECOVERY_CHANNEL=:recovery,"
                   "UID_MIN=:uid_min,UID_MAX=:uid_max,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:id",
                   {"id": node_id, "version": str(host_manager_version)[:128], "recovery": recovery[:512],
                    "uid_min": uid_min, "uid_max": uid_max, "actor": actor})
        tx.execute("UPDATE CX_MANAGED_NODES SET STATUS='VALIDATED',VALIDATION_STATE='RUNTIME_VERIFIED' WHERE NODE_ID=:id", {"id": node_id})
        _audit(tx, actor, "RUNTIME_HOST_BOOTSTRAP_COMPLETE", "MANAGED_NODE", node_id, "ALLOW", why)
    connection.execute_transaction_callback(work)
    return {"node_id": node_id, "bootstrap_state": "VERIFIED",
            "root_remote_login": "DISABLED", "uid_min": uid_min, "uid_max": uid_max}


def record_authenticated_host_receipt(node_id: str, evidence: Mapping[str, Any], *,
                                      lifecycle_passed: bool,
                                      root_remote_login: str,
                                      recovery_channel: str,
                                      host_manager_version: str) -> dict[str, Any]:
    """Persist evidence received through an already verified onboarding token."""
    checks = evidence.get("checks")
    required = {"linux_x86_64", "glibc_2_34", "systemd", "cgroup_v2", "bubblewrap", "libseccomp"}
    if (not isinstance(checks, Mapping) or evidence.get("passed") is not True
            or not all(checks.get(name) is True for name in required)):
        raise HostProvisioningError("Host Manager preflight evidence is incomplete")
    if lifecycle_passed is not True:
        raise HostProvisioningError("host lifecycle verification has not passed")
    if str(root_remote_login or "").upper() != "DISABLED":
        raise HostProvisioningError("remote root login must be disabled")
    recovery = str(recovery_channel or "").strip()
    if len(recovery) < 3:
        raise HostProvisioningError("a recovery channel is required")
    digest = "sha256:" + hashlib.sha256(
        json.dumps(dict(evidence), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    actor = "POOL_NODE:" + str(node_id)

    def work(tx: Any) -> None:
        existing = _row(tx.query_one("SELECT NODE_ID FROM CX_RUNTIME_HOST_PROFILES WHERE NODE_ID=:id FOR UPDATE", {"id": node_id}))
        values = {"id": node_id, "version": str(host_manager_version)[:128], "recovery": recovery[:512],
                  "digest": digest, "actor": actor}
        if existing:
            tx.execute("UPDATE CX_RUNTIME_HOST_PROFILES SET HOST_MANAGER_VERSION=:version,BOOTSTRAP_STATE='VERIFIED',"
                       "ROOT_REMOTE_LOGIN='DISABLED',RECOVERY_CHANNEL=:recovery,PREFLIGHT_DIGEST=:digest,"
                       "LAST_PREFLIGHT_AT=CURRENT_TIMESTAMP,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:id", values)
        else:
            tx.execute("INSERT INTO CX_RUNTIME_HOST_PROFILES(NODE_ID,HOST_MANAGER_VERSION,BOOTSTRAP_STATE,"
                       "ROOT_REMOTE_LOGIN,RECOVERY_CHANNEL,UID_MIN,UID_MAX,PREFLIGHT_DIGEST,CREATED_BY,UPDATED_BY,LAST_PREFLIGHT_AT) "
                       "VALUES (:id,:version,'VERIFIED','DISABLED',:recovery,200000,299999,:digest,:actor,:actor,CURRENT_TIMESTAMP)", values)
        tx.execute("UPDATE CX_MANAGED_NODES SET STATUS='VALIDATED',VALIDATION_STATE='RUNTIME_VERIFIED',"
                   "LAST_VALIDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:id", {"id": node_id})
        _audit(tx, actor, "RUNTIME_HOST_AUTHENTICATED_RECEIPT", "MANAGED_NODE", node_id, "ALLOW", "token-authenticated Host Manager evidence")
    connection.execute_transaction_callback(work)
    return {"node_id": node_id, "bootstrap_state": "VERIFIED",
            "root_remote_login": "DISABLED", "preflight_digest": digest}


def allocate_identity(actor: str, node_id: str, agent_id: str,
                      instance_id: str, reason: str) -> dict[str, Any]:
    _require(actor)
    if len(str(reason or "").strip()) < 3 or not str(agent_id or "").strip() or not str(instance_id or "").strip():
        raise HostProvisioningError("Agent, instance, and allocation reason are required")
    lease_id = "UIDLEASE_" + secrets.token_hex(16)

    def work(tx: Any) -> dict[str, Any]:
        profile = _row(tx.query_one(
            "SELECT NODE_ID,BOOTSTRAP_STATE,UID_MIN,UID_MAX FROM CX_RUNTIME_HOST_PROFILES WHERE NODE_ID=:id FOR UPDATE",
            {"id": node_id}))
        if not profile or str(profile.get("bootstrap_state") or "") != "VERIFIED":
            raise HostProvisioningError("runtime host is not verified")
        existing = _row(tx.query_one(
            "SELECT LEASE_ID,RUNTIME_UID,RUNTIME_GID,STATUS FROM CX_RUNTIME_UID_LEASES "
            "WHERE NODE_ID=:node AND AGENT_ID=:agent AND INSTANCE_ID=:instance AND STATUS='ACTIVE'",
            {"node": node_id, "agent": agent_id, "instance": instance_id}))
        if existing:
            return existing
        used = {int(_row(item).get("runtime_uid") or 0) for item in tx.query(
            "SELECT RUNTIME_UID FROM CX_RUNTIME_UID_LEASES WHERE NODE_ID=:node AND STATUS='ACTIVE'",
            {"node": node_id})}
        uid = next((candidate for candidate in range(int(profile["uid_min"]), int(profile["uid_max"]) + 1)
                    if candidate not in used), None)
        if uid is None:
            raise HostProvisioningError("runtime UID/GID pool is exhausted")
        tx.execute("INSERT INTO CX_RUNTIME_UID_LEASES(LEASE_ID,NODE_ID,AGENT_ID,INSTANCE_ID,RUNTIME_UID,"
                   "RUNTIME_GID,STATUS,CREATED_BY,REASON) VALUES (:lease,:node,:agent,:instance,:uid,:gid,'ACTIVE',:actor,:reason)",
                   {"lease": lease_id, "node": node_id, "agent": str(agent_id)[:128],
                    "instance": str(instance_id)[:128], "uid": uid, "gid": uid,
                    "actor": actor, "reason": str(reason)[:2000]})
        _audit(tx, actor, "RUNTIME_IDENTITY_ALLOCATE", "RUNTIME_UID_LEASE", lease_id, "ALLOW", str(reason))
        return {"lease_id": lease_id, "runtime_uid": uid, "runtime_gid": uid, "status": "ACTIVE"}
    return connection.execute_transaction_callback(work)


def release_identity(actor: str, lease_id: str, reason: str) -> dict[str, Any]:
    _require(actor)
    if len(str(reason or "").strip()) < 3:
        raise HostProvisioningError("release reason is required")

    def work(tx: Any) -> dict[str, Any]:
        lease = _row(tx.query_one(
            "SELECT LEASE_ID,NODE_ID,AGENT_ID,INSTANCE_ID,STATUS FROM CX_RUNTIME_UID_LEASES "
            "WHERE LEASE_ID=:id FOR UPDATE", {"id": lease_id}))
        if not lease:
            return {"lease_id": lease_id, "status": "RELEASED", "idempotent": True}
        if str(lease.get("status") or "") != "ACTIVE":
            return lease
        active = _row(tx.query_one(
            "SELECT CONTRACT_ID FROM CX_RUNTIME_ISOLATION_CONTRACTS WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance "
            "AND STATUS IN ('ACTIVE','DRAIN','ISOLATED')",
            {"agent": lease["agent_id"], "instance": lease["instance_id"]}))
        if active:
            raise HostProvisioningError("revoke and terminate the runtime before releasing its identity")
        # The immutable audit event retains release history. Removing the
        # current lease row makes the numeric identity reusable without
        # weakening the database uniqueness constraint for active leases.
        tx.execute("DELETE FROM CX_RUNTIME_UID_LEASES WHERE LEASE_ID=:id", {"id": lease_id})
        _audit(tx, actor, "RUNTIME_IDENTITY_RELEASE", "RUNTIME_UID_LEASE", lease_id, "ALLOW", str(reason))
        return {**lease, "status": "RELEASED"}
    return connection.execute_transaction_callback(work)
