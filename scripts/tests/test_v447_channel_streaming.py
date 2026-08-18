"""Regression tests for bounded SSE delivery in v4.4.7."""

from pathlib import Path

import pytest


def test_stream_flushes_throttled_remainder_before_returning():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    stream = runtime.split("def _stream_llm", 1)[1].split("def _set_profile_health", 1)[0]
    assert "pending = \"\"" in stream
    assert "pending += piece" in stream
    assert "on_delta(pending)" in stream
    assert "if pending:" in stream
    assert "pending = \"\"" in stream.split("on_delta(pending)", 1)[0]


def test_stream_delta_contract_sends_chunks_without_dropping_the_final_chunk():
    root = Path(__file__).resolve().parents[1]
    runtime = (root / "lib" / "native_runtime.py").read_text(encoding="utf-8")
    stream = runtime.split("def _stream_llm", 1)[1].split("def _set_profile_health", 1)[0]
    assert "Callers receive only the new delta" in stream
    assert "The complete output" in stream
    assert "The provider may finish before the throttle interval elapses" in stream


def test_stream_flushes_final_piece_when_throttle_interval_is_not_reached(monkeypatch):
    from lib import native_runtime

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            for piece in ("hel", "lo"):
                yield ("data: {\"choices\":[{\"delta\":{\"content\":\"" + piece + "\"}}]}\n\n").encode()
            yield b"data: [DONE]\n\n"

    monkeypatch.setattr(native_runtime.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    ticks = iter((10.0, 10.1, 10.1))
    monkeypatch.setattr(native_runtime.time, "monotonic", lambda: next(ticks))
    deltas = []
    result = native_runtime._stream_llm(
        {"provider_url": "http://llm.example", "model_id": "demo"}, [], deltas.append,
    )
    assert result["content"] == "hello"
    assert "".join(deltas) == "hello"
    assert deltas == ["hello"]


def test_management_knowledge_postcondition_accepts_only_matching_builtin_digest():
    from lib import native_agent_api

    content = {"scope": "database_control_plane", "knowledge_version": "2"}
    digest = native_agent_api._digest(content)

    class Tx:
        def __init__(self, observed_digest):
            self.observed_digest = observed_digest

        def query_one(self, _sql, _params):
            return {
                "manifest_id": "AM_SEED_PLATFORM_ADMIN_KNOWLEDGE_V2",
                "manifest_kind": "MANAGEMENT_KNOWLEDGE",
                "content_json": native_agent_api._json(content),
                "content_digest": self.observed_digest,
                "signature": "BUILTIN-SHA256:" + self.observed_digest,
                "signature_status": "VERIFIED_BUILTIN",
                "status": "PUBLISHED",
                "managed": "Y",
            }

    assert native_agent_api._verify_management_knowledge(Tx(digest))["status"] == "VERIFIED"
    with pytest.raises(native_agent_api.NativeAgentError, match="verification failed"):
        native_agent_api._verify_management_knowledge(Tx("0" * 64))


def test_management_knowledge_uses_immutable_v2_without_rewriting_v1():
    from lib import native_agent_api

    assert native_agent_api.MANAGEMENT_KNOWLEDGE_VERSION == 2

    class Tx:
        def __init__(self):
            self.queries = []
            self.inserts = []

        def query_one(self, sql, params):
            self.queries.append((sql, params))
            return None

        def execute(self, sql, params):
            self.inserts.append((sql, params))

    tx = Tx()
    knowledge = next(item[2] for item in native_agent_api.BUILTIN_MANIFESTS if item[0] == "platform-admin-knowledge")
    assert native_agent_api._ensure_manifest(tx, "platform-admin-knowledge", "MANAGEMENT_KNOWLEDGE", knowledge)
    assert tx.queries[0][1]["version"] == 2
    assert tx.inserts[0][1]["version"] == 2
    assert tx.inserts[0][1]["id"].endswith("_V2")


def test_completed_legacy_bootstrap_automatically_seeds_management_knowledge(monkeypatch):
    from lib import native_agent_api

    class Tx:
        def query_one(self, sql, _params):
            if "CX_NATIVE_BOOTSTRAP" in sql:
                return {"bootstrap_version": "4.3.6", "status": "COMPLETED"}
            return None

    seeded = []
    monkeypatch.setattr(native_agent_api.connection, "execute_transaction_callback", lambda work: work(Tx()))
    monkeypatch.setattr(native_agent_api, "_ensure_principal", lambda *_args: None)
    monkeypatch.setattr(native_agent_api, "_enterprise", lambda: False)
    monkeypatch.setattr(
        native_agent_api, "_ensure_manifest",
        lambda _tx, key, kind, _content: seeded.append((key, kind)) or True,
    )
    monkeypatch.setattr(
        native_agent_api, "_verify_management_knowledge",
        lambda _tx: {"status": "VERIFIED", "digest": "a" * 64},
    )
    result = native_agent_api.bootstrap_native_agents()
    assert ("platform-admin-knowledge", "MANAGEMENT_KNOWLEDGE") in seeded
    assert result["management_knowledge"]["status"] == "VERIFIED"
