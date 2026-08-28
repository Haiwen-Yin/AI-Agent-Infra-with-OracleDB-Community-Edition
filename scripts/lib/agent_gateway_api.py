"""Common external-Agent gateway for v4.3.0.

OpenClaw, Hermes and platform Agents use this small protocol instead of
receiving database credentials.  Raw access tokens and client secrets are
returned once; only purpose-separated digests are stored in the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from . import connection, identity_api


class GatewayError(ValueError):
    """Safe protocol error that does not reveal credential state."""


def _compliance_allows(agent_id: str, operation: str) -> bool:
    """Recheck the current authoritative control state for every Gateway use."""
    try:
        from . import edition_features
        if not edition_features.has_feature("compliance"):
            return True
        from . import compliance_api
        return bool(compliance_api.control_allows(agent_id, operation))
    except ImportError:
        # Old independently packaged releases have no compliance module.  A
        # v4.3.4 package always contains it and fails closed on database error.
        return True
    except Exception:
        return False


def _now() -> datetime:
    # Gateway tokens are stored in adapter-neutral naive TIMESTAMP columns and
    # compared to database CURRENT_TIMESTAMP. Keep their wall-clock basis
    # aligned with identity/session expiry values.
    return datetime.now().astimezone().replace(tzinfo=None)


def local_node_id() -> str:
    """Return the stable identity used to scope restart recovery."""
    import os
    return os.environ.get("MEMORY_SERVER_NODE_ID", "").strip() or (
        f"{socket.gethostname()}:{os.environ.get('MEMORY_SERVER_PORT', '8000')}"
    )


def _digest(value: str, purpose: str) -> str:
    return hmac.new(
        identity_api._secret_digest("gateway-pepper", purpose).encode("ascii"),
        str(value).encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def _limit(limit: int = 100) -> tuple[str, Dict[str, Any]]:
    value = max(1, min(int(limit), 500))
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"}:
        return "LIMIT :limit", {"limit": value}
    return "FETCH FIRST :limit ROWS ONLY", {"limit": value}


def _five_minute_deadline_sql() -> str:
    """Return a five-minute expression accepted by the active adapter.

    Oracle-compatible engines use the ANSI ``INTERVAL '5' MINUTE`` form,
    while PostgreSQL requires the unit inside the interval literal.
    Keeping this choice here prevents a PostgreSQL deployment from failing
    only when an Agent instance or delivery is created.
    """
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"}:
        return "CURRENT_TIMESTAMP + INTERVAL '5 minutes'"
    return "CURRENT_TIMESTAMP + INTERVAL '5' MINUTE"


def verify_ed25519_proof(public_key: str, signature: str, message: str) -> bool:
    """Verify an Ed25519 proof without ever persisting a private key."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
        sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        Ed25519PublicKey.from_public_bytes(key).verify(sig, message.encode("utf-8"))
        return True
    except Exception:
        return False


def authenticate_client_secret(agent_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
    if not agent_id or not client_secret:
        return None
    # Enrollment persists the registered Client Secret with the identity
    # service's purpose-separated digest. Gateway must use that same contract;
    # its private _digest() namespace is reserved for short-lived access and
    # delivery tokens, not long-lived registration credentials.
    digest = identity_api._secret_digest(client_secret, "agent-client-secret")
    row = identity_api._row(connection.execute_query_one(
        "SELECT c.AGENT_ID, c.CREDENTIAL_ID, c.CREDENTIAL_TYPE, c.PUBLIC_KEY, c.STATUS, c.EXPIRES_AT "
        "FROM CX_AGENT_CREDENTIALS c JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = c.AGENT_ID "
        "WHERE c.AGENT_ID = :agent_id AND c.SECRET_DIGEST = :digest "
        "AND c.STATUS = 'ACTIVE' AND p.STATUS = 'ACTIVE' "
        "AND (c.EXPIRES_AT IS NULL OR c.EXPIRES_AT > CURRENT_TIMESTAMP)",
        {"agent_id": agent_id, "digest": digest},
    ))
    return row


def authenticate_activation_client_secret(agent_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
    """Authenticate only the one transition allowed before an Agent is active.

    This deliberately cannot issue a work token.  It exists so a freshly
    enrolled Agent can prove possession of its registered credential without
    an administrator manufacturing runtime evidence on its behalf.
    """
    if not agent_id or not client_secret:
        return None
    digest = identity_api._secret_digest(client_secret, "agent-client-secret")
    return identity_api._row(connection.execute_query_one(
        "SELECT c.AGENT_ID,c.CREDENTIAL_ID,c.CREDENTIAL_TYPE,c.PUBLIC_KEY,c.STATUS,p.STATUS AS AGENT_STATUS "
        "FROM CX_AGENT_CREDENTIALS c JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=c.AGENT_ID "
        "WHERE c.AGENT_ID=:agent_id AND c.SECRET_DIGEST=:digest AND c.STATUS='ACTIVE' "
        "AND p.PRINCIPAL_TYPE='AGENT' AND p.STATUS='PENDING_ACTIVATION' "
        "AND (c.EXPIRES_AT IS NULL OR c.EXPIRES_AT>CURRENT_TIMESTAMP)",
        {"agent_id": agent_id, "digest": digest},
    ))


def issue_access_token(agent_id: str, instance_id: str, scopes: Iterable[str], *, ttl_seconds: int = 300, lease_digest: str = "") -> Dict[str, Any]:
    if not agent_id or not instance_id:
        raise GatewayError("agent and instance are required")
    instance = identity_api._row(connection.execute_query_one(
        "SELECT i.INSTANCE_ID, i.AGENT_ID, i.STATUS, i.SECURITY_DOMAIN_ID, i.CHANNEL_ID, "
        "i.FENCING_TOKEN, i.LEASE_EXPIRES_AT, p.STATUS AS AGENT_STATUS "
        "FROM CX_AGENT_INSTANCES i JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = i.AGENT_ID "
        "WHERE i.INSTANCE_ID = :instance_id AND i.AGENT_ID = :agent_id",
        {"instance_id": instance_id, "agent_id": agent_id},
    ))
    if (not instance or str(instance.get("status") or "").upper() != "ACTIVE"
            or str(instance.get("agent_status") or "").upper() != "ACTIVE"):
        raise GatewayError("agent instance is unavailable")
    scope_list = sorted({str(scope).strip() for scope in scopes if str(scope).strip()})
    operation = "remediation" if scope_list and set(scope_list) <= {"compliance.evidence", "compliance.remediation"} else "token"
    if not _compliance_allows(agent_id, operation):
        raise GatewayError("agent control state blocks token issuance")
    ttl = max(30, min(int(ttl_seconds), 900))
    raw = secrets.token_urlsafe(32)
    expires = _now() + timedelta(seconds=ttl)
    connection.execute(
        "INSERT INTO CX_AGENT_ACCESS_TOKENS(TOKEN_DIGEST, AGENT_ID, INSTANCE_ID, SCOPE_JSON, LEASE_DIGEST, FENCING_TOKEN, EXPIRES_AT) "
        "VALUES (:token_digest, :agent_id, :instance_id, :scope_json, :lease_digest, :fencing_token, :expires_at)",
        {"token_digest": _digest(raw, "agent-access-token"), "agent_id": agent_id,
         "instance_id": instance_id, "scope_json": json.dumps(scope_list, separators=(",", ":"), sort_keys=True),
         "lease_digest": lease_digest or None, "fencing_token": instance["fencing_token"], "expires_at": expires},
    )
    return {"access_token": raw, "agent_id": agent_id, "instance_id": instance_id,
            "scopes": scope_list, "expires_at": expires.isoformat()}


def create_instance(agent_id: str, *, channel_id: str = "", security_domain_id: str = "",
                    node_id: str = "", classification: str = "INTERNAL", run_id: str = "") -> Dict[str, Any]:
    """Create an isolated runtime subject for an external Agent."""
    agent = identity_api._row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT'",
        {"agent_id": agent_id},
    ))
    if not agent or str(agent.get("status") or "").upper() not in {"ACTIVE", "PENDING_CONFIRMATION"}:
        raise GatewayError("agent is unavailable")
    if str(agent.get("status") or "").upper() != "ACTIVE":
        raise GatewayError("agent activation is required")
    if channel_id == "CH_PLATFORM_ADMINISTRATION":
        try:
            from . import admin_management
            member = identity_api._row(connection.execute_query_one(
                "SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent "
                "AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'",
                {"group_id": admin_management.ADMIN_GROUP_ID, "agent": agent_id},
            ))
            if not member:
                raise GatewayError("only approved Admin Agents may run in the Platform Administration Channel")
        except ImportError:
            raise GatewayError("Platform Administration control service is unavailable")
    if not _compliance_allows(agent_id, "work"):
        raise GatewayError("agent control state blocks new work")
    if channel_id:
        membership = identity_api._row(connection.execute_query_one(
            "SELECT c.SECURITY_DOMAIN_ID, c.CLASSIFICATION, d.CLASSIFICATION AS DOMAIN_CLASSIFICATION "
            "FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID = c.CHANNEL_ID "
            "JOIN CX_SECURITY_DOMAINS d ON d.SECURITY_DOMAIN_ID = c.SECURITY_DOMAIN_ID "
            "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID = c.SECURITY_DOMAIN_ID "
            "AND dm.PRINCIPAL_ID = :agent_id AND dm.STATUS = 'ACTIVE' "
            "AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL > CURRENT_TIMESTAMP) "
            "WHERE c.CHANNEL_ID = :channel_id AND c.STATUS = 'ACTIVE' AND d.STATUS = 'ACTIVE' "
            "AND m.PRINCIPAL_ID = :agent_id AND m.STATUS = 'ACTIVE' "
            "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"channel_id": channel_id, "agent_id": agent_id},
        ))
        if not membership:
            raise GatewayError("agent is not a Channel member")
        if security_domain_id and security_domain_id != membership.get("security_domain_id"):
            raise GatewayError("security domain binding failed")
        security_domain_id = str(membership.get("security_domain_id") or security_domain_id)
        classification = str(membership.get("classification") or classification)
        try:
            classification = identity_api._classification(classification)
            if not identity_api._classification_meets_minimum(classification, membership.get("domain_classification") or "INTERNAL"):
                raise GatewayError("instance classification is below the Security Domain minimum")
        except (identity_api.IdentityError, KeyError) as exc:
            raise GatewayError("instance classification is invalid") from exc
    else:
        # An unbound instance must still be anchored to a real domain and an
        # active Agent membership. A caller cannot choose an arbitrary domain
        # merely by putting its identifier in the request body.
        if not security_domain_id:
            raise GatewayError("security domain is required for an unbound instance")
        domain = identity_api._row(connection.execute_query_one(
            "SELECT d.SECURITY_DOMAIN_ID, d.CLASSIFICATION FROM CX_SECURITY_DOMAINS d "
            "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID = d.SECURITY_DOMAIN_ID "
            "AND dm.PRINCIPAL_ID = :agent_id AND dm.STATUS = 'ACTIVE' "
            "AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL > CURRENT_TIMESTAMP) "
            "WHERE d.SECURITY_DOMAIN_ID = :security_domain_id AND d.STATUS = 'ACTIVE'",
            {"agent_id": agent_id, "security_domain_id": security_domain_id},
        ))
        if not domain:
            raise GatewayError("agent is not a member of the security domain")
        try:
            classification = identity_api._classification(classification)
            if not identity_api._classification_meets_minimum(classification, domain.get("classification") or "INTERNAL"):
                raise GatewayError("instance classification is below the Security Domain minimum")
        except (identity_api.IdentityError, KeyError) as exc:
            raise GatewayError("instance classification is invalid") from exc
    instance_id = identity_api._id("INS")
    node_id = str(node_id or local_node_id())[:128]
    connection.execute(
        "INSERT INTO CX_AGENT_INSTANCES(INSTANCE_ID, AGENT_ID, CHANNEL_ID, SECURITY_DOMAIN_ID, RUN_ID, "
        "CLASSIFICATION, NODE_ID, STATUS, FENCING_TOKEN, LEASE_EXPIRES_AT) VALUES (:instance_id, :agent_id, :channel_id, "
        ":security_domain_id, :run_id, :classification, :node_id, 'ACTIVE', 1, " + _five_minute_deadline_sql() + ")",
        {"instance_id": instance_id, "agent_id": agent_id, "channel_id": channel_id or None,
         "security_domain_id": security_domain_id or None, "run_id": run_id or None,
         "classification": classification[:32], "node_id": node_id[:128]},
    )
    if channel_id:
        identity_api.enqueue_instance_backlog(agent_id, instance_id, channel_id)
    return {"instance_id": instance_id, "agent_id": agent_id, "channel_id": channel_id,
            "security_domain_id": security_domain_id, "classification": classification, "status": "ACTIVE"}


def heartbeat_instance(agent_id: str, instance_id: str) -> bool:
    if not _compliance_allows(agent_id, "heartbeat"):
        return False
    changed = connection.execute(
        "UPDATE CX_AGENT_INSTANCES SET LAST_SEEN_AT = CURRENT_TIMESTAMP, "
        "LEASE_EXPIRES_AT = " + _five_minute_deadline_sql() + ", UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE INSTANCE_ID = :instance_id AND AGENT_ID = :agent_id AND STATUS = 'ACTIVE' "
        "AND REVOKED_AT IS NULL AND EXISTS (SELECT 1 FROM CX_PRINCIPALS p "
        "WHERE p.PRINCIPAL_ID = :agent_id AND p.STATUS = 'ACTIVE')",
        {"instance_id": instance_id, "agent_id": agent_id},
    ) > 0
    if changed:
        try:
            from . import edition_features
            if not edition_features.has_feature("compliance"):
                return changed
            from . import compliance_api
            compliance_api.observe_gateway_heartbeat(agent_id, instance_id)
        except ImportError:
            pass
    return changed


def revoke_instance(agent_id: str, instance_id: str, reason: str = "revoked") -> bool:
    if not reason.strip():
        raise GatewayError("instance revoke reason is required")
    changed = connection.execute(
        "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
        "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1 WHERE INSTANCE_ID = :instance_id "
        "AND AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
        {"instance_id": instance_id, "agent_id": agent_id, "reason": reason[:1000]},
    ) > 0
    if changed:
        connection.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE INSTANCE_ID = :instance_id "
            "AND REVOKED_AT IS NULL", {"instance_id": instance_id},
        )
        connection.execute(
            "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason WHERE AGENT_ID = :agent_id AND INSTANCE_ID = :instance_id "
            "AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id, "instance_id": instance_id, "reason": reason[:2000]},
        )
    return changed


def reclaim_local_instances(node_id: str, reason: str = "web node restart") -> int:
    """Fence and revoke only instances previously leased by one local node.

    A node restart invalidates its old runtime ownership even if the lease has
    not reached its timeout yet.  The node predicate is mandatory so a
    multi-node Admin Agent group cannot reclaim another node's live instances.
    """
    node_id = str(node_id or "").strip()[:128]
    if not node_id:
        return 0
    changed = connection.execute(
        "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
        "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE NODE_ID = :node_id AND STATUS = 'ACTIVE'",
        {"node_id": node_id, "reason": reason[:1000]},
    )
    if changed:
        connection.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE REVOKED_AT IS NULL AND INSTANCE_ID IN "
            "(SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE NODE_ID = :node_id AND STATUS = 'REVOKED')",
            {"node_id": node_id},
        )
        connection.execute(
            "UPDATE CX_AGENT_DELIVERIES SET STATUS = 'PENDING', CLAIMED_BY = NULL, CLAIM_TOKEN_DIGEST = NULL, "
            "CLAIMED_AT = NULL, VISIBILITY_UNTIL = NULL, FENCING_TOKEN = NULL, "
            "FAILURE_REASON = :reason, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE STATUS = 'CLAIMED' AND INSTANCE_ID IN "
            "(SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE NODE_ID = :node_id AND STATUS = 'REVOKED')",
            {"node_id": node_id, "reason": reason[:2000]},
        )
        connection.execute(
            "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason WHERE INSTANCE_ID IN "
            "(SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE NODE_ID = :node_id AND STATUS = 'REVOKED') "
            "AND STATUS = 'ACTIVE'",
            {"node_id": node_id, "reason": reason[:2000]},
        )
    return int(changed or 0)


def authenticate_access_token(raw_token: str, agent_id: str = "", instance_id: str = "", required_scope: str = "", *, operation: str = "work") -> Optional[Dict[str, Any]]:
    if not raw_token:
        return None
    row = identity_api._row(connection.execute_query_one(
        "SELECT t.TOKEN_DIGEST, t.AGENT_ID, t.INSTANCE_ID, t.SCOPE_JSON, t.LEASE_DIGEST, "
        "t.FENCING_TOKEN, t.EXPIRES_AT, i.STATUS AS INSTANCE_STATUS, i.LEASE_EXPIRES_AT, "
        "i.FENCING_TOKEN AS CURRENT_FENCING_TOKEN, p.STATUS AS AGENT_STATUS "
        "FROM CX_AGENT_ACCESS_TOKENS t JOIN CX_AGENT_INSTANCES i ON i.INSTANCE_ID = t.INSTANCE_ID "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = t.AGENT_ID "
        "WHERE t.TOKEN_DIGEST = :digest AND t.REVOKED_AT IS NULL "
        "AND t.AGENT_ID = i.AGENT_ID "
        "AND t.EXPIRES_AT > CURRENT_TIMESTAMP AND i.STATUS = 'ACTIVE' "
        "AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP AND p.STATUS = 'ACTIVE' "
        "AND t.FENCING_TOKEN = i.FENCING_TOKEN", {"digest": _digest(raw_token, "agent-access-token")},
    ))
    if not row or (agent_id and str(row.get("agent_id")) != agent_id) or (instance_id and str(row.get("instance_id")) != instance_id):
        return None
    if not _compliance_allows(str(row.get("agent_id") or ""), operation):
        return None
    try:
        scopes = set(json.loads(row.get("scope_json") or "[]"))
    except (TypeError, ValueError):
        scopes = set()
    if required_scope and required_scope not in scopes and "*" not in scopes:
        return None
    row["scopes"] = sorted(scopes)
    return row


def revoke_access_token(raw_token: str, reason: str = "revoked") -> bool:
    if not raw_token:
        return False
    return connection.execute(
        "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE TOKEN_DIGEST = :digest AND REVOKED_AT IS NULL",
        {"digest": _digest(raw_token, "agent-access-token")},
    ) > 0


def claim_events(agent_id: str, instance_id: str, limit: int = 50) -> list[Dict[str, Any]]:
    """Claim durable deliveries using an instance-scoped fencing lease."""
    suffix, params = _limit(limit)
    params.update({"agent_id": agent_id, "instance_id": instance_id})
    query = (
        "SELECT d.DELIVERY_ID, d.EVENT_TYPE, d.CHANNEL_ID, d.MESSAGE_ID, d.PAYLOAD_JSON, "
        "d.IDEMPOTENCY_KEY, d.ATTEMPT_COUNT, d.MAX_ATTEMPTS, d.STATUS, d.VISIBILITY_UNTIL, "
        "i.FENCING_TOKEN "
        "FROM CX_AGENT_DELIVERIES d JOIN CX_AGENT_INSTANCES i ON i.INSTANCE_ID = d.INSTANCE_ID "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = d.AGENT_ID "
        "WHERE d.AGENT_ID = :agent_id AND d.INSTANCE_ID = :instance_id AND i.STATUS = 'ACTIVE' "
        "AND p.STATUS = 'ACTIVE' AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP "
        "AND (d.FENCING_TOKEN IS NULL OR d.FENCING_TOKEN = i.FENCING_TOKEN) "
        "AND d.ATTEMPT_COUNT < d.MAX_ATTEMPTS AND (d.STATUS = 'PENDING' OR "
        "(d.STATUS = 'CLAIMED' AND d.VISIBILITY_UNTIL <= CURRENT_TIMESTAMP)) "
        "ORDER BY d.CREATED_AT, d.DELIVERY_ID " + suffix
    )
    rows = identity_api._safe_query(query, params)
    claimed: list[Dict[str, Any]] = []
    for row in rows:
        delivery_id = str(row.get("delivery_id") or "")
        claim_token = secrets.token_urlsafe(32)
        changed = connection.execute(
            "UPDATE CX_AGENT_DELIVERIES SET STATUS = 'CLAIMED', CLAIMED_BY = :instance_id, "
            "CLAIM_TOKEN_DIGEST = :claim_token_digest, CLAIMED_AT = CURRENT_TIMESTAMP, "
            "FENCING_TOKEN = :fencing_token, "
            "VISIBILITY_UNTIL = " + _five_minute_deadline_sql() + ", ATTEMPT_COUNT = ATTEMPT_COUNT + 1, "
            "UPDATED_AT = CURRENT_TIMESTAMP WHERE DELIVERY_ID = :delivery_id AND INSTANCE_ID = :instance_id "
            "AND AGENT_ID = :agent_id AND ATTEMPT_COUNT < MAX_ATTEMPTS "
            "AND (STATUS = 'PENDING' OR (STATUS = 'CLAIMED' AND VISIBILITY_UNTIL <= CURRENT_TIMESTAMP)) "
            "AND EXISTS (SELECT 1 FROM CX_AGENT_INSTANCES i WHERE i.INSTANCE_ID = :instance_id "
            "AND i.AGENT_ID = :agent_id AND i.STATUS = 'ACTIVE' AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP "
            "AND i.FENCING_TOKEN = :fencing_token)",
            {"delivery_id": delivery_id, "instance_id": instance_id, "agent_id": agent_id,
             "claim_token_digest": _digest(claim_token, "agent-delivery-claim"),
             "fencing_token": row.get("fencing_token")},
        )
        if changed:
            row["claim_token"] = claim_token
            claimed.append(row)
    return claimed


def acknowledge_event(agent_id: str, instance_id: str, delivery_id: str, *, claim_token: str = "", success: bool = True, reason: str = "") -> bool:
    if not claim_token:
        return False
    status = "ACKED" if success else "FAILED"
    changed = connection.execute(
        "UPDATE CX_AGENT_DELIVERIES SET STATUS = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT >= MAX_ATTEMPTS "
        "THEN 'DEAD_LETTER' WHEN :status = 'FAILED' THEN 'PENDING' ELSE 'ACKED' END, "
        "CLAIMED_BY = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT < MAX_ATTEMPTS THEN NULL ELSE CLAIMED_BY END, "
        "CLAIM_TOKEN_DIGEST = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT < MAX_ATTEMPTS THEN NULL ELSE CLAIM_TOKEN_DIGEST END, "
        "CLAIMED_AT = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT < MAX_ATTEMPTS THEN NULL ELSE CLAIMED_AT END, "
        "VISIBILITY_UNTIL = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT < MAX_ATTEMPTS THEN NULL ELSE VISIBILITY_UNTIL END, "
        "FENCING_TOKEN = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT < MAX_ATTEMPTS THEN NULL ELSE FENCING_TOKEN END, "
        "ACKED_AT = CASE WHEN :status = 'ACKED' THEN CURRENT_TIMESTAMP ELSE ACKED_AT END, "
        "DEAD_LETTER_AT = CASE WHEN :status = 'FAILED' AND ATTEMPT_COUNT >= MAX_ATTEMPTS "
        "THEN CURRENT_TIMESTAMP ELSE DEAD_LETTER_AT END, FAILURE_REASON = :reason, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE DELIVERY_ID = :delivery_id "
        "AND AGENT_ID = :agent_id AND INSTANCE_ID = :instance_id AND CLAIMED_BY = :instance_id "
        "AND CLAIM_TOKEN_DIGEST = :claim_token_digest AND STATUS = 'CLAIMED' "
        "AND EXISTS (SELECT 1 FROM CX_AGENT_INSTANCES i WHERE i.INSTANCE_ID = :instance_id "
        "AND i.AGENT_ID = :agent_id AND i.STATUS = 'ACTIVE' AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP "
        "AND i.FENCING_TOKEN = (SELECT d2.FENCING_TOKEN FROM CX_AGENT_DELIVERIES d2 "
        "WHERE d2.DELIVERY_ID = :delivery_id))",
        {"status": status, "reason": reason[:2000], "delivery_id": delivery_id,
         "agent_id": agent_id, "instance_id": instance_id,
         "claim_token_digest": _digest(claim_token, "agent-delivery-claim")},
    )
    return changed > 0


def submit_arrival(agent_id: str, instance_id: str, barrier_id: str, report: Dict[str, Any],
                   participant_role: str, idempotency_key: str) -> Dict[str, Any]:
    if not agent_id or not instance_id:
        raise GatewayError("agent and instance are required")
    instance = identity_api._row(connection.execute_query_one(
        "SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID = :instance_id "
        "AND AGENT_ID = :agent_id AND STATUS = 'ACTIVE' AND LEASE_EXPIRES_AT > CURRENT_TIMESTAMP",
        {"instance_id": instance_id, "agent_id": agent_id},
    ))
    if not instance:
        raise GatewayError("agent instance is unavailable")
    return identity_api.arrive_barrier(agent_id, barrier_id, report, participant_role, idempotency_key)


def list_channel_events(principal_id: str, channel_id: str = "", limit: int = 100, before: str = "") -> list[Dict[str, Any]]:
    """Pull only messages from Channels where the Agent is an active member."""
    if channel_id == "CH_PLATFORM_ADMINISTRATION":
        try:
            from . import admin_management
            member = identity_api._row(connection.execute_query_one(
                "SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent "
                "AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'",
                {"group_id": admin_management.ADMIN_GROUP_ID, "agent": principal_id},
            ))
            if not member:
                raise GatewayError("Platform Administration Channel events require approved Admin Agent membership")
        except ImportError:
            raise GatewayError("Platform Administration control service is unavailable")
    suffix, params = _limit(limit)
    params["principal_id"] = principal_id
    query = (
        "SELECT msg.MESSAGE_ID, msg.CHANNEL_ID, msg.THREAD_TYPE, msg.THREAD_ID, msg.PRINCIPAL_ID, "
        "msg.BODY_TEXT, msg.MESSAGE_TYPE, msg.REFERENCE_JSON, msg.CREATED_AT "
        "FROM CX_CHANNEL_MESSAGES msg JOIN CX_CHANNEL_MEMBERS cm ON cm.CHANNEL_ID = msg.CHANNEL_ID "
        "WHERE cm.PRINCIPAL_ID = :principal_id AND cm.STATUS = 'ACTIVE' "
        "AND (cm.VALID_UNTIL IS NULL OR cm.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND msg.REDACTED_AT IS NULL "
        "AND (msg.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = msg.THREAD_ID "
        "AND tm.PRINCIPAL_ID = :principal_id AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP)))"
    )
    if channel_id:
        query += " AND msg.CHANNEL_ID = :channel_id"
        params["channel_id"] = channel_id
    if before:
        query += " AND msg.MESSAGE_ID < :before"
        params["before"] = before
    query += " ORDER BY msg.CREATED_AT DESC, msg.MESSAGE_ID DESC " + suffix
    return identity_api._safe_query(query, params)


def add_channel_member(actor_principal_id: str, channel_id: str, member_principal_id: str,
                       role: str = "MEMBER", reason: str = "") -> bool:
    try:
        from . import admin_management
        if admin_management._protected_channel(channel_id):
            admin_management.can_add_protected_member(actor_principal_id, member_principal_id, reason)
            if str(role or "").upper() not in {"REVIEWER", "OPERATOR"}:
                raise GatewayError("protected Platform Administration Channel role is invalid")
    except ImportError:
        pass
    if not reason.strip():
        raise GatewayError("membership addition reason is required")
    identity_api._assert_channel_member(actor_principal_id, channel_id, "channels.manage_members")
    if not member_principal_id:
        raise GatewayError("member is required")
    member_role = str(role or "MEMBER").upper()
    if member_role not in {"MEMBER", "MODERATOR", "REVIEWER", "OPERATOR"}:
        raise GatewayError("member role is invalid")
    channel = identity_api._row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID, STATUS FROM CX_CHANNELS WHERE CHANNEL_ID = :channel_id",
        {"channel_id": channel_id},
    ))
    if not channel or str(channel.get("status") or "").upper() != "ACTIVE":
        raise GatewayError("channel is unavailable")
    principal = identity_api._row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id "
        "AND STATUS = 'ACTIVE'", {"principal_id": member_principal_id},
    ))
    if not principal:
        raise GatewayError("member principal is unavailable")
    domain_member = identity_api._row(connection.execute_query_one(
        "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID = :security_domain_id "
        "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"security_domain_id": channel["security_domain_id"], "principal_id": member_principal_id},
    ))
    # A Channel is not a way to grant Domain access. Administrators must first
    # add a reviewed Principal to the Security Domain, then admit it here.
    if not domain_member:
        raise GatewayError("member is outside the Channel security domain")
    revived = connection.execute(
        "UPDATE CX_CHANNEL_MEMBERS SET STATUS = 'ACTIVE', MEMBER_ROLE = :member_role, "
        "VALID_UNTIL = NULL WHERE CHANNEL_ID = :channel_id AND PRINCIPAL_ID = :principal_id",
        {"channel_id": channel_id, "principal_id": member_principal_id, "member_role": member_role[:32]},
    )
    if revived:
        identity_api._audit(actor_principal_id, "CHANNEL_MEMBER_ADD", "CHANNEL", channel_id, "ALLOW", reason)
        return True
    try:
        changed = connection.execute(
            "INSERT INTO CX_CHANNEL_MEMBERS(MEMBER_ID, CHANNEL_ID, PRINCIPAL_ID, MEMBER_ROLE) "
            "VALUES (:member_id, :channel_id, :principal_id, :member_role)",
            {"member_id": identity_api._id("CM"), "channel_id": channel_id,
             "principal_id": member_principal_id, "member_role": member_role[:32]},
        ) > 0
    except Exception as exc:
        raise GatewayError("member could not be added") from exc
    if changed:
        identity_api._audit(actor_principal_id, "CHANNEL_MEMBER_ADD", "CHANNEL", channel_id, "ALLOW", reason)
    return changed


def remove_channel_member(actor_principal_id: str, channel_id: str, member_principal_id: str, reason: str) -> bool:
    try:
        from . import admin_management
        if admin_management._protected_channel(channel_id):
            raise GatewayError("protected Platform Administration Channel membership is managed by the administration service")
    except ImportError:
        pass
    if not reason.strip():
        raise GatewayError("membership removal reason is required")
    identity_api._assert_channel_member(actor_principal_id, channel_id, "channels.manage_members")
    changed = connection.execute(
        "UPDATE CX_CHANNEL_MEMBERS SET STATUS = 'REVOKED', VALID_UNTIL = CURRENT_TIMESTAMP "
        "WHERE CHANNEL_ID = :channel_id AND PRINCIPAL_ID = :principal_id AND MEMBER_ROLE <> 'OWNER' AND STATUS = 'ACTIVE'",
        {"channel_id": channel_id, "principal_id": member_principal_id},
    ) > 0
    if changed:
        # Revocation fences channel-scoped instances and their short-lived
        # tokens immediately; it does not touch the same Agent elsewhere.
        connection.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND CHANNEL_ID = :channel_id AND STATUS = 'ACTIVE'",
            {"agent_id": member_principal_id, "channel_id": channel_id, "reason": reason[:1000]},
        )
        connection.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND INSTANCE_ID IN "
            "(SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE AGENT_ID = :agent_id AND CHANNEL_ID = :channel_id)",
            {"agent_id": member_principal_id, "channel_id": channel_id},
        )
        identity_api._audit(actor_principal_id, "CHANNEL_MEMBER_REMOVE", "CHANNEL", channel_id, "ALLOW", reason)
    return changed
