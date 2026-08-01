"""Regression tests for v4.3 transactional security boundaries.

The doubles in this module deliberately exercise the adapter-neutral service
contracts.  They do not claim that an Oracle, PostgreSQL, or YashanDB server
has been reached; live database evidence remains a separate release gate.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from lib import identity_api, profile_api, security_lifecycle


class _SessionConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.session: dict[str, Any] | None = None
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        upper = sql.upper()
        if "SELECT PERMISSION_VERSION FROM CX_PRINCIPALS" in upper:
            return {"permission_version": 1}
        if "FROM CX_WEB_SESSIONS" in upper:
            return self.session
        if "SELECT STATUS, MFA_REQUIRED, PERMISSION_VERSION" in upper:
            return {"status": "ACTIVE", "mfa_required": False, "permission_version": 1}
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        params = params or {}
        self.executed.append((sql, params))
        upper = sql.upper()
        if "INSERT INTO CX_WEB_SESSIONS" in upper:
            self.session = {
                "session_digest": params["digest"],
                "principal_id": params["principal_id"],
                "user_id": params["user_id"],
                "auth_method": params["auth_method"],
                "mfa_level": params["mfa_level"],
                "node_id": params["node_id"],
                "permission_version": params["permission_version"],
                "csrf_digest": params["csrf_digest"],
                "expires_at": params["expires_at"],
                "created_at": identity_api._now(),
                "revoked_at": None,
            }
        return 1


class _AtomicConnection:
    """Small transaction double with the rows needed by governance services."""

    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.barrier_status = "WAITING"
        self.arrival: dict[str, Any] | None = None

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        params = params or {}
        upper = sql.upper()
        if "FROM CX_PRINCIPALS" in upper:
            if "PRINCIPAL_TYPE = 'AGENT'" in upper:
                return {"principal_id": "agent-1", "principal_type": "AGENT", "status": "ACTIVE"}
            principal_id = params.get("principal_id") or params.get("target") or "admin"
            return {"principal_id": principal_id, "principal_type": "HUMAN", "status": "ACTIVE", "permission_version": 1}
        if "FROM CX_CHANNELS" in upper:
            return {
                "channel_id": "channel-1", "status": "ACTIVE", "legal_hold": False,
                "metadata_json": "{}", "security_domain_id": "domain-1",
            }
        if "FROM CX_AGENT_RELATIONSHIPS" in upper:
            return {"relationship_id": "relationship-1"}
        if "FROM CX_BARRIERS" in upper:
            return {
                "barrier_id": "barrier-1", "channel_id": None, "created_by": "admin",
                "policy_json": '{"quorum":1}',
                "participant_snapshot": '[{"principal_id":"admin","role":"WORKER"}]',
                "status": self.barrier_status,
            }
        if "FROM CX_BARRIER_ARRIVALS" in upper:
            return self.arrival
        return None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None):
        upper = sql.upper()
        if "FROM CX_USER_ROLES" in upper:
            return [{"role_code": "SYSTEM_ADMIN"}]
        if "FROM CX_USER_PERMISSION_OVERRIDES" in upper:
            return []
        if "FROM CX_DELEGATIONS" in upper:
            return []
        if "FROM CX_BARRIER_ARRIVALS" in upper:
            return [self.arrival] if self.arrival else []
        return []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        params = params or {}
        self.executed.append((sql, params))
        upper = sql.upper()
        if "INSERT INTO CX_BARRIER_ARRIVALS" in upper:
            self.arrival = {
                "arrival_id": params["arrival_id"],
                "report_digest": params["report_digest"],
                "principal_id": params["principal_id"],
                "participant_role": params["participant_role"],
                "idempotency_key": params["idempotency_key"],
            }
        if "UPDATE CX_BARRIERS SET STATUS = 'READY'" in upper:
            self.barrier_status = "READY"
        return 1

    query_one = execute_query_one
    query = execute_query

    def execute_transaction_callback(self, callback):
        return callback(self)


class _PasswordConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.reset: dict[str, Any] | None = None
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        upper = sql.upper()
        if "FROM CX_HUMAN_IDENTITIES" in upper and "IDENTITY_TYPE = 'LOCAL'" in upper:
            return {"identity_id": "identity-1", "principal_id": "human-1", "status": "ACTIVE"}
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        params = params or {}
        self.executed.append((sql, params))
        if "INSERT INTO CX_PASSWORD_RESET_TOKENS" in sql.upper():
            self.reset = {
                "token_id": params["token_id"], "principal_id": params["principal_id"],
                "expires_at": params["expires_at"], "consumed_at": None,
            }
        if "UPDATE CX_PASSWORD_RESET_TOKENS" in sql.upper() and self.reset:
            if self.reset["consumed_at"] is not None:
                return 0
            self.reset["consumed_at"] = identity_api._now()
        return 1

    def execute_transaction_callback(self, callback):
        return callback(self)

    def query_one(self, sql: str, params: dict[str, Any] | None = None):
        upper = sql.upper()
        if "FROM CX_PASSWORD_RESET_TOKENS" in upper:
            if not self.reset:
                return None
            return {**self.reset}
        if "FROM CX_HUMAN_IDENTITIES" in upper:
            return {"username": "alice"}
        return None

    def query(self, sql: str, params: dict[str, Any] | None = None):
        return []


def test_session_ttl_is_capped_and_expiry_is_enforced(monkeypatch):
    db = _SessionConnection()
    monkeypatch.setattr(identity_api, "connection", db)

    session = identity_api.create_session("human-1", "user-1", "node-1", ttl_seconds=3600)
    assert db.session is not None
    assert 0 < (db.session["expires_at"] - db.session["created_at"]).total_seconds() <= 300
    assert identity_api.resolve_session(session["session_id"]) is not None

    db.session["expires_at"] = identity_api._now() - timedelta(seconds=1)
    assert identity_api.resolve_session(session["session_id"]) is None


def test_password_reset_token_has_one_winner_and_shared_transaction(monkeypatch):
    db = _PasswordConnection()
    monkeypatch.setattr(security_lifecycle, "connection", db)
    monkeypatch.setattr(security_lifecycle, "_secret_digest", lambda value, purpose: value)
    monkeypatch.setattr(identity_api, "hash_password_argon2id", lambda password: "argon2id:test")

    issued = security_lifecycle.issue_password_reset("alice")
    assert issued["issued"] is True
    assert security_lifecycle.consume_password_reset(issued["token"], "replacement-password") is True
    with pytest.raises(security_lifecycle.LifecycleError, match="invalid or expired"):
        security_lifecycle.consume_password_reset(issued["token"], "replacement-password")
    assert sum("CX_PASSWORD_RESET_TOKENS" in sql for sql, _ in db.executed) >= 2


def test_legal_hold_update_and_evidence_use_one_transaction(monkeypatch):
    db = _AtomicConnection()
    monkeypatch.setattr(identity_api, "connection", db)

    result = identity_api.set_channel_legal_hold("admin", "channel-1", True, "regulatory investigation")
    assert result["status"] == "FROZEN"
    statements = [sql.upper() for sql, _ in db.executed]
    assert any("UPDATE CX_CHANNELS" in sql for sql in statements)
    assert any("INSERT INTO CX_CHANNEL_DELETION_EVIDENCE" in sql for sql in statements)
    assert any("INSERT INTO CX_SECURITY_EVENTS" in sql for sql in statements)


def test_agent_status_revoke_is_atomic_and_requeues_claimed_work(monkeypatch):
    db = _AtomicConnection()
    monkeypatch.setattr(identity_api, "connection", db)

    assert identity_api.set_agent_status("admin", "agent-1", "DISABLED", "incident response") is True
    statements = [sql.upper() for sql, _ in db.executed]
    assert any("UPDATE CX_PRINCIPALS" in sql for sql in statements)
    assert any("UPDATE CX_AGENT_DELIVERIES" in sql and "STATUS = 'PENDING'" in sql for sql in statements)
    assert any("INSERT INTO CX_SECURITY_EVENTS" in sql for sql in statements)


def test_barrier_arrival_is_idempotent_after_quorum_transition(monkeypatch):
    db = _AtomicConnection()
    monkeypatch.setattr(identity_api, "connection", db)

    first = identity_api.arrive_barrier("admin", "barrier-1", {"result": "ok"}, "WORKER", "retry-key")
    second = identity_api.arrive_barrier("admin", "barrier-1", {"result": "ok"}, "WORKER", "retry-key")
    assert first["status"] == "READY"
    assert second["idempotent"] is True
    assert second["arrival_id"] == first["arrival_id"]
    with pytest.raises(identity_api.IdentityError, match="already arrived"):
        identity_api.arrive_barrier("admin", "barrier-1", {"result": "ok"}, "WORKER", "new-key")


def test_profile_activation_fails_closed_when_active_work_query_is_unavailable():
    class BrokenTx:
        def query(self, sql, params=None):
            raise RuntimeError("permission denied for relation GRAPH_RUNS")

    with pytest.raises(RuntimeError, match="permission denied"):
        profile_api._active_work_tx(BrokenTx())
