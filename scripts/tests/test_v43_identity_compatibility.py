"""Regression tests for v4.3 local identity compatibility."""

import hashlib
from pathlib import Path

import pytest

from lib import identity_api, security_lifecycle

try:
    from lib import approval_api
except ImportError:
    approval_api = None


def test_short_legacy_password_is_upgraded_without_relaxing_new_password_policy(monkeypatch):
    password = "admin"
    legacy_hash = "SHA256:" + hashlib.sha256(password.encode("utf-8")).hexdigest()
    monkeypatch.setattr(identity_api, "_hash_argon2id", lambda value: "$argon2id$legacy-migrated")

    valid, upgraded = identity_api.verify_password_hash(password, legacy_hash)

    assert valid is True
    assert upgraded == "$argon2id$legacy-migrated"


def test_new_password_hashing_still_requires_twelve_characters():
    try:
        identity_api.hash_password_argon2id("admin")
    except identity_api.IdentityError:
        return
    raise AssertionError("new local passwords must retain the twelve-character policy")


def test_global_user_visibility_does_not_send_unused_oracle_bind(monkeypatch):
    captured = {}
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_limit_clause", lambda: "FETCH FIRST :limit ROWS ONLY")
    monkeypatch.setattr(identity_api, "_principal_visibility_clause", lambda *_args: "1 = 1")

    def query(sql, params):
        captured.update({"sql": sql, "params": params})
        return []

    monkeypatch.setattr(identity_api, "_required_query", query)
    identity_api.list_users("admin-principal", 25)

    assert captured["params"] == {"limit": 25}
    assert ":principal_id" not in captured["sql"]


def test_bootstrap_admin_display_name_is_fixed_in_user_management(monkeypatch):
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_limit_clause", lambda: "FETCH FIRST :limit ROWS ONLY")
    monkeypatch.setattr(identity_api, "_principal_visibility_clause", lambda *_args: "1 = 1")
    monkeypatch.setattr(identity_api, "_protected_bootstrap_admin", lambda *_args: True)
    monkeypatch.setattr(identity_api, "_required_query", lambda *_args, **_kwargs: [{
        "principal_id": "admin-principal",
        "display_name": "A personal name",
        "portal_access": "Y",
        "app_access": "Y",
    }])

    rows = identity_api.list_users("admin-principal", 1)

    assert rows[0]["display_name"] == "管理员"
    assert rows[0]["protected_system_admin"] is True


def test_global_principal_visibility_does_not_send_unused_oracle_bind(monkeypatch):
    captured = {}
    monkeypatch.setattr(identity_api, "effective_access", lambda *_args: {"decision": "DENY"})
    monkeypatch.setattr(identity_api, "_principal_visibility_clause", lambda *_args: "1 = 1")

    def query(sql, params):
        captured.update({"sql": sql, "params": params})
        return {"allowed": 1}

    monkeypatch.setattr(identity_api.connection, "execute_query_one", query)
    assert identity_api._principal_visible_to("admin-principal", "target-principal")
    assert captured["params"] == {"target": "target-principal"}
    assert ":principal_id" not in captured["sql"]


def test_mfa_policy_is_explicit_and_not_implied_by_admin_role(monkeypatch):
    class Connection:
        @staticmethod
        def execute_query_one(_sql, _params):
            return {"mfa_required": "N"}

        @staticmethod
        def execute_query(*_args, **_kwargs):
            raise AssertionError("MFA policy must not be inferred from roles")

    monkeypatch.setattr(security_lifecycle, "connection", Connection())
    assert security_lifecycle.mfa_required("admin-principal") is False


def test_mfa_cannot_be_enforced_before_a_factor_is_active(monkeypatch):
    monkeypatch.setattr(security_lifecycle, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_principal_visible_to", lambda *_args: True)
    monkeypatch.setattr(security_lifecycle, "has_active_mfa_factor", lambda *_args: False)

    with pytest.raises(security_lifecycle.LifecycleError, match="active MFA factor"):
        security_lifecycle.set_mfa_required(
            "admin-principal", "admin-principal", True, "enable MFA after setup",
        )


def test_system_admin_agent_inventory_does_not_build_delegated_scope_first():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def list_agents(", 1)[1].split("\ndef _agent_visible_to(", 1)[0]
    assert function.index('effective_access(principal_id, "agents.read.all")') < function.index(
        "visibility = _agent_visibility_clause(principal_id)"
    )


def test_system_admin_barrier_inventory_avoids_lob_distinct_and_membership_scope():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def list_barriers(", 1)[1].split("\ndef barrier_detail(", 1)[0]
    assert '"SELECT DISTINCT b.BARRIER_ID' not in function
    assert 'visibility = "1 = 1"' in function
    assert "EXISTS (SELECT 1 FROM CX_CHANNEL_MEMBERS" in function


def test_server_controller_exports_the_resolved_cookie_port():
    controller = Path(identity_api.__file__).resolve().parents[1] / "start_web_server.sh"
    source = controller.read_text(encoding="utf-8")
    assert 'export MEMORY_SERVER_PORT="$PORT"' in source


def test_legacy_cookie_name_uses_entry_scope_and_fastapi_runtime_port():
    server = Path(identity_api.__file__).resolve().parents[1] / "visualization" / "server.py"
    source = server.read_text(encoding="utf-8")
    function = source.split("def _get_cookie_name(scope='PORTAL'):", 1)[1].split("\ndef _load_server_config", 1)[0]
    assert "os.environ.get('MEMORY_SERVER_PORT'" in function
    assert "portal_session_id" in function
    assert "dashboard_session_id" in function


def test_system_admin_channel_inventory_uses_global_scope(monkeypatch):
    captured = {}
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(identity_api, "_limit_clause", lambda: "FETCH FIRST :limit ROWS ONLY")

    def query(sql, params):
        captured.update({"sql": sql, "params": params})
        return []

    monkeypatch.setattr(identity_api, "_required_query", query)
    identity_api.list_channels("admin-principal", 25)
    assert "LEFT JOIN CX_CHANNEL_MEMBERS" in captured["sql"]
    assert "WHERE c.STATUS <> 'DELETED'" in captured["sql"]
    assert captured["params"] == {"principal_id": "admin-principal", "limit": 25}


def test_session_touch_renews_database_expiry_and_not_only_last_seen():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def resolve_session(", 1)[1].split("\ndef set_session_mfa_level", 1)[0]
    assert "EXPIRES_AT = :expires_at" in function
    assert "row[\"expires_at\"] = new_expiry" in function


def test_existing_bootstrap_admin_is_idempotently_promoted_to_system_admin():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def _ensure_principal(", 1)[1].split("\ndef bootstrap_existing_admins", 1)[0]
    assert "BOOTSTRAP_ADMIN" in function
    assert "ROLE_CODE = 'SYSTEM_ADMIN'" in function


def test_bootstrap_admin_system_role_cannot_be_revoked(monkeypatch):
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_principal_visible_to", lambda *_args: True)
    monkeypatch.setattr(identity_api, "_protected_bootstrap_admin", lambda *_args: True)
    monkeypatch.setattr(
        identity_api.connection, "execute_query_one",
        lambda *_args, **_kwargs: {"role_code": "SYSTEM_ADMIN"},
    )

    with pytest.raises(PermissionError, match="protected"):
        identity_api.revoke_user_role("actor", "bootstrap-admin", "role-1", "attempt")


def test_bootstrap_admin_app_access_cannot_be_disabled(monkeypatch):
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_principal_visible_to", lambda *_args: True)
    monkeypatch.setattr(
        identity_api, "entry_access",
        lambda *_args: {"protected_system_admin": True, "app_enabled": True},
    )

    with pytest.raises(PermissionError, match="protected"):
        identity_api.set_entry_access("actor", "bootstrap-admin", False, "attempt")


def test_regular_user_entry_access_change_revokes_sessions(monkeypatch):
    calls = []
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_principal_visible_to", lambda *_args: True)
    monkeypatch.setattr(
        identity_api, "entry_access",
        lambda principal_id: {
            "principal_id": principal_id,
            "protected_system_admin": False,
            "portal_enabled": True,
            "app_enabled": False,
        },
    )
    monkeypatch.setattr(identity_api.connection, "execute", lambda sql, params: calls.append((sql, params)) or 1)
    monkeypatch.setattr(identity_api, "revoke_principal_sessions", lambda *args: calls.append(("revoke", args)))
    monkeypatch.setattr(identity_api, "_audit", lambda *args: calls.append(("audit", args)))

    result = identity_api.set_entry_access("actor", "user-1", False, "Portal only")

    assert result["portal_enabled"] is True
    assert result["app_enabled"] is False
    assert any(item[0] == "revoke" for item in calls)
    assert any(item[0] == "audit" for item in calls)


def test_approved_registration_defaults_to_portal_only():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def approve_registration(", 1)[1].split("\ndef reject_registration", 1)[0]
    assert "app_access=False" in function


def test_registration_approval_atomically_assigns_primary_organization():
    source = Path(identity_api.__file__).read_text(encoding="utf-8")
    function = source.split("def approve_registration(", 1)[1].split("\ndef reject_registration", 1)[0]
    assert "organization_id" in function
    assert 'organizations.members.manage' in function
    assert "INSERT INTO CX_ORGANIZATION_MEMBERS" in function
    assert "'PRIMARY'" in function
    assert "execute_transaction_callback(work)" in function


def test_ordinary_entry_access_requires_primary_organization(monkeypatch):
    monkeypatch.setattr(identity_api.connection, "execute_query_one", lambda *_args, **_kwargs: {
        "status": "ACTIVE", "portal_access": "Y", "app_access": "Y",
    })
    monkeypatch.setattr(identity_api, "_protected_bootstrap_admin", lambda *_args: False)
    monkeypatch.setattr(identity_api, "has_active_primary_organization", lambda *_args: False)

    access = identity_api.entry_access("person-1")

    assert access["organization_ready"] is False
    assert access["portal_enabled"] is False
    assert access["app_enabled"] is False


def test_user_inventory_uses_principal_as_person_and_reports_organization(monkeypatch):
    monkeypatch.setattr(identity_api, "_require", lambda *_args: None)
    monkeypatch.setattr(identity_api, "_limit_clause", lambda: "FETCH FIRST :limit ROWS ONLY")
    monkeypatch.setattr(identity_api, "_principal_visibility_clause", lambda *_args: "1 = 1")
    captured = {}
    monkeypatch.setattr(identity_api, "_required_query", lambda sql, params: captured.update(sql=sql) or [])

    identity_api.list_users("admin", 10)

    assert "LEFT JOIN CX_ORGANIZATION_MEMBERS" in captured["sql"]
    assert "ORGANIZATION_NAME" in captured["sql"]
    assert "LOGIN_IDENTITY_COUNT" in captured["sql"]


def test_legacy_yashandb_approval_type_is_populated_on_compatibility_retry(monkeypatch):
    if approval_api is None:
        pytest.skip("Enterprise approval module is physically excluded from Community packages")
    calls = []

    def insert(sql, params):
        calls.append((sql, params))
        if len(calls) == 1:
            raise RuntimeError("YAS-04006 cannot insert NULL value to column APPROVAL_TYPE")
        return "approval-1"

    monkeypatch.setattr(approval_api, "execute_insert_returning_id", insert)

    approval_id = approval_api.create_request("TOOL", "tool-1", "agent-1")

    assert approval_id == "approval-1"
    assert len(calls) == 2
    assert "APPROVAL_TYPE" not in calls[0][0]
    assert "APPROVAL_TYPE" in calls[1][0]
    assert calls[1][1]["etype"] == "TOOL"
