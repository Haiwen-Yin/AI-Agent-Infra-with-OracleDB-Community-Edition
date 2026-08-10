"""Platform-native Agent provisioning and runtime contracts for v4.3.6.

This module owns the database-authoritative control plane for built-in and
platform-created Agents.  It intentionally does not implement customer
vendor connectors.  Those integrations use the DeploymentTarget contract and
are kept outside the product's trust boundary.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api


PLATFORM_ADMIN_AGENT_ID = "SYSTEM_PLATFORM_ADMIN_AGENT"
COMPLIANCE_ADMIN_AGENT_ID = "SYSTEM_COMPLIANCE_ADMIN_AGENT"
BOOTSTRAP_VERSION = "4.3.6"
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


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


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
    existing = _row(tx.query_one(
        "SELECT MANIFEST_ID FROM CX_NATIVE_MANIFESTS WHERE MANIFEST_KEY=:key AND VERSION=1 FOR UPDATE",
        {"key": key},
    ))
    if existing:
        return False
    digest = _digest(content)
    tx.execute(
        "INSERT INTO CX_NATIVE_MANIFESTS(MANIFEST_ID,MANIFEST_KEY,VERSION,MANIFEST_KIND,CONTENT_JSON,"
        "CONTENT_DIGEST,SIGNATURE,SIGNATURE_STATUS,STATUS,MANAGED,CREATED_BY) VALUES "
        "(:id,:key,1,:kind,:content,:digest,:signature,'VERIFIED_BUILTIN','PUBLISHED','Y','SYSTEM_BOOTSTRAP')",
        {"id": "AM_SEED_" + key.replace("-", "_").upper(), "key": key,
         "kind": kind, "content": _json(content), "digest": digest,
         "signature": "BUILTIN-SHA256:" + digest},
    )
    return True


def _ensure_principal(tx: Any, agent_id: str) -> None:
    existing = _row(tx.query_one(
        "SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id FOR UPDATE",
        {"id": agent_id},
    ))
    if not existing:
        tx.execute(
            "INSERT INTO CX_PRINCIPALS(PRINCIPAL_ID,PRINCIPAL_TYPE,STATUS,PERMISSION_VERSION) "
            "VALUES (:id,'AGENT','ACTIVE',1)", {"id": agent_id},
        )


def _ensure_native_agent(tx: Any, agent_id: str, kind: str, template_key: str,
                         target_id: str, owner_id: str = "") -> bool:
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
    _ensure_principal(tx, agent_id)
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
            return {"status": "COMPLETED", "idempotent": True,
                    "agents": [PLATFORM_ADMIN_AGENT_ID] + ([COMPLIANCE_ADMIN_AGENT_ID] if _enterprise() else [])}
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
        return {"status": "COMPLETED", "idempotent": not bool(created), "created": created}
    try:
        return connection.execute_transaction_callback(work)
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


def list_templates(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT TEMPLATE_ID,TEMPLATE_KEY,DISPLAY_NAME,TEMPLATE_KIND,CONTENT_JSON,CONTENT_DIGEST,"
        "LOCKED_FIELDS_JSON,STATUS,MANAGED,CREATED_AT,UPDATED_AT FROM CX_AGENT_TEMPLATES "
        "WHERE STATUS='PUBLISHED' ORDER BY DISPLAY_NAME" + suffix, params,
    ))


def list_manifests(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT MANIFEST_ID,MANIFEST_KEY,VERSION,MANIFEST_KIND,CONTENT_JSON,CONTENT_DIGEST,"
        "SIGNATURE_STATUS,STATUS,MANAGED,CREATED_AT,UPDATED_AT FROM CX_NATIVE_MANIFESTS "
        "WHERE STATUS='PUBLISHED' ORDER BY MANIFEST_KEY,VERSION DESC" + suffix, params,
    ))


def list_llm_profiles(actor: str, limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,STATUS,SECRET_PRESENT,HEALTH_STATE,"
        "VERSION,APPROVED_FOR_JSON,UPDATED_BY,UPDATED_AT FROM CX_LLM_PROVIDER_PROFILES ORDER BY PROFILE_KEY" + suffix,
        params,
    ))
    for row in rows:
        row.pop("api_key_cipher", None)
        row["secret_present"] = str(row.get("secret_present") or "N").upper() == "Y"
    return rows


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
                tx.execute(
                    "UPDATE CX_LLM_PROVIDER_PROFILES SET PROVIDER_URL=:url,MODEL_ID=:model,API_KEY_CIPHER=:cipher,"
                    "SECRET_PRESENT=:secret,APPROVED_FOR_JSON=:approved,VERSION=VERSION+1,UPDATED_BY=:actor,"
                    "UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
                    params,
                )
            else:
                tx.execute(
                    "UPDATE CX_LLM_PROVIDER_PROFILES SET PROVIDER_URL=:url,MODEL_ID=:model,APPROVED_FOR_JSON=:approved,"
                    "VERSION=VERSION+1,UPDATED_BY=:actor,UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
                    params,
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


def _policy_row() -> Dict[str, Any]:
    row = _row(connection.execute_query_one(
        "SELECT POLICY_KEY,STATE,VERSION,UPDATED_BY,REASON,UPDATED_AT FROM CX_EXTERNAL_AGENT_POLICY "
        "WHERE POLICY_KEY=:key", {"key": EXTERNAL_REGISTRATION_KEY},
    ))
    if not row:
        raise NativeAgentError("external Agent registration policy is unavailable")
    return row


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
