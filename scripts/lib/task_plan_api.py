"""AI Agent Infra v4.1.0 - Enterprise Edition - Task Plan API

Task plan creation, step management, breakpoint recovery,
tool call auditing, and dependency tracking.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import (
    DATABASE_DIALECT, execute, execute_query, execute_query_one,
    execute_insert_returning_id,
)

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "CANCELLED"})
_STEP_TERMINAL_STATUSES = frozenset({"SUCCESS", "FAILED", "SKIPPED"})
_ALLOWED_PLAN_UPDATES = frozenset({"goal", "priority", "strategy", "result_summary", "status", "branch_id"})
_ALLOWED_STEP_UPDATES = frozenset({"description", "tool_name", "tool_input", "tool_output", "status", "assigned_agent_id"})


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    for key, value in row.items():
        lk = key.lower()
        if isinstance(value, str) and lk in (
            "tool_input", "tool_output", "context_data",
        ):
            try:
                result[lk] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                result[lk] = value
        else:
            result[lk] = value
    return result


def create_plan(agent_id: str, goal: str, priority: int = 5,
                strategy: Optional[str] = None,
                branch_id: Optional[str] = None) -> str:
    """Create a new task plan and return its PLAN_ID."""
    sql = """
        INSERT INTO TASK_PLANS (PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, BRANCH_ID)
        VALUES ('PLAN_' || AI_NEW_ID(), :agent_id, :goal, 'PENDING', :priority, :strategy, :branch_id)
        RETURNING PLAN_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "agent_id": agent_id,
        "goal": goal,
        "priority": priority,
        "strategy": strategy,
        "branch_id": branch_id,
    })


_PLAN_TIMESTAMP_COLS = """
    TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
    TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
"""


def _plan_select_cols(pg_mode: bool = False) -> str:
    """Return the SELECT column list for plans, with an optional COMPLETED_AT column.

    PG's task_plans has no COMPLETED_AT column; UPDATED_AT serves the same role.
    """
    if pg_mode:
        return (
            "PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID, "
            "TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT, "
            "TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT, "
            "TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT"
        )
    return (
        "PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID, "
        "TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT, "
        "TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT, "
        "TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT"
    )


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a plan by PLAN_ID."""
    try:
        sql = f"""
            SELECT {_plan_select_cols(pg_mode=True)}
            FROM TASK_PLANS
            WHERE PLAN_ID = :plan_id
        """
        row = execute_query_one(sql, {"plan_id": plan_id})
    except Exception:
        sql = f"""
            SELECT {_plan_select_cols(pg_mode=False)}
            FROM TASK_PLANS
            WHERE PLAN_ID = :plan_id
        """
        row = execute_query_one(sql, {"plan_id": plan_id})
    if row is None:
        return None
    return _row_to_dict(row)


def update_plan(plan_id: str, **kwargs: Any) -> bool:
    """Update plan fields. Sets UPDATED_AT (and COMPLETED_AT if available) on terminal status transitions."""
    valid = {k: v for k, v in kwargs.items() if k in _ALLOWED_PLAN_UPDATES}
    if not valid:
        return False

    has_terminal = "status" in valid and valid["status"] in _TERMINAL_STATUSES

    set_parts = []
    params: Dict[str, Any] = {"plan_id": plan_id}
    for key, value in valid.items():
        if key == "status":
            set_parts.append(f"{key.upper()} = :{key}")
            params[key] = value
        elif key == "completed_at":
            continue
        else:
            set_parts.append(f"{key.upper()} = :{key}")
            params[key] = value

    if not set_parts:
        return False

    set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
    if has_terminal:
        set_parts.append("COMPLETED_AT = CURRENT_TIMESTAMP")

    set_clause = ", ".join(set_parts)
    sql = f"UPDATE TASK_PLANS SET {set_clause} WHERE PLAN_ID = :plan_id"
    try:
        affected = execute(sql, params)
    except Exception:
        if has_terminal:
            set_parts = [p for p in set_parts if not p.startswith("COMPLETED_AT")]
            set_clause = ", ".join(set_parts)
            sql = f"UPDATE TASK_PLANS SET {set_clause} WHERE PLAN_ID = :plan_id"
            affected = execute(sql, params)
        else:
            raise
    return affected > 0


def add_step(plan_id: str, plan_status: str, description: str, step_order: int,
             tool_name: Optional[str] = None, tool_input: Optional[Any] = None,
             assigned_agent_id: Optional[str] = None) -> str:
    """Add a step to a plan and return its STEP_ID."""
    if DATABASE_DIALECT == "postgresql":
        sql = """
        INSERT INTO TASK_STEPS (STEP_ID, PLAN_ID, PLAN_STATUS, STEP_ORDER, DESCRIPTION,
                                TOOL_NAME, TOOL_INPUT, STATUS)
        VALUES ('STEP_' || AI_NEW_ID(), :plan_id, :plan_status, :step_order,
                :description, :tool_name, :tool_input, 'PENDING')
        RETURNING STEP_ID INTO :ret_id
        """
    else:
        sql = """
        INSERT INTO TASK_STEPS (STEP_ID, PLAN_ID, PLAN_STATUS, STEP_ORDER, DESCRIPTION,
                                TOOL_NAME, TOOL_INPUT, ASSIGNED_AGENT_ID, STATUS)
        VALUES ('STEP_' || AI_NEW_ID(), :plan_id, :plan_status, :step_order,
                :description, :tool_name, :tool_input, :vaaid, 'PENDING')
        RETURNING STEP_ID INTO :ret_id
        """
    return execute_insert_returning_id(sql, {
        "plan_id": plan_id,
        "plan_status": plan_status,
        "step_order": step_order,
        "description": description,
        "tool_name": tool_name,
        "tool_input": json.dumps(tool_input) if tool_input is not None else None,
        "vaaid": assigned_agent_id,
    })


def update_step(step_id: str, **kwargs: Any) -> bool:
    """Update step fields. Sets timestamps on status transitions (if those columns exist)."""
    valid = {k: v for k, v in kwargs.items() if k in _ALLOWED_STEP_UPDATES}
    if not valid:
        return False

    set_parts = []
    params: Dict[str, Any] = {"step_id": step_id}
    for key, value in valid.items():
        if key in ("tool_input", "tool_output"):
            params[key] = json.dumps(value) if value is not None else None
        else:
            params[key] = value
        set_parts.append(f"{key.upper()} = :{key}")

    extra_sets = []
    if "status" in valid:
        if valid["status"] == "RUNNING":
            extra_sets.append("STARTED_AT = CURRENT_TIMESTAMP")
        elif valid["status"] in _STEP_TERMINAL_STATUSES:
            extra_sets.append("COMPLETED_AT = CURRENT_TIMESTAMP")

    set_clause = ", ".join(set_parts + extra_sets)
    sql = f"UPDATE TASK_STEPS SET {set_clause} WHERE STEP_ID = :step_id"
    try:
        affected = execute(sql, params)
    except Exception:
        if extra_sets:
            set_clause = ", ".join(set_parts)
            sql = f"UPDATE TASK_STEPS SET {set_clause} WHERE STEP_ID = :step_id"
            affected = execute(sql, params)
        else:
            raise
    return affected > 0


def get_plan_steps(plan_id: str) -> List[Dict[str, Any]]:
    """Return all steps for a plan ordered by STEP_ORDER."""
    try:
        sql = """
            SELECT STEP_ID, PLAN_ID, PLAN_STATUS, STEP_ORDER, DESCRIPTION,
                   TOOL_NAME, TOOL_INPUT, TOOL_OUTPUT, ASSIGNED_AGENT_ID, STATUS,
                   TO_CHAR(STARTED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
                   TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
            FROM TASK_STEPS
            WHERE PLAN_ID = :plan_id
            ORDER BY STEP_ORDER
        """
        rows = execute_query(sql, {"plan_id": plan_id})
    except Exception:
        try:
            sql = """
                SELECT STEP_ID, PLAN_ID, PLAN_STATUS, STEP_ORDER, DESCRIPTION,
                       TOOL_NAME, TOOL_INPUT, TOOL_OUTPUT, STATUS,
                       TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS STARTED_AT,
                       TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
                FROM TASK_STEPS
                WHERE PLAN_ID = :plan_id
                ORDER BY STEP_ORDER
            """
            rows = execute_query(sql, {"plan_id": plan_id})
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"get_plan_steps failed: {e}")
            rows = []
    return [_row_to_dict(r) for r in rows]


def add_dependency(source_plan_id: str, target_plan_id: str, dep_type: str) -> str:
    """Create a dependency between two plans and return its DEP_ID."""
    sql = """
        INSERT INTO TASK_DEPENDENCIES (DEP_ID, SOURCE_PLAN_ID, TARGET_PLAN_ID, DEP_TYPE)
        VALUES ('DEP_' || AI_NEW_ID(), :source, :target, :dep_type)
        RETURNING DEP_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "source": source_plan_id,
        "target": target_plan_id,
        "dep_type": dep_type,
    })


def get_plan_dependencies(plan_id: str) -> List[Dict[str, Any]]:
    """Return all dependencies where the plan is source or target."""
    sql = """
        SELECT DEP_ID, SOURCE_PLAN_ID, TARGET_PLAN_ID, DEP_TYPE,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM TASK_DEPENDENCIES
        WHERE SOURCE_PLAN_ID = :plan_id OR TARGET_PLAN_ID = :plan_id
        ORDER BY CREATED_AT
    """
    return [_row_to_dict(r) for r in execute_query(sql, {"plan_id": plan_id})]


def log_tool_call(plan_id: str, step_id: Optional[str] = None,
                  tool_name: Optional[str] = None,
                  tool_input: Optional[Any] = None,
                  tool_output: Optional[Any] = None,
                  status: str = "PENDING",
                  duration_ms: Optional[int] = None) -> str:
    """Log a tool call and return its CALL_ID."""
    sql = """
        INSERT INTO TASK_TOOL_CALLS (CALL_ID, PLAN_ID, STEP_ID, TOOL_NAME,
                                     TOOL_INPUT, TOOL_OUTPUT, STATUS, DURATION_MS)
        VALUES ('CALL_' || AI_NEW_ID(), :plan_id, :step_id, :tool_name,
                :tool_input, :tool_output, :status, :duration_ms)
        RETURNING CALL_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "plan_id": plan_id,
        "step_id": step_id,
        "tool_name": tool_name,
        "tool_input": json.dumps(tool_input) if tool_input is not None else None,
        "tool_output": json.dumps(tool_output) if tool_output is not None else None,
        "status": status,
        "duration_ms": duration_ms,
    })


def save_snapshot(plan_id: str, snapshot_type: str, context_data: Any) -> str:
    """Save a context snapshot and return its SNAPSHOT_ID."""
    sql = """
        INSERT INTO TASK_CONTEXT_SNAPSHOTS (SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA)
        VALUES ('SNAP_' || AI_NEW_ID(), :plan_id, :snapshot_type, :context_data)
        RETURNING SNAPSHOT_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "plan_id": plan_id,
        "snapshot_type": snapshot_type,
        "context_data": json.dumps(context_data) if context_data is not None else None,
    })


def list_plans(agent_id: Optional[str] = None, status: Optional[str] = None,
               limit: int = 50) -> List[Dict[str, Any]]:
    """List plans with optional filters."""
    conditions = []
    params: Dict[str, Any] = {"lim": limit}
    if agent_id is not None:
        conditions.append("AGENT_ID = :agent_id")
        params["agent_id"] = agent_id
    if status is not None:
        conditions.append("STATUS = :status")
        params["status"] = status

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    try:
        sql = f"""
            SELECT PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
            FROM TASK_PLANS
            {where}
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        return [_row_to_dict(r) for r in execute_query(sql, params)]
    except Exception:
        sql = f"""
            SELECT PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
            FROM TASK_PLANS
            {where}
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        return [_row_to_dict(r) for r in execute_query(sql, params)]


def delete_plan(plan_id: str) -> bool:
    """Delete a plan and all related records."""
    execute("DELETE FROM TASK_TOOL_CALLS WHERE PLAN_ID = :plan_id", {"plan_id": plan_id})
    execute("DELETE FROM TASK_CONTEXT_SNAPSHOTS WHERE PLAN_ID = :plan_id", {"plan_id": plan_id})
    execute("DELETE FROM TASK_STEPS WHERE PLAN_ID = :plan_id", {"plan_id": plan_id})
    execute("DELETE FROM TASK_DEPENDENCIES WHERE SOURCE_PLAN_ID = :plan_id OR TARGET_PLAN_ID = :plan_id",
            {"plan_id": plan_id})
    return execute("DELETE FROM TASK_PLANS WHERE PLAN_ID = :plan_id", {"plan_id": plan_id}) > 0


def get_branch_plans(branch_id: str) -> List[Dict[str, Any]]:
    """Return all plans associated with a branch."""
    try:
        sql = """
            SELECT PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
            FROM TASK_PLANS
            WHERE BRANCH_ID = :branch_id
            ORDER BY CREATED_AT DESC
        """
        return [_row_to_dict(r) for r in execute_query(sql, {"branch_id": branch_id})]
    except Exception:
        sql = """
            SELECT PLAN_ID, AGENT_ID, GOAL, STATUS, PRIORITY, STRATEGY, RESULT_SUMMARY, BRANCH_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   TO_CHAR(COMPLETED_AT, 'YYYY-MM-DD HH24:MI:SS') AS COMPLETED_AT
            FROM TASK_PLANS
            WHERE BRANCH_ID = :branch_id
            ORDER BY CREATED_AT DESC
        """
        return [_row_to_dict(r) for r in execute_query(sql, {"branch_id": branch_id})]

def distribute_plan_to_group(plan_id: str, group_id: str) -> Dict[str, Any]:
    """Distribute plan steps to collaboration group members in round-robin."""
    from . import collab_api
    members = collab_api.list_group_members(group_id)
    active_members = [m for m in members if m.get("status") == "ACTIVE"]
    if not active_members:
        return {"plan_id": plan_id, "group_id": group_id, "assigned": 0, "message": "No active members"}
    steps = get_plan_steps(plan_id)
    if not steps:
        return {"plan_id": plan_id, "group_id": group_id, "assigned": 0, "message": "No steps"}
    assigned = 0
    for i, step in enumerate(steps):
        if step.get("status") not in ("PENDING",):
            continue
        member = active_members[i % len(active_members)]
        agent_id = member["agent_id"]
        update_step(step["step_id"], assigned_agent_id=agent_id)
        assigned += 1
    return {"plan_id": plan_id, "group_id": group_id, "assigned": assigned, "member_count": len(active_members)}


def bind_loop_to_step(step_id: str, loop_id: str, binding_type: str = 'COMPLETION', auto_start: str = 'N') -> str:
    from .loop_api import start_run
    binding_id = execute_insert_returning_id("""
        INSERT INTO TASK_LOOP_BINDING (BINDING_ID, STEP_ID, LOOP_ID, BINDING_TYPE, AUTO_START)
        VALUES (AI_NEW_ID(), :step_id, :loop_id, :binding_type, :auto_start)
        RETURNING BINDING_ID INTO :ret_id
    """, {"step_id": step_id, "loop_id": loop_id, "binding_type": binding_type, "auto_start": auto_start})
    execute("UPDATE TASK_STEPS SET LOOP_ID = :loop_id, STEP_COMPLETION_TYPE = 'LOOP' WHERE STEP_ID = :step_id", {"loop_id": loop_id, "step_id": step_id})
    if auto_start == 'Y':
        start_run(loop_id, ...)
    return binding_id

def get_step_loop(step_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("""
        SELECT b.BINDING_ID, b.STEP_ID, b.LOOP_ID, b.BINDING_TYPE, b.AUTO_START, b.CREATED_AT
        FROM TASK_LOOP_BINDING b WHERE b.STEP_ID = :step_id
    """, {"step_id": step_id})
    return _row_to_dict(row) if row else None
