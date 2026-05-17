"""Oracle Memory System v2.0.0 - Multi-Agent API

Agent registration, memory visibility control, session management,
access audit logging, and collaboration requests.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def register_agent(
    agent_id: str,
    agent_name: str,
    agent_type: str = "general",
    capabilities: Optional[List[str]] = None,
    description: str = "",
    permission_level: str = "READ_WRITE",
) -> bool:
    sql = """
        MERGE INTO AGENT_REGISTRY t
        USING (SELECT :aid AS AGENT_ID FROM DUAL) s
        ON (t.AGENT_ID = s.AGENT_ID)
        WHEN NOT MATCHED THEN
            INSERT (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION,
                    CAPABILITIES, STATUS, PERMISSION_LEVEL)
            VALUES (:aid, :aname, :atype, :adesc, :caps, 'ACTIVE', :perm)
    """
    try:
        execute(sql, {
            "aid": agent_id,
            "aname": agent_name,
            "atype": agent_type,
            "adesc": description,
            "caps": json.dumps(capabilities or []),
            "perm": permission_level,
        })
        return True
    except Exception as e:
        logger.error("Failed to register agent %s: %s", agent_id, e)
        return False


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    sql = """
        SELECT AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION, STATUS,
               CAPABILITIES, PERMISSION_LEVEL,
               TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
               TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
        FROM AGENT_REGISTRY
        WHERE AGENT_ID = :aid
    """
    row = execute_query_one(sql, {"aid": agent_id})
    if row and isinstance(row.get("capabilities"), str):
        try:
            row["capabilities"] = json.loads(row["capabilities"])
        except (json.JSONDecodeError, TypeError):
            pass
    return row


def list_agents(agent_type: Optional[str] = None, status: str = "ACTIVE") -> List[Dict[str, Any]]:
    conditions = ["STATUS = :status"]
    params: Dict[str, Any] = {"status": status}
    if agent_type:
        conditions.append("AGENT_TYPE = :atype")
        params["atype"] = agent_type

    where = " AND ".join(conditions)
    sql = f"""
        SELECT AGENT_ID, AGENT_NAME, AGENT_TYPE, CAPABILITIES, PERMISSION_LEVEL
        FROM AGENT_REGISTRY
        WHERE {where}
        ORDER BY CREATED_AT
    """
    rows = execute_query(sql, params)
    for r in rows:
        if isinstance(r.get("capabilities"), str):
            try:
                r["capabilities"] = json.loads(r["capabilities"])
            except (json.JSONDecodeError, TypeError):
                pass
    return rows


def disable_agent(agent_id: str, reason: str = "") -> bool:
    sql = """
        UPDATE AGENT_REGISTRY
        SET STATUS = 'DISABLED', UPDATED_AT = SYSTIMESTAMP,
            PENDING_RECOVERY = 'Y'
        WHERE AGENT_ID = :aid
    """
    if execute(sql, {"aid": agent_id}) > 0:
        log_sql = """
            INSERT INTO AGENT_PERMISSION_LOG (AGENT_ID, OLD_STATUS, NEW_STATUS, CHANGE_REASON, STATUS)
            VALUES (:aid, 'ACTIVE', 'DISABLED', :reason, 'COMPLETED')
        """
        execute(log_sql, {"aid": agent_id, "reason": reason})
        return True
    return False


def enable_agent(agent_id: str) -> bool:
    sql = """
        UPDATE AGENT_REGISTRY
        SET STATUS = 'ACTIVE', UPDATED_AT = SYSTIMESTAMP,
            PENDING_RECOVERY = 'N', RECOVERED_COUNT = RECOVERED_COUNT + 1
        WHERE AGENT_ID = :aid
    """
    return execute(sql, {"aid": agent_id}) > 0


def create_session(agent_id: str, working_memory_id: Optional[int] = None) -> Optional[str]:
    import time
    session_id = f"session-{agent_id}-{int(time.time())}"
    sql = """
        INSERT INTO AGENT_SESSION (SESSION_ID, AGENT_ID, IS_ACTIVE, CONTEXT_SNAPSHOT, WORKING_MEMORY_ID)
        VALUES (:sid, :aid, 'Y', '{}', :wmid)
    """
    try:
        execute(sql, {"sid": session_id, "aid": agent_id, "wmid": working_memory_id})
        return session_id
    except Exception as e:
        logger.error("Failed to create session: %s", e)
        return None


def update_session_context(session_id: str, context: Dict[str, Any]) -> bool:
    sql = """
        UPDATE AGENT_SESSION
        SET CONTEXT_SNAPSHOT = :ctx, LAST_ACTIVITY = SYSTIMESTAMP
        WHERE SESSION_ID = :sid AND IS_ACTIVE = 'Y'
    """
    return execute(sql, {"sid": session_id, "ctx": json.dumps(context)}) > 0


def close_session(session_id: str) -> bool:
    sql = """
        UPDATE AGENT_SESSION
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP
        WHERE SESSION_ID = :sid
    """
    return execute(sql, {"sid": session_id}) > 0


def get_active_sessions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if agent_id:
        sql = """
            SELECT s.SESSION_ID, s.AGENT_ID, a.AGENT_NAME,
                   TO_CHAR(s.START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   s.IS_ACTIVE, s.WORKING_MEMORY_ID
            FROM AGENT_SESSION s
            LEFT JOIN AGENT_REGISTRY a ON a.AGENT_ID = s.AGENT_ID
            WHERE s.IS_ACTIVE = 'Y' AND s.AGENT_ID = :aid
            ORDER BY s.START_TIME DESC
        """
        return execute_query(sql, {"aid": agent_id})
    else:
        sql = """
            SELECT s.SESSION_ID, s.AGENT_ID, a.AGENT_NAME,
                   TO_CHAR(s.START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   s.IS_ACTIVE, s.WORKING_MEMORY_ID
            FROM AGENT_SESSION s
            LEFT JOIN AGENT_REGISTRY a ON a.AGENT_ID = s.AGENT_ID
            WHERE s.IS_ACTIVE = 'Y'
            ORDER BY s.START_TIME DESC
        """
        return execute_query(sql)


def log_access(agent_id: str, entity_id: int, access_type: str = "READ") -> None:
    sql = """
        INSERT INTO ENTITY_ACCESS_LOG (AGENT_ID, ENTITY_ID, ACCESS_TYPE, ACCESS_TIME)
        VALUES (:aid, :eid, :atype, SYSTIMESTAMP)
    """
    execute(sql, {"aid": agent_id, "eid": entity_id, "atype": access_type})


def get_access_history(agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """
        SELECT AGENT_ID, ENTITY_ID, ACCESS_TYPE,
               TO_CHAR(ACCESS_TIME, 'YYYY-MM-DD HH24:MI:SS') AS ACCESS_TIME
        FROM ENTITY_ACCESS_LOG
        WHERE AGENT_ID = :aid
        ORDER BY ACCESS_TIME DESC
        FETCH FIRST :lim ROWS ONLY
    """
    return execute_query(sql, {"aid": agent_id, "lim": limit})


def request_collaboration(sharing_agent: str, receiving_agent: str,
                          entity_id: int, reason: str = "") -> Optional[int]:
    sql = """
        INSERT INTO AGENT_COLLABORATION (SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID,
                                         SHARE_REASON, STATUS)
        VALUES (:sharer, :receiver, :eid, :reason, 'PENDING')
        RETURNING COLLAB_ID INTO :ret_id
    """
    try:
        return execute_insert_returning_id(sql, {
            "sharer": sharing_agent,
            "receiver": receiving_agent,
            "eid": entity_id,
            "reason": reason,
        })
    except Exception as e:
        logger.error("Failed to request collaboration: %s", e)
        return None


def approve_collaboration(collab_id: int) -> bool:
    sql = """
        UPDATE AGENT_COLLABORATION
        SET STATUS = 'ACCEPTED', APPROVED_AT = SYSTIMESTAMP
        WHERE COLLAB_ID = :cid AND STATUS = 'PENDING'
    """
    return execute(sql, {"cid": collab_id}) > 0


def reject_collaboration(collab_id: int) -> bool:
    sql = """
        UPDATE AGENT_COLLABORATION
        SET STATUS = 'REJECTED'
        WHERE COLLAB_ID = :cid AND STATUS = 'PENDING'
    """
    return execute(sql, {"cid": collab_id}) > 0


def get_pending_requests(agent_id: str, role: str = "receiving") -> List[Dict[str, Any]]:
    if role == "receiving":
        sql = """
            SELECT COLLAB_ID, SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID,
                   SHARE_REASON, STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM AGENT_COLLABORATION
            WHERE RECEIVING_AGENT = :aid AND STATUS = 'PENDING'
            ORDER BY CREATED_AT DESC
        """
    else:
        sql = """
            SELECT COLLAB_ID, SHARING_AGENT, RECEIVING_AGENT, MEMORY_ID,
                   SHARE_REASON, STATUS,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT
            FROM AGENT_COLLABORATION
            WHERE SHARING_AGENT = :aid AND STATUS = 'PENDING'
            ORDER BY CREATED_AT DESC
        """
    return execute_query(sql, {"aid": agent_id})
