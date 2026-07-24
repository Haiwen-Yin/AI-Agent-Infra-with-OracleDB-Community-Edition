"""AI Agent Infra v4.1.0 - Enterprise Edition - Monitoring & Observability

Agent health dashboard, system overview, stalled detection,
performance metrics, and drift detection.

Tables: AGENT_REGISTRY, AGENT_SESSION, TASK_PLANS, LOOP_RUNS,
        TASK_TOOL_CALLS, ENTITY_ACCESS_LOG, CONTEXT_AUDIT_LOG (ENT)
"""

import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, sanitize_row

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
    try:
        busy = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'ACTIVE' AND LAST_ACTIVE_AT > CURRENT_TIMESTAMP - INTERVAL '5 minutes'")
    except Exception:
        busy = execute_query_one("SELECT COUNT(*) AS CNT FROM AGENT_REGISTRY WHERE STATUS = 'ACTIVE' AND LAST_ACTIVE_AT > CURRENT_TIMESTAMP - INTERVAL '5' MINUTE")
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
    try:
        rows = execute_query(
            f"""SELECT a.AGENT_ID, a.AGENT_NAME, a.STATUS, a.LAST_ACTIVE_AT,
                       s.SESSION_ID, s.CREATED_AT AS START_TIME
                FROM AGENT_REGISTRY a
                LEFT JOIN AGENT_SESSION s ON s.AGENT_ID = a.AGENT_ID AND s.IS_ACTIVE = 'Y'
                WHERE a.STATUS = 'ACTIVE'
                  AND a.LAST_ACTIVE_AT < CURRENT_TIMESTAMP - INTERVAL '{threshold_minutes} minutes'
                ORDER BY a.LAST_ACTIVE_AT ASC""",
        )
    except Exception:
        try:
            rows = execute_query(
                f"""SELECT a.AGENT_ID, a.AGENT_NAME, a.STATUS, a.LAST_ACTIVE_AT,
                           s.SESSION_ID, s.START_TIME
                    FROM AGENT_REGISTRY a
                    LEFT JOIN AGENT_SESSION s ON s.AGENT_ID = a.AGENT_ID AND s.IS_ACTIVE = 'Y'
                    WHERE a.STATUS = 'ACTIVE'
                      AND a.LAST_ACTIVE_AT < CURRENT_TIMESTAMP - INTERVAL '{threshold_minutes}' MINUTE
                    ORDER BY a.LAST_ACTIVE_AT ASC""",
            )
        except Exception as e:
            logger.debug(f"get_stalled_agents failed: {e}")
            rows = []
    return [sanitize_row(r) for r in rows]


def get_active_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        rows = execute_query(
            """SELECT * FROM (
                  SELECT a.*, ROW_NUMBER() OVER (ORDER BY CREATED_AT DESC) AS rn
                  FROM CONTEXT_AUDIT_LOG a
                  WHERE RESOLUTION_STATUS = 'OPEN'
                ) WHERE rn <= :limit""",
            {"limit": limit},
        )
        return [sanitize_row(r) for r in rows] if rows else []
    except Exception as e:
        logger.debug(f"get_active_alerts: CONTEXT_AUDIT_LOG unavailable: {e}")
        return []


def get_performance_metrics(since: Optional[str] = None) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    cutoff_7d = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    cutoff_24h = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    def _pg_interval(seconds: int):
        return f"CURRENT_TIMESTAMP - INTERVAL '{seconds} seconds'"

    try:
        avg_session = execute_query_one(
            f"SELECT AVG(EXTRACT(EPOCH FROM (LAST_ACTIVE_AT - CREATED_AT))) AS VAL, "
            f"COUNT(*) AS SAMPLE_COUNT FROM AGENT_SESSION "
            f"WHERE IS_ACTIVE = FALSE AND LAST_ACTIVE_AT IS NOT NULL "
            f"AND CREATED_AT > {_pg_interval(7 * 86400)}"
        )
    except Exception:
        try:
            avg_session = execute_query_one(
                "SELECT AVG((CAST(END_TIME AS DATE) - CAST(START_TIME AS DATE)) * 86400) AS VAL, "
                "COUNT(*) AS SAMPLE_COUNT "
                "FROM AGENT_SESSION WHERE END_TIME IS NOT NULL "
                "AND START_TIME > :cutoff", {"cutoff": cutoff_7d}
            )
        except Exception as e:
            logger.debug(f"avg_session query failed: {e}")
            avg_session = None
    try:
        avg_loop = execute_query_one(
            f"SELECT AVG(EXTRACT(EPOCH FROM (COMPLETED_AT - STARTED_AT))) AS VAL, "
            f"COUNT(*) AS SAMPLE_COUNT "
            f"FROM LOOP_RUNS WHERE COMPLETED_AT IS NOT NULL "
            f"AND STARTED_AT > {_pg_interval(7 * 86400)}"
        )
    except Exception:
        try:
            avg_loop = execute_query_one(
                "SELECT AVG((CAST(COMPLETED_AT AS DATE) - CAST(STARTED_AT AS DATE)) * 86400) AS VAL, "
                "COUNT(*) AS SAMPLE_COUNT "
                "FROM LOOP_RUNS WHERE COMPLETED_AT IS NOT NULL "
                "AND STARTED_AT > :cutoff", {"cutoff": cutoff_7d}
            )
        except Exception as e:
            logger.debug(f"avg_loop query failed: {e}")
            avg_loop = None
    try:
        avg_iterations = execute_query_one(
            f"SELECT AVG(ITERATION_COUNT) AS VAL, COUNT(*) AS SAMPLE_COUNT FROM LOOP_RUNS "
            f"WHERE STATUS = 'COMPLETED' AND STARTED_AT > {_pg_interval(7 * 86400)}"
        )
    except Exception:
        try:
            avg_iterations = execute_query_one(
                "SELECT AVG(ITERATION_COUNT) AS VAL, COUNT(*) AS SAMPLE_COUNT FROM LOOP_RUNS "
                "WHERE STATUS = 'COMPLETED' AND STARTED_AT > :cutoff", {"cutoff": cutoff_7d}
            )
        except Exception as e:
            logger.debug(f"avg_iterations query failed: {e}")
            avg_iterations = None
    try:
        avg_tool = execute_query_one(
            f"SELECT AVG(DURATION_MS) AS VAL, COUNT(*) AS SAMPLE_COUNT FROM TASK_TOOL_CALLS "
            f"WHERE CREATED_AT > {_pg_interval(7 * 86400)}"
        )
    except Exception:
        try:
            avg_tool = execute_query_one(
                "SELECT AVG(DURATION_MS) AS VAL, COUNT(*) AS SAMPLE_COUNT FROM TASK_TOOL_CALLS "
                "WHERE CREATED_AT > :cutoff", {"cutoff": cutoff_7d}
            )
        except Exception as e:
            logger.debug(f"avg_tool query failed: {e}")
            avg_tool = None
    try:
        access_count = execute_query_one(
            f"SELECT COUNT(*) AS CNT FROM ENTITY_ACCESS_LOG "
            f"WHERE ACCESS_TIME > {_pg_interval(86400)}"
        )
    except Exception:
        try:
            access_count = execute_query_one(
                "SELECT COUNT(*) AS CNT FROM ENTITY_ACCESS_LOG "
                "WHERE ACCESS_TIME > :cutoff", {"cutoff": cutoff_24h}
            )
        except Exception as e:
            logger.debug(f"access_count query failed: {e}")
            access_count = None

    def _val(row):
        return row.get("val") if row else None

    def _samples(row):
        return row.get("sample_count", 0) if row else 0

    return {
        "avg_session_duration": _val(avg_session),
        "session_sample_count": _samples(avg_session),
        "avg_loop_duration": _val(avg_loop),
        "loop_sample_count": _samples(avg_loop),
        "avg_iteration_count": _val(avg_iterations),
        "iteration_sample_count": _samples(avg_iterations),
        "avg_tool_duration_ms": _val(avg_tool),
        "tool_sample_count": _samples(avg_tool),
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


# ============================================================
# R4: Agent Auto-Recovery with ALERT_RULES
# ============================================================

def _ensure_alert_rules_table() -> bool:
    """ALERT_RULES is installed by the versioned database migration."""
    return True


def create_alert_rule(
    rule_name: str,
    agent_id: Optional[str],
    metric: str,
    operator: str,
    threshold: float,
    action: str,
    action_config: Optional[Dict[str, Any]] = None,
    cooldown_minutes: int = 30,
    enabled: bool = True,
) -> Optional[str]:
    """Insert a new ALERT_RULES row and return its RULE_ID."""
    _ensure_alert_rules_table()
    import json as _json
    try:
        valid_ops = (">", "<", ">=", "<=", "=", "!=")
        if operator not in valid_ops:
            raise ValueError(f"operator must be one of {valid_ops}")

        rule_id = f"AR_{__import__('uuid').uuid4().hex[:16]}"
        cfg_str = _json.dumps(action_config) if action_config else None
        execute(
            """INSERT INTO ALERT_RULES
                   (RULE_ID, RULE_NAME, AGENT_ID, METRIC_NAME, OPERATOR,
                    THRESHOLD, ACTION, ACTION_CONFIG, ENABLED, COOLDOWN_MINUTES,
                    CREATED_AT)
               VALUES (:rid, :name, :aid, :metric, :op, :thr, :act, :cfg,
                       :en, :cd, CURRENT_TIMESTAMP)""",
            {
                "rid": rule_id,
                "name": rule_name,
                "aid": agent_id,
                "metric": metric,
                "op": operator,
                "thr": threshold,
                "act": action,
                "cfg": cfg_str,
                "en": "Y" if enabled else "N",
                "cd": cooldown_minutes,
            },
        )
        return rule_id
    except Exception as e:
        logger.error(f"create_alert_rule failed: {e}")
        return None


def _matches_rule(value: float, operator: str, threshold: float) -> bool:
    try:
        if operator == ">":
            return value > threshold
        if operator == "<":
            return value < threshold
        if operator == ">=":
            return value >= threshold
        if operator == "<=":
            return value <= threshold
        if operator == "=":
            return value == threshold
        if operator == "!=":
            return value != threshold
    except Exception:
        return False
    return False


def _evaluate_rule(rule: Dict[str, Any], agents_stale: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Evaluate one rule against a snapshot of stale agent metrics.

    Returns a trigger dict if the rule fired, otherwise None.
    """
    import json as _json
    try:
        threshold = float(rule.get("threshold", 0))
        operator = (rule.get("operator") or ">").strip()
        metric = (rule.get("metric_name") or "").lower()
        cooldown = float(rule.get("cooldown_minutes") or 0)
        last_triggered = rule.get("last_triggered_at")

        # Cooldown enforcement
        if last_triggered is not None and cooldown > 0:
            import datetime
            try:
                now = datetime.datetime.now()
                if hasattr(last_triggered, "tzinfo") and last_triggered.tzinfo:
                    now = datetime.datetime.now(last_triggered.tzinfo)
                if (now - last_triggered).total_seconds() < cooldown * 60:
                    return None
            except Exception:
                pass

        target_agent_id = rule.get("agent_id")
        candidates = (
            [agents_stale[target_agent_id]] if target_agent_id and target_agent_id in agents_stale
            else list(agents_stale.values())
        )

        for agent in candidates:
            value = agent.get(metric)
            if value is None:
                continue
            try:
                value_num = float(value)
            except (TypeError, ValueError):
                continue
            if _matches_rule(value_num, operator, threshold):
                cfg = rule.get("action_config")
                if isinstance(cfg, str):
                    try:
                        cfg = _json.loads(cfg)
                    except Exception:
                        cfg = {}
                return {
                    "rule_id": rule.get("rule_id"),
                    "rule_name": rule.get("rule_name"),
                    "agent_id": agent.get("agent_id"),
                    "metric": metric,
                    "operator": operator,
                    "threshold": threshold,
                    "observed_value": value_num,
                    "action": rule.get("action"),
                    "action_config": cfg,
                }
    except Exception as e:
        logger.debug(f"_evaluate_rule failed: {e}")
    return None


def check_agent_health(stale_threshold_minutes: int = 30) -> Dict[str, Any]:
    """Snapshot agent health for auto-recovery decisions.

    Returns a dict with:
      - stale_agents: list of agents whose LAST_SEEN_AT exceeds threshold
      - rules_evalated: count of enabled ALERT_RULES considered
      - actions_pending: list of rule-triggered recovery actions
    """
    _ensure_alert_rules_table()
    try:
        try:
            stale_rows = execute_query(
                f"""SELECT AGENT_ID, AGENT_NAME, STATUS, LAST_SEEN_AT, LAST_ACTIVE_AT
                    FROM AGENT_REGISTRY
                    WHERE LAST_SEEN_AT IS NOT NULL
                      AND LAST_SEEN_AT < CURRENT_TIMESTAMP - INTERVAL '{int(stale_threshold_minutes)} minutes'
                    ORDER BY LAST_SEEN_AT ASC""",
                {},
            )
        except Exception:
            stale_rows = execute_query(
                f"""SELECT AGENT_ID, AGENT_NAME, STATUS, LAST_SEEN_AT, LAST_ACTIVE_AT
                    FROM AGENT_REGISTRY
                    WHERE LAST_SEEN_AT IS NOT NULL
                      AND LAST_SEEN_AT < CURRENT_TIMESTAMP - INTERVAL '{int(stale_threshold_minutes)}' MINUTE
                    ORDER BY LAST_SEEN_AT ASC""",
                {},
            )
    except Exception as e:
        logger.error(f"check_agent_health stale query failed: {e}")
        stale_rows = []

    stale_agents: Dict[str, Dict[str, Any]] = {}
    for r in stale_rows:
        a = sanitize_row(r)
        agent_id = a.get("agent_id")
        if not agent_id:
            continue
        import datetime
        stale_minutes = None
        last_seen = a.get("last_seen_at")
        if last_seen and not isinstance(last_seen, str):
            try:
                now = datetime.datetime.now(last_seen.tzinfo) if getattr(last_seen, "tzinfo", None) else datetime.datetime.now()
                stale_minutes = (now - last_seen).total_seconds() / 60.0
            except Exception:
                pass
        a["stale_minutes"] = round(stale_minutes, 1) if stale_minutes is not None else None
        stale_agents[agent_id] = a

    actions: List[Dict[str, Any]] = []
    rules_evaluated = 0
    try:
        rules = execute_query(
            """SELECT RULE_ID, RULE_NAME, AGENT_ID, METRIC_NAME, OPERATOR,
                      THRESHOLD, ACTION, ACTION_CONFIG, COOLDOWN_MINUTES,
                      LAST_TRIGGERED_AT
               FROM ALERT_RULES
               WHERE ENABLED = 'Y'""",
            {},
        )
        for rule in rules:
            rules_evaluated += 1
            trigger = _evaluate_rule(rule, stale_agents)
            if trigger:
                actions.append(trigger)
    except Exception as e:
        logger.debug(f"check_agent_health rule eval failed: {e}")

    return {
        "stale_agents": list(stale_agents.values()),
        "rules_evaluated": rules_evaluated,
        "actions_pending": actions,
    }


def evaluate_alert_rules() -> List[Dict[str, Any]]:
    """Evaluate every enabled ALERT_RULE against current agent health and fire actions."""
    _ensure_alert_rules_table()
    snapshot = check_agent_health()
    fired: List[Dict[str, Any]] = []
    for trigger in snapshot.get("actions_pending", []):
        fired.append(trigger)
        try:
            execute(
                """UPDATE ALERT_RULES
                       SET LAST_TRIGGERED_AT = CURRENT_TIMESTAMP
                   WHERE RULE_ID = :rid""",
                {"rid": trigger.get("rule_id")},
            )
        except Exception as e:
            logger.debug(f"evaluate_alert_rules LAST_TRIGGERED_AT update failed: {e}")
    return fired


def auto_recover_stalled_agents(stale_threshold_minutes: int = 30) -> Dict[str, Any]:
    """Mark long-stale agents as STALLED and trigger any matching recovery rules.

    Returns a summary dict with the count of agents marked stalled and the
    list of recovery actions that fired. Wrapped defensively so missing
    columns/tables do not crash the caller.
    """
    snapshot = check_agent_health(stale_threshold_minutes=stale_threshold_minutes)
    marked = 0
    marked_agent_ids: List[str] = []

    for agent in snapshot.get("stale_agents", []):
        agent_id = agent.get("agent_id")
        if not agent_id:
            continue
        try:
            rowcount = execute(
                "UPDATE AGENT_REGISTRY SET STATUS = 'STALLED' WHERE AGENT_ID = :aid AND STATUS <> 'STALLED'",
                {"aid": agent_id},
            )
            if rowcount and rowcount > 0:
                marked += 1
                marked_agent_ids.append(agent_id)
        except Exception as e:
            logger.error(f"auto_recover_stalled_agents mark failed for {agent_id}: {e}")

    actions = snapshot.get("actions_pending", [])

    # Best-effort recovery actions (RESTART / NOTIFY / DISABLE)
    for action in actions:
        try:
            kind = (action.get("action") or "").upper()
            if kind in ("RESTART", "RESUME"):
                target = action.get("agent_id")
                if target:
                    execute(
                        "UPDATE AGENT_REGISTRY SET STATUS = 'ACTIVE' WHERE AGENT_ID = :aid",
                        {"aid": target},
                    )
            elif kind in ("DISABLE", "SUSPEND"):
                target = action.get("agent_id")
                if target:
                    execute(
                        "UPDATE AGENT_REGISTRY SET STATUS = 'SUSPENDED' WHERE AGENT_ID = :aid",
                        {"aid": target},
                    )
        except Exception as e:
            logger.error(f"auto_recover action '{action.get('action')}' failed: {e}")

    return {
        "stale_threshold_minutes": stale_threshold_minutes,
        "agents_marked_stalled": marked,
        "marked_agent_ids": marked_agent_ids,
        "actions_fired": actions,
    }
