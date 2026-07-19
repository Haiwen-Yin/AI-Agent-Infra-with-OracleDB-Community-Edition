"""AI Agent Infra v4.0.0 - Enterprise Edition - Workspace API

Workspace lifecycle management, context chains, agent handoff sessions,
workspace recovery, and task linking.
"""

import json
import uuid
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"metadata", "context_data"}

_ALLOWED_UPDATE_FIELDS = frozenset({
    "workspace_name", "status", "isolation_mode",
    "current_agent_id", "current_session_id", "summary", "metadata",
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
    return result


def create_workspace(
    owner_user_id: Optional[str] = None,
    name: Optional[str] = None,
    workspace_type: str = "CONVERSATION",
    isolation_mode: str = "SHARED",
    metadata: Optional[Any] = None,
) -> str:
    """Create a new workspace and return its ID."""
    ws_id_sql = "'WS_' || RAWTOHEX(SYS_GUID())"
    meta_val = json.dumps(metadata) if isinstance(metadata, (dict, list)) else metadata
    sql = f"""
        INSERT INTO WORKSPACES (WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME,
                                WORKSPACE_TYPE, ISOLATION_MODE, METADATA,
                                STATUS, CREATED_AT, UPDATED_AT)
        VALUES ({ws_id_sql}, :owner, :name, :wtype, :iso, :meta,
                'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING WORKSPACE_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "owner": owner_user_id,
        "name": name,
        "wtype": workspace_type,
        "iso": isolation_mode,
        "meta": meta_val,
    }, id_column="WORKSPACE_ID")


def get_workspace(workspace_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a workspace by ID."""
    sql = """
        SELECT WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME, WORKSPACE_TYPE,
               ISOLATION_MODE, CURRENT_AGENT_ID, CURRENT_SESSION_ID,
               SUMMARY, METADATA, STATUS,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM WORKSPACES
        WHERE WORKSPACE_ID = :wid
    """
    row = execute_query_one(sql, {"wid": workspace_id})
    return _row_to_dict(row) if row else None


def get_user_workspaces(
    user_id: str,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return workspaces owned by a user, optionally filtered by status."""
    if status:
        sql = """
            SELECT WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME, WORKSPACE_TYPE,
                   ISOLATION_MODE, CURRENT_AGENT_ID, CURRENT_SESSION_ID,
                   SUMMARY, METADATA, STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM WORKSPACES
            WHERE OWNER_USER_ID = :owner_id AND STATUS = :stat
            ORDER BY UPDATED_AT DESC
        """
        rows = execute_query(sql, {"owner_id": user_id, "stat": status})
    else:
        sql = """
            SELECT WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME, WORKSPACE_TYPE,
                   ISOLATION_MODE, CURRENT_AGENT_ID, CURRENT_SESSION_ID,
                   SUMMARY, METADATA, STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM WORKSPACES
            WHERE OWNER_USER_ID = :owner_id
            ORDER BY UPDATED_AT DESC
        """
        rows = execute_query(sql, {"owner_id": user_id})
    return [_row_to_dict(r) for r in rows]


def update_workspace(workspace_id: str, **kwargs: Any) -> bool:
    """Update allowed fields on a workspace. JSON fields are auto-serialized."""
    updates: Dict[str, str] = {}
    params: Dict[str, Any] = {"wid": workspace_id}
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
    updates["UPDATED_AT"] = "CURRENT_TIMESTAMP"
    set_clause = ", ".join(f"{k} = {v}" for k, v in updates.items())
    sql = f"UPDATE WORKSPACES SET {set_clause} WHERE WORKSPACE_ID = :wid"
    return execute(sql, params) > 0


def _sanitize_context_data(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    sensitive_keys = {
        'password', 'passwd', 'secret', 'credential', 'token',
        'api_key', 'apikey', 'private_key', 'access_key',
        'dsn', 'connection_string', 'db_url', 'database_url',
        'master_key', 'encryption_key', 'auth_header',
    }
    sanitized = {}
    for k, v in data.items():
        kl = k.lower()
        if any(sk in kl for sk in sensitive_keys):
            sanitized[k] = '[REDACTED]'
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_context_data(v)
        else:
            sanitized[k] = v
    return sanitized


def save_context(
    workspace_id: str,
    agent_id: str,
    context_type: str,
    context_data: Any,
    session_id: Optional[str] = None,
    parent_context_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    visibility: str = "SHARED",
) -> str:
    """Save a context entry to the workspace context chain.

    Sensitive fields in context_data (password, token, credential, dsn, etc.)
    are automatically redacted to prevent credential leakage into the database.

    visibility: 'PRIVATE' (only creating agent can see) or 'SHARED' (collab group members can see)
    """
    context_data = _sanitize_context_data(context_data)
    ctx_id_sql = "'CTX_' || RAWTOHEX(SYS_GUID())"
    data_val = json.dumps(context_data) if isinstance(context_data, (dict, list)) else context_data
    sql = f"""
        INSERT INTO WORKSPACE_CONTEXT (CONTEXT_ID, WORKSPACE_ID, AGENT_ID,
                                       SESSION_ID, CONTEXT_TYPE, CONTEXT_DATA,
                                       PARENT_CONTEXT_ID, BRANCH_ID, VISIBILITY, CREATED_AT)
        VALUES ({ctx_id_sql}, :wid, :aid, :sid, :ctype, :cdata, :pcid, :vbrid, :vis, CURRENT_TIMESTAMP)
        RETURNING CONTEXT_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "wid": workspace_id,
        "aid": agent_id,
        "sid": session_id,
        "ctype": context_type,
        "cdata": data_val,
        "pcid": parent_context_id,
        "vbrid": branch_id,
        "vis": visibility,
    }, id_column="CONTEXT_ID")


def get_context_chain(
    workspace_id: str,
    limit: int = 10,
    branch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the latest context entries for a workspace."""
    if branch_id:
        sql = """
            SELECT CONTEXT_ID, WORKSPACE_ID, AGENT_ID, SESSION_ID,
                   CONTEXT_TYPE, CONTEXT_DATA, PARENT_CONTEXT_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM WORKSPACE_CONTEXT
            WHERE WORKSPACE_ID = :wid AND BRANCH_ID = :vbrid
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        rows = execute_query(sql, {"wid": workspace_id, "lim": limit, "vbrid": branch_id})
    else:
        sql = """
            SELECT CONTEXT_ID, WORKSPACE_ID, AGENT_ID, SESSION_ID,
                   CONTEXT_TYPE, CONTEXT_DATA, PARENT_CONTEXT_ID,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM WORKSPACE_CONTEXT
            WHERE WORKSPACE_ID = :wid
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        rows = execute_query(sql, {"wid": workspace_id, "lim": limit})
    return [_row_to_dict(r) for r in rows]


def get_latest_context(workspace_id: str) -> Optional[Dict[str, Any]]:
    """Return the single most recent context entry for a workspace."""
    sql = """
        SELECT CONTEXT_ID, WORKSPACE_ID, AGENT_ID, SESSION_ID,
               CONTEXT_TYPE, CONTEXT_DATA, PARENT_CONTEXT_ID,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
        FROM WORKSPACE_CONTEXT
        WHERE WORKSPACE_ID = :wid
        ORDER BY CREATED_AT DESC
        FETCH FIRST 1 ROWS ONLY
    """
    row = execute_query_one(sql, {"wid": workspace_id})
    return _row_to_dict(row) if row else None


def create_handoff_session(
    workspace_id: str,
    new_agent_id: str,
    handoff_data: Optional[Any] = None,
) -> str:
    """Create a handoff session, transferring workspace control to a new agent.

    Steps:
      1. Retrieve latest context and current active session from workspace.
      2. Create a new AGENT_SESSION linked to the predecessor.
      3. Save a HANDOFF context entry with handoff_data.
      4. Update WORKSPACES to point to the new agent and session.

    Returns the new session_id.
    """
    from .branch_api import fork_branch

    ws = get_workspace(workspace_id)
    if ws is None:
        raise ValueError(f"Workspace not found: {workspace_id}")

    latest_ctx = get_latest_context(workspace_id)
    current_session_id = ws.get("current_session_id")

    branch_id = fork_branch(
        workspace_id=workspace_id,
        fork_context_id=latest_ctx["context_id"] if latest_ctx else None,
        branch_name=f"handoff-to-{new_agent_id}",
        branch_type="HANDOFF",
        agent_id=new_agent_id,
        source_agent_id=ws.get("current_agent_id"),
        purpose=f"Handoff from {ws.get('current_agent_id', '?')} to {new_agent_id}",
        fork_session_id=current_session_id,
    )

    session_id_sql = "'SES_' || RAWTOHEX(SYS_GUID())"
    sql = f"""
        INSERT INTO AGENT_SESSION (SESSION_ID, AGENT_ID, WORKSPACE_ID,
                                   PREDECESSOR_SESSION_ID, OWNER_USER_ID,
                                   IS_ACTIVE, START_TIME, CONTEXT, BRANCH_ID)
        VALUES ({session_id_sql}, :aid, :wid, :pred, :owner,
                'Y', CURRENT_TIMESTAMP, :ctx, :vbrid)
        RETURNING SESSION_ID INTO :ret_id
    """
    new_session_id = execute_insert_returning_id(sql, {
        "aid": new_agent_id,
        "wid": workspace_id,
        "pred": current_session_id,
        "owner": ws.get("owner_user_id"),
        "ctx": json.dumps(handoff_data) if isinstance(handoff_data, (dict, list)) else handoff_data,
        "vbrid": branch_id,
    }, id_column="SESSION_ID")

    save_context(
        workspace_id=workspace_id,
        agent_id=new_agent_id,
        context_type="HANDOFF",
        context_data=handoff_data or {},
        session_id=new_session_id,
        parent_context_id=latest_ctx.get("context_id") if latest_ctx else None,
        branch_id=branch_id,
    )

    update_workspace(
        workspace_id,
        current_agent_id=new_agent_id,
        current_session_id=new_session_id,
    )

    return new_session_id


def recover_workspace(workspace_id: str) -> Dict[str, Any]:
    """Return the complete recoverable state of a workspace."""
    ws = get_workspace(workspace_id)
    if ws is None:
        raise ValueError(f"Workspace not found: {workspace_id}")

    context_chain = get_context_chain(workspace_id, limit=5)

    active_tasks_sql = """
        SELECT tp.PLAN_ID, tp.GOAL, tp.STATUS,
               tp.PRIORITY, tp.STRATEGY,
               TO_CHAR(tp.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(tp.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM TASK_PLANS tp
        JOIN WORKSPACE_TASKS wt ON tp.PLAN_ID = wt.PLAN_ID
        WHERE wt.WORKSPACE_ID = :wid
          AND tp.STATUS IN ('PENDING', 'RUNNING', 'BLOCKED')
        ORDER BY tp.UPDATED_AT DESC
    """
    active_tasks = execute_query(active_tasks_sql, {"wid": workspace_id})

    recent_sessions_sql = """
        SELECT SESSION_ID, AGENT_ID, WORKSPACE_ID, PREDECESSOR_SESSION_ID,
               OWNER_USER_ID, IS_ACTIVE,
               TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
               TO_CHAR(END_TIME, 'YYYY-MM-DD HH24:MI:SS') AS END_TIME,
               CONTEXT
        FROM AGENT_SESSION
        WHERE WORKSPACE_ID = :wid
        ORDER BY START_TIME DESC
        FETCH FIRST 5 ROWS ONLY
    """
    recent_sessions = [_row_to_dict(r) for r in execute_query(recent_sessions_sql, {"wid": workspace_id})]

    recent_entities: List[Dict[str, Any]] = []
    if ws.get("isolation_mode") == "ISOLATED":
        recent_entities_sql = """
            SELECT ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM ENTITIES
            WHERE WORKSPACE_ID = :wid
            ORDER BY UPDATED_AT DESC
            FETCH FIRST 10 ROWS ONLY
        """
        recent_entities = [_row_to_dict(r) for r in execute_query(recent_entities_sql, {"wid": workspace_id})]

    return {
        "workspace": ws,
        "context_chain": context_chain,
        "active_tasks": active_tasks,
        "recent_sessions": recent_sessions,
        "recent_entities": recent_entities,
    }


def link_task_to_workspace(workspace_id: str, plan_id: str) -> bool:
    """Link a task plan to a workspace."""
    sql = """
        INSERT INTO WORKSPACE_TASKS (WORKSPACE_ID, PLAN_ID, ASSIGNED_AT)
        VALUES (:wid, :pid, CURRENT_TIMESTAMP)
    """
    return execute(sql, {"wid": workspace_id, "pid": plan_id}) > 0


def get_workspace_tasks(workspace_id: str) -> List[Dict[str, Any]]:
    """Return all tasks linked to a workspace."""
    sql = """
        SELECT tp.PLAN_ID, tp.GOAL, tp.STATUS,
               tp.PRIORITY, tp.STRATEGY, tp.AGENT_ID,
               TO_CHAR(tp.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(tp.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT,
               wt.WORKSPACE_ID,
               TO_CHAR(wt.ASSIGNED_AT, 'YYYY-MM-DD HH24:MI:SS') AS ASSIGNED_AT
        FROM TASK_PLANS tp
        JOIN WORKSPACE_TASKS wt ON tp.PLAN_ID = wt.PLAN_ID
        WHERE wt.WORKSPACE_ID = :wid
        ORDER BY tp.UPDATED_AT DESC
    """
    return execute_query(sql, {"wid": workspace_id})
