from datetime import datetime
from unittest.mock import Mock

import pytest
from lib import compliance_api as api


@pytest.fixture
def review(monkeypatch):
    monkeypatch.setattr(api, "_enterprise_enabled", lambda: True)
    monkeypatch.setattr(api, "_require", Mock())
    monkeypatch.setattr(api, "_visible", Mock())
    monkeypatch.setattr(api, "_audit_tx", Mock())
    finding = {"finding_id": "finding", "agent_id": "agent", "status": "OPEN", "last_observed_at": datetime(2026, 9, 9)}
    def query(sql, params):
        return {"principal_type": "HUMAN", "status": "ACTIVE"} if "CX_PRINCIPALS" in sql else finding
    tx = Mock(query_one=Mock(side_effect=query), execute=Mock(return_value=1))
    monkeypatch.setattr(api.connection, "execute_transaction_callback", lambda fn: fn(tx))
    return tx, finding


def run(**overrides):
    args = dict(actor="reviewer", finding_id="finding", decision="RESOLVE", reason="Inspected repair", evidence_ref="ticket:123",
                expected_status="OPEN", expected_observed_at="2026-09-09T00:00:00")
    return api.review_finding(**(args | overrides))


def test_resolve_audits_without_restoring_agent_authority(review):
    tx, _ = review
    assert run() == {"finding_id": "finding", "status": "RESOLVED", "agent_control_changed": False}
    assert len(tx.execute.call_args_list) == 2
    assert all("CX_COMPLIANCE_" in c.args[0] for c in tx.execute.call_args_list)
    assert "ticket:123" in api._audit_tx.call_args.args[-1]


@pytest.mark.parametrize("overrides", [{"evidence_ref": ""}, {"expected_status": "ACKNOWLEDGED"},
    {"expected_observed_at": "2026-09-08T00:00:00"}, {"decision": "REOPEN"}, {"reason": "x"},
    {"reason": "x" * 1900, "evidence_ref": "y" * 1900}])
def test_invalid_or_stale_review_writes_nothing(review, overrides):
    with pytest.raises(api.ComplianceError): run(**overrides)
    review[0].execute.assert_not_called()


@pytest.mark.parametrize("denial", ["community", "permission", "scope", "agent"])
def test_review_rejects_unauthorized_before_mutation(review, monkeypatch, denial):
    if denial == "community": monkeypatch.setattr(api, "_enterprise_enabled", lambda: False)
    if denial == "permission": monkeypatch.setattr(api, "_require", Mock(side_effect=PermissionError()))
    if denial == "scope": monkeypatch.setattr(api, "_visible", Mock(side_effect=PermissionError()))
    if denial == "agent": review[0].query_one.side_effect = lambda *_: {"principal_type": "AGENT", "status": "ACTIVE"}
    with pytest.raises((api.ComplianceError, PermissionError)): run()
    review[0].execute.assert_not_called()


def test_acknowledge_leaves_remediation_and_controls_unchanged(review):
    assert run(decision="ACKNOWLEDGE", evidence_ref="")["status"] == "ACKNOWLEDGED"
    assert review[0].execute.call_count == 1
