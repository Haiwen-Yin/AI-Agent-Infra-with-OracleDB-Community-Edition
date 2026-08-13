"""Database-authoritative Agent compliance services for v4.3.4.

This module deliberately keeps policy evaluation deterministic.  An Agent,
adapter, or LLM can submit evidence or an advisory explanation, but only a
validated evidence record and a versioned rule can change the authoritative
posture or control state.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api, cursor_pagination


REGISTRATION_STATES = frozenset({"PENDING_CONFIRMATION", "PENDING_ACTIVATION", "ACTIVE", "DISABLED"})
RUNTIME_STATES = frozenset({"NEVER_SEEN", "ONLINE", "IDLE", "STALE", "OFFLINE"})
POSTURE_STATES = frozenset({"UNKNOWN", "COMPLIANT", "DEGRADED", "NON_COMPLIANT"})
CONTROL_STATES = frozenset({"NORMAL", "RESTRICTED", "QUARANTINED", "DISABLED"})
EVIDENCE_STRENGTHS = frozenset({"MANAGED_RUNTIME", "SIGNED_ADAPTER", "BOUNDARY_ONLY"})
AUTOMATIC_RULES = frozenset({"CREDENTIAL_REUSE", "IDENTITY_BINDING_CONFLICT", "PROFILE_DIGEST_MISMATCH", "FENCING_BYPASS"})
SEED_PROFILES = (
    ("general-restricted", "General Restricted", {"locked_fields": ["database", "network", "secrets"], "controls": {"database": "gateway_only", "network": "allowlist", "secrets": "broker_only"}}),
    ("code-development", "Code Development", {"locked_fields": ["database", "secrets"], "controls": {"database": "read_scoped", "secrets": "broker_only", "commands": "approved_workspace"}}),
    ("production-operations", "Production Operations", {"locked_fields": ["database", "approval", "commands"], "controls": {"database": "least_privilege", "approval": "required", "commands": "allowlist"}}),
    ("sensitive-data-analysis", "Sensitive Data Analysis", {"locked_fields": ["data", "export", "retention"], "controls": {"data": "classified", "export": "approved", "retention": "evidence_required"}}),
    ("security-review", "Security Review", {"locked_fields": ["network", "tools", "audit"], "controls": {"network": "isolated", "tools": "allowlist", "audit": "immutable"}}),
)
COMPLIANCE_SERVICE_ID = "SYSTEM_COMPLIANCE"
COMPLIANCE_ADMIN_AGENT_ID = "SYSTEM_COMPLIANCE_ADMIN"


class ComplianceError(ValueError):
    """Safe compliance-domain error."""


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{str(key).lower(): value for key, value in dict(row).items()} for row in rows]


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None


def _limit(limit: int) -> tuple[str, Dict[str, Any]]:
    value = max(1, min(int(limit), 500))
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"}:
        return " LIMIT :limit", {"limit": value}
    return " FETCH FIRST :limit ROWS ONLY", {"limit": value}


def _require(actor: str, action: str) -> None:
    if identity_api.effective_access(actor, action).get("decision") != "ALLOW":
        raise PermissionError("compliance permission denied")


def _visible(actor: str, agent_id: str) -> None:
    if not identity_api._agent_visible_to(actor, agent_id):
        raise PermissionError("Agent is outside the delegated scope")


def _active_human_tx(tx: Any, principal_id: str) -> None:
    """Keep approval decisions with a live Human Principal, never an Agent."""
    row = _row(tx.query_one(
        "SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id",
        {"principal_id": principal_id},
    ))
    if not row or str(row.get("principal_type") or "").upper() != "HUMAN" or str(row.get("status") or "").upper() != "ACTIVE":
        raise PermissionError("A distinct active Human approver is required")


def _enterprise_enabled() -> bool:
    try:
        from . import edition_features
        return bool(edition_features.has_feature("compliance"))
    except (ImportError, AttributeError):
        # Source-tree development has no generated edition manifest.  Keep the
        # service testable while packaged Community editions fail closed.
        return True


def enterprise_required() -> None:
    if not _enterprise_enabled():
        raise ComplianceError("Enterprise compliance capability is unavailable")


def _agent_row(agent_id: str, tx: Any = None) -> Dict[str, Any]:
    query = "SELECT PRINCIPAL_ID, PRINCIPAL_TYPE, STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID = :agent_id"
    row = _row(tx.query_one(query, {"agent_id": agent_id}) if tx else connection.execute_query_one(query, {"agent_id": agent_id}))
    if not row or str(row.get("principal_type") or "").upper() != "AGENT":
        raise ComplianceError("Agent is unavailable")
    return row


def _posture_row(agent_id: str, instance_id: str = "", tx: Any = None, lock: bool = False) -> Optional[Dict[str, Any]]:
    query = (
        "SELECT POSTURE_ID, AGENT_ID, INSTANCE_ID, REGISTRATION_STATE, RUNTIME_STATE, POSTURE_STATE, "
        "CONTROL_STATE, EVIDENCE_STRENGTH, PROFILE_VERSION_ID, ACTIVATION_ID, VERSION, GRACE_UNTIL "
        "FROM CX_AGENT_POSTURES WHERE AGENT_ID = :agent_id AND "
        "((INSTANCE_ID IS NULL AND :instance_id IS NULL) OR INSTANCE_ID = :instance_id)"
    )
    if lock:
        query += " FOR UPDATE"
    params = {"agent_id": agent_id, "instance_id": instance_id or None}
    return _row(tx.query_one(query, params) if tx else connection.execute_query_one(query, params))


def _audit_tx(tx: Any, actor: str, action: str, resource_type: str, resource_id: str, outcome: str, reason: str) -> None:
    identity_api._audit_tx(tx, actor, action, resource_type, resource_id, outcome, reason[:2000])


def _ensure_posture_tx(tx: Any, agent_id: str, *, registration: str = "PENDING_ACTIVATION", profile_version_id: str = "", evidence_strength: str = "BOUNDARY_ONLY") -> Dict[str, Any]:
    existing = _posture_row(agent_id, tx=tx, lock=True)
    if existing:
        return existing
    posture_id = _id("POST")
    tx.execute(
        "INSERT INTO CX_AGENT_POSTURES(POSTURE_ID, AGENT_ID, REGISTRATION_STATE, RUNTIME_STATE, POSTURE_STATE, "
        "CONTROL_STATE, EVIDENCE_STRENGTH, PROFILE_VERSION_ID, VERSION) VALUES "
        "(:posture_id, :agent_id, :registration_state, 'NEVER_SEEN', 'UNKNOWN', 'NORMAL', :evidence_strength, :profile_version_id, 1)",
        {"posture_id": posture_id, "agent_id": agent_id, "registration_state": registration,
         "evidence_strength": evidence_strength, "profile_version_id": profile_version_id or None},
    )
    return _posture_row(agent_id, tx=tx, lock=True) or {"posture_id": posture_id, "version": 1}


def _canonical_profile_content(content: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(content, dict):
        raise ComplianceError("Profile content must be an object")
    serialized = _json(content)
    if len(serialized) > 200_000 or any(key in serialized.lower() for key in ("password", "private_key", "client_secret", "access_token")):
        raise ComplianceError("Profile content is invalid or contains a secret-like field")
    locked = content.get("locked_fields", [])
    if not isinstance(locked, list) or any(not isinstance(item, str) or not item.strip() for item in locked):
        raise ComplianceError("Profile locked_fields must be a string list")
    return json.loads(serialized)


def _profile_content(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value or "{}"))
    except (TypeError, ValueError) as exc:
        raise ComplianceError("Profile content is malformed") from exc


def _validate_profile_publication_tx(tx: Any, version: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a bounded parent chain and enforce parent locked fields."""
    content = _canonical_profile_content(_profile_content(version.get("content_json")))
    parent_id = str(version.get("parent_version_id") or "")
    visited = {str(version.get("profile_version_id") or "")}
    depth = 0
    while parent_id:
        depth += 1
        if depth > 8 or parent_id in visited:
            raise ComplianceError("Profile inheritance cycle or excessive depth")
        visited.add(parent_id)
        parent = _row(tx.query_one(
            "SELECT PROFILE_VERSION_ID,PARENT_VERSION_ID,CONTENT_JSON,STATUS FROM CX_AGENT_PROFILE_VERSIONS "
            "WHERE PROFILE_VERSION_ID=:id", {"id": parent_id}))
        if not parent or str(parent.get("status") or "").upper() != "PUBLISHED":
            raise ComplianceError("Profile parent must be published")
        parent_content = _canonical_profile_content(_profile_content(parent.get("content_json")))
        for field in parent_content.get("locked_fields", []):
            if field in content and content[field] != parent_content.get(field):
                raise ComplianceError("Profile changes a parent locked field")
        parent_id = str(parent.get("parent_version_id") or "")
    return content


def _active_profile_tx(tx: Any, agent_id: str) -> str:
    row = _row(tx.query_one(
        "SELECT a.PROFILE_VERSION_ID FROM CX_AGENT_PROFILE_ASSIGNMENTS a "
        "JOIN CX_AGENT_PROFILE_VERSIONS v ON v.PROFILE_VERSION_ID=a.PROFILE_VERSION_ID "
        "WHERE a.AGENT_ID=:agent_id AND a.STATUS='ACTIVE' AND v.STATUS='PUBLISHED' "
        "ORDER BY a.CREATED_AT DESC FETCH FIRST 1 ROWS ONLY", {"agent_id": agent_id}))
    return str((row or {}).get("profile_version_id") or "")


def list_postures(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    _require(actor, "agents.read")
    suffix, params = _limit(limit)
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = (
            "SELECT p.POSTURE_ID,p.AGENT_ID,p.INSTANCE_ID,p.REGISTRATION_STATE,p.RUNTIME_STATE,p.POSTURE_STATE,"
            "p.CONTROL_STATE,p.EVIDENCE_STRENGTH,p.PROFILE_VERSION_ID,p.LAST_EVALUATED_AT,p.GRACE_UNTIL,p.UPDATED_AT "
            "FROM CX_AGENT_POSTURES p ORDER BY p.UPDATED_AT DESC" + suffix
        )
    else:
        params["actor"] = actor
        query = (
            "SELECT DISTINCT p.POSTURE_ID,p.AGENT_ID,p.INSTANCE_ID,p.REGISTRATION_STATE,p.RUNTIME_STATE,p.POSTURE_STATE,"
            "p.CONTROL_STATE,p.EVIDENCE_STRENGTH,p.PROFILE_VERSION_ID,p.LAST_EVALUATED_AT,p.GRACE_UNTIL,p.UPDATED_AT "
            "FROM CX_AGENT_POSTURES p JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=p.AGENT_ID "
            "WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE' ORDER BY p.UPDATED_AT DESC" + suffix
        )
    return _rows(connection.execute_query(query, params))


def list_postures_cursor(actor: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    """Return posture rows with principal-bound opaque pagination."""
    _require(actor, "agents.read")
    context = cursor_pagination.resolve(actor, "compliance_postures", {}, "posture_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "compliance_postures", "sort_key": "posture_id:asc"})
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after = str(context["position"].get("posture_id") or "")
    after_clause = " AND p.POSTURE_ID>:after" if after else ""
    if after:
        params["after"] = after
    columns = ("p.POSTURE_ID,p.AGENT_ID,p.INSTANCE_ID,p.REGISTRATION_STATE,p.RUNTIME_STATE,p.POSTURE_STATE,"
               "p.CONTROL_STATE,p.EVIDENCE_STRENGTH,p.PROFILE_VERSION_ID,p.LAST_EVALUATED_AT,p.GRACE_UNTIL,p.UPDATED_AT")
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT " + columns + " FROM CX_AGENT_POSTURES p WHERE 1=1" + after_clause + " ORDER BY p.POSTURE_ID" + _limit(int(context["page_size"]) + 1)[0]
    else:
        params["actor"] = actor
        query = ("SELECT DISTINCT " + columns + " FROM CX_AGENT_POSTURES p JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=p.AGENT_ID "
                 "WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'" + after_clause + " ORDER BY p.POSTURE_ID" + _limit(int(context["page_size"]) + 1)[0])
    return cursor_pagination.page(_rows(connection.execute_query(query, params)), context,
                                  lambda item: {"posture_id": str(item["posture_id"])})


def posture_detail(actor: str, agent_id: str) -> Dict[str, Any]:
    _require(actor, "agents.read")
    _visible(actor, agent_id)
    posture = _posture_row(agent_id)
    if not posture:
        return {"agent_id": agent_id, "registration_state": "PENDING_ACTIVATION", "runtime_state": "NEVER_SEEN",
                "posture_state": "UNKNOWN", "control_state": "NORMAL", "evidence_strength": "BOUNDARY_ONLY"}
    return posture


def runtime_posture(agent_id: str) -> Dict[str, Any]:
    """Return only the caller's own non-sensitive posture projection."""
    posture = _posture_row(agent_id)
    if not posture:
        raise ComplianceError("Agent posture is unavailable")
    return {key: posture.get(key) for key in (
        "agent_id", "registration_state", "runtime_state", "posture_state", "control_state",
        "evidence_strength", "profile_version_id", "activation_id", "last_evaluated_at", "grace_until",
    )}


def list_profiles(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    enterprise_required()
    _require(actor, "agents.read")
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT p.PROFILE_ID,p.PROFILE_KEY,p.DISPLAY_NAME,p.STATUS,v.PROFILE_VERSION_ID,v.VERSION_LABEL,v.CONTENT_DIGEST,"
        "v.STATUS AS VERSION_STATUS,v.PUBLISHED_AT,v.CREATED_AT FROM CX_AGENT_PROFILES p "
        "LEFT JOIN CX_AGENT_PROFILE_VERSIONS v ON v.PROFILE_ID=p.PROFILE_ID "
        "ORDER BY p.CREATED_AT DESC,v.CREATED_AT DESC" + suffix, params))


def list_profiles_cursor(actor: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.read")
    context = cursor_pagination.resolve(actor, "compliance_profiles", {}, "profile_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "compliance_profiles", "sort_key": "profile_id:asc"})
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after = str(context["position"].get("profile_id") or "")
    clause = " WHERE p.PROFILE_ID>:after" if after else ""
    if after:
        params["after"] = after
    rows = connection.execute_query(
        "SELECT p.PROFILE_ID,p.PROFILE_KEY,p.DISPLAY_NAME,p.STATUS,v.PROFILE_VERSION_ID,v.VERSION_LABEL,v.CONTENT_DIGEST,"
        "v.STATUS AS VERSION_STATUS,v.PUBLISHED_AT,v.CREATED_AT FROM CX_AGENT_PROFILES p LEFT JOIN CX_AGENT_PROFILE_VERSIONS v "
        "ON v.PROFILE_ID=p.PROFILE_ID" + clause + " ORDER BY p.PROFILE_ID,v.PROFILE_VERSION_ID" +
        _limit(int(context["page_size"]) + 1)[0], params,
    )
    result = cursor_pagination.page(_rows(rows), context, lambda item: {"profile_id": str(item["profile_id"])})
    try:
        total = _row(connection.execute_query_one("SELECT COUNT(*) AS CNT FROM CX_AGENT_PROFILES", {}))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def ensure_seed_profiles() -> int:
    """Create unassigned Enterprise baseline Profiles once, without widening authority."""
    if not _enterprise_enabled():
        return 0
    created = 0
    for profile_key, display_name, content in SEED_PROFILES:
        canonical = _json(_canonical_profile_content(content))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        profile_id = "AP_SEED_" + profile_key.replace("-", "_").upper()
        version_id = profile_id + "_V1"
        def work(tx: Any) -> bool:
            existing = _row(tx.query_one("SELECT PROFILE_ID FROM CX_AGENT_PROFILES WHERE PROFILE_KEY=:key FOR UPDATE", {"key": profile_key}))
            if existing:
                return False
            tx.execute(
                "INSERT INTO CX_AGENT_PROFILES(PROFILE_ID,PROFILE_KEY,DISPLAY_NAME,STATUS,CREATED_BY) "
                "VALUES (:profile_id,:profile_key,:display_name,'ACTIVE','SYSTEM_COMPLIANCE')",
                {"profile_id": profile_id, "profile_key": profile_key, "display_name": display_name})
            tx.execute(
                "INSERT INTO CX_AGENT_PROFILE_VERSIONS(PROFILE_VERSION_ID,PROFILE_ID,VERSION_LABEL,CONTENT_JSON,CONTENT_DIGEST,STATUS,CREATED_BY,PUBLISHED_AT) "
                "VALUES (:version_id,:profile_id,'v1',:content,:digest,'PUBLISHED','SYSTEM_COMPLIANCE',CURRENT_TIMESTAMP)",
                {"version_id": version_id, "profile_id": profile_id, "content": canonical, "digest": digest})
            return True
        if connection.execute_transaction_callback(work):
            created += 1
    return created


def ensure_compliance_admin_agent() -> bool:
    """Provision the inert, independently attributed Compliance Admin identity.

    This is deliberately only an identity and assignment seed.  It owns no
    database credential, no Human credential, and no control mutation path.
    A future advisory runtime must still enroll a separate bound credential
    before it can receive a Gateway instance or a short-lived token.
    """
    if not _enterprise_enabled():
        return False
    profile_version_id = "AP_SEED_GENERAL_RESTRICTED_V1"

    def work(tx: Any) -> bool:
        existing = _row(tx.query_one(
            "SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id FOR UPDATE",
            {"principal_id": COMPLIANCE_ADMIN_AGENT_ID},
        ))
        if existing:
            return False
        service = _row(tx.query_one(
            "SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id FOR UPDATE",
            {"principal_id": COMPLIANCE_SERVICE_ID},
        ))
        if not service:
            tx.execute(
                "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS,PORTAL_ACCESS,APP_ACCESS) "
                "VALUES (:principal_id,'SERVICE','Compliance Controller Service','ACTIVE','N','N')",
                {"principal_id": COMPLIANCE_SERVICE_ID},
            )
        tx.execute(
            "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS,PORTAL_ACCESS,APP_ACCESS) "
            "VALUES (:principal_id,'AGENT','Compliance Admin Agent','PENDING_ACTIVATION','N','N')",
            {"principal_id": COMPLIANCE_ADMIN_AGENT_ID},
        )
        tx.execute(
            "INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID,AGENT_ID,PRINCIPAL_ID,RELATIONSHIP_ROLE,STATUS) "
            "VALUES (:relationship_id,:agent_id,:service_id,'OPERATOR','ACTIVE')",
            {"relationship_id": _id("AR"), "agent_id": COMPLIANCE_ADMIN_AGENT_ID,
             "service_id": COMPLIANCE_SERVICE_ID},
        )
        profile = _row(tx.query_one(
            "SELECT PROFILE_VERSION_ID FROM CX_AGENT_PROFILE_VERSIONS WHERE PROFILE_VERSION_ID=:profile_version_id "
            "AND STATUS='PUBLISHED'", {"profile_version_id": profile_version_id},
        ))
        if not profile:
            raise ComplianceError("Compliance Admin Profile is unavailable")
        tx.execute(
            "INSERT INTO CX_AGENT_PROFILE_ASSIGNMENTS(ASSIGNMENT_ID,AGENT_ID,PROFILE_VERSION_ID,ENVIRONMENT,STATUS,ASSIGNED_BY,REASON) "
            "VALUES (:assignment_id,:agent_id,:profile_version_id,'system','ACTIVE',:service_id,'system-managed compliance advisory identity')",
            {"assignment_id": _id("APA"), "agent_id": COMPLIANCE_ADMIN_AGENT_ID,
             "profile_version_id": profile_version_id, "service_id": COMPLIANCE_SERVICE_ID},
        )
        _ensure_posture_tx(tx, COMPLIANCE_ADMIN_AGENT_ID, registration="PENDING_ACTIVATION",
                           profile_version_id=profile_version_id, evidence_strength="BOUNDARY_ONLY")
        _audit_tx(tx, COMPLIANCE_SERVICE_ID, "COMPLIANCE_SYSTEM_AGENT_PROVISION", "AGENT",
                  COMPLIANCE_ADMIN_AGENT_ID, "ALLOW", "independent advisory identity without credentials")
        return True

    return bool(connection.execute_transaction_callback(work))


def create_profile_draft(actor: str, profile_key: str, display_name: str, content: Dict[str, Any], reason: str,
                         parent_version_id: str = "") -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.manage")
    if not profile_key.strip() or not display_name.strip() or not reason.strip():
        raise ComplianceError("Profile key, name, and reason are required")
    canonical = _json(_canonical_profile_content(content))
    profile_id, version_id = _id("AP"), _id("APV")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one("SELECT PROFILE_ID FROM CX_AGENT_PROFILES WHERE PROFILE_KEY=:profile_key FOR UPDATE", {"profile_key": profile_key[:128]}))
        active_profile_id = str((existing or {}).get("profile_id") or profile_id)
        if not existing:
            tx.execute("INSERT INTO CX_AGENT_PROFILES(PROFILE_ID,PROFILE_KEY,DISPLAY_NAME,STATUS,CREATED_BY) VALUES (:profile_id,:profile_key,:display_name,'DRAFT',:actor)",
                       {"profile_id": active_profile_id, "profile_key": profile_key[:128], "display_name": display_name[:256], "actor": actor})
        tx.execute(
            "INSERT INTO CX_AGENT_PROFILE_VERSIONS(PROFILE_VERSION_ID,PROFILE_ID,VERSION_LABEL,PARENT_VERSION_ID,CONTENT_JSON,CONTENT_DIGEST,STATUS,CREATED_BY) "
            "VALUES (:version_id,:profile_id,:version_label,:parent_version_id,:content_json,:content_digest,'DRAFT',:actor)",
            {"version_id": version_id, "profile_id": active_profile_id, "version_label": "draft-" + version_id[-12:],
             "parent_version_id": parent_version_id or None, "content_json": canonical, "content_digest": digest, "actor": actor})
        _audit_tx(tx, actor, "COMPLIANCE_PROFILE_DRAFT", "AGENT_PROFILE", version_id, "ALLOW", reason)
        return {"profile_id": active_profile_id, "profile_version_id": version_id, "content_digest": digest, "status": "DRAFT"}
    return connection.execute_transaction_callback(work)


def publish_profile(actor: str, profile_version_id: str, reason: str) -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.manage")
    if not reason.strip():
        raise ComplianceError("Publication reason is required")
    def work(tx: Any) -> Dict[str, Any]:
        version = _row(tx.query_one("SELECT PROFILE_VERSION_ID,PROFILE_ID,STATUS,CONTENT_JSON,CONTENT_DIGEST FROM CX_AGENT_PROFILE_VERSIONS WHERE PROFILE_VERSION_ID=:id FOR UPDATE", {"id": profile_version_id}))
        if not version or str(version.get("status") or "").upper() != "DRAFT":
            raise ComplianceError("Profile draft is unavailable")
        _validate_profile_publication_tx(tx, version)
        actual = hashlib.sha256(str(version.get("content_json") or "").encode("utf-8")).hexdigest()
        if actual != str(version.get("content_digest") or ""):
            raise ComplianceError("Profile digest mismatch")
        changed = tx.execute("UPDATE CX_AGENT_PROFILE_VERSIONS SET STATUS='PUBLISHED',PUBLISHED_AT=CURRENT_TIMESTAMP WHERE PROFILE_VERSION_ID=:id AND STATUS='DRAFT'", {"id": profile_version_id})
        if changed != 1:
            raise ComplianceError("Profile changed concurrently")
        tx.execute("UPDATE CX_AGENT_PROFILES SET STATUS='ACTIVE',UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:profile_id", {"profile_id": version["profile_id"]})
        _audit_tx(tx, actor, "COMPLIANCE_PROFILE_PUBLISH", "AGENT_PROFILE", profile_version_id, "ALLOW", reason)
        return {"profile_version_id": profile_version_id, "profile_id": version["profile_id"], "status": "PUBLISHED", "content_digest": actual}
    return connection.execute_transaction_callback(work)


def assign_profile(actor: str, agent_id: str, profile_version_id: str, environment: str, reason: str) -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.manage")
    _visible(actor, agent_id)
    if not environment.strip() or not reason.strip():
        raise ComplianceError("Environment and reason are required")
    assignment_id = _id("APA")
    def work(tx: Any) -> Dict[str, Any]:
        _agent_row(agent_id, tx)
        version = _row(tx.query_one("SELECT PROFILE_VERSION_ID,STATUS FROM CX_AGENT_PROFILE_VERSIONS WHERE PROFILE_VERSION_ID=:id FOR UPDATE", {"id": profile_version_id}))
        if not version or str(version.get("status") or "").upper() != "PUBLISHED":
            raise ComplianceError("Published Profile is required")
        tx.execute("UPDATE CX_AGENT_PROFILE_ASSIGNMENTS SET STATUS='SUPERSEDED',ENDED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent_id AND ENVIRONMENT=:environment AND STATUS='ACTIVE'", {"agent_id": agent_id, "environment": environment[:64]})
        tx.execute("INSERT INTO CX_AGENT_PROFILE_ASSIGNMENTS(ASSIGNMENT_ID,AGENT_ID,PROFILE_VERSION_ID,ENVIRONMENT,STATUS,ASSIGNED_BY,REASON) VALUES (:assignment_id,:agent_id,:profile_version_id,:environment,'ACTIVE',:actor,:reason)",
                   {"assignment_id": assignment_id, "agent_id": agent_id, "profile_version_id": profile_version_id, "environment": environment[:64], "actor": actor, "reason": reason[:2000]})
        posture = _ensure_posture_tx(tx, agent_id, profile_version_id=profile_version_id)
        tx.execute("UPDATE CX_AGENT_POSTURES SET PROFILE_VERSION_ID=:profile_version_id,POSTURE_STATE='UNKNOWN',UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 WHERE POSTURE_ID=:posture_id AND VERSION=:version", {"profile_version_id": profile_version_id, "posture_id": posture["posture_id"], "version": posture["version"]})
        _audit_tx(tx, actor, "COMPLIANCE_PROFILE_ASSIGN", "AGENT", agent_id, "ALLOW", reason)
        return {"assignment_id": assignment_id, "agent_id": agent_id, "profile_version_id": profile_version_id, "status": "ACTIVE"}
    return connection.execute_transaction_callback(work)


def activate_agent(actor: str, agent_id: str, profile_version_id: str, evidence_strength: str, baseline: Dict[str, Any], reason: str) -> Dict[str, Any]:
    _require(actor, "agents.manage")
    _visible(actor, agent_id)
    strength = str(evidence_strength or "").upper()
    if strength not in EVIDENCE_STRENGTHS or not reason.strip():
        raise ComplianceError("Activation evidence strength or reason is invalid")
    normalized = _json(baseline)
    if len(normalized) > 200_000:
        raise ComplianceError("Capability baseline is too large")
    activation_id = _id("ACT")
    baseline_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    def work(tx: Any) -> Dict[str, Any]:
        agent = _agent_row(agent_id, tx)
        if str(agent.get("status") or "").upper() in {"DISABLED", "QUARANTINED"}:
            raise ComplianceError("Agent cannot be activated")
        # A newly enrolled Agent must prove its own bound credential through
        # the Gateway.  A human may only refresh a previously active legacy
        # Agent; a page click is never activation proof for a new runtime.
        if str(agent.get("status") or "").upper() != "ACTIVE":
            raise ComplianceError("Pending Agent must complete Gateway activation proof")
        if profile_version_id:
            version = _row(tx.query_one("SELECT PROFILE_VERSION_ID,STATUS FROM CX_AGENT_PROFILE_VERSIONS WHERE PROFILE_VERSION_ID=:id", {"id": profile_version_id}))
            if not version or str(version.get("status") or "").upper() != "PUBLISHED":
                raise ComplianceError("Published Profile is required")
        tx.execute("UPDATE CX_AGENT_ACTIVATIONS SET STATUS='SUPERSEDED',SUPERSEDED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent_id AND STATUS='ACTIVE'", {"agent_id": agent_id})
        tx.execute("INSERT INTO CX_AGENT_ACTIVATIONS(ACTIVATION_ID,AGENT_ID,PROFILE_VERSION_ID,EVIDENCE_STRENGTH,BASELINE_JSON,BASELINE_DIGEST,STATUS,ACTIVATED_BY) VALUES (:activation_id,:agent_id,:profile_version_id,:evidence_strength,:baseline_json,:baseline_digest,'ACTIVE',:actor)",
                   {"activation_id": activation_id, "agent_id": agent_id, "profile_version_id": profile_version_id or None, "evidence_strength": strength, "baseline_json": normalized, "baseline_digest": baseline_digest, "actor": actor})
        posture = _ensure_posture_tx(tx, agent_id, registration="PENDING_ACTIVATION", profile_version_id=profile_version_id, evidence_strength=strength)
        tx.execute("UPDATE CX_AGENT_POSTURES SET REGISTRATION_STATE='ACTIVE',POSTURE_STATE='COMPLIANT',CONTROL_STATE='NORMAL',EVIDENCE_STRENGTH=:strength,PROFILE_VERSION_ID=:profile_version_id,ACTIVATION_ID=:activation_id,LAST_EVALUATED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 WHERE POSTURE_ID=:posture_id AND VERSION=:version", {"strength": strength, "profile_version_id": profile_version_id or None, "activation_id": activation_id, "posture_id": posture["posture_id"], "version": posture["version"]})
        tx.execute("UPDATE CX_PRINCIPALS SET STATUS='ACTIVE',UPDATED_AT=CURRENT_TIMESTAMP WHERE PRINCIPAL_ID=:agent_id", {"agent_id": agent_id})
        _audit_tx(tx, actor, "COMPLIANCE_AGENT_ACTIVATE", "AGENT", agent_id, "ALLOW", reason)
        return {"activation_id": activation_id, "agent_id": agent_id, "profile_version_id": profile_version_id or None, "baseline_digest": baseline_digest, "posture_state": "COMPLIANT"}
    return connection.execute_transaction_callback(work)


def activate_from_gateway(agent_id: str, baseline: Dict[str, Any], *, credential_type: str,
                          runtime: str = "", environment: str = "", security_domain_id: str = "") -> Dict[str, Any]:
    """Activate a pending Agent only after it proves its registered credential.

    The caller never selects the evidence strength, owner, domain, or Profile.
    Those fields are derived from stored enrollment and assignment authority.
    """
    if not isinstance(baseline, dict):
        raise ComplianceError("Activation baseline must be an object")
    declared = _json(baseline)
    if len(declared) > 100_000:
        raise ComplianceError("Activation baseline is too large")
    credential_type = str(credential_type or "").upper()
    if credential_type not in {"CLIENT_SECRET", "ED25519"}:
        raise ComplianceError("Activation credential is invalid")
    activation_id = _id("ACT")

    def work(tx: Any) -> Dict[str, Any]:
        agent = _agent_row(agent_id, tx)
        state = str(agent.get("status") or "").upper()
        if state != "PENDING_ACTIVATION":
            raise ComplianceError("Agent is not awaiting activation")
        enrollment = _row(tx.query_one(
            "SELECT SECURITY_DOMAIN_ID,ENVIRONMENT,RUNTIME,RISK_TIER FROM CX_ENROLLMENT_GRANTS "
            "WHERE AGENT_ID=:agent_id AND STATUS='ACTIVE' ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY",
            {"agent_id": agent_id}))
        if not enrollment:
            raise ComplianceError("Enrollment authority is unavailable")
        if runtime and str(enrollment.get("runtime") or "") and runtime != str(enrollment.get("runtime")):
            raise ComplianceError("Activation runtime does not match enrollment")
        if environment and str(enrollment.get("environment") or "") and environment != str(enrollment.get("environment")):
            raise ComplianceError("Activation environment does not match enrollment")
        if security_domain_id and str(enrollment.get("security_domain_id") or "") and security_domain_id != str(enrollment.get("security_domain_id")):
            raise ComplianceError("Activation domain does not match enrollment")
        profile_version_id = _active_profile_tx(tx, agent_id)
        strength = "SIGNED_ADAPTER" if credential_type == "ED25519" else "BOUNDARY_ONLY"
        server_baseline = {
            "declared": json.loads(declared),
            "runtime": str(enrollment.get("runtime") or runtime),
            "environment": str(enrollment.get("environment") or environment),
            "security_domain_id": str(enrollment.get("security_domain_id") or security_domain_id),
            "credential_type": credential_type,
            "evidence_strength": strength,
        }
        canonical = _json(server_baseline)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        tx.execute("UPDATE CX_AGENT_ACTIVATIONS SET STATUS='SUPERSEDED',SUPERSEDED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent_id AND STATUS='ACTIVE'", {"agent_id": agent_id})
        tx.execute(
            "INSERT INTO CX_AGENT_ACTIVATIONS(ACTIVATION_ID,AGENT_ID,PROFILE_VERSION_ID,EVIDENCE_STRENGTH,BASELINE_JSON,BASELINE_DIGEST,STATUS,ACTIVATED_BY) "
            "VALUES (:activation_id,:agent_id,:profile_version_id,:strength,:baseline,:digest,'ACTIVE',:actor)",
            {"activation_id": activation_id, "agent_id": agent_id, "profile_version_id": profile_version_id or None,
             "strength": strength, "baseline": canonical, "digest": digest, "actor": "GATEWAY:" + credential_type})
        evidence_id = _id("EVD")
        tx.execute(
            "INSERT INTO CX_AGENT_POSTURE_EVIDENCE(EVIDENCE_ID,AGENT_ID,EVIDENCE_TYPE,PROVIDER,NONCE,PAYLOAD_JSON,PAYLOAD_DIGEST) "
            "VALUES (:evidence_id,:agent_id,'ACTIVATION_PROOF','GATEWAY',:nonce,:payload,:digest)",
            {"evidence_id": evidence_id, "agent_id": agent_id, "nonce": "activation:" + activation_id,
             "payload": _json({"activation_id": activation_id, "credential_type": credential_type, "baseline_digest": digest}),
             "digest": _digest({"activation_id": activation_id, "credential_type": credential_type, "baseline_digest": digest})})
        posture = _ensure_posture_tx(tx, agent_id, registration="PENDING_ACTIVATION", profile_version_id=profile_version_id, evidence_strength=strength)
        tx.execute(
            "UPDATE CX_AGENT_POSTURES SET REGISTRATION_STATE='ACTIVE',RUNTIME_STATE='NEVER_SEEN',POSTURE_STATE='COMPLIANT',"
            "CONTROL_STATE='NORMAL',EVIDENCE_STRENGTH=:strength,PROFILE_VERSION_ID=:profile_version_id,ACTIVATION_ID=:activation_id,"
            "LAST_EVIDENCE_AT=CURRENT_TIMESTAMP,LAST_EVALUATED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 "
            "WHERE POSTURE_ID=:posture_id AND VERSION=:version",
            {"strength": strength, "profile_version_id": profile_version_id or None, "activation_id": activation_id,
             "posture_id": posture["posture_id"], "version": posture["version"]})
        changed = tx.execute("UPDATE CX_PRINCIPALS SET STATUS='ACTIVE',UPDATED_AT=CURRENT_TIMESTAMP WHERE PRINCIPAL_ID=:agent_id AND STATUS='PENDING_ACTIVATION'", {"agent_id": agent_id})
        if changed != 1:
            raise ComplianceError("Agent activation changed concurrently")
        _audit_tx(tx, agent_id, "COMPLIANCE_GATEWAY_ACTIVATE", "AGENT", agent_id, "ALLOW", "registered credential proof")
        return {"activation_id": activation_id, "agent_id": agent_id, "profile_version_id": profile_version_id or None,
                "evidence_strength": strength, "baseline_digest": digest, "posture_state": "COMPLIANT"}
    return connection.execute_transaction_callback(work)


def observe_gateway_heartbeat(agent_id: str, instance_id: str) -> None:
    """Project a successful authenticated heartbeat without treating it as a violation signal."""
    connection.execute(
        "UPDATE CX_AGENT_POSTURES SET RUNTIME_STATE='ONLINE',LAST_EVIDENCE_AT=CURRENT_TIMESTAMP,"
        "UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 WHERE AGENT_ID=:agent_id AND INSTANCE_ID IS NULL",
        {"agent_id": agent_id})


def submit_evidence(agent_id: str, evidence_type: str, payload: Dict[str, Any], *, instance_id: str = "", provider: str = "BOUNDARY", nonce: str = "", expires_at: str = "") -> Dict[str, Any]:
    """Record bounded, attributable evidence from a verified caller boundary."""
    if not agent_id or not evidence_type or not isinstance(payload, dict):
        raise ComplianceError("Evidence identity, type, and object payload are required")
    serialized = _json(payload)
    if len(serialized) > 100_000:
        raise ComplianceError("Evidence payload is too large")
    evidence_id = _id("EVD")
    payload_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    def work(tx: Any) -> Dict[str, Any]:
        _agent_row(agent_id, tx)
        if nonce:
            duplicate = _row(tx.query_one("SELECT EVIDENCE_ID FROM CX_AGENT_POSTURE_EVIDENCE WHERE AGENT_ID=:agent_id AND NONCE=:nonce FOR UPDATE", {"agent_id": agent_id, "nonce": nonce[:256]}))
            if duplicate:
                return {"evidence_id": duplicate["evidence_id"], "idempotent": True, "payload_digest": payload_digest}
        tx.execute("INSERT INTO CX_AGENT_POSTURE_EVIDENCE(EVIDENCE_ID,AGENT_ID,INSTANCE_ID,EVIDENCE_TYPE,PROVIDER,NONCE,PAYLOAD_JSON,PAYLOAD_DIGEST,EXPIRES_AT) VALUES (:evidence_id,:agent_id,:instance_id,:evidence_type,:provider,:nonce,:payload_json,:payload_digest,:expires_at)",
                   {"evidence_id": evidence_id, "agent_id": agent_id, "instance_id": instance_id or None, "evidence_type": evidence_type[:64], "provider": provider[:64], "nonce": nonce[:256] or None, "payload_json": serialized, "payload_digest": payload_digest, "expires_at": expires_at or None})
        posture = _ensure_posture_tx(tx, agent_id)
        tx.execute(
            "UPDATE CX_AGENT_POSTURES SET RUNTIME_STATE='ONLINE',LAST_EVIDENCE_AT=CURRENT_TIMESTAMP,"
            "POSTURE_STATE=CASE WHEN POSTURE_STATE IN ('UNKNOWN','DEGRADED') THEN 'COMPLIANT' ELSE POSTURE_STATE END,"
            "LAST_EVALUATED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 "
            "WHERE POSTURE_ID=:posture_id AND VERSION=:version",
            {"posture_id": posture["posture_id"], "version": posture["version"]})
        return {"evidence_id": evidence_id, "payload_digest": payload_digest, "idempotent": False}
    return connection.execute_transaction_callback(work)


def submit_gateway_evidence(agent_id: str, instance_id: str, evidence_type: str, payload: Dict[str, Any], *,
                            nonce: str = "", expires_at: str = "") -> Dict[str, Any]:
    """Record Agent evidence only after Gateway instance authentication.

    The instance check prevents a token for one runtime from attaching claims
    to another runtime or from using the generic evidence API as an authority
    bypass.  Gateway attribution proves boundary observation, not the
    unobserved internals of an external Agent process.
    """
    if not control_allows(agent_id, "evidence"):
        raise ComplianceError("Agent control state blocks evidence")
    instance = _row(connection.execute_query_one(
        "SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance_id AND AGENT_ID=:agent_id "
        "AND STATUS='ACTIVE' AND REVOKED_AT IS NULL AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
        {"instance_id": instance_id, "agent_id": agent_id}))
    if not instance:
        raise ComplianceError("Gateway instance is unavailable")
    return submit_evidence(agent_id, evidence_type, payload, instance_id=instance_id, provider="GATEWAY", nonce=nonce, expires_at=expires_at)


def submit_mcp_evidence(agent_id: str, evidence_type: str, payload: Dict[str, Any], *, nonce: str = "") -> Dict[str, Any]:
    """Record MCP boundary evidence without asserting a signed or managed runtime."""
    if not control_allows(agent_id, "evidence"):
        raise ComplianceError("Agent control state blocks evidence")
    agent = _agent_row(agent_id)
    if str(agent.get("status") or "").upper() != "ACTIVE":
        raise ComplianceError("Active Agent registration is required")
    return submit_evidence(agent_id, evidence_type, payload, provider="MCP_BOUNDARY", nonce=nonce)


def _open_finding_tx(tx: Any, agent_id: str, rule_code: str, severity: str, reason: str, evidence_id: str = "", automatic_action: str = "") -> Dict[str, Any]:
    current = _row(tx.query_one("SELECT FINDING_ID,STATUS FROM CX_COMPLIANCE_FINDINGS WHERE AGENT_ID=:agent_id AND RULE_CODE=:rule_code AND STATUS IN ('OPEN','ACKNOWLEDGED','REMEDIATING') FOR UPDATE", {"agent_id": agent_id, "rule_code": rule_code}))
    if current:
        tx.execute("UPDATE CX_COMPLIANCE_FINDINGS SET LAST_OBSERVED_AT=CURRENT_TIMESTAMP,DETAIL=:detail,EVIDENCE_ID=COALESCE(:evidence_id,EVIDENCE_ID),UPDATED_AT=CURRENT_TIMESTAMP WHERE FINDING_ID=:id", {"detail": reason[:2000], "evidence_id": evidence_id or None, "id": current["finding_id"]})
        return {"finding_id": current["finding_id"], "idempotent": True}
    finding_id = _id("CF")
    tx.execute("INSERT INTO CX_COMPLIANCE_FINDINGS(FINDING_ID,AGENT_ID,RULE_CODE,RULE_VERSION,SEVERITY,STATUS,EVIDENCE_ID,DETAIL,AUTOMATIC_ACTION,FIRST_OBSERVED_AT,LAST_OBSERVED_AT) VALUES (:finding_id,:agent_id,:rule_code,'v4.3.4',:severity,'OPEN',:evidence_id,:detail,:automatic_action,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
               {"finding_id": finding_id, "agent_id": agent_id, "rule_code": rule_code[:64], "severity": severity[:32], "evidence_id": evidence_id or None, "detail": reason[:2000], "automatic_action": automatic_action[:32] or None})
    return {"finding_id": finding_id, "idempotent": False}


def report_deterministic_violation(actor: str, agent_id: str, rule_code: str, reason: str, evidence_id: str = "", automatic: bool = False) -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.operate")
    _visible(actor, agent_id)
    code = str(rule_code or "").upper()
    if code not in AUTOMATIC_RULES or not reason.strip():
        raise ComplianceError("Deterministic rule is invalid")
    if automatic and not str(actor).startswith("SYSTEM:COMPLIANCE_CONTROLLER"):
        raise PermissionError("Automatic compliance action is controller-only")
    def work(tx: Any) -> Dict[str, Any]:
        posture = _ensure_posture_tx(tx, agent_id)
        action = "QUARANTINE" if automatic else ""
        finding = _open_finding_tx(tx, agent_id, code, "HIGH", reason, evidence_id, action)
        control = "QUARANTINED" if automatic else str(posture.get("control_state") or "NORMAL")
        tx.execute("UPDATE CX_AGENT_POSTURES SET POSTURE_STATE='NON_COMPLIANT',CONTROL_STATE=:control,LAST_EVALUATED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 WHERE POSTURE_ID=:posture_id AND VERSION=:version", {"control": control, "posture_id": posture["posture_id"], "version": posture["version"]})
        if automatic:
            tx.execute("UPDATE CX_AGENT_INSTANCES SET STATUS='QUARANTINED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKE_REASON=:reason,FENCING_TOKEN=FENCING_TOKEN+1 WHERE AGENT_ID=:agent_id AND STATUS='ACTIVE'", {"reason": reason[:1000], "agent_id": agent_id})
            tx.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent_id AND REVOKED_AT IS NULL", {"agent_id": agent_id})
        _audit_tx(tx, actor, "COMPLIANCE_RULE_VIOLATION", "AGENT", agent_id, "ALLOW", reason)
        return {"agent_id": agent_id, **finding, "posture_state": "NON_COMPLIANT", "control_state": control}
    return connection.execute_transaction_callback(work)


def list_findings(actor: str, agent_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    enterprise_required()
    _require(actor, "agents.read")
    suffix, params = _limit(limit)
    if agent_id:
        _visible(actor, agent_id)
        params["agent_id"] = agent_id
        query = "SELECT FINDING_ID,AGENT_ID,RULE_CODE,RULE_VERSION,SEVERITY,STATUS,EVIDENCE_ID,DETAIL,AUTOMATIC_ACTION,FIRST_OBSERVED_AT,LAST_OBSERVED_AT,UPDATED_AT FROM CX_COMPLIANCE_FINDINGS WHERE AGENT_ID=:agent_id ORDER BY LAST_OBSERVED_AT DESC" + suffix
    elif identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT FINDING_ID,AGENT_ID,RULE_CODE,RULE_VERSION,SEVERITY,STATUS,EVIDENCE_ID,DETAIL,AUTOMATIC_ACTION,FIRST_OBSERVED_AT,LAST_OBSERVED_AT,UPDATED_AT FROM CX_COMPLIANCE_FINDINGS ORDER BY LAST_OBSERVED_AT DESC" + suffix
    else:
        params["actor"] = actor
        query = "SELECT DISTINCT f.FINDING_ID,f.AGENT_ID,f.RULE_CODE,f.RULE_VERSION,f.SEVERITY,f.STATUS,f.EVIDENCE_ID,f.DETAIL,f.AUTOMATIC_ACTION,f.FIRST_OBSERVED_AT,f.LAST_OBSERVED_AT,f.UPDATED_AT FROM CX_COMPLIANCE_FINDINGS f JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=f.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE' ORDER BY f.LAST_OBSERVED_AT DESC" + suffix
    return _rows(connection.execute_query(query, params))


def list_findings_cursor(actor: str, *, page_size: int = 20, cursor: str = "", agent_id: str = "") -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.read")
    if agent_id:
        _visible(actor, agent_id)
    filters = {"agent_id": agent_id}
    context = cursor_pagination.resolve(actor, "compliance_findings", filters, "finding_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "compliance_findings", "sort_key": "finding_id:asc"})
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after = str(context["position"].get("finding_id") or "")
    after_clause = " AND f.FINDING_ID>:after" if after else ""
    if after:
        params["after"] = after
    columns = ("f.FINDING_ID,f.AGENT_ID,f.RULE_CODE,f.RULE_VERSION,f.SEVERITY,f.STATUS,f.EVIDENCE_ID,f.DETAIL,"
               "f.AUTOMATIC_ACTION,f.FIRST_OBSERVED_AT,f.LAST_OBSERVED_AT,f.UPDATED_AT")
    if agent_id:
        params["agent_id"] = agent_id
        where = "f.AGENT_ID=:agent_id" + after_clause
        query = "SELECT " + columns + " FROM CX_COMPLIANCE_FINDINGS f WHERE " + where + " ORDER BY f.FINDING_ID" + _limit(int(context["page_size"]) + 1)[0]
    elif identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT " + columns + " FROM CX_COMPLIANCE_FINDINGS f WHERE 1=1" + after_clause + " ORDER BY f.FINDING_ID" + _limit(int(context["page_size"]) + 1)[0]
    else:
        params["actor"] = actor
        query = ("SELECT DISTINCT " + columns + " FROM CX_COMPLIANCE_FINDINGS f JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=f.AGENT_ID "
                 "WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'" + after_clause + " ORDER BY f.FINDING_ID" + _limit(int(context["page_size"]) + 1)[0])
    result = cursor_pagination.page(_rows(connection.execute_query(query, params)), context,
                                    lambda item: {"finding_id": str(item["finding_id"])})
    count_params = {key: value for key, value in params.items() if key not in {"limit", "after"}}
    if agent_id:
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_COMPLIANCE_FINDINGS f WHERE f.AGENT_ID=:agent_id"
    elif identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_COMPLIANCE_FINDINGS f"
    else:
        count_sql = ("SELECT COUNT(DISTINCT f.FINDING_ID) AS CNT FROM CX_COMPLIANCE_FINDINGS f JOIN CX_AGENT_RELATIONSHIPS r "
                     "ON r.AGENT_ID=f.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'")
    try:
        total = _row(connection.execute_query_one(count_sql, count_params))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def create_remediation(actor: str, finding_id: str, required_action: str, reason: str,
                       deadline_at: str = "") -> Dict[str, Any]:
    """Open one idempotent, structured remediation case for an active finding."""
    enterprise_required()
    _require(actor, "agents.operate")
    if not finding_id or not required_action.strip() or not reason.strip():
        raise ComplianceError("Finding, required action, and reason are required")
    case_id = _id("REM")
    def work(tx: Any) -> Dict[str, Any]:
        finding = _row(tx.query_one(
            "SELECT FINDING_ID,AGENT_ID,STATUS,RULE_CODE,SEVERITY FROM CX_COMPLIANCE_FINDINGS "
            "WHERE FINDING_ID=:finding_id FOR UPDATE", {"finding_id": finding_id}))
        if not finding or str(finding.get("status") or "").upper() not in {"OPEN", "ACKNOWLEDGED", "REMEDIATING"}:
            raise ComplianceError("Open compliance finding is required")
        _visible(actor, str(finding["agent_id"]))
        existing = _row(tx.query_one(
            "SELECT CASE_ID,STATUS FROM CX_COMPLIANCE_REMEDIATION_CASES WHERE FINDING_ID=:finding_id "
            "AND STATUS IN ('OPEN','ACKNOWLEDGED','REMEDIATING') FOR UPDATE", {"finding_id": finding_id}))
        if existing:
            return {"case_id": existing["case_id"], "agent_id": finding["agent_id"], "status": existing["status"], "idempotent": True}
        schema = {"type": "object", "required": ["evidence"], "additionalProperties": False,
                  "properties": {"evidence": {"type": "object"}, "summary": {"type": "string", "maxLength": 2000}}}
        tx.execute(
            "INSERT INTO CX_COMPLIANCE_REMEDIATION_CASES(CASE_ID,FINDING_ID,AGENT_ID,REQUIRED_ACTION,RESPONSE_SCHEMA_JSON,STATUS,DEADLINE_AT,CREATED_BY) "
            "VALUES (:case_id,:finding_id,:agent_id,:required_action,:schema,'OPEN',:deadline_at,:actor)",
            {"case_id": case_id, "finding_id": finding_id, "agent_id": finding["agent_id"],
             "required_action": required_action[:128], "schema": _json(schema), "deadline_at": deadline_at or None, "actor": actor})
        tx.execute("UPDATE CX_COMPLIANCE_FINDINGS SET STATUS='REMEDIATING',UPDATED_AT=CURRENT_TIMESTAMP WHERE FINDING_ID=:finding_id", {"finding_id": finding_id})
        _audit_tx(tx, actor, "COMPLIANCE_REMEDIATION_CREATE", "COMPLIANCE_FINDING", finding_id, "ALLOW", reason)
        return {"case_id": case_id, "agent_id": finding["agent_id"], "status": "OPEN", "idempotent": False}
    result = connection.execute_transaction_callback(work)
    if not result["idempotent"]:
        # Notification remains a delivery convenience.  The remediation row is
        # authoritative, and a retry is safely deduplicated by the existing key.
        identity_api.enqueue_notification(
            str(result["agent_id"]), "COMPLIANCE_REMEDIATION", "ACTION_REQUIRED",
            "compliance-remediation:" + str(result["case_id"]),
            {"case_id": result["case_id"], "finding_id": finding_id, "required_action": required_action[:128]},
            deadline_at=deadline_at or None,
        )
    return result


def respond_remediation(agent_id: str, case_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
    """Accept only an authenticated Agent's structured remediation evidence."""
    if not agent_id or not case_id or not isinstance(response, dict):
        raise ComplianceError("Agent, remediation case, and response are required")
    if not isinstance(response.get("evidence"), dict):
        raise ComplianceError("Structured remediation evidence is required")
    serialized = _json(response)
    if len(serialized) > 100_000:
        raise ComplianceError("Remediation response is too large")
    def work(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one(
            "SELECT CASE_ID,AGENT_ID,FINDING_ID,STATUS FROM CX_COMPLIANCE_REMEDIATION_CASES "
            "WHERE CASE_ID=:case_id FOR UPDATE", {"case_id": case_id}))
        if not row or str(row.get("agent_id") or "") != agent_id or str(row.get("status") or "").upper() not in {"OPEN", "ACKNOWLEDGED", "REMEDIATING"}:
            raise ComplianceError("Remediation case is unavailable")
        evidence_id = _id("EVD")
        evidence_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        tx.execute(
            "INSERT INTO CX_AGENT_POSTURE_EVIDENCE(EVIDENCE_ID,AGENT_ID,EVIDENCE_TYPE,PROVIDER,PAYLOAD_JSON,PAYLOAD_DIGEST) "
            "VALUES (:evidence_id,:agent_id,'REMEDIATION_RESPONSE','GATEWAY',:payload_json,:payload_digest)",
            {"evidence_id": evidence_id, "agent_id": agent_id, "payload_json": serialized, "payload_digest": evidence_digest},
        )
        tx.execute(
            "UPDATE CX_COMPLIANCE_REMEDIATION_CASES SET STATUS='ACKNOWLEDGED',RESPONSE_EVIDENCE_ID=:evidence_id,"
            "UPDATED_AT=CURRENT_TIMESTAMP WHERE CASE_ID=:case_id",
            {"case_id": case_id, "evidence_id": evidence_id},
        )
        tx.execute("UPDATE CX_COMPLIANCE_FINDINGS SET STATUS='ACKNOWLEDGED',UPDATED_AT=CURRENT_TIMESTAMP WHERE FINDING_ID=:finding_id AND STATUS='REMEDIATING'", {"finding_id": row["finding_id"]})
        return {"case_id": case_id, "finding_id": row["finding_id"], "status": "ACKNOWLEDGED",
                "evidence": {"evidence_id": evidence_id, "payload_digest": evidence_digest}}
    return connection.execute_transaction_callback(work)


def list_remediation_cases(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    enterprise_required()
    _require(actor, "agents.read")
    suffix, params = _limit(limit)
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT CASE_ID,FINDING_ID,AGENT_ID,REQUIRED_ACTION,STATUS,DEADLINE_AT,CREATED_AT,UPDATED_AT FROM CX_COMPLIANCE_REMEDIATION_CASES ORDER BY UPDATED_AT DESC" + suffix
    else:
        params["actor"] = actor
        query = "SELECT DISTINCT c.CASE_ID,c.FINDING_ID,c.AGENT_ID,c.REQUIRED_ACTION,c.STATUS,c.DEADLINE_AT,c.CREATED_AT,c.UPDATED_AT FROM CX_COMPLIANCE_REMEDIATION_CASES c JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=c.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE' ORDER BY c.UPDATED_AT DESC" + suffix
    return _rows(connection.execute_query(query, params))


def list_remediation_cases_cursor(actor: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.read")
    context = cursor_pagination.resolve(actor, "compliance_remediations", {}, "case_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "compliance_remediations", "sort_key": "case_id:asc"})
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after = str(context["position"].get("case_id") or "")
    after_clause = " AND c.CASE_ID>:after" if after else ""
    if after:
        params["after"] = after
    columns = "c.CASE_ID,c.FINDING_ID,c.AGENT_ID,c.REQUIRED_ACTION,c.STATUS,c.DEADLINE_AT,c.CREATED_AT,c.UPDATED_AT"
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT " + columns + " FROM CX_COMPLIANCE_REMEDIATION_CASES c WHERE 1=1" + after_clause + " ORDER BY c.CASE_ID" + _limit(int(context["page_size"]) + 1)[0]
    else:
        params["actor"] = actor
        query = ("SELECT DISTINCT " + columns + " FROM CX_COMPLIANCE_REMEDIATION_CASES c JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=c.AGENT_ID "
                 "WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'" + after_clause + " ORDER BY c.CASE_ID" + _limit(int(context["page_size"]) + 1)[0])
    result = cursor_pagination.page(_rows(connection.execute_query(query, params)), context,
                                    lambda item: {"case_id": str(item["case_id"])})
    count_params = {key: value for key, value in params.items() if key not in {"limit", "after"}}
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_COMPLIANCE_REMEDIATION_CASES c"
    else:
        count_sql = ("SELECT COUNT(DISTINCT c.CASE_ID) AS CNT FROM CX_COMPLIANCE_REMEDIATION_CASES c JOIN CX_AGENT_RELATIONSHIPS r "
                     "ON r.AGENT_ID=c.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'")
    try:
        total = _row(connection.execute_query_one(count_sql, count_params))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def create_exception(actor: str, policy_key: str, reason: str, *, agent_id: str = "", profile_version_id: str = "",
                     environment: str = "", expires_at: str = "", compensating_controls: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.manage")
    if not policy_key.strip() or not reason.strip() or not expires_at:
        raise ComplianceError("Policy, reason, and expiry are required for an exception")
    if agent_id:
        _visible(actor, agent_id)
    exception_id = _id("EXC")
    if not isinstance(compensating_controls, dict) or not compensating_controls:
        raise ComplianceError("Compensating controls are required for an exception")
    payload = _json(compensating_controls)
    connection.execute(
        "INSERT INTO CX_COMPLIANCE_EXCEPTIONS(EXCEPTION_ID,AGENT_ID,PROFILE_VERSION_ID,POLICY_KEY,ENVIRONMENT,REASON,COMPENSATING_CONTROLS_JSON,REQUESTED_BY,STATUS,EXPIRES_AT) "
        "VALUES (:exception_id,:agent_id,:profile_version_id,:policy_key,:environment,:reason,:controls,:actor,'PENDING',:expires_at)",
        {"exception_id": exception_id, "agent_id": agent_id or None, "profile_version_id": profile_version_id or None,
         "policy_key": policy_key[:128], "environment": environment[:64] or None, "reason": reason[:2000],
         "controls": payload, "actor": actor, "expires_at": expires_at},
    )
    identity_api._audit(actor, "COMPLIANCE_EXCEPTION_REQUEST", "COMPLIANCE_EXCEPTION", exception_id, "ALLOW", reason)
    return {"exception_id": exception_id, "status": "PENDING", "expires_at": expires_at}


def list_exceptions(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    enterprise_required()
    _require(actor, "agents.read")
    suffix, params = _limit(limit)
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT EXCEPTION_ID,AGENT_ID,PROFILE_VERSION_ID,POLICY_KEY,ENVIRONMENT,REASON,REQUESTED_BY,APPROVED_BY,DECISION_REASON,DECIDED_AT,APPROVAL_COUNT,STATUS,EFFECTIVE_AT,EXPIRES_AT,REVOKED_AT,CREATED_AT FROM CX_COMPLIANCE_EXCEPTIONS ORDER BY CREATED_AT DESC" + suffix
    else:
        params["actor"] = actor
        query = "SELECT DISTINCT e.EXCEPTION_ID,e.AGENT_ID,e.PROFILE_VERSION_ID,e.POLICY_KEY,e.ENVIRONMENT,e.REASON,e.REQUESTED_BY,e.APPROVED_BY,e.DECISION_REASON,e.DECIDED_AT,e.APPROVAL_COUNT,e.STATUS,e.EFFECTIVE_AT,e.EXPIRES_AT,e.REVOKED_AT,e.CREATED_AT FROM CX_COMPLIANCE_EXCEPTIONS e JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=e.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE' ORDER BY e.CREATED_AT DESC" + suffix
    return _rows(connection.execute_query(query, params))


def list_exceptions_cursor(actor: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.read")
    context = cursor_pagination.resolve(actor, "compliance_exceptions", {}, "exception_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "compliance_exceptions", "sort_key": "exception_id:asc"})
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    after = str(context["position"].get("exception_id") or "")
    after_clause = " AND e.EXCEPTION_ID>:after" if after else ""
    if after:
        params["after"] = after
    columns = ("e.EXCEPTION_ID,e.AGENT_ID,e.PROFILE_VERSION_ID,e.POLICY_KEY,e.ENVIRONMENT,e.REASON,e.REQUESTED_BY,"
               "e.APPROVED_BY,e.DECISION_REASON,e.DECIDED_AT,e.APPROVAL_COUNT,e.STATUS,e.EFFECTIVE_AT,e.EXPIRES_AT,e.REVOKED_AT,e.CREATED_AT")
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        query = "SELECT " + columns + " FROM CX_COMPLIANCE_EXCEPTIONS e WHERE 1=1" + after_clause + " ORDER BY e.EXCEPTION_ID" + _limit(int(context["page_size"]) + 1)[0]
    else:
        params["actor"] = actor
        query = ("SELECT DISTINCT " + columns + " FROM CX_COMPLIANCE_EXCEPTIONS e JOIN CX_AGENT_RELATIONSHIPS r ON r.AGENT_ID=e.AGENT_ID "
                 "WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'" + after_clause + " ORDER BY e.EXCEPTION_ID" + _limit(int(context["page_size"]) + 1)[0])
    result = cursor_pagination.page(_rows(connection.execute_query(query, params)), context,
                                    lambda item: {"exception_id": str(item["exception_id"])})
    count_params = {key: value for key, value in params.items() if key not in {"limit", "after"}}
    if identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW":
        count_sql = "SELECT COUNT(*) AS CNT FROM CX_COMPLIANCE_EXCEPTIONS e"
    else:
        count_sql = ("SELECT COUNT(DISTINCT e.EXCEPTION_ID) AS CNT FROM CX_COMPLIANCE_EXCEPTIONS e JOIN CX_AGENT_RELATIONSHIPS r "
                     "ON r.AGENT_ID=e.AGENT_ID WHERE r.PRINCIPAL_ID=:actor AND r.STATUS='ACTIVE'")
    try:
        total = _row(connection.execute_query_one(count_sql, count_params))
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def decide_exception(actor: str, exception_id: str, decision: str, reason: str) -> Dict[str, Any]:
    """Apply a distinct-human approval or revoke decision and retain its audit evidence."""
    enterprise_required()
    _require(actor, "agents.manage")
    target = str(decision or "").upper()
    if target not in {"APPROVE", "REJECT", "REVOKE"} or not reason.strip():
        raise ComplianceError("Exception decision and reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        _active_human_tx(tx, actor)
        row = _row(tx.query_one(
            "SELECT EXCEPTION_ID,AGENT_ID,REQUESTED_BY,STATUS,EXPIRES_AT FROM CX_COMPLIANCE_EXCEPTIONS "
            "WHERE EXCEPTION_ID=:id FOR UPDATE", {"id": exception_id}))
        if not row:
            raise ComplianceError("Exception is unavailable")
        if row.get("agent_id"):
            _visible(actor, str(row["agent_id"]))
        if target == "APPROVE":
            if str(row.get("requested_by") or "") == actor:
                raise PermissionError("Exception requester cannot approve the request")
            changed = tx.execute(
                "UPDATE CX_COMPLIANCE_EXCEPTIONS SET STATUS='APPROVED',EFFECTIVE_AT=CURRENT_TIMESTAMP,"
                "APPROVED_BY=:actor,DECISION_REASON=:reason,DECIDED_AT=CURRENT_TIMESTAMP,APPROVAL_COUNT=APPROVAL_COUNT+1 "
                "WHERE EXCEPTION_ID=:id AND STATUS='PENDING' AND EXPIRES_AT>CURRENT_TIMESTAMP",
                {"id": exception_id, "actor": actor, "reason": reason[:2000]},
            )
            result = "APPROVED"
        elif target == "REJECT":
            changed = tx.execute(
                "UPDATE CX_COMPLIANCE_EXCEPTIONS SET STATUS='REJECTED',DECISION_REASON=:reason,DECIDED_AT=CURRENT_TIMESTAMP "
                "WHERE EXCEPTION_ID=:id AND STATUS='PENDING'", {"id": exception_id, "reason": reason[:2000]},
            )
            result = "REJECTED"
        else:
            changed = tx.execute(
                "UPDATE CX_COMPLIANCE_EXCEPTIONS SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,"
                "DECISION_REASON=:reason,DECIDED_AT=CURRENT_TIMESTAMP WHERE EXCEPTION_ID=:id AND STATUS IN ('PENDING','APPROVED')",
                {"id": exception_id, "reason": reason[:2000]},
            )
            result = "REVOKED"
        if changed != 1:
            raise ComplianceError("Exception state changed concurrently or expired")
        _audit_tx(tx, actor, "COMPLIANCE_EXCEPTION_" + result, "COMPLIANCE_EXCEPTION", exception_id, "ALLOW", reason)
        return {"exception_id": exception_id, "status": result}
    return connection.execute_transaction_callback(work)


def set_control(actor: str, agent_id: str, control_state: str, reason: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
    _require(actor, "agents.operate")
    _visible(actor, agent_id)
    state = str(control_state or "").upper()
    if state not in CONTROL_STATES or not reason.strip():
        raise ComplianceError("Control state or reason is invalid")
    if state == "NORMAL":
        _require(actor, "agents.manage")
    def work(tx: Any) -> Dict[str, Any]:
        posture = _ensure_posture_tx(tx, agent_id)
        if expected_version is not None and int(posture.get("version") or 0) != int(expected_version):
            raise ComplianceError("Posture changed concurrently")
        if state == "NORMAL" and str(posture.get("control_state") or "").upper() in {"QUARANTINED", "DISABLED"}:
            open_case = _row(tx.query_one(
                "SELECT CASE_ID FROM CX_COMPLIANCE_REMEDIATION_CASES WHERE AGENT_ID=:agent_id "
                "AND STATUS IN ('OPEN','ACKNOWLEDGED','REMEDIATING') FOR UPDATE", {"agent_id": agent_id}))
            if open_case:
                raise ComplianceError("Open remediation must be reviewed before restoration")
        tx.execute("UPDATE CX_AGENT_POSTURES SET CONTROL_STATE=:state,UPDATED_AT=CURRENT_TIMESTAMP,VERSION=VERSION+1 WHERE POSTURE_ID=:posture_id AND VERSION=:version", {"state": state, "posture_id": posture["posture_id"], "version": posture["version"]})
        if state in {"QUARANTINED", "DISABLED"}:
            tx.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent_id AND REVOKED_AT IS NULL", {"agent_id": agent_id})
            tx.execute("UPDATE CX_AGENT_INSTANCES SET STATUS='QUARANTINED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKE_REASON=:reason,FENCING_TOKEN=FENCING_TOKEN+1 WHERE AGENT_ID=:agent_id AND STATUS='ACTIVE'", {"agent_id": agent_id, "reason": reason[:1000]})
        if state == "DISABLED":
            tx.execute("UPDATE CX_PRINCIPALS SET STATUS='DISABLED',UPDATED_AT=CURRENT_TIMESTAMP WHERE PRINCIPAL_ID=:agent_id AND PRINCIPAL_TYPE='AGENT'", {"agent_id": agent_id})
        elif state == "NORMAL":
            tx.execute("UPDATE CX_PRINCIPALS SET STATUS='ACTIVE',UPDATED_AT=CURRENT_TIMESTAMP WHERE PRINCIPAL_ID=:agent_id AND PRINCIPAL_TYPE='AGENT' AND STATUS='DISABLED'", {"agent_id": agent_id})
        _audit_tx(tx, actor, "COMPLIANCE_CONTROL_" + state, "AGENT", agent_id, "ALLOW", reason)
        return {"agent_id": agent_id, "control_state": state, "version": int(posture.get("version") or 0) + 1}
    return connection.execute_transaction_callback(work)


def control_allows(agent_id: str, operation: str) -> bool:
    """Fail closed for formal work; keep only heartbeat/evidence/recovery while restricted."""
    posture = _posture_row(agent_id)
    if not posture:
        return False
    state = str(posture.get("control_state") or "NORMAL").upper()
    if state == "NORMAL":
        return True
    if state == "RESTRICTED":
        return operation in {"heartbeat", "evidence", "remediation", "recovery"}
    return operation == "recovery"


def controller_summary(actor: str) -> Dict[str, Any]:
    enterprise_required()
    _require(actor, "agents.read")
    postures = list_postures(actor, 500)
    posture_counts: Dict[tuple[str, str], int] = {}
    for posture in postures:
        key = (str(posture.get("posture_state") or "UNKNOWN"), str(posture.get("control_state") or "NORMAL"))
        posture_counts[key] = posture_counts.get(key, 0) + 1
    rows = [{"posture_state": state, "control_state": control, "count": count}
            for (state, control), count in sorted(posture_counts.items())]
    severity_counts: Dict[str, int] = {}
    for finding in list_findings(actor, limit=500):
        if str(finding.get("status") or "").upper() in {"OPEN", "ACKNOWLEDGED", "REMEDIATING"}:
            severity = str(finding.get("severity") or "UNKNOWN")
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
    findings = [{"severity": severity, "count": count} for severity, count in sorted(severity_counts.items())]
    is_global = identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW"
    jobs = _rows(connection.execute_query("SELECT STATUS,COUNT(*) AS COUNT FROM CX_COMPLIANCE_CONTROLLER_JOBS GROUP BY STATUS")) if is_global else []
    latest = _row(connection.execute_query_one(
        "SELECT LEASE_OWNER,UPDATED_AT,LAST_ERROR FROM CX_COMPLIANCE_CONTROLLER_JOBS ORDER BY UPDATED_AT DESC FETCH FIRST 1 ROWS ONLY")) if is_global else None
    return {"postures": rows, "open_findings": findings, "jobs": jobs,
            "controller": "DEGRADED" if (latest or {}).get("last_error") else ("READY" if is_global else "SCOPE_LIMITED"),
            "lease_owner": (latest or {}).get("lease_owner") or "", "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "scope_limited": not is_global}
