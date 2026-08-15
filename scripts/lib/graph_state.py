"""Typed Graph State, scope, reducer, and artifact-reference helpers."""

from __future__ import annotations

import hashlib
import json
import base64
import math
import os
import re
from hmac import compare_digest
from typing import Any, Dict, Iterable, List, Optional, Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


STATE_SCOPES = frozenset({"GRAPH_SHARED", "BRANCH_LOCAL", "NODE_PRIVATE", "SECRET"})
REDUCERS = frozenset({"REPLACE", "APPEND", "SET_UNION", "SUM", "FIRST", "LAST"})
DEFAULT_MAX_RESULT_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 50 * 1024 * 1024
SENSITIVE_KEY_TOKENS = frozenset({
    "secret", "password", "token", "credential", "api_key", "apikey",
    "access_key", "private_key", "authorization", "cookie",
})
STATE_CODEC_PREFIX = "aigstate:v1:"
STATE_CODEC_FORMAT = "GRAPH_STATE_AES_GCM"
STATE_CODEC_AAD = b"ai-agent-infra:graph-state:v1"
STATE_KEY_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _key_bytes(value: bytes) -> bytes:
    """Normalize a key without ever serializing the key into state."""
    if not isinstance(value, bytes) or len(value) < 16:
        raise ValueError("Graph State key must contain at least 16 bytes")
    if len(value) not in (16, 24, 32):
        return hashlib.sha256(value).digest()
    return value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))


class StateKeyring:
    """Versioned AES-GCM keyring for SECRET Graph State fields.

    The envelope carries only the key version, nonce, and ciphertext.  Key
    material is supplied by the process or a secret manager and is never
    written to a checkpoint, trace, API response, or error message.
    """

    def __init__(self, keys: Dict[str, bytes], active_version: str):
        normalized = {}
        for version, key in (keys or {}).items():
            version = str(version)
            if not STATE_KEY_VERSION_PATTERN.fullmatch(version):
                raise ValueError(f"invalid Graph State key version: {version}")
            normalized[version] = _key_bytes(key)
        active_version = str(active_version or "")
        if active_version not in normalized:
            raise ValueError("active Graph State key version is not present")
        self._keys = normalized
        self.active_version = active_version

    @classmethod
    def from_environment(cls, environ: Optional[Dict[str, str]] = None) -> "StateKeyring":
        """Build a keyring from the existing master key and optional old keys.

        ``GRAPH_STATE_KEYS_JSON`` is a map of version to base64 key.  The
        current ``MASTER_DB_KEY``/local master key is installed under
        ``GRAPH_STATE_KEY_VERSION`` and old versions remain available for
        decrypting state during a controlled rotation window.
        """
        # An explicitly supplied empty mapping is useful in tests and in a
        # controlled bootstrap.  Falling back on the process environment in
        # that case makes key rotation depend on ambient state.
        env = environ if environ is not None else os.environ
        from .connection_crypto import get_master_key

        active = str(env.get("GRAPH_STATE_KEY_VERSION") or "1")
        keys: Dict[str, bytes] = {active: get_master_key()}
        raw = env.get("GRAPH_STATE_KEYS_JSON")
        if raw:
            try:
                configured = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("GRAPH_STATE_KEYS_JSON is not valid JSON") from exc
            if not isinstance(configured, dict):
                raise ValueError("GRAPH_STATE_KEYS_JSON must be an object")
            for version, encoded in configured.items():
                try:
                    keys[str(version)] = base64.b64decode(str(encoded), validate=True)
                except Exception as exc:
                    raise ValueError(f"invalid Graph State key for version {version}") from exc
        return cls(keys, active)

    def add_key(self, version: str, key: bytes, *, make_active: bool = False) -> None:
        version = str(version)
        if not STATE_KEY_VERSION_PATTERN.fullmatch(version):
            raise ValueError(f"invalid Graph State key version: {version}")
        self._keys[version] = _key_bytes(key)
        if make_active:
            self.active_version = version

    def has_key(self, version: str) -> bool:
        """Return whether a retained key version can decrypt historical state."""
        return str(version or "") in self._keys

    def remove_key(self, version: str) -> None:
        """Retire an old key only after callers have completed retention checks."""
        version = str(version or "")
        if version == self.active_version:
            raise ValueError("the active Graph State key cannot be retired")
        if version not in self._keys:
            return
        del self._keys[version]

    def versions(self) -> List[str]:
        return sorted(self._keys)

    def encode(self, value: Any, *, aad: str = "", key_version: Optional[str] = None) -> str:
        version = str(key_version or self.active_version)
        key = self._keys.get(version)
        if key is None:
            raise KeyError(f"Graph State key version is unavailable: {version}")
        nonce = os.urandom(12)
        associated_data = STATE_CODEC_AAD + b":" + str(aad).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(
            nonce,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            associated_data,
        )
        envelope = {
            "format": STATE_CODEC_FORMAT,
            "key_version": version,
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }
        return STATE_CODEC_PREFIX + _b64(_canonical(envelope).encode("utf-8"))

    def decode(self, encoded: str, *, aad: str = "") -> Any:
        if not isinstance(encoded, str) or not encoded.startswith(STATE_CODEC_PREFIX):
            raise ValueError("value is not a Graph State envelope")
        try:
            envelope = json.loads(_unb64(encoded[len(STATE_CODEC_PREFIX):]).decode("utf-8"))
            if envelope.get("format") != STATE_CODEC_FORMAT:
                raise ValueError("unsupported Graph State envelope")
            version = str(envelope["key_version"])
            key = self._keys.get(version)
            if key is None:
                raise KeyError(f"Graph State key version is unavailable: {version}")
            plaintext = AESGCM(key).decrypt(
                _unb64(envelope["nonce"]), _unb64(envelope["ciphertext"]),
                STATE_CODEC_AAD + b":" + str(aad).encode("utf-8"),
            )
            return json.loads(plaintext.decode("utf-8"))
        except InvalidTag as exc:
            raise ValueError("Graph State authentication failed") from exc
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            if isinstance(exc, KeyError):
                raise
            raise ValueError("invalid Graph State envelope") from exc

    def rotate(self, encoded: str, *, aad: str = "", new_version: Optional[str] = None) -> str:
        value = self.decode(encoded, aad=aad)
        version = str(new_version or self.active_version)
        if version not in self._keys:
            raise KeyError(f"Graph State key version is unavailable: {version}")
        return self.encode(value, aad=aad, key_version=version)


def is_state_envelope(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(STATE_CODEC_PREFIX)


def _field_spec(fields: Optional[Dict[str, Dict[str, Any]]], path: str, key: Any) -> Dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    return fields.get(path) or fields.get(str(key)) or {}


def encode_secret_state(value: Any, fields: Optional[Dict[str, Dict[str, Any]]] = None,
                        keyring: Optional[StateKeyring] = None, path: str = "") -> Any:
    """Encrypt declared SECRET fields recursively, preserving other fields."""
    if keyring is None:
        keyring = StateKeyring.from_environment()
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            spec = _field_spec(fields, child_path, key)
            if str(spec.get("scope") or "").upper() == "SECRET" or _is_sensitive_key(key):
                result[key] = child if is_state_envelope(child) else keyring.encode(child, aad=child_path)
            else:
                result[key] = encode_secret_state(child, fields, keyring, child_path)
        return result
    if isinstance(value, list):
        return [encode_secret_state(item, fields, keyring, f"{path}[{index}]")
                for index, item in enumerate(value)]
    return value


def decode_secret_state(value: Any, keyring: StateKeyring, *, allow_secrets: bool = False,
                        path: str = "") -> Any:
    """Decode only for an explicitly authorized consumer; otherwise redact."""
    if is_state_envelope(value):
        if not allow_secrets:
            return "[REDACTED]"
        return decode_secret_state(keyring.decode(value, aad=path), keyring,
                                   allow_secrets=True, path=path)
    if isinstance(value, dict):
        return {key: decode_secret_state(child, keyring, allow_secrets=allow_secrets,
                                          path=f"{path}.{key}" if path else str(key))
                for key, child in value.items()}
    if isinstance(value, list):
        return [decode_secret_state(item, keyring, allow_secrets=allow_secrets,
                                    path=str(path) + "[" + str(index) + "]") for index, item in enumerate(value)]
    return value


def rotate_secret_state(value: Any, old_keyring: StateKeyring, new_keyring: StateKeyring,
                        *, path: str = "") -> Any:
    """Rotate every encrypted field without exposing its plaintext to callers."""
    if is_state_envelope(value):
        return new_keyring.encode(old_keyring.decode(value, aad=path), aad=path)
    if isinstance(value, dict):
        return {key: rotate_secret_state(child, old_keyring, new_keyring,
                                          path=f"{path}.{key}" if path else str(key))
                for key, child in value.items()}
    if isinstance(value, list):
        return [rotate_secret_state(item, old_keyring, new_keyring,
                                    path=str(path) + "[" + str(index) + "]") for index, item in enumerate(value)]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def validate_schema(value: Any, schema: Dict[str, Any], path: str = "state") -> List[Dict[str, Any]]:
    """Validate the portable JSON Schema subset used by Graph State."""
    errors: List[Dict[str, Any]] = []
    schema = schema or {}
    if isinstance(value, float) and not math.isfinite(value):
        return [{"path": path, "code": "NONFINITE_NUMBER"}]
    expected = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool), "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if expected in type_ok and not type_ok[expected]:
        return [{"path": path, "code": "TYPE_MISMATCH", "expected": expected}]
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                errors.append({"path": f"{path}.{required}", "code": "REQUIRED_FIELD_MISSING"})
        for key, child_schema in (schema.get("properties") or {}).items():
            if key in value:
                errors.extend(validate_schema(value[key], child_schema or {}, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            properties = schema.get("properties") or {}
            for key in sorted(set(value) - set(properties)):
                errors.append({
                    "path": f"{path}.{key}",
                    "code": "ADDITIONAL_PROPERTY_FORBIDDEN",
                })
    if isinstance(value, list) and schema.get("items"):
        for index, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{index}]"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"path": path, "code": "ENUM_VALUE_INVALID"})
    return errors


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key or "").lower()
    return any(token in lowered for token in SENSITIVE_KEY_TOKENS)


def _redact_value(value: Any, fields: Optional[Dict[str, Dict[str, Any]]] = None,
                  allow_secrets: bool = False, field: Optional[Dict[str, Any]] = None,
                  key: Optional[str] = None, path: str = "") -> Any:
    field = field or {}
    secret = str(field.get("scope") or "").upper() == "SECRET" or _is_sensitive_key(key)
    if secret and not allow_secrets:
        return "[REDACTED]"
    if isinstance(value, dict):
        result = {}
        for child_key, child_value in value.items():
            child_path = f"{path}.{child_key}" if path else str(child_key)
            child_field = _field_spec(fields, child_path, child_key)
            result[child_key] = _redact_value(
                child_value, fields, allow_secrets, child_field, str(child_key), child_path
            )
        return result
    if isinstance(value, list):
        return [_redact_value(item, fields, allow_secrets, path= f"{path}[{index}]")
                for index, item in enumerate(value)]
    return value


def validate_scopes(fields: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    errors = []
    for name, spec in fields.items():
        scope = str(spec.get("scope") or "").upper()
        if scope not in STATE_SCOPES:
            errors.append({"field": name, "code": "STATE_SCOPE_INVALID", "scope": scope})
        if scope == "SECRET" and spec.get("output_visible") is True:
            errors.append({"field": name, "code": "SECRET_OUTPUT_FORBIDDEN"})
    return errors


def redact_state(state: Any, fields: Optional[Dict[str, Dict[str, Any]]] = None,
                 allow_secrets: bool = False) -> Any:
    return _redact_value(state, fields, allow_secrets)


def _set_path(target: Dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        return
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _get_path(source: Dict[str, Any], path: str) -> Any:
    current: Any = source
    for part in [part for part in str(path).split(".") if part]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def project_state(state: Any, input_schema: Optional[Dict[str, Any]] = None,
                  resource_scope: Optional[Dict[str, Any]] = None,
                  fields: Optional[Dict[str, Dict[str, Any]]] = None) -> tuple[Any, List[Dict[str, Any]]]:
    """Project only the state a node is allowed to see.

    ``state_fields`` is an explicit allow-list.  When it is absent, a node
    with declared input properties receives those properties only; legacy
    nodes with an empty schema retain their v4.1-compatible state view.  The
    result is always recursively redacted before it can cross the Worker
    boundary.
    """
    source = state if isinstance(state, dict) else {}
    schema = input_schema if isinstance(input_schema, dict) else {}
    scope = resource_scope if isinstance(resource_scope, dict) else {}
    configured = scope.get("state_fields", scope.get("allowed_state_fields"))
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if configured == "*":
        allowed: Optional[Sequence[str]] = None
    elif isinstance(configured, dict):
        allowed = list(configured.keys())
    elif isinstance(configured, (list, tuple, set)):
        allowed = [str(item) for item in configured]
    elif properties:
        allowed = list(properties.keys())
    else:
        allowed = None

    if allowed is None:
        projected = dict(source)
    else:
        projected = {}
        for path in allowed:
            value = _get_path(source, str(path))
            if value is not None:
                _set_path(projected, str(path), value)
    safe = redact_state(projected, fields=fields, allow_secrets=False)
    return safe, validate_schema(safe, schema, path="input")


def json_size_bytes(value: Any) -> int:
    return len(_canonical(value).encode("utf-8"))


def validate_artifact_references(value: Any, path: str = "output") -> List[Dict[str, Any]]:
    """Validate references without accepting an inline artifact payload."""
    errors: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        if "artifact_refs" in value:
            refs = value["artifact_refs"]
            if not isinstance(refs, list):
                errors.append({"path": f"{path}.artifact_refs", "code": "ARTIFACT_REFS_NOT_ARRAY"})
            else:
                if len(refs) > 100:
                    errors.append({"path": f"{path}.artifact_refs", "code": "ARTIFACT_REFS_LIMIT"})
                for index, ref in enumerate(refs):
                    ref_path = f"{path}.artifact_refs[{index}]"
                    if not isinstance(ref, dict):
                        errors.append({"path": ref_path, "code": "ARTIFACT_REF_NOT_OBJECT"})
                        continue
                    for key in ("artifact_id", "content_hash"):
                        if not ref.get(key):
                            errors.append({"path": f"{ref_path}.{key}", "code": "ARTIFACT_REF_FIELD_MISSING"})
                    if any(key in ref for key in ("content", "content_base64", "blob", "payload")):
                        errors.append({"path": ref_path, "code": "ARTIFACT_INLINE_CONTENT_FORBIDDEN"})
                    if "content_size" in ref and (
                        not isinstance(ref["content_size"], int) or ref["content_size"] < 0
                    ):
                        errors.append({"path": f"{ref_path}.content_size", "code": "ARTIFACT_SIZE_INVALID"})
        for key, child in value.items():
            errors.extend(validate_artifact_references(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(validate_artifact_references(child, f"{path}[{index}]"))
    return errors


def prepare_output(value: Any, output_schema: Optional[Dict[str, Any]] = None,
                   max_bytes: Optional[int] = None) -> tuple[Any, List[Dict[str, Any]]]:
    """Redact and validate a Worker result before it is checkpointed."""
    safe = redact_state(value, allow_secrets=False)
    errors = validate_schema(safe, output_schema or {}, path="output")
    errors.extend(validate_artifact_references(safe))
    requested = DEFAULT_MAX_RESULT_BYTES if max_bytes is None else int(max_bytes)
    limit = max(1, min(requested, MAX_RESULT_BYTES))
    try:
        size = json_size_bytes(safe)
    except (TypeError, ValueError, OverflowError):
        size = 0
        errors.append({"path": "output", "code": "STATE_NOT_JSON"})
    if size > limit:
        errors.append({"path": "output", "code": "OUTPUT_SIZE_EXCEEDED", "limit": limit, "size": size})
    return safe, errors


def reduce_values(reducer: str, values: Iterable[Any]) -> Any:
    reducer = str(reducer or "").upper()
    if reducer not in REDUCERS:
        raise ValueError(f"unknown reducer: {reducer}")
    values = list(values)
    if not values:
        return None
    if reducer == "REPLACE":
        if len(values) > 1 and any(value != values[0] for value in values[1:]):
            raise ValueError("REPLACE reducer received conflicting concurrent values")
        return values[-1]
    if reducer == "APPEND":
        result = []
        for value in values:
            result.extend(value if isinstance(value, list) else [value])
        return result
    if reducer == "SET_UNION":
        values_by_marker = {}
        for value in values:
            for item in (value if isinstance(value, list) else [value]):
                marker = _canonical(item)
                values_by_marker.setdefault(marker, item)
        return [values_by_marker[marker] for marker in sorted(values_by_marker)]
    if reducer == "SUM":
        return sum(values)
    if reducer == "FIRST":
        return values[0]
    return values[-1]


def apply_delta(state: Dict[str, Any], delta: Dict[str, Any], schema: Optional[Dict[str, Any]] = None,
                fields: Optional[Dict[str, Dict[str, Any]]] = None,
                allow_secrets: bool = False) -> Dict[str, Any]:
    fields = fields or {}
    for key in delta:
        field = fields.get(key) or {}
        if str(field.get("scope") or "").upper() == "SECRET" and not allow_secrets:
            raise PermissionError(f"secret field is not writable in this scope: {key}")
    result = dict(state or {})
    result.update(delta or {})
    errors = validate_schema(result, schema or {})
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=True))
    return result


def artifact_reference(artifact: Dict[str, Any], summary: Optional[str] = None) -> Dict[str, Any]:
    if not artifact.get("artifact_id") or not artifact.get("content_hash"):
        raise ValueError("artifact reference requires artifact_id and content_hash")
    return {
        "artifact_id": artifact["artifact_id"],
        "content_hash": artifact["content_hash"],
        "content_size": artifact.get("content_size", 0),
        "summary": (summary or "")[:2000],
    }
