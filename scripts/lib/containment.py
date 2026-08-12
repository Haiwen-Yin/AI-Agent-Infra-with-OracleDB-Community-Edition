"""Pure v4.4.1 Agent containment command contract."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Mapping


STATES = ("OBSERVE", "DRAIN", "QUARANTINE", "TERMINATE", "INFRA_TERMINATE")
STATE_ORDER = {state: index for index, state in enumerate(STATES)}


def command_payload(instance_id: str, generation: int, nonce: str, issuer: str, reason: str, expires_at: str, action: str) -> str:
    return json.dumps({"action": action, "expires_at": expires_at, "generation": generation,
                       "instance_id": instance_id, "issuer": issuer, "nonce": nonce, "reason": reason},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sign_command(payload: str, secret: bytes) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_command(command: Mapping[str, Any], *, current_generation: int, current_state: str, secret: bytes, now: datetime | None = None) -> tuple[bool, str]:
    action = str(command.get("action") or "").upper()
    if action not in STATES:
        return False, "ACTION_INVALID"
    if STATE_ORDER[action] < STATE_ORDER.get(str(current_state).upper(), 0):
        return False, "STATE_REGRESSION"
    try:
        generation = int(command.get("generation"))
    except (TypeError, ValueError):
        return False, "GENERATION_INVALID"
    if generation <= current_generation:
        return False, "STALE_GENERATION"
    expiry = str(command.get("expires_at") or "")
    try:
        parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed <= (now or datetime.now(timezone.utc)):
            return False, "COMMAND_EXPIRED"
    except ValueError:
        return False, "EXPIRY_INVALID"
    payload = command_payload(str(command.get("instance_id") or ""), generation, str(command.get("nonce") or ""),
                              str(command.get("issuer") or ""), str(command.get("reason") or ""), expiry, action)
    if not hmac.compare_digest(str(command.get("signature") or ""), sign_command(payload, secret)):
        return False, "SIGNATURE_INVALID"
    if not command.get("instance_id") or not command.get("nonce") or not command.get("reason"):
        return False, "COMMAND_INCOMPLETE"
    return True, "VALID"


def quarantine_precedes_termination(current_state: str, requested_state: str) -> bool:
    current = str(current_state or "OBSERVE").upper()
    requested = str(requested_state or "").upper()
    return requested not in {"TERMINATE", "INFRA_TERMINATE"} or current in {"QUARANTINE", "TERMINATE", "INFRA_TERMINATE"}
