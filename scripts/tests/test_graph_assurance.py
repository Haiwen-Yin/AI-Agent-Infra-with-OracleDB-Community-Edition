"""v4.3.3 pure assurance and supply-chain contract tests."""

from __future__ import annotations

import os

import pytest

from lib import graph_assurance, graph_supply_chain


def _document():
    return {
        "format": "chuanxu-graph-definition",
        "format_version": "1",
        "definition": {"version": {"nodes": [{"node_key": "start", "node_type": "START", "config": {}}]}},
    }


def test_failpoints_are_test_mode_only(monkeypatch):
    monkeypatch.delenv("CX_GRAPH_TEST_MODE", raising=False)
    graph_assurance.clear_failpoints_for_test()
    with pytest.raises(PermissionError):
        graph_assurance.arm_failpoint_for_test("before_claim")

    monkeypatch.setenv("CX_GRAPH_TEST_MODE", "1")
    with graph_assurance.failpoint_for_test("before_claim"):
        with pytest.raises(graph_assurance.FailpointTriggered):
            graph_assurance.checkpoint("before_claim")
        graph_assurance.checkpoint("before_claim")


def test_supply_chain_signing_detects_tampering():
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    unsigned = graph_supply_chain.attach_envelope(_document(), publisher="publisher-a")
    signed = graph_supply_chain.sign_document(unsigned, private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    ), key_id="publisher-a-key")
    key = graph_supply_chain._b64(public)
    assert graph_supply_chain.verify_document(signed, {"publisher-a-key": key})["trusted"] is True

    signed["definition"]["version"]["nodes"][0]["node_type"] = "AGENT"
    assert graph_supply_chain.verify_document(signed, {"publisher-a-key": key})["code"] == "DOCUMENT_DIGEST_MISMATCH"


def test_unsigned_and_arbitrary_code_imports_remain_untrusted_or_rejected():
    unsigned = graph_supply_chain.attach_envelope(_document())
    assert graph_supply_chain.verify_document(unsigned, {})["code"] == "UNSIGNED"
    unsafe = _document()
    unsafe["definition"]["version"]["nodes"][0]["config"] = {"expression": "__import__('os').system('id')"}
    findings = graph_supply_chain.scan_document(unsafe)
    assert any(item["code"] == "ARBITRARY_CODE_REJECTED" for item in findings)


def test_dependency_lock_is_canonical_and_compatibility_is_bounded():
    envelope = graph_supply_chain.make_envelope(_document(), dependencies=[
        {"kind": "skill", "name": "review", "version": "1.0"},
        {"kind": "executor", "name": "agent", "version": "2.0"},
    ])
    assert [item["kind"] for item in envelope["dependencies"]] == ["EXECUTOR", "SKILL"]
    with pytest.raises(ValueError):
        graph_supply_chain.make_envelope(_document(), compatibility="UNKNOWN")


def test_assurance_surface_is_protected_and_failpoints_have_no_web_route():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    server = (root / "visualization" / "server.py").read_text(encoding="utf-8")
    template = (root / "visualization" / "templates" / "graph.html").read_text(encoding="utf-8")
    for route in (
        "/api/graph-assurance/invariants",
        "/api/graph-assurance/evidence",
        "/api/graph-dynamic/proposals",
        "/api/a2a/agent-card",
        "/api/telemetry/status",
    ):
        assert route in server
    assert "arm_failpoint_for_test" not in server
    assert "CX_GRAPH_TEST_MODE" not in server
    assert 'id="graph-view-assurance"' in template
    assert 'id="assuranceInvariants"' in template
