"""Contract checks for v4.4.2 managed Agent Channel responses."""

from pathlib import Path


def test_explicit_management_mentions_are_dispatched_but_normal_messages_are_not():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    assert "CHANNEL_MANAGEMENT_AGENT_DISPATCH" in identity
    assert "CH_PLATFORM_ADMINISTRATION" in identity
    assert "create_channel_execution(" in identity
    assert "explicit management Agent mention queued" in native
    assert "platform management permission is required for Channel Agent dispatch" in native
    assert "agent_dispatch_errors" in identity
    assert "client retry create a duplicate request message" in identity


def test_runtime_writes_one_idempotent_agent_response_without_recursive_dispatch():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    assert "_write_channel_response(" in runtime
    assert "post_channel_agent_response(" in runtime
    assert "MSG_AR_" in identity
    assert '"AGENT_RESPONSE"' in identity
    assert "response_to" in identity


def test_protected_management_agents_receive_explicit_default_domain_admission():
    root = Path(__file__).resolve().parents[1]
    management = (root / "lib" / "admin_management.py").read_text(encoding="utf-8")
    assert "management_agents = [native_agent_api.PLATFORM_ADMIN_AGENT_ID]" in management
    assert "CX_DOMAIN_MEMBERS" in management
    assert "their audited reply is rejected" in management


def test_channel_streaming_and_markdown_are_owned_by_the_control_plane():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "_stream_llm(" in runtime
    assert "begin_channel_agent_response(" in identity
    assert "AGENT_RESPONSE_STREAMING" in identity
    assert '"[streaming]"' in identity
    assert "ChannelMarkdown" in ui


def test_channel_inbox_orders_pinned_channels_then_recent_activity_and_admin_gets_safe_status_snapshot():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "pinned:desc/activity:desc/channel_id:asc" in identity
    assert "set_channel_pinned(" in identity
    assert "CHANNEL_PIN_" in identity
    assert "UPDATE CX_CHANNELS SET UPDATED_AT=CURRENT_TIMESTAMP" in identity
    assert "management_status_snapshot(" in native
    assert "credential-free" in native
    assert "messageStreamRef" in ui and "followLatestRef" in ui
    assert "Opening a Channel is an inbox action" in ui
    assert "enabledFlag(selected.pinned)" in ui


def test_channel_background_refresh_preserves_manual_history_scroll_position():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    channels = ui.split("function Channels", 1)[1].split("function BarriersPage", 1)[0]
    assert "onScroll={handleMessageScroll}" in channels
    assert "followLatestRef.current = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 72" in channels
    assert "if (followLatestRef.current)" in channels
    assert "followLatestRef.current || nearBottom" not in channels


def test_cursor_pager_select_keeps_the_selected_number_readable():
    root = Path(__file__).resolve().parents[1]
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    pager = css.split(".cursor-pager {", 1)[1].split(".operation-feedback", 1)[0]
    assert "width: 54px" in pager
    assert "padding: 2px 4px" in pager
    assert "color: var(--ink)" in pager
    assert "background: var(--surface-strong)" in pager


def test_channel_composer_keeps_controls_aligned_when_hints_or_feedback_expand():
    root = Path(__file__).resolve().parents[1]
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    composer = css.split(".message-compose {", 1)[1].split(".message-compose textarea", 1)[0]
    controls = css.split(".compose-controls {", 1)[1].split(".decision-box", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr) minmax(245px, 30%)" in composer
    assert "align-items: start" in composer
    assert "padding-top: 20px" in controls


def test_channel_pinning_route_requires_the_existing_lifecycle_permission():
    root = Path(__file__).resolve().parents[1]
    app = (root / "web_app.py").read_text(encoding="utf-8")
    route = app.split('@app.post("/api/channels/{channel_id}/pin")', 1)[1].split('@app.get("/api/bridges")', 1)[0]
    assert 'Depends(require_action("channels.lifecycle"))' in route
    assert "identity_api.set_channel_pinned" in route


def test_management_channel_system_agents_are_protected_and_pinning_updates_the_ui_immediately():
    root = Path(__file__).resolve().parents[1]
    gateway = (root / "lib" / "agent_gateway_api.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "protected Platform Administration Channel membership is managed" in gateway
    assert 'String(selected.channel_id) === "CH_PLATFORM_ADMINISTRATION"' in ui
    assert 'text("不可移除", "Non-removable")' in ui
    assert "setSelected({ ...selected, pinned: enabled })" in ui
    assert "setChannels((items) => items.map" in ui


def test_channel_ui_distinguishes_discussion_threads_from_channel_members():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert 'text("讨论线程与频道成员", "Discussion Threads and Channel Members")' in ui
    assert "Discussion threads organize message context inside a Channel" in ui
    assert 'className="channel-create-form"' in ui
    assert 'className="channel-create-fields"' in ui
    assert 'className="channel-member-form"' in ui
    assert "频道必须选择已授权的活动安全域" in ui
    assert "请选择已授权的安全域" in ui
    channels = ui.split("function Channels", 1)[1].split("function BarriersPage", 1)[0]
    assert '<input name="security_domain_id"' not in channels


def test_background_sync_and_operation_feedback_use_non_blocking_header_and_toast():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert "cx-request-progress" not in ui
    assert "cx-sync-indicator" in ui
    assert "window.setTimeout(() => setNotice(\"\"), 4800)" in ui
    assert ".cx-notice" in css and "position: fixed;" in css


def test_empty_stream_content_uses_one_bounded_non_streaming_fallback():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    assert 'str(exc) != "LLM provider returned no content"' in runtime
    assert "output = _call_llm(profile" in runtime


def test_status_requests_use_the_database_control_plane_not_model_reconstruction():
    root = Path(__file__).resolve().parents[1]
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    assert "is_management_status_request(" in native
    assert 'payload["management_status_snapshot"]' in native
    assert "_management_status_markdown(" in runtime
    assert '"database-control-plane"' in runtime


def test_health_read_exposes_bounded_control_plane_summary_and_typo_alias():
    root = Path(__file__).resolve().parents[1]
    pool = (root / "lib" / "platform_agent_pool.py").read_text(encoding="utf-8")
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    assert '"managed_nodes"' in pool and '"native_agents"' in pool
    assert '"llm_profiles"' in pool and '"active_executions"' in pool
    assert 'command_type == "HEATH_READ"' in native
    assert 'database_dialect' in runtime and 'checked_at' in runtime


def test_streaming_refresh_does_not_filter_same_message_by_creation_time():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    channels = ui.split("function Channels", 1)[1].split("function BarriersPage", 1)[0]
    assert "refresh the bounded recent window instead" in channels
    assert "messages?limit=100${after}" not in channels


def test_platform_commands_and_product_questions_have_complete_deterministic_feedback():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    pool = (root / "lib" / "platform_agent_pool.py").read_text(encoding="utf-8")
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "Required parameters" in runtime and "审批信息" in runtime
    assert "_platform_product_markdown" in runtime
    assert "is_management_product_request" in native
    assert '"parameter_schema"' in pool
    assert "platform-command-summary" in ui and "platform-command-state" in ui


def test_compliance_posture_cards_explain_assessment_count_and_enforcement():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert 'text("证据评估结论", "Evidence assessment")' in ui
    assert 'text("Agent 数量", "Agent count")' in ui
    assert 'text("平台控制措施", "Platform enforcement")' in ui
    assert "不等同于违规" in ui and "仅允许恢复流程" in ui
    assert "健康合规 Agent" in ui and "待评估 Agent" in ui and "已隔离违规 Agent" in ui
    assert "postureGroupTitle" in ui
    assert ".compliance-posture-guide" in css
    assert ".compliance-posture-fields" in css


def test_management_template_questions_use_private_control_plane_knowledge():
    root = Path(__file__).resolve().parents[1]
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    assert '"platform-admin-knowledge"' in native
    assert '"MANAGEMENT_KNOWLEDGE"' in native
    assert "management_template_knowledge(" in native
    assert "is_management_template_request(" in native
    assert '"management_template_knowledge"]' in native
    assert "_management_template_markdown(" in runtime
    assert "当前没有直接创建、编辑或发布 Agent 模板的页面或 API" in native
    assert "Compliance control templates are governance profiles" in native


def test_management_knowledge_has_complete_navigation_and_template_semantics():
    from lib import native_agent_api

    manifests = [item for item in native_agent_api.BUILTIN_MANIFESTS if item[0] == "platform-admin-knowledge"]
    assert len(manifests) == 1
    knowledge = manifests[0][2]
    workflow = knowledge["template_workflow"]
    assert workflow["seed_location_zh"] == "Dashboard > 智能体 > 平台原生智能体生成 > 平台内置管理智能体"
    assert workflow["seed_location_en"] == "Dashboard > Agents > Platform-native Agent provisioning > Built-in management Agents"
    assert workflow["business_request_location_zh"].endswith("平台原生智能体生成 > 业务智能体申请")
    assert workflow["approval_location_zh"].endswith("平台原生智能体生成 > 申请与审批")
    assert "能力倾向" in workflow["template_meaning_zh"]
    assert "不授予数据库、网络、Skill 或 Tool 权限" in workflow["template_meaning_zh"]
    assert {item["key"] for item in knowledge["business_template_options"]} == {
        "general-restricted", "code-development", "production-operations",
    }


def test_management_responses_follow_the_question_language():
    from lib import native_agent_api, native_runtime

    assert native_agent_api.management_response_language("如何申请内置 Agent 模板？") == "zh"
    assert native_agent_api.management_response_language("How do I request a built-in Agent template?") == "en"
    knowledge = next(item[2] for item in native_agent_api.BUILTIN_MANIFESTS if item[0] == "platform-admin-knowledge")
    chinese = native_runtime._management_template_markdown({**knowledge, "response_language": "zh"})
    english = native_runtime._management_template_markdown({**knowledge, "response_language": "en"})
    assert "Dashboard > 智能体 > 平台原生智能体生成 > 平台内置管理智能体" in chinese
    assert "Built-in Agent templates and platform Agent requests" not in chinese
    assert "Dashboard > Agents > Platform-native Agent provisioning > Built-in management Agents" in english
    assert "内置 Agent 模板与平台 Agent 申请" not in english
    snapshot = {"native_agents": {}, "runtime_executions": {}, "llm_profiles": {}, "admin_group": {}}
    assert "平台运行状态" in native_runtime._management_status_markdown(snapshot, "zh")
    assert "Platform runtime status" in native_runtime._management_status_markdown(snapshot, "en")


def test_native_manifest_and_adapter_panels_are_stacked_full_width():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert '<div className="native-contract-panels">' in ui
    layout = css.split(".native-contract-panels {", 1)[1].split("}", 1)[0]
    child = css.split(".native-contract-panels > .info-panel {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr)" in layout
    assert "width: 100%" in child


def test_management_knowledge_is_not_in_general_manifest_listing():
    root = Path(__file__).resolve().parents[1]
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    assert "MANIFEST_KIND <> 'MANAGEMENT_KNOWLEDGE'" in native
    assert "platform.manage" in native.split("def list_manifests", 1)[1].split("def management_template_knowledge", 1)[0]


def test_deployment_bootstrap_verifies_the_private_knowledge_seed():
    root = Path(__file__).resolve().parents[1]
    native = (root / "lib" / "native_agent_api.py").read_text(encoding="utf-8")
    deployment = (root / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    bootstrap = native.split("def bootstrap_native_agents", 1)[1].split("def activate_bootstrap_agents", 1)[0]
    assert "_verify_management_knowledge(tx)" in bootstrap
    assert '"management_knowledge": knowledge' in bootstrap
    assert "CONTENT_DIGEST" in native.split("def _verify_management_knowledge", 1)[1].split("def _principal_display_name", 1)[0]
    assert "native_agent_api.bootstrap_native_agents()" in deployment
    assert '_record_evidence(journal.run_id, "POSTFLIGHT"' in deployment


def test_deployment_postflight_verifies_scoped_private_knowledge():
    root = Path(__file__).resolve().parents[1]
    deployment = (root / "lib" / "deployment_orchestrator.py").read_text(encoding="utf-8")
    block = deployment.split("native = native_agent_api.bootstrap_native_agents()", 1)[1].split("models = _configure_models", 1)[0]
    assert '"scoped_knowledge": native.get("scoped_knowledge")' in block
    assert '!= "MIGRATED"' in block
    assert '_record_evidence(journal.run_id, "PLATFORM_KNOWLEDGE_POSTFLIGHT"' in block
