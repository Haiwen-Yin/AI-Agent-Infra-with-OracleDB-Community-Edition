"""Governed Security Domain administration and collaboration-group binding.

Security Domains are the authorization boundary.  Legacy collaboration groups
remain execution coordination records and can only provide reviewed candidates
to a conversion draft; no Channel or group relationship grants authority.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from . import connection, identity_api


DOMAIN_ACTION = "domains.manage"
DOMAIN_READ_ACTION = "channels.read"
VALID_DOMAIN_STATES = {"DRAFT", "ACTIVE", "SUSPENDED", "REVOKED"}
VALID_MEMBER_STATES = {"ACTIVE", "SUSPENDED", "REVOKED"}
VALID_BINDING_TYPES = {"CHANNEL", "LEGACY_COLLAB_GROUP"}
VALID_BINDING_STATES = {"DRAFT", "ACTIVE", "SUSPENDED", "REVOKED", "SUPERSEDED"}
VALID_DRAFT_STATES = {"DRAFT", "REVIEW", "APPROVED", "APPLIED", "REJECTED", "EXPIRED", "FAILED"}
VALID_TIERS = {"OWNER", "ADMIN", "MEMBER", "VIEWER"}


class SecurityDomainError(ValueError):
    """Safe error for Security Domain operations."""


class SecurityDomainConflict(SecurityDomainError):
    """A domain proposal or binding no longer matches current state."""


def _row(value: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): item for key, item in dict(value).items()} if value else None


def _rows(values: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(value) or {} for value in values]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _id(prefix: str) -> str:
    return identity_api._id(prefix)


def _text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    result = str(value or "").strip()
    if (required and not result) or len(result) > maximum or "\x00" in result:
        raise SecurityDomainError(f"{field} is invalid")
    return result


def _classification(value: Any) -> str:
    try:
        return identity_api._classification(value)
    except identity_api.IdentityError as exc:
        raise SecurityDomainError("Security classification is invalid") from exc


def _timestamp(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        return identity_api._timestamp(value)
    except identity_api.IdentityError as exc:
        raise SecurityDomainError("membership validity is invalid") from exc


def _require(actor: str, action: str = DOMAIN_ACTION) -> None:
    decision = identity_api.effective_access(actor, action)
    if decision.get("decision") != "ALLOW":
        raise PermissionError(f"permission denied: {action}")


def _audit(actor: str, action: str, resource_type: str, resource_id: str, outcome: str, reason: str) -> None:
    identity_api._audit(actor, action, resource_type, resource_id, outcome, reason[:2000])


def _limit_clause() -> str:
    return "LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"} else "FETCH FIRST :limit ROWS ONLY"


def _execution_group_binding(group_expression: str, binding_expression: str = "b.TARGET_ID") -> str:
    """Compare legacy numeric PostgreSQL group IDs with portable text bindings."""
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"}:
        return f"{binding_expression}=CAST({group_expression} AS VARCHAR(128))"
    return f"{binding_expression}={group_expression}"


def _domain_row(domain_id: str, *, active_only: bool = False) -> Optional[Dict[str, Any]]:
    suffix = " AND d.STATUS = 'ACTIVE'" if active_only else ""
    return _row(connection.execute_query_one(
        "SELECT d.SECURITY_DOMAIN_ID,d.DOMAIN_NAME,d.CLASSIFICATION,d.PURPOSE,d.STATUS,d.CREATED_AT,"
        "g.OWNER_PRINCIPAL_ID,g.REASON,g.UPDATED_AT "
        "FROM CX_SECURITY_DOMAINS d LEFT JOIN CX_DOMAIN_GOVERNANCE g "
        "ON g.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID "
        "WHERE d.SECURITY_DOMAIN_ID=:domain_id" + suffix,
        {"domain_id": domain_id},
    ))


def _principal_exists(principal_id: str) -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id",
        {"principal_id": principal_id},
    ))
    if not row or str(row.get("status") or "").upper() not in {"ACTIVE", "PENDING_CONFIRMATION"}:
        raise SecurityDomainError("principal is unavailable")
    return row


def _actor_can_use_domain(actor: str, domain_id: str) -> bool:
    if identity_api.effective_access(actor, DOMAIN_ACTION).get("decision") == "ALLOW":
        return True
    row = _row(connection.execute_query_one(
        "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain_id "
        "AND PRINCIPAL_ID=:principal_id AND STATUS='ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
        {"domain_id": domain_id, "principal_id": actor},
    ))
    return bool(row)


def list_domains(actor: str, *, limit: int = 200, include_inactive: bool = False) -> List[Dict[str, Any]]:
    """Return only domains that the caller may discover."""
    identity_api._require(actor, DOMAIN_READ_ACTION)
    limit = max(1, min(int(limit), 500))
    admin = identity_api.effective_access(actor, DOMAIN_ACTION).get("decision") == "ALLOW"
    status = "" if include_inactive and admin else " AND d.STATUS='ACTIVE'"
    if admin:
        rows = connection.execute_query(
            "SELECT d.SECURITY_DOMAIN_ID,d.DOMAIN_NAME,d.CLASSIFICATION,d.PURPOSE,d.STATUS,d.CREATED_AT,"
            "g.OWNER_PRINCIPAL_ID,g.REASON,g.UPDATED_AT,"
            "(SELECT COUNT(*) FROM CX_DOMAIN_MEMBERS m WHERE m.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID "
            "AND m.STATUS='ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)) AS MEMBER_COUNT "
            "FROM CX_SECURITY_DOMAINS d LEFT JOIN CX_DOMAIN_GOVERNANCE g ON g.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID "
            "WHERE 1=1" + status + " ORDER BY d.DOMAIN_NAME,d.SECURITY_DOMAIN_ID " + _limit_clause(),
            {"limit": limit},
        )
    else:
        rows = connection.execute_query(
            "SELECT d.SECURITY_DOMAIN_ID,d.DOMAIN_NAME,d.CLASSIFICATION,d.PURPOSE,d.STATUS,d.CREATED_AT,"
            "g.OWNER_PRINCIPAL_ID,g.REASON,g.UPDATED_AT,1 AS MEMBER_COUNT "
            "FROM CX_SECURITY_DOMAINS d JOIN CX_DOMAIN_MEMBERS m ON m.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID "
            "LEFT JOIN CX_DOMAIN_GOVERNANCE g ON g.SECURITY_DOMAIN_ID=d.SECURITY_DOMAIN_ID "
            "WHERE m.PRINCIPAL_ID=:actor AND m.STATUS='ACTIVE' "
            "AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)" + status +
            " ORDER BY d.DOMAIN_NAME,d.SECURITY_DOMAIN_ID " + _limit_clause(),
            {"actor": actor, "limit": limit},
        )
    return _rows(rows)


def list_members(actor: str, domain_id: str) -> List[Dict[str, Any]]:
    if not _actor_can_use_domain(actor, domain_id):
        raise PermissionError("Security Domain access denied")
    rows = connection.execute_query(
        "SELECT m.MEMBERSHIP_ID,m.SECURITY_DOMAIN_ID,m.PRINCIPAL_ID,m.MEMBERSHIP_TIER,m.VALID_UNTIL,m.STATUS,"
        "p.PRINCIPAL_TYPE,p.DISPLAY_NAME,p.STATUS AS PRINCIPAL_STATUS "
        "FROM CX_DOMAIN_MEMBERS m JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=m.PRINCIPAL_ID "
        "WHERE m.SECURITY_DOMAIN_ID=:domain_id ORDER BY p.PRINCIPAL_TYPE,p.DISPLAY_NAME,m.PRINCIPAL_ID",
        {"domain_id": domain_id},
    )
    return _rows(rows)


def create_domain(actor: str, domain_id: str, name: str, classification: str, purpose: str, owner_principal_id: str, reason: str, *, status: str = "ACTIVE") -> Dict[str, Any]:
    _require(actor)
    domain_id = _text(domain_id, "security domain ID", 128, required=True).upper()
    if domain_id == "DEFAULT":
        raise SecurityDomainError("DEFAULT cannot be created or repurposed")
    name = _text(name, "domain name", 256, required=True)
    purpose = _text(purpose, "purpose", 1000, required=True)
    reason = _text(reason, "reason", 2000, required=True)
    owner_principal_id = _text(owner_principal_id, "owner", 128, required=True)
    status = str(status or "ACTIVE").upper()
    if status not in VALID_DOMAIN_STATES - {"REVOKED"}:
        raise SecurityDomainError("Security Domain status is invalid")
    classification = _classification(classification)
    _principal_exists(owner_principal_id)

    def work(tx: Any) -> Dict[str, Any]:
        if tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID=:domain_id", {"domain_id": domain_id}):
            raise SecurityDomainConflict("Security Domain already exists")
        tx.execute(
            "INSERT INTO CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID,DOMAIN_NAME,CLASSIFICATION,PURPOSE,STATUS) "
            "VALUES(:domain_id,:name,:classification,:purpose,:status)",
            {"domain_id": domain_id, "name": name, "classification": classification, "purpose": purpose, "status": status},
        )
        tx.execute(
            "INSERT INTO CX_DOMAIN_GOVERNANCE(SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,REASON,UPDATED_BY) "
            "VALUES(:domain_id,:owner,:reason,:actor)",
            {"domain_id": domain_id, "owner": owner_principal_id, "reason": reason, "actor": actor},
        )
        tx.execute(
            "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID,SECURITY_DOMAIN_ID,PRINCIPAL_ID,MEMBERSHIP_TIER,STATUS) "
            "VALUES(:membership_id,:domain_id,:owner,'OWNER','ACTIVE')",
            {"membership_id": _id("DM"), "domain_id": domain_id, "owner": owner_principal_id},
        )
        return {"security_domain_id": domain_id, "domain_name": name, "classification": classification, "purpose": purpose, "status": status, "owner_principal_id": owner_principal_id}

    result = connection.execute_transaction_callback(work)
    _audit(actor, "SECURITY_DOMAIN_CREATE", "SECURITY_DOMAIN", domain_id, "ALLOW", reason)
    return result


def set_domain_status(actor: str, domain_id: str, status: str, reason: str) -> Dict[str, Any]:
    _require(actor)
    domain_id = _text(domain_id, "security domain ID", 128, required=True)
    status = str(status or "").upper()
    reason = _text(reason, "reason", 2000, required=True)
    if domain_id == "DEFAULT":
        raise SecurityDomainError("DEFAULT lifecycle is managed by bootstrap policy")
    if status not in VALID_DOMAIN_STATES:
        raise SecurityDomainError("Security Domain status is invalid")
    if not _domain_row(domain_id):
        raise SecurityDomainError("Security Domain is unavailable")
    connection.execute_transaction_result([
        ("UPDATE CX_SECURITY_DOMAINS SET STATUS=:status WHERE SECURITY_DOMAIN_ID=:domain_id", {"status": status, "domain_id": domain_id}),
        ("UPDATE CX_DOMAIN_GOVERNANCE SET REASON=:reason,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE SECURITY_DOMAIN_ID=:domain_id", {"reason": reason, "actor": actor, "domain_id": domain_id}),
    ])
    if status != "ACTIVE":
        connection.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKE_REASON=:reason,"
            "FENCING_TOKEN=FENCING_TOKEN+1,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE SECURITY_DOMAIN_ID=:domain_id AND STATUS='ACTIVE'",
            {"domain_id": domain_id, "reason": reason[:1000]},
        )
    _audit(actor, "SECURITY_DOMAIN_" + status, "SECURITY_DOMAIN", domain_id, "ALLOW", reason)
    return {"security_domain_id": domain_id, "status": status}


def set_member(actor: str, domain_id: str, principal_id: str, tier: str, reason: str, *, valid_until: Any = None, status: str = "ACTIVE") -> Dict[str, Any]:
    _require(actor)
    domain_id = _text(domain_id, "security domain ID", 128, required=True)
    principal_id = _text(principal_id, "principal", 128, required=True)
    tier = str(tier or "MEMBER").upper()
    status = str(status or "ACTIVE").upper()
    reason = _text(reason, "reason", 2000, required=True)
    if tier not in VALID_TIERS or status not in VALID_MEMBER_STATES:
        raise SecurityDomainError("membership policy is invalid")
    if not _domain_row(domain_id, active_only=status == "ACTIVE"):
        raise SecurityDomainError("Security Domain is unavailable")
    _principal_exists(principal_id)
    expiry = _timestamp(valid_until)

    def work(tx: Any) -> Dict[str, Any]:
        existing = tx.query_one(
            "SELECT MEMBERSHIP_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain_id AND PRINCIPAL_ID=:principal_id",
            {"domain_id": domain_id, "principal_id": principal_id},
        )
        if existing:
            tx.execute(
                "UPDATE CX_DOMAIN_MEMBERS SET MEMBERSHIP_TIER=:tier,VALID_UNTIL=:valid_until,STATUS=:status "
                "WHERE SECURITY_DOMAIN_ID=:domain_id AND PRINCIPAL_ID=:principal_id",
                {"tier": tier, "valid_until": expiry, "status": status, "domain_id": domain_id, "principal_id": principal_id},
            )
            membership_id = str(_row(existing).get("membership_id"))
        else:
            membership_id = _id("DM")
            tx.execute(
                "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID,SECURITY_DOMAIN_ID,PRINCIPAL_ID,MEMBERSHIP_TIER,VALID_UNTIL,STATUS) "
                "VALUES(:membership_id,:domain_id,:principal_id,:tier,:valid_until,:status)",
                {"membership_id": membership_id, "domain_id": domain_id, "principal_id": principal_id, "tier": tier, "valid_until": expiry, "status": status},
            )
        return {"membership_id": membership_id, "security_domain_id": domain_id, "principal_id": principal_id, "membership_tier": tier, "status": status}

    result = connection.execute_transaction_callback(work)
    if status != "ACTIVE":
        connection.execute(
            "UPDATE CX_AGENT_INSTANCES SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKE_REASON=:reason,"
            "FENCING_TOKEN=FENCING_TOKEN+1,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE SECURITY_DOMAIN_ID=:domain_id AND AGENT_ID=:principal_id AND STATUS='ACTIVE'",
            {"domain_id": domain_id, "principal_id": principal_id, "reason": reason[:1000]},
        )
    _audit(actor, "SECURITY_DOMAIN_MEMBER_" + status, "SECURITY_DOMAIN", domain_id, "ALLOW", reason)
    return result


def list_principal_candidates(actor: str, *, limit: int = 300) -> List[Dict[str, Any]]:
    _require(actor)
    rows = connection.execute_query(
        "SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS FROM CX_PRINCIPALS "
        "WHERE STATUS IN ('ACTIVE','PENDING_CONFIRMATION') ORDER BY PRINCIPAL_TYPE,DISPLAY_NAME,PRINCIPAL_ID " + _limit_clause(),
        {"limit": max(1, min(int(limit), 500))},
    )
    return _rows(rows)


def list_bindings(actor: str, domain_id: str = "") -> List[Dict[str, Any]]:
    identity_api._require(actor, DOMAIN_READ_ACTION)
    if domain_id and not _actor_can_use_domain(actor, domain_id):
        raise PermissionError("Security Domain access denied")
    admin = identity_api.effective_access(actor, DOMAIN_ACTION).get("decision") == "ALLOW"
    where = "WHERE b.SECURITY_DOMAIN_ID=:domain_id" if domain_id else ""
    params: Dict[str, Any] = {"domain_id": domain_id} if domain_id else {}
    if not admin and not domain_id:
        where = "JOIN CX_DOMAIN_MEMBERS m ON m.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID WHERE m.PRINCIPAL_ID=:actor AND m.STATUS='ACTIVE' AND (m.VALID_UNTIL IS NULL OR m.VALID_UNTIL>CURRENT_TIMESTAMP)"
        params = {"actor": actor}
    rows = connection.execute_query(
        "SELECT b.BINDING_ID,b.SECURITY_DOMAIN_ID,b.BINDING_TYPE,b.TARGET_ID,b.STATUS,b.REASON,b.APPROVAL_REF,b.CREATED_BY,b.CREATED_AT,b.UPDATED_AT "
        "FROM CX_DOMAIN_BINDINGS b " + where + " ORDER BY b.CREATED_AT DESC,b.BINDING_ID",
        params,
    )
    return _rows(rows)


def create_binding(actor: str, domain_id: str, binding_type: str, target_id: str, reason: str, *, approval_ref: str = "") -> Dict[str, Any]:
    _require(actor)
    domain_id = _text(domain_id, "security domain ID", 128, required=True)
    target_id = _text(target_id, "binding target", 128, required=True)
    binding_type = str(binding_type or "").upper()
    reason = _text(reason, "reason", 2000, required=True)
    if binding_type not in VALID_BINDING_TYPES:
        raise SecurityDomainError("binding type is invalid")
    if not _domain_row(domain_id, active_only=True):
        raise SecurityDomainError("Security Domain is unavailable")
    if binding_type == "CHANNEL":
        target = _row(connection.execute_query_one("SELECT CHANNEL_ID,SECURITY_DOMAIN_ID,STATUS FROM CX_CHANNELS WHERE CHANNEL_ID=:target_id", {"target_id": target_id}))
        if not target or str(target.get("status") or "").upper() != "ACTIVE" or str(target.get("security_domain_id")) != domain_id:
            raise SecurityDomainError("Channel binding target is unavailable")
    else:
        target = _row(connection.execute_query_one("SELECT GROUP_ID,STATUS FROM COLLAB_GROUPS WHERE GROUP_ID=:target_id", {"target_id": target_id}))
        if not target or str(target.get("status") or "").upper() != "ACTIVE":
            raise SecurityDomainError("collaboration group binding target is unavailable")

    def work(tx: Any) -> Dict[str, Any]:
        if binding_type == "LEGACY_COLLAB_GROUP":
            current = tx.query_one(
                "SELECT BINDING_ID,SECURITY_DOMAIN_ID FROM CX_DOMAIN_BINDINGS WHERE BINDING_TYPE='LEGACY_COLLAB_GROUP' "
                "AND TARGET_ID=:target_id AND STATUS='ACTIVE'", {"target_id": target_id},
            )
            if current and str(_row(current).get("security_domain_id")) != domain_id:
                raise SecurityDomainConflict("collaboration group already has an active Security Domain binding")
            if current:
                return {"binding_id": str(_row(current).get("binding_id")), "security_domain_id": domain_id, "binding_type": binding_type, "target_id": target_id, "status": "ACTIVE", "reused": True}
        existing = tx.query_one(
            "SELECT BINDING_ID FROM CX_DOMAIN_BINDINGS WHERE SECURITY_DOMAIN_ID=:domain_id AND BINDING_TYPE=:binding_type "
            "AND TARGET_ID=:target_id AND STATUS='ACTIVE'",
            {"domain_id": domain_id, "binding_type": binding_type, "target_id": target_id},
        )
        if existing:
            return {"binding_id": str(_row(existing).get("binding_id")), "security_domain_id": domain_id, "binding_type": binding_type, "target_id": target_id, "status": "ACTIVE", "reused": True}
        binding_id = _id("DB")
        tx.execute(
            "INSERT INTO CX_DOMAIN_BINDINGS(BINDING_ID,SECURITY_DOMAIN_ID,BINDING_TYPE,TARGET_ID,STATUS,REASON,APPROVAL_REF,CREATED_BY) "
            "VALUES(:binding_id,:domain_id,:binding_type,:target_id,'ACTIVE',:reason,:approval_ref,:actor)",
            {"binding_id": binding_id, "domain_id": domain_id, "binding_type": binding_type, "target_id": target_id, "reason": reason, "approval_ref": approval_ref or None, "actor": actor},
        )
        return {"binding_id": binding_id, "security_domain_id": domain_id, "binding_type": binding_type, "target_id": target_id, "status": "ACTIVE", "reused": False}

    result = connection.execute_transaction_callback(work)
    _audit(actor, "SECURITY_DOMAIN_BIND_" + binding_type, "SECURITY_DOMAIN", domain_id, "ALLOW", reason)
    return result


def list_collaboration_groups(actor: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    _require(actor)
    rows = connection.execute_query(
        "SELECT g.GROUP_ID,g.GROUP_NAME,g.GROUP_TYPE,g.DESCRIPTION,g.COORDINATOR_AGENT_ID,g.SHARING_POLICY,g.STATUS,"
        "(SELECT COUNT(*) FROM COLLAB_GROUP_MEMBERS m WHERE m.GROUP_ID=g.GROUP_ID AND m.STATUS='ACTIVE') AS MEMBER_COUNT,"
        "b.SECURITY_DOMAIN_ID AS BOUND_SECURITY_DOMAIN_ID,b.STATUS AS BINDING_STATUS "
        "FROM COLLAB_GROUPS g JOIN CX_DOMAIN_BINDINGS b ON b.BINDING_TYPE='LEGACY_COLLAB_GROUP' "
        "AND " + _execution_group_binding("g.GROUP_ID") + " AND b.STATUS='ACTIVE' "
        "JOIN COLLAB_GROUP_MEMBERS self_member ON self_member.GROUP_ID=g.GROUP_ID "
        "AND self_member.AGENT_ID=:actor AND self_member.STATUS='ACTIVE' "
        "JOIN CX_DOMAIN_MEMBERS domain_member ON domain_member.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID "
        "AND domain_member.PRINCIPAL_ID=:actor AND domain_member.STATUS='ACTIVE' "
        "AND (domain_member.VALID_UNTIL IS NULL OR domain_member.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "WHERE g.STATUS='ACTIVE' "
        "ORDER BY g.GROUP_NAME,g.GROUP_ID " + _limit_clause(),
        {"actor": actor, "limit": max(1, min(int(limit), 500))},
    )
    result = _rows(rows)
    for item in result:
        item["compatibility"] = {
            "contract": "legacy-collaboration-read/v1",
            "deprecated": True,
            "authorization_source": "SECURITY_DOMAIN",
            "scope": "filtered-current-principal-channel-domain",
        }
    return result


def list_execution_groups(actor: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    """List execution groups inside the caller's current Security Domains.

    Collaboration groups are retained for execution coordination, but this is
    the only supported external read shape. Humans need active Domain
    membership; Agents additionally need active membership in the group.
    """
    _require(actor, "collab.read")
    rows = connection.execute_query(
        "SELECT g.GROUP_ID,g.GROUP_NAME,g.GROUP_TYPE,g.DESCRIPTION,g.WORKSPACE_ID,"
        "g.COORDINATOR_AGENT_ID,g.SHARING_POLICY,g.STATUS,"
        "(SELECT COUNT(*) FROM COLLAB_GROUP_MEMBERS m WHERE m.GROUP_ID=g.GROUP_ID AND m.STATUS='ACTIVE') AS MEMBER_COUNT,"
        "b.SECURITY_DOMAIN_ID AS SECURITY_DOMAIN_ID,b.STATUS AS BINDING_STATUS,"
        "p.PRINCIPAL_TYPE AS ACTOR_TYPE "
        "FROM COLLAB_GROUPS g JOIN CX_DOMAIN_BINDINGS b ON b.BINDING_TYPE='LEGACY_COLLAB_GROUP' "
        "AND " + _execution_group_binding("g.GROUP_ID") + " AND b.STATUS='ACTIVE' "
        "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID "
        "AND dm.PRINCIPAL_ID=:actor AND dm.STATUS='ACTIVE' "
        "AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=:actor "
        "LEFT JOIN COLLAB_GROUP_MEMBERS self_member ON self_member.GROUP_ID=g.GROUP_ID "
        "AND self_member.AGENT_ID=:actor AND self_member.STATUS='ACTIVE' "
        "WHERE g.STATUS='ACTIVE' AND (p.PRINCIPAL_TYPE='HUMAN' OR self_member.AGENT_ID IS NOT NULL) "
        "ORDER BY g.GROUP_NAME,g.GROUP_ID " + _limit_clause(),
        {"actor": actor, "limit": max(1, min(int(limit), 500))},
    )
    result = _rows(rows)
    for item in result:
        item["execution_group"] = True
        item["authorization_source"] = "SECURITY_DOMAIN_AND_GROUP_MEMBERSHIP"
        item["compatibility"] = {
            "contract": "execution-group-scope/v1",
            "deprecated_legacy_group": True,
            "sharing_policy_authoritative": False,
        }
    return result


def assert_execution_group_access(actor: str, group_id: str, *, write: bool = False) -> Dict[str, Any]:
    """Fail closed unless actor has current Domain and execution-group scope."""
    _require(actor, "collab.write" if write else "collab.read")
    group_id = _text(group_id, "execution group", 128, required=True)
    row = _row(connection.execute_query_one(
        "SELECT g.GROUP_ID,g.GROUP_NAME,g.WORKSPACE_ID,g.SPEC_ID,g.STATUS,"
        "b.SECURITY_DOMAIN_ID,p.PRINCIPAL_TYPE "
        "FROM COLLAB_GROUPS g JOIN CX_DOMAIN_BINDINGS b ON b.BINDING_TYPE='LEGACY_COLLAB_GROUP' "
        "AND " + _execution_group_binding("g.GROUP_ID") + " AND b.STATUS='ACTIVE' "
        "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID "
        "AND dm.PRINCIPAL_ID=:actor AND dm.STATUS='ACTIVE' "
        "AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=:actor "
        "LEFT JOIN COLLAB_GROUP_MEMBERS gm ON gm.GROUP_ID=g.GROUP_ID "
        "AND gm.AGENT_ID=:actor AND gm.STATUS='ACTIVE' "
        "WHERE g.GROUP_ID=:group_id AND g.STATUS='ACTIVE' "
        "AND (p.PRINCIPAL_TYPE='HUMAN' OR gm.AGENT_ID IS NOT NULL)",
        {"actor": actor, "group_id": group_id},
    ))
    if not row:
        raise PermissionError("Execution group is outside the current Security Domain or membership scope")
    row["execution_group"] = True
    row["authorization_source"] = "SECURITY_DOMAIN_AND_GROUP_MEMBERSHIP"
    return row


def list_legacy_collaboration_messages(actor: str, group_id: str, *, channel_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    """Read historical messages only through the current governed scope."""
    _require(actor)
    params = {"actor": actor, "group_id": _text(group_id, "group ID", 128, required=True), "limit": max(1, min(int(limit), 500))}
    channel_filter = ""
    if channel_id:
        params["channel_id"] = _text(channel_id, "channel ID", 128, required=True)
        channel_filter = (
            " AND EXISTS (SELECT 1 FROM CX_CHANNELS c JOIN CX_CHANNEL_MEMBERS cm "
            "ON cm.CHANNEL_ID=c.CHANNEL_ID AND cm.PRINCIPAL_ID=:actor AND cm.STATUS='ACTIVE' "
            "WHERE c.CHANNEL_ID=:channel_id AND c.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID AND c.STATUS='ACTIVE')"
        )
    rows = connection.execute_query(
        "SELECT m.MESSAGE_ID,m.GROUP_ID,m.AGENT_ID,m.MESSAGE_TEXT,m.CREATED_AT "
        "FROM COLLAB_MESSAGES m JOIN COLLAB_GROUP_MEMBERS gm ON gm.GROUP_ID=m.GROUP_ID AND gm.AGENT_ID=:actor AND gm.STATUS='ACTIVE' "
        "WHERE m.GROUP_ID=:group_id AND EXISTS (SELECT 1 FROM CX_DOMAIN_BINDINGS b "
        "JOIN CX_DOMAIN_MEMBERS dm ON dm.SECURITY_DOMAIN_ID=b.SECURITY_DOMAIN_ID "
        "AND dm.PRINCIPAL_ID=:actor AND dm.STATUS='ACTIVE' "
        "AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP) "
        "WHERE b.BINDING_TYPE='LEGACY_COLLAB_GROUP' AND " + _execution_group_binding("m.GROUP_ID") + " AND b.STATUS='ACTIVE'"
        + channel_filter + ") ORDER BY m.CREATED_AT DESC " + _limit_clause(), params,
    )
    return [{**_row(row), "compatibility": {"contract": "legacy-collaboration-read/v1", "deprecated": True, "scope": "principal-channel-domain"}} for row in rows]


def create_conversion_draft(actor: str, group_id: str, domain_id: str, domain_name: str, classification: str, purpose: str, owner_principal_id: str, reason: str) -> Dict[str, Any]:
    _require(actor)
    group_id = _text(group_id, "collaboration group", 128, required=True)
    domain_id = _text(domain_id, "security domain ID", 128, required=True).upper()
    domain_name = _text(domain_name, "domain name", 256, required=True)
    purpose = _text(purpose, "purpose", 1000, required=True)
    owner_principal_id = _text(owner_principal_id, "owner", 128, required=True)
    reason = _text(reason, "reason", 2000, required=True)
    classification = _classification(classification)
    if domain_id == "DEFAULT":
        raise SecurityDomainError("DEFAULT cannot be used for a conversion draft")
    _principal_exists(owner_principal_id)
    group = _row(connection.execute_query_one(
        "SELECT GROUP_ID,GROUP_NAME,GROUP_TYPE,DESCRIPTION,COORDINATOR_AGENT_ID,SHARING_POLICY,STATUS "
        "FROM COLLAB_GROUPS WHERE GROUP_ID=:group_id", {"group_id": group_id},
    ))
    if not group or str(group.get("status") or "").upper() != "ACTIVE":
        raise SecurityDomainError("collaboration group is unavailable")
    members = _rows(connection.execute_query(
        "SELECT m.AGENT_ID,m.ROLE,m.STATUS,p.DISPLAY_NAME,p.PRINCIPAL_TYPE FROM COLLAB_GROUP_MEMBERS m "
        "JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=m.AGENT_ID "
        "WHERE m.GROUP_ID=:group_id AND m.STATUS='ACTIVE' AND p.PRINCIPAL_TYPE='AGENT' "
        "AND p.STATUS IN ('ACTIVE','PENDING_CONFIRMATION')",
        {"group_id": group_id},
    ))
    snapshot = {"group": group, "agent_candidates": members, "note": "Candidates require explicit confirmation; sharing policy is non-authoritative."}

    def work(tx: Any) -> Dict[str, Any]:
        active = tx.query_one(
            "SELECT BINDING_ID FROM CX_DOMAIN_BINDINGS WHERE BINDING_TYPE='LEGACY_COLLAB_GROUP' "
            "AND TARGET_ID=:group_id AND STATUS='ACTIVE'", {"group_id": group_id},
        )
        if active:
            raise SecurityDomainConflict("collaboration group already has an active Security Domain binding")
        draft_id = _id("DCD")
        tx.execute(
            "INSERT INTO CX_DOMAIN_CONVERSION_DRAFTS(DRAFT_ID,SOURCE_GROUP_ID,PROPOSED_DOMAIN_ID,DOMAIN_NAME,CLASSIFICATION,PURPOSE,OWNER_PRINCIPAL_ID,"
            "SNAPSHOT_JSON,STATUS,REASON,CREATED_BY) VALUES(:draft_id,:group_id,:domain_id,:domain_name,:classification,:purpose,:owner,:snapshot,'DRAFT',:reason,:actor)",
            {"draft_id": draft_id, "group_id": group_id, "domain_id": domain_id, "domain_name": domain_name, "classification": classification, "purpose": purpose, "owner": owner_principal_id, "snapshot": _json(snapshot), "reason": reason, "actor": actor},
        )
        for member in members:
            principal_id = str(member.get("agent_id") or "")
            if principal_id:
                tx.execute(
                    "INSERT INTO CX_DOMAIN_DRAFT_MEMBERS(DRAFT_MEMBER_ID,DRAFT_ID,PRINCIPAL_ID,PRINCIPAL_TYPE,MEMBERSHIP_TIER,DECISION) "
                    "VALUES(:draft_member_id,:draft_id,:principal_id,'AGENT','MEMBER','PENDING')",
                    {"draft_member_id": _id("DCM"), "draft_id": draft_id, "principal_id": principal_id},
                )
        tx.execute(
            "INSERT INTO CX_DOMAIN_DRAFT_MEMBERS(DRAFT_MEMBER_ID,DRAFT_ID,PRINCIPAL_ID,PRINCIPAL_TYPE,MEMBERSHIP_TIER,DECISION) "
            "VALUES(:draft_member_id,:draft_id,:principal_id,'HUMAN','OWNER','CONFIRMED')",
            {"draft_member_id": _id("DCM"), "draft_id": draft_id, "principal_id": owner_principal_id},
        )
        return {"draft_id": draft_id, "status": "DRAFT", "candidate_count": len(members), "source_group_id": group_id, "proposed_domain_id": domain_id}

    result = connection.execute_transaction_callback(work)
    _audit(actor, "SECURITY_DOMAIN_CONVERSION_DRAFT_CREATE", "COLLAB_GROUP", group_id, "ALLOW", reason)
    return result


def get_conversion_draft(actor: str, draft_id: str) -> Dict[str, Any]:
    _require(actor)
    draft = _row(connection.execute_query_one("SELECT * FROM CX_DOMAIN_CONVERSION_DRAFTS WHERE DRAFT_ID=:draft_id", {"draft_id": draft_id}))
    if not draft:
        raise SecurityDomainError("conversion draft is unavailable")
    members = _rows(connection.execute_query(
        "SELECT d.DRAFT_MEMBER_ID,d.PRINCIPAL_ID,d.PRINCIPAL_TYPE,d.MEMBERSHIP_TIER,d.VALID_UNTIL,d.DECISION,"
        "p.DISPLAY_NAME,p.STATUS AS PRINCIPAL_STATUS FROM CX_DOMAIN_DRAFT_MEMBERS d LEFT JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=d.PRINCIPAL_ID "
        "WHERE d.DRAFT_ID=:draft_id ORDER BY d.PRINCIPAL_TYPE,p.DISPLAY_NAME,d.PRINCIPAL_ID", {"draft_id": draft_id},
    ))
    draft["members"] = members
    return draft


def review_draft_member(actor: str, draft_id: str, principal_id: str, decision: str, tier: str, reason: str, *, valid_until: Any = None) -> Dict[str, Any]:
    _require(actor)
    decision = str(decision or "").upper()
    tier = str(tier or "MEMBER").upper()
    reason = _text(reason, "reason", 2000, required=True)
    if decision not in {"CONFIRMED", "REJECTED"} or tier not in VALID_TIERS:
        raise SecurityDomainError("draft member decision is invalid")
    draft = get_conversion_draft(actor, draft_id)
    if str(draft.get("status") or "").upper() not in {"DRAFT", "REVIEW"}:
        raise SecurityDomainConflict("conversion draft is not editable")
    _principal_exists(principal_id)
    changed = connection.execute(
        "UPDATE CX_DOMAIN_DRAFT_MEMBERS SET DECISION=:decision,MEMBERSHIP_TIER=:tier,VALID_UNTIL=:valid_until,"
        "REVIEWED_BY=:actor,REVIEWED_AT=CURRENT_TIMESTAMP,REVIEW_REASON=:reason WHERE DRAFT_ID=:draft_id AND PRINCIPAL_ID=:principal_id",
        {"decision": decision, "tier": tier, "valid_until": _timestamp(valid_until), "actor": actor, "reason": reason, "draft_id": draft_id, "principal_id": principal_id},
    )
    if not changed:
        raise SecurityDomainError("draft member is unavailable")
    connection.execute("UPDATE CX_DOMAIN_CONVERSION_DRAFTS SET STATUS='REVIEW',UPDATED_AT=CURRENT_TIMESTAMP WHERE DRAFT_ID=:draft_id", {"draft_id": draft_id})
    _audit(actor, "SECURITY_DOMAIN_DRAFT_MEMBER_" + decision, "SECURITY_DOMAIN_CONVERSION_DRAFT", draft_id, "ALLOW", reason)
    return {"draft_id": draft_id, "principal_id": principal_id, "decision": decision, "membership_tier": tier}


def apply_conversion_draft(actor: str, draft_id: str, reason: str, *, approval_ref: str = "") -> Dict[str, Any]:
    _require(actor)
    reason = _text(reason, "reason", 2000, required=True)

    def work(tx: Any) -> Dict[str, Any]:
        draft = _row(tx.query_one("SELECT * FROM CX_DOMAIN_CONVERSION_DRAFTS WHERE DRAFT_ID=:draft_id", {"draft_id": draft_id}))
        if not draft:
            raise SecurityDomainError("conversion draft is unavailable")
        if str(draft.get("status") or "").upper() not in {"DRAFT", "REVIEW", "APPROVED"}:
            raise SecurityDomainConflict("conversion draft is not applicable")
        group_id = str(draft.get("source_group_id"))
        existing_binding = tx.query_one("SELECT BINDING_ID FROM CX_DOMAIN_BINDINGS WHERE BINDING_TYPE='LEGACY_COLLAB_GROUP' AND TARGET_ID=:group_id AND STATUS='ACTIVE'", {"group_id": group_id})
        if existing_binding:
            raise SecurityDomainConflict("collaboration group already has an active Security Domain binding")
        domain_id = str(draft.get("proposed_domain_id"))
        existing_domain = tx.query_one("SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID=:domain_id", {"domain_id": domain_id})
        if existing_domain:
            raise SecurityDomainConflict("proposed Security Domain already exists")
        confirmed = _rows(tx.query(
            "SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,MEMBERSHIP_TIER,VALID_UNTIL FROM CX_DOMAIN_DRAFT_MEMBERS "
            "WHERE DRAFT_ID=:draft_id AND DECISION='CONFIRMED'", {"draft_id": draft_id},
        ))
        if not any(str(item.get("principal_id")) == str(draft.get("owner_principal_id")) and str(item.get("membership_tier")).upper() == "OWNER" for item in confirmed):
            raise SecurityDomainError("conversion draft requires confirmed accountable owner")
        for item in confirmed:
            _principal_exists(str(item.get("principal_id") or ""))
        tx.execute(
            "INSERT INTO CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID,DOMAIN_NAME,CLASSIFICATION,PURPOSE,STATUS) "
            "VALUES(:domain_id,:name,:classification,:purpose,'ACTIVE')",
            {"domain_id": domain_id, "name": draft.get("domain_name"), "classification": draft.get("classification"), "purpose": draft.get("purpose")},
        )
        tx.execute(
            "INSERT INTO CX_DOMAIN_GOVERNANCE(SECURITY_DOMAIN_ID,OWNER_PRINCIPAL_ID,REASON,UPDATED_BY) VALUES(:domain_id,:owner,:reason,:actor)",
            {"domain_id": domain_id, "owner": draft.get("owner_principal_id"), "reason": reason, "actor": actor},
        )
        for item in confirmed:
            tx.execute(
                "INSERT INTO CX_DOMAIN_MEMBERS(MEMBERSHIP_ID,SECURITY_DOMAIN_ID,PRINCIPAL_ID,MEMBERSHIP_TIER,VALID_UNTIL,STATUS) "
                "VALUES(:membership_id,:domain_id,:principal_id,:tier,:valid_until,'ACTIVE')",
                {"membership_id": _id("DM"), "domain_id": domain_id, "principal_id": item.get("principal_id"), "tier": item.get("membership_tier"), "valid_until": item.get("valid_until")},
            )
        binding_id = _id("DB")
        tx.execute(
            "INSERT INTO CX_DOMAIN_BINDINGS(BINDING_ID,SECURITY_DOMAIN_ID,BINDING_TYPE,TARGET_ID,STATUS,REASON,APPROVAL_REF,CREATED_BY) "
            "VALUES(:binding_id,:domain_id,'LEGACY_COLLAB_GROUP',:group_id,'ACTIVE',:reason,:approval_ref,:actor)",
            {"binding_id": binding_id, "domain_id": domain_id, "group_id": group_id, "reason": reason, "approval_ref": approval_ref or None, "actor": actor},
        )
        tx.execute(
            "UPDATE CX_DOMAIN_CONVERSION_DRAFTS SET STATUS='APPLIED',APPROVAL_REF=:approval_ref,APPLIED_BY=:actor,APPLIED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE DRAFT_ID=:draft_id",
            {"approval_ref": approval_ref or None, "actor": actor, "draft_id": draft_id},
        )
        return {"draft_id": draft_id, "security_domain_id": domain_id, "binding_id": binding_id, "source_group_id": group_id, "confirmed_members": len(confirmed), "status": "APPLIED"}

    try:
        result = connection.execute_transaction_callback(work)
    except Exception:
        try:
            connection.execute("UPDATE CX_DOMAIN_CONVERSION_DRAFTS SET STATUS='FAILED',UPDATED_AT=CURRENT_TIMESTAMP WHERE DRAFT_ID=:draft_id AND STATUS IN ('DRAFT','REVIEW','APPROVED')", {"draft_id": draft_id})
        except Exception:
            pass
        raise
    _audit(actor, "SECURITY_DOMAIN_CONVERSION_APPLY", "SECURITY_DOMAIN_CONVERSION_DRAFT", draft_id, "ALLOW", reason)
    return result
