"""v4.4.4 governed Portal Pool, node, storage, endpoint and command services."""

from __future__ import annotations

import json
import secrets
import hashlib
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from . import connection, identity_api, native_agent_api


class AgentPoolError(ValueError):
    """A governed platform-pool operation was rejected."""


_DISCOVERY_WINDOW: Dict[str, list[float]] = {}
_DISCOVERY_LOCK = threading.Lock()
_AGENT_INFO_DIRNAME = "AI-Agent-Infra-with-DB"


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(16)}"


def _row(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in dict(row or {}).items()}


def _rows(rows: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [_row(row) for row in rows]


def _require_admin(actor: str) -> None:
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _roles(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip().upper() for item in value if str(item).strip()}
    try:
        return {str(item).strip().upper() for item in json.loads(str(value or "[]")) if str(item).strip()}
    except (TypeError, ValueError):
        return set()


def resolve_agent_info_path(base_path: str) -> str:
    """Resolve a Linux node-local parent directory to the managed Agent root."""
    base = str(base_path or "").strip()
    if not base or not base.startswith("/"):
        raise AgentPoolError("the local Agent information parent directory must be an absolute Linux path")
    normalized = os.path.normpath(base)
    resolved = normalized if os.path.basename(normalized) == _AGENT_INFO_DIRNAME else os.path.join(normalized, _AGENT_INFO_DIRNAME)
    if len(resolved) > 512:
        raise AgentPoolError("the resolved local Agent information directory is too long")
    return resolved


def list_portal_llm_policy(actor: str) -> Dict[str, Any]:
    _require_admin(actor)
    policy = _row(connection.execute_query_one(
        "SELECT POLICY_ID,DEFAULT_PROFILE_ID,VERSION,UPDATED_BY,REASON,UPDATED_AT "
        "FROM CX_PORTAL_LLM_POLICIES WHERE POLICY_ID='DEFAULT'"))
    allowed = _rows(connection.execute_query(
        "SELECT PROFILE_ID FROM CX_PORTAL_LLM_ALLOWLIST WHERE POLICY_ID='DEFAULT' AND STATUS='ACTIVE' ORDER BY PROFILE_ID"))
    profiles = _rows(connection.execute_query(
        "SELECT PROFILE_ID,PROFILE_KEY,MODEL_ID,HEALTH_STATE,STATUS FROM CX_LLM_PROVIDER_PROFILES "
        "WHERE STATUS='ACTIVE' ORDER BY PROFILE_KEY"))
    return {"policy": policy, "allowed_profile_ids": [str(x.get("profile_id")) for x in allowed], "profiles": profiles}


def portal_llm_options() -> Dict[str, Any]:
    """Return display-only profiles permitted for an authenticated Portal session."""
    policy = _row(connection.execute_query_one("SELECT DEFAULT_PROFILE_ID,VERSION FROM CX_PORTAL_LLM_POLICIES WHERE POLICY_ID='DEFAULT'"))
    allowed = _rows(connection.execute_query("SELECT PROFILE_ID FROM CX_PORTAL_LLM_ALLOWLIST WHERE POLICY_ID='DEFAULT' AND STATUS='ACTIVE'"))
    ids = [str(item.get("profile_id")) for item in allowed]
    if not ids:
        return {"default_profile_id": policy.get("default_profile_id"), "version": policy.get("version"), "items": []}
    placeholders = ",".join(f":p{i}" for i in range(len(ids)))
    params = {f"p{i}": value for i, value in enumerate(ids)}
    rows = _rows(connection.execute_query("SELECT PROFILE_ID,PROFILE_KEY,MODEL_ID,HEALTH_STATE FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE' AND PROFILE_ID IN (" + placeholders + ") ORDER BY PROFILE_KEY", params))
    return {"default_profile_id": policy.get("default_profile_id"), "version": policy.get("version"), "items": rows}


def set_portal_llm_policy(actor: str, default_profile_id: str, allowed_profile_ids: list[str], reason: str, expected_version: int) -> Dict[str, Any]:
    _require_admin(actor)
    default_id = str(default_profile_id or "").strip()
    allowed = sorted({str(value).strip() for value in allowed_profile_ids if str(value).strip()})
    if not default_id or default_id not in allowed or len(str(reason or "").strip()) < 3:
        raise AgentPoolError("a default allowlisted profile and reason are required")
    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one("SELECT VERSION FROM CX_PORTAL_LLM_POLICIES WHERE POLICY_ID='DEFAULT' FOR UPDATE", {}))
        if not current or int(current.get("version") or 0) != int(expected_version):
            raise AgentPoolError("Portal LLM policy changed concurrently")
        for profile_id in allowed:
            profile = tx.query_one("SELECT PROFILE_ID,STATUS,HEALTH_STATE FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id", {"id": profile_id})
            if not profile or str(_row(profile).get("status") or "").upper() != "ACTIVE" or str(_row(profile).get("health_state") or "").upper() not in {"HEALTHY", "VERIFIED", "READY"}:
                raise AgentPoolError("every Portal LLM profile must be active and healthy")
        next_version = int(current.get("version") or 1) + 1
        tx.execute("UPDATE CX_PORTAL_LLM_POLICIES SET DEFAULT_PROFILE_ID=:profile,VERSION=:version,UPDATED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE POLICY_ID='DEFAULT'", {"profile": default_id, "version": next_version, "actor": actor, "reason": reason[:2000]})
        tx.execute("DELETE FROM CX_PORTAL_LLM_ALLOWLIST WHERE POLICY_ID='DEFAULT'", {})
        for profile_id in allowed:
            tx.execute("INSERT INTO CX_PORTAL_LLM_ALLOWLIST(POLICY_ID,PROFILE_ID,STATUS,UPDATED_BY,REASON) VALUES ('DEFAULT',:profile,'ACTIVE',:actor,:reason)", {"profile": profile_id, "actor": actor, "reason": reason[:2000]})
        identity_api._audit_tx(tx, actor, "PORTAL_LLM_POLICY_UPDATE", "PORTAL_LLM_POLICY", "DEFAULT", "ALLOW", reason)
        return {"policy_id": "DEFAULT", "default_profile_id": default_id, "allowed_profile_ids": allowed, "version": next_version}
    return connection.execute_transaction_callback(work)


def create_command(actor: str, command_type: str, target: Dict[str, Any], parameters: Dict[str, Any], security_domain_id: str, reason: str, expires_seconds: int = 900) -> Dict[str, Any]:
    _require_admin(actor)
    allowed = {"HEALTH_READ", "AGENT_STATUS_READ", "POOL_STATUS_READ", "LLM_STATUS_READ", "EMBEDDING_STATUS_READ", "NODE_VALIDATE", "STORAGE_VALIDATE", "AGENT_DRAIN", "AGENT_QUARANTINE", "PORTAL_LLM_POLICY_PROPOSE", "TEMPLATE_PUBLISH_PROPOSE"}
    kind = str(command_type or "").upper()
    if kind not in allowed or len(str(reason or "").strip()) < 3:
        raise AgentPoolError("unsupported command or missing reason")
    state = "COMPLETED" if kind.endswith("_READ") else "PENDING_APPROVAL"
    command_id = _id("CMD")
    expires = datetime.now(timezone.utc) + timedelta(seconds=max(60, min(int(expires_seconds), 86400)))
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("INSERT INTO CX_PLATFORM_ADMIN_COMMANDS(COMMAND_ID,COMMAND_TYPE,TARGET_JSON,PARAMETERS_JSON,SECURITY_DOMAIN_ID,REQUESTED_BY,REASON,STATUS,EXPIRES_AT) VALUES (:id,:type,:target,:params,:domain,:actor,:reason,:status,:expires)", {"id": command_id, "type": kind, "target": _json(target), "params": _json(parameters), "domain": security_domain_id or "DEFAULT", "actor": actor, "reason": reason[:2000], "status": state, "expires": expires}),
        identity_api._audit_tx(tx, actor, "PLATFORM_ADMIN_COMMAND", "ADMIN_COMMAND", command_id, "ALLOW", reason)
    )[0])
    result: Dict[str, Any] = {}
    action: Dict[str, Any] = {}
    if state == "COMPLETED":
        result = execute_read_command(actor, command_id)
    else:
        # The command is durable before the Action Card is created. The card
        # is the only path that can later approve a mutation; chat text and
        # LLM output never call a mutating service directly.
        action = identity_api.create_action_card(
            actor, "CH_PLATFORM_ADMINISTRATION", "PLATFORM_ADMIN_COMMAND",
            {"command_id": command_id, "command_type": kind, "target": target, "parameters": parameters,
             "security_domain_id": security_domain_id or "DEFAULT"}, reason, "ADMIN_COMMAND:" + command_id)
    return {"command_id": command_id, "command_type": kind, "status": state, "expires_at": expires.isoformat(), "result": result, "action_card": action}


def execute_approved_command(actor: str, command_id: str, action_id: str) -> Dict[str, Any]:
    """Execute only a confirmed platform command from an Action Card."""
    _require_admin(actor)
    def work(tx: Any) -> Dict[str, Any]:
        action = _row(tx.query_one(
            "SELECT ACTION_ID,ACTION_TYPE,PAYLOAD_JSON,STATUS FROM CX_ACTION_CARDS WHERE ACTION_ID=:id FOR UPDATE",
            {"id": action_id}))
        command = _row(tx.query_one(
            "SELECT COMMAND_ID,COMMAND_TYPE,TARGET_JSON,PARAMETERS_JSON,STATUS FROM CX_PLATFORM_ADMIN_COMMANDS WHERE COMMAND_ID=:id FOR UPDATE",
            {"id": command_id}))
        if not action or str(action.get("status") or "").upper() != "CONFIRMED":
            raise AgentPoolError("the platform Action Card is not confirmed")
        if not command or str(command.get("status") or "").upper() != "PENDING_APPROVAL":
            raise AgentPoolError("the platform command is no longer pending")
        payload = json.loads(str(action.get("payload_json") or "{}"))
        if str(payload.get("command_id") or "") != command_id or str(command.get("command_type") or "").upper() != "AGENT_DRAIN":
            raise AgentPoolError("the platform Action Card does not match the requested command")
        target = json.loads(str(command.get("target_json") or "{}"))
        params = json.loads(str(command.get("parameters_json") or "{}"))
        source = str(target.get("node_id") or "").strip()
        destination = str(params.get("target_node_id") or "").strip()
        if not source or not destination or source == destination:
            raise AgentPoolError("a different source and destination node are required")
        source_row = _row(tx.query_one("SELECT NODE_ID,STATUS FROM CX_MANAGED_NODES WHERE NODE_ID=:id FOR UPDATE", {"id": source}))
        destination_row = _row(tx.query_one("SELECT NODE_ID,STATUS,ROLE_JSON FROM CX_MANAGED_NODES WHERE NODE_ID=:id FOR UPDATE", {"id": destination}))
        if not source_row or str(source_row.get("status") or "").upper() == "RETIRED":
            raise AgentPoolError("source node is unavailable")
        if not destination_row or str(destination_row.get("status") or "").upper() not in {"ACTIVE", "VALIDATED"} or "AGENT_POOL" not in _roles(destination_row.get("role_json")):
            raise AgentPoolError("destination must be an active Agent Pool node")
        tx.execute("UPDATE CX_RUNTIME_WORKERS SET STATUS='DRAINING',UPDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:id AND STATUS IN ('ONLINE','STARTING')", {"id": source})
        retried = tx.execute("UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='PENDING',WORKER_ID=NULL,NODE_ID=:destination,LEASE_EXPIRES_AT=NULL,UPDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:source AND STATUS='CLAIMED' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP", {"source": source, "destination": destination})
        active = _row(tx.query_one("SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE NODE_ID=:id AND STATUS IN ('CLAIMED','RUNNING','STREAMING','WAITING')", {"id": source})) or {}
        tx.execute("UPDATE CX_PLATFORM_ADMIN_COMMANDS SET STATUS='COMPLETED',UPDATED_AT=CURRENT_TIMESTAMP WHERE COMMAND_ID=:id", {"id": command_id})
        identity_api._audit_tx(tx, actor, "AGENT_POOL_NODE_DRAIN", "MANAGED_NODE", source, "ALLOW", "confirmed Action Card " + action_id)
        return {"command_id": command_id, "source_node_id": source, "destination_node_id": destination, "status": "DRAINING", "requeued_expired_tasks": int(retried or 0), "running_tasks_remaining": int(active.get("cnt") or 0)}
    return connection.execute_transaction_callback(work)


def list_commands(actor: str, limit: int = 50) -> list[Dict[str, Any]]:
    _require_admin(actor)
    suffix = " LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST :limit ROWS ONLY"
    return _rows(connection.execute_query("SELECT COMMAND_ID,COMMAND_TYPE,TARGET_JSON,PARAMETERS_JSON,SECURITY_DOMAIN_ID,REQUESTED_BY,REASON,STATUS,EXPIRES_AT,CREATED_AT,UPDATED_AT FROM CX_PLATFORM_ADMIN_COMMANDS ORDER BY CREATED_AT DESC" + suffix, {"limit": max(1, min(int(limit), 200))}))


def execute_read_command(actor: str, command_id: str) -> Dict[str, Any]:
    """Execute a closed, read-only command and return credential-free data."""
    _require_admin(actor)
    command = _row(connection.execute_query_one(
        "SELECT COMMAND_ID,COMMAND_TYPE,STATUS,EXPIRES_AT FROM CX_PLATFORM_ADMIN_COMMANDS WHERE COMMAND_ID=:id",
        {"id": command_id}))
    if not command or str(command.get("status") or "").upper() != "COMPLETED":
        raise AgentPoolError("read command is unavailable")
    kind = str(command.get("command_type") or "").upper()
    if not kind.endswith("_READ"):
        raise AgentPoolError("only read commands can be executed directly")
    if kind == "HEALTH_READ":
        result = {"status": "ok", "scope": "database_control_plane"}
    elif kind == "AGENT_STATUS_READ":
        result = {"active": _count("CX_NATIVE_AGENTS", "STATUS='ACTIVE'"), "inactive": _count("CX_NATIVE_AGENTS", "STATUS<>'ACTIVE'")}
    elif kind == "POOL_STATUS_READ":
        result = {"nodes": _count("CX_MANAGED_NODES", "STATUS IN ('REGISTERED','VALIDATED')"), "pending_validation": _count("CX_MANAGED_NODES", "VALIDATION_STATE='PENDING'")}
    elif kind == "LLM_STATUS_READ":
        result = {"active": _count("CX_LLM_PROVIDER_PROFILES", "STATUS='ACTIVE'"), "healthy": _count("CX_LLM_PROVIDER_PROFILES", "STATUS='ACTIVE' AND HEALTH_STATE IN ('HEALTHY','VERIFIED','READY')")}
    elif kind == "EMBEDDING_STATUS_READ":
        result = {"profiles": _count("CX_EMBEDDING_PROFILES", "STATUS='ACTIVE'"), "contracts": _count("CX_EMBEDDING_CONTRACTS", "STATUS='ACTIVE'")}
    else:
        raise AgentPoolError("unsupported read command")
    identity_api._audit(actor, "PLATFORM_ADMIN_COMMAND_READ", "ADMIN_COMMAND", command_id, "ALLOW", "read command executed")
    return result


def _count(table: str, predicate: str) -> int:
    try:
        value = _row(connection.execute_query_one(f"SELECT COUNT(*) AS CNT FROM {table} WHERE {predicate}")) or {}
        return int(value.get("cnt") or 0)
    except Exception:
        return 0


def list_nodes(actor: str, limit: int = 100) -> list[Dict[str, Any]]:
    _require_admin(actor)
    suffix = " LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST :limit ROWS ONLY"
    return _rows(connection.execute_query("SELECT NODE_ID,NODE_KEY,HOST_REFERENCE,SSH_PORT,OS_USER,ROLE_JSON,FAILURE_DOMAIN,TRUST_MODE,AGENT_INFO_PATH,STATUS,VALIDATION_STATE,CREATED_BY,LAST_VALIDATED_AT FROM CX_MANAGED_NODES WHERE STATUS <> 'RETIRED' ORDER BY NODE_KEY" + suffix, {"limit": max(1, min(int(limit), 500))}))


def retire_node(actor: str, node_id: str, reason: str) -> Dict[str, Any]:
    """Governedly remove a managed node while retaining its audit history."""
    _require_admin(actor)
    node_key = str(node_id or "").strip()
    why = str(reason or "").strip()
    if not node_key or len(why) < 3:
        raise AgentPoolError("a node and removal reason of at least three characters are required")

    def work(tx: Any) -> Dict[str, Any]:
        node = _row(tx.query_one(
            "SELECT NODE_ID,NODE_KEY,STATUS,CREATED_BY FROM CX_MANAGED_NODES WHERE NODE_ID=:id FOR UPDATE",
            {"id": node_key}))
        if not node:
            raise AgentPoolError("managed node is unavailable")
        if str(node.get("status") or "").upper() == "RETIRED":
            raise AgentPoolError("managed node is already retired")
        if str(node.get("created_by") or "").upper() == "SYSTEM_BOOTSTRAP":
            raise AgentPoolError("the bootstrap system node cannot be removed")

        blockers: list[str] = []
        checks = (
            ("active runtime workers", "SELECT COUNT(*) AS CNT FROM CX_RUNTIME_WORKERS WHERE NODE_ID=:id AND STATUS IN ('ONLINE','STARTING','DRAINING')"),
            ("active Agent Pool onboarding", "SELECT COUNT(*) AS CNT FROM CX_AGENT_POOL_NODE_ONBOARDINGS WHERE NODE_ID=:id AND STATUS IN ('PENDING','CHECKED_IN','ACTIVE') AND EXPIRES_AT>CURRENT_TIMESTAMP"),
            ("active storage bindings", "SELECT COUNT(*) AS CNT FROM CX_MANAGED_NODE_STORAGE_BINDINGS WHERE NODE_ID=:id AND STATUS IN ('BOUND','ACTIVE')"),
            ("active Admin Agent membership", "SELECT COUNT(*) AS CNT FROM CX_ADMIN_AGENT_MEMBERS WHERE NODE_ID=:id AND STATUS IN ('CANDIDATE','APPROVED','ACTIVE')"),
            ("active executions", "SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE NODE_ID=:id AND STATUS IN ('PENDING','CLAIMED','RUNNING','STREAMING','WAITING')"),
        )
        for label, query in checks:
            try:
                count = _row(tx.query_one(query, {"id": node_key})) or {}
                if int(count.get("cnt") or 0) > 0:
                    blockers.append(label)
            except Exception:
                # Optional v4.4 tables are absent only on pre-v4.4 schemas;
                # the node API remains usable there while known dependencies
                # are still enforced whenever their tables exist.
                continue
        if blockers:
            raise AgentPoolError("node removal blocked by: " + ", ".join(blockers))
        tx.execute(
            "UPDATE CX_MANAGED_NODES SET STATUS='RETIRED',VALIDATION_STATE='RETIRED',REASON=:reason WHERE NODE_ID=:id",
            {"id": node_key, "reason": why[:2000]},
        )
        _audit_tx(tx, actor, "MANAGED_NODE_RETIRE", "MANAGED_NODE", node_key, "ALLOW", why)
        return {"node_id": node_key, "node_key": node.get("node_key"), "status": "RETIRED"}
    return connection.execute_transaction_callback(work)


def register_node(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require_admin(actor)
    if len(str(body.get("reason") or "").strip()) < 3 or not body.get("node_key") or not body.get("host_reference"):
        raise AgentPoolError("node key, host reference, and reason are required")
    trust = str(body.get("trust_mode") or "MUTUAL_TRUST").upper()
    if trust not in {"MUTUAL_TRUST", "ONE_USE_PASSWORD"}:
        raise AgentPoolError("unsupported SSH trust mode")
    roles = {str(item).strip().upper() for item in (body.get("roles") or []) if str(item).strip()}
    local_path = str(body.get("agent_info_path") or "").strip()
    if ("ADMIN_AGENT" in roles or "AGENT_POOL" in roles) and not local_path:
        raise AgentPoolError("a local Agent information directory is required for Admin Agent and Agent Pool nodes")
    if local_path:
        local_path = resolve_agent_info_path(local_path)
    node_id = _id("NODE")
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("INSERT INTO CX_MANAGED_NODES(NODE_ID,NODE_KEY,HOST_REFERENCE,SSH_PORT,OS_USER,ROLE_JSON,FAILURE_DOMAIN,TRUST_MODE,AGENT_INFO_PATH,STATUS,VALIDATION_STATE,CREATED_BY,REASON) VALUES (:id,:key,:host,:port,:user,:roles,:domain,:trust,:agent_info_path,'REGISTERED','PENDING',:actor,:reason)", {"id": node_id, "key": str(body["node_key"])[:128], "host": str(body["host_reference"])[:256], "port": int(body.get("ssh_port") or 22), "user": str(body.get("os_user") or "")[:128], "roles": _json(body.get("roles") or []), "domain": str(body.get("failure_domain") or "")[:128], "trust": trust, "agent_info_path": local_path[:512], "actor": actor, "reason": str(body["reason"])[:2000]}),
        identity_api._audit_tx(tx, actor, "MANAGED_NODE_REGISTER", "MANAGED_NODE", node_id, "ALLOW", str(body["reason"]))
    )[0])
    return {"node_id": node_id, "status": "REGISTERED", "validation_state": "PENDING"}


def ensure_managed_node(*, node_key: str, host_reference: str, roles: list[str],
                        actor: str = "SYSTEM_BOOTSTRAP", ssh_port: int = 22,
                        os_user: str = "", failure_domain: str = "", agent_info_path: str = "",
                        reason: str = "automatic node inventory") -> Dict[str, Any]:
    """Create or return a node discovered by platform/runtime deployment.

    Manual node registration is intentionally not required for platform-owned
    runtimes. Discovery records metadata only; reachability and SSH trust are
    still validated by the authenticated adapter.
    """
    key = str(node_key or "").strip()[:128]
    host = str(host_reference or "").strip()[:256]
    if not key or not host:
        raise AgentPoolError("automatic node inventory requires node key and host")
    existing = _row(connection.execute_query_one(
        "SELECT NODE_ID,AGENT_INFO_PATH,STATUS,VALIDATION_STATE FROM CX_MANAGED_NODES WHERE NODE_KEY=:key",
        {"key": key},
    ))
    if existing:
        if agent_info_path and (not str(existing.get("agent_info_path") or "").strip() or actor == "SYSTEM_BOOTSTRAP"):
            node_ids = {str(existing["node_id"])}
            if actor == "SYSTEM_BOOTSTRAP":
                family = key.split(":", 1)[0]
                discovered = _rows(connection.execute_query(
                    "SELECT NODE_ID,NODE_KEY,HOST_REFERENCE FROM CX_MANAGED_NODES WHERE CREATED_BY='SYSTEM_BOOTSTRAP' AND (AGENT_INFO_PATH IS NULL OR AGENT_INFO_PATH='')"
                ))
                node_ids.update(str(item["node_id"]) for item in discovered
                                if str(item.get("host_reference") or "") == host
                                or str(item.get("node_key") or "").split(":", 1)[0] == family)

            def record_paths(tx: Any) -> None:
                for discovered_id in node_ids:
                    tx.execute("UPDATE CX_MANAGED_NODES SET AGENT_INFO_PATH=:path WHERE NODE_ID=:id", {"path": str(agent_info_path)[:512], "id": discovered_id})
                identity_api._audit_tx(tx, actor, "MANAGED_NODE_LOCAL_PATH_DISCOVER", "MANAGED_NODE", str(existing["node_id"]), "ALLOW", "platform startup recorded the deployment directory")

            connection.execute_transaction_callback(record_paths)
        return {"node_id": existing.get("node_id"), "status": existing.get("status"),
                "validation_state": existing.get("validation_state"), "agent_info_path": str(agent_info_path or existing.get("agent_info_path") or ""), "discovered": False}
    node_id = _id("NODE")
    role_json = _json([str(value).upper() for value in roles if str(value).strip()])
    connection.execute_transaction_callback(lambda tx: (
        tx.execute(
            "INSERT INTO CX_MANAGED_NODES(NODE_ID,NODE_KEY,HOST_REFERENCE,SSH_PORT,OS_USER,ROLE_JSON,FAILURE_DOMAIN,TRUST_MODE,AGENT_INFO_PATH,STATUS,VALIDATION_STATE,CREATED_BY,REASON) "
            "VALUES (:node_id_value,:node_key_value,:host_value,:port_value,:os_user_value,:roles_json,:domain_value,'MUTUAL_TRUST',:agent_info_path_value,'REGISTERED','PENDING',:actor_value,:reason_value)",
            {"node_id_value": node_id, "node_key_value": key, "host_value": host, "port_value": int(ssh_port or 22),
             "os_user_value": str(os_user or "")[:128], "roles_json": role_json,
             "domain_value": str(failure_domain or "")[:128], "agent_info_path_value": str(agent_info_path or "")[:512], "actor_value": actor,
             "reason_value": str(reason)[:2000]},
        ),
        identity_api._audit_tx(tx, actor, "MANAGED_NODE_DISCOVER", "MANAGED_NODE", node_id, "ALLOW", str(reason)[:2000]),
    )[0])
    return {"node_id": node_id, "status": "REGISTERED", "validation_state": "PENDING", "discovered": True}


def validate_node(actor: str, node_id: str) -> Dict[str, Any]:
    """Perform a bounded connectivity check; never opens a remote shell."""
    _require_admin(actor)
    node = _row(connection.execute_query_one(
        "SELECT NODE_ID,HOST_REFERENCE,SSH_PORT,STATUS FROM CX_MANAGED_NODES WHERE NODE_ID=:id",
        {"id": node_id}))
    if not node:
        raise AgentPoolError("managed node is unavailable")
    state, detail = "FAILED", "host could not be reached"
    try:
        host = str(node.get("host_reference") or "")
        port = int(node.get("ssh_port") or 22)
        # Resolve and connect with a short timeout. SSH authentication and
        # command execution belong to a separately authenticated adapter.
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        with socket.create_connection((host, port), timeout=3):
            state, detail = "REACHABLE", "TCP endpoint reachable; SSH authentication not attempted"
    except (OSError, ValueError):
        pass
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("UPDATE CX_MANAGED_NODES SET VALIDATION_STATE=:state,LAST_VALIDATED_AT=CURRENT_TIMESTAMP,STATUS=:status WHERE NODE_ID=:id", {"state": state, "status": "VALIDATED" if state == "REACHABLE" else "REGISTERED", "id": node_id}),
        identity_api._audit_tx(tx, actor, "MANAGED_NODE_VALIDATE", "MANAGED_NODE", node_id, "ALLOW" if state == "REACHABLE" else "ERROR", detail)
    )[0])
    return {"node_id": node_id, "validation_state": state, "detail": detail}


def list_node_onboardings(actor: str, limit: int = 100) -> list[Dict[str, Any]]:
    """Return credential-free Host/adapter onboarding states for Pool nodes."""
    _require_admin(actor)
    suffix = " LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST :limit ROWS ONLY"
    return _rows(connection.execute_query(
        "SELECT o.ONBOARDING_ID,o.NODE_ID,n.NODE_KEY,n.HOST_REFERENCE,o.INTEGRATION_KIND,o.STATUS,"
        "o.EXPIRES_AT,o.CHECKED_IN_AT,o.LAST_HEARTBEAT_AT,o.RUNTIME_VERSION,o.REASON,o.CREATED_AT "
        "FROM CX_AGENT_POOL_NODE_ONBOARDINGS o JOIN CX_MANAGED_NODES n ON n.NODE_ID=o.NODE_ID "
        "WHERE n.STATUS <> 'RETIRED' ORDER BY o.CREATED_AT DESC" + suffix,
        {"limit": max(1, min(int(limit), 200))},
    ))


def create_node_onboarding(actor: str, node_id: str, reason: str, expires_seconds: int = 1800) -> Dict[str, Any]:
    """Create a single-use Host bootstrap token after bounded node validation.

    The token is returned once and only its digest is persisted.  It proves
    that the host received the operator-issued bootstrap command; it is not a
    substitute for SSH credentials, database identity, or authorization.
    """
    _require_admin(actor)
    if len(str(reason or "").strip()) < 3:
        raise AgentPoolError("an onboarding reason is required")
    node = _row(connection.execute_query_one(
        "SELECT NODE_ID,NODE_KEY,ROLE_JSON,VALIDATION_STATE,STATUS FROM CX_MANAGED_NODES WHERE NODE_ID=:id",
        {"id": str(node_id or "")},
    ))
    if not node or "AGENT_POOL" not in _roles(node.get("role_json")):
        raise AgentPoolError("an Agent Pool managed node is required")
    if str(node.get("validation_state") or "").upper() not in {"REACHABLE", "ONLINE"}:
        raise AgentPoolError("validate the host reachability before issuing a bootstrap token")
    onboarding_id = _id("POOLONBOARD")
    token = "POOLNODE_" + secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=max(300, min(int(expires_seconds), 86400)))
    def work(tx: Any) -> None:
        tx.execute(
            "UPDATE CX_AGENT_POOL_NODE_ONBOARDINGS SET STATUS='SUPERSEDED',UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE NODE_ID=:node AND STATUS IN ('PENDING_CHECKIN','CHECKED_IN')",
            {"node": node["node_id"]},
        )
        tx.execute(
            "INSERT INTO CX_AGENT_POOL_NODE_ONBOARDINGS(ONBOARDING_ID,NODE_ID,INTEGRATION_KIND,TOKEN_DIGEST,STATUS,EXPIRES_AT,RESULT_JSON,CREATED_BY,REASON) "
            "VALUES (:id,:node,'HOST_BOOTSTRAP',:digest,'PENDING_CHECKIN',:expires,:result,:actor,:reason)",
            {"id": onboarding_id, "node": node["node_id"], "digest": _digest(token),
             "expires": expires, "result": _json({"issued": True}), "actor": actor,
             "reason": str(reason)[:2000]},
        )
        identity_api._audit_tx(tx, actor, "AGENT_POOL_NODE_BOOTSTRAP_ISSUE", "AGENT_POOL_NODE_ONBOARDING", onboarding_id, "ALLOW", str(reason)[:2000])
    connection.execute_transaction_callback(work)
    return {"onboarding_id": onboarding_id, "node_id": node["node_id"], "node_key": node["node_key"],
            "bootstrap_token": token, "expires_at": expires.isoformat(), "status": "PENDING_CHECKIN"}


def _verify_onboarding_token(onboarding_id: str, token: str, *, allow_active: bool) -> Dict[str, Any]:
    record = _row(connection.execute_query_one(
        "SELECT ONBOARDING_ID,NODE_ID,TOKEN_DIGEST,STATUS,EXPIRES_AT FROM CX_AGENT_POOL_NODE_ONBOARDINGS WHERE ONBOARDING_ID=:id",
        {"id": str(onboarding_id or "")},
    ))
    allowed = {"PENDING_CHECKIN", "CHECKED_IN"}
    if allow_active:
        allowed.add("ACTIVE")
    if not record or str(record.get("status") or "").upper() not in allowed:
        raise PermissionError("Agent Pool node onboarding is unavailable")
    if not secrets.compare_digest(str(record.get("token_digest") or ""), _digest(token)):
        raise PermissionError("Agent Pool node bootstrap token is invalid")
    valid = _row(connection.execute_query_one(
        "SELECT ONBOARDING_ID FROM CX_AGENT_POOL_NODE_ONBOARDINGS WHERE ONBOARDING_ID=:id AND EXPIRES_AT>CURRENT_TIMESTAMP",
        {"id": str(onboarding_id)},
    ))
    if not valid:
        raise PermissionError("Agent Pool node bootstrap token has expired")
    return record


def node_onboarding_checkin(onboarding_id: str, token: str, runtime_version: str, hostname: str, shared_path: str = "", agent_info_path: str = "") -> Dict[str, Any]:
    """Accept a bounded, token-authenticated receipt from the target host."""
    record = _verify_onboarding_token(onboarding_id, token, allow_active=False)
    if not str(runtime_version or "").strip() or not str(hostname or "").strip():
        raise AgentPoolError("runtime version and hostname are required for node check-in")
    evidence = {"hostname": str(hostname)[:128], "shared_path": str(shared_path or "")[:512], "agent_info_path": str(agent_info_path or "")[:512], "receipt": "host_bootstrap"}
    connection.execute_transaction_callback(lambda tx: (
        tx.execute(
            "UPDATE CX_AGENT_POOL_NODE_ONBOARDINGS SET STATUS='CHECKED_IN',CHECKED_IN_AT=CURRENT_TIMESTAMP,"
            "LAST_HEARTBEAT_AT=CURRENT_TIMESTAMP,RUNTIME_VERSION=:version,RESULT_JSON=:result,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE ONBOARDING_ID=:id",
            {"id": record["onboarding_id"], "version": str(runtime_version)[:128], "result": _json(evidence)},
        ),
        identity_api._audit_tx(tx, "POOL_NODE:" + str(record["node_id"]), "AGENT_POOL_NODE_CHECKIN", "AGENT_POOL_NODE_ONBOARDING", str(record["onboarding_id"]), "ALLOW", "host bootstrap receipt"),
    )[0])
    return {"onboarding_id": record["onboarding_id"], "status": "CHECKED_IN", "next_step": "administrator_activation"}


def activate_node_onboarding(actor: str, onboarding_id: str, reason: str) -> Dict[str, Any]:
    """Activate only a checked-in Pool node with a dedicated storage binding."""
    _require_admin(actor)
    if len(str(reason or "").strip()) < 3:
        raise AgentPoolError("an activation reason is required")
    record = _row(connection.execute_query_one(
        "SELECT ONBOARDING_ID,NODE_ID,STATUS FROM CX_AGENT_POOL_NODE_ONBOARDINGS WHERE ONBOARDING_ID=:id",
        {"id": str(onboarding_id or "")},
    ))
    if not record or str(record.get("status") or "").upper() != "CHECKED_IN":
        raise AgentPoolError("a checked-in Agent Pool node onboarding is required")
    bindings = _rows(connection.execute_query(
        "SELECT s.STORAGE_PURPOSE FROM CX_MANAGED_NODE_STORAGE_BINDINGS b "
        "JOIN CX_SHARED_STORAGE_PROFILES s ON s.STORAGE_ID=b.STORAGE_ID "
        "WHERE b.NODE_ID=:node AND b.STATUS='BOUND' AND b.ROLE_SCOPE IN ('AGENT_POOL','ALL_PLATFORM_AGENTS') "
        "AND s.STORAGE_PURPOSE='AGENT_POOL_RUNTIME'",
        {"node": record["node_id"]},
    ))
    purposes = {str(item.get("storage_purpose") or "").upper() for item in bindings}
    node = _row(connection.execute_query_one("SELECT AGENT_INFO_PATH FROM CX_MANAGED_NODES WHERE NODE_ID=:node", {"node": record["node_id"]}))
    required = {"AGENT_POOL_RUNTIME"}
    if not str(node.get("agent_info_path") or "").strip():
        raise AgentPoolError("the Agent Pool node must have a local Agent information directory")
    if not required.issubset(purposes):
        raise AgentPoolError("bind both Agent Pool shared and Agent information directories before activation")
    def work(tx: Any) -> None:
        tx.execute("UPDATE CX_AGENT_POOL_NODE_ONBOARDINGS SET STATUS='ACTIVE',LAST_HEARTBEAT_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE ONBOARDING_ID=:id", {"id": record["onboarding_id"]})
        tx.execute("UPDATE CX_MANAGED_NODES SET STATUS='ACTIVE',VALIDATION_STATE='ONLINE',LAST_VALIDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:node", {"node": record["node_id"]})
        identity_api._audit_tx(tx, actor, "AGENT_POOL_NODE_ACTIVATE", "AGENT_POOL_NODE_ONBOARDING", str(record["onboarding_id"]), "ALLOW", str(reason)[:2000])
    connection.execute_transaction_callback(work)
    return {"onboarding_id": record["onboarding_id"], "status": "ACTIVE"}


def node_onboarding_heartbeat(onboarding_id: str, token: str, runtime_version: str) -> Dict[str, Any]:
    record = _verify_onboarding_token(onboarding_id, token, allow_active=True)
    if str(record.get("status") or "").upper() != "ACTIVE":
        raise PermissionError("Agent Pool node is not active")
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("UPDATE CX_AGENT_POOL_NODE_ONBOARDINGS SET LAST_HEARTBEAT_AT=CURRENT_TIMESTAMP,RUNTIME_VERSION=:version,UPDATED_AT=CURRENT_TIMESTAMP WHERE ONBOARDING_ID=:id", {"id": record["onboarding_id"], "version": str(runtime_version or "unknown")[:128]}),
        tx.execute("UPDATE CX_MANAGED_NODES SET STATUS='ACTIVE',VALIDATION_STATE='ONLINE',LAST_VALIDATED_AT=CURRENT_TIMESTAMP WHERE NODE_ID=:node", {"node": record["node_id"]}),
    )[0])
    return {"onboarding_id": record["onboarding_id"], "status": "ACTIVE"}


def list_storage(actor: str) -> list[Dict[str, Any]]:
    _require_admin(actor)
    return _rows(connection.execute_query("SELECT STORAGE_ID,STORAGE_KEY,BACKEND_KIND,LOCATION_REF,STORAGE_PURPOSE,STATUS,VALIDATION_STATE,CREATED_AT FROM CX_SHARED_STORAGE_PROFILES WHERE STORAGE_PURPOSE IN ('ADMIN_RUNTIME','AGENT_POOL_RUNTIME') AND STATUS <> 'REMOVED' ORDER BY STORAGE_KEY"))


def register_storage(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require_admin(actor)
    kind = str(body.get("backend_kind") or "LOCAL_PATH").upper()
    purpose = str(body.get("storage_purpose") or "ADMIN_RUNTIME").upper()
    if purpose not in {"ADMIN_RUNTIME", "AGENT_POOL_RUNTIME"}:
        raise AgentPoolError("unsupported shared storage purpose")
    if kind not in {"LOCAL_PATH", "NFS", "OBJECT_STORAGE", "UNIFIED_STORAGE"} or not body.get("storage_key") or not body.get("location_ref") or len(str(body.get("reason") or "").strip()) < 3:
        raise AgentPoolError("storage key, location, supported backend, and reason are required")
    state = "PENDING" if kind == "LOCAL_PATH" else "UNSUPPORTED_ADAPTER"
    storage_id = _id("STORE")
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("INSERT INTO CX_SHARED_STORAGE_PROFILES(STORAGE_ID,STORAGE_KEY,BACKEND_KIND,LOCATION_REF,STORAGE_PURPOSE,STATUS,VALIDATION_STATE,CREATED_BY,REASON) VALUES (:id,:key,:kind,:location,:purpose,'REGISTERED',:state,:actor,:reason)", {"id": storage_id, "key": str(body["storage_key"])[:128], "kind": kind, "location": str(body["location_ref"])[:512], "purpose": purpose, "state": state, "actor": actor, "reason": str(body["reason"])[:2000]}),
        identity_api._audit_tx(tx, actor, "SHARED_STORAGE_REGISTER", "SHARED_STORAGE", storage_id, "ALLOW", str(body["reason"]))
    )[0])
    return {"storage_id": storage_id, "status": "REGISTERED", "validation_state": state}


def validate_storage(actor: str, storage_id: str) -> Dict[str, Any]:
    _require_admin(actor)
    storage = _row(connection.execute_query_one(
        "SELECT STORAGE_ID,BACKEND_KIND,LOCATION_REF FROM CX_SHARED_STORAGE_PROFILES WHERE STORAGE_ID=:id",
        {"id": storage_id}))
    if not storage:
        raise AgentPoolError("shared storage profile is unavailable")
    kind = str(storage.get("backend_kind") or "").upper()
    state, detail = "UNSUPPORTED_ADAPTER", "backend adapter is not enabled"
    if kind == "LOCAL_PATH":
        location = os.path.abspath(str(storage.get("location_ref") or ""))
        try:
            state = "READY" if os.path.isdir(location) and os.access(location, os.R_OK | os.W_OK | os.X_OK) else "FAILED"
            detail = "local path is accessible" if state == "READY" else "local path is missing or not writable"
        except OSError:
            state, detail = "FAILED", "local path validation failed"
    connection.execute_transaction_callback(lambda tx: (
        tx.execute("UPDATE CX_SHARED_STORAGE_PROFILES SET VALIDATION_STATE=:state WHERE STORAGE_ID=:id", {"state": state, "id": storage_id}),
        identity_api._audit_tx(tx, actor, "SHARED_STORAGE_VALIDATE", "SHARED_STORAGE", storage_id, "ALLOW" if state == "READY" else "ERROR", detail)
    )[0])
    return {"storage_id": storage_id, "validation_state": state, "detail": detail}


def list_node_storage_bindings(actor: str) -> list[Dict[str, Any]]:
    _require_admin(actor)
    return _rows(connection.execute_query(
        "SELECT b.BINDING_ID,b.NODE_ID,n.NODE_KEY,b.STORAGE_ID,s.STORAGE_KEY,b.MOUNT_REFERENCE,"
        "b.ROLE_SCOPE,b.STATUS,b.REASON,b.CREATED_AT FROM CX_MANAGED_NODE_STORAGE_BINDINGS b "
        "JOIN CX_MANAGED_NODES n ON n.NODE_ID=b.NODE_ID JOIN CX_SHARED_STORAGE_PROFILES s ON s.STORAGE_ID=b.STORAGE_ID "
        "WHERE b.STATUS <> 'REMOVED' AND n.STATUS <> 'RETIRED' ORDER BY b.CREATED_AT DESC"))


def bind_node_storage(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require_admin(actor)
    node_id = str(body.get("node_id") or "").strip()
    storage_id = str(body.get("storage_id") or "").strip()
    mount = str(body.get("mount_reference") or "").strip()
    scope = str(body.get("role_scope") or "ADMIN_AGENT").strip().upper()
    reason = str(body.get("reason") or "").strip()
    if not node_id or not storage_id or not mount or len(reason) < 3:
        raise AgentPoolError("node, storage, mount reference, and reason are required")
    if scope not in {"ADMIN_AGENT", "COMPLIANCE_AGENT", "AGENT_POOL", "ALL_PLATFORM_AGENTS"}:
        raise AgentPoolError("unsupported storage role scope")
    binding_id = _id("BIND")
    def work(tx: Any) -> None:
        if not _row(tx.query_one("SELECT NODE_ID FROM CX_MANAGED_NODES WHERE NODE_ID=:id", {"id": node_id})):
            raise AgentPoolError("managed node is unavailable")
        if not _row(tx.query_one("SELECT STORAGE_ID FROM CX_SHARED_STORAGE_PROFILES WHERE STORAGE_ID=:id", {"id": storage_id})):
            raise AgentPoolError("shared storage profile is unavailable")
        storage_row = _row(tx.query_one("SELECT STORAGE_PURPOSE FROM CX_SHARED_STORAGE_PROFILES WHERE STORAGE_ID=:id", {"id": storage_id}))
        purpose = str(storage_row.get("storage_purpose") or "ADMIN_RUNTIME").upper() if storage_row else ""
        allowed = {
            "ADMIN_AGENT": {"ADMIN_RUNTIME"},
            "AGENT_POOL": {"AGENT_POOL_RUNTIME"},
            "ALL_PLATFORM_AGENTS": {"ADMIN_RUNTIME", "AGENT_POOL_RUNTIME"},
        }
        if purpose not in allowed.get(scope, set()):
            raise AgentPoolError("storage purpose does not match the selected node role")
        tx.execute("INSERT INTO CX_MANAGED_NODE_STORAGE_BINDINGS(BINDING_ID,NODE_ID,STORAGE_ID,MOUNT_REFERENCE,ROLE_SCOPE,STATUS,REASON,CREATED_BY) VALUES (:id,:node,:storage,:mount,:scope,'BOUND',:reason,:actor)", {"id": binding_id, "node": node_id, "storage": storage_id, "mount": mount[:512], "scope": scope, "reason": reason[:2000], "actor": actor})
        identity_api._audit_tx(tx, actor, "NODE_STORAGE_BIND", "NODE_STORAGE_BINDING", binding_id, "ALLOW", reason)
    connection.execute_transaction_callback(work)
    return {"binding_id": binding_id, "status": "BOUND"}


def remove_node_storage_binding(actor: str, binding_id: str, reason: str) -> Dict[str, Any]:
    _require_admin(actor)
    if len(str(reason or "").strip()) < 3:
        raise AgentPoolError("removal reason is required")
    def work(tx: Any) -> None:
        if not _row(tx.query_one("SELECT BINDING_ID FROM CX_MANAGED_NODE_STORAGE_BINDINGS WHERE BINDING_ID=:id", {"id": binding_id})):
            raise AgentPoolError("storage binding is unavailable")
        tx.execute("UPDATE CX_MANAGED_NODE_STORAGE_BINDINGS SET STATUS='REMOVED',REASON=:reason WHERE BINDING_ID=:id", {"id": binding_id, "reason": str(reason)[:2000]})
        identity_api._audit_tx(tx, actor, "NODE_STORAGE_UNBIND", "NODE_STORAGE_BINDING", binding_id, "ALLOW", reason)
    connection.execute_transaction_callback(work)
    return {"binding_id": binding_id, "status": "REMOVED"}


def list_endpoints(actor: str) -> list[Dict[str, Any]]:
    _require_admin(actor)
    return _rows(connection.execute_query("SELECT ENDPOINT_ID,ENDPOINT_KEY,DATABASE_DIALECT,HOST_REFERENCE,PORT,TLS_REQUIRED,STATUS,CREATED_AT FROM CX_EXTERNAL_DB_ENDPOINTS ORDER BY ENDPOINT_KEY"))


def discover_agent_endpoint(actor: str) -> Dict[str, Any]:
    """Return only scoped connection metadata for an authenticated Agent."""
    if not actor:
        raise PermissionError("authenticated Agent is required")
    now = time.monotonic()
    with _DISCOVERY_LOCK:
        recent = [stamp for stamp in _DISCOVERY_WINDOW.get(actor, []) if now - stamp < 60]
        if len(recent) >= 30:
            raise PermissionError("endpoint discovery rate limit exceeded")
        recent.append(now)
        _DISCOVERY_WINDOW[actor] = recent
    endpoint = None
    grants = connection.execute_query(
        "SELECT GRANT_ID,SECURITY_DOMAIN_ID,POLICY_SNAPSHOT FROM CX_ENROLLMENT_GRANTS "
        "WHERE AGENT_ID=:actor AND STATUS='ACTIVE' AND EXPIRES_AT>CURRENT_TIMESTAMP",
        {"actor": actor})
    for grant in grants:
        grant_row = _row(grant) or {}
        snapshot = grant_row.get("policy_snapshot")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except (TypeError, ValueError):
                snapshot = {}
        endpoint_id = str((snapshot or {}).get("database_endpoint_id") or "")
        if endpoint_id:
            endpoint = _row(connection.execute_query_one(
                "SELECT ENDPOINT_ID,ENDPOINT_KEY,DATABASE_DIALECT,HOST_REFERENCE,PORT,TLS_REQUIRED "
                "FROM CX_EXTERNAL_DB_ENDPOINTS WHERE ENDPOINT_ID=:id AND STATUS='ACTIVE'",
                {"id": endpoint_id}))
            if endpoint:
                break
    source = "EXTERNAL_PROFILE"
    if endpoint:
        result = {"source": source, "endpoint_id": endpoint.get("endpoint_id"), "endpoint_key": endpoint.get("endpoint_key"), "database_dialect": endpoint.get("database_dialect"), "host": endpoint.get("host_reference"), "port": endpoint.get("port"), "tls_required": str(endpoint.get("tls_required") or "Y").upper() == "Y"}
    else:
        from .config import get_config
        db = get_config().database
        source = "INITIALIZATION_FALLBACK"
        result = {"source": source, "database_dialect": str(getattr(connection, "DATABASE_DIALECT", "unknown")), "host": str(getattr(db, "host", "") or ""), "port": int(getattr(db, "port", 0) or 0), "dbname": str(getattr(db, "dbname", "") or ""), "tls_required": True}
    connection.execute_transaction_callback(lambda tx: identity_api._audit_tx(tx, actor, "AGENT_DATABASE_ENDPOINT_DISCOVERY", "DB_ENDPOINT", str(result.get("endpoint_id") or source), "ALLOW", "scoped endpoint metadata was requested"))
    return result


def register_endpoint(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require_admin(actor)
    if not body.get("endpoint_key") or not body.get("host_reference") or len(str(body.get("reason") or "").strip()) < 3:
        raise AgentPoolError("endpoint key, host reference, and reason are required")
    grant_id = str(body.get("registration_grant_id") or "").strip()
    if grant_id:
        grant = _row(connection.execute_query_one(
            "SELECT GRANT_ID,SECURITY_DOMAIN_ID,POLICY_SNAPSHOT,STATUS,EXPIRES_AT FROM CX_ENROLLMENT_GRANTS WHERE GRANT_ID=:id",
            {"id": grant_id}))
        if not grant or str(grant.get("status") or "").upper() != "ACTIVE":
            raise AgentPoolError("registration grant is unavailable")
        if body.get("security_domain_id") and str(body.get("security_domain_id")) != str(grant.get("security_domain_id")):
            raise AgentPoolError("endpoint Security Domain does not match its registration grant")
    endpoint_id = _id("ENDPOINT")
    def work(tx: Any) -> Dict[str, Any]:
        tx.execute("INSERT INTO CX_EXTERNAL_DB_ENDPOINTS(ENDPOINT_ID,ENDPOINT_KEY,DATABASE_DIALECT,HOST_REFERENCE,PORT,TLS_REQUIRED,STATUS,CREATED_BY,REASON) VALUES (:id,:key,:dialect,:host,:port,:tls,'ACTIVE',:actor,:reason)", {"id": endpoint_id, "key": str(body["endpoint_key"])[:128], "dialect": str(body.get("database_dialect") or getattr(connection, "DATABASE_DIALECT", "unknown"))[:32], "host": str(body["host_reference"])[:256], "port": int(body.get("port") or 0), "tls": "Y" if body.get("tls_required", True) else "N", "actor": actor, "reason": str(body["reason"])[:2000]})
        if grant_id:
            snapshot = grant.get("policy_snapshot") if grant else {}
            if isinstance(snapshot, str):
                try:
                    snapshot = json.loads(snapshot)
                except (TypeError, ValueError):
                    snapshot = {}
            snapshot = dict(snapshot or {})
            snapshot["database_endpoint_id"] = endpoint_id
            snapshot["database_endpoint_security_domain"] = str(grant.get("security_domain_id") or "DEFAULT")
            tx.execute("UPDATE CX_ENROLLMENT_GRANTS SET POLICY_SNAPSHOT=:snapshot WHERE GRANT_ID=:grant", {"snapshot": _json(snapshot), "grant": grant_id})
        identity_api._audit_tx(tx, actor, "EXTERNAL_DB_ENDPOINT_REGISTER", "DB_ENDPOINT", endpoint_id, "ALLOW", str(body["reason"]))
        return {"endpoint_id": endpoint_id, "status": "ACTIVE", "registration_grant_id": grant_id or None}
    return connection.execute_transaction_callback(work)


def list_enhancements(actor: str) -> Dict[str, Any]:
    _require_admin(actor)
    templates = _rows(connection.execute_query("SELECT TEMPLATE_ID,TEMPLATE_KEY,DISPLAY_NAME,TEMPLATE_KIND,STATUS,MANAGED FROM CX_AGENT_TEMPLATES ORDER BY TEMPLATE_KEY"))
    return {"items": templates, "count": len(templates)}
