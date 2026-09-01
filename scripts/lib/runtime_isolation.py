"""Fail-closed runtime isolation contracts for v4.4.11.

This module deliberately does not pretend to create a sandbox.  Deployment
adapters produce the evidence, and this contract validates that evidence before
an Agent Instance is admitted.  Database authorization remains independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Mapping


ISOLATION_LEVELS = (
    "SHARED",
    "DOMAIN_ISOLATED",
    "DEDICATED_RUNTIME",
    "DEDICATED_CONTAINER",
    "DEDICATED_VM",
)
_RANK = {value: index for index, value in enumerate(ISOLATION_LEVELS)}
ENFORCEMENT_MODES = frozenset({"VERIFIED", "UNVERIFIED", "NOT_APPLICABLE"})
BOUNDARIES = frozenset({"process", "filesystem", "ipc", "network", "resource", "credential"})
CONTRACT_STATES = frozenset({"ACTIVE", "DRAIN", "ISOLATED", "TERMINATED", "REVOKED"})
_STATE_TRANSITIONS = {
    "ACTIVE": frozenset({"DRAIN", "ISOLATED", "REVOKED"}),
    "DRAIN": frozenset({"ACTIVE", "ISOLATED", "TERMINATED", "REVOKED"}),
    "ISOLATED": frozenset({"TERMINATED", "REVOKED"}),
    "TERMINATED": frozenset(),
    "REVOKED": frozenset(),
}


class IsolationError(ValueError):
    """Raised when an Agent runtime cannot satisfy its isolation contract."""


@dataclass(frozen=True)
class RuntimeIsolationContract:
    isolation_level: str
    enforcement_mode: str
    runtime_adapter: str
    runtime_identity: str = ""
    evidence_ref: str = ""
    boundaries: frozenset[str] = field(default_factory=frozenset)
    policy_digest: str = ""
    rootfs_digest: str = ""

    def __post_init__(self) -> None:
        level = str(self.isolation_level or "").upper()
        mode = str(self.enforcement_mode or "").upper()
        if level not in _RANK:
            raise IsolationError("unknown runtime isolation level")
        if mode not in ENFORCEMENT_MODES:
            raise IsolationError("unknown runtime enforcement mode")
        object.__setattr__(self, "isolation_level", level)
        object.__setattr__(self, "enforcement_mode", mode)
        object.__setattr__(self, "boundaries", frozenset(str(item).lower() for item in self.boundaries))

    @property
    def rank(self) -> int:
        return _RANK[self.isolation_level]


def validate_admission(
    contract: RuntimeIsolationContract,
    *,
    requested_level: str | None = None,
    external_agent: bool = False,
    adapter_capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate runtime evidence before a workload receives executable work.

    ``adapter_capabilities`` is intentionally explicit.  A database row or a
    UI-selected label alone cannot promote an unverified runtime.
    """
    requested = str(requested_level or contract.isolation_level).upper()
    if requested not in _RANK:
        raise IsolationError("unknown requested runtime isolation level")
    if contract.rank < _RANK[requested]:
        raise IsolationError("runtime isolation is weaker than requested")
    if external_agent and contract.rank < _RANK["DEDICATED_CONTAINER"]:
        raise IsolationError("external Agent requires container or VM isolation")
    if contract.rank >= _RANK["DEDICATED_CONTAINER"]:
        if contract.enforcement_mode != "VERIFIED":
            raise IsolationError("container or VM isolation requires verified evidence")
        missing = BOUNDARIES.difference(contract.boundaries)
        if missing:
            raise IsolationError("runtime isolation evidence is incomplete: " + ",".join(sorted(missing)))
        if not contract.runtime_identity or not contract.evidence_ref:
            raise IsolationError("runtime identity and evidence reference are required")
    capabilities = dict(adapter_capabilities or {})
    adapter_level = str(capabilities.get("max_isolation_level") or "").upper()
    if adapter_level and adapter_level in _RANK and _RANK[adapter_level] < contract.rank:
        raise IsolationError("deployment adapter cannot enforce requested isolation")
    if capabilities.get("enforcement_mode") and str(capabilities["enforcement_mode"]).upper() != contract.enforcement_mode:
        raise IsolationError("runtime enforcement evidence does not match adapter")
    return {
        "admitted": True,
        "isolation_level": contract.isolation_level,
        "enforcement_mode": contract.enforcement_mode,
        "runtime_adapter": contract.runtime_adapter,
        "runtime_identity": contract.runtime_identity,
        "evidence_ref": contract.evidence_ref,
    }


def detect_drift(contract: RuntimeIsolationContract, observed: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic drift report; callers must drain on drift."""
    checks = {
        "runtime_identity": contract.runtime_identity,
        "policy_digest": contract.policy_digest,
        "rootfs_digest": contract.rootfs_digest,
    }
    mismatches = [
        key for key, expected in checks.items()
        if expected and str(observed.get(key) or "") != str(expected)
    ]
    return {
        "drift": bool(mismatches),
        "mismatches": mismatches,
        "next_state": "DRAIN" if mismatches else "ACTIVE",
    }


def required_boundaries(level: str) -> frozenset[str]:
    """Expose the boundary contract for deployment adapters and UI."""
    normalized = str(level or "").upper()
    if normalized not in _RANK:
        raise IsolationError("unknown runtime isolation level")
    return BOUNDARIES if _RANK[normalized] >= _RANK["DEDICATED_CONTAINER"] else frozenset()


def collect_linux_runtime_evidence(*, proc_root: str = "/proc", cgroup_root: str = "/sys/fs/cgroup") -> dict[str, Any]:
    """Collect non-secret evidence for the current Linux runtime.

    This is an observation helper, not a sandbox.  It intentionally reports
    what is observable so an adapter can refuse admission when a stronger
    container/VM boundary is required.
    """
    proc = Path(proc_root)
    namespaces = {}
    for name in ("pid", "mnt", "net", "user", "ipc", "uts"):
        link = proc / "self" / "ns" / name
        try:
            namespaces[name] = os.readlink(link)
        except OSError:
            namespaces[name] = ""
    uid = ""
    status = proc / "self" / "status"
    try:
        for line in status.read_text(encoding="ascii", errors="replace").splitlines():
            if line.startswith("Uid:"):
                uid = line.split()[1]
                break
    except OSError:
        pass
    return {
        "runtime_identity": f"pid:{os.getpid()}:uid:{uid or os.getuid()}",
        "uid": uid or str(os.getuid()),
        "namespaces": namespaces,
        "cgroup_root": str(cgroup_root),
        "proc_observed": status.is_file(),
        "sandbox_verified": False,
        "enforcement_mode": "UNVERIFIED",
    }


def linux_evidence_boundaries(evidence: Mapping[str, Any]) -> frozenset[str]:
    """Translate adapter evidence into boundaries conservatively."""
    if str(evidence.get("enforcement_mode") or "").upper() != "VERIFIED":
        return frozenset()
    values = evidence.get("boundaries")
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(item).lower() for item in values).intersection(BOUNDARIES)


def persist_contract(actor: str, agent_id: str, instance_id: str,
                     contract: RuntimeIsolationContract) -> dict[str, Any]:
    """Persist verified or explicitly unverified isolation facts."""
    import json
    import secrets
    from . import connection, identity_api

    if identity_api.effective_access(actor, "agents.manage").get("decision") != "ALLOW":
        raise PermissionError("runtime isolation contract permission denied")
    agent = str(agent_id or "").strip()
    instance = str(instance_id or "").strip()
    if not agent or not instance:
        raise IsolationError("Agent and instance are required")
    contract_id = "RIC_" + secrets.token_hex(20)

    def work(tx: Any) -> None:
        existing = tx.query_one(
            "SELECT CONTRACT_ID,VERSION FROM CX_RUNTIME_ISOLATION_CONTRACTS "
            "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance FOR UPDATE",
            {"agent": agent, "instance": instance},
        )
        values = {"agent": agent, "instance": instance, "level": contract.isolation_level,
                  "mode": contract.enforcement_mode, "adapter": contract.runtime_adapter,
                  "identity": contract.runtime_identity or None,
                  "boundaries": json.dumps(sorted(contract.boundaries), separators=(",", ":")),
                  "policy": contract.policy_digest or None, "rootfs": contract.rootfs_digest or None,
                  "evidence": contract.evidence_ref or None, "actor": actor}
        if existing:
            tx.execute(
                "UPDATE CX_RUNTIME_ISOLATION_CONTRACTS SET ISOLATION_LEVEL=:level,ENFORCEMENT_MODE=:mode,"
                "RUNTIME_ADAPTER=:adapter,RUNTIME_IDENTITY=:identity,BOUNDARIES_JSON=:boundaries,"
                "POLICY_DIGEST=:policy,ROOTFS_DIGEST=:rootfs,EVIDENCE_REF=:evidence,STATUS='ACTIVE',"
                "VERSION=VERSION+1,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP "
                "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance",
                values,
            )
        else:
            tx.execute(
                "INSERT INTO CX_RUNTIME_ISOLATION_CONTRACTS(CONTRACT_ID,AGENT_ID,INSTANCE_ID,ISOLATION_LEVEL,"
                "ENFORCEMENT_MODE,RUNTIME_ADAPTER,RUNTIME_IDENTITY,BOUNDARIES_JSON,POLICY_DIGEST,ROOTFS_DIGEST,"
                "EVIDENCE_REF,STATUS,CREATED_BY,UPDATED_BY) VALUES "
                "(:id,:agent,:instance,:level,:mode,:adapter,:identity,:boundaries,:policy,:rootfs,:evidence,'ACTIVE',:actor,:actor)",
                {"id": contract_id, **values},
            )
        identity_api._audit_tx(tx, actor, "RUNTIME_ISOLATION_CONTRACT", "AGENT_INSTANCE", instance,
                               "ALLOW", f"{contract.isolation_level}:{contract.enforcement_mode}")

    connection.execute_transaction_callback(work)
    return {"agent_id": agent, "instance_id": instance, "isolation_level": contract.isolation_level,
            "enforcement_mode": contract.enforcement_mode, "status": "ACTIVE"}


def get_contract(agent_id: str, instance_id: str) -> dict[str, Any]:
    """Return the current contract without treating a missing row as SHARED."""
    import json
    from . import connection, identity_api

    row = identity_api._row(connection.execute_query_one(
        "SELECT CONTRACT_ID,AGENT_ID,INSTANCE_ID,ISOLATION_LEVEL,ENFORCEMENT_MODE,RUNTIME_ADAPTER,"
        "RUNTIME_IDENTITY,BOUNDARIES_JSON,POLICY_DIGEST,ROOTFS_DIGEST,EVIDENCE_REF,STATUS,VERSION,UPDATED_AT "
        "FROM CX_RUNTIME_ISOLATION_CONTRACTS WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance",
        {"agent": str(agent_id or "").strip(), "instance": str(instance_id or "").strip()},
    ))
    if not row:
        raise IsolationError("runtime isolation contract is unavailable")
    try:
        row["boundaries"] = json.loads(str(row.pop("boundaries_json", "[]") or "[]"))
    except (TypeError, ValueError):
        row["boundaries"] = []
    return row


def heartbeat_contract(agent_id: str, instance_id: str, observed: Mapping[str, Any]) -> dict[str, Any]:
    """Compare signed adapter observations and drain the contract on drift.

    The caller is responsible for authenticating the Agent Instance before
    invoking this function.  Once status changes to DRAIN, Gateway token and
    work admission checks reject the instance until an administrator records
    a new verified contract.
    """
    from . import connection

    current = get_contract(agent_id, instance_id)
    if str(current.get("status") or "").upper() != "ACTIVE":
        return {"accepted": False, "status": str(current.get("status") or ""), "drift": False}
    contract = RuntimeIsolationContract(
        isolation_level=str(current.get("isolation_level") or ""),
        enforcement_mode=str(current.get("enforcement_mode") or ""),
        runtime_adapter=str(current.get("runtime_adapter") or ""),
        runtime_identity=str(current.get("runtime_identity") or ""),
        evidence_ref=str(current.get("evidence_ref") or ""),
        boundaries=frozenset(current.get("boundaries") or []),
        policy_digest=str(current.get("policy_digest") or ""),
        rootfs_digest=str(current.get("rootfs_digest") or ""),
    )
    report = detect_drift(contract, observed)
    if not report["drift"]:
        return {"accepted": True, "status": "ACTIVE", **report}
    changed = connection.execute(
        "UPDATE CX_RUNTIME_ISOLATION_CONTRACTS SET STATUS='DRAIN',VERSION=VERSION+1,UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance AND STATUS='ACTIVE' AND VERSION=:version",
        {"agent": agent_id, "instance": instance_id, "version": int(current.get("version") or 0)},
    )
    if int(changed or 0) != 1:
        raise IsolationError("runtime isolation contract changed concurrently")
    return {"accepted": False, "status": "DRAIN", **report}


def transition_contract(actor: str, agent_id: str, instance_id: str, target_state: str,
                        reason: str, expected_version: int) -> dict[str, Any]:
    """Apply a governed drain/isolate/terminate/revoke transition."""
    from . import connection, identity_api

    if identity_api.effective_access(actor, "agents.manage").get("decision") != "ALLOW":
        raise PermissionError("runtime isolation lifecycle permission denied")
    target = str(target_state or "").upper()
    if target not in CONTRACT_STATES:
        raise IsolationError("unknown runtime isolation state")
    if len(str(reason or "").strip()) < 3:
        raise IsolationError("runtime isolation transition reason is required")

    def work(tx: Any) -> dict[str, Any]:
        row = identity_api._row(tx.query_one(
            "SELECT STATUS,VERSION FROM CX_RUNTIME_ISOLATION_CONTRACTS "
            "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance FOR UPDATE",
            {"agent": agent_id, "instance": instance_id},
        ))
        if not row:
            raise IsolationError("runtime isolation contract is unavailable")
        before = str(row.get("status") or "").upper()
        version = int(row.get("version") or 0)
        if version != int(expected_version):
            raise IsolationError("runtime isolation contract changed concurrently")
        if target == before:
            return {"agent_id": agent_id, "instance_id": instance_id, "status": before,
                    "version": version, "idempotent": True}
        if target not in _STATE_TRANSITIONS.get(before, frozenset()):
            raise IsolationError(f"invalid runtime isolation transition: {before} -> {target}")
        changed = tx.execute(
            "UPDATE CX_RUNTIME_ISOLATION_CONTRACTS SET STATUS=:target,VERSION=VERSION+1,UPDATED_BY=:actor,"
            "UPDATED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance AND VERSION=:version",
            {"target": target, "actor": actor, "agent": agent_id, "instance": instance_id, "version": version},
        )
        if int(changed or 0) != 1:
            raise IsolationError("runtime isolation contract changed concurrently")
        if target in {"ISOLATED", "TERMINATED", "REVOKED"}:
            tx.execute(
                "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP "
                "WHERE INSTANCE_ID=:instance AND REVOKED_AT IS NULL", {"instance": instance_id},
            )
        if target in {"TERMINATED", "REVOKED"}:
            tx.execute(
                "UPDATE CX_AGENT_INSTANCES SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,"
                "REVOKE_REASON=:reason,FENCING_TOKEN=FENCING_TOKEN+1,UPDATED_AT=CURRENT_TIMESTAMP "
                "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance AND STATUS='ACTIVE'",
                {"agent": agent_id, "instance": instance_id, "reason": str(reason)[:1000]},
            )
        identity_api._audit_tx(tx, actor, "RUNTIME_ISOLATION_TRANSITION", "AGENT_INSTANCE", instance_id,
                               "ALLOW", f"{before}->{target}: {str(reason)[:1800]}")
        return {"agent_id": agent_id, "instance_id": instance_id, "status": target,
                "version": version + 1, "idempotent": False}

    return connection.execute_transaction_callback(work)
