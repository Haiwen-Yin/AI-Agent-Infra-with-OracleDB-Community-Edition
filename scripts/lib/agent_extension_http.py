"""Authenticated product HTTP entry points for selected Agent extensions."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from contextlib import nullcontext
from jsonschema.exceptions import ValidationError, SchemaError

from . import provider_capability_probes
from . import agent_directory, context_derivations, graph_inspection, registered_protocols, managed_inputs, agent_diagnostics, answer_evaluation
from . import telemetry_delivery
from .agent_extension_contracts import bounded_json
from .cursor_pagination import normalize_page_size


class ProviderProbeBody(BaseModel):
    capability: str = Field(max_length=64)
    parameters: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=60)


class ProviderParameterBody(BaseModel):
    probe_id: str = Field(min_length=1, max_length=128)
    parameters: dict


class BoundedBody(BaseModel):
    value: dict


class VersionBody(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(default="Requested by the owner", min_length=3, max_length=2000)


class ManagedInputBody(BaseModel):
    security_domain_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=256)
    media_type: str = Field(max_length=128)
    content_base64: str = Field(min_length=1, max_length=5592408)


class InputQuestion(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)


class FrameworkExecutionBody(BaseModel):
    security_domain_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    messages: list[dict]
    idempotency_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=2000)


class AnswerEvalCaseBody(BaseModel):
    case_id: str = Field(min_length=1, max_length=128)
    query_text: str = Field(min_length=1, max_length=2000)
    expected_mode: str = Field(min_length=1, max_length=32)
    expected_entity_ids: list[str] = Field(default_factory=list, max_length=32)
    reason: str = Field(default='Approved answer-quality case', min_length=3, max_length=2000)


class AnswerEvalResultBody(BaseModel):
    case_id: str
    case_version: int = Field(ge=1)
    profile_id: str
    profile_version: int = Field(ge=1)
    entry_kind: str
    observed_mode: str
    passed: bool
    latency_ms: int = Field(ge=0, le=3600000)
    policy_digest: str = Field(min_length=1, max_length=128)
    detail: dict = Field(default_factory=dict)


def install(app, require_action, schema_owner_context=nullcontext, *, prefix="/api"):
    from .edition_features import AGENT_EXTENSIONS_ENABLED
    if not AGENT_EXTENSIONS_ENABLED:
        return
    router = APIRouter()
    def invoke(operation, session, *args, **kwargs):
        try:
            from .continuity_bindings import authenticated_transport
            with schema_owner_context(), authenticated_transport(session.get("continuity_transport")):
                return operation(str(session["principal_id"]), *args, **kwargs)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValidationError, SchemaError, KeyError) as exc:
            raise HTTPException(status_code=422, detail="Integration request failed its data contract") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Agent integration service is unavailable") from exc

    @router.get(prefix + "/llm-provider-profiles/{profile_id}/capability-probes")
    def provider_probes(profile_id: str, session=Depends(require_action("platform.manage"))):
        return invoke(provider_capability_probes.list_probes, session, profile_id)

    @router.post(prefix + "/llm-provider-profiles/{profile_id}/capability-probes")
    def provider_probe(profile_id: str, body: ProviderProbeBody, session=Depends(require_action("platform.manage"))):
        return invoke(provider_capability_probes.probe, session, profile_id, body.capability,
                      body.parameters, timeout=body.timeout_seconds)

    @router.post(prefix + "/llm-provider-profiles/{profile_id}/parameter-contracts")
    def provider_parameter_contract(profile_id: str, body: ProviderParameterBody, session=Depends(require_action("platform.manage"))):
        return invoke(provider_capability_probes.approve_parameters, session, profile_id, body.probe_id, body.parameters)

    root = prefix + "/agent-extensions"

    @router.get(root + "/directory")
    def directory(security_domain_id: str, family: str, query: str = "", after: str = "", limit: int = Query(20, ge=1, le=50), session=Depends(require_action("workspaces.read"))):
        return invoke(agent_directory.search, session, security_domain_id, family, query, after=after, limit=limit)

    @router.get(root + "/answer-evaluation/cases")
    def answer_eval_cases(include_retired: bool = False, limit: int = Query(100, ge=1, le=100), session=Depends(require_action("platform.manage"))):
        return invoke(answer_evaluation.list_cases, session, include_retired=include_retired, limit=limit)

    @router.post(root + "/answer-evaluation/cases")
    def answer_eval_case(body: AnswerEvalCaseBody, session=Depends(require_action("platform.manage"))):
        return invoke(answer_evaluation.register_case, session, body.case_id, body.query_text,
                      body.expected_mode, body.expected_entity_ids, reason=body.reason)

    @router.post(root + "/answer-evaluation/results")
    def answer_eval_result(body: AnswerEvalResultBody, session=Depends(require_action("platform.manage"))):
        return invoke(answer_evaluation.record_result, session, body.case_id, body.case_version,
                      body.profile_id, body.profile_version, body.entry_kind, body.observed_mode,
                      body.passed, body.latency_ms, body.policy_digest, body.detail)

    @router.post(root + "/directory/load")
    def directory_load(body: BoundedBody, session=Depends(require_action("workspaces.read"))):
        value = bounded_json(body.value)
        return invoke(agent_directory.load, session, value["security_domain_id"], value["family"], value["entity_id"], value["version"], value["content_digest"])

    @router.post(root + "/context/derive")
    def derive(body: BoundedBody, session=Depends(require_action("workspaces.read"))):
        return invoke(context_derivations.derive, session, body.value["assembly_id"], body.value["token_budget"])

    @router.get(root + "/context/derivations/{derivation_id}")
    def read_derivation(derivation_id: str, session=Depends(require_action("workspaces.read"))):
        return invoke(context_derivations.read, session, derivation_id)

    @router.post(root + "/context/budget")
    def context_budget(body: BoundedBody, session=Depends(require_action("workspaces.read"))):
        return invoke(lambda actor: context_derivations.budget_plan(**body.value), session)

    @router.get(root + "/graph/slo")
    def slo(limit: int = Query(20, ge=1, le=100), cursor: str = "", status: str = "", session=Depends(require_action("platform.manage"))):
        # Cursor-backed inventories use one shared page contract.  Normalize
        # here as well as in the service so HTTP clients receive the same
        # 20/50/100 boundary as every other SLO reader.
        return invoke(graph_inspection.slo_report, session, page_size=normalize_page_size(limit), cursor=cursor, status=status)

    @router.post(root + "/graph/import-preview")
    def import_preview(body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(graph_inspection.manifest_preview, session, body.value["document"], body.value.get("target_graph_id"))

    @router.post(root + "/graph/import")
    def import_draft(body: BoundedBody, session=Depends(require_action("platform.manage"))):
        value = body.value
        return invoke(graph_inspection.import_draft, session, value["document"], value["preview_digest"], value.get("target_graph_id"), value.get("reason", "Authorized draft import"))

    @router.post(root + "/graph/runs/{run_id}/offline-replay")
    def offline_replay(run_id: str, session=Depends(require_action("platform.manage"))):
        return invoke(graph_inspection.offline_replay, session, run_id)

    @router.post(root + "/graph/runs/{run_id}/migration-preflight")
    def migration_preflight(run_id: str, body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(graph_inspection.migration_preflight, session, run_id, body.value["target_version_id"], body.value.get("mapping", {}))

    @router.post(root + "/graph/runs/{run_id}/fork")
    def fork(run_id: str, body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(graph_inspection.checkpoint_fork, session, run_id, body.value["checkpoint_id"], body.value["idempotency_key"], body.value["reason"])

    @router.post(root + "/graph/runs/{run_id}/resume")
    def resume_graph(run_id: str, body: BoundedBody, session=Depends(require_action("agents.operate"))):
        def operation(actor):
            effective_capabilities.require(actor, graph="graph_checkpoint_fork", action="agents.operate", approved_binding=True)
            from . import graph_runtime
            return {"run_id": run_id, "resumed": graph_runtime.resume_run(run_id, actor, body.value["reason"], body.value.get("resolution"))}
        from . import effective_capabilities
        return invoke(operation, session)

    @router.get(root + "/integrations")
    def integrations(security_domain_id: str, kind: str = "", session=Depends(require_action("workspaces.read"))):
        return invoke(registered_protocols.list_endpoints, session, security_domain_id, kind)

    @router.post(root + "/integrations")
    def register_integration(body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(registered_protocols.register, session, bounded_json(body.value))

    @router.post(root + "/integrations/{endpoint_id}/revoke")
    def revoke_integration(endpoint_id: str, body: VersionBody, session=Depends(require_action("platform.manage"))):
        return invoke(registered_protocols.revoke, session, endpoint_id, body.expected_version, body.reason)

    @router.post(root + "/integrations/{endpoint_id}/discover")
    def discover(endpoint_id: str, session=Depends(require_action("tools.read"))):
        return invoke(registered_protocols.discover, session, endpoint_id)

    @router.post(root + "/integrations/{endpoint_id}/a2a-binding")
    def a2a_binding(endpoint_id: str, body: BoundedBody, session=Depends(require_action("platform.manage"))):
        from .a2a_http_binding import bind
        return invoke(bind, session, endpoint_id, body.value["graph_version_id"], body.value["plan_id"])

    @router.post(root + "/integrations/{endpoint_id}/tools/approve")
    def approve_tool(endpoint_id: str, body: BoundedBody, session=Depends(require_action("platform.manage"))):
        value = body.value
        return invoke(registered_protocols.approve_tool, session, endpoint_id, value["tool_name"], value["tool_digest"], value["expected_revision"])

    @router.post(root + "/integrations/{endpoint_id}/tools/withdraw")
    def withdraw_tool(endpoint_id: str, body: BoundedBody, session=Depends(require_action("platform.manage"))):
        value = body.value
        return invoke(registered_protocols.withdraw_tool, session, endpoint_id, value["tool_name"], value["tool_digest"], value["expected_revision"])

    @router.post(root + "/integrations/{endpoint_id}/tools/call")
    def call_tool(endpoint_id: str, body: BoundedBody, session=Depends(require_action("tools.read"))):
        value = bounded_json(body.value)
        return invoke(registered_protocols.call_tool, session, endpoint_id, value["tool_name"], value["tool_digest"], value["arguments"], value["idempotency_key"])

    @router.get(root + "/calls/{call_id}")
    def read_call(call_id: str, session=Depends(require_action("tools.read"))):
        return invoke(registered_protocols.read_call, session, call_id)

    @router.post(root + "/calls/{call_id}/cancel")
    def cancel_call(call_id: str, session=Depends(require_action("tools.read"))):
        return invoke(registered_protocols.cancel_call, session, call_id)

    @router.get(root + "/assets")
    def assets(security_domain_id: str, session=Depends(require_action("workspaces.read"))):
        return invoke(managed_inputs.list_assets, session, security_domain_id)

    @router.post(root + "/assets")
    def upload(body: ManagedInputBody, session=Depends(require_action("workspaces.write"))):
        return invoke(managed_inputs.upload, session, body.security_domain_id, body.filename, body.media_type, body.content_base64)

    @router.post(root + "/assets/{asset_id}/query")
    def query_asset(asset_id: str, body: InputQuestion, session=Depends(require_action("model_gateway.forward"))):
        return invoke(managed_inputs.query, session, asset_id, body.profile_id, body.question)

    @router.post(root + "/assets/{asset_id}/revoke")
    def revoke_asset(asset_id: str, body: VersionBody, session=Depends(require_action("workspaces.write"))):
        return invoke(managed_inputs.revoke, session, asset_id, body.expected_version)

    @router.get(root + "/executions/{execution_id}/progress")
    def execution_progress(execution_id: str, session=Depends(require_action("agents.operate"))):
        return invoke(agent_diagnostics.progress, session, execution_id)

    @router.post(root + "/framework/executions")
    def framework_execution(body: FrameworkExecutionBody, session=Depends(require_action("agents.operate"))):
        from . import framework_execution as service
        return invoke(service.enqueue, session, body.security_domain_id, body.agent_id,
                      body.messages, body.idempotency_key, body.reason)

    @router.post(root + "/executions/{execution_id}/cancel")
    def cancel_execution(execution_id: str, session=Depends(require_action("agents.operate"))):
        return invoke(agent_diagnostics.cancel, session, execution_id)

    @router.post(root + "/diagnostics")
    def diagnose(body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(agent_diagnostics.run, session, body.value["security_domain_id"], body.value["check_kind"], body.value.get("resource_id", ""))

    @router.post(root + "/telemetry")
    def queue_telemetry(body: BoundedBody, session=Depends(require_action("platform.manage"))):
        return invoke(telemetry_delivery.queue, session, body.value["endpoint_id"], body.value["outbox_id"], body.value["trace_id"])

    @router.get(root + "/telemetry/{delivery_id}")
    def read_telemetry(delivery_id: str, session=Depends(require_action("platform.manage"))):
        return invoke(telemetry_delivery.read, session, delivery_id)

    app.include_router(router)
