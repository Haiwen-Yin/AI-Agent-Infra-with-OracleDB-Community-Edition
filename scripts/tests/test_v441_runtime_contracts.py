"""Regression contracts for v4.4.1 runtime compatibility boundaries."""

from pathlib import Path
import re

from lib import admin_management, cursor_pagination, identity_api


def test_management_channel_resolves_legacy_admin_by_local_identity(monkeypatch):
    class Transaction:
        def query(self, _sql, _params):
            return [{"PRINCIPAL_ID": "HP_opaque_admin"}]

    assert admin_management._admin_principals(Transaction()) == ["HP_opaque_admin"]


def test_management_initialization_adopts_legacy_administrator_first():
    source = Path(admin_management.__file__).read_text(encoding="utf-8")
    function = source.split("def initialize()", 1)[1].split("\ndef session_policy", 1)[0]
    assert "identity_api.bootstrap_existing_admins()" in function
    assert "_admin_principals(tx)" in function
    assert 'principal_id == "admin"' not in function


def test_session_absolute_deadline_limits_idle_renewal():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def resolve_session(", 1)[1].split("\ndef set_session_mfa_level", 1)[0]
    assert "absolute_deadline" in function
    assert "new_expiry = min(new_expiry, absolute_deadline)" in function


def test_dashboard_session_expiry_includes_a_timezone_offset():
    source = Path(__file__).resolve().parents[1] / "web_app.py"
    content = source.read_text(encoding="utf-8")
    helper = content.split("def _browser_session_expiry", 1)[1].split("def _session_from_request", 1)[0]
    assert "timestamp.astimezone().isoformat()" in helper
    assert "_browser_session_expiry(session.get(\"expires_at\"))" in content


def test_frontend_keeps_legacy_naive_session_expiry_in_local_time():
    source = Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx"
    content = source.read_text(encoding="utf-8")
    assert 'raw.replace(" ", "T")' in content
    assert "const hasTimezone =" in content
    assert "new Date(browserValue).getTime()" in content
    assert "`${raw}Z`" not in content


def test_upgrade_protocol_keeps_remote_execution_outside_web_service():
    source = Path(admin_management.__file__).read_text(encoding="utf-8")
    assert "def start_upgrade_rollout(" in source
    assert "def advance_upgrade_node(" in source
    assert "zipfile" in source
    assert "subprocess" not in source


def test_automatic_uploaded_upgrade_keeps_signature_and_safe_point_boundaries():
    source = Path(admin_management.__file__).read_text(encoding="utf-8")
    function = source.split("def auto_schedule_upgrade(", 1)[1].split("\ndef preflight_upgrade", 1)[0]
    assert "upgrade package database does not match this installation" in function
    assert "upgrade package version must be newer than this installation" in function
    assert "CX_UPGRADE_NODES" in function
    assert "CX_SKILL_DISTRIBUTION" in function
    assert "'OLD_VERSION'" in function
    assert "subprocess" not in function


def test_uploaded_upgrade_endpoint_passes_current_release_version():
    source = (Path(__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    endpoint = source.split("def platform_upgrade_upload(", 1)[1].split("\n\n@app.post(\"/api/platform/upgrades/{upgrade_id}/preflight\")", 1)[0]
    assert "stage_upgrade_archive(" in endpoint
    assert "reason, VERSION" in endpoint


def test_dashboard_uses_a_single_archive_upload_workflow():
    app = (Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    platform = app.split("function PlatformOperationsPage(", 1)[1].split("function DeploymentModelsPage(", 1)[0]
    assert 'name="package" type="file"' in platform
    assert "/api/platform/upgrades/upload?reason=" in platform
    assert "上传并自动编排" in platform
    assert "/human-approval" not in platform
    assert "/skill-distribution" not in platform


def test_dashboard_agent_registration_uses_full_width_panels_and_compact_status():
    app = (Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    agents = app.split("function AgentsPage(", 1)[1].split("function Channels(", 1)[0]
    assert "external-registration-form" in agents
    assert "external-registration-status" in agents
    registered = agents.split('title={text("已注册智能体", "Registered Agents")}', 1)[1].split('title={text("Enrollment 历史", "Enrollment history")}', 1)[0]
    assert 'split-grid' not in registered


def test_oracle_sql_does_not_use_group_as_bind_name():
    root = Path(admin_management.__file__).resolve().parent
    sources = [
        (root / "admin_management.py").read_text(encoding="utf-8"),
        (root / "agent_gateway_api.py").read_text(encoding="utf-8"),
    ]
    assert all(not re.search(r":group\b", source) for source in sources)
    assert all("GROUP_ID=:group " not in source for source in sources)


def test_skill_distribution_requires_safe_point_and_records_drift():
    source = Path(admin_management.__file__).read_text(encoding="utf-8")
    function = source.split("def acknowledge_upgrade_skill(", 1)[1].split("\ndef record_artifact_receipt", 1)[0]
    assert 'activation = "ACTIVE" if verified and safe_point else "OLD_VERSION"' in function
    assert 'drift = "IN_SYNC" if activation == "ACTIVE" else "DRIFT"' in function


def test_agent_upgrade_poll_is_instance_authenticated_and_metadata_only():
    app = (Path(__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    endpoint = app.split("def gateway_pending_upgrade_skills(", 1)[1].split("\n\n@app.post(\"/api/gateway/upgrades/skill-ack\")", 1)[0]
    assert '_gateway_context(request, "skills.read")' in endpoint
    assert "pending_upgrade_skills" in endpoint
    source = Path(admin_management.__file__).read_text(encoding="utf-8")
    function = source.split("def pending_upgrade_skills(", 1)[1].split("\ndef record_artifact_receipt", 1)[0]
    assert "PACKAGE_DIGEST" in function
    assert "safe_point_required" in function
    assert "API_KEY" not in function


def test_first_cursor_page_does_not_bind_empty_key_for_oracle_compatible_databases(monkeypatch):
    captured = []
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_limit_clause", lambda: "FETCH FIRST :limit ROWS ONLY")
    monkeypatch.setattr(identity_api, "_principal_visibility_clause", lambda *_args: "1 = 1")
    monkeypatch.setattr(identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(identity_api.cursor_pagination, "resolve", lambda *_args: {"position": {}, "page_size": 20, "filter_digest": "d"})
    monkeypatch.setattr(identity_api.cursor_pagination, "page", lambda rows, *_args: {"items": rows})
    monkeypatch.setattr(identity_api, "_required_query", lambda sql, params: captured.append((sql, params)) or [])

    identity_api.list_users_cursor("admin")
    identity_api.list_agents_cursor("admin")
    identity_api.list_channels_cursor("admin")

    assert all("after" not in params for _, params in captured)
    assert all(":after" not in sql for sql, _ in captured)


def test_cursor_persistence_avoids_oracle_reserved_position_bind_name():
    source = Path(cursor_pagination.__file__).read_text(encoding="utf-8")
    assert ":position," not in source
    assert ":position_json," in source
    assert ":sort," not in source
    assert ":size," not in source
    assert ":principal," not in source


def test_monitor_and_audit_cursor_queries_avoid_oracle_reserved_limit_bind_name():
    monitor = (Path(__file__).resolve().parents[1] / "lib" / "monitor_api.py").read_text(encoding="utf-8")
    audit = (Path(__file__).resolve().parents[1] / "lib" / "audit_api.py").read_text(encoding="utf-8")
    monitor_cursor = monitor.split("def get_agent_health_cursor", 1)[1].split("def get_system_overview", 1)[0]
    audit_cursor = audit.split("def get_audit_events_cursor", 1)[1].split("def get_audit_event", 1)[0]
    assert "FETCH FIRST :row_limit ROWS ONLY" in monitor_cursor
    assert "FETCH FIRST :row_limit ROWS ONLY" in audit_cursor
    assert "FETCH FIRST :limit ROWS ONLY" not in monitor_cursor
    assert "FETCH FIRST :limit ROWS ONLY" not in audit_cursor


def test_dashboard_agent_views_separate_registered_external_and_native_paths():
    app = (Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert '"已注册智能体", "Registered Agents"' in app
    assert '"外部智能体注册", "External Agent registration"' in app
    assert '"平台原生智能体生成", "Platform-native Agent provisioning"' in app
    assert '"/api/platform/external-agent-registration"' in app
    assert "/api/native-agents?page_size=${size}" in app


def test_external_enrollment_uses_agent_name_without_implicit_runtime_binding():
    web_app = (Path(__file__).resolve().parents[1] / "web_app.py").read_text(encoding="utf-8")
    identity = Path(identity_api.__file__).read_text(encoding="utf-8")
    assert 'runtime: str = Field(default="", max_length=128)' in web_app
    assert 'agent_name: str = Field(min_length=1, max_length=256)' in web_app
    assert 'runtime: str = "", security_domain_id' in identity
    assert 'if not agent_name:' in identity
    assert 'Enrollment Agent name is required' in identity


def test_dashboard_maps_management_failures_and_long_readiness_values():
    app = (Path(__file__).resolve().parents[1] / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert '"Monitor inventory is unavailable": ["监控智能体清单暂不可用"' in app
    assert '"Audit service unavailable": ["审计服务暂不可用"' in app
    assert 'HIGH_AVAILABILITY_NOT_READY: ["高可用尚未就绪"' in app
    css = (Path(__file__).resolve().parents[1] / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert ".management-metric-grid .metric-value" in css
    assert "overflow-wrap: anywhere" in css
