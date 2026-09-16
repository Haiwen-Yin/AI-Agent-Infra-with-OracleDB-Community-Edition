"""Explicit outcome proposals retain exact relational sources, never auto-promote."""
from . import connection,continuity_handoff as handoff,continuity_candidates as candidates
from .continuity_contracts import OutcomeProposal,NewCandidate
from .continuity_state import ContinuityConflict


def propose_experience(actor,handoff_id,value):
    request=OutcomeProposal.model_validate(value)
    def perform(tx):
        record=handoff._read_outcome(tx,actor,handoff_id)
        if record['outcome_id']!=request.expected_outcome_id or record['content_digest']!=request.expected_digest:
            raise ContinuityConflict('STALE_CONTENT','The proposal must reference the exact observed outcome')
        root=tx.query_one("SELECT w.SECURITY_DOMAIN_ID FROM CX_HANDOFFS h JOIN CX_WORK_CONTRACTS w "
                          "ON w.WORK_CONTRACT_ID=h.WORK_CONTRACT_ID WHERE h.HANDOFF_ID=:handoff",{'handoff':handoff_id})
        proposal=NewCandidate(security_domain_id=root['security_domain_id'],content=request.content,
            sources=[dict(family='HANDOFF_OUTCOME',entity_id=record['outcome_id'],revision_id=str(record['revision_no']),
                          content_digest=record['content_digest'])],reason=request.reason,idempotency_key=request.idempotency_key)
        return candidates._create_candidate(tx,actor,proposal)
    return connection.execute_transaction_callback(perform)
