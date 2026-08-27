import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    from shared.lib import model_governance_api as governance
    from shared.lib import model_usage_api
except ModuleNotFoundError:  # generated edition
    from lib import model_governance_api as governance
    from lib import model_usage_api


ROOT = Path(__file__).resolve().parents[2]
GENERATED = (ROOT / "build-manifest.json").is_file()


class FakeTx:
    def __init__(self, rows=None, one=None):
        self.rows = rows or []
        self.one = one or {}
        self.writes = []

    def query(self, _sql, _params=None):
        return list(self.rows)

    def query_one(self, sql, _params=None):
        return dict(self.one(sql) if callable(self.one) else self.one)

    def execute(self, sql, params=None):
        self.writes.append((sql, params or {}))
        return 1


def allow(monkeypatch):
    monkeypatch.setattr(governance.identity_api, "effective_access", lambda *_args, **_kwargs: {"decision": "ALLOW"})


@pytest.mark.skipif(GENERATED, reason="cross-adapter migration equivalence is a unified-source gate")
def test_migration_57_is_equivalent_and_pg_forces_rls():
    required = {
        "CX_MODEL_QUOTA_POLICIES", "CX_MODEL_QUOTA_RESERVATIONS", "CX_MODEL_REPLAY_SNAPSHOTS",
        "CX_PROVIDER_INVOICE_BATCHES", "CX_PROVIDER_INVOICE_LINES", "CX_MODEL_RECONCILIATIONS",
        "CX_PROVIDER_INVOICE_CORRECTIONS",
        "CX_MODEL_ALLOCATION_RULES", "CX_MODEL_ALLOCATIONS", "CX_MODEL_EVIDENCE_ADAPTERS",
        "CX_MODEL_EVIDENCE_BATCHES", "CX_WALLBOARD_DEF_VERSIONS", "CX_WALLBOARD_PUBLICATIONS",
    }
    for database in ("oracle", "pg", "yashandb"):
        source = (ROOT / "adapters" / database / "deploy" / "57_v4_4_10_complete_model_governance.sql").read_text(encoding="utf-8").upper()
        assert required <= {name for name in required if name in source}
        assert "CORRELATION_ID" in source
        assert "CURRENT_MARKER" in source
        if database == "pg":
            assert source.count("FORCE ROW LEVEL SECURITY") >= 12
            assert "PUBLIC.CURRENT_AGENT_IDENTITY()" in source


def test_hard_quota_rejects_before_reservation_insert(monkeypatch):
    policy = {"policy_id": "P1", "policy_key": "monthly", "scope_type": "GLOBAL", "scope_id": None, "metric": "TOKEN", "limit_value": "100", "currency": None, "enforcement": "HARD", "window_type": "MONTHLY", "reservation_value": "20", "incomplete_policy": "CHARGE_RESERVED"}
    monkeypatch.setattr(governance.connection, "execute_query", lambda sql, _params=None: [policy] if "CX_MODEL_QUOTA_POLICIES WHERE" in sql else [])
    tx = FakeTx(one=lambda sql: {"policy_id": "P1", "limit_value": "100", "reservation_value": "20", "enforcement": "HARD", "window_type": "MONTHLY"} if "FOR UPDATE" in sql else {"committed": "80", "reserved": "10"})
    monkeypatch.setattr(governance.connection, "execute_transaction_callback", lambda callback: callback(tx))
    with pytest.raises(governance.QuotaExceeded):
        governance.reserve_quota("R1", "HP1", "", "", "PROFILE", "MODEL")
    assert tx.writes == []


def test_warn_quota_reserves_and_reports_warning(monkeypatch):
    policy = {"policy_id": "P1", "policy_key": "daily", "scope_type": "GLOBAL", "scope_id": None, "metric": "TOKEN", "limit_value": "10", "currency": None, "enforcement": "WARN", "window_type": "DAILY", "reservation_value": "20", "incomplete_policy": "RELEASE"}
    monkeypatch.setattr(governance.connection, "execute_query", lambda sql, _params=None: [policy] if "CX_MODEL_QUOTA_POLICIES WHERE" in sql else [])
    tx = FakeTx(one=lambda sql: {"policy_id": "P1", "limit_value": "10", "reservation_value": "20", "enforcement": "WARN", "window_type": "DAILY"} if "FOR UPDATE" in sql else {"committed": 0, "reserved": 0})
    monkeypatch.setattr(governance.connection, "execute_transaction_callback", lambda callback: callback(tx))
    result = governance.reserve_quota("R1", "HP1", "", "", "PROFILE", "MODEL")
    assert result["warnings"]
    assert tx.writes[0][1]["warning"] == "quota threshold exceeded"


def test_incomplete_quota_respects_release_and_charge_policy(monkeypatch):
    tx = FakeTx(rows=[
        {"reservation_id": "A", "reserved_value": "5", "metric": "TOKEN", "currency": None, "incomplete_policy": "RELEASE"},
        {"reservation_id": "B", "reserved_value": "7", "metric": "TOKEN", "currency": None, "incomplete_policy": "CHARGE_RESERVED"},
    ])
    monkeypatch.setattr(governance.connection, "execute_transaction_callback", lambda callback: callback(tx))
    governance.settle_quota("R1", None, None, "", incomplete=True)
    assert [(item[1]["status"], item[1]["value"]) for item in tx.writes] == [("RELEASED", None), ("SETTLED_INCOMPLETE", "7")]


def test_replay_snapshot_is_digest_bound_and_marked(monkeypatch):
    try:
        from shared.lib import connection_crypto
    except ModuleNotFoundError:
        from lib import connection_crypto
    writes = []
    monkeypatch.setattr(connection_crypto, "encrypt_section", lambda value: "cipher:" + governance._digest(value))
    monkeypatch.setattr(connection_crypto, "decrypt_section", lambda _cipher: {"response": {"request_id": "R1", "choices": []}})
    monkeypatch.setattr(governance.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    governance.save_replay_snapshot("R1", {"request_id": "R1", "choices": []})
    stored = writes[0][1]
    assert ":size" not in writes[0][0] and ":expires)" not in writes[0][0]
    assert stored["byte_count"] > 0 and stored["expires_at"] is not None
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: {"response_cipher": stored["cipher"], "response_digest": stored["digest"]})
    assert governance.replay_snapshot("R1")["replayed"] is True
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: {"response_cipher": stored["cipher"], "response_digest": "wrong"})
    with pytest.raises(governance.ReplayUnavailable):
        governance.replay_snapshot("R1")


def test_idempotent_success_replays_without_dispatch(monkeypatch):
    monkeypatch.setattr(model_usage_api.connection, "execute_query_one", lambda *_args, **_kwargs: {"request_id": "R1", "input_digest": "same", "status": "SUCCEEDED"})
    monkeypatch.setattr(model_usage_api.model_governance_api, "replay_snapshot", lambda request: {"request_id": request, "replayed": True})
    assert model_usage_api._idempotent_replay("HP1", "key", "same")["replayed"] is True
    with pytest.raises(model_usage_api.ModelUsageConflict):
        model_usage_api._idempotent_replay("HP1", "key", "different")


def test_usage_insert_binds_every_declared_placeholder(monkeypatch):
    import re

    writes = []
    monkeypatch.setattr(model_usage_api, "_price", lambda *_args: {"cost": "0.100000", "currency": "CNY", "pricing_version": "v1"})
    monkeypatch.setattr(model_usage_api.model_governance_api, "settle_quota", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(model_usage_api.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    model_usage_api._write_usage(
        "REQ1", "HP1", "", "provider", "model",
        {"prompt_tokens": 5, "completion_tokens": 3, "cached_tokens": None, "reasoning_tokens": None, "total_tokens": 8},
        "PROVIDER_REPORTED", 0, "SUCCEEDED", "idem",
    )
    sql, params = writes[0]
    assert set(re.findall(r":([a-z_]+)", sql)) <= set(params)
    assert params["prompt"] == 5 and params["completion"] == 3 and params["price"] == "v1"


def test_quota_status_returns_a_bounded_count(monkeypatch):
    allow(monkeypatch)
    monkeypatch.setattr(governance.connection, "execute_query", lambda *_args, **_kwargs: [
        {"policy_id": "P1", "limit_value": "10", "committed": "2", "reserved": "1"},
    ])
    result = governance.quota_status("ADMIN", 10)
    assert result["count"] == 1
    assert result["items"][0]["remaining"] == "7.000000"


def test_effective_dated_defaults_use_database_clock(monkeypatch):
    allow(monkeypatch)
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: {"version": 0})
    writes = []
    monkeypatch.setattr(governance.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    governance.create_quota_policy("ADMIN", {
        "policy_key": "clock", "scope_type": "GLOBAL", "metric": "TOKEN", "limit_value": "10",
        "enforcement": "WARN", "window_type": "DAILY", "reservation_value": "1",
        "incomplete_policy": "RELEASE", "reason": "database clock contract",
    })
    assert "CURRENT_TIMESTAMP" in writes[0][0]
    assert "effective_from" not in writes[0][1]


def test_invoice_import_requires_balanced_lines(monkeypatch):
    allow(monkeypatch)
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: None)
    tx = FakeTx()
    monkeypatch.setattr(governance.connection, "execute_transaction_callback", lambda callback: callback(tx))
    body = {"provider_key": "P", "external_invoice_id": "I", "currency": "CNY", "period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z", "total_amount": "10", "reason": "billing review", "lines": [{"external_line_id": "1", "amount": "9"}]}
    with pytest.raises(governance.ModelGovernanceError, match="must equal"):
        governance.import_invoice("ADMIN", body)


def test_allocation_rule_requires_exactly_one_hundred_percent(monkeypatch):
    allow(monkeypatch)
    if GENERATED:
        from lib import edition_features
        if str(edition_features.EDITION).lower() != "enterprise":
            with pytest.raises(governance.ModelGovernanceError, match="Enterprise"):
                governance.create_allocation_rule("ADMIN", {"rule_key": "r", "reason": "cost center", "targets": [{"target_type": "COST_CENTER", "target_id": "A", "percentage": "60"}]})
            return
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: {"version": 0})
    with pytest.raises(governance.ModelGovernanceError, match="exactly 100"):
        governance.create_allocation_rule("ADMIN", {"rule_key": "r", "reason": "cost center", "targets": [{"target_type": "COST_CENTER", "target_id": "A", "percentage": "60"}]})


def test_signed_external_evidence_is_verified_and_idempotent(monkeypatch):
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    body = {"adapter_id": "A", "key_version": 1, "sequence_no": 1, "nonce": "nonce-123456", "observed_from": (now - timedelta(minutes=1)).isoformat(), "observed_to": now.isoformat(), "facts": {"provider_key": "openai", "agent_id": "AG1", "request_count": 2, "total_tokens": 30}}
    canonical = {**body, "observed_from": governance._parse_time(body["observed_from"], required=True).isoformat(), "observed_to": governance._parse_time(body["observed_to"], required=True).isoformat()}
    body["signature"] = base64.b64encode(private.sign(governance._json(canonical).encode())).decode()
    calls = 0
    def one(sql, _params=None):
        nonlocal calls
        calls += 1
        if "CX_MODEL_EVIDENCE_ADAPTERS" in sql:
            return {"verification_key": public, "scopes_json": '["provider:openai","agent:AG1"]', "status": "ACTIVE"}
        return None
    writes = []
    monkeypatch.setattr(governance.connection, "execute_query_one", one)
    monkeypatch.setattr(governance.connection, "execute", lambda sql, params: writes.append((sql, params)) or 1)
    result = governance.ingest_external_evidence(body, "corr-123456")
    assert result["usage_provenance"] == "EXTERNALLY_VERIFIED"
    assert body["signature"] not in str(writes[0][1])
    stored_digest = writes[0][1]["digest"]
    lookup = 0
    def existing(sql, _params=None):
        nonlocal lookup
        lookup += 1
        if "CX_MODEL_EVIDENCE_ADAPTERS" in sql:
            return {"verification_key": public, "scopes_json": '["provider:openai","agent:AG1"]', "status": "ACTIVE"}
        return {"batch_id": result["batch_id"], "payload_digest": stored_digest}
    monkeypatch.setattr(governance.connection, "execute_query_one", existing)
    assert governance.ingest_external_evidence(body, "corr-123456")["idempotent"] is True
    bad = dict(body); bad["facts"] = {**body["facts"], "request_count": 3}
    with pytest.raises(governance.EvidenceRejected, match="signature"):
        governance.ingest_external_evidence(bad, "corr-123456")


def test_wallboard_definition_allowlist_and_projection():
    config = governance.validate_wallboard_config({"widgets": ["agent_overview", "coverage"], "refresh_seconds": 20, "locale": "zh-CN"}, {})
    result = governance.filter_wallboard_projection({"definition_id": "D", "definition_version": 1, "definition_name": "N", "generated_at": "now", "freshness": "CURRENT", "scope": "authorized", "partial": False, "widgets": config["widgets"], "refresh_seconds": 20, "agents": {"total": 1}, "coverage": {"gateway_observed_requests": 1}, "model_usage": [{"secret": "never"}]}, {"config": config})
    assert "agents" in result and "coverage" in result
    assert "model_usage" not in result
    with pytest.raises(governance.ModelGovernanceError):
        governance.validate_wallboard_config({"widgets": ["agent_overview", "select password from users"]}, {})


def test_wallboard_definition_version_is_cross_adapter_integer(monkeypatch):
    allow(monkeypatch)
    monkeypatch.setattr(governance.connection, "execute_query_one", lambda *_args, **_kwargs: {
        "version_id": "V1", "definition_id": "D1", "version": Decimal("1"), "display_name": "Board",
        "config_json": '{"widgets":["agent_overview"]}', "scope_json": "{}",
    })
    result = governance.resolve_wallboard_definition("ADMIN", "D1")
    assert result["version"] == 1
    assert isinstance(result["version"], int)


def test_wallboard_scope_is_pushed_into_usage_sql(monkeypatch):
    monkeypatch.setattr(model_usage_api.identity_api, "_agent_visibility_clause", lambda _actor: "p.PRINCIPAL_ID='VISIBLE'")
    sql, params = model_usage_api._usage_scope("HP1", resource_scope={"organization_id": "ORG1", "security_domain_id": "DOM1"})
    assert "CX_ORGANIZATION_MEMBERS" in sql and "CX_ORGANIZATION_CLOSURE" in sql
    assert "CX_AGENT_RELATIONSHIPS" in sql and "PRIMARY_OWNER" in sql and "CX_DOMAIN_MEMBERS" in sql
    assert params["wallboard_org"] == "ORG1" and params["wallboard_domain"] == "DOM1"


@pytest.mark.skipif(GENERATED, reason="route source inspection is a unified-source gate")
def test_v410_public_error_contract_and_routes_are_present():
    source = (ROOT / "shared" / "web_app.py").read_text(encoding="utf-8")
    for marker in ("correlation_id", "retryable", "X-Correlation-ID", "/api/model-gateway/quotas", "/api/model-finance/overview", "/api/model-evidence/ingest", "/api/wallboard/definitions"):
        assert marker in source


@pytest.mark.skipif(GENERATED, reason="frontend source inspection is a unified-source gate")
def test_model_governance_forms_have_responsive_non_overlapping_layout():
    css = (ROOT / "shared" / "web" / "src" / "app.css").read_text(encoding="utf-8")
    assert ".model-governance-panel .config-field.config-multiline" in css
    assert "grid-template-rows: 16px auto minmax(22px, auto)" in css
    assert ".governance-action-forms > .compact-configuration-form" in css
    assert "@media (max-width: 1180px) { .governance-action-forms { grid-template-columns: 1fr; } }" in css
    assert "@media (max-width: 520px)" in css
