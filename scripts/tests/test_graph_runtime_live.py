"""Repeatable v4.2 live Graph Runtime checks.

Run from a built package with an explicit encrypted configuration path::

    source scripts/python_runtime.sh && export PYTHON_BIN="$(cx_resolve_python)" && \
    cx_prepare_python_environment "$PYTHON_BIN" && \
    PYTHONPATH=scripts "$PYTHON_BIN" scripts/tests/test_graph_runtime_live.py \
        --database oracle --config /path/to/config.json

The runner prints only a compact, credential-free JSON result.  It creates
unique Graph objects and does not assume the test database is empty.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _configure(package_root: Path, config_file: Path):
    scripts = package_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from lib import config as config_module

    config_module._PROJECT_ROOT = config_file.resolve().parent
    config_module._config = None
    from lib import connection

    connection._pool = None
    return connection


def run_live_checks(package_root: Path, config_file: Path, database: str) -> Dict[str, Any]:
    connection = _configure(package_root, config_file)
    from lib import graph_compiler as compiler
    from lib import graph_definition_api as definitions
    from lib import graph_event_api as events
    from lib import graph_runtime as runtime
    from lib import graph_worker as worker
    from lib import graph_assurance, graph_dynamic, graph_supply_chain, a2a_gateway, graph_telemetry

    actor = "v420-edge-" + uuid.uuid4().hex[:12]
    suffix = uuid.uuid4().hex[:8]
    checks: Dict[str, bool] = {}

    def make_graph(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                   budget: Dict[str, Any] | None = None) -> Tuple[str, str]:
        graph_id = definitions.create_graph(
            "v420-edge-" + uuid.uuid4().hex[:10], actor
        )
        version_id = definitions.create_version(
            graph_id, nodes, edges, actor_id=actor, reason="edge coverage",
            budget=budget or {},
        )
        published = compiler.compile_and_publish(
            version_id, actor, "edge coverage publish"
        )
        plan_id = published.get("plan_id") or definitions.get_version(version_id).get("plan_id")
        return version_id, plan_id

    def new_run(version_id: str, plan_id: str, label: str) -> str:
        return runtime.create_run(
            version_id, plan_id, actor, {"label": label}, {},
            "idem-" + label + "-" + uuid.uuid4().hex[:8],
        )

    def advertise(worker_id: str) -> None:
        worker.advertise(
            worker_id, "edge-test", ["graph"], agent_id=actor,
            node_id="node-" + database,
        )

    def claim(worker_id: str, run_id: str, node_key: str):
        return worker.claim(
            worker_id, "edge-test", ["graph"], 120, agent_id=actor,
            node_id="node-" + database, node_key=node_key,
        )

    # Lease expiry is forced through the database so the check is fast and
    # verifies the same timestamp comparison used by the reaper.
    lease_start = "lease-start-" + suffix
    lease_end = "lease-end-" + suffix
    version_id, plan_id = make_graph(
        [{"node_key": lease_start, "node_type": "START"},
         {"node_key": lease_end, "node_type": "END"}],
        [{"edge_id": "lease-edge-" + suffix,
          "source_node_key": lease_start, "target_node_key": lease_end}],
    )
    run_id = new_run(version_id, plan_id, "lease")
    advertise("lease-a-" + suffix)
    old = claim("lease-a-" + suffix, run_id, lease_start)
    assert old
    expired = datetime(2000, 1, 1)
    connection.execute(
        "UPDATE GRAPH_ATTEMPTS SET LEASE_EXPIRES_AT = :expired WHERE ATTEMPT_ID = :attempt_id",
        {"expired": expired, "attempt_id": old["attempt_id"]},
    )
    connection.execute(
        "UPDATE GRAPH_LEASE_TOKENS SET EXPIRES_AT = :expired WHERE ATTEMPT_ID = :attempt_id",
        {"expired": expired, "attempt_id": old["attempt_id"]},
    )
    assert runtime.reap_expired_leases() >= 1
    assert worker.heartbeat(old["lease_token"]) is False
    advertise("lease-b-" + suffix)
    fresh = claim("lease-b-" + suffix, run_id, lease_start)
    assert fresh and fresh["fencing_token"] == 2
    try:
        worker.complete(old["lease_token"], {"stale": True}, actor)
    except PermissionError:
        pass
    else:
        raise AssertionError("stale lease completed")
    assert runtime.cancel_run(run_id, actor, "lease fencing test")
    checks["lease_recovery_and_stale_fencing"] = True

    # The conditional Ready update must allow exactly one concurrent claimant.
    concurrent_start = "concurrent-start-" + suffix
    concurrent_end = "concurrent-end-" + suffix
    version_id, plan_id = make_graph(
        [{"node_key": concurrent_start, "node_type": "START"},
         {"node_key": concurrent_end, "node_type": "END"}],
        [{"edge_id": "concurrent-edge-" + suffix,
          "source_node_key": concurrent_start, "target_node_key": concurrent_end}],
    )
    run_id = new_run(version_id, plan_id, "concurrency")

    def race(index: int):
        worker_id = f"race-{index}-{suffix}"
        advertise(worker_id)
        return claim(worker_id, run_id, concurrent_start)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(race, (1, 2)))
    assert sum(item is not None for item in claimed) == 1
    assert runtime.cancel_run(run_id, actor, "claim race test")
    checks["claim_concurrency"] = True

    # A hard call budget blocks the next Ready node atomically.
    budget_start = "budget-start-" + suffix
    budget_end = "budget-end-" + suffix
    version_id, plan_id = make_graph(
        [{"node_key": budget_start, "node_type": "START"},
         {"node_key": budget_end, "node_type": "END"}],
        [{"edge_id": "budget-edge-" + suffix,
          "source_node_key": budget_start, "target_node_key": budget_end}],
        {"max_calls": 1},
    )
    run_id = new_run(version_id, plan_id, "budget")
    budget_worker = "budget-" + suffix
    advertise(budget_worker)
    attempt = claim(budget_worker, run_id, budget_start)
    assert attempt
    worker.complete(attempt["lease_token"], {"budget": "first"}, actor)
    assert claim(budget_worker, run_id, budget_end) is None
    assert runtime.get_run(run_id)["status"] == "REVIEW_REQUIRED"
    checks["budget_hard_limit"] = True

    # Fan-out/fan-in must retain branch records and commit the Join once.
    start = "join-start-" + suffix
    left = "join-left-" + suffix
    right = "join-right-" + suffix
    join = "join-node-" + suffix
    end = "join-end-" + suffix
    join_key = "join-key-" + suffix
    nodes = [{"node_key": key, "node_type":
              "START" if key == start else "END" if key == end else "AGENT"}
             for key in (start, left, right, join, end)]
    edges = [
        {"edge_id": "join-start-left-" + suffix, "source_node_key": start,
         "target_node_key": left, "edge_kind": "FAN_OUT"},
        {"edge_id": "join-start-right-" + suffix, "source_node_key": start,
         "target_node_key": right, "edge_kind": "FAN_OUT"},
        {"edge_id": "join-left-join-" + suffix, "source_node_key": left,
         "target_node_key": join, "edge_kind": "FAN_IN", "join_key": join_key,
         "config": {"join_strategy": "ALL", "reducer": "APPEND"}},
        {"edge_id": "join-right-join-" + suffix, "source_node_key": right,
         "target_node_key": join, "edge_kind": "FAN_IN", "join_key": join_key,
         "config": {"join_strategy": "ALL", "reducer": "APPEND"}},
        {"edge_id": "join-join-end-" + suffix, "source_node_key": join,
         "target_node_key": end},
    ]
    version_id, plan_id = make_graph(nodes, edges)
    run_id = new_run(version_id, plan_id, "join")
    join_worker = "join-" + suffix
    advertise(join_worker)
    attempt = claim(join_worker, run_id, start)
    assert attempt
    worker.complete(attempt["lease_token"], {"branch": "start"}, actor)
    left_attempt = claim(join_worker, run_id, left)
    right_attempt = claim(join_worker, run_id, right)
    assert left_attempt and right_attempt
    worker.complete(left_attempt["lease_token"], {"branch": "left"}, actor)
    worker.complete(right_attempt["lease_token"], {"branch": "right"}, actor)
    attempt = claim(join_worker, run_id, join)
    assert attempt
    worker.complete(attempt["lease_token"], {"joined": True}, actor)
    attempt = claim(join_worker, run_id, end)
    assert attempt
    worker.complete(attempt["lease_token"], {"done": True}, actor)
    assert runtime.get_run(run_id)["status"] == "SUCCEEDED"
    assert any(item["status"] == "COMMITTED" for item in runtime.list_join_states(run_id))
    assert len(runtime.list_branches(run_id)) >= 2
    checks["branch_join"] = True

    # An unauthenticated event is retained; an authenticated matching event
    # resolves the durable wait and makes its Worker claimable.
    wait_start = "wait-start-" + suffix
    wait_node = "wait-node-" + suffix
    wait_end = "wait-end-" + suffix
    correlation = "corr-" + suffix
    version_id, plan_id = make_graph(
        [{"node_key": wait_start, "node_type": "START"},
         {"node_key": wait_node, "node_type": "EVENT"},
         {"node_key": wait_end, "node_type": "END"}],
        [{"edge_id": "wait-start-wait-" + suffix, "source_node_key": wait_start,
          "target_node_key": wait_node, "config": {"wait_kind": "EVENT",
          "event_type": "APPROVAL", "correlation_key": correlation}},
         {"edge_id": "wait-wait-end-" + suffix, "source_node_key": wait_node,
          "target_node_key": wait_end}],
    )
    run_id = new_run(version_id, plan_id, "wait")
    wait_worker = "wait-" + suffix
    advertise(wait_worker)
    attempt = claim(wait_worker, run_id, wait_start)
    assert attempt
    worker.complete(attempt["lease_token"], {"before_wait": True}, actor)
    assert runtime.get_run(run_id)["status"] == "WAITING"
    received = events.receive(
        "source-" + suffix, "APPROVAL", "1", "wait-event-" + suffix,
        {"correlation_key": correlation, "approved": True}, {"subject": actor},
    )
    assert received["status"] == "PROCESSED" and received["waits_resolved"] == 1
    attempt = claim(wait_worker, run_id, wait_node)
    assert attempt
    worker.complete(attempt["lease_token"], {"after_wait": True}, actor)
    attempt = claim(wait_worker, run_id, wait_end)
    assert attempt
    worker.complete(attempt["lease_token"], {"done": True}, actor)
    assert runtime.get_run(run_id)["status"] == "SUCCEEDED"
    checks["event_wait_and_idempotency"] = True

    # Node contracts must narrow the Worker input and validate the result
    # before the checkpoint/transition transaction is committed.
    boundary_start = "boundary-start-" + suffix
    boundary_work = "boundary-work-" + suffix
    boundary_end = "boundary-end-" + suffix
    boundary_version, boundary_plan = make_graph(
        [
            {"node_key": boundary_start, "node_type": "START"},
            {
                "node_key": boundary_work,
                "node_type": "AGENT",
                "input_schema": {
                    "type": "object", "required": ["public"],
                    "properties": {"public": {"type": "string"}},
                },
                "output_schema": {
                    "type": "object", "required": ["result", "artifact_refs"],
                    "properties": {"result": {"type": "string"}, "artifact_refs": {"type": "array"}},
                },
                "resource_scope": {"state_fields": ["public"]},
                "config": {"max_output_bytes": 4096},
            },
            {"node_key": boundary_end, "node_type": "END"},
        ],
        [
            {"edge_id": "boundary-edge-a-" + suffix, "source_node_key": boundary_start, "target_node_key": boundary_work},
            {"edge_id": "boundary-edge-b-" + suffix, "source_node_key": boundary_work, "target_node_key": boundary_end},
        ],
    )
    boundary_run = new_run(boundary_version, boundary_plan, "boundary")
    boundary_worker = "boundary-" + suffix
    advertise(boundary_worker)
    attempt = claim(boundary_worker, boundary_run, boundary_start)
    assert attempt and "input_state" in attempt
    worker.complete(attempt["lease_token"], {"public": "visible", "api_token": "must-redact"}, actor)
    attempt = claim(boundary_worker, boundary_run, boundary_work)
    assert attempt
    assert attempt["input_state"] == {"public": "visible"}
    try:
        worker.complete(attempt["lease_token"], {"result": "invalid"}, actor)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid node result was committed")
    worker.complete(
        attempt["lease_token"],
        {"result": "valid", "artifact_refs": [{"artifact_id": "ART_TEST", "content_hash": "hash"}]},
        actor,
    )
    attempt = claim(boundary_worker, boundary_run, boundary_end)
    assert attempt
    worker.complete(attempt["lease_token"], {"done": True}, actor)
    assert runtime.get_run(boundary_run)["status"] == "SUCCEEDED"
    checks["state_projection_and_result_contract"] = True

    # A non-idempotent effect with an uncertain outcome becomes a human review
    # case.  The automatic retry path must never resend it.
    effect_start = "effect-start-" + suffix
    effect_node = "effect-node-" + suffix
    effect_end = "effect-end-" + suffix
    effect_version, effect_plan = make_graph(
        [
            {"node_key": effect_start, "node_type": "START"},
            {
                "node_key": effect_node, "node_type": "HTTP_API",
                "side_effect_class": "NON_IDEMPOTENT",
                "config": {"retry_policy": {"max_attempts": 3, "confirmation_required": True}},
            },
            {"node_key": effect_end, "node_type": "END"},
        ],
        [
            {"edge_id": "effect-edge-a-" + suffix, "source_node_key": effect_start, "target_node_key": effect_node},
            {"edge_id": "effect-edge-b-" + suffix, "source_node_key": effect_node, "target_node_key": effect_end},
        ],
    )
    effect_run = new_run(effect_version, effect_plan, "uncertain-effect")
    effect_worker = "effect-" + suffix
    advertise(effect_worker)
    attempt = claim(effect_worker, effect_run, effect_start)
    assert attempt
    worker.complete(attempt["lease_token"], {"started": True}, actor)
    attempt = claim(effect_worker, effect_run, effect_node)
    assert attempt
    assert worker.fail(attempt["lease_token"], "UNCERTAIN_OUTCOME", "remote result was not confirmed", actor)
    assert runtime.get_run(effect_run)["status"] == "REVIEW_REQUIRED"
    assert claim(effect_worker, effect_run, effect_node) is None
    checks["non_idempotent_uncertain_outcome_review"] = True

    # Migration is permitted only after a pause/quiescence barrier.
    migration_graph = definitions.create_graph("v420-migration-" + suffix, actor)
    migration_start = "migration-start-" + suffix
    migration_end = "migration-end-" + suffix
    source_version = definitions.create_version(
        migration_graph,
        [{"node_key": migration_start, "node_type": "START"},
         {"node_key": migration_end, "node_type": "END"}],
        [{"edge_id": "migration-edge-a-" + suffix,
          "source_node_key": migration_start, "target_node_key": migration_end}],
        actor_id=actor, reason="migration source",
    )
    source_plan = compiler.compile_and_publish(source_version, actor, "publish source")
    source_plan_id = source_plan.get("plan_id") or definitions.get_version(source_version).get("plan_id")
    target_version = definitions.create_version(
        migration_graph,
        [{"node_key": migration_start, "node_type": "START"},
         {"node_key": "migration-mid-" + suffix, "node_type": "AGENT"},
         {"node_key": migration_end, "node_type": "END"}],
        [{"edge_id": "migration-edge-b-" + suffix, "source_node_key": migration_start,
          "target_node_key": "migration-mid-" + suffix},
         {"edge_id": "migration-edge-c-" + suffix, "source_node_key": "migration-mid-" + suffix,
          "target_node_key": migration_end}],
        parent_version_id=source_version, actor_id=actor, reason="migration target",
    )
    target_plan = compiler.compile_and_publish(target_version, actor, "publish target")
    target_plan_id = target_plan.get("plan_id") or definitions.get_version(target_version).get("plan_id")
    run_id = new_run(source_version, source_plan_id, "migration")
    assert runtime.pause_run(run_id, actor, "migration barrier")
    migration = runtime.migrate_run(
        run_id, target_version, actor, "quiescent migration", {"start": migration_start}
    )
    assert migration["status"] == "APPLIED"
    assert runtime.get_run(run_id)["graph_version_id"] == target_version
    checks["quiescent_version_migration"] = True

    outbox_id = events.enqueue(run_id, "TEST_OUTBOX", "outbox-" + suffix, {"safe": "payload"})
    assert outbox_id and events.mark_outbox(outbox_id, "DISPATCHING")
    assert events.mark_outbox(outbox_id, "SENT")
    assert events.mark_outbox(outbox_id, "SENT") is False
    checks["outbox_idempotency"] = True

    # v4.3.3 failure injection is test-process-only. A failure after the
    # Checkpoint write must roll back the entire completion transaction.
    failure_start = "failure-start-" + suffix
    failure_end = "failure-end-" + suffix
    failure_version, failure_plan = make_graph(
        [{"node_key": failure_start, "node_type": "START"},
         {"node_key": failure_end, "node_type": "END"}],
        [{"edge_id": "failure-edge-" + suffix, "source_node_key": failure_start, "target_node_key": failure_end}],
    )
    failure_run = new_run(failure_version, failure_plan, "atomic-failpoint")
    failure_worker = "failure-" + suffix
    advertise(failure_worker)
    failure_attempt = claim(failure_worker, failure_run, failure_start)
    assert failure_attempt
    old_test_mode = os.environ.get("CX_GRAPH_TEST_MODE")
    os.environ["CX_GRAPH_TEST_MODE"] = "1"
    try:
        with graph_assurance.failpoint_for_test("after_checkpoint"):
            try:
                worker.complete(failure_attempt["lease_token"], {"must": "rollback"}, actor)
            except graph_assurance.FailpointTriggered:
                pass
            else:
                raise AssertionError("completion failpoint did not trigger")
    finally:
        if old_test_mode is None:
            os.environ.pop("CX_GRAPH_TEST_MODE", None)
        else:
            os.environ["CX_GRAPH_TEST_MODE"] = old_test_mode
    assert runtime.get_run(failure_run)["current_checkpoint_id"] is None
    assert runtime.list_attempts(failure_run)[0]["status"] == "RUNNING"
    worker.complete(failure_attempt["lease_token"], {"committed": True}, actor)
    checks["failure_injection_atomic_completion"] = True

    recovery = graph_assurance.recover_runtime(actor, worker_id="replacement-" + suffix)
    assert recovery["evidence_id"]
    assert any(item["evidence_type"] == "AGENT_RUNTIME_RECOVERED" for item in graph_assurance.list_evidence(limit=20))
    assert graph_assurance.invariant_scan()["healthy"] is True
    checks["runtime_recovery_evidence_and_invariants"] = True

    # A signed portable definition imports as a trusted Draft and can only be
    # published after the normal compiler path. Private key material remains
    # inside this test process.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    exported = definitions.export_version(failure_version, include_status=True)
    signed = graph_supply_chain.sign_document(
        exported, private_key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption(),
        ), key_id="live-" + suffix,
    )
    import_graph = definitions.create_graph("v433-import-" + suffix, actor)
    imported = definitions.import_version(
        signed, actor, target_graph_id=import_graph,
        trusted_public_keys={"live-" + suffix: graph_supply_chain._b64(public_key)},
    )
    assert imported["supply_chain"]["verification"]["trusted"] is True
    assert compiler.compile_and_publish(imported["graph_version_id"], actor, "trusted import") ["published"] is True
    checks["signed_definition_supply_chain"] = True

    # Dynamic Graph creates a child Draft; a high-risk side-effect expansion
    # stays non-publishable until the existing governed approval reaches quorum.
    dynamic_graph = definitions.create_graph("v433-dynamic-" + suffix, actor)
    dynamic_start, dynamic_agent, dynamic_end = "dynamic-start-" + suffix, "dynamic-agent-" + suffix, "dynamic-end-" + suffix
    dynamic_source = definitions.create_version(
        dynamic_graph,
        [{"node_key": dynamic_start, "node_type": "START"}, {"node_key": dynamic_agent, "node_type": "AGENT"}, {"node_key": dynamic_end, "node_type": "END"}],
        [{"edge_id": "dynamic-a-" + suffix, "source_node_key": dynamic_start, "target_node_key": dynamic_agent},
         {"edge_id": "dynamic-b-" + suffix, "source_node_key": dynamic_agent, "target_node_key": dynamic_end}],
        actor_id=actor, reason="dynamic source",
    )
    assert compiler.compile_and_publish(dynamic_source, actor, "publish dynamic source")["published"] is True
    old_profile = os.environ.get("CX_RUNTIME_PROFILE")
    os.environ["CX_RUNTIME_PROFILE"] = "development"
    try:
        proposal = graph_dynamic.create_draft(
            dynamic_source,
            [{"op": "REPLACE_NODE", "node_key": dynamic_agent,
              "node": {"node_type": "AGENT", "side_effect_class": "NON_IDEMPOTENT", "resource_scope": {"classification": "RESTRICTED"}}}],
            actor, "live high-risk dynamic proposal", expected_version=dynamic_source,
        )
        assert proposal["status"] == "PENDING_APPROVAL"
        try:
            compiler.compile_and_publish(proposal["target_version_id"], actor, "attempt bypass")
        except ValueError:
            pass
        else:
            raise AssertionError("high-risk Dynamic Graph bypassed approval")

        source_plan_id = definitions.get_version(dynamic_source).get("plan_id")
        task = a2a_gateway.create_task(dynamic_source, source_plan_id, actor, input_state={"a2a": True})
        assert a2a_gateway.get_task(task["id"], actor)["run_id"] == task["run_id"]
        telemetry_outbox = events.enqueue(task["run_id"], "OTLP_TEST", "otlp-" + suffix, {"metadata": "only"})
        projection = graph_telemetry.project_trace(task["run_id"], {"event_type": "A2A_TASK", "output": "not-exported"})
        assert graph_telemetry.queue_delivery(telemetry_outbox, "local-test", projection)
    finally:
        if old_profile is None:
            os.environ.pop("CX_RUNTIME_PROFILE", None)
        else:
            os.environ["CX_RUNTIME_PROFILE"] = old_profile
    checks["dynamic_graph_a2a_and_telemetry_preview"] = True
    return {"database": database, "passed": True, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="v4.2 live Graph Runtime checks")
    parser.add_argument("--database", required=True, choices=("oracle", "pg", "yashandb"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--package-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        result = run_live_checks(args.package_root.resolve(), args.config.resolve(), args.database)
    except Exception as exc:  # pragma: no cover - database-dependent path
        result = {"database": args.database, "passed": False,
                  "error_type": type(exc).__name__, "error": str(exc)[:600]}
        traceback.print_exc(file=sys.stderr)
        print(json.dumps(result, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
