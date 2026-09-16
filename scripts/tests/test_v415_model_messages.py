"""Provider compatibility must preserve instruction order and role boundaries."""
import json
import pytest
from lib import native_runtime


@pytest.mark.parametrize("stream", [False, True])
def test_provider_receives_one_leading_system_message(monkeypatch, stream):
    messages = [{"role": "system", "content": "Rules"},
                {"role": "system", "content": "Quoted reference data"},
                {"role": "user", "content": "Question"}]
    sent = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, *_):
            return json.dumps({"model": "demo", "choices": [{"message": {"content": "42"}}]}).encode()
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"42"}}]}\n'
            yield b'data: [DONE]\n'

    def open_request(request, **_):
        sent.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(native_runtime.urllib.request, "urlopen", open_request)
    profile = {"provider_url": "http://example.test/v1", "model_id": "demo"}
    result = native_runtime._stream_llm(profile, messages, lambda _: None) if stream else native_runtime._call_llm(profile, messages)
    assert result["content"] == "42"
    assert sent[0]["messages"] == [{"role": "system", "content": "Rules\n\nQuoted reference data"}, messages[2]]
    assert len(messages) == 3 and messages[0]["content"] == "Rules"


def test_conversation_messages_are_never_promoted_or_reordered():
    messages = [{"role": "user", "content": "untrusted"}, {"role": "system", "content": "later"}]
    assert native_runtime._provider_messages(messages) == messages
