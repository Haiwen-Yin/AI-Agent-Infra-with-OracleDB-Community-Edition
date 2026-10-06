"""Behavioral capability checks shared by HTTP, protocol and Worker services."""
import pytest

from lib import effective_capabilities as capabilities


@pytest.fixture
def authority(monkeypatch):
    monkeypatch.setattr(capabilities.identity_api, "effective_access", lambda actor, action: {"decision": "ALLOW" if actor == "admin" else "DENY"})
    monkeypatch.setattr(capabilities.graph_production_profile, "state", lambda key: "CONTROLLED")
    monkeypatch.setattr(capabilities.graph_production_profile, "require", lambda key, controlled=False: "CONTROLLED" if controlled else (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(capabilities.model_capability_api, "state", lambda key: "READ_ONLY")


def test_controlled_operation_uses_database_state_and_current_actor(authority):
    assert capabilities.require("admin", graph="a2a_gateway", model="a2a_exchange")["graph_state"] == "CONTROLLED"
    with pytest.raises(PermissionError):
        capabilities.require("other", graph="a2a_gateway")


def test_read_only_posture_cannot_execute_a_write(authority):
    with pytest.raises(PermissionError):
        capabilities.require("admin", model="mcp_execution", impact="WRITE")


def test_proposal_never_becomes_execution(authority, monkeypatch):
    monkeypatch.setattr(capabilities.model_capability_api, "state", lambda key: "PROPOSAL_ONLY")
    assert capabilities.require("admin", model="model_tool_calls", proposal=True)["decision"] == "PROPOSAL"
    with pytest.raises(PermissionError):
        capabilities.require("admin", model="model_tool_calls")


def test_unknown_or_disabled_matrix_remains_unavailable(authority, monkeypatch):
    monkeypatch.setattr(capabilities.model_capability_api, "state", lambda key: "OFF")
    with pytest.raises(PermissionError):
        capabilities.require("admin", model="mcp_discovery")


@pytest.mark.parametrize("path, expected", [
    ("/api/graph-dynamic/proposals", "graph_manifest_draft_import"),
    ("/api/graph-runs/run/migration-preflight", "graph_inspection"),
    ("/api/graph-runs/run/offline-replay", "graph_inspection"),
    ("/api/graph-runs/run/migrate", "graph_dynamic_migration"),
    ("/api/graph-runs/run/replay", "graph_replay"),
    ("/api/graph-runs/run/fork", "graph_checkpoint_fork"),
    ("/api/a2a/tasks/run", "a2a_gateway"),
    ("/api/telemetry/status", "otel_export"),
    ("/api/unrelated/migrate", None),
])
def test_offline_analysis_and_draft_authoring_do_not_require_live_migration(path, expected):
    assert capabilities.graph_operation(path) == expected
