"""Boundary contracts for governed Security Domain and collaboration binding."""

from pathlib import Path

import pytest

from lib import identity_api, security_domain_api


def test_v443_static_contract_is_complete_for_all_adapters():
    import live_db_validator

    root = Path(__file__).resolve().parents[2]
    for database in ("oracle", "pg", "yashandb"):
        scripts = [root / "adapters" / database / "deploy" / name for name in live_db_validator.V443_MIGRATION_SCRIPTS]
        result = live_db_validator.validate_v443_static_contract(database, scripts)
        assert result["passed"] is True
        assert result["v443_security_domain_binding"]["single_active_group_binding"] is True


def test_legacy_group_is_only_a_candidate_source_not_an_authority():
    root = Path(__file__).resolve().parents[1]
    source = (root / "lib" / "security_domain_api.py").read_text(encoding="utf-8")
    proposal = source.split("def create_conversion_draft", 1)[1].split("def get_conversion_draft", 1)[0]
    assert "'PENDING'" in proposal
    assert "Candidates require explicit confirmation" in proposal
    assert "p.PRINCIPAL_TYPE='AGENT'" in proposal
    assert "p.STATUS IN ('ACTIVE','PENDING_CONFIRMATION')" in proposal
    # The legacy policy is retained in a read-only source snapshot for review,
    # but this proposal path must not write authorization memberships.
    assert "SHARING_POLICY" in proposal.upper()
    assert "INSERT INTO CX_DOMAIN_MEMBERS" not in proposal
    apply = source.split("def apply_conversion_draft", 1)[1]
    assert "DECISION='CONFIRMED'" in apply
    assert "confirmed accountable owner" in apply


def test_channel_rechecks_current_security_domain_membership():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    guard = identity.split("def _assert_channel_member", 1)[1].split("def _assert_thread_member", 1)[0]
    assert "Channel membership is an admission record" in guard
    assert "CX_DOMAIN_MEMBERS" in guard
    assert "Channel Security Domain access denied" in guard
    gateway = (root / "lib" / "agent_gateway_api.py").read_text(encoding="utf-8")
    admission = gateway.split("def add_channel_member", 1)[1].split("def remove_channel_member", 1)[0]
    assert "A Channel is not a way to grant Domain access" in admission
    assert "if not domain_member:" in admission


def test_binding_rejects_second_active_domain_for_one_group(monkeypatch):
    class Tx:
        def query_one(self, sql, params):
            if "CX_DOMAIN_BINDINGS WHERE BINDING_TYPE='LEGACY_COLLAB_GROUP'" in sql:
                return {"binding_id": "DB_EXISTING", "security_domain_id": "SD_OTHER"}
            return None

        def execute(self, sql, params):
            raise AssertionError("a second active binding must not be inserted")

    monkeypatch.setattr(security_domain_api, "_require", lambda *_args: None)
    monkeypatch.setattr(security_domain_api, "_domain_row", lambda *_args, **_kwargs: {"security_domain_id": "SD_NEW"})
    monkeypatch.setattr(security_domain_api.connection, "execute_query_one", lambda sql, params: {"group_id": "CG_A", "status": "ACTIVE"})
    monkeypatch.setattr(security_domain_api.connection, "execute_transaction_callback", lambda callback: callback(Tx()))
    with pytest.raises(security_domain_api.SecurityDomainConflict):
        security_domain_api.create_binding("HP_ADMIN", "SD_NEW", "LEGACY_COLLAB_GROUP", "CG_A", "separate project boundary")


def test_security_domain_conflict_is_not_reported_as_service_unavailable():
    source = Path(__file__).resolve().parents[1].joinpath("web_app.py").read_text(encoding="utf-8")
    mapper = source.split("def _identity_http_error", 1)[1].split("def _optional_module", 1)[0]
    assert "security_domain_api.SecurityDomainConflict" in mapper
    assert "status_code=409" in mapper
    assert "security_domain_api.SecurityDomainError" in mapper
    assert "status_code=400" in mapper


def test_default_domain_cannot_be_created_or_repurposed(monkeypatch):
    monkeypatch.setattr(security_domain_api, "_require", lambda *_args: None)
    with pytest.raises(security_domain_api.SecurityDomainError, match="DEFAULT"):
        security_domain_api.create_domain("HP_ADMIN", "DEFAULT", "wrong", "INTERNAL", "wrong", "HP_OWNER", "wrong")


def test_channel_create_writes_binding_in_the_same_transaction():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    create = identity.split("def create_channel", 1)[1].split("def list_channels", 1)[0]
    assert "CX_DOMAIN_BINDINGS" in create
    assert "connection.execute_transaction_callback(_create)" in create
    assert "'CHANNEL'" in create
