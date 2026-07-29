"""Static contracts for the v4.3 governance surface.

These checks deliberately do not claim a live database or browser result.  They
protect the source-to-migration-to-route boundary before those environments
are exercised by the release validators.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODE = not (ROOT / "shared").is_dir()
SOURCE_ROOT = ROOT / "shared" if not PACKAGE_MODE else ROOT / "scripts"


def _database_key() -> str | None:
    if not PACKAGE_MODE:
        return None
    import json
    try:
        return str(json.loads((ROOT / "build-manifest.json").read_text(encoding="ascii"))["database"]["key"])
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _migration_path(database: str) -> Path:
    source_path = ROOT / "adapters" / database / "deploy" / "17_v4_3_0_governance_lifecycle.sql"
    if source_path.is_file():
        return source_path
    return SOURCE_ROOT / "deploy" / "17_v4_3_0_governance_lifecycle.sql"


def _route_paths() -> set[str]:
    tree = ast.parse((SOURCE_ROOT / "web_app.py").read_text(encoding="utf-8"))
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                value = decorator.args[0].value
                if isinstance(value, str) and value.startswith("/api/"):
                    paths.add(value)
    return paths


def test_channel_thread_governance_routes_are_exposed():
    routes = _route_paths()
    assert "/api/channels/{channel_id}/summary" in routes
    assert "/api/channels/{channel_id}/threads" in routes
    assert "/api/notifications" in routes
    source = (SOURCE_ROOT / "web_app.py").read_text(encoding="utf-8")
    assert "create_channel_thread" in source
    assert "notifications.manage" in source


def test_thread_service_keeps_parent_channel_and_direct_agent_boundary():
    source = (SOURCE_ROOT / "lib" / "identity_api.py").read_text(encoding="utf-8")
    assert "Agent-to-Agent Direct threads are disabled by policy" in source
    assert "THREAD_ID, CHANNEL_ID, THREAD_TYPE, STATUS" in source
    assert "child thread classification cannot broaden its parent" in source
    assert "a non-Channel message requires a thread id" in source


def test_all_database_lifecycle_migrations_are_additive_and_retryable():
    expected = (
        "LIFECYCLE_REASON", "DELETION_AFTER", "QUARANTINED_AT", "APPROVAL_REASON",
        "POLICY_VERSION", "IDEMPOTENCY_KEY", "NOTIFICATION_LEVEL", "ACKNOWLEDGED_BY",
        "ESCALATED_AT", "RETRY_COUNT", "MAX_RETRIES", "LAST_RECOVERY_ACTION",
        "RECOVERY_REASON", "CX_CHANNEL_THREADS", "CX_RUNTIME_PROFILE_CHANGES",
    )
    databases = ("oracle", "pg", "yashandb") if not PACKAGE_MODE else (_database_key(),)
    for database in databases:
        assert database
        path = _migration_path(database)
        text = path.read_text(encoding="utf-8").upper()
        for token in expected:
            assert token in text, f"{database}: missing {token}"
        if database == "pg":
            assert "ADD COLUMN IF NOT EXISTS" in text
        else:
            assert "EXECUTE IMMEDIATE" in text


def test_oracle_and_yashan_role_sync_is_conditional_and_dialect_aware():
    if PACKAGE_MODE and _database_key() not in {"oracle", "yashandb"}:
        return
    oracle = _migration_path("oracle").read_text(encoding="utf-8").upper()
    yashan = _migration_path("yashandb").read_text(encoding="utf-8").upper()
    sources = (oracle, yashan) if not PACKAGE_MODE else (
        oracle if _database_key() == "oracle" else yashan,
    )

    for source in sources:
        assert "SELECT DISPLAY_NAME, PERMISSIONS_JSON, DATA_SCOPES_JSON, MANAGED" in source
        assert "FOR UPDATE" in source
        assert "IF L_MANAGED = 'Y'" in source
        assert "VERSION = NVL(VERSION, 1) + 1" in source
        assert "SAME_CLOB(L_PERMISSIONS, P_PERMISSIONS) = 0" in source
        assert "SAME_CLOB(L_SCOPES, P_SCOPES) = 0" in source
        assert "WHEN MATCHED THEN UPDATE SET" not in source

    if not PACKAGE_MODE or _database_key() == "oracle":
        assert "DBMS_LOB.COMPARE" in oracle
    if not PACKAGE_MODE or _database_key() == "yashandb":
        assert "DBMS_LOB.COMPARE" not in yashan
        assert "DBMS_LOB.SUBSTR(P_LEFT, 4000, L_OFFSET)" in yashan
        assert "YASHANDB" in yashan


def test_oracle_and_yashan_17_migrations_absorb_only_known_duplicate_errors():
    if PACKAGE_MODE and _database_key() not in {"oracle", "yashandb"}:
        return
    oracle = _migration_path("oracle").read_text(encoding="utf-8").upper()
    yashan = _migration_path("yashandb").read_text(encoding="utf-8").upper()

    sources = (oracle, yashan) if not PACKAGE_MODE else (
        oracle if _database_key() == "oracle" else yashan,
    )
    for source in sources:
        assert "SQLCODE NOT IN (-955, -1408)" not in source
    if not PACKAGE_MODE or _database_key() == "oracle":
        assert "SQLCODE <> -955" in oracle
    if not PACKAGE_MODE or _database_key() == "yashandb":
        assert "ABS(SQLCODE) NOT IN (1430, 2013, 2176)" in yashan
        assert "ABS(SQLCODE) NOT IN (955, 4207, 2043)" in yashan
        assert "ABS(SQLCODE) NOT IN (955, 4207)" in yashan
        assert yashan.count("ABS(SQLCODE) NOT IN (1430, 2013, 2176)") == 14
        assert yashan.count("ABS(SQLCODE) NOT IN (955, 4207) THEN") == 3


def test_build_keeps_v43_migration_in_graph_boundary():
    source_path = ROOT / "build.py"
    source = source_path.read_text(encoding="utf-8") if source_path.is_file() else (ROOT / "build-manifest.json").read_text(encoding="ascii")
    assert "17_v4_3_0_" in source
