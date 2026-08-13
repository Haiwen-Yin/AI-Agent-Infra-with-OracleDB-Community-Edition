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
