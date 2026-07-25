"""Pure security and scheduling contracts for v4.2 Graph Engineering."""

import json

import pytest

from lib.graph_event_contract import (
    classify_event,
    normalize_trigger,
    sign_event,
    validate_event,
    verify_event_auth,
)
from lib.graph_scheduler import admission_decision, fair_order, validate_policy
from lib.graph_state import (
    StateKeyring,
    decode_secret_state,
    encode_secret_state,
    is_state_envelope,
    rotate_secret_state,
)


def test_state_secret_envelope_is_versioned_authenticated_and_rotatable():
    old = StateKeyring({"2026-07": b"old-state-key-0123456789012345"}, "2026-07")
    new = StateKeyring({"2026-08": b"new-state-key-0123456789012345"}, "2026-08")
    state = {"public": "ok", "credential": {"password": "do-not-persist"}}

    encoded = encode_secret_state(state, keyring=old)
    assert is_state_envelope(encoded["credential"])
    assert "do-not-persist" not in json.dumps(encoded, ensure_ascii=True)
    assert decode_secret_state(encoded, old, allow_secrets=False)["credential"] == "[REDACTED]"
    assert decode_secret_state(encoded, old, allow_secrets=True) == state

    rotated = rotate_secret_state(encoded, old, new)
    assert rotated["credential"] != encoded["credential"]
    assert decode_secret_state(rotated, new, allow_secrets=True) == state
    with pytest.raises((KeyError, ValueError)):
        decode_secret_state(rotated, old, allow_secrets=True)


def test_state_secret_field_scope_encrypts_non_sensitive_names():
    keyring = StateKeyring({"1": b"state-key-012345678901234567890123"}, "1")
    encoded = encode_secret_state(
        {"internal_value": "hidden", "public": "visible"},
        fields={"internal_value": {"scope": "SECRET"}}, keyring=keyring,
    )
    assert is_state_envelope(encoded["internal_value"])
    assert encoded["public"] == "visible"


def test_event_signature_rejects_tampering_and_replay():
    secret = b"event-signing-key-0123456789012345"
    payload = {"correlation_key": "C1", "approved": True}
    auth = sign_event("source-a", "APPROVAL", "1", "evt-1", payload, secret, subject="agent-a", issued_at=100)
    assert verify_event_auth(
        "source-a", "APPROVAL", "1", "evt-1", payload, auth, {"default": secret},
        now=100, replay_window_seconds=30,
    )["authenticated"] is True
    tampered = dict(auth)
    tampered["signature"] = "0" * 64
    invalid = verify_event_auth(
        "source-a", "APPROVAL", "1", "evt-1", {"correlation_key": "C1", "approved": False},
        tampered, {"default": secret}, now=100, replay_window_seconds=30,
    )
    assert invalid["authenticated"] is False
    assert any(item["code"] == "EVENT_SIGNATURE_INVALID" for item in invalid["errors"])
    replay = verify_event_auth(
        "source-a", "APPROVAL", "1", "evt-1", payload, auth, {"default": secret},
        now=200, replay_window_seconds=30,
    )
    assert replay["replay"] is True


def test_event_contract_distinguishes_duplicate_and_poison_events():
    assert validate_event("source-a", "APPROVAL", "1", "evt-1", {"ok": True}) == []
    assert validate_event("bad source", "approval", "x", "", [])
    assert classify_event(duplicate=True)["status"] == "DUPLICATE"
    poison = classify_event(validation_errors=[{"code": "EVENT_PAYLOAD_TOO_LARGE"}])
    assert poison["status"] == "DEAD_LETTER"
    assert poison["activation_allowed"] is False


def test_trigger_catalog_covers_manual_api_schedule_database_external_and_internal():
    assert normalize_trigger("MANUAL")["kind"] == "MANUAL"
    assert normalize_trigger("API", {"path": "/graph/run"})["kind"] == "API"
    assert normalize_trigger("SCHEDULE", {"expression": "*/5 * * * *", "timezone": "Asia/Shanghai"})["kind"] == "SCHEDULE"
    assert normalize_trigger("DATABASE", {"source_ref": "db", "event_type": "ROW_CHANGED"})["config"]["event_type"] == "ROW_CHANGED"
    assert normalize_trigger("EXTERNAL", {"source_ref": "webhook", "event_type": "WEBHOOK"})["kind"] == "EXTERNAL"
    assert normalize_trigger("INTERNAL", {"event_type": "GRAPH_READY"})["kind"] == "INTERNAL"
    with pytest.raises(ValueError):
        normalize_trigger("API", {"path": "graph/run"})


def test_scheduler_admission_and_fair_order_are_bounded():
    assert validate_policy({"max_concurrency": 2, "max_queue_depth": 4}) == []
    assert admission_decision({"max_concurrency": 2}, active_count=2)["reason"] == "CONCURRENCY_LIMIT"
    assert admission_decision({"max_queue_depth": 2}, queue_depth=2)["reason"] == "BACKPRESSURE"
    assert admission_decision({"rate_per_minute": 2}, recent_count=2)["reason"] == "RATE_LIMIT"
    items = [
        {"run_id": "r2", "priority": 9, "ready_id": "b"},
        {"run_id": "r1", "priority": 1, "ready_id": "a"},
        {"run_id": "r2", "priority": 1, "ready_id": "c"},
        {"run_id": "r1", "priority": 9, "ready_id": "d"},
    ]
    ordered = fair_order(items, fairness_key="run_id")
    assert [item["run_id"] for item in ordered] == ["r1", "r2", "r1", "r2"]


def test_scheduler_enterprise_quotas_apply_to_matching_scopes():
    policy = {
        "quotas": {
            "workspace": {"max_concurrency": 1},
            "resource_class": {"max_queue_depth": 2},
        }
    }
    assert validate_policy(policy) == []
    blocked = admission_decision(
        policy,
        scopes={"workspace": "ws-1", "resource_class": "gpu"},
        scope_counts={
            "workspace:ws-1": {"active_count": 1},
            "resource_class:gpu": {"queue_depth": 2},
        },
    )
    assert blocked["allowed"] is False
    assert blocked["reason"] == "WORKSPACE_QUOTA_CONCURRENCY_LIMIT"


def test_weighted_fair_order_keeps_aging_bounded():
    ordered = fair_order(
        [
            {"actor_id": "a", "ready_id": "a1", "priority": 1, "fairness_weight": 2},
            {"actor_id": "a", "ready_id": "a2", "priority": 1, "fairness_weight": 2},
            {"actor_id": "b", "ready_id": "b1", "priority": 1, "fairness_weight": 1},
        ],
        fairness_key="actor_id",
    )
    assert [item["ready_id"] for item in ordered] == ["a1", "a2", "b1"]
