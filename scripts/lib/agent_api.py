"""AI Agent Infra v4.3.6 - Community Edition - Agent API

Agent registration, session management, access audit logging,
collaboration tracking, and Admin/Agent separation support.
"""

import secrets
import json
import logging
import oracledb
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id, sanitize_row, get_connection, execute_plsql

logger = logging.getLogger(__name__)

_JSON_COLUMNS = {"capabilities", "config", "context"}

_ALLOWED_UPDATE_FIELDS = {
    "agent_name", "agent_type", "description",
    "capabilities", "config", "status", "wm_entity_id",
}


def _database_user_name(agent_id: str) -> str:
    """Keep the legacy Oracle mapping while rejecting unsafe identifiers."""
    name = str(agent_id or "").replace("-", "_").upper()
    if not name or len(name) > 128 or not name[0].isalpha() or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$#_" for char in name
    ):
        raise ValueError("Agent ID cannot be mapped to a safe Oracle End User name")
    return name


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
    """Register a new agent or update an existing one via MERGE.
    Also creates a Deep Sec End User for Data Grant enforcement."""
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
    try:
        from .agent_registration import register_agent as register_identity
        register_identity(
            agent_id=agent_id, owner_ref="legacy-api", runtime=agent_type or "platform",
            environment="managed", capabilities=capabilities if isinstance(capabilities, (list, tuple)) else [],
            idempotency_key=f"legacy-api-{agent_id}", created_by="legacy-api",
        )
    except Exception as exc:
        logger.debug("Registered identity deferred for %s: %s", agent_id, exc)
    _ensure_end_user(agent_id)
    return agent_id


def _ensure_end_user(agent_id: str) -> None:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                result_var = cur.var(oracledb.STRING)
                cur.execute(
                    "BEGIN :r := END_USER_MANAGER.ensure_end_user(:aid); END;",
                    {"r": result_var, "aid": agent_id},
                )
                result = result_var.getvalue()
                if result and not str(result).startswith('ERROR'):
                    conn.commit()
                    logger.info("Deep Sec End User ensured for %s", agent_id)
                else:
                    logger.debug("End User for %s: %s", agent_id, result)
    except Exception as e:
        logger.debug("End User creation skipped for %s: %s", agent_id, e)


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
    owner_user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    predecessor_session_id: Optional[str] = None,
    branch_id: Optional[str] = None,
) -> str:
    """Create a new agent session and return the session ID."""
    session_id_sql = "'SES_' || RAWTOHEX(SYS_GUID())"
    ctx_val = json.dumps(context) if isinstance(context, (dict, list)) else context
    sql = f"""
        INSERT INTO AGENT_SESSION (SESSION_ID, AGENT_ID, WM_ENTITY_ID, 
            OWNER_USER_ID, WORKSPACE_ID, PREDECESSOR_SESSION_ID, BRANCH_ID,
            IS_ACTIVE, START_TIME, CONTEXT)
        VALUES ({session_id_sql}, :aid, :wmid, :owner_uid, :ws_id, :pred_sid, :vbrid,
            'Y', SYSTIMESTAMP, :ctx)
        RETURNING SESSION_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "aid": agent_id,
        "wmid": wm_entity_id,
        "owner_uid": owner_user_id,
        "ws_id": workspace_id,
        "pred_sid": predecessor_session_id,
        "vbrid": branch_id,
        "ctx": ctx_val,
    }, id_column="SESSION_ID")


def end_session(session_id: str) -> bool:
    """End an active session."""
    sql = """
        UPDATE AGENT_SESSION
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP
        WHERE SESSION_ID = :sid AND IS_ACTIVE = 'Y'
    """
    result = execute(sql, {"sid": session_id}) > 0
    # TODO: auto-save SUMMARY context to workspace if session has WORKSPACE_ID
    # This will be implemented in the Python API layer to avoid circular imports
    # with workspace_api module.
    return result


def checkpoint_session(session_id: str, context_data: Any) -> Optional[str]:
    """Save a checkpoint context for the session's workspace. Returns context_id on success, None on failure."""
    sql = """
        SELECT WORKSPACE_ID, AGENT_ID
        FROM AGENT_SESSION
        WHERE SESSION_ID = :sid
    """
    row = execute_query_one(sql, {"sid": session_id})
    if not row or not row.get("workspace_id"):
        return None
    from .workspace_api import save_context
    save_context(
        workspace_id=row["workspace_id"],
        agent_id=row["agent_id"],
        context_type="CHECKPOINT",
        context_data=context_data,
        session_id=session_id,
    )
    ctx_row = execute_query_one("""
        SELECT CONTEXT_ID FROM WORKSPACE_CONTEXT
        WHERE SESSION_ID = :vsid AND CONTEXT_TYPE = 'CHECKPOINT'
        ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY
    """, {"vsid": session_id})
    return ctx_row["context_id"] if ctx_row else None


def get_session_chain(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Trace the session chain backwards via PREDECESSOR_SESSION_ID."""
    chain = []
    current_id = session_id
    visited = set()
    while current_id and current_id not in visited and len(chain) < limit:
        visited.add(current_id)
        sql = """
            SELECT SESSION_ID, AGENT_ID, WORKSPACE_ID, PREDECESSOR_SESSION_ID,
                   IS_ACTIVE,
                   TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   TO_CHAR(END_TIME, 'YYYY-MM-DD HH24:MI:SS') AS END_TIME,
                   CONTEXT
            FROM AGENT_SESSION
            WHERE SESSION_ID = :sid
        """
        row = execute_query_one(sql, {"sid": current_id})
        if not row:
            break
        chain.append(_row_to_dict(row))
        current_id = row.get("predecessor_session_id")
    return chain


def get_active_sessions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all active sessions, optionally filtered by agent."""
    if agent_id:
        sql = """
            SELECT SESSION_ID, AGENT_ID, WM_ENTITY_ID, WORKSPACE_ID, OWNER_USER_ID,
                   IS_ACTIVE,
                   TO_CHAR(START_TIME, 'YYYY-MM-DD HH24:MI:SS') AS START_TIME,
                   CONTEXT
            FROM AGENT_SESSION
            WHERE IS_ACTIVE = 'Y' AND AGENT_ID = :aid
            ORDER BY START_TIME DESC
        """
        rows = execute_query(sql, {"aid": agent_id})
    else:
        sql = """
            SELECT SESSION_ID, AGENT_ID, WM_ENTITY_ID, WORKSPACE_ID, OWNER_USER_ID,
                   IS_ACTIVE,
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


def issue_credential(agent_id, user_id, scope, credential_type='ACCESS_TOKEN', expires_at=None):
    enc_result = execute_query_one("SELECT DB_CRYPTO.encrypt(:plain) AS ciphertext FROM DUAL", {"plain": json.dumps(scope)})
    encrypted_value = enc_result['ciphertext'] if enc_result else json.dumps(scope)
    row = execute_query_one("SELECT RAWTOHEX(SYS_GUID()) AS ID FROM DUAL")
    cred_id = "CRED_" + row["id"]
    sql = """
        INSERT INTO AGENT_CREDENTIALS (CREDENTIAL_ID, AGENT_ID, USER_ID,
            CREDENTIAL_TYPE, CREDENTIAL_VALUE, SCOPE, IS_ACTIVE, CREATED_AT, EXPIRES_AT)
        VALUES (:cid, :aid, :vuid, :ctype, :cval, :cscope, 'Y', SYSTIMESTAMP, :exp)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"cid": cred_id, "aid": agent_id, "vuid": user_id, "ctype": credential_type,
                              "cval": encrypted_value, "cscope": json.dumps(scope), "exp": expires_at})
            conn.commit()
    return cred_id


def verify_credential(credential_id):
    row = execute_query_one("""
        SELECT CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE,
               CREDENTIAL_VALUE, SCOPE, IS_ACTIVE, EXPIRES_AT
        FROM AGENT_CREDENTIALS WHERE CREDENTIAL_ID = :cid
    """, {"cid": credential_id})
    if not row or row.get("is_active") != 'Y':
        return None
    expires_at = row.get("expires_at")
    if expires_at:
        from datetime import datetime
        if hasattr(expires_at, 'isoformat'):
            expires_at = datetime.fromisoformat(expires_at.isoformat())
        if expires_at < datetime.now():
            return None
    try:
        dec_result = execute_query_one("SELECT DB_CRYPTO.decrypt(:cipher) AS plaintext FROM DUAL", {"cipher": row["credential_value"]})
        scope = json.loads(dec_result['plaintext']) if dec_result and dec_result.get('plaintext') else row.get("scope", {})
    except Exception:
        scope = row.get("scope", {})
    return {
        "credential_id": row["credential_id"],
        "agent_id": row["agent_id"],
        "user_id": row["user_id"],
        "credential_type": row["credential_type"],
        "scope": scope,
        "expires_at": row.get("expires_at"),
    }


def get_credentials_for_user(user_id, agent_id=None):
    if agent_id:
        sql = """SELECT CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE, SCOPE,
                   IS_ACTIVE, EXPIRES_AT, CREATED_AT
           FROM AGENT_CREDENTIALS WHERE USER_ID = :b1 AND AGENT_ID = :b2 AND IS_ACTIVE = 'Y'
           ORDER BY CREATED_AT DESC"""
        rows = execute_query(sql, {"b1": user_id, "b2": agent_id})
    else:
        sql = """SELECT CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE, SCOPE,
                   IS_ACTIVE, EXPIRES_AT, CREATED_AT
           FROM AGENT_CREDENTIALS WHERE USER_ID = :b1 AND IS_ACTIVE = 'Y'
           ORDER BY CREATED_AT DESC"""
        rows = execute_query(sql, {"b1": user_id})
    return [_row_to_dict(r) for r in rows]


def revoke_credential(credential_id):
    return execute("""
        UPDATE AGENT_CREDENTIALS SET IS_ACTIVE = 'N'
        WHERE CREDENTIAL_ID = :cid AND IS_ACTIVE = 'Y'
    """, {"cid": credential_id}) > 0


def hibernate_agent(agent_id, portal_node_id=None):
    params = {"aid": agent_id}
    node_condition = ""
    if portal_node_id:
        params["node_id"] = portal_node_id
        node_condition = " AND PORTAL_NODE_ID = :node_id"
    return execute("""
        UPDATE AGENT_REGISTRY
        SET STATUS = 'POOL', CURRENT_USER_ID = NULL, PORTAL_NODE_ID = NULL,
            UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = :aid AND STATUS = 'ACTIVE'
    """ + node_condition, params) > 0


def reclaim_portal_agents(portal_node_id: str) -> int:
    if not portal_node_id:
        return 0
    assigned = execute_query("""
        SELECT AGENT_ID FROM AGENT_REGISTRY
        WHERE STATUS = 'ACTIVE' AND PORTAL_NODE_ID = :node_id
    """, {"node_id": portal_node_id})
    for row in assigned:
        for session in get_active_sessions(row.get("agent_id")):
            try:
                end_session(session.get("session_id"))
            except Exception:
                logger.warning("Unable to close stale Portal session for %s", row.get("agent_id"))
    return execute("""
        UPDATE AGENT_REGISTRY
        SET STATUS = 'POOL', CURRENT_USER_ID = NULL, PORTAL_NODE_ID = NULL,
            UPDATED_AT = SYSTIMESTAMP
        WHERE STATUS = 'ACTIVE' AND PORTAL_NODE_ID = :node_id
    """, {"node_id": portal_node_id})


def wake_agent(agent_id, user_id=None, credential_id=None):
    agent = get_agent(agent_id)
    if not agent or agent.get("status") not in ("DORMANT", "POOL"):
        return None
    if credential_id:
        cred = verify_credential(credential_id)
        if not cred:
            return None
        if user_id is None:
            user_id = cred.get("user_id")
    params = {"b1": agent_id}
    set_parts = ["STATUS = 'ACTIVE'", "PORTAL_NODE_ID = NULL", "LAST_ACTIVE_AT = SYSTIMESTAMP", "UPDATED_AT = SYSTIMESTAMP"]
    if user_id:
        set_parts.append("CURRENT_USER_ID = :b2")
        params["b2"] = user_id
    sql = "UPDATE AGENT_REGISTRY SET " + ", ".join(set_parts) + " WHERE AGENT_ID = :b1"
    execute(sql, params)
    refreshed = get_agent(agent_id)
    if not refreshed:
        return None
    result = _row_to_dict(refreshed)
    if user_id:
        from .workspace_api import get_user_workspaces
        workspaces = get_user_workspaces(user_id)
        result["user_workspaces"] = workspaces
    return result


def register_pool_agent(agent_id, pool_config):
    agent = get_agent(agent_id)
    if not agent:
        return False
    cfg = agent.get("config", {}) or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    cfg["pool_config"] = pool_config
    return update_agent(agent_id, config=cfg, status="POOL")


def assign_pool_agent(user_id, required_skills):
    rows = execute_query("""
        SELECT AGENT_ID, CONFIG FROM AGENT_REGISTRY WHERE STATUS = 'POOL'
    """)
    best_agent = None
    best_score = -1
    for row in rows:
        config = row.get("config", {})
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except Exception:
                config = {}
        pool_config = config.get("pool_config", {}) if isinstance(config, dict) else {}
        skills_tags = pool_config.get("skills_tags", [])
        score = len(set(required_skills) & set(skills_tags))
        if score > best_score:
            best_score = score
            best_agent = row["agent_id"]
    if best_agent is None or best_score == 0:
        return None
    execute("""
        UPDATE AGENT_REGISTRY
        SET STATUS = 'ACTIVE', CURRENT_USER_ID = :b1,
            LAST_ACTIVE_AT = SYSTIMESTAMP, UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = :b2
    """, {"b1": user_id, "b2": best_agent})
    return _row_to_dict(get_agent(best_agent))


def assign_random_pool_agent(user_id: str, portal_node_id: Optional[str] = None, excluded_agent_ids=None) -> Optional[Dict[str, Any]]:
    rows = execute_query("""
        SELECT a.AGENT_ID FROM AGENT_REGISTRY a
        LEFT JOIN AGENT_REGISTRATIONS r ON r.AGENT_ID = a.AGENT_ID
        WHERE a.STATUS = 'POOL'
          AND (r.AGENT_ID IS NULL OR r.STATUS = 'ACTIVE')
        ORDER BY DBMS_RANDOM.VALUE
    """)
    excluded = {str(value) for value in (excluded_agent_ids or ())}
    for row in rows:
        agent_id = row["agent_id"]
        if str(agent_id) in excluded:
            continue
        claimed = execute("""
            UPDATE AGENT_REGISTRY
            SET STATUS = 'ACTIVE', CURRENT_USER_ID = :b1, PORTAL_NODE_ID = :node_id,
                LAST_ACTIVE_AT = SYSTIMESTAMP, UPDATED_AT = SYSTIMESTAMP
            WHERE AGENT_ID = :b2 AND STATUS = 'POOL'
        """, {"b1": user_id, "b2": agent_id, "node_id": portal_node_id})
        if claimed != 1:
            continue
        result = _row_to_dict(get_agent(agent_id))
        if result and user_id:
            from .workspace_api import get_user_workspaces
            result["user_workspaces"] = get_user_workspaces(user_id)
        return result
    return None


import secrets as _secrets


def generate_admin_token() -> str:
    token = "AT_" + _secrets.token_hex(32)
    enc_result = execute_query_one("SELECT DB_CRYPTO.encrypt(:plain) AS ciphertext FROM DUAL", {"plain": token})
    encrypted = enc_result['ciphertext'] if enc_result else token
    execute("""
        MERGE INTO SYSTEM_CONFIG sc
        USING (SELECT 'admin.registration_token' AS k FROM DUAL) d
        ON (sc.CONFIG_KEY = d.k)
        WHEN MATCHED THEN UPDATE SET CONFIG_VALUE = :val, UPDATED_AT = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
            VALUES ('admin.registration_token', :val, 'Admin token for Agent registration (encrypted)')
    """, {"val": encrypted})
    logger.info("Generated new admin registration token")
    return token


def verify_admin_token(token: str) -> bool:
    if not token or not token.startswith("AT_"):
        return False
    row = execute_query_one(
        "SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = 'admin.registration_token'",
    )
    if not row:
        return False
    stored = row.get("config_value", "")
    if stored.startswith("AT_"):
        return _secrets.compare_digest(stored, token)
    try:
        dec = execute_query_one("SELECT DB_CRYPTO.decrypt(:cipher) AS plaintext FROM DUAL", {"cipher": stored})
        if dec and dec.get("plaintext"):
            return _secrets.compare_digest(dec["plaintext"], token)
    except Exception:
        pass
    return False


def register_agent_via_admin(
    agent_id: str,
    agent_name: str,
    admin_token: str,
    agent_type: Optional[str] = None,
    description: Optional[str] = None,
    capabilities: Optional[Any] = None,
    config: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    if not verify_admin_token(admin_token):
        logger.warning("Admin token verification failed for agent registration: %s", agent_id)
        return None

    register_agent(agent_id, agent_name, agent_type=agent_type,
                   description=description, capabilities=capabilities, config=config)

    eu_name = _database_user_name(agent_id)
    pwd = _get_end_user_password_direct(agent_id)
    if not pwd:
        logger.error("Failed to get End User password for %s after registration", agent_id)
        return None

    dsn = ""
    try:
        from .config import get_config
        dsn = get_config().database.dsn or ""
    except Exception:
        pass

    from .connection_crypto import encrypt_credential_for_distribution
    credential_data = {
        "username": eu_name,
        "password": pwd,
        "dsn": dsn,
        "db_type": "oracle",
    }
    encrypted = encrypt_credential_for_distribution(credential_data, admin_token)

    from .connection_crypto import generate_agent_crypto_key
    agent_crypto_key = generate_agent_crypto_key()
    _store_agent_crypto_key(agent_id, agent_crypto_key)
    _store_agent_crypto_key_version(agent_id, 1)

    recovery_codes = generate_recovery_codes(agent_id)

    return {
        "agent_id": agent_id,
        "end_user": {
            "credential_encrypted": encrypted["credential_encrypted"],
            "salt": encrypted["salt"],
        },
        "crypto_key": agent_crypto_key,
        "crypto_key_version": 1,
        "recovery_codes": recovery_codes,
    }


def _get_end_user_password_direct(agent_id: str) -> Optional[str]:
    try:
        row = execute_query_one(
            "SELECT config_value FROM system_config WHERE config_key = :key",
            {"key": f"end_user_pwd.{agent_id}"},
        )
        return row["config_value"] if row else None
    except Exception:
        return None


import hashlib as _hashlib


def generate_recovery_codes(agent_id: str, count: int = 8) -> List[str]:
    codes = []
    code_records = []
    for _ in range(count):
        segments = [secrets.token_hex(2).upper() for _ in range(3)]
        code = "RC-" + "-".join(segments)
        codes.append(code)
        h = _hashlib.sha256(code.encode()).hexdigest()
        code_records.append({"hash": h, "used": False})

    payload = json.dumps(code_records)
    enc_result = execute_query_one("SELECT DB_CRYPTO.encrypt(:plain) AS ciphertext FROM DUAL", {"plain": payload})
    encrypted = enc_result['ciphertext'] if enc_result else payload

    execute("""
        MERGE INTO SYSTEM_CONFIG sc
        USING (SELECT 'recovery_codes.' || :aid AS k FROM DUAL) d
        ON (sc.CONFIG_KEY = d.k)
        WHEN MATCHED THEN UPDATE SET CONFIG_VALUE = :val, UPDATED_AT = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
            VALUES ('recovery_codes.' || :aid, :val, 'Recovery codes for agent ' || :aid)
    """, {"aid": agent_id, "val": encrypted})

    logger.info("Generated %d recovery codes for agent %s", count, agent_id)
    return codes


def verify_recovery_code(agent_id: str, code: str) -> bool:
    row = execute_query_one(
        "SELECT CONFIG_VALUE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = :key",
        {"key": f"recovery_codes.{agent_id}"},
    )
    if not row:
        return False

    stored = row.get("config_value", "")
    try:
        dec = execute_query_one("SELECT DB_CRYPTO.decrypt(:cipher) AS plaintext FROM DUAL", {"cipher": stored})
        payload = dec["plaintext"] if dec else stored
    except Exception:
        payload = stored

    try:
        code_records = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return False

    code_hash = _hashlib.sha256(code.encode()).hexdigest()
    for rec in code_records:
        if rec.get("hash") == code_hash and not rec.get("used"):
            rec["used"] = True
            new_payload = json.dumps(code_records)
            enc_result = execute_query_one("SELECT DB_CRYPTO.encrypt(:plain) AS ciphertext FROM DUAL", {"plain": new_payload})
            new_encrypted = enc_result['ciphertext'] if enc_result else new_payload
            execute(
                "UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = :val WHERE CONFIG_KEY = :key",
                {"val": new_encrypted, "key": f"recovery_codes.{agent_id}"},
            )
            logger.info("Recovery code consumed for agent %s", agent_id)
            return True

    return False


def recover_agent_via_admin(
    agent_id: str,
    recovery_code: str,
    admin_token: str,
) -> Optional[Dict[str, Any]]:
    if not verify_admin_token(admin_token):
        logger.warning("Admin token verification failed for agent recovery: %s", agent_id)
        return None

    if not verify_recovery_code(agent_id, recovery_code):
        logger.warning("Invalid or used recovery code for agent: %s", agent_id)
        return None

    agent = execute_query_one(
        "SELECT STATUS, LAST_SEEN_AT FROM AGENT_REGISTRY WHERE AGENT_ID = :aid",
        {"aid": agent_id},
    )
    if agent is None:
        return None

    active_check = execute_query_one(
        """SELECT CASE
               WHEN CAST(SYSTIMESTAMP AS TIMESTAMP) - NVL(LAST_SEEN_AT, CAST(SYSTIMESTAMP AS TIMESTAMP) - NUMTOYMINTERVAL(1, 'YEAR')) < NUMTODSINTERVAL(5, 'MINUTE')
               THEN 'ACTIVE'
               ELSE 'INACTIVE'
           END AS check_result
           FROM AGENT_REGISTRY WHERE AGENT_ID = :aid""",
        {"aid": agent_id},
    )
    if active_check and active_check.get("check_result") == "ACTIVE":
        logger.warning("Recovery rejected: agent %s may still be active (LAST_SEEN_AT within 5 min)", agent_id)
        return None

    eu_name = _database_user_name(agent_id)
    new_pwd = secrets.token_hex(8)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'ALTER END USER "{eu_name}" IDENTIFIED BY "{new_pwd}"')
                conn.commit()
    except Exception as e:
        logger.warning("Failed to reset End User password for %s: %s", agent_id, e)
        return None

    execute("""
        UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = :pwd
        WHERE CONFIG_KEY = :key
    """, {"pwd": new_pwd, "key": f"end_user_pwd.{agent_id}"})

    execute("""
        UPDATE AGENT_REGISTRY SET STATUS = 'ACTIVE', UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = :aid
    """, {"aid": agent_id})

    dsn = ""
    try:
        from .config import get_config
        dsn = get_config().database.dsn or ""
    except Exception:
        pass

    from .connection_crypto import encrypt_credential_for_distribution
    credential_data = {
        "username": eu_name,
        "password": new_pwd,
        "dsn": dsn,
        "db_type": "oracle",
    }
    encrypted = encrypt_credential_for_distribution(credential_data, admin_token)

    logger.info("Agent %s recovered successfully", agent_id)
    return {
        "agent_id": agent_id,
        "recovered": True,
        "end_user": {
            "credential_encrypted": encrypted["credential_encrypted"],
            "salt": encrypted["salt"],
        },
    }


def _store_agent_crypto_key(agent_id: str, crypto_key: str) -> None:
    execute(
        "INSERT INTO SYSTEM_CONFIG (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) "
        "VALUES (:k, :v, :d) "
        "ON CONFLICT (CONFIG_KEY) DO UPDATE SET CONFIG_VALUE = :v",
        {"k": f"agent_crypto_key:{agent_id}", "v": crypto_key, "d": f"Per-Agent encryption key for {agent_id}"},
    ) if False else execute(
        "MERGE INTO SYSTEM_CONFIG t "
        "USING (SELECT :k AS CONFIG_KEY, :v AS CONFIG_VALUE FROM DUAL) s "
        "ON (t.CONFIG_KEY = s.CONFIG_KEY) "
        "WHEN MATCHED THEN UPDATE SET t.CONFIG_VALUE = s.CONFIG_VALUE "
        "WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) "
        "VALUES (s.CONFIG_KEY, s.CONFIG_VALUE, :d)",
        {"k": f"agent_crypto_key:{agent_id}", "v": crypto_key, "d": f"Per-Agent encryption key for {agent_id}"},
    )


def _get_agent_crypto_key(agent_id: str) -> Optional[str]:
    row = execute_query_one(
        "SELECT config_value FROM system_config WHERE config_key = :k",
        {"k": f"agent_crypto_key:{agent_id}"},
    )
    return row["config_value"] if row else None


def _store_agent_crypto_key_version(agent_id: str, version: int) -> None:
    execute(
        "MERGE INTO SYSTEM_CONFIG t "
        "USING (SELECT :k AS CONFIG_KEY, TO_CHAR(:v) AS CONFIG_VALUE FROM DUAL) s "
        "ON (t.CONFIG_KEY = s.CONFIG_KEY) "
        "WHEN MATCHED THEN UPDATE SET t.CONFIG_VALUE = s.CONFIG_VALUE "
        "WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) "
        "VALUES (s.CONFIG_KEY, s.CONFIG_VALUE, :d)",
        {"k": f"agent_crypto_key_version:{agent_id}", "v": version, "d": f"Crypto key version for {agent_id}"},
    )


def get_agent_crypto_key_version(agent_id: str) -> int:
    row = execute_query_one(
        "SELECT config_value FROM system_config WHERE config_key = :k",
        {"k": f"agent_crypto_key_version:{agent_id}"},
    )
    try:
        return int(row["config_value"]) if row else 0
    except (ValueError, TypeError):
        return 0


def rotate_agent_crypto_key(agent_id: str) -> Optional[Dict[str, Any]]:
    from .connection_crypto import generate_agent_crypto_key
    new_key = generate_agent_crypto_key()
    current_version = get_agent_crypto_key_version(agent_id)
    new_version = current_version + 1

    _store_agent_crypto_key(agent_id, new_key)
    _store_agent_crypto_key_version(agent_id, new_version)

    logger.info("Rotated crypto key for agent %s to version %d", agent_id, new_version)
    return {"agent_id": agent_id, "key_version": new_version}


def rotate_all_crypto_keys() -> List[Dict[str, Any]]:
    agents = execute_query(
        "SELECT DISTINCT agent_id FROM agent_registry WHERE status != 'DELETED'",
        {},
    )
    results = []
    for row in agents:
        result = rotate_agent_crypto_key(row["agent_id"])
        if result:
            results.append(result)
    logger.info("Rotated crypto keys for %d agents", len(results))
    return results
