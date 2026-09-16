"""Typed contracts shared by continuity HTTP, Agent and database services.

These models validate structure, never authority. A source reference is a
locator; every resolver must separately authorize the current reader.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import unicodedata
from typing import Annotated, Literal, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, StringConstraints, field_validator, model_validator

Identifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
Reason = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]
Revision = Annotated[StrictInt, Field(ge=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Family(str, Enum):
    MEMORY = 'MEMORY'
    KNOWLEDGE = 'KNOWLEDGE'
    EXPERIENCE = 'EXPERIENCE'
    SKILL = 'SKILL'
    HANDOFF = 'HANDOFF'
    HANDOFF_OUTCOME = 'HANDOFF_OUTCOME'
    TASK = 'TASK'
    GRAPH = 'GRAPH'
    DB4A2A = 'DB4A2A'
    AUDIT = 'AUDIT'


class SourceRef(Contract):
    family: Family
    entity_id: Identifier
    revision_id: Identifier
    content_digest: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class ToolInvocation(Contract):
    security_domain_id: Identifier
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout: Annotated[StrictInt, Field(ge=1, le=120)] = 30
    reason: Reason
    idempotency_key: Identifier

    @field_validator('arguments')
    @classmethod
    def bounded_arguments(cls, value):
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:
            raise ValueError('Tool arguments exceed the supported size')
        return value


class Criterion(Contract):
    criterion_id: Identifier
    description: Text
    verification: Text


class WorkContent(Contract):
    objective: Text
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=100)]
    constraints: Annotated[tuple[Text, ...], Field(max_length=100)] = ()
    sources: Annotated[tuple[SourceRef, ...], Field(max_length=100)] = ()

    @model_validator(mode='after')
    def unique_criteria(self):
        keys = [item.criterion_id for item in self.criteria]
        if len(set(keys)) != len(keys):
            raise ValueError('criterion IDs must be unique')
        return self


class NewWork(Contract):
    security_domain_id: Identifier
    owner_principal_id: Identifier
    workspace_id: Identifier | None = None
    task_id: Identifier | None = None
    graph_run_id: Identifier | None = None
    content: WorkContent
    reason: Reason
    idempotency_key: Identifier


class WorkRevision(Contract):
    expected_version: Revision
    content: WorkContent
    reason: Reason
    idempotency_key: Identifier


class WorkStateChange(Contract):
    expected_version: Revision
    status: Literal['IN_PROGRESS', 'BLOCKED', 'COMPLETED', 'CANCELLED', 'EXPIRED']
    reason: Reason
    idempotency_key: Identifier


class NextAction(Contract):
    action_id: Identifier
    description: Text
    responsible_principal_id: Identifier
    prerequisites: Annotated[tuple[Text, ...], Field(max_length=30)] = ()
    acceptance: Text


class HandoffContent(Contract):
    summary: Text
    decisions: Annotated[tuple[Text, ...], Field(max_length=100)] = ()
    constraints: Annotated[tuple[Text, ...], Field(max_length=100)] = ()
    evidence: Annotated[tuple[SourceRef, ...], Field(max_length=100)] = ()
    next_actions: Annotated[tuple[NextAction, ...], Field(min_length=1, max_length=100)]
    open_questions: Annotated[tuple[Text, ...], Field(max_length=100)] = ()
    risks_and_blockers: Annotated[tuple[Text, ...], Field(max_length=100)] = ()

    @model_validator(mode='after')
    def unique_actions(self):
        keys = [item.action_id for item in self.next_actions]
        if len(set(keys)) != len(keys):
            raise ValueError('action IDs must be unique')
        return self


class NewHandoff(Contract):
    expected_work_version: Revision
    recipient_principal_id: Identifier
    sender_instance_id: Identifier | None = None
    recipient_instance_id: Identifier | None = None
    kind: Literal['HUMAN_TO_AGENT', 'AGENT_TO_AGENT', 'AGENT_TO_HUMAN', 'WORKER_REPLACEMENT']
    content: HandoffContent
    expires_at: datetime
    reason: Reason
    idempotency_key: Identifier

    @field_validator('expires_at')
    @classmethod
    def explicit_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('expires_at must include a timezone')
        return value.astimezone(timezone.utc)


class HandoffDecision(Contract):
    expected_version: Revision
    expected_revision_no: Revision
    decision: Literal['ACKNOWLEDGED', 'REJECTED', 'IN_PROGRESS']
    reason: Reason
    idempotency_key: Identifier


class HandoffRevision(Contract):
    expected_version: Revision
    expected_revision_no: Revision
    expected_work_version: Revision
    content: HandoffContent
    reason: Reason
    idempotency_key: Identifier


class HandoffOutcome(Contract):
    expected_version: Revision
    expected_revision_no: Revision
    result: Literal['COMPLETED', 'BLOCKED', 'FAILED']
    summary: Text
    satisfied_criteria: Annotated[tuple[Identifier, ...], Field(max_length=100)] = ()
    evidence: Annotated[tuple[SourceRef, ...], Field(max_length=100)] = ()
    reason: Reason
    idempotency_key: Identifier


class AssemblyRequest(Contract):
    request_id: Identifier
    security_domain_id: Identifier
    work_contract_id: Identifier | None = None
    handoff_id: Identifier | None = None
    sources: Annotated[tuple[SourceRef, ...], Field(max_length=100)] = ()
    token_budget: Annotated[StrictInt, Field(ge=1, le=131072)] = 4096
    entry_limit: Annotated[StrictInt, Field(ge=0, le=100)] = 20
    ttl_seconds: Annotated[StrictInt, Field(ge=30, le=3600)] = 300
    purpose: Reason
    idempotency_key: Identifier


class MemoryProposal(Contract):
    family: Literal['MEMORY']
    title: Text
    body: Text
    memory_type: Literal['EPISODIC', 'FACT', 'PREFERENCE', 'DECISION', 'PROCEDURAL']


class KnowledgeProposal(Contract):
    family: Literal['KNOWLEDGE']
    title: Text
    body: Text


class ExperienceProposal(Contract):
    family: Literal['EXPERIENCE']
    title: Text
    problem: Text
    solution: Text
    validation: Text
    applicability: Text


class OutcomeContent(Contract):
    outcome_id: Identifier
    handoff_id: Identifier
    revision_no: Revision
    submitted_by: Identifier
    result: Literal['COMPLETED','BLOCKED','FAILED']
    summary: Text
    evidence: tuple[SourceRef,...]
    satisfied_criteria: tuple[Identifier,...]


class OutcomeProposal(Contract):
    expected_outcome_id: Identifier
    expected_digest: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    content: ExperienceProposal
    reason: Reason
    idempotency_key: Identifier


class SkillProposal(Contract):
    family: Literal['SKILL']
    title: Text
    instructions: Text
    input_contract: Text
    output_contract: Text
    required_actions: Annotated[tuple[Identifier, ...], Field(max_length=100)] = ()


Proposal = Annotated[MemoryProposal | KnowledgeProposal | ExperienceProposal | SkillProposal, Field(discriminator='family')]


class NewCandidate(Contract):
    security_domain_id: Identifier
    content: Proposal
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1, max_length=100)]
    replaces: SourceRef | None = None
    reason: Reason
    idempotency_key: Identifier

    @model_validator(mode='after')
    def replacement_family(self):
        if self.replaces and self.replaces.family.value != self.content.family:
            raise ValueError('replacement must belong to the same artifact family')
        return self


class CandidateReview(Contract):
    expected_version: Revision
    expected_digest: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    decision: Literal['APPROVED', 'REJECTED']
    reason: Reason
    idempotency_key: Identifier


class CandidatePayload(Contract):
    content: Proposal
    sources: Annotated[tuple[SourceRef, ...], Field(min_length=1, max_length=100)]
    replaces: SourceRef | None = None


class CandidateRevision(NewCandidate):
    expected_version: Revision


class CandidatePromotion(Contract):
    expected_version: Revision
    expected_digest: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    reason: Reason
    idempotency_key: Identifier


class NewPublication(Contract):
    source: SourceRef
    target_security_domain_id: Identifier
    purpose: Reason
    classification: Literal['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED']
    expires_at: datetime
    reason: Reason
    idempotency_key: Identifier

    @field_validator('expires_at')
    @classmethod
    def explicit_timezone(cls, value):
        return NewHandoff.explicit_timezone(value)


class PublicationRevocation(Contract):
    expected_version: Revision
    reason: Reason
    idempotency_key: Identifier


class ArtifactRetirement(Contract):
    source: SourceRef
    expected_version: Revision
    reason: Reason
    idempotency_key: Identifier

    @model_validator(mode='after')
    def formal_family(self):
        if self.source.family.value not in {'MEMORY','KNOWLEDGE','EXPERIENCE','SKILL'}:
            raise ValueError('Only formal artifact families can be retired')
        return self


class DiagnosticCheck(Contract):
    check_code: Identifier
    status: Literal['PASS', 'FAIL', 'UNAVAILABLE', 'UNOBSERVED']
    observed: StrictBool
    detail_code: Identifier
    evidence: Annotated[tuple[SourceRef, ...], Field(max_length=20)] = ()

    @model_validator(mode='after')
    def observation_required(self):
        if self.status in {'PASS', 'FAIL'} and not self.observed:
            raise ValueError('an unexecuted check cannot pass or fail')
        if self.status == 'UNOBSERVED' and self.observed:
            raise ValueError('UNOBSERVED cannot claim an observation')
        return self


DiagnosticCode=Literal['PRINCIPAL','DOMAIN','DATABASE','SOURCE_ACCESS','CONTEXT_INPUT','INSTANCE','SKILL_DELIVERY','ENTRYPOINT_PARITY']


class CapabilitiesRequest(Contract):
    security_domain_id: Identifier


class InventoryPage(Contract):
    cursor: Identifier | None = None
    limit: Annotated[StrictInt,Field(ge=1,le=100)] = 50


class InventoryRequest(InventoryPage):
    security_domain_id: Identifier


class NewDiagnosticRun(Contract):
    request_id: Identifier
    security_domain_id: Identifier
    checks: Annotated[tuple[DiagnosticCode, ...], Field(min_length=1,max_length=8)] = ('PRINCIPAL','DOMAIN','DATABASE','SOURCE_ACCESS','CONTEXT_INPUT','INSTANCE','SKILL_DELIVERY','ENTRYPOINT_PARITY')
    sources: Annotated[tuple[SourceRef, ...], Field(max_length=100)] = ()
    assembly_id: Identifier | None = None
    instance_id: Identifier | None = None
    distribution_id: Identifier | None = None
    purpose: Reason
    idempotency_key: Identifier

    @model_validator(mode='after')
    def unique_checks(self):
        if len(set(self.checks))!=len(self.checks):
            raise ValueError('diagnostic checks must be unique')
        return self


def canonical_content(value: Contract) -> str:
    """Portable JSON for exact-version hashing; list order is meaningful."""
    def normalize(item):
        if isinstance(item, str):
            return unicodedata.normalize('NFC', item)
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        return item
    return json.dumps(normalize(value.model_dump(mode='json')), ensure_ascii=True,
                      sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_digest(value: Contract) -> str:
    return hashlib.sha256(canonical_content(value).encode('utf-8')).hexdigest()


def request_digest(actor: str, operation: str, value: Contract) -> str:
    """Bind retries to actor, operation and exact validated request content."""
    payload = json.dumps([actor, operation, canonical_content(value)], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
