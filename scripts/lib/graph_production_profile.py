"""Database-authoritative, capability-level Graph production profile.

The matrix is intentionally separate from the legacy all-or-nothing runtime
profile.  A client cannot promote a preview feature by sending a request or
by merely finding its source module in the package.
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, Iterable, List, Optional

from . import connection, identity_api

PROFILE_KEY = "PRODUCTION"
STATES = frozenset({"ENABLED", "CONTROLLED", "DISABLED", "UNAVAILABLE"})
CAPABILITIES = {
    "graph_runtime_core": {"zh": "图运行核心", "en": "Graph Runtime core"},
    "graph_inspection": {"zh": "图检查", "en": "Graph inspection"},
    "graph_manifest_draft_import": {"zh": "图清单草稿导入", "en": "Graph Manifest Draft import"},
    "graph_slo_readonly": {"zh": "图 SLO 只读视图", "en": "Graph SLO read-only views"},
    "graph_checkpoint_fork": {"zh": "检查点分叉", "en": "Checkpoint fork"},
    "graph_replay": {"zh": "图回放", "en": "Graph replay"},
    "a2a_gateway": {"zh": "A2A 网关", "en": "A2A gateway"},
    "otel_export": {"zh": "OTLP 导出", "en": "OTLP export"},
    "graph_dynamic_migration": {"zh": "动态图迁移", "en": "Dynamic Graph migration"},
    "framework_adapter_execution": {"zh": "框架适配器执行", "en": "Framework adapter execution"},
}

# A capability cannot be promoted independently of the stable runtime pieces
# it relies on.  This is deliberately evaluated from the database matrix so a
# stale UI or client cannot promote a dependent preview feature by itself.
DEPENDENCIES = {
    "graph_inspection": {"graph_runtime_core"},
    "graph_manifest_draft_import": {"graph_runtime_core"},
    "graph_slo_readonly": {"graph_runtime_core"},
    "graph_checkpoint_fork": {"graph_runtime_core"},
    "graph_replay": {"graph_runtime_core", "graph_checkpoint_fork"},
    "a2a_gateway": {"graph_runtime_core"},
    "otel_export": {"graph_runtime_core"},
    "graph_dynamic_migration": {"graph_runtime_core"},
    "framework_adapter_execution": {"graph_runtime_core"},
}


class ProfileUnavailable(RuntimeError):
    pass


class ProfileConflict(ValueError):
    pass


def _row(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in dict(row or {}).items()}


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) for row in rows]


def _db_rows() -> List[Dict[str, Any]]:
    try:
        rows = connection.execute_query(
            "SELECT PROFILE_KEY,CAPABILITY_KEY,STATE,VERSION,MANDATORY,EVIDENCE_REF,REASON,EFFECTIVE_AT,UPDATED_BY,UPDATED_AT "
            "FROM CX_GRAPH_CAPABILITY_MATRIX WHERE PROFILE_KEY=:profile ORDER BY CAPABILITY_KEY",
            {"profile": PROFILE_KEY},
        )
    except Exception as exc:
        raise ProfileUnavailable("Graph capability matrix is unavailable") from exc
    result = _rows(rows)
    if {str(item.get("capability_key") or "") for item in result} != set(CAPABILITIES):
        raise ProfileUnavailable("Graph capability matrix is incomplete")
    return result


def list_capabilities() -> Dict[str, Any]:
    rows = _db_rows()
    return {
        "profile_key": PROFILE_KEY,
        "profile_version": "4.4.2",
        "items": [
            {**row, "display_name_zh": CAPABILITIES[key]["zh"], "display_name_en": CAPABILITIES[key]["en"]}
            for row in rows
            for key in [str(row.get("capability_key") or "")]
        ],
    }


def state(capability_key: str) -> str:
    key = str(capability_key or "")
    if key not in CAPABILITIES:
        raise ProfileConflict("Unknown Graph capability")
    item = next((row for row in _db_rows() if str(row.get("capability_key") or "") == key), None)
    value = str((item or {}).get("state") or "UNAVAILABLE").upper()
    return value if value in STATES else "UNAVAILABLE"


def require(capability_key: str, *, controlled: bool = False) -> str:
    value = state(capability_key)
    if value == "DISABLED":
        raise ProfileConflict("Graph capability is disabled: " + capability_key)
    if value == "UNAVAILABLE":
        raise ProfileUnavailable("Graph capability is unavailable: " + capability_key)
    if value == "CONTROLLED" and not controlled:
        raise ProfileConflict("Graph capability requires controlled authorization: " + capability_key)
    return value


def set_state(actor: str, capability_key: str, new_state: str, reason: str,
              expected_version: int, evidence_ref: str = "") -> Dict[str, Any]:
    key = str(capability_key or "")
    target = str(new_state or "").upper()
    if key not in CAPABILITIES or target not in STATES:
        raise ProfileConflict("Unknown Graph capability or state")
    if len(str(reason or "").strip()) < 3:
        raise ProfileConflict("A reason is required")
    if key == "graph_runtime_core" and target != "ENABLED":
        raise ProfileConflict("Graph Runtime core is a mandatory capability")
    if target in {"ENABLED", "CONTROLLED"} and len(str(evidence_ref or '').strip()) < 3:
        raise ProfileConflict("evidence reference is required for capability promotion")

    def work(tx: Any) -> Dict[str, Any]:
        current = _row(tx.query_one(
            "SELECT STATE,VERSION,MANDATORY FROM CX_GRAPH_CAPABILITY_MATRIX "
            "WHERE PROFILE_KEY=:profile AND CAPABILITY_KEY=:key FOR UPDATE",
            {"profile": PROFILE_KEY, "key": key},
        ))
        if not current:
            raise ProfileUnavailable("Graph capability matrix is incomplete")
        version = int(current.get("version") or 0)
        if version != int(expected_version):
            raise ProfileConflict("Graph capability changed concurrently")
        before = str(current.get("state") or "UNAVAILABLE").upper()
        if before == target:
            return {"capability_key": key, "state": before, "version": version, "idempotent": True}
        if target in {"ENABLED", "CONTROLLED"}:
            for dependency in DEPENDENCIES.get(key, set()):
                dependency_row = _row(tx.query_one(
                    "SELECT STATE FROM CX_GRAPH_CAPABILITY_MATRIX "
                    "WHERE PROFILE_KEY=:profile AND CAPABILITY_KEY=:key",
                    {"profile": PROFILE_KEY, "key": dependency},
                ))
                dependency_state = str(dependency_row.get("state") or "UNAVAILABLE").upper()
                if dependency_state != "ENABLED":
                    raise ProfileConflict(
                        f"Graph capability dependency is not enabled: {key} requires {dependency}"
                    )
        changed = tx.execute(
            "UPDATE CX_GRAPH_CAPABILITY_MATRIX SET STATE=:state,VERSION=VERSION+1,EVIDENCE_REF=:evidence,"
            "REASON=:reason,UPDATED_BY=:actor,UPDATED_AT=CURRENT_TIMESTAMP "
            "WHERE PROFILE_KEY=:profile AND CAPABILITY_KEY=:key AND VERSION=:version",
            {"state": target, "evidence": str(evidence_ref or "")[:256] or None,
             "reason": str(reason)[:2000], "actor": actor, "profile": PROFILE_KEY,
             "key": key, "version": version},
        )
        if changed != 1:
            raise ProfileConflict("Graph capability changed concurrently")
        history_id = "GPH_" + secrets.token_hex(20)
        tx.execute(
            "INSERT INTO CX_GRAPH_CAPABILITY_HISTORY(HISTORY_ID,PROFILE_KEY,CAPABILITY_KEY,FROM_STATE,TO_STATE,"
            "EXPECTED_VERSION,EVIDENCE_REF,REASON,CHANGED_BY) VALUES (:id,:profile,:key,:before,:after,:version,:evidence,:reason,:actor)",
            {"id": history_id, "profile": PROFILE_KEY, "key": key, "before": before, "after": target,
             "version": version, "evidence": str(evidence_ref or "")[:256] or None,
             "reason": str(reason)[:2000], "actor": actor},
        )
        identity_api._audit_tx(tx, actor, "GRAPH_CAPABILITY_STATE_CHANGE", "GRAPH_CAPABILITY", key, "ALLOW", str(reason)[:2000])
        return {"capability_key": key, "state": target, "version": version + 1, "idempotent": False}

    connection.execute_transaction_callback(work)
    item = next(item for item in list_capabilities()["items"] if item["capability_key"] == key)
    return item
