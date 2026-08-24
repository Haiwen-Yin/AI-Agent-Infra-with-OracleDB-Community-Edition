"""v4.4.10 model quota, finance, external evidence, and wallboard governance."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import connection, identity_api


class ModelGovernanceError(RuntimeError):
    code = "MODEL_GOVERNANCE_ERROR"
    retryable = False


class QuotaExceeded(ModelGovernanceError):
    code = "MODEL_QUOTA_EXCEEDED"


class ReplayUnavailable(ModelGovernanceError):
    code = "MODEL_REPLAY_UNAVAILABLE"


class EvidenceRejected(ModelGovernanceError):
    code = "MODEL_EVIDENCE_REJECTED"


ALLOWED_SCOPE_TYPES = {"GLOBAL", "CREDENTIAL", "PRINCIPAL", "AGENT", "HUMAN", "ORGANIZATION", "SECURITY_DOMAIN", "PROFILE", "MODEL", "COST_CENTER"}
ALLOWED_WIDGETS = {
    "agent_overview", "runtime", "usage_trend", "model_usage", "coverage",
    "budget_risk", "compliance", "approvals", "graph_runs", "provider_health",
}
ALLOWED_DIMENSIONS = {"day", "provider", "model", "provenance", "status", "organization", "security_domain"}
DEFAULT_WIDGETS = ["agent_overview", "runtime", "usage_trend", "model_usage", "coverage", "budget_risk"]


def _row(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(key).lower(): item for key, item in dict(value or {}).items()}


def _rows(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(value) for value in values]


def _id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(12)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _decimal(value: Any, *, non_negative: bool = True) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ModelGovernanceError("amount must be a fixed-precision decimal") from exc
    if non_negative and result < 0:
        raise ModelGovernanceError("amount must be non-negative")
    return result


def _require(actor: str, action: str, fallback: str = "platform.manage") -> Dict[str, Any]:
    access = identity_api.effective_access(actor, action)
    if access.get("decision") != "ALLOW" and fallback and fallback != action:
        access = identity_api.effective_access(actor, fallback)
    if access.get("decision") != "ALLOW":
        raise PermissionError(f"{action} permission is required")
    return access


def _parse_time(value: str, *, required: bool = False) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ModelGovernanceError("timestamp is required")
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelGovernanceError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window(window_type: str, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if window_type == "DAILY":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def create_quota_policy(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require(actor, "model_gateway.manage")
    scope_type = str(body.get("scope_type") or "GLOBAL").upper()
    metric = str(body.get("metric") or "TOKEN").upper()
    enforcement = str(body.get("enforcement") or "HARD").upper()
    window_type = str(body.get("window_type") or "MONTHLY").upper()
    incomplete = str(body.get("incomplete_policy") or "CHARGE_RESERVED").upper()
    if scope_type not in ALLOWED_SCOPE_TYPES or metric not in {"TOKEN", "COST"}:
        raise ModelGovernanceError("quota scope or metric is unsupported")
    if enforcement not in {"HARD", "WARN"} or window_type not in {"DAILY", "MONTHLY"}:
        raise ModelGovernanceError("quota enforcement or window is unsupported")
    if incomplete not in {"CHARGE_RESERVED", "RELEASE"}:
        raise ModelGovernanceError("incomplete usage policy is unsupported")
    scope_id = str(body.get("scope_id") or "")[:128] or None
    if scope_type != "GLOBAL" and not scope_id:
        raise ModelGovernanceError("scoped quota requires scope_id")
    currency = str(body.get("currency") or "").upper()[:12] or None
    if metric == "COST" and not currency:
        raise ModelGovernanceError("monetary quota requires currency")
    policy_key = str(body.get("policy_key") or "").strip()[:128]
    reason = str(body.get("reason") or "").strip()[:500]
    if not policy_key or not reason:
        raise ModelGovernanceError("policy key and compliance reason are required")
    latest = _row(connection.execute_query_one(
        "SELECT MAX(VERSION) AS VERSION FROM CX_MODEL_QUOTA_POLICIES WHERE POLICY_KEY=:key", {"key": policy_key},
    ))
    version = int(latest.get("version") or 0) + 1
    policy_id = _id("MQP")
    params = {
        "id": policy_id, "key": policy_key, "version": version, "scope_type": scope_type,
        "scope_id": scope_id, "metric": metric, "limit_value": str(_decimal(body.get("limit_value"))),
        "currency": currency, "enforcement": enforcement, "window_type": window_type,
        "reservation_value": str(_decimal(body.get("reservation_value", 0))), "incomplete": incomplete,
        "effective_from": _parse_time(str(body.get("effective_from") or "")),
        "effective_to": _parse_time(str(body.get("effective_to") or "")), "actor": actor, "reason": reason,
    }
    if _decimal(params["reservation_value"]) <= 0:
        raise ModelGovernanceError("quota reservation amount must be greater than zero")
    effective_from_sql = ":effective_from" if params["effective_from"] is not None else "CURRENT_TIMESTAMP"
    if params["effective_from"] is None:
        params.pop("effective_from")
    connection.execute(
        "INSERT INTO CX_MODEL_QUOTA_POLICIES(POLICY_ID,POLICY_KEY,VERSION,SCOPE_TYPE,SCOPE_ID,METRIC,LIMIT_VALUE,CURRENCY,ENFORCEMENT,WINDOW_TYPE,RESERVATION_VALUE,INCOMPLETE_POLICY,EFFECTIVE_FROM,EFFECTIVE_TO,STATUS,CREATED_BY,REASON) "
        f"VALUES(:id,:key,:version,:scope_type,:scope_id,:metric,:limit_value,:currency,:enforcement,:window_type,:reservation_value,:incomplete,{effective_from_sql},:effective_to,'ACTIVE',:actor,:reason)", params,
    )
    return {**params, "policy_id": policy_id, "status": "ACTIVE"}


def list_quota_policies(actor: str, limit: int = 100) -> Dict[str, Any]:
    _require(actor, "model_gateway.manage")
    rows = _rows(connection.execute_query(
        "SELECT POLICY_ID,POLICY_KEY,VERSION,SCOPE_TYPE,SCOPE_ID,METRIC,LIMIT_VALUE,CURRENCY,ENFORCEMENT,WINDOW_TYPE,RESERVATION_VALUE,INCOMPLETE_POLICY,EFFECTIVE_FROM,EFFECTIVE_TO,STATUS,REASON,CREATED_AT FROM CX_MODEL_QUOTA_POLICIES ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY", {},
    ))
    return {"items": rows[:max(1, min(int(limit or 100), 200))], "count": len(rows)}


def _quota_scope_ids(actor: str, credential_id: str, agent_id: str, profile_id: str, model_id: str) -> Dict[str, set[str]]:
    values = {
        "GLOBAL": {""}, "CREDENTIAL": {credential_id} if credential_id else set(),
        "PRINCIPAL": {actor}, "HUMAN": {actor}, "AGENT": {agent_id} if agent_id else set(),
        "PROFILE": {profile_id}, "MODEL": {model_id}, "ORGANIZATION": set(),
        "SECURITY_DOMAIN": set(), "COST_CENTER": set(),
    }
    principals = {actor} | ({agent_id} if agent_id else set())
    for principal in principals:
        domains = connection.execute_query(
            "SELECT SECURITY_DOMAIN_ID FROM CX_DOMAIN_MEMBERS WHERE PRINCIPAL_ID=:principal AND STATUS='ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
            {"principal": principal},
        )
        values["SECURITY_DOMAIN"].update(str(_row(item).get("security_domain_id") or "") for item in domains)
        organizations = connection.execute_query(
            "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID=:principal AND STATUS='ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)",
            {"principal": principal},
        )
        values["ORGANIZATION"].update(str(_row(item).get("organization_id") or "") for item in organizations)
    return {key: {item for item in items if item or key == "GLOBAL"} for key, items in values.items()}


def reserve_quota(request_id: str, actor: str, credential_id: str, agent_id: str, profile_id: str, model_id: str) -> Dict[str, Any]:
    scope_ids = _quota_scope_ids(actor, credential_id, agent_id, profile_id, model_id)
    policies = _rows(connection.execute_query(
        "SELECT POLICY_ID,POLICY_KEY,VERSION,SCOPE_TYPE,SCOPE_ID,METRIC,LIMIT_VALUE,CURRENCY,ENFORCEMENT,WINDOW_TYPE,RESERVATION_VALUE,INCOMPLETE_POLICY "
        "FROM CX_MODEL_QUOTA_POLICIES WHERE STATUS='ACTIVE' AND EFFECTIVE_FROM<=CURRENT_TIMESTAMP AND (EFFECTIVE_TO IS NULL OR EFFECTIVE_TO>CURRENT_TIMESTAMP)", {},
    ))
    matched = [item for item in policies if str(item.get("scope_id") or "") in scope_ids.get(str(item.get("scope_type") or ""), set())]
    warnings: List[Dict[str, Any]] = []

    def apply(tx):
        reservations = []
        for policy in matched:
            locked = _row(tx.query_one("SELECT POLICY_ID,LIMIT_VALUE,RESERVATION_VALUE,ENFORCEMENT,WINDOW_TYPE FROM CX_MODEL_QUOTA_POLICIES WHERE POLICY_ID=:id AND STATUS='ACTIVE' FOR UPDATE", {"id": policy["policy_id"]}))
            if not locked:
                continue
            start, end = _window(str(locked["window_type"]))
            totals = _row(tx.query_one(
                "SELECT COALESCE(SUM(CASE WHEN STATUS IN ('SETTLED','SETTLED_INCOMPLETE') THEN SETTLED_VALUE ELSE 0 END),0) AS COMMITTED,COALESCE(SUM(CASE WHEN STATUS='RESERVED' THEN RESERVED_VALUE ELSE 0 END),0) AS RESERVED FROM CX_MODEL_QUOTA_RESERVATIONS WHERE POLICY_ID=:id AND WINDOW_START=:window_start",
                {"id": policy["policy_id"], "window_start": start},
            ))
            amount = _decimal(locked.get("reservation_value") or 0)
            projected = _decimal(totals.get("committed") or 0) + _decimal(totals.get("reserved") or 0) + amount
            limit_value = _decimal(locked.get("limit_value") or 0)
            warning = "quota threshold exceeded" if projected > limit_value else ""
            if warning and str(locked.get("enforcement")) == "HARD":
                raise QuotaExceeded(f"hard quota {policy['policy_key']} is exhausted")
            reservation_id = _id("MQR")
            tx.execute(
                "INSERT INTO CX_MODEL_QUOTA_RESERVATIONS(RESERVATION_ID,REQUEST_ID,POLICY_ID,WINDOW_START,WINDOW_END,RESERVED_VALUE,STATUS,WARNING,EXPIRES_AT) VALUES(:id,:request,:policy,:window_start,:window_end,:reserved_value,'RESERVED',:warning,:expires_at)",
                {"id": reservation_id, "request": request_id, "policy": policy["policy_id"], "window_start": start, "window_end": end, "reserved_value": str(amount), "warning": warning or None, "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5)},
            )
            reservations.append({"reservation_id": reservation_id, "policy_id": policy["policy_id"], "metric": policy["metric"], "currency": policy.get("currency"), "warning": warning})
        return reservations

    reservations = connection.execute_transaction_callback(apply)
    warnings.extend(item for item in reservations if item.get("warning"))
    return {"reservations": reservations, "warnings": warnings}


def settle_quota(request_id: str, total_tokens: Optional[int], cost: Any, currency: str, *, incomplete: bool = False) -> None:
    def apply(tx):
        rows = _rows(tx.query(
            "SELECT r.RESERVATION_ID,r.RESERVED_VALUE,p.METRIC,p.CURRENCY,p.INCOMPLETE_POLICY FROM CX_MODEL_QUOTA_RESERVATIONS r JOIN CX_MODEL_QUOTA_POLICIES p ON p.POLICY_ID=r.POLICY_ID WHERE r.REQUEST_ID=:request AND r.STATUS='RESERVED' FOR UPDATE",
            {"request": request_id},
        ))
        for item in rows:
            if incomplete and item.get("incomplete_policy") == "RELEASE":
                status, value = "RELEASED", None
            elif incomplete:
                status, value = "SETTLED_INCOMPLETE", item.get("reserved_value")
            elif item.get("metric") == "TOKEN":
                status, value = "SETTLED", str(_decimal(total_tokens or 0))
            elif str(item.get("currency") or "") == str(currency or "") and cost is not None:
                status, value = "SETTLED", str(_decimal(cost))
            else:
                status, value = "RELEASED", None
            tx.execute("UPDATE CX_MODEL_QUOTA_RESERVATIONS SET STATUS=:status,SETTLED_VALUE=:value,UPDATED_AT=CURRENT_TIMESTAMP WHERE RESERVATION_ID=:id", {"status": status, "value": value, "id": item["reservation_id"]})
    connection.execute_transaction_callback(apply)


def release_quota(request_id: str, status: str = "RELEASED") -> int:
    return int(connection.execute(
        "UPDATE CX_MODEL_QUOTA_RESERVATIONS SET STATUS=:status,UPDATED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:request AND STATUS='RESERVED'",
        {"status": status[:24], "request": request_id},
    ) or 0)


def expire_quota_reservations() -> int:
    return int(connection.execute(
        "UPDATE CX_MODEL_QUOTA_RESERVATIONS SET STATUS='EXPIRED',UPDATED_AT=CURRENT_TIMESTAMP WHERE STATUS='RESERVED' AND EXPIRES_AT<=CURRENT_TIMESTAMP", {},
    ) or 0)


def quota_status(actor: str, limit: int = 100) -> Dict[str, Any]:
    _require(actor, "model_gateway.manage")
    rows = _rows(connection.execute_query(
        "SELECT p.POLICY_ID,p.POLICY_KEY,p.VERSION,p.SCOPE_TYPE,p.SCOPE_ID,p.METRIC,p.LIMIT_VALUE,p.CURRENCY,p.ENFORCEMENT,p.WINDOW_TYPE,p.STATUS,"
        "COALESCE(SUM(CASE WHEN r.STATUS IN ('SETTLED','SETTLED_INCOMPLETE') THEN r.SETTLED_VALUE ELSE 0 END),0) AS COMMITTED,"
        "COALESCE(SUM(CASE WHEN r.STATUS='RESERVED' THEN r.RESERVED_VALUE ELSE 0 END),0) AS RESERVED,MAX(r.UPDATED_AT) AS WATERMARK "
        "FROM CX_MODEL_QUOTA_POLICIES p LEFT JOIN CX_MODEL_QUOTA_RESERVATIONS r ON r.POLICY_ID=p.POLICY_ID "
        "AND r.WINDOW_START<=CURRENT_TIMESTAMP AND r.WINDOW_END>CURRENT_TIMESTAMP "
        "GROUP BY p.POLICY_ID,p.POLICY_KEY,p.VERSION,p.SCOPE_TYPE,p.SCOPE_ID,p.METRIC,p.LIMIT_VALUE,p.CURRENCY,p.ENFORCEMENT,p.WINDOW_TYPE,p.STATUS "
        "ORDER BY p.POLICY_KEY,p.VERSION DESC FETCH FIRST 200 ROWS ONLY", {},
    ))
    for item in rows:
        item["remaining"] = str(max(Decimal("0"), _decimal(item.get("limit_value") or 0) - _decimal(item.get("committed") or 0) - _decimal(item.get("reserved") or 0)))
    items = rows[:max(1, min(int(limit or 100), 200))]
    return {"items": items, "count": len(items), "generated_at": datetime.now(timezone.utc).isoformat()}


def _replay_snapshot_params(request_id: str, response: Dict[str, Any], ttl_seconds: int = 86400) -> Dict[str, Any]:
    from .connection_crypto import encrypt_section
    raw = _json(response).encode("utf-8")
    if len(raw) > 1024 * 1024:
        raise ReplayUnavailable("response exceeds replay snapshot limit")
    cipher = encrypt_section({"response": response})
    return {"request": request_id, "cipher": cipher, "digest": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw), "expires_at": datetime.now(timezone.utc) + timedelta(seconds=max(60, min(int(ttl_seconds), 604800)))}


def save_replay_snapshot(request_id: str, response: Dict[str, Any], ttl_seconds: int = 86400) -> None:
    connection.execute(
        "INSERT INTO CX_MODEL_REPLAY_SNAPSHOTS(REQUEST_ID,RESPONSE_CIPHER,RESPONSE_DIGEST,KEY_REFERENCE,BYTE_COUNT,EXPIRES_AT) VALUES(:request,:cipher,:digest,'master:aigcm:v1',:byte_count,:expires_at)",
        _replay_snapshot_params(request_id, response, ttl_seconds),
    )


def finalize_replayable_success(request_id: str, response: Dict[str, Any], ttl_seconds: int = 86400) -> None:
    """Commit the replay snapshot and terminal request state atomically."""
    params = _replay_snapshot_params(request_id, response, ttl_seconds)
    def apply(tx):
        tx.execute(
            "INSERT INTO CX_MODEL_REPLAY_SNAPSHOTS(REQUEST_ID,RESPONSE_CIPHER,RESPONSE_DIGEST,KEY_REFERENCE,BYTE_COUNT,EXPIRES_AT) VALUES(:request,:cipher,:digest,'master:aigcm:v1',:byte_count,:expires_at)",
            params,
        )
        tx.execute(
            "UPDATE CX_MODEL_REQUESTS SET STATUS='SUCCEEDED',COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:request AND STATUS<>'SUCCEEDED'",
            {"request": request_id},
        )
    connection.execute_transaction_callback(apply)


def replay_snapshot(request_id: str) -> Dict[str, Any]:
    from .connection_crypto import decrypt_section
    row = _row(connection.execute_query_one(
        "SELECT RESPONSE_CIPHER,RESPONSE_DIGEST,EXPIRES_AT FROM CX_MODEL_REPLAY_SNAPSHOTS WHERE REQUEST_ID=:request AND EXPIRES_AT>CURRENT_TIMESTAMP", {"request": request_id},
    ))
    if not row:
        raise ReplayUnavailable("idempotent response replay is unavailable")
    try:
        response = decrypt_section(str(row["response_cipher"]))["response"]
    except Exception as exc:
        raise ReplayUnavailable("idempotent response replay is unavailable") from exc
    if hashlib.sha256(_json(response).encode("utf-8")).hexdigest() != str(row["response_digest"]):
        raise ReplayUnavailable("idempotent response replay is unavailable")
    result = dict(response)
    result["replayed"] = True
    return result


def import_invoice(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    provider = str(body.get("provider_key") or "")[:128]
    external_id = str(body.get("external_invoice_id") or "")[:160]
    currency = str(body.get("currency") or "").upper()[:12]
    lines = body.get("lines") or []
    reason = str(body.get("reason") or "")[:500]
    if not provider or not external_id or not currency or not reason or not isinstance(lines, list) or len(lines) > 1000:
        raise ModelGovernanceError("invoice identity, currency, reason, and bounded lines are required")
    canonical = {key: body.get(key) for key in ("provider_key", "external_invoice_id", "currency", "period_start", "period_end", "total_amount", "lines")}
    source_digest = _digest(canonical)
    existing = _row(connection.execute_query_one("SELECT BATCH_ID,SOURCE_DIGEST,STATUS FROM CX_PROVIDER_INVOICE_BATCHES WHERE PROVIDER_KEY=:provider AND EXTERNAL_INVOICE_ID=:external", {"provider": provider, "external": external_id}))
    if existing:
        if existing.get("source_digest") != source_digest:
            raise ModelGovernanceError("invoice identifier conflicts with another source digest")
        return {"batch_id": existing["batch_id"], "status": existing["status"], "idempotent": True}
    batch_id = _id("INV")
    total = _decimal(body.get("total_amount"))

    def apply(tx):
        tx.execute("INSERT INTO CX_PROVIDER_INVOICE_BATCHES(BATCH_ID,PROVIDER_KEY,EXTERNAL_INVOICE_ID,SOURCE_DIGEST,CURRENCY,PERIOD_START,PERIOD_END,TOTAL_AMOUNT,STATUS,IMPORTED_BY,REASON) VALUES(:id,:provider,:external,:digest,:currency,:period_start,:period_end,:total,'IMPORTED',:actor,:reason)", {"id": batch_id, "provider": provider, "external": external_id, "digest": source_digest, "currency": currency, "period_start": _parse_time(str(body.get("period_start") or ""), required=True), "period_end": _parse_time(str(body.get("period_end") or ""), required=True), "total": str(total), "actor": actor, "reason": reason})
        line_total = Decimal("0")
        for index, line in enumerate(lines):
            amount = _decimal(line.get("amount")); line_total += amount
            line_id = _id("INL"); external_line = str(line.get("external_line_id") or index)[:160]
            tx.execute("INSERT INTO CX_PROVIDER_INVOICE_LINES(LINE_ID,BATCH_ID,EXTERNAL_LINE_ID,MODEL_ID,QUANTITY,AMOUNT,CURRENCY,LINE_DIGEST) VALUES(:id,:batch,:external,:model,:quantity,:line_amount,:currency,:digest)", {"id": line_id, "batch": batch_id, "external": external_line, "model": str(line.get("model_id") or "")[:256] or None, "quantity": str(_decimal(line.get("quantity", 0))), "line_amount": str(amount), "currency": currency, "digest": _digest(line)})
        if line_total != total:
            raise ModelGovernanceError("invoice lines must equal the declared total")
    connection.execute_transaction_callback(apply)
    return {"batch_id": batch_id, "status": "IMPORTED", "source_digest": source_digest, "line_count": len(lines), "idempotent": False}


def list_invoices(actor: str, limit: int = 100) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    rows = _rows(connection.execute_query("SELECT BATCH_ID,PROVIDER_KEY,EXTERNAL_INVOICE_ID,CURRENCY,PERIOD_START,PERIOD_END,TOTAL_AMOUNT,STATUS,CREATED_AT FROM CX_PROVIDER_INVOICE_BATCHES ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY", {}))
    return {"items": rows[:max(1, min(int(limit or 100), 200))], "count": len(rows)}


def financial_overview(actor: str, limit: int = 100) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    bounded = max(1, min(int(limit or 100), 200))
    queries = {
        "invoices": "SELECT BATCH_ID,PROVIDER_KEY,EXTERNAL_INVOICE_ID,CURRENCY,PERIOD_START,PERIOD_END,TOTAL_AMOUNT,STATUS,CREATED_AT FROM CX_PROVIDER_INVOICE_BATCHES ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
        "lines": "SELECT LINE_ID,BATCH_ID,EXTERNAL_LINE_ID,MODEL_ID,QUANTITY,AMOUNT,CURRENCY,CREATED_AT FROM CX_PROVIDER_INVOICE_LINES ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
        "reconciliations": "SELECT RECONCILIATION_ID,LINE_ID,USAGE_ID,RULE_VERSION,INVOICE_AMOUNT,CALCULATED_AMOUNT,VARIANCE_AMOUNT,STATUS,CREATED_AT FROM CX_MODEL_RECONCILIATIONS ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
        "corrections": "SELECT CORRECTION_ID,LINE_ID,PRIOR_CORRECTION_ID,AMOUNT_DELTA,CURRENCY,CREATED_BY,REASON,CREATED_AT FROM CX_PROVIDER_INVOICE_CORRECTIONS ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
        "rules": "SELECT RULE_ID,RULE_KEY,VERSION,TARGET_TYPE,TARGET_ID,PERCENTAGE,CURRENCY,EFFECTIVE_FROM,EFFECTIVE_TO,STATUS,CREATED_AT FROM CX_MODEL_ALLOCATION_RULES ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
        "allocations": "SELECT ALLOCATION_ID,SOURCE_TYPE,SOURCE_ID,RULE_ID,TARGET_TYPE,TARGET_ID,AMOUNT,CURRENCY,REMAINDER,CREATED_AT FROM CX_MODEL_ALLOCATIONS ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY",
    }
    return {key: _rows(connection.execute_query(sql, {}))[:bounded] for key, sql in queries.items()}


def reconcile_invoice_line(actor: str, line_id: str, usage_id: str, rule_version: str, confidence: Any, reason: str) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    line = _row(connection.execute_query_one("SELECT LINE_ID,AMOUNT,CURRENCY FROM CX_PROVIDER_INVOICE_LINES WHERE LINE_ID=:id", {"id": line_id}))
    usage = _row(connection.execute_query_one("SELECT USAGE_ID,COST,CURRENCY FROM CX_MODEL_USAGE WHERE USAGE_ID=:id", {"id": usage_id})) if usage_id else {}
    if not line or (usage_id and not usage) or not str(rule_version).strip() or not str(reason).strip():
        raise ModelGovernanceError("invoice line or usage fact is unavailable")
    if usage and str(usage.get("currency") or "") != str(line.get("currency") or ""):
        raise ModelGovernanceError("reconciliation currencies do not match")
    invoice_amount = _decimal(line["amount"]); calculated = _decimal(usage["cost"]) if usage and usage.get("cost") is not None else None
    variance = invoice_amount - calculated if calculated is not None else None
    reconciliation_id = _id("REC")
    confidence_value = _decimal(confidence)
    if confidence_value > 1:
        raise ModelGovernanceError("reconciliation confidence must be between zero and one")
    connection.execute("INSERT INTO CX_MODEL_RECONCILIATIONS(RECONCILIATION_ID,LINE_ID,USAGE_ID,RULE_VERSION,CONFIDENCE,INVOICE_AMOUNT,CALCULATED_AMOUNT,VARIANCE_AMOUNT,STATUS,CREATED_BY,REASON) VALUES(:id,:line,:usage,:rule,:confidence,:invoice,:calculated,:variance,'RECONCILED',:actor,:reason)", {"id": reconciliation_id, "line": line_id, "usage": usage_id or None, "rule": str(rule_version)[:64], "confidence": str(confidence_value), "invoice": str(invoice_amount), "calculated": str(calculated) if calculated is not None else None, "variance": str(variance) if variance is not None else None, "actor": actor, "reason": str(reason)[:500]})
    return {"reconciliation_id": reconciliation_id, "invoice_amount": str(invoice_amount), "calculated_amount": str(calculated) if calculated is not None else None, "variance_amount": str(variance) if variance is not None else None, "currency": line["currency"], "status": "RECONCILED"}


def correct_invoice_line(actor: str, line_id: str, amount_delta: Any, prior_correction_id: str, reason: str) -> Dict[str, Any]:
    """Append a linked invoice correction without mutating imported evidence."""
    _require(actor, "model_usage.manage")
    delta = _decimal(amount_delta, non_negative=False)
    if delta == 0 or not str(reason).strip():
        raise ModelGovernanceError("a non-zero correction and reason are required")
    line = _row(connection.execute_query_one(
        "SELECT LINE_ID,CURRENCY FROM CX_PROVIDER_INVOICE_LINES WHERE LINE_ID=:id", {"id": line_id},
    ))
    if not line:
        raise ModelGovernanceError("invoice line is unavailable")
    prior = str(prior_correction_id or "")[:128] or None
    if prior and not connection.execute_query_one(
        "SELECT CORRECTION_ID FROM CX_PROVIDER_INVOICE_CORRECTIONS WHERE CORRECTION_ID=:id AND LINE_ID=:line",
        {"id": prior, "line": line_id},
    ):
        raise ModelGovernanceError("prior correction is unavailable for this invoice line")
    correction_id = _id("INC")
    connection.execute(
        "INSERT INTO CX_PROVIDER_INVOICE_CORRECTIONS(CORRECTION_ID,LINE_ID,PRIOR_CORRECTION_ID,AMOUNT_DELTA,CURRENCY,CREATED_BY,REASON) VALUES(:id,:line,:prior_correction,:delta,:currency,:actor,:reason)",
        {"id": correction_id, "line": line_id, "prior_correction": prior, "delta": str(delta), "currency": line["currency"], "actor": actor, "reason": str(reason)[:500]},
    )
    return {"correction_id": correction_id, "line_id": line_id, "prior_correction_id": prior, "amount_delta": str(delta), "currency": line["currency"], "status": "APPENDED"}


def create_allocation_rule(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    from . import edition_features
    if str(edition_features.EDITION).lower() != "enterprise":
        raise ModelGovernanceError("internal chargeback requires Enterprise edition")
    rule_key = str(body.get("rule_key") or "")[:128]; reason = str(body.get("reason") or "")[:500]
    targets = body.get("targets") or [{"target_type": body.get("target_type"), "target_id": body.get("target_id"), "percentage": body.get("percentage")}]
    if not rule_key or not reason or not isinstance(targets, list) or not targets or len(targets) > 100:
        raise ModelGovernanceError("allocation rule target and reason are required")
    normalized = []
    for target in targets:
        target_type = str(target.get("target_type") or "").upper()[:32]; target_id = str(target.get("target_id") or "")[:128]
        percentage = _decimal(target.get("percentage"))
        if target_type not in ALLOWED_SCOPE_TYPES - {"GLOBAL"} or not target_id or percentage > 100:
            raise ModelGovernanceError("allocation rule target is invalid")
        normalized.append({"target_type": target_type, "target_id": target_id, "percentage": percentage})
    if sum((item["percentage"] for item in normalized), Decimal("0")) != Decimal("100.000000"):
        raise ModelGovernanceError("allocation rule target percentages must total exactly 100")
    latest = _row(connection.execute_query_one("SELECT MAX(VERSION) AS VERSION FROM CX_MODEL_ALLOCATION_RULES WHERE RULE_KEY=:key", {"key": rule_key}))
    version = int(latest.get("version") or 0) + 1; items = []
    def apply(tx):
        tx.execute("UPDATE CX_MODEL_ALLOCATION_RULES SET STATUS='SUPERSEDED' WHERE RULE_KEY=:key AND STATUS='ACTIVE'", {"key": rule_key})
        for target in normalized:
            rule_id = _id("ALR")
            effective_from = _parse_time(str(body.get("effective_from") or ""))
            effective_from_sql = ":effective_from" if effective_from is not None else "CURRENT_TIMESTAMP"
            rule_params = {"id": rule_id, "key": rule_key, "version": version, "target_type": target["target_type"], "target": target["target_id"], "percentage": str(target["percentage"]), "currency": str(body.get("currency") or "").upper()[:12] or None, "effective_to": _parse_time(str(body.get("effective_to") or "")), "actor": actor, "reason": reason}
            if effective_from is not None:
                rule_params["effective_from"] = effective_from
            tx.execute(f"INSERT INTO CX_MODEL_ALLOCATION_RULES(RULE_ID,RULE_KEY,VERSION,TARGET_TYPE,TARGET_ID,PERCENTAGE,CURRENCY,EFFECTIVE_FROM,EFFECTIVE_TO,STATUS,CREATED_BY,REASON) VALUES(:id,:key,:version,:target_type,:target,:percentage,:currency,{effective_from_sql},:effective_to,'ACTIVE',:actor,:reason)", rule_params)
            items.append({"rule_id": rule_id, **target})
    connection.execute_transaction_callback(apply)
    return {"rule_key": rule_key, "version": version, "items": items, "status": "ACTIVE"}


def allocate_source(actor: str, source_type: str, source_id: str, rule_key: str) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    kind = str(source_type).upper()
    if kind not in {"USAGE", "INVOICE"}:
        raise ModelGovernanceError("allocation source type is unsupported")
    source_sql = "SELECT COST AS AMOUNT,CURRENCY FROM CX_MODEL_USAGE WHERE USAGE_ID=:id FOR UPDATE" if kind == "USAGE" else "SELECT AMOUNT,CURRENCY FROM CX_PROVIDER_INVOICE_LINES WHERE LINE_ID=:id FOR UPDATE"
    def apply(tx):
        source = _row(tx.query_one(source_sql, {"id": source_id}))
        if not source or source.get("amount") is None or not source.get("currency"):
            raise ModelGovernanceError("allocation source amount is unavailable")
        rules = _rows(tx.query("SELECT RULE_ID,TARGET_TYPE,TARGET_ID,PERCENTAGE,CURRENCY FROM CX_MODEL_ALLOCATION_RULES WHERE RULE_KEY=:key AND STATUS='ACTIVE' AND EFFECTIVE_FROM<=CURRENT_TIMESTAMP AND (EFFECTIVE_TO IS NULL OR EFFECTIVE_TO>CURRENT_TIMESTAMP) AND (CURRENCY IS NULL OR CURRENCY=:currency) ORDER BY RULE_ID FETCH FIRST 200 ROWS ONLY", {"key": str(rule_key)[:128], "currency": source["currency"]}))
        if not rules:
            raise ModelGovernanceError("no active allocation rule applies")
        existing = _rows(tx.query("SELECT ALLOCATION_ID,RULE_ID,TARGET_TYPE,TARGET_ID,AMOUNT,CURRENCY,REMAINDER FROM CX_MODEL_ALLOCATIONS WHERE SOURCE_TYPE=:source_type AND SOURCE_ID=:source ORDER BY RULE_ID", {"source_type": kind, "source": source_id}))
        if existing:
            return {"source_type": kind, "source_id": source_id, "amount": str(_decimal(source["amount"])), "currency": source["currency"], "allocated": str(sum((_decimal(item["amount"]) for item in existing), Decimal("0"))), "balanced": sum((_decimal(item["amount"]) for item in existing), Decimal("0")) == _decimal(source["amount"]), "items": existing, "idempotent": True}
        amount = _decimal(source["amount"]); allocated = Decimal("0"); items = []
        for index, rule in enumerate(rules):
            part = (amount * _decimal(rule["percentage"]) / Decimal("100")).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            remainder = index == len(rules) - 1
            if remainder:
                part = amount - allocated
            allocated += part; allocation_id = _id("ALL")
            tx.execute("INSERT INTO CX_MODEL_ALLOCATIONS(ALLOCATION_ID,SOURCE_TYPE,SOURCE_ID,RULE_ID,TARGET_TYPE,TARGET_ID,AMOUNT,CURRENCY,REMAINDER) VALUES(:id,:source_type,:source,:rule,:target_type,:target,:allocation_amount,:currency,:remainder)", {"id": allocation_id, "source_type": kind, "source": source_id, "rule": rule["rule_id"], "target_type": rule["target_type"], "target": rule["target_id"], "allocation_amount": str(part), "currency": source["currency"], "remainder": True if str(getattr(connection, "DATABASE_DIALECT", "")).lower() == "postgresql" and remainder else (False if str(getattr(connection, "DATABASE_DIALECT", "")).lower() == "postgresql" else ("Y" if remainder else "N"))})
            items.append({"allocation_id": allocation_id, "target_type": rule["target_type"], "target_id": rule["target_id"], "amount": str(part), "remainder": remainder})
        return {"source_type": kind, "source_id": source_id, "amount": str(amount), "currency": source["currency"], "allocated": str(allocated), "balanced": allocated == amount, "items": items, "idempotent": False}
    return connection.execute_transaction_callback(apply)


def register_evidence_adapter(actor: str, body: Dict[str, Any]) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    display_name = str(body.get("display_name") or "")[:160]; verification_key = str(body.get("verification_key") or "").strip()
    scopes = body.get("scopes") or []
    if not display_name or not verification_key or not isinstance(scopes, list):
        raise ModelGovernanceError("adapter name, public verification key, and scopes are required")
    try:
        raw = base64.b64decode(verification_key, validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except Exception as exc:
        raise ModelGovernanceError("adapter verification key must be base64 Ed25519 public key") from exc
    adapter_id = str(body.get("adapter_id") or _id("EVA"))[:128]
    latest = _row(connection.execute_query_one("SELECT MAX(KEY_VERSION) AS VERSION FROM CX_MODEL_EVIDENCE_ADAPTERS WHERE ADAPTER_ID=:id", {"id": adapter_id}))
    version = int(latest.get("version") or 0) + 1
    connection.execute("UPDATE CX_MODEL_EVIDENCE_ADAPTERS SET STATUS='ROTATED' WHERE ADAPTER_ID=:id AND STATUS='ACTIVE'", {"id": adapter_id})
    connection.execute("INSERT INTO CX_MODEL_EVIDENCE_ADAPTERS(ADAPTER_ID,DISPLAY_NAME,KEY_VERSION,VERIFICATION_KEY,SCOPES_JSON,STATUS,CREATED_BY) VALUES(:id,:name,:version,:key,:scopes,'ACTIVE',:actor)", {"id": adapter_id, "name": display_name, "version": version, "key": verification_key, "scopes": _json(sorted({str(item)[:256] for item in scopes})), "actor": actor})
    return {"adapter_id": adapter_id, "key_version": version, "display_name": display_name, "scopes": scopes, "status": "ACTIVE"}


def revoke_evidence_adapter(actor: str, adapter_id: str, reason: str) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    changed = connection.execute("UPDATE CX_MODEL_EVIDENCE_ADAPTERS SET STATUS='REVOKED',REVOKED_AT=CURRENT_TIMESTAMP,REVOKED_BY=:actor,REVOKE_REASON=:reason WHERE ADAPTER_ID=:id AND STATUS='ACTIVE'", {"actor": actor, "reason": str(reason)[:500], "id": adapter_id})
    return {"adapter_id": adapter_id, "status": "REVOKED", "changed": int(changed or 0)}


def list_evidence_adapters(actor: str, limit: int = 100) -> Dict[str, Any]:
    _require(actor, "model_usage.manage")
    rows = _rows(connection.execute_query("SELECT ADAPTER_ID,DISPLAY_NAME,KEY_VERSION,SCOPES_JSON,STATUS,CREATED_BY,CREATED_AT,REVOKED_AT,REVOKE_REASON FROM CX_MODEL_EVIDENCE_ADAPTERS ORDER BY CREATED_AT DESC FETCH FIRST 200 ROWS ONLY", {}))
    for item in rows:
        try:
            item["scopes"] = json.loads(str(item.pop("scopes_json") or "[]"))
        except (TypeError, ValueError):
            item["scopes"] = []
    return {"items": rows[:max(1, min(int(limit or 100), 200))], "count": len(rows)}


def ingest_external_evidence(body: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
    adapter_id = str(body.get("adapter_id") or "")[:128]; version = int(body.get("key_version") or 0)
    sequence = int(body.get("sequence_no") or 0); nonce = str(body.get("nonce") or "")[:128]
    signature = str(body.get("signature") or ""); facts = body.get("facts") or {}
    observed_from = _parse_time(str(body.get("observed_from") or ""), required=True)
    observed_to = _parse_time(str(body.get("observed_to") or ""), required=True)
    if not nonce or not isinstance(facts, dict) or observed_to < observed_from or datetime.now(timezone.utc) - observed_to > timedelta(days=7):
        raise EvidenceRejected("external evidence envelope is invalid or stale")
    canonical = {"adapter_id": adapter_id, "key_version": version, "sequence_no": sequence, "nonce": nonce, "observed_from": observed_from.isoformat(), "observed_to": observed_to.isoformat(), "facts": facts}
    payload = _json(canonical).encode("utf-8"); payload_digest = hashlib.sha256(payload).hexdigest()
    adapter = _row(connection.execute_query_one("SELECT VERIFICATION_KEY,SCOPES_JSON,STATUS FROM CX_MODEL_EVIDENCE_ADAPTERS WHERE ADAPTER_ID=:id AND KEY_VERSION=:version AND STATUS='ACTIVE'", {"id": adapter_id, "version": version}))
    if not adapter:
        raise EvidenceRejected("external evidence adapter is unavailable")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(str(adapter["verification_key"]), validate=True)).verify(base64.b64decode(signature, validate=True), payload)
    except Exception as exc:
        raise EvidenceRejected("external evidence signature is invalid") from exc
    try:
        scopes = set(json.loads(str(adapter.get("scopes_json") or "[]")))
    except (TypeError, ValueError):
        scopes = set()
    provider = str(facts.get("provider_key") or "")[:128]; agent_id = str(facts.get("agent_id") or "")[:128]
    if any(item.startswith("provider:") for item in scopes) and f"provider:{provider}" not in scopes:
        raise EvidenceRejected("external evidence provider is outside adapter scope")
    if any(item.startswith("agent:") for item in scopes) and f"agent:{agent_id}" not in scopes:
        raise EvidenceRejected("external evidence Agent is outside adapter scope")
    existing = _row(connection.execute_query_one("SELECT BATCH_ID,PAYLOAD_DIGEST FROM CX_MODEL_EVIDENCE_BATCHES WHERE ADAPTER_ID=:id AND (SEQUENCE_NO=:sequence OR NONCE=:nonce)", {"id": adapter_id, "sequence": sequence, "nonce": nonce}))
    if existing:
        if existing.get("payload_digest") != payload_digest:
            raise EvidenceRejected("external evidence sequence or nonce conflicts")
        return {"batch_id": existing["batch_id"], "status": "VERIFIED", "idempotent": True, "correlation_id": correlation_id}
    request_count = max(0, int(facts.get("request_count") or 0)); total_tokens = facts.get("total_tokens")
    if total_tokens is not None:
        total_tokens = max(0, int(total_tokens))
    batch_id = _id("EVB")
    connection.execute("INSERT INTO CX_MODEL_EVIDENCE_BATCHES(BATCH_ID,ADAPTER_ID,KEY_VERSION,SEQUENCE_NO,NONCE,PAYLOAD_DIGEST,SIGNATURE_DIGEST,OBSERVED_FROM,OBSERVED_TO,PROVIDER_KEY,AGENT_ID,REQUEST_COUNT,TOTAL_TOKENS,USAGE_PROVENANCE,STATUS,CORRELATION_ID) VALUES(:id,:adapter,:version,:sequence,:nonce,:digest,:signature_digest,:observed_from,:observed_to,:provider,:agent,:requests,:tokens,'EXTERNALLY_VERIFIED','VERIFIED',:correlation)", {"id": batch_id, "adapter": adapter_id, "version": version, "sequence": sequence, "nonce": nonce, "digest": payload_digest, "signature_digest": hashlib.sha256(signature.encode()).hexdigest(), "observed_from": observed_from, "observed_to": observed_to, "provider": provider or None, "agent": agent_id or None, "requests": request_count, "tokens": total_tokens, "correlation": correlation_id})
    return {"batch_id": batch_id, "status": "VERIFIED", "usage_provenance": "EXTERNALLY_VERIFIED", "idempotent": False, "correlation_id": correlation_id}


def external_coverage(actor: str, resource_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _require(actor, "model_usage.read", "")
    try:
        visibility = identity_api._agent_visibility_clause(actor)
    except Exception as exc:
        raise PermissionError("external evidence scope is unavailable") from exc
    clause = "e.STATUS='VERIFIED' AND e.AGENT_ID IS NOT NULL AND EXISTS (SELECT 1 FROM CX_PRINCIPALS p WHERE p.PRINCIPAL_ID=e.AGENT_ID AND p.PRINCIPAL_TYPE='AGENT' AND " + visibility + ")"
    params: Dict[str, Any] = {"principal_id": actor} if ":principal_id" in visibility else {}
    scope = resource_scope or {}
    if scope.get("security_domain_id"):
        clause += " AND EXISTS (SELECT 1 FROM CX_DOMAIN_MEMBERS dm WHERE dm.PRINCIPAL_ID=e.AGENT_ID AND dm.SECURITY_DOMAIN_ID=:domain AND dm.STATUS='ACTIVE' AND (dm.VALID_UNTIL IS NULL OR dm.VALID_UNTIL>CURRENT_TIMESTAMP))"
        params["domain"] = str(scope["security_domain_id"])
    if scope.get("organization_id"):
        clause += " AND EXISTS (SELECT 1 FROM CX_ORGANIZATION_MEMBERS om WHERE om.PRINCIPAL_ID=e.AGENT_ID AND om.ORGANIZATION_ID=:organization AND om.STATUS='ACTIVE' AND (om.VALID_UNTIL IS NULL OR om.VALID_UNTIL>CURRENT_TIMESTAMP))"
        params["organization"] = str(scope["organization_id"])
    row = _row(connection.execute_query_one(
        "SELECT COALESCE(SUM(e.REQUEST_COUNT),0) AS REQUESTS,COALESCE(SUM(e.TOTAL_TOKENS),0) AS TOKENS,MAX(e.OBSERVED_TO) AS WATERMARK FROM CX_MODEL_EVIDENCE_BATCHES e WHERE " + clause,
        params,
    ))
    return {"externally_verified_requests": int(row.get("requests") or 0), "externally_verified_tokens": int(row.get("tokens") or 0), "watermark": row.get("watermark")}


def validate_wallboard_config(config: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(scope, dict):
        raise ModelGovernanceError("wallboard config and scope must be objects")
    widgets = config.get("widgets") or DEFAULT_WIDGETS
    dimensions = config.get("dimensions") or ["day", "provider", "model", "provenance"]
    refresh = int(config.get("refresh_seconds") or 30)
    locale = str(config.get("locale") or "zh-CN")
    if not isinstance(widgets, list) or not widgets or len(widgets) > len(ALLOWED_WIDGETS) or set(widgets) - ALLOWED_WIDGETS:
        raise ModelGovernanceError("wallboard contains an unsupported widget")
    if not isinstance(dimensions, list) or set(dimensions) - ALLOWED_DIMENSIONS:
        raise ModelGovernanceError("wallboard contains an unsupported dimension")
    if refresh < 15 or refresh > 3600 or locale not in {"zh-CN", "en-US"}:
        raise ModelGovernanceError("wallboard refresh or locale is unsupported")
    if set(scope) - {"organization_id", "security_domain_id"}:
        raise ModelGovernanceError("wallboard scope selector is unsupported")
    layout = str(config.get("layout") or "EXECUTIVE_GRID").upper()
    if layout not in {"EXECUTIVE_GRID", "OPERATIONS_GRID", "COMPLIANCE_GRID"}:
        raise ModelGovernanceError("wallboard layout is unsupported")
    if any(value and not __import__("re").fullmatch(r"[A-Za-z0-9_.:-]{1,128}", str(value)) for value in scope.values()):
        raise ModelGovernanceError("wallboard scope identifier is invalid")
    serialized = _json({"config": config, "scope": scope})
    if len(serialized) > 100_000:
        raise ModelGovernanceError("wallboard definition contains unsafe content")
    return {"widgets": list(dict.fromkeys(widgets)), "dimensions": list(dict.fromkeys(dimensions)), "refresh_seconds": refresh, "locale": locale, "layout": layout}


def create_wallboard_definition(actor: str, definition_id: str, display_name: str, config: Dict[str, Any], scope: Dict[str, Any], reason: str) -> Dict[str, Any]:
    _require(actor, "wallboard.manage")
    definition = str(definition_id or _id("WBD"))[:128]; name = str(display_name or "")[:160]; reason = str(reason or "")[:500]
    if not name or not reason:
        raise ModelGovernanceError("wallboard name and compliance reason are required")
    normalized = validate_wallboard_config(config, scope)
    latest = _row(connection.execute_query_one("SELECT MAX(VERSION) AS VERSION FROM CX_WALLBOARD_DEF_VERSIONS WHERE DEFINITION_ID=:id", {"id": definition}))
    version = int(latest.get("version") or 0) + 1; version_id = _id("WDV")
    connection.execute("INSERT INTO CX_WALLBOARD_DEF_VERSIONS(VERSION_ID,DEFINITION_ID,VERSION,DISPLAY_NAME,CONFIG_JSON,SCOPE_JSON,STATUS,CREATED_BY,REASON) VALUES(:version_id,:definition,:version,:name,:config,:scope,'DRAFT',:actor,:reason)", {"version_id": version_id, "definition": definition, "version": version, "name": name, "config": _json(normalized), "scope": _json(scope), "actor": actor, "reason": reason})
    return {"version_id": version_id, "definition_id": definition, "version": version, "display_name": name, "config": normalized, "scope": scope, "status": "DRAFT"}


def list_wallboard_definitions(actor: str) -> Dict[str, Any]:
    _require(actor, "wallboard.manage")
    rows = _rows(connection.execute_query("SELECT v.VERSION_ID,v.DEFINITION_ID,v.VERSION,v.DISPLAY_NAME,v.CONFIG_JSON,v.SCOPE_JSON,v.STATUS,v.CREATED_BY,v.REASON,v.CREATED_AT,CASE WHEN p.STATUS='CURRENT' THEN 'Y' ELSE 'N' END AS PUBLISHED FROM CX_WALLBOARD_DEF_VERSIONS v LEFT JOIN CX_WALLBOARD_PUBLICATIONS p ON p.VERSION_ID=v.VERSION_ID AND p.STATUS='CURRENT' ORDER BY v.DEFINITION_ID,v.VERSION DESC FETCH FIRST 200 ROWS ONLY", {}))
    for item in rows:
        item["version"] = int(item.get("version") or 0)
        for key in ("config_json", "scope_json"):
            try: item[key.removesuffix("_json")] = json.loads(str(item.pop(key) or "{}"))
            except (TypeError, ValueError): item[key.removesuffix("_json")] = {}
    return {"items": rows, "count": len(rows), "widget_registry": sorted(ALLOWED_WIDGETS), "dimension_registry": sorted(ALLOWED_DIMENSIONS)}


def publish_wallboard_definition(actor: str, version_id: str, reason: str) -> Dict[str, Any]:
    _require(actor, "wallboard.manage")
    reason = str(reason or "")[:500]
    if not reason:
        raise ModelGovernanceError("publication reason is required")

    def apply(tx):
        version = _row(tx.query_one("SELECT VERSION_ID,DEFINITION_ID,CONFIG_JSON,SCOPE_JSON FROM CX_WALLBOARD_DEF_VERSIONS WHERE VERSION_ID=:id FOR UPDATE", {"id": version_id}))
        if not version:
            raise ModelGovernanceError("wallboard version is unavailable")
        validate_wallboard_config(json.loads(str(version["config_json"])), json.loads(str(version["scope_json"])))
        tx.execute("UPDATE CX_WALLBOARD_PUBLICATIONS SET STATUS='RETIRED',CURRENT_MARKER=NULL WHERE DEFINITION_ID=:definition AND STATUS='CURRENT'", {"definition": version["definition_id"]})
        publication_id = _id("WDP")
        tx.execute("INSERT INTO CX_WALLBOARD_PUBLICATIONS(PUBLICATION_ID,DEFINITION_ID,VERSION_ID,STATUS,PUBLISHED_BY,REASON,CURRENT_MARKER) VALUES(:id,:definition,:version,'CURRENT',:actor,:reason,:marker)", {"id": publication_id, "definition": version["definition_id"], "version": version_id, "actor": actor, "reason": reason, "marker": version["definition_id"]})
        tx.execute("UPDATE CX_WALLBOARD_DEF_VERSIONS SET STATUS=CASE WHEN VERSION_ID=:version THEN 'PUBLISHED' ELSE STATUS END WHERE DEFINITION_ID=:definition", {"version": version_id, "definition": version["definition_id"]})
        return {"publication_id": publication_id, "definition_id": version["definition_id"], "version_id": version_id, "status": "CURRENT"}
    return connection.execute_transaction_callback(apply)


def resolve_wallboard_definition(actor: str, definition_id: str) -> Dict[str, Any]:
    if not definition_id:
        return {"definition_id": "builtin-v410", "version_id": "builtin-v410-1", "version": 1, "display_name": "平台运行总览", "config": {"widgets": DEFAULT_WIDGETS, "dimensions": ["day", "provider", "model", "provenance"], "refresh_seconds": 30, "locale": "zh-CN", "layout": "EXECUTIVE_GRID"}, "scope": {}}
    row = _row(connection.execute_query_one("SELECT v.VERSION_ID,v.DEFINITION_ID,v.VERSION,v.DISPLAY_NAME,v.CONFIG_JSON,v.SCOPE_JSON FROM CX_WALLBOARD_PUBLICATIONS p JOIN CX_WALLBOARD_DEF_VERSIONS v ON v.VERSION_ID=p.VERSION_ID WHERE p.DEFINITION_ID=:id AND p.STATUS='CURRENT'", {"id": definition_id}))
    if not row:
        raise PermissionError("published wallboard definition is unavailable")
    scope = json.loads(str(row.pop("scope_json") or "{}")); config = json.loads(str(row.pop("config_json") or "{}"))
    resource = {"security_domain_id": scope.get("security_domain_id")} if scope.get("security_domain_id") else None
    access = identity_api.effective_access(actor, "wallboard.read", resource=resource)
    if access.get("decision") != "ALLOW":
        raise PermissionError("published wallboard definition is unavailable")
    if scope.get("organization_id") and identity_api.effective_access(actor, "platform.manage").get("decision") != "ALLOW":
        membership = connection.execute_query_one("SELECT MEMBERSHIP_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID=:actor AND ORGANIZATION_ID=:organization AND STATUS='ACTIVE' AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)", {"actor": actor, "organization": scope["organization_id"]})
        if not membership:
            raise PermissionError("published wallboard definition is unavailable")
    row["version"] = int(row.get("version") or 0)
    return {**row, "config": validate_wallboard_config(config, scope), "scope": scope}


def filter_wallboard_projection(payload: Dict[str, Any], definition: Dict[str, Any]) -> Dict[str, Any]:
    widget_keys = {
        "agent_overview": {"agents"}, "runtime": {"runtime"}, "usage_trend": {"usage_trend"},
        "model_usage": {"model_usage"}, "coverage": {"coverage"}, "budget_risk": {"budget"},
        "compliance": {"compliance"}, "approvals": {"approvals"}, "graph_runs": {"graph_runs"},
        "provider_health": {"provider_health"},
    }
    allowed = set().union(*(widget_keys[item] for item in definition["config"]["widgets"]))
    always = {"definition_id", "definition_version", "definition_name", "generated_at", "freshness", "scope", "partial", "sources", "widgets", "refresh_seconds"}
    return {key: value for key, value in payload.items() if key in allowed | always}
