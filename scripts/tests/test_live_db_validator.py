"""Static contracts for edition-aware live catalog validation."""

from __future__ import annotations

import live_db_validator as validator
import pytest

from live_db_validator import (
    GOVERNANCE_TABLES,
    REGISTRATION_TABLES,
    ProbeResult,
    _catalog_index_is_unique,
)


def test_registration_is_common_but_governance_tables_are_enterprise_only():
    assert REGISTRATION_TABLES == ("AGENT_REGISTRATIONS",)
    assert "AGENT_REGISTRATIONS" not in GOVERNANCE_TABLES
    assert len(GOVERNANCE_TABLES) == 12

    community = ProbeResult(database="pg", connected=True)
    community.governance_tables_required = 0
    assert community.registration_tables_required == 1
    assert community.governance_tables_required == 0

    enterprise = ProbeResult(database="pg", connected=True)
    assert enterprise.registration_tables_required == 1
    assert enterprise.governance_tables_required == 12


def test_catalog_unique_flags_accept_yashandb_and_oracle_forms():
    for value in ("UNIQUE", "Y", "YES", "TRUE", " unique "):
        assert _catalog_index_is_unique(value) is True
    for value in (None, "N", "NO", "FALSE", "NONUNIQUE"):
        assert _catalog_index_is_unique(value) is False


@pytest.mark.parametrize("name", [
    "49_v4_4_8_security_domain_rls.sql",
    "51_v4_4_9_identity_boundary_repair.sql",
    "53_v4_4_9_pg_runtime_boundary.sql",
])
def test_pg_extra_migrations_follow_package_layout(tmp_path, monkeypatch, name):
    monkeypatch.setattr(validator, "REPO_ROOT", tmp_path)
    assert validator._migration_path("pg", name) == tmp_path / "adapters/pg/deploy" / name
    (tmp_path / "build-manifest.json").write_text("{}")
    # Even a missing packaged migration must not fall back to a source tree.
    assert validator._migration_path("pg", name) == tmp_path / "scripts/deploy" / name
