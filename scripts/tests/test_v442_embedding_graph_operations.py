from pathlib import Path
from typing import Any

import pytest

import live_db_validator
from lib import graph_production_profile, knowledge_api

ROOT = Path(__file__).resolve().parents[2]
GENERATED_COMMUNITY = False
if (ROOT / "build-manifest.json").is_file():
    import json

    GENERATED_COMMUNITY = json.loads(
        (ROOT / "build-manifest.json").read_text(encoding="utf-8")
    ).get("edition") == "Community"


def _adapter_scripts(names: tuple[str, ...] | list[str]):
    root = Path(__file__).resolve().parents[2]
    if (root / "adapters").is_dir():
        return [
            (database, [root / "adapters" / database / "deploy" / name for name in names])
            for database in ("oracle", "pg", "yashandb")
        ]
    manifest = root / "build-manifest.json"
    assert manifest.is_file(), "generated package must include build-manifest.json"
    import json

    database = str(json.loads(manifest.read_text(encoding="utf-8"))["database"]["key"])
    return [(database, [root / "scripts" / "deploy" / name for name in names])]


@pytest.mark.skipif(
    GENERATED_COMMUNITY,
    reason="the historical full-chain validator requires Enterprise-only governance migrations",
)
def test_v442_static_contract_is_complete_for_all_adapters():
    for database, scripts in _adapter_scripts(live_db_validator.V442_MIGRATION_SCRIPTS):
        result = live_db_validator.validate_v442_static_contract(database, scripts)
        assert result["passed"] is True
        assert result["v442_operations"]["no_plaintext_secret_markers"] is True


def test_channel_pinning_migration_is_additive_for_all_adapters():
    for _database, scripts in _adapter_scripts(("38_v4_4_2_channel_pinning.sql",)):
        source = scripts[0].read_text(encoding="utf-8")
        assert "PINNED" in source.upper()
        assert "IDX_CX_CHANNEL_PIN_ACTIVITY" in source.upper()


def test_graph_matrix_rejects_disabled_and_requires_controlled_access(monkeypatch):
    rows = [
        {"profile_key": "PRODUCTION", "capability_key": key, "state": "DISABLED" if key == "a2a_gateway" else "ENABLED", "version": 1}
        for key in graph_production_profile.CAPABILITIES
    ]
    monkeypatch.setattr(graph_production_profile.connection, "execute_query", lambda *_args, **_kwargs: rows)
    with pytest.raises(graph_production_profile.ProfileConflict, match="disabled"):
        graph_production_profile.require("a2a_gateway")
    rows[-1]["state"] = "CONTROLLED"
    controlled_key = list(graph_production_profile.CAPABILITIES)[-1]
    with pytest.raises(graph_production_profile.ProfileConflict, match="controlled"):
        graph_production_profile.require(controlled_key)
    assert graph_production_profile.require(controlled_key, controlled=True) == "CONTROLLED"


class _Tx:
    def __init__(self):
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def query_one(self, sql: str, params: dict[str, Any]):
        if "CX_GRAPH_CAPABILITY_MATRIX" in sql:
            return {"state": "DISABLED", "version": 2, "mandatory": "N"}
        return None

    def execute(self, sql: str, params: dict[str, Any]):
        self.executed.append((sql, params))
        return 1


def test_graph_matrix_stale_update_is_rejected_without_writes(monkeypatch):
    tx = _Tx()
    monkeypatch.setattr(graph_production_profile.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(graph_production_profile.ProfileConflict, match="concurrently"):
        graph_production_profile.set_state("admin", "a2a_gateway", "CONTROLLED", "controlled test", 1, "evidence://test")
    assert tx.executed == []


def test_graph_promotion_requires_evidence(monkeypatch):
    with pytest.raises(graph_production_profile.ProfileConflict, match="evidence"):
        graph_production_profile.set_state("admin", "a2a_gateway", "CONTROLLED", "promotion test", 1)


def test_graph_promotion_rejects_disabled_dependency(monkeypatch):
    class DependencyTx(_Tx):
        def query_one(self, sql: str, params: dict[str, Any]):
            if "CAPABILITY_KEY=:key" in sql and params.get("key") == "a2a_gateway":
                return {"state": "DISABLED", "version": 1, "mandatory": "N"}
            if "CAPABILITY_KEY=:key" in sql and params.get("key") == "graph_runtime_core":
                return {"state": "DISABLED", "version": 1, "mandatory": "Y"}
            return None

    tx = DependencyTx()
    monkeypatch.setattr(graph_production_profile.connection, "execute_transaction_callback", lambda work: work(tx))
    with pytest.raises(graph_production_profile.ProfileConflict, match="dependency"):
        graph_production_profile.set_state("admin", "a2a_gateway", "CONTROLLED", "promotion test", 1, "evidence://test")
    assert tx.executed == []


def test_graph_capability_route_keeps_governed_updates_but_runtime_profiles_locked():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web_app.py").read_text(encoding="utf-8")
    route = app.split('@app.put("/api/platform/graph-capabilities/{capability_key}")', 1)[1].split('@app.get("/api/platform/administration")', 1)[0]
    assert "graph_production_profile.set_state" in route
    assert "expected_version" in route and "evidence_ref" in route
    assert "cannot be changed at runtime" not in route
    assert 'Experimental runtime profiles are unavailable in the Production configuration' in app


def test_llm_draft_probe_is_ephemeral_and_dashboard_requires_it_before_save():
    root = Path(__file__).resolve().parents[1]
    api_source = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    app = (root / "web_app.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    probe = api_source.split("def probe_llm_profile", 1)[1].split("def _policy_row", 1)[0]
    assert '"max_tokens": 1' in probe
    assert "LLM_PROFILE_DRAFT_PROBE" in probe
    assert "API_KEY_CIPHER" not in probe
    assert '@app.post("/api/llm-provider-profiles/probe-draft")' in app
    profiles = ui.split("function LLMProviderProfilesPanel", 1)[1].split("function PlatformOperationsPage", 1)[0]
    assert '"/api/llm-provider-profiles/probe-draft"' in profiles
    assert "testedVersion !== draftVersion" in profiles
    assert 'tab === "llm-providers"' in ui


def test_channel_mentions_are_member_bounded_and_message_display_uses_name():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    messages = identity.split("def post_channel_message", 1)[1].split("def _enqueue_channel_deliveries", 1)[0]
    listing = identity.split("def list_channel_messages", 1)[1].split("def channel_summary", 1)[0]
    channels = ui.split("function Channels", 1)[1].split("function BarriersPage", 1)[0]
    assert "mentioned principal is outside the Channel" in messages
    assert "_channel_principal_is_member(channel_id, subject)" in messages
    assert "COALESCE(p.DISPLAY_NAME, m.PRINCIPAL_ID) AS SENDER_DISPLAY_NAME" in listing
    assert "sender_display_name" in channels
    assert "onKeyDown" in channels and "event.key === \"Enter\" && !event.shiftKey" in channels
    assert "references: mentions.length ? { mentions } : {}" in channels
    assert "mention-menu" in channels and "查看主体信息" in channels


def test_native_management_agents_have_readable_principal_display_names():
    root = Path(__file__).resolve().parents[1]
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    assert 'return "Platform Admin Agent"' in native
    assert 'return "Compliance Admin Agent"' in native
    assert "DISPLAY_NAME=:display_name" in native
    native_agent = native.split("def _ensure_native_agent", 1)[1].split("def bootstrap_native_agents", 1)[0]
    assert native_agent.index("_ensure_principal(tx, agent_id)") < native_agent.index("if existing:")
    bootstrap = native.split("def bootstrap_native_agents", 1)[1]
    assert bootstrap.index("_ensure_principal(tx, PLATFORM_ADMIN_AGENT_ID)") < bootstrap.index('return {"status": "COMPLETED"')


def test_frontend_uses_verified_platform_activation_and_enforced_normalization():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    app = (root / "web_app.py").read_text(encoding="utf-8")
    assert "/api/embedding/platform/activate" in ui
    assert 'normalize_vectors: true' in ui
    assert 'className="derived-value enforced-value"' in ui
    assert '@app.post("/api/embedding/platform/activate")' in app


def test_frontend_localizes_fastapi_validation_and_unknown_api_errors():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "function validationMessage(detail: unknown, lang: Lang)" in ui
    assert 'reason: ["变更原因", "change reason"]' in ui
    assert '"请填写变更原因。"' in ui
    assert '"请求内容不符合要求，请检查必填项和格式。"' in ui
    assert '"当前账号没有执行此操作的权限。"' in ui
    assert '"当前版本未提供该功能接口。"' in ui
    assert '"用户名或密码错误，或账号暂时锁定。"' in ui


def test_v442_dashboard_removes_manual_embedding_operations_and_keeps_forms_labeled():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert 'name="agent_name" required' in ui
    assert 'defaultValue="OpenClaw / Hermes"' not in ui
    assert 'aria-label={text("功能配置分区", "Capability configuration sections")}' in ui
    assert 'text("自动化结果", "Automated results")' in ui
    assert 'text("创建契约", "Create Contract")' not in ui
    assert 'text("创建空间", "Create Space")' not in ui
    assert 'text("保存绑定", "Save binding")' not in ui
    assert 'text("加入队列", "Queue job")' not in ui
    assert 'name="profile_key" required placeholder' not in ui
    assert "function useUrlState" in ui
    assert '"section"' in ui
    assert 'platformTabKeys' in ui


def test_v442_dashboard_automates_embedding_activation_and_uses_named_external_agents():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    probe = ui.split('const testProfile = async () =>', 1)[1].split('const profiles =', 1)[0]
    assert '"/api/embedding/platform/activate"' in probe
    assert "observed_dimension" in probe
    assert 'text("测试并自动配置", "Test and configure")' in ui
    assert 'text("智能体名称", "Agent name")' in ui
    assert 'item.agent_name || "-"' in ui
    assert 'text("运行时", "Runtime")' not in ui
    assert ".cursor-pager" in css and "flex-wrap: nowrap" in css
    deployment = ui.split("function DeploymentModelsPage", 1)[1].split("function NativeAgentsPage", 1)[0]
    assert '<input name="dimension"' not in deployment
    assert "待测试" in deployment
    assert "admin-admission-form" in ui and "placeholder={text(\"目标节点 ID\"" not in ui


def test_v442_embedding_manual_write_routes_are_not_mounted_and_knowledge_graph_is_principal_scoped():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web_app.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert '@app.post("/api/embedding/profiles")' not in app
    assert '@app.post("/api/embedding/contracts")' not in app
    assert '@app.post("/api/embedding/spaces")' not in app
    assert '@app.post("/api/embedding/bindings")' not in app
    assert '@app.post("/api/embedding/jobs")' not in app
    assert '@app.get("/api/knowledge")' in app
    assert 'Depends(require_action("knowledge.read"))' in app
    assert '"/api/knowledge?limit=200"' in ui
    assert "automation-boundary" in ui


def test_v442_external_redemption_does_not_prefill_runtime():
    root = Path(__file__).resolve().parents[1]
    web_app = (root / "web_app.py").read_text(encoding="utf-8")
    assert 'class EnrollmentBody(BaseModel):' in web_app
    enrollment = web_app.split('class EnrollmentBody(BaseModel):', 1)[1].split('class GrantBody', 1)[0]
    assert 'runtime: str = Field(default="", max_length=128)' in enrollment
    assert 'runtime: str = Field(default="generic"' not in enrollment


def test_v442_dashboard_grant_is_named_and_never_binds_runtime():
    root = Path(__file__).resolve().parents[1]
    web_app = (root / "web_app.py").read_text(encoding="utf-8")
    grant = web_app.split('class GrantBody(BaseModel):', 1)[1].split('class ChannelBody', 1)[0]
    route = web_app.split('@app.post("/api/enrollment/grants")', 1)[1].split('@app.post("/api/enrollment/redeem")', 1)[0]
    assert 'agent_name: str = Field(min_length=1' in grant
    assert 'runtime:' not in grant
    assert 'runtime="UNSPECIFIED"' in route
    assert "actual runtime during token redemption" in route


def test_v442_external_registration_policy_is_controlled_after_async_load():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    panel = ui.split("function ExternalRegistrationPolicyPanel", 1)[1].split("function PlatformOperationsPage", 1)[0]
    assert 'const [state, setState] = useState("")' in panel
    assert 'const [loaded, setLoaded] = useState(false)' in panel
    assert 'setState(String(value.state || "DISABLED").toUpperCase())' in panel
    assert 'setLoaded(true)' in panel
    assert 'value={state} disabled={!loaded} onChange={(event) => setState(event.target.value)}' in panel
    assert 'defaultValue={String(policy.state || "ENABLED")}' not in panel
    assert 'name="runtime"' not in panel


def test_v442_all_cursor_pagers_are_single_line():
    root = Path(__file__).resolve().parents[1]
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert ".pager-size-control" in css
    assert "flex-wrap: nowrap" in css
    assert "overflow-x: auto" in css
    assert "min-height: 28px" in css
    assert 'className="pager-page-status"' in ui
    assert 'text(`${page} / ${totalPages} 页`, `${page} / ${totalPages}`)' in ui
    assert "width: 48px" in css


def test_v442_external_registration_is_agent_named_and_never_runtime_prefilled():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    external = ui.split("const externalRegistration =", 1)[1].split('if (view === "native")', 1)[0]
    assert 'text("外部注册策略", "External registration policy")' in external
    assert 'text("智能体名称", "Agent name")' in external
    assert 'name="runtime"' not in external
    assert 'text("运行时", "Runtime")' not in external
    assert 'className="pager-size-control"' in ui


def test_v442_external_status_does_not_render_runtime_as_a_registration_field():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    external = ui.split("const externalRegistration =", 1)[1].split('if (view === "native")', 1)[0]
    status = external.split('title={text("外部注册策略"', 1)[1].split('</InfoPanel>', 1)[0]
    assert 'name="runtime"' not in status
    assert 'name="agent_name"' not in status
    assert 'agent_name' in external


def test_v442_embedding_inventory_has_no_mutating_dashboard_controls():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    deployment = ui.split("function DeploymentModelsPage", 1)[1].split("function NativeAgentsPage", 1)[0]
    assert 'text("创建契约", "Create Contract")' not in deployment
    assert 'text("创建空间", "Create Space")' not in deployment
    assert 'text("保存绑定", "Save binding")' not in deployment
    assert 'text("加入队列", "Queue job")' not in deployment
    assert '自动测试并配置' in deployment


def test_v442_public_embedding_write_surface_has_one_automated_activation_path():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web_app.py").read_text(encoding="utf-8")
    assert '@app.post("/api/embedding/platform/activate")' in app
    for path in ("profiles", "contracts", "spaces", "bindings", "jobs"):
        assert f'@app.post("/api/embedding/{path}")' not in app


def test_v442_form_labels_and_multiline_fields_are_stable_and_external_agent_form_is_named():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    external = ui.split("const externalRegistration =", 1)[1].split("if (view === \"native\")", 1)[0]
    assert 'name="agent_name" autoComplete="off" required' in external
    assert 'name="runtime"' not in external
    assert 'name="agent_name" required' in ui
    assert 'name="purpose" required' in ui
    assert 'name="profile_key" required' in ui
    forms = ui.split("function DeploymentModelsPage", 1)[1].split("function NativeAgentsPage", 1)[0]
    forms += ui.split("function CompliancePage", 1)[1].split("function AgentsPage", 1)[0]
    assert "placeholder=" not in forms
    assert '.config-field > span {' in css
    assert '.config-field.config-multiline {' in css
    assert 'grid-template-rows: 16px 62px minmax(22px, auto)' in css
    assert '.config-field > textarea {' in css


def test_v442_embedding_results_are_read_only_and_activation_is_the_single_write_path():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    deployment = ui.split("function DeploymentModelsPage", 1)[1].split("function NativeAgentsPage", 1)[0]
    assert '"/api/embedding/platform/activate"' in deployment
    assert '"/api/embedding/profiles/probe-draft"' in deployment
    assert "自动化结果" in deployment
    assert "不提供手工创建、修改或补偿入口" in deployment
    for inventory_path in (
        "/api/embedding/contracts?limit=100",
        "/api/embedding/spaces?limit=100",
        "/api/embedding/bindings?limit=100",
        "/api/embedding/jobs?limit=100",
    ):
        assert inventory_path in deployment  # read-only inventory endpoints only
    assert 'method: "POST", body: JSON.stringify(draft)' in deployment


def test_v442_embedding_activation_explains_automatic_maintenance_and_no_manual_followup():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    deployment = ui.split("function DeploymentModelsPage", 1)[1].split("function NativeAgentsPage", 1)[0]
    assert "不存在后续手工创建契约、空间、绑定或迁移任务的步骤" in deployment
    assert "以下为只读状态，不提供手工创建、修改或补偿入口" in deployment
    assert 'name="dimension"' not in deployment


def test_v442_knowledge_inventory_paths_keep_authenticated_principal(monkeypatch):
    captured = []
    monkeypatch.setattr(knowledge_api.cursor_pagination, "resolve", lambda *_args: {
        "position": {}, "page_size": 20, "filter_digest": "knowledge-test",
    })
    monkeypatch.setattr(knowledge_api.cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    monkeypatch.setattr(knowledge_api.identity_api, "effective_access", lambda *_args: {"decision": "DENY"})
    monkeypatch.setattr(knowledge_api.identity_api, "_agent_visibility_clause", lambda *_args: "SCOPE_CLAUSE(:principal_id)")
    monkeypatch.setattr(knowledge_api, "execute_query", lambda sql, params: captured.append((sql, params)) or [])

    knowledge_api.search_knowledge(principal_id="human-1")
    knowledge_api.search_knowledge_cursor("human-1")

    assert len(captured) == 2
    for sql, params in captured:
        assert "SCOPE_CLAUSE" in sql
        assert params["principal_id"] == "human-1"


def test_v442_knowledge_inventory_omits_unused_principal_bind_for_constant_scope(monkeypatch):
    captured = []
    monkeypatch.setattr(knowledge_api.cursor_pagination, "resolve", lambda *_args: {
        "position": {}, "page_size": 20, "filter_digest": "knowledge-test",
    })
    monkeypatch.setattr(knowledge_api.cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    monkeypatch.setattr(knowledge_api.identity_api, "effective_access", lambda *_args: {"decision": "DENY"})
    monkeypatch.setattr(knowledge_api.identity_api, "_agent_visibility_clause", lambda *_args: "1=1")
    monkeypatch.setattr(knowledge_api, "execute_query", lambda sql, params: captured.append((sql, params)) or [])

    knowledge_api.search_knowledge(principal_id="admin")
    knowledge_api.search_knowledge_cursor("admin")

    assert len(captured) == 2
    assert all(":principal_id" not in sql for sql, _params in captured)
    assert all("principal_id" not in params for _sql, params in captured)


def test_v442_separates_platform_operations_and_expands_admin_target_contract():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    api = (root / "web_app.py").read_text(encoding="utf-8")
    management = (root / "lib" / "admin_management.py").read_text(encoding="utf-8")
    assert 'function PlatformConfigurationPage' in ui
    assert '"config"' in ui
    assert '["agent-pool", "Agent Pool 配置"' in ui
    assert '"agent-pool", "Agent Pool 配置"' not in ui.split("const nav = [", 1)[1].split("];", 1)[0]
    assert "pool-llm-allowlist" in ui
    assert "pool-config-stack" in ui
    assert "host_reference" in ui and "ssh_port" in ui and "os_user" in ui
    assert "ssh_trust_mode" in api and "ssh_password" in api
    assert "password_persisted" in management
    assert "PENDING_ADAPTER_VERIFICATION" in management
    platform_page = ui.split("function PlatformCapabilitiesPage", 1)[1].split("function ExternalRegistrationPolicyPanel", 1)[0]
    assert 'activeTab === "administration"' not in platform_page or "false &&" in platform_page
    assert 'activeTab === "upgrade"' not in platform_page or "false &&" in platform_page


def test_v442_platform_operations_page_is_exposed_to_platform_managers():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web_app.py").read_text(encoding="utf-8")
    pages = app.split('pages = {', 1)[1].split('feature_map =', 1)[0]
    assert '"platform-operations": "platform.manage"' in pages


def test_v442_compliance_draft_is_structured_and_forms_do_not_use_instructional_placeholders():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "allowed_skills" in ui and "allowed_tools" in ui
    assert "classification_ceiling" in ui and "database_access" in ui
    assert "network_egress" in ui and "approval_policy" in ui and "audit_retention" in ui
    assert 'name="profile_key" required placeholder' not in ui
    assert 'name="agent_name" required placeholder' not in ui
    assert 'text("合规控制模板", "Compliance control templates")' in ui
    assert 'text("受管配置", "Governed profiles")' not in ui


def test_v445_platform_child_state_uses_shared_url_state_contract():
    ui = (Path(__file__).parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "function useUrlState" in ui
    assert '"config"' in ui
    assert '"section"' in ui
