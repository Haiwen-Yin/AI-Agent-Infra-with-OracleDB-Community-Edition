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


@pytest.fixture
def object_read(registry, monkeypatch):
    for item in registry.values(): item["executor_state"] = "ENABLED"
    monkeypatch.setattr(pool.identity_api, "_audit", Mock())
    def setup(kind, target):
        monkeypatch.setattr(pool.connection, "execute_query_one", Mock(return_value={
            "command_id": "C1", "command_type": kind, "status": "COMPLETED",
            "target_json": pool._json(target), "parameters_json": "{}"}))
    return setup


def test_agent_diagnosis_rechecks_object_authorization(object_read, monkeypatch):
    from lib import compliance_api
    object_read("AGENT_DIAGNOSIS_READ", {"agent_id": "outside-scope"})
    reader = Mock(side_effect=PermissionError("outside scope"))
    monkeypatch.setattr(compliance_api, "posture_detail", reader)
    if not compliance_api._enterprise_enabled():
        with pytest.raises(pool.AgentPoolError, match="COMMAND_EDITION_UNAVAILABLE"):
            pool.execute_read_command("admin", "C1")
        reader.assert_not_called()
        return
    with pytest.raises(PermissionError): pool.execute_read_command("admin", "C1")
    reader.assert_called_once_with("admin", "outside-scope")


def test_findings_command_projects_summary_without_evidence_body(object_read, monkeypatch):
    from lib import compliance_api
    object_read("COMPLIANCE_FINDINGS_READ", {"agent_id": "agent"})
    reader = Mock(return_value=[{"finding_id": "f1", "severity": "HIGH", "detail": "sensitive content"}])
    monkeypatch.setattr(compliance_api, "list_findings", reader)
    if not compliance_api._enterprise_enabled():
        with pytest.raises(pool.AgentPoolError, match="COMMAND_EDITION_UNAVAILABLE"):
            pool.execute_read_command("admin", "C1")
        reader.assert_not_called()
        return
    result = pool.execute_read_command("admin", "C1")
    assert result["items"][0]["finding_id"] == "f1"
    assert "detail" not in result["items"][0]
    reader.assert_called_once_with("admin", "agent", limit=20)


def test_approval_command_preserves_channel_acl_and_omits_payload(object_read, monkeypatch):
    object_read("APPROVAL_STATUS_READ", {})
    reader = Mock(return_value=[{"action_id": "a1", "status": "PROPOSED", "payload_json": "sensitive"}])
    monkeypatch.setattr(pool.identity_api, "list_action_cards", reader)
    result = pool.execute_read_command("admin", "C1")
    reader.assert_called_once_with("admin", "CH_PLATFORM_ADMINISTRATION", limit=20)
    assert "payload_json" not in result["items"][0]


def test_disabled_object_executor_fails_closed(object_read, registry, monkeypatch):
    from lib import compliance_api
    object_read("AGENT_DIAGNOSIS_READ", {"agent_id": "agent"})
    registry["AGENT_DIAGNOSIS_READ"]["executor_state"] = "DISABLED"
    reader = Mock()
    monkeypatch.setattr(compliance_api, "posture_detail", reader)
    with pytest.raises(pool.AgentPoolError, match="UNAVAILABLE"):
        pool.execute_read_command("admin", "C1")
    reader.assert_not_called()


def test_action_scan_rejects_credentials_before_approval(registry):
    from lib import content_security
    with pytest.raises(content_security.ContentDenied):
        pool._inspect_command(registry["NODE_VALIDATE"], {"node_id": "sk-" + "a" * 28}, {})


def test_high_risk_action_scan_never_grants_execution(registry):
    result = pool._inspect_command(registry["AGENT_DRAIN"], {"node_id": "A"}, {"target_node_id": "B"})
    assert result["decision"] == "REQUIRE_APPROVAL"
    assert len(result["content_digest"]) == 64


def test_scanner_failure_prevents_action_creation(registry, monkeypatch):
    from lib import content_security
    monkeypatch.setattr(content_security, "enforce", Mock(side_effect=RuntimeError("scanner unavailable")))
    database = Mock()
    monkeypatch.setattr(pool.connection, "execute_transaction_callback", database)
    with pytest.raises(RuntimeError):
        pool.create_command("admin", "AGENT_DRAIN", {"node_id": "A"}, {"target_node_id": "B"}, "DEFAULT", "reviewed")
    database.assert_not_called()

def test_expire_commands_only_reclaims_expired_pending(monkeypatch):
    from unittest.mock import Mock
    tx = Mock(query=Mock(return_value=[{"COMMAND_ID": "C1"}]), execute=Mock(return_value=1))
    monkeypatch.setattr(pool, "_require_admin", Mock())
    monkeypatch.setattr(pool.connection, "execute_transaction_callback", lambda fn: fn(tx))
    monkeypatch.setattr(pool.identity_api, "_audit_tx", Mock())
    result = pool.expire_commands("admin")
    assert result == {"status": "COMPLETED", "expired": ["C1"], "count": 1}
    assert "STATUS='EXPIRED'" in tx.execute.call_args.args[0]


@pytest.mark.parametrize("kind", sorted(pool.COMPLIANCE_COMMANDS))
def test_community_rejects_compliance_contract_before_database(monkeypatch, kind):
    from lib import compliance_api
    monkeypatch.setattr(compliance_api, "_enterprise_enabled", lambda: False)
    database = Mock()
    monkeypatch.setattr(pool.connection, "execute_query_one", database)
    with pytest.raises(pool.AgentPoolError, match="EDITION_UNAVAILABLE"):
        pool._command_contract(kind)
    database.assert_not_called()
