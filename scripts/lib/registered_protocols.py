"""Registered, scoped MCP transports with exact approved tool contracts."""
from datetime import timedelta
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import connection, identity_api, effective_capabilities, agent_gateway_api
from . import continuity_work as work
from .continuity_bindings import _transport
from .connection_crypto import encrypt_section, decrypt_section
from .agent_extension_contracts import bounded_json, canonical, digest, identifier, opener, registered_url, row, safe_key, validate_schema

MCP_VERSIONS = frozenset({"2025-06-18", "2025-11-25"})
TRANSPORTS = {"MCP": "STREAMABLE_HTTP", "A2A": "HTTP_JSON", "OTLP": "HTTP_PROTO_JSON"}


def _human_admin(actor):
    effective_capabilities.authorize(actor)
    principal = row(connection.execute_query_one("SELECT PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor", {"actor": actor}))
    if principal.get("principal_type") != "HUMAN" or principal.get("status") != "ACTIVE":
        raise PermissionError("An active authorized Human must manage integrations")


def register(actor, value):
    _human_admin(actor)
    kind = value.get("protocol_kind")
    if kind not in TRANSPORTS:
        raise ValueError("Unsupported registered protocol")
    url = registered_url(value.get("endpoint_url"))
    version = str(value.get("protocol_version") or "")
    if ((kind == "MCP" and version not in MCP_VERSIONS) or (kind == "A2A" and version != "1.0.1") or
            (kind == "OTLP" and version != "1.9.0")):
        raise ValueError("Unsupported protocol version")
    if not 1 <= int(value.get("timeout_seconds", 30)) <= 60 or not 1024 <= int(value.get("max_response_bytes", 1048576)) <= 4194304:
        raise ValueError("Integration limits are invalid")
    issuer, resource = str(value.get("issuer_url") or ""), str(value.get("resource_url") or "")
    if bool(issuer) != bool(resource):
        raise ValueError("Issuer and resource must be registered together")
    if issuer:
        issuer, resource = registered_url(issuer), registered_url(resource)
        if urlsplit(resource).netloc != urlsplit(url).netloc:
            raise ValueError("The registered authentication resource must match the service origin")
    name, reason = str(value.get("endpoint_name") or ""), str(value.get("reason") or "")
    if not 1 <= len(name.strip()) <= 256 or not 3 <= len(reason.strip()) <= 2000:
        raise ValueError("Integration name and reason are required")
    bearer = value.get("bearer_token", "")
    if not isinstance(bearer, str) or len(bearer) > 4096 or any(ord(char) < 32 for char in bearer):
        raise ValueError("Invalid registered authentication value")
    endpoint_id = str(value.get("endpoint_id") or identifier("PE"))
    contract = {"endpoint_url": url, "protocol_kind": kind, "protocol_version": version,
                "transport_kind": TRANSPORTS[kind], "issuer_url": issuer, "resource_url": resource,
                "sdk_version": "mcp==1.28.1" if kind == "MCP" else "chuanxu-bounded-http/1",
                "timeout_seconds": int(value.get("timeout_seconds", 30)), "max_response_bytes": int(value.get("max_response_bytes", 1048576))}
    def perform(tx):
        _human_admin(actor)
        work._lock_actor(tx, actor)
        work._authorize(tx, actor, value["security_domain_id"], write=True)
        previous = row(tx.query_one("SELECT * FROM CX_PROTOCOL_ENDPOINTS WHERE ENDPOINT_ID=:endpoint FOR UPDATE", {"endpoint": endpoint_id}))
        revision = 1
        if previous:
            if (previous["owner_id"] != actor or previous["security_domain_id"] != value["security_domain_id"] or
                    previous["protocol_kind"] != kind or int(previous["version"]) != int(value.get("expected_version", 0))):
                raise ValueError("Integration ownership or version changed")
            revision = int(previous["current_revision"]) + 1
            tx.execute("UPDATE CX_PROTOCOL_ENDPOINTS SET ENDPOINT_NAME=:name,CURRENT_REVISION=:revision,AUTH_CIPHER=:auth,STATUS='ACTIVE',VERSION=VERSION+1,UPDATED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE ENDPOINT_ID=:endpoint",
                {"name": name, "revision": revision, "auth": encrypt_section({"bearer_token": bearer}), "actor": actor, "reason": reason, "endpoint": endpoint_id})
        else:
            tx.execute("INSERT INTO CX_PROTOCOL_ENDPOINTS(ENDPOINT_ID,ENDPOINT_NAME,PROTOCOL_KIND,OWNER_ID,SECURITY_DOMAIN_ID,CURRENT_REVISION,STATUS,AUTH_CIPHER,UPDATED_BY,REASON) VALUES(:endpoint,:name,:kind,:actor,:domain,1,'ACTIVE',:auth,:actor,:reason)",
                {"endpoint": endpoint_id, "name": name, "kind": kind, "actor": actor, "domain": value["security_domain_id"], "auth": encrypt_section({"bearer_token": bearer}), "reason": reason})
        tx.execute("INSERT INTO CX_PROTOCOL_REVISIONS(ENDPOINT_ID,REVISION_NO,ENDPOINT_URL,TRANSPORT_KIND,PROTOCOL_VERSION,SDK_VERSION,ISSUER_URL,RESOURCE_URL,CONTRACT_DIGEST,TIMEOUT_SECONDS,MAX_RESPONSE_BYTES,REGISTERED_BY) VALUES(:endpoint,:revision,:url,:transport,:protocol,:sdk,:issuer,:resource_url,:digest,:timeout,:maximum,:actor)",
            {"endpoint": endpoint_id, "revision": revision, "url": url, "transport": TRANSPORTS[kind], "protocol": version, "sdk": contract["sdk_version"], "issuer": issuer or None, "resource_url": resource or None,
             "digest": digest(contract), "timeout": contract["timeout_seconds"], "maximum": contract["max_response_bytes"], "actor": actor})
        identity_api._audit_tx(tx, actor, "INTEGRATION_REGISTERED", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", reason)
        return {"endpoint_id": endpoint_id, "revision_no": revision, "version": int(previous.get("version", 0)) + 1, "status": "ACTIVE", "contract_digest": digest(contract)}
    return connection.execute_transaction_callback(perform)


def endpoint(actor, endpoint_id, *, kind=None, tx=None):
    query_one = tx.query_one if tx is not None else connection.execute_query_one
    record = row(query_one("SELECT e.*,r.ENDPOINT_URL,r.TRANSPORT_KIND,r.PROTOCOL_VERSION,r.SDK_VERSION,r.ISSUER_URL,r.RESOURCE_URL,r.CONTRACT_DIGEST,r.TIMEOUT_SECONDS,r.MAX_RESPONSE_BYTES FROM CX_PROTOCOL_ENDPOINTS e JOIN CX_PROTOCOL_REVISIONS r ON r.ENDPOINT_ID=e.ENDPOINT_ID AND r.REVISION_NO=e.CURRENT_REVISION WHERE e.ENDPOINT_ID=:endpoint", {"endpoint": endpoint_id}))
    if not record or record["status"] != "ACTIVE" or kind and record["protocol_kind"] != kind:
        raise PermissionError("Registered integration is unavailable")
    if tx is not None:
        work._authorize(tx, actor, record["security_domain_id"], write=False)
    else:
        connection.execute_transaction_callback(lambda current: work._authorize(current, actor, record["security_domain_id"], write=False))
    registered_url(record["endpoint_url"])
    return record


def list_endpoints(actor, domain, kind=""):
    def perform(tx):
        work._authorize(tx, actor, domain, write=False)
        if kind and kind not in TRANSPORTS:
            raise ValueError("Invalid protocol filter")
        return {"items": [row(item) for item in tx.query(
            "SELECT ENDPOINT_ID,ENDPOINT_NAME,PROTOCOL_KIND,CURRENT_REVISION,STATUS,VERSION FROM CX_PROTOCOL_ENDPOINTS WHERE SECURITY_DOMAIN_ID=:domain" +
            (" AND PROTOCOL_KIND=:kind" if kind else "") + " ORDER BY ENDPOINT_NAME" + identity_api._limit_clause("page_limit"),
            {"domain": domain, "page_limit": 100, **({"kind": kind} if kind else {})})]}
    return connection.execute_transaction_callback(perform)


def revoke(actor, endpoint_id, expected_version, reason):
    _human_admin(actor)
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise ValueError("A bounded revocation reason is required")
    def perform(tx):
        _human_admin(actor)
        record = endpoint(actor, endpoint_id, tx=tx)
        work._authorize(tx, actor, record["security_domain_id"], write=True)
        changed = tx.execute("UPDATE CX_PROTOCOL_ENDPOINTS SET STATUS='REVOKED',AUTH_CIPHER=NULL,VERSION=VERSION+1,UPDATED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE ENDPOINT_ID=:endpoint AND VERSION=:version AND STATUS='ACTIVE'",
            {"actor": actor, "reason": str(reason)[:2000], "endpoint": endpoint_id, "version": int(expected_version)})
        if changed != 1:
            raise ValueError("Integration changed concurrently")
        identity_api._audit_tx(tx, actor, "INTEGRATION_REVOKED", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", reason)
        return {"endpoint_id": endpoint_id, "status": "REVOKED"}
    return connection.execute_transaction_callback(perform)


def headers(record):
    result = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    auth = decrypt_section(record["auth_cipher"]) if record.get("auth_cipher") else {}
    if auth.get("bearer_token"):
        result["Authorization"] = "Bearer " + auth["bearer_token"]
    return result


def post(record, payload, extra_headers=None, *, return_status=False):
    bounded_json(payload, maximum=int(record["max_response_bytes"]))
    request = urllib.request.Request(registered_url(record["endpoint_url"]), data=canonical(payload).encode(),
        headers={**headers(record), **(extra_headers or {})}, method="POST")
    with opener().open(request, timeout=int(record["timeout_seconds"])) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        maximum = int(record["max_response_bytes"])
        if response.status == 202:
            result = (None, dict(response.headers))
            return (*result, response.status) if return_status else result
        if content_type == "text/event-stream":
            total, started, data_lines = 0, time.monotonic(), []
            while True:
                if time.monotonic() - started > int(record["timeout_seconds"]):
                    raise TimeoutError("Protocol response deadline")
                line = response.readline(min(65537, maximum + 1))
                total += len(line)
                if total > maximum or len(line) > 65536:
                    raise ValueError("Protocol event exceeds its registered size limit")
                if not line:
                    raise ValueError("Protocol event stream ended without a response")
                if line.startswith(b"data:"):
                    data_lines.append(line[5:].strip())
                if not line.strip() and data_lines:
                    item = json.loads(b"\n".join(data_lines))
                    data_lines = []
                    if item.get("id") == payload.get("id"):
                        result = (bounded_json(item, maximum=maximum), dict(response.headers))
                        return (*result, response.status) if return_status else result
        if content_type not in {"application/json", "application/a2a+json"}:
            raise ValueError("Unexpected registered protocol media type")
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("Protocol response exceeds its registered size limit")
        result = (bounded_json(json.loads(raw), maximum=maximum), dict(response.headers))
        return (*result, response.status) if return_status else result


class MCPSession:
    def __init__(self, record):
        self.record, self.session_id, self.counter = record, "", 0

    def rpc(self, method, params):
        self.counter += 1
        extra = {"MCP-Protocol-Version": self.record["protocol_version"]}
        if self.session_id:
            extra["Mcp-Session-Id"] = self.session_id
        result, response_headers = post(self.record, {"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params}, extra)
        observed = next((value for key, value in response_headers.items() if key.lower() == "mcp-session-id"), "")
        if observed:
            if len(observed) > 256 or any(ord(char) < 32 for char in observed) or self.session_id and observed != self.session_id:
                raise ValueError("Invalid MCP session identity")
            self.session_id = observed
        if not isinstance(result, dict) or result.get("jsonrpc") != "2.0" or result.get("id") != self.counter or "error" in result:
            raise ValueError("MCP request failed its response contract")
        return result.get("result")

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": self.record["protocol_version"], "capabilities": {}, "clientInfo": {"name": "chuanxu", "version": "4.5.2"}})
        if not isinstance(result, dict) or result.get("protocolVersion") != self.record["protocol_version"] or "tools" not in result.get("capabilities", {}):
            raise ValueError("Registered MCP version or tools capability is unavailable")
        extra = {"MCP-Protocol-Version": self.record["protocol_version"], **({"Mcp-Session-Id": self.session_id} if self.session_id else {})}
        post(self.record, {"jsonrpc": "2.0", "method": "notifications/initialized"}, extra)


def tool_contract(tool):
    if not isinstance(tool, dict):
        raise ValueError("MCP Tool must be an object")
    safe_key(tool.get("name"), maximum=256)
    validate_schema(tool.get("inputSchema"), check_value=False)
    if tool.get("outputSchema") is not None:
        validate_schema(tool["outputSchema"], check_value=False)
    return {"name": tool["name"], "title": str(tool.get("title") or tool["name"])[:256],
            "description": str(tool.get("description") or "")[:2000], "inputSchema": tool["inputSchema"],
            "outputSchema": tool.get("outputSchema"), "readOnly": (tool.get("annotations") or {}).get("readOnlyHint") is True}


def remote_contracts(session):
    contracts, cursor, seen = [], None, set()
    for _ in range(8):
        page = session.rpc("tools/list", {"cursor": cursor} if cursor else {})
        if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
            raise ValueError("Invalid MCP discovery response")
        contracts.extend(tool_contract(item) for item in page["tools"])
        if len(contracts) > 200 or len({item["name"] for item in contracts}) != len(contracts):
            raise ValueError("MCP directory exceeds limits or duplicates names")
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or len(cursor) > 1024 or cursor in seen:
            raise ValueError("Invalid or repeated MCP discovery cursor")
        seen.add(cursor)
    else:
        raise ValueError("MCP discovery exceeds its page limit")
    return contracts


def discover(actor, endpoint_id):
    effective_capabilities.require(actor, model="mcp_discovery", action="tools.read")
    record = endpoint(actor, endpoint_id, kind="MCP")
    session = MCPSession(record)
    session.initialize()
    contracts = remote_contracts(session)
    def perform(tx):
        fresh = endpoint(actor, endpoint_id, kind="MCP", tx=tx)
        effective_capabilities.require(actor, model="mcp_discovery", action="tools.read")
        if fresh["version"] != record["version"]:
            raise ValueError("MCP endpoint changed during discovery")
        # Even an identical contract observed again closes execution approval;
        # discovery never preserves authority after a changed remote service.
        tx.execute("UPDATE CX_PROTOCOL_TOOLS SET STATUS='REVOKED',APPROVED_BY=NULL WHERE ENDPOINT_ID=:endpoint AND REVISION_NO=:revision AND STATUS='APPROVED'", {"endpoint": endpoint_id, "revision": int(record["current_revision"])})
        for contract in contracts:
            tool_digest = digest(contract)
            existing = tx.query_one("SELECT TOOL_DIGEST FROM CX_PROTOCOL_TOOLS WHERE ENDPOINT_ID=:endpoint AND REVISION_NO=:revision AND TOOL_NAME=:tool AND TOOL_DIGEST=:digest", {"endpoint": endpoint_id, "revision": int(record["current_revision"]), "tool": contract["name"], "digest": tool_digest})
            if not existing:
                tx.execute("INSERT INTO CX_PROTOCOL_TOOLS(ENDPOINT_ID,REVISION_NO,TOOL_NAME,TOOL_DIGEST,DISPLAY_NAME,DESCRIPTION,INPUT_SCHEMA_JSON,OUTPUT_SCHEMA_JSON,READ_ONLY,STATUS) VALUES(:endpoint,:revision,:tool,:digest,:name,:description,:input_schema,:output_schema,:readonly,'DISCOVERED')",
                    {"endpoint": endpoint_id, "revision": int(record["current_revision"]), "tool": contract["name"], "digest": tool_digest, "name": contract["title"], "description": contract["description"] or None,
                     "input_schema": canonical(contract["inputSchema"]), "output_schema": canonical(contract["outputSchema"]) if contract["outputSchema"] is not None else None, "readonly": int(contract["readOnly"])})
        identity_api._audit_tx(tx, actor, "MCP_SERVICE_DISCOVERED", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", "Scoped version-bound metadata discovery")
        return {"endpoint_id": endpoint_id, "revision_no": int(record["current_revision"]), "items": [{"name": item["name"], "title": item["title"], "description": item["description"], "read_only": item["readOnly"], "tool_digest": digest(item)} for item in contracts]}
    return connection.execute_transaction_callback(perform)


def approve_tool(actor, endpoint_id, tool_name, tool_digest, expected_revision):
    _human_admin(actor)
    def perform(tx):
        _human_admin(actor)
        record = endpoint(actor, endpoint_id, kind="MCP", tx=tx)
        work._authorize(tx, actor, record["security_domain_id"], write=True)
        if int(record["current_revision"]) != int(expected_revision):
            raise ValueError("MCP endpoint revision changed")
        changed = tx.execute("UPDATE CX_PROTOCOL_TOOLS SET STATUS='APPROVED',APPROVED_BY=:actor WHERE ENDPOINT_ID=:endpoint AND REVISION_NO=:revision AND TOOL_NAME=:tool AND TOOL_DIGEST=:digest AND READ_ONLY=1 AND STATUS IN ('DISCOVERED','REVOKED')",
            {"actor": actor, "endpoint": endpoint_id, "revision": int(expected_revision), "tool": tool_name, "digest": tool_digest})
        if changed != 1:
            raise ValueError("An exact discovered read-only tool is required")
        identity_api._audit_tx(tx, actor, "MCP_TOOL_APPROVED", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", "Independent read-only contract approval: " + tool_name[:256])
        return {"tool_name": tool_name, "tool_digest": tool_digest, "status": "APPROVED"}
    return connection.execute_transaction_callback(perform)


def withdraw_tool(actor, endpoint_id, tool_name, tool_digest, expected_revision):
    _human_admin(actor)
    def perform(tx):
        _human_admin(actor)
        record = endpoint(actor, endpoint_id, kind="MCP", tx=tx)
        work._authorize(tx, actor, record["security_domain_id"], write=True)
        if int(record["current_revision"]) != int(expected_revision):
            raise ValueError("MCP endpoint revision changed")
        changed = tx.execute("UPDATE CX_PROTOCOL_TOOLS SET STATUS='REVOKED',APPROVED_BY=NULL WHERE ENDPOINT_ID=:endpoint AND REVISION_NO=:revision AND TOOL_NAME=:tool AND TOOL_DIGEST=:digest AND STATUS='APPROVED'", {"endpoint": endpoint_id, "revision": expected_revision, "tool": tool_name, "digest": tool_digest})
        if changed != 1:
            raise ValueError("An exact approved tool is required")
        identity_api._audit_tx(tx, actor, "MCP_TOOL_WITHDRAWN", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", tool_name)
        return {"tool_name": tool_name, "tool_digest": tool_digest, "status": "REVOKED"}
    return connection.execute_transaction_callback(perform)


def _call_authority(tx, call):
    effective_capabilities.require(call["actor_id"], model="mcp_execution", action="tools.read")
    record = endpoint(call["actor_id"], call["endpoint_id"], kind="MCP", tx=tx)
    principal = row(tx.query_one("SELECT STATUS,PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor", {"actor": call["actor_id"]}))
    if int(principal.get("permission_version") or 0) != int(call["permission_version"]) or principal.get("status") != "ACTIVE" or int(record["version"]) != int(call["endpoint_version"]):
        raise PermissionError("MCP caller or endpoint authority changed")
    credential = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CREDENTIALS WHERE CALL_ID=:call", {"call": call["call_id"]}))
    if not credential:
        raise PermissionError("Original MCP transport credential is required")
    current = agent_gateway_api._authenticate_access_token_digest(credential["token_digest"], call["actor_id"], credential["instance_id"], "tools.read", operation="tools.read", query_one=tx.query_one)
    if not current or int(current["fencing_token"]) != int(credential["fencing_token"]) or current["security_domain_id"] != call["security_domain_id"]:
        raise PermissionError("Original MCP credential was revoked or fenced")
    tool = row(tx.query_one("SELECT * FROM CX_PROTOCOL_TOOLS WHERE ENDPOINT_ID=:endpoint AND REVISION_NO=:revision AND TOOL_NAME=:tool AND TOOL_DIGEST=:digest AND READ_ONLY=1 AND STATUS='APPROVED'", {"endpoint": call["endpoint_id"], "revision": int(call["revision_no"]), "tool": call["tool_name"], "digest": call["tool_digest"]}))
    if not tool:
        raise PermissionError("MCP Tool approval was withdrawn")
    return record, tool


def call_tool(actor, endpoint_id, tool_name, tool_digest, arguments, idempotency_key):
    bounded_json(arguments)
    safe_key(idempotency_key)
    payload_digest = digest({"endpoint": endpoint_id, "tool": tool_name, "contract": tool_digest, "arguments": arguments})
    transport = _transport.get()
    if transport is None:
        raise PermissionError("An authenticated MCP transport credential is required")
    def reserve(tx):
        effective_capabilities.require(actor, model="mcp_execution", action="tools.read")
        record = endpoint(actor, endpoint_id, kind="MCP", tx=tx)
        prior = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE ACTOR_ID=:actor AND IDEMPOTENCY_KEY=:key FOR UPDATE", {"actor": actor, "key": idempotency_key}))
        if prior:
            if prior["payload_digest"] != payload_digest:
                raise ValueError("MCP idempotency key has different content")
            fresh, tool = _call_authority(tx, prior)
            if prior["status"] == "PENDING" and not tx.query_one("SELECT ATTEMPT_ID FROM CX_PROTOCOL_ATTEMPTS WHERE CALL_ID=:call", {"call": prior["call_id"]}):
                validate_schema(json.loads(tool["input_schema_json"]), arguments)
                return prior, fresh, tool
            return prior, None, None
        call = {"call_id": identifier("PC"), "endpoint_id": endpoint_id, "revision_no": int(record["current_revision"]),
                "tool_name": tool_name, "tool_digest": tool_digest, "actor_id": actor, "security_domain_id": record["security_domain_id"],
                "permission_version": int(row(tx.query_one("SELECT PERMISSION_VERSION FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:actor", {"actor": actor}))["permission_version"]),
                "endpoint_version": int(record["version"]), "idempotency_key": idempotency_key, "payload_digest": payload_digest, "status": "PENDING"}
        tx.execute("INSERT INTO CX_PROTOCOL_CALLS(CALL_ID,ENDPOINT_ID,REVISION_NO,TOOL_NAME,TOOL_DIGEST,ACTOR_ID,SECURITY_DOMAIN_ID,PERMISSION_VERSION,ENDPOINT_VERSION,IDEMPOTENCY_KEY,PAYLOAD_DIGEST,STATUS) VALUES(:call_id,:endpoint_id,:revision_no,:tool_name,:tool_digest,:actor_id,:security_domain_id,:permission_version,:endpoint_version,:idempotency_key,:payload_digest,:status)", call)
        if transport:
            tx.execute("INSERT INTO CX_PROTOCOL_CREDENTIALS(CALL_ID,INSTANCE_ID,TOKEN_DIGEST,FENCING_TOKEN) VALUES(:call,:instance,:token,:fence)", {"call": call["call_id"], "instance": transport["instance_id"], "token": transport["token_digest"], "fence": transport["fencing_token"]})
        fresh, tool = _call_authority(tx, call)
        validate_schema(json.loads(tool["input_schema_json"]), arguments)
        identity_api._audit_tx(tx, actor, "MCP_CALL_QUEUED", "PROTOCOL_CALL", call["call_id"], "ALLOW", "Exact approved read-only tool")
        return call, fresh, tool
    call, record, tool = connection.execute_transaction_callback(reserve)
    if record is None:
        return read_call(actor, call["call_id"])
    attempt_id = identifier("PA")
    def claim(tx):
        current = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE CALL_ID=:call FOR UPDATE", {"call": call["call_id"]}))
        fresh, current_tool = _call_authority(tx, current)
        if current["status"] != "PENDING" or current["cancel_requested"]:
            raise PermissionError("MCP Call is no longer dispatchable")
        tx.execute("INSERT INTO CX_PROTOCOL_ATTEMPTS(ATTEMPT_ID,CALL_ID,ATTEMPT_NO,FENCING_TOKEN,STATUS,LEASE_EXPIRES_AT) VALUES(:attempt,:call,1,1,'SENDING',:expires)", {"attempt": attempt_id, "call": call["call_id"], "expires": agent_gateway_api._now() + timedelta(seconds=int(fresh["timeout_seconds"]) * 3 + 10)})
        tx.execute("UPDATE CX_PROTOCOL_CALLS SET STATUS='SENDING' WHERE CALL_ID=:call AND STATUS='PENDING'", {"call": call["call_id"]})
        return fresh, current_tool
    record, tool = connection.execute_transaction_callback(claim)
    status, result, error, sent = "UNOBSERVED", None, None, False
    try:
        session = MCPSession(record)
        session.initialize()
        contracts = remote_contracts(session)
        if not any(item["name"] == tool_name and digest(item) == tool_digest and item["readOnly"] for item in contracts):
            raise PermissionError("Remote MCP tool contract changed; discover and approve it again")
        def last_dispatch_check(tx):
            current = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE CALL_ID=:call FOR UPDATE", {"call": call["call_id"]}))
            if current["status"] != "SENDING" or current["cancel_requested"] or not tx.query_one(
                    "SELECT ATTEMPT_ID FROM CX_PROTOCOL_ATTEMPTS WHERE ATTEMPT_ID=:attempt AND FENCING_TOKEN=1 AND STATUS='SENDING' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP", {"attempt": attempt_id}):
                raise PermissionError("MCP Call was cancelled or its dispatch lease expired")
            return _call_authority(tx, current)
        connection.execute_transaction_callback(last_dispatch_check)
        sent = True
        result = session.rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise ValueError("MCP Tool reported a failed result")
        if tool.get("output_schema_json"):
            validate_schema(json.loads(tool["output_schema_json"]), result.get("structuredContent"))
        status = "SUCCEEDED"
    except urllib.error.HTTPError as exc:
        status, error = ("FAILED" if 400 <= exc.code < 500 else "UNOBSERVED"), "HTTP_" + str(int(exc.code))
    except Exception as exc:
        if not sent:
            status = "FAILED"
        error = "RESULT_CONTRACT_INVALID" if isinstance(exc, ValueError) else "TRANSPORT_UNOBSERVED"
    def complete(tx):
        current = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE CALL_ID=:call FOR UPDATE", {"call": call["call_id"]}))
        attempt = tx.query_one("SELECT ATTEMPT_ID FROM CX_PROTOCOL_ATTEMPTS WHERE ATTEMPT_ID=:attempt AND FENCING_TOKEN=1 AND STATUS='SENDING' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP", {"attempt": attempt_id})
        final = status if attempt and not current["cancel_requested"] else "UNOBSERVED"
        try:
            _call_authority(tx, current)
        except PermissionError:
            final = "UNOBSERVED"
        tx.execute("UPDATE CX_PROTOCOL_CALLS SET STATUS=:state,RESULT_CIPHER=:cipher,RESULT_DIGEST=:digest,COMPLETED_AT=CURRENT_TIMESTAMP WHERE CALL_ID=:call AND STATUS IN ('SENDING','CANCEL_REQUESTED')",
            {"state": final, "cipher": encrypt_section({"result": result}) if final == "SUCCEEDED" else None, "digest": digest(result) if final == "SUCCEEDED" else None, "call": call["call_id"]})
        tx.execute("UPDATE CX_PROTOCOL_ATTEMPTS SET STATUS=:state,ERROR_CODE=:error,COMPLETED_AT=CURRENT_TIMESTAMP WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING'", {"state": final, "error": error, "attempt": attempt_id})
        identity_api._audit_tx(tx, actor, "MCP_CALL_OBSERVED", "PROTOCOL_CALL", call["call_id"], "ALLOW" if final == "SUCCEEDED" else "DENY", final)
        return {"call_id": call["call_id"], "status": final, "result": result if final == "SUCCEEDED" else None, "error_code": error}
    return connection.execute_transaction_callback(complete)


def read_call(actor, call_id):
    def perform(tx):
        call = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE CALL_ID=:call AND ACTOR_ID=:actor", {"call": call_id, "actor": actor}))
        if not call:
            raise PermissionError("MCP Call access denied")
        _call_authority(tx, call)
        result = decrypt_section(call["result_cipher"])["result"] if call.get("result_cipher") else None
        if result is not None and digest(result) != call["result_digest"]:
            raise ValueError("MCP result digest mismatch")
        return {"call_id": call_id, "status": call["status"], "result": result, "cancel_requested": bool(call["cancel_requested"]), "created_at": call["created_at"], "completed_at": call.get("completed_at")}
    return connection.execute_transaction_callback(perform)


def cancel_call(actor, call_id):
    def perform(tx):
        call = row(tx.query_one("SELECT * FROM CX_PROTOCOL_CALLS WHERE CALL_ID=:call AND ACTOR_ID=:actor FOR UPDATE", {"call": call_id, "actor": actor}))
        if not call:
            raise PermissionError("MCP Call access denied")
        _call_authority(tx, call)
        if call["status"] in {"PENDING", "SENDING"}:
            next_state = "CANCELLED" if call["status"] == "PENDING" else "CANCEL_REQUESTED"
            tx.execute("UPDATE CX_PROTOCOL_CALLS SET STATUS=:state,CANCEL_REQUESTED=1 WHERE CALL_ID=:call", {"state": next_state, "call": call_id})
            return {"call_id": call_id, "status": next_state, "remote_cancellation_confirmed": False}
        return {"call_id": call_id, "status": call["status"], "remote_cancellation_confirmed": False}
    return connection.execute_transaction_callback(perform)


def reconcile_calls():
    """Expired sends remain uncertain; never repeat a remote request."""
    def perform(tx):
        calls = tx.query("SELECT c.CALL_ID,a.ATTEMPT_ID FROM CX_PROTOCOL_CALLS c JOIN CX_PROTOCOL_ATTEMPTS a ON a.CALL_ID=c.CALL_ID WHERE c.STATUS IN ('SENDING','CANCEL_REQUESTED') AND a.STATUS='SENDING' AND a.LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP ORDER BY c.CALL_ID" + identity_api._limit_clause("page_limit"), {"page_limit": 100})
        for item in calls:
            item = row(item)
            tx.execute("UPDATE CX_PROTOCOL_CALLS SET STATUS='UNOBSERVED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE CALL_ID=:call AND STATUS IN ('SENDING','CANCEL_REQUESTED')", {"call": item["call_id"]})
            tx.execute("UPDATE CX_PROTOCOL_ATTEMPTS SET STATUS='UNOBSERVED',ERROR_CODE='EXPIRED_SEND',COMPLETED_AT=CURRENT_TIMESTAMP WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING'", {"attempt": item["attempt_id"]})
        return len(calls)
    return connection.execute_transaction_callback(perform)
