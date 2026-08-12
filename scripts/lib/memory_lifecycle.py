"""Database-authoritative v4.3.2 Memory lifecycle service.

The module deliberately keeps authorization outside of memory text and model
output.  Callers must authorize a Principal before resolving a family; this
service then maintains immutable content versions, bounded chains and durable
organization work using the selected adapter transaction facade.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

from . import connection, identity_api, cursor_pagination
from .connection import execute, execute_query, execute_query_one, execute_transaction_callback

MEMORY_TYPES = frozenset({"EPISODIC", "FACT", "PREFERENCE", "DECISION", "PROCEDURAL", "EXPERIENCE"})
MEMORY_SCOPES = frozenset({"RUNTIME_CONTEXT", "CHANNEL_MEMORY", "AGENT_MEMORY", "WORKSPACE_MEMORY", "ENTERPRISE_KNOWLEDGE"})
LIFECYCLE_STATES = frozenset({"CANDIDATE", "ACTIVE", "STALE", "CONFLICTED", "SUPERSEDED", "EXPIRED", "MIGRATED", "ARCHIVED", "QUARANTINED", "UNAVAILABLE"})
REPRESENTATION_TYPES = frozenset({"SOURCE", "ATOMIC_FACT", "SHORT_SUMMARY", "STANDARD_SUMMARY", "TOPIC_SUMMARY", "CHAIN_SUMMARY"})
ORDINARY_VISIBLE_STATES = ("ACTIVE", "STALE", "CONFLICTED", "MIGRATED")
HIGH_IMPACT_CANDIDATES = frozenset({"REPLACE", "MERGE", "SCOPE_CHANGE", "CONFLICT", "PROMOTE"})
RELATION_TYPES = frozenset({
    "DERIVED_FROM", "SUMMARIZES", "SUPERSEDES", "MIGRATED_FROM", "OBSERVED_IN",
    "USED_BY", "RESULTED_IN", "SIMILAR_TO", "OVERLAPS", "RELATED_TO", "CONTRADICTS",
    "CAUSES", "PROMOTED_TO", "SCOPED_TO", "TEMPORAL_NEXT",
})
JOB_TYPES = frozenset({"CONSOLIDATE", "ARCHIVE_REVIEW", "REPRESENT", "DISCOVER_RELATIONS"})
USAGE_EVENT_TYPES = frozenset({"RETRIEVED", "SELECTED", "CONTEXT_INCLUDED", "CITED", "TASK_OUTCOME", "HUMAN_FEEDBACK", "AGENT_FEEDBACK"})
CLASSIFICATION_LEVELS = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}
SAFE_REPRESENTATION_ORDER = {
    "RUNTIME_CONTEXT": ("SHORT_SUMMARY", "ATOMIC_FACT", "STANDARD_SUMMARY", "TOPIC_SUMMARY", "SOURCE"),
    "REVIEW": ("SOURCE", "STANDARD_SUMMARY", "SHORT_SUMMARY", "ATOMIC_FACT", "TOPIC_SUMMARY"),
    "AUDIT": ("SOURCE", "STANDARD_SUMMARY", "SHORT_SUMMARY", "ATOMIC_FACT", "TOPIC_SUMMARY"),
}


class MemoryLifecycleError(ValueError):
    """Stable lifecycle contract error with a machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VersionRequest:
    title: str
    body: str
    memory_type: str = "EPISODIC"
    memory_scope: str = "AGENT_MEMORY"
    classification: str = "INTERNAL"
    owner_principal_id: Optional[str] = None
    owner_agent_id: Optional[str] = None
    workspace_id: Optional[str] = None
    security_domain_id: Optional[str] = None
    source_ref: Optional[str] = None
    source_digest: Optional[str] = None
    valid_until: Optional[str] = None
    policy_version: str = "v4.3.2"
    reason: str = ""


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(*values: Any) -> str:
    return hashlib.sha256("\x1f".join("" if value is None else str(value) for value in values).encode("utf-8")).hexdigest()


def _database_boolean(value: bool) -> bool | str:
    """Return the physical boolean representation required by the adapter."""
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"}:
        return bool(value)
    return "Y" if value else "N"


def _normal(value: str, allowed: frozenset[str], field: str) -> str:
    normalized = str(value or "").upper()
    if normalized not in allowed:
        raise MemoryLifecycleError("INVALID_ARGUMENT", f"unsupported {field}: {value}")
    return normalized


def _request(value: Mapping[str, Any] | VersionRequest) -> VersionRequest:
    if isinstance(value, VersionRequest):
        request = value
    else:
        request = VersionRequest(
            title=str(value.get("title") or "Untitled memory")[:500],
            body=str(value.get("body") if value.get("body") is not None else value.get("content") or ""),
            memory_type=str(value.get("memory_type") or "EPISODIC"),
            memory_scope=str(value.get("memory_scope") or "AGENT_MEMORY"),
            classification=str(value.get("classification") or "INTERNAL").upper(),
            owner_principal_id=value.get("owner_principal_id"), owner_agent_id=value.get("owner_agent_id") or value.get("owned_by_agent"),
            workspace_id=value.get("workspace_id"), security_domain_id=value.get("security_domain_id"),
            source_ref=value.get("source_ref"), source_digest=value.get("source_digest"), valid_until=value.get("valid_until"),
            policy_version=str(value.get("policy_version") or "v4.3.2"), reason=str(value.get("reason") or ""),
        )
    if not request.title.strip():
        raise MemoryLifecycleError("INVALID_ARGUMENT", "memory title is required")
    _normal(request.memory_type, MEMORY_TYPES, "memory_type")
    _normal(request.memory_scope, MEMORY_SCOPES, "memory_scope")
    if request.classification not in CLASSIFICATION_LEVELS:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "unsupported memory classification")
    return request


def _safe_error() -> MemoryLifecycleError:
    """Never disclose whether a protected memory exists to an unauthorized caller."""
    return MemoryLifecycleError("ACCESS_DENIED", "memory is unavailable")


def _parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value or ""))
        return parsed
    except (TypeError, ValueError):
        return default


def inspect_ingestion(body: str) -> dict[str, Any]:
    """Classify stored input as untrusted data before it can enter retrieval.

    The check is deliberately deterministic and conservative.  It records
    evidence for review but never executes, follows, or treats text as an
    instruction.  A policy-controlled LLM may later add a candidate, never a
    direct state transition.
    """
    text = str(body or "")
    lowered = text.lower()
    signals: list[str] = []
    checks = {
        "PROMPT_INJECTION": ("ignore previous", "system prompt", "developer message", "jailbreak"),
        "CREDENTIAL": ("api_key", "api key", "password=", "secret=", "authorization: bearer"),
        "EXFILTRATION": ("upload all", "send all", "exfiltrate", "paste the database"),
        "TOOL_INDUCEMENT": ("call tool", "run command", "execute sql", "curl http"),
    }
    for signal, patterns in checks.items():
        if any(pattern in lowered for pattern in patterns):
            signals.append(signal)
    if re.search(r"https?://[^\s<>]+", text, re.I):
        signals.append("LINK")
    return {"digest": _digest(text), "signals": sorted(set(signals)), "quarantine_recommended": bool(set(signals) - {"LINK"})}


def _require_memory_access(principal_id: str, version: Mapping[str, Any], *, purpose: str,
                           agent_instance_id: Optional[str] = None,
                           agent_fencing_token: Optional[int] = None) -> None:
    """Enforce live authorization for a concrete Version before revealing it."""
    if not principal_id:
        raise _safe_error()
    access = identity_api.effective_access(principal_id, "memory.read")
    if access.get("decision") != "ALLOW":
        raise _safe_error()
    if str(version.get("lifecycle_state") or "").upper() not in ORDINARY_VISIBLE_STATES:
        raise _safe_error()
    classification = str(version.get("classification") or "INTERNAL").upper()
    # A domain is a positive grant.  An absent domain does not widen access;
    # owner/admin access remains subject to the scope gate below.
    domain_id = version.get("security_domain_id")
    if domain_id and "ALL" not in set(access.get("scopes") or []):
        member = execute_query_one(
            "SELECT 1 AS ALLOWED FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain_id "
            "AND PRINCIPAL_ID=:principal_id AND STATUS='ACTIVE' "
            "AND (VALID_UNTIL IS NULL OR VALID_UNTIL > CURRENT_TIMESTAMP)",
            {"domain_id": domain_id, "principal_id": principal_id},
        )
        if not member:
            raise _safe_error()
    scopes = {str(value).upper() for value in access.get("scopes") or []}
    owner = str(version.get("owner_principal_id") or "")
    if "ALL" not in scopes and owner and owner != principal_id and "ASSIGNED" not in scopes and "ORG_SUBTREE" not in scopes:
        raise _safe_error()
    if agent_instance_id:
        instance = execute_query_one(
            "SELECT STATUS,FENCING_TOKEN,REVOKED_AT,LEASE_EXPIRES_AT FROM CX_AGENT_INSTANCES "
            "WHERE INSTANCE_ID=:instance_id", {"instance_id": agent_instance_id},
        )
        if (not instance or str(instance.get("status") or "").upper() != "ACTIVE"
                or instance.get("revoked_at") is not None
                or int(instance.get("fencing_token") or -1) != int(agent_fencing_token or -1)):
            raise _safe_error()


def _authorized_version(principal_id: str, version_id: str, *, purpose: str,
                        agent_instance_id: Optional[str] = None,
                        agent_fencing_token: Optional[int] = None) -> dict[str, Any]:
    row = execute_query_one("SELECT * FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:version_id", {"version_id": version_id})
    if not row:
        raise _safe_error()
    _require_memory_access(principal_id, row, purpose=purpose, agent_instance_id=agent_instance_id,
                           agent_fencing_token=agent_fencing_token)
    return dict(row)


def _version_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["entity_id"] = result.get("legacy_entity_id") or result.get("family_id")
    result["memory_id"] = result["entity_id"]
    result["content"] = result.get("body_text")
    result["summary"] = result.get("title")
    result["status"] = result.get("lifecycle_state")
    result["category"] = result.get("memory_type")
    return result


def current_memories(*, keyword: Optional[str] = None, memory_type: Optional[str] = None,
                     memory_scope: Optional[str] = None, lifecycle_state: Optional[str] = None,
                     workspace_id: Optional[str] = None, owner_agent_id: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Return only current, ordinary-retrievable versions in legacy-compatible shape."""
    conditions = ["f.CURRENT_VERSION_ID = v.VERSION_ID"]
    params: dict[str, Any] = {"lim": max(1, min(int(limit), 500)), "off": max(0, int(offset))}
    if lifecycle_state:
        conditions.append("v.LIFECYCLE_STATE = :state")
        params["state"] = _normal(lifecycle_state, LIFECYCLE_STATES, "lifecycle_state")
    else:
        conditions.append("v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED')")
        conditions.append("(v.VALID_UNTIL IS NULL OR v.VALID_UNTIL > CURRENT_TIMESTAMP)")
    if keyword:
        conditions.append("(UPPER(v.TITLE) LIKE UPPER(:keyword) OR UPPER(v.BODY_TEXT) LIKE UPPER(:keyword))")
        params["keyword"] = f"%{keyword}%"
    if memory_type:
        conditions.append("v.MEMORY_TYPE = :memory_type")
        params["memory_type"] = _normal(memory_type, MEMORY_TYPES, "memory_type")
    if memory_scope:
        conditions.append("v.MEMORY_SCOPE = :memory_scope")
        params["memory_scope"] = _normal(memory_scope, MEMORY_SCOPES, "memory_scope")
    if workspace_id:
        conditions.append("v.WORKSPACE_ID = :workspace_id")
        params["workspace_id"] = workspace_id
    if owner_agent_id:
        conditions.append("v.OWNER_AGENT_ID = :owner_agent_id")
        params["owner_agent_id"] = owner_agent_id
    rows = execute_query(
        f"""SELECT f.FAMILY_ID, f.LEGACY_ENTITY_ID, f.CURRENT_VERSION_ID, f.FAMILY_STATE,
                   v.VERSION_ID, v.VERSION_NUMBER, v.TITLE, v.BODY_TEXT, v.CONTENT_DIGEST,
                   v.MEMORY_TYPE, v.MEMORY_SCOPE, v.LIFECYCLE_STATE, v.CLASSIFICATION,
                   v.OWNER_PRINCIPAL_ID, v.OWNER_AGENT_ID, v.WORKSPACE_ID, v.SECURITY_DOMAIN_ID,
                   v.VALID_FROM, v.VALID_UNTIL, v.POLICY_VERSION, v.CREATED_BY, v.REASON, v.CREATED_AT
              FROM CX_MEMORY_FAMILIES f JOIN CX_MEMORY_VERSIONS v ON v.VERSION_ID = f.CURRENT_VERSION_ID
             WHERE {' AND '.join(conditions)}
             ORDER BY v.CREATED_AT DESC OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY""", params,
    )
    return [_version_row(row) for row in rows]


def current_memories_cursor(
    principal_id: str, *, page_size: int = 20, cursor: str = "", keyword: Optional[str] = None,
    memory_type: Optional[str] = None, memory_scope: Optional[str] = None,
    lifecycle_state: Optional[str] = None, workspace_id: Optional[str] = None,
    owner_agent_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return current Memory families as a bounded, opaque cursor page."""
    filters = {"keyword": keyword or "", "memory_type": memory_type or "",
               "memory_scope": memory_scope or "", "lifecycle_state": lifecycle_state or "",
               "workspace_id": workspace_id or "", "owner_agent_id": owner_agent_id or ""}
    context = cursor_pagination.resolve(principal_id, "memory", filters, "family_id:asc", page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "memory", "sort_key": "family_id:asc"})
    conditions = ["f.CURRENT_VERSION_ID = v.VERSION_ID"]
    params: dict[str, Any] = {"lim": int(context["page_size"]) + 1}
    if lifecycle_state:
        conditions.append("v.LIFECYCLE_STATE = :state")
        params["state"] = _normal(lifecycle_state, LIFECYCLE_STATES, "lifecycle_state")
    else:
        conditions.append("v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED')")
        conditions.append("(v.VALID_UNTIL IS NULL OR v.VALID_UNTIL > CURRENT_TIMESTAMP)")
    if keyword:
        conditions.append("(UPPER(v.TITLE) LIKE UPPER(:keyword) OR UPPER(v.BODY_TEXT) LIKE UPPER(:keyword))")
        params["keyword"] = f"%{keyword}%"
    if memory_type:
        conditions.append("v.MEMORY_TYPE = :memory_type")
        params["memory_type"] = _normal(memory_type, MEMORY_TYPES, "memory_type")
    if memory_scope:
        conditions.append("v.MEMORY_SCOPE = :memory_scope")
        params["memory_scope"] = _normal(memory_scope, MEMORY_SCOPES, "memory_scope")
    if workspace_id:
        conditions.append("v.WORKSPACE_ID = :workspace_id")
        params["workspace_id"] = workspace_id
    if owner_agent_id:
        conditions.append("v.OWNER_AGENT_ID = :owner_agent_id")
        params["owner_agent_id"] = owner_agent_id
    if identity_api.effective_access(principal_id, "agents.read.all").get("decision") != "ALLOW":
        conditions.append(
            "(v.OWNER_PRINCIPAL_ID=:principal_id OR EXISTS (SELECT 1 FROM CX_PRINCIPALS p "
            "WHERE p.PRINCIPAL_ID=v.OWNER_AGENT_ID AND p.PRINCIPAL_TYPE='AGENT' AND " +
            identity_api._agent_visibility_clause(principal_id) + "))"
        )
        params["principal_id"] = principal_id
    after = str(context["position"].get("family_id") or "")
    if after:
        conditions.append("f.FAMILY_ID > :after")
        params["after"] = after
    rows = execute_query(
        "SELECT f.FAMILY_ID,f.LEGACY_ENTITY_ID,f.CURRENT_VERSION_ID,f.FAMILY_STATE,v.VERSION_ID,v.VERSION_NUMBER,"
        "v.TITLE,v.BODY_TEXT,v.CONTENT_DIGEST,v.MEMORY_TYPE,v.MEMORY_SCOPE,v.LIFECYCLE_STATE,v.CLASSIFICATION,"
        "v.OWNER_PRINCIPAL_ID,v.OWNER_AGENT_ID,v.WORKSPACE_ID,v.SECURITY_DOMAIN_ID,v.VALID_FROM,v.VALID_UNTIL,"
        "v.POLICY_VERSION,v.CREATED_BY,v.REASON,v.CREATED_AT FROM CX_MEMORY_FAMILIES f "
        "JOIN CX_MEMORY_VERSIONS v ON v.VERSION_ID=f.CURRENT_VERSION_ID WHERE " + " AND ".join(conditions) +
        " ORDER BY f.FAMILY_ID FETCH FIRST :lim ROWS ONLY", params,
    )
    values = [_version_row(row) for row in rows]
    return cursor_pagination.page(values, context, lambda item: {"family_id": str(item["family_id"])})


def get_family(family_id: str, *, include_history: bool = False) -> Optional[dict[str, Any]]:
    family = execute_query_one("SELECT * FROM CX_MEMORY_FAMILIES WHERE FAMILY_ID = :family_id", {"family_id": family_id})
    if not family:
        return None
    current = execute_query_one("SELECT * FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id", {"version_id": family["current_version_id"]}) if family.get("current_version_id") else None
    result = {"family": dict(family), "current": _version_row(current) if current else None}
    if include_history:
        result["history"] = [_version_row(row) for row in execute_query(
            "SELECT * FROM CX_MEMORY_VERSIONS WHERE FAMILY_ID = :family_id ORDER BY VERSION_NUMBER DESC FETCH FIRST :lim ROWS ONLY",
            {"family_id": family_id, "lim": 100},
        )]
    return result


def adopt_legacy_memory(entity_id: str, *, actor: Optional[str] = None) -> Optional[str]:
    """Return the stable family for a legacy entity without changing its ID or body."""
    existing = execute_query_one("SELECT FAMILY_ID FROM CX_MEMORY_FAMILIES WHERE LEGACY_ENTITY_ID = :entity_id", {"entity_id": str(entity_id)})
    if existing:
        return str(existing["family_id"])
    entity = execute_query_one(
        "SELECT ENTITY_ID, TITLE, CONTENT, CATEGORY, STATUS, OWNED_BY_AGENT, SOURCE_AGENT, WORKSPACE_ID, VISIBILITY FROM ENTITIES WHERE ENTITY_ID = :entity_id AND ENTITY_TYPE = 'MEMORY'",
        {"entity_id": str(entity_id)},
    )
    if not entity:
        return None
    family_id, version_id = f"MF-{entity_id}", f"MV-{entity_id}-1"
    request = _request({"title": entity.get("title"), "content": entity.get("content"), "memory_type": entity.get("category") if str(entity.get("category")).upper() in MEMORY_TYPES else "EPISODIC", "memory_scope": "WORKSPACE_MEMORY" if entity.get("workspace_id") else "AGENT_MEMORY", "owner_agent_id": entity.get("owned_by_agent"), "workspace_id": entity.get("workspace_id"), "reason": "legacy adoption"})
    digest = _digest(request.body, entity.get("summary"), entity.get("updated_at"))
    def commit(tx: Any) -> str:
        if tx.query_one("SELECT FAMILY_ID FROM CX_MEMORY_FAMILIES WHERE LEGACY_ENTITY_ID = :entity_id", {"entity_id": str(entity_id)}):
            return family_id
        tx.execute("INSERT INTO CX_MEMORY_FAMILIES (FAMILY_ID, LEGACY_ENTITY_ID, CURRENT_VERSION_ID, FAMILY_STATE, OWNER_PRINCIPAL_ID, WORKSPACE_ID, CLASSIFICATION) VALUES (:family_id,:entity_id,:version_id,'ACTIVE',:actor,:workspace_id,:classification)", {"family_id": family_id, "entity_id": str(entity_id), "version_id": version_id, "actor": actor, "workspace_id": request.workspace_id, "classification": request.classification})
        tx.execute("INSERT INTO CX_MEMORY_VERSIONS (VERSION_ID,FAMILY_ID,VERSION_NUMBER,LEGACY_ENTITY_ID,TITLE,BODY_TEXT,CONTENT_DIGEST,MEMORY_TYPE,MEMORY_SCOPE,LIFECYCLE_STATE,CLASSIFICATION,OWNER_AGENT_ID,WORKSPACE_ID,CREATED_BY,REASON) VALUES (:version_id,:family_id,1,:entity_id,:title,:body,:digest,:memory_type,:memory_scope,:state,:classification,:owner_agent_id,:workspace_id,:actor,:reason)", {"version_id": version_id, "family_id": family_id, "entity_id": str(entity_id), "title": request.title, "body": request.body, "digest": digest, "memory_type": request.memory_type.upper(), "memory_scope": request.memory_scope.upper(), "state": "ACTIVE" if str(entity.get("status")).upper() == "ACTIVE" else "STALE", "classification": request.classification, "owner_agent_id": request.owner_agent_id, "workspace_id": request.workspace_id, "actor": actor, "reason": request.reason})
        _insert_source_representation(tx, version_id, request.body, digest)
        _outbox(tx, "FAMILY", family_id, "ADOPTED", {"family_id": family_id, "version_id": version_id})
        return family_id
    return execute_transaction_callback(commit)


def create_family(request_value: Mapping[str, Any] | VersionRequest, *, actor: str, idempotency_key: Optional[str] = None) -> dict[str, Any]:
    request = _request(request_value)
    inspection = inspect_ingestion(request.body)
    if inspection["quarantine_recommended"]:
        # Persist immutable evidence, but fail closed from ordinary retrieval.
        request = VersionRequest(**{**request.__dict__, "reason": (request.reason + " | ingestion signals: " + ",".join(inspection["signals"]))[:1800]})
    family_id, version_id = _id("MF"), _id("MV")
    digest = _digest(request.title, request.body, request.memory_type, request.memory_scope, request.classification)
    def commit(tx: Any) -> dict[str, Any]:
        tx.execute("INSERT INTO CX_MEMORY_FAMILIES (FAMILY_ID,CURRENT_VERSION_ID,FAMILY_STATE,OWNER_PRINCIPAL_ID,WORKSPACE_ID,SECURITY_DOMAIN_ID,CLASSIFICATION) VALUES (:family_id,:version_id,'ACTIVE',:actor,:workspace_id,:security_domain_id,:classification)", {"family_id": family_id, "version_id": version_id, "actor": request.owner_principal_id or actor, "workspace_id": request.workspace_id, "security_domain_id": request.security_domain_id, "classification": request.classification})
        _insert_version(tx, version_id, family_id, 1, request, digest, actor,
                        lifecycle_state="QUARANTINED" if inspection["quarantine_recommended"] else "ACTIVE")
        _insert_source_representation(tx, version_id, request.body, digest)
        for signal in inspection["signals"]:
            tx.execute("INSERT INTO CX_MEMORY_INGESTION_FINDINGS (FINDING_ID,VERSION_ID,FINDING_TYPE,SEVERITY,CONTENT_DIGEST,EVIDENCE_JSON,STATUS) VALUES (:finding_id,:version_id,:finding_type,:severity,:content_digest,:evidence,'OPEN')", {"finding_id": _id("MIF"), "version_id": version_id, "finding_type": signal, "severity": "HIGH" if signal != "LINK" else "LOW", "content_digest": inspection["digest"], "evidence": _json({"detector": "deterministic-v1"})})
        _outbox(tx, "FAMILY", family_id, "CURRENT_VERSION_CHANGED", {"family_id": family_id, "version_id": version_id, "idempotency_key": idempotency_key, "ingestion": inspection})
        return {"family_id": family_id, "version_id": version_id, "version_number": 1,
                "lifecycle_state": "QUARANTINED" if inspection["quarantine_recommended"] else "ACTIVE",
                "ingestion_signals": inspection["signals"]}
    return execute_transaction_callback(commit)


def create_successor(family_id: str, expected_version_id: str, request_value: Mapping[str, Any] | VersionRequest, *, actor: str, idempotency_key: Optional[str] = None, lifecycle_state: str = "ACTIVE") -> dict[str, Any]:
    request = _request(request_value)
    next_state = _normal(lifecycle_state, LIFECYCLE_STATES, "lifecycle_state")
    version_id = _id("MV")
    digest = _digest(request.title, request.body, request.memory_type, request.memory_scope, request.classification)
    def commit(tx: Any) -> dict[str, Any]:
        family = tx.query_one("SELECT FAMILY_ID,CURRENT_VERSION_ID FROM CX_MEMORY_FAMILIES WHERE FAMILY_ID = :family_id", {"family_id": family_id})
        if not family:
            raise MemoryLifecycleError("NOT_FOUND", "memory family is unavailable")
        if str(family.get("current_version_id")) != str(expected_version_id):
            raise MemoryLifecycleError("VERSION_CONFLICT", "current memory version changed; refresh before retrying")
        number = int((tx.query_one("SELECT COALESCE(MAX(VERSION_NUMBER),0) AS VERSION_NUMBER FROM CX_MEMORY_VERSIONS WHERE FAMILY_ID = :family_id", {"family_id": family_id}) or {}).get("version_number") or 0) + 1
        _insert_version(tx, version_id, family_id, number, request, digest, actor, lifecycle_state=next_state)
        _insert_source_representation(tx, version_id, request.body, digest)
        changed = tx.execute("UPDATE CX_MEMORY_FAMILIES SET CURRENT_VERSION_ID = :next_version, FAMILY_STATE = :family_state, ROW_VERSION = ROW_VERSION + 1, UPDATED_AT = CURRENT_TIMESTAMP WHERE FAMILY_ID = :family_id AND CURRENT_VERSION_ID = :expected_version", {"next_version": version_id, "family_state": next_state, "family_id": family_id, "expected_version": expected_version_id})
        if not changed:
            raise MemoryLifecycleError("VERSION_CONFLICT", "current memory version changed; no mutation was applied")
        tx.execute("UPDATE CX_MEMORY_VERSIONS SET LIFECYCLE_STATE = 'SUPERSEDED' WHERE VERSION_ID = :expected_version AND LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED')", {"expected_version": expected_version_id})
        _relation(tx, expected_version_id, version_id, "SUPERSEDES", deterministic=True, actor=actor)
        _outbox(tx, "FAMILY", family_id, "CURRENT_VERSION_CHANGED", {"family_id": family_id, "previous_version_id": expected_version_id, "version_id": version_id, "lifecycle_state": next_state, "idempotency_key": idempotency_key})
        return {"family_id": family_id, "version_id": version_id, "version_number": number, "lifecycle_state": next_state}
    return execute_transaction_callback(commit)


def mark_unavailable(family_id: str, *, actor: str, reason: str, expected_version_id: Optional[str] = None) -> dict[str, Any]:
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "logical unavailability requires a reason")
    detail = get_family(family_id)
    if not detail or not detail.get("current"):
        raise MemoryLifecycleError("NOT_FOUND", "memory family is unavailable")
    current = detail["current"]
    expected = expected_version_id or str(current["version_id"])
    request = _request({**current, "body": current.get("body_text") or current.get("content") or "", "reason": reason})
    result = create_successor(family_id, expected, request, actor=actor, lifecycle_state="UNAVAILABLE")
    return {**result, "reason": reason}


def quarantine_family(family_id: str, *, actor: str, reason: str, expected_version_id: Optional[str] = None) -> dict[str, Any]:
    """Fail closed for suspected poisoned or security-restricted memory.

    This is a logical transition: source and audit lineage remain intact, while
    current reads and graph projection rebuilds exclude the quarantined Version.
    """
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "memory quarantine requires a reason")
    detail = get_family(family_id)
    if not detail or not detail.get("current"):
        raise MemoryLifecycleError("NOT_FOUND", "memory family is unavailable")
    current = detail["current"]
    expected = expected_version_id or str(current["version_id"])
    request = _request({**current, "body": current.get("body_text") or current.get("content") or "", "reason": reason})
    result = create_successor(family_id, expected, request, actor=actor, lifecycle_state="QUARANTINED")
    return {**result, "reason": reason}


def create_representation(version_id: str, representation_type: str, body: str, *, generator_version: str = "deterministic-v1", source_version_ids: Optional[Iterable[str]] = None) -> str:
    kind = _normal(representation_type, REPRESENTATION_TYPES, "representation_type")
    representation_id, digest = _id("MR"), _digest(version_id, kind, body)
    execute("INSERT INTO CX_MEMORY_REPRESENTATIONS (REPRESENTATION_ID,VERSION_ID,REPRESENTATION_TYPE,BODY_TEXT,CONTENT_DIGEST,TOKEN_COUNT,GENERATION_METHOD,GENERATOR_VERSION,SOURCE_VERSION_IDS_JSON) VALUES (:representation_id,:version_id,:representation_type,:body,:digest,:token_count,'DETERMINISTIC',:generator_version,:source_versions)", {"representation_id": representation_id, "version_id": version_id, "representation_type": kind, "body": body, "digest": digest, "token_count": max(0, len(body) // 4), "generator_version": generator_version, "source_versions": _json(list(source_version_ids or []))})
    return representation_id


def register_content_artifact(*, content: str | bytes, owner_ref: str, classification: str = "INTERNAL",
                              media_type: str = "text/plain", storage_uri: Optional[str] = None,
                              retention_until: Optional[str] = None) -> dict[str, Any]:
    """Register content once in the governed Artifact store and return its digest reference."""
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    digest = hashlib.sha256(raw).hexdigest()
    existing = execute_query_one("SELECT ARTIFACT_ID,CONTENT_HASH FROM GRAPH_ARTIFACTS WHERE CONTENT_HASH=:digest", {"digest": digest})
    if existing:
        return {"artifact_id": existing.get("artifact_id"), "content_digest": digest, "reused": True}
    artifact_id = _id("MART")
    execute(
        "INSERT INTO GRAPH_ARTIFACTS (ARTIFACT_ID,CONTENT_HASH,MEDIA_TYPE,CONTENT_SIZE,STORAGE_URI,CONTENT_BLOB,OWNER_REF,CLASSIFICATION,RETENTION_UNTIL) "
        "VALUES (:artifact_id,:digest,:media_type,:content_size,:storage_uri,:content_blob,:owner_ref,:classification,:retention_until)",
        {"artifact_id": artifact_id, "digest": digest, "media_type": media_type[:256], "content_size": len(raw),
         "storage_uri": storage_uri, "content_blob": raw, "owner_ref": owner_ref, "classification": classification,
         "retention_until": retention_until},
    )
    return {"artifact_id": artifact_id, "content_digest": digest, "reused": False}


def attach_artifact(version_id: str, artifact_id: str, *, actor: str, relation: str = "SOURCE") -> str:
    """Link a Version to content-addressed evidence without copying a large body."""
    link_id = _id("MALINK")
    execute("INSERT INTO CX_MEMORY_VERSION_ARTIFACTS (LINK_ID,VERSION_ID,ARTIFACT_ID,RELATION_TYPE,CREATED_BY) "
            "VALUES (:link_id,:version_id,:artifact_id,:relation,:actor)",
            {"link_id": link_id, "version_id": version_id, "artifact_id": artifact_id,
             "relation": relation[:32], "actor": actor})
    execute("UPDATE CX_MEMORY_VERSIONS SET SOURCE_REF=:source_ref, SOURCE_DIGEST=(SELECT CONTENT_HASH FROM GRAPH_ARTIFACTS WHERE ARTIFACT_ID=:artifact_id) WHERE VERSION_ID=:version_id",
            {"source_ref": f"artifact:{artifact_id}", "artifact_id": artifact_id, "version_id": version_id})
    return link_id


def select_representations(principal_id: str, version_ids: Iterable[str], *, purpose: str = "RUNTIME_CONTEXT",
                           token_budget: int = 2048, agent_instance_id: Optional[str] = None,
                           agent_fencing_token: Optional[int] = None) -> list[dict[str, Any]]:
    """Build diverse, authorized context without silently including duplicate source text."""
    remaining = max(0, min(int(token_budget), 100000))
    selected: list[dict[str, Any]] = []
    families: set[str] = set()
    digests: set[str] = set()
    order = SAFE_REPRESENTATION_ORDER.get(str(purpose).upper(), SAFE_REPRESENTATION_ORDER["RUNTIME_CONTEXT"])
    for version_id in list(dict.fromkeys(str(value) for value in version_ids))[:500]:
        version = _authorized_version(principal_id, version_id, purpose=purpose,
                                      agent_instance_id=agent_instance_id, agent_fencing_token=agent_fencing_token)
        if str(version.get("family_id") or "") in families:
            continue
        representations = execute_query(
            "SELECT * FROM CX_MEMORY_REPRESENTATIONS WHERE VERSION_ID=:version_id AND VALIDATION_STATE='VALID' "
            "AND INDEX_STATE='HOT' ORDER BY CREATED_AT DESC FETCH FIRST :lim ROWS ONLY",
            {"version_id": version_id, "lim": 20},
        )
        ranked = sorted(representations, key=lambda row: order.index(str(row.get("representation_type") or "SOURCE"))
                        if str(row.get("representation_type") or "SOURCE") in order else len(order))
        representation = next((row for row in ranked if int(row.get("token_count") or 0) <= remaining
                               and str(row.get("content_digest") or "") not in digests), None)
        if not representation:
            continue
        selected.append({"family_id": version.get("family_id"), "version_id": version_id,
                         "representation_id": representation.get("representation_id"),
                         "representation_type": representation.get("representation_type"),
                         "body_text": representation.get("body_text"), "token_count": int(representation.get("token_count") or 0)})
        families.add(str(version.get("family_id") or ""))
        digests.add(str(representation.get("content_digest") or ""))
        remaining -= int(representation.get("token_count") or 0)
    return selected


def archive_version(version_id: str, *, actor: str, reason: str, cold: bool = True) -> bool:
    """Logically archive evidence and remove it from ordinary hot retrieval."""
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "archive requires a reason")
    def commit(tx: Any) -> bool:
        version = tx.query_one("SELECT VERSION_ID,FAMILY_ID FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:version_id", {"version_id": version_id})
        if not version:
            raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
        tx.execute("UPDATE CX_MEMORY_VERSIONS SET LIFECYCLE_STATE='ARCHIVED', REASON=:reason WHERE VERSION_ID=:version_id", {"reason": reason[:2000], "version_id": version_id})
        if cold:
            tx.execute("UPDATE CX_MEMORY_REPRESENTATIONS SET INDEX_STATE='COLD' WHERE VERSION_ID=:version_id", {"version_id": version_id})
        tx.execute("UPDATE CX_MEMORY_RELATIONS SET RELATION_STATE='INACTIVE' WHERE SOURCE_VERSION_ID=:version_id OR TARGET_VERSION_ID=:version_id", {"version_id": version_id})
        _outbox(tx, "VERSION", version_id, "ARCHIVED", {"version_id": version_id, "reason": reason, "actor": actor})
        return True
    return bool(execute_transaction_callback(commit))


def create_deterministic_summary(version_id: str, *, token_budget: int = 128) -> str:
    """Create a no-LLM short representation without changing the source version."""
    source = execute_query_one(
        "SELECT BODY_TEXT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id",
        {"version_id": version_id},
    )
    if not source:
        raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
    body = str(source.get("body_text") or "").strip()
    maximum = max(32, min(int(token_budget), 1024)) * 4
    summary = body[:maximum]
    if len(body) > len(summary):
        boundary = max(summary.rfind(". "), summary.rfind("。"), summary.rfind("\n"))
        summary = summary[:boundary + 1] if boundary > len(summary) // 3 else summary.rstrip() + "..."
    return create_representation(
        version_id, "SHORT_SUMMARY", summary, generator_version="deterministic-extractive-v1",
        source_version_ids=[version_id],
    )


def create_deterministic_representations(version_id: str, *, token_budget: int = 256) -> list[str]:
    """Create bounded no-LLM representations without modifying the source Version.

    The output is deliberately extractive.  Semantic rewrites remain candidates
    for review, while these representation records retain their source digest.
    """
    source = execute_query_one(
        "SELECT TITLE,BODY_TEXT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id",
        {"version_id": version_id},
    )
    if not source:
        raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
    title = str(source.get("title") or "").strip()
    body = str(source.get("body_text") or "").strip()
    chunks = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+|\n+", body) if item.strip()]
    atomic = "\n".join(chunks[:8]) or body[:512]
    short_limit = max(32, min(int(token_budget), 1024)) * 4
    short = body[:short_limit].rstrip()
    if len(body) > len(short):
        short += "..."
    standard = body[: min(len(body), short_limit * 3)].rstrip()
    if len(body) > len(standard):
        standard += "..."
    topic = "\n".join(filter(None, [title, chunks[0] if chunks else body[:240]]))
    values = (
        ("ATOMIC_FACT", atomic),
        ("SHORT_SUMMARY", short),
        ("STANDARD_SUMMARY", standard),
        ("TOPIC_SUMMARY", topic),
    )
    return [
        create_representation(
            version_id, kind, text, generator_version="deterministic-extractive-v1",
            source_version_ids=[version_id],
        )
        for kind, text in values if text
    ]


def _select_snapshot_members(reader: Any, *, token_budget: int, limit: int = 200) -> list[dict[str, Any]]:
    """Select a bounded, reproducible context set through one DB reader.

    ``reader`` is either an adapter transaction or the module-level connection
    facade.  Keeping selection on the transaction used for persistence avoids
    publishing a snapshot whose members were read before a concurrent change.
    """
    versions = reader.query(
        "SELECT f.FAMILY_ID,f.LEGACY_ENTITY_ID,v.VERSION_ID,v.VERSION_NUMBER,v.TITLE,v.BODY_TEXT,"
        "v.MEMORY_TYPE,v.MEMORY_SCOPE,v.LIFECYCLE_STATE,v.CLASSIFICATION,v.OWNER_PRINCIPAL_ID,"
        "v.OWNER_AGENT_ID,v.WORKSPACE_ID,v.SECURITY_DOMAIN_ID,v.VALID_FROM,v.VALID_UNTIL "
        "FROM CX_MEMORY_FAMILIES f JOIN CX_MEMORY_VERSIONS v ON v.VERSION_ID=f.CURRENT_VERSION_ID "
        "WHERE v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED') "
        "AND (v.VALID_UNTIL IS NULL OR v.VALID_UNTIL > CURRENT_TIMESTAMP) "
        "ORDER BY v.CREATED_AT DESC FETCH FIRST :lim ROWS ONLY",
        {"lim": max(1, min(int(limit), 500))},
    )
    remaining = max(0, min(int(token_budget), 100000))
    members = []
    for rank, version in enumerate(versions):
        representations = reader.query(
            "SELECT REPRESENTATION_ID, REPRESENTATION_TYPE, TOKEN_COUNT FROM CX_MEMORY_REPRESENTATIONS WHERE VERSION_ID = :version_id AND VALIDATION_STATE = 'VALID' AND INDEX_STATE = 'HOT' ORDER BY CASE REPRESENTATION_TYPE WHEN 'SHORT_SUMMARY' THEN 1 WHEN 'ATOMIC_FACT' THEN 2 ELSE 3 END FETCH FIRST :lim ROWS ONLY",
            {"version_id": version["version_id"], "lim": 10},
        )
        representation = next((item for item in representations if int(item.get("token_count") or 0) <= remaining), None)
        if not representation:
            continue
        tokens = int(representation.get("token_count") or 0)
        members.append({"family_id": version["family_id"], "version_id": version["version_id"], "representation_id": representation["representation_id"], "rank": rank, "tokens": tokens})
        remaining -= tokens
    return members


def _snapshot_subject(tx: Any, principal_id: Optional[str], agent_instance_id: Optional[str],
                      agent_fencing_token: Optional[int]) -> dict[str, Any]:
    """Freeze only identifiers/versions; live status remains authoritative at read time."""
    subject = {"principal_id": principal_id, "principal_permission_version": None,
               "agent_instance_id": agent_instance_id, "agent_fencing_token": agent_fencing_token}
    if principal_id:
        principal = tx.query_one(
            "SELECT STATUS,PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id",
            {"principal_id": principal_id},
        )
        if not principal or str(principal.get("status") or "").upper() != "ACTIVE":
            raise MemoryLifecycleError("ACCESS_REVOKED", "memory snapshot principal is unavailable")
        subject["principal_permission_version"] = int(principal.get("permission_version") or 1)
    if agent_instance_id:
        instance = tx.query_one(
            "SELECT STATUS,FENCING_TOKEN,REVOKED_AT,LEASE_EXPIRES_AT FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance_id",
            {"instance_id": agent_instance_id},
        )
        actual_fencing = int((instance or {}).get("fencing_token") or -1)
        if (not instance or str(instance.get("status") or "").upper() != "ACTIVE"
                or instance.get("revoked_at") is not None or actual_fencing != int(agent_fencing_token or -1)):
            raise MemoryLifecycleError("ACCESS_REVOKED", "memory snapshot Agent instance is unavailable")
    return subject


def _insert_snapshot(tx: Any, *, snapshot_id: str, run_id: str, actor: str, purpose: str,
                     query_version: str, idempotency_key: Optional[str], members: list[dict[str, Any]],
                     subject: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    digest = _digest(run_id, purpose, query_version, _json(members))
    subject = dict(subject or {})
    tx.execute("INSERT INTO CX_MEMORY_SNAPSHOTS (SNAPSHOT_ID,RUN_ID,SNAPSHOT_VERSION,PURPOSE,POLICY_VERSION,QUERY_DIGEST,SNAPSHOT_DIGEST,STATE,CREATED_BY,IDEMPOTENCY_KEY,PRINCIPAL_ID,PRINCIPAL_PERMISSION_VERSION,AGENT_INSTANCE_ID,AGENT_FENCING_TOKEN) VALUES (:snapshot_id,:run_id,1,:purpose,'v4.3.2',:query_digest,:snapshot_digest,'ACTIVE',:actor,:idempotency_key,:principal_id,:principal_permission_version,:agent_instance_id,:agent_fencing_token)", {"snapshot_id": snapshot_id, "run_id": run_id, "purpose": purpose, "query_digest": _digest(query_version, purpose), "snapshot_digest": digest, "actor": actor, "idempotency_key": idempotency_key, **subject})
    for member in members:
        tx.execute("INSERT INTO CX_MEMORY_SNAPSHOT_MEMBERS (SNAPSHOT_ID,FAMILY_ID,VERSION_ID,REPRESENTATION_ID,SELECTION_RANK,SELECTED_TOKENS) VALUES (:snapshot_id,:family_id,:version_id,:representation_id,:rank,:tokens)", {"snapshot_id": snapshot_id, **member})
    return {"snapshot_id": snapshot_id, "snapshot_version": 1, "snapshot_digest": digest, "members": len(members), "token_count": sum(item["tokens"] for item in members)}


def create_snapshot(run_id: str, *, actor: str, purpose: str = "RUNTIME_CONTEXT", token_budget: int = 2048,
                    idempotency_key: Optional[str] = None, query_version: str = "v4.3.2",
                    principal_id: Optional[str] = None, agent_instance_id: Optional[str] = None,
                    agent_fencing_token: Optional[int] = None) -> dict[str, Any]:
    """Pin the selected current versions for a reproducible Run context."""
    if not run_id:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "run_id is required")
    snapshot_id = _id("MSNAP")
    def commit(tx: Any) -> dict[str, Any]:
        if idempotency_key:
            existing = tx.query_one("SELECT SNAPSHOT_ID, SNAPSHOT_VERSION, SNAPSHOT_DIGEST, STATE FROM CX_MEMORY_SNAPSHOTS WHERE RUN_ID = :run_id AND IDEMPOTENCY_KEY = :idempotency_key", {"run_id": run_id, "idempotency_key": idempotency_key})
            if existing:
                return dict(existing)
        return _insert_snapshot(
            tx, snapshot_id=snapshot_id, run_id=run_id, actor=actor, purpose=purpose,
            query_version=query_version, idempotency_key=idempotency_key,
            members=_select_snapshot_members(tx, token_budget=token_budget),
            subject=_snapshot_subject(tx, principal_id, agent_instance_id, agent_fencing_token),
        )
    return execute_transaction_callback(commit)


def snapshot_diff(snapshot_id: str) -> dict[str, Any]:
    snapshot = execute_query_one("SELECT SNAPSHOT_ID,RUN_ID,SNAPSHOT_VERSION,STATE,SNAPSHOT_DIGEST FROM CX_MEMORY_SNAPSHOTS WHERE SNAPSHOT_ID = :snapshot_id", {"snapshot_id": snapshot_id})
    if not snapshot:
        raise MemoryLifecycleError("NOT_FOUND", "memory snapshot is unavailable")
    pinned = execute_query("SELECT FAMILY_ID,VERSION_ID,REPRESENTATION_ID,SELECTION_RANK,SELECTED_TOKENS FROM CX_MEMORY_SNAPSHOT_MEMBERS WHERE SNAPSHOT_ID = :snapshot_id", {"snapshot_id": snapshot_id})
    current = {item["family_id"]: item for item in current_memories(limit=500)}
    changed = [
        {"family_id": item["family_id"], "pinned_version_id": item["version_id"], "current_version_id": current.get(item["family_id"], {}).get("version_id"), "status": "REMOVED" if item["family_id"] not in current else "CHANGED"}
        for item in pinned if current.get(item["family_id"], {}).get("version_id") != item["version_id"]
    ]
    added = [item for family, item in current.items() if family not in {member["family_id"] for member in pinned}]
    return {"snapshot": dict(snapshot), "changed": changed, "added": added[:100], "pinned_count": len(pinned)}


def refresh_snapshot(snapshot_id: str, *, actor: str, token_budget: int = 2048,
                     reason: str, idempotency_key: Optional[str] = None,
                     expected_snapshot_version: Optional[int] = None) -> dict[str, Any]:
    """Create the next Run snapshot only with an explicit actor and reason."""
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "memory snapshot refresh requires a reason")
    next_key = idempotency_key or f"refresh:{snapshot_id}:{_digest(reason)[:24]}"
    def commit(tx: Any) -> dict[str, Any]:
        prior = tx.query_one(
            "SELECT SNAPSHOT_ID,RUN_ID,PURPOSE,STATE,SNAPSHOT_VERSION,PRINCIPAL_ID,PRINCIPAL_PERMISSION_VERSION,AGENT_INSTANCE_ID,AGENT_FENCING_TOKEN FROM CX_MEMORY_SNAPSHOTS WHERE SNAPSHOT_ID = :snapshot_id",
            {"snapshot_id": snapshot_id},
        )
        if not prior or str(prior.get("state") or "").upper() != "ACTIVE":
            # A retry with the same idempotency key returns its committed successor.
            existing = tx.query_one(
                "SELECT SNAPSHOT_ID,SNAPSHOT_VERSION,SNAPSHOT_DIGEST,STATE FROM CX_MEMORY_SNAPSHOTS WHERE IDEMPOTENCY_KEY = :idempotency_key",
                {"idempotency_key": next_key},
            )
            if existing:
                return {**dict(existing), "refreshed_from": snapshot_id, "idempotent": True}
            raise MemoryLifecycleError("NOT_FOUND", "active memory snapshot is unavailable")
        actual_version = int(prior.get("snapshot_version") or 1)
        if expected_snapshot_version is not None and int(expected_snapshot_version) != actual_version:
            raise MemoryLifecycleError("VERSION_CONFLICT", "memory snapshot changed; refresh before retrying")
        existing = tx.query_one(
            "SELECT SNAPSHOT_ID,SNAPSHOT_VERSION,SNAPSHOT_DIGEST,STATE FROM CX_MEMORY_SNAPSHOTS WHERE RUN_ID = :run_id AND IDEMPOTENCY_KEY = :idempotency_key",
            {"run_id": prior["run_id"], "idempotency_key": next_key},
        )
        if existing:
            return {**dict(existing), "refreshed_from": snapshot_id, "idempotent": True}
        result = _insert_snapshot(
            tx, snapshot_id=_id("MSNAP"), run_id=str(prior["run_id"]), actor=actor,
            purpose=str(prior.get("purpose") or "RUNTIME_CONTEXT"), query_version="v4.3.2",
            idempotency_key=next_key, members=_select_snapshot_members(tx, token_budget=token_budget),
            subject=_snapshot_subject(tx, prior.get("principal_id"), prior.get("agent_instance_id"), prior.get("agent_fencing_token")),
        )
        changed = tx.execute(
            "UPDATE CX_MEMORY_SNAPSHOTS SET STATE = 'REFRESHED', REASON = :reason WHERE SNAPSHOT_ID = :snapshot_id "
            "AND STATE = 'ACTIVE' AND SNAPSHOT_VERSION = :expected_snapshot_version",
            {"reason": reason, "snapshot_id": snapshot_id, "expected_snapshot_version": actual_version},
        )
        if changed != 1:
            raise MemoryLifecycleError("VERSION_CONFLICT", "memory snapshot changed; refresh before retrying")
        _outbox(tx, "SNAPSHOT", snapshot_id, "REFRESHED", {
            "actor": actor, "reason": reason, "refreshed_to": result["snapshot_id"], "snapshot_version": actual_version,
        })
        return {**result, "refreshed_from": snapshot_id}
    return execute_transaction_callback(commit)


def resolve_snapshot(snapshot_id: str, *, continuation: str = "PAUSE") -> dict[str, Any]:
    """Resolve a pinned context against immediate security and expiry state.

    Snapshot membership remains immutable.  This resolver does not mutate it:
    security restrictions fail closed immediately, while ordinary expiry returns
    a governed boundary outcome instead of silently extending a memory.
    """
    mode = str(continuation or "PAUSE").upper()
    if mode not in {"PAUSE", "HUMAN_DECISION", "RISK_CONTINUE"}:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "unsupported snapshot continuation")
    snapshot = execute_query_one("SELECT SNAPSHOT_ID,STATE,PRINCIPAL_ID,PRINCIPAL_PERMISSION_VERSION,AGENT_INSTANCE_ID,AGENT_FENCING_TOKEN FROM CX_MEMORY_SNAPSHOTS WHERE SNAPSHOT_ID = :snapshot_id", {"snapshot_id": snapshot_id})
    if not snapshot:
        raise MemoryLifecycleError("NOT_FOUND", "memory snapshot is unavailable")
    principal_id = snapshot.get("principal_id")
    if principal_id:
        principal = execute_query_one("SELECT STATUS,PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:principal_id", {"principal_id": principal_id})
        if (not principal or str(principal.get("status") or "").upper() != "ACTIVE"
                or int(principal.get("permission_version") or 0) != int(snapshot.get("principal_permission_version") or 0)):
            raise MemoryLifecycleError("ACCESS_REVOKED", "snapshot principal authorization changed")
    instance_id = snapshot.get("agent_instance_id")
    if instance_id:
        instance = execute_query_one("SELECT STATUS,FENCING_TOKEN,REVOKED_AT,LEASE_EXPIRES_AT FROM CX_AGENT_INSTANCES WHERE INSTANCE_ID=:instance_id", {"instance_id": instance_id})
        if (not instance or str(instance.get("status") or "").upper() != "ACTIVE" or instance.get("revoked_at") is not None
                or int(instance.get("fencing_token") or -1) != int(snapshot.get("agent_fencing_token") or -1)):
            raise MemoryLifecycleError("ACCESS_REVOKED", "snapshot Agent fencing changed")
    rows = execute_query(
        "SELECT m.FAMILY_ID,m.VERSION_ID,m.REPRESENTATION_ID,m.SELECTED_TOKENS,v.LIFECYCLE_STATE,v.SECURITY_DOMAIN_ID,v.VALID_UNTIL,"
        "CASE WHEN v.VALID_UNTIL IS NOT NULL AND v.VALID_UNTIL <= CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS IS_EXPIRED "
        "FROM CX_MEMORY_SNAPSHOT_MEMBERS m JOIN CX_MEMORY_VERSIONS v ON v.VERSION_ID=m.VERSION_ID "
        "WHERE m.SNAPSHOT_ID=:snapshot_id ORDER BY m.SELECTION_RANK",
        {"snapshot_id": snapshot_id},
    )
    allowed, security_blocked, stale = [], [], []
    for row in rows:
        state = str(row.get("lifecycle_state") or "").upper()
        expired = int(row.get("is_expired") or 0) == 1
        if state in {"QUARANTINED", "UNAVAILABLE", "ARCHIVED", "EXPIRED"}:
            security_blocked.append({"version_id": row["version_id"], "reason": state})
        elif principal_id and row.get("security_domain_id"):
            domain_member = execute_query_one(
                "SELECT 1 AS MEMBER FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:domain_id AND PRINCIPAL_ID=:principal_id AND STATUS='ACTIVE'",
                {"domain_id": row["security_domain_id"], "principal_id": principal_id},
            )
            if not domain_member:
                security_blocked.append({"version_id": row["version_id"], "reason": "DOMAIN_REVOKED"})
        elif expired:
            stale.append({"version_id": row["version_id"], "reason": "EXPIRED"})
        else:
            allowed.append(dict(row))
    outcome = "READY" if not stale else mode
    return {"snapshot": dict(snapshot), "members": allowed, "security_blocked": security_blocked,
            "stale": stale, "outcome": outcome, "requires_governed_refresh": bool(stale),
            "risk_marked": bool(stale and mode == "RISK_CONTINUE")}


def dynamic_score_explanation(version_id: str) -> dict[str, Any]:
    """Explain bounded dynamic effectiveness without mutating base importance."""
    row = execute_query_one("SELECT LIFECYCLE_STATE, VALID_UNTIL, CREATED_AT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id", {"version_id": version_id})
    if not row:
        raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
    events = execute_query("SELECT EVENT_TYPE, OUTCOME, VALUE_NUMERIC FROM CX_MEMORY_USAGE_EVENTS WHERE VERSION_ID = :version_id FETCH FIRST :lim ROWS ONLY", {"version_id": version_id, "lim": 500})
    helpful = sum(1 for event in events if str(event.get("outcome") or "").upper() == "HELPFUL")
    stale = sum(1 for event in events if str(event.get("outcome") or "").upper() in {"STALE", "UNHELPFUL", "CONFLICT"})
    selected = sum(1 for event in events if str(event.get("event_type") or "").upper() in {"SELECTED", "CONTEXT_INCLUDED", "CITED"})
    relation = execute_query_one("SELECT COUNT(*) AS CNT FROM CX_MEMORY_RELATIONS WHERE (SOURCE_VERSION_ID=:version_id OR TARGET_VERSION_ID=:version_id) AND RELATION_STATE='ACTIVE'", {"version_id": version_id}) or {}
    graph_support = min(0.12, int(relation.get("cnt") or 0) * 0.01)
    state = str(row.get("lifecycle_state") or "").upper()
    state_penalty = 0.3 if state in {"CONFLICTED", "STALE"} else 0.0
    score = max(0.0, min(1.0, 0.45 + min(0.15, selected * 0.01) + min(0.15, helpful * 0.03) + graph_support - min(0.25, stale * 0.05) - state_penalty))
    return {"version_id": version_id, "effective_score": round(score, 4), "factors": {"selection_signal": selected, "helpful_feedback": helpful, "negative_feedback": stale, "graph_support": round(graph_support, 4), "lifecycle_penalty": state_penalty, "lifecycle_state": state}, "note": "Dynamic effectiveness does not change immutable content or base importance."}


def create_relation(source_version_id: str, target_version_id: str, relation_type: str, *, deterministic: bool, confidence: Optional[float] = None, method: str = "rule-v1", evidence: Optional[Mapping[str, Any]] = None, actor: Optional[str] = None) -> str:
    if source_version_id == target_version_id:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "a memory version cannot relate to itself")
    normalized_type = str(relation_type).upper()
    if normalized_type not in RELATION_TYPES:
        raise MemoryLifecycleError("INVALID_ARGUMENT", f"unsupported relation_type: {relation_type}")
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "relation confidence must be between zero and one")
    relation_id = _id("MREL")
    execute("INSERT INTO CX_MEMORY_RELATIONS (RELATION_ID,SOURCE_VERSION_ID,TARGET_VERSION_ID,RELATION_TYPE,RELATION_STATE,DETERMINISTIC,CONFIDENCE,METHOD,EVIDENCE_JSON,CREATED_BY) VALUES (:relation_id,:source_version_id,:target_version_id,:relation_type,'ACTIVE',:deterministic,:confidence,:method,:evidence,:actor)", {"relation_id": relation_id, "source_version_id": source_version_id, "target_version_id": target_version_id, "relation_type": normalized_type, "deterministic": _database_boolean(deterministic), "confidence": confidence, "method": method, "evidence": _json(dict(evidence or {})), "actor": actor})
    return relation_id


def discover_relations(version_id: str, *, actor: str, limit: int = 50, token_budget: int = 8192,
                       activate_low_risk: bool = True) -> dict[str, Any]:
    """Discover bounded overlap candidates without creating a quadratic graph."""
    source = execute_query_one("SELECT VERSION_ID,FAMILY_ID,BODY_TEXT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:version_id", {"version_id": version_id})
    if not source:
        raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
    terms = list(dict.fromkeys(re.findall(r"[A-Za-z0-9_]{4,}|[\u4e00-\u9fff]{2,}", str(source.get("body_text") or "")[:max(256, min(int(token_budget), 65536))].lower())))[:12]
    if not terms:
        return {"version_id": version_id, "activated": [], "candidates": [], "truncated": False}
    conditions = " OR ".join("UPPER(BODY_TEXT) LIKE UPPER(:term_%d)" % index for index in range(len(terms)))
    params = {f"term_{index}": f"%{term}%" for index, term in enumerate(terms)}
    params.update({"version_id": version_id, "family_id": source.get("family_id"), "lim": max(1, min(int(limit), 100))})
    rows = execute_query(
        "SELECT VERSION_ID,BODY_TEXT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID<>:version_id AND FAMILY_ID<>:family_id "
        "AND LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED') AND (" + conditions + ") "
        "ORDER BY CREATED_AT DESC FETCH FIRST :lim ROWS ONLY", params,
    )
    source_terms = set(terms)
    activated, candidates = [], []
    for row in rows:
        target_terms = set(re.findall(r"[A-Za-z0-9_]{4,}|[\u4e00-\u9fff]{2,}", str(row.get("body_text") or "").lower()))
        overlap = len(source_terms & target_terms) / max(1, len(source_terms | target_terms))
        target = str(row.get("version_id"))
        if overlap >= 0.6 and activate_low_risk:
            exists = execute_query_one("SELECT RELATION_ID FROM CX_MEMORY_RELATIONS WHERE SOURCE_VERSION_ID=:source AND TARGET_VERSION_ID=:target AND RELATION_TYPE='OVERLAPS' AND RELATION_STATE='ACTIVE'", {"source": version_id, "target": target})
            if not exists:
                activated.append(create_relation(version_id, target, "OVERLAPS", deterministic=True, confidence=round(overlap, 4), method="bounded-token-overlap-v1", evidence={"terms": sorted(source_terms & target_terms)[:12]}, actor=actor))
        elif overlap >= 0.2:
            candidates.append(create_candidate("RELATION", version_id, {"target_version_id": target, "relation_type": "SIMILAR_TO", "overlap": round(overlap, 4)}, actor=actor, confidence=round(overlap, 4), reason="bounded relation discovery"))
    return {"version_id": version_id, "activated": activated, "candidates": candidates, "truncated": len(rows) >= int(params["lim"]), "candidate_budget": int(params["lim"])}


def organize_memory(version_id: str, *, actor: str, dry_run: bool = True, token_budget: int = 256) -> dict[str, Any]:
    """Execute the staged deterministic organization path; semantic output stays a candidate."""
    version = execute_query_one("SELECT * FROM CX_MEMORY_VERSIONS WHERE VERSION_ID=:version_id", {"version_id": version_id})
    if not version:
        raise MemoryLifecycleError("NOT_FOUND", "memory version is unavailable")
    inspection = inspect_ingestion(str(version.get("body_text") or ""))
    result = {"version_id": version_id, "dry_run": bool(dry_run), "stages": ["NORMALIZE", "DISCOVER", "CLASSIFY", "REPRESENT", "VALIDATE", "REVIEW", "ACTIVATE", "INDEX", "OBSERVE"], "ingestion_signals": inspection["signals"], "would_quarantine": inspection["quarantine_recommended"]}
    if dry_run:
        return result
    for signal in inspection["signals"]:
        execute("INSERT INTO CX_MEMORY_INGESTION_FINDINGS (FINDING_ID,VERSION_ID,FINDING_TYPE,SEVERITY,CONTENT_DIGEST,EVIDENCE_JSON,STATUS) VALUES (:finding_id,:version_id,:finding_type,:severity,:digest,:evidence,'OPEN')", {"finding_id": _id("MIF"), "version_id": version_id, "finding_type": signal, "severity": "HIGH" if signal != "LINK" else "LOW", "digest": inspection["digest"], "evidence": _json({"detector": "deterministic-v1"})})
    if inspection["quarantine_recommended"]:
        family = get_family(str(version.get("family_id")))
        if ((family or {}).get("current") or {}).get("version_id") == version_id:
            quarantine_family(str(version.get("family_id")), actor=actor, reason="ingestion safety review required", expected_version_id=version_id)
        return {**result, "quarantined": True}
    representations = create_deterministic_representations(version_id, token_budget=token_budget)
    relations = discover_relations(version_id, actor=actor)
    return {**result, "representations": representations, "relations": relations, "validated": True}


def propose_llm_candidate(version_id: str, output: Mapping[str, Any], *, actor: str, endpoint_class: str,
                          model_id: str, prompt_version: str, input_digest: str) -> dict[str, Any]:
    """Store structured model output as an auditable candidate, never direct state."""
    if endpoint_class.upper() not in {"LOCAL", "APPROVED_INTERNAL"}:
        raise MemoryLifecycleError("POLICY_DENIED", "memory model endpoint is not approved")
    if not isinstance(output, Mapping) or not isinstance(output.get("summary"), str):
        raise MemoryLifecycleError("INVALID_ARGUMENT", "model output does not satisfy memory candidate schema")
    proposed = {"summary": str(output["summary"])[:16000], "atomic_facts": list(output.get("atomic_facts") or [])[:32], "relations": list(output.get("relations") or [])[:32], "model_id": model_id[:256], "endpoint_class": endpoint_class.upper(), "prompt_version": prompt_version[:128], "input_digest": input_digest, "output_digest": _digest(_json(output))}
    return create_candidate("LLM_SUMMARY", version_id, proposed, actor=actor, confidence=output.get("confidence"), reason="structured model output requires review")


def chain(version_id: str, *, hops: int = 2, limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    """Relational fallback chain traversal with hard hop and cardinality limits."""
    max_hops, max_nodes = max(1, min(int(hops), 6)), max(1, min(int(limit), 250))
    frontier, seen, nodes, relations = [version_id], {version_id}, [], []
    for _ in range(max_hops):
        if not frontier or len(seen) >= max_nodes:
            break
        rows = execute_query("SELECT * FROM CX_MEMORY_RELATIONS WHERE RELATION_STATE = 'ACTIVE' AND (SOURCE_VERSION_ID IN ({}) OR TARGET_VERSION_ID IN ({})) FETCH FIRST :lim ROWS ONLY".format(",".join(f":s{i}" for i in range(len(frontier))), ",".join(f":t{i}" for i in range(len(frontier)))), {**{f"s{i}": item for i, item in enumerate(frontier)}, **{f"t{i}": item for i, item in enumerate(frontier)}, "lim": max_nodes})
        next_frontier = []
        for relation in rows:
            relations.append(dict(relation))
            for candidate in (str(relation.get("source_version_id")), str(relation.get("target_version_id"))):
                if candidate not in seen and len(seen) < max_nodes:
                    seen.add(candidate); next_frontier.append(candidate)
        frontier = next_frontier
    for item in seen:
        row = execute_query_one("SELECT VERSION_ID,TITLE,MEMORY_TYPE,MEMORY_SCOPE,LIFECYCLE_STATE,CLASSIFICATION,CREATED_AT FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id", {"version_id": item})
        if row:
            nodes.append(dict(row))
    return {"nodes": nodes, "relations": relations[:max_nodes]}


def authorized_chain(principal_id: str, version_id: str, *, purpose: str = "RUNTIME_CONTEXT", hops: int = 2,
                     limit: int = 100, agent_instance_id: Optional[str] = None,
                     agent_fencing_token: Optional[int] = None) -> dict[str, list[dict[str, Any]]]:
    """Return an authorized induced subgraph without exposing hidden counts or edges."""
    _authorized_version(principal_id, version_id, purpose=purpose, agent_instance_id=agent_instance_id,
                        agent_fencing_token=agent_fencing_token)
    raw = chain(version_id, hops=hops, limit=limit)
    nodes, allowed_ids = [], set()
    for node in raw["nodes"]:
        try:
            _require_memory_access(principal_id, node, purpose=purpose, agent_instance_id=agent_instance_id,
                                   agent_fencing_token=agent_fencing_token)
        except MemoryLifecycleError:
            continue
        nodes.append(node)
        allowed_ids.add(str(node.get("version_id")))
    return {"nodes": nodes, "relations": [row for row in raw["relations"] if str(row.get("source_version_id")) in allowed_ids and str(row.get("target_version_id")) in allowed_ids]}


def create_candidate(candidate_type: str, source_version_id: str, proposed: Mapping[str, Any], *, actor: str, confidence: Optional[float] = None, reason: str = "", idempotency_key: Optional[str] = None) -> dict[str, Any]:
    candidate_type = str(candidate_type).upper()
    candidate_id = _id("MCAND")
    policy_result = "REVIEW" if candidate_type in HIGH_IMPACT_CANDIDATES else "VALIDATED"
    execute("INSERT INTO CX_MEMORY_CANDIDATES (CANDIDATE_ID,CANDIDATE_TYPE,SOURCE_VERSION_ID,PROPOSED_JSON,CONFIDENCE,STATUS,POLICY_RESULT,CREATED_BY,REASON,IDEMPOTENCY_KEY) VALUES (:candidate_id,:candidate_type,:source_version_id,:proposed,:confidence,'PENDING',:policy_result,:actor,:reason,:idempotency_key)", {"candidate_id": candidate_id, "candidate_type": candidate_type[:32], "source_version_id": source_version_id, "proposed": _json(dict(proposed)), "confidence": confidence, "policy_result": policy_result, "actor": actor, "reason": reason, "idempotency_key": idempotency_key})
    return {"candidate_id": candidate_id, "status": "PENDING", "policy_result": policy_result}


def review_candidate(candidate_id: str, decision: str, *, reviewer: str, reason: str) -> bool:
    decision = str(decision).upper()
    if decision not in {"APPROVE", "REJECT"} or not reason.strip():
        raise MemoryLifecycleError("INVALID_ARGUMENT", "review decision and reason are required")
    def commit(tx: Any) -> bool:
        item = tx.query_one("SELECT CANDIDATE_ID,STATUS FROM CX_MEMORY_CANDIDATES WHERE CANDIDATE_ID = :candidate_id", {"candidate_id": candidate_id})
        if not item or str(item.get("status")) != "PENDING":
            return False
        tx.execute("INSERT INTO CX_MEMORY_REVIEWS (REVIEW_ID,CANDIDATE_ID,REVIEWER_PRINCIPAL_ID,DECISION,REASON) VALUES (:review_id,:candidate_id,:reviewer,:decision,:reason)", {"review_id": _id("MREV"), "candidate_id": candidate_id, "reviewer": reviewer, "decision": decision, "reason": reason})
        tx.execute("UPDATE CX_MEMORY_CANDIDATES SET STATUS = :status, UPDATED_AT = CURRENT_TIMESTAMP WHERE CANDIDATE_ID = :candidate_id", {"status": "APPROVED" if decision == "APPROVE" else "REJECTED", "candidate_id": candidate_id})
        return True
    return bool(execute_transaction_callback(commit))


def activate_candidate(candidate_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    """Apply an approved replacement as a new Version, never an in-place edit."""
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "candidate activation requires a reason")
    candidate = execute_query_one(
        "SELECT c.CANDIDATE_ID,c.CANDIDATE_TYPE,c.SOURCE_VERSION_ID,c.PROPOSED_JSON,c.STATUS,v.FAMILY_ID "
        "FROM CX_MEMORY_CANDIDATES c JOIN CX_MEMORY_VERSIONS v ON v.VERSION_ID = c.SOURCE_VERSION_ID "
        "WHERE c.CANDIDATE_ID = :candidate_id",
        {"candidate_id": candidate_id},
    )
    if not candidate or str(candidate.get("status") or "").upper() != "APPROVED":
        raise MemoryLifecycleError("NOT_FOUND", "approved memory candidate is unavailable")
    if str(candidate.get("candidate_type") or "").upper() not in {"REPLACE", "MERGE", "SCOPE_CHANGE"}:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "candidate type cannot activate a memory version")
    claimed = execute(
        "UPDATE CX_MEMORY_CANDIDATES SET STATUS = 'ACTIVATING', UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE CANDIDATE_ID = :candidate_id AND STATUS = 'APPROVED'",
        {"candidate_id": candidate_id},
    )
    if claimed != 1:
        raise MemoryLifecycleError("VERSION_CONFLICT", "candidate activation is already in progress")
    try:
        proposed = json.loads(str(candidate.get("proposed_json") or "{}"))
        source = execute_query_one("SELECT * FROM CX_MEMORY_VERSIONS WHERE VERSION_ID = :version_id", {"version_id": candidate["source_version_id"]})
        if not source:
            raise MemoryLifecycleError("NOT_FOUND", "candidate source version is unavailable")
        request = {
            "title": proposed.get("title") or source.get("title"),
            "body": proposed.get("body") or source.get("body_text"),
            "memory_type": proposed.get("memory_type") or source.get("memory_type"),
            "memory_scope": proposed.get("memory_scope") or source.get("memory_scope"),
            "classification": proposed.get("classification") or source.get("classification"),
            "owner_principal_id": source.get("owner_principal_id"), "owner_agent_id": source.get("owner_agent_id"),
            "workspace_id": source.get("workspace_id"), "security_domain_id": source.get("security_domain_id"),
            "source_ref": source.get("source_ref"), "source_digest": source.get("source_digest"),
            "valid_until": source.get("valid_until"), "reason": reason,
        }
        result = create_successor(str(candidate["family_id"]), str(candidate["source_version_id"]), request, actor=actor)
        execute("UPDATE CX_MEMORY_CANDIDATES SET STATUS = 'ACTIVATED', UPDATED_AT = CURRENT_TIMESTAMP WHERE CANDIDATE_ID = :candidate_id", {"candidate_id": candidate_id})
        return {**result, "candidate_id": candidate_id, "status": "ACTIVATED"}
    except Exception:
        execute("UPDATE CX_MEMORY_CANDIDATES SET STATUS = 'APPROVED', UPDATED_AT = CURRENT_TIMESTAMP WHERE CANDIDATE_ID = :candidate_id AND STATUS = 'ACTIVATING'", {"candidate_id": candidate_id})
        raise


def _job_subjects(tx: Any, scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Freeze a bounded input partition when the durable job is created."""
    conditions = ["f.CURRENT_VERSION_ID = v.VERSION_ID", "v.LIFECYCLE_STATE IN ('ACTIVE','STALE','CONFLICTED','MIGRATED')"]
    params: dict[str, Any] = {"lim": max(1, min(int(scope.get("item_limit") or 100), 500))}
    if scope.get("family_id"):
        conditions.append("f.FAMILY_ID = :family_id")
        params["family_id"] = str(scope["family_id"])
    if scope.get("memory_scope"):
        conditions.append("v.MEMORY_SCOPE = :memory_scope")
        params["memory_scope"] = _normal(str(scope["memory_scope"]), MEMORY_SCOPES, "memory_scope")
    if scope.get("workspace_id"):
        conditions.append("v.WORKSPACE_ID = :workspace_id")
        params["workspace_id"] = str(scope["workspace_id"])
    if scope.get("owner_agent_id"):
        conditions.append("v.OWNER_AGENT_ID = :owner_agent_id")
        params["owner_agent_id"] = str(scope["owner_agent_id"])
    return tx.query(
        "SELECT v.VERSION_ID,v.CONTENT_DIGEST FROM CX_MEMORY_FAMILIES f JOIN CX_MEMORY_VERSIONS v "
        f"ON {' AND '.join(conditions)} ORDER BY v.CREATED_AT FETCH FIRST :lim ROWS ONLY", params,
    )


def create_job(job_type: str, *, actor: str, scope: Optional[Mapping[str, Any]] = None, dry_run: bool = True, reason: str = "", idempotency_key: Optional[str] = None) -> dict[str, Any]:
    job_type = str(job_type).upper()
    if job_type not in JOB_TYPES:
        raise MemoryLifecycleError("INVALID_ARGUMENT", f"unsupported memory job_type: {job_type}")
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "memory job requires a reason")
    normalized_scope = dict(scope or {})
    job_id = _id("MJOB")
    def commit(tx: Any) -> dict[str, Any]:
        if idempotency_key:
            existing = tx.query_one("SELECT JOB_ID,STATUS,DRY_RUN FROM CX_MEMORY_JOBS WHERE IDEMPOTENCY_KEY = :idempotency_key", {"idempotency_key": idempotency_key})
            if existing:
                return {"job_id": existing["job_id"], "status": existing["status"], "dry_run": str(existing.get("dry_run") or "Y").upper() in {"Y", "TRUE", "1"}, "idempotent": True}
        subjects = _job_subjects(tx, normalized_scope)
        tx.execute("INSERT INTO CX_MEMORY_JOBS (JOB_ID,JOB_TYPE,STATUS,SCOPE_JSON,DRY_RUN,POLICY_VERSION,REQUESTED_BY,REASON,IDEMPOTENCY_KEY,CHECKPOINT_JSON) VALUES (:job_id,:job_type,'QUEUED',:scope,:dry_run,'v4.3.2',:actor,:reason,:idempotency_key,:checkpoint)", {"job_id": job_id, "job_type": job_type, "scope": _json(normalized_scope), "dry_run": _database_boolean(dry_run), "actor": actor, "reason": reason, "idempotency_key": idempotency_key, "checkpoint": _json({"total_items": len(subjects), "completed_items": 0})})
        for subject in subjects:
            tx.execute("INSERT INTO CX_MEMORY_JOB_ITEMS (ITEM_ID,JOB_ID,SUBJECT_VERSION_ID,STATUS,INPUT_DIGEST,RESULT_JSON) VALUES (:item_id,:job_id,:version_id,'QUEUED',:digest,'{}')", {"item_id": _id("MJI"), "job_id": job_id, "version_id": subject["version_id"], "digest": subject.get("content_digest")})
        _outbox(tx, "JOB", job_id, "QUEUED", {"job_type": job_type, "items": len(subjects), "dry_run": bool(dry_run)})
        return {"job_id": job_id, "status": "QUEUED", "dry_run": bool(dry_run), "item_count": len(subjects)}
    return execute_transaction_callback(commit)


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    return [dict(row) for row in execute_query("SELECT * FROM CX_MEMORY_JOBS ORDER BY CREATED_AT DESC FETCH FIRST :lim ROWS ONLY", {"lim": max(1, min(int(limit), 200))})]


def claim_job(worker_id: str, *, lease_seconds: int = 120) -> Optional[dict[str, Any]]:
    """Claim one queued or expired job using a conditional fenced update."""
    if not worker_id.strip():
        raise MemoryLifecycleError("INVALID_ARGUMENT", "memory job worker_id is required")
    candidate = execute_query_one(
        "SELECT JOB_ID FROM CX_MEMORY_JOBS WHERE STATUS = 'QUEUED' OR "
        "(STATUS = 'RUNNING' AND LEASE_EXPIRES_AT <= CURRENT_TIMESTAMP) "
        "ORDER BY CREATED_AT FETCH FIRST :lim ROWS ONLY",
        {"lim": 1},
    )
    if not candidate:
        return None
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    claimed = execute(
        "UPDATE CX_MEMORY_JOBS SET STATUS = 'RUNNING', LEASE_OWNER = :worker_id, LEASE_EXPIRES_AT = :expires_at, "
        "FENCING_TOKEN = FENCING_TOKEN + 1, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE JOB_ID = :job_id AND (STATUS = 'QUEUED' OR (STATUS = 'RUNNING' AND LEASE_EXPIRES_AT <= CURRENT_TIMESTAMP))",
        {"worker_id": worker_id, "expires_at": expires_at, "job_id": candidate["job_id"]},
    )
    if claimed != 1:
        return None
    return execute_query_one("SELECT * FROM CX_MEMORY_JOBS WHERE JOB_ID = :job_id", {"job_id": candidate["job_id"]})


def complete_job(job_id: str, *, worker_id: str, fencing_token: int, result: Mapping[str, Any], status: str = "COMPLETED") -> bool:
    if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "terminal memory job status is invalid")
    changed = execute(
        "UPDATE CX_MEMORY_JOBS SET STATUS = :status, CHECKPOINT_JSON = :result, LEASE_EXPIRES_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE JOB_ID = :job_id AND STATUS = 'RUNNING' AND LEASE_OWNER = :worker_id AND FENCING_TOKEN = :fencing_token",
        {"status": status, "result": _json(dict(result)), "job_id": job_id, "worker_id": worker_id, "fencing_token": int(fencing_token)},
    )
    return changed == 1


def renew_job_lease(job_id: str, *, worker_id: str, fencing_token: int, lease_seconds: int = 120) -> bool:
    """Renew only the caller's current lease; a stale node cannot extend it."""
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    changed = execute(
        "UPDATE CX_MEMORY_JOBS SET LEASE_EXPIRES_AT=:expires_at, UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE JOB_ID=:job_id AND STATUS='RUNNING' AND LEASE_OWNER=:worker_id AND FENCING_TOKEN=:fencing_token AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP",
        {"expires_at": expires_at, "job_id": job_id, "worker_id": worker_id, "fencing_token": int(fencing_token)},
    )
    return changed == 1


def cancel_job(job_id: str, *, actor: str, reason: str) -> bool:
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "memory job cancellation requires a reason")
    def commit(tx: Any) -> bool:
        changed = tx.execute("UPDATE CX_MEMORY_JOBS SET STATUS='CANCELLED', REASON=:reason, UPDATED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:job_id AND STATUS IN ('QUEUED','RUNNING')", {"job_id": job_id, "reason": reason})
        if changed:
            tx.execute("UPDATE CX_MEMORY_JOB_ITEMS SET STATUS='CANCELLED', UPDATED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:job_id AND STATUS IN ('QUEUED','RUNNING')", {"job_id": job_id})
            _outbox(tx, "JOB", job_id, "CANCELLED", {"actor": actor, "reason": reason})
        return changed == 1
    return bool(execute_transaction_callback(commit))


def retry_job(job_id: str, *, actor: str, reason: str) -> bool:
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "memory job retry requires a reason")
    def commit(tx: Any) -> bool:
        changed = tx.execute("UPDATE CX_MEMORY_JOBS SET STATUS='QUEUED', LEASE_OWNER=NULL, LEASE_EXPIRES_AT=NULL, UPDATED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:job_id AND STATUS IN ('FAILED','CANCELLED')", {"job_id": job_id})
        if changed:
            tx.execute("UPDATE CX_MEMORY_JOB_ITEMS SET STATUS='QUEUED', LEASE_OWNER=NULL, LEASE_EXPIRES_AT=NULL, UPDATED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:job_id AND STATUS IN ('FAILED','CANCELLED')", {"job_id": job_id})
            _outbox(tx, "JOB", job_id, "REQUEUED", {"actor": actor, "reason": reason})
        return changed == 1
    return bool(execute_transaction_callback(commit))


def claim_job_item(job_id: str, *, worker_id: str, job_fencing_token: int, lease_seconds: int = 120) -> Optional[dict[str, Any]]:
    """Claim one bounded item while proving the enclosing job lease is still ours."""
    candidate = execute_query_one(
        "SELECT ITEM_ID FROM CX_MEMORY_JOB_ITEMS WHERE JOB_ID=:job_id AND (STATUS='QUEUED' OR (STATUS='RUNNING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP)) ORDER BY CREATED_AT FETCH FIRST :lim ROWS ONLY",
        {"job_id": job_id, "lim": 1},
    )
    if not candidate:
        return None
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    changed = execute(
        "UPDATE CX_MEMORY_JOB_ITEMS SET STATUS='RUNNING',LEASE_OWNER=:worker_id,LEASE_EXPIRES_AT=:expires_at,FENCING_TOKEN=FENCING_TOKEN+1,ATTEMPT_COUNT=ATTEMPT_COUNT+1,UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE ITEM_ID=:item_id AND (STATUS='QUEUED' OR (STATUS='RUNNING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP)) "
        "AND EXISTS (SELECT 1 FROM CX_MEMORY_JOBS j WHERE j.JOB_ID=:job_id AND j.STATUS='RUNNING' AND j.LEASE_OWNER=:worker_id AND j.FENCING_TOKEN=:job_fencing_token AND j.LEASE_EXPIRES_AT>CURRENT_TIMESTAMP)",
        {"worker_id": worker_id, "expires_at": expires_at, "item_id": candidate["item_id"], "job_id": job_id, "job_fencing_token": int(job_fencing_token)},
    )
    if changed != 1:
        return None
    return execute_query_one("SELECT * FROM CX_MEMORY_JOB_ITEMS WHERE ITEM_ID=:item_id", {"item_id": candidate["item_id"]})


def complete_job_item(item_id: str, *, worker_id: str, fencing_token: int, result: Mapping[str, Any], status: str = "COMPLETED") -> bool:
    if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "terminal memory job item status is invalid")
    changed = execute(
        "UPDATE CX_MEMORY_JOB_ITEMS SET STATUS=:status,RESULT_JSON=:result,LEASE_EXPIRES_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE ITEM_ID=:item_id AND STATUS='RUNNING' AND LEASE_OWNER=:worker_id AND FENCING_TOKEN=:fencing_token",
        {"status": status, "result": _json(dict(result)), "item_id": item_id, "worker_id": worker_id, "fencing_token": int(fencing_token)},
    )
    return changed == 1


def submit_external_worker_result(item_id: str, *, worker_id: str, fencing_token: int,
                                  input_digest: str, output: Mapping[str, Any], schema_version: str = "memory-candidate-v1") -> dict[str, Any]:
    """Accept an authenticated external-worker result only for its live fenced item.

    The payload is schema-checked and stored as evidence.  It creates a
    candidate rather than changing a Version or relation directly.
    """
    if not isinstance(output, Mapping) or not isinstance(output.get("summary"), str):
        raise MemoryLifecycleError("INVALID_ARGUMENT", "external worker output schema is invalid")
    item = execute_query_one("SELECT ITEM_ID,SUBJECT_VERSION_ID,STATUS,LEASE_OWNER,FENCING_TOKEN,INPUT_DIGEST FROM CX_MEMORY_JOB_ITEMS WHERE ITEM_ID=:item_id", {"item_id": item_id})
    if (not item or str(item.get("status") or "") != "RUNNING" or str(item.get("lease_owner") or "") != worker_id
            or int(item.get("fencing_token") or -1) != int(fencing_token)):
        raise MemoryLifecycleError("FENCING_REJECTED", "external worker lease is unavailable")
    if str(item.get("input_digest") or "") != str(input_digest):
        raise MemoryLifecycleError("INPUT_CONFLICT", "external worker input changed")
    output_digest = _digest(_json(output))
    result_id = _id("MWR")
    execute("INSERT INTO CX_MEMORY_WORKER_RESULTS (RESULT_ID,JOB_ITEM_ID,WORKER_ID,FENCING_TOKEN,INPUT_DIGEST,OUTPUT_DIGEST,SCHEMA_VERSION,RESULT_JSON,VALIDATION_STATE) VALUES (:result_id,:item_id,:worker_id,:fencing_token,:input_digest,:output_digest,:schema_version,:result,'VALID')", {"result_id": result_id, "item_id": item_id, "worker_id": worker_id, "fencing_token": int(fencing_token), "input_digest": input_digest, "output_digest": output_digest, "schema_version": schema_version[:64], "result": _json(dict(output))})
    candidate = propose_llm_candidate(str(item.get("subject_version_id")), output, actor=worker_id,
                                      endpoint_class="APPROVED_INTERNAL", model_id=str(output.get("model_id") or "external-worker"),
                                      prompt_version=str(output.get("prompt_version") or "external-v1"), input_digest=input_digest)
    completed = complete_job_item(item_id, worker_id=worker_id, fencing_token=fencing_token,
                                  result={"worker_result_id": result_id, "candidate_id": candidate["candidate_id"], "output_digest": output_digest})
    if not completed:
        raise MemoryLifecycleError("FENCING_REJECTED", "external worker completion was superseded")
    return {"worker_result_id": result_id, "candidate": candidate}


def claim_projection_event(worker_id: str, *, lease_seconds: int = 120) -> Optional[dict[str, Any]]:
    """Claim one rebuildable projection event without making it an authority.

    A projection worker only consumes relational outbox facts.  It never decides
    visibility or authorization, so an unavailable AGE/native graph cannot
    widen access and relational traversal remains the functional fallback.
    """
    if not worker_id.strip():
        raise MemoryLifecycleError("INVALID_ARGUMENT", "projection worker_id is required")
    candidate = execute_query_one(
        "SELECT OUTBOX_ID FROM CX_MEMORY_PROJECTION_OUTBOX WHERE (STATUS='PENDING' AND AVAILABLE_AT<=CURRENT_TIMESTAMP) OR (STATUS='RUNNING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP) ORDER BY CREATED_AT FETCH FIRST :lim ROWS ONLY",
        {"lim": 1},
    )
    if not candidate:
        return None
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    changed = execute(
        "UPDATE CX_MEMORY_PROJECTION_OUTBOX SET STATUS='RUNNING',LEASE_OWNER=:worker_id,LEASE_EXPIRES_AT=:expires_at,FENCING_TOKEN=FENCING_TOKEN+1,ATTEMPTS=ATTEMPTS+1 "
        "WHERE OUTBOX_ID=:outbox_id AND ((STATUS='PENDING' AND AVAILABLE_AT<=CURRENT_TIMESTAMP) OR (STATUS='RUNNING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP))",
        {"worker_id": worker_id, "expires_at": expires_at, "outbox_id": candidate["outbox_id"]},
    )
    if changed != 1:
        return None
    return execute_query_one("SELECT * FROM CX_MEMORY_PROJECTION_OUTBOX WHERE OUTBOX_ID=:outbox_id", {"outbox_id": candidate["outbox_id"]})


def complete_projection_event(outbox_id: str, *, worker_id: str, fencing_token: int) -> bool:
    return execute(
        "UPDATE CX_MEMORY_PROJECTION_OUTBOX SET STATUS='PROCESSED',PROCESSED_AT=CURRENT_TIMESTAMP,LEASE_EXPIRES_AT=CURRENT_TIMESTAMP "
        "WHERE OUTBOX_ID=:outbox_id AND STATUS='RUNNING' AND LEASE_OWNER=:worker_id AND FENCING_TOKEN=:fencing_token",
        {"outbox_id": outbox_id, "worker_id": worker_id, "fencing_token": int(fencing_token)},
    ) == 1


def defer_projection_event(outbox_id: str, *, worker_id: str, fencing_token: int, reason: str, retry_seconds: int = 30) -> bool:
    """Return a failed projection event to the queue with bounded delayed retry."""
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "projection retry requires a reason")
    available_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=max(5, min(int(retry_seconds), 3600)))
    return execute(
        "UPDATE CX_MEMORY_PROJECTION_OUTBOX SET STATUS='PENDING',AVAILABLE_AT=:available_at,LEASE_OWNER=NULL,LEASE_EXPIRES_AT=NULL "
        "WHERE OUTBOX_ID=:outbox_id AND STATUS='RUNNING' AND LEASE_OWNER=:worker_id AND FENCING_TOKEN=:fencing_token",
        {"available_at": available_at, "outbox_id": outbox_id, "worker_id": worker_id, "fencing_token": int(fencing_token)},
    ) == 1


def projection_metrics() -> dict[str, Any]:
    row = execute_query_one(
        "SELECT COUNT(*) AS TOTAL, SUM(CASE WHEN STATUS='PENDING' THEN 1 ELSE 0 END) AS PENDING, "
        "SUM(CASE WHEN STATUS='RUNNING' THEN 1 ELSE 0 END) AS RUNNING, "
        "SUM(CASE WHEN STATUS='PROCESSED' THEN 1 ELSE 0 END) AS PROCESSED, MIN(CASE WHEN STATUS='PENDING' THEN CREATED_AT ELSE NULL END) AS OLDEST_PENDING_AT "
        "FROM CX_MEMORY_PROJECTION_OUTBOX",
        {},
    ) or {}
    return {"total": int(row.get("total") or 0), "pending": int(row.get("pending") or 0),
            "running": int(row.get("running") or 0), "processed": int(row.get("processed") or 0),
            "oldest_pending_at": row.get("oldest_pending_at"), "authority": "RELATIONAL"}


def request_projection_rebuild(*, actor: str, limit: int = 500, reason: str) -> dict[str, Any]:
    """Queue a bounded relational rebuild; workers may rebuild any graph view."""
    if not reason.strip():
        raise MemoryLifecycleError("REASON_REQUIRED", "projection rebuild requires a reason")
    bounded = max(1, min(int(limit), 5000))
    def commit(tx: Any) -> dict[str, Any]:
        versions = tx.query(
            "SELECT VERSION_ID FROM CX_MEMORY_VERSIONS WHERE LIFECYCLE_STATE NOT IN ('QUARANTINED','UNAVAILABLE','ARCHIVED') ORDER BY CREATED_AT FETCH FIRST :lim ROWS ONLY",
            {"lim": bounded},
        )
        for version in versions:
            _outbox(tx, "VERSION", str(version["version_id"]), "PROJECTION_REBUILD", {"actor": actor, "reason": reason})
        return {"queued": len(versions), "limit": bounded, "authority": "RELATIONAL"}
    return execute_transaction_callback(commit)


def _finish_job_if_done(job: Mapping[str, Any], *, worker_id: str, result: Mapping[str, Any]) -> bool:
    remaining = execute_query_one("SELECT COUNT(*) AS REMAINING FROM CX_MEMORY_JOB_ITEMS WHERE JOB_ID=:job_id AND STATUS NOT IN ('COMPLETED','CANCELLED')", {"job_id": job["job_id"]})
    if int((remaining or {}).get("remaining") or 0) != 0:
        return False
    return complete_job(str(job["job_id"]), worker_id=worker_id, fencing_token=int(job["fencing_token"]), result=result)


def run_job_once(worker_id: str, *, lease_seconds: int = 120) -> Optional[dict[str, Any]]:
    """Execute the deterministic, bounded part of one claimed memory job."""
    job = claim_job(worker_id, lease_seconds=lease_seconds)
    if not job:
        return None
    try:
        dry_run = bool(job.get("dry_run")) if isinstance(job.get("dry_run"), bool) else str(job.get("dry_run") or "Y").upper() == "Y"
        result: dict[str, Any] = {"job_id": job["job_id"], "job_type": job["job_type"], "dry_run": dry_run, "processed_items": 0, "created_representations": 0, "candidate_count": 0}
        while True:
            item = claim_job_item(str(job["job_id"]), worker_id=worker_id, job_fencing_token=int(job["fencing_token"]), lease_seconds=lease_seconds)
            if not item:
                break
            item_result: dict[str, Any] = {"version_id": item.get("subject_version_id"), "dry_run": dry_run}
            if not dry_run and str(job.get("job_type") or "").upper() in {"REPRESENT", "CONSOLIDATE"}:
                created = create_deterministic_representations(str(item["subject_version_id"]))
                item_result["representations"] = len(created)
                result["created_representations"] += len(created)
            if str(job.get("job_type") or "").upper() == "ARCHIVE_REVIEW":
                item_result["review_required"] = True
                result["candidate_count"] += 1
            if not complete_job_item(str(item["item_id"]), worker_id=worker_id, fencing_token=int(item["fencing_token"]), result=item_result):
                raise MemoryLifecycleError("VERSION_CONFLICT", "memory job item lease was lost")
            result["processed_items"] += 1
            if not renew_job_lease(str(job["job_id"]), worker_id=worker_id, fencing_token=int(job["fencing_token"]), lease_seconds=lease_seconds):
                raise MemoryLifecycleError("VERSION_CONFLICT", "memory job lease was lost")
        result["completed"] = _finish_job_if_done(job, worker_id=worker_id, result=result)
        return result
    except Exception as exc:
        complete_job(str(job["job_id"]), worker_id=worker_id, fencing_token=int(job["fencing_token"]), result={"error": str(exc)[:1000]}, status="FAILED")
        raise


def record_usage(version_id: str, event_type: str, *, principal_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None, purpose: str = "RUNTIME_CONTEXT", outcome: Optional[str] = None, value: Optional[float] = None, idempotency_key: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None) -> str:
    normalized_event = str(event_type).upper()
    if normalized_event not in USAGE_EVENT_TYPES:
        raise MemoryLifecycleError("INVALID_ARGUMENT", "unsupported memory usage event")
    if agent_id:
        blocked = execute_query_one("SELECT 1 AS BLOCKED FROM CX_AGENT_INSTANCES WHERE AGENT_ID=:agent_id AND STATUS IN ('REVOKED','QUARANTINED','DISABLED') FETCH FIRST :lim ROWS ONLY", {"agent_id": agent_id, "lim": 1})
        if blocked:
            raise MemoryLifecycleError("ACCESS_DENIED", "feedback source is unavailable")
    event_id = _id("MUSE")
    execute("INSERT INTO CX_MEMORY_USAGE_EVENTS (USAGE_EVENT_ID,VERSION_ID,EVENT_TYPE,PRINCIPAL_ID,AGENT_ID,RUN_ID,PURPOSE,OUTCOME,VALUE_NUMERIC,IDEMPOTENCY_KEY,METADATA_JSON) VALUES (:event_id,:version_id,:event_type,:principal_id,:agent_id,:run_id,:purpose,:outcome,:value,:idempotency_key,:metadata)", {"event_id": event_id, "version_id": version_id, "event_type": normalized_event, "principal_id": principal_id, "agent_id": agent_id, "run_id": run_id, "purpose": purpose[:128], "outcome": outcome, "value": value, "idempotency_key": idempotency_key or event_id, "metadata": _json(dict(metadata or {}))})
    return event_id


def _insert_version(tx: Any, version_id: str, family_id: str, number: int, request: VersionRequest, digest: str, actor: str, *, lifecycle_state: str = "ACTIVE") -> None:
    tx.execute("INSERT INTO CX_MEMORY_VERSIONS (VERSION_ID,FAMILY_ID,VERSION_NUMBER,TITLE,BODY_TEXT,CONTENT_DIGEST,MEMORY_TYPE,MEMORY_SCOPE,LIFECYCLE_STATE,CLASSIFICATION,SOURCE_REF,SOURCE_DIGEST,OWNER_PRINCIPAL_ID,OWNER_AGENT_ID,WORKSPACE_ID,SECURITY_DOMAIN_ID,VALID_UNTIL,POLICY_VERSION,CREATED_BY,REASON,METADATA_JSON) VALUES (:version_id,:family_id,:version_number,:title,:body,:digest,:memory_type,:memory_scope,:lifecycle_state,:classification,:source_ref,:source_digest,:owner_principal_id,:owner_agent_id,:workspace_id,:security_domain_id,:valid_until,:policy_version,:actor,:reason,'{}')", {"version_id": version_id, "family_id": family_id, "version_number": number, "title": request.title, "body": request.body, "digest": digest, "memory_type": request.memory_type.upper(), "memory_scope": request.memory_scope.upper(), "lifecycle_state": _normal(lifecycle_state, LIFECYCLE_STATES, "lifecycle_state"), "classification": request.classification, "source_ref": request.source_ref, "source_digest": request.source_digest, "owner_principal_id": request.owner_principal_id, "owner_agent_id": request.owner_agent_id, "workspace_id": request.workspace_id, "security_domain_id": request.security_domain_id, "valid_until": request.valid_until, "policy_version": request.policy_version, "actor": actor, "reason": request.reason})


def _insert_source_representation(tx: Any, version_id: str, body: str, digest: str) -> None:
    tx.execute("INSERT INTO CX_MEMORY_REPRESENTATIONS (REPRESENTATION_ID,VERSION_ID,REPRESENTATION_TYPE,BODY_TEXT,CONTENT_DIGEST,TOKEN_COUNT,GENERATION_METHOD,SOURCE_VERSION_IDS_JSON) VALUES (:representation_id,:version_id,'SOURCE',:body,:digest,:token_count,'DETERMINISTIC','[]')", {"representation_id": _id("MR"), "version_id": version_id, "body": body, "digest": digest, "token_count": max(0, len(body) // 4)})


def _relation(tx: Any, source: str, target: str, relation_type: str, *, deterministic: bool, actor: str) -> None:
    tx.execute("INSERT INTO CX_MEMORY_RELATIONS (RELATION_ID,SOURCE_VERSION_ID,TARGET_VERSION_ID,RELATION_TYPE,RELATION_STATE,DETERMINISTIC,METHOD,EVIDENCE_JSON,CREATED_BY) VALUES (:relation_id,:source,:target,:relation_type,'ACTIVE',:deterministic,'lifecycle-v1','{}',:actor)", {"relation_id": _id("MREL"), "source": source, "target": target, "relation_type": relation_type, "deterministic": _database_boolean(deterministic), "actor": actor})


def _outbox(tx: Any, aggregate_type: str, aggregate_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
    tx.execute("INSERT INTO CX_MEMORY_PROJECTION_OUTBOX (OUTBOX_ID,AGGREGATE_TYPE,AGGREGATE_ID,EVENT_TYPE,PAYLOAD_JSON) VALUES (:outbox_id,:aggregate_type,:aggregate_id,:event_type,:payload)", {"outbox_id": _id("MOUT"), "aggregate_type": aggregate_type, "aggregate_id": aggregate_id, "event_type": event_type, "payload": _json(dict(payload))})
