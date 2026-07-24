#!/usr/bin/env python3.14
"""Non-destructive POC readiness checks for the three supported databases.

The checker records only configuration metadata, capability counts, driver
availability, and exception types.  It never writes to a database and never
places credentials, DSNs, or connection error text in the report.
"""

from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
import platform
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_DATABASES = ("oracle", "pg", "yashandb")
CORE_TABLES = (
    "ENTITIES", "AGENT_REGISTRY", "WORKSPACES", "TASK_PLANS", "TASK_STEPS",
    "SKILL_META", "LOOP_RUNS", "SYSTEM_CONFIG",
)
V401_TABLES = (
    "EXECUTION_JOBS", "EXECUTION_ATTEMPTS", "EXECUTION_POLICIES",
    "EXECUTION_ARTIFACTS", "EXECUTION_AUDIT", "EVENT_DEAD_LETTER",
    "DAG_EXECUTION_LOG", "ALERT_RULES",
)
REGISTRATION_TABLES = ("AGENT_REGISTRATIONS",)
GOVERNANCE_TABLES = (
    "GOV_RESOURCES", "GOV_POLICIES", "GOV_GRANTS", "GOV_DECISIONS",
    "GOV_APPROVAL_REQUESTS", "GOV_APPROVAL_DECISIONS", "GOV_EMERGENCY_OPS",
    "GOV_EMERGENCY_STEPS", "GOV_AUDIT_EVENTS", "GOV_AUDIT_RETENTION",
    "GOV_LEGAL_HOLDS", "GOV_EVIDENCE_EXPORTS",
)

DATABASE_FIELDS = {
    "oracle": ("user", "password", "dsn"),
    # PostgreSQL may intentionally omit password when peer, trust, or a
    # restrictive .pgpass/driver authentication path is configured.
    "pg": ("user", "host", "port", "dbname"),
    "yashandb": ("user", "password", "dsn"),
}
DRIVER_MODULES = {"oracle": "oracledb", "pg": "psycopg2", "yashandb": "yaspy"}


def _version() -> str:
    root = Path(__file__).resolve().parent
    for version_file in (root / "VERSION", root.parent / "VERSION"):
        if version_file.exists():
            return version_file.read_text(encoding="ascii").strip()
    for manifest in (root / "build-manifest.json", root.parent / "build-manifest.json"):
        if manifest.exists():
            try:
                return str(json.loads(manifest.read_text(encoding="ascii")).get("version") or "unknown")
            except (OSError, ValueError):
                pass
    return "unknown"


def _safe_error(exc: BaseException) -> str:
    return type(exc).__name__


def _master_key() -> bytes:
    env_key = os.environ.get("MASTER_DB_KEY")
    if env_key:
        try:
            raw = base64.b64decode(env_key, validate=True)
        except Exception:
            raw = env_key.encode("utf-8")
        if len(raw) >= 16:
            return raw[:32].ljust(32, b"\x00")
    for path in (
        Path.home() / ".ai-agent-infra" / "master.key",
        Path.home() / ".oracle-infra" / "master.key",
    ):
        if path.exists():
            raw = base64.b64decode(path.read_text(encoding="ascii").strip())
            if len(raw) >= 16:
                return raw[:32].ljust(32, b"\x00")
    raise RuntimeError("MasterKeyMissing")


def _decrypt_section(blob: str) -> dict[str, Any]:
    try:
        from lib.connection_crypto import decrypt_section
    except ImportError:
        from shared.lib.connection_crypto import decrypt_section
    return dict(decrypt_section(blob, _master_key()))


def _load_config(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ConfigObjectRequired")
    section = dict(raw.get("database") or {})
    encrypted = bool(section.get("_encrypted"))
    if encrypted:
        resolved = _decrypt_section(str(section["_encrypted"]))
        resolved.update({key: value for key, value in section.items() if key not in {"_encrypted", "_key_source"}})
        section = resolved
    return raw, section, {"encrypted": encrypted, "top_level_keys": sorted(raw), "database_keys": sorted(section)}


def _scalar(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def _query(conn: Any, sql: str, params: Any = None) -> list[Any]:
    with conn.cursor() as cursor:
        cursor.execute(sql, params or {})
        return list(cursor.fetchall())


def _connect(database: str, config: dict[str, Any]) -> Any:
    if database == "oracle":
        module = importlib.import_module("oracledb")
        return module.connect(
            user=config["user"], password=config["password"], dsn=config["dsn"],
            tcp_connect_timeout=8,
        )
    if database == "pg":
        module = importlib.import_module("psycopg2")
        connect_args = {
            "user": config["user"], "host": config["host"],
            "port": int(config["port"]), "dbname": config["dbname"],
            "connect_timeout": 8,
        }
        if config.get("password"):
            connect_args["password"] = config["password"]
        return module.connect(**connect_args)
    module = importlib.import_module("yaspy")
    return module.Connection(
        user=config["user"], password=config["password"], dsn=config["dsn"],
    )


def _capabilities(database: str, conn: Any, enterprise: bool) -> dict[str, Any]:
    if database == "pg":
        table_rows = _query(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        present = {str(_scalar(row)).upper() for row in table_rows}
        skill_rows = _query(
            conn,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'skill_meta'",
        )
        skill_columns = {str(_scalar(row)).upper() for row in skill_rows}
    else:
        table_rows = _query(conn, "SELECT table_name FROM user_tables")
        present = {str(_scalar(row)).upper() for row in table_rows}
        skill_rows = _query(conn, "SELECT column_name FROM user_tab_columns WHERE table_name = 'SKILL_META'")
        skill_columns = {str(_scalar(row)).upper() for row in skill_rows}

    required = list(CORE_TABLES + V401_TABLES + REGISTRATION_TABLES)
    if enterprise:
        required.extend(GOVERNANCE_TABLES)
    missing = sorted(set(required) - present)
    return {
        "core_tables_present": len(present.intersection(CORE_TABLES)),
        "core_tables_required": len(CORE_TABLES),
        "v401_tables_present": len(present.intersection(V401_TABLES)),
        "v401_tables_required": len(V401_TABLES),
        "registration_tables_present": len(present.intersection(REGISTRATION_TABLES)),
        "registration_tables_required": len(REGISTRATION_TABLES),
        "governance_tables_present": len(present.intersection(GOVERNANCE_TABLES)),
        "governance_tables_required": len(GOVERNANCE_TABLES) if enterprise else 0,
        "missing_tables": missing,
        "skill_entity_contract": {"ENTITY_ID", "ENTITY_TYPE", "SKILL_NAME"} <= skill_columns,
    }


def check_target(database: str, config_path: Path | None, enterprise: bool = True) -> dict[str, Any]:
    """Return a sanitized, non-destructive readiness result for one target."""
    result: dict[str, Any] = {
        "database": database,
        "config": {"present": False, "encrypted": False, "mode": None, "fields_present": {}},
        "runtime": {
            "python": platform.python_version(),
            "python_required": "3.14+",
            "python_ok": sys.version_info[:2] >= (3, 14),
            "driver": DRIVER_MODULES[database],
            "driver_available": False,
        },
        "connection": {"attempted": False, "connected": False, "product": "", "version": ""},
        "capabilities": {},
        "ready": False,
        "remediation": [],
    }
    if config_path is None or not config_path.exists():
        result["remediation"].append("Provide a readable database config for this target.")
        return result

    result["config"]["present"] = True
    try:
        mode = stat.S_IMODE(config_path.stat().st_mode)
        result["config"]["mode"] = oct(mode)
        if mode & 0o077:
            result["remediation"].append("Restrict the runtime config to owner-only permissions (0600).")
        _, config, metadata = _load_config(config_path)
        result["config"]["encrypted"] = metadata["encrypted"]
        result["config"]["fields_present"] = {
            field: bool(config.get(field)) for field in DATABASE_FIELDS[database]
        }
        missing_fields = [field for field in DATABASE_FIELDS[database] if not config.get(field)]
        if missing_fields:
            result["remediation"].append("Provide all required database config fields: " + ", ".join(missing_fields) + ".")
    except Exception as exc:
        result["remediation"].append("Read and decrypt the database config with the active master key.")
        result["config"]["error_type"] = _safe_error(exc)
        return result

    try:
        importlib.import_module(DRIVER_MODULES[database])
        result["runtime"]["driver_available"] = True
    except Exception as exc:
        result["runtime"]["driver_error_type"] = _safe_error(exc)
        result["remediation"].append("Install the bundled database driver before the POC.")

    if not result["runtime"]["python_ok"]:
        result["remediation"].append("Run the POC with Linuxbrew Python 3.14 or newer.")
    if not result["config"]["fields_present"] or not all(result["config"]["fields_present"].values()):
        return result
    if not result["runtime"]["driver_available"]:
        return result

    conn = None
    result["connection"]["attempted"] = True
    try:
        conn = _connect(database, config)
        result["connection"]["connected"] = True
        if database == "pg":
            version = _scalar(_query(conn, "SELECT version()")[0])
            result["connection"]["product"] = "PostgreSQL"
        else:
            version = _scalar(_query(conn, "SELECT banner FROM v$version FETCH FIRST 1 ROW ONLY")[0])
            result["connection"]["product"] = "Oracle AI Database" if database == "oracle" else "YashanDB"
        result["connection"]["version"] = str(version or "")[:80]
        result["capabilities"] = _capabilities(database, conn, enterprise)
        if result["capabilities"]["missing_tables"]:
            result["remediation"].append("Apply the v4.1.0 schema and governance migrations before accepting POC traffic.")
        if not result["capabilities"]["skill_entity_contract"]:
            result["remediation"].append("Deploy the SKILL_META Entity contract required by the Skill runtime.")
    except Exception as exc:
        result["connection"]["error_type"] = _safe_error(exc)
        result["remediation"].append("Verify database reachability, credentials, and the required v4.1.0 objects.")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    capabilities = result["capabilities"]
    result["ready"] = (
        result["config"]["present"]
        and not (result["config"]["mode"] and int(result["config"]["mode"], 8) & 0o077)
        and result["runtime"]["python_ok"]
        and result["runtime"]["driver_available"]
        and result["connection"]["connected"]
        and not capabilities.get("missing_tables")
        and capabilities.get("skill_entity_contract") is True
        and not result["remediation"]
    )
    return result


def build_report(configs: dict[str, Path | None], enterprise: bool = True) -> dict[str, Any]:
    results = [check_target(database, configs.get(database), enterprise) for database in SUPPORTED_DATABASES]
    return {
        "schema": "ai-agent-infra-poc-readiness/v1",
        "version": _version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "edition": "Enterprise" if enterprise else "Community",
        "non_destructive": True,
        "results": results,
        "passed": all(item["ready"] for item in results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run non-destructive v4.1.0 POC readiness checks.")
    parser.add_argument("--oracle-config", type=Path)
    parser.add_argument("--pg-config", type=Path)
    parser.add_argument("--yashandb-config", type=Path)
    parser.add_argument("--edition", choices=("community", "enterprise"), default="enterprise")
    parser.add_argument("--output", type=Path, default=Path("poc-readiness.json"))
    args = parser.parse_args(argv)
    payload = build_report(
        {"oracle": args.oracle_config, "pg": args.pg_config, "yashandb": args.yashandb_config},
        enterprise=args.edition == "enterprise",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print(json.dumps({"output": str(args.output), "passed": payload["passed"]}, ensure_ascii=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
