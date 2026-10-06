"""Actual version-bound Provider probes, retaining only redacted evidence."""

from datetime import datetime, timedelta, timezone
import json
import base64
import struct
import time
import urllib.error
import urllib.request
import zlib
from jsonschema.exceptions import SchemaError, ValidationError

from . import connection, identity_api, native_agent_api
from .agent_extension_contracts import canonical, digest, identifier, opener, registered_url, row, validate_schema
from .effective_capabilities import authorize

CAPABILITIES = frozenset({"TEXT", "STREAM", "STRUCTURED_OUTPUT", "TOOL_PROPOSAL", "REASONING_PARAMETERS", "CLIENT_CANCELLATION", "USAGE", "IMAGE_INPUT"})
PARAMETER_KEYS = frozenset({"reasoning_effort", "preserve_thinking"})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PROBE_SCHEMA = {"type": "object", "properties": {"ok": {"const": "CX_OK"}}, "required": ["ok"], "additionalProperties": False}


def _image_probe():
    def chunk(name, content):
        return struct.pack(">I", len(content)) + name + content + struct.pack(">I", zlib.crc32(name + content))
    pixels = (b"\x00" + b"\xff\x00\x00" * 32) * 32
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode("ascii")


def parameters(value):
    if not isinstance(value, dict) or set(value) - PARAMETER_KEYS:
        raise ValueError("Only registered reasoning parameters may be probed")
    if "reasoning_effort" in value and value["reasoning_effort"] not in {"none", "minimal", "low", "medium", "high", "max"}:
        raise ValueError("Unsupported reasoning effort value")
    if "preserve_thinking" in value and not isinstance(value["preserve_thinking"], bool):
        raise ValueError("preserve_thinking must be boolean")
    return dict(value)


def _profile(actor, profile_id):
    authorize(actor)
    profile = row(connection.execute_query_one(
        "SELECT PROFILE_ID,VERSION,PROVIDER_URL,MODEL_ID,API_KEY_CIPHER,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile",
        {"profile": profile_id},
    ))
    if not profile or profile.get("status") != "ACTIVE":
        raise ValueError("Active Provider Profile is required")
    registered_url(profile["provider_url"])
    return profile


def payload(capability, model_id, parameter_values):
    if capability not in CAPABILITIES:
        raise ValueError("Unknown Provider probe capability")
    result = {"model": model_id, "max_tokens": 512, "temperature": 0, "stream": capability in {"STREAM", "CLIENT_CANCELLATION"},
              "messages": [{"role": "user", "content": "Reply with exactly CX_OK and no other text."}], **parameters(parameter_values)}
    if capability == "STRUCTURED_OUTPUT":
        result["messages"] = [{"role": "user", "content": 'Return exactly the JSON object {"ok":"CX_OK"}.'}]
        result["response_format"] = {"type": "json_schema", "json_schema": {"name": "chuanxu_probe", "strict": True, "schema": PROBE_SCHEMA}}
    elif capability == "TOOL_PROPOSAL":
        result["messages"] = [{"role": "user", "content": "Propose calling cx_probe with ok set to CX_OK. Do not execute anything."}]
        result["tools"] = [{"type": "function", "function": {"name": "cx_probe", "description": "A probe-only function which is never executed", "parameters": PROBE_SCHEMA}}]
        # A single advertised function and required selection verifies the
        # proposal without relying on a provider's named-choice extension.
        result["tool_choice"] = "required"
    elif capability == "IMAGE_INPUT":
        # Verify image content, not just acceptance of an ignored image field.
        result["messages"] = [{"role": "user", "content": [{"type": "text", "text": "Identify the dominant color of this image. Reply with only its uppercase English color name."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _image_probe()}}]}]
    if result["stream"]:
        result["stream_options"] = {"include_usage": True}
    return result


def _usage(value):
    if not isinstance(value, dict):
        return {}
    return {key: int(value[key]) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(value.get(key), int) and not isinstance(value[key], bool) and value[key] >= 0}


def observe_json(capability, profile, value):
    if not isinstance(value, dict) or not native_agent_api._llm_model_matches(profile["model_id"], str(value.get("model") or "")):
        raise ValueError("MODEL_MISMATCH")
    choices = value.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ValueError("EMPTY_COMPLETION")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise ValueError("INVALID_COMPLETION")
    content = message.get("content") or ""
    observation = {"observed_model": str(value["model"]), "finish_reason": str(choices[0].get("finish_reason") or "unknown"),
                   "reasoning_present": bool(message.get("reasoning_content")), "usage": _usage(value.get("usage")),
                   "output_digest": digest({"content": content, "tool_calls": message.get("tool_calls") or []})}
    if capability == "STRUCTURED_OUTPUT":
        validate_schema(PROBE_SCHEMA, json.loads(content))
        observation["schema_valid"] = True
    elif capability == "TOOL_PROPOSAL":
        calls = message.get("tool_calls") or []
        if len(calls) != 1 or calls[0].get("type") != "function" or (calls[0].get("function") or {}).get("name") != "cx_probe":
            raise ValueError("TOOL_PROPOSAL_MISMATCH")
        validate_schema(PROBE_SCHEMA, json.loads(calls[0]["function"]["arguments"]))
        observation["tool_proposal_valid"] = True
    elif not isinstance(content, str) or content.strip() != ("RED" if capability == "IMAGE_INPUT" else "CX_OK"):
        raise ValueError("PROBE_ANSWER_MISMATCH")
    if capability == "USAGE" and not {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(observation["usage"]):
        raise ValueError("USAGE_UNAVAILABLE")
    return observation


def _send(profile, request_payload, timeout, capability):
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if request_payload["stream"] else "application/json"}
    if profile.get("api_key_cipher"):
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(str(profile["api_key_cipher"])).get("api_key") or "")
        if secret:
            headers["Authorization"] = "Bearer " + secret
    request = urllib.request.Request(registered_url(profile["provider_url"]) + "/chat/completions",
                                     data=canonical(request_payload).encode("utf-8"), headers=headers, method="POST")
    started = time.monotonic()
    with opener().open(request, timeout=timeout) as response:
        if not request_payload["stream"]:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("RESPONSE_TOO_LARGE")
            return observe_json(capability, profile, json.loads(raw))
        pieces, usage, seen_model = [], {}, ""
        total, first_token_ms, finished, reasoning_present = 0, None, False, False
        while True:
            if time.monotonic() - started > timeout:
                raise TimeoutError("PROBE_DEADLINE")
            raw_line = response.readline(65537)
            if not raw_line:
                break
            total += len(raw_line)
            if len(raw_line) > 65536 or total > MAX_RESPONSE_BYTES:
                raise ValueError("STREAM_TOO_LARGE")
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            item = json.loads(data)
            seen_model = str(item.get("model") or seen_model)
            usage.update(_usage(item.get("usage")))
            for choice in item.get("choices") or []:
                delta = choice.get("delta") or {}
                reasoning_present = reasoning_present or bool(delta.get("reasoning_content"))
                if choice.get("finish_reason"):
                    finished = True
                piece = delta.get("content") or ""
                if piece:
                    if not isinstance(piece, str):
                        raise ValueError("INVALID_STREAM_CONTENT")
                    if first_token_ms is None:
                        first_token_ms = round((time.monotonic() - started) * 1000)
                    pieces.append(piece)
                    if capability == "CLIENT_CANCELLATION":
                        if not native_agent_api._llm_model_matches(profile["model_id"], seen_model):
                            raise ValueError("MODEL_MISMATCH")
                        return {"observed_model": seen_model, "first_token_ms": first_token_ms,
                                "client_stream_closed": True, "provider_cancellation_confirmed": False,
                                "reasoning_present": reasoning_present}
        if not finished or not native_agent_api._llm_model_matches(profile["model_id"], seen_model) or "".join(pieces).strip() != "CX_OK":
            raise ValueError("STREAM_COMPLETION_MISMATCH")
        return {"observed_model": seen_model, "first_token_ms": first_token_ms, "stream_completed": True,
                "reasoning_present": reasoning_present, "usage": usage, "output_digest": digest("".join(pieces))}


def probe(actor, profile_id, capability, parameter_values=None, *, timeout=30):
    profile = _profile(actor, profile_id)
    selected = parameters(parameter_values or {})
    capability = str(capability).upper()
    request_payload = payload(capability, profile["model_id"], selected)
    timeout = max(1, min(int(timeout), 60))
    probe_id = identifier("PCP")
    schema_digest = digest(PROBE_SCHEMA if capability in {"STRUCTURED_OUTPUT", "TOOL_PROPOSAL"} else {})
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None)
    def reserve(tx):
        current = row(tx.query_one("SELECT VERSION,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile FOR UPDATE", {"profile": profile_id}))
        if current.get("status") != "ACTIVE" or int(current.get("version") or 0) != int(profile["version"]):
            raise ValueError("Provider Profile changed before its probe")
        tx.execute("INSERT INTO CX_PROVIDER_CAP_PROBES(PROBE_ID,PROFILE_ID,PROFILE_VERSION,MODEL_ID,API_DIALECT,CAPABILITY_KEY,STATUS,PARAMETER_DIGEST,SCHEMA_DIGEST,EXPIRES_AT,ACTOR_ID) "
                   "VALUES(:probe,:profile,:version,:model,'CHAT_COMPLETIONS',:capability,'RUNNING',:parameters,:schema,:expires,:actor)",
                   {"probe": probe_id, "profile": profile_id, "version": int(profile["version"]), "model": profile["model_id"],
                    "capability": capability, "parameters": digest(selected), "schema": schema_digest, "expires": expires, "actor": actor})
    connection.execute_transaction_callback(reserve)
    started = time.monotonic()
    try:
        # Revalidate authority and configuration at the last pre-dispatch point.
        fresh = _profile(actor, profile_id)
        if fresh["version"] != profile["version"]:
            raise ValueError("PROFILE_CHANGED")
        observation = _send(fresh, request_payload, timeout, capability)
        status = "CLIENT_CANCELLED" if capability == "CLIENT_CANCELLATION" else "VERIFIED"
    except Exception as exc:
        code = "PROVIDER_UNAVAILABLE"
        if isinstance(exc, urllib.error.HTTPError):
            code = "HTTP_" + str(int(exc.code))
        elif isinstance(exc, TimeoutError):
            code = "TIMEOUT"
        elif isinstance(exc, (ValueError, TypeError, KeyError, SchemaError, ValidationError)):
            # Keep fixed validation codes, never provider output or secrets.
            known = {"MODEL_MISMATCH", "EMPTY_COMPLETION", "INVALID_COMPLETION", "TOOL_PROPOSAL_MISMATCH",
                     "PROBE_ANSWER_MISMATCH", "USAGE_UNAVAILABLE", "STREAM_COMPLETION_MISMATCH",
                     "RESPONSE_TOO_LARGE", "STREAM_TOO_LARGE", "INVALID_STREAM_CONTENT"}
            code = str(exc) if str(exc) in known else "INVALID_PROBE_RESULT"
        validation_failure = code in {"INVALID_PROBE_RESULT", "MODEL_MISMATCH", "EMPTY_COMPLETION", "INVALID_COMPLETION",
                                     "TOOL_PROPOSAL_MISMATCH", "PROBE_ANSWER_MISMATCH", "USAGE_UNAVAILABLE",
                                     "STREAM_COMPLETION_MISMATCH", "RESPONSE_TOO_LARGE", "STREAM_TOO_LARGE", "INVALID_STREAM_CONTENT"}
        observation, status = {"error_code": code}, "UNSUPPORTED" if code.startswith("HTTP_4") or validation_failure else "FAILED"
    observation["latency_ms"] = round((time.monotonic() - started) * 1000)
    def finish(tx):
        current = row(tx.query_one("SELECT VERSION,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile FOR UPDATE", {"profile": profile_id}))
        observed_status = status if current.get("status") == "ACTIVE" and int(current.get("version") or 0) == int(profile["version"]) else "STALE"
        tx.execute("UPDATE CX_PROVIDER_CAP_PROBES SET STATUS=:status,OBSERVATION_JSON=:observation,EVIDENCE_DIGEST=:digest,COMPLETED_AT=CURRENT_TIMESTAMP WHERE PROBE_ID=:probe AND STATUS='RUNNING'",
                   {"status": observed_status, "observation": canonical(observation), "digest": digest(observation), "probe": probe_id})
        identity_api._audit_tx(tx, actor, "PROVIDER_CAPABILITY_PROBE", "PROVIDER_PROFILE", profile_id, "ALLOW" if observed_status in {"VERIFIED", "CLIENT_CANCELLED"} else "DENY", capability)
        return {"probe_id": probe_id, "profile_id": profile_id, "profile_version": int(profile["version"]), "capability": capability,
                "status": observed_status, "observation": observation, "evidence_digest": digest(observation)}
    return connection.execute_transaction_callback(finish)


def list_probes(actor, profile_id):
    profile = _profile(actor, profile_id)
    return {"profile_id": profile_id, "profile_version": profile["version"], "items": [row(value) for value in connection.execute_query(
        "SELECT PROBE_ID,PROFILE_VERSION,CAPABILITY_KEY,STATUS,OBSERVATION_JSON,EVIDENCE_DIGEST,STARTED_AT,COMPLETED_AT,EXPIRES_AT FROM CX_PROVIDER_CAP_PROBES WHERE PROFILE_ID=:profile ORDER BY STARTED_AT DESC FETCH FIRST 100 ROWS ONLY",
        {"profile": profile_id},
    )]}


def approve_parameters(actor, profile_id, probe_id, parameter_values):
    profile = _profile(actor, profile_id)
    selected = parameters(parameter_values)
    if not selected:
        raise ValueError("At least one verified parameter is required")
    def perform(tx):
        current = row(tx.query_one("SELECT VERSION,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile FOR UPDATE", {"profile": profile_id}))
        evidence = row(tx.query_one("SELECT PROFILE_ID,PROFILE_VERSION,CAPABILITY_KEY,STATUS,PARAMETER_DIGEST FROM CX_PROVIDER_CAP_PROBES WHERE PROBE_ID=:probe AND EXPIRES_AT>CURRENT_TIMESTAMP", {"probe": probe_id}))
        if (current.get("status") != "ACTIVE" or current.get("version") != profile["version"] or
                evidence.get("profile_id") != profile_id or int(evidence.get("profile_version") or 0) != int(profile["version"]) or
                evidence.get("status") != "VERIFIED" or evidence.get("capability_key") != "REASONING_PARAMETERS" or
                evidence.get("parameter_digest") != digest(selected)):
            raise ValueError("Current successful probe evidence for these exact parameters is required")
        for key, value in selected.items():
            previous = row(tx.query_one("SELECT CONTRACT_DIGEST,STATUS FROM CX_PROVIDER_PARAM_CONTRACTS WHERE PROFILE_ID=:profile AND PROFILE_VERSION=:version AND PARAMETER_KEY=:parameter",
                                        {"profile": profile_id, "version": int(profile["version"]), "parameter": key}))
            contract = digest({"key": key, "value": value, "probe": probe_id})
            if previous:
                if previous.get("contract_digest") != contract or previous.get("status") != "ACTIVE":
                    raise ValueError("Parameter contracts are immutable; create a new Provider Profile revision")
                continue
            tx.execute("INSERT INTO CX_PROVIDER_PARAM_CONTRACTS(PROFILE_ID,PROFILE_VERSION,PARAMETER_KEY,VALUE_JSON,PROBE_ID,CONTRACT_DIGEST,STATUS,APPROVED_BY) VALUES(:profile,:version,:parameter,:value,:probe,:digest,'ACTIVE',:actor)",
                       {"profile": profile_id, "version": int(profile["version"]), "parameter": key, "value": canonical(value), "probe": probe_id, "digest": contract, "actor": actor})
        identity_api._audit_tx(tx, actor, "PROVIDER_PARAMETERS_APPROVED", "PROVIDER_PROFILE", profile_id, "ALLOW", "Exact tested parameter contract")
        return {"profile_id": profile_id, "profile_version": profile["version"], "parameters": selected}
    return connection.execute_transaction_callback(perform)


def request_parameters(profile_id, profile_version=None):
    """Only an active, unexpired contract for the current profile may be used."""
    from . import edition_features
    if not profile_id or not edition_features.AGENT_EXTENSIONS_ENABLED:
        return {}
    current = row(connection.execute_query_one(
        "SELECT VERSION,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile", {"profile": profile_id},
    ))
    if (current.get("status") != "ACTIVE" or profile_version is not None and
            int(current.get("version") or 0) != int(profile_version)):
        raise PermissionError("Provider Profile changed before model dispatch")
    records = connection.execute_query(
        "SELECT p.PARAMETER_KEY,p.VALUE_JSON FROM CX_PROVIDER_PARAM_CONTRACTS p "
        "JOIN CX_LLM_PROVIDER_PROFILES f ON f.PROFILE_ID=p.PROFILE_ID AND f.VERSION=p.PROFILE_VERSION "
        "JOIN CX_PROVIDER_CAP_PROBES e ON e.PROBE_ID=p.PROBE_ID AND e.PROFILE_VERSION=f.VERSION "
        "WHERE p.PROFILE_ID=:profile AND p.STATUS='ACTIVE' AND f.STATUS='ACTIVE' AND e.STATUS='VERIFIED' AND e.EXPIRES_AT>CURRENT_TIMESTAMP",
        {"profile": profile_id},
    )
    return parameters({row(value)["parameter_key"]: json.loads(row(value)["value_json"]) for value in records})


def apply_parameters(profile, request_payload):
    """Apply only the verified current-revision contract to a fresh request."""
    return {**request_payload, **request_parameters(profile.get("profile_id"), profile.get("version"))}
