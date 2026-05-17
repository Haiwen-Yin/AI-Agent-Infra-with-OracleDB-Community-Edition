"""Oracle Memory System v2.0.0 - Task Plan API

Task plan creation, step management, breakpoint recovery,
tool call auditing, and dependency tracking.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def create_task_plan(
    plan_name: str,
    plan_type: str = "task",
    description: Optional[str] = None,
    goal: Optional[str] = None,
    priority: int = 2,
    steps: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> int:
    plan_sql = """
        INSERT INTO TASK_PLANS (PLAN_NAME, PLAN_TYPE, STATUS, DESCRIPTION, GOAL,
                                PRIORITY, METADATA, TAGS)
        VALUES (:name, :ptype, 'PENDING', :desc, :goal, :priority, :meta, :tags)
        RETURNING PLAN_ID INTO :ret_id
    """
    plan_id = execute_insert_returning_id(plan_sql, {
        "name": plan_name,
        "ptype": plan_type,
        "desc": description,
        "goal": goal,
        "priority": priority,
        "meta": json.dumps(metadata or {}),
        "tags": json.dumps(tags or []),
    })

    if steps:
        for i, step in enumerate(steps, 1):
            step_sql = """
                INSERT INTO TASK_STEPS (PLAN_ID, STEP_ORDER, STEP_NAME, ACTION, TOOLS_USED, STATUS)
                VALUES (:pid, :ord, :sname, :action, :tools, 'PENDING')
            """
            execute(step_sql, {
                "pid": plan_id,
                "ord": i,
                "sname": step.get("name", f"Step {i}"),
                "action": step.get("action", ""),
                "tools": json.dumps(step.get("tools_used", [])),
            })

    save_snapshot(plan_id, {
        "next_action": steps[0].get("action") if steps else None,
        "step_index": 0,
    }, snapshot_type="AUTO")

    return plan_id


def get_task_plan(plan_id: int) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT PLAN_ID, PLAN_NAME, PLAN_TYPE, STATUS, DESCRIPTION, GOAL, PRIORITY,
               METADATA, TAGS,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(STARTED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
        FROM TASK_PLANS
        WHERE PLAN_ID = :pid
    """
    row = execute_query_one(sql, {"pid": plan_id})
    if row is None:
        return None
    for col in ("metadata", "tags"):
        if isinstance(row.get(col), str):
            try:
                row[col] = json.loads(row[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return row


def get_task_steps(plan_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT STEP_ID, PLAN_ID, STEP_ORDER, STEP_NAME, ACTION, TOOLS_USED,
               STATUS, RESULT, ERROR_MSG,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(STARTED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
               TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
        FROM TASK_STEPS
        WHERE PLAN_ID = :pid
        ORDER BY STEP_ORDER
    """
    return execute_query(sql, {"pid": plan_id})


def update_step_status(plan_id: int, step_id: int, status: str,
                       result: Optional[str] = None, error_msg: Optional[str] = None) -> bool:
    updates = {"status": status}
    if result is not None:
        updates["result"] = result
    if error_msg is not None:
        updates["error_msg"] = error_msg
    if status == "IN_PROGRESS":
        updates["started_at"] = "SYSTIMESTAMP"
    elif status in ("SUCCESS", "FAILED", "BLOCKED"):
        updates["completed_at"] = "SYSTIMESTAMP"

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["sid"] = step_id
    execute(f"UPDATE TASK_STEPS SET {set_clause} WHERE STEP_ID = :sid", updates)

    plan_status = _derive_plan_status(plan_id)
    execute("UPDATE TASK_PLANS SET STATUS = :ps, UPDATED_AT = SYSTIMESTAMP WHERE PLAN_ID = :pid",
            {"ps": plan_status, "pid": plan_id})

    save_snapshot(plan_id, {"trigger": f"step_{status}", "step_id": step_id}, snapshot_type="AUTO")
    return True


def save_snapshot(plan_id: int, context: Dict[str, Any],
                  snapshot_type: str = "MANUAL") -> int:
    execute("""
        UPDATE TASK_CONTEXT_SNAPSHOTS SET IS_LATEST = 'N'
        WHERE PLAN_ID = :pid AND IS_LATEST = 'Y'
    """, {"pid": plan_id})

    sql = """
        INSERT INTO TASK_CONTEXT_SNAPSHOTS (PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA,
                                            NEXT_ACTION, IS_LATEST, TRIGGER_REASON)
        VALUES (:pid, :stype, :ctx, :next, 'Y', :trigger)
        RETURNING SNAPSHOT_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "pid": plan_id,
        "stype": snapshot_type,
        "ctx": json.dumps(context),
        "next": context.get("next_action"),
        "trigger": json.dumps({"trigger": context.get("trigger", snapshot_type)}),
    })


def resume_task(plan_id: int) -> Optional[Dict[str, Any]]:
    snapshot = execute_query_one("""
        SELECT SNAPSHOT_ID, CONTEXT_DATA, NEXT_ACTION, SNAPSHOT_TYPE,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM TASK_CONTEXT_SNAPSHOTS
        WHERE PLAN_ID = :pid AND IS_LATEST = 'Y'
        ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY
    """, {"pid": plan_id})

    if snapshot is None:
        return None

    context = snapshot.get("context_data", "{}")
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except (json.JSONDecodeError, TypeError):
            context = {}

    incomplete = execute_query("""
        SELECT STEP_ID, STEP_ORDER, STEP_NAME, ACTION, STATUS
        FROM TASK_STEPS
        WHERE PLAN_ID = :pid AND STATUS IN ('PENDING', 'IN_PROGRESS', 'BLOCKED')
        ORDER BY STEP_ORDER
    """, {"pid": plan_id})

    return {
        "plan_id": plan_id,
        "context": context,
        "next_action": snapshot.get("next_action"),
        "snapshot_time": snapshot.get("created_at"),
        "incomplete_steps": incomplete,
    }


def log_tool_call(plan_id: int, tool_name: str, action: str,
                  step_id: Optional[int] = None, status: str = "SUCCESS",
                  result_size: Optional[int] = None, duration_ms: Optional[int] = None) -> int:
    sql = """
        INSERT INTO TASK_TOOL_CALLS (PLAN_ID, STEP_ID, TOOL_NAME, ACTION,
                                     STATUS, RESULT_SIZE, DURATION_MS)
        VALUES (:pid, :sid, :tool, :action, :status, :rsize, :dur)
        RETURNING CALL_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "pid": plan_id,
        "sid": step_id,
        "tool": tool_name,
        "action": action,
        "status": status,
        "rsize": result_size,
        "dur": duration_ms,
    })


def add_dependency(source_plan_id: int, target_plan_id: int,
                   dependency_type: str = "HARD",
                   condition: Optional[str] = None) -> int:
    sql = """
        INSERT INTO TASK_DEPENDENCIES (SOURCE_PLAN_ID, TARGET_PLAN_ID, DEPENDENCY_TYPE, CONDITION)
        VALUES (:src, :tgt, :dtype, :cond)
        RETURNING DEPENDENCY_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "src": source_plan_id,
        "tgt": target_plan_id,
        "dtype": dependency_type,
        "cond": condition,
    })


def search_completed_tasks(plan_type: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: int = 50) -> List[Dict[str, Any]]:
    conditions = ["STATUS IN ('SUCCESS', 'FAILED')"]
    params: Dict[str, Any] = {"lim": limit}
    if plan_type:
        conditions.append("PLAN_TYPE = :ptype")
        params["ptype"] = plan_type
    if status:
        conditions.append("STATUS = :st")
        params["st"] = status

    where = " AND ".join(conditions)
    sql = f"""
        SELECT PLAN_ID, PLAN_NAME, PLAN_TYPE, STATUS, PRIORITY,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
        FROM TASK_PLANS
        WHERE {where}
        ORDER BY COMPLETED_AT DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return execute_query(sql, params)


def _derive_plan_status(plan_id: int) -> str:
    row = execute_query_one("""
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN STATUS = 'SUCCESS' THEN 1 END) AS done,
            COUNT(CASE WHEN STATUS IN ('IN_PROGRESS', 'BLOCKED') THEN 1 END) AS active,
            COUNT(CASE WHEN STATUS = 'FAILED' THEN 1 END) AS failed
        FROM TASK_STEPS WHERE PLAN_ID = :pid
    """, {"pid": plan_id})
    if not row:
        return "PENDING"
    if row["total"] == 0:
        return "PENDING"
    if row["done"] == row["total"]:
        return "SUCCESS"
    if row["failed"] > 0:
        return "FAILED"
    if row["active"] > 0:
        return "RUNNING"
    return "PENDING"
