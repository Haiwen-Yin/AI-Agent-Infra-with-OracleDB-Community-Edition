"""v4.3.0 identity, authorization, enrollment, Channel and Barrier services.

The module deliberately uses the adapter-neutral connection facade.  It keeps
authorization decisions and ownership in the database while treating every
client-supplied identity field as data, never as an authenticated claim.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import connection, governed_contracts, cursor_pagination


REGISTRATION_MODES = {"CLOSED", "APPROVAL", "INVITE_ONLY", "DIRECTORY", "OPEN"}
USER_STATES = {"PENDING", "ACTIVE", "LOCKED", "DISABLED", "EXPIRED"}
SCOPES = {
    "ALL", "SECURITY_DOMAIN", "ORG_SUBTREE", "DIRECT_REPORTS",
    "RESPONSIBLE_GROUP", "OWNED", "ASSIGNED", "NONE",
}
ROLE_FALLBACKS = {
    "END_USER": {
        "permissions": {
            "profile.read", "profile.update", "agents.enroll", "agents.read",
            "channels.read", "channels.write", "tasks.read", "workspaces.read",
            "knowledge.read", "memory.read", "skills.read", "specs.read",
            "branches.read", "collab.read", "loops.read", "graphs.read",
            "notifications.read", "users.read", "users.sessions.read",
            "sessions.revoke", "users.identity.link", "users.security.manage",
            "organizations.read",
        },
        "scopes": {"OWNED", "ASSIGNED"},
    },
    "SYSTEM_ADMIN": {"permissions": {"*"}, "scopes": {"ALL"}},
    "SECURITY_ADMIN": {
        "permissions": {
            "security.*", "sessions.revoke", "domains.manage", "profile.update",
            "users.identity.link", "users.security.manage", "users.sessions.read",
            "users.delegations.read", "users.delegations.manage", "agents.claim",
            "channels.bridge", "channels.lifecycle", "channels.delete",
            "channels.manage_members", "channels.quarantine", "memory.review",
            "agents.transfer", "agents.offboard", "barriers.recover",
            "notifications.manage", "barriers.create", "channels.actions.decide",
        },
        "scopes": {"SECURITY_DOMAIN"},
    },
    # Delegated managers can operate within their organization scope, but
    # cannot approve registrations or assign roles without an explicit,
    # separately delegated administration grant.
    "AGENT_MANAGER": {
        "permissions": {
            "agents.read", "agents.enroll", "agents.manage", "agents.operate",
            "agents.transfer", "agents.offboard", "channels.read", "channels.create",
            "channels.manage_members", "channels.lifecycle", "users.read",
            "notifications.manage", "profile.update",
            "organizations.read",
        },
        "scopes": {"ORG_SUBTREE"},
    },
    "ORG_MANAGER": {
        "permissions": {
            "organizations.read", "organizations.manage",
            "organizations.people.read", "organizations.agents.read",
            "organizations.anomalies.read",
            "organizations.changes.create", "organizations.changes.write",
            "organizations.changes.submit", "organizations.history.read",
            "organizations.members.manage", "organizations.reporting.manage",
            "organizations.sync.manage",
            "agents.read", "users.read", "profile.update",
        },
        "scopes": {"ORG_SUBTREE"},
    },
    "AUDITOR": {"permissions": {"audit.read", "audit.export", "users.read", "profile.update"}, "scopes": {"SECURITY_DOMAIN"}},
    "APPROVER": {"permissions": {"approvals.read", "approvals.decide", "channels.actions.decide", "barriers.release", "barriers.recover", "memory.review", "profile.update"}, "scopes": {"ASSIGNED"}},
    "OPERATOR": {"permissions": {"agents.read", "agents.operate", "channels.write", "barriers.arrive", "profile.update"}, "scopes": {"ASSIGNED"}},
    "DEVELOPER": {"permissions": {"skills.read", "tools.read", "graphs.read", "barriers.create", "profile.update"}, "scopes": {"OWNED"}},
    "USER_ADMIN": {
        "permissions": {"users.read", "users.read.all", "users.approve", "users.roles.manage", "users.permissions.manage", "users.identity.link", "users.security.manage", "users.sessions.read", "users.delegations.read", "users.delegations.manage", "organizations.read", "organizations.members.manage", "organizations.reporting.manage"},
        "scopes": {"ORG_SUBTREE"},
    },
    "ROLE_ADMIN": {
        "permissions": {"users.read", "users.roles.manage", "users.permissions.manage", "users.delegations.read", "users.delegations.manage"},
        "scopes": {"ORG_SUBTREE"},
    },
    "AGENT": {
        "permissions": {"channels.read", "channels.write", "barriers.read", "barriers.arrive", "actions.propose"},
        "scopes": {"ASSIGNED"},
    },
}

# Oracle-compatible databases treat the empty string as NULL.  Keep a real
# provider value for local identities while accepting rows created by the
# earlier empty-string implementation during migration.
LOCAL_PROVIDER = "LOCAL"
_LOCAL_PROVIDER_PREDICATE = "(PROVIDER = 'LOCAL' OR PROVIDER IS NULL OR PROVIDER = '')"

CLASSIFICATION_LEVELS = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}

# The web contract deliberately has a five-minute upper bound.  Deployment
# configuration may shorten the lease, but it must never turn a database
# session into a long-lived bearer credential.
# Individual session policies remain conservative by default (five minutes
# idle).  The global ceiling permits a separately governed absolute lifetime.
SESSION_MAX_SECONDS = 86400


class IdentityError(ValueError):
    """A safe, non-enumerating identity boundary error."""


def _dialect() -> str:
    return str(getattr(connection, "DATABASE_DIALECT", "") or "").lower()


def _limit_clause(bind_name: str = "limit") -> str:
    """Return a row limiter supported by the selected database adapter."""
    if _dialect() in {"postgresql", "pg"}:
        return "LIMIT :" + bind_name
    return "FETCH FIRST :" + bind_name + " ROWS ONLY"


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


def _now() -> datetime:
    """Return the deployment-local wall clock for naive database TIMESTAMPs.

    Identity tables intentionally use cross-adapter ``TIMESTAMP`` columns.
    Binding a naive UTC value while Oracle/YashanDB compare against a local
    ``CURRENT_TIMESTAMP`` makes a newly issued TTL appear expired by the
    timezone offset.  All identity expiry values therefore use the same local
    wall-clock basis as the database session.
    """
    return datetime.now().astimezone().replace(tzinfo=None)


def _timestamp(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IdentityError("timestamp is invalid") from exc
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _merge_metadata(raw: Any, updates: Dict[str, Any]) -> str:
    """Preserve existing portable metadata while recording a new event."""
    value: Dict[str, Any] = {}
    if isinstance(raw, dict):
        value = dict(raw)
    elif raw:
        try:
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                value = parsed
        except (TypeError, ValueError):
            value = {"legacy_metadata": str(raw)[:4000]}
    value.update(updates)
    return _json(value)


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {str(key).lower(): value for key, value in dict(row).items()}


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(item) or {} for item in rows]


def _safe_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    try:
        return _rows(connection.execute_query(sql, params or {}))
    except Exception:
        # This is used only for optional compatibility probes.  Mutating
        # operations never suppress a missing governance schema.
        return []


def _required_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Run a governance query without converting schema failures to empty data."""
    try:
        return _rows(connection.execute_query(sql, params or {}))
    except Exception as exc:
        raise IdentityError("identity governance data is unavailable") from exc


def principal_summary(principal_id: str) -> Dict[str, Any]:
    """Return non-secret identity metadata for the authenticated console."""
    row = _row(connection.execute_query_one(
        "SELECT p.PRINCIPAL_ID, p.PRINCIPAL_TYPE, p.DISPLAY_NAME, p.STATUS, p.PERMISSION_VERSION, "
        "i.USERNAME, i.EMAIL, i.IDENTITY_TYPE "
        "FROM CX_PRINCIPALS p LEFT JOIN CX_HUMAN_IDENTITIES i "
        "ON i.PRINCIPAL_ID = p.PRINCIPAL_ID AND i.STATUS = 'ACTIVE' "
        "WHERE p.PRINCIPAL_ID = :principal_id",
        {"principal_id": principal_id},
    )) or {}
    roles = _required_query(
        "SELECT ROLE_CODE FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id "
        "AND STATUS = 'ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP) "
        "ORDER BY ROLE_CODE",
        {"principal_id": principal_id},
    )
    return {
        "principal_id": row.get("principal_id") or principal_id,
        "principal_type": row.get("principal_type") or "",
        "status": row.get("status") or "",
        "permission_version": int(row.get("permission_version") or 0),
        "username": row.get("username") or "",
        "email": row.get("email") or "",
        "roles": [str(item.get("role_code") or "") for item in roles],
    }


def _secret_digest(value: str, purpose: str) -> str:
    pepper = os.environ.get("CX_IDENTITY_PEPPER")
    if pepper:
        key = pepper.encode("utf-8")
    else:
        from .connection_crypto import get_master_key
        key = get_master_key()
    return hmac.new(key, f"{purpose}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _argon2_hasher():
    try:
        from argon2 import PasswordHasher
        from argon2.low_level import Type
    except ImportError as exc:  # pragma: no cover - dependency is package-gated
        raise RuntimeError("argon2-cffi is required for local password operations") from exc
    return PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


def hash_password_argon2id(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise IdentityError("Password does not meet the minimum policy")
    return _hash_argon2id(password)


def _hash_argon2id(password: str) -> str:
    """Hash a verified credential during a controlled legacy migration.

    New password entry points call ``hash_password_argon2id`` and retain the
    twelve-character policy.  A legacy credential has already passed its
    existing verifier, so migration must not turn a valid short historical
    password into a service-unavailable login failure.
    """
    if not isinstance(password, str) or not password:
        raise IdentityError("Password is invalid")
    return _argon2_hasher().hash(password)


def verify_password_hash(password: str, stored_hash: str, legacy_salt: str = "") -> Tuple[bool, Optional[str]]:
    """Return ``(valid, upgraded_hash)`` for Argon2id or legacy SHA-256."""
    stored = str(stored_hash or "")
    if stored.startswith("$argon2id$"):
        try:
            hasher = _argon2_hasher()
            valid = hasher.verify(stored, password)
            upgraded = hasher.hash(password) if valid and hasher.check_needs_rehash(stored) else None
            return bool(valid), upgraded
        except Exception:
            return False, None
    if stored.startswith("SHA256:"):
        expected = stored[7:]
        material = f"{password}{legacy_salt}".encode("utf-8") if legacy_salt else password.encode("utf-8")
        actual = hashlib.sha256(material).hexdigest()
        if hmac.compare_digest(actual.lower(), expected.lower()):
            return True, _hash_argon2id(password)
    return False, None


def registration_mode() -> str:
    value = str(os.environ.get("CX_REGISTRATION_MODE", "APPROVAL") or "APPROVAL").upper()
    return value if value in REGISTRATION_MODES else "APPROVAL"


def _normalize_username(username: str) -> str:
    return str(username or "").strip().casefold()


def _classification(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in CLASSIFICATION_LEVELS:
        raise IdentityError("Security classification is invalid")
    return normalized


def _classification_meets_minimum(value: Any, minimum: Any) -> bool:
    return CLASSIFICATION_LEVELS[_classification(value)] >= CLASSIFICATION_LEVELS[_classification(minimum)]


def _valid_invite_code(invite_code: str) -> bool:
    """Validate an invite without keeping or comparing the raw code in SQL."""
    expected = str(os.environ.get("CX_INVITE_CODE_DIGEST", "") or "").strip().lower()
    if not expected or not invite_code:
        return False
    actual = _secret_digest(invite_code, "human-invite")
    return hmac.compare_digest(actual, expected)


def _local_identity(username: str) -> Optional[Dict[str, Any]]:
    username = _normalize_username(username)
    return _row(connection.execute_query_one(
        "SELECT IDENTITY_ID, PRINCIPAL_ID, USERNAME, PASSWORD_HASH, STATUS "
        "FROM CX_HUMAN_IDENTITIES WHERE IDENTITY_TYPE = 'LOCAL' AND " + _LOCAL_PROVIDER_PREDICATE + " "
        "AND SUBJECT_KEY = :username",
        {"username": username},
    ))


def _create_system_user(username: str, password_hash: str, role: str = "USER") -> str:
    """Create a legacy-compatible SYSTEM_USERS row without assuming PG IDs."""
    if _dialect() == "postgresql":
        connection.execute(
            "INSERT INTO SYSTEM_USERS (USERNAME, PASSWORD_HASH, ROLE, STATUS, AUTH_SOURCE, CREATED_AT, UPDATED_AT) "
            "VALUES (:username, :password_hash, :role, 'ACTIVE', 'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            {"username": username, "password_hash": password_hash, "role": role},
        )
        row = connection.execute_query_one("SELECT USER_ID FROM SYSTEM_USERS WHERE USERNAME = :username", {"username": username})
        if not row:
            raise IdentityError("Unable to create user")
        return str(_row(row)["user_id"])
    user_id = _id("USR")
    connection.execute(
        "INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, STATUS, AUTH_SOURCE, CREATED_AT, UPDATED_AT) "
        "VALUES (:user_id, :username, :password_hash, :role, 'ACTIVE', 'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"user_id": user_id, "username": username, "password_hash": password_hash, "role": role},
    )
    return user_id


def ensure_principal_defaults(principal_id: str) -> None:
    """Attach a principal to the bootstrap security domain exactly once.

    The migration creates the domain, but existing installations may already
    contain users when the v4.3 migration is applied.  Keeping this repair in
    the service makes those users usable without granting them cross-domain
    access or requiring a manual SQL update.
    """
    domain = _row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = 'DEFAULT' AND STATUS = 'ACTIVE'"
    ))
    if not domain:
        try:
            connection.execute(
                "INSERT INTO CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID, DOMAIN_NAME, CLASSIFICATION, PURPOSE, STATUS) "
                "VALUES ('DEFAULT', 'Default Security Domain', 'INTERNAL', 'Bootstrap domain; replace with an organization-specific domain before production', 'ACTIVE')"
            )
        except Exception:
            return
    member = _row(connection.execute_query_one(
        "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS "
        "WHERE SECURITY_DOMAIN_ID = 'DEFAULT' AND PRINCIPAL_ID = :principal_id",
        {"principal_id": principal_id},
    ))
    if not member:
        try:
            connection.execute(
                "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID, SECURITY_DOMAIN_ID, PRINCIPAL_ID, MEMBERSHIP_TIER) "
                "VALUES (:membership_id, 'DEFAULT', :principal_id, 'MEMBER')",
                {"membership_id": _id("DM"), "principal_id": principal_id},
            )
        except Exception:
            # A concurrent login can win the unique constraint.  It is safe to
            # continue because the membership is then already present.
            pass


def _ensure_principal(
    user_id: str,
    username: str,
    password_hash: str,
    status: str = "ACTIVE",
    role_code: str = "END_USER",
    email: str = "",
    display_name: str = "",
    app_access: bool = True,
) -> str:
    display_name = str(display_name or username).strip()[:256]
    existing = _local_identity(username)
    if existing:
        principal_id = str(existing["principal_id"])
        connection.execute(
            "UPDATE CX_PRINCIPALS SET DISPLAY_NAME = COALESCE(:display_name, DISPLAY_NAME) "
            "WHERE PRINCIPAL_ID = :principal_id",
            {"display_name": display_name or None, "principal_id": principal_id},
        )
        connection.execute(
            "UPDATE CX_HUMAN_IDENTITIES SET PROVIDER = :provider, PASSWORD_HASH = :password_hash, EMAIL = COALESCE(:email, EMAIL), STATUS = :status, "
            "UPDATED_AT = CURRENT_TIMESTAMP WHERE IDENTITY_ID = :identity_id",
            {"provider": LOCAL_PROVIDER, "password_hash": password_hash, "email": email or None, "status": status, "identity_id": existing["identity_id"]},
        )
        if str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"}:
            connection.execute(
                "UPDATE CX_PRINCIPALS SET PORTAL_ACCESS = 'Y', APP_ACCESS = 'Y' "
                "WHERE PRINCIPAL_ID = :principal_id",
                {"principal_id": principal_id},
            )
            assigned = _row(connection.execute_query_one(
                "SELECT USER_ROLE_ID FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id "
                "AND ROLE_CODE = 'SYSTEM_ADMIN' AND STATUS = 'ACTIVE'",
                {"principal_id": principal_id},
            ))
            if not assigned:
                connection.execute(
                    "INSERT INTO CX_USER_ROLES(USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE) "
                    "VALUES (:id, :principal_id, 'SYSTEM_ADMIN', 'BOOTSTRAP_ADMIN')",
                    {"id": _id("UR"), "principal_id": principal_id},
                )
        ensure_principal_defaults(principal_id)
        return principal_id
    principal_id = _id("HP")
    connection.execute(
        "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID, PRINCIPAL_TYPE, DISPLAY_NAME, STATUS, PORTAL_ACCESS, APP_ACCESS) "
        "VALUES (:principal_id, 'HUMAN', :display_name, :status, 'Y', :app_access)",
        {"principal_id": principal_id, "display_name": display_name, "status": status,
         "app_access": "Y" if app_access or str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"} else "N"},
    )
    connection.execute(
        "INSERT INTO CX_HUMAN_IDENTITIES(IDENTITY_ID, PRINCIPAL_ID, IDENTITY_TYPE, PROVIDER, SUBJECT_KEY, USERNAME, EMAIL, PASSWORD_HASH, PASSWORD_VERSION, STATUS) "
        "VALUES (:identity_id, :principal_id, 'LOCAL', :provider, :subject_key, :username, :email, :password_hash, 'argon2id-v1', :status)",
        {"identity_id": _id("HI"), "principal_id": principal_id, "provider": LOCAL_PROVIDER, "subject_key": username,
         "username": username, "email": email or None, "password_hash": password_hash, "status": status},
    )
    role = "SYSTEM_ADMIN" if str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"} else "END_USER"
    connection.execute(
        "INSERT INTO CX_USER_ROLES(USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE) "
        "VALUES (:id, :principal_id, :role_code, :source)",
        {"id": _id("UR"), "principal_id": principal_id, "role_code": role,
         "source": "BOOTSTRAP_ADMIN" if role == "SYSTEM_ADMIN" and username == "admin" else "DEFAULT"},
    )
    ensure_principal_defaults(principal_id)
    return principal_id


def bootstrap_existing_admins() -> int:
    """Link pre-v4.3 ADMIN rows to SYSTEM_ADMIN Principals.

    This does not create a password or a privileged account.  It only adopts
    an already active local administrator from the legacy schema, so a fresh
    installation still has to use the existing password wizard/secret.
    """
    adopted = 0
    try:
        rows = connection.execute_query(
            "SELECT USER_ID, USERNAME, PASSWORD_HASH FROM SYSTEM_USERS "
            "WHERE STATUS = 'ACTIVE' AND ROLE = 'ADMIN' AND AUTH_SOURCE = 'LOCAL'"
        )
    except Exception:
        return 0
    for item in _rows(rows):
        try:
            _ensure_principal(
                str(item["user_id"]), str(item["username"]),
                str(item.get("password_hash") or ""), "ACTIVE", "SYSTEM_ADMIN",
            )
            adopted += 1
        except Exception:
            continue
    return adopted


def _default_registration_organization() -> str:
    """Resolve the sole server-selected organization used only by OPEN mode."""
    configured = str(os.environ.get("CX_DEFAULT_ORGANIZATION_ID", "")).strip()
    if configured:
        row = _row(connection.execute_query_one(
            "SELECT ORGANIZATION_ID FROM CX_ORGANIZATIONS "
            "WHERE ORGANIZATION_ID = :organization_id AND STATUS = 'ACTIVE'",
            {"organization_id": configured},
        ))
        if not row:
            raise IdentityError("Default registration organization is unavailable")
        return str(row["organization_id"])
    rows = _rows(connection.execute_query(
        "SELECT ORGANIZATION_ID FROM CX_ORGANIZATIONS "
        "WHERE PARENT_ID IS NULL AND STATUS = 'ACTIVE' ORDER BY ORGANIZATION_ID"
    ))
    if len(rows) != 1:
        raise IdentityError("OPEN registration requires one default root organization")
    return str(rows[0]["organization_id"])


def register_human(
    username: str, password: str, email: str = "", invite_code: str = "", *,
    display_name: str = "",
) -> Dict[str, Any]:
    username = _normalize_username(username)
    display_name = str(display_name or username).strip()
    if not username or len(username) > 128 or not password or not display_name or len(display_name) > 256:
        raise IdentityError("Registration data is invalid")
    mode = registration_mode()
    if mode == "CLOSED":
        raise IdentityError("Registration is unavailable")
    if mode == "INVITE_ONLY" and not _valid_invite_code(invite_code):
        raise IdentityError("Invitation is required")
    if mode == "DIRECTORY":
        raise IdentityError("Directory registration must be completed by the configured provider")
    if _local_identity(username) or _row(connection.execute_query_one(
        "SELECT REQUEST_ID FROM CX_REGISTRATION_REQUESTS "
        "WHERE lower(USERNAME) = :username AND STATUS = 'PENDING'",
        {"username": username},
    )):
        raise IdentityError("Registration could not be completed")
    password_hash = hash_password_argon2id(password)
    request_id = _id("REG")
    if mode == "OPEN":
        organization_id = _default_registration_organization()
        def activate(tx: Any) -> tuple[str, str]:
            user_id = _create_system_user_tx(tx, username, password_hash)
            principal_id = _ensure_principal_tx(
                tx, user_id, username, password_hash, "ACTIVE", "USER", email,
                display_name, app_access=False,
            )
            tx.execute(
                "INSERT INTO CX_ORGANIZATION_MEMBERS(MEMBERSHIP_ID, ORGANIZATION_ID, PRINCIPAL_ID, "
                "MEMBERSHIP_KIND, MEMBERSHIP_ROLE, VALID_FROM, SOURCE_TYPE, STATUS, ROW_VERSION, UPDATED_BY) "
                "VALUES (:membership_id, :organization_id, :principal_id, 'PRIMARY', 'MEMBER', "
                "CURRENT_TIMESTAMP, 'SYSTEM', 'ACTIVE', 1, :updated_by)",
                {"membership_id": _id("OM"), "organization_id": organization_id,
                 "principal_id": principal_id, "updated_by": principal_id},
            )
            return user_id, principal_id
        user_id, principal_id = connection.execute_transaction_callback(activate)
        _audit(principal_id, "HUMAN_REGISTER", "HUMAN", principal_id, "ALLOW", "open registration")
        return {"request_id": request_id, "user_id": user_id, "principal_id": principal_id,
                "organization_id": organization_id, "username": username,
                "status": "ACTIVE", "role": "USER"}
    connection.execute(
        "INSERT INTO CX_REGISTRATION_REQUESTS(REQUEST_ID, USERNAME, DISPLAY_NAME, EMAIL, PASSWORD_HASH, AUTH_SOURCE, REGISTRATION_MODE, STATUS) "
        "VALUES (:request_id, :username, :display_name, :email, :password_hash, 'LOCAL', :registration_mode, 'PENDING')",
        {"request_id": request_id, "username": username, "display_name": display_name,
         "email": email or None, "password_hash": password_hash, "registration_mode": mode},
    )
    _audit(None, "HUMAN_REGISTER", "HUMAN", request_id, "PENDING", "approval registration")
    return {"request_id": request_id, "username": username, "status": "PENDING", "role": "USER"}


def _create_system_user_tx(tx: Any, username: str, password_hash: str, role: str = "USER") -> str:
    """Create the compatibility user row inside the approval transaction."""
    if _dialect() == "postgresql":
        tx.execute(
            "INSERT INTO SYSTEM_USERS (USERNAME, PASSWORD_HASH, ROLE, STATUS, AUTH_SOURCE, CREATED_AT, UPDATED_AT) "
            "VALUES (:username, :password_hash, :role, 'ACTIVE', 'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            {"username": username, "password_hash": password_hash, "role": role},
        )
        row = tx.query_one(
            "SELECT USER_ID FROM SYSTEM_USERS WHERE USERNAME = :username",
            {"username": username},
        )
        if not row:
            raise IdentityError("Unable to create user")
        return str(_row(row)["user_id"])
    user_id = _id("USR")
    tx.execute(
        "INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, STATUS, AUTH_SOURCE, CREATED_AT, UPDATED_AT) "
        "VALUES (:user_id, :username, :password_hash, :role, 'ACTIVE', 'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"user_id": user_id, "username": username, "password_hash": password_hash, "role": role},
    )
    return user_id


def _ensure_principal_tx(
    tx: Any,
    user_id: str,
    username: str,
    password_hash: str,
    status: str = "ACTIVE",
    role_code: str = "END_USER",
    email: str = "",
    display_name: str = "",
    app_access: bool = True,
) -> str:
    """Create the Principal and default-domain membership on one DB session."""
    display_name = str(display_name or username).strip()[:256]
    existing = _row(tx.query_one(
        "SELECT IDENTITY_ID, PRINCIPAL_ID FROM CX_HUMAN_IDENTITIES "
        "WHERE IDENTITY_TYPE = 'LOCAL' AND " + _LOCAL_PROVIDER_PREDICATE + " AND SUBJECT_KEY = :username",
        {"username": _normalize_username(username)},
    ))
    if existing:
        principal_id = str(existing["principal_id"])
        tx.execute(
            "UPDATE CX_PRINCIPALS SET DISPLAY_NAME = COALESCE(:display_name, DISPLAY_NAME) "
            "WHERE PRINCIPAL_ID = :principal_id",
            {"display_name": display_name or None, "principal_id": principal_id},
        )
        tx.execute(
            "UPDATE CX_HUMAN_IDENTITIES SET PROVIDER = :provider, PASSWORD_HASH = :password_hash, "
            "EMAIL = COALESCE(:email, EMAIL), STATUS = :status, "
            "PASSWORD_VERSION = 'argon2id-v1', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE IDENTITY_ID = :identity_id",
            {"provider": LOCAL_PROVIDER, "password_hash": password_hash, "email": email or None, "status": status,
             "identity_id": existing["identity_id"]},
        )
        if str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"}:
            tx.execute(
                "UPDATE CX_PRINCIPALS SET PORTAL_ACCESS = 'Y', APP_ACCESS = 'Y' "
                "WHERE PRINCIPAL_ID = :principal_id",
                {"principal_id": principal_id},
            )
            assigned = _row(tx.query_one(
                "SELECT USER_ROLE_ID FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id "
                "AND ROLE_CODE = 'SYSTEM_ADMIN' AND STATUS = 'ACTIVE'",
                {"principal_id": principal_id},
            ))
            if not assigned:
                tx.execute(
                    "INSERT INTO CX_USER_ROLES(USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE) "
                    "VALUES (:id, :principal_id, 'SYSTEM_ADMIN', 'BOOTSTRAP_ADMIN')",
                    {"id": _id("UR"), "principal_id": principal_id},
                )
        return principal_id

    principal_id = _id("HP")
    tx.execute(
        "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID, PRINCIPAL_TYPE, DISPLAY_NAME, STATUS, PORTAL_ACCESS, APP_ACCESS) "
        "VALUES (:principal_id, 'HUMAN', :display_name, :status, 'Y', :app_access)",
        {"principal_id": principal_id, "display_name": display_name, "status": status,
         "app_access": "Y" if app_access or str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"} else "N"},
    )
    tx.execute(
        "INSERT INTO CX_HUMAN_IDENTITIES(IDENTITY_ID, PRINCIPAL_ID, IDENTITY_TYPE, PROVIDER, "
        "SUBJECT_KEY, USERNAME, EMAIL, PASSWORD_HASH, PASSWORD_VERSION, STATUS) "
        "VALUES (:identity_id, :principal_id, 'LOCAL', :provider, :subject_key, :username, :email, "
        ":password_hash, 'argon2id-v1', :status)",
        {"identity_id": _id("HI"), "principal_id": principal_id,
         "provider": LOCAL_PROVIDER,
         "subject_key": _normalize_username(username), "username": _normalize_username(username),
         "email": email or None, "password_hash": password_hash, "status": status},
    )
    role = "SYSTEM_ADMIN" if str(role_code or "").upper() in {"ADMIN", "ADMINISTRATOR", "SYSTEM_ADMIN"} else "END_USER"
    tx.execute(
        "INSERT INTO CX_USER_ROLES(USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE) "
        "VALUES (:id, :principal_id, :role_code, :source)",
        {"id": _id("UR"), "principal_id": principal_id, "role_code": role,
         "source": "BOOTSTRAP_ADMIN" if role == "SYSTEM_ADMIN" and username == "admin" else "DEFAULT"},
    )
    domain = _row(tx.query_one(
        "SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = 'DEFAULT' AND STATUS = 'ACTIVE'"
    ))
    if not domain:
        tx.execute(
            "INSERT INTO CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID, DOMAIN_NAME, CLASSIFICATION, PURPOSE, STATUS) "
            "VALUES ('DEFAULT', 'Default Security Domain', 'INTERNAL', "
            "'Bootstrap domain; replace with an organization-specific domain before production', 'ACTIVE')"
        )
    tx.execute(
        "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID, SECURITY_DOMAIN_ID, PRINCIPAL_ID, MEMBERSHIP_TIER) "
        "VALUES (:membership_id, 'DEFAULT', :principal_id, 'MEMBER')",
        {"membership_id": _id("DM"), "principal_id": principal_id},
    )
    return principal_id


def approve_registration(
    request_id: str, actor_principal_id: str, reason: str, organization_id: str,
) -> Dict[str, Any]:
    _require(actor_principal_id, "users.approve")
    _require(actor_principal_id, "organizations.members.manage")
    if not reason.strip():
        raise IdentityError("Approval reason is required")
    organization_id = str(organization_id or "").strip()
    if not organization_id:
        raise IdentityError("Primary organization is required")
    organization_access = effective_access(actor_principal_id, "organizations.members.manage")
    organization_scopes = {str(item).upper() for item in organization_access.get("scopes", [])}
    def work(tx: Any) -> Dict[str, Any]:
        scope_clause = ""
        params = {"organization_id": organization_id, "actor_principal_id": actor_principal_id}
        if "ALL" not in organization_scopes:
            scope_clause = (
                " AND EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS actor_org "
                "JOIN CX_ORGANIZATION_CLOSURE path ON path.ANCESTOR_ID = actor_org.ORGANIZATION_ID "
                "WHERE actor_org.PRINCIPAL_ID = :actor_principal_id "
                "AND actor_org.MEMBERSHIP_KIND = 'PRIMARY' AND actor_org.STATUS = 'ACTIVE' "
                "AND path.DESCENDANT_ID = CX_ORGANIZATIONS.ORGANIZATION_ID)"
            )
        organization = _row(tx.query_one(
            "SELECT ORGANIZATION_ID FROM CX_ORGANIZATIONS "
            "WHERE ORGANIZATION_ID = :organization_id AND STATUS = 'ACTIVE'" + scope_clause + " FOR UPDATE",
            params,
        ))
        if not organization:
            raise IdentityError("Primary organization is unavailable")
        row = _row(tx.query_one(
            "SELECT REQUEST_ID, USERNAME, DISPLAY_NAME, EMAIL, PASSWORD_HASH, STATUS "
            "FROM CX_REGISTRATION_REQUESTS WHERE REQUEST_ID = :request_id FOR UPDATE",
            {"request_id": request_id},
        ))
        if not row or str(row.get("status") or "").upper() != "PENDING":
            raise IdentityError("Registration request is unavailable")
        user_id = _create_system_user_tx(tx, row["username"], row["password_hash"])
        principal_id = _ensure_principal_tx(
            tx, user_id, row["username"], row["password_hash"], "ACTIVE", "USER",
            row.get("email") or "", row.get("display_name") or row["username"],
            app_access=False,
        )
        tx.execute(
            "INSERT INTO CX_ORGANIZATION_MEMBERS(MEMBERSHIP_ID, ORGANIZATION_ID, PRINCIPAL_ID, "
            "MEMBERSHIP_KIND, MEMBERSHIP_ROLE, VALID_FROM, SOURCE_TYPE, STATUS, ROW_VERSION, UPDATED_BY) "
            "VALUES (:membership_id, :organization_id, :principal_id, 'PRIMARY', 'MEMBER', "
            "CURRENT_TIMESTAMP, 'MANUAL', 'ACTIVE', 1, :updated_by)",
            {"membership_id": _id("OM"), "organization_id": organization_id,
             "principal_id": principal_id, "updated_by": actor_principal_id},
        )
        changed = tx.execute(
            "UPDATE CX_REGISTRATION_REQUESTS SET STATUS = 'APPROVED', DECISION_BY = :actor, "
            "DECISION_REASON = :reason, DECIDED_AT = CURRENT_TIMESTAMP "
            "WHERE REQUEST_ID = :request_id AND STATUS = 'PENDING'",
            {"actor": actor_principal_id, "reason": reason[:2000], "request_id": request_id},
        )
        if changed != 1:
            raise IdentityError("Registration request is unavailable")
        return {"request_id": request_id, "user_id": user_id, "principal_id": principal_id,
                "organization_id": organization_id, "username": row["username"],
                "status": "ACTIVE", "role": "USER"}

    result = connection.execute_transaction_callback(work)
    _audit(actor_principal_id, "HUMAN_REGISTER_APPROVE", "REGISTRATION", request_id, "ALLOW", reason)
    return result


def reject_registration(request_id: str, actor_principal_id: str, reason: str) -> Dict[str, Any]:
    """Reject a pending registration without creating a compatibility user."""
    _require(actor_principal_id, "users.approve")
    if not reason.strip():
        raise IdentityError("Registration rejection reason is required")
    changed = connection.execute(
        "UPDATE CX_REGISTRATION_REQUESTS SET STATUS = 'REJECTED', DECISION_BY = :actor, "
        "DECISION_REASON = :reason, DECIDED_AT = CURRENT_TIMESTAMP "
        "WHERE REQUEST_ID = :request_id AND STATUS = 'PENDING'",
        {"actor": actor_principal_id, "reason": reason[:2000], "request_id": request_id},
    )
    if changed != 1:
        raise IdentityError("Registration request is unavailable")
    _audit(actor_principal_id, "HUMAN_REGISTER_REJECT", "REGISTRATION", request_id, "ALLOW", reason)
    return {"request_id": request_id, "status": "REJECTED", "decision_by": actor_principal_id}


def _active_scopes(principal_id: str) -> set[str]:
    access = effective_access(principal_id, "profile.read")
    return {str(value).upper() for value in access.get("scopes", []) if str(value).upper() in SCOPES}


def _organization_scope_clause(target_principal_sql: str, principal_id_param: str = ":principal_id") -> str:
    """Build the portable v4.3.1 primary-membership organization scope."""
    return (
        "EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS actor_org "
        "JOIN CX_ORGANIZATION_CLOSURE org_path "
        "ON org_path.ANCESTOR_ID = actor_org.ORGANIZATION_ID "
        "JOIN CX_ORGANIZATION_MEMBERS target_org "
        "ON target_org.ORGANIZATION_ID = org_path.DESCENDANT_ID "
        "AND target_org.PRINCIPAL_ID = " + target_principal_sql + " "
        "WHERE actor_org.PRINCIPAL_ID = " + principal_id_param + " "
        "AND actor_org.STATUS = 'ACTIVE' AND target_org.STATUS = 'ACTIVE' "
        "AND actor_org.MEMBERSHIP_KIND = 'PRIMARY' "
        "AND target_org.MEMBERSHIP_KIND = 'PRIMARY' "
        "AND (actor_org.VALID_UNTIL IS NULL OR actor_org.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND (target_org.VALID_UNTIL IS NULL OR target_org.VALID_UNTIL > CURRENT_TIMESTAMP) "
        ")"
    )


def _ensure_scope_tables(scopes: set[str]) -> None:
    """Fail closed when a configured data scope has not been migrated."""
    required: set[str] = set()
    if "DIRECT_REPORTS" in scopes or "ORG_SUBTREE" in scopes:
        required.update({"CX_ORGANIZATION_MEMBERS"})
    if "ORG_SUBTREE" in scopes:
        required.update({"CX_ORGANIZATIONS", "CX_ORGANIZATION_CLOSURE"})
    if "DIRECT_REPORTS" in scopes:
        required.add("CX_REPORTING_RELATIONSHIPS")
    if "RESPONSIBLE_GROUP" in scopes:
        required.update({"CX_RESPONSIBLE_GROUPS", "CX_RESPONSIBLE_GROUP_MEMBERS"})
    if "SECURITY_DOMAIN" in scopes:
        required.update({"CX_SECURITY_DOMAINS", "CX_DOMAIN_MEMBERS"})
    for table in sorted(required):
        try:
            connection.execute_query_one(f"SELECT 1 FROM {table} WHERE 1 = 0", {})
        except Exception as exc:
            raise IdentityError("configured authorization scope is not migrated") from exc


def _principal_visibility_clause(principal_id: str, target_principal_sql: str = "p.PRINCIPAL_ID") -> str:
    scopes = _active_scopes(principal_id)
    _ensure_scope_tables(scopes)
    if "ALL" in scopes:
        return "1 = 1"
    clauses: list[str] = [f"{target_principal_sql} = :principal_id"] if scopes & {"OWNED", "ASSIGNED"} else []
    if "DIRECT_REPORTS" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_REPORTING_RELATIONSHIPS direct_report "
            "WHERE direct_report.PRINCIPAL_ID = " + target_principal_sql + " "
            "AND direct_report.MANAGER_PRINCIPAL_ID = :principal_id "
            "AND direct_report.RELATIONSHIP_TYPE = 'DIRECT' "
            "AND direct_report.STATUS = 'ACTIVE' "
            "AND (direct_report.VALID_UNTIL IS NULL OR direct_report.VALID_UNTIL > CURRENT_TIMESTAMP))"
        )
    if "RESPONSIBLE_GROUP" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_RESPONSIBLE_GROUPS actor_group_def "
            "JOIN CX_RESPONSIBLE_GROUP_MEMBERS actor_group "
            "ON actor_group.GROUP_ID = actor_group_def.GROUP_ID "
            "JOIN CX_RESPONSIBLE_GROUP_MEMBERS target_group "
            "ON target_group.GROUP_ID = actor_group.GROUP_ID "
            "WHERE actor_group.PRINCIPAL_ID = :principal_id "
            "AND target_group.PRINCIPAL_ID = " + target_principal_sql + " "
            "AND actor_group_def.STATUS = 'ACTIVE' "
            "AND actor_group.STATUS = 'ACTIVE' AND target_group.STATUS = 'ACTIVE')"
        )
    if "ORG_SUBTREE" in scopes:
        clauses.append(_organization_scope_clause(target_principal_sql))
    domain_clause = ""
    if "SECURITY_DOMAIN" in scopes:
        domain_clause = (
            "EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS actor_domain "
            "JOIN CX_DOMAIN_MEMBERS target_domain ON target_domain.SECURITY_DOMAIN_ID = actor_domain.SECURITY_DOMAIN_ID "
            "WHERE actor_domain.PRINCIPAL_ID = :principal_id "
            "AND target_domain.PRINCIPAL_ID = " + target_principal_sql + " "
            "AND actor_domain.STATUS = 'ACTIVE' AND target_domain.STATUS = 'ACTIVE')"
        )
    scoped = "(" + " OR ".join(clauses) + ")" if clauses else ("1 = 1" if domain_clause else "1 = 0")
    return f"({scoped} AND {domain_clause})" if domain_clause else scoped


def _agent_visibility_clause(principal_id: str) -> str:
    scopes = _active_scopes(principal_id)
    _ensure_scope_tables(scopes)
    if "ALL" in scopes:
        return "1 = 1"
    clauses: list[str] = []
    if "OWNED" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS owned_r "
            "WHERE owned_r.AGENT_ID = p.PRINCIPAL_ID AND owned_r.PRINCIPAL_ID = :principal_id "
            "AND owned_r.RELATIONSHIP_ROLE IN ('PRIMARY_OWNER','SPONSOR') AND owned_r.STATUS = 'ACTIVE')"
        )
    if "ASSIGNED" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS assigned_r "
            "WHERE assigned_r.AGENT_ID = p.PRINCIPAL_ID AND assigned_r.PRINCIPAL_ID = :principal_id "
            "AND assigned_r.STATUS = 'ACTIVE')"
        )
    if "DIRECT_REPORTS" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS report_r "
            "JOIN CX_REPORTING_RELATIONSHIPS report_member ON report_member.PRINCIPAL_ID = report_r.PRINCIPAL_ID "
            "WHERE report_r.AGENT_ID = p.PRINCIPAL_ID AND report_r.STATUS = 'ACTIVE' "
            "AND report_member.MANAGER_PRINCIPAL_ID = :principal_id "
            "AND report_member.RELATIONSHIP_TYPE = 'DIRECT' AND report_member.STATUS = 'ACTIVE' "
            "AND (report_member.VALID_UNTIL IS NULL OR report_member.VALID_UNTIL > CURRENT_TIMESTAMP))"
        )
    if "RESPONSIBLE_GROUP" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS group_r "
            "JOIN CX_RESPONSIBLE_GROUPS group_def ON group_def.GROUP_ID = group_r.RESPONSIBLE_GROUP_ID "
            "JOIN CX_RESPONSIBLE_GROUP_MEMBERS actor_group ON actor_group.PRINCIPAL_ID = :principal_id "
            "JOIN CX_RESPONSIBLE_GROUP_MEMBERS target_group ON target_group.GROUP_ID = actor_group.GROUP_ID "
            "AND target_group.PRINCIPAL_ID = group_r.PRINCIPAL_ID "
            "WHERE group_r.AGENT_ID = p.PRINCIPAL_ID AND group_r.STATUS = 'ACTIVE' "
            "AND group_def.STATUS = 'ACTIVE' "
            "AND actor_group.STATUS = 'ACTIVE' AND target_group.STATUS = 'ACTIVE' "
            "AND group_r.RESPONSIBLE_GROUP_ID = actor_group.GROUP_ID)"
        )
    if "ORG_SUBTREE" in scopes:
        clauses.append(
            "EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS org_r "
            "WHERE org_r.AGENT_ID = p.PRINCIPAL_ID AND org_r.STATUS = 'ACTIVE' AND "
            + _organization_scope_clause("org_r.PRINCIPAL_ID") + ")"
        )
    domain_clause = ""
    if "SECURITY_DOMAIN" in scopes:
        domain_clause = (
            "EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS actor_domain "
            "JOIN CX_DOMAIN_MEMBERS agent_domain ON agent_domain.SECURITY_DOMAIN_ID = actor_domain.SECURITY_DOMAIN_ID "
            "WHERE actor_domain.PRINCIPAL_ID = :principal_id AND agent_domain.PRINCIPAL_ID = p.PRINCIPAL_ID "
            "AND actor_domain.STATUS = 'ACTIVE' AND agent_domain.STATUS = 'ACTIVE')"
        )
    scoped = "(" + " OR ".join(clauses) + ")" if clauses else ("1 = 1" if domain_clause else "1 = 0")
    return f"({scoped} AND {domain_clause})" if domain_clause else scoped


def _protected_bootstrap_admin(principal_id: str) -> bool:
    row = _row(connection.execute_query_one(
        "SELECT 1 FROM CX_HUMAN_IDENTITIES i JOIN CX_USER_ROLES r "
        "ON r.PRINCIPAL_ID = i.PRINCIPAL_ID "
        "WHERE i.PRINCIPAL_ID = :principal_id AND i.IDENTITY_TYPE = 'LOCAL' "
        "AND i.SUBJECT_KEY = 'admin' AND i.STATUS = 'ACTIVE' "
        "AND r.ROLE_CODE = 'SYSTEM_ADMIN' AND r.STATUS = 'ACTIVE' "
        "AND r.SOURCE = 'BOOTSTRAP_ADMIN'",
        {"principal_id": principal_id},
    ))
    return bool(row)


def has_active_login_identity(principal_id: str, executor: Any = None) -> bool:
    """Return whether a Human Principal has a usable proven login identity."""
    executor = executor or connection
    query_one = getattr(executor, "query_one", None) or executor.execute_query_one
    return bool(_row(query_one(
        "SELECT IDENTITY_ID FROM CX_HUMAN_IDENTITIES "
        "WHERE PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE'",
        {"principal_id": principal_id},
    )))


def has_active_primary_organization(principal_id: str, executor: Any = None) -> bool:
    """Return whether a Human Principal has its authoritative placement."""
    executor = executor or connection
    query_one = getattr(executor, "query_one", None) or executor.execute_query_one
    return bool(_row(query_one(
        "SELECT MEMBERSHIP_ID FROM CX_ORGANIZATION_MEMBERS "
        "WHERE PRINCIPAL_ID = :principal_id AND MEMBERSHIP_KIND = 'PRIMARY' "
        "AND STATUS = 'ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"principal_id": principal_id},
    )))


def entry_access(principal_id: str) -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT PORTAL_ACCESS, APP_ACCESS, STATUS FROM CX_PRINCIPALS "
        "WHERE PRINCIPAL_ID = :principal_id AND PRINCIPAL_TYPE = 'HUMAN'",
        {"principal_id": principal_id},
    ))
    active = bool(row and str(row.get("status") or "").upper() == "ACTIVE")
    protected = active and _protected_bootstrap_admin(principal_id)
    organization_ready = protected or (active and has_active_primary_organization(principal_id))
    return {
        "principal_id": principal_id,
        "portal_enabled": organization_ready and (protected or str(row.get("portal_access") or "N").upper() == "Y"),
        "app_enabled": organization_ready and (protected or str(row.get("app_access") or "N").upper() == "Y"),
        "protected_system_admin": protected,
        "organization_ready": organization_ready,
    }


def entry_allowed(principal_id: str, entry: str) -> bool:
    code = str(entry or "").strip().upper()
    if code not in {"PORTAL", "APP"}:
        return False
    access = entry_access(principal_id)
    return bool(access["portal_enabled" if code == "PORTAL" else "app_enabled"])


def get_entry_access(actor_principal_id: str, target_principal_id: str) -> Dict[str, Any]:
    _require(actor_principal_id, "users.read")
    if not _principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("user is outside the delegated scope")
    return entry_access(target_principal_id)


def set_entry_access(
    actor_principal_id: str, target_principal_id: str, app_enabled: bool, reason: str,
) -> Dict[str, Any]:
    if not reason.strip():
        raise IdentityError("Entry-access change reason is required")
    _require(actor_principal_id, "users.permissions.manage")
    if not _principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("user is outside the delegated scope")
    current = entry_access(target_principal_id)
    if current["protected_system_admin"] and not app_enabled:
        raise PermissionError("bootstrap administrator entry access is protected")
    changed = connection.execute(
        "UPDATE CX_PRINCIPALS SET PORTAL_ACCESS = 'Y', APP_ACCESS = :app_access, "
        "PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE PRINCIPAL_ID = :principal_id AND PRINCIPAL_TYPE = 'HUMAN' AND STATUS = 'ACTIVE'",
        {"app_access": "Y" if app_enabled else "N", "principal_id": target_principal_id},
    )
    if changed != 1:
        raise IdentityError("Entry-access target is unavailable")
    revoke_principal_sessions(target_principal_id, "entry-access policy changed")
    _audit(actor_principal_id, "USER_ENTRY_ACCESS_UPDATE", "HUMAN", target_principal_id, "ALLOW", reason)
    return entry_access(target_principal_id)


def list_users(principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return only human identities visible to the authenticated Principal.

    The first implementation uses role-backed administration.  Data-scope
    filtering is deliberately kept server-side and can be extended with
    organization/domain joins without changing the API contract.
    """
    _require(principal_id, "users.read")
    suffix = _limit_clause()
    visibility = _principal_visibility_clause(principal_id)
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    if ":principal_id" in visibility:
        params["principal_id"] = principal_id
    rows = _required_query(
        "SELECT p.PRINCIPAL_ID, p.PRINCIPAL_TYPE, p.DISPLAY_NAME, p.STATUS, p.PERMISSION_VERSION, "
        "p.PORTAL_ACCESS, p.APP_ACCESS, "
        "(SELECT MIN(i.USERNAME) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS USERNAME, "
        "(SELECT MIN(i.EMAIL) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS EMAIL, "
        "(SELECT MIN(i.IDENTITY_TYPE) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS IDENTITY_TYPE, "
        "(SELECT MAX(i.LAST_LOGIN_AT) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS LAST_LOGIN_AT, "
        "(SELECT COUNT(*) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND i.STATUS = 'ACTIVE') AS LOGIN_IDENTITY_COUNT, "
        "m.ORGANIZATION_ID, o.ORGANIZATION_NAME "
        "FROM CX_PRINCIPALS p LEFT JOIN CX_ORGANIZATION_MEMBERS m ON m.PRINCIPAL_ID = p.PRINCIPAL_ID "
        "AND m.MEMBERSHIP_KIND = 'PRIMARY' AND m.STATUS = 'ACTIVE' "
        "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "LEFT JOIN CX_ORGANIZATIONS o ON o.ORGANIZATION_ID = m.ORGANIZATION_ID "
        "WHERE p.PRINCIPAL_TYPE = 'HUMAN' AND " + visibility + " "
        "ORDER BY p.DISPLAY_NAME, p.PRINCIPAL_ID " + suffix,
        params,
    )
    for row in rows:
        protected = _protected_bootstrap_admin(str(row["principal_id"]))
        if protected:
            row["display_name"] = "管理员"
        organization_ready = protected or bool(row.get("organization_id"))
        row["portal_enabled"] = organization_ready and (protected or str(row.get("portal_access") or "N").upper() == "Y")
        row["app_enabled"] = organization_ready and (protected or str(row.get("app_access") or "N").upper() == "Y")
        row["protected_system_admin"] = protected
        row["account_ready"] = protected or int(row.get("login_identity_count") or 0) > 0
        row["organization_ready"] = organization_ready
    return rows


def list_users_cursor(principal_id: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    """Return a principal-bound keyset page of human users."""
    _require(principal_id, "users.read")
    context = cursor_pagination.resolve(principal_id, "users", {}, "principal_id:asc", page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "users", "sort_key": "principal_id:asc"})
    visibility = _principal_visibility_clause(principal_id)
    after = str(context["position"].get("principal_id") or "")
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    if ":principal_id" in visibility:
        params["principal_id"] = principal_id
    after_clause = " AND p.PRINCIPAL_ID>:after" if after else ""
    if after:
        params["after"] = after
    rows = _required_query(
        "SELECT p.PRINCIPAL_ID,p.PRINCIPAL_TYPE,p.DISPLAY_NAME,p.STATUS,p.PERMISSION_VERSION,p.PORTAL_ACCESS,p.APP_ACCESS,"
        "(SELECT MIN(i.USERNAME) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID=p.PRINCIPAL_ID AND i.STATUS='ACTIVE') AS USERNAME,"
        "(SELECT MIN(i.EMAIL) FROM CX_HUMAN_IDENTITIES i WHERE i.PRINCIPAL_ID=p.PRINCIPAL_ID AND i.STATUS='ACTIVE') AS EMAIL,"
        "m.ORGANIZATION_ID,o.ORGANIZATION_NAME FROM CX_PRINCIPALS p LEFT JOIN CX_ORGANIZATION_MEMBERS m ON m.PRINCIPAL_ID=p.PRINCIPAL_ID "
        "AND m.MEMBERSHIP_KIND='PRIMARY' AND m.STATUS='ACTIVE' LEFT JOIN CX_ORGANIZATIONS o ON o.ORGANIZATION_ID=m.ORGANIZATION_ID "
        "WHERE p.PRINCIPAL_TYPE='HUMAN' AND " + visibility + after_clause + " ORDER BY p.PRINCIPAL_ID " + _limit_clause(), params,
    )
    for row in rows:
        protected = _protected_bootstrap_admin(str(row["principal_id"]))
        row["display_name"] = "管理员" if protected else row.get("display_name")
        row["portal_enabled"] = protected or str(row.get("portal_access") or "N").upper() == "Y"
        row["app_enabled"] = protected or str(row.get("app_access") or "N").upper() == "Y"
        row["protected_system_admin"] = protected
    result = cursor_pagination.page(rows, context, lambda item: {"principal_id": str(item["principal_id"])})
    count_params: Dict[str, Any] = {}
    if ":principal_id" in visibility:
        count_params["principal_id"] = principal_id
    try:
        total = _row(connection.execute_query_one(
            "SELECT COUNT(*) AS CNT FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_TYPE='HUMAN' AND " + visibility,
            count_params,
        ))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def _principal_visible_to(actor_principal_id: str, target_principal_id: str) -> bool:
    """Apply the same bounded scope used by the user and Agent inventories."""
    if actor_principal_id == target_principal_id:
        return True
    if effective_access(actor_principal_id, "users.read.all")["decision"] == "ALLOW":
        return True
    visibility = _principal_visibility_clause(actor_principal_id, "p.PRINCIPAL_ID")
    params = {"target": target_principal_id}
    if ":principal_id" in visibility:
        params["principal_id"] = actor_principal_id
    row = _row(connection.execute_query_one(
        "SELECT 1 FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_ID = :target AND " + visibility,
        params,
    ))
    return bool(row)


def list_registration_requests(principal_id: str, status: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "users.read")
    # A pending request has no authenticated Principal or organization yet.
    # Returning it to a scoped manager would therefore leak an unbound identity.
    if effective_access(principal_id, "users.read.all")["decision"] != "ALLOW":
        raise PermissionError("registration review requires global user scope")
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    where = ""
    if status:
        where = " WHERE STATUS = :status"
        params["status"] = status.upper()[:32]
    return _required_query(
        "SELECT REQUEST_ID, USERNAME, DISPLAY_NAME, EMAIL, AUTH_SOURCE, REGISTRATION_MODE, STATUS, "
        "DECISION_BY, DECISION_REASON, CREATED_AT, DECIDED_AT FROM CX_REGISTRATION_REQUESTS" +
        where + " ORDER BY CREATED_AT DESC " + _limit_clause(), params,
    )


def list_user_roles(actor_principal_id: str, target_principal_id: str) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "users.read")
    if not _principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("user is outside the delegated scope")
    rows = _required_query(
        "SELECT USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE, VALID_FROM, VALID_UNTIL, "
        "GRANTED_BY, STATUS FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id "
        "ORDER BY ROLE_CODE",
        {"principal_id": target_principal_id},
    )
    protected = _protected_bootstrap_admin(target_principal_id)
    for row in rows:
        row["protected"] = protected and str(row.get("role_code") or "").upper() == "SYSTEM_ADMIN"
    return rows


def assign_user_role(actor_principal_id: str, target_principal_id: str, role_code: str, reason: str) -> Dict[str, Any]:
    if not reason.strip():
        raise IdentityError("Role change reason is required")
    _require(actor_principal_id, "users.roles.manage")
    target = str(target_principal_id or "").strip()
    role = str(role_code or "").strip().upper()
    if not target or role not in set(ROLE_FALLBACKS) | {"USER_ADMIN", "ORG_MANAGER", "ROLE_ADMIN"}:
        raise IdentityError("Role assignment is invalid")
    if role == "AGENT":
        raise IdentityError("Agent roles are assigned through Agent enrollment")
    if target == actor_principal_id and role not in {"END_USER"}:
        raise PermissionError("self elevation is not allowed")
    if not _principal_visible_to(actor_principal_id, target):
        raise PermissionError("user is outside the delegated scope")
    if role in {"SYSTEM_ADMIN", "SECURITY_ADMIN", "USER_ADMIN", "ORG_MANAGER", "ROLE_ADMIN"} and effective_access(actor_principal_id, "users.roles.manage.all")["decision"] != "ALLOW":
        raise PermissionError("elevated role requires role-administration delegation")
    target_row = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": target},
    ))
    if not target_row or str(target_row.get("principal_type") or "").upper() != "HUMAN" or str(target_row.get("status") or "").upper() != "ACTIVE":
        raise IdentityError("Role target is unavailable")
    role_id = _id("UR")
    inserted = connection.execute(
        "INSERT INTO CX_USER_ROLES(USER_ROLE_ID, PRINCIPAL_ID, ROLE_CODE, SOURCE, GRANTED_BY, STATUS) "
        "VALUES (:user_role_id, :principal_id, :role_code, 'DIRECT', :granted_by, 'ACTIVE')",
        {"user_role_id": role_id, "principal_id": target, "role_code": role, "granted_by": actor_principal_id},
    )
    if inserted != 1:
        raise IdentityError("Role assignment was not committed")
    revoke_principal_sessions(target, "role assignment")
    _audit(actor_principal_id, "USER_ROLE_ASSIGN", "HUMAN", target, "ALLOW", reason)
    return {"user_role_id": role_id, "principal_id": target, "role_code": role, "reason": reason[:2000]}


def revoke_user_role(actor_principal_id: str, target_principal_id: str, user_role_id: str, reason: str) -> bool:
    if not reason.strip():
        raise IdentityError("Role change reason is required")
    _require(actor_principal_id, "users.roles.manage")
    if not _principal_visible_to(actor_principal_id, target_principal_id):
        raise PermissionError("user is outside the delegated scope")
    assigned = _row(connection.execute_query_one(
        "SELECT ROLE_CODE FROM CX_USER_ROLES WHERE USER_ROLE_ID = :user_role_id "
        "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE'",
        {"user_role_id": user_role_id, "principal_id": target_principal_id},
    ))
    if not assigned:
        return False
    if str(assigned.get("role_code") or "").upper() == "SYSTEM_ADMIN" and _protected_bootstrap_admin(target_principal_id):
        raise PermissionError("bootstrap administrator system role is protected")
    if (
        str(assigned.get("role_code") or "").upper()
        in {"SYSTEM_ADMIN", "SECURITY_ADMIN", "USER_ADMIN", "ORG_MANAGER", "ROLE_ADMIN"}
        and effective_access(actor_principal_id, "users.roles.manage.all")["decision"] != "ALLOW"
    ):
        raise PermissionError("elevated role requires role-administration delegation")
    changed = connection.execute(
        "UPDATE CX_USER_ROLES SET STATUS = 'REVOKED' WHERE USER_ROLE_ID = :user_role_id "
        "AND PRINCIPAL_ID = :principal_id AND ROLE_CODE <> 'END_USER' AND STATUS = 'ACTIVE'",
        {"user_role_id": user_role_id, "principal_id": target_principal_id},
    ) > 0
    if changed:
        revoke_principal_sessions(target_principal_id, "role revocation")
        _audit(actor_principal_id, "USER_ROLE_REVOKE", "HUMAN", target_principal_id, "ALLOW", reason)
    return changed


def list_role_templates(principal_id: str) -> List[Dict[str, Any]]:
    _require(principal_id, "users.read")
    rows = _required_query(
        "SELECT ROLE_CODE, DISPLAY_NAME, PERMISSIONS_JSON, DATA_SCOPES_JSON, VERSION, MANAGED, UPDATED_AT "
        "FROM CX_ROLE_TEMPLATES ORDER BY ROLE_CODE"
    )
    for row in rows:
        for key in ("permissions_json", "data_scopes_json"):
            try:
                row[key[:-5]] = json.loads(row.pop(key) or "[]")
            except (TypeError, ValueError):
                row[key[:-5]] = []
    return rows


def assign_permission_override(
    actor_principal_id: str,
    target_principal_id: str,
    resource_action: str,
    effect: str,
    data_scope: str,
    reason: str,
) -> Dict[str, Any]:
    """Add an auditable per-user permission override without editing role code."""
    if not reason.strip():
        raise IdentityError("Permission override reason is required")
    _require(actor_principal_id, "users.permissions.manage")
    target = str(target_principal_id or "").strip()
    action = str(resource_action or "").strip()
    target_effect = str(effect or "").upper().strip()
    scope = str(data_scope or "NONE").upper().strip()
    if not target or not action or len(action) > 256 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.*-" for char in action):
        raise IdentityError("Permission action is invalid")
    if target_effect not in {"ALLOW", "DENY"} or scope not in SCOPES:
        raise IdentityError("Permission override is invalid")
    if not _principal_visible_to(actor_principal_id, target):
        raise PermissionError("user is outside the delegated scope")
    if target == actor_principal_id and target_effect == "ALLOW":
        raise PermissionError("self permission elevation is not allowed")
    if target_effect == "DENY" and _protected_bootstrap_admin(target):
        raise PermissionError("bootstrap administrator authority is protected")
    if action in {"*", "users.roles.manage", "users.permissions.manage", "security.*"} and effective_access(actor_principal_id, "users.roles.manage.all")["decision"] != "ALLOW":
        raise PermissionError("elevated permission requires role-administration delegation")
    override_id = _id("PO")
    changed = connection.execute(
        "INSERT INTO CX_USER_PERMISSION_OVERRIDES(OVERRIDE_ID, PRINCIPAL_ID, RESOURCE_ACTION, EFFECT, DATA_SCOPE, REASON, GRANTED_BY) "
        "VALUES (:override_id, :principal_id, :resource_action, :effect, :data_scope, :reason, :granted_by)",
        {"override_id": override_id, "principal_id": target, "resource_action": action,
         "effect": target_effect, "data_scope": scope, "reason": reason[:2000],
         "granted_by": actor_principal_id},
    )
    if changed != 1:
        raise IdentityError("Permission override was not committed")
    revoke_principal_sessions(target, "permission override")
    _audit(actor_principal_id, "USER_PERMISSION_OVERRIDE", "HUMAN", target, target_effect, reason)
    return {
        "override_id": override_id,
        "principal_id": target,
        "resource_action": action,
        "effect": target_effect,
        "data_scope": scope,
        "reason": reason[:2000],
    }


def authenticate_local(username: str, password: str) -> Optional[Dict[str, Any]]:
    username = _normalize_username(username)
    salt_expr = "COALESCE(u.SALT, '') AS SALT, " if _dialect() == "postgresql" else "'' AS SALT, "
    # v4.3 authentication is Principal-based.  A failed identity-schema
    # query must not silently become a legacy SYSTEM_USERS authentication,
    # because a permission or connection failure would otherwise bypass the
    # new status, MFA, lockout, and session admission checks.
    row = _row(connection.execute_query_one(
        "SELECT u.USER_ID, u.USERNAME, u.PASSWORD_HASH, u.ROLE, u.STATUS, u.AUTH_SOURCE, "
        + salt_expr + "i.IDENTITY_ID, i.PRINCIPAL_ID, i.PROVIDER, i.LOCKED_UNTIL FROM SYSTEM_USERS u "
        "LEFT JOIN CX_HUMAN_IDENTITIES i ON i.IDENTITY_TYPE = 'LOCAL' AND i.SUBJECT_KEY = u.USERNAME "
        "WHERE u.USERNAME = :username", {"username": username},
    ))
    if not row or str(row.get("status") or "").upper() != "ACTIVE":
        return None
    if str(row.get("auth_source") or "LOCAL").upper() != "LOCAL":
        return None
    locked_until = _timestamp(row.get("locked_until"))
    if locked_until is not None and locked_until > _now():
        return None
    valid, upgraded = verify_password_hash(password, str(row.get("password_hash") or ""), str(row.get("salt") or ""))
    if not valid:
        return None
    if upgraded:
        connection.execute(
            "UPDATE SYSTEM_USERS SET PASSWORD_HASH = :password_hash, UPDATED_AT = CURRENT_TIMESTAMP WHERE USER_ID = :user_id",
            {"password_hash": upgraded, "user_id": row["user_id"]},
        )
        if row.get("principal_id"):
            connection.execute(
                "UPDATE CX_HUMAN_IDENTITIES SET PASSWORD_HASH = :password_hash, PASSWORD_VERSION = 'argon2id-v1', UPDATED_AT = CURRENT_TIMESTAMP WHERE PRINCIPAL_ID = :principal_id",
                {"password_hash": upgraded, "principal_id": row["principal_id"]},
            )
    if not row.get("principal_id"):
        principal_id = _ensure_principal(
            str(row["user_id"]), username,
            upgraded or str(row["password_hash"]), "ACTIVE",
            str(row.get("role") or "USER"),
        )
        row["principal_id"] = principal_id
    elif row.get("identity_id") and str(row.get("provider") or "").upper() != LOCAL_PROVIDER:
        # Oracle-compatible engines expose an empty string as NULL.  Repair
        # identities adopted before v4.3 so all later identity operations see
        # the explicit local provider value.
        connection.execute(
            "UPDATE CX_HUMAN_IDENTITIES SET PROVIDER = :provider, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE IDENTITY_ID = :identity_id",
            {"provider": LOCAL_PROVIDER, "identity_id": row["identity_id"]},
        )
    connection.execute("UPDATE SYSTEM_USERS SET LAST_LOGIN = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP WHERE USER_ID = :user_id", {"user_id": row["user_id"]})
    return row


def create_session(principal_id: str, user_id: str, node_id: str, auth_method: str = "LOCAL",
                   mfa_level: str = "NONE", ttl_seconds: int = 300) -> Dict[str, str]:
    raw_id = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw_id.encode("ascii")).hexdigest()
    csrf_digest = hashlib.sha256(csrf.encode("ascii")).hexdigest()
    current = _row(connection.execute_query_one(
        "SELECT PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id", {"principal_id": principal_id}
    )) or {}
    permission_version = int(current.get("permission_version") or 1)
    try:
        requested_ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise IdentityError("session timeout is invalid") from exc
    # Write both timestamps from the application clock.  CURRENT_TIMESTAMP is
    # database-session-timezone dependent, which made the five-minute hard
    # limit reject valid PostgreSQL/YashanDB sessions after they were created.
    created = _now()
    expires = created + timedelta(seconds=max(60, min(SESSION_MAX_SECONDS, requested_ttl)))
    connection.execute(
        "INSERT INTO CX_WEB_SESSIONS(SESSION_DIGEST, PRINCIPAL_ID, USER_ID, AUTH_METHOD, MFA_LEVEL, NODE_ID, CLIENT_SUMMARY, PERMISSION_VERSION, CSRF_DIGEST, CREATED_AT, EXPIRES_AT) "
        "VALUES (:digest, :principal_id, :user_id, :auth_method, :mfa_level, :node_id, :client_summary, :permission_version, :csrf_digest, :created_at, :expires_at)",
        {"digest": digest, "principal_id": principal_id, "user_id": user_id, "auth_method": auth_method,
         "mfa_level": mfa_level, "node_id": node_id, "client_summary": "", "permission_version": permission_version,
         "csrf_digest": csrf_digest, "created_at": created, "expires_at": expires},
    )
    return {"session_id": raw_id, "csrf_token": csrf, "expires_at": _iso(expires) or ""}


def resolve_session(raw_session_id: str, touch: bool = True, ttl_seconds: int = 300,
                    absolute_ttl_seconds: int = SESSION_MAX_SECONDS) -> Optional[Dict[str, Any]]:
    if not raw_session_id:
        return None
    digest = hashlib.sha256(raw_session_id.encode("utf-8")).hexdigest()
    row = _row(connection.execute_query_one(
        "SELECT SESSION_DIGEST, PRINCIPAL_ID, USER_ID, AUTH_METHOD, MFA_LEVEL, NODE_ID, PERMISSION_VERSION, CSRF_DIGEST, EXPIRES_AT, CREATED_AT, REVOKED_AT "
        "FROM CX_WEB_SESSIONS WHERE SESSION_DIGEST = :digest", {"digest": digest}
    ))
    if not row or row.get("revoked_at") is not None:
        return None
    now = _now()
    try:
        expiry = _timestamp(row.get("expires_at"))
        created = _timestamp(row.get("created_at"))
    except IdentityError:
        return None
    try:
        absolute_ttl = int(absolute_ttl_seconds)
    except (TypeError, ValueError):
        absolute_ttl = SESSION_MAX_SECONDS
    absolute_deadline = created + timedelta(seconds=max(60, min(SESSION_MAX_SECONDS, absolute_ttl))) if created else None
    if (expiry is not None and expiry <= now) or (absolute_deadline is not None and absolute_deadline <= now):
        return None
    principal = _row(connection.execute_query_one(
        "SELECT STATUS, MFA_REQUIRED, PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id", {"principal_id": row["principal_id"]}
    ))
    if not principal or str(principal.get("status") or "").upper() != "ACTIVE":
        return None
    required_mfa = principal.get("mfa_required")
    if (required_mfa is True or str(required_mfa or "").upper() in {"Y", "YES", "TRUE", "1"}) and str(row.get("mfa_level") or "NONE").upper() == "NONE":
        return None
    if int(principal.get("permission_version") or 1) != int(row.get("permission_version") or 1):
        return None
    if touch:
        try:
            requested_ttl = int(ttl_seconds)
        except (TypeError, ValueError):
            requested_ttl = 300
        new_expiry = now + timedelta(seconds=max(60, min(SESSION_MAX_SECONDS, requested_ttl)))
        if absolute_deadline is not None:
            new_expiry = min(new_expiry, absolute_deadline)
        connection.execute(
            "UPDATE CX_WEB_SESSIONS SET LAST_SEEN_AT = :last_seen_at, EXPIRES_AT = :expires_at "
            "WHERE SESSION_DIGEST = :digest AND REVOKED_AT IS NULL",
            {"last_seen_at": now, "expires_at": new_expiry, "digest": digest},
        )
        row["expires_at"] = new_expiry
    row["session_digest"] = digest
    row["permission_version"] = int(principal.get("permission_version") or 1)
    return row


def set_session_mfa_level(session_digest: str, mfa_level: str = "STRONG") -> bool:
    """Promote a verified setup session after its MFA factor is confirmed."""
    level = str(mfa_level or "").upper()
    if not session_digest or level != "STRONG":
        raise IdentityError("MFA session level is invalid")
    return connection.execute(
        "UPDATE CX_WEB_SESSIONS SET MFA_LEVEL = :mfa_level "
        "WHERE SESSION_DIGEST = :session_digest AND REVOKED_AT IS NULL",
        {"mfa_level": level, "session_digest": session_digest},
    ) == 1


def revoke_session(raw_session_id: str, reason: str = "logout") -> bool:
    digest = hashlib.sha256(str(raw_session_id or "").encode("utf-8")).hexdigest()
    return connection.execute(
        "UPDATE CX_WEB_SESSIONS SET REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason WHERE SESSION_DIGEST = :digest AND REVOKED_AT IS NULL",
        {"digest": digest, "reason": reason[:1000]},
    ) > 0


def revoke_principal_sessions(principal_id: str, reason: str = "permission change") -> int:
    count = connection.execute(
        "UPDATE CX_WEB_SESSIONS SET REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason WHERE PRINCIPAL_ID = :principal_id AND REVOKED_AT IS NULL",
        {"principal_id": principal_id, "reason": reason[:1000]},
    )
    connection.execute("UPDATE CX_PRINCIPALS SET PERMISSION_VERSION = PERMISSION_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP WHERE PRINCIPAL_ID = :principal_id", {"principal_id": principal_id})
    return count


def verify_csrf(session: Dict[str, Any], csrf_token: str) -> bool:
    if not csrf_token or not session.get("csrf_digest"):
        return False
    return hmac.compare_digest(str(session["csrf_digest"]), hashlib.sha256(csrf_token.encode("utf-8")).hexdigest())


def _permission_match(permissions: Iterable[str], action: str) -> bool:
    for item in permissions:
        item = str(item)
        if item == "*" or item == action:
            return True
        if item.endswith(".*") and action.startswith(item[:-1]):
            return True
    return False


def effective_access(
    principal_id: str,
    action: str,
    *,
    resource: Optional[Dict[str, Any]] = None,
    _include_delegations: bool = True,
) -> Dict[str, Any]:
    principal = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_TYPE, STATUS, PERMISSION_VERSION FROM CX_PRINCIPALS "
        "WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": principal_id},
    ))
    principal_status = str((principal or {}).get("status") or "").upper()
    if not principal or principal_status != "ACTIVE":
        # Never turn an unknown, disabled, expired, or pending identity into
        # a default End User.  This is the first decision in every API path.
        return {
            "decision": "DENY",
            "action": action,
            "scopes": ["NONE"],
            "roles": [],
            "sources": ["principal:inactive-or-unknown"],
            "policy_version": int((principal or {}).get("permission_version") or 0),
        }
    roles = _rows(_required_query(
        "SELECT ROLE_CODE FROM CX_USER_ROLES WHERE PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)", {"principal_id": principal_id}
    ))
    if not roles:
        roles = [{"role_code": "AGENT" if str(principal.get("principal_type") or "").upper() == "AGENT" else "END_USER"}]
    permissions: set[str] = set()
    scopes: set[str] = set()
    sources: List[str] = []
    for role_row in roles:
        code = str(role_row.get("role_code") or "END_USER").upper()
        template = _row(connection.execute_query_one("SELECT PERMISSIONS_JSON, DATA_SCOPES_JSON FROM CX_ROLE_TEMPLATES WHERE ROLE_CODE = :role_code", {"role_code": code}))
        fallback = ROLE_FALLBACKS.get(code, ROLE_FALLBACKS["END_USER"])
        try:
            role_permissions = set(json.loads(template.get("permissions_json") or "[]")) if template else set(fallback["permissions"])
        except (ValueError, TypeError):
            role_permissions = set(fallback["permissions"])
        try:
            role_scopes = set(json.loads(template.get("data_scopes_json") or "[]")) if template else set(fallback["scopes"])
        except (ValueError, TypeError):
            role_scopes = set(fallback["scopes"])
        permissions.update(role_permissions)
        scopes.update(role_scopes & SCOPES)
        sources.append(f"role:{code}")
    overrides = _rows(_required_query(
        "SELECT EFFECT, DATA_SCOPE, SECURITY_DOMAIN_ID, REASON, GRANTED_BY FROM CX_USER_PERMISSION_OVERRIDES "
        "WHERE PRINCIPAL_ID = :principal_id AND RESOURCE_ACTION = :action AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP) "
        "ORDER BY CREATED_AT DESC", {"principal_id": principal_id, "action": action}
    ))
    decision = "ALLOW" if _permission_match(permissions, action) else "DENY"
    explicit_deny = False
    for override in overrides:
        source = f"override:{override.get('granted_by') or 'unknown'}"
        sources.append(source)
        if str(override.get("effect") or "").upper() == "DENY":
            decision = "DENY"
            explicit_deny = True
            break
        decision = "ALLOW"
        if str(override.get("data_scope") or "NONE").upper() in SCOPES:
            scopes.add(str(override["data_scope"]).upper())
    if _include_delegations and not explicit_deny:
        # Delegations are runtime grants, not role copies.  Every evaluation
        # rechecks the grantor's current direct authority, status and expiry;
        # revocation therefore takes effect without waiting for a cache or
        # session restart.  Delegated authority is deliberately not used to
        # validate the grantor, preventing transitive self-expansion.
        delegations = _required_query(
            "SELECT DELEGATION_ID, GRANTOR_PRINCIPAL_ID, PERMISSIONS_JSON, DATA_SCOPE "
            "FROM CX_DELEGATIONS WHERE GRANTEE_PRINCIPAL_ID = :principal_id "
            "AND STATUS = 'ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP) "
            "ORDER BY CREATED_AT DESC",
            {"principal_id": principal_id},
        )
        for delegation in delegations:
            grantor_id = str(delegation.get("grantor_principal_id") or "")
            if not grantor_id or grantor_id == principal_id:
                continue
            try:
                delegated_permissions = json.loads(delegation.get("permissions_json") or "[]")
            except (TypeError, ValueError):
                continue
            if not isinstance(delegated_permissions, list) or not _permission_match(delegated_permissions, action):
                continue
            grantor_access = effective_access(
                grantor_id, action, resource=resource, _include_delegations=False,
            )
            if grantor_access.get("decision") != "ALLOW":
                continue
            decision = "ALLOW"
            delegation_scope = str(delegation.get("data_scope") or "NONE").upper()
            if delegation_scope in SCOPES:
                scopes.add(delegation_scope)
            sources.append(f"delegation:{delegation.get('delegation_id') or 'unknown'}:{grantor_id}")
    if resource and decision == "ALLOW":
        required_domain = resource.get("security_domain_id")
        allowed_domain = resource.get("allowed_security_domain_id")
        if required_domain and allowed_domain and required_domain != allowed_domain:
            decision = "DENY"
    return {"decision": decision, "action": action, "scopes": sorted(scopes or {"NONE"}), "roles": [r["role_code"] for r in roles], "sources": sources, "policy_version": _permission_version(principal_id)}


def _permission_version(principal_id: str) -> int:
    row = _row(connection.execute_query_one("SELECT PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id", {"principal_id": principal_id}))
    return int((row or {}).get("permission_version") or 1)


def simulate_access(principal_id: str, action: str, resource: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = effective_access(principal_id, action, resource=resource)
    result["simulation"] = True
    return result


def _require(principal_id: str, action: str) -> None:
    if effective_access(principal_id, action)["decision"] != "ALLOW":
        raise PermissionError(f"permission denied: {action}")


def create_enrollment_grant(sponsor_principal_id: str, owner_principal_id: Optional[str] = None, *, environment: str = "development", runtime: str = "", security_domain_id: str = "DEFAULT", agent_name: str = "", risk_tier: str = "STANDARD", ttl_seconds: int = 900, node_constraint: str = "", public_key_constraint: str = "", responsible_group_id: str = "") -> Dict[str, Any]:
    agent_name = str(agent_name or "").strip()
    if not agent_name:
        raise IdentityError("Enrollment Agent name is required")
    _require(sponsor_principal_id, "agents.enroll")
    owner = owner_principal_id or sponsor_principal_id
    if owner != sponsor_principal_id and effective_access(sponsor_principal_id, "agents.enroll.others")["decision"] != "ALLOW":
        raise PermissionError("sponsor cannot enroll another owner")
    if int(ttl_seconds) < 60 or int(ttl_seconds) > 3600:
        raise IdentityError("Enrollment expiry must be between 60 and 3600 seconds")
    risk = str(risk_tier or "STANDARD").upper()
    if risk not in {"LOW", "STANDARD", "RESTRICTED", "CRITICAL"}:
        raise IdentityError("Enrollment risk tier is invalid")
    domain = _row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = :security_domain_id AND STATUS = 'ACTIVE'",
        {"security_domain_id": security_domain_id},
    ))
    if not domain:
        raise IdentityError("Enrollment security domain is unavailable")
    owner_row = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS "
        "WHERE PRINCIPAL_ID = :owner_principal_id",
        {"owner_principal_id": owner},
    ))
    if not owner_row or str(owner_row.get("status") or "").upper() != "ACTIVE":
        raise IdentityError("Enrollment owner is unavailable")
    if str(owner_row.get("principal_type") or "").upper() != "HUMAN":
        raise IdentityError("Enrollment owner must be a Human Principal")
    domain_member = _row(connection.execute_query_one(
        "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID = :domain "
        "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"domain": security_domain_id, "principal_id": owner},
    ))
    if not domain_member and effective_access(sponsor_principal_id, "domains.manage")["decision"] != "ALLOW":
        raise PermissionError("Enrollment owner is outside the security domain")
    group_id = str(responsible_group_id or "").strip()[:128]
    if group_id:
        group_member = _row(connection.execute_query_one(
            "SELECT GROUP_ID FROM CX_RESPONSIBLE_GROUP_MEMBERS "
            "WHERE GROUP_ID = :group_id AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE'",
            {"group_id": group_id, "principal_id": sponsor_principal_id},
        ))
        if not group_member and effective_access(sponsor_principal_id, "domains.manage")["decision"] != "ALLOW":
            raise PermissionError("Enrollment responsible group is unavailable")
    grant_id = _id("EG")
    token_id = _id("ET")
    raw_token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    digest = _secret_digest(raw_token, "agent-enrollment")
    expires = _now() + timedelta(seconds=int(ttl_seconds))
    snapshot = {"owner": owner, "sponsor": sponsor_principal_id, "environment": environment, "runtime": runtime, "security_domain_id": security_domain_id, "responsible_group_id": group_id, "risk_tier": risk, "created_at": _iso(_now())}
    statements = [
        ("INSERT INTO CX_ENROLLMENT_GRANTS(GRANT_ID, SPONSOR_PRINCIPAL_ID, OWNER_PRINCIPAL_ID, RESPONSIBLE_GROUP_ID, SECURITY_DOMAIN_ID, ENVIRONMENT, RUNTIME, AGENT_NAME, NODE_CONSTRAINT, PUBLIC_KEY_CONSTRAINT, RISK_TIER, POLICY_SNAPSHOT, EXPIRES_AT) VALUES (:grant_id, :sponsor, :owner, :responsible_group_id, :domain, :environment, :runtime, :agent_name, :node_constraint, :public_key_constraint, :risk_tier, :snapshot, :expires_at)", {"grant_id": grant_id, "sponsor": sponsor_principal_id, "owner": owner, "responsible_group_id": group_id or None, "domain": security_domain_id, "environment": environment, "runtime": runtime, "agent_name": agent_name[:256], "node_constraint": node_constraint[:256], "public_key_constraint": public_key_constraint, "risk_tier": risk, "snapshot": _json(snapshot), "expires_at": expires}),
        ("INSERT INTO CX_ENROLLMENT_TOKENS(TOKEN_ID, GRANT_ID, TOKEN_DIGEST, PURPOSE, EXPIRES_AT) VALUES (:token_id, :grant_id, :token_digest, 'AGENT_ENROLLMENT', :expires_at)", {"token_id": token_id, "grant_id": grant_id, "token_digest": digest, "expires_at": expires}),
    ]
    connection.execute_transaction_result(statements)
    _audit(sponsor_principal_id, "AGENT_ENROLLMENT_CREATE", "ENROLLMENT_GRANT", grant_id, "ALLOW", "one-time token issued")
    return {"grant_id": grant_id, "token": raw_token, "expires_at": _iso(expires) or "", "owner_principal_id": owner, "responsible_group_id": group_id, "risk_tier": risk}


def redeem_enrollment(token: str, agent_id: str = "", *, runtime: str = "", environment: str = "", node_id: str = "", public_key: str = "", client_secret: str = "") -> Dict[str, Any]:
    if not token or len(token) < 40:
        raise IdentityError("Enrollment token is invalid")
    digest = _secret_digest(token, "agent-enrollment")
    generated_agent_id = agent_id.strip() or _id("AG")
    if len(generated_agent_id) > 128:
        raise IdentityError("Agent identifier is invalid")

    def work(tx):
        row = _row(tx.query_one(
            "SELECT t.TOKEN_ID, t.GRANT_ID, g.AGENT_ID, g.SPONSOR_PRINCIPAL_ID, g.OWNER_PRINCIPAL_ID, g.RESPONSIBLE_GROUP_ID, g.SECURITY_DOMAIN_ID, g.ENVIRONMENT AS GRANT_ENVIRONMENT, g.RUNTIME AS GRANT_RUNTIME, g.AGENT_NAME, g.NODE_CONSTRAINT, g.PUBLIC_KEY_CONSTRAINT, g.RISK_TIER, g.POLICY_SNAPSHOT, g.MAX_USES, g.USED_COUNT "
            "FROM CX_ENROLLMENT_TOKENS t JOIN CX_ENROLLMENT_GRANTS g ON g.GRANT_ID = t.GRANT_ID "
            "WHERE t.TOKEN_DIGEST = :token_digest AND t.PURPOSE = 'AGENT_ENROLLMENT' AND t.CONSUMED_AT IS NULL AND t.EXPIRES_AT > CURRENT_TIMESTAMP AND g.STATUS = 'ACTIVE' AND g.EXPIRES_AT > CURRENT_TIMESTAMP",
            {"token_digest": digest},
        ))
        if not row:
            raise IdentityError("Enrollment token is invalid or expired")
        # Lock the one-time token and its quota row before checking usage.  A
        # read-then-update sequence without these locks can redeem one token
        # twice when two Agents race through the enrollment endpoint.
        if not tx.query_one(
            "SELECT TOKEN_ID FROM CX_ENROLLMENT_TOKENS WHERE TOKEN_ID = :token_id FOR UPDATE",
            {"token_id": row["token_id"]},
        ):
            raise IdentityError("Enrollment token is invalid or expired")
        if not tx.query_one(
            "SELECT GRANT_ID FROM CX_ENROLLMENT_GRANTS WHERE GRANT_ID = :grant_id FOR UPDATE",
            {"grant_id": row["grant_id"]},
        ):
            raise IdentityError("Enrollment grant is unavailable")
        row = _row(tx.query_one(
            "SELECT t.TOKEN_ID, t.GRANT_ID, g.AGENT_ID, g.SPONSOR_PRINCIPAL_ID, g.OWNER_PRINCIPAL_ID, g.RESPONSIBLE_GROUP_ID, g.SECURITY_DOMAIN_ID, g.ENVIRONMENT AS GRANT_ENVIRONMENT, g.RUNTIME AS GRANT_RUNTIME, g.AGENT_NAME, g.NODE_CONSTRAINT, g.PUBLIC_KEY_CONSTRAINT, g.RISK_TIER, g.POLICY_SNAPSHOT, g.MAX_USES, g.USED_COUNT "
            "FROM CX_ENROLLMENT_TOKENS t JOIN CX_ENROLLMENT_GRANTS g ON g.GRANT_ID = t.GRANT_ID "
            "WHERE t.TOKEN_ID = :token_id AND t.PURPOSE = 'AGENT_ENROLLMENT' AND t.CONSUMED_AT IS NULL AND t.EXPIRES_AT > CURRENT_TIMESTAMP AND g.STATUS = 'ACTIVE' AND g.EXPIRES_AT > CURRENT_TIMESTAMP",
            {"token_id": row["token_id"]},
        ))
        if not row:
            raise IdentityError("Enrollment token is invalid or expired")
        if row.get("node_constraint") and row["node_constraint"] != node_id:
            raise IdentityError("Enrollment node binding failed")
        if row.get("public_key_constraint") and row["public_key_constraint"] != public_key:
            raise IdentityError("Enrollment key binding failed")
        if row.get("grant_runtime") and runtime and row["grant_runtime"] != runtime:
            raise IdentityError("Enrollment runtime binding failed")
        if row.get("grant_environment") and environment and row["grant_environment"] != environment:
            raise IdentityError("Enrollment environment binding failed")
        if int(row.get("max_uses") or 0) <= int(row.get("used_count") or 0):
            raise IdentityError("Enrollment quota is exhausted")
        # Enrollment fixes ownership but does not prove an approved runtime.
        # All new Agents must complete v4.3.4 activation before formal work.
        status = "PENDING_CONFIRMATION" if str(row.get("risk_tier") or "STANDARD").upper() != "LOW" else "PENDING_ACTIVATION"
        consumed = tx.execute("UPDATE CX_ENROLLMENT_TOKENS SET CONSUMED_AT = CURRENT_TIMESTAMP, CONSUMED_AGENT_ID = :agent_id WHERE TOKEN_ID = :token_id AND CONSUMED_AT IS NULL", {"agent_id": generated_agent_id, "token_id": row["token_id"]})
        if consumed != 1:
            raise IdentityError("Enrollment token was already redeemed")
        counted = tx.execute("UPDATE CX_ENROLLMENT_GRANTS SET USED_COUNT = USED_COUNT + 1 WHERE GRANT_ID = :grant_id AND USED_COUNT < MAX_USES", {"grant_id": row["grant_id"]})
        if counted != 1:
            raise IdentityError("Enrollment quota is exhausted")
        tx.execute(
            "UPDATE CX_ENROLLMENT_GRANTS SET AGENT_ID = :agent_id WHERE GRANT_ID = :grant_id AND AGENT_ID IS NULL",
            {"agent_id": generated_agent_id, "grant_id": row["grant_id"]},
        )
        tx.execute("INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS) VALUES (:agent_id, 'AGENT', :status)", {"agent_id": generated_agent_id, "status": status})
        tx.execute(
            "INSERT INTO CX_AGENT_POSTURES(POSTURE_ID, AGENT_ID, REGISTRATION_STATE, RUNTIME_STATE, POSTURE_STATE, "
            "CONTROL_STATE, EVIDENCE_STRENGTH, VERSION) VALUES (:posture_id, :agent_id, :registration_state, "
            "'NEVER_SEEN', 'UNKNOWN', 'NORMAL', 'BOUNDARY_ONLY', 1)",
            {"posture_id": _id("POST"), "agent_id": generated_agent_id, "registration_state": status},
        )
        if row.get("security_domain_id"):
            tx.execute(
                "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID, SECURITY_DOMAIN_ID, PRINCIPAL_ID, MEMBERSHIP_TIER, STATUS) "
                "VALUES (:membership_id, :security_domain_id, :agent_id, 'MEMBER', 'ACTIVE')",
                {"membership_id": _id("DM"), "security_domain_id": row["security_domain_id"],
                 "agent_id": generated_agent_id},
            )
        tx.execute("INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, RESPONSIBLE_GROUP_ID) VALUES (:sponsor_rel, :agent_id, :sponsor, 'SPONSOR', :responsible_group_id)", {"sponsor_rel": _id("AR"), "agent_id": generated_agent_id, "sponsor": row["sponsor_principal_id"], "responsible_group_id": row.get("responsible_group_id")})
        tx.execute("INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, RESPONSIBLE_GROUP_ID) VALUES (:owner_rel, :agent_id, :owner, 'PRIMARY_OWNER', :responsible_group_id)", {"owner_rel": _id("AR"), "agent_id": generated_agent_id, "owner": row["owner_principal_id"], "responsible_group_id": row.get("responsible_group_id")})
        secret = client_secret or secrets.token_urlsafe(32)
        cred_type = "ED25519" if public_key else "CLIENT_SECRET"
        tx.execute("INSERT INTO CX_AGENT_CREDENTIALS(CREDENTIAL_ID, AGENT_ID, CREDENTIAL_TYPE, PUBLIC_KEY, SECRET_DIGEST, STATUS) VALUES (:credential_id, :agent_id, :credential_type, :public_key, :secret_digest, :status)", {"credential_id": _id("AC"), "agent_id": generated_agent_id, "credential_type": cred_type, "public_key": public_key or None, "secret_digest": _secret_digest(secret, "agent-client-secret") if cred_type == "CLIENT_SECRET" else None, "status": "ACTIVE"})
        return {"agent_id": generated_agent_id, "status": status, "owner_principal_id": row["owner_principal_id"], "sponsor_principal_id": row["sponsor_principal_id"], "responsible_group_id": row.get("responsible_group_id"), "credential_type": cred_type, "credential": secret if cred_type == "CLIENT_SECRET" else None, "security_domain_id": row.get("security_domain_id"), "environment": environment or row.get("grant_environment"), "runtime": runtime or row.get("grant_runtime")}

    result = connection.execute_transaction_callback(work)
    _audit(result["owner_principal_id"], "AGENT_ENROLLMENT_REDEEM", "AGENT", result["agent_id"], "ALLOW", "one-time token consumed")
    return result


def list_enrollment_grants(principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "agents.read")
    if effective_access(principal_id, "agents.read.all")["decision"] == "ALLOW":
        return _required_query(
            "SELECT GRANT_ID, SPONSOR_PRINCIPAL_ID, OWNER_PRINCIPAL_ID, RESPONSIBLE_GROUP_ID, SECURITY_DOMAIN_ID, "
            "ENVIRONMENT, RUNTIME, AGENT_NAME, RISK_TIER, STATUS, EXPIRES_AT, MAX_USES, USED_COUNT, CREATED_AT "
            "FROM CX_ENROLLMENT_GRANTS ORDER BY CREATED_AT DESC " + _limit_clause(),
            {"limit": max(1, min(int(limit), 500))},
        )
    return _required_query(
        "SELECT GRANT_ID, SPONSOR_PRINCIPAL_ID, OWNER_PRINCIPAL_ID, RESPONSIBLE_GROUP_ID, SECURITY_DOMAIN_ID, "
        "ENVIRONMENT, RUNTIME, AGENT_NAME, RISK_TIER, STATUS, EXPIRES_AT, MAX_USES, USED_COUNT, CREATED_AT "
        "FROM CX_ENROLLMENT_GRANTS WHERE SPONSOR_PRINCIPAL_ID = :principal_id OR OWNER_PRINCIPAL_ID = :principal_id "
        "ORDER BY CREATED_AT DESC " + _limit_clause(),
        {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
    )


def list_agents(principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List logical Agents through ownership relationships, without secrets."""
    _require(principal_id, "agents.read")
    # Resolve the global administrator path before building delegated-scope
    # SQL. Some upgraded databases intentionally have no organization/domain
    # memberships yet; an ALL-scoped administrator must not depend on them.
    if effective_access(principal_id, "agents.read.all")["decision"] == "ALLOW":
        return _required_query(
            "SELECT p.PRINCIPAL_ID AS AGENT_ID, p.STATUS, p.CREATED_AT, p.UPDATED_AT, "
            "MIN(r.RELATIONSHIP_ROLE) AS RELATIONSHIP_ROLE, MIN(r.PRINCIPAL_ID) AS RELATED_PRINCIPAL_ID "
            "FROM CX_PRINCIPALS p LEFT JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID = p.PRINCIPAL_ID "
            "WHERE p.PRINCIPAL_TYPE = 'AGENT' "
            "GROUP BY p.PRINCIPAL_ID, p.STATUS, p.CREATED_AT, p.UPDATED_AT "
            "ORDER BY p.UPDATED_AT DESC " + _limit_clause(),
            {"limit": max(1, min(int(limit), 500))},
        )
    visibility = _agent_visibility_clause(principal_id)
    return _required_query(
        "SELECT p.PRINCIPAL_ID AS AGENT_ID, p.STATUS, p.CREATED_AT, p.UPDATED_AT, "
        "MIN(r.RELATIONSHIP_ROLE) AS RELATIONSHIP_ROLE, MIN(r.PRINCIPAL_ID) AS RELATED_PRINCIPAL_ID "
        "FROM CX_PRINCIPALS p JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID = p.PRINCIPAL_ID "
        "WHERE p.PRINCIPAL_TYPE = 'AGENT' AND r.STATUS = 'ACTIVE' AND " + visibility + " "
        "GROUP BY p.PRINCIPAL_ID, p.STATUS, p.CREATED_AT, p.UPDATED_AT "
        "ORDER BY p.UPDATED_AT DESC " + _limit_clause(),
        {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
    )


def list_agents_cursor(principal_id: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    """Return a keyset page of Agents without widening ownership scope."""
    _require(principal_id, "agents.read")
    context = cursor_pagination.resolve(principal_id, "agents", {}, "agent_id:asc", page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "agents", "sort_key": "agent_id:asc"})
    after = str(context["position"].get("agent_id") or "")
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after_clause = " AND p.PRINCIPAL_ID>:after" if after else ""
    if after:
        params["after"] = after
    if effective_access(principal_id, "agents.read.all")["decision"] == "ALLOW":
        sql = (
            "SELECT p.PRINCIPAL_ID AS AGENT_ID,p.STATUS,p.CREATED_AT,p.UPDATED_AT,MIN(r.RELATIONSHIP_ROLE) AS RELATIONSHIP_ROLE,"
            "MIN(r.PRINCIPAL_ID) AS RELATED_PRINCIPAL_ID FROM CX_PRINCIPALS p LEFT JOIN CX_AGENT_RELATIONSHIPS r "
            "ON r.AGENT_ID=p.PRINCIPAL_ID WHERE p.PRINCIPAL_TYPE='AGENT'" + after_clause + " "
            "GROUP BY p.PRINCIPAL_ID,p.STATUS,p.CREATED_AT,p.UPDATED_AT ORDER BY p.PRINCIPAL_ID " + _limit_clause()
        )
    else:
        visibility = _agent_visibility_clause(principal_id)
        params["principal_id"] = principal_id
        sql = (
            "SELECT p.PRINCIPAL_ID AS AGENT_ID,p.STATUS,p.CREATED_AT,p.UPDATED_AT,MIN(r.RELATIONSHIP_ROLE) AS RELATIONSHIP_ROLE,"
            "MIN(r.PRINCIPAL_ID) AS RELATED_PRINCIPAL_ID FROM CX_PRINCIPALS p JOIN CX_AGENT_RELATIONSHIPS r "
            "ON r.AGENT_ID=p.PRINCIPAL_ID WHERE p.PRINCIPAL_TYPE='AGENT' AND r.STATUS='ACTIVE' AND " + visibility +
            after_clause + " GROUP BY p.PRINCIPAL_ID,p.STATUS,p.CREATED_AT,p.UPDATED_AT ORDER BY p.PRINCIPAL_ID " + _limit_clause()
        )
    rows = _required_query(sql, params)
    result = cursor_pagination.page(rows, context, lambda item: {"agent_id": str(item["agent_id"])})
    count_params: Dict[str, Any] = {}
    try:
        if effective_access(principal_id, "agents.read.all")["decision"] == "ALLOW":
            total = _row(connection.execute_query_one(
                "SELECT COUNT(*) AS CNT FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_TYPE='AGENT'", count_params,
            ))
        else:
            visibility = _agent_visibility_clause(principal_id)
            count_params["principal_id"] = principal_id
            total = _row(connection.execute_query_one(
                "SELECT COUNT(DISTINCT p.PRINCIPAL_ID) AS CNT FROM CX_PRINCIPALS p JOIN CX_AGENT_RELATIONSHIPS r "
                "ON r.AGENT_ID=p.PRINCIPAL_ID WHERE p.PRINCIPAL_TYPE='AGENT' AND r.STATUS='ACTIVE' AND " + visibility,
                count_params,
            ))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def _agent_visible_to(actor_principal_id: str, agent_id: str) -> bool:
    """Check an Agent relationship or organization scope server-side."""
    if effective_access(actor_principal_id, "agents.read.all")["decision"] == "ALLOW":
        return True
    row = _row(connection.execute_query_one(
        "SELECT 1 FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_ID = :agent_id "
        "AND p.PRINCIPAL_TYPE = 'AGENT' AND " + _agent_visibility_clause(actor_principal_id),
        {"agent_id": agent_id, "principal_id": actor_principal_id},
    ))
    return bool(row)


def set_agent_status(actor_principal_id: str, agent_id: str, status: str, reason: str) -> bool:
    if not reason.strip():
        raise IdentityError("Agent status reason is required")
    target = str(status or "").upper()
    if target not in {"ACTIVE", "PENDING_ACTIVATION", "DISABLED", "QUARANTINED", "OWNER_TRANSFER_REQUIRED"}:
        raise IdentityError("Agent status is invalid")
    access = effective_access(actor_principal_id, "agents.manage")
    related = _row(connection.execute_query_one(
        "SELECT AGENT_ID FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID = :agent_id "
        "AND PRINCIPAL_ID = :principal_id AND RELATIONSHIP_ROLE IN ('PRIMARY_OWNER','OPERATOR') AND STATUS = 'ACTIVE'",
        {"agent_id": agent_id, "principal_id": actor_principal_id},
    ))
    if access["decision"] != "ALLOW" and not related:
        raise PermissionError("Agent status change denied")
    if (
        access["decision"] == "ALLOW"
        and effective_access(actor_principal_id, "agents.manage.all")["decision"] != "ALLOW"
        and not _agent_visible_to(actor_principal_id, agent_id)
        and not related
    ):
        raise PermissionError("Agent is outside the delegated scope")
    def _commit(tx: Any) -> bool:
        # Lock the logical Agent before changing its status.  The status,
        # fencing, credential/token revocation, delivery recovery, derived
        # object invalidation, and audit event must have one commit outcome.
        agent = _row(tx.query_one(
            "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS "
            "WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT' FOR UPDATE",
            {"agent_id": agent_id},
        ))
        if not agent:
            return False
        if target == "ACTIVE" and str(agent.get("status") or "").upper() != "ACTIVE":
            activation = _row(tx.query_one(
                "SELECT ACTIVATION_ID FROM CX_AGENT_ACTIVATIONS WHERE AGENT_ID = :agent_id "
                "AND STATUS = 'ACTIVE' FOR UPDATE",
                {"agent_id": agent_id},
            ))
            if not activation:
                raise IdentityError("Agent activation evidence is required")
        related_tx = _row(tx.query_one(
            "SELECT RELATIONSHIP_ID FROM CX_AGENT_RELATIONSHIPS "
            "WHERE AGENT_ID = :agent_id AND PRINCIPAL_ID = :principal_id "
            "AND RELATIONSHIP_ROLE IN ('PRIMARY_OWNER','OPERATOR') AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id, "principal_id": actor_principal_id},
        ))
        if access["decision"] != "ALLOW" and not related_tx:
            raise PermissionError("Agent status change denied")
        changed = tx.execute(
            "UPDATE CX_PRINCIPALS SET STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT'",
            {"status": target, "agent_id": agent_id},
        ) > 0
        if not changed:
            return False
        # Confirmation advances to activation pending.  The registered proof
        # credential remains present for the activation handshake, while the
        # non-ACTIVE Principal still prevents ordinary Gateway use.
        if target not in {"ACTIVE", "PENDING_ACTIVATION"}:
            instance_status = "QUARANTINED" if target == "QUARANTINED" else "REVOKED"
            tx.execute(
                "UPDATE CX_AGENT_INSTANCES SET STATUS = :instance_status, REVOKED_AT = CURRENT_TIMESTAMP, "
                "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
                {"instance_status": instance_status, "agent_id": agent_id, "reason": reason[:1000]},
            )
            tx.execute(
                "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND REVOKED_AT IS NULL",
                {"agent_id": agent_id},
            )
            tx.execute(
                "UPDATE CX_AGENT_CREDENTIALS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
                {"agent_id": agent_id},
            )
            tx.execute(
                "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
                "REVOKE_REASON = :reason WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
                {"agent_id": agent_id, "reason": reason[:2000]},
            )
            tx.execute(
                "UPDATE CX_AGENT_DELIVERIES SET STATUS = 'PENDING', CLAIMED_BY = NULL, "
                "CLAIM_TOKEN_DIGEST = NULL, CLAIMED_AT = NULL, VISIBILITY_UNTIL = NULL, "
                "FENCING_TOKEN = NULL, FAILURE_REASON = :reason, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND STATUS = 'CLAIMED'",
                {"agent_id": agent_id, "reason": reason[:2000]},
            )
        _audit_tx(tx, actor_principal_id, "AGENT_STATUS_" + target, "AGENT", agent_id, "ALLOW", reason)
        return True

    return bool(connection.execute_transaction_callback(_commit))


def _bool_column(value: Any) -> bool:
    return value is True or str(value or "").strip().upper() in {"Y", "YES", "TRUE", "1", "T"}


def _hold_value(enabled: bool) -> Any:
    return bool(enabled) if _dialect() in {"postgresql", "pg"} else ("Y" if enabled else "N")


def _channel_reference_count(channel_id: str) -> int:
    """Count durable references before a destructive lifecycle transition."""
    total = 0
    for table, column in (
        ("CX_CHANNEL_MESSAGES", "CHANNEL_ID"),
        ("CX_CHANNEL_THREADS", "CHANNEL_ID"),
        ("CX_BARRIERS", "CHANNEL_ID"),
        ("CX_ACTION_CARDS", "CHANNEL_ID"),
        ("CX_AGENT_INSTANCES", "CHANNEL_ID"),
        ("CX_BRIDGES", "CHANNEL_ID"),
        ("CX_CHANNEL_MEMORY_CANDIDATES", "CHANNEL_ID"),
        ("CX_AGENT_DELIVERIES", "CHANNEL_ID"),
    ):
        try:
            extra = ""
            if table in {"CX_CHANNEL_MESSAGES", "CX_CHANNEL_THREADS"}:
                extra = " AND STATUS <> 'DELETED'" if table == "CX_CHANNEL_THREADS" else " AND REDACTED_AT IS NULL"
            elif table == "CX_AGENT_INSTANCES":
                extra = " AND STATUS = 'ACTIVE' AND LEASE_EXPIRES_AT > CURRENT_TIMESTAMP"
            elif table == "CX_BRIDGES":
                extra = " AND STATUS IN ('PENDING','APPROVED')"
            elif table == "CX_CHANNEL_MEMORY_CANDIDATES":
                extra = " AND STATUS IN ('PROPOSED','APPROVED','QUARANTINED')"
            elif table == "CX_AGENT_DELIVERIES":
                extra = " AND STATUS IN ('PENDING','CLAIMED','FAILED')"
            row = _row(connection.execute_query_one(
                f"SELECT COUNT(*) AS CNT FROM {table} WHERE {column} = :channel_id" + extra,
                {"channel_id": channel_id},
            )) or {}
            total += int(row.get("cnt") or 0)
        except Exception:
            # A missing optional reference table is not a reason to permit
            # deletion.  Treat an unavailable reference check as one ref.
            total += 1
    return total


def transition_channel_lifecycle(
    actor_principal_id: str,
    channel_id: str,
    target_status: str,
    reason: str,
    *,
    deletion_after: Any = None,
) -> Dict[str, Any]:
    """Apply a governed Channel lifecycle transition and its runtime effects."""
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION":
        raise PermissionError("protected Platform Administration Channel lifecycle is managed by the administration service")
    _require(actor_principal_id, "channels.lifecycle")
    row = _row(connection.execute_query_one(
        "SELECT CHANNEL_ID, STATUS, LEGAL_HOLD, RETENTION_UNTIL, DELETION_AFTER, SECURITY_DOMAIN_ID, METADATA_JSON "
        "FROM CX_CHANNELS WHERE CHANNEL_ID = :channel_id",
        {"channel_id": channel_id},
    ))
    if not row:
        raise IdentityError("Channel not found")
    if effective_access(actor_principal_id, "domains.manage")["decision"] != "ALLOW":
        _assert_channel_member(actor_principal_id, channel_id, "channels.lifecycle")
    hold = _bool_column(row.get("legal_hold"))
    deadline = (
        _timestamp(deletion_after) if deletion_after is not None
        else _timestamp(row.get("deletion_after")) or _timestamp(row.get("retention_until"))
    )
    if str(target_status or "").upper() == "DELETION_PENDING" and deadline is None:
        deadline = _now() + timedelta(days=7)
    reference_count = _channel_reference_count(channel_id)
    active_work = bool(_row(connection.execute_query_one(
        "SELECT 1 FROM CX_AGENT_INSTANCES WHERE CHANNEL_ID = :channel_id "
        "AND STATUS = 'ACTIVE' AND LEASE_EXPIRES_AT > CURRENT_TIMESTAMP",
        {"channel_id": channel_id},
    )))
    requested_status = str(target_status or "").upper()
    decision = governed_contracts.validate_channel_transition(
        str(row.get("status") or ""), target_status, legal_hold=hold,
        referenced_objects=reference_count,
        deletion_after=deadline, reason=reason, authorized=True,
        active_work=active_work, quiesced=not active_work,
        retention_expired=bool(deadline is not None and _now() >= deadline),
        deletion_approved=(requested_status == "DELETED" and effective_access(actor_principal_id, "channels.delete")["decision"] == "ALLOW"),
        now=_now(),
        recovery_authorized=effective_access(actor_principal_id, "channels.quarantine")["decision"] == "ALLOW",
        investigation_authorized=effective_access(actor_principal_id, "security.read")["decision"] == "ALLOW",
    )
    params = {
        "channel_id": channel_id, "status": decision["target"],
        "retention_until": deadline, "reason": reason[:2000],
    }
    # Metadata JSON remains portable and records the latest state reason even
    # on databases where no vendor JSON operators are available.
    connection.execute(
        "UPDATE CX_CHANNELS SET STATUS = :status, RETENTION_UNTIL = COALESCE(:retention_until, RETENTION_UNTIL), "
        "DELETION_AFTER = COALESCE(:retention_until, DELETION_AFTER), LIFECYCLE_REASON = :reason, "
        "QUARANTINED_AT = CASE WHEN :status = 'QUARANTINED' THEN CURRENT_TIMESTAMP ELSE QUARANTINED_AT END, "
        "METADATA_JSON = :metadata_json, UPDATED_AT = CURRENT_TIMESTAMP WHERE CHANNEL_ID = :channel_id",
        {**params, "metadata_json": _merge_metadata(
            row.get("metadata_json"),
            {"lifecycle_reason": reason[:2000], "target": decision["target"]},
        )},
    )
    if decision["effects"]["revoke_temporary_access"]:
        connection.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANNEL_ID = :channel_id AND STATUS = 'ACTIVE'",
            {"channel_id": channel_id, "reason": reason[:1000]},
        )
        connection.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE INSTANCE_ID IN (SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE CHANNEL_ID = :channel_id) "
            "AND REVOKED_AT IS NULL", {"channel_id": channel_id},
        )
    if decision["effects"]["block_memory_promotion"]:
        try:
            connection.execute(
                "UPDATE CX_CHANNEL_MEMORY_CANDIDATES SET STATUS = 'QUARANTINED', "
                "REVIEW_REASON = :reason, REVIEWED_AT = CURRENT_TIMESTAMP "
                "WHERE CHANNEL_ID = :channel_id AND STATUS IN ('PROPOSED','APPROVED')",
                {"channel_id": channel_id, "reason": reason[:2000]},
            )
        except Exception:
            pass
    destination = str(decision["target"]).upper()
    if destination in {"FROZEN", "QUARANTINED", "DELETION_PENDING", "DELETED"}:
        # The mutable Channel row is not sufficient for legal or incident
        # review.  Isolation and destructive transitions append an immutable
        # evidence record with the exact decision inputs and effects.
        connection.execute(
            "INSERT INTO CX_CHANNEL_DELETION_EVIDENCE(EVIDENCE_ID, CHANNEL_ID, ACTOR_PRINCIPAL_ID, "
            "FROM_STATUS, TO_STATUS, REFERENCE_COUNT, REASON, DETAIL_JSON) VALUES "
            "(:evidence_id, :channel_id, :actor_principal_id, :from_status, :to_status, "
            ":reference_count, :reason, :detail_json)",
            {
                "evidence_id": _id("CHE"), "channel_id": channel_id,
                "actor_principal_id": actor_principal_id,
                "from_status": str(row.get("status") or "").upper(),
                "to_status": destination, "reference_count": reference_count,
                "reason": reason[:2000], "detail_json": _json({
                    "active_work": active_work,
                    "legal_hold": hold,
                    "retention_until": _iso(deadline),
                    "decision_code": decision.get("code"),
                    "effects": decision.get("effects", {}),
                }),
            },
        )
    _audit(actor_principal_id, "CHANNEL_LIFECYCLE_" + decision["target"], "CHANNEL", channel_id, "ALLOW", reason)
    return {"channel_id": channel_id, **decision, "retention_until": _iso(deadline)}


def set_channel_legal_hold(actor_principal_id: str, channel_id: str, enabled: bool, reason: str) -> Dict[str, Any]:
    """Set or release a Channel hold and its immutable evidence atomically."""
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION":
        raise PermissionError("protected Platform Administration Channel hold is managed by the administration service")
    _require(actor_principal_id, "channels.lifecycle")
    if not str(reason or "").strip():
        raise IdentityError("legal hold reason is required")
    if effective_access(actor_principal_id, "domains.manage")["decision"] != "ALLOW":
        _assert_channel_member(actor_principal_id, channel_id, "channels.lifecycle")
    hold = bool(enabled)

    def _commit(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one(
            "SELECT CHANNEL_ID, STATUS, LEGAL_HOLD, METADATA_JSON FROM CX_CHANNELS "
            "WHERE CHANNEL_ID = :channel_id FOR UPDATE",
            {"channel_id": channel_id},
        ))
        if not row:
            raise IdentityError("Channel not found")
        current_status = str(row.get("status") or "ACTIVE").upper()
        target = "FROZEN" if hold and current_status in {"ACTIVE", "READ_ONLY", "ARCHIVED"} else current_status
        changed = tx.execute(
            "UPDATE CX_CHANNELS SET LEGAL_HOLD = :legal_hold, STATUS = :status, "
            "LIFECYCLE_REASON = :reason, METADATA_JSON = :metadata_json, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE CHANNEL_ID = :channel_id",
            {"legal_hold": _hold_value(hold), "status": target, "channel_id": channel_id,
             "reason": reason[:2000], "metadata_json": _merge_metadata(
                 row.get("metadata_json"),
                 {"legal_hold_reason": reason[:2000], "enabled": hold},
             )},
        )
        if changed != 1:
            raise IdentityError("Channel hold changed concurrently")
        # A hold/release is itself a preservation decision.  It must not be
        # possible for the mutable Channel row to commit while its evidence
        # insert is lost on a second connection.
        tx.execute(
            "INSERT INTO CX_CHANNEL_DELETION_EVIDENCE(EVIDENCE_ID, CHANNEL_ID, ACTOR_PRINCIPAL_ID, "
            "FROM_STATUS, TO_STATUS, REFERENCE_COUNT, REASON, DETAIL_JSON) VALUES "
            "(:evidence_id, :channel_id, :actor_principal_id, :from_status, :to_status, 0, :reason, :detail_json)",
            {"evidence_id": _id("CHE"), "channel_id": channel_id,
             "actor_principal_id": actor_principal_id, "from_status": current_status,
             "to_status": target, "reason": reason[:2000], "detail_json": _json({
                 "event": "LEGAL_HOLD_SET" if hold else "LEGAL_HOLD_RELEASE",
                 "legal_hold": hold,
             })},
        )
        _audit_tx(
            tx, actor_principal_id,
            "CHANNEL_LEGAL_HOLD_" + ("SET" if hold else "RELEASE"),
            "CHANNEL", channel_id, "ALLOW", reason,
        )
        return {"channel_id": channel_id, "legal_hold": hold, "status": target}

    return connection.execute_transaction_callback(_commit)


def create_bridge(
    actor_principal_id: str,
    source_domain_id: str,
    target_domain_id: str,
    mode: str,
    classification: str,
    recipients: List[str],
    purpose: str,
    reason: str,
    *,
    expires_at: Any = None,
    full_copy_enabled: bool = False,
) -> Dict[str, Any]:
    """Create a pending cross-domain Bridge; content is unavailable until approval."""
    _require(actor_principal_id, "channels.bridge")
    source = _row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID, CLASSIFICATION FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = :domain AND STATUS = 'ACTIVE'", {"domain": source_domain_id},
    ))
    target = _row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID, CLASSIFICATION FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = :domain AND STATUS = 'ACTIVE'", {"domain": target_domain_id},
    ))
    if not source or not target:
        raise IdentityError("Bridge Security Domain is unavailable")
    expiry = _timestamp(expires_at) if expires_at is not None else (_now() + timedelta(hours=24))
    decision = governed_contracts.validate_bridge_request(
        source_domain_id, target_domain_id, mode, classification,
        target_minimum=target.get("classification") or "PUBLIC",
        full_copy_enabled=full_copy_enabled, recipients=recipients,
        purpose=purpose, reason=reason, expires_at=expiry,
    )
    bridge_id = _id("BR")
    connection.execute(
        "INSERT INTO CX_BRIDGES(BRIDGE_ID, SOURCE_DOMAIN_ID, TARGET_DOMAIN_ID, TRANSFER_MODE, PURPOSE, "
        "CLASSIFICATION, RECIPIENT_SNAPSHOT, STATUS, EXPIRES_AT, CREATED_BY) "
        "VALUES (:bridge_id, :source_domain, :target_domain, :transfer_mode, :purpose, :classification, "
        ":recipients, 'PENDING', :expires_at, :created_by)",
        {"bridge_id": bridge_id, "source_domain": source_domain_id, "target_domain": target_domain_id,
         "transfer_mode": decision["transfer_mode"], "purpose": decision["purpose"],
         "classification": decision["classification"], "recipients": _json(list(decision["recipients"])),
         "expires_at": expiry, "created_by": actor_principal_id},
    )
    _audit(actor_principal_id, "BRIDGE_CREATE", "BRIDGE", bridge_id, "PENDING", reason)
    return {"bridge_id": bridge_id, "status": "PENDING", **decision}


def approve_bridge(actor_principal_id: str, bridge_id: str, reason: str) -> bool:
    _require(actor_principal_id, "channels.bridge")
    if not str(reason or "").strip():
        raise IdentityError("Bridge approval reason is required")
    def _commit(tx: Any) -> bool:
        row = _row(tx.query_one(
            "SELECT CREATED_BY, STATUS, EXPIRES_AT FROM CX_BRIDGES "
            "WHERE BRIDGE_ID = :bridge_id FOR UPDATE", {"bridge_id": bridge_id},
        ))
        if not row or str(row.get("status") or "").upper() != "PENDING":
            return False
        if str(row.get("created_by") or "") == actor_principal_id:
            raise PermissionError("Bridge proposer cannot approve its own transfer")
        expiry = _timestamp(row.get("expires_at"))
        if expiry is None or expiry <= _now():
            raise IdentityError("Bridge has expired")
        changed = tx.execute(
            "UPDATE CX_BRIDGES SET STATUS = 'APPROVED', APPROVED_BY = :approved_by, APPROVAL_REASON = :reason "
            "WHERE BRIDGE_ID = :bridge_id AND STATUS = 'PENDING' AND EXPIRES_AT > CURRENT_TIMESTAMP",
            {"approved_by": actor_principal_id, "reason": reason[:2000], "bridge_id": bridge_id},
        ) > 0
        if changed:
            _audit_tx(tx, actor_principal_id, "BRIDGE_APPROVE", "BRIDGE", bridge_id, "ALLOW", reason)
        return changed

    return bool(connection.execute_transaction_callback(_commit))


def create_bridge_transfer(
    actor_principal_id: str,
    bridge_id: str,
    source_object_type: str,
    source_object_id: str,
    reason: str,
    *,
    payload_digest: str = "",
    target_object_id: str = "",
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """Record a transfer request; a pending row never exposes source content."""
    _require(actor_principal_id, "channels.bridge")
    if not str(reason or "").strip():
        raise IdentityError("Bridge transfer reason is required")
    domain_admin = effective_access(actor_principal_id, "domains.manage")["decision"] == "ALLOW"
    transfer_id = _id("BT")

    def _commit(tx: Any) -> Dict[str, Any]:
        bridge = _row(tx.query_one(
            "SELECT BRIDGE_ID, SOURCE_DOMAIN_ID, TARGET_DOMAIN_ID, TRANSFER_MODE, CLASSIFICATION, STATUS, EXPIRES_AT "
            "FROM CX_BRIDGES WHERE BRIDGE_ID = :bridge_id FOR UPDATE", {"bridge_id": bridge_id},
        ))
        if not bridge or str(bridge.get("status") or "").upper() != "APPROVED":
            raise PermissionError("Bridge is not approved")
        domain_membership = _row(tx.query_one(
            "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID = :security_domain_id "
            "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"security_domain_id": bridge.get("source_domain_id"), "principal_id": actor_principal_id},
        ))
        if not domain_membership and not domain_admin:
            raise PermissionError("Bridge source domain access denied")
        expiry = _timestamp(bridge.get("expires_at"))
        if expiry is None or expiry <= _now():
            raise IdentityError("Bridge has expired")
        if idempotency_key:
            existing = _row(tx.query_one(
                "SELECT TRANSFER_ID, STATUS FROM CX_BRIDGE_TRANSFERS WHERE BRIDGE_ID = :bridge_id "
                "AND IDEMPOTENCY_KEY = :idempotency_key FOR UPDATE",
                {"bridge_id": bridge_id, "idempotency_key": idempotency_key[:256]},
            ))
            if existing:
                return {"transfer_id": existing.get("transfer_id"), "bridge_id": bridge_id,
                        "status": existing.get("status"), "idempotent": True}
        tx.execute(
            "INSERT INTO CX_BRIDGE_TRANSFERS(TRANSFER_ID, BRIDGE_ID, SOURCE_OBJECT_TYPE, SOURCE_OBJECT_ID, "
            "TARGET_OBJECT_ID, PAYLOAD_DIGEST, IDEMPOTENCY_KEY, SOURCE_CLASSIFICATION, STATUS, CREATED_BY, REASON) VALUES "
            "(:transfer_id, :bridge_id, :object_type, :object_id, :target_object_id, :payload_digest, "
            ":idempotency_key, :source_classification, 'PENDING', :created_by, :reason)",
            {"transfer_id": transfer_id, "bridge_id": bridge_id, "object_type": str(source_object_type)[:64],
             "object_id": str(source_object_id)[:128], "target_object_id": target_object_id or None,
             "payload_digest": payload_digest[:128] or None, "source_classification": bridge.get("classification") or "INTERNAL",
             "created_by": actor_principal_id,
             "idempotency_key": idempotency_key[:256] or None, "reason": reason[:2000]},
        )
        _audit_tx(tx, actor_principal_id, "BRIDGE_TRANSFER_PROPOSE", "BRIDGE_TRANSFER", transfer_id, "PENDING", reason)
        return {"transfer_id": transfer_id, "bridge_id": bridge_id, "status": "PENDING",
                "transfer_mode": bridge.get("transfer_mode"), "idempotent": False}

    return connection.execute_transaction_callback(_commit)


def list_bridges(actor_principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    _require(actor_principal_id, "channels.bridge")
    return _required_query(
        "SELECT BRIDGE_ID, SOURCE_DOMAIN_ID, TARGET_DOMAIN_ID, CHANNEL_ID, TRANSFER_MODE, PURPOSE, CLASSIFICATION, "
        "RECIPIENT_SNAPSHOT, STATUS, EXPIRES_AT, APPROVED_BY, APPROVAL_REASON, POLICY_VERSION, CREATED_BY, CREATED_AT "
        "FROM CX_BRIDGES WHERE CREATED_BY = :actor OR APPROVED_BY = :actor ORDER BY CREATED_AT DESC "
        + _limit_clause(), {"actor": actor_principal_id, "limit": max(1, min(int(limit), 500))},
    )


def enqueue_notification(
    principal_id: str, notification_type: str, level: str, dedupe_key: str,
    payload: Optional[Dict[str, Any]] = None, deadline_at: Any = None,
) -> Dict[str, Any]:
    normalized = governed_contracts.build_notification(
        principal_id, notification_type, level, dedupe_key, payload, deadline_at=deadline_at,
    )
    existing = _row(connection.execute_query_one(
        "SELECT NOTIFICATION_ID, ACKNOWLEDGED_AT, DEADLINE_AT FROM CX_NOTIFICATIONS "
        "WHERE PRINCIPAL_ID = :principal_id AND DEDUPE_KEY = :dedupe_key",
        {"principal_id": principal_id, "dedupe_key": normalized["dedupe_key"]},
    ))
    if existing:
        return {**normalized, "notification_id": existing.get("notification_id"), "idempotent": True}
    notification_id = _id("NT")
    encoded = {"level": normalized["level"], "required_action": normalized["required_action"], **normalized["payload"]}
    connection.execute(
        "INSERT INTO CX_NOTIFICATIONS(NOTIFICATION_ID, PRINCIPAL_ID, NOTIFICATION_TYPE, DEDUPE_KEY, "
        "PAYLOAD_JSON, NOTIFICATION_LEVEL, DEADLINE_AT) VALUES (:notification_id, :principal_id, :notification_type, "
        ":dedupe_key, :payload, :level, :deadline_at)",
        {"notification_id": notification_id, "principal_id": principal_id,
         "notification_type": normalized["notification_type"], "dedupe_key": normalized["dedupe_key"],
         "payload": _json(encoded), "level": normalized["level"], "deadline_at": deadline_at},
    )
    return {**normalized, "notification_id": notification_id, "idempotent": False}


def list_notifications(principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "notifications.read")
    rows = _required_query(
        "SELECT NOTIFICATION_ID, NOTIFICATION_TYPE, DEDUPE_KEY, PAYLOAD_JSON, NOTIFICATION_LEVEL, "
        "ACKNOWLEDGED_AT, ACKNOWLEDGED_BY, ESCALATED_AT, DEADLINE_AT, CREATED_AT "
        "FROM CX_NOTIFICATIONS WHERE PRINCIPAL_ID = :principal_id "
        "ORDER BY CREATED_AT DESC " + _limit_clause(),
        {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
    )
    for row in rows:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        row["level"] = row.get("notification_level") or payload.pop("level", "INFO")
        row["required_action"] = bool(payload.pop("required_action", False))
        row["payload"] = payload
    return rows


def acknowledge_notification(principal_id: str, notification_id: str) -> bool:
    _require(principal_id, "notifications.read")
    changed = connection.execute(
        "UPDATE CX_NOTIFICATIONS SET ACKNOWLEDGED_AT = CURRENT_TIMESTAMP, ACKNOWLEDGED_BY = :principal_id "
        "WHERE NOTIFICATION_ID = :notification_id AND PRINCIPAL_ID = :principal_id "
        "AND ACKNOWLEDGED_AT IS NULL",
        {"notification_id": notification_id, "principal_id": principal_id},
    ) > 0
    if changed:
        _audit(principal_id, "NOTIFICATION_ACK", "NOTIFICATION", notification_id, "ALLOW", "acknowledged")
    return changed


def propose_memory_candidate(
    principal_id: str, channel_id: str, content: Dict[str, Any], classification: str,
    destination_scope: str, purpose: str,
) -> Dict[str, Any]:
    """Persist a review-gated memory candidate; no broader retrieval is written."""
    channel = _assert_channel_member(principal_id, channel_id, "channels.write")
    classification = _classification(classification)
    if not _classification_meets_minimum(classification, channel.get("classification") or "INTERNAL"):
        raise IdentityError("candidate classification is below the Channel classification")
    if not str(purpose or "").strip():
        raise IdentityError("memory promotion purpose is required")
    candidate_id = _id("MC")
    connection.execute(
        "INSERT INTO CX_CHANNEL_MEMORY_CANDIDATES(CANDIDATE_ID, CHANNEL_ID, SECURITY_DOMAIN_ID, PROPOSED_BY, "
        "CONTENT_JSON, CLASSIFICATION, DESTINATION_SCOPE, PROVENANCE_JSON, STATUS) VALUES "
        "(:candidate_id, :channel_id, :domain, :proposed_by, :content, :classification, :scope, :provenance, 'PROPOSED')",
        {"candidate_id": candidate_id, "channel_id": channel_id, "domain": channel.get("security_domain_id"),
         "proposed_by": principal_id, "content": _json(content), "classification": classification,
         "scope": str(destination_scope or "CHANNEL")[:32],
         "provenance": _json({"source_channel_id": channel_id, "source_principal_id": principal_id, "purpose": purpose[:2000]})},
    )
    _audit(principal_id, "MEMORY_CANDIDATE_PROPOSE", "MEMORY_CANDIDATE", candidate_id, "PENDING", purpose)
    return {"candidate_id": candidate_id, "status": "PROPOSED", "channel_id": channel_id, "classification": classification}


def review_memory_candidate(principal_id: str, candidate_id: str, decision: str, reason: str) -> bool:
    _require(principal_id, "memory.review")
    if not str(reason or "").strip():
        raise IdentityError("memory review reason is required")
    row = _row(connection.execute_query_one(
        "SELECT PROPOSED_BY, STATUS FROM CX_CHANNEL_MEMORY_CANDIDATES WHERE CANDIDATE_ID = :candidate_id",
        {"candidate_id": candidate_id},
    ))
    if not row or str(row.get("status") or "").upper() != "PROPOSED":
        return False
    if row.get("proposed_by") == principal_id:
        raise PermissionError("memory proposer cannot approve its own candidate")
    target = "APPROVED" if str(decision or "").upper() in {"APPROVE", "APPROVED"} else "REJECTED"
    changed = connection.execute(
        "UPDATE CX_CHANNEL_MEMORY_CANDIDATES SET STATUS = :status, REVIEWED_BY = :reviewed_by, "
        "REVIEW_REASON = :reason, REVIEWED_AT = CURRENT_TIMESTAMP WHERE CANDIDATE_ID = :candidate_id AND STATUS = 'PROPOSED'",
        {"status": target, "reviewed_by": principal_id, "reason": reason[:2000], "candidate_id": candidate_id},
    ) > 0
    if changed:
        _audit(principal_id, "MEMORY_CANDIDATE_" + target, "MEMORY_CANDIDATE", candidate_id, "ALLOW", reason)
    return changed


def transfer_agent_owner(actor_principal_id: str, agent_id: str, new_owner_principal_id: str, reason: str) -> Dict[str, Any]:
    _require(actor_principal_id, "agents.transfer")
    if not str(reason or "").strip():
        raise IdentityError("Agent transfer reason is required")
    if not _agent_visible_to(actor_principal_id, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    owner = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :owner",
        {"owner": new_owner_principal_id},
    ))
    if not owner or str(owner.get("principal_type") or "").upper() != "HUMAN" or str(owner.get("status") or "").upper() != "ACTIVE":
        raise IdentityError("New Agent owner is unavailable")
    if not _principal_visible_to(actor_principal_id, new_owner_principal_id) and effective_access(actor_principal_id, "agents.transfer.all")["decision"] != "ALLOW":
        raise PermissionError("New Agent owner is outside the delegated scope")
    flag = True if _dialect() in {"postgresql", "pg"} else "Y"

    def work(tx: Any) -> Dict[str, Any]:
        agent = _row(tx.query_one(
            "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT' FOR UPDATE",
            {"agent_id": agent_id},
        ))
        if not agent or str(agent.get("status") or "").upper() in {"DISABLED", "REVOKED"}:
            raise IdentityError("Agent is unavailable")
        current = _row(tx.query_one(
            "SELECT RELATIONSHIP_ID, PRINCIPAL_ID FROM CX_AGENT_RELATIONSHIPS WHERE AGENT_ID = :agent_id "
            "AND RELATIONSHIP_ROLE = 'PRIMARY_OWNER' AND STATUS = 'ACTIVE' FOR UPDATE",
            {"agent_id": agent_id},
        ))
        old_owner = str(current.get("principal_id") or "") if current else ""
        if old_owner == new_owner_principal_id:
            return {"agent_id": agent_id, "owner_principal_id": new_owner_principal_id, "status": "UNCHANGED"}
        tx.execute(
            "UPDATE CX_AGENT_RELATIONSHIPS SET STATUS = 'ENDED', ENDED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND RELATIONSHIP_ROLE = 'PRIMARY_OWNER' AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id},
        )
        tx.execute(
            "INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID, AGENT_ID, PRINCIPAL_ID, RELATIONSHIP_ROLE, STATUS) "
            "VALUES (:relationship_id, :agent_id, :principal_id, 'PRIMARY_OWNER', 'ACTIVE')",
            {"relationship_id": _id("AR"), "agent_id": agent_id, "principal_id": new_owner_principal_id},
        )
        instances = tx.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id, "reason": reason[:1000]},
        )
        credentials = tx.execute(
            "UPDATE CX_AGENT_CREDENTIALS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id},
        )
        tx.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND REVOKED_AT IS NULL",
            {"agent_id": agent_id},
        )
        deliveries = tx.execute(
            "UPDATE CX_AGENT_DELIVERIES SET STATUS = 'PENDING', CLAIMED_BY = NULL, "
            "CLAIM_TOKEN_DIGEST = NULL, CLAIMED_AT = NULL, VISIBILITY_UNTIL = NULL, "
            "FENCING_TOKEN = NULL, FAILURE_REASON = :reason, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'CLAIMED'",
            {"agent_id": agent_id, "reason": "owner transfer: " + reason[:1900]},
        )
        derived = tx.execute(
            "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
            {"agent_id": agent_id, "reason": reason[:2000]},
        )
        tx.execute(
            "UPDATE CX_ENROLLMENT_GRANTS SET OWNER_PRINCIPAL_ID = :new_owner, STATUS = 'REVOKED' "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'",
            {"new_owner": new_owner_principal_id, "agent_id": agent_id},
        )
        tx.execute(
            "INSERT INTO CX_AGENT_OWNERSHIP_HISTORY(HISTORY_ID, AGENT_ID, OLD_OWNER_PRINCIPAL_ID, NEW_OWNER_PRINCIPAL_ID, ACTOR_PRINCIPAL_ID, POLICY_VERSION, CREDENTIAL_ROTATED, GRANTS_REEVALUATED, REASON) "
            "VALUES (:history_id, :agent_id, :old_owner, :new_owner, :actor, 1, :credential_rotated, :grants_reevaluated, :reason)",
            {"history_id": _id("AOH"), "agent_id": agent_id, "old_owner": old_owner or None,
             "new_owner": new_owner_principal_id, "actor": actor_principal_id,
             "credential_rotated": flag, "grants_reevaluated": flag, "reason": reason[:2000]},
        )
        _audit_tx(
            tx, actor_principal_id, "AGENT_OWNER_TRANSFER", "AGENT", agent_id,
            "ALLOW", reason,
        )
        return {"agent_id": agent_id, "owner_principal_id": new_owner_principal_id,
                "status": "CREDENTIAL_ROTATION_REQUIRED", "old_owner_principal_id": old_owner or None,
                "revoked_instances": int(instances or 0), "revoked_credentials": int(credentials or 0),
                "revoked_derived_objects": int(derived or 0),
                "requeued_claimed_deliveries": int(deliveries or 0),
                "credential_rotation_required": True,
                "requires_reenrollment": True,
                "grants_reevaluated": True}

    result = connection.execute_transaction_callback(work)
    return result


def offboard_agent(actor_principal_id: str, agent_id: str, *, owner_type: str = "HUMAN", has_responsible_group: bool = False, environment: str = "DEVELOPMENT", reason: str) -> Dict[str, Any]:
    _require(actor_principal_id, "agents.offboard")
    if not _agent_visible_to(actor_principal_id, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    disposition = governed_contracts.owner_disposition(
        owner_type=owner_type, has_responsible_group=has_responsible_group,
        agent_environment=environment, evidence=reason,
    )
    target_status = {
        "SUSPEND": "DISABLED", "QUARANTINE": "QUARANTINED", "TRANSFER_REQUIRED": "OWNER_TRANSFER_REQUIRED",
        "SYSTEM_MANAGED": "ACTIVE", "UNCLAIMED": "OWNER_TRANSFER_REQUIRED", "DEMO_ISOLATED": "DISABLED",
    }[disposition["disposition"]]
    flag = True if _dialect() in {"postgresql", "pg"} else "Y"
    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT' FOR UPDATE",
            {"agent_id": agent_id},
        ))
        if not current:
            raise IdentityError("Agent is unavailable")
        tx.execute(
            "UPDATE CX_PRINCIPALS SET STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID = :agent_id AND PRINCIPAL_TYPE = 'AGENT'",
            {"status": target_status, "agent_id": agent_id},
        )
        instances = tx.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, "
            "REVOKE_REASON = :reason, FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'", {"agent_id": agent_id, "reason": reason[:1000]},
        )
        credentials = 0
        if disposition["revoke_credentials"]:
            credentials = tx.execute(
                "UPDATE CX_AGENT_CREDENTIALS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP "
                "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'", {"agent_id": agent_id},
            )
        tx.execute(
            "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND REVOKED_AT IS NULL", {"agent_id": agent_id},
        )
        deliveries = tx.execute(
            "UPDATE CX_AGENT_DELIVERIES SET STATUS = 'PENDING', CLAIMED_BY = NULL, "
            "CLAIM_TOKEN_DIGEST = NULL, CLAIMED_AT = NULL, VISIBILITY_UNTIL = NULL, "
            "FENCING_TOKEN = NULL, FAILURE_REASON = :reason, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'CLAIMED'",
            {"agent_id": agent_id, "reason": "Agent offboarding: " + reason[:1900]},
        )
        derived = tx.execute(
            "UPDATE CX_AGENT_DERIVED_OBJECTS SET STATUS = 'REVOKED', REVOKED_AT = CURRENT_TIMESTAMP, REVOKE_REASON = :reason "
            "WHERE AGENT_ID = :agent_id AND STATUS = 'ACTIVE'", {"agent_id": agent_id, "reason": reason[:2000]},
        )
        tx.execute(
            "INSERT INTO CX_AGENT_OWNERSHIP_HISTORY(HISTORY_ID, AGENT_ID, OLD_OWNER_PRINCIPAL_ID, NEW_OWNER_PRINCIPAL_ID, ACTOR_PRINCIPAL_ID, POLICY_VERSION, CREDENTIAL_ROTATED, GRANTS_REEVALUATED, REASON) "
            "SELECT :history_id, :agent_id, r.PRINCIPAL_ID, NULL, :actor, 1, :credential_rotated, :grants_reevaluated, :reason "
            "FROM CX_AGENT_RELATIONSHIPS r WHERE r.AGENT_ID = :agent_id AND r.RELATIONSHIP_ROLE = 'PRIMARY_OWNER' AND r.STATUS = 'ACTIVE'",
            {"history_id": _id("AOH"), "agent_id": agent_id, "actor": actor_principal_id,
             "credential_rotated": flag if disposition["revoke_credentials"] else (True if _dialect() in {"postgresql", "pg"} else "N"),
             "grants_reevaluated": flag, "reason": reason[:2000]},
        )
        _audit_tx(
            tx, actor_principal_id, "AGENT_OFFBOARD_" + disposition["disposition"],
            "AGENT", agent_id, "ALLOW", reason,
        )
        return {"revoked_instances": int(instances or 0), "revoked_credentials": int(credentials or 0),
                "revoked_derived_objects": int(derived or 0),
                "requeued_claimed_deliveries": int(deliveries or 0),
                "credential_rotation_required": bool(disposition["revoke_credentials"]),
                "requires_reenrollment": bool(disposition["revoke_credentials"]),
                "grants_reevaluated": True}
    result = connection.execute_transaction_callback(work)
    return {"agent_id": agent_id, "status": target_status, **disposition, **result}


def create_channel(principal_id: str, name: str, security_domain_id: str, *, classification: str = "INTERNAL", channel_type: str = "TEAM") -> Dict[str, Any]:
    _require(principal_id, "channels.create")
    if not str(name or "").strip() or not str(security_domain_id or "").strip():
        raise IdentityError("Channel name and security domain are required")
    domain = _row(connection.execute_query_one(
        "SELECT SECURITY_DOMAIN_ID, CLASSIFICATION FROM CX_SECURITY_DOMAINS "
        "WHERE SECURITY_DOMAIN_ID = :security_domain_id AND STATUS = 'ACTIVE'",
        {"security_domain_id": security_domain_id},
    ))
    if not domain:
        raise IdentityError("Security domain is unavailable")
    classification = _classification(classification)
    if not _classification_meets_minimum(classification, domain.get("classification") or "INTERNAL"):
        raise IdentityError("Channel classification is below the Security Domain minimum")
    if effective_access(principal_id, "domains.manage")["decision"] != "ALLOW":
        member = _row(connection.execute_query_one(
            "SELECT PRINCIPAL_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID = :security_domain_id "
            "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"security_domain_id": security_domain_id, "principal_id": principal_id},
        ))
        if not member:
            raise PermissionError("Channel domain access denied")
    channel_id = _id("CH")
    # Keep the explicit Channel-to-Domain relationship in the v4.4.3 binding
    # ledger.  The row is evidence and discoverability metadata; authorization
    # remains based on current domain membership below and never on this row.
    def _create(tx: Any) -> None:
        tx.execute(
            "INSERT INTO CX_CHANNELS(CHANNEL_ID, CHANNEL_NAME, SECURITY_DOMAIN_ID, CLASSIFICATION, CHANNEL_TYPE, CREATED_BY) VALUES (:channel_id, :name, :domain, :classification, :channel_type, :created_by)",
            {"channel_id": channel_id, "name": name[:256], "domain": security_domain_id, "classification": classification, "channel_type": channel_type, "created_by": principal_id},
        )
        tx.execute(
            "INSERT INTO CX_CHANNEL_MEMBERS(MEMBER_ID, CHANNEL_ID, PRINCIPAL_ID, MEMBER_ROLE) VALUES (:member_id, :channel_id, :principal_id, 'OWNER')",
            {"member_id": _id("CM"), "channel_id": channel_id, "principal_id": principal_id},
        )
        tx.execute(
            "INSERT INTO CX_DOMAIN_BINDINGS(BINDING_ID,SECURITY_DOMAIN_ID,BINDING_TYPE,TARGET_ID,STATUS,REASON,CREATED_BY) "
            "VALUES(:binding_id,:domain,'CHANNEL',:channel_id,'ACTIVE','Channel created in selected Security Domain',:created_by)",
            {"binding_id": _id("DB"), "domain": security_domain_id, "channel_id": channel_id, "created_by": principal_id},
        )
    connection.execute_transaction_callback(_create)
    _audit(principal_id, "CHANNEL_CREATE", "CHANNEL", channel_id, "ALLOW", "channel created")
    return {"channel_id": channel_id, "channel_name": name, "security_domain_id": security_domain_id, "classification": classification, "status": "ACTIVE"}


def list_channels(principal_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "channels.read")
    if effective_access(principal_id, "channels.read.all")["decision"] == "ALLOW":
        return _required_query(
            "SELECT c.CHANNEL_ID, c.CHANNEL_NAME, c.SECURITY_DOMAIN_ID, c.CLASSIFICATION, c.CHANNEL_TYPE, c.STATUS, "
            "c.LEGAL_HOLD, c.PINNED, c.RETENTION_UNTIL, c.DELETION_AFTER, c.QUARANTINED_AT, c.UPDATED_AT, "
            "COALESCE(m.MEMBER_ROLE, 'SYSTEM_ADMIN') AS MEMBER_ROLE "
            "FROM CX_CHANNELS c LEFT JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID = c.CHANNEL_ID "
            "AND m.PRINCIPAL_ID = :principal_id AND m.STATUS = 'ACTIVE' "
            "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
            "WHERE c.STATUS <> 'DELETED' ORDER BY " + _channel_pin_order("c") + ", c.UPDATED_AT DESC, c.CHANNEL_ID " + _limit_clause(),
            {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
        )
    return _required_query(
        "SELECT c.CHANNEL_ID, c.CHANNEL_NAME, c.SECURITY_DOMAIN_ID, c.CLASSIFICATION, c.CHANNEL_TYPE, c.STATUS, "
        "c.LEGAL_HOLD, c.PINNED, c.RETENTION_UNTIL, c.DELETION_AFTER, c.QUARANTINED_AT, c.UPDATED_AT, m.MEMBER_ROLE "
        "FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID = c.CHANNEL_ID "
        "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=c.SECURITY_DOMAIN_ID AND dm.PRINCIPAL_ID=m.PRINCIPAL_ID "
        "WHERE m.PRINCIPAL_ID = :principal_id AND m.STATUS = 'ACTIVE' AND c.STATUS <> 'DELETED' "
        "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND dm.STATUS='ACTIVE' AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "ORDER BY " + _channel_pin_order("c") + ", c.UPDATED_AT DESC, c.CHANNEL_ID " + _limit_clause(),
        {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
    )


def list_channels_cursor(principal_id: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    """Return Channels with pinned inboxes first, then latest activity."""
    _require(principal_id, "channels.read")
    sort_key = "pinned:desc/activity:desc/channel_id:asc"
    context = cursor_pagination.resolve(principal_id, "channels", {}, sort_key, page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "channels", "sort_key": sort_key})
    after = str(context["position"].get("channel_id") or "")
    after_activity = str(context["position"].get("activity_key") or "")
    after_pinned = str(context["position"].get("pinned_key") or "")
    params: Dict[str, Any] = {"principal_id": principal_id, "limit": int(context["page_size"]) + 1}
    if after and after_activity and after_pinned:
        activity_expr = _channel_activity_key("c")
        pinned_expr = _channel_pin_order("c")
        after_clause = (
            " AND (" + pinned_expr + "<:after_pinned OR (" + pinned_expr + "=:after_pinned AND ("
            + activity_expr + "<:after_activity OR (" + activity_expr + "=:after_activity AND c.CHANNEL_ID>:after))))"
        )
        params["after"] = after
        params["after_activity"] = after_activity
        params["after_pinned"] = after_pinned
    else:
        after_clause = ""
    activity_expr = _channel_activity_key("c")
    pinned_expr = _channel_pin_order("c")
    common = "SELECT c.CHANNEL_ID,c.CHANNEL_NAME,c.SECURITY_DOMAIN_ID,c.CLASSIFICATION,c.CHANNEL_TYPE,c.STATUS,c.LEGAL_HOLD,c.PINNED,c.UPDATED_AT," + activity_expr + " AS ACTIVITY_KEY," + pinned_expr + " AS PINNED_KEY,"
    all_access = effective_access(principal_id, "channels.read.all")["decision"] == "ALLOW"
    if all_access:
        sql = common + "COALESCE(m.MEMBER_ROLE,'SYSTEM_ADMIN') AS MEMBER_ROLE FROM CX_CHANNELS c LEFT JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID=c.CHANNEL_ID AND m.PRINCIPAL_ID=:principal_id AND m.STATUS='ACTIVE' WHERE c.STATUS<>'DELETED'" + after_clause + " ORDER BY " + pinned_expr + " DESC," + activity_expr + " DESC,c.CHANNEL_ID " + _limit_clause()
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_CHANNELS c WHERE c.STATUS<>'DELETED'"
        count_params: Dict[str, Any] = {}
    else:
        sql = common + "m.MEMBER_ROLE FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID=c.CHANNEL_ID JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=c.SECURITY_DOMAIN_ID AND dm.PRINCIPAL_ID=m.PRINCIPAL_ID WHERE m.PRINCIPAL_ID=:principal_id AND m.STATUS='ACTIVE' AND c.STATUS<>'DELETED' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP) AND dm.STATUS='ACTIVE' AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP)" + after_clause + " ORDER BY " + pinned_expr + " DESC," + activity_expr + " DESC,c.CHANNEL_ID " + _limit_clause()
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID=c.CHANNEL_ID JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=c.SECURITY_DOMAIN_ID AND dm.PRINCIPAL_ID=m.PRINCIPAL_ID WHERE m.PRINCIPAL_ID=:principal_id AND m.STATUS='ACTIVE' AND c.STATUS<>'DELETED' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP) AND dm.STATUS='ACTIVE' AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP)"
        count_params = {"principal_id": principal_id}
    rows = _required_query(sql, params)
    result = cursor_pagination.page(rows, context, lambda item: {
        "channel_id": str(item["channel_id"]),
        "activity_key": str(item.get("activity_key") or ""),
        "pinned_key": str(item.get("pinned_key") or "0"),
    })
    try:
        total = _row(connection.execute_query_one(count_sql, count_params))
        result["total_items"] = int(total.get("cnt") or 0) if total else 0
    except Exception:
        # Cursor pagination remains usable in adapter-less contract tests.
        # The Dashboard omits a total-page indicator until the count is known.
        pass
    return result


def _channel_activity_key(alias: str = "c") -> str:
    """A portable, cursor-safe text key for recency ordering."""
    if _dialect() in {"postgresql", "pg"}:
        return "TO_CHAR(" + alias + ".UPDATED_AT,'YYYYMMDDHH24MISSUS')"
    return "TO_CHAR(" + alias + ".UPDATED_AT,'YYYYMMDDHH24MISSFF6')"


def _channel_pin_order(alias: str = "c") -> str:
    """Return a portable numeric ordering key for globally pinned Channels."""
    if _dialect() in {"postgresql", "pg"}:
        return "CASE WHEN " + alias + ".PINNED THEN 1 ELSE 0 END"
    return "CASE WHEN " + alias + ".PINNED = 'Y' THEN 1 ELSE 0 END"


def set_channel_pinned(actor_principal_id: str, channel_id: str, enabled: bool, reason: str) -> Dict[str, Any]:
    """Set global inbox priority without changing a Channel's activity clock."""
    _require(actor_principal_id, "channels.lifecycle")
    if not str(reason or "").strip():
        raise IdentityError("Channel pinning reason is required")
    if effective_access(actor_principal_id, "domains.manage")["decision"] != "ALLOW":
        _assert_channel_member(actor_principal_id, channel_id, "channels.lifecycle")

    def _commit(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one(
            "SELECT CHANNEL_ID, PINNED FROM CX_CHANNELS WHERE CHANNEL_ID = :channel_id FOR UPDATE",
            {"channel_id": channel_id},
        ))
        if not row:
            raise IdentityError("Channel not found")
        changed = tx.execute(
            "UPDATE CX_CHANNELS SET PINNED = :pinned WHERE CHANNEL_ID = :channel_id",
            {"channel_id": channel_id, "pinned": _hold_value(bool(enabled))},
        )
        if changed != 1:
            raise IdentityError("Channel pinning changed concurrently")
        _audit_tx(
            tx, actor_principal_id, "CHANNEL_PIN_" + ("SET" if enabled else "RELEASE"),
            "CHANNEL", channel_id, "ALLOW", reason,
        )
        return {"channel_id": channel_id, "pinned": bool(enabled)}

    return connection.execute_transaction_callback(_commit)


def list_channel_members(principal_id: str, channel_id: str) -> List[Dict[str, Any]]:
    _assert_channel_member(principal_id, channel_id, "channels.read")
    return _required_query(
        "SELECT m.MEMBER_ID, m.CHANNEL_ID, m.PRINCIPAL_ID, m.MEMBER_ROLE, m.JOINED_AT, "
        "m.VALID_UNTIL, m.STATUS, p.PRINCIPAL_TYPE, p.STATUS AS PRINCIPAL_STATUS, p.DISPLAY_NAME "
        "FROM CX_CHANNEL_MEMBERS m JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = m.PRINCIPAL_ID "
        "WHERE m.CHANNEL_ID = :channel_id AND m.STATUS = 'ACTIVE' "
        "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND p.STATUS = 'ACTIVE' ORDER BY m.JOINED_AT",
        {"channel_id": channel_id},
    )


def _channel_principal_is_member(channel_id: str, principal_id: str) -> bool:
    """Check another participant without bypassing an Agent's RLS boundary."""
    current_agent = getattr(connection, "get_current_agent_id", lambda: None)()
    if _dialect() in {"postgresql", "pg"} and current_agent:
        row = _row(connection.execute_query_one(
            "SELECT public.cx_channel_principal_member(:channel_id, :principal_id) AS ALLOWED",
            {"channel_id": channel_id, "principal_id": principal_id},
        ))
        return bool(row and row.get("allowed"))
    return bool(_row(connection.execute_query_one(
        "SELECT MEMBER_ID FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID = :channel_id "
        "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"channel_id": channel_id, "principal_id": principal_id},
    )))


def _channel_principal_type(channel_id: str, principal_id: str) -> Optional[str]:
    """Return only the participant type exposed by the controlled PG check."""
    current_agent = getattr(connection, "get_current_agent_id", lambda: None)()
    if _dialect() in {"postgresql", "pg"} and current_agent:
        row = _row(connection.execute_query_one(
            "SELECT public.cx_channel_principal_type(:channel_id, :principal_id) AS PRINCIPAL_TYPE",
            {"channel_id": channel_id, "principal_id": principal_id},
        ))
        return str(row.get("principal_type")) if row and row.get("principal_type") else None
    row = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_TYPE FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE'",
        {"principal_id": principal_id},
    ))
    return str(row.get("principal_type")) if row and row.get("principal_type") else None


def create_channel_thread(
    principal_id: str,
    channel_id: str,
    thread_type: str = "CHANNEL",
    *,
    parent_thread_id: str = "",
    classification: str = "INTERNAL",
    policy: Optional[Dict[str, Any]] = None,
    participant_principal_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION" and str(thread_type or "CHANNEL").upper() in {"PRIVATE", "DIRECT"}:
        raise PermissionError("private and direct threads are disabled in the Platform Administration Channel")
    """Create a bounded collaboration thread under one Channel.

    A thread is a navigation and execution-context boundary only.  It never
    grants data, Skill, Tool, model, or export access beyond the parent
    Channel.  Agent-to-Agent Direct threads remain disabled by default.
    """
    channel = _assert_channel_member(principal_id, channel_id, "channels.write")
    thread_kind = str(thread_type or "CHANNEL").strip().upper()
    allowed_types = {"CHANNEL", "TASK", "RUN", "BARRIER", "PRIVATE", "DIRECT"}
    if thread_kind not in allowed_types:
        raise IdentityError("thread type is invalid")
    actor = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_TYPE FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
        {"principal_id": principal_id},
    )) or {}
    requested_participants = [str(value or "").strip() for value in (participant_principal_ids or [])]
    requested_participants = [value for value in dict.fromkeys(requested_participants) if value]
    if principal_id in requested_participants:
        requested_participants.remove(principal_id)
    if thread_kind in {"PRIVATE", "DIRECT"} and not requested_participants:
        raise IdentityError("private and direct threads require explicit participants")
    if thread_kind == "DIRECT" and len(requested_participants) != 1:
        raise IdentityError("direct threads require exactly one other participant")
    if thread_kind not in {"PRIVATE", "DIRECT"} and requested_participants:
        raise IdentityError("participants are only supported for private or direct threads")
    thread_participants = [principal_id] + requested_participants
    participant_rows: List[Dict[str, Any]] = []
    for participant_id in thread_participants:
        participant_type = _channel_principal_type(channel_id, participant_id)
        participant_row = {"principal_id": participant_id, "principal_type": participant_type, "status": "ACTIVE"} if participant_type else None
        if not participant_row:
            raise IdentityError("thread participant is unavailable")
        if not _channel_principal_is_member(channel_id, participant_id):
            raise PermissionError("thread participant is outside the Channel")
        participant_rows.append(participant_row)
    if thread_kind == "DIRECT" and all(
        str(value.get("principal_type") or "").upper() == "AGENT" for value in participant_rows
    ):
        raise PermissionError("Agent-to-Agent Direct threads are disabled by policy")
    selected_classification = _classification(classification)
    if not _classification_meets_minimum(selected_classification, channel.get("classification") or "INTERNAL"):
        raise IdentityError("thread classification cannot broaden the Channel")
    if parent_thread_id:
        parent = _row(connection.execute_query_one(
            "SELECT THREAD_ID, CHANNEL_ID, CLASSIFICATION, STATUS FROM CX_CHANNEL_THREADS "
            "WHERE THREAD_ID = :thread_id AND CHANNEL_ID = :channel_id",
            {"thread_id": parent_thread_id, "channel_id": channel_id},
        ))
        if not parent or str(parent.get("status") or "").upper() != "ACTIVE":
            raise IdentityError("parent thread is unavailable")
        if not _classification_meets_minimum(selected_classification, parent.get("classification") or "INTERNAL"):
            raise IdentityError("child thread classification cannot broaden its parent")
    thread_id = _id("TH")
    thread_policy = dict(policy or {})
    if thread_kind in {"PRIVATE", "DIRECT"}:
        # The database RLS policy uses this immutable participant snapshot;
        # it is not an authorization grant beyond the parent Channel.
        thread_policy["participant_principal_ids"] = list(thread_participants)
    statements = [(
        "INSERT INTO CX_CHANNEL_THREADS(THREAD_ID, CHANNEL_ID, PARENT_THREAD_ID, THREAD_TYPE, "
        "CLASSIFICATION, STATUS, POLICY_JSON, CREATED_BY) VALUES (:thread_id, :channel_id, "
        ":parent_thread_id, :thread_type, :classification, 'ACTIVE', :policy_json, :created_by)",
        {"thread_id": thread_id, "channel_id": channel_id,
         "parent_thread_id": parent_thread_id or None, "thread_type": thread_kind,
         "classification": selected_classification, "policy_json": _json(thread_policy),
         "created_by": principal_id},
    )]
    if thread_kind in {"PRIVATE", "DIRECT"}:
        for participant_id in thread_participants:
            statements.append((
                "INSERT INTO CX_CHANNEL_THREAD_MEMBERS(THREAD_MEMBER_ID, THREAD_ID, PRINCIPAL_ID, MEMBER_ROLE) "
                "VALUES (:thread_member_id, :thread_id, :principal_id, :member_role)",
                {"thread_member_id": _id("TM"), "thread_id": thread_id,
                 "principal_id": participant_id,
                 "member_role": "OWNER" if participant_id == principal_id else "MEMBER"},
            ))
    connection.execute_transaction_result(statements)
    _audit(principal_id, "CHANNEL_THREAD_CREATE", "CHANNEL_THREAD", thread_id, "ALLOW", "thread created")
    return {
        "thread_id": thread_id, "channel_id": channel_id,
        "parent_thread_id": parent_thread_id or None, "thread_type": thread_kind,
        "classification": selected_classification, "status": "ACTIVE",
        "participant_principal_ids": thread_participants if thread_kind in {"PRIVATE", "DIRECT"} else [],
    }


def list_channel_threads(principal_id: str, channel_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List thread metadata after rechecking current Channel membership."""
    _assert_channel_member(principal_id, channel_id, "channels.read")
    return _required_query(
        "SELECT THREAD_ID, CHANNEL_ID, PARENT_THREAD_ID, THREAD_TYPE, CLASSIFICATION, "
        "STATUS, POLICY_JSON, CREATED_BY, CREATED_AT, UPDATED_AT FROM CX_CHANNEL_THREADS t "
        "WHERE t.CHANNEL_ID = :channel_id AND t.STATUS <> 'DELETED' "
        "AND (t.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = t.THREAD_ID "
        "AND tm.PRINCIPAL_ID = :principal_id AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP))) "
        "ORDER BY t.UPDATED_AT DESC "
        + _limit_clause(),
        {"channel_id": channel_id, "principal_id": principal_id, "limit": max(1, min(int(limit), 500))},
    )


def _assert_channel_member(principal_id: str, channel_id: str, action: str = "channels.read") -> Dict[str, Any]:
    _require(principal_id, action)
    row = _row(connection.execute_query_one(
        "SELECT c.CHANNEL_ID, c.SECURITY_DOMAIN_ID, c.CLASSIFICATION, c.STATUS, m.MEMBER_ROLE "
        "FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID = c.CHANNEL_ID "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = m.PRINCIPAL_ID "
        "WHERE c.CHANNEL_ID = :channel_id AND c.STATUS <> 'DELETED' AND m.PRINCIPAL_ID = :principal_id "
        "AND m.STATUS = 'ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND p.STATUS = 'ACTIVE'",
        {"channel_id": channel_id, "principal_id": principal_id},
    ))
    if not row and action == "channels.read" and effective_access(principal_id, "channels.read.all")["decision"] == "ALLOW":
        row = _row(connection.execute_query_one(
            "SELECT CHANNEL_ID, SECURITY_DOMAIN_ID, CLASSIFICATION, STATUS, 'SYSTEM_ADMIN' AS MEMBER_ROLE "
            "FROM CX_CHANNELS WHERE CHANNEL_ID = :channel_id AND STATUS <> 'DELETED'",
            {"channel_id": channel_id},
        ))
    if not row:
        raise PermissionError("Channel access denied")
    # Channel membership is an admission record, not the authorization
    # boundary. Recheck the Domain on every guarded operation so expired or
    # revoked members cannot retain access through historical Channel rows.
    if effective_access(principal_id, "domains.manage")["decision"] != "ALLOW":
        domain_member = _row(connection.execute_query_one(
            "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain_id "
            "AND PRINCIPAL_ID=:principal_id AND STATUS='ACTIVE' "
            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
            {"domain_id": row.get("security_domain_id"), "principal_id": principal_id},
        ))
        if not domain_member:
            raise PermissionError("Channel Security Domain access denied")
    if str(row.get("status") or "").upper() != "ACTIVE" and action != "channels.read":
        raise PermissionError("Channel is not accepting this operation")
    return row


def _assert_thread_member(principal_id: str, thread_id: str, action: str = "channels.read") -> Dict[str, Any]:
    """Recheck Channel and explicit private/direct thread membership."""
    thread = _row(connection.execute_query_one(
        "SELECT THREAD_ID, CHANNEL_ID, THREAD_TYPE, STATUS FROM CX_CHANNEL_THREADS "
        "WHERE THREAD_ID = :thread_id",
        {"thread_id": thread_id},
    ))
    if not thread or str(thread.get("status") or "").upper() != "ACTIVE":
        raise IdentityError("thread is unavailable")
    _assert_channel_member(principal_id, str(thread["channel_id"]), action)
    if str(thread.get("thread_type") or "").upper() in {"PRIVATE", "DIRECT"} and not _row(connection.execute_query_one(
        "SELECT THREAD_MEMBER_ID FROM CX_CHANNEL_THREAD_MEMBERS "
        "WHERE THREAD_ID = :thread_id AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"thread_id": thread_id, "principal_id": principal_id},
    )):
        raise PermissionError("thread access denied")
    return thread


def post_channel_message(principal_id: str, channel_id: str, body: str, *, thread_type: str = "CHANNEL", thread_id: str = "", message_type: str = "TEXT", references: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    channel = _assert_channel_member(principal_id, channel_id, "channels.write")
    if not body or len(body) > 100000:
        raise IdentityError("Message body is invalid")
    normalized_thread_type = str(thread_type or "CHANNEL").strip().upper()
    if normalized_thread_type not in {"CHANNEL", "TASK", "RUN", "BARRIER", "PRIVATE", "DIRECT"}:
        raise IdentityError("message thread type is invalid")
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION" and normalized_thread_type in {"PRIVATE", "DIRECT"}:
        raise PermissionError("private and direct messages are disabled in the Platform Administration Channel")
    if thread_id:
        thread = _assert_thread_member(principal_id, thread_id, "channels.write")
        if str(thread.get("channel_id") or "") != channel_id:
            raise PermissionError("message thread is outside the Channel")
        if str(thread.get("thread_type") or "").upper() != normalized_thread_type:
            raise IdentityError("message thread type does not match the thread")
        if normalized_thread_type == "DIRECT":
            direct_agents = _row(connection.execute_query_one(
                "SELECT COUNT(*) AS CNT FROM CX_CHANNEL_THREAD_MEMBERS tm "
                "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = tm.PRINCIPAL_ID "
                "WHERE tm.THREAD_ID = :thread_id AND tm.STATUS = 'ACTIVE' "
                "AND p.PRINCIPAL_TYPE = 'AGENT'",
                {"thread_id": thread_id},
            )) or {}
            if int(direct_agents.get("cnt") or 0) > 1:
                raise PermissionError("Agent-to-Agent Direct threads are disabled by policy")
    elif normalized_thread_type != "CHANNEL":
        raise IdentityError("a non-Channel message requires a thread id")
    references = references if isinstance(references, dict) else {}
    mentions = references.get("mentions", []) if isinstance(references, dict) else []
    if not isinstance(mentions, list) or len(mentions) > 50:
        raise IdentityError("message mentions are invalid")
    normalized_mentions = []
    for mentioned in mentions:
        subject = str(mentioned or "").strip()[:128]
        if subject and subject not in normalized_mentions:
            if not _channel_principal_is_member(channel_id, subject):
                raise PermissionError("mentioned principal is outside the Channel")
            normalized_mentions.append(subject)
    references = {**references, "mentions": normalized_mentions} if normalized_mentions else {
        key: value for key, value in references.items() if key != "mentions"
    }
    message_id = _id("MSG")
    insert_sql = (
        "INSERT INTO CX_CHANNEL_MESSAGES(MESSAGE_ID, CHANNEL_ID, THREAD_TYPE, THREAD_ID, PRINCIPAL_ID, BODY_TEXT, BODY_CLASSIFICATION, MESSAGE_TYPE, REFERENCE_JSON) "
        "VALUES (:message_id, :channel_id, :thread_type, :thread_id, :principal_id, :body, :body_classification, :message_type, :references)"
    )
    insert_params = {
        "message_id": message_id, "channel_id": channel_id, "thread_type": normalized_thread_type,
        "thread_id": thread_id or None, "principal_id": principal_id, "body": body,
        "body_classification": str(channel.get("classification") or "INTERNAL"),
        "message_type": message_type, "references": _json(references),
    }
    current_agent = getattr(connection, "get_current_agent_id", lambda: None)()
    if _dialect() in {"postgresql", "pg"} and current_agent == principal_id:
        # The Agent RLS role cannot insert a delivery for another instance.
        # The controlled function performs the bounded fan-out atomically.
        def _agent_message_transaction(tx: Any) -> int:
            tx.execute(insert_sql, insert_params)
            result = tx.query_one(
                "SELECT public.cx_enqueue_channel_deliveries(:message_id, :channel_id, :body, :message_type, :references, :classification) AS INSERTED",
                {"message_id": message_id, "channel_id": channel_id, "body": body,
                "message_type": message_type, "references": _json(references),
                 "classification": channel.get("classification") or "INTERNAL"},
            ) or {}
            return int(result.get("inserted") or 0)
        delivered = connection.execute_transaction_callback(_agent_message_transaction)
    else:
        connection.execute(insert_sql, insert_params)
        delivered = _enqueue_channel_deliveries(message_id, channel_id, body, message_type, references, channel.get("classification") or "INTERNAL")
    # The Channel list is an activity inbox. Advancing its timestamp after a
    # durable message commit keeps the recent-conversation ordering portable
    # across all supported database implementations.
    connection.execute("UPDATE CX_CHANNELS SET UPDATED_AT=CURRENT_TIMESTAMP WHERE CHANNEL_ID=:channel_id", {"channel_id": channel_id})
    _audit(principal_id, "CHANNEL_MESSAGE_CREATE", "CHANNEL", channel_id, "ALLOW", "message persisted")
    dispatches: List[Dict[str, Any]] = []
    # Only a human administrator's explicit mention in the protected Channel
    # reaches the native runtime. Replies are AGENT_RESPONSE messages with no
    # mentions, so they cannot recursively invoke an Agent.
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION" and normalized_mentions:
        from . import native_agent_api
        dispatch_errors: List[Dict[str, str]] = []
        for mentioned_agent_id in normalized_mentions:
            try:
                if mentioned_agent_id not in {
                    native_agent_api.PLATFORM_ADMIN_AGENT_ID,
                    native_agent_api.COMPLIANCE_ADMIN_AGENT_ID,
                }:
                    continue
                dispatches.append(native_agent_api.create_channel_execution(
                    principal_id, channel_id, message_id, body, mentioned_agent_id,
                    normalized_thread_type, thread_id,
                ))
            except (native_agent_api.NativeAgentError, PermissionError) as exc:
                # The human message is already durable and auditable. Preserve
                # it, report the bounded dispatch failure, and never make a
                # client retry create a duplicate request message.
                dispatch_errors.append({"agent_id": mentioned_agent_id, "reason": str(exc)[:240]})
                _audit(principal_id, "CHANNEL_MANAGEMENT_AGENT_DISPATCH", "CHANNEL_MESSAGE", message_id,
                       "DENY", "explicit management Agent dispatch was not queued")
    return {"message_id": message_id, "channel_id": channel_id, "principal_id": principal_id, "body": body,
            "message_type": message_type, "deliveries_enqueued": int(delivered or 0), "agent_dispatches": dispatches,
            "agent_dispatch_errors": dispatch_errors if str(channel_id) == "CH_PLATFORM_ADMINISTRATION" and normalized_mentions else []}


def _channel_agent_response_message_id(channel_id: str, execution_id: str) -> str:
    digest = hashlib.sha256((str(channel_id) + ":" + str(execution_id)).encode("utf-8")).hexdigest()
    return "MSG_AR_" + digest[:56]


def begin_channel_agent_response(agent_id: str, channel_id: str, *, execution_id: str,
                                 thread_type: str = "CHANNEL", thread_id: str = "") -> Dict[str, Any]:
    """Create an idempotent, visible placeholder before model streaming starts."""
    _assert_channel_member(agent_id, channel_id, "channels.write")
    if not execution_id:
        raise IdentityError("managed Agent response is invalid")
    message_id = _channel_agent_response_message_id(channel_id, execution_id)
    references = _json({"execution_id": execution_id, "response_to": "CHANNEL_MENTION"})
    params = {
        "message_id": message_id, "channel_id": channel_id,
        "thread_type": str(thread_type or "CHANNEL").upper(), "thread_id": thread_id or None,
        # Oracle normalizes an empty string to NULL, while BODY_TEXT is
        # required. The UI recognizes this neutral marker as a spinner and
        # never renders it as response content.
        "principal_id": agent_id, "body": "[streaming]", "message_type": "AGENT_RESPONSE_STREAMING", "references": references,
    }
    try:
        connection.execute(
            "INSERT INTO CX_CHANNEL_MESSAGES(MESSAGE_ID,CHANNEL_ID,THREAD_TYPE,THREAD_ID,PRINCIPAL_ID,BODY_TEXT,BODY_CLASSIFICATION,MESSAGE_TYPE,REFERENCE_JSON) "
            "SELECT :message_id,:channel_id,:thread_type,:thread_id,:principal_id,:body,c.CLASSIFICATION,:message_type,:references "
            "FROM CX_CHANNELS c WHERE c.CHANNEL_ID=:channel_id AND c.STATUS='ACTIVE'",
            params,
        )
    except Exception:
        existing = _row(connection.execute_query_one(
            "SELECT MESSAGE_ID FROM CX_CHANNEL_MESSAGES WHERE MESSAGE_ID=:message_id",
            {"message_id": message_id},
        ))
        if existing:
            return {"message_id": message_id, "status": "EXISTS", "idempotent": True}
        raise
    _audit(agent_id, "CHANNEL_MANAGEMENT_AGENT_RESPONSE_BEGIN", "CHANNEL_MESSAGE", message_id,
           "ALLOW", "managed Agent response streaming started")
    connection.execute("UPDATE CX_CHANNELS SET UPDATED_AT=CURRENT_TIMESTAMP WHERE CHANNEL_ID=:channel_id", {"channel_id": channel_id})
    return {"message_id": message_id, "status": "CREATED", "idempotent": False}


def update_channel_agent_response(agent_id: str, channel_id: str, body: str, *, execution_id: str,
                                  completed: bool = False) -> Dict[str, Any]:
    """Update the single placeholder owned by a managed Agent.

    Chunk updates intentionally do not create audit rows. The begin and final
    transitions are auditable while the Channel stays readable under long
    model responses.
    """
    if not execution_id or len(body) > 100000:
        raise IdentityError("managed Agent response is invalid")
    message_id = _channel_agent_response_message_id(channel_id, execution_id)
    changed = connection.execute(
        "UPDATE CX_CHANNEL_MESSAGES SET BODY_TEXT=:body,MESSAGE_TYPE=:message_type WHERE MESSAGE_ID=:message_id "
        "AND CHANNEL_ID=:channel_id AND PRINCIPAL_ID=:agent",
        {"body": body, "message_type": "AGENT_RESPONSE" if completed else "AGENT_RESPONSE_STREAMING",
         "message_id": message_id, "channel_id": channel_id, "agent": agent_id},
    )
    if changed != 1:
        raise IdentityError("managed Agent response is unavailable")
    connection.execute("UPDATE CX_CHANNELS SET UPDATED_AT=CURRENT_TIMESTAMP WHERE CHANNEL_ID=:channel_id", {"channel_id": channel_id})
    if completed:
        _audit(agent_id, "CHANNEL_MANAGEMENT_AGENT_RESPONSE", "CHANNEL_MESSAGE", message_id,
               "ALLOW", "managed Agent response completed")
    return {"message_id": message_id, "status": "COMPLETED" if completed else "STREAMING"}


def post_channel_agent_response(agent_id: str, channel_id: str, body: str, *,
                                execution_id: str, thread_type: str = "CHANNEL",
                                thread_id: str = "") -> Dict[str, Any]:
    """Persist a completed response, retaining compatibility with non-streaming callers."""
    begin_channel_agent_response(agent_id, channel_id, execution_id=execution_id,
                                 thread_type=thread_type, thread_id=thread_id)
    return update_channel_agent_response(agent_id, channel_id, body, execution_id=execution_id,
                                         completed=True)


def _enqueue_channel_deliveries(message_id: str, channel_id: str, body: str,
                                message_type: str, references: Dict[str, Any],
                                classification: str) -> int:
    """Create durable per-instance deliveries without widening membership."""
    instances = _required_query(
        "SELECT DISTINCT i.INSTANCE_ID, i.AGENT_ID FROM CX_AGENT_INSTANCES i "
        "JOIN CX_CHANNEL_MESSAGES msg ON msg.MESSAGE_ID = :message_id "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = i.AGENT_ID "
        "JOIN CX_CHANNEL_MEMBERS m ON m.PRINCIPAL_ID = i.AGENT_ID "
        "WHERE m.CHANNEL_ID = :channel_id AND m.STATUS = 'ACTIVE' "
        "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "AND i.CHANNEL_ID = :channel_id AND i.STATUS = 'ACTIVE' AND p.STATUS = 'ACTIVE' "
        "AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP "
        "AND (msg.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = msg.THREAD_ID "
        "AND tm.PRINCIPAL_ID = i.AGENT_ID AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP)))",
        {"message_id": message_id, "channel_id": channel_id},
    )
    payload = _json({"message_id": message_id, "channel_id": channel_id, "body": body,
                     "message_type": message_type, "references": references,
                     "classification": classification})
    inserted = 0
    for item in instances:
        instance_id = str(item.get("instance_id") or "")
        agent_id = str(item.get("agent_id") or "")
        if not instance_id or not agent_id:
            continue
        try:
            inserted += connection.execute(
                "INSERT INTO CX_AGENT_DELIVERIES(DELIVERY_ID, EVENT_TYPE, CHANNEL_ID, MESSAGE_ID, AGENT_ID, INSTANCE_ID, PAYLOAD_JSON, IDEMPOTENCY_KEY, STATUS) "
                "VALUES (:delivery_id, 'CHANNEL_MESSAGE', :channel_id, :message_id, :agent_id, :instance_id, :payload_json, :idempotency_key, 'PENDING')",
                {"delivery_id": _id("DLV"), "channel_id": channel_id, "message_id": message_id,
                 "agent_id": agent_id, "instance_id": instance_id, "payload_json": payload,
                 "idempotency_key": f"channel:{message_id}:{instance_id}"},
            )
        except Exception:
            # A duplicate is harmless; all other delivery failures are retained
            # as a security event for the operational reconciler.
            _audit(agent_id, "CHANNEL_DELIVERY_ENQUEUE_FAILED", "CHANNEL", channel_id, "ERROR", message_id)
    return inserted


def enqueue_instance_backlog(agent_id: str, instance_id: str, channel_id: str, limit: int = 100) -> int:
    """Backfill recent Channel messages when an isolated instance is created."""
    if not agent_id or not instance_id or not channel_id:
        return 0
    rows = _required_query(
        "SELECT m.MESSAGE_ID, m.BODY_TEXT, m.MESSAGE_TYPE, m.REFERENCE_JSON, m.BODY_CLASSIFICATION "
        "FROM CX_CHANNEL_MESSAGES m JOIN CX_CHANNEL_MEMBERS cm ON cm.CHANNEL_ID = m.CHANNEL_ID "
        "AND cm.PRINCIPAL_ID = :agent_id AND cm.STATUS = 'ACTIVE' "
        "AND (cm.VALID_UNTIL IS NULL OR cm.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "WHERE m.CHANNEL_ID = :channel_id AND m.REDACTED_AT IS NULL "
        "AND (m.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = m.THREAD_ID "
        "AND tm.PRINCIPAL_ID = :agent_id AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP))) "
        "ORDER BY m.CREATED_AT DESC, m.MESSAGE_ID DESC " + _limit_clause(),
        {"agent_id": agent_id, "channel_id": channel_id, "limit": max(1, min(int(limit), 500))},
    )
    inserted = 0
    for row in rows:
        message_id = str(row.get("message_id") or "")
        if not message_id:
            continue
        reference = row.get("reference_json") or "{}"
        if not isinstance(reference, str):
            reference = _json(reference)
        try:
            inserted += connection.execute(
                "INSERT INTO CX_AGENT_DELIVERIES(DELIVERY_ID, EVENT_TYPE, CHANNEL_ID, MESSAGE_ID, AGENT_ID, INSTANCE_ID, PAYLOAD_JSON, IDEMPOTENCY_KEY, STATUS) "
                "VALUES (:delivery_id, 'CHANNEL_MESSAGE', :channel_id, :message_id, :agent_id, :instance_id, :payload_json, :idempotency_key, 'PENDING')",
                {"delivery_id": _id("DLV"), "channel_id": channel_id, "message_id": message_id,
                 "agent_id": agent_id, "instance_id": instance_id,
                 "payload_json": _json({"message_id": message_id, "channel_id": channel_id,
                                         "body": row.get("body_text"), "message_type": row.get("message_type"),
                                         "references": reference,
                                         "classification": row.get("body_classification") or "INTERNAL"}),
                 "idempotency_key": f"channel:{message_id}:{instance_id}"},
            )
        except Exception:
            continue
    return inserted


def list_channel_messages(principal_id: str, channel_id: str, limit: int = 100, before: str = "") -> List[Dict[str, Any]]:
    _assert_channel_member(principal_id, channel_id)
    params: Dict[str, Any] = {"channel_id": channel_id, "principal_id": principal_id, "limit": max(1, min(int(limit), 500))}
    cursor = ""
    if before:
        cursor = " AND m.MESSAGE_ID < :before"
        params["before"] = before
    return _required_query(
        "SELECT m.MESSAGE_ID, m.CHANNEL_ID, m.THREAD_TYPE, m.THREAD_ID, m.PRINCIPAL_ID, "
        "COALESCE(p.DISPLAY_NAME, m.PRINCIPAL_ID) AS SENDER_DISPLAY_NAME, "
        "p.PRINCIPAL_TYPE AS SENDER_PRINCIPAL_TYPE, p.STATUS AS SENDER_STATUS, "
        "m.BODY_TEXT, m.MESSAGE_TYPE, m.REFERENCE_JSON, m.CREATED_AT "
        "FROM CX_CHANNEL_MESSAGES m JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=m.PRINCIPAL_ID "
        "WHERE m.CHANNEL_ID = :channel_id "
        "AND m.REDACTED_AT IS NULL "
        "AND (m.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = m.THREAD_ID "
        "AND tm.PRINCIPAL_ID = :principal_id AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP)))"
        + cursor + " ORDER BY m.CREATED_AT DESC, m.MESSAGE_ID DESC " + _limit_clause(),
        params,
    )


def channel_summary(principal_id: str, channel_id: str) -> Dict[str, Any]:
    """Return bounded operational counters for the Channel UI."""
    channel = _assert_channel_member(principal_id, channel_id, "channels.read")
    members = _row(connection.execute_query_one(
        "SELECT COUNT(*) AS CNT FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID = :channel_id "
        "AND STATUS = 'ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
        {"channel_id": channel_id},
    )) or {}
    messages = _row(connection.execute_query_one(
        "SELECT COUNT(*) AS CNT FROM CX_CHANNEL_MESSAGES m WHERE m.CHANNEL_ID = :channel_id "
        "AND m.REDACTED_AT IS NULL AND (m.THREAD_TYPE NOT IN ('PRIVATE','DIRECT') OR EXISTS ("
        "SELECT 1 FROM CX_CHANNEL_THREAD_MEMBERS tm WHERE tm.THREAD_ID = m.THREAD_ID "
        "AND tm.PRINCIPAL_ID = :principal_id AND tm.STATUS = 'ACTIVE' "
        "AND (tm.VALID_UNTIL IS NULL OR tm.VALID_UNTIL > CURRENT_TIMESTAMP)))",
        {"channel_id": channel_id, "principal_id": principal_id},
    )) or {}
    agents = _row(connection.execute_query_one(
        "SELECT COUNT(DISTINCT i.AGENT_ID) AS CNT FROM CX_AGENT_INSTANCES i "
        "JOIN CX_CHANNEL_MEMBERS m ON m.PRINCIPAL_ID = i.AGENT_ID AND m.CHANNEL_ID = i.CHANNEL_ID "
        "WHERE i.CHANNEL_ID = :channel_id AND i.STATUS = 'ACTIVE' AND i.LEASE_EXPIRES_AT > CURRENT_TIMESTAMP",
        {"channel_id": channel_id},
    )) or {}
    barriers = _row(connection.execute_query_one(
        "SELECT COUNT(*) AS CNT FROM CX_BARRIERS WHERE CHANNEL_ID = :channel_id "
        "AND STATUS IN ('WAITING','READY','REVIEW_REQUIRED')", {"channel_id": channel_id},
    )) or {}
    return {
        "channel_id": channel_id, "channel_status": channel.get("status"),
        "classification": channel.get("classification"),
        "member_count": int(members.get("cnt") or 0),
        "message_count": int(messages.get("cnt") or 0),
        "active_agent_count": int(agents.get("cnt") or 0),
        "open_barrier_count": int(barriers.get("cnt") or 0),
    }


def create_barrier(principal_id: str, node_key: str, policy: Dict[str, Any], participant_snapshot: List[Dict[str, Any]], *, channel_id: str = "", run_id: str = "", checkpoint_id: str = "", timeout_at: Any = None) -> Dict[str, Any]:
    _require(principal_id, "barriers.create")
    if channel_id:
        _assert_channel_member(principal_id, channel_id, "barriers.create")
    if not str(node_key or "").strip() or not isinstance(participant_snapshot, list) or not participant_snapshot:
        raise IdentityError("Barrier node and participant snapshot are required")
    normalized_snapshot = []
    for participant in participant_snapshot:
        if not isinstance(participant, dict):
            raise IdentityError("Barrier participant snapshot is invalid")
        identity = str(participant.get("principal_id") or participant.get("agent_id") or "").strip()
        if not identity:
            raise IdentityError("Barrier participant identity is required")
        current_agent = getattr(connection, "get_current_agent_id", lambda: None)()
        participant_row = None
        if _dialect() in {"postgresql", "pg"} and current_agent:
            participant_row = {"principal_id": identity, "status": "ACTIVE"} if _channel_principal_is_member(channel_id, identity) else None
        else:
            participant_row = _row(connection.execute_query_one(
                "SELECT PRINCIPAL_ID, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :principal_id",
                {"principal_id": identity},
            ))
        if not participant_row or str(participant_row.get("status") or "").upper() != "ACTIVE":
            raise IdentityError("Barrier participant is unavailable")
        if channel_id and not _channel_principal_is_member(channel_id, identity):
            raise PermissionError("Barrier participant is outside the Channel")
        normalized_snapshot.append({**participant, "principal_id": identity})
    barrier_id = _id("BA")
    connection.execute(
        "INSERT INTO CX_BARRIERS(BARRIER_ID, CHANNEL_ID, RUN_ID, NODE_KEY, POLICY_JSON, PARTICIPANT_SNAPSHOT, CHECKPOINT_ID, CREATED_BY, TIMEOUT_AT) "
        "VALUES (:barrier_id, :channel_id, :run_id, :node_key, :policy, :participants, :checkpoint_id, :created_by, :timeout_at)",
        {"barrier_id": barrier_id, "channel_id": channel_id or None, "run_id": run_id or None,
         "node_key": node_key[:128], "policy": _json(policy), "participants": _json(normalized_snapshot),
         "checkpoint_id": checkpoint_id or None, "created_by": principal_id, "timeout_at": timeout_at},
    )
    _audit(principal_id, "BARRIER_CREATE", "BARRIER", barrier_id, "ALLOW", "barrier activated")
    return {"barrier_id": barrier_id, "status": "WAITING", "policy": policy, "participant_snapshot": normalized_snapshot}


def arrive_barrier(principal_id: str, barrier_id: str, report: Dict[str, Any], participant_role: str = "MEMBER", idempotency_key: str = "") -> Dict[str, Any]:
    arrival_id = _id("ARR")
    report_text = _json(report)
    digest = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    idempotency_key = str(idempotency_key or "").strip()[:256]
    if not idempotency_key:
        idempotency_key = "report:" + digest[:48]
    normalized_role = str(participant_role or "MEMBER").upper()[:64]

    # Serialize all arrivals for one Barrier.  This makes the duplicate check,
    # insert, quorum evaluation, and WAITING -> READY transition one winner.
    def _commit(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one(
            "SELECT BARRIER_ID, CHANNEL_ID, CREATED_BY, POLICY_JSON, PARTICIPANT_SNAPSHOT, STATUS "
            "FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id FOR UPDATE",
            {"barrier_id": barrier_id},
        ))
        if not row:
            raise IdentityError("Barrier is no longer waiting")
        if row.get("channel_id"):
            member = tx.query_one(
                "SELECT PRINCIPAL_ID FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID = :channel_id "
                "AND PRINCIPAL_ID = :principal_id AND STATUS = 'ACTIVE' "
                "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
                {"channel_id": row["channel_id"], "principal_id": principal_id},
            )
            if not member:
                raise PermissionError("Barrier access denied")
        else:
            _require(principal_id, "barriers.arrive")
            if str(row.get("created_by") or "") != principal_id and effective_access(principal_id, "barriers.read.all")["decision"] != "ALLOW":
                raise PermissionError("Barrier access denied")
        # A completed Barrier may still receive a network retry for an
        # already accepted arrival.  Check that exact request after admission
        # but before rejecting the terminal state.  New or conflicting
        # arrivals remain denied once the Barrier is no longer WAITING.
        if str(row.get("status") or "").upper() != "WAITING":
            previous = _row(tx.query_one(
                "SELECT ARRIVAL_ID, REPORT_DIGEST, IDEMPOTENCY_KEY FROM CX_BARRIER_ARRIVALS "
                "WHERE BARRIER_ID = :barrier_id AND PRINCIPAL_ID = :principal_id FOR UPDATE",
                {"barrier_id": barrier_id, "principal_id": principal_id},
            ))
            if previous:
                if str(previous.get("idempotency_key") or "") != idempotency_key:
                    raise IdentityError("Barrier participant has already arrived")
                if str(previous.get("report_digest")) != digest:
                    raise IdentityError("Barrier arrival idempotency conflict")
                return {"arrival_id": str(previous["arrival_id"]), "barrier_id": barrier_id,
                        "status": str(row.get("status")), "report_digest": digest,
                        "idempotent": True}
            raise IdentityError("Barrier is no longer waiting")
        try:
            policy = json.loads(row.get("policy_json") or "{}")
            participants = json.loads(row.get("participant_snapshot") or "[]")
        except (TypeError, ValueError) as exc:
            raise IdentityError("Barrier policy is invalid") from exc
        allowed = {str(item.get("principal_id") or item.get("agent_id") or "") for item in participants if isinstance(item, dict)}
        if allowed and principal_id not in allowed:
            raise PermissionError("Principal is not in the Barrier snapshot")
        participant_roles = {
            str(item.get("role") or item.get("participant_role") or "").upper()
            for item in participants
            if isinstance(item, dict)
            and str(item.get("principal_id") or item.get("agent_id") or "") == principal_id
        }
        if participant_roles and normalized_role not in participant_roles:
            raise PermissionError("Participant role is not in the Barrier snapshot")
        previous = _row(tx.query_one(
            "SELECT ARRIVAL_ID, REPORT_DIGEST, IDEMPOTENCY_KEY FROM CX_BARRIER_ARRIVALS "
            "WHERE BARRIER_ID = :barrier_id AND PRINCIPAL_ID = :principal_id FOR UPDATE",
            {"barrier_id": barrier_id, "principal_id": principal_id},
        ))
        idempotent = bool(previous)
        if previous:
            if str(previous.get("idempotency_key") or "") != idempotency_key:
                raise IdentityError("Barrier participant has already arrived")
            if str(previous.get("report_digest")) != digest:
                raise IdentityError("Barrier arrival idempotency conflict")
            effective_arrival_id = str(previous["arrival_id"])
        else:
            effective_arrival_id = arrival_id
            tx.execute(
                "INSERT INTO CX_BARRIER_ARRIVALS(ARRIVAL_ID, BARRIER_ID, PRINCIPAL_ID, PARTICIPANT_ROLE, REPORT_DIGEST, REPORT_JSON, IDEMPOTENCY_KEY) "
                "VALUES (:arrival_id, :barrier_id, :principal_id, :participant_role, :report_digest, :report_json, :idempotency_key)",
                {"arrival_id": effective_arrival_id, "barrier_id": barrier_id, "principal_id": principal_id,
                 "participant_role": normalized_role, "report_digest": digest, "report_json": report_text,
                 "idempotency_key": idempotency_key},
            )
        arrivals = tx.query(
            "SELECT PRINCIPAL_ID, PARTICIPANT_ROLE FROM CX_BARRIER_ARRIVALS "
            "WHERE BARRIER_ID = :barrier_id AND STATUS = 'ACCEPTED'",
            {"barrier_id": barrier_id},
        )
        required_roles = {str(value) for value in policy.get("required_roles", [])}
        arrived_roles = {str(item.get("participant_role")) for item in arrivals}
        try:
            quorum = int(policy.get("quorum") or len(participants) or 1)
        except (TypeError, ValueError):
            quorum = len(participants) or 1
        status = "READY" if len(arrivals) >= quorum and required_roles <= arrived_roles else "WAITING"
        if status == "READY":
            tx.execute(
                "UPDATE CX_BARRIERS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE BARRIER_ID = :barrier_id AND STATUS = 'WAITING'",
                {"barrier_id": barrier_id},
            )
        if not idempotent:
            _audit_tx(tx, principal_id, "BARRIER_ARRIVAL", "BARRIER", barrier_id, "ALLOW", "arrival accepted")
        return {"arrival_id": effective_arrival_id, "barrier_id": barrier_id, "status": status,
                "report_digest": digest, "idempotent": idempotent}

    return connection.execute_transaction_callback(_commit)


def evaluate_barrier(barrier_id: str) -> str:
    row = _row(connection.execute_query_one("SELECT POLICY_JSON, PARTICIPANT_SNAPSHOT, STATUS FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id", {"barrier_id": barrier_id}))
    if not row:
        raise IdentityError("Barrier not found")
    if str(row.get("status") or "").upper() != "WAITING":
        return str(row.get("status"))
    try:
        policy = json.loads(row.get("policy_json") or "{}")
    except (TypeError, ValueError):
        policy = {}
    try:
        snapshot = json.loads(row.get("participant_snapshot") or "[]")
    except (TypeError, ValueError):
        snapshot = []
    arrivals = _required_query("SELECT PRINCIPAL_ID, PARTICIPANT_ROLE FROM CX_BARRIER_ARRIVALS WHERE BARRIER_ID = :barrier_id AND STATUS = 'ACCEPTED'", {"barrier_id": barrier_id})
    required_roles = {str(value) for value in policy.get("required_roles", [])}
    arrived_roles = {str(item.get("participant_role")) for item in arrivals}
    try:
        quorum = int(policy.get("quorum") or len(snapshot) or 1)
    except (TypeError, ValueError):
        quorum = len(snapshot) or 1
    if len(arrivals) >= quorum and required_roles <= arrived_roles:
        # Conditional state advancement makes READY a durable one-way
        # readiness decision under concurrent arrivals.  Release remains a
        # separate conditional transition, so it can happen only once.
        connection.execute(
            "UPDATE CX_BARRIERS SET STATUS = 'READY', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE BARRIER_ID = :barrier_id AND STATUS = 'WAITING'",
            {"barrier_id": barrier_id},
        )
        return "READY"
    return "WAITING"


def list_barriers(principal_id: str, channel_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "barriers.read")
    params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    channel_filter = ""
    if channel_id:
        channel_filter = " AND b.CHANNEL_ID = :channel_id"
        params["channel_id"] = channel_id
    if effective_access(principal_id, "barriers.read.all")["decision"] == "ALLOW":
        visibility = "1 = 1"
    else:
        params["principal_id"] = principal_id
        visibility = (
            "(EXISTS (SELECT 1 FROM CX_CHANNEL_MEMBERS cm "
            "WHERE cm.CHANNEL_ID = b.CHANNEL_ID AND cm.PRINCIPAL_ID = :principal_id "
            "AND cm.STATUS = 'ACTIVE' "
            "AND (cm.VALID_UNTIL IS NULL OR cm.VALID_UNTIL > CURRENT_TIMESTAMP)) "
            "OR (b.CHANNEL_ID IS NULL AND b.CREATED_BY = :principal_id))"
        )
    return _required_query(
        "SELECT b.BARRIER_ID, b.CHANNEL_ID, b.RUN_ID, b.NODE_KEY, b.POLICY_JSON, "
        "b.PARTICIPANT_SNAPSHOT, b.STATUS, b.CHECKPOINT_ID, b.CREATED_BY, b.TIMEOUT_AT, b.RELEASED_BY, "
        "b.RELEASED_AT, b.CREATED_AT, b.UPDATED_AT FROM CX_BARRIERS b "
        "WHERE " + visibility + channel_filter +
        " ORDER BY b.UPDATED_AT DESC " + _limit_clause(), params,
    )


def barrier_detail(principal_id: str, barrier_id: str) -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT BARRIER_ID, CHANNEL_ID, RUN_ID, NODE_KEY, POLICY_JSON, PARTICIPANT_SNAPSHOT, "
        "STATUS, CHECKPOINT_ID, CREATED_BY, TIMEOUT_AT, RELEASED_BY, RELEASED_AT, CREATED_AT, UPDATED_AT "
        "FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id", {"barrier_id": barrier_id},
    ))
    if not row:
        raise IdentityError("Barrier not found")
    if row.get("channel_id"):
        _assert_channel_member(principal_id, str(row["channel_id"]), "barriers.read")
    else:
        _require(principal_id, "barriers.read")
        if str(row.get("created_by") or "") != principal_id and effective_access(principal_id, "barriers.read.all")["decision"] != "ALLOW":
            raise PermissionError("Barrier access denied")
    row["arrivals"] = _required_query(
        "SELECT ARRIVAL_ID, PRINCIPAL_ID, PARTICIPANT_ROLE, REPORT_DIGEST, REPORT_JSON, "
        "STATUS, CREATED_AT FROM CX_BARRIER_ARRIVALS WHERE BARRIER_ID = :barrier_id ORDER BY CREATED_AT",
        {"barrier_id": barrier_id},
    )
    return row


def create_action_card(principal_id: str, channel_id: str, action_type: str, payload: Dict[str, Any], reason: str, idempotency_key: str) -> Dict[str, Any]:
    if not reason.strip() or not idempotency_key.strip():
        raise IdentityError("Action reason and idempotency key are required")
    _assert_channel_member(principal_id, channel_id, "channels.write")
    if str(channel_id) == "CH_PLATFORM_ADMINISTRATION" and not str(action_type or "").upper().startswith("PLATFORM_"):
        raise PermissionError("protected Platform Administration Channel requires a PLATFORM_ Action Card")
    existing = _row(connection.execute_query_one(
        "SELECT ACTION_ID, CHANNEL_ID, ACTION_TYPE, VERSION, PAYLOAD_JSON, STATUS, REASON, CREATED_AT "
        "FROM CX_ACTION_CARDS WHERE IDEMPOTENCY_KEY = :idempotency_key",
        {"idempotency_key": idempotency_key[:256]},
    ))
    if existing:
        return {**existing, "idempotent": True}
    action_id = _id("ACT")
    connection.execute(
        "INSERT INTO CX_ACTION_CARDS(ACTION_ID, CHANNEL_ID, PROPOSED_BY, ACTION_TYPE, VERSION, PAYLOAD_JSON, STATUS, REASON, IDEMPOTENCY_KEY) "
        "VALUES (:action_id, :channel_id, :proposed_by, :action_type, 1, :payload, 'PROPOSED', :reason, :idempotency_key)",
        {"action_id": action_id, "channel_id": channel_id, "proposed_by": principal_id,
         "action_type": action_type[:64], "payload": _json(payload), "reason": reason[:2000],
         "idempotency_key": idempotency_key[:256]},
    )
    _audit(principal_id, "ACTION_CARD_PROPOSE", "ACTION_CARD", action_id, "PENDING", reason)
    return {"action_id": action_id, "channel_id": channel_id, "action_type": action_type, "status": "PROPOSED", "payload": payload, "reason": reason}


def list_action_cards(principal_id: str, channel_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    _require(principal_id, "channels.read")
    params: Dict[str, Any] = {"principal_id": principal_id, "limit": max(1, min(int(limit), 500))}
    extra = ""
    if channel_id:
        extra = " AND a.CHANNEL_ID = :channel_id"
        params["channel_id"] = channel_id
    return _required_query(
        "SELECT a.ACTION_ID, a.CHANNEL_ID, a.PROPOSED_BY, a.ACTION_TYPE, a.VERSION, a.PAYLOAD_JSON, "
        "a.STATUS, a.REASON, a.DECIDED_BY, a.DECIDED_AT, a.CREATED_AT FROM CX_ACTION_CARDS a "
        "JOIN CX_CHANNEL_MEMBERS m ON m.CHANNEL_ID = a.CHANNEL_ID AND m.PRINCIPAL_ID = :principal_id "
        "AND m.STATUS = 'ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "WHERE 1 = 1" + extra + " ORDER BY a.CREATED_AT DESC " + _limit_clause(), params,
    )


def decide_action_card(principal_id: str, action_id: str, decision: str, reason: str) -> bool:
    if not reason.strip():
        raise IdentityError("Action decision reason is required")
    _require(principal_id, "channels.actions.decide")
    action = _row(connection.execute_query_one(
        "SELECT CHANNEL_ID, PROPOSED_BY, STATUS FROM CX_ACTION_CARDS WHERE ACTION_ID = :action_id",
        {"action_id": action_id},
    ))
    if not action or str(action.get("status") or "").upper() != "PROPOSED":
        return False
    _assert_channel_member(principal_id, str(action["channel_id"]), "channels.actions.decide")
    if str(action.get("proposed_by") or "") == principal_id and effective_access(principal_id, "channels.actions.decide.self")["decision"] != "ALLOW":
        raise PermissionError("Action proposer cannot approve its own Action Card")
    target = "CONFIRMED" if str(decision or "").upper() in {"CONFIRM", "APPROVE", "RELEASE"} else "REJECTED"
    changed = connection.execute(
        "UPDATE CX_ACTION_CARDS SET STATUS = :status, DECIDED_BY = :decided_by, DECIDED_AT = CURRENT_TIMESTAMP "
        "WHERE ACTION_ID = :action_id AND STATUS = 'PROPOSED'",
        {"status": target, "decided_by": principal_id, "action_id": action_id},
    ) > 0
    if changed:
        _audit(principal_id, "ACTION_CARD_" + target, "ACTION_CARD", action_id, "ALLOW", reason)
    return changed


def release_barrier(principal_id: str, barrier_id: str, decision: str, reason: str) -> bool:
    if not reason.strip():
        raise IdentityError("Barrier release reason is required")
    _require(principal_id, "barriers.release")
    barrier = _row(connection.execute_query_one(
        "SELECT CHANNEL_ID FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id", {"barrier_id": barrier_id}
    ))
    if not barrier:
        raise IdentityError("Barrier not found")
    if barrier.get("channel_id"):
        _assert_channel_member(principal_id, str(barrier["channel_id"]), "barriers.release")
    decision = str(decision or "RELEASE").upper()
    target = "RELEASED" if decision == "RELEASE" else "REJECTED"
    changed = connection.execute("UPDATE CX_BARRIERS SET STATUS = :status, RELEASED_BY = :principal_id, RELEASED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP WHERE BARRIER_ID = :barrier_id AND STATUS IN ('WAITING','READY','REVIEWING','REVIEW_REQUIRED')", {"status": target, "principal_id": principal_id, "barrier_id": barrier_id}) > 0
    if changed:
        _audit(principal_id, "BARRIER_" + target, "BARRIER", barrier_id, "ALLOW", reason)
    return changed


def recover_barrier(
    principal_id: str,
    barrier_id: str,
    action: str,
    reason: str,
    *,
    substitute_principal_id: str = "",
) -> Dict[str, Any]:
    """Recover a Barrier through a durable state transition.

    The database row is updated before the caller can dispatch more work.  A
    Worker lease is never held by this control operation; the Graph Runtime
    observes the new status and claims a fresh attempt if appropriate.
    """
    _require(principal_id, "barriers.recover")
    if not str(reason or "").strip():
        raise IdentityError("Barrier recovery reason is required")
    row = _row(connection.execute_query_one(
        "SELECT BARRIER_ID, CHANNEL_ID, RUN_ID, STATUS, POLICY_JSON, PARTICIPANT_SNAPSHOT, "
        "CHECKPOINT_ID, TIMEOUT_AT, CREATED_BY, RETRY_COUNT, MAX_RETRIES "
        "FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id", {"barrier_id": barrier_id},
    ))
    if not row:
        raise IdentityError("Barrier not found")
    if row.get("channel_id"):
        _assert_channel_member(principal_id, str(row["channel_id"]), "barriers.recover")
    try:
        policy = json.loads(row.get("policy_json") or "{}")
    except (TypeError, ValueError):
        policy = {}
    selected = str(action or "").strip().upper()
    state_map = {
        "WAITING": "ARRIVING", "READY": "QUORUM_REACHED", "FAILED": "ARRIVING",
        "RETRYING": "REWORK", "ESCALATED": "REVIEWING", "TIMED_OUT": "EXPIRED",
        "REVIEW_REQUIRED": "REVIEW_REQUIRED", "REVIEWING": "REVIEWING",
        "REWORK": "REWORK", "QUORUM_REACHED": "QUORUM_REACHED", "ARRIVING": "ARRIVING",
    }
    retry_count = int(row.get("retry_count") or policy.get("retry_count") or 0)
    max_retries = int(row.get("max_retries") or policy.get("max_retries") or 3)
    try:
        snapshot = json.loads(row.get("participant_snapshot") or "[]")
    except (TypeError, ValueError) as exc:
        raise IdentityError("Barrier participant snapshot is invalid") from exc
    if not isinstance(snapshot, list):
        raise IdentityError("Barrier participant snapshot is invalid")
    arrivals = _required_query(
        "SELECT PRINCIPAL_ID, PARTICIPANT_ROLE FROM CX_BARRIER_ARRIVALS "
        "WHERE BARRIER_ID = :barrier_id AND STATUS = 'ACCEPTED'",
        {"barrier_id": barrier_id},
    )
    def _policy_values(value: Any) -> List[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    required_roles = _policy_values(policy.get("required_roles"))
    arrived_roles = {str(item.get("participant_role") or "") for item in arrivals}
    failed_roles = _policy_values(policy.get("failed_roles")) or [role for role in required_roles if role not in arrived_roles]
    checkpoint_id = str(row.get("checkpoint_id") or "")
    checkpoint = None
    checkpoint_authorized = False
    if checkpoint_id:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            raise IdentityError("Barrier checkpoint is not bound to a Graph Run")
        try:
            checkpoint = _row(connection.execute_query_one(
                "SELECT CHECKPOINT_ID, RUN_ID, ACTOR_ID, STATE_HASH FROM GRAPH_CHECKPOINTS "
                "WHERE CHECKPOINT_ID = :checkpoint_id AND RUN_ID = :run_id",
                {"checkpoint_id": checkpoint_id, "run_id": run_id},
            ))
        except Exception as exc:
            raise IdentityError("Barrier checkpoint service is unavailable") from exc
        if checkpoint:
            authorized_ids = policy.get("checkpoint_authorized_principals") or policy.get("authorized_recovery_principals") or []
            if isinstance(authorized_ids, str):
                authorized_ids = [authorized_ids]
            checkpoint_authorized = (
                principal_id in {str(value) for value in authorized_ids}
                or str(row.get("created_by") or "") == principal_id
                or effective_access(principal_id, "graphs.read.all")["decision"] == "ALLOW"
                or effective_access(principal_id, "domains.manage")["decision"] == "ALLOW"
            )
            if not checkpoint_authorized:
                raise PermissionError("Barrier checkpoint recovery is outside the authorized scope")
    substitute_authorized = False
    if substitute_principal_id:
        current_agent = getattr(connection, "get_current_agent_id", lambda: None)()
        if _dialect() in {"postgresql", "pg"} and current_agent:
            substitute = {"principal_id": substitute_principal_id, "status": "ACTIVE"} if row.get("channel_id") and _channel_principal_is_member(str(row["channel_id"]), substitute_principal_id) else None
        else:
            substitute = _row(connection.execute_query_one(
                "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS "
                "WHERE PRINCIPAL_ID = :principal_id", {"principal_id": substitute_principal_id},
            ))
        if not substitute or str(substitute.get("status") or "").upper() != "ACTIVE":
            raise IdentityError("Barrier substitute is unavailable")
        if row.get("channel_id"):
            if not _channel_principal_is_member(str(row["channel_id"]), substitute_principal_id):
                raise PermissionError("Barrier substitute is outside the Channel")
        declared = policy.get("authorized_substitutes") or policy.get("substitutes") or []
        if isinstance(declared, dict):
            declared = [declared]
        for candidate in declared:
            candidate_id = candidate.get("principal_id") if isinstance(candidate, dict) else candidate
            if str(candidate_id or "") == substitute_principal_id:
                substitute_authorized = True
                break
        if not substitute_authorized:
            raise PermissionError("Barrier substitute is not explicitly authorized")
    deadline = _timestamp(row.get("timeout_at"))
    now = _now()
    requested_human_review = selected in {"ESCALATE", "HUMAN_DECISION_REQUIRED", "TIMEOUT"}
    decision = governed_contracts.barrier_recovery_decision(
        state_map.get(str(row.get("status") or "").upper(), str(row.get("status") or "").upper()),
        retry_count, max_retries,
        security_tier=str(policy.get("security_tier") or "INTERNAL"),
        checkpoint_available=bool(checkpoint), checkpoint_authorized=checkpoint_authorized,
        substitute_available=bool(substitute_principal_id), substitute_authorized=substitute_authorized,
        failed_roles=failed_roles, required_roles=required_roles,
        quorum=int(policy.get("quorum") or 0), arrived_count=len(arrivals),
        timed_out=requested_human_review or bool(deadline and now >= deadline), deadline_at=deadline, now=now,
        escalation_available=requested_human_review or bool(policy.get("escalation_enabled", True)),
        human_decision_available=True,
    )
    if not decision.allowed:
        raise IdentityError(decision.message)
    action_name = str(decision.action or "").upper()
    requested_aliases = {
        "REVIEW": {"REVIEW", "RELEASE"},
        "RESTORE_CHECKPOINT": {"RESTORE_CHECKPOINT"},
        "SUBSTITUTE": {"SUBSTITUTE"},
        "RETRY": {"RETRY"},
        "HUMAN_DECISION_REQUIRED": {"HUMAN_DECISION_REQUIRED", "ESCALATE", "TIMEOUT"},
        "WAIT": {"WAIT"},
    }
    if selected and selected not in requested_aliases.get(action_name, {action_name}):
        raise IdentityError("Barrier recovery action is not currently available")
    if action_name == "WAIT":
        return {
            "barrier_id": barrier_id, **decision.as_dict(), "action": "WAIT",
            "next_status": str(row.get("status") or ""), "changed": False,
            "substitute_principal_id": None, "checkpoint_id": checkpoint_id or None,
        }
    policy["retry_count"] = retry_count + (1 if action_name == "RETRY" else 0)
    policy["max_retries"] = max_retries
    if substitute_principal_id:
        policy["substitute_principal_id"] = substitute_principal_id[:128]
        policy["substitutions"] = list(policy.get("substitutions") or []) + [{
            "principal_id": substitute_principal_id[:128], "actor": principal_id,
            "failed_roles": list(failed_roles), "at": _iso(now),
        }]
        failed_principals = set(_policy_values(policy.get("failed_principals")))
        failed_role_set = set(failed_roles)
        replacement_applied = False
        for participant in snapshot:
            if not isinstance(participant, dict):
                continue
            role = str(
                participant.get("role") or participant.get("participant_role")
                or participant.get("participantRole") or ""
            )
            identity = str(participant.get("principal_id") or participant.get("agent_id") or "")
            if identity in failed_principals or role in failed_role_set:
                participant["principal_id"] = substitute_principal_id
                participant["substituted_for"] = participant.get("substituted_for") or role
                replacement_applied = True
                break
        if not replacement_applied:
            raise IdentityError("Barrier substitute has no failed participant target")
        policy["participant_snapshot"] = snapshot
    policy["last_recovery"] = {"action": action_name, "actor": principal_id, "reason": reason[:2000]}
    next_status = {"RETRY": "WAITING", "RESTORE_CHECKPOINT": "WAITING", "SUBSTITUTE": "WAITING", "REVIEW": "REVIEW_REQUIRED", "HUMAN_DECISION_REQUIRED": "REVIEW_REQUIRED"}.get(action_name, "REVIEW_REQUIRED")
    def _persist_recovery(tx: Any) -> bool:
        locked = _row(tx.query_one(
            "SELECT STATUS, RETRY_COUNT FROM CX_BARRIERS WHERE BARRIER_ID = :barrier_id FOR UPDATE",
            {"barrier_id": barrier_id},
        ))
        if not locked or str(locked.get("status") or "") != str(row.get("status") or ""):
            raise IdentityError("Barrier changed concurrently")
        if int(locked.get("retry_count") or 0) != int(row.get("retry_count") or 0):
            raise IdentityError("Barrier recovery version changed concurrently")
        if action_name == "RESTORE_CHECKPOINT" and checkpoint:
            run_changed = tx.execute(
                "UPDATE GRAPH_RUNS SET CURRENT_CHECKPOINT_ID = :checkpoint_id, STATUS = 'WAITING', "
                "ERROR_CODE = NULL, ERROR_MESSAGE = NULL, UPDATED_AT = CURRENT_TIMESTAMP "
                "WHERE RUN_ID = :run_id AND STATUS NOT IN ('SUCCEEDED','CANCELLED')",
                {"checkpoint_id": checkpoint_id, "run_id": row.get("run_id")},
            )
            if run_changed <= 0:
                raise IdentityError("Graph Run checkpoint restoration failed")
        return tx.execute(
            "UPDATE CX_BARRIERS SET STATUS = :status, POLICY_JSON = :policy, LAST_RECOVERY_ACTION = :action, "
            "RECOVERY_REASON = :reason, RETRY_COUNT = :retry_count, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE BARRIER_ID = :barrier_id AND STATUS = :current_status AND RETRY_COUNT = :current_retry_count",
            {"status": next_status, "policy": _json(policy), "barrier_id": barrier_id,
             "current_status": row.get("status"), "action": action_name,
             "reason": reason[:2000], "retry_count": policy["retry_count"],
             "current_retry_count": int(row.get("retry_count") or 0)},
        ) > 0
    changed = connection.execute_transaction_callback(_persist_recovery)
    if not changed:
        raise IdentityError("Barrier changed concurrently")
    _audit(principal_id, "BARRIER_RECOVER_" + action_name, "BARRIER", barrier_id, "ALLOW", reason)
    return {"barrier_id": barrier_id, **decision.as_dict(), "action": action_name, "next_status": next_status, "substitute_principal_id": substitute_principal_id or None, "checkpoint_id": checkpoint_id or None}


def _audit(principal_id: Optional[str], action: str, resource_type: str, resource_id: str, outcome: str, reason: str) -> None:
    try:
        connection.execute("INSERT INTO CX_SECURITY_EVENTS(EVENT_ID, PRINCIPAL_ID, ACTOR_TYPE, ACTION_NAME, RESOURCE_TYPE, RESOURCE_ID, OUTCOME, REASON, DETAIL_JSON) VALUES (:event_id, :principal_id, :actor_type, :action_name, :resource_type, :resource_id, :outcome, :reason, :detail_json)", {"event_id": _id("SE"), "principal_id": principal_id, "actor_type": "HUMAN" if principal_id and str(principal_id).startswith("HP_") else "SYSTEM", "action_name": action, "resource_type": resource_type, "resource_id": resource_id, "outcome": outcome, "reason": reason[:2000], "detail_json": "{}"})
    except Exception:
        # Security event failures must not turn a successful business result
        # into an untraceable response; callers can inspect the DB health gate.
        pass


def _audit_tx(tx: Any, principal_id: Optional[str], action: str, resource_type: str,
              resource_id: str, outcome: str, reason: str) -> None:
    """Write a required audit event through an existing transaction object."""
    tx.execute(
        "INSERT INTO CX_SECURITY_EVENTS(EVENT_ID, PRINCIPAL_ID, ACTOR_TYPE, ACTION_NAME, RESOURCE_TYPE, RESOURCE_ID, OUTCOME, REASON, DETAIL_JSON) "
        "VALUES (:event_id, :principal_id, :actor_type, :action_name, :resource_type, :resource_id, :outcome, :reason, :detail_json)",
        {
            "event_id": _id("SE"), "principal_id": principal_id,
            "actor_type": "HUMAN" if principal_id and str(principal_id).startswith("HP_") else "SYSTEM",
            "action_name": action, "resource_type": resource_type, "resource_id": resource_id,
            "outcome": outcome, "reason": str(reason or "")[:2000], "detail_json": "{}",
        },
    )
