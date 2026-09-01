"""FastAPI/Uvicorn entrypoint for the v4.4.11 Chuanxu Web application.

The database-backed services are the authoritative implementation.  This
entrypoint intentionally contains only HTTP concerns and exposes the same
session, CSRF, capability, Channel, Barrier, and Enrollment contracts to
Dashboard and external Skill clients.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import functools
import json
import io
import logging
import os
import queue
import secrets
import socket
import sys
import threading
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    from lib import identity_api, external_identity_api, agent_gateway_api, compliance_api, connection, governed_contracts, security_lifecycle, organization_api, security_domain_api, platform_capabilities, native_agent_api, native_runtime, model_usage_api, model_governance_api, deployment_adapters, runtime_isolation, db4a2a, embedding_governance, admin_management, cursor_pagination, task_plan_api, knowledge_api, memory_lifecycle, skill_api, spec_api, graph_production_profile, platform_agent_pool, host_provisioning, platform_governance_graph as governance_graph_module
except ModuleNotFoundError as exc:
    # Only a missing top-level package means this is the source tree.  Do not
    # hide missing packaged dependencies by incorrectly falling back to shared.
    if exc.name != "lib":
        raise
    from shared.lib import identity_api, external_identity_api, agent_gateway_api, compliance_api, connection, governed_contracts, security_lifecycle, organization_api, security_domain_api, platform_capabilities, native_agent_api, native_runtime, model_usage_api, model_governance_api, deployment_adapters, runtime_isolation, db4a2a, embedding_governance, admin_management, cursor_pagination, task_plan_api, knowledge_api, memory_lifecycle, skill_api, spec_api, graph_production_profile, platform_agent_pool, host_provisioning, platform_governance_graph as governance_graph_module


VERSION = "4.4.11"
logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).resolve().parent / "web"
if not WEB_ROOT.is_dir():
    WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
DIST_ROOT = WEB_ROOT / "dist"
DEFAULT_NODE_ID = agent_gateway_api.local_node_id()
_COMPLIANCE_CONTROLLER_STOP = threading.Event()
_NATIVE_RUNTIME_STOP = threading.Event()
_ENTERPRISE_COMPLIANCE_PATHS = (
    "/api/compliance",
    "/api/agents/{agent_id}/posture",
    "/api/agents/{agent_id}/activate",
    "/api/agents/{agent_id}/compliance-profile",
    "/api/agents/{agent_id}/compliance-control",
    "/api/agents/{agent_id}/compliance-violation",
    "/api/gateway/evidence",
    "/api/gateway/remediations/{case_id}/respond",
)

_VALID_PROFILES = {"production", "graph-preview", "development", "experimental-4.2"}
_PUBLIC_LEGACY_API = {
    "/api/health",
    "/api/login",
    "/portal/api/register",
    "/portal/api/login",
}
_TOKEN_LEGACY_API = {
    "/api/admin/agent/register",
    "/api/admin/agent/recover",
    "/api/agents/register",
    "/api/agents/heartbeat",
}
_MFA_SETUP_ALLOWED_PATHS = {
    "/api/auth/mfa/enroll",
    "/api/auth/mfa/confirm",
    "/api/auth/logout",
    "/portal/api/auth/mfa/enroll",
    "/portal/api/auth/mfa/confirm",
    "/portal/api/auth/logout",
}


def _edition_features():
    try:
        from lib import edition_features
    except ModuleNotFoundError:
        try:
            from shared.lib import edition_features
        except ModuleNotFoundError:
            return None
    return edition_features


def _runtime_profile() -> str:
    """Return a validated, build-aware profile without exposing configuration."""
    features = _edition_features()
    default = str(getattr(features, "PROFILE", "production") or "production")
    requested = str(os.environ.get("CX_RUNTIME_PROFILE", default) or default).strip()
    if requested not in _VALID_PROFILES:
        requested = default if default in _VALID_PROFILES else "production"
    return requested

app = FastAPI(title="Chuanxu AI Agent Management Platform", version=VERSION)


def _correlation_id(request: Request) -> str:
    current = str(getattr(request.state, "correlation_id", "") or "")
    if current:
        return current
    supplied = str(request.headers.get("X-Correlation-ID") or "").strip()
    if 8 <= len(supplied) <= 128 and all(character.isalnum() or character in "-_.:" for character in supplied):
        current = supplied
    else:
        current = "cx_" + secrets.token_hex(16)
    request.state.correlation_id = current
    return current


def _error_response(request: Request, status: int, code: str, message: str, retryable: Optional[bool] = None) -> JSONResponse:
    correlation = _correlation_id(request)
    safe_message = str(message or "Request failed")[:500]
    body = {
        "code": str(code or "REQUEST_FAILED")[:96],
        "message": safe_message,
        "correlation_id": correlation,
        "retryable": status in {408, 429, 502, 503, 504} if retryable is None else bool(retryable),
        "detail": safe_message,
    }
    return JSONResponse(body, status_code=status, headers={"X-Correlation-ID": correlation})


@app.exception_handler(StarletteHTTPException)
async def governed_http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    code = "HTTP_" + str(exc.status_code)
    message = "Request failed"
    retryable = None
    if isinstance(detail, dict):
        code = str(detail.get("code") or code)
        message = str(detail.get("message") or detail.get("detail") or message)
        retryable = detail.get("retryable")
    else:
        message = str(detail or message)
    return _error_response(request, int(exc.status_code), code, message, retryable)


@app.exception_handler(RequestValidationError)
async def governed_validation_error(request: Request, _exc: RequestValidationError):
    return _error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", False)


@app.exception_handler(Exception)
async def governed_unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled request failure correlation_id=%s", _correlation_id(request), exc_info=exc)
    return _error_response(request, 500, "INTERNAL_ERROR", "Internal request failed", False)


def _path_capability(path: str) -> Optional[str]:
    """Map every product entry point to one installation capability."""
    normalized = "/" + str(path or "").lstrip("/")
    if normalized.startswith("/portal"):
        return "portal"
    if normalized.startswith("/app/"):
        page = normalized.split("/", 3)[2]
        return {
            "monitor": "monitor", "agents": "agents", "tasks": "tasks",
            "workspaces": "workspaces", "knowledge": "knowledge", "memory": "memory",
            "skills": "skills", "specs": "specs", "branches": "branches",
            "collab": "collaboration", "loops": "loops", "graph": "graph",
            "channels": "channels", "barriers": "barriers", "approvals": "approvals",
            "compliance": "compliance", "audit": "audit_view", "users": "users",
            "organization": "organization", "security-domains": "security_domains", "platform": "platform_config",
            "native-agents": "agent_provisioning", "deployment": "deployment_governance",
            "wallboard": "wallboard",
        }.get(page)
    if normalized.startswith("/api/agents/") and any(part in normalized for part in ("/posture", "/activate", "/compliance-")):
        return "compliance"
    rules = (
        (("/api/platform", "/api/model-gateway"), "platform_config"),
        (("/api/monitor",), "monitor"),
        (("/api/wallboard", "/api/model-usage"), "wallboard"),
        (("/api/model-finance",), "model_finance"),
        (("/api/model-evidence",), "external_model_evidence"),
        (("/api/agents/",), "agents"),
        (("/api/tasks", "/api/execution", "/ap/v1/agent/tasks"), "tasks"),
        (("/api/workspaces",), "workspaces"),
        (("/api/knowledge",), "knowledge"),
        (("/api/memory",), "memory"),
        (("/api/skills", "/api/skill", "/api/agent/skills"), "skills"),
        (("/api/specs",), "specs"),
        (("/api/branches", "/api/branch"), "branches"),
        (("/api/collab",), "collaboration"),
        (("/api/loops",), "loops"),
        (("/api/graphs", "/api/graph-", "/api/graph/"), "graph"),
        (("/api/channels", "/api/gateway/channels", "/api/agent-gateway/channels", "/api/gateway/events"), "channels"),
        (("/api/barriers", "/api/gateway/barriers", "/api/agent-gateway/barriers"), "barriers"),
        (("/api/approvals",), "approvals"),
        (("/api/compliance", "/api/gateway/evidence", "/api/gateway/remediations"), "compliance"),
        (("/api/audit", "/api/traces", "/api/evidence", "/api/legal-holds"), "audit_view"),
        (("/api/users", "/api/registration"), "users"),
        (("/api/organization",), "organization"),
        (("/api/security-domains",), "security_domains"),
        (("/api/embedding",), "embedding_governance"),
        (("/api/deployment-runs",), "deployment_governance"),
    )
    for prefixes, capability in rules:
        if any(
            normalized == prefix.rstrip("/")
            or normalized.startswith(prefix.rstrip("/") + "/")
            for prefix in prefixes
        ):
            return capability
    return None


def _graph_operation_capability(path: str) -> Optional[str]:
    """Map Graph protocol operations to the database-authoritative matrix."""
    normalized = "/" + str(path or "").lstrip("/")
    if normalized.startswith("/api/a2a"):
        return "a2a_gateway"
    if normalized.startswith("/api/telemetry"):
        return "otel_export"
    if normalized.startswith("/api/graph-dynamic") or normalized.endswith("/migrate"):
        return "graph_dynamic_migration"
    if normalized.startswith(("/api/graph/", "/api/graphs/", "/api/graph-")) and normalized.endswith("/replay"):
        return "graph_replay"
    if normalized.startswith(("/api/graph/", "/api/graphs/", "/api/graph-")) and normalized.endswith("/fork"):
        return "graph_checkpoint_fork"
    if normalized.startswith("/api/graph-assurance"):
        return "graph_slo_readonly"
    if (normalized.startswith("/api/graph-manifest") or normalized.startswith("/api/graph-compat")
            or normalized.startswith("/api/graphs/") and normalized.endswith("/import")):
        return "graph_manifest_draft_import"
    if normalized.startswith(("/api/graphs", "/api/graph-", "/api/graph/")):
        return "graph_runtime_core"
    return None


@app.middleware("http")
async def enforce_platform_capability(request: Request, call_next):
    capability = _path_capability(request.url.path)
    if capability:
        try:
            enabled = platform_capabilities.is_enabled(capability)
        except (platform_capabilities.CapabilityServiceUnavailable, platform_capabilities.CapabilityError):
            return JSONResponse(
                {"detail": {"code": "CAPABILITY_SERVICE_UNAVAILABLE", "capability": capability}},
                status_code=503,
            )
        if not enabled:
            return JSONResponse(
                {"detail": {"code": "CAPABILITY_DISABLED", "capability": capability}},
                status_code=409,
            )
    graph_capability = _graph_operation_capability(request.url.path)
    if graph_capability:
        try:
            graph_state = graph_production_profile.state(graph_capability)
            controlled = False
            if graph_state == "CONTROLLED":
                session = _session_from_request(request)
                if not session:
                    return JSONResponse({"detail": {"code": "GRAPH_CAPABILITY_CONTROLLED", "capability": graph_capability}}, status_code=403)
                access = identity_api.effective_access(str(session["principal_id"]), "platform.manage")
                controlled = access.get("decision") == "ALLOW"
            graph_production_profile.require(graph_capability, controlled=controlled)
        except graph_production_profile.ProfileConflict as exc:
            return JSONResponse({"detail": {"code": "GRAPH_CAPABILITY_BLOCKED", "message": str(exc)}}, status_code=409)
        except graph_production_profile.ProfileUnavailable:
            return JSONResponse({"detail": {"code": "GRAPH_CAPABILITY_UNAVAILABLE", "capability": graph_capability}}, status_code=503)
    return await call_next(request)


@app.middleware("http")
async def enforce_database_read_only_session(request: Request, call_next):
    """Fence every authenticated browser mutation for a DB-marked identity."""
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in {
        "/api/auth/logout", "/portal/api/auth/logout",
    }:
        scope = "PORTAL" if request.url.path.startswith("/portal/") else "DASHBOARD"
        session = _session_from_request(request, scope)
        if session:
            try:
                with _schema_owner_context():
                    read_only = identity_api.is_global_read_only_principal(str(session["principal_id"]))
            except Exception:
                return JSONResponse({"detail": "Authorization service unavailable"}, status_code=503)
            if read_only:
                return JSONResponse({"detail": "This session is read-only"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def clear_agent_database_context(request: Request, call_next):
    """Clear DB identity and renew authenticated inactivity Sessions."""
    try:
        response = await call_next(request)
        session = getattr(request.state, "cx_session", None)
        raw_session_id = getattr(request.state, "cx_session_id", "")
        session_scope = getattr(request.state, "cx_session_scope", "DASHBOARD")
        session_exit_paths = {
            "/api/auth/logout",
            "/portal/api/auth/logout",
            "/portal/api/agent/release",
        }
        if session and raw_session_id and request.url.path not in session_exit_paths and response.status_code < 400:
            _set_session_cookie(response, {"session_id": raw_session_id}, session_scope, request.url.port)
            expires_at = _browser_session_expiry(session.get("expires_at"))
            if expires_at:
                response.headers["X-Session-Expires-At"] = expires_at
        return response
    finally:
        clear_context = getattr(connection, "set_agent_context", None)
        if callable(clear_context):
            clear_context(None)


@app.middleware("http")
async def attach_correlation_id(request: Request, call_next):
    correlation = _correlation_id(request)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation
    return response


def _local_node_id() -> str:
    return agent_gateway_api.local_node_id()


@contextmanager
def _schema_owner_context():
    """Run human identity checks outside any Business Agent context."""
    previous = connection.get_current_agent_id()
    if previous:
        connection.set_agent_context(None)
    try:
        yield
    finally:
        connection.set_agent_context(previous)


def _gateway_request_context(func):
    """Fence one synchronous Gateway call to its worker-thread invocation."""
    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any):
        clear_context = getattr(connection, "set_agent_context", None)
        if callable(clear_context):
            clear_context(None)
        try:
            return func(*args, **kwargs)
        finally:
            if callable(clear_context):
                clear_context(None)
    return wrapped


def _reclaim_local_agents() -> int:
    """Reclaim only Portal and Gateway leases owned by this process node."""
    reclaimed = 0
    try:
        try:
            from lib import agent_api
        except ModuleNotFoundError:
            from shared.lib import agent_api
        reclaimed += int(agent_api.reclaim_portal_agents(_local_node_id()) or 0)
    except Exception:
        pass
    try:
        reclaimed += int(agent_gateway_api.reclaim_local_instances(_local_node_id()) or 0)
    except Exception:
        pass
    return reclaimed


def _start_compliance_controller() -> None:
    """Run only the deterministic Controller; leases make multi-node safe."""
    features = _edition_features()
    if features is not None and not features.has_feature("compliance"):
        return
    def worker() -> None:
        try:
            from lib import compliance_controller
        except ModuleNotFoundError:
            from shared.lib import compliance_controller
        while not _COMPLIANCE_CONTROLLER_STOP.is_set():
            try:
                if platform_capabilities.is_enabled("compliance"):
                    compliance_controller.run_once(_local_node_id(), limit=50)
            except Exception:
                logger.debug("Compliance Controller cycle failed", exc_info=True)
            _COMPLIANCE_CONTROLLER_STOP.wait(30)
    threading.Thread(target=worker, name="cx-compliance-controller", daemon=True).start()


def _start_native_runtime() -> None:
    """Run the reference local Worker; database leases coordinate nodes."""
    def worker() -> None:
        while not _NATIVE_RUNTIME_STOP.is_set():
            try:
                native_runtime.execute_one(node_id=_local_node_id())
            except Exception:
                logger.debug("Native Runtime cycle failed", exc_info=True)
            _NATIVE_RUNTIME_STOP.wait(2)
    threading.Thread(target=worker, name="cx-native-runtime", daemon=True).start()


def _bootstrap_native_agents() -> None:
    """Initialize platform-owned Agent identities after database migration.

    A v4.3.5 database does not have the additive v4.3.6 tables yet.  Startup
    remains compatible in that state; the migration runner is authoritative
    and the next restart will complete bootstrap.
    """
    try:
        native_agent_api.bootstrap_native_agents()
    except Exception:
        logger.info("Native Agent bootstrap is pending migration", exc_info=True)


def _bootstrap_admin_management() -> None:
    """Initialize v4.4.1 management objects after their additive migration."""
    try:
        admin_management.initialize()
    except Exception:
        logger.info("Platform Administration bootstrap is pending migration", exc_info=True)


def _bootstrap_managed_node() -> None:
    """Record this platform runtime as an Admin Agent node automatically."""
    try:
        host = os.environ.get("CX_NODE_HOST", "").strip() or agent_gateway_api.local_node_id().split(":", 1)[0]
        module_dir = Path(__file__).resolve().parent
        deployment_dir = module_dir.parent if module_dir.name == "scripts" else module_dir
        platform_agent_pool.ensure_managed_node(
            node_key=DEFAULT_NODE_ID, host_reference=host, roles=["ADMIN_AGENT"],
            actor="SYSTEM_BOOTSTRAP", agent_info_path=str(deployment_dir),
            reason="Platform startup collected the local runtime node metadata",
        )
    except Exception:
        logger.info("Managed node discovery is pending migration", exc_info=True)


def _remove_enterprise_compliance_routes() -> None:
    """Keep Enterprise compliance HTTP surfaces out of Community runtimes."""
    features = _edition_features()
    if features is None or features.has_feature("compliance"):
        return
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in _ENTERPRISE_COMPLIANCE_PATHS
    ]


@app.on_event("startup")
def on_startup() -> None:
    # Recovery is deliberately node-scoped; another collaborating Dashboard
    # node keeps its leases and active Agent assignment.
    _remove_enterprise_compliance_routes()
    _reclaim_local_agents()
    _COMPLIANCE_CONTROLLER_STOP.clear()
    _NATIVE_RUNTIME_STOP.clear()
    _bootstrap_native_agents()
    _bootstrap_admin_management()
    _bootstrap_managed_node()
    _start_compliance_controller()
    _start_native_runtime()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _COMPLIANCE_CONTROLLER_STOP.set()
    _NATIVE_RUNTIME_STOP.set()
    _reclaim_local_agents()
    try:
        identity_api.connection.close_pool()
    except Exception:
        pass


def _legacy_module():
    """Load the established page/API implementation only for compatibility routes."""
    try:
        from visualization import server as legacy
    except ModuleNotFoundError:
        from shared.visualization import server as legacy
    return legacy


def _build_legacy_handler(method: str, path: str, query: str, headers: Dict[str, str], body: bytes, wfile: Any):
    """Build an in-process legacy handler backed by the supplied writer."""
    legacy = _legacy_module()
    raw_headers = "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n"
    handler = legacy.VisHandler.__new__(legacy.VisHandler)
    handler.rfile = io.BytesIO(body or b"")
    handler.wfile = wfile
    handler.headers = BytesParser(policy=HTTP).parsebytes(raw_headers.encode("latin-1"))
    handler.request_version = "HTTP/1.1"
    handler.command = method
    handler.path = path + (("?" + query) if query else "")
    handler.requestline = f"{method} {handler.path} HTTP/1.1"
    handler.client_address = (headers.get("x-forwarded-for", "127.0.0.1"), 0)
    handler.server = type("CompatServer", (), {
        "server_name": "chuanxu",
        "server_port": int(os.environ.get("MEMORY_SERVER_PORT", "8000")),
    })()
    handler.close_connection = True
    return handler


def _run_legacy_handler(handler: Any, method: str) -> None:
    if method == "GET":
        handler.do_GET()
    elif method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()


def _parse_legacy_response_head(head: bytes) -> tuple[int, Dict[str, str]]:
    lines = head.split(b"\r\n")
    try:
        status_code = int(lines[0].split(None, 2)[1])
    except (IndexError, ValueError):
        status_code = 502
    response_headers: Dict[str, str] = {}
    for line in lines[1:]:
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        name = key.decode("latin-1")
        if name.lower() in {"content-length", "transfer-encoding", "connection"}:
            continue
        response_headers[name] = value.lstrip().decode("latin-1")
    return status_code, response_headers


class _LegacyStreamWriter:
    """Expose BaseHTTPRequestHandler output as incrementally consumable chunks."""

    _END = object()

    def __init__(self) -> None:
        self._head_buffer = bytearray()
        self._chunks: queue.Queue[Any] = queue.Queue(maxsize=64)
        self.headers_ready = threading.Event()
        self.closed = threading.Event()
        self.status_code = 502
        self.response_headers: Dict[str, str] = {}
        self.error: Optional[BaseException] = None

    def write(self, data: bytes) -> int:
        if self.closed.is_set():
            raise BrokenPipeError("stream client disconnected")
        payload = bytes(data)
        if not self.headers_ready.is_set():
            self._head_buffer.extend(payload)
            marker = self._head_buffer.find(b"\r\n\r\n")
            if marker < 0:
                return len(data)
            head = bytes(self._head_buffer[:marker])
            payload = bytes(self._head_buffer[marker + 4:])
            self._head_buffer.clear()
            self.status_code, self.response_headers = _parse_legacy_response_head(head)
            self.headers_ready.set()
        if payload:
            self._put(payload)
        return len(data)

    def flush(self) -> None:
        return None

    def _put(self, item: Any) -> None:
        while not self.closed.is_set():
            try:
                self._chunks.put(item, timeout=0.2)
                return
            except queue.Full:
                continue
        raise BrokenPipeError("stream client disconnected")

    def finish(self, error: Optional[BaseException] = None) -> None:
        self.error = error
        if not self.headers_ready.is_set():
            self.headers_ready.set()
        try:
            self._put(self._END)
        except BrokenPipeError:
            pass

    def iter_chunks(self) -> Iterator[bytes]:
        try:
            while True:
                chunk = self._chunks.get()
                if chunk is self._END:
                    if self.error:
                        logger.error("Legacy streaming handler failed: %s", self.error)
                    return
                yield chunk
        finally:
            self.closed.set()


def _clear_legacy_thread_context() -> None:
    clear_context = getattr(connection, "set_agent_context", None)
    if callable(clear_context):
        clear_context(None)


def _legacy_stream_worker(handler: Any, method: str, writer: _LegacyStreamWriter) -> None:
    error: Optional[BaseException] = None
    try:
        _run_legacy_handler(handler, method)
    except (BrokenPipeError, ConnectionResetError):
        pass
    except BaseException as exc:
        error = exc
    finally:
        _clear_legacy_thread_context()
        writer.finish(error)


async def _legacy_stream_dispatch(
    method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
) -> Response:
    writer = _LegacyStreamWriter()
    handler = _build_legacy_handler(method, path, query, headers, body, writer)
    worker = threading.Thread(
        target=_legacy_stream_worker,
        args=(handler, method, writer),
        name="portal-stream",
        daemon=True,
    )
    worker.start()
    await asyncio.to_thread(writer.headers_ready.wait)
    if writer.error and not writer.response_headers:
        return JSONResponse({"error": str(writer.error)}, status_code=500)
    return StreamingResponse(
        writer.iter_chunks(),
        status_code=writer.status_code,
        headers=writer.response_headers,
        media_type=None,
    )


def _legacy_dispatch(method: str, path: str, query: str, headers: Dict[str, str], body: bytes) -> Response:
    """Run a non-streaming legacy handler without starting a second listener.

    The compatibility bridge is deliberately request-local: it does not own a
    socket, thread, session store, scheduler, or database connection.  FastAPI
    remains the only network entrypoint while v4.1 pages and clients keep their
    existing contracts during the React migration.
    """
    handler = _build_legacy_handler(method, path, query, headers, body, io.BytesIO())
    try:
        _run_legacy_handler(handler, method)
    except Exception as exc:  # the legacy handler normally serializes errors itself
        payload = json.dumps({"error": str(exc)}).encode("utf-8")
        return Response(payload, status_code=500, media_type="application/json")
    finally:
        # The legacy handler may set a Business Agent identity for Portal
        # operations.  FastAPI reuses this event-loop thread between requests,
        # so never carry that identity into the next human authorization check.
        clear_context = getattr(connection, "set_agent_context", None)
        if callable(clear_context):
            clear_context(None)

    raw = handler.wfile.getvalue()
    marker = raw.find(b"\r\n\r\n")
    if marker < 0:
        return Response(raw, status_code=502, media_type="text/plain")
    head, payload = raw[:marker], raw[marker + 4:]
    status_code, response_headers = _parse_legacy_response_head(head)
    return Response(payload, status_code=status_code, headers=response_headers)


def _legacy_required_action(path: str, method: str) -> Optional[str]:
    """Map compatibility APIs to the same coarse permission boundary as React."""
    rules = (
        ("/api/monitor", "agents.read"),
        ("/api/agents", "agents.read"),
        ("/api/tasks", "tasks.read"),
        ("/api/workspaces", "workspaces.read"),
        ("/api/knowledge", "knowledge.read"),
        ("/api/memory", "memory.read"),
        ("/api/skills", "skills.read"),
        ("/api/skill", "skills.read"),
        ("/api/agent/skills", "skills.read"),
        ("/api/specs", "specs.read"),
        ("/api/branches", "branches.read"),
        ("/api/branch", "branches.read"),
        ("/api/collab", "collab.read"),
        ("/api/loops", "loops.read"),
        ("/api/graphs", "graphs.read"),
        ("/api/graph-", "graphs.read"),
        ("/api/graph/", "graphs.read"),
        ("/api/approvals", "approvals.read"),
        ("/api/audit", "audit.read"),
        ("/api/traces", "audit.read"),
        ("/api/tools", "tools.read"),
        ("/api/events", "notifications.read"),
        ("/api/users", "users.read"),
        ("/api/registration", "users.read"),
        ("/api/governance", "security.read"),
        ("/api/execution", "tasks.read"),
        ("/ap/v1/agent/tasks", "tasks.read"),
    )
    for prefix, action in rules:
        if path == prefix or path.startswith(prefix + "/"):
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                return {
                    "agents.read": "agents.operate",
                    "tasks.read": "tasks.write",
                    "workspaces.read": "workspaces.write",
                    "knowledge.read": "knowledge.write",
                    "memory.read": "memory.write",
                    "skills.read": "skills.write",
                    "specs.read": "specs.write",
                    "branches.read": "branches.write",
                    "collab.read": "collab.write",
                    "loops.read": "loops.write",
                    "graphs.read": "graphs.write",
                    "approvals.read": "approvals.decide",
                    "audit.read": "audit.export",
                    "tools.read": "tools.write",
                    "notifications.read": "notifications.write",
                }.get(action, action)
            return action
    return None


def _legacy_gate(request: Request, path: str) -> Optional[Response]:
    """Apply session, Agent-token, CSRF and coarse permission checks to legacy APIs."""
    if not path.startswith(("/api/", "/portal/api/", "/ap/")):
        return None
    if path in _TOKEN_LEGACY_API and path not in {"/api/agents/heartbeat"}:
        try:
            native_agent_api.enforce_external_registration_allowed()
        except PermissionError as exc:
            return JSONResponse({"error": "External Agent registration is disabled"}, status_code=409)
        except Exception:
            return JSONResponse({"error": "External Agent registration policy unavailable"}, status_code=503)
        return None
    if path in _PUBLIC_LEGACY_API or path in _TOKEN_LEGACY_API:
        return None

    agent_id = request.headers.get("X-Agent-Id", "").strip()
    agent_token = request.headers.get("X-Agent-Token", "").strip()
    if agent_id or agent_token:
        try:
            try:
                from lib import agent_registration
            except ModuleNotFoundError:
                from shared.lib import agent_registration
            valid = bool(agent_id and agent_token and agent_registration.authenticate_agent(agent_id, agent_token))
        except Exception:
            valid = False
        if not valid:
            return JSONResponse({"error": "Registered Agent authentication required"}, status_code=401)
        # Agent requests carry their own admission proof and must not be
        # forced to manufacture a human CSRF token.
        return None

    entry = "PORTAL" if path.startswith("/portal/api/") else "APP"
    session = _session_from_request(
        request, "PORTAL" if entry == "PORTAL" else "DASHBOARD"
    )
    if not session:
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    try:
        with _schema_owner_context():
            allowed = identity_api.entry_allowed(str(session["principal_id"]), entry)
        if not allowed:
            return JSONResponse({"error": f"{entry.title()} access is disabled"}, status_code=403)
    except Exception:
        return JSONResponse({"error": "Entry-access policy is unavailable"}, status_code=503)
    if str(session.get("mfa_level") or "NONE").upper() == "SETUP":
        return JSONResponse({"error": "MFA setup required"}, status_code=403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not identity_api.verify_csrf(session, request.headers.get("X-CSRF-Token", "")):
            return JSONResponse({"error": "CSRF validation failed"}, status_code=403)
    action = _legacy_required_action(path, request.method)
    if action:
        try:
            with _schema_owner_context():
                access = identity_api.effective_access(str(session["principal_id"]), action)
        except Exception:
            return JSONResponse({"error": "Authorization service unavailable"}, status_code=503)
        if access.get("decision") != "ALLOW":
            return JSONResponse({"error": "permission denied", "access": access}, status_code=403)
    return None


@app.get("/static/{file_path:path}")
def static_file(file_path: str) -> Response:
    candidates = [
        DIST_ROOT / file_path,
        Path(__file__).resolve().parent / "visualization" / "static" / file_path,
        Path(__file__).resolve().parent / "visualization" / "static" / "brand" / file_path,
        Path(__file__).resolve().parent / "scripts" / "visualization" / "static" / file_path,
        Path(__file__).resolve().parent.parent / "scripts" / "visualization" / "static" / "brand" / file_path,
        Path(__file__).resolve().parent.parent / "business_plan" / "brand" / "visual_system" / "assets" / Path(file_path).name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            # The control-plane UI is security-sensitive. Do not let a browser
            # reuse an older bundle after a session-boundary or UI correction.
            return FileResponse(candidate, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=404, detail="Static asset not found")


class RegistrationBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=1024)
    email: str = Field(default="", max_length=320)
    mobile: str = Field(default="", max_length=64)
    invite_code: str = Field(default="", max_length=512)
    registration_token: str = Field(default="", max_length=512)


class HumanRegistrationTokenBody(BaseModel):
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)
    reason: str = Field(min_length=1, max_length=2000)


class RegistrationFieldPolicyBody(BaseModel):
    field_state: str = Field(min_length=1, max_length=16)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class RegistrationTokenPolicyBody(BaseModel):
    required: bool
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class PortalConnectionPolicyBody(BaseModel):
    max_connections: int = Field(ge=1, le=32)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class ExternalProviderBody(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128)
    adapter_type: str = Field(min_length=1, max_length=128)
    protocol_type: str = Field(min_length=1, max_length=64)
    issuer: str = Field(default="", max_length=512)
    tenant_reference: str = Field(default="", max_length=256)
    endpoints: Dict[str, Any] = Field(default_factory=dict)
    redirect_allowlist: list[str] = Field(default_factory=list, max_length=20)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    credential_reference: str = Field(default="", max_length=256)
    attribute_mapping: Dict[str, Any] = Field(default_factory=dict)
    registration_policy: str = Field(default="APPROVAL", max_length=32)
    status: str = Field(default="DISABLED", max_length=24)
    expected_version: int = Field(default=0, ge=0)
    reason: str = Field(min_length=1, max_length=2000)


class ExternalLoginStartBody(BaseModel):
    provider_id: str = Field(min_length=1, max_length=128)
    entry: str = Field(default="PORTAL", max_length=16)
    redirect_uri: str = Field(default="", max_length=2048)


class ExternalLoginCallbackBody(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=512)
    nonce: str = Field(min_length=1, max_length=512)
    callback_digest: str = Field(min_length=1, max_length=512)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    mfa_code: str = Field(default="", max_length=32)


class PasswordResetRequestBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)


class PasswordResetConsumeBody(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=12, max_length=1024)
    reason: str = Field(default="password reset", max_length=2000)


class IdentityLinkBody(BaseModel):
    target_principal_id: str = Field(min_length=1, max_length=128)
    identity_type: str = Field(min_length=1, max_length=16)
    provider: str = Field(min_length=1, max_length=256)
    subject_key: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=1, max_length=2000)


class MfaPolicyBody(BaseModel):
    required: bool
    reason: str = Field(min_length=1, max_length=2000)


class MfaEnrollBody(BaseModel):
    target_principal_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class MfaConfirmBody(BaseModel):
    factor_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class OrganizationChangeBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    operations: list[Dict[str, Any]] = Field(default_factory=list, max_length=1000)
    idempotency_key: str = Field(default="", max_length=256)


class OrganizationOperationBody(BaseModel):
    operation: Dict[str, Any]
    reason: str = Field(default="MFA enrollment confirmation", max_length=2000)


class OrganizationWorkflowBody(BaseModel):
    reason: str = Field(default="", max_length=2000)


class RecoveryCodesBody(BaseModel):
    target_principal_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=8, ge=4, le=12)


class SessionRevokeBody(BaseModel):
    target_principal_id: str = Field(min_length=1, max_length=128)
    session_digest: str = Field(min_length=32, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class DelegationBody(BaseModel):
    grantee_principal_id: str = Field(min_length=1, max_length=128)
    permissions: list[str] = Field(min_length=1, max_length=100)
    data_scope: str = Field(default="ASSIGNED", max_length=32)
    valid_until: Optional[str] = Field(default=None, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class DelegationRevokeBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AgentRelationshipBody(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    relationship_role: str = Field(default="OPERATOR", max_length=32)
    responsible_group_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class LegacyClaimBody(BaseModel):
    review_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class InstanceQuarantineBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class ComplianceActivationBody(BaseModel):
    profile_version_id: str = Field(default="", max_length=128)
    evidence_strength: str = Field(default="BOUNDARY_ONLY", max_length=32)
    baseline: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)


class ComplianceProfileBody(BaseModel):
    profile_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    content: Dict[str, Any] = Field(default_factory=dict)
    parent_version_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class ComplianceAssignmentBody(BaseModel):
    profile_version_id: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="production", min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class ComplianceControlBody(BaseModel):
    control_state: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: Optional[int] = Field(default=None, ge=1)


class ComplianceViolationBody(BaseModel):
    rule_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_id: str = Field(default="", max_length=128)
    automatic: bool = False


class ModelForwardBody(BaseModel):
    provider_profile_id: str = Field(min_length=1, max_length=128)
    messages: List[Dict[str, Any]] = Field(min_length=1, max_length=100)
    agent_id: str = Field(default="", max_length=128)
    stream: bool = False
    idempotency_key: str = Field(default="", max_length=160)


class EmbeddingGatewayBody(BaseModel):
    model: str = Field(default="", max_length=256)
    input: Any


class EmbeddingAccessGrantBody(BaseModel):
    subject_type: str = Field(min_length=1, max_length=32)
    subject_id: str = Field(min_length=1, max_length=128)
    effect: str = Field(default="ALLOW", max_length=16)
    allowed_profile_id: str = Field(default="", max_length=128)
    max_batch_size: int = Field(default=1, ge=1, le=16)
    max_input_chars: int = Field(default=16000, ge=1, le=64000)
    valid_from: str = Field(default="", max_length=64)
    valid_until: str = Field(default="", max_length=64)
    reason: str = Field(min_length=3, max_length=2000)


class GatewayCredentialBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    scopes: List[str] = Field(default_factory=list, max_length=50)
    expires_at: str = Field(default="", max_length=64)


class GatewayRevokeBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ModelRoutingPolicyBody(BaseModel):
    agent_id: str = Field(default="", max_length=128)
    profile_id: str = Field(default="", max_length=128)
    gateway_enabled: bool = False
    direct_allowed: bool = True
    reason: str = Field(min_length=1, max_length=500)


class ModelQuotaPolicyBody(BaseModel):
    policy_key: str = Field(min_length=1, max_length=128)
    scope_type: str = Field(default="GLOBAL", max_length=32)
    scope_id: str = Field(default="", max_length=128)
    metric: str = Field(default="TOKEN", max_length=16)
    limit_value: str = Field(min_length=1, max_length=64)
    currency: str = Field(default="", max_length=12)
    enforcement: str = Field(default="HARD", max_length=16)
    window_type: str = Field(default="MONTHLY", max_length=16)
    reservation_value: str = Field(default="0", max_length=64)
    incomplete_policy: str = Field(default="CHARGE_RESERVED", max_length=24)
    effective_from: str = Field(default="", max_length=64)
    effective_to: str = Field(default="", max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class ProviderInvoiceBody(BaseModel):
    provider_key: str = Field(min_length=1, max_length=128)
    external_invoice_id: str = Field(min_length=1, max_length=160)
    currency: str = Field(min_length=1, max_length=12)
    period_start: str = Field(min_length=1, max_length=64)
    period_end: str = Field(min_length=1, max_length=64)
    total_amount: str = Field(min_length=1, max_length=64)
    lines: List[Dict[str, Any]] = Field(default_factory=list, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)


class ReconciliationBody(BaseModel):
    usage_id: str = Field(default="", max_length=128)
    rule_version: str = Field(min_length=1, max_length=64)
    confidence: str = Field(default="1", max_length=32)
    reason: str = Field(min_length=1, max_length=500)


class InvoiceCorrectionBody(BaseModel):
    amount_delta: str = Field(min_length=1, max_length=32)
    prior_correction_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class AllocationRuleBody(BaseModel):
    rule_key: str = Field(min_length=1, max_length=128)
    target_type: str = Field(default="", max_length=32)
    target_id: str = Field(default="", max_length=128)
    percentage: str = Field(default="", max_length=32)
    targets: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)
    currency: str = Field(default="", max_length=12)
    effective_from: str = Field(default="", max_length=64)
    effective_to: str = Field(default="", max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class AllocationRequestBody(BaseModel):
    rule_key: str = Field(min_length=1, max_length=128)


class EvidenceAdapterBody(BaseModel):
    adapter_id: str = Field(default="", max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    verification_key: str = Field(min_length=1, max_length=512)
    scopes: List[str] = Field(default_factory=list, max_length=100)


class ExternalEvidenceBody(BaseModel):
    adapter_id: str = Field(min_length=1, max_length=128)
    key_version: int = Field(ge=1)
    sequence_no: int = Field(ge=0)
    nonce: str = Field(min_length=8, max_length=128)
    observed_from: str = Field(min_length=1, max_length=64)
    observed_to: str = Field(min_length=1, max_length=64)
    facts: Dict[str, Any] = Field(default_factory=dict)
    signature: str = Field(min_length=1, max_length=512)


class WallboardDefinitionBody(BaseModel):
    definition_id: str = Field(default="", max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    config: Dict[str, Any] = Field(default_factory=dict)
    scope: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class GovernedReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ComplianceRemediationBody(BaseModel):
    required_action: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    deadline_at: str = Field(default="", max_length=64)


class ComplianceExceptionBody(BaseModel):
    policy_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    agent_id: str = Field(default="", max_length=128)
    profile_version_id: str = Field(default="", max_length=128)
    environment: str = Field(default="", max_length=64)
    expires_at: str = Field(min_length=1, max_length=64)
    compensating_controls: Dict[str, Any] = Field(default_factory=dict)


class DerivedObjectBody(BaseModel):
    object_type: str = Field(min_length=1, max_length=64)
    object_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class MemoryPromoteBody(BaseModel):
    destination_scope: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class ConnectorBody(BaseModel):
    bridge_id: str = Field(min_length=1, max_length=128)
    mode: str = Field(min_length=1, max_length=32)
    endpoint_ref: str = Field(min_length=1, max_length=512)
    metadata_only: bool = True
    restricted_domain: bool = False
    reason: str = Field(min_length=1, max_length=2000)


class EnrollmentBody(BaseModel):
    enrollment_token: str = Field(default="", max_length=512)
    agent_id: str = Field(default="", max_length=128)
    # The external Agent declares its runtime during redemption.  Do not
    # manufacture a generic runtime when a Skill-first client omits it.
    runtime: str = Field(default="", max_length=128)
    environment: str = Field(default="development", max_length=64)
    node_id: str = Field(default="", max_length=128)
    public_key: str = Field(default="", max_length=10000)
    client_secret: str = Field(default="", max_length=512)


class GrantBody(BaseModel):
    owner_principal_id: str = Field(default="", max_length=128)
    responsible_group_id: str = Field(default="", max_length=128)
    environment: str = Field(default="development", max_length=64)
    security_domain_id: str = Field(default="DEFAULT", max_length=128)
    agent_name: str = Field(min_length=1, max_length=256)
    risk_tier: str = Field(default="STANDARD", max_length=32)
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=3600)


class ChannelBody(BaseModel):
    channel_name: str = Field(min_length=1, max_length=256)
    security_domain_id: str = Field(min_length=1, max_length=128)
    classification: str = Field(default="INTERNAL", max_length=32)
    channel_type: str = Field(default="TEAM", max_length=32)


class SecurityDomainBody(BaseModel):
    security_domain_id: str = Field(min_length=1, max_length=128)
    domain_name: str = Field(min_length=1, max_length=256)
    classification: str = Field(default="INTERNAL", max_length=32)
    purpose: str = Field(min_length=1, max_length=1000)
    owner_principal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    status: str = Field(default="ACTIVE", max_length=32)


class SecurityDomainMemberBody(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    membership_tier: str = Field(default="MEMBER", max_length=32)
    valid_until: str = Field(default="", max_length=64)
    status: str = Field(default="ACTIVE", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class SecurityDomainStatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class DomainBindingBody(BaseModel):
    binding_type: str = Field(min_length=1, max_length=32)
    target_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    approval_ref: str = Field(default="", max_length=256)


class DomainConversionDraftBody(BaseModel):
    source_group_id: str = Field(min_length=1, max_length=128)
    security_domain_id: str = Field(min_length=1, max_length=128)
    domain_name: str = Field(min_length=1, max_length=256)
    classification: str = Field(default="INTERNAL", max_length=32)
    purpose: str = Field(min_length=1, max_length=1000)
    owner_principal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class DraftMemberReviewBody(BaseModel):
    decision: str = Field(min_length=1, max_length=32)
    membership_tier: str = Field(default="MEMBER", max_length=32)
    valid_until: str = Field(default="", max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class DraftApplyBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    approval_ref: str = Field(default="", max_length=256)


class MessageBody(BaseModel):
    body: str = Field(min_length=1, max_length=100000)
    thread_type: str = Field(default="CHANNEL", max_length=32)
    thread_id: str = Field(default="", max_length=128)
    message_type: str = Field(default="TEXT", max_length=32)
    references: Dict[str, Any] = Field(default_factory=dict)
    response_language: str = Field(default="", max_length=8)


class ThreadBody(BaseModel):
    thread_type: str = Field(default="CHANNEL", max_length=32)
    parent_thread_id: str = Field(default="", max_length=128)
    classification: str = Field(default="INTERNAL", max_length=32)
    policy: Dict[str, Any] = Field(default_factory=dict)
    participant_principal_ids: list[str] = Field(default_factory=list, max_length=50)


class BarrierBody(BaseModel):
    node_key: str = Field(min_length=1, max_length=128)
    policy: Dict[str, Any] = Field(default_factory=dict)
    participant_snapshot: list[Dict[str, Any]] = Field(default_factory=list)
    channel_id: str = Field(default="", max_length=128)
    run_id: str = Field(default="", max_length=128)
    checkpoint_id: str = Field(default="", max_length=128)


class ArrivalBody(BaseModel):
    report: Dict[str, Any] = Field(default_factory=dict)
    participant_role: str = Field(default="MEMBER", max_length=64)
    idempotency_key: str = Field(default="", max_length=256)


class BarrierRecoveryBody(BaseModel):
    action: str = Field(default="", max_length=32)
    substitute_principal_id: str = Field(default="", max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class DecisionBody(BaseModel):
    decision: str = Field(default="RELEASE", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class RegistrationApprovalBody(DecisionBody):
    organization_id: str = Field(min_length=1, max_length=128)


class RoleBody(BaseModel):
    role_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class RoleRevokeBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class EntryAccessBody(BaseModel):
    app_enabled: bool
    reason: str = Field(min_length=1, max_length=2000)


class PermissionOverrideBody(BaseModel):
    resource_action: str = Field(min_length=1, max_length=256)
    effect: str = Field(default="ALLOW", max_length=16)
    data_scope: str = Field(default="NONE", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class ActionCardBody(BaseModel):
    action_type: str = Field(min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=256)


class GatewayTokenBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    client_secret: str = Field(default="", max_length=512)
    public_key: str = Field(default="", max_length=10000)
    signature: str = Field(default="", max_length=10000)
    challenge: str = Field(default="", max_length=512)
    instance_id: str = Field(default="", max_length=128)
    channel_id: str = Field(default="", max_length=128)
    security_domain_id: str = Field(default="", max_length=128)
    node_id: str = Field(default="", max_length=128)
    scopes: list[str] = Field(default_factory=list, max_length=16)


class GatewayActivationBody(GatewayTokenBody):
    baseline: Dict[str, Any] = Field(default_factory=dict)


class GatewayEvidenceBody(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    nonce: str = Field(default="", max_length=256)
    expires_at: str = Field(default="", max_length=64)


class GatewayRemediationBody(BaseModel):
    response: Dict[str, Any] = Field(default_factory=dict)


class GatewayAckBody(BaseModel):
    claim_token: str = Field(min_length=1, max_length=512)
    success: bool = True
    reason: str = Field(default="", max_length=2000)


class GatewayMessageBody(BaseModel):
    body: str = Field(min_length=1, max_length=100000)
    thread_type: str = Field(default="CHANNEL", max_length=32)
    thread_id: str = Field(default="", max_length=128)
    references: Dict[str, Any] = Field(default_factory=dict)


class GatewayKnowledgeBody(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=100000)
    summary: str = Field(default="", max_length=4000)
    domain: str = Field(default="", max_length=128)
    topic: str = Field(default="", max_length=128)
    difficulty: str = Field(default="INTERMEDIATE", max_length=32)
    category: str = Field(default="", max_length=128)
    importance: int = Field(default=5, ge=1, le=10)
    sharing_scope: str = Field(default="PRINCIPAL_PRIVATE", max_length=32)
    organization_id: str = Field(default="", max_length=128)
    hierarchy_depth: Optional[int] = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=3, max_length=2000)


class ChannelMemberBody(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    member_role: str = Field(default="MEMBER", max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


class LegalHoldBody(BaseModel):
    hold_id: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=2000)


class LifecycleBody(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)
    deletion_after: Optional[str] = Field(default=None, max_length=64)


class BridgeBody(BaseModel):
    source_domain_id: str = Field(min_length=1, max_length=128)
    target_domain_id: str = Field(min_length=1, max_length=128)
    transfer_mode: str = Field(default="SUMMARY", max_length=32)
    classification: str = Field(default="INTERNAL", max_length=32)
    recipients: list[str] = Field(default_factory=list, max_length=100)
    purpose: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)
    expires_at: Optional[str] = Field(default=None, max_length=64)
    full_copy_enabled: bool = False


class BridgeTransferBody(BaseModel):
    source_object_type: str = Field(min_length=1, max_length=64)
    source_object_id: str = Field(min_length=1, max_length=128)
    target_object_id: str = Field(default="", max_length=128)
    payload_digest: str = Field(default="", max_length=128)
    idempotency_key: str = Field(default="", max_length=256)
    reason: str = Field(min_length=1, max_length=2000)


class NotificationBody(BaseModel):
    principal_id: str = Field(default="", max_length=128)
    notification_type: str = Field(min_length=1, max_length=64)
    level: str = Field(default="INFO", max_length=32)
    dedupe_key: str = Field(min_length=1, max_length=256)
    payload: Dict[str, Any] = Field(default_factory=dict)
    deadline_at: Optional[str] = Field(default=None, max_length=64)


class MemoryCandidateBody(BaseModel):
    content: Dict[str, Any] = Field(default_factory=dict)
    classification: str = Field(default="INTERNAL", max_length=32)
    destination_scope: str = Field(default="CHANNEL", max_length=32)
    purpose: str = Field(min_length=1, max_length=2000)


class OwnerTransferBody(BaseModel):
    new_owner_principal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)


class OffboardBody(BaseModel):
    owner_type: str = Field(default="HUMAN", max_length=32)
    has_responsible_group: bool = False
    environment: str = Field(default="DEVELOPMENT", max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class ProfileBody(BaseModel):
    target_profile: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class PlatformCapabilityBody(BaseModel):
    enabled: bool
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class GraphCapabilityBody(BaseModel):
    state: str = Field(min_length=1, max_length=16)
    expected_version: int = Field(ge=1)
    evidence_ref: str = Field(default="", max_length=256)
    reason: str = Field(min_length=3, max_length=2000)


class LLMProviderProfileBody(BaseModel):
    profile_key: str = Field(min_length=1, max_length=128)
    provider_url: str = Field(min_length=1, max_length=512)
    model_id: str = Field(min_length=1, max_length=256)
    api_key: str = Field(default="", max_length=4096)
    approved_for: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)


class RetirementBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class PortalLLMPolicyBody(BaseModel):
    default_profile_id: str = Field(min_length=1, max_length=128)
    allowed_profile_ids: list[str] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)
    expected_version: int = Field(default=1, ge=1)


class PlatformAdminCommandBody(BaseModel):
    command_type: str = Field(min_length=1, max_length=64)
    target: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    security_domain_id: str = Field(default="DEFAULT", max_length=128)
    reason: str = Field(min_length=3, max_length=2000)
    expires_seconds: int = Field(default=900, ge=60, le=86400)


class PlatformCommandHelpBody(BaseModel):
    command_key: str = Field(default="", max_length=64)


class ManagedNodeBody(BaseModel):
    node_key: str = Field(min_length=1, max_length=128)
    host_reference: str = Field(min_length=1, max_length=256)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    os_user: str = Field(default="", max_length=128)
    roles: list[str] = Field(default_factory=list, max_length=8)
    failure_domain: str = Field(default="", max_length=128)
    trust_mode: str = Field(default="MUTUAL_TRUST", max_length=32)
    # Accepted only for a one-use verification request; register_node never persists it.
    ssh_password: str = Field(default="", max_length=2048)
    agent_info_path: str = Field(default="", max_length=512)
    reason: str = Field(min_length=3, max_length=2000)


class RuntimeHostPreflightBody(BaseModel):
    evidence: Dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)


class RuntimeHostBootstrapBody(BaseModel):
    host_manager_version: str = Field(min_length=1, max_length=128)
    recovery_channel: str = Field(min_length=3, max_length=512)
    root_remote_login: str = Field(default="DISABLED", max_length=16)
    uid_min: int = Field(default=200000, ge=100000, le=2000000000)
    uid_max: int = Field(default=299999, ge=100001, le=2000000000)
    reason: str = Field(min_length=3, max_length=2000)


class RuntimeIdentityLeaseBody(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class SharedStorageBody(BaseModel):
    storage_key: str = Field(min_length=1, max_length=128)
    backend_kind: str = Field(default="LOCAL_PATH", max_length=32)
    location_ref: str = Field(min_length=1, max_length=512)
    storage_purpose: str = Field(default="ADMIN_RUNTIME", max_length=32)
    reason: str = Field(min_length=3, max_length=2000)


class NodeStorageBindingBody(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    storage_id: str = Field(min_length=1, max_length=128)
    mount_reference: str = Field(min_length=1, max_length=512)
    role_scope: str = Field(default="ADMIN_AGENT", min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=2000)


class AgentPoolNodeOnboardingBody(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)
    expires_seconds: int = Field(default=1800, ge=300, le=86400)


class AgentPoolNodeActivationBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class AgentPoolNodeCheckinBody(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    runtime_version: str = Field(min_length=1, max_length=128)
    hostname: str = Field(min_length=1, max_length=128)
    shared_path: str = Field(default="", max_length=512)
    agent_info_path: str = Field(default="", max_length=512)
    runtime_preflight: Dict[str, Any]
    lifecycle_passed: bool
    root_remote_login: str = Field(max_length=16)
    recovery_channel: str = Field(min_length=3, max_length=512)


class AgentPoolNodeHeartbeatBody(BaseModel):
    token: str = Field(min_length=16, max_length=512)
    runtime_version: str = Field(default="unknown", max_length=128)


class ExternalEndpointBody(BaseModel):
    endpoint_key: str = Field(min_length=1, max_length=128)
    database_dialect: str = Field(default="", max_length=32)
    host_reference: str = Field(min_length=1, max_length=256)
    port: int = Field(ge=1, le=65535)
    tls_required: bool = True
    registration_grant_id: str = Field(default="", max_length=128)
    security_domain_id: str = Field(default="DEFAULT", max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class ExternalEndpointUpdateBody(BaseModel):
    host_reference: str = Field(min_length=1, max_length=256)
    port: int = Field(ge=1, le=65535)
    tls_required: bool = True
    reason: str = Field(min_length=3, max_length=2000)


class LLMProviderProfileProbeBody(BaseModel):
    """Ephemeral LLM draft used only for a pre-save connectivity probe."""
    profile_key: str = Field(min_length=1, max_length=128)
    provider_url: str = Field(min_length=1, max_length=512)
    model_id: str = Field(min_length=1, max_length=256)
    api_key: str = Field(default="", max_length=4096)


class EmbeddingProfileBody(BaseModel):
    profile_key: str = Field(min_length=1, max_length=128)
    provider_url: str = Field(default="", max_length=512)
    model_id: str = Field(default="", max_length=256)
    execution_mode: str = Field(min_length=1, max_length=32)
    dimension: int = Field(ge=0, le=65536)
    distance_metric: str = Field(default="COSINE", max_length=32)
    normalize_vectors: bool = True
    preprocessing: Dict[str, Any] = Field(default_factory=dict)
    modalities: list[str] = Field(default_factory=lambda: ["TEXT"], max_length=16)
    api_key: str = Field(default="", max_length=4096)
    secret_reference: str = Field(default="", max_length=512)
    model_fingerprint: str = Field(default="", max_length=256)
    expected_version: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class EmbeddingActivationBody(BaseModel):
    profile_key: str = Field(min_length=1, max_length=128)
    provider_url: str = Field(default="", max_length=512)
    model_id: str = Field(default="", max_length=256)
    execution_mode: str = Field(min_length=1, max_length=32)
    dimension: int = Field(ge=0, le=65536)
    distance_metric: str = Field(default="COSINE", max_length=32)
    api_key: str = Field(default="", max_length=4096)
    secret_reference: str = Field(default="", max_length=512)
    model_fingerprint: str = Field(default="", max_length=256)
    reason: str = Field(min_length=3, max_length=2000)


class EmbeddingContractBody(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    model_fingerprint: str = Field(default="", max_length=256)
    reason: str = Field(min_length=3, max_length=2000)


class EmbeddingSpaceBody(BaseModel):
    space_key: str = Field(min_length=1, max_length=128)
    contract_id: str = Field(min_length=1, max_length=128)
    default: bool = False
    writable: bool = False
    physical_ref: str = Field(default="", max_length=256)
    reason: str = Field(min_length=3, max_length=2000)


class EmbeddingBindingBody(BaseModel):
    binding_scope: str = Field(min_length=1, max_length=32)
    binding_subject_id: str = Field(min_length=1, max_length=128)
    profile_id: str = Field(min_length=1, max_length=128)
    space_id: str = Field(min_length=1, max_length=128)
    expected_version: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class EmbeddingProbeBody(BaseModel):
    scope: str = Field(default="PLATFORM", max_length=32)
    timeout: int = Field(default=30, ge=1, le=120)


class AgentEmbeddingProbeBody(BaseModel):
    observed_dimension: int = Field(ge=1, le=65536)
    observed_model: str = Field(default="", max_length=256)
    response_digest: str = Field(min_length=64, max_length=64)
    model_fingerprint: str = Field(default="", max_length=256)


class EmbeddingJobBody(BaseModel):
    job_kind: str = Field(min_length=1, max_length=32)
    target_space_id: str = Field(min_length=1, max_length=128)
    source_space_id: str = Field(default="", max_length=128)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class NativeAgentRequestBody(BaseModel):
    agent_name: str = Field(min_length=1, max_length=256)
    owner_principal_id: str = Field(min_length=1, max_length=128)
    template_key: str = Field(min_length=1, max_length=128)
    provider_profile_id: str = Field(default="", max_length=128)
    deployment_target_id: str = Field(default="DT_LOCAL_MANAGED", max_length=128)
    isolation_level: str = Field(default="DOMAIN_ISOLATED", max_length=32)
    classification: str = Field(default="INTERNAL", max_length=32)
    purpose: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=3, max_length=2000)


class NativeAgentDecisionBody(BaseModel):
    decision: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=3, max_length=2000)


class RuntimeIsolationContractBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    isolation_level: str = Field(min_length=1, max_length=32)
    enforcement_mode: str = Field(min_length=1, max_length=32)
    runtime_adapter: str = Field(min_length=1, max_length=128)
    runtime_identity: str = Field(default="", max_length=256)
    boundaries: list[str] = Field(default_factory=list, max_length=16)
    policy_digest: str = Field(default="", max_length=256)
    rootfs_digest: str = Field(default="", max_length=256)
    evidence_ref: str = Field(default="", max_length=512)
    external_agent: bool = False


class RuntimeIsolationHeartbeatBody(BaseModel):
    runtime_identity: str = Field(min_length=1, max_length=256)
    policy_digest: str = Field(default="", max_length=256)
    rootfs_digest: str = Field(default="", max_length=256)


class RuntimeIsolationTransitionBody(BaseModel):
    target_state: str = Field(min_length=1, max_length=32)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class DB4A2ADispatchBody(BaseModel):
    receiver_agent_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=256)
    context_ref: str = Field(min_length=1, max_length=256)
    snapshot_digest: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)
    scope_ref: str = Field(min_length=1, max_length=256)
    source_branch: str = Field(default="", max_length=256)
    branch_policy: str = Field(default="READ_ONLY", max_length=32)
    transport: str = Field(default="DB_MEDIATED", max_length=32)


class DB4A2ABranchBody(BaseModel):
    branch_name: str = Field(min_length=1, max_length=256)
    purpose: str = Field(min_length=1, max_length=500)


class NativeAgentActivationBody(BaseModel):
    llm_profile_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class NativeAgentExecuteBody(BaseModel):
    messages: list[Dict[str, Any]] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)


class ExternalRegistrationPolicyBody(BaseModel):
    state: str = Field(min_length=1, max_length=32)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


class AdminEnrollmentBody(BaseModel):
    admission_path: str = Field(min_length=1, max_length=32)
    public_key: str = Field(default="", max_length=10000)
    node_id: str = Field(min_length=1, max_length=256)
    host_reference: str = Field(default="", max_length=256)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    os_user: str = Field(default="", max_length=128)
    deployment_target: str = Field(default="", max_length=128)
    ssh_trust_mode: str = Field(default="MUTUAL_TRUST", max_length=32)
    ssh_password: str = Field(default="", max_length=2048)
    failure_domain: str = Field(default="", max_length=128)
    agent_info_path: str = Field(default="", max_length=512)
    reason: str = Field(min_length=3, max_length=2000)
    package_digest: str = Field(default="", max_length=128)


class AdminWeightBody(BaseModel):
    weight: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=3, max_length=2000)


class AdminObservationBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class AdminApprovalBody(BaseModel):
    weight: int = Field(ge=1, le=1_000_000)
    reason: str = Field(min_length=3, max_length=2000)


class AdminLeaderBody(BaseModel):
    lease_seconds: int = Field(default=60, ge=15, le=300)


class ProtectedInviteBody(BaseModel):
    principal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)
    valid_until: str = Field(default="", max_length=64)


class ContainmentCommandBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    requested_state: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=3, max_length=2000)
    expires_seconds: int = Field(default=300, ge=60, le=3600)


class ContainmentAcknowledgementBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=1)
    success: bool = True
    cleanup_evidence: Dict[str, Any] = Field(default_factory=dict)


class UpgradeStageBody(BaseModel):
    package_version: str = Field(min_length=1, max_length=64)
    edition: str = Field(min_length=1, max_length=32)
    package_digest: str = Field(min_length=32, max_length=128)
    signature_state: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=3, max_length=2000)


class UpgradeApprovalBody(BaseModel):
    decision: str = Field(min_length=1, max_length=16)
    reason: str = Field(min_length=3, max_length=2000)


class UpgradeVoteBody(UpgradeApprovalBody):
    upgrade_id: str = Field(min_length=1, max_length=128)
    term: int = Field(ge=1)
    fencing_token: int = Field(ge=1)


class UpgradeRolloutBody(BaseModel):
    node_ids: list[str] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=2000)


class UpgradeNodeBody(BaseModel):
    target_state: str = Field(min_length=1, max_length=32)
    active_work_count: int = Field(default=0, ge=0)
    health_state: str = Field(default="UNKNOWN", max_length=32)
    reason: str = Field(min_length=3, max_length=2000)


class SkillDistributionBody(BaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=100)
    skill_version: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=2000)


class SkillDistributionAcknowledgementBody(BaseModel):
    upgrade_id: str = Field(min_length=1, max_length=128)
    skill_version: str = Field(min_length=1, max_length=64)
    safe_point: bool = False
    verified: bool = True
    detail: str = Field(default="", max_length=1000)


class ArtifactReceiptBody(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=256)
    received_digest: str = Field(min_length=64, max_length=64)
    signature_state: str = Field(min_length=1, max_length=32)
    available: bool = True
    detail: Dict[str, Any] = Field(default_factory=dict)


class SessionPolicyBody(BaseModel):
    idle_timeout_seconds: int = Field(ge=60, le=86400)
    absolute_timeout_seconds: int = Field(ge=60, le=86400)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


def _session_scope_for_path(path: str) -> str:
    return "PORTAL" if str(path or "").startswith("/portal/") else "DASHBOARD"


def _cookie_name(scope: str = "DASHBOARD", port: Any = None) -> str:
    normalized = str(scope or "").upper()
    if normalized not in {"DASHBOARD", "PORTAL"}:
        raise ValueError("invalid session scope")
    prefix = "portal_session_id" if normalized == "PORTAL" else "dashboard_session_id"
    # The request port is authoritative because deployments may expose the
    # service on any port, independently of its packaged/default setting.
    if port is None:
        port = os.environ.get("MEMORY_SERVER_PORT", "8000")
    return f"{prefix}_{str(port or '8000')}"


def _session_timeout_seconds() -> int:
    """Return the bounded web Session lease (five minutes maximum)."""
    try:
        configured = int(os.environ.get("MEMORY_SESSION_TIMEOUT", "300"))
    except (TypeError, ValueError):
        configured = 300
    return max(60, min(identity_api.SESSION_MAX_SECONDS, configured))


def _dashboard_session_policy() -> Dict[str, Any]:
    return _session_policy("DASHBOARD")


def _session_policy(scope: str) -> Dict[str, Any]:
    try:
        return admin_management.session_policy(str(scope or "DASHBOARD").upper())
    except Exception:
        return {"idle_timeout_seconds": _session_timeout_seconds(), "absolute_timeout_seconds": 28800, "version": 0}


def _browser_session_expiry(value: Any) -> str:
    """Serialize a naive database timestamp with its local time-zone offset.

    Session rows intentionally use portable, naive ``TIMESTAMP`` values. A
    browser treating this value as UTC shifts an Oracle/YashanDB session by
    the server UTC offset, so response values must carry that offset.
    """
    try:
        timestamp = identity_api._timestamp(value)
    except identity_api.IdentityError:
        return ""
    if timestamp is None:
        return ""
    return timestamp.astimezone().isoformat()


def _session_from_request(request: Request, scope: str = "DASHBOARD") -> Optional[Dict[str, Any]]:
    normalized_scope = str(scope or "").upper()
    # Deployments may be reverse-proxied or exposed on an arbitrary port.  In
    # that case Starlette's parsed URL port can differ from the port used when
    # the login response minted the cookie.  Resolve the exact current name
    # first, then the configured port and finally the historical unqualified
    # cookie names so compatibility routes share the same session as modern
    # FastAPI routes.
    prefix = "portal_session_id" if normalized_scope == "PORTAL" else "dashboard_session_id"
    candidate_names = []
    for candidate_port in (
        request.url.port,
        os.environ.get("MEMORY_SERVER_PORT"),
        request.headers.get("x-forwarded-port"),
    ):
        if candidate_port is None:
            continue
        name = f"{prefix}_{str(candidate_port).strip()}"
        if name not in candidate_names:
            candidate_names.append(name)
    candidate_names.extend((prefix,))
    raw = next((request.cookies.get(name) for name in candidate_names if request.cookies.get(name)), None)
    if not raw:
        # Last-resort compatibility for proxies that rewrite cookie suffixes;
        # only accept the scope-specific prefix and never a foreign session.
        raw = next((value for name, value in request.cookies.items()
                    if str(name).startswith(prefix + "_") and value), None)
    if not raw:
        return None
    cached = getattr(request.state, "cx_session_cache", None)
    if cached is not None:
        return cached
    with _schema_owner_context():
        policy = _session_policy(normalized_scope)
        session = identity_api.resolve_session(raw, ttl_seconds=int(policy["idle_timeout_seconds"]), absolute_ttl_seconds=int(policy["absolute_timeout_seconds"]), expected_scope=normalized_scope)
    if session:
        request.state.cx_session = session
        request.state.cx_session_id = raw
        request.state.cx_session_scope = normalized_scope
        request.state.cx_session_cache = session
    return session


def principal(request: Request) -> Dict[str, Any]:
    # Sync endpoints run in a reusable worker-thread pool. ContextVar prevents
    # concurrent-task sharing, but a value set by a completed sync Gateway
    # endpoint can remain in that worker's context. Fence every Human request
    # before resolving its session so no prior Agent DB identity is restored
    # after a temporary Schema Owner authorization check.
    clear_context = getattr(connection, "set_agent_context", None)
    if callable(clear_context):
        clear_context(None)
    scope = _session_scope_for_path(request.url.path)
    session = _session_from_request(request, scope)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    entry = "PORTAL" if scope == "PORTAL" else "APP"
    try:
        with _schema_owner_context():
            allowed = identity_api.entry_allowed(str(session["principal_id"]), entry)
        if not allowed:
            raise HTTPException(status_code=403, detail=f"{entry.title()} access is disabled")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Entry-access policy is unavailable") from exc
    return session


def require_csrf(request: Request, session: Dict[str, Any] = Depends(principal)) -> Dict[str, Any]:
    if str(session.get("mfa_level") or "NONE").upper() == "SETUP" and request.url.path not in _MFA_SETUP_ALLOWED_PATHS:
        raise HTTPException(status_code=403, detail="MFA setup required")
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return session
    token = request.headers.get("X-CSRF-Token", "")
    if not identity_api.verify_csrf(session, token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return session


def require_action(action: str):
    def dependency(session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
        try:
            with _schema_owner_context():
                access = identity_api.effective_access(str(session["principal_id"]), action)
        except Exception as exc:
            # Authorization failures must be distinguishable from a real deny;
            # otherwise a missing governance table or unavailable database is
            # presented to the operator as an ordinary empty/denied page.
            raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc
        if access["decision"] != "ALLOW":
            raise HTTPException(status_code=403, detail={"error": "permission denied", "access": access})
        return session
    return dependency


def require_action_cached(action: str):
    """Authorize one mutation with a request-local permission snapshot.

    Unlike the generic dependency, this keeps the bounded authorization cache
    active while the endpoint executes.  It must only be used by endpoints that
    do not mutate roles, delegations, overrides, or Principal state during the
    same request.  Channel message persistence is such a read/write operation:
    it performs repeated membership and platform-management checks before
    committing a message and an Agent dispatch.
    """
    def dependency(session: Dict[str, Any] = Depends(require_csrf)):
        with identity_api.cached_authorization():
            try:
                with _schema_owner_context():
                    access = identity_api.effective_access(str(session["principal_id"]), action)
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc
            if access["decision"] != "ALLOW":
                raise HTTPException(status_code=403, detail={"error": "permission denied", "access": access})
            yield session
    return dependency


def _identity_http_error(exc: Exception, detail: str, *, identity_status: int = 400) -> HTTPException:
    """Map identity failures without leaking database or governance details."""
    # Governance conflicts are expected, auditable operator outcomes.  They
    # must not be presented as an unavailable identity service, otherwise a
    # rejected second binding looks like an infrastructure failure.
    if isinstance(exc, security_domain_api.SecurityDomainConflict):
        return HTTPException(status_code=409, detail=str(exc) or detail)
    if isinstance(exc, security_domain_api.SecurityDomainError):
        return HTTPException(status_code=400, detail=str(exc) or detail)
    if isinstance(exc, model_governance_api.QuotaExceeded):
        return HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc) or detail, "retryable": False})
    if isinstance(exc, model_governance_api.ModelGovernanceError):
        return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc) or detail, "retryable": bool(exc.retryable)})
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=detail)
    if isinstance(exc, identity_api.IdentityError):
        return HTTPException(status_code=identity_status, detail=detail)
    if isinstance(exc, security_lifecycle.LifecycleError):
        return HTTPException(status_code=identity_status, detail=detail)
    return HTTPException(status_code=503, detail="Identity governance service unavailable")


def _optional_module(name: str):
    """Load an edition-gated service without importing it into Community."""
    import importlib
    try:
        return importlib.import_module(f"lib.{name}")
    except (ImportError, ModuleNotFoundError):
        try:
            return importlib.import_module(f"shared.lib.{name}")
        except (ImportError, ModuleNotFoundError):
            return None


def _set_session_cookie(response: Response, session: Dict[str, str], scope: str = "DASHBOARD", port: Any = None) -> None:
    secure = os.environ.get("CX_WEB_SECURE_COOKIE", "").lower() in {"1", "true", "yes"}
    response.set_cookie(
        _cookie_name(scope, port), session["session_id"], max_age=int(_session_policy(scope)["absolute_timeout_seconds"]),
        httponly=True, samesite="lax", secure=secure, path="/",
    )


def _shell() -> FileResponse:
    for path in (DIST_ROOT / "index.html", WEB_ROOT / "index.html"):
        if path.is_file():
            # The shell contains the hashed UI bundle reference. Avoid keeping
            # an old shell after a controlled platform upgrade.
            return FileResponse(path, headers={"Cache-Control": "no-store"})
    raise HTTPException(status_code=503, detail="Web assets are not built")


@app.get("/health")
@app.get("/api/health")
def health() -> Dict[str, Any]:
    """Process liveness only; database readiness is exposed separately."""
    return {
        "status": "ok",
        "product": "Chuanxu",
        "product_zh": "川序",
        "product_type": "AI Agent Management Platform",
        "technical_project": "AI Agent Infra with DB",
        "version": VERSION,
        "profile": _runtime_profile(),
        "database": os.environ.get("CX_DATABASE", "adapter"),
    }


@app.get("/ready")
@app.get("/api/ready")
def readiness(response: Response) -> Dict[str, Any]:
    """Fail closed until the database and current control-plane schema respond."""
    try:
        suffix = str(connection.merge_scalar_suffix())
        with _schema_owner_context():
            probe = connection.execute_query_one("SELECT 1 AS READY" + suffix, {})
            required = connection.execute_query_one(
                "SELECT COUNT(*) AS CNT FROM CX_PLATFORM_CAPABILITIES "
                "WHERE CAPABILITY_KEY IN ('identity','authorization','wallboard','model_finance','external_model_evidence')",
                {},
            )
        probe_row = {str(key).lower(): value for key, value in dict(probe or {}).items()}
        required_row = {str(key).lower(): value for key, value in dict(required or {}).items()}
        if int(probe_row.get("ready") or 0) != 1 or int(required_row.get("cnt") or 0) != 5:
            raise RuntimeError("required control-plane capabilities are incomplete")
    except Exception:
        response.status_code = 503
        return {
            "status": "not_ready",
            "version": VERSION,
            "checks": {"database": "unavailable", "control_plane": "unavailable"},
        }
    return {
        "status": "ready",
        "version": VERSION,
        "checks": {"database": "ready", "control_plane": "ready"},
    }


@app.get("/app")
@app.get("/app/{page}")
def shell(page: str = "monitor") -> FileResponse:
    return _shell()


@app.get("/register", include_in_schema=False)
def registration_page() -> FileResponse:
    """Use one entry-independent registration surface for both consoles."""
    return _shell()


@app.get("/api/auth/registration-policy")
def registration_policy() -> Dict[str, Any]:
    try:
        return {
            "context": "SELF",
            "fields": identity_api.registration_field_policies("SELF"),
            "token_required": identity_api.human_registration_token_required(),
        }
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Registration policy service unavailable") from exc


@app.get("/api/auth/external/providers")
def external_identity_providers(entry: str = "PORTAL") -> Dict[str, Any]:
    try:
        return {"items": external_identity_api.list_providers(entry)}
    except external_identity_api.ExternalIdentityError as exc:
        raise HTTPException(status_code=400, detail="External identity provider is unavailable") from exc


@app.post("/api/auth/external/start")
def external_identity_start(body: ExternalLoginStartBody) -> Dict[str, Any]:
    try:
        return external_identity_api.start_transaction(body.provider_id, body.entry, body.redirect_uri)
    except external_identity_api.ExternalIdentityError as exc:
        raise HTTPException(status_code=400, detail="External identity login cannot be started") from exc


@app.post("/api/auth/external/callback")
def external_identity_callback(body: ExternalLoginCallbackBody) -> Dict[str, Any]:
    try:
        # This validates the transaction only. A provider adapter must still
        # normalize claims and pass the separate binding/approval workflow.
        return external_identity_api.validate_callback(
            body.transaction_id, body.state, body.nonce, body.callback_digest,
        )
    except external_identity_api.ExternalIdentityError as exc:
        raise HTTPException(status_code=400, detail="External identity callback was rejected") from exc


@app.get("/api/auth/external/status/{transaction_id}")
def external_identity_status(transaction_id: str) -> Dict[str, Any]:
    try:
        return external_identity_api.transaction_status(transaction_id)
    except external_identity_api.ExternalIdentityError as exc:
        raise HTTPException(status_code=404, detail="External identity transaction is unavailable") from exc


@app.get("/login", include_in_schema=False)
def legacy_login_redirect() -> RedirectResponse:
    """Retire the password-only Dashboard entry in favor of MFA admission."""
    return RedirectResponse(url="/app", status_code=302)


@app.post("/api/auth/register", status_code=202)
def register(body: RegistrationBody) -> Dict[str, Any]:
    try:
        result = identity_api.register_human(
            body.username, body.password, body.email, body.invite_code,
            display_name=body.display_name,
            mobile=body.mobile, registration_token=body.registration_token,
        )
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=400, detail="Registration could not be completed") from exc
    return {"success": True, "status": result.get("status"), "request_id": result.get("request_id"), "username": result.get("username")}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response, request: Request) -> Dict[str, Any]:
    try:
        if security_lifecycle.is_login_locked(body.username):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        user = identity_api.authenticate_local(body.username, body.password)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Identity service unavailable") from exc
    if not user or not user.get("principal_id"):
        try:
            security_lifecycle.record_login_failure(body.username)
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        if not identity_api.entry_allowed(str(user["principal_id"]), "APP"):
            raise HTTPException(status_code=403, detail="Application access is disabled")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Entry-access policy is unavailable") from exc
    mfa_level = "NONE"
    try:
        required = security_lifecycle.mfa_required(str(user["principal_id"]))
        method = security_lifecycle.verify_mfa(str(user["principal_id"]), body.mfa_code) if body.mfa_code else ""
        if required and not method and not security_lifecycle.has_active_mfa_factor(str(user["principal_id"])):
            # A legacy/bootstrap administrator must be able to enroll the
            # first factor, but receives no application access beforehand.
            security_lifecycle.record_login_success(str(user["principal_id"]))
            session = identity_api.create_session(
                str(user["principal_id"]), str(user["user_id"]), _local_node_id(),
                mfa_level="SETUP", ttl_seconds=int(_dashboard_session_policy()["idle_timeout_seconds"]),
                session_scope="DASHBOARD",
            )
            _set_session_cookie(response, session, port=request.url.port)
            return {
                "success": True,
                "principal_id": user["principal_id"],
                "user_id": user["user_id"],
                "username": user["username"],
                "role": user.get("role", "USER"),
                "mfa_level": "SETUP",
                "mfa_setup_required": True,
                "csrf_token": session["csrf_token"],
                "expires_at": _browser_session_expiry(session.get("expires_at")),
                "session_timeout_seconds": _session_timeout_seconds(),
            }
        admission = governed_contracts.mfa_admission_decision(
            principal_active=True, required=required, level="STRONG" if method else "NONE",
            accepted=bool(method), method=method,
        )
        if not admission.allowed:
            security_lifecycle.record_login_failure(body.username)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        mfa_level = "STRONG" if method else "NONE"
        security_lifecycle.record_login_success(str(user["principal_id"]))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="MFA service unavailable") from exc
    try:
        session = identity_api.create_session(
            str(user["principal_id"]), str(user["user_id"]), _local_node_id(),
            mfa_level=mfa_level,
            ttl_seconds=int(_dashboard_session_policy()["idle_timeout_seconds"]),
            session_scope="DASHBOARD",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    _set_session_cookie(response, session, port=request.url.port)
    return {
        "success": True,
        "principal_id": user["principal_id"],
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user.get("role", "USER"),
        "mfa_level": mfa_level,
        "mfa_setup_required": False,
        "csrf_token": session["csrf_token"],
        "expires_at": _browser_session_expiry(session.get("expires_at")),
        "session_timeout_seconds": _session_timeout_seconds(),
    }


@app.post("/api/auth/logout")
@app.post("/portal/api/auth/logout")
def logout(request: Request, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, bool]:
    scope = _session_scope_for_path(request.url.path)
    scopes = ("PORTAL", "DASHBOARD") if scope == "PORTAL" else ("DASHBOARD",)
    try:
        for candidate_scope in scopes:
            raw = request.cookies.get(_cookie_name(candidate_scope, request.url.port), "")
            if raw:
                identity_api.revoke_session(raw, "logout")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    response = JSONResponse({"success": True})
    for candidate_scope in scopes:
        response.delete_cookie(_cookie_name(candidate_scope, request.url.port), path="/")
    return response


@app.post("/api/auth/password-reset/request")
def password_reset_request(body: PasswordResetRequestBody) -> Dict[str, Any]:
    """Always return the same response so local-account existence is not disclosed."""
    try:
        result = security_lifecycle.issue_password_reset(body.username)
    except Exception:
        result = {"expires_in_seconds": 900}
    return {
        "success": True,
        "message": "If the account is eligible, a password reset instruction will be delivered.",
        "expires_in_seconds": int(result.get("expires_in_seconds") or 900),
    }


@app.post("/api/auth/password-reset/consume")
def password_reset_consume(body: PasswordResetConsumeBody) -> Dict[str, Any]:
    try:
        changed = security_lifecycle.consume_password_reset(
            body.token, body.new_password, reason=body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Password reset token is invalid or expired") from exc
    return {"success": bool(changed)}


@app.post("/api/auth/mfa/enroll")
@app.post("/portal/api/auth/mfa/enroll")
def mfa_enroll(body: MfaEnrollBody, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
    target = body.target_principal_id or str(session["principal_id"])
    if target != str(session["principal_id"]):
        raise HTTPException(status_code=403, detail="MFA enrollment target is outside the current session")
    try:
        return security_lifecycle.enroll_totp(str(session["principal_id"]), target, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "MFA enrollment was not accepted") from exc


@app.post("/api/auth/mfa/confirm")
@app.post("/portal/api/auth/mfa/confirm")
def mfa_confirm(body: MfaConfirmBody, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
    try:
        confirmed = security_lifecycle.confirm_totp(
            str(session["principal_id"]), body.factor_id, body.code, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "MFA confirmation failed") from exc
    if not confirmed:
        raise HTTPException(status_code=400, detail="MFA confirmation failed")
    try:
        promoted = identity_api.set_session_mfa_level(str(session.get("session_digest") or ""), "STRONG")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    if not promoted:
        raise HTTPException(status_code=503, detail="Session service unavailable")
    session["mfa_level"] = "STRONG"
    return {"success": True, "mfa_level": "STRONG"}


@app.get("/api/auth/me")
def me(session: Dict[str, Any] = Depends(principal)) -> Dict[str, Any]:
    try:
        access = identity_api.effective_access(str(session["principal_id"]), "profile.read")
        summary = identity_api.principal_summary(str(session["principal_id"]))
        required_mfa = security_lifecycle.mfa_required(str(session["principal_id"]))
        read_only = identity_api.is_global_read_only_principal(str(session["principal_id"]))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Identity governance service unavailable") from exc
    return {
        "principal_id": session["principal_id"],
        "user_id": session.get("user_id"),
        "mfa_level": session.get("mfa_level"),
        "mfa_required": required_mfa,
        "mfa_setup_required": str(session.get("mfa_level") or "NONE").upper() == "SETUP",
        "access": access,
        "registration_mode": identity_api.registration_mode(),
        "profile": summary,
        "expires_at": _browser_session_expiry(session.get("expires_at")),
        "session_timeout_seconds": _session_timeout_seconds(),
        "read_only": read_only,
    }


@app.get("/api/capabilities")
def capabilities(session: Dict[str, Any] = Depends(principal)) -> Dict[str, Any]:
    """Return a presentation manifest derived from current DB permissions."""
    if str(session.get("mfa_level") or "NONE").upper() == "SETUP":
        return {
            "version": session.get("permission_version"),
            "release_version": VERSION,
            "profile": _runtime_profile(),
            "pages": [],
            "actions": {},
            "maturity": {"core": "stable", "graph": "experimental", "channel": "active"},
            "features": [],
            "mfa_setup_required": True,
            "session_timeout_seconds": _session_timeout_seconds(),
        }
    pages = {
        "monitor": "agents.read", "agents": "agents.read", "tasks": "tasks.read",
        "workspaces": "workspaces.read", "knowledge": "knowledge.read", "memory": "memory.read",
        "skills": "skills.read", "specs": "specs.read", "branches": "tasks.read",
        "collab": "channels.read", "loops": "tasks.read", "graph": "graphs.read",
        "channels": "channels.read", "barriers": "barriers.read", "approvals": "approvals.read", "compliance": "agents.read",
        "audit": "audit.read", "users": "users.read",
        "organization": "organizations.read",
        "security-domains": "domains.manage",
        "platform": "platform.manage", "platform-operations": "platform.manage", "deployment": "platform.manage",
        "native-agents": "platform.manage", "wallboard": "wallboard.read",
    }
    feature_map = {
        "approvals": "approvals", "audit": "audit", "compliance": "compliance",
    }
    operation_actions = {
        "profile.update", "agents.enroll", "agents.operate", "agents.transfer", "agents.offboard",
        "agents.read.all", "agents.manage", "agents.manage.all", "agents.enroll.others", "agents.claim",
        "skills.write", "branches.write", "loops.write", "tasks.write", "workspaces.write", "specs.write",
        "channels.create", "channels.read.all", "channels.write", "channels.manage_members", "channels.lifecycle",
        "channels.quarantine", "channels.bridge", "channels.actions.decide", "memory.review",
        "collab.write", "approvals.decide", "audit.export",
        "notifications.manage", "barriers.create", "barriers.arrive", "barriers.release", "barriers.recover",
        "users.approve", "users.roles.manage", "users.permissions.manage",
        "users.identity.link", "users.security.manage", "users.sessions.read",
        "sessions.revoke", "users.delegations.read", "users.delegations.manage",
        "organizations.manage", "organizations.changes.create", "organizations.changes.write",
        "organizations.changes.submit", "organizations.changes.approve", "organizations.changes.publish",
        "organizations.history.read", "organizations.members.manage",
        "organizations.reporting.manage", "organizations.sync.manage",
        "organizations.emergency", "organizations.export",
        "domains.manage",
        "platform.manage", "model_usage.read", "model_usage.manage", "model_gateway.manage", "wallboard.read", "wallboard.manage",
    }
    features = _edition_features()
    try:
        access_by_action = identity_api.effective_access_many(
            str(session["principal_id"]), set(pages.values()) | operation_actions,
        )
        read_only = identity_api.is_global_read_only_principal(str(session["principal_id"]))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc
    try:
        platform_page_states = platform_capabilities.page_states()
    except platform_capabilities.CapabilityServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="Platform capability service unavailable") from exc
    allowed = [
        page for page, action in pages.items()
        if access_by_action[action]["decision"] == "ALLOW"
        and (page not in feature_map or features is None or features.has_feature(feature_map[page]))
        and platform_page_states.get(page, True)
    ]
    if read_only:
        for action in operation_actions:
            access_by_action[action] = {
                "decision": "DENY", "scopes": ["NONE"], "sources": ["session:read-only"],
                "policy_version": session.get("permission_version"),
            }
    profile = _runtime_profile()
    return {
        "version": session.get("permission_version"), "release_version": VERSION,
        "profile": profile,
        "pages": allowed, "actions": access_by_action,
        "maturity": {"core": "stable", "graph": "experimental", "channel": "active"},
        "features": sorted(getattr(features, "FEATURES", set()) if features else set()),
        "platform_capabilities": platform_page_states,
        "session_timeout_seconds": _session_timeout_seconds(),
        "read_only": read_only,
    }


@app.get("/api/platform/capabilities")
def platform_capability_list(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return platform_capabilities.list_capabilities(limit=limit)
    except platform_capabilities.CapabilityServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="Platform capability service unavailable") from exc


@app.put("/api/platform/capabilities/{capability_key}")
def platform_capability_update(
    capability_key: str,
    body: PlatformCapabilityBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return platform_capabilities.set_enabled(
            str(session["principal_id"]), capability_key, body.enabled,
            body.reason, body.expected_version,
        )
    except platform_capabilities.CapabilityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except platform_capabilities.CapabilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except platform_capabilities.CapabilityServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="Platform capability service unavailable") from exc


@app.get("/api/platform/graph-capabilities")
def graph_capability_list(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return graph_production_profile.list_capabilities()
    except graph_production_profile.ProfileUnavailable as exc:
        raise HTTPException(status_code=503, detail="Graph capability matrix is unavailable") from exc


@app.put("/api/platform/graph-capabilities/{capability_key}")
def graph_capability_update(
    capability_key: str,
    body: GraphCapabilityBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        # Runtime profile selection remains release-controlled. This endpoint
        # changes one governed capability inside that Production baseline.
        return graph_production_profile.set_state(
            str(session["principal_id"]), capability_key, body.state,
            body.reason, body.expected_version, body.evidence_ref,
        )
    except graph_production_profile.ProfileConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except graph_production_profile.ProfileUnavailable as exc:
        raise HTTPException(status_code=503, detail="Graph capability matrix is unavailable") from exc


@app.get("/api/platform/administration")
def platform_administration_state(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.list_management_state(str(session["principal_id"]))
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Platform Administration service is unavailable") from exc


@app.get("/api/platform/admin-enrollments")
def platform_admin_enrollment_list(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return {"items": admin_management.list_admin_enrollments(str(session["principal_id"]), limit)}
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/session-policies")
def platform_session_policies(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return {"dashboard": admin_management.session_policy("DASHBOARD"), "portal": admin_management.session_policy("PORTAL")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Session policy service is unavailable") from exc


@app.put("/api/platform/session-policies/{kind}")
def platform_session_policy_update(
    kind: str, body: SessionPolicyBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.update_session_policy(
            str(session["principal_id"]), kind, body.idle_timeout_seconds,
            body.absolute_timeout_seconds, body.expected_version, body.reason,
        )
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/administration/initialize")
def platform_administration_initialize(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.initialize()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Platform Administration initialization failed") from exc


@app.post("/api/platform/administration/invitations")
def platform_administration_invite(
    body: ProtectedInviteBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.invite_protected_human(str(session["principal_id"]), body.principal_id, body.reason, body.valid_until)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-enrollments")
def platform_admin_enrollment(
    body: AdminEnrollmentBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.create_admin_enrollment(
            str(session["principal_id"]), body.admission_path, body.public_key,
            body.node_id, body.reason, body.package_digest,
            host_reference=body.host_reference, ssh_port=body.ssh_port,
            os_user=body.os_user, deployment_target=body.deployment_target,
            ssh_trust_mode=body.ssh_trust_mode, ssh_password=body.ssh_password,
            failure_domain=body.failure_domain, agent_info_path=body.agent_info_path,
        )
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-enrollments/{enrollment_id}/observe")
def platform_admin_enrollment_observe(
    enrollment_id: str, body: AdminObservationBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.observe_admin_enrollment(str(session["principal_id"]), enrollment_id, body.agent_id, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-members/{member_id}/approve")
def platform_admin_member_approve(
    member_id: str, body: AdminApprovalBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.approve_admin_member(str(session["principal_id"]), member_id, body.weight, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/platform/admin-members/{member_id}/weight")
def platform_admin_weight(
    member_id: str, body: AdminWeightBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.set_member_weight(str(session["principal_id"]), member_id, body.weight, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-members/{member_id}/leader")
def platform_admin_leader(
    member_id: str, body: AdminLeaderBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.acquire_leader(str(session["principal_id"]), member_id, body.lease_seconds)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/containment")
def platform_containment(
    body: ContainmentCommandBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.issue_containment(str(session["principal_id"]), body.agent_id, body.instance_id, body.requested_state, body.reason, body.expires_seconds)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/upgrades")
def platform_upgrade_stage(
    body: UpgradeStageBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.stage_upgrade(str(session["principal_id"]), body.package_version, body.edition, body.package_digest, body.signature_state, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/upgrades/upload")
async def platform_upgrade_upload(
    request: Request, reason: str = "",
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    """Accept one release archive into the isolated management staging area."""
    filename = request.headers.get("X-Upload-Filename", "")
    try:
        content = await request.body()
        return admin_management.stage_upgrade_archive(
            str(session["principal_id"]), filename, content, reason, VERSION,
        )
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Upgrade archive staging service is unavailable") from exc


@app.post("/api/platform/upgrades/{upgrade_id}/preflight")
def platform_upgrade_preflight(
    upgrade_id: str,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        features = _edition_features()
        edition = str(getattr(features, "EDITION", "Enterprise"))
        return admin_management.preflight_upgrade(str(session["principal_id"]), upgrade_id, edition)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/upgrades/{upgrade_id}/human-approval")
def platform_upgrade_human_approval(
    upgrade_id: str, body: UpgradeApprovalBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.approve_upgrade(str(session["principal_id"]), upgrade_id, body.decision, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/upgrades/{upgrade_id}/rollout")
def platform_upgrade_rollout(
    upgrade_id: str, body: UpgradeRolloutBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.start_upgrade_rollout(str(session["principal_id"]), upgrade_id, body.node_ids, body.reason)
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/upgrades/{upgrade_id}/skill-distribution")
def platform_upgrade_skill_distribution(
    upgrade_id: str, body: SkillDistributionBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return admin_management.distribute_upgrade_skill(
            str(session["principal_id"]), upgrade_id, body.agent_ids, body.skill_version, body.reason,
        )
    except (admin_management.ManagementError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/native-bootstrap")
def native_bootstrap_status(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        marker = connection.execute_query_one(
            "SELECT BOOTSTRAP_KEY,BOOTSTRAP_VERSION,STATUS,STARTED_AT,COMPLETED_AT,UPDATED_AT "
            "FROM CX_NATIVE_BOOTSTRAP WHERE BOOTSTRAP_KEY='v4.3.6'",
        )
        return {"status": "MIGRATION_PENDING" if not marker else "READY", "bootstrap": marker or {}}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Native Agent bootstrap status unavailable") from exc


@app.post("/api/platform/native-bootstrap")
def native_bootstrap_run(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.bootstrap_native_agents()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Native Agent bootstrap failed") from exc


@app.get("/api/agent-templates")
def native_agent_templates(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        items = native_agent_api.list_templates(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent templates are unavailable") from exc


@app.get("/api/deployment-targets")
def deployment_targets(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        suffix, params = native_agent_api._limit(limit)
        targets = connection.execute_query(
            "SELECT TARGET_ID,TARGET_KEY,TARGET_TYPE,STATUS,MANAGED,CREATED_AT,UPDATED_AT "
            "FROM CX_DEPLOYMENT_TARGETS ORDER BY TARGET_KEY" + suffix, params,
        )
        return {"items": [{str(k).lower(): v for k, v in dict(row).items()} for row in targets],
                "reference_adapters": deployment_adapters.describe_reference_adapters()}
    except Exception as exc:
        raise _identity_http_error(exc, "Deployment targets are unavailable") from exc


@app.post("/api/runtime-isolation/contracts")
def runtime_isolation_contract(
    body: RuntimeIsolationContractBody,
    session: Dict[str, Any] = Depends(require_action("agents.manage")),
) -> Dict[str, Any]:
    try:
        contract = runtime_isolation.RuntimeIsolationContract(
            isolation_level=body.isolation_level,
            enforcement_mode=body.enforcement_mode,
            runtime_adapter=body.runtime_adapter,
            runtime_identity=body.runtime_identity,
            evidence_ref=body.evidence_ref,
            boundaries=frozenset(body.boundaries),
            policy_digest=body.policy_digest,
            rootfs_digest=body.rootfs_digest,
        )
        admission = runtime_isolation.validate_admission(
            contract, requested_level=body.isolation_level,
            external_agent=body.external_agent,
        )
        persisted = runtime_isolation.persist_contract(
            str(session["principal_id"]), body.agent_id, body.instance_id, contract,
        )
        return {**persisted, "admission": admission}
    except Exception as exc:
        raise _identity_http_error(exc, "Runtime isolation contract was denied") from exc


@app.get("/api/runtime-isolation/contracts/{agent_id}/{instance_id}")
def runtime_isolation_contract_get(
    agent_id: str,
    instance_id: str,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        return runtime_isolation.get_contract(agent_id, instance_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Runtime isolation contract is unavailable") from exc


@app.post("/api/runtime-isolation/contracts/{agent_id}/{instance_id}/transition")
def runtime_isolation_contract_transition(
    agent_id: str,
    instance_id: str,
    body: RuntimeIsolationTransitionBody,
    session: Dict[str, Any] = Depends(require_action("agents.manage")),
) -> Dict[str, Any]:
    try:
        return runtime_isolation.transition_contract(
            str(session["principal_id"]), agent_id, instance_id, body.target_state,
            body.reason, body.expected_version,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Runtime isolation transition was denied") from exc


@app.post("/api/db4a2a/dispatches")
def db4a2a_dispatch(
    body: DB4A2ADispatchBody,
    session: Dict[str, Any] = Depends(require_action("agents.operate")),
) -> Dict[str, Any]:
    try:
        reference = db4a2a.ContextReference(
            body.context_ref, body.snapshot_digest, body.expected_version,
            body.scope_ref, body.source_branch,
        )
        envelope = db4a2a.build_dispatch(
            task_id=body.task_id, context=reference,
            branch_policy=body.branch_policy, transport=body.transport,
        )
        return db4a2a.persist_dispatch(
            str(session["principal_id"]), body.receiver_agent_id, envelope,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "DB4A2A dispatch was denied") from exc


@app.get("/api/db4a2a/dispatches")
def db4a2a_dispatches(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("tasks.read")),
) -> Dict[str, Any]:
    try:
        return db4a2a.list_dispatches(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "DB4A2A dispatches are unavailable") from exc


@app.post("/api/db4a2a/dispatches/{dispatch_id}/branch")
def db4a2a_dispatch_branch(
    dispatch_id: str,
    body: DB4A2ABranchBody,
    session: Dict[str, Any] = Depends(require_action("agents.operate")),
) -> Dict[str, Any]:
    try:
        return db4a2a.create_dispatch_branch(
            str(session["principal_id"]), dispatch_id, body.branch_name, body.purpose,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "DB4A2A branch was denied") from exc


@app.get("/api/graph-assurance/invariants")
def graph_assurance_invariants(
    session: Dict[str, Any] = Depends(require_action("graphs.read")),
) -> Dict[str, Any]:
    """Return bounded read-only Graph Runtime integrity findings."""
    module = _optional_module("graph_assurance")
    if module is None:
        raise HTTPException(status_code=404, detail="Graph assurance is unavailable")
    try:
        return module.invariant_scan()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Graph assurance scan unavailable") from exc


@app.get("/api/graph-assurance/evidence")
def graph_assurance_evidence(
    run_id: str = "",
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("graphs.read")),
) -> Dict[str, Any]:
    """Return bounded recovery evidence without mutation or failpoint access."""
    module = _optional_module("graph_assurance")
    if module is None:
        raise HTTPException(status_code=404, detail="Graph assurance is unavailable")
    try:
        items = module.list_evidence(run_id=run_id or None, limit=max(1, min(int(limit), 500)))
        return {"items": items, "count": len(items), "read_only": True}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Graph assurance evidence unavailable") from exc


@app.get("/api/native-manifests")
def native_manifests(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        items = native_agent_api.list_manifests(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Native Skill and Tool manifests are unavailable") from exc


@app.get("/api/native-agents")
def native_agents(
    limit: int = 100,
    page_size: int = 0,
    cursor: str = "",
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        if page_size:
            return native_agent_api.list_native_agents_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor,
            )
        items = native_agent_api.list_native_agents(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Native Agent inventory is unavailable") from exc


@app.get("/api/tasks")
def task_inventory(
    limit: int = 100, page_size: int = 0, cursor: str = "", agent_id: str = "", status: str = "",
    session: Dict[str, Any] = Depends(require_action("tasks.read")),
) -> Dict[str, Any]:
    """Keep legacy plans while exposing a bounded v4.4.1 inventory page."""
    try:
        if page_size:
            result = task_plan_api.list_plans_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor,
                agent_id=agent_id or None, status=status or None,
            )
            result["plans"] = result["items"]
            return result
        items = task_plan_api.list_plans(agent_id=agent_id or None, status=status or None, limit=max(1, min(limit, 500)))
        return {"items": items, "plans": items, "count": len(items)}
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Task cursor is invalid") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Task inventory is unavailable") from exc


@app.get("/api/knowledge/inventory")
def knowledge_inventory(
    limit: int = 100, page_size: int = 0, cursor: str = "", domain: str = "", topic: str = "",
    keyword: str = "", difficulty: str = "", workspace_id: str = "", isolation_mode: str = "",
    session: Dict[str, Any] = Depends(require_action("knowledge.read")),
) -> Dict[str, Any]:
    try:
        if page_size:
            result = knowledge_api.search_knowledge_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor, domain=domain or None,
                topic=topic or None, keyword=keyword or None, difficulty=difficulty or None,
                workspace_id=workspace_id or None, isolation_mode=isolation_mode or None,
            )
            result["knowledge"] = result["items"]
            return result
        items = knowledge_api.search_knowledge(
            domain=domain or None, topic=topic or None, keyword=keyword or None,
            difficulty=difficulty or None, workspace_id=workspace_id or None,
            isolation_mode=isolation_mode or None, limit=max(1, min(limit, 500)),
            principal_id=str(session["principal_id"]),
        )
        return {"items": items, "knowledge": items, "count": len(items)}
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Knowledge cursor is invalid") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Knowledge inventory is unavailable") from exc


@app.get("/api/knowledge/{entity_id}/access-policy")
def knowledge_access_policy(entity_id: str, session: Dict[str, Any] = Depends(require_action("knowledge.read"))) -> Dict[str, Any]:
    try:
        return {"policy": knowledge_api.get_access_policy(entity_id)}
    except Exception as exc:
        raise _identity_http_error(exc, "Knowledge access policy is unavailable") from exc


@app.get("/api/knowledge/access-options")
def knowledge_access_options(limit: int = 500, session: Dict[str, Any] = Depends(require_action("knowledge.read"))) -> Dict[str, Any]:
    """Return organization targets visible to the actor for knowledge grouping."""
    try:
        rows = organization_api.list_options(str(session["principal_id"]), limit=max(1, min(limit, 500)))
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        raise _identity_http_error(exc, "Knowledge access options are unavailable") from exc


@app.get("/api/knowledge/organization-groups/{organization_id}")
def knowledge_organization_group(organization_id: str, limit: int = 100, session: Dict[str, Any] = Depends(require_action("knowledge.read"))) -> Dict[str, Any]:
    try:
        rows = knowledge_api.list_organization_policies(organization_id, limit=limit)
        return {"organization_id": organization_id, "knowledge": rows, "count": len(rows)}
    except Exception as exc:
        raise _identity_http_error(exc, "Organization knowledge group is unavailable") from exc


@app.put("/api/knowledge/{entity_id}/access-policy")
def update_knowledge_access_policy(entity_id: str, body: Dict[str, Any], session: Dict[str, Any] = Depends(require_action("knowledge.write"))) -> Dict[str, Any]:
    try:
        policy = knowledge_api.set_access_policy(
            entity_id, str(body.get("scope_type") or ""), str(session["principal_id"]),
            organization_id=body.get("organization_id"), principal_id=body.get("principal_id"),
            hierarchy_depth=body.get("hierarchy_depth"), reason=str(body.get("reason") or ""),
        )
        return {"policy": policy}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Knowledge access policy update failed") from exc


@app.get("/api/knowledge")
def knowledge_graph(
    limit: int = 100,
    domain: str = "",
    topic: str = "",
    keyword: str = "",
    difficulty: str = "",
    workspace_id: str = "",
    isolation_mode: str = "",
    session: Dict[str, Any] = Depends(require_action("knowledge.read")),
) -> Dict[str, Any]:
    """Return a principal-filtered Knowledge graph projection."""
    actor = str(session["principal_id"])
    amount = max(1, min(int(limit), 200))
    try:
        items = knowledge_api.search_knowledge(
            domain=domain or None, topic=topic or None, keyword=keyword or None,
            difficulty=difficulty or None, workspace_id=workspace_id or None,
            isolation_mode=isolation_mode or None, limit=amount, principal_id=actor,
        )
        by_id = {str(item.get("entity_id")): item for item in items if item.get("entity_id")}
        nodes = [{
            "id": entity_id,
            "label": str(item.get("title") or item.get("summary") or entity_id),
            "title": str(item.get("title") or item.get("summary") or entity_id),
            "entity_type": "KNOWLEDGE",
            "status": item.get("status"),
        } for entity_id, item in by_id.items()]
        edges: Dict[str, Dict[str, Any]] = {}
        for entity_id in by_id:
            for edge in knowledge_api.get_edges(entity_id):
                source = str(edge.get("source_id") or "")
                target = str(edge.get("target_id") or "")
                if source not in by_id or target not in by_id:
                    continue
                edge_id = str(edge.get("edge_id") or f"{source}:{target}:{edge.get('edge_type') or 'RELATED'}")
                edges[edge_id] = {
                    "id": edge_id, "from": source, "to": target,
                    "label": str(edge.get("edge_type") or "RELATED"),
                    "strength": edge.get("strength"), "confidence": edge.get("confidence"),
                }
            context = knowledge_api.get_knowledge_context(entity_id)
            if context:
                chain = context.get("organization_chain") or []
                for org in chain:
                    org_id = str(org.get("organization_id") or "")
                    if not org_id:
                        continue
                    nodes.append({"id": org_id, "label": str(org.get("organization_name") or org_id),
                                  "title": "Organization scope", "entity_type": "ORGANIZATION", "status": "ACTIVE"})
                    edge_id = f"{entity_id}:ORGANIZATION_SCOPE:{org_id}"
                    edges[edge_id] = {"id": edge_id, "from": entity_id, "to": org_id,
                                      "label": "ORGANIZATION_SCOPE", "strength": 1, "confidence": 1}
                for group in [*(context.get("responsible_groups") or []), *(context.get("execution_groups") or [])]:
                    group_id = str(group.get("group_id") or "")
                    if not group_id:
                        continue
                    nodes.append({"id": group_id, "label": str(group.get("group_name") or group_id),
                                  "title": "Agent group context", "entity_type": "GROUP", "status": "ACTIVE"})
                    edge_id = f"{entity_id}:GROUP_CONTEXT:{group_id}"
                    edges[edge_id] = {"id": edge_id, "from": entity_id, "to": group_id,
                                      "label": "GROUP_CONTEXT", "strength": 1, "confidence": 1}
        unique_nodes = {str(node["id"]): node for node in nodes}
        return {"nodes": list(unique_nodes.values()), "edges": list(edges.values()), "count": len(unique_nodes)}
    except Exception as exc:
        raise _identity_http_error(exc, "Knowledge graph is unavailable") from exc


@app.get("/api/memory/inventory")
def memory_inventory(
    page_size: int = 20, cursor: str = "", keyword: str = "", memory_type: str = "",
    memory_scope: str = "", lifecycle_state: str = "", workspace_id: str = "", owner_agent_id: str = "",
    session: Dict[str, Any] = Depends(require_action("memory.read")),
) -> Dict[str, Any]:
    """A page-only inventory route; /api/memory remains the legacy graph projection."""
    try:
        result = memory_lifecycle.current_memories_cursor(
            str(session["principal_id"]), page_size=page_size, cursor=cursor, keyword=keyword or None,
            memory_type=memory_type or None, memory_scope=memory_scope or None,
            lifecycle_state=lifecycle_state or None, workspace_id=workspace_id or None,
            owner_agent_id=owner_agent_id or None,
        )
        result["memories"] = result["items"]
        return result
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Memory cursor is invalid") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Memory inventory is unavailable") from exc


@app.get("/api/skills")
def skill_inventory(
    limit: int = 100, page_size: int = 0, cursor: str = "", skill_type: str = "", runtime: str = "",
    skill_status: str = "ACTIVE", session: Dict[str, Any] = Depends(require_action("skills.read")),
) -> Dict[str, Any]:
    try:
        if page_size:
            result = skill_api.list_skills_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor,
                skill_type=skill_type or None, runtime=runtime or None, skill_status=skill_status,
            )
            result["skills"] = result["items"]
            return result
        items = skill_api.list_skills(skill_type=skill_type or None, runtime=runtime or None,
                                      skill_status=skill_status, limit=max(1, min(limit, 500)))
        return {"items": items, "skills": items, "count": len(items)}
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Skill cursor is invalid") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Skill inventory is unavailable") from exc


@app.get("/api/specs")
def spec_inventory(
    limit: int = 100, page_size: int = 0, cursor: str = "", spec_scope: str = "", spec_status: str = "",
    session: Dict[str, Any] = Depends(require_action("specs.read")),
) -> Dict[str, Any]:
    try:
        if page_size:
            result = spec_api.list_specs_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor,
                spec_scope=spec_scope or None, spec_status=spec_status or None,
            )
            result["specs"] = result["items"]
            return result
        items = spec_api.list_specs(spec_scope=spec_scope or None, spec_status=spec_status or None,
                                    limit=max(1, min(limit, 500)))
        return {"items": items, "specs": items, "count": len(items)}
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Spec cursor is invalid") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Spec inventory is unavailable") from exc


@app.post("/api/native-agents/{agent_id}/activate")
def native_agent_activate(
    agent_id: str,
    body: NativeAgentActivationBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.activate_agent(
            str(session["principal_id"]), agent_id, body.llm_profile_id, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Native Agent activation was denied") from exc


@app.post("/api/native-agents/{agent_id}/execute")
def native_agent_execute(
    agent_id: str,
    body: NativeAgentExecuteBody,
    session: Dict[str, Any] = Depends(require_action("agents.operate")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.create_execution(
            str(session["principal_id"]), agent_id, body.messages, body.reason,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Native Agent execution could not be queued") from exc


@app.get("/api/native-executions/{execution_id}")
def native_execution(
    execution_id: str,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        return native_runtime.get_execution(str(session["principal_id"]), execution_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Native Agent execution is unavailable") from exc


@app.get("/api/llm-provider-profiles")
def llm_provider_profiles(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = native_agent_api.list_llm_profiles(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "LLM Provider Profiles are unavailable") from exc


def model_forward_authorization(request: Request) -> Dict[str, Any]:
    authorization = request.headers.get("Authorization", "")
    raw_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if raw_token.startswith("cxgw_"):
        return {"actor": "", "gateway_token": raw_token}
    session = require_csrf(request, principal(request))
    try:
        with _schema_owner_context():
            access = identity_api.effective_access(str(session["principal_id"]), "model_gateway.forward")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc
    if access.get("decision") != "ALLOW":
        raise HTTPException(status_code=403, detail="Model gateway forwarding permission is required")
    return {"actor": str(session["principal_id"]), "gateway_token": ""}


@app.post("/api/model-gateway/completions")
def model_gateway_completion(request: Request, body: ModelForwardBody, authorization: Dict[str, Any] = Depends(model_forward_authorization)) -> Dict[str, Any]:
    try:
        if body.stream:
            return StreamingResponse(model_usage_api.stream_forward(str(authorization["actor"]), body.provider_profile_id, body.messages, agent_id=body.agent_id, idempotency_key=body.idempotency_key, gateway_token=str(authorization["gateway_token"]), correlation_id=_correlation_id(request)), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Correlation-ID": _correlation_id(request)})
        return model_usage_api.forward(str(authorization["actor"]), body.provider_profile_id, body.messages, agent_id=body.agent_id, stream=body.stream, idempotency_key=body.idempotency_key, gateway_token=str(authorization["gateway_token"]), correlation_id=_correlation_id(request))
    except PermissionError as exc:
        raise HTTPException(status_code=401 if authorization.get("gateway_token") else 403, detail=str(exc)) from exc
    except model_usage_api.ModelUsageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except model_usage_api.ModelUsageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except model_governance_api.QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc
    except model_governance_api.ReplayUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Model gateway request failed", identity_status=503) from exc


@app.get("/api/model-usage/summary")
def model_usage_summary(limit: int = 30, session: Dict[str, Any] = Depends(require_action("model_usage.read"))) -> Dict[str, Any]:
    try:
        return model_usage_api.usage_summary(str(session["principal_id"]), limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Model usage is unavailable", identity_status=503) from exc


@app.post("/api/model-gateway/credentials")
def model_gateway_credential(body: GatewayCredentialBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return model_usage_api.issue_gateway_credential(str(session["principal_id"]), body.display_name, body.scopes, body.expires_at)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Gateway credential could not be issued") from exc


@app.post("/api/model-gateway/credentials/{credential_id}/revoke")
def model_gateway_credential_revoke(credential_id: str, body: GatewayRevokeBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return model_usage_api.revoke_gateway_credential(str(session["principal_id"]), credential_id, body.reason)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Gateway credential could not be revoked") from exc


def _gateway_distribution_url(request: Request) -> str:
    base = str(os.environ.get("CX_PUBLIC_BASE_URL") or request.base_url).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("platform public URL must use http or https")
    return base + "/api/model-gateway/completions"


@app.get("/api/model-gateway/routing")
def model_gateway_routing(request: Request, agent_id: str = "", profile_id: str = "", session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        result = model_usage_api.routing_policy(str(session["principal_id"]), agent_id, profile_id)
        result["gateway_url"] = _gateway_distribution_url(request)
        return result
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc: raise _identity_http_error(exc, "Model routing policy is unavailable") from exc


@app.put("/api/model-gateway/routing")
def model_gateway_routing_update(body: ModelRoutingPolicyBody, request: Request, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try: return model_usage_api.set_routing_policy(str(session["principal_id"]), body.agent_id, body.profile_id, body.gateway_enabled, body.direct_allowed, body.reason, _gateway_distribution_url(request))
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc: raise _identity_http_error(exc, "Model routing policy could not be saved") from exc


@app.get("/api/model-gateway/quotas")
def model_quota_list(limit: int = 100, session: Dict[str, Any] = Depends(require_action("model_gateway.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.list_quota_policies(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "Model quota policies are unavailable") from exc


@app.post("/api/model-gateway/quotas")
def model_quota_create(body: ModelQuotaPolicyBody, session: Dict[str, Any] = Depends(require_action("model_gateway.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.create_quota_policy(str(session["principal_id"]), body.model_dump())
    except Exception as exc:
        raise _identity_http_error(exc, "Model quota policy could not be created") from exc


@app.get("/api/model-gateway/quota-status")
def model_quota_status(limit: int = 100, session: Dict[str, Any] = Depends(require_action("model_gateway.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.quota_status(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "Model quota status is unavailable") from exc


@app.get("/api/model-finance/invoices")
def model_invoice_list(limit: int = 100, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.list_invoices(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "Provider invoices are unavailable") from exc


@app.get("/api/model-finance/overview")
def model_finance_overview(limit: int = 100, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.financial_overview(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "Model financial accounting is unavailable") from exc


@app.post("/api/model-finance/invoices")
def model_invoice_import(body: ProviderInvoiceBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.import_invoice(str(session["principal_id"]), body.model_dump())
    except Exception as exc:
        raise _identity_http_error(exc, "Provider invoice could not be imported") from exc


@app.post("/api/model-finance/invoice-lines/{line_id}/reconcile")
def model_invoice_reconcile(line_id: str, body: ReconciliationBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.reconcile_invoice_line(str(session["principal_id"]), line_id, body.usage_id, body.rule_version, body.confidence, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Provider invoice line could not be reconciled") from exc


@app.post("/api/model-finance/invoice-lines/{line_id}/corrections")
def model_invoice_correct(line_id: str, body: InvoiceCorrectionBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.correct_invoice_line(str(session["principal_id"]), line_id, body.amount_delta, body.prior_correction_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Provider invoice correction could not be appended") from exc


@app.post("/api/model-finance/allocation-rules")
def model_allocation_rule_create(body: AllocationRuleBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.create_allocation_rule(str(session["principal_id"]), body.model_dump())
    except Exception as exc:
        raise _identity_http_error(exc, "Allocation rule could not be created") from exc


@app.post("/api/model-finance/{source_type}/{source_id}/allocate")
def model_allocate(source_type: str, source_id: str, body: AllocationRequestBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.allocate_source(str(session["principal_id"]), source_type, source_id, body.rule_key)
    except Exception as exc:
        raise _identity_http_error(exc, "Internal allocation could not be completed") from exc


@app.post("/api/model-evidence/adapters")
def model_evidence_adapter_create(body: EvidenceAdapterBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.register_evidence_adapter(str(session["principal_id"]), body.model_dump())
    except Exception as exc:
        raise _identity_http_error(exc, "External evidence adapter could not be registered") from exc


@app.get("/api/model-evidence/adapters")
def model_evidence_adapter_list(limit: int = 100, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.list_evidence_adapters(str(session["principal_id"]), limit)
    except Exception as exc:
        raise _identity_http_error(exc, "External evidence adapters are unavailable") from exc


@app.post("/api/model-evidence/adapters/{adapter_id}/revoke")
def model_evidence_adapter_revoke(adapter_id: str, body: GovernedReasonBody, session: Dict[str, Any] = Depends(require_action("model_usage.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.revoke_evidence_adapter(str(session["principal_id"]), adapter_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "External evidence adapter could not be revoked") from exc


@app.post("/api/model-evidence/ingest")
def model_evidence_ingest(request: Request, body: ExternalEvidenceBody) -> Dict[str, Any]:
    try:
        return model_governance_api.ingest_external_evidence(body.model_dump(), _correlation_id(request))
    except model_governance_api.EvidenceRejected as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "External model evidence could not be ingested") from exc


@app.get("/api/model-evidence/coverage")
def model_evidence_coverage(session: Dict[str, Any] = Depends(require_action("model_usage.read"))) -> Dict[str, Any]:
    try:
        return model_governance_api.external_coverage(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "External model evidence coverage is unavailable") from exc


@app.get("/api/wallboard/definitions")
def wallboard_definition_list(session: Dict[str, Any] = Depends(require_action("wallboard.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.list_wallboard_definitions(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "Wallboard definitions are unavailable") from exc


@app.post("/api/wallboard/definitions")
def wallboard_definition_create(body: WallboardDefinitionBody, session: Dict[str, Any] = Depends(require_action("wallboard.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.create_wallboard_definition(str(session["principal_id"]), body.definition_id, body.display_name, body.config, body.scope, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Wallboard definition could not be created") from exc


@app.post("/api/wallboard/definitions/{version_id}/publish")
def wallboard_definition_publish(version_id: str, body: GovernedReasonBody, session: Dict[str, Any] = Depends(require_action("wallboard.manage"))) -> Dict[str, Any]:
    try:
        return model_governance_api.publish_wallboard_definition(str(session["principal_id"]), version_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Wallboard definition could not be published") from exc


@app.post("/api/wallboard/definitions/{version_id}/rollback")
def wallboard_definition_rollback(version_id: str, body: GovernedReasonBody, session: Dict[str, Any] = Depends(require_action("wallboard.manage"))) -> Dict[str, Any]:
    try:
        result = model_governance_api.publish_wallboard_definition(str(session["principal_id"]), version_id, body.reason)
        result["operation"] = "ROLLBACK"
        return result
    except Exception as exc:
        raise _identity_http_error(exc, "Wallboard definition could not be rolled back") from exc


@app.get("/api/wallboard")
def executive_wallboard(definition_id: str = "", session: Dict[str, Any] = Depends(require_action("wallboard.read"))) -> Dict[str, Any]:
    try:
        return model_usage_api.wallboard(str(session["principal_id"]), definition_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Executive wallboard is unavailable", identity_status=503) from exc


@app.post("/api/llm-provider-profiles")
def llm_provider_profile(
    body: LLMProviderProfileBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.upsert_llm_profile(
            str(session["principal_id"]), body.profile_key, body.provider_url,
            body.model_id, body.api_key, body.reason, body.approved_for,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "LLM Provider Profile could not be saved") from exc


@app.post("/api/llm-provider-profiles/probe-draft")
def llm_provider_profile_probe(
    body: LLMProviderProfileProbeBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.probe_llm_profile(
            str(session["principal_id"]), body.profile_key, body.provider_url,
            body.model_id, body.api_key,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "LLM Provider draft probe failed", identity_status=503) from exc


@app.post("/api/llm-provider-profiles/{profile_id}/probe")
def llm_provider_profile_saved_probe(
    profile_id: str,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.probe_saved_llm_profile(str(session["principal_id"]), profile_id)
    except native_agent_api.NativeAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="platform management permission is required") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "LLM Provider Profile probe failed", identity_status=503) from exc


@app.delete("/api/llm-provider-profiles/{profile_id}")
def llm_provider_profile_retire(profile_id: str, body: RetirementBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return native_agent_api.retire_llm_profile(str(session["principal_id"]), profile_id, body.reason)
    except native_agent_api.LLMProfileInUse as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except native_agent_api.NativeAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "LLM Provider Profile could not be retired") from exc


@app.get("/api/platform/portal-llm-policy")
def portal_llm_policy(session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.list_portal_llm_policy(str(session["principal_id"]))
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/platform/portal-llm-policy")
def portal_llm_policy_update(body: PortalLLMPolicyBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.set_portal_llm_policy(str(session["principal_id"]), body.default_profile_id, body.allowed_profile_ids, body.reason, body.expected_version)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/admin-commands")
def platform_admin_commands(limit: int = 50, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_commands(str(session["principal_id"]), limit)}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/admin-commands/catalog")
def platform_admin_command_catalog(
    channel_id: str = "CH_PLATFORM_ADMINISTRATION",
    query: str = "",
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return platform_agent_pool.list_command_catalog(str(session["principal_id"]), channel_id, query)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-commands/help")
def platform_admin_command_help(
    body: PlatformCommandHelpBody,
    channel_id: str = "CH_PLATFORM_ADMINISTRATION",
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return platform_agent_pool.command_help(str(session["principal_id"]), body.command_key, channel_id)
    except platform_agent_pool.AgentPoolError as exc:
        message = str(exc)
        status = 404 if message == "UNKNOWN_PLATFORM_COMMAND" else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Platform command help denied") from exc


@app.get("/api/platform/governance-graph")
def platform_governance_graph(
    refresh_interval_seconds: int = 3,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return governance_graph_module.governance_projection(
            str(session["principal_id"]), refresh_interval_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Platform governance graph denied") from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Platform governance graph is unavailable", identity_status=503) from exc


@app.get("/api/collaboration-groups/{group_id}/legacy-messages")
def legacy_collaboration_messages(group_id: str, channel_id: str = "", limit: int = 100, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = security_domain_api.list_legacy_collaboration_messages(
            str(session["principal_id"]), group_id, channel_id=channel_id, limit=limit,
        )
        return {"items": items, "count": len(items), "deprecated": True, "contract": "legacy-collaboration-read/v1"}
    except Exception as exc:
        raise _identity_http_error(exc, "Legacy collaboration messages are unavailable", identity_status=503) from exc


@app.post("/api/platform/admin-commands")
def platform_admin_command(body: PlatformAdminCommandBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.create_command(str(session["principal_id"]), body.command_type, body.target, body.parameters, body.security_domain_id, body.reason, body.expires_seconds)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/admin-commands/{command_id}/execute")
def platform_admin_command_execute(command_id: str, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"command_id": command_id, "status": "COMPLETED", "result": platform_agent_pool.execute_read_command(str(session["principal_id"]), command_id)}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/managed-nodes")
def managed_nodes(limit: int = 100, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_nodes(str(session["principal_id"]), limit)}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/managed-nodes")
def managed_node(body: ManagedNodeBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.register_node(str(session["principal_id"]), body.model_dump())
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/managed-nodes/{node_id}/validate")
def managed_node_validate(node_id: str, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.validate_node(str(session["principal_id"]), node_id)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/runtime-hosts")
def runtime_hosts(session: Dict[str, Any] = Depends(require_action("hosts.read"))) -> Dict[str, Any]:
    try:
        return {"items": host_provisioning.list_runtime_hosts(str(session["principal_id"]))}
    except (host_provisioning.HostProvisioningError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/managed-nodes/{node_id}/runtime-preflight")
def runtime_host_preflight(node_id: str, body: RuntimeHostPreflightBody,
                           session: Dict[str, Any] = Depends(require_action("hosts.manage"))) -> Dict[str, Any]:
    try:
        return host_provisioning.record_preflight(
            str(session["principal_id"]), node_id, body.evidence, body.reason)
    except (host_provisioning.HostProvisioningError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/managed-nodes/{node_id}/complete-runtime-bootstrap")
def runtime_host_bootstrap(node_id: str, body: RuntimeHostBootstrapBody,
                           session: Dict[str, Any] = Depends(require_action("hosts.manage"))) -> Dict[str, Any]:
    try:
        return host_provisioning.complete_bootstrap(
            str(session["principal_id"]), node_id,
            host_manager_version=body.host_manager_version,
            recovery_channel=body.recovery_channel,
            root_remote_login=body.root_remote_login,
            uid_min=body.uid_min, uid_max=body.uid_max, reason=body.reason)
    except (host_provisioning.HostProvisioningError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/runtime-identity-leases")
def runtime_identity_allocate(body: RuntimeIdentityLeaseBody,
                              session: Dict[str, Any] = Depends(require_action("hosts.manage"))) -> Dict[str, Any]:
    try:
        return host_provisioning.allocate_identity(
            str(session["principal_id"]), body.node_id, body.agent_id,
            body.instance_id, body.reason)
    except (host_provisioning.HostProvisioningError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/platform/runtime-identity-leases/{lease_id}")
def runtime_identity_release(lease_id: str, body: RetirementBody,
                             session: Dict[str, Any] = Depends(require_action("hosts.manage"))) -> Dict[str, Any]:
    try:
        return host_provisioning.release_identity(
            str(session["principal_id"]), lease_id, body.reason)
    except (host_provisioning.HostProvisioningError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/platform/managed-nodes/{node_id}")
def managed_node_retire(node_id: str, body: RetirementBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.retire_node(str(session["principal_id"]), node_id, body.reason)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/agent-pool/onboardings")
def agent_pool_node_onboardings(limit: int = 100, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_node_onboardings(str(session["principal_id"]), limit)}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/agent-pool/onboardings")
def agent_pool_node_onboarding_create(body: AgentPoolNodeOnboardingBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.create_node_onboarding(str(session["principal_id"]), body.node_id, body.reason, body.expires_seconds)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/agent-pool/onboardings/{onboarding_id}/activate")
def agent_pool_node_onboarding_activate(onboarding_id: str, body: AgentPoolNodeActivationBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.activate_node_onboarding(str(session["principal_id"]), onboarding_id, body.reason)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent-pool/node-onboardings/{onboarding_id}/check-in")
def agent_pool_node_onboarding_checkin(onboarding_id: str, body: AgentPoolNodeCheckinBody) -> Dict[str, Any]:
    try:
        return platform_agent_pool.node_onboarding_checkin(
            onboarding_id, body.token, body.runtime_version, body.hostname,
            body.shared_path, body.agent_info_path,
            runtime_preflight=body.runtime_preflight,
            lifecycle_passed=body.lifecycle_passed,
            root_remote_login=body.root_remote_login,
            recovery_channel=body.recovery_channel,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Agent Pool node check-in was rejected") from exc
    except platform_agent_pool.AgentPoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent-pool/node-onboardings/{onboarding_id}/heartbeat")
def agent_pool_node_onboarding_heartbeat(onboarding_id: str, body: AgentPoolNodeHeartbeatBody) -> Dict[str, Any]:
    try:
        return platform_agent_pool.node_onboarding_heartbeat(onboarding_id, body.token, body.runtime_version)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Agent Pool node heartbeat was rejected") from exc
    except platform_agent_pool.AgentPoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/shared-storage")
def shared_storage(session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_storage(str(session["principal_id"]))}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/shared-storage")
def shared_storage_create(body: SharedStorageBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.register_storage(str(session["principal_id"]), body.model_dump())
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/shared-storage/{storage_id}/validate")
def shared_storage_validate(storage_id: str, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.validate_storage(str(session["principal_id"]), storage_id)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/node-storage-bindings")
def node_storage_bindings(session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_node_storage_bindings(str(session["principal_id"]))}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/node-storage-bindings")
def node_storage_binding_create(body: NodeStorageBindingBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.bind_node_storage(str(session["principal_id"]), body.model_dump())
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/node-storage-bindings/{binding_id}/remove")
def node_storage_binding_remove(binding_id: str, body: Dict[str, Any], session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.remove_node_storage_binding(str(session["principal_id"]), binding_id, str(body.get("reason") or ""))
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/external-db-endpoints")
def external_db_endpoints(session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return {"items": platform_agent_pool.list_endpoints(str(session["principal_id"]))}
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/platform/external-db-endpoints")
def external_db_endpoint(body: ExternalEndpointBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.register_endpoint(str(session["principal_id"]), body.model_dump())
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/platform/external-db-endpoints/{endpoint_id}")
def external_db_endpoint_update(endpoint_id: str, body: ExternalEndpointUpdateBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.update_endpoint(str(session["principal_id"]), endpoint_id, body.model_dump())
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/platform/external-db-endpoints/{endpoint_id}")
def external_db_endpoint_retire(endpoint_id: str, body: RetirementBody, session: Dict[str, Any] = Depends(require_action("platform.manage"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.retire_endpoint(str(session["principal_id"]), endpoint_id, body.reason)
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/platform/portal-enhancements")
def portal_enhancements(session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        return platform_agent_pool.list_enhancements(str(session["principal_id"]))
    except (platform_agent_pool.AgentPoolError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/deployment-runs")
def deployment_runs(
    limit: int = 50,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        amount = max(1, min(int(limit), 500))
        suffix = " LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST :limit ROWS ONLY"
        rows = connection.execute_query(
            "SELECT RUN_ID,RUN_MODE,DATABASE_DIALECT,EDITION,PACKAGE_VERSION,STATUS,READINESS_JSON,"
            "DEPLOYMENT_AGENT_ID,CURRENT_STEP,FAILURE_CODE,FAILURE_DETAIL,CREATED_AT,UPDATED_AT,COMPLETED_AT "
            "FROM CX_DEPLOYMENT_RUNS ORDER BY CREATED_AT DESC" + suffix, {"limit": amount},
        )
        items = []
        for row in rows:
            item = {str(key).lower(): value for key, value in dict(row).items()}
            try:
                item["readiness"] = json.loads(str(item.pop("readiness_json", "{}") or "{}"))
            except ValueError:
                item["readiness"] = {}
            items.append(item)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Deployment evidence is unavailable") from exc


@app.get("/api/embedding/readiness")
def embedding_readiness(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return {"readiness": embedding_governance.readiness(), "queue": embedding_governance.queue_metrics()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Contract readiness is unavailable") from exc


@app.get("/api/embedding/profiles")
def embedding_profiles(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_profiles(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Profiles are unavailable") from exc


# Deliberately not mounted as a public Dashboard/API operation. The standard
# workflow uses probe-draft followed by platform/activate; the function is
# retained for controlled migration code that imports this module directly.
def embedding_profile(
    body: EmbeddingProfileBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.upsert_profile(
            str(session["principal_id"]), profile_key=body.profile_key, provider_url=body.provider_url,
            model_id=body.model_id, execution_mode=body.execution_mode, dimension=body.dimension,
            distance_metric=body.distance_metric, normalize_vectors=body.normalize_vectors,
            preprocessing=body.preprocessing, modalities=body.modalities, api_key=body.api_key,
            secret_reference=body.secret_reference, model_fingerprint=body.model_fingerprint,
            expected_version=body.expected_version, reason=body.reason,
        )
    except embedding_governance.EmbeddingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Profile could not be saved") from exc


@app.post("/api/embedding/platform/activate")
def embedding_platform_activate(
    body: EmbeddingActivationBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.activate_platform_embedding(
            str(session["principal_id"]), profile_key=body.profile_key,
            provider_url=body.provider_url, model_id=body.model_id,
            execution_mode=body.execution_mode, dimension=body.dimension,
            distance_metric=body.distance_metric, api_key=body.api_key,
            secret_reference=body.secret_reference, reason=body.reason,
            model_fingerprint=body.model_fingerprint,
        )
    except embedding_governance.EmbeddingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Platform Embedding activation failed")
        raise HTTPException(status_code=503, detail="Platform Embedding activation failed") from exc


@app.post("/api/embedding/profiles/probe-draft")
def embedding_profile_draft_probe(
    body: EmbeddingProfileBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.probe_draft(
            str(session["principal_id"]), profile_key=body.profile_key,
            provider_url=body.provider_url, model_id=body.model_id,
            execution_mode=body.execution_mode, dimension=body.dimension,
            distance_metric=body.distance_metric, normalize_vectors=body.normalize_vectors,
            api_key=body.api_key, secret_reference=body.secret_reference,
            reason=body.reason,
        )
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding draft probe failed") from exc


@app.get("/api/embedding/contracts")
def embedding_contracts(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_contracts(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Contracts are unavailable") from exc


def embedding_contract(
    body: EmbeddingContractBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.create_contract(
            str(session["principal_id"]), body.profile_id, body.reason,
            model_fingerprint=body.model_fingerprint,
        )
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Contract could not be created") from exc


@app.get("/api/embedding/spaces")
def embedding_spaces(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_spaces(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Spaces are unavailable") from exc


def embedding_space(
    body: EmbeddingSpaceBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.create_space(
            str(session["principal_id"]), body.space_key, body.contract_id, body.reason,
            default=body.default, writable=body.writable, physical_ref=body.physical_ref,
        )
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Space could not be created") from exc


@app.get("/api/embedding/bindings")
def embedding_bindings(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_bindings(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding bindings are unavailable") from exc


def embedding_binding(
    body: EmbeddingBindingBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.bind(
            str(session["principal_id"]), body.binding_scope, body.binding_subject_id,
            body.profile_id, body.space_id, body.reason, body.expected_version,
        )
    except embedding_governance.EmbeddingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding binding could not be saved") from exc


@app.post("/api/embedding/profiles/{profile_id}/probe")
def embedding_probe(
    profile_id: str,
    body: EmbeddingProbeBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.probe_profile(str(session["principal_id"]), profile_id, scope=body.scope, timeout=body.timeout)
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding probe failed") from exc


@app.post("/api/gateway/embedding/profiles/{profile_id}/probe")
@app.post("/api/agent-gateway/embedding/profiles/{profile_id}/probe")
@_gateway_request_context
def gateway_embedding_probe(profile_id: str, body: AgentEmbeddingProbeBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, "embedding.probe", operation="embedding.probe",
        attach_agent_database_context=False,
    )
    try:
        return embedding_governance.record_agent_probe(
            str(context["agent_id"]), profile_id, observed_dimension=body.observed_dimension,
            observed_model=body.observed_model, response_digest=body.response_digest,
            model_fingerprint=body.model_fingerprint,
        )
    except embedding_governance.EmbeddingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent-side Embedding probe failed") from exc


@app.post("/api/gateway/v1/embeddings")
@app.post("/api/agent-gateway/v1/embeddings")
@_gateway_request_context
def gateway_embeddings(request: Request, body: EmbeddingGatewayBody) -> Dict[str, Any]:
    context = _gateway_context(
        request, "embedding.generate", operation="embedding.generate",
        attach_agent_database_context=False,
    )
    try:
        return embedding_governance.gateway_embeddings(
            str(context["agent_id"]), body.input, requested_model=body.model,
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            correlation_id=_correlation_id(request),
        )
    except embedding_governance.EmbeddingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except model_usage_api.ModelUsageConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except model_governance_api.QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc), "retryable": False}) from exc
    except Exception as exc:
        logger.exception("Agent Embedding gateway request failed")
        raise HTTPException(status_code=503, detail="Agent Embedding gateway request failed") from exc


@app.get("/api/embedding/access-grants")
def embedding_access_grants(
    limit: int = 200,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_access_grants(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding access grants are unavailable") from exc


@app.post("/api/embedding/access-grants")
def embedding_access_grant_create(
    body: EmbeddingAccessGrantBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.upsert_access_grant(
            str(session["principal_id"]), subject_type=body.subject_type, subject_id=body.subject_id,
            effect=body.effect, allowed_profile_id=body.allowed_profile_id,
            max_batch_size=body.max_batch_size, max_input_chars=body.max_input_chars,
            valid_from=body.valid_from, valid_until=body.valid_until, reason=body.reason,
        )
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding access grant could not be saved") from exc


@app.delete("/api/embedding/access-grants/{grant_id}")
def embedding_access_grant_revoke(
    grant_id: str, body: GovernedReasonBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.revoke_access_grant(str(session["principal_id"]), grant_id, body.reason)
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding access grant could not be revoked") from exc


@app.get("/api/embedding/jobs")
def embedding_jobs(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        items = embedding_governance.list_jobs(limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding jobs are unavailable") from exc


def embedding_job(
    body: EmbeddingJobBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return embedding_governance.enqueue_job(
            str(session["principal_id"]), job_kind=body.job_kind, target_space_id=body.target_space_id,
            source_space_id=body.source_space_id, input_data=body.input_data,
            idempotency_key=body.idempotency_key, reason=body.reason,
        )
    except embedding_governance.EmbeddingGovernanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Embedding Job could not be queued") from exc


@app.get("/api/platform/external-agent-registration")
def external_agent_registration_policy(
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.external_registration_policy()
    except Exception as exc:
        raise _identity_http_error(exc, "External Agent registration policy is unavailable") from exc


@app.put("/api/platform/external-agent-registration")
def external_agent_registration_policy_update(
    body: ExternalRegistrationPolicyBody,
    session: Dict[str, Any] = Depends(require_action("platform.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.set_external_registration_policy(
            str(session["principal_id"]), body.state, body.reason, body.expected_version,
        )
    except native_agent_api.NativeAgentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "External Agent registration policy update was denied") from exc


@app.get("/api/agent-provision-requests")
def agent_provision_requests(
    limit: int = 100,
    session: Dict[str, Any] = Depends(require_action("agents.read")),
) -> Dict[str, Any]:
    try:
        items = native_agent_api.list_requests(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent provisioning requests are unavailable") from exc


@app.post("/api/agent-provision-requests")
def agent_provision_request(
    body: NativeAgentRequestBody,
    session: Dict[str, Any] = Depends(require_action("agents.enroll")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.create_request(
            str(session["principal_id"]), agent_name=body.agent_name,
            owner_principal_id=body.owner_principal_id, template_key=body.template_key,
            provider_profile_id=body.provider_profile_id,
            target_id=body.deployment_target_id, isolation_level=body.isolation_level,
            classification=body.classification, purpose=body.purpose, reason=body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Agent provisioning request was denied") from exc


@app.post("/api/agent-provision-requests/{request_id}/decision")
def agent_provision_decision(
    request_id: str,
    body: NativeAgentDecisionBody,
    session: Dict[str, Any] = Depends(require_action("agents.manage")),
) -> Dict[str, Any]:
    try:
        return native_agent_api.decide_request(
            str(session["principal_id"]), request_id, body.decision, body.reason,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except native_agent_api.NativeAgentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise _identity_http_error(exc, "Agent provisioning decision was denied") from exc


def _organization_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail="Organization permission denied")
    if isinstance(exc, organization_api.OrganizationConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, organization_api.OrganizationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail="Organization governance service unavailable")


def _organization_id(value: str) -> str:
    value = str(value or "")
    return value[4:] if value.startswith("org:") else value


def _organization_operation(value: Dict[str, Any]) -> tuple[str, str, str, Dict[str, Any], Optional[int]]:
    item = dict(value or {})
    requested = str(item.get("operation_type") or "").upper()
    if requested == "CREATE_ORGANIZATION":
        # target_id is the parent for creates and must never become the child ID.
        subject = _organization_id(str(item.get("subject_id") or item.get("organization_id") or ""))
    else:
        subject = _organization_id(str(item.get("subject_id") or item.get("organization_id") or item.get("target_id") or ""))
    target = _organization_id(str(item.get("target_id") or ""))
    expected = item.get("expected_row_version", item.get("row_version"))
    if requested == "MOVE_ORGANIZATION":
        return requested, "ORGANIZATION", subject, {"parent_id": _organization_id(str(item.get("new_parent_id") or target)) or None}, expected
    if requested == "CREATE_ORGANIZATION":
        command = {
            "organization_id": subject,
            "parent_id": target or None,
            "organization_code": str(item.get("organization_code") or item.get("name") or subject or "ORG")[:128],
            "organization_name": str(item.get("organization_name") or item.get("name") or subject or "Organization")[:256],
            "organization_type": str(item.get("organization_type") or "DEPARTMENT"),
        }
        return requested, "ORGANIZATION", "", command, expected
    if requested == "UPDATE_ORGANIZATION" and item.get("name"):
        return "RENAME_ORGANIZATION", "ORGANIZATION", subject, {"organization_name": item["name"]}, expected
    if requested == "ASSIGN_PERSON":
        membership_id = identity_api._id("OMEM")
        return "ADD_MEMBERSHIP", "MEMBERSHIP", membership_id, {
            "membership_id": membership_id, "organization_id": target,
            "principal_id": str(item.get("subject_id") or ""),
            "membership_kind": str(item.get("membership_kind") or "PRIMARY"),
            "source_type": "MANUAL",
        }, expected
    if requested == "ASSIGN_AGENT":
        relationship_id = identity_api._id("AREL")
        return "SET_AGENT_RELATIONSHIP", "AGENT_RELATIONSHIP", relationship_id, {
            "relationship_id": relationship_id, "agent_id": str(item.get("subject_id") or ""),
            "principal_id": str(item.get("principal_id") or ""),
            "relationship_role": str(item.get("relationship_role") or "PRIMARY_OWNER"),
            "responsible_organization_id": target,
        }, expected
    command = {key: item[key] for key in (
        "organization_code", "organization_type", "sort_order",
        "responsible_principal_id", "security_domain_id",
    ) if key in item}
    return requested, "ORGANIZATION", subject, command, expected


@app.get("/api/organization/roots")
def organization_roots(limit: int = 100, session: Dict[str, Any] = Depends(require_action("organizations.read"))) -> Dict[str, Any]:
    try:
        return {"roots": organization_api.list_roots(str(session["principal_id"]), limit=limit)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/options")
def organization_options(limit: int = 500, session: Dict[str, Any] = Depends(require_action("organizations.members.manage"))) -> Dict[str, Any]:
    try:
        rows = organization_api.list_options(str(session["principal_id"]), limit=limit)
        return {"items": rows, "count": len(rows)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/graph")
def organization_graph(mode: str = "organization", focus_id: str = "", depth: int = 2, limit: int = 300, session: Dict[str, Any] = Depends(require_action("organizations.read"))) -> Dict[str, Any]:
    try:
        return organization_api.organization_graph(str(session["principal_id"]), _organization_id(focus_id), mode, depth, limit)
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/search")
def organization_search(q: str, limit: int = 50, session: Dict[str, Any] = Depends(require_action("organizations.read"))) -> Dict[str, Any]:
    try:
        return {"results": organization_api.search(str(session["principal_id"]), q, limit)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/nodes/{organization_id}")
def organization_node(organization_id: str, session: Dict[str, Any] = Depends(require_action("organizations.read"))) -> Dict[str, Any]:
    try:
        return organization_api.get_detail(str(session["principal_id"]), _organization_id(organization_id))
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/changes")
def organization_changes(status: str = "", limit: int = 100, session: Dict[str, Any] = Depends(require_action("organizations.changes.write"))) -> Dict[str, Any]:
    try:
        return {"change_sets": organization_api.list_changes(str(session["principal_id"]), limit, status=status)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.post("/api/organization/changes")
def organization_change_create(body: OrganizationChangeBody, session: Dict[str, Any] = Depends(require_action("organizations.changes.create"))) -> Dict[str, Any]:
    actor = str(session["principal_id"])
    try:
        change = organization_api.create_change_set(actor, body.reason, body.idempotency_key or identity_api._id("ORGWEB"))
        change_id = str(change["change_id"])
        for item in body.operations:
            operation_type, target_type, target_id, command, expected = _organization_operation(item)
            organization_api.append_operation(actor, change_id, operation_type, target_type, target_id, command, expected)
        return {"change_set": organization_api.get_change_set(actor, change_id)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.post("/api/organization/changes/{change_id}/operations")
def organization_change_operation(change_id: str, body: OrganizationOperationBody, session: Dict[str, Any] = Depends(require_action("organizations.changes.write"))) -> Dict[str, Any]:
    actor = str(session["principal_id"])
    try:
        operation_type, target_type, target_id, command, expected = _organization_operation(body.operation)
        organization_api.append_operation(actor, change_id, operation_type, target_type, target_id, command, expected)
        return {"change_set": organization_api.get_change_set(actor, change_id)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.post("/api/organization/changes/{change_id}/{action}")
def organization_change_action(
    change_id: str,
    action: str,
    body: OrganizationWorkflowBody = OrganizationWorkflowBody(),
    session: Dict[str, Any] = Depends(require_csrf),
) -> Dict[str, Any]:
    actor = str(session["principal_id"])
    try:
        if action == "undo":
            result = organization_api.undo_operation(actor, change_id)
        elif action == "redo":
            result = organization_api.redo_operation(actor, change_id)
        elif action == "validate":
            organization_api.validate_change_set(actor, change_id)
            organization_api.calculate_impact(actor, change_id)
            result = organization_api.get_change_set(actor, change_id)
        elif action == "submit":
            result = organization_api.submit_change_set(actor, change_id)
        elif action == "publish":
            pending = organization_api.get_change_set(actor, change_id)
            features = _edition_features()
            if (str(pending.get("status") or "").upper() == "PENDING_APPROVAL"
                    and not (features and features.has_feature("approvals"))):
                result = organization_api.publish_com_pending(actor, change_id, body.reason)
            else:
                result = organization_api.publish_low_risk(actor, change_id, body.reason)
        elif action == "withdraw":
            result = organization_api.withdraw_change_set(actor, change_id, body.reason)
        elif action == "discard":
            result = organization_api.cancel_change_set(actor, change_id, body.reason)
        else:
            raise HTTPException(status_code=404, detail="Organization action not found")
        return {"change_set": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/history")
def organization_history(focus_id: str = "", limit: int = 100, session: Dict[str, Any] = Depends(require_action("organizations.history.read"))) -> Dict[str, Any]:
    try:
        return {"history": organization_api.list_history(str(session["principal_id"]), limit, organization_id=_organization_id(focus_id))}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/organization/sync/conflicts")
def organization_sync_conflicts(batch_id: str = "", limit: int = 100, session: Dict[str, Any] = Depends(require_action("organizations.sync.manage"))) -> Dict[str, Any]:
    try:
        return {"conflicts": organization_api.list_sync_conflicts(str(session["principal_id"]), limit, batch_id=batch_id)}
    except Exception as exc:
        raise _organization_http_error(exc) from exc


@app.get("/api/approvals")
def approvals(limit: int = 100, status: str = "", page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("approvals.read"))) -> Dict[str, Any]:
    module = _optional_module("approval_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise approvals are unavailable")
    try:
        if page_size:
            return module.list_all_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor, status=status)
        items = module.list_all(limit=max(1, min(int(limit), 500)))
        if status:
            expected = status.upper()
            items = [item for item in items if str(item.get("approval_status") or item.get("status") or "").upper() == expected]
        return {"approvals": items, "items": items, "count": len(items)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approval governance service unavailable") from exc


@app.get("/api/approvals/stats")
def approval_stats(session: Dict[str, Any] = Depends(require_action("approvals.read"))) -> Dict[str, Any]:
    module = _optional_module("approval_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise approvals are unavailable")
    try:
        return module.get_stats()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approval governance service unavailable") from exc


@app.get("/api/approvals/{approval_id}")
def approval_detail(approval_id: str, session: Dict[str, Any] = Depends(require_action("approvals.read"))) -> Dict[str, Any]:
    module = _optional_module("approval_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise approvals are unavailable")
    try:
        item = module.get_request_detail(approval_id, str(session["principal_id"]))
        if not item:
            raise HTTPException(status_code=404, detail="Approval request not found")
        return {"approval": item}
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Approval detail is unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approval governance service unavailable") from exc


@app.post("/api/approvals/{approval_id}/approve")
def approval_approve(approval_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("approvals.decide"))) -> Dict[str, Any]:
    module = _optional_module("approval_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise approvals are unavailable")
    try:
        changed = module.approve(approval_id, str(session["principal_id"]), body.reason)
        return {"success": bool(changed), "approval_id": approval_id}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approval governance service unavailable") from exc


@app.post("/api/approvals/{approval_id}/reject")
def approval_reject(approval_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("approvals.decide"))) -> Dict[str, Any]:
    module = _optional_module("approval_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise approvals are unavailable")
    try:
        changed = module.reject(approval_id, str(session["principal_id"]), body.reason)
        return {"success": bool(changed), "approval_id": approval_id}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Approval governance service unavailable") from exc


@app.get("/api/audit")
def audit(limit: int = 100, page_size: int = 0, cursor: str = "", resolution_status: str = "", audit_type: str = "", session: Dict[str, Any] = Depends(require_action("audit.read"))) -> Dict[str, Any]:
    module = _optional_module("audit_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise audit is unavailable")
    try:
        if page_size:
            return module.get_audit_events_cursor(
                str(session["principal_id"]), page_size=page_size, cursor=cursor,
                resolution_status=resolution_status or None, audit_type=audit_type or None,
            )
        events = module.get_audit_events(limit=max(1, min(int(limit), 1000)))
        try:
            stats = module.get_audit_stats()
        except Exception:
            stats = {}
        return {"events": events, "items": events, "stats": stats, "count": len(events)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Audit service unavailable") from exc


@app.get("/api/audit/stats")
def audit_stats(session: Dict[str, Any] = Depends(require_action("audit.read"))) -> Dict[str, Any]:
    module = _optional_module("audit_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise audit is unavailable")
    try:
        return module.get_audit_stats()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Audit service unavailable") from exc


@app.get("/api/governance/evidence/export")
def evidence_export(limit: int = 1000, reason: str = "", session: Dict[str, Any] = Depends(require_action("audit.export"))) -> Dict[str, Any]:
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Evidence export reason is required")
    module = _optional_module("governance_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise evidence export is unavailable")
    try:
        result = module.export_evidence(str(session["principal_id"]), limit=max(1, min(int(limit), 5000)))
        return {"success": True, "reason": reason[:2000], **result}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Evidence export was denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Evidence export service unavailable") from exc


@app.post("/api/governance/legal-holds")
def legal_hold(body: LegalHoldBody, session: Dict[str, Any] = Depends(require_action("audit.export"))) -> Dict[str, Any]:
    module = _optional_module("governance_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Enterprise legal hold is unavailable")
    try:
        created = module.add_legal_hold(body.hold_id, body.scope, body.reason, str(session["principal_id"]))
        return {"success": bool(created), "hold_id": body.hold_id}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Legal hold was denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Legal hold service unavailable") from exc


@app.get("/api/users")
def users(page_size: int = 20, cursor: str = "", session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return identity_api.list_users_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
    except (identity_api.IdentityError, cursor_pagination.CursorError) as exc:
        raise HTTPException(status_code=503, detail="User authorization scope is unavailable") from exc


@app.get("/api/registration/requests")
def registration_requests(status: str = "", session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        rows = identity_api.list_registration_requests(str(session["principal_id"]), status)
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Registration governance data is unavailable") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Registration requests are outside the delegated scope") from exc
    return {"items": rows, "count": len(rows)}


@app.post("/api/registration/requests/{request_id}/approve")
def registration_approve(request_id: str, body: RegistrationApprovalBody, session: Dict[str, Any] = Depends(require_action("users.approve"))) -> Dict[str, Any]:
    try:
        result = identity_api.approve_registration(
            request_id, str(session["principal_id"]), body.reason, body.organization_id,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Registration decision failed") from exc
    return result


@app.post("/api/registration/requests/{request_id}/reject")
def registration_reject(request_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("users.approve"))) -> Dict[str, Any]:
    try:
        return identity_api.reject_registration(request_id, str(session["principal_id"]), body.reason)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Registration decision failed") from exc


@app.get("/api/registration/tokens")
def registration_tokens(limit: int = 100, session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return {"items": identity_api.list_human_registration_tokens(str(session["principal_id"]), limit)}
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=503, detail="Registration token inventory is unavailable") from exc


@app.post("/api/registration/tokens")
def registration_token_issue(body: HumanRegistrationTokenBody, session: Dict[str, Any] = Depends(require_action("users.approve"))) -> Dict[str, Any]:
    try:
        return identity_api.issue_human_registration_token(
            str(session["principal_id"]), body.expires_in_seconds, body.reason,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Registration token issue was denied") from exc


@app.delete("/api/registration/tokens/{token_id}")
def registration_token_revoke(token_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("users.approve"))) -> Dict[str, Any]:
    try:
        return {"success": identity_api.revoke_human_registration_token(
            str(session["principal_id"]), token_id, body.reason,
        )}
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Registration token revoke was denied") from exc


@app.get("/api/registration/policy")
def registration_policy_admin(
    context: str = "SELF",
    session: Dict[str, Any] = Depends(require_action("users.read")),
) -> Dict[str, Any]:
    try:
        return identity_api.registration_administration_policy(context)
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Registration policy service unavailable") from exc


@app.put("/api/registration/policy/{context}/{field_key}")
def registration_field_policy_update(
    context: str, field_key: str, body: RegistrationFieldPolicyBody,
    session: Dict[str, Any] = Depends(require_action("users.permissions.manage")),
) -> Dict[str, Any]:
    try:
        return identity_api.update_registration_field_policy(
            str(session["principal_id"]), context, field_key,
            body.field_state, body.expected_version, body.reason,
        )
    except identity_api.IdentityError as exc:
        status = 409 if "conflict" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail="Registration policy update was rejected") from exc


@app.put("/api/registration/token-policy")
def registration_token_policy_update(
    body: RegistrationTokenPolicyBody,
    session: Dict[str, Any] = Depends(require_action("users.permissions.manage")),
) -> Dict[str, Any]:
    try:
        return identity_api.set_human_registration_token_required(
            str(session["principal_id"]), body.required, body.expected_version, body.reason,
        )
    except identity_api.IdentityError as exc:
        status = 409 if "conflict" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail="Registration Token policy update was rejected") from exc


@app.get("/api/users/{principal_id}/portal-connections")
def user_portal_connections(
    principal_id: str,
    session: Dict[str, Any] = Depends(require_action("users.sessions.read")),
) -> Dict[str, Any]:
    try:
        actor = str(session["principal_id"])
        return {
            "policy": identity_api.portal_connection_policy(actor, principal_id),
            "items": identity_api.portal_connection_inventory(actor, principal_id),
        }
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Portal connection inventory is unavailable") from exc


@app.put("/api/users/{principal_id}/portal-connections/policy")
def user_portal_connection_policy_update(
    principal_id: str, body: PortalConnectionPolicyBody,
    session: Dict[str, Any] = Depends(require_action("users.permissions.manage")),
) -> Dict[str, Any]:
    try:
        return identity_api.set_portal_connection_policy(
            str(session["principal_id"]), principal_id, body.max_connections,
            body.expected_version, body.reason,
        )
    except identity_api.IdentityError as exc:
        status = 409 if "conflict" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail="Portal connection policy update was rejected") from exc


@app.delete("/api/users/{principal_id}/portal-connections/{connection_id}")
def user_portal_connection_release(
    principal_id: str, connection_id: str, body: DecisionBody,
    session: Dict[str, Any] = Depends(require_action("sessions.revoke")),
) -> Dict[str, Any]:
    try:
        return {"success": identity_api.force_release_portal_connection(
            str(session["principal_id"]), principal_id, connection_id, body.reason,
        )}
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=400, detail="Portal connection release was rejected") from exc


@app.get("/api/identity/providers")
def identity_provider_configurations(
    session: Dict[str, Any] = Depends(require_action("users.security.manage")),
) -> Dict[str, Any]:
    try:
        return {"items": external_identity_api.list_provider_configurations(str(session["principal_id"]))}
    except (external_identity_api.ExternalIdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="External identity provider inventory is unavailable") from exc


@app.put("/api/identity/providers")
def identity_provider_save(
    body: ExternalProviderBody,
    session: Dict[str, Any] = Depends(require_action("users.security.manage")),
) -> Dict[str, Any]:
    try:
        return external_identity_api.save_provider_configuration(str(session["principal_id"]), body.model_dump())
    except (external_identity_api.ExternalIdentityError, PermissionError) as exc:
        status = 409 if "conflict" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail="External identity provider configuration was rejected") from exc


@app.post("/api/identity/providers/{provider_id}/test")
def identity_provider_test(
    provider_id: str, body: DecisionBody,
    session: Dict[str, Any] = Depends(require_action("users.security.manage")),
) -> Dict[str, Any]:
    try:
        return external_identity_api.provider_test(str(session["principal_id"]), provider_id, body.reason)
    except (external_identity_api.ExternalIdentityError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail="External identity provider test was unavailable") from exc


@app.delete("/api/identity/providers/{provider_id}")
def identity_provider_delete(
    provider_id: str, body: DecisionBody,
    session: Dict[str, Any] = Depends(require_action("users.security.manage")),
) -> Dict[str, Any]:
    try:
        return {"success": external_identity_api.delete_provider_configuration(
            str(session["principal_id"]), provider_id, body.reason,
        )}
    except (external_identity_api.ExternalIdentityError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail="External identity provider deletion was rejected") from exc


@app.get("/api/users/{principal_id}/access")
def access(principal_id: str, action: str = "profile.read", session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return identity_api.simulate_access(principal_id, action)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Access simulation is outside the delegated scope") from exc
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc


@app.get("/api/users/{principal_id}/roles")
def user_roles(principal_id: str, session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return {"items": identity_api.list_user_roles(str(session["principal_id"]), principal_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="User roles are outside the delegated scope") from exc
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Role service unavailable") from exc


@app.get("/api/users/{principal_id}/entry-access")
def user_entry_access(principal_id: str, session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return identity_api.get_entry_access(str(session["principal_id"]), principal_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Entry access is outside the delegated scope") from exc
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Entry-access policy is unavailable") from exc


@app.post("/api/users/{principal_id}/entry-access")
def user_entry_access_update(principal_id: str, body: EntryAccessBody, session: Dict[str, Any] = Depends(require_action("users.permissions.manage"))) -> Dict[str, Any]:
    try:
        return identity_api.set_entry_access(
            str(session["principal_id"]), principal_id, body.app_enabled, body.reason,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Entry-access change was denied") from exc


@app.post("/api/users/{principal_id}/roles")
def user_role_assign(principal_id: str, body: RoleBody, session: Dict[str, Any] = Depends(require_action("users.roles.manage"))) -> Dict[str, Any]:
    try:
        return identity_api.assign_user_role(str(session["principal_id"]), principal_id, body.role_code, body.reason)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Role change failed") from exc


@app.delete("/api/users/{principal_id}/roles/{user_role_id}")
def user_role_revoke(principal_id: str, user_role_id: str, body: RoleRevokeBody, session: Dict[str, Any] = Depends(require_action("users.roles.manage"))) -> Dict[str, Any]:
    try:
        changed = identity_api.revoke_user_role(str(session["principal_id"]), principal_id, user_role_id, body.reason)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Role change failed") from exc
    return {"success": changed}


@app.get("/api/roles")
def roles(session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return {"items": identity_api.list_role_templates(str(session["principal_id"]))}
    except identity_api.IdentityError as exc:
        raise HTTPException(status_code=503, detail="Role templates are unavailable") from exc


@app.get("/api/users/{principal_id}/security")
def user_security(principal_id: str, session: Dict[str, Any] = Depends(require_action("users.read"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.security_overview(str(session["principal_id"]), principal_id)
    except Exception as exc:
        raise _identity_http_error(exc, "User security overview is unavailable", identity_status=403) from exc


@app.post("/api/users/{principal_id}/identities")
def user_identity_link(principal_id: str, body: IdentityLinkBody, session: Dict[str, Any] = Depends(require_action("users.identity.link"))) -> Dict[str, Any]:
    if body.target_principal_id != principal_id:
        raise HTTPException(status_code=400, detail="Identity target does not match the route")
    try:
        actor = str(session["principal_id"])
        current_proven = bool(session.get("mfa_level") not in {None, "NONE"})
        target_mfa = actor == principal_id and current_proven
        approval = actor != principal_id and identity_api.effective_access(actor, "users.roles.manage") ["decision"] == "ALLOW"
        return security_lifecycle.link_external_identity(
            actor, principal_id, body.identity_type, body.provider, body.subject_key,
            current_identity_proven=current_proven,
            target_mfa_satisfied=target_mfa,
            approval_present=approval,
            reason=body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "External identity linking was denied") from exc


@app.post("/api/users/{principal_id}/mfa/policy")
def user_mfa_policy(principal_id: str, body: MfaPolicyBody, session: Dict[str, Any] = Depends(require_action("users.security.manage"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.set_mfa_required(
            str(session["principal_id"]), principal_id, body.required, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "MFA policy change was denied") from exc


@app.post("/api/users/{principal_id}/mfa/enroll")
def user_mfa_enroll(principal_id: str, body: MfaEnrollBody, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
    actor = str(session["principal_id"])
    if actor != principal_id:
        try:
            identity_api.effective_access(actor, "users.security.manage")["decision"] == "ALLOW" or (_ for _ in ()).throw(PermissionError())
        except Exception as exc:
            raise HTTPException(status_code=403, detail="MFA enrollment is outside the delegated scope") from exc
    try:
        return security_lifecycle.enroll_totp(actor, principal_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "MFA enrollment was denied") from exc


@app.post("/api/users/{principal_id}/mfa/confirm")
def user_mfa_confirm(principal_id: str, body: MfaConfirmBody, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
    if str(session["principal_id"]) != principal_id:
        raise HTTPException(status_code=403, detail="MFA confirmation is limited to the current user")
    try:
        confirmed = security_lifecycle.confirm_totp(principal_id, body.factor_id, body.code, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "MFA confirmation failed") from exc
    if not confirmed:
        raise HTTPException(status_code=400, detail="MFA confirmation failed")
    try:
        promoted = identity_api.set_session_mfa_level(str(session.get("session_digest") or ""), "STRONG")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Session service unavailable") from exc
    if not promoted:
        raise HTTPException(status_code=503, detail="Session service unavailable")
    session["mfa_level"] = "STRONG"
    return {"success": True, "mfa_level": "STRONG"}


@app.post("/api/users/{principal_id}/mfa/recovery-codes")
def user_mfa_recovery_codes(principal_id: str, body: RecoveryCodesBody, session: Dict[str, Any] = Depends(require_csrf)) -> Dict[str, Any]:
    actor = str(session["principal_id"])
    try:
        access = identity_api.effective_access(actor, "users.security.manage")
        is_admin = access["decision"] == "ALLOW"
        if actor != principal_id and not is_admin:
            raise PermissionError("MFA recovery codes are outside the delegated scope")
        return security_lifecycle.issue_recovery_codes(
            actor, principal_id, body.reason, body.count,
            actor_mfa_satisfied=session.get("mfa_level") not in {None, "NONE"},
        )
    except Exception as exc:
        raise _identity_http_error(exc, "MFA recovery codes could not be issued") from exc


@app.get("/api/users/{principal_id}/sessions")
def user_sessions(principal_id: str, session: Dict[str, Any] = Depends(require_action("users.sessions.read"))) -> Dict[str, Any]:
    try:
        items = security_lifecycle.list_sessions(str(session["principal_id"]), principal_id)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Session inventory is unavailable", identity_status=403) from exc


@app.post("/api/sessions/revoke")
def session_revoke(body: SessionRevokeBody, session: Dict[str, Any] = Depends(require_action("sessions.revoke"))) -> Dict[str, Any]:
    try:
        changed = security_lifecycle.revoke_session_for_principal(
            str(session["principal_id"]), body.target_principal_id, body.session_digest, body.reason,
        )
        return {"success": changed}
    except Exception as exc:
        raise _identity_http_error(exc, "Session revocation was denied") from exc


@app.get("/api/delegations")
def delegations(session: Dict[str, Any] = Depends(require_action("users.delegations.read"))) -> Dict[str, Any]:
    try:
        items = security_lifecycle.list_delegations(str(session["principal_id"]))
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Delegation inventory is unavailable", identity_status=403) from exc


@app.post("/api/delegations")
def delegation(body: DelegationBody, session: Dict[str, Any] = Depends(require_action("users.delegations.manage"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.create_delegation(
            str(session["principal_id"]), body.grantee_principal_id, body.permissions,
            body.data_scope, body.reason, body.valid_until,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Delegation could not be created") from exc


@app.post("/api/delegations/{delegation_id}/revoke")
def delegation_revoke(delegation_id: str, body: DelegationRevokeBody, session: Dict[str, Any] = Depends(require_action("users.delegations.manage"))) -> Dict[str, Any]:
    try:
        return {"success": security_lifecycle.revoke_delegation(str(session["principal_id"]), delegation_id, body.reason), "delegation_id": delegation_id}
    except Exception as exc:
        raise _identity_http_error(exc, "Delegation revocation was denied") from exc


@app.post("/api/users/{principal_id}/permission-overrides")
def user_permission_override(principal_id: str, body: PermissionOverrideBody, session: Dict[str, Any] = Depends(require_action("users.permissions.manage"))) -> Dict[str, Any]:
    try:
        return identity_api.assign_permission_override(
            str(session["principal_id"]), principal_id, body.resource_action,
            body.effect, body.data_scope, body.reason,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Permission override failed") from exc


@app.get("/api/agents")
def agents(page_size: int = 20, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        return identity_api.list_agents_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
    except (identity_api.IdentityError, cursor_pagination.CursorError) as exc:
        raise HTTPException(status_code=503, detail="Agent authorization scope is unavailable") from exc


@app.get("/api/monitor/agents-page")
def monitor_agents_page(page_size: int = 20, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    module = _optional_module("monitor_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Monitoring is unavailable")
    try:
        return module.get_agent_health_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
    except cursor_pagination.CursorError as exc:
        raise HTTPException(status_code=422, detail="Monitor cursor is invalid") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Monitor inventory is unavailable") from exc


@app.get("/api/monitor/overview")
def monitor_overview(session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    """Return the authenticated platform overview used by the Monitor page."""
    module = _optional_module("monitor_api")
    if module is None:
        raise HTTPException(status_code=404, detail="Monitoring is unavailable")
    try:
        # Native platform Agents are included by monitor_api as control-plane
        # health, while business Agent rows remain authorization scoped.
        return module.get_system_overview(str(session["principal_id"]))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Monitor overview is unavailable") from exc


@app.get("/api/agents/{agent_id}/posture")
def agent_posture(agent_id: str, session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        return compliance_api.posture_detail(str(session["principal_id"]), agent_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Agent compliance posture is unavailable", identity_status=403) from exc


@app.post("/api/agents/{agent_id}/activate")
def agent_activate(agent_id: str, body: ComplianceActivationBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.activate_agent(str(session["principal_id"]), agent_id, body.profile_version_id,
                                             body.evidence_strength, body.baseline, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Agent activation was denied") from exc


@app.get("/api/compliance/summary")
def compliance_summary(session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        return compliance_api.controller_summary(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance summary is unavailable", identity_status=403) from exc


@app.get("/api/compliance/postures")
def compliance_postures(limit: int = 100, page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if page_size:
            return compliance_api.list_postures_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
        items = compliance_api.list_postures(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance posture inventory is unavailable", identity_status=403) from exc


@app.get("/api/compliance/findings")
def compliance_findings(agent_id: str = "", limit: int = 100, page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if page_size:
            return compliance_api.list_findings_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor, agent_id=agent_id)
        items = compliance_api.list_findings(str(session["principal_id"]), agent_id, limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance findings are unavailable", identity_status=403) from exc


@app.get("/api/compliance/remediations")
def compliance_remediations(limit: int = 100, page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if page_size:
            return compliance_api.list_remediation_cases_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
        items = compliance_api.list_remediation_cases(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance remediation inventory is unavailable", identity_status=403) from exc


@app.post("/api/compliance/findings/{finding_id}/remediations")
def compliance_remediation_create(finding_id: str, body: ComplianceRemediationBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        return compliance_api.create_remediation(str(session["principal_id"]), finding_id, body.required_action, body.reason, body.deadline_at)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance remediation creation was denied") from exc


@app.get("/api/compliance/exceptions")
def compliance_exceptions(limit: int = 100, page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if page_size:
            return compliance_api.list_exceptions_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
        items = compliance_api.list_exceptions(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance exception inventory is unavailable", identity_status=403) from exc


@app.post("/api/compliance/exceptions")
def compliance_exception_create(body: ComplianceExceptionBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.create_exception(
            str(session["principal_id"]), body.policy_key, body.reason, agent_id=body.agent_id,
            profile_version_id=body.profile_version_id, environment=body.environment,
            expires_at=body.expires_at, compensating_controls=body.compensating_controls)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance exception request was denied") from exc


@app.post("/api/compliance/exceptions/{exception_id}/{decision}")
def compliance_exception_decide(exception_id: str, decision: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.decide_exception(str(session["principal_id"]), exception_id, decision, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance exception decision was denied") from exc


@app.get("/api/compliance/profiles")
def compliance_profiles(limit: int = 100, page_size: int = 0, cursor: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if page_size:
            return compliance_api.list_profiles_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
        items = compliance_api.list_profiles(str(session["principal_id"]), limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance profiles are unavailable", identity_status=403) from exc


@app.post("/api/compliance/profiles")
def compliance_profile_create(body: ComplianceProfileBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.create_profile_draft(str(session["principal_id"]), body.profile_key, body.display_name,
                                                   body.content, body.reason, body.parent_version_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance Profile creation was denied") from exc


@app.post("/api/compliance/profiles/{profile_version_id}/publish")
def compliance_profile_publish(profile_version_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.publish_profile(str(session["principal_id"]), profile_version_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance Profile publication was denied") from exc


@app.post("/api/agents/{agent_id}/compliance-profile")
def compliance_profile_assign(agent_id: str, body: ComplianceAssignmentBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return compliance_api.assign_profile(str(session["principal_id"]), agent_id, body.profile_version_id, body.environment, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance Profile assignment was denied") from exc


@app.post("/api/agents/{agent_id}/compliance-control")
def compliance_control(agent_id: str, body: ComplianceControlBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        return compliance_api.set_control(str(session["principal_id"]), agent_id, body.control_state, body.reason, body.expected_version)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance control was denied") from exc


@app.post("/api/agents/{agent_id}/compliance-violation")
def compliance_violation(agent_id: str, body: ComplianceViolationBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        return compliance_api.report_deterministic_violation(str(session["principal_id"]), agent_id, body.rule_code,
                                                              body.reason, body.evidence_id, body.automatic)
    except Exception as exc:
        raise _identity_http_error(exc, "Compliance violation was denied") from exc


@app.get("/api/agents/{agent_id}/relationships")
def agent_relationships(agent_id: str, session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        items = security_lifecycle.list_agent_relationships(str(session["principal_id"]), agent_id)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent relationship inventory is unavailable", identity_status=403) from exc


@app.post("/api/agents/{agent_id}/relationships")
def agent_relationship(agent_id: str, body: AgentRelationshipBody, session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.assign_agent_relationship(
            str(session["principal_id"]), agent_id, body.principal_id,
            body.relationship_role, body.reason,
            responsible_group_id=body.responsible_group_id,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Agent relationship assignment was denied") from exc


@app.get("/api/agents/{agent_id}/derived-objects")
def agent_derived_objects(agent_id: str, instance_id: str = "", session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        items = security_lifecycle.list_derived_objects(str(session["principal_id"]), agent_id, instance_id)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent derived objects are unavailable", identity_status=403) from exc


@app.post("/api/agents/{agent_id}/derived-objects")
def agent_derived_object(agent_id: str, body: DerivedObjectBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.register_derived_object(
            str(session["principal_id"]), agent_id, body.object_type, body.object_id,
            instance_id=body.instance_id, reason=body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Agent derived object registration was denied") from exc


@app.post("/api/agents/{agent_id}/derived-objects/revoke")
def agent_derived_objects_revoke(agent_id: str, body: DecisionBody, instance_id: str = "", session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        if not identity_api._agent_visible_to(str(session["principal_id"]), agent_id):
            raise PermissionError("Agent is outside the delegated scope")
        changed = security_lifecycle.revoke_derived_objects(agent_id, instance_id=instance_id, reason=body.reason)
        return {"success": True, "changed": changed, "agent_id": agent_id, "instance_id": instance_id or None}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent derived object revocation was denied") from exc


@app.get("/api/agents/{agent_id}/ownership-history")
def agent_ownership_history(agent_id: str, session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        if not identity_api._agent_visible_to(str(session["principal_id"]), agent_id):
            raise PermissionError("Agent is outside the delegated scope")
        items = identity_api._required_query(
            "SELECT HISTORY_ID, AGENT_ID, OLD_OWNER_PRINCIPAL_ID, NEW_OWNER_PRINCIPAL_ID, ACTOR_PRINCIPAL_ID, POLICY_VERSION, CREDENTIAL_ROTATED, GRANTS_REEVALUATED, REASON, CREATED_AT "
            "FROM CX_AGENT_OWNERSHIP_HISTORY WHERE AGENT_ID = :agent_id ORDER BY CREATED_AT DESC " + identity_api._limit_clause(),
            {"agent_id": agent_id, "limit": 200},
        )
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent ownership history is unavailable", identity_status=403) from exc


@app.post("/api/agents/legacy/classify")
def legacy_agent_classify(session: Dict[str, Any] = Depends(require_action("agents.manage"))) -> Dict[str, Any]:
    try:
        items = security_lifecycle.classify_legacy_agents(str(session["principal_id"]))
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Legacy Agent classification was denied") from exc


@app.post("/api/agents/{agent_id}/legacy-claim")
def legacy_agent_claim(agent_id: str, body: LegacyClaimBody, session: Dict[str, Any] = Depends(require_action("agents.claim"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.claim_legacy_agent(
            str(session["principal_id"]), agent_id, body.review_id, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Legacy Agent claim was denied") from exc


@app.post("/api/agents/instances/quarantine")
def agent_instance_quarantine(body: InstanceQuarantineBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        changed = security_lifecycle.quarantine_agent_instance(
            str(session["principal_id"]), body.agent_id, body.instance_id, body.reason,
        )
        return {"success": changed, "agent_id": body.agent_id, "instance_id": body.instance_id}
    except Exception as exc:
        raise _identity_http_error(exc, "Agent instance quarantine was denied") from exc


@app.post("/api/agents/{agent_id}/status")
def agent_status(agent_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("agents.operate"))) -> Dict[str, Any]:
    try:
        changed = identity_api.set_agent_status(str(session["principal_id"]), agent_id, body.decision, body.reason)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Agent status change failed") from exc
    return {"success": changed, "agent_id": agent_id, "status": body.decision.upper()}


@app.post("/api/agents/{agent_id}/owner-transfer")
def agent_owner_transfer(agent_id: str, body: OwnerTransferBody, session: Dict[str, Any] = Depends(require_action("agents.transfer"))) -> Dict[str, Any]:
    try:
        return identity_api.transfer_agent_owner(
            str(session["principal_id"]), agent_id, body.new_owner_principal_id, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Agent ownership transfer was denied") from exc


@app.post("/api/agents/{agent_id}/offboard")
def agent_offboard(agent_id: str, body: OffboardBody, session: Dict[str, Any] = Depends(require_action("agents.offboard"))) -> Dict[str, Any]:
    try:
        return identity_api.offboard_agent(
            str(session["principal_id"]), agent_id, owner_type=body.owner_type,
            has_responsible_group=body.has_responsible_group, environment=body.environment,
            reason=body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Agent offboarding was denied") from exc


@app.get("/api/enrollment/grants")
def enrollment_grants(session: Dict[str, Any] = Depends(require_action("agents.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_enrollment_grants(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "Enrollment governance data is unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/enrollment/grants")
def grant(body: GrantBody, session: Dict[str, Any] = Depends(require_action("agents.enroll"))) -> Dict[str, Any]:
    try:
        ttl_seconds = body.ttl_seconds if body.ttl_seconds is not None else 900
        # A Dashboard grant names the Agent and fixes ownership/scope only.
        # Runtime identity is declared by the external Agent at redemption;
        # keeping it out of this request prevents stale or generic defaults.
        # Oracle keeps RUNTIME non-null for the grant snapshot.  The external
        # Agent still declares its actual runtime during token redemption; this
        # placeholder only represents an intentionally unconstrained grant.
        return identity_api.create_enrollment_grant(str(session["principal_id"]), body.owner_principal_id or None, environment=body.environment, runtime="UNSPECIFIED", security_domain_id=body.security_domain_id, agent_name=body.agent_name, risk_tier=body.risk_tier, ttl_seconds=ttl_seconds, responsible_group_id=body.responsible_group_id)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Enrollment grant could not be created") from exc


@app.post("/api/enrollment/redeem")
def redeem(body: EnrollmentBody) -> Dict[str, Any]:
    try:
        native_agent_api.enforce_external_registration_allowed()
        return identity_api.redeem_enrollment(body.enrollment_token, body.agent_id, runtime=body.runtime, environment=body.environment, node_id=body.node_id, public_key=body.public_key, client_secret=body.client_secret)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Enrollment failed") from exc


@app.get("/api/channels")
def channels(page_size: int = 20, cursor: str = "", session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        return identity_api.list_channels_cursor(str(session["principal_id"]), page_size=page_size, cursor=cursor)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel governance data is unavailable", identity_status=503) from exc


@app.post("/api/channels")
def channel(body: ChannelBody, session: Dict[str, Any] = Depends(require_action("channels.create"))) -> Dict[str, Any]:
    try:
        return identity_api.create_channel(str(session["principal_id"]), body.channel_name, body.security_domain_id, classification=body.classification, channel_type=body.channel_type)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel could not be created") from exc


@app.get("/api/security-domains")
def security_domains(limit: int = 200, include_inactive: bool = False, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = security_domain_api.list_domains(str(session["principal_id"]), limit=limit, include_inactive=include_inactive)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain inventory is unavailable", identity_status=503) from exc


@app.get("/api/security-domains/candidates")
def security_domain_candidates(limit: int = 300, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return {"items": security_domain_api.list_principal_candidates(str(session["principal_id"]), limit=limit)}
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain candidates are unavailable", identity_status=503) from exc


@app.post("/api/security-domains")
def security_domain_create(body: SecurityDomainBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.create_domain(str(session["principal_id"]), body.security_domain_id, body.domain_name, body.classification, body.purpose, body.owner_principal_id, body.reason, status=body.status)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain could not be created") from exc


@app.get("/api/security-domains/{domain_id}/members")
def security_domain_members(domain_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = security_domain_api.list_members(str(session["principal_id"]), domain_id)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain members are unavailable", identity_status=503) from exc


@app.post("/api/security-domains/{domain_id}/members")
def security_domain_member_set(domain_id: str, body: SecurityDomainMemberBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.set_member(str(session["principal_id"]), domain_id, body.principal_id, body.membership_tier, body.reason, valid_until=body.valid_until, status=body.status)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain member could not be updated") from exc


@app.post("/api/security-domains/{domain_id}/lifecycle")
def security_domain_lifecycle(domain_id: str, body: SecurityDomainStatusBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.set_domain_status(str(session["principal_id"]), domain_id, body.status, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain lifecycle could not be changed") from exc


@app.get("/api/security-domains/{domain_id}/bindings")
def security_domain_bindings(domain_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = security_domain_api.list_bindings(str(session["principal_id"]), domain_id)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain bindings are unavailable", identity_status=503) from exc


@app.post("/api/security-domains/{domain_id}/bindings")
def security_domain_binding_create(domain_id: str, body: DomainBindingBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.create_binding(str(session["principal_id"]), domain_id, body.binding_type, body.target_id, body.reason, approval_ref=body.approval_ref)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain binding could not be created") from exc


@app.get("/api/security-domains/collaboration-groups")
def security_domain_groups(limit: int = 200, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return {"items": security_domain_api.list_collaboration_groups(str(session["principal_id"]), limit=limit)}
    except Exception as exc:
        raise _identity_http_error(exc, "Collaboration group inventory is unavailable", identity_status=503) from exc


@app.post("/api/security-domains/conversion-drafts")
def security_domain_conversion_draft_create(body: DomainConversionDraftBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.create_conversion_draft(str(session["principal_id"]), body.source_group_id, body.security_domain_id, body.domain_name, body.classification, body.purpose, body.owner_principal_id, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain conversion draft could not be created") from exc


@app.get("/api/security-domains/conversion-drafts/{draft_id}")
def security_domain_conversion_draft(draft_id: str, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.get_conversion_draft(str(session["principal_id"]), draft_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain conversion draft is unavailable", identity_status=503) from exc


@app.post("/api/security-domains/conversion-drafts/{draft_id}/members/{principal_id}")
def security_domain_conversion_draft_member(draft_id: str, principal_id: str, body: DraftMemberReviewBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.review_draft_member(str(session["principal_id"]), draft_id, principal_id, body.decision, body.membership_tier, body.reason, valid_until=body.valid_until)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain conversion member could not be reviewed") from exc


@app.post("/api/security-domains/conversion-drafts/{draft_id}/apply")
def security_domain_conversion_draft_apply(draft_id: str, body: DraftApplyBody, session: Dict[str, Any] = Depends(require_action("domains.manage"))) -> Dict[str, Any]:
    try:
        return security_domain_api.apply_conversion_draft(str(session["principal_id"]), draft_id, body.reason, approval_ref=body.approval_ref)
    except Exception as exc:
        raise _identity_http_error(exc, "Security Domain conversion draft could not be applied") from exc


@app.post("/api/channels/{channel_id}/lifecycle")
def channel_lifecycle(channel_id: str, body: LifecycleBody, session: Dict[str, Any] = Depends(require_action("channels.lifecycle"))) -> Dict[str, Any]:
    try:
        return identity_api.transition_channel_lifecycle(
            str(session["principal_id"]), channel_id, body.status, body.reason,
            deletion_after=body.deletion_after,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Channel lifecycle transition was denied") from exc


@app.post("/api/channels/{channel_id}/legal-hold")
def channel_legal_hold(channel_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("channels.lifecycle"))) -> Dict[str, Any]:
    try:
        enabled = str(body.decision or "").upper() in {"ON", "ENABLE", "ENABLED", "SET", "TRUE"}
        return identity_api.set_channel_legal_hold(str(session["principal_id"]), channel_id, enabled, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel legal hold operation was denied") from exc


@app.post("/api/channels/{channel_id}/pin")
def channel_pin(channel_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("channels.lifecycle"))) -> Dict[str, Any]:
    try:
        enabled = str(body.decision or "").upper() in {"ON", "ENABLE", "ENABLED", "SET", "TRUE"}
        return identity_api.set_channel_pinned(str(session["principal_id"]), channel_id, enabled, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel pin operation was denied") from exc


@app.get("/api/bridges")
def bridges(session: Dict[str, Any] = Depends(require_action("channels.bridge"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_bridges(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "Bridge governance data is unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/bridges")
def bridge(body: BridgeBody, session: Dict[str, Any] = Depends(require_action("channels.bridge"))) -> Dict[str, Any]:
    try:
        return identity_api.create_bridge(
            str(session["principal_id"]), body.source_domain_id, body.target_domain_id,
            body.transfer_mode, body.classification, body.recipients, body.purpose,
            body.reason, expires_at=body.expires_at, full_copy_enabled=body.full_copy_enabled,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Bridge could not be created") from exc


@app.post("/api/bridges/{bridge_id}/approve")
def bridge_approve(bridge_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("channels.bridge"))) -> Dict[str, Any]:
    try:
        return {"success": identity_api.approve_bridge(str(session["principal_id"]), bridge_id, body.reason), "bridge_id": bridge_id}
    except Exception as exc:
        raise _identity_http_error(exc, "Bridge approval was denied") from exc


@app.post("/api/bridges/{bridge_id}/transfers")
def bridge_transfer(bridge_id: str, body: BridgeTransferBody, session: Dict[str, Any] = Depends(require_action("channels.bridge"))) -> Dict[str, Any]:
    try:
        return identity_api.create_bridge_transfer(
            str(session["principal_id"]), bridge_id, body.source_object_type,
            body.source_object_id, body.reason, payload_digest=body.payload_digest,
            target_object_id=body.target_object_id, idempotency_key=body.idempotency_key,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Bridge transfer was denied") from exc


@app.post("/api/bridges/connectors")
def bridge_connector(body: ConnectorBody, session: Dict[str, Any] = Depends(require_action("channels.bridge"))) -> Dict[str, Any]:
    features = _edition_features()
    enterprise = bool(features and features.has_feature("governance"))
    try:
        return security_lifecycle.create_connector(
            str(session["principal_id"]), body.bridge_id, body.mode,
            body.endpoint_ref, body.reason, metadata_only=body.metadata_only,
            restricted_domain=body.restricted_domain, enterprise=enterprise,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Bridge connector was denied") from exc


@app.get("/api/notifications")
def notifications(session: Dict[str, Any] = Depends(require_action("notifications.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_notifications(str(session["principal_id"]))
    except Exception as exc:
        raise _identity_http_error(exc, "Notifications are unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/notifications/{notification_id}/ack")
def notification_ack(notification_id: str, session: Dict[str, Any] = Depends(require_action("notifications.read"))) -> Dict[str, Any]:
    try:
        return {"success": identity_api.acknowledge_notification(str(session["principal_id"]), notification_id), "notification_id": notification_id}
    except Exception as exc:
        raise _identity_http_error(exc, "Notification acknowledgement failed") from exc


@app.post("/api/notifications")
def notification_create(body: NotificationBody, session: Dict[str, Any] = Depends(require_action("notifications.manage"))) -> Dict[str, Any]:
    """Create a durable notification without exposing notification content to Agents."""
    try:
        return identity_api.enqueue_notification(
            body.principal_id or str(session["principal_id"]), body.notification_type,
            body.level, body.dedupe_key, body.payload, deadline_at=body.deadline_at,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Notification could not be created") from exc


@app.get("/api/channels/{channel_id}/memory-candidates")
def memory_candidates(channel_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        identity_api._assert_channel_member(str(session["principal_id"]), channel_id, "channels.read")
        items = identity_api._required_query(
            "SELECT CANDIDATE_ID, CHANNEL_ID, PROPOSED_BY, CLASSIFICATION, DESTINATION_SCOPE, STATUS, "
            "REVIEWED_BY, REVIEW_REASON, CREATED_AT, REVIEWED_AT FROM CX_CHANNEL_MEMORY_CANDIDATES "
            "WHERE CHANNEL_ID = :channel_id ORDER BY CREATED_AT DESC " + identity_api._limit_clause(),
            {"channel_id": channel_id, "limit": 100},
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Memory candidates are unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/channels/{channel_id}/memory-candidates")
def memory_candidate(channel_id: str, body: MemoryCandidateBody, session: Dict[str, Any] = Depends(require_action("channels.write"))) -> Dict[str, Any]:
    try:
        return identity_api.propose_memory_candidate(
            str(session["principal_id"]), channel_id, body.content,
            body.classification, body.destination_scope, body.purpose,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Memory candidate was not accepted") from exc


@app.post("/api/memory-candidates/{candidate_id}/review")
def memory_candidate_review(candidate_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("memory.review"))) -> Dict[str, Any]:
    try:
        return {"success": identity_api.review_memory_candidate(str(session["principal_id"]), candidate_id, body.decision, body.reason), "candidate_id": candidate_id}
    except Exception as exc:
        raise _identity_http_error(exc, "Memory candidate review was denied") from exc


@app.post("/api/memory-candidates/{candidate_id}/promote")
def memory_candidate_promote(candidate_id: str, body: MemoryPromoteBody, session: Dict[str, Any] = Depends(require_action("memory.review"))) -> Dict[str, Any]:
    try:
        return security_lifecycle.promote_memory_candidate(
            str(session["principal_id"]), candidate_id, body.destination_scope, body.reason,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Memory candidate promotion was denied") from exc


@app.get("/api/channels/{channel_id}/messages")
def messages(channel_id: str, limit: int = 100, before: str = "", after: str = "", session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_channel_messages(
            str(session["principal_id"]), channel_id,
            limit=max(1, min(limit, 500)), before=before, after=after,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Channel messages are unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.get("/api/channels/{channel_id}/summary")
def channel_summary(channel_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        return identity_api.channel_summary(str(session["principal_id"]), channel_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel summary is unavailable", identity_status=503) from exc


@app.get("/api/channels/{channel_id}/threads")
def channel_threads(channel_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_channel_threads(str(session["principal_id"]), channel_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel threads are unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/channels/{channel_id}/threads")
def channel_thread_create(channel_id: str, body: ThreadBody, session: Dict[str, Any] = Depends(require_action("channels.write"))) -> Dict[str, Any]:
    try:
        return identity_api.create_channel_thread(
            str(session["principal_id"]), channel_id, body.thread_type,
            parent_thread_id=body.parent_thread_id, classification=body.classification,
            policy=body.policy, participant_principal_ids=body.participant_principal_ids,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Channel thread could not be created") from exc


@app.post("/api/channels/{channel_id}/messages")
def message(channel_id: str, body: MessageBody, session: Dict[str, Any] = Depends(require_action_cached("channels.write"))) -> Dict[str, Any]:
    try:
        return identity_api.post_channel_message(str(session["principal_id"]), channel_id, body.body, thread_type=body.thread_type, thread_id=body.thread_id, message_type=body.message_type, references=body.references, response_language=body.response_language)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel message was not accepted") from exc


@app.get("/api/channels/{channel_id}/members")
def channel_members(channel_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_channel_members(str(session["principal_id"]), channel_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel access denied", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/channels/{channel_id}/members")
def channel_member_add(channel_id: str, body: ChannelMemberBody, session: Dict[str, Any] = Depends(require_action("channels.manage_members"))) -> Dict[str, Any]:
    try:
        changed = agent_gateway_api.add_channel_member(
            str(session["principal_id"]), channel_id, body.principal_id, body.member_role, body.reason,
        )
    except (agent_gateway_api.GatewayError, identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Channel member could not be added") from exc
    return {"success": changed, "channel_id": channel_id, "principal_id": body.principal_id, "member_role": body.member_role}


@app.delete("/api/channels/{channel_id}/members/{member_principal_id}")
def channel_member_remove(channel_id: str, member_principal_id: str, body: ChannelMemberBody, session: Dict[str, Any] = Depends(require_action("channels.manage_members"))) -> Dict[str, Any]:
    try:
        changed = agent_gateway_api.remove_channel_member(
            str(session["principal_id"]), channel_id, member_principal_id, body.reason,
        )
    except (agent_gateway_api.GatewayError, identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Channel member could not be removed") from exc
    return {"success": changed, "channel_id": channel_id, "principal_id": member_principal_id}


@app.post("/api/channels/{channel_id}/actions")
def action_card(channel_id: str, body: ActionCardBody, session: Dict[str, Any] = Depends(require_action("channels.write"))) -> Dict[str, Any]:
    try:
        return identity_api.create_action_card(str(session["principal_id"]), channel_id, body.action_type, body.payload, body.reason, body.idempotency_key)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Action proposal was not accepted") from exc


@app.get("/api/channels/{channel_id}/actions")
def action_cards(channel_id: str, session: Dict[str, Any] = Depends(require_action("channels.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_action_cards(str(session["principal_id"]), channel_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Channel actions are unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.post("/api/actions/{action_id}/decision")
def action_decision(action_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("channels.actions.decide"))) -> Dict[str, Any]:
    try:
        actor = str(session["principal_id"])
        changed = identity_api.decide_action_card(actor, action_id, body.decision, body.reason)
        if str(body.decision or "").upper() in {"CONFIRM", "APPROVE", "RELEASE"}:
            action = {str(k).lower(): v for k, v in dict(connection.execute_query_one(
                "SELECT ACTION_TYPE,PAYLOAD_JSON,STATUS FROM CX_ACTION_CARDS WHERE ACTION_ID=:id", {"id": action_id},
            ) or {}).items()}
            # A confirmed Action Card is durable approval evidence. Replaying the
            # same decision resumes an interrupted command without approving it twice.
            if (str(action.get("status") or "").upper() == "CONFIRMED" and
                    str(action.get("action_type") or "").upper() == "PLATFORM_ADMIN_COMMAND"):
                payload = json.loads(str(action.get("payload_json") or "{}"))
                command_id = str(payload.get("command_id") or "")
                if command_id:
                    platform_agent_pool.execute_approved_command(actor, command_id, action_id)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Action decision failed") from exc
    return {"success": changed, "action_id": action_id}


@app.post("/api/barriers")
def barrier(body: BarrierBody, session: Dict[str, Any] = Depends(require_action("barriers.create"))) -> Dict[str, Any]:
    try:
        return identity_api.create_barrier(str(session["principal_id"]), body.node_key, body.policy, body.participant_snapshot, channel_id=body.channel_id, run_id=body.run_id, checkpoint_id=body.checkpoint_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Barrier could not be created") from exc


@app.post("/api/barriers/{barrier_id}/arrivals")
def arrival(barrier_id: str, body: ArrivalBody, session: Dict[str, Any] = Depends(require_action("barriers.arrive"))) -> Dict[str, Any]:
    try:
        return identity_api.arrive_barrier(str(session["principal_id"]), barrier_id, body.report, body.participant_role, body.idempotency_key)
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=409 if "conflict" in str(exc).lower() else 403, detail="Barrier arrival failed") from exc


@app.get("/api/barriers")
def barriers(channel_id: str = "", session: Dict[str, Any] = Depends(require_action("barriers.read"))) -> Dict[str, Any]:
    try:
        items = identity_api.list_barriers(str(session["principal_id"]), channel_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Barrier governance data is unavailable", identity_status=503) from exc
    return {"items": items, "count": len(items)}


@app.get("/api/barriers/{barrier_id}")
def barrier_detail(barrier_id: str, session: Dict[str, Any] = Depends(require_action("barriers.read"))) -> Dict[str, Any]:
    try:
        return identity_api.barrier_detail(str(session["principal_id"]), barrier_id)
    except Exception as exc:
        raise _identity_http_error(exc, "Barrier access denied", identity_status=503) from exc


@app.post("/api/barriers/{barrier_id}/decision")
def barrier_decision(barrier_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("barriers.release"))) -> Dict[str, Any]:
    try:
        changed = identity_api.release_barrier(str(session["principal_id"]), barrier_id, body.decision, body.reason)
    except Exception as exc:
        raise _identity_http_error(exc, "Barrier decision failed") from exc
    return {"success": changed, "barrier_id": barrier_id}


@app.post("/api/barriers/{barrier_id}/recover")
def barrier_recover(barrier_id: str, body: BarrierRecoveryBody, session: Dict[str, Any] = Depends(require_action("barriers.recover"))) -> Dict[str, Any]:
    try:
        return identity_api.recover_barrier(
            str(session["principal_id"]), barrier_id, body.action, body.reason,
            substitute_principal_id=body.substitute_principal_id,
        )
    except Exception as exc:
        raise _identity_http_error(exc, "Barrier recovery was denied") from exc


@app.post("/api/runtime/profile/preflight")
def runtime_profile_preflight(body: ProfileBody, session: Dict[str, Any] = Depends(require_action("profile.update"))) -> Dict[str, Any]:
    raise HTTPException(
        status_code=409,
        detail="Experimental runtime profiles are unavailable in the Production configuration",
    )


@app.post("/api/runtime/profile/{change_id}/activate")
def runtime_profile_activate(change_id: str, body: DecisionBody, session: Dict[str, Any] = Depends(require_action("profile.update"))) -> Dict[str, Any]:
    raise HTTPException(
        status_code=409,
        detail="Experimental runtime profiles are unavailable in the Production configuration",
    )


def _gateway_context(request: Request, required_scope: str = "", *, operation: str = "work",
                     attach_agent_database_context: bool = True) -> Dict[str, Any]:
    # A worker may previously have served another Agent or Human request.
    # Authentication must always begin from the Schema Owner boundary; only
    # the verified Agent for this request may then select a dedicated login.
    clear_context = getattr(connection, "set_agent_context", None)
    if callable(clear_context):
        clear_context(None)
    authorization = request.headers.get("Authorization", "")
    raw_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    agent_id = request.headers.get("X-Agent-Id", "").strip()
    instance_id = request.headers.get("X-Agent-Instance", "").strip()
    context = agent_gateway_api.authenticate_access_token(raw_token, agent_id, instance_id, required_scope, operation=operation)
    if not context:
        raise HTTPException(status_code=401, detail="Agent access token is invalid")
    set_context = getattr(connection, "set_agent_context", None)
    if attach_agent_database_context and callable(set_context):
        set_context(str(context["agent_id"]))
    return context


def _gateway_activation_credential(body: GatewayActivationBody) -> Optional[Dict[str, Any]]:
    """Verify a pending Agent's registered credential for activation only."""
    credential = agent_gateway_api.authenticate_activation_client_secret(body.agent_id, body.client_secret)
    if credential:
        return credential
    if not (body.public_key and body.signature and body.challenge):
        return None
    try:
        candidate = identity_api._row(connection.execute_query_one(
            "SELECT c.AGENT_ID,c.CREDENTIAL_ID,c.CREDENTIAL_TYPE,c.PUBLIC_KEY,c.STATUS,p.STATUS AS AGENT_STATUS "
            "FROM CX_AGENT_CREDENTIALS c JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID=c.AGENT_ID "
            "WHERE c.AGENT_ID=:agent_id AND c.CREDENTIAL_TYPE='ED25519' AND c.STATUS='ACTIVE' "
            "AND p.PRINCIPAL_TYPE='AGENT' AND p.STATUS='PENDING_ACTIVATION' "
            "AND (c.EXPIRES_AT IS NULL OR c.EXPIRES_AT>CURRENT_TIMESTAMP)", {"agent_id": body.agent_id}))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent credential service unavailable") from exc
    if not candidate or str(candidate.get("public_key") or "") != body.public_key:
        return None
    return candidate if agent_gateway_api.verify_ed25519_proof(
        body.public_key, body.signature, f"{body.agent_id}|activation|{body.challenge}") else None


@app.post("/api/gateway/activate")
@app.post("/api/agent-gateway/activate")
@_gateway_request_context
def gateway_activate(body: GatewayActivationBody) -> Dict[str, Any]:
    """Complete the one allowed pre-active Gateway action: credential proof."""
    credential = _gateway_activation_credential(body)
    if not credential:
        raise HTTPException(status_code=401, detail="Agent activation credential is invalid")
    try:
        features = _edition_features()
        if features is not None and not features.has_feature("compliance"):
            return identity_api.activate_community_agent(
                body.agent_id, body.security_domain_id, body.baseline,
            )
        return compliance_api.activate_from_gateway(
            body.agent_id, body.baseline, credential_type=str(credential.get("credential_type") or ""),
            runtime="", environment="", security_domain_id=body.security_domain_id,
        )
    except compliance_api.ComplianceError as exc:
        raise HTTPException(status_code=403, detail="Agent activation was denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent activation service unavailable") from exc


@app.post("/api/gateway/token")
@app.post("/api/agent-gateway/token")
@_gateway_request_context
def gateway_token(body: GatewayTokenBody) -> Dict[str, Any]:
    """Exchange a one-time bootstrap credential for a short-lived instance token."""
    instance_id = body.instance_id
    try:
        credential = agent_gateway_api.authenticate_client_secret(body.agent_id, body.client_secret)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent credential service unavailable") from exc
    if not credential and body.public_key and body.signature and body.challenge:
        try:
            credential = identity_api._row(connection.execute_query_one(
                "SELECT c.AGENT_ID, c.CREDENTIAL_ID, c.CREDENTIAL_TYPE, c.PUBLIC_KEY, c.STATUS, c.EXPIRES_AT "
                "FROM CX_AGENT_CREDENTIALS c JOIN CX_PRINCIPALS p ON p.PRINCIPAL_ID = c.AGENT_ID "
                "WHERE c.AGENT_ID = :agent_id AND c.CREDENTIAL_TYPE = 'ED25519' "
                "AND c.STATUS = 'ACTIVE' AND p.PRINCIPAL_TYPE = 'AGENT' AND p.STATUS = 'ACTIVE' "
                "AND (c.EXPIRES_AT IS NULL OR c.EXPIRES_AT > CURRENT_TIMESTAMP)", {"agent_id": body.agent_id},
            ))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Agent credential service unavailable") from exc
        if not credential or str(credential.get("public_key") or "") != body.public_key:
            credential = None
        elif not agent_gateway_api.verify_ed25519_proof(
            body.public_key, body.signature,
            f"{body.agent_id}|{instance_id}|{body.challenge}",
        ):
            credential = None
    if not credential:
        raise HTTPException(status_code=401, detail="Agent credential is invalid")
    if not instance_id:
        try:
            instance = agent_gateway_api.create_instance(
                body.agent_id, channel_id=body.channel_id,
                security_domain_id=body.security_domain_id, node_id=body.node_id,
            )
            instance_id = instance["instance_id"]
        except (agent_gateway_api.GatewayError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail="Agent instance could not be created") from exc
    requested = body.scopes or ["channels.read", "channels.write"]
    allowed = {"channels.read", "channels.write", "barriers.arrive", "actions.propose", "events.read", "compliance.evidence", "compliance.remediation", "embedding.probe", "embedding.generate", "database.endpoint", "skills.read", "memory.propose", "knowledge.read", "knowledge.write"}
    if not set(requested) <= allowed:
        raise HTTPException(status_code=403, detail="Requested Agent scope is not allowed")
    if "embedding.generate" in requested:
        try:
            embedding_governance.require_embedding_gateway_access(body.agent_id)
        except (PermissionError, embedding_governance.EmbeddingGovernanceError) as exc:
            raise HTTPException(status_code=403, detail="Agent is not authorized for platform Embedding generation") from exc
    try:
        issued = agent_gateway_api.issue_access_token(body.agent_id, instance_id, requested)
        # Database target metadata is distributed only after the Agent has
        # authenticated.  Passwords, keys, and connection secrets are never
        # included; the endpoint resolver applies the enrollment-grant scope.
        issued["database_endpoint"] = platform_agent_pool.discover_agent_endpoint(body.agent_id)
        return issued
    except agent_gateway_api.GatewayError as exc:
        raise HTTPException(status_code=403, detail="Agent token could not be issued") from exc


@app.get("/api/gateway/database-endpoint")
@app.get("/api/agent-gateway/database-endpoint")
@_gateway_request_context
def gateway_database_endpoint(request: Request) -> Dict[str, Any]:
    """Rediscover the authenticated external Agent's scoped DB target."""
    context = _gateway_context(
        request, "database.endpoint", operation="database.endpoint",
        attach_agent_database_context=False,
    )
    try:
        return platform_agent_pool.discover_agent_endpoint(str(context["agent_id"]))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database endpoint discovery unavailable") from exc


@app.post("/api/gateway/instances")
@_gateway_request_context
def gateway_instance(body: GatewayTokenBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, operation="instances.create", attach_agent_database_context=False,
    )
    try:
        return agent_gateway_api.create_instance(
            str(context["agent_id"]), channel_id=body.channel_id,
            security_domain_id=body.security_domain_id, node_id=body.node_id,
        )
    except agent_gateway_api.GatewayError as exc:
        raise HTTPException(status_code=403, detail="Agent instance could not be created") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent instance service unavailable") from exc


@app.get("/api/gateway/events")
@app.get("/api/agent-gateway/events")
@_gateway_request_context
def gateway_events(request: Request, channel_id: str = "", limit: int = 100) -> Dict[str, Any]:
    context = _gateway_context(
        request, "channels.read", operation="channels.read",
        attach_agent_database_context=False,
    )
    try:
        items = agent_gateway_api.list_channel_events(str(context["agent_id"]), channel_id, max(1, min(int(limit), 500)))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent event service unavailable") from exc
    return {"items": items, "count": len(items), "agent_id": context["agent_id"], "instance_id": context["instance_id"]}


@app.get("/api/gateway/events/stream")
@_gateway_request_context
def gateway_event_stream(request: Request, channel_id: str = "", limit: int = 50) -> StreamingResponse:
    context = _gateway_context(
        request, "channels.read", operation="channels.read",
        attach_agent_database_context=False,
    )
    try:
        items = agent_gateway_api.list_channel_events(str(context["agent_id"]), channel_id, max(1, min(int(limit), 500)))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent event service unavailable") from exc

    # Encode before response headers are sent. Database adapters return native
    # datetime/Decimal values; a lazy json.dumps failure would otherwise leave
    # the external Agent with a successful but truncated SSE response.
    event_payload = json.dumps({"items": jsonable_encoder(items)}, ensure_ascii=True)

    async def stream():
        yield "event: channel\n"
        yield "data: " + event_payload + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/gateway/events/claim")
@app.post("/api/agent-gateway/events/claim")
@_gateway_request_context
def gateway_claim(request: Request, limit: int = 50) -> Dict[str, Any]:
    context = _gateway_context(request, "events.read")
    try:
        items = agent_gateway_api.claim_events(
            str(context["agent_id"]), str(context["instance_id"]), max(1, min(int(limit), 100)),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent event service unavailable") from exc
    return {"items": items, "count": len(items), "agent_id": context["agent_id"], "instance_id": context["instance_id"]}


@app.post("/api/gateway/events/{delivery_id}/ack")
@_gateway_request_context
def gateway_ack(delivery_id: str, body: GatewayAckBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(request, "events.read")
    try:
        changed = agent_gateway_api.acknowledge_event(
            str(context["agent_id"]), str(context["instance_id"]), delivery_id,
            claim_token=body.claim_token, success=body.success, reason=body.reason,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent event service unavailable") from exc
    return {"success": changed, "delivery_id": delivery_id}


@app.post("/api/gateway/heartbeat")
@_gateway_request_context
def gateway_heartbeat(request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, operation="heartbeat", attach_agent_database_context=False,
    )
    try:
        return {"success": agent_gateway_api.heartbeat_instance(str(context["agent_id"]), str(context["instance_id"]))}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent instance service unavailable") from exc


@app.post("/api/gateway/runtime-heartbeat")
@app.post("/api/agent-gateway/runtime-heartbeat")
@_gateway_request_context
def gateway_runtime_heartbeat(body: RuntimeIsolationHeartbeatBody, request: Request) -> Dict[str, Any]:
    """Validate runtime identity and immediately drain a drifted instance."""
    context = _gateway_context(
        request, operation="heartbeat", attach_agent_database_context=False,
    )
    try:
        report = runtime_isolation.heartbeat_contract(
            str(context["agent_id"]), str(context["instance_id"]),
            {"runtime_identity": body.runtime_identity, "policy_digest": body.policy_digest,
             "rootfs_digest": body.rootfs_digest},
        )
        if report.get("accepted"):
            report["lease_renewed"] = agent_gateway_api.heartbeat_instance(
                str(context["agent_id"]), str(context["instance_id"]),
            )
        else:
            report["lease_renewed"] = False
        return report
    except runtime_isolation.IsolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Runtime isolation heartbeat unavailable") from exc


@app.get("/api/gateway/containment")
@app.get("/api/agent-gateway/containment")
@_gateway_request_context
def gateway_containment(request: Request) -> Dict[str, Any]:
    """Let an authenticated instance retrieve at most its newest command."""
    context = _gateway_context(
        request, operation="containment.read", attach_agent_database_context=False,
    )
    try:
        command = admin_management.pull_containment_command(
            str(context["agent_id"]), str(context["instance_id"]),
        )
        return {"command": command}
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Containment command service unavailable") from exc


@app.post("/api/gateway/containment/ack")
@app.post("/api/agent-gateway/containment/ack")
@_gateway_request_context
def gateway_containment_ack(body: ContainmentAcknowledgementBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, operation="containment.ack", attach_agent_database_context=False,
    )
    try:
        return admin_management.acknowledge_containment(
            str(context["agent_id"]), str(context["instance_id"]), body.command_id,
            body.generation, body.cleanup_evidence, body.success,
        )
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Containment acknowledgement service unavailable") from exc


@app.post("/api/gateway/upgrades/vote")
@app.post("/api/agent-gateway/upgrades/vote")
@_gateway_request_context
def gateway_upgrade_vote(body: UpgradeVoteBody, request: Request) -> Dict[str, Any]:
    """Accept an Admin Agent vote from its authenticated, fenced instance."""
    context = _gateway_context(
        request, operation="upgrades.vote", attach_agent_database_context=False,
    )
    try:
        return admin_management.vote_upgrade(
            str(context["agent_id"]), str(context["instance_id"]), body.upgrade_id,
            body.decision, body.term, body.fencing_token, body.reason,
        )
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Upgrade vote service unavailable") from exc


@app.post("/api/gateway/upgrades/{upgrade_id}/node")
@app.post("/api/agent-gateway/upgrades/{upgrade_id}/node")
@_gateway_request_context
def gateway_upgrade_node(
    upgrade_id: str, body: UpgradeNodeBody, request: Request,
) -> Dict[str, Any]:
    """Accept serialized node maintenance evidence only from the live Leader."""
    context = _gateway_context(
        request, operation="upgrades.node", attach_agent_database_context=False,
    )
    try:
        return admin_management.advance_upgrade_node_from_gateway(
            str(context["agent_id"]), str(context["instance_id"]), upgrade_id,
            body.target_state, body.active_work_count, body.health_state, body.reason,
        )
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Upgrade node evidence service unavailable") from exc


@app.get("/api/gateway/upgrades/skill-pending")
@app.get("/api/agent-gateway/upgrades/skill-pending")
@_gateway_request_context
def gateway_pending_upgrade_skills(request: Request) -> Dict[str, Any]:
    """Return the caller's pending Skill updates without package contents."""
    context = _gateway_context(
        request, "skills.read", operation="skills.read",
        attach_agent_database_context=False,
    )
    try:
        return {"items": admin_management.pending_upgrade_skills(str(context["agent_id"]))}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Skill distribution status service unavailable") from exc


@app.post("/api/gateway/upgrades/skill-ack")
@app.post("/api/agent-gateway/upgrades/skill-ack")
@_gateway_request_context
def gateway_upgrade_skill_ack(body: SkillDistributionAcknowledgementBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, operation="skills.ack", attach_agent_database_context=False,
    )
    try:
        return admin_management.acknowledge_upgrade_skill(
            str(context["agent_id"]), body.upgrade_id, body.skill_version,
            body.safe_point, body.verified, body.detail,
        )
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Skill distribution acknowledgement service unavailable") from exc


@app.post("/api/gateway/management-artifacts/receipt")
@app.post("/api/agent-gateway/management-artifacts/receipt")
@_gateway_request_context
def gateway_management_artifact_receipt(body: ArtifactReceiptBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, operation="artifacts.receipt", attach_agent_database_context=False,
    )
    try:
        return admin_management.record_artifact_receipt(
            str(context["agent_id"]), body.artifact_id, body.node_id, body.received_digest,
            body.signature_state, body.available, body.detail,
        )
    except admin_management.ManagementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Management artifact receipt service unavailable") from exc


@app.post("/api/gateway/evidence")
@_gateway_request_context
def gateway_evidence(body: GatewayEvidenceBody, request: Request) -> Dict[str, Any]:
    """Accept bounded runtime evidence through the existing Gateway token."""
    context = _gateway_context(request, "compliance.evidence", operation="evidence", attach_agent_database_context=False)
    try:
        return compliance_api.submit_gateway_evidence(
            str(context["agent_id"]), str(context["instance_id"]), body.evidence_type,
            body.payload, nonce=body.nonce, expires_at=body.expires_at,
        )
    except compliance_api.ComplianceError as exc:
        raise HTTPException(status_code=403, detail="Compliance evidence was denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Compliance evidence service unavailable") from exc


@app.post("/api/gateway/remediations/{case_id}/respond")
@_gateway_request_context
def gateway_remediation(case_id: str, body: GatewayRemediationBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(request, "compliance.remediation", operation="remediation", attach_agent_database_context=False)
    try:
        return compliance_api.respond_remediation(str(context["agent_id"]), case_id, body.response)
    except compliance_api.ComplianceError as exc:
        raise HTTPException(status_code=403, detail="Remediation response was denied") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Remediation response service unavailable") from exc


@app.post("/api/gateway/channels/{channel_id}/messages")
@_gateway_request_context
def gateway_message(channel_id: str, body: GatewayMessageBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, "channels.write", operation="channels.write",
        attach_agent_database_context=False,
    )
    try:
        return identity_api.post_channel_message(
            str(context["agent_id"]), channel_id, body.body,
            thread_type=body.thread_type, thread_id=body.thread_id,
            references=body.references,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Channel message was not accepted") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Channel message service unavailable") from exc


@app.post("/api/gateway/channels/{channel_id}/memory-candidates")
@_gateway_request_context
def gateway_memory_candidate(channel_id: str, body: MemoryCandidateBody, request: Request) -> Dict[str, Any]:
    """Submit external-Agent memory through the existing Human review gate."""
    context = _gateway_context(
        request, "memory.propose", operation="memory.propose",
        attach_agent_database_context=False,
    )
    try:
        return identity_api.propose_memory_candidate(
            str(context["agent_id"]), channel_id, body.content,
            body.classification, body.destination_scope, body.purpose,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Memory candidate was not accepted") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Memory candidate service unavailable") from exc


@app.post("/api/gateway/knowledge")
@_gateway_request_context
def gateway_knowledge_create(body: GatewayKnowledgeBody, request: Request) -> Dict[str, Any]:
    """Create Agent-attributed knowledge with a database-authoritative scope."""
    context = _gateway_context(
        request, "knowledge.write", operation="knowledge.write",
        attach_agent_database_context=False,
    )
    scope = str(body.sharing_scope or "PRINCIPAL_PRIVATE").upper()
    if scope == "PUBLIC_COMPANY":
        raise HTTPException(status_code=403, detail="Company-wide Agent knowledge requires Human publication approval")
    if scope not in {"PRINCIPAL_PRIVATE", "ORGANIZATION_SUBTREE", "ORGANIZATION_LEVEL"}:
        raise HTTPException(status_code=422, detail="Knowledge sharing scope is invalid")
    try:
        entity_id = knowledge_api.create_knowledge(
            body.title, body.content, domain=body.domain or None, topic=body.topic or None,
            difficulty=body.difficulty, category=body.category or None,
            importance=body.importance, summary=body.summary or None,
            owned_by_agent=str(context["agent_id"]),
            visibility="PRIVATE" if scope == "PRINCIPAL_PRIVATE" else "SHARED",
            sharing_scope=scope, organization_id=body.organization_id or None,
            hierarchy_depth=body.hierarchy_depth, creation_reason=body.reason,
        )
        return {
            "entity_id": str(entity_id), "agent_id": str(context["agent_id"]),
            "sharing_scope": scope, "knowledge_context": knowledge_api.get_knowledge_context(str(entity_id)),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent knowledge creation service unavailable") from exc


@app.get("/api/gateway/knowledge/{entity_id}")
@_gateway_request_context
def gateway_knowledge_get(entity_id: str, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, "knowledge.read", operation="knowledge.read",
        attach_agent_database_context=False,
    )
    try:
        item = knowledge_api.get_knowledge(entity_id, principal_id=str(context["agent_id"]))
        if not item:
            raise HTTPException(status_code=404, detail="Knowledge is unavailable")
        return {"knowledge": item}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Agent knowledge service unavailable") from exc


@app.post("/api/gateway/barriers/{barrier_id}/arrivals")
@_gateway_request_context
def gateway_arrival(barrier_id: str, body: ArrivalBody, request: Request) -> Dict[str, Any]:
    # Arrival can atomically advance the shared Barrier state. Keep the
    # dedicated Agent login unable to UPDATE the Barrier table directly; the
    # authenticated control-plane transaction rechecks instance, Channel,
    # participant snapshot, role, and idempotency before changing it.
    context = _gateway_context(
        request, "barriers.arrive", operation="barriers.arrive",
        attach_agent_database_context=False,
    )
    try:
        return agent_gateway_api.submit_arrival(
            str(context["agent_id"]), str(context["instance_id"]), barrier_id,
            body.report, body.participant_role, body.idempotency_key,
        )
    except (agent_gateway_api.GatewayError, identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Barrier arrival failed") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Barrier service unavailable") from exc


@app.post("/api/gateway/channels/{channel_id}/actions")
@_gateway_request_context
def gateway_action(channel_id: str, body: ActionCardBody, request: Request) -> Dict[str, Any]:
    context = _gateway_context(
        request, "actions.propose", operation="actions.propose",
        attach_agent_database_context=False,
    )
    try:
        return identity_api.create_action_card(
            str(context["agent_id"]), channel_id, body.action_type,
            body.payload, body.reason, body.idempotency_key,
        )
    except (identity_api.IdentityError, PermissionError) as exc:
        raise HTTPException(status_code=403, detail="Action proposal was not accepted") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Action service unavailable") from exc


@app.get("/api/runtime/profile")
def runtime_profile() -> Dict[str, Any]:
    profile = _runtime_profile()
    features = _edition_features()
    return {
        "profile": profile,
        "capabilities": {
            "channels": True,
            "barriers": True,
            "graph_preview": profile in {"graph-preview", "development", "experimental-4.2"},
            "production_ready": profile == "production",
            "graph_engineering": bool(getattr(features, "GRAPH_ENGINEERING_ENABLED", True)),
        },
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def legacy_compatibility(path: str, request: Request) -> Response:
    """Keep every existing Dashboard, Portal and Agent API route available."""
    normalized = "/" + path
    gate_response = _legacy_gate(request, normalized)
    if gate_response is not None:
        return gate_response
    body = await request.body()
    if normalized == "/portal/api/chat/send" and request.method == "POST":
        try:
            is_stream = json.loads(body or b"{}").get("stream") is True
        except (json.JSONDecodeError, AttributeError):
            is_stream = False
        if is_stream:
            return await _legacy_stream_dispatch(
                request.method, normalized, request.url.query, dict(request.headers), body,
            )
    response = _legacy_dispatch(request.method, normalized, request.url.query, dict(request.headers), body)
    if normalized == "/portal/api/agent/release":
        # The legacy handler clears both browser-entry Cookies. Preserve both
        # headers across the compatibility bridge and never let the session
        # renewal middleware recreate either one on this security boundary.
        response.delete_cookie(_cookie_name("PORTAL", request.url.port), path="/")
        response.delete_cookie(_cookie_name("DASHBOARD", request.url.port), path="/")
    return response
