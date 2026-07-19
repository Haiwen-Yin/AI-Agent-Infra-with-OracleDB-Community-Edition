"""AI Agent Infra v4.0.0 - Enterprise Edition - Context Audit API

Rule engine + semantic similarity analysis for context audit.
Enterprise-only feature.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    sanitize_row,
)
from .config import load_config

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"violation_detail"}
_AUDIT_TYPES = {"RULE_VIOLATION", "CONTEXT_SIMILARITY", "IDLE_PATTERN", "ACCESS_ANOMALY", "DATA_LEAK"}
_RESOLUTION_STATUSES = {"OPEN", "ACKNOWLEDGED", "RESOLVED", "FALSE_POSITIVE", "ESCALATED"}


def log_audit_event(
    entity_id: str,
    entity_type: str,
    audit_type: str,
    rule_id: Optional[str] = None,
    similarity_score: Optional[float] = None,
    threshold_score: Optional[float] = None,
    violation_detail: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> str:
    if audit_type not in _AUDIT_TYPES:
        raise ValueError(f"Invalid audit_type: {audit_type}. Must be one of {_AUDIT_TYPES}")
    import uuid as _uuid
    audit_id = f"AUD_{_uuid.uuid4().hex[:24]}"
    try:
        execute(
            """INSERT INTO CONTEXT_AUDIT_LOG (
                AUDIT_ID, ENTITY_ID, ENTITY_TYPE, AUDIT_TYPE,
                RULE_ID, SIMILARITY_SCORE, THRESHOLD_SCORE, VIOLATION_DETAIL,
                AGENT_ID, SESSION_ID, WORKSPACE_ID
            ) VALUES (
                :audit_id, :entity_id, :entity_type, :audit_type,
                :rule_id, :sim_score, :thresh_score, :violation_detail,
                :agent_id, :session_id, :workspace_id
            )""",
            {
                "audit_id": audit_id, "entity_id": entity_id, "entity_type": entity_type,
                "audit_type": audit_type, "rule_id": rule_id,
                "sim_score": similarity_score, "thresh_score": threshold_score,
                "violation_detail": violation_detail, "agent_id": agent_id,
                "session_id": session_id, "workspace_id": workspace_id,
            }
        )
    except Exception as e:
        logger.debug(f"log_audit_event: CONTEXT_AUDIT_LOG unavailable: {e}")
    return audit_id


def get_audit_events(
    resolution_status: Optional[str] = None,
    audit_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if resolution_status and resolution_status not in _RESOLUTION_STATUSES:
        raise ValueError(f"Invalid resolution_status: {resolution_status}")
    if audit_type and audit_type not in _AUDIT_TYPES:
        raise ValueError(f"Invalid audit_type: {audit_type}")

    sql = """SELECT AUDIT_ID, ENTITY_ID, ENTITY_TYPE, AUDIT_TYPE, RULE_ID,
             SIMILARITY_SCORE, THRESHOLD_SCORE, VIOLATION_DETAIL,
             AGENT_ID, SESSION_ID, WORKSPACE_ID, RESOLUTION_STATUS,
             RESOLVED_BY, RESOLVED_AT, CREATED_AT
             FROM CONTEXT_AUDIT_LOG WHERE 1=1"""
    params = {}
    idx = 1

    if resolution_status:
        params[f"p{idx}"] = resolution_status
        sql += f" AND RESOLUTION_STATUS = :p{idx}"
        idx += 1
    if audit_type:
        params[f"p{idx}"] = audit_type
        sql += f" AND AUDIT_TYPE = :p{idx}"
        idx += 1

    sql += " ORDER BY CREATED_AT DESC"
    sql += f" FETCH FIRST {min(limit, 1000)} ROWS ONLY"

    try:
        rows = execute_query(sql, params if params else None)
    except Exception as e:
        logger.debug(f"get_audit_events: CONTEXT_AUDIT_LOG unavailable: {e}")
        return []
    return [sanitize_row(r) for r in rows]


def get_audit_event(audit_id: str) -> Optional[Dict[str, Any]]:
    try:
        row = execute_query_one(
            """SELECT AUDIT_ID, ENTITY_ID, ENTITY_TYPE, AUDIT_TYPE, RULE_ID,
               SIMILARITY_SCORE, THRESHOLD_SCORE, VIOLATION_DETAIL,
               AGENT_ID, SESSION_ID, WORKSPACE_ID, RESOLUTION_STATUS,
               RESOLVED_BY, RESOLVED_AT, CREATED_AT
               FROM CONTEXT_AUDIT_LOG WHERE AUDIT_ID = :aid""",
            {"aid": audit_id}
        )
    except Exception as e:
        logger.debug(f"get_audit_event: CONTEXT_AUDIT_LOG unavailable: {e}")
        return None
    return sanitize_row(row) if row else None


def resolve_audit_event(
    audit_id: str,
    resolution_status: str,
    resolved_by: str,
) -> bool:
    if resolution_status not in _RESOLUTION_STATUSES:
        raise ValueError(f"Invalid resolution_status: {resolution_status}")
    existing = get_audit_event(audit_id)
    if not existing:
        return False
    try:
        execute(
            """UPDATE CONTEXT_AUDIT_LOG
               SET RESOLUTION_STATUS = :status, RESOLVED_BY = :resolved_by, RESOLVED_AT = CURRENT_TIMESTAMP
               WHERE AUDIT_ID = :aid""",
            {"status": resolution_status, "resolved_by": resolved_by, "aid": audit_id}
        )
    except Exception as e:
        logger.debug(f"resolve_audit_event: CONTEXT_AUDIT_LOG unavailable: {e}")
        return False
    return True


def evaluate_rules(
    entity_id: str,
    entity_type: str,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> int:
    try:
        entity = execute_query_one(
            "SELECT WORKSPACE_ID, VISIBILITY, CATEGORY FROM ENTITIES WHERE ENTITY_ID = :eid AND ENTITY_TYPE = :etype",
            {"eid": entity_id, "etype": entity_type}
        )
        if not entity:
            return 0

        try:
            rules = execute_query(
                "SELECT RULE_ID, RULE_NAME, RULE_TYPE, CONDITION_EXPR, SEVERITY FROM CONTEXT_AUDIT_RULES WHERE IS_ENABLED = 'Y'"
            )
        except Exception as e:
            logger.debug(f"evaluate_rules: CONTEXT_AUDIT_RULES unavailable: {e}")
            return 0
    except Exception as e:
        logger.debug(f"evaluate_rules failed: {e}")
        return 0

    violation_count = 0
    for rule in rules:
        triggered = False

        if rule.get("RULE_TYPE") == "CROSS_BOUNDARY" and agent_id:
            agent = execute_query_one(
                "SELECT WORKSPACE_ID FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
                {"aid": agent_id}
            )
            if (agent and entity["WORKSPACE_ID"] and agent["WORKSPACE_ID"]
                    and entity["WORKSPACE_ID"] != agent["WORKSPACE_ID"]
                    and entity["VISIBILITY"] == "PRIVATE"):
                triggered = True

        elif rule.get("RULE_TYPE") == "IDLE_DETECTION" and agent_id:
            config = load_config()
            timeout = getattr(config, 'enterprise', None)
            idle_min = 60
            if timeout:
                idle_min = getattr(timeout, 'audit_idle_timeout_min', 60)
            agent_row = execute_query_one(
                "SELECT LAST_SEEN_AT FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
                {"aid": agent_id}
            )
            if agent_row and agent_row["LAST_SEEN_AT"]:
                elapsed = datetime.utcnow() - agent_row["LAST_SEEN_AT"].replace(tzinfo=None)
                if elapsed > timedelta(minutes=idle_min):
                    triggered = True

        if triggered:
            violation_count += 1
            log_audit_event(
                entity_id=entity_id,
                entity_type=entity_type,
                audit_type="RULE_VIOLATION",
                rule_id=rule["RULE_ID"],
                violation_detail=f"{rule['RULE_NAME']}: {rule['CONDITION_EXPR']}",
                agent_id=agent_id,
                workspace_id=workspace_id,
            )

    return violation_count


def check_context_similarity(
    entity_id: str,
    entity_type: str,
    threshold: Optional[float] = None,
    agent_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if threshold is None:
        config = load_config()
        ent_cfg = getattr(config, 'enterprise', None)
        threshold = 0.40
        if ent_cfg:
            threshold = getattr(ent_cfg, 'audit_threshold_score', 0.40)

    from .embedding_api import search_similar
    similar = search_similar(entity_id, entity_type=entity_type, top_k=10)

    violations = []
    for match in similar:
        score = match.get("score", 0)
        if score >= threshold and match.get("entity_id") != entity_id:
            audit_id = log_audit_event(
                entity_id=entity_id,
                entity_type=entity_type,
                audit_type="CONTEXT_SIMILARITY",
                rule_id="RULE_SIMILARITY_THRESHOLD",
                similarity_score=score,
                threshold_score=threshold,
                violation_detail=(
                    f"Entity {entity_id} similar to {match.get('entity_id')} "
                    f"(score={score:.4f}, threshold={threshold:.4f})"
                ),
                agent_id=agent_id,
                workspace_id=workspace_id,
            )
            violations.append({
                "audit_id": audit_id,
                "matched_entity_id": match.get("entity_id"),
                "similarity_score": score,
                "threshold": threshold,
            })

    return violations


def get_audit_stats(since: Optional[datetime] = None) -> Dict[str, Any]:
    if since is None:
        since = datetime.utcnow() - timedelta(days=7)

    try:
        rows = execute_query(
            """SELECT AUDIT_TYPE, RESOLUTION_STATUS,
                      COUNT(*) AS EVENT_COUNT,
                      AVG(SIMILARITY_SCORE) AS AVG_SIMILARITY,
                      MAX(CREATED_AT) AS LAST_EVENT
               FROM CONTEXT_AUDIT_LOG
               WHERE CREATED_AT >= :since
               GROUP BY AUDIT_TYPE, RESOLUTION_STATUS
               ORDER BY AUDIT_TYPE, RESOLUTION_STATUS""",
            {"since": since}
        )

        total = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM CONTEXT_AUDIT_LOG WHERE CREATED_AT >= :since",
            {"since": since}
        )

        open_count = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM CONTEXT_AUDIT_LOG WHERE RESOLUTION_STATUS = 'OPEN' AND CREATED_AT >= :since",
            {"since": since}
        )
    except Exception as e:
        logger.debug(f"get_audit_stats: CONTEXT_AUDIT_LOG unavailable: {e}")
        rows, total, open_count = [], None, None

    return {
        "since": since.isoformat(),
        "total_events": total["cnt"] if total else 0,
        "open_events": open_count["cnt"] if open_count else 0,
        "breakdown": [sanitize_row(r) for r in rows],
    }
