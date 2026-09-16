"""State preconditions for transactional continuity operations.

Call only after current resource authorization and while holding the entity
lock. These checks do not replace database authorization or versioned writes.
"""
from datetime import datetime, timezone


class ContinuityError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ContinuityConflict(ContinuityError):
    pass


WORK_TRANSITIONS = {
    'OPEN': {'IN_PROGRESS', 'BLOCKED', 'CANCELLED', 'EXPIRED'},
    'IN_PROGRESS': {'BLOCKED', 'COMPLETED', 'CANCELLED', 'EXPIRED'},
    'BLOCKED': {'IN_PROGRESS', 'CANCELLED', 'EXPIRED'},
    'COMPLETED': set(), 'CANCELLED': set(), 'EXPIRED': set(),
}
HANDOFF_TRANSITIONS = {
    'DRAFT': {'OFFERED', 'EXPIRED'},
    'OFFERED': {'ACKNOWLEDGED', 'REJECTED', 'EXPIRED'},
    'ACKNOWLEDGED': {'IN_PROGRESS', 'REJECTED', 'EXPIRED'},
    'IN_PROGRESS': {'COMPLETED', 'REJECTED', 'EXPIRED'},
    'COMPLETED': set(), 'REJECTED': set(), 'EXPIRED': set(),
}
CANDIDATE_TRANSITIONS = {
    'PENDING': {'REVIEWING', 'REJECTED', 'EXPIRED', 'SUPERSEDED'},
    'REVIEWING': {'APPROVED', 'REJECTED', 'EXPIRED', 'SUPERSEDED'},
    'APPROVED': set(), 'REJECTED': set(), 'EXPIRED': set(), 'SUPERSEDED': set(),
}


def require_version(actual: int, expected: int):
    if type(actual) is not int or type(expected) is not int or actual < 1 or expected < 1:
        raise ContinuityError('INVALID_VERSION', 'A positive integer version is required')
    if actual != expected:
        raise ContinuityConflict('STALE_VERSION', 'The resource changed; read its current version')


def require_transition(family: str, current: str, target: str):
    graphs = {'WORK': WORK_TRANSITIONS, 'HANDOFF': HANDOFF_TRANSITIONS, 'CANDIDATE': CANDIDATE_TRANSITIONS}
    if family not in graphs or current not in graphs[family] or target not in graphs[family]:
        raise ContinuityError('INVALID_STATE', 'Unknown lifecycle state')
    if target not in graphs[family][current]:
        raise ContinuityConflict('INVALID_TRANSITION', 'The requested lifecycle transition is not allowed')


def require_not_expired(expires_at: datetime, now: datetime):
    # New continuity timestamps are absolute instants. Never compare a naive
    # database clock to an application-local value or assume a missing zone.
    for value in (expires_at, now):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ContinuityError('INVALID_TIME', 'An explicit timezone is required')
    if expires_at.astimezone(timezone.utc) <= now.astimezone(timezone.utc):
        raise ContinuityConflict('EXPIRED', 'The resource has expired')


def acknowledge_handoff(*, actor: str, recipient: str, status: str, version: int,
                        expected_version: int, revision_no: int, expected_revision_no: int,
                        expires_at: datetime, now: datetime):
    if not actor or actor != recipient:
        raise PermissionError('Only the current recipient can acknowledge this handoff')
    require_version(version, expected_version)
    require_version(revision_no, expected_revision_no)
    require_not_expired(expires_at, now)
    require_transition('HANDOFF', status, 'ACKNOWLEDGED')


def review_candidate(*, reviewer: str, proposer: str, status: str, version: int,
                     expected_version: int, actual_digest: str, expected_digest: str,
                     decision: str):
    if not reviewer or not proposer or reviewer == proposer:
        raise PermissionError('Candidate review requires a separate authorized reviewer')
    require_version(version, expected_version)
    if actual_digest != expected_digest:
        raise ContinuityConflict('STALE_CONTENT', 'Candidate content differs from the reviewed revision')
    require_transition('CANDIDATE', status, decision)


def require_idempotent_request(stored_digest: str, incoming_digest: str):
    if not stored_digest or not incoming_digest or stored_digest != incoming_digest:
        raise ContinuityConflict('IDEMPOTENCY_CONFLICT', 'The idempotency key belongs to a different request')


def diagnostic_status(checks: list[str]) -> str:
    """A run passes only if every requested check was actually observed to pass."""
    if any(value not in {'PASS', 'FAIL', 'UNAVAILABLE', 'UNOBSERVED'} for value in checks):
        raise ContinuityError('INVALID_CHECK', 'Unknown diagnostic result')
    if 'FAIL' in checks:
        return 'FAIL'
    if not checks or 'UNOBSERVED' in checks:
        return 'UNOBSERVED'
    if 'UNAVAILABLE' in checks:
        return 'UNAVAILABLE'
    return 'PASS'
