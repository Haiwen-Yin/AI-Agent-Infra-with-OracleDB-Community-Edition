"""Static contracts for edition-aware live catalog validation."""

from __future__ import annotations

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
