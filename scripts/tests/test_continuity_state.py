from datetime import datetime, timedelta, timezone

import pytest

from lib.continuity_state import (
    ContinuityError, ContinuityConflict, acknowledge_handoff, diagnostic_status,
    require_transition, require_not_expired, require_version, require_idempotent_request,
    review_candidate,
)


def test_receiver_must_confirm_the_exact_revision():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    values = dict(actor='B', recipient='B', status='OFFERED', version=3, expected_version=3,
                  revision_no=2, expected_revision_no=2, expires_at=now+timedelta(hours=1), now=now)
    acknowledge_handoff(**values)
    with pytest.raises(PermissionError):
        acknowledge_handoff(**dict(values, actor='A'))
    for change in [dict(expected_version=2), dict(expected_revision_no=1), dict(expires_at=now), dict(status='COMPLETED')]:
        with pytest.raises(ContinuityConflict):
            acknowledge_handoff(**dict(values, **change))


@pytest.mark.parametrize('family,terminal', [('WORK','COMPLETED'), ('WORK','CANCELLED'),
    ('HANDOFF','COMPLETED'), ('HANDOFF','REJECTED'), ('CANDIDATE','APPROVED'), ('CANDIDATE','SUPERSEDED')])
def test_terminal_entities_cannot_be_reopened(family, terminal):
    with pytest.raises(ContinuityConflict):
        require_transition(family, terminal, terminal)


def test_candidate_review_cannot_change_content_or_approve_own_work():
    values = dict(reviewer='human', proposer='agent', status='REVIEWING', version=2,
                  expected_version=2, actual_digest='a'*64, expected_digest='a'*64, decision='APPROVED')
    review_candidate(**values)
    with pytest.raises(PermissionError):
        review_candidate(**dict(values, reviewer='agent'))
    with pytest.raises(ContinuityConflict):
        review_candidate(**dict(values, expected_digest='b'*64))
    with pytest.raises(ContinuityConflict):
        review_candidate(**dict(values, expected_version=1))


def test_expiry_uses_absolute_time_across_offsets():
    now = datetime(2026, 9, 15, 8, tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(ContinuityConflict):
        require_not_expired(datetime(2026, 9, 15, tzinfo=timezone.utc), now)
    with pytest.raises(ContinuityError):
        require_not_expired(now.replace(tzinfo=None), now)
    require_not_expired(now+timedelta(seconds=1), now.astimezone(timezone.utc))


def test_key_reuse_is_not_permission_to_replace_a_request():
    require_idempotent_request('a'*64, 'a'*64)
    with pytest.raises(ContinuityConflict):
        require_idempotent_request('a'*64, 'b'*64)
    with pytest.raises(ContinuityError):
        require_version(1, True)


@pytest.mark.parametrize('checks,status', [([], 'UNOBSERVED'), (['PASS'], 'PASS'),
    (['PASS','UNAVAILABLE'], 'UNAVAILABLE'), (['PASS','UNOBSERVED'], 'UNOBSERVED'),
    (['FAIL','UNAVAILABLE'], 'FAIL')])
def test_diagnostic_summary_cannot_turn_missing_evidence_into_pass(checks, status):
    assert diagnostic_status(checks) == status
