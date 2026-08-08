#!/usr/bin/env python3.14
"""Read-only live database capability probe for v4.1.0 release evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent


def _resolve_repo_root() -> Path:
    """Resolve the source root or the root of a generated package.

    Source tools live at the repository root. Generated packages place the
    tool under ``scripts/`` and keep ``build-manifest.json`` one directory
    above it. Looking for the manifest avoids depending on the caller's
    working directory while retaining the source-tree fallback.
    """
    if (_SCRIPT_DIR / "build-manifest.json").is_file():
        return _SCRIPT_DIR
    packaged_root = _SCRIPT_DIR.parent
    if (packaged_root / "build-manifest.json").is_file():
        return packaged_root
    return _SCRIPT_DIR


REPO_ROOT = _resolve_repo_root()
LEGACY_KEY_PATH = Path.home() / ".oracle-infra" / "master.key"


def _available_databases() -> tuple[str, ...]:
    """Return all source adapters or the single adapter in a generated package."""
    manifest_path = REPO_ROOT / "build-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        manifest = {}
    key = str((manifest.get("database") or {}).get("key") or "").lower()
    if key in {"oracle", "pg", "yashandb"}:
        return (key,)
    return ("oracle", "pg", "yashandb")


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
GRAPH_TABLES = (
    "GRAPH_DEFINITIONS", "GRAPH_VERSIONS", "GRAPH_NODES", "GRAPH_EDGES",
    "GRAPH_ALIASES", "GRAPH_TYPE_REGISTRY", "GRAPH_COMPILE_PLANS",
    "GRAPH_RUNS", "GRAPH_NODE_RUNS", "GRAPH_ATTEMPTS", "GRAPH_READY_NODES",
    "GRAPH_WORKERS", "GRAPH_LEASE_TOKENS", "GRAPH_CHECKPOINTS",
    "GRAPH_STATE_EVENTS", "GRAPH_TRANSITIONS", "GRAPH_INBOX", "GRAPH_OUTBOX",
    "GRAPH_ARTIFACTS", "GRAPH_EVALUATIONS", "GRAPH_INTERVENTIONS",
    "GRAPH_JOIN_STATES", "GRAPH_RUN_BRANCHES", "GRAPH_WAIT_SUBSCRIPTIONS",
    "GRAPH_TRACES", "GRAPH_RUN_MIGRATIONS", "GRAPH_COMPAT_BINDINGS",
    "GRAPH_TRIGGERS", "GRAPH_EXECUTOR_REGISTRY", "GRAPH_GOVERNANCE_EVENTS",
)


# v4.3.0 is deliberately described here once and consumed by both the
# read-only probe and migration_runner.py.  Keeping the contract beside the
# probe also means generated packages ship the same validation rules as the
# source tree without another packaging-only module.
V43_MIGRATION_SCRIPTS = (
    "16_v4_3_0_identity_channels.sql",
    "17_v4_3_0_governance_lifecycle.sql",
    "18_v4_3_0_security_lifecycle.sql",
)

V431_MIGRATION_SCRIPTS = V43_MIGRATION_SCRIPTS + (
    "19_v4_3_1_organization_governance.sql",
    "20_v4_3_1_human_display_name.sql",
    "21_v4_3_1_entry_access.sql",
    "22_v4_3_1_identity_organization_alignment.sql",
)

V432_MIGRATION_SCRIPTS = V431_MIGRATION_SCRIPTS + (
    "23_v4_3_2_memory_lifecycle.sql",
    "24_v4_3_2_memory_digest_alignment.sql",
    "25_v4_3_2_disable_legacy_memory_fusion.sql",
    "26_v4_3_2_snapshot_subject_fencing.sql",
    "27_v4_3_2_memory_governance_completion.sql",
)

V433_MIGRATION_SCRIPTS = V432_MIGRATION_SCRIPTS + (
    "28_v4_3_3_graph_assurance.sql",
)

V433_GRAPH_ASSURANCE_TABLES = (
    "GRAPH_ASSURANCE_EVIDENCE", "GRAPH_DEFINITION_PROVENANCE", "GRAPH_DEFINITION_DEPENDENCIES",
    "GRAPH_DEFINITION_SIGNATURES", "GRAPH_DEFINITION_SCANS", "GRAPH_DYNAMIC_PROPOSALS",
    "GRAPH_PROTOCOL_TASKS", "GRAPH_TELEMETRY_DELIVERIES",
)

V434_MIGRATION_SCRIPTS = V433_MIGRATION_SCRIPTS + (
    "29_v4_3_4_agent_compliance.sql",
    "30_v4_3_4_compliance_hardening.sql",
)
V434_COMPLIANCE_TABLES = (
    "CX_AGENT_PROFILES", "CX_AGENT_PROFILE_VERSIONS", "CX_AGENT_PROFILE_ASSIGNMENTS",
    "CX_AGENT_ACTIVATIONS", "CX_AGENT_POSTURES", "CX_AGENT_POSTURE_EVIDENCE",
    "CX_COMPLIANCE_FINDINGS", "CX_COMPLIANCE_REMEDIATION_CASES",
    "CX_COMPLIANCE_EXCEPTIONS", "CX_COMPLIANCE_CONTROLLER_JOBS",
)
V434_COMPLIANCE_REQUIRED_COLUMNS = {
    "CX_AGENT_PROFILES": frozenset({"PROFILE_ID", "PROFILE_KEY", "DISPLAY_NAME", "STATUS", "CREATED_BY"}),
    "CX_AGENT_PROFILE_VERSIONS": frozenset({"PROFILE_VERSION_ID", "PROFILE_ID", "CONTENT_JSON", "CONTENT_DIGEST", "STATUS"}),
    "CX_AGENT_PROFILE_ASSIGNMENTS": frozenset({"ASSIGNMENT_ID", "AGENT_ID", "PROFILE_VERSION_ID", "ENVIRONMENT", "STATUS"}),
    "CX_AGENT_ACTIVATIONS": frozenset({"ACTIVATION_ID", "AGENT_ID", "EVIDENCE_STRENGTH", "BASELINE_DIGEST", "STATUS"}),
    "CX_AGENT_POSTURES": frozenset({"POSTURE_ID", "AGENT_ID", "REGISTRATION_STATE", "RUNTIME_STATE", "POSTURE_STATE", "CONTROL_STATE", "VERSION"}),
    "CX_AGENT_POSTURE_EVIDENCE": frozenset({"EVIDENCE_ID", "AGENT_ID", "EVIDENCE_TYPE", "PROVIDER", "PAYLOAD_DIGEST"}),
    "CX_COMPLIANCE_FINDINGS": frozenset({"FINDING_ID", "AGENT_ID", "RULE_CODE", "SEVERITY", "STATUS", "DEADLINE_AT"}),
    "CX_COMPLIANCE_REMEDIATION_CASES": frozenset({"CASE_ID", "FINDING_ID", "AGENT_ID", "STATUS", "RESPONSE_EVIDENCE_ID"}),
    "CX_COMPLIANCE_EXCEPTIONS": frozenset({"EXCEPTION_ID", "POLICY_KEY", "REQUESTED_BY", "APPROVED_BY", "DECISION_REASON", "STATUS", "EXPIRES_AT"}),
    "CX_COMPLIANCE_CONTROLLER_JOBS": frozenset({"JOB_ID", "JOB_TYPE", "STATUS", "FENCING_TOKEN", "IDEMPOTENCY_KEY"}),
}

V435_MIGRATION_SCRIPTS = V434_MIGRATION_SCRIPTS + (
    "31_v4_3_5_platform_capabilities.sql",
)
V435_PLATFORM_TABLES = (
    "CX_PLATFORM_CAPABILITIES", "CX_PLATFORM_CAPABILITY_DEPENDENCIES",
    "CX_PLATFORM_CAPABILITY_HISTORY",
)
V435_PLATFORM_REQUIRED_COLUMNS = {
    "CX_PLATFORM_CAPABILITIES": frozenset({
        "CAPABILITY_KEY", "ENABLED", "MANDATORY", "VERSION", "UPDATED_BY",
        "UPDATE_REASON", "CREATED_AT", "UPDATED_AT",
    }),
    "CX_PLATFORM_CAPABILITY_DEPENDENCIES": frozenset({"CAPABILITY_KEY", "DEPENDS_ON_KEY"}),
    "CX_PLATFORM_CAPABILITY_HISTORY": frozenset({
        "HISTORY_ID", "CAPABILITY_KEY", "FROM_ENABLED", "TO_ENABLED",
        "RESULT_VERSION", "CHANGED_BY", "REASON", "CREATED_AT",
    }),
}

V436_MIGRATION_SCRIPTS = V435_MIGRATION_SCRIPTS + (
    "32_v4_3_6_native_agents.sql",
)
V436_NATIVE_AGENT_TABLES = (
    "CX_NATIVE_BOOTSTRAP", "CX_AGENT_TEMPLATES", "CX_NATIVE_MANIFESTS", "CX_NATIVE_AGENTS",
    "CX_LLM_PROVIDER_PROFILES", "CX_DEPLOYMENT_TARGETS",
    "CX_NATIVE_PROVISION_REQUESTS", "CX_RUNTIME_WORKERS",
    "CX_RUNTIME_EXECUTIONS", "CX_EXTERNAL_AGENT_POLICY",
    "CX_EXTERNAL_AGENT_POLICY_HISTORY",
)
V436_NATIVE_AGENT_REQUIRED_COLUMNS = {
    "CX_NATIVE_BOOTSTRAP": frozenset({"BOOTSTRAP_KEY", "BOOTSTRAP_VERSION", "STATUS"}),
    "CX_AGENT_TEMPLATES": frozenset({"TEMPLATE_ID", "TEMPLATE_KEY", "CONTENT_JSON", "CONTENT_DIGEST", "STATUS"}),
    "CX_NATIVE_MANIFESTS": frozenset({"MANIFEST_ID", "MANIFEST_KEY", "VERSION", "CONTENT_DIGEST", "SIGNATURE", "SIGNATURE_STATUS", "STATUS"}),
    "CX_NATIVE_AGENTS": frozenset({"AGENT_ID", "SOURCE", "AGENT_KIND", "STATUS", "ACTIVATION_STATE", "DEPLOYMENT_TARGET_ID"}),
    "CX_LLM_PROVIDER_PROFILES": frozenset({"PROFILE_ID", "PROFILE_KEY", "PROVIDER_URL", "MODEL_ID", "API_KEY_CIPHER", "STATUS"}),
    "CX_DEPLOYMENT_TARGETS": frozenset({"TARGET_ID", "TARGET_KEY", "TARGET_TYPE", "CONFIG_JSON", "STATUS"}),
    "CX_NATIVE_PROVISION_REQUESTS": frozenset({"REQUEST_ID", "APPLICANT_PRINCIPAL_ID", "OWNER_PRINCIPAL_ID", "STATUS", "REASON"}),
    "CX_RUNTIME_WORKERS": frozenset({"WORKER_ID", "NODE_ID", "STATUS", "FENCING_TOKEN"}),
    "CX_RUNTIME_EXECUTIONS": frozenset({"EXECUTION_ID", "AGENT_ID", "STATUS", "INPUT_JSON", "FENCING_TOKEN"}),
    "CX_EXTERNAL_AGENT_POLICY": frozenset({"POLICY_KEY", "STATE", "VERSION", "REASON"}),
    "CX_EXTERNAL_AGENT_POLICY_HISTORY": frozenset({"HISTORY_ID", "POLICY_KEY", "FROM_STATE", "TO_STATE", "RESULT_VERSION"}),
}

V432_MEMORY_TABLES = (
    "CX_MEMORY_FAMILIES", "CX_MEMORY_VERSIONS", "CX_MEMORY_REPRESENTATIONS",
    "CX_MEMORY_RELATIONS", "CX_MEMORY_SNAPSHOTS", "CX_MEMORY_SNAPSHOT_MEMBERS",
    "CX_MEMORY_POLICIES", "CX_MEMORY_JOBS", "CX_MEMORY_JOB_ITEMS",
    "CX_MEMORY_USAGE_EVENTS", "CX_MEMORY_CANDIDATES", "CX_MEMORY_REVIEWS",
    "CX_MEMORY_PROJECTION_OUTBOX",
    "CX_MEMORY_VERSION_ARTIFACTS", "CX_MEMORY_INGESTION_FINDINGS", "CX_MEMORY_WORKER_RESULTS",
)

V432_MEMORY_REQUIRED_COLUMNS = {
    "CX_MEMORY_FAMILIES": frozenset({"FAMILY_ID", "CURRENT_VERSION_ID", "LEGACY_ENTITY_ID", "ROW_VERSION"}),
    "CX_MEMORY_VERSIONS": frozenset({"VERSION_ID", "FAMILY_ID", "VERSION_NUMBER", "CONTENT_DIGEST", "MEMORY_TYPE", "MEMORY_SCOPE", "LIFECYCLE_STATE"}),
    "CX_MEMORY_REPRESENTATIONS": frozenset({"REPRESENTATION_ID", "VERSION_ID", "REPRESENTATION_TYPE", "CONTENT_DIGEST", "TOKEN_COUNT"}),
    "CX_MEMORY_RELATIONS": frozenset({"RELATION_ID", "SOURCE_VERSION_ID", "TARGET_VERSION_ID", "RELATION_TYPE", "RELATION_STATE"}),
    "CX_MEMORY_SNAPSHOTS": frozenset({"SNAPSHOT_ID", "RUN_ID", "SNAPSHOT_VERSION", "SNAPSHOT_DIGEST", "PRINCIPAL_ID", "PRINCIPAL_PERMISSION_VERSION", "AGENT_INSTANCE_ID", "AGENT_FENCING_TOKEN"}),
    "CX_MEMORY_JOBS": frozenset({"JOB_ID", "JOB_TYPE", "STATUS", "FENCING_TOKEN"}),
    "CX_MEMORY_CANDIDATES": frozenset({"CANDIDATE_ID", "CANDIDATE_TYPE", "STATUS", "POLICY_RESULT"}),
    "CX_MEMORY_PROJECTION_OUTBOX": frozenset({"OUTBOX_ID", "AGGREGATE_ID", "EVENT_TYPE", "STATUS"}),
    "CX_MEMORY_VERSION_ARTIFACTS": frozenset({"LINK_ID", "VERSION_ID", "ARTIFACT_ID", "RELATION_TYPE"}),
    "CX_MEMORY_INGESTION_FINDINGS": frozenset({"FINDING_ID", "VERSION_ID", "FINDING_TYPE", "CONTENT_DIGEST", "STATUS"}),
    "CX_MEMORY_WORKER_RESULTS": frozenset({"RESULT_ID", "JOB_ITEM_ID", "WORKER_ID", "FENCING_TOKEN", "VALIDATION_STATE"}),
}

V431_ORGANIZATION_TABLES = (
    "CX_REPORTING_RELATIONSHIPS", "CX_ORGANIZATION_CLOSURE",
    "CX_ORGANIZATION_VERSIONS", "CX_ORGANIZATION_UNIT_HISTORY",
    "CX_ORGANIZATION_MEMBER_HISTORY", "CX_REPORTING_HISTORY",
    "CX_ORG_CHANGESETS", "CX_ORG_CHANGE_OPERATIONS",
    "CX_DIRECTORY_SYNC_BATCHES", "CX_DIRECTORY_SOURCE_RECORDS",
    "CX_DIRECTORY_CONFLICTS", "CX_ORG_LIFECYCLE_CASES", "CX_ORG_DISPOSITIONS",
)

V431_ORGANIZATION_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({
        "PRINCIPAL_ID", "PRINCIPAL_TYPE", "DISPLAY_NAME", "STATUS",
    }),
    "CX_REGISTRATION_REQUESTS": frozenset({
        "REQUEST_ID", "USERNAME", "DISPLAY_NAME", "STATUS",
    }),
    "CX_ORGANIZATIONS": frozenset({
        "ORGANIZATION_ID", "PARENT_ID", "ORGANIZATION_NAME", "ORGANIZATION_CODE",
        "ORGANIZATION_TYPE", "IS_LEGAL_ENTITY", "SORT_ORDER", "VALID_FROM",
        "VALID_UNTIL", "SOURCE_TYPE", "ROW_VERSION", "STATUS",
    }),
    "CX_ORGANIZATION_MEMBERS": frozenset({
        "MEMBERSHIP_ID", "ORGANIZATION_ID", "PRINCIPAL_ID", "MEMBERSHIP_KIND",
        "VALID_FROM", "VALID_UNTIL", "SOURCE_TYPE", "ROW_VERSION", "STATUS",
    }),
    "CX_REPORTING_RELATIONSHIPS": frozenset({
        "RELATIONSHIP_ID", "PRINCIPAL_ID", "MANAGER_PRINCIPAL_ID",
        "RELATIONSHIP_TYPE", "VALID_FROM", "VALID_UNTIL", "SOURCE_TYPE",
        "ROW_VERSION", "STATUS",
    }),
    "CX_ORGANIZATION_CLOSURE": frozenset({"ANCESTOR_ID", "DESCENDANT_ID", "DEPTH"}),
    "CX_ORGANIZATION_VERSIONS": frozenset({
        "VERSION_ID", "VERSION_NUMBER", "CHANGE_SET_ID", "STATUS", "EFFECTIVE_AT",
        "REASON", "CREATED_BY",
    }),
    "CX_ORGANIZATION_UNIT_HISTORY": frozenset({
        "HISTORY_ID", "VERSION_ID", "ORGANIZATION_ID", "OPERATION", "FACT_JSON",
        "FACT_DIGEST", "ACTOR_PRINCIPAL_ID", "REASON",
    }),
    "CX_ORGANIZATION_MEMBER_HISTORY": frozenset({
        "HISTORY_ID", "VERSION_ID", "MEMBERSHIP_ID", "PRINCIPAL_ID",
        "ORGANIZATION_ID", "OPERATION", "FACT_JSON", "FACT_DIGEST",
    }),
    "CX_REPORTING_HISTORY": frozenset({
        "HISTORY_ID", "VERSION_ID", "RELATIONSHIP_ID", "PRINCIPAL_ID",
        "MANAGER_PRINCIPAL_ID", "OPERATION", "FACT_JSON", "FACT_DIGEST",
    }),
    "CX_ORG_CHANGESETS": frozenset({
        "CHANGE_SET_ID", "BASE_VERSION_ID", "AUTHOR_PRINCIPAL_ID", "STATUS",
        "REASON", "RISK_LEVEL", "IDEMPOTENCY_KEY", "ROW_VERSION",
    }),
    "CX_ORG_CHANGE_OPERATIONS": frozenset({
        "OPERATION_ID", "CHANGE_SET_ID", "SEQUENCE_NUMBER", "OPERATION_TYPE",
        "TARGET_TYPE", "COMMAND_JSON", "AFTER_DIGEST", "STATUS",
    }),
    "CX_DIRECTORY_SYNC_BATCHES": frozenset({
        "SYNC_BATCH_ID", "CONNECTOR_ID", "CONNECTOR_TYPE", "SOURCE_DIGEST",
        "STATUS", "REQUESTED_BY", "CHANGE_SET_ID",
    }),
    "CX_DIRECTORY_SOURCE_RECORDS": frozenset({
        "SOURCE_RECORD_ID", "SYNC_BATCH_ID", "CONNECTOR_ID", "EXTERNAL_OBJECT_ID",
        "OBJECT_TYPE", "SOURCE_DIGEST", "NORMALIZED_JSON", "STATUS",
    }),
    "CX_DIRECTORY_CONFLICTS": frozenset({
        "CONFLICT_ID", "SYNC_BATCH_ID", "OBJECT_TYPE", "FIELD_NAME",
        "AUTHORITY_SOURCE", "RISK_LEVEL", "STATUS",
    }),
    "CX_ORG_LIFECYCLE_CASES": frozenset({
        "LIFECYCLE_CASE_ID", "SUBJECT_TYPE", "SUBJECT_ID", "LIFECYCLE_TYPE",
        "STATUS", "REASON", "ROW_VERSION", "CREATED_BY",
    }),
    "CX_ORG_DISPOSITIONS": frozenset({
        "DISPOSITION_ID", "LIFECYCLE_CASE_ID", "CHANGE_SET_ID", "SUBJECT_TYPE",
        "SUBJECT_ID", "DISPOSITION_TYPE", "STATUS", "REASON",
    }),
}

V431_ENTRY_ACCESS_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({"PORTAL_ACCESS", "APP_ACCESS", "ORGANIZATION_REQUIRED"}),
}

V431_INDEX_CONTRACT = {
    "IDX_CX_ORG_ACTIVE_PRIMARY": ("CX_ORGANIZATION_MEMBERS", True),
    "IDX_CX_REPORTING_ACTIVE_DIRECT": ("CX_REPORTING_RELATIONSHIPS", True),
    "IDX_CX_ORG_CLOSURE_DESC": ("CX_ORGANIZATION_CLOSURE", False),
    "IDX_CX_ORG_CLOSURE_ANCESTOR": ("CX_ORGANIZATION_CLOSURE", False),
    "IDX_CX_ORG_CHANGESET_STATE": ("CX_ORG_CHANGESETS", False),
    "IDX_CX_DIRECTORY_CONFLICT": ("CX_DIRECTORY_CONFLICTS", False),
}

V43_BASE_TABLES = (
    "CX_PRINCIPALS", "CX_HUMAN_IDENTITIES", "CX_REGISTRATION_REQUESTS", "CX_WEB_SESSIONS",
    "CX_ROLE_TEMPLATES", "CX_USER_ROLES", "CX_USER_PERMISSION_OVERRIDES",
    "CX_ORGANIZATIONS", "CX_ORGANIZATION_MEMBERS", "CX_RESPONSIBLE_GROUPS",
    "CX_RESPONSIBLE_GROUP_MEMBERS", "CX_SECURITY_DOMAINS", "CX_DOMAIN_MEMBERS",
    "CX_ENROLLMENT_GRANTS", "CX_ENROLLMENT_TOKENS", "CX_AGENT_RELATIONSHIPS",
    "CX_AGENT_CREDENTIALS", "CX_AGENT_ACCESS_TOKENS", "CX_CHANNELS", "CX_CHANNEL_MEMBERS",
    "CX_CHANNEL_MESSAGES", "CX_BARRIERS", "CX_BARRIER_ARRIVALS", "CX_ACTION_CARDS",
    "CX_NOTIFICATIONS", "CX_SECURITY_EVENTS", "CX_BRIDGES", "CX_AGENT_INSTANCES",
    "CX_AGENT_DELIVERIES", "CX_CHANNEL_MEMORY_CANDIDATES", "CX_BRIDGE_TRANSFERS",
)
V43_GOVERNANCE_TABLES = (
    "CX_CHANNEL_THREADS", "CX_CHANNEL_THREAD_MEMBERS", "CX_RUNTIME_PROFILE_CHANGES",
)
V43_SECURITY_TABLES = (
    "CX_MFA_FACTORS", "CX_MFA_RECOVERY_CODES", "CX_PASSWORD_RESET_TOKENS",
    "CX_IDENTITY_LINK_AUDIT", "CX_DELEGATIONS", "CX_AGENT_QUOTAS",
    "CX_AGENT_OWNERSHIP_HISTORY", "CX_AGENT_LEGACY_REVIEWS", "CX_AGENT_DERIVED_OBJECTS",
    "CX_CHANNEL_DELETION_EVIDENCE", "CX_MEMORY_ARTIFACT_LINKS", "CX_BRIDGE_CONNECTORS",
)
V43_REQUIRED_TABLES = V43_BASE_TABLES + V43_GOVERNANCE_TABLES + V43_SECURITY_TABLES

# These are the portable columns needed by the lifecycle APIs.  The contract
# intentionally checks more than a table name: an old draft with the right
# table names but missing fencing, ownership, or evidence fields is not an
# applied migration.
V43_BASE_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({"PRINCIPAL_ID", "PRINCIPAL_TYPE", "STATUS", "PERMISSION_VERSION"}),
    "CX_HUMAN_IDENTITIES": frozenset({"IDENTITY_ID", "PRINCIPAL_ID", "IDENTITY_TYPE", "SUBJECT_KEY", "PASSWORD_HASH", "STATUS"}),
    "CX_REGISTRATION_REQUESTS": frozenset({"REQUEST_ID", "USERNAME", "PASSWORD_HASH", "STATUS", "CREATED_AT"}),
    "CX_WEB_SESSIONS": frozenset({"SESSION_DIGEST", "PRINCIPAL_ID", "CSRF_DIGEST", "EXPIRES_AT", "REVOKED_AT", "NODE_ID"}),
    "CX_ROLE_TEMPLATES": frozenset({"ROLE_CODE", "PERMISSIONS_JSON", "DATA_SCOPES_JSON", "MANAGED"}),
    "CX_USER_ROLES": frozenset({"USER_ROLE_ID", "PRINCIPAL_ID", "ROLE_CODE", "STATUS"}),
    "CX_USER_PERMISSION_OVERRIDES": frozenset({"OVERRIDE_ID", "PRINCIPAL_ID", "RESOURCE_ACTION", "EFFECT", "DATA_SCOPE", "REASON"}),
    "CX_ORGANIZATIONS": frozenset({"ORGANIZATION_ID", "PARENT_ID", "STATUS"}),
    "CX_ORGANIZATION_MEMBERS": frozenset({"MEMBERSHIP_ID", "ORGANIZATION_ID", "PRINCIPAL_ID", "MANAGER_PRINCIPAL_ID", "STATUS"}),
    "CX_RESPONSIBLE_GROUPS": frozenset({"GROUP_ID", "SECURITY_DOMAIN_ID", "PARENT_GROUP_ID", "STATUS"}),
    "CX_RESPONSIBLE_GROUP_MEMBERS": frozenset({"GROUP_ID", "PRINCIPAL_ID", "MEMBER_ROLE", "STATUS"}),
    "CX_SECURITY_DOMAINS": frozenset({"SECURITY_DOMAIN_ID", "DOMAIN_NAME", "CLASSIFICATION", "STATUS"}),
    "CX_DOMAIN_MEMBERS": frozenset({"MEMBERSHIP_ID", "SECURITY_DOMAIN_ID", "PRINCIPAL_ID", "MEMBERSHIP_TIER", "STATUS"}),
    "CX_ENROLLMENT_GRANTS": frozenset({"GRANT_ID", "SPONSOR_PRINCIPAL_ID", "OWNER_PRINCIPAL_ID", "RESPONSIBLE_GROUP_ID", "ENVIRONMENT", "RUNTIME", "POLICY_SNAPSHOT", "STATUS", "EXPIRES_AT", "MAX_USES", "USED_COUNT"}),
    "CX_ENROLLMENT_TOKENS": frozenset({"TOKEN_ID", "GRANT_ID", "TOKEN_DIGEST", "EXPIRES_AT", "CONSUMED_AT"}),
    "CX_AGENT_RELATIONSHIPS": frozenset({"RELATIONSHIP_ID", "AGENT_ID", "PRINCIPAL_ID", "RELATIONSHIP_ROLE", "RESPONSIBLE_GROUP_ID", "STATUS"}),
    "CX_AGENT_CREDENTIALS": frozenset({"CREDENTIAL_ID", "AGENT_ID", "CREDENTIAL_TYPE", "STATUS"}),
    "CX_AGENT_ACCESS_TOKENS": frozenset({"TOKEN_DIGEST", "AGENT_ID", "INSTANCE_ID", "FENCING_TOKEN", "EXPIRES_AT", "REVOKED_AT"}),
    "CX_CHANNELS": frozenset({"CHANNEL_ID", "CHANNEL_NAME", "SECURITY_DOMAIN_ID", "CLASSIFICATION", "CHANNEL_TYPE", "STATUS", "RETENTION_UNTIL", "LEGAL_HOLD"}),
    "CX_CHANNEL_MEMBERS": frozenset({"MEMBER_ID", "CHANNEL_ID", "PRINCIPAL_ID", "MEMBER_ROLE", "STATUS"}),
    "CX_CHANNEL_MESSAGES": frozenset({"MESSAGE_ID", "CHANNEL_ID", "PRINCIPAL_ID", "BODY_TEXT", "CREATED_AT"}),
    "CX_BARRIERS": frozenset({"BARRIER_ID", "NODE_KEY", "POLICY_JSON", "PARTICIPANT_SNAPSHOT", "STATUS", "CREATED_BY"}),
    "CX_BARRIER_ARRIVALS": frozenset({"ARRIVAL_ID", "BARRIER_ID", "PRINCIPAL_ID", "PARTICIPANT_ROLE", "REPORT_DIGEST", "REPORT_JSON", "IDEMPOTENCY_KEY"}),
    "CX_ACTION_CARDS": frozenset({"ACTION_ID", "CHANNEL_ID", "PROPOSED_BY", "ACTION_TYPE", "STATUS", "REASON", "IDEMPOTENCY_KEY"}),
    "CX_NOTIFICATIONS": frozenset({"NOTIFICATION_ID", "PRINCIPAL_ID", "NOTIFICATION_TYPE", "DEDUPE_KEY", "PAYLOAD_JSON"}),
    "CX_SECURITY_EVENTS": frozenset({"EVENT_ID", "PRINCIPAL_ID", "ACTION_NAME", "OUTCOME", "CREATED_AT"}),
    "CX_BRIDGES": frozenset({"BRIDGE_ID", "SOURCE_DOMAIN_ID", "TARGET_DOMAIN_ID", "TRANSFER_MODE", "PURPOSE", "CLASSIFICATION", "RECIPIENT_SNAPSHOT", "STATUS"}),
    "CX_AGENT_INSTANCES": frozenset({"INSTANCE_ID", "AGENT_ID", "CHANNEL_ID", "STATUS", "FENCING_TOKEN", "LAST_SEEN_AT", "LEASE_EXPIRES_AT"}),
    "CX_AGENT_DELIVERIES": frozenset({"DELIVERY_ID", "AGENT_ID", "INSTANCE_ID", "IDEMPOTENCY_KEY", "STATUS", "CLAIM_TOKEN_DIGEST", "CLAIMED_AT", "FENCING_TOKEN"}),
    "CX_CHANNEL_MEMORY_CANDIDATES": frozenset({"CANDIDATE_ID", "CHANNEL_ID", "SECURITY_DOMAIN_ID", "CONTENT_JSON", "CLASSIFICATION", "DESTINATION_SCOPE", "PROVENANCE_JSON", "STATUS"}),
    "CX_BRIDGE_TRANSFERS": frozenset({"TRANSFER_ID", "BRIDGE_ID", "SOURCE_OBJECT_TYPE", "SOURCE_OBJECT_ID", "STATUS", "CREATED_BY", "IDEMPOTENCY_KEY", "SOURCE_CLASSIFICATION"}),
}

V43_GOVERNANCE_REQUIRED_COLUMNS = {
    "CX_CHANNELS": frozenset({"LIFECYCLE_REASON", "DELETION_AFTER", "QUARANTINED_AT"}),
    "CX_BRIDGES": frozenset({"APPROVAL_REASON", "POLICY_VERSION"}),
    "CX_BRIDGE_TRANSFERS": frozenset({"IDEMPOTENCY_KEY", "SOURCE_CLASSIFICATION"}),
    "CX_NOTIFICATIONS": frozenset({"NOTIFICATION_LEVEL", "ACKNOWLEDGED_BY", "ESCALATED_AT"}),
    "CX_BARRIERS": frozenset({"RETRY_COUNT", "MAX_RETRIES", "LAST_RECOVERY_ACTION", "RECOVERY_REASON"}),
    "CX_CHANNEL_THREADS": frozenset({"THREAD_ID", "CHANNEL_ID", "THREAD_TYPE", "CLASSIFICATION", "STATUS", "POLICY_JSON", "CREATED_BY"}),
    "CX_CHANNEL_THREAD_MEMBERS": frozenset({"THREAD_MEMBER_ID", "THREAD_ID", "PRINCIPAL_ID", "MEMBER_ROLE", "STATUS", "VALID_UNTIL"}),
    "CX_RUNTIME_PROFILE_CHANGES": frozenset({"CHANGE_ID", "REQUESTED_BY", "CURRENT_PROFILE", "TARGET_PROFILE", "IMPACT_JSON", "STATUS", "REASON"}),
}

V43_SECURITY_REQUIRED_COLUMNS = {
    "CX_PRINCIPALS": frozenset({"MFA_REQUIRED"}),
    "CX_HUMAN_IDENTITIES": frozenset({"FAILED_LOGIN_COUNT", "LOCKED_UNTIL", "USER_ID"}),
    "CX_ENROLLMENT_GRANTS": frozenset({"AGENT_ID"}),
    "CX_MFA_FACTORS": frozenset({"FACTOR_ID", "PRINCIPAL_ID", "FACTOR_TYPE", "STATUS"}),
    "CX_MFA_RECOVERY_CODES": frozenset({"CODE_ID", "PRINCIPAL_ID", "CODE_DIGEST", "STATUS"}),
    "CX_PASSWORD_RESET_TOKENS": frozenset({"TOKEN_ID", "PRINCIPAL_ID", "TOKEN_DIGEST", "PURPOSE", "EXPIRES_AT", "CONSUMED_AT"}),
    "CX_IDENTITY_LINK_AUDIT": frozenset({"LINK_EVENT_ID", "PRINCIPAL_ID", "ACTOR_PRINCIPAL_ID", "PROVIDER", "SUBJECT_DIGEST", "REASON", "OUTCOME"}),
    "CX_DELEGATIONS": frozenset({"DELEGATION_ID", "GRANTOR_PRINCIPAL_ID", "GRANTEE_PRINCIPAL_ID", "PERMISSIONS_JSON", "DATA_SCOPE", "REASON", "STATUS"}),
    "CX_AGENT_QUOTAS": frozenset({"QUOTA_ID", "SCOPE_TYPE", "SCOPE_ID", "ENVIRONMENT", "MAX_AGENTS", "USED_AGENTS", "MAX_ACTIVE_INSTANCES", "USED_ACTIVE_INSTANCES", "STATUS"}),
    "CX_AGENT_OWNERSHIP_HISTORY": frozenset({"HISTORY_ID", "AGENT_ID", "ACTOR_PRINCIPAL_ID", "CREDENTIAL_ROTATED", "GRANTS_REEVALUATED", "REASON"}),
    "CX_AGENT_LEGACY_REVIEWS": frozenset({"REVIEW_ID", "AGENT_ID", "CLASSIFICATION", "EVIDENCE_JSON", "STATUS", "CLAIM_REASON"}),
    "CX_AGENT_DERIVED_OBJECTS": frozenset({"DERIVED_OBJECT_ID", "AGENT_ID", "INSTANCE_ID", "OBJECT_TYPE", "OBJECT_ID", "STATUS", "REVOKED_AT"}),
    "CX_CHANNEL_DELETION_EVIDENCE": frozenset({"EVIDENCE_ID", "CHANNEL_ID", "ACTOR_PRINCIPAL_ID", "FROM_STATUS", "TO_STATUS", "REFERENCE_COUNT", "REASON", "DETAIL_JSON"}),
    "CX_MEMORY_ARTIFACT_LINKS": frozenset({"LINK_ID", "CANDIDATE_ID", "ARTIFACT_ID", "DESTINATION_SCOPE", "STATUS"}),
    "CX_BRIDGE_CONNECTORS": frozenset({"CONNECTOR_ID", "BRIDGE_ID", "CONNECTOR_MODE", "ENDPOINT_REF", "METADATA_ONLY", "STATUS", "REASON"}),
}

V43_REQUIRED_COLUMNS = {
    table: frozenset(columns)
    for table, columns in {
        **V43_BASE_REQUIRED_COLUMNS,
        **V43_GOVERNANCE_REQUIRED_COLUMNS,
        **V43_SECURITY_REQUIRED_COLUMNS,
    }.items()
}

# These are the columns a short-lived early v4.3 draft could omit.  They may
# be replayed by the identity step, but an unrelated partial table is never
# silently adopted.
V43_EARLY_ADDITIVE_COLUMNS = {
    "CX_AGENT_INSTANCES": frozenset({"LEASE_EXPIRES_AT"}),
    "CX_AGENT_ACCESS_TOKENS": frozenset({"FENCING_TOKEN"}),
    "CX_BARRIERS": frozenset({"CREATED_BY"}),
    "CX_AGENT_DELIVERIES": frozenset({"CLAIM_TOKEN_DIGEST", "CLAIMED_AT", "FENCING_TOKEN"}),
}

V43_INDEX_CONTRACT = {
    "IDX_CX_PRINCIPAL_TYPE": ("CX_PRINCIPALS", False),
    "IDX_CX_IDENTITY_PRINCIPAL": ("CX_HUMAN_IDENTITIES", False),
    "IDX_CX_IDENTITY_USERNAME": ("CX_HUMAN_IDENTITIES", True),
    "IDX_CX_REGISTRATION_STATUS": ("CX_REGISTRATION_REQUESTS", False),
    "IDX_CX_SESSION_PRINCIPAL": ("CX_WEB_SESSIONS", False),
    "IDX_CX_USER_ROLES": ("CX_USER_ROLES", False),
    "IDX_CX_PERMISSION_OVERRIDE": ("CX_USER_PERMISSION_OVERRIDES", False),
    "IDX_CX_ENROLLMENT_TOKEN_ACTIVE": ("CX_ENROLLMENT_TOKENS", False),
    "IDX_CX_AGENT_PRIMARY_OWNER": ("CX_AGENT_RELATIONSHIPS", True),
    "IDX_CX_AGENT_ACCESS_TOKEN": ("CX_AGENT_ACCESS_TOKENS", False),
    "IDX_CX_CHANNEL_DOMAIN": ("CX_CHANNELS", False),
    "IDX_CX_CHANNEL_MESSAGE_CURSOR": ("CX_CHANNEL_MESSAGES", False),
    "IDX_CX_BARRIER_STATUS": ("CX_BARRIERS", False),
    "IDX_CX_BARRIER_ARRIVAL_IDEMP": ("CX_BARRIER_ARRIVALS", True),
    "IDX_CX_SECURITY_EVENT_TIME": ("CX_SECURITY_EVENTS", False),
    "IDX_CX_AGENT_INSTANCE_SCOPE": ("CX_AGENT_INSTANCES", False),
    "IDX_CX_DELIVERY_CLAIM": ("CX_AGENT_DELIVERIES", False),
    "IDX_CX_DELIVERY_CLAIM_TOKEN": ("CX_AGENT_DELIVERIES", False),
    "IDX_CX_BRIDGE_TRANSFER_IDEMP": ("CX_BRIDGE_TRANSFERS", True),
    "IDX_CX_CHANNEL_THREAD_PARENT": ("CX_CHANNEL_THREADS", False),
    "IDX_CX_CHANNEL_THREAD_MEMBER": ("CX_CHANNEL_THREAD_MEMBERS", False),
    "IDX_CX_MFA_PRINCIPAL": ("CX_MFA_FACTORS", False),
    "IDX_CX_RESET_ACTIVE": ("CX_PASSWORD_RESET_TOKENS", False),
    "IDX_CX_AGENT_REVIEW_STATUS": ("CX_AGENT_LEGACY_REVIEWS", False),
    "IDX_CX_DERIVED_AGENT": ("CX_AGENT_DERIVED_OBJECTS", False),
    "IDX_CX_ENROLLMENT_AGENT": ("CX_ENROLLMENT_GRANTS", False),
}

V43_BASE_INDEXES = frozenset(name for name, (table, unique) in V43_INDEX_CONTRACT.items() if table in V43_BASE_TABLES)
V43_GOVERNANCE_INDEXES = frozenset({"IDX_CX_BRIDGE_TRANSFER_IDEMP", "IDX_CX_CHANNEL_THREAD_PARENT", "IDX_CX_CHANNEL_THREAD_MEMBER"})
V43_SECURITY_INDEXES = frozenset({"IDX_CX_MFA_PRINCIPAL", "IDX_CX_RESET_ACTIVE", "IDX_CX_AGENT_REVIEW_STATUS", "IDX_CX_DERIVED_AGENT", "IDX_CX_ENROLLMENT_AGENT"})

V43_PG_RLS_TABLES = frozenset({
    "CX_PRINCIPALS", "CX_HUMAN_IDENTITIES", "CX_REGISTRATION_REQUESTS", "CX_WEB_SESSIONS",
    "CX_ROLE_TEMPLATES", "CX_USER_ROLES", "CX_USER_PERMISSION_OVERRIDES", "CX_ORGANIZATIONS",
    "CX_ORGANIZATION_MEMBERS", "CX_SECURITY_DOMAINS", "CX_DOMAIN_MEMBERS", "CX_ENROLLMENT_GRANTS",
    "CX_ENROLLMENT_TOKENS", "CX_AGENT_RELATIONSHIPS", "CX_AGENT_CREDENTIALS", "CX_AGENT_ACCESS_TOKENS",
    "CX_CHANNELS", "CX_CHANNEL_MEMBERS", "CX_CHANNEL_MESSAGES", "CX_BARRIERS", "CX_BARRIER_ARRIVALS",
    "CX_ACTION_CARDS", "CX_NOTIFICATIONS", "CX_SECURITY_EVENTS", "CX_BRIDGES",
    "CX_CHANNEL_MEMORY_CANDIDATES", "CX_BRIDGE_TRANSFERS", "CX_AGENT_INSTANCES", "CX_AGENT_DELIVERIES",
    "CX_CHANNEL_THREADS", "CX_CHANNEL_THREAD_MEMBERS", "CX_RUNTIME_PROFILE_CHANGES",
    "CX_MFA_FACTORS", "CX_MFA_RECOVERY_CODES", "CX_PASSWORD_RESET_TOKENS", "CX_DELEGATIONS",
    "CX_AGENT_LEGACY_REVIEWS", "CX_AGENT_DERIVED_OBJECTS",
})

V43_PG_RLS_POLICIES = frozenset({
    "CX_PRINCIPALS_AGENT_SELF", "CX_AGENT_RELATIONSHIPS_SELF", "CX_AGENT_CREDENTIALS_SELF",
    "CX_AGENT_ACCESS_TOKENS_SELF", "CX_AGENT_INSTANCES_SELF", "CX_AGENT_DELIVERIES_SELF",
    "CX_CHANNELS_MEMBER", "CX_CHANNEL_MEMBERS_MEMBER", "CX_CHANNEL_MESSAGES_MEMBER",
    "CX_CHANNEL_MESSAGES_AGENT_INSERT", "CX_BARRIERS_MEMBER", "CX_BARRIER_ARRIVALS_MEMBER",
    "CX_BARRIER_ARRIVALS_AGENT_INSERT", "CX_ACTION_CARDS_MEMBER", "CX_ACTION_CARDS_AGENT_INSERT",
    "CX_NOTIFICATIONS_SELF", "CX_SECURITY_EVENTS_SELF", "CX_SECURITY_EVENTS_AGENT_INSERT",
    "CX_CHANNEL_MEMORY_CANDIDATES_MEMBER", "CX_CHANNEL_MEMORY_CANDIDATES_AGENT_INSERT",
    "CX_CHANNEL_THREADS_MEMBER", "CX_CHANNEL_THREADS_AGENT_INSERT", "CX_CHANNEL_THREAD_MEMBERS_MEMBER",
    "CX_CHANNEL_THREAD_MEMBERS_AGENT_INSERT", "CX_MFA_FACTOR_OWNER", "CX_MFA_RECOVERY_OWNER",
    "CX_RESET_OWNER", "CX_DELEGATION_MEMBER", "CX_LEGACY_REVIEW_SCOPE", "CX_DERIVED_INSTANCE_SCOPE",
})

V43_PG_PERMISSION_MARKERS = (
    "GRANT USAGE ON SCHEMA PUBLIC TO AI_AGENT_RUNTIME",
    "REVOKE ALL ON FUNCTION PUBLIC.CX_AGENT_CHANNEL_MEMBER",
    "GRANT EXECUTE ON FUNCTION PUBLIC.CX_AGENT_CHANNEL_MEMBER",
    "REVOKE ALL ON TABLE PUBLIC.CX_CHANNEL_THREADS",
    "GRANT SELECT, INSERT ON TABLE PUBLIC.CX_CHANNEL_THREADS",
    "REVOKE UPDATE, DELETE ON TABLE PUBLIC.CX_CHANNEL_THREADS",
)

V43_NATIVE_PERMISSION_MARKERS = (
    "GRANT CREATE SESSION TO AGENT_API",
    "GRANT SELECT ON &&SCHEMA_OWNER..ENTITIES TO AGENT_API",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON",
    "DEEP_SEC_SESSION_ROLE",
    "CREATE TABLE",
    "DROP ANY TABLE",
)

V43_PG_RUNTIME_TABLES = frozenset({
    "CX_PRINCIPALS", "CX_HUMAN_IDENTITIES", "CX_AGENT_RELATIONSHIPS", "CX_AGENT_CREDENTIALS",
    "CX_AGENT_ACCESS_TOKENS", "CX_AGENT_INSTANCES", "CX_AGENT_DELIVERIES", "CX_CHANNELS",
    "CX_CHANNEL_MEMBERS", "CX_CHANNEL_MESSAGES", "CX_BARRIERS", "CX_BARRIER_ARRIVALS",
    "CX_ACTION_CARDS", "CX_NOTIFICATIONS", "CX_SECURITY_EVENTS", "CX_CHANNEL_MEMORY_CANDIDATES",
})
V43_PG_THREAD_RUNTIME_TABLES = frozenset({"CX_CHANNEL_THREADS", "CX_CHANNEL_THREAD_MEMBERS"})


def _strip_sql_comments(text: str) -> str:
    """Remove SQL comments before inspecting declarations, not SQL strings."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"--[^\r\n]*", " ", text)


def _balanced_sql_body(text: str, opening: int) -> tuple[str, int] | None:
    """Return text inside a parenthesized SQL expression.

    v4.3 Oracle/Yashan declarations are sometimes inside a quoted
    ``EXECUTE IMMEDIATE`` block.  This small scanner handles nested type
    parentheses and doubled single quotes without attempting to execute SQL.
    """
    if opening >= len(text) or text[opening] != "(":
        return None
    depth = 0
    quote: str | None = None
    index = opening
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char == "'" or char == '"':
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index], index
        index += 1
    return None


def _split_sql_top_level(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char == "'" or char == '"':
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return parts


def _declared_table_columns(text: str) -> dict[str, set[str]]:
    """Extract table columns from direct and quoted CREATE/ALTER TABLE SQL."""
    source = _strip_sql_comments(text)
    tables: dict[str, set[str]] = {}
    create_pattern = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:[A-Z0-9_]+\.)?([A-Z0-9_]+)\s*\(", re.IGNORECASE,
    )
    for match in create_pattern.finditer(source):
        body = _balanced_sql_body(source, match.end() - 1)
        if body is None:
            continue
        columns = tables.setdefault(match.group(1).upper(), set())
        for part in _split_sql_top_level(body[0]):
            token = re.match(r"\s*([A-Z][A-Z0-9_]*)\b", part, re.IGNORECASE)
            if not token:
                continue
            name = token.group(1).upper()
            if name not in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
                columns.add(name)

    alter_pattern = re.compile(
        r"\bALTER\s+TABLE\s+(?:[A-Z0-9_]+\.)?([A-Z0-9_]+)\s+"
        r"ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?",
        re.IGNORECASE,
    )
    for match in alter_pattern.finditer(source):
        table = match.group(1).upper()
        rest = source[match.end():].lstrip()
        if rest.startswith("("):
            body = _balanced_sql_body(source, match.end() + len(source[match.end():]) - len(rest))
            if body is None:
                continue
            columns = tables.setdefault(table, set())
            for part in _split_sql_top_level(body[0]):
                token = re.match(r"\s*([A-Z][A-Z0-9_]*)\b", part, re.IGNORECASE)
                if token:
                    columns.add(token.group(1).upper())
        else:
            token = re.match(r"([A-Z][A-Z0-9_]*)\b", rest, re.IGNORECASE)
            if token:
                tables.setdefault(table, set()).add(token.group(1).upper())
    for match in re.finditer(
        r"\bADD_COLUMN\s*\(\s*'([A-Z0-9_]+)'\s*,\s*'([A-Z0-9_]+)'",
        source,
        re.IGNORECASE,
    ):
        tables.setdefault(match.group(1).upper(), set()).add(match.group(2).upper())
    return tables


def _declared_indexes(text: str) -> dict[str, dict[str, Any]]:
    source = _strip_sql_comments(text)
    result: dict[str, dict[str, Any]] = {}
    pattern = re.compile(
        r"\bCREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:[A-Z0-9_]+\.)?([A-Z0-9_]+)\s+ON\s+"
        r"(?:[A-Z0-9_]+\.)?([A-Z0-9_]+)\s*\(", re.IGNORECASE,
    )
    for match in pattern.finditer(source):
        body = _balanced_sql_body(source, match.end() - 1)
        result[match.group(2).upper()] = {
            "table": match.group(3).upper(),
            "unique": bool(match.group(1)),
            "columns": body[0].strip().upper() if body else "",
        }
    return result


def _normalized_marker_text(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_sql_comments(text)).strip().upper()


def _v43_stage_requirements(stage: str) -> tuple[set[str], dict[str, frozenset[str]], set[str], set[str], set[str]]:
    if stage not in {"identity", "governance", "security"}:
        raise ValueError(f"unknown v4.3 stage: {stage}")
    tables = set(V43_BASE_TABLES)
    columns = dict(V43_BASE_REQUIRED_COLUMNS)
    indexes = set(V43_BASE_INDEXES)
    rls_tables = set(V43_PG_RLS_TABLES.intersection(tables))
    policies = {
        name for name in V43_PG_RLS_POLICIES
        if not name.startswith(("CX_CHANNEL_THREAD_", "CX_MFA_", "CX_RESET_", "CX_DELEGATION_", "CX_LEGACY_", "CX_DERIVED_"))
    }
    if stage in {"governance", "security"}:
        tables.update(V43_GOVERNANCE_TABLES)
        columns.update(V43_GOVERNANCE_REQUIRED_COLUMNS)
        indexes.update(V43_GOVERNANCE_INDEXES)
        rls_tables.update(V43_PG_RLS_TABLES.intersection(V43_GOVERNANCE_TABLES))
        policies.update({name for name in V43_PG_RLS_POLICIES if name.startswith("CX_CHANNEL_THREAD_")})
    if stage == "security":
        tables.update(V43_SECURITY_TABLES)
        columns = dict(V43_REQUIRED_COLUMNS)
        indexes.update(V43_SECURITY_INDEXES)
        rls_tables.update(V43_PG_RLS_TABLES.intersection(V43_SECURITY_TABLES))
        policies.update({
            name for name in V43_PG_RLS_POLICIES
            if name.startswith(("CX_MFA_", "CX_RESET_", "CX_DELEGATION_", "CX_LEGACY_", "CX_DERIVED_"))
        })
    return tables, columns, indexes, rls_tables, policies


def _snapshot_index_info(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexes = snapshot.get("indexes") or {}
    if isinstance(indexes, dict):
        return {str(name).upper(): dict(value or {}) for name, value in indexes.items()}
    return {str(name).upper(): {} for name in indexes}


def _catalog_index_is_unique(value: Any) -> bool:
    """Normalize unique-index flags returned by the supported catalogs."""
    return str(value or "").strip().upper() in {"UNIQUE", "Y", "YES", "TRUE"}


def validate_v43_catalog_snapshot(
    database: str,
    snapshot: dict[str, Any],
    *,
    require_runtime_permissions: bool = False,
) -> dict[str, Any]:
    """Validate a catalog snapshot without connecting to or changing a DB."""
    present_tables = {str(item).upper() for item in (snapshot.get("tables") or set())}
    columns = {
        str(table).upper(): {str(item).upper() for item in values}
        for table, values in (snapshot.get("columns") or {}).items()
    }
    index_info = _snapshot_index_info(snapshot)
    stage_reports: dict[str, dict[str, Any]] = {}
    for stage in ("identity", "governance", "security"):
        tables, required_columns, required_indexes, required_rls, required_policies = _v43_stage_requirements(stage)
        missing_tables = sorted(tables - present_tables)
        missing_columns = {
            table: sorted(set(required) - columns.get(table, set()))
            for table, required in required_columns.items()
            if set(required) - columns.get(table, set())
        }
        missing_indexes = sorted(
            name for name in required_indexes
            if name not in index_info
            or str(index_info[name].get("table") or "").upper() != V43_INDEX_CONTRACT[name][0]
            or (V43_INDEX_CONTRACT[name][1] and not _catalog_index_is_unique(index_info[name].get("unique")))
        )
        missing_rls = sorted(
            required_rls - {str(item).upper() for item in (snapshot.get("rls_tables") or set())}
        ) if database == "pg" else []
        missing_policies = sorted(
            required_policies - {str(item).upper() for item in (snapshot.get("policies") or set())}
        ) if database == "pg" else []
        stage_reports[stage] = {
            "tables_required": len(tables),
            "tables_present": len(tables - set(missing_tables)),
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "missing_indexes": missing_indexes,
            "missing_rls_tables": missing_rls,
            "missing_policies": missing_policies,
            "passed": not (missing_tables or missing_columns or missing_indexes or missing_rls or missing_policies),
        }

    permission_passed = bool(snapshot.get("permission_contract_passed", True))
    permission_missing = list(snapshot.get("missing_privileges") or [])
    if require_runtime_permissions and not permission_passed:
        permission_missing = permission_missing or ["runtime permission contract"]
    schema_passed = stage_reports["security"]["passed"]
    return {
        "database": database,
        "stages": stage_reports,
        "schema_passed": schema_passed,
        "permission_contract_passed": permission_passed,
        "missing_privileges": permission_missing,
        "passed": schema_passed and (permission_passed if require_runtime_permissions else True),
    }


def v43_partial_schema_incomplete(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only partial objects that cannot be safely adopted or retried."""
    present_tables = {str(item).upper() for item in (snapshot.get("tables") or set())}
    columns = {
        str(table).upper(): {str(item).upper() for item in values}
        for table, values in (snapshot.get("columns") or {}).items()
    }
    incomplete: list[dict[str, Any]] = []
    for table in sorted(present_tables.intersection(V43_REQUIRED_TABLES)):
        if table in V43_BASE_TABLES:
            required = set(V43_BASE_REQUIRED_COLUMNS.get(table, frozenset()))
            required -= set(V43_EARLY_ADDITIVE_COLUMNS.get(table, frozenset()))
        else:
            required = set(V43_REQUIRED_COLUMNS.get(table, frozenset()))
        missing = sorted(required - columns.get(table, set()))
        if missing:
            incomplete.append({"table": table, "missing_columns": missing})
    return incomplete


def v43_additive_columns_missing(snapshot: dict[str, Any]) -> bool:
    present_tables = {str(item).upper() for item in (snapshot.get("tables") or set())}
    columns = {
        str(table).upper(): {str(item).upper() for item in values}
        for table, values in (snapshot.get("columns") or {}).items()
    }
    return any(
        table in present_tables and set(required) - columns.get(table, set())
        for table, required in V43_EARLY_ADDITIVE_COLUMNS.items()
    )


def validate_v43_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate v4.3 SQL declarations using only local files."""
    selected = {path.name: path for path in scripts}
    missing_scripts = [name for name in V43_MIGRATION_SCRIPTS if name not in selected or not selected[name].is_file()]
    sql_parts = [path.read_text(encoding="utf-8") for path in scripts if path.is_file()]
    deploy_dir = next((path.parent for path in scripts if path.is_file()), None)
    if deploy_dir:
        grants = deploy_dir / "4_grants.sql"
        if grants.is_file():
            sql_parts.append(grants.read_text(encoding="utf-8"))
    source = "\n".join(sql_parts)
    declared_tables = _declared_table_columns(source)
    declared_indexes = _declared_indexes(source)
    missing_tables = sorted(set(V43_REQUIRED_TABLES) - set(declared_tables))
    missing_columns = {
        table: sorted(set(required) - declared_tables.get(table, set()))
        for table, required in V43_REQUIRED_COLUMNS.items()
        if set(required) - declared_tables.get(table, set())
    }
    missing_indexes = sorted(
        name for name, (table, unique) in V43_INDEX_CONTRACT.items()
        if name not in declared_indexes
        or declared_indexes[name]["table"] != table
        or (unique and not declared_indexes[name]["unique"])
    )
    marker_text = _normalized_marker_text(source)
    if database == "pg":
        missing_rls_tables = sorted(
            table for table in V43_PG_RLS_TABLES
            if not re.search(rf"\bALTER\s+TABLE\s+(?:PUBLIC\.)?{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY\b", marker_text)
        )
        declared_policies = {name.upper() for name in re.findall(r"\bCREATE\s+POLICY\s+([A-Z0-9_]+)", marker_text)}
        missing_policies = sorted(V43_PG_RLS_POLICIES - declared_policies)
        missing_permissions = [marker for marker in V43_PG_PERMISSION_MARKERS if marker not in marker_text]
    else:
        missing_rls_tables = []
        missing_policies = []
        missing_permissions = [marker for marker in V43_NATIVE_PERMISSION_MARKERS if marker not in marker_text]
    return {
        "database": database,
        "scripts_required": list(V43_MIGRATION_SCRIPTS),
        "scripts_missing": missing_scripts,
        "tables_missing": missing_tables,
        "columns_missing": missing_columns,
        "indexes_missing": missing_indexes,
        "rls_tables_missing": missing_rls_tables,
        "policies_missing": missing_policies,
        "permissions_missing": missing_permissions,
        "passed": not any((missing_scripts, missing_tables, missing_columns, missing_indexes, missing_rls_tables, missing_policies, missing_permissions)),
    }


def validate_v431_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.1 organization declarations locally."""
    base = validate_v43_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    missing_scripts = [
        name for name in V431_MIGRATION_SCRIPTS
        if name not in selected or not selected[name].is_file()
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in scripts if path.is_file()
    )
    declared_tables = _declared_table_columns(source)
    declared_indexes = _declared_indexes(source)
    missing_tables = sorted(set(V431_ORGANIZATION_TABLES) - set(declared_tables))
    missing_columns = {
        table: sorted(set(required) - declared_tables.get(table, set()))
        for table, required in V431_ORGANIZATION_REQUIRED_COLUMNS.items()
        if set(required) - declared_tables.get(table, set())
    }
    for table, required in V431_ENTRY_ACCESS_REQUIRED_COLUMNS.items():
        missing = set(required) - declared_tables.get(table, set())
        if missing:
            missing_columns.setdefault(table, []).extend(sorted(missing))
    missing_indexes = sorted(
        name for name, (table, unique) in V431_INDEX_CONTRACT.items()
        if name not in declared_indexes
        or declared_indexes[name]["table"] != table
        or (unique and not declared_indexes[name]["unique"])
    )
    organization = {
        "scripts_required": list(V431_MIGRATION_SCRIPTS),
        "scripts_missing": missing_scripts,
        "tables_missing": missing_tables,
        "columns_missing": missing_columns,
        "indexes_missing": missing_indexes,
    }
    organization["passed"] = not any(
        (missing_scripts, missing_tables, missing_columns, missing_indexes)
    )
    return {
        "database": database,
        "v43": base,
        "organization": organization,
        "passed": bool(base.get("passed")) and bool(organization["passed"]),
    }


def validate_v432_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.2 versioned-memory declarations locally."""
    base = validate_v431_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    migration = selected.get("23_v4_3_2_memory_lifecycle.sql")
    alignment = selected.get("24_v4_3_2_memory_digest_alignment.sql")
    scheduler_correction = selected.get("25_v4_3_2_disable_legacy_memory_fusion.sql")
    snapshot_fencing = selected.get("26_v4_3_2_snapshot_subject_fencing.sql")
    completion = selected.get("27_v4_3_2_memory_governance_completion.sql")
    source = migration.read_text(encoding="utf-8") if migration and migration.is_file() else ""
    alignment_source = alignment.read_text(encoding="utf-8") if alignment and alignment.is_file() else ""
    scheduler_source = scheduler_correction.read_text(encoding="utf-8") if scheduler_correction and scheduler_correction.is_file() else ""
    fencing_source = snapshot_fencing.read_text(encoding="utf-8") if snapshot_fencing and snapshot_fencing.is_file() else ""
    completion_source = completion.read_text(encoding="utf-8") if completion and completion.is_file() else ""
    normalized = _normalized_marker_text(source)
    all_memory_source = normalized + _normalized_marker_text(fencing_source) + _normalized_marker_text(completion_source)
    missing_tables = [name for name in V432_MEMORY_TABLES if name not in all_memory_source]
    missing_columns = {
        table: sorted(column for column in required if column not in all_memory_source)
        for table, required in V432_MEMORY_REQUIRED_COLUMNS.items()
        if any(column not in all_memory_source for column in required)
    }
    memory = {
        "scripts_required": list(V432_MIGRATION_SCRIPTS),
        "scripts_missing": [name for name in V432_MIGRATION_SCRIPTS if name not in selected or not selected[name].is_file()],
        "tables_missing": missing_tables,
        "columns_missing": missing_columns,
        "digest_alignment": bool(alignment_source) and (
            "SHA256(" in alignment_source.upper()
            if database == "pg" else "DBMS_CRYPTO.HASH" in alignment_source.upper()
        ),
        "legacy_fusion_disabled": "MEMORY_FUSION_JOB" in scheduler_source.upper() and (
            "CRON.UNSCHEDULE" in scheduler_source.upper()
            if database == "pg" else "DBMS_SCHEDULER.DROP_JOB" in scheduler_source.upper()
        ),
    }
    memory["passed"] = not any((memory["scripts_missing"], memory["tables_missing"], memory["columns_missing"])) and memory["digest_alignment"] and memory["legacy_fusion_disabled"]
    return {"database": database, "v431": base, "memory": memory,
            "passed": bool(base.get("passed")) and bool(memory["passed"])}


def validate_v433_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.3 runtime-assurance declarations."""
    base = validate_v432_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    migration = selected.get("28_v4_3_3_graph_assurance.sql")
    source = _normalized_marker_text(migration.read_text(encoding="utf-8")) if migration and migration.is_file() else ""
    assurance = {
        "scripts_required": list(V433_MIGRATION_SCRIPTS),
        "scripts_missing": [name for name in V433_MIGRATION_SCRIPTS if name not in selected or not selected[name].is_file()],
        "tables_missing": [name for name in V433_GRAPH_ASSURANCE_TABLES if name not in source],
        "no_private_key_storage": "PRIVATE_KEY" not in source,
    }
    assurance["passed"] = not any((assurance["scripts_missing"], assurance["tables_missing"])) and assurance["no_private_key_storage"]
    return {"database": database, "v432": base, "graph_assurance": assurance,
            "passed": bool(base.get("passed")) and bool(assurance["passed"])}


def validate_v434_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.4 compliance migration source."""
    base = validate_v433_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    migration = selected.get("29_v4_3_4_agent_compliance.sql")
    source = _normalized_marker_text(migration.read_text(encoding="utf-8")) if migration and migration.is_file() else ""
    compliance = {
        "scripts_required": list(V434_MIGRATION_SCRIPTS),
        "scripts_missing": [name for name in V434_MIGRATION_SCRIPTS if name not in selected or not selected[name].is_file()],
        "tables_missing": [name for name in V434_COMPLIANCE_TABLES if name not in source],
        "no_profile_secret_storage": not any(marker in source for marker in ("PRIVATE_KEY", "CLIENT_SECRET", "ACCESS_TOKEN")),
    }
    compliance["passed"] = not any((compliance["scripts_missing"], compliance["tables_missing"])) and compliance["no_profile_secret_storage"]
    return {"database": database, "v433": base, "compliance": compliance,
            "passed": bool(base.get("passed")) and bool(compliance["passed"])}


def validate_v435_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.5 platform capability declarations."""
    # Community packages intentionally omit the Enterprise compliance overlay.
    # Keep the common v4.3.3 chain mandatory, while validating 4.3.4 only when
    # its scripts are physically present in the package.
    base = validate_v433_static_contract(database, scripts)
    compliance_present = any(
        path.name == "29_v4_3_4_agent_compliance.sql" and path.is_file()
        for path in scripts
    )
    if compliance_present:
        base = validate_v434_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    migration = selected.get("31_v4_3_5_platform_capabilities.sql")
    source = _normalized_marker_text(migration.read_text(encoding="utf-8")) if migration and migration.is_file() else ""
    optional_overlay = {"29_v4_3_4_agent_compliance.sql", "30_v4_3_4_compliance_hardening.sql"}
    capability = {
        "scripts_required": list(V435_MIGRATION_SCRIPTS),
        "scripts_missing": [
            name for name in V435_MIGRATION_SCRIPTS
            if name not in optional_overlay and (name not in selected or not selected[name].is_file())
        ],
        "tables_missing": [name for name in V435_PLATFORM_TABLES if name not in source],
        "no_secret_storage": not any(marker in source for marker in ("PRIVATE_KEY", "CLIENT_SECRET", "ACCESS_TOKEN", "PASSWORD")),
    }
    capability["passed"] = not any((capability["scripts_missing"], capability["tables_missing"])) and capability["no_secret_storage"]
    return {"database": database, "v434": base, "platform_capabilities": capability,
            "passed": bool(base.get("passed")) and bool(capability["passed"])}


def validate_v436_static_contract(database: str, scripts: Sequence[Path]) -> dict[str, Any]:
    """Validate the additive v4.3.6 native Agent declarations."""
    base = validate_v435_static_contract(database, scripts)
    selected = {path.name: path for path in scripts}
    migration = selected.get("32_v4_3_6_native_agents.sql")
    source = _normalized_marker_text(migration.read_text(encoding="utf-8")) if migration and migration.is_file() else ""
    native = {
        "scripts_required": list(V436_MIGRATION_SCRIPTS),
        "scripts_missing": [name for name in V436_MIGRATION_SCRIPTS if name not in selected or not selected[name].is_file()],
        "tables_missing": [name for name in V436_NATIVE_AGENT_TABLES if name not in source],
        "encrypted_secret_column": "API_KEY_CIPHER" in source,
        "no_plaintext_secret_markers": not any(marker in source for marker in ("PRIVATE_KEY", "CLIENT_SECRET", "PASSWORD")),
    }
    native["passed"] = not any((native["scripts_missing"], native["tables_missing"])) and native["encrypted_secret_column"] and native["no_plaintext_secret_markers"]
    return {"database": database, "v435": base, "native_agents": native,
            "passed": bool(base.get("passed")) and bool(native["passed"])}


def _pg_runtime_permission_contract(cursor: Any) -> dict[str, Any]:
    """Read actual PostgreSQL grants; absence of the runtime role is a failure."""
    cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_agent_runtime')")
    role_present = bool(_scalar(cursor.fetchone()))
    if not role_present:
        return {"role_present": False, "passed": False, "missing": ["role:ai_agent_runtime"]}
    missing: list[str] = []
    cursor.execute("SELECT has_schema_privilege('ai_agent_runtime', current_schema(), 'USAGE')")
    if not bool(_scalar(cursor.fetchone())):
        missing.append("schema:USAGE")
    for table in sorted(V43_PG_RUNTIME_TABLES):
        cursor.execute(
            "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, 'SELECT,INSERT,UPDATE,DELETE')",
            (table.lower(),),
        )
        if not bool(_scalar(cursor.fetchone())):
            missing.append(f"table:{table}:SELECT,INSERT,UPDATE,DELETE")
    for table in sorted(V43_PG_THREAD_RUNTIME_TABLES):
        cursor.execute(
            "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, 'SELECT,INSERT')",
            (table.lower(),),
        )
        if not bool(_scalar(cursor.fetchone())):
            missing.append(f"table:{table}:SELECT,INSERT")
        cursor.execute(
            "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, 'UPDATE')",
            (table.lower(),),
        )
        if bool(_scalar(cursor.fetchone())):
            missing.append(f"table:{table}:UPDATE_REVOKED")
        cursor.execute(
            "SELECT has_table_privilege('ai_agent_runtime', current_schema() || '.' || %s, 'DELETE')",
            (table.lower(),),
        )
        if bool(_scalar(cursor.fetchone())):
            missing.append(f"table:{table}:DELETE_REVOKED")
    return {"role_present": True, "passed": not missing, "missing": missing}


def v43_catalog_snapshot(cursor: Any, database: str, *, include_permissions: bool = False) -> dict[str, Any]:
    """Read v4.3 catalog facts without writing or changing session state."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    tables = {str(row[0]).upper() for row in cursor.fetchall()}
    columns: dict[str, set[str]] = {}
    for table in tuple(dict.fromkeys(
        V43_REQUIRED_TABLES + V434_COMPLIANCE_TABLES + V435_PLATFORM_TABLES
    )):
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
        columns[table] = {str(row[0]).upper() for row in cursor.fetchall()}

    indexes: dict[str, dict[str, Any]] = {}
    if database == "pg":
        cursor.execute(
            "SELECT upper(indexname), upper(tablename), indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema()"
        )
        for row in cursor.fetchall():
            indexes[str(row[0]).upper()] = {
                "table": str(row[1]).upper(),
                "unique": str(row[2] or "").upper().startswith("CREATE UNIQUE INDEX"),
            }
    else:
        cursor.execute("SELECT INDEX_NAME, TABLE_NAME, UNIQUENESS FROM USER_INDEXES")
        for row in cursor.fetchall():
            indexes[str(row[0]).upper()] = {
                "table": str(row[1]).upper(),
                "unique": _catalog_index_is_unique(row[2]),
            }

    snapshot: dict[str, Any] = {"tables": tables, "columns": columns, "indexes": indexes}
    if database == "pg":
        cursor.execute(
            "SELECT upper(c.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' AND c.relrowsecurity"
        )
        snapshot["rls_tables"] = {str(row[0]).upper() for row in cursor.fetchall()}
        cursor.execute("SELECT upper(policyname) FROM pg_policies WHERE schemaname = current_schema()")
        snapshot["policies"] = {str(row[0]).upper() for row in cursor.fetchall()}
        if include_permissions:
            permissions = _pg_runtime_permission_contract(cursor)
            snapshot["permission_contract_passed"] = permissions["passed"]
            snapshot["missing_privileges"] = permissions["missing"]
            snapshot["runtime_role_present"] = permissions["role_present"]
    else:
        snapshot["permission_contract_passed"] = True
    return snapshot


@dataclass
class ProbeResult:
    database: str
    connected: bool
    product: str = ""
    version: str = ""
    core_tables_present: int = 0
    core_tables_required: int = len(CORE_TABLES)
    v401_tables_present: int = 0
    v401_tables_required: int = len(V401_TABLES)
    v401_tables_missing: list[str] = field(default_factory=list)
    registration_tables_present: int = 0
    registration_tables_required: int = len(REGISTRATION_TABLES)
    registration_tables_missing: list[str] = field(default_factory=list)
    governance_tables_present: int = 0
    governance_tables_required: int = len(GOVERNANCE_TABLES)
    governance_tables_missing: list[str] = field(default_factory=list)
    graph_tables_present: int = 0
    graph_tables_required: int = len(GRAPH_TABLES)
    graph_tables_missing: list[str] = field(default_factory=list)
    skill_entity_contract: bool = False
    oracle_text_contract: dict[str, Any] = field(default_factory=dict)
    v43_schema_contract: dict[str, Any] = field(default_factory=dict)
    v43_partial_schema: list[dict[str, Any]] = field(default_factory=list)
    v431_organization_contract: dict[str, Any] = field(default_factory=dict)
    v434_compliance_contract: dict[str, Any] = field(default_factory=dict)
    v435_platform_contract: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""


def _capture_v43_catalog(cursor: Any, database: str, result: ProbeResult) -> None:
    """Attach the read-only v4.3 catalog contract to a live probe result."""
    snapshot = v43_catalog_snapshot(cursor, database, include_permissions=database == "pg")
    result.v43_schema_contract = validate_v43_catalog_snapshot(
        database, snapshot, require_runtime_permissions=database == "pg",
    )
    result.v43_partial_schema = v43_partial_schema_incomplete(snapshot)
    result.v431_organization_contract = _capture_v431_organization(cursor, database)
    result.v434_compliance_contract = {
        "tables_missing": sorted(set(V434_COMPLIANCE_TABLES) - set(snapshot["tables"])),
        "columns_missing": {
            table: sorted(set(required) - set(snapshot["columns"].get(table, set())))
            for table, required in V434_COMPLIANCE_REQUIRED_COLUMNS.items()
            if set(required) - set(snapshot["columns"].get(table, set()))
        },
    }
    result.v434_compliance_contract["passed"] = not any((
        result.v434_compliance_contract["tables_missing"], result.v434_compliance_contract["columns_missing"],
    ))
    result.v435_platform_contract = {
        "tables_missing": sorted(set(V435_PLATFORM_TABLES) - set(snapshot["tables"])),
        "columns_missing": {
            table: sorted(set(required) - set(snapshot["columns"].get(table, set())))
            for table, required in V435_PLATFORM_REQUIRED_COLUMNS.items()
            if set(required) - set(snapshot["columns"].get(table, set()))
        },
    }
    result.v435_platform_contract["passed"] = not any((
        result.v435_platform_contract["tables_missing"], result.v435_platform_contract["columns_missing"],
    ))


def _capture_v431_organization(cursor: Any, database: str) -> dict[str, Any]:
    """Read and validate the additive organization catalog without mutation."""
    if database == "pg":
        cursor.execute(
            "SELECT upper(table_name) FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
    else:
        cursor.execute("SELECT TABLE_NAME FROM USER_TABLES")
    tables = {str(row[0]).upper() for row in cursor.fetchall()}
    columns: dict[str, set[str]] = {}
    for table in V431_ORGANIZATION_REQUIRED_COLUMNS:
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
        columns[table] = {str(row[0]).upper() for row in cursor.fetchall()}
    if database == "pg":
        cursor.execute(
            "SELECT upper(indexname), upper(tablename), indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema()"
        )
        indexes = {
            str(row[0]).upper(): {
                "table": str(row[1]).upper(),
                "unique": str(row[2] or "").upper().startswith("CREATE UNIQUE INDEX"),
            }
            for row in cursor.fetchall()
        }
    else:
        cursor.execute("SELECT INDEX_NAME, TABLE_NAME, UNIQUENESS FROM USER_INDEXES")
        indexes = {
            str(row[0]).upper(): {
                "table": str(row[1]).upper(),
                "unique": _catalog_index_is_unique(row[2]),
            }
            for row in cursor.fetchall()
        }
    missing_tables = sorted(set(V431_ORGANIZATION_TABLES) - tables)
    missing_columns = {
        table: sorted(set(required) - columns.get(table, set()))
        for table, required in V431_ORGANIZATION_REQUIRED_COLUMNS.items()
        if set(required) - columns.get(table, set())
    }
    missing_indexes = sorted(
        name for name, (table, unique) in V431_INDEX_CONTRACT.items()
        if name not in indexes
        or indexes[name]["table"] != table
        or (unique and not indexes[name]["unique"])
    )
    return {
        "tables_missing": missing_tables,
        "columns_missing": missing_columns,
        "indexes_missing": missing_indexes,
        "passed": not any((missing_tables, missing_columns, missing_indexes)),
    }


def _load_database_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    section = dict(raw.get("database") or {})
    encrypted = section.pop("_encrypted", None)
    section.pop("_key_source", None)
    if encrypted:
        try:
            from shared.lib.connection_crypto import decrypt_section
        except ImportError:  # Generated packages place the shared library under scripts/.
            from lib.connection_crypto import decrypt_section
        key = base64.b64decode(LEGACY_KEY_PATH.read_text(encoding="ascii").strip())
        section.update(decrypt_section(encrypted, key))
    return section


def _scalar(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def _probe_oracle(config: dict[str, Any], *, enterprise: bool = True) -> ProbeResult:
    import oracledb

    result = ProbeResult(database="oracle", connected=False, product="Oracle AI Database")
    conn = oracledb.connect(
        user=config["user"], password=config["password"], dsn=config["dsn"],
        tcp_connect_timeout=8,
    )
    try:
        result.connected = True
        with conn.cursor() as cursor:
            try:
                cursor.execute("SELECT banner FROM v$version FETCH FIRST 1 ROW ONLY")
                banner = str(_scalar(cursor.fetchone()) or "")
                result.version = banner[:32]
            except Exception:
                result.version = "unavailable"
            names = CORE_TABLES + V401_TABLES + REGISTRATION_TABLES + GOVERNANCE_TABLES + GRAPH_TABLES
            binds = ",".join(f":n{i}" for i in range(len(names)))
            cursor.execute(
                f"SELECT table_name FROM user_tables WHERE table_name IN ({binds})",
                {f"n{i}": name for i, name in enumerate(names)},
            )
            present = {str(row[0]).upper() for row in cursor.fetchall()}
            cursor.execute(
                "SELECT column_name FROM user_tab_columns WHERE table_name = 'SKILL_META'"
            )
            skill_columns = {str(row[0]).upper() for row in cursor.fetchall()}
            cursor.execute(
                "SELECT COUNT(*) FROM CTXSYS.CTX_PREFERENCES "
                "WHERE PRE_OWNER = USER AND PRE_NAME = 'ENTITIES_MCD'"
            )
            preference_present = int(_scalar(cursor.fetchone()) or 0) == 1
            cursor.execute(
                "SELECT DOMIDX_STATUS, DOMIDX_OPSTATUS FROM USER_INDEXES "
                "WHERE INDEX_NAME = 'ENTITIES_SEARCH_CTX'"
            )
            index_row = cursor.fetchone()
            index_status = tuple(str(value or "").upper() for value in index_row) if index_row else ()
            result.oracle_text_contract = {
                "preference_present": preference_present,
                "index_present": bool(index_row),
                "domidx_status": index_status[0] if len(index_status) > 0 else "",
                "domidx_opstatus": index_status[1] if len(index_status) > 1 else "",
                "passed": preference_present and index_status == ("VALID", "VALID"),
            }
            _capture_v43_catalog(cursor, "oracle", result)
        result.core_tables_present = len(present.intersection(CORE_TABLES))
        result.v401_tables_present = len(present.intersection(V401_TABLES))
        result.v401_tables_missing = sorted(set(V401_TABLES) - present)
        result.registration_tables_present = len(present.intersection(REGISTRATION_TABLES))
        result.registration_tables_missing = sorted(set(REGISTRATION_TABLES) - present)
        result.governance_tables_required = len(GOVERNANCE_TABLES) if enterprise else 0
        result.governance_tables_present = len(present.intersection(GOVERNANCE_TABLES))
        result.governance_tables_missing = sorted(set(GOVERNANCE_TABLES) - present) if enterprise else []
        result.graph_tables_present = len(present.intersection(GRAPH_TABLES))
        result.graph_tables_missing = sorted(set(GRAPH_TABLES) - present)
        result.skill_entity_contract = {"ENTITY_ID", "ENTITY_TYPE", "SKILL_NAME"} <= skill_columns
        if not result.oracle_text_contract:
            result.oracle_text_contract = {"passed": False, "error": "not-probed"}
        return result
    finally:
        conn.close()


def _probe_pg(config: dict[str, Any], *, enterprise: bool = True) -> ProbeResult:
    import psycopg2

    result = ProbeResult(database="pg", connected=False, product="PostgreSQL")
    conn = psycopg2.connect(
        user=config["user"], password=config.get("password"), host=config["host"],
        port=int(config.get("port", 5432)), dbname=config["dbname"],
        connect_timeout=8,
    )
    try:
        conn.set_session(readonly=True, autocommit=False)
        result.connected = True
        with conn.cursor() as cursor:
            cursor.execute("SHOW server_version")
            result.version = str(_scalar(cursor.fetchone()) or "")[:32]
            cursor.execute(
                "SELECT upper(table_name) FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            )
            present = {str(row[0]).upper() for row in cursor.fetchall()}
            cursor.execute(
                "SELECT upper(column_name) FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'skill_meta'"
            )
            skill_columns = {str(row[0]).upper() for row in cursor.fetchall()}
            _capture_v43_catalog(cursor, "pg", result)
        conn.rollback()
        result.core_tables_present = len(present.intersection(CORE_TABLES))
        result.v401_tables_present = len(present.intersection(V401_TABLES))
        result.v401_tables_missing = sorted(set(V401_TABLES) - present)
        result.registration_tables_present = len(present.intersection(REGISTRATION_TABLES))
        result.registration_tables_missing = sorted(set(REGISTRATION_TABLES) - present)
        result.governance_tables_required = len(GOVERNANCE_TABLES) if enterprise else 0
        result.governance_tables_present = len(present.intersection(GOVERNANCE_TABLES))
        result.governance_tables_missing = sorted(set(GOVERNANCE_TABLES) - present) if enterprise else []
        result.graph_tables_present = len(present.intersection(GRAPH_TABLES))
        result.graph_tables_missing = sorted(set(GRAPH_TABLES) - present)
        result.skill_entity_contract = {"ENTITY_ID", "ENTITY_TYPE", "SKILL_NAME"} <= skill_columns
        return result
    finally:
        conn.close()


def _probe_yashandb(config: dict[str, Any], *, enterprise: bool = True) -> ProbeResult:
    import yaspy

    result = ProbeResult(database="yashandb", connected=False, product="YashanDB")
    conn = yaspy.Connection(
        user=config["user"], password=config["password"], dsn=config["dsn"]
    )
    try:
        result.connected = True
        with conn.cursor() as cursor:
            cursor.execute("SELECT VERSION FROM V$INSTANCE")
            result.version = str(_scalar(cursor.fetchone()) or "")[:32]
            names = CORE_TABLES + V401_TABLES + REGISTRATION_TABLES + GOVERNANCE_TABLES + GRAPH_TABLES
            binds = ",".join(f":n{i}" for i in range(len(names)))
            cursor.execute(
                f"SELECT TABLE_NAME FROM USER_TABLES WHERE TABLE_NAME IN ({binds})",
                {f"n{i}": name for i, name in enumerate(names)},
            )
            present = {str(row[0]).upper() for row in cursor.fetchall()}
            cursor.execute(
                "SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME = 'SKILL_META'"
            )
            skill_columns = {str(row[0]).upper() for row in cursor.fetchall()}
            _capture_v43_catalog(cursor, "yashandb", result)
        result.core_tables_present = len(present.intersection(CORE_TABLES))
        result.v401_tables_present = len(present.intersection(V401_TABLES))
        result.v401_tables_missing = sorted(set(V401_TABLES) - present)
        result.registration_tables_present = len(present.intersection(REGISTRATION_TABLES))
        result.registration_tables_missing = sorted(set(REGISTRATION_TABLES) - present)
        result.governance_tables_required = len(GOVERNANCE_TABLES) if enterprise else 0
        result.governance_tables_present = len(present.intersection(GOVERNANCE_TABLES))
        result.governance_tables_missing = sorted(set(GOVERNANCE_TABLES) - present) if enterprise else []
        result.graph_tables_present = len(present.intersection(GRAPH_TABLES))
        result.graph_tables_missing = sorted(set(GRAPH_TABLES) - present)
        result.skill_entity_contract = {"ENTITY_ID", "ENTITY_TYPE", "SKILL_NAME"} <= skill_columns
        return result
    finally:
        conn.close()


PROBES = {"oracle": _probe_oracle, "pg": _probe_pg, "yashandb": _probe_yashandb}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle-config", type=Path)
    parser.add_argument("--pg-config", type=Path)
    parser.add_argument("--yashandb-config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", default="", help="release version represented by this evidence")
    parser.add_argument("--edition", choices=("community", "enterprise"),
                        help="edition contract; defaults to the package manifest or enterprise")
    args = parser.parse_args()

    paths = {
        "oracle": args.oracle_config,
        "pg": args.pg_config,
        "yashandb": args.yashandb_config,
    }
    available_databases = _available_databases()
    manifest_path = REPO_ROOT / "build-manifest.json"
    manifest_edition = ""
    if manifest_path.is_file():
        try:
            manifest_edition = str(json.loads(manifest_path.read_text(encoding="ascii")).get("edition") or "").lower()
        except (OSError, ValueError):
            manifest_edition = ""
    edition = args.edition or manifest_edition or "enterprise"
    enterprise = edition == "enterprise"
    results: list[ProbeResult] = []
    if args.version:
        target_version = args.version
    else:
        manifest_path = REPO_ROOT / "build-manifest.json"
        version_path = REPO_ROOT / "VERSION"
        if manifest_path.is_file():
            target_version = str(json.loads(manifest_path.read_text(encoding="ascii")).get("version") or "unknown")
        elif version_path.is_file():
            target_version = version_path.read_text(encoding="ascii").strip()
        else:
            target_version = "unknown"
    # v4.3.0 integrates the internal v4.2.1 Graph closure.  Its live schema
    # gate therefore has the same mandatory Graph object contract as the
    # v4.2.x experimental line; otherwise an incomplete v4.3.0 deployment
    # could be reported as ready.
    requires_graph = target_version.startswith(("4.2.", "4.3."))
    requires_v43 = target_version.startswith("4.3.")
    requires_v431 = target_version.startswith(("4.3.1", "4.3.2", "4.3.3", "4.3.4", "4.3.5"))
    requires_v432 = target_version.startswith(("4.3.2", "4.3.3", "4.3.4", "4.3.5"))
    requires_v433 = target_version.startswith(("4.3.3", "4.3.4", "4.3.5"))
    requires_v434 = target_version.startswith(("4.3.4", "4.3.5"))
    requires_v435 = target_version.startswith("4.3.5")
    static_contracts: dict[str, dict[str, Any]] = {}
    if requires_v43:
        for database in available_databases:
            migration_scripts = V435_MIGRATION_SCRIPTS if requires_v435 else (V434_MIGRATION_SCRIPTS if requires_v434 else (V433_MIGRATION_SCRIPTS if requires_v433 else (V432_MIGRATION_SCRIPTS if requires_v432 else (V431_MIGRATION_SCRIPTS if requires_v431 else V43_MIGRATION_SCRIPTS))))
            scripts = [
                (REPO_ROOT / "scripts" / "deploy" / name)
                if (REPO_ROOT / "scripts" / "deploy" / name).is_file()
                else (REPO_ROOT / "adapters" / database / "deploy" / name)
                for name in migration_scripts
            ]
            static_contracts[database] = (
                validate_v435_static_contract(database, scripts) if requires_v435 else (validate_v434_static_contract(database, scripts) if requires_v434 else (validate_v433_static_contract(database, scripts) if requires_v433 else (
                    validate_v432_static_contract(database, scripts) if requires_v432 else (
                        validate_v431_static_contract(database, scripts) if requires_v431 else validate_v43_static_contract(database, scripts)
                    ))
                ))
            )
    for database in available_databases:
        path = paths[database]
        if path is None:
            parser.error(f"--{database}-config is required for {database}")
        try:
            results.append(PROBES[database](_load_database_config(path), enterprise=enterprise))
        except Exception as exc:
            results.append(ProbeResult(
                database=database, connected=False, product=database,
                governance_tables_required=len(GOVERNANCE_TABLES) if enterprise else 0,
                error_type=type(exc).__name__,
            ))

    payload = {
        "schema": "ai-agent-infra-live-probe/v1",
        "version": target_version,
        "edition": edition.title(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_fingerprints": {
            database: hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
            for database, path in paths.items()
            if database in available_databases and path is not None
        },
        "results": [asdict(result) for result in results],
        "passed": all(
            result.connected
            and result.core_tables_present == result.core_tables_required
            and result.v401_tables_present == result.v401_tables_required
            and result.registration_tables_present == result.registration_tables_required
            and result.governance_tables_present >= result.governance_tables_required
            and (not requires_graph or (
                result.graph_tables_present == result.graph_tables_required
                and not result.graph_tables_missing
            ))
            and (not requires_v43 or (
                result.v43_schema_contract.get("passed") is True
                and (not requires_v434 or not enterprise or result.v434_compliance_contract.get("passed") is True)
                and (not requires_v435 or result.v435_platform_contract.get("passed") is True)
                and not result.v43_partial_schema
            ))
            and (not requires_v431 or result.v431_organization_contract.get("passed") is True)
            and result.skill_entity_contract
            and (result.database != "oracle" or result.oracle_text_contract.get("passed") is True)
            and (not requires_v43 or static_contracts.get(result.database, {}).get("passed") is True)
            for result in results
        ),
        "v43_static_contracts": static_contracts,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
