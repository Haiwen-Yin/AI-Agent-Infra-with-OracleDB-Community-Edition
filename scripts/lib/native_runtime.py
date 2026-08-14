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
import time
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


def _stream_llm(profile: Dict[str, Any], messages: List[Dict[str, Any]], on_delta: Any) -> Dict[str, Any]:
    """Stream OpenAI-compatible deltas without retaining or logging prompts."""
    provider_url = str(profile.get("provider_url") or "").strip().rstrip("/")
    parsed = urlsplit(provider_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise RuntimeError("LLM provider URL is invalid")
    model = str(profile.get("model_id") or "")
    if not model:
        raise RuntimeError("LLM provider profile is incomplete")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    cipher = str(profile.get("api_key_cipher") or "")
    if cipher:
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(cipher).get("api_key") or "")
        if secret:
            headers["Authorization"] = "Bearer " + secret
    payload = json.dumps({"model": model, "messages": messages, "stream": True}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(provider_url + "/chat/completions", data=payload, headers=headers, method="POST")
    content = ""
    last_emit = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                item = line[5:].strip()
                if item == "[DONE]":
                    break
                try:
                    payload_item = json.loads(item)
                    choices = payload_item.get("choices") or []
                    delta = (choices[0] or {}).get("delta") if choices else {}
                    piece = str((delta or {}).get("content") or "")
                except (TypeError, ValueError):
                    continue
                if not piece:
                    continue
                content += piece
                if len(content.encode("utf-8")) > 100000:
                    raise RuntimeError("LLM provider response is too large")
                now = time.monotonic()
                if now - last_emit >= 0.25:
                    # Callers receive only the new delta. The complete output
                    # remains local for persistence and integrity checks.
                    on_delta(piece)
                    last_emit = now
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("LLM provider streaming request failed") from exc
    if not content:
        raise RuntimeError("LLM provider returned no content")
    return {"content": content, "model": model}


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


def _channel_dispatch(input_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    dispatch = input_payload.get("channel_dispatch") if isinstance(input_payload, dict) else None
    return dispatch if isinstance(dispatch, dict) and str(dispatch.get("channel_id") or "") == "CH_PLATFORM_ADMINISTRATION" else None


def _management_status_markdown(snapshot: Dict[str, Any]) -> str:
    """Render a credential-free database control-plane report deterministically."""
    native = snapshot.get("native_agents") if isinstance(snapshot, dict) else {}
    runtime = snapshot.get("runtime_executions") if isinstance(snapshot, dict) else {}
    llm = snapshot.get("llm_profiles") if isinstance(snapshot, dict) else {}
    group = snapshot.get("admin_group") if isinstance(snapshot, dict) else {}
    return "\n".join([
        "## 平台运行状态",
        "",
        "- **状态范围**：数据库控制平面聚合状态，不包含主机、连接、凭证、Token 或用户数据。",
        f"- **内置智能体**：活动 {int((native or {}).get('active') or 0)}，非活动 {int((native or {}).get('non_active') or 0)}。",
        f"- **运行任务**：等待 {int((runtime or {}).get('pending') or 0)}，执行中 {int((runtime or {}).get('claimed') or 0)}，失败 {int((runtime or {}).get('failed') or 0)}。",
        f"- **LLM 配置**：活动 {int((llm or {}).get('active') or 0)}，健康 {int((llm or {}).get('healthy') or 0)}，降级 {int((llm or {}).get('degraded') or 0)}。",
        f"- **Admin 协作组**：状态 {str((group or {}).get('status') or 'UNKNOWN')}，投票成员 {int((group or {}).get('active_voting_members') or 0)}，当前任期 {int((group or {}).get('current_term') or 0)}。",
        "",
        "> 该报告仅提供只读状态。配置、成员、升级和阻断操作必须通过受治理的操作卡与审批流程执行。",
    ])


def _write_channel_response(agent_id: str, execution_id: str, input_payload: Dict[str, Any],
                            output: Optional[Dict[str, Any]] = None, failure: str = "") -> None:
    """Return a managed runtime result to the protected Channel once only."""
    dispatch = _channel_dispatch(input_payload)
    if not dispatch:
        return
    channel_id = str(dispatch["channel_id"])
    content = str((output or {}).get("content") or "").strip()
    if not content:
        content = "The management Agent could not complete this request. Check the Agent model configuration and the audit record before retrying."
    identity_api.post_channel_agent_response(agent_id, channel_id, content, execution_id=execution_id,
                                             thread_type=str(dispatch.get("thread_type") or "CHANNEL"),
                                             thread_id=str(dispatch.get("thread_id") or ""))


def execute_one(worker_id: str = "", node_id: str = "") -> Dict[str, Any]:
    worker_id = worker_id or local_worker_id()
    node_id = node_id or native_agent_api._text(socket.gethostname(), 128)
    claimed = native_agent_api.claim_runtime(worker_id, node_id, limit=1)
    if not claimed:
        return {"status": "IDLE", "worker_id": worker_id}
    execution = claimed[0]
    execution_id = str(execution.get("execution_id") or "")
    fencing_token = int(execution.get("fencing_token") or 0)
    input_payload: Dict[str, Any] = {}
    agent: Optional[Dict[str, Any]] = None
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
        status_snapshot = input_payload.get("management_status_snapshot") if isinstance(input_payload, dict) else None
        if not profile and not isinstance(status_snapshot, dict):
            raise RuntimeError("Agent has no active LLM Provider Profile")
        dispatch = _channel_dispatch(input_payload)
        if dispatch:
            channel_id = str(dispatch["channel_id"])
            identity_api.begin_channel_agent_response(
                str(agent.get("agent_id") or ""), channel_id, execution_id=execution_id,
                thread_type=str(dispatch.get("thread_type") or "CHANNEL"), thread_id=str(dispatch.get("thread_id") or ""),
            )
            if isinstance(status_snapshot, dict):
                output = {"content": _management_status_markdown(status_snapshot), "model": "database-control-plane"}
            else:
                try:
                    output = _stream_llm(
                        profile, messages if isinstance(messages, list) else [],
                        lambda content: identity_api.update_channel_agent_response(
                            str(agent.get("agent_id") or ""), channel_id, content, execution_id=execution_id,
                        ),
                    )
                except RuntimeError as exc:
                    # Some OpenAI-compatible reasoning providers can complete an
                    # SSE response without a content delta. Preserve the same
                    # bounded prompt and safe Channel response by falling back to
                    # one non-streaming request; transport and timeout failures
                    # remain failures and are never retried here.
                    if str(exc) != "LLM provider returned no content":
                        raise
                    output = _call_llm(profile, messages if isinstance(messages, list) else [])
            identity_api.update_channel_agent_response(
                str(agent.get("agent_id") or ""), channel_id, str(output.get("content") or ""),
                execution_id=execution_id, completed=True,
            )
        else:
            if not profile:
                raise RuntimeError("Agent has no active LLM Provider Profile")
            output = _call_llm(profile, messages if isinstance(messages, list) else [])
        _set_profile_health(str(agent.get("llm_profile_id") or ""), "HEALTHY")
        if not dispatch:
            _write_channel_response(str(agent.get("agent_id") or ""), execution_id, input_payload, output=output)
        _finish(execution_id, worker_id, node_id, fencing_token, "COMPLETED", output=output)
        return {"status": "COMPLETED", "execution_id": execution_id}
    except Exception as exc:
        logger.info("Native execution failed: %s", type(exc).__name__)
        try:
            _set_profile_health(str((agent or {}).get("llm_profile_id") or ""), "DEGRADED")
        except Exception:
            logger.debug("Unable to update LLM health", exc_info=True)
        try:
            _write_channel_response(str((agent or {}).get("agent_id") or ""), execution_id, input_payload, failure="runtime execution failed")
        except Exception:
            logger.debug("Unable to write Channel response", exc_info=True)
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
