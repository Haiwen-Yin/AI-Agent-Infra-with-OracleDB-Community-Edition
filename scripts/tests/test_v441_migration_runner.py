"""Regression coverage for the v4.4.1 migration completeness probe."""

from pathlib import Path

import migration_runner


def test_v441_objects_complete_reads_schema_catalog(monkeypatch):
    monkeypatch.setattr(migration_runner, "MIGRATION_VERSION", "4.4.1")
    monkeypatch.setattr(migration_runner, "_schema_tables", lambda cursor, database: set(migration_runner.V441_ADMIN_HA_TABLES))
    monkeypatch.setattr(migration_runner, "_schema_columns_complete", lambda *args: True)
    assert migration_runner._objects_complete(object(), "pg") is True


def test_v441_script_selection_includes_management_migration():
    names = migration_runner._v441_script_names("pg", Path("config.json"), "enterprise")
    assert names[-2:] == ["35_v4_4_1_admin_ha_upgrade.sql", "36_v4_4_1_upgrade_protocol.sql"]


def test_v441_legacy_checksum_adoption_requires_complete_schema(monkeypatch):
    script = Path("35_v4_4_1_admin_ha_upgrade.sql")
    checksum = next(iter(
        migration_runner.LEGACY_V441_STEP_CHECKSUMS["pg"]
        ["35_v4_4_1_admin_ha_upgrade"]
    ))
    monkeypatch.setattr(migration_runner, "_step_objects_complete", lambda *args: True)
    assert migration_runner._legacy_v441_step_compatible(object(), "pg", script, checksum)

    monkeypatch.setattr(migration_runner, "_step_objects_complete", lambda *args: False)
    assert not migration_runner._legacy_v441_step_compatible(object(), "pg", script, checksum)
    assert not migration_runner._legacy_v441_step_compatible(object(), "pg", script, "unknown")


def test_oracle_admin_enrollment_not_null_repair_is_idempotent():
    script = Path(migration_runner.REPO_ROOT) / "adapters/oracle/deploy/35_v4_4_1_admin_ha_upgrade.sql"
    content = script.read_text(encoding="utf-8")
    declaration = content.index("DECLARE\n  v_nullable CHAR(1);")
    procedure = content.index("  PROCEDURE ddl", declaration)
    nullable_guard = content.index("IF v_nullable='Y' THEN")
    modify = content.index("ALTER TABLE CX_ADMIN_ENROLLMENTS MODIFY (REQUESTED_BY NOT NULL)")

    assert declaration < procedure
    assert nullable_guard < modify
