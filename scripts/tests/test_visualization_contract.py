"""Regression tests for version and web-session rendering contracts."""

from pathlib import Path


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "visualization" / "templates"
SERVER_PATH = TEMPLATES_DIR.parent / "server.py"


def test_templates_do_not_hardcode_historical_version():
    for template in TEMPLATES_DIR.glob("*.html"):
        assert "v3.10.2" not in template.read_text(encoding="utf-8"), template.name


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
        assert "{{SESSION_TIMEOUT}}" in content, name
        assert "{{SESSION_TIMEOUT_DISPLAY}}" in content, name
        assert "_aloSec=3600" not in content, name
        assert 'id="sessionTimer"' not in content, name


def test_audit_uses_dashboard_native_scale_without_bootstrap():
    path = TEMPLATES_DIR / "audit.html"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    top_bar = content.split('<div class="top-bar">', 1)[1].split(
        '<div class="content-area">', 1
    )[0]
    assert 'class="tab-btns"' in top_bar
    assert 'class="tab-btn active"' in top_bar
    assert "switchAuditTab('overview',this)" in top_bar
    assert "bootstrap" not in content.lower()
    assert ".audit-stats-grid{display:grid" in content
    assert ".table-responsive{width:100%;overflow-x:auto" in content


def test_portal_agent_lifecycle_is_isolated_by_node():
    content = SERVER_PATH.read_text(encoding="utf-8")
    assert "def _get_or_assign_portal_agent(user_id):" in content
    assert "def _portal_node_id():" in content
    assert "MEMORY_SERVER_NODE_ID" in content
    assert "PORTAL_NODE_ID = :v_node_id" in content
    assert "agent_api.assign_random_pool_agent(str(user_id), node_id)" in content
    assert "agent_api.hibernate_agent(agent_id, _portal_node_id())" in content
    assert "agent_api.reclaim_portal_agents(_portal_node_id())" in content
    assert "'user_id': str(user_id)" in content
    assert "if agent_id not in in_use" not in content
    assert "ws_id = str(data.get('workspace_id') or '').strip()" in content
    assert "'workspace_id': str(r['workspace_id'])" in content
    assert "AGENT_ID LIKE 'AGENT_POOL_%'" not in content


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
