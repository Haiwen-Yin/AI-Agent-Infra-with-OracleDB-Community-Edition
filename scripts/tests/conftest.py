"""AI Agent Infra v4.1.0 - Pytest Configuration and Shared Fixtures

Provides parameterized database fixtures so the same test suite can run
against Oracle, PostgreSQL, and YashanDB backends without duplication.

Fixtures:
    db_type        - parameterized string ("oracle" | "pg" | "yashandb")
    db_connection  - yields a live connection object for the current db_type
                     (skips the test automatically if the backend is unreachable)

Environment overrides:
    AIAGENT_TEST_DB   - restrict parameterization to a single backend
    AIAGENT_SKIP_DB   - comma-separated list of backends to skip
    AIAGENT_ORACLE_DSN, AIAGENT_PG_DSN, AIAGENT_YASHANDB_DSN - override DSN
    AIAGENT_ORACLE_USER / AIAGENT_ORACLE_PASSWORD (and *_PG_*, *_YASHANDB_*)
"""

import os
import base64
import json
import socket
import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection parameters per backend. Defaults mirror editions/*.json but can
# be overridden via environment variables for CI / local dev environments.
# ---------------------------------------------------------------------------
DB_CONFIGS: Dict[str, Dict[str, Any]] = {
    "oracle": {
        "driver": "oracledb",
        "module_name": "oracledb",
        "user": os.environ.get("AIAGENT_ORACLE_USER", "aiadmin"),
        "password": os.environ.get("AIAGENT_ORACLE_PASSWORD", ""),
        "dsn": os.environ.get("AIAGENT_ORACLE_DSN", ""),
        "pool_min": 1,
        "pool_max": 2,
        "select_dummy": "SELECT 1 AS val",
    },
    "pg": {
        "driver": "psycopg2",
        "module_name": "psycopg2",
        "user": os.environ.get("AIAGENT_PG_USER", "pgsql"),
        "password": os.environ.get("AIAGENT_PG_PASSWORD", ""),
        "host": os.environ.get("AIAGENT_PG_HOST", ""),
        "port": int(os.environ.get("AIAGENT_PG_PORT", "5432")),
        "dbname": os.environ.get("AIAGENT_PG_DBNAME", "ai_agent"),
        "pool_min": 1,
        "pool_max": 2,
        "select_dummy": "SELECT 1 AS val",
    },
    "yashandb": {
        "driver": "yaspy",
        "module_name": "yaspy",
        "user": os.environ.get("AIAGENT_YASHANDB_USER", "aiadmin"),
        "password": os.environ.get("AIAGENT_YASHANDB_PASSWORD", ""),
        "dsn": os.environ.get("AIAGENT_YASHANDB_DSN", ""),
        "pool_min": 1,
        "pool_max": 2,
        "select_dummy": "SELECT 1 AS val",
    },
}


def _apply_config_file(name: str) -> None:
    path_value = os.environ.get(f"AIAGENT_{name.upper()}_CONFIG")
    if not path_value:
        return
    section = dict(
        json.loads(Path(path_value).read_text(encoding="utf-8")).get("database") or {}
    )
    encrypted = section.pop("_encrypted", None)
    section.pop("_key_source", None)
    if encrypted:
        from lib.connection_crypto import decrypt_section
        key = base64.b64decode(
            (Path.home() / ".oracle-infra" / "master.key").read_text(encoding="ascii").strip()
        )
        section.update(decrypt_section(encrypted, key))
    DB_CONFIGS[name].update(section)


for _database_name in DB_CONFIGS:
    _apply_config_file(_database_name)


def _active_backends() -> List[str]:
    """Compute the list of backends to parameterize, honoring env overrides."""
    all_backends = list(DB_CONFIGS.keys())
    forced = os.environ.get("AIAGENT_TEST_DB")
    if forced:
        if forced not in DB_CONFIGS:
            raise ValueError(
                f"AIAGENT_TEST_DB={forced!r} is not one of {list(DB_CONFIGS)}"
            )
        return [forced]
    skipped = {
        s.strip().lower()
        for s in os.environ.get("AIAGENT_SKIP_DB", "").split(",")
        if s.strip()
    }
    return [b for b in all_backends if b.lower() not in skipped]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(params=_active_backends())
def db_type(request) -> str:
    """Parameterized backend name: 'oracle', 'pg', or 'yashandb'."""
    return request.param


@pytest.fixture(scope="session")
def _db_reachable() -> Dict[str, bool]:
    """Session cache of which backends are reachable (driver import + host:port)."""
    cache: Dict[str, bool] = {}

    def _check(name: str) -> bool:
        if name in cache:
            return cache[name]
        cfg = DB_CONFIGS[name]
        ok = True
        # 1. driver importable
        try:
            importlib.import_module(cfg["module_name"])
        except Exception as e:  # pragma: no cover - environment dependent
            logger.warning("backend %s driver %s not importable: %s", name, cfg["module_name"], e)
            ok = False

        # 2. host/port reachable
        if ok:
            host = cfg.get("host")
            port = cfg.get("port")
            if not host:
                # parse host/port out of DSN (host:port/service)
                dsn = cfg.get("dsn", "")
                if ":" in dsn and "/" in dsn:
                    hp = dsn.split("/", 1)[0]
                    if ":" in hp:
                        host, port_s = hp.split(":", 1)
                        try:
                            port = int(port_s)
                        except ValueError:
                            port = None
            if not host or not port:
                ok = False
            if host and port:
                try:
                    with socket.create_connection((host, port), timeout=3):
                        pass
                except OSError as e:  # pragma: no cover - environment dependent
                    logger.warning("backend %s unreachable at %s:%s: %s", name, host, port, e)
                    ok = False
        cache[name] = ok
        return ok

    return {"check": _check}


def _open_connection(name: str) -> Any:
    """Open a raw DB-API connection for the given backend."""
    cfg = DB_CONFIGS[name]
    if name == "oracle":
        import oracledb
        return oracledb.connect(user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"])
    if name == "pg":
        import psycopg2
        return psycopg2.connect(
            user=cfg["user"], password=cfg["password"],
            host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"],
        )
    if name == "yashandb":
        import yaspy
        return yaspy.connect(user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"])
    raise ValueError(f"unknown backend: {name}")


@pytest.fixture
def db_connection(db_type: str, _db_reachable):
    """Yield a live DB-API connection for the current db_type.

    Automatically skips the test if the backend is unreachable
    (driver missing or host/port refused).
    """
    if not _db_reachable["check"](db_type):
        pytest.skip(f"backend {db_type!r} not reachable in this environment")
    conn = _open_connection(db_type)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


# ---------------------------------------------------------------------------
# Pytest collection hooks
# ---------------------------------------------------------------------------
def pytest_report_header(config) -> List[str]:
    """Add backend info to the pytest header."""
    lines = [
        "AI Agent Infra v4.1.0 - parameterized DB fixtures",
        f"  Active backends: {_active_backends()}",
    ]
    forced = os.environ.get("AIAGENT_TEST_DB")
    if forced:
        lines.append(f"  (forced via AIAGENT_TEST_DB={forced})")
    return lines


def pytest_configure(config):
    """Register markers used by the parameterized suite."""
    config.addinivalue_line(
        "markers",
        "oracle: test runs against the Oracle backend",
    )
    config.addinivalue_line(
        "markers",
        "pg: test runs against the PostgreSQL backend",
    )
    config.addinivalue_line(
        "markers",
        "yashandb: test runs against the YashanDB backend",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-apply per-backend markers based on the db_type fixture parameter."""
    for item in items:
        backend_params = [
            p for p in item.iter_markers(name="db_type")
            if p.args
        ]
        # db_type is a fixture, so inspect callspec params instead
        callspec_backend = getattr(item, "callspec", None)
        if callspec_backend is not None:
            for param_name, param_val in callspec_backend.params.items():
                if (
                    param_name == "db_type"
                    and isinstance(param_val, str)
                    and param_val in DB_CONFIGS
                ):
                    marker = getattr(pytest.mark, param_val, None)
                    if marker is not None:
                        item.add_marker(marker)
