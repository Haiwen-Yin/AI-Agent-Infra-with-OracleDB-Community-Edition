"""AI Agent Infra v4.4.9 - Community Edition - Spec API

Spec Driven Development: create/manage specification documents with plan linkage and validation.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from .connection import (
    DATABASE_DIALECT,
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)
from . import cursor_pagination, identity_api


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
        VALUES (AI_NEW_ID(), 'SPEC', :title, :content, :summary,
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

    constraints_column = "SPEC_CONSTRAINTS" if DATABASE_DIALECT == "postgresql" else '"CONSTRAINTS"'
    meta_sql = f"""
        INSERT INTO SPEC_META (ENTITY_ID, ENTITY_TYPE, SPEC_VERSION, SPEC_STATUS,
                               ACCEPTANCE_CRITERIA, {constraints_column}, SPEC_SCOPE,
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

    # Version history is an integrity boundary in v4.4.  Do not silently
    # accept a mutable specification when the required persistence failed.
    version_id = create_spec_version(entity_id, "CREATED", "Initial version")
    if not version_id:
        raise RuntimeError("SPEC_VERSION_PERSISTENCE_FAILED")

    return entity_id


def get_spec(entity_id: str) -> Optional[Dict[str, Any]]:
    """Get spec with metadata and plan links. Returns dict or None."""
    try:
        sql = """
            SELECT e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CONTENT, e.SUMMARY,
                   e.CATEGORY, e.STATUS, e.OWNED_BY_AGENT, e.VISIBILITY, e.IMPORTANCE,
                   e.WORKSPACE_ID,
                   TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
                   sm.SPEC_VERSION, sm.SPEC_STATUS, sm.ACCEPTANCE_CRITERIA,
                   sm.spec_constraints AS CONSTRAINTS, sm.SPEC_SCOPE, sm.COMPLEXITY, sm.PARENT_SPEC_ID
            FROM ENTITIES e
            LEFT JOIN SPEC_META sm ON sm.ENTITY_ID = e.ENTITY_ID
                                   AND sm.ENTITY_TYPE = e.ENTITY_TYPE
            WHERE e.ENTITY_ID = :eid AND e.ENTITY_TYPE = 'SPEC'
        """
        row = execute_query_one(sql, {"eid": entity_id})
    except Exception:
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
    if str(result.get("status", "")).upper() == "DELETED":
        return None

    try:
        links_sql = """
            SELECT LINK_ID, SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM SPEC_PLAN_LINKS
            WHERE SPEC_ID = :sid
        """
        links = execute_query(links_sql, {"sid": entity_id})
    except Exception:
        try:
            links_sql = """
                SELECT LINK_ID, SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH
                FROM SPEC_PLAN_LINKS
                WHERE SPEC_ID = :sid
            """
            links = execute_query(links_sql, {"sid": entity_id})
        except Exception:
            links = []
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
        set_parts.append("UPDATED_AT = CURRENT_TIMESTAMP")
        entity_updates["eid"] = entity_id
        sql = f"UPDATE ENTITIES SET {', '.join(set_parts)} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'"
        affected += execute(sql, entity_updates)

    if meta_updates:
        quoted_keys = {k: f'"{k.upper()}"' if k in ("acceptance_criteria", "constraints") else k for k in meta_updates}
        set_clause = ", ".join(f"{quoted_keys[k]} = :{k}" for k in meta_updates)
        meta_updates["eid"] = entity_id
        sql = f"UPDATE SPEC_META SET {set_clause} WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'"
        affected += execute(sql, meta_updates)

    if affected > 0:
        updated_fields = sorted(list(entity_updates.keys()) + list(meta_updates.keys()))
        version_id = create_spec_version(
            entity_id,
            "MODIFIED",
            f"Updated fields: {', '.join(updated_fields)}",
            diff_json={"updated_fields": updated_fields,
                       "entity": entity_updates,
                       "meta": meta_updates},
        )
        if not version_id:
            raise RuntimeError("SPEC_VERSION_PERSISTENCE_FAILED")

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


def list_specs_cursor(principal_id: str, *, page_size: int = 20, cursor: str = "",
                      spec_scope: Optional[str] = None, spec_status: Optional[str] = None) -> Dict[str, Any]:
    """Return a principal-bound Spec inventory page."""
    filters = {"spec_scope": spec_scope or "", "spec_status": spec_status or ""}
    context = cursor_pagination.resolve(principal_id, "specs", filters, "entity_id:asc", page_size, cursor)
    context.update({"principal_id": principal_id, "resource_key": "specs", "sort_key": "entity_id:asc"})
    conditions = ["e.ENTITY_TYPE='SPEC'"]
    params: Dict[str, Any] = {"lim": int(context["page_size"]) + 1}
    if spec_scope:
        conditions.append("sm.SPEC_SCOPE=:scope")
        params["scope"] = spec_scope
    if spec_status:
        conditions.append("sm.SPEC_STATUS=:sstatus")
        params["sstatus"] = spec_status
    if identity_api.effective_access(principal_id, "agents.read.all").get("decision") != "ALLOW":
        conditions.append(
            "(e.VISIBILITY IN ('PUBLIC','SHARED') OR EXISTS (SELECT 1 FROM CX_PRINCIPALS p "
            "WHERE p.PRINCIPAL_ID=e.OWNED_BY_AGENT AND p.PRINCIPAL_TYPE='AGENT' AND " +
            identity_api._agent_visibility_clause(principal_id) + "))"
        )
        params["principal_id"] = principal_id
    after = str(context["position"].get("entity_id") or "")
    if after:
        conditions.append("e.ENTITY_ID>:after")
        params["after"] = after
    rows = execute_query(
        "SELECT e.ENTITY_ID,e.TITLE,e.CATEGORY,e.STATUS,e.IMPORTANCE,sm.SPEC_VERSION,sm.SPEC_STATUS,"
        "sm.SPEC_SCOPE,sm.COMPLEXITY,sm.BRANCH_ID FROM ENTITIES e JOIN SPEC_META sm "
        "ON sm.ENTITY_ID=e.ENTITY_ID AND sm.ENTITY_TYPE=e.ENTITY_TYPE WHERE " + " AND ".join(conditions) +
        " ORDER BY e.ENTITY_ID FETCH FIRST :lim ROWS ONLY", params,
    )
    values = [sanitize_row(row) for row in rows]
    result = cursor_pagination.page(values, context, lambda item: {"entity_id": str(item["entity_id"])})
    count_conditions = [condition for condition in conditions if condition != "e.ENTITY_ID>:after"]
    count_params = {key: value for key, value in params.items() if key not in {"lim", "after"}}
    try:
        total = execute_query_one(
            "SELECT COUNT(*) AS CNT FROM ENTITIES e JOIN SPEC_META sm "
            "ON sm.ENTITY_ID=e.ENTITY_ID AND sm.ENTITY_TYPE=e.ENTITY_TYPE WHERE " +
            " AND ".join(count_conditions),
            count_params,
        )
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


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
        VALUES (AI_NEW_ID(), :spec_id, :plan_id, :link_type, :strength)
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
    try:
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
    except Exception:
        try:
            sql = """
                SELECT spl.LINK_ID, spl.SPEC_ID, spl.PLAN_ID, spl.LINK_TYPE,
                       spl.LINK_STRENGTH,
                       tp.GOAL, tp.STATUS AS PLAN_STATUS
                FROM SPEC_PLAN_LINKS spl
                JOIN TASK_PLANS tp ON tp.PLAN_ID = spl.PLAN_ID
                WHERE spl.SPEC_ID = :sid
            """
            rows = execute_query(sql, {"sid": spec_id})
        except Exception:
            rows = []
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
        details = []
        if isinstance(ac, list):
            for criterion in ac:
                validated += 1
                if isinstance(criterion, dict):
                    criterion_id = criterion.get("id") or criterion.get("key") or str(validated)
                    required_task_ids = {str(value) for value in criterion.get("task_ids", [])}
                    required_tags = {str(value).lower() for value in criterion.get("tags", [])}
                    task_ids = {str(step.get("step_id") or step.get("id") or "") for step in steps}
                    task_tags = {str(tag).lower() for step in steps for tag in (step.get("tags") or [])}
                    matched = (not required_task_ids or required_task_ids <= task_ids) and (not required_tags or required_tags <= task_tags)
                    details.append({"criterion": criterion_id, "matched": matched, "mode": "structured"})
                else:
                    # Legacy string criteria cannot establish delivery
                    # evidence. Keep their presence visible, but never infer
                    # completion from substring matching.
                    matched = False
                    details.append({"criterion": str(criterion), "matched": False, "mode": "legacy_requires_migration"})
                if matched:
                    passed += 1

        results["validations"].append({
            "plan_id": pid,
            "goal": plan.get("goal", "") if plan else "",
            "plan_status": plan.get("status", "") if plan else "",
            "criteria_validated": validated,
            "criteria_passed": passed,
            "pass_rate": round(passed / validated, 2) if validated > 0 else 0,
            "details": details,
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
    """Retire a spec instead of physically deleting governed history."""
    try:
        affected = execute(
            "UPDATE ENTITIES SET STATUS = 'DELETED', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC' AND STATUS <> 'DELETED'",
            {"eid": entity_id},
        )
        if affected:
            execute(
                "UPDATE SPEC_META SET SPEC_STATUS = 'DEPRECATED' "
                "WHERE ENTITY_ID = :eid AND ENTITY_TYPE = 'SPEC'",
                {"eid": entity_id},
            )
            version_id = create_spec_version(entity_id, "DELETED", "Deleted without physical deletion")
            if not version_id:
                raise RuntimeError("SPEC_VERSION_PERSISTENCE_FAILED")
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

    acceptance_criteria = spec.get("acceptance_criteria") or []
    if isinstance(acceptance_criteria, str):
        try:
            acceptance_criteria = json.loads(acceptance_criteria)
        except (TypeError, json.JSONDecodeError):
            acceptance_criteria = []

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


def create_spec_version(
    spec_id: str,
    change_type: str = "MODIFIED",
    change_summary: str = "",
    diff_json: Optional[Any] = None,
) -> Optional[str]:
    """Record a new version entry for a spec. Returns VERSION_ID or None if unavailable."""
    try:
        # PostgreSQL may expose legacy numeric ENTITY_ID values while the
        # version ledger deliberately uses a portable string reference.
        spec_id = str(spec_id)
        next_num_sql = (
            "SELECT COALESCE(MAX(VERSION_NUMBER), 0) + 1 AS NEXT_VER "
            "FROM SPEC_VERSIONS WHERE SPEC_ID = :sid"
        )
        row = execute_query_one(next_num_sql, {"sid": spec_id})
        next_ver = int(row["next_ver"]) if row and row.get("next_ver") is not None else 1

        if diff_json is None:
            current = get_spec(spec_id)
            snapshot_keys = [
                "title", "content", "summary", "category", "status",
                "importance", "visibility", "spec_version", "spec_status",
                "acceptance_criteria", "constraints", "spec_scope", "complexity",
            ]
            diff_json = {k: current.get(k) for k in snapshot_keys if current}

        diff_str = diff_json if isinstance(diff_json, str) else json.dumps(diff_json or {}, default=str)

        from .connection import get_current_agent_id
        created_by = get_current_agent_id()

        version_id = "SPECVER_" + uuid.uuid4().hex
        sql = """
            INSERT INTO SPEC_VERSIONS (VERSION_ID, SPEC_ID, VERSION_NUMBER,
                                       CHANGE_TYPE, CHANGE_SUMMARY, DIFF_JSON,
                                       CREATED_BY)
            VALUES (:vid, :sid, :vnum, :ctype, :csum, :djson, :cby)
        """
        execute(sql, {
            "vid": version_id,
            "sid": spec_id,
            "vnum": next_ver,
            "ctype": change_type,
            "csum": change_summary,
            "djson": diff_str,
            "cby": created_by,
        })
        return version_id
    except Exception:
        return None


def get_spec_versions(spec_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return version history for a spec, most recent first."""
    try:
        sql = """
            SELECT VERSION_ID, SPEC_ID, VERSION_NUMBER, CHANGE_TYPE,
                   CHANGE_SUMMARY, DIFF_JSON, CREATED_BY,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM SPEC_VERSIONS
            WHERE SPEC_ID = :sid
            ORDER BY VERSION_NUMBER DESC
            OFFSET 0 ROWS FETCH NEXT :lim ROWS ONLY
        """
        rows = execute_query(sql, {"sid": spec_id, "lim": limit})
        return [sanitize_row(r) for r in rows]
    except Exception:
        return []


def get_spec_version_diff(
    spec_id: str,
    version_a: int,
    version_b: int,
) -> Optional[Dict[str, Any]]:
    """Return the DIFF_JSON snapshots for two versions for comparison."""
    try:
        sql = """
            SELECT VERSION_NUMBER, CHANGE_TYPE, CHANGE_SUMMARY, DIFF_JSON,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   CREATED_BY
            FROM SPEC_VERSIONS
            WHERE SPEC_ID = :sid AND VERSION_NUMBER IN (:va, :vb)
            ORDER BY VERSION_NUMBER
        """
        rows = execute_query(sql, {"sid": spec_id, "va": version_a, "vb": version_b})
        snapshots = {int(r["version_number"]): sanitize_row(r) for r in rows}
        if version_a not in snapshots or version_b not in snapshots:
            return None

        def _parse(rec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not rec:
                return None
            dj = rec.get("diff_json")
            if isinstance(dj, str):
                try:
                    return json.loads(dj)
                except (json.JSONDecodeError, TypeError):
                    return None
            return dj if isinstance(dj, dict) else None

        a_state = _parse(snapshots[version_a])
        b_state = _parse(snapshots[version_b])

        changed_fields = []
        if isinstance(a_state, dict) and isinstance(b_state, dict):
            all_keys = set(a_state.keys()) | set(b_state.keys())
            for key in all_keys:
                if a_state.get(key) != b_state.get(key):
                    changed_fields.append(key)

        return {
            "spec_id": spec_id,
            "version_a": snapshots[version_a],
            "version_b": snapshots[version_b],
            "changed_fields": changed_fields,
        }
    except Exception:
        return None


def get_spec_at_version(spec_id: str, version_number: int) -> Optional[Dict[str, Any]]:
    """Return the spec state snapshot (DIFF_JSON) at a specific version."""
    try:
        sql = """
            SELECT VERSION_ID, SPEC_ID, VERSION_NUMBER, CHANGE_TYPE,
                   CHANGE_SUMMARY, DIFF_JSON, CREATED_BY,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM SPEC_VERSIONS
            WHERE SPEC_ID = :sid AND VERSION_NUMBER = :vnum
        """
        row = execute_query_one(sql, {"sid": spec_id, "vnum": version_number})
        if row is None:
            return None

        result = sanitize_row(row)
        dj = result.get("diff_json")
        if isinstance(dj, str):
            try:
                result["diff_json"] = json.loads(dj)
            except (json.JSONDecodeError, TypeError):
                pass
        return result
    except Exception:
        return None
