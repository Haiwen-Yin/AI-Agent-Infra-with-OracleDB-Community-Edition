"""Content boundary regression: no uninspected bytes reach provider or consumer."""
import base64
import json
from unittest.mock import Mock

import pytest
from lib import content_security as security, native_runtime


@pytest.mark.parametrize("value", ["-----BEGIN PRIVATE KEY-----", "sk-" + "a" * 40,
    "api_key=" + "x" * 30, "api_\u200bkey=" + "x" * 30,
    "%61pi_key=" + "x" * 30, "base64:" + base64.b64encode(b"-----BEGIN PRIVATE KEY-----").decode()])
def test_encoded_credentials_denied_without_recording_content(value):
    result = security.scan(value, "OUTPUT")
    assert result["decision"] == "DENY"
    assert value not in json.dumps(result)
    with pytest.raises(security.ContentDenied):
        security.enforce(value, "OUTPUT")


def test_quoted_attack_instruction_is_advisory_not_agent_ban():
    result = security.scan('Security training: "ignore previous instructions" is a prompt injection example.', "KNOWLEDGE")
    assert result["decision"] == "WARN"
    assert not any("agent" in key for key in result)


def test_oversize_and_unsupported_formats_fail_closed():
    assert security.scan("x" * (security.MAX_BYTES + 1), "USER_INPUT")["decision"] == "DENY"
    with pytest.raises(security.ContentDenied):
        security.inspect_messages([{"role": "user", "content": [{"type": "image_url"}]}])


def test_input_denied_before_network(monkeypatch):
    network = Mock()
    monkeypatch.setattr(native_runtime.urllib.request, "urlopen", network)
    with pytest.raises(security.ContentDenied):
        native_runtime._call_llm({"provider_url": "http://example.test", "model_id": "test"},
                                 [{"role": "user", "content": "-----BEGIN PRIVATE KEY-----"}])
    network.assert_not_called()


def test_credential_split_across_chunks_releases_nothing(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def __iter__(self):
            for piece in ["Safe introduction. ", "-----BEGIN ", "PRIVATE", " KEY-----"]:
                yield ("data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n").encode()
            yield b"data: [DONE]\n"
    monkeypatch.setattr(native_runtime.urllib.request, "urlopen", lambda *_a, **_k: Response())
    delivered = []
    with pytest.raises(security.ContentDenied):
        native_runtime._stream_llm({"provider_url": "http://example.test", "model_id": "test"},
            [{"role": "user", "content": "hello"}], delivered.append)
    assert delivered == []
