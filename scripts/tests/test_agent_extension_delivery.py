"""Regression coverage for observed delivery and profile-bound evaluation."""
import pytest
from lib import telemetry_delivery as telemetry, answer_evaluation as evaluation
from lib import identity_api


def test_agent_visibility_denial_uses_only_binds_in_the_query(monkeypatch):
    monkeypatch.setattr(identity_api, "effective_access", lambda *_: {"decision": "DENY", "scopes": ["NONE"]})
    def query(sql, params):
        assert ":principal_id" not in sql and params == {"agent_id": "agent"}
        return None
    monkeypatch.setattr(identity_api.connection, "execute_query_one", query)
    assert not identity_api._agent_visible_to("unavailable", "agent")


@pytest.mark.parametrize("entry", ["PORTAL", "CHANNEL"])
def test_shared_evaluation_uses_the_authorized_profile_for_model_supplement(monkeypatch, entry):
    monkeypatch.setattr(evaluation, "_require_owner", lambda *_: None)
    monkeypatch.setattr(evaluation, "list_cases", lambda *_a, **_k: [{
        "case_id": "case", "version": 1, "query_text": "General science question",
        "expected_mode": "NO_MATCH", "expected_entities_json": "[]",
    }])
    def lookup(sql, params):
        if "CX_LLM_PROVIDER_PROFILES" in sql:
            return {"profile_id": "approved-profile", "version": 7, "status": "ACTIVE", "health_state": "HEALTHY"}
        return {"agent_id": "agent", "llm_profile_id": "approved-profile", "status": "ACTIVE"}
    monkeypatch.setattr(evaluation.connection, "execute_query_one", lookup)
    monkeypatch.setattr(evaluation.answer_planning, "retrieve", lambda *_: {
        "status": "NO_MATCH", "items": [], "missing_parts": [],
    })
    recorded = []
    def record(*args):
        recorded.append(args)
        return {"passed": args[8]}
    monkeypatch.setattr(evaluation, "record_result", record)
    result = evaluation.run_shared_case("owner", "case", 1, "agent", "approved-profile", {
        "mode": "KNOWLEDGE_FIRST", "allow_model_supplement": "Y",
        "disclosure_profiles": ["approved-profile"],
    }, entry_kind=entry)
    assert result["prepared"]["answer_source"] == "MODEL_SUPPLEMENT"
    assert recorded[0][3:7] == ("approved-profile", 7, entry, "MODEL_SUPPLEMENT")


@pytest.mark.parametrize("http_status,response,expected", [
    (200, {}, "DELIVERED"), (202, None, "DELIVERED"),
    (200, {"partialSuccess": {"rejectedSpans": "1"}}, "FAILED"),
])
def test_claimed_telemetry_is_sent_once_and_commits_observed_status(monkeypatch, http_status, response, expected):
    payload = {"delivery_id": "delivery", "actor_id": "owner", "endpoint_id": "endpoint",
               "revision_no": 1, "projection_digest": "digest"}
    registration = {"timeout_seconds": 3}
    projection = {"resourceSpans": []}
    writes, sends, audits = [], [], []
    class Tx:
        def query_one(self, *_args):
            return {"attempt_id": "attempt"}
        def execute(self, sql, params):
            writes.append((sql, params))
    calls = 0
    def transaction(callback):
        nonlocal calls
        calls += 1
        if calls == 1:
            return payload, registration, projection
        return callback(Tx())
    monkeypatch.setattr(telemetry.connection, "execute_transaction_callback", transaction)
    monkeypatch.setattr(telemetry, "_authority", lambda *_: registration)
    monkeypatch.setattr(telemetry.identity_api, "_audit_tx", lambda *args: audits.append(args))
    def post(record, value, **kwargs):
        sends.append((record, value, kwargs))
        return response, {}, http_status
    monkeypatch.setattr(telemetry.protocols, "post", post)
    assert telemetry.deliver_one()["status"] == expected
    assert len(sends) == 1 and sends[0][1] == projection
    assert len(writes) == 2 and all(item[1]["state"] == expected for item in writes)
    assert audits[-1][2] == "OTLP_OBSERVED"
