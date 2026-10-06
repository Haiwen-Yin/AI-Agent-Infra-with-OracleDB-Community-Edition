"""Shared database-first task continuity for A2A and DB4A2A.

The module deliberately keeps protocol rows and the existing Task Plan tables
authoritative.  The v4.5.2 tables added by the migration are a normalized
relationship and execution ledger; they do not become a second scheduler or
authorization store.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .continuity_state import ContinuityConflict, ContinuityError


LINK_KINDS = frozenset({"A2A", "DB4A2A", "MCP", "GRAPH", "RUNTIME", "DIAGNOSTIC"})
EFFECT_CLASSES = frozenset({"READ_ONLY", "REVERSIBLE", "CONSEQUENTIAL"})
LINK_STATES = frozenset({"PENDING", "RUNNING", "WAITING", "SUCCEEDED", "FAILED", "CANCELLED", "UNOBSERVED", "LEGACY_UNMAPPED"})
ATTEMPT_STATES = frozenset({"SENDING", "SUCCEEDED", "FAILED", "CANCELLED", "UNOBSERVED"})

# The continuity ledger is deliberately stricter than the protocol status
# projections.  In particular, an expired/unknown send may only be resolved;
# it must never silently return to RUNNING and issue a second external send.
_LINK_TRANSITIONS = {
    "PENDING": {"RUNNING", "WAITING", "CANCELLED", "UNOBSERVED"},
    "RUNNING": {"WAITING", "SUCCEEDED", "FAILED", "CANCELLED", "UNOBSERVED"},
    "WAITING": {"RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "UNOBSERVED"},
    "UNOBSERVED": {"SUCCEEDED", "FAILED", "CANCELLED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "LEGACY_UNMAPPED": set(),
}


def _id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(20)


def _row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in dict(row or {}).items()}


def _digest(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = str(value or "").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_naive(value: Any) -> datetime | None:
    """Normalize driver timestamps to a comparable UTC-naive instant.

    Oracle/YashanDB TIMESTAMP values are commonly naive while PostgreSQL may
    return an aware value for a timestamptz column.  Continuity comparisons
    must not depend on which adapter supplied the row.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def schema_statements(dialect: str) -> list[str]:
    """Return the portable table definitions used by migration 101.

    The generator replaces TEXT with CLOB for Oracle/YashanDB.  All state and
    identity columns are bounded relational values so the three adapters keep
    equivalent constraints and indexes.
    """
    if dialect not in {"pg", "postgresql", "oracle", "yashandb", "yashan"}:
        raise ValueError("unsupported database adapter")
    body = "TEXT" if dialect in {"pg", "postgresql"} else "CLOB"
    # PostgreSQL's historical TASK_PLANS table is LIST-partitioned by STATUS
    # and exposes only the composite primary key (PLAN_ID, STATUS).  A
    # partitioned table cannot provide a global unique PLAN_ID constraint, so
    # PostgreSQL rejects a direct FK to PLAN_ID (SQLSTATE 42830).  The
    # continuity service still resolves and locks the canonical plan through
    # TASK_PLANS before admission; the other adapters retain the database FK
    # against their existing UK_TASK_PLANS_ID.  Keeping this distinction here
    # makes the generated migration executable on all three schemas without
    # introducing a duplicate scheduler/locator table.
    task_reference = " REFERENCES TASK_PLANS(PLAN_ID)" if dialect not in {"pg", "postgresql"} else ""
    return [
        "CREATE TABLE CX_TASK_CONTINUITY_LINKS ("
        "CONTINUITY_ID VARCHAR(128) PRIMARY KEY, "
        "CANONICAL_TASK_ID VARCHAR(64)" + task_reference + ", "
        "LINK_KIND VARCHAR(24) NOT NULL CHECK(LINK_KIND IN ('A2A','DB4A2A','MCP','GRAPH','RUNTIME','DIAGNOSTIC')), "
        "LINK_ID VARCHAR(256) NOT NULL, "
        "ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), "
        "SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "AUTHORIZATION_VERSION INTEGER NOT NULL CHECK(AUTHORIZATION_VERSION>0), "
        "CAPABILITY_VERSION INTEGER NOT NULL CHECK(CAPABILITY_VERSION>0), "
        "EFFECT_CLASS VARCHAR(24) NOT NULL CHECK(EFFECT_CLASS IN ('READ_ONLY','REVERSIBLE','CONSEQUENTIAL')), "
        "IDEMPOTENCY_KEY VARCHAR(128) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, "
        "INPUT_DIGEST VARCHAR(64) NOT NULL, CONTEXT_ASSEMBLY_ID VARCHAR(128) REFERENCES CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('PENDING','RUNNING','WAITING','SUCCEEDED','FAILED','CANCELLED','UNOBSERVED','LEGACY_UNMAPPED')), "
        "PROTOCOL_VERSION VARCHAR(64), SDK_VERSION VARCHAR(64), "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
        "UNIQUE(LINK_KIND,LINK_ID), UNIQUE(ACTOR_ID,IDEMPOTENCY_KEY))",
        "CREATE TABLE CX_TASK_CONTINUITY_ATTEMPTS ("
        "ATTEMPT_ID VARCHAR(128) PRIMARY KEY, CONTINUITY_ID VARCHAR(128) NOT NULL REFERENCES CX_TASK_CONTINUITY_LINKS(CONTINUITY_ID), "
        "ATTEMPT_NO INTEGER NOT NULL CHECK(ATTEMPT_NO>0), FENCING_TOKEN INTEGER NOT NULL CHECK(FENCING_TOKEN>0), "
        "STATUS VARCHAR(24) NOT NULL CHECK(STATUS IN ('SENDING','SUCCEEDED','FAILED','CANCELLED','UNOBSERVED')), "
        "BUSINESS_KEY VARCHAR(256) NOT NULL, REQUEST_DIGEST VARCHAR(64) NOT NULL, LEASE_EXPIRES_AT TIMESTAMP NOT NULL, "
        "STARTED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, COMPLETED_AT TIMESTAMP, ERROR_CODE VARCHAR(128), "
        "ERROR_MESSAGE VARCHAR(2000), UNIQUE(CONTINUITY_ID,ATTEMPT_NO))",
        "CREATE TABLE CX_TASK_CONTINUITY_LEASES ("
        "CONTINUITY_ID VARCHAR(128) PRIMARY KEY REFERENCES CX_TASK_CONTINUITY_LINKS(CONTINUITY_ID), "
        "LEASE_OWNER VARCHAR(128) NOT NULL, FENCING_TOKEN INTEGER NOT NULL CHECK(FENCING_TOKEN>0), "
        "LEASE_EXPIRES_AT TIMESTAMP NOT NULL, STATUS VARCHAR(16) NOT NULL CHECK(STATUS IN ('ACTIVE','EXPIRED','RELEASED')), "
        "UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        "CREATE TABLE CX_TASK_CONTINUITY_CONTEXT ("
        "CONTINUITY_ID VARCHAR(128) PRIMARY KEY REFERENCES CX_TASK_CONTINUITY_LINKS(CONTINUITY_ID), "
        "ASSEMBLY_ID VARCHAR(128) REFERENCES CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID), SOURCE_REVISION_ID VARCHAR(128) NOT NULL, "
        "SOURCE_DIGEST VARCHAR(64) NOT NULL, BRANCH_ID VARCHAR(128), SECURITY_DOMAIN_ID VARCHAR(128) NOT NULL REFERENCES CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID), "
        "AUTHORIZATION_VERSION INTEGER NOT NULL CHECK(AUTHORIZATION_VERSION>0), SUMMARY_POLICY VARCHAR(64) NOT NULL, "
        "CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        "CREATE TABLE CX_TASK_CONTINUITY_TRANSITIONS ("
        "TRANSITION_ID VARCHAR(128) PRIMARY KEY, CONTINUITY_ID VARCHAR(128) NOT NULL REFERENCES CX_TASK_CONTINUITY_LINKS(CONTINUITY_ID), "
        "FROM_STATUS VARCHAR(24), TO_STATUS VARCHAR(24) NOT NULL CHECK(TO_STATUS IN ('PENDING','RUNNING','WAITING','SUCCEEDED','FAILED','CANCELLED','UNOBSERVED','LEGACY_UNMAPPED')), "
        "ACTOR_ID VARCHAR(128) NOT NULL REFERENCES CX_PRINCIPALS(PRINCIPAL_ID), REASON VARCHAR(2000) NOT NULL, "
        "REQUEST_DIGEST VARCHAR(64) NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
        "CREATE TABLE CX_TASK_CONTINUITY_LEGACY ("
        "DISPATCH_ID VARCHAR(128) PRIMARY KEY, TASK_ID VARCHAR(256) NOT NULL, MATCHED_TASK_ID VARCHAR(64)" + task_reference + ", "
        "CLASSIFICATION VARCHAR(24) NOT NULL CHECK(CLASSIFICATION IN ('EXACT_MATCH','LEGACY_UNMAPPED','AMBIGUOUS')), "
        "REASON VARCHAR(2000) NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)",
    ]


def _canonical_task(tx: Any, task_id: str) -> str:
    value = str(task_id or "").strip()
    if not value or len(value) > 64:
        raise ContinuityError("INVALID_TASK", "A canonical Task Plan identifier is required")
    row = _row(tx.query_one("SELECT PLAN_ID,STATUS FROM TASK_PLANS WHERE PLAN_ID=:task FOR UPDATE", {"task": value}))
    if not row:
        raise ContinuityError("TASK_NOT_FOUND", "The canonical Task Plan is unavailable")
    return str(row["plan_id"])


def ensure_task_root(tx: Any, actor: str, task_id: str | None = None, *, goal: str = "Protocol task",
                     preferred_agent_id: str | None = None) -> str:
    """Resolve or create a Task Plan root for a new protocol admission.

    Creation is restricted to an active Agent principal.  Human callers must
    first create a governed Task Plan through the existing Task Plan API and
    pass its stable identifier.
    """
    # Protocol task IDs are not required to be Task Plan IDs.  A2A and
    # DB4A2A have historically accepted opaque business keys, so only reuse a
    # Task Plan after proving an exact unique match; otherwise create a new
    # canonical root and leave the protocol key on its source row.
    if task_id:
        value = str(task_id).strip()
        if value and len(value) <= 64:
            existing = _row(tx.query_one(
                "SELECT PLAN_ID FROM TASK_PLANS WHERE PLAN_ID=:task FOR UPDATE", {"task": value}))
            if existing:
                return str(existing["plan_id"])
    principal = _row(tx.query_one("SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor FOR UPDATE", {"actor": actor}))
    if principal.get("status") != "ACTIVE":
        raise ContinuityError("ACTOR_INACTIVE", "The admitting principal is inactive")
    agent_id = str(preferred_agent_id or actor)
    if preferred_agent_id:
        candidate = _row(tx.query_one(
            "SELECT AGENT_ID FROM AGENT_REGISTRY WHERE AGENT_ID=:agent", {"agent": agent_id}))
        if not candidate:
            raise ContinuityError("AGENT_NOT_FOUND", "The preferred receiving Agent is unavailable")
    elif principal.get("principal_type") != "AGENT":
        owner = _row(tx.query_one(
            "SELECT AGENT_ID FROM CX_AGENT_RELATIONSHIPS WHERE PRINCIPAL_ID=:actor AND STATUS='ACTIVE' "
            "AND RELATIONSHIP_ROLE IN ('PRIMARY_OWNER','SPONSOR','RESPONSIBLE') ORDER BY RELATIONSHIP_ROLE,AGENT_ID",
            {"actor": actor},
        ))
        if not owner:
            raise ContinuityError("TASK_REQUIRED", "A human admission must reference an existing Task Plan")
        agent_id = str(owner["agent_id"])
    plan_id = _id("PLAN")[:64]
    text = str(goal or "Protocol task").strip()[:2000] or "Protocol task"
    tx.execute("INSERT INTO TASK_PLANS(PLAN_ID,AGENT_ID,GOAL,STATUS,PRIORITY,STRATEGY) VALUES(:plan,:agent,:goal,'RUNNING',5,'PROTOCOL_CONTINUITY')",
               {"plan": plan_id, "agent": agent_id, "goal": text})
    return plan_id


def _transition(tx: Any, continuity_id: str, actor: str, target: str, reason: str, request_digest: str) -> None:
    if target not in LINK_STATES:
        raise ContinuityError("INVALID_STATE", "Unknown task continuity state")
    current = _row(tx.query_one("SELECT STATUS FROM CX_TASK_CONTINUITY_LINKS WHERE CONTINUITY_ID=:id FOR UPDATE", {"id": continuity_id}))
    if not current:
        raise ContinuityError("LINK_NOT_FOUND", "Task continuity link is unavailable")
    before = str(current["status"])
    if before == target:
        return
    if target not in _LINK_TRANSITIONS.get(before, set()):
        if before in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise ContinuityConflict("TERMINAL_TASK", "A terminal task cannot change state")
        if before == "UNOBSERVED":
            raise ContinuityConflict("UNKNOWN_SEND", "Reconcile the unknown send before starting another attempt")
        raise ContinuityConflict("INVALID_TRANSITION", f"Cannot transition task from {before} to {target}")
    tx.execute("UPDATE CX_TASK_CONTINUITY_LINKS SET STATUS=:status,UPDATED_AT=CURRENT_TIMESTAMP WHERE CONTINUITY_ID=:id AND STATUS=:before",
               {"status": target, "id": continuity_id, "before": before})
    tx.execute("INSERT INTO CX_TASK_CONTINUITY_TRANSITIONS(TRANSITION_ID,CONTINUITY_ID,FROM_STATUS,TO_STATUS,ACTOR_ID,REASON,REQUEST_DIGEST) VALUES(:event,:id,:before,:after,:actor,:reason,:digest)",
               {"event": _id("TCT"), "id": continuity_id, "before": before, "after": target, "actor": actor,
                "reason": str(reason or "state transition")[:2000], "digest": request_digest})


def link_protocol_task(tx: Any, *, actor: str, security_domain_id: str, link_kind: str, link_id: str,
                       canonical_task_id: str, idempotency_key: str, request_digest: str,
                       input_digest: str | None = None, effect_class: str = "READ_ONLY",
                       authorization_version: int = 1, capability_version: int = 1,
                       status: str = "PENDING", context_assembly_id: str | None = None,
                       protocol_version: str | None = None, sdk_version: str | None = None,
                       reason: str = "protocol admission") -> dict[str, Any]:
    kind = str(link_kind or "").upper()
    if kind not in LINK_KINDS:
        raise ContinuityError("INVALID_LINK_KIND", "Unsupported continuity link kind")
    effect = str(effect_class or "").upper()
    if effect not in EFFECT_CLASSES:
        raise ContinuityError("INVALID_EFFECT_CLASS", "Unsupported task effect class")
    if status not in LINK_STATES or status == "LEGACY_UNMAPPED":
        raise ContinuityError("INVALID_STATE", "Invalid admission state")
    canonical = _canonical_task(tx, canonical_task_id)
    idem = str(idempotency_key or "").strip()
    if not idem or len(idem) > 128:
        raise ContinuityError("INVALID_IDEMPOTENCY_KEY", "A bounded idempotency key is required")
    existing = _row(tx.query_one("SELECT * FROM CX_TASK_CONTINUITY_LINKS WHERE LINK_KIND=:kind AND LINK_ID=:link",
                                 {"kind": kind, "link": str(link_id)}))
    if not existing:
        # A stable idempotency key must be honored even when a protocol retry
        # uses a newly generated transport/link ID.
        existing = _row(tx.query_one(
            "SELECT * FROM CX_TASK_CONTINUITY_LINKS WHERE ACTOR_ID=:actor AND IDEMPOTENCY_KEY=:idem",
            {"actor": actor, "idem": idem}))
    if existing:
        if (existing.get("request_digest") != request_digest or existing.get("canonical_task_id") != canonical or
                existing.get("actor_id") != actor or existing.get("security_domain_id") != security_domain_id or
                str(existing.get("link_kind") or "").upper() != kind):
            raise ContinuityConflict("IDEMPOTENCY_CONFLICT", "The protocol link belongs to different task facts")
        return existing | {"replayed": True}
    continuity_id = _id("TC")
    tx.execute("INSERT INTO CX_TASK_CONTINUITY_LINKS(CONTINUITY_ID,CANONICAL_TASK_ID,LINK_KIND,LINK_ID,ACTOR_ID,SECURITY_DOMAIN_ID,AUTHORIZATION_VERSION,CAPABILITY_VERSION,EFFECT_CLASS,IDEMPOTENCY_KEY,REQUEST_DIGEST,INPUT_DIGEST,CONTEXT_ASSEMBLY_ID,STATUS,PROTOCOL_VERSION,SDK_VERSION) VALUES(:id,:task,:kind,:link,:actor,:domain,:auth,:cap,:effect,:idem,:request,:input,:assembly,:status,:protocol,:sdk)",
               {"id": continuity_id, "task": canonical, "kind": kind, "link": str(link_id), "actor": actor,
                "domain": security_domain_id, "auth": max(1, int(authorization_version)), "cap": max(1, int(capability_version)),
                "effect": effect, "idem": idem, "request": request_digest,
                "input": input_digest or _digest(request_digest), "assembly": context_assembly_id, "status": status,
                "protocol": protocol_version, "sdk": sdk_version})
    tx.execute("INSERT INTO CX_TASK_CONTINUITY_TRANSITIONS(TRANSITION_ID,CONTINUITY_ID,FROM_STATUS,TO_STATUS,ACTOR_ID,REASON,REQUEST_DIGEST) VALUES(:event,:id,NULL,:status,:actor,:reason,:digest)",
               {"event": _id("TCT"), "id": continuity_id, "status": status, "actor": actor,
                "reason": str(reason or "protocol admission")[:2000], "digest": request_digest})
    return {"continuity_id": continuity_id, "canonical_task_id": canonical, "link_kind": kind, "link_id": str(link_id), "status": status, "replayed": False}


def bind_context(tx: Any, *, continuity_id: str, assembly_id: str | None, source_revision_id: str,
                 source_digest: str, security_domain_id: str, authorization_version: int,
                 branch_id: str | None = None, summary_policy: str = "EXACT") -> None:
    if not source_revision_id or not source_digest:
        raise ContinuityError("CONTEXT_REQUIRED", "An exact source revision and digest are required")
    existing = _row(tx.query_one("SELECT SOURCE_REVISION_ID,SOURCE_DIGEST FROM CX_TASK_CONTINUITY_CONTEXT WHERE CONTINUITY_ID=:id", {"id": continuity_id}))
    if existing:
        if existing.get("source_revision_id") != source_revision_id or existing.get("source_digest") != source_digest:
            raise ContinuityConflict("CONTEXT_CONFLICT", "Context binding differs from the recorded revision")
        return
    tx.execute("INSERT INTO CX_TASK_CONTINUITY_CONTEXT(CONTINUITY_ID,ASSEMBLY_ID,SOURCE_REVISION_ID,SOURCE_DIGEST,BRANCH_ID,SECURITY_DOMAIN_ID,AUTHORIZATION_VERSION,SUMMARY_POLICY) VALUES(:id,:assembly,:revision,:digest,:branch,:domain,:auth,:policy)",
               {"id": continuity_id, "assembly": assembly_id, "revision": source_revision_id, "digest": source_digest,
                "branch": branch_id, "domain": security_domain_id, "auth": max(1, int(authorization_version)),
                "policy": str(summary_policy or "EXACT")[:64]})


def claim_attempt(tx: Any, *, continuity_id: str, worker_id: str, business_key: str,
                  request_digest: str, lease_seconds: int = 60) -> dict[str, Any]:
    """Claim one fenced attempt; expired leases are replaced atomically."""
    now = _now()
    expiry = now + timedelta(seconds=max(1, min(int(lease_seconds), 3600)))
    link = _row(tx.query_one("SELECT STATUS FROM CX_TASK_CONTINUITY_LINKS WHERE CONTINUITY_ID=:id FOR UPDATE", {"id": continuity_id}))
    if not link or link.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise ContinuityError("TERMINAL_TASK", "A terminal or missing task cannot be claimed")
    if link.get("status") == "UNOBSERVED":
        raise ContinuityConflict("UNKNOWN_SEND", "Reconcile the unknown send before starting another attempt")
    lease = _row(tx.query_one("SELECT LEASE_OWNER,FENCING_TOKEN,LEASE_EXPIRES_AT,STATUS FROM CX_TASK_CONTINUITY_LEASES WHERE CONTINUITY_ID=:id FOR UPDATE", {"id": continuity_id}))
    lease_expiry = _utc_naive(lease.get("lease_expires_at")) if lease else None
    if lease and lease.get("status") == "ACTIVE" and lease_expiry and lease_expiry > now:
        # A retry by the same worker with the same durable business key is an
        # idempotent claim, not a second send.
        active = _row(tx.query_one(
            "SELECT ATTEMPT_ID,ATTEMPT_NO,FENCING_TOKEN,LEASE_EXPIRES_AT FROM CX_TASK_CONTINUITY_ATTEMPTS "
            "WHERE CONTINUITY_ID=:id AND BUSINESS_KEY=:business AND REQUEST_DIGEST=:digest AND STATUS='SENDING' "
            "ORDER BY ATTEMPT_NO DESC", {"id": continuity_id, "business": str(business_key)[:256], "digest": request_digest}))
        if str(lease.get("lease_owner")) == str(worker_id) and active:
            return {"attempt_id": active["attempt_id"], "continuity_id": continuity_id,
                    "attempt_no": int(active["attempt_no"]), "fencing_token": int(active["fencing_token"]),
                    "lease_expires_at": active.get("lease_expires_at"), "replayed": True}
        raise ContinuityConflict("LEASE_HELD", "The task is leased by another worker")
    if lease and lease.get("status") == "ACTIVE" and lease_expiry and lease_expiry <= now:
        # The external outcome of an expired SENDING attempt is unknown.  Do
        # not issue a new request until a caller reconciles its business key.
        stale = _row(tx.query_one(
            "SELECT ATTEMPT_ID FROM CX_TASK_CONTINUITY_ATTEMPTS WHERE CONTINUITY_ID=:id "
            "AND STATUS='SENDING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP ORDER BY ATTEMPT_NO DESC",
            {"id": continuity_id}))
        if stale:
            tx.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET STATUS='UNOBSERVED',COMPLETED_AT=CURRENT_TIMESTAMP,ERROR_CODE='LEASE_EXPIRED',ERROR_MESSAGE='External outcome was not observed before lease expiry' WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING'",
                       {"attempt": stale["attempt_id"]})
            tx.execute("UPDATE CX_TASK_CONTINUITY_LEASES SET STATUS='EXPIRED',UPDATED_AT=CURRENT_TIMESTAMP WHERE CONTINUITY_ID=:id AND FENCING_TOKEN=:token",
                       {"id": continuity_id, "token": lease.get("fencing_token")})
            _transition(tx, continuity_id, worker_id, "UNOBSERVED", "attempt lease expired before outcome", request_digest)
            # The caller receives a durable refusal rather than an exception;
            # raising here would roll the state back in normal transaction
            # runners and erase the very uncertainty we must preserve.
            return {"continuity_id": continuity_id, "status": "UNOBSERVED",
                    "reconciliation_required": True,
                    "reason": "The previous send is unobserved; reconcile it before retrying"}
    token = int(lease.get("fencing_token") or 0) + 1 if lease else 1
    if lease:
        tx.execute("UPDATE CX_TASK_CONTINUITY_LEASES SET LEASE_OWNER=:owner,FENCING_TOKEN=:token,LEASE_EXPIRES_AT=:until,STATUS='ACTIVE',UPDATED_AT=CURRENT_TIMESTAMP WHERE CONTINUITY_ID=:id",
                   {"owner": worker_id, "token": token, "until": expiry, "id": continuity_id})
    else:
        tx.execute("INSERT INTO CX_TASK_CONTINUITY_LEASES(CONTINUITY_ID,LEASE_OWNER,FENCING_TOKEN,LEASE_EXPIRES_AT,STATUS) VALUES(:id,:owner,:token,:until,'ACTIVE')",
                   {"id": continuity_id, "owner": worker_id, "token": token, "until": expiry})
    current = _row(tx.query_one("SELECT COALESCE(MAX(ATTEMPT_NO),0) AS ATTEMPT_NO FROM CX_TASK_CONTINUITY_ATTEMPTS WHERE CONTINUITY_ID=:id", {"id": continuity_id}))
    number = int(current.get("attempt_no") or 0) + 1
    attempt_id = _id("TCA")
    tx.execute("INSERT INTO CX_TASK_CONTINUITY_ATTEMPTS(ATTEMPT_ID,CONTINUITY_ID,ATTEMPT_NO,FENCING_TOKEN,STATUS,BUSINESS_KEY,REQUEST_DIGEST,LEASE_EXPIRES_AT) VALUES(:attempt,:id,:number,:token,'SENDING',:business,:digest,:until)",
               {"attempt": attempt_id, "id": continuity_id, "number": number, "token": token,
                "business": str(business_key)[:256], "digest": request_digest, "until": expiry})
    _transition(tx, continuity_id, worker_id, "RUNNING", "fenced attempt claimed", request_digest)
    return {"attempt_id": attempt_id, "continuity_id": continuity_id, "attempt_no": number, "fencing_token": token, "lease_expires_at": expiry}


def finish_attempt(tx: Any, *, attempt_id: str, worker_id: str, fencing_token: int,
                   status: str, request_digest: str, error_code: str | None = None,
                   error_message: str | None = None) -> dict[str, Any]:
    target = str(status or "").upper()
    if target not in ATTEMPT_STATES:
        raise ContinuityError("INVALID_ATTEMPT_STATE", "Unknown attempt state")
    row = _row(tx.query_one("SELECT a.CONTINUITY_ID,a.FENCING_TOKEN,a.STATUS,a.LEASE_EXPIRES_AT,l.LEASE_OWNER,l.FENCING_TOKEN AS LEASE_TOKEN FROM CX_TASK_CONTINUITY_ATTEMPTS a JOIN CX_TASK_CONTINUITY_LEASES l ON l.CONTINUITY_ID=a.CONTINUITY_ID WHERE a.ATTEMPT_ID=:attempt FOR UPDATE", {"attempt": attempt_id}))
    if not row or int(row.get("fencing_token") or 0) != int(fencing_token) or int(row.get("lease_token") or 0) != int(fencing_token) or str(row.get("lease_owner")) != str(worker_id):
        raise ContinuityConflict("FENCING_MISMATCH", "The worker lease is stale")
    if row.get("status") != "SENDING":
        raise ContinuityConflict("ATTEMPT_TERMINAL", "The attempt has already been completed")
    expires = _utc_naive(row.get("lease_expires_at"))
    if expires and expires <= _now():
        # Preserve the unknown-send fact before rejecting the stale worker.
        tx.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET STATUS='UNOBSERVED',COMPLETED_AT=CURRENT_TIMESTAMP,ERROR_CODE='LEASE_EXPIRED',ERROR_MESSAGE='Stale worker completed after lease expiry' WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING' AND FENCING_TOKEN=:token",
                   {"attempt": attempt_id, "token": fencing_token})
        _transition(tx, str(row["continuity_id"]), worker_id, "UNOBSERVED", "stale worker result rejected; outcome is unobserved", request_digest)
        tx.execute("UPDATE CX_TASK_CONTINUITY_LEASES SET STATUS='EXPIRED',UPDATED_AT=CURRENT_TIMESTAMP WHERE CONTINUITY_ID=:id AND FENCING_TOKEN=:token",
                   {"id": row["continuity_id"], "token": fencing_token})
        return {"attempt_id": attempt_id, "continuity_id": row["continuity_id"], "status": "UNOBSERVED",
                "fencing_token": fencing_token, "accepted": False}
    tx.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET STATUS=:status,COMPLETED_AT=CURRENT_TIMESTAMP,ERROR_CODE=:code,ERROR_MESSAGE=:message WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING' AND FENCING_TOKEN=:token",
               {"status": target, "attempt": attempt_id, "token": fencing_token, "code": error_code, "message": error_message})
    mapped = {"SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "CANCELLED": "CANCELLED", "UNOBSERVED": "UNOBSERVED"}[target]
    _transition(tx, str(row["continuity_id"]), worker_id, mapped, error_message or "attempt completed", request_digest)
    tx.execute("UPDATE CX_TASK_CONTINUITY_LEASES SET STATUS='RELEASED',UPDATED_AT=CURRENT_TIMESTAMP WHERE CONTINUITY_ID=:id AND FENCING_TOKEN=:token",
               {"id": row["continuity_id"], "token": fencing_token})
    return {"attempt_id": attempt_id, "continuity_id": row["continuity_id"], "status": target, "fencing_token": fencing_token}


def reconcile_unobserved(tx: Any, *, continuity_id: str, business_key: str, actor: str,
                        request_digest: str, outcome: str | None = None) -> dict[str, Any]:
    """Resolve an unknown send using the persisted business key.

    A missing outcome remains UNOBSERVED.  The function never emits a new
    attempt; callers must reconcile before any retry.
    """
    rows = tx.query("SELECT ATTEMPT_ID,STATUS,REQUEST_DIGEST FROM CX_TASK_CONTINUITY_ATTEMPTS WHERE CONTINUITY_ID=:id AND BUSINESS_KEY=:business ORDER BY ATTEMPT_NO DESC", {"id": continuity_id, "business": str(business_key)[:256]})
    if not rows:
        raise ContinuityError("ATTEMPT_NOT_FOUND", "No persisted attempt matches the business key")
    target = str(outcome or "UNOBSERVED").upper()
    if target not in {"SUCCEEDED", "FAILED", "CANCELLED", "UNOBSERVED"}:
        raise ContinuityError("INVALID_RECONCILIATION", "Unknown reconciliation outcome")
    attempt = _row(rows[0])
    if attempt.get("status") != "UNOBSERVED":
        raise ContinuityConflict("NOT_UNOBSERVED", "Only an explicitly unobserved attempt can be reconciled")
    if request_digest and attempt.get("request_digest") != request_digest:
        raise ContinuityConflict("IDEMPOTENCY_CONFLICT", "The business key belongs to a different request")
    attempt_id = attempt["attempt_id"]
    if target != "UNOBSERVED":
        tx.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET STATUS=:status,COMPLETED_AT=CURRENT_TIMESTAMP WHERE ATTEMPT_ID=:attempt AND STATUS='UNOBSERVED'",
                   {"status": target, "attempt": attempt_id})
        _transition(tx, continuity_id, actor, target, "unknown send reconciled by business key", request_digest)
    return {"attempt_id": attempt_id, "continuity_id": continuity_id, "status": target, "replayed": True}


def read_link(tx: Any, *, actor: str, continuity_id: str) -> dict[str, Any] | None:
    """Return a governed continuity projection; authorization stays upstream."""
    row = _row(tx.query_one("SELECT * FROM CX_TASK_CONTINUITY_LINKS WHERE CONTINUITY_ID=:id", {"id": continuity_id}))
    if not row:
        return None
    row["attempts"] = [_row(item) for item in tx.query("SELECT * FROM CX_TASK_CONTINUITY_ATTEMPTS WHERE CONTINUITY_ID=:id ORDER BY ATTEMPT_NO", {"id": continuity_id})]
    row["context"] = _row(tx.query_one("SELECT * FROM CX_TASK_CONTINUITY_CONTEXT WHERE CONTINUITY_ID=:id", {"id": continuity_id})) or None
    return row
