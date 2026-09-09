"""Immutable approval bindings shared by bounded platform mutations."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import identity_api


class ApprovalRequired(PermissionError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def request(actor: str, action_type: str, binding: dict[str, Any], reason: str) -> dict[str, Any]:
    if not action_type.startswith("PLATFORM_") or not reason.strip():
        raise ValueError("A platform action and reason are required")
    payload = {"binding": binding, "binding_digest": digest(binding), "requested_by": actor,
               "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}
    return identity_api.create_action_card(actor, "CH_PLATFORM_ADMINISTRATION", action_type, payload, reason,
        "GOVERNED:" + digest({"actor": actor, "type": action_type, "payload": payload}))


def require_tx(tx: Any, action_id: str, action_type: str, binding: dict[str, Any],
               required_action: str) -> dict[str, Any]:
    if not action_id:
        raise ApprovalRequired("An independently approved Action Card is required")
    raw = tx.query_one("SELECT ACTION_ID,ACTION_TYPE,CHANNEL_ID,PROPOSED_BY,DECIDED_BY,STATUS,PAYLOAD_JSON "
                       "FROM CX_ACTION_CARDS WHERE ACTION_ID=:id FOR UPDATE", {"id": action_id})
    row = {str(key).lower(): value for key, value in (raw or {}).items()}
    if (row.get("status") != "CONFIRMED" or row.get("action_type") != action_type
            or row.get("channel_id") != "CH_PLATFORM_ADMINISTRATION"):
        raise ApprovalRequired("Matching confirmed Action Card is required")
    try:
        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"])
        expiry = datetime.fromisoformat(payload["expires_at"])
        valid = (expiry.tzinfo is not None and expiry > datetime.now(timezone.utc)
                 and payload["binding"] == binding and payload["binding_digest"] == digest(binding)
                 and payload["requested_by"] == row["proposed_by"])
    except (KeyError, ValueError, TypeError):
        valid = False
    if not valid:
        raise ApprovalRequired("Approval binding changed or expired; request approval again")
    if not row.get("decided_by") or row["decided_by"] == row["proposed_by"]:
        raise ApprovalRequired("An independent Human approval is required")
    for principal, action in ((row["proposed_by"], required_action), (row["decided_by"], "channels.actions.decide")):
        identity = tx.query_one("SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id FOR UPDATE", {"id": principal})
        identity = {str(key).lower(): value for key, value in (identity or {}).items()}
        if identity.get("status") != "ACTIVE" or (principal == row["decided_by"] and identity.get("principal_type") != "HUMAN"):
            raise ApprovalRequired("Approval principal is inactive or is not a Human approver")
        if identity_api.effective_access(principal, action).get("decision") != "ALLOW":
            raise ApprovalRequired("Approval principal authority was revoked")
        identity_api._assert_channel_member(principal, "CH_PLATFORM_ADMINISTRATION", action)
    return row
