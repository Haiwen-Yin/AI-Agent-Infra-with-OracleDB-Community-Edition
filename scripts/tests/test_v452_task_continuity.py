"""v4.5.2 unified task continuity contract tests.

SQLite is used only as a deterministic transaction harness here.  The
adapter-specific migration gates still execute the generated SQL against each
real database.
"""

from datetime import datetime, timedelta
import sqlite3

import pytest

from lib import task_continuity
from lib.continuity_state import ContinuityConflict, ContinuityError


@pytest.fixture
def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE CX_PRINCIPALS(PRINCIPAL_ID TEXT PRIMARY KEY, PRINCIPAL_TYPE TEXT, STATUS TEXT);
        CREATE TABLE CX_SECURITY_DOMAINS(SECURITY_DOMAIN_ID TEXT PRIMARY KEY, STATUS TEXT);
        CREATE TABLE CX_CONTEXT_ASSEMBLIES(ASSEMBLY_ID TEXT PRIMARY KEY);
        CREATE TABLE AGENT_REGISTRY(AGENT_ID TEXT PRIMARY KEY);
        CREATE TABLE TASK_PLANS(
            PLAN_ID TEXT PRIMARY KEY, AGENT_ID TEXT, GOAL TEXT, STATUS TEXT,
            PRIORITY INTEGER, STRATEGY TEXT
        );
        INSERT INTO CX_PRINCIPALS VALUES('owner','HUMAN','ACTIVE'),('agent-a','AGENT','ACTIVE'),('agent-b','AGENT','ACTIVE');
        INSERT INTO CX_SECURITY_DOMAINS VALUES('domain','ACTIVE');
        INSERT INTO AGENT_REGISTRY VALUES('agent-a'),('agent-b');
    """)
    for statement in task_continuity.schema_statements("pg"):
        db.execute(statement)
    db.commit()

    class Transaction:
        def execute(self, statement, params):
            return db.execute(statement.replace(" FOR UPDATE", ""), params).rowcount

        def query(self, statement, params):
            rows = db.execute(statement.replace(" FOR UPDATE", ""), params).fetchall()
            return [{key.lower(): row[key] for key in row.keys()} for row in rows]

        def query_one(self, statement, params):
            rows = self.query(statement, params)
            return rows[0] if rows else None

    def run(callback):
        try:
            result = callback(Transaction())
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise

    yield db, Transaction, run
    db.close()


def admit(db, run, *, task_id="opaque-business-key", link_id="dispatch-1", idem="idem-1", canonical_task_id=None):
    def work(tx):
        plan = canonical_task_id or task_continuity.ensure_task_root(
            tx, "owner", task_id, goal="DB4A2A test", preferred_agent_id="agent-a")
        return task_continuity.link_protocol_task(
            tx, actor="owner", security_domain_id="domain", link_kind="DB4A2A",
            link_id=link_id, canonical_task_id=plan, idempotency_key=idem,
            request_digest="r" * 64, input_digest="i" * 64, status="PENDING",
        )
    return run(work)


def test_opaque_protocol_key_gets_one_canonical_task_owned_by_receiver(database):
    db, _, run = database
    first = admit(db, run, task_id="business/123")
    plan = db.execute("SELECT PLAN_ID,AGENT_ID FROM TASK_PLANS").fetchone()
    assert plan["PLAN_ID"] == first["canonical_task_id"]
    assert plan["AGENT_ID"] == "agent-a"
    # A repeated protocol admission may reuse the exact canonical plan.
    second = admit(db, run, task_id="business/123", link_id="dispatch-2", idem="idem-2",
                   canonical_task_id=first["canonical_task_id"])
    assert second["canonical_task_id"] == first["canonical_task_id"]
    assert db.execute("SELECT COUNT(*) FROM TASK_PLANS").fetchone()[0] == 1


def test_idempotency_key_replays_without_creating_a_second_link(database):
    db, _, run = database
    first = admit(db, run)
    replay = admit(db, run, link_id="retry-transport-id", canonical_task_id=first["canonical_task_id"])
    assert replay["replayed"] is True
    assert replay["continuity_id"] == first["continuity_id"]
    assert db.execute("SELECT COUNT(*) FROM CX_TASK_CONTINUITY_LINKS").fetchone()[0] == 1
    with pytest.raises(ContinuityConflict):
        def conflicting(tx):
            task_continuity.link_protocol_task(
                tx, actor="owner", security_domain_id="domain", link_kind="DB4A2A",
                link_id="another", canonical_task_id=first["canonical_task_id"],
                idempotency_key="idem-1", request_digest="x" * 64,
            )
        run(conflicting)


def test_active_worker_retry_is_idempotent_and_other_worker_is_fenced(database):
    db, _, run = database
    link = admit(db, run)
    claimed = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-a",
        business_key="send-key", request_digest="r" * 64, lease_seconds=60))
    replay = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-a",
        business_key="send-key", request_digest="r" * 64, lease_seconds=60))
    assert replay["replayed"] is True and replay["attempt_id"] == claimed["attempt_id"]
    with pytest.raises(ContinuityConflict, match="leased"):
        run(lambda tx: task_continuity.claim_attempt(
            tx, continuity_id=link["continuity_id"], worker_id="worker-b",
            business_key="other-send", request_digest="r" * 64, lease_seconds=60))


def test_expired_send_becomes_unobserved_before_any_retry(database):
    db, _, run = database
    link = admit(db, run)
    claimed = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-a",
        business_key="send-key", request_digest="r" * 64, lease_seconds=60))
    expired = (datetime.utcnow() - timedelta(minutes=5)).isoformat(sep=" ")
    db.execute("UPDATE CX_TASK_CONTINUITY_LEASES SET LEASE_EXPIRES_AT=?", (expired,))
    db.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET LEASE_EXPIRES_AT=?", (expired,))
    db.commit()
    refusal = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-b",
        business_key="retry", request_digest="r" * 64, lease_seconds=60))
    assert refusal["status"] == "UNOBSERVED" and refusal["reconciliation_required"] is True
    assert db.execute("SELECT STATUS FROM CX_TASK_CONTINUITY_LINKS").fetchone()[0] == "UNOBSERVED"
    assert db.execute("SELECT STATUS FROM CX_TASK_CONTINUITY_ATTEMPTS").fetchone()[0] == "UNOBSERVED"
    with pytest.raises(ContinuityConflict, match="unknown send"):
        run(lambda tx: task_continuity.claim_attempt(
            tx, continuity_id=link["continuity_id"], worker_id="worker-b",
            business_key="retry", request_digest="r" * 64, lease_seconds=60))
    assert claimed["fencing_token"] == 1


def test_stale_completion_is_rejected_and_persisted_as_unknown(database):
    db, _, run = database
    link = admit(db, run)
    claimed = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-a",
        business_key="send-key", request_digest="r" * 64, lease_seconds=60))
    expired = (datetime.utcnow() - timedelta(minutes=5)).isoformat(sep=" ")
    db.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET LEASE_EXPIRES_AT=?", (expired,))
    db.commit()
    result = run(lambda tx: task_continuity.finish_attempt(
        tx, attempt_id=claimed["attempt_id"], worker_id="worker-a",
        fencing_token=claimed["fencing_token"], status="SUCCEEDED", request_digest="r" * 64))
    assert result["accepted"] is False and result["status"] == "UNOBSERVED"
    assert db.execute("SELECT STATUS FROM CX_TASK_CONTINUITY_LINKS").fetchone()[0] == "UNOBSERVED"


def test_unknown_send_must_be_reconciled_with_the_original_digest(database):
    db, _, run = database
    link = admit(db, run)
    claimed = run(lambda tx: task_continuity.claim_attempt(
        tx, continuity_id=link["continuity_id"], worker_id="worker-a",
        business_key="send-key", request_digest="r" * 64, lease_seconds=60))
    db.execute("UPDATE CX_TASK_CONTINUITY_ATTEMPTS SET STATUS='UNOBSERVED'")
    db.execute("UPDATE CX_TASK_CONTINUITY_LINKS SET STATUS='UNOBSERVED'")
    db.commit()
    with pytest.raises(ContinuityConflict, match="different request"):
        run(lambda tx: task_continuity.reconcile_unobserved(
            tx, continuity_id=link["continuity_id"], business_key="send-key", actor="owner",
            request_digest="x" * 64, outcome="SUCCEEDED"))
    resolved = run(lambda tx: task_continuity.reconcile_unobserved(
        tx, continuity_id=link["continuity_id"], business_key="send-key", actor="owner",
        request_digest="r" * 64, outcome="SUCCEEDED"))
    assert resolved["status"] == "SUCCEEDED"
    with pytest.raises(ContinuityError, match="terminal"):
        run(lambda tx: task_continuity.claim_attempt(
            tx, continuity_id=link["continuity_id"], worker_id="worker-b",
            business_key="retry", request_digest="r" * 64))


def test_state_matrix_rejects_skipping_waiting_to_pending(database):
    db, _, run = database
    link = admit(db, run)
    with pytest.raises(ContinuityConflict, match="transition"):
        run(lambda tx: task_continuity._transition(
            tx, link["continuity_id"], "owner", "SUCCEEDED", "invalid", "r" * 64))
