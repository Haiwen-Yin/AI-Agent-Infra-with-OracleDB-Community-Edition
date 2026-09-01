"""Database-mediated Agent collaboration (DB4A2A) contracts.

The wire message carries references and consistency facts.  The receiving
Agent must authenticate separately and read the authorized database projection;
references never grant data, Tool, Skill, Model, or export authority.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, Mapping


class DB4A2AError(ValueError):
    pass


_ID = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")


def _required(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result or not _ID.fullmatch(result):
        raise DB4A2AError(f"invalid {label}")
    return result


@dataclass(frozen=True)
class ContextReference:
    context_id: str
    snapshot_digest: str
    expected_version: int
    scope_ref: str
    source_branch: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_id", _required(self.context_id, "context reference"))
        object.__setattr__(self, "snapshot_digest", _required(self.snapshot_digest, "snapshot digest"))
        object.__setattr__(self, "scope_ref", _required(self.scope_ref, "scope reference"))
        if int(self.expected_version) < 1:
            raise DB4A2AError("expected version must be positive")
        if self.source_branch:
            object.__setattr__(self, "source_branch", _required(self.source_branch, "source branch"))


def build_dispatch(
    *,
    task_id: str,
    context: ContextReference,
    branch_policy: str = "READ_ONLY",
    transport: str = "DB_MEDIATED",
    inline_context: Any = None,
) -> dict[str, Any]:
    """Build a small dispatch envelope and reject accidental payload copying."""
    if inline_context not in (None, "", {}, [], ()):
        raise DB4A2AError("DB4A2A dispatch cannot carry inline context")
    policy = str(branch_policy or "").upper()
    if policy not in {"READ_ONLY", "CHILD_BRANCH_WRITE"}:
        raise DB4A2AError("invalid branch policy")
    mode = str(transport or "").upper()
    if mode not in {"DB_MEDIATED", "A2A_PAYLOAD"}:
        raise DB4A2AError("invalid collaboration transport")
    return {
        "protocol": "db4a2a/v1",
        "task_id": _required(task_id, "task id"),
        "context_ref": context.context_id,
        "snapshot_digest": context.snapshot_digest,
        "expected_version": int(context.expected_version),
        "scope_ref": context.scope_ref,
        "source_branch": context.source_branch or None,
        "branch_policy": policy,
        "transport": mode,
    }


def validate_reference_access(
    envelope: Mapping[str, Any],
    *,
    authenticated: bool,
    authorized: bool,
    observed_version: int,
    observed_digest: str,
) -> dict[str, Any]:
    """Validate a reference immediately before reading shared context."""
    if not authenticated:
        raise DB4A2AError("Agent authentication is required")
    if not authorized:
        raise DB4A2AError("context reference is not authorized")
    expected = int(envelope.get("expected_version") or 0)
    if expected != int(observed_version):
        raise DB4A2AError("context version mismatch")
    if str(envelope.get("snapshot_digest") or "") != str(observed_digest or ""):
        raise DB4A2AError("context snapshot mismatch")
    return {"read_allowed": True, "context_ref": str(envelope.get("context_ref") or "")}


def child_branch_provenance(envelope: Mapping[str, Any], branch_id: str) -> dict[str, Any]:
    """Create immutable provenance for a branch-local write."""
    if str(envelope.get("branch_policy") or "").upper() != "CHILD_BRANCH_WRITE":
        raise DB4A2AError("branch policy does not permit child writes")
    return {
        "branch_id": _required(branch_id, "branch id"),
        "source_context_ref": _required(envelope.get("context_ref"), "context reference"),
        "source_snapshot_digest": _required(envelope.get("snapshot_digest"), "snapshot digest"),
        "source_expected_version": int(envelope.get("expected_version") or 0),
        "source_scope_ref": _required(envelope.get("scope_ref"), "scope reference"),
        "write_mode": "CHILD_BRANCH_ONLY",
    }


def persist_dispatch(actor: str, receiver_agent_id: str, envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a validated reference dispatch in the database control plane."""
    from . import connection, identity_api

    if identity_api.effective_access(actor, "agents.operate").get("decision") != "ALLOW":
        raise PermissionError("DB4A2A dispatch permission denied")
    receiver = _required(receiver_agent_id, "receiver Agent")
    if not identity_api._agent_visible_to(actor, receiver):
        raise PermissionError("DB4A2A receiver is outside the delegated scope")
    dispatch_id = "DBA2A_" + secrets.token_hex(20)
    normalized = {
        "task_id": _required(envelope.get("task_id"), "task id"),
        "context_ref": _required(envelope.get("context_ref"), "context reference"),
        "snapshot_digest": _required(envelope.get("snapshot_digest"), "snapshot digest"),
        "scope_ref": _required(envelope.get("scope_ref"), "scope reference"),
        "expected_version": int(envelope.get("expected_version") or 0),
        "branch_policy": str(envelope.get("branch_policy") or "READ_ONLY").upper(),
        "transport": str(envelope.get("transport") or "DB_MEDIATED").upper(),
        "source_branch": str(envelope.get("source_branch") or ""),
    }
    if normalized["expected_version"] < 1:
        raise DB4A2AError("expected version must be positive")
    if normalized["branch_policy"] not in {"READ_ONLY", "CHILD_BRANCH_WRITE"}:
        raise DB4A2AError("invalid branch policy")
    if normalized["transport"] not in {"DB_MEDIATED", "A2A_PAYLOAD"}:
        raise DB4A2AError("invalid collaboration transport")
    if normalized["transport"] == "DB_MEDIATED":
        context = identity_api._row(connection.execute_query_one(
            "SELECT c.CONTEXT_ID,c.WORKSPACE_ID FROM WORKSPACE_CONTEXT c "
            "JOIN WORKSPACES w ON w.WORKSPACE_ID=c.WORKSPACE_ID "
            "WHERE c.CONTEXT_ID=:context AND w.STATUS='ACTIVE'",
            {"context": normalized["context_ref"]},
        ))
        if not context:
            raise PermissionError("DB4A2A context is unavailable in the authorized database scope")

    def work(tx: Any) -> None:
        tx.execute(
            "INSERT INTO CX_DB4A2A_DISPATCHES(DISPATCH_ID,TASK_ID,SENDER_PRINCIPAL_ID,RECEIVER_AGENT_ID,"
            "CONTEXT_REF,SNAPSHOT_DIGEST,EXPECTED_VERSION,SCOPE_REF,SOURCE_BRANCH,BRANCH_POLICY,TRANSPORT,STATUS) "
            "VALUES (:id,:task,:sender,:receiver,:context,:digest,:version,:scope,:source,:policy,:transport,'DISPATCHED')",
            {"id": dispatch_id, "task": normalized["task_id"], "sender": actor, "receiver": receiver,
             "context": normalized["context_ref"], "digest": normalized["snapshot_digest"],
             "version": normalized["expected_version"], "scope": normalized["scope_ref"],
             "source": normalized["source_branch"] or None, "policy": normalized["branch_policy"],
             "transport": normalized["transport"]},
        )
        identity_api._audit_tx(tx, actor, "DB4A2A_DISPATCH", "DB4A2A_DISPATCH", dispatch_id,
                               "ALLOW", "reference-oriented Agent task dispatch")

    connection.execute_transaction_callback(work)
    return {"dispatch_id": dispatch_id, "status": "DISPATCHED", **normalized, "receiver_agent_id": receiver}


def list_dispatches(actor: str, limit: int = 100) -> dict[str, Any]:
    from . import connection, identity_api

    if identity_api.effective_access(actor, "tasks.read").get("decision") != "ALLOW":
        raise PermissionError("DB4A2A dispatch read permission denied")
    amount = max(1, min(int(limit), 500))
    dialect = str(getattr(connection, "DATABASE_DIALECT", "")).lower()
    suffix = " FETCH FIRST :limit ROWS ONLY" if dialect in {"oracle", "yashandb", "yashan"} else " LIMIT :limit"
    rows = connection.execute_query(
        "SELECT DISPATCH_ID,TASK_ID,SENDER_PRINCIPAL_ID,RECEIVER_AGENT_ID,CONTEXT_REF,SNAPSHOT_DIGEST,"
        "EXPECTED_VERSION,SCOPE_REF,SOURCE_BRANCH,BRANCH_POLICY,TRANSPORT,STATUS,CHILD_BRANCH_ID,CREATED_AT,UPDATED_AT "
        "FROM CX_DB4A2A_DISPATCHES WHERE SENDER_PRINCIPAL_ID=:actor OR RECEIVER_AGENT_ID=:actor "
        "ORDER BY CREATED_AT DESC" + suffix,
        {"actor": actor, "limit": amount},
    )
    items = [{str(key).lower(): value for key, value in dict(row).items()} for row in rows]
    return {"items": items, "count": len(items)}


def create_dispatch_branch(actor: str, dispatch_id: str, branch_name: str, purpose: str) -> dict[str, Any]:
    """Fork the referenced workspace Context through the existing Branch API."""
    from . import branch_api, connection, identity_api

    if identity_api.effective_access(actor, "agents.operate").get("decision") != "ALLOW":
        raise PermissionError("DB4A2A branch permission denied")
    row = connection.execute_query_one(
        "SELECT DISPATCH_ID,SENDER_PRINCIPAL_ID,RECEIVER_AGENT_ID,CONTEXT_REF,SNAPSHOT_DIGEST,EXPECTED_VERSION,"
        "SCOPE_REF,BRANCH_POLICY,STATUS,CHILD_BRANCH_ID "
        "FROM CX_DB4A2A_DISPATCHES WHERE DISPATCH_ID=:id",
        {"id": _required(dispatch_id, "dispatch id")},
    )
    item = {str(key).lower(): value for key, value in dict(row or {}).items()}
    if not item:
        raise DB4A2AError("DB4A2A dispatch is unavailable")
    if item.get("child_branch_id"):
        return {"dispatch_id": dispatch_id, "branch_id": item["child_branch_id"], "idempotent": True}
    if str(item.get("branch_policy") or "").upper() != "CHILD_BRANCH_WRITE":
        raise DB4A2AError("branch policy does not permit child writes")
    context = connection.execute_query_one(
        "SELECT WORKSPACE_ID FROM WORKSPACE_CONTEXT WHERE CONTEXT_ID=:context",
        {"context": item["context_ref"]},
    )
    context_row = {str(key).lower(): value for key, value in dict(context or {}).items()}
    if not context_row.get("workspace_id"):
        raise DB4A2AError("referenced workspace context is unavailable")
    branch_id = branch_api.fork_branch(
        workspace_id=str(context_row["workspace_id"]), fork_context_id=str(item["context_ref"]),
        branch_name=_required(branch_name, "branch name"), branch_type="DB4A2A",
        agent_id=str(item.get("receiver_agent_id") or actor),
        source_agent_id=str(item.get("sender_principal_id") or actor),
        purpose=str(purpose or "")[:500],
    )
    changed = connection.execute_transaction_callback(lambda tx: tx.execute(
        "UPDATE CX_DB4A2A_DISPATCHES SET CHILD_BRANCH_ID=:branch,STATUS='BRANCHED',UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE DISPATCH_ID=:id AND CHILD_BRANCH_ID IS NULL",
        {"branch": branch_id, "id": dispatch_id},
    ))
    if int(changed or 0) != 1:
        raise DB4A2AError("DB4A2A branch was created concurrently")
    return {"dispatch_id": dispatch_id, "branch_id": branch_id,
            "provenance": child_branch_provenance(item, branch_id), "idempotent": False}
