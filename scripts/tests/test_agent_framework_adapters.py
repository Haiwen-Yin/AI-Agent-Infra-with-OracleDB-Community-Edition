"""Pure contract tests for the framework-neutral Agent Gateway adapters."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from lib.agent_framework_adapters import (
    GATEWAY_SCHEMA,
    HermesGatewayAdapter,
    OpenClawGatewayAdapter,
    FrameworkAdapterError,
    ack_to_gateway,
    build_action_request,
    build_arrival_request,
    build_ack_request,
    build_instance_request,
    build_pull_request,
    build_registration_request,
    build_token_request,
    create_gateway_adapter,
    event_to_framework_message,
    framework_message_to_gateway,
    normalize_framework_name,
    validate_action_response,
    validate_arrival_response,
    validate_ack_response,
    validate_instance_response,
    validate_pull_response,
    validate_registration_response,
    validate_token_response,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "shared" if (ROOT / "shared").is_dir() else ROOT / "scripts"


def _event(**overrides):
    value = {
        "agent_id": "agent-a",
        "instance_id": "instance-a",
        "delivery_id": "delivery-a",
        "event_type": "CHANNEL_MESSAGE",
        "channel_id": "channel-a",
        "message_id": "message-a",
        "payload": {"body": "hello", "priority": "normal"},
        "idempotency_key": "channel:message-a:instance-a",
        "attempt_count": 1,
        "max_attempts": 3,
        "status": "CLAIMED",
        "claim_token": "claim-a",
    }
    value.update(overrides)
    return value


def _framework_message(**overrides):
    value = {
        "schema": GATEWAY_SCHEMA,
        "framework": "OpenClaw",
        "agent_id": "agent-a",
        "instance_id": "instance-a",
        "message": {
            "delivery_id": "delivery-a",
            "event_type": "CHANNEL_MESSAGE",
            "channel_id": "channel-a",
            "message_id": "message-a",
            "body": "reply",
            "thread_type": "CHANNEL",
            "thread_id": "thread-a",
            "references": {"source": "message-a"},
            "message_type": "RESPONSE",
            "idempotency_key": "reply:message-a",
        },
    }
    value.update(overrides)
    return value


def test_normalize_framework_name_supports_known_aliases_and_safe_custom_names():
    assert normalize_framework_name("OpenClaw") == "openclaw"
    assert normalize_framework_name("open-claw") == "openclaw"
    assert normalize_framework_name("Hermes Agent") == "hermes"
    assert normalize_framework_name("Acme Runner") == "acme-runner"
    assert normalize_framework_name("framework-neutral") == "generic"


@pytest.mark.parametrize("value", ["", "  ", "../../gateway", "bad\nname", None, 123])
def test_normalize_framework_name_rejects_invalid_names(value):
    with pytest.raises(FrameworkAdapterError):
        normalize_framework_name(value)


def test_event_to_framework_message_parses_durable_json_and_hides_lease_metadata():
    event = _event(payload=None, payload_json=json.dumps({"body": "from db", "answer": 42}),
                   fencing_token=7, visibility_until="2026-07-28T12:00:00Z")
    converted = event_to_framework_message(event, "Hermes")

    assert converted["schema"] == GATEWAY_SCHEMA
    assert converted["framework"] == "hermes"
    assert converted["agent_id"] == "agent-a"
    assert converted["instance_id"] == "instance-a"
    assert converted["event"]["payload"] == {"body": "from db", "answer": 42}
    assert converted["message"]["body"] == "from db"
    assert converted["ack"]["claim_token"] == "claim-a"
    assert "fencing_token" not in json.dumps(converted)
    assert "visibility_until" not in json.dumps(converted)


@pytest.mark.parametrize("field", ["agent_id", "instance_id"])
def test_event_to_framework_message_rejects_empty_identity(field):
    event = _event(**{field: "   "})
    with pytest.raises(FrameworkAdapterError, match=field):
        event_to_framework_message(event)


@pytest.mark.parametrize("bad", [
    {"secret": "not allowed"},
    {"payload_json": "not-json"},
    {"payload": {"a": object()}},
    {"attempt_count": -1},
])
def test_event_to_framework_message_fails_closed(bad):
    with pytest.raises(FrameworkAdapterError):
        event_to_framework_message(_event(**bad))


def test_framework_message_to_gateway_returns_only_gateway_message_fields():
    converted = framework_message_to_gateway(_framework_message())

    assert converted == {
        "channel_id": "channel-a",
        "body": "reply",
        "thread_type": "CHANNEL",
        "thread_id": "thread-a",
        "references": {"source": "message-a"},
        "message_type": "RESPONSE",
        "delivery_id": "delivery-a",
        "event_type": "CHANNEL_MESSAGE",
        "message_id": "message-a",
        "idempotency_key": "reply:message-a",
    }


def test_framework_envelope_validates_nested_event_and_ack():
    valid = _framework_message(
        event={
            "delivery_id": "delivery-a",
            "event_type": "CHANNEL_MESSAGE",
            "payload": {"body": "hello"},
        },
        ack={
            "schema": GATEWAY_SCHEMA,
            "agent_id": "agent-a",
            "instance_id": "instance-a",
            "delivery_id": "delivery-a",
            "claim_token": "claim-a",
        },
    )
    assert framework_message_to_gateway(valid)["body"] == "reply"

    invalid_event = _framework_message(event={"delivery_id": "delivery-a", "admin": True})
    with pytest.raises(FrameworkAdapterError):
        framework_message_to_gateway(invalid_event)

    invalid_ack = _framework_message(ack={"agent_id": "agent-a", "extra": True})
    with pytest.raises(FrameworkAdapterError):
        framework_message_to_gateway(invalid_ack)


@pytest.mark.parametrize("bad", [
    {"unknown": True},
    {"message": {"admin": True}},
    {"agent_id": ""},
    {"instance_id": ""},
    {"message": {"channel_id": "channel-a", "body": "   "}},
])
def test_framework_message_to_gateway_rejects_unknown_or_empty_fields(bad):
    value = _framework_message()
    if "message" in bad and isinstance(bad["message"], dict):
        value["message"] = {**value["message"], **bad["message"]}
        if "admin" in bad["message"]:
            pass
    else:
        value.update(bad)
    with pytest.raises(FrameworkAdapterError):
        framework_message_to_gateway(value)


def test_ack_to_gateway_normalizes_success_and_reason():
    converted = ack_to_gateway({
        "schema": GATEWAY_SCHEMA,
        "agent_id": "agent-a",
        "instance_id": "instance-a",
        "delivery_id": "delivery-a",
        "claim_token": "claim-a",
        "success": False,
        "reason": "temporary failure",
    })
    assert converted == {
        "delivery_id": "delivery-a",
        "claim_token": "claim-a",
        "success": False,
        "reason": "temporary failure",
    }


@pytest.mark.parametrize("bad", [
    {"agent_id": ""},
    {"instance_id": ""},
    {"claim_token": ""},
    {"delivery_id": ""},
    {"extra": "nope"},
    {"success": "false"},
])
def test_ack_to_gateway_rejects_invalid_identity_claim_and_fields(bad):
    value = {
        "agent_id": "agent-a",
        "instance_id": "instance-a",
        "delivery_id": "delivery-a",
        "claim_token": "claim-a",
    }
    value.update(bad)
    with pytest.raises(FrameworkAdapterError):
        ack_to_gateway(value)


def test_client_identity_claims_are_not_authoritative():
    message = _framework_message(agent_id="attacker", instance_id="other-instance")
    assert "agent_id" not in framework_message_to_gateway(message)
    assert "instance_id" not in framework_message_to_gateway(message)
    with pytest.raises(FrameworkAdapterError, match="trusted context"):
        framework_message_to_gateway(message, trusted_agent_id="agent-a")

    ack = {
        "agent_id": "attacker",
        "instance_id": "instance-a",
        "delivery_id": "delivery-a",
        "claim_token": "claim-a",
    }
    with pytest.raises(FrameworkAdapterError, match="trusted context"):
        ack_to_gateway(ack, trusted_agent_id="agent-a", trusted_instance_id="instance-a")


def test_request_builders_follow_existing_gateway_routes_and_omit_runtime_identity():
    registration = build_registration_request("enrollment-token-12345678901234567890", framework="OpenClaw")
    assert registration["path"] == "/api/enrollment/redeem"
    assert registration["body"]["runtime"] == "openclaw"
    assert "client_secret" not in registration["body"]

    token = build_token_request("agent-a", "client-secret-a", scopes=["events.read"])
    assert token["path"] == "/api/gateway/token"
    assert token["body"]["agent_id"] == "agent-a"
    assert token["body"]["scopes"] == ["events.read"]

    instance = build_instance_request(channel_id="channel-a", node_id="node-a")
    pull = build_pull_request(limit=25)
    ack = build_ack_request("delivery-a", "claim-token-a", success=False, reason="retry")
    arrival = build_arrival_request(
        "barrier-a", {"completed_work": ["step-1"], "risk": "LOW"},
        participant_role="Reviewer", idempotency_key="arrival-001",
    )
    action = build_action_request(
        "channel-a", "PAUSE_RUN", {"run_id": "run-a"},
        reason="Review required", idempotency_key="action-001",
    )
    assert instance["path"] == "/api/gateway/instances"
    assert pull == {
        "schema": GATEWAY_SCHEMA,
        "method": "POST",
        "path": "/api/gateway/events/claim",
        "query": {"limit": 25},
        "body": {},
    }
    assert ack["path"] == "/api/gateway/events/delivery-a/ack"
    assert arrival["path"] == "/api/gateway/barriers/barrier-a/arrivals"
    assert arrival["body"]["participant_role"] == "REVIEWER"
    assert action["path"] == "/api/gateway/channels/channel-a/actions"
    for request in (instance, pull, ack, arrival, action):
        assert "agent_id" not in request["body"]
        assert "instance_id" not in request["body"]


def test_token_request_supports_public_key_proof_without_private_material():
    request = build_token_request(
        "agent-a", public_key="public-key-a", signature="signature-a", challenge="challenge-a",
    )
    assert request["body"]["public_key"] == "public-key-a"
    assert "client_secret" not in request["body"]
    with pytest.raises(FrameworkAdapterError):
        build_token_request(
            "agent-a", public_key="-----BEGIN PRIVATE KEY-----", signature="signature-a", challenge="challenge-a",
        )


def test_gateway_response_validators_bind_every_server_result():
    registration = validate_registration_response({
        "agent_id": "agent-a", "status": "ACTIVE", "owner_principal_id": "human-a",
        "sponsor_principal_id": "human-a", "credential_type": "CLIENT_SECRET",
        "credential": "one-time-credential", "runtime": "openclaw", "environment": "development",
    }, expected_runtime="OpenClaw", expected_environment="development")
    assert registration["agent_id"] == "agent-a"
    assert registration["credential"] == "one-time-credential"

    instance = validate_instance_response({
        "instance_id": "instance-a", "agent_id": "agent-a", "channel_id": "channel-a",
        "status": "ACTIVE", "classification": "INTERNAL",
    }, expected_agent_id="agent-a")
    token = validate_token_response({
        "access_token": "access-token-a", "agent_id": "agent-a", "instance_id": "instance-a",
        "scopes": ["events.read"], "expires_at": "2026-07-28T12:00:00Z",
    }, expected_agent_id="agent-a", expected_instance_id="instance-a")
    pull = validate_pull_response({
        "items": [{
            "delivery_id": "delivery-a", "event_type": "CHANNEL_MESSAGE",
            "channel_id": "channel-a", "payload": {"body": "hello"}, "claim_token": "claim-a",
        }], "count": 1, "agent_id": "agent-a", "instance_id": "instance-a",
    }, expected_agent_id="agent-a", expected_instance_id="instance-a", framework="Hermes")
    ack = validate_ack_response({"success": True, "delivery_id": "delivery-a"}, "delivery-a")
    arrival = validate_arrival_response({
        "arrival_id": "arrival-a", "barrier_id": "barrier-a", "status": "READY",
        "report_digest": "a" * 64, "idempotent": False,
    }, "barrier-a")
    action = validate_action_response({
        "action_id": "action-a", "channel_id": "channel-a", "action_type": "PAUSE_RUN",
        "status": "PROPOSED", "payload": {"run_id": "run-a"}, "reason": "Review required",
        "idempotent": False,
    }, "channel-a", "PAUSE_RUN")
    assert instance["agent_id"] == token["agent_id"] == pull["agent_id"] == "agent-a"
    assert token["access_token"] == "access-token-a"
    assert pull["items"][0]["ack"]["claim_token"] == "claim-a"
    assert ack["success"] is True
    assert arrival["status"] == "READY"
    assert action["payload"] == {"run_id": "run-a"}


@pytest.mark.parametrize("call", [
    lambda: build_registration_request("short"),
    lambda: build_token_request("agent-a"),
    lambda: build_token_request("agent-a", "secret-a", public_key="public-a"),
    lambda: build_instance_request(),
    lambda: build_pull_request(limit=101),
    lambda: build_ack_request("delivery-a", ""),
    lambda: build_arrival_request("barrier-a", {}, idempotency_key="short"),
    lambda: build_arrival_request("barrier-a", {"evidence": float("nan")}, idempotency_key="arrival-001"),
    lambda: build_action_request("channel-a", "PAUSE", {"password": "plain"}, reason="x", idempotency_key="action-001"),
    lambda: build_action_request("channel-a", "PAUSE", {}, reason="", idempotency_key="action-001"),
])
def test_request_builders_reject_invalid_or_sensitive_input(call):
    with pytest.raises(FrameworkAdapterError):
        call()


@pytest.mark.parametrize("response", [
    {"agent_id": "other", "status": "ACTIVE", "owner_principal_id": "human-a", "sponsor_principal_id": "human-a", "credential_type": "CLIENT_SECRET", "credential": "credential-a"},
    {"agent_id": "agent-a", "status": "ACTIVE", "owner_principal_id": "human-a", "sponsor_principal_id": "human-a", "credential_type": "CLIENT_SECRET", "credential": "credential-a", "secret_digest": "plain"},
])
def test_response_validators_reject_identity_mismatch_and_credential_metadata(response):
    if response["agent_id"] == "other":
        with pytest.raises(FrameworkAdapterError):
            validate_instance_response({"instance_id": "instance-a", "agent_id": "other", "status": "ACTIVE"}, expected_agent_id="agent-a")
    else:
        with pytest.raises(FrameworkAdapterError):
            validate_registration_response(response)


def test_framework_specific_facades_are_stateless_and_share_the_same_contract():
    openclaw = OpenClawGatewayAdapter()
    hermes = HermesGatewayAdapter()
    generic = create_gateway_adapter("framework-neutral")
    assert openclaw.framework == "openclaw"
    assert hermes.framework == "hermes"
    assert generic.framework == "generic"
    assert openclaw.registration_request("enrollment-token-12345678901234567890")["body"]["runtime"] == "openclaw"
    assert hermes.pull_request(limit=1)["path"] == "/api/gateway/events/claim"


def test_module_is_pure_and_has_no_project_or_io_imports():
    source = (SOURCE_ROOT / "lib/agent_framework_adapters.py").read_text(encoding="ascii")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".", 1)[0])
    assert set(imports) <= {"__future__", "json", "re", "collections", "typing"}
    assert "connection" not in source
    assert "requests" not in source
