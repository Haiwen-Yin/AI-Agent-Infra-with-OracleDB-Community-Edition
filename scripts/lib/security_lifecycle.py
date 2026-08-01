"""Database services for the v4.3 identity and governed-content lifecycle.

The module is intentionally separate from the HTTP layer.  It contains no
framework-specific code and treats opaque token values as write-only output.
Every mutation records a reasoned security event and rechecks the current
database state instead of trusting a capability manifest cached by a client.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

from . import connection, governed_contracts, identity_api


class LifecycleError(ValueError):
    """Safe service boundary error with no secret or identity enumeration."""


def _row(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): item for key, item in dict(value).items()} if value else None


def _rows(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(value) or {} for value in values]


def _dialect() -> str:
    return str(getattr(connection, "DATABASE_DIALECT", "") or "").lower()


def _limit(limit: int) -> str:
    return "LIMIT :limit" if _dialect() in {"postgresql", "pg"} else "FETCH FIRST :limit ROWS ONLY"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _id(prefix: str) -> str:
    return identity_api._id(prefix)


def _now():
    return identity_api._now()


def _audit(actor: Optional[str], action: str, resource_type: str, resource_id: str, outcome: str, reason: str) -> None:
    identity_api._audit(actor, action, resource_type, resource_id, outcome, reason)


def _require(actor: str, action: str) -> None:
    identity_api._require(actor, action)


def _secret_digest(value: str, purpose: str) -> str:
    return identity_api._secret_digest(value, purpose)


def _valid_password(password: str) -> bool:
    return isinstance(password, str) and len(password) >= 12


def _totp(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _verify_totp_secret(secret: bytes, code: str, now: Optional[float] = None) -> bool:
    normalized = str(code or "").strip()
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    counter = int((now if now is not None else time.time()) // 30)
    return any(hmac.compare_digest(_totp(secret, counter + offset), normalized) for offset in (-1, 0, 1))


def _decrypt_totp(value: str) -> bytes:
    try:
        from .connection_crypto import decrypt_section
        payload = decrypt_section(value)
        encoded = str(payload["secret"]).upper()
        secret = base64.b32decode(encoded + ("=" * (-len(encoded) % 8)), casefold=True)
    except Exception as exc:
        raise LifecycleError("MFA factor is unavailable") from exc
    return secret


def link_external_identity(
    actor_principal_id: str,
    target_principal_id: str,
    identity_type: str,
    provider: str,
    subject_key: str,
    *,
    current_identity_proven: bool,
    target_mfa_satisfied: bool,
    approval_present: bool = False,
    reason: str,
) -> Dict[str, Any]:
    decision = governed_contracts.identity_link_decision(
        identity_type, provider, subject_key, actor_id=actor_principal_id,
        target_principal_id=target_principal_id,
        current_identity_proven=current_identity_proven,
        target_mfa_satisfied=target_mfa_satisfied,
        approval_present=approval_present, reason=reason,
    )
    if not decision.allowed:
        raise LifecycleError(decision.message)
    _require(actor_principal_id, "users.identity.link")
    target = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": target_principal_id},
    ))
    if not target or target.get("status", "").upper() != "ACTIVE" or target.get("principal_type", "").upper() != "HUMAN":
        raise LifecycleError("identity target is unavailable")
    existing = _row(connection.execute_query_one(
        "SELECT IDENTITY_ID, PRINCIPAL_ID, STATUS FROM CX_HUMAN_IDENTITIES "
        "WHERE IDENTITY_TYPE = :identity_type AND PROVIDER = :provider AND SUBJECT_KEY = :subject_key",
        {"identity_type": identity_type.upper(), "provider": provider[:256], "subject_key": subject_key[:512]},
    ))
    if existing and str(existing.get("principal_id")) != target_principal_id:
        raise LifecycleError("identity target is unavailable")
    if existing:
        connection.execute(
            "INSERT INTO CX_IDENTITY_LINK_AUDIT(LINK_EVENT_ID, IDENTITY_ID, PRINCIPAL_ID, ACTOR_PRINCIPAL_ID, PROVIDER, SUBJECT_DIGEST, REASON, OUTCOME) "
            "VALUES (:event_id, :identity_id, :principal_id, :actor, :provider, :subject_digest, :reason, 'IDEMPOTENT')",
            {"event_id": _id("ILA"), "identity_id": existing["identity_id"],
             "principal_id": target_principal_id, "actor": actor_principal_id,
             "provider": provider[:256], "subject_digest": _secret_digest(subject_key, "identity-subject"),
             "reason": reason[:2000]},
        )
        return {"identity_id": existing["identity_id"], "principal_id": target_principal_id, "idempotent": True}
    identity_id = _id("HI")
    connection.execute(
        "INSERT INTO CX_HUMAN_IDENTITIES(IDENTITY_ID, PRINCIPAL_ID, IDENTITY_TYPE, PROVIDER, SUBJECT_KEY, STATUS) "
        "VALUES (:identity_id, :principal_id, :identity_type, :provider, :subject_key, 'ACTIVE')",
        {"identity_id": identity_id, "principal_id": target_principal_id,
         "identity_type": identity_type.upper(), "provider": provider[:256], "subject_key": subject_key[:512]},
    )
    connection.execute(
        "INSERT INTO CX_IDENTITY_LINK_AUDIT(LINK_EVENT_ID, IDENTITY_ID, PRINCIPAL_ID, ACTOR_PRINCIPAL_ID, PROVIDER, SUBJECT_DIGEST, REASON, OUTCOME) "
        "VALUES (:event_id, :identity_id, :principal_id, :actor, :provider, :subject_digest, :reason, 'CREATED')",
        {"event_id": _id("ILA"), "identity_id": identity_id, "principal_id": target_principal_id,
         "actor": actor_principal_id, "provider": provider[:256],
         "subject_digest": _secret_digest(subject_key, "identity-subject"), "reason": reason[:2000]},
    )
    _audit(actor_principal_id, "IDENTITY_LINK", "HUMAN_IDENTITY", identity_id, "ALLOW", reason)
    return {"identity_id": identity_id, "principal_id": target_principal_id, "identity_type": identity_type.upper(), "provider": provider[:256]}


def list_external_identities(actor_principal_id: str, target_principal_id: str) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "users.read")
    if not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("identity is outside the delegated scope")
    return _rows(connection.execute_query(
        "SELECT IDENTITY_ID, PRINCIPAL_ID, IDENTITY_TYPE, PROVIDER, SUBJECT_KEY, STATUS, LAST_LOGIN_AT, CREATED_AT "
        "FROM CX_HUMAN_IDENTITIES WHERE PRINCIPAL_ID = :principal_id ORDER BY CREATED_AT",
        {"principal_id": target_principal_id},
    ))


def set_mfa_required(actor_principal_id: str, target_principal_id: str, required: bool, reason: str) -> Dict[str, Any]:
    _require(actor_principal_id, "users.security.manage")
    if not reason.strip() or not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise LifecycleError("MFA policy change is not allowed")
    if required and not has_active_mfa_factor(target_principal_id):
        raise LifecycleError("an active MFA factor is required before MFA can be enforced")
    changed = connection.execute(
        "UPDATE CX_PRINCIPALS SET MFA_REQUIRED = :required, PERMISSION_VERSION = PERMISSION_VERSION + 1, "
        "UPDATED_AT = CURRENT_TIMESTAMP WHERE PRINCIPAL_ID = :principal_id AND PRINCIPAL_TYPE = 'HUMAN'",
        {"required": bool(required) if _dialect() in {"postgresql", "pg"} else ("Y" if required else "N"), "principal_id": target_principal_id},
    )
    if changed:
        identity_api.revoke_principal_sessions(target_principal_id, "MFA policy changed")
        _audit(actor_principal_id, "MFA_POLICY_CHANGE", "HUMAN", target_principal_id, "ALLOW", reason)
    return {"principal_id": target_principal_id, "mfa_required": bool(required), "changed": bool(changed)}


def enroll_totp(actor_principal_id: str, target_principal_id: str, reason: str) -> Dict[str, Any]:
    if actor_principal_id != target_principal_id:
        _require(actor_principal_id, "users.security.manage")
    else:
        _require(actor_principal_id, "profile.update")
    if not reason.strip() or not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise LifecycleError("MFA enrollment is not allowed")
    secret = secrets.token_bytes(20)
    encoded = base64.b32encode(secret).decode("ascii").rstrip("=")
    from .connection_crypto import encrypt_section
    factor_id = _id("MFA")
    connection.execute(
        "UPDATE CX_MFA_FACTORS SET STATUS = 'REVOKED' "
        "WHERE PRINCIPAL_ID = :principal_id AND FACTOR_TYPE = 'TOTP' AND STATUS = 'PENDING'",
        {"principal_id": target_principal_id},
    )
    connection.execute(
        "INSERT INTO CX_MFA_FACTORS(FACTOR_ID, PRINCIPAL_ID, FACTOR_TYPE, SECRET_CIPHERTEXT, STATUS) "
        "VALUES (:factor_id, :principal_id, 'TOTP', :secret_ciphertext, 'PENDING')",
        {"factor_id": factor_id, "principal_id": target_principal_id,
         "secret_ciphertext": encrypt_section({"secret": encoded})},
    )
    _audit(actor_principal_id, "MFA_ENROLL", "MFA_FACTOR", factor_id, "ALLOW", reason)
    return {"factor_id": factor_id, "factor_type": "TOTP", "secret": encoded, "otpauth_uri": "otpauth://totp/Chuanxu:%s?secret=%s&issuer=Chuanxu" % (target_principal_id, encoded)}


def confirm_totp(target_principal_id: str, factor_id: str, code: str, reason: str = "MFA enrollment confirmation") -> bool:
    row = _row(connection.execute_query_one(
        "SELECT FACTOR_ID, SECRET_CIPHERTEXT, STATUS FROM CX_MFA_FACTORS "
        "WHERE FACTOR_ID = :factor_id AND PRINCIPAL_ID = :principal_id AND FACTOR_TYPE = 'TOTP'",
        {"factor_id": factor_id, "principal_id": target_principal_id},
    ))
    if not row or row.get("status", "").upper() not in {"PENDING", "ACTIVE"} or not _verify_totp_secret(_decrypt_totp(str(row["secret_ciphertext"])), code):
        return False
    changed = connection.execute(
        "UPDATE CX_MFA_FACTORS SET STATUS = 'ACTIVE', VERIFIED_AT = CURRENT_TIMESTAMP "
        "WHERE FACTOR_ID = :factor_id AND PRINCIPAL_ID = :principal_id AND STATUS = 'PENDING'",
        {"factor_id": factor_id, "principal_id": target_principal_id},
    )
    if changed:
        _audit(target_principal_id, "MFA_CONFIRM", "MFA_FACTOR", factor_id, "ALLOW", reason)
    return bool(changed or str(row.get("status")).upper() == "ACTIVE")


def issue_recovery_codes(
    actor_principal_id: str, target_principal_id: str, reason: str, count: int = 8,
    *, actor_mfa_satisfied: bool = False,
) -> Dict[str, Any]:
    if actor_principal_id != target_principal_id:
        _require(actor_principal_id, "users.security.manage")
    elif not actor_mfa_satisfied:
        raise LifecycleError("recovery code issuance requires an authenticated MFA session")
    if not reason.strip() or not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise LifecycleError("recovery code operation is not allowed")
    count = max(4, min(int(count), 12))
    connection.execute("UPDATE CX_MFA_RECOVERY_CODES SET STATUS = 'REVOKED' WHERE PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE'", {"principal_id": target_principal_id})
    codes = [secrets.token_hex(6).upper() for _ in range(count)]
    for code in codes:
        connection.execute(
            "INSERT INTO CX_MFA_RECOVERY_CODES(CODE_ID, PRINCIPAL_ID, CODE_DIGEST, STATUS) VALUES (:code_id, :principal_id, :digest, 'ACTIVE')",
            {"code_id": _id("MRC"), "principal_id": target_principal_id, "digest": _secret_digest(code, "mfa-recovery")},
        )
    _audit(actor_principal_id, "MFA_RECOVERY_CODES_ISSUE", "HUMAN", target_principal_id, "ALLOW", reason)
    return {"principal_id": target_principal_id, "codes": codes, "count": len(codes)}


def verify_mfa(principal_id: str, code: str) -> str:
    factors = _rows(connection.execute_query(
        "SELECT FACTOR_ID, SECRET_CIPHERTEXT FROM CX_MFA_FACTORS WHERE PRINCIPAL_ID = :principal_id AND FACTOR_TYPE = 'TOTP' AND STATUS = 'ACTIVE'",
        {"principal_id": principal_id},
    ))
    for factor in factors:
        if _verify_totp_secret(_decrypt_totp(str(factor.get("secret_ciphertext") or "")), code):
            connection.execute(
                "UPDATE CX_MFA_FACTORS SET LAST_USED_AT = CURRENT_TIMESTAMP WHERE FACTOR_ID = :factor_id",
                {"factor_id": factor.get("factor_id")},
            )
            return "TOTP"
    digest = _secret_digest(str(code or ""), "mfa-recovery")
    changed = connection.execute(
        "UPDATE CX_MFA_RECOVERY_CODES SET STATUS = 'USED', USED_AT = CURRENT_TIMESTAMP "
        "WHERE PRINCIPAL_ID = :principal_id AND CODE_DIGEST = :digest AND STATUS = 'ACTIVE'",
        {"principal_id": principal_id, "digest": digest},
    )
    return "RECOVERY_CODE" if changed else ""


def has_active_mfa_factor(principal_id: str) -> bool:
    """Return whether a Principal has a usable TOTP factor for login."""
    rows = connection.execute_query(
        "SELECT FACTOR_ID FROM CX_MFA_FACTORS "
        "WHERE PRINCIPAL_ID = :principal_id AND FACTOR_TYPE = 'TOTP' AND STATUS = 'ACTIVE'",
        {"principal_id": principal_id},
    )
    return bool(rows)


def mfa_required(principal_id: str) -> bool:
    row = _row(connection.execute_query_one("SELECT MFA_REQUIRED FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id", {"principal_id": principal_id})) or {}
    return (
        str(row.get("mfa_required") or "").upper() in {"Y", "YES", "TRUE", "1"}
        or row.get("mfa_required") is True
    )


def record_login_failure(username: str) -> None:
    """Increment a bounded database lockout counter without revealing account state."""
    # Bind the deadline instead of embedding database-specific interval syntax.
    # This keeps lockout behavior identical across Oracle, PostgreSQL, and
    # YashanDB and avoids relying on a server clock expression in one adapter.
    locked_until = _now() + timedelta(minutes=15)
    # Keep the threshold decision inside one row update.  A read followed by
    # an update loses concurrent failures and can leave an account unlocked.
    connection.execute(
        "UPDATE CX_HUMAN_IDENTITIES SET "
        "FAILED_LOGIN_COUNT = CASE WHEN COALESCE(FAILED_LOGIN_COUNT, 0) + 1 >= 5 THEN 0 "
        "ELSE COALESCE(FAILED_LOGIN_COUNT, 0) + 1 END, "
        "LOCKED_UNTIL = CASE WHEN COALESCE(FAILED_LOGIN_COUNT, 0) + 1 >= 5 THEN :locked_until "
        "ELSE LOCKED_UNTIL END "
        "WHERE IDENTITY_TYPE = 'LOCAL' AND SUBJECT_KEY = :username",
        {"username": str(username or "").casefold(), "locked_until": locked_until},
    )


def is_login_locked(username: str) -> bool:
    """Return lock state without revealing whether a username exists."""
    row = _row(connection.execute_query_one(
        "SELECT LOCKED_UNTIL FROM CX_HUMAN_IDENTITIES "
        "WHERE IDENTITY_TYPE = 'LOCAL' AND SUBJECT_KEY = :username",
        {"username": str(username or "").casefold()},
    ))
    locked_until = identity_api._timestamp((row or {}).get("locked_until"))
    return bool(locked_until and locked_until > _now())


def record_login_success(principal_id: str) -> None:
    """Clear the bounded lockout counter after a complete admission."""
    connection.execute(
        "UPDATE CX_HUMAN_IDENTITIES SET FAILED_LOGIN_COUNT = 0, LOCKED_UNTIL = NULL, "
        "LAST_LOGIN_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE PRINCIPAL_ID = :principal_id AND IDENTITY_TYPE = 'LOCAL'",
        {"principal_id": principal_id},
    )


def issue_password_reset(username: str, *, reason: str = "self-service password reset") -> Dict[str, Any]:
    """Issue a purpose-separated one-time reset token; callers should return a generic response."""
    row = _row(connection.execute_query_one(
        "SELECT IDENTITY_ID, PRINCIPAL_ID, STATUS FROM CX_HUMAN_IDENTITIES WHERE IDENTITY_TYPE = 'LOCAL' AND SUBJECT_KEY = :username",
        {"username": str(username or "").casefold()},
    ))
    raw = secrets.token_urlsafe(32)
    if row and str(row.get("status") or "").upper() == "ACTIVE":
        expires = _now() + timedelta(minutes=15)
        connection.execute(
            "INSERT INTO CX_PASSWORD_RESET_TOKENS(TOKEN_ID, PRINCIPAL_ID, TOKEN_DIGEST, PURPOSE, EXPIRES_AT) "
            "VALUES (:token_id, :principal_id, :token_digest, 'PASSWORD_RESET', :expires_at)",
            {"token_id": _id("PRT"), "principal_id": row["principal_id"], "token_digest": _secret_digest(raw, "password-reset"), "expires_at": expires},
        )
        _audit(None, "PASSWORD_RESET_ISSUE", "HUMAN", str(row["principal_id"]), "PENDING", reason)
    return {"issued": bool(row), "token": raw if row else None, "expires_in_seconds": 900}


def consume_password_reset(token: str, new_password: str, *, reason: str = "password reset") -> bool:
    if not _valid_password(new_password):
        raise LifecycleError("replacement password does not meet policy")
    digest = _secret_digest(token, "password-reset")
    hashed = identity_api.hash_password_argon2id(new_password)

    def _commit(tx: Any) -> str:
        # Lock the token before checking expiry/consumption.  The conditional
        # update alone prevents double use, but the lock also makes the
        # password, legacy mirror, Session revocation, and audit one winner.
        row = _row(tx.query_one(
            "SELECT TOKEN_ID, PRINCIPAL_ID, EXPIRES_AT, CONSUMED_AT FROM CX_PASSWORD_RESET_TOKENS "
            "WHERE TOKEN_DIGEST = :token_digest AND PURPOSE = 'PASSWORD_RESET' FOR UPDATE",
            {"token_digest": digest},
        ))
        expires_at = identity_api._timestamp(row.get("expires_at")) if row else None
        if not row or row.get("consumed_at") is not None or expires_at is None or expires_at <= _now():
            raise LifecycleError("password reset token is invalid or expired")
        changed = tx.execute(
            "UPDATE CX_PASSWORD_RESET_TOKENS SET CONSUMED_AT = CURRENT_TIMESTAMP WHERE TOKEN_ID = :token_id AND CONSUMED_AT IS NULL",
            {"token_id": row["token_id"]},
        )
        if changed != 1:
            raise LifecycleError("password reset token is invalid or expired")
        identity = _row(tx.query_one(
            "SELECT USERNAME FROM CX_HUMAN_IDENTITIES WHERE PRINCIPAL_ID = :principal_id AND IDENTITY_TYPE = 'LOCAL' FOR UPDATE",
            {"principal_id": row["principal_id"]},
        )) or {}
        changed_identity = tx.execute(
            "UPDATE CX_HUMAN_IDENTITIES SET PASSWORD_HASH = :password_hash, PASSWORD_VERSION = 'argon2id-v1', "
            "FAILED_LOGIN_COUNT = 0, LOCKED_UNTIL = NULL, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :principal_id AND IDENTITY_TYPE = 'LOCAL'",
            {"password_hash": hashed, "principal_id": row["principal_id"]},
        )
        if changed_identity != 1:
            raise LifecycleError("password reset identity is unavailable")
        if identity.get("username"):
            tx.execute(
                "UPDATE SYSTEM_USERS SET PASSWORD_HASH = :password_hash, UPDATED_AT = CURRENT_TIMESTAMP WHERE USERNAME = :username",
                {"password_hash": hashed, "username": identity["username"]},
            )
        tx.execute(
            "UPDATE CX_WEB_SESSIONS SET REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason "
            "WHERE PRINCIPAL_ID = :principal_id AND REVOKED_AT IS NULL",
            {"principal_id": row["principal_id"], "reason": "password reset"},
        )
        tx.execute(
            "UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :principal_id",
            {"principal_id": row["principal_id"]},
        )
        identity_api._audit_tx(
            tx, str(row["principal_id"]), "PASSWORD_RESET_COMMIT", "HUMAN",
            str(row["principal_id"]), "ALLOW", reason,
        )
        return str(row["principal_id"])

    connection.execute_transaction_callback(_commit)
    return True


def list_sessions(actor_principal_id: str, target_principal_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "users.sessions.read")
    target = target_principal_id or actor_principal_id
    if target != actor_principal_id and not identity_api._principal_visible_to(actor_principal_id, target):
        raise PermissionError("sessions are outside the delegated scope")
    return _rows(connection.execute_query(
        "SELECT SESSION_DIGEST, PRINCIPAL_ID, AUTH_METHOD, MFA_LEVEL, NODE_ID, PERMISSION_VERSION, EXPIRES_AT, LAST_SEEN_AT, REVOKED_AT, CREATED_AT "
        "FROM CX_WEB_SESSIONS WHERE PRINCIPAL_ID = :principal_id ORDER BY CREATED_AT DESC " + _limit(limit),
        {"principal_id": target, "limit": max(1, min(int(limit), 500))},
    ))


def revoke_session_for_principal(actor_principal_id: str, target_principal_id: str, session_digest: str, reason: str) -> bool:
    _require(actor_principal_id, "sessions.revoke")
    if not reason.strip() or not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise LifecycleError("session revocation is not allowed")
    changed = connection.execute("UPDATE CX_WEB_SESSIONS SET REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason WHERE SESSION_DIGEST = :session_digest AND PRINCIPAL_ID = :principal_id AND REVOKED_AT IS NULL", {"session_digest": session_digest, "principal_id": target_principal_id, "reason": reason[:1000]})
    if changed:
        _audit(actor_principal_id, "SESSION_REVOKE", "SESSION", session_digest, "ALLOW", reason)
    return bool(changed)


def create_delegation(actor_principal_id: str, grantee_id: str, permissions: List[str], data_scope: str, reason: str, valid_until: Any = None) -> Dict[str, Any]:
    _require(actor_principal_id, "users.delegations.manage")
    if actor_principal_id == grantee_id:
        raise LifecycleError("delegation cannot target the granting principal")
    grantee = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": grantee_id},
    ))
    if not grantee or str(grantee.get("principal_type") or "").upper() != "HUMAN" or str(grantee.get("status") or "").upper() != "ACTIVE":
        raise LifecycleError("delegation target is unavailable")
    if not identity_api._principal_visible_to(actor_principal_id, grantee_id):
        raise PermissionError("delegation target is outside the delegated scope")
    grantor = identity_api.effective_access(actor_principal_id, "users.delegations.manage")
    grantor_permissions: set[str] = set()
    for role in grantor.get("roles", []):
        template = _row(connection.execute_query_one("SELECT PERMISSIONS_JSON FROM CX_ROLE_TEMPLATES WHERE ROLE_CODE = :role_code", {"role_code": role}))
        if template:
            try:
                grantor_permissions.update(json.loads(template.get("permissions_json") or "[]"))
            except (TypeError, ValueError):
                pass
        fallback = identity_api.ROLE_FALLBACKS.get(str(role).upper(), {})
        grantor_permissions.update(fallback.get("permissions", set()))
    decision = governed_contracts.delegation_decision(actor_principal_id, grantee_id, permissions, data_scope, grantor_permissions=grantor_permissions, reason=reason, valid_until=valid_until, target_scope="ORG_SUBTREE")
    if not decision.allowed:
        raise LifecycleError(decision.message)
    delegation_id = _id("DEL")
    connection.execute("INSERT INTO CX_DELEGATIONS(DELEGATION_ID, GRANTOR_PRINCIPAL_ID, GRANTEE_PRINCIPAL_ID, PERMISSIONS_JSON, DATA_SCOPE, VALID_UNTIL, REASON, STATUS) VALUES (:delegation_id, :grantor, :grantee, :permissions, :data_scope, :valid_until, :reason, 'ACTIVE')", {"delegation_id": delegation_id, "grantor": actor_principal_id, "grantee": grantee_id, "permissions": _json(permissions), "data_scope": data_scope.upper(), "valid_until": identity_api._timestamp(valid_until) if valid_until else None, "reason": reason[:2000]})
    connection.execute("UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP WHERE PRINCIPAL_ID = :principal_id", {"principal_id": grantee_id})
    _audit(actor_principal_id, "DELEGATION_CREATE", "DELEGATION", delegation_id, "ALLOW", reason)
    return {"delegation_id": delegation_id, "grantor_principal_id": actor_principal_id, "grantee_principal_id": grantee_id, "permissions": permissions, "data_scope": data_scope.upper(), "status": "ACTIVE"}


def list_delegations(actor_principal_id: str, limit: int = 100, target_principal_id: str = "") -> List[Dict[str, Any]]:
    _require(actor_principal_id, "users.delegations.read")
    target = str(target_principal_id or "").strip()
    if target and target != actor_principal_id:
        if not identity_api._principal_visible_to(actor_principal_id, target):
            raise PermissionError("delegation target is outside the delegated scope")
        where = "(GRANTOR_PRINCIPAL_ID = :target OR GRANTEE_PRINCIPAL_ID = :target)"
        params = {"target": target, "limit": max(1, min(int(limit), 500))}
    else:
        where = "(GRANTOR_PRINCIPAL_ID = :principal_id OR GRANTEE_PRINCIPAL_ID = :principal_id)"
        params = {"principal_id": actor_principal_id, "limit": max(1, min(int(limit), 500))}
    return _rows(connection.execute_query("SELECT DELEGATION_ID, GRANTOR_PRINCIPAL_ID, GRANTEE_PRINCIPAL_ID, PERMISSIONS_JSON, DATA_SCOPE, VALID_UNTIL, STATUS, REASON, CREATED_AT FROM CX_DELEGATIONS WHERE " + where + " ORDER BY CREATED_AT DESC " + _limit(limit), params))


def revoke_delegation(actor_principal_id: str, delegation_id: str, reason: str) -> bool:
    _require(actor_principal_id, "users.delegations.manage")
    if not reason.strip():
        raise LifecycleError("delegation revocation reason is required")
    row = _row(connection.execute_query_one(
        "SELECT DELEGATION_ID, GRANTOR_PRINCIPAL_ID, GRANTEE_PRINCIPAL_ID, STATUS "
        "FROM CX_DELEGATIONS WHERE DELEGATION_ID = :delegation_id",
        {"delegation_id": delegation_id},
    ))
    if not row or str(row.get("status") or "").upper() != "ACTIVE":
        return False
    grantor = str(row.get("grantor_principal_id") or "")
    grantee = str(row.get("grantee_principal_id") or "")
    if actor_principal_id not in {grantor, grantee} and identity_api.effective_access(actor_principal_id, "users.delegations.manage.all")["decision"] != "ALLOW":
        raise PermissionError("delegation is outside the delegated scope")
    changed = connection.execute(
        "UPDATE CX_DELEGATIONS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, VERSION = VERSION + 1 "
        "WHERE DELEGATION_ID = :delegation_id AND STATUS = 'ACTIVE'",
        {"delegation_id": delegation_id},
    )
    if changed:
        connection.execute(
            "UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :principal_id",
            {"principal_id": grantee},
        )
        identity_api.revoke_principal_sessions(grantee, "delegation revoked")
        _audit(actor_principal_id, "DELEGATION_REVOKE", "DELEGATION", delegation_id, "ALLOW", reason)
    return bool(changed)


def list_agent_relationships(actor_principal_id: str, agent_id: str) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "agents.read")
    if not identity_api._agent_visible_to(actor_principal_id, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    return _rows(connection.execute_query("SELECT RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, RESPONSIBLE_GROUP_ID, STATUS, CREATED_AT, ENDED_AT FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID = :agent_id ORDER BY CREATED_AT", {"agent_id": agent_id}))


def assign_agent_relationship(
    actor_principal_id: str,
    agent_id: str,
    principal_id: str,
    role: str,
    reason: str,
    *,
    responsible_group_id: str = "",
) -> Dict[str, Any]:
    _require(actor_principal_id, "agents.manage")
    normalized_role = str(role or "").strip().upper()
    if normalized_role not in {"SPONSOR", "PRIMARY_OWNER", "OPERATOR", "VIEWER"}:
        raise LifecycleError("Agent relationship role is invalid")
    if not str(reason or "").strip():
        raise LifecycleError("Agent relationship reason is required")
    if (
        identity_api.effective_access(actor_principal_id, "agents.manage.all")["decision"] != "ALLOW"
        and not identity_api._agent_visible_to(actor_principal_id, agent_id)
    ):
        raise PermissionError("Agent is outside the delegated scope")
    agent = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id",
        {"agent_id": agent_id},
    ))
    if not agent or str(agent.get("principal_type") or "").upper() != "AGENT" or str(agent.get("status") or "").upper() not in {"ACTIVE", "PENDING_CONFIRMATION"}:
        raise LifecycleError("Agent is unavailable")
    target = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": principal_id},
    ))
    target_type = str((target or {}).get("principal_type") or "").upper()
    if not target or target_type not in {"HUMAN", "AGENT"} or str(target.get("status") or "").upper() != "ACTIVE":
        raise LifecycleError("relationship Principal is unavailable")
    if normalized_role in {"SPONSOR", "PRIMARY_OWNER"} and target_type != "HUMAN":
        raise LifecycleError("Sponsor and primary owner must be Human Principals")
    group_id = str(responsible_group_id or "").strip()[:128]
    if group_id:
        group = _row(connection.execute_query_one(
            "SELECT GROUP_ID FROM CX_RESPONSIBLE_GROUPS WHERE GROUP_ID = :group_id AND STATUS = 'ACTIVE'",
            {"group_id": group_id},
        ))
        if not group:
            raise LifecycleError("responsible group is unavailable")

    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one(
            "SELECT RELATIONSHIP_ID FROM CX_AGENT_RELATIONSHIPS "
            "WHERE AGENT_ID = :agent_id AND PRINCIPAL_ID = :principal_id "
            "AND RELATIONSHIP_ROLE = :role AND STATUS = 'ACTIVE' FOR UPDATE",
            {"agent_id": agent_id, "principal_id": principal_id, "role": normalized_role},
        ))
        if existing:
            return {"relationship_id": existing["relationship_id"], "idempotent": True}
        existing_owner = _row(tx.query_one(
            "SELECT PRINCIPAL_ID FROM CX_AGENT_RELATIONSHIPS "
            "WHERE AGENT_ID = :agent_id AND RELATIONSHIP_ROLE = 'PRIMARY_OWNER' "
            "AND STATUS = 'ACTIVE' FOR UPDATE",
            {"agent_id": agent_id},
        )) or {}
        decision = governed_contracts.agent_relationship_decision(
            normalized_role, agent_id=agent_id, principal_id=principal_id,
            active=True, existing_primary_owner=str(existing_owner.get("principal_id") or ""),
            actor_is_new_owner=actor_principal_id == principal_id and normalized_role == "PRIMARY_OWNER",
            reason=reason,
        )
        if not decision.allowed:
            raise LifecycleError(decision.message)
        relationship_id = _id("AR")
        inserted = tx.execute(
            "INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, "
            "RELATIONSHIP_ROLE, RESPONSIBLE_GROUP_ID, STATUS) VALUES "
            "(:relationship_id, :agent_id, :principal_id, :role, :responsible_group_id, 'ACTIVE')",
            {"relationship_id": relationship_id, "agent_id": agent_id,
             "principal_id": principal_id, "role": normalized_role,
             "responsible_group_id": group_id or None},
        )
        if inserted != 1:
            raise LifecycleError("Agent relationship was not committed")
        return {"relationship_id": relationship_id, "idempotent": False}

    result = connection.execute_transaction_callback(work)
    if not result.get("idempotent"):
        connection.execute(
            "UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :principal_id", {"principal_id": principal_id},
        )
        _audit(actor_principal_id, "AGENT_RELATIONSHIP_ASSIGN", "AGENT", agent_id, "ALLOW", reason)
    return {"relationship_id": result["relationship_id"], "agent_id": agent_id,
            "principal_id": principal_id, "role": normalized_role,
            "responsible_group_id": group_id or None, "status": "ACTIVE",
            "idempotent": bool(result.get("idempotent"))}


def classify_legacy_agents(actor_principal_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "agents.manage")
    rows = _rows(connection.execute_query("SELECT p.PRINCIPAL_ID AS AGENT_ID, p.STATUS FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_TYPE = 'AGENT' ORDER BY p.CREATED_AT " + _limit(limit), {"limit": max(1, min(int(limit), 500))}))
    results = []
    for row in rows:
        agent_id = str(row.get("agent_id") or "")
        relationships = _rows(connection.execute_query("SELECT RELATIONSHIP_ROLE, PRINCIPAL_ID FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'", {"agent_id": agent_id}))
        owner = any(str(item.get("relationship_role")).upper() == "PRIMARY_OWNER" for item in relationships)
        state = "PROVEN_OWNED" if owner else "OWNER_REVIEW_REQUIRED"
        existing = _row(connection.execute_query_one(
            "SELECT REVIEW_ID, CLASSIFICATION, STATUS FROM CX_AGENT_LEGACY_REVIEWS "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'OPEN' ORDER BY CREATED_AT DESC " + _limit(1),
            {"agent_id": agent_id, "limit": 1},
        ))
        if existing:
            results.append({"agent_id": agent_id, "classification": existing.get("classification") or state, "review_id": existing.get("review_id"), "idempotent": True})
            continue
        review_id = _id("LAR")
        connection.execute("INSERT INTO CX_AGENT_LEGACY_REVIEWS(REVIEW_ID, AGENT_ID, CLASSIFICATION, EVIDENCE_JSON, STATUS) VALUES (:review_id, :agent_id, :classification, :evidence, 'OPEN')", {"review_id": review_id, "agent_id": agent_id, "classification": state, "evidence": _json({"relationship_owner": owner, "source": "v4.3 conservative migration"})})
        results.append({"agent_id": agent_id, "classification": state, "review_id": review_id})
    return results


def claim_legacy_agent(actor_principal_id: str, agent_id: str, review_id: str, reason: str) -> Dict[str, Any]:
    _require(actor_principal_id, "agents.claim")
    if not reason.strip():
        raise LifecycleError("legacy Agent claim reason is required")
    def work(tx: Any) -> Dict[str, Any]:
        review = _row(tx.query_one("SELECT REVIEW_ID, AGENT_ID, CLASSIFICATION, STATUS FROM CX_AGENT_LEGACY_REVIEWS WHERE REVIEW_ID = :review_id AND AGENT_ID = :agent_id FOR UPDATE", {"review_id": review_id, "agent_id": agent_id}))
        if not review or str(review.get("status") or "").upper() != "OPEN" or str(review.get("classification") or "").upper() not in {"OWNER_REVIEW_REQUIRED", "UNCLAIMED"}:
            raise LifecycleError("legacy Agent review is unavailable")
        agent = _row(tx.query_one("SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT' FOR UPDATE", {"agent_id": agent_id}))
        owner = _row(tx.query_one("SELECT RELATIONSHIP_ID, PRINCIPAL_ID FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID = :agent_id AND RELATIONSHIP_ROLE = 'PRIMARY_OWNER' AND STATUS = 'ACTIVE' FOR UPDATE", {"agent_id": agent_id}))
        if not agent or str(agent.get("status") or "").upper() not in {"ACTIVE", "PENDING_CONFIRMATION"} or owner:
            raise LifecycleError("legacy Agent review is unavailable")
        relationship_id = _id("AR")
        tx.execute("INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, STATUS) VALUES (:relationship_id, :agent_id, :principal_id, 'PRIMARY_OWNER', 'ACTIVE')", {"relationship_id": relationship_id, "agent_id": agent_id, "principal_id": actor_principal_id})
        changed = tx.execute("UPDATE CX_AGENT_LEGACY_REVIEWS SET STATUS = 'CLAIMED', CLAIMED_BY = :claimed_by, CLAIM_REASON = :reason, DECIDED_AT = CURRENT_TIMESTAMP WHERE REVIEW_ID = :review_id AND STATUS = 'OPEN'", {"claimed_by": actor_principal_id, "reason": reason[:2000], "review_id": review_id})
        if changed != 1:
            raise LifecycleError("legacy Agent review changed concurrently")
        return {"relationship_id": relationship_id}
    relationship_result = connection.execute_transaction_callback(work)
    connection.execute("UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1 WHERE PRINCIPAL_ID = :principal_id", {"principal_id": actor_principal_id})
    _audit(actor_principal_id, "AGENT_LEGACY_CLAIM", "AGENT", agent_id, "ALLOW", reason)
    return {"agent_id": agent_id, "review_id": review_id, "relationship": {"relationship_id": relationship_result["relationship_id"], "agent_id": agent_id, "principal_id": actor_principal_id, "role": "PRIMARY_OWNER", "status": "ACTIVE"}, "status": "CLAIMED"}


def register_derived_object(
    actor_principal_id: str, agent_id: str, object_type: str, object_id: str,
    *, instance_id: str = "", reason: str,
) -> Dict[str, Any]:
    """Track a governed object produced by an Agent or isolated instance."""
    _require(actor_principal_id, "agents.operate")
    if not reason.strip() or not object_type.strip() or not object_id.strip():
        raise LifecycleError("derived object registration requires type, identity, and reason")
    if not identity_api._agent_visible_to(actor_principal_id, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    if instance_id:
        instance = _row(connection.execute_query_one(
            "SELECT STATUS FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID = :instance_id AND AGENT_ID = :agent_id",
            {"instance_id": instance_id, "agent_id": agent_id},
        ))
        if not instance or str(instance.get("status") or "").upper() != "ACTIVE":
            raise LifecycleError("Agent instance is unavailable")
    existing = _row(connection.execute_query_one(
        "SELECT DERIVED_OBJECT_ID, STATUS FROM CX_AGENT_DERIVED_OBJECTS WHERE AGENT_ID = :agent_id "
        "AND COALESCE(INSTANCE_ID, '') = COALESCE(:instance_id, '') AND OBJECT_TYPE = :object_type AND OBJECT_ID = :object_id AND STATUS = 'ACTIVE'",
        {"agent_id": agent_id, "instance_id": instance_id or None, "object_type": object_type[:64], "object_id": object_id[:128]},
    ))
    if existing:
        return {"derived_object_id": existing["derived_object_id"], "status": "ACTIVE", "idempotent": True}
    derived_id = _id("DOBJ")
    connection.execute(
        "INSERT INTO CX_AGENT_DERIVED_OBJECTS(DERIVED_OBJECT_ID, AGENT_ID, INSTANCE_ID, OBJECT_TYPE, OBJECT_ID, STATUS) "
        "VALUES (:derived_object_id, :agent_id, :instance_id, :object_type, :object_id, 'ACTIVE')",
        {"derived_object_id": derived_id, "agent_id": agent_id, "instance_id": instance_id or None, "object_type": object_type[:64], "object_id": object_id[:128]},
    )
    _audit(actor_principal_id, "AGENT_DERIVED_OBJECT_REGISTER", "AGENT", agent_id, "ALLOW", reason)
    return {"derived_object_id": derived_id, "agent_id": agent_id, "instance_id": instance_id or None, "object_type": object_type[:64], "object_id": object_id[:128], "status": "ACTIVE"}


def list_derived_objects(actor_principal_id: str, agent_id: str, instance_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "agents.read")
    if not identity_api._agent_visible_to(actor_principal_id, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    condition = " AND INSTANCE_ID = :instance_id" if instance_id else ""
    params: Dict[str, Any] = {"agent_id": agent_id, "limit": max(1, min(int(limit), 500))}
    if instance_id:
        params["instance_id"] = instance_id
    return _rows(connection.execute_query(
        "SELECT DERIVED_OBJECT_ID, AGENT_ID, INSTANCE_ID, OBJECT_TYPE, OBJECT_ID, STATUS, CREATED_AT, REVOKED_AT, REVOKE_REASON "
        "FROM CX_AGENT_DERIVED_OBJECTS WHERE AGENT_ID = :agent_id" + condition + " ORDER BY CREATED_AT DESC " + _limit(params["limit"]), params,
    ))


def revoke_derived_objects(agent_id: str, *, instance_id: str = "", reason: str) -> int:
    if not reason.strip():
        raise LifecycleError("derived object revocation reason is required")
    condition = " AND INSTANCE_ID = :instance_id" if instance_id else ""
    params: Dict[str, Any] = {"agent_id": agent_id, "reason": reason[:2000]}
    if instance_id:
        params["instance_id"] = instance_id
    return int(connection.execute(
        "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason "
        "WHERE AGENT_ID = :agent_id" + condition + " AND STATUS = 'ACTIVE'", params,
    ) or 0)


def quarantine_agent_instance(actor_principal_id: str, agent_id: str, instance_id: str, reason: str) -> bool:
    _require(actor_principal_id, "agents.operate")
    if not reason.strip() or not identity_api._agent_visible_to(actor_principal_id, agent_id):
        raise LifecycleError("Agent instance quarantine is not allowed")
    changed = connection.execute("UPDATE CX_AGENT_INSTANCES SET STATUS = 'QUARANTINED', REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP WHERE AGENT_ID = :agent_id AND INSTANCE_ID = :instance_id AND STATUS = 'ACTIVE'", {"agent_id": agent_id, "instance_id": instance_id, "reason": reason[:1000]})
    if changed:
        connection.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE AGENT_ID = :agent_id AND INSTANCE_ID = :instance_id AND REVOKED_AT IS NULL", {"agent_id": agent_id, "instance_id": instance_id})
        revoke_derived_objects(agent_id, instance_id=instance_id, reason=reason)
        _audit(actor_principal_id, "AGENT_INSTANCE_QUARANTINE", "AGENT_INSTANCE", instance_id, "ALLOW", reason)
    return bool(changed)


def escalate_notification(actor_principal_id: str, notification_id: str, reason: str) -> bool:
    _require(actor_principal_id, "notifications.manage")
    if not reason.strip():
        raise LifecycleError("notification escalation reason is required")
    changed = connection.execute("UPDATE CX_NOTIFICATIONS SET NOTIFICATION_LEVEL = CASE WHEN NOTIFICATION_LEVEL = 'INFO' THEN 'WARNING' WHEN NOTIFICATION_LEVEL = 'WARNING' THEN 'ACTION_REQUIRED' ELSE 'CRITICAL' END, ESCALATED_AT = CURRENT_TIMESTAMP WHERE NOTIFICATION_ID = :notification_id AND ACKNOWLEDGED_AT IS NULL", {"notification_id": notification_id})
    if changed:
        _audit(actor_principal_id, "NOTIFICATION_ESCALATE", "NOTIFICATION", notification_id, "ALLOW", reason)
    return bool(changed)


def promote_memory_candidate(actor_principal_id: str, candidate_id: str, destination_scope: str, reason: str, *, approver_authorized: bool = False) -> Dict[str, Any]:
    _require(actor_principal_id, "memory.review")
    row = _row(connection.execute_query_one("SELECT CANDIDATE_ID, CHANNEL_ID, SECURITY_DOMAIN_ID, CONTENT_JSON, CLASSIFICATION, DESTINATION_SCOPE, PROVENANCE_JSON, STATUS, PROPOSED_BY FROM CX_CHANNEL_MEMORY_CANDIDATES WHERE CANDIDATE_ID = :candidate_id", {"candidate_id": candidate_id}))
    if not row:
        raise LifecycleError("Memory Candidate is unavailable")
    channel_id = str(row.get("channel_id") or "")
    identity_api._assert_channel_member(actor_principal_id, channel_id, "memory.review")
    current_scope = str(row.get("destination_scope") or "CHANNEL_MEMORY").upper()
    current_scope = "CHANNEL_MEMORY" if current_scope == "CHANNEL" else current_scope
    target_scope = str(destination_scope or "").upper()
    decision = governed_contracts.memory_promotion_decision(
        target_scope, current_scope=current_scope, source_authorized=True,
        approver_authorized=approver_authorized or str(row.get("proposed_by")) != actor_principal_id,
        classification_allowed=True, provenance_present=bool(row.get("provenance_json")), reason=reason,
    )
    if not decision.allowed:
        raise LifecycleError(decision.message)
    content = str(row.get("content_json") or "{}").encode("utf-8")
    content_hash = hashlib.sha256(content).hexdigest()

    def _commit(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT CANDIDATE_ID, CHANNEL_ID, SECURITY_DOMAIN_ID, CONTENT_JSON, CLASSIFICATION, "
            "DESTINATION_SCOPE, PROVENANCE_JSON, STATUS, PROPOSED_BY "
            "FROM CX_CHANNEL_MEMORY_CANDIDATES WHERE CANDIDATE_ID = :candidate_id FOR UPDATE",
            {"candidate_id": candidate_id},
        ))
        if not current or str(current.get("status") or "").upper() != "PROPOSED":
            raise LifecycleError("Memory Candidate changed concurrently")
        member = tx.query_one(
            "SELECT m.PRINCIPAL_ID, c.CLASSIFICATION, c.STATUS FROM CX_CHANNEL_MEMBERS m "
            "JOIN CX_CHANNELS c ON c.CHANNEL_ID = m.CHANNEL_ID "
            "WHERE m.CHANNEL_ID = :channel_id AND m.PRINCIPAL_ID = :principal_id "
            "AND m.STATUS = 'ACTIVE' AND c.STATUS NOT IN ('DELETED','QUARANTINED') "
            "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"channel_id": current.get("channel_id"), "principal_id": actor_principal_id},
        )
        if not member:
            raise PermissionError("memory review is outside the Channel")
        current_scope_value = str(current.get("destination_scope") or "CHANNEL_MEMORY").upper()
        current_scope_value = "CHANNEL_MEMORY" if current_scope_value == "CHANNEL" else current_scope_value
        current_decision = governed_contracts.memory_promotion_decision(
            target_scope, current_scope=current_scope_value, source_authorized=True,
            approver_authorized=approver_authorized or str(current.get("proposed_by")) != actor_principal_id,
            classification_allowed=identity_api._classification_meets_minimum(
                str(current.get("classification") or "INTERNAL"), str(member.get("classification") or "INTERNAL"),
            ), provenance_present=bool(current.get("provenance_json")), reason=reason,
        )
        if not current_decision.allowed:
            raise LifecycleError(current_decision.message)
        artifact = _row(tx.query_one(
            "SELECT ARTIFACT_ID FROM GRAPH_ARTIFACTS WHERE CONTENT_HASH = :content_hash FOR UPDATE",
            {"content_hash": content_hash},
        ))
        artifact_id = str(artifact.get("artifact_id")) if artifact else _id("ART")
        if not artifact:
            tx.execute(
                "INSERT INTO GRAPH_ARTIFACTS(ARTIFACT_ID, CONTENT_HASH, MEDIA_TYPE, CONTENT_SIZE, CONTENT_BLOB, OWNER_REF, CLASSIFICATION) "
                "VALUES (:artifact_id, :content_hash, 'application/json', :content_size, :content_blob, :owner_ref, :classification)",
                {"artifact_id": artifact_id, "content_hash": content_hash, "content_size": len(content),
                 "content_blob": content, "owner_ref": f"memory-candidate:{candidate_id}",
                 "classification": str(current.get("classification") or "INTERNAL")},
            )
            try:
                from . import graph_governance
                graph_governance.record_governance_event(
                    "ARTIFACT_CREATED", f"memory-candidate:{candidate_id}",
                    "Memory candidate promoted", artifact_id=artifact_id,
                    detail={"content_hash": content_hash, "content_size": len(content)}, tx=tx,
                )
            except ImportError:
                pass
        tx.execute(
            "INSERT INTO CX_MEMORY_ARTIFACT_LINKS(LINK_ID, CANDIDATE_ID, ARTIFACT_ID, DESTINATION_SCOPE, STATUS) "
            "VALUES (:link_id, :candidate_id, :artifact_id, :destination_scope, 'ACTIVE')",
            {"link_id": _id("MAL"), "candidate_id": candidate_id,
             "artifact_id": artifact_id, "destination_scope": target_scope},
        )
        changed = tx.execute(
            "UPDATE CX_CHANNEL_MEMORY_CANDIDATES SET STATUS = 'APPROVED', DESTINATION_SCOPE = :destination_scope, "
            "REVIEWED_BY = :reviewed_by, REVIEW_REASON = :reason, REVIEWED_AT = CURRENT_TIMESTAMP "
            "WHERE CANDIDATE_ID = :candidate_id AND STATUS = 'PROPOSED'",
            {"destination_scope": target_scope, "reviewed_by": actor_principal_id,
             "reason": reason[:2000], "candidate_id": candidate_id},
        )
        if changed != 1:
            raise LifecycleError("Memory Candidate changed concurrently")
        identity_api._audit_tx(
            tx, actor_principal_id, "MEMORY_CANDIDATE_PROMOTE", "MEMORY_CANDIDATE",
            candidate_id, "ALLOW", reason,
        )
        return {"candidate_id": candidate_id, "status": "APPROVED",
                "destination_scope": target_scope, "artifact_id": artifact_id,
                "content_hash": content_hash}

    try:
        return connection.execute_transaction_callback(_commit)
    except (LifecycleError, PermissionError):
        raise
    except Exception as exc:
        raise LifecycleError("Memory Artifact storage is unavailable") from exc


def create_connector(actor_principal_id: str, bridge_id: str, mode: str, endpoint_ref: str, reason: str, *, metadata_only: bool = True, restricted_domain: bool = False, enterprise: bool = False) -> Dict[str, Any]:
    _require(actor_principal_id, "channels.bridge")
    decision = governed_contracts.connector_decision(mode, enterprise=enterprise, restricted_domain=restricted_domain, metadata_only=metadata_only, endpoint_authorized=bool(endpoint_ref), secret_ref_present=bool(endpoint_ref), reason=reason)
    if not decision.allowed:
        raise LifecycleError(decision.message)
    connector_id = _id("CON")
    domain_admin = effective_access(actor_principal_id, "domains.manage")["decision"] == "ALLOW"

    def _commit(tx: Any) -> Dict[str, Any]:
        bridge = _row(tx.query_one(
            "SELECT BRIDGE_ID, SOURCE_DOMAIN_ID, STATUS, EXPIRES_AT FROM CX_BRIDGES "
            "WHERE BRIDGE_ID = :bridge_id FOR UPDATE", {"bridge_id": bridge_id},
        ))
        if not bridge or str(bridge.get("status") or "").upper() != "APPROVED":
            raise LifecycleError("Bridge is not approved")
        expiry = identity_api._timestamp(bridge.get("expires_at"))
        if expiry is None or expiry <= _now():
            raise LifecycleError("Bridge has expired")
        member = tx.query_one(
            "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID = :domain "
            "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"domain": bridge.get("source_domain_id"), "principal_id": actor_principal_id},
        )
        if not member and not domain_admin:
            raise PermissionError("Bridge source domain access denied")
        tx.execute(
            "INSERT INTO CX_BRIDGE_CONNECTORS(CONNECTOR_ID, BRIDGE_ID, CONNECTOR_MODE, ENDPOINT_REF, METADATA_ONLY, STATUS, REASON) "
            "VALUES (:connector_id, :bridge_id, :connector_mode, :endpoint_ref, :metadata_only, 'ACTIVE', :reason)",
            {"connector_id": connector_id, "bridge_id": bridge_id, "connector_mode": mode.upper(),
             "endpoint_ref": endpoint_ref[:512],
             "metadata_only": bool(metadata_only) if _dialect() in {"postgresql", "pg"} else ("Y" if metadata_only else "N"),
             "reason": reason[:2000]},
        )
        identity_api._audit_tx(tx, actor_principal_id, "BRIDGE_CONNECTOR_CREATE", "BRIDGE", bridge_id, "ALLOW", reason)
        return {"connector_id": connector_id, "bridge_id": bridge_id, "mode": mode.upper(), "metadata_only": metadata_only, "status": "ACTIVE"}

    try:
        return connection.execute_transaction_callback(_commit)
    except (LifecycleError, PermissionError):
        raise
    except Exception as exc:
        raise LifecycleError("Bridge connector storage is unavailable") from exc


def security_overview(actor_principal_id: str, target_principal_id: str) -> Dict[str, Any]:
    _require(actor_principal_id, "users.read")
    if not identity_api._principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("user is outside the delegated scope")
    profile = identity_api.principal_summary(target_principal_id)
    session_access = identity_api.effective_access(actor_principal_id, "users.sessions.read")["decision"] == "ALLOW"
    delegation_access = identity_api.effective_access(actor_principal_id, "users.delegations.read")["decision"] == "ALLOW"
    return {
        "profile": profile,
        "identities": list_external_identities(actor_principal_id, target_principal_id),
        "mfa_required": mfa_required(target_principal_id),
        "sessions": list_sessions(actor_principal_id, target_principal_id) if session_access else [],
        "delegations": list_delegations(actor_principal_id, target_principal_id=target_principal_id) if delegation_access else [],
    }
