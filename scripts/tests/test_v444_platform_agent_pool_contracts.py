from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v444_migrations_exist_for_all_adapters():
    for adapter in ("oracle", "pg", "yashandb"):
        path = ROOT / "adapters" / adapter / "deploy" / "40_v4_4_4_agent_pool_cloud.sql"
        assert path.is_file()
        text = path.read_text(encoding="utf-8").upper()
        assert "CX_PORTAL_LLM_POLICIES" in text
        assert "CX_PLATFORM_ADMIN_COMMANDS" in text
        assert "CX_MANAGED_NODES" in text
        assert "CX_SHARED_STORAGE_PROFILES" in text
        assert "CX_MANAGED_NODE_STORAGE_BINDINGS" in (ROOT / "adapters" / adapter / "deploy" / "41_v4_4_4_node_storage_binding.sql").read_text(encoding="utf-8").upper()
        purpose = (ROOT / "adapters" / adapter / "deploy" / "42_v4_4_4_storage_purpose.sql").read_text(encoding="utf-8").upper()
        assert "STORAGE_PURPOSE" in purpose
        assert "CX_EXTERNAL_DB_ENDPOINTS" in text


def test_v444_service_never_accepts_arbitrary_command_types():
    source = (ROOT / "shared/lib/platform_agent_pool.py").read_text(encoding="utf-8")
    assert '"HEALTH_READ"' in source
    assert '"AGENT_QUARANTINE"' in source
    assert "unsupported command or missing reason" in source
    assert "PENDING_APPROVAL" in source
    assert "create_action_card" in source
    assert "execute_read_command" in source
    assert "reason" in source


def test_v444_portal_selector_is_allowlist_bound_and_secret_free():
    source = (ROOT / "shared/lib/platform_agent_pool.py").read_text(encoding="utf-8")
    assert "portal_llm_options" in source
    assert "PROFILE_KEY,MODEL_ID,HEALTH_STATE" in source
    assert "API_KEY_CIPHER" not in source.split("def portal_llm_options", 1)[1].split("def set_portal_llm_policy", 1)[0]
    template = (ROOT / "shared/visualization/templates/portal_chat.html").read_text(encoding="utf-8")
    assert "/portal/api/llm-profiles" in template
    assert "/portal/api/llm-profile/select" in template


def test_v444_node_credentials_are_not_part_of_persisted_contract():
    source = (ROOT / "shared/lib/platform_agent_pool.py").read_text(encoding="utf-8")
    assert "ssh_password" not in source
    assert "ONE_USE_PASSWORD" in source
    assert "ROLE_JSON" in source


def test_v444_template_seed_keys_are_present():
    required = {"CODE_PLAN", "CODE_PROGRAM", "CODE_REVIEW", "OFFICE_TEXT", "PPT_DESIGN"}
    for adapter in ("oracle", "pg", "yashandb"):
        text = (ROOT / "adapters" / adapter / "deploy" / "40_v4_4_4_agent_pool_cloud.sql").read_text(encoding="utf-8")
        for key in required:
            assert key in text


def test_v444_runtime_streams_deltas_without_repeating_accumulated_output():
    source = (ROOT / "shared/lib/native_runtime.py").read_text(encoding="utf-8")
    assert "on_delta(piece)" in source
    assert "on_delta(content)" not in source
    assert "no active LLM Provider Profile" in source


def test_v444_channel_uses_explicit_typed_platform_command_path():
    source = (ROOT / "shared/lib/native_agent_api.py").read_text(encoding="utf-8")
    assert 'startswith("/platform ")' in source
    assert "create_command" in source
    assert "ordinary prose" in source


def test_v444_endpoint_policy_snapshot_binding_and_rate_limit_are_present():
    source = (ROOT / "shared/lib/platform_agent_pool.py").read_text(encoding="utf-8")
    assert "POLICY_SNAPSHOT" in source
    assert "database_endpoint_id" in source
    assert "endpoint discovery rate limit exceeded" in source
    assert "len(recent) >= 30" in source


def test_v444_node_storage_binding_is_governed_and_scoped():
    source = (ROOT / "shared/lib/platform_agent_pool.py").read_text(encoding="utf-8")
    assert "list_node_storage_bindings" in source
    assert "NODE_STORAGE_BIND" in source
    assert "ALL_PLATFORM_AGENTS" in source
    assert "storage binding is unavailable" in source


def test_v444_agent_pool_is_a_platform_configuration_subpage():
    ui = (ROOT / "shared/web/src/App.tsx").read_text(encoding="utf-8")
    api = (ROOT / "shared/web_app.py").read_text(encoding="utf-8")
    nav = ui.split("const nav = [", 1)[1].split("];", 1)[0]
    assert '"agent-pool"' not in nav
    assert '"agent-pool", "Agent Pool 配置"' in ui
    assert "pool-llm-allowlist" in ui
    assert "pool-config-stack" in ui
    assert "Admin Agent 运行节点共享目录绑定" in ui
    pages = api.split("pages = {", 1)[1].split("feature_map =", 1)[0]
    assert '"agent-pool"' not in pages
    assert "ADMIN_RUNTIME" in ui and "AGENT_POOL_RUNTIME" in ui
    assert "Admin Agent 运行信息目录绑定" in ui
    assert "Agent Pool 运行时目录绑定" in ui
    assert "storage_purpose" in ui
