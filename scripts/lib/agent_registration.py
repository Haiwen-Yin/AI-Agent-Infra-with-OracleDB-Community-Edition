"""Registered-Agent admission and lifecycle contract for v4.1.0.

The legacy ``AGENT_REGISTRY`` table remains the operational pool inventory.
This module adds the explicit managed-boundary identity used by HTTP, MCP,
Skill and external runtimes.  Credentials are returned only at registration
time and only their SHA-256 digest is persisted.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from .connection import execute, execute_query, execute_query_one, sanitize_row


ACTIVE_STATUSES = {"ACTIVE"}
INACTIVE_STATUSES = {"DISABLED", "REVOKED", "EXPIRED", "DUPLICATE_CONFLICT"}


def _now() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _credential_digest(credential: str) -> str:
    return hashlib.sha256(str(credential).encode("utf-8")).hexdigest()


def _normalise(value: Any) -> str:
    return str(value or "").strip()


def _json_text(value: Any) -> str:
    import json

    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def governance_installed() -> bool:
    """Return whether the v4.1.0 registration table is deployed."""
    try:
        execute_query_one("SELECT 1 AS PRESENT FROM AGENT_REGISTRATIONS FETCH FIRST 1 ROWS ONLY")
        return True
    except Exception:
        return False


def get_registration(agent_id: str) -> Optional[Dict[str, Any]]:
    if not _normalise(agent_id):
        return None
    try:
        row = execute_query_one(
            """SELECT AGENT_ID, OWNER_REF, RUNTIME, ENVIRONMENT, NODE_ID,
                      CAPABILITIES_JSON, CREDENTIAL_VERSION, STATUS,
                      REGISTERED_AT, LAST_SEEN_AT, EXPIRES_AT, IDEMPOTENCY_KEY,
                      CREATED_BY, UPDATED_AT
                 FROM AGENT_REGISTRATIONS WHERE AGENT_ID = :agent_id""",
            {"agent_id": agent_id},
        )
        return sanitize_row(row) if row else None
    except Exception:
        return None


def register_agent(
    agent_id: str,
    owner_ref: str = "",
    runtime: str = "generic",
    environment: str = "unknown",
    node_id: str = "",
    capabilities: Optional[Iterable[str]] = None,
    credential: Optional[str] = None,
    credential_version: str = "1",
    expires_at: Optional[datetime] = None,
    idempotency_key: Optional[str] = None,
    created_by: str = "administrator",
) -> Optional[Dict[str, Any]]:
    """Create or idempotently refresh a registered Agent.

    A caller that omits a credential receives a one-time generated token in
    the result.  Existing registrations never expose their stored digest.
    """
    agent_id = _normalise(agent_id)
    if not agent_id or len(agent_id) > 128:
        raise ValueError("agent_id is required and must be at most 128 characters")
    if not _normalise(owner_ref):
        raise ValueError("owner_ref is required")
    idempotency_key = _normalise(idempotency_key) or f"reg-{uuid.uuid4().hex}"
    credential = credential or f"agt_{secrets.token_urlsafe(32)}"
    existing = get_registration(agent_id)
    if existing:
        same_key = _normalise(existing.get("idempotency_key")) == idempotency_key
        if same_key:
            result = dict(existing)
            result["idempotent"] = True
            return result
        if existing.get("status") == "ACTIVE":
            # Registration updates are explicit; a duplicate active identity
            # must not silently replace its owner or grants.
            raise ValueError("active Agent registration already exists")

    params = {
        "agent_id": agent_id,
        "owner_ref": owner_ref[:256],
        "runtime": runtime[:128],
        "environment": environment[:128],
        "node_id": node_id[:128],
        "capabilities": _json_text(list(capabilities or [])),
        "credential_version": credential_version[:64],
        "credential_hash": _credential_digest(credential),
        "status": "ACTIVE",
        "expires_at": expires_at,
        "idempotency_key": idempotency_key[:160],
        "created_by": created_by[:256],
    }
    try:
        if existing:
            update_params = dict(params)
            update_params.pop("created_by", None)
            execute(
                """UPDATE AGENT_REGISTRATIONS
                      SET OWNER_REF = :owner_ref, RUNTIME = :runtime,
                          ENVIRONMENT = :environment, NODE_ID = :node_id,
                          CAPABILITIES_JSON = :capabilities,
                          CREDENTIAL_VERSION = :credential_version,
                          CREDENTIAL_HASH = :credential_hash, STATUS = :status,
                          EXPIRES_AT = :expires_at,
                          IDEMPOTENCY_KEY = :idempotency_key,
                          UPDATED_AT = CURRENT_TIMESTAMP
                    WHERE AGENT_ID = :agent_id""",
                update_params,
            )
        else:
            execute(
                """INSERT INTO AGENT_REGISTRATIONS
                    (AGENT_ID, OWNER_REF, RUNTIME, ENVIRONMENT, NODE_ID,
                     CAPABILITIES_JSON, CREDENTIAL_VERSION, CREDENTIAL_HASH,
                     STATUS, REGISTERED_AT, LAST_SEEN_AT, EXPIRES_AT,
                     IDEMPOTENCY_KEY, CREATED_BY, UPDATED_AT)
                         VALUES (:agent_id, :owner_ref, :runtime, :environment, :node_id,
                         :capabilities, :credential_version, :credential_hash,
                         :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                         :expires_at, :idempotency_key, :created_by,
                         CURRENT_TIMESTAMP)""",
                params,
            )
    except Exception:
        # A concurrent retry may have won the unique Agent or idempotency key.
        winner = get_registration(agent_id)
        if winner:
            return {**winner, "idempotent": True}
        raise
    result = get_registration(agent_id) or {"agent_id": agent_id, "status": "ACTIVE"}
    result["credential"] = credential
    result["idempotent"] = False
    return result


def adopt_legacy_agent(agent_id: str, created_by: str = "legacy-confirmation") -> Optional[Dict[str, Any]]:
    """Explicitly bind an existing pool Agent to the registration inventory."""
    # Registration is the managed identity boundary.  A pool Agent may
    # already have been registered by the Admin API with a different
    # idempotency key; treating that valid identity as a duplicate makes the
    # Portal release the Agent it just claimed.
    existing = get_registration(agent_id)
    if existing:
        return existing
    try:
        legacy = execute_query_one(
            "SELECT AGENT_ID, AGENT_NAME, AGENT_TYPE, CAPABILITIES, STATUS, PORTAL_NODE_ID "
            "FROM AGENT_REGISTRY WHERE AGENT_ID = :agent_id",
            {"agent_id": agent_id},
        )
    except Exception:
        return None
    if not legacy:
        return None
    return register_agent(
        agent_id=agent_id,
        owner_ref=str(legacy.get("created_by_agent_id") or created_by),
        runtime=str(legacy.get("agent_type") or "platform"),
        environment="managed",
        node_id=str(legacy.get("portal_node_id") or ""),
        capabilities=legacy.get("capabilities") or [],
        created_by=created_by,
        idempotency_key=f"legacy-{agent_id}",
    )


def authenticate_agent(agent_id: str, credential: str) -> Optional[Dict[str, Any]]:
    """Verify a credential and return a safe registration row."""
    row = get_registration(agent_id)
    if not row or row.get("status") not in ACTIVE_STATUSES:
        return None
    expires_at = row.get("expires_at")
    parsed_expiry = _as_datetime(expires_at)
    if parsed_expiry and parsed_expiry <= _now():
        try:
            execute(
                "UPDATE AGENT_REGISTRATIONS SET STATUS = 'EXPIRED', UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
                {"agent_id": agent_id},
            )
        except Exception:
            pass
        return None
    try:
        stored = execute_query_one(
            "SELECT CREDENTIAL_HASH FROM AGENT_REGISTRATIONS WHERE AGENT_ID = :agent_id",
            {"agent_id": agent_id},
        )
        if not stored or not secrets.compare_digest(
            str(stored.get("credential_hash") or ""), _credential_digest(credential)
        ):
            return None
        execute(
            "UPDATE AGENT_REGISTRATIONS SET LAST_SEEN_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id},
        )
        return get_registration(agent_id)
    except Exception:
        return None


def heartbeat(agent_id: str, credential: str) -> bool:
    return authenticate_agent(agent_id, credential) is not None


def set_status(agent_id: str, status: str, actor: str = "administrator") -> bool:
    status = _normalise(status).upper()
    if status not in ACTIVE_STATUSES | INACTIVE_STATUSES:
        raise ValueError("invalid registration status")
    try:
        return execute(
            "UPDATE AGENT_REGISTRATIONS SET STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id",
            {"status": status, "agent_id": agent_id},
        ) > 0
    except Exception:
        return False


def list_registrations(limit: int = 100, status: Optional[str] = None) -> list[Dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    params: Dict[str, Any] = {"limit": limit}
    where = ""
    if status:
        where = " WHERE STATUS = :status"
        params["status"] = status.upper()
    try:
        rows = execute_query(
            """SELECT AGENT_ID, OWNER_REF, RUNTIME, ENVIRONMENT, NODE_ID,
                      CAPABILITIES_JSON, CREDENTIAL_VERSION, STATUS,
                      REGISTERED_AT, LAST_SEEN_AT, EXPIRES_AT, CREATED_BY, UPDATED_AT
                 FROM AGENT_REGISTRATIONS""" + where +
            " ORDER BY UPDATED_AT DESC FETCH FIRST :limit ROWS ONLY",
            params,
        )
        return [sanitize_row(row) for row in rows]
    except Exception:
        return []


def admission_error(agent_id: str, credential: str) -> str:
    row = get_registration(agent_id)
    if not row:
        return "AGENT_NOT_REGISTERED"
    if row.get("status") != "ACTIVE":
        return f"AGENT_{str(row.get('status') or 'INACTIVE').upper()}"
    if not authenticate_agent(agent_id, credential):
        return "AGENT_CREDENTIAL_INVALID"
    return ""
