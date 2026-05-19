"""Oracle Memory System v2.1.0 - Agent API

Agent registration, session management, access audit logging,
and collaboration tracking.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"capabilities", "config", "context"}

_ALLOWED_UPDATE_FIELDS = {
    "agent_name", "agent_type", "description",
    "capabilities", "config", "status", "wm_entity_id",
}


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        result = dict(row)
    else:
        result = dict(row)
    for key in result:
        if key.lower() in _JSON_COLUMNS and isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


def register_agent(
    agent_id: str,
    agent_name: str,
    agent_type: Optional[str] = None,
    description: Optional[str] = None,
    capabilities: Optional[Any] = None,
    config: Optional[Any] = None,
) -> str:
    """Register a new agent or update an existing one via MERGE."""
    sql = """
        MERGE INTO AGENT_REGISTRY t
        USING (SELECT :aid AS AGENT_ID FROM DUAL) s
        ON (t.AGENT_ID = s.AGENT_ID)
        WHEN NOT MATCHED THEN
            INSERT (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION,
                    CAPABILITIES, CONFIG, STATUS, CREATED_AT, UPDATED_AT)
            VALUES (:aid, :aname, :atype, :adesc, :caps, :cfg, 'ACTIVE',
                    SYSTIMESTAMP, SYSTIMESTAMP)
        WHEN MATCHED THEN
            UPDATE SET AGENT_NAME = :aname,
                       LAST_SEEN_AT = SYSTIMESTAMP
    """
    caps_val = json.dumps(capabilities) if isinstance(capabilities, (dict, list)) else capabilities
    cfg_val = json.dumps(config) if isinstance(config, (dict, list)) else config
    execute(sql, {
        "aid": agent_id,
        "aname": agent_name,
        "atype": agent_type,
        "adesc": description,
        "caps": caps_val,
        "cfg": cfg_val,
    })
    return agent_id


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve agent details by ID."""
    sql = """
        SELECT AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION,
               CAPABILITIES, CONFIG, WM_ENTITY_ID, STATUS,
               TO_CHAR(LAST_SEEN_AT, 'YYYY-MM-DD HH24:MI:SS') AS LAST_SEEN_AT,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM AGENT_REGISTRY
        WHERE AGENT_ID = :aid
    """
    row = execute_query_one(sql, {"aid": agent_id})
    return _row_to_dict(row) if row else None


def update_agent(agent_id: str, **kwargs: Any) -> bool:
    """Update allowed fields on an agent. JSON fields are auto-serialized."""
    updates = {}
    params: Dict[str, Any] = {"aid": agent_id}
    for key, value in kwargs.items():
        col = key.lower()
        if col not in _ALLOWED_UPDATE_FIELDS:
            continue
        db_col = col.upper()
        if col in ("capabilities", "config") and isinstance(value, (dict, list)):
            updates[db_col] = f":{col}"
            params[col] = json.dumps(value)
        else:
            updates[db_col] = f":{col}"
            params[col] = value
    if not updates:
        return False
    updates["UPDATED_AT"] = "SYSTIMESTAMP"
    set_clause = ", ".join(f"{k} = {v}" for k, v in updates.items())
    sql = f"UPDATE AGENT_REGISTRY SET {set_clause} WHERE AGENT_ID = :aid"
    return execute(sql, params) > 0


def decommission_agent(agent_id: str) -> bool:
    """Mark an agent as decommissioned."""
    sql = """
        UPDATE AGENT_REGISTRY
        SET STATUS = 'DECOMMISSIONED', UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = :aid
    """
    return execute(sql, {"aid": agent_id}) > 0


def heartbeat(agent_id: str) -> bool:
    """Update the agent's last-seen timestamp."""
    sql = """
        UPDATE AGENT_REGISTRY
        SET LAST_SEEN_AT = SYSTIMESTAMP
        WHERE AGENT_ID = :aid
    """
    return execute(sql, {"aid": agent_id}) > 0


def create_session(
    agent_id: str,
    wm_entity_id: Optional[str] = None,
    context: Optional[Any] = None,
) -> str:
    """Create a new agent session and return the session ID."""
    session_id_sql = "'SES_' || RAWTOHEX(SYS_GUID())"
    ctx_val = json.dumps(context) if isinstance(context, (dict, list)) else context
    sql = f"""
        INSERT INTO AGENT_SESSION (SESSION_ID, AGENT_ID, WM_ENTITY_ID, IS_ACTIVE, START_TIME, CONTEXT)
        VALUES ({session_id_sql}, :aid, :wmid, 'Y', SYSTIMESTAMP, :ctx)
        RETURNING SESSION_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "aid": agent_id,
        "wmid": wm_entity_id,
        "ctx": ctx_val,
    }, id_column="SESSION_ID")


def end_session(session_id: str) -> bool:
    """End an active session."""
    sql = """
        UPDATE AGENT_SESSION
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP
        WHERE SESSION_ID = :sid AND IS_ACTIVE = 'Y'
    """
    return execute(sql, {"sid": session_id}) > 0


def get_active_sessions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all active sessions, optionally filtered by agent."""
    if agent_id:
        sql = """
            SELECT SESSION_ID, AGENT_ID, WM_ENTITY_ID, IS_ACTIVE,
                   TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   CONTEXT
            FROM AGENT_SESSION
            WHERE IS_ACTIVE = 'Y' AND AGENT_ID = :aid
            ORDER BY START_TIME DESC
        """
        rows = execute_query(sql, {"aid": agent_id})
    else:
        sql = """
            SELECT SESSION_ID, AGENT_ID, WM_ENTITY_ID, IS_ACTIVE,
                   TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   CONTEXT
            FROM AGENT_SESSION
            WHERE IS_ACTIVE = 'Y'
            ORDER BY START_TIME DESC
        """
        rows = execute_query(sql)
    return [_row_to_dict(r) for r in rows]


def log_access(
    agent_id: str,
    entity_id: str,
    access_type: str,
    session_id: Optional[str] = None,
) -> str:
    """Log an entity access event and return the log ID."""
    log_id_sql = "'LOG_' || RAWTOHEX(SYS_GUID())"
    sql = f"""
        INSERT INTO ENTITY_ACCESS_LOG (LOG_ID, ENTITY_ID, AGENT_ID, ACCESS_TYPE, ACCESS_TIME, SESSION_ID)
        VALUES ({log_id_sql}, :eid, :aid, :atype, SYSTIMESTAMP, :sid)
        RETURNING LOG_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "eid": entity_id,
        "aid": agent_id,
        "atype": access_type,
        "sid": session_id,
    }, id_column="LOG_ID")


def get_access_log(
    entity_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query access logs with optional entity or agent filter."""
    conditions = []
    params: Dict[str, Any] = {"lim": limit}
    if entity_id:
        conditions.append("ENTITY_ID = :eid")
        params["eid"] = entity_id
    if agent_id:
        conditions.append("AGENT_ID = :aid")
        params["aid"] = agent_id
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT LOG_ID, ENTITY_ID, AGENT_ID, ACCESS_TYPE, SESSION_ID,
               TO_CHAR(ACCESS_TIME, 'YYYY-MM-DD HH24:MI:SS') AS ACCESS_TIME,
               CONTEXT
        FROM ENTITY_ACCESS_LOG
        {where}
        ORDER BY ACCESS_TIME DESC
        FETCH FIRST :lim ROWS ONLY
    """
    rows = execute_query(sql, params)
    return [_row_to_dict(r) for r in rows]


def create_collaboration(
    source_agent_id: str,
    target_agent_id: str,
    col_type: str,
    entity_id: Optional[str] = None,
    context: Optional[Any] = None,
    strength: float = 1.0,
) -> str:
    """Create a collaboration link between two agents."""
    col_id_sql = "'COL_' || RAWTOHEX(SYS_GUID())"
    ctx_val = json.dumps(context) if isinstance(context, (dict, list)) else context
    sql = f"""
        INSERT INTO AGENT_COLLABORATION (COL_ID, SOURCE_AGENT_ID, TARGET_AGENT_ID,
                                          COL_TYPE, ENTITY_ID, CONTEXT, STRENGTH,
                                          CREATED_AT, UPDATED_AT)
        VALUES ({col_id_sql}, :src, :tgt, :ctype, :eid, :ctx, :str,
                SYSTIMESTAMP, SYSTIMESTAMP)
        RETURNING COL_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "src": source_agent_id,
        "tgt": target_agent_id,
        "ctype": col_type,
        "eid": entity_id,
        "ctx": ctx_val,
        "str": strength,
    }, id_column="COL_ID")


def get_collaborations(
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query collaborations, optionally filtered by agent involvement."""
    if agent_id:
        sql = """
            SELECT COL_ID, SOURCE_AGENT_ID, TARGET_AGENT_ID, COL_TYPE,
                   ENTITY_ID, CONTEXT, STRENGTH,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM AGENT_COLLABORATION
            WHERE SOURCE_AGENT_ID = :aid OR TARGET_AGENT_ID = :aid
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        rows = execute_query(sql, {"aid": agent_id, "lim": limit})
    else:
        sql = """
            SELECT COL_ID, SOURCE_AGENT_ID, TARGET_AGENT_ID, COL_TYPE,
                   ENTITY_ID, CONTEXT, STRENGTH,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM AGENT_COLLABORATION
            ORDER BY CREATED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        rows = execute_query(sql, {"lim": limit})
    return [_row_to_dict(r) for r in rows]
