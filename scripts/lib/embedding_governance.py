"""Database-authoritative Embedding Contracts for v4.3.7.

This module governs model identity and vector-space compatibility.  It does
not make an LLM, a caller supplied vector, or a provider response an authority
to bypass database identity, approval, audit, or storage checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from . import connection, identity_api


MODES = frozenset({
    "PLATFORM_MANAGED", "ENTERPRISE_DIRECT", "ENTERPRISE_PROXY",
    "PRECOMPUTED_IMPORT", "NONE",
})
PROFILE_STATES = frozenset({"DRAFT", "ACTIVE", "DISABLED", "RETIRED"})
SPACE_STATES = frozenset({"DRAFT", "ACTIVE", "ARCHIVED", "MIGRATING", "RETIRED"})
PROBE_STATES = frozenset({"VERIFIED", "AGENT_VERIFIED", "GATEWAY_VERIFIED", "CONFIGURED_ONLY", "FAILED"})
DEFAULT_SPACE_KEY = "LEGACY_DEFAULT"


class EmbeddingGovernanceError(ValueError):
    """Safe error exposed by Embedding Contract operations."""


class EmbeddingConflict(EmbeddingGovernanceError):
    """Optimistic concurrency or incompatible-space error."""


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(20)}"


def _text(value: Any, limit: int = 256) -> str:
    return str(value or "").strip()[:limit]


def _row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {str(key).lower(): value for key, value in dict(row).items()} if row else None


def _rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_row(row) or {} for row in rows]


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True,
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parse(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _optional_timestamp(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EmbeddingGovernanceError("Embedding grant validity timestamp is invalid") from exc
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _dialect() -> str:
    return str(getattr(connection, "DATABASE_DIALECT", "")).lower()


def _limit(limit: int) -> tuple[str, Dict[str, Any]]:
    amount = max(1, min(int(limit), 500))
    if _dialect() in {"pg", "postgresql"}:
        return " LIMIT :limit", {"limit": amount}
    return " FETCH FIRST :limit ROWS ONLY", {"limit": amount}


def _audit(tx: Any, actor: str, action: str, resource_type: str,
           resource_id: str, outcome: str, reason: str) -> None:
    # Profile, Contract, Space and binding mutations are governance changes.
    # They must never appear successful when their required audit evidence
    # could not be committed in the same transaction.
    identity_api._audit_tx(tx, actor, action, resource_type, resource_id,
                           outcome, _text(reason, 2000))


def _profile_row(profile_id: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,MODEL_FINGERPRINT,API_KEY_CIPHER,SECRET_REFERENCE,"
        "EXECUTION_MODE,DIMENSION,DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,"
        "STATUS,HEALTH_STATE,VERSION,UPDATED_BY,UPDATE_REASON,CREATED_AT,UPDATED_AT "
        "FROM CX_EMBEDDING_PROFILES WHERE PROFILE_ID=:id", {"id": profile_id},
    ))


def _contract_row(contract_id: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT CONTRACT_ID,PROFILE_ID,CONTRACT_VERSION,PROVIDER_IDENTITY,MODEL_FINGERPRINT,DIMENSION,"
        "DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,EXECUTION_MODE,STATUS,"
        "CONTRACT_DIGEST,CREATED_BY,CREATED_AT FROM CX_EMBEDDING_CONTRACTS WHERE CONTRACT_ID=:id",
        {"id": contract_id},
    ))


def _space_row(space_id: str) -> Optional[Dict[str, Any]]:
    return _row(connection.execute_query_one(
        "SELECT SPACE_ID,SPACE_KEY,CONTRACT_ID,STATUS,IS_DEFAULT,WRITE_ENABLED,VALIDATION_STATE,"
        "PHYSICAL_REF,CREATED_BY,REASON,CREATED_AT,UPDATED_AT FROM CX_EMBEDDING_SPACES WHERE SPACE_ID=:id",
        {"id": space_id},
    ))


def list_profiles(limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,MODEL_FINGERPRINT,SECRET_REFERENCE,EXECUTION_MODE,DIMENSION,"
        "DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,STATUS,HEALTH_STATE,"
        "VERSION,UPDATED_BY,UPDATE_REASON,CREATED_AT,UPDATED_AT "
        "FROM CX_EMBEDDING_PROFILES ORDER BY PROFILE_KEY" + suffix, params,
    ))
    for row in rows:
        row["secret_present"] = bool(_profile_row(str(row.get("profile_id") or "")).get("api_key_cipher")) if row.get("profile_id") else False
        row["preprocessing"] = _parse(row.pop("preprocessing_json", "{}"), {})
        row["modalities"] = _parse(row.pop("modalities_json", "[]"), [])
    return rows


def list_spaces(limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT s.SPACE_ID,s.SPACE_KEY,s.CONTRACT_ID,s.STATUS,s.IS_DEFAULT,s.WRITE_ENABLED,s.VALIDATION_STATE,"
        "s.PHYSICAL_REF,s.CREATED_BY,s.REASON,s.CREATED_AT,s.UPDATED_AT,c.DIMENSION,c.MODEL_FINGERPRINT,"
        "p.PROFILE_KEY,p.MODEL_ID,p.EXECUTION_MODE FROM CX_EMBEDDING_SPACES s "
        "LEFT JOIN CX_EMBEDDING_CONTRACTS c ON c.CONTRACT_ID=s.CONTRACT_ID "
        "LEFT JOIN CX_EMBEDDING_PROFILES p ON p.PROFILE_ID=c.PROFILE_ID "
        "ORDER BY s.CREATED_AT DESC" + suffix, params,
    ))


def list_contracts(limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT c.CONTRACT_ID,c.PROFILE_ID,c.CONTRACT_VERSION,c.PROVIDER_IDENTITY,c.MODEL_FINGERPRINT,c.DIMENSION,"
        "c.DISTANCE_METRIC,c.NORMALIZE_VECTORS,c.EXECUTION_MODE,c.STATUS,c.CONTRACT_DIGEST,c.CREATED_BY,c.CREATED_AT,"
        "p.PROFILE_KEY,p.MODEL_ID FROM CX_EMBEDDING_CONTRACTS c "
        "LEFT JOIN CX_EMBEDDING_PROFILES p ON p.PROFILE_ID=c.PROFILE_ID "
        "ORDER BY c.CREATED_AT DESC" + suffix, params,
    ))
    return rows


def list_bindings(limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT b.BINDING_ID,b.BINDING_SCOPE,b.BINDING_SUBJECT_ID,b.PROFILE_ID,b.SPACE_ID,b.STATUS,b.VERSION,"
        "b.APPROVED_BY,b.REASON,b.CREATED_AT,b.UPDATED_AT,p.PROFILE_KEY,s.SPACE_KEY,s.CONTRACT_ID "
        "FROM CX_EMBEDDING_BINDINGS b LEFT JOIN CX_EMBEDDING_PROFILES p ON p.PROFILE_ID=b.PROFILE_ID "
        "LEFT JOIN CX_EMBEDDING_SPACES s ON s.SPACE_ID=b.SPACE_ID ORDER BY b.UPDATED_AT DESC" + suffix, params,
    ))


def _validated_mode(value: Any) -> str:
    mode = _text(value, 32).upper()
    if mode not in MODES:
        raise EmbeddingGovernanceError("unsupported Embedding execution mode")
    return mode


def _validated_dimension(value: Any, mode: str) -> int:
    try:
        dimension = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise EmbeddingGovernanceError("Embedding dimension is invalid") from exc
    if mode != "NONE" and not 1 <= dimension <= 65536:
        raise EmbeddingGovernanceError("Embedding dimension is required")
    return dimension


def _canonical_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider_identity": _text(profile.get("provider_url"), 512).rstrip("/"),
        "model_id": _text(profile.get("model_id"), 256),
        "model_fingerprint": _text(profile.get("model_fingerprint"), 256),
        "dimension": int(profile.get("dimension") or 0),
        "distance_metric": _text(profile.get("distance_metric") or "COSINE", 32).upper(),
        "normalize_vectors": "Y" if bool(profile.get("normalize_vectors", True)) else "N",
        "preprocessing": profile.get("preprocessing") if isinstance(profile.get("preprocessing"), dict) else _parse(profile.get("preprocessing_json"), {}),
        "modalities": profile.get("modalities") if isinstance(profile.get("modalities"), list) else _parse(profile.get("modalities_json"), ["TEXT"]),
        "execution_mode": _validated_mode(profile.get("execution_mode")),
    }


def _contract_payload(profile: Dict[str, Any]) -> Dict[str, Any]:
    item = _canonical_profile(profile)
    return {
        "provider_identity": item["provider_identity"],
        "model_fingerprint": item["model_fingerprint"],
        "dimension": item["dimension"],
        "distance_metric": item["distance_metric"],
        "normalize_vectors": item["normalize_vectors"],
        "preprocessing": item["preprocessing"],
        "modalities": item["modalities"],
        "execution_mode": item["execution_mode"],
    }


def upsert_profile(actor: str, *, profile_key: str, provider_url: str, model_id: str,
                   execution_mode: str, dimension: int, distance_metric: str = "COSINE",
                   normalize_vectors: bool = True, preprocessing: Optional[Dict[str, Any]] = None,
                   modalities: Optional[List[str]] = None, api_key: str = "",
                   secret_reference: str = "", reason: str = "", expected_version: Optional[int] = None,
                   model_fingerprint: str = "") -> Dict[str, Any]:
    key = _text(profile_key, 128)
    mode = _validated_mode(execution_mode)
    if not key or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("profile key and reason are required")
    if mode != "NONE" and not _text(model_id, 256):
        raise EmbeddingGovernanceError("Embedding model is required")
    if mode in {"PLATFORM_MANAGED", "ENTERPRISE_DIRECT", "ENTERPRISE_PROXY"} and not _text(provider_url, 512) and not _text(secret_reference, 512):
        raise EmbeddingGovernanceError("provider URL or secret reference is required")
    dimension = _validated_dimension(dimension, mode)
    distance = _text(distance_metric or "COSINE", 32).upper()
    if distance not in {"COSINE", "EUCLIDEAN", "DOT_PRODUCT"}:
        raise EmbeddingGovernanceError("unsupported distance metric")
    normalized_modalities = sorted({_text(item, 32).upper() for item in (modalities or ["TEXT"]) if _text(item, 32)})
    if mode != "NONE" and not normalized_modalities:
        raise EmbeddingGovernanceError("at least one Embedding modality is required")
    cipher = None
    if api_key:
        from .connection_crypto import encrypt_section
        cipher = encrypt_section({"api_key": api_key})
    profile_id = "EMB_" + key.replace("-", "_").upper()
    payload = {
        "provider_url": _text(provider_url, 512).rstrip("/"), "model_id": _text(model_id, 256),
        "model_fingerprint": _text(model_fingerprint, 256), "dimension": dimension,
        "distance_metric": distance, "normalize_vectors": normalize_vectors,
        "preprocessing": preprocessing or {}, "modalities": normalized_modalities,
        "execution_mode": mode,
    }

    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one(
            "SELECT PROFILE_ID,VERSION FROM CX_EMBEDDING_PROFILES WHERE PROFILE_KEY=:key FOR UPDATE",
            {"key": key},
        ))
        if existing and expected_version is not None and int(existing.get("version") or 0) != int(expected_version):
            raise EmbeddingConflict("Embedding Profile changed concurrently")
        version = int((existing or {}).get("version") or 0) + 1 if existing else 1
        params = {
            "profile_id": str((existing or {}).get("profile_id") or profile_id), "profile_key": key,
            "provider_url": payload["provider_url"] or None, "model_id": payload["model_id"] or "NONE", "model_fingerprint": payload["model_fingerprint"] or None, "api_cipher": cipher,
            "secret_ref": _text(secret_reference, 512) or None, "execution_mode": mode, "embedding_dimension": dimension,
            "metric": distance, "normalize_value": "Y" if normalize_vectors else "N",
            "preprocessing_json": _json(payload["preprocessing"]), "modalities_json": _json(normalized_modalities),
            "updated_by": actor, "update_reason": _text(reason, 2000), "profile_version": version,
        }
        if existing:
            secret_sql = ",API_KEY_CIPHER=:api_cipher" if cipher else ""
            update_params = {name: value for name, value in params.items() if name not in {"profile_key", "api_cipher"}}
            if cipher:
                update_params["api_cipher"] = cipher
            tx.execute(
                "UPDATE CX_EMBEDDING_PROFILES SET PROVIDER_URL=:provider_url,MODEL_ID=:model_id,MODEL_FINGERPRINT=:model_fingerprint,SECRET_REFERENCE=:secret_ref,"
                "EXECUTION_MODE=:execution_mode,DIMENSION=:embedding_dimension,DISTANCE_METRIC=:metric,NORMALIZE_VECTORS=:normalize_value,"
                "PREPROCESSING_JSON=:preprocessing_json,MODALITIES_JSON=:modalities_json,STATUS='ACTIVE',VERSION=:profile_version,"
                "UPDATED_BY=:updated_by,UPDATE_REASON=:update_reason,UPDATED_AT=CURRENT_TIMESTAMP" + secret_sql + " WHERE PROFILE_ID=:profile_id",
                update_params,
            )
        else:
            tx.execute(
                "INSERT INTO CX_EMBEDDING_PROFILES(PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,MODEL_FINGERPRINT,API_KEY_CIPHER,SECRET_REFERENCE,"
                "EXECUTION_MODE,DIMENSION,DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,STATUS,"
                "HEALTH_STATE,VERSION,UPDATED_BY,UPDATE_REASON) VALUES (:profile_id,:profile_key,:provider_url,:model_id,:model_fingerprint,:api_cipher,:secret_ref,:execution_mode,:embedding_dimension,"
                ":metric,:normalize_value,:preprocessing_json,:modalities_json,'ACTIVE','UNKNOWN',:profile_version,:updated_by,:update_reason)", params,
            )
        _audit(tx, actor, "EMBEDDING_PROFILE_UPSERT", "EMBEDDING_PROFILE", params["profile_id"], "ALLOW", params["update_reason"])
        return {"profile_id": params["profile_id"], "profile_key": key, "version": version, "status": "ACTIVE"}
    return connection.execute_transaction_callback(work)


def create_contract(actor: str, profile_id: str, reason: str, *, model_fingerprint: str = "") -> Dict[str, Any]:
    if len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("a reason is required")
    profile = _profile_row(profile_id)
    if not profile:
        raise EmbeddingGovernanceError("Embedding Profile is unavailable")
    payload = _contract_payload({**profile, "model_fingerprint": model_fingerprint or profile.get("model_fingerprint", "")})
    digest = _digest(payload)
    def work(tx: Any) -> Dict[str, Any]:
        latest = _row(tx.query_one(
            "SELECT CONTRACT_ID,CONTRACT_VERSION,CONTRACT_DIGEST FROM CX_EMBEDDING_CONTRACTS "
            "WHERE PROFILE_ID=:id ORDER BY CONTRACT_VERSION DESC FOR UPDATE",
            {"id": profile_id},
        ))
        if latest and str(latest.get("contract_digest") or "") == digest:
            return {"contract_id": latest["contract_id"], "contract_version": int(latest["contract_version"]), "idempotent": True}
        version = int((latest or {}).get("contract_version") or 0) + 1
        contract_id = _id("EC")
        tx.execute(
            "INSERT INTO CX_EMBEDDING_CONTRACTS(CONTRACT_ID,PROFILE_ID,CONTRACT_VERSION,PROVIDER_IDENTITY,MODEL_FINGERPRINT,"
            "DIMENSION,DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,EXECUTION_MODE,STATUS,"
            "CONTRACT_DIGEST,CREATED_BY) VALUES (:p_contract_id,:p_profile_id,:p_contract_version,:p_provider_identity,:p_model_fingerprint,:p_dimension,:p_metric,:p_normalize,"
            ":p_preprocessing,:p_modalities,:p_execution_mode,'ACTIVE',:p_digest,:p_actor)",
            {"p_contract_id": contract_id, "p_profile_id": profile_id, "p_contract_version": version, "p_provider_identity": payload["provider_identity"] or None,
             "p_model_fingerprint": payload["model_fingerprint"] or None, "p_dimension": payload["dimension"], "p_metric": payload["distance_metric"],
             "p_normalize": payload["normalize_vectors"], "p_preprocessing": _json(payload["preprocessing"]),
             "p_modalities": _json(payload["modalities"]), "p_execution_mode": payload["execution_mode"], "p_digest": digest, "p_actor": actor},
        )
        _audit(tx, actor, "EMBEDDING_CONTRACT_CREATE", "EMBEDDING_CONTRACT", contract_id, "ALLOW", reason)
        return {"contract_id": contract_id, "contract_version": version, "idempotent": False}
    return connection.execute_transaction_callback(work)


def create_space(actor: str, space_key: str, contract_id: str, reason: str, *,
                 default: bool = False, writable: bool = False, physical_ref: str = "") -> Dict[str, Any]:
    key = _text(space_key, 128)
    if not key or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("space key and reason are required")
    if contract_id and not _contract_row(contract_id):
        raise EmbeddingGovernanceError("Embedding Contract is unavailable")
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one("SELECT SPACE_ID FROM CX_EMBEDDING_SPACES WHERE SPACE_KEY=:key FOR UPDATE", {"key": key}))
        if existing:
            return {"space_id": existing["space_id"], "space_key": key, "idempotent": True}
        if default:
            tx.execute("UPDATE CX_EMBEDDING_SPACES SET IS_DEFAULT='N',UPDATED_AT=CURRENT_TIMESTAMP WHERE IS_DEFAULT='Y'", {})
        space_id = _id("ES")
        tx.execute(
            "INSERT INTO CX_EMBEDDING_SPACES(SPACE_ID,SPACE_KEY,CONTRACT_ID,STATUS,IS_DEFAULT,WRITE_ENABLED,VALIDATION_STATE,"
            "PHYSICAL_REF,CREATED_BY,REASON) VALUES (:p_space_id,:p_space_key,:p_contract_id,'ACTIVE',:p_is_default,:p_write_enabled,'CONFIGURED_ONLY',:p_physical_ref,:p_actor,:p_reason)",
            {"p_space_id": space_id, "p_space_key": key, "p_contract_id": contract_id or None, "p_is_default": "Y" if default else "N",
             "p_write_enabled": "Y" if writable else "N", "p_physical_ref": _text(physical_ref, 256) or None, "p_actor": actor, "p_reason": _text(reason, 2000)},
        )
        _audit(tx, actor, "EMBEDDING_SPACE_CREATE", "EMBEDDING_SPACE", space_id, "ALLOW", reason)
        return {"space_id": space_id, "space_key": key, "idempotent": False}
    return connection.execute_transaction_callback(work)


def _endpoint_url(provider_url: str) -> str:
    value = _text(provider_url, 512).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise EmbeddingGovernanceError("Embedding provider URL is invalid")
    return value if value.endswith("/embeddings") else value + "/embeddings"


def _profile_api_key(profile: Dict[str, Any]) -> str:
    cipher = str(profile.get("api_key_cipher") or "")
    if not cipher:
        return ""
    from .connection_crypto import decrypt_section
    return str(decrypt_section(cipher).get("api_key") or "")


def _physical_dimension(profile: Dict[str, Any]) -> Optional[int]:
    if _dialect() in {"pg", "postgresql"}:
        try:
            row = _row(connection.execute_query_one(
                # pgvector stores the declared vector dimension directly in
                # atttypmod (unlike variable-length PostgreSQL base types).
                "SELECT a.atttypmod AS DIMENSION FROM pg_attribute a "
                "JOIN pg_class c ON c.oid=a.attrelid WHERE c.relname='entity_embeddings' "
                "AND a.attname='embedding' AND a.attnum>0", {},
            ))
            return int((row or {}).get("dimension")) if row and int(row.get("dimension") or 0) > 0 else None
        except Exception:
            return None
    try:
        from .config import get_config
        configured = int(get_config().embedding.dimension or 0)
        return configured if configured > 0 else None
    except Exception:
        return None


def probe_profile(actor: str, profile_id: str, *, scope: str = "PLATFORM", timeout: int = 30) -> Dict[str, Any]:
    profile = _profile_row(profile_id)
    if not profile:
        raise EmbeddingGovernanceError("Embedding Profile is unavailable")
    mode = _validated_mode(profile.get("execution_mode"))
    scope = _text(scope, 32).upper() or "PLATFORM"
    result: Dict[str, Any] = {"scope": scope, "mode": mode, "configured_dimension": int(profile.get("dimension") or 0)}
    status = "CONFIGURED_ONLY"
    error_code = ""
    observed_dimension: Optional[int] = None
    observed_model = ""
    try:
        if mode == "NONE":
            status = "VERIFIED"
            result["vector_enabled"] = False
        elif scope not in {"PLATFORM", "GATEWAY"}:
            status = "CONFIGURED_ONLY"
            result["action"] = "Agent-side challenge required"
        elif not profile.get("provider_url"):
            status = "CONFIGURED_ONLY"
            result["action"] = "Enterprise-managed secret reference requires Agent-side verification"
        else:
            headers = {"Content-Type": "application/json"}
            api_key = _profile_api_key(profile)
            if api_key:
                headers["Authorization"] = "Bearer " + api_key
            request = urllib.request.Request(
                _endpoint_url(str(profile["provider_url"])),
                data=json.dumps({"model": profile["model_id"], "input": "chuanxu embedding contract probe"}).encode("utf-8"),
                headers=headers, method="POST",
            )
            with urllib.request.urlopen(request, timeout=max(1, min(int(timeout), 120))) as response:
                payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
            vector = ((payload.get("data") or [{}])[0] or {}).get("embedding")
            if not isinstance(vector, list) or not vector or not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in vector):
                raise EmbeddingGovernanceError("Embedding provider returned an invalid vector")
            observed_dimension = len(vector)
            observed_model = _text(payload.get("model") or profile["model_id"], 256)
            physical = _physical_dimension(profile)
            result.update({"observed_dimension": observed_dimension, "observed_model": observed_model, "physical_dimension": physical})
            if observed_dimension != int(profile.get("dimension") or 0):
                raise EmbeddingGovernanceError("Embedding response dimension differs from the Profile")
            if physical and physical != observed_dimension:
                raise EmbeddingGovernanceError("Embedding dimension is incompatible with deployed vector storage")
            status = "VERIFIED" if scope == "PLATFORM" else "GATEWAY_VERIFIED"
    except (EmbeddingGovernanceError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        status = "FAILED"
        error_code = "PROBE_FAILED"
        result["error"] = _text(str(exc), 256)
    probe_id = _id("EP")
    def work(tx: Any) -> Dict[str, Any]:
        tx.execute(
            "INSERT INTO CX_EMBEDDING_PROBES(PROBE_ID,PROFILE_ID,PROBE_SCOPE,STATUS,OBSERVED_DIMENSION,OBSERVED_MODEL,"
            "OBSERVED_FINGERPRINT,RESULT_JSON,ERROR_CODE,CREATED_BY) VALUES (:id,:profile,:scope,:status,:dimension,:model,"
            ":fingerprint,:result,:error,:actor)",
            {"id": probe_id, "profile": profile_id, "scope": scope, "status": status,
             "dimension": observed_dimension, "model": observed_model or None, "fingerprint": None,
             "result": _json(result), "error": error_code or None, "actor": actor},
        )
        tx.execute("UPDATE CX_EMBEDDING_PROFILES SET HEALTH_STATE=:health,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id",
                   {"health": status, "id": profile_id})
        _audit(tx, actor, "EMBEDDING_PROFILE_PROBE", "EMBEDDING_PROFILE", profile_id,
               "ALLOW" if status != "FAILED" else "DENY", f"{scope} probe: {status}")
        return {"probe_id": probe_id, "status": status, "result": result}
    return connection.execute_transaction_callback(work)


def probe_draft(actor: str, *, profile_key: str, provider_url: str, model_id: str,
                execution_mode: str, dimension: int, distance_metric: str,
                normalize_vectors: bool, api_key: str, secret_reference: str,
                reason: str, timeout: int = 30) -> Dict[str, Any]:
    """Verify an Embedding Profile before persisting it or its secret.

    This preflight intentionally writes only bounded audit evidence.  The API
    key stays in process memory for the outbound test and is never included in
    audit payloads, result JSON, or a database row.
    """
    key = _text(profile_key, 128)
    mode = _validated_mode(execution_mode)
    if not key or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("profile key and reason are required")
    if mode != "NONE" and not _text(model_id, 256):
        raise EmbeddingGovernanceError("Embedding model is required")
    if mode in {"PLATFORM_MANAGED", "ENTERPRISE_DIRECT", "ENTERPRISE_PROXY"} and not _text(provider_url, 512) and not _text(secret_reference, 512):
        raise EmbeddingGovernanceError("provider URL or secret reference is required")
    # A zero draft dimension means "discover it from the provider".  Persisted
    # Profiles still require a positive dimension for every vector mode.
    configured_dimension = int(dimension or 0)
    if mode == "NONE":
        configured_dimension = 0
    elif configured_dimension < 0 or configured_dimension > 65536:
        raise EmbeddingGovernanceError("Embedding dimension is invalid")
    metric = _text(distance_metric or "COSINE", 32).upper()
    if metric not in {"COSINE", "EUCLIDEAN", "DOT_PRODUCT"}:
        raise EmbeddingGovernanceError("unsupported distance metric")

    result: Dict[str, Any] = {
        "scope": "DRAFT", "mode": mode, "configured_dimension": configured_dimension,
        "distance_metric": metric, "normalize_vectors": bool(normalize_vectors),
    }
    status = "FAILED"
    outcome = "DENY"
    try:
        if mode == "NONE":
            status = "VERIFIED"
            outcome = "ALLOW"
            result["vector_enabled"] = False
        elif not _text(provider_url, 512):
            raise EmbeddingGovernanceError(
                "A provider URL is required for pre-creation testing; a secret reference must be verified by an authenticated Agent after creation"
            )
        else:
            headers = {"Content-Type": "application/json"}
            if _text(api_key, 4096):
                headers["Authorization"] = "Bearer " + _text(api_key, 4096)
            request = urllib.request.Request(
                _endpoint_url(_text(provider_url, 512)),
                data=json.dumps({"model": _text(model_id, 256), "input": "chuanxu embedding contract probe"}).encode("utf-8"),
                headers=headers, method="POST",
            )
            with urllib.request.urlopen(request, timeout=max(1, min(int(timeout), 120))) as response:
                payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
            vector = ((payload.get("data") or [{}])[0] or {}).get("embedding")
            if not isinstance(vector, list) or not vector or not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in vector):
                raise EmbeddingGovernanceError("Embedding provider returned an invalid vector")
            observed_dimension = len(vector)
            physical = _physical_dimension({"dimension": configured_dimension})
            result.update({
                "observed_dimension": observed_dimension,
                "observed_model": _text(payload.get("model") or model_id, 256),
                "physical_dimension": physical,
            })
            if configured_dimension and observed_dimension != configured_dimension:
                raise EmbeddingGovernanceError("Embedding response dimension differs from the Profile")
            if physical and physical != observed_dimension:
                raise EmbeddingGovernanceError("Embedding dimension is incompatible with deployed vector storage")
            status = "VERIFIED"
            outcome = "ALLOW"
    except (EmbeddingGovernanceError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        result["error"] = _text(str(exc), 256)

    result["response_digest"] = _digest({
        "model": result.get("observed_model") or model_id,
        "dimension": result.get("observed_dimension") or configured_dimension,
        "status": status,
    })

    def work(tx: Any) -> Dict[str, Any]:
        _audit(tx, actor, "EMBEDDING_PROFILE_DRAFT_PROBE", "EMBEDDING_PROFILE_DRAFT", key,
               outcome, f"Draft probe: {status}")
        return {"status": status, "result": result}
    return connection.execute_transaction_callback(work)


def activate_platform_embedding(actor: str, *, profile_key: str, provider_url: str,
                                model_id: str, execution_mode: str, dimension: int,
                                distance_metric: str = "COSINE", api_key: str = "",
                                secret_reference: str = "", reason: str = "",
                                model_fingerprint: str = "") -> Dict[str, Any]:
    """Probe and activate the one platform-wide Embedding contract.

    The provider probe is performed before persistence. Once a platform
    Contract has been deployed, its vector identity is immutable at runtime:
    replacement is a redeployment operation, never an in-place edit.
    """
    if len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("profile key and reason are required")
    normalized_mode = _validated_mode(execution_mode)
    if normalized_mode != "NONE":
        # Platform default normalization is a contract invariant, not a UI
        # preference.  Callers cannot disable it through this endpoint.
        normalize_vectors = True
    else:
        normalize_vectors = True
    probe = probe_draft(
        actor, profile_key=profile_key, provider_url=provider_url,
        model_id=model_id, execution_mode=normalized_mode, dimension=dimension,
        distance_metric=distance_metric, normalize_vectors=normalize_vectors,
        api_key=api_key, secret_reference=secret_reference, reason=reason,
    )
    if str(probe.get("status") or "").upper() != "VERIFIED":
        raise EmbeddingGovernanceError("Embedding provider verification failed")
    probe_result = dict(probe.get("result") or {})
    observed_dimension = int(probe_result.get("observed_dimension") or dimension or 0)
    if normalized_mode != "NONE" and observed_dimension <= 0:
        raise EmbeddingGovernanceError("Embedding provider dimension was not observed")
    activation_id = _id("EA")
    response_digest = str(probe_result.get("response_digest") or _digest(probe_result))

    def work(tx: Any) -> Dict[str, Any]:
        deployed_binding = _row(tx.query_one(
            "SELECT BINDING_ID,PROFILE_ID,SPACE_ID,STATUS,VERSION FROM CX_EMBEDDING_BINDINGS "
            "WHERE BINDING_SCOPE='PLATFORM' AND BINDING_SUBJECT_ID='DEFAULT' FOR UPDATE", {},
        ))
        if deployed_binding and str(deployed_binding.get("status") or "").upper() == "ACTIVE":
            raise EmbeddingConflict(
                "Platform Embedding is already deployed; redeploy the platform to change the unified Embedding model"
            )
        key = _text(profile_key, 128)
        profile_id = "EMB_" + key.replace("-", "_").upper()
        existing_profile = _row(tx.query_one(
            "SELECT PROFILE_ID,PROFILE_KEY,VERSION FROM CX_EMBEDDING_PROFILES WHERE PROFILE_KEY=:key FOR UPDATE",
            {"key": key},
        ))
        profile_id = str((existing_profile or {}).get("profile_id") or profile_id)
        profile_version = int((existing_profile or {}).get("version") or 0) + 1
        from .connection_crypto import encrypt_section
        api_cipher = encrypt_section({"api_key": api_key}) if api_key else None
        profile_params = {
            "profile_id": profile_id, "profile_key": key,
            "provider_url": _text(provider_url, 512).rstrip("/") or None,
            "model_id": _text(model_id, 256) or "NONE",
            "model_fingerprint": _text(model_fingerprint, 256) or None,
            "api_cipher": api_cipher, "secret_ref": _text(secret_reference, 512) or None,
            "execution_mode": normalized_mode, "dimension": observed_dimension,
            "metric": _text(distance_metric or "COSINE", 32).upper(),
            "preprocessing": _json({}),
            "modalities": _json(["TEXT"]), "version": profile_version,
            "actor": actor, "reason": _text(reason, 2000),
        }
        if existing_profile:
            tx.execute(
                "UPDATE CX_EMBEDDING_PROFILES SET PROVIDER_URL=:provider_url,MODEL_ID=:model_id,"
                "MODEL_FINGERPRINT=:model_fingerprint,API_KEY_CIPHER=:api_cipher,SECRET_REFERENCE=:secret_ref,"
                "EXECUTION_MODE=:execution_mode,DIMENSION=:dimension,DISTANCE_METRIC=:metric,"
                "NORMALIZE_VECTORS='Y',PREPROCESSING_JSON=:preprocessing,MODALITIES_JSON=:modalities,"
                "STATUS='ACTIVE',HEALTH_STATE='VERIFIED',VERSION=:version,UPDATED_BY=:actor,"
                "UPDATE_REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:profile_id",
                profile_params,
            )
        else:
            tx.execute(
                "INSERT INTO CX_EMBEDDING_PROFILES(PROFILE_ID,PROFILE_KEY,PROVIDER_URL,MODEL_ID,"
                "MODEL_FINGERPRINT,API_KEY_CIPHER,SECRET_REFERENCE,EXECUTION_MODE,DIMENSION,DISTANCE_METRIC,"
                "NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,STATUS,HEALTH_STATE,VERSION,UPDATED_BY,UPDATE_REASON) "
                "VALUES (:profile_id,:profile_key,:provider_url,:model_id,:model_fingerprint,:api_cipher,"
                ":secret_ref,:execution_mode,:dimension,:metric,'Y',:preprocessing,:modalities,'ACTIVE','VERIFIED',"
                ":version,:actor,:reason)", profile_params,
            )
        _audit(tx, actor, "EMBEDDING_PROFILE_UPSERT", "EMBEDDING_PROFILE", profile_id, "ALLOW", reason)

        effective_model_fingerprint = _text(model_fingerprint, 256) or _digest({"model_id": _text(model_id, 256)})
        payload = {
            "provider_identity": profile_params["provider_url"] or "",
            "model_fingerprint": effective_model_fingerprint,
            "model_id": _text(model_id, 256),
            "dimension": observed_dimension, "distance_metric": profile_params["metric"],
            "normalize_vectors": "Y", "preprocessing": {}, "modalities": ["TEXT"],
            "execution_mode": normalized_mode,
        }
        digest = _digest(payload)
        latest = _row(tx.query_one(
            "SELECT CONTRACT_ID,CONTRACT_VERSION,CONTRACT_DIGEST FROM CX_EMBEDDING_CONTRACTS "
            "WHERE PROFILE_ID=:profile_id ORDER BY CONTRACT_VERSION DESC FOR UPDATE",
            {"profile_id": profile_id},
        ))
        contract_id = str((latest or {}).get("contract_id") or "")
        contract_version = int((latest or {}).get("contract_version") or 0)
        contract_idempotent = bool(latest and str(latest.get("contract_digest") or "") == digest)
        if not contract_idempotent:
            contract_version += 1
            contract_id = _id("EC")
            tx.execute(
                "INSERT INTO CX_EMBEDDING_CONTRACTS(CONTRACT_ID,PROFILE_ID,CONTRACT_VERSION,PROVIDER_IDENTITY,"
                "MODEL_FINGERPRINT,DIMENSION,DISTANCE_METRIC,NORMALIZE_VECTORS,PREPROCESSING_JSON,MODALITIES_JSON,"
                "EXECUTION_MODE,STATUS,CONTRACT_DIGEST,CREATED_BY) VALUES (:id,:profile_id,:version,:provider,"
                ":fingerprint,:dimension,:metric,'Y',:preprocessing,:modalities,:execution_mode,'ACTIVE',:digest,:actor)",
                {"id": contract_id, "profile_id": profile_id, "version": contract_version,
                 "provider": payload["provider_identity"] or None, "fingerprint": payload["model_fingerprint"] or None,
                 "dimension": observed_dimension, "metric": payload["distance_metric"],
                 "preprocessing": _json({}), "modalities": _json(["TEXT"]), "execution_mode": normalized_mode,
                 "digest": digest, "actor": actor},
            )
            _audit(tx, actor, "EMBEDDING_CONTRACT_CREATE", "EMBEDDING_CONTRACT", contract_id, "ALLOW", reason)

        current_space = _row(tx.query_one(
            "SELECT SPACE_ID,SPACE_KEY,CONTRACT_ID FROM CX_EMBEDDING_SPACES "
            "WHERE IS_DEFAULT='Y' FOR UPDATE", {},
        ))
        if contract_idempotent:
            space = _row(tx.query_one(
                "SELECT SPACE_ID,SPACE_KEY FROM CX_EMBEDDING_SPACES WHERE CONTRACT_ID=:contract_id "
                "AND IS_DEFAULT='Y' FOR UPDATE", {"contract_id": contract_id},
            ))
        else:
            space = None
        migration_state = "NONE" if contract_idempotent else "MIGRATION_REQUIRED"
        if not space:
            if current_space and str(current_space.get("contract_id") or "") != contract_id:
                tx.execute(
                    "UPDATE CX_EMBEDDING_SPACES SET IS_DEFAULT='N',WRITE_ENABLED='N',STATUS='ARCHIVED',"
                    "UPDATED_AT=CURRENT_TIMESTAMP WHERE SPACE_ID=:space_id",
                    {"space_id": current_space["space_id"]},
                )
            space_id = _id("ES")
            space_key = f"PLATFORM_DEFAULT_V{contract_version}"
            tx.execute(
                "INSERT INTO CX_EMBEDDING_SPACES(SPACE_ID,SPACE_KEY,CONTRACT_ID,STATUS,IS_DEFAULT,WRITE_ENABLED,"
                "VALIDATION_STATE,PHYSICAL_REF,CREATED_BY,REASON) VALUES (:id,:key,:contract_id,'ACTIVE','Y',:writable,"
                "'VERIFIED',NULL,:actor,:reason)",
                {"id": space_id, "key": space_key, "contract_id": contract_id,
                 "writable": "Y" if normalized_mode != "NONE" else "N", "actor": actor, "reason": reason},
            )
            _audit(tx, actor, "EMBEDDING_SPACE_CREATE", "EMBEDDING_SPACE", space_id, "ALLOW", reason)
            space = {"space_id": space_id, "space_key": space_key, "idempotent": False}
        else:
            space_id = str(space["space_id"])
            tx.execute(
                "UPDATE CX_EMBEDDING_SPACES SET STATUS='ACTIVE',IS_DEFAULT='Y',WRITE_ENABLED=:writable,"
                "VALIDATION_STATE='VERIFIED',UPDATED_AT=CURRENT_TIMESTAMP WHERE SPACE_ID=:space_id",
                {"space_id": space_id, "writable": "Y" if normalized_mode != "NONE" else "N"},
            )
            space["idempotent"] = True

        binding_row = deployed_binding
        binding_id = str((binding_row or {}).get("binding_id") or _id("EB"))
        binding_version = int((binding_row or {}).get("version") or 0) + 1
        binding_params = {"id": binding_id, "profile_id": profile_id, "space_id": space_id,
                          "version": binding_version, "actor": actor, "reason": _text(reason, 2000)}
        if binding_row:
            tx.execute(
                "UPDATE CX_EMBEDDING_BINDINGS SET PROFILE_ID=:profile_id,SPACE_ID=:space_id,STATUS='ACTIVE',"
                "VERSION=:version,APPROVED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE BINDING_ID=:id",
                binding_params,
            )
        else:
            tx.execute(
                "INSERT INTO CX_EMBEDDING_BINDINGS(BINDING_ID,BINDING_SCOPE,BINDING_SUBJECT_ID,PROFILE_ID,SPACE_ID,"
                "STATUS,VERSION,APPROVED_BY,REASON) VALUES (:id,'PLATFORM','DEFAULT',:profile_id,:space_id,'ACTIVE',"
                ":version,:actor,:reason)", binding_params,
            )
        _audit(tx, actor, "EMBEDDING_BINDING_UPSERT", "EMBEDDING_BINDING", binding_id, "ALLOW", reason)
        tx.execute(
            "INSERT INTO CX_EMBEDDING_ACTIVATION_EVIDENCE(ACTIVATION_ID,PROFILE_ID,PROFILE_VERSION,OBSERVED_DIMENSION,"
            "OBSERVED_MODEL,RESPONSE_DIGEST,PROBE_STATUS,ACTIVATION_STATUS,CONTRACT_ID,SPACE_ID,BINDING_ID,MIGRATION_STATE,REASON,ACTOR) "
            "VALUES (:id,:profile,:profile_version,:dimension,:model,:digest,'VERIFIED','ACTIVE',:contract,:space,:binding,:migration,:reason,:actor)",
            {"id": activation_id, "profile": profile_id, "profile_version": profile_version,
             "dimension": observed_dimension, "model": probe_result.get("observed_model") or model_id,
             "digest": response_digest, "contract": contract_id, "space": space_id,
             "binding": binding_id, "migration": migration_state,
             "reason": _text(reason, 2000), "actor": actor},
        )
        _audit(tx, actor, "EMBEDDING_PLATFORM_ACTIVATE", "EMBEDDING_PROFILE", profile_id, "ALLOW", reason)
        return {"activation_id": activation_id, "profile_id": profile_id, "profile_version": profile_version,
                "contract_id": contract_id, "contract_version": contract_version, "space_id": space_id,
                "space_key": space["space_key"], "binding_id": binding_id,
                "binding_version": binding_version, "migration_state": migration_state,
                "contract_idempotent": contract_idempotent}

    evidence = connection.execute_transaction_callback(work)
    return {**evidence, "normalize_vectors": True, "validation_state": "VERIFIED",
            "profile": {"profile_id": evidence["profile_id"], "profile_key": _text(profile_key, 128),
                        "version": evidence["profile_version"], "status": "ACTIVE"},
            "contract": {"contract_id": evidence["contract_id"], "contract_version": evidence["contract_version"],
                         "idempotent": evidence["contract_idempotent"]},
            "space": {"space_id": evidence["space_id"], "space_key": evidence["space_key"]},
            "binding": {"binding_id": evidence["binding_id"], "version": evidence.get("binding_version", 1)}}


def record_agent_probe(actor: str, profile_id: str, *, observed_dimension: int,
                       observed_model: str, response_digest: str,
                       model_fingerprint: str = "") -> Dict[str, Any]:
    """Record a signed-runtime Agent-side Embedding challenge result.

    Enterprise-direct profiles deliberately keep the provider credential and
    sample vector outside the platform.  The authenticated Agent submits only
    bounded compatibility evidence; its active binding is checked again before
    it can move a Space into the Agent-verified state.
    """
    profile = _profile_row(profile_id)
    if not profile:
        raise EmbeddingGovernanceError("Embedding Profile is unavailable")
    effective = effective_binding(actor)
    bound_profile = str(((effective.get("profile") or {}).get("profile_id") or ""))
    if bound_profile != profile_id:
        raise EmbeddingConflict("Agent is not bound to this Embedding Profile")
    try:
        dimension = int(observed_dimension)
    except (TypeError, ValueError) as exc:
        raise EmbeddingGovernanceError("Agent probe dimension is invalid") from exc
    if dimension != int(profile.get("dimension") or 0):
        raise EmbeddingConflict("Agent probe dimension differs from the Profile")
    model = _text(observed_model, 256)
    if model and model != str(profile.get("model_id") or ""):
        raise EmbeddingConflict("Agent probe model differs from the Profile")
    digest = _text(response_digest, 128).lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise EmbeddingGovernanceError("Agent probe response digest is invalid")
    expected_fingerprint = _text(profile.get("model_fingerprint"), 256)
    supplied_fingerprint = _text(model_fingerprint, 256)
    if expected_fingerprint and supplied_fingerprint and expected_fingerprint != supplied_fingerprint:
        raise EmbeddingConflict("Agent probe fingerprint differs from the Profile")
    probe_id = _id("EP")
    space = effective.get("space") or {}
    def work(tx: Any) -> Dict[str, Any]:
        tx.execute(
            "INSERT INTO CX_EMBEDDING_PROBES(PROBE_ID,PROFILE_ID,PROBE_SCOPE,STATUS,OBSERVED_DIMENSION,OBSERVED_MODEL,"
            "OBSERVED_FINGERPRINT,RESULT_JSON,ERROR_CODE,CREATED_BY) VALUES (:id,:profile,'AGENT','AGENT_VERIFIED',:dimension,:model,"
            ":fingerprint,:result,NULL,:actor)",
            {"id": probe_id, "profile": profile_id, "dimension": dimension, "model": model or None,
             "fingerprint": supplied_fingerprint or None,
             "result": _json({"response_digest": digest, "binding_id": (effective.get("binding") or {}).get("binding_id")}), "actor": actor},
        )
        tx.execute("UPDATE CX_EMBEDDING_PROFILES SET HEALTH_STATE='AGENT_VERIFIED',UPDATED_AT=CURRENT_TIMESTAMP WHERE PROFILE_ID=:id", {"id": profile_id})
        if space.get("space_id"):
            tx.execute("UPDATE CX_EMBEDDING_SPACES SET VALIDATION_STATE='AGENT_VERIFIED',UPDATED_AT=CURRENT_TIMESTAMP WHERE SPACE_ID=:id", {"id": space["space_id"]})
        _audit(tx, actor, "EMBEDDING_AGENT_PROBE", "EMBEDDING_PROFILE", profile_id, "ALLOW", "Agent-side compatibility challenge")
        return {"probe_id": probe_id, "status": "AGENT_VERIFIED", "profile_id": profile_id, "space_id": space.get("space_id")}
    return connection.execute_transaction_callback(work)


def bind(actor: str, binding_scope: str, binding_subject_id: str, profile_id: str,
         space_id: str, reason: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
    scope = _text(binding_scope, 32).upper()
    subject = _text(binding_subject_id, 128)
    if scope not in {"PLATFORM", "TEMPLATE", "AGENT"} or not subject or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("binding scope, subject, and reason are required")
    profile = _profile_row(profile_id) if profile_id else None
    space = _space_row(space_id) if space_id else None
    if profile_id and not profile:
        raise EmbeddingGovernanceError("Embedding Profile is unavailable")
    if space_id and not space:
        raise EmbeddingGovernanceError("Embedding Space is unavailable")
    if space and profile:
        contract = _contract_row(str(space.get("contract_id") or "")) if space.get("contract_id") else None
        if contract and str(contract.get("profile_id") or "") != profile_id:
            raise EmbeddingConflict("Embedding Space belongs to another Profile")
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one(
            "SELECT BINDING_ID,VERSION FROM CX_EMBEDDING_BINDINGS WHERE BINDING_SCOPE=:scope AND BINDING_SUBJECT_ID=:subject FOR UPDATE",
            {"scope": scope, "subject": subject},
        ))
        if existing and expected_version is not None and int(existing.get("version") or 0) != int(expected_version):
            raise EmbeddingConflict("Embedding binding changed concurrently")
        binding_id = str((existing or {}).get("binding_id") or _id("EB"))
        version = int((existing or {}).get("version") or 0) + 1 if existing else 1
        params = {"p_binding_id": binding_id, "p_scope": scope, "p_subject": subject, "p_profile_id": profile_id or None,
                  "p_space_id": space_id or None, "p_version": version, "p_actor": actor, "p_reason": _text(reason, 2000)}
        if existing:
            update_params = {
                key: value for key, value in params.items()
                if key not in {"p_scope", "p_subject"}
            }
            tx.execute(
                "UPDATE CX_EMBEDDING_BINDINGS SET PROFILE_ID=:p_profile_id,SPACE_ID=:p_space_id,STATUS='ACTIVE',VERSION=:p_version,"
                "APPROVED_BY=:p_actor,REASON=:p_reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE BINDING_ID=:p_binding_id", update_params,
            )
        else:
            tx.execute(
                "INSERT INTO CX_EMBEDDING_BINDINGS(BINDING_ID,BINDING_SCOPE,BINDING_SUBJECT_ID,PROFILE_ID,SPACE_ID,"
                "STATUS,VERSION,APPROVED_BY,REASON) VALUES (:p_binding_id,:p_scope,:p_subject,:p_profile_id,:p_space_id,'ACTIVE',:p_version,:p_actor,:p_reason)", params,
            )
        _audit(tx, actor, "EMBEDDING_BINDING_UPSERT", "EMBEDDING_BINDING", binding_id, "ALLOW", params["p_reason"])
        return {"binding_id": binding_id, "version": version, "binding_scope": scope, "binding_subject_id": subject}
    return connection.execute_transaction_callback(work)


def effective_binding(agent_id: str = "", template_key: str = "") -> Dict[str, Any]:
    candidates = [("AGENT", _text(agent_id, 128)), ("TEMPLATE", _text(template_key, 128)), ("PLATFORM", "DEFAULT")]
    for scope, subject in candidates:
        if not subject:
            continue
        binding = _row(connection.execute_query_one(
            "SELECT BINDING_ID,PROFILE_ID,SPACE_ID,VERSION,STATUS FROM CX_EMBEDDING_BINDINGS "
            "WHERE BINDING_SCOPE=:scope AND BINDING_SUBJECT_ID=:subject AND STATUS='ACTIVE'",
            {"scope": scope, "subject": subject},
        ))
        if not binding:
            continue
        profile = _profile_row(str(binding.get("profile_id") or "")) if binding.get("profile_id") else None
        space = _space_row(str(binding.get("space_id") or "")) if binding.get("space_id") else None
        contract = _contract_row(str((space or {}).get("contract_id") or "")) if space else None
        return {"binding": binding, "profile": profile, "space": space, "contract": contract,
                "source": scope, "ready": bool(profile and space and contract and str(space.get("write_enabled") or "N") == "Y"
                                              and str(space.get("validation_state") or "") in {"VERIFIED", "AGENT_VERIFIED", "GATEWAY_VERIFIED"})}
    return {"binding": None, "profile": None, "space": None, "contract": None, "source": "NONE", "ready": False}


def embedding_gateway_access(agent_id: str) -> Dict[str, Any]:
    """Resolve runtime access independently from the model Binding.

    Platform-created Agents retain platform-default behavior. External Agents
    fail closed unless an active, time-bounded database grant matches their
    Agent, template, organization, or security-domain identity.
    """
    agent = _row(connection.execute_query_one(
        "SELECT p.PRINCIPAL_ID,p.STATUS,n.SOURCE,n.TEMPLATE_ID FROM CX_PRINCIPALS p "
        "LEFT JOIN CX_NATIVE_AGENTS n ON n.AGENT_ID=p.PRINCIPAL_ID "
        "WHERE p.PRINCIPAL_ID=:id AND p.PRINCIPAL_TYPE='AGENT'", {"id": agent_id},
    ))
    if not agent or str(agent.get("status") or "").upper() != "ACTIVE":
        raise EmbeddingGovernanceError("Agent is unavailable for Embedding gateway access")
    source = str(agent.get("source") or "EXTERNAL_SKILL").upper()
    external = source not in {"PLATFORM_BUILTIN", "PLATFORM_CREATED"}
    effective = effective_binding(agent_id)
    if external:
        registration = _row(connection.execute_query_one(
            "SELECT EMBEDDING_MODE FROM AGENT_REGISTRATIONS WHERE AGENT_ID=:id", {"id": agent_id}
        ))
        if registration and str(registration.get("embedding_mode") or "PLATFORM_MANAGED").upper() == "AGENT_MANAGED":
            return {"allowed": False, "external": True, "agent_source": source,
                    "decision": "AGENT_MANAGED_NO_PLATFORM_ROUTE", "grant": None,
                    "effective": effective}
    if not effective.get("binding") or not effective.get("ready"):
        raise EmbeddingGovernanceError("Embedding Contract is not available for this Agent")
    profile_id = str(((effective.get("profile") or {}).get("profile_id") or ""))
    subject_ids: Dict[str, set[str]] = {
        "AGENT": {agent_id}, "TEMPLATE": set(), "ORGANIZATION": set(), "SECURITY_DOMAIN": set(),
    }
    if agent.get("template_id"):
        subject_ids["TEMPLATE"].add(str(agent["template_id"]))
    for row in _rows(connection.execute_query(
        "SELECT SECURITY_DOMAIN_ID FROM CX_DOMAIN_MEMBERS WHERE PRINCIPAL_ID=:id AND STATUS='ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)", {"id": agent_id},
    )):
        if row.get("security_domain_id"):
            subject_ids["SECURITY_DOMAIN"].add(str(row["security_domain_id"]))
    for row in _rows(connection.execute_query(
        "SELECT ORGANIZATION_ID FROM CX_ORGANIZATION_MEMBERS WHERE PRINCIPAL_ID=:id AND STATUS='ACTIVE' "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP) UNION SELECT om.ORGANIZATION_ID "
        "FROM CX_AGENT_RELATIONSHIPS ar JOIN CX_ORGANIZATION_MEMBERS om ON om.PRINCIPAL_ID=ar.PRINCIPAL_ID "
        "WHERE ar.AGENT_ID=:id AND ar.STATUS='ACTIVE' AND om.STATUS='ACTIVE' "
        "AND (om.VALID_UNTIL IS NULL OR om.VALID_UNTIL>CURRENT_TIMESTAMP)", {"id": agent_id},
    )):
        if row.get("organization_id"):
            subject_ids["ORGANIZATION"].add(str(row["organization_id"]))
    grants = _rows(connection.execute_query(
        "SELECT GRANT_ID,SUBJECT_TYPE,SUBJECT_ID,EFFECT,ALLOWED_PROFILE_ID,MAX_BATCH_SIZE,MAX_INPUT_CHARS,"
        "VALID_FROM,VALID_UNTIL,VERSION FROM CX_EMBEDDING_ACCESS_GRANTS WHERE STATUS='ACTIVE' "
        "AND (VALID_FROM IS NULL OR VALID_FROM<=CURRENT_TIMESTAMP) "
        "AND (VALID_UNTIL IS NULL OR VALID_UNTIL>CURRENT_TIMESTAMP)", {},
    ))
    matching = [item for item in grants
                if str(item.get("subject_id") or "") in subject_ids.get(str(item.get("subject_type") or ""), set())
                and (not item.get("allowed_profile_id") or str(item.get("allowed_profile_id")) == profile_id)]
    denied = next((item for item in matching if str(item.get("effect") or "").upper() == "DENY"), None)
    if denied:
        return {"allowed": False, "external": external, "agent_source": source,
                "decision": "EXPLICIT_DENY", "grant": denied, "effective": effective}
    priority = {"AGENT": 0, "TEMPLATE": 1, "SECURITY_DOMAIN": 2, "ORGANIZATION": 3}
    allowed = sorted(
        (item for item in matching if str(item.get("effect") or "").upper() == "ALLOW"),
        key=lambda item: (priority.get(str(item.get("subject_type") or ""), 99), -int(item.get("version") or 0)),
    )
    if allowed:
        grant = allowed[0]
        return {"allowed": True, "external": external, "agent_source": source,
                "decision": "EXPLICIT_ALLOW", "grant": grant, "effective": effective,
                "max_batch_size": max(1, min(int(grant.get("max_batch_size") or 1), 16)),
                "max_input_chars": max(1, min(int(grant.get("max_input_chars") or 16000), 64000))}
    if external:
        return {"allowed": False, "external": True, "agent_source": source,
                "decision": "EXTERNAL_DEFAULT_DENY", "grant": None, "effective": effective}
    return {"allowed": True, "external": False, "agent_source": source,
            "decision": "PLATFORM_AGENT_DEFAULT", "grant": None, "effective": effective,
            "max_batch_size": 16, "max_input_chars": 64000}


def require_embedding_gateway_access(agent_id: str) -> Dict[str, Any]:
    access = embedding_gateway_access(agent_id)
    if not access.get("allowed"):
        raise PermissionError("Agent is not authorized for platform Embedding generation")
    return access


def gateway_embeddings(actor: str, input_value: Any, *, requested_model: str = "",
                       idempotency_key: str = "", correlation_id: str = "") -> Dict[str, Any]:
    """Generate governed vectors for an authenticated external Agent.

    The caller can name the effective model as an OpenAI-client compatibility
    check, but cannot select or override the Profile bound by the platform.
    Prompt text and returned vectors are never persisted in usage or audit
    records.
    """
    access = require_embedding_gateway_access(actor)
    effective = access["effective"]
    profile = effective.get("profile") or {}
    contract = effective.get("contract") or {}
    space = effective.get("space") or {}
    mode = _validated_mode(profile.get("execution_mode"))
    if mode != "PLATFORM_MANAGED":
        raise EmbeddingGovernanceError("Agent Embedding generation is not routed through the platform")
    model_id = str(profile.get("model_id") or "")
    profile_key = str(profile.get("profile_key") or "")
    requested = _text(requested_model, 256)
    if requested and requested not in {model_id, profile_key}:
        raise EmbeddingConflict("Requested model differs from the effective Embedding Binding")
    if isinstance(input_value, str):
        inputs = [input_value]
    elif isinstance(input_value, list) and all(isinstance(item, str) for item in input_value):
        inputs = list(input_value)
    else:
        raise EmbeddingGovernanceError("input must be a string or a list of strings")
    batch_limit = int(access.get("max_batch_size") or 1)
    char_limit = int(access.get("max_input_chars") or 16000)
    if not inputs or len(inputs) > batch_limit:
        raise EmbeddingGovernanceError(f"input must contain between 1 and {batch_limit} texts")
    inputs = [item.strip() for item in inputs]
    if any(not item or len(item) > char_limit for item in inputs) or sum(len(item) for item in inputs) > char_limit:
        raise EmbeddingGovernanceError("Embedding input exceeds the configured limit")

    from . import model_governance_api, model_usage_api
    request_id = _id("EMR")
    started = time.monotonic()
    input_digest = _digest(inputs)
    key = _text(idempotency_key, 160)
    if key:
        model_usage_api._reserve_idempotency(actor, key, input_digest)
    request_params = {
        "id": request_id, "actor": actor, "agent": actor,
        "profile": str(profile.get("profile_id") or ""), "model": model_id,
        "key": key or None, "digest": input_digest,
        "correlation": _text(correlation_id, 128) or request_id,
    }
    connection.execute(
        "INSERT INTO CX_MODEL_REQUESTS(REQUEST_ID,ACTOR_PRINCIPAL_ID,AGENT_ID,PROFILE_ID,MODEL_ID,STATUS,"
        "IDEMPOTENCY_KEY,INPUT_DIGEST,CORRELATION_ID,CREDENTIAL_ID) "
        "VALUES(:id,:actor,:agent,:profile,:model,'AUTHORIZED',:key,:digest,:correlation,NULL)",
        request_params,
    )
    try:
        quota = model_governance_api.reserve_quota(
            request_id, actor, "", actor, str(profile.get("profile_id") or ""), model_id,
        )
    except model_governance_api.QuotaExceeded:
        connection.execute(
            "UPDATE CX_MODEL_REQUESTS SET STATUS='QUOTA_REJECTED',ERROR_CATEGORY='QUOTA_EXCEEDED',"
            "COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id},
        )
        identity_api._audit(actor, "EMBEDDING_GATEWAY_GENERATE", "EMBEDDING_PROFILE",
                            str(profile.get("profile_id") or ""), "DENY", "Embedding quota exceeded")
        raise
    except Exception:
        connection.execute(
            "UPDATE CX_MODEL_REQUESTS SET STATUS='FAILED',ERROR_CATEGORY='QUOTA_EVALUATION_FAILED',"
            "COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id", {"id": request_id},
        )
        identity_api._audit(actor, "EMBEDDING_GATEWAY_GENERATE", "EMBEDDING_PROFILE",
                            str(profile.get("profile_id") or ""), "DENY", "Embedding quota evaluation failed")
        raise

    headers = {"Content-Type": "application/json"}
    api_key = _profile_api_key(profile)
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(
        _endpoint_url(str(profile.get("provider_url") or "")),
        data=json.dumps({"model": model_id, "input": inputs if len(inputs) > 1 else inputs[0]},
                        ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise EmbeddingGovernanceError("Embedding provider response exceeded the configured limit")
        payload = json.loads(raw.decode("utf-8"))
        data = payload.get("data")
        dimension = int(contract.get("dimension") or 0)
        if not isinstance(data, list) or len(data) != len(inputs):
            raise EmbeddingGovernanceError("Embedding provider returned an invalid batch")
        vectors: List[List[float]] = []
        for item in data:
            vector = (item or {}).get("embedding") if isinstance(item, dict) else None
            if (not isinstance(vector, list) or len(vector) != dimension
                    or not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector)):
                raise EmbeddingGovernanceError("Embedding provider returned an invalid vector")
            normalized = [float(value) for value in vector]
            if str(profile.get("normalize_vectors") or "Y").upper() == "Y":
                norm = math.sqrt(sum(value * value for value in normalized))
                if norm <= 0:
                    raise EmbeddingGovernanceError("Embedding provider returned a zero vector")
                normalized = [value / norm for value in normalized]
            vectors.append(normalized)
        provider_usage = payload.get("usage") or {}
        usage = model_usage_api._usage({"usage": provider_usage})
        usage_record = model_usage_api._write_usage(
            request_id, actor, actor, profile_key or "embedding", model_id, usage,
            "PROVIDER_REPORTED" if usage.get("total_tokens") is not None else "INCOMPLETE",
            started, "SUCCEEDED", key,
        )
        connection.execute(
            "UPDATE CX_MODEL_REQUESTS SET STATUS='SUCCEEDED',COMPLETED_AT=CURRENT_TIMESTAMP "
            "WHERE REQUEST_ID=:id", {"id": request_id},
        )
        identity_api._audit(actor, "EMBEDDING_GATEWAY_GENERATE", "EMBEDDING_PROFILE",
                            str(profile.get("profile_id") or ""), "ALLOW", "Governed Agent Embedding request")
        return {
            "object": "list",
            "data": [{"object": "embedding", "index": index, "embedding": vector}
                     for index, vector in enumerate(vectors)],
            "model": model_id,
            "usage": {
                "prompt_tokens": usage_record.get("prompt_tokens"),
                "total_tokens": usage_record.get("total_tokens"),
            },
            "request_id": request_id,
            "contract_id": str(contract.get("contract_id") or ""),
            "space_id": str(space.get("space_id") or ""),
            "quota_warnings": quota.get("warnings") or [],
        }
    except Exception:
        model_governance_api.release_quota(request_id)
        connection.execute(
            "UPDATE CX_MODEL_REQUESTS SET STATUS='FAILED',ERROR_CATEGORY='EMBEDDING_PROVIDER_FAILED',"
            "COMPLETED_AT=CURRENT_TIMESTAMP WHERE REQUEST_ID=:id AND STATUS<>'SUCCEEDED'", {"id": request_id},
        )
        identity_api._audit(actor, "EMBEDDING_GATEWAY_GENERATE", "EMBEDDING_PROFILE",
                            str(profile.get("profile_id") or ""), "DENY", "Governed Agent Embedding request failed")
        raise


def validate_vector_write(agent_id: str, vector: List[float], *, space_id: str,
                          profile_id: str, contract_id: str, source_mode: str) -> Dict[str, Any]:
    if not isinstance(vector, list) or not vector or not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in vector):
        raise EmbeddingGovernanceError("Embedding vector is invalid")
    effective = effective_binding(agent_id)
    profile = effective.get("profile") or _profile_row(profile_id)
    space = effective.get("space") or _space_row(space_id)
    contract = effective.get("contract") or _contract_row(contract_id)
    if not profile or not space or not contract:
        raise EmbeddingGovernanceError("Embedding Contract is not configured for this Agent")
    if str(space.get("space_id") or "") != space_id or str(profile.get("profile_id") or "") != profile_id or str(contract.get("contract_id") or "") != contract_id:
        raise EmbeddingConflict("submitted Embedding Contract does not match the effective binding")
    if str(space.get("write_enabled") or "N") != "Y" or str(space.get("validation_state") or "") not in {"VERIFIED", "AGENT_VERIFIED", "GATEWAY_VERIFIED"}:
        raise EmbeddingGovernanceError("Embedding Space is not writable")
    if int(contract.get("dimension") or 0) != len(vector):
        raise EmbeddingConflict("Embedding vector dimension does not match the Contract")
    mode = _validated_mode(source_mode)
    if mode != _validated_mode(profile.get("execution_mode")):
        raise EmbeddingConflict("Embedding source mode does not match the Profile")
    return {"profile": profile, "space": space, "contract": contract}


def enqueue_job(actor: str, *, job_kind: str, target_space_id: str, reason: str,
                source_space_id: str = "", input_data: Optional[Dict[str, Any]] = None,
                idempotency_key: str = "") -> Dict[str, Any]:
    kind = _text(job_kind, 32).upper()
    if kind not in {"INGEST", "REEMBED", "VERIFY"} or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("job kind and reason are required")
    target = _space_row(target_space_id)
    if not target:
        raise EmbeddingGovernanceError("target Embedding Space is unavailable")
    key = _text(idempotency_key, 128) or _digest({"kind": kind, "target": target_space_id, "input": input_data or {}})[:64]
    def work(tx: Any) -> Dict[str, Any]:
        existing = _row(tx.query_one("SELECT JOB_ID,STATUS FROM CX_EMBEDDING_JOBS WHERE IDEMPOTENCY_KEY=:key FOR UPDATE", {"key": key}))
        if existing:
            return {"job_id": existing["job_id"], "status": existing["status"], "idempotent": True}
        job_id = _id("EJ")
        tx.execute(
            "INSERT INTO CX_EMBEDDING_JOBS(JOB_ID,JOB_KIND,SOURCE_SPACE_ID,TARGET_SPACE_ID,STATUS,REQUESTED_BY,REASON,"
            "IDEMPOTENCY_KEY,INPUT_JSON) VALUES (:id,:kind,:source,:target,'PENDING',:actor,:reason,:key,:input)",
            {"id": job_id, "kind": kind, "source": source_space_id or None, "target": target_space_id,
             "actor": actor, "reason": _text(reason, 2000), "key": key, "input": _json(input_data or {})},
        )
        _audit(tx, actor, "EMBEDDING_JOB_ENQUEUE", "EMBEDDING_JOB", job_id, "ALLOW", reason)
        return {"job_id": job_id, "status": "PENDING", "idempotent": False}
    return connection.execute_transaction_callback(work)


def list_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT JOB_ID,JOB_KIND,SOURCE_SPACE_ID,TARGET_SPACE_ID,STATUS,REQUESTED_BY,REASON,IDEMPOTENCY_KEY,"
        "WORKER_ID,LEASE_EXPIRES_AT,FENCING_TOKEN,CREATED_AT,UPDATED_AT,COMPLETED_AT "
        "FROM CX_EMBEDDING_JOBS ORDER BY CREATED_AT DESC" + suffix, params,
    ))
    return rows


def _job_lease_sql() -> str:
    return "CURRENT_TIMESTAMP + INTERVAL '5 minutes'" if _dialect() in {"pg", "postgresql"} else "CURRENT_TIMESTAMP + INTERVAL '5' MINUTE"


def claim_jobs(worker_id: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    worker = _text(worker_id, 128)
    if not worker:
        raise EmbeddingGovernanceError("worker identity is required")
    suffix, params = _limit(limit)
    rows = _rows(connection.execute_query(
        "SELECT JOB_ID,FENCING_TOKEN FROM CX_EMBEDDING_JOBS WHERE STATUS='PENDING' OR "
        "(STATUS='CLAIMED' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP) ORDER BY CREATED_AT" + suffix, params,
    ))
    claimed: List[Dict[str, Any]] = []
    for row in rows:
        job_id = str(row.get("job_id") or "")
        changed = connection.execute(
            "UPDATE CX_EMBEDDING_JOBS SET STATUS='CLAIMED',WORKER_ID=:worker,LEASE_EXPIRES_AT=" + _job_lease_sql() + ","
            "FENCING_TOKEN=FENCING_TOKEN+1,UPDATED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:id AND "
            "(STATUS='PENDING' OR (STATUS='CLAIMED' AND LEASE_EXPIRES_AT<=CURRENT_TIMESTAMP))",
            {"worker": worker, "id": job_id},
        )
        if changed:
            current = _row(connection.execute_query_one(
                "SELECT JOB_ID,JOB_KIND,SOURCE_SPACE_ID,TARGET_SPACE_ID,INPUT_JSON,FENCING_TOKEN FROM CX_EMBEDDING_JOBS "
                "WHERE JOB_ID=:id AND WORKER_ID=:worker AND STATUS='CLAIMED'", {"id": job_id, "worker": worker},
            ))
            if current:
                current["input"] = _parse(current.pop("input_json", "{}"), {})
                claimed.append(current)
    return claimed


def complete_job(actor: str, job_id: str, fencing_token: int, *, result: Optional[Dict[str, Any]] = None,
                 error: str = "") -> Dict[str, Any]:
    identifier = _text(job_id, 128)
    if not identifier:
        raise EmbeddingGovernanceError("job identity is required")
    outcome = "FAILED" if error else "COMPLETED"
    def work(tx: Any) -> Dict[str, Any]:
        job = _row(tx.query_one(
            "SELECT JOB_ID,STATUS,FENCING_TOKEN,WORKER_ID FROM CX_EMBEDDING_JOBS WHERE JOB_ID=:id FOR UPDATE",
            {"id": identifier},
        ))
        if not job or str(job.get("status") or "") != "CLAIMED":
            raise EmbeddingConflict("Embedding Job is not claimed")
        if int(job.get("fencing_token") or 0) != int(fencing_token):
            raise EmbeddingConflict("Embedding Job lease is stale")
        tx.execute(
            "UPDATE CX_EMBEDDING_JOBS SET STATUS=:status,RESULT_JSON=:result,LEASE_EXPIRES_AT=NULL,"
            "UPDATED_AT=CURRENT_TIMESTAMP,COMPLETED_AT=CURRENT_TIMESTAMP WHERE JOB_ID=:id AND FENCING_TOKEN=:token",
            {"status": outcome, "result": _json(_safe_result(result, error)), "id": identifier, "token": int(fencing_token)},
        )
        _audit(tx, actor, "EMBEDDING_JOB_COMPLETE", "EMBEDDING_JOB", identifier,
               "ALLOW" if not error else "DENY", "worker completion" if not error else _text(error, 2000))
        return {"job_id": identifier, "status": outcome}
    return connection.execute_transaction_callback(work)


def _managed_vector_expression() -> str:
    """Return the adapter expression for an already validated JSON vector."""
    return "CAST(:vec AS vector)" if _dialect() in {"pg", "postgresql"} else "TO_VECTOR(:vec)"


def _managed_write(profile: Dict[str, Any], space: Dict[str, Any], contract: Dict[str, Any],
                   entity_id: str, entity_type: str, content: str, vector: List[float]) -> None:
    """Write one Worker-generated vector into its explicitly leased Space.

    This is deliberately separate from interactive Agent writes.  A job is
    created through an audited management mutation, then fenced by
    ``claim_jobs`` before reaching this function; it cannot borrow the
    platform default binding or cross into another Space.
    """
    if len(vector) != int(contract.get("dimension") or 0):
        raise EmbeddingConflict("managed Embedding response dimension does not match the Contract")
    if not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in vector):
        raise EmbeddingGovernanceError("managed Embedding response is invalid")
    params = {
        "entity_id": entity_id, "entity_type": entity_type,
        "space_id": str(space["space_id"]), "profile_id": str(profile["profile_id"]),
        "contract_id": str(contract["contract_id"]), "model": str(profile.get("model_id") or ""),
        "dimension": len(vector), "digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "source_mode": str(profile.get("execution_mode") or ""), "vec": json.dumps(vector),
    }
    exists = connection.execute_query_one(
        "SELECT COUNT(*) AS C FROM ENTITY_EMBEDDINGS WHERE ENTITY_ID=:entity_id AND ENTITY_TYPE=:entity_type "
        "AND EMBEDDING_SPACE_ID=:space_id",
        {"entity_id": params["entity_id"], "entity_type": params["entity_type"], "space_id": params["space_id"]},
    )
    count = int((_row(exists) or {}).get("c") or 0)
    expression = _managed_vector_expression()
    if count:
        connection.execute(
            "UPDATE ENTITY_EMBEDDINGS SET EMBEDDING=" + expression + ",EMBEDDING_MODEL=:model,EMBEDDING_DIM=:dimension,"
            "EMBEDDING_PROFILE_ID=:profile_id,EMBEDDING_CONTRACT_ID=:contract_id,CONTENT_DIGEST=:digest,"
            "SOURCE_MODE=:source_mode,VALIDATION_STATUS='VERIFIED' WHERE ENTITY_ID=:entity_id AND ENTITY_TYPE=:entity_type "
            "AND EMBEDDING_SPACE_ID=:space_id", params,
        )
        return
    connection.execute(
        "INSERT INTO ENTITY_EMBEDDINGS(ENTITY_ID,ENTITY_TYPE,EMBEDDING_SPACE_ID,EMBEDDING_PROFILE_ID,"
        "EMBEDDING_CONTRACT_ID,CONTENT_DIGEST,SOURCE_MODE,VALIDATION_STATUS,EMBEDDING,EMBEDDING_MODEL,EMBEDDING_DIM,CREATED_AT) "
        "VALUES (:entity_id,:entity_type,:space_id,:profile_id,:contract_id,:digest,:source_mode,'VERIFIED'," + expression + ",:model,:dimension,CURRENT_TIMESTAMP)",
        params,
    )


def _managed_job_candidates(input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load a bounded, explicit candidate set for a managed ingestion job."""
    entity_type = _text(input_data.get("entity_type") or "MEMORY", 32).upper()
    try:
        limit = max(1, min(int(input_data.get("limit") or 100), 500))
    except (TypeError, ValueError):
        raise EmbeddingGovernanceError("managed job limit is invalid") from None
    requested = input_data.get("entity_ids") or []
    if requested and (not isinstance(requested, list) or len(requested) > 500):
        raise EmbeddingGovernanceError("managed job entity_ids must contain at most 500 values")
    params: Dict[str, Any] = {"entity_type": entity_type, "limit": limit}
    where = "ENTITY_TYPE=:entity_type"
    if requested:
        # This code owns the package SQL and expands only positional binds,
        # never text from a model or browser request.
        names = []
        for index, value in enumerate(requested):
            name = f"entity_{index}"
            names.append(":" + name)
            params[name] = _text(value, 128)
        where += " AND ENTITY_ID IN (" + ",".join(names) + ")"
    suffix, limit_params = _limit(limit)
    params.update(limit_params)
    rows = connection.execute_query(
        "SELECT ENTITY_ID,ENTITY_TYPE,TITLE,CONTENT FROM ENTITIES WHERE " + where + " ORDER BY CREATED_AT DESC" + suffix,
        params,
    )
    return _rows(rows)


def list_access_grants(limit: int = 200) -> List[Dict[str, Any]]:
    suffix, params = _limit(limit)
    return _rows(connection.execute_query(
        "SELECT GRANT_ID,GRANT_KEY,SUBJECT_TYPE,SUBJECT_ID,EFFECT,ALLOWED_PROFILE_ID,MAX_BATCH_SIZE,"
        "MAX_INPUT_CHARS,VALID_FROM,VALID_UNTIL,STATUS,VERSION,APPROVED_BY,REASON,CREATED_AT,UPDATED_AT "
        "FROM CX_EMBEDDING_ACCESS_GRANTS ORDER BY UPDATED_AT DESC" + suffix, params,
    ))


def _grant_subject_exists(subject_type: str, subject_id: str, tx: Any) -> bool:
    queries = {
        "AGENT": ("SELECT PRINCIPAL_ID FROM CX_PRINCIPALS WHERE PRINCIPAL_ID=:id AND PRINCIPAL_TYPE='AGENT' AND STATUS='ACTIVE'", {}),
        "TEMPLATE": ("SELECT TEMPLATE_ID FROM CX_AGENT_TEMPLATES WHERE TEMPLATE_ID=:id AND STATUS='PUBLISHED'", {}),
        "ORGANIZATION": ("SELECT ORGANIZATION_ID FROM CX_ORGANIZATIONS WHERE ORGANIZATION_ID=:id AND STATUS='ACTIVE'", {}),
        "SECURITY_DOMAIN": ("SELECT SECURITY_DOMAIN_ID FROM CX_SECURITY_DOMAINS WHERE SECURITY_DOMAIN_ID=:id AND STATUS='ACTIVE'", {}),
    }
    sql, params = queries[subject_type]
    params["id"] = subject_id
    return bool(_row(tx.query_one(sql, params)))


def _revoke_subject_tokens(tx: Any, subject_type: str, subject_id: str) -> None:
    predicates = {
        "AGENT": "AGENT_ID=:subject",
        "TEMPLATE": "AGENT_ID IN (SELECT AGENT_ID FROM CX_NATIVE_AGENTS WHERE TEMPLATE_ID=:subject)",
        "SECURITY_DOMAIN": "AGENT_ID IN (SELECT PRINCIPAL_ID FROM CX_DOMAIN_MEMBERS WHERE SECURITY_DOMAIN_ID=:subject AND STATUS='ACTIVE')",
        "ORGANIZATION": (
            "(AGENT_ID IN (SELECT PRINCIPAL_ID FROM CX_ORGANIZATION_MEMBERS WHERE ORGANIZATION_ID=:subject AND STATUS='ACTIVE') "
            "OR AGENT_ID IN (SELECT ar.AGENT_ID FROM CX_AGENT_RELATIONSHIPS ar JOIN CX_ORGANIZATION_MEMBERS om "
            "ON om.PRINCIPAL_ID=ar.PRINCIPAL_ID AND om.STATUS='ACTIVE' WHERE om.ORGANIZATION_ID=:subject "
            "AND ar.STATUS='ACTIVE'))"
        ),
    }
    tx.execute(
        "UPDATE CX_AGENT_ACCESS_TOKENS SET REVOKED_AT=CURRENT_TIMESTAMP WHERE REVOKED_AT IS NULL AND "
        + predicates[subject_type], {"subject": subject_id},
    )


def upsert_access_grant(actor: str, *, subject_type: str, subject_id: str, effect: str,
                        allowed_profile_id: str = "", max_batch_size: int = 1,
                        max_input_chars: int = 16000, valid_from: Any = None,
                        valid_until: Any = None, reason: str = "") -> Dict[str, Any]:
    subject_type = _text(subject_type, 32).upper()
    subject_id = _text(subject_id, 128)
    effect = _text(effect, 16).upper()
    profile_id = _text(allowed_profile_id, 128)
    if subject_type not in {"AGENT", "TEMPLATE", "ORGANIZATION", "SECURITY_DOMAIN"}:
        raise EmbeddingGovernanceError("Embedding grant subject type is invalid")
    if not subject_id or effect not in {"ALLOW", "DENY"} or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("Embedding grant subject, effect, and reason are required")
    try:
        batch_limit = int(max_batch_size)
        char_limit = int(max_input_chars)
    except (TypeError, ValueError) as exc:
        raise EmbeddingGovernanceError("Embedding grant limits are invalid") from exc
    if batch_limit < 1 or batch_limit > 16 or char_limit < 1 or char_limit > 64000:
        raise EmbeddingGovernanceError("Embedding grant limits are outside the supported range")
    valid_from = _optional_timestamp(valid_from)
    valid_until = _optional_timestamp(valid_until)
    if valid_from and valid_until and valid_until <= valid_from:
        raise EmbeddingGovernanceError("Embedding grant expiry must be later than its start time")
    grant_key = _digest({"subject_type": subject_type, "subject_id": subject_id, "profile_id": profile_id or "*"})[:64]

    def work(tx: Any) -> Dict[str, Any]:
        if not _grant_subject_exists(subject_type, subject_id, tx):
            raise EmbeddingGovernanceError("Embedding grant subject is unavailable")
        if profile_id and not _row(tx.query_one(
            "SELECT PROFILE_ID FROM CX_EMBEDDING_PROFILES WHERE PROFILE_ID=:id AND STATUS='ACTIVE'", {"id": profile_id},
        )):
            raise EmbeddingGovernanceError("Embedding grant Profile is unavailable")
        existing = _row(tx.query_one(
            "SELECT GRANT_ID,VERSION FROM CX_EMBEDDING_ACCESS_GRANTS WHERE GRANT_KEY=:key FOR UPDATE", {"key": grant_key},
        ))
        grant_id = str((existing or {}).get("grant_id") or _id("EAG"))
        version = int((existing or {}).get("version") or 0) + 1
        params = {
            "id": grant_id, "key": grant_key, "subject_type": subject_type, "subject_id": subject_id,
            "effect": effect, "profile": profile_id or None, "batch": batch_limit, "chars": char_limit,
            "valid_from": valid_from or None, "valid_until": valid_until or None,
            "version": version, "actor": actor, "reason": _text(reason, 2000),
        }
        if existing:
            tx.execute(
                "UPDATE CX_EMBEDDING_ACCESS_GRANTS SET EFFECT=:effect,ALLOWED_PROFILE_ID=:profile,"
                "MAX_BATCH_SIZE=:batch,MAX_INPUT_CHARS=:chars,VALID_FROM=:valid_from,VALID_UNTIL=:valid_until,"
                "STATUS='ACTIVE',VERSION=:version,APPROVED_BY=:actor,REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP "
                "WHERE GRANT_ID=:id", {key: params[key] for key in (
                    "effect", "profile", "batch", "chars", "valid_from", "valid_until", "version", "actor", "reason", "id")},
            )
        else:
            tx.execute(
                "INSERT INTO CX_EMBEDDING_ACCESS_GRANTS(GRANT_ID,GRANT_KEY,SUBJECT_TYPE,SUBJECT_ID,EFFECT,"
                "ALLOWED_PROFILE_ID,MAX_BATCH_SIZE,MAX_INPUT_CHARS,VALID_FROM,VALID_UNTIL,STATUS,VERSION,APPROVED_BY,REASON) "
                "VALUES(:id,:key,:subject_type,:subject_id,:effect,:profile,:batch,:chars,:valid_from,:valid_until,"
                "'ACTIVE',:version,:actor,:reason)", params,
            )
        _revoke_subject_tokens(tx, subject_type, subject_id)
        _audit(tx, actor, "EMBEDDING_ACCESS_GRANT_UPSERT", "EMBEDDING_ACCESS_GRANT", grant_id, "ALLOW", reason)
        return {"grant_id": grant_id, "grant_key": grant_key, "version": version, "status": "ACTIVE",
                "subject_type": subject_type, "subject_id": subject_id, "effect": effect,
                "allowed_profile_id": profile_id or None, "max_batch_size": batch_limit,
                "max_input_chars": char_limit}
    return connection.execute_transaction_callback(work)


def revoke_access_grant(actor: str, grant_id: str, reason: str) -> Dict[str, Any]:
    identifier = _text(grant_id, 128)
    if not identifier or len(_text(reason, 2000)) < 3:
        raise EmbeddingGovernanceError("Embedding grant and reason are required")

    def work(tx: Any) -> Dict[str, Any]:
        grant = _row(tx.query_one(
            "SELECT GRANT_ID,SUBJECT_TYPE,SUBJECT_ID,STATUS,VERSION FROM CX_EMBEDDING_ACCESS_GRANTS "
            "WHERE GRANT_ID=:id FOR UPDATE", {"id": identifier},
        ))
        if not grant:
            raise EmbeddingGovernanceError("Embedding access grant is unavailable")
        if str(grant.get("status") or "").upper() != "REVOKED":
            tx.execute(
                "UPDATE CX_EMBEDDING_ACCESS_GRANTS SET STATUS='REVOKED',VERSION=VERSION+1,APPROVED_BY=:actor,"
                "REASON=:reason,UPDATED_AT=CURRENT_TIMESTAMP WHERE GRANT_ID=:id",
                {"actor": actor, "reason": _text(reason, 2000), "id": identifier},
            )
            _revoke_subject_tokens(tx, str(grant["subject_type"]), str(grant["subject_id"]))
            _audit(tx, actor, "EMBEDDING_ACCESS_GRANT_REVOKE", "EMBEDDING_ACCESS_GRANT", identifier, "ALLOW", reason)
        return {"grant_id": identifier, "status": "REVOKED", "version": int(grant.get("version") or 0) + 1}
    return connection.execute_transaction_callback(work)


def _run_managed_job(worker_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    target = _space_row(str(job.get("target_space_id") or ""))
    if not target or not target.get("contract_id"):
        raise EmbeddingGovernanceError("managed Embedding Job target Space is unavailable")
    contract = _contract_row(str(target["contract_id"]))
    profile = _profile_row(str((contract or {}).get("profile_id") or ""))
    if not contract or not profile:
        raise EmbeddingGovernanceError("managed Embedding Job Contract is unavailable")
    mode = _validated_mode(profile.get("execution_mode"))
    if mode not in {"PLATFORM_MANAGED", "ENTERPRISE_PROXY"}:
        raise EmbeddingGovernanceError("this Embedding mode requires Agent-side or precomputed ingestion")
    if str(target.get("write_enabled") or "N") != "Y" or str(target.get("validation_state") or "") not in {"VERIFIED", "GATEWAY_VERIFIED"}:
        raise EmbeddingGovernanceError("managed Embedding Job target Space is not verified and writable")
    kind = _text(job.get("job_kind"), 32).upper()
    if kind == "VERIFY":
        probe = probe_profile(worker_id, str(profile["profile_id"]), scope="PLATFORM")
        return {"kind": kind, "probe": probe}
    if kind not in {"INGEST", "REEMBED"}:
        raise EmbeddingGovernanceError("managed Embedding Job kind is unsupported")
    from .embedding_api import generate_embedding
    api_key = _profile_api_key(profile)
    completed = 0
    skipped = 0
    for row in _managed_job_candidates(dict(job.get("input") or {})):
        content = ((str(row.get("title") or "") + " " + str(row.get("content") or "")).strip())[:8000]
        if not content:
            skipped += 1
            continue
        vector = generate_embedding(content, api_url=str(profile.get("provider_url") or ""),
                                    model=str(profile.get("model_id") or ""), api_key=api_key)
        _managed_write(profile, target, contract, str(row["entity_id"]), str(row["entity_type"]), content, vector)
        completed += 1
    return {"kind": kind, "space_id": target["space_id"], "processed": completed, "skipped": skipped}


def run_managed_worker(worker_id: str, *, limit: int = 10) -> Dict[str, Any]:
    """Claim and execute a bounded batch outside Dashboard request handling."""
    worker = _text(worker_id, 128)
    claimed = claim_jobs(worker, limit=limit)
    completed = 0
    failed = 0
    details = []
    for job in claimed:
        job_id = str(job.get("job_id") or "")
        try:
            result = _run_managed_job(worker, job)
            complete_job(worker, job_id, int(job.get("fencing_token") or 0), result=result)
            completed += 1
            details.append({"job_id": job_id, "status": "COMPLETED", "result": result})
        except Exception as exc:
            complete_job(worker, job_id, int(job.get("fencing_token") or 0), error=_text(str(exc), 256))
            failed += 1
            details.append({"job_id": job_id, "status": "FAILED", "error": _text(str(exc), 256)})
    return {"worker_id": worker, "claimed": len(claimed), "completed": completed, "failed": failed, "details": details}


def _safe_result(result: Optional[Dict[str, Any]], error: str) -> Dict[str, Any]:
    value = dict(result or {})
    if error:
        value["error"] = _text(error, 256)
    return value


def readiness() -> Dict[str, Any]:
    default = _row(connection.execute_query_one(
        "SELECT SPACE_ID,SPACE_KEY,CONTRACT_ID,STATUS,WRITE_ENABLED,VALIDATION_STATE FROM CX_EMBEDDING_SPACES WHERE IS_DEFAULT='Y'", {},
    ))
    if not default:
        return {"state": "UNCONFIGURED", "vector_ready": False, "platform_deployed": False,
                "reason": "No default Embedding Space"}
    contract = _contract_row(str(default.get("contract_id") or "")) if default.get("contract_id") else None
    profile = _profile_row(str((contract or {}).get("profile_id") or "")) if contract else None
    binding = _row(connection.execute_query_one(
        "SELECT BINDING_ID,PROFILE_ID,SPACE_ID,STATUS FROM CX_EMBEDDING_BINDINGS "
        "WHERE BINDING_SCOPE='PLATFORM' AND BINDING_SUBJECT_ID='DEFAULT' AND STATUS='ACTIVE'", {},
    ))
    deployed = bool(
        contract and binding
        and str(binding.get("profile_id") or "") == str((contract or {}).get("profile_id") or "")
        and str(binding.get("space_id") or "") == str(default.get("space_id") or "")
    )
    state = str(default.get("validation_state") or "UNVERIFIED")
    ready = bool(contract and str(default.get("write_enabled") or "N") == "Y" and state in {"VERIFIED", "AGENT_VERIFIED", "GATEWAY_VERIFIED"})
    return {"state": "READY" if ready else state, "vector_ready": ready, "platform_deployed": deployed,
            "space_id": default.get("space_id"), "space_key": default.get("space_key"),
            "contract_id": (contract or {}).get("contract_id"),
            "profile_key": (profile or {}).get("profile_key"),
            "dimension": (contract or {}).get("dimension")}


def queue_metrics() -> Dict[str, Any]:
    rows = _rows(connection.execute_query(
        "SELECT STATUS,COUNT(*) AS COUNT FROM CX_EMBEDDING_JOBS GROUP BY STATUS", {},
    ))
    counts = {str(row.get("status") or ""): int(row.get("count") or 0) for row in rows}
    return {"counts": counts, "pending": counts.get("PENDING", 0) + counts.get("CLAIMED", 0)}
