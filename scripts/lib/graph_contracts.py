"""Database-independent contracts shared by Graph services and tests."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Optional


GRAPH_STATUSES = frozenset({"DRAFT", "VALIDATED", "PUBLISHED", "DEPRECATED", "ARCHIVED"})


class CompletionContractError(ValueError):
    """Stable failure for a completion payload that cannot be canonicalized."""

    def __init__(self, diagnostic: Dict[str, Any]):
        self.diagnostic = dict(diagnostic or {})
        super().__init__(
            f"{self.diagnostic.get('code', 'COMPLETION_PAYLOAD_INVALID')}: "
            f"{self.diagnostic.get('message', 'completion payload is invalid')}"
        )


def completion_request_digest(output_state: Optional[Dict[str, Any]],
                              evidence: Optional[Dict[str, Any]]) -> str:
    """Return a stable digest for an exact Worker completion request."""
    if output_state is not None and not isinstance(output_state, dict):
        raise CompletionContractError({
            "code": "COMPLETION_OUTPUT_OBJECT_REQUIRED",
            "message": "output_state must be an object",
        })
    if evidence is not None and not isinstance(evidence, dict):
        raise CompletionContractError({
            "code": "COMPLETION_EVIDENCE_OBJECT_REQUIRED",
            "message": "evidence must be an object",
        })
    payload = {"output_state": output_state or {}, "evidence": evidence or {}}
    try:
        encoded = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise CompletionContractError({
            "code": "COMPLETION_PAYLOAD_NOT_JSON",
            "message": "output_state and evidence must contain finite JSON values",
        }) from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_valid_status_transition(old: str, new: str) -> bool:
    """Return whether a Graph Version can move between lifecycle states."""
    allowed = {
        "DRAFT": {"VALIDATED", "ARCHIVED"},
        "VALIDATED": {"DRAFT", "PUBLISHED", "ARCHIVED"},
        "PUBLISHED": {"DEPRECATED", "ARCHIVED"},
        "DEPRECATED": {"ARCHIVED"},
        "ARCHIVED": set(),
    }
    old_status = str(old or "").upper()
    new_status = str(new or "").upper()
    return new_status in GRAPH_STATUSES and new_status in allowed.get(old_status, set())


def worker_matches(required_capabilities: Optional[Iterable[str]],
                   worker_capabilities: Optional[Iterable[str]],
                   required_resource_class: Optional[str] = None,
                   worker_runtime: Optional[str] = None) -> bool:
    """Check scheduling eligibility without granting authorization.

    A resource class may be advertised as the Worker runtime or as one of its
    capabilities.  Authorization and policy checks remain separate concerns.
    """
    required = {str(item) for item in (required_capabilities or []) if str(item)}
    advertised = {str(item) for item in (worker_capabilities or []) if str(item)}
    if not required.issubset(advertised):
        return False
    resource_class = str(required_resource_class or "").strip()
    if resource_class and resource_class not in advertised and resource_class != str(worker_runtime or ""):
        return False
    return True
