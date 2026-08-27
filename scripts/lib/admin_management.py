"""v4.4.1 database-backed Platform Administration control plane.

This service intentionally does not execute uploaded packages or remote kill
commands.  It persists verified intent and database-side isolation first;
authenticated Admin Agent and infrastructure adapters consume those facts.
"""

from __future__ import annotations

import hashlib
import json
import base64
import hmac
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import admin_ha, compliance_api, containment, connection, identity_api, native_agent_api, platform_agent_pool

ADMIN_CHANNEL_NAME = "PLATFORM_ADMINISTRATION"
ADMIN_CHANNEL_ID = "CH_PLATFORM_ADMINISTRATION"
ADMIN_GROUP_ID = "AG_PLATFORM_ADMINISTRATION"
ADMIN_GROUP_KEY = "PLATFORM_ADMINISTRATION"


class ManagementError(ValueError):
    """Safe management-plane error."""


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(20)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _compare_versions(left: str, right: str) -> int:
    """Compare dotted release versions without accepting a downgrade."""
    def parts(value: str) -> tuple[int, ...]:
        try:
            return tuple(int(item) for item in str(value).strip().split("."))
        except ValueError as exc:
            raise ManagementError("upgrade package version is invalid") from exc
    left_parts, right_parts = parts(left), parts(right)
    length = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (length - len(left_parts))
    padded_right = right_parts + (0,) * (length - len(right_parts))
    return (padded_left > padded_right) - (padded_left < padded_right)


def _flag(value: bool) -> Any:
    return bool(value) if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else ("Y" if value else "N")


def _update_or_insert(tx: Any, update_sql: str, insert_sql: str, params: Dict[str, Any]) -> None:
    """Perform a portable upsert while the caller holds its governing row lock.

    The three supported databases do not share one UPSERT syntax.  Callers
    lock the upgrade plan or artifact scope before reaching here, so an update
    followed by an insert preserves the same uniqueness contract without
    embedding a vendor SQL branch in the shared service layer.
    """
    if tx.execute(update_sql, params) != 1:
        tx.execute(insert_sql, params)


def _admin_principals(tx: Any) -> List[str]:
    """Resolve the protected local administrator by identity, not a guessed ID.

    Pre-v4.3 installations use ``admin`` as a username while the unified
    identity migration creates an opaque human principal ID.  The protected
    Platform Administration Channel must use that actual principal ID.
    """
    rows = _rows(tx.query(
        "SELECT i.PRINCIPAL_ID FROM CX_HUMAN_IDENTITIES i JOIN CX_USER_ROLES r "
        "ON r.PRINCIPAL_ID=i.PRINCIPAL_ID WHERE i.IDENTITY_TYPE='LOCAL' "
        "AND i.SUBJECT_KEY='admin' AND i.STATUS='ACTIVE' AND r.ROLE_CODE='SYSTEM_ADMIN' "
        "AND r.STATUS='ACTIVE' AND r.SOURCE='BOOTSTRAP_ADMIN' FOR UPDATE",
        {},
    ))
    return [str(row["principal_id"]) for row in rows if row.get("principal_id")]


def initialize() -> Dict[str, Any]:
    """Idempotently establish the protected human/management-Agent Channel."""
    # Older deployments keep the built-in administrator in SYSTEM_USERS until
    # the first identity-aware service starts.  Adopt that pre-existing local
    # account before checking protected Channel membership; never manufacture
    # a password or a new privileged human identity here.
    identity_api.bootstrap_existing_admins()
    def work(tx: Any) -> Dict[str, Any]:
        channel = _row(tx.query_one("SELECT CHANNEL_ID FROM CX_CHANNELS WHERE CHANNEL_ID=:id FOR UPDATE", {"id": ADMIN_CHANNEL_ID}))
        if not channel:
            domain = _row(tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID='DEFAULT' AND STATUS='ACTIVE'", {}))
            if not domain:
                raise ManagementError("default security domain is unavailable")
            tx.execute(
                "INSERT INTO CX_CHANNELS(CHANNEL_ID,CHANNEL_NAME,SECURITY_DOMAIN_ID,CLASSIFICATION,CHANNEL_TYPE,STATUS,CREATED_BY) "
                "VALUES (:id,:name,'DEFAULT','RESTRICTED','SYSTEM_PROTECTED','ACTIVE','SYSTEM_BOOTSTRAP')",
                {"id": ADMIN_CHANNEL_ID, "name": ADMIN_CHANNEL_NAME},
            )
        group = _row(tx.query_one("SELECT GROUP_ID FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id FOR UPDATE", {"id": ADMIN_GROUP_ID}))
        if not group:
            tx.execute(
                "INSERT INTO CX_ADMIN_AGENT_GROUPS(GROUP_ID,GROUP_KEY,STATUS,PRODUCTION_POLICY,CONFIGURATION_STATE) "
                "VALUES (:id,:key,'ACTIVE','Y','VALID')", {"id": ADMIN_GROUP_ID, "key": ADMIN_GROUP_KEY},
            )
        management_agents = [native_agent_api.PLATFORM_ADMIN_AGENT_ID]
        if native_agent_api._enterprise():
            management_agents.append(native_agent_api.COMPLIANCE_ADMIN_AGENT_ID)
        principals = _admin_principals(tx) + management_agents + [compliance_api.COMPLIANCE_SERVICE_ID]
        created = []
        for principal_id in principals:
            principal = _row(tx.query_one("SELECT PRINCIPAL_ID,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id FOR UPDATE", {"id": principal_id}))
            if not principal or str(principal.get("status") or "").upper() != "ACTIVE":
                continue
            existing = _row(tx.query_one("SELECT MEMBER_ID FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID=:channel AND PRINCIPAL_ID=:principal FOR UPDATE", {"channel": ADMIN_CHANNEL_ID, "principal": principal_id}))
            if not existing:
                tx.execute("INSERT INTO CX_CHANNEL_MEMBERS(MEMBER_ID,CHANNEL_ID,PRINCIPAL_ID,MEMBER_ROLE,STATUS) VALUES (:id,:channel,:principal,:role,'ACTIVE')",
                           {"id": _id("CM"), "channel": ADMIN_CHANNEL_ID, "principal": principal_id, "role": "OWNER" if principal_id in _admin_principals(tx) else "OPERATOR"})
                created.append(principal_id)
        # Channel membership is deliberately not sufficient for a protected
        # Channel.  Native management Agents must also be admitted to its
        # DEFAULT Security Domain, otherwise their audited reply is rejected
        # by the same zero-trust check applied to every other participant.
        for agent_id in management_agents:
            member = _row(tx.query_one(
                "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID='DEFAULT' "
                "AND PRINCIPAL_ID=:principal AND STATUS='ACTIVE' FOR UPDATE",
                {"principal": agent_id},
            ))
            if not member:
                historical = _row(tx.query_one(
                    "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID='DEFAULT' "
                    "AND PRINCIPAL_ID=:principal FOR UPDATE",
                    {"principal": agent_id},
                ))
                if not historical:
                    tx.execute(
                        "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID,SECURITY_DOMAIN_ID,PRINCIPAL_ID,MEMBERSHIP_TIER,STATUS) "
                        "VALUES (:id,'DEFAULT',:principal,'OPERATOR','ACTIVE')",
                        {"id": _id("DM"), "principal": agent_id},
                    )
                else:
                    tx.execute(
                        "UPDATE CX_DOMAIN_MEMBERS SET MEMBERSHIP_TIER='OPERATOR',STATUS='ACTIVE',VALID_UNTIL=NULL "
                        "WHERE MEMBERSHIP_ID=:id",
                        {"id": historical["membership_id"]},
                    )
        native = _row(tx.query_one("SELECT AGENT_ID FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:id FOR UPDATE", {"id": native_agent_api.PLATFORM_ADMIN_AGENT_ID}))
        if native:
            member = _row(tx.query_one("SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent FOR UPDATE", {"group_id": ADMIN_GROUP_ID, "agent": native_agent_api.PLATFORM_ADMIN_AGENT_ID}))
            if not member:
                tx.execute(
                    "INSERT INTO CX_ADMIN_AGENT_MEMBERS(MEMBER_ID,GROUP_ID,AGENT_ID,ADMISSION_PATH,STATUS,VOTING_ENABLED,WEIGHT,NODE_ID,PUBLIC_KEY_DIGEST,APPROVED_AT) "
                    "VALUES (:id,:group_id,:agent,'PLATFORM_DEPLOYED','ACTIVE','Y',5,'LOCAL_BOOTSTRAP','BUILTIN',CURRENT_TIMESTAMP)",
                    {"id": _id("AAM"), "group_id": ADMIN_GROUP_ID, "agent": native_agent_api.PLATFORM_ADMIN_AGENT_ID},
                )
        for policy_key in ("DASHBOARD", "PORTAL"):
            policy = _row(tx.query_one("SELECT POLICY_KEY FROM CX_WEB_SESSION_POLICIES WHERE POLICY_KEY=:key FOR UPDATE", {"key": policy_key}))
            if not policy:
                tx.execute(
                    "INSERT INTO CX_WEB_SESSION_POLICIES(POLICY_KEY,IDLE_TIMEOUT_SECONDS,ABSOLUTE_TIMEOUT_SECONDS,UPDATED_BY,REASON) "
                    "VALUES (:key,300,28800,'SYSTEM_BOOTSTRAP','v4.4.1 default session policy')", {"key": policy_key},
                )
        identity_api._audit_tx(tx, "SYSTEM_BOOTSTRAP", "PLATFORM_ADMIN_CHANNEL_INITIALIZE", "CHANNEL", ADMIN_CHANNEL_ID, "ALLOW", "protected Platform Administration Channel initialized")
        return {"channel_id": ADMIN_CHANNEL_ID, "group_id": ADMIN_GROUP_ID, "created_members": created}
    return connection.execute_transaction_callback(work)


def session_policy(kind: str) -> Dict[str, Any]:
    key = "PORTAL" if str(kind).upper() == "PORTAL" else "DASHBOARD"
    row = _row(connection.execute_query_one(
        "SELECT POLICY_KEY,IDLE_TIMEOUT_SECONDS,ABSOLUTE_TIMEOUT_SECONDS,VERSION,UPDATED_AT "
        "FROM CX_WEB_SESSION_POLICIES WHERE POLICY_KEY=:key", {"key": key},
    ))
    if not row:
        raise ManagementError("session policy is unavailable")
    return {"policy_key": key, "idle_timeout_seconds": max(60, min(int(row.get("idle_timeout_seconds") or 300), 86400)),
            "absolute_timeout_seconds": max(60, min(int(row.get("absolute_timeout_seconds") or 28800), 86400)),
            "version": int(row.get("version") or 1), "updated_at": row.get("updated_at")}


def update_session_policy(actor: str, kind: str, idle_timeout_seconds: int, absolute_timeout_seconds: int,
                          expected_version: int, reason: str) -> Dict[str, Any]:
    _require_manage(actor)
    key = "PORTAL" if str(kind).upper() == "PORTAL" else "DASHBOARD"
    idle, absolute = int(idle_timeout_seconds), int(absolute_timeout_seconds)
    if not 60 <= idle <= 86400 or not idle <= absolute <= 86400 or len(str(reason or "").strip()) < 3:
        raise ManagementError("session policy values are invalid")
    def work(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one("SELECT VERSION FROM CX_WEB_SESSION_POLICIES WHERE POLICY_KEY=:key FOR UPDATE", {"key": key}))
        if not row or int(row.get("version") or 0) != int(expected_version):
            raise ManagementError("session policy changed concurrently")
        next_version = int(row["version"]) + 1
        tx.execute("UPDATE CX_WEB_SESSION_POLICIES SET IDLE_TIMEOUT_SECONDS=:idle,ABSOLUTE_TIMEOUT_SECONDS=:absolute,VERSION=:version,UPDATED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE POLICY_KEY=:key", {"idle": idle, "absolute": absolute, "version": next_version, "actor": actor, "reason": reason[:2000], "key": key})
        tx.execute("INSERT INTO CX_WEB_SESSION_POLICY_HISTORY(HISTORY_ID,POLICY_KEY,VERSION,IDLE_TIMEOUT_SECONDS,ABSOLUTE_TIMEOUT_SECONDS,CHANGED_BY,REASON) VALUES (:id,:key,:version,:idle,:absolute,:actor,:reason)", {"id": _id("SPH"), "key": key, "version": next_version, "idle": idle, "absolute": absolute, "actor": actor, "reason": reason[:2000]})
        identity_api._audit_tx(tx, actor, "WEB_SESSION_POLICY_UPDATE", "SESSION_POLICY", key, "ALLOW", reason)
        return {"policy_key": key, "idle_timeout_seconds": idle, "absolute_timeout_seconds": absolute, "version": next_version}
    return connection.execute_transaction_callback(work)


def _require_manage(actor: str) -> None:
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")


def _protected_channel(channel_id: str) -> bool:
    return str(channel_id) == ADMIN_CHANNEL_ID


def can_add_protected_member(actor: str, principal_id: str, reason: str) -> None:
    _require_manage(actor)
    if not str(reason or "").strip():
        raise ManagementError("an invitation reason is required")
    if principal_id == actor:
        raise ManagementError("self-invitation is not allowed")
    principal = _row(connection.execute_query_one("SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id", {"id": principal_id}))
    if not principal or str(principal.get("status") or "").upper() != "ACTIVE":
        raise ManagementError("invited principal is unavailable")
    if str(principal.get("principal_type") or "").upper() == "HUMAN":
        return
    member = _row(connection.execute_query_one(
        "SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent "
        "AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'",
        {"group_id": ADMIN_GROUP_ID, "agent": principal_id},
    ))
    if not member:
        raise ManagementError("only approved management Admin Agents may join the protected Channel")


def invite_protected_human(actor: str, principal_id: str, reason: str, valid_until: str = "") -> Dict[str, Any]:
    can_add_protected_member(actor, principal_id, reason)
    principal = _row(connection.execute_query_one("SELECT PRINCIPAL_TYPE FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id", {"id": principal_id}))
    if not principal or str(principal.get("principal_type") or "").upper() != "HUMAN":
        raise ManagementError("protected human invitations are only for human principals")
    changed = connection.execute(
        "UPDATE CX_CHANNEL_MEMBERS SET STATUS='ACTIVE',MEMBER_ROLE='REVIEWER',VALID_UNTIL=:until WHERE CHANNEL_ID=:channel AND PRINCIPAL_ID=:principal",
        {"until": valid_until or None, "channel": ADMIN_CHANNEL_ID, "principal": principal_id},
    )
    if not changed:
        connection.execute("INSERT INTO CX_CHANNEL_MEMBERS(MEMBER_ID,CHANNEL_ID,PRINCIPAL_ID,MEMBER_ROLE,VALID_UNTIL,STATUS) VALUES (:id,:channel,:principal,'REVIEWER',:until,'ACTIVE')",
                           {"id": _id("CM"), "channel": ADMIN_CHANNEL_ID, "principal": principal_id, "until": valid_until or None})
    identity_api._audit(actor, "PLATFORM_ADMIN_CHANNEL_INVITE", "CHANNEL", ADMIN_CHANNEL_ID, "ALLOW", reason)
    return {"channel_id": ADMIN_CHANNEL_ID, "principal_id": principal_id, "status": "ACTIVE"}


def list_group(actor: str) -> Dict[str, Any]:
    _require_manage(actor)
    group = _row(connection.execute_query_one("SELECT GROUP_ID,GROUP_KEY,STATUS,PRODUCTION_POLICY,CURRENT_TERM,LEADER_MEMBER_ID,LEADER_LEASE_EXPIRES_AT,FENCING_TOKEN,CONFIGURATION_STATE FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id", {"id": ADMIN_GROUP_ID})) or {}
    members = _rows(connection.execute_query("SELECT MEMBER_ID,GROUP_ID,AGENT_ID,ADMISSION_PATH,STATUS,VOTING_ENABLED,WEIGHT,NODE_ID,CANDIDATE_SINCE,APPROVED_AT,UPDATED_AT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:id ORDER BY WEIGHT DESC,MEMBER_ID", {"id": ADMIN_GROUP_ID}))
    valid = admin_ha.validate_weights([item for item in members if str(item.get("voting_enabled") or "N").upper() == "Y"])
    healthy = sum(1 for item in members if str(item.get("status") or "").upper() == "ACTIVE")
    return {"group": group, "members": members, "weight_validation": valid.__dict__, "healthy_members": healthy,
            "readiness": "READY" if valid.valid and healthy >= 3 else "HIGH_AVAILABILITY_NOT_READY"}


def list_admin_enrollments(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Return pending Admin admissions without exposing public-key material.

    The enrollment record deliberately stores only a public-key digest.  The
    candidate has to prove possession through its independently authenticated
    gateway identity before a human can put it into observation.
    """
    _require_manage(actor)
    amount = max(1, min(int(limit), 100))
    suffix = "LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST :limit ROWS ONLY"
    return _rows(connection.execute_query(
        "SELECT ENROLLMENT_ID,ADMISSION_PATH,AGENT_ID,NODE_ID,PUBLIC_KEY_DIGEST,PACKAGE_DIGEST,STATUS,"
        "REASON,EXPIRES_AT,APPROVED_BY,CREATED_AT,UPDATED_AT FROM CX_ADMIN_ENROLLMENTS "
        "WHERE GROUP_ID=:group_id ORDER BY CREATED_AT DESC " + suffix,
        {"group_id": ADMIN_GROUP_ID, "limit": amount},
    ))


def create_admin_enrollment(
    actor: str, admission_path: str, public_key: str, node_id: str, reason: str,
    package_digest: str = "", *, host_reference: str = "", ssh_port: int = 22,
    os_user: str = "", deployment_target: str = "", ssh_trust_mode: str = "MUTUAL_TRUST",
    ssh_password: str = "", failure_domain: str = "", agent_info_path: str = "",
) -> Dict[str, Any]:
    _require_manage(actor)
    path = str(admission_path or "").upper()
    if path not in {"PLATFORM_DEPLOYED", "EXTERNAL_ADMIN"}:
        raise ManagementError("Admin admission path is invalid")
    if not node_id or len(str(reason or "").strip()) < 3:
        raise ManagementError("node ID and reason are required")
    if path == "EXTERNAL_ADMIN" and len(str(public_key or "").strip()) < 16:
        raise ManagementError("external Admin identity public key is required")
    trust_mode = str(ssh_trust_mode or "").upper()
    if trust_mode not in {"MUTUAL_TRUST", "ONE_USE_PASSWORD"}:
        raise ManagementError("SSH trust mode is invalid")
    if path == "PLATFORM_DEPLOYED":
        if not host_reference or not os_user or not deployment_target or not failure_domain:
            raise ManagementError("platform deployment requires host, operating-system user, deployment target, and failure domain")
        if trust_mode == "ONE_USE_PASSWORD" and not ssh_password:
            raise ManagementError("one-use SSH password is required when mutual trust is unavailable")
    elif any((host_reference, os_user, deployment_target, ssh_password, failure_domain)):
        raise ManagementError("external Admin admission uses its key package and must not include infrastructure credentials")
    enrollment_id = _id("AAE")
    # Platform-deployed candidates receive their identity key from the existing
    # Admin Agent during deployment. Keep only a transient marker until the
    # authenticated Agent credential is observed; external candidates must
    # provide their public key before enrollment.
    digest = _digest(public_key) if public_key else _digest(_json({"path": path, "node": node_id, "enrollment": enrollment_id}))
    package = package_digest or _digest(_json({"path": path, "node": node_id, "key": digest, "reason": reason}))
    target_id = _id("ANT") if path == "PLATFORM_DEPLOYED" else ""

    def work(tx: Any) -> None:
        if target_id:
            tx.execute(
                "INSERT INTO CX_ADMIN_NODE_TARGETS(TARGET_ID,NODE_ID,HOST_REFERENCE,SSH_PORT,OS_USER,DEPLOYMENT_TARGET,SSH_TRUST_MODE,PUBLIC_KEY_DIGEST,FAILURE_DOMAIN,STATUS,REASON,CREATED_BY) "
                "VALUES (:id,:node,:host,:port,:user,:target,:trust,:key,:domain,'PENDING_ADAPTER_VERIFICATION',:reason,:actor)",
                {"id": target_id, "node": node_id[:256], "host": host_reference[:256], "port": int(ssh_port),
                 "user": os_user[:128], "target": deployment_target[:128], "trust": trust_mode,
                 "key": digest, "domain": failure_domain[:128], "reason": reason[:2000], "actor": actor},
            )
            # Password verification is deliberately one-use: retain a digest of
            # the attempt outcome only, never the password or a reversible form.
            tx.execute(
                "INSERT INTO CX_ADMIN_DEPLOYMENT_ATTEMPTS(ATTEMPT_ID,TARGET_ID,ATTEMPT_DIGEST,VERIFICATION_STATE,RESULT_DIGEST,REASON,CREATED_BY) "
                "VALUES (:id,:target,:attempt,:state,:result,:reason,:actor)",
                {"id": _id("ADA"), "target": target_id,
                 "attempt": _digest(_json({"node": node_id, "host": host_reference, "port": int(ssh_port), "user": os_user, "trust": trust_mode})),
                 "state": "PENDING_ADAPTER_VERIFICATION", "result": _digest("metadata-recorded"),
                 "reason": reason[:2000], "actor": actor},
            )
        tx.execute(
            "INSERT INTO CX_ADMIN_ENROLLMENTS(ENROLLMENT_ID,GROUP_ID,ADMISSION_PATH,NODE_ID,PUBLIC_KEY_DIGEST,PACKAGE_DIGEST,STATUS,REASON,REQUESTED_BY,EXPIRES_AT) "
            "VALUES (:id,:group_id,:path,:node,:key,:package,'CANDIDATE',:reason,:actor," + _expiry_sql() + ")",
            {"id": enrollment_id, "group_id": ADMIN_GROUP_ID, "path": path, "node": node_id[:256], "key": digest,
             "package": package[:128], "reason": reason[:2000], "actor": actor},
        )
        identity_api._audit_tx(tx, actor, "ADMIN_AGENT_ENROLLMENT_CREATE", "ADMIN_ENROLLMENT", enrollment_id, "ALLOW", reason)

    connection.execute_transaction_callback(work)
    discovered_node = None
    if path == "PLATFORM_DEPLOYED":
        discovered_node = platform_agent_pool.ensure_managed_node(
            node_key=node_id, host_reference=host_reference, roles=["ADMIN_AGENT"],
            actor=actor, ssh_port=ssh_port, os_user=os_user,
            failure_domain=failure_domain,
            agent_info_path=platform_agent_pool.resolve_agent_info_path(agent_info_path) if agent_info_path else "",
            reason="Admin Agent deployment metadata was collected automatically",
        )
    return {"enrollment_id": enrollment_id, "target_id": target_id or None, "admission_path": path, "status": "CANDIDATE", "public_key_digest": digest, "password_persisted": False, "managed_node": discovered_node}


def observe_admin_enrollment(actor: str, enrollment_id: str, agent_id: str, reason: str) -> Dict[str, Any]:
    """Bind a candidate to an already verified Admin identity for observation.

    A normal enrollment token cannot reach this path.  Platform-deployed
    candidates must already have a platform-owned identity; external Admin
    candidates must present an independently registered Agent identity.
    """
    _require_manage(actor)
    if len(str(reason or "").strip()) < 3:
        raise ManagementError("an observation reason is required")
    def work(tx: Any) -> Dict[str, Any]:
        enrollment = _row(tx.query_one("SELECT ENROLLMENT_ID,ADMISSION_PATH,PUBLIC_KEY_DIGEST,STATUS,EXPIRES_AT FROM CX_ADMIN_ENROLLMENTS WHERE ENROLLMENT_ID=:id FOR UPDATE", {"id": enrollment_id}))
        if not enrollment or str(enrollment.get("status") or "").upper() != "CANDIDATE":
            raise ManagementError("Admin enrollment is not a candidate")
        still_valid = _row(tx.query_one(
            "SELECT ENROLLMENT_ID FROM CX_ADMIN_ENROLLMENTS WHERE ENROLLMENT_ID=:id AND EXPIRES_AT>CURRENT_TIMESTAMP",
            {"id": enrollment_id},
        ))
        if not still_valid:
            raise ManagementError("Admin enrollment has expired")
        principal = _row(tx.query_one("SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:agent FOR UPDATE", {"agent": agent_id}))
        if not principal or str(principal.get("principal_type") or "").upper() != "AGENT" or str(principal.get("status") or "").upper() != "ACTIVE":
            raise ManagementError("Admin candidate Agent identity is unavailable")
        credential = _row(tx.query_one(
            "SELECT PUBLIC_KEY FROM CX_AGENT_CREDENTIALS WHERE AGENT_ID=:agent AND CREDENTIAL_TYPE='ED25519' "
            "AND STATUS='ACTIVE' AND (EXPIRES_AT IS NULL OR EXPIRES_AT>CURRENT_TIMESTAMP)", {"agent": agent_id},
        ))
        candidate_path = str(enrollment.get("admission_path") or "").upper()
        credential_digest = _digest(str(credential.get("public_key") or "")) if credential else ""
        if not credential:
            raise ManagementError("Admin candidate identity credential is unavailable")
        if candidate_path == "PLATFORM_DEPLOYED":
            native = _row(tx.query_one("SELECT AGENT_ID,AGENT_KIND,SOURCE FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:agent", {"agent": agent_id}))
            if not native or str(native.get("agent_kind") or "").upper() != "PLATFORM_ADMIN":
                raise ManagementError("platform-deployed Admin candidate must use the Platform Admin template")
            # The existing Admin Agent establishes the deployment identity. The
            # credential is authoritative; the enrollment form does not require
            # an operator to copy its public key manually.
            tx.execute("UPDATE CX_ADMIN_ENROLLMENTS SET PUBLIC_KEY_DIGEST=:key,UPDATED_AT=CURRENT_TIMESTAMP WHERE ENROLLMENT_ID=:id", {"key": credential_digest, "id": enrollment_id})
        elif credential_digest != str(enrollment.get("public_key_digest") or ""):
            raise ManagementError("Admin candidate public-key proof does not match the enrollment")
        existing = _row(tx.query_one("SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent FOR UPDATE", {"group_id": ADMIN_GROUP_ID, "agent": agent_id}))
        if existing:
            raise ManagementError("Agent is already an Admin group member")
        member_id = _id("AAM")
        tx.execute("INSERT INTO CX_ADMIN_AGENT_MEMBERS(MEMBER_ID,GROUP_ID,AGENT_ID,ADMISSION_PATH,STATUS,VOTING_ENABLED,WEIGHT,NODE_ID,PUBLIC_KEY_DIGEST) SELECT :member,:group_id,:agent,ADMISSION_PATH,'OBSERVATION','N',1,NODE_ID,PUBLIC_KEY_DIGEST FROM CX_ADMIN_ENROLLMENTS WHERE ENROLLMENT_ID=:enrollment", {"member": member_id, "group_id": ADMIN_GROUP_ID, "agent": agent_id, "enrollment": enrollment_id})
        tx.execute("UPDATE CX_ADMIN_ENROLLMENTS SET AGENT_ID=:agent,STATUS='OBSERVATION',UPDATED_AT=CURRENT_TIMESTAMP WHERE ENROLLMENT_ID=:id", {"agent": agent_id, "id": enrollment_id})
        identity_api._audit_tx(tx, actor, "ADMIN_AGENT_ENROLLMENT_OBSERVE", "ADMIN_ENROLLMENT", enrollment_id, "ALLOW", reason)
        return {"enrollment_id": enrollment_id, "member_id": member_id, "agent_id": agent_id, "status": "OBSERVATION"}
    return connection.execute_transaction_callback(work)


def approve_admin_member(actor: str, member_id: str, weight: int, reason: str) -> Dict[str, Any]:
    """Admit an observed candidate after a human approval record.

    The first member is human-approved bootstrap.  Subsequent approval
    evidence is captured in a quorum snapshot; automation must still verify
    the snapshot before acting on membership changes.
    """
    _require_manage(actor)
    if len(str(reason or "").strip()) < 3:
        raise ManagementError("an approval reason is required")
    def work(tx: Any) -> Dict[str, Any]:
        member = _row(tx.query_one("SELECT MEMBER_ID,GROUP_ID,AGENT_ID,STATUS,VOTING_ENABLED FROM CX_ADMIN_AGENT_MEMBERS WHERE MEMBER_ID=:id FOR UPDATE", {"id": member_id}))
        if not member or str(member.get("status") or "").upper() != "OBSERVATION":
            raise ManagementError("Admin Agent candidate is not in observation")
        enrollment = _row(tx.query_one(
            "SELECT ENROLLMENT_ID,STATUS,REQUESTED_BY FROM CX_ADMIN_ENROLLMENTS WHERE AGENT_ID=:agent AND GROUP_ID=:group_id "
            "AND STATUS='OBSERVATION' FOR UPDATE", {"agent": member["agent_id"], "group_id": ADMIN_GROUP_ID},
        ))
        if not enrollment:
            raise ManagementError("Admin Agent observation evidence is unavailable")
        if str(enrollment.get("requested_by") or "") == actor:
            raise ManagementError("Admin Agent requester cannot approve its own enrollment")
        others = _rows(tx.query("SELECT MEMBER_ID,AGENT_ID,STATUS,VOTING_ENABLED,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id FOR UPDATE", {"group_id": ADMIN_GROUP_ID}))
        prospective = []
        for item in others:
            changed = dict(item)
            if str(changed.get("member_id")) == member_id:
                changed.update({"status": "ACTIVE", "voting_enabled": "Y", "weight": int(weight)})
            if str(changed.get("voting_enabled") or "N").upper() == "Y":
                prospective.append(changed)
        validation = admin_ha.validate_weights(prospective)
        if not validation.valid:
            tx.execute("UPDATE CX_ADMIN_AGENT_GROUPS SET CONFIGURATION_STATE='CONFIGURATION_INVALID',UPDATED_AT=CURRENT_TIMESTAMP WHERE GROUP_ID=:group_id", {"group_id": ADMIN_GROUP_ID})
            raise ManagementError(validation.message)
        tx.execute("UPDATE CX_ADMIN_AGENT_MEMBERS SET STATUS='ACTIVE',VOTING_ENABLED='Y',WEIGHT=:weight,APPROVED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE MEMBER_ID=:id", {"weight": int(weight), "id": member_id})
        tx.execute("UPDATE CX_ADMIN_ENROLLMENTS SET STATUS='APPROVED',APPROVED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE ENROLLMENT_ID=:id", {"actor": actor, "id": enrollment["enrollment_id"]})
        existing_channel_member = _row(tx.query_one(
            "SELECT MEMBER_ID FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID=:channel AND PRINCIPAL_ID=:agent FOR UPDATE",
            {"channel": ADMIN_CHANNEL_ID, "agent": member["agent_id"]},
        ))
        if existing_channel_member:
            tx.execute("UPDATE CX_CHANNEL_MEMBERS SET STATUS='ACTIVE',MEMBER_ROLE='OPERATOR',VALID_UNTIL=NULL WHERE MEMBER_ID=:id", {"id": existing_channel_member["member_id"]})
        else:
            tx.execute(
                "INSERT INTO CX_CHANNEL_MEMBERS(MEMBER_ID,CHANNEL_ID,PRINCIPAL_ID,MEMBER_ROLE,STATUS) VALUES (:id,:channel,:agent,'OPERATOR','ACTIVE')",
                {"id": _id("CM"), "channel": ADMIN_CHANNEL_ID, "agent": member["agent_id"]},
            )
        snapshot_id = _id("AQS")
        tx.execute("INSERT INTO CX_ADMIN_QUORUM_SNAPSHOTS(SNAPSHOT_ID,GROUP_ID,TERM,MEMBERS_JSON,TOTAL_WEIGHT,REQUIRED_COUNT,REQUIRED_WEIGHT,DECISION,DECISION_REASON) VALUES (:id,:group_id,0,:members,:total,:count,:weight,'HUMAN_APPROVED',:reason)", {"id": snapshot_id, "group_id": ADMIN_GROUP_ID, "members": _json(prospective), "total": validation.total_weight, "count": len(prospective) // 2 + 1, "weight": validation.total_weight // 2 + 1, "reason": reason[:2000]})
        tx.execute("UPDATE CX_ADMIN_AGENT_GROUPS SET CONFIGURATION_STATE='VALID',UPDATED_AT=CURRENT_TIMESTAMP WHERE GROUP_ID=:group_id", {"group_id": ADMIN_GROUP_ID})
        identity_api._audit_tx(tx, actor, "ADMIN_AGENT_MEMBER_APPROVE", "ADMIN_AGENT_MEMBER", member_id, "ALLOW", reason)
        return {"member_id": member_id, "agent_id": member["agent_id"], "status": "ACTIVE", "weight": int(weight), "snapshot_id": snapshot_id}
    return connection.execute_transaction_callback(work)


def _expiry_sql() -> str:
    return "CURRENT_TIMESTAMP + INTERVAL '15 minutes'" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "CURRENT_TIMESTAMP + INTERVAL '15' MINUTE"


def set_member_weight(actor: str, member_id: str, weight: int, reason: str) -> Dict[str, Any]:
    _require_manage(actor)
    if len(str(reason or "").strip()) < 3:
        raise ManagementError("a reason is required")
    def work(tx: Any) -> Dict[str, Any]:
        members = _rows(tx.query_one("SELECT MEMBER_ID,AGENT_ID,STATUS,VOTING_ENABLED,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id FOR UPDATE", {"group_id": ADMIN_GROUP_ID}) or [])
        # Some adapters return one mapping for query_one mocks; the runtime uses query below.
        members = _rows(tx.query("SELECT MEMBER_ID,AGENT_ID,STATUS,VOTING_ENABLED,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id FOR UPDATE", {"group_id": ADMIN_GROUP_ID}))
        changed_members = []
        found = False
        for item in members:
            updated = dict(item)
            if str(item.get("member_id")) == member_id:
                updated["weight"] = int(weight)
                found = True
            if str(updated.get("voting_enabled") or "N").upper() == "Y":
                changed_members.append(updated)
        if not found:
            raise ManagementError("Admin Agent member is unavailable")
        validation = admin_ha.validate_weights(changed_members)
        if not validation.valid:
            tx.execute("UPDATE CX_ADMIN_AGENT_GROUPS SET CONFIGURATION_STATE='CONFIGURATION_INVALID',UPDATED_AT=CURRENT_TIMESTAMP WHERE GROUP_ID=:group_id", {"group_id": ADMIN_GROUP_ID})
            raise ManagementError(validation.message)
        updated = tx.execute("UPDATE CX_ADMIN_AGENT_MEMBERS SET WEIGHT=:weight,UPDATED_AT=CURRENT_TIMESTAMP WHERE MEMBER_ID=:member", {"weight": int(weight), "member": member_id})
        if updated != 1:
            raise ManagementError("Admin Agent member changed concurrently")
        tx.execute("UPDATE CX_ADMIN_AGENT_GROUPS SET CONFIGURATION_STATE='VALID',UPDATED_AT=CURRENT_TIMESTAMP WHERE GROUP_ID=:group_id", {"group_id": ADMIN_GROUP_ID})
        identity_api._audit_tx(tx, actor, "ADMIN_AGENT_WEIGHT_CHANGE", "ADMIN_AGENT_MEMBER", member_id, "ALLOW", reason)
        return {"member_id": member_id, "weight": int(weight), "configuration_state": "VALID"}
    return connection.execute_transaction_callback(work)


def acquire_leader(actor: str, member_id: str, lease_seconds: int = 60) -> Dict[str, Any]:
    _require_manage(actor)
    lease_seconds = max(15, min(int(lease_seconds), 300))
    def work(tx: Any) -> Dict[str, Any]:
        group = _row(tx.query_one("SELECT GROUP_ID,CURRENT_TERM,FENCING_TOKEN,CONFIGURATION_STATE FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id FOR UPDATE", {"id": ADMIN_GROUP_ID}))
        if not group or str(group.get("configuration_state") or "").upper() != "VALID":
            raise ManagementError("Admin Agent group configuration is invalid")
        members = _rows(tx.query("SELECT MEMBER_ID,AGENT_ID,STATUS,VOTING_ENABLED,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:id AND VOTING_ENABLED='Y' FOR UPDATE", {"id": ADMIN_GROUP_ID}))
        selected = admin_ha.leader_candidate(members)
        if selected != member_id:
            raise ManagementError("Leader candidate does not match the deterministic succession order")
        next_term, next_fencing = int(group.get("current_term") or 0) + 1, int(group.get("fencing_token") or 0) + 1
        interval = f"CURRENT_TIMESTAMP + INTERVAL '{lease_seconds} seconds'" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else f"CURRENT_TIMESTAMP + INTERVAL '{lease_seconds}' SECOND"
        tx.execute("UPDATE CX_ADMIN_AGENT_GROUPS SET CURRENT_TERM=:term,FENCING_TOKEN=:fencing,LEADER_MEMBER_ID=:member,LEADER_LEASE_EXPIRES_AT=" + interval + ",UPDATED_AT=CURRENT_TIMESTAMP WHERE GROUP_ID=:id", {"term": next_term, "fencing": next_fencing, "member": member_id, "id": ADMIN_GROUP_ID})
        tx.execute("INSERT INTO CX_ADMIN_LEADER_EVIDENCE(EVIDENCE_ID,GROUP_ID,MEMBER_ID,NEW_TERM,NEW_FENCING_TOKEN,EVENT_TYPE,DETAIL_JSON) VALUES (:id,:group_id,:member,:term,:fencing,'LEADER_ELECTED',:detail)", {"id": _id("ALE"), "group_id": ADMIN_GROUP_ID, "member": member_id, "term": next_term, "fencing": next_fencing, "detail": _json({"lease_seconds": lease_seconds})})
        return {"member_id": member_id, "term": next_term, "fencing_token": next_fencing}
    return connection.execute_transaction_callback(work)


def issue_containment(actor: str, agent_id: str, instance_id: str, requested_state: str, reason: str, expires_seconds: int = 300) -> Dict[str, Any]:
    _require_manage(actor)
    state = str(requested_state or "").upper()
    if state not in containment.STATES or len(str(reason or "").strip()) < 3:
        raise ManagementError("containment state and reason are required")
    current = _row(connection.execute_query_one(
        "SELECT CONTROL_GENERATION AS GENERATION,REQUESTED_STATE AS STATE FROM CX_AGENT_CONTAINMENT_COMMANDS "
        "WHERE INSTANCE_ID=:instance ORDER BY CONTROL_GENERATION DESC " +
        ("LIMIT 1" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 1 ROWS ONLY"),
        {"instance": instance_id},
    )) or {}
    previous_state, generation = str(current.get("state") or "OBSERVE"), int(current.get("generation") or 0)
    if not containment.quarantine_precedes_termination(previous_state, state):
        raise ManagementError("quarantine must be confirmed before termination")
    if state in {"QUARANTINE", "TERMINATE", "INFRA_TERMINATE"}:
        connection.execute("UPDATE CX_AGENT_INSTANCES SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKE_REASON=:reason,FENCING_TOKEN=FENCING_TOKEN+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE INSTANCE_ID=:instance AND AGENT_ID=:agent AND STATUS='ACTIVE'", {"reason": reason[:1000], "instance": instance_id, "agent": agent_id})
        connection.execute("UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP WHERE INSTANCE_ID=:instance AND AGENT_ID=:agent AND REVOKED_AT IS NULL", {"instance": instance_id, "agent": agent_id})
    command_id, next_generation = _id("ACC"), generation + 1
    # The command ID is a public, unique nonce. Its digest is persisted to
    # support replay evidence, while an authenticated Agent can reconstruct
    # the signed envelope without a second secret-delivery channel.
    nonce = command_id
    expiry_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, min(int(expires_seconds), 3600)))
    expiry = expiry_at.isoformat()
    payload = containment.command_payload(instance_id, next_generation, nonce, actor, reason, expiry, state)
    from .connection_crypto import get_master_key
    signature = containment.sign_command(payload, get_master_key())
    connection.execute("INSERT INTO CX_AGENT_CONTAINMENT_COMMANDS(COMMAND_ID,AGENT_ID,INSTANCE_ID,REQUESTED_STATE,CONTROL_GENERATION,NONCE_DIGEST,ISSUER_PRINCIPAL_ID,REASON,EXPIRES_AT,SIGNATURE,AUTHORITY_STATE) VALUES (:id,:agent,:instance,:state,:generation,:nonce,:issuer,:reason,:expires,:signature,'ISOLATED')", {"id": command_id, "agent": agent_id, "instance": instance_id, "state": state, "generation": next_generation, "nonce": _digest(nonce), "issuer": actor, "reason": reason[:2000], "expires": expiry_at, "signature": signature})
    identity_api._audit(actor, "AGENT_CONTAINMENT_" + state, "AGENT_INSTANCE", instance_id, "ALLOW", reason)
    return {"command_id": command_id, "state": state, "control_generation": next_generation, "authority_state": "ISOLATED", "infrastructure_termination": "NOT_CONFIGURED" if state == "INFRA_TERMINATE" else "NOT_REQUESTED"}


def pull_containment_command(agent_id: str, instance_id: str) -> Optional[Dict[str, Any]]:
    """Return the newest still-actionable command for its exact Agent instance.

    The raw nonce is intentionally never persisted.  A command is delivered
    through the authenticated Gateway and acknowledged by its command ID;
    replay is rejected by the generation and acknowledgement state.
    """
    row = _row(connection.execute_query_one(
        "SELECT COMMAND_ID,AGENT_ID,INSTANCE_ID,REQUESTED_STATE,CONTROL_GENERATION,ISSUER_PRINCIPAL_ID,"
        "REASON,EXPIRES_AT,SIGNATURE,AUTHORITY_STATE,AGENT_ACK_STATE FROM CX_AGENT_CONTAINMENT_COMMANDS "
        "WHERE AGENT_ID=:agent AND INSTANCE_ID=:instance AND AGENT_ACK_STATE='PENDING' "
        "AND EXPIRES_AT>CURRENT_TIMESTAMP ORDER BY CONTROL_GENERATION DESC " +
        ("LIMIT 1" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 1 ROWS ONLY"),
        {"agent": agent_id, "instance": instance_id},
    ))
    if not row:
        return None
    return {"command_id": row["command_id"], "agent_id": row["agent_id"], "instance_id": row["instance_id"],
            "action": row["requested_state"], "generation": int(row["control_generation"]),
            "issuer": row["issuer_principal_id"], "reason": row["reason"], "expires_at": str(row["expires_at"]),
            "nonce": row["command_id"], "signature": row["signature"], "authority_state": row["authority_state"]}


def acknowledge_containment(agent_id: str, instance_id: str, command_id: str, generation: int,
                            cleanup_evidence: Dict[str, Any], success: bool) -> Dict[str, Any]:
    """Persist a one-way cleanup acknowledgement from the fenced Agent instance."""
    evidence = _json({"memory_cleanup": bool(cleanup_evidence.get("memory_cleanup")),
                      "stopped": bool(cleanup_evidence.get("stopped")),
                      "detail": str(cleanup_evidence.get("detail") or "")[:1000]})
    state = "ACKNOWLEDGED" if success else "FAILED"
    changed = connection.execute(
        "UPDATE CX_AGENT_CONTAINMENT_COMMANDS SET AGENT_ACK_STATE=:state,CLEANUP_EVIDENCE_JSON=:evidence,"
        "UPDATED_AT=CURRENT_TIMESTAMP WHERE COMMAND_ID=:id AND AGENT_ID=:agent AND INSTANCE_ID=:instance "
        "AND CONTROL_GENERATION=:generation AND AGENT_ACK_STATE='PENDING' AND EXPIRES_AT>CURRENT_TIMESTAMP",
        {"state": state, "evidence": evidence, "id": command_id, "agent": agent_id,
         "instance": instance_id, "generation": int(generation)},
    )
    if changed != 1:
        raise ManagementError("containment acknowledgement is stale or unavailable")
    identity_api._audit(agent_id, "AGENT_CONTAINMENT_ACK", "AGENT_INSTANCE", instance_id,
                        "ALLOW" if success else "ERROR", command_id)
    return {"command_id": command_id, "agent_ack_state": state}


def stage_upgrade(actor: str, package_version: str, edition: str, package_digest: str, signature_state: str, reason: str) -> Dict[str, Any]:
    _require_manage(actor)
    if not package_version or len(package_digest) < 32 or str(signature_state).upper() != "VERIFIED":
        raise ManagementError("only a verified package digest may be staged")
    upgrade_id = _id("UPG")
    connection.execute("INSERT INTO CX_UPGRADE_PLANS(UPGRADE_ID,PACKAGE_VERSION,EDITION,PACKAGE_DIGEST,SIGNATURE_STATE,PREFLIGHT_STATE,STATUS,REASON,CREATED_BY) VALUES (:id,:version,:edition,:digest,'VERIFIED','PENDING','STAGED',:reason,:actor)", {"id": upgrade_id, "version": package_version[:64], "edition": edition[:32], "digest": package_digest[:128], "reason": reason[:2000], "actor": actor})
    identity_api._audit(actor, "UPGRADE_STAGE", "UPGRADE", upgrade_id, "ALLOW", reason)
    return {"upgrade_id": upgrade_id, "status": "STAGED", "signature_state": "VERIFIED"}


def _staging_directory() -> Path:
    path = Path(os.environ.get("CX_UPGRADE_STAGING_DIR", str(Path.home() / ".ai-agent-infra" / "upgrade-staging")))
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _verify_package_manifest(archive: zipfile.ZipFile) -> tuple[Dict[str, Any], str]:
    names = [item.filename for item in archive.infolist() if not item.is_dir()]
    if not names or any(name.startswith("/") or ".." in Path(name).parts for name in names):
        raise ManagementError("upgrade archive contains an unsafe path")
    manifest_names = [name for name in names if name.endswith("/build-manifest.json")]
    guard_names = [name for name in names if name.endswith("/package-files.sha256")]
    if len(manifest_names) != 1 or len(guard_names) != 1:
        raise ManagementError("upgrade archive must contain exactly one package manifest and file manifest")
    root = manifest_names[0].rsplit("/", 1)[0] + "/"
    if guard_names[0] != root + "package-files.sha256":
        raise ManagementError("upgrade archive manifests are not in the same package root")
    try:
        manifest = json.loads(archive.read(manifest_names[0]).decode("ascii"))
        lines = archive.read(guard_names[0]).decode("ascii").splitlines()
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ManagementError("upgrade archive manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != "ai-agent-infra-build/v1":
        raise ManagementError("upgrade archive build manifest is invalid")
    expected: Dict[str, str] = {}
    for line in lines:
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise ManagementError("upgrade archive file manifest is invalid") from exc
        if len(digest) != 64 or not all(char in "0123456789abcdef" for char in digest.lower()):
            raise ManagementError("upgrade archive file digest is invalid")
        expected[relative.strip()] = digest.lower()
    actual = {name[len(root):] for name in names if name.startswith(root) and not name.endswith("/package-files.sha256")}
    if set(expected) != actual:
        raise ManagementError("upgrade archive file manifest does not match its contents")
    for relative, digest in expected.items():
        if hashlib.sha256(archive.read(root + relative)).hexdigest() != digest:
            raise ManagementError("upgrade archive file digest verification failed")
    return manifest, root


def _verify_release_signature(archive: zipfile.ZipFile, root: str, package_digest: str) -> tuple[str, str]:
    """Verify an optional Ed25519 release signature against an operator key.

    Packaging does not carry private keys. An operator supplies the trusted
    public key through ``CX_RELEASE_SIGNING_PUBLIC_KEY`` and signs the archive
    digest externally. Without both pieces, the package stays untrusted.
    """
    signature_name = root + "release-signature.json"
    public_key = os.environ.get("CX_RELEASE_SIGNING_PUBLIC_KEY", "").strip()
    if not public_key or signature_name not in archive.namelist():
        return "UNTRUSTED", "release signing key or signature is unavailable"
    try:
        envelope = json.loads(archive.read(signature_name).decode("ascii"))
        if str(envelope.get("algorithm") or "").upper() != "ED25519" or str(envelope.get("digest") or "") != package_digest:
            return "UNTRUSTED", "release signature envelope does not bind the archive digest"
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
        signature = base64.urlsafe_b64decode(str(envelope.get("signature") or "") + "=" * (-len(str(envelope.get("signature") or "")) % 4))
        Ed25519PublicKey.from_public_bytes(key).verify(signature, package_digest.encode("ascii"))
    except Exception:
        return "UNTRUSTED", "release signature verification failed"
    return "VERIFIED", str(envelope.get("key_id") or "operator-key")[:256]


def stage_upgrade_archive(actor: str, filename: str, content: bytes, reason: str,
                          current_version: str = "") -> Dict[str, Any]:
    """Stage an uploaded archive only after server-side integrity checks."""
    _require_manage(actor)
    if len(str(reason or "").strip()) < 3 or not filename.lower().endswith(".zip") or not content:
        raise ManagementError("a ZIP package and a reason are required")
    if len(content) > 2 * 1024 * 1024 * 1024:
        raise ManagementError("upgrade package exceeds the 2 GiB staging limit")
    package_digest = hashlib.sha256(content).hexdigest()
    try:
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 4 * 1024 * 1024 * 1024:
                raise ManagementError("upgrade archive expanded size exceeds the staging limit")
            manifest, root = _verify_package_manifest(archive)
            signature_state, signature_detail = _verify_release_signature(archive, root, package_digest)
    except zipfile.BadZipFile as exc:
        raise ManagementError("upgrade package is not a valid ZIP archive") from exc
    database = str((manifest.get("database") or {}).get("key") or "").lower()
    edition = str(manifest.get("edition") or "")
    version = str(manifest.get("version") or "")
    if database not in {"oracle", "pg", "yashandb"} or edition not in {"Community", "Enterprise"} or not version:
        raise ManagementError("upgrade package manifest has an unsupported database, edition, or version")
    stage = _staging_directory() / (package_digest + ".zip")
    if not stage.exists():
        stage.write_bytes(content)
        try:
            os.chmod(stage, 0o600)
        except OSError:
            pass
    artifact_id, upgrade_id = _id("ART"), _id("UPG")
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one("SELECT UPGRADE_ID,PACKAGE_VERSION,EDITION,STATUS,SIGNATURE_STATE FROM CX_UPGRADE_PLANS WHERE PACKAGE_DIGEST=:digest FOR UPDATE", {"digest": package_digest}))
        if existing:
            return {"upgrade_id": existing["upgrade_id"], "status": existing["status"], "idempotent": True,
                    "signature_state": existing.get("signature_state") or signature_state,
                    "signature_detail": signature_detail, "package_version": existing.get("package_version") or version,
                    "edition": existing.get("edition") or edition}
        tx.execute(
            "INSERT INTO CX_MANAGEMENT_ARTIFACTS(ARTIFACT_ID,ARTIFACT_KEY,ARTIFACT_VERSION,ARTIFACT_KIND,CONTENT_DIGEST,"
            "SIGNATURE,CLASSIFICATION,SECRET_FREE,STATUS,STORAGE_ADAPTER,CREATED_BY) VALUES "
            "(:id,:key,:version,'RELEASE_PACKAGE',:digest,:signature,'RESTRICTED','Y','STAGED','PEER',:actor)",
            {"id": artifact_id, "key": "release-package", "version": version[:64], "digest": package_digest,
             "signature": signature_detail, "actor": actor},
        )
        tx.execute(
            "INSERT INTO CX_UPGRADE_PLANS(UPGRADE_ID,PACKAGE_VERSION,EDITION,PACKAGE_DIGEST,SIGNATURE_STATE,PREFLIGHT_STATE,"
            "STATUS,REASON,CREATED_BY) VALUES (:id,:version,:edition,:digest,:signature,'PENDING','STAGED',:reason,:actor)",
            {"id": upgrade_id, "version": version[:64], "edition": edition[:32], "digest": package_digest,
             "signature": signature_state, "reason": reason[:2000], "actor": actor},
        )
        identity_api._audit_tx(tx, actor, "UPGRADE_ARCHIVE_STAGE", "UPGRADE", upgrade_id,
                               "ALLOW" if signature_state == "VERIFIED" else "DENY", reason)
        return {"upgrade_id": upgrade_id, "status": "STAGED", "signature_state": signature_state,
                "signature_detail": signature_detail, "package_version": version, "edition": edition}
    result = connection.execute_transaction_callback(work)
    if str(result.get("signature_state") or "").upper() == "VERIFIED":
        result.update(auto_schedule_upgrade(actor, str(result["upgrade_id"]), str(edition), current_version))
    else:
        result["automation_state"] = "WAITING_FOR_TRUSTED_SIGNATURE"
    return result


def _package_manifest_for_upgrade(upgrade_id: str) -> tuple[Dict[str, Any], str, str]:
    """Read a staged package without extracting or executing it."""
    row = _row(connection.execute_query_one(
        "SELECT PACKAGE_DIGEST FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id",
        {"id": upgrade_id},
    ))
    if not row:
        raise ManagementError("upgrade package is unavailable")
    archive_path = _staging_directory() / (str(row.get("package_digest") or "") + ".zip")
    if not archive_path.is_file():
        raise ManagementError("staged upgrade archive is unavailable on this node")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest, root = _verify_package_manifest(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ManagementError("staged upgrade archive cannot be read") from exc
    return manifest, root, str(row.get("package_digest") or "")


def auto_schedule_upgrade(actor: str, upgrade_id: str, expected_edition: str,
                          current_version: str = "") -> Dict[str, Any]:
    """Automatically prepare governed node and Agent updates after upload.

    This removes manual ID/node/recipient entry from the Dashboard. It does
    not execute archive contents, bypass signature verification, or switch an
    active runtime before that runtime reports a safe point.
    """
    _require_manage(actor)
    manifest, _root, package_digest = _package_manifest_for_upgrade(upgrade_id)
    database = str((manifest.get("database") or {}).get("key") or "").lower()
    current_database = str(getattr(connection, "DATABASE_DIALECT", "")).lower()
    database_key = "pg" if current_database in {"pg", "postgresql"} else current_database
    edition = str(manifest.get("edition") or "")
    version = str(manifest.get("version") or "")
    if database != database_key:
        raise ManagementError("upgrade package database does not match this installation")
    if edition.upper() != str(expected_edition or "").upper():
        raise ManagementError("upgrade package edition is incompatible with this installation")
    if not version:
        raise ManagementError("upgrade package version is missing")
    if current_version and _compare_versions(version, current_version) <= 0:
        raise ManagementError("upgrade package version must be newer than this installation")

    def work(tx: Any) -> Dict[str, Any]:
        plan = _row(tx.query_one(
            "SELECT UPGRADE_ID,PACKAGE_DIGEST,SIGNATURE_STATE,STATUS FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE",
            {"id": upgrade_id},
        ))
        if not plan or str(plan.get("package_digest") or "") != package_digest:
            raise ManagementError("upgrade plan does not match the staged archive")
        if str(plan.get("signature_state") or "").upper() != "VERIFIED":
            raise ManagementError("upgrade package signature is not trusted")
        if str(plan.get("status") or "") == "AUTO_SCHEDULED":
            return {"status": "AUTO_SCHEDULED", "automation_state": "ALREADY_SCHEDULED", "upgrade_id": upgrade_id}
        nodes = _rows(tx.query(
            "SELECT DISTINCT NODE_ID FROM CX_AGENT_INSTANCES WHERE STATUS='ACTIVE' AND NODE_ID IS NOT NULL",
            {},
        ))
        nodes += _rows(tx.query(
            "SELECT DISTINCT NODE_ID FROM CX_RUNTIME_WORKERS WHERE STATUS='ONLINE' AND NODE_ID IS NOT NULL",
            {},
        ))
        node_ids = sorted({str(item.get("node_id") or "") for item in nodes if str(item.get("node_id") or "")})
        if not node_ids:
            node_ids = [os.environ.get("MEMORY_SERVER_NODE_ID", "LOCAL_NODE")[:256] or "LOCAL_NODE"]
        for node_id in node_ids:
            existing = _row(tx.query_one(
                "SELECT UPGRADE_NODE_ID FROM CX_UPGRADE_NODES WHERE UPGRADE_ID=:upgrade AND NODE_ID=:node FOR UPDATE",
                {"upgrade": upgrade_id, "node": node_id},
            ))
            if not existing:
                tx.execute(
                    "INSERT INTO CX_UPGRADE_NODES(UPGRADE_NODE_ID,UPGRADE_ID,NODE_ID,STATE,NEW_VERSION,SKILL_STATE,HEALTH_STATE) "
                    "VALUES (:id,:upgrade,:node,'PENDING',:version,'QUEUED','UNKNOWN')",
                    {"id": _id("UPN"), "upgrade": upgrade_id, "node": node_id, "version": version[:64]},
                )
        recipients = _rows(tx.query(
            "SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_TYPE='AGENT' AND STATUS='ACTIVE'",
            {},
        ))
        for recipient in recipients:
            agent_id = str(recipient.get("principal_id") or "")
            if not agent_id:
                continue
            params = {"id": _id("SKD"), "upgrade": upgrade_id, "agent": agent_id,
                      "version": version[:64], "evidence": _json({"issuer": actor, "mode": "AUTO_UPLOAD", "package_digest": package_digest})}
            _update_or_insert(
                tx,
                "UPDATE CX_SKILL_DISTRIBUTION SET MESSAGE_STATE='SENT',ACKNOWLEDGEMENT_STATE='PENDING',UPDATED_AT=CURRENT_TIMESTAMP,EVIDENCE_JSON=:evidence "
                "WHERE UPGRADE_ID=:upgrade AND AGENT_ID=:agent AND SKILL_VERSION=:version",
                "INSERT INTO CX_SKILL_DISTRIBUTION(DISTRIBUTION_ID,UPGRADE_ID,AGENT_ID,SKILL_VERSION,MESSAGE_STATE,ACKNOWLEDGEMENT_STATE,ACTIVATION_STATE,DRIFT_STATE,EVIDENCE_JSON) "
                "VALUES (:id,:upgrade,:agent,:version,'SENT','PENDING','OLD_VERSION','UNKNOWN',:evidence)",
                params,
            )
        tx.execute(
            "UPDATE CX_UPGRADE_PLANS SET PREFLIGHT_STATE='PASSED',APPROVAL_STATE='AUTOMATED_CONTROLLED',ROLLOUT_STATE='READY',STATUS='AUTO_SCHEDULED',UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id",
            {"id": upgrade_id},
        )
        identity_api._audit_tx(tx, actor, "UPGRADE_AUTO_SCHEDULE", "UPGRADE", upgrade_id, "ALLOW",
                               "verified package automatically scheduled for governed nodes and Agents")
        return {"upgrade_id": upgrade_id, "status": "AUTO_SCHEDULED", "automation_state": "AUTO_SCHEDULED",
                "node_count": len(node_ids), "agent_count": len(recipients), "package_version": version}
    return connection.execute_transaction_callback(work)


def preflight_upgrade(actor: str, upgrade_id: str, expected_edition: str) -> Dict[str, Any]:
    _require_manage(actor)
    def work(tx: Any) -> Dict[str, Any]:
        row = _row(tx.query_one("SELECT UPGRADE_ID,EDITION,SIGNATURE_STATE,STATUS FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE", {"id": upgrade_id}))
        if not row or str(row.get("status") or "") != "STAGED":
            raise ManagementError("upgrade is not staged")
        if str(row.get("signature_state") or "") != "VERIFIED":
            raise ManagementError("upgrade package signature is not trusted")
        if str(row.get("edition") or "").upper() != str(expected_edition or "").upper():
            raise ManagementError("upgrade package edition is incompatible with this installation")
        tx.execute("UPDATE CX_UPGRADE_PLANS SET PREFLIGHT_STATE='PASSED',STATUS='PREFLIGHT',UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id", {"id": upgrade_id})
        identity_api._audit_tx(tx, actor, "UPGRADE_PREFLIGHT", "UPGRADE", upgrade_id, "ALLOW", "server-side package and edition preflight passed")
        return {"upgrade_id": upgrade_id, "status": "PREFLIGHT", "preflight_state": "PASSED"}
    return connection.execute_transaction_callback(work)


def approve_upgrade(actor: str, upgrade_id: str, decision: str, reason: str) -> Dict[str, Any]:
    """Record the mandatory human approval before Admin Agent quorum voting."""
    _require_manage(actor)
    verdict = str(decision or "").upper()
    if verdict not in {"APPROVE", "REJECT"} or len(str(reason or "").strip()) < 3:
        raise ManagementError("upgrade decision and reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        plan = _row(tx.query_one(
            "SELECT UPGRADE_ID,STATUS,CREATED_BY FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE",
            {"id": upgrade_id},
        ))
        if not plan or str(plan.get("status") or "") != "PREFLIGHT":
            raise ManagementError("upgrade is not ready for human approval")
        if str(plan.get("created_by") or "") == actor:
            raise ManagementError("upgrade submitter cannot provide the required human approval")
        params = {"id": _id("UPA"), "upgrade": upgrade_id, "actor": actor,
                  "decision": verdict, "reason": reason[:2000]}
        _update_or_insert(
            tx,
            "UPDATE CX_UPGRADE_APPROVALS SET DECISION=:decision,REASON=:reason,CREATED_AT=CURRENT_TIMESTAMP "
            "WHERE UPGRADE_ID=:upgrade AND APPROVAL_KIND='HUMAN' AND PRINCIPAL_ID=:actor",
            "INSERT INTO CX_UPGRADE_APPROVALS(APPROVAL_ID,UPGRADE_ID,APPROVAL_KIND,PRINCIPAL_ID,DECISION,REASON) "
            "VALUES (:id,:upgrade,'HUMAN',:actor,:decision,:reason)",
            params,
        )
        status = "HUMAN_APPROVAL" if verdict == "APPROVE" else "REJECTED"
        tx.execute("UPDATE CX_UPGRADE_PLANS SET APPROVAL_STATE=:state,STATUS=:status,UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id", {"state": status, "status": status, "id": upgrade_id})
        identity_api._audit_tx(tx, actor, "UPGRADE_HUMAN_" + verdict, "UPGRADE", upgrade_id, "ALLOW", reason)
        return {"upgrade_id": upgrade_id, "status": status, "decision": verdict}
    return connection.execute_transaction_callback(work)


def vote_upgrade(agent_id: str, instance_id: str, upgrade_id: str, decision: str, term: int,
                 fencing_token: int, reason: str) -> Dict[str, Any]:
    """Accept one authenticated Admin Agent vote bound to the current term."""
    verdict = str(decision or "").upper()
    if verdict not in {"APPROVE", "REJECT"} or len(str(reason or "").strip()) < 3:
        raise ManagementError("upgrade vote and reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        plan = _row(tx.query_one("SELECT UPGRADE_ID,STATUS FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE", {"id": upgrade_id}))
        if not plan or str(plan.get("status") or "") != "HUMAN_APPROVAL":
            raise ManagementError("upgrade is not ready for Admin Agent quorum")
        group = _row(tx.query_one("SELECT CURRENT_TERM,FENCING_TOKEN,CONFIGURATION_STATE FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id FOR UPDATE", {"id": ADMIN_GROUP_ID}))
        if not group or str(group.get("configuration_state") or "") != "VALID" or not admin_ha.accept_write(current_term=int(group.get("current_term") or 0), current_fencing=int(group.get("fencing_token") or 0), write_term=int(term), write_fencing=int(fencing_token), lease_valid=True):
            raise ManagementError("upgrade vote carries a stale Admin Agent term or fencing token")
        instance = _row(tx.query_one("SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance AND AGENT_ID=:agent AND STATUS='ACTIVE' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP", {"instance": instance_id, "agent": agent_id}))
        member = _row(tx.query_one("SELECT MEMBER_ID,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'", {"group_id": ADMIN_GROUP_ID, "agent": agent_id}))
        if not instance or not member:
            raise ManagementError("only an active voting Admin Agent instance may vote")
        params = {"id": _id("UPA"), "upgrade": upgrade_id, "agent": agent_id,
                  "decision": verdict, "term": int(term), "fencing": int(fencing_token),
                  "reason": reason[:2000]}
        _update_or_insert(
            tx,
            "UPDATE CX_UPGRADE_APPROVALS SET DECISION=:decision,TERM=:term,FENCING_TOKEN=:fencing,REASON=:reason,CREATED_AT=CURRENT_TIMESTAMP "
            "WHERE UPGRADE_ID=:upgrade AND APPROVAL_KIND='ADMIN_AGENT' AND PRINCIPAL_ID=:agent",
            "INSERT INTO CX_UPGRADE_APPROVALS(APPROVAL_ID,UPGRADE_ID,APPROVAL_KIND,PRINCIPAL_ID,DECISION,TERM,FENCING_TOKEN,REASON) "
            "VALUES (:id,:upgrade,'ADMIN_AGENT',:agent,:decision,:term,:fencing,:reason)",
            params,
        )
        members = _rows(tx.query("SELECT MEMBER_ID,AGENT_ID,STATUS,VOTING_ENABLED,WEIGHT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'", {"group_id": ADMIN_GROUP_ID}))
        approvals = _rows(tx.query("SELECT PRINCIPAL_ID,DECISION FROM CX_UPGRADE_APPROVALS WHERE UPGRADE_ID=:upgrade AND APPROVAL_KIND='ADMIN_AGENT' AND TERM=:term AND FENCING_TOKEN=:fencing", {"upgrade": upgrade_id, "term": int(term), "fencing": int(fencing_token)}))
        outcome = admin_ha.quorum(members, [{"agent_id": item["principal_id"], "decision": item["decision"]} for item in approvals])
        status = "QUORUM_APPROVAL" if outcome["allowed"] else "HUMAN_APPROVAL"
        tx.execute("UPDATE CX_UPGRADE_PLANS SET APPROVAL_STATE=:state,STATUS=:status,UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id", {"state": "QUORUM_APPROVED" if outcome["allowed"] else "QUORUM_PENDING", "status": status, "id": upgrade_id})
        identity_api._audit_tx(tx, agent_id, "UPGRADE_ADMIN_VOTE_" + verdict, "UPGRADE", upgrade_id, "ALLOW", reason)
        return {"upgrade_id": upgrade_id, "status": status, "quorum": outcome}
    return connection.execute_transaction_callback(work)


def start_upgrade_rollout(actor: str, upgrade_id: str, node_ids: List[str], reason: str) -> Dict[str, Any]:
    """Create the serialized node plan after approvals; adapters perform the work."""
    _require_manage(actor)
    requested_nodes = sorted({str(node).strip()[:256] for node in node_ids if str(node).strip()})
    if not requested_nodes or len(str(reason or "").strip()) < 3:
        raise ManagementError("at least one rollout node and a reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        plan = _row(tx.query_one("SELECT UPGRADE_ID,STATUS FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE", {"id": upgrade_id}))
        if not plan or str(plan.get("status") or "") != "QUORUM_APPROVAL":
            raise ManagementError("human and Admin Agent quorum approval are required")
        for node_id in requested_nodes:
            existing = _row(tx.query_one("SELECT UPGRADE_NODE_ID FROM CX_UPGRADE_NODES WHERE UPGRADE_ID=:upgrade AND NODE_ID=:node FOR UPDATE", {"upgrade": upgrade_id, "node": node_id}))
            if not existing:
                tx.execute("INSERT INTO CX_UPGRADE_NODES(UPGRADE_NODE_ID,UPGRADE_ID,NODE_ID,STATE,SKILL_STATE,HEALTH_STATE) VALUES (:id,:upgrade,:node,'PENDING','PENDING','UNKNOWN')", {"id": _id("UPN"), "upgrade": upgrade_id, "node": node_id})
        tx.execute("UPDATE CX_UPGRADE_PLANS SET ROLLOUT_STATE='READY',STATUS='ROLLING',UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id", {"id": upgrade_id})
        identity_api._audit_tx(tx, actor, "UPGRADE_ROLLOUT_PREPARE", "UPGRADE", upgrade_id, "ALLOW", reason)
        return {"upgrade_id": upgrade_id, "status": "ROLLING", "nodes": requested_nodes}
    return connection.execute_transaction_callback(work)


def _advance_upgrade_node(actor: str, upgrade_id: str, node_id: str, target_state: str,
                          active_work_count: int, health_state: str, reason: str) -> Dict[str, Any]:
    """Advance one node after its caller has passed the appropriate boundary."""
    state = str(target_state or "").upper()
    allowed = {"PENDING": "DRAINING", "DRAINING": "MIGRATING", "MIGRATING": "HEALTHY"}
    if state not in set(allowed.values()) or int(active_work_count) < 0 or len(str(reason or "").strip()) < 3:
        raise ManagementError("upgrade node transition is invalid")
    def work(tx: Any) -> Dict[str, Any]:
        node = _row(tx.query_one("SELECT UPGRADE_NODE_ID,STATE FROM CX_UPGRADE_NODES WHERE UPGRADE_ID=:upgrade AND NODE_ID=:node FOR UPDATE", {"upgrade": upgrade_id, "node": node_id}))
        if not node or allowed.get(str(node.get("state") or "").upper()) != state:
            raise ManagementError("upgrade node transition is stale or out of order")
        if state == "DRAINING":
            active = _row(tx.query_one(
                "SELECT UPGRADE_NODE_ID FROM CX_UPGRADE_NODES WHERE UPGRADE_ID=:upgrade "
                "AND STATE IN ('DRAINING','MIGRATING') AND UPGRADE_NODE_ID<>:node "
                + ("LIMIT 1" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 1 ROWS ONLY"),
                {"upgrade": upgrade_id, "node": node["upgrade_node_id"]},
            ))
            if active:
                raise ManagementError("another rollout node is still draining or migrating")
        if state == "MIGRATING" and int(active_work_count) != 0:
            raise ManagementError("node still has active work; it must remain draining")
        tx.execute("UPDATE CX_UPGRADE_NODES SET STATE=:state,ACTIVE_WORK_COUNT=:work,HEALTH_STATE=:health,EVIDENCE_JSON=:evidence,UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_NODE_ID=:id", {"state": state, "work": int(active_work_count), "health": str(health_state or "UNKNOWN")[:32], "evidence": _json({"actor": actor, "reason": reason[:2000]}), "id": node["upgrade_node_id"]})
        remaining = _rows(tx.query("SELECT STATE FROM CX_UPGRADE_NODES WHERE UPGRADE_ID=:upgrade", {"upgrade": upgrade_id}))
        complete = bool(remaining) and all(str(item.get("state") or "") == "HEALTHY" for item in remaining)
        tx.execute("UPDATE CX_UPGRADE_PLANS SET ROLLOUT_STATE=:rollout,STATUS=:status,UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:id", {"rollout": "COMPLETED" if complete else "IN_PROGRESS", "status": "SKILL_DISTRIBUTION" if complete else "ROLLING", "id": upgrade_id})
        identity_api._audit_tx(tx, actor, "UPGRADE_NODE_" + state, "UPGRADE_NODE", str(node["upgrade_node_id"]), "ALLOW", reason)
        return {"upgrade_id": upgrade_id, "node_id": node_id, "state": state, "rollout_complete": complete}
    return connection.execute_transaction_callback(work)


def advance_upgrade_node(actor: str, upgrade_id: str, node_id: str, target_state: str,
                         active_work_count: int, health_state: str, reason: str) -> Dict[str, Any]:
    """Record a supervised node transition from the protected Dashboard."""
    _require_manage(actor)
    return _advance_upgrade_node(actor, upgrade_id, node_id, target_state,
                                 active_work_count, health_state, reason)


def advance_upgrade_node_from_gateway(agent_id: str, instance_id: str, upgrade_id: str,
                                      target_state: str, active_work_count: int,
                                      health_state: str, reason: str) -> Dict[str, Any]:
    """Accept maintenance evidence only from the current Leader's own node."""
    group = _row(connection.execute_query_one(
        "SELECT LEADER_MEMBER_ID,CURRENT_TERM,FENCING_TOKEN,LEADER_LEASE_EXPIRES_AT "
        "FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id", {"id": ADMIN_GROUP_ID},
    ))
    member = _row(connection.execute_query_one(
        "SELECT MEMBER_ID,NODE_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id "
        "AND AGENT_ID=:agent AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'",
        {"group_id": ADMIN_GROUP_ID, "agent": agent_id},
    ))
    instance = _row(connection.execute_query_one(
        "SELECT INSTANCE_ID FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance AND AGENT_ID=:agent "
        "AND STATUS='ACTIVE' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
        {"instance": instance_id, "agent": agent_id},
    ))
    if not group or not member or not instance or str(group.get("leader_member_id") or "") != str(member.get("member_id") or ""):
        raise ManagementError("only the current active Admin Agent Leader may submit rollout evidence")
    lease = _row(connection.execute_query_one(
        "SELECT GROUP_ID FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:id AND LEADER_LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
        {"id": ADMIN_GROUP_ID},
    ))
    if not lease:
        raise ManagementError("Admin Agent Leader lease is unavailable")
    return _advance_upgrade_node(agent_id, upgrade_id, str(member.get("node_id") or ""), target_state,
                                 active_work_count, health_state, reason)


def distribute_upgrade_skill(actor: str, upgrade_id: str, agent_ids: List[str], skill_version: str,
                             reason: str) -> Dict[str, Any]:
    """Queue signed Skill-update notices; activation remains pinned to safe points."""
    _require_manage(actor)
    agents = sorted({str(agent).strip()[:128] for agent in agent_ids if str(agent).strip()})
    if not agents or not skill_version or len(str(reason or "").strip()) < 3:
        raise ManagementError("Agent recipients, Skill version, and reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        plan = _row(tx.query_one("SELECT UPGRADE_ID,STATUS,SIGNATURE_STATE FROM CX_UPGRADE_PLANS WHERE UPGRADE_ID=:id FOR UPDATE", {"id": upgrade_id}))
        if not plan or str(plan.get("status") or "") != "SKILL_DISTRIBUTION" or str(plan.get("signature_state") or "") != "VERIFIED":
            raise ManagementError("only a verified rollout-complete upgrade may distribute a Skill")
        for agent_id in agents:
            principal = _row(tx.query_one("SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id AND PRINCIPAL_TYPE='AGENT' AND STATUS='ACTIVE'", {"id": agent_id}))
            if not principal:
                raise ManagementError("Skill recipient Agent is unavailable")
            params = {"id": _id("SKD"), "upgrade": upgrade_id, "agent": agent_id,
                      "version": skill_version[:64], "evidence": _json({"issuer": actor,
                      "reason": reason[:2000], "signature_state": "VERIFIED"})}
            _update_or_insert(
                tx,
                "UPDATE CX_SKILL_DISTRIBUTION SET MESSAGE_STATE='SENT',ACKNOWLEDGEMENT_STATE='PENDING',EVIDENCE_JSON=:evidence,UPDATED_AT=CURRENT_TIMESTAMP "
                "WHERE UPGRADE_ID=:upgrade AND AGENT_ID=:agent AND SKILL_VERSION=:version",
                "INSERT INTO CX_SKILL_DISTRIBUTION(DISTRIBUTION_ID,UPGRADE_ID,AGENT_ID,SKILL_VERSION,MESSAGE_STATE,ACKNOWLEDGEMENT_STATE,ACTIVATION_STATE,DRIFT_STATE,EVIDENCE_JSON) "
                "VALUES (:id,:upgrade,:agent,:version,'SENT','PENDING','OLD_VERSION','UNKNOWN',:evidence)",
                params,
            )
        identity_api._audit_tx(tx, actor, "UPGRADE_SKILL_DISTRIBUTION", "UPGRADE", upgrade_id, "ALLOW", reason)
        return {"upgrade_id": upgrade_id, "recipients": agents, "skill_version": skill_version, "status": "SKILL_DISTRIBUTION"}
    return connection.execute_transaction_callback(work)


def acknowledge_upgrade_skill(agent_id: str, upgrade_id: str, skill_version: str, safe_point: bool,
                              verified: bool, detail: str = "") -> Dict[str, Any]:
    """Acknowledge verification and switch only at an Agent-declared safe point."""
    ack = "ACKNOWLEDGED" if verified else "FAILED"
    activation = "ACTIVE" if verified and safe_point else "OLD_VERSION"
    drift = "IN_SYNC" if activation == "ACTIVE" else "DRIFT"
    changed = connection.execute(
        "UPDATE CX_SKILL_DISTRIBUTION SET ACKNOWLEDGEMENT_STATE=:ack,ACTIVATION_STATE=:activation,DRIFT_STATE=:drift,"
        "EVIDENCE_JSON=:evidence,UPDATED_AT=CURRENT_TIMESTAMP WHERE UPGRADE_ID=:upgrade AND AGENT_ID=:agent "
        "AND SKILL_VERSION=:version AND MESSAGE_STATE='SENT'",
        {"ack": ack, "activation": activation, "drift": drift, "evidence": _json({"safe_point": bool(safe_point), "verified": bool(verified), "detail": str(detail or "")[:1000]}), "upgrade": upgrade_id, "agent": agent_id, "version": skill_version},
    )
    if changed != 1:
        raise ManagementError("Skill distribution acknowledgement is unavailable")
    identity_api._audit(agent_id, "UPGRADE_SKILL_ACK", "UPGRADE", upgrade_id, "ALLOW" if verified else "ERROR", detail or skill_version)
    return {"upgrade_id": upgrade_id, "agent_id": agent_id, "acknowledgement_state": ack, "activation_state": activation, "drift_state": drift}


def pending_upgrade_skills(agent_id: str) -> List[Dict[str, Any]]:
    """Return signed-update metadata to one authenticated Agent only.

    The archive itself is deliberately not sent through the Gateway. An Agent
    obtains the approved Skill through its managed distribution path, verifies
    it, and calls the acknowledgement route at a task-safe point.
    """
    suffix = " LIMIT 20" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST 20 ROWS ONLY"
    rows = _rows(connection.execute_query(
        "SELECT d.UPGRADE_ID,d.SKILL_VERSION,d.MESSAGE_STATE,d.ACKNOWLEDGEMENT_STATE,d.ACTIVATION_STATE,d.DRIFT_STATE,"
        "p.PACKAGE_DIGEST,p.PACKAGE_VERSION,p.SIGNATURE_STATE FROM CX_SKILL_DISTRIBUTION d "
        "JOIN CX_UPGRADE_PLANS p ON p.UPGRADE_ID=d.UPGRADE_ID "
        "WHERE d.AGENT_ID=:agent AND d.MESSAGE_STATE='SENT' AND d.ACKNOWLEDGEMENT_STATE='PENDING' "
        "AND p.SIGNATURE_STATE='VERIFIED' ORDER BY d.UPDATED_AT ASC" + suffix,
        {"agent": agent_id},
    ))
    return [{
        "upgrade_id": row["upgrade_id"],
        "skill_version": row["skill_version"],
        "package_version": row["package_version"],
        "package_digest": row["package_digest"],
        "signature_state": row["signature_state"],
        "activation_state": row["activation_state"],
        "safe_point_required": True,
    } for row in rows]


def record_artifact_receipt(agent_id: str, artifact_id: str, node_id: str, received_digest: str,
                            signature_state: str, available: bool, detail: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a node receipt for peer synchronization without accepting secrets."""
    if not node_id or len(received_digest) != 64 or str(signature_state).upper() not in {"VERIFIED", "FAILED"}:
        raise ManagementError("artifact receipt is invalid")
    def work(tx: Any) -> str:
        artifact = _row(tx.query_one(
            "SELECT ARTIFACT_ID,CONTENT_DIGEST,SECRET_FREE FROM CX_MANAGEMENT_ARTIFACTS "
            "WHERE ARTIFACT_ID=:id FOR UPDATE", {"id": artifact_id},
        ))
        if not artifact or str(artifact.get("secret_free") or "N").upper() != "Y" or str(artifact.get("content_digest") or "") != received_digest:
            raise ManagementError("artifact receipt does not match a secret-free catalog entry")
        status = "AVAILABLE" if available and str(signature_state).upper() == "VERIFIED" else "MISSING"
        params = {"id": _id("ARR"), "artifact": artifact_id, "node": node_id[:256],
                  "digest": received_digest, "signature": str(signature_state).upper(),
                  "status": status, "detail": _json(detail or {})}
        _update_or_insert(
            tx,
            "UPDATE CX_MANAGEMENT_ARTIFACT_RECEIPTS SET RECEIVED_DIGEST=:digest,SIGNATURE_STATE=:signature,AVAILABILITY_STATE=:status,DETAIL_JSON=:detail,RECEIVED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE ARTIFACT_ID=:artifact AND NODE_ID=:node",
            "INSERT INTO CX_MANAGEMENT_ARTIFACT_RECEIPTS(RECEIPT_ID,ARTIFACT_ID,NODE_ID,RECEIVED_DIGEST,SIGNATURE_STATE,AVAILABILITY_STATE,DETAIL_JSON,RECEIVED_AT) "
            "VALUES (:id,:artifact,:node,:digest,:signature,:status,:detail,CURRENT_TIMESTAMP)",
            params,
        )
        return status
    status = connection.execute_transaction_callback(work)
    identity_api._audit(agent_id, "MANAGEMENT_ARTIFACT_RECEIPT", "MANAGEMENT_ARTIFACT", artifact_id, "ALLOW" if status == "AVAILABLE" else "ERROR", node_id)
    return {"artifact_id": artifact_id, "node_id": node_id, "availability_state": status}


def list_management_state(actor: str) -> Dict[str, Any]:
    _require_manage(actor)
    group = list_group(actor)
    channel = _row(connection.execute_query_one("SELECT CHANNEL_ID,CHANNEL_NAME,STATUS,CLASSIFICATION,CHANNEL_TYPE FROM CX_CHANNELS WHERE CHANNEL_ID=:id", {"id": ADMIN_CHANNEL_ID})) or {}
    plans = _rows(connection.execute_query("SELECT UPGRADE_ID,PACKAGE_VERSION,EDITION,SIGNATURE_STATE,PREFLIGHT_STATE,APPROVAL_STATE,ROLLOUT_STATE,STATUS,UPDATED_AT FROM CX_UPGRADE_PLANS ORDER BY UPDATED_AT DESC " + ("LIMIT 20" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 20 ROWS ONLY"), {}))
    nodes = _rows(connection.execute_query("SELECT UPGRADE_ID,NODE_ID,STATE,ACTIVE_WORK_COUNT,SKILL_STATE,HEALTH_STATE,UPDATED_AT FROM CX_UPGRADE_NODES ORDER BY UPDATED_AT DESC " + ("LIMIT 100" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 100 ROWS ONLY"), {}))
    distributions = _rows(connection.execute_query("SELECT UPGRADE_ID,AGENT_ID,SKILL_VERSION,MESSAGE_STATE,ACKNOWLEDGEMENT_STATE,ACTIVATION_STATE,DRIFT_STATE,UPDATED_AT FROM CX_SKILL_DISTRIBUTION ORDER BY UPDATED_AT DESC " + ("LIMIT 100" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 100 ROWS ONLY"), {}))
    commands = _rows(connection.execute_query("SELECT COMMAND_ID,AGENT_ID,INSTANCE_ID,REQUESTED_STATE,CONTROL_GENERATION,AUTHORITY_STATE,AGENT_ACK_STATE,INFRASTRUCTURE_ACK_STATE,CREATED_AT FROM CX_AGENT_CONTAINMENT_COMMANDS ORDER BY CREATED_AT DESC " + ("LIMIT 20" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else "FETCH FIRST 20 ROWS ONLY"), {}))
    return {"channel": channel, "admin_group": group, "upgrades": plans, "upgrade_nodes": nodes,
            "skill_distributions": distributions, "containment": commands,
            "storage_adapters": [{"key": "PEER", "status": "AVAILABLE"}, {"key": "NFS", "status": "ADAPTER_REQUIRED"}, {"key": "OBJECT_STORAGE", "status": "ADAPTER_REQUIRED"}, {"key": "UNIFIED_STORAGE", "status": "ADAPTER_REQUIRED"}]}
