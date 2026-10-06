"""Authorized graph analysis over exact persisted facts and bounded drafts."""
import json
from datetime import datetime, timezone
from . import connection, effective_capabilities, graph_assurance, graph_compiler, identity_api, cursor_pagination
from . import graph_definition_api as definitions, graph_runtime as runtime, graph_state
from .agent_extension_contracts import bounded_json, canonical, digest, row, safe_key


def _run(tx, actor, run_id, capability="graph_inspection"):
    effective_capabilities.require(actor, graph=capability)
    record = row(tx.query_one("SELECT * FROM GRAPH_RUNS WHERE RUN_ID=:run FOR UPDATE", {"run": run_id}))
    if not record:
        raise ValueError("Graph Run not found")
    access = effective_capabilities.authorize(actor)
    if record.get("actor_id") != actor and "ALL" not in access.get("scopes", []):
        raise PermissionError("Graph Run is outside the current management scope")
    return record


def replay_facts(initial_state, events, checkpoints):
    """Deterministic state reconstruction, with no executor or transport access."""
    state, findings, previous_id, expected_seq = dict(initial_state), [], None, 1
    by_id = {item["checkpoint_id"]: item for item in checkpoints}
    for event in events:
        seq = int(event["seq_no"])
        if seq != expected_seq:
            findings.append({"code": "EVENT_SEQUENCE_GAP", "seq_no": seq})
        if event.get("prior_checkpoint_id") != previous_id:
            findings.append({"code": "PARENT_CHECKPOINT_MISMATCH", "seq_no": seq})
        delta = json.loads(event["delta_json"] or "{}")
        evidence = json.loads(event.get("reducer_json") or "{}")
        if not isinstance(delta, dict) or not isinstance(evidence, dict):
            raise ValueError("Invalid recorded state event")
        for key, value in delta.items():
            reducer = (evidence.get("reducers") or {}).get(key)
            if reducer:
                values = [value] if key not in state or state[key] is None else [state[key], value]
                state[key] = graph_state.reduce_values(reducer, values)
            else:
                state[key] = value
        actual_hash = runtime._hash(state)
        if actual_hash != event["state_hash"]:
            findings.append({"code": "EVENT_STATE_HASH_MISMATCH", "seq_no": seq})
        checkpoint = by_id.get(event.get("checkpoint_id"))
        if (not checkpoint or int(checkpoint["seq_no"]) != seq or
                checkpoint.get("parent_checkpoint_id") != previous_id or
                checkpoint["state_hash"] != actual_hash or
                runtime._hash(json.loads(checkpoint["state_json"])) != actual_hash):
            findings.append({"code": "CHECKPOINT_INTEGRITY_MISMATCH", "seq_no": seq})
        previous_id, expected_seq = event.get("checkpoint_id"), seq + 1
    if len(by_id) != len(events):
        findings.append({"code": "CHECKPOINT_EVENT_COUNT_MISMATCH"})
    return {"status": "VERIFIED" if not findings else "DISCREPANCIES", "state_hash": runtime._hash(state),
            "event_count": len(events), "checkpoint_count": len(checkpoints), "findings": findings,
            "execution_invoked": False}


def offline_replay(actor, run_id):
    def perform(tx):
        record = _run(tx, actor, run_id)
        events = [row(item) for item in tx.query("SELECT * FROM GRAPH_STATE_EVENTS WHERE RUN_ID=:run ORDER BY SEQ_NO" +
            identity_api._limit_clause("page_limit"), {"run": run_id, "page_limit": 2001})]
        checkpoints = [row(item) for item in tx.query("SELECT * FROM GRAPH_CHECKPOINTS WHERE RUN_ID=:run ORDER BY SEQ_NO" +
            identity_api._limit_clause("page_limit"), {"run": run_id, "page_limit": 2001})]
        if max(len(events), len(checkpoints)) > 2000:
            raise ValueError("Offline replay exceeds the bounded 2000-event inspection limit")
        report = replay_facts(json.loads(record.get("input_state_json") or "{}"), events, checkpoints)
        plan = row(tx.query_one("SELECT PLAN_JSON,PLAN_DIGEST,DEFINITION_DIGEST FROM GRAPH_COMPILE_PLANS WHERE PLAN_ID=:plan", {"plan": record["plan_id"]}))
        if (not plan or _plan_hash(json.loads(plan["plan_json"])) != plan["plan_digest"] or
                plan["plan_digest"] != record["plan_digest"] or plan["definition_digest"] != record["definition_digest"]):
            report["findings"].append({"code": "SOURCE_PLAN_DIGEST_MISMATCH"})
            report["status"] = "DISCREPANCIES"
        report["run_id"] = run_id
        report["evidence_id"] = graph_assurance.record_evidence_tx(tx, "OFFLINE_REPLAY", report["status"], run_id=run_id, actor_id=actor, detail=report)
        return report
    return connection.execute_transaction_callback(perform)


def migration_assessment(source, target, node_runs, mapping, budget, usage, leases):
    bounded_json(mapping)
    old = {item["node_key"]: item for item in source.get("nodes") or []}
    new = {item["node_key"]: item for item in target.get("nodes") or []}
    findings, compensation = [], []
    if not isinstance(mapping, dict) or set(mapping) - set(old) or any(value not in new for value in mapping.values()):
        raise ValueError("Node mapping must reference existing stable source and target keys")
    effective = {key: mapping.get(key, key) for key in old}
    if len(set(effective.values())) != len(effective):
        findings.append({"code": "NODE_MAPPING_COLLISION"})
    for item in node_runs:
        key = item["node_key"]
        mapped = effective.get(key)
        if item["status"] in {"PENDING", "READY", "RUNNING", "WAITING"} and mapped not in new:
            findings.append({"code": "PENDING_NODE_REMOVED", "node_key": key})
        if mapped in new and key in old:
            if str(old[key].get("side_effect_class") or "NONE") != str(new[mapped].get("side_effect_class") or "NONE"):
                findings.append({"code": "SIDE_EFFECT_CLASS_CHANGED", "node_key": key})
            if canonical(old[key].get("resource_scope") or {}) != canonical(new[mapped].get("resource_scope") or {}):
                findings.append({"code": "RESOURCE_SCOPE_CHANGED", "node_key": key})
        if item["status"] == "SUCCEEDED" and str(old.get(key, {}).get("side_effect_class") or "NONE") != "NONE":
            compensation.append(key)
    for key, consumed in usage.items():
        maximum = budget.get("max_" + key)
        if maximum is not None and float(consumed) > float(maximum):
            findings.append({"code": "TARGET_BUDGET_EXCEEDED", "budget_key": key})
    if leases:
        findings.append({"code": "ACTIVE_LEASES", "count": len(leases)})
    return {"status": "BLOCKED" if findings else "PREFLIGHT_PASSED", "findings": findings,
            "stable_mapping": effective, "compensation_review_nodes": sorted(set(compensation)),
            "live_migration_performed": False, "executor_approval": False}


def migration_preflight(actor, run_id, target_version_id, mapping):
    def perform(tx):
        record = _run(tx, actor, run_id)
        source = definitions.get_version(record["graph_version_id"])
        target = definitions.get_version(target_version_id)
        if not target or source["graph_id"] != target["graph_id"]:
            raise ValueError("Target version must belong to the same Graph")
        nodes = [row(item) for item in tx.query("SELECT NODE_KEY,STATUS FROM GRAPH_NODE_RUNS WHERE RUN_ID=:run", {"run": run_id})]
        # Graph leases are UTC-naive even when the database session clock is
        # local. Comparing them with CURRENT_TIMESTAMP can discard an active
        # lease by the session timezone offset.
        leases = tx.query("SELECT ATTEMPT_ID,FENCING_TOKEN FROM GRAPH_ATTEMPTS WHERE RUN_ID=:run AND STATUS IN ('CLAIMED','RUNNING','WAITING') AND LEASE_EXPIRES_AT>:lease_now", {"run": run_id, "lease_now": datetime.now(timezone.utc).replace(tzinfo=None)})
        report = migration_assessment(source, target, nodes, mapping, target.get("budget") or {}, json.loads(record.get("budget_usage_json") or "{}"), leases)
        if record["status"] not in {"PAUSED", "WAITING"}:
            report["findings"].append({"code": "RUN_NOT_AT_SAFE_POINT"})
        if target["status"] != "PUBLISHED":
            report["findings"].append({"code": "TARGET_VERSION_UNPUBLISHED"})
        if source.get("input_schema") != target.get("input_schema") or source.get("output_schema") != target.get("output_schema"):
            report["findings"].append({"code": "STATE_SCHEMA_CHANGED"})
        if report["findings"]:
            report["status"] = "BLOCKED"
        report.update(run_id=run_id, source_version_id=record["graph_version_id"], target_version_id=target_version_id,
                      source_definition_digest=record["definition_digest"], target_definition_digest=target.get("definition_digest"))
        report["evidence_id"] = graph_assurance.record_evidence_tx(tx, "MIGRATION_PREFLIGHT", report["status"], run_id=run_id, actor_id=actor, detail=report)
        return report
    return connection.execute_transaction_callback(perform)


def manifest_preview(actor, document, target_graph_id=None):
    effective_capabilities.require(actor, graph="graph_manifest_draft_import")
    bounded_json(document, maximum=1048576)
    if document.get("format") != definitions.GRAPH_EXPORT_FORMAT or str(document.get("format_version")) != definitions.GRAPH_EXPORT_VERSION:
        raise ValueError("Unsupported canonical Graph manifest")
    definition = document.get("definition") or {}
    version = definition.get("version") or {}
    nodes, edges = definitions._prepare_topology_inputs(version.get("nodes") or [], version.get("edges") or [])
    if len(nodes) > 256 or len(edges) > 1024:
        raise ValueError("Graph manifest exceeds topology limits")
    for item in nodes:
        config = item.get("config") or {}
        if any(key in config for key in ("code", "command", "python", "shell", "sql", "url")):
            raise ValueError("Executable code and arbitrary transports cannot be imported")
        executor = config.get("executor")
        if executor and not any(manifest["name"] == executor for manifest in graph_compiler.graph_executor.builtin_executor_manifests()):
            raise ValueError("Graph manifest names an unregistered executor")
    findings = definitions.graph_supply_chain.scan_document(document)
    if findings:
        raise ValueError("Graph manifest failed its supply-chain scan")
    compiled = graph_compiler.compile_definition({
        "schema_version": version.get("schema_version") or definitions.GRAPH_SCHEMA_VERSION,
        "input_schema": version.get("input_schema") or {}, "output_schema": version.get("output_schema") or {},
        "budget": version.get("budget") or {}, "nodes": nodes, "edges": edges,
    }, adapter={"dialect": "portable"}, registry=definitions.list_types(limit=500))
    if not compiled["valid"]:
        raise ValueError("Graph manifest failed compilation: " + ",".join(item["code"] for item in compiled["errors"])[:1000])
    previous = {}
    if target_graph_id:
        graph = definitions.get_graph(target_graph_id)
        if not graph or graph["status"] != "ACTIVE":
            raise ValueError("Target Graph is unavailable")
        access = effective_capabilities.authorize(actor)
        if graph.get("owner_ref") != actor and "ALL" not in access.get("scopes", []):
            raise PermissionError("Target Graph is outside the current management scope")
        versions = definitions.list_versions(target_graph_id)
        if versions:
            previous = definitions.get_version(versions[0]["graph_version_id"])
    old_keys = {item["node_key"] for item in previous.get("nodes") or []}
    new_keys = {item["node_key"] for item in nodes}
    return {"manifest_digest": digest(document), "node_count": len(nodes), "edge_count": len(edges),
            "added_nodes": sorted(new_keys - old_keys), "removed_nodes": sorted(old_keys - new_keys),
            "changed_nodes": sorted(key for key in new_keys & old_keys if _logical_node(next(item for item in nodes if item["node_key"] == key)) != _logical_node(next(item for item in previous["nodes"] if item["node_key"] == key))),
            "target_graph_id": target_graph_id, "status": "VALID_DRAFT_INPUT", "automatically_published": False}


def _logical_node(item):
    value = graph_compiler._normalize_node(item)
    return canonical({key: item for key, item in value.items() if key not in {"node_id", "graph_version_id", "created_at", "updated_at"}})


def _plan_hash(value):
    return runtime._hash({key: item for key, item in value.items() if key != "adapter"})


def import_draft(actor, document, preview_digest, target_graph_id=None, reason="Authorized draft import"):
    preview = manifest_preview(actor, document, target_graph_id)
    if preview["manifest_digest"] != preview_digest:
        raise ValueError("Manifest changed since its preview")
    return definitions.import_version(document, actor, target_graph_id=target_graph_id, reason=reason)


def checkpoint_fork(actor, run_id, checkpoint_id, idempotency_key, reason):
    safe_key(idempotency_key)
    if not 3 <= len(reason.strip()) <= 2000:
        raise ValueError("A fork reason is required")
    request_hash = digest({"run": run_id, "checkpoint": checkpoint_id, "actor": actor, "reason": reason})
    def perform(tx):
        parent = _run(tx, actor, run_id, "graph_checkpoint_fork")
        checkpoint = row(tx.query_one("SELECT * FROM GRAPH_CHECKPOINTS WHERE RUN_ID=:run AND CHECKPOINT_ID=:checkpoint", {"run": run_id, "checkpoint": checkpoint_id}))
        if not checkpoint or parent["current_checkpoint_id"] != checkpoint_id:
            raise ValueError("Fork requires the exact current checkpoint")
        snapshot = json.loads(checkpoint["state_json"])
        if runtime._hash(snapshot) != checkpoint["state_hash"]:
            raise ValueError("Checkpoint digest mismatch")
        prior = row(tx.query_one("SELECT r.RUN_ID,f.REQUEST_DIGEST FROM GRAPH_RUNS r LEFT JOIN CX_GRAPH_FORKS f ON f.CHILD_RUN_ID=r.RUN_ID WHERE r.GRAPH_VERSION_ID=:version AND r.IDEMPOTENCY_KEY=:key", {"version": parent["graph_version_id"], "key": "fork:" + actor + ":" + idempotency_key}))
        if prior:
            if prior["request_digest"] != request_hash:
                raise ValueError("Fork idempotency key has different content")
            return {"run_id": prior["run_id"], "replayed": True}
        plan_record = row(tx.query_one("SELECT PLAN_JSON,PLAN_DIGEST FROM GRAPH_COMPILE_PLANS WHERE PLAN_ID=:plan", {"plan": parent["plan_id"]}))
        if not plan_record or plan_record["plan_digest"] != parent["plan_digest"] or _plan_hash(json.loads(plan_record["plan_json"])) != parent["plan_digest"]:
            raise ValueError("Fork source plan digest mismatch")
        plan = json.loads(plan_record["plan_json"])
        # Restart is only automatic for plans containing no side effects.
        paused = any(str(item.get("side_effect_class") or "NONE") != "NONE" for item in plan.get("nodes") or list((plan.get("node_index") or {}).values()))
        child = runtime.create_run(parent["graph_version_id"], parent["plan_id"], actor, snapshot,
            json.loads(parent.get("budget_json") or "{}"), "fork:" + actor + ":" + idempotency_key,
            start_paused=paused, admission_evidence={"parent_run_id": run_id, "checkpoint_id": checkpoint_id}, transaction=tx)
        tx.execute("INSERT INTO CX_GRAPH_FORKS(CHILD_RUN_ID,PARENT_RUN_ID,CHECKPOINT_ID,SOURCE_PLAN_DIGEST,SNAPSHOT_HASH,ACTOR_ID,REQUEST_DIGEST,REASON) VALUES(:child,:parent,:checkpoint,:plan,:snapshot,:actor,:digest,:reason)",
            {"child": child, "parent": run_id, "checkpoint": checkpoint_id, "plan": parent["plan_digest"], "snapshot": checkpoint["state_hash"], "actor": actor, "digest": request_hash, "reason": reason})
        tx.execute("UPDATE GRAPH_RUNS SET BUDGET_USAGE_JSON=:usage WHERE RUN_ID=:child", {"usage": parent.get("budget_usage_json") or "{}", "child": child})
        if paused:
            tx.execute("UPDATE GRAPH_RUNS SET ERROR_CODE='FORK_REPLAY_APPROVAL_REQUIRED',ERROR_MESSAGE='A Human approval or compensation evidence is required before replay' WHERE RUN_ID=:child", {"child": child})
        runtime._write_checkpoint_tx(tx, child, {}, actor, snapshot_kind="FORK", reducer_evidence={"parent_run_id": run_id, "checkpoint_id": checkpoint_id})
        return {"run_id": child, "parent_run_id": run_id, "checkpoint_id": checkpoint_id, "status": "PAUSED" if paused else "RUNNING", "replayed": False}
    return connection.execute_transaction_callback(perform)


def slo_report(actor, *, page_size=20, cursor="", status=""):
    effective_capabilities.require(actor, graph="graph_slo_readonly")
    access = effective_capabilities.authorize(actor)
    if status and status not in {"PENDING", "RUNNING", "WAITING", "PAUSED", "SUCCEEDED", "FAILED", "CANCELLED", "MIGRATING", "REVIEW_REQUIRED"}:
        raise ValueError("Invalid Graph Run status filter")
    context = cursor_pagination.resolve(actor, "graph-slo", {"status": status}, "run_id:asc", page_size, cursor)
    context.update(principal_id=actor, resource_key="graph-slo", sort_key="run_id:asc")
    conditions, params = [], {"page_limit": page_size + 1}
    if "ALL" not in access.get("scopes", []):
        conditions.append("r.ACTOR_ID=:actor")
        params["actor"] = actor
    if status:
        conditions.append("r.STATUS=:state")
        params["state"] = status
    if context["position"].get("run_id"):
        conditions.append("r.RUN_ID>:after")
        params["after"] = context["position"]["run_id"]
    records = [row(item) for item in connection.execute_query(
        "SELECT r.RUN_ID,r.GRAPH_VERSION_ID,r.STATUS,r.CREATED_AT,r.COMPLETED_AT,"
        "(SELECT COUNT(*) FROM GRAPH_ATTEMPTS a WHERE a.RUN_ID=r.RUN_ID) AS ATTEMPT_COUNT,"
        "(SELECT COUNT(*) FROM GRAPH_ATTEMPTS a WHERE a.RUN_ID=r.RUN_ID AND a.STATUS='STALE') AS STALE_ATTEMPTS,"
        "(SELECT COUNT(*) FROM GRAPH_READY_NODES n WHERE n.RUN_ID=r.RUN_ID AND n.STATUS='READY') AS QUEUE_DEPTH "
        "FROM GRAPH_RUNS r" + (" WHERE " + " AND ".join(conditions) if conditions else "") +
        " ORDER BY r.RUN_ID" + identity_api._limit_clause("page_limit"), params)]
    for record in records:
        end, start = record.get("completed_at"), record.get("created_at")
        record["duration_ms"] = max(0, round((end - start).total_seconds() * 1000)) if end and start else None
    result = cursor_pagination.page(records, context, lambda item: {"run_id": item["run_id"]})
    result["observation_scope"] = "Authorized persisted run facts; pending durations have no completed measurement"
    return result
