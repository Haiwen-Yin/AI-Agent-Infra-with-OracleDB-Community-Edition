"""Pure contracts for Graph event authentication, replay, and poison handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


EVENT_SCHEMA = "graph-event/1"
EVENT_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
SCHEMA_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
MAX_EVENT_BYTES = 1024 * 1024
DEFAULT_REPLAY_WINDOW_SECONDS = 300
SIGNATURE_ALGORITHM = "HMAC-SHA256"
TRIGGER_KINDS = frozenset({"MANUAL", "API", "SCHEDULE", "DATABASE", "EXTERNAL", "INTERNAL"})


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def _timestamp(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def validate_event(source_ref: str, event_type: str, schema_version: str,
                   idempotency_key: str, payload: Any,
                   *, max_bytes: int = MAX_EVENT_BYTES) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    if not isinstance(source_ref, str) or not IDENTITY_PATTERN.fullmatch(source_ref):
        errors.append({"code": "EVENT_SOURCE_INVALID", "field": "source_ref"})
    if not isinstance(event_type, str) or not EVENT_TYPE_PATTERN.fullmatch(event_type.upper()):
        errors.append({"code": "EVENT_TYPE_INVALID", "field": "event_type"})
    if not isinstance(schema_version, str) or not SCHEMA_VERSION_PATTERN.fullmatch(schema_version):
        errors.append({"code": "EVENT_SCHEMA_VERSION_INVALID", "field": "schema_version"})
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        errors.append({"code": "EVENT_IDEMPOTENCY_INVALID", "field": "idempotency_key"})
    if not isinstance(payload, dict):
        errors.append({"code": "EVENT_PAYLOAD_OBJECT_REQUIRED", "field": "payload"})
    else:
        try:
            size = len(canonical(payload).encode("utf-8"))
        except (TypeError, ValueError):
            errors.append({"code": "EVENT_PAYLOAD_NOT_JSON", "field": "payload"})
        else:
            if size > max(1, min(int(max_bytes), 50 * 1024 * 1024)):
                errors.append({"code": "EVENT_PAYLOAD_TOO_LARGE", "size": size, "limit": int(max_bytes)})
    return errors


def _signing_document(source_ref: str, event_type: str, schema_version: str,
                      idempotency_key: str, payload: Any, issued_at: Any,
                      nonce: str) -> bytes:
    return canonical({
        "source_ref": source_ref, "event_type": event_type.upper(),
        "schema_version": schema_version, "idempotency_key": idempotency_key,
        "payload_hash": payload_hash(payload), "issued_at": issued_at, "nonce": nonce,
    }).encode("utf-8")


def sign_event(source_ref: str, event_type: str, schema_version: str,
               idempotency_key: str, payload: Dict[str, Any], secret: bytes,
               *, subject: str, key_id: str = "default", issued_at: Optional[Any] = None,
               nonce: Optional[str] = None) -> Dict[str, Any]:
    """Create an auth envelope; the secret is never part of the returned value."""
    if not isinstance(secret, bytes) or len(secret) < 16:
        raise ValueError("event signing key must contain at least 16 bytes")
    errors = validate_event(source_ref, event_type, schema_version, idempotency_key, payload)
    if errors:
        raise ValueError(canonical(errors))
    timestamp = issued_at if issued_at is not None else int(time.time())
    nonce = nonce or secrets.token_urlsafe(18)
    signature = hmac.new(secret, _signing_document(
        source_ref, event_type, schema_version, idempotency_key, payload, timestamp, nonce,
    ), hashlib.sha256).hexdigest()
    return {
        "algorithm": SIGNATURE_ALGORITHM, "key_id": str(key_id), "subject": str(subject),
        "issued_at": timestamp, "nonce": nonce, "signature": signature,
    }


def verify_event_auth(source_ref: str, event_type: str, schema_version: str,
                      idempotency_key: str, payload: Dict[str, Any],
                      authentication: Optional[Dict[str, Any]],
                      key_lookup: Optional[Mapping[str, bytes] | Callable[[str], Optional[bytes]]] = None,
                      *, now: Optional[float] = None,
                      replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
                      require_signature: bool = True) -> Dict[str, Any]:
    """Verify a signed event without trusting a request-body ``subject``."""
    auth = dict(authentication or {})
    errors = validate_event(source_ref, event_type, schema_version, idempotency_key, payload)
    subject = str(auth.get("subject") or auth.get("agent_id") or "")
    if not subject or not IDENTITY_PATTERN.fullmatch(subject):
        errors.append({"code": "EVENT_SUBJECT_INVALID", "field": "authentication.subject"})
    signature = str(auth.get("signature") or "")
    if not signature:
        if require_signature:
            errors.append({"code": "EVENT_SIGNATURE_REQUIRED"})
        return {"authenticated": False, "replay": False, "errors": errors, "subject": subject}
    if str(auth.get("algorithm") or "").upper() != SIGNATURE_ALGORITHM:
        errors.append({"code": "EVENT_SIGNATURE_ALGORITHM_INVALID"})
    key_id = str(auth.get("key_id") or "")
    key = key_lookup.get(key_id) if isinstance(key_lookup, Mapping) else key_lookup(key_id) if callable(key_lookup) else None
    if not key:
        errors.append({"code": "EVENT_SIGNING_KEY_UNAVAILABLE", "key_id": key_id})
    issued_at = _timestamp(auth.get("issued_at"))
    current = float(now if now is not None else time.time())
    if issued_at is None:
        errors.append({"code": "EVENT_TIMESTAMP_INVALID"})
    elif abs(current - issued_at) > max(1, int(replay_window_seconds)):
        errors.append({"code": "EVENT_REPLAY_WINDOW_EXCEEDED"})
    nonce = str(auth.get("nonce") or "")
    if not nonce or len(nonce) > 128:
        errors.append({"code": "EVENT_NONCE_INVALID"})
    if key and issued_at is not None and nonce and not errors:
        expected = hmac.new(key, _signing_document(
            source_ref, event_type, schema_version, idempotency_key, payload,
            auth.get("issued_at"), nonce,
        ), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            errors.append({"code": "EVENT_SIGNATURE_INVALID"})
    return {"authenticated": not errors, "replay": any(item["code"].startswith("EVENT_REPLAY") for item in errors),
            "errors": errors, "subject": subject, "key_id": key_id}


def classify_event(*, validation_errors: Optional[Iterable[Dict[str, Any]]] = None,
                   authentication: Optional[Dict[str, Any]] = None,
                   duplicate: bool = False) -> Dict[str, Any]:
    errors = list(validation_errors or [])
    auth = authentication or {}
    auth_errors = list(auth.get("errors") or [])
    if duplicate:
        return {"status": "DUPLICATE", "activation_allowed": False, "poison": False, "errors": []}
    errors.extend(auth_errors)
    poison = bool(errors)
    return {
        "status": "DEAD_LETTER" if poison else ("PROCESSED" if auth.get("authenticated") else "RECEIVED"),
        "activation_allowed": bool(auth.get("authenticated")) and not poison,
        "poison": poison,
        "errors": errors,
    }


def normalize_trigger(kind: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate the six trigger families without making a network/database call."""
    kind = str(kind or "").upper()
    config = dict(config or {})
    if kind not in TRIGGER_KINDS:
        raise ValueError(f"unknown Graph trigger kind: {kind or '<missing>'}")
    required: Dict[str, tuple[str, ...]] = {
        "MANUAL": (), "API": ("path",), "SCHEDULE": ("expression",),
        "DATABASE": ("source_ref", "event_type"),
        "EXTERNAL": ("source_ref", "event_type"), "INTERNAL": ("event_type",),
    }
    missing = [name for name in required[kind] if not str(config.get(name) or "").strip()]
    if missing:
        raise ValueError(f"Graph {kind} trigger requires: {', '.join(missing)}")
    if kind == "SCHEDULE" and not (config.get("timezone") or "UTC"):
        raise ValueError("Graph schedule trigger requires a timezone")
    if kind in {"DATABASE", "EXTERNAL", "INTERNAL"}:
        event_type = str(config.get("event_type") or "").upper()
        if not EVENT_TYPE_PATTERN.fullmatch(event_type):
            raise ValueError("Graph trigger event_type is invalid")
        config["event_type"] = event_type
    if kind == "API":
        path = str(config["path"])
        if not path.startswith("/") or len(path) > 512:
            raise ValueError("Graph API trigger path is invalid")
        config["path"] = path
    return {"trigger_schema": "graph-trigger/1", "kind": kind, "config": config}
