"""Opt-in, rollback-only database tests; authorization is tested separately."""

import os
import secrets

import pytest

try:
    from shared.lib import branch_api, connection, db4a2a, identity_api
except ModuleNotFoundError:
    from lib import branch_api, connection, db4a2a, identity_api

pytestmark = pytest.mark.skipif(os.environ.get("CX_V412_DISPATCH_LIVE") != "1",
                                reason="explicit configured database dispatch gate required")


class RollbackProbe(Exception):
    pass


@pytest.mark.parametrize("failure", ["none", "link", "audit", "stale"])
def test_real_branch_transaction_rolls_back(monkeypatch, failure):
    dispatch_id = "DBA2A_TEST_" + secrets.token_hex(12)
    branch_name = "v412-rollback-" + secrets.token_hex(10)
    original_transaction = connection.execute_transaction_callback
    monkeypatch.setattr(identity_api, "effective_access", lambda *_: {"decision": "ALLOW"})
    # This rollback-only fixture is not committed and is deliberately invisible
    # to a second database session. Dedicated committed tests cover RLS reads.
    monkeypatch.setattr(db4a2a, "_check_context_reader", lambda *_: None)
    monkeypatch.setattr(db4a2a, "_check_context_sender", lambda *_: None)
    monkeypatch.setattr(db4a2a, "_lock_reader_policy", lambda *_: None)
    observed = []

    def work(tx):
        agent = tx.query_one("SELECT AGENT_ID FROM AGENT_REGISTRY ORDER BY AGENT_ID FETCH FIRST 1 ROWS ONLY")
        assert agent, "initialized test database requires a registered Agent"
        actor = agent["agent_id"]
        data = '{"purpose":"v412 rollback-only test","items":[1,2,3]}'
        if connection.DATABASE_DIALECT in {"postgresql", "pg"}:
            workspace = tx.query_one("INSERT INTO WORKSPACES(WORKSPACE_NAME,STATUS) "
                                     "VALUES (:name,'ACTIVE') RETURNING WORKSPACE_ID", {"name": branch_name})["workspace_id"]
            context_id = tx.query_one("INSERT INTO WORKSPACE_CONTEXT(WORKSPACE_ID,AGENT_ID,CONTEXT_TYPE,CONTEXT_DATA) "
                                      "VALUES (:workspace,:actor,'CHECKPOINT',:data) RETURNING CONTEXT_ID",
                                      dict(workspace=workspace, actor=actor, data=data))["context_id"]
        else:
            workspace, context_id = "WS_" + secrets.token_hex(12), "CTX_" + secrets.token_hex(12)
            tx.execute("INSERT INTO WORKSPACES(WORKSPACE_ID,WORKSPACE_NAME,STATUS) VALUES (:id,:name,'ACTIVE')",
                       dict(id=workspace, name=branch_name))
            tx.execute("INSERT INTO WORKSPACE_CONTEXT(CONTEXT_ID,WORKSPACE_ID,AGENT_ID,CONTEXT_TYPE,CONTEXT_DATA) "
                       "VALUES (:id,:workspace,:actor,'CHECKPOINT',:data)",
                       dict(id=context_id, workspace=workspace, actor=actor, data=data))
        context = dict(context_id=context_id, workspace_id=workspace, context_data=data, branch_id=None)
        digest = db4a2a.context_snapshot(context["context_data"])
        tx.execute("INSERT INTO CX_DB4A2A_DISPATCHES(DISPATCH_ID,TASK_ID,SENDER_PRINCIPAL_ID,"
                   "RECEIVER_AGENT_ID,CONTEXT_REF,SNAPSHOT_DIGEST,EXPECTED_VERSION,SCOPE_REF,"
                   "SOURCE_BRANCH,BRANCH_POLICY,TRANSPORT,STATUS) VALUES "
                   "(:id,:task,:actor,:actor,:context,:digest,1,:scope,:source,'CHILD_BRANCH_WRITE',"
                   "'DB_MEDIATED','DISPATCHED')",
                   dict(id=dispatch_id, task=dispatch_id, actor=actor,
                        context=str(context["context_id"]), digest=digest if failure != "stale" else "sha256:stale",
                        scope="workspace:" + str(context["workspace_id"]),
                        source=str(context["branch_id"]) if context.get("branch_id") else None))

        class Proxy:
            query_one = tx.query_one

            def execute(self, sql, params=None):
                if failure == "link" and sql.startswith("UPDATE CX_DB4A2A_DISPATCHES"):
                    raise RollbackProbe("link")
                return tx.execute(sql, params)

        def audit(*_args):
            if failure == "audit":
                raise RollbackProbe("audit")

        monkeypatch.setattr(identity_api, "_audit_tx", audit)
        monkeypatch.setattr(connection, "execute_transaction_callback", lambda callback: callback(Proxy()))
        result = db4a2a.create_dispatch_branch(actor, dispatch_id, branch_name, "rollback-only database test")
        observed.append(result)
        again = db4a2a.create_dispatch_branch(actor, dispatch_id, branch_name, "repeat")
        assert again["idempotent"] and again["branch_id"] == result["branch_id"]
        raise RollbackProbe("none")

    with pytest.raises((RollbackProbe, db4a2a.DB4A2AError)) as error:
        original_transaction(work)
    if failure == "stale":
        assert "snapshot mismatch" in str(error.value)
    else:
        assert str(error.value) == failure
    assert bool(observed) == (failure == "none")
    assert not connection.execute_query_one("SELECT DISPATCH_ID FROM CX_DB4A2A_DISPATCHES WHERE DISPATCH_ID=:id",
                                            {"id": dispatch_id})
    assert not connection.execute_query_one("SELECT BRANCH_ID FROM CONTEXT_BRANCHES WHERE BRANCH_NAME=:name",
                                            {"name": branch_name})
