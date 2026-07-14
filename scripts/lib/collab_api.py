"""AI Agent Infra v3.5.0 - Community Edition - Collaboration Group API

Collaboration group lifecycle, membership management,
shared/personal workspaces, and group memory sharing.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import (
    execute,
    execute_query,
    execute_query_one,
    execute_insert_returning_id,
    sanitize_row,
)
from .workspace_api import create_workspace
from .memory_api import create_memory, search_memories

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"metadata"}

_ALLOWED_UPDATE_FIELDS = frozenset({
    "group_name", "group_type", "description",
    "coordinator_agent_id", "sharing_policy", "status", "metadata",
})


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
    return sanitize_row(result)


def create_collab_group(
    name: str,
    group_type: str,
    coordinator_agent_id: Optional[str] = None,
    description: Optional[str] = None,
    sharing_policy: str = "OPEN",
    metadata: Optional[Any] = None,
    branch_id: Optional[str] = None,
    spec_id: Optional[str] = None,
) -> str:
    ws_id = create_workspace(
        name=f"CollabGroup: {name}",
        workspace_type="COLLAB_GROUP",
        isolation_mode="SHARED",
        metadata={"collab_group_name": name, "group_type": group_type},
    )

    meta_val = json.dumps(metadata) if isinstance(metadata, (dict, list)) else metadata
    group_id_sql = "'CG_' || RAWTOHEX(SYS_GUID())"
    sql = f"""
        INSERT INTO COLLAB_GROUPS (GROUP_ID, GROUP_NAME, GROUP_TYPE, DESCRIPTION,
                                   WORKSPACE_ID, COORDINATOR_AGENT_ID, SHARING_POLICY,
                                   STATUS, METADATA, BRANCH_ID, SPEC_ID, CREATED_AT, UPDATED_AT)
        VALUES ({group_id_sql}, :name, :gtype, :descr, :wsid, :coord, :policy,
                'ACTIVE', :meta, :vbrid, :vsid, SYSTIMESTAMP, SYSTIMESTAMP)
        RETURNING GROUP_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "name": name,
        "gtype": group_type,
        "descr": description,
        "wsid": ws_id,
        "coord": coordinator_agent_id,
        "policy": sharing_policy,
        "meta": meta_val,
        "vbrid": branch_id,
        "vsid": spec_id,
    })


def get_collab_group(group_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT GROUP_ID, GROUP_NAME, GROUP_TYPE, DESCRIPTION,
               WORKSPACE_ID, COORDINATOR_AGENT_ID, SHARING_POLICY,
               STATUS, METADATA, BRANCH_ID, SPEC_ID,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM COLLAB_GROUPS
        WHERE GROUP_ID = :gid
    """
    row = execute_query_one(sql, {"gid": group_id})
    if row is None:
        return None
    group = _row_to_dict(row)
    group["members"] = list_group_members(group_id)
    return group


def update_collab_group(group_id: str, **kwargs: Any) -> bool:
    updates: Dict[str, str] = {}
    params: Dict[str, Any] = {"gid": group_id}
    for key, value in kwargs.items():
        col = key.lower()
        if col not in _ALLOWED_UPDATE_FIELDS:
            continue
        db_col = col.upper()
        if col in ("metadata",) and isinstance(value, (dict, list)):
            updates[db_col] = f":{col}"
            params[col] = json.dumps(value)
        else:
            updates[db_col] = f":{col}"
            params[col] = value
    if not updates:
        return False
    updates["UPDATED_AT"] = "SYSTIMESTAMP"
    set_clause = ", ".join(f"{k} = {v}" for k, v in updates.items())
    sql = f"UPDATE COLLAB_GROUPS SET {set_clause} WHERE GROUP_ID = :gid"
    return execute(sql, params) > 0


def add_group_member(
    group_id: str,
    agent_id: str,
    role: str = "MEMBER",
    branch_id: Optional[str] = None,
) -> str:
    """Add a member to a collaboration group and initialize trust edges."""
    personal_workspace_id = None
    if role in ("LEAD", "CONTRIBUTOR"):
        personal_workspace_id = create_workspace(
            name=f"Personal: {agent_id} in {group_id}",
            workspace_type="PERSONAL_IN_GROUP",
            isolation_mode="ISOLATED",
            metadata={"group_id": group_id, "agent_id": agent_id, "role": role},
        )

    member_id_sql = "'CGM_' || RAWTOHEX(SYS_GUID())"
    sql = f"""
        INSERT INTO COLLAB_GROUP_MEMBERS (MEMBER_ID, GROUP_ID, AGENT_ID, ROLE,
                                          PERSONAL_WORKSPACE_ID, BRANCH_ID, JOINED_AT, STATUS)
        VALUES ({member_id_sql}, :gid, :aid, :role, :pwid, :vmbrid, SYSTIMESTAMP, 'ACTIVE')
        RETURNING MEMBER_ID INTO :ret_id
    """
    member_id = execute_insert_returning_id(sql, {
        "gid": group_id,
        "aid": agent_id,
        "role": role,
        "pwid": personal_workspace_id,
        "vmbrid": branch_id,
    })
    if member_id:
        _init_member_trust(group_id, agent_id)
    return member_id


def _init_member_trust(group_id: str, agent_id: str):
    """v3.10.0: Initialize trust edges when a member joins a group."""
    try:
        from .graph_api import init_group_trust
        group = get_collab_group(group_id)
        coordinator = group.get('coordinator_agent_id') if group else agent_id
        members = list_group_members(group_id)
        existing_ids = [m.get('agent_id') for m in members if m.get('agent_id') != agent_id]
        init_group_trust(agent_id, group_id, coordinator, existing_ids)
    except Exception:
        pass


def remove_group_member(group_id: str, agent_id: str) -> bool:
    sql = """
        UPDATE COLLAB_GROUP_MEMBERS
        SET STATUS = 'LEFT'
        WHERE GROUP_ID = :gid AND AGENT_ID = :aid AND STATUS = 'ACTIVE'
    """
    return execute(sql, {"gid": group_id, "aid": agent_id}) > 0


def list_group_members(group_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT MEMBER_ID, GROUP_ID, AGENT_ID, ROLE,
               PERSONAL_WORKSPACE_ID, BRANCH_ID, STATUS,
               TO_CHAR(JOINED_AT, 'YYYY-MM-DD HH24:MI:SS') AS JOINED_AT
        FROM COLLAB_GROUP_MEMBERS
        WHERE GROUP_ID = :gid
        ORDER BY JOINED_AT ASC
    """
    rows = execute_query(sql, {"gid": group_id})
    return [sanitize_row(dict(r)) for r in rows]


def get_agent_groups(agent_id: str) -> List[Dict[str, Any]]:
    sql = """
        SELECT g.GROUP_ID, g.GROUP_NAME, g.GROUP_TYPE, g.DESCRIPTION,
               g.WORKSPACE_ID, g.COORDINATOR_AGENT_ID, g.SHARING_POLICY,
               g.STATUS, g.METADATA,
               TO_CHAR(g.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(g.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               m.ROLE AS MEMBER_ROLE,
               m.STATUS AS MEMBER_STATUS
        FROM COLLAB_GROUPS g
        JOIN COLLAB_GROUP_MEMBERS m ON g.GROUP_ID = m.GROUP_ID
        WHERE m.AGENT_ID = :aid
        ORDER BY g.CREATED_AT DESC
    """
    rows = execute_query(sql, {"aid": agent_id})
    return [_row_to_dict(r) for r in rows]


def share_memory_to_group(
    agent_id: str,
    group_id: str,
    title: str,
    content: str,
    category: str = "general",
    importance: int = 5,
    **kwargs: Any,
) -> str:
    group = get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group not found: {group_id}")
    workspace_id = group.get("workspace_id")
    return create_memory(
        title=title,
        content=content,
        category=category,
        importance=importance,
        source_agent=agent_id,
        owned_by_agent=agent_id,
        visibility="SHARED",
        workspace_id=workspace_id,
        **kwargs,
    )


def get_group_shared_memories(
    group_id: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    group = get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group not found: {group_id}")
    workspace_id = group.get("workspace_id")
    return search_memories(workspace_id=workspace_id, limit=limit)


def delete_collab_group(group_id: str) -> bool:
    execute("DELETE FROM COLLAB_GROUP_MEMBERS WHERE GROUP_ID = :gid", {"gid": group_id})
    sql = "DELETE FROM COLLAB_GROUPS WHERE GROUP_ID = :gid"
    return execute(sql, {"gid": group_id}) > 0

def get_member_branches(group_id: str) -> List[Dict[str, Any]]:
    """Return all members with their branch info for a collaboration group."""
    members = list_group_members(group_id)
    result = []
    from . import branch_api
    for m in members:
        agent_id = m.get("agent_id")
        member_branch_id = m.get("branch_id")
        branch_info = None
        if member_branch_id:
            branch_info = branch_api.get_branch(member_branch_id)
        elif m.get("personal_workspace_id"):
            try:
                branches = branch_api.list_branches(
                    workspace_id=m["personal_workspace_id"],
                    status="ACTIVE"
                )
                if branches:
                    branch_info = branches[0]
                    member_branch_id = branch_info.get("branch_id")
            except Exception:
                pass
        result.append({
            "member_id": m.get("member_id"),
            "agent_id": agent_id,
            "role": m.get("role"),
            "branch_id": member_branch_id,
            "branch_info": branch_info,
        })
    return result


def validate_group_against_spec(group_id: str, spec_id: Optional[str] = None) -> Dict[str, Any]:
    """Validate a collaboration group progress against its associated spec.

    If spec_id is not provided, uses the group's SPEC_ID.
    Returns aggregate validation across all member branches.
    """
    group = get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group {group_id} not found")
    
    effective_spec_id = spec_id or group.get("spec_id")
    if not effective_spec_id:
        return {"pass_rate": 0.0, "total": 0, "passed": 0, "failed": 0, "details": [], "message": "No spec associated"}
    
    members = get_member_branches(group_id)
    from . import spec_api
    
    all_results = []
    total_passed = 0
    total_criteria = 0
    
    for m in members:
        bid = m.get("branch_id")
        if bid:
            try:
                val = spec_api.validate_branch_against_spec(bid, effective_spec_id)
                total_passed += val.get("passed", 0)
                total_criteria = max(total_criteria, val.get("total", 0))
                all_results.append({"agent_id": m["agent_id"], "branch_id": bid, **val})
            except Exception as e:
                all_results.append({"agent_id": m["agent_id"], "branch_id": bid, "error": str(e)})
    
    return {
        "pass_rate": round(total_passed / total_criteria, 2) if total_criteria > 0 else 0.0,
        "total": total_criteria,
        "passed": total_passed,
        "failed": total_criteria - total_passed,
        "member_results": all_results,
    }


def sync_group_context(group_id: str) -> Dict[str, Any]:
    """Sync key context from member branches to the shared workspace.

    Copies the latest SUMMARY context from each member's branch into the
    group's shared workspace for cross-agent visibility.
    """
    group = get_collab_group(group_id)
    if group is None:
        raise ValueError(f"Collaboration group {group_id} not found")
    
    ws_id = group.get("workspace_id")
    members = list_group_members(group_id)
    from . import workspace_api, branch_api
    
    synced = 0
    for m in members:
        bid = m.get("branch_id")
        if not bid:
            continue
        try:
            chain = branch_api.get_branch_context_chain(bid)
            for ctx in chain:
                if ctx.get("context_type") == "SUMMARY":
                    workspace_api.save_context(
                        workspace_id=ws_id,
                        agent_id=m["agent_id"],
                        context_type="AUTO_SAVE",
                        context_data={
                            "synced_from_branch": bid,
                            "agent_id": m["agent_id"],
                            "summary": ctx.get("context_data"),
                        },
                    )
                    synced += 1
                    break
        except Exception:
            continue
    
    return {"group_id": group_id, "synced_count": synced}


def create_group_loop(group_id: str, title: str, goal_definition: dict, agent_id: str, **kwargs) -> str:
    from .loop_api import create_loop
    loop_id = create_loop(
        title=title,
        goal_definition=goal_definition,
        stop_conditions=kwargs.get("stop_conditions", {"max_iterations": 10, "timeout_minutes": 60, "consecutive_passes": 2}),
        evaluation_config=kwargs.get("evaluation_config", {"type": "AGGREGATE"}),
        owned_by_agent=agent_id,
        collab_group_id=group_id,
        **{k: v for k, v in kwargs.items() if k not in ("stop_conditions", "evaluation_config")}
    )
    return loop_id

def get_group_loop_status(group_id: str) -> Dict[str, Any]:
    rows = execute_query("""
        SELECT e.ENTITY_ID, e.TITLE, e.STATUS, m.COLLAB_GROUP_ID
        FROM ENTITIES e JOIN LOOP_META m ON e.ENTITY_ID = m.ENTITY_ID
        WHERE m.COLLAB_GROUP_ID = :group_id AND e.ENTITY_TYPE = 'LOOP_DEFINITION'
    """, {"group_id": group_id})
    return {"group_id": group_id, "loops": [_row_to_dict(r) for r in rows]}
