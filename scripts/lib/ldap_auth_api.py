"""AI Agent Infra v4.0.0 - Enterprise Edition - LDAP Authentication API"""

import json
import logging
import ssl as ssl_module
from typing import Any, Dict, List, Optional

from .connection import execute, execute_query, execute_query_one, execute_insert_returning_id
from .config import get_config

logger = logging.getLogger(__name__)

try:
    import ldap3
    _LDAP3_AVAILABLE = True
except ImportError:
    _LDAP3_AVAILABLE = False
    logger.error("ldap3 package is required for LDAP authentication but is not installed")


def _get_active_config(config_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if config_id:
        sql = """
            SELECT CONFIG_ID, SERVER_URL, BASE_DN, BIND_DN, BIND_CREDENTIAL,
                   USER_FILTER, GROUP_FILTER, USE_TLS, TLS_VALIDATE,
                   SYNC_INTERVAL_MIN, GROUP_ROLE_MAPPING, STATUS,
                   TO_CHAR(LAST_SYNC_AT, 'YYYY-MM-DD HH24:MI:SS') AS LAST_SYNC_AT,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM LDAP_CONFIG
            WHERE CONFIG_ID = :cid AND STATUS = 'ACTIVE'
        """
        row = execute_query_one(sql, {"cid": config_id})
    else:
        sql = """
            SELECT CONFIG_ID, SERVER_URL, BASE_DN, BIND_DN, BIND_CREDENTIAL,
                   USER_FILTER, GROUP_FILTER, USE_TLS, TLS_VALIDATE,
                   SYNC_INTERVAL_MIN, GROUP_ROLE_MAPPING, STATUS,
                   TO_CHAR(LAST_SYNC_AT, 'YYYY-MM-DD HH24:MI:SS') AS LAST_SYNC_AT,
                   TO_CHAR(CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS CREATED_AT,
                   TO_CHAR(UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') AS UPDATED_AT
            FROM LDAP_CONFIG
            WHERE STATUS = 'ACTIVE'
            ORDER BY CREATED_AT DESC
            FETCH FIRST 1 ROWS ONLY
        """
        row = execute_query_one(sql)
    if row and row.get('bind_credential'):
        try:
            result = execute_query_one("SELECT DB_CRYPTO.decrypt(:cipher) AS plaintext FROM DUAL", {"cipher": row['bind_credential']})
            if result and result.get('plaintext'):
                row['bind_credential'] = result['plaintext']
        except Exception:
            pass
    return row


def _resolve_server_url(server_url: str, use_tls: str) -> str:
    if use_tls == 'Y' and server_url.lower().startswith("ldap://"):
        return "ldaps://" + server_url[7:]
    return server_url


def _build_ldap_server(config: Dict[str, Any]) -> Any:
    server_url = _resolve_server_url(config["server_url"], config.get("use_tls", "N"))
    use_tls = config.get("use_tls", "N")
    tls_validate = config.get("tls_validate", "Y")
    if use_tls == 'Y':
        validate = ssl_module.CERT_REQUIRED if tls_validate == 'Y' else ssl_module.CERT_NONE
        tls = ldap3.Tls(validate=validate)
        return ldap3.Server(server_url, use_ssl=True, tls=tls, get_info=ldap3.ALL)
    return ldap3.Server(server_url, get_info=ldap3.ALL)


def _parse_json_field(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def configure_ldap(
    server_url: str,
    base_dn: str,
    bind_dn: str,
    bind_credential: str,
    user_filter: str = "(uid={username})",
    group_filter: str = "(memberUid={username})",
    use_tls: str = "Y",
    tls_validate: str = "Y",
    sync_interval_min: int = 60,
    group_role_mapping: Optional[Any] = None,
) -> str:
    config_id_sql = "'LC_' || RAWTOHEX(SYS_GUID())"
    grm_val = json.dumps(group_role_mapping) if isinstance(group_role_mapping, (dict, list)) else group_role_mapping
    encrypted_cred_result = execute_query_one("SELECT DB_CRYPTO.encrypt(:plain) AS ciphertext FROM DUAL", {"plain": bind_credential})
    encrypted_cred = encrypted_cred_result['ciphertext'] if encrypted_cred_result else bind_credential
    sql = f"""
        INSERT INTO LDAP_CONFIG (CONFIG_ID, SERVER_URL, BASE_DN, BIND_DN, BIND_CREDENTIAL,
                                  USER_FILTER, GROUP_FILTER, USE_TLS, TLS_VALIDATE,
                                  SYNC_INTERVAL_MIN, GROUP_ROLE_MAPPING, STATUS,
                                  CREATED_AT, UPDATED_AT)
        VALUES ({config_id_sql}, :server_url, :base_dn, :bind_dn, :bind_cred,
                :user_filter, :group_filter, :use_tls, :tls_validate,
                :sync_interval, :group_role_map, 'ACTIVE',
                SYSTIMESTAMP, SYSTIMESTAMP)
        RETURNING CONFIG_ID INTO :ret_id
    """
    return execute_insert_returning_id(sql, {
        "server_url": server_url,
        "base_dn": base_dn,
        "bind_dn": bind_dn,
        "bind_cred": encrypted_cred,
        "user_filter": user_filter,
        "group_filter": group_filter,
        "use_tls": use_tls,
        "tls_validate": tls_validate,
        "sync_interval": sync_interval_min,
        "group_role_map": grm_val,
    }, id_column="CONFIG_ID")


def test_ldap_connection(config_id: Optional[str] = None) -> Dict[str, Any]:
    if not _LDAP3_AVAILABLE:
        return {"success": False, "error": "ldap3 package is not installed"}
    config = _get_active_config(config_id)
    if not config:
        return {"success": False, "error": "No active LDAP configuration found"}
    try:
        server = _build_ldap_server(config)
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_credential"],
                                auto_bind=True, raise_exceptions=True)
        result = {
            "success": True,
            "server_info": {
                "host": server.host,
                "port": server.port,
                "ssl": server.ssl,
            },
        }
        if server.info:
            result["naming_contexts"] = server.info.naming_contexts if server.info.naming_contexts else []
            result["supported_controls"] = server.info.supported_controls if server.info.supported_controls else []
        conn.unbind()
        return result
    except Exception as e:
        logger.error("LDAP connection test failed: %s", e)
        return {"success": False, "error": str(e)}


def authenticate_via_ldap(username: str, password: str) -> Optional[Dict[str, Any]]:
    if not _LDAP3_AVAILABLE:
        logger.error("ldap3 package is not installed")
        return None
    config = _get_active_config()
    if not config:
        logger.error("No active LDAP configuration found")
        return None
    try:
        server = _build_ldap_server(config)
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_credential"],
                                auto_bind=True, raise_exceptions=True)
        user_filter = config["user_filter"].replace("{username}", username)
        conn.search(config["base_dn"], user_filter, search_scope=ldap3.SUBTREE,
                    attributes=["cn", "mail", "uid"])
        if not conn.entries:
            conn.unbind()
            return None
        user_entry = conn.entries[0]
        user_dn = user_entry.entry_dn
        conn.unbind()
        bind_conn = ldap3.Connection(server, user=user_dn, password=password,
                                     auto_bind=True, raise_exceptions=True)
        bind_conn.unbind()
        user_info = {"dn": user_dn, "username": username}
        if hasattr(user_entry, "cn") and user_entry.cn.value:
            user_info["cn"] = user_entry.cn.value
        if hasattr(user_entry, "mail") and user_entry.mail.value:
            user_info["mail"] = user_entry.mail.value
        if hasattr(user_entry, "uid") and user_entry.uid.value:
            user_info["uid"] = user_entry.uid.value
        if hasattr(user_entry, "memberOf") and user_entry.memberOf.value:
            user_info["groups"] = user_entry.memberOf.values if hasattr(user_entry.memberOf, "values") else [user_entry.memberOf.value]
        else:
            user_info["groups"] = []
        return user_info
    except Exception as e:
        logger.error("LDAP authentication failed for user %s: %s", username, e)
        return None


def sync_ldap_users(config_id: Optional[str] = None, sync_type: str = "INCREMENTAL") -> Dict[str, Any]:
    if not _LDAP3_AVAILABLE:
        return {"success": False, "error": "ldap3 package is not installed", "synced": 0, "updated": 0, "errors": 0}
    config = _get_active_config(config_id)
    if not config:
        return {"success": False, "error": "No active LDAP configuration found", "synced": 0, "updated": 0, "errors": 0}
    log_id_sql = "'LSL_' || RAWTOHEX(SYS_GUID())"
    log_sql = f"""
        INSERT INTO LDAP_SYNC_LOG (LOG_ID, SYNC_TYPE, STATUS, USERS_SYNCED, GROUPS_SYNCED, SYNC_TIME)
        VALUES ({log_id_sql}, :sync_type, 'SUCCESS', 0, 0, SYSTIMESTAMP)
        RETURNING LOG_ID INTO :ret_id
    """
    log_id = execute_insert_returning_id(log_sql, {
        "sync_type": sync_type,
    }, id_column="LOG_ID")
    synced = 0
    updated = 0
    errors = 0
    try:
        server = _build_ldap_server(config)
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_credential"],
                                auto_bind=True, raise_exceptions=True)
        user_filter = config["user_filter"].replace("{username}", "*")
        user_filter = user_filter.replace("(uid=*)", "(objectClass=person)") if user_filter == "(uid=*)" else user_filter
        search_filter = "(objectClass=person)" if "*" in user_filter else user_filter
        if sync_type == "INCREMENTAL":
            last_sync = config.get("last_sync_at")
            if last_sync:
                search_filter = f"(&{search_filter}(modifyTimestamp>={last_sync.replace('-', '').replace(':', '').replace(' ', '')}Z))"
        conn.search(config["base_dn"], search_filter, search_scope=ldap3.SUBTREE,
                    attributes=["cn", "mail", "uid"])
        for entry in conn.entries:
            try:
                user_dn = entry.entry_dn
                uid = entry.uid.value if hasattr(entry, "uid") and entry.uid.value else None
                cn = entry.cn.value if hasattr(entry, "cn") and entry.cn.value else None
                mail = entry.mail.value if hasattr(entry, "mail") and entry.mail.value else None
                if not uid:
                    errors += 1
                    continue
                user_id = f"ldap_{uid}"
                existing = execute_query_one(
                    "SELECT USER_ID FROM SYSTEM_USERS WHERE USER_ID = :v_uid",
                    {"v_uid": user_id},
                )
                if existing:
                    execute("""
                        UPDATE SYSTEM_USERS
                        SET LDAP_DN = :v_ldap_dn, UPDATED_AT = SYSTIMESTAMP
                        WHERE USER_ID = :v_uid2
                    """, {
                        "v_uid2": user_id,
                        "v_ldap_dn": user_dn,
                    })
                    updated += 1
                else:
                    execute("""
                        INSERT INTO SYSTEM_USERS (USER_ID, USERNAME, PASSWORD_HASH, ROLE, AUTH_SOURCE,
                                                   LDAP_DN, STATUS, CREATED_AT, UPDATED_AT)
                        VALUES (:v_uid, :v_username, 'LDAP_MANAGED', 'USER', 'LDAP', :v_ldap_dn,
                                'ACTIVE', SYSTIMESTAMP, SYSTIMESTAMP)
                    """, {
                        "v_uid": user_id,
                        "v_username": uid,
                        "v_ldap_dn": user_dn,
                    })
                    synced += 1
            except Exception as e:
                logger.error("Error syncing LDAP user: %s", e)
                errors += 1
        conn.unbind()
        execute("""
            UPDATE LDAP_CONFIG SET LAST_SYNC_AT = SYSTIMESTAMP, UPDATED_AT = SYSTIMESTAMP
            WHERE CONFIG_ID = :cid
        """, {"cid": config["config_id"]})
        execute("""
            UPDATE LDAP_SYNC_LOG SET USERS_SYNCED = :synced,
                   GROUPS_SYNCED = :groups, ERROR_MESSAGE = :errors_desc
            WHERE LOG_ID = :lid
        """, {
            "lid": log_id,
            "synced": synced + updated,
            "groups": 0,
            "errors_desc": f"errors={errors}" if errors > 0 else None,
        })
        return {"success": True, "synced": synced, "updated": updated, "errors": errors, "log_id": log_id}
    except Exception as e:
        logger.error("LDAP sync failed: %s", e)
        execute("""
            UPDATE LDAP_SYNC_LOG SET STATUS = 'FAILED',
                   ERROR_MESSAGE = :msg
            WHERE LOG_ID = :lid
        """, {"lid": log_id, "msg": str(e)[:4000]})
        return {"success": False, "error": str(e), "synced": synced, "updated": updated, "errors": errors, "log_id": log_id}


def get_ldap_groups(username: str, config_id: Optional[str] = None) -> List[str]:
    if not _LDAP3_AVAILABLE:
        logger.error("ldap3 package is not installed")
        return []
    config = _get_active_config(config_id)
    if not config:
        return []
    try:
        server = _build_ldap_server(config)
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_credential"],
                                auto_bind=True, raise_exceptions=True)
        user_filter = config["user_filter"].replace("{username}", username)
        conn.search(config["base_dn"], user_filter, search_scope=ldap3.SUBTREE,
                    attributes=["dn"])
        if not conn.entries:
            conn.unbind()
            return []
        user_dn = conn.entries[0].entry_dn
        group_filter = config["group_filter"].replace("{username}", username)
        conn.search(config["base_dn"], group_filter, search_scope=ldap3.SUBTREE,
                    attributes=["cn"])
        groups = []
        for entry in conn.entries:
            if hasattr(entry, "cn") and entry.cn.value:
                groups.append(entry.cn.value)
        conn.unbind()
        return groups
    except Exception as e:
        logger.error("Failed to get LDAP groups for %s: %s", username, e)
        return []


def map_ldap_group_to_role(ldap_groups: List[str], config_id: Optional[str] = None) -> str:
    config = _get_active_config(config_id)
    if not config:
        return "VIEWER"
    group_role_mapping = _parse_json_field(config.get("group_role_mapping"))
    if not group_role_mapping or not isinstance(group_role_mapping, dict):
        return "VIEWER"
    priority_order = ["ADMIN", "POWER_USER", "USER", "VIEWER"]
    matched_roles = []
    for group in ldap_groups:
        role = group_role_mapping.get(group)
        if role:
            matched_roles.append(role)
    for role in priority_order:
        if role in matched_roles:
            return role
    if matched_roles:
        return matched_roles[0]
    return "VIEWER"


def get_ldap_user_info(username: str, config_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not _LDAP3_AVAILABLE:
        logger.error("ldap3 package is not installed")
        return None
    config = _get_active_config(config_id)
    if not config:
        return None
    try:
        server = _build_ldap_server(config)
        conn = ldap3.Connection(server, user=config["bind_dn"], password=config["bind_credential"],
                                auto_bind=True, raise_exceptions=True)
        user_filter = config["user_filter"].replace("{username}", username)
        conn.search(config["base_dn"], user_filter, search_scope=ldap3.SUBTREE,
                    attributes=["dn", "cn", "mail", "uid", "title", "department", "memberOf"])
        if not conn.entries:
            conn.unbind()
            return None
        entry = conn.entries[0]
        user_info: Dict[str, Any] = {"dn": entry.entry_dn}
        for attr in ["cn", "mail", "uid", "title", "department"]:
            if hasattr(entry, attr):
                val = getattr(entry, attr).value
                if val:
                    user_info[attr] = val
        if hasattr(entry, "memberOf") and entry.memberOf.value:
            user_info["memberOf"] = entry.memberOf.values if hasattr(entry.memberOf, "values") else [entry.memberOf.value]
        else:
            user_info["memberOf"] = []
        conn.unbind()
        return user_info
    except Exception as e:
        logger.error("Failed to get LDAP user info for %s: %s", username, e)
        return None


def schedule_ldap_sync(config_id: Optional[str] = None) -> Dict[str, Any]:
    return sync_ldap_users(config_id=config_id, sync_type="INCREMENTAL")
