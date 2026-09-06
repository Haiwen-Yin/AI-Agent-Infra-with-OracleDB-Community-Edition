from pathlib import Path
import json
import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODE = (ROOT / "build-manifest.json").is_file() and not (ROOT / "adapters").is_dir()
DATABASE_KEY = (
    str(json.loads((ROOT / "build-manifest.json").read_text(encoding="ascii"))["database"]["key"])
    if PACKAGE_MODE else None
)
LIB_ROOT = ROOT / ("scripts/lib" if PACKAGE_MODE else "shared/lib")
WEB_APP_PATH = ROOT / ("scripts/web_app.py" if PACKAGE_MODE else "shared/web_app.py")
UI_PATH = ROOT / ("web/src/App.tsx" if PACKAGE_MODE else "shared/web/src/App.tsx")
PORTAL_TEMPLATE_PATH = ROOT / (
    "scripts/visualization/templates/portal_chat.html"
    if PACKAGE_MODE else "shared/visualization/templates/portal_chat.html"
)
VISUALIZATION_SERVER_PATH = ROOT / (
    "scripts/visualization/server.py"
    if PACKAGE_MODE else "shared/visualization/server.py"
)
NODE_TOOL_PATH = ROOT / ("scripts/agent_pool_node.py" if PACKAGE_MODE else "shared/scripts/agent_pool_node.py")
MIGRATION_RUNNER_PATH = ROOT / ("scripts/migration_runner.py" if PACKAGE_MODE else "migration_runner.py")


def _migration_dir(adapter: str) -> Path:
    if PACKAGE_MODE:
        if adapter != DATABASE_KEY:
            pytest.skip(f"{adapter} migration is validated by its generated package")
        return ROOT / "scripts" / "deploy"
    return ROOT / "adapters" / adapter / "deploy"


def test_v444_migrations_exist_for_all_adapters():
    for adapter in ("oracle", "pg", "yashandb"):
        deploy = _migration_dir(adapter)
        path = deploy / "40_v4_4_4_agent_pool_cloud.sql"
        assert path.is_file()
        text = path.read_text(encoding="utf-8").upper()
        assert "CX_PORTAL_LLM_POLICIES" in text
        assert "CX_PLATFORM_ADMIN_COMMANDS" in text
        assert "CX_MANAGED_NODES" in text
        assert "CX_SHARED_STORAGE_PROFILES" in text
        assert "CX_MANAGED_NODE_STORAGE_BINDINGS" in (deploy / "41_v4_4_4_node_storage_binding.sql").read_text(encoding="utf-8").upper()
        purpose = (deploy / "42_v4_4_4_storage_purpose.sql").read_text(encoding="utf-8").upper()
        assert "STORAGE_PURPOSE" in purpose
        onboarding = (deploy / "43_v4_4_4_agent_pool_node_onboarding.sql").read_text(encoding="utf-8").upper()
        assert "CX_AGENT_POOL_NODE_ONBOARDINGS" in onboarding
        assert "TOKEN_DIGEST" in onboarding
        assert "CX_EXTERNAL_DB_ENDPOINTS" in text
        local_path = (deploy / "44_v4_4_4_managed_node_local_info_path.sql").read_text(encoding="utf-8").upper()
        assert "AGENT_INFO_PATH" in local_path
        assert "AGENT_POOL_AGENT_RUNTIME" in local_path


def test_v444_service_never_accepts_arbitrary_command_types():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    assert '"HEALTH_READ"' in source
    assert '"AGENT_QUARANTINE"' in source
    assert "UNKNOWN_PLATFORM_COMMAND" in source
    assert "COMMAND_PARAMETER_REQUIRED" in source
    assert "COMMAND_REASON_REQUIRED" in source
    assert "PENDING_APPROVAL" in source
    assert "create_action_card" in source
    assert "execute_read_command" in source
    assert "reason" in source


def test_v444_portal_selector_is_allowlist_bound_and_secret_free():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    assert "portal_llm_options" in source
    assert "PROFILE_KEY,MODEL_ID,HEALTH_STATE" in source
    assert "API_KEY_CIPHER" not in source.split("def portal_llm_options", 1)[1].split("def set_portal_llm_policy", 1)[0]
    template = PORTAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "/portal/api/llm-profiles" in template
    assert "/portal/api/llm-profile/select" in template


def test_portal_llm_control_plane_reads_clear_agent_context():
    source = VISUALIZATION_SERVER_PATH.read_text(encoding="utf-8")
    for function in (
        source.split("def _handle_portal_llm_select", 1)[1].split("def _portal_selected_llm", 1)[0],
        source.split("def _portal_selected_llm", 1)[1].split("def _handle_portal_chat_send", 1)[0],
        source.split("elif path == '/portal/api/llm-profiles':", 1)[1].split("elif path == '/portal/api/agent/status':", 1)[0],
    ):
        assert "connection.set_agent_context(None)" in function
        assert "connection.get_current_agent_id()" in function


def test_v444_node_credentials_are_not_part_of_persisted_contract(monkeypatch):
    try:
        from shared.lib import platform_agent_pool as pool
    except ModuleNotFoundError:
        from lib import platform_agent_pool as pool
    captured = []
    class Transaction:
        def execute(self, sql, binds):
            captured.append((sql, dict(binds)))
            return 1
    monkeypatch.setattr(pool, "_require_admin", lambda *_: None)
    monkeypatch.setattr(pool.connection, "execute_transaction_callback", lambda fn: fn(Transaction()))
    monkeypatch.setattr(pool.identity_api, "_audit_tx", lambda *args: captured.append(args[1:]))
    result = pool.register_node("admin", {
        "node_key": "test-node", "host_reference": "node.example.invalid",
        "reason": "regression test", "trust_mode": "ONE_USE_PASSWORD",
        "ssh_password": "sentinel-one-use-secret", "roles": [],
    })
    persisted = repr(captured) + repr(result)
    assert "sentinel-one-use-secret" not in persisted
    assert "ssh_password" not in persisted
    assert "ONE_USE_PASSWORD" in persisted
    assert "ROLE_JSON" in persisted


def test_v444_managed_resources_have_governed_retirement_contracts():
    pool = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    native = (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")
    web = WEB_APP_PATH.read_text(encoding="utf-8")
    ui = UI_PATH.read_text(encoding="utf-8")
    assert "def retire_node" in pool
    assert "FROM CX_MANAGED_NODES WHERE STATUS <> 'RETIRED'" in pool
    assert "WHERE n.STATUS <> 'RETIRED' ORDER BY o.CREATED_AT DESC" in pool
    assert "AND n.STATUS <> 'RETIRED' ORDER BY b.CREATED_AT DESC" in pool
    assert "SYSTEM_BOOTSTRAP" in pool
    assert "MANAGED_NODE_RETIRE" in pool
    assert "CX_RUNTIME_WORKERS" in pool and "CX_RUNTIME_EXECUTIONS" in pool
    assert "CX_ADMIN_AGENT_MEMBERS" in pool
    assert "def execute_approved_command" in pool
    assert "STATUS='DRAINING'" in pool
    assert "requeued_expired_tasks" in pool
    assert "def retire_llm_profile" in native
    assert "FROM CX_LLM_PROVIDER_PROFILES WHERE STATUS <> 'RETIRED'" in native
    assert "LLM_PROFILE_RETIRE" in native
    assert "CX_PORTAL_LLM_ALLOWLIST" in native
    assert "CX_NATIVE_PROVISION_REQUESTS" in native
    assert "class LLMProfileInUse" in native
    assert "LLM_PROFILE_IN_USE:" in native
    assert '@app.delete("/api/platform/managed-nodes/{node_id}")' in web
    assert '@app.delete("/api/llm-provider-profiles/{profile_id}")' in web
    assert 'method: "DELETE"' in ui
    assert "系统节点，不可移除" in ui


def test_llm_profile_form_keeps_a_stable_form_reference_across_await():
    ui = UI_PATH.read_text(encoding="utf-8")
    submit = ui.split("const saveProfile = async", 1)[1].split("const probe = async", 1)[0]
    assert "const formElement = event.currentTarget" in submit
    assert "formElement.reset()" in submit
    assert "event.currentTarget.reset()" not in submit
    assert "LLM_PROFILE_IN_USE:" in ui


def test_v444_management_channel_drain_is_typed_and_approval_bound():
    native = (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")
    web = WEB_APP_PATH.read_text(encoding="utf-8")
    assert 'command_type == "AGENT_DRAIN"' in native
    assert "source node, destination node, and reason" in native
    assert "execute_approved_command" in web


def test_v444_local_agent_directory_is_resolved_and_bootstrap_discovered():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    web = WEB_APP_PATH.read_text(encoding="utf-8")
    ui = UI_PATH.read_text(encoding="utf-8")
    assert 'AI-Agent-Infra-with-DB' in source
    assert "def resolve_agent_info_path" in source
    assert "MANAGED_NODE_LOCAL_PATH_DISCOVER" in source
    assert 'deployment_dir = module_dir.parent if module_dir.name == "scripts" else module_dir' in web
    assert "agent_info_path=str(deployment_dir)" in web
    assert "LocalAgentPathField" in ui
    assert "Resolved storage directory" in ui


def test_v444_pool_host_onboarding_is_token_bound_and_requires_storage():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    assert "def create_node_onboarding" in source
    assert "def node_onboarding_checkin" in source
    assert "def activate_node_onboarding" in source
    assert "def node_onboarding_heartbeat" in source
    assert "bootstrap_token" in source
    assert "TOKEN_DIGEST" in source
    assert "AGENT_POOL_RUNTIME" in source
    assert "AGENT_INFO_PATH" in source
    assert "local Agent information directory" in source
    tool = NODE_TOOL_PATH.read_text(encoding="utf-8")
    assert "/api/agent-pool/node-onboardings/" in tool
    assert "--token" in tool
    assert "--agent-info-path" in tool


def test_v444_template_seed_keys_are_present():
    required = {"CODE_PLAN", "CODE_PROGRAM", "CODE_REVIEW", "OFFICE_TEXT", "PPT_DESIGN"}
    for adapter in ("oracle", "pg", "yashandb"):
        text = (_migration_dir(adapter) / "40_v4_4_4_agent_pool_cloud.sql").read_text(encoding="utf-8")
        for key in required:
            assert key in text


def test_v444_runtime_streams_deltas_without_repeating_accumulated_output():
    source = (LIB_ROOT / "native_runtime.py").read_text(encoding="utf-8")
    assert "pending += piece" in source
    assert "on_delta(pending)" in source
    assert "on_delta(content)" not in source
    assert "no active LLM Provider Profile" in source


def test_v444_channel_uses_explicit_typed_platform_command_path():
    source = (LIB_ROOT / "native_agent_api.py").read_text(encoding="utf-8")
    assert 'startswith("/platform ")' in source
    assert "create_command" in source
    assert "ordinary prose" in source


def test_v444_endpoint_policy_snapshot_binding_and_rate_limit_are_present():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    assert "POLICY_SNAPSHOT" in source
    assert "database_endpoint_id" in source
    assert "endpoint discovery rate limit exceeded" in source
    assert "len(recent) >= 30" in source


def test_v444_node_storage_binding_is_governed_and_scoped():
    source = (LIB_ROOT / "platform_agent_pool.py").read_text(encoding="utf-8")
    assert "list_node_storage_bindings" in source
    assert "NODE_STORAGE_BIND" in source
    assert "ALL_PLATFORM_AGENTS" in source
    assert "storage binding is unavailable" in source


def test_v444_agent_pool_is_a_platform_configuration_subpage():
    ui = UI_PATH.read_text(encoding="utf-8")
    api = WEB_APP_PATH.read_text(encoding="utf-8")
    nav = ui.split("const nav = [", 1)[1].split("];", 1)[0]
    assert '"agent-pool"' not in nav
    assert '"agent-pool", "Agent Pool 配置"' in ui
    assert "pool-llm-allowlist" in ui
    assert "pool-config-stack" in ui
    assert "Admin Agent 运行节点共享目录绑定" in ui
    pages = api.split("pages = {", 1)[1].split("feature_map =", 1)[0]
    assert '"agent-pool"' not in pages
    assert "ADMIN_RUNTIME" in ui and "AGENT_POOL_RUNTIME" in ui
    assert "Agent Pool 运行时共享目录绑定" in ui
    assert "本地 Agent 信息目录" in ui
    assert "storage_purpose" in ui


def test_v444_runner_selects_the_additive_host_onboarding_step():
    runner = MIGRATION_RUNNER_PATH.read_text(encoding="utf-8")
    selected = runner.split("def _v444_script_names", 1)[1].split("def _prepare_migration", 1)[0]
    assert 'names.append("43_v4_4_4_agent_pool_node_onboarding.sql")' in selected
    assert 'names.append("44_v4_4_4_managed_node_local_info_path.sql")' in selected
