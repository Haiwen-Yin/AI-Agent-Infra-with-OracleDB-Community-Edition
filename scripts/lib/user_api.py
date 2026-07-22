"""AI Agent Infra v4.0.1 - Enterprise Edition - User Management API

User registration, profile, and user-scoped content retrieval.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id

logger = logging.getLogger(__name__)


def register_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    existing = execute_query_one(
        "SELECT USER_ID FROM SYSTEM_USERS WHERE USERNAME = :v_uname",
        {"v_uname": username},
    )
    if existing:
        return None

    pw_hash = "SHA256:" + hashlib.sha256(password.encode()).hexdigest()
    user_id_sql = "'USR_' || AI_NEW_ID()"

    sql = f"""
        INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, STATUS,
                                   AUTH_SOURCE, CREATED_AT, UPDATED_AT)
        VALUES ({user_id_sql}, :v_uname, :v_pwhash, 'USER', 'ACTIVE',
                'LOCAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING USER_ID INTO :ret_id
    """
    user_id = execute_insert_returning_id(sql, {
        "v_uname": username,
        "v_pwhash": pw_hash,
    }, id_column="USER_ID")

    return {
        "user_id": user_id,
        "username": username,
        "role": "USER",
        "status": "ACTIVE",
        "auth_source": "LOCAL",
    }


def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    row = execute_query_one(
        "SELECT USER_ID, USERNAME, ROLE, STATUS, AUTH_SOURCE, CREATED_AT, UPDATED_AT FROM SYSTEM_USERS WHERE USER_ID = :v_uid",
        {"v_uid": user_id},
    )
    if not row:
        return None
    return row


def update_last_login(user_id: str) -> None:
    execute(
        "UPDATE SYSTEM_USERS SET LAST_LOGIN = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP WHERE USER_ID = :v_uid",
        {"v_uid": user_id},
    )


def get_user_memories(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT ENTITY_ID, TITLE, ENTITY_TYPE, STATUS, CREATED_AT
           FROM ENTITIES
           WHERE ENTITY_TYPE = 'MEMORY'
           ORDER BY CREATED_AT DESC FETCH FIRST :v_lim ROWS ONLY""",
        {"v_lim": limit},
    )
    return rows[:limit]


def get_user_workspaces(user_id: str) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT w.WORKSPACE_ID, w.WORKSPACE_NAME, w.WORKSPACE_TYPE, w.STATUS, w.CREATED_AT
           FROM WORKSPACES w
           WHERE w.OWNER_USER_ID = :v_uid
           ORDER BY w.CREATED_AT DESC""",
        {"v_uid": user_id},
    )
    return rows


def get_user_sessions(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = execute_query(
        """SELECT s.SESSION_ID, s.AGENT_ID, s.IS_ACTIVE, s.START_TIME, s.END_TIME,
                  a.AGENT_NAME
           FROM AGENT_SESSION s
           JOIN AGENT_REGISTRY a ON s.AGENT_ID = a.AGENT_ID
           WHERE s.OWNER_USER_ID = :v_uid
           ORDER BY s.START_TIME DESC""",
        {"v_uid": user_id},
    )
    return rows[:limit]


def register_ldap_user(username: str, ldap_dn: str) -> Optional[Dict[str, Any]]:
    existing = execute_query_one(
        "SELECT USER_ID FROM SYSTEM_USERS WHERE USERNAME = :v_uname AND AUTH_SOURCE = 'LDAP'",
        {"v_uname": username},
    )
    if existing:
        execute(
            "UPDATE SYSTEM_USERS SET LDAP_DN = :v_dn, UPDATED_AT = CURRENT_TIMESTAMP WHERE USER_ID = :v_uid",
            {"v_dn": ldap_dn, "v_uid": existing["user_id"]},
        )
        return {
            "user_id": existing["user_id"],
            "username": username,
            "role": "USER",
            "status": "ACTIVE",
            "auth_source": "LDAP",
        }
    user_id_sql = "'USR_' || AI_NEW_ID()"
    sql = f"""
        INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, STATUS,
                                   AUTH_SOURCE, LDAP_DN, CREATED_AT, UPDATED_AT)
        VALUES ({user_id_sql}, :v_uname, 'LDAP_MANAGED', 'USER', 'ACTIVE',
                'LDAP', :v_dn, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING USER_ID INTO :ret_id
    """
    user_id = execute_insert_returning_id(sql, {
        "v_uname": username,
        "v_dn": ldap_dn,
    }, id_column="USER_ID")
    return {
        "user_id": user_id,
        "username": username,
        "role": "USER",
        "status": "ACTIVE",
        "auth_source": "LDAP",
    }
