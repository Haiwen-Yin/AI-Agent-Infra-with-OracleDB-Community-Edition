from unittest.mock import Mock
from decimal import Decimal

import pytest

try:
    from shared.lib import branch_api, connection, db4a2a, identity_api
except ModuleNotFoundError:
    from lib import branch_api, connection, db4a2a, identity_api


@pytest.fixture
def dispatch(monkeypatch):
    item = dict(dispatch_id="D1", sender_principal_id="sender", receiver_agent_id="receiver",
                context_ref="C1", snapshot_digest=db4a2a.context_snapshot({"text": "context"}), expected_version=1,
                scope_ref="workspace:W1", branch_policy="CHILD_BRANCH_WRITE", status="DISPATCHED",
                child_branch_id=None, transport="DB_MEDIATED", source_branch=None)
    query = Mock(side_effect=lambda sql, params: item if "CX_DB4A2A" in sql else
                 {"workspace_id": "W1", "context_data": {"text": "context"}, "branch_id": None,
                  "agent_id": "context-author"})
    fork = Mock(return_value="B1")
    write = Mock(return_value=1)
    monkeypatch.setattr(identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    monkeypatch.setattr(db4a2a, "_check_context_sender", Mock())
    monkeypatch.setattr(db4a2a, "_lock_reader_policy", Mock())
    monkeypatch.setattr(connection, "execute_query_one", query)
    monkeypatch.setattr(branch_api, "fork_branch_tx", fork)
    monkeypatch.setattr(identity_api, "_audit_tx", Mock())
    monkeypatch.setattr(connection, "execute_transaction_callback", lambda fn: fn(type("Tx", (), {"execute": write, "query_one": query})()))
    return item, query, fork, write


@pytest.mark.parametrize("existing", [None, "secret-branch"])
def test_unrelated_operator_cannot_read_or_create_branch(dispatch, existing):
    item, query, fork, write = dispatch
    item["child_branch_id"] = existing
    with pytest.raises(db4a2a.DB4A2AError, match="dispatch is unavailable"):
        db4a2a.create_dispatch_branch("unrelated", "D1", "child", "test")
    assert query.call_args.args[1]["actor"] == "unrelated"
    assert "SENDER_PRINCIPAL_ID=:actor OR RECEIVER_AGENT_ID=:actor" in query.call_args.args[0]
    fork.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("field,value", [("snapshot_digest", "sha256:stale"),
                                         ("expected_version", 2), ("scope_ref", "workspace:other"),
                                         ("source_branch", "other")])
def test_stale_reference_fails_before_branch_write(dispatch, field, value):
    item, _, fork, write = dispatch
    item[field] = value
    with pytest.raises(db4a2a.DB4A2AError, match="mismatch"):
        db4a2a.create_dispatch_branch("receiver", "D1", "child", "test")
    fork.assert_not_called()
    write.assert_not_called()


def test_context_digest_is_json_order_independent():
    assert db4a2a.context_snapshot('{"b":2,"a":1}') == db4a2a.context_snapshot({"a": 1, "b": 2})


@pytest.mark.parametrize("outcome", ["visible", "hidden", "error"])
def test_reader_check_restores_identity(monkeypatch, outcome):
    monkeypatch.setattr(connection, "execute_query_one", Mock(
        return_value={"context_id": "C1"} if outcome == "visible" else None,
        side_effect=RuntimeError("database unavailable") if outcome == "error" else None))
    connection.set_agent_context("original")
    try:
        if outcome == "visible":
            db4a2a._check_context_reader("receiver", "C1")
        else:
            with pytest.raises(PermissionError if outcome == "hidden" else RuntimeError):
                db4a2a._check_context_reader("receiver", "C1")
        assert connection.get_current_agent_id() == "original"
    finally:
        connection.set_agent_context(None)


def test_context_digest_preserves_oracle_numeric_precision():
    assert db4a2a.context_snapshot({"n": Decimal("1.00")}) == db4a2a.context_snapshot({"n": 1})
    assert db4a2a.context_snapshot({"n": Decimal("0.12345678901234567890123456789")}) == db4a2a.context_snapshot(
        '{"n":0.12345678901234567890123456789}')
    assert db4a2a.context_snapshot({"n": Decimal("0.12345678901234567890123456789")}) != db4a2a.context_snapshot(
        '{"n":0.12345678901234567890123456788}')
    assert db4a2a.context_snapshot({"n": 1}) != db4a2a.context_snapshot({"n": "1"})
    with pytest.raises(db4a2a.DB4A2AError, match="non-finite"):
        db4a2a.context_snapshot({"n": float("nan")})


@pytest.mark.parametrize("status", ["CANCELLED", "COMPLETED", "FAILED", "", "unknown"])
def test_inactive_dispatch_rejected_before_idempotent_return(dispatch, status):
    item, _, fork, write = dispatch
    item.update(status=status, child_branch_id="B1")
    with pytest.raises(db4a2a.DB4A2AError, match="not active"):
        db4a2a.create_dispatch_branch("receiver", "D1", "child", "test")
    fork.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("actor", ["sender", "receiver"])
def test_participant_can_create_branch_with_scoped_update(dispatch, actor):
    _, _, fork, write = dispatch
    result = db4a2a.create_dispatch_branch(actor, "D1", "child", "test")
    assert result["branch_id"] == "B1"
    assert result["provenance"]["source_context_ref"] == "C1"
    fork.assert_called_once()
    assert fork.call_args.kwargs["source_agent_id"] == "context-author"
    assert write.call_args.args[1]["actor"] == actor
    assert "STATUS='DISPATCHED'" in write.call_args.args[0]


def test_idempotent_branch_does_not_write(dispatch):
    item, _, fork, write = dispatch
    item.update(status="BRANCHED", child_branch_id="B1")
    assert db4a2a.create_dispatch_branch("receiver", "D1", "child", "test")["idempotent"]
    fork.assert_not_called()
    write.assert_not_called()


def test_read_only_dispatch_cannot_return_child(dispatch):
    item, _, fork, write = dispatch
    item.update(branch_policy="READ_ONLY", child_branch_id="B1")
    with pytest.raises(db4a2a.DB4A2AError, match="does not permit"):
        db4a2a.create_dispatch_branch("sender", "D1", "child", "test")
    fork.assert_not_called()
    write.assert_not_called()


def test_fork_failure_does_not_link_nonexistent_branch(dispatch):
    _, _, fork, write = dispatch
    fork.side_effect = RuntimeError("database write failed")
    with pytest.raises(RuntimeError, match="database write failed"):
        db4a2a.create_dispatch_branch("receiver", "D1", "child", "test")
    write.assert_not_called()


def test_database_insert_errors_do_not_return_fake_branch_id(monkeypatch):
    monkeypatch.setattr(branch_api, "DATABASE_DIALECT", "yashandb")
    execute = Mock(side_effect=RuntimeError("database write rejected"))
    monkeypatch.setattr(branch_api, "execute", execute)
    with pytest.raises(RuntimeError, match="database write rejected"):
        branch_api.fork_branch("W1", "C1", "child", "DB4A2A", "receiver")


def test_postgres_does_not_attempt_oracle_procedure(monkeypatch):
    monkeypatch.setattr(branch_api, "DATABASE_DIALECT", "postgresql")
    monkeypatch.setattr(branch_api, "oracledb", object())
    connect = Mock(side_effect=AssertionError("Oracle path must not run"))
    monkeypatch.setattr(branch_api, "get_connection", connect)
    monkeypatch.setattr(branch_api, "execute_insert_returning_id", Mock(return_value="B1"))
    assert branch_api.fork_branch("W1", "C1", "child", "DB4A2A", "receiver") == "B1"
    connect.assert_not_called()
