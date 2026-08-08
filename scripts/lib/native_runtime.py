"""Reference local Runtime Worker for v4.3.6.

The Worker is a control-plane reference implementation.  It executes one
database-leased unit at a time, uses a fresh in-memory message list, and never
reuses a previous Agent's credentials, workspace, or model context. Customer
Runtime Adapters may implement the same lifecycle contract externally.
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional

from . import connection, identity_api, native_agent_api

logger = logging.getLogger(__name__)


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(k).lower(): v for k, v in dict(row).items()} if row else None


def local_worker_id() -> str:
    return "native-worker:" + socket.gethostname()


def _parse(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _llm_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    if not profile_id:
        return None
    return _row(connection.execute_query_one(
        "SELECT PROFILE_ID,PROVIDER_URL,MODEL_ID,API_KEY_CIPHER,STATUS FROM CX_LLM_PROVIDER_PROFILES "
        "WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": profile_id},
    ))


def _call_llm(profile: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Call an OpenAI-compatible endpoint without logging prompt or secrets."""
    provider_url = str(profile.get("provider_url") or "").strip().rstrip("/")
    parsed = urlsplit(provider_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError("LLM provider URL is invalid")
    url = provider_url + "/chat/completions"
    model = str(profile.get("model_id") or "")
    if not url or not model:
        raise RuntimeError("LLM provider profile is incomplete")
    headers = {"Content-Type": "application/json"}
    cipher = str(profile.get("api_key_cipher") or "")
    if cipher:
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(cipher).get("api_key") or "")
        if secret:
            headers["Authorization"] = "Bearer " + secret
    payload = json.dumps({"model": model, "messages": messages, "stream": False},
                         ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise RuntimeError("LLM provider response is too large")
            result = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("LLM provider request failed") from exc
    choices = result.get("choices") or []
    message = (choices[0] or {}).get("message") if choices else {}
    content = str((message or {}).get("content") or "")
    if not content:
        raise RuntimeError("LLM provider returned no content")
    return {"content": content,
            "model": result.get("model") or model}


def _set_profile_health(profile_id: str, state: str) -> None:
    connection.execute(
        "UPDATE CX_LLM_PROVIDER_PROFILES SET HEALTH_STATE=:state,UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE PROFILE_ID=:id AND STATUS='ACTIVE'",
        {"state": state[:32], "id": profile_id},
    )


def enqueue(actor: str, agent_id: str, messages: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    if not isinstance(messages, list) or not messages or len(messages) > 100:
        raise native_agent_api.NativeAgentError("messages must contain between 1 and 100 items")
    if len(native_agent_api._json(messages).encode("utf-8")) > 256 * 1024:
        raise native_agent_api.NativeAgentError("execution input is too large")
    agent = _row(connection.execute_query_one(
        "SELECT AGENT_ID,STATUS,ACTIVATION_STATE,DEPLOYMENT_TARGET_ID,LLM_PROFILE_ID FROM CX_NATIVE_AGENTS "
        "WHERE AGENT_ID=:id", {"id": agent_id},
    ))
    if not agent:
        raise native_agent_api.NativeAgentError("native Agent is unavailable")
    if str(agent.get("status") or "").upper() != "ACTIVE":
        raise native_agent_api.NativeAgentError("native Agent is not active")
    if not identity_api._agent_visible_to(actor, agent_id):
        raise PermissionError("Agent is outside the delegated scope")
    execution_id = native_agent_api._id("EXE")
    payload = native_agent_api._json({"messages": messages})
    connection.execute(
        "INSERT INTO CX_RUNTIME_EXECUTIONS(EXECUTION_ID,AGENT_ID,TARGET_ID,ISOLATION_LEVEL,STATUS,INPUT_JSON,"
        "CONTEXT_DIGEST) VALUES (:id,:agent,:target,'DOMAIN_ISOLATED','PENDING',:input,:digest)",
        {"id": execution_id, "agent": agent_id, "target": agent.get("deployment_target_id"),
         "input": payload, "digest": native_agent_api._digest(payload)},
    )
    return {"execution_id": execution_id, "agent_id": agent_id, "status": "PENDING"}


def _finish(execution_id: str, worker_id: str, node_id: str, fencing_token: int,
            status: str, output: Optional[Dict[str, Any]] = None,
            failure: str = "") -> None:
    connection.execute(
        "UPDATE CX_RUNTIME_EXECUTIONS SET STATUS=:status,OUTPUT_JSON=:output,FAILURE_REASON=:failure,"
        "COMPLETED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE EXECUTION_ID=:id "
        "AND WORKER_ID=:worker AND NODE_ID=:node AND FENCING_TOKEN=:token AND STATUS='CLAIMED'",
        {"status": status, "output": native_agent_api._json(output) if output is not None else None,
         "failure": failure[:2000] or None, "id": execution_id, "worker": worker_id,
         "node": node_id, "token": fencing_token},
    )


def execute_one(worker_id: str = "", node_id: str = "") -> Dict[str, Any]:
    worker_id = worker_id or local_worker_id()
    node_id = node_id or native_agent_api._text(socket.gethostname(), 128)
    claimed = native_agent_api.claim_runtime(worker_id, node_id, limit=1)
    if not claimed:
        return {"status": "IDLE", "worker_id": worker_id}
    execution = claimed[0]
    execution_id = str(execution.get("execution_id") or "")
    fencing_token = int(execution.get("fencing_token") or 0)
    try:
        agent = _row(connection.execute_query_one(
            "SELECT AGENT_ID,STATUS,LLM_PROFILE_ID FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:id",
            {"id": execution.get("agent_id")},
        ))
        if not agent or str(agent.get("status") or "").upper() != "ACTIVE":
            raise RuntimeError("Agent is not active")
        input_payload = _parse(execution.get("input_json"), {})
        messages = input_payload.get("messages") if isinstance(input_payload, dict) else []
        profile = _llm_profile(str(agent.get("llm_profile_id") or ""))
        if not profile:
            raise RuntimeError("Agent has no active LLM Provider Profile")
        output = _call_llm(profile, messages if isinstance(messages, list) else [])
        _set_profile_health(str(agent.get("llm_profile_id") or ""), "HEALTHY")
        _finish(execution_id, worker_id, node_id, fencing_token, "COMPLETED", output=output)
        return {"status": "COMPLETED", "execution_id": execution_id}
    except Exception as exc:
        logger.info("Native execution failed: %s", type(exc).__name__)
        try:
            _set_profile_health(str((agent or {}).get("llm_profile_id") or ""), "DEGRADED")
        except Exception:
            logger.debug("Unable to update LLM health", exc_info=True)
        _finish(execution_id, worker_id, node_id, fencing_token, "FAILED", failure="runtime execution failed")
        return {"status": "FAILED", "execution_id": execution_id}


def get_execution(actor: str, execution_id: str) -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT EXECUTION_ID,AGENT_ID,TARGET_ID,ISOLATION_LEVEL,STATUS,WORKER_ID,NODE_ID,OUTPUT_JSON,"
        "FAILURE_REASON,STARTED_AT,COMPLETED_AT,CREATED_AT,UPDATED_AT FROM CX_RUNTIME_EXECUTIONS "
        "WHERE EXECUTION_ID=:id", {"id": execution_id},
    ))
    if not row or not identity_api._agent_visible_to(actor, str(row.get("agent_id") or "")):
        raise PermissionError("Execution is unavailable")
    if row.get("output_json"):
        row["output"] = _parse(row.pop("output_json"), {})
    return row
