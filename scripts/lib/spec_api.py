"""AI Agent Infra v3.5.0 - Community Edition - Spec API

Spec Driven Development: create/manage specification documents with plan linkage and validation.
"""

import json
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)


def create_spec(
    title: str,
    content: Optional[str] = None,
    summary: Optional[str] = None,
    category: Optional[str] = None,
    importance: int = 5,
    owned_by_agent: Optional[str] = None,
    visibility: str = "SHARED",
    workspace_id: Optional[str] = None,
    spec_scope: Optional[str] = None,
    complexity: str = "MEDIUM",
    acceptance_criteria: Optional[Any] = None,
    constraints: Optional[Any] = None,
    parent_spec_id: Optional[str] = None,
    branch_id: Optional[str] = None,
) -> str:
    """Create a specification document. Returns ENTITY_ID."""
    entity_sql = """
        INSERT INTO ENTITIES (ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY,
                              CATEGORY, STATUS, OWNED_BY_AGENT, VISIBILITY,
                              IMPORTANCE, WORKSPACE_ID)
        VALUES (RAWTOHEX(SYS_GUID()), 'SPEC', :title, :content, :summary,
                :category, 'ACTIVE', :owned_by_agent, :visibility,
                :importance, :workspace_id)
        RETURNING ENTITY_ID INTO :ret_id
    """
    entity_id = execute_insert_returning_id(entity_sql, {
        "title": title,
        "content": content,
        "summary": summary,
        "category": category,
        "owned_by_agent": owned_by_agent,
        "visibility": visibility,
        "importance": importance,
        "workspace_id": workspace_id,
    })

    ac_val = json.dumps(acceptance_criteria) if acceptance_criteria and not isinstance(acceptance_criteria, str) else acceptance_criteria
    cs_val = json.dumps(constraints) if constraints and not isinstance(constraints, str) else constraints

    meta_sql = """
        INSERT INTO SPEC_META (ENTITY_ID, ENTITY_TYPE, SPEC_VERSION, SPEC_STATUS,
                               ACCEPTANCE_CRITERIA, "CONSTRAINTS", SPEC_SCOPE,
                               COMPLEXITY, PARENT_SPEC_ID, BRANCH_ID)
        VALUES (:eid, 'SPEC', 1, 'DRAFT', :ac, :cs, :scope, :complexity, :parent_id, :branch_id)
    """
    execute(meta_sql, {
        "eid": entity_id,
        "ac": ac_val,
        "cs": cs_val,
        "scope": spec_scope,
        "complexity": complexity,
        "parent_id": parent_spec_id,
        "branch_id": branch_id,
    })

    return entity_id


def get_spec(entity_id: str) -> Optional[Dict[str, Any]]:
    """Get spec with metadata and plan links. Returns dict or None."""
    sql = """
        SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY,
               e.CATEGORY, e.STATUS, e.OWNED_BY_AGENT, e.VISIBILITY, e.IMPORTANCE,
               e.WORKSPACE_ID,
               TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               sm.SPEC_VERSION, sm.SPEC_STATUS, sm.ACCEPTANCE_CRITERIA,
               sm."CONSTRAINTS", sm.SPEC_SCOPE, sm.COMPLEXITY, sm.PARENT_SPEC_ID
        FROM ENTITIES e
        LEFT JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID
                               AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE e.ENTITY_ID = :eid AND e.ENTITY_TYPE = 'SPEC'
    """
    row = execute_query_one(sql, {"eid": entity_id})
    if row is None:
        return None

    result = sanitize_row(row)

    links_sql = """
        SELECT LINK_ID, SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM SPEC_PLAN_LINKS
        WHERE SPEC_ID = :sid
    """
    links = execute_query(links_sql, {"sid": entity_id})
    result["plan_links"] = [sanitize_row(l) for l in links]
    return result


def update_spec(entity_id: str, **kwargs: Any) -> bool:
    """Update spec content or metadata. Returns True/False."""
    entity_fields = {"title", "content", "summary", "category", "importance",
                     "visibility", "status"}
    meta_fields = {"spec_status", "spec_scope", "complexity",
                   "acceptance_criteria", "constraints"}

    entity_updates: Dict[str, Any] = {}
    meta_updates: Dict[str, Any] = {}

    for k, v in kwargs.items():
        lk = k.lower()
        if lk in entity_fields and v is not None:
            entity_updates[lk] = v
        elif lk in meta_fields and v is not None:
            if lk in ("acceptance_criteria", "constraints") and not isinstance(v, str):
                meta_updates[lk] = json.dumps(v)
            else:
                meta_updates[lk] = v

    affected = 0

    if entity_updates:
        set_parts = [f"{k} = :{k}" for k in entity_updates]
        set_parts.append("UPDATED_AT = SYSTIMESTAMP")
        entity_updates["eid"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        quoted_keys = {k: f'"{k.upper()}"' if k in ("acceptance_criteria", "constraints") else k for k in meta_updates}
        set_clause = ", ".join(f"{quoted_keys[k]} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE SPEC_META SET {set_clause} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'"
        affected += execute(sql, meta_updates)

    return affected > 0


def list_specs(
    spec_scope: Optional[str] = None,
    spec_status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List specifications with optional filters."""
    conditions = ["e.ENTITY_TYPE = 'SPEC'"]
    params: Dict[str, Any] = {"lim": limit, "off": 0}

    if spec_scope:
        conditions.append("sm.SPEC_SCOPE = :scope")
        params["scope"] = spec_scope
    if spec_status:
        conditions.append("sm.SPEC_STATUS = :sstatus")
        params["sstatus"] = spec_status

    where = " AND ".join(conditions)
    sql = f"""
        SELECT e.ENTITY_ID, e.TITLE, e.CATEGORY, e.STATUS, e.IMPORTANCE,
               sm.SPEC_VERSION, sm.SPEC_STATUS, sm.SPEC_SCOPE, sm.COMPLEXITY,
               sm.BRANCH_ID
        FROM ENTITIES e
        JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID
                          AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE {where}
        ORDER BY e.CREATED_AT DESC
        OFFSET :off ROWS FETCH NEXT :lim ROWS ONLY
    """
    rows = execute_query(sql, params)
    return [sanitize_row(r) for r in rows]


def create_plan_from_spec(spec_id: str, agent_id: str) -> str:
    """Generate a Task Plan from spec acceptance criteria. Returns PLAN_ID."""
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")

    from . import task_plan_api

    goal = spec.get("title", "Unnamed spec")
    plan_id = task_plan_api.create_plan(agent_id=agent_id, goal=goal)

    ac = spec.get("acceptance_criteria")
    if ac:
        if isinstance(ac, str):
            try:
                ac = json.loads(ac)
            except (json.JSONDecodeError, TypeError):
                ac = None
        if isinstance(ac, list):
            status = _get_plan_status(plan_id)
            for i, criterion in enumerate(ac, 1):
                desc = criterion if isinstance(criterion, str) else json.dumps(criterion)
                task_plan_api.add_step(plan_id, status, desc, i)

    link_spec_to_plan(spec_id, plan_id, "DRIVES")
    return plan_id


def _get_plan_status(plan_id: str) -> str:
    row = execute_query_one(
        "SELECT STATUS FROM TASK_PLANS WHERE PLAN_ID = :pid",
        {"pid": plan_id},
    )
    return row["status"] if row else "PENDING"


def link_spec_to_plan(
    spec_id: str,
    plan_id: str,
    link_type: str,
    strength: float = 1.0,
) -> str:
    """Create spec-plan link. Returns LINK_ID."""
    sql = """
        INSERT INTO SPEC_PLAN_LINKS (LINK_ID, SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH)
        VALUES (RAWTOHEX(SYS_GUID()), :spec_id, :plan_id, :link_type, :strength)
        RETURNING LINK_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "spec_id": spec_id,
        "plan_id": plan_id,
        "link_type": link_type,
        "strength": strength,
    })


def get_spec_plan_links(spec_id: str) -> List[Dict[str, Any]]:
    """Get all plan links for a spec."""
    sql = """
        SELECT spl.LINK_ID, spl.SPEC_ID, spl.PLAN_ID, spl.LINK_TYPE,
               spl.LINK_STRENGTH,
               TO_CHAR(spl.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               tp.GOAL, tp.STATUS AS PLAN_STATUS
        FROM SPEC_PLAN_LINKS spl
        JOIN TASK_PLANS tp ON tp.PLAN_ID = spl.PLAN_ID
        WHERE spl.SPEC_ID = :sid
        ORDER BY spl.CREATED_AT
    """
    rows = execute_query(sql, {"sid": spec_id})
    return [sanitize_row(r) for r in rows]


def validate_plan_against_spec(
    spec_id: str,
    plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate plan(s) against spec acceptance criteria. Returns validation report."""
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")

    ac = spec.get("acceptance_criteria")
    if isinstance(ac, str):
        try:
            ac = json.loads(ac)
        except (json.JSONDecodeError, TypeError):
            ac = None

    results: Dict[str, Any] = {
        "spec_id": spec_id,
        "criteria_count": len(ac) if isinstance(ac, list) else 0,
        "validations": [],
    }

    if plan_id:
        plan_ids = [plan_id]
    else:
        links = get_spec_plan_links(spec_id)
        plan_ids = [l["plan_id"] for l in links if l.get("link_type") == "DRIVES"]

    from . import task_plan_api

    for pid in plan_ids:
        plan = task_plan_api.get_plan(pid)
        steps = task_plan_api.get_plan_steps(pid)
        step_descs = [s.get("description", "") for s in steps]

        validated = 0
        passed = 0
        if isinstance(ac, list):
            for criterion in ac:
                validated += 1
                crit_str = criterion if isinstance(criterion, str) else json.dumps(criterion)
                for desc in step_descs:
                    if crit_str.lower() in desc.lower():
                        passed += 1
                        break

        results["validations"].append({
            "plan_id": pid,
            "goal": plan.get("goal", "") if plan else "",
            "plan_status": plan.get("status", "") if plan else "",
            "criteria_validated": validated,
            "criteria_passed": passed,
            "pass_rate": round(passed / validated, 2) if validated > 0 else 0,
        })

    return results


def derive_spec(
    parent_spec_id: str,
    title: str,
    content: Optional[str] = None,
    summary: Optional[str] = None,
) -> str:
    """Derive a new spec version from parent. Returns new ENTITY_ID."""
    parent = get_spec(parent_spec_id)
    if parent is None:
        raise ValueError(f"Parent spec {parent_spec_id} not found")

    return create_spec(
        title=title,
        content=content or parent.get("content"),
        summary=summary or parent.get("summary"),
        category=parent.get("category"),
        importance=parent.get("importance"),
        owned_by_agent=parent.get("owned_by_agent"),
        visibility=parent.get("visibility"),
        workspace_id=parent.get("workspace_id"),
        spec_scope=parent.get("spec_scope"),
        complexity=parent.get("complexity"),
        acceptance_criteria=parent.get("acceptance_criteria"),
        constraints=parent.get("constraints"),
        parent_spec_id=parent_spec_id,
    )


def delete_spec(entity_id: str) -> bool:
    """Delete a spec and all related data. Returns True/False."""
    try:
        execute("DELETE FROM SPEC_PLAN_LINKS WHERE SPEC_ID = :eid", {"eid": entity_id})
        execute("DELETE FROM SPEC_META WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'", {"eid": entity_id})
        execute("DELETE FROM ENTITY_TAGS WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'", {"eid": entity_id})
        execute("DELETE FROM ENTITY_EDGES WHERE SOURCE_ID = :eid AND SOURCE_TYPE = 'SPEC'", {"eid": entity_id})
        affected = execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'", {"eid": entity_id})
        return affected > 0
    except Exception:
        return False

def create_plan_from_spec_in_branch(spec_id: str, branch_id: str, agent_id: str) -> str:
    """Generate a Task Plan from spec acceptance criteria within a branch. Returns PLAN_ID."""
    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")

    from . import task_plan_api

    goal = spec.get("title", "Unnamed spec")
    plan_id = task_plan_api.create_plan(agent_id=agent_id, goal=goal, branch_id=branch_id)

    ac = spec.get("acceptance_criteria")
    if ac:
        if isinstance(ac, str):
            try:
                ac = json.loads(ac)
            except (json.JSONDecodeError, TypeError):
                ac = None
        if isinstance(ac, list):
            status = _get_plan_status(plan_id)
            for i, criterion in enumerate(ac, 1):
                desc = criterion if isinstance(criterion, str) else json.dumps(criterion)
                task_plan_api.add_step(plan_id, status, desc, i)

    link_spec_to_plan(spec_id, plan_id, "DRIVES")
    return plan_id


def validate_branch_against_spec(branch_id: str, spec_id: str) -> Dict[str, Any]:
    """Validate a branch context chain against a spec acceptance criteria."""
    from . import branch_api

    spec = get_spec(spec_id)
    if spec is None:
        raise ValueError(f"Spec {spec_id} not found")

    ac = spec.get("acceptance_criteria")
    if not ac:
        return {"pass_rate": 1.0, "total": 0, "passed": 0, "failed": 0, "details": []}
    if isinstance(ac, str):
        try:
            ac = json.loads(ac)
        except (json.JSONDecodeError, TypeError):
            ac = None
    if not isinstance(ac, list):
        return {"pass_rate": 0.0, "total": 0, "passed": 0, "failed": 0, "details": []}

    chain = branch_api.get_branch_context_chain(branch_id)
    context_text = " ".join(
        str(ctx.get("context_data", "")) for ctx in chain if ctx.get("context_data")
    ).lower()

    results = []
    passed = 0
    for criterion in ac:
        desc = criterion if isinstance(criterion, str) else json.dumps(criterion)
        keywords = [w.lower() for w in desc.split() if len(w) > 3]
        match = any(kw in context_text for kw in keywords) if keywords else desc.lower() in context_text
        if match:
            passed += 1
        results.append({"criterion": desc, "matched": match})

    total = len(ac)
    return {
        "pass_rate": round(passed / total, 2) if total > 0 else 1.0,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "details": results,
    }

def create_spec_for_group(title: str, group_id: str, **kwargs: Any) -> str:
    """Create a spec associated with a collaboration group. Returns ENTITY_ID."""
    from . import collab_api
    group = collab_api.get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group {group_id} not found")
    ws_id = group.get("workspace_id")
    branch_id = group.get("branch_id")
    spec_id = create_spec(
        title=title,
        workspace_id=ws_id,
        branch_id=branch_id,
        **kwargs,
    )
    return spec_id


def validate_group_progress(spec_id: str, group_id: str) -> Dict[str, Any]:
    """Validate a collaboration group's overall progress against a spec."""
    from . import collab_api
    return collab_api.validate_group_against_spec(group_id, spec_id)


def derive_loop_from_spec(spec_id: str, agent_id: str) -> Dict[str, Any]:
    """Derive a loop definition from a spec. Returns the derived loop parameters."""
    spec = get_spec(spec_id)
    if not spec:
        raise ValueError(f"Spec {spec_id} not found")

    properties = spec.get("properties", {})
    acceptance_criteria = properties.get("acceptance_criteria", [])

    goal_definition = {
        "type": "SPEC_VALIDATION",
        "spec_id": spec_id,
        "success_criteria": [str(c) for c in acceptance_criteria] if acceptance_criteria else [f"Spec {spec_id} validated"],
        "constraints": ["Must validate against all acceptance criteria"]
    }

    stop_conditions = {
        "max_iterations": 10,
        "timeout_minutes": 60,
        "consecutive_passes": 2
    }

    evaluation_config = {
        "type": "SPEC_VALIDATION",
        "spec_id": spec_id,
        "criteria": [str(c) for c in acceptance_criteria] if acceptance_criteria else []
    }

    return {
        "title": f"Loop for spec: {spec.get('title', spec_id)}",
        "summary": f"Auto-derived loop for spec validation",
        "goal_definition": goal_definition,
        "stop_conditions": stop_conditions,
        "evaluation_config": evaluation_config,
        "spec_id": spec_id,
        "owned_by_agent": agent_id
    }
