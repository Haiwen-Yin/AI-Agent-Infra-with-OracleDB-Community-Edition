"""Database-authoritative model, MCP, A2A, and execution capability controls."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api

STATES = frozenset({"OFF", "READ_ONLY", "PROPOSAL_ONLY", "GOVERNED_EXECUTOR"})
CAPABILITIES = frozenset({
    "model_reasoning", "structured_output", "model_tool_calls", "mcp_discovery",
    "mcp_execution", "a2a_exchange", "governed_execution",
})
HIGH_IMPACT = frozenset({"WRITE", "POLICY_CHANGE", "AGENT_CONTROL", "EXTERNAL_CONTACT", "PUBLICATION"})


class CapabilityUnavailable(RuntimeError):
    pass


class CapabilityConflict(ValueError):
    pass


def _row(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(key).lower(): item for key, item in dict(value or {}).items()}


def _rows(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(value) for value in values]


def list_capabilities() -> Dict[str, Any]:
    try:
        rows = _rows(connection.execute_query(
            "SELECT CAPABILITY_KEY,STATE,VERSION,MANDATORY,SECURITY_DOMAIN_ID,SOURCE_DIGEST,SCHEMA_DIGEST,"
            "RESOURCE_SCOPE_JSON,EVIDENCE_REF,REASON,UPDATED_BY,UPDATED_AT "
            "FROM CX_MODEL_CAPABILITIES ORDER BY CAPABILITY_KEY"
        ))
    except Exception as exc:
        raise CapabilityUnavailable("Model capability registry is unavailable") from exc
    if {str(item.get("capability_key") or "") for item in rows} != CAPABILITIES:
        raise CapabilityUnavailable("Model capability registry is incomplete")
    return {"version": "4.4.14", "items": rows}


def state(capability_key: str) -> str:
    key = str(capability_key or "").strip()
    if key not in CAPABILITIES:
        raise CapabilityConflict("Unknown model capability")
    item = next(row for row in list_capabilities()["items"] if row["capability_key"] == key)
    value = str(item.get("state") or "OFF").upper()
    return value if value in STATES else "OFF"


def set_state(actor: str, capability_key: str, new_state: str, reason: str,
              expected_version: int, evidence_ref: str = "") -> Dict[str, Any]:
    key, target = str(capability_key or "").strip(), str(new_state or "").upper()
    if key not in CAPABILITIES or target not in STATES:
        raise CapabilityConflict("Unknown model capability or state")
    if len(str(reason or "").strip()) < 3:
        raise CapabilityConflict("A reason is required")
    if target in {"READ_ONLY", "PROPOSAL_ONLY", "GOVERNED_EXECUTOR"} and len(str(evidence_ref or "").strip()) < 3:
        raise CapabilityConflict("Evidence reference is required for capability promotion")

    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT STATE,VERSION,MANDATORY FROM CX_MODEL_CAPABILITIES WHERE CAPABILITY_KEY=:key FOR UPDATE",
            {"key": key},
        ))
        if not current:
            raise CapabilityUnavailable("Model capability registry is incomplete")
        version = int(current.get("version") or 0)
        if version != int(expected_version):
            raise CapabilityConflict("Model capability changed concurrently")
        before = str(current.get("state") or "OFF").upper()
        if before == target:
            return {"capability_key": key, "state": target, "version": version, "idempotent": True}
        changed = tx.execute(
            "UPDATE CX_MODEL_CAPABILITIES SET STATE=:state,VERSION=VERSION+1,EVIDENCE_REF=:evidence,"
            "REASON=:reason,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE CAPABILITY_KEY=:key AND VERSION=:version",
            {"state": target, "evidence": str(evidence_ref)[:256] or None, "reason": str(reason)[:2000],
             "actor": actor, "key": key, "version": version},
        )
        if changed != 1:
            raise CapabilityConflict("Model capability changed concurrently")
        tx.execute(
            "INSERT INTO CX_MODEL_CAPABILITY_HISTORY(HISTORY_ID,CAPABILITY_KEY,FROM_STATE,TO_STATE,"
            "EXPECTED_VERSION,EVIDENCE_REF,REASON,CHANGED_BY) VALUES(:id,:key,:before,:after,:version,:evidence,:reason,:actor)",
            {"id": "MCH_" + secrets.token_hex(20), "key": key, "before": before, "after": target,
             "version": version, "evidence": str(evidence_ref)[:256] or None,
             "reason": str(reason)[:2000], "actor": actor},
        )
        identity_api._audit_tx(tx, actor, "MODEL_CAPABILITY_STATE_CHANGE", "MODEL_CAPABILITY", key, "ALLOW", str(reason)[:2000])
        return {"capability_key": key, "state": target, "version": version + 1, "idempotent": False}

    result = connection.execute_transaction_callback(work)
    return result


def execution_decision(capability_key: str, impact: str, *, source_digest: str = "",
                       schema_digest: str = "", security_domain_id: str = "",
                       resource_scope: Optional[Dict[str, Any]] = None,
                       approved: bool = False) -> Dict[str, Any]:
    """Return the bounded disposition; a model response never grants authority."""
    posture = state(capability_key)
    impact_key = str(impact or "").upper()
    trusted = all((source_digest, schema_digest, security_domain_id)) and bool(resource_scope)
    if posture == "OFF":
        disposition = "DENY"
    elif posture == "READ_ONLY":
        disposition = "ALLOW_READ" if impact_key == "READ" and trusted else "DENY"
    elif posture == "PROPOSAL_ONLY" or impact_key in HIGH_IMPACT:
        disposition = "EXECUTE" if posture == "GOVERNED_EXECUTOR" and approved and trusted else "ACTION_CARD"
    else:
        disposition = "EXECUTE" if approved and trusted else "ACTION_CARD"
    return {"capability_key": capability_key, "state": posture, "disposition": disposition,
            "trusted_metadata": trusted, "approval_required": disposition == "ACTION_CARD"}


def normalize_provider_response(*, provider_key: str, model_id: str, request_id: str,
                                response: Dict[str, Any], latency_ms: int = 0,
                                retry_count: int = 0, timed_out: bool = False,
                                cancelled: bool = False, schema_valid: Optional[bool] = None) -> Dict[str, Any]:
    """Build a secret-free evidence envelope without returning hidden reasoning text."""
    choices = list(response.get("choices") or [])
    first = dict(choices[0] or {}) if choices else {}
    message = dict(first.get("message") or {})
    tool_calls = list(message.get("tool_calls") or [])
    usage = dict(response.get("usage") or {})
    envelope = {
        "provider_key": str(provider_key), "model_id": str(model_id), "request_id": str(request_id),
        "provider_request_id": str(response.get("id") or ""), "finish_state": str(first.get("finish_reason") or "unknown"),
        "content": message.get("content"), "reasoning": {"present": bool(message.get("reasoning_content")),
            "tokens": ((usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))},
        "tool_calls": tool_calls, "structured_output": {"requested": schema_valid is not None, "valid": schema_valid},
        "usage": usage, "latency_ms": max(0, int(latency_ms)), "retry_count": max(0, int(retry_count)),
        "timeout": bool(timed_out), "cancelled": bool(cancelled),
    }
    digest_input = json.dumps(envelope, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    envelope["evidence_digest"] = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    if schema_valid is False:
        envelope["finish_state"] = "schema_mismatch"
        envelope["content"] = None
        envelope["tool_calls"] = []
    return envelope
