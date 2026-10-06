"""A2A 1.0.1 HTTP+JSON binding for explicitly bound pure Graph tasks."""
from datetime import timezone
import json
import time
from . import connection, identity_api, graph_runtime as runtime, effective_capabilities, agent_gateway_api
from . import registered_protocols as protocols, continuity_work as work
from .continuity_bindings import _transport
from .agent_extension_contracts import canonical, digest, bounded_json, identifier, row, safe_key
from . import cursor_pagination as cursors

STATE_MAP = {"PENDING": "TASK_STATE_SUBMITTED", "RUNNING": "TASK_STATE_WORKING", "WAITING": "TASK_STATE_INPUT_REQUIRED",
             "PAUSED": "TASK_STATE_INPUT_REQUIRED", "SUCCEEDED": "TASK_STATE_COMPLETED", "FAILED": "TASK_STATE_FAILED",
             "CANCELLED": "TASK_STATE_CANCELED", "REVIEW_REQUIRED": "TASK_STATE_FAILED"}
TERMINAL = frozenset({"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"})


def bind(actor, endpoint_id, graph_version_id, plan_id):
    protocols._human_admin(actor)
    def perform(tx):
        record = protocols.endpoint(actor, endpoint_id, kind="A2A", tx=tx)
        work._authorize(tx, actor, record["security_domain_id"], write=True)
        plan = row(tx.query_one("SELECT p.PLAN_JSON,p.PLAN_DIGEST,v.STATUS FROM GRAPH_COMPILE_PLANS p JOIN GRAPH_VERSIONS v ON v.GRAPH_VERSION_ID=p.GRAPH_VERSION_ID WHERE p.PLAN_ID=:plan AND p.GRAPH_VERSION_ID=:version", {"plan": plan_id, "version": graph_version_id}))
        if not plan or plan["status"] != "PUBLISHED":
            raise ValueError("A published exact Graph plan is required")
        value = json.loads(plan["plan_json"])
        logical = {key: item for key, item in value.items() if key != "adapter"}
        if runtime._hash(logical) != plan["plan_digest"]:
            raise ValueError("A2A plan digest mismatch")
        nodes = value.get("nodes") or list((value.get("node_index") or {}).values())
        if any(item.get("side_effect_class", "NONE") != "NONE" or item.get("node_type") not in {"START", "END", "CONTROL", "HUMAN", "TIMER", "EVENT"} for item in nodes):
            raise ValueError("This A2A binding supports pure, bounded Graph nodes only")
        tx.execute("INSERT INTO CX_A2A_GRAPH_BINDINGS(ENDPOINT_ID,REVISION_NO,GRAPH_VERSION_ID,PLAN_ID,PLAN_DIGEST,APPROVED_BY) VALUES(:endpoint,:revision,:version,:plan,:digest,:actor)", {"endpoint": endpoint_id, "revision": int(record["current_revision"]), "version": graph_version_id, "plan": plan_id, "digest": plan["plan_digest"], "actor": actor})
        identity_api._audit_tx(tx, actor, "A2A_GRAPH_BOUND", "PROTOCOL_ENDPOINT", endpoint_id, "ALLOW", "Published pure Graph and exact plan")
        return {"endpoint_id": endpoint_id, "revision_no": int(record["current_revision"]), "plan_digest": plan["plan_digest"]}
    return connection.execute_transaction_callback(perform)


def authority(tx, actor, endpoint_id):
    record = protocols.endpoint(actor, endpoint_id, kind="A2A", tx=tx)
    bound = row(tx.query_one("SELECT b.*,v.STATUS,p.PLAN_DIGEST AS CURRENT_PLAN_DIGEST FROM CX_A2A_GRAPH_BINDINGS b JOIN GRAPH_VERSIONS v ON v.GRAPH_VERSION_ID=b.GRAPH_VERSION_ID JOIN GRAPH_COMPILE_PLANS p ON p.PLAN_ID=b.PLAN_ID WHERE b.ENDPOINT_ID=:endpoint AND b.REVISION_NO=:revision", {"endpoint": endpoint_id, "revision": int(record["current_revision"])}))
    if not bound or bound["status"] != "PUBLISHED" or bound["plan_digest"] != bound["current_plan_digest"]:
        raise PermissionError("A2A binding is not currently approved")
    effective_capabilities.require(actor, graph="a2a_gateway", model="a2a_exchange", action="agents.operate", approved_binding=True)
    work._authorize(tx, actor, record["security_domain_id"], write=False)
    return record, bound


def _credential(tx, request):
    credential = row(tx.query_one("SELECT * FROM CX_A2A_CREDENTIALS WHERE PROTOCOL_TASK_ID=:task", {"task": request["protocol_task_id"]}))
    if not credential:
        raise PermissionError("Original A2A transport credential is required")
    current = agent_gateway_api._authenticate_access_token_digest(credential["token_digest"], request["actor_id"], credential["instance_id"], "agents.operate", operation="agents.operate", query_one=tx.query_one)
    if not current or int(current["fencing_token"]) != int(credential["fencing_token"]) or current["security_domain_id"] != request["security_domain_id"]:
        raise PermissionError("Original A2A credential was revoked or fenced")


def validate_send(value, endpoint_id):
    bounded_json(value, maximum=32768)
    if value.get("tenant") not in {None, "", endpoint_id}:
        raise ValueError("A2A tenant does not match the selected interface")
    if set(value) - {"tenant", "message", "configuration", "metadata"}:
        raise ValueError("Unsupported A2A request fields")
    config = value.get("configuration") or {}
    if config.get("pushNotificationConfig") or config.get("blocking"):
        raise ValueError("Push notifications and blocking sends are unavailable")
    message = value.get("message")
    if not isinstance(message, dict) or message.get("role") != "ROLE_USER":
        raise ValueError("A2A requires a user Message")
    safe_key(message.get("messageId"))
    if message.get("contextId"):
        safe_key(message["contextId"])
    parts = message.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8 or any(not isinstance(part, dict) or set(part) != {"text"} or not isinstance(part["text"], str) for part in parts):
        raise ValueError("This A2A interface accepts bounded text parts only")
    text = "\n".join(part["text"] for part in parts)
    if not 1 <= len(text.encode()) <= 16384:
        raise ValueError("A2A message text exceeds its bound")
    return message, text


def send(actor, endpoint_id, value):
    message, text = validate_send(value, endpoint_id)
    request_hash = digest(value)
    transport = _transport.get()
    if transport is None:
        raise PermissionError("An authenticated A2A transport credential is required")
    def perform(tx):
        record, bound = authority(tx, actor, endpoint_id)
        work._lock_actor(tx, actor)
        prior = row(tx.query_one("SELECT q.*,r.GRAPH_VERSION_ID FROM CX_A2A_REQUESTS q JOIN GRAPH_PROTOCOL_TASKS t ON t.PROTOCOL_TASK_ID=q.PROTOCOL_TASK_ID JOIN GRAPH_RUNS r ON r.RUN_ID=t.RUN_ID WHERE q.ACTOR_ID=:actor AND q.MESSAGE_ID=:message", {"actor": actor, "message": message["messageId"]}))
        if prior:
            _credential(tx, prior)
            linked = row(tx.query_one("SELECT ENDPOINT_ID,REVISION_NO FROM CX_A2A_TASK_BINDINGS WHERE PROTOCOL_TASK_ID=:task", {"task": prior["protocol_task_id"]}))
            if prior["request_digest"] != request_hash or linked.get("endpoint_id") != endpoint_id or int(linked.get("revision_no") or 0) != int(record["current_revision"]) or prior["graph_version_id"] != bound["graph_version_id"] or prior["security_domain_id"] != record["security_domain_id"]:
                raise ValueError("A2A Message ID has different content, context or binding")
            return prior["protocol_task_id"]
        if message.get("taskId"):
            raise ValueError("Continuation messages are unavailable; reconnect subscriptions or submit a new task")
        task, context = identifier("A2A"), message.get("contextId") or identifier("CTX")
        run_id = runtime.create_run(bound["graph_version_id"], bound["plan_id"], actor,
            {"message": text}, {"max_nodes": 64, "max_retries": 2, "max_external_calls": 0, "max_concurrency": 1, "max_duration_seconds": 60},
            "a2a:" + actor + ":" + message["messageId"], transaction=tx)
        tx.execute("INSERT INTO GRAPH_PROTOCOL_TASKS(PROTOCOL_TASK_ID,PROTOCOL_VERSION,RUN_ID,PRINCIPAL_ID,STATUS,CURSOR_SEQ) VALUES(:task,'1.0.1',:run,:actor,'SUBMITTED',0)", {"task": task, "run": run_id, "actor": actor})
        tx.execute("INSERT INTO CX_A2A_REQUESTS(PROTOCOL_TASK_ID,SECURITY_DOMAIN_ID,ACTOR_ID,CONTEXT_ID,MESSAGE_ID,REQUEST_DIGEST) VALUES(:task,:domain,:actor,:context,:message,:digest)", {"task": task, "domain": record["security_domain_id"], "actor": actor, "context": context, "message": message["messageId"], "digest": request_hash})
        tx.execute("INSERT INTO CX_A2A_TASK_BINDINGS(PROTOCOL_TASK_ID,ENDPOINT_ID,REVISION_NO) VALUES(:task,:endpoint,:revision)", {"task": task, "endpoint": endpoint_id, "revision": int(record["current_revision"])})
        if transport:
            tx.execute("INSERT INTO CX_A2A_CREDENTIALS(PROTOCOL_TASK_ID,INSTANCE_ID,TOKEN_DIGEST,FENCING_TOKEN) VALUES(:task,:instance,:token,:fence)", {"task": task, "instance": transport["instance_id"], "token": transport["token_digest"], "fence": int(transport["fencing_token"])})
            _credential(tx, {"protocol_task_id": task, "actor_id": actor, "security_domain_id": record["security_domain_id"]})
        identity_api._audit_tx(tx, actor, "A2A_TASK_SUBMITTED", "PROTOCOL_TASK", task, "ALLOW", "Bounded pure Graph task")
        return task
    task = connection.execute_transaction_callback(perform)
    return {"task": get(actor, endpoint_id, task)}


def _task(tx, actor, endpoint_id, task_id):
    record, bound = authority(tx, actor, endpoint_id)
    value = row(tx.query_one("SELECT q.*,t.RUN_ID,r.STATUS AS RUN_STATUS,r.GRAPH_VERSION_ID,r.PLAN_DIGEST,r.UPDATED_AT,r.CURRENT_CHECKPOINT_ID,r.INPUT_STATE_JSON FROM CX_A2A_REQUESTS q JOIN GRAPH_PROTOCOL_TASKS t ON t.PROTOCOL_TASK_ID=q.PROTOCOL_TASK_ID JOIN GRAPH_RUNS r ON r.RUN_ID=t.RUN_ID WHERE q.PROTOCOL_TASK_ID=:task AND q.ACTOR_ID=:actor", {"task": task_id, "actor": actor}))
    linked = row(tx.query_one("SELECT ENDPOINT_ID,REVISION_NO FROM CX_A2A_TASK_BINDINGS WHERE PROTOCOL_TASK_ID=:task", {"task": task_id}))
    if (not value or value["security_domain_id"] != record["security_domain_id"] or
            linked.get("endpoint_id") != endpoint_id or int(linked.get("revision_no") or 0) != int(record["current_revision"]) or
            value["graph_version_id"] != bound["graph_version_id"] or value["plan_digest"] != bound["plan_digest"]):
        raise PermissionError("A2A task is outside the current binding")
    _credential(tx, value)
    return value


def _history(value, history_length):
    """Project a bounded A2A message history from the authoritative input."""
    if history_length is None:
        return None
    try:
        length = int(history_length)
    except (TypeError, ValueError):
        raise ValueError("historyLength must be between 0 and 100") from None
    if not 0 <= length <= 100:
        raise ValueError("historyLength must be between 0 and 100")
    if length == 0:
        return []
    try:
        state = json.loads(value.get("input_state_json") or "{}")
    except (TypeError, ValueError):
        state = {}
    text = state.get("message") if isinstance(state, dict) else None
    if not isinstance(text, str) or not text.strip():
        return []
    return [{"messageId": value["message_id"], "role": "ROLE_USER",
             "parts": [{"text": text[:16384]}], "contextId": value["context_id"]}]


def get(actor, endpoint_id, task_id, *, context_id="", include_artifacts=True,
        history_length=None, transaction=None):
    def perform(tx):
        value = _task(tx, actor, endpoint_id, task_id)
        if context_id and context_id != value["context_id"]:
            raise ValueError("A2A task context mismatch")
        stamp = value["updated_at"]
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        result = {"id": task_id, "contextId": value["context_id"], "status": {"state": STATE_MAP.get(value["run_status"], "TASK_STATE_UNSPECIFIED"), "timestamp": stamp.isoformat().replace("+00:00", "Z")}}
        history = _history(value, history_length)
        if history is not None:
            result["history"] = history
        if include_artifacts and value["run_status"] == "SUCCEEDED" and value.get("current_checkpoint_id"):
            checkpoint = row(tx.query_one("SELECT STATE_JSON FROM GRAPH_CHECKPOINTS WHERE CHECKPOINT_ID=:checkpoint AND RUN_ID=:run", {"checkpoint": value["current_checkpoint_id"], "run": value["run_id"]}))
            if checkpoint:
                from .graph_state import redact_state
                content = redact_state(json.loads(checkpoint["state_json"]), allow_secrets=False)
                bounded_json(content, maximum=32768)
                result["artifacts"] = [{"artifactId": task_id + "-result", "name": "Graph result", "parts": [{"data": content}]}]
        return result
    return perform(transaction) if transaction is not None else connection.execute_transaction_callback(perform)


def cancel(actor, endpoint_id, task_id):
    value = connection.execute_transaction_callback(lambda tx: _task(tx, actor, endpoint_id, task_id))
    if STATE_MAP.get(value["run_status"]) in TERMINAL:
        raise ValueError("A terminal A2A task cannot be canceled")
    runtime.cancel_run(value["run_id"], actor, "A2A caller requested cancellation")
    return get(actor, endpoint_id, task_id)


def list_tasks(actor, endpoint_id, *, context_id="", status="", page_size=50,
               page_token="", include_artifacts=False, history_length=None):
    if not 1 <= page_size <= 100 or status and status not in STATE_MAP.values():
        raise ValueError("Invalid A2A task page or state")
    filters = {"endpoint": endpoint_id, "context": context_id, "status": status, "include_artifacts": include_artifacts}
    filter_hash = cursors._digest(filters)
    def perform(tx):
        record, bound = authority(tx, actor, endpoint_id)
        position = ""
        if page_token:
            cursor = row(tx.query_one("SELECT POSITION_KEY FROM CX_API_CURSORS WHERE CURSOR_ID=:cursor AND PRINCIPAL_ID=:actor AND RESOURCE_KEY='a2a-tasks' AND FILTER_DIGEST=:digest AND SORT_KEY='task_id:asc' AND PAGE_SIZE=:page_size AND EXPIRES_AT>CURRENT_TIMESTAMP", {"cursor": page_token, "actor": actor, "digest": filter_hash, "page_size": page_size}))
            if not cursor:
                raise ValueError("A2A page token is expired or does not match the request")
            position = json.loads(cursor["position_key"])["task_id"]
        params = {"actor": actor, "domain": record["security_domain_id"], "version": bound["graph_version_id"], "endpoint": endpoint_id, "revision": int(record["current_revision"])}
        where = "q.ACTOR_ID=:actor AND q.SECURITY_DOMAIN_ID=:domain AND r.GRAPH_VERSION_ID=:version AND b.ENDPOINT_ID=:endpoint AND b.REVISION_NO=:revision"
        if context_id:
            where += " AND q.CONTEXT_ID=:context"
            params["context"] = context_id
        if status:
            matches = [key for key, value in STATE_MAP.items() if value == status]
            placeholders = []
            for index, match in enumerate(matches):
                key = "state_" + str(index)
                placeholders.append(":" + key)
                params[key] = match
            where += " AND r.STATUS IN (" + ",".join(placeholders) + ")"
        joins = " FROM CX_A2A_REQUESTS q JOIN CX_A2A_TASK_BINDINGS b ON b.PROTOCOL_TASK_ID=q.PROTOCOL_TASK_ID JOIN GRAPH_PROTOCOL_TASKS t ON t.PROTOCOL_TASK_ID=q.PROTOCOL_TASK_ID JOIN GRAPH_RUNS r ON r.RUN_ID=t.RUN_ID WHERE "
        total = int(row(tx.query_one("SELECT COUNT(*) AS CNT" + joins + where, params))["cnt"])
        if position:
            where += " AND q.PROTOCOL_TASK_ID>:after"
            params["after"] = position
        candidates = tx.query("SELECT q.PROTOCOL_TASK_ID" + joins + where + " ORDER BY q.PROTOCOL_TASK_ID" + identity_api._limit_clause("page_limit"), {**params, "page_limit": page_size + 1})
        page = candidates[:page_size]
        tasks = [get(actor, endpoint_id, row(item)["protocol_task_id"], include_artifacts=include_artifacts,
                     history_length=history_length, transaction=tx) for item in page]
        next_token = cursors.issue(actor, "a2a-tasks", filter_hash, "task_id:asc", page_size, {"task_id": row(page[-1])["protocol_task_id"]}) if len(candidates) > page_size else ""
        return {"tasks": tasks, "nextPageToken": next_token, "pageSize": page_size, "totalSize": total}
    return connection.execute_transaction_callback(perform)


def card(actor, endpoint_id):
    record, bound = connection.execute_transaction_callback(lambda tx: authority(tx, actor, endpoint_id))
    return {"name": record["endpoint_name"], "description": "Authorized bounded pure Graph tasks; reconnectable status streams, no push notifications or task continuation messages.",
            "version": "4.5.1", "supportedInterfaces": [{"url": record["endpoint_url"], "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0", "tenant": endpoint_id}],
            "capabilities": {"streaming": True, "pushNotifications": False}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
            "securitySchemes": {"gateway": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}, "securityRequirements": [{"schemes": {"gateway": {"list": ["agents.operate"]}}}],
            "skills": [{"id": bound["graph_version_id"], "name": "Published pure Graph", "description": "Independently approved exact Graph version", "tags": ["graph", "read-only"]}]}


def subscribe(actor, endpoint_id, task_id, *, last_event_id="", deadline_seconds=30):
    if not 1 <= deadline_seconds <= 60:
        raise ValueError("Invalid A2A subscription deadline")
    if last_event_id and not last_event_id.startswith(task_id + ":"):
        raise ValueError("A2A resume cursor belongs to another task")
    until, last = time.monotonic() + deadline_seconds, last_event_id
    while time.monotonic() < until:
        task = get(actor, endpoint_id, task_id)
        event_id = task_id + ":" + digest(task)
        if event_id != last:
            yield {"id": event_id, "data": {"task": task}}
            last = event_id
        if task["status"]["state"] in TERMINAL:
            return
        time.sleep(0.25)
