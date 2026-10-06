"""Durable bounded OTLP/HTTP trace delivery of committed metadata only."""
from datetime import timedelta
import hashlib
import json
import urllib.error
from . import connection, effective_capabilities, graph_telemetry, identity_api, agent_gateway_api
from . import registered_protocols as protocols
from . import graph_inspection
from .agent_extension_contracts import canonical, digest, identifier, row

EVENTS = frozenset({"STATE_KEY_ROTATED", "NODE_DEADLINE_EXPIRED", "EXECUTOR_REJECTED", "INPUT_SCHEMA_REJECTED", "BUDGET_BLOCKED", "EDGE_SELECTED", "RETRY_SCHEDULED", "ATTEMPT_FAILED", "LEASE_EXPIRED", "WAIT_EXPIRED", "RUN_CANCELLED", "RUN_PAUSED", "RUN_RESUMED", "MANUAL_RETRY", "ATTEMPT_REASSIGNED", "NODE_SKIPPED", "ROUTE_FORCED", "WAIT_RESOLVED", "RUN_MIGRATED", "ATTEMPT_COMMITTED", "ATTEMPT_CLAIMED", "RUN_CREATED"})
STATES = frozenset({"APPLIED", "PENDING", "RUNNING", "CLAIMED", "SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED", "PAUSED", "WAITING", "READY", "SKIPPED", "REVIEW_REQUIRED", "STALE"})


def projection(run_id, trace):
    event = trace.get("event_type") if trace.get("event_type") in EVENTS else "GRAPH_EVENT"
    state = trace.get("status") if trace.get("status") in STATES else "UNKNOWN"
    trace_id = hashlib.sha256(("graph:" + run_id).encode()).hexdigest()[:32]
    span_id = hashlib.sha256((trace_id + ":" + str(trace["trace_id"])).encode()).hexdigest()[:16]
    timestamp = trace["created_at"]
    from datetime import timezone
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    nanos = str(int(timestamp.timestamp() * 1000000000))
    attributes = [{"key": "graph.run.id", "value": {"stringValue": run_id}},
                  {"key": "graph.event.type", "value": {"stringValue": event}},
                  {"key": "graph.status", "value": {"stringValue": state}}]
    # Explicit allowlist: neither DETAIL_JSON nor state/prompt/result content
    # can enter a standard OTLP field, resource attribute or span name.
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "chuanxu"}}]},
        "scopeSpans": [{"scope": {"name": "chuanxu.graph", "version": "1"}, "spans": [{"traceId": trace_id,
            "spanId": span_id, "name": "chuanxu.graph." + event.lower(), "kind": 1,
            "startTimeUnixNano": nanos, "endTimeUnixNano": nanos, "attributes": attributes,
            "status": {"code": 2 if state == "FAILED" else 1}}]}]}]}


def queue(actor, endpoint_id, outbox_id, trace_id):
    effective_capabilities.require(actor, graph="otel_export")
    def perform(tx):
        record = protocols.endpoint(actor, endpoint_id, kind="OTLP", tx=tx)
        outbox = row(tx.query_one("SELECT RUN_ID FROM GRAPH_OUTBOX WHERE OUTBOX_ID=:outbox", {"outbox": outbox_id}))
        if not outbox:
            raise ValueError("A committed Graph outbox record is required")
        graph_inspection._run(tx, actor, outbox["run_id"])
        trace = row(tx.query_one("SELECT TRACE_ID,EVENT_TYPE,STATUS,CREATED_AT FROM GRAPH_TRACES WHERE TRACE_ID=:trace AND RUN_ID=:run", {"trace": trace_id, "run": outbox.get("run_id")}))
        if not trace:
            raise ValueError("A committed trace from the selected outbox run is required")
        payload = projection(outbox["run_id"], trace)
        destination = endpoint_id + ":" + str(record["current_revision"])
        prior = row(tx.query_one("SELECT d.DELIVERY_ID,p.PROJECTION_DIGEST FROM GRAPH_TELEMETRY_DELIVERIES d JOIN CX_TELEMETRY_PAYLOADS p ON p.DELIVERY_ID=d.DELIVERY_ID WHERE d.OUTBOX_ID=:outbox AND d.DESTINATION_REF=:destination", {"outbox": outbox_id, "destination": destination}))
        if prior:
            if prior["projection_digest"] != digest(payload):
                raise ValueError("Delivery key has different trace metadata")
            return {"delivery_id": prior["delivery_id"], "replayed": True}
        delivery = identifier("GTD")
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        tx.execute("INSERT INTO GRAPH_TELEMETRY_DELIVERIES(DELIVERY_ID,OUTBOX_ID,MAPPING_VERSION,DESTINATION_REF,STATUS,TRACE_ID,SPAN_ID) VALUES(:delivery,:outbox,'otlp-http-1.9.0',:destination,'PENDING',:trace,:span)", {"delivery": delivery, "outbox": outbox_id, "destination": destination, "trace": span["traceId"], "span": span["spanId"]})
        tx.execute("INSERT INTO CX_TELEMETRY_PAYLOADS(DELIVERY_ID,ENDPOINT_ID,REVISION_NO,ACTOR_ID,PROJECTION_JSON,PROJECTION_DIGEST) VALUES(:delivery,:endpoint,:revision,:actor,:payload,:digest)", {"delivery": delivery, "endpoint": endpoint_id, "revision": int(record["current_revision"]), "actor": actor, "payload": canonical(payload), "digest": digest(payload)})
        identity_api._audit_tx(tx, actor, "OTLP_QUEUED", "TELEMETRY_DELIVERY", delivery, "ALLOW", "Committed metadata allowlist")
        return {"delivery_id": delivery, "status": "PENDING", "projection_digest": digest(payload), "replayed": False}
    return connection.execute_transaction_callback(perform)


def _authority(tx, payload):
    effective_capabilities.require(payload["actor_id"], graph="otel_export")
    record = protocols.endpoint(payload["actor_id"], payload["endpoint_id"], kind="OTLP", tx=tx)
    if int(record["current_revision"]) != int(payload["revision_no"]):
        raise PermissionError("Collector registration was replaced")
    delivery = row(tx.query_one("SELECT o.RUN_ID FROM GRAPH_TELEMETRY_DELIVERIES d JOIN GRAPH_OUTBOX o ON o.OUTBOX_ID=d.OUTBOX_ID WHERE d.DELIVERY_ID=:delivery", {"delivery": payload["delivery_id"]}))
    if not delivery:
        raise PermissionError("Telemetry source is unavailable")
    graph_inspection._run(tx, payload["actor_id"], delivery["run_id"])
    return record


def read(actor, delivery_id):
    def perform(tx):
        payload = row(tx.query_one("SELECT * FROM CX_TELEMETRY_PAYLOADS WHERE DELIVERY_ID=:delivery AND ACTOR_ID=:actor", {"delivery": delivery_id, "actor": actor}))
        if not payload:
            raise PermissionError("Delivery access denied")
        _authority(tx, payload)
        return row(tx.query_one("SELECT DELIVERY_ID,STATUS,LAST_ERROR,TRACE_ID,SPAN_ID FROM GRAPH_TELEMETRY_DELIVERIES WHERE DELIVERY_ID=:delivery", {"delivery": delivery_id}))
    return connection.execute_transaction_callback(perform)


def deliver_one():
    attempt_id = identifier("TA")
    def claim(tx):
        candidates = tx.query("SELECT d.DELIVERY_ID FROM GRAPH_TELEMETRY_DELIVERIES d JOIN CX_TELEMETRY_PAYLOADS p ON p.DELIVERY_ID=d.DELIVERY_ID WHERE d.STATUS='PENDING' ORDER BY d.CREATED_AT" + identity_api._limit_clause("page_limit"), {"page_limit": 1})
        if not candidates:
            return None
        delivery = row(candidates[0])["delivery_id"]
        current = row(tx.query_one("SELECT STATUS FROM GRAPH_TELEMETRY_DELIVERIES WHERE DELIVERY_ID=:delivery FOR UPDATE", {"delivery": delivery}))
        if current["status"] != "PENDING":
            return None
        payload = row(tx.query_one("SELECT * FROM CX_TELEMETRY_PAYLOADS WHERE DELIVERY_ID=:delivery", {"delivery": delivery}))
        try:
            record = _authority(tx, payload)
        except PermissionError:
            tx.execute("UPDATE GRAPH_TELEMETRY_DELIVERIES SET STATUS='FAILED',LAST_ERROR='ENDPOINT_REVOKED',UPDATED_AT=CURRENT_TIMESTAMP WHERE DELIVERY_ID=:delivery AND STATUS='PENDING'", {"delivery": delivery})
            identity_api._audit_tx(tx, payload["actor_id"], "OTLP_REJECTED", "TELEMETRY_DELIVERY", delivery, "DENY", "Collector registration is no longer authorized")
            return {"skipped": True, "delivery_id": delivery, "status": "FAILED"}
        try:
            value = json.loads(payload["projection_json"])
        except (TypeError, ValueError):
            value = None
        if not isinstance(value, dict) or digest(value) != payload["projection_digest"]:
            tx.execute("UPDATE GRAPH_TELEMETRY_DELIVERIES SET STATUS='FAILED',LAST_ERROR='PROJECTION_DIGEST_MISMATCH',UPDATED_AT=CURRENT_TIMESTAMP WHERE DELIVERY_ID=:delivery AND STATUS='PENDING'", {"delivery": delivery})
            identity_api._audit_tx(tx, payload["actor_id"], "OTLP_REJECTED", "TELEMETRY_DELIVERY", delivery, "DENY", "Projection integrity check failed")
            return {"skipped": True, "delivery_id": delivery, "status": "FAILED"}
        tx.execute("INSERT INTO CX_TELEMETRY_ATTEMPTS(ATTEMPT_ID,DELIVERY_ID,ENDPOINT_ID,REVISION_NO,ATTEMPT_NO,STATUS,PROJECTION_DIGEST,LEASE_EXPIRES_AT) VALUES(:attempt,:delivery,:endpoint,:revision,1,'SENDING',:digest,:expires)", {"attempt": attempt_id, "delivery": delivery, "endpoint": payload["endpoint_id"], "revision": int(payload["revision_no"]), "digest": payload["projection_digest"], "expires": agent_gateway_api._now() + timedelta(seconds=int(record["timeout_seconds"]) + 15)})
        tx.execute("UPDATE GRAPH_TELEMETRY_DELIVERIES SET STATUS='SENDING',UPDATED_AT=CURRENT_TIMESTAMP WHERE DELIVERY_ID=:delivery", {"delivery": delivery})
        return payload, record, value
    claimed = connection.execute_transaction_callback(claim)
    if not claimed:
        return {"status": "IDLE"}
    if isinstance(claimed, dict) and claimed.get("skipped"):
        return {"delivery_id": claimed["delivery_id"], "status": claimed["status"]}
    payload, record, value = claimed
    state, code, http_status = "UNOBSERVED", None, None
    try:
        def last_check(tx):
            _authority(tx, payload)
            if not tx.query_one("SELECT ATTEMPT_ID FROM CX_TELEMETRY_ATTEMPTS WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP", {"attempt": attempt_id}):
                raise PermissionError("Telemetry lease expired")
        connection.execute_transaction_callback(last_check)
        result, _, http_status = protocols.post(record, value, return_status=True)
        # OTLP collectors may acknowledge asynchronously with 202 and no
        # response body.  A response-level acknowledgement is still an
        # observed delivery; only a transport timeout/connection failure is
        # uncertain.
        if int(http_status or 0) == 202:
            state = "DELIVERED"
        elif not isinstance(result, dict):
            raise ValueError("Collector did not return its OTLP response")
        else:
            partial = result.get("partialSuccess") or {}
            if int(partial.get("rejectedSpans", 0)) or partial.get("errorMessage"):
                state, code = "FAILED", "COLLECTOR_REJECTED"
            else:
                state = "DELIVERED"
    except urllib.error.HTTPError as exc:
        http_status, code = int(exc.code), "HTTP_" + str(int(exc.code))
        # HTTP status is an observed collector response.  Both client and
        # server errors are failed deliveries; uncertain is reserved for no
        # response at all.
        state = "FAILED"
    except Exception:
        code = "TRANSPORT_UNOBSERVED"
    def finish(tx):
        final = state
        try:
            _authority(tx, payload)
            if not tx.query_one("SELECT ATTEMPT_ID FROM CX_TELEMETRY_ATTEMPTS WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING' AND LEASE_EXPIRES_AT>CURRENT_TIMESTAMP", {"attempt": attempt_id}):
                final = "UNOBSERVED"
        except PermissionError:
            final = "UNOBSERVED"
        tx.execute("UPDATE CX_TELEMETRY_ATTEMPTS SET STATUS=:state,HTTP_STATUS=:http_status,ERROR_CODE=:code,COMPLETED_AT=CURRENT_TIMESTAMP WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING'", {"state": final, "http_status": http_status, "code": code, "attempt": attempt_id})
        tx.execute("UPDATE GRAPH_TELEMETRY_DELIVERIES SET STATUS=:state,LAST_ERROR=:code,UPDATED_AT=CURRENT_TIMESTAMP WHERE DELIVERY_ID=:delivery AND STATUS='SENDING'", {"state": final, "code": code, "delivery": payload["delivery_id"]})
        identity_api._audit_tx(tx, payload["actor_id"], "OTLP_OBSERVED", "TELEMETRY_DELIVERY", payload["delivery_id"], "ALLOW" if final == "DELIVERED" else "DENY", final)
        return {"delivery_id": payload["delivery_id"], "status": final, "projection_digest": payload["projection_digest"]}
    return connection.execute_transaction_callback(finish)


def reconcile():
    def perform(tx):
        expired = tx.query("SELECT ATTEMPT_ID,DELIVERY_ID FROM CX_TELEMETRY_ATTEMPTS WHERE STATUS='SENDING' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP ORDER BY STARTED_AT" + identity_api._limit_clause("page_limit"), {"page_limit": 100})
        for item in expired:
            item = row(item)
            tx.execute("UPDATE CX_TELEMETRY_ATTEMPTS SET STATUS='UNOBSERVED',ERROR_CODE='EXPIRED_SEND',COMPLETED_AT=CURRENT_TIMESTAMP WHERE ATTEMPT_ID=:attempt AND STATUS='SENDING'", {"attempt": item["attempt_id"]})
            tx.execute("UPDATE GRAPH_TELEMETRY_DELIVERIES SET STATUS='UNOBSERVED',LAST_ERROR='EXPIRED_SEND',UPDATED_AT=CURRENT_TIMESTAMP WHERE DELIVERY_ID=:delivery AND STATUS='SENDING'", {"delivery": item["delivery_id"]})
        return len(expired)
    return connection.execute_transaction_callback(perform)
