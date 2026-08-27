"""Database-authoritative isolation inventory for v4.4.8."""

from __future__ import annotations

import json
from typing import Any, Dict

from . import connection, identity_api


INVENTORY = (
    ("identity", "CX_PRINCIPALS", ["PRINCIPAL_ID"], "Human UI; Agent gateway", "Self only", "NONE", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("identity", "CX_HUMAN_IDENTITIES", ["PRINCIPAL_ID"], "User management", "None", "NONE", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("identity", "CX_WEB_SESSIONS", ["PRINCIPAL_ID"], "Session policy", "None", "NONE", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("domain", "CX_SECURITY_DOMAINS", ["SECURITY_DOMAIN_ID"], "Security Domain UI", "Control plane only", "EXPLICIT", "SOURCE", "GOVERNED_TRANSITION", "NONE"),
    ("domain", "CX_DOMAIN_MEMBERS", ["SECURITY_DOMAIN_ID", "PRINCIPAL_ID"], "Domain members", "Control plane only", "EXPLICIT", "SOURCE", "GOVERNED_TRANSITION", "NONE"),
    ("channel", "CX_CHANNELS", ["SECURITY_DOMAIN_ID"], "Channel UI", "Channel+Domain member", "CHANNEL_MEMBERS", "SOURCE", "GOVERNED_TRANSITION", "NONE"),
    ("channel", "CX_CHANNEL_MESSAGES", ["SECURITY_DOMAIN_ID"], "Channel UI", "Channel+Domain member", "CHANNEL_MEMBERS", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("channel", "CX_CHANNEL_THREADS", ["SECURITY_DOMAIN_ID"], "Channel UI", "Thread+Channel+Domain", "PARTICIPANTS", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("governance", "CX_ACTION_CARDS", ["SECURITY_DOMAIN_ID"], "Approval UI", "Channel+Domain approver", "APPROVAL_POLICY", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("knowledge", "ENTITIES", ["OWNED_BY_AGENT", "WORKSPACE_ID"], "Knowledge UI", "Owner/scoped Agent", "VISIBILITY", "FTS_VECTOR_GRAPH", "GOVERNED_TRANSITION", "WORKSPACE_TO_ENTITY"),
    ("knowledge", "ENTITY_EDGES", ["SOURCE_ID", "TARGET_ID"], "Graph UI", "Both visible endpoints", "ENDPOINT_VISIBILITY", "GRAPH", "GOVERNED_TRANSITION", "ENDPOINT_CLASSIFICATION"),
    ("memory", "CX_MEMORY_FAMILIES", ["SECURITY_DOMAIN_ID", "OWNER_PRINCIPAL_ID"], "Memory UI", "Owner/scoped Agent", "DOMAIN_AND_OWNER", "VERSION_GRAPH", "GOVERNED_TRANSITION", "FAMILY_TO_VERSION"),
    ("memory", "CX_MEMORY_VERSIONS", ["SECURITY_DOMAIN_ID", "OWNER_PRINCIPAL_ID"], "Memory UI", "Owner/scoped Agent", "DOMAIN_AND_OWNER", "VERSION_GRAPH", "IMMUTABLE_SCOPE", "FAMILY_TO_VERSION"),
    ("graph", "GRAPH_RUNS", ["ACTOR_ID"], "Graph Run UI", "Actor/scope", "ACTOR_SCOPE", "RUN_EVENTS", "IMMUTABLE_SCOPE", "RUN_TO_NODE_ATTEMPT"),
    ("graph", "GRAPH_ARTIFACTS", ["OWNER_REF", "CLASSIFICATION"], "Artifact UI", "Owner/classified scope", "CLASSIFICATION", "CONTENT_ADDRESSABLE", "RETENTION_POLICY", "CLASSIFICATION_CEILING"),
    ("platform", "CX_PLATFORM_KNOWLEDGE", ["AUDIENCE", "SCOPE_TYPE", "SECURITY_DOMAIN_ID", "OWNER_PRINCIPAL_ID"], "Management context", "Built-in management Agent only", "EXPLICIT_SCOPE", "FTS_VECTOR_GRAPH", "IMMUTABLE_SCOPE", "SOURCE_SIGNATURE"),
    ("platform", "CX_PLATFORM_COMMANDS", ["COMMAND_KEY"], "Command registry", "Management context only", "NONE", "SOURCE", "IMMUTABLE_SCOPE", "NONE"),
    ("compliance", "CX_AGENT_POSTURES", ["AGENT_ID"], "Compliance UI", "Scoped operator", "SCOPE", "SOURCE", "GOVERNED_TRANSITION", "AGENT_TO_POSTURE"),
    ("compliance", "CX_COMPLIANCE_FINDINGS", ["AGENT_ID"], "Compliance UI", "Scoped operator", "SCOPE", "EVIDENCE", "GOVERNED_TRANSITION", "AGENT_TO_FINDING"),
    ("model", "CX_LLM_PROVIDER_PROFILES", ["PROFILE_ID"], "Deployment UI", "Control plane only", "NONE", "SOURCE", "LOGICAL_RETIREMENT", "SHARED_CONTROL_PLANE"),
)


def _row(row: Any) -> Dict[str, Any]:
    return {str(key).lower(): value for key, value in dict(row or {}).items()}


def ensure_isolation_inventory() -> Dict[str, Any]:
    """Idempotently seed the release-owned inventory without overwrites."""
    inserted = 0
    def work(tx: Any) -> Dict[str, Any]:
        nonlocal inserted
        for object_type, object_name, keys, human_path, agent_path, sharing, derived, move_policy, inheritance in INVENTORY:
            existing = _row(tx.query_one(
                "SELECT INVENTORY_ID FROM CX_DATABASE_ISOLATION_INVENTORY "
                "WHERE OBJECT_TYPE=:object_type AND OBJECT_NAME=:object_name",
                {"object_type": object_type, "object_name": object_name},
            ))
            if existing:
                continue
            inventory_id = "DII_" + object_type.upper() + "_" + object_name.upper()
            derived_inheritance = f"{derived}:{inheritance}"
            tx.execute(
                "INSERT INTO CX_DATABASE_ISOLATION_INVENTORY(INVENTORY_ID,OBJECT_TYPE,OBJECT_NAME,SCOPE_KEYS_JSON,"
                "HUMAN_PATH,AGENT_PATH,SHARING_MODEL,DERIVED_INHERITANCE,MOVE_POLICY,ORACLE_ENFORCEMENT,"
                "PG_ENFORCEMENT,YASHAN_ENFORCEMENT,STATUS,REASON,UPDATED_BY) VALUES "
                "(:id,:object_type,:object_name,:keys,:human,:agent,:sharing,:inheritance,:move,"
                "'END_USER_DATA_GRANT','ROLE_RLS','INDEPENDENT_USER_LEAST_PRIVILEGE','IMPLEMENTED',:reason,'SYSTEM_BOOTSTRAP')",
                {"id": inventory_id[:128], "object_type": object_type[:128], "object_name": object_name[:128],
                 "keys": json.dumps(keys, sort_keys=True, separators=(",", ":")),
                 "human": human_path[:512], "agent": agent_path[:512], "sharing": sharing[:64],
                 "move": move_policy[:64], "inheritance": derived_inheritance[:256],
                 "reason": "v4.4.10 database-authoritative isolation baseline"},
            )
            inserted += 1
        return {"status": "COMPLETED", "inserted": inserted, "total": len(INVENTORY)}
    return connection.execute_transaction_callback(work)


def list_isolation_inventory(actor: str) -> Dict[str, Any]:
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform isolation inventory permission denied")
    rows = connection.execute_query(
        "SELECT INVENTORY_ID,OBJECT_TYPE,OBJECT_NAME,SCOPE_KEYS_JSON,HUMAN_PATH,AGENT_PATH,SHARING_MODEL,"
        "DERIVED_INHERITANCE,MOVE_POLICY,ORACLE_ENFORCEMENT,PG_ENFORCEMENT,YASHAN_ENFORCEMENT,VERIFICATION_REF,"
        "STATUS,VERSION,UPDATED_AT FROM CX_DATABASE_ISOLATION_INVENTORY ORDER BY OBJECT_TYPE,OBJECT_NAME",
    )
    items = [_row(row) for row in rows]
    return {"items": items, "count": len(items)}
