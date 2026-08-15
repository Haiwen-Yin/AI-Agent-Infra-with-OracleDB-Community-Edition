from pathlib import Path

from lib import a2a_gateway, graph_governance, graph_runtime, graph_state


UI_SOURCE = Path(__file__).parents[1] / "web" / "src" / "App.tsx"


def test_dashboard_uses_whitelisted_url_state_and_browser_history():
    source = UI_SOURCE.read_text(encoding="utf-8")
    assert "function useUrlState" in source
    assert 'window.addEventListener("popstate"' in source
    assert 'window.history.replaceState({}, "", url.pathname + url.search)' in source
    assert "allowed.includes" in source


def test_deep_linked_dashboard_sections_are_declared():
    source = UI_SOURCE.read_text(encoding="utf-8")
    for key in ("config", "section", "tab", "view", "library", "panel", "channel", "focus"):
        assert f'"{key}"' in source
    for value in ("registered", "external", "native", "chat", "manage", "relationships"):
        assert f'"{value}"' in source


def test_sensitive_channel_content_is_not_added_to_url_state():
    source = UI_SOURCE.read_text(encoding="utf-8")
    assert 'useUrlParam("channel")' in source
    assert 'useUrlParam("message")' not in source
    assert 'useUrlParam("token")' not in source
    assert 'useUrlParam("api_key")' not in source


def test_graph_state_scope_and_reducer_contracts_are_deterministic():
    assert graph_state.validate_scopes({"shared": {"scope": "GRAPH_SHARED"}}) == []
    assert graph_state.validate_scopes({"secret": {"scope": "SECRET", "output_visible": True}})
    assert graph_state.reduce_values("SET_UNION", [["b", "a"], ["a", "c"]]) == ["a", "b", "c"]
    try:
        graph_state.reduce_values("REPLACE", [{"v": 1}, {"v": 2}])
    except ValueError as exc:
        assert "conflicting" in str(exc)
    else:
        raise AssertionError("conflicting REPLACE values must be rejected")


def test_graph_budget_and_agent_protocol_metadata_remain_governed():
    decision = graph_governance.budget_decision(
        {"max_tokens": 100, "max_calls": 2},
        {"tokens": 90, "calls": 1},
        {"tokens": 20, "calls": 1},
    )
    assert decision["allowed"] is False
    assert {item["metric"] for item in decision["hard_exceeded"]} == {"tokens"}

    card = a2a_gateway.agent_card(
        {"skills": [{"skill_id": "claimed-admin", "skill_name": "Admin"}]},
        authenticated=True,
        granted_skills=[],
    )
    assert card["skills"] == []


def test_fork_replay_pauses_before_non_repeatable_effects():
    safe = graph_runtime.fork_replay_decision({
        "nodes": [{"node_key": "read", "side_effect_class": "NONE"}],
    })
    governed = graph_runtime.fork_replay_decision({
        "nodes": [
            {"node_key": "notify", "side_effect_class": "NON_IDEMPOTENT"},
            {"node_key": "charge", "side_effect_class": "NON_IDEMPOTENT"},
        ],
    })

    assert safe == {
        "allowed": True, "status": "RUNNING", "reason_code": None,
        "non_repeatable_nodes": [],
    }
    assert governed == {
        "allowed": False, "status": "PAUSED",
        "reason_code": "FORK_REPLAY_APPROVAL_REQUIRED",
        "non_repeatable_nodes": ["charge", "notify"],
    }


def test_run_contract_rejects_plan_version_or_digest_mismatch():
    digest = "a" * 64
    plan_digest = "b" * 64
    version = {"definition_digest": digest, "schema_version": "1.0"}
    plan = {
        "graph_version_id": "version-1", "definition_digest": digest,
        "plan_digest": plan_digest,
    }
    assert graph_runtime.run_contract_snapshot("version-1", "plan-1", version, plan) == {
        "definition_digest": digest,
        "plan_digest": plan_digest,
        "compatibility_level": "COMPATIBLE",
        "state_schema_version": "1.0",
        "budget_schema_version": "graph-budget/1",
    }

    for invalid in (
        dict(plan, graph_version_id="version-2"),
        dict(plan, definition_digest="c" * 64),
        dict(plan, plan_digest="not-a-digest"),
    ):
        try:
            graph_runtime.run_contract_snapshot("version-1", "plan-1", version, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("a mismatched immutable Run contract must fail closed")


def test_v445_has_equivalent_additive_run_contract_migrations():
    root = Path(__file__).parents[2]
    required = {
        "DEFINITION_DIGEST", "PLAN_DIGEST", "COMPATIBILITY_LEVEL",
        "STATE_SCHEMA_VERSION", "BUDGET_SCHEMA_VERSION",
    }
    for adapter in ("oracle", "pg", "yashandb"):
        source = (root / "adapters" / adapter / "deploy" /
                  "45_v4_4_5_graph_run_contract.sql").read_text(encoding="utf-8").upper()
        assert required <= {marker for marker in required if marker in source}
        assert "P.GRAPH_VERSION_ID = R.GRAPH_VERSION_ID" in source


class _ResolutionTx:
    def __init__(self, row):
        self.row = row

    def query_one(self, _sql, _params):
        return self.row


def test_fork_replay_resolution_is_bound_to_run_and_action():
    approved = {
        "approval_id": "approval-1", "status": "APPROVED",
        "resource_id": "run-child", "action": "GRAPH_FORK_REPLAY",
    }
    assert graph_runtime._fork_replay_resolution(
        _ResolutionTx(approved), "run-child",
        {"type": "APPROVAL", "approval_id": "approval-1"},
    ) == {"type": "APPROVAL", "approval_id": "approval-1"}

    try:
        graph_runtime._fork_replay_resolution(
            _ResolutionTx(dict(approved, resource_id="another-run")), "run-child",
            {"type": "APPROVAL", "approval_id": "approval-1"},
        )
    except PermissionError as exc:
        assert "not bound" in str(exc)
    else:
        raise AssertionError("an approval for another Run must fail closed")

    assert graph_runtime._fork_replay_resolution(
        _ResolutionTx(None), "run-child",
        {"type": "COMPENSATION", "evidence": "artifact://compensation/42"},
    )["type"] == "COMPENSATION"
