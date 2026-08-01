"""Pure Node Executor contract tests for v4.2.1."""

import pytest

from lib.graph_executor import (
    admission,
    builtin_executor_manifests,
    dispatch_record,
    effect_idempotency_key,
    execute_control,
    list_persisted_manifests,
    register_persisted_manifest,
    set_persisted_status,
    side_effect_retry_decision,
    validate_manifest,
)


def test_builtin_executor_registry_is_complete_and_valid():
    manifests = builtin_executor_manifests()
    assert {item["name"] for item in manifests} == {
        "CONTROL", "WORKER", "HUMAN_WAIT", "TIMER_WAIT", "EVENT_WAIT",
    }
    assert all(validate_manifest(item) == [] for item in manifests)


@pytest.mark.parametrize(
    ("node_type", "executor", "kind"),
    [("START", "CONTROL", "CONTROL"), ("TOOL", "WORKER", "WORKER"),
     ("HUMAN", "HUMAN_WAIT", "WAIT"), ("TIMER", "TIMER_WAIT", "WAIT"),
     ("EVENT", "EVENT_WAIT", "WAIT")],
)
def test_node_types_resolve_to_one_registered_executor(node_type, executor, kind):
    result = admission({"node_type": node_type, "config": {"executor": executor}})
    assert result["name"] == executor
    assert result["kind"] == kind
    assert result["contract_version"] == "1.0"


def test_control_executor_is_local_and_declarative():
    result = execute_control({"node_type": "START"}, {"request": "r1"})
    assert result.status == "COMPLETED"
    assert result.output_state == {"request": "r1", "control_node": "START"}


def test_worker_and_wait_nodes_only_create_dispatch_records():
    worker = dispatch_record({"node_type": "TOOL"}, {"safe": True})
    waiting = dispatch_record({"node_type": "EVENT"}, {"safe": True})
    assert worker.status == "DELEGATED"
    assert waiting.status == "WAITING"
    assert worker.output_state["executor_admission"]["name"] == "WORKER"
    assert waiting.output_state["executor_admission"]["name"] == "EVENT_WAIT"


def test_external_effect_key_is_stable_per_logical_node_run_and_isolated_between_nodes():
    first = effect_idempotency_key("RUN_1", "NODE_1", "IDEMPOTENT_EXTERNAL")
    replay = effect_idempotency_key("RUN_1", "NODE_1", "IDEMPOTENT_EXTERNAL")
    different_node = effect_idempotency_key("RUN_1", "NODE_2", "IDEMPOTENT_EXTERNAL")
    different_run = effect_idempotency_key("RUN_2", "NODE_1", "IDEMPOTENT_EXTERNAL")

    assert first == replay
    assert first != different_node
    assert first != different_run
    assert effect_idempotency_key("RUN:1", "NODE", "IDEMPOTENT_EXTERNAL") != effect_idempotency_key(
        "RUN", "1:NODE", "IDEMPOTENT_EXTERNAL",
    )
    assert first.startswith("effect:")
    assert effect_idempotency_key("RUN_1", "NODE_1", "NONE") is None
    assert effect_idempotency_key("RUN_1", "NODE_1", "NON_IDEMPOTENT") is None


def test_external_effect_key_requires_logical_identity():
    with pytest.raises(ValueError):
        effect_idempotency_key("", "NODE_1", "IDEMPOTENT_EXTERNAL")
    with pytest.raises(ValueError):
        effect_idempotency_key("RUN_1", "", "IDEMPOTENT_EXTERNAL")


@pytest.mark.parametrize("side_effect_class", ["NONE", "DB_TRANSACTIONAL", "IDEMPOTENT_EXTERNAL"])
def test_retryable_effect_classes_retry_until_their_limit(side_effect_class):
    result = side_effect_retry_decision(side_effect_class, "TEMPORARY_FAILURE", 1, 2)
    assert result == {
        "retry": True, "status": "READY", "uncertain_outcome": False,
        "automatic_retry": True, "reason": "RETRYABLE_FAILURE",
    }

    exhausted = side_effect_retry_decision(side_effect_class, "TEMPORARY_FAILURE", 2, 2)
    assert exhausted["retry"] is False
    assert exhausted["status"] == "FAILED"


def test_uncertain_idempotent_external_failure_can_retry_but_non_idempotent_cannot():
    external = side_effect_retry_decision("IDEMPOTENT_EXTERNAL", "OUTCOME_UNKNOWN", 1, 2)
    assert external["retry"] is True
    assert external["uncertain_outcome"] is True

    non_idempotent = side_effect_retry_decision("NON_IDEMPOTENT", "OUTCOME_UNKNOWN", 1, 2)
    assert non_idempotent == {
        "retry": False, "status": "REVIEW_REQUIRED", "uncertain_outcome": True,
        "automatic_retry": False, "reason": "NON_IDEMPOTENT_UNCERTAIN",
    }


def test_non_idempotent_failure_never_retries_automatically():
    result = side_effect_retry_decision("NON_IDEMPOTENT", "TEMPORARY_FAILURE", 1, 5)
    assert result["retry"] is False
    assert result["status"] == "FAILED"
    assert result["automatic_retry"] is False


def test_executor_cannot_be_repurposed_for_another_node_or_effect():
    with pytest.raises(ValueError):
        admission({"node_type": "TOOL", "config": {"executor": "CONTROL"}})
    with pytest.raises(ValueError):
        admission({"node_type": "TOOL", "side_effect_class": "NON_IDEMPOTENT",
                   "config": {"executor": "CONTROL"}})


class _RegistryConnection:
    DATABASE_DIALECT = "postgresql"

    def __init__(self):
        self.calls = []
        self.rows = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return 1

    def execute_query(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return list(self.rows)

    def execute_query_one(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return {"executor_name": "CUSTOM_TOOL"}


def _custom_manifest():
    return {
        "name": "custom_tool",
        "version": "2.1",
        "executor_kind": "WORKER",
        "node_types": ["TOOL"],
        "side_effect_classes": ["NONE", "IDEMPOTENT_EXTERNAL"],
        "description": "Declarative test executor",
    }


def test_custom_manifest_is_normalized_and_persisted_without_code_fields():
    connection = _RegistryConnection()
    executor_id = register_persisted_manifest(connection, _custom_manifest(), "admin")
    assert executor_id.startswith("EXEC_")
    sql, params = connection.calls[-1]
    assert "ON CONFLICT" in sql
    assert params["manifest_json"].find("CUSTOM_TOOL") >= 0
    assert params["manifest_json"].find("contract_version") >= 0

    unsafe = dict(_custom_manifest(), handler="python:module.call")
    with pytest.raises(ValueError, match="EXECUTOR_MANIFEST_INVALID"):
        register_persisted_manifest(connection, unsafe, "admin")


def test_builtin_executor_names_are_immutable():
    with pytest.raises(ValueError, match="EXECUTOR_BUILTIN_NAME_RESERVED"):
        register_persisted_manifest(
            _RegistryConnection(),
            dict(_custom_manifest(), name="WORKER"),
            "admin",
        )


def test_registry_status_changes_require_reason_and_are_listed():
    connection = _RegistryConnection()
    with pytest.raises(ValueError, match="requires a reason"):
        set_persisted_status(connection, "EXEC_custom", "DISABLED", "admin", "")
    assert set_persisted_status(connection, "EXEC_custom", "DISABLED", "admin", "retire test") is True
    connection.rows = [{
        "executor_name": "CUSTOM_TOOL", "executor_version": "2.1", "executor_kind": "WORKER",
        "manifest_json": '{"kind":"EXECUTOR","name":"CUSTOM_TOOL","version":"2.1",'
                          '"executor_kind":"WORKER","node_types":["TOOL"],'
                          '"side_effect_classes":["NONE"]}',
        "status": "ACTIVE", "status_reason": "registered",
    }]
    items = list_persisted_manifests(connection)
    assert items[0]["name"] == "CUSTOM_TOOL"
    assert items[0]["status_reason"] == "registered"
