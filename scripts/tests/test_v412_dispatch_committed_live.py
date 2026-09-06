"""Opt-in committed, isolated-database authorization and concurrency tests."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import secrets
import threading
import time

import pytest
try:
    from shared.lib import connection, db4a2a, identity_api
except ModuleNotFoundError:
    from lib import connection, db4a2a, identity_api

pytestmark = pytest.mark.skipif(os.environ.get("CX_V412_COMMITTED_LIVE") != "1",
                                reason="isolated committed database gate required")


@pytest.fixture
def reference():
    from lib.config import get_config
    cfg = get_config().database
    target = str(getattr(cfg, "dbname", "") or getattr(cfg, "dsn", "")).lower()
    assert "cxv412" in target, "refusing non-isolated target"
    agents = connection.execute_query("SELECT AGENT_ID FROM AGENT_REGISTRY WHERE AGENT_ID LIKE :prefix ORDER BY AGENT_ID",
                                      {"prefix": "AGENT_V410_FULL%"})
    assert len(agents) >= 2, "run external enrollment tests first"
    receiver, other = str(agents[0]["agent_id"]), str(agents[1]["agent_id"])
    if connection.DATABASE_DIALECT in {"yashan", "yashandb"}:
        from lib import agent_api
        # Existing enrolled identities must be reconciled through the normal provisioner.
        agent_api.ensure_external_agent_identity(receiver)
        agent_api.ensure_external_agent_identity(other)
    humans = connection.execute_query("SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_TYPE='HUMAN' AND STATUS='ACTIVE'")
    admin = next(str(row["principal_id"]) for row in humans
                 if identity_api.effective_access(str(row["principal_id"]), "agents.manage.all")["decision"] == "ALLOW")
    key = "v412-committed-" + secrets.token_hex(8)
    data = json.dumps({"purpose": key, "amount": 123.45, "items": [1, 2, 3]})
    workspace = context = None
    dispatches = []

    def setup(tx):
        nonlocal workspace, context
        params = {"name": key, "agent": receiver}
        if connection.DATABASE_DIALECT in {"pg", "postgresql"}:
            workspace = tx.query_one("INSERT INTO WORKSPACES(WORKSPACE_NAME,ISOLATION_MODE,CURRENT_AGENT_ID,STATUS) "
                                     "VALUES (:name,'ISOLATED',:agent,'ACTIVE') RETURNING WORKSPACE_ID", params)["workspace_id"]
            context = tx.query_one("INSERT INTO WORKSPACE_CONTEXT(WORKSPACE_ID,AGENT_ID,CONTEXT_TYPE,CONTEXT_DATA,VISIBILITY) "
                                   "VALUES (:ws,:agent,'CHECKPOINT',:data,'PRIVATE') RETURNING CONTEXT_ID",
                                   {"ws": workspace, "agent": receiver, "data": data})["context_id"]
        else:
            workspace, context = "WS_" + secrets.token_hex(10), "CTX_" + secrets.token_hex(10)
            tx.execute("INSERT INTO WORKSPACES(WORKSPACE_ID,WORKSPACE_NAME,ISOLATION_MODE,CURRENT_AGENT_ID,STATUS) "
                       "VALUES (:id,:name,'ISOLATED',:agent,'ACTIVE')", {**params, "id": workspace})
            tx.execute("INSERT INTO WORKSPACE_CONTEXT(CONTEXT_ID,WORKSPACE_ID,AGENT_ID,CONTEXT_TYPE,CONTEXT_DATA,VISIBILITY) "
                       "VALUES (:id,:ws,:agent,'CHECKPOINT',:data,'PRIVATE')",
                       {"id": context, "ws": workspace, "agent": receiver, "data": data})
    connection.execute_transaction_callback(setup)
    envelope = db4a2a.build_dispatch(task_id=key, context=db4a2a.ContextReference(
        str(context), db4a2a.context_snapshot(data), 1, "workspace:" + str(workspace)), branch_policy="CHILD_BRANCH_WRITE")
    try:
        yield {"admin": admin, "receiver": receiver, "other": other, "context": context,
               "envelope": envelope, "dispatches": dispatches, "name": key}
    finally:
        connection.set_agent_context(None)
        def cleanup(tx):
            if connection.DATABASE_DIALECT in {"yashan", "yashandb"}:
                tx.execute("DELETE FROM CX_CONTEXT_READ_GRANTS WHERE CONTEXT_ID=:id", {"id": context})
            for dispatch in dispatches:
                tx.execute("DELETE FROM CX_DB4A2A_DISPATCHES WHERE DISPATCH_ID=:id", {"id": dispatch})
            tx.execute("DELETE FROM CONTEXT_BRANCHES WHERE WORKSPACE_ID=:ws", {"ws": workspace})
            tx.execute("DELETE FROM WORKSPACE_CONTEXT WHERE WORKSPACE_ID=:ws", {"ws": workspace})
            tx.execute("DELETE FROM WORKSPACES WHERE WORKSPACE_ID=:ws", {"ws": workspace})
        connection.execute_transaction_callback(cleanup)


def test_receiver_database_policy_rejects_private_context(reference):
    r = reference
    db4a2a._check_context_reader(r["receiver"], str(r["context"]))
    with pytest.raises(PermissionError):
        db4a2a._check_context_reader(r["other"], str(r["context"]))
    with pytest.raises(PermissionError):
        db4a2a.persist_dispatch(r["admin"], r["other"], r["envelope"])
    assert connection.get_current_agent_id() is None


def test_sender_cannot_borrow_receiver_private_context(reference):
    r = reference
    def check(tx):
        context = db4a2a._check_context(tx, r["envelope"])
        db4a2a._check_context_sender(tx, r["receiver"], context)
        with pytest.raises(PermissionError):
            db4a2a._check_context_sender(tx, r["other"], context)
    connection.execute_transaction_callback(check)


def test_two_clients_get_one_durable_branch(reference):
    r = reference
    dispatch = db4a2a.persist_dispatch(r["admin"], r["receiver"], r["envelope"])["dispatch_id"]
    r["dispatches"].append(dispatch)
    barrier = threading.Barrier(2)
    def fork(index):
        barrier.wait(timeout=10)
        return db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"] + str(index), "real concurrent test")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(fork, [1, 2]))
    assert results[0]["branch_id"] == results[1]["branch_id"]
    assert sorted(result["idempotent"] for result in results) == [False, True]
    persisted = connection.execute_query_one("SELECT CHILD_BRANCH_ID,STATUS FROM CX_DB4A2A_DISPATCHES WHERE DISPATCH_ID=:id", {"id": dispatch})
    assert str(persisted["child_branch_id"]) == results[0]["branch_id"]
    assert persisted["status"] == "BRANCHED"


def test_committed_dispatch_survives_connection_recreation(reference):
    r = reference
    dispatch = db4a2a.persist_dispatch(r["admin"], r["receiver"], r["envelope"])["dispatch_id"]
    r["dispatches"].append(dispatch)
    connection.close_end_user_connections()
    result = db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"], "recreated connection")
    assert result["branch_id"]
    with pytest.raises((PermissionError, db4a2a.DB4A2AError)):
        db4a2a.create_dispatch_branch(r["other"], dispatch, "denied", "unrelated actor")


def test_yashan_base_table_and_mapping_cannot_bypass_view(reference):
    if connection.DATABASE_DIALECT not in {"yashan", "yashandb"}:
        pytest.skip("YashanDB scoped-view contract")
    connection.set_agent_context(reference["other"])
    try:
        for table in ("WORKSPACE_CONTEXT", "CX_AGENT_DB_IDENTITIES", "CX_CONTEXT_READ_GRANTS"):
            with pytest.raises(Exception):
                connection.execute_query(f"SELECT * FROM {table}")
        with pytest.raises(Exception):
            connection.execute("UPDATE CX_AGENT_DB_IDENTITIES SET AGENT_ID=:id", {"id": reference["receiver"]})
    finally:
        connection.set_agent_context(None)


def test_concurrent_receiver_sessions_are_distinct(reference):
    barrier = threading.Barrier(2)
    def inspect(_):
        connection.set_agent_context(reference["receiver"])
        try:
            with connection.get_connection_for_agent() as conn:
                barrier.wait(timeout=10)
                with conn.cursor() as cur:
                    cur.execute("SELECT 1" + connection.scalar_select_suffix())
                    assert cur.fetchone()[0] == 1
                return id(conn)
        finally:
            connection.set_agent_context(None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        identifiers = list(pool.map(inspect, (1, 2)))
    assert identifiers[0] != identifiers[1]


def test_yashan_explicit_share_and_revocation(reference):
    if connection.DATABASE_DIALECT not in {"yashan", "yashandb"}:
        pytest.skip("YashanDB scoped-view contract")
    r = reference
    connection.execute("UPDATE WORKSPACE_CONTEXT SET VISIBILITY='SHARED' WHERE CONTEXT_ID=:id", {"id": r["context"]})
    with pytest.raises(PermissionError):
        db4a2a._check_context_reader(r["other"], str(r["context"]))
    connection.execute("INSERT INTO CX_CONTEXT_READ_GRANTS(CONTEXT_ID,AGENT_ID) VALUES (:id,:agent)",
                       {"id": r["context"], "agent": r["other"]})
    db4a2a._check_context_reader(r["other"], str(r["context"]))
    dispatch = db4a2a.persist_dispatch(r["admin"], r["other"], r["envelope"])["dispatch_id"]
    r["dispatches"].append(dispatch)
    db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"], "shared branch")
    connection.execute("DELETE FROM CX_CONTEXT_READ_GRANTS WHERE CONTEXT_ID=:id", {"id": r["context"]})
    with pytest.raises(PermissionError):
        db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"], "revoked idempotent retry")


def test_yashan_share_revoke_waits_for_branch_transaction(reference, monkeypatch):
    if connection.DATABASE_DIALECT not in {"yashan", "yashandb"}:
        pytest.skip("YashanDB explicit-share lock contract")
    r = reference
    connection.execute("UPDATE WORKSPACE_CONTEXT SET VISIBILITY='SHARED' WHERE CONTEXT_ID=:id", {"id": r["context"]})
    connection.execute("INSERT INTO CX_CONTEXT_READ_GRANTS(CONTEXT_ID,AGENT_ID) VALUES (:id,:agent)",
                       {"id": r["context"], "agent": r["other"]})
    dispatch = db4a2a.persist_dispatch(r["admin"], r["other"], r["envelope"])["dispatch_id"]
    r["dispatches"].append(dispatch)
    checked, release, revoking = threading.Event(), threading.Event(), threading.Event()
    original = db4a2a._check_context_reader

    def pause(reader, context):
        original(reader, context)
        checked.set()
        assert release.wait(10), "test failed to release branch transaction"

    def revoke():
        revoking.set()
        connection.execute("DELETE FROM CX_CONTEXT_READ_GRANTS WHERE CONTEXT_ID=:id", {"id": r["context"]})

    monkeypatch.setattr(db4a2a, "_check_context_reader", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        branch = pool.submit(db4a2a.create_dispatch_branch, r["admin"], dispatch, r["name"], "concurrent revoke")
        try:
            assert checked.wait(10)
            revoked = pool.submit(revoke)
            assert revoking.wait(5)
            time.sleep(0.2)
            assert not revoked.done(), "share deletion must wait for the authorized transaction"
        finally:
            release.set()
        assert branch.result(timeout=10)["branch_id"]
        revoked.result(timeout=10)
    monkeypatch.setattr(db4a2a, "_check_context_reader", original)
    with pytest.raises(PermissionError):
        db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"], "post-revoke retry")


@pytest.mark.parametrize("participant", ["admin", "receiver"])
def test_participant_revocation_serializes_with_branch(reference, monkeypatch, participant):
    r = reference
    principal = r[participant]
    original_status = connection.execute_query_one(
        "SELECT STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id", {"id": principal})["status"]
    dispatch = db4a2a.persist_dispatch(r["admin"], r["receiver"], r["envelope"])["dispatch_id"]
    r["dispatches"].append(dispatch)
    checked, release, revoking = threading.Event(), threading.Event(), threading.Event()
    original = db4a2a._check_context_reader

    def pause(reader, context):
        original(reader, context)
        checked.set()
        assert release.wait(10), "branch transaction was not released"

    def revoke():
        revoking.set()
        connection.execute("UPDATE CX_PRINCIPALS SET STATUS='SUSPENDED' WHERE PRINCIPAL_ID=:id",
                           {"id": principal})

    monkeypatch.setattr(db4a2a, "_check_context_reader", pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            branch = pool.submit(db4a2a.create_dispatch_branch, r["admin"], dispatch, r["name"], "participant revoke race")
            try:
                assert checked.wait(10)
                revoked = pool.submit(revoke)
                assert revoking.wait(5)
                time.sleep(0.2)
                assert not revoked.done(), "revocation must wait for the authorized transaction"
            finally:
                release.set()
            assert branch.result(timeout=10)["branch_id"]
            revoked.result(timeout=10)
        monkeypatch.setattr(db4a2a, "_check_context_reader", original)
        with pytest.raises((PermissionError, db4a2a.DB4A2AError)):
            db4a2a.create_dispatch_branch(r["admin"], dispatch, r["name"], "post-participant-revoke retry")
    finally:
        connection.set_agent_context(None)
        connection.execute("UPDATE CX_PRINCIPALS SET STATUS=:status WHERE PRINCIPAL_ID=:id",
                           {"status": original_status, "id": principal})
        assert connection.execute_query_one(
            "SELECT STATUS FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id", {"id": principal})["status"] == original_status
