"""Explicit read-only checks and authorized durable execution observations."""
from decimal import Decimal
import json
from . import connection, identity_api, native_runtime, native_agent_api, effective_capabilities
from . import continuity_work as work
from .agent_extension_contracts import row, canonical, digest, identifier


def _json_safe(value):
    """Normalize adapter scalar values before persisting a diagnostic report.

    Oracle and YashanDB drivers may return ``Decimal`` for NUMBER columns,
    including values nested inside a row returned by a diagnostic query.  A
    report is a durable JSON contract, so normalize those values recursively
    while preserving integral revisions as integers and fractional values as
    strings when JSON's binary float would lose precision.
    """
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _capability_metadata(registry):
    """Return the public diagnostic allowlist, excluding release evidence."""
    result = {}
    for key in ("profile_key", "version", "profile_version"):
        if key not in registry:
            continue
        value = registry.get(key)
        if key in {"version", "profile_version"} and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                # Graph capability profiles use semantic version strings;
                # database numeric profile revisions still normalize to int.
                value = str(value)
        result[key] = value
    items = []
    for item in registry.get("items") or []:
        if not isinstance(item, dict):
            continue
        normalized = {}
        for key in ("capability_key", "state", "version", "mandatory"):
            if key not in item:
                continue
            value = item[key]
            # Oracle/YashanDB drivers may expose NUMBER/INTEGER values as
            # Decimal.  Diagnostics are persisted as canonical JSON, so
            # normalize the bounded capability version before serialization.
            if key == "version" and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = str(value)
            normalized[key] = value
        items.append(normalized)
    result["items"] = items
    return result


def progress(actor, execution_id, *, transaction=None):
    execution = native_runtime.get_execution(actor, execution_id, transaction=transaction)
    # Do not make progress inspection a second result/prompt export route.
    execution.pop("output", None)
    execution.pop("input_json", None)
    observation = row(connection.execute_query_one("SELECT QUEUE_MS,PROVIDER_LATENCY_MS,FIRST_TOKEN_MS,CANCELLATION_STATE,FINISH_CODE FROM CX_EXECUTION_OBSERVATIONS WHERE EXECUTION_ID=:execution", {"execution": execution_id}))
    return {"execution": execution, "observation": observation or None,
            "remote_cancellation_confirmed": False, "diagnostic_available": True}


def cancel(actor, execution_id):
    native_runtime.get_execution(actor, execution_id)
    effective_capabilities.authorize(actor, "agents.operate")
    def perform(tx):
        native_runtime.get_execution(actor, execution_id, transaction=tx)
        record = row(tx.query_one("SELECT * FROM CX_RUNTIME_EXECUTIONS WHERE EXECUTION_ID=:execution FOR UPDATE", {"execution": execution_id}))
        if record["status"] not in {"PENDING", "CLAIMED"}:
            return {"execution_id": execution_id, "status": record["status"], "remote_cancellation_confirmed": False}
        state = "LOCAL_CANCELLED" if record["status"] == "PENDING" else "PROVIDER_UNCONFIRMED"
        tx.execute("UPDATE CX_RUNTIME_EXECUTIONS SET STATUS='CANCELLED',FENCING_TOKEN=FENCING_TOKEN+1,OUTPUT_JSON=NULL,FAILURE_REASON=:reason,COMPLETED_AT=CURRENT_TIMESTAMP,UPDATED_AT=CURRENT_TIMESTAMP WHERE EXECUTION_ID=:execution", {"execution": execution_id, "reason": state})
        if not tx.query_one("SELECT EXECUTION_ID FROM CX_EXECUTION_OBSERVATIONS WHERE EXECUTION_ID=:execution", {"execution": execution_id}):
            tx.execute("INSERT INTO CX_EXECUTION_OBSERVATIONS(EXECUTION_ID,FENCING_TOKEN,CANCELLATION_STATE,FINISH_CODE) VALUES(:execution,:fence,:state,'USER_CANCELLED')", {"execution": execution_id, "fence": int(record["fencing_token"]) + 1, "state": state})
        identity_api._audit_tx(tx, actor, "EXECUTION_CANCELLED", "RUNTIME_EXECUTION", execution_id, "ALLOW", state)
        return {"execution_id": execution_id, "status": "CANCELLED", "cancellation_state": state, "remote_cancellation_confirmed": False}
    return connection.execute_transaction_callback(perform)


def run(actor, domain, check_kind, resource_id=""):
    if check_kind not in {"CAPABILITIES", "AGENT", "EXECUTION", "PROVIDER", "INTEGRATION"}:
        raise ValueError("Unsupported read-only diagnostic")
    effective_capabilities.authorize(actor)
    def perform(tx):
        work._authorize(tx, actor, domain, write=False)
        findings, observed = [], {}
        if check_kind == "CAPABILITIES":
            observed = {"graph": _capability_metadata(effective_capabilities.graph_production_profile.list_capabilities()),
                        "model": _capability_metadata(effective_capabilities.model_capability_api.list_capabilities())}
        elif check_kind == "AGENT":
            if not identity_api._agent_visible_to(actor, resource_id):
                raise PermissionError("Agent is outside delegated scope")
            # The requester owns the diagnostic boundary.  Requiring the
            # target Agent itself to hold a Work-space permission incorrectly
            # denied an administrator's read-only diagnostic for an Agent
            # that was visible through delegated scope.
            work._authorize(tx, actor, domain, write=False)
            observed = row(tx.query_one("SELECT STATUS,ACTIVATION_STATE,DEPLOYMENT_TARGET_ID,LLM_PROFILE_ID FROM CX_NATIVE_AGENTS WHERE AGENT_ID=:agent", {"agent": resource_id}))
            if not observed:
                raise ValueError("Native Agent is unavailable")
            if observed.get("status") != "ACTIVE":
                findings.append({"code": "AGENT_INACTIVE"})
            target = row(tx.query_one("SELECT STATUS,TARGET_TYPE FROM CX_DEPLOYMENT_TARGETS WHERE TARGET_ID=:target", {"target": observed.get("deployment_target_id")}))
            profile = row(tx.query_one("SELECT STATUS,HEALTH_STATE,VERSION FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile", {"profile": observed.get("llm_profile_id")}))
            if target.get("status") != "ACTIVE":
                findings.append({"code": "TARGET_UNAVAILABLE"})
            if profile.get("status") != "ACTIVE" or profile.get("health_state") != "HEALTHY":
                findings.append({"code": "MODEL_PROFILE_NOT_HEALTHY"})
            observed = {"agent_status": observed["status"], "target": target, "profile": profile}
        elif check_kind == "EXECUTION":
            observed = progress(actor, resource_id, transaction=tx)
            if observed["execution"].get("status") in {"FAILED", "UNOBSERVED"}:
                findings.append({"code": "EXECUTION_REQUIRES_REVIEW"})
        elif check_kind == "PROVIDER":
            observed = row(tx.query_one("SELECT PROFILE_ID,VERSION,HEALTH_STATE,STATUS FROM CX_LLM_PROVIDER_PROFILES WHERE PROFILE_ID=:profile", {"profile": resource_id}))
            if not observed:
                raise ValueError("Provider Profile unavailable")
            if observed.get("health_state") != "HEALTHY":
                findings.append({"code": "MODEL_PROFILE_NOT_HEALTHY"})
        else:
            from .registered_protocols import endpoint
            record = endpoint(actor, resource_id, tx=tx)
            if record["security_domain_id"] != domain:
                raise PermissionError("Integration domain differs from diagnostic request")
            observed = {key: record[key] for key in ("endpoint_id", "protocol_kind", "current_revision", "version", "status")}
        report = _json_safe({"check_kind": check_kind, "resource_id": resource_id or None, "findings": findings,
                             "observed": observed, "repair_executed": False, "network_probe_executed": False})
        diagnostic = identifier("DG")
        status = "FINDINGS" if findings else "HEALTHY"
        tx.execute("INSERT INTO CX_AGENT_DIAGNOSTICS(DIAGNOSTIC_ID,ACTOR_ID,SECURITY_DOMAIN_ID,CHECK_KIND,RESOURCE_ID,STATUS,RESULT_JSON,RESULT_DIGEST) VALUES(:diagnostic,:actor,:domain,:kind,:resource_id,:state,:result,:digest)", {"diagnostic": diagnostic, "actor": actor, "domain": domain, "kind": check_kind, "resource_id": resource_id or None, "state": status, "result": canonical(report), "digest": digest(report)})
        identity_api._audit_tx(tx, actor, "READONLY_DIAGNOSTIC", "AGENT_DIAGNOSTIC", diagnostic, "ALLOW", check_kind)
        return {"diagnostic_id": diagnostic, "status": status, **report}
    return connection.execute_transaction_callback(perform)
