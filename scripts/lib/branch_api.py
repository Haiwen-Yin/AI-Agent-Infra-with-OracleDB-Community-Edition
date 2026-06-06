"""AI Agent Infra v3.3.0 - Context Branching API

Context branch lifecycle management: fork, merge, abandon, pause, resume,
branch comparison, conflict detection, and lesson extraction from abandoned branches.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, get_connection

import oracledb

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"context_data", "metadata", "conflicts"}


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    for key in result:
        if key.lower() in _JSON_COLUMNS and isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def fork_branch(
    workspace_id: str,
    fork_context_id: str,
    branch_name: str,
    branch_type: str,
    agent_id: str,
    source_agent_id: Optional[str] = None,
    purpose: Optional[str] = None,
    fork_session_id: Optional[str] = None,
) -> str:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            BEGIN
                :result := BRANCH_MANAGER.fork_branch(
                    :vwid, :vfcid, :vbname, :vbtype, :vaid,
                    :vsaid, :vpurpose, :vfsid
                );
            END;
        """, {
            "vwid": workspace_id,
            "vfcid": fork_context_id,
            "vbname": branch_name,
            "vbtype": branch_type,
            "vaid": agent_id,
            "vsaid": source_agent_id,
            "vpurpose": purpose,
            "vfsid": fork_session_id,
            "result": cur.var(str),
        })
        result = cur.bindvars["result"].getvalue()
        conn.commit()
        return result


def get_branch(branch_id: str) -> Optional[Dict[str, Any]]:
    sql = "SELECT BRANCH_MANAGER.get_branch(:vbid) AS bj FROM DUAL"
    row = execute_query_one(sql, {"vbid": branch_id})
    if row and row.get("bj"):
        val = row["bj"]
        if isinstance(val, str):
            return json.loads(val)
        return val
    return None


def get_branch_tree(workspace_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT BRANCH_ID, PARENT_BRANCH_ID, BRANCH_NAME, BRANCH_TYPE,
               BRANCH_STATUS, AGENT_ID, FORK_CONTEXT_ID,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(CLOSED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CLOSED_AT
        FROM CONTEXT_BRANCHES
        WHERE WORKSPACE_ID = :vwid
        ORDER BY CREATED_AT ASC
    """
    rows = execute_query(sql, {"vwid": workspace_id})
    flat = [_row_to_dict(r) for r in rows]
    children_map: Dict[str, List] = {}
    roots = []
    for b in flat:
        children_map.setdefault(b.get("parent_branch_id"), []).append(b)
    for b in flat:
        b["children"] = children_map.get(b["branch_id"], [])
    for b in flat:
        if b.get("parent_branch_id") is None:
            roots.append(b)
    return roots


def get_branch_context_chain(branch_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
        SELECT CONTEXT_ID, WORKSPACE_ID, AGENT_ID, SESSION_ID,
               CONTEXT_TYPE, CONTEXT_DATA, PARENT_CONTEXT_ID, BRANCH_ID,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM WORKSPACE_CONTEXT
        WHERE BRANCH_ID = :vbid
        ORDER BY CREATED_AT ASC
        FETCH FIRST :vlim ROWS ONLY
    """
    rows = execute_query(sql, {"vbid": branch_id, "vlim": limit})
    return [_row_to_dict(r) for r in rows]


def diff_branches(branch_a_id: str, branch_b_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT 'ONLY_IN_A' AS diff_side, CONTEXT_ID, CONTEXT_TYPE,
               AGENT_ID, TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM WORKSPACE_CONTEXT
        WHERE BRANCH_ID = :vaid AND CONTEXT_TYPE != 'BRANCH_POINT'
        UNION ALL
        SELECT 'ONLY_IN_B' AS diff_side, CONTEXT_ID, CONTEXT_TYPE,
               AGENT_ID, TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM WORKSPACE_CONTEXT
        WHERE BRANCH_ID = :vbid AND CONTEXT_TYPE != 'BRANCH_POINT'
        ORDER BY diff_side, CREATED_AT ASC
    """
    rows = execute_query(sql, {"vaid": branch_a_id, "vbid": branch_b_id})
    return [_row_to_dict(r) for r in rows]


def detect_conflicts(source_branch_id: str, target_branch_id: str) -> Dict[str, Any]:
    sql = """
        SELECT BRANCH_MANAGER.detect_conflicts(:vsbid, :vtbid) AS cj FROM DUAL
    """
    row = execute_query_one(sql, {"vsbid": source_branch_id, "vtbid": target_branch_id})
    if row and row.get("cj"):
        val = row["cj"]
        if isinstance(val, str):
            return json.loads(val)
        return val
    return {"total_conflicts": 0}


def merge_branch(
    source_branch_id: str,
    target_branch_id: str,
    merge_type: str = "MERGE",
    merged_by_agent: str = "",
    conflict_resolutions: Optional[Dict] = None,
) -> Dict[str, Any]:
    conflicts = detect_conflicts(source_branch_id, target_branch_id)
    total = conflicts.get("total_conflicts", 0)
    if total > 0 and conflict_resolutions is None:
        return {
            "status": "CONFLICTS_DETECTED",
            "conflicts": conflicts,
            "merge_id": None,
            "message": "Conflicts detected. Provide conflict_resolutions to proceed.",
        }
    cr_json = json.dumps(conflict_resolutions) if conflict_resolutions else None
    sql = """
        CALL BRANCH_MANAGER.merge_branch(
            :vsbid, :vtbid, :vmtype, :vmagent, CAST(:vcr AS JSON)
        )
    """
    execute(sql, {
        "vsbid": source_branch_id,
        "vtbid": target_branch_id,
        "vmtype": merge_type,
        "vmagent": merged_by_agent,
        "vcr": cr_json,
    })
    result = "PARTIAL" if total > 0 else "SUCCESS"
    return {"status": result, "conflicts": conflicts}


def abandon_branch(branch_id: str, reason: Optional[str] = None) -> bool:
    sql = "CALL BRANCH_MANAGER.abandon_branch(:vbid, :vreason)"
    execute(sql, {"vbid": branch_id, "vreason": reason})
    return True


def pause_branch(branch_id: str) -> bool:
    sql = "CALL BRANCH_MANAGER.pause_branch(:vbid)"
    execute(sql, {"vbid": branch_id})
    return True


def resume_branch(branch_id: str) -> bool:
    sql = "CALL BRANCH_MANAGER.resume_branch(:vbid)"
    execute(sql, {"vbid": branch_id})
    return True


def get_agent_branches(agent_id: str, status: str = "ACTIVE") -> List[Dict[str, Any]]:
    sql = """
        SELECT BRANCH_ID, WORKSPACE_ID, PARENT_BRANCH_ID, BRANCH_NAME,
               BRANCH_TYPE, BRANCH_STATUS, FORK_CONTEXT_ID,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(CLOSED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CLOSED_AT
        FROM CONTEXT_BRANCHES
        WHERE AGENT_ID = :vaid
          AND BRANCH_STATUS = :vstatus
        ORDER BY CREATED_AT DESC
    """
    rows = execute_query(sql, {"vaid": agent_id, "vstatus": status})
    return [_row_to_dict(r) for r in rows]


def get_branch_stats(branch_id: str) -> Dict[str, Any]:
    sql = "SELECT BRANCH_MANAGER.get_branch_stats(:vbid) AS sj FROM DUAL"
    row = execute_query_one(sql, {"vbid": branch_id})
    if row and row.get("sj"):
        val = row["sj"]
        if isinstance(val, str):
            return json.loads(val)
        return val
    return {"branch_id": branch_id, "error": "not found"}


def mark_as_lesson(
    branch_id: str,
    context_id: str,
    lesson_type: str,
    lesson_summary: str,
    lesson_detail: Optional[str] = None,
    agent_id: str = "",
) -> str:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            BEGIN
                :result := BRANCH_MANAGER.mark_as_lesson(
                    :vbid, :vcid, :vltype, :vlsum, :vldet, :vaid
                );
            END;
        """, {
            "vbid": branch_id,
            "vcid": context_id,
            "vltype": lesson_type,
            "vlsum": lesson_summary,
            "vldet": lesson_detail,
            "vaid": agent_id,
            "result": cur.var(str),
        })
        result = cur.bindvars["result"].getvalue()
        conn.commit()
        return result


def extract_lessons_from_branch(
    branch_id: str,
    auto_confirm: bool = False,
) -> Dict[str, Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        ret_var = cur.var(oracledb.DB_TYPE_JSON)
        cur.execute("""
            BEGIN
                :result := BRANCH_MANAGER.extract_lessons(:vbid, :vac);
            END;
        """, {
            "vbid": branch_id,
            "vac": "Y" if auto_confirm else "N",
            "result": ret_var,
        })
        val = ret_var.getvalue()
        conn.commit()
        if val:
            if isinstance(val, str):
                return json.loads(val)
            return val
    return {"branch_id": branch_id, "error": "extraction failed"}


def list_branches(
    workspace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    branch_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    conditions = []
    params: Dict[str, Any] = {"vlim": limit}
    if workspace_id:
        conditions.append("WORKSPACE_ID = :vwid")
        params["vwid"] = workspace_id
    if agent_id:
        conditions.append("AGENT_ID = :vaid")
        params["vaid"] = agent_id
    if status:
        conditions.append("BRANCH_STATUS = :vstatus")
        params["vstatus"] = status
    if branch_type:
        conditions.append("BRANCH_TYPE = :vbtype")
        params["vbtype"] = branch_type
    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
        SELECT BRANCH_ID, WORKSPACE_ID, PARENT_BRANCH_ID, BRANCH_NAME,
               BRANCH_TYPE, BRANCH_STATUS, AGENT_ID, SOURCE_AGENT_ID,
               FORK_CONTEXT_ID, BRANCH_PURPOSE,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(CLOSED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CLOSED_AT
        FROM CONTEXT_BRANCHES
        WHERE {where}
        ORDER BY CREATED_AT DESC
        FETCH FIRST :vlim ROWS ONLY
    """
    rows = execute_query(sql, params)
    return [_row_to_dict(r) for r in rows]

def fork_branch_for_spec(workspace_id: str, spec_id: str, branch_name: str,
                         agent_id: str, source_agent_id: Optional[str] = None) -> str:
    """Fork a branch for implementing a spec. Returns BRANCH_ID."""
    from . import spec_api
    spec = spec_api.get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")
    purpose = f"Implement spec: {spec.get('title', spec_id)}"
    branch_id = fork_branch(
        workspace_id=workspace_id,
        fork_context_id=None,
        branch_name=branch_name,
        branch_type="EXPLORATION",
        agent_id=agent_id,
        source_agent_id=source_agent_id,
        purpose=purpose,
    )
    return branch_id


def merge_branch_with_validation(source_branch_id: str, target_branch_id: str,
                                  spec_id: Optional[str] = None,
                                  merged_by_agent: Optional[str] = None,
                                  conflict_resolutions: Optional[Any] = None) -> Dict[str, Any]:
    """Merge a branch with optional spec validation. Returns merge result + validation."""
    result = {"merge_status": None, "validation": None}
    merge_branch(
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        merged_by_agent=merged_by_agent,
        conflict_resolutions=conflict_resolutions,
    )
    result["merge_status"] = "completed"
    if spec_id:
        from . import spec_api
        validation = spec_api.validate_branch_against_spec(source_branch_id, spec_id)
        result["validation"] = validation
    return result

def fork_parallel_branches(workspace_id: str, agent_ids: List[str],
                           branch_name_prefix: str = "parallel",
                           spec_id: Optional[str] = None,
                           purpose: Optional[str] = None) -> Dict[str, Any]:
    """Create PARALLEL branches for multiple agents. Returns {branch_id: agent_id} mapping."""
    results = []
    for i, agent_id in enumerate(agent_ids):
        branch_name = f"{branch_name_prefix}-{agent_id}-{i+1}"
        branch_purpose = purpose or f"Parallel exploration by {agent_id}"
        if spec_id:
            branch_purpose = f"Implement spec {spec_id}: {branch_purpose}"
        bid = fork_branch(
            workspace_id=workspace_id,
            fork_context_id=None,
            branch_name=branch_name,
            branch_type="PARALLEL",
            agent_id=agent_id,
            purpose=branch_purpose,
        )
        results.append({"branch_id": bid, "agent_id": agent_id, "branch_name": branch_name})
    return {"workspace_id": workspace_id, "branches": results, "count": len(results)}


def merge_parallel_branches(source_branch_ids: List[str], target_branch_id: str,
                            merged_by_agent: Optional[str] = None) -> Dict[str, Any]:
    """Merge multiple parallel branches into a target branch.

    Detects conflicts across all sources before merging.
    Returns summary of merge results.
    """
    agent = merged_by_agent or "SYSTEM"
    all_conflicts = []
    merged = []
    
    for src_id in source_branch_ids:
        try:
            conflicts = detect_conflicts(src_id, target_branch_id)
            conflict_count = conflicts.get("total_conflicts", 0)
            if conflict_count > 0:
                all_conflicts.append({"source_branch_id": src_id, "conflicts": conflicts})
            else:
                merge_branch(
                    source_branch_id=src_id,
                    target_branch_id=target_branch_id,
                    merge_type="MERGE",
                    merged_by_agent=agent,
                )
                merged.append(src_id)
        except Exception as e:
            all_conflicts.append({"source_branch_id": src_id, "error": str(e)})
    
    return {
        "merged_count": len(merged),
        "merged": merged,
        "conflict_count": len(all_conflicts),
        "conflicts": all_conflicts,
    }


def get_parallel_diff(branch_ids: List[str]) -> List[Dict[str, Any]]:
    """Compare multiple parallel branches pairwise. Returns diff for each pair."""
    diffs = []
    for i in range(len(branch_ids)):
        for j in range(i + 1, len(branch_ids)):
            try:
                diff = diff_branches(branch_ids[i], branch_ids[j])
                diffs.append({
                    "branch_a": branch_ids[i],
                    "branch_b": branch_ids[j],
                    "diff": diff,
                })
            except Exception as e:
                diffs.append({
                    "branch_a": branch_ids[i],
                    "branch_b": branch_ids[j],
                    "error": str(e),
                })
    return diffs
