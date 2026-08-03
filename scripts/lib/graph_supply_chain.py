"""Canonical Graph Definition supply-chain envelopes.

Private signing material is passed by a local publisher and never written to
the database, exported document metadata, audit detail, or application logs.
The service accepts unsigned definitions only as untrusted Draft candidates.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional


SUPPLY_CHAIN_VERSION = "1.0"
COMPATIBILITY_LEVELS = frozenset({"COMPATIBLE", "MIGRATION_REQUIRED", "INCOMPATIBLE"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))


def _signature_payload(document: Dict[str, Any]) -> Dict[str, Any]:
    copy = json.loads(canonical_json(document))
    copy.pop("export_digest", None)
    envelope = copy.setdefault("supply_chain", {})
    envelope.pop("signature", None)
    return copy


def normalize_dependencies(dependencies: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for item in dependencies or []:
        if not isinstance(item, dict):
            raise ValueError("dependency lock entries must be objects")
        kind = str(item.get("kind") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        item_digest = str(item.get("digest") or "").strip().lower()
        if not kind or not name or not version:
            raise ValueError("dependency lock requires kind, name, and version")
        if item_digest and not re.fullmatch(r"[0-9a-f]{64}", item_digest):
            raise ValueError("dependency digest must be a SHA-256 hex digest")
        result.append({"kind": kind, "name": name, "version": version, "digest": item_digest})
    return sorted(result, key=lambda item: (item["kind"], item["name"], item["version"], item["digest"]))


def make_envelope(document: Dict[str, Any], *, publisher: str = "", source_uri: str = "",
                  parent_digest: str = "", dependencies: Optional[Iterable[Dict[str, Any]]] = None,
                  compatibility: str = "COMPATIBLE", compiler_version: str = "") -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("Graph Definition document must be an object")
    level = str(compatibility or "COMPATIBLE").upper()
    if level not in COMPATIBILITY_LEVELS:
        raise ValueError("invalid compatibility level")
    if parent_digest and not re.fullmatch(r"[0-9a-f]{64}", str(parent_digest).lower()):
        raise ValueError("parent digest must be a SHA-256 hex digest")
    return {
        "schema_version": SUPPLY_CHAIN_VERSION,
        "publisher": str(publisher or "")[:256],
        "source_uri": str(source_uri or "")[:1024],
        "parent_digest": str(parent_digest or "").lower(),
        "dependencies": normalize_dependencies(dependencies),
        "compatibility": level,
        "compiler_version": str(compiler_version or "")[:64],
        "document_digest": digest({key: value for key, value in document.items() if key != "export_digest"}),
    }


def attach_envelope(document: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    result = json.loads(canonical_json(document))
    result["supply_chain"] = make_envelope(result, **kwargs)
    result["export_digest"] = digest(_signature_payload(result))
    return result


def sign_document(document: Dict[str, Any], private_key: bytes, *, key_id: str) -> Dict[str, Any]:
    if not str(key_id or "").strip():
        raise ValueError("publisher key id is required")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.from_private_bytes(private_key)
    except Exception as exc:
        raise ValueError("invalid Ed25519 private key") from exc
    result = json.loads(canonical_json(document))
    envelope = result.setdefault("supply_chain", make_envelope(result))
    payload = canonical_json(_signature_payload(result)).encode("utf-8")
    envelope["signature"] = {"algorithm": "ED25519", "key_id": str(key_id)[:256],
                              "value": _b64(key.sign(payload))}
    result["export_digest"] = digest(_signature_payload(result))
    return result


def verify_document(document: Dict[str, Any], trusted_public_keys: Dict[str, str]) -> Dict[str, Any]:
    if not isinstance(document, dict):
        return {"verified": False, "trusted": False, "code": "DOCUMENT_REQUIRED"}
    envelope = document.get("supply_chain") or {}
    expected = str(envelope.get("document_digest") or "")
    actual = digest({key: value for key, value in document.items() if key not in {"export_digest", "supply_chain"}})
    # The envelope digest covers the export excluding mutable presentation
    # metadata. It is deliberately checked before a signature is considered.
    if expected and expected != actual:
        return {"verified": False, "trusted": False, "code": "DOCUMENT_DIGEST_MISMATCH"}
    signature = envelope.get("signature") or {}
    key_id = str(signature.get("key_id") or "")
    if not signature:
        return {"verified": False, "trusted": False, "code": "UNSIGNED"}
    if str(signature.get("algorithm") or "").upper() != "ED25519":
        return {"verified": False, "trusted": False, "code": "SIGNATURE_ALGORITHM_UNSUPPORTED"}
    public_key = trusted_public_keys.get(key_id)
    if not public_key:
        return {"verified": False, "trusted": False, "code": "PUBLISHER_UNTRUSTED", "key_id": key_id}
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(_unb64(public_key)).verify(
            _unb64(str(signature.get("value") or "")), canonical_json(_signature_payload(document)).encode("utf-8"),
        )
    except Exception:
        return {"verified": False, "trusted": False, "code": "SIGNATURE_INVALID", "key_id": key_id}
    return {"verified": True, "trusted": True, "code": "VERIFIED", "key_id": key_id,
            "compatibility": str(envelope.get("compatibility") or "COMPATIBLE").upper()}


def scan_document(document: Dict[str, Any], *, supported_dependencies: Optional[Iterable[Dict[str, Any]]] = None,
                  edition: str = "Enterprise") -> List[Dict[str, str]]:
    """Return deterministic import findings without executing imported content."""
    findings: List[Dict[str, str]] = []
    envelope = document.get("supply_chain") or {}
    definition = document.get("definition") or {}
    for dependency in normalize_dependencies(envelope.get("dependencies") or []):
        if supported_dependencies is not None and dependency not in normalize_dependencies(supported_dependencies):
            findings.append({"code": "DEPENDENCY_UNAVAILABLE", "severity": "HIGH", "detail": dependency["name"]})
    for node in ((definition.get("version") or {}).get("nodes") or []):
        config = node.get("config") if isinstance(node, dict) else {}
        text = canonical_json(config or {}).lower()
        if any(marker in text for marker in ("__import__", "subprocess", "os.system", "eval(", "exec(")):
            findings.append({"code": "ARBITRARY_CODE_REJECTED", "severity": "CRITICAL", "detail": str(node.get("node_key") or "")})
        if str(node.get("node_type") or "").upper() == "SCHEDULER" and str(edition).lower() == "community":
            findings.append({"code": "EDITION_MISMATCH", "severity": "HIGH", "detail": "SCHEDULER"})
    if str(envelope.get("compatibility") or "COMPATIBLE").upper() == "INCOMPATIBLE":
        findings.append({"code": "INCOMPATIBLE_IMPORT", "severity": "HIGH", "detail": "declared"})
    return findings
