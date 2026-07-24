"""AI Agent Infra v4.1.0 - Enterprise Edition - Distributed Tracing

Trace ID propagation across sessions, plans, loop runs, and tool calls.
Thread-local trace context for automatic propagation.

Tables: AGENT_SESSION (TRACE_ID), TASK_PLANS (TRACE_ID),
        LOOP_RUNS (TRACE_ID), TASK_TOOL_CALLS (TRACE_ID),
        ENTITY_ACCESS_LOG (TRACE_ID, DURATION_MS)
"""

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from .connection import execute_query, execute_query_one, sanitize_row

logger = logging.getLogger(__name__)
_thread_local = threading.local()


def init_trace(source: str = "API") -> str:
    trace_id = uuid.uuid4().hex
    _thread_local.trace_id = trace_id
    logger.debug("Trace %s initialized from %s", trace_id, source)
    return trace_id


def set_trace(trace_id: str):
    _thread_local.trace_id = trace_id


def get_trace() -> Optional[str]:
    return getattr(_thread_local, "trace_id", None)


def clear_trace():
    if hasattr(_thread_local, "trace_id"):
        del _thread_local.trace_id


def get_trace_tree(trace_id: str) -> Dict[str, Any]:
    session = execute_query_one(
        "SELECT * FROM AGENT_SESSION WHERE TRACE_ID = :tid FETCH FIRST 1 ROWS ONLY",
        {"tid": trace_id},
    )
    plans = execute_query(
        "SELECT * FROM TASK_PLANS WHERE TRACE_ID = :tid ORDER BY CREATED_AT",
        {"tid": trace_id},
    )
    runs = execute_query(
        "SELECT * FROM LOOP_RUNS WHERE TRACE_ID = :tid ORDER BY STARTED_AT",
        {"tid": trace_id},
    )
    tool_calls = execute_query(
        "SELECT * FROM TASK_TOOL_CALLS WHERE TRACE_ID = :tid ORDER BY CREATED_AT",
        {"tid": trace_id},
    )
    access_logs = execute_query(
        "SELECT * FROM ENTITY_ACCESS_LOG WHERE TRACE_ID = :tid ORDER BY ACCESS_TIME FETCH FIRST 100 ROWS ONLY",
        {"tid": trace_id},
    )

    def _safe(row):
        return sanitize_row(row) if row else None

    return {
        "trace_id": trace_id,
        "session": _safe(session),
        "plans": [sanitize_row(p) for p in plans],
        "loop_runs": [sanitize_row(r) for r in runs],
        "tool_calls": [sanitize_row(t) for t in tool_calls],
        "access_logs": [sanitize_row(a) for a in access_logs],
        "span_count": 1 + len(plans) + len(runs) + len(tool_calls) + len(access_logs),
    }


def get_trace_summary(
    agent_id: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    clauses = ["s.TRACE_ID IS NOT NULL"]
    params: Dict[str, Any] = {"limit": limit}
    if agent_id:
        clauses.append("s.AGENT_ID = :aid")
        params["aid"] = agent_id
    if since:
        clauses.append("s.START_TIME >= TO_TIMESTAMP(:since)")
        params["since"] = since

    rows = execute_query(
        f"""SELECT s.TRACE_ID, s.AGENT_ID, s.SESSION_ID,
                  s.START_TIME, s.END_TIME, s.IS_ACTIVE,
                  (SELECT COUNT(*) FROM TASK_PLANS p WHERE p.TRACE_ID = s.TRACE_ID) AS plan_count,
                  (SELECT COUNT(*) FROM LOOP_RUNS r WHERE r.TRACE_ID = s.TRACE_ID) AS run_count,
                  (SELECT COUNT(*) FROM TASK_TOOL_CALLS t WHERE t.TRACE_ID = s.TRACE_ID) AS tool_count
           FROM AGENT_SESSION s
           WHERE {' AND '.join(clauses)}
           ORDER BY s.START_TIME DESC
           FETCH FIRST :limit ROWS ONLY""",
        params,
    )
    return [sanitize_row(r) for r in rows]


def get_trace_span(trace_id: str, span_type: str) -> Dict[str, Any]:
    table_map = {
        "SESSION": "AGENT_SESSION",
        "PLAN": "TASK_PLANS",
        "RUN": "LOOP_RUNS",
        "TOOL_CALL": "TASK_TOOL_CALLS",
        "ACCESS_LOG": "ENTITY_ACCESS_LOG",
    }
    table = table_map.get(span_type.upper())
    if not table:
        return {"error": f"Unknown span type: {span_type}"}
    rows = execute_query(
        f"SELECT * FROM {table} WHERE TRACE_ID = :tid ORDER BY CREATED_AT",
        {"tid": trace_id},
    )
    return {"trace_id": trace_id, "span_type": span_type, "spans": [sanitize_row(r) for r in rows]}
