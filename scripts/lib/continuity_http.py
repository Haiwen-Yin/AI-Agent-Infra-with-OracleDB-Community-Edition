"""Typed continuity HTTP routes using the installation's session/CSRF guard."""
from fastapi import APIRouter, Depends, HTTPException,Query
import logging
import re

logger=logging.getLogger(__name__)

from . import continuity_work as work, continuity_handoff as handoff, continuity_assembly as assembly
from .continuity_contracts import NewWork, WorkRevision, WorkStateChange, NewHandoff, HandoffRevision, HandoffDecision, HandoffOutcome, AssemblyRequest
from .continuity_state import ContinuityError, ContinuityConflict
from . import continuity_candidates as candidates,continuity_publications as publications
from .continuity_contracts import NewCandidate,CandidateRevision,CandidateReview,CandidatePromotion,NewPublication,PublicationRevocation
from .continuity_contracts import NewDiagnosticRun,Identifier
from . import continuity_diagnostics as diagnostics
from . import continuity_retirement as retirement
from .continuity_contracts import ArtifactRetirement
from . import continuity_inventory as inventory
from . import continuity_outcomes as outcomes
from .continuity_contracts import OutcomeProposal
from . import continuity_policy
from . import continuity_runtime
from . import continuity_native_sources


def install_routes(app,require_action,schema_owner_context,*,prefix='/api'):
    router=APIRouter(prefix=prefix)
    def invoke(function,session,*args):
        try:
            from .continuity_bindings import authenticated_transport
            with schema_owner_context(), authenticated_transport(session.get('continuity_transport')):
                return function(str(session['principal_id']),*args)
        except PermissionError as exc:
            raise HTTPException(403,detail={'code':'ACCESS_DENIED','message':'Continuity access denied'}) from exc
        except ContinuityConflict as exc:
            raise HTTPException(409,detail={'code':exc.code,'message':str(exc)}) from exc
        except ContinuityError as exc:
            status=503 if exc.code.endswith('_UNAVAILABLE') else 422
            raise HTTPException(status,detail={'code':exc.code,'message':str(exc)}) from exc
        except Exception as exc:
            # Driver failures can contain connection strings or sensitive SQL.
            codes=re.findall(r'(?:ORA|YAS)-[0-9]{5}',str(exc))
            logger.warning("Continuity operation %s failed (%s; codes=%s)",
                           function.__name__,type(exc).__name__,','.join(codes))
            raise HTTPException(503,detail={'code':'CONTINUITY_UNAVAILABLE','message':'Continuity service unavailable'}) from exc

    if prefix == '/api/agent-gateway/continuity':
        from .continuity_contracts import ToolInvocation
        from . import continuity_tools

        @router.post('/tools/{tool_id}/invoke')
        def invoke_dynamic_tool(tool_id:str,body:ToolInvocation,session:dict=Depends(require_action('actions.propose'))):
            return invoke(continuity_tools.propose,session,tool_id,body)

    @router.get('/continuity-domains')
    def list_domains(cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_domains,session,dict(cursor=cursor,limit=limit))

    @router.get('/continuity-recipients')
    def list_recipients(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_recipients,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.get('/work-contracts')
    def list_work(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_work,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.get('/handoffs')
    def list_handoffs(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_handoffs,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.post('/work-contracts')
    def create_work(body:NewWork,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(work.create_work,session,body)

    @router.post('/context/runtime-executions')
    def create_context_execution(body:continuity_runtime.ContextExecutionRequest,session:dict=Depends(require_action('agents.operate'))):
        return invoke(continuity_runtime.enqueue,session,body)

    @router.post('/context/native-sources')
    def capture_native_source(body:continuity_native_sources.CaptureRequest,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(continuity_native_sources.capture,session,body)

    @router.get('/context/runtime-executions/{execution_id}')
    def read_context_execution(execution_id:str,session:dict=Depends(require_action('agents.operate'))):
        return invoke(continuity_runtime.read_execution,session,execution_id)

    @router.get('/context/runtime-agents')
    def list_context_agents(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('agents.operate'))):
        return invoke(continuity_runtime.list_agents,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.post('/work-contracts/{work_id}/handoff-policy')
    def change_handoff_policy(work_id:str,body:continuity_policy.HandoffPolicyChange,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(continuity_policy.change,session,work_id,body)

    @router.get('/work-contracts/{work_id}')
    def read_work(work_id:str,revision:int|None=None,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(work.read_work,session,work_id,revision)

    @router.post('/work-contracts/{work_id}/revisions')
    def revise_work(work_id:str,body:WorkRevision,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(work.revise_work,session,work_id,body)

    @router.post('/work-contracts/{work_id}/status')
    def change_state(work_id:str,body:WorkStateChange,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(work.change_work_state,session,work_id,body)

    @router.post('/work-contracts/{work_id}/handoffs')
    def offer(work_id:str,body:NewHandoff,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(handoff.offer,session,work_id,body)

    @router.get('/handoffs/{handoff_id}/history')
    def history(handoff_id:str,revision:int|None=None,session:dict=Depends(require_action('workspaces.read'))):
        if revision is None:
            return invoke(handoff.history,session,handoff_id)
        return invoke(handoff.read_handoff,session,handoff_id,revision)

    @router.post('/handoffs/{handoff_id}/revisions')
    def revise(handoff_id:str,body:HandoffRevision,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(handoff.revise_handoff,session,handoff_id,body)

    @router.post('/handoffs/{handoff_id}/acknowledge')
    def acknowledge(handoff_id:str,body:HandoffDecision,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(handoff.decide,session,handoff_id,body)

    @router.post('/handoffs/{handoff_id}/outcome')
    def outcome(handoff_id:str,body:HandoffOutcome,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(handoff.submit_outcome,session,handoff_id,body)

    @router.post('/handoffs/{handoff_id}/experience-candidates')
    def propose_experience(handoff_id:str,body:OutcomeProposal,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(outcomes.propose_experience,session,handoff_id,body)

    @router.get('/handoffs/{handoff_id}/outcome')
    def read_outcome(handoff_id:str,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(handoff.read_outcome,session,handoff_id)

    @router.get('/context/assemblies')
    def list_assemblies(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_assemblies,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.post('/context/assemble')
    def prepare(body:AssemblyRequest,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(assembly.assemble,session,body)

    @router.get('/context/assemblies/{assembly_id}')
    def read_assembly(assembly_id:str,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(assembly.read_assembly,session,assembly_id)

    @router.get('/context/assemblies/{assembly_id}/items')
    def items(assembly_id:str,session:dict=Depends(require_action('workspaces.read'))):
        record=invoke(assembly.read_assembly,session,assembly_id)
        return {'assembly_id':assembly_id,'status':record['status'],'items':record['items']}

    @router.get('/artifact-candidates')
    def list_candidates(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_candidates,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.post('/artifact-candidates')
    def create_candidate(body:NewCandidate,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(candidates.create_candidate,session,body)

    @router.get('/artifact-candidates/{candidate_id}')
    def read_candidate(candidate_id:str,revision:int|None=None,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(candidates.read_candidate,session,candidate_id,revision)

    @router.post('/artifact-candidates/{candidate_id}/revisions')
    def revise_candidate(candidate_id:str,body:CandidateRevision,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(candidates.revise_candidate,session,candidate_id,body)

    @router.post('/artifact-candidates/{candidate_id}/review')
    def review_candidate(candidate_id:str,body:CandidateReview,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(candidates.review_candidate,session,candidate_id,body)

    @router.post('/artifact-candidates/{candidate_id}/promote')
    def promote_candidate(candidate_id:str,body:CandidatePromotion,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(candidates.promote_candidate,session,candidate_id,body)

    @router.get('/context-publications')
    def list_publications(security_domain_id:Identifier,cursor:Identifier|None=None,limit:int=Query(50,ge=1,le=100),session:dict=Depends(require_action('workspaces.read'))):
        return invoke(inventory.list_publications,session,dict(security_domain_id=security_domain_id,cursor=cursor,limit=limit))

    @router.post('/context-publications')
    def publish(body:NewPublication,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(publications.publish,session,body)

    @router.post('/context-publications/{publication_id}/revoke')
    def revoke(publication_id:str,body:PublicationRevocation,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(publications.revoke,session,publication_id,body)

    @router.post('/diagnostics/runs')
    def run_diagnostics(body:NewDiagnosticRun,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(diagnostics.run_diagnostics,session,body)

    @router.get('/diagnostics/runs/{run_id}')
    def read_diagnostics(run_id:str,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(diagnostics.read_run,session,run_id)

    @router.get('/continuity-capabilities')
    def capabilities(security_domain_id:Identifier,session:dict=Depends(require_action('workspaces.read'))):
        return invoke(diagnostics.capabilities,session,{'security_domain_id':security_domain_id})

    @router.post('/artifact-candidates/retire-artifact')
    def retire_artifact(body:ArtifactRetirement,session:dict=Depends(require_action('workspaces.write'))):
        return invoke(retirement.retire,session,body)

    app.include_router(router)
