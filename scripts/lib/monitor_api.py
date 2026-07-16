"""AI Agent Infra v3.10.2 - Community Edition - Monitoring & Observability

Agent health dashboard, system overview, stalled detection,
performance metrics, and drift detection.

Tables: AGENT_REGISTRY, AGENT_SESSION, TASK_PLANS, LOOP_RUNS,
        TASK_TOOL_CALLS, ENTITY_ACCESS_LOG, CONTEXT_AUDIT_LOG (ENT)
"""

import logging
from typing import Any, Dict, List, Optional

from .connection import execute_query, execute_query_one, sanitize_row

logger = logging.getLogger(__name__)


def get_agent_health(agent_id: Optional[str] = None) -> Dict[str, Any]:
    if agent_id:
        agent = execute_query_one(
            "SELECT * FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
            {"aid": agent_id},
        )
        if not agent:
            return {"error": f"Agent not found: {agent_id}"}
        session = execute_query_one(
            "SELECT * FROM AGENT_SESSION WHERE AGENT_ID = :aid AND IS_ACTIVE = 'Y' FETCH FIRST 1 ROWS ONLY",
            {"aid": agent_id},
        )
        plan_count = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM TASK_PLANS WHERE AGENT_ID = :aid AND STATUS = 'RUNNING'",
            {"aid": agent_id},
        )
        run_count = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM LOOP_RUNS WHERE AGENT_ID = :aid AND STATUS = 'RUNNING'",
            {"aid": agent_id},
        )
        last_active = agent.get("last_active_at")
        import datetime
        stale_seconds = None
        if last_active:
            if isinstance(last_active, str):
                stale_seconds = None
            else:
                delta = datetime.datetime.now(last_active.tzinfo) if last_active.tzinfo else datetime.datetime.now() - last_active
                stale_seconds = int(delta.total_seconds())

        status = "ONLINE"
        if agent.get("status") == "POOL":
            status = "IDLE"
        elif agent.get("status") in ("INACTIVE", "SUSPENDED", "DECOMMISSIONED"):
            status = "OFFLINE"
        elif stale_seconds and stale_seconds > 600:
            status = "STALLED"

        return {
            "agent_id": agent_id,
            "agent_name": agent.get("agent_name"),
            "status": status,
            "db_status": agent.get("status"),
            "current_session_id": session.get("session_id") if session else None,
            "active_plan_count": plan_count.get("cnt", 0) if plan_count else 0,
            "running_loop_count": run_count.get("cnt", 0) if run_count else 0,
            "last_active_at": str(last_active) if last_active else None,
            "stale_seconds": stale_seconds,
        }
    else:
        agents = execute_query(
            "SELECT AGENT_ID, AGENT_NAME, STATUS, LAST_SEEN_AT, LAST_ACTIVE_AT FROM AGENT_REGISTRY ORDER BY AGENT_NAME",
        )
        result = []
        for a in agents:
            a = sanitize_row(a)
            health = get_agent_health(a.get("agent_id"))
            result.append(health)
        return {"agents": result}


def get_system_overview() -> Dict[str, Any]:
    total = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY")
    online = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'ACTIVE'")
    busy = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'ACTIVE' AND LAST_ACTIVE_AT > SYSTIMESTAMP - INTERVAL '5' MINUTE")
    pool = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'POOL'")
    dormant = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'DORMANT'")
    active_sessions = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_SESSION WHERE IS_ACTIVE = 'Y'")
    running_plans = execute_query_one("SELECT COUNT(*) AS CNT FROM TASK_PLANS WHERE STATUS = 'RUNNING'")
    running_loops = execute_query_one("SELECT COUNT(*) AS CNT FROM LOOP_RUNS WHERE STATUS = 'RUNNING'")
    stalled = get_stalled_agents(10)

    return {
        "agents": {
            "total": total.get("cnt", 0) if total else 0,
            "online": online.get("cnt", 0) if online else 0,
            "busy": busy.get("cnt", 0) if busy else 0,
            "idle": pool.get("cnt", 0) if pool else 0,
            "dormant": dormant.get("cnt", 0) if dormant else 0,
        },
        "sessions": {
            "active": active_sessions.get("cnt", 0) if active_sessions else 0,
        },
        "tasks": {
            "running_plans": running_plans.get("cnt", 0) if running_plans else 0,
            "running_loops": running_loops.get("cnt", 0) if running_loops else 0,
        },
        "stalled_count": len(stalled),
    }


def get_stalled_agents(threshold_minutes: int = 10) -> List[Dict[str, Any]]:
    rows = execute_query(
        f"""SELECT a.AGENT_ID, a.AGENT_NAME, a.STATUS, a.LAST_ACTIVE_AT,
                  s.SESSION_ID, s.START_TIME
           FROM AGENT_REGISTRY a
           LEFT JOIN AGENT_SESSION s ON s.AGENT_ID = a.AGENT_ID AND s.IS_ACTIVE = 'Y'
           WHERE a.STATUS = 'ACTIVE'
             AND a.LAST_ACTIVE_AT < SYSTIMESTAMP - INTERVAL '{threshold_minutes}' MINUTE
           ORDER BY a.LAST_ACTIVE_AT ASC""",
    )
    return [sanitize_row(r) for r in rows]


def get_active_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT * FROM (
              SELECT a.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
              FROM CONTEXT_AUDIT_LOG a
              WHERE RESOLUTION_STATUS = 'OPEN'
            ) WHERE rn <= :limit""",
        {"limit": limit},
    )
    return [sanitize_row(r) for r in rows] if rows else []


def get_performance_metrics(since: Optional[str] = None) -> Dict[str, Any]:
    avg_session = execute_query_one(
        "SELECT AVG((CAST(END_TIME AS DATE) - CAST(START_TIME AS DATE)) * 86400) AS VAL FROM AGENT_SESSION WHERE END_TIME IS NOT NULL AND START_TIME > SYSTIMESTAMP - NUMTODSINTERVAL(7, 'DAY')"
    )
    avg_loop = execute_query_one(
        "SELECT AVG((CAST(COMPLETED_AT AS DATE) - CAST(STARTED_AT AS DATE)) * 86400) AS VAL FROM LOOP_RUNS WHERE COMPLETED_AT IS NOT NULL AND STARTED_AT > SYSTIMESTAMP - NUMTODSINTERVAL(7, 'DAY')"
    )
    avg_iterations = execute_query_one(
        "SELECT AVG(ITERATION_COUNT) AS VAL FROM LOOP_RUNS WHERE STATUS = 'COMPLETED' AND STARTED_AT > SYSTIMESTAMP - NUMTODSINTERVAL(7, 'DAY')"
    )
    avg_tool = execute_query_one(
        "SELECT AVG(DURATION_MS) AS VAL FROM TASK_TOOL_CALLS WHERE CREATED_AT > SYSTIMESTAMP - NUMTODSINTERVAL(7, 'DAY')"
    )
    access_count = execute_query_one(
        "SELECT COUNT(*) AS CNT FROM ENTITY_ACCESS_LOG WHERE ACCESS_TIME > SYSTIMESTAMP - NUMTODSINTERVAL(1, 'DAY')"
    )

    def _val(row):
        return row.get("val") if row else None

    return {
        "avg_session_duration": _val(avg_session),
        "avg_loop_duration": _val(avg_loop),
        "avg_iteration_count": _val(avg_iterations),
        "avg_tool_duration_ms": _val(avg_tool),
        "entity_access_count_24h": access_count.get("cnt", 0) if access_count else 0,
    }


def detect_run_drift(
    loop_id: str,
    metric: str = "total_tokens",
    baseline_runs: int = 10,
    deviation_stdev: float = 2.0,
) -> Dict[str, Any]:
    rows = execute_query(
        f"""SELECT {metric} AS VAL FROM LOOP_RUNS
           WHERE LOOP_ID = :lid AND STATUS = 'COMPLETED'
           ORDER BY STARTED_AT DESC FETCH FIRST :limit ROWS ONLY""",
        {"lid": loop_id, "limit": baseline_runs * 2},
    )
    if len(rows) < 3:
        return {"has_drift": False, "reason": "insufficient_data", "count": len(rows)}

    values = [r.get("val") or 0 for r in rows]
    baseline = values[-baseline_runs:] if len(values) >= baseline_runs else values
    recent = values[:max(1, len(values) // 2)]

    import statistics
    b_avg = statistics.mean(baseline) if baseline else 0
    b_stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0
    r_avg = statistics.mean(recent) if recent else 0

    has_drift = b_stdev > 0 and abs(r_avg - b_avg) > deviation_stdev * b_stdev

    return {
        "has_drift": has_drift,
        "metric": metric,
        "baseline_avg": round(b_avg, 2),
        "baseline_stdev": round(b_stdev, 2),
        "recent_avg": round(r_avg, 2),
        "drift_factor": round(abs(r_avg - b_avg) / b_stdev, 2) if b_stdev > 0 else 0,
    }


def detect_eval_drift(
    agent_id: str,
    eval_type: str = "LLM_JUDGE",
    baseline_count: int = 20,
) -> Dict[str, Any]:
    rows = execute_query(
        """SELECT i.EVALUATION_RESULT, i.EVALUATION_PASSED, i.CREATED_AT
           FROM LOOP_ITERATIONS i
           JOIN LOOP_RUNS r ON r.RUN_ID = i.RUN_ID
           WHERE r.AGENT_ID = :aid
           ORDER BY i.CREATED_AT DESC
           FETCH FIRST :limit ROWS ONLY""",
        {"aid": agent_id, "limit": baseline_count * 2},
    )
    if len(rows) < 5:
        return {"has_drift": False, "reason": "insufficient_data"}

    passed = [1 if r.get("evaluation_passed") == "Y" else 0 for r in rows]
    half = len(passed) // 2
    baseline_pass_rate = sum(passed[half:]) / max(1, len(passed) - half)
    recent_pass_rate = sum(passed[:half]) / max(1, half)

    trend = "stable"
    if recent_pass_rate < baseline_pass_rate - 0.15:
        trend = "declining"
    elif recent_pass_rate > baseline_pass_rate + 0.15:
        trend = "improving"

    return {
        "has_drift": trend != "stable",
        "trend": trend,
        "baseline_pass_rate": round(baseline_pass_rate, 3),
        "recent_pass_rate": round(recent_pass_rate, 3),
    }


def detect_iteration_bloat(
    agent_id: str,
    baseline_count: int = 20,
) -> Dict[str, Any]:
    rows = execute_query(
        """SELECT ITERATION_COUNT FROM LOOP_RUNS
           WHERE AGENT_ID = :aid AND STATUS = 'COMPLETED'
           ORDER BY STARTED_AT DESC
           FETCH FIRST :limit ROWS ONLY""",
        {"aid": agent_id, "limit": baseline_count * 2},
    )
    if len(rows) < 5:
        return {"has_drift": False, "reason": "insufficient_data"}

    counts = [r.get("iteration_count", 0) for r in rows]
    half = len(counts) // 2
    import statistics
    baseline_avg = statistics.mean(counts[half:]) if counts[half:] else 0
    recent_avg = statistics.mean(counts[:half]) if counts[:half] else 0

    has_drift = recent_avg > baseline_avg * 1.3

    return {
        "has_drift": has_drift,
        "baseline_avg_iterations": round(baseline_avg, 1),
        "recent_avg_iterations": round(recent_avg, 1),
        "trend": "increasing" if has_drift else "stable",
    }
