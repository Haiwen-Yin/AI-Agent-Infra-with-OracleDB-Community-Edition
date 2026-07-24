"""Regression tests for version and web-session rendering contracts."""

import json
from pathlib import Path


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "visualization" / "templates"
SERVER_PATH = TEMPLATES_DIR.parent / "server.py"


def test_templates_do_not_hardcode_historical_version():
    for template in TEMPLATES_DIR.glob("*.html"):
        assert "v3.10.2" not in template.read_text(encoding="utf-8"), template.name


def test_dashboard_login_fields_are_stacked_and_aligned():
    css = (TEMPLATES_DIR.parent / "static" / "pages" / "login.css").read_text(encoding="utf-8")
    assert ".login-card form {" in css
    assert "flex-direction: column;" in css
    assert ".login-card .mb-3," in css and ".login-card .mb-4 {" in css
    assert ".form-control {" in css
    assert "display: block;" in css
    assert "width: 100%;" in css
    assert ".form-label {" in css


def test_dashboard_templates_use_configured_session_timeout():
    dashboard_templates = {
        "agents.html",
        "approvals.html",
        "audit.html",
        "branches.html",
        "collab.html",
        "graph.html",
        "knowledge.html",
        "loops.html",
        "memory.html",
        "monitor.html",
        "skills.html",
        "specs.html",
        "tasks.html",
        "workspaces.html",
    }
    for name in dashboard_templates:
        path = TEMPLATES_DIR / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        assert 'id="autoLogoutTimer"' in content, name
        # Source templates retain placeholders; packaged templates contain
        # the resolved five-minute value after build-time injection.
        assert "{{SESSION_TIMEOUT}}" in content or "_aloSec=300" in content, name
        assert "{{SESSION_TIMEOUT_DISPLAY}}" in content or "05:00" in content, name
        assert "_aloSec=3600" not in content, name
        assert 'id="sessionTimer"' not in content, name


def test_audit_uses_dashboard_native_scale_without_bootstrap():
    path = TEMPLATES_DIR / "audit.html"
    css_path = TEMPLATES_DIR.parent / "static" / "pages" / "audit.css"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    assert 'class="top-bar"' in content
    assert 'class="cx-page-tabs"' in content
    assert 'class="cx-page-tab active"' in content
    assert "bootstrap" not in content.lower()
    css = css_path.read_text(encoding="utf-8")
    assert ".audit-stats-grid{display:grid" in css
    assert ".table-responsive{width:100%;overflow-x:auto" in css


def test_portal_agent_lifecycle_is_isolated_by_node():
    content = SERVER_PATH.read_text(encoding="utf-8")
    assert "def _get_or_assign_portal_agent(user_id):" in content
    assert "def _portal_node_id():" in content
    assert "MEMORY_SERVER_NODE_ID" in content
    assert "PORTAL_NODE_ID = :v_node_id" in content
    assert "agent_api.assign_random_pool_agent(str(user_id), node_id, attempted)" in content
    assert "agent_api.hibernate_agent(agent_id, _portal_node_id())" in content
    assert "agent_api.reclaim_portal_agents(_portal_node_id())" in content
    assert "'user_id': str(user_id)" in content
    assert "if agent_id not in in_use" not in content
    assert "ws_id = str(data.get('workspace_id') or '').strip()" in content
    assert "'workspace_id': str(r['workspace_id'])" in content
    assert "AGENT_ID LIKE 'AGENT_POOL_%'" not in content


def test_portal_agent_registration_does_not_reject_existing_identity():
    content = SERVER_PATH.read_text(encoding="utf-8")
    registration = (SERVER_PATH.parent.parent / "lib" / "agent_registration.py").read_text(encoding="utf-8")
    assert "registration = agent_registration.get_registration(agent_id)" in content
    assert "agent_api.register_agent(" in content
    assert "connection.get_connection_for_agent(agent_id)" in content
    assert "existing = get_registration(agent_id)" in registration
    assert "return existing" in registration


def test_portal_registration_check_uses_schema_owner_context():
    content = SERVER_PATH.read_text(encoding="utf-8")
    guard = content.split("def _require_registered_session_agent(self):", 1)[1].split(
        "    def _authorize_request", 1
    )[0]
    assert "previous_agent_id = connection.get_current_agent_id()" in guard
    assert "connection.set_agent_context(None)" in guard
    assert "connection.set_agent_context(previous_agent_id)" in guard
    assert guard.index("connection.set_agent_context(None)") < guard.index("agent_registration.get_registration")
    assert guard.index("agent_registration.get_registration") < guard.index("connection.set_agent_context(previous_agent_id)")


def test_portal_user_type_control_has_visible_down_arrow():
    template = (TEMPLATES_DIR / "portal_login.html").read_text(encoding="utf-8")
    css = (TEMPLATES_DIR.parent / "static" / "pages" / "portal_login.css").read_text(encoding="utf-8")
    assert 'class="auth-mode-select"' in template
    assert 'class="select-arrow"' in template
    assert ".select-arrow svg" in css


def test_pool_assignment_excludes_inactive_registered_agents():
    root = Path(__file__).resolve().parents[2]
    adapter_files = [
        root / "adapters" / database / "agent_api.py"
        for database in ("oracle", "pg", "yashandb")
    ]
    if not adapter_files[0].exists():
        adapter_files = [root / "scripts" / "lib" / "agent_api.py"]
    for path in adapter_files:
        content = path.read_text(encoding="utf-8")
        assert "LEFT JOIN" in content
        assert "AGENT_REGISTRATIONS" in content.upper()
        assert "STATUS = 'ACTIVE'" in content.upper()
    pg = root / "adapters" / "pg" / "agent_api.py"
    if pg.exists():
        assert "def _ensure_agent_login(agent_id: str)" in pg.read_text(encoding="utf-8")
    elif json.loads((root / "build-manifest.json").read_text(encoding="utf-8")).get("database", {}).get("key") == "pg":
        assert "def _ensure_agent_login(agent_id: str)" in adapter_files[0].read_text(encoding="utf-8")


def test_auth_branding_preserves_product_title():
    script = (SERVER_PATH.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    assert "auth.textContent = \"\"" not in script
    assert "auth.insertBefore(authLogo, auth.firstChild)" in script


def test_all_adapters_persist_and_condition_portal_node_ownership():
    root = Path(__file__).resolve().parents[2]
    adapter_files = [
        root / "adapters" / database / "agent_api.py"
        for database in ("oracle", "pg", "yashandb")
    ]
    if not adapter_files[0].exists():
        adapter_files = [root / "scripts" / "lib" / "agent_api.py"]
    for path in adapter_files:
        content = path.read_text(encoding="utf-8")
        assert "def reclaim_portal_agents(portal_node_id: str) -> int:" in content
        assert "portal_node_id: Optional[str] = None" in content
        assert "PORTAL_NODE_ID" in content.upper()
        assert "STATUS = 'POOL'" in content.upper()


def test_portal_uses_safe_full_markdown_renderer():
    content = (TEMPLATES_DIR / "portal_chat.html").read_text(encoding="utf-8")
    static_dir = TEMPLATES_DIR.parent / "static"
    assert '<script src="/static/marked.min.js"></script>' in content
    assert '<script src="/static/purify.min.js"></script>' in content
    assert "window.marked.parse" in content
    assert "window.DOMPurify.sanitize" in content
    assert "renderMarkdown(content)" in content
    assert "renderMarkdown(fullText)" in content
    assert (static_dir / "marked.min.js").stat().st_size > 30_000
    assert (static_dir / "purify.min.js").stat().st_size > 20_000


def test_portal_exit_waits_for_agent_release_before_redirect():
    content = (TEMPLATES_DIR / "portal_chat.html").read_text(encoding="utf-8")
    release = content.split("async function releaseAgent(){", 1)[1].split("\n}", 1)[0]
    assert "await fetch('/portal/api/agent/release'" in release
    assert "if(!response.ok||!result.success)" in release
    assert "session_id_'+window.location.port" in release
    assert release.index("await fetch") < release.index("window.location.href")


def test_monitor_metrics_use_pg_session_columns_and_show_sample_state():
    root = Path(__file__).resolve().parents[2]
    api_path = root / "shared" / "lib" / "monitor_api.py"
    if not api_path.exists():
        api_path = root / "scripts" / "lib" / "monitor_api.py"
    api = api_path.read_text(encoding="utf-8")
    template = (TEMPLATES_DIR / "monitor.html").read_text(encoding="utf-8")
    assert "LAST_ACTIVE_AT - CREATED_AT" in api
    assert "IS_ACTIVE = FALSE" in api
    assert '"session_sample_count"' in api
    assert "No samples" in template
    assert "Entity Accesses (24h)" in template


def test_dashboard_sidebar_spacing_is_compact_and_consistent():
    expected = ".sidebar-nav a{display:flex;align-items:center;gap:10px;padding:8px 20px;"
    for template in TEMPLATES_DIR.glob("*.html"):
        content = template.read_text(encoding="utf-8")
        if ".sidebar-nav a{" in content:
            assert expected in content, template.name


def test_common_light_ui_contract_covers_dynamic_content_and_action_buttons():
    css = (TEMPLATES_DIR.parent / "static" / "chuanxu.css").read_text(encoding="utf-8")
    assert "display: flex;" in css.split(".sidebar-nav a, .sidebar-link", 1)[1].split("}", 1)[0]
    assert '[data-lang="zh"] [data-en]' in css
    assert '[data-lang="en"] [data-zh]' in css
    for variant in ("info", "success", "warn", "danger", "purple"):
        assert f".btn-sm.btn-{variant}" in css
    assert "gap: 0 !important" in css
    assert ".branch-record-row.hovered td" in css
    assert "animation: cx-spin .8s linear infinite !important" in css
    assert "writing-mode: horizontal-tb" in css
    assert ".data-table td.cx-truncate" in css
    assert ".cx-truncate:not(td):not(th)" in css


def test_graph_labels_use_theme_contrast_backgrounds():
    graph = (TEMPLATES_DIR / "graph.html").read_text(encoding="utf-8")
    assert "function graphLabelFont(palette,size,background,foreground)" in graph
    assert "labelBackground:styles.getPropertyValue('--cx-surface-strong')" in graph
    assert "background:labelBackground" in graph
    assert "nodeTextColor(nodeColor)" in graph
    assert "strokeWidth:5" in graph
    assert "edge:dark?'#8296b5':'#6d8096'" in graph
    assert "font:graphLabelFont(palette,10)" in graph


def test_dashboard_sidebar_brand_identifies_ai_agent_management_platform():
    script = (TEMPLATES_DIR.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    assert "function addPlatformName()" in script
    assert "AI Agent Management Platform" in script
    assert "AI Agent 管理平台" in script
    platform = script.split("function addPlatformName()", 1)[1].split("function addThemeToggle()", 1)[0]
    assert 'document.querySelector(".sidebar-brand")' in platform
    assert "cx-sidebar-platform-name" in platform
    assert ".top-bar" not in platform


def test_branch_and_loop_light_actions_have_visible_labels():
    branches = (TEMPLATES_DIR / "branches.html").read_text(encoding="utf-8")
    loops = (TEMPLATES_DIR / "loops.html").read_text(encoding="utf-8")
    assert "branch-record-row" in branches
    assert "branch-actions-row" in branches
    assert "class=\"btn-sm btn-warn\"" in branches
    assert "class=\"btn-sm btn-danger\"" in branches
    assert '<b style="color:#fff"' not in loops
    assert "class=\"btn-sm btn-success\"" in loops
    assert "class=\"btn-sm btn-danger\"" in loops
    assert "bindBranchRowHover(tb)" in branches
    assert "classList.add('hovered')" in branches
    assert "finally" in loops.split("async function loadLoops", 1)[1].split("function renderLoopList", 1)[0]


def test_governance_and_audit_templates_keep_actions_and_event_details_localized():
    if not (TEMPLATES_DIR / "approvals.html").exists() or not (TEMPLATES_DIR / "audit.html").exists():
        return
    approvals = (TEMPLATES_DIR / "approvals.html").read_text(encoding="utf-8")
    audit = (TEMPLATES_DIR / "audit.html").read_text(encoding="utf-8")
    approvals_css = (TEMPLATES_DIR.parent / "static" / "pages" / "approvals.css").read_text(encoding="utf-8")
    audit_css = (TEMPLATES_DIR.parent / "static" / "pages" / "audit.css").read_text(encoding="utf-8")
    assert 'data-zh>操作</span><span data-en>Actions' in approvals
    assert 'data-zh>智能体 ID</span><span data-en>Agent ID' in approvals
    assert 'data-zh>无</span><span data-en>None' in approvals
    assert ".emergency-form{grid-template-columns:" in approvals_css
    assert ".cx-governance-page #requests .cx-toolbar" in approvals_css
    assert ".cx-governance-page #emergency>.cx-table-wrap" in approvals_css
    assert 'class="cx-guide"' in audit
    assert 'class="cx-list-guide"' in audit
    assert "toggleAuditDetail" in audit
    assert "window.toggleAuditDetail=toggleAuditDetail" in audit
    assert 'data-zh>点击条目查看详情' in audit
    assert "cx-approval-action" in approvals
    assert "cx-actions-cell" in approvals
    assert ".cx-approval-action" in approvals_css
    assert ".emergency-actions .btn{display:inline-flex" in approvals_css
    assert "min-width:1240px" in audit_css
    assert "e.outcome" in audit
    assert "e.correlation_id" in audit
    assert ".audit-detail-row" in audit_css
    assert ".cx-detail-trigger" not in audit_css
    assert "min-width:220px" in approvals_css
    assert "overflow:visible!important" in approvals_css
    assert "cx-emergency-guide" in approvals
    skills = (TEMPLATES_DIR / "skills.html").read_text(encoding="utf-8")
    assert "chuanxu-language-change" in skills
    assert "data-skill-label-zh=\"删除\"" in skills
    assert "#trash" in skills
    assert "Array.isArray(d.requests)" in approvals
    assert "closedLabels" in approvals


def test_enterprise_navigation_and_language_controls_match_dashboard_contract():
    approvals = (TEMPLATES_DIR / "approvals.html").read_text(encoding="utf-8")
    audit = (TEMPLATES_DIR / "audit.html").read_text(encoding="utf-8")
    shared_css = (TEMPLATES_DIR.parent / "static" / "chuanxu.css").read_text(encoding="utf-8")
    for content in (approvals, audit):
        assert '<span data-zh>审批</span><span data-en>Approvals</span>' in content
        assert '<span data-zh>审批与治理</span><span data-en>Approvals & Governance</span></a>' not in content
        assert 'class="lang-toggle" type="button" onclick="toggleLang()"' in content
    divider_rule = shared_css.split(".sidebar-nav .nav-divider", 1)[1].split("}", 1)[0]
    assert "border-top: 1px solid" in divider_rule


def test_audit_event_details_use_row_expansion_without_detail_column():
    audit = (TEMPLATES_DIR / "audit.html").read_text(encoding="utf-8")
    event_header = audit.split('<section id="events"', 1)[1].split("</thead>", 1)[0]
    render = audit.split("function render(){", 1)[1].split("function load()", 1)[0]
    assert 'data-zh>详情</span><span data-en>Detail' not in event_header
    assert "detailCell" not in render
    assert 'colspan="8"' in render
    assert 'colspan="9"' not in render
    assert "toggleAuditDetail" in render


def test_expandable_dashboard_lists_explain_row_detail_interaction():
    expandable_templates = {
        "agents.html",
        "audit.html",
        "branches.html",
        "collab.html",
        "knowledge.html",
        "memory.html",
        "skills.html",
        "specs.html",
        "tasks.html",
        "workspaces.html",
    }
    for name in expandable_templates:
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert 'class="cx-list-guide"' in content, name
        assert 'data-zh>点击条目查看详情' in content, name
        assert 'data-en>Click a row to view details' in content, name
    agents = (TEMPLATES_DIR / "agents.html").read_text(encoding="utf-8")
    assert 'onclick="showRegistryDetail(' not in agents
    assert 'onclick="showSessionDetail(' not in agents
    assert 'onclick="showCollabDetail(' not in agents


def test_dashboard_footer_and_brand_geometry_are_shared_by_enterprise_pages():
    css = (TEMPLATES_DIR.parent / "static" / "chuanxu.css").read_text(encoding="utf-8")
    nav = css.split(".sidebar-nav {", 1)[1].split("}", 1)[0]
    footer = css.split(".sidebar-footer {", 1)[1].split("}", 1)[0]
    footer_controls = css.split(".sidebar-footer .lang-toggle, .sidebar-footer .logout-btn", 1)[1].split("}", 1)[0]
    timer = css.split(".timer-display {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto" in nav
    assert "overflow-y: auto" in nav
    assert "flex: 0 0 auto" in footer
    assert "width: 100%" in footer_controls
    assert "box-sizing: border-box" in footer_controls
    assert "line-height: 1.2" in footer_controls
    assert "padding: 4px 0 !important" in timer
    script = (TEMPLATES_DIR.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    assert "cx-title-lockup" not in script
    for name in ("approvals.html", "audit.html"):
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert 'class="lang-toggle" type="button" onclick="toggleLang()"' in content
        assert 'class="logout-btn"' in content
        assert 'id="autoLogoutTimer"' in content


def test_graph_pages_share_theme_contrast_fonts_and_graph_filters_are_localized():
    shared_script = (TEMPLATES_DIR.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    assert "window.ChuanxuGraph" in shared_script
    assert "nodeTextColor" in shared_script
    for name in ("knowledge.html", "memory.html"):
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert "window.ChuanxuGraph.nodeFont" in content, name
        assert "window.ChuanxuGraph.edgeFont" in content, name
        assert "#e8ecf4" not in content, name
        assert "#9ca8c0" not in content, name
    graph = (TEMPLATES_DIR / "graph.html").read_text(encoding="utf-8")
    assert 'data-label-zh="所有类型" data-label-en="All types"' in graph
    assert 'data-graph-type="MEMORY"' in graph
    assert 'data-graph-type="LOOP_DEFINITION"' in graph
    assert "activeGraphTypes" in graph
    assert "applyGraphTypeFilter" in graph


def test_status_and_level_filter_chips_are_bilingual_and_functional():
    cases = {
        "monitor.html": ("data-status=\"ONLINE\"", "在线", "Online", "_activeFilters"),
        "approvals.html": ("data-approval-status=\"PENDING\"", "待处理", "Pending", "approvalFilter"),
        "audit.html": ("data-audit-level=\"METADATA\"", "元数据", "Metadata", "activeAuditLevels"),
        "tasks.html": ("data-task-status=\"RUNNING\"", "运行中", "Running", "activeTaskStatuses"),
    }
    for name, markers in cases.items():
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in content, f"{name}: {marker}"
        assert 'aria-pressed="true"' in content, name
    approvals = (TEMPLATES_DIR / "approvals.html").read_text(encoding="utf-8")
    for status in ("PENDING", "APPROVED", "REJECTED", "REVIEW_REQUIRED", "EXPIRED"):
        assert f"{status}:[" in approvals
    assert "There are no expired requests" in approvals


def test_legal_hold_guidance_matches_retention_scope_semantics():
    audit = (TEMPLATES_DIR / "audit.html").read_text(encoding="utf-8")
    governance = (TEMPLATES_DIR.parent.parent / "lib" / "governance_api.py").read_text(encoding="utf-8")
    assert "审计 ID、资源 ID，或填写 *" in audit
    assert "matching uses the complete ID exactly" in audit
    assert "while the hold is ACTIVE" in audit
    assert "SCOPE = '*' OR SCOPE = :resource_id OR SCOPE = :audit_id" in governance


def test_dynamic_enum_values_use_shared_localized_display_labels():
    script = (TEMPLATES_DIR.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    for marker in (
        'ONLINE: ["在线", "Online"]',
        'APPROVAL_REQUIRED: ["需要审批", "Approval required"]',
        'AUDIT_RETENTION: ["审计留存", "Audit retention"]',
        'DATABASE_DATA: ["数据库数据", "Database data"]',
        'CANCEL_WORK: ["取消任务", "Cancel work"]',
        "valueLabel: valueLabel",
        "valueList: valueList",
    ):
        assert marker in script

    for name in ("monitor.html", "tasks.html", "approvals.html", "audit.html", "skills.html"):
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert "window.ChuanxuUI.valueLabel" in content, name
        assert "chuanxu-language-change" in content, name

    approvals = (TEMPLATES_DIR / "approvals.html").read_text(encoding="utf-8")
    audit = (TEMPLATES_DIR / "audit.html").read_text(encoding="utf-8")
    assert "window.ChuanxuUI.valueList" in approvals
    assert "esc(label(a.action))" in approvals
    assert "esc(label(e.action))" in audit
    assert "label(rawAction).toUpperCase().indexOf(action)" in audit


def test_skills_navigation_is_localized_as_chinese_skill_name():
    dashboard_templates = [
        path for path in TEMPLATES_DIR.glob("*.html")
        if 'href="/skills"' in path.read_text(encoding="utf-8")
    ]
    assert dashboard_templates
    for path in dashboard_templates:
        content = path.read_text(encoding="utf-8")
        assert '<span data-zh>技能</span><span data-en>Skills</span>' in content, path.name
        assert '<span data-zh>Skills</span>' not in content, path.name


def test_remaining_dashboard_enum_data_uses_shared_localized_labels():
    script = (TEMPLATES_DIR.parent / "static" / "chuanxu.js").read_text(encoding="utf-8")
    for marker in (
        'BUSINESS: ["业务", "Business"]',
        'CONVERSATION: ["会话", "Conversation"]',
        'DRAFT: ["草稿", "Draft"]',
        'IMPLEMENTED: ["已实现", "Implemented"]',
        'HANDOFF: ["交接", "Handoff"]',
        'AD_HOC: ["临时", "Ad hoc"]',
        'PIPELINE: ["流水线", "Pipeline"]',
        'REMOVED: ["已移除", "Removed"]',
        'PUBLIC: ["公开", "Public"]',
        'MANUAL: ["手动评估", "Manual"]',
        'SCHEDULE: ["定时触发", "Schedule"]',
    ):
        assert marker in script

    for name in ("agents.html", "workspaces.html", "specs.html", "branches.html", "collab.html", "loops.html"):
        content = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert "window.ChuanxuUI.valueLabel" in content, name
        assert "chuanxu-language-change" in content, name

    agents = (TEMPLATES_DIR / "agents.html").read_text(encoding="utf-8")
    workspaces = (TEMPLATES_DIR / "workspaces.html").read_text(encoding="utf-8")
    specs = (TEMPLATES_DIR / "specs.html").read_text(encoding="utf-8")
    branches = (TEMPLATES_DIR / "branches.html").read_text(encoding="utf-8")
    collab = (TEMPLATES_DIR / "collab.html").read_text(encoding="utf-8")
    loops = (TEMPLATES_DIR / "loops.html").read_text(encoding="utf-8")
    assert "valueLabel(a.agent_type" in agents
    assert "valueLabel(ws.workspace_type" in workspaces and "valueLabel(ws.isolation_mode" in workspaces
    assert "valueLabel(s.spec_scope" in specs and "valueLabel(s.complexity" in specs
    assert "valueLabel(raw)" in branches and 'data-label-zh="探索"' in branches
    assert "valueLabel(g.group_type" in collab and "valueLabel(g.sharing_policy" in collab
    assert 'data-cx-value="' in loops and 'data-label-zh="手动评估"' in loops
