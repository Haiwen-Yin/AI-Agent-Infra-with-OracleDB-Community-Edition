"""Read-only governance projections for v4.4.8 platform maintenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from . import connection, identity_api, platform_agent_pool


def _row(row: Any) -> Dict[str, Any]:
    return {str(key).lower(): value for key, value in dict(row or {}).items()}


def _count(sql: str, params: Dict[str, Any] | None = None) -> int:
    try:
        return int(_row(connection.execute_query_one(sql, params)).get("cnt") or 0)
    except Exception:
        return 0


def _require_manage(actor: str) -> None:
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform governance graph permission denied")


def governance_projection(actor: str, refresh_interval_seconds: int = 3) -> Dict[str, Any]:
    """Build a demand-refreshed dependency and blast-radius projection."""
    _require_manage(actor)
    interval = int(refresh_interval_seconds)
    if interval not in {1, 3, 5, 10}:
        raise ValueError("refresh interval must be 1, 3, 5, or 10 seconds")

    nodes = [
        {"key": "platform", "label": "Platform control plane", "group": "control"},
        {"key": "admin_agents", "label": "Admin Agent group", "group": "control"},
        {"key": "agent_pool", "label": "Agent Pool nodes", "group": "runtime"},
        {"key": "llm", "label": "LLM profiles", "group": "model"},
        {"key": "embedding", "label": "Embedding contracts", "group": "model"},
        {"key": "graph", "label": "Graph Runtime", "group": "runtime"},
        {"key": "compliance", "label": "Compliance posture", "group": "governance"},
    ]
    edges = [
        {"source": "platform", "target": "admin_agents"},
        {"source": "platform", "target": "agent_pool"},
        {"source": "agent_pool", "target": "llm"},
        {"source": "agent_pool", "target": "graph"},
        {"source": "platform", "target": "embedding"},
        {"source": "platform", "target": "compliance"},
    ]
    metrics = {
        "admin_members": _count("SELECT COUNT(*) AS CNT FROM CX_ADMIN_AGENT_MEMBERS WHERE STATUS='ACTIVE'"),
        "managed_nodes": _count("SELECT COUNT(*) AS CNT FROM CX_MANAGED_NODES WHERE STATUS IN ('ACTIVE','VALIDATED')"),
        "runtime_executions": _count("SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE STATUS IN ('PENDING','CLAIMED','RUNNING','STREAMING','WAITING')"),
        "active_llm_profiles": _count("SELECT COUNT(*) AS CNT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE'"),
        "healthy_llm_profiles": _count("SELECT COUNT(*) AS CNT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE' AND HEALTH_STATE='HEALTHY'"),
        "active_graph_runs": _count("SELECT COUNT(*) AS CNT FROM GRAPH_RUNS WHERE STATUS IN ('RUNNING','WAITING','MIGRATING')"),
        "maintenance_tasks": _count("SELECT COUNT(*) AS CNT FROM CX_PLATFORM_MAINTENANCE_TASKS WHERE STATUS IN ('DISCOVERED','ANALYZED','PROPOSED','AUTHORIZED','EXECUTING','VERIFYING')"),
        "noncompliant_postures": _count("SELECT COUNT(*) AS CNT FROM CX_AGENT_POSTURES WHERE POSTURE_STATE='NON_COMPLIANT'"),
    }
    return {
        "kind": "PLATFORM_GOVERNANCE_PROJECTION",
        "read_only": True,
        "refresh_interval_seconds": interval,
        "fresh_at": datetime.now(timezone.utc).isoformat(),
        "safe_autonomy": platform_agent_pool.safe_autonomy_policy(),
        "metrics": metrics,
        "nodes": nodes,
        "edges": edges,
    }
