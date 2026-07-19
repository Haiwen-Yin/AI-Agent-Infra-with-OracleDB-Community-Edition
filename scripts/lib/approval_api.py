"""AI Agent Infra v4.0.0 - Enterprise Edition - Approval API

Unified approval management for Human-in-the-Loop workflows.
Supports three entity types: STEP (orchestrator), LOOP (loop runs), TOOL (tool calls).

Table: APPROVAL_REQUESTS
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)

logger = logging.getLogger(__name__)


def create_request(
    entity_type: str,
    entity_id: str,
    requested_by: str,
) -> Optional[str]:
    """Create an approval request for a step, loop, or tool call.

    Args:
        entity_type: 'STEP', 'LOOP', or 'TOOL'
        entity_id: The ID of the entity requiring approval
        requested_by: Agent ID that requested the approval

    Returns: approval_id or None on failure
    """
    try:
        from .event_bus import publish_event
    except ImportError:
        publish_event = None

    approval_id = execute_insert_returning_id(
        """INSERT INTO APPROVAL_REQUESTS (APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY)
           VALUES (RAWTOHEX(SYS_GUID()), :etype, :eid, :rby)
           RETURNING APPROVAL_ID INTO :ret_id""",
        {"etype": entity_type, "eid": entity_id, "rby": requested_by},
    )

    if approval_id and publish_event:
        try:
            publish_event(
                event_type="APPROVAL_REQUIRED",
                source_id=requested_by,
                source_type="AGENT",
                payload={"approval_id": approval_id, "entity_type": entity_type, "entity_id": entity_id},
            )
        except Exception:
            pass

    logger.info("Approval request created: %s for %s:%s", approval_id, entity_type, entity_id)
    return approval_id


def approve(approval_id: str, approver: str) -> bool:
    """Approve a pending request."""
    result = execute(
        """UPDATE APPROVAL_REQUESTS
           SET APPROVAL_STATUS = 'APPROVED', APPROVED_BY = :approver, APPROVED_AT = SYSTIMESTAMP
           WHERE APPROVAL_ID = :aid AND APPROVAL_STATUS = 'PENDING'""",
        {"approver": approver, "aid": approval_id},
    )
    if result > 0:
        _notify_entity_approval(approval_id, "APPROVED")
        logger.info("Approval %s approved by %s", approval_id, approver)
    return result > 0


def reject(approval_id: str, approver: str, reason: str = "") -> bool:
    """Reject a pending request."""
    result = execute(
        """UPDATE APPROVAL_REQUESTS
           SET APPROVAL_STATUS = 'REJECTED', APPROVED_BY = :approver, APPROVED_AT = SYSTIMESTAMP,
               REJECT_REASON = :reason
           WHERE APPROVAL_ID = :aid AND APPROVAL_STATUS = 'PENDING'""",
        {"approver": approver, "reason": reason, "aid": approval_id},
    )
    if result > 0:
        _notify_entity_approval(approval_id, "REJECTED")
        logger.info("Approval %s rejected by %s: %s", approval_id, approver, reason)
    return result > 0


def get_request(approval_id: str) -> Optional[Dict[str, Any]]:
    """Get a single approval request by ID."""
    row = execute_query_one(
        """SELECT APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY,
                  APPROVAL_STATUS, APPROVED_BY, APPROVED_AT, REJECT_REASON, CREATED_AT
           FROM APPROVAL_REQUESTS WHERE APPROVAL_ID = :aid""",
        {"aid": approval_id},
    )
    return sanitize_row(row) if row else None


def list_pending(entity_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List all pending approval requests, optionally filtered by entity type."""
    if entity_type:
        rows = execute_query(
            """SELECT APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY,
                      APPROVAL_STATUS, CREATED_AT
               FROM APPROVAL_REQUESTS
               WHERE APPROVAL_STATUS = 'PENDING' AND ENTITY_TYPE = :etype
               ORDER BY CREATED_AT DESC
               FETCH FIRST :limit ROWS ONLY""",
            {"etype": entity_type, "limit": limit},
        )
    else:
        rows = execute_query(
            """SELECT APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY,
                      APPROVAL_STATUS, CREATED_AT
               FROM APPROVAL_REQUESTS
               WHERE APPROVAL_STATUS = 'PENDING'
               ORDER BY CREATED_AT DESC
               FETCH FIRST :limit ROWS ONLY""",
            {"limit": limit},
        )
    return [sanitize_row(r) for r in rows] if rows else []


def list_all(limit: int = 100) -> List[Dict[str, Any]]:
    """List all approval requests (all statuses)."""
    rows = execute_query(
        """SELECT APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY,
                  APPROVAL_STATUS, APPROVED_BY, APPROVED_AT, REJECT_REASON, CREATED_AT
           FROM APPROVAL_REQUESTS
           ORDER BY CREATED_AT DESC
           FETCH FIRST :limit ROWS ONLY""",
        {"limit": limit},
    )
    return [sanitize_row(r) for r in rows] if rows else []


def check_approval_needed(entity_type: str, entity_id: str) -> bool:
    """Check if an entity requires approval before execution.

    For STEP: checks STEP_EXECUTION_PLAN.REQUIRES_APPROVAL
    For LOOP: checks LOOP_META.REQUIRE_APPROVAL
    For TOOL: checks TOOL_REGISTRY.REQUIRES_APPROVAL
    """
    if entity_type == "STEP":
        row = execute_query_one(
            "SELECT REQUIRES_APPROVAL FROM STEP_EXECUTION_PLAN WHERE PLAN_ID = :eid",
            {"eid": entity_id},
        )
        return row and row.get("requires_approval") == "Y"
    elif entity_type == "LOOP":
        row = execute_query_one(
            "SELECT REQUIRE_APPROVAL FROM LOOP_META WHERE LOOP_ID = :eid",
            {"eid": entity_id},
        )
        return row and row.get("require_approval") == "Y"
    elif entity_type == "TOOL":
        row = execute_query_one(
            "SELECT REQUIRES_APPROVAL FROM TOOL_REGISTRY WHERE TOOL_ID = :eid",
            {"eid": entity_id},
        )
        return row and row.get("requires_approval") == "Y"
    return False


def get_pending_for_entity(entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Get the pending approval request for a specific entity, if any."""
    row = execute_query_one(
        """SELECT APPROVAL_ID, APPROVAL_STATUS, REQUESTED_BY, CREATED_AT
           FROM APPROVAL_REQUESTS
           WHERE ENTITY_TYPE = :etype AND ENTITY_ID = :eid
             AND APPROVAL_STATUS = 'PENDING'
           ORDER BY CREATED_AT DESC
           FETCH FIRST 1 ROWS ONLY""",
        {"etype": entity_type, "eid": entity_id},
    )
    return sanitize_row(row) if row else None


def _notify_entity_approval(approval_id: str, decision: str):
    """Publish an event when an approval is decided."""
    try:
        from .event_bus import publish_event
        req = get_request(approval_id)
        if req:
            publish_event(
                event_type="APPROVAL_DECIDED",
                source_id=req.get("approved_by", "system"),
                source_type="AGENT",
                payload={
                    "approval_id": approval_id,
                    "entity_type": req.get("entity_type"),
                    "entity_id": req.get("entity_id"),
                    "decision": decision,
                },
            )
    except Exception:
        pass


def get_stats() -> Dict[str, Any]:
    """Get approval statistics."""
    rows = execute_query(
        """SELECT APPROVAL_STATUS, COUNT(*) AS cnt
           FROM APPROVAL_REQUESTS
           GROUP BY APPROVAL_STATUS""",
        {},
    )
    stats = {"total": 0, "pending": 0, "approved": 0, "rejected": 0}
    if rows:
        for r in rows:
            status = r.get("approval_status", "").lower()
            count = r.get("cnt", 0)
            stats[status] = count
            stats["total"] += count
    return stats


# ---------------------------------------------------------------------------
# D5: Approval SLA + Notifications
# ---------------------------------------------------------------------------

def _ensure_sla_columns() -> None:
    """Add SLA_DEADLINE and SLA_ESCALATE_TO columns to APPROVAL_REQUESTS if missing."""
    try:
        execute("ALTER TABLE APPROVAL_REQUESTS ADD (SLA_DEADLINE TIMESTAMP)", {})
    except Exception:
        pass
    try:
        execute("ALTER TABLE APPROVAL_REQUESTS ADD (SLA_ESCALATE_TO VARCHAR2(64))", {})
    except Exception:
        pass


def set_sla(approval_id: str, deadline_hours: float, escalate_to: str) -> bool:
    """Set SLA_DEADLINE = SYSTIMESTAMP + deadline_hours and SLA_ESCALATE_TO."""
    if deadline_hours <= 0:
        raise ValueError("deadline_hours must be positive")
    _ensure_sla_columns()
    try:
        # Build the interval clause in SQL so it is timezone-correct.
        # Use NUMTODSINTERVAL for fractional hours.
        result = execute(
            """UPDATE APPROVAL_REQUESTS
                  SET SLA_DEADLINE = SYSTIMESTAMP + NUMTODSINTERVAL(:hours, 'HOUR'),
                      SLA_ESCALATE_TO = :escal
                WHERE APPROVAL_ID = :aid AND APPROVAL_STATUS = 'PENDING'""",
            {"hours": deadline_hours, "escal": escalate_to, "aid": approval_id},
        )
        return result > 0
    except Exception as e:
        logger.warning("Failed to set SLA for approval %s: %s", approval_id, e)
        return False


def check_sla_overdue() -> List[Dict[str, Any]]:
    """Find overdue PENDING approvals and escalate them.

    Returns the list of escalated approvals.
    """
    _ensure_sla_columns()
    try:
        rows = execute_query(
            """SELECT APPROVAL_ID, ENTITY_TYPE, ENTITY_ID, REQUESTED_BY,
                      SLA_DEADLINE, SLA_ESCALATE_TO
                 FROM APPROVAL_REQUESTS
                WHERE APPROVAL_STATUS = 'PENDING'
                  AND SLA_DEADLINE IS NOT NULL
                  AND SLA_DEADLINE < SYSTIMESTAMP
                  AND (SLA_ESCALATE_TO IS NOT NULL)""",
            {},
        )
    except Exception as e:
        logger.warning("SLA overdue query failed: %s", e)
        return []

    escalated: List[Dict[str, Any]] = []
    for r in rows:
        approval_id = r.get("approval_id")
        escalate_to = r.get("sla_escalate_to")
        try:
            # Publish an escalation event; if event_bus unavailable, swallow.
            try:
                from .event_bus import publish_event
                publish_event(
                    event_type="APPROVAL_SLA_OVERDUE",
                    source_id=escalate_to,
                    source_type="AGENT",
                    payload={
                        "approval_id": approval_id,
                        "entity_type": r.get("entity_type"),
                        "entity_id": r.get("entity_id"),
                        "escalated_to": escalate_to,
                    },
                )
            except Exception:
                pass

            # Update SLA_ESCALATE_TO with an "ESCALATED:" marker to avoid re-escalation loops.
            execute(
                """UPDATE APPROVAL_REQUESTS
                      SET SLA_ESCALATE_TO = 'ESCALATED:' || :escal
                    WHERE APPROVAL_ID = :aid""",
                {"escal": escalate_to or "", "aid": approval_id},
            )
            escalated.append(sanitize_row(r))
            logger.info("Approval %s escalated to %s (SLA overdue)",
                        approval_id, escalate_to)
        except Exception as e:
            logger.warning("Failed to escalate approval %s: %s", approval_id, e)

    return escalated


def get_sla_stats() -> Dict[str, Any]:
    """Return counts of pending / overdue / escalated approvals."""
    _ensure_sla_columns()
    stats = {"pending": 0, "overdue": 0, "escalated": 0}
    try:
        row = execute_query_one(
            """SELECT
                  SUM(CASE WHEN APPROVAL_STATUS = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN APPROVAL_STATUS = 'PENDING'
                            AND SLA_DEADLINE IS NOT NULL
                            AND SLA_DEADLINE < SYSTIMESTAMP THEN 1 ELSE 0 END) AS overdue,
                  SUM(CASE WHEN APPROVAL_STATUS = 'PENDING'
                            AND SLA_ESCALATE_TO LIKE 'ESCALATED:%' THEN 1 ELSE 0 END) AS escalated
                 FROM APPROVAL_REQUESTS""",
            {},
        )
        if row:
            stats["pending"] = int(row.get("pending", 0) or 0)
            stats["overdue"] = int(row.get("overdue", 0) or 0)
            stats["escalated"] = int(row.get("escalated", 0) or 0)
    except Exception as e:
        logger.warning("SLA stats query failed: %s", e)
    return stats
