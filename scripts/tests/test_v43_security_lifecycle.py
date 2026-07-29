"""Focused behavior tests for v4.3 identity and runtime containment.

These tests use a deliberately small connection double.  They verify service
decisions and the SQL mutation boundaries without pretending to be a live
Oracle, PostgreSQL, or YashanDB result.
"""

from __future__ import annotations

from typing import Any

import pytest

from lib import agent_gateway_api, governed_contracts, identity_api


class _ConnectionDouble:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.query_one_calls: list[tuple[str, dict[str, Any]]] = []
        self.principal_status: dict[str, str] = {
            "grantor": "ACTIVE",
            "grantee": "ACTIVE",
            "admin": "ACTIVE",
        }
        self.delegations: list[dict[str, Any]] = []

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        params = params or {}
        self.query_one_calls.append((sql, params))
        upper = sql.upper()
        if "FROM CX_PRINCIPALS" in upper:
            principal_id = str(params.get("principal_id") or params.get("target") or "")
            status = self.principal_status.get(principal_id)
            if status is None:
                return None
            return {
                "principal_id": principal_id,
                "principal_type": "HUMAN",
                "status": status,
                "permission_version": 1,
            }
        if "COUNT(*)" in upper:
            return {"cnt": 0}
        if "FROM CX_AGENT_INSTANCES" in upper and "SELECT 1" in upper:
            return None
        if "FROM CX_ROLE_TEMPLATES" in upper:
            return None
        if "FROM CX_USER_PERMISSION_OVERRIDES" in upper:
            return None
        if "PERMISSION_VERSION" in upper:
            return {"permission_version": 1}
        if "FROM CX_CHANNELS" in upper:
            return {
                "channel_id": "channel-1", "status": "ACTIVE", "legal_hold": False,
                "retention_until": None, "deletion_after": None,
                "security_domain_id": "domain-1", "metadata_json": "{}",
            }
        if "FROM CX_BARRIERS" in upper:
            return {"policy_json": '{"quorum": 2}', "participant_snapshot": "[]", "status": "WAITING"}
        return None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None):
        upper = sql.upper()
        if "FROM CX_USER_ROLES" in upper:
            principal_id = str((params or {}).get("principal_id") or "")
            return [{"role_code": "SYSTEM_ADMIN"}] if principal_id in {"admin", "grantor"} else [{"role_code": "END_USER"}]
        if "FROM CX_USER_PERMISSION_OVERRIDES" in upper:
            return []
        if "FROM CX_DELEGATIONS" in upper:
            return list(self.delegations)
        if "FROM CX_BARRIER_ARRIVALS" in upper:
            return [
                {"principal_id": "agent-a", "participant_role": "WORKER"},
                {"principal_id": "agent-b", "participant_role": "REVIEWER"},
            ]
        return []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        self.executed.append((sql, params or {}))
        if "UPDATE CX_AGENT_INSTANCES" in sql.upper():
            return 1
        return 1


def test_channel_transition_compatibility_facade_preserves_runtime_gates():
    with pytest.raises(governed_contracts.GovernanceContractError):
        governed_contracts.validate_channel_transition(
            "ACTIVE", "ARCHIVED", authorized=True, active_work=True, quiesced=False,
        )

    allowed = governed_contracts.validate_channel_transition(
        "ACTIVE", "QUARANTINED", authorized=True, active_work=False, quiesced=True,
    )
    assert allowed["target"] == "QUARANTINED"
    assert allowed["effects"]["revoke_temporary_access"] is True


def test_delegated_permission_is_live_and_revocation_is_immediate(monkeypatch):
    db = _ConnectionDouble()
    db.delegations = [{
        "delegation_id": "delegation-1",
        "grantor_principal_id": "grantor",
        "permissions_json": '["users.approve"]',
        "data_scope": "ASSIGNED",
    }]
    monkeypatch.setattr(identity_api, "connection", db)

    allowed = identity_api.effective_access("grantee", "users.approve")
    assert allowed["decision"] == "ALLOW"
    assert "delegation:delegation-1:grantor" in allowed["sources"]
    assert "ASSIGNED" in allowed["scopes"]

    db.delegations = []
    denied = identity_api.effective_access("grantee", "users.approve")
    assert denied["decision"] == "DENY"

    db.delegations = [{
        "delegation_id": "delegation-1",
        "grantor_principal_id": "grantor",
        "permissions_json": '["users.approve"]',
        "data_scope": "ASSIGNED",
    }]
    db.principal_status["grantor"] = "DISABLED"
    assert identity_api.effective_access("grantee", "users.approve")["decision"] == "DENY"


def test_channel_isolation_writes_immutable_evidence(monkeypatch):
    db = _ConnectionDouble()
    monkeypatch.setattr(identity_api, "connection", db)
    monkeypatch.setattr(identity_api, "_audit", lambda *args, **kwargs: None)

    result = identity_api.transition_channel_lifecycle(
        "admin", "channel-1", "QUARANTINED", "contain compromised Agent",
    )
    assert result["target"] == "QUARANTINED"
    evidence = [sql for sql, _ in db.executed if "CX_CHANNEL_DELETION_EVIDENCE" in sql]
    assert len(evidence) == 1
    assert any("UPDATE CX_CHANNELS" in sql for sql, _ in db.executed)


def test_barrier_ready_state_is_persisted_once(monkeypatch):
    db = _ConnectionDouble()
    monkeypatch.setattr(identity_api, "connection", db)
    assert identity_api.evaluate_barrier("barrier-1") == "READY"
    ready_updates = [sql for sql, _ in db.executed if "SET STATUS = 'READY'" in sql]
    assert len(ready_updates) == 1
    assert "STATUS = 'WAITING'" in ready_updates[0]


def test_instance_revoke_also_revokes_instance_derived_objects(monkeypatch):
    db = _ConnectionDouble()
    monkeypatch.setattr(agent_gateway_api, "connection", db)
    assert agent_gateway_api.revoke_instance("agent-1", "instance-1", "incident response") is True
    derived_updates = [sql for sql, _ in db.executed if "CX_AGENT_DERIVED_OBJECTS" in sql]
    assert len(derived_updates) == 1
    assert "INSTANCE_ID = :instance_id" in derived_updates[0]
