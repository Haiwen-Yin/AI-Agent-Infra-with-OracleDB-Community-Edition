"""Governed model forwarding, usage accounting, and wallboard projections.

The module deliberately stores request metadata and usage facts only. Provider
credentials and prompt/response bodies never enter the ledger.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api, model_governance_api


class ModelUsageError(RuntimeError):
    pass


class ModelUsageConflict(ModelUsageError):
    pass


def _db_bool(value: bool) -> Any:
    return bool(value) if str(getattr(connection, "DATABASE_DIALECT", "")).lower() == "postgresql" else ("Y" if value else "N")


def _as_bool(value: Any) -> bool:
    return value is True or str(value or "").strip().upper() in {"Y", "YES", "TRUE", "1", "ON"}


def routing_policy(actor: str, agent_id: str = "", profile_id: str = "") -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "model_gateway.manage")
    if access.get("decision") != "ALLOW": raise PermissionError("model gateway management permission is required")
    row = _row(connection.execute_query_one("SELECT POLICY_ID,AGENT_ID,PROFILE_ID,ROUTING_MODE,GATEWAY_ENABLED,DIRECT_ALLOWED,GATEWAY_URL,UPDATED_BY,UPDATED_AT,REASON FROM CX_MODEL_ROUTING_POLICIES WHERE (AGENT_ID=:agent OR AGENT_ID IS NULL) AND (PROFILE_ID=:profile OR PROFILE_ID IS NULL) ORDER BY CASE WHEN AGENT_ID IS NULL THEN 1 ELSE 0 END, CASE WHEN PROFILE_ID IS NULL THEN 1 ELSE 0 END, UPDATED_AT DESC FETCH FIRST 1 ROWS ONLY", {"agent": agent_id or None, "profile": profile_id or None}))
    if row:
        row["gateway_enabled"] = _as_bool(row.get("gateway_enabled"))
        row["direct_allowed"] = _as_bool(row.get("direct_allowed"))
        return row
    return {"routing_mode": "OPTIONAL", "gateway_enabled": False, "direct_allowed": True, "gateway_url": "", "agent_id": agent_id, "profile_id": profile_id}


def set_routing_policy(actor: str, agent_id: str, profile_id: str, gateway_enabled: bool, direct_allowed: bool, reason: str, gateway_url: str = "") -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "model_gateway.manage")
    if access.get("decision") != "ALLOW": raise PermissionError("model gateway management permission is required")
    url = str(gateway_url or "").strip()[:512]
    if url and not (url.startswith("http://") or url.startswith("https://")): raise ValueError("gateway URL must use http or https")
    current = _row(connection.execute_query_one(
        "SELECT POLICY_ID FROM CX_MODEL_ROUTING_POLICIES WHERE "
        "((AGENT_ID=:agent) OR (AGENT_ID IS NULL AND :agent IS NULL)) AND "
        "((PROFILE_ID=:profile) OR (PROFILE_ID IS NULL AND :profile IS NULL)) "
        "ORDER BY UPDATED_AT DESC FETCH FIRST 1 ROWS ONLY",
        {"agent": agent_id or None, "profile": profile_id or None},
    ))
    policy_id = str(current.get("policy_id") or _id("MRP"))
    params = {"id": policy_id, "agent": agent_id or None, "profile": profile_id or None,
              "enabled": _db_bool(gateway_enabled), "direct": _db_bool(direct_allowed),
              "url": url or None, "actor": actor, "reason": reason[:500]}
    if current:
        connection.execute(
            "UPDATE CX_MODEL_ROUTING_POLICIES SET ROUTING_MODE='OPTIONAL',GATEWAY_ENABLED=:enabled,"
            "DIRECT_ALLOWED=:direct,GATEWAY_URL=:url,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP,REASON=:reason "
            "WHERE POLICY_ID=:id", params,
        )
    else:
        connection.execute("INSERT INTO CX_MODEL_ROUTING_POLICIES(POLICY_ID,AGENT_ID,PROFILE_ID,ROUTING_MODE,GATEWAY_ENABLED,DIRECT_ALLOWED,GATEWAY_URL,UPDATED_BY,REASON) VALUES(:id,:agent,:profile,'OPTIONAL',:enabled,:direct,:url,:actor,:reason)", params)
    return {"policy_id": policy_id, "agent_id": agent_id, "profile_id": profile_id, "routing_mode": "OPTIONAL", "gateway_enabled": gateway_enabled, "direct_allowed": direct_allowed, "gateway_url": url, "updated_by": actor}


def _row(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in dict(value or {}).items()}


def _id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(12)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope(actor: str) -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "model_usage.read")
    if access.get("decision") != "ALLOW": raise PermissionError("model usage permission is required")
    return access


def _usage_scope(actor: str, alias: str = "u", resource_scope: Optional[Dict[str, Any]] = None) -> tuple[str, Dict[str, Any]]:
    """Scope ledger aggregates to the caller and its visible Agent set."""
    try:
        visibility = identity_api._agent_visibility_clause(actor)
    except Exception as exc:
        raise PermissionError("model usage scope is unavailable") from exc
    clause = (
        "(" + alias + ".ACTOR_PRINCIPAL_ID=:actor OR EXISTS (SELECT 1 FROM CX_PRINCIPALS p "
        "WHERE p.PRINCIPAL_ID=" + alias + ".AGENT_ID AND p.PRINCIPAL_TYPE='AGENT' AND "
        + visibility + "))"
    )
    params: Dict[str, Any] = {"actor": actor}
    if ":principal_id" in visibility:
        params["principal_id"] = actor
    scope = resource_scope or {}
    if scope.get("security_domain_id"):
        clause += " AND " + alias + ".AGENT_ID IS NOT NULL AND EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS wdm WHERE wdm.PRINCIPAL_ID=" + alias + ".AGENT_ID AND wdm.SECURITY_DOMAIN_ID=:wallboard_domain AND wdm.STATUS='ACTIVE' AND (wdm.VALID_UNTIL IS NULL OR wdm.VALID_UNTIL>CURRENT_TIMESTAMP))"
        params["wallboard_domain"] = str(scope["security_domain_id"])
    if scope.get("organization_id"):
        clause += (
            " AND " + alias + ".AGENT_ID IS NOT NULL AND EXISTS (SELECT 1 FROM CX_AGENT_RELATIONSHIPS war "
            "JOIN CX_ORGANIZATION_MEMBERS wom ON wom.PRINCIPAL_ID=war.PRINCIPAL_ID "
            "WHERE war.AGENT_ID=" + alias + ".AGENT_ID AND war.RELATIONSHIP_ROLE='PRIMARY_OWNER' "
            "AND war.STATUS='ACTIVE' AND wom.STATUS='ACTIVE' "
            "AND (wom.VALID_UNTIL IS NULL OR wom.VALID_UNTIL>CURRENT_TIMESTAMP) "
            "AND EXISTS (SELECT 1 FROM CX_ORGANIZATION_CLOSURE woc "
            "WHERE woc.ANCESTOR_ID=:wallboard_org AND woc.DESCENDANT_ID=wom.ORGANIZATION_ID))"
        )
        params["wallboard_org"] = str(scope["organization_id"])
    return clause, params


def issue_gateway_credential(actor: str, name: str, scopes: List[str], expires_at: str = "") -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "model_gateway.manage")
    if access.get("decision") != "ALLOW": access = identity_api.effective_access(actor, "platform.manage")
    if access.get("decision") != "ALLOW":
        raise PermissionError("model gateway management permission is required")
    normalized_scopes = sorted({str(item or "").strip() for item in scopes if str(item or "").strip()})
    if "model.forward" not in normalized_scopes:
        raise ModelUsageError("gateway credential requires model.forward scope")
    for item in normalized_scopes:
        if item != "model.forward" and not item.startswith(("profile:", "agent:")):
            raise ModelUsageError("gateway credential contains an unsupported scope")
        if item.startswith(("profile:", "agent:")) and not item.split(":", 1)[1]:
            raise ModelUsageError("gateway credential contains an invalid scope")
    raw = "cxgw_" + secrets.token_urlsafe(30)
    credential_id = _id("GWC")
    connection.execute(
        "INSERT INTO CX_MODEL_GATEWAY_CREDENTIALS(CREDENTIAL_ID,DISPLAY_NAME,TOKEN_DIGEST,SCOPES_JSON,STATUS,EXPIRES_AT,CREATED_BY) "
        "VALUES(:id,:name,:digest,:scopes,'ACTIVE',:credential_expires_at,:actor)",
        {"id": credential_id, "name": name[:160], "digest": _token(raw), "scopes": json.dumps(normalized_scopes[:50]), "credential_expires_at": expires_at or None, "actor": actor},
    )
    return {"credential_id": credential_id, "token": raw, "display_name": name[:160], "status": "ACTIVE", "scopes": normalized_scopes[:50], "expires_at": expires_at}


def revoke_gateway_credential(actor: str, credential_id: str, reason: str) -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "model_gateway.manage")
    if access.get("decision") != "ALLOW": access = identity_api.effective_access(actor, "platform.manage")
    if access.get("decision") != "ALLOW":
        raise PermissionError("model gateway management permission is required")
    changed = connection.execute("UPDATE CX_MODEL_GATEWAY_CREDENTIALS SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKED_BY=:actor,REVOKE_REASON=:reason WHERE CREDENTIAL_ID=:id AND STATUS='ACTIVE'", {"actor": actor, "reason": reason[:500], "id": credential_id})
    return {"credential_id": credential_id, "status": "REVOKED", "changed": int(changed or 0)}


def _credential(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    return _row(connection.execute_query_one("SELECT CREDENTIAL_ID,DISPLAY_NAME,SCOPES_JSON,STATUS,EXPIRES_AT,CREATED_BY FROM CX_MODEL_GATEWAY_CREDENTIALS WHERE TOKEN_DIGEST=:digest AND STATUS='ACTIVE' AND (EXPIRES_AT IS NULL OR EXPIRES_AT>CURRENT_TIMESTAMP)", {"digest": _token(raw)})) or None


def authenticate_gateway_credential(raw: str, profile_id: str, agent_id: str = "") -> Dict[str, Any]:
    credential = _credential(raw)
    if not credential:
        raise PermissionError("model gateway credential is invalid")
    try:
        scopes = json.loads(credential.get("scopes_json") or "[]")
    except (TypeError, ValueError):
        scopes = []
    if not isinstance(scopes, list) or "model.forward" not in scopes:
        raise PermissionError("model gateway credential is invalid")
    profiles = {str(item).split(":", 1)[1] for item in scopes if str(item).startswith("profile:")}
    agents = {str(item).split(":", 1)[1] for item in scopes if str(item).startswith("agent:")}
    if profiles and profile_id not in profiles:
        raise PermissionError("model gateway credential is invalid")
    if agents and (not agent_id or agent_id not in agents):
        raise PermissionError("model gateway credential is invalid")
    return {
        "credential_id": str(credential["credential_id"]),
        "actor_principal_id": str(credential["created_by"]),
        "scopes": scopes,
    }


def _authorize_forward(actor: str, gateway_token: str, profile_id: str, agent_id: str) -> str:
    if gateway_token:
        return str(authenticate_gateway_credential(gateway_token, profile_id, agent_id)["actor_principal_id"])
    access = identity_api.effective_access(actor, "model_gateway.forward")
    if access.get("decision") != "ALLOW":
        raise PermissionError("model gateway forwarding permission is required")
    return actor


def _forward_context(actor: str, gateway_token: str, profile_id: str, agent_id: str) -> Dict[str, str]:
    if gateway_token:
        credential = authenticate_gateway_credential(gateway_token, profile_id, agent_id)
        return {"actor": str(credential["actor_principal_id"]), "credential_id": str(credential["credential_id"])}
    return {"actor": _authorize_forward(actor, "", profile_id, agent_id), "credential_id": ""}


def _reserve_idempotency(actor: str, key: str, input_digest: str) -> None:
    if not key:
        return
    existing = _row(connection.execute_query_one(
        "SELECT REQUEST_ID,INPUT_DIGEST,STATUS FROM CX_MODEL_REQUESTS "
        "WHERE ACTOR_PRINCIPAL_ID=:actor AND IDEMPOTENCY_KEY=:key",
        {"actor": actor, "key": key[:160]},
    ))
    if not existing:
        return
    if str(existing.get("input_digest") or "") != input_digest:
        raise ModelUsageConflict("idempotency key was already used for a different request")
    raise ModelUsageConflict("request with this idempotency key already exists")


def _idempotent_replay(actor: str, key: str, input_digest: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    existing = _row(connection.execute_query_one(
        "SELECT REQUEST_ID,INPUT_DIGEST,STATUS FROM CX_MODEL_REQUESTS WHERE ACTOR_PRINCIPAL_ID=:actor AND IDEMPOTENCY_KEY=:key",
        {"actor": actor, "key": key[:160]},
    ))
    if not existing:
        return None
    if str(existing.get("input_digest") or "") != input_digest:
        raise ModelUsageConflict("idempotency key was already used for a different request")
    if str(existing.get("status") or "").upper() == "SUCCEEDED":
        return model_governance_api.replay_snapshot(str(existing["request_id"]))
    raise ModelUsageConflict("request with this idempotency key is still occupied")


def _usage(result: Dict[str, Any]) -> Dict[str, Optional[int]]:
    usage = result.get("usage") or {}
    def n(*keys: str) -> Optional[int]:
        for key in keys:
            if usage.get(key) is not None:
                try: return max(0, int(usage[key]))
                except (TypeError, ValueError): return None
        return None
    prompt, completion = n("prompt_tokens", "input_tokens"), n("completion_tokens", "output_tokens")
    total = n("total_tokens")
    if total is None and prompt is not None and completion is not None: total = prompt + completion
    def detail(parent: str, field: str) -> Optional[int]:
        value = usage.get(parent)
        if not isinstance(value, dict) or value.get(field) is None:
            return None
        try:
            return max(0, int(value[field]))
        except (TypeError, ValueError, OverflowError):
            return None
    cached = n("cached_tokens", "cache_read_input_tokens")
    if cached is None:
        cached = detail("prompt_tokens_details", "cached_tokens")
    reasoning = n("reasoning_tokens")
    if reasoning is None:
        reasoning = detail("completion_tokens_details", "reasoning_tokens")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "cached_tokens": cached, "reasoning_tokens": reasoning, "total_tokens": total}


def _price(provider: str, model: str, usage: Dict[str, Optional[int]]) -> Dict[str, Any]:
    row = _row(connection.execute_query_one("SELECT PRICE_ID,PRICING_VERSION,CURRENCY,INPUT_PER_MILLION,OUTPUT_PER_MILLION,CACHE_PER_MILLION,REASONING_PER_MILLION FROM CX_MODEL_PRICING WHERE PROVIDER_KEY=:provider AND MODEL_ID=:model AND STATUS='ACTIVE' AND EFFECTIVE_FROM<=CURRENT_TIMESTAMP AND (EFFECTIVE_TO IS NULL OR EFFECTIVE_TO>CURRENT_TIMESTAMP) ORDER BY EFFECTIVE_FROM DESC FETCH FIRST 1 ROWS ONLY", {"provider": provider[:128], "model": model[:256]}))
    if not row: return {"cost": None, "currency": "", "pricing_version": ""}
    cost = Decimal("0")
    # Chat-completion detail counts are subsets of input/output totals.
    # A missing detail tariff keeps those tokens on the ordinary tariff.
    for total_field, detail_field, ordinary_rate, detail_rate in (
        ("prompt_tokens", "cached_tokens", "input_per_million", "cache_per_million"),
        ("completion_tokens", "reasoning_tokens", "output_per_million", "reasoning_per_million"),
    ):
        total_count = usage.get(total_field)
        detail_count = usage.get(detail_field) or 0
        if total_count is None or detail_count < 0 or detail_count > total_count:
            return {"cost": None, "currency": str(row.get("currency") or ""), "pricing_version": str(row.get("pricing_version") or "")}
        split = detail_count if row.get(detail_rate) is not None else 0
        for count, rate in ((total_count - split, ordinary_rate), (split, detail_rate)):
            if count and row.get(rate) is None:
                return {"cost": None, "currency": str(row.get("currency") or ""), "pricing_version": str(row.get("pricing_version") or "")}
            if count:
                cost += Decimal(str(count)) * Decimal(str(row[rate])) / Decimal("1000000")
    return {"cost": str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)), "currency": str(row.get("currency") or ""), "pricing_version": str(row.get("pricing_version") or "")}


def _write_usage(request_id: str, actor: str, agent_id: str, provider: str, model: str, usage: Dict[str, Optional[int]], provenance: str, started: float, status: str, idempotency_key: str = "") -> Dict[str, Any]:
    total = usage.get("total_tokens")
    if total is None and usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None:
        total = int(usage["prompt_tokens"] or 0) + int(usage["completion_tokens"] or 0)
        usage["total_tokens"] = total
    pricing = _price(provider, model, usage)
    usage_id = _id("USG")
    connection.execute("INSERT INTO CX_MODEL_USAGE(USAGE_ID,REQUEST_ID,ACTOR_PRINCIPAL_ID,AGENT_ID,PROVIDER_KEY,MODEL_ID,PROMPT_TOKENS,COMPLETION_TOKENS,CACHED_TOKENS,REASONING_TOKENS,TOTAL_TOKENS,USAGE_PROVENANCE,COST,CURRENCY,PRICING_VERSION,STATUS,LATENCY_MS,IDEMPOTENCY_KEY) VALUES(:id,:request,:actor,:agent,:provider,:model,:prompt,:completion,:cached,:reasoning,:total,:provenance,:cost,:currency,:price,:status,:latency,:key)", {"id": usage_id, "request": request_id, "actor": actor, "agent": agent_id or None, "provider": provider, "model": model, "prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"), "cached": usage.get("cached_tokens"), "reasoning": usage.get("reasoning_tokens"), "total": usage.get("total_tokens"), "provenance": provenance, "cost": pricing["cost"], "currency": pricing["currency"], "price": pricing["pricing_version"], "status": status, "latency": int(max(0, (time.monotonic()-started)*1000)), "key": idempotency_key[:160] or None})
    model_governance_api.settle_quota(request_id, total, pricing["cost"], pricing["currency"], incomplete=provenance == "INCOMPLETE")
    return {"usage_id": usage_id, "request_id": request_id, **usage, "usage_provenance": provenance, "cost": pricing["cost"], "currency": pricing["currency"], "pricing_version": pricing["pricing_version"]}


def forward(actor: str, provider_profile_id: str, messages: List[Dict[str, Any]], *, agent_id: str = "", stream: bool = False, idempotency_key: str = "", gateway_token: str = "", correlation_id: str = "") -> Dict[str, Any]:
    context = _forward_context(actor, gateway_token, provider_profile_id, agent_id); actor = context["actor"]
    if not isinstance(messages, list) or not messages or len(messages) > 100:
        raise ModelUsageError("messages must contain between 1 and 100 items")
    profile = _row(connection.execute_query_one("SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,STATUS,API_KEY_CIPHER FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": provider_profile_id}))
    if not profile: raise ModelUsageError("LLM provider profile is unavailable")
    request_id = _id("LMR"); started = time.monotonic(); input_digest = _digest(messages)
    replay = _idempotent_replay(actor, idempotency_key, input_digest)
    if replay is not None:
        return replay
    _reserve_idempotency(actor, idempotency_key, input_digest)
    connection.execute("INSERT INTO CX_MODEL_REQUESTS(REQUEST_ID,ACTOR_PRINCIPAL_ID,AGENT_ID,PROFILE_ID,MODEL_ID,STATUS,IDEMPOTENCY_KEY,INPUT_DIGEST,CORRELATION_ID,CREDENTIAL_ID) VALUES(:id,:actor,:agent,:profile,:model,'AUTHORIZED',:key,:digest,:correlation,:credential)", {"id": request_id, "actor": actor, "agent": agent_id or None, "profile": provider_profile_id, "model": profile.get("model_id"), "key": idempotency_key[:160] or request_id, "digest": input_digest, "correlation": correlation_id[:128] or request_id, "credential": context["credential_id"] or None})
    try:
        quota = model_governance_api.reserve_quota(request_id, actor, context["credential_id"], agent_id, provider_profile_id, str(profile.get("model_id") or ""))
    except model_governance_api.QuotaExceeded:
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='QUOTA_REJECTED',ERROR_CATEGORY='QUOTA_EXCEEDED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id})
        raise
    provider_url = str(profile.get("provider_url") or "").rstrip("/") + "/chat/completions"
    payload = json.dumps({"model": profile.get("model_id"), "messages": messages, "stream": bool(stream), "stream_options": {"include_usage": True} if stream else None}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json"}
    cipher = str(profile.get("api_key_cipher") or "")
    if cipher:
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(cipher).get("api_key") or "")
        if secret: headers["Authorization"] = "Bearer " + secret
    req = urllib.request.Request(provider_url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ModelUsageError("model provider response exceeded the configured limit")
        result = json.loads(raw.decode("utf-8"))
        usage = _usage(result)
        record = _write_usage(request_id, actor, agent_id, str(profile.get("profile_key") or provider_profile_id), str(result.get("model") or profile.get("model_id")), usage, "PROVIDER_REPORTED" if usage.get("total_tokens") is not None else "INCOMPLETE", started, "SUCCEEDED", idempotency_key)
        response_payload = {"request_id": request_id, "model": result.get("model") or profile.get("model_id"), "choices": result.get("choices") or [], "usage": record, "quota_warnings": quota["warnings"], "correlation_id": correlation_id[:128] or request_id}
        model_governance_api.finalize_replayable_success(request_id, response_payload)
        return response_payload
    except (model_governance_api.ModelGovernanceError, ModelUsageError):
        model_governance_api.release_quota(request_id)
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='FAILED',ERROR_CATEGORY='GOVERNED_REQUEST_FAILED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id AND STATUS<>'SUCCEEDED'", {"id": request_id})
        raise
    except Exception as exc:
        model_governance_api.release_quota(request_id)
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='FAILED',ERROR_CATEGORY='PROVIDER_UNAVAILABLE',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id})
        raise ModelUsageError("model provider request failed") from exc


def stream_forward(actor: str, provider_profile_id: str, messages: List[Dict[str, Any]], *, agent_id: str = "", idempotency_key: str = "", gateway_token: str = "", correlation_id: str = "") -> Iterable[bytes]:
    """Yield provider SSE data while reconciling terminal usage exactly once."""
    context = _forward_context(actor, gateway_token, provider_profile_id, agent_id); actor = context["actor"]
    if not isinstance(messages, list) or not messages or len(messages) > 100:
        raise ModelUsageError("messages must contain between 1 and 100 items")
    profile = _row(connection.execute_query_one("SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,STATUS,API_KEY_CIPHER FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": provider_profile_id}))
    if not profile: raise ModelUsageError("LLM provider profile is unavailable")
    request_id, started, input_digest = _id("LMR"), time.monotonic(), _digest(messages)
    _reserve_idempotency(actor, idempotency_key, input_digest)
    connection.execute("INSERT INTO CX_MODEL_REQUESTS(REQUEST_ID,ACTOR_PRINCIPAL_ID,AGENT_ID,PROFILE_ID,MODEL_ID,STATUS,IDEMPOTENCY_KEY,INPUT_DIGEST,CORRELATION_ID,CREDENTIAL_ID) VALUES(:id,:actor,:agent,:profile,:model,'DISPATCHED',:key,:digest,:correlation,:credential)", {"id": request_id, "actor": actor, "agent": agent_id or None, "profile": provider_profile_id, "model": profile.get("model_id"), "key": idempotency_key[:160] or request_id, "digest": input_digest, "correlation": correlation_id[:128] or request_id, "credential": context["credential_id"] or None})
    try:
        model_governance_api.reserve_quota(request_id, actor, context["credential_id"], agent_id, provider_profile_id, str(profile.get("model_id") or ""))
    except model_governance_api.QuotaExceeded:
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='QUOTA_REJECTED',ERROR_CATEGORY='QUOTA_EXCEEDED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id})
        raise
    payload = json.dumps({"model": profile.get("model_id"), "messages": messages, "stream": True, "stream_options": {"include_usage": True}}, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    cipher = str(profile.get("api_key_cipher") or "")
    if cipher:
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(cipher).get("api_key") or "")
        if secret: headers["Authorization"] = "Bearer " + secret
    request = urllib.request.Request(str(profile.get("provider_url") or "").rstrip("/") + "/chat/completions", data=payload, headers=headers, method="POST")
    terminal: Dict[str, Any] = {}
    streamed_bytes = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw in response:
                streamed_bytes += len(raw)
                if len(raw) > 256 * 1024 or streamed_bytes > 8 * 1024 * 1024:
                    raise ModelUsageError("model provider stream exceeded the configured limit")
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"): continue
                item = line[5:].strip()
                if item != "[DONE]":
                    try:
                        payload_item = json.loads(item)
                        if payload_item.get("usage"): terminal = payload_item
                    except (TypeError, ValueError): pass
                yield ("data: " + item + "\n\n").encode("utf-8")
        usage = _usage(terminal)
        _write_usage(request_id, actor, agent_id, str(profile.get("profile_key") or provider_profile_id), str(terminal.get("model") or profile.get("model_id")), usage, "PROVIDER_REPORTED" if usage.get("total_tokens") is not None else "INCOMPLETE", started, "SUCCEEDED", idempotency_key)
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='SUCCEEDED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id})
    except Exception as exc:
        model_governance_api.settle_quota(request_id, None, None, "", incomplete=True)
        connection.execute("UPDATE CX_MODEL_REQUESTS SET STATUS='INCOMPLETE',ERROR_CATEGORY='STREAM_INTERRUPTED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id})
        raise ModelUsageError("model provider streaming request failed") from exc


def usage_summary(actor: str, limit: int = 30, resource_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _scope(actor); limit = max(1, min(int(limit or 30), 100))
    visibility, params = _usage_scope(actor, resource_scope=resource_scope)
    rows = connection.execute_query("SELECT PROVIDER_KEY,MODEL_ID,USAGE_PROVENANCE,COUNT(*) AS REQUESTS,COALESCE(SUM(TOTAL_TOKENS),0) AS TOTAL_TOKENS,COALESCE(SUM(COST),0) AS COST,CURRENCY,MAX(CREATED_AT) AS LAST_SEEN FROM CX_MODEL_USAGE u WHERE " + visibility + " GROUP BY PROVIDER_KEY,MODEL_ID,USAGE_PROVENANCE,CURRENCY ORDER BY LAST_SEEN DESC FETCH FIRST 100 ROWS ONLY", params)
    external = model_governance_api.external_coverage(actor, resource_scope)
    observed_requests = sum(int(_row(row).get("requests") or 0) for row in rows)
    return {"items": [{str(k).lower(): v for k, v in dict(row).items()} for row in rows[:limit]], "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "scope": "authorized", "coverage": {"gateway_observed_requests": observed_requests, **external, "unknown_direct_activity": True}}


def wallboard(actor: str, definition_id: str = "") -> Dict[str, Any]:
    access = identity_api.effective_access(actor, "wallboard.read")
    if access.get("decision") != "ALLOW": raise PermissionError("wallboard permission is required")
    definition = model_governance_api.resolve_wallboard_definition(actor, definition_id)
    usage = usage_summary(actor, 10, definition["scope"])
    visibility, params = _usage_scope(actor, resource_scope=definition["scope"])
    trend_rows = connection.execute_query(
        "SELECT CREATED_AT,TOTAL_TOKENS,COST,USAGE_PROVENANCE FROM CX_MODEL_USAGE "
        "u WHERE " + visibility + " ORDER BY CREATED_AT DESC FETCH FIRST 2000 ROWS ONLY",
        params,
    )
    from datetime import date, datetime, timedelta
    today = date.today()
    buckets = {today - timedelta(days=offset): {"tokens": 0, "cost": 0.0, "requests": 0, "observed": 0} for offset in range(13, -1, -1)}
    for item in trend_rows:
        row = _row(item)
        created = row.get("created_at")
        if isinstance(created, datetime): day = created.date()
        elif isinstance(created, date): day = created
        else:
            try: day = datetime.fromisoformat(str(created).replace("Z", "+00:00")).date()
            except (TypeError, ValueError): continue
        bucket = buckets.get(day)
        if bucket is None: continue
        bucket["requests"] += 1
        bucket["tokens"] += int(row.get("total_tokens") or 0)
        try: bucket["cost"] += float(row.get("cost") or 0)
        except (TypeError, ValueError): pass
        if str(row.get("usage_provenance") or "").upper() == "PROVIDER_REPORTED": bucket["observed"] += 1
    from . import monitor_api
    runtime_error = False
    try:
        runtime = monitor_api.get_system_overview(actor, definition["scope"])
    except Exception:
        # An unavailable source is not an empty source. Keep the public error
        # bounded while allowing readers to distinguish degraded data from a
        # genuine, successfully queried zero.
        runtime_error = True
        runtime = {"agents": {"total": None, "online": None, "busy": None, "idle": None, "dormant": None}, "sessions": {"active": None}, "tasks": {"running_plans": None, "running_loops": None}, "stalled_count": None}
    native_agents = _row(connection.execute_query_one(
        "SELECT COUNT(*) AS TOTAL, SUM(CASE WHEN n.STATUS='ACTIVE' THEN 1 ELSE 0 END) AS ACTIVE "
        "FROM CX_NATIVE_AGENTS n", {},
    ))
    runtime_agents = _row(runtime.get("agents") or {})
    quota_scope, quota_params = _usage_scope(actor, "r", definition["scope"])
    budget = _row(connection.execute_query_one("SELECT COUNT(*) AS POLICIES,COALESCE(SUM(CASE WHEN q.WARNING IS NOT NULL THEN 1 ELSE 0 END),0) AS WARNINGS,COALESCE(SUM(CASE WHEN r.STATUS='QUOTA_REJECTED' THEN 1 ELSE 0 END),0) AS REJECTIONS FROM CX_MODEL_QUOTA_RESERVATIONS q JOIN CX_MODEL_REQUESTS r ON r.REQUEST_ID=q.REQUEST_ID WHERE " + quota_scope, quota_params))
    runtime_metric = lambda key: None if runtime_error else int(runtime_agents.get(key) or 0)
    payload = {"definition_id": definition["definition_id"], "definition_version": definition["version"], "definition_name": definition["display_name"], "widgets": definition["config"]["widgets"], "refresh_seconds": definition["config"]["refresh_seconds"], "generated_at": usage["generated_at"], "freshness": "DEGRADED" if runtime_error else "CURRENT", "scope": "authorized", "partial": runtime_error,
            "sources": {"runtime": {"status": "UNAVAILABLE" if runtime_error else "CURRENT", "error_code": "RUNTIME_OVERVIEW_UNAVAILABLE" if runtime_error else None}, "model_usage": {"status": "CURRENT", "error_code": None}},
            "agents": {"total": runtime_metric("total"), "online": runtime_metric("online"), "busy": runtime_metric("busy"), "native_total": int(native_agents.get("total") or 0), "native_active": int(native_agents.get("active") or 0)},
            "runtime": runtime, "model_usage": usage["items"], "usage_trend": [{"day": day.isoformat(), **value} for day, value in buckets.items()], "coverage": usage["coverage"], "budget": {"policies": int(budget.get("policies") or 0), "warnings": int(budget.get("warnings") or 0), "rejections": int(budget.get("rejections") or 0)}}
    return model_governance_api.filter_wallboard_projection(payload, definition)
