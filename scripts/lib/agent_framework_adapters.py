"""Framework-neutral adapters for the external Agent Gateway contract.

The Gateway is the security and delivery boundary.  OpenClaw, Hermes, and
other runtimes may use different local message objects, but this module keeps
the conversion contract deliberately small and deterministic:

* Gateway events become a message envelope with an explicit transport event
  and an application message.
* Framework messages become the fields accepted by the Gateway message API.
* Acknowledgements are converted independently so a framework cannot invent
  an identity or reuse an unrelated delivery claim.

This module is intentionally pure.  It imports no project modules and performs
no database, filesystem, environment, or network operations.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Dict, Optional


GATEWAY_SCHEMA = "agent-gateway/1"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_EVENT_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_TEXT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_FRAMEWORK_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")


class FrameworkAdapterError(ValueError):
    """Raised when a framework payload does not satisfy the Gateway contract."""


# A short alias is useful to callers that treat all boundary failures as
# contract errors while retaining the more descriptive public class above.
AdapterContractError = FrameworkAdapterError


_EVENT_FIELDS = frozenset({
    "agent_id", "instance_id", "delivery_id", "event_type", "channel_id",
    "message_id", "payload", "payload_json", "idempotency_key",
    "attempt_count", "max_attempts", "status", "visibility_until",
    "fencing_token", "claim_token", "thread_type", "thread_id",
    "references", "message_type",
})
_MESSAGE_FIELDS = frozenset({
    "delivery_id", "event_type", "channel_id", "message_id", "body",
    "payload", "idempotency_key", "attempt_count", "max_attempts", "status",
    "thread_type", "thread_id", "references", "message_type",
})
_ACK_FIELDS = frozenset({
    "schema", "agent_id", "instance_id", "delivery_id", "claim_token",
    "success", "reason",
})
_FRAMEWORK_ENVELOPE_FIELDS = frozenset({
    "schema", "framework", "agent_id", "instance_id", "event", "message", "ack",
})
_SENSITIVE_JSON_KEYS = frozenset({
    "access_token", "api_key", "client_secret", "database_password",
    "credential", "enrollment_token", "password", "private_key",
    "refresh_token", "secret", "secret_digest",
})
_BOOTSTRAP_SCOPE_SET = frozenset({
    "channels.read", "channels.write", "barriers.arrive", "actions.propose",
    "events.read",
})
_RESPONSE_WRAPPER_FIELDS = frozenset({"status_code", "body"})


def _mapping(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FrameworkAdapterError(f"{name} must be an object")
    return dict(value)


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FrameworkAdapterError(f"{name} contains unauthorized fields: {', '.join(unknown)}")


def _identity(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise FrameworkAdapterError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise FrameworkAdapterError(f"{field} is required")
    if not _IDENTIFIER_PATTERN.fullmatch(result):
        raise FrameworkAdapterError(f"{field} is invalid")
    return result


def _text_id(value: Any, field: str, *, required: bool = False) -> Optional[str]:
    if value is None or value == "":
        if required:
            raise FrameworkAdapterError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise FrameworkAdapterError(f"{field} must be a string")
    result = value.strip()
    if not result:
        if required:
            raise FrameworkAdapterError(f"{field} is required")
        return None
    if not _TEXT_ID_PATTERN.fullmatch(result):
        raise FrameworkAdapterError(f"{field} is invalid")
    return result


def _event_type(value: Any) -> str:
    if not isinstance(value, str):
        raise FrameworkAdapterError("event_type must be a string")
    result = value.strip().upper()
    if not _EVENT_TYPE_PATTERN.fullmatch(result):
        raise FrameworkAdapterError("event_type is invalid")
    return result


def _optional_text(value: Any, field: str, *, max_length: int = 256) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise FrameworkAdapterError(f"{field} must be a string")
    result = value.strip()
    if not result:
        return None
    if len(result) > max_length or any(ord(char) < 32 for char in result):
        raise FrameworkAdapterError(f"{field} is invalid")
    return result


def _reject_sensitive_json(value: Any, field: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise FrameworkAdapterError(f"{field} keys must be strings")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _SENSITIVE_JSON_KEYS:
                raise FrameworkAdapterError(f"{field} contains a credential field")
            _reject_sensitive_json(nested, field)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_json(nested, field)


def _json_object(value: Any, field: str, *, reject_sensitive: bool = True) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FrameworkAdapterError(f"{field} must be a JSON object")
    if reject_sensitive:
        _reject_sensitive_json(value, field)
    try:
        # Round-trip to reject non-JSON values and avoid returning a caller's
        # mutable object through a supposedly pure boundary conversion.
        return json.loads(json.dumps(dict(value), ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as exc:
        raise FrameworkAdapterError(f"{field} must contain JSON values") from exc


def _ephemeral_secret(value: Any, field: str, *, minimum: int = 1, maximum: int = 10000) -> str:
    """Validate a secret transported once without retaining it."""
    if not isinstance(value, str):
        raise FrameworkAdapterError(f"{field} must be a string")
    result = value.strip()
    if len(result) < minimum or len(result) > maximum or any(ord(char) < 32 for char in result):
        raise FrameworkAdapterError(f"{field} is invalid")
    return result


def _path_id(value: Any, field: str) -> str:
    return _identity(value, field)


def _request(method: str, path: str, body: Mapping[str, Any], *, query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build a transport-neutral descriptor for an existing Gateway route."""
    try:
        copied_body = json.loads(json.dumps(dict(body), ensure_ascii=True, allow_nan=False))
        copied_query = json.loads(json.dumps(dict(query or {}), ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as exc:
        raise FrameworkAdapterError("request contains non-JSON values") from exc
    return {
        "schema": GATEWAY_SCHEMA,
        "method": method.upper(),
        "path": path,
        "query": copied_query,
        "body": copied_body,
    }


def _response_body(value: Mapping[str, Any], name: str) -> Dict[str, Any]:
    """Accept a direct Gateway body or a successful transport response wrapper."""
    raw = _mapping(value, name)
    if "status_code" in raw or ("body" in raw and set(raw) <= _RESPONSE_WRAPPER_FIELDS):
        _reject_unknown(raw, _RESPONSE_WRAPPER_FIELDS, name)
        status = raw.get("status_code", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
            raise FrameworkAdapterError(f"{name} status is not successful")
        return _mapping(raw.get("body"), f"{name}.body")
    return raw


def _expected_identity(expected: str, trusted: str, field: str) -> str:
    if expected and trusted and _identity(expected, field) != _identity(trusted, field):
        raise FrameworkAdapterError(f"trusted {field} values disagree")
    candidate = trusted or expected
    if not candidate:
        raise FrameworkAdapterError(f"trusted {field} is required")
    return _identity(candidate, f"trusted_{field}")


def _assert_response_identity(body: Mapping[str, Any], field: str, expected: str) -> str:
    actual = _identity(body.get(field), f"response.{field}")
    if actual != expected:
        raise FrameworkAdapterError(f"response {field} is not bound to the trusted context")
    return expected


def _runtime_name(value: Any, default: str) -> str:
    raw = _optional_text(value, "runtime", max_length=128)
    if raw is None:
        return normalize_framework_name(default)
    try:
        return normalize_framework_name(raw)
    except FrameworkAdapterError:
        # Keep versioned labels such as ``OpenClaw/1.2`` as metadata without
        # treating them as a new authorization mechanism.
        return raw


def _payload(event: Mapping[str, Any]) -> Dict[str, Any]:
    has_payload = "payload" in event
    has_payload_json = "payload_json" in event
    if not has_payload and not has_payload_json:
        raise FrameworkAdapterError("event requires payload or payload_json")
    if has_payload and has_payload_json and event.get("payload") is not None:
        left = _json_object(event["payload"], "payload")
        right = _parse_payload_json(event["payload_json"])
        if left != right:
            raise FrameworkAdapterError("payload and payload_json disagree")
        return left
    if has_payload and event.get("payload") is not None:
        return _json_object(event["payload"], "payload")
    return _parse_payload_json(event.get("payload_json"))


def _parse_payload_json(value: Any) -> Dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        raise FrameworkAdapterError("payload_json must be a non-empty JSON string")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FrameworkAdapterError("payload_json is invalid JSON") from exc
    return _json_object(decoded, "payload_json")


def _nonnegative_int(value: Any, field: str, *, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FrameworkAdapterError(f"{field} must be a non-negative integer")
    return value


def _message_fields(source: Mapping[str, Any], *, require_channel: bool, require_body: bool) -> Dict[str, Any]:
    _reject_unknown(source, _MESSAGE_FIELDS, "message")
    channel_id = _text_id(source.get("channel_id"), "message.channel_id", required=require_channel)
    body = source.get("body")
    if body is None or body == "":
        if require_body:
            raise FrameworkAdapterError("message.body is required")
    elif not isinstance(body, str) or not body.strip():
        raise FrameworkAdapterError("message.body must be a non-empty string")
    elif len(body) > 100000:
        raise FrameworkAdapterError("message.body is too large")

    result: Dict[str, Any] = {}
    for field in ("delivery_id", "message_id", "idempotency_key", "thread_id"):
        value = _text_id(source.get(field), f"message.{field}")
        if value is not None:
            result[field] = value
    event_type = source.get("event_type")
    if event_type is not None and event_type != "":
        result["event_type"] = _event_type(event_type)
    if channel_id is not None:
        result["channel_id"] = channel_id
    if body is not None and body != "":
        result["body"] = body

    thread_type = _optional_text(source.get("thread_type"), "message.thread_type", max_length=32)
    if thread_type is not None:
        result["thread_type"] = thread_type.upper()
    message_type = _optional_text(source.get("message_type"), "message.message_type", max_length=32)
    if message_type is not None:
        result["message_type"] = message_type.upper()
    references = source.get("references")
    if references is not None:
        result["references"] = _json_object(references, "message.references")
    if "payload" in source and source["payload"] is not None:
        result["payload"] = _json_object(source["payload"], "message.payload")
    for field in ("attempt_count", "max_attempts"):
        value = _nonnegative_int(source.get(field), f"message.{field}")
        if value is not None:
            result[field] = value
    status = _optional_text(source.get("status"), "message.status", max_length=32)
    if status is not None:
        result["status"] = status.upper()
    return result


def normalize_framework_name(name: str) -> str:
    """Return a stable lowercase framework identifier.

    Known aliases collapse to ``openclaw`` and ``hermes``.  Other framework
    names remain supported, but are limited to a safe ASCII identifier so this
    boundary cannot be used to smuggle paths, control characters, or markup.
    """
    if not isinstance(name, str):
        raise FrameworkAdapterError("framework name must be a string")
    if any(ord(char) < 32 for char in name):
        raise FrameworkAdapterError("framework name is invalid")
    raw = " ".join(name.strip().lower().replace("_", " ").split())
    aliases = {
        "openclaw": "openclaw",
        "open claw": "openclaw",
        "open-claw": "openclaw",
        "open claw agent": "openclaw",
        "hermes": "hermes",
        "hermes agent": "hermes",
        "hermes-agent": "hermes",
        "generic": "generic",
        "gateway": "generic",
        "framework neutral": "generic",
        "framework-neutral": "generic",
    }
    if raw in aliases:
        return aliases[raw]
    if not raw or not _FRAMEWORK_PATTERN.fullmatch(raw):
        raise FrameworkAdapterError("framework name is invalid")
    return raw.replace(" ", "-")


def _event_fields(event: Mapping[str, Any]) -> Dict[str, Any]:
    _reject_unknown(event, _EVENT_FIELDS, "event")
    agent_id = _identity(event.get("agent_id"), "agent_id")
    instance_id = _identity(event.get("instance_id"), "instance_id")
    delivery_id = _text_id(event.get("delivery_id"), "delivery_id", required=True)
    event_type = _event_type(event.get("event_type"))
    payload = _payload(event)
    result: Dict[str, Any] = {
        "agent_id": agent_id,
        "instance_id": instance_id,
        "delivery_id": delivery_id,
        "event_type": event_type,
        "payload": payload,
    }
    for field in ("channel_id", "message_id", "idempotency_key"):
        value = _text_id(event.get(field), field)
        if value is not None:
            result[field] = value
    for field in ("attempt_count", "max_attempts"):
        value = _nonnegative_int(event.get(field), field)
        if value is not None:
            result[field] = value
    status = _optional_text(event.get("status"), "status", max_length=32)
    if status is not None:
        result["status"] = status.upper()
    claim_token = _optional_text(event.get("claim_token"), "claim_token", max_length=512)
    if claim_token is not None:
        result["claim_token"] = claim_token
    thread_type = _optional_text(event.get("thread_type"), "thread_type", max_length=32)
    if thread_type is not None:
        result["thread_type"] = thread_type.upper()
    thread_id = _text_id(event.get("thread_id"), "thread_id")
    if thread_id is not None:
        result["thread_id"] = thread_id
    if event.get("references") is not None:
        result["references"] = _json_object(event["references"], "references")
    message_type = _optional_text(event.get("message_type"), "message_type", max_length=32)
    if message_type is not None:
        result["message_type"] = message_type.upper()
    if "fencing_token" in event:
        _nonnegative_int(event.get("fencing_token"), "fencing_token")
    if "visibility_until" in event:
        _optional_text(event.get("visibility_until"), "visibility_until", max_length=128)
    return result


def event_to_framework_message(event: Mapping[str, Any], framework: str = "generic") -> Dict[str, Any]:
    """Convert one claimed Gateway event into a framework-neutral message.

    ``payload_json`` is accepted because it is the durable Gateway storage
    representation.  Internal lease fields such as ``fencing_token`` and
    ``visibility_until`` are validated as known Gateway metadata but are never
    exposed in the returned framework envelope.
    """
    normalized = _event_fields(_mapping(event, "event"))
    framework_name = normalize_framework_name(framework)
    message_source: Dict[str, Any] = {
        key: normalized[key]
        for key in _MESSAGE_FIELDS
        if key in normalized
    }
    payload = normalized["payload"]
    if "body" not in message_source:
        for candidate in ("body", "body_text", "content"):
            if isinstance(payload.get(candidate), str) and payload[candidate].strip():
                message_source["body"] = payload[candidate]
                break
    message = _message_fields(message_source, require_channel=False, require_body=False)
    result: Dict[str, Any] = {
        "schema": GATEWAY_SCHEMA,
        "framework": framework_name,
        "agent_id": normalized["agent_id"],
        "instance_id": normalized["instance_id"],
        "event": {key: value for key, value in normalized.items()
                  if key not in {"agent_id", "instance_id", "claim_token", "thread_type", "thread_id", "references", "message_type"}},
        "message": message,
    }
    ack: Dict[str, Any] = {
        "schema": GATEWAY_SCHEMA,
        "agent_id": normalized["agent_id"],
        "instance_id": normalized["instance_id"],
        "delivery_id": normalized["delivery_id"],
    }
    if "claim_token" in normalized:
        ack["claim_token"] = normalized["claim_token"]
    result["ack"] = ack
    return result


def _framework_envelope(value: Mapping[str, Any]) -> Dict[str, Any]:
    envelope = _mapping(value, "framework message")
    _reject_unknown(envelope, _FRAMEWORK_ENVELOPE_FIELDS, "framework message")
    schema = envelope.get("schema")
    if schema is not None and schema != GATEWAY_SCHEMA:
        raise FrameworkAdapterError("framework message schema is unsupported")
    # These fields may be supplied as framework claims for observability, but
    # they are never an authorization source.  Gateway calls below use the
    # bearer-token context and intentionally omit them from request bodies.
    agent_id = _identity(envelope.get("agent_id"), "agent_id") if "agent_id" in envelope else None
    instance_id = _identity(envelope.get("instance_id"), "instance_id") if "instance_id" in envelope else None
    framework_value = envelope.get("framework", "generic")
    if not isinstance(framework_value, str):
        raise FrameworkAdapterError("framework name must be a string")
    framework = normalize_framework_name(framework_value or "generic")
    raw_message = envelope.get("message")
    if isinstance(raw_message, Mapping):
        message_source = dict(raw_message)
    elif isinstance(raw_message, str):
        message_source = {"body": raw_message}
    else:
        raise FrameworkAdapterError("framework message.message must be an object or string")
    message = _message_fields(message_source, require_channel=True, require_body=True)
    nested_event = envelope.get("event")
    if nested_event is not None:
        event_value = _mapping(nested_event, "framework message.event")
        _reject_unknown(event_value, _MESSAGE_FIELDS, "framework message.event")
        _text_id(event_value.get("delivery_id"), "event.delivery_id", required=True)
        _event_type(event_value.get("event_type"))
        if "payload" not in event_value:
            raise FrameworkAdapterError("event.payload is required")
        _json_object(event_value["payload"], "event.payload")
    nested_ack = envelope.get("ack")
    if nested_ack is not None:
        ack_value = _mapping(nested_ack, "framework message.ack")
        ack_to_gateway(ack_value)
    return {
        "schema": GATEWAY_SCHEMA,
        "framework": framework,
        "agent_id": agent_id,
        "instance_id": instance_id,
        "message": message,
        "event": nested_event,
        "ack": nested_ack,
    }


def framework_message_to_gateway(
    message: Mapping[str, Any],
    *,
    expected_agent_id: str = "",
    expected_instance_id: str = "",
    trusted_agent_id: str = "",
    trusted_instance_id: str = "",
) -> Dict[str, Any]:
    """Convert a framework message envelope to Gateway message request fields.

    The returned mapping is suitable for the Gateway's channel-message body.
    Client-supplied identity claims are discarded.  When a caller supplies a
    trusted identity, any claims in the framework envelope must match it; the
    authenticated Gateway context remains authoritative.
    """
    envelope = _framework_envelope(message)
    if expected_agent_id or trusted_agent_id:
        trusted_agent = _expected_identity(expected_agent_id, trusted_agent_id, "agent_id")
        if envelope["agent_id"] is not None and envelope["agent_id"] != trusted_agent:
            raise FrameworkAdapterError("framework agent_id is not bound to the trusted context")
    if expected_instance_id or trusted_instance_id:
        trusted_instance = _expected_identity(expected_instance_id, trusted_instance_id, "instance_id")
        if envelope["instance_id"] is not None and envelope["instance_id"] != trusted_instance:
            raise FrameworkAdapterError("framework instance_id is not bound to the trusted context")
    body = envelope["message"]
    result: Dict[str, Any] = {
        "channel_id": body["channel_id"],
        "body": body["body"],
    }
    for field in ("thread_type", "thread_id", "references", "message_type", "delivery_id", "event_type", "message_id", "idempotency_key"):
        if field in body:
            result[field] = body[field]
    return result


def ack_to_gateway(
    ack: Mapping[str, Any],
    *,
    expected_agent_id: str = "",
    expected_instance_id: str = "",
    trusted_agent_id: str = "",
    trusted_instance_id: str = "",
) -> Dict[str, Any]:
    """Validate an acknowledgement without trusting client identity claims."""
    value = _mapping(ack, "ack")
    _reject_unknown(value, _ACK_FIELDS, "ack")
    schema = value.get("schema")
    if schema is not None and schema != GATEWAY_SCHEMA:
        raise FrameworkAdapterError("ack schema is unsupported")
    claimed_agent = _identity(value.get("agent_id"), "agent_id") if "agent_id" in value else None
    claimed_instance = _identity(value.get("instance_id"), "instance_id") if "instance_id" in value else None
    if expected_agent_id or trusted_agent_id:
        expected_agent = _expected_identity(expected_agent_id, trusted_agent_id, "agent_id")
        if claimed_agent is not None and claimed_agent != expected_agent:
            raise FrameworkAdapterError("ack agent_id is not bound to the trusted context")
    if expected_instance_id or trusted_instance_id:
        expected_instance = _expected_identity(expected_instance_id, trusted_instance_id, "instance_id")
        if claimed_instance is not None and claimed_instance != expected_instance:
            raise FrameworkAdapterError("ack instance_id is not bound to the trusted context")
    result = {
        "delivery_id": _text_id(value.get("delivery_id"), "delivery_id", required=True),
        "claim_token": _optional_text(value.get("claim_token"), "claim_token", max_length=512),
        "success": value.get("success", True),
        "reason": _optional_text(value.get("reason"), "reason", max_length=2000) or "",
    }
    if not result["claim_token"]:
        raise FrameworkAdapterError("claim_token is required")
    if not isinstance(result["success"], bool):
        raise FrameworkAdapterError("success must be a boolean")
    return result


def _scope_list(scopes: Any) -> list[str]:
    if scopes is None:
        values = ["channels.read", "channels.write"]
    elif isinstance(scopes, (list, tuple, set, frozenset)):
        values = list(scopes)
    else:
        raise FrameworkAdapterError("scopes must be an array")
    normalized: set[str] = set()
    for scope in values:
        if not isinstance(scope, str):
            raise FrameworkAdapterError("scope must be a string")
        value = scope.strip().lower()
        if value not in _BOOTSTRAP_SCOPE_SET:
            raise FrameworkAdapterError("scope is not supported by the Gateway")
        normalized.add(value)
    if not normalized:
        raise FrameworkAdapterError("at least one scope is required")
    return sorted(normalized)


def _required_reason(value: Any, field: str = "reason") -> str:
    result = _optional_text(value, field, max_length=2000)
    if not result:
        raise FrameworkAdapterError(f"{field} is required")
    return result


def _required_idempotency(value: Any) -> str:
    result = _text_id(value, "idempotency_key", required=True)
    if result is None or len(result) < 8:
        raise FrameworkAdapterError("idempotency_key must contain at least 8 characters")
    return result


def build_registration_request(
    enrollment_token: str,
    *,
    framework: str = "generic",
    runtime: str = "",
    agent_id: str = "",
    environment: str = "development",
    node_id: str = "",
    public_key: str = "",
) -> Dict[str, Any]:
    """Build the one-time Enrollment request used by OpenClaw or Hermes.

    The token is a one-use enrollment capability, not a database credential.
    This function neither persists it nor accepts a client secret; the Gateway
    generates or records only its digest and returns a compatibility credential
    once when the configured enrollment policy requires one.
    """
    body: Dict[str, Any] = {
        "enrollment_token": _ephemeral_secret(enrollment_token, "enrollment_token", minimum=20, maximum=512),
        "runtime": _runtime_name(runtime, framework),
        "environment": _optional_text(environment, "environment", max_length=64) or "development",
    }
    requested_agent = _text_id(agent_id, "agent_id")
    if requested_agent is not None:
        body["agent_id"] = requested_agent
    requested_node = _text_id(node_id, "node_id")
    if requested_node is not None:
        body["node_id"] = requested_node
    key = _optional_text(public_key, "public_key", max_length=10000)
    if key is not None:
        if "PRIVATE KEY" in key.upper():
            raise FrameworkAdapterError("public_key must not contain a private key")
        body["public_key"] = key
    return _request("POST", "/api/enrollment/redeem", body)


def build_token_request(
    agent_id: str,
    credential: str = "",
    *,
    instance_id: str = "",
    public_key: str = "",
    signature: str = "",
    challenge: str = "",
    channel_id: str = "",
    security_domain_id: str = "",
    node_id: str = "",
    scopes: Any = None,
) -> Dict[str, Any]:
    """Build the bootstrap exchange for an instance-scoped access token.

    A compatibility client secret is accepted only as a transient function
    argument and is copied into the outbound body once.  The adapter has no
    cache, file, global, or credential field.  Ed25519 callers can avoid a
    shared secret by supplying the public-key proof tuple instead.
    """
    body: Dict[str, Any] = {"agent_id": _identity(agent_id, "agent_id"), "scopes": _scope_list(scopes)}
    has_secret = bool(credential)
    has_proof = bool(public_key or signature or challenge)
    if has_secret and has_proof:
        raise FrameworkAdapterError("choose a client secret or an Ed25519 proof")
    if has_secret:
        body["client_secret"] = _ephemeral_secret(credential, "client_secret", minimum=8, maximum=512)
    elif has_proof:
        key = _ephemeral_secret(public_key, "public_key", minimum=8, maximum=10000)
        if "PRIVATE KEY" in key.upper():
            raise FrameworkAdapterError("public_key must not contain a private key")
        body["public_key"] = key
        body["signature"] = _ephemeral_secret(signature, "signature", minimum=8, maximum=10000)
        body["challenge"] = _ephemeral_secret(challenge, "challenge", minimum=8, maximum=512)
    else:
        raise FrameworkAdapterError("a client secret or an Ed25519 proof is required")
    optional_ids = (
        ("instance_id", instance_id),
        ("channel_id", channel_id),
        ("security_domain_id", security_domain_id),
        ("node_id", node_id),
    )
    for field, value in optional_ids:
        normalized = _text_id(value, field)
        if normalized is not None:
            body[field] = normalized
    return _request("POST", "/api/gateway/token", body)


build_access_token_request = build_token_request


def build_instance_request(
    *,
    channel_id: str = "",
    security_domain_id: str = "",
    node_id: str = "",
) -> Dict[str, Any]:
    """Build an instance request whose Agent identity comes from the token."""
    channel = _text_id(channel_id, "channel_id")
    domain = _text_id(security_domain_id, "security_domain_id")
    if channel is None and domain is None:
        raise FrameworkAdapterError("channel_id or security_domain_id is required")
    body: Dict[str, Any] = {}
    for field, value in (("channel_id", channel), ("security_domain_id", domain), ("node_id", _text_id(node_id, "node_id"))):
        if value is not None:
            body[field] = value
    return _request("POST", "/api/gateway/instances", body)


def build_pull_request(*, limit: int = 50) -> Dict[str, Any]:
    """Build a pull claim request; identity is resolved from the bearer token."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise FrameworkAdapterError("limit must be an integer between 1 and 100")
    return _request("POST", "/api/gateway/events/claim", {}, query={"limit": limit})


def build_ack_request(
    delivery_id: str,
    claim_token: str,
    *,
    success: bool = True,
    reason: str = "",
) -> Dict[str, Any]:
    """Build a fenced acknowledgement for one claimed delivery."""
    if not isinstance(success, bool):
        raise FrameworkAdapterError("success must be a boolean")
    body: Dict[str, Any] = {
        "claim_token": _ephemeral_secret(claim_token, "claim_token", minimum=8, maximum=512),
        "success": success,
    }
    normalized_reason = _optional_text(reason, "reason", max_length=2000)
    if normalized_reason is not None:
        body["reason"] = normalized_reason
    return _request("POST", f"/api/gateway/events/{_path_id(delivery_id, 'delivery_id')}/ack", body)


def build_arrival_request(
    barrier_id: str,
    report: Mapping[str, Any],
    *,
    participant_role: str = "MEMBER",
    idempotency_key: str,
) -> Dict[str, Any]:
    """Build a structured, idempotent Barrier Arrival Report."""
    normalized_report = _json_object(report, "report")
    if not normalized_report:
        raise FrameworkAdapterError("report must not be empty")
    role = _optional_text(participant_role, "participant_role", max_length=64)
    if not role:
        raise FrameworkAdapterError("participant_role is required")
    return _request(
        "POST",
        f"/api/gateway/barriers/{_path_id(barrier_id, 'barrier_id')}/arrivals",
        {"report": normalized_report, "participant_role": role.upper(), "idempotency_key": _required_idempotency(idempotency_key)},
    )


def build_action_request(
    channel_id: str,
    action_type: str,
    payload: Mapping[str, Any],
    *,
    reason: str,
    idempotency_key: str,
) -> Dict[str, Any]:
    """Build a proposal; ordinary Channel text cannot execute an Action."""
    action = _optional_text(action_type, "action_type", max_length=64)
    if not action:
        raise FrameworkAdapterError("action_type is required")
    return _request(
        "POST",
        f"/api/gateway/channels/{_path_id(channel_id, 'channel_id')}/actions",
        {
            "action_type": action,
            "payload": _json_object(payload, "payload"),
            "reason": _required_reason(reason),
            "idempotency_key": _required_idempotency(idempotency_key),
        },
    )


def validate_registration_response(
    response: Mapping[str, Any],
    *,
    expected_runtime: str = "",
    expected_environment: str = "",
) -> Dict[str, Any]:
    """Validate the server result of one-time Agent Enrollment."""
    body = _response_body(response, "registration response")
    allowed = frozenset({
        "agent_id", "status", "owner_principal_id", "sponsor_principal_id",
        "responsible_group_id", "credential_type", "credential",
        "security_domain_id", "environment", "runtime",
    })
    _reject_unknown(body, allowed, "registration response")
    agent_id = _identity(body.get("agent_id"), "response.agent_id")
    status = _optional_text(body.get("status"), "response.status", max_length=32)
    if status is None or status.upper() not in {"ACTIVE", "PENDING_CONFIRMATION"}:
        raise FrameworkAdapterError("registration response status is invalid")
    owner = _identity(body.get("owner_principal_id"), "response.owner_principal_id")
    sponsor = _identity(body.get("sponsor_principal_id"), "response.sponsor_principal_id")
    credential_type = _optional_text(body.get("credential_type"), "response.credential_type", max_length=32)
    if credential_type is None or credential_type.upper() not in {"CLIENT_SECRET", "ED25519"}:
        raise FrameworkAdapterError("registration response credential type is invalid")
    credential = body.get("credential")
    if credential_type.upper() == "CLIENT_SECRET":
        credential = _ephemeral_secret(credential, "response.credential", minimum=8, maximum=512)
    elif credential not in (None, ""):
        raise FrameworkAdapterError("Ed25519 registration must not return a client secret")
    runtime = _optional_text(body.get("runtime"), "response.runtime", max_length=128)
    environment = _optional_text(body.get("environment"), "response.environment", max_length=64)
    if expected_runtime and runtime != _runtime_name(expected_runtime, "generic"):
        raise FrameworkAdapterError("registration response runtime is not bound to the request")
    if expected_environment and environment != _optional_text(expected_environment, "environment", max_length=64):
        raise FrameworkAdapterError("registration response environment is not bound to the request")
    result: Dict[str, Any] = {
        "agent_id": agent_id,
        "status": status.upper(),
        "owner_principal_id": owner,
        "sponsor_principal_id": sponsor,
        "credential_type": credential_type.upper(),
        "credential": credential if credential is not None else None,
    }
    for field in ("responsible_group_id", "security_domain_id"):
        value = _text_id(body.get(field), f"response.{field}")
        if value is not None:
            result[field] = value
    if runtime is not None:
        result["runtime"] = runtime
    if environment is not None:
        result["environment"] = environment
    return result


def validate_token_response(
    response: Mapping[str, Any],
    expected_agent_id: str = "",
    expected_instance_id: str = "",
    *,
    trusted_agent_id: str = "",
    trusted_instance_id: str = "",
) -> Dict[str, Any]:
    """Validate an instance-scoped bearer token without accepting its identity."""
    body = _response_body(response, "token response")
    allowed = frozenset({"access_token", "agent_id", "instance_id", "scopes", "expires_at"})
    _reject_unknown(body, allowed, "token response")
    agent = _expected_identity(expected_agent_id, trusted_agent_id, "agent_id")
    instance = _expected_identity(expected_instance_id, trusted_instance_id, "instance_id")
    _assert_response_identity(body, "agent_id", agent)
    _assert_response_identity(body, "instance_id", instance)
    token = _ephemeral_secret(body.get("access_token"), "response.access_token", minimum=8, maximum=512)
    if "scopes" not in body:
        raise FrameworkAdapterError("token response scopes are required")
    scopes = _scope_list(body.get("scopes"))
    expires_at = _optional_text(body.get("expires_at"), "response.expires_at", max_length=128)
    if not expires_at:
        raise FrameworkAdapterError("token response expiry is required")
    return {"access_token": token, "agent_id": agent, "instance_id": instance, "scopes": scopes, "expires_at": expires_at}


validate_access_token_response = validate_token_response


def validate_instance_response(
    response: Mapping[str, Any],
    expected_agent_id: str = "",
    *,
    trusted_agent_id: str = "",
) -> Dict[str, Any]:
    """Validate an instance response against a trusted Agent binding."""
    body = _response_body(response, "instance response")
    allowed = frozenset({"instance_id", "agent_id", "channel_id", "security_domain_id", "classification", "status"})
    _reject_unknown(body, allowed, "instance response")
    agent = _expected_identity(expected_agent_id, trusted_agent_id, "agent_id")
    _assert_response_identity(body, "agent_id", agent)
    instance = _identity(body.get("instance_id"), "response.instance_id")
    status = _optional_text(body.get("status"), "response.status", max_length=32)
    if status is None or status.upper() != "ACTIVE":
        raise FrameworkAdapterError("instance response is not active")
    result: Dict[str, Any] = {"instance_id": instance, "agent_id": agent, "status": status.upper()}
    for field in ("channel_id", "security_domain_id"):
        value = _text_id(body.get(field), f"response.{field}")
        if value is not None:
            result[field] = value
    classification = _optional_text(body.get("classification"), "response.classification", max_length=32)
    if classification is not None:
        result["classification"] = classification.upper()
    return result


def validate_pull_response(
    response: Mapping[str, Any],
    expected_agent_id: str = "",
    expected_instance_id: str = "",
    *,
    framework: str = "generic",
    trusted_agent_id: str = "",
    trusted_instance_id: str = "",
) -> Dict[str, Any]:
    """Validate and convert claimed events for an OpenClaw/Hermes runtime."""
    body = _response_body(response, "pull response")
    allowed = frozenset({"items", "count", "agent_id", "instance_id"})
    _reject_unknown(body, allowed, "pull response")
    agent = _expected_identity(expected_agent_id, trusted_agent_id, "agent_id")
    instance = _expected_identity(expected_instance_id, trusted_instance_id, "instance_id")
    _assert_response_identity(body, "agent_id", agent)
    _assert_response_identity(body, "instance_id", instance)
    items = body.get("items")
    if not isinstance(items, list) or len(items) > 100:
        raise FrameworkAdapterError("pull response items must be an array of at most 100 events")
    count = _nonnegative_int(body.get("count"), "response.count")
    if count is None or count != len(items):
        raise FrameworkAdapterError("pull response count is inconsistent")
    normalized_items: list[Dict[str, Any]] = []
    for item in items:
        event = _mapping(item, "pull response item")
        if "agent_id" in event and _identity(event.get("agent_id"), "event.agent_id") != agent:
            raise FrameworkAdapterError("event agent_id is not bound to the trusted context")
        if "instance_id" in event and _identity(event.get("instance_id"), "event.instance_id") != instance:
            raise FrameworkAdapterError("event instance_id is not bound to the trusted context")
        event["agent_id"] = agent
        event["instance_id"] = instance
        normalized_items.append(event_to_framework_message(event, framework))
    return {"schema": GATEWAY_SCHEMA, "framework": normalize_framework_name(framework), "agent_id": agent, "instance_id": instance, "items": normalized_items, "count": len(normalized_items)}


def validate_ack_response(response: Mapping[str, Any], expected_delivery_id: str) -> Dict[str, Any]:
    """Validate the committed result of a delivery acknowledgement."""
    body = _response_body(response, "ack response")
    _reject_unknown(body, frozenset({"success", "delivery_id"}), "ack response")
    delivery = _path_id(expected_delivery_id, "expected_delivery_id")
    if _path_id(body.get("delivery_id"), "response.delivery_id") != delivery:
        raise FrameworkAdapterError("ack response delivery_id is not bound to the request")
    if not isinstance(body.get("success"), bool):
        raise FrameworkAdapterError("ack response success must be a boolean")
    return {"success": body["success"], "delivery_id": delivery}


def validate_arrival_response(response: Mapping[str, Any], expected_barrier_id: str) -> Dict[str, Any]:
    """Validate the durable, idempotent result of a Barrier arrival."""
    body = _response_body(response, "arrival response")
    _reject_unknown(body, frozenset({"arrival_id", "barrier_id", "status", "report_digest", "idempotent"}), "arrival response")
    barrier = _path_id(expected_barrier_id, "expected_barrier_id")
    if _path_id(body.get("barrier_id"), "response.barrier_id") != barrier:
        raise FrameworkAdapterError("arrival response barrier_id is not bound to the request")
    arrival = _identity(body.get("arrival_id"), "response.arrival_id")
    status = _optional_text(body.get("status"), "response.status", max_length=32)
    digest = body.get("report_digest")
    if not status or status.upper() not in {"WAITING", "READY"} or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise FrameworkAdapterError("arrival response is invalid")
    idempotent = body.get("idempotent", False)
    if not isinstance(idempotent, bool):
        raise FrameworkAdapterError("arrival response idempotent must be a boolean")
    return {"arrival_id": arrival, "barrier_id": barrier, "status": status.upper(), "report_digest": digest.lower(), "idempotent": idempotent}


def validate_action_response(
    response: Mapping[str, Any],
    expected_channel_id: str,
    expected_action_type: str = "",
) -> Dict[str, Any]:
    """Validate an Action Card proposal result; it is not execution approval."""
    body = _response_body(response, "action response")
    allowed = frozenset({
        "action_id", "channel_id", "action_type", "version", "payload", "payload_json",
        "status", "reason", "idempotent", "created_at",
    })
    _reject_unknown(body, allowed, "action response")
    channel = _path_id(expected_channel_id, "expected_channel_id")
    if _path_id(body.get("channel_id"), "response.channel_id") != channel:
        raise FrameworkAdapterError("action response channel_id is not bound to the request")
    action_id = _identity(body.get("action_id"), "response.action_id")
    action_type = _optional_text(body.get("action_type"), "response.action_type", max_length=64)
    if not action_type:
        raise FrameworkAdapterError("action response action_type is required")
    if expected_action_type:
        expected_action = _optional_text(expected_action_type, "expected_action_type", max_length=64)
        if not expected_action or action_type.upper() != expected_action.upper():
            raise FrameworkAdapterError("action response action_type is not bound to the request")
    status = _optional_text(body.get("status"), "response.status", max_length=32)
    if not status or status.upper() not in {"PROPOSED", "CONFIRMED", "REJECTED", "CANCELLED"}:
        raise FrameworkAdapterError("action response status is required")
    payload: Dict[str, Any]
    if body.get("payload") is not None and body.get("payload_json") is not None:
        payload = _json_object(body["payload"], "response.payload")
        if payload != _parse_payload_json(body["payload_json"]):
            raise FrameworkAdapterError("action response payloads disagree")
    elif body.get("payload") is not None:
        payload = _json_object(body["payload"], "response.payload")
    elif body.get("payload_json") is not None:
        payload = _parse_payload_json(body["payload_json"])
    else:
        payload = {}
    version = _nonnegative_int(body.get("version"), "response.version")
    idempotent = body.get("idempotent", False)
    if not isinstance(idempotent, bool):
        raise FrameworkAdapterError("action response idempotent must be a boolean")
    result: Dict[str, Any] = {
        "action_id": action_id,
        "channel_id": channel,
        "action_type": action_type,
        "status": status.upper(),
        "payload": payload,
        "idempotent": idempotent,
    }
    if version is not None:
        result["version"] = version
    reason = _optional_text(body.get("reason"), "response.reason", max_length=2000)
    if reason is not None:
        result["reason"] = reason
    created_at = _optional_text(body.get("created_at"), "response.created_at", max_length=128)
    if created_at is not None:
        result["created_at"] = created_at
    return result


class FrameworkGatewayAdapter:
    """Stateless facade shared by OpenClaw, Hermes, and generic runtimes."""

    __slots__ = ("framework",)

    def __init__(self, framework: str = "generic") -> None:
        self.framework = normalize_framework_name(framework)

    def event_to_message(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        return event_to_framework_message(event, self.framework)

    def message_to_gateway(self, message: Mapping[str, Any], **trusted: str) -> Dict[str, Any]:
        return framework_message_to_gateway(message, **trusted)

    def registration_request(self, enrollment_token: str, **kwargs: Any) -> Dict[str, Any]:
        return build_registration_request(enrollment_token, framework=self.framework, **kwargs)

    def token_request(self, agent_id: str, credential: str = "", **kwargs: Any) -> Dict[str, Any]:
        return build_token_request(agent_id, credential, **kwargs)

    def instance_request(self, **kwargs: Any) -> Dict[str, Any]:
        return build_instance_request(**kwargs)

    def pull_request(self, **kwargs: Any) -> Dict[str, Any]:
        return build_pull_request(**kwargs)

    def ack_request(self, delivery_id: str, claim_token: str, **kwargs: Any) -> Dict[str, Any]:
        return build_ack_request(delivery_id, claim_token, **kwargs)

    def arrival_request(self, barrier_id: str, report: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return build_arrival_request(barrier_id, report, **kwargs)

    def action_request(self, channel_id: str, action_type: str, payload: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return build_action_request(channel_id, action_type, payload, **kwargs)

    def validate_registration(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_registration_response(response, **kwargs)

    def validate_token(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_token_response(response, **kwargs)

    def validate_instance(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_instance_response(response, **kwargs)

    def validate_pull(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_pull_response(response, framework=self.framework, **kwargs)

    def validate_ack(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_ack_response(response, **kwargs)

    def validate_arrival(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_arrival_response(response, **kwargs)

    def validate_action(self, response: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return validate_action_response(response, **kwargs)


class OpenClawGatewayAdapter(FrameworkGatewayAdapter):
    def __init__(self) -> None:
        super().__init__("openclaw")


class HermesGatewayAdapter(FrameworkGatewayAdapter):
    def __init__(self) -> None:
        super().__init__("hermes")


OpenClawAdapter = OpenClawGatewayAdapter
HermesAdapter = HermesGatewayAdapter
FrameworkNeutralGatewayAdapter = FrameworkGatewayAdapter


def create_gateway_adapter(framework: str = "generic") -> FrameworkGatewayAdapter:
    normalized = normalize_framework_name(framework)
    if normalized == "openclaw":
        return OpenClawGatewayAdapter()
    if normalized == "hermes":
        return HermesGatewayAdapter()
    return FrameworkGatewayAdapter(normalized)


__all__ = [
    "AdapterContractError",
    "FrameworkGatewayAdapter",
    "FrameworkNeutralGatewayAdapter",
    "FrameworkAdapterError",
    "GATEWAY_SCHEMA",
    "HermesAdapter",
    "HermesGatewayAdapter",
    "OpenClawAdapter",
    "OpenClawGatewayAdapter",
    "ack_to_gateway",
    "build_access_token_request",
    "build_action_request",
    "build_arrival_request",
    "build_ack_request",
    "build_instance_request",
    "build_pull_request",
    "build_registration_request",
    "build_token_request",
    "create_gateway_adapter",
    "event_to_framework_message",
    "framework_message_to_gateway",
    "normalize_framework_name",
    "validate_access_token_response",
    "validate_action_response",
    "validate_arrival_response",
    "validate_ack_response",
    "validate_instance_response",
    "validate_pull_response",
    "validate_registration_response",
    "validate_token_response",
]
