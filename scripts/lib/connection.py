"""AI Agent Infra v3.7.4 - Community Edition - Database Connection Pool Manager

Unified oracledb connection pool with bind-variable support.
Replaces all SQLcl subprocess calls with direct oracledb access.
Includes Deep Data Security context management.
Supports Admin/Agent separation modes (standalone, admin, agent).
"""

import json
import oracledb
import threading
import logging
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_config, DatabaseConfig, AgentModeConfig

_logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

oracledb.defaults.fetch_lobs = False

_pool: Optional[oracledb.ConnectionPool] = None
_lock = threading.Lock()


def _init_pool(cfg: DatabaseConfig) -> oracledb.ConnectionPool:
    return oracledb.create_pool(
        user=cfg.user,
        password=cfg.password,
        dsn=cfg.dsn,
        min=cfg.pool_min,
        max=cfg.pool_max,
        increment=cfg.pool_increment,
        getmode=oracledb.SPOOL_ATTRVAL_NOWAIT,
    )


def get_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                cfg = get_config()
                if cfg.agent.mode == "agent":
                    raise RuntimeError("Schema owner pool not available in agent mode")
                db_cfg = cfg.database
                logger.info("Initializing connection pool: %s@%s (min=%d, max=%d)",
                            db_cfg.user, db_cfg.dsn, db_cfg.pool_min, db_cfg.pool_max)
                _pool = _init_pool(db_cfg)
    return _pool


@contextmanager
def get_connection():
    pool = get_pool()
    conn = pool.acquire()
    try:
        apply_agent_context(conn)
        yield conn
    finally:
        clear_agent_context(conn)
        pool.release(conn)


_current_agent_id = threading.local()

_end_user_connections: Dict[str, oracledb.Connection] = {}
_end_user_lock = threading.Lock()

_agent_eu_creds: Optional[Dict[str, str]] = None
_agent_eu_lock = threading.Lock()


def _load_agent_eu_creds() -> Dict[str, str]:
    global _agent_eu_creds
    with _agent_eu_lock:
        if _agent_eu_creds is not None:
            return _agent_eu_creds
        cfg = get_config()
        config_path = cfg.project_root / "agent_config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"agent_config.json not found at {config_path}")
        from .connection_crypto import load_agent_config
        creds = load_agent_config(config_path)
        _agent_eu_creds = creds
        return _agent_eu_creds


def set_agent_context(agent_id: Optional[str]) -> None:
    _current_agent_id.value = agent_id

def get_current_agent_id() -> Optional[str]:
    return getattr(_current_agent_id, 'value', None)

def _agent_id_to_end_user_name(agent_id: str) -> str:
    return agent_id.replace('-', '_').upper()

def _get_end_user_password(agent_id: str) -> Optional[str]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM system_config WHERE config_key = :key",
                    {"key": f"end_user_pwd.{agent_id}"},
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None

def get_end_user_connection(agent_id: str) -> Optional[oracledb.Connection]:
    cfg = get_config()
    if cfg.agent.mode == "agent":
        return _get_agent_mode_end_user_connection(agent_id)

    with _end_user_lock:
        existing = _end_user_connections.get(agent_id)
        if existing:
            try:
                with existing.cursor() as cur:
                    cur.execute("SELECT 1 FROM DUAL")
                return existing
            except Exception:
                try:
                    existing.close()
                except Exception:
                    pass
                _end_user_connections.pop(agent_id, None)

        pwd = _get_end_user_password(agent_id)
        if not pwd:
            _logger.debug("No end user password for %s, falling back to pool", agent_id)
            return None

        eu_name = _agent_id_to_end_user_name(agent_id)
        db_cfg = cfg.database
        try:
            conn = oracledb.connect(
                user=eu_name,
                password=pwd,
                dsn=db_cfg.dsn,
            )
            with conn.cursor() as cur:
                cur.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {cfg.database.user}")
            _end_user_connections[agent_id] = conn
            _logger.info("Created Deep Sec End User connection for %s (EU: %s)", agent_id, eu_name)
            return conn
        except oracledb.Error as e:
            _logger.debug("End User connection failed for %s (EU: %s): %s", agent_id, eu_name, e)
            return None


def _get_agent_mode_end_user_connection(agent_id: str) -> Optional[oracledb.Connection]:
    with _end_user_lock:
        existing = _end_user_connections.get(agent_id)
        if existing:
            try:
                with existing.cursor() as cur:
                    cur.execute("SELECT 1 FROM DUAL")
                return existing
            except Exception:
                try:
                    existing.close()
                except Exception:
                    pass
                _end_user_connections.pop(agent_id, None)

    try:
        creds = _load_agent_eu_creds()
        conn = oracledb.connect(
            user=creds["username"],
            password=creds["password"],
            dsn=creds["dsn"],
        )
        with conn.cursor() as cur:
            cur.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {cfg.database.user}")
        with _end_user_lock:
            _end_user_connections[agent_id] = conn
        _logger.info("Created Agent-mode End User connection for %s (EU: %s)", agent_id, creds["username"])
        return conn
    except Exception as e:
        _logger.error("Agent-mode End User connection failed for %s: %s", agent_id, e)
        return None


def close_end_user_connections():
    with _end_user_lock:
        for agent_id, conn in _end_user_connections.items():
            try:
                conn.close()
            except Exception:
                pass
        _end_user_connections.clear()

@contextmanager
def get_connection_for_agent(agent_id: Optional[str] = None):
    aid = agent_id or get_current_agent_id()
    if aid:
        eu_conn = get_end_user_connection(aid)
        if eu_conn:
            try:
                yield eu_conn
            finally:
                pass
            return
    cfg = get_config()
    if cfg.agent.mode == "agent":
        creds = _load_agent_eu_creds()
        eu_conn = get_end_user_connection(creds.get("agent_id") or aid or "agent")
        if eu_conn:
            try:
                yield eu_conn
            finally:
                pass
            return
        raise RuntimeError("No End User connection available in agent mode")
    with get_connection() as conn:
        yield conn

def apply_agent_context(conn: oracledb.Connection, agent_id: Optional[str] = None) -> None:
    aid = agent_id or get_current_agent_id()
    if aid:
        try:
            with conn.cursor() as cur:
                cur.execute(f"BEGIN {get_config().database.user}.SET_AGENT_CONTEXT.set_agent_id(:aid); END;", {"aid": aid})
        except oracledb.Error as e:
            _logger.debug("SET_AGENT_CONTEXT.set_agent_id failed (Deep Sec not deployed?): %s", e)

def clear_agent_context(conn: oracledb.Connection) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(f"BEGIN {get_config().database.user}.SET_AGENT_CONTEXT.clear_context(); END;")
    except oracledb.Error as e:
        _logger.debug("SET_AGENT_CONTEXT.clear_context failed (Deep Sec not deployed?): %s", e)

def close_pool():
    global _pool
    close_end_user_connections()
    if _pool is not None:
        with _lock:
            if _pool is not None:
                _pool.close()
                _pool = None


def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            conn.commit()
            return cur.rowcount


def execute_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [col[0].lower() for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rows = execute_query(sql, params)
    return rows[0] if rows else None


def execute_insert(sql: str, params: Optional[Dict[str, Any]] = None) -> str:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            conn.commit()
            return "ok"


def execute_insert_returning_id(sql: str, params: Optional[Dict[str, Any]] = None,
                                 id_column: str = "ENTITY_ID") -> str:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            new_id = cur.var(oracledb.STRING)
            params_with_return = dict(params or {})
            params_with_return["ret_id"] = new_id
            cur.execute(sql, params_with_return)
            conn.commit()
            val = new_id.getvalue()
            return val[0] if isinstance(val, list) else val


def execute_many(sql: str, params_list: List[Dict[str, Any]]) -> int:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            total = 0
            for params in params_list:
                cur.execute(sql, params)
                total += cur.rowcount
            conn.commit()
            return total


def execute_plsql(plsql: str, params: Optional[Dict[str, Any]] = None) -> Any:
    with get_connection_for_agent() as conn:
        with conn.cursor() as cur:
            cur.execute(plsql, params or {})
            conn.commit()
            if cur.description:
                columns = [col[0].lower() for col in cur.description]
                rows = cur.fetchall()
                if len(rows) == 1 and len(columns) == 1:
                    return rows[0][0]
                return [dict(zip(columns, row)) for row in rows]
            return None


def _sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_json(i) for i in obj]
    elif isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def sanitize_row(d):
    if not isinstance(d, dict):
        return d
    result = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _sanitize_json(v)
        elif isinstance(v, list):
            result[k] = [_sanitize_json(i) for i in v]
        else:
            result[k] = v
    return result
