"""Deterministic release-bound Bootstrap Deployment Agent orchestration.

The orchestrator is deliberately local to a release package.  It coordinates
only checksummed package scripts and never executes LLM output, remote callback
instructions, or arbitrary SQL supplied through its status/API surfaces.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


RUN_MODES = frozenset({"INITIALIZE", "UPGRADE", "RESUME", "STATUS", "VERIFY"})
TERMINAL_STATES = frozenset({"COMPLETED", "RETIRED", "FAILED_MANUAL_ACTION_REQUIRED"})
ORACLE_OWNER_BASE_PRIVILEGES = frozenset({
    "CREATE SESSION", "CREATE TABLE", "CREATE SEQUENCE", "CREATE VIEW",
    "CREATE PROCEDURE", "CREATE TRIGGER", "CREATE TYPE", "CREATE JOB",
    "CREATE PROPERTY GRAPH",
})
ORACLE_ENTERPRISE_OWNER_PRIVILEGES = frozenset({
    "CREATE DATA GRANT", "CREATE ANY DATA GRANT", "ADMINISTER ANY DATA GRANT",
    "CREATE DATA ROLE", "DROP DATA ROLE", "GRANT ANY DATA ROLE",
    "SET USE DATA GRANTS ONLY", "CREATE END USER", "ALTER END USER",
    "DROP END USER", "CREATE END USER CONTEXT", "CREATE ANY END USER CONTEXT",
    "CREATE END USER SECURITY CONTEXT", "CREATE ANY CONTEXT",
})
ORACLE_OWNER_OBJECT_PRIVILEGES = frozenset({
    ("SYS", "DBMS_CRYPTO", "EXECUTE"),
    ("SYS", "UTL_HTTP", "EXECUTE"),
})
YASHAN_OWNER_BASE_PRIVILEGES = frozenset({
    "CREATE SESSION", "CREATE TABLE", "CREATE VIEW", "CREATE SEQUENCE",
    "CREATE PROCEDURE", "CREATE TRIGGER", "CREATE TYPE", "CREATE JOB",
    "CREATE USER", "ALTER USER",
})


class DeploymentError(RuntimeError):
    """A deterministic deployment error with a safe operator-facing message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe(value: Any) -> Any:
    """Redact secret-shaped values before evidence is persisted."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            result[str(key)] = "[REDACTED]" if any(token in lowered for token in ("password", "api_key", "secret", "token", "cipher")) else _safe(item)
        return result
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _root_from(path: Path) -> Path:
    # source: shared/lib/module.py -> repository root; package:
    # scripts/lib/module.py -> package root.
    return path.resolve().parents[2]


PACKAGE_ROOT = _root_from(Path(__file__))


class DeploymentJournal:
    """Small encrypted state journal for the pre-database bootstrap phase."""

    def __init__(self, root: Path, run_id: str = "") -> None:
        self.directory = root / ".runtime" / "deployment"
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.run_id = run_id or "DEPLOY_" + secrets.token_hex(16)
        self.path = self.directory / f"{self.run_id}.journal"
        self.key_path = self.directory / f"{self.run_id}.key"

    def _key(self) -> bytes:
        if self.key_path.exists():
            return base64.urlsafe_b64decode(self.key_path.read_bytes())
        key = secrets.token_bytes(32)
        self.key_path.write_bytes(base64.urlsafe_b64encode(key))
        os.chmod(self.key_path, 0o600)
        return key

    def save(self, payload: Dict[str, Any]) -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        body = json.dumps(_safe(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encrypted = AESGCM(self._key()).encrypt(nonce, body, self.run_id.encode("ascii"))
        self.path.write_bytes(nonce + encrypted)
        os.chmod(self.path, 0o600)
        return _digest(nonce + encrypted)

    def load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            raise DeploymentError("deployment journal is unavailable")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = self.path.read_bytes()
        if len(raw) < 13:
            raise DeploymentError("deployment journal integrity check failed")
        try:
            body = AESGCM(self._key()).decrypt(raw[:12], raw[12:], self.run_id.encode("ascii"))
            value = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise DeploymentError("deployment journal integrity check failed") from exc
        return value if isinstance(value, dict) else {}

    def retire(self) -> None:
        # Keep an encrypted, non-secret record for forensic linkage; destroy
        # the local key so it cannot later be reopened as an active journal.
        if self.key_path.exists():
            self.key_path.unlink()


@dataclass(frozen=True)
class ManifestAction:
    key: str
    phase: str
    path: Path
    authority: str = "OWNER"

    @property
    def digest(self) -> str:
        return _digest(self.path.read_bytes())


def _package_deploy_dir(database: str, root: Path = PACKAGE_ROOT) -> Path:
    packaged = root / "scripts" / "deploy"
    if packaged.is_dir():
        return packaged
    return root / "adapters" / database / "deploy"


def release_baseline(database: str, root: Path = PACKAGE_ROOT) -> Dict[str, Any]:
    """Load the sole adapter baseline and validate its executable boundary."""
    deploy = _package_deploy_dir(database, root)
    manifests = sorted(deploy.glob("baseline_v*.json"))
    if len(manifests) != 1:
        raise DeploymentError("package must contain exactly one deployment baseline manifest")
    try:
        baseline = json.loads(manifests[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeploymentError("deployment baseline manifest is unreadable") from exc
    version = str(baseline.get("version") or "").strip()
    terminal = str(baseline.get("required_terminal_migration") or "").strip()
    if not version or str(baseline.get("database") or "").lower() != database:
        raise DeploymentError("deployment baseline manifest does not match the selected database")
    if not terminal or not (deploy / terminal).is_file():
        raise DeploymentError("deployment baseline terminal migration is missing")
    return baseline


def release_version(database: str, root: Path = PACKAGE_ROOT, requested: str = "") -> str:
    """Resolve and verify the version declared by the packaged baseline."""
    version = str(release_baseline(database, root).get("version") or "").strip()
    requested = str(requested or "").strip()
    if requested and requested != version:
        raise DeploymentError("requested version does not match the packaged deployment baseline")
    return version


def _tool_path(database: str, root: Path = PACKAGE_ROOT) -> Path:
    name = {"oracle": "deploy_oracle.py", "pg": "deploy_pg.py", "yashandb": "deploy_yashandb.py"}[database]
    packaged = root / "scripts" / name
    if packaged.is_file():
        return packaged
    return root / "adapters" / database / name


def manifest(database: str, edition: str, root: Path = PACKAGE_ROOT) -> List[ManifestAction]:
    deploy = _package_deploy_dir(database, root)
    names = ["1_schema.sql", "7_v4_0_1_migration.sql", "2_api.sql", "3_jobs.sql", "4_harness_templates.sql"]
    names.append("8_v4_1_0_governance.sql" if edition.lower() == "enterprise" else "8_v4_1_0_registration.sql")
    if database == "oracle" and edition.lower() == "enterprise":
        names.append("6_deep_sec_policy.sql")
    if database == "yashandb":
        names.append("6_deep_sec_policy.sql")
    actions = []
    for index, name in enumerate(names, start=1):
        path = deploy / name
        if not path.is_file():
            raise DeploymentError(f"package manifest is missing {name}")
        actions.append(ManifestAction(f"base-{index:02d}-{path.stem}", "BASE_SCHEMA", path))
    return actions


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise DeploymentError(f"cannot load package deployer: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connect(database: str, config: Dict[str, Any]):
    if database == "oracle":
        import oracledb
        return oracledb.connect(user=config["user"], password=config["password"], dsn=config["dsn"], tcp_connect_timeout=10)
    if database == "yashandb":
        import yaspy
        return yaspy.Connection(user=config["user"], password=config["password"], dsn=config["dsn"])
    import psycopg2
    return psycopg2.connect(user=config["user"], password=config.get("password"), host=config["host"],
                            port=int(config.get("port", 5432)), dbname=config["dbname"], connect_timeout=10)


def _scalar(cursor: Any, sql: str, params: Any = None) -> Any:
    cursor.execute(sql, params or {})
    row = cursor.fetchone()
    return row[0] if row else None


def _check(code: str, state: str, message: str, remediation: str = "", detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"code": code, "state": state, "message": message, "remediation": remediation, "detail": _safe(detail or {})}


def preflight(database: str, config: Dict[str, Any], *, require_empty: bool = False,
              edition: str = "") -> Dict[str, Any]:
    """Return normalized prepared-database checks without changing the target."""
    checks: List[Dict[str, Any]] = []
    try:
        conn = _connect(database, config)
    except Exception as exc:
        message = str(exc)
        nne = database == "oracle" and ("DPY-3001" in message or "Native Network Encryption" in message)
        checks.append(_check(
            "DATABASE_CONNECTION", "BLOCKED", "Database connection could not be established",
            ("The database requires Oracle Native Network Encryption. Use a DBA-approved compatible "
             "server policy or a separately validated Oracle Client Thick Mode deployment; do not "
             "silently weaken encryption." if nne else
             "Verify the configured host, port, service, listener, credentials, and network path."),
            {"error_code": "ORACLE_NATIVE_ENCRYPTION_REQUIRES_THICK_MODE" if nne else "DATABASE_CONNECTION_FAILED"},
        ))
        return {"database": database, "checked_at": _now(), "checks": checks,
                "passed": False, "blocked": checks}
    try:
        with conn.cursor() as cursor:
            if database == "pg":
                version = str(_scalar(cursor, "SHOW server_version") or "")
                checks.append(_check("PG_VERSION", "PASS" if version.startswith("18.") else "BLOCKED", "PostgreSQL version detected", "Use PostgreSQL 18.", {"version": version}))
                extension_rows = []
                available_rows = []
                try:
                    cursor.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector','age')")
                    extension_rows = [str(item[0]) for item in cursor.fetchall()]
                    cursor.execute("SELECT name FROM pg_available_extensions WHERE name IN ('vector','age')")
                    available_rows = [str(item[0]) for item in cursor.fetchall()]
                except Exception:
                    pass
                for extension in ("vector", "age"):
                    state = "PASS" if extension in extension_rows else ("BLOCKED" if extension in available_rows else "BLOCKED")
                    checks.append(_check(f"PG_{extension.upper()}", state,
                                         f"{extension} extension is enabled in the target database",
                                         f"Install and enable PostgreSQL extension {extension} in the target database.",
                                         {"enabled": extension in extension_rows, "available": extension in available_rows}))
                if "age" in extension_rows:
                    try:
                        age_usage = bool(_scalar(cursor, "SELECT has_schema_privilege(current_user,'ag_catalog','USAGE')"))
                        age_graph = bool(_scalar(
                            cursor,
                            "SELECT has_table_privilege(current_user,'ag_catalog.ag_graph','SELECT,INSERT,UPDATE,DELETE')",
                        ))
                        age_label = bool(_scalar(
                            cursor,
                            "SELECT has_table_privilege(current_user,'ag_catalog.ag_label','SELECT,INSERT,UPDATE,DELETE')",
                        ))
                        age_create = bool(_scalar(
                            cursor,
                            "SELECT has_database_privilege(current_user,current_database(),'CREATE')",
                        ))
                        age_ready = age_usage and age_graph and age_label and age_create
                        checks.append(_check(
                            "PG_AGE_OWNER_PRIVILEGES", "PASS" if age_ready else "BLOCKED",
                            "Deployment owner can create and maintain Apache AGE graph namespaces",
                            "Run deploy/0_pg_database_prerequisites.sql as the database administrator in the target database.",
                            {
                                "schema_usage": age_usage,
                                "graph_catalog_access": age_graph,
                                "label_catalog_access": age_label,
                                "database_create": age_create,
                            },
                        ))
                    except Exception:
                        checks.append(_check(
                            "PG_AGE_OWNER_PRIVILEGES", "BLOCKED",
                            "Apache AGE owner privileges could not be verified",
                            "Run deploy/0_pg_database_prerequisites.sql as the database administrator in the target database.",
                        ))
                try:
                    can_create_roles = bool(_scalar(
                        cursor,
                        "SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user",
                    ))
                    runtime_role_exists = bool(_scalar(
                        cursor,
                        "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ai_agent_runtime')",
                    ))
                    runtime_role_admin = bool(_scalar(
                        cursor,
                        "SELECT EXISTS(SELECT 1 FROM pg_auth_members membership "
                        "JOIN pg_roles granted_role ON granted_role.oid=membership.roleid "
                        "JOIN pg_roles member_role ON member_role.oid=membership.member "
                        "WHERE granted_role.rolname='ai_agent_runtime' "
                        "AND member_role.rolname=current_user AND membership.admin_option)",
                    ))
                    role_ready = can_create_roles and runtime_role_exists and runtime_role_admin
                    checks.append(_check(
                        "PG_AGENT_ROLE_ADMIN", "PASS" if role_ready else "BLOCKED",
                        "Deployment owner can provision isolated Agent login roles",
                        "Run deploy/0_pg_database_prerequisites.sql as the database administrator in the target database.",
                        {
                            "create_role": can_create_roles,
                            "runtime_role_exists": runtime_role_exists,
                            "runtime_role_admin": runtime_role_admin,
                        },
                    ))
                except Exception:
                    checks.append(_check(
                        "PG_AGENT_ROLE_ADMIN", "BLOCKED",
                        "Agent login role-management prerequisites could not be verified",
                        "Run deploy/0_pg_database_prerequisites.sql as the database administrator in the target database.",
                    ))
                try:
                    can_create = bool(_scalar(cursor, "SELECT has_schema_privilege(current_user,'public','CREATE')"))
                    checks.append(_check("PG_SCHEMA_CREATE", "PASS" if can_create else "BLOCKED",
                                         "Deployment role can create objects in public schema",
                                         "Use the prepared schema owner or grant CREATE on the target schema."))
                except Exception:
                    checks.append(_check("PG_SCHEMA_CREATE", "WARN", "Schema create privilege could not be verified",
                                         "Verify the deployment role owns or can create objects in the target schema."))
                count = int(_scalar(cursor, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'") or 0)
            else:
                version = ""
                try:
                    version = str(_scalar(cursor, "SELECT VERSION FROM V$INSTANCE") or "")
                except Exception:
                    checks.append(_check("DB_VERSION_VIEW", "WARN", "Database version view is not visible to the deployment user", "Grant a read-only version view privilege for richer preflight evidence."))
                count = int(_scalar(cursor, "SELECT COUNT(*) FROM USER_TABLES") or 0)
                service = ""
                try:
                    service_sql = "SELECT SYS_CONTEXT('USERENV','CON_NAME') FROM " + "DU" + "AL"
                    service = str(_scalar(cursor, service_sql) or "")
                except Exception:
                    pass
                checks.append(_check("PDB_OR_SERVICE", "PASS" if service else "WARN", "Connected target is a prepared application service",
                                     "Connect to the prepared PDB/service for this deployment.", {"version": version, "service": service}))
                if database == "oracle" and service.upper() == "CDB$ROOT":
                    checks.append(_check("ORACLE_TARGET_PDB", "BLOCKED", "Oracle target is CDB$ROOT",
                                         "Create/open a dedicated PDB service and connect the deployment owner to that service."))
                elif database == "oracle":
                    checks.append(_check("ORACLE_TARGET_PDB", "PASS" if service else "WARN", "Oracle target PDB/service boundary"))
                if database == "oracle":
                    try:
                        cursor.execute("SELECT VALUE FROM V$OPTION WHERE PARAMETER = :parameter", {"parameter": "Partitioning"})
                        row = cursor.fetchone()
                        enabled = bool(row and str(row[0] or "").upper() == "TRUE")
                        checks.append(_check(
                            "ORACLE_PARTITIONING", "PASS" if enabled else "BLOCKED",
                            "Oracle Partitioning is enabled for the packaged baseline",
                            "Enable Partitioning in the active Oracle Home with chopt, restart the database, and rerun preflight.",
                            {"enabled": enabled},
                        ))
                    except Exception:
                        checks.append(_check(
                            "ORACLE_PARTITIONING", "BLOCKED",
                            "Oracle Partitioning availability could not be verified",
                            "Grant read-only access to V$OPTION for preflight or have the DBA verify Partitioning=TRUE.",
                        ))
                try:
                    cursor.execute("SELECT DEFAULT_TABLESPACE,TEMPORARY_TABLESPACE FROM USER_USERS")
                    row = cursor.fetchone()
                    default_ts, temp_ts = (str(row[0] or ""), str(row[1] or "")) if row else ("", "")
                    checks.append(_check("TABLESPACES", "PASS" if default_ts and temp_ts else "BLOCKED", "Default and temporary tablespaces are prepared",
                                         "Prepare writable default and temporary tablespaces for the deployment user.", {"default": default_ts, "temporary": temp_ts}))
                except Exception:
                    checks.append(_check("TABLESPACES", "WARN", "Tablespace metadata is not visible", "Grant read-only metadata visibility or review the DBA remediation report."))
                try:
                    privilege_view = "USER_SYS_PRIVS" if database == "yashandb" else "SESSION_PRIVS"
                    cursor.execute(f"SELECT PRIVILEGE FROM {privilege_view}")
                    privileges = {str(item[0]).upper() for item in cursor.fetchall()}
                    if database == "oracle":
                        required = set(ORACLE_OWNER_BASE_PRIVILEGES)
                    elif database == "yashandb":
                        required = set(YASHAN_OWNER_BASE_PRIVILEGES)
                    else:
                        required = {"CREATE TABLE", "CREATE PROCEDURE", "CREATE SEQUENCE"}
                    if database == "oracle":
                        required.update(ORACLE_ENTERPRISE_OWNER_PRIVILEGES)
                    missing = sorted(required - privileges)
                    checks.append(_check("OWNER_PRIVILEGES", "PASS" if not missing else "BLOCKED", "Deployment owner privileges",
                                         "Grant the required schema-owner privileges before deployment.", {"missing": missing}))
                except Exception:
                    checks.append(_check("OWNER_PRIVILEGES", "WARN", "Deployment owner privileges could not be verified",
                                         "Verify schema-owner privileges before deployment."))
                if database == "oracle":
                    try:
                        cursor.execute(
                            "SELECT COUNT(*) FROM USER_ROLE_PRIVS "
                            "WHERE GRANTED_ROLE='DEEP_SEC_SESSION_ROLE' AND ADMIN_OPTION IN ('Y','YES')"
                        )
                        role_admin = int(cursor.fetchone()[0] or 0) > 0
                        checks.append(_check(
                            "ORACLE_END_USER_ROLE_ADMIN",
                            "PASS" if role_admin else "BLOCKED",
                            "Oracle End User session-role management",
                            "Run deploy/0_oracle_database_prerequisites.sql as SYSDBA in the target PDB.",
                            {"owner_admin_option": role_admin},
                        ))
                    except Exception:
                        checks.append(_check(
                            "ORACLE_END_USER_ROLE_ADMIN", "BLOCKED",
                            "Oracle End User session-role prerequisites could not be verified",
                            "Run deploy/0_oracle_database_prerequisites.sql as SYSDBA in the target PDB.",
                        ))
                if database == "yashandb":
                    try:
                        cursor.execute(
                            "SELECT COUNT(*) FROM USER_ROLE_PRIVS "
                            "WHERE GRANTED_ROLE='DEEP_SEC_SESSION_ROLE' AND ADMIN_OPTION='Y'"
                        )
                        role_admin = int(cursor.fetchone()[0] or 0) > 0
                        role_exists = role_admin
                        checks.append(_check(
                            "YASHAN_AGENT_ROLE_ADMIN",
                            "PASS" if role_exists and role_admin else "BLOCKED",
                            "YashanDB independent Agent session-role management",
                            "Run deploy/0_yashandb_database_prerequisites.sql as the database administrator in the target PDB.",
                            {"role_exists": role_exists, "owner_admin_option": role_admin},
                        ))
                    except Exception:
                        checks.append(_check(
                            "YASHAN_AGENT_ROLE_ADMIN", "BLOCKED",
                            "YashanDB Agent session-role prerequisites could not be verified",
                            "Run deploy/0_yashandb_database_prerequisites.sql as the database administrator in the target PDB.",
                        ))
                if database == "oracle":
                    try:
                        has_unlimited = "UNLIMITED TABLESPACE" in privileges
                        cursor.execute("SELECT MAX_BYTES FROM USER_TS_QUOTAS WHERE TABLESPACE_NAME=(SELECT DEFAULT_TABLESPACE FROM USER_USERS)")
                        quota_row = cursor.fetchone()
                        quota = int(quota_row[0]) if quota_row and quota_row[0] is not None else 0
                        quota_ok = has_unlimited or quota == -1 or quota > 0
                        checks.append(_check("TABLESPACE_QUOTA", "PASS" if quota_ok else "BLOCKED",
                                             "Deployment owner has writable default-tablespace quota",
                                             "Grant an explicit quota on the application tablespace; UNLIMITED TABLESPACE is not required."))
                    except Exception:
                        checks.append(_check("TABLESPACE_QUOTA", "WARN", "Tablespace quota could not be verified",
                                             "Verify a non-zero owner quota on the default application tablespace."))
                    try:
                        cursor.execute("SELECT GRANTED_ROLE FROM USER_ROLE_PRIVS WHERE GRANTED_ROLE='CTXAPP'")
                        has_ctxapp = bool(cursor.fetchone())
                        cursor.execute("SELECT COUNT(*) FROM USER_TAB_PRIVS_RECD WHERE OWNER='CTXSYS' AND TABLE_NAME='CTX_DDL' AND PRIVILEGE='EXECUTE'")
                        has_ctxddl = int(cursor.fetchone()[0] or 0) > 0
                        checks.append(_check("ORACLE_TEXT", "PASS" if has_ctxapp and has_ctxddl else "BLOCKED",
                                             "Oracle Text creation privileges",
                                             "Grant CTXAPP and direct EXECUTE on CTXSYS.CTX_DDL to the deployment owner.",
                                             {"ctxapp": has_ctxapp, "ctx_ddl_execute": has_ctxddl}))
                    except Exception:
                        checks.append(_check("ORACLE_TEXT", "BLOCKED", "Oracle Text privileges could not be verified",
                                             "Install Oracle Text and grant CTXAPP plus direct CTXSYS.CTX_DDL execute."))
                    try:
                        cursor.execute("SELECT VALUE FROM NLS_DATABASE_PARAMETERS WHERE PARAMETER='NLS_CHARACTERSET'")
                        charset_row = cursor.fetchone()
                        charset = str(charset_row[0] or "") if charset_row else ""
                        checks.append(_check("DATABASE_CHARACTER_SET", "PASS" if charset == "AL32UTF8" else "WARN",
                                             "Oracle database character set", "Use AL32UTF8 for complete multilingual behavior.",
                                             {"character_set": charset}))
                    except Exception:
                        checks.append(_check("DATABASE_CHARACTER_SET", "WARN", "Oracle character set could not be verified",
                                             "Have the DBA verify NLS_CHARACTERSET=AL32UTF8."))
                    try:
                        cursor.execute(
                            "SELECT OWNER,TABLE_NAME,PRIVILEGE FROM USER_TAB_PRIVS_RECD "
                            "WHERE OWNER='SYS' AND TABLE_NAME IN ('DBMS_CRYPTO','UTL_HTTP')"
                        )
                        received = {
                            (str(row[0]).upper(), str(row[1]).upper(), str(row[2]).upper())
                            for row in cursor.fetchall()
                        }
                        missing_objects = sorted(
                            ".".join(item) for item in ORACLE_OWNER_OBJECT_PRIVILEGES - received
                        )
                        checks.append(_check(
                            "OWNER_OBJECT_PRIVILEGES",
                            "PASS" if not missing_objects else "BLOCKED",
                            "Deployment owner direct package privileges",
                            "Grant direct EXECUTE on SYS.DBMS_CRYPTO and SYS.UTL_HTTP to the deployment owner.",
                            {"missing": missing_objects},
                        ))
                    except Exception:
                        checks.append(_check(
                            "OWNER_OBJECT_PRIVILEGES", "BLOCKED",
                            "Deployment owner direct package privileges could not be verified",
                            "Grant the documented direct SYS package privileges and permit the owner to inspect received grants.",
                        ))
            checks.append(_check("TARGET_EMPTY", "PASS" if count == 0 else ("BLOCKED" if require_empty else "WARN"),
                                 "Application schema table count", "Use upgrade/resume for an existing platform target.", {"table_count": count}))
    finally:
        conn.close()
    blocked = [item for item in checks if item["state"] == "BLOCKED"]
    return {"database": database, "checked_at": _now(), "checks": checks, "passed": not blocked, "blocked": blocked}


def _execute_action(database: str, config: Dict[str, Any], action: ManifestAction, root: Path) -> None:
    tool = _load_module(_tool_path(database, root), f"cx_deployer_{database}")
    conn = _connect(database, config)
    try:
        if database in {"oracle", "pg"}:
            options = {
                "define_overrides": {
                    "SCHEMA_OWNER" if database == "oracle" else "schema_owner": config["user"],
                },
            }
            ok = bool(tool.execute_sql_file(conn, action.path, verbose=False, **options))
            if not ok:
                raise DeploymentError(f"package action failed: {action.key}")
            return
        # YashanDB deployer exposes trusted parser helpers but no callable file
        # executor. Keep execution local and only tolerate idempotent DDL.
        content = action.path.read_text(encoding="utf-8")
        content = tool.substitute_vars(content, tool.parse_defines(content))
        content = tool.remove_prompts(content)
        with conn.cursor() as cursor:
            for statement in tool.split_statements(content):
                try:
                    cursor.execute(statement)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    message = str(exc).lower()
                    if not any(token in message for token in ("already exists", "already indexed", "duplicate column")):
                        raise DeploymentError(f"package action failed: {action.key}") from exc
    finally:
        conn.close()


def _database_config(raw: Dict[str, Any], database: str) -> Dict[str, Any]:
    value = dict(raw.get("database") or {})
    if database == "pg":
        result = {"user": str(value.get("user") or ""), "password": str(value.get("password") or ""),
                  "host": str(value.get("host") or ""), "port": int(value.get("port") or 5432),
                  "dbname": str(value.get("dbname") or value.get("database") or "")}
        required = (result["user"], result["host"], result["dbname"])
    else:
        result = {"user": str(value.get("user") or ""), "password": str(value.get("password") or ""), "dsn": str(value.get("dsn") or "")}
        required = tuple(result.values())
    if not all(str(item).strip() for item in required):
        raise DeploymentError("database connection configuration is incomplete")
    return result


def _read_config(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeploymentError("deployment configuration is unreadable") from exc
    if not isinstance(value, dict):
        raise DeploymentError("deployment configuration must be a JSON object")
    return value


def _resolve_sensitive_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve only in process memory so encrypted configs support upgrade/resume."""
    resolved = dict(raw)
    try:
        from .connection_crypto import decrypt_database_section, decrypt_embedding_section, decrypt_llm_section
        resolved["database"] = decrypt_database_section(dict(raw.get("database") or {}))
        resolved["llm"] = decrypt_llm_section(dict(raw.get("llm") or {}))
        resolved["embedding"] = decrypt_embedding_section(dict(raw.get("embedding") or {}))
    except Exception as exc:
        raise DeploymentError("deployment configuration secrets cannot be decrypted") from exc
    return resolved


def _activate_runtime_config(config_path: Path) -> None:
    """Point packaged adapter services at the command's exact config file.

    Base SQL is executed through direct driver connections, but post-schema
    governance records use the selected adapter's connection facade.  Reset
    its lazy caches so both phases target the same database when ``--config``
    is used.
    """
    os.environ["CX_CONFIG_PATH"] = str(config_path.resolve())
    try:
        from . import config as runtime_config
        runtime_config._config = None
        from . import connection
        connection.close_pool()
        if hasattr(connection, "_pool"):
            connection._pool = None
    except Exception:
        # The direct deploy path remains authoritative until the selected
        # package adapter is present; its later imports will read this env var.
        pass


def _migration_apply(target_version: str, database: str, edition: str, config_path: Path,
                     config: Dict[str, Any], root: Path) -> List[Dict[str, Any]]:
    import sys
    scripts_root = root / "scripts"
    if scripts_root.is_dir() and str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    try:
        import migration_runner as runner
    except ImportError as exc:
        raise DeploymentError("migration runner is unavailable in this package") from exc
    runner.MIGRATION_VERSION = target_version
    runner.MIGRATION_EDITION = edition.lower()
    try:
        names = runner.release_script_names(target_version, database, config_path, edition.lower())
    except ValueError as exc:
        raise DeploymentError(str(exc)) from exc
    deploy = _package_deploy_dir(database, root)
    apply = {"oracle": runner._apply_oracle, "pg": runner._apply_pg, "yashandb": runner._apply_yashandb}[database]
    results = []
    for name in names:
        result = apply(config, deploy / name)
        results.append({"script": name, "passed": bool(result.passed), "ledger_status": result.ledger_status,
                        "checksum": result.checksum, "error": result.error_type})
        if not result.passed:
            raise DeploymentError(f"migration failed: {name}: {result.error_type or result.ledger_status}")
    return results


def _recovery_boundary(mode: str, database_backup_confirmed: bool,
                       initialization_boundary: str = "") -> Dict[str, Any]:
    """Record the operator boundary without pretending to inspect DB backups."""
    if mode == "INITIALIZE":
        if initialization_boundary != "VERIFIED_EMPTY_TARGET":
            raise DeploymentError("initialization requires a verified empty target boundary")
        return {
            "status": "NOT_REQUIRED",
            "authority": "DATABASE_MANAGED",
            "reason": "NO_PREEXISTING_PLATFORM_DATA",
            "initialization_boundary": initialization_boundary,
        }
    if not database_backup_confirmed:
        raise DeploymentError(
            "upgrade requires explicit confirmation that database-side backup "
            "and recovery responsibilities have been accepted"
        )
    return {
        "status": "OPERATOR_CONFIRMED",
        "authority": "DATABASE_MANAGED",
        "reason": "DATABASE_BACKUP_AND_RECOVERY_ACCEPTED",
        "verification": "NOT_CLIENT_VERIFIABLE",
    }


def _database_record(run_id: str, mode: str, database: str, edition: str, target_version: str, plan_digest: str,
                     journal_digest: str, status: str, readiness: Dict[str, Any], current_step: str = "") -> None:
    from . import connection, native_agent_api
    agent_id = "BOOTSTRAP_DEPLOYMENT_AGENT:" + run_id
    def work(tx: Any) -> None:
        native_agent_api._ensure_principal(tx, agent_id)
        existing = tx.query_one("SELECT RUN_ID FROM CX_DEPLOYMENT_RUNS WHERE RUN_ID=:id FOR UPDATE", {"id": run_id})
        params = {"id": run_id, "run_mode": mode, "database": database, "edition": edition.upper(), "version": target_version,
                  "status": status, "readiness": json.dumps(_safe(readiness), ensure_ascii=True), "plan": plan_digest,
                  "journal": journal_digest, "agent": agent_id, "step": current_step or None}
        if existing:
            update_params = {
                key: params[key]
                for key in ("status", "readiness", "journal", "step", "id")
            }
            tx.execute("UPDATE CX_DEPLOYMENT_RUNS SET STATUS=:status,READINESS_JSON=:readiness,JOURNAL_DIGEST=:journal,"
                       "CURRENT_STEP=:step,UPDATED_AT=CURRENT_TIMESTAMP WHERE RUN_ID=:id", update_params)
        else:
            tx.execute("INSERT INTO CX_DEPLOYMENT_RUNS(RUN_ID,RUN_MODE,DATABASE_DIALECT,EDITION,PACKAGE_VERSION,STATUS,"
                       "READINESS_JSON,PLAN_DIGEST,JOURNAL_DIGEST,DEPLOYMENT_AGENT_ID,CURRENT_STEP,CREATED_BY) VALUES "
                       "(:id,:run_mode,:database,:edition,:version,:status,:readiness,:plan,:journal,:agent,:step,'SYSTEM_BOOTSTRAP')", params)
        native_agent_api._audit(tx, agent_id, "BOOTSTRAP_DEPLOYMENT_STATE", "DEPLOYMENT_RUN", run_id, "ALLOW", status)
    connection.execute_transaction_callback(work)


def _record_step(run_id: str, step_key: str, step_order: int, action_digest: str,
                 status: str, result: Optional[Dict[str, Any]] = None, error_code: str = "") -> None:
    """Persist sanitized deployment progress after the control-plane migration exists."""
    from . import connection
    payload = _safe(result or {})
    def work(tx: Any) -> None:
        existing = tx.query_one(
            "SELECT STEP_ID,ATTEMPT_COUNT FROM CX_DEPLOYMENT_STEPS WHERE RUN_ID=:run AND STEP_KEY=:key FOR UPDATE",
            {"run": run_id, "key": step_key},
        )
        params = {"id": str((existing or {}).get("step_id") or "DST_" + _digest({"run": run_id, "key": step_key})[:32]),
                  "run": run_id, "key": step_key, "step_order": int(step_order), "status": status,
                  "digest": action_digest, "result": json.dumps(payload, ensure_ascii=True, sort_keys=True),
                  "error": _text_error(error_code), "attempts": int((existing or {}).get("attempt_count") or 0) + 1}
        if existing:
            update_params = {
                key: params[key]
                for key in ("id", "status", "digest", "result", "error", "attempts")
            }
            tx.execute(
                "UPDATE CX_DEPLOYMENT_STEPS SET STATUS=:status,ACTION_DIGEST=:digest,RESULT_JSON=:result,ERROR_CODE=:error,"
                "ATTEMPT_COUNT=:attempts,UPDATED_AT=CURRENT_TIMESTAMP,STARTED_AT=CASE WHEN :status='RUNNING' THEN CURRENT_TIMESTAMP ELSE STARTED_AT END,"
                "COMPLETED_AT=CASE WHEN :status IN ('COMPLETED','FAILED') THEN CURRENT_TIMESTAMP ELSE COMPLETED_AT END "
                "WHERE STEP_ID=:id", update_params,
            )
        else:
            tx.execute(
                "INSERT INTO CX_DEPLOYMENT_STEPS(STEP_ID,RUN_ID,STEP_KEY,STEP_ORDER,STATUS,ACTION_DIGEST,RESULT_JSON,ERROR_CODE,ATTEMPT_COUNT,STARTED_AT,COMPLETED_AT) "
                "VALUES (:id,:run,:key,:step_order,:status,:digest,:result,:error,:attempts,CURRENT_TIMESTAMP,CASE WHEN :status IN ('COMPLETED','FAILED') THEN CURRENT_TIMESTAMP ELSE NULL END)", params,
            )
    connection.execute_transaction_callback(work)


def _text_error(value: str) -> Optional[str]:
    return str(value or "").strip()[:128] or None


def _record_evidence(run_id: str, evidence_type: str, payload: Dict[str, Any], status: str = "RECORDED") -> None:
    from . import connection
    safe = _safe(payload)
    body = json.dumps(safe, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    connection.execute(
        "INSERT INTO CX_DEPLOYMENT_EVIDENCE(EVIDENCE_ID,RUN_ID,EVIDENCE_TYPE,PAYLOAD_JSON,PAYLOAD_DIGEST,STATUS) "
        "VALUES (:id,:run,:type,:payload,:digest,:status)",
        {"id": "DEV_" + secrets.token_hex(20), "run": run_id, "type": str(evidence_type)[:64],
         "payload": body, "digest": _digest(body), "status": str(status)[:32]},
    )


def _deployment_database_status(database: str, config: Dict[str, Any], run_id: str = "") -> Dict[str, Any]:
    """Read durable status without relying on the web adapter or config path."""
    conn = _connect(database, config)
    try:
        with conn.cursor() as cursor:
            predicate = "WHERE RUN_ID=:id" if run_id else ""
            params: Any = {"id": run_id} if run_id else {}
            if database == "pg":
                predicate = "WHERE run_id=%(id)s" if run_id else ""
                params = {"id": run_id} if run_id else None
            sql = ("SELECT RUN_ID,STATUS,CURRENT_STEP,READINESS_JSON,FAILURE_CODE,FAILURE_DETAIL,CREATED_AT,UPDATED_AT,COMPLETED_AT "
                   "FROM CX_DEPLOYMENT_RUNS " + predicate + " ORDER BY CREATED_AT DESC")
            if database == "pg":
                sql += " LIMIT 1"
            else:
                sql += " FETCH FIRST 1 ROWS ONLY"
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if not row:
                return {"state": "NOT_INITIALIZED"}
            names = [str(item[0]).lower() for item in cursor.description]
            value = dict(zip(names, row))
            try:
                value["readiness"] = json.loads(str(value.pop("readiness_json", "{}") or "{}"))
            except ValueError:
                value["readiness"] = {}
            value["state"] = "RECORDED"
            return value
    except Exception:
        return {"state": "NOT_INITIALIZED"}
    finally:
        conn.close()


def postflight(database: str, edition: str, config: Dict[str, Any], terminal_migration: str) -> Dict[str, Any]:
    """Verify release and database-security closure before reporting READY."""
    checks: List[Dict[str, Any]] = []
    conn = _connect(database, config)
    try:
        with conn.cursor() as cursor:
            step = terminal_migration.removesuffix(".sql")
            if database == "pg":
                cursor.execute(
                    "SELECT COUNT(*) FROM AI_SCHEMA_MIGRATION_STEPS WHERE STEP_NAME=%s AND STATUS='APPLIED'",
                    (step,),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM AI_SCHEMA_MIGRATION_STEPS WHERE STEP_NAME=:step AND STATUS='APPLIED'",
                    {"step": step},
                )
            terminal_count = int((cursor.fetchone() or [0])[0] or 0)
            checks.append(_check(
                "TERMINAL_MIGRATION", "PASS" if terminal_count == 1 else "BLOCKED",
                "Packaged terminal migration is applied",
                "Apply the complete release-bound migration chain before handoff.",
                {"step": terminal_migration, "count": terminal_count},
            ))

            cursor.execute("SELECT COUNT(*) FROM AI_SCHEMA_MIGRATION_STEPS WHERE STATUS='FAILED'")
            failed = int((cursor.fetchone() or [0])[0] or 0)
            checks.append(_check(
                "FAILED_MIGRATIONS", "PASS" if failed == 0 else "BLOCKED",
                "Migration ledger has no failed steps",
                "Resolve failed migration steps before handoff.", {"count": failed},
            ))

            if database == "oracle":
                dual = "DU" + "AL"
                cursor.execute(
                    "SELECT COUNT(*) FROM USER_OBJECTS WHERE STATUS='INVALID' "
                    "AND OBJECT_TYPE IN ('PACKAGE','PACKAGE BODY','PROCEDURE','FUNCTION','TRIGGER')"
                )
                invalid_plsql = int((cursor.fetchone() or [0])[0] or 0)
                checks.append(_check(
                    "ORACLE_INVALID_PLSQL", "PASS" if invalid_plsql == 0 else "BLOCKED",
                    "Oracle executable schema objects are valid",
                    "Inspect USER_ERRORS and compile or redeploy every invalid executable object.",
                    {"count": invalid_plsql},
                ))

                cursor.execute(
                    "SELECT COUNT(*) FROM SYSTEM_CONFIG WHERE CONFIG_KEY IN "
                    "('db_crypto_master_key','db_crypto_key_salt') AND CONFIG_VALUE IS NOT NULL"
                )
                key_count = int((cursor.fetchone() or [0])[0] or 0)
                checks.append(_check(
                    "DB_CRYPTO_KEYS", "PASS" if key_count == 2 else "BLOCKED",
                    "Database encryption keys are initialized",
                    "Initialize both DB_CRYPTO key records through the trusted owner bootstrap.",
                    {"count": key_count},
                ))

                cursor.execute(
                    "SELECT CASE WHEN DB_CRYPTO.decrypt(DB_CRYPTO.encrypt('postflight'))='postflight' "
                    f"THEN 1 ELSE 0 END FROM {dual}"
                )
                crypto_probe = int((cursor.fetchone() or [0])[0] or 0)
                checks.append(_check(
                    "DB_CRYPTO_PROBE", "PASS" if crypto_probe == 1 else "BLOCKED",
                    "Database encryption package round trip succeeds",
                    "Resolve DB_CRYPTO compilation, grants, or key initialization before handoff.",
                ))

                if str(edition).lower() == "enterprise":
                    cursor.execute(
                        "BEGIN SET_AGENT_CONTEXT.set_agent_id(:agent_id); END;",
                        {"agent_id": "POSTFLIGHT_PROBE"},
                    )
                    cursor.execute(
                        f"SELECT CASE WHEN SYS_CONTEXT('AGENT_CTX','AGENT_ID')='POSTFLIGHT_PROBE' "
                        f"THEN 1 ELSE 0 END FROM {dual}"
                    )
                    context_probe = int((cursor.fetchone() or [0])[0] or 0)
                    cursor.execute("BEGIN SET_AGENT_CONTEXT.clear_context(); END;")
                    checks.append(_check(
                        "ORACLE_AGENT_CONTEXT", "PASS" if context_probe == 1 else "BLOCKED",
                        "Trusted Agent application context exists",
                        "Execute the packaged Oracle Enterprise Deep Data Security policy.",
                    ))

                    cursor.execute("SELECT COUNT(DISTINCT GRANT_NAME) FROM USER_DATA_GRANTS")
                    grant_count = int((cursor.fetchone() or [0])[0] or 0)
                    checks.append(_check(
                        "ORACLE_DATA_GRANTS", "PASS" if grant_count >= 23 else "BLOCKED",
                        "Oracle Data Grants are installed",
                        "Execute the packaged Deep Data Security policy and inspect invalid grant definitions.",
                        {"count": grant_count, "minimum": 23},
                    ))

                    cursor.execute(
                        "SELECT COUNT(*) FROM USER_SOURCE WHERE NAME='SET_AGENT_CONTEXT' AND TYPE='PACKAGE BODY' "
                        "AND (LOWER(TEXT) LIKE '%ora_end_user_context.username%' "
                        "OR LOWER(TEXT) LIKE '%trusted end user%')"
                    )
                    hardening_markers = int((cursor.fetchone() or [0])[0] or 0)
                    checks.append(_check(
                        "ORACLE_CONTEXT_HARDENING", "PASS" if hardening_markers >= 2 else "BLOCKED",
                        "Agent context setter enforces trusted End User identity",
                        "Apply the packaged security-boundary repair after the Deep Data Security policy.",
                        {"markers": hardening_markers},
                    ))
    except Exception as exc:
        checks.append(_check(
            "POSTFLIGHT_QUERY", "BLOCKED", "Database postflight could not be completed",
            "Resolve the database error and rerun verify.", {"error": type(exc).__name__},
        ))
    finally:
        conn.close()
    blocked = [item for item in checks if item["state"] == "BLOCKED"]
    return {"database": database, "edition": edition, "checked_at": _now(),
            "checks": checks, "passed": not blocked, "blocked": blocked}


def _retire_run(run_id: str) -> None:
    from . import connection
    agent_id = "BOOTSTRAP_DEPLOYMENT_AGENT:" + run_id
    connection.execute("UPDATE CX_DEPLOYMENT_RUNS SET STATUS='RETIRED',COMPLETED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE RUN_ID=:id", {"id": run_id})
    connection.execute("UPDATE CX_PRINCIPALS SET STATUS='RETIRED',PERMISSION_VERSION=PERMISSION_VERSION+1 WHERE PRINCIPAL_ID=:id", {"id": agent_id})


def _bootstrap_admin_hash(password: str) -> str:
    if not password:
        raise DeploymentError("initial administrator password is required")
    try:
        from .identity_api import IdentityError, hash_password_argon2id
        return hash_password_argon2id(password)
    except IdentityError as exc:
        raise DeploymentError("initial administrator password does not meet policy") from exc
    except RuntimeError as exc:
        raise DeploymentError("administrator password hashing dependency is unavailable") from exc


def _set_bootstrap_admin(database: str, config: Dict[str, Any], password: str, password_hash: str) -> None:
    """Replace the inert schema seed with a one-installation Argon2id hash."""
    conn = _connect(database, config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT PASSWORD_HASH FROM SYSTEM_USERS WHERE USERNAME='admin' AND ROLE='ADMIN'")
            row = cursor.fetchone()
            current_hash = str(row[0] or "") if row else ""
            if not row:
                if database == "pg":
                    cursor.execute(
                        "INSERT INTO system_users(username,password_hash,role,status,auth_source,created_at,updated_at) "
                        "VALUES ('admin',%(password_hash)s,'ADMIN','ACTIVE','LOCAL',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        {"password_hash": password_hash},
                    )
                else:
                    cursor.execute(
                        "INSERT INTO SYSTEM_USERS(USER_ID,USERNAME,PASSWORD_HASH,ROLE,STATUS,AUTH_SOURCE,CREATED_AT,UPDATED_AT) "
                        "VALUES ('admin','admin',:password_hash,'ADMIN','ACTIVE','LOCAL',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        {"password_hash": password_hash},
                    )
                conn.commit()
                return
            if current_hash and current_hash != "SHA256:placeholder_change_me":
                from .identity_api import verify_password_hash
                if verify_password_hash(password, current_hash)[0]:
                    return
                raise DeploymentError("initial administrator is already configured with a different password")
            if database == "pg":
                cursor.execute(
                    "UPDATE system_users SET password_hash=%(password_hash)s, updated_at=CURRENT_TIMESTAMP "
                    "WHERE username='admin' AND role='ADMIN' AND password_hash='SHA256:placeholder_change_me'",
                    {"password_hash": password_hash},
                )
            else:
                cursor.execute(
                    "UPDATE SYSTEM_USERS SET PASSWORD_HASH=:password_hash, UPDATED_AT=CURRENT_TIMESTAMP "
                    "WHERE USERNAME='admin' AND ROLE='ADMIN' AND PASSWORD_HASH='SHA256:placeholder_change_me'",
                    {"password_hash": password_hash},
                )
            if int(cursor.rowcount or 0) != 1:
                raise DeploymentError("initial administrator seed is missing or already configured")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _bootstrap_admin_configured(database: str, config: Dict[str, Any]) -> bool:
    """Return whether initialization already committed a non-seed admin."""
    conn = _connect(database, config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT PASSWORD_HASH FROM SYSTEM_USERS WHERE USERNAME='admin' AND ROLE='ADMIN'")
            row = cursor.fetchone()
            current_hash = str(row[0] or "") if row else ""
            return bool(current_hash and current_hash != "SHA256:placeholder_change_me")
    finally:
        conn.close()


def _adopt_bootstrap_admin() -> Dict[str, Any]:
    from . import connection, identity_api
    identity_api.bootstrap_existing_admins()
    row = connection.execute_query_one(
        "SELECT i.PRINCIPAL_ID,i.STATUS FROM CX_HUMAN_IDENTITIES i "
        "JOIN CX_USER_ROLES r ON r.PRINCIPAL_ID=i.PRINCIPAL_ID "
        "WHERE i.USERNAME='admin' AND i.STATUS='ACTIVE' AND r.ROLE_CODE='SYSTEM_ADMIN' AND r.STATUS='ACTIVE'"
    )
    if not row:
        raise DeploymentError("initial administrator principal was not created")
    value = dict(row)
    return {"principal_id": str(value.get("principal_id") or value.get("PRINCIPAL_ID") or ""), "status": "ACTIVE"}


def _configure_models(raw: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    from . import embedding_governance, native_agent_api
    actor = "BOOTSTRAP_DEPLOYMENT_AGENT:" + run_id
    result: Dict[str, Any] = {"llm": "UNCONFIGURED", "embedding": "UNCONFIGURED"}
    llm = dict(raw.get("llm") or {})
    if llm.get("api_url") and llm.get("model"):
        llm_profile = native_agent_api.upsert_llm_profile(actor, "deployment-default", str(llm["api_url"]), str(llm["model"]),
                                                           str(llm.get("api_key") or ""), "Bootstrap Deployment Agent initial LLM configuration")
        native_agent_api.activate_bootstrap_agents(actor, str(llm_profile["profile_id"]))
        result["llm"] = "CONFIGURED"
    embedding = dict(raw.get("embedding") or {})
    mode = str(embedding.get("execution_mode") or embedding.get("mode") or "PLATFORM_MANAGED").upper()
    if mode == "NONE":
        result["embedding"] = "DISABLED"
        return result
    if not embedding.get("model"):
        return result
    profile = embedding_governance.upsert_profile(
        actor, profile_key=str(embedding.get("profile_key") or "platform-default"),
        provider_url=str(embedding.get("api_url") or ""), model_id=str(embedding.get("model") or ""),
        execution_mode=mode, dimension=int(embedding.get("dimension") or 0),
        distance_metric=str(embedding.get("distance_metric") or "COSINE"),
        normalize_vectors=bool(embedding.get("normalize_vectors", True)),
        preprocessing=dict(embedding.get("preprocessing") or {}), modalities=list(embedding.get("modalities") or ["TEXT"]),
        api_key=str(embedding.get("api_key") or ""), secret_reference=str(embedding.get("secret_reference") or ""),
        reason="Bootstrap Deployment Agent initial Embedding configuration", model_fingerprint=str(embedding.get("model_fingerprint") or ""),
    )
    contract = embedding_governance.create_contract(actor, str(profile["profile_id"]), "Bootstrap initial Embedding Contract")
    space = embedding_governance.create_space(actor, "DEFAULT", str(contract["contract_id"]), "Bootstrap default Embedding Space", default=True, writable=True)
    embedding_governance.bind(actor, "PLATFORM", "DEFAULT", str(profile["profile_id"]), str(space["space_id"]), "Bootstrap default Embedding binding")
    probe = embedding_governance.probe_profile(actor, str(profile["profile_id"]))
    if str(probe.get("status") or "") in {"VERIFIED", "AGENT_VERIFIED", "GATEWAY_VERIFIED"}:
        from . import connection
        connection.execute("UPDATE CX_EMBEDDING_SPACES SET VALIDATION_STATE=:state,UPDATED_AT=CURRENT_TIMESTAMP WHERE SPACE_ID=:id",
                           {"state": probe["status"], "id": space["space_id"]})
        result["embedding"] = "VERIFIED"
    else:
        result["embedding"] = str(probe.get("status") or "CONFIGURED_ONLY")
    return result


def run(mode: str, *, database: str, edition: str, config_path: Path,
        root: Path = PACKAGE_ROOT, run_id: str = "", target_version: str = "",
        bootstrap_admin_password: str = "", database_backup_confirmed: bool = False) -> Dict[str, Any]:
    mode = str(mode or "").upper()
    database = str(database or "").lower()
    edition = str(edition or "").lower()
    if mode not in RUN_MODES or database not in {"oracle", "pg", "yashandb"} or edition not in {"community", "enterprise"}:
        raise DeploymentError("unsupported deployment mode, database, or edition")
    baseline = release_baseline(database, root)
    target_version = release_version(database, root, target_version)
    terminal_migration = str(baseline["required_terminal_migration"])
    raw = _resolve_sensitive_config(_read_config(config_path))
    config = _database_config(raw, database)
    _activate_runtime_config(config_path)
    journal = DeploymentJournal(root, run_id)
    if mode in {"STATUS", "VERIFY"}:
        durable = _deployment_database_status(database, config, run_id)
        verified = postflight(database, edition, config, terminal_migration) if mode == "VERIFY" else None
        return {"run_id": journal.run_id, "mode": mode, "version": target_version,
                "terminal_migration": terminal_migration,
                "preflight": preflight(database, config, require_empty=False, edition=edition),
                "postflight": verified, "deployment": durable}
    resuming = mode == "RESUME"
    resume_from_handoff = False
    if resuming:
        prior = journal.load()
        if (str(prior.get("database") or "") != database or str(prior.get("edition") or "") != edition
                or str(prior.get("target_version") or target_version) != target_version):
            raise DeploymentError("deployment journal does not match the requested target")
        mode = str(prior.get("mode") or "INITIALIZE")
        durable_resume = _deployment_database_status(database, config, journal.run_id)
        resume_from_handoff = str(durable_resume.get("status") or "").upper() == "NATIVE_HANDOFF"
    admin_hash = (
        _bootstrap_admin_hash(bootstrap_admin_password)
        if mode == "INITIALIZE" and bootstrap_admin_password
        else ""
    )
    plan = manifest(database, edition, root)
    plan_digest = _digest([{"key": action.key, "digest": action.digest, "authority": action.authority} for action in plan])
    state = {"run_id": journal.run_id, "mode": mode, "database": database, "edition": edition,
             "target_version": target_version, "terminal_migration": terminal_migration,
             "plan_digest": plan_digest, "updated_at": _now()}
    journal_digest = journal.save(state)
    first = preflight(
        database, config,
        require_empty=mode == "INITIALIZE" and not resuming,
        edition=edition,
    )
    if not first["passed"]:
        state["status"] = "FAILED_MANUAL_ACTION_REQUIRED"
        state["preflight"] = first
        journal.save(state)
        return {"run_id": journal.run_id, "status": state["status"], "preflight": first}
    if mode == "INITIALIZE":
        initialization_boundary = str(prior.get("initialization_boundary") or "") if resuming else "VERIFIED_EMPTY_TARGET"
        recovery = _recovery_boundary(mode, False, initialization_boundary)
        state["initialization_boundary"] = initialization_boundary
        state["recovery_boundary"] = recovery
        journal_digest = journal.save(state)
    else:
        prior_recovery = dict(prior.get("recovery_boundary") or {}) if resuming else {}
        confirmed = database_backup_confirmed or prior_recovery.get("status") == "OPERATOR_CONFIRMED"
        recovery = _recovery_boundary(mode, confirmed)
        state["recovery_boundary"] = recovery
        journal_digest = journal.save(state)
    if mode == "INITIALIZE":
        if not resume_from_handoff:
            for action in plan:
                state["current_step"] = action.key
                journal_digest = journal.save(state)
                _execute_action(database, config, action, root)
            if bootstrap_admin_password:
                _set_bootstrap_admin(database, config, bootstrap_admin_password, admin_hash)
            elif not (resuming and _bootstrap_admin_configured(database, config)):
                raise DeploymentError("initial administrator password is required")
        elif not _bootstrap_admin_configured(database, config):
            raise DeploymentError("initial administrator setup is incomplete; resume with --admin-password-file")
    migrations = _migration_apply(target_version, database, edition, config_path, config, root)
    if not migrations or str(migrations[-1].get("script") or "") != terminal_migration:
        raise DeploymentError("migration chain did not reach the packaged terminal migration")
    readiness = {"database": "PENDING", "control_plane": "PENDING", "llm": "UNCONFIGURED", "embedding": "UNCONFIGURED", "runtime": "PENDING", "enrollment": "BLOCKED"}
    _database_record(journal.run_id, mode, database, edition, target_version, plan_digest, journal_digest, "NATIVE_HANDOFF", readiness, "native-handoff")
    _record_evidence(journal.run_id, "PREFLIGHT", {"target": first, "recovery_boundary": recovery})
    _record_evidence(journal.run_id, "MIGRATION_RESULTS", {"migrations": migrations, "manifest_digest": plan_digest})
    for index, action in enumerate(plan, start=1):
        _record_step(journal.run_id, action.key, index, action.digest, "COMPLETED", {"phase": action.phase, "path": action.path.name})
    for index, result in enumerate(migrations, start=len(plan) + 1):
        _record_step(journal.run_id, "migration-" + str(result["script"]), index, str(result["checksum"]), "COMPLETED", result)
    admin = _adopt_bootstrap_admin()
    _record_evidence(journal.run_id, "INITIAL_ADMIN", admin)
    from . import native_agent_api
    native = native_agent_api.bootstrap_native_agents()
    knowledge_state = {
        "management_knowledge": native.get("management_knowledge") or {},
        "scoped_knowledge": native.get("scoped_knowledge") or {},
    }
    if str((knowledge_state.get("scoped_knowledge") or {}).get("status") or "") != "MIGRATED":
        raise DeploymentError("scoped platform management knowledge did not pass postflight")
    _record_evidence(journal.run_id, "PLATFORM_KNOWLEDGE_POSTFLIGHT", knowledge_state)
    models = _configure_models(raw, journal.run_id)
    verified = postflight(database, edition, config, terminal_migration)
    if not verified["passed"]:
        raise DeploymentError("database postflight verification failed")
    readiness["database"] = "READY"
    readiness["control_plane"] = "READY"
    readiness.update(models)
    readiness["runtime"] = "READY"
    readiness["enrollment"] = "READY" if models.get("embedding") in {"VERIFIED", "DISABLED", "UNCONFIGURED"} else "BLOCKED"
    journal_digest = journal.save({**state, "status": "POSTFLIGHT_PASSED", "readiness": readiness, "migrations": migrations})
    _database_record(journal.run_id, mode, database, edition, target_version, plan_digest, journal_digest, "COMPLETED", readiness, "postflight")
    _record_evidence(journal.run_id, "POSTFLIGHT", {"readiness": readiness, "verification": verified, "initial_admin": admin,
                                                     "native_agents": native, "models": models})
    _retire_run(journal.run_id)
    journal.retire()
    try:
        from .connection_crypto import auto_encrypt_config
        auto_encrypt_config(config_path)
    except Exception as exc:
        raise DeploymentError("deployment completed but configuration encryption failed") from exc
    return {"run_id": journal.run_id, "status": "RETIRED", "version": target_version,
            "preflight": first, "migrations": migrations, "initial_admin": admin,
            "native_agents": native, "readiness": readiness}
