"""Cross-entry contracts reject ambiguous revisions and fabricated checks."""
import pytest
from pydantic import ValidationError
from lib.continuity_contracts import (
    AssemblyRequest, Criterion, DiagnosticCheck, NewCandidate, NewHandoff,
    NewPublication, SourceRef, WorkContent, WorkRevision, content_digest, request_digest,
)


def source(family='KNOWLEDGE'):
    return dict(family=family, entity_id='entity-1', revision_id='revision-3', content_digest='a'*64)


def work(title='目标'):
    return WorkContent(objective=title, criteria=(Criterion(criterion_id='c1', description='可验证结果', verification='实际回归'),))


def test_digest_is_cross_entry_stable_and_unicode_normalized():
    assert content_digest(work('café')) == content_digest(work('cafe\u0301'))
    assert content_digest(work()) == content_digest(WorkContent.model_validate_json(work().model_dump_json()))
    assert content_digest(work('new')) != content_digest(work())
    assert request_digest('a', 'create', work()) != request_digest('b', 'create', work())
    assert request_digest('a', 'create', work()) != request_digest('a', 'revise', work())


@pytest.mark.parametrize('version', [0, -1, True, '1', 1.2])
def test_versions_are_positive_integers_without_coercion(version):
    with pytest.raises(ValidationError):
        WorkRevision(expected_version=version, content=work(), reason='change', idempotency_key='r1')


def test_source_is_exact_and_does_not_accept_authority_fields():
    with pytest.raises(ValidationError):
        SourceRef(**source(), authorized=True)
    with pytest.raises(ValidationError):
        SourceRef(family='KNOWLEDGE', entity_id='e')
    with pytest.raises(ValidationError):
        SourceRef(**dict(source(), content_digest='latest'))


def test_work_criteria_require_unique_ids():
    with pytest.raises(ValidationError):
        WorkContent(objective='goal', criteria=work().criteria*2)


@pytest.mark.parametrize('budget,limit', [(True, 10), (0, 1), (200000, 1), (10, -1), (10, 101)])
def test_assembly_limits_are_bounded(budget, limit):
    with pytest.raises(ValidationError):
        AssemblyRequest(request_id='r', security_domain_id='d', purpose='answer', idempotency_key='k', token_budget=budget, entry_limit=limit)


def test_empty_context_is_an_explicit_valid_request():
    request = AssemblyRequest(request_id='r', security_domain_id='d', purpose='answer', idempotency_key='k', entry_limit=0)
    assert request.sources == () and request.entry_limit == 0


def test_candidates_cannot_cross_families_or_omit_provenance():
    candidate = dict(security_domain_id='d', content={'family':'KNOWLEDGE','title':'title','body':'body'},
                     sources=[source()], reason='review', idempotency_key='k')
    assert NewCandidate(**candidate).content.family == 'KNOWLEDGE'
    with pytest.raises(ValidationError):
        NewCandidate(**dict(candidate, sources=[]))
    with pytest.raises(ValidationError):
        NewCandidate(**candidate, replaces=source('SKILL'))
    with pytest.raises(ValidationError):
        NewCandidate(**dict(candidate, content={'family':'EXPERIENCE','title':'title','body':'unverified'}))


@pytest.mark.parametrize('status,observed', [('PASS',False), ('FAIL',False), ('UNOBSERVED',True)])
def test_diagnostics_do_not_invent_observation(status, observed):
    with pytest.raises(ValidationError):
        DiagnosticCheck(check_code='model', status=status, observed=observed, detail_code='not_executed')


def test_publication_requires_explicit_timezone_and_pins_revision():
    values = dict(source=source(), target_security_domain_id='d', purpose='review', classification='INTERNAL',
                  reason='share', idempotency_key='k')
    with pytest.raises(ValidationError):
        NewPublication(**values, expires_at='2026-10-01T00:00:00')
    one = NewPublication(**values, expires_at='2026-10-01T08:00:00+08:00')
    two = NewPublication(**values, expires_at='2026-10-01T00:00:00Z')
    assert content_digest(one) == content_digest(two)


def test_handoff_requires_explicit_receiver_and_structured_next_action():
    with pytest.raises(ValidationError):
        NewHandoff(expected_work_version=1, recipient_principal_id='b', kind='AGENT_TO_AGENT',
                   content={'summary':'done','next_actions':[]}, expires_at='2026-10-01T00:00:00Z',
                   reason='transfer', idempotency_key='k')
