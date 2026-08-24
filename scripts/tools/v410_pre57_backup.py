#!/usr/bin/env python3.14
"""Create a verifiable logical recovery point for additive migration 57."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_db_validator import _load_database_config
from migration_runner import _connect_for_preflight, verify_backup_evidence


NEW_TABLES = (
    "CX_MODEL_QUOTA_POLICIES", "CX_MODEL_QUOTA_RESERVATIONS", "CX_MODEL_REPLAY_SNAPSHOTS",
    "CX_PROVIDER_INVOICE_BATCHES", "CX_PROVIDER_INVOICE_LINES", "CX_PROVIDER_INVOICE_CORRECTIONS",
    "CX_MODEL_RECONCILIATIONS", "CX_MODEL_ALLOCATION_RULES", "CX_MODEL_ALLOCATIONS",
    "CX_MODEL_EVIDENCE_ADAPTERS", "CX_MODEL_EVIDENCE_BATCHES", "CX_WALLBOARD_DEF_VERSIONS",
    "CX_WALLBOARD_PUBLICATIONS",
)
CAPABILITIES = ("model_finance", "external_model_evidence")


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "byte_count": len(value)}
    if hasattr(value, "read"):
        return _json_value(value.read())
    return value


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(item[0]).lower() for item in cursor.description or ()]
    return [{columns[index]: _json_value(value) for index, value in enumerate(row)} for row in cursor.fetchall()]


def _query(cursor: Any, database: str, sql_pg: str, sql_oracle: str, params_pg=(), params_oracle=None) -> list[dict[str, Any]]:
    cursor.execute(sql_pg, params_pg) if database == "pg" else cursor.execute(sql_oracle, params_oracle or {})
    return _rows(cursor)


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _rollback_sql(database: str, snapshot: dict[str, Any]) -> str:
    absent_caps = [key for key in CAPABILITIES if not any(str(row.get("capability_key")) == key for row in snapshot["capabilities"])]
    existing_columns = set(snapshot["model_request_columns"])
    lines = ["-- Generated recovery procedure for v4.4.10 migration 57.", "-- Stop all v4.4.10 services before execution. New migration-57 data will be removed."]
    if database == "pg":
        lines.extend(["BEGIN;"])
        lines.extend(f"DROP TABLE IF EXISTS {table.lower()} CASCADE;" for table in reversed(NEW_TABLES))
        if "CORRELATION_ID" not in existing_columns:
            lines.append("ALTER TABLE cx_model_requests DROP COLUMN IF EXISTS correlation_id;")
        if "CREDENTIAL_ID" not in existing_columns:
            lines.append("ALTER TABLE cx_model_requests DROP COLUMN IF EXISTS credential_id;")
        if absent_caps:
            literals = ",".join(_sql_literal(item) for item in absent_caps)
            lines.append(f"DELETE FROM cx_platform_capabilities WHERE capability_key IN ({literals});")
        lines.append("DELETE FROM ai_schema_migration_steps WHERE version='4.4.10' AND step_name='57_v4_4_10_complete_model_governance';")
        ledger = snapshot["migration_ledger"]
        if ledger:
            checksum = _sql_literal(str(ledger[0]["checksum"]))
            lines.append(f"INSERT INTO ai_schema_migrations(version,checksum) VALUES ('4.4.10',{checksum}) ON CONFLICT(version) DO UPDATE SET checksum=EXCLUDED.checksum;")
        else:
            lines.append("DELETE FROM ai_schema_migrations WHERE version='4.4.10';")
        lines.append("COMMIT;")
        return "\n".join(lines) + "\n"

    for table in reversed(NEW_TABLES):
        lines.extend([
            "DECLARE n NUMBER; BEGIN",
            f" SELECT COUNT(*) INTO n FROM USER_TABLES WHERE TABLE_NAME='{table}';",
            f" IF n>0 THEN EXECUTE IMMEDIATE 'DROP TABLE {table} CASCADE CONSTRAINTS'; END IF;",
            "END;", "/",
        ])
    for column in ("CORRELATION_ID", "CREDENTIAL_ID"):
        if column not in existing_columns:
            lines.extend([
                "DECLARE n NUMBER; BEGIN",
                f" SELECT COUNT(*) INTO n FROM USER_TAB_COLUMNS WHERE TABLE_NAME='CX_MODEL_REQUESTS' AND COLUMN_NAME='{column}';",
                f" IF n>0 THEN EXECUTE IMMEDIATE 'ALTER TABLE CX_MODEL_REQUESTS DROP COLUMN {column}'; END IF;",
                "END;", "/",
            ])
    if absent_caps:
        literals = ",".join(_sql_literal(item) for item in absent_caps)
        lines.append(f"DELETE FROM CX_PLATFORM_CAPABILITIES WHERE CAPABILITY_KEY IN ({literals});")
    lines.append("DELETE FROM AI_SCHEMA_MIGRATION_STEPS WHERE VERSION='4.4.10' AND STEP_NAME='57_v4_4_10_complete_model_governance';")
    ledger = snapshot["migration_ledger"]
    if ledger:
        checksum = _sql_literal(str(ledger[0]["checksum"]))
        lines.append(f"MERGE INTO AI_SCHEMA_MIGRATIONS d USING (SELECT '4.4.10' VERSION,{checksum} CHECKSUM FROM DUAL) s ON (d.VERSION=s.VERSION) WHEN MATCHED THEN UPDATE SET d.CHECKSUM=s.CHECKSUM WHEN NOT MATCHED THEN INSERT(VERSION,CHECKSUM) VALUES(s.VERSION,s.CHECKSUM);")
    else:
        lines.append("DELETE FROM AI_SCHEMA_MIGRATIONS WHERE VERSION='4.4.10';")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def create_backup(database: str, config_path: Path, output_root: Path) -> Path:
    output = output_root.resolve() / database
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    config = _load_database_config(config_path)
    connection = _connect_for_preflight(database, config)
    try:
        with connection.cursor() as cursor:
            tables = _query(cursor, database,
                "SELECT upper(table_name) table_name FROM information_schema.tables WHERE table_schema=current_schema() ORDER BY table_name",
                "SELECT TABLE_NAME FROM USER_TABLES ORDER BY TABLE_NAME")
            table_names = {str(row["table_name"]).upper() for row in tables}
            columns = _query(cursor, database,
                "SELECT upper(table_name) table_name,upper(column_name) column_name,data_type,ordinal_position FROM information_schema.columns WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position",
                "SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_ID AS ORDINAL_POSITION FROM USER_TAB_COLUMNS ORDER BY TABLE_NAME,COLUMN_ID")
            indexes = _query(cursor, database,
                "SELECT upper(tablename) table_name,upper(indexname) index_name,indexdef FROM pg_indexes WHERE schemaname=current_schema() ORDER BY tablename,indexname",
                "SELECT TABLE_NAME,INDEX_NAME,UNIQUENESS FROM USER_INDEXES ORDER BY TABLE_NAME,INDEX_NAME")
            capabilities = _query(cursor, database,
                "SELECT capability_key,mandatory,enabled,version,updated_by,update_reason FROM cx_platform_capabilities WHERE capability_key IN (%s,%s) ORDER BY capability_key",
                "SELECT CAPABILITY_KEY,MANDATORY,ENABLED,VERSION,UPDATED_BY,UPDATE_REASON FROM CX_PLATFORM_CAPABILITIES WHERE CAPABILITY_KEY IN (:a,:b) ORDER BY CAPABILITY_KEY",
                CAPABILITIES, {"a": CAPABILITIES[0], "b": CAPABILITIES[1]})
            ledger = _query(cursor, database,
                "SELECT version,checksum,applied_at FROM ai_schema_migrations WHERE version=%s",
                "SELECT VERSION,CHECKSUM,APPLIED_AT FROM AI_SCHEMA_MIGRATIONS WHERE VERSION=:version",
                ("4.4.10",), {"version": "4.4.10"}) if "AI_SCHEMA_MIGRATIONS" in table_names else []
            steps = _query(cursor, database,
                "SELECT version,step_name,checksum,status,statements_executed,failed_statement FROM ai_schema_migration_steps WHERE version=%s ORDER BY step_name",
                "SELECT VERSION,STEP_NAME,CHECKSUM,STATUS,STATEMENTS_EXECUTED,FAILED_STATEMENT FROM AI_SCHEMA_MIGRATION_STEPS WHERE VERSION=:version ORDER BY STEP_NAME",
                ("4.4.10",), {"version": "4.4.10"}) if "AI_SCHEMA_MIGRATION_STEPS" in table_names else []
            request_count = _query(cursor, database,
                "SELECT COUNT(*) row_count FROM cx_model_requests",
                "SELECT COUNT(*) ROW_COUNT FROM CX_MODEL_REQUESTS")
    finally:
        connection.close()

    existing_new = sorted(set(NEW_TABLES) & table_names)
    if existing_new:
        raise RuntimeError(f"migration 57 objects already exist: {', '.join(existing_new)}")
    request_columns = sorted(str(row["column_name"]).upper() for row in columns if str(row["table_name"]).upper() == "CX_MODEL_REQUESTS")
    snapshot = {
        "schema": "ai-agent-infra-v410-pre57-logical-snapshot/v1", "database": database,
        "created_at": datetime.now(timezone.utc).isoformat(), "source_config": str(config_path.resolve()),
        "table_catalog": tables, "column_catalog": columns, "index_catalog": indexes,
        "catalog_sha256": hashlib.sha256(json.dumps({"tables": tables, "columns": columns, "indexes": indexes}, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "model_request_columns": request_columns, "model_request_row_count": int(request_count[0]["row_count"]),
        "capabilities": capabilities, "migration_ledger": ledger, "migration_steps": steps,
    }
    snapshot_path = output / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    rollback_path = output / "rollback.sql"
    rollback_path.write_text(_rollback_sql(database, snapshot), encoding="utf-8")
    restore_path = output / "RESTORE.md"
    restore_path.write_text(
        "# Migration 57 recovery\n\nStop v4.4.10 services, verify the database identity, execute `rollback.sql` with the schema-owner account, then run the v4.4.9 live validator. The rollback removes all post-migration-57 governance data and restores the recorded migration ledger boundary.\n",
        encoding="utf-8",
    )
    for path in (snapshot_path, rollback_path, restore_path):
        os.chmod(path, 0o600)
    artifacts = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (snapshot_path, rollback_path, restore_path)}
    evidence = {
        "schema": "ai-agent-infra-backup-evidence/v1", "database": database,
        "created_at": snapshot["created_at"], "backup_ref": str(output), "recoverable": True,
        "scope": "v4.4.10 additive migration 57 logical boundary", "artifacts": artifacts,
    }
    evidence["manifest_sha256"] = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    evidence_path = output / "backup-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    os.chmod(evidence_path, 0o600)
    verified, message = verify_backup_evidence(evidence_path)
    if not verified:
        raise RuntimeError(f"generated evidence failed verification: {message}")
    return evidence_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, choices=("oracle", "pg", "yashandb"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    print(create_backup(args.database, args.config, args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
