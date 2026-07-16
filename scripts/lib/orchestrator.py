"""AI Agent Infra v3.10.2 - Community Edition - Multi-Agent Orchestration

DAG execution engine, fan-out/fan-in, pipeline orchestration,
and retry policies for task steps.

Tables: STEP_RETRY_POLICY, STEP_EXECUTION_PLAN
"""

import logging
import threading
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert,
    sanitize_row,
)
from . import loop_api
from . import collab_api

logger = logging.getLogger(__name__)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    return sanitize_row(row)


def resolve_dag(plan_id: str) -> List[Dict[str, Any]]:
    clauses = execute_query(
        "SELECT * FROM TASK_DEPENDENCIES WHERE PLAN_ID = :pid",
        {"pid": plan_id},
    )
    steps = execute_query(
        "SELECT * FROM TASK_STEPS WHERE PLAN_ID = :pid ORDER BY STEP_ORDER",
        {"pid": plan_id},
    )
    if not steps:
        return []

    step_ids = {s["step_id"] for s in steps}
    deps: Dict[str, Set[str]] = {s["step_id"]: set() for s in steps}
    for dep in clauses:
        child = dep.get("child_step_id") or dep.get("dependent_step_id")
        parent = dep.get("parent_step_id") or dep.get("dependency_step_id")
        if child and parent and child in step_ids and parent in step_ids:
            deps[child].add(parent)

    in_degree = {sid: len(d) for sid, d in deps.items()}
    queue = deque([sid for sid, d in in_degree.items() if d == 0])
    sorted_steps: List[str] = []
    while queue:
        sid = queue.popleft()
        sorted_steps.append(sid)
        for other_sid, d in deps.items():
            if sid in d:
                d.discard(sid)
                in_degree[other_sid] -= 1
                if in_degree[other_sid] == 0:
                    queue.append(other_sid)

    if len(sorted_steps) != len(step_ids):
        raise ValueError(f"Cycle detected in DAG for plan {plan_id}")

    groups: List[Dict[str, Any]] = []
    current_group: List[str] = []
    for sid in sorted_steps:
        if in_degree.get(sid, 0) == 0 and current_group:
            prev = steps[[s["step_id"] for s in steps].index(current_group[-1])]
            curr = steps[[s["step_id"] for s in steps].index(sid)]
            if prev.get("step_order") == curr.get("step_order"):
                current_group.append(sid)
            else:
                groups.append({"parallel_group": len(groups) + 1, "steps": current_group})
                current_group = [sid]
        else:
            if current_group:
                groups.append({"parallel_group": len(groups) + 1, "steps": current_group})
            current_group = [sid]
    if current_group:
        groups.append({"parallel_group": len(groups) + 1, "steps": current_group})

    for group in groups:
        for sid in group["steps"]:
            execute(
                """INSERT INTO STEP_EXECUTION_PLAN (PLAN_ID, ROOT_PLAN_ID, STEP_GROUP_ID, STEP_ORDER, STEP_ID, STATUS)
                   VALUES (RAWTOHEX(SYS_GUID()), :root, :gid, :p_order, :sid, 'PENDING')""",
                {"root": plan_id, "gid": group["parallel_group"],
                 "order": group["parallel_group"], "sid": sid},
            )
    return groups


def execute_dag(plan_id: str) -> Dict[str, Any]:
    groups = resolve_dag(plan_id)
    results = {"total_steps": 0, "completed": 0, "failed": 0, "skipped": 0}

    for group in groups:
        for step_id in group["steps"]:
            results["total_steps"] += 1
            try:
                ok = execute_step_with_retry(step_id)
                if ok:
                    results["completed"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error("Step %s failed: %s", step_id, e)
                results["failed"] += 1
    return results


def fan_out(
    step_id: str,
    agent_ids: List[str],
    loop_goal: str,
    evaluation_type: str = "AGGREGATE",
) -> Dict[str, Any]:
    step = execute_query_one(
        "SELECT PLAN_ID, BRANCH_ID FROM TASK_STEPS WHERE STEP_ID = :sid",
        {"sid": step_id},
    )
    if not step:
        raise ValueError(f"Step not found: {step_id}")

    groups = collab_api.get_agent_groups(agent_ids[0]) if agent_ids else []
    group_id = groups[0]["group_id"] if groups else None
    if not group_id:
        raise ValueError(f"Agent {agent_ids[0]} has no collaboration group")

    parent_loop_id = loop_api.create_loop(
        title=f"Fan-out: {step_id}",
        goal_definition=loop_goal,
        agent_id=agent_ids[0],
        workspace_id=None,
        evaluation_type=evaluation_type,
    )

    sub_loop_ids: List[str] = []
    for agent_id in agent_ids:
        sub_id = loop_api.create_loop(
            title=f"Sub-loop for {agent_id}",
            goal_definition=loop_goal,
            agent_id=agent_id,
            workspace_id=None,
            parent_loop_id=parent_loop_id,
        )
        sub_loop_ids.append(sub_id)

    return {"parent_loop_id": parent_loop_id, "sub_loop_ids": sub_loop_ids}


def fan_in(parent_loop_id: str, strategy: str = "CONSENSUS") -> Dict[str, Any]:
    agg = loop_api.aggregate_child_runs(parent_loop_id)
    if not agg or agg.get("total", 0) == 0:
        return {"strategy": strategy, "result": None, "scores": []}

    child_runs = agg.get("runs", [])
    completed = [r for r in child_runs if r.get("status") == "COMPLETED"]
    failed = [r for r in child_runs if r.get("status") == "FAILED"]

    result: Dict[str, Any] = {"strategy": strategy, "total": agg["total"],
                              "completed": len(completed), "failed": len(failed)}

    if strategy == "CONSENSUS":
        passed = sum(1 for r in completed if r.get("eval_passed") == "Y")
        result["result"] = "PASS" if passed > len(completed) / 2 else "FAIL"
        result["scores"] = [{"run_id": r.get("run_id"), "passed": r.get("eval_passed")} for r in completed]
    elif strategy == "BEST_OF_N":
        best = max(completed, key=lambda r: r.get("eval_score", 0)) if completed else None
        result["result"] = best
        result["scores"] = [{"run_id": r.get("run_id"), "score": r.get("eval_score", 0)} for r in completed]
    elif strategy == "CONCATENATE":
        result["result"] = [r.get("final_result") for r in completed]
        result["scores"] = [{"run_id": r.get("run_id"), "result": r.get("final_result")} for r in completed]
    elif strategy == "FIRST":
        first = completed[0] if completed else None
        result["result"] = first.get("final_result") if first else None
        result["scores"] = [{"run_id": first.get("run_id")} for first in completed[:1]]
    else:
        result["result"] = "UNKNOWN_STRATEGY"

    return result


def create_pipeline(step_ids: List[str], mode: str = "SEQUENTIAL") -> str:
    if mode not in ("SEQUENTIAL", "PARALLEL", "CONDITIONAL"):
        raise ValueError(f"Unknown pipeline mode: {mode}")

    plan_id = execute_insert_returning_id(
        "INSERT INTO TASK_PLANS (PLAN_ID, AGENT_ID, GOAL, STRATEGY, STATUS) VALUES (RAWTOHEX(SYS_GUID()), 'SYSTEM', 'Pipeline', :p_mode, 'PENDING') RETURNING PLAN_ID INTO :ret_id",
        {"p_mode": mode},
    )

    for order, step_id in enumerate(step_ids, 1):
        parallel_group = 1 if mode == "PARALLEL" else order
        execute(
            """INSERT INTO STEP_EXECUTION_PLAN (PLAN_ID, ROOT_PLAN_ID, STEP_GROUP_ID, STEP_ORDER, STEP_ID, STATUS)
               VALUES (RAWTOHEX(SYS_GUID()), :root, :gid, :p_order, :sid, 'PENDING')""",
            {"root": plan_id, "gid": parallel_group, "p_order": order, "sid": step_id},
        )
    return plan_id


def add_retry_policy(
    step_id: str,
    max_retries: int = 3,
    backoff_seconds: int = 5,
    backoff_multiplier: float = 2.0,
    timeout_seconds: Optional[int] = None,
    fallback_action: str = "FAIL",
) -> str:
    return execute_insert_returning_id(
        """INSERT INTO STEP_RETRY_POLICY
           (POLICY_ID, STEP_ID, MAX_RETRIES, BACKOFF_SECONDS, BACKOFF_MULTIPLIER,
            TIMEOUT_SECONDS, FALLBACK_ACTION, RETRY_COUNT)
           VALUES (RAWTOHEX(SYS_GUID()), :sid, :max_r, :bo_sec, :bo_mult,
                   :timeout, :fallback, 0) RETURNING POLICY_ID INTO :ret_id""",
        {"sid": step_id, "max_r": max_retries, "bo_sec": backoff_seconds,
         "bo_mult": backoff_multiplier, "timeout": timeout_seconds, "fallback": fallback_action},
    )


def get_execution_status(plan_id: str) -> Dict[str, Any]:
    rows = execute_query(
        "SELECT STATUS, COUNT(*) AS CNT FROM STEP_EXECUTION_PLAN WHERE ROOT_PLAN_ID = :pid GROUP BY STATUS",
        {"pid": plan_id},
    )
    status_counts = {r["status"]: r["cnt"] for r in rows}
    total = sum(status_counts.values())
    return {
        "total": total,
        "completed": status_counts.get("COMPLETED", 0),
        "running": status_counts.get("RUNNING", 0),
        "failed": status_counts.get("FAILED", 0),
        "pending": status_counts.get("PENDING", 0),
        "skipped": status_counts.get("SKIPPED", 0),
    }


def execute_step_with_retry(step_id: str) -> bool:
    policy = execute_query_one(
        "SELECT * FROM STEP_RETRY_POLICY WHERE STEP_ID = :sid",
        {"sid": step_id},
    )

    max_retries = policy.get("max_retries", 0) if policy else 0
    backoff = policy.get("backoff_seconds", 5) if policy else 5
    multiplier = policy.get("backoff_multiplier", 2.0) if policy else 2.0
    timeout = policy.get("timeout_seconds") if policy else None
    fallback = policy.get("fallback_action", "FAIL") if policy else "FAIL"

    step = execute_query_one(
        "SELECT * FROM TASK_STEPS WHERE STEP_ID = :sid",
        {"sid": step_id},
    )
    if not step:
        logger.error("Step %s not found", step_id)
        return False

    # v3.9.0: Check if step requires approval before execution
    try:
        from .approval_api import check_approval_needed, get_pending_for_entity, create_request
        if check_approval_needed("STEP", step_id):
            pending = get_pending_for_entity("STEP", step_id)
            if pending:
                logger.info("Step %s waiting for approval %s", step_id, pending.get("approval_id"))
                execute(
                    "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'PAUSED' WHERE STEP_ID = :sid AND STATUS = 'PENDING'",
                    {"sid": step_id},
                )
                return False
            else:
                requested_by = step.get("agent_id", "system")
                create_request("STEP", step_id, requested_by)
                execute(
                    "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'PAUSED' WHERE STEP_ID = :sid AND STATUS = 'PENDING'",
                    {"sid": step_id},
                )
                logger.info("Step %s paused for approval", step_id)
                return False
    except Exception as e:
        logger.warning("Approval check failed for step %s: %s", step_id, e)

    for attempt in range(max_retries + 1):
        execute(
            "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'RUNNING', STARTED_AT = SYSTIMESTAMP WHERE STEP_ID = :sid AND STATUS = 'PENDING'",
            {"sid": step_id},
        )
        try:
            loop_id = step.get("loop_id")
            if loop_id:
                from . import loop_api
                runs = loop_api.get_runs_for_loop(loop_id)
                active_runs = [r for r in runs if r.get("status") == "RUNNING"]
                if active_runs:
                    logger.info("Step %s waiting for loop %s to complete", step_id, loop_id)
                    continue

            execute(
                "UPDATE TASK_STEPS SET STATUS = 'SUCCESS', COMPLETED_AT = SYSTIMESTAMP WHERE STEP_ID = :sid",
                {"sid": step_id},
            )
            execute(
                "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'COMPLETED', COMPLETED_AT = SYSTIMESTAMP WHERE STEP_ID = :sid",
                {"sid": step_id},
            )
            if policy:
                execute(
                    "UPDATE STEP_RETRY_POLICY SET RETRY_COUNT = :cnt, LAST_RETRY_AT = SYSTIMESTAMP WHERE POLICY_ID = :pid",
                    {"cnt": attempt, "pid": policy["policy_id"]},
                )
            return True
        except Exception as e:
            logger.warning("Step %s attempt %d failed: %s", step_id, attempt + 1, e)
            if attempt < max_retries:
                import time
                wait = backoff * (multiplier ** attempt)
                time.sleep(wait)
                if policy:
                    execute(
                        "UPDATE STEP_RETRY_POLICY SET RETRY_COUNT = :cnt, LAST_RETRY_AT = SYSTIMESTAMP WHERE POLICY_ID = :pid",
                        {"cnt": attempt + 1, "pid": policy["policy_id"]},
                    )
            else:
                if fallback == "SKIP":
                    execute(
                        "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'SKIPPED' WHERE STEP_ID = :sid",
                        {"sid": step_id},
                    )
                    return False
                elif fallback == "NOTIFY_COORDINATOR":
                    logger.error("Step %s exhausted retries, notifying coordinator", step_id)
                execute(
                    "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'FAILED' WHERE STEP_ID = :sid",
                    {"sid": step_id},
                )
                return False
    return False


def approve_step(step_id: str, approver: str) -> bool:
    """Approve a paused step and resume it."""
    from .approval_api import approve, get_pending_for_entity
    pending = get_pending_for_entity("STEP", step_id)
    if not pending:
        return False
    result = approve(pending["approval_id"], approver)
    if result:
        execute(
            "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'PENDING', APPROVED_BY = :approver, APPROVED_AT = SYSTIMESTAMP WHERE STEP_ID = :sid AND STATUS = 'PAUSED'",
            {"approver": approver, "sid": step_id},
        )
        logger.info("Step %s approved by %s, resuming", step_id, approver)
    return result


def reject_step(step_id: str, approver: str, reason: str = "") -> bool:
    """Reject a paused step and skip it."""
    from .approval_api import reject, get_pending_for_entity
    pending = get_pending_for_entity("STEP", step_id)
    if not pending:
        return False
    result = reject(pending["approval_id"], approver, reason)
    if result:
        execute(
            "UPDATE STEP_EXECUTION_PLAN SET STATUS = 'SKIPPED', APPROVED_BY = :approver, APPROVED_AT = SYSTIMESTAMP WHERE STEP_ID = :sid AND STATUS = 'PAUSED'",
            {"approver": approver, "sid": step_id},
        )
        logger.info("Step %s rejected by %s: %s", step_id, approver, reason)
    return result
