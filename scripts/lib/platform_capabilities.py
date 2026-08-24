"""Database-authoritative platform capability switches for v4.3.5."""

from __future__ import annotations

import secrets
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api


class CapabilityError(ValueError):
    """Safe capability configuration error."""


class CapabilityConflict(CapabilityError):
    """The requested state conflicts with a newer state or dependency."""


class CapabilityServiceUnavailable(RuntimeError):
    """The authoritative capability registry cannot be read."""


REGISTRY: Dict[str, Dict[str, Any]] = {
    "identity": {"zh": "身份认证", "en": "Identity", "mandatory": True, "page": ""},
    "authorization": {"zh": "权限控制", "en": "Authorization", "mandatory": True, "page": ""},
    "security": {"zh": "安全控制", "en": "Security controls", "mandatory": True, "page": ""},
    "audit_write": {"zh": "审计写入", "en": "Audit writing", "mandatory": True, "page": ""},
    "agents": {"zh": "智能体", "en": "Agents", "mandatory": True, "page": "agents"},
    "users": {"zh": "用户管理", "en": "User management", "mandatory": True, "page": "users"},
    "platform_config": {"zh": "功能配置", "en": "Capability configuration", "mandatory": True, "page": "platform"},
    "deployment_governance": {"zh": "部署与模型", "en": "Deployment & models", "mandatory": True, "page": "deployment"},
    "embedding_governance": {"zh": "向量契约治理", "en": "Embedding Contract governance", "mandatory": True, "page": ""},
    "embedding_managed_worker": {"zh": "平台向量工作器", "en": "Platform Embedding worker", "mandatory": False, "page": ""},
    "agent_provisioning": {"zh": "业务智能体配置", "en": "Business Agent provisioning", "mandatory": False, "page": "native-agents"},
    "portal": {"zh": "门户", "en": "Portal", "mandatory": False, "page": ""},
    "monitor": {"zh": "监控", "en": "Monitor", "mandatory": False, "page": "monitor"},
    "wallboard": {"zh": "管理大屏", "en": "Executive wallboard", "mandatory": False, "page": "wallboard"},
    "model_finance": {"zh": "模型财务治理", "en": "Model financial governance", "mandatory": False, "page": ""},
    "external_model_evidence": {"zh": "外部模型证据", "en": "External model evidence", "mandatory": False, "page": ""},
    "tasks": {"zh": "任务", "en": "Tasks", "mandatory": False, "page": "tasks"},
    "workspaces": {"zh": "工作区", "en": "Workspaces", "mandatory": False, "page": "workspaces"},
    "knowledge": {"zh": "知识", "en": "Knowledge", "mandatory": False, "page": "knowledge"},
    "memory": {"zh": "记忆", "en": "Memory", "mandatory": False, "page": "memory"},
    "skills": {"zh": "技能", "en": "Skills", "mandatory": False, "page": "skills"},
    "specs": {"zh": "规格", "en": "Specs", "mandatory": False, "page": "specs"},
    "branches": {"zh": "分支", "en": "Branches", "mandatory": False, "page": "branches"},
    "collaboration": {"zh": "协作", "en": "Collaboration", "mandatory": False, "page": "collab"},
    "loops": {"zh": "循环", "en": "Loops", "mandatory": False, "page": "loops"},
    "graph": {"zh": "图探索", "en": "Graph", "mandatory": False, "page": "graph"},
    "channels": {"zh": "频道", "en": "Channels", "mandatory": False, "page": "channels"},
    "barriers": {"zh": "协作关卡", "en": "Collaboration gates", "mandatory": False, "page": "barriers"},
    "approvals": {"zh": "审批", "en": "Approvals", "mandatory": False, "page": "approvals", "edition": "approvals"},
    "compliance": {"zh": "合规", "en": "Compliance", "mandatory": False, "page": "compliance", "edition": "compliance"},
    "audit_view": {"zh": "审计查看", "en": "Audit view", "mandatory": False, "page": "audit", "edition": "audit"},
    "organization": {"zh": "组织架构", "en": "Organization", "mandatory": False, "page": "organization"},
    "security_domains": {"zh": "安全域", "en": "Security Domains", "mandatory": True, "page": "security-domains"},
    "admin_channel_ha": {"zh": "平台管理频道与高可用", "en": "Platform Administration and HA", "mandatory": True, "page": "platform"},
    "controlled_upgrade": {"zh": "受控升级", "en": "Controlled upgrade", "mandatory": True, "page": "platform"},
    "agent_containment": {"zh": "智能体阻断", "en": "Agent containment", "mandatory": True, "page": "platform"},
    "session_policy": {"zh": "会话策略", "en": "Session policy", "mandatory": True, "page": "platform"},
}

DEPENDENCIES = {
    "deployment_governance": ("audit_write",),
    "model_finance": ("audit_write",),
    "external_model_evidence": ("audit_write",),
    "embedding_governance": ("agents", "audit_write"),
    "embedding_managed_worker": ("embedding_governance",),
    "agent_provisioning": ("agents", "audit_write"),
    "branches": ("tasks", "workspaces"),
    "collaboration": ("agents",),
    "loops": ("tasks",),
    "graph": ("tasks",),
    "channels": ("agents",),
    "barriers": ("channels",),
    "approvals": ("audit_write",),
    "compliance": ("agents", "audit_write"),
    "audit_view": ("audit_write",),
    "organization": ("users", "agents"),
    "security_domains": ("identity", "authorization", "audit_write", "channels"),
    "admin_channel_ha": ("agents", "audit_write"),
    "controlled_upgrade": ("admin_channel_ha", "audit_write"),
    "agent_containment": ("admin_channel_ha", "audit_write"),
    "session_policy": ("identity", "audit_write"),
}


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _edition_available(key: str) -> bool:
    required = str(REGISTRY.get(key, {}).get("edition") or "")
    if not required:
        return True
    try:
        from . import edition_features
        return bool(edition_features.has_feature(required))
    except (ImportError, AttributeError):
        return True


def _state_row(key: str) -> Dict[str, Any]:
    if key not in REGISTRY:
        raise CapabilityError("Unknown platform capability")
    try:
        row = _row(connection.execute_query_one(
            "SELECT CAPABILITY_KEY,ENABLED,MANDATORY,VERSION,UPDATED_BY,UPDATE_REASON,UPDATED_AT "
            "FROM CX_PLATFORM_CAPABILITIES WHERE CAPABILITY_KEY=:key",
            {"key": key},
        ))
    except Exception as exc:
        raise CapabilityServiceUnavailable("Platform capability registry is unavailable") from exc
    if not row:
        raise CapabilityServiceUnavailable("Platform capability registry is incomplete")
    return row


def is_enabled(key: str) -> bool:
    row = _state_row(key)
    return bool(_edition_available(key) and str(row.get("enabled") or "N").upper() == "Y")


def page_states() -> Dict[str, bool]:
    try:
        rows = _rows(connection.execute_query(
            "SELECT CAPABILITY_KEY,ENABLED FROM CX_PLATFORM_CAPABILITIES"
        ))
    except Exception as exc:
        raise CapabilityServiceUnavailable("Platform capability registry is unavailable") from exc
    configured = {
        str(row.get("capability_key") or ""): str(row.get("enabled") or "N").upper() == "Y"
        for row in rows
    }
    if any(key not in configured for key in REGISTRY):
        raise CapabilityServiceUnavailable("Platform capability registry is incomplete")
    return {
        str(meta["page"]): configured[key] and _edition_available(key)
        for key, meta in REGISTRY.items() if meta.get("page")
    }


def list_capabilities(limit: int = 100) -> Dict[str, Any]:
    try:
        states = _rows(connection.execute_query(
            "SELECT CAPABILITY_KEY,ENABLED,MANDATORY,VERSION,UPDATED_BY,UPDATE_REASON,UPDATED_AT "
            "FROM CX_PLATFORM_CAPABILITIES ORDER BY CAPABILITY_KEY"
        ))
        dependencies = _rows(connection.execute_query(
            "SELECT CAPABILITY_KEY,DEPENDS_ON_KEY FROM CX_PLATFORM_CAPABILITY_DEPENDENCIES "
            "ORDER BY CAPABILITY_KEY,DEPENDS_ON_KEY"
        ))
        suffix = " LIMIT :limit" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"} else " FETCH FIRST :limit ROWS ONLY"
        history = _rows(connection.execute_query(
            "SELECT HISTORY_ID,CAPABILITY_KEY,FROM_ENABLED,TO_ENABLED,RESULT_VERSION,CHANGED_BY,REASON,CREATED_AT "
            "FROM CX_PLATFORM_CAPABILITY_HISTORY ORDER BY CREATED_AT DESC" + suffix,
            {"limit": max(1, min(int(limit), 500))},
        ))
    except Exception as exc:
        raise CapabilityServiceUnavailable("Platform capability registry is unavailable") from exc
    by_key = {str(item.get("capability_key") or ""): item for item in states}
    dep_map: Dict[str, List[str]] = {}
    for item in dependencies:
        dep_map.setdefault(str(item.get("capability_key") or ""), []).append(str(item.get("depends_on_key") or ""))
    items = []
    for key, meta in REGISTRY.items():
        state = by_key.get(key)
        if not state:
            raise CapabilityServiceUnavailable("Platform capability registry is incomplete")
        configured = str(state.get("enabled") or "N").upper() == "Y"
        available = _edition_available(key)
        items.append({
            **state,
            "display_name_zh": meta["zh"],
            "display_name_en": meta["en"],
            "page": meta.get("page") or None,
            "mandatory": bool(meta.get("mandatory")) or str(state.get("mandatory") or "N").upper() == "Y",
            "configured_enabled": configured,
            "edition_available": available,
            "effective_enabled": configured and available,
            "dependencies": dep_map.get(key, []),
        })
    return {"items": items, "history": history, "schema_version": "4.4.3"}


def set_enabled(actor: str, key: str, enabled: bool, reason: str, expected_version: int) -> Dict[str, Any]:
    reason = str(reason or "").strip()
    if key not in REGISTRY:
        raise CapabilityError("Unknown platform capability")
    if len(reason) < 3 or len(reason) > 2000:
        raise CapabilityError("A reason between 3 and 2000 characters is required")
    if not _edition_available(key):
        raise CapabilityError("Capability is unavailable in this edition")
    if REGISTRY[key].get("mandatory") and not enabled:
        raise CapabilityError("Mandatory platform capabilities cannot be disabled")

    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT CAPABILITY_KEY,ENABLED,MANDATORY,VERSION FROM CX_PLATFORM_CAPABILITIES "
            "WHERE CAPABILITY_KEY=:key FOR UPDATE", {"key": key},
        ))
        if not current:
            raise CapabilityServiceUnavailable("Platform capability registry is incomplete")
        version = int(current.get("version") or 0)
        if version != int(expected_version):
            raise CapabilityConflict("Capability changed concurrently")
        before = str(current.get("enabled") or "N").upper() == "Y"
        if before == bool(enabled):
            return current
        if enabled:
            for dependency in DEPENDENCIES.get(key, ()):
                dep = _row(tx.query_one(
                    "SELECT ENABLED FROM CX_PLATFORM_CAPABILITIES WHERE CAPABILITY_KEY=:key",
                    {"key": dependency},
                ))
                if not dep or str(dep.get("enabled") or "N").upper() != "Y" or not _edition_available(dependency):
                    raise CapabilityConflict("Required capabilities are disabled or unavailable: " + dependency)
        else:
            blockers = []
            for dependent, required in DEPENDENCIES.items():
                if key not in required or not _edition_available(dependent):
                    continue
                row = _row(tx.query_one(
                    "SELECT ENABLED FROM CX_PLATFORM_CAPABILITIES WHERE CAPABILITY_KEY=:key",
                    {"key": dependent},
                ))
                if row and str(row.get("enabled") or "N").upper() == "Y":
                    blockers.append(dependent)
            if blockers:
                raise CapabilityConflict("Enabled capabilities depend on this capability: " + ", ".join(sorted(blockers)))
        changed = tx.execute(
            "UPDATE CX_PLATFORM_CAPABILITIES SET ENABLED=:enabled,VERSION=VERSION+1,UPDATED_BY=:actor,"
            "UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE CAPABILITY_KEY=:key AND VERSION=:version",
            {"enabled": "Y" if enabled else "N", "actor": actor, "reason": reason, "key": key, "version": version},
        )
        if changed != 1:
            raise CapabilityConflict("Capability changed concurrently")
        resulting = version + 1
        history_id = "PCH_" + secrets.token_hex(20)
        tx.execute(
            "INSERT INTO CX_PLATFORM_CAPABILITY_HISTORY(HISTORY_ID,CAPABILITY_KEY,FROM_ENABLED,TO_ENABLED,"
            "RESULT_VERSION,CHANGED_BY,REASON) VALUES (:history_id,:key,:before,:after,:version,:actor,:reason)",
            {"history_id": history_id, "key": key, "before": "Y" if before else "N", "after": "Y" if enabled else "N", "version": resulting, "actor": actor, "reason": reason},
        )
        identity_api._audit_tx(tx, actor, "PLATFORM_CAPABILITY_UPDATE", "PLATFORM_CAPABILITY", key, "ALLOW", reason)
        return {"capability_key": key, "enabled": "Y" if enabled else "N", "version": resulting}

    connection.execute_transaction_callback(work)
    return next(item for item in list_capabilities(limit=20)["items"] if item["capability_key"] == key)
