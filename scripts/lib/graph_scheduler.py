"""Portable scheduling controls for Graph Runtime.

The pure admission contract is shared by Community and Enterprise.  Enterprise
adds a database-backed scheduler lease so multiple Scheduler processes can
coordinate without creating a second execution kernel.
"""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def validate_policy(policy: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    policy = policy or {}
    errors: List[Dict[str, Any]] = []
    numeric = {
        "max_concurrency": 1, "max_queue_depth": 1, "rate_per_minute": 1,
        "retry_after_seconds": 0.1,
    }
    for key, minimum in numeric.items():
        if key not in policy:
            continue
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
            errors.append({"code": "SCHEDULER_POLICY_INVALID", "field": key})
    if "fairness_key" in policy and not isinstance(policy["fairness_key"], str):
        errors.append({"code": "SCHEDULER_FAIRNESS_KEY_INVALID"})
    for field in ("weight", "fairness_weight", "aging_seconds"):
        if field in policy:
            value = policy[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                errors.append({"code": "SCHEDULER_POLICY_INVALID", "field": field})
    quotas = policy.get("quotas")
    if quotas is not None:
        if not isinstance(quotas, dict):
            errors.append({"code": "SCHEDULER_QUOTAS_INVALID"})
        else:
            for scope_kind, quota in quotas.items():
                if not isinstance(scope_kind, str) or not isinstance(quota, dict):
                    errors.append({"code": "SCHEDULER_QUOTA_INVALID", "scope": str(scope_kind)})
                    continue
                errors.extend(
                    dict(item, scope=scope_kind)
                    for item in validate_policy(quota)
                    if item.get("code") != "SCHEDULER_QUOTAS_INVALID"
                )
    isolation = policy.get("resource_isolation")
    if isolation is not None and not isinstance(isolation, (str, list, tuple, set)):
        errors.append({"code": "SCHEDULER_RESOURCE_ISOLATION_INVALID"})
    return errors


def admission_decision(policy: Optional[Dict[str, Any]], *, queue_depth: int = 0,
                       active_count: int = 0, recent_count: int = 0,
                       scopes: Optional[Dict[str, Any]] = None,
                       scope_counts: Optional[Dict[str, Dict[str, int]]] = None) -> Dict[str, Any]:
    """Return a bounded decision without mutating durable scheduler state."""
    policy = dict(policy or {})
    errors = validate_policy(policy)
    if errors:
        return {"allowed": False, "reason": "INVALID_POLICY", "retry_after_seconds": 0, "errors": errors}
    max_queue = policy.get("max_queue_depth")
    if max_queue is not None and int(queue_depth) >= int(max_queue):
        return {"allowed": False, "reason": "BACKPRESSURE", "retry_after_seconds": float(policy.get("retry_after_seconds", 1))}
    max_concurrency = policy.get("max_concurrency")
    if max_concurrency is not None and int(active_count) >= int(max_concurrency):
        return {"allowed": False, "reason": "CONCURRENCY_LIMIT", "retry_after_seconds": float(policy.get("retry_after_seconds", 1))}
    rate = policy.get("rate_per_minute")
    if rate is not None and int(recent_count) >= int(rate):
        return {"allowed": False, "reason": "RATE_LIMIT", "retry_after_seconds": 60.0}
    scope_values = {str(key).lower(): str(value) for key, value in (scopes or {}).items()}
    for scope_kind, quota in (policy.get("quotas") or {}).items():
        kind = str(scope_kind).lower()
        scope_key = scope_values.get(kind)
        if not scope_key:
            continue
        counters = (scope_counts or {}).get(f"{kind}:{scope_key}", {})
        quota_decision = admission_decision(
            {key: value for key, value in quota.items() if key != "quotas"},
            queue_depth=int(counters.get("queue_depth", 0)),
            active_count=int(counters.get("active_count", 0)),
            recent_count=int(counters.get("recent_count", 0)),
        )
        if not quota_decision["allowed"]:
            return {
                **quota_decision,
                "reason": f"{kind.upper()}_QUOTA_{quota_decision['reason']}",
                "scope": {"kind": kind, "key": scope_key},
            }
    return {"allowed": True, "reason": "ADMITTED", "retry_after_seconds": 0}


def fair_order(items: Iterable[Dict[str, Any]], *, fairness_key: str = "actor_id") -> List[Dict[str, Any]]:
    """Stable weighted-fair ordering for a bounded ready batch.

    Items remain round-robin by default.  A bounded ``fairness_weight`` may
    grant a scope more turns, while ``aging_seconds`` raises old ready work
    without allowing an unbounded priority value to dominate the batch.
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = str(item.get(fairness_key) or item.get("run_id") or "")
        group = grouped.setdefault(key, {"items": [], "weight": 1})
        group["items"].append(dict(item))
        try:
            weight = int(item.get("fairness_weight") or item.get("weight") or 1)
        except (TypeError, ValueError):
            weight = 1
        group["weight"] = max(1, min(weight, 8))

    def effective_priority(item: Dict[str, Any]) -> tuple[int, str]:
        priority = int(item.get("priority") or 0)
        aging_seconds = float(item.get("aging_seconds") or 0)
        created = item.get("created_at") or item.get("available_at")
        if aging_seconds > 0 and created:
            try:
                if isinstance(created, datetime):
                    timestamp = created
                else:
                    timestamp = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())
                priority += min(100, int(age // aging_seconds))
            except (TypeError, ValueError):
                pass
        return (-priority, str(item.get("ready_id") or ""))

    for group in grouped.values():
        group["items"].sort(key=effective_priority)
    result: List[Dict[str, Any]] = []
    while grouped:
        for key in sorted(list(grouped)):
            group = grouped.get(key) or {}
            values = group.get("items") or []
            for _ in range(int(group.get("weight") or 1)):
                if not values:
                    break
                result.append(values.pop(0))
            if not values:
                grouped.pop(key, None)
    return result


def _quota_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = {str(key).lower(): value for key, value in dict(row).items()}
    raw = result.get("policy_json")
    if isinstance(raw, str):
        try:
            result["policy"] = json.loads(raw)
        except (TypeError, ValueError):
            result["policy"] = {}
    elif isinstance(raw, dict):
        result["policy"] = raw
    else:
        result["policy"] = {}
    return result


def upsert_quota(group_id: str, scope_kind: str, scope_key: str,
                 policy: Dict[str, Any], actor_id: str) -> str:
    """Persist one Enterprise scheduler quota policy.

    The policy is data, not executable SQL.  Community packages do not ship
    the Enterprise migration and therefore never expose this table.
    """
    if not group_id or not scope_kind or not scope_key or not actor_id:
        raise ValueError("group_id, scope_kind, scope_key, and actor_id are required")
    errors = validate_policy(policy)
    if errors:
        raise ValueError(json.dumps(errors, ensure_ascii=True))
    from . import connection
    quota_id = _id("QUOTA")
    params = {
        "quota_id": quota_id, "group_id": group_id, "scope_kind": str(scope_kind).upper(),
        "scope_key": scope_key, "policy_json": json.dumps(policy or {}, ensure_ascii=True, sort_keys=True),
        "actor_id": actor_id,
    }
    database = str(getattr(connection, "DATABASE_DIALECT", "")).lower()
    if database in {"pg", "postgres", "postgresql"}:
        sql = (
            "INSERT INTO GRAPH_SCHEDULER_QUOTAS (QUOTA_ID, GROUP_ID, SCOPE_KIND, SCOPE_KEY, POLICY_JSON, ACTOR_ID, STATUS, CREATED_AT, UPDATED_AT) "
            "VALUES (:quota_id, :group_id, :scope_kind, :scope_key, :policy_json, :actor_id, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (GROUP_ID, SCOPE_KIND, SCOPE_KEY) DO UPDATE SET POLICY_JSON = EXCLUDED.POLICY_JSON, ACTOR_ID = EXCLUDED.ACTOR_ID, STATUS = 'ACTIVE', UPDATED_AT = CURRENT_TIMESTAMP"
        )
    else:
        merge_scalar_suffix = getattr(connection, "merge_scalar_suffix", lambda: "")()
        sql = (
            "MERGE INTO GRAPH_SCHEDULER_QUOTAS dst USING (SELECT :quota_id QUOTA_ID, :group_id GROUP_ID, :scope_kind SCOPE_KIND, :scope_key SCOPE_KEY"
            f"{merge_scalar_suffix}) src "
            "ON (dst.GROUP_ID = src.GROUP_ID AND dst.SCOPE_KIND = src.SCOPE_KIND AND dst.SCOPE_KEY = src.SCOPE_KEY) "
            "WHEN MATCHED THEN UPDATE SET POLICY_JSON = :policy_json, ACTOR_ID = :actor_id, STATUS = 'ACTIVE', UPDATED_AT = CURRENT_TIMESTAMP "
            "WHEN NOT MATCHED THEN INSERT (QUOTA_ID, GROUP_ID, SCOPE_KIND, SCOPE_KEY, POLICY_JSON, ACTOR_ID, STATUS, CREATED_AT, UPDATED_AT) "
            "VALUES (:quota_id, :group_id, :scope_kind, :scope_key, :policy_json, :actor_id, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    connection.execute(sql, params)
    return quota_id


def load_quota_policy(group_id: str, scopes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load matching persisted Enterprise quotas into the pure policy shape."""
    if not group_id:
        return {}
    from . import connection
    rows = connection.execute_query(
        "SELECT GROUP_ID, SCOPE_KIND, SCOPE_KEY, POLICY_JSON FROM GRAPH_SCHEDULER_QUOTAS "
        "WHERE GROUP_ID = :group_id AND STATUS = 'ACTIVE'",
        {"group_id": group_id},
    )
    values = {str(key).lower(): str(value) for key, value in (scopes or {}).items()}
    quotas: Dict[str, Any] = {}
    for row in rows:
        item = _quota_row(row)
        kind = str(item.get("scope_kind") or "").lower()
        if kind and values.get(kind) == str(item.get("scope_key") or ""):
            quotas[kind] = item.get("policy") or {}
    return {"quotas": quotas} if quotas else {}


def _expiry(ttl_seconds: int) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(5, min(int(ttl_seconds), 300)))).replace(tzinfo=None)


def acquire_scheduler_lease(scheduler_id: str, group_id: str = "default", *,
                            ttl_seconds: int = 30, node_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Acquire or renew one Enterprise scheduler-group lease.

    The conditional update is the fencing barrier.  A scheduler that loses the
    lease receives ``None`` and must stop claiming Ready Nodes.
    """
    if not scheduler_id or not group_id:
        raise ValueError("scheduler_id and group_id are required")
    from . import connection
    expires = _expiry(ttl_seconds)

    def _acquire(tx):
        row = tx.query_one(
            "SELECT LEASE_ID, SCHEDULER_ID, FENCING_TOKEN, EXPIRES_AT, STATUS FROM GRAPH_SCHEDULER_LEASES "
            "WHERE GROUP_ID = :group_id", {"group_id": group_id},
        )
        if not row:
            lease_id = _id("SCHED")
            try:
                tx.execute(
                    "INSERT INTO GRAPH_SCHEDULER_LEASES (LEASE_ID, GROUP_ID, SCHEDULER_ID, NODE_ID, FENCING_TOKEN, STATUS, EXPIRES_AT, CREATED_AT, UPDATED_AT) "
                    "VALUES (:lease_id, :group_id, :scheduler_id, :node_id, 1, 'ACTIVE', :expires_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    {"lease_id": lease_id, "group_id": group_id, "scheduler_id": scheduler_id, "node_id": node_id, "expires_at": expires},
                )
                return {"lease_id": lease_id, "group_id": group_id, "scheduler_id": scheduler_id, "fencing_token": 1, "expires_at": expires}
            except Exception:
                row = tx.query_one("SELECT LEASE_ID, SCHEDULER_ID, FENCING_TOKEN, EXPIRES_AT, STATUS FROM GRAPH_SCHEDULER_LEASES WHERE GROUP_ID = :group_id", {"group_id": group_id})
                if not row:
                    raise
        owner = str(row.get("scheduler_id") or "")
        active = str(row.get("status") or "").upper() == "ACTIVE"
        expires_at = row.get("expires_at")
        if active and owner != scheduler_id and expires_at:
            parsed = expires_at if isinstance(expires_at, datetime) else None
            if parsed and parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed and parsed > datetime.now(timezone.utc):
                return None
        next_token = int(row.get("fencing_token") or 0) + (0 if owner == scheduler_id and active else 1)
        changed = tx.execute(
            "UPDATE GRAPH_SCHEDULER_LEASES SET SCHEDULER_ID = :scheduler_id, NODE_ID = :node_id, FENCING_TOKEN = :fencing_token, STATUS = 'ACTIVE', EXPIRES_AT = :expires_at, UPDATED_AT = CURRENT_TIMESTAMP "
            "WHERE LEASE_ID = :lease_id AND (SCHEDULER_ID = :scheduler_id OR STATUS <> 'ACTIVE' OR EXPIRES_AT <= CURRENT_TIMESTAMP)",
            {"scheduler_id": scheduler_id, "node_id": node_id, "fencing_token": next_token, "expires_at": expires, "lease_id": row["lease_id"]},
        )
        if changed != 1:
            return None
        return {"lease_id": row["lease_id"], "group_id": group_id, "scheduler_id": scheduler_id, "fencing_token": next_token, "expires_at": expires}

    return connection.execute_transaction_callback(_acquire)


def verify_scheduler_lease(lease_id: str, scheduler_id: str, fencing_token: int) -> bool:
    from . import connection
    row = connection.execute_query_one(
        "SELECT SCHEDULER_ID, FENCING_TOKEN, STATUS, EXPIRES_AT FROM GRAPH_SCHEDULER_LEASES WHERE LEASE_ID = :lease_id",
        {"lease_id": lease_id},
    )
    if not row or str(row.get("scheduler_id") or "") != str(scheduler_id):
        return False
    if int(row.get("fencing_token") or 0) != int(fencing_token) or str(row.get("status") or "").upper() != "ACTIVE":
        return False
    expires = row.get("expires_at")
    if isinstance(expires, datetime):
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
    return bool(expires)


def release_scheduler_lease(lease_id: str, scheduler_id: str, fencing_token: int) -> bool:
    from . import connection
    return connection.execute(
        "UPDATE GRAPH_SCHEDULER_LEASES SET STATUS = 'RELEASED', UPDATED_AT = CURRENT_TIMESTAMP WHERE LEASE_ID = :lease_id AND SCHEDULER_ID = :scheduler_id AND FENCING_TOKEN = :fencing_token AND STATUS = 'ACTIVE'",
        {"lease_id": lease_id, "scheduler_id": scheduler_id, "fencing_token": fencing_token},
    ) > 0
