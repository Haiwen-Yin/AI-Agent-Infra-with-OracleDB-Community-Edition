from pathlib import Path
import json
import pytest

import migration_runner


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_MODE = (ROOT / "build-manifest.json").is_file() and not (ROOT / "adapters").is_dir()
DATABASE_KEY = (
    str(json.loads((ROOT / "build-manifest.json").read_text(encoding="ascii"))["database"]["key"])
    if PACKAGE_MODE else None
)


def _migration_dir(adapter: str) -> Path:
    if PACKAGE_MODE:
        if adapter != DATABASE_KEY:
            pytest.skip(f"{adapter} migration is validated by its generated package")
        return ROOT / "scripts" / "deploy"
    return ROOT / "adapters" / adapter / "deploy"


def test_v448_migrations_exist_for_all_adapters():
    for adapter in ("oracle", "pg", "yashandb"):
        deploy = _migration_dir(adapter)
        source = (deploy / "48_v4_4_8_platform_agent_isolation.sql").read_text(encoding="utf-8").upper()
        for marker in (
            "CX_PLATFORM_COMMANDS", "CX_PLATFORM_COMMAND_EXECUTORS",
            "CX_PLATFORM_MAINTENANCE_TASKS", "CX_PLATFORM_MAINTENANCE_ATTEMPTS",
            "CX_PLATFORM_SAFE_AUTONOMY_POLICIES", "CX_PLATFORM_KNOWLEDGE",
            "CX_PLATFORM_KNOWLEDGE_CHUNKS", "CX_PLATFORM_KNOWLEDGE_GRANTS",
            "CX_DATABASE_ISOLATION_INVENTORY", "EMERGENCY_CONTAINMENT",
            "PROPOSAL_ONLY", "GOVERNED_EXECUTOR",
        ):
            assert marker in source
        if adapter == "pg":
            for marker in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY", "REVOKE ALL PRIVILEGES"):
                assert marker in source
            domain = (deploy / "49_v4_4_8_security_domain_rls.sql").read_text(encoding="utf-8").upper()
            assert "CX_CHANNEL_DOMAIN_MEMBER" in domain
            assert "CX_DOMAIN_MEMBERS" in domain
            assert "AGENT_DB_IDENTITY" in domain


def test_v448_migration_selection_and_object_contract(monkeypatch):
    monkeypatch.setattr(migration_runner, "MIGRATION_VERSION", "4.4.8")
    names = migration_runner._v448_script_names("pg", Path("config.json"), "enterprise")
    assert names[-2:] == ["48_v4_4_8_platform_agent_isolation.sql", "49_v4_4_8_security_domain_rls.sql"]
    assert migration_runner._v448_script_names("oracle", Path("config.json"), "enterprise")[-1] == "48_v4_4_8_platform_agent_isolation.sql"
    assert "4.4.8" in migration_runner.JOURNALED_MIGRATION_VERSIONS


def test_v448_static_contract_accepts_current_source():
    from live_db_validator import V448_MIGRATION_SCRIPTS, validate_v448_static_contract

    for adapter in ("oracle", "pg", "yashandb"):
        deploy = _migration_dir(adapter)
        scripts = [deploy / name for name in V448_MIGRATION_SCRIPTS]
        if adapter == "pg":
            scripts.append(deploy / "49_v4_4_8_security_domain_rls.sql")
        result = validate_v448_static_contract(adapter, scripts)
        assert result["passed"], result


def test_v448_native_and_pg_isolation_revoke_legacy_collab_runtime_access():
    for adapter in ("oracle", "yashandb"):
        source = (_migration_dir(adapter) / "48_v4_4_8_platform_agent_isolation.sql").read_text(encoding="utf-8").upper()
        assert "REVOKE SELECT ON AIADMIN.COLLAB_GROUPS FROM AGENT_API" in source
        assert "REVOKE SELECT ON AIADMIN.COLLAB_GROUP_MEMBERS FROM AGENT_API" in source
    pg_domain = (_migration_dir("pg") / "49_v4_4_8_security_domain_rls.sql").read_text(encoding="utf-8").upper()
    assert "JOIN PUBLIC.CX_DOMAIN_MEMBERS DOMAIN_MEMBER" in pg_domain
    assert "CURRENT_USER" in pg_domain
    assert "AGENT_DB_IDENTITY" in pg_domain
