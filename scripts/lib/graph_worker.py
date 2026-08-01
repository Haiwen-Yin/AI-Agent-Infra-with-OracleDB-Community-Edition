"""Pull-based Graph Worker protocol shared by platform and external Agents."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import graph_runtime


def advertise(worker_id: str, runtime: str, capabilities: Optional[List[str]] = None,
              agent_id: Optional[str] = None, node_id: Optional[str] = None) -> Dict[str, Any]:
    if not graph_runtime.register_worker(worker_id, runtime, capabilities, agent_id, node_id):
        raise PermissionError("worker is disabled or revoked")
    return {
        "worker_id": worker_id,
        "runtime": runtime,
        "capabilities": capabilities or [],
        "protocol": "graph-worker/1",
        "pull": True,
    }


def claim(worker_id: str, runtime: str, capabilities: Optional[List[str]] = None,
          lease_seconds: int = 120, agent_id: Optional[str] = None,
          node_id: Optional[str] = None, node_key: Optional[str] = None,
          scheduler_id: Optional[str] = None,
          scheduler_lease: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return graph_runtime.claim_ready(
        worker_id, runtime, capabilities, lease_seconds, agent_id, node_id, node_key,
        scheduler_id, scheduler_lease,
    )


def heartbeat(lease_token: str, lease_seconds: int = 120) -> bool:
    return graph_runtime.heartbeat(lease_token, lease_seconds)


def checkpoint(lease_token: str, delta: Dict[str, Any], actor_id: str,
               reducer_evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lease = graph_runtime._verify_lease(lease_token, "checkpoint")
    if not lease:
        raise PermissionError("invalid, expired, or revoked lease token")
    return graph_runtime.append_checkpoint(
        lease["run_id"], delta, actor_id, lease["attempt_id"], "DELTA", reducer_evidence
    )


def complete(lease_token: str, output_state: Optional[Dict[str, Any]], actor_id: str,
             evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return graph_runtime.complete_attempt(lease_token, output_state, actor_id, evidence)


def fail(lease_token: str, error_code: str, error_message: str, actor_id: str) -> bool:
    return graph_runtime.fail_attempt(lease_token, error_code, error_message, actor_id)


def revoke(lease_token: str, actor_id: str, reason: str) -> bool:
    if not reason:
        raise ValueError("lease revocation reason is required")
    lease = graph_runtime._verify_lease(lease_token, "heartbeat")
    if not lease:
        return False
    from . import connection
    return connection.execute(
        "UPDATE GRAPH_LEASE_TOKENS SET REVOKED_AT = CURRENT_TIMESTAMP WHERE LEASE_ID = :lease_id",
        {"lease_id": lease["lease_id"]},
    ) > 0
