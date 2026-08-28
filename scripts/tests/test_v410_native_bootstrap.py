"""Regression contracts for the v4.4.10 no-external-Agent bootstrap path."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import migration_runner
from lib import connection, deployment_orchestrator, identity_api, native_agent_api


def _layout() -> tuple[Path, Path, bool]:
    tests_parent = Path(__file__).resolve().parents[1]
    packaged = tests_parent.name == "scripts"
    package_root = tests_parent.parent if packaged else tests_parent.parent
    return tests_parent, package_root, packaged


def _load_bootstrap_cli():
    runtime_root, _package_root, packaged = _layout()
    path = runtime_root / "bootstrap_deployment_agent.py" if packaged else runtime_root / "scripts" / "bootstrap_deployment_agent.py"
    spec = importlib.util.spec_from_file_location("cx_bootstrap_cli_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_platform_prefers_package_virtual_environment():
    runtime_root, package_root, packaged = _layout()
    installer = runtime_root / "install_platform.sh" if packaged else package_root / "shared" / "install_platform.sh"
    source = installer.read_text(encoding="utf-8")
    assert 'VENV_PYTHON="${CX_VENV_DIR:-$ROOT_DIR/.venv}/bin/python"' in source
    assert '[[ -z "${PYTHON_BIN:-}" && -x "$VENV_PYTHON" ]]' in source
    assert 'PYTHON_BIN="$VENV_PYTHON"' in source


def _packaged_database(root: Path) -> str:
    manifest = root / "build-manifest.json"
    if not manifest.is_file():
        return "oracle"
    return str(json.loads(manifest.read_text(encoding="utf-8"))["database"]["key"])


def _packaged_edition(root: Path) -> str:
    manifest = root / "build-manifest.json"
    if not manifest.is_file():
        return "source"
    return str(json.loads(manifest.read_text(encoding="utf-8"))["edition"]).lower()


def _database_deploy_script(database: str, name: str) -> Path:
    """Resolve a database-specific SQL contract in source or a matching package."""
    _runtime_root, package_root, packaged = _layout()
    if packaged:
        if _packaged_database(package_root) != database:
            pytest.skip(f"{database} package contract")
        return package_root / "scripts" / "deploy" / name
    return package_root / "adapters" / database / "deploy" / name


def test_oracle_prerequisite_script_is_bounded_and_pdb_scoped():
    runtime_root, package_root, packaged = _layout()
    if packaged and _packaged_database(package_root) != "oracle":
        pytest.skip("Oracle-only prerequisite contract")
    path = (
        runtime_root / "deploy" / "0_oracle_database_prerequisites.sql"
        if packaged
        else package_root / "adapters" / "oracle" / "deploy" / "0_oracle_database_prerequisites.sql"
    )
    sql = path.read_text(encoding="utf-8").upper()
    assert "WHENEVER SQLERROR EXIT SQL.SQLCODE" in sql
    assert "DEFINE APP_QUOTA" in sql
    assert "QUOTA &&APP_QUOTA ON &&APP_TABLESPACE" in sql
    assert "CDB$ROOT" in sql and "RAISE_APPLICATION_ERROR" in sql
    assert "NLS_CHARACTERSET" in sql
    assert "CREATE TRIGGER" in sql
    assert "CREATE ROLE DEEP_SEC_SESSION_ROLE" in sql
    assert "GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE" in sql
    assert "GRANT DEEP_SEC_SESSION_ROLE TO &&SCHEMA_OWNER WITH ADMIN OPTION" in sql
    assert "CREATE USER" not in sql
    assert "IDENTIFIED BY" not in sql
    assert "UNLIMITED TABLESPACE" not in sql
    assert "QUOTA UNLIMITED" not in sql
    assert "CREATE TRIGGER" in deployment_orchestrator.ORACLE_OWNER_BASE_PRIVILEGES


def test_baseline_declares_v410_terminal_knowledge_context():
    root = Path(__file__).resolve().parents[2]
    manifest_path = root / "build-manifest.json"
    if manifest_path.is_file():
        package = json.loads(manifest_path.read_text(encoding="utf-8"))
        databases = (str(package["database"]["key"]),)
    else:
        databases = ("oracle", "pg", "yashandb")
    for database in databases:
        baseline = deployment_orchestrator.release_baseline(database, root)
        assert baseline["version"] == "4.4.10"
        assert baseline["deployment"] == "bootstrap-deployment-agent"
        assert baseline["required_terminal_migration"] == "65_v4_4_10_external_agent_domain_context.sql"


def test_oracle_fresh_baseline_memory_migrations_do_not_require_crypto_grant():
    root = Path(__file__).resolve().parents[2]
    if (root / "adapters").is_dir():
        deploy = root / "adapters" / "oracle" / "deploy"
    elif _packaged_database(root) == "oracle":
        deploy = root / "scripts" / "deploy"
    else:
        pytest.skip("Oracle package contract")
    for name in ("23_v4_3_2_memory_lifecycle.sql", "24_v4_3_2_memory_digest_alignment.sql"):
        source = (deploy / name).read_text(encoding="utf-8").upper()
        assert "STANDARD_HASH(" in source
        assert "DBMS_CRYPTO.HASH" not in source


def test_oracle_v449_security_repair_is_schema_owner_independent():
    root = Path(__file__).resolve().parents[2]
    if (root / "adapters").is_dir():
        script = root / "adapters" / "oracle" / "deploy" / "50_v4_4_9_security_boundary_repair.sql"
    elif _packaged_database(root) == "oracle":
        script = root / "scripts" / "deploy" / "50_v4_4_9_security_boundary_repair.sql"
    else:
        pytest.skip("Oracle package contract")
    source = script.read_text(encoding="utf-8").upper()
    assert "AIADMIN." not in source
    assert "<> 'AIADMIN'" not in source
    assert "SYS_CONTEXT('USERENV', 'CURRENT_USER')" in source
    assert "CREATE OR REPLACE PACKAGE SET_AGENT_CONTEXT AS" in source
    assert source.index("CREATE OR REPLACE PACKAGE SET_AGENT_CONTEXT AS") < source.index("CREATE OR REPLACE PACKAGE BODY SET_AGENT_CONTEXT AS")
    expected_select = "SELECT ORA_END_USER_CONTEXT.USERNAME INTO V_END_USER FROM " + "DU" + "AL"
    assert expected_select in source
    assert "UPPER(V_END_USER)" in source
    assert "CREATE DATA ROLE ADMIN_DATA_ROLE" in source
    assert "SQLCODE != -52514" in source
    assert "SQLCODE NOT IN (-1917, -1927)" in source


def test_release_version_rejects_requested_package_mismatch():
    root = Path(__file__).resolve().parents[2]
    database = _packaged_database(root)
    assert deployment_orchestrator.release_version(database, root, "4.4.10") == "4.4.10"
    with pytest.raises(deployment_orchestrator.DeploymentError, match="does not match"):
        deployment_orchestrator.release_version(database, root, "4.3.7")


def test_public_release_selector_routes_v410_to_complete_chain(monkeypatch):
    expected = ["55.sql", "56.sql", "57.sql", "58.sql", "59.sql"]
    monkeypatch.setattr(migration_runner, "_v410_script_names", lambda *_args: expected)
    assert migration_runner.release_script_names("4.4.10", "oracle", Path("config.json"), "enterprise") == expected
    with pytest.raises(ValueError, match="unsupported package bootstrap version"):
        migration_runner.release_script_names("9.9.9", "oracle", Path("config.json"), "enterprise")


def test_initial_admin_password_uses_identity_argon2id_policy(monkeypatch):
    captured = {}
    def hash_password(value):
        captured["password"] = value
        return "$argon2id$test"
    monkeypatch.setattr(identity_api, "hash_password_argon2id", hash_password)
    hashed = deployment_orchestrator._bootstrap_admin_hash("Correct-Horse-Battery-2026")
    assert captured["password"] == "Correct-Horse-Battery-2026"
    assert hashed == "$argon2id$test"
    assert identity_api.verify_password_hash("placeholder_change_me", "SHA256:placeholder_change_me")[0] is False


def test_initial_admin_hash_reports_missing_runtime_dependency(monkeypatch):
    monkeypatch.setattr(
        identity_api, "hash_password_argon2id",
        lambda _value: (_ for _ in ()).throw(RuntimeError("argon2 unavailable")),
    )
    with pytest.raises(deployment_orchestrator.DeploymentError, match="hashing dependency"):
        deployment_orchestrator._bootstrap_admin_hash("Correct-Horse-Battery-2026")


def test_initial_admin_is_created_when_baseline_has_no_placeholder_seed():
    source = Path(deployment_orchestrator.__file__).read_text(encoding="utf-8")
    function = source.split("def _set_bootstrap_admin", 1)[1].split("def _bootstrap_admin_configured", 1)[0]
    assert "if not row:" in function
    assert "INSERT INTO system_users" in function
    assert "INSERT INTO SYSTEM_USERS" in function
    assert "'LOCAL'" in function


def test_noninteractive_password_file_must_be_private(tmp_path):
    cli = _load_bootstrap_cli()
    password_file = tmp_path / "admin-password"
    password_file.write_text("Correct-Horse-Battery-2026\n", encoding="utf-8")
    password_file.chmod(0o644)
    with pytest.raises(deployment_orchestrator.DeploymentError, match="0600"):
        cli._initial_admin_password("initialize", password_file)
    password_file.chmod(0o600)
    assert cli._initial_admin_password("initialize", password_file) == "Correct-Horse-Battery-2026"


def test_interactive_admin_password_masks_characters_and_handles_backspace(monkeypatch):
    cli = _load_bootstrap_cli()

    class Input:
        def __init__(self):
            self.chars = iter("CorrectX\x7f-Horse\n")

        def fileno(self):
            return 7

        def read(self, _size):
            return next(self.chars)

    class Output:
        def __init__(self):
            self.value = ""

        def write(self, value):
            self.value += value

        def flush(self):
            pass

    terminal = [0, 0, 0, cli.termios.ECHO | cli.termios.ICANON, 0, 0, [0] * 32]
    output = Output()
    monkeypatch.setattr(cli.sys, "stdin", Input())
    monkeypatch.setattr(cli.sys, "stderr", output)
    monkeypatch.setattr(cli.termios, "tcgetattr", lambda _fd: [*terminal[:6], list(terminal[6])])
    changes = []
    monkeypatch.setattr(cli.termios, "tcsetattr", lambda fd, when, state: changes.append((fd, when, state)))
    assert cli._masked_getpass("Admin: ") == "Correct-Horse"
    assert output.value == "Admin: ********\b \b******\n"
    assert len(changes) == 2


def test_resume_can_adopt_an_already_configured_administrator_without_plaintext():
    cli = _load_bootstrap_cli()
    assert cli._initial_admin_password("resume", None) == ""
    source = Path(deployment_orchestrator.__file__).read_text(encoding="utf-8")
    assert "resuming and _bootstrap_admin_configured(database, config)" in source
    assert 'current_hash != "SHA256:placeholder_change_me"' in source
    assert 'resume_from_handoff = str(durable_resume.get("status") or "").upper() == "NATIVE_HANDOFF"' in source
    assert "if not resume_from_handoff:" in source


def test_empty_target_initialization_uses_database_managed_recovery_boundary(tmp_path):
    boundary = deployment_orchestrator._recovery_boundary(
        "INITIALIZE", False, "VERIFIED_EMPTY_TARGET",
    )
    assert boundary == {
        "status": "NOT_REQUIRED",
        "authority": "DATABASE_MANAGED",
        "reason": "NO_PREEXISTING_PLATFORM_DATA",
        "initialization_boundary": "VERIFIED_EMPTY_TARGET",
    }
    with pytest.raises(deployment_orchestrator.DeploymentError, match="verified empty target"):
        deployment_orchestrator._recovery_boundary("INITIALIZE", False)


def test_upgrade_requires_database_backup_responsibility_confirmation():
    with pytest.raises(deployment_orchestrator.DeploymentError, match="explicit confirmation"):
        deployment_orchestrator._recovery_boundary("UPGRADE", False)
    assert deployment_orchestrator._recovery_boundary("UPGRADE", True) == {
        "status": "OPERATOR_CONFIRMED",
        "authority": "DATABASE_MANAGED",
        "reason": "DATABASE_BACKUP_AND_RECOVERY_ACCEPTED",
        "verification": "NOT_CLIENT_VERIFIABLE",
    }


def test_noninteractive_upgrade_requires_explicit_confirmation(monkeypatch):
    cli = _load_bootstrap_cli()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(deployment_orchestrator.DeploymentError, match="--confirm-database-backup"):
        cli._database_backup_confirmation("upgrade", False)
    assert cli._database_backup_confirmation("upgrade", True) is True
    assert cli._database_backup_confirmation("initialize", False) is False


def test_interactive_upgrade_accepts_only_explicit_word(monkeypatch):
    cli = _load_bootstrap_cli()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    with pytest.raises(deployment_orchestrator.DeploymentError, match="not accepted"):
        cli._database_backup_confirmation("upgrade", False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "UPGRADE")
    assert cli._database_backup_confirmation("upgrade", False) is True


def test_initialize_verifies_empty_target_before_recovery_boundary():
    runtime_root, package_root, packaged = _layout()
    source = (runtime_root / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    run_source = source.split("def run(mode:", 1)[1]
    assert run_source.index("first = preflight(") < run_source.index("recovery = _recovery_boundary(")
    assert 'prior.get("initialization_boundary")' in run_source
    assert 'prior_recovery.get("status") == "OPERATOR_CONFIRMED"' in run_source
    runner_path = runtime_root / "migration_runner.py" if packaged else package_root / "migration_runner.py"
    runner = runner_path.read_text(encoding="utf-8")
    assert "and not (args.preflight or args.dry_run)" in runner
    assert "and not args.confirm_database_backup" in runner


class _OraclePreflightCursor:
    def __init__(self, partitioning):
        self.partitioning = partitioning
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        self.sql = sql.upper()

    def fetchone(self):
        if "V$INSTANCE" in self.sql:
            return ("23.26.3.0.0",)
        if "COUNT(*) FROM USER_TABLES" in self.sql:
            return (0,)
        if "SYS_CONTEXT" in self.sql:
            return ("DB4AGENT",)
        if "V$OPTION" in self.sql:
            return (self.partitioning,)
        if "USER_USERS" in self.sql:
            return ("AI_TBS", "TEMP")
        if "USER_TS_QUOTAS" in self.sql:
            return (-1,)
        if "USER_ROLE_PRIVS" in self.sql:
            if "DEEP_SEC_SESSION_ROLE" in self.sql:
                return (1,)
            return ("CTXAPP",)
        if "CTXSYS" in self.sql and "CTX_DDL" in self.sql:
            return (1,)
        if "NLS_DATABASE_PARAMETERS" in self.sql:
            return ("AL32UTF8",)
        raise AssertionError(self.sql)

    def fetchall(self):
        if "SESSION_PRIVS" in self.sql:
            required = (
                deployment_orchestrator.ORACLE_OWNER_BASE_PRIVILEGES
                | deployment_orchestrator.ORACLE_ENTERPRISE_OWNER_PRIVILEGES
            )
            return [(item,) for item in sorted(required)]
        if "USER_TAB_PRIVS_RECD" in self.sql:
            return [
                ("SYS", "DBMS_CRYPTO", "EXECUTE"),
                ("SYS", "UTL_HTTP", "EXECUTE"),
            ]
        raise AssertionError(self.sql)


class _OraclePreflightConnection:
    def __init__(self, partitioning):
        self.cursor_instance = _OraclePreflightCursor(partitioning)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        return None


class _PgPreflightCursor:
    def __init__(self, age_ready: bool):
        self.age_ready = age_ready
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, _params=None):
        self.sql = sql

    def fetchone(self):
        if self.sql == "SHOW server_version":
            return ("18.3",)
        if "has_schema_privilege(current_user,'ag_catalog'" in self.sql:
            return (self.age_ready,)
        if "has_table_privilege(current_user,'ag_catalog.ag_graph'" in self.sql:
            return (self.age_ready,)
        if "has_table_privilege(current_user,'ag_catalog.ag_label'" in self.sql:
            return (self.age_ready,)
        if "has_database_privilege(current_user,current_database()" in self.sql:
            return (self.age_ready,)
        if "SELECT rolcreaterole FROM pg_roles" in self.sql:
            return (self.age_ready,)
        if "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ai_agent_runtime')" in self.sql:
            return (self.age_ready,)
        if "FROM pg_auth_members membership" in self.sql:
            return (self.age_ready,)
        if "has_schema_privilege(current_user,'public'" in self.sql:
            return (True,)
        if "COUNT(*) FROM information_schema.tables" in self.sql:
            return (0,)
        raise AssertionError(self.sql)

    def fetchall(self):
        if "FROM pg_extension" in self.sql:
            return [("age",), ("vector",)]
        if "FROM pg_available_extensions" in self.sql:
            return [("age",), ("vector",)]
        raise AssertionError(self.sql)


class _PgPreflightConnection:
    def __init__(self, age_ready: bool):
        self.cursor_instance = _PgPreflightCursor(age_ready)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        return None


@pytest.mark.parametrize(("age_ready", "passed"), ((True, True), (False, False)))
def test_pg_preflight_requires_bounded_age_owner_privileges(monkeypatch, age_ready, passed):
    monkeypatch.setattr(
        deployment_orchestrator, "_connect",
        lambda _database, _config: _PgPreflightConnection(age_ready),
    )
    result = deployment_orchestrator.preflight(
        "pg",
        {"user": "owner", "password": "secret", "host": "db", "port": 5433, "dbname": "platform"},
        require_empty=True,
    )
    check = next(item for item in result["checks"] if item["code"] == "PG_AGE_OWNER_PRIVILEGES")
    assert check["state"] == ("PASS" if passed else "BLOCKED")
    role_check = next(item for item in result["checks"] if item["code"] == "PG_AGENT_ROLE_ADMIN")
    assert role_check["state"] == ("PASS" if passed else "BLOCKED")
    assert result["passed"] is passed


def test_pg_prerequisite_grants_age_without_superuser():
    source = _database_deploy_script(
        "pg", "0_pg_database_prerequisites.sql",
    ).read_text(encoding="utf-8")
    assert "GRANT USAGE ON SCHEMA ag_catalog" in source
    assert 'GRANT CREATE ON DATABASE :"DBNAME"' in source
    assert "CREATE ROLE ai_agent_runtime NOLOGIN NOSUPERUSER" in source
    assert 'ALTER ROLE :"schema_owner" CREATEROLE' in source
    assert 'GRANT ai_agent_runtime TO :"schema_owner" WITH ADMIN OPTION' in source
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("--")
    )
    assert 'ALTER ROLE :"schema_owner" SUPERUSER' not in executable


def test_pg_control_plane_force_rls_allows_only_the_trusted_table_owner():
    source = _database_deploy_script(
        "pg", "50_v4_4_9_security_boundary_repair.sql",
    ).read_text(encoding="utf-8")
    owner_policy = source.index("trusted_owner_control_plane")
    seed = source.index("INSERT INTO cx_platform_safe_autonomy_policies")
    assert owner_policy < seed
    assert "TO %I USING (true) WITH CHECK (true)" in source
    assert "deny_direct_runtime" in source
    assert "FORCE ROW LEVEL SECURITY" in source


def test_pg_terminal_migration_closes_all_force_rls_owner_policies():
    source = _database_deploy_script(
        "pg", "65_v4_4_10_external_agent_domain_context.sql",
    ).read_text(encoding="utf-8")
    assert "class.relforcerowsecurity" in source
    assert "cx_trusted_schema_owner" in source
    assert "TO %I USING (true) WITH CHECK (true)" in source
    assert "item.owner_name" in source


def test_pg_agent_login_creation_keeps_rotation_under_bounded_owner():
    runtime_root, package_root, packaged = _layout()
    if packaged and _packaged_database(package_root) != "pg":
        pytest.skip("PostgreSQL package contract")
    path = (
        runtime_root / "lib" / "agent_api.py"
        if packaged
        else package_root / "adapters" / "pg" / "agent_api.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "SET LOCAL createrole_self_grant = 'set, inherit'" in source
    assert "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS" in source


def test_yashandb_prerequisite_and_preflight_require_agent_user_rotation():
    runtime_root, package_root, packaged = _layout()
    if packaged and _packaged_database(package_root) != "yashandb":
        pytest.skip("YashanDB package contract")
    deploy = runtime_root / "deploy" if packaged else package_root / "adapters" / "yashandb" / "deploy"
    prerequisite = (deploy / "0_yashandb_database_prerequisites.sql").read_text(encoding="utf-8").upper()
    assert "CREATE PROCEDURE, CREATE TRIGGER, CREATE TYPE, CREATE JOB" in prerequisite
    assert "GRANT CREATE USER TO &&SCHEMA_OWNER" in prerequisite
    assert "GRANT ALTER USER TO &&SCHEMA_OWNER" in prerequisite
    assert "CREATE ROLE DEEP_SEC_SESSION_ROLE" in prerequisite
    assert "GRANT DEEP_SEC_SESSION_ROLE TO &&SCHEMA_OWNER WITH ADMIN OPTION" in prerequisite
    assert "GRANT DBA" not in prerequisite
    source = Path(deployment_orchestrator.__file__).read_text(encoding="utf-8")
    assert 'YASHAN_OWNER_BASE_PRIVILEGES = frozenset({' in source
    assert '"CREATE USER", "ALTER USER"' in source
    assert '"CREATE PROCEDURE", "CREATE TRIGGER", "CREATE TYPE", "CREATE JOB"' in source
    assert '"YASHAN_AGENT_ROLE_ADMIN"' in source
    assert '"USER_SYS_PRIVS" if database == "yashandb" else "SESSION_PRIVS"' in source
    assert "ADMIN_OPTION='Y'" in source
    assert "DBA_ROLES WHERE ROLE='DEEP_SEC_SESSION_ROLE'" not in source
    target_edition = _packaged_edition(package_root) if packaged else "community"
    actions = deployment_orchestrator.manifest("yashandb", target_edition, package_root)
    assert actions[-1].path.name == "6_deep_sec_policy.sql"
    builder = (package_root / "build.py").read_text(encoding="utf-8") if not packaged else ""
    if builder:
        assert 'if database != "yashandb":' in builder


@pytest.mark.parametrize(("value", "passed"), (("TRUE", True), ("FALSE", False)))
def test_oracle_preflight_requires_partitioning(monkeypatch, value, passed):
    monkeypatch.setattr(
        deployment_orchestrator, "_connect",
        lambda _database, _config: _OraclePreflightConnection(value),
    )
    result = deployment_orchestrator.preflight(
        "oracle", {"user": "owner", "password": "secret", "dsn": "db/service"},
        require_empty=True,
    )
    partitioning = next(item for item in result["checks"] if item["code"] == "ORACLE_PARTITIONING")
    assert partitioning["state"] == ("PASS" if passed else "BLOCKED")
    assert result["passed"] is passed


@pytest.mark.parametrize("edition", ("community", "enterprise"))
def test_oracle_preflight_requires_data_grant_privilege(monkeypatch, edition):
    connection = _OraclePreflightConnection("TRUE")
    original = connection.cursor_instance.fetchall

    def fetchall():
        if "SESSION_PRIVS" in connection.cursor_instance.sql:
            return [(item,) for item in sorted(deployment_orchestrator.ORACLE_OWNER_BASE_PRIVILEGES)]
        return original()

    connection.cursor_instance.fetchall = fetchall
    monkeypatch.setattr(
        deployment_orchestrator, "_connect",
        lambda _database, _config: connection,
    )
    result = deployment_orchestrator.preflight(
        "oracle", {"user": "owner", "password": "secret", "dsn": "db/service"},
        require_empty=True, edition=edition,
    )
    owner = next(item for item in result["checks"] if item["code"] == "OWNER_PRIVILEGES")
    assert owner["state"] == "BLOCKED"
    assert set(owner["detail"]["missing"]) == deployment_orchestrator.ORACLE_ENTERPRISE_OWNER_PRIVILEGES


def test_oracle_preflight_accepts_native_yes_admin_option():
    source = Path(deployment_orchestrator.__file__).read_text(encoding="utf-8")
    assert "ADMIN_OPTION IN ('Y','YES')" in source


def test_oracle_preflight_blocks_missing_create_trigger(monkeypatch):
    connection = _OraclePreflightConnection("TRUE")
    original = connection.cursor_instance.fetchall

    def fetchall():
        if "SESSION_PRIVS" in connection.cursor_instance.sql:
            return [
                (item,) for item in sorted(
                    (deployment_orchestrator.ORACLE_OWNER_BASE_PRIVILEGES
                     | deployment_orchestrator.ORACLE_ENTERPRISE_OWNER_PRIVILEGES)
                    - {"CREATE TRIGGER"}
                )
            ]
        return original()

    connection.cursor_instance.fetchall = fetchall
    monkeypatch.setattr(deployment_orchestrator, "_connect", lambda *_args: connection)
    result = deployment_orchestrator.preflight(
        "oracle", {"user": "owner", "password": "secret", "dsn": "db/service"},
        require_empty=True,
    )
    owner = next(item for item in result["checks"] if item["code"] == "OWNER_PRIVILEGES")
    assert owner["state"] == "BLOCKED"
    assert owner["detail"]["missing"] == ["CREATE TRIGGER"]
    assert result["passed"] is False


def test_oracle_preflight_blocks_missing_direct_sys_package_grants(monkeypatch):
    connection = _OraclePreflightConnection("TRUE")
    original = connection.cursor_instance.fetchall

    def fetchall():
        if "USER_TAB_PRIVS_RECD" in connection.cursor_instance.sql:
            return []
        return original()

    connection.cursor_instance.fetchall = fetchall
    monkeypatch.setattr(deployment_orchestrator, "_connect", lambda *_args: connection)
    result = deployment_orchestrator.preflight(
        "oracle", {"user": "owner", "password": "secret", "dsn": "db/service"},
        require_empty=True,
    )
    check = next(item for item in result["checks"] if item["code"] == "OWNER_OBJECT_PRIVILEGES")
    assert check["state"] == "BLOCKED"
    assert check["detail"]["missing"] == ["SYS.DBMS_CRYPTO.EXECUTE", "SYS.UTL_HTTP.EXECUTE"]


def test_oracle_enterprise_manifest_executes_deep_security_before_migrations():
    root = Path(__file__).resolve().parents[2]
    if not (root / "adapters" / "oracle").is_dir() and _packaged_database(root) != "oracle":
        pytest.skip("Oracle package contract")
    if not (root / "adapters" / "oracle").is_dir() and _packaged_edition(root) != "enterprise":
        pytest.skip("Oracle Enterprise package contract")
    actions = deployment_orchestrator.manifest("oracle", "enterprise", root)
    assert actions[-1].path.name == "6_deep_sec_policy.sql"
    if (root / "adapters" / "oracle").is_dir():
        assert "6_deep_sec_policy.sql" not in {
            item.path.name for item in deployment_orchestrator.manifest("oracle", "community", root)
        }


def test_oracle_baseline_initializes_crypto_and_uses_runtime_schema_owner():
    root = Path(__file__).resolve().parents[2]
    deploy = root / "adapters" / "oracle" / "deploy" if (root / "adapters").is_dir() else root / "scripts" / "deploy"
    if not deploy.is_dir() or _packaged_database(root) != "oracle" and not (root / "adapters").is_dir():
        pytest.skip("Oracle package contract")
    if not (root / "adapters" / "oracle").is_dir() and _packaged_edition(root) != "enterprise":
        pytest.skip("Oracle Enterprise package contract")
    api = (deploy / "2_api.sql").read_text(encoding="utf-8")
    policy = (deploy / "6_deep_sec_policy.sql").read_text(encoding="utf-8")
    orchestrator = (Path(__file__).resolve().parents[1] / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    assert "db_crypto_master_key" in api and "DBMS_CRYPTO.RANDOMBYTES(32)" in api
    assert '"&&SCHEMA_OWNER..agent_auth_pkg.init_agent_context"' in policy
    assert '"SCHEMA_OWNER" if database == "oracle" else "schema_owner": config["user"]' in orchestrator
    assert "verified = postflight(" in orchestrator
    assert "SET_AGENT_CONTEXT.set_agent_id(:agent_id)" in orchestrator
    assert "SYS_CONTEXT('AGENT_CTX','AGENT_ID')='POSTFLIGHT_PROBE'" in orchestrator
    assert "SET_AGENT_CONTEXT.clear_context()" in orchestrator


def test_bootstrap_evidence_contains_identity_not_plaintext_password():
    source = (Path(__file__).resolve().parents[1] / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    postflight = source.split('_record_evidence(journal.run_id, "POSTFLIGHT"', 1)[1]
    assert '"initial_admin": admin' in postflight
    assert '"bootstrap_admin_password"' not in postflight
    assert '"password_hash"' not in postflight


def test_existing_deployment_record_uses_exact_oracle_update_binds(monkeypatch):
    class Tx:
        def query_one(self, _sql, _params):
            return {"run_id": "DEPLOY_TEST"}

        def execute(self, sql, params):
            if sql.startswith("UPDATE CX_DEPLOYMENT_RUNS"):
                placeholders = set(re.findall(r":([a-z_]+)", sql))
                assert set(params) == placeholders

    tx = Tx()
    monkeypatch.setattr(connection, "execute_transaction_callback", lambda work: work(tx))
    monkeypatch.setattr(native_agent_api, "_ensure_principal", lambda *_args: None)
    monkeypatch.setattr(native_agent_api, "_audit", lambda *_args: None)
    deployment_orchestrator._database_record(
        "DEPLOY_TEST", "INITIALIZE", "oracle", "enterprise", "4.4.10",
        "plan", "journal", "COMPLETED", {"database": "READY"}, "postflight",
    )


def test_existing_deployment_step_uses_exact_oracle_update_binds(monkeypatch):
    class Tx:
        def query_one(self, _sql, _params):
            return {"step_id": "DST_TEST", "attempt_count": 1}

        def execute(self, sql, params):
            placeholders = set(re.findall(r":([a-z_]+)", sql))
            assert set(params) == placeholders

    monkeypatch.setattr(connection, "execute_transaction_callback", lambda work: work(Tx()))
    deployment_orchestrator._record_step(
        "DEPLOY_TEST", "base-01-1_schema", 1, "digest", "COMPLETED", {"passed": True},
    )


@pytest.mark.parametrize("api_key", ["", "provider-secret"])
def test_existing_llm_profile_uses_exact_oracle_update_binds(monkeypatch, api_key):
    class Tx:
        def query_one(self, sql, _params):
            if "CX_LLM_PROVIDER_PROFILES" in sql:
                return {"profile_id": "LLM_DEPLOYMENT_DEFAULT", "version": 1}
            return None

        def execute(self, sql, params):
            if sql.startswith("UPDATE CX_LLM_PROVIDER_PROFILES"):
                placeholders = set(re.findall(r":([a-z_]+)", sql))
                assert set(params) == placeholders

    if api_key:
        from lib import connection_crypto
        monkeypatch.setattr(connection_crypto, "encrypt_section", lambda _value: "ciphertext")
    monkeypatch.setattr(connection, "execute_transaction_callback", lambda work: work(Tx()))
    monkeypatch.setattr(native_agent_api, "_audit", lambda *_args: None)
    native_agent_api.upsert_llm_profile(
        "BOOTSTRAP", "deployment-default", "https://llm.example/v1", "model-id",
        api_key, "bootstrap model configuration",
    )


def test_first_run_wizard_keeps_llm_optional_and_generates_session_secret():
    runtime_root, package_root, packaged = _layout()
    wizard_path = runtime_root / "config_wizard.sh" if packaged else runtime_root / "scripts" / "config_wizard.sh"
    wizard = wizard_path.read_text(encoding="utf-8")
    assert "LLM API URL (leave empty to configure after bootstrap)" in wizard
    assert "LLM model ID (provider model identifier; leave empty if URL is empty)" in wizard
    assert "LLM API URL and model ID must be configured together" in wizard
    assert "secrets.token_urlsafe(48)" in wizard
    assert "read_masked_secret" in wizard
    assert 'read_masked_secret "  DB password: " DB_PASS' in wizard
    assert 'read_masked_secret "  LLM API key (leave empty if none): " LLM_KEY' in wizard
    assert 'read_masked_secret "  Embedding API key (leave empty if none or Agent-side): " EMB_KEY' in wizard
    assert "Listen address" in wizard
    assert "Web port" in wizard
    assert 'c["server"]["host"] = os.environ["SERVER_HOST"]' in wizard
    assert 'c["server"]["port"] = int(os.environ["SERVER_PORT"])' in wizard
    if packaged:
        example = json.loads((package_root / "config.example.json").read_text(encoding="utf-8"))
        assert example["security"]["secret_key"] == "<SESSION_SECRET>"
    else:
        build = (package_root / "build.py").read_text(encoding="utf-8")
        assert '"secret_key": "<SESSION_SECRET>"' in build


def test_first_run_wizard_persists_server_binding(tmp_path):
    runtime_root, _package_root, packaged = _layout()
    source_scripts = runtime_root if packaged else runtime_root / "scripts"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(source_scripts / "config_wizard.sh", scripts / "config_wizard.sh")
    shutil.copy2(source_scripts / "python_runtime.sh", scripts / "python_runtime.sh")
    (tmp_path / "config.example.json").write_text(json.dumps({
        "database": {"user": "<DB_USER>", "password": "<DB_PASSWORD>", "dsn": "<DB_DSN>"},
        "server": {"host": "0.0.0.0", "port": 8000},
        "security": {"secret_key": "<SESSION_SECRET>"},
        "llm": {"api_url": "<LLM_URL>", "model": "<LLM_MODEL>", "api_key": "<LLM_KEY>"},
        "embedding": {"api_url": "<EMBEDDING_URL>", "api_key": "<EMBEDDING_KEY>"},
    }), encoding="utf-8")
    class Handler(BaseHTTPRequestHandler):
        model = "provider/model-prod-001-0731"
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload = json.dumps({"model": self.model, "choices": [{"message": {"content": "ok"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, _format, *_args):
            return
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    llm_url = f"http://127.0.0.1:{server.server_port}/v1"
    answers = f"Y\naiadmin\ndb-secret\nlocalhost:1521/service\n127.0.0.1\n18081\n{llm_url}\nmodel-prod-001\n\n5\n"
    try:
        result = subprocess.run(
            ["bash", str(scripts / "config_wizard.sh")], input=answers, text=True,
            capture_output=True, env=dict(os.environ, PYTHON_BIN=sys.executable), check=False,
        )
        config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        Handler.model = "different-model"
        (tmp_path / "config.json").unlink(missing_ok=True)
        mismatch = subprocess.run(
            ["bash", str(scripts / "config_wizard.sh")], input=answers, text=True,
            capture_output=True, env=dict(os.environ, PYTHON_BIN=sys.executable), check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.returncode == 0, result.stderr
    assert config["server"] == {"host": "127.0.0.1", "port": 18081}
    assert config["llm"]["api_url"] == llm_url
    assert config["llm"]["model"] == "model-prod-001"
    assert "LLM endpoint and model ID verified" in result.stdout
    assert mismatch.returncode == 2
    assert "LLM endpoint returned a different model ID" in mismatch.stderr
    rejected = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert rejected["llm"] == {
        "api_url": "<LLM_URL>", "model": "<LLM_MODEL>", "api_key": "<LLM_KEY>",
    }
    assert "Web service binding: 127.0.0.1:18081" in result.stdout


def test_first_run_wizard_rejects_llm_url_without_model_id(tmp_path):
    runtime_root, _package_root, packaged = _layout()
    source_scripts = runtime_root if packaged else runtime_root / "scripts"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(source_scripts / "config_wizard.sh", scripts / "config_wizard.sh")
    shutil.copy2(source_scripts / "python_runtime.sh", scripts / "python_runtime.sh")
    (tmp_path / "config.example.json").write_text(json.dumps({
        "database": {"user": "<DB_USER>", "password": "<DB_PASSWORD>", "dsn": "<DB_DSN>"},
        "server": {"host": "0.0.0.0", "port": 8000},
        "security": {"secret_key": "<SESSION_SECRET>"},
        "llm": {"api_url": "<LLM_URL>", "model": "<LLM_MODEL>", "api_key": "<LLM_KEY>"},
        "embedding": {"api_url": "<EMBEDDING_URL>", "api_key": "<EMBEDDING_KEY>"},
    }), encoding="utf-8")
    answers = "Y\naiadmin\ndb-secret\nlocalhost:1521/service\n\n\nhttps://llm.example/v1\n\n"
    result = subprocess.run(
        ["bash", str(scripts / "config_wizard.sh")], input=answers, text=True,
        capture_output=True, env=dict(os.environ, PYTHON_BIN=sys.executable), check=False,
    )
    assert result.returncode == 2
    assert "LLM API URL and model ID must be configured together" in result.stderr
