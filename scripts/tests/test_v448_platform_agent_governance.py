from typing import Any

import pytest

from lib import platform_agent_pool


class GovernanceDb:
    DATABASE_DIALECT = "postgresql"

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.next_id = 1
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, sql: str, params: dict[str, Any] | None) -> dict[str, Any]:
        values = dict(params or {})
        self.calls.append((sql, values))
        return values

    def execute_query_one(self, sql: str, params: dict[str, Any] | None = None):
        values = self._record(sql, params)
        upper = sql.upper()
        if "CX_PLATFORM_SAFE_AUTONOMY_POLICIES" in upper:
            return {"policy_id": "DEFAULT", "state": "ENABLED", "execution_principal": "SYSTEM_PLATFORM_ADMIN_AGENT",
                    "rate_limit_per_minute": 10, "max_concurrency": 1, "failure_budget": 1, "version": 1}
        if "FROM CX_PLATFORM_COMMANDS WHERE COMMAND_KEY" in upper:
            key = str(values.get("kind"))
            return {"command_id": f"PCMD_{key}_V1", "risk_level": "READ"}
        if "IDEMPOTENCY_KEY=:KEY" in upper:
            return next((row for row in self.rows.values()
                         if row.get("idempotency_key") == values.get("key")), None)
        if "WHERE TASK_ID=:TASK FOR UPDATE" in upper:
            return self.rows.get(str(values.get("task")))
        if "WHERE TASK_ID=:TASK" in upper:
            return self.rows.get(str(values.get("task")))
        if "COUNT(*) AS CNT" in upper:
            if "CX_PLATFORM_ADMIN_COMMANDS" in upper:
                return {"cnt": 2}
            return {"cnt": 0}
        return None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None):
        self._record(sql, params)
        upper = sql.upper()
        if "FROM CX_PLATFORM_MAINTENANCE_TASKS" in upper and "SELECT TASK_ID,FENCING_TOKEN" in upper:
            return [dict(row) for row in self.rows.values() if row.get("status") in {"AUTHORIZED", "EXECUTING"}]
        return []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        values = self._record(sql, params)
        upper = sql.upper()
        if "INSERT INTO CX_PLATFORM_MAINTENANCE_TASKS" in upper:
            self.rows[str(values["task"])] = {
                "task_id": values["task"], "task_kind": values["kind"], "status": "PROPOSED",
                "risk_level": values["risk"], "autonomous": values["autonomous"],
                "scope_json": values["scope"], "finding_json": values["finding"], "plan_json": values["plan"],
                "created_by": values["actor"], "lease_owner": None, "fencing_token": 1,
                "idempotency_key": values.get("key"), "graph_run_id": values.get("run"),
                "evidence_json": "{}",
            }
            return 1
        if "STATUS='AUTHORIZED'" in upper and "EVIDENCE_JSON" in upper:
            row = self.rows[str(values["task"])]
            row["status"] = "AUTHORIZED"
            return 1
        if "SET STATUS='EXECUTING'" in upper:
            row = self.rows[str(values["task"])]
            row["status"] = "EXECUTING"
            row["lease_owner"] = values["owner"]
            row["fencing_token"] += 1
            return 1
        if "POSTFLIGHT_JSON" in upper:
            row = self.rows[str(values["task"])]
            row["status"] = values["status"]
            row["postflight_json"] = values["output"]
            return 1 if row.get("lease_owner") == values.get("owner") and row.get("fencing_token") == values.get("token") else 0
        if "SET GRAPH_RUN_ID=:RUN" in upper:
            row = self.rows[str(values["task"])]
            row["graph_run_id"] = values["run"]
            row["evidence_json"] = values["evidence"]
            return 1
        return 1

    def execute_transaction_callback(self, work):
        return work(self)

    query_one = execute_query_one
    query = execute_query


@pytest.fixture
def service(monkeypatch):
    db = GovernanceDb()
    monkeypatch.setattr(platform_agent_pool, "connection", db)
    monkeypatch.setattr(platform_agent_pool.identity_api, "effective_access", lambda *_args, **_kwargs: {"decision": "ALLOW"})
    monkeypatch.setattr(platform_agent_pool.identity_api, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(platform_agent_pool.identity_api, "_audit_tx", lambda *_args, **_kwargs: None)
    return db


def test_autonomous_task_fails_closed_when_policy_is_disabled(monkeypatch, service):
    def disabled(_sql, _params):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(service, "execute_query_one", disabled)
    with pytest.raises(platform_agent_pool.AgentPoolError, match="not enabled"):
        platform_agent_pool.create_maintenance_task(
            "admin", "HEALTH_READ", "", "SAFE_MAINTENANCE", {}, {}, {}, autonomous=True,
        )


def test_task_requires_separate_authorizer_and_safe_risk(service):
    created = platform_agent_pool.create_maintenance_task(
        "requester", "HEALTH_READ", "", "READ", {}, {}, {},
        idempotency_key="health-check-1", autonomous=True,
    )
    task_id = created["task_id"]
    with pytest.raises(platform_agent_pool.AgentPoolError, match="cannot authorize"):
        platform_agent_pool.authorize_maintenance_task("requester", task_id, "same person")
    service.rows[task_id]["risk_level"] = "HIGH_RISK_CHANGE"
    with pytest.raises(platform_agent_pool.AgentPoolError, match="separately governed"):
        platform_agent_pool.authorize_maintenance_task("approver", task_id, "high risk")
    service.rows[task_id]["risk_level"] = "READ"
    assert platform_agent_pool.authorize_maintenance_task("approver", task_id, "approved")["status"] == "AUTHORIZED"


def test_safe_maintenance_claims_executes_and_completes_with_fence(service):
    created = platform_agent_pool.create_maintenance_task(
        "requester", "HEALTH_READ", "", "READ", {}, {}, {}, autonomous=True,
    )
    platform_agent_pool.authorize_maintenance_task("approver", created["task_id"], "approved")
    result = platform_agent_pool.run_safe_maintenance_once("SYSTEM_PLATFORM_ADMIN_AGENT", limit=1)
    assert result["status"] == "COMPLETED"
    assert result["completed"][0]["status"] == "COMPLETED"
    with pytest.raises(platform_agent_pool.AgentPoolError, match="stale"):
        platform_agent_pool.complete_maintenance_task(
            "SYSTEM_PLATFORM_ADMIN_AGENT", created["task_id"], 1, {}, verified=True,
        )


def test_unimplemented_executor_records_verification_failure(service):
    created = platform_agent_pool.create_maintenance_task(
        "requester", "NODE_VALIDATE", "", "SAFE_MAINTENANCE", {}, {}, {}, autonomous=True,
    )
    platform_agent_pool.authorize_maintenance_task("approver", created["task_id"], "approved")
    result = platform_agent_pool.run_safe_maintenance_once("SYSTEM_PLATFORM_ADMIN_AGENT", limit=1)
    assert result["completed"][0]["status"] == "VERIFY_FAILED"


def test_observation_scan_is_daily_and_proposal_only(service):
    service.rows.clear()
    first = platform_agent_pool.run_platform_observation_scan("admin")
    assert first["status"] == "PROPOSED"
    assert {item["kind"] for item in first["items"]} == {
        "HEALTH_READ", "LLM_STATUS_READ", "EMBEDDING_STATUS_READ", "EXPIRED_COMMAND_CLEANUP",
    }
    assert all(
        str(row.get("idempotency_key") or "").startswith("v448-observation-")
        for row in service.rows.values()
    )
    second = platform_agent_pool.run_platform_observation_scan("admin")
    assert all(item["idempotent"] for item in second["items"])
    assert len(service.rows) == 4
    assert next(item for item in second["items"] if item["kind"] == "EXPIRED_COMMAND_CLEANUP")["status"] == "PROPOSED"


def test_graph_run_binding_reuses_existing_contract_and_is_immutable(service):
    created = platform_agent_pool.create_maintenance_task(
        "requester", "HEALTH_READ", "", "READ", {}, {}, {},
    )
    task_id = created["task_id"]
    service.graph_rows = {"RUN_1": {"run_id": "RUN_1", "graph_version_id": "GV_1",
                                    "plan_id": "PLAN_1", "status": "PAUSED"}}

    original_query_one = service.execute_query_one
    def query_one(sql, params=None):
        if "FROM GRAPH_RUNS WHERE RUN_ID=:RUN FOR UPDATE" in sql.upper():
            return service.graph_rows.get(str((params or {}).get("run")))
        return original_query_one(sql, params)
    service.execute_query_one = query_one
    service.query_one = query_one

    bound = platform_agent_pool.bind_maintenance_graph_run(
        "admin", task_id, "RUN_1", graph_version_id="GV_1", plan_id="PLAN_1",
        admission_evidence={"approved_plan_digest": "a" * 64},
    )
    assert bound["graph_run_id"] == "RUN_1"
    assert platform_agent_pool.bind_maintenance_graph_run(
        "admin", task_id, "RUN_1", graph_version_id="GV_1", plan_id="PLAN_1",
        admission_evidence={"approved_plan_digest": "a" * 64},
    )["idempotent"] is True
    service.graph_rows["RUN_1"]["status"] = "FAILED"
    with pytest.raises(platform_agent_pool.AgentPoolError, match="immutable"):
        platform_agent_pool.bind_maintenance_graph_run(
            "admin", task_id, "RUN_2", graph_version_id="GV_1", plan_id="PLAN_1",
            admission_evidence={"approved_plan_digest": "a" * 64},
        )
