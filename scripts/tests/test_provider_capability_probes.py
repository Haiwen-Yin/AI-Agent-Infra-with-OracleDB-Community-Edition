"""Provider evidence checks that prevent ignored fields and stale contracts."""
import json
import pytest
from lib import provider_capability_probes as probes, native_agent_api

PROFILE = {"model_id": "qwen/qwen3.8-27b", "profile_id": "profile", "version": 3}


def completion(content="CX_OK", **message):
    return {"model": PROFILE["model_id"], "choices": [{"message": {"content": content, **message}, "finish_reason": "stop"}]}


def test_tool_proposal_requires_an_actual_matching_call():
    body = probes.payload("TOOL_PROPOSAL", PROFILE["model_id"], {})
    assert body["tool_choice"] == "required"
    with pytest.raises(ValueError, match="TOOL_PROPOSAL_MISMATCH"):
        probes.observe_json("TOOL_PROPOSAL", PROFILE, completion())
    actual = completion(None, tool_calls=[{"type": "function", "function": {"name": "cx_probe", "arguments": '{"ok":"CX_OK"}'}}])
    assert probes.observe_json("TOOL_PROPOSAL", PROFILE, actual)["tool_proposal_valid"]


def test_structured_output_validates_body_not_provider_claim():
    assert probes.observe_json("STRUCTURED_OUTPUT", PROFILE, completion('{"ok":"CX_OK"}'))["schema_valid"]
    with pytest.raises(Exception):
        probes.observe_json("STRUCTURED_OUTPUT", PROFILE, completion('{"ok":"wrong"}'))


def test_ignored_image_and_hidden_reasoning_do_not_prove_capability():
    with pytest.raises(ValueError, match="PROBE_ANSWER_MISMATCH"):
        probes.observe_json("IMAGE_INPUT", PROFILE, completion())
    result = probes.observe_json("IMAGE_INPUT", PROFILE, completion("RED", reasoning_content="private reasoning"))
    assert result["reasoning_present"]
    assert "private reasoning" not in json.dumps(result)


def test_wrong_model_and_incomplete_usage_fail():
    wrong = {**completion(), "model": "another-model"}
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        probes.observe_json("TEXT", PROFILE, wrong)
    with pytest.raises(ValueError, match="USAGE_UNAVAILABLE"):
        probes.observe_json("USAGE", PROFILE, completion())


def test_parameter_contract_is_exact_current_revision(monkeypatch):
    monkeypatch.setattr(probes.connection, "execute_query_one", lambda *_: {"VERSION": 3, "STATUS": "ACTIVE"})
    monkeypatch.setattr(probes.connection, "execute_query", lambda *_: [{"PARAMETER_KEY": "reasoning_effort", "VALUE_JSON": '"none"'}])
    assert probes.apply_parameters(PROFILE, {"model": "m"}) == {"model": "m", "reasoning_effort": "none"}
    with pytest.raises(PermissionError, match="changed"):
        probes.apply_parameters({**PROFILE, "version": 2}, {})


def test_unregistered_reasoning_parameters_are_rejected():
    for value in ({"arbitrary": True}, {"reasoning_effort": "unlimited"}, {"preserve_thinking": 1}):
        with pytest.raises(ValueError):
            probes.parameters(value)


@pytest.mark.parametrize("message", [{"content": ""}, {"content": "  "}, {"reasoning_content": "hidden only"}])
def test_health_check_cannot_accept_empty_completion(monkeypatch, message):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, *_): return json.dumps({"model": "m", "choices": [{"message": message}]}).encode()
    monkeypatch.setattr(native_agent_api.urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(native_agent_api.connection, "execute_transaction_callback", lambda callback: callback(None))
    monkeypatch.setattr(native_agent_api, "_audit", lambda *_a, **_k: None)
    with pytest.raises(native_agent_api.NativeAgentError, match="no content"):
        native_agent_api.probe_llm_profile("admin", "test", "http://provider/v1", "m", "")
