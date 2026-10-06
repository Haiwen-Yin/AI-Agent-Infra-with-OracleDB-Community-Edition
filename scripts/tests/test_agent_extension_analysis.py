"""Offline analysis detects corrupt history and preserves bounded obligations."""
import json
from datetime import datetime, timedelta, timezone
import pytest
from lib import graph_inspection as graphs, graph_runtime, context_derivations as context, answer_planning


def test_offline_replay_reconstructs_reducers_and_detects_changed_facts():
    state = {"n": 5}
    checkpoint = {"checkpoint_id": "cp", "seq_no": 1, "parent_checkpoint_id": None, "state_json": json.dumps(state), "state_hash": graph_runtime._hash(state)}
    event = {"seq_no": 1, "prior_checkpoint_id": None, "checkpoint_id": "cp", "delta_json": '{"n":3}', "reducer_json": '{"reducers":{"n":"SUM"}}', "state_hash": graph_runtime._hash(state)}
    assert graphs.replay_facts({"n": 2}, [event], [checkpoint])["status"] == "VERIFIED"
    result = graphs.replay_facts({"n": 2}, [{**event, "delta_json": '{"n":4}'}], [checkpoint])
    assert result["status"] == "DISCREPANCIES"
    assert not result["execution_invoked"]


def test_migration_preflight_reports_removed_pending_nodes_leases_and_budget():
    source = {"nodes": [{"node_key": "pending", "side_effect_class": "NONE"}]}
    target = {"nodes": []}
    result = graphs.migration_assessment(source, target, [{"node_key": "pending", "status": "WAITING"}], {}, {"max_tokens": 5}, {"tokens": 6}, ["lease"])
    assert {item["code"] for item in result["findings"]} == {"PENDING_NODE_REMOVED", "ACTIVE_LEASES", "TARGET_BUDGET_EXCEEDED"}
    assert not result["live_migration_performed"]


def test_migration_preflight_keeps_utc_lease_active_in_a_local_database_session(monkeypatch):
    source = {"graph_id": "graph", "status": "PUBLISHED", "nodes": [], "definition_digest": "digest"}
    monkeypatch.setattr(graphs, "_run", lambda *_: {
        "graph_version_id": "source", "status": "PAUSED", "budget_usage_json": "{}", "definition_digest": "digest",
    })
    monkeypatch.setattr(graphs.definitions, "get_version", lambda *_: source)
    monkeypatch.setattr(graphs.graph_assurance, "record_evidence_tx", lambda *_a, **_k: "evidence")
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1)
    local_database_now = expiry + timedelta(hours=8)
    class Tx:
        def query(self, sql, params):
            if "GRAPH_ATTEMPTS" in sql:
                comparison = params.get("lease_now", local_database_now)
                return [{"attempt_id": "active", "fencing_token": 1}] if expiry > comparison else []
            return []
    monkeypatch.setattr(graphs.connection, "execute_transaction_callback", lambda operation: operation(Tx()))
    report = graphs.migration_preflight("owner", "run", "target", {})
    assert report["status"] == "BLOCKED"
    assert {item["code"] for item in report["findings"]} == {"ACTIVE_LEASES"}


def test_reaper_preserves_unexpired_utc_lease_in_a_local_database_session(monkeypatch):
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1)
    local_database_now = expiry + timedelta(hours=8)
    class Tx:
        def query(self, sql, params):
            if "GRAPH_ATTEMPTS" in sql:
                comparison = params.get("lease_now", local_database_now)
                return [{"attempt_id": "active", "node_run_id": "node", "run_id": "run", "fencing_token": 1}] if expiry <= comparison else []
            return []
        def execute(self, *_):
            raise AssertionError("A live lease must not be fenced")
    monkeypatch.setattr(graph_runtime.connection, "execute_transaction_callback", lambda operation: operation(Tx()))
    assert graph_runtime.reap_expired_leases() == 0


def test_context_budget_reserves_response_and_instructions():
    result = context.budget_plan(2048, 512, 256, 1400)
    assert result["source_budget"] == 1280
    assert result["derivation_required"]


def test_extract_keeps_constraints_and_incomplete_work_verbatim():
    original = {"constraints": ["Keep TEST"], "incomplete_work": ["verify six editions"], "optional": "x" * 1000}
    result = context.extract(json.dumps(original), 220)
    assert result["preserved_obligations"] == [{"constraints": original["constraints"], "incomplete_work": original["incomplete_work"]}]
    assert len(context.canonical(result).encode()) <= 220
    with pytest.raises(ValueError, match="Mandatory"):
        context.extract(json.dumps(original), 10)


def test_partial_knowledge_is_separate_from_general_model_knowledge():
    policy = {"mode": "KNOWLEDGE_FIRST", "allow_model_supplement": "Y", "disclosure_profiles": ["model"]}
    retrieval = {"status": "PARTIAL_MATCH", "items": [{"entity_id": "k", "title": "川序", "content": "Platform fact", "digest": "d"}], "missing_parts": ["quantum mechanics"]}
    plan = answer_planning.prepare("question", "model", policy, retrieval)
    assert plan["answer_source"] == "MIXED_SOURCES"
    assert "separate explicitly labeled section" in plan["messages"][0]["content"]
    policy["mode"] = "KNOWLEDGE_ONLY"
    assert answer_planning.prepare("question", "model", policy, retrieval)["answer_source"] == "KNOWLEDGE_GROUNDED"


def test_bare_ambiguous_vendor_needs_clarification_before_model(monkeypatch):
    monkeypatch.setattr(answer_planning.knowledge_grounding, "search", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("No retrieval for ambiguous subject")))
    assert answer_planning.retrieve("human", "agent", "Oracle")["status"] == "AMBIGUOUS"


def test_delegated_graph_management_cannot_inspect_another_owners_run(monkeypatch):
    monkeypatch.setattr(graphs.effective_capabilities, "require", lambda *_a, **_k: None)
    monkeypatch.setattr(graphs.effective_capabilities, "authorize", lambda *_: {"scopes": ["ASSIGNED"]})
    class Tx:
        def query_one(self, *_):
            return {"run_id": "run", "actor_id": "another-owner"}
    with pytest.raises(PermissionError, match="management scope"):
        graphs._run(Tx(), "delegated", "run")
