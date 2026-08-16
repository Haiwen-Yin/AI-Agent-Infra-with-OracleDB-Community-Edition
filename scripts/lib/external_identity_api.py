"""Provider-neutral external identity transaction boundary.

Vendor SDKs are deliberately outside this module.  This service persists only
bounded transaction metadata and normalized binding evidence; provider claims
cannot grant roles, entry access, or organization membership.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional

from . import connection, identity_api


class ExternalIdentityError(ValueError):
    pass


_PROTOCOLS = {"OIDC", "OAUTH2", "SAML2", "ENTERPRISE_QR"}


def _json_columns() -> tuple[str, str, str, str]:
    if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"}:
        return "ENDPOINTS_JSON", "REDIRECT_ALLOWLIST_JSON", "SCOPES_JSON", "ATTRIBUTE_MAPPING_JSON"
    return "ENDPOINTS_JSON", "REDIRECT_ALLOWLIST", "SCOPES_JSON", "ATTRIBUTE_MAPPING"


def _digest(value: str, purpose: str) -> str:
    return identity_api._secret_digest(value, purpose)


def list_providers(entry: str = "PORTAL") -> list[Dict[str, Any]]:
    entry = str(entry or "PORTAL").upper()
    if entry not in {"PORTAL", "APP"}:
        raise ExternalIdentityError("entry is invalid")
    rows = connection.execute_query(
        "SELECT PROVIDER_ID, PROVIDER_KEY, ADAPTER_TYPE, PROTOCOL_TYPE, TENANT_REFERENCE, "
        "REGISTRATION_POLICY, CAPABILITY_STATUS, STATUS FROM CX_IDENTITY_PROVIDERS "
        "WHERE STATUS = 'ENABLED' ORDER BY PROVIDER_KEY", {},
    )
    return [identity_api._row(row) or {} for row in rows]


def list_provider_configurations(actor_principal_id: str) -> list[Dict[str, Any]]:
    identity_api._require(actor_principal_id, "users.security.manage")
    endpoint_col, redirect_col, scopes_col, mapping_col = _json_columns()
    rows = connection.execute_query(
        "SELECT PROVIDER_ID, PROVIDER_KEY, ADAPTER_TYPE, PROTOCOL_TYPE, ISSUER, TENANT_REFERENCE, "
        f"{endpoint_col} AS ENDPOINTS_JSON, {redirect_col} AS REDIRECT_ALLOWLIST, "
        f"{scopes_col} AS SCOPES_JSON, {mapping_col} AS ATTRIBUTE_MAPPING, "
        "CASE WHEN CREDENTIAL_REFERENCE IS NULL THEN 'N' ELSE 'Y' END AS CREDENTIAL_PRESENT, "
        "REGISTRATION_POLICY, CAPABILITY_STATUS, VERSION, STATUS, UPDATED_BY, UPDATED_AT "
        "FROM CX_IDENTITY_PROVIDERS ORDER BY PROVIDER_KEY", {},
    )
    return [identity_api._row(row) or {} for row in rows]


def save_provider_configuration(actor_principal_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a provider-neutral profile without accepting authority claims.

    Adapter validation is a separate release-evidence operation. Configuration
    alone therefore never changes capability posture to AVAILABLE.
    """
    identity_api._require(actor_principal_id, "users.security.manage")
    provider_key = str(payload.get("provider_key") or "").strip().lower()[:128]
    adapter_type = str(payload.get("adapter_type") or "").strip().upper()[:128]
    protocol = str(payload.get("protocol_type") or "").strip().upper()
    reason = str(payload.get("reason") or "").strip()[:2000]
    if not provider_key or not adapter_type or protocol not in _PROTOCOLS or not reason:
        raise ExternalIdentityError("external identity provider configuration is invalid")
    status = str(payload.get("status") or "DISABLED").upper()
    if status not in {"ENABLED", "DISABLED"}:
        raise ExternalIdentityError("external identity provider configuration is invalid")
    registration_policy = str(payload.get("registration_policy") or "APPROVAL").upper()
    if registration_policy not in {"CLOSED", "APPROVAL", "INVITE_ONLY", "DIRECTORY"}:
        raise ExternalIdentityError("external identity provider configuration is invalid")
    try:
        endpoints = identity_api._json(payload.get("endpoints") or {})
        redirects = identity_api._json(payload.get("redirect_allowlist") or [])
        scopes = identity_api._json(payload.get("scopes") or [])
        mapping = identity_api._json(payload.get("attribute_mapping") or {})
    except (TypeError, ValueError) as exc:
        raise ExternalIdentityError("external identity provider JSON is invalid") from exc
    endpoint_col, redirect_col, scopes_col, mapping_col = _json_columns()
    existing = identity_api._row(connection.execute_query_one(
        "SELECT PROVIDER_ID, VERSION, CAPABILITY_STATUS FROM CX_IDENTITY_PROVIDERS WHERE PROVIDER_KEY = :provider_key",
        {"provider_key": provider_key},
    ))
    expected_version = int(payload.get("expected_version") or 0)
    values = {
        "provider_key": provider_key, "adapter_type": adapter_type, "protocol_type": protocol,
        "issuer": str(payload.get("issuer") or "").strip()[:512] or None,
        "tenant_reference": str(payload.get("tenant_reference") or "").strip()[:256] or None,
        "endpoints": endpoints, "redirects": redirects, "scopes": scopes, "mapping": mapping,
        "credential_reference": str(payload.get("credential_reference") or "").strip()[:256] or None,
        "registration_policy": registration_policy, "status": status,
        "actor": actor_principal_id,
    }
    if existing:
        if expected_version != int(existing.get("version") or 0):
            raise ExternalIdentityError("external identity provider version conflict")
        changed = connection.execute(
            "UPDATE CX_IDENTITY_PROVIDERS SET ADAPTER_TYPE = :adapter_type, PROTOCOL_TYPE = :protocol_type, "
            "ISSUER = :issuer, TENANT_REFERENCE = :tenant_reference, "
            f"{endpoint_col} = :endpoints, {redirect_col} = :redirects, {scopes_col} = :scopes, {mapping_col} = :mapping, "
            "CREDENTIAL_REFERENCE = COALESCE(:credential_reference, CREDENTIAL_REFERENCE), "
            "REGISTRATION_POLICY = :registration_policy, STATUS = :status, VERSION = VERSION + 1, "
            "UPDATED_BY = :actor, UPDATED_AT = CURRENT_TIMESTAMP WHERE PROVIDER_KEY = :provider_key AND VERSION = :expected_version",
            {**values, "expected_version": expected_version},
        )
        if changed != 1:
            raise ExternalIdentityError("external identity provider version conflict")
        provider_id = str(existing["provider_id"])
    else:
        if expected_version != 0:
            raise ExternalIdentityError("external identity provider version conflict")
        provider_id = identity_api._id("IDP")
        connection.execute(
            "INSERT INTO CX_IDENTITY_PROVIDERS(PROVIDER_ID, PROVIDER_KEY, ADAPTER_TYPE, PROTOCOL_TYPE, ISSUER, "
            f"TENANT_REFERENCE, {endpoint_col}, {redirect_col}, {scopes_col}, CREDENTIAL_REFERENCE, {mapping_col}, "
            "REGISTRATION_POLICY, CAPABILITY_STATUS, VERSION, STATUS, UPDATED_BY) VALUES "
            "(:provider_id, :provider_key, :adapter_type, :protocol_type, :issuer, :tenant_reference, :endpoints, "
            ":redirects, :scopes, :credential_reference, :mapping, :registration_policy, 'UNAVAILABLE', 1, :status, :actor)",
            {**values, "provider_id": provider_id},
        )
    identity_api._audit(actor_principal_id, "EXTERNAL_IDENTITY_PROVIDER_SAVE", "IDENTITY_PROVIDER",
                        provider_id, "ALLOW", reason)
    return next(item for item in list_provider_configurations(actor_principal_id) if item["provider_id"] == provider_id)


def provider_test(actor_principal_id: str, provider_id: str, reason: str) -> Dict[str, Any]:
    identity_api._require(actor_principal_id, "users.security.manage")
    if not str(reason or "").strip():
        raise ExternalIdentityError("provider test reason is required")
    row = identity_api._row(connection.execute_query_one(
        "SELECT PROVIDER_ID, ADAPTER_TYPE, CAPABILITY_STATUS, STATUS FROM CX_IDENTITY_PROVIDERS "
        "WHERE PROVIDER_ID = :provider_id", {"provider_id": str(provider_id)[:128]},
    ))
    if not row:
        raise ExternalIdentityError("external identity provider is unavailable")
    # No vendor adapter ships as validated in v4.4.6. Do not turn stored URLs
    # into an SSRF primitive or report a configuration-only profile as usable.
    result = {"provider_id": provider_id, "status": "UNAVAILABLE", "adapter_type": row.get("adapter_type"),
              "message": "A validated provider adapter is not installed"}
    identity_api._audit(actor_principal_id, "EXTERNAL_IDENTITY_PROVIDER_TEST", "IDENTITY_PROVIDER",
                        provider_id, "DENY", reason)
    return result


def delete_provider_configuration(actor_principal_id: str, provider_id: str, reason: str) -> bool:
    identity_api._require(actor_principal_id, "users.security.manage")
    if not str(reason or "").strip():
        raise ExternalIdentityError("provider deletion reason is required")
    binding = identity_api._row(connection.execute_query_one(
        "SELECT BINDING_ID FROM CX_EXTERNAL_ID_BINDINGS WHERE PROVIDER_ID = :provider_id "
        "AND STATUS IN ('ACTIVE','PENDING')", {"provider_id": str(provider_id)[:128]},
    ))
    if binding:
        raise ExternalIdentityError("provider has active identity bindings")
    changed = connection.execute(
        "DELETE FROM CX_IDENTITY_PROVIDERS WHERE PROVIDER_ID = :provider_id AND STATUS = 'DISABLED'",
        {"provider_id": str(provider_id)[:128]},
    )
    if changed != 1:
        raise ExternalIdentityError("provider is unavailable or enabled")
    identity_api._audit(actor_principal_id, "EXTERNAL_IDENTITY_PROVIDER_DELETE", "IDENTITY_PROVIDER",
                        provider_id, "ALLOW", reason)
    return True


def transaction_status(transaction_id: str) -> Dict[str, Any]:
    row = identity_api._row(connection.execute_query_one(
        "SELECT TRANSACTION_ID, PROVIDER_ID, ENTRY, EXPIRES_AT, STATUS, FAILURE_CODE, CONSUMED_AT "
        "FROM CX_EXT_LOGIN_TXNS WHERE TRANSACTION_ID = :transaction_id",
        {"transaction_id": str(transaction_id or "")[:128]},
    ))
    if not row:
        raise ExternalIdentityError("external login transaction is unavailable")
    expiry = identity_api._timestamp(row.get("expires_at"))
    if expiry is not None and expiry <= identity_api._now() and str(row.get("status")) not in {"CONSUMED", "FAILED", "EXPIRED"}:
        connection.execute(
            "UPDATE CX_EXT_LOGIN_TXNS SET STATUS = 'EXPIRED', FAILURE_CODE = 'EXPIRED' "
            "WHERE TRANSACTION_ID = :transaction_id", {"transaction_id": transaction_id},
        )
        row["status"] = "EXPIRED"
        row["failure_code"] = "EXPIRED"
    row["expires_at"] = identity_api._iso(expiry)
    row["consumed_at"] = identity_api._iso(row.get("consumed_at"))
    return row


def start_transaction(provider_id: str, entry: str = "PORTAL", redirect_uri: str = "") -> Dict[str, Any]:
    provider_id = str(provider_id or "").strip()[:128]
    entry = str(entry or "PORTAL").upper()
    if not provider_id or entry not in {"PORTAL", "APP"}:
        raise ExternalIdentityError("external login request is invalid")
    allowlist_column = "REDIRECT_ALLOWLIST_JSON" if str(getattr(connection, "DATABASE_DIALECT", "")).lower() in {"postgresql", "pg"} else "REDIRECT_ALLOWLIST"
    provider = identity_api._row(connection.execute_query_one(
        "SELECT PROVIDER_ID, STATUS, CAPABILITY_STATUS, " + allowlist_column + " AS REDIRECT_ALLOWLIST "
        "FROM CX_IDENTITY_PROVIDERS WHERE PROVIDER_ID = :provider_id", {"provider_id": provider_id},
    ))
    if not provider or str(provider.get("status") or "").upper() != "ENABLED":
        raise ExternalIdentityError("external identity provider is unavailable")
    if str(provider.get("capability_status") or "UNAVAILABLE").upper() != "AVAILABLE":
        raise ExternalIdentityError("external identity provider is unavailable")
    redirect = str(redirect_uri or "").strip()
    allowlist = provider.get("redirect_allowlist") or "[]"
    try:
        allowed = json.loads(allowlist) if isinstance(allowlist, str) else allowlist
    except (TypeError, ValueError) as exc:
        raise ExternalIdentityError("provider redirect policy is invalid") from exc
    if redirect and redirect not in set(str(item) for item in (allowed or [])):
        raise ExternalIdentityError("redirect is not allowed")
    transaction_id = identity_api._id("EXT")
    raw_state = secrets.token_urlsafe(32)
    raw_nonce = secrets.token_urlsafe(32)
    expires = identity_api._now() + timedelta(minutes=5)
    connection.execute(
        "INSERT INTO CX_EXT_LOGIN_TXNS(TRANSACTION_ID, TRANSACTION_DIGEST, PROVIDER_ID, ENTRY, STATE_DIGEST, "
        "NONCE_DIGEST, EXPIRES_AT, STATUS, ATTEMPTS) VALUES (:transaction_id, :transaction_digest, :provider_id, :entry, "
        ":state_digest, :nonce_digest, :expires_at, 'STARTED', 0)",
        {"transaction_id": transaction_id, "transaction_digest": _digest(transaction_id, "external-login-transaction"),
         "provider_id": provider_id, "entry": entry, "state_digest": _digest(raw_state, "external-login-state"),
         "nonce_digest": _digest(raw_nonce, "external-login-nonce"), "expires_at": expires},
    )
    return {"transaction_id": transaction_id, "state": raw_state, "nonce": raw_nonce,
            "expires_at": identity_api._iso(expires), "provider_id": provider_id, "entry": entry}


def validate_callback(transaction_id: str, state: str, nonce: str, callback_digest: str) -> Dict[str, Any]:
    row = identity_api._row(connection.execute_query_one(
        "SELECT TRANSACTION_ID, PROVIDER_ID, ENTRY, STATE_DIGEST, NONCE_DIGEST, EXPIRES_AT, STATUS, ATTEMPTS "
        "FROM CX_EXT_LOGIN_TXNS WHERE TRANSACTION_ID = :transaction_id", {"transaction_id": str(transaction_id)[:128]},
    ))
    if not row or str(row.get("status") or "").upper() not in {"STARTED", "PENDING"}:
        raise ExternalIdentityError("external login transaction is unavailable")
    expiry = identity_api._timestamp(row.get("expires_at"))
    if expiry is None or expiry <= identity_api._now():
        connection.execute("UPDATE CX_EXT_LOGIN_TXNS SET STATUS = 'EXPIRED', FAILURE_CODE = 'EXPIRED' WHERE TRANSACTION_ID = :transaction_id", {"transaction_id": transaction_id})
        raise ExternalIdentityError("external login transaction is expired")
    if not hmac.compare_digest(str(row.get("state_digest") or ""), _digest(state, "external-login-state")):
        raise ExternalIdentityError("external login state is invalid")
    if not hmac.compare_digest(str(row.get("nonce_digest") or ""), _digest(nonce, "external-login-nonce")):
        raise ExternalIdentityError("external login nonce is invalid")
    changed = connection.execute(
        "UPDATE CX_EXT_LOGIN_TXNS SET STATUS = 'CALLBACK_VALIDATED', ATTEMPTS = ATTEMPTS + 1, CALLBACK_DIGEST = :callback_digest "
        "WHERE TRANSACTION_ID = :transaction_id AND STATUS IN ('STARTED','PENDING') AND EXPIRES_AT > CURRENT_TIMESTAMP",
        {"transaction_id": transaction_id, "callback_digest": _digest(str(callback_digest)[:512], "external-login-callback")},
    )
    if changed != 1:
        raise ExternalIdentityError("external login transaction was already consumed")
    return {"transaction_id": transaction_id, "provider_id": row["provider_id"], "entry": row["entry"], "status": "CALLBACK_VALIDATED", "binding_required": True}
