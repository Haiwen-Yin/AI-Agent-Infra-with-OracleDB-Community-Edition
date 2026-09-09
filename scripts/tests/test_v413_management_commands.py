from unittest.mock import Mock
import pytest
from lib import platform_agent_pool as pool


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(pool, "_require_admin", Mock())
    rows = {item[0]: {"command_key": item[0], "version": 1, "execution_mode": item[2], "parameter_schema": item[5]} for item in pool.COMMAND_SEEDS}
    monkeypatch.setattr(pool, "_command_contract", lambda key: rows[key])
    return rows


@pytest.mark.parametrize("command,target", [("NODE_VALIDATE", {"node_id": "N1"}), ("STORAGE_VALIDATE", {"storage_id": "N1"}), ("AGENT_QUARANTINE", {"agent_id": "N1"})])
def test_slash_parameters_follow_registered_schema(registry, command, target):
    parsed = pool.parse_channel_command("admin", f"/platform {command} N1 完整的 多词原因")
    assert parsed["target"] == target
    assert parsed["reason"] == "完整的 多词原因"


def test_drain_retains_existing_executor_parameter_names(registry):
    parsed = pool.parse_channel_command("admin", "/platform AGENT_DRAIN A B 审批排空")
    assert parsed["target"] == {"node_id": "A"}
    assert parsed["parameters"] == {"target_node_id": "B"}


def test_missing_and_unknown_parameters_rejected(registry):
    with pytest.raises(pool.AgentPoolError, match="REQUIRED"):
        pool.parse_channel_command("admin", "/platform NODE_VALIDATE")
    with pytest.raises(pool.AgentPoolError, match="UNKNOWN"):
        pool._validate_command_parameters(registry["NODE_VALIDATE"], {"node_id": "N1", "shell": "anything"}, {})


def test_read_without_reason_has_auditable_default(registry):
    parsed = pool.parse_channel_command("admin", "/platform HEATH_READ")
    assert parsed["kind"] == "HEALTH_READ"
    assert len(parsed["reason"]) >= 3


def test_unrelated_action_cannot_replay_completed_command(monkeypatch):
    monkeypatch.setattr(pool, "_require_admin", Mock())
    tx = Mock(query_one=Mock(side_effect=[{"status": "CONFIRMED", "action_type": "PLATFORM_ADMIN_COMMAND", "payload_json": '{"command_id":"other"}'},
        {"command_id": "C1", "status": "COMPLETED"}]))
    monkeypatch.setattr(pool.connection, "execute_transaction_callback", lambda fn: fn(tx))
    with pytest.raises(pool.AgentPoolError, match="does not match"):
        pool.execute_approved_command("admin", "C1", "A1")
    tx.execute.assert_not_called()
