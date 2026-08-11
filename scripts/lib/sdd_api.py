"""Database service for v4.4 native Spec Driven Development.

OpenSpec is optionally imported through this service.  Once an approved
baseline exists, execution consumes only these database records; local
Markdown and the OpenSpec CLI are never execution state.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .connection import execute, execute_insert_returning_id, execute_query, execute_query_one, sanitize_row
from . import sdd_contracts


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _actor(actor: Optional[str]) -> str:
    if actor:
        return str(actor)
    try:
        from .connection import get_current_agent_id
        return str(get_current_agent_id() or "SYSTEM")
    except Exception:
        return "SYSTEM"


def _row(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    return sanitize_row(row) if row else None


def create_change(title: str, *, summary: str = "", scope: str = "SOFTWARE_DELIVERY",
                  security_domain_id: Optional[str] = None, actor: Optional[str] = None,
                  source_kind: str = "NATIVE") -> Dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        raise ValueError("title is required")
    change_id, revision_id = _id("SDD_CHANGE"), _id("SDD_REV")
    actor_id = _actor(actor)
    execute(
        "INSERT INTO CX_SDD_CHANGES (CHANGE_ID,TITLE,SUMMARY,PROFILE_KEY,SECURITY_DOMAIN_ID,STATUS,CURRENT_REVISION_ID,CREATED_BY,UPDATED_BY) "
        "VALUES (:change_id,:title,:summary,:profile_key,:domain_id,'DRAFT',:revision_id,:actor,:actor)",
        {"change_id": change_id, "title": title[:512], "summary": summary[:4000], "profile_key": scope[:64],
         "domain_id": security_domain_id, "revision_id": revision_id, "actor": actor_id},
    )
    digest = _digest({"title": title, "summary": summary, "source_kind": source_kind})
    execute(
        "INSERT INTO CX_SDD_REVISIONS (REVISION_ID,CHANGE_ID,REVISION_NO,REVISION_STATE,SOURCE_KIND,CONTENT_DIGEST,EXPECTED_VERSION,CREATED_BY,REASON) "
        "VALUES (:revision_id,:change_id,1,'WORKING_REVISION',:source_kind,:digest,1,:actor,'Initial native revision')",
        {"revision_id": revision_id, "change_id": change_id, "source_kind": source_kind[:32], "digest": digest, "actor": actor_id},
    )
    return get_change(change_id) or {"change_id": change_id, "revision_id": revision_id}


def list_changes(limit: int = 100) -> List[Dict[str, Any]]:
    rows = execute_query(
        "SELECT CHANGE_ID,TITLE,SUMMARY,PROFILE_KEY,SECURITY_DOMAIN_ID,STATUS,CURRENT_REVISION_ID,CREATED_BY,UPDATED_BY,CREATED_AT,UPDATED_AT "
        "FROM CX_SDD_CHANGES ORDER BY UPDATED_AT DESC OFFSET 0 ROWS FETCH NEXT :lim ROWS ONLY", {"lim": max(1, min(int(limit), 500))},
    )
    return [_row(item) or {} for item in rows]


def get_change(change_id: str) -> Optional[Dict[str, Any]]:
    change = _row(execute_query_one("SELECT CHANGE_ID,TITLE,SUMMARY,PROFILE_KEY,SECURITY_DOMAIN_ID,STATUS,CURRENT_REVISION_ID,CREATED_BY,UPDATED_BY,CREATED_AT,UPDATED_AT FROM CX_SDD_CHANGES WHERE CHANGE_ID=:change_id", {"change_id": change_id}))
    if not change:
        return None
    revision_id = change.get("current_revision_id")
    change["revision"] = get_revision(str(revision_id)) if revision_id else None
    change["tasks"] = list_tasks(str(revision_id)) if revision_id else []
    change["evidence"] = list_evidence(str(revision_id)) if revision_id else []
    return change


def get_revision(revision_id: str) -> Optional[Dict[str, Any]]:
    revision = _row(execute_query_one(
        "SELECT REVISION_ID,CHANGE_ID,REVISION_NO,REVISION_STATE,SOURCE_KIND,SOURCE_SNAPSHOT_ID,CONTENT_DIGEST,EXPECTED_VERSION,BASELINE_OF_REVISION_ID,APPROVED_BY,APPROVED_AT,CREATED_BY,CREATED_AT,REASON "
        "FROM CX_SDD_REVISIONS WHERE REVISION_ID=:revision_id", {"revision_id": revision_id}))
    if not revision:
        return None
    rows = execute_query("SELECT CLAUSE_ID,CLAUSE_KIND,CLAUSE_KEY,TITLE,BODY_TEXT,STRUCTURED_JSON,STATUS,ORDINAL,EXPECTED_VERSION,CREATED_AT,UPDATED_AT FROM CX_SDD_CLAUSES WHERE REVISION_ID=:revision_id ORDER BY ORDINAL,CLAUSE_ID", {"revision_id": revision_id})
    revision["clauses"] = [_row(item) or {} for item in rows]
    fragments = execute_query("SELECT FRAGMENT_ID,FRAGMENT_KIND,SOURCE_PATH,SOURCE_OFFSET,CONTENT_DIGEST,SUMMARY,STATUS,WAIVED_BY,WAIVER_REASON,WAIVER_EXPIRES_AT FROM CX_SDD_UNRESOLVED_FRAGMENTS WHERE REVISION_ID=:revision_id ORDER BY CREATED_AT", {"revision_id": revision_id})
    revision["unresolved_fragments"] = [_row(item) or {} for item in fragments]
    return revision


def create_clause(revision_id: str, kind: str, title: str, *, body_text: str = "", structured: Any = None,
                  ordinal: int = 0, actor: Optional[str] = None) -> Dict[str, Any]:
    revision = get_revision(revision_id)
    if not revision:
        raise ValueError("revision not found")
    decision = sdd_contracts.patch_decision(revision.get("revision_state"), revision.get("expected_version"), revision.get("expected_version"), actor_is_authorized=True)
    if not decision.allowed:
        raise PermissionError(decision.message)
    clause_id = _id("SDD_CLAUSE")
    payload = structured if structured is not None else {}
    execute(
        "INSERT INTO CX_SDD_CLAUSES (CLAUSE_ID,REVISION_ID,CLAUSE_KIND,CLAUSE_KEY,TITLE,BODY_TEXT,STRUCTURED_JSON,STATUS,ORDINAL,EXPECTED_VERSION,CREATED_BY,UPDATED_BY) "
        "VALUES (:clause_id,:revision_id,:kind,:clause_key,:title,:body,:structured,'ACTIVE',:ordinal,1,:actor,:actor)",
        {"clause_id": clause_id, "revision_id": revision_id, "kind": str(kind).upper()[:64], "clause_key": clause_id,
         "title": str(title)[:1000], "body": str(body_text or ""), "structured": _json(payload), "ordinal": int(ordinal or 0), "actor": _actor(actor)},
    )
    _touch_revision(revision_id, _actor(actor), "Clause created")
    return _row(execute_query_one("SELECT CLAUSE_ID,REVISION_ID,CLAUSE_KIND,CLAUSE_KEY,TITLE,BODY_TEXT,STRUCTURED_JSON,STATUS,ORDINAL,EXPECTED_VERSION FROM CX_SDD_CLAUSES WHERE CLAUSE_ID=:clause_id", {"clause_id": clause_id})) or {"clause_id": clause_id}


def patch_clause(clause_id: str, *, expected_version: int, title: Optional[str] = None, body_text: Optional[str] = None,
                 structured: Any = None, reason: str, actor: Optional[str] = None) -> Dict[str, Any]:
    row = _row(execute_query_one(
        "SELECT c.CLAUSE_ID,c.REVISION_ID,c.EXPECTED_VERSION,r.REVISION_STATE FROM CX_SDD_CLAUSES c JOIN CX_SDD_REVISIONS r ON r.REVISION_ID=c.REVISION_ID WHERE c.CLAUSE_ID=:clause_id", {"clause_id": clause_id}))
    if not row:
        raise ValueError("clause not found")
    decision = sdd_contracts.patch_decision(row.get("revision_state"), expected_version, row.get("expected_version"), actor_is_authorized=True)
    if not decision.allowed:
        raise ValueError(decision.code)
    fields, params = [], {"clause_id": clause_id, "expected": int(expected_version), "actor": _actor(actor)}
    if title is not None:
        fields.append("TITLE=:title"); params["title"] = str(title)[:1000]
    if body_text is not None:
        fields.append("BODY_TEXT=:body"); params["body"] = str(body_text)
    if structured is not None:
        fields.append("STRUCTURED_JSON=:structured"); params["structured"] = _json(structured)
    if not fields:
        raise ValueError("patch has no changes")
    fields.extend(["EXPECTED_VERSION=EXPECTED_VERSION+1", "UPDATED_BY=:actor", "UPDATED_AT=CURRENT_TIMESTAMP"])
    changed = execute("UPDATE CX_SDD_CLAUSES SET " + ",".join(fields) + " WHERE CLAUSE_ID=:clause_id AND EXPECTED_VERSION=:expected", params)
    if changed != 1:
        raise ValueError("SDD_VERSION_CONFLICT")
    _touch_revision(str(row["revision_id"]), _actor(actor), reason)
    return _row(execute_query_one("SELECT CLAUSE_ID,REVISION_ID,CLAUSE_KIND,TITLE,BODY_TEXT,STRUCTURED_JSON,EXPECTED_VERSION,UPDATED_AT FROM CX_SDD_CLAUSES WHERE CLAUSE_ID=:clause_id", {"clause_id": clause_id})) or {}


def _touch_revision(revision_id: str, actor: str, reason: str) -> None:
    revision = get_revision(revision_id)
    if not revision:
        return
    digest = _digest({"clauses": revision.get("clauses", []), "reason": reason})
    execute("UPDATE CX_SDD_REVISIONS SET CONTENT_DIGEST=:digest,EXPECTED_VERSION=EXPECTED_VERSION+1,REASON=:reason WHERE REVISION_ID=:revision_id", {"digest": digest, "reason": reason[:2000], "revision_id": revision_id})


def create_working_revision(change_id: str, *, reason: str, actor: Optional[str] = None) -> Dict[str, Any]:
    change = get_change(change_id)
    if not change or not change.get("revision"):
        raise ValueError("change not found")
    current = change["revision"]
    state = str(current.get("revision_state"))
    if state not in {"APPROVED_BASELINE", "AMENDMENT", "WORKING_REVISION"}:
        raise ValueError("SDD_REVISION_TRANSITION_DENIED")
    next_id, number, actor_id = _id("SDD_REV"), int(current.get("revision_no") or 0) + 1, _actor(actor)
    execute(
        "INSERT INTO CX_SDD_REVISIONS (REVISION_ID,CHANGE_ID,REVISION_NO,REVISION_STATE,SOURCE_KIND,SOURCE_SNAPSHOT_ID,CONTENT_DIGEST,EXPECTED_VERSION,BASELINE_OF_REVISION_ID,CREATED_BY,REASON) "
        "VALUES (:revision_id,:change_id,:revision_no,'WORKING_REVISION','NATIVE',:snapshot_id,:digest,1,:parent_id,:actor,:reason)",
        {"revision_id": next_id, "change_id": change_id, "revision_no": number, "snapshot_id": current.get("source_snapshot_id"),
         "digest": current.get("content_digest"), "parent_id": current.get("revision_id"), "actor": actor_id, "reason": reason[:2000]},
    )
    for clause in current.get("clauses", []):
        create_clause(next_id, str(clause.get("clause_kind")), str(clause.get("title")), body_text=str(clause.get("body_text") or ""), structured=_decode(clause.get("structured_json")), ordinal=int(clause.get("ordinal") or 0), actor=actor_id)
    execute("UPDATE CX_SDD_CHANGES SET CURRENT_REVISION_ID=:revision_id,STATUS='DRAFT',UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE CHANGE_ID=:change_id", {"revision_id": next_id, "actor": actor_id, "change_id": change_id})
    return get_revision(next_id) or {}


def approve_baseline(revision_id: str, *, reason: str, actor: Optional[str] = None, approvals_complete: bool = True,
                     reviews_complete: bool = True) -> Dict[str, Any]:
    revision = get_revision(revision_id)
    if not revision:
        raise ValueError("revision not found")
    fragments = revision.get("unresolved_fragments", [])
    acceptance = [item for item in revision.get("clauses", []) if str(item.get("clause_kind")).upper() == "ACCEPTANCE_CRITERION"]
    decision = sdd_contracts.baseline_decision(unresolved_fragments=fragments, required_reviews_complete=reviews_complete,
                                                required_approvals_complete=approvals_complete, acceptance_complete=bool(acceptance))
    if not decision.allowed:
        raise ValueError(decision.code)
    transition = sdd_contracts.revision_transition(revision.get("revision_state"), "APPROVED_BASELINE", reason=reason)
    if not transition.allowed:
        raise ValueError(transition.code)
    actor_id = _actor(actor)
    execute("UPDATE CX_SDD_REVISIONS SET REVISION_STATE='APPROVED_BASELINE',APPROVED_BY=:actor,APPROVED_AT=CURRENT_TIMESTAMP,REASON=:reason,EXPECTED_VERSION=EXPECTED_VERSION+1 WHERE REVISION_ID=:revision_id", {"actor": actor_id, "reason": reason[:2000], "revision_id": revision_id})
    execute("UPDATE CX_SDD_CHANGES SET STATUS='APPROVED',CURRENT_REVISION_ID=:revision_id,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP WHERE CHANGE_ID=:change_id", {"revision_id": revision_id, "actor": actor_id, "change_id": revision["change_id"]})
    return get_revision(revision_id) or {}


def create_task(revision_id: str, title: str, *, role_key: str, risk_level: str = "LOW", read_set: Any = None,
                write_set: Any = None, depends_on: Any = None, actor: Optional[str] = None) -> Dict[str, Any]:
    decision = sdd_contracts.role_decision(role_key, risk_level)
    if not decision.allowed:
        raise ValueError(decision.code)
    task_id = _id("SDD_TASK")
    execute(
        "INSERT INTO CX_SDD_TASKS (TASK_ID,REVISION_ID,TITLE,ROLE_KEY,RISK_LEVEL,READ_SET_JSON,WRITE_SET_JSON,DEPENDS_ON_JSON,STATUS,EXPECTED_VERSION,CREATED_BY,UPDATED_BY) "
        "VALUES (:task_id,:revision_id,:title,:role,:risk,:read_set,:write_set,:depends_on,'PENDING',1,:actor,:actor)",
        {"task_id": task_id, "revision_id": revision_id, "title": str(title)[:1000], "role": str(role_key).upper()[:64],
         "risk": str(risk_level).upper()[:16], "read_set": _json(read_set or []), "write_set": _json(write_set or []),
         "depends_on": _json(depends_on or []), "actor": _actor(actor)},
    )
    return _row(execute_query_one("SELECT TASK_ID,REVISION_ID,TITLE,ROLE_KEY,RISK_LEVEL,READ_SET_JSON,WRITE_SET_JSON,DEPENDS_ON_JSON,STATUS,EXPECTED_VERSION FROM CX_SDD_TASKS WHERE TASK_ID=:task_id", {"task_id": task_id})) or {}


def list_tasks(revision_id: str) -> List[Dict[str, Any]]:
    rows = execute_query("SELECT TASK_ID,REVISION_ID,TITLE,ROLE_KEY,RISK_LEVEL,READ_SET_JSON,WRITE_SET_JSON,DEPENDS_ON_JSON,STATUS,ASSIGNED_PRINCIPAL_ID,EXPECTED_VERSION,CREATED_AT,UPDATED_AT FROM CX_SDD_TASKS WHERE REVISION_ID=:revision_id ORDER BY CREATED_AT", {"revision_id": revision_id})
    return [_row(item) or {} for item in rows]


def record_evidence(revision_id: str, *, task_id: Optional[str] = None, criterion_clause_id: Optional[str] = None,
                    evidence_type: str, source_kind: str, reference_uri: str, artifact_digest: str,
                    detail: Any = None, actor: Optional[str] = None, independent: bool = False) -> Dict[str, Any]:
    if not artifact_digest or len(str(artifact_digest)) < 32:
        raise ValueError("artifact_digest is required")
    evidence_id = _id("SDD_EVIDENCE")
    execute(
        "INSERT INTO CX_SDD_EVIDENCE (EVIDENCE_ID,REVISION_ID,TASK_ID,CRITERION_CLAUSE_ID,EVIDENCE_TYPE,SOURCE_KIND,REFERENCE_URI,ARTIFACT_DIGEST,DETAIL_JSON,INDEPENDENT_FLAG,STATUS,CREATED_BY) "
        "VALUES (:evidence_id,:revision_id,:task_id,:criterion_id,:type,:source,:reference,:digest,:detail,:independent,'VALID',:actor)",
        {"evidence_id": evidence_id, "revision_id": revision_id, "task_id": task_id, "criterion_id": criterion_clause_id,
         "type": str(evidence_type).upper()[:64], "source": str(source_kind).upper()[:64], "reference": reference_uri[:2048],
         "digest": artifact_digest[:128], "detail": _json(detail or {}), "independent": "Y" if independent else "N", "actor": _actor(actor)},
    )
    return _row(execute_query_one("SELECT EVIDENCE_ID,REVISION_ID,TASK_ID,CRITERION_CLAUSE_ID,EVIDENCE_TYPE,SOURCE_KIND,REFERENCE_URI,ARTIFACT_DIGEST,INDEPENDENT_FLAG,STATUS,CREATED_AT FROM CX_SDD_EVIDENCE WHERE EVIDENCE_ID=:evidence_id", {"evidence_id": evidence_id})) or {}


def list_evidence(revision_id: str) -> List[Dict[str, Any]]:
    rows = execute_query("SELECT EVIDENCE_ID,REVISION_ID,TASK_ID,CRITERION_CLAUSE_ID,EVIDENCE_TYPE,SOURCE_KIND,REFERENCE_URI,ARTIFACT_DIGEST,INDEPENDENT_FLAG,STATUS,CREATED_AT FROM CX_SDD_EVIDENCE WHERE REVISION_ID=:revision_id ORDER BY CREATED_AT DESC", {"revision_id": revision_id})
    return [_row(item) or {} for item in rows]


def compile_execution_graph(revision_id: str, *, budget: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Compile typed tasks into a deterministic SDD graph contract.

    The returned graph can be handed to the existing Graph Runtime adapter.
    It is deliberately data-only: no worker is started and no source checkout
    happens while a browser request is being handled.
    """
    revision = get_revision(revision_id)
    if not revision or str(revision.get("revision_state")).upper() != "APPROVED_BASELINE":
        raise ValueError("SDD_APPROVED_BASELINE_REQUIRED")
    tasks = list_tasks(revision_id)
    nodes: List[Dict[str, Any]] = [{"node_key": "start", "node_type": "START", "read_set": [], "write_set": []}]
    edges: List[Dict[str, Any]] = []
    task_ids = {str(task.get("task_id")) for task in tasks}
    for task in tasks:
        key = "task_" + str(task["task_id"])
        dependencies = _decode(task.get("depends_on_json"))
        if not isinstance(dependencies, list):
            raise ValueError("SDD_TASK_DEPENDENCY_INVALID")
        nodes.append({
            "node_key": key, "node_type": "AGENT", "task_id": task["task_id"],
            "role_key": task["role_key"], "risk_level": task["risk_level"],
            "read_set": _decode(task.get("read_set_json")), "write_set": _decode(task.get("write_set_json")),
        })
        if not dependencies:
            edges.append({"source_node_key": "start", "target_node_key": key})
        for dependency in dependencies:
            if str(dependency) not in task_ids:
                raise ValueError("SDD_TASK_DEPENDENCY_UNKNOWN")
            edges.append({"source_node_key": "task_" + str(dependency), "target_node_key": key})
    nodes.append({"node_key": "end", "node_type": "END", "read_set": [], "write_set": []})
    depended = {str(dep) for task in tasks for dep in (_decode(task.get("depends_on_json")) if isinstance(_decode(task.get("depends_on_json")), list) else [])}
    for task in tasks:
        if str(task["task_id"]) not in depended:
            edges.append({"source_node_key": "task_" + str(task["task_id"]), "target_node_key": "end"})
    if not tasks:
        edges.append({"source_node_key": "start", "target_node_key": "end"})
    decision = sdd_contracts.graph_contract_decision(nodes, edges, budget=budget or {})
    if not decision.allowed:
        raise ValueError(decision.code + ":" + ",".join(decision.details.get("errors", [])))
    return {"revision_id": revision_id, "nodes": nodes, "edges": edges, "budget": dict(budget or {}), "digest": _digest({"nodes": nodes, "edges": edges, "budget": budget or {}})}


def create_run(revision_id: str, *, budget: Optional[Mapping[str, Any]] = None, actor: Optional[str] = None) -> Dict[str, Any]:
    compiled = compile_execution_graph(revision_id, budget=budget)
    run_id, actor_id = _id("SDD_RUN"), _actor(actor)
    execute(
        "INSERT INTO CX_SDD_RUNS (RUN_ID,REVISION_ID,STATUS,RISK_LEVEL,BUDGET_JSON,CONTEXT_DIGEST,CREATED_BY) "
        "VALUES (:run_id,:revision_id,'READY','LOW',:budget,:digest,:actor)",
        {"run_id": run_id, "revision_id": revision_id, "budget": _json(budget or {}), "digest": compiled["digest"], "actor": actor_id},
    )
    tasks_by_id = {str(task["task_id"]): task for task in list_tasks(revision_id)}
    for node in compiled["nodes"]:
        task = tasks_by_id.get(str(node.get("task_id")))
        execute(
            "INSERT INTO CX_SDD_RUN_NODES (RUN_NODE_ID,RUN_ID,TASK_ID,NODE_KEY,STATUS,READ_SET_JSON,WRITE_SET_JSON) "
            "VALUES (:run_node_id,:run_id,:task_id,:node_key,:status,:read_set,:write_set)",
            {"run_node_id": _id("SDD_NODE"), "run_id": run_id, "task_id": node.get("task_id"),
             "node_key": node["node_key"], "status": "READY" if node["node_key"] == "start" else "PENDING",
             "read_set": _json(node.get("read_set") or []), "write_set": _json(node.get("write_set") or [])},
        )
    return {"run_id": run_id, "revision_id": revision_id, "status": "READY", "graph": compiled}


def claim_resource(run_id: str, task_id: str, *, resource_kind: str, resource_ref: str,
                   owner_principal_id: str, lease_seconds: int = 300) -> Dict[str, Any]:
    """Claim one immutable execution resource; an active conflict fails closed."""
    existing = _row(execute_query_one(
        "SELECT LEASE_ID,OWNER_PRINCIPAL_ID,LEASE_EXPIRES_AT FROM CX_SDD_RESOURCE_LEASES "
        "WHERE RESOURCE_KIND=:kind AND RESOURCE_REF=:ref AND STATUS='ACTIVE'", {"kind": resource_kind[:64], "ref": resource_ref[:2048]}))
    if existing:
        raise ValueError("SDD_RESOURCE_CONFLICT")
    lease_id = _id("SDD_LEASE")
    expiry = datetime.now(timezone.utc) + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
    execute(
        "INSERT INTO CX_SDD_RESOURCE_LEASES (LEASE_ID,RUN_ID,TASK_ID,RESOURCE_KIND,RESOURCE_REF,OWNER_PRINCIPAL_ID,FENCING_TOKEN,STATUS,LEASE_EXPIRES_AT) "
        "VALUES (:lease_id,:run_id,:task_id,:kind,:ref,:owner,1,'ACTIVE',:expiry)",
        {"lease_id": lease_id, "run_id": run_id, "task_id": task_id, "kind": resource_kind[:64], "ref": resource_ref[:2048],
         "owner": owner_principal_id[:256], "expiry": expiry},
    )
    return {"lease_id": lease_id, "run_id": run_id, "task_id": task_id, "fencing_token": 1, "lease_expires_at": expiry.isoformat()}


def release_resource(lease_id: str, *, owner_principal_id: str, fencing_token: int) -> bool:
    affected = execute(
        "UPDATE CX_SDD_RESOURCE_LEASES SET STATUS='RELEASED',UPDATED_AT=CURRENT_TIMESTAMP "
        "WHERE LEASE_ID=:lease_id AND OWNER_PRINCIPAL_ID=:owner AND FENCING_TOKEN=:token AND STATUS='ACTIVE'",
        {"lease_id": lease_id, "owner": owner_principal_id, "token": int(fencing_token)},
    )
    return affected == 1


def record_artifact(*, run_id: Optional[str], task_id: Optional[str], artifact_kind: str,
                    reference_uri: str, content_digest: str, actor: Optional[str] = None) -> Dict[str, Any]:
    if len(str(content_digest or "")) < 32:
        raise ValueError("content_digest is required")
    artifact_id = _id("SDD_ARTIFACT")
    execute(
        "INSERT INTO CX_SDD_ARTIFACTS (ARTIFACT_ID,RUN_ID,TASK_ID,ARTIFACT_KIND,REFERENCE_URI,CONTENT_DIGEST,STATUS,CREATED_BY) "
        "VALUES (:artifact_id,:run_id,:task_id,:kind,:reference,:digest,'VALID',:actor)",
        {"artifact_id": artifact_id, "run_id": run_id, "task_id": task_id, "kind": artifact_kind[:64],
         "reference": reference_uri[:2048], "digest": content_digest[:128], "actor": _actor(actor)},
    )
    return {"artifact_id": artifact_id, "content_digest": content_digest, "status": "VALID"}


def invalidate_artifact(reference_uri: str, content_digest: str) -> int:
    """Digest mismatch invalidates artifact and all matching evidence records."""
    changed = execute(
        "UPDATE CX_SDD_ARTIFACTS SET STATUS='STALE' WHERE REFERENCE_URI=:reference AND CONTENT_DIGEST<>:digest AND STATUS='VALID'",
        {"reference": reference_uri[:2048], "digest": content_digest[:128]},
    )
    execute(
        "UPDATE CX_SDD_EVIDENCE SET STATUS='STALE' WHERE REFERENCE_URI=:reference AND ARTIFACT_DIGEST<>:digest AND STATUS='VALID'",
        {"reference": reference_uri[:2048], "digest": content_digest[:128]},
    )
    return changed


def create_source_snapshot(change_id: str, files: Mapping[str, str], *, actor: Optional[str] = None) -> Dict[str, Any]:
    if not files:
        raise ValueError("source files are required")
    normalized = {str(path): str(body) for path, body in sorted(files.items())}
    snapshot_id, actor_id = _id("SDD_SNAPSHOT"), _actor(actor)
    digest = _digest(normalized)
    execute("INSERT INTO CX_SDD_SOURCE_SNAPSHOTS (SNAPSHOT_ID,CHANGE_ID,SOURCE_FORMAT,CONTENT_JSON,CONTENT_DIGEST,CREATED_BY) VALUES (:snapshot_id,:change_id,'OPENSPEC',:content,:digest,:actor)", {"snapshot_id": snapshot_id, "change_id": change_id, "content": _json(normalized), "digest": digest, "actor": actor_id})
    return {"snapshot_id": snapshot_id, "change_id": change_id, "content_digest": digest}


def import_openspec(change_id: str, root: str | Path, *, actor: Optional[str] = None) -> Dict[str, Any]:
    root_path = Path(root).resolve()
    allowed = ("proposal.md", "design.md", "tasks.md")
    files: Dict[str, str] = {}
    for name in allowed:
        path = root_path / name
        if path.is_file():
            files[name] = path.read_text(encoding="utf-8")
    for path in sorted((root_path / "specs").glob("**/spec.md")) if (root_path / "specs").is_dir() else []:
        files[str(path.relative_to(root_path))] = path.read_text(encoding="utf-8")
    snapshot = create_source_snapshot(change_id, files, actor=actor)
    revision = create_working_revision(change_id, reason="OpenSpec import", actor=actor)
    execute("UPDATE CX_SDD_REVISIONS SET SOURCE_KIND='OPENSPEC',SOURCE_SNAPSHOT_ID=:snapshot_id WHERE REVISION_ID=:revision_id", {"snapshot_id": snapshot["snapshot_id"], "revision_id": revision["revision_id"]})
    clauses, fragments = _parse_openspec(files)
    for ordinal, clause in enumerate(clauses, 1):
        create_clause(revision["revision_id"], clause["kind"], clause["title"], body_text=clause["body"], structured=clause.get("structured"), ordinal=ordinal, actor=actor)
    for fragment in fragments:
        execute("INSERT INTO CX_SDD_UNRESOLVED_FRAGMENTS (FRAGMENT_ID,REVISION_ID,FRAGMENT_KIND,SOURCE_PATH,SOURCE_OFFSET,CONTENT_DIGEST,SUMMARY,STATUS) VALUES (:id,:revision_id,:kind,:path,:offset,:digest,:summary,'OPEN')", {"id": _id("SDD_FRAGMENT"), "revision_id": revision["revision_id"], "kind": fragment["kind"], "path": fragment["path"], "offset": fragment["offset"], "digest": _digest(fragment), "summary": fragment["summary"][:2000]})
    return {"snapshot": snapshot, "revision_id": revision["revision_id"], "clauses_created": len(clauses), "unresolved_fragments": len(fragments)}


def _parse_openspec(files: Mapping[str, str]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    clauses: List[Dict[str, Any]] = []
    fragments: List[Dict[str, Any]] = []
    requirement = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.M)
    scenario = re.compile(r"^#### Scenario:\s*(.+?)\s*$", re.M)
    task = re.compile(r"^- \[[ xX]\]\s*(.+?)\s*$", re.M)
    for path, text in files.items():
        matches = list(requirement.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end].strip()
            clauses.append({"kind": "REQUIREMENT", "title": match.group(1), "body": body, "structured": {"source_path": path, "offset": match.start()}})
            for sm in scenario.finditer(body):
                scenario_body = body[sm.end():].split("#### Scenario:", 1)[0].strip()
                clauses.append({"kind": "SCENARIO", "title": sm.group(1), "body": scenario_body, "structured": {"source_path": path, "offset": match.end() + sm.start()}})
                clauses.append({"kind": "ACCEPTANCE_CRITERION", "title": sm.group(1), "body": scenario_body, "structured": {"source_path": path, "offset": match.end() + sm.start(), "source": "scenario"}})
        for tm in task.finditer(text):
            clauses.append({"kind": "TASK", "title": tm.group(1), "body": tm.group(1), "structured": {"source_path": path, "offset": tm.start()}})
        if not matches and not list(task.finditer(text)) and text.strip():
            fragments.append({"kind": "EXPLANATORY", "path": path, "offset": 0, "summary": text[:500]})
    return clauses, fragments


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {"raw": value}
    return value or {}
