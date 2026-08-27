"""Platform-native Agent provisioning and runtime contracts for v4.3.6.

This module owns the database-authoritative control plane for built-in and
platform-created Agents.  It intentionally does not implement customer
vendor connectors.  Those integrations use the DeploymentTarget contract and
are kept outside the product's trust boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from . import connection, identity_api, cursor_pagination


PLATFORM_ADMIN_AGENT_ID = "SYSTEM_PLATFORM_ADMIN_AGENT"
COMPLIANCE_ADMIN_AGENT_ID = "SYSTEM_COMPLIANCE_ADMIN_AGENT"
BOOTSTRAP_VERSION = "4.3.6"
MANAGEMENT_KNOWLEDGE_VERSION = 2
EXTERNAL_REGISTRATION_KEY = "external_agent_registration"
AGENT_SOURCES = frozenset({"PLATFORM_BUILTIN", "PLATFORM_CREATED", "EXTERNAL_SKILL"})
AGENT_STATES = frozenset({
    "INITIALIZED", "ACTIVATION_PENDING", "ACTIVE", "DEGRADED", "RESTRICTED",
    "QUARANTINED", "DISABLED", "RETIRED", "REQUESTED", "APPROVAL_PENDING",
    "PROVISIONING", "REJECTED", "FAILED",
})
REGISTRATION_STATES = frozenset({"DISABLED", "APPROVAL_ONLY", "ENABLED"})
ISOLATION_LEVELS = frozenset({
    "STANDARD", "DOMAIN_ISOLATED", "DEDICATED_CONTAINER", "DEDICATED_RUNTIME",
    "EXTERNAL_MANAGED",
})


class NativeAgentError(ValueError):
    """Safe native Agent contract error."""


class NativeAgentConflict(NativeAgentError):
    """Optimistic concurrency or lifecycle conflict."""


class LLMProfileInUse(NativeAgentConflict):
    """An LLM profile still has governed references that block retirement."""

    def __init__(self, blockers: Iterable[str]):
        self.blockers = tuple(str(item) for item in blockers)
        super().__init__("LLM_PROFILE_IN_USE:" + ",".join(self.blockers))


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


def _text(value: Any, limit: int = 256) -> str:
    return str(value or "").strip()[:limit]


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(k).lower(): v for k, v in dict(row).items()} if row else None


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True,
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parse(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _llm_model_matches(expected: Any, observed: Any) -> bool:
    """Accept provider namespaces and bounded numeric alias resolutions."""
    expected_name = _text(expected, 256).lower()
    observed_name = _text(observed, 256).lower()
    if not expected_name or not observed_name:
        return False
    expected_base = expected_name.rsplit("/", 1)[-1]
    observed_base = observed_name.rsplit("/", 1)[-1]
    if observed_name == expected_name or observed_base == expected_base:
        return True
    prefix = expected_base + "-"
    if not observed_base.startswith(prefix):
        return False
    version = observed_base[len(prefix):]
    return re.fullmatch(r"(?:\d{3,8}|\d{4}-\d{2}-\d{2})", version) is not None


def _enterprise() -> bool:
    try:
        from . import edition_features
        return bool(edition_features.has_feature("compliance"))
    except (ImportError, AttributeError):
        return True


def _limit(limit: int) -> tuple[str, Dict[str, Any]]:
    amount = max(1, min(int(limit), 500))
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"}:
        return " LIMIT :limit", {"limit": amount}
    return " FETCH FIRST :limit ROWS ONLY", {"limit": amount}


def _lease_deadline_sql() -> str:
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"pg", "postgresql"}:
        return "CURRENT_TIMESTAMP + INTERVAL '5 minutes'"
    return "CURRENT_TIMESTAMP + INTERVAL '5' MINUTE"


def _lease_started_sql() -> str:
    # YashanDB 23.5 rejects COALESCE between its timestamp expression and a
    # nullable timestamp column in this UPDATE shape, while NVL preserves the
    # same semantics.  Keep the workaround local to the adapter dialect.
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"yashandb", "yashan"}:
        return "NVL(STARTED_AT,CURRENT_TIMESTAMP)"
    return "COALESCE(STARTED_AT,CURRENT_TIMESTAMP)"


def _audit(tx: Any, actor: str, action: str, resource_type: str,
           resource_id: str, outcome: str, reason: str) -> None:
    identity_api._audit_tx(tx, actor, action, resource_type, resource_id,
                           outcome, _text(reason, 2000))


BUILTIN_TEMPLATES = (
    ("platform-admin", "Platform Admin Agent", "PLATFORM_ADMIN", {
        "locked_fields": ["database", "secrets", "security", "approval"],
        "tools": ["agent_inventory", "runtime_status", "platform_notice", "audit_summary"],
        "scopes": ["PLATFORM_METADATA"], "isolation_level": "DOMAIN_ISOLATED",
        "approval_required": True,
    }),
    ("compliance-admin", "Compliance Admin Agent", "COMPLIANCE_ADMIN", {
        "locked_fields": ["database", "secrets", "security", "audit", "approval"],
        "tools": ["posture_summary", "finding_explain", "remediation_draft", "compliance_notice"],
        "scopes": ["COMPLIANCE_PROJECTION"], "isolation_level": "DEDICATED_CONTAINER",
        "approval_required": True,
    }),
    ("general-restricted", "General Restricted Agent", "BUSINESS", {
        "locked_fields": ["database", "secrets", "export"],
        "tools": ["approved_skill_only"], "scopes": ["ASSIGNED"],
        "isolation_level": "DOMAIN_ISOLATED", "approval_required": True,
    }),
    ("code-development", "Code Development Agent", "BUSINESS", {
        "locked_fields": ["database", "secrets", "commands"],
        "tools": ["approved_workspace", "review_required"], "scopes": ["WORKSPACE"],
        "isolation_level": "DEDICATED_CONTAINER", "approval_required": True,
    }),
    ("production-operations", "Production Operations Agent", "BUSINESS", {
        "locked_fields": ["database", "approval", "commands", "network"],
        "tools": ["allowlisted_command", "change_ticket_required"],
        "scopes": ["APPROVED_PRODUCTION_SCOPE"], "isolation_level": "DEDICATED_RUNTIME",
        "approval_required": True,
    }),
)

BUILTIN_MANIFESTS = (
    ("platform-admin-tools", "TOOL", {"tools": ["agent_inventory", "runtime_status", "platform_notice", "audit_summary"]}),
    ("compliance-admin-tools", "TOOL", {"tools": ["posture_summary", "finding_explain", "remediation_draft", "compliance_notice"]}),
    ("restricted-agent-skills", "SKILL", {"skills": ["approved_skill_only"], "requires_gateway": True}),
    ("compliance-admin-knowledge", "MANAGEMENT_KNOWLEDGE", {
        "knowledge_version": "1",
        "audience": "COMPLIANCE_ADMIN_AGENT_ONLY",
        "scope": "compliance_control_plane",
        "governance_workflow": {
            "proposal_boundary_zh": "合规控制器只能创建整改案件和平台管理频道中的治理操作卡，不能自行批准或执行平台变更。",
            "proposal_boundary_en": "The Compliance Controller may create remediation cases and governed Action Cards in the Platform Administration Channel, but cannot approve or execute platform changes itself.",
            "action_type": "PLATFORM_COMPLIANCE_REMEDIATION",
            "required_human_approval_zh": "所有平台变更必须由授权人类管理员最终批准。",
            "required_human_approval_en": "Every platform change requires final approval by an authorized human administrator.",
        },
        "knowledge_isolation": {
            "audience": "COMPLIANCE_ADMIN",
            "scope_type": "COMPLIANCE_AGENT",
            "classification": "RESTRICTED",
        },
    }),
    ("platform-admin-knowledge", "MANAGEMENT_KNOWLEDGE", {
        "knowledge_version": "2",
        "audience": "PLATFORM_MANAGEMENT_AGENTS_ONLY",
        "scope": "database_control_plane",
        "template_workflow": {
            "current_capability": "BUILTIN_SEEDS_AND_BUSINESS_REQUESTS",
            "template_editing_page": None,
            "template_editing_api": None,
            "seed_location_zh": "Dashboard > 智能体 > 平台原生智能体生成 > 平台内置管理智能体",
            "seed_location_en": "Dashboard > Agents > Platform-native Agent provisioning > Built-in management Agents",
            "business_request_location_zh": "Dashboard > 智能体 > 平台原生智能体生成 > 业务智能体申请",
            "business_request_location_en": "Dashboard > Agents > Platform-native Agent provisioning > Business Agent request",
            "approval_location_zh": "Dashboard > 智能体 > 平台原生智能体生成 > 申请与审批",
            "approval_location_en": "Dashboard > Agents > Platform-native Agent provisioning > Requests and approvals",
            "template_meaning_zh": "内置 Agent 模板是申请平台业务 Agent 时的受管选项。不同模板代表不同的能力倾向、隔离要求和安全基线；模板本身不授予数据库、网络、Skill 或 Tool 权限。",
            "template_meaning_en": "A built-in Agent template is a managed option selected when requesting a platform Business Agent. Templates express capability tendencies, isolation requirements, and security baselines; they do not grant database, network, Skill, or Tool authority.",
            "compliance_distinction_zh": "合规控制模板是治理约束配置，不是 Agent 运行模板。",
            "compliance_distinction_en": "Compliance control templates are governance profiles, not Agent runtime templates.",
        },
        "business_template_options": [
            {"key": "general-restricted", "zh": "通用受限：面向一般工作，仅允许已审批 Skill，采用安全域隔离。", "en": "General restricted: general work with approved Skills only and Security Domain isolation."},
            {"key": "code-development", "zh": "代码开发：面向受控工作区和代码任务，要求独立容器与复核。", "en": "Code development: controlled workspace and coding work with dedicated-container isolation and review."},
            {"key": "production-operations", "zh": "生产运维：面向获批生产范围，仅允许白名单命令，要求变更单、审批和独立运行时。", "en": "Production operations: approved production scope with allowlisted commands, change ticket, approval, and dedicated runtime."},
        ],
        "required_request_controls_en": [
            "agent_name", "template_key", "owner_principal_id", "provider_profile_id",
            "deployment_target_id", "isolation_level", "classification", "purpose", "reason",
        ],
        "required_request_controls_zh": [
            "智能体名称", "受管模板", "负责人账户", "LLM 配置", "部署目标",
            "隔离级别", "数据分类", "业务目的", "申请原因",
        ],
        "security_controls_en": [
            "approved Skills and Tools only",
            "database access through scoped identity and gateway policy",
            "network egress allowlist or isolation",
            "data classification ceiling",
            "separated approval; applicant cannot approve their own request",
            "audit and retention evidence",
            "LLM and Embedding compatibility checks before activation",
        ],
        "security_controls_zh": [
            "只能使用已审批的 Skill 与 Tool",
            "数据库访问由独立身份、范围授权和网关策略控制",
            "网络出口必须使用白名单或隔离策略",
            "数据分类不得超过模板与申请批准的上限",
            "申请人与审批人职责分离，申请人不能审批自己的申请",
            "保留操作审计与留存证据",
            "激活前验证 LLM、Embedding、部署目标和运行时兼容性",
        ],
        "request_lifecycle_en": [
            "TEMPLATE_SELECTED", "APPROVAL_PENDING", "APPROVED", "PROVISIONING", "ACTIVATION_PENDING", "ACTIVE",
        ],
        "request_lifecycle_zh": ["选择模板", "等待审批", "已批准", "部署中", "等待激活", "运行中"],
        "immutability_en": "Published built-in template versions are immutable. A future template-authoring path must create a new reviewed version with digest, evidence, approval, and rollback target. Protected platform-admin and compliance-admin templates are not selectable for Business Agent requests and cannot be deleted or overwritten.",
        "immutability_zh": "已发布的内置模板版本不可覆盖。未来的模板编制能力必须创建新版本，并具备摘要、证据、审批和回滚目标。受保护的 platform-admin 与 compliance-admin 模板不能用于业务 Agent 申请，也不能删除或直接覆盖。",
        "external_registration_en": "External Skill-first registration is a separate enrollment path and does not create or modify a platform Agent template.",
        "external_registration_zh": "外部 Skill-first 注册是独立接入路径，不会创建或修改平台 Agent 模板。",
        "missing_capability_answer_en": "There is currently no direct Agent-template create, edit, or publish page or API. Do not claim that the Compliance control-template draft page edits an Agent template.",
        "missing_capability_answer_zh": "当前没有直接创建、编辑或发布 Agent 模板的页面或 API。不得把“合规控制模板草稿”解释为 Agent 模板编辑功能。",
    }),
)


def _ensure_template(tx: Any, key: str, display_name: str, kind: str,
                     content: Dict[str, Any]) -> bool:
    existing = _row(tx.query_one(
        "SELECT TEMPLATE_ID,CONTENT_DIGEST FROM CX_AGENT_TEMPLATES WHERE TEMPLATE_KEY=:key FOR UPDATE",
        {"key": key},
    ))
    digest = _digest(content)
    if existing:
        return False
    tx.execute(
        "INSERT INTO CX_AGENT_TEMPLATES(TEMPLATE_ID,TEMPLATE_KEY,DISPLAY_NAME,TEMPLATE_KIND,CONTENT_JSON,"
        "CONTENT_DIGEST,LOCKED_FIELDS_JSON,STATUS,MANAGED,CREATED_BY) VALUES "
        "(:id,:key,:display,:kind,:content,:digest,:locked,'PUBLISHED','Y','SYSTEM_BOOTSTRAP')",
        {"id": "AT_SEED_" + key.replace("-", "_").upper(), "key": key,
         "display": display_name, "kind": kind, "content": _json(content),
         "digest": digest, "locked": _json(content.get("locked_fields", []))},
    )
    return True


def _ensure_target(tx: Any, target_key: str = "local-managed") -> str:
    existing = _row(tx.query_one(
        "SELECT TARGET_ID FROM CX_DEPLOYMENT_TARGETS WHERE TARGET_KEY=:key FOR UPDATE",
        {"key": target_key},
    ))
    if existing:
        return str(existing.get("target_id"))
    target_id = "DT_LOCAL_MANAGED"
    tx.execute(
        "INSERT INTO CX_DEPLOYMENT_TARGETS(TARGET_ID,TARGET_KEY,TARGET_TYPE,CONFIG_JSON,STATUS,MANAGED,CREATED_BY) "
        "VALUES (:id,:key,'LOCAL_MANAGED',:config,'ACTIVE','Y','SYSTEM_BOOTSTRAP')",
        {"id": target_id, "key": target_key, "config": _json({"reference": True})},
    )
    return target_id


def _ensure_manifest(tx: Any, key: str, kind: str, content: Dict[str, Any]) -> bool:
    version = MANAGEMENT_KNOWLEDGE_VERSION if key == "platform-admin-knowledge" else 1
    existing = _row(tx.query_one(
        "SELECT MANIFEST_ID FROM CX_NATIVE_MANIFESTS WHERE MANIFEST_KEY=:key AND VERSION=:version FOR UPDATE",
        {"key": key, "version": version},
    ))
    if existing:
        return False
    digest = _digest(content)
    tx.execute(
        "INSERT INTO CX_NATIVE_MANIFESTS(MANIFEST_ID,MANIFEST_KEY,VERSION,MANIFEST_KIND,CONTENT_JSON,"
        "CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,MANAGED,CREATED_BY) VALUES "
        "(:id,:key,:version,:kind,:content,:digest,:signature,'VERIFIED_BUILTIN','PUBLISHED','Y','SYSTEM_BOOTSTRAP')",
        {"id": "AM_SEED_" + key.replace("-", "_").upper() + "_V" + str(version), "key": key,
         "version": version, "kind": kind, "content": _json(content), "digest": digest,
         "signature": "BUILTIN-SHA256:" + digest},
    )
    return True


def _verify_management_knowledge(tx: Any) -> Dict[str, Any]:
    """Fail closed unless the deployment-owned knowledge seed is intact."""
    row = _row(tx.query_one(
        "SELECT MANIFEST_ID,MANIFEST_KIND,CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,"
        "SIGNATURE_STATUS,STATUS,MANAGED FROM CX_NATIVE_MANIFESTS "
        "WHERE MANIFEST_KEY='platform-admin-knowledge' AND VERSION=:version FOR UPDATE",
        {"version": MANAGEMENT_KNOWLEDGE_VERSION},
    ))
    if not row:
        raise NativeAgentError("platform management knowledge was not initialized")
    content = _parse(row.get("content_json"), {})
    digest = str(row.get("content_digest") or "")
    valid = (
        isinstance(content, dict)
        and str(row.get("manifest_kind") or "") == "MANAGEMENT_KNOWLEDGE"
        and str(row.get("signature_status") or "") == "VERIFIED_BUILTIN"
        and str(row.get("status") or "") == "PUBLISHED"
        and str(row.get("managed") or "") == "Y"
        and digest == _digest(content)
        and str(row.get("signature") or "") == "BUILTIN-SHA256:" + digest
    )
    if not valid:
        raise NativeAgentError("platform management knowledge verification failed")
    return {"manifest_id": str(row.get("manifest_id") or ""), "status": "VERIFIED", "digest": digest}


def _ensure_platform_knowledge(tx: Any) -> Dict[str, Any]:
    """Migrate the signed manifest into the scoped private-knowledge model."""
    source = _row(tx.query_one(
        "SELECT MANIFEST_ID,CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,MANAGED "
        "FROM CX_NATIVE_MANIFESTS WHERE MANIFEST_KEY='platform-admin-knowledge' "
        "AND VERSION=:version FOR UPDATE", {"version": MANAGEMENT_KNOWLEDGE_VERSION},
    ))
    if not source:
        raise NativeAgentError("management knowledge source is unavailable")
    content = _parse(source.get("content_json"), {})
    digest = str(source.get("content_digest") or "")
    if (
        not isinstance(content, dict)
        or digest != _digest(content)
        or str(source.get("signature_status") or "") != "VERIFIED_BUILTIN"
        or str(source.get("status") or "") != "PUBLISHED"
        or str(source.get("managed") or "") != "Y"
    ):
        raise NativeAgentError("management knowledge migration verification failed")

    knowledge_id = "PK_PLATFORM_ADMIN_KNOWLEDGE_V" + str(MANAGEMENT_KNOWLEDGE_VERSION)
    existing = _row(tx.query_one(
        "SELECT KNOWLEDGE_ID,CONTENT_DIGEST FROM CX_PLATFORM_KNOWLEDGE WHERE KNOWLEDGE_KEY=:key "
        "AND VERSION=:version FOR UPDATE", {"key": "platform-admin-knowledge", "version": MANAGEMENT_KNOWLEDGE_VERSION},
    ))
    if not existing:
        tx.execute(
            "INSERT INTO CX_PLATFORM_KNOWLEDGE(KNOWLEDGE_ID,KNOWLEDGE_KEY,VERSION,KNOWLEDGE_KIND,AUDIENCE,"
            "SCOPE_TYPE,CLASSIFICATION,CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,"
            "VALID_FROM,SOURCE_MANIFEST_ID,CREATED_BY) VALUES (:id,:key,:version,'MANAGEMENT_RUNBOOK',"
            "'MANAGEMENT_AGENTS','MANAGEMENT_AGENT','RESTRICTED',:content,:digest,:signature,'VERIFIED_BUILTIN',"
            "'PUBLISHED',CURRENT_TIMESTAMP,:source,'SYSTEM_BOOTSTRAP')",
            {"id": knowledge_id, "key": "platform-admin-knowledge",
             "version": MANAGEMENT_KNOWLEDGE_VERSION, "content": _json(content), "digest": digest,
             "signature": "BUILTIN-SHA256:" + digest, "source": str(source.get("manifest_id") or "")},
        )
    elif str(existing.get("content_digest") or "") != digest:
        raise NativeAgentError("scoped management knowledge digest mismatch")
    return {"knowledge_id": knowledge_id, "status": "MIGRATED", "digest": digest}


def _ensure_compliance_knowledge(tx: Any) -> Dict[str, Any]:
    """Seed the Enterprise-only Compliance Admin private runbook."""
    if not _enterprise():
        return {"status": "UNAVAILABLE", "enterprise_only": True}
    row = _row(tx.query_one(
        "SELECT CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,MANAGED "
        "FROM CX_NATIVE_MANIFESTS WHERE MANIFEST_KEY='compliance-admin-knowledge' AND VERSION=1 FOR UPDATE",
        {},
    ))
    if not row:
        raise NativeAgentError("compliance management knowledge was not initialized")
    content = _parse(row.get("content_json"), {})
    digest = str(row.get("content_digest") or "")
    if (
        not isinstance(content, dict)
        or digest != _digest(content)
        or str(row.get("signature_status") or "") != "VERIFIED_BUILTIN"
        or str(row.get("status") or "") != "PUBLISHED"
        or str(row.get("managed") or "") != "Y"
    ):
        raise NativeAgentError("compliance management knowledge verification failed")
    knowledge_id = "PK_COMPLIANCE_ADMIN_KNOWLEDGE_V1"
    existing = _row(tx.query_one(
        "SELECT KNOWLEDGE_ID,CONTENT_DIGEST FROM CX_PLATFORM_KNOWLEDGE "
        "WHERE KNOWLEDGE_KEY='compliance-admin-knowledge' AND VERSION=1 FOR UPDATE", {},
    ))
    if not existing:
        tx.execute(
            "INSERT INTO CX_PLATFORM_KNOWLEDGE(KNOWLEDGE_ID,KNOWLEDGE_KEY,VERSION,KNOWLEDGE_KIND,AUDIENCE,"
            "SCOPE_TYPE,CLASSIFICATION,CONTENT_JSON,CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,"
            "VALID_FROM,SOURCE_MANIFEST_ID,CREATED_BY) VALUES "
            "(:id,'compliance-admin-knowledge',1,'COMPLIANCE_RUNBOOK','COMPLIANCE_ADMIN','COMPLIANCE_AGENT',"
            "'RESTRICTED',:content,:digest,:signature,'VERIFIED_BUILTIN','PUBLISHED',CURRENT_TIMESTAMP,:source,'SYSTEM_BOOTSTRAP')",
            {"id": knowledge_id, "content": _json(content), "digest": digest,
             "signature": "BUILTIN-SHA256:" + digest,
             "source": str(row.get("manifest_id") or "")},
        )
    elif str(existing.get("content_digest") or "") != digest:
        raise NativeAgentError("compliance knowledge digest mismatch")
    return {"knowledge_id": knowledge_id, "status": "MIGRATED", "digest": digest}


def _principal_display_name(agent_id: str) -> str:
    if agent_id == PLATFORM_ADMIN_AGENT_ID:
        return "Platform Admin Agent"
    if agent_id == COMPLIANCE_ADMIN_AGENT_ID:
        return "Compliance Admin Agent"
    return "Managed Agent"


def _ensure_principal(tx: Any, agent_id: str) -> None:
    existing = _row(tx.query_one(
        "SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id FOR UPDATE",
        {"id": agent_id},
    ))
    if not existing:
        tx.execute(
            "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID,PRINCIPAL_TYPE,DISPLAY_NAME,STATUS,PERMISSION_VERSION) "
            "VALUES (:id,'AGENT',:display_name,'ACTIVE',1)",
            {"id": agent_id, "display_name": _principal_display_name(agent_id)},
        )
    else:
        # Earlier bootstrap versions did not write a display name. Backfill
        # only blank names so operator-provided names always remain intact.
        tx.execute(
            "UPDATE CX_PRINCIPALS SET DISPLAY_NAME=:display_name,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE PRINCIPAL_ID=:id AND (DISPLAY_NAME IS NULL OR TRIM(DISPLAY_NAME)='')",
            {"id": agent_id, "display_name": _principal_display_name(agent_id)},
        )


def _ensure_native_agent(tx: Any, agent_id: str, kind: str, template_key: str,
                         target_id: str, owner_id: str = "") -> bool:
    # Keep the Principal display name correct even for an already-completed
    # bootstrap. This makes the operation genuinely repeatable across release
    # upgrades without altering an operator-supplied non-empty display name.
    _ensure_principal(tx, agent_id)
    existing = _row(tx.query_one(
        "SELECT AGENT_ID FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:id FOR UPDATE",
        {"id": agent_id},
    ))
    if existing:
        return False
    template = _row(tx.query_one(
        "SELECT TEMPLATE_ID FROM CX_AGENT_TEMPLATES WHERE TEMPLATE_KEY=:key AND STATUS='PUBLISHED'",
        {"key": template_key},
    ))
    if not template:
        raise NativeAgentError("native Agent template is unavailable")
    tx.execute(
        "INSERT INTO CX_NATIVE_AGENTS(AGENT_ID,SOURCE,AGENT_KIND,TEMPLATE_ID,OWNER_PRINCIPAL_ID,STATUS,"
        "ACTIVATION_STATE,DEPLOYMENT_TARGET_ID,SECURITY_DOMAIN_ID,IS_PROTECTED,CREATED_BY) VALUES "
        "(:agent,:source,:kind,:template,:owner,'INITIALIZED','ACTIVATION_PENDING',:target,'DEFAULT','Y','SYSTEM_BOOTSTRAP')",
        {"agent": agent_id, "source": "PLATFORM_BUILTIN", "kind": kind,
         "template": template["template_id"], "owner": owner_id or None,
         "target": target_id},
    )
    _audit(tx, "SYSTEM_BOOTSTRAP", "NATIVE_AGENT_BOOTSTRAP", "AGENT",
           agent_id, "ALLOW", "v4.3.6 idempotent platform bootstrap")
    return True


def bootstrap_native_agents() -> Dict[str, Any]:
    """Create platform-owned identities and templates without an LLM call."""
    def work(tx: Any) -> Dict[str, Any]:
        marker = _row(tx.query_one(
            "SELECT BOOTSTRAP_VERSION,STATUS FROM CX_NATIVE_BOOTSTRAP WHERE BOOTSTRAP_KEY='v4.3.6' FOR UPDATE",
            {},
        ))
        if marker and str(marker.get("status") or "") == "COMPLETED":
            # Completed deployments still receive non-destructive identity
            # repairs introduced by later releases, such as display names.
            _ensure_principal(tx, PLATFORM_ADMIN_AGENT_ID)
            if _enterprise():
                _ensure_principal(tx, COMPLIANCE_ADMIN_AGENT_ID)
            # Later releases may add immutable built-in knowledge without
            # rerunning the original bootstrap or changing published seeds.
            for key, kind, content in BUILTIN_MANIFESTS:
                if kind != "TOOL" or _enterprise() or key == "restricted-agent-skills":
                    _ensure_manifest(tx, key, kind, content)
            knowledge = _verify_management_knowledge(tx)
            scoped_knowledge = _ensure_platform_knowledge(tx)
            compliance_knowledge = _ensure_compliance_knowledge(tx)
            return {"status": "COMPLETED", "idempotent": True,
                    "agents": [PLATFORM_ADMIN_AGENT_ID] + ([COMPLIANCE_ADMIN_AGENT_ID] if _enterprise() else []),
                    "management_knowledge": knowledge, "scoped_knowledge": scoped_knowledge,
                    "compliance_knowledge": compliance_knowledge}
        if not marker:
            tx.execute(
                "INSERT INTO CX_NATIVE_BOOTSTRAP(BOOTSTRAP_KEY,BOOTSTRAP_VERSION,STATUS,STARTED_AT) "
                "VALUES ('v4.3.6','4.3.6','RUNNING',CURRENT_TIMESTAMP)", {},
            )
        for key, display, kind, content in BUILTIN_TEMPLATES:
            if kind != "COMPLIANCE_ADMIN" or _enterprise():
                _ensure_template(tx, key, display, kind, content)
        for key, kind, content in BUILTIN_MANIFESTS:
            if kind != "TOOL" or _enterprise() or key == "restricted-agent-skills":
                _ensure_manifest(tx, key, kind, content)
        knowledge = _verify_management_knowledge(tx)
        scoped_knowledge = _ensure_platform_knowledge(tx)
        compliance_knowledge = _ensure_compliance_knowledge(tx)
        target_id = _ensure_target(tx)
        created = []
        if _ensure_native_agent(tx, PLATFORM_ADMIN_AGENT_ID, "PLATFORM_ADMIN", "platform-admin", target_id):
            created.append(PLATFORM_ADMIN_AGENT_ID)
        if _enterprise() and _ensure_native_agent(
            tx, COMPLIANCE_ADMIN_AGENT_ID, "COMPLIANCE_ADMIN", "compliance-admin", target_id,
        ):
            created.append(COMPLIANCE_ADMIN_AGENT_ID)
        policy = _row(tx.query_one(
            "SELECT POLICY_KEY FROM CX_EXTERNAL_AGENT_POLICY WHERE POLICY_KEY=:key FOR UPDATE",
            {"key": EXTERNAL_REGISTRATION_KEY},
        ))
        if not policy:
            tx.execute(
                "INSERT INTO CX_EXTERNAL_AGENT_POLICY(POLICY_KEY,STATE,VERSION,UPDATED_BY,REASON) "
                "VALUES (:key,'ENABLED',1,'SYSTEM_BOOTSTRAP','preserve existing external Skill-first registration')",
                {"key": EXTERNAL_REGISTRATION_KEY},
            )
        tx.execute(
            "UPDATE CX_NATIVE_BOOTSTRAP SET STATUS='COMPLETED',COMPLETED_AT=CURRENT_TIMESTAMP "
            "WHERE BOOTSTRAP_KEY='v4.3.6'",
            {},
        )
        _audit(tx, "SYSTEM_BOOTSTRAP", "NATIVE_AGENT_BOOTSTRAP_COMPLETE", "PLATFORM",
               "v4.3.6", "ALLOW", "native Agent bootstrap completed")
        return {"status": "COMPLETED", "idempotent": not bool(created), "created": created,
                "management_knowledge": knowledge, "scoped_knowledge": scoped_knowledge,
                "compliance_knowledge": compliance_knowledge}
    try:
        result = connection.execute_transaction_callback(work)
        try:
            from . import platform_agent_pool
            result["platform_command_registry"] = platform_agent_pool.ensure_platform_command_registry()
            from . import isolation_inventory
            result["isolation_inventory"] = isolation_inventory.ensure_isolation_inventory()
        except Exception as exc:
            raise NativeAgentError("platform control-plane bootstrap failed") from exc
        return result
    except Exception as exc:
        raise NativeAgentError("native Agent bootstrap is unavailable") from exc


def activate_bootstrap_agents(actor: str, llm_profile_id: str) -> Dict[str, Any]:
    """Activate only platform-owned management Agents after trusted bootstrap.

    This is intentionally not exposed as a general API.  Normal business
    Agents still require a human approval and activation action.
    """
    if not str(actor).startswith("BOOTSTRAP_DEPLOYMENT_AGENT:") or not _text(llm_profile_id, 128):
        raise NativeAgentError("bootstrap Agent activation is restricted")
    def work(tx: Any) -> Dict[str, Any]:
        profile = _row(tx.query_one(
            "SELECT PROFILE_ID,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id FOR UPDATE",
            {"id": llm_profile_id},
        ))
        if not profile or str(profile.get("status") or "").upper() != "ACTIVE":
            raise NativeAgentError("LLM Provider Profile is unavailable")
        agent_ids = [PLATFORM_ADMIN_AGENT_ID]
        if _enterprise():
            agent_ids.append(COMPLIANCE_ADMIN_AGENT_ID)
        activated = []
        for agent_id in agent_ids:
            changed = tx.execute(
                "UPDATE CX_NATIVE_AGENTS SET STATUS='ACTIVE',ACTIVATION_STATE='ACTIVE',LLM_PROFILE_ID=:profile,"
                "UPDATED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent AND SOURCE='PLATFORM_BUILTIN' AND STATUS IN ('INITIALIZED','ACTIVATION_PENDING','DEGRADED')",
                {"profile": llm_profile_id, "agent": agent_id},
            )
            if changed:
                activated.append(agent_id)
                _audit(tx, actor, "BOOTSTRAP_AGENT_ACTIVATE", "AGENT", agent_id, "ALLOW",
                       "Bootstrap Deployment Agent attached the approved platform LLM Profile")
        return {"activated": activated, "llm_profile_id": llm_profile_id}
    return connection.execute_transaction_callback(work)


def list_native_agents(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    all_access = False
    try:
        all_access = identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW"
    except Exception:
        pass
    where = ""
    if not all_access:
        where = " WHERE OWNER_PRINCIPAL_ID=:actor OR AGENT_ID=:actor"
        params["actor"] = actor
    rows = connection.execute_query(
        "SELECT AGENT_ID,SOURCE,AGENT_KIND,TEMPLATE_ID,OWNER_PRINCIPAL_ID,STATUS,ACTIVATION_STATE,"
        "LLM_PROFILE_ID,DEPLOYMENT_TARGET_ID,SECURITY_DOMAIN_ID,IS_PROTECTED,CREATED_AT,UPDATED_AT "
        "FROM CX_NATIVE_AGENTS" + where + " ORDER BY CREATED_AT DESC" + suffix, params,
    )
    return _rows(rows)


def list_native_agents_cursor(actor: str, *, page_size: int = 20, cursor: str = "") -> Dict[str, Any]:
    """Return authorized platform-native Agents without a whole-inventory scan."""
    context = cursor_pagination.resolve(actor, "native_agents", {}, "agent_id:asc", page_size, cursor)
    context.update({"principal_id": actor, "resource_key": "native_agents", "sort_key": "agent_id:asc"})
    all_access = False
    try:
        all_access = identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW"
    except Exception:
        pass
    params: Dict[str, Any] = {"limit": int(context["page_size"]) + 1}
    conditions: list[str] = []
    if not all_access:
        conditions.append("(OWNER_PRINCIPAL_ID=:actor OR AGENT_ID=:actor)")
        params["actor"] = actor
    after = str(context["position"].get("agent_id") or "")
    if after:
        conditions.append("AGENT_ID>:after")
        params["after"] = after
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = connection.execute_query(
        "SELECT AGENT_ID,SOURCE,AGENT_KIND,TEMPLATE_ID,OWNER_PRINCIPAL_ID,STATUS,ACTIVATION_STATE,"
        "LLM_PROFILE_ID,DEPLOYMENT_TARGET_ID,SECURITY_DOMAIN_ID,IS_PROTECTED,CREATED_AT,UPDATED_AT "
        "FROM CX_NATIVE_AGENTS" + where + " ORDER BY AGENT_ID" + _limit(int(context["page_size"]) + 1)[0], params,
    )
    values = _rows(rows)
    result = cursor_pagination.page(values, context, lambda item: {"agent_id": str(item["agent_id"])})
    count_where = " WHERE " + " AND ".join(
        [condition for condition in conditions if not condition.startswith("AGENT_ID>:after")]
    ) if any(not condition.startswith("AGENT_ID>:after") for condition in conditions) else ""
    count_params = {key: value for key, value in params.items() if key != "limit" and key != "after"}
    try:
        total = connection.execute_query_one("SELECT COUNT(*) AS CNT FROM CX_NATIVE_AGENTS" + count_where, count_params)
        result["total_items"] = int((total or {}).get("cnt") or 0)
    except Exception:
        pass
    return result


def list_templates(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT TEMPLATE_ID,TEMPLATE_KEY,DISPLAY_NAME,TEMPLATE_KIND,CONTENT_JSON,CONTENT_DIGEST,"
        "LOCKED_FIELDS_JSON,STATUS,MANAGED,CREATED_AT,UPDATED_AT FROM CX_AGENT_TEMPLATES "
        "WHERE STATUS='PUBLISHED' ORDER BY DISPLAY_NAME" + suffix, params,
    ))


def list_manifests(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    management_access = identity_api.effective_access(actor, "platform.manage").get("decision") == "ALLOW"
    private_clause = "" if management_access else " AND MANIFEST_KIND <> 'MANAGEMENT_KNOWLEDGE'"
    return _rows(connection.execute_query(
        "SELECT MANIFEST_ID,MANIFEST_KEY,VERSION,MANIFEST_KIND,CONTENT_JSON,CONTENT_DIGEST,"
        "SIGNATURE_STATUS,STATUS,MANAGED,CREATED_AT,UPDATED_AT FROM CX_NATIVE_MANIFESTS "
        "WHERE STATUS='PUBLISHED'" + private_clause + " ORDER BY MANIFEST_KEY,VERSION DESC" + suffix, params,
    ))


def management_template_knowledge(actor: str, agent_id: str, response_language: str = "en") -> Dict[str, Any]:
    """Read scoped, signed product workflow knowledge for management Agents."""
    if agent_id not in {PLATFORM_ADMIN_AGENT_ID, COMPLIANCE_ADMIN_AGENT_ID}:
        raise NativeAgentError("management knowledge is limited to built-in management Agents")
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required for management knowledge")
    is_compliance = agent_id == COMPLIANCE_ADMIN_AGENT_ID
    knowledge_key = "compliance-admin-knowledge" if is_compliance else "platform-admin-knowledge"
    version = 1 if is_compliance else MANAGEMENT_KNOWLEDGE_VERSION
    audience = "COMPLIANCE_ADMIN" if is_compliance else "MANAGEMENT_AGENTS"
    scope = "COMPLIANCE_AGENT" if is_compliance else "MANAGEMENT_AGENT"
    row = _row(connection.execute_query_one(
        "SELECT CONTENT_JSON,CONTENT_DIGEST,SIGNATURE_STATUS FROM CX_PLATFORM_KNOWLEDGE "
        "WHERE KNOWLEDGE_KEY=:knowledge_key AND VERSION=:version AND STATUS='PUBLISHED' "
        "AND AUDIENCE=:audience AND SCOPE_TYPE=:scope "
        "AND (VALID_FROM IS NULL OR VALID_FROM<=CURRENT_TIMESTAMP) "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
        {"knowledge_key": knowledge_key, "version": version,
         "audience": audience, "scope": scope},
    ))
    if not row:
        raise NativeAgentError("management knowledge is not initialized")
    content = _parse(row.get("content_json"), {})
    if (
        not isinstance(content, dict)
        or str(row.get("signature_status") or "") != "VERIFIED_BUILTIN"
        or str(row.get("content_digest") or "") != _digest(content)
    ):
        raise NativeAgentError("management knowledge is not verified")
    identity_api._audit(actor, "PLATFORM_KNOWLEDGE_READ", "PLATFORM_KNOWLEDGE",
                        knowledge_key, "ALLOW", "authorized scoped management knowledge read")
    return {**content, "response_language": "zh" if response_language == "zh" else "en"}


def management_knowledge_projection(actor: str, agent_id: str) -> Dict[str, Any]:
    """Return only the signed source projection for a management Agent.

    Chunk, vector, full-text, and graph projections remain unavailable until
    they are built with the same audience/scope/classification predicates. A
    missing projection must fail closed rather than fall back to shared rows.
    """
    content = management_template_knowledge(actor, agent_id)
    is_compliance = agent_id == COMPLIANCE_ADMIN_AGENT_ID
    return {
        "knowledge_key": "compliance-admin-knowledge" if is_compliance else "platform-admin-knowledge",
        "projection_mode": "SIGNED_SOURCE_ONLY",
        "chunk_projection": "UNAVAILABLE",
        "fulltext_projection": "UNAVAILABLE",
        "vector_projection": "UNAVAILABLE",
        "graph_projection": "UNAVAILABLE",
        "classification": "RESTRICTED",
        "content": content,
    }


def management_response_language(body: str) -> str:
    return "zh" if any("\u4e00" <= char <= "\u9fff" for char in str(body or "")) else "en"


def is_management_template_request(body: str) -> bool:
    """Recognize template lifecycle questions without broad model intent expansion."""
    value = str(body or "").lower()
    markers = (
        "内置agent模板", "内置 agent 模板", "内置智能体模板", "平台原生智能体模板",
        "添加内置", "修改内置", "创建模板", "编辑模板", "发布模板",
        "built-in agent template", "native agent template", "create template",
        "edit template", "publish template",
    )
    return any(marker in value for marker in markers)


def is_management_product_request(body: str) -> bool:
    """Recognize bounded platform/product overview questions."""
    value = str(body or "").lower()
    markers = (
        "平台介绍", "产品介绍", "介绍一下平台", "介绍一下产品", "平台是做什么", "产品是做什么",
        "平台能力", "产品能力", "平台功能", "产品功能", "什么是川序", "川序是什么",
        "platform overview", "product overview", "introduce the platform", "what is chuanxu",
        "what does the platform do", "platform capabilities", "product capabilities",
    )
    return any(marker in value for marker in markers)


def list_llm_profiles(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,STATUS,SECRET_PRESENT,HEALTH_STATE,"
        "VERSION,APPROVED_FOR_JSON,UPDATED_BY,UPDATED_AT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS <> 'RETIRED' ORDER BY PROFILE_KEY" + suffix,
        params,
    ))
    for row in rows:
        row.pop("api_key_cipher", None)
        row["secret_present"] = str(row.get("secret_present") or "N").upper() == "Y"
    return rows


def retire_llm_profile(actor: str, profile_id: str, reason: str) -> Dict[str, Any]:
    """Retire an LLM profile and revoke its stored secret without deleting history."""
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")
    profile_key = _text(profile_id, 128)
    why = _text(reason, 2000)
    if not profile_key or len(why) < 3:
        raise NativeAgentError("an LLM profile and removal reason of at least three characters are required")

    def work(tx: Any) -> Dict[str, Any]:
        profile = _row(tx.query_one(
            "SELECT PROFILE_ID,PROFILE_KEY,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id FOR UPDATE",
            {"id": profile_key}))
        if not profile:
            raise NativeAgentError("LLM Provider Profile is unavailable")
        if str(profile.get("status") or "").upper() == "RETIRED":
            raise NativeAgentError("LLM Provider Profile is already retired")
        blockers: list[str] = []
        checks = (
            ("PORTAL_DEFAULT", "SELECT COUNT(*) AS CNT FROM CX_PORTAL_LLM_POLICIES WHERE DEFAULT_PROFILE_ID=:id"),
            ("PORTAL_ALLOWLIST", "SELECT COUNT(*) AS CNT FROM CX_PORTAL_LLM_ALLOWLIST WHERE PROFILE_ID=:id AND STATUS='ACTIVE'"),
            ("ACTIVE_NATIVE_AGENT", "SELECT COUNT(*) AS CNT FROM CX_NATIVE_AGENTS WHERE LLM_PROFILE_ID=:id AND STATUS NOT IN ('RETIRED','DISABLED','QUARANTINED')"),
            ("PENDING_AGENT_REQUEST", "SELECT COUNT(*) AS CNT FROM CX_NATIVE_PROVISION_REQUESTS WHERE LLM_PROFILE_ID=:id AND STATUS IN ('APPROVAL_PENDING','APPROVED','PROVISIONING','PENDING')"),
        )
        for label, query in checks:
            count = _row(tx.query_one(query, {"id": profile_key})) or {}
            if int(count.get("cnt") or 0) > 0:
                blockers.append(label)
        if blockers:
            raise LLMProfileInUse(blockers)
        tx.execute(
            "UPDATE CX_LLM_PROVIDER_PROFILES SET STATUS='RETIRED',HEALTH_STATE='RETIRED',API_KEY_CIPHER=NULL,SECRET_PRESENT='N',UPDATED_BY=:actor,UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
            {"id": profile_key, "actor": actor, "reason": why},
        )
        _audit(tx, actor, "LLM_PROFILE_RETIRE", "LLM_PROFILE", profile_key, "ALLOW", why)
        return {"profile_id": profile_key, "profile_key": profile.get("profile_key"), "status": "RETIRED", "secret_present": False}
    return connection.execute_transaction_callback(work)


def upsert_llm_profile(actor: str, profile_key: str, provider_url: str, model_id: str,
                       api_key: str, reason: str, approved_for: Optional[list[str]] = None) -> Dict[str, Any]:
    if not _text(profile_key, 128) or not _text(provider_url, 512) or not _text(model_id, 256):
        raise NativeAgentError("profile key, provider URL, and model ID are required")
    if len(_text(reason, 2000)) < 3:
        raise NativeAgentError("a reason is required")
    cipher = None
    if api_key:
        from .connection_crypto import encrypt_section
        cipher = encrypt_section({"api_key": api_key})
    profile_id = "LLM_" + _text(profile_key, 128).replace("-", "_").upper()
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one(
            "SELECT PROFILE_ID,VERSION FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_KEY=:key FOR UPDATE",
            {"key": profile_key},
        ))
        params = {"id": str((existing or {}).get("profile_id") or profile_id), "key": profile_key[:128],
                  "url": provider_url[:512], "model": model_id[:256], "cipher": cipher,
                  "secret": "Y" if api_key else "N", "approved": _json(approved_for or []), "actor": actor,
                  "reason": reason[:2000]}
        if existing:
            # An empty API key deliberately preserves a previously configured
            # encrypted secret; callers can clear it explicitly through the
            # dedicated rotation/revocation operation.
            if cipher:
                update_params = {
                    key: params[key]
                    for key in ("id", "url", "model", "cipher", "secret", "approved", "actor", "reason")
                }
                tx.execute(
                    "UPDATE CX_LLM_PROVIDER_PROFILES SET PROVIDER_URL=:url,MODEL_ID=:model,API_KEY_CIPHER=:cipher,"
                    "SECRET_PRESENT=:secret,APPROVED_FOR_JSON=:approved,VERSION=VERSION+1,UPDATED_BY=:actor,"
                    "UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
                    update_params,
                )
            else:
                update_params = {
                    key: params[key]
                    for key in ("id", "url", "model", "approved", "actor", "reason")
                }
                tx.execute(
                    "UPDATE CX_LLM_PROVIDER_PROFILES SET PROVIDER_URL=:url,MODEL_ID=:model,APPROVED_FOR_JSON=:approved,"
                    "VERSION=VERSION+1,UPDATED_BY=:actor,UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
                    update_params,
                )
        else:
            tx.execute(
                "INSERT INTO CX_LLM_PROVIDER_PROFILES(PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,API_KEY_CIPHER,"
                "SECRET_PRESENT,HEALTH_STATE,STATUS,VERSION,APPROVED_FOR_JSON,UPDATED_BY,UPDATE_REASON) VALUES "
                "(:id,:key,:url,:model,:cipher,:secret,'UNKNOWN','ACTIVE',1,:approved,:actor,:reason)", params,
            )
        _audit(tx, actor, "LLM_PROFILE_UPSERT", "LLM_PROFILE", params["id"], "ALLOW", reason)
        return {"profile_id": params["id"], "profile_key": profile_key, "status": "ACTIVE", "secret_present": bool(api_key)}
    return connection.execute_transaction_callback(work)


def probe_llm_profile(actor: str, profile_key: str, provider_url: str, model_id: str,
                      api_key: str, *, timeout: int = 20) -> Dict[str, Any]:
    """Probe an OpenAI-compatible LLM without persisting or logging its secret."""
    key = _text(profile_key, 128)
    url = _text(provider_url, 512).rstrip("/")
    model = _text(model_id, 256)
    parsed = urlsplit(url)
    if not key or not model or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NativeAgentError("profile key, provider URL, and model ID are required")
    if parsed.username or parsed.password or parsed.fragment:
        raise NativeAgentError("LLM provider URL is invalid")
    headers = {"Content-Type": "application/json"}
    secret = _text(api_key, 4096)
    if secret:
        headers["Authorization"] = "Bearer " + secret
    started = time.monotonic()
    try:
        request = urllib.request.Request(
            url + "/chat/completions",
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": "health check"}],
                "max_tokens": 1,
                "stream": False,
            }, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=max(1, min(int(timeout), 60))) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        if not isinstance(payload, dict) or not (payload.get("choices") or []):
            raise NativeAgentError("LLM provider returned no completion")
        observed_model = _text(payload.get("model"), 256)
        if not _llm_model_matches(model, observed_model):
            raise NativeAgentError("LLM provider returned a different model")
        elapsed_ms = round((time.monotonic() - started) * 1000)
        # The audit contains only the profile identity and outcome; it never
        # contains the URL query, prompt, response, or API Key.
        def work(tx: Any) -> Dict[str, Any]:
            _audit(tx, actor, "LLM_PROFILE_DRAFT_PROBE", "LLM_PROFILE_DRAFT", key,
                   "ALLOW", "LLM draft connectivity probe verified")
            return {"status": "VERIFIED", "profile_key": key,
                    "observed_model": observed_model,
                    "latency_ms": elapsed_ms}
        return connection.execute_transaction_callback(work)
    except (NativeAgentError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        def work(tx: Any) -> Dict[str, Any]:
            _audit(tx, actor, "LLM_PROFILE_DRAFT_PROBE", "LLM_PROFILE_DRAFT", key,
                   "DENY", "LLM draft connectivity probe failed")
            return {"status": "FAILED", "profile_key": key}
        connection.execute_transaction_callback(work)
        if isinstance(exc, NativeAgentError):
            raise NativeAgentError(str(exc)) from exc
        raise NativeAgentError("LLM provider probe failed") from exc


def _policy_row() -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT POLICY_KEY,STATE,VERSION,UPDATED_BY,REASON,UPDATED_AT FROM CX_EXTERNAL_AGENT_POLICY "
        "WHERE POLICY_KEY=:key", {"key": EXTERNAL_REGISTRATION_KEY},
    ))
    if not row:
        raise NativeAgentError("external Agent registration policy is unavailable")
    return row


def probe_saved_llm_profile(actor: str, profile_id: str, *, timeout: int = 20) -> Dict[str, Any]:
    """Probe a persisted profile and update only its safe health projection."""
    if identity_api.effective_access(str(actor), "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required")
    key = _text(profile_id, 128)
    row = _row(connection.execute_query_one(
        "SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,API_KEY_CIPHER,STATUS "
        "FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id", {"id": key},
    ))
    if not row or str(row.get("status") or "").upper() != "ACTIVE":
        raise NativeAgentError("LLM Provider Profile is unavailable")
    secret = ""
    cipher = str(row.get("api_key_cipher") or "")
    if cipher:
        from .connection_crypto import decrypt_section
        secret = str(decrypt_section(cipher).get("api_key") or "")
    try:
        result = probe_llm_profile(
            actor, str(row.get("profile_key") or key), str(row.get("provider_url") or ""),
            str(row.get("model_id") or ""), secret, timeout=timeout,
        )
    except Exception:
        connection.execute(
            "UPDATE CX_LLM_PROVIDER_PROFILES SET HEALTH_STATE='DEGRADED',UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": key},
        )
        raise
    connection.execute(
        "UPDATE CX_LLM_PROVIDER_PROFILES SET HEALTH_STATE='HEALTHY',UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": key},
    )
    return {**result, "profile_id": key, "health_state": "HEALTHY"}


def external_registration_policy() -> Dict[str, Any]:
    row = _policy_row()
    row["allowed"] = str(row.get("state") or "DISABLED").upper() != "DISABLED"
    return row


def set_external_registration_policy(actor: str, state: str, reason: str,
                                     expected_version: int) -> Dict[str, Any]:
    state = _text(state, 32).upper()
    reason = _text(reason, 2000)
    if state not in REGISTRATION_STATES or len(reason) < 3:
        raise NativeAgentError("invalid external registration state or missing reason")
    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT POLICY_KEY,STATE,VERSION FROM CX_EXTERNAL_AGENT_POLICY WHERE POLICY_KEY=:key FOR UPDATE",
            {"key": EXTERNAL_REGISTRATION_KEY},
        ))
        if not current:
            raise NativeAgentError("external Agent registration policy is unavailable")
        if int(current.get("version") or 0) != int(expected_version):
            raise NativeAgentConflict("external registration policy changed concurrently")
        if str(current.get("state") or "").upper() == state:
            return current
        tx.execute(
            "UPDATE CX_EXTERNAL_AGENT_POLICY SET STATE=:state,VERSION=VERSION+1,UPDATED_BY=:actor,REASON=:reason,"
            "UPDATED_AT=CURRENT_TIMESTAMP WHERE POLICY_KEY=:key AND VERSION=:version",
            {"key": EXTERNAL_REGISTRATION_KEY, "state": state, "actor": actor, "reason": reason,
             "version": int(current["version"])},
        )
        tx.execute(
            "INSERT INTO CX_EXTERNAL_AGENT_POLICY_HISTORY(HISTORY_ID,POLICY_KEY,FROM_STATE,TO_STATE,RESULT_VERSION,"
            "CHANGED_BY,REASON) VALUES (:id,:key,:before,:after,:version,:actor,:reason)",
            {"id": _id("EAPH"), "key": EXTERNAL_REGISTRATION_KEY, "before": current["state"],
             "after": state, "version": int(current["version"]) + 1, "actor": actor, "reason": reason},
        )
        _audit(tx, actor, "EXTERNAL_AGENT_REGISTRATION_POLICY", "PLATFORM",
               EXTERNAL_REGISTRATION_KEY, "ALLOW", reason)
        return {"policy_key": EXTERNAL_REGISTRATION_KEY, "state": state, "version": int(current["version"]) + 1}
    return connection.execute_transaction_callback(work)


def create_request(actor: str, *, agent_name: str, owner_principal_id: str,
                   template_key: str, provider_profile_id: str, target_id: str,
                   isolation_level: str, classification: str, purpose: str,
                   reason: str) -> Dict[str, Any]:
    if not all((_text(agent_name, 256), _text(owner_principal_id, 128), _text(template_key, 128),
                _text(purpose, 2000), _text(reason, 2000))):
        raise NativeAgentError("Agent name, owner, template, purpose, and reason are required")
    isolation_level = _text(isolation_level, 32).upper()
    if isolation_level not in ISOLATION_LEVELS:
        raise NativeAgentError("invalid runtime isolation level")
    owner_principal_id = _text(owner_principal_id, 128)
    if owner_principal_id != actor and identity_api.effective_access(
        actor, "agents.enroll.others"
    ).get("decision") != "ALLOW":
        raise PermissionError("Agent owner is outside the delegated scope")
    request_id = _id("APR")
    def work(tx: Any) -> Dict[str, Any]:
        owner = _row(tx.query_one(
            "SELECT PRINCIPAL_ID,PRINCIPAL_TYPE,STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id",
            {"id": owner_principal_id},
        ))
        if not owner or str(owner.get("status") or "").upper() != "ACTIVE" or str(owner.get("principal_type") or "").upper() != "HUMAN":
            raise NativeAgentError("Agent owner must be an active human Principal")
        template = _row(tx.query_one(
            "SELECT TEMPLATE_ID,CONTENT_JSON FROM CX_AGENT_TEMPLATES WHERE TEMPLATE_KEY=:key AND STATUS='PUBLISHED'",
            {"key": template_key},
        ))
        if not template:
            raise NativeAgentError("Agent template is unavailable")
        content = template.get("content_json")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                content = {}
        required = str((content or {}).get("isolation_level") or "STANDARD").upper()
        rank = {name: index for index, name in enumerate(("STANDARD", "DOMAIN_ISOLATED", "DEDICATED_CONTAINER", "DEDICATED_RUNTIME", "EXTERNAL_MANAGED"))}
        if required in rank and rank[isolation_level] < rank[required]:
            raise NativeAgentError("requested isolation is weaker than the template requirement")
        tx.execute(
            "INSERT INTO CX_NATIVE_PROVISION_REQUESTS(REQUEST_ID,AGENT_NAME,APPLICANT_PRINCIPAL_ID,OWNER_PRINCIPAL_ID,"
            "TEMPLATE_KEY,LLM_PROFILE_ID,DEPLOYMENT_TARGET_ID,ISOLATION_LEVEL,CLASSIFICATION,PURPOSE,REASON,STATUS) VALUES "
            "(:id,:name,:applicant,:owner,:template,:profile,:target,:isolation,:classification,:purpose,:reason,'APPROVAL_PENDING')",
            {"id": request_id, "name": agent_name[:256], "applicant": actor, "owner": owner_principal_id[:128],
             "template": template_key[:128], "profile": provider_profile_id[:128] or None,
             "target": target_id[:128] or None, "isolation": isolation_level, "classification": classification[:32],
             "purpose": purpose[:2000], "reason": reason[:2000]},
        )
        _audit(tx, actor, "AGENT_PROVISION_REQUEST", "AGENT_REQUEST", request_id, "ALLOW", reason)
        return {"request_id": request_id, "status": "APPROVAL_PENDING"}
    return connection.execute_transaction_callback(work)


def list_requests(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    all_access = False
    try:
        all_access = identity_api.effective_access(actor, "agents.read.all").get("decision") == "ALLOW"
    except Exception:
        pass
    where = ""
    if not all_access:
        where = " WHERE APPLICANT_PRINCIPAL_ID=:actor OR OWNER_PRINCIPAL_ID=:actor OR DECIDED_BY=:actor"
        params["actor"] = actor
    return _rows(connection.execute_query(
        "SELECT REQUEST_ID,AGENT_NAME,APPLICANT_PRINCIPAL_ID,OWNER_PRINCIPAL_ID,TEMPLATE_KEY,LLM_PROFILE_ID,"
        "DEPLOYMENT_TARGET_ID,ISOLATION_LEVEL,CLASSIFICATION,PURPOSE,REASON,STATUS,DECIDED_BY,DECISION_REASON,"
        "CREATED_AT,UPDATED_AT FROM CX_NATIVE_PROVISION_REQUESTS" + where + " ORDER BY CREATED_AT DESC" + suffix, params,
    ))


def decide_request(actor: str, request_id: str, decision: str, reason: str) -> Dict[str, Any]:
    decision = _text(decision, 32).upper()
    reason = _text(reason, 2000)
    if decision not in {"APPROVE", "REJECT"} or len(reason) < 3:
        raise NativeAgentError("invalid decision or missing reason")
    if identity_api.effective_access(actor, "agents.manage").get("decision") != "ALLOW":
        raise PermissionError("Agent provisioning decision denied")
    def work(tx: Any) -> Dict[str, Any]:
        request = _row(tx.query_one(
            "SELECT * FROM CX_NATIVE_PROVISION_REQUESTS WHERE REQUEST_ID=:id FOR UPDATE",
            {"id": request_id},
        ))
        if not request or str(request.get("status") or "") != "APPROVAL_PENDING":
            raise NativeAgentConflict("Agent request is not pending approval")
        if str(request.get("applicant_principal_id") or "") == actor:
            raise PermissionError("applicant cannot approve its own Agent request")
        status = "PROVISIONING" if decision == "APPROVE" else "REJECTED"
        tx.execute(
            "UPDATE CX_NATIVE_PROVISION_REQUESTS SET STATUS=:status,DECIDED_BY=:actor,DECISION_REASON=:reason,"
            "DECIDED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id",
            {"status": status, "actor": actor, "reason": reason, "id": request_id},
        )
        created_agent_id = ""
        if decision == "APPROVE":
            created_agent_id = _id("PA")
            target_id = str(request.get("deployment_target_id") or "DT_LOCAL_MANAGED")
            template = _row(tx.query_one(
                "SELECT TEMPLATE_ID FROM CX_AGENT_TEMPLATES WHERE TEMPLATE_KEY=:key AND STATUS='PUBLISHED'",
                {"key": request.get("template_key")},
            ))
            if not template:
                raise NativeAgentError("Agent template is unavailable")
            _ensure_principal(tx, created_agent_id)
            tx.execute(
                "INSERT INTO CX_NATIVE_AGENTS(AGENT_ID,SOURCE,AGENT_KIND,TEMPLATE_ID,OWNER_PRINCIPAL_ID,STATUS,"
                "ACTIVATION_STATE,LLM_PROFILE_ID,DEPLOYMENT_TARGET_ID,SECURITY_DOMAIN_ID,IS_PROTECTED,CREATED_BY) VALUES "
                "(:agent,'PLATFORM_CREATED',:kind,:template,:owner,'INITIALIZED','ACTIVATION_PENDING',:profile,:target,'DEFAULT','N',:actor)",
                {"agent": created_agent_id, "kind": "BUSINESS", "template": template["template_id"],
                 "owner": request.get("owner_principal_id"), "profile": request.get("llm_profile_id"),
                 "target": target_id, "actor": actor},
            )
            tx.execute(
                "INSERT INTO CX_AGENT_RELATIONSHIPS(RELATIONSHIP_ID,AGENT_ID,PRINCIPAL_ID,RELATIONSHIP_ROLE,STATUS) "
                "VALUES (:id,:agent,:owner,'PRIMARY_OWNER','ACTIVE')",
                {"id": _id("AR"), "agent": created_agent_id, "owner": request.get("owner_principal_id")},
            )
            _audit(tx, actor, "PLATFORM_AGENT_PROVISIONED", "AGENT", created_agent_id, "ALLOW", reason)
        _audit(tx, actor, "AGENT_PROVISION_DECISION", "AGENT_REQUEST", request_id, "ALLOW", reason)
        return {"request_id": request_id, "status": status, "decision": decision,
                "agent_id": created_agent_id or None}
    return connection.execute_transaction_callback(work)


def activate_agent(actor: str, agent_id: str, llm_profile_id: str, reason: str) -> Dict[str, Any]:
    if len(_text(reason, 2000)) < 3 or not _text(llm_profile_id, 128):
        raise NativeAgentError("an approved LLM profile and reason are required")
    if identity_api.effective_access(actor, "agents.manage").get("decision") != "ALLOW":
        raise PermissionError("native Agent activation denied")
    def work(tx: Any) -> Dict[str, Any]:
        agent = _row(tx.query_one(
            "SELECT AGENT_ID,STATUS,ACTIVATION_STATE,IS_PROTECTED FROM CX_NATIVE_AGENTS "
            "WHERE AGENT_ID=:id FOR UPDATE", {"id": agent_id},
        ))
        if not agent:
            raise NativeAgentError("native Agent is unavailable")
        if not identity_api._agent_visible_to(actor, agent_id):
            raise PermissionError("Agent is outside the delegated scope")
        profile = _row(tx.query_one(
            "SELECT PROFILE_ID,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:id",
            {"id": llm_profile_id},
        ))
        if not profile or str(profile.get("status") or "").upper() != "ACTIVE":
            raise NativeAgentError("LLM Provider Profile is unavailable")
        if str(agent.get("is_protected") or "N").upper() != "Y":
            # A configured default Contract is optional for platforms that do
            # not use vectors.  Once it exists, a business Agent cannot become
            # active while that Contract remains unverified or write-blocked.
            from . import embedding_governance
            effective = embedding_governance.effective_binding(agent_id)
            if effective.get("binding") and not effective.get("ready"):
                raise NativeAgentError("Embedding Contract is not ready for this business Agent")
        tx.execute(
            "UPDATE CX_NATIVE_AGENTS SET STATUS='ACTIVE',ACTIVATION_STATE='ACTIVE',LLM_PROFILE_ID=:profile,"
            "UPDATED_AT=CURRENT_TIMESTAMP WHERE AGENT_ID=:agent",
            {"profile": llm_profile_id, "agent": agent_id},
        )
        _audit(tx, actor, "NATIVE_AGENT_ACTIVATE", "AGENT", agent_id, "ALLOW", reason)
        return {"agent_id": agent_id, "status": "ACTIVE", "activation_state": "ACTIVE",
                "llm_profile_id": llm_profile_id}
    return connection.execute_transaction_callback(work)


def create_execution(actor: str, agent_id: str, messages: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    from . import native_runtime
    return native_runtime.enqueue(actor, agent_id, messages, reason)


def _count_status(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    try:
        row = _row(connection.execute_query_one(sql, params or {})) or {}
        return int(row.get("cnt") or 0)
    except Exception:
        return 0


def management_status_snapshot(actor: str, agent_id: str) -> Dict[str, Any]:
    """Return an aggregated, credential-free control-plane status snapshot.

    It intentionally returns counts and state classes only. No database DSN,
    host, API key, prompt, channel body, human identity, or agent token can be
    passed to a model through the management Channel.
    """
    from . import admin_management

    if agent_id not in {PLATFORM_ADMIN_AGENT_ID, COMPLIANCE_ADMIN_AGENT_ID}:
        raise NativeAgentError("management status snapshot is limited to built-in management Agents")
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required for a status snapshot")
    snapshot = {
        "scope": "database_control_plane_only",
        "native_agents": {
            "active": _count_status("SELECT COUNT(*) AS CNT FROM CX_NATIVE_AGENTS WHERE STATUS='ACTIVE'"),
            "non_active": _count_status("SELECT COUNT(*) AS CNT FROM CX_NATIVE_AGENTS WHERE STATUS<>'ACTIVE'"),
        },
        "runtime_executions": {
            "pending": _count_status("SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE STATUS='PENDING'"),
            "claimed": _count_status("SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE STATUS='CLAIMED'"),
            "failed": _count_status("SELECT COUNT(*) AS CNT FROM CX_RUNTIME_EXECUTIONS WHERE STATUS='FAILED'"),
        },
        "llm_profiles": {
            "active": _count_status("SELECT COUNT(*) AS CNT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE'"),
            "healthy": _count_status("SELECT COUNT(*) AS CNT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE' AND HEALTH_STATE='HEALTHY'"),
            "degraded": _count_status("SELECT COUNT(*) AS CNT FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS='ACTIVE' AND HEALTH_STATE='DEGRADED'"),
        },
        "admin_group": {
            "active_voting_members": _count_status("SELECT COUNT(*) AS CNT FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND STATUS='ACTIVE' AND VOTING_ENABLED='Y'", {"group_id": admin_management.ADMIN_GROUP_ID}),
            "current_term": 0,
            "status": "UNKNOWN",
        },
    }
    try:
        group = _row(connection.execute_query_one(
            "SELECT STATUS,CURRENT_TERM FROM CX_ADMIN_AGENT_GROUPS WHERE GROUP_ID=:group_id",
            {"group_id": admin_management.ADMIN_GROUP_ID},
        )) or {}
        snapshot["admin_group"].update({"status": str(group.get("status") or "UNKNOWN"), "current_term": int(group.get("current_term") or 0)})
    except Exception:
        pass
    return snapshot


def is_management_status_request(body: str) -> bool:
    """Recognize read-only platform-health requests without intent expansion."""
    value = str(body or "").lower()
    markers = (
        "运行状态", "平台状态", "当前状态", "系统状态", "健康状态", "检查状态",
        "runtime status", "platform status", "system status", "health status",
    )
    return any(marker in value for marker in markers)


def create_channel_execution(actor: str, channel_id: str, message_id: str, body: str,
                             mentioned_agent_id: str, thread_type: str = "CHANNEL",
                             thread_id: str = "", *, response_language: str = "") -> Dict[str, Any]:
    """Queue one bounded management-channel response for an explicit mention.

    A Channel message is not an authority grant.  This narrow bridge exists
    only for the protected Platform Administration Channel and only for an
    active built-in management Agent explicitly mentioned by a human member.
    The deterministic execution ID makes a browser retry or delivery retry
    harmless without requiring a new database table.
    """
    from . import admin_management

    if channel_id != admin_management.ADMIN_CHANNEL_ID:
        raise NativeAgentError("native Channel execution is limited to the Platform Administration Channel")
    is_platform_command = str(body or "").strip().lower().startswith("/platform ")
    if is_platform_command and mentioned_agent_id != PLATFORM_ADMIN_AGENT_ID:
        raise NativeAgentError("typed platform commands are handled by the Platform Admin Agent")
    if mentioned_agent_id not in {PLATFORM_ADMIN_AGENT_ID, COMPLIANCE_ADMIN_AGENT_ID}:
        raise NativeAgentError("mentioned Agent is not an approved management Agent")
    if mentioned_agent_id == COMPLIANCE_ADMIN_AGENT_ID and not _enterprise():
        raise NativeAgentError("Compliance Admin Agent is unavailable in this edition")
    if not str(message_id or "").strip() or not str(body or "").strip():
        raise NativeAgentError("Channel message context is incomplete")
    if len(body.encode("utf-8")) > 48 * 1024:
        raise NativeAgentError("Channel message is too large for managed Agent execution")
    if identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        raise PermissionError("platform management permission is required for Channel Agent dispatch")

    # ordinary prose remains conversational; an explicit slash command is converted to the same typed command and
    # Action Card used by Dashboard. Ordinary prose remains conversational and
    # can only request a read-only status snapshot.
    command_notice: Dict[str, Any] = {}
    stripped = str(body or "").strip()
    if stripped.lower().startswith("/platform "):
        from . import platform_agent_pool
        pieces = stripped.split(None, 4)
        command_type = pieces[1].upper() if len(pieces) > 1 else ""
        # Accept the common transposition in HEALTH_READ while keeping the
        # persisted command contract and audit vocabulary canonical.
        if command_type == "HEATH_READ":
            command_type = "HEALTH_READ"
        command_target: Dict[str, Any] = {}
        command_parameters: Dict[str, Any] = {}
        if command_type == "HELP":
            help_key = pieces[2].strip() if len(pieces) > 2 else ""
            command_notice = {"help": platform_agent_pool.command_help(actor, help_key, channel_id)}
            command_notice = {"command_type": "HELP", "status": "COMPLETED", **command_notice}
        else:
            if command_type == "AGENT_DRAIN":
                if len(pieces) < 4:
                    raise NativeAgentError("AGENT_DRAIN requires source node, destination node, and reason")
                command_target = {"node_id": pieces[2].strip()}
                command_parameters = {"target_node_id": pieces[3].strip()}
                command_reason = stripped.split(None, 4)[4].strip() if len(stripped.split(None, 4)) > 4 else ""
            else:
                command_reason = pieces[2].strip() if len(pieces) > 2 else ""
            command = platform_agent_pool.create_command(
                actor, command_type, command_target, command_parameters, "DEFAULT", command_reason,
            )
            command_notice = {"command_id": command.get("command_id"), "command_type": command_type,
                              "status": command.get("status"), "result": command.get("result") or {},
                              "action_card": command.get("action_card") or {}}

    command_help_snapshot = command_notice.get("help") if command_notice.get("command_type") == "HELP" else None
    command_result_snapshot = command_notice if command_notice.get("status") == "COMPLETED" and command_notice.get("result") else None
    status_request = is_management_status_request(body)
    template_request = is_management_template_request(body)
    product_request = is_management_product_request(body)
    deterministic_response = bool(
        command_help_snapshot is not None
        or command_result_snapshot is not None
        or status_request
        or template_request
        or product_request
    )

    def work(tx: Any) -> Dict[str, Any]:
        nonlocal response_language
        member = _row(tx.query_one(
            "SELECT MEMBER_ID FROM CX_ADMIN_AGENT_MEMBERS WHERE GROUP_ID=:group_id AND AGENT_ID=:agent "
            "AND STATUS='ACTIVE' AND VOTING_ENABLED='Y' FOR UPDATE",
            {"group_id": admin_management.ADMIN_GROUP_ID, "agent": mentioned_agent_id},
        ))
        agent = _row(tx.query_one(
            "SELECT AGENT_ID,STATUS,ACTIVATION_STATE,DEPLOYMENT_TARGET_ID,LLM_PROFILE_ID FROM CX_NATIVE_AGENTS "
            "WHERE AGENT_ID=:agent FOR UPDATE", {"agent": mentioned_agent_id},
        ))
        if not member or not agent or str(agent.get("status") or "").upper() != "ACTIVE":
            raise NativeAgentError("mentioned management Agent is not ready")
        if not deterministic_response and not str(agent.get("llm_profile_id") or ""):
            raise NativeAgentError("mentioned management Agent is not ready")
        channel_member = _row(tx.query_one(
            "SELECT MEMBER_ID FROM CX_CHANNEL_MEMBERS WHERE CHANNEL_ID=:channel AND PRINCIPAL_ID=:agent "
            "AND STATUS='ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP) FOR UPDATE",
            {"channel": channel_id, "agent": mentioned_agent_id},
        ))
        if not channel_member:
            raise NativeAgentError("mentioned management Agent is not an active Channel member")
        digest = _digest({"channel": channel_id, "message": message_id, "agent": mentioned_agent_id})
        execution_id = "EXE_CH_" + digest[:56]
        existing = _row(tx.query_one(
            "SELECT EXECUTION_ID,STATUS FROM CX_RUNTIME_EXECUTIONS WHERE EXECUTION_ID=:id FOR UPDATE",
            {"id": execution_id},
        ))
        if existing:
            return {"execution_id": execution_id, "agent_id": mentioned_agent_id,
                    "status": str(existing.get("status") or "PENDING"), "idempotent": True}
        response_language = response_language or management_response_language(body)
        status_snapshot = management_status_snapshot(actor, mentioned_agent_id) if status_request else None
        template_knowledge = management_template_knowledge(
            actor, mentioned_agent_id, response_language,
        ) if template_request else None
        system_prompt = (
            "你是受保护管理频道中的平台管理 Agent。必须仅使用中文回答本次明确提及你的请求，并保持简洁。"
            "不得声称已执行配置、安全、成员、升级或阻断变更；涉及这些变更时，应说明所需的受治理操作卡或审批路径。"
            if response_language == "zh" else
            "You are a platform management Agent in a protected administration Channel. "
            "Answer the explicitly mentioned request concisely and only in English. Do not claim that you executed a "
            "configuration, security, membership, upgrade, or containment change. For such changes, explain the "
            "governed Action Card or approval path required."
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": body},
            ],
            "response_language": response_language,
            "channel_dispatch": {
                "channel_id": channel_id, "message_id": message_id,
                "thread_type": str(thread_type or "CHANNEL").upper(), "thread_id": thread_id or "",
                "requester_principal_id": actor,
            },
        }
        if command_notice:
            command_prompt = (
                "已记录一个显式的类型化平台命令。请仅说明该结果，不得声称执行了任何额外操作："
                if response_language == "zh" else
                "An explicit typed platform command was recorded. Present this result without claiming any additional action: "
            )
            payload["messages"].insert(0, {"role": "system", "content": command_prompt + _json(command_notice)})
        if status_snapshot is not None:
            payload["management_status_snapshot"] = status_snapshot
        if command_help_snapshot is not None:
            payload["platform_command_help"] = command_help_snapshot
        if command_result_snapshot is not None:
            payload["platform_command_result"] = command_result_snapshot
        if template_knowledge is not None:
            payload["management_template_knowledge"] = template_knowledge
        if product_request:
            payload["management_product_overview"] = management_template_knowledge(
                actor, mentioned_agent_id, response_language,
            )
        input_json = _json(payload)
        tx.execute(
            "INSERT INTO CX_RUNTIME_EXECUTIONS(EXECUTION_ID,AGENT_ID,TARGET_ID,ISOLATION_LEVEL,STATUS,INPUT_JSON,CONTEXT_DIGEST) "
            "VALUES (:id,:agent,:target,'DOMAIN_ISOLATED','PENDING',:input,:digest)",
            {"id": execution_id, "agent": mentioned_agent_id, "target": agent.get("deployment_target_id"),
             "input": input_json, "digest": digest},
        )
        _audit(tx, actor, "CHANNEL_MANAGEMENT_AGENT_DISPATCH", "CHANNEL_MESSAGE", message_id,
               "ALLOW", "explicit management Agent mention queued")
        return {"execution_id": execution_id, "agent_id": mentioned_agent_id,
                "status": "PENDING", "idempotent": False}

    return connection.execute_transaction_callback(work)


def enforce_external_registration_allowed() -> None:
    state = str(_policy_row().get("state") or "DISABLED").upper()
    if state == "DISABLED":
        raise PermissionError("external Agent registration is disabled")


def claim_runtime(worker_id: str, node_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Claim bounded executions with a database lease; no model call occurs here."""
    suffix, params = _limit(limit)
    # Keep the SELECT bind set separate from the conditional UPDATE bind set.
    # Oracle rejects extra bind variables that do not occur in the statement;
    # PostgreSQL happens to tolerate them, which previously hid this adapter
    # incompatibility.
    worker = _text(worker_id, 128)
    node = _text(node_id, 128)
    rows = connection.execute_query(
        "SELECT EXECUTION_ID,AGENT_ID,TARGET_ID,ISOLATION_LEVEL,STATUS,FENCING_TOKEN,INPUT_JSON FROM CX_RUNTIME_EXECUTIONS "
        "WHERE STATUS='PENDING' OR (STATUS='CLAIMED' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP) "
        "ORDER BY CREATED_AT" + suffix, params,
    )
    claimed: List[Dict[str, Any]] = []
    for raw in rows:
        row = _row(raw) or {}
        changed = connection.execute(
            "UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='CLAIMED',WORKER_ID=:worker,NODE_ID=:node,"
            "LEASE_EXPIRES_AT=" + _lease_deadline_sql() + ",FENCING_TOKEN=FENCING_TOKEN+1,"
            "STARTED_AT=" + _lease_started_sql() + ",UPDATED_AT=CURRENT_TIMESTAMP WHERE EXECUTION_ID=:id AND (STATUS='PENDING' OR "
            "(STATUS='CLAIMED' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP))",
            {"worker": worker, "node": node, "id": row.get("execution_id")},
        )
        if changed:
            row["fencing_token"] = int(row.get("fencing_token") or 0) + 1
            row["worker_id"] = worker
            row["node_id"] = node
            claimed.append(row)
    return claimed
