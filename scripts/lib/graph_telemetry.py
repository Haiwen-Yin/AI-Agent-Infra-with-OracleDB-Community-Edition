"""Redacted OpenTelemetry GenAI projection for committed Graph facts."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Iterable, Optional

from . import connection, profile_api


MAPPING_VERSION = "otel-genai-preview-2026-08-03"
PREVIEW_PROFILES = frozenset({"development", "experimental-4.2"})
SENSITIVE = frozenset({"prompt", "completion", "output", "state", "secret", "credential", "token", "password", "artifact", "memory"})


def enabled() -> bool:
    return profile_api.current_profile() in PREVIEW_PROFILES


def require_enabled() -> None:
    if not enabled():
        raise PermissionError("OTLP export is disabled by the active runtime profile")


def redact_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if any(term in str(key).lower() for term in SENSITIVE) else redact_metadata(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    if isinstance(value, (str, bytes)):
        return "[REDACTED]"
    return value


def project_trace(run_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Map metadata only, retaining correlation but excluding payload bodies."""
    trace_id = hashlib.sha256(("graph:" + str(run_id)).encode("utf-8")).hexdigest()[:32]
    span_id = hashlib.sha256((trace_id + ":" + str(event.get("trace_id") or event.get("event_type") or "")).encode("utf-8")).hexdigest()[:16]
    attributes = redact_metadata({
        "graph.run.id": run_id, "graph.event.type": event.get("event_type"), "graph.status": event.get("status"),
        "graph.node.key": event.get("node_key"), "graph.attempt.id": event.get("attempt_id"),
        "gen_ai.usage.input_tokens": event.get("input_token_count"), "gen_ai.usage.output_tokens": event.get("output_token_count"),
    })
    return {"mapping_version": MAPPING_VERSION, "trace_id": trace_id, "span_id": span_id,
            "name": "chuanxu.graph." + str(event.get("event_type") or "event").lower(), "attributes": attributes}


def queue_delivery(outbox_id: str, destination_ref: str, projection: Dict[str, Any]) -> str:
    require_enabled()
    if not str(outbox_id or "").strip() or not str(destination_ref or "").strip():
        raise ValueError("OTLP outbox and destination are required")
    delivery_id = "GTD_" + uuid.uuid4().hex
    connection.execute(
        "INSERT INTO GRAPH_TELEMETRY_DELIVERIES (DELIVERY_ID, OUTBOX_ID, MAPPING_VERSION, DESTINATION_REF, STATUS, TRACE_ID, SPAN_ID, CREATED_AT, UPDATED_AT) "
        "VALUES (:delivery_id, :outbox_id, :mapping_version, :destination_ref, 'PENDING', :trace_id, :span_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"delivery_id": delivery_id, "outbox_id": outbox_id, "mapping_version": MAPPING_VERSION,
         "destination_ref": destination_ref[:512], "trace_id": projection.get("trace_id"), "span_id": projection.get("span_id")},
    )
    return delivery_id
