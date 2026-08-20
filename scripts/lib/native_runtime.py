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
    pending = ""
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
                pending += piece
                if len(content.encode("utf-8")) > 100000:
                    raise RuntimeError("LLM provider response is too large")
                now = time.monotonic()
                if now - last_emit >= 0.25:
                    # Callers receive only the new delta. The complete output
                    # remains local for persistence and integrity checks.
                    on_delta(pending)
                    pending = ""
                    last_emit = now
            # The provider may finish before the throttle interval elapses.
            # Flush the bounded remainder so the client never needs the final
            # persisted response to discover text that was not streamed.
            if pending:
                on_delta(pending)
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


def _management_status_markdown(snapshot: Dict[str, Any], language: str = "zh") -> str:
    """Render a credential-free database control-plane report deterministically."""
    native = snapshot.get("native_agents") if isinstance(snapshot, dict) else {}
    runtime = snapshot.get("runtime_executions") if isinstance(snapshot, dict) else {}
    llm = snapshot.get("llm_profiles") if isinstance(snapshot, dict) else {}
    group = snapshot.get("admin_group") if isinstance(snapshot, dict) else {}
    if language == "en":
        return "\n".join([
            "## Platform runtime status", "",
            "- **Scope**: Aggregated database control-plane state; excludes hosts, connections, credentials, tokens, and user data.",
            f"- **Built-in Agents**: {int((native or {}).get('active') or 0)} active, {int((native or {}).get('non_active') or 0)} inactive.",
            f"- **Runtime executions**: {int((runtime or {}).get('pending') or 0)} pending, {int((runtime or {}).get('claimed') or 0)} running, {int((runtime or {}).get('failed') or 0)} failed.",
            f"- **LLM profiles**: {int((llm or {}).get('active') or 0)} active, {int((llm or {}).get('healthy') or 0)} healthy, {int((llm or {}).get('degraded') or 0)} degraded.",
            f"- **Admin group**: status {str((group or {}).get('status') or 'UNKNOWN')}, {int((group or {}).get('active_voting_members') or 0)} voting members, term {int((group or {}).get('current_term') or 0)}.",
            "", "> This is a read-only report. Configuration, membership, upgrade, and containment changes require governed Action Cards and approval workflows.",
        ])
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


def _management_template_markdown(knowledge: Dict[str, Any]) -> str:
    """Render fixed product workflow guidance; never ask the LLM to invent it."""
    language = "zh" if str(knowledge.get("response_language") or "en") == "zh" else "en"
    workflow = knowledge.get("template_workflow") or {}
    controls = knowledge.get("security_controls_" + language) or []
    lifecycle = knowledge.get("request_lifecycle_" + language) or []
    required = knowledge.get("required_request_controls_" + language) or []
    options = knowledge.get("business_template_options") or []
    if language == "zh":
        return "\n".join([
            "## 内置 Agent 模板与平台 Agent 申请", "",
            f"- **模板含义**：{workflow.get('template_meaning_zh') or '未配置'}",
            f"- **内置管理 Agent**：{workflow.get('seed_location_zh') or '未配置'}。",
            f"- **业务 Agent 申请**：{workflow.get('business_request_location_zh') or '未配置'}。",
            f"- **申请审批**：{workflow.get('approval_location_zh') or '未配置'}。",
            f"- **对象区别**：{workflow.get('compliance_distinction_zh') or '未配置'}",
            f"- **当前边界**：{knowledge.get('missing_capability_answer_zh') or ''}",
            "", "### 可选业务模板与能力倾向",
            *[f"- **{item.get('key')}**：{item.get('zh')}" for item in options],
            "", "### 申请必须填写", "- " + "、".join(required),
            "", "### 安全与合规控制", *[f"- {item}" for item in controls],
            "", "### 业务 Agent 生命周期", "- " + " -> ".join(lifecycle),
            "", f"> {knowledge.get('immutability_zh') or ''}",
            f"> {knowledge.get('external_registration_zh') or ''}",
        ])
    return "\n".join([
        "## Built-in Agent templates and platform Agent requests", "",
        f"- **Template meaning**: {workflow.get('template_meaning_en') or 'Not configured'}",
        f"- **Built-in management Agents**: {workflow.get('seed_location_en') or 'Not configured'}.",
        f"- **Business Agent request**: {workflow.get('business_request_location_en') or 'Not configured'}.",
        f"- **Request approval**: {workflow.get('approval_location_en') or 'Not configured'}.",
        f"- **Object distinction**: {workflow.get('compliance_distinction_en') or 'Not configured'}",
        f"- **Current boundary**: {knowledge.get('missing_capability_answer_en') or ''}",
        "", "### Selectable Business templates and capability tendencies",
        *[f"- **{item.get('key')}**: {item.get('en')}" for item in options],
        "", "### Required request fields", "- " + ", ".join(required),
        "", "### Security and compliance controls", *[f"- {item}" for item in controls],
        "", "### Business Agent lifecycle", "- " + " -> ".join(lifecycle),
        "", f"> {knowledge.get('immutability_en') or ''}",
        f"> {knowledge.get('external_registration_en') or ''}",
    ])


def _platform_command_help_markdown(help_payload: Dict[str, Any], language: str = "zh") -> str:
    """Render command help directly from the database registry payload."""
    item = help_payload.get("item")
    if isinstance(item, dict):
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        name = str(metadata.get("name_zh" if language == "zh" else "name_en") or item.get("command_key") or "")
        summary = str(metadata.get("summary_zh" if language == "zh" else "summary_en") or "")
        schema = item.get("parameter_schema") if isinstance(item.get("parameter_schema"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        return "\n".join([
            "## 平台命令帮助" if language == "zh" else "## Platform command help", "",
            f"- **{item.get('command_key')}** · {name}",
            f"- **{'格式' if language == 'zh' else 'Syntax'}**: `{item.get('example')}`",
            f"- **{'风险等级' if language == 'zh' else 'Risk'}**: {item.get('risk_level')}",
            f"- **{'执行状态' if language == 'zh' else 'Execution'}**: {item.get('execution_mode')} / {item.get('executor_state')}",
            f"- {summary}",
            f"- **{'必填参数' if language == 'zh' else 'Required parameters'}**: {', '.join(str(value) for value in required) or ('无' if language == 'zh' else 'none')}",
            f"- **{'边界' if language == 'zh' else 'Boundary'}**: " + (
                "该命令不因聊天文本或模型输出获得额外权限；需要变更时仍以操作卡和审批结果为准。"
                if language == "zh" else
                "Chat text and model output do not add authority; governed Action Cards and approvals remain authoritative."
            ),
        ])
    items = help_payload.get("items") if isinstance(help_payload.get("items"), list) else []
    rows = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        name = str(metadata.get("name_zh" if language == "zh" else "name_en") or entry.get("command_key") or "")
        rows.append(f"- **{entry.get('command_key')}** · {name} · `{entry.get('risk_level')}` · `{entry.get('execution_mode')}`")
    return "\n".join([
        "## 平台命令帮助" if language == "zh" else "## Platform command help", "",
        *(rows or [(("- 暂无可用命令。") if language == "zh" else "- No usable commands.")]),
        "",
        "> " + (
            "输入 /platform HELP <COMMAND_KEY> 查看单个命令格式。命令发现按当前管理员权限过滤。"
            if language == "zh" else
            "Enter /platform HELP <COMMAND_KEY> for command-specific syntax. Discovery is filtered by the administrator's authority."
        ),
    ])


def _platform_command_result_markdown(command: Dict[str, Any], language: str = "zh") -> str:
    """Render a credential-free, deterministic platform command result."""
    command_key = str(command.get("command_type") or "PLATFORM_COMMAND").upper()
    status = str(command.get("status") or "UNKNOWN").upper()
    result = command.get("result") if isinstance(command.get("result"), dict) else {}
    if language == "zh":
        title = "平台命令结果"
        command_label = "命令"
        status_label = "状态"
        result_label = "结果"
        scope_labels = {
            "database_control_plane": "数据库控制平面",
        }
    else:
        title = "Platform command result"
        command_label = "Command"
        status_label = "Status"
        result_label = "Result"
        scope_labels = {
            "database_control_plane": "database control plane",
        }
    lines = [
        f"## {title}",
        "",
        f"- **{command_label}**：`{command_key}`",
        f"- **{status_label}**：`{status}`",
        "",
        f"### {result_label}",
    ]
    if result.get("status") == "ok":
        scope = str(result.get("scope") or "")
        if language == "zh":
            lines.append(f"- 检查通过，范围：{scope_labels.get(scope, scope or '数据库控制平面')}。")
        else:
            lines.append(f"- Check passed, scope: {scope_labels.get(scope, scope or 'database control plane')}.")
    def render_value(value: Any) -> str:
        if isinstance(value, dict):
            return "; ".join(f"{sub_key}={render_value(sub_value)}" for sub_key, sub_value in value.items())
        if isinstance(value, list):
            return ", ".join(render_value(item) for item in value)
        return str(value)

    action = command.get("action_card") if isinstance(command.get("action_card"), dict) else {}
    if action:
        lines.extend([
            "",
            f"### {'审批信息' if language == 'zh' else 'Approval'}",
            f"- **{'操作卡' if language == 'zh' else 'Action Card'}**：`{action.get('action_id') or action.get('id') or 'created'}`",
            f"- **{'状态' if language == 'zh' else 'Status'}**：`{action.get('status') or 'PENDING'}`",
            f"- **{'说明' if language == 'zh' else 'Boundary'}**：" + ("变更命令只创建审批卡，不会因聊天或模型输出自动执行。" if language == 'zh' else "The change command creates an approval card only; chat or model output cannot execute it automatically."),
        ])
    for key, value in result.items():
        if key in {"status", "scope"}:
            continue
        label = {
            "managed_nodes": "托管节点" if language == "zh" else "Managed nodes",
            "native_agents": "原生 Agent" if language == "zh" else "Native Agents",
            "llm_profiles": "LLM 配置" if language == "zh" else "LLM profiles",
            "embedding": "Embedding" if language == "zh" else "Embedding",
            "runtime": "运行时" if language == "zh" else "Runtime",
            "database_dialect": "数据库方言" if language == "zh" else "Database dialect",
            "checked_at": "检查时间" if language == "zh" else "Checked at",
        }.get(key, key)
        if isinstance(value, dict):
            details = render_value(value)
            lines.append(f"- **{label}**：`{details}`")
        else:
            lines.append(f"- **{label}**：`{value}`")
    return "\n".join(lines)


def _platform_product_markdown(knowledge: Dict[str, Any], language: str = "zh") -> str:
    """Render a signed platform overview without an LLM call."""
    options = knowledge.get("business_template_options") if isinstance(knowledge.get("business_template_options"), list) else []
    if language == "zh":
        return "\n".join([
            "## 川序 AI Agent 管理平台", "",
            "这是一个以 Oracle、PostgreSQL 和 YashanDB 为权威控制面的 AI Agent 管理平台。平台将 Agent 身份、组织、频道、知识、记忆、图关系、任务、Skill、审批、合规和审计纳入数据库治理。",
            "", "### 当前平台能力",
            "- 可观测：Agent、运行时、关系图和审计状态可查询。",
            "- 可调度：持久任务、协作关卡、审批和受治理执行形成闭环。",
            "- 可运维：三数据库适配、离线部署、独立身份、凭据轮换和故障边界清晰。",
            "", "### Agent 与安全边界",
            "- 平台管理 Agent 只处理受保护的平台控制面；业务 Agent 必须经过申请、审批、部署和激活。",
            "- 聊天文本、提示词、Skill、Tool 或 URL 不会自动授予数据库或平台权限。",
            "- 高风险变更必须生成操作卡并由授权人员最终审批。",
            "", "### 可选业务模板",
            *[f"- **{item.get('key')}**：{item.get('zh')}" for item in options],
            "", "### 当前限制",
            str(knowledge.get("missing_capability_answer_zh") or "当前能力以已发布版本和实例授权为准。"),
        ])
    return "\n".join([
        "## Chuanxu AI Agent Management Platform", "",
        "A database-governed AI Agent management platform for Oracle, PostgreSQL, and YashanDB. Agent identity, organization, Channels, knowledge, memory, graph relationships, tasks, Skills, approvals, compliance, and audit remain under the database control plane.",
        "", "### Current capabilities",
        "- Observable: Agent, runtime, graph, and audit state are queryable.",
        "- Schedulable: durable tasks, collaboration gates, approvals, and governed execution form one lifecycle.",
        "- Operable: three database adapters, offline deployment, independent identities, credential rotation, and explicit failure boundaries.",
        "", "### Agent and security boundaries",
        "- Platform management Agents handle only the protected control plane; Business Agents require request, approval, deployment, and activation.",
        "- Chat text, prompts, Skills, Tools, and URLs never grant database or platform authority.",
        "- High-risk changes create an Action Card and require final approval by an authorized human.",
        "", "### Selectable Business templates",
        *[f"- **{item.get('key')}**: {item.get('en')}" for item in options],
        "", "### Current boundary",
        str(knowledge.get("missing_capability_answer_en") or "Capabilities are bounded by the published release and instance authorization."),
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
        content = (
            "管理 Agent 未能完成本次请求。请检查 Agent 模型配置和审计记录后重试。"
            if str(input_payload.get("response_language") or "en") == "zh" else
            "The management Agent could not complete this request. Check the Agent model configuration and the audit record before retrying."
        )
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
        template_knowledge = input_payload.get("management_template_knowledge") if isinstance(input_payload, dict) else None
        product_overview = input_payload.get("management_product_overview") if isinstance(input_payload, dict) else None
        command_help = input_payload.get("platform_command_help") if isinstance(input_payload, dict) else None
        command_result = input_payload.get("platform_command_result") if isinstance(input_payload, dict) else None
        response_language = "zh" if str(input_payload.get("response_language") or "en") == "zh" else "en"
        if not profile and not isinstance(status_snapshot, dict) and not isinstance(template_knowledge, dict) and not isinstance(product_overview, dict) and not isinstance(command_help, dict) and not isinstance(command_result, dict):
            raise RuntimeError("Agent has no active LLM Provider Profile")
        dispatch = _channel_dispatch(input_payload)
        if dispatch:
            channel_id = str(dispatch["channel_id"])
            identity_api.begin_channel_agent_response(
                str(agent.get("agent_id") or ""), channel_id, execution_id=execution_id,
                thread_type=str(dispatch.get("thread_type") or "CHANNEL"), thread_id=str(dispatch.get("thread_id") or ""),
            )
            if isinstance(template_knowledge, dict):
                output = {"content": _management_template_markdown(template_knowledge), "model": "database-control-plane"}
            elif isinstance(product_overview, dict):
                output = {"content": _platform_product_markdown(product_overview, response_language), "model": "database-control-plane"}
            elif isinstance(command_help, dict):
                output = {"content": _platform_command_help_markdown(command_help, response_language), "model": "database-control-plane"}
            elif isinstance(command_result, dict):
                output = {"content": _platform_command_result_markdown(command_result, response_language), "model": "database-control-plane"}
            elif isinstance(status_snapshot, dict):
                output = {"content": _management_status_markdown(status_snapshot, response_language), "model": "database-control-plane"}
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
