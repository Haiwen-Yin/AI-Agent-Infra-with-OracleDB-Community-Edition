#!/usr/bin/env python3.14
"""Apply versioned migrations using encrypted local connection configs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from live_db_validator import (
    REPO_ROOT,
    V43_MIGRATION_SCRIPTS,
    V431_MIGRATION_SCRIPTS,
    V432_MIGRATION_SCRIPTS,
    V433_MIGRATION_SCRIPTS,
    V434_MIGRATION_SCRIPTS,
    V435_MIGRATION_SCRIPTS,
    V436_MIGRATION_SCRIPTS,
    V431_ORGANIZATION_REQUIRED_COLUMNS,
    V431_ORGANIZATION_TABLES,
    V432_MEMORY_TABLES,
    V432_MEMORY_REQUIRED_COLUMNS,
    V433_GRAPH_ASSURANCE_TABLES,
    V435_PLATFORM_TABLES,
    V435_PLATFORM_REQUIRED_COLUMNS,
    V436_NATIVE_AGENT_TABLES,
    V436_NATIVE_AGENT_REQUIRED_COLUMNS,
    V437_MIGRATION_SCRIPTS,
    V437_BOOTSTRAP_TABLES,
    V437_BOOTSTRAP_REQUIRED_COLUMNS,
    V440_MIGRATION_SCRIPTS,
    V440_SDD_TABLES,
    V440_SDD_REQUIRED_COLUMNS,
    V441_MIGRATION_SCRIPTS,
    V441_ADMIN_HA_TABLES,
    V441_ADMIN_HA_REQUIRED_COLUMNS,
    V442_MIGRATION_SCRIPTS,
    V442_GRAPH_OPERATIONS_TABLES,
    V442_GRAPH_OPERATIONS_REQUIRED_COLUMNS,
    V443_MIGRATION_SCRIPTS,
    V443_SECURITY_DOMAIN_TABLES,
    V443_SECURITY_DOMAIN_REQUIRED_COLUMNS,
    _load_database_config,
    validate_v43_static_contract,
    validate_v431_static_contract,
    validate_v432_static_contract,
    validate_v433_static_contract,
    validate_v434_static_contract,
    validate_v435_static_contract,
    validate_v436_static_contract,
    validate_v437_static_contract,
    validate_v440_static_contract,
    validate_v441_static_contract,
    validate_v442_static_contract,
    validate_v443_static_contract,
)


@dataclass
class MigrationResult:
    database: str
    passed: bool
    script: str = ""
    mode: str = "apply"
    statements_executed: int = 0
    existing_objects_skipped: int = 0
    error_type: str = ""
    error_code: str = ""
    error_object: str = ""
    failed_statement: int = 0
    checksum: str = ""
    ledger_status: str = ""
    backup_verified: bool = False
    capacity: dict[str, Any] | None = None
    warnings: list[str] | None = None
    step_statuses: list[dict[str, Any]] | None = None


MIGRATION_VERSION = "4.1.0"
MIGRATION_EDITION = "community"
GRAPH_MIGRATION_VERSIONS = frozenset({"4.2.0", "4.2.1"})
CHANNEL_MIGRATION_VERSIONS = frozenset({"4.3.0"})
ORGANIZATION_MIGRATION_VERSIONS = frozenset({"4.3.1"})
MEMORY_LIFECYCLE_MIGRATION_VERSIONS = frozenset({"4.3.2"})
GRAPH_ASSURANCE_MIGRATION_VERSIONS = frozenset({"4.3.3"})
COMPLIANCE_MIGRATION_VERSIONS = frozenset({"4.3.4"})
PLATFORM_CAPABILITY_MIGRATION_VERSIONS = frozenset({"4.3.5"})
NATIVE_AGENT_MIGRATION_VERSIONS = frozenset({"4.3.6"})
BOOTSTRAP_EMBEDDING_MIGRATION_VERSIONS = frozenset({"4.3.7"})
NATIVE_SDD_MIGRATION_VERSIONS = frozenset({"4.4.0"})
ADMIN_HA_MIGRATION_VERSIONS = frozenset({"4.4.1"})
GRAPH_OPERATIONS_MIGRATION_VERSIONS = frozenset({"4.4.2"})
SECURITY_DOMAIN_BINDING_MIGRATION_VERSIONS = frozenset({"4.4.3"})
JOURNALED_MIGRATION_VERSIONS = (
    GRAPH_MIGRATION_VERSIONS | CHANNEL_MIGRATION_VERSIONS | ORGANIZATION_MIGRATION_VERSIONS | MEMORY_LIFECYCLE_MIGRATION_VERSIONS | GRAPH_ASSURANCE_MIGRATION_VERSIONS | COMPLIANCE_MIGRATION_VERSIONS | PLATFORM_CAPABILITY_MIGRATION_VERSIONS | NATIVE_AGENT_MIGRATION_VERSIONS | BOOTSTRAP_EMBEDDING_MIGRATION_VERSIONS | NATIVE_SDD_MIGRATION_VERSIONS | ADMIN_HA_MIGRATION_VERSIONS | GRAPH_OPERATIONS_MIGRATION_VERSIONS | SECURITY_DOMAIN_BINDING_MIGRATION_VERSIONS
)

# v4.4.1 was exercised against the retained PostgreSQL and YashanDB test
# baselines while its additive script was still being finalized.  These are
# the only two recorded development checksums that may be adopted.  Adoption
# is still conditional on a complete live v4.4.1 schema, so an arbitrary
# changed migration can never bypass the ledger.
LEGACY_V441_STEP_CHECKSUMS = {
    "pg": {"35_v4_4_1_admin_ha_upgrade": frozenset({
        "91a00214f10d65d2bcf5f570143147b2e100bee36f8ac0890b3c746e007f53dd",
    })},
    "yashandb": {"35_v4_4_1_admin_ha_upgrade": frozenset({
        "a9ff7debaa665f838b696558bac29dd151f0c9d2542efa875c5bab843741b304",
    })},
}

# v4.4.2 was applied to the retained Oracle and YashanDB ENT baselines before
# the final release runner checksum was recorded.  These are the only
# historical checksums accepted for step 37, and adoption still requires the
# complete v4.4.2 object/column contract below.  This preserves tamper
# detection while allowing a verified, already-complete test baseline to be
# revalidated.
LEGACY_V442_STEP_CHECKSUMS = {
    "oracle": {"37_v4_4_2_embedding_graph_operations": frozenset({
        "c1e92386326e9dbb7cd58a4e43d6f479c1ae4dd19696bd58679168ef3907c3f2",
    })},
    "yashandb": {"37_v4_4_2_embedding_graph_operations": frozenset({
        "c1e92386326e9dbb7cd58a4e43d6f479c1ae4dd19696bd58679168ef3907c3f2",
    })},
}

V434_COMPLIANCE_TABLES = frozenset({
    "CX_AGENT_PROFILES", "CX_AGENT_PROFILE_VERSIONS", "CX_AGENT_PROFILE_ASSIGNMENTS",
    "CX_AGENT_ACTIVATIONS", "CX_AGENT_POSTURES", "CX_AGENT_POSTURE_EVIDENCE",
    "CX_COMPLIANCE_FINDINGS", "CX_COMPLIANCE_REMEDIATION_CASES",
    "CX_COMPLIANCE_EXCEPTIONS", "CX_COMPLIANCE_CONTROLLER_JOBS",
})

CHANNEL_REQUIRED_TABLES = frozenset({
    "CX_PRINCIPALS", "CX_HUMAN_IDENTITIES", "CX_REGISTRATION_REQUESTS", "CX_WEB_SESSIONS",
    "CX_ROLE_TEMPLATES", "CX_USER_ROLES", "CX_USER_PERMISSION_OVERRIDES", "CX_ORGANIZATIONS",
    "CX_ORGANIZATION_MEMBERS", "CX_SECURITY_DOMAINS", "CX_DOMAIN_MEMBERS", "CX_ENROLLMENT_GRANTS",
    "CX_ENROLLMENT_TOKENS", "CX_AGENT_RELATIONSHIPS", "CX_AGENT_CREDENTIALS", "CX_AGENT_ACCESS_TOKENS",
    "CX_CHANNELS", "CX_CHANNEL_MEMBERS", "CX_CHANNEL_MESSAGES", "CX_BARRIERS", "CX_BARRIER_ARRIVALS",
    "CX_ACTION_CARDS", "CX_NOTIFICATIONS", "CX_SECURITY_EVENTS", "CX_BRIDGES", "CX_AGENT_INSTANCES",
    "CX_AGENT_DELIVERIES", "CX_CHANNEL_MEMORY_CANDIDATES", "CX_BRIDGE_TRANSFERS",
})

CHANNEL_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({"PRINCIPAL_ID", "PRINCIPAL_TYPE", "STATUS", "PERMISSION_VERSION"}),
    "CX_HUMAN_IDENTITIES": frozenset({"IDENTITY_ID", "PRINCIPAL_ID", "IDENTITY_TYPE", "SUBJECT_KEY", "PASSWORD_HASH"}),
    "CX_WEB_SESSIONS": frozenset({"SESSION_DIGEST", "PRINCIPAL_ID", "CSRF_DIGEST", "EXPIRES_AT", "REVOKED_AT"}),
    "CX_ENROLLMENT_GRANTS": frozenset({"GRANT_ID", "SPONSOR_PRINCIPAL_ID", "OWNER_PRINCIPAL_ID", "MAX_USES", "USED_COUNT"}),
    "CX_ENROLLMENT_TOKENS": frozenset({"TOKEN_ID", "GRANT_ID", "TOKEN_DIGEST", "CONSUMED_AT"}),
    "CX_AGENT_CREDENTIALS": frozenset({"CREDENTIAL_ID", "AGENT_ID", "CREDENTIAL_TYPE", "STATUS"}),
    "CX_AGENT_ACCESS_TOKENS": frozenset({"TOKEN_DIGEST", "AGENT_ID", "INSTANCE_ID", "FENCING_TOKEN", "EXPIRES_AT"}),
    "CX_CHANNELS": frozenset({"CHANNEL_ID", "CHANNEL_NAME", "SECURITY_DOMAIN_ID", "STATUS", "LEGAL_HOLD"}),
    "CX_CHANNEL_MEMBERS": frozenset({"MEMBER_ID", "CHANNEL_ID", "PRINCIPAL_ID", "MEMBER_ROLE", "STATUS"}),
    "CX_CHANNEL_MESSAGES": frozenset({"MESSAGE_ID", "CHANNEL_ID", "PRINCIPAL_ID", "BODY_TEXT", "CREATED_AT"}),
    "CX_BARRIERS": frozenset({"BARRIER_ID", "NODE_KEY", "POLICY_JSON", "PARTICIPANT_SNAPSHOT", "CREATED_BY", "STATUS"}),
    "CX_BARRIER_ARRIVALS": frozenset({"ARRIVAL_ID", "BARRIER_ID", "PRINCIPAL_ID", "REPORT_DIGEST", "REPORT_JSON", "IDEMPOTENCY_KEY"}),
    "CX_SECURITY_EVENTS": frozenset({"EVENT_ID", "ACTION_NAME", "OUTCOME", "CREATED_AT"}),
    "CX_AGENT_INSTANCES": frozenset({"INSTANCE_ID", "AGENT_ID", "STATUS", "FENCING_TOKEN", "LEASE_EXPIRES_AT"}),
    "CX_AGENT_DELIVERIES": frozenset({"DELIVERY_ID", "AGENT_ID", "INSTANCE_ID", "IDEMPOTENCY_KEY", "STATUS", "CLAIM_TOKEN_DIGEST", "CLAIMED_AT", "FENCING_TOKEN"}),
}

# A v4.3.0 draft was briefly usable before Gateway fencing was finalized.
# These columns are deliberately upgraded in-place; all other missing columns
# still make an existing partial schema fail closed instead of being adopted.
CHANNEL_ADDITIVE_COLUMNS = {
    "CX_AGENT_INSTANCES": frozenset({"LEASE_EXPIRES_AT"}),
    "CX_AGENT_ACCESS_TOKENS": frozenset({"FENCING_TOKEN"}),
    "CX_BARRIERS": frozenset({"CREATED_BY"}),
    "CX_AGENT_DELIVERIES": frozenset({"CLAIM_TOKEN_DIGEST", "CLAIMED_AT", "FENCING_TOKEN"}),
}

# v4.3.0 keeps the identity/Channel step and the lifecycle step separate so
# an interrupted deployment can resume without replaying the base schema. The
# lifecycle step is nevertheless part of the same release contract because
# runtime recovery, retention, notifications, threads and profile changes
# read these fields.
GOVERNANCE_REQUIRED_TABLES = frozenset({
    "CX_CHANNEL_THREADS", "CX_CHANNEL_THREAD_MEMBERS", "CX_RUNTIME_PROFILE_CHANGES",
})
GOVERNANCE_REQUIRED_COLUMNS = {
    "CX_CHANNELS": frozenset({"LIFECYCLE_REASON", "DELETION_AFTER", "QUARANTINED_AT"}),
    "CX_BRIDGES": frozenset({"APPROVAL_REASON", "POLICY_VERSION"}),
    "CX_BRIDGE_TRANSFERS": frozenset({"IDEMPOTENCY_KEY", "SOURCE_CLASSIFICATION"}),
    "CX_NOTIFICATIONS": frozenset({"NOTIFICATION_LEVEL", "ACKNOWLEDGED_BY", "ESCALATED_AT"}),
    "CX_BARRIERS": frozenset({"RETRY_COUNT", "MAX_RETRIES", "LAST_RECOVERY_ACTION", "RECOVERY_REASON"}),
    "CX_CHANNEL_THREADS": frozenset({
        "THREAD_ID", "CHANNEL_ID", "THREAD_TYPE", "CLASSIFICATION", "STATUS", "POLICY_JSON", "CREATED_BY",
    }),
    "CX_CHANNEL_THREAD_MEMBERS": frozenset({
        "THREAD_MEMBER_ID", "THREAD_ID", "PRINCIPAL_ID", "MEMBER_ROLE", "STATUS", "VALID_UNTIL",
    }),
    "CX_RUNTIME_PROFILE_CHANGES": frozenset({
        "CHANGE_ID", "REQUESTED_BY", "CURRENT_PROFILE", "TARGET_PROFILE", "IMPACT_JSON", "STATUS", "REASON",
    }),
}

# v4.3.0 security lifecycle objects are intentionally probed separately from
# the Channel and governance steps.  A database may have completed 16 and 17
# while still lacking these tables; treating the partial schema as complete
# would skip the security migration on the next retry.
SECURITY_REQUIRED_TABLES = frozenset({
    "CX_MFA_FACTORS", "CX_MFA_RECOVERY_CODES", "CX_PASSWORD_RESET_TOKENS",
    "CX_IDENTITY_LINK_AUDIT", "CX_DELEGATIONS", "CX_AGENT_QUOTAS",
    "CX_AGENT_OWNERSHIP_HISTORY", "CX_AGENT_LEGACY_REVIEWS",
    "CX_AGENT_DERIVED_OBJECTS", "CX_CHANNEL_DELETION_EVIDENCE",
    "CX_MEMORY_ARTIFACT_LINKS", "CX_BRIDGE_CONNECTORS",
})

SECURITY_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({"MFA_REQUIRED"}),
    "CX_HUMAN_IDENTITIES": frozenset({"FAILED_LOGIN_COUNT", "LOCKED_UNTIL", "USER_ID"}),
    "CX_ENROLLMENT_GRANTS": frozenset({"AGENT_ID"}),
    "CX_MFA_FACTORS": frozenset({"FACTOR_ID", "PRINCIPAL_ID", "FACTOR_TYPE", "SECRET_CIPHERTEXT", "STATUS"}),
    "CX_MFA_RECOVERY_CODES": frozenset({"CODE_ID", "PRINCIPAL_ID", "CODE_DIGEST", "STATUS"}),
    "CX_PASSWORD_RESET_TOKENS": frozenset({"TOKEN_ID", "PRINCIPAL_ID", "TOKEN_DIGEST", "PURPOSE", "EXPIRES_AT", "CONSUMED_AT"}),
    "CX_IDENTITY_LINK_AUDIT": frozenset({"LINK_EVENT_ID", "PRINCIPAL_ID", "ACTOR_PRINCIPAL_ID", "PROVIDER", "SUBJECT_DIGEST", "REASON", "OUTCOME"}),
    "CX_DELEGATIONS": frozenset({"DELEGATION_ID", "GRANTOR_PRINCIPAL_ID", "GRANTEE_PRINCIPAL_ID", "PERMISSIONS_JSON", "DATA_SCOPE", "STATUS", "VERSION"}),
    "CX_AGENT_QUOTAS": frozenset({"QUOTA_ID", "SCOPE_TYPE", "SCOPE_ID", "ENVIRONMENT", "MAX_AGENTS", "USED_AGENTS", "MAX_ACTIVE_INSTANCES", "USED_ACTIVE_INSTANCES", "STATUS"}),
    "CX_AGENT_OWNERSHIP_HISTORY": frozenset({"HISTORY_ID", "AGENT_ID", "ACTOR_PRINCIPAL_ID", "CREDENTIAL_ROTATED", "GRANTS_REEVALUATED", "REASON"}),
    "CX_AGENT_LEGACY_REVIEWS": frozenset({"REVIEW_ID", "AGENT_ID", "CLASSIFICATION", "EVIDENCE_JSON", "STATUS"}),
    "CX_AGENT_DERIVED_OBJECTS": frozenset({"DERIVED_OBJECT_ID", "AGENT_ID", "OBJECT_TYPE", "OBJECT_ID", "STATUS"}),
    "CX_CHANNEL_DELETION_EVIDENCE": frozenset({"EVIDENCE_ID", "CHANNEL_ID", "ACTOR_PRINCIPAL_ID", "FROM_STATUS", "TO_STATUS", "REFERENCE_COUNT", "REASON", "DETAIL_JSON"}),
    "CX_MEMORY_ARTIFACT_LINKS": frozenset({"LINK_ID", "CANDIDATE_ID", "ARTIFACT_ID", "DESTINATION_SCOPE", "STATUS"}),
    "CX_BRIDGE_CONNECTORS": frozenset({"CONNECTOR_ID", "BRIDGE_ID", "CONNECTOR_MODE", "ENDPOINT_REF", "METADATA_ONLY", "STATUS", "REASON"}),
}

GRAPH_V421_REQUIRED_COLUMNS = {
    "GRAPH_ATTEMPTS": frozenset({"COMPLETION_DIGEST", "EFFECT_IDEMPOTENCY_KEY"}),
    "GRAPH_INBOX": frozenset({"ATTEMPTS", "AVAILABLE_AT"}),
    "GRAPH_OUTBOX": frozenset({"MAX_ATTEMPTS"}),
    "GRAPH_EXECUTOR_REGISTRY": frozenset({
        "STATUS_REASON", "STATUS_CHANGED_BY", "STATUS_CHANGED_AT",
    }),
}


def _package_manifest() -> dict[str, Any]:
    """Read generated package identity when this tool runs outside the repo."""
    path = REPO_ROOT / "build-manifest.json"
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _available_databases() -> tuple[str, ...]:
    """Return database adapters available in source or a generated package."""
    manifest_key = str((_package_manifest().get("database") or {}).get("key") or "").lower()
    if manifest_key in {"oracle", "pg", "yashandb"}:
        return (manifest_key,)
    return ("oracle", "pg", "yashandb")


def _deployment_script(database: str, name: str) -> Path:
    """Resolve an adapter SQL script in unified source or a built package."""
    packaged = REPO_ROOT / "scripts" / "deploy" / name
    if packaged.is_file():
        return packaged
    return REPO_ROOT / "adapters" / database / "deploy" / name

# v4.2.0 has had a small number of published, schema-equivalent migration
# variants while the Graph deployment was stabilized.  The current release
# keeps each step's checksum meaningful and adds step 14, so only these
# recorded checksums may be adopted after the corresponding objects are
# verified.  An arbitrary checksum is never accepted as a shortcut.
LEGACY_GRAPH_STEP_CHECKSUMS = {
    "oracle": {
        "9_v4_2_0_graph_engineering": frozenset({
            "8541de761a9b06cfdea586db356b179f53e6a2fe31b93dcf8c0d431d8fe21348",
        }),
        "11_v4_2_0_graph_control": frozenset({
            "421ca3bc2718a8578acb5a40a2b2a162a659b19b13ce2b02d785ed5d32ad0a05",
        }),
    },
    "pg": {
        "9_v4_2_0_graph_engineering": frozenset({
            "be787c557c67705466ee8901ba99c9d7f8a3dbe8a29ac5d184589a9d60eb5b83",
        }),
    },
    "yashandb": {
        "9_v4_2_0_graph_engineering": frozenset({
            "356ad572cbccd4e2cc5877d9f0c5ece8d97af1499143c0a047f4fd15f90b00cb",
        }),
        "11_v4_2_0_graph_control": frozenset({
            "e00af80a4ea10a94da3031afc835a35adfa1144921dcfd764b7e765ebcd1fa26",
        }),
        "12_v4_2_0_graph_edge_scope": frozenset({
            "5bebe10dc60294c44adac9d8c544b2268de9de165b548a4d6fade7561c13a991",
        }),
    },
}

LEGACY_GRAPH_STEP_TABLES = {
    "9_v4_2_0_graph_engineering": frozenset({
        "GRAPH_DEFINITIONS", "GRAPH_VERSIONS", "GRAPH_NODES", "GRAPH_EDGES",
        "GRAPH_ALIASES", "GRAPH_TYPE_REGISTRY", "GRAPH_COMPILE_PLANS",
    }),
    "11_v4_2_0_graph_control": frozenset({
        "GRAPH_JOIN_STATES", "GRAPH_RUN_BRANCHES", "GRAPH_WAIT_SUBSCRIPTIONS",
        "GRAPH_TRACES", "GRAPH_RUN_MIGRATIONS", "GRAPH_COMPAT_BINDINGS",
    }),
    "12_v4_2_0_graph_edge_scope": frozenset({"GRAPH_EDGES"}),
}

LEGACY_GRAPH_STEP_COLUMNS = {
    "11_v4_2_0_graph_control": {
        "GRAPH_ARTIFACTS": frozenset({
            "LEGAL_HOLD_ACTOR", "LEGAL_HOLD_REASON", "LEGAL_HOLD_AT",
            "RELEASED_BY", "RELEASE_REASON", "RELEASED_AT",
        }),
    },
}


def _script_key(script: Path) -> str:
    return script.stem[:96]


def _checksum(script: Path) -> str:
    return hashlib.sha256(script.read_bytes()).hexdigest()


def _ensure_ledger(cursor: Any, database: str) -> None:
    if database == "pg":
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS ai_schema_migrations ("
            "version varchar(32) PRIMARY KEY, checksum varchar(64) NOT NULL, "
            "applied_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL)"
        )
        return
    varchar = "VARCHAR2" if database == "oracle" else "VARCHAR"
    try:
        cursor.execute(
            f"CREATE TABLE AI_SCHEMA_MIGRATIONS (VERSION {varchar}(32) PRIMARY KEY, "
            f"CHECKSUM {varchar}(64) NOT NULL, "
            "APPLIED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
        )
    except Exception as exc:
        if not _is_existing_object(exc):
            raise


def _ensure_step_ledger(cursor: Any, database: str) -> None:
    """Create the additive v4.2 step journal without changing v4.1 tables."""
    if database == "pg":
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS ai_schema_migration_steps ("
            "version varchar(32) NOT NULL, step_name varchar(96) NOT NULL, "
            "checksum varchar(64) NOT NULL, status varchar(24) NOT NULL, "
            "statements_executed integer DEFAULT 0 NOT NULL, failed_statement integer DEFAULT 0 NOT NULL, "
            "error_code varchar(128), error_message varchar(2000), "
            "started_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "applied_at timestamp, PRIMARY KEY (version, step_name))"
        )
        return
    varchar = "VARCHAR2" if database == "oracle" else "VARCHAR"
    try:
        cursor.execute(
            f"CREATE TABLE AI_SCHEMA_MIGRATION_STEPS (VERSION {varchar}(32) NOT NULL, "
            f"STEP_NAME {varchar}(96) NOT NULL, CHECKSUM {varchar}(64) NOT NULL, "
            f"STATUS {varchar}(24) NOT NULL, STATEMENTS_EXECUTED NUMBER(20,0) DEFAULT 0 NOT NULL, "
            f"FAILED_STATEMENT NUMBER(20,0) DEFAULT 0 NOT NULL, ERROR_CODE {varchar}(128), "
            f"ERROR_MESSAGE {varchar}(2000), STARTED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            f"UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, APPLIED_AT TIMESTAMP, "
            "PRIMARY KEY (VERSION, STEP_NAME))"
        )
    except Exception as exc:
        if not _is_existing_object(exc):
            raise


def _step_row(cursor: Any, database: str, script: Path) -> dict[str, Any] | None:
    params = {"version": MIGRATION_VERSION, "step_name": _script_key(script)}
    if database == "pg":
        cursor.execute(
            "SELECT checksum, status, statements_executed, failed_statement FROM ai_schema_migration_steps "
            "WHERE version = %s AND step_name = %s",
            (MIGRATION_VERSION, _script_key(script)),
        )
    else:
        cursor.execute(
            "SELECT CHECKSUM, STATUS, STATEMENTS_EXECUTED, FAILED_STATEMENT FROM AI_SCHEMA_MIGRATION_STEPS "
            "WHERE VERSION = :version AND STEP_NAME = :step_name", params,
        )
    row = cursor.fetchone()
    if not row:
        return None
    return {"checksum": str(row[0]), "status": str(row[1]).upper(),
            "statements_executed": int(row[2] or 0), "failed_statement": int(row[3] or 0)}


def _legacy_graph_step_compatible(cursor: Any, database: str, script: Path,
                                  checksum: str) -> bool:
    """Whether a known legacy Graph step can be safely claimed by this release."""
    allowed = LEGACY_GRAPH_STEP_CHECKSUMS.get(database, {}).get(_script_key(script), frozenset())
    if checksum not in allowed:
        return False
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute(
            "SELECT upper(table_name) FROM user_tables"
        )
    tables = {str(row[0]).upper() for row in cursor.fetchall()}
    required_tables = LEGACY_GRAPH_STEP_TABLES.get(_script_key(script), frozenset())
    if not required_tables <= tables:
        return False
    for table, required_columns in LEGACY_GRAPH_STEP_COLUMNS.get(_script_key(script), {}).items():
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns "
                "WHERE upper(table_name) = :table_name", {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        if not required_columns <= columns:
            return False
    # Step 14 is additive. If an early database already has the trigger table,
    # verify its shape now; otherwise step 14 will create it below.
    if "GRAPH_TRIGGERS" in tables:
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                ("GRAPH_TRIGGERS",),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns "
                "WHERE upper(table_name) = :table_name", {"table_name": "GRAPH_TRIGGERS"},
            )
        trigger_columns = {str(row[0]).upper() for row in cursor.fetchall()}
        required_trigger_columns = {
            "TRIGGER_ID", "GRAPH_VERSION_ID", "TRIGGER_KIND", "CONFIG_JSON", "STATUS",
            "ACTOR_ID", "REASON", "CREATED_AT", "UPDATED_AT",
        }
        return required_trigger_columns <= trigger_columns
    return True


def _upsert_step_row(cursor: Any, database: str, script: Path, checksum: str,
                     status: str, statements_executed: int = 0,
                     failed_statement: int = 0, error_code: str = "",
                     error_message: str = "") -> None:
    params = {"version": MIGRATION_VERSION, "step_name": _script_key(script),
              "checksum": checksum, "status": status[:24],
              "statements_executed": statements_executed, "failed_statement": failed_statement,
              "error_code": error_code[:128], "error_message": error_message[:2000]}
    if database == "pg":
        cursor.execute(
            "INSERT INTO ai_schema_migration_steps "
            "(version, step_name, checksum, status, statements_executed, failed_statement, error_code, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (version, step_name) DO UPDATE SET checksum = EXCLUDED.checksum, "
            "status = EXCLUDED.status, statements_executed = EXCLUDED.statements_executed, "
            "failed_statement = EXCLUDED.failed_statement, error_code = EXCLUDED.error_code, "
            "error_message = EXCLUDED.error_message, updated_at = CURRENT_TIMESTAMP, "
            "applied_at = CASE WHEN EXCLUDED.status = 'APPLIED' THEN CURRENT_TIMESTAMP ELSE ai_schema_migration_steps.applied_at END",
            (MIGRATION_VERSION, _script_key(script), checksum, status[:24], statements_executed,
             failed_statement, error_code[:128], error_message[:2000]),
        )
        return
    cursor.execute(
        "MERGE INTO AI_SCHEMA_MIGRATION_STEPS dst USING "
        "(SELECT :version AS VERSION, :step_name AS STEP_NAME FROM DUAL) src "
        "ON (dst.VERSION = src.VERSION AND dst.STEP_NAME = src.STEP_NAME) "
        "WHEN MATCHED THEN UPDATE SET CHECKSUM = :checksum, STATUS = :status, "
        "STATEMENTS_EXECUTED = :statements_executed, FAILED_STATEMENT = :failed_statement, "
        "ERROR_CODE = :error_code, ERROR_MESSAGE = :error_message, UPDATED_AT = CURRENT_TIMESTAMP, "
        "APPLIED_AT = CASE WHEN :status = 'APPLIED' THEN CURRENT_TIMESTAMP ELSE dst.APPLIED_AT END "
        "WHEN NOT MATCHED THEN INSERT (VERSION, STEP_NAME, CHECKSUM, STATUS, STATEMENTS_EXECUTED, "
        "FAILED_STATEMENT, ERROR_CODE, ERROR_MESSAGE) VALUES (:version, :step_name, :checksum, :status, "
        ":statements_executed, :failed_statement, :error_code, :error_message)", params,
    )


def verify_backup_evidence(path: Path | None) -> tuple[bool, str]:
    """Verify a small, portable backup manifest without exposing backup data."""
    if path is None:
        return False, "backup evidence path was not provided"
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"backup evidence is unreadable: {type(exc).__name__}"
    if evidence.get("recoverable") is not True:
        return False, "backup evidence must declare recoverable=true"
    if not evidence.get("created_at") or not evidence.get("backup_ref"):
        return False, "backup evidence requires created_at and backup_ref"
    expected = evidence.get("manifest_sha256")
    if expected:
        copy = dict(evidence)
        copy.pop("manifest_sha256", None)
        actual = hashlib.sha256(json.dumps(copy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual != str(expected):
            return False, "backup evidence manifest checksum mismatch"
    return True, "verified"


def _capacity_probe(cursor: Any, database: str, tier: int | None = None) -> dict[str, Any]:
    """Collect comparable, non-destructive capacity facts for migration evidence."""
    tables = ("ENTITIES", "ENTITY_EDGES", "GRAPH_DEFINITIONS", "GRAPH_RUNS")
    counts: dict[str, int | None] = {}
    for table in tables:
        try:
            if database == "pg":
                cursor.execute(f"SELECT COUNT(*) FROM {table.lower()}")
            else:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row = cursor.fetchone()
            counts[table] = int(row[0]) if row else 0
        except Exception:
            counts[table] = None
            # A missing table aborts a PostgreSQL transaction.  The probe is
            # intentionally read-only, so clear that error before checking
            # the next optional v4.2 object or AGE capability.
            if database == "pg":
                try:
                    cursor.connection.rollback()
                except Exception:
                    pass
    known = [value for value in counts.values() if value is not None]
    estimate = sum(known)
    result: dict[str, Any] = {"tier": tier, "row_counts": counts,
                              "observed_rows": estimate, "status": "PASS"}
    if tier is not None and estimate > tier:
        result["status"] = "REVIEW"
        result["warning"] = "observed rows exceed selected benchmark tier"
    return result


def _preflight(conn: Any, database: str, scripts: list[Path], tier: int | None = None) -> dict[str, Any]:
    """Read-only readiness check used by both Dry Run and actual migration."""
    with conn.cursor() as cursor:
        if database == "pg":
            cursor.execute("SELECT current_database()")
        else:
            cursor.execute("SELECT USER FROM DUAL")
        identity = cursor.fetchone()
        objects_complete = _objects_complete(cursor, database)
        capacity = _capacity_probe(cursor, database, tier)
        capabilities: dict[str, Any] = {}
        if database == "pg":
            try:
                cursor.execute(
                    "SELECT name, installed_version FROM pg_available_extensions WHERE name = 'age'"
                )
                age_row = cursor.fetchone()
                # AGE may be available to CREATE but not installed yet.  The
                # migration owns the idempotent CREATE EXTENSION step, so both
                # states are ready; a missing catalog row is not.
                capabilities["apache_age_available"] = bool(age_row)
                capabilities["apache_age_installed"] = bool(age_row and age_row[1])
            except Exception:
                capabilities["apache_age_available"] = False
        v43_static_contract: dict[str, Any] = {}
        if MIGRATION_VERSION == "4.3.0":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V43_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V43_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v43_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.1":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V431_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V431_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v431_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.2":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V432_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V432_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v432_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.3":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V433_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V433_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v433_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.4":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V434_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V434_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v434_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.5":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V435_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V435_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v435_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.6":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V436_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V436_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v436_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.3.7":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V437_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V437_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v437_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.4.0":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V440_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V440_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v440_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.4.1":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V441_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V441_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v441_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.4.2":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V442_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V442_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v442_static_contract(database, full_scripts)
        elif MIGRATION_VERSION == "4.4.3":
            deploy_dir = scripts[0].parent if scripts else _deployment_script(database, V443_MIGRATION_SCRIPTS[0]).parent
            full_scripts = [deploy_dir / name for name in V443_MIGRATION_SCRIPTS]
            v43_static_contract = validate_v443_static_contract(database, full_scripts)
    return {"database": database, "identity_present": bool(identity),
            "objects_complete_before": objects_complete,
            "scripts": [{"name": path.name, "checksum": _checksum(path)} for path in scripts],
            "capacity": capacity, "capabilities": capabilities,
            "v43_static_contract": v43_static_contract,
            "passed": bool(identity) and capabilities.get("apache_age_available", True)
            and (not v43_static_contract or v43_static_contract.get("passed") is True)}


def _ledger_checksum(cursor: Any, database: str) -> str | None:
    if database == "pg":
        cursor.execute(
            "SELECT checksum FROM ai_schema_migrations WHERE version = %s",
            (MIGRATION_VERSION,),
        )
    else:
        cursor.execute(
            "SELECT CHECKSUM FROM AI_SCHEMA_MIGRATIONS WHERE VERSION = :version",
            {"version": MIGRATION_VERSION},
        )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def _record_ledger(cursor: Any, checksum: str, database: str) -> None:
    if database == "pg":
        cursor.execute(
            "INSERT INTO ai_schema_migrations(version, checksum) VALUES (%s, %s) "
            "ON CONFLICT (version) DO UPDATE SET checksum = EXCLUDED.checksum",
            (MIGRATION_VERSION, checksum),
        )
    else:
        cursor.execute(
            "INSERT INTO AI_SCHEMA_MIGRATIONS(VERSION, CHECKSUM) "
            "VALUES (:version, :checksum)",
            {"version": MIGRATION_VERSION, "checksum": checksum},
        )


def _schema_tables(cursor: Any, database: str) -> set[str]:
    """Return the current schema table names in one portable representation."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    return {str(row[0]).upper() for row in cursor.fetchall()}


def _schema_columns(cursor: Any, database: str, table: str) -> set[str]:
    """Return one table's columns without relying on vendor-specific casing."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(column_name) FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND upper(table_name) = %s",
            (table,),
        )
    else:
        cursor.execute(
            "SELECT upper(column_name) FROM user_tab_columns "
            "WHERE upper(table_name) = :table_name", {"table_name": table},
        )
    return {str(row[0]).upper() for row in cursor.fetchall()}


def _schema_columns_complete(cursor: Any, database: str, required: dict[str, frozenset[str]], present: set[str] | None = None) -> bool:
    present = present if present is not None else _schema_tables(cursor, database)
    for table, required_columns in required.items():
        if table not in present or not required_columns <= _schema_columns(cursor, database, table):
            return False
    return True


def _channel_objects_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    return CHANNEL_REQUIRED_TABLES <= present and _schema_columns_complete(
        cursor, database, CHANNEL_REQUIRED_COLUMNS, present,
    )


def _security_lifecycle_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    return SECURITY_REQUIRED_TABLES <= present and _schema_columns_complete(
        cursor, database, SECURITY_REQUIRED_COLUMNS, present,
    )


def _organization_governance_complete(cursor: Any, database: str) -> bool:
    """Check the additive v4.3.1 organization step independently."""
    present = _schema_tables(cursor, database)
    base_columns = {
        table: columns for table, columns in V431_ORGANIZATION_REQUIRED_COLUMNS.items()
        if table not in {"CX_PRINCIPALS", "CX_REGISTRATION_REQUESTS"}
    }
    return set(V431_ORGANIZATION_TABLES) <= present and _schema_columns_complete(
        cursor, database, base_columns, present,
    )


def _human_display_name_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    required = {
        table: V431_ORGANIZATION_REQUIRED_COLUMNS[table]
        for table in ("CX_PRINCIPALS", "CX_REGISTRATION_REQUESTS")
    }
    return _schema_columns_complete(cursor, database, required, present)


def _entry_access_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    return _schema_columns_complete(
        cursor, database,
        {"CX_PRINCIPALS": frozenset({"PORTAL_ACCESS", "APP_ACCESS"})},
        present,
    )


def _identity_organization_alignment_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    return _schema_columns_complete(
        cursor, database,
        {"CX_PRINCIPALS": frozenset({"ORGANIZATION_REQUIRED"})},
        present,
    )


def _memory_lifecycle_complete(cursor: Any, database: str) -> bool:
    present = _schema_tables(cursor, database)
    return set(V432_MEMORY_TABLES) <= present and _schema_columns_complete(
        cursor, database, V432_MEMORY_REQUIRED_COLUMNS, present,
    )


def _objects_complete(cursor: Any, database: str) -> bool:
    if MIGRATION_VERSION in SECURITY_DOMAIN_BINDING_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V443_SECURITY_DOMAIN_TABLES) <= present and _schema_columns_complete(
            cursor, database, V443_SECURITY_DOMAIN_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in GRAPH_OPERATIONS_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V442_GRAPH_OPERATIONS_TABLES) <= present and _schema_columns_complete(
            cursor, database, V442_GRAPH_OPERATIONS_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in NATIVE_SDD_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V440_SDD_TABLES) <= present and _schema_columns_complete(
            cursor, database, V440_SDD_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in ADMIN_HA_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V441_ADMIN_HA_TABLES) <= present and _schema_columns_complete(
            cursor, database, V441_ADMIN_HA_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in BOOTSTRAP_EMBEDDING_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V437_BOOTSTRAP_TABLES) <= present and _schema_columns_complete(
            cursor, database, V437_BOOTSTRAP_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in NATIVE_AGENT_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V436_NATIVE_AGENT_TABLES) <= present and _schema_columns_complete(
            cursor, database, V436_NATIVE_AGENT_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in PLATFORM_CAPABILITY_MIGRATION_VERSIONS:
        present = _schema_tables(cursor, database)
        return set(V435_PLATFORM_TABLES) <= present and _schema_columns_complete(
            cursor, database, V435_PLATFORM_REQUIRED_COLUMNS, present,
        )
    if MIGRATION_VERSION in COMPLIANCE_MIGRATION_VERSIONS:
        return V434_COMPLIANCE_TABLES <= _schema_tables(cursor, database)
    if MIGRATION_VERSION in GRAPH_ASSURANCE_MIGRATION_VERSIONS:
        return (
            _channel_objects_complete(cursor, database)
            and _governance_lifecycle_complete(cursor, database)
            and _security_lifecycle_complete(cursor, database)
            and _organization_governance_complete(cursor, database)
            and _human_display_name_complete(cursor, database)
            and _entry_access_complete(cursor, database)
            and _identity_organization_alignment_complete(cursor, database)
            and _memory_lifecycle_complete(cursor, database)
            and set(V433_GRAPH_ASSURANCE_TABLES) <= _schema_tables(cursor, database)
        )
    if MIGRATION_VERSION in MEMORY_LIFECYCLE_MIGRATION_VERSIONS:
        return (
            _channel_objects_complete(cursor, database)
            and _governance_lifecycle_complete(cursor, database)
            and _security_lifecycle_complete(cursor, database)
            and _organization_governance_complete(cursor, database)
            and _human_display_name_complete(cursor, database)
            and _entry_access_complete(cursor, database)
            and _identity_organization_alignment_complete(cursor, database)
            and _memory_lifecycle_complete(cursor, database)
        )
    if MIGRATION_VERSION in ORGANIZATION_MIGRATION_VERSIONS:
        return (
            _channel_objects_complete(cursor, database)
            and _governance_lifecycle_complete(cursor, database)
            and _security_lifecycle_complete(cursor, database)
            and _organization_governance_complete(cursor, database)
            and _human_display_name_complete(cursor, database)
            and _entry_access_complete(cursor, database)
            and _identity_organization_alignment_complete(cursor, database)
        )
    if MIGRATION_VERSION in CHANNEL_MIGRATION_VERSIONS:
        # v4.3.0 is a single public integration point, but its scripts are
        # deliberately selected and retried as three independent steps.
        # Require all three only when deciding whether the release is complete.
        return (
            _channel_objects_complete(cursor, database)
            and _governance_lifecycle_complete(cursor, database)
            and _security_lifecycle_complete(cursor, database)
        )

    required = {
        "EXECUTION_JOBS", "EXECUTION_ATTEMPTS", "EXECUTION_POLICIES",
        "EXECUTION_ARTIFACTS", "EXECUTION_AUDIT", "EVENT_DEAD_LETTER",
        "DAG_EXECUTION_LOG", "ALERT_RULES",
    }
    if MIGRATION_VERSION == "4.1.0":
        required.update({
            "AGENT_REGISTRATIONS", "GOV_RESOURCES", "GOV_POLICIES", "GOV_GRANTS",
            "GOV_DECISIONS", "GOV_APPROVAL_REQUESTS", "GOV_APPROVAL_DECISIONS",
            "GOV_EMERGENCY_OPS", "GOV_EMERGENCY_STEPS", "GOV_AUDIT_EVENTS",
            "GOV_AUDIT_RETENTION", "GOV_LEGAL_HOLDS", "GOV_EVIDENCE_EXPORTS",
        })
    if MIGRATION_VERSION in GRAPH_MIGRATION_VERSIONS:
        required.update({
            "AI_SCHEMA_MIGRATION_STEPS",
            "GRAPH_DEFINITIONS", "GRAPH_VERSIONS", "GRAPH_NODES", "GRAPH_EDGES",
            "GRAPH_ALIASES", "GRAPH_TYPE_REGISTRY", "GRAPH_COMPILE_PLANS",
            "GRAPH_RUNS", "GRAPH_NODE_RUNS", "GRAPH_READY_NODES", "GRAPH_ATTEMPTS",
            "GRAPH_STATE_EVENTS", "GRAPH_CHECKPOINTS", "GRAPH_TRANSITIONS",
            "GRAPH_ARTIFACTS", "GRAPH_WORKERS", "GRAPH_LEASE_TOKENS",
            "GRAPH_INBOX", "GRAPH_OUTBOX", "GRAPH_EVALUATIONS", "GRAPH_INTERVENTIONS",
            "GRAPH_JOIN_STATES", "GRAPH_RUN_BRANCHES", "GRAPH_WAIT_SUBSCRIPTIONS", "GRAPH_TRIGGERS",
            "GRAPH_TRACES", "GRAPH_RUN_MIGRATIONS", "GRAPH_COMPAT_BINDINGS",
        })
        if MIGRATION_EDITION == "enterprise":
            required.update({"GRAPH_SCHEDULER_LEASES", "GRAPH_SCHEDULER_QUOTAS"})
        if MIGRATION_VERSION == "4.2.1":
            required.update({"GRAPH_EXECUTOR_REGISTRY", "GRAPH_GOVERNANCE_EVENTS"})
    present = _schema_tables(cursor, database)
    if not required <= present:
        return False
    if MIGRATION_VERSION != "4.2.1":
        return True
    for table, required_columns in GRAPH_V421_REQUIRED_COLUMNS.items():
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns "
                "WHERE upper(table_name) = :table_name", {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        if not required_columns <= columns:
            return False
    return True


def _governance_lifecycle_complete(cursor: Any, database: str) -> bool:
    """Check the additive v4.3 lifecycle/thread/profile step independently."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    present = {str(row[0]).upper() for row in cursor.fetchall()}
    if not GOVERNANCE_REQUIRED_TABLES <= present:
        return False
    for table, required_columns in GOVERNANCE_REQUIRED_COLUMNS.items():
        if table not in present:
            return False
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns "
                "WHERE upper(table_name) = :table_name", {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        if not required_columns <= columns:
            return False
    if database == "pg":
        return _pg_thread_runtime_permissions_complete(cursor)
    return True


def _pg_thread_runtime_permissions_complete(cursor: Any) -> bool:
    """Require the Agent Runtime thread tables to be append-only."""
    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_agent_runtime')")
    if not bool(cursor.fetchone()[0]):
        return False
    for table in ("cx_channel_threads", "cx_channel_thread_members"):
        cursor.execute(
            "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, 'SELECT,INSERT')",
            (table,),
        )
        if not bool(cursor.fetchone()[0]):
            return False
        for privilege in ("UPDATE", "DELETE"):
            cursor.execute(
                "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, %s)",
                (table, privilege),
            )
            if bool(cursor.fetchone()[0]):
                return False
    return True


def _channel_schema_incomplete(cursor: Any, database: str) -> bool:
    """Reject an existing partial v4.3 schema instead of silently adopting it."""
    if MIGRATION_VERSION not in (CHANNEL_MIGRATION_VERSIONS | ORGANIZATION_MIGRATION_VERSIONS):
        return False
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    present = {str(row[0]).upper() for row in cursor.fetchall()}
    for table, required_columns in CHANNEL_REQUIRED_COLUMNS.items():
        if table not in present:
            continue
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns WHERE upper(table_name) = :table_name",
                {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        required_base = required_columns - CHANNEL_ADDITIVE_COLUMNS.get(table, frozenset())
        if not required_base <= columns:
            return True
    return False


def _channel_additive_columns_missing(cursor: Any, database: str) -> bool:
    """Return true only for an existing, otherwise complete early v4.3 schema."""
    if MIGRATION_VERSION not in (CHANNEL_MIGRATION_VERSIONS | ORGANIZATION_MIGRATION_VERSIONS):
        return False
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    present = {str(row[0]).upper() for row in cursor.fetchall()}
    for table, additive_columns in CHANNEL_ADDITIVE_COLUMNS.items():
        if table not in present:
            continue
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns WHERE upper(table_name) = :table_name",
                {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        if not additive_columns <= columns:
            return True
    return False


def _graph_v420_baseline_present(cursor: Any, database: str) -> bool:
    """Detect an installed Graph baseline before choosing v4.3.0 steps."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    present = {str(row[0]).upper() for row in cursor.fetchall()}
    required = {
        "GRAPH_DEFINITIONS", "GRAPH_VERSIONS", "GRAPH_NODES", "GRAPH_EDGES",
        "GRAPH_ALIASES", "GRAPH_TYPE_REGISTRY", "GRAPH_COMPILE_PLANS",
        "GRAPH_RUNS", "GRAPH_NODE_RUNS", "GRAPH_READY_NODES", "GRAPH_ATTEMPTS",
        "GRAPH_STATE_EVENTS", "GRAPH_CHECKPOINTS", "GRAPH_TRANSITIONS",
        "GRAPH_ARTIFACTS", "GRAPH_WORKERS", "GRAPH_LEASE_TOKENS", "GRAPH_INBOX",
        "GRAPH_OUTBOX", "GRAPH_EVALUATIONS", "GRAPH_INTERVENTIONS",
        "GRAPH_JOIN_STATES", "GRAPH_RUN_BRANCHES", "GRAPH_WAIT_SUBSCRIPTIONS",
        "GRAPH_TRIGGERS", "GRAPH_TRACES", "GRAPH_RUN_MIGRATIONS",
        "GRAPH_COMPAT_BINDINGS",
    }
    if MIGRATION_EDITION == "enterprise":
        required.update({"GRAPH_SCHEDULER_LEASES", "GRAPH_SCHEDULER_QUOTAS"})
    return required <= present


def _graph_v421_closure_present(cursor: Any, database: str) -> bool:
    """Verify the internal Executor closure, including its additive columns."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    present = {str(row[0]).upper() for row in cursor.fetchall()}
    if not {"GRAPH_EXECUTOR_REGISTRY", "GRAPH_GOVERNANCE_EVENTS"} <= present:
        return False
    for table, required_columns in GRAPH_V421_REQUIRED_COLUMNS.items():
        if database == "pg":
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND upper(table_name) = %s",
                (table,),
            )
        else:
            cursor.execute(
                "SELECT upper(column_name) FROM user_tab_columns "
                "WHERE upper(table_name) = :table_name", {"table_name": table},
            )
        columns = {str(row[0]).upper() for row in cursor.fetchall()}
        if not required_columns <= columns:
            return False
    return True


def _step_objects_complete(cursor: Any, database: str, script: Path) -> bool:
    """Verify the objects owned by an already-journaled additive step.

    A prior runner can leave an ``APPLIED`` row after a process interruption or
    after an idempotent script was only partially effective.  The step ledger
    is evidence, not a substitute for checking the schema it claims to own.
    """
    key = _script_key(script)
    if key == "15_v4_2_1_executor_registry":
        return _graph_v421_closure_present(cursor, database)
    if key == "16_v4_3_0_identity_channels":
        return _channel_objects_complete(cursor, database)
    if key == "17_v4_3_0_governance_lifecycle":
        return _governance_lifecycle_complete(cursor, database)
    if key == "18_v4_3_0_security_lifecycle":
        return _security_lifecycle_complete(cursor, database)
    if key == "19_v4_3_1_organization_governance":
        return _organization_governance_complete(cursor, database)
    if key == "20_v4_3_1_human_display_name":
        return _human_display_name_complete(cursor, database)
    if key == "21_v4_3_1_entry_access":
        return _entry_access_complete(cursor, database)
    if key == "22_v4_3_1_identity_organization_alignment":
        return _identity_organization_alignment_complete(cursor, database)
    if key == "23_v4_3_2_memory_lifecycle":
        return _memory_lifecycle_complete(cursor, database)
    if key == "28_v4_3_3_graph_assurance":
        return set(V433_GRAPH_ASSURANCE_TABLES) <= _schema_tables(cursor, database)
    if key == "34_v4_4_0_governed_sdd":
        present = _schema_tables(cursor, database)
        return set(V440_SDD_TABLES) <= present and _schema_columns_complete(
            cursor, database, V440_SDD_REQUIRED_COLUMNS, present,
        )
    if key == "35_v4_4_1_admin_ha_upgrade":
        present = _schema_tables(cursor, database)
        required_tables = set(V441_ADMIN_HA_TABLES) - {"CX_UPGRADE_APPROVALS"}
        required_columns = {
            table: columns for table, columns in V441_ADMIN_HA_REQUIRED_COLUMNS.items()
            if table != "CX_UPGRADE_APPROVALS"
        }
        return required_tables <= present and _schema_columns_complete(
            cursor, database, required_columns, present,
        )
    if key == "36_v4_4_1_upgrade_protocol":
        present = _schema_tables(cursor, database)
        return "CX_UPGRADE_APPROVALS" in present and _schema_columns_complete(
            cursor, database,
            {"CX_UPGRADE_APPROVALS": V441_ADMIN_HA_REQUIRED_COLUMNS["CX_UPGRADE_APPROVALS"]},
            present,
        )
    if key == "37_v4_4_2_embedding_graph_operations":
        present = _schema_tables(cursor, database)
        return set(V442_GRAPH_OPERATIONS_TABLES) <= present and _schema_columns_complete(
            cursor, database, V442_GRAPH_OPERATIONS_REQUIRED_COLUMNS, present,
        )
    if key == "39_v4_4_3_security_domain_binding":
        present = _schema_tables(cursor, database)
        return set(V443_SECURITY_DOMAIN_TABLES) <= present and _schema_columns_complete(
            cursor, database, V443_SECURITY_DOMAIN_REQUIRED_COLUMNS, present,
        )
    return True


def _legacy_v441_step_compatible(cursor: Any, database: str, script: Path,
                                 checksum: str) -> bool:
    """Adopt only recorded v4.4.1 development checksums after schema proof."""
    allowed = LEGACY_V441_STEP_CHECKSUMS.get(database, {}).get(
        _script_key(script), frozenset(),
    )
    return checksum in allowed and _step_objects_complete(cursor, database, script)


def _legacy_v442_step_compatible(cursor: Any, database: str, script: Path,
                                 checksum: str) -> bool:
    """Adopt only the recorded pre-release v4.4.2 checksum after schema proof."""
    allowed = LEGACY_V442_STEP_CHECKSUMS.get(database, {}).get(
        _script_key(script), frozenset(),
    )
    return checksum in allowed and _step_objects_complete(cursor, database, script)


def _v43_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Select the missing v4.3.0 chain from the live schema.

    v4.3.0 is the public integration point, so a clean v4.1.x database must
    receive the Graph prerequisite chain, while an existing v4.2 deployment
    should only run the missing closure and identity/Channel step.
    """
    baseline = False
    closure = False
    channels = False
    try:
        config = _load_database_config(config_path)
        probe = _connect_for_preflight(database, config)
        try:
            with probe.cursor() as cursor:
                baseline = _graph_v420_baseline_present(cursor, database)
                closure = baseline and _graph_v421_closure_present(cursor, database)
                channels = _channel_objects_complete(cursor, database)
                governance = channels and _governance_lifecycle_complete(cursor, database)
                security = governance and _security_lifecycle_complete(cursor, database)
        finally:
            probe.close()
    except Exception:
        # The later preflight reports the connection error. Selecting the full
        # chain here keeps a transient probe failure from silently omitting a
        # prerequisite migration.
        baseline = closure = channels = governance = security = False

    names: list[str] = []
    if not baseline:
        names.extend([
            "9_v4_2_0_graph_engineering.sql",
            "10_v4_2_0_graph_runtime.sql",
            "11_v4_2_0_graph_control.sql",
            "12_v4_2_0_graph_edge_scope.sql",
        ])
        if edition == "enterprise":
            names.append("13_v4_2_0_scheduler_ha.sql")
        names.append("14_v4_2_0_graph_triggers.sql")
    if not closure:
        names.append("15_v4_2_1_executor_registry.sql")
    if not channels:
        names.append("16_v4_3_0_identity_channels.sql")
    if not governance:
        names.append("17_v4_3_0_governance_lifecycle.sql")
    if not security:
        names.append("18_v4_3_0_security_lifecycle.sql")
    # Keep a concrete idempotent lifecycle step for a fully applied database
    # so the ledger/preflight output still proves the current release target.
    return names or ["18_v4_3_0_security_lifecycle.sql"]


def _v431_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Select the v4.3 prerequisite chain and the organization step."""
    names = _v43_script_names(database, config_path, edition)
    try:
        config = _load_database_config(config_path)
        probe = _connect_for_preflight(database, config)
        try:
            with probe.cursor() as cursor:
                v43_complete = (
                    _channel_objects_complete(cursor, database)
                    and _governance_lifecycle_complete(cursor, database)
                    and _security_lifecycle_complete(cursor, database)
                )
                organization_complete = v43_complete and _organization_governance_complete(cursor, database)
                display_name_complete = v43_complete and _human_display_name_complete(cursor, database)
                entry_access_complete = v43_complete and _entry_access_complete(cursor, database)
                identity_org_complete = v43_complete and _identity_organization_alignment_complete(cursor, database)
        finally:
            probe.close()
    except Exception:
        v43_complete = organization_complete = display_name_complete = entry_access_complete = identity_org_complete = False
    if v43_complete and names == ["18_v4_3_0_security_lifecycle.sql"]:
        names = []
    if not organization_complete:
        names.append("19_v4_3_1_organization_governance.sql")
    if not display_name_complete:
        names.append("20_v4_3_1_human_display_name.sql")
    if not entry_access_complete:
        names.append("21_v4_3_1_entry_access.sql")
    if not identity_org_complete:
        names.append("22_v4_3_1_identity_organization_alignment.sql")
    return names or ["22_v4_3_1_identity_organization_alignment.sql"]


def _v432_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Select the full prerequisite chain and the idempotent Memory corrections."""
    names = _v431_script_names(database, config_path, edition)
    try:
        config = _load_database_config(config_path)
        probe = _connect_for_preflight(database, config)
        try:
            with probe.cursor() as cursor:
                complete = _memory_lifecycle_complete(cursor, database)
        finally:
            probe.close()
    except Exception:
        complete = False
    if complete and names == ["22_v4_3_1_identity_organization_alignment.sql"]:
        names = []
    if not complete:
        names.append("23_v4_3_2_memory_lifecycle.sql")
    # Step 24 upgrades the original step-23 legacy digest values without
    # changing its immutable ledger checksum.  It is safe to select on every
    # v4.3.2 invocation because the per-step ledger deduplicates it.
    names.append("24_v4_3_2_memory_digest_alignment.sql")
    # Step 25 removes the old direct-mutating scheduler. It must remain a
    # separate journaled correction so an already-applied step 23 is upgraded.
    names.append("25_v4_3_2_disable_legacy_memory_fusion.sql")
    names.append("26_v4_3_2_snapshot_subject_fencing.sql")
    names.append("27_v4_3_2_memory_governance_completion.sql")
    return names


def _v433_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Apply only the additive assurance step when v4.3.2 is already intact."""
    try:
        config = _load_database_config(config_path)
        probe = _connect_for_preflight(database, config)
        try:
            with probe.cursor() as cursor:
                baseline_complete = _memory_lifecycle_complete(cursor, database)
        finally:
            probe.close()
    except Exception:
        baseline_complete = False
    names = ["28_v4_3_3_graph_assurance.sql"] if baseline_complete else _v432_script_names(database, config_path, edition)
    if "28_v4_3_3_graph_assurance.sql" not in names:
        names.append("28_v4_3_3_graph_assurance.sql")
    return names


def _v434_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    # A few historical test baselines had v4.3.2/4.3.3 Graph and Memory
    # objects without the identity/Channel step.  Compliance depends on that
    # authority and must not execute its legacy backfill against a partial
    # schema.  Reuse the complete, idempotent v4.3.0 chain in that case.
    try:
        config = _load_database_config(config_path)
        probe = _connect_for_preflight(database, config)
        try:
            with probe.cursor() as cursor:
                channel_ready = _channel_objects_complete(cursor, database)
        finally:
            probe.close()
    except Exception:
        channel_ready = False
    names = _v433_script_names(database, config_path, edition) if channel_ready else _v43_script_names(database, config_path, edition)
    for name in _v432_script_names(database, config_path, edition):
        if name not in names:
            names.append(name)
    if "28_v4_3_3_graph_assurance.sql" not in names:
        names.append("28_v4_3_3_graph_assurance.sql")
    if edition.lower() == "enterprise":
        if "29_v4_3_4_agent_compliance.sql" not in names:
            names.append("29_v4_3_4_agent_compliance.sql")
        if "30_v4_3_4_compliance_hardening.sql" not in names:
            names.append("30_v4_3_4_compliance_hardening.sql")
    return names


def _v435_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Apply all prerequisites before the database-authoritative registry."""
    names = _v434_script_names(database, config_path, edition)
    if "31_v4_3_5_platform_capabilities.sql" not in names:
        names.append("31_v4_3_5_platform_capabilities.sql")
    return names


def _v436_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    names = _v435_script_names(database, config_path, edition)
    if "32_v4_3_6_native_agents.sql" not in names:
        names.append("32_v4_3_6_native_agents.sql")
    return names


def _v437_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    names = _v436_script_names(database, config_path, edition)
    if "33_v4_3_7_bootstrap_embedding.sql" not in names:
        names.append("33_v4_3_7_bootstrap_embedding.sql")
    return names


def _v440_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    """Add the native SDD step after the edition-aware v4.3.7 chain."""
    names = _v437_script_names(database, config_path, edition)
    if "34_v4_4_0_governed_sdd.sql" not in names:
        names.append("34_v4_4_0_governed_sdd.sql")
    return names


def _v441_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    names = _v440_script_names(database, config_path, edition)
    if "35_v4_4_1_admin_ha_upgrade.sql" not in names:
        names.append("35_v4_4_1_admin_ha_upgrade.sql")
    if "36_v4_4_1_upgrade_protocol.sql" not in names:
        names.append("36_v4_4_1_upgrade_protocol.sql")
    return names


def _v442_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    names = _v441_script_names(database, config_path, edition)
    if "37_v4_4_2_embedding_graph_operations.sql" not in names:
        names.append("37_v4_4_2_embedding_graph_operations.sql")
    if "38_v4_4_2_channel_pinning.sql" not in names:
        names.append("38_v4_4_2_channel_pinning.sql")
    return names


def _v443_script_names(database: str, config_path: Path, edition: str) -> list[str]:
    names = _v442_script_names(database, config_path, edition)
    if "39_v4_4_3_security_domain_binding.sql" not in names:
        names.append("39_v4_4_3_security_domain_binding.sql")
    return names


def _prepare_migration(conn: Any, database: str, script: Path) -> MigrationResult | None:
    checksum = _checksum(script)
    with conn.cursor() as cursor:
        _ensure_ledger(cursor, database)
        existing = _ledger_checksum(cursor, database)
        if existing is not None:
            if database == "pg" and existing == "embedded-v4.0.1" and MIGRATION_VERSION == "4.0.1":
                _record_ledger(cursor, checksum, database)
                conn.commit()
                return MigrationResult(
                    database=database, passed=True, checksum=checksum,
                    ledger_status="upgraded_legacy_checksum",
                )
            if existing != checksum:
                if _objects_complete(cursor, database):
                    return MigrationResult(
                        database=database, passed=False, checksum=checksum,
                        ledger_status="checksum_mismatch", error_type="ChecksumMismatch",
                    )
                if database == "pg":
                    cursor.execute("DELETE FROM ai_schema_migrations WHERE version = %s", (MIGRATION_VERSION,))
                else:
                    cursor.execute("DELETE FROM AI_SCHEMA_MIGRATIONS WHERE VERSION = :version", {"version": MIGRATION_VERSION})
            if _objects_complete(cursor, database):
                conn.commit()
                return MigrationResult(
                    database=database, passed=True, checksum=checksum,
                    ledger_status="already_applied",
                )
            # An earlier runner version could record the v4.1.0 checksum after
            # checking only v4.0.1 objects. Remove that incomplete ledger row
            # and execute the actual governance script below.
            if database == "pg":
                cursor.execute("DELETE FROM ai_schema_migrations WHERE version = %s", (MIGRATION_VERSION,))
            else:
                cursor.execute("DELETE FROM AI_SCHEMA_MIGRATIONS WHERE VERSION = :version", {"version": MIGRATION_VERSION})
        if _objects_complete(cursor, database):
            _record_ledger(cursor, checksum, database)
            conn.commit()
            return MigrationResult(
                database=database, passed=True, checksum=checksum,
                ledger_status="adopted_existing",
            )
    conn.commit()
    return None


def _statements(path: Path) -> list[str]:
    """Split deploy files while preserving SQL*Plus PL/SQL blocks.

    Oracle/YashanDB native graph declarations may contain semicolons inside a
    ``BEGIN ... END`` block and use a line containing ``/`` as the terminator.
    PostgreSQL ``DO $$`` blocks have the same property.  The previous plain
    ``text.split(';')`` parser turned those blocks into invalid fragments.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_block = False
    dollar_tag: str | None = None

    def flush() -> None:
        nonlocal buffer, in_block, dollar_tag
        was_block = in_block
        cleaned_lines = []
        for line in buffer:
            stripped = line.strip()
            if not stripped or stripped.startswith("--") or stripped.upper().startswith("PROMPT "):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()
        # Drivers execute Oracle PL/SQL blocks with the terminating END;.
        # Only standalone SQL needs its SQL*Plus semicolon removed.
        if not was_block:
            cleaned = cleaned.rstrip(";").strip()
        buffer = []
        in_block = False
        dollar_tag = None
        if cleaned and cleaned.upper() != "COMMIT":
            statements.append(cleaned)

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if stripped == "/":
            flush()
            continue
        if not buffer and (upper.startswith("PROMPT ") or upper.startswith("--")):
            continue
        buffer.append(line)
        if dollar_tag:
            if stripped.endswith(dollar_tag + ";"):
                flush()
            continue
        # PostgreSQL functions and DO blocks may contain ordinary semicolons
        # inside a dollar-quoted body.  Track the tag before the generic SQL
        # terminator check so the body is sent to the driver as one statement.
        dollar_match = re.search(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", line)
        if dollar_match and line.count(dollar_match.group(0)) == 1:
            dollar_tag = dollar_match.group(0)
            in_block = True
            continue
        # Some adapter migrations use the compact form ``BEGIN EXECUTE
        # IMMEDIATE ...``.  It is still a PL/SQL block and its internal
        # semicolons must not terminate the statement early.
        if not in_block and (
            upper == "BEGIN"
            or upper.startswith("BEGIN ")
            or upper == "DECLARE"
            or upper.startswith("DECLARE ")
            or upper.startswith("DO $$")
        ):
            in_block = True
        if not in_block and stripped.endswith(";"):
            flush()
        elif in_block and (upper == "$$;" or upper == "END;" or upper == "END $$;" or upper == "END /"):
            # A slash line is preferred for Oracle; this fallback handles
            # drivers/files that omit it after a single top-level block.
            if upper in {"$$;", "END $$;"}:
                flush()
    flush()
    return statements


def _error_code(exc: Exception) -> str:
    first = exc.args[0] if exc.args else None
    code = getattr(first, "code", None) or getattr(exc, "code", None)
    if code is not None:
        return str(code)
    match = re.search(r"(?:ORA-|YAS-)(\d+)", str(exc), re.IGNORECASE)
    return match.group(1) if match else ""


def _is_existing_object(exc: Exception) -> bool:
    code = _error_code(exc).lstrip("-")
    if code in {"955", "1430", "1408", "2043", "2261"}:
        return True
    message = str(exc).lower()
    return any(fragment in message for fragment in (
        "already exists", "duplicate column", "name is already used",
        "column being added already exists", "such column list already indexed",
    ))


def _apply_statement_migration(
    database: str,
    config: dict[str, Any],
    connect: Callable[[dict[str, Any]], Any],
    script: Path,
) -> MigrationResult:
    result = MigrationResult(database=database, passed=False, script=script.name)
    conn = connect(config)
    try:
        result.checksum = _checksum(script)
        if MIGRATION_VERSION in (CHANNEL_MIGRATION_VERSIONS | ORGANIZATION_MIGRATION_VERSIONS):
            with conn.cursor() as cursor:
                if _channel_schema_incomplete(cursor, database):
                    result.error_type = "SchemaIncomplete"
                    result.ledger_status = "blocked_incomplete_schema"
                    return result
        if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
            with conn.cursor() as cursor:
                _ensure_step_ledger(cursor, database)
                existing = _step_row(cursor, database, script)
                if existing:
                    if existing["checksum"] != result.checksum and existing["status"] == "APPLIED":
                        additive_upgrade = _channel_additive_columns_missing(cursor, database)
                        native_sdd_repair = (
                            _script_key(script) == "34_v4_4_0_governed_sdd"
                            and not _step_objects_complete(cursor, database, script)
                        )
                        admin_ha_repair = (
                            _script_key(script) == "35_v4_4_1_admin_ha_upgrade"
                            and not _step_objects_complete(cursor, database, script)
                        )
                        graph_operations_repair = (
                            _script_key(script) == "37_v4_4_2_embedding_graph_operations"
                            and not _step_objects_complete(cursor, database, script)
                        )
                        if additive_upgrade or native_sdd_repair or admin_ha_repair or graph_operations_repair:
                            # Continue below and replay the idempotent script. The
                            # early v4.3 draft is not accepted as complete until
                            # every fencing/claim column is present.
                            pass
                        elif _legacy_v441_step_compatible(cursor, database, script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, database, script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_v441_development_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        elif _legacy_v442_step_compatible(cursor, database, script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, database, script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_v442_pre_release_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        elif _legacy_graph_step_compatible(cursor, database, script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, database, script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_legacy_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        else:
                            result.error_type = "ChecksumMismatch"
                            result.ledger_status = "checksum_mismatch"
                            return result
                    step_complete = _step_objects_complete(cursor, database, script)
                    if existing["checksum"] == result.checksum and existing["status"] == "APPLIED" and step_complete:
                        permission_repair = (
                            database == "pg"
                            and _script_key(script) == "17_v4_3_0_governance_lifecycle"
                            and not _pg_thread_runtime_permissions_complete(cursor)
                        )
                        if not permission_repair:
                            result.passed = True
                            result.ledger_status = "already_applied"
                            result.statements_executed = existing["statements_executed"]
                            return result
                _upsert_step_row(cursor, database, script, result.checksum, "RUNNING")
            # Make the journal visible before the first DDL. This is the
            # durable retry marker when a process is interrupted mid-step.
            conn.commit()
        else:
            prepared = _prepare_migration(conn, database, script)
            if prepared is not None:
                prepared.script = script.name
                return prepared
        with conn.cursor() as cursor:
            for number, statement in enumerate(_statements(script), start=1):
                try:
                    cursor.execute(statement)
                    result.statements_executed += 1
                except Exception as exc:
                    if _is_existing_object(exc):
                        result.existing_objects_skipped += 1
                        continue
                    result.error_type = type(exc).__name__
                    result.error_code = _error_code(exc)
                    result.failed_statement = number
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
                        with conn.cursor() as journal:
                            _upsert_step_row(
                                journal, database, script, result.checksum, "FAILED",
                                result.statements_executed, number, result.error_code, str(exc),
                            )
                        conn.commit()
                    return result
            if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
                _upsert_step_row(
                    cursor, database, script, result.checksum, "APPLIED", result.statements_executed,
                )
            else:
                _record_ledger(cursor, result.checksum, database)
        conn.commit()
        result.passed = True
        result.ledger_status = "applied"
        return result
    finally:
        conn.close()


def _apply_oracle(config: dict[str, Any], script: Path) -> MigrationResult:
    import oracledb

    return _apply_statement_migration(
        "oracle", config,
        lambda cfg: oracledb.connect(
            user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"],
            tcp_connect_timeout=8,
        ),
        script,
    )


def _apply_yashandb(config: dict[str, Any], script: Path) -> MigrationResult:
    import yaspy

    return _apply_statement_migration(
        "yashandb", config,
        lambda cfg: yaspy.Connection(
            user=cfg["user"], password=cfg["password"], dsn=cfg["dsn"]
        ),
        script,
    )


def _apply_pg(config: dict[str, Any], script: Path) -> MigrationResult:
    import psycopg2

    result = MigrationResult(database="pg", passed=False, script=script.name)
    conn = psycopg2.connect(
        user=config["user"], password=config.get("password"), host=config["host"],
        port=int(config.get("port", 5432)), dbname=config["dbname"],
        connect_timeout=8,
    )
    try:
        result.checksum = _checksum(script)
        statements = _statements(script)
        if MIGRATION_VERSION in (CHANNEL_MIGRATION_VERSIONS | ORGANIZATION_MIGRATION_VERSIONS):
            with conn.cursor() as cursor:
                if _channel_schema_incomplete(cursor, "pg"):
                    result.error_type = "SchemaIncomplete"
                    result.ledger_status = "blocked_incomplete_schema"
                    return result
        if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
            with conn.cursor() as cursor:
                _ensure_step_ledger(cursor, "pg")
                existing = _step_row(cursor, "pg", script)
                if existing:
                    if existing["checksum"] != result.checksum and existing["status"] == "APPLIED":
                        additive_upgrade = _channel_additive_columns_missing(cursor, "pg")
                        native_sdd_repair = (
                            _script_key(script) == "34_v4_4_0_governed_sdd"
                            and not _step_objects_complete(cursor, "pg", script)
                        )
                        admin_ha_repair = (
                            _script_key(script) == "35_v4_4_1_admin_ha_upgrade"
                            and not _step_objects_complete(cursor, "pg", script)
                        )
                        graph_operations_repair = (
                            _script_key(script) == "37_v4_4_2_embedding_graph_operations"
                            and not _step_objects_complete(cursor, "pg", script)
                        )
                        if additive_upgrade or native_sdd_repair or admin_ha_repair or graph_operations_repair:
                            pass
                        elif _legacy_v441_step_compatible(cursor, "pg", script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, "pg", script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_v441_development_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        elif _legacy_v442_step_compatible(cursor, "pg", script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, "pg", script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_v442_pre_release_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        elif _legacy_graph_step_compatible(cursor, "pg", script, existing["checksum"]):
                            _upsert_step_row(
                                cursor, "pg", script, result.checksum, "APPLIED",
                                existing["statements_executed"], existing["failed_statement"],
                            )
                            conn.commit()
                            result.passed = True
                            result.ledger_status = "adopted_legacy_checksum"
                            result.statements_executed = existing["statements_executed"]
                            return result
                        else:
                            result.error_type = "ChecksumMismatch"
                            result.ledger_status = "checksum_mismatch"
                            return result
                    step_complete = _step_objects_complete(cursor, "pg", script)
                    if existing["checksum"] == result.checksum and existing["status"] == "APPLIED" and step_complete:
                        result.passed = True
                        result.ledger_status = "already_applied"
                        result.statements_executed = existing["statements_executed"]
                        return result
                _upsert_step_row(cursor, "pg", script, result.checksum, "RUNNING")
            conn.commit()
        else:
            prepared = _prepare_migration(conn, "pg", script)
            if prepared is not None:
                prepared.script = script.name
                return prepared
        with conn.cursor() as cursor:
            # PostgreSQL receives the complete file in one transaction so
            # AGE/DDL blocks and their IF NOT EXISTS guards remain atomic.
            cursor.execute(script.read_text(encoding="utf-8"))
            result.statements_executed = len(statements) or 1
            if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
                _upsert_step_row(cursor, "pg", script, result.checksum, "APPLIED", result.statements_executed)
            else:
                _record_ledger(cursor, result.checksum, "pg")
        conn.commit()
        result.passed = True
        result.ledger_status = "applied"
    except Exception as exc:
        conn.rollback()
        result.error_type = type(exc).__name__
        result.error_code = getattr(exc, "pgcode", "") or ""
        result.error_object = getattr(getattr(exc, "diag", None), "constraint_name", "") or ""
        result.failed_statement = max(1, result.statements_executed + 1)
        if MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS:
            try:
                with conn.cursor() as cursor:
                    _ensure_step_ledger(cursor, "pg")
                    _upsert_step_row(
                        cursor, "pg", script, result.checksum, "FAILED",
                        result.statements_executed, result.failed_statement, result.error_code, str(exc),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
    finally:
        conn.close()
    return result


def _connect_for_preflight(database: str, config: dict[str, Any]) -> Any:
    if database == "oracle":
        import oracledb
        return oracledb.connect(
            user=config["user"], password=config["password"], dsn=config["dsn"],
            tcp_connect_timeout=8,
        )
    if database == "yashandb":
        import yaspy
        return yaspy.Connection(user=config["user"], password=config["password"], dsn=config["dsn"])
    import psycopg2
    return psycopg2.connect(
        user=config["user"], password=config.get("password"), host=config["host"],
        port=int(config.get("port", 5432)), dbname=config["dbname"], connect_timeout=8,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", choices=("all", "oracle", "pg", "yashandb"), default="all")
    parser.add_argument("--version", choices=("4.0.1", "4.1.0", "4.2.0", "4.2.1", "4.3.0", "4.3.1", "4.3.2", "4.3.3", "4.3.4", "4.3.5", "4.3.6", "4.3.7", "4.4.0", "4.4.1", "4.4.2", "4.4.3"), default="4.1.0")
    parser.add_argument("--edition", choices=("community", "enterprise"), default="community",
                        help="v4.2 scheduler scope; Community excludes Enterprise HA objects")
    parser.add_argument("--oracle-config", type=Path)
    parser.add_argument("--pg-config", type=Path)
    parser.add_argument("--yashandb-config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preflight", action="store_true", help="run read-only readiness checks only")
    parser.add_argument("--dry-run", action="store_true", help="show checksums and capacity without changing the database")
    parser.add_argument("--capacity-tier", type=int, choices=(5000, 10000, 50000, 100000),
                        help="benchmark tier used for non-destructive capacity evidence")
    parser.add_argument("--backup-evidence", type=Path,
                        help="JSON manifest proving that a recoverable pre-migration backup exists")
    args = parser.parse_args()

    global MIGRATION_VERSION, MIGRATION_EDITION
    MIGRATION_VERSION = args.version
    MIGRATION_EDITION = args.edition
    paths = {
        "oracle": args.oracle_config,
        "pg": args.pg_config,
        "yashandb": args.yashandb_config,
    }
    runners = {"oracle": _apply_oracle, "pg": _apply_pg, "yashandb": _apply_yashandb}
    backup_verified, backup_message = verify_backup_evidence(args.backup_evidence)
    results = []
    preflight_results = []
    available_databases = _available_databases()
    if args.database != "all" and args.database not in available_databases:
        parser.error(
            f"database {args.database!r} is not available in this source tree or package"
        )
    selected = available_databases if args.database == "all" else (args.database,)
    for database in selected:
        if paths[database] is None:
            parser.error(f"--{database}-config is required for {database}")
        if MIGRATION_VERSION == "4.0.1":
            script_names = ["7_v4_0_1_migration.sql"]
        elif MIGRATION_VERSION == "4.1.0":
            script_names = ["8_v4_1_0_governance.sql"]
        elif MIGRATION_VERSION == "4.3.0":
            script_names = _v43_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.1":
            script_names = _v431_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.2":
            script_names = _v432_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.3":
            script_names = _v433_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.4":
            script_names = _v434_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.5":
            script_names = _v435_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.6":
            script_names = _v436_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.3.7":
            script_names = _v437_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.4.0":
            script_names = _v440_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.4.1":
            script_names = _v441_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.4.2":
            script_names = _v442_script_names(database, paths[database], MIGRATION_EDITION)
        elif MIGRATION_VERSION == "4.4.3":
            script_names = _v443_script_names(database, paths[database], MIGRATION_EDITION)
        else:
            script_names = [
                "9_v4_2_0_graph_engineering.sql", "10_v4_2_0_graph_runtime.sql",
                "11_v4_2_0_graph_control.sql", "12_v4_2_0_graph_edge_scope.sql",
            ]
        if MIGRATION_VERSION in GRAPH_MIGRATION_VERSIONS and MIGRATION_EDITION == "enterprise":
            script_names.append("13_v4_2_0_scheduler_ha.sql")
        if MIGRATION_VERSION in GRAPH_MIGRATION_VERSIONS:
            script_names.append("14_v4_2_0_graph_triggers.sql")
        if MIGRATION_VERSION == "4.2.1":
            # A normal v4.2.0 -> v4.2.1 upgrade only needs the additive
            # registry step.  A clean v4.1.x database still receives the
            # complete Graph prerequisite chain before that step.
            try:
                config_for_selection = _load_database_config(paths[database])
                probe_for_selection = _connect_for_preflight(database, config_for_selection)
                try:
                    with probe_for_selection.cursor() as cursor:
                        baseline_present = _graph_v420_baseline_present(cursor, database)
                finally:
                    probe_for_selection.close()
            except Exception:
                baseline_present = False
            if baseline_present:
                script_names = []
            script_names.append("15_v4_2_1_executor_registry.sql")
        scripts = [_deployment_script(database, name) for name in script_names]
        if any(not script.is_file() for script in scripts):
            parser.error(f"migration script is missing for {database}: {[str(script) for script in scripts if not script.is_file()]}")
        try:
            config = _load_database_config(paths[database])
            connection_for_probe = _connect_for_preflight(database, config)
            try:
                preflight = _preflight(connection_for_probe, database, scripts, args.capacity_tier)
            finally:
                connection_for_probe.close()
            preflight_results.append(preflight)
            graph_backup_missing = MIGRATION_VERSION in JOURNALED_MIGRATION_VERSIONS and not backup_verified
            if args.preflight or args.dry_run or graph_backup_missing:
                warnings = []
                if graph_backup_missing:
                    warnings.append(backup_message)
                results.append(MigrationResult(
                    database=database,
                    passed=bool(preflight.get("passed")) and not graph_backup_missing,
                    script="preflight",
                    mode="dry-run" if args.dry_run else "preflight",
                    checksum=hashlib.sha256("".join(item["checksum"] for item in preflight["scripts"]).encode()).hexdigest(),
                    ledger_status="ready" if preflight.get("passed") and not graph_backup_missing else "blocked",
                    backup_verified=backup_verified,
                    capacity=preflight.get("capacity"),
                    warnings=warnings or None,
                ))
                continue
            per_script = []
            for script in scripts:
                result = runners[database](config, script)
                per_script.append(result)
                if not result.passed:
                    break
            if len(per_script) == 1:
                aggregate = per_script[0]
            else:
                final = per_script[-1]
                statuses = [item.ledger_status for item in per_script]
                if all(status == "already_applied" for status in statuses):
                    aggregate_status = "already_applied"
                elif all(status == "applied" for status in statuses):
                    aggregate_status = "applied"
                elif all(item.passed for item in per_script):
                    aggregate_status = "applied_with_retry"
                else:
                    aggregate_status = final.ledger_status
                aggregate = MigrationResult(
                    database=database, passed=all(item.passed for item in per_script),
                    script="aggregate", mode="apply",
                    statements_executed=sum(item.statements_executed for item in per_script),
                    existing_objects_skipped=sum(item.existing_objects_skipped for item in per_script),
                    error_type=final.error_type, error_code=final.error_code,
                    error_object=final.error_object, failed_statement=final.failed_statement,
                    checksum=hashlib.sha256("".join(item.checksum for item in per_script).encode()).hexdigest(),
                    ledger_status=aggregate_status,
                    step_statuses=[
                        {
                            "script": item.script,
                            "passed": item.passed,
                            "ledger_status": item.ledger_status,
                            "statements_executed": item.statements_executed,
                            "existing_objects_skipped": item.existing_objects_skipped,
                        }
                        for item in per_script
                    ],
                )
            aggregate.backup_verified = backup_verified
            aggregate.capacity = preflight.get("capacity")
            results.append(aggregate)
        except Exception as exc:
            results.append(MigrationResult(
                database=database, passed=False, script="preflight", mode="preflight",
                backup_verified=backup_verified, error_type=type(exc).__name__,
                error_code=_error_code(exc),
            ))

    payload = {
        "schema": "ai-agent-infra-migration-evidence/v1",
        "version": MIGRATION_VERSION,
        "edition": MIGRATION_EDITION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry-run" if args.dry_run else ("preflight" if args.preflight else "apply"),
        "backup": {"verified": backup_verified, "message": backup_message},
        "preflight": preflight_results,
        "results": [asdict(result) for result in results],
        "passed": bool(results) and all(result.passed for result in results),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
