import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from lib import governed_approval as approval
from lib import admin_management


@pytest.fixture
def approved(monkeypatch):
    binding = {"profile_version_id": "v1", "content_digest": "a" * 64}
    payload = {"binding": binding, "binding_digest": approval.digest(binding), "requested_by": "requester",
               "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
    row = {"action_id": "a1", "action_type": "PLATFORM_COMPLIANCE_PROFILE_PUBLISH", "channel_id": "CH_PLATFORM_ADMINISTRATION",
           "proposed_by": "requester", "decided_by": "reviewer", "status": "CONFIRMED", "payload_json": json.dumps(payload)}
    tx = Mock(query_one=Mock(side_effect=lambda sql, params: row if "CX_ACTION_CARDS" in sql else {"principal_type": "HUMAN", "status": "ACTIVE"}))
    monkeypatch.setattr(approval.identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    monkeypatch.setattr(approval.identity_api, "_assert_channel_member", Mock())
    return tx, row, payload, binding


def verify(tx, binding):
    return approval.require_tx(tx, "a1", "PLATFORM_COMPLIANCE_PROFILE_PUBLISH", binding, "agents.manage")


def test_matching_independent_approval(approved):
    tx, row, _, binding = approved
    assert verify(tx, binding)["action_id"] == "a1"
    tx.execute.assert_not_called()


@pytest.mark.parametrize("fault", ["self", "expired", "content", "digest", "status", "type", "channel", "requester"])
def test_invalid_binding_fails_before_effect(approved, fault):
    tx, row, payload, binding = approved
    if fault == "self": row["decided_by"] = row["proposed_by"]
    elif fault == "expired": payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    elif fault == "content": binding = {**binding, "profile_version_id": "v2"}
    elif fault == "digest": payload["binding_digest"] = "0" * 64
    elif fault == "status": row["status"] = "PROPOSED"
    elif fault == "type": row["action_type"] = "PLATFORM_OTHER"
    elif fault == "channel": row["channel_id"] = "OTHER"
    elif fault == "requester": payload["requested_by"] = "someone-else"
    row["payload_json"] = json.dumps(payload)
    with pytest.raises(approval.ApprovalRequired): verify(tx, binding)
    tx.execute.assert_not_called()


def test_revoked_approver_cannot_authorize_execution(approved, monkeypatch):
    tx, _, _, binding = approved
    monkeypatch.setattr(approval.identity_api, "effective_access", lambda principal, _: {"decision": "DENY" if principal == "reviewer" else "ALLOW"})
    with pytest.raises(approval.ApprovalRequired): verify(tx, binding)


def test_missing_approval_does_not_query_database():
    tx = Mock()
    with pytest.raises(approval.ApprovalRequired):
        approval.require_tx(tx, "", "PLATFORM_COMPLIANCE_PROFILE_PUBLISH", {}, "agents.manage")
    tx.query_one.assert_not_called()


def test_high_impact_containment_creates_bound_action_card(monkeypatch):
    monkeypatch.setattr(admin_management, "_require_manage", lambda _actor: None)
    requested = Mock(return_value={"action_id": "ACT1"})
    monkeypatch.setattr(admin_management.governed_approval, "request", requested)
    result = admin_management.request_containment("requester", "A1", "I1", "quarantine", "incident response", 300)
    assert result["action_id"] == "ACT1"
    requested.assert_called_once_with("requester", "PLATFORM_AGENT_CONTAINMENT", {
        "agent_id": "A1", "instance_id": "I1", "requested_state": "QUARANTINE",
        "reason": "incident response", "expires_seconds": 300,
    }, "incident response")


def test_high_impact_containment_requires_matching_approval(monkeypatch):
    monkeypatch.setattr(admin_management, "_require_manage", lambda _actor: None)
    callback = Mock(side_effect=approval.ApprovalRequired("approval required"))
    monkeypatch.setattr(admin_management.connection, "execute_transaction_callback", callback)
    with pytest.raises(approval.ApprovalRequired):
        admin_management.issue_containment("requester", "A1", "I1", "QUARANTINE", "incident response")
    callback.assert_called_once()
