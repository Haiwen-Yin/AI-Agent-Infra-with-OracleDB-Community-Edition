try:
    from lib import model_capability_api as api
except ImportError:  # Source-tree test layout.
    from shared.lib import model_capability_api as api


def _rows():
    return [
        {"CAPABILITY_KEY": key, "STATE": "READ_ONLY", "VERSION": 1, "MANDATORY": "N",
         "SECURITY_DOMAIN_ID": None, "SOURCE_DIGEST": None, "SCHEMA_DIGEST": None,
         "RESOURCE_SCOPE_JSON": "{}", "EVIDENCE_REF": None, "REASON": "test",
         "UPDATED_BY": "SYSTEM", "UPDATED_AT": None}
        for key in sorted(api.CAPABILITIES)
    ]


def test_registry_is_complete(monkeypatch):
    monkeypatch.setattr(api.connection, "execute_query", lambda *_a, **_k: _rows())
    result = api.list_capabilities()
    assert result["version"] == "4.4.14"
    assert {item["capability_key"] for item in result["items"]} == api.CAPABILITIES


def test_external_execution_fails_closed_without_trust_metadata(monkeypatch):
    monkeypatch.setattr(api, "state", lambda _key: "GOVERNED_EXECUTOR")
    decision = api.execution_decision("mcp_execution", "WRITE", approved=True)
    assert decision["disposition"] == "ACTION_CARD"
    assert decision["trusted_metadata"] is False


def test_approved_governed_execution_requires_all_trust_metadata(monkeypatch):
    monkeypatch.setattr(api, "state", lambda _key: "GOVERNED_EXECUTOR")
    decision = api.execution_decision(
        "mcp_execution", "WRITE", approved=True, source_digest="a" * 64,
        schema_digest="b" * 64, security_domain_id="DEFAULT", resource_scope={"ids": ["K1"]},
    )
    assert decision["disposition"] == "EXECUTE"


def test_schema_mismatch_removes_content_and_tool_calls():
    response = {
        "id": "provider-request", "choices": [{"finish_reason": "tool_calls", "message": {
            "content": '{"unsafe":true}', "reasoning_content": "private chain of thought",
            "tool_calls": [{"id": "call-1", "function": {"name": "write"}}],
        }}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                  "completion_tokens_details": {"reasoning_tokens": 2}},
    }
    result = api.normalize_provider_response(
        provider_key="test", model_id="model", request_id="request", response=response,
        schema_valid=False,
    )
    assert result["finish_state"] == "schema_mismatch"
    assert result["content"] is None
    assert result["tool_calls"] == []
    assert result["reasoning"] == {"present": True, "tokens": 2}
    assert "private chain of thought" not in str(result)
    assert len(result["evidence_digest"]) == 64


def test_timeout_cancellation_and_retry_evidence():
    result = api.normalize_provider_response(
        provider_key="test", model_id="model", request_id="request", response={},
        latency_ms=321, retry_count=2, timed_out=True, cancelled=True,
    )
    assert result["timeout"] is True
    assert result["cancelled"] is True
    assert result["retry_count"] == 2
    assert result["latency_ms"] == 321
