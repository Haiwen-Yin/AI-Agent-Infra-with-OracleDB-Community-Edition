"""Database-mediated Agent collaboration (DB4A2A) contracts.

The wire message carries references and consistency facts.  The receiving
Agent must authenticate separately and read the authorized database projection;
references never grant data, Tool, Skill, Model, or export authority.
"""

from __future__ import annotations

import json
import hashlib
import re
import secrets
from dataclasses import dataclass
from decimal import Decimal
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


def context_snapshot(context_data: Any) -> str:
    """Version 1 hashes canonical stored JSON, not client prose or transport bytes."""
    if hasattr(context_data, "read"):
        context_data = context_data.read()
    if isinstance(context_data, (str, bytes)):
        context_data = json.loads(context_data, parse_float=Decimal)

    def canonical(value):
        if value is None or isinstance(value, (str, bool)):
            return [type(value).__name__, value]
        if isinstance(value, (int, float, Decimal)):
            number = Decimal(str(value))
            if not number.is_finite():
                raise DB4A2AError("context contains a non-finite number")
            sign, digits, exponent = number.as_tuple()
            text = "".join(str(digit) for digit in digits).rstrip("0")
            if not text:
                return ["number", "0"]
            exponent += len(digits) - len(text)
            return ["number", ("-" if sign else "") + text + "e" + str(exponent)]
        if isinstance(value, list):
            return ["array", [canonical(item) for item in value]]
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return ["object", [[key, canonical(value[key])] for key in sorted(value)]]
        raise DB4A2AError("context contains an unsupported JSON value")

    encoded = json.dumps(canonical(context_data), sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _check_context_reader(receiver: str, context_id: str) -> None:
    """Use the receiver's real database identity, never the control-plane Owner."""
    from . import connection

    previous = connection.get_current_agent_id()
    try:
        connection.set_agent_context(receiver)
        table = ("CX_AGENT_CONTEXT_READ" if connection.DATABASE_DIALECT in {"yashandb", "yashan"}
                 else "WORKSPACE_CONTEXT")
        visible = connection.execute_query_one(
            f"SELECT CONTEXT_ID FROM {table} WHERE CONTEXT_ID=:id", {"id": context_id})
        if not visible:
            raise PermissionError("receiver cannot read the referenced database context")
    finally:
        connection.set_agent_context(previous)


def _lock_reader_policy(tx: Any, reader: str, context_id: str) -> None:
    """Serialize principal disable and explicit-share deletion with dispatch."""
    from . import connection

    principal = tx.query_one(
        "SELECT PRINCIPAL_ID,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id FOR UPDATE",
        {"id": reader})
    principal = {str(k).lower(): v for k, v in dict(principal or {}).items()}
    if principal.get("status") != "ACTIVE":
        raise PermissionError("DB4A2A participant is inactive or unknown")
    if connection.DATABASE_DIALECT in {"yashandb", "yashan"}:
        tx.query_one("SELECT CONTEXT_ID FROM CX_CONTEXT_READ_GRANTS "
                     "WHERE CONTEXT_ID=:context AND AGENT_ID=:agent FOR UPDATE",
                     {"context": context_id, "agent": reader})


def _check_context(tx: Any, envelope: Mapping[str, Any]) -> dict[str, Any]:
    row = tx.query_one(
        "SELECT CONTEXT_ID,WORKSPACE_ID,CONTEXT_DATA,BRANCH_ID,AGENT_ID FROM WORKSPACE_CONTEXT "
        "WHERE CONTEXT_ID=:context FOR UPDATE", {"context": envelope["context_ref"]})
    item = {str(key).lower(): value for key, value in dict(row or {}).items()}
    if not item:
        raise DB4A2AError("referenced workspace context is unavailable")
    workspace = tx.query_one("SELECT WORKSPACE_ID FROM WORKSPACES WHERE WORKSPACE_ID=:workspace "
                             "AND STATUS='ACTIVE'", {"workspace": item["workspace_id"]})
    if not workspace:
        raise DB4A2AError("referenced workspace is unavailable")
    validate_reference_access(envelope, authenticated=True, authorized=True,
                              observed_version=1, observed_digest=context_snapshot(item["context_data"]))
    if envelope["scope_ref"] != "workspace:" + str(item["workspace_id"]):
        raise DB4A2AError("context workspace scope mismatch")
    if str(envelope.get("source_branch") or "") != str(item.get("branch_id") or ""):
        raise DB4A2AError("context source branch mismatch")
    return item


def _check_context_sender(tx: Any, actor: str, context: Mapping[str, Any]) -> None:
    """Receiver visibility never delegates a sender's context authority."""
    from . import identity_api

    principal = tx.query_one(
        "SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor",
        {"actor": actor})
    principal = {str(k).lower(): v for k, v in dict(principal or {}).items()}
    if principal.get("status") != "ACTIVE":
        raise PermissionError("DB4A2A sender is inactive or unknown")
    if principal.get("principal_type") == "AGENT":
        _check_context_reader(actor, str(context["context_id"]))
        return
    if principal.get("principal_type") != "HUMAN":
        raise PermissionError("DB4A2A sender identity is unsupported")
    if identity_api.effective_access(actor, "agents.manage.all").get("decision") == "ALLOW":
        return
    workspace = tx.query_one(
        "SELECT WORKSPACE_ID FROM WORKSPACES WHERE WORKSPACE_ID=:workspace AND OWNER_USER_ID=:actor",
        {"workspace": context["workspace_id"], "actor": actor})
    if not workspace:
        raise PermissionError("DB4A2A sender does not own the referenced workspace")


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
    def work(tx: Any) -> None:
        if normalized["transport"] == "DB_MEDIATED":
            for participant in sorted({actor, receiver}):
                _lock_reader_policy(tx, participant, normalized["context_ref"])
            context = _check_context(tx, normalized)
            _check_context_reader(receiver, normalized["context_ref"])
            _check_context_sender(tx, actor, context)
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
    """Lock, verify and fork a reference in one database transaction."""
    from . import branch_api, connection, identity_api

    if identity_api.effective_access(actor, "agents.operate").get("decision") != "ALLOW":
        raise PermissionError("DB4A2A branch permission denied")
    dispatch_id = _required(dispatch_id, "dispatch id")

    def work(tx: Any) -> dict[str, Any]:
        row = tx.query_one(
        "SELECT DISPATCH_ID,SENDER_PRINCIPAL_ID,RECEIVER_AGENT_ID,CONTEXT_REF,SNAPSHOT_DIGEST,EXPECTED_VERSION,"
        "SCOPE_REF,SOURCE_BRANCH,TRANSPORT,BRANCH_POLICY,STATUS,CHILD_BRANCH_ID "
        "FROM CX_DB4A2A_DISPATCHES WHERE DISPATCH_ID=:id "
        "AND (SENDER_PRINCIPAL_ID=:actor OR RECEIVER_AGENT_ID=:actor) FOR UPDATE",
        {"id": dispatch_id, "actor": actor})
        item = {str(key).lower(): value for key, value in dict(row or {}).items()}
        if not item or actor not in (item.get("sender_principal_id"), item.get("receiver_agent_id")):
            raise DB4A2AError("DB4A2A dispatch is unavailable")
        if str(item.get("status") or "").upper() not in {"DISPATCHED", "BRANCHED"}:
            raise DB4A2AError("DB4A2A dispatch is not active")
        if item.get("branch_policy") != "CHILD_BRANCH_WRITE":
            raise DB4A2AError("branch policy does not permit child writes")
        if item.get("transport") != "DB_MEDIATED":
            raise DB4A2AError("payload dispatch cannot fork a database reference")
        for participant in sorted({str(item["sender_principal_id"]), str(item["receiver_agent_id"])}):
            _lock_reader_policy(tx, participant, str(item["context_ref"]))
        context = _check_context(tx, item)
        _check_context_reader(str(item["receiver_agent_id"]), str(item["context_ref"]))
        _check_context_sender(tx, str(item["sender_principal_id"]), context)
        if item.get("child_branch_id"):
            return {"dispatch_id": dispatch_id, "branch_id": item["child_branch_id"], "idempotent": True}
        if item["status"] != "DISPATCHED":
            raise DB4A2AError("DB4A2A branched dispatch is missing its branch")
        name = str(branch_name or "").strip()
        if not name or len(name) > 256:
            raise DB4A2AError("invalid branch name")
        branch_id = branch_api.fork_branch_tx(
            tx, workspace_id=context["workspace_id"], fork_context_id=item["context_ref"],
            branch_name=name, agent_id=item["receiver_agent_id"],
            source_agent_id=context.get("agent_id"), purpose=str(purpose or "")[:500],
            parent_branch_id=context.get("branch_id"))
        changed = tx.execute(
        "UPDATE CX_DB4A2A_DISPATCHES SET CHILD_BRANCH_ID=:branch,STATUS='BRANCHED',UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE DISPATCH_ID=:id AND CHILD_BRANCH_ID IS NULL AND STATUS='DISPATCHED' "
        "AND (SENDER_PRINCIPAL_ID=:actor OR RECEIVER_AGENT_ID=:actor)",
        {"branch": branch_id, "id": dispatch_id, "actor": actor})
        if int(changed or 0) != 1:
            raise DB4A2AError("DB4A2A dispatch changed while branching")
        identity_api._audit_tx(tx, actor, "DB4A2A_BRANCH", "DB4A2A_DISPATCH", dispatch_id,
                               "ALLOW", "verified reference branch")
        return {"dispatch_id": dispatch_id, "branch_id": branch_id,
                "provenance": child_branch_provenance(item, branch_id), "idempotent": False}

    return connection.execute_transaction_callback(work)
