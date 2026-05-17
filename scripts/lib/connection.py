"""Oracle Memory System v2.0.0 - Database Connection Pool Manager

Unified oracledb connection pool with bind-variable support.
Replaces all SQLcl subprocess calls with direct oracledb access.
"""

import oracledb
import threading
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from .config import get_config, DatabaseConfig

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
                cfg = get_config().database
                logger.info("Initializing connection pool: %s@%s (min=%d, max=%d)",
                            cfg.user, cfg.dsn, cfg.pool_min, cfg.pool_max)
                _pool = _init_pool(cfg)
    return _pool


@contextmanager
def get_connection():
    pool = get_pool()
    conn = pool.acquire()
    try:
        yield conn
    finally:
        pool.release(conn)


def close_pool():
    global _pool
    if _pool is not None:
        with _lock:
            if _pool is not None:
                _pool.close()
                _pool = None


def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            conn.commit()
            return cur.rowcount


def execute_query(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [col[0].lower() for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    rows = execute_query(sql, params)
    return rows[0] if rows else None


def execute_insert(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            cur.execute("SELECT :seq.CURRVAL FROM DUAL", {"seq": None})
            conn.commit()
            return cur.fetchone()[0]


def execute_insert_returning_id(sql: str, params: Optional[Dict[str, Any]] = None,
                                 id_column: str = "ENTITY_ID") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            new_id = cur.var(oracledb.NUMBER)
            params_with_return = dict(params or {})
            params_with_return["ret_id"] = new_id
            cur.execute(sql, params_with_return)
            conn.commit()
            val = new_id.getvalue()
            return int(val[0]) if isinstance(val, list) else int(val)


def execute_many(sql: str, params_list: List[Dict[str, Any]]) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            total = 0
            for params in params_list:
                cur.execute(sql, params)
                total += cur.rowcount
            conn.commit()
            return total


def execute_plsql(plsql: str, params: Optional[Dict[str, Any]] = None) -> Any:
    with get_connection() as conn:
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
