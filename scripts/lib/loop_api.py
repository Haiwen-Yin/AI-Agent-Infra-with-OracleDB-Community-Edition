"""AI Agent Infra v4.0.0 - Enterprise Edition - Loop Engineering API

Loop Engineering: design goal-driven autonomous feedback loops for AI agents.
Each Loop definition is stored as an ENTITY (ENTITY_TYPE='LOOP_DEFINITION')
with metadata in LOOP_META. Runs and iterations track execution state.
"""

import json
import subprocess
import os
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from .connection import (
    execute, execute_query, execute_query_one, execute_insert_returning_id,
)
from .config import get_config


def _fire_hooks(loop_id: str, hook_event: str, context: Optional[Dict[str, Any]] = None):
    """Fire LOOP_HOOKS for the given event. Silently ignores errors."""
    try:
        from .event_bus import execute_hooks
        execute_hooks(loop_id, hook_event, context)
    except Exception as e:
        logger.debug("Hook execution failed for %s/%s: %s", loop_id, hook_event, e)


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for json_col in ("goal_definition", "stop_conditions", "evaluation_config",
                     "trigger_config", "plan_data", "actions", "observations",
                     "evaluation_result", "adjustment", "hook_config"):
        val = result.get(json_col)
        if isinstance(val, str):
            try:
                result[json_col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


# -- Loop Definition CRUD --

def create_loop(
    title: str,
    goal_definition: Dict[str, Any],
    stop_conditions: Dict[str, Any],
    evaluation_config: Dict[str, Any],
    summary: Optional[str] = None,
    trigger_config: Optional[Dict[str, Any]] = None,
    harness_template_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    owned_by_agent: Optional[str] = None,
    visibility: str = "PRIVATE",
    spec_id: Optional[str] = None,
    parent_loop_id: Optional[str] = None,
    collab_group_id: Optional[str] = None,
) -> str:
    entity_id = execute_insert_returning_id("""
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, SUMMARY, STATUS,
                              OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
                              IMPORTANCE, RETRIEVAL_COUNT, WORKSPACE_ID)
        VALUES (RAWTOHEX(SYS_GUID()), 'LOOP_DEFINITION', :title, :summary, 'ACTIVE',
                :owned_by_agent, :source_agent, :visibility, 5, 0, :workspace_id)
        RETURNING ENTITY_ID INTO :ret_id
    """, {
        "title": title, "summary": summary,
        "owned_by_agent": owned_by_agent, "source_agent": owned_by_agent,
        "visibility": visibility, "workspace_id": workspace_id,
    })
    execute("""
        INSERT INTO LOOP_META (ENTITY_ID, ENTITY_TYPE, LOOP_VERSION,
                               GOAL_DEFINITION, STOP_CONDITIONS, EVALUATION_CONFIG,
                               TRIGGER_CONFIG, HARNESS_TEMPLATE_ID, WORKSPACE_ID, BRANCH_ID,
                               SPEC_ID, PARENT_LOOP_ID, COLLAB_GROUP_ID)
        VALUES (:eid, 'LOOP_DEFINITION', '1.0',
                :goal, :stop, :eval, :trigger_cfg, :harness, :ws, :branch,
                :spec_id, :parent_loop_id, :collab_group_id)
    """, {
        "eid": entity_id,
        "goal": json.dumps(goal_definition),
        "stop": json.dumps(stop_conditions),
        "eval": json.dumps(evaluation_config),
        "trigger_cfg": json.dumps(trigger_config) if trigger_config else None,
        "harness": harness_template_id, "ws": workspace_id, "branch": branch_id,
        "spec_id": spec_id, "parent_loop_id": parent_loop_id,
        "collab_group_id": collab_group_id,
    })
    return entity_id


def get_loop(loop_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("""
        SELECT e.ENTITY_ID AS loop_id, e.TITLE, e.SUMMARY, e.STATUS, e.VISIBILITY,
               e.OWNED_BY_AGENT, e.WORKSPACE_ID, e.CREATED_AT, e.UPDATED_AT,
               m.LOOP_VERSION, m.GOAL_DEFINITION, m.STOP_CONDITIONS,
               m.EVALUATION_CONFIG, m.TRIGGER_CONFIG,
               m.HARNESS_TEMPLATE_ID, m.BRANCH_ID,
               m.SPEC_ID, m.PARENT_LOOP_ID, m.COLLAB_GROUP_ID
        FROM ENTITIES e JOIN LOOP_META m ON e.ENTITY_ID = m.ENTITY_ID
        WHERE e.ENTITY_ID = :id AND e.ENTITY_TYPE = 'LOOP_DEFINITION'
    """, {"id": loop_id})
    return _row_to_dict(row) if row else None


def update_loop(loop_id: str, **kwargs: Any) -> bool:
    count = 0
    entity_fields = {"title": "TITLE", "summary": "SUMMARY", "visibility": "VISIBILITY"}
    sets, params = [], {"id": loop_id}
    for k, v in kwargs.items():
        if k in entity_fields and v is not None:
            sets.append(f"{entity_fields[k]} = :{k}")
            params[k] = v
    if sets:
        execute(f"UPDATE ENTITIES SET {', '.join(sets)}, UPDATED_AT = SYSTIMESTAMP "
                f"WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'LOOP_DEFINITION'", params)
        count += 1
    meta_fields = {"goal_definition", "stop_conditions", "evaluation_config", "trigger_config"}
    msets, mparams = [], {"id": loop_id}
    for k, v in kwargs.items():
        if k in meta_fields and v is not None:
            msets.append(f"{k.upper()} = :{k}")
            mparams[k] = json.dumps(v) if isinstance(v, dict) else v
    if msets:
        execute(f"UPDATE LOOP_META SET {', '.join(msets)} WHERE ENTITY_ID = :id", mparams)
        count += 1
    return count > 0


def delete_loop(loop_id: str) -> bool:
    execute("DELETE FROM LOOP_ITERATIONS WHERE RUN_ID IN (SELECT RUN_ID FROM LOOP_RUNS WHERE LOOP_ID = :id)", {"id": loop_id})
    execute("DELETE FROM LOOP_RUNS WHERE LOOP_ID = :id", {"id": loop_id})
    execute("DELETE FROM LOOP_HOOKS WHERE LOOP_ID = :id", {"id": loop_id})
    execute("DELETE FROM TASK_LOOP_BINDING WHERE LOOP_ID = :id", {"id": loop_id})
    execute("DELETE FROM LOOP_META WHERE ENTITY_ID = :id", {"id": loop_id})
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :id AND ENTITY_TYPE = 'LOOP_DEFINITION'", {"id": loop_id})
    return True


def list_loops(status: Optional[str] = None, agent_id: Optional[str] = None,
               parent_loop_id: Optional[str] = None,
               collab_group_id: Optional[str] = None,
               spec_id: Optional[str] = None,
               limit: int = 50) -> List[Dict[str, Any]]:
    sql = """SELECT e.ENTITY_ID AS loop_id, e.TITLE, e.SUMMARY, e.STATUS, e.VISIBILITY,
               e.OWNED_BY_AGENT, e.WORKSPACE_ID, e.CREATED_AT,
               m.LOOP_VERSION, m.GOAL_DEFINITION
            FROM ENTITIES e JOIN LOOP_META m ON e.ENTITY_ID = m.ENTITY_ID
            WHERE e.ENTITY_TYPE = 'LOOP_DEFINITION'"""
    params: Dict[str, Any] = {"limit": limit}
    if status:
        sql += " AND e.STATUS = :status"; params["status"] = status
    if agent_id:
        sql += " AND e.OWNED_BY_AGENT = :agent_id"; params["agent_id"] = agent_id
    if parent_loop_id:
        sql += " AND m.PARENT_LOOP_ID = :parent_loop_id"; params["parent_loop_id"] = parent_loop_id
    if collab_group_id:
        sql += " AND m.COLLAB_GROUP_ID = :collab_group_id"; params["collab_group_id"] = collab_group_id
    if spec_id:
        sql += " AND m.SPEC_ID = :spec_id_filter"; params["spec_id_filter"] = spec_id
    sql += " ORDER BY e.CREATED_AT DESC FETCH FIRST :limit ROWS ONLY"
    return [_row_to_dict(r) for r in execute_query(sql, params)]


# -- Run Management --

def start_run(loop_id: str, agent_id: str, trigger_type: str = "MANUAL",
              trigger_source: Optional[str] = None,
              parent_run_id: Optional[str] = None) -> str:
    run_id = execute_insert_returning_id("""
        INSERT INTO LOOP_RUNS (RUN_ID, LOOP_ID, AGENT_ID, TRIGGER_TYPE, TRIGGER_SOURCE,
                               STATUS, ITERATION_COUNT, TOTAL_TOKENS, STARTED_AT,
                               PARENT_RUN_ID)
        VALUES (RAWTOHEX(SYS_GUID()), :loop_id, :agent_id, :trigger_type, :trigger_source,
                'RUNNING', 0, 0, SYSTIMESTAMP, :parent_run_id)
        RETURNING RUN_ID INTO :ret_id
    """, {"loop_id": loop_id, "agent_id": agent_id,
          "trigger_type": trigger_type, "trigger_source": trigger_source,
          "parent_run_id": parent_run_id})
    _fire_hooks(loop_id, "ON_START", {"run_id": run_id, "agent_id": agent_id})
    return run_id


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("""
        SELECT RUN_ID, LOOP_ID, AGENT_ID, TRIGGER_TYPE, TRIGGER_SOURCE,
               STATUS, ITERATION_COUNT, TOTAL_TOKENS, FINAL_RESULT,
               ERROR_MESSAGE, STARTED_AT, COMPLETED_AT, PARENT_RUN_ID
        FROM LOOP_RUNS WHERE RUN_ID = :id
    """, {"id": run_id})
    return dict(row) if row else None


def list_runs(loop_id: Optional[str] = None, status: Optional[str] = None,
              limit: int = 50) -> List[Dict[str, Any]]:
    sql = ("SELECT RUN_ID, LOOP_ID, AGENT_ID, TRIGGER_TYPE, TRIGGER_SOURCE, "
           "STATUS, ITERATION_COUNT, TOTAL_TOKENS, FINAL_RESULT, STARTED_AT, COMPLETED_AT "
           "FROM LOOP_RUNS WHERE 1=1")
    params: Dict[str, Any] = {"limit": limit}
    if loop_id:
        sql += " AND LOOP_ID = :loop_id"; params["loop_id"] = loop_id
    if status:
        sql += " AND STATUS = :status"; params["status"] = status
    sql += " ORDER BY STARTED_AT DESC FETCH FIRST :limit ROWS ONLY"
    return [dict(r) for r in execute_query(sql, params)]


def pause_run(run_id: str) -> bool:
    return execute("UPDATE LOOP_RUNS SET STATUS = 'PAUSED' "
                   "WHERE RUN_ID = :id AND STATUS = 'RUNNING'", {"id": run_id}) > 0


def resume_run(run_id: str) -> bool:
    return execute("UPDATE LOOP_RUNS SET STATUS = 'RUNNING' "
                   "WHERE RUN_ID = :id AND STATUS = 'PAUSED'", {"id": run_id}) > 0


def stop_run(run_id: str, reason: Optional[str] = None) -> bool:
    run = get_run(run_id)
    result = execute("UPDATE LOOP_RUNS SET STATUS = 'STOPPED', FINAL_RESULT = :reason, "
                     "COMPLETED_AT = SYSTIMESTAMP WHERE RUN_ID = :id "
                     "AND STATUS IN ('RUNNING','PAUSED')",
                     {"id": run_id, "reason": reason}) > 0
    if result:
        if run:
            _fire_hooks(run["loop_id"], "ON_STOP", {"run_id": run_id, "reason": reason})
        on_loop_run_completed(run_id)
    return result


def fail_run(run_id: str, error_message: str) -> bool:
    run = get_run(run_id)
    result = execute("UPDATE LOOP_RUNS SET STATUS = 'FAILED', ERROR_MESSAGE = :err, "
                   "COMPLETED_AT = SYSTIMESTAMP WHERE RUN_ID = :id",
                   {"id": run_id, "err": error_message}) > 0
    if result and run:
        _fire_hooks(run["loop_id"], "ON_FAIL", {"run_id": run_id, "error": error_message})
    return result


def complete_run(run_id: str, final_result: Optional[str] = None) -> bool:
    run = get_run(run_id)
    result = execute("UPDATE LOOP_RUNS SET STATUS = 'COMPLETED', FINAL_RESULT = :result, "
                     "COMPLETED_AT = SYSTIMESTAMP WHERE RUN_ID = :id "
                     "AND STATUS IN ('RUNNING','PAUSED')",
                     {"id": run_id, "result": final_result}) > 0
    if result:
        if run:
            _fire_hooks(run["loop_id"], "ON_STOP", {"run_id": run_id, "result": final_result})
        on_loop_run_completed(run_id)
    return result


# -- Collaborative & Spec-Driven Loop Features --

def create_loop_from_spec(spec_id: str, agent_id: str, **kwargs: Any) -> str:
    from .spec_api import get_spec
    spec = get_spec(spec_id)
    if not spec:
        raise ValueError(f"Spec {spec_id} not found")
    acceptance = spec.get("acceptance_criteria") or {}
    if isinstance(acceptance, str):
        acceptance = json.loads(acceptance)
    goal_definition = {"type": "SPEC_VALIDATION", "spec_id": spec_id,
                       "criteria": acceptance}
    stop_conditions = kwargs.pop("stop_conditions", {"max_iterations": 10})
    evaluation_config = {"type": "SPEC_VALIDATION", "spec_id": spec_id}
    return create_loop(
        title=kwargs.pop("title", f"Loop for spec: {spec.get('title', spec_id)}"),
        goal_definition=goal_definition,
        stop_conditions=stop_conditions,
        evaluation_config=evaluation_config,
        owned_by_agent=agent_id,
        spec_id=spec_id,
        **kwargs,
    )


def create_collab_loop(group_id: str, parent_loop_id: Optional[str],
                       agent_id: str, **kwargs: Any) -> str:
    if parent_loop_id:
        parent = get_loop(parent_loop_id)
        if not parent:
            raise ValueError(f"Parent loop {parent_loop_id} not found")
        if parent.get("parent_loop_id"):
            raise ValueError("2-level nesting limit: parent_loop_id is already a child loop")
    from .collab_api import list_group_members
    members = list_group_members(group_id)
    if not members:
        raise ValueError(f"Collaboration group {group_id} has no members")
    return create_loop(
        title=kwargs.pop("title", f"Collab loop for group {group_id}"),
        goal_definition=kwargs.pop("goal_definition", {"type": "COLLABORATIVE", "group_id": group_id}),
        stop_conditions=kwargs.pop("stop_conditions", {"max_iterations": 10}),
        evaluation_config=kwargs.pop("evaluation_config", {"type": "CONSENSUS"}),
        owned_by_agent=agent_id,
        collab_group_id=group_id,
        parent_loop_id=parent_loop_id,
        **kwargs,
    )


def create_sub_loops_for_group(parent_loop_id: str, group_id: str,
                               agent_ids: List[str]) -> List[str]:
    parent = get_loop(parent_loop_id)
    if not parent:
        raise ValueError(f"Parent loop {parent_loop_id} not found")
    if parent.get("parent_loop_id"):
        raise ValueError("Parent loop is already a sub-loop; 2-level nesting limit exceeded")
    sub_loop_ids = []
    for aid in agent_ids:
        lid = create_loop(
            title=f"Sub-loop for agent {aid}",
            goal_definition=parent.get("goal_definition", {}),
            stop_conditions=parent.get("stop_conditions", {}),
            evaluation_config=parent.get("evaluation_config", {}),
            owned_by_agent=aid,
            parent_loop_id=parent_loop_id,
            collab_group_id=group_id,
        )
        sub_loop_ids.append(lid)
    return sub_loop_ids


def aggregate_child_runs(parent_run_id: str) -> Dict[str, Any]:
    rows = execute_query("""
        SELECT RUN_ID, STATUS, FINAL_RESULT
        FROM LOOP_RUNS WHERE PARENT_RUN_ID = :parent_run_id
    """, {"parent_run_id": parent_run_id})
    total = len(rows)
    completed = sum(1 for r in rows if r["status"] == "COMPLETED")
    failed = sum(1 for r in rows if r["status"] in ("FAILED", "STOPPED", "TIMEOUT"))
    running = sum(1 for r in rows if r["status"] in ("RUNNING", "PAUSED"))
    results = [{"run_id": r["run_id"], "status": r["status"],
                "final_result": r["final_result"]} for r in rows]
    return {"total": total, "completed": completed, "failed": failed,
            "running": running, "results": results}


def bind_loop_to_step(loop_id: str, step_id: str,
                      binding_type: str = 'COMPLETION',
                      auto_start: str = 'N') -> str:
    binding_id = execute_insert_returning_id("""
        INSERT INTO TASK_LOOP_BINDING (BINDING_ID, LOOP_ID, STEP_ID, BINDING_TYPE,
                                       AUTO_START, CREATED_AT)
        VALUES (RAWTOHEX(SYS_GUID()), :loop_id, :step_id, :binding_type,
                :auto_start, SYSTIMESTAMP)
        RETURNING BINDING_ID INTO :ret_id
    """, {"loop_id": loop_id, "step_id": step_id,
          "binding_type": binding_type, "auto_start": auto_start})
    execute("UPDATE TASK_STEPS SET LOOP_ID = :loop_id, STEP_COMPLETION_TYPE = 'LOOP' "
            "WHERE STEP_ID = :step_id",
            {"loop_id": loop_id, "step_id": step_id})
    if auto_start == 'Y':
        loop = get_loop(loop_id)
        start_run(loop_id, loop.get("owned_by_agent") if loop else None)
    return binding_id


def get_step_loop(step_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("""
        SELECT b.BINDING_ID, b.LOOP_ID, b.STEP_ID, b.BINDING_TYPE,
               b.AUTO_START, b.CREATED_AT
        FROM TASK_LOOP_BINDING b WHERE b.STEP_ID = :step_id
    """, {"step_id": step_id})
    if not row:
        return None
    result = dict(row)
    loop = get_loop(result["loop_id"])
    if loop:
        result["loop"] = loop
    return result


def on_loop_run_completed(run_id: str) -> List[str]:
    run = get_run(run_id)
    if not run:
        return []
    loop_id = run["loop_id"]
    rows = execute_query("""
        SELECT STEP_ID, BINDING_TYPE FROM TASK_LOOP_BINDING
        WHERE LOOP_ID = :loop_id AND BINDING_TYPE = 'COMPLETION'
    """, {"loop_id": loop_id})
    updated = []
    for r in rows:
        execute("UPDATE TASK_STEPS SET STATUS = 'SUCCESS', COMPLETED_AT = SYSTIMESTAMP "
                "WHERE STEP_ID = :step_id", {"step_id": r["step_id"]})
        updated.append(r["step_id"])
    return updated


def create_validation_loop_for_skill(skill_id: str, agent_id: str) -> Optional[str]:
    from .skill_api import get_skill
    skill = get_skill(skill_id)
    if not skill:
        return None
    metadata = skill.get("metadata") or skill.get("skill_metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    validation_loop = metadata.get("validation_loop")
    if not validation_loop:
        return None
    if isinstance(validation_loop, str):
        validation_loop = json.loads(validation_loop)
    return create_loop(
        title=validation_loop.get("title", f"Validation loop for skill {skill_id}"),
        goal_definition=validation_loop.get("goal_definition", {"type": "SKILL_VALIDATION", "skill_id": skill_id}),
        stop_conditions=validation_loop.get("stop_conditions", {"max_iterations": 5}),
        evaluation_config=validation_loop.get("evaluation_config", {"type": "TEST"}),
        owned_by_agent=agent_id,
    )


# -- Iteration Management --

def record_iteration(
    run_id: str,
    plan_data: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    observations: Optional[Dict[str, Any]] = None,
    evaluation_result: Optional[Dict[str, Any]] = None,
    evaluation_passed: bool = False,
    adjustment: Optional[Dict[str, Any]] = None,
    token_usage: int = 0,
) -> str:
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")
    iter_id = execute_insert_returning_id("""
        INSERT INTO LOOP_ITERATIONS (ITERATION_ID, RUN_ID, ITERATION_ORDER,
                                     PLAN_DATA, ACTIONS, OBSERVATIONS,
                                     EVALUATION_RESULT, EVALUATION_PASSED, ADJUSTMENT,
                                     TOKEN_USAGE, STARTED_AT, COMPLETED_AT)
        VALUES (RAWTOHEX(SYS_GUID()), :run_id, :iter_order,
                :plan_data, :actions, :observations,
                :eval_result, :eval_passed, :adjustment,
                :tokens, SYSTIMESTAMP, SYSTIMESTAMP)
        RETURNING ITERATION_ID INTO :ret_id
    """, {
        "run_id": run_id,
        "iter_order": run["iteration_count"] + 1,
        "plan_data": json.dumps(plan_data) if plan_data else None,
        "actions": json.dumps(actions) if actions else None,
        "observations": json.dumps(observations) if observations else None,
        "eval_result": json.dumps(evaluation_result) if evaluation_result else None,
        "eval_passed": "Y" if evaluation_passed else "N",
        "adjustment": json.dumps(adjustment) if adjustment else None,
        "tokens": token_usage,
    })
    execute("UPDATE LOOP_RUNS SET ITERATION_COUNT = ITERATION_COUNT + 1, "
            "TOTAL_TOKENS = TOTAL_TOKENS + :tokens WHERE RUN_ID = :id",
            {"tokens": token_usage, "id": run_id})
    if evaluation_passed:
        execute("UPDATE LOOP_RUNS SET STATUS = 'COMPLETED', COMPLETED_AT = SYSTIMESTAMP, "
                "FINAL_RESULT = 'Goal achieved at iteration ' || TO_CHAR(ITERATION_COUNT) "
                "WHERE RUN_ID = :id", {"id": run_id})
    return iter_id


def get_iteration(iteration_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one("""
        SELECT ITERATION_ID, RUN_ID, ITERATION_ORDER, PLAN_DATA, ACTIONS,
               OBSERVATIONS, EVALUATION_RESULT, EVALUATION_PASSED,
               ADJUSTMENT, TOKEN_USAGE, STARTED_AT, COMPLETED_AT
        FROM LOOP_ITERATIONS WHERE ITERATION_ID = :id
    """, {"id": iteration_id})
    return _row_to_dict(row) if row else None


def list_iterations(run_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query("""
        SELECT ITERATION_ID, RUN_ID, ITERATION_ORDER, EVALUATION_PASSED,
               TOKEN_USAGE, STARTED_AT, COMPLETED_AT
        FROM LOOP_ITERATIONS WHERE RUN_ID = :id
        ORDER BY ITERATION_ORDER ASC FETCH FIRST :limit ROWS ONLY
    """, {"id": run_id, "limit": limit})
    return [dict(r) for r in rows]

# -- Stats & Operations --

def get_loop_stats(loop_id: str) -> Dict[str, Any]:
    try:
        row = execute_query_one("""
            SELECT
                (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id) AS total_runs,
                (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS = 'COMPLETED') AS completed,
                (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS IN ('FAILED','STOPPED','TIMEOUT')) AS failed,
                (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS IN ('RUNNING','PAUSED')) AS running,
                (SELECT COUNT(*) FROM LOOP_ITERATIONS li JOIN LOOP_RUNS lr ON li.RUN_ID = lr.RUN_ID
                 WHERE lr.LOOP_ID = :id) AS total_iterations,
                (SELECT COALESCE(SUM(TOTAL_TOKENS), 0) FROM LOOP_RUNS WHERE LOOP_ID = :id) AS total_tokens
        """, {"id": loop_id})
        return dict(row) if row else {}
    except Exception:
        try:
            row = execute_query_one("""
                SELECT
                    (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id) AS total_runs,
                    (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS = 'COMPLETED') AS completed,
                    (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS IN ('FAILED','STOPPED','TIMEOUT')) AS failed,
                    (SELECT COUNT(*) FROM LOOP_RUNS WHERE LOOP_ID = :id AND STATUS IN ('RUNNING','PAUSED')) AS running,
                    (SELECT COUNT(*) FROM LOOP_ITERATIONS li JOIN LOOP_RUNS lr ON li.RUN_ID = lr.RUN_ID
                     WHERE lr.LOOP_ID = :id) AS total_iterations,
                    (SELECT NVL(SUM(TOTAL_TOKENS), 0) FROM LOOP_RUNS WHERE LOOP_ID = :id) AS total_tokens
                FROM DUAL
            """, {"id": loop_id})
            return dict(row) if row else {}
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"get_loop_stats failed: {e}")
            return {}


def check_stop_conditions(run_id: str) -> str:
    run = get_run(run_id)
    if not run:
        return "STOP"
    loop = get_loop(run["loop_id"])
    if not loop:
        return "STOP"
    stop = loop.get("stop_conditions") or {}
    if isinstance(stop, str):
        stop = json.loads(stop)
    max_iter = stop.get("max_iterations")
    if max_iter and run["iteration_count"] >= max_iter:
        return "STOP"
    max_tokens = stop.get("max_tokens")
    if max_tokens and run["total_tokens"] >= max_tokens:
        return "STOP"
    max_dur = stop.get("max_duration_seconds")
    if max_dur and run.get("started_at"):
        elapsed = (datetime.now() - run["started_at"].replace(tzinfo=None)).total_seconds()
        if elapsed >= max_dur:
            return "TIMEOUT"
    return "CONTINUE"


# -- Hooks --

def add_hook(loop_id: str, hook_event: str, hook_type: str,
             hook_config: Optional[Dict[str, Any]] = None,
             priority: int = 5) -> str:
    return execute_insert_returning_id("""
        INSERT INTO LOOP_HOOKS (HOOK_ID, LOOP_ID, HOOK_EVENT, HOOK_TYPE,
                                HOOK_CONFIG, PRIORITY, ENABLED, CREATED_AT)
        VALUES (RAWTOHEX(SYS_GUID()), :loop_id, :event, :type,
                :config, :priority, 'Y', SYSTIMESTAMP)
        RETURNING HOOK_ID INTO :ret_id
    """, {"loop_id": loop_id, "event": hook_event, "type": hook_type,
          "config": json.dumps(hook_config) if hook_config else None,
          "priority": priority})


def remove_hook(hook_id: str) -> bool:
    return execute("DELETE FROM LOOP_HOOKS WHERE HOOK_ID = :id", {"id": hook_id}) > 0


def list_hooks(loop_id: str) -> List[Dict[str, Any]]:
    rows = execute_query("""
        SELECT HOOK_ID, LOOP_ID, HOOK_EVENT, HOOK_TYPE, HOOK_CONFIG,
               PRIORITY, ENABLED, CREATED_AT
        FROM LOOP_HOOKS WHERE LOOP_ID = :id ORDER BY PRIORITY ASC, CREATED_AT ASC
    """, {"id": loop_id})
    return [_row_to_dict(r) for r in rows]


def cleanup_old_runs(days_threshold: int = 90) -> int:
    try:
        n1 = execute("""DELETE FROM LOOP_ITERATIONS WHERE RUN_ID IN (
            SELECT RUN_ID FROM LOOP_RUNS WHERE STATUS IN ('COMPLETED','STOPPED','FAILED','TIMEOUT')
              AND COMPLETED_AT < CURRENT_TIMESTAMP - INTERVAL '%d days')""" % days_threshold)
        n2 = execute("""DELETE FROM LOOP_RUNS WHERE STATUS IN ('COMPLETED','STOPPED','FAILED','TIMEOUT')
              AND COMPLETED_AT < CURRENT_TIMESTAMP - INTERVAL '%d days'""" % days_threshold)
    except Exception:
        try:
            n1 = execute("""DELETE FROM LOOP_ITERATIONS WHERE RUN_ID IN (
                SELECT RUN_ID FROM LOOP_RUNS WHERE STATUS IN ('COMPLETED','STOPPED','FAILED','TIMEOUT')
                  AND COMPLETED_AT < SYSTIMESTAMP - :days)""", {"days": days_threshold})
            n2 = execute("""DELETE FROM LOOP_RUNS WHERE STATUS IN ('COMPLETED','STOPPED','FAILED','TIMEOUT')
                  AND COMPLETED_AT < SYSTIMESTAMP - :days""", {"days": days_threshold})
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"cleanup_old_runs failed: {e}")
            n1, n2 = 0, 0
    return n1 + n2


# -- Evaluation Engine --

def evaluate_iteration(run_id: str, iteration_id: str) -> Dict[str, Any]:
    """Evaluate an iteration using the configured evaluation method.

    Supports 6 evaluation types:
    - TEST: run a shell command, check exit code
    - DIFF: analyze git diff
    - LLM_JUDGE: call an LLM API to score the output
    - MANUAL: mark as awaiting review
    """
    run = get_run(run_id)
    if not run:
        return {"passed": False, "error": "Run not found"}

    loop = get_loop(run["loop_id"])
    if not loop:
        return {"passed": False, "error": "Loop definition not found"}

    eval_cfg = loop.get("evaluation_config") or {}
    if isinstance(eval_cfg, str):
        eval_cfg = json.loads(eval_cfg)

    eval_type = eval_cfg.get("eval_type", "MANUAL")
    iter_data = get_iteration(iteration_id) or {}

    if eval_type == "TEST":
        return _eval_test(eval_cfg, iter_data)
    elif eval_type == "DIFF":
        return _eval_diff(eval_cfg, iter_data)
    elif eval_type == "LLM_JUDGE":
        return _eval_llm_judge(eval_cfg, iter_data)
    elif eval_type == "SPEC_VALIDATION":
        return _eval_spec_validation(eval_cfg, iter_data)
    elif eval_type == "AGGREGATE":
        return _eval_aggregate(eval_cfg, iter_data)
    else:
        return _eval_manual(eval_cfg, iter_data)


def _eval_test(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Run a shell command and check exit code."""
    cmd = cfg.get("eval_command")
    if not cmd:
        return {"passed": False, "error": "No eval_command configured"}

    timeout = cfg.get("eval_timeout", 120)
    success_code = cfg.get("success_exit_code", 0)

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        passed = result.returncode == success_code

        criteria = cfg.get("success_criteria", {})
        details = {
            "exit_code": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }

        if passed and criteria.get("min_pass_rate"):
            output = result.stdout + result.stderr
            pass_match = output.count("passed")
            fail_match = output.count("failed")
            total = pass_match + fail_match
            if total > 0:
                rate = pass_match / total
                details["pass_rate"] = rate
                if rate < criteria["min_pass_rate"]:
                    passed = False

        return {"passed": passed, "eval_type": "TEST", "details": details}
    except subprocess.TimeoutExpired:
        return {"passed": False, "eval_type": "TEST", "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"passed": False, "eval_type": "TEST", "error": str(e)}


def _eval_diff(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Analyze git diff to evaluate changes."""
    diff_cmd = cfg.get("diff_command", "git diff --stat")
    max_files = cfg.get("max_files_changed")
    max_lines = cfg.get("max_lines_changed")

    try:
        result = subprocess.run(
            diff_cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        output = result.stdout
        file_count = output.count(" | ") if output else 0

        line_count = 0
        for line in output.split("\n"):
            if "+" in line or "-" in line:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        line_count += abs(int(parts[-1]))
                    except ValueError:
                        pass

        passed = True
        if max_files and file_count > max_files:
            passed = False
        if max_lines and line_count > max_lines:
            passed = False

        return {
            "passed": passed, "eval_type": "DIFF",
            "details": {"files_changed": file_count, "lines_changed": line_count,
                        "diff_summary": output[-1000:] if output else ""}
        }
    except Exception as e:
        return {"passed": False, "eval_type": "DIFF", "error": str(e)}


def _eval_llm_judge(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Call an LLM API to score the output."""
    config = get_config()
    judge_cfg = config.get("llm_judge", {})
    if not judge_cfg.get("enabled", False):
        return {"passed": False, "eval_type": "LLM_JUDGE",
                "error": "LLM_JUDGE not enabled in config"}

    api_url = judge_cfg.get("api_url", "")
    model = judge_cfg.get("model", "gpt-4o")
    timeout = judge_cfg.get("timeout", 60)
    min_score = judge_cfg.get("min_score", 7)
    prompt_template = cfg.get("eval_prompt",
        "Rate this AI agent output from 1-10 based on correctness and quality. "
        "Return JSON: {\"score\": int, \"reasoning\": string}.\n\nOutput to evaluate:\n{output}")

    output_text = ""
    if iter_data.get("observations"):
        obs = iter_data["observations"]
        if isinstance(obs, str):
            obs = json.loads(obs)
        output_text = json.dumps(obs, indent=2)[:4000]

    prompt = prompt_template.replace("{output}", output_text)

    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }).encode()

        req = urllib.request.Request(api_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = json.loads(resp.read().decode())

        content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            judge_result = json.loads(content)
        except json.JSONDecodeError:
            import re
            score_match = re.search(r'"score"\s*:\s*(\d+)', content)
            judge_result = {"score": int(score_match.group(1)) if score_match else 0,
                            "reasoning": content}

        score = judge_result.get("score", 0)
        passed = score >= min_score

        return {"passed": passed, "eval_type": "LLM_JUDGE",
                "details": {"score": score, "min_score": min_score,
                            "reasoning": judge_result.get("reasoning", "")}}
    except Exception as e:
        return {"passed": False, "eval_type": "LLM_JUDGE", "error": str(e)}


def _eval_spec_validation(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Validate iteration results against spec acceptance criteria."""
    from .spec_api import get_spec
    spec_id = cfg.get("spec_id")
    if not spec_id:
        return {"passed": False, "eval_type": "SPEC_VALIDATION", "error": "No spec_id configured"}
    spec = get_spec(spec_id)
    if not spec:
        return {"passed": False, "eval_type": "SPEC_VALIDATION", "error": f"Spec {spec_id} not found"}
    properties = spec.get("properties", {})
    criteria = properties.get("acceptance_criteria", [])
    if not criteria:
        return {"passed": True, "eval_type": "SPEC_VALIDATION", "details": {"message": "No acceptance criteria defined, auto-pass"}}
    results = []
    all_passed = True
    for criterion in criteria:
        crit_str = str(criterion).lower()
        obs = iter_data.get("observations", {})
        if isinstance(obs, str):
            try:
                obs = json.loads(obs)
            except Exception:
                obs = {}
        obs_str = json.dumps(obs).lower() if isinstance(obs, dict) else str(obs).lower()
        passed = any(kw in obs_str for kw in crit_str.split() if len(kw) > 2) or "pass" in obs_str or "success" in obs_str
        results.append({"criterion": str(criterion), "passed": passed})
        if not passed:
            all_passed = False
    return {"passed": all_passed, "eval_type": "SPEC_VALIDATION", "details": {"criteria_results": results, "total": len(criteria), "passed_count": sum(1 for r in results if r["passed"])}}


def _eval_aggregate(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Aggregate results from child/sub-loop runs."""
    parent_run_id = iter_data.get("parent_run_id") or cfg.get("parent_run_id")
    if not parent_run_id:
        return {"passed": False, "eval_type": "AGGREGATE", "error": "No parent_run_id for aggregation"}
    agg = aggregate_child_runs(parent_run_id)
    total = agg.get("total", 0)
    completed = agg.get("completed", 0)
    failed = agg.get("failed", 0)
    if total == 0:
        return {"passed": False, "eval_type": "AGGREGATE", "details": {"message": "No child runs found"}}
    all_completed = (completed + failed) == total
    all_passed = failed == 0 and completed > 0 and all_completed
    return {"passed": all_passed, "eval_type": "AGGREGATE", "details": {"total": total, "completed": completed, "failed": failed, "all_completed": all_completed, "results": agg.get("results", [])}}


def _eval_manual(cfg: Dict, iter_data: Dict) -> Dict[str, Any]:
    """Mark iteration as awaiting manual review."""
    return {"passed": False, "eval_type": "MANUAL",
            "details": {"status": "AWAITING_REVIEW",
                        "message": "Manual review required"}}


# -- Loop Execution Engine --

def execute_loop_iteration(run_id: str, agent_id: str,
                           plan_data: Optional[Dict] = None,
                           actions: Optional[Dict] = None,
                           observations: Optional[Dict] = None,
                           token_usage: int = 0) -> Dict[str, Any]:
    """Execute one full loop iteration: record + evaluate + check stop conditions.

    Returns dict with:
    - iteration_id: the recorded iteration ID
    - evaluation: evaluation result
    - stop_status: CONTINUE | STOP | TIMEOUT
    - run_status: current run status
    """
    stop_check = check_stop_conditions(run_id)
    if stop_check != "CONTINUE":
        if stop_check == "TIMEOUT":
            execute("UPDATE LOOP_RUNS SET STATUS='TIMEOUT', COMPLETED_AT=SYSTIMESTAMP "
                    "WHERE RUN_ID=:id", {"id": run_id})
        return {"iteration_id": None, "evaluation": None,
                "stop_status": stop_check, "run_status": stop_check}

    iter_id = record_iteration(
        run_id=run_id, plan_data=plan_data, actions=actions,
        observations=observations, token_usage=token_usage,
    )

    eval_result = evaluate_iteration(run_id, iter_id)
    passed = eval_result.get("passed", False)

    execute("UPDATE LOOP_ITERATIONS SET EVALUATION_RESULT=:result, "
            "EVALUATION_PASSED=:passed, ADJUSTMENT=:adj WHERE ITERATION_ID=:id",
            {"result": json.dumps(eval_result), "passed": "Y" if passed else "N",
             "adj": json.dumps({"next_action": "continue" if not passed else "done"}),
             "id": iter_id})

    run = get_run(run_id)
    if run:
        _fire_hooks(run["loop_id"], "POST_ITERATION",
                     {"run_id": run_id, "iteration_id": iter_id, "passed": passed})

    if passed:
        execute("UPDATE LOOP_RUNS SET STATUS='COMPLETED', COMPLETED_AT=SYSTIMESTAMP, "
                "FINAL_RESULT='Goal achieved' WHERE RUN_ID=:id", {"id": run_id})
        on_loop_run_completed(run_id)
        return {"iteration_id": iter_id, "evaluation": eval_result,
                "stop_status": "STOP", "run_status": "COMPLETED"}

    stop_check = check_stop_conditions(run_id)
    if stop_check != "CONTINUE":
        if stop_check == "TIMEOUT":
            execute("UPDATE LOOP_RUNS SET STATUS='TIMEOUT', COMPLETED_AT=SYSTIMESTAMP "
                    "WHERE RUN_ID=:id", {"id": run_id})
        else:
            execute("UPDATE LOOP_RUNS SET STATUS='STOPPED', COMPLETED_AT=SYSTIMESTAMP "
                    "WHERE RUN_ID=:id", {"id": run_id})

    return {"iteration_id": iter_id, "evaluation": eval_result,
            "stop_status": stop_check,
            "run_status": "TIMEOUT" if stop_check == "TIMEOUT" else
                          ("STOPPED" if stop_check == "STOP" else "RUNNING")}
