"""Sender authorization is independent of the receiver's read grant."""

from unittest.mock import Mock

import pytest

try:
    from shared.lib import db4a2a, identity_api
except ModuleNotFoundError:
    from lib import db4a2a, identity_api


@pytest.mark.parametrize("kind,status,owner,admin,allowed", [
    ("HUMAN", "ACTIVE", True, False, True),
    ("HUMAN", "ACTIVE", False, False, False),
    ("HUMAN", "ACTIVE", False, True, True),
    ("HUMAN", "DISABLED", True, True, False),
    ("SERVICE", "ACTIVE", True, True, False),
    ("AGENT", "ACTIVE", False, False, True),
])
def test_sender_scope(monkeypatch, kind, status, owner, admin, allowed):
    tx = Mock()
    tx.query_one.side_effect = [{"principal_type": kind, "status": status},
                                {"workspace_id": "W"} if owner else None]
    reader = Mock()
    monkeypatch.setattr(db4a2a, "_check_context_reader", reader)
    monkeypatch.setattr(identity_api, "effective_access", lambda *_: {"decision": "ALLOW" if admin else "DENY"})
    context = {"context_id": "C", "workspace_id": "W"}
    if allowed:
        db4a2a._check_context_sender(tx, "sender", context)
    else:
        with pytest.raises(PermissionError):
            db4a2a._check_context_sender(tx, "sender", context)
    if kind == "AGENT" and allowed:
        reader.assert_called_once_with("sender", "C")
    else:
        reader.assert_not_called()


def test_sender_agent_cannot_borrow_receiver_visibility(monkeypatch):
    tx = Mock()
    tx.query_one.return_value = {"principal_type": "AGENT", "status": "ACTIVE"}
    reader = Mock(side_effect=PermissionError("private context"))
    monkeypatch.setattr(db4a2a, "_check_context_reader", reader)
    with pytest.raises(PermissionError, match="private context"):
        db4a2a._check_context_sender(tx, "sender", {"context_id": "C", "workspace_id": "W"})
    reader.assert_called_once_with("sender", "C")
