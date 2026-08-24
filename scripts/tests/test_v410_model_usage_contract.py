from pathlib import Path

import pytest
import migration_runner
import live_db_validator
try:
    from shared.lib import identity_api, model_usage_api, monitor_api
except ModuleNotFoundError:  # generated edition
    from lib import identity_api, model_usage_api, monitor_api


ROOT = Path(__file__).resolve().parents[2]
GENERATED = (ROOT / "build-manifest.json").is_file()


@pytest.mark.skipif(GENERATED, reason="cross-adapter script selection is a unified-source gate")
def test_v410_scripts_are_selected_for_all_adapters():
    for database in ("oracle", "pg", "yashandb"):
        names = migration_runner._v410_script_names(database, ROOT / "config.json", "enterprise")
        assert names[-5:] == [
            "55_v4_4_10_model_usage_wallboard.sql",
            "56_v4_4_10_runtime_repair.sql",
            "57_v4_4_10_complete_model_governance.sql",
            "58_v4_4_10_knowledge_scope.sql",
            "59_v4_4_10_knowledge_graph_context.sql",
        ]
        assert (ROOT / "adapters" / database / "deploy" / names[-1]).is_file()


@pytest.mark.skipif(GENERATED, reason="source release-gate inspection is a unified-source gate")
def test_pre57_backup_keeps_dialects_isolated_and_validator_allowlist_narrow():
    import re

    backup = (ROOT / "tools" / "v410_pre57_backup.py").read_text(encoding="utf-8")
    validator = (ROOT / "spec_validator.py").read_text(encoding="utf-8")

    assert 'database == "pg"' in backup
    assert "ON CONFLICT(version) DO UPDATE" in backup
    assert "MERGE INTO AI_SCHEMA_MIGRATIONS" in backup
    assert "FROM" + " DUAL" in backup
    allowlist = validator.split("dialect_boundary_dual_files = {", 1)[1].split("}", 1)[0]
    assert set(re.findall(r'\"([^\"]+\.py)\"', allowlist)) == {
        "migration_runner.py",
        "v410_pre57_backup.py",
    }


@pytest.mark.skipif(GENERATED, reason="cross-adapter validator closure is a unified-source gate")
def test_live_validator_selects_and_checks_the_v410_contract():
    for database in ("oracle", "pg", "yashandb"):
        deploy = ROOT / "adapters" / database / "deploy"
        scripts = [deploy / name for name in live_db_validator.V410_MIGRATION_SCRIPTS]
        if database == "pg":
            scripts.extend([deploy / "51_v4_4_9_identity_boundary_repair.sql", deploy / "53_v4_4_9_pg_runtime_boundary.sql"])
        result = live_db_validator.validate_v410_static_contract(database, scripts)
        assert result["passed"] is True, result


@pytest.mark.skipif(GENERATED, reason="source module inspection is a unified-source gate")
def test_model_usage_contract_does_not_log_payloads_or_float_costs():
    source = (ROOT / "shared" / "lib" / "model_usage_api.py").read_text(encoding="utf-8")
    assert "prompt/response bodies" in source
    assert "Decimal(" in source
    assert "PROVIDER_REPORTED" in source
    assert "INCOMPLETE" in source
    assert "Authorization" in source
    assert "decrypt_section" in source


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_wallboard_route_is_read_only_and_scoped():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/wallboard")' in source
    wallboard_route = source.split('@app.get("/api/wallboard")', 1)[1].split("\n\n", 1)[0]
    assert 'Depends(require_action("wallboard.read"))' in wallboard_route
    assert 'Depends(require_action("agents.read"))' not in wallboard_route
    assert "@app.post(\"/api/wallboard\")" not in source


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_model_usage_routes_use_separate_reporting_and_forwarding_permissions():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    reporting = source.split('@app.get("/api/model-usage/summary")', 1)[1].split("\n\n", 1)[0]
    forwarding = source.split('def model_forward_authorization', 1)[1].split('@app.get("/api/model-usage/summary")', 1)[0]
    assert 'Depends(require_action("model_usage.read"))' in reporting
    assert 'model_gateway.forward' in forwarding
    assert 'authenticate_gateway_credential' in (ROOT / "shared" / "lib" / "model_usage_api.py").read_text(encoding="utf-8")
    assert 'Depends(require_action("agents.read"))' not in reporting + forwarding


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_oci_readiness_is_distinct_from_process_liveness():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/health")' in source
    assert '@app.get("/api/ready")' in source
    readiness = source.split('@app.get("/ready")', 1)[1].split('@app.get("/app")', 1)[0]
    assert "CX_PLATFORM_CAPABILITIES" in readiness
    assert "response.status_code = 503" in readiness
    assert '"status": "not_ready"' in readiness


@pytest.mark.skipif(GENERATED, reason="cross-adapter seed equivalence is a unified-source gate")
def test_v410_seeds_wallboard_capability_registry():
    for database in ("oracle", "pg", "yashandb"):
        source = "\n".join(
            (ROOT / "adapters" / database / "deploy" / name).read_text(encoding="utf-8").lower()
            for name in ("55_v4_4_10_model_usage_wallboard.sql", "56_v4_4_10_runtime_repair.sql")
        )
        assert "wallboard" in source
        assert "cx_platform_capabilities" in source


def test_v410_runtime_registry_matches_new_database_capabilities():
    try:
        from shared.lib import platform_capabilities
    except ModuleNotFoundError:
        from lib import platform_capabilities

    assert {"model_finance", "external_model_evidence"} <= set(platform_capabilities.REGISTRY)
    assert platform_capabilities.DEPENDENCIES["model_finance"] == ("audit_write",)
    assert platform_capabilities.DEPENDENCIES["external_model_evidence"] == ("audit_write",)


@pytest.mark.skipif(GENERATED, reason="PostgreSQL source inspection runs in the unified-source gate")
def test_v410_postgresql_rls_uses_the_runtime_identity_boundary():
    source = (ROOT / "adapters" / "pg" / "deploy" / "56_v4_4_10_runtime_repair.sql").read_text(encoding="utf-8")
    assert "app.current_principal_id" not in source
    assert "public.current_agent_identity()" in source
    assert "cx_model_credentials_owner" in source


def test_gateway_credential_enforces_forward_and_target_scopes(monkeypatch):
    monkeypatch.setattr(
        model_usage_api,
        "_credential",
        lambda _raw: {
            "credential_id": "GWC_1", "created_by": "HP_OWNER",
            "scopes_json": '["model.forward","profile:PROFILE_1","agent:AGENT_1"]',
        },
    )
    context = model_usage_api.authenticate_gateway_credential("cxgw_secret", "PROFILE_1", "AGENT_1")
    assert context["actor_principal_id"] == "HP_OWNER"
    try:
        model_usage_api.authenticate_gateway_credential("cxgw_secret", "PROFILE_2", "AGENT_1")
    except PermissionError:
        pass
    else:
        raise AssertionError("profile-restricted credential accepted another profile")


def test_idempotency_conflicts_are_stable_and_payload_bound(monkeypatch):
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"request_id": "LMR_1", "input_digest": "digest-a", "status": "SUCCEEDED"},
    )
    for digest in ("digest-a", "digest-b"):
        try:
            model_usage_api._reserve_idempotency("HP_1", "same-key", digest)
        except model_usage_api.ModelUsageConflict:
            pass
        else:
            raise AssertionError("duplicate idempotency key was accepted")


def test_routing_boolean_encoding_is_adapter_explicit(monkeypatch):
    monkeypatch.setattr(model_usage_api.connection, "DATABASE_DIALECT", "oracle")
    assert model_usage_api._db_bool(True) == "Y"
    assert model_usage_api._db_bool(False) == "N"
    assert model_usage_api._as_bool("Y") is True
    assert model_usage_api._as_bool("N") is False
    monkeypatch.setattr(model_usage_api.connection, "DATABASE_DIALECT", "postgresql")
    assert model_usage_api._db_bool(True) is True


def test_routing_change_updates_the_existing_policy(monkeypatch):
    monkeypatch.setattr(model_usage_api.identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(model_usage_api.connection, "execute_query_one", lambda *_args, **_kwargs: {"policy_id": "MRP_1"})
    writes = []
    monkeypatch.setattr(model_usage_api.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    result = model_usage_api.set_routing_policy("HP_ADMIN", "", "PROFILE_1", True, False, "approved", "https://example.test/api/model-gateway/completions")
    assert writes and writes[0][0].startswith("UPDATE CX_MODEL_ROUTING_POLICIES")
    assert result["policy_id"] == "MRP_1"


def test_wallboard_agent_totals_use_one_registered_agent_population(monkeypatch):
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "effective_access",
        lambda *_args, **_kwargs: {"decision": "ALLOW"},
    )
    monkeypatch.setattr(
        model_usage_api,
        "usage_summary",
        lambda *_args, **_kwargs: {
            "items": [],
            "generated_at": "2026-08-21T00:00:00Z",
            "coverage": {"observed": True, "unobserved": "unknown"},
        },
    )
    monkeypatch.setattr(model_usage_api.connection, "execute_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"total": 2, "active": 2},
    )
    monkeypatch.setattr(
        monitor_api,
        "get_system_overview",
        lambda _actor=None, _resource_scope=None: {
            "agents": {"total": 14, "online": 14, "busy": 3},
            "sessions": {"active": 4},
            "tasks": {"running_plans": 2, "running_loops": 1},
            "stalled_count": 0,
        },
    )

    result = model_usage_api.wallboard("admin")

    assert result["agents"] == {
        "total": 14,
        "online": 14,
        "busy": 3,
        "native_total": 2,
        "native_active": 2,
    }


def test_wallboard_uses_one_authorized_agent_scope(monkeypatch):
    accesses = []
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "effective_access",
        lambda _actor, action: accesses.append(action) or {"decision": "ALLOW"},
    )
    monkeypatch.setattr(
        model_usage_api.identity_api,
        "_agent_visibility_clause",
        lambda _actor: "p.PRINCIPAL_ID='AGENT_VISIBLE'",
    )
    queries = []
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query",
        lambda sql, params=None: queries.append((sql, params)) or [],
    )
    monkeypatch.setattr(
        model_usage_api.connection,
        "execute_query_one",
        lambda *_args, **_kwargs: {"total": 0, "active": 0},
    )
    monkeypatch.setattr(
        monitor_api,
        "get_system_overview",
        lambda actor=None, resource_scope=None: {
            "agents": {"total": 1, "online": 1, "busy": 0},
            "sessions": {"active": 0}, "tasks": {"running_plans": 0, "running_loops": 0},
            "stalled_count": 0, "scope_actor": actor,
        },
    )
    monkeypatch.setattr(monitor_api, "_overview_agent_scope", lambda actor, alias="a", resource_scope=None: ("1=0", {"principal_id": actor}))

    result = model_usage_api.wallboard("MANAGER")

    assert result["runtime"]["scope_actor"] == "MANAGER"
    assert all("AGENT_VISIBLE" in sql for sql, _params in queries)
    assert all(params == {"actor": "MANAGER"} for _sql, params in queries)
    assert "agents.read" not in accesses


def test_wallboard_marks_runtime_failure_as_partial_not_zero(monkeypatch):
    monkeypatch.setattr(model_usage_api.identity_api, "effective_access", lambda *_args: {"decision": "ALLOW"})
    monkeypatch.setattr(model_usage_api, "usage_summary", lambda *_args, **_kwargs: {
        "items": [], "generated_at": "2026-08-23T00:00:00Z", "coverage": {},
    })
    monkeypatch.setattr(model_usage_api.connection, "execute_query", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(model_usage_api.connection, "execute_query_one", lambda *_args, **_kwargs: {"total": 0, "active": 0})
    monkeypatch.setattr(monitor_api, "get_system_overview", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database detail must not leak")))
    monkeypatch.setattr(monitor_api, "_overview_agent_scope", lambda *_args, **_kwargs: ("1=0", {}))

    result = model_usage_api.wallboard("ADMIN")

    assert result["partial"] is True
    assert result["freshness"] == "DEGRADED"
    assert result["sources"]["runtime"] == {
        "status": "UNAVAILABLE", "error_code": "RUNTIME_OVERVIEW_UNAVAILABLE",
    }
    assert result["agents"]["total"] is None
    assert result["runtime"]["sessions"]["active"] is None
    assert "database detail" not in str(result)


def test_wallboard_organization_scope_follows_primary_owner_membership(monkeypatch):
    monkeypatch.setattr(identity_api, "_agent_visibility_clause", lambda _actor: "1=1")

    sql, params = monitor_api._overview_agent_scope(
        "ADMIN", resource_scope={"organization_id": "ORG_ROOT"},
    )

    assert "CX_AGENT_RELATIONSHIPS" in sql and "PRIMARY_OWNER" in sql
    assert "CX_ORGANIZATION_MEMBERS" in sql and "CX_ORGANIZATION_CLOSURE" in sql
    assert "wom.PRINCIPAL_ID=war.PRINCIPAL_ID" in sql
    assert params["wallboard_org"] == "ORG_ROOT"
