"""Versioned Node Executor contracts for the v4.2 Graph Runtime.

The registry is declarative. A node may be executed by a local control
executor, delegated to the pull-based Worker protocol, or held by a durable
wait. Arbitrary Python, SQL, shell, and network callbacks are never accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional


EXECUTOR_CONTRACT_VERSION = "1.0"
EXECUTOR_KINDS = frozenset({"CONTROL", "WORKER", "WAIT"})
EXECUTOR_STATUSES = frozenset({"ACTIVE", "DISABLED", "DEPRECATED"})
EXECUTOR_NODE_TYPES = frozenset({
    "START", "END", "CONTROL", "SKILL", "TOOL", "AGENT", "MODEL",
    "DATABASE", "HTTP_API", "FUNCTION", "LOOP", "SUBGRAPH", "HUMAN",
    "TIMER", "EVENT",
})
SIDE_EFFECT_CLASSES = frozenset({"NONE", "DB_TRANSACTIONAL", "IDEMPOTENT_EXTERNAL", "NON_IDEMPOTENT"})
UNCERTAIN_OUTCOME_CODES = frozenset({
    "UNCERTAIN_OUTCOME", "OUTCOME_UNKNOWN", "NON_IDEMPOTENT_UNCERTAIN",
})
MANIFEST_FIELDS = frozenset({
    "kind", "name", "version", "executor_kind", "node_types", "side_effect_classes",
    "contract_version", "description", "constraints",
})


@dataclass(frozen=True)
class ExecutorManifest:
    """Portable metadata for one registered Node Executor."""

    name: str
    version: str
    executor_kind: str
    node_types: tuple[str, ...]
    side_effect_classes: tuple[str, ...] = ("NONE",)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": "EXECUTOR",
            "name": self.name,
            "version": self.version,
            "executor_kind": self.executor_kind,
            "node_types": list(self.node_types),
            "side_effect_classes": list(self.side_effect_classes),
            "contract_version": EXECUTOR_CONTRACT_VERSION,
        }


@dataclass(frozen=True)
class ExecutorResult:
    """Sanitized result of executor admission or local execution."""

    status: str
    output_state: Dict[str, Any]
    executor: str
    executor_version: str = EXECUTOR_CONTRACT_VERSION
    reason: Optional[str] = None


def _normalized_name(value: Any) -> str:
    name = str(value or "").strip().upper()
    if not name or len(name) > 128 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in name):
        raise ValueError("executor name must be a bounded identifier")
    return name


def _normalized_version(value: Any) -> str:
    version = str(value or "").strip()
    if not version or len(version) > 64 or any(
        ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        for ch in version
    ):
        raise ValueError("executor version must be a bounded identifier")
    return version


def _is_registry_missing_error(exc: Exception) -> bool:
    """Suppress only the expected pre-15-migration missing-table condition."""
    message = str(exc).lower()
    return any(fragment in message for fragment in (
        "graph_executor_registry", "undefined table", "table or view does not exist",
        "invalid object name", "does not exist",
    ))


def validate_manifest(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    if not isinstance(manifest, dict):
        return [{"code": "EXECUTOR_MANIFEST_OBJECT_REQUIRED"}]
    unsupported = sorted(set(manifest) - MANIFEST_FIELDS)
    if unsupported:
        errors.append({"code": "EXECUTOR_MANIFEST_FIELD_UNSUPPORTED", "fields": unsupported})
    if manifest.get("kind") is not None and str(manifest.get("kind")).upper() != "EXECUTOR":
        errors.append({"code": "EXECUTOR_KIND_MARKER_INVALID"})
    try:
        _normalized_name(manifest.get("name"))
    except ValueError:
        errors.append({"code": "EXECUTOR_NAME_INVALID"})
    try:
        _normalized_version(manifest.get("version"))
    except ValueError:
        errors.append({"code": "EXECUTOR_VERSION_INVALID"})
    if manifest.get("contract_version") is not None and str(manifest.get("contract_version")) != EXECUTOR_CONTRACT_VERSION:
        errors.append({"code": "EXECUTOR_CONTRACT_VERSION_UNSUPPORTED"})
    kind = str(manifest.get("executor_kind") or "").upper()
    if kind not in EXECUTOR_KINDS:
        errors.append({"code": "EXECUTOR_KIND_INVALID"})
    node_types = manifest.get("node_types")
    if not isinstance(node_types, list) or not node_types:
        errors.append({"code": "EXECUTOR_NODE_TYPES_REQUIRED"})
    elif any(
        not str(item).strip() or len(str(item)) > 128
        or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in str(item).upper())
        for item in node_types
    ):
        errors.append({"code": "EXECUTOR_NODE_TYPE_INVALID"})
    effects = manifest.get("side_effect_classes", ["NONE"])
    if not isinstance(effects, list) or not effects or not {str(item).upper() for item in effects} <= SIDE_EFFECT_CLASSES:
        errors.append({"code": "EXECUTOR_SIDE_EFFECT_CLASS_INVALID"})
    if kind == "WAIT" and any(str(item).upper() not in {"HUMAN", "TIMER", "EVENT"} for item in node_types or []):
        errors.append({"code": "EXECUTOR_WAIT_NODE_INVALID"})
    if kind == "CONTROL" and any(str(item).upper() not in {"START", "END", "CONTROL"} for item in node_types or []):
        errors.append({"code": "EXECUTOR_CONTROL_NODE_INVALID"})
    if manifest.get("description") is not None and len(str(manifest.get("description"))) > 2000:
        errors.append({"code": "EXECUTOR_DESCRIPTION_TOO_LONG"})
    if manifest.get("constraints") is not None and not isinstance(manifest.get("constraints"), dict):
        errors.append({"code": "EXECUTOR_CONSTRAINTS_OBJECT_REQUIRED"})
    return errors


def builtin_executor_manifests() -> List[Dict[str, Any]]:
    """Return the immutable executor surface shared by all editions."""
    return [
        ExecutorManifest("CONTROL", EXECUTOR_CONTRACT_VERSION, "CONTROL", ("START", "END", "CONTROL"), ("NONE",)).as_dict(),
        ExecutorManifest("WORKER", EXECUTOR_CONTRACT_VERSION, "WORKER", (
            "SKILL", "TOOL", "AGENT", "MODEL", "DATABASE", "HTTP_API", "FUNCTION", "LOOP", "SUBGRAPH",
        ), tuple(SIDE_EFFECT_CLASSES)).as_dict(),
        ExecutorManifest("HUMAN_WAIT", EXECUTOR_CONTRACT_VERSION, "WAIT", ("HUMAN",), ("NONE",)).as_dict(),
        ExecutorManifest("TIMER_WAIT", EXECUTOR_CONTRACT_VERSION, "WAIT", ("TIMER",), ("NONE",)).as_dict(),
        ExecutorManifest("EVENT_WAIT", EXECUTOR_CONTRACT_VERSION, "WAIT", ("EVENT",), ("NONE",)).as_dict(),
    ]


def manifests_from_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert database registry rows into portable manifests.

    Invalid or disabled rows are ignored here and rejected by the caller when
    a referenced Executor cannot be resolved. This keeps registry inspection
    safe even while an administrator is repairing a manifest.
    """
    result: List[Dict[str, Any]] = []
    for row in rows or []:
        row = {str(key).lower(): value for key, value in dict(row).items()}
        if str(row.get("status") or "ACTIVE").upper() != "ACTIVE":
            continue
        raw = row.get("manifest_json")
        try:
            manifest = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        manifest.setdefault("name", row.get("executor_name"))
        manifest.setdefault("version", row.get("executor_version"))
        manifest.setdefault("executor_kind", row.get("executor_kind"))
        if validate_manifest(manifest) == []:
            manifest["status"] = "ACTIVE"
            for key in (
                "executor_id", "actor_id", "status_reason", "status_changed_by",
                "status_changed_at", "created_at", "updated_at",
            ):
                if row.get(key) is not None:
                    manifest[key] = row[key]
            result.append(manifest)
    return result


def load_persisted_manifests(connection_module: Any) -> List[Dict[str, Any]]:
    """Load active custom manifests when the v4.2.1 table is installed."""
    try:
        rows = connection_module.execute_query(
            "SELECT EXECUTOR_NAME, EXECUTOR_VERSION, EXECUTOR_KIND, NODE_TYPES_JSON, "
            "SIDE_EFFECT_CLASSES_JSON, MANIFEST_JSON, STATUS FROM GRAPH_EXECUTOR_REGISTRY "
            "WHERE STATUS = 'ACTIVE' ORDER BY EXECUTOR_NAME, EXECUTOR_VERSION"
        )
    except Exception as exc:
        if _is_registry_missing_error(exc):
            return []
        raise
    return manifests_from_rows(rows)


def all_manifests(connection_module: Any = None) -> List[Dict[str, Any]]:
    """Return built-ins followed by active persisted extension manifests."""
    return builtin_executor_manifests() + (
        load_persisted_manifests(connection_module) if connection_module is not None else []
    )


def register_persisted_manifest(connection_module: Any, manifest: Dict[str, Any], actor_id: str) -> str:
    """Persist one validated custom manifest using the active adapter dialect."""
    manifest = dict(manifest or {})
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError({"code": "EXECUTOR_MANIFEST_INVALID", "errors": errors})
    if not str(actor_id or "").strip():
        raise ValueError("actor_id is required")
    import hashlib

    name = _normalized_name(manifest["name"])
    if name in {item["name"] for item in builtin_executor_manifests()}:
        raise ValueError({"code": "EXECUTOR_BUILTIN_NAME_RESERVED", "name": name})
    version = _normalized_version(manifest["version"])
    manifest["name"] = name
    manifest["version"] = version
    manifest["executor_kind"] = str(manifest["executor_kind"]).upper()
    manifest["node_types"] = [str(item).upper() for item in manifest["node_types"]]
    manifest["side_effect_classes"] = [
        str(item).upper() for item in manifest.get("side_effect_classes", ["NONE"])
    ]
    manifest["kind"] = "EXECUTOR"
    manifest["contract_version"] = EXECUTOR_CONTRACT_VERSION
    executor_id = "EXEC_" + hashlib.sha256(f"{name}:{version}".encode("utf-8")).hexdigest()[:112]
    payload = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    params = {
        "executor_id": executor_id, "executor_name": name, "executor_version": version,
        "executor_kind": str(manifest["executor_kind"]).upper(),
        "node_types_json": json.dumps(manifest["node_types"], ensure_ascii=True),
        "side_effect_classes_json": json.dumps(manifest.get("side_effect_classes", ["NONE"]), ensure_ascii=True),
        "manifest_json": payload, "actor_id": str(actor_id),
    }
    dialect = str(getattr(connection_module, "DATABASE_DIALECT", "")).lower()
    if dialect == "postgresql":
        connection_module.execute(
            "INSERT INTO GRAPH_EXECUTOR_REGISTRY "
            "(EXECUTOR_ID, EXECUTOR_NAME, EXECUTOR_VERSION, EXECUTOR_KIND, NODE_TYPES_JSON, "
            "SIDE_EFFECT_CLASSES_JSON, MANIFEST_JSON, STATUS, ACTOR_ID, STATUS_REASON, "
            "STATUS_CHANGED_BY, STATUS_CHANGED_AT, CREATED_AT, UPDATED_AT) "
            "VALUES (:executor_id, :executor_name, :executor_version, :executor_kind, :node_types_json, "
            ":side_effect_classes_json, :manifest_json, 'ACTIVE', :actor_id, 'Registered', :actor_id, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (EXECUTOR_NAME, EXECUTOR_VERSION) DO UPDATE SET EXECUTOR_KIND = EXCLUDED.EXECUTOR_KIND, "
            "NODE_TYPES_JSON = EXCLUDED.NODE_TYPES_JSON, SIDE_EFFECT_CLASSES_JSON = EXCLUDED.SIDE_EFFECT_CLASSES_JSON, "
            "MANIFEST_JSON = EXCLUDED.MANIFEST_JSON, STATUS = 'ACTIVE', ACTOR_ID = EXCLUDED.ACTOR_ID, "
            "STATUS_REASON = 'Registered', STATUS_CHANGED_BY = EXCLUDED.ACTOR_ID, "
            "STATUS_CHANGED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP",
            params,
        )
    else:
        connection_module.execute(
            "MERGE INTO GRAPH_EXECUTOR_REGISTRY dst "
            "USING (SELECT :executor_name AS EXECUTOR_NAME, :executor_version AS EXECUTOR_VERSION" + connection_module.merge_scalar_suffix() + ") src "
            "ON (dst.EXECUTOR_NAME = src.EXECUTOR_NAME AND dst.EXECUTOR_VERSION = src.EXECUTOR_VERSION) "
            "WHEN MATCHED THEN UPDATE SET EXECUTOR_KIND = :executor_kind, NODE_TYPES_JSON = :node_types_json, "
            "SIDE_EFFECT_CLASSES_JSON = :side_effect_classes_json, MANIFEST_JSON = :manifest_json, STATUS = 'ACTIVE', "
            "ACTOR_ID = :actor_id, STATUS_REASON = 'Registered', STATUS_CHANGED_BY = :actor_id, "
            "STATUS_CHANGED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHEN NOT MATCHED THEN INSERT (EXECUTOR_ID, EXECUTOR_NAME, EXECUTOR_VERSION, EXECUTOR_KIND, NODE_TYPES_JSON, "
            "SIDE_EFFECT_CLASSES_JSON, MANIFEST_JSON, STATUS, ACTOR_ID, STATUS_REASON, STATUS_CHANGED_BY, "
            "STATUS_CHANGED_AT, CREATED_AT, UPDATED_AT) VALUES "
            "(:executor_id, :executor_name, :executor_version, :executor_kind, :node_types_json, :side_effect_classes_json, "
            ":manifest_json, 'ACTIVE', :actor_id, 'Registered', :actor_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            params,
        )
    return executor_id


def list_persisted_manifests(connection_module: Any, include_inactive: bool = False) -> List[Dict[str, Any]]:
    """List registry rows with status metadata; built-ins are added by the caller."""
    where = "" if include_inactive else " WHERE STATUS = 'ACTIVE'"
    rows = connection_module.execute_query(
        "SELECT EXECUTOR_ID, EXECUTOR_NAME, EXECUTOR_VERSION, EXECUTOR_KIND, NODE_TYPES_JSON, "
        "SIDE_EFFECT_CLASSES_JSON, MANIFEST_JSON, STATUS, ACTOR_ID, STATUS_REASON, STATUS_CHANGED_BY, "
        "STATUS_CHANGED_AT, CREATED_AT, UPDATED_AT FROM GRAPH_EXECUTOR_REGISTRY" + where +
        " ORDER BY EXECUTOR_NAME, EXECUTOR_VERSION"
    )
    result = []
    for row in rows:
        normalized = {str(key).lower(): value for key, value in dict(row).items()}
        raw = normalized.get("manifest_json")
        try:
            manifest = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError):
            manifest = {}
        manifest.setdefault("name", normalized.get("executor_name"))
        manifest.setdefault("version", normalized.get("executor_version"))
        manifest.setdefault("executor_kind", normalized.get("executor_kind"))
        if validate_manifest(manifest) == []:
            manifest["status"] = str(normalized.get("status") or "ACTIVE").upper()
            for key in (
                "executor_id", "actor_id", "status_reason", "status_changed_by",
                "status_changed_at", "created_at", "updated_at",
            ):
                if normalized.get(key) is not None:
                    manifest[key] = normalized[key]
            result.append(manifest)
    return result


def set_persisted_status(connection_module: Any, executor_id: str, status: str,
                         actor_id: str, reason: str) -> bool:
    """Change a custom Executor status with an auditable reason."""
    status = str(status or "").upper()
    if status not in EXECUTOR_STATUSES:
        raise ValueError("invalid Executor status")
    if not str(executor_id or "").strip() or not str(actor_id or "").strip():
        raise ValueError("executor_id and actor_id are required")
    if not str(reason or "").strip():
        raise ValueError("Executor status change requires a reason")
    existing = connection_module.execute_query_one(
        "SELECT EXECUTOR_NAME FROM GRAPH_EXECUTOR_REGISTRY WHERE EXECUTOR_ID = :executor_id",
        {"executor_id": executor_id},
    )
    if not existing:
        return False
    name = _normalized_name(existing.get("executor_name"))
    if name in {item["name"] for item in builtin_executor_manifests()}:
        raise ValueError({"code": "EXECUTOR_BUILTIN_NAME_RESERVED", "name": name})
    return connection_module.execute(
        "UPDATE GRAPH_EXECUTOR_REGISTRY SET STATUS = :status, STATUS_REASON = :reason, "
        "STATUS_CHANGED_BY = :actor_id, STATUS_CHANGED_AT = CURRENT_TIMESTAMP, UPDATED_AT = CURRENT_TIMESTAMP "
        "WHERE EXECUTOR_ID = :executor_id",
        {"status": status, "reason": str(reason)[:2000], "actor_id": str(actor_id)[:256], "executor_id": executor_id},
    ) > 0


def _manifest_map(manifests: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[tuple[str, str], Dict[str, Any]]:
    result: Dict[tuple[str, str], Dict[str, Any]] = {}
    builtin_keys = {
        (_normalized_name(item["name"]), _normalized_version(item["version"]))
        for item in builtin_executor_manifests()
    }
    builtin_names = {key[0] for key in builtin_keys}
    # Built-ins are always present.  A caller-provided list is an extension
    # overlay, not a replacement registry; otherwise a custom registry read
    # could accidentally make START/END or WAIT nodes unresolvable.
    candidates = list(builtin_executor_manifests())
    candidates.extend(list(manifests or []))
    for manifest in candidates:
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError({"code": "EXECUTOR_MANIFEST_INVALID", "errors": errors})
        key = (_normalized_name(manifest["name"]), _normalized_version(manifest["version"]))
        if key in result:
            # The compiler passes the normalized registry, which includes the
            # immutable built-ins. Repeating an identical built-in is harmless;
            # a different manifest with the same key remains a hard failure.
            if result[key] == manifest and key in builtin_keys:
                continue
            raise ValueError({"code": "EXECUTOR_DUPLICATE_VERSION", "name": key[0], "version": key[1]})
        if key[0] in builtin_names and key not in builtin_keys:
            raise ValueError({"code": "EXECUTOR_BUILTIN_NAME_RESERVED", "name": key[0]})
        result[key] = dict(manifest)
    return result


def resolve_executor(node: Dict[str, Any], manifests: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Resolve a node to a registered executor without executing user code."""
    node = dict(node or {})
    node_type = str(node.get("node_type") or node.get("type") or "").upper()
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    requested = config.get("executor") or node.get("executor")
    if isinstance(requested, dict):
        name = requested.get("name") or requested.get("type")
        version = requested.get("version") or EXECUTOR_CONTRACT_VERSION
    else:
        name = requested
        version = EXECUTOR_CONTRACT_VERSION
    if not name:
        name = {
            "START": "CONTROL", "END": "CONTROL", "CONTROL": "CONTROL",
            "HUMAN": "HUMAN_WAIT", "TIMER": "TIMER_WAIT", "EVENT": "EVENT_WAIT",
        }.get(node_type, "WORKER")
    key = (_normalized_name(name), _normalized_version(version))
    manifest = _manifest_map(manifests).get(key)
    if not manifest:
        raise ValueError(f"executor is not registered: {key[0]}/{key[1]}")
    if node_type not in {str(item).upper() for item in manifest["node_types"]}:
        raise ValueError(f"executor {key[0]} cannot handle node type {node_type}")
    effect = str(node.get("side_effect_class") or "NONE").upper()
    if effect not in {str(item).upper() for item in manifest["side_effect_classes"]}:
        raise ValueError(f"executor {key[0]} cannot handle side effect class {effect}")
    return manifest


def admission(node: Dict[str, Any], *, manifests: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return a stable executor admission record for a compiled node."""
    manifest = resolve_executor(node, manifests)
    return {
        "name": manifest["name"],
        "version": manifest["version"],
        "kind": manifest["executor_kind"],
        "node_type": str(node.get("node_type") or node.get("type") or "").upper(),
        "side_effect_class": str(node.get("side_effect_class") or "NONE").upper(),
        "contract_version": EXECUTOR_CONTRACT_VERSION,
    }


def execute_control(node: Dict[str, Any], input_state: Optional[Dict[str, Any]] = None) -> ExecutorResult:
    """Execute only declarative control nodes locally."""
    manifest = resolve_executor(node)
    if manifest["executor_kind"] != "CONTROL":
        raise ValueError("execute_control only accepts control nodes")
    node_type = str(node.get("node_type") or "").upper()
    state = dict(input_state or {})
    state.setdefault("control_node", node_type)
    return ExecutorResult("COMPLETED", state, manifest["name"], manifest["version"])


def dispatch_record(node: Dict[str, Any], input_state: Optional[Dict[str, Any]] = None) -> ExecutorResult:
    """Create a Worker/Wait dispatch record without performing the effect."""
    manifest = resolve_executor(node)
    kind = manifest["executor_kind"]
    return ExecutorResult(
        "WAITING" if kind == "WAIT" else "DELEGATED",
        {"executor_admission": admission(node), "input_state_available": input_state is not None},
        manifest["name"], manifest["version"],
        "node requires durable wait handling" if kind == "WAIT" else "node delegated to Graph Worker protocol",
    )


def effect_idempotency_key(run_id: str, node_run_id: str,
                           side_effect_class: str) -> Optional[str]:
    """Return the stable remote-effect key for one logical Node Run.

    Attempt IDs intentionally change after lease expiry or retry.  Reusing an
    Attempt ID as a remote idempotency key would therefore allow a retry to
    submit the same external effect twice.  Only the explicitly idempotent
    external class receives a stable key; non-idempotent effects must remain a
    human-reviewed operation.
    """
    effect = str(side_effect_class or "NONE").upper()
    if effect not in SIDE_EFFECT_CLASSES:
        raise ValueError(f"unsupported side-effect class: {effect}")
    if effect != "IDEMPOTENT_EXTERNAL":
        return None
    if not str(run_id or "").strip() or not str(node_run_id or "").strip():
        raise ValueError("run_id and node_run_id are required for an external effect key")
    return "effect:" + hashlib.sha256(
        json.dumps(
            [str(run_id), str(node_run_id), effect],
            ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:112]


def side_effect_retry_decision(side_effect_class: str, error_code: str,
                               attempts_used: int, max_attempts: int) -> Dict[str, Any]:
    """Decide whether a failed Node may be retried automatically.

    The result is a pure contract consumed by the database runtime.  It keeps
    uncertain non-idempotent effects in review and prevents callers from
    turning a manual confirmation into an automatic resend.
    """
    effect = str(side_effect_class or "NONE").upper()
    if effect not in SIDE_EFFECT_CLASSES:
        raise ValueError(f"unsupported side-effect class: {effect}")
    try:
        used = max(1, int(attempts_used))
        maximum = max(1, int(max_attempts))
    except (TypeError, ValueError) as exc:
        raise ValueError("attempt counts must be positive integers") from exc
    uncertain = str(error_code or "").upper() in UNCERTAIN_OUTCOME_CODES
    if uncertain and effect == "NON_IDEMPOTENT":
        return {
            "retry": False, "status": "REVIEW_REQUIRED",
            "uncertain_outcome": True, "automatic_retry": False,
            "reason": "NON_IDEMPOTENT_UNCERTAIN",
        }
    if effect == "NON_IDEMPOTENT":
        return {
            "retry": False, "status": "FAILED",
            "uncertain_outcome": False, "automatic_retry": False,
            "reason": "NON_IDEMPOTENT_REQUIRES_MANUAL_RETRY",
        }
    if used < maximum:
        return {
            "retry": True, "status": "READY",
            "uncertain_outcome": uncertain, "automatic_retry": True,
            "reason": "RETRYABLE_FAILURE",
        }
    return {
        "retry": False, "status": "REVIEW_REQUIRED" if uncertain else "FAILED",
        "uncertain_outcome": uncertain, "automatic_retry": False,
        "reason": "RETRY_LIMIT_REACHED",
    }
