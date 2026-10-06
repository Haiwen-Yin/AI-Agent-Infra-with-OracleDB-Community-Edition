"""One database-authoritative capability decision for product entry points."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import graph_production_profile, identity_api, model_capability_api


def graph_operation(path: str) -> Optional[str]:
    normalized = "/" + str(path or "").lstrip("/")
    graph_route = normalized.startswith(("/api/graph/", "/api/graphs", "/api/graph-"))
    if graph_route and normalized.endswith(("/offline-replay", "/migration-preflight", "/import-preview")):
        return "graph_inspection"
    if normalized.startswith("/api/a2a"):
        return "a2a_gateway"
    if normalized.startswith("/api/telemetry"):
        return "otel_export"
    # Authoring a draft is not migration of a running Graph.
    if normalized.startswith("/api/graph-dynamic/proposals"):
        return "graph_manifest_draft_import"
    if graph_route and normalized.endswith("/migrate"):
        return "graph_dynamic_migration"
    if graph_route and normalized.endswith("/replay"):
        return "graph_replay"
    if graph_route and normalized.endswith("/fork"):
        return "graph_checkpoint_fork"
    if normalized.startswith("/api/graph-assurance"):
        return "graph_slo_readonly"
    if (normalized.startswith(("/api/graph-manifest", "/api/graph-compat"))
            or normalized.startswith("/api/graphs/") and normalized.endswith("/import")):
        return "graph_manifest_draft_import"
    if graph_route:
        return "graph_runtime_core"
    return None


def authorize(actor: str, action: str = "platform.manage") -> Dict[str, Any]:
    if not str(actor or "").strip():
        raise PermissionError("An authenticated Principal is required")
    access = identity_api.effective_access(str(actor), action)
    if access.get("decision") != "ALLOW":
        raise PermissionError("Current Principal authorization denies this operation")
    return access


def require(actor: str, *, graph: str = "", model: str = "",
            action: str = "platform.manage", impact: str = "READ",
            proposal: bool = False, approved_binding: bool = False) -> Dict[str, Any]:
    """Check fresh capability state and authority, never a runtime-profile label.

    A caller receiving a permitted proposal still has no executor approval.
    Concrete resource, credential and lease checks belong to the dispatching
    service and must be performed again immediately before the actual send.
    """
    authorize(actor, action)
    result: Dict[str, Any] = {"decision": "ALLOW", "action": action, "impact": impact}
    if graph:
        state = graph_production_profile.state(graph)
        controlled = state == "CONTROLLED" and (
            action == "platform.manage" or
            approved_binding and graph == "a2a_gateway" and action == "agents.operate" or
            identity_api.effective_access(str(actor), "platform.manage").get("decision") == "ALLOW"
        )
        graph_production_profile.require(graph, controlled=controlled)
        result["graph_state"] = state
    if model:
        state = model_capability_api.state(model)
        if state == "OFF" or (state == "READ_ONLY" and impact != "READ"):
            raise PermissionError("Model/protocol capability denies this operation: " + model)
        if state == "PROPOSAL_ONLY" and not proposal:
            raise PermissionError("This capability permits proposals only: " + model)
        result["model_state"] = state
        if proposal:
            result["decision"] = "PROPOSAL"
    return result


def graph_available(key: str) -> bool:
    """Informational availability; dispatch still needs require() and resources."""
    return graph_production_profile.state(key) in {"ENABLED", "CONTROLLED"}
