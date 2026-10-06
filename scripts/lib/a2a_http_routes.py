"""Authenticated standard A2A HTTP paths, backed by durable task bindings."""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from . import a2a_http_binding as service
from .continuity_bindings import authenticated_transport
from .agent_extension_contracts import canonical
from .agent_extension_http import BoundedBody


def install(app, require_action, schema_owner_context):
    from .edition_features import AGENT_EXTENSIONS_ENABLED
    if not AGENT_EXTENSIONS_ENABLED:
        return
    router = APIRouter(prefix="/api/a2a/{endpoint_id}")
    def version(request):
        if request.headers.get("A2A-Version", "1.0") not in {"1.0", "1.0.1"}:
            raise HTTPException(400, detail={"code": "VERSION_NOT_SUPPORTED", "message": "This interface supports A2A 1.0"})
    def invoke(operation, session, endpoint_id, *args, **kwargs):
        try:
            with schema_owner_context(), authenticated_transport(session.get("continuity_transport")):
                return operation(str(session["principal_id"]), endpoint_id, *args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(403, detail={"code": "PERMISSION_DENIED", "message": "A2A task or service access denied"}) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, detail={"code": "INVALID_ARGUMENT", "message": str(exc) if isinstance(exc, ValueError) else "A2A request field is missing"}) from exc
        except Exception as exc:
            raise HTTPException(503, detail={"code": "UNAVAILABLE", "message": "A2A service unavailable"}) from exc

    @router.get("/extendedAgentCard")
    def card(endpoint_id: str, request: Request, session=Depends(require_action("agents.operate"))):
        version(request)
        return invoke(service.card, session, endpoint_id)

    @router.post("/message:send")
    def send(endpoint_id: str, body: dict, request: Request, session=Depends(require_action("agents.operate"))):
        version(request)
        return invoke(service.send, session, endpoint_id, body)

    def events(session, endpoint_id, task_id, last_event_id=""):
        try:
            with schema_owner_context(), authenticated_transport(session.get("continuity_transport")):
                for event in service.subscribe(str(session["principal_id"]), endpoint_id, task_id, last_event_id=last_event_id):
                    yield ("id: " + event["id"] + "\ndata: " + canonical(event["data"]) + "\n\n").encode()
        except PermissionError:
            # The HTTP stream is already open; close it without disclosing any
            # more task data. Reconnection rechecks the original credential.
            return

    @router.post("/message:stream")
    def send_stream(endpoint_id: str, body: dict, request: Request, session=Depends(require_action("agents.operate"))):
        version(request)
        result = invoke(service.send, session, endpoint_id, body)
        return StreamingResponse(events(session, endpoint_id, result["task"]["id"]), media_type="text/event-stream", headers={"Cache-Control": "no-store", "A2A-Version": "1.0"})

    @router.get("/tasks/{task_id}:subscribe")
    def subscribe(endpoint_id: str, task_id: str, request: Request, session=Depends(require_action("agents.operate"))):
        version(request)
        invoke(service.get, session, endpoint_id, task_id)
        cursor = request.headers.get("Last-Event-ID", "")
        if cursor and not cursor.startswith(task_id + ":"):
            raise HTTPException(400, detail="A2A resume cursor belongs to another task")
        return StreamingResponse(events(session, endpoint_id, task_id, cursor), media_type="text/event-stream", headers={"Cache-Control": "no-store", "A2A-Version": "1.0"})

    @router.post("/tasks/{task_id}:cancel")
    def cancel(endpoint_id: str, task_id: str, request: Request, body: dict | None = None, session=Depends(require_action("agents.operate"))):
        version(request)
        if body and body.get("tenant") not in {None, "", endpoint_id}:
            raise HTTPException(400, detail="A2A tenant mismatch")
        return invoke(service.cancel, session, endpoint_id, task_id)

    @router.get("/tasks/{task_id}")
    def get(endpoint_id: str, task_id: str, request: Request, tenant: str = "", historyLength: int | None = Query(None, ge=0, le=100), session=Depends(require_action("agents.operate"))):
        version(request)
        if tenant and tenant != endpoint_id:
            raise HTTPException(400, detail="A2A tenant mismatch")
        return invoke(service.get, session, endpoint_id, task_id, history_length=historyLength)

    @router.get("/tasks")
    def tasks(endpoint_id: str, request: Request, tenant: str = "", contextId: str = "", status: str = "", pageSize: int = Query(50, ge=1, le=100), pageToken: str = "", historyLength: int | None = Query(None, ge=0, le=100), includeArtifacts: bool = False, session=Depends(require_action("agents.operate"))):
        version(request)
        if tenant and tenant != endpoint_id:
            raise HTTPException(400, detail="A2A tenant mismatch")
        return invoke(service.list_tasks, session, endpoint_id, context_id=contextId, status=status, page_size=pageSize, page_token=pageToken, include_artifacts=includeArtifacts, history_length=historyLength)

    app.include_router(router)
