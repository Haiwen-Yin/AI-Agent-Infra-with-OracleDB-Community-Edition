"""Typed continuity transport shared by MCP and local Agent integrations."""
import os
from typing import Annotated,Literal,Union
from urllib.parse import quote,urlsplit

import httpx
from pydantic import Field,TypeAdapter,ValidationError,create_model
from . import continuity_contracts as dto
from .continuity_policy import HandoffPolicyChange
from .continuity_runtime import ContextExecutionRequest
from .continuity_native_sources import CaptureRequest

OPERATIONS={
    'context_native_capture':('POST','/context/native-sources',CaptureRequest,None,False),
    'context_runtime_enqueue':('POST','/context/runtime-executions',ContextExecutionRequest,None,False),
    'context_runtime_read':('GET','/context/runtime-executions/{execution_id}',dto.Contract,'execution_id',False),
    'context_runtime_agents':('GET','/context/runtime-agents',dto.InventoryRequest,None,False),
    'work_handoff_policy':('POST','/work-contracts/{work_id}/handoff-policy',HandoffPolicyChange,'work_id',False),
    'tool_invoke':('POST','/tools/{tool_id}/invoke',dto.ToolInvocation,'tool_id',False),
    'domain_list':('GET','/continuity-domains',dto.InventoryPage,None,False),
    'recipient_list':('GET','/continuity-recipients',dto.InventoryRequest,None,False),
    'work_list':('GET','/work-contracts',dto.InventoryRequest,None,False),
    'handoff_list':('GET','/handoffs',dto.InventoryRequest,None,False),
    'capabilities':('GET','/continuity-capabilities',dto.CapabilitiesRequest,None,False),
    'work_create':('POST','/work-contracts',dto.NewWork,None,False),
    'work_read':('GET','/work-contracts/{work_id}',dto.Contract,'work_id',True),
    'work_revise':('POST','/work-contracts/{work_id}/revisions',dto.WorkRevision,'work_id',False),
    'work_status':('POST','/work-contracts/{work_id}/status',dto.WorkStateChange,'work_id',False),
    'handoff_offer':('POST','/work-contracts/{work_id}/handoffs',dto.NewHandoff,'work_id',False),
    'handoff_read':('GET','/handoffs/{handoff_id}/history',dto.Contract,'handoff_id',True),
    'handoff_revise':('POST','/handoffs/{handoff_id}/revisions',dto.HandoffRevision,'handoff_id',False),
    'handoff_decide':('POST','/handoffs/{handoff_id}/acknowledge',dto.HandoffDecision,'handoff_id',False),
    'outcome_submit':('POST','/handoffs/{handoff_id}/outcome',dto.HandoffOutcome,'handoff_id',False),
    'outcome_read':('GET','/handoffs/{handoff_id}/outcome',dto.Contract,'handoff_id',False),
    'outcome_propose_experience':('POST','/handoffs/{handoff_id}/experience-candidates',dto.OutcomeProposal,'handoff_id',False),
    'context_assemble':('POST','/context/assemble',dto.AssemblyRequest,None,False),
    'context_read':('GET','/context/assemblies/{assembly_id}',dto.Contract,'assembly_id',False),
    'context_list':('GET','/context/assemblies',dto.InventoryRequest,None,False),
    'candidate_create':('POST','/artifact-candidates',dto.NewCandidate,None,False),
    'candidate_list':('GET','/artifact-candidates',dto.InventoryRequest,None,False),
    'candidate_read':('GET','/artifact-candidates/{candidate_id}',dto.Contract,'candidate_id',True),
    'candidate_revise':('POST','/artifact-candidates/{candidate_id}/revisions',dto.CandidateRevision,'candidate_id',False),
    'candidate_review':('POST','/artifact-candidates/{candidate_id}/review',dto.CandidateReview,'candidate_id',False),
    'candidate_promote':('POST','/artifact-candidates/{candidate_id}/promote',dto.CandidatePromotion,'candidate_id',False),
    'artifact_retire':('POST','/artifact-candidates/retire-artifact',dto.ArtifactRetirement,None,False),
    'context_publish':('POST','/context-publications',dto.NewPublication,None,False),
    'publication_list':('GET','/context-publications',dto.InventoryRequest,None,False),
    'publication_revoke':('POST','/context-publications/{publication_id}/revoke',dto.PublicationRevocation,'publication_id',False),
    'diagnostics_run':('POST','/diagnostics/runs',dto.NewDiagnosticRun,None,False),
    'diagnostics_read':('GET','/diagnostics/runs/{run_id}',dto.Contract,'run_id',False),
}


def _contract():
    calls=[]
    for name,(_,_,base,identifier,revision) in OPERATIONS.items():
        fields={identifier:(dto.Identifier,...)} if identifier else {}
        if revision:
            fields['revision']=(dto.Revision|None,None)
        body=create_model(name+'Request',__base__=base,**fields)
        calls.append(create_model(name+'Call',__base__=dto.Contract,operation=(Literal[name],...),request=(body,...)))
    return TypeAdapter(Annotated[Union[tuple(calls)],Field(discriminator='operation')])


CALL=_contract()


class ContinuityClientError(ValueError):
    def __init__(self,code):
        super().__init__(code)
        self.code=code


def input_schema():
    return CALL.json_schema()


def call(actor,value,*,transport=None):
    try:
        request=CALL.validate_python(value)
    except ValidationError as exc:
        raise ContinuityClientError('INVALID_REQUEST') from exc
    base=os.environ.get('CX_CONTINUITY_GATEWAY_URL','').rstrip('/')
    token=os.environ.get('CX_AGENT_ACCESS_TOKEN','')
    instance=os.environ.get('CX_AGENT_INSTANCE_ID','')
    parsed=urlsplit(base)
    if not actor or not token or not instance or parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ContinuityClientError('GATEWAY_CONFIGURATION_REQUIRED')
    method,path,_,identifier,_=OPERATIONS[request.operation]
    payload=request.request.model_dump(mode='json')
    if identifier:
        path=path.replace('{'+identifier+'}',quote(payload.pop(identifier),safe=''))
    headers={'Authorization':'Bearer '+token,'X-Agent-Id':actor,'X-Agent-Instance':instance}
    try:
        with httpx.Client(timeout=30,follow_redirects=False,trust_env=False,transport=transport) as client:
            response=client.request(method,base+path,headers=headers,
                                    **({'params':{k:v for k,v in payload.items() if v is not None}} if method=='GET' else {'json':payload}))
        if response.status_code!=200:
            code={401:'UNAUTHENTICATED',403:'ACCESS_DENIED',409:'CONFLICT',422:'INVALID_REQUEST'}.get(response.status_code,'GATEWAY_UNAVAILABLE')
            raise ContinuityClientError(code)
        result=response.json()
        if not isinstance(result,dict):
            raise ContinuityClientError('GATEWAY_UNAVAILABLE')
        return result
    except ContinuityClientError:
        raise
    except Exception as exc:
        # No automatic replay after uncertain delivery, and no credentials,
        # remote error bodies or transport details in the caller-visible error.
        raise ContinuityClientError('GATEWAY_UNAVAILABLE') from exc
