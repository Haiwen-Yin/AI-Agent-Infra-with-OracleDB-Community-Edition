"""Database-independent governance contracts for the v4.3 platform.

This module contains validation and planning functions only.  It does not
open connections, read files, use process state, or mutate its arguments.
Callers can persist the returned decisions in the adapter-specific services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class ContractInputError(ValueError):
    """Raised by direct helpers when a required key cannot be generated."""


@dataclass(frozen=True)
class ContractDecision:
    """A serializable, explainable result shared by all pure contracts."""

    allowed: bool
    code: str
    message: str
    action: Optional[str] = None
    state: Optional[str] = None
    reasons: Tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.allowed

    def __bool__(self) -> bool:
        return self.allowed

    def __getitem__(self, key: str) -> Any:
        values = self.as_dict()
        if key in values:
            return values[key]
        return self.details[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "ok": self.allowed,
            "code": self.code,
            "message": self.message,
            "action": self.action,
            "state": self.state,
            "reasons": list(self.reasons),
            "details": dict(self.details),
        }


def _decision(
    allowed: bool,
    code: str,
    message: str,
    *,
    action: Optional[str] = None,
    state: Optional[str] = None,
    reasons: Iterable[str] = (),
    **details: Any,
) -> ContractDecision:
    return ContractDecision(
        bool(allowed),
        str(code),
        str(message),
        action=action,
        state=state,
        reasons=tuple(str(item) for item in reasons),
        details=details,
    )


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None


UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _as_datetime(value: Any) -> Optional[datetime]:
    """Normalize supported timestamp values to aware UTC without using a clock."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractInputError("value is not finite JSON") from exc


# ---------------------------------------------------------------------------
# Channel lifecycle
# ---------------------------------------------------------------------------

CHANNEL_STATUSES = frozenset({
    "ACTIVE",
    "READ_ONLY",
    "ARCHIVED",
    "FROZEN",
    "QUARANTINED",
    "DELETION_PENDING",
    "DELETED",
})

CHANNEL_TRANSITIONS = {
    "ACTIVE": frozenset({"READ_ONLY", "ARCHIVED", "FROZEN", "QUARANTINED", "DELETION_PENDING"}),
    "READ_ONLY": frozenset({"ACTIVE", "ARCHIVED", "FROZEN", "QUARANTINED", "DELETION_PENDING"}),
    "ARCHIVED": frozenset({"READ_ONLY", "FROZEN", "QUARANTINED", "DELETION_PENDING"}),
    "FROZEN": frozenset({"ACTIVE", "READ_ONLY", "ARCHIVED", "QUARANTINED", "DELETION_PENDING"}),
    "QUARANTINED": frozenset({"ACTIVE", "FROZEN", "READ_ONLY", "ARCHIVED", "DELETION_PENDING"}),
    "DELETION_PENDING": frozenset({"ARCHIVED", "FROZEN", "QUARANTINED", "READ_ONLY", "DELETED"}),
    "DELETED": frozenset(),
}


def channel_lifecycle_decision(
    current_status: str,
    requested_status: str,
    *,
    authorized: bool = False,
    legal_hold: bool = False,
    reference_count: int = 0,
    active_work: bool = False,
    quiesced: bool = False,
    retention_expired: bool = False,
    deletion_approved: bool = False,
    deletion_deadline: Any = None,
    now: Any = None,
    recovery_authorized: bool = False,
    investigation_authorized: bool = False,
) -> ContractDecision:
    """Validate one Channel lifecycle transition without performing it.

    ``DELETION_PENDING`` is a scheduled state and may still have references;
    ``DELETED`` is allowed only after all references and active work are gone.
    A legal hold blocks both deletion states and normal recovery from
    ``FROZEN``.  Quarantine is intentionally available as a stricter security
    response from every non-terminal state.
    """
    current = _upper(current_status)
    requested = _upper(requested_status)
    if current not in CHANNEL_STATUSES or requested not in CHANNEL_STATUSES:
        return _decision(False, "CHANNEL_STATUS_INVALID", "channel status is not supported")
    count = _positive_int(reference_count)
    if count is None:
        return _decision(False, "CHANNEL_REFERENCE_COUNT_INVALID", "reference_count must be non-negative", state=current)
    if current == requested:
        return _decision(True, "CHANNEL_NO_CHANGE", "channel already has the requested status", state=current)
    if not authorized:
        return _decision(False, "CHANNEL_AUTHORIZATION_REQUIRED", "authorized lifecycle control is required", state=current)
    if requested in {"DELETION_PENDING", "DELETED"} and legal_hold:
        return _decision(False, "CHANNEL_LEGAL_HOLD", "legal hold overrides deletion", state=current)
    if requested not in CHANNEL_TRANSITIONS[current]:
        return _decision(
            False,
            "CHANNEL_TRANSITION_FORBIDDEN",
            "channel lifecycle transition is not allowed",
            state=current,
            reasons=(f"{current}->{requested}",),
        )
    if current == "DELETED":
        return _decision(False, "CHANNEL_TERMINAL", "deleted channels cannot be changed", state=current)
    if requested == "DELETED":
        if current != "DELETION_PENDING":
            return _decision(False, "CHANNEL_DELETE_REQUIRES_PENDING", "deletion requires DELETION_PENDING", state=current)
        if count:
            return _decision(
                False,
                "CHANNEL_REFERENCES_REMAIN",
                "deletion is blocked by retained references",
                state=current,
                reference_count=count,
            )
        if active_work or not quiesced:
            return _decision(False, "CHANNEL_WORK_NOT_QUIESCED", "active work must be stopped before deletion", state=current)
        if not retention_expired:
            return _decision(False, "CHANNEL_RETENTION_ACTIVE", "retention deadline has not expired", state=current)
        if not deletion_approved:
            return _decision(False, "CHANNEL_DELETE_APPROVAL_REQUIRED", "attributable deletion approval is required", state=current)
        if deletion_deadline is not None:
            deadline = _as_datetime(deletion_deadline)
            current_time = _as_datetime(now) or UTC_EPOCH
            if deadline is None:
                return _decision(False, "CHANNEL_DELETION_DEADLINE_INVALID", "deletion_deadline is invalid", state=current)
            if current_time < deadline:
                return _decision(False, "CHANNEL_DELETION_GRACE_PERIOD", "deletion grace period is still active", state=current, deletion_deadline=_iso(deadline))
        return _decision(True, "CHANNEL_DELETE_ALLOWED", "channel may be deleted", action="DELETE", state=requested, reference_count=0)
    if requested == "DELETION_PENDING":
        if legal_hold:
            return _decision(False, "CHANNEL_LEGAL_HOLD", "legal hold requires preserved evidence", state=current)
        if active_work or not quiesced:
            return _decision(False, "CHANNEL_WORK_NOT_QUIESCED", "active work must be stopped before deletion is scheduled", state=current)
        return _decision(
            True,
            "CHANNEL_DELETION_SCHEDULED",
            "channel may enter delayed deletion",
            action="SCHEDULE_DELETION",
            state=requested,
            reference_count=count,
            deletion_blocked_by_references=bool(count),
        )
    if requested == "ARCHIVED" and (active_work or not quiesced):
        return _decision(False, "CHANNEL_WORK_NOT_QUIESCED", "archiving must stop background work first", state=current)
    if requested == "FROZEN" and legal_hold:
        return _decision(True, "CHANNEL_LEGAL_HOLD_FROZEN", "channel is frozen to preserve held evidence", action="FREEZE", state=requested, legal_hold=True)
    if current == "FROZEN" and requested in {"ACTIVE", "READ_ONLY", "ARCHIVED"}:
        if legal_hold:
            return _decision(False, "CHANNEL_LEGAL_HOLD", "held evidence cannot be unfrozen", state=current)
        if not recovery_authorized:
            return _decision(False, "CHANNEL_RECOVERY_AUTHORIZATION_REQUIRED", "controlled recovery authorization is required", state=current)
    if current == "QUARANTINED" and requested in {"ACTIVE", "READ_ONLY", "ARCHIVED"}:
        if not investigation_authorized or not recovery_authorized:
            return _decision(False, "CHANNEL_QUARANTINE_RECOVERY_REQUIRED", "investigation and recovery authorization are required", state=current)
    if requested == "ACTIVE" and legal_hold:
        return _decision(False, "CHANNEL_LEGAL_HOLD", "legal hold prevents active access", state=current)
    return _decision(True, "CHANNEL_TRANSITION_ALLOWED", "channel lifecycle transition is allowed", action=requested, state=requested, reference_count=count)


validate_channel_lifecycle = channel_lifecycle_decision


def channel_can_delete(**kwargs: Any) -> bool:
    """Return only the deletion decision for callers that need a boolean."""
    kwargs = dict(kwargs)
    kwargs["requested_status"] = "DELETED"
    return bool(channel_lifecycle_decision(**kwargs))


# ---------------------------------------------------------------------------
# Bridge transfer
# ---------------------------------------------------------------------------

BRIDGE_MODES = frozenset({"REFERENCE", "REDACTED_COPY", "SUMMARY", "ARTIFACT", "FULL_COPY"})
BRIDGE_PHASES = frozenset({"PROPOSE", "DELIVER", "READ"})
BRIDGE_RISK = {
    "REFERENCE": "LOW",
    "SUMMARY": "MEDIUM",
    "REDACTED_COPY": "MEDIUM",
    "ARTIFACT": "HIGH",
    "FULL_COPY": "CRITICAL",
}
CLASSIFICATION_LEVELS = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}


def _recipient_clearance_allows(clearance: Any, required: int) -> bool:
    if clearance is None:
        return True
    if isinstance(clearance, Mapping):
        values = list(clearance.values())
    elif isinstance(clearance, (list, tuple, set, frozenset)):
        values = list(clearance)
    else:
        values = [clearance]
    if not values:
        return False
    levels = [CLASSIFICATION_LEVELS.get(_upper(value), -1) for value in values]
    return all(level >= required for level in levels)


def bridge_transfer_decision(
    source_domain_id: str,
    target_domain_id: str,
    transfer_mode: str,
    *,
    phase: str = "PROPOSE",
    purpose: str = "",
    reason: str = "",
    classification: str = "INTERNAL",
    recipients: Optional[Sequence[str]] = None,
    policy_version: str = "",
    expires_at: Any = None,
    now: Any = None,
    approval_status: str = "PENDING",
    proposer_id: str = "",
    approver_id: str = "",
    full_copy_enabled: bool = False,
    target_policy_allows: bool = True,
    source_body_authorized: bool = False,
    recipient_clearance: Any = None,
    delivered_classification: Optional[str] = None,
    source_object_id: str = "",
    artifact_id: str = "",
    provenance: Any = None,
    redaction_confirmed: bool = False,
    summary_confirmed: bool = False,
    source_quarantined: bool = False,
    target_quarantined: bool = False,
) -> ContractDecision:
    """Validate a governed cross-domain Bridge proposal or delivery."""
    source = _text(source_domain_id)
    target = _text(target_domain_id)
    mode = _upper(transfer_mode)
    step = _upper(phase)
    approval = _upper(approval_status)
    level_name = _upper(classification)
    if not source or not target or source == target:
        return _decision(False, "BRIDGE_DOMAIN_INVALID", "Bridge requires two different Security Domains")
    if mode not in BRIDGE_MODES:
        return _decision(False, "BRIDGE_MODE_INVALID", "transfer mode is not supported")
    if step not in BRIDGE_PHASES:
        return _decision(False, "BRIDGE_PHASE_INVALID", "Bridge phase is not supported")
    if level_name not in CLASSIFICATION_LEVELS:
        return _decision(False, "BRIDGE_CLASSIFICATION_INVALID", "classification is not supported")
    if not _text(purpose) or not _text(reason):
        return _decision(False, "BRIDGE_PURPOSE_REASON_REQUIRED", "purpose and reason are required")
    if not _text(policy_version):
        return _decision(False, "BRIDGE_POLICY_REQUIRED", "policy version is required")
    recipient_list = tuple(_text(item) for item in (recipients or ()))
    if not recipient_list or any(not item for item in recipient_list) or len(set(recipient_list)) != len(recipient_list):
        return _decision(False, "BRIDGE_RECIPIENTS_INVALID", "Bridge recipients must be non-empty and unique")
    expiry = _as_datetime(expires_at)
    current_time = _as_datetime(now) or UTC_EPOCH
    if expiry is None or expiry <= current_time:
        return _decision(False, "BRIDGE_EXPIRY_INVALID", "Bridge expiry must be after the evaluation time")
    if approval in {"REJECTED", "EXPIRED", "CANCELLED"}:
        return _decision(False, "BRIDGE_NOT_APPROVED", "Bridge is not in a deliverable approval state")
    if _text(proposer_id) and _text(proposer_id) == _text(approver_id):
        return _decision(False, "BRIDGE_SELF_APPROVAL", "the proposer cannot approve its own Bridge")
    if source_quarantined or target_quarantined:
        return _decision(False, "BRIDGE_QUARANTINED_DOMAIN", "Bridge is blocked by a quarantined Security Domain")
    if not target_policy_allows:
        return _decision(False, "BRIDGE_TARGET_POLICY_DENY", "target policy does not allow this transfer")
    if not _text(source_object_id):
        return _decision(False, "BRIDGE_SOURCE_REQUIRED", "source object identity is required")
    if mode == "FULL_COPY" and not full_copy_enabled:
        return _decision(False, "BRIDGE_FULL_COPY_DISABLED", "FULL_COPY requires explicit policy enablement")
    if mode == "ARTIFACT" and not _text(artifact_id):
        return _decision(False, "BRIDGE_ARTIFACT_REQUIRED", "ARTIFACT transfer requires an Artifact identity")
    if mode == "REDACTED_COPY" and step in {"DELIVER", "READ"} and not redaction_confirmed:
        return _decision(False, "BRIDGE_REDACTION_REQUIRED", "redaction must be confirmed before delivery")
    if mode == "SUMMARY" and step in {"DELIVER", "READ"} and not summary_confirmed:
        return _decision(False, "BRIDGE_SUMMARY_REQUIRED", "summary generation must be confirmed before delivery")
    if provenance is None or provenance == "" or provenance == {}:
        return _decision(False, "BRIDGE_PROVENANCE_REQUIRED", "source provenance is required")
    output_classification = _upper(delivered_classification or level_name)
    if output_classification not in CLASSIFICATION_LEVELS:
        return _decision(False, "BRIDGE_DELIVERED_CLASSIFICATION_INVALID", "delivered classification is not supported")
    if not _recipient_clearance_allows(recipient_clearance, CLASSIFICATION_LEVELS[output_classification]):
        return _decision(False, "BRIDGE_RECIPIENT_CLEARANCE_DENY", "a recipient lacks the required classification clearance")
    requires_approval = True
    if step in {"DELIVER", "READ"}:
        if approval != "APPROVED" or not _text(approver_id):
            return _decision(False, "BRIDGE_APPROVAL_REQUIRED", "approved and attributable Bridge decision is required")
        if not source_body_authorized:
            return _decision(
                False,
                "BRIDGE_SOURCE_REAUTH_REQUIRED",
                "current source authorization is required before protected content is read",
                content_allowed=False,
            )
    content_allowed = step in {"DELIVER", "READ"} and bool(source_body_authorized)
    if step == "PROPOSE":
        return _decision(
            True,
            "BRIDGE_PROPOSAL_ALLOWED",
            "Bridge proposal may be recorded pending governed approval",
            action="PROPOSE",
            state="PENDING",
            risk_level=BRIDGE_RISK[mode],
            requires_approval=requires_approval,
            content_allowed=False,
            output_classification=output_classification,
            expires_at=_iso(expiry),
        )
    return _decision(
        True,
        "BRIDGE_TRANSFER_ALLOWED",
        "Bridge transfer is authorized for the requested phase",
        action="DELIVER" if step == "DELIVER" else "READ",
        state="APPROVED",
        risk_level=BRIDGE_RISK[mode],
        requires_approval=requires_approval,
        content_allowed=content_allowed,
        output_classification=output_classification,
        expires_at=_iso(expiry),
    )


validate_bridge_transfer = bridge_transfer_decision


# ---------------------------------------------------------------------------
# Notification grading, idempotency, and deadlines
# ---------------------------------------------------------------------------

NOTIFICATION_LEVELS = frozenset({"INFO", "ACTION_REQUIRED", "WARNING", "CRITICAL"})
NOTIFICATION_DEADLINES = {
    "ACTION_REQUIRED": 24 * 60 * 60,
    "WARNING": 4 * 60 * 60,
    "CRITICAL": 60 * 60,
}


def notification_dedupe_key(
    principal_id: str,
    event_type: str,
    resource_id: str,
    occurrence_key: str,
    *,
    policy_version: str = "",
) -> str:
    """Build a stable key without putting notification content in the key."""
    values = {
        "version": "notification/1",
        "principal_id": _text(principal_id),
        "event_type": _upper(event_type),
        "resource_id": _text(resource_id),
        "occurrence_key": _text(occurrence_key),
        "policy_version": _text(policy_version),
    }
    if not values["principal_id"] or not values["event_type"] or not values["resource_id"] or not values["occurrence_key"]:
        raise ContractInputError("principal_id, event_type, resource_id, and occurrence_key are required")
    return "notif:v1:" + hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()


make_notification_dedupe_key = notification_dedupe_key


def notification_deadline(
    level: str,
    created_at: Any,
    *,
    deadline_seconds: Optional[int] = None,
) -> Optional[str]:
    """Return a deterministic deadline for a notification level."""
    normalized = _upper(level)
    created = _as_datetime(created_at)
    if normalized not in NOTIFICATION_LEVELS or created is None:
        return None
    seconds = deadline_seconds if deadline_seconds is not None else NOTIFICATION_DEADLINES.get(normalized)
    if seconds is None:
        return None
    if isinstance(seconds, bool):
        return None
    try:
        seconds_value = int(seconds)
    except (TypeError, ValueError, OverflowError):
        return None
    if seconds_value <= 0:
        return None
    return _iso(created + timedelta(seconds=seconds_value))


def notification_decision(
    level: str,
    principal_id: str,
    event_type: str,
    resource_id: str,
    occurrence_key: str,
    *,
    created_at: Any = None,
    deadline_at: Any = None,
    deadline_seconds: Optional[int] = None,
    now: Any = None,
    already_exists: bool = False,
    suppress_requested: bool = False,
    external_requested: bool = False,
    external_authorized: bool = False,
    channel_classification: str = "INTERNAL",
    policy_version: str = "",
) -> ContractDecision:
    """Validate an actionable notification before durable enqueue."""
    severity = _upper(level)
    if severity not in NOTIFICATION_LEVELS:
        return _decision(False, "NOTIFICATION_LEVEL_INVALID", "notification level is not supported")
    try:
        dedupe_key = notification_dedupe_key(
            principal_id, event_type, resource_id, occurrence_key, policy_version=policy_version,
        )
    except ContractInputError:
        return _decision(False, "NOTIFICATION_IDENTITY_INVALID", "notification identity fields are required")
    created = _as_datetime(created_at) or (_as_datetime(now) or UTC_EPOCH)
    current_time = _as_datetime(now) or created
    classification = _upper(channel_classification)
    if classification not in CLASSIFICATION_LEVELS:
        return _decision(False, "NOTIFICATION_CLASSIFICATION_INVALID", "channel classification is not supported")
    if isinstance(deadline_seconds, bool) or (deadline_seconds is not None and _positive_int(deadline_seconds) in {None, 0}):
        return _decision(False, "NOTIFICATION_DEADLINE_INVALID", "deadline_seconds must be positive")
    deadline = _as_datetime(deadline_at) if deadline_at is not None else None
    if deadline_at is not None and deadline is None:
        return _decision(False, "NOTIFICATION_DEADLINE_INVALID", "deadline_at is invalid")
    if deadline is None:
        generated = notification_deadline(severity, created, deadline_seconds=deadline_seconds)
        deadline = _as_datetime(generated)
    if deadline is not None and deadline <= created:
        return _decision(False, "NOTIFICATION_DEADLINE_INVALID", "deadline must be after creation")
    if severity in {"ACTION_REQUIRED", "CRITICAL"} and deadline is None:
        return _decision(False, "NOTIFICATION_DEADLINE_REQUIRED", "action-required notifications need a deadline")
    if severity in {"ACTION_REQUIRED", "CRITICAL"} and deadline is not None and deadline <= current_time:
        return _decision(False, "NOTIFICATION_DEADLINE_EXPIRED", "required notification deadline has expired")
    if severity in {"ACTION_REQUIRED", "CRITICAL"} and suppress_requested:
        return _decision(False, "NOTIFICATION_SUPPRESSION_FORBIDDEN", "required notifications cannot be suppressed")
    if external_requested and classification != "PUBLIC" and not external_authorized:
        return _decision(False, "NOTIFICATION_EXTERNAL_CONTENT_DENY", "protected content cannot leave the approved domain")
    if already_exists:
        return _decision(
            False,
            "NOTIFICATION_DUPLICATE",
            "notification dedupe key already exists",
            action="NO_ENQUEUE",
            idempotent=True,
            dedupe_key=dedupe_key,
        )
    return _decision(
        True,
        "NOTIFICATION_ENQUEUE_ALLOWED",
        "notification may be durably enqueued",
        action="ENQUEUE",
        severity=severity,
        dedupe_key=dedupe_key,
        durable=severity in {"ACTION_REQUIRED", "CRITICAL"},
        suppressible=severity in {"INFO", "WARNING"},
        external_requested=external_requested,
        external_allowed=not external_requested or classification == "PUBLIC" or external_authorized,
        deadline_at=_iso(deadline),
        escalation_at=_iso(deadline) if severity in {"ACTION_REQUIRED", "CRITICAL"} else None,
    )


validate_notification = notification_decision


# ---------------------------------------------------------------------------
# Agent ownership and offboarding
# ---------------------------------------------------------------------------

AGENT_DISPOSITIONS = frozenset({
    "NO_ACTION",
    "SUSPEND",
    "QUARANTINE",
    "PAUSE",
    "OWNER_TRANSFER_REQUIRED",
    "TRANSFER_READY",
})


def owner_offboarding_disposition(
    owner_kind: str,
    environment: str,
    classification: str,
    *,
    owner_offboarded: bool = True,
    responsible_group: bool = False,
    approved_work: bool = False,
    continuity_authorized: bool = False,
    security_incident: bool = False,
    successor_id: str = "",
    successor_active: bool = False,
    transfer_approved: bool = False,
    credentials_rotated: bool = False,
    grants_reevaluated: bool = False,
) -> ContractDecision:
    """Select a conservative Agent disposition when ownership changes."""
    kind = _upper(owner_kind)
    env = _upper(environment)
    level = _upper(classification)
    if kind not in {"PERSONAL", "GROUP", "SYSTEM"}:
        return _decision(False, "AGENT_OWNER_KIND_INVALID", "owner kind is not supported")
    if level not in CLASSIFICATION_LEVELS:
        return _decision(False, "AGENT_CLASSIFICATION_INVALID", "classification is not supported")
    if not owner_offboarded:
        return _decision(True, "AGENT_OWNER_ACTIVE", "owner remains active", action="NO_ACTION", disposition="NO_ACTION", allow_approved_work=True, allow_new_work=True)
    if security_incident:
        return _decision(False, "AGENT_SECURITY_QUARANTINE", "security incident requires immediate quarantine", action="QUARANTINE", disposition="QUARANTINE", allow_approved_work=False, allow_new_work=False)
    if successor_id and successor_active and transfer_approved and credentials_rotated and grants_reevaluated:
        return _decision(True, "AGENT_TRANSFER_READY", "ownership transfer controls are complete", action="TRANSFER", disposition="TRANSFER_READY", allow_approved_work=False, allow_new_work=False)
    if level == "RESTRICTED" or env == "RESTRICTED":
        return _decision(False, "AGENT_RESTRICTED_PAUSE", "restricted Agents must pause during owner offboarding", action="PAUSE", disposition="PAUSE", allow_approved_work=False, allow_new_work=False, transfer_required=True)
    if kind == "PERSONAL":
        return _decision(False, "AGENT_PERSONAL_SUSPEND", "personal Agent must be suspended pending ownership review", action="SUSPEND", disposition="SUSPEND", allow_approved_work=False, allow_new_work=False, transfer_required=True)
    if env in {"PRODUCTION", "PROD"} and responsible_group:
        may_finish = bool(approved_work and continuity_authorized)
        return _decision(
            False,
            "AGENT_OWNER_TRANSFER_REQUIRED",
            "group-responsible production Agent requires ownership transfer",
            action="OWNER_TRANSFER_REQUIRED",
            disposition="OWNER_TRANSFER_REQUIRED",
            allow_approved_work=may_finish,
            allow_new_work=False,
            allow_new_high_risk_work=False,
            transfer_required=True,
        )
    return _decision(False, "AGENT_OWNER_TRANSFER_REQUIRED", "Agent work must stop until an owner is resolved", action="OWNER_TRANSFER_REQUIRED", disposition="OWNER_TRANSFER_REQUIRED", allow_approved_work=False, allow_new_work=False, transfer_required=True)


agent_offboarding_disposition = owner_offboarding_disposition


def owner_transfer_decision(
    current_owner_id: str,
    new_owner_id: str,
    *,
    new_owner_active: bool = False,
    policy_approved: bool = False,
    credentials_rotated: bool = False,
    grants_reevaluated: bool = False,
    security_domain_compatible: bool = True,
    actor_is_new_owner: bool = False,
) -> ContractDecision:
    """Validate the controls needed before an Agent owner transfer commits."""
    current = _text(current_owner_id)
    new = _text(new_owner_id)
    if not current or not new or current == new:
        return _decision(False, "AGENT_TRANSFER_OWNER_INVALID", "current and new owners must be distinct")
    if not new_owner_active:
        return _decision(False, "AGENT_TRANSFER_OWNER_INACTIVE", "new owner must be active")
    if actor_is_new_owner:
        return _decision(False, "AGENT_TRANSFER_SELF_APPROVAL", "new owner cannot approve its own transfer")
    if not security_domain_compatible:
        return _decision(False, "AGENT_TRANSFER_DOMAIN_DENY", "new owner is not eligible for the Security Domain")
    missing = []
    if not policy_approved:
        missing.append("policy_approval")
    if not credentials_rotated:
        missing.append("credential_rotation")
    if not grants_reevaluated:
        missing.append("grant_reevaluation")
    if missing:
        return _decision(False, "AGENT_TRANSFER_CONTROLS_INCOMPLETE", "ownership transfer controls are incomplete", reasons=missing, missing_controls=tuple(missing))
    return _decision(True, "AGENT_TRANSFER_ALLOWED", "ownership transfer may commit", action="TRANSFER", new_owner_id=new)


# ---------------------------------------------------------------------------
# Barrier retry, recovery, and escalation
# ---------------------------------------------------------------------------

BARRIER_STATES = frozenset({
    "OPEN", "ARRIVING", "QUORUM_REACHED", "REVIEWING", "REVIEW_REQUIRED", "DECIDED",
    "RELEASED", "REWORK", "CANCELLED", "EXPIRED",
})

BARRIER_TRANSITIONS = {
    "OPEN": frozenset({"ARRIVING", "CANCELLED", "EXPIRED"}),
    "ARRIVING": frozenset({"QUORUM_REACHED", "REVIEWING", "REWORK", "CANCELLED", "EXPIRED"}),
    "QUORUM_REACHED": frozenset({"REVIEWING", "DECIDED", "REWORK", "CANCELLED", "EXPIRED"}),
    "REVIEWING": frozenset({"DECIDED", "REWORK", "CANCELLED", "EXPIRED"}),
    "REVIEW_REQUIRED": frozenset({"DECIDED", "REWORK", "CANCELLED", "EXPIRED"}),
    "DECIDED": frozenset({"RELEASED", "REWORK", "CANCELLED"}),
    "RELEASED": frozenset(),
    "REWORK": frozenset({"ARRIVING", "REVIEWING", "CANCELLED", "EXPIRED"}),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset({"REVIEWING", "CANCELLED"}),
}


def barrier_transition_decision(
    current_status: str,
    requested_status: str,
    *,
    authorized: bool = False,
    expected_version_matches: bool = True,
    reason: str = "",
    evidence_present: bool = False,
) -> ContractDecision:
    """Validate a Barrier state transition and its decision evidence."""
    current = _upper(current_status)
    requested = _upper(requested_status)
    if current not in BARRIER_STATES or requested not in BARRIER_STATES:
        return _decision(False, "BARRIER_STATE_INVALID", "Barrier state is not supported")
    if current == requested:
        return _decision(True, "BARRIER_NO_CHANGE", "Barrier already has the requested state", state=current)
    if requested not in BARRIER_TRANSITIONS[current]:
        return _decision(False, "BARRIER_TRANSITION_FORBIDDEN", "Barrier transition is not allowed", state=current)
    if not authorized:
        return _decision(False, "BARRIER_AUTHORIZATION_REQUIRED", "authorized Barrier control is required", state=current)
    if not expected_version_matches:
        return _decision(False, "BARRIER_VERSION_CONFLICT", "Barrier fencing version is stale", state=current)
    if requested in {"DECIDED", "RELEASED", "REWORK", "CANCELLED", "EXPIRED"} and not _text(reason):
        return _decision(False, "BARRIER_REASON_REQUIRED", "a reason is required for this Barrier decision", state=current)
    if requested in {"DECIDED", "RELEASED"} and not evidence_present:
        return _decision(False, "BARRIER_EVIDENCE_REQUIRED", "decision evidence is required before release", state=current)
    return _decision(True, "BARRIER_TRANSITION_ALLOWED", "Barrier transition is allowed", action=requested, state=requested)


def barrier_recovery_decision(
    status: str = "ARRIVING",
    attempt_count: int = 0,
    max_retries: int = 0,
    *,
    security_tier: str = "INTERNAL",
    retry_allowed: bool = True,
    checkpoint_available: bool = False,
    checkpoint_authorized: bool = False,
    substitute_available: bool = False,
    substitute_authorized: bool = False,
    failed_roles: Optional[Iterable[str]] = None,
    required_roles: Optional[Iterable[str]] = None,
    quorum: int = 0,
    candidate_quorum: Optional[int] = None,
    arrived_count: int = 0,
    timed_out: bool = False,
    deadline_at: Any = None,
    now: Any = None,
    escalation_available: bool = False,
    human_decision_available: bool = False,
) -> ContractDecision:
    """Choose the next staged Barrier recovery action.

    The order is retry, checkpoint restoration, authorized substitute, and
    escalation.  No branch silently removes a required role or releases a
    restricted Barrier under a lower quorum.
    """
    state = _upper(status)
    tier = _upper(security_tier)
    if state not in BARRIER_STATES:
        return _decision(False, "BARRIER_STATE_INVALID", "Barrier state is not supported")
    if tier not in CLASSIFICATION_LEVELS:
        return _decision(False, "BARRIER_SECURITY_TIER_INVALID", "security tier is not supported")
    attempts = _positive_int(attempt_count)
    retries = _positive_int(max_retries)
    required = tuple(sorted({_text(item) for item in (required_roles or ()) if _text(item)}))
    failed = tuple(sorted({_text(item) for item in (failed_roles or ()) if _text(item)}))
    if attempts is None or retries is None:
        return _decision(False, "BARRIER_RETRY_COUNT_INVALID", "attempt counts must be non-negative")
    if candidate_quorum is not None:
        proposed = _positive_int(candidate_quorum)
        current_quorum = _positive_int(quorum)
        if proposed is None or current_quorum is None:
            return _decision(False, "BARRIER_QUORUM_INVALID", "quorum must be non-negative")
        if tier in {"CONFIDENTIAL", "RESTRICTED"} and proposed < current_quorum:
            return _decision(False, "BARRIER_QUORUM_LOWERING_FORBIDDEN", "protected Barrier quorum cannot be lowered", required_quorum=current_quorum, candidate_quorum=proposed)
    if state in {"RELEASED", "CANCELLED"}:
        return _decision(False, "BARRIER_TERMINAL", "terminal Barrier cannot recover", state=state)
    deadline = _as_datetime(deadline_at) if deadline_at is not None else None
    if deadline_at is not None and deadline is None:
        return _decision(False, "BARRIER_DEADLINE_INVALID", "deadline_at is invalid", state=state)
    current_time = _as_datetime(now) or UTC_EPOCH
    arrived = _positive_int(arrived_count)
    if arrived is None:
        return _decision(False, "BARRIER_ARRIVAL_COUNT_INVALID", "arrived_count must be non-negative", state=state)
    expired = bool(timed_out or (deadline is not None and current_time >= deadline))
    quorum_value = _positive_int(quorum, default=0) or 0
    ready = bool(quorum_value and arrived >= quorum_value and not failed)
    if not expired and not failed:
        if ready:
            return _decision(True, "BARRIER_READY_FOR_REVIEW", "Barrier has enough arrivals for governed review", action="REVIEW", state="QUORUM_REACHED", arrived_count=arrived, quorum=quorum_value)
        return _decision(True, "BARRIER_WAITING", "Barrier is waiting for arrivals", action="WAIT", state=state, arrived_count=arrived, quorum=quorum_value)
    if not expired and failed and retry_allowed and attempts < retries:
        return _decision(True, "BARRIER_RETRY_ALLOWED", "retry is the next recovery stage", action="RETRY", state=state, next_attempt=attempts + 1, max_retries=retries, required_roles=required)
    if checkpoint_available and checkpoint_authorized:
        return _decision(True, "BARRIER_CHECKPOINT_RESTORE_ALLOWED", "checkpoint restoration is the next recovery stage", action="RESTORE_CHECKPOINT", state="REWORK", required_roles=required, preserves_required_roles=True)
    if substitute_available and substitute_authorized:
        return _decision(True, "BARRIER_SUBSTITUTE_ALLOWED", "an authorized role substitute may be assigned", action="SUBSTITUTE", state="REVIEWING", required_roles=required, failed_roles=failed, preserves_required_roles=True, quorum=quorum_value)
    if substitute_available and not substitute_authorized:
        reason = "available substitute lacks authorization"
    elif failed:
        reason = "required participant failure has no authorized recovery"
    else:
        reason = "Barrier deadline requires governed escalation"
    if escalation_available or human_decision_available or tier in {"CONFIDENTIAL", "RESTRICTED"}:
        return _decision(True, "BARRIER_ESCALATION_REQUIRED", reason, action="HUMAN_DECISION_REQUIRED", state="REVIEWING", required_roles=required, failed_roles=failed, preserves_required_roles=True, quorum=quorum_value)
    return _decision(False, "BARRIER_RECOVERY_BLOCKED", reason, action="PAUSE", state=state, required_roles=required, failed_roles=failed, preserves_required_roles=True, quorum=quorum_value)


barrier_retry_decision = barrier_recovery_decision


# ---------------------------------------------------------------------------
# Runtime profile preflight and impact
# ---------------------------------------------------------------------------

PROFILES = frozenset({"PRODUCTION", "GRAPH-PREVIEW", "DEVELOPMENT", "EXPERIMENTAL-4.2"})
PROFILE_CAPABILITIES = {
    "PRODUCTION": frozenset({"stable_core", "channels", "barriers", "gateway", "graph_runtime", "governance"}),
    "GRAPH-PREVIEW": frozenset({"stable_core", "channels", "barriers", "gateway", "graph_runtime", "governance", "graph_preview", "graph_migration", "graph_dynamic"}),
    "DEVELOPMENT": frozenset({"stable_core", "channels", "barriers", "gateway", "graph_runtime", "governance", "graph_preview", "graph_migration", "graph_dynamic", "a2a_gateway", "otel_export", "experimental_connectors", "diagnostics"}),
    "EXPERIMENTAL-4.2": frozenset({"stable_core", "channels", "barriers", "gateway", "graph_runtime", "governance", "graph_preview", "graph_migration", "graph_dynamic", "a2a_gateway", "otel_export", "experimental_connectors"}),
}
DEFAULT_CAPABILITY_DEPENDENCIES = {
    "graph_preview": frozenset({"graph_runtime"}),
    "graph_migration": frozenset({"graph_runtime", "barriers", "governance"}),
    "graph_dynamic": frozenset({"graph_runtime", "graph_migration", "governance"}),
    "a2a_gateway": frozenset({"gateway", "graph_runtime", "governance"}),
    "otel_export": frozenset({"graph_runtime", "governance"}),
    "experimental_connectors": frozenset({"gateway", "governance"}),
}


def resolve_profile_capabilities(profile: str) -> frozenset:
    """Return the server-side default capability set for a profile."""
    return PROFILE_CAPABILITIES.get(_upper(profile).replace("_", "-"), frozenset())


def _normalize_capabilities(value: Optional[Iterable[str]], default: Iterable[str]) -> Set[str]:
    if value is None:
        return {_text(item).lower() for item in default if _text(item)}
    if isinstance(value, str):
        value = value.split(",")
    return {_text(item).lower() for item in value if _text(item)}


def _work_items(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = [value]
    if isinstance(value, int) and not isinstance(value, bool):
        return [{"id": f"active-{index + 1}", "capabilities": ()} for index in range(max(0, value))]
    result = []
    if isinstance(value, (str, bytes)):
        return [{"id": _text(value), "capabilities": ()}] if _text(value) else []
    try:
        items = list(value)
    except TypeError:
        return [{"id": "active-work", "capabilities": ()}]
    for index, item in enumerate(items):
        if isinstance(item, Mapping):
            result.append(dict(item))
        else:
            result.append({"id": _text(item) or f"active-{index + 1}", "capabilities": ()})
    return result


def profile_change_impact(
    current_profile: str,
    target_profile: str,
    *,
    current_capabilities: Optional[Iterable[str]] = None,
    target_capabilities: Optional[Iterable[str]] = None,
    active_work: Any = None,
    capability_dependencies: Optional[Mapping[str, Iterable[str]]] = None,
) -> Dict[str, Any]:
    """Compute profile delta and active-work impact without authorization."""
    current_name = _upper(current_profile).replace("_", "-")
    target_name = _upper(target_profile).replace("_", "-")
    current = _normalize_capabilities(current_capabilities, resolve_profile_capabilities(current_name))
    target = _normalize_capabilities(target_capabilities, resolve_profile_capabilities(target_name))
    dependencies = dict(DEFAULT_CAPABILITY_DEPENDENCIES)
    for key, values in (capability_dependencies or {}).items():
        dependencies[_text(key).lower()] = frozenset(_text(item).lower() for item in values if _text(item))
    removed = sorted(current - target)
    added = sorted(target - current)
    missing_dependencies = {
        capability: sorted(dependencies.get(capability, ()))
        for capability in sorted(target)
        if not set(dependencies.get(capability, ())).issubset(target)
    }
    work = _work_items(active_work)
    impacted = []
    for item in work:
        required = _normalize_capabilities(item.get("capabilities"), ())
        lost = sorted(required - target)
        if lost:
            impacted.append({"id": _text(item.get("id")) or "active-work", "lost_capabilities": lost, "status": _text(item.get("status")) or "ACTIVE"})
    return {
        "current_profile": current_name,
        "target_profile": target_name,
        "current_capabilities": sorted(current),
        "target_capabilities": sorted(target),
        "added_capabilities": added,
        "removed_capabilities": removed,
        "missing_dependencies": missing_dependencies,
        "active_work_count": len(work),
        "impacted_work": impacted,
        "requires_restart": current_name != target_name or bool(added or removed),
        "risk": "HIGH" if impacted or missing_dependencies else "MEDIUM" if added or removed else "LOW",
    }


def profile_change_preflight(
    current_profile: str,
    target_profile: str,
    *,
    authorized: bool = False,
    reason: str = "",
    current_capabilities: Optional[Iterable[str]] = None,
    target_capabilities: Optional[Iterable[str]] = None,
    active_work: Any = None,
    dependency_status: Optional[Mapping[str, Any]] = None,
    data_readiness: Optional[Mapping[str, Any]] = None,
    capability_dependencies: Optional[Mapping[str, Iterable[str]]] = None,
    incompatible_capabilities: Optional[Iterable[Sequence[str]]] = None,
    restart_available: bool = True,
    controlled_activation_available: bool = False,
    audit_available: bool = True,
) -> ContractDecision:
    """Perform profile dependency, data, work, and activation preflight."""
    current_name = _upper(current_profile).replace("_", "-")
    target_name = _upper(target_profile).replace("_", "-")
    if current_name not in PROFILES or target_name not in PROFILES:
        return _decision(False, "PROFILE_INVALID", "runtime profile is not supported")
    impact = profile_change_impact(
        current_name,
        target_name,
        current_capabilities=current_capabilities,
        target_capabilities=target_capabilities,
        active_work=active_work,
        capability_dependencies=capability_dependencies,
    )
    if current_name == target_name and not impact["requires_restart"] and not _text(reason):
        return _decision(True, "PROFILE_NO_CHANGE", "runtime profile is unchanged", action="NO_CHANGE", state=current_name, impact=impact)
    if not authorized:
        return _decision(False, "PROFILE_AUTHORIZATION_REQUIRED", "profile change requires governed administration", state=current_name, impact=impact)
    if not _text(reason):
        return _decision(False, "PROFILE_REASON_REQUIRED", "profile change reason is required", state=current_name, impact=impact)
    if not audit_available:
        return _decision(False, "PROFILE_AUDIT_UNAVAILABLE", "profile change cannot proceed without audit evidence", state=current_name, impact=impact)
    blockers: List[str] = []
    if impact["missing_dependencies"]:
        blockers.append("MISSING_CAPABILITY_DEPENDENCY")
    status = {str(key).lower(): value for key, value in (dependency_status or {}).items()}
    for capability in impact["added_capabilities"]:
        value = status.get(capability)
        if isinstance(value, Mapping):
            ready = bool(value.get("ready", value.get("available", False)))
        elif value is None:
            ready = True
        else:
            ready = bool(value)
        if not ready:
            blockers.append("DEPENDENCY_NOT_READY:" + capability)
    readiness = {str(key).lower(): value for key, value in (data_readiness or {}).items()}
    for capability in impact["added_capabilities"]:
        if capability in readiness and not bool(readiness[capability]):
            blockers.append("DATA_NOT_READY:" + capability)
    target = set(impact["target_capabilities"])
    for pair in incompatible_capabilities or ():
        if len(pair) != 2:
            blockers.append("INCOMPATIBLE_CAPABILITY_SPEC_INVALID")
            continue
        left, right = _text(pair[0]).lower(), _text(pair[1]).lower()
        if left and right and left in target and right in target:
            blockers.append(f"INCOMPATIBLE_CAPABILITIES:{left}:{right}")
    if impact["impacted_work"]:
        blockers.append("ACTIVE_WORK_DEPENDENCY")
    if impact["requires_restart"] and not (restart_available or controlled_activation_available):
        blockers.append("ACTIVATION_UNAVAILABLE")
    if blockers:
        return _decision(False, "PROFILE_PREFLIGHT_BLOCKED", "profile change has unresolved preflight blockers", state=current_name, reasons=blockers, blockers=tuple(blockers), impact=impact, controlled_activation=controlled_activation_available)
    return _decision(True, "PROFILE_PREFLIGHT_ALLOWED", "profile change passed preflight", action="ACTIVATE", state=target_name, reasons=(), blockers=(), impact=impact, controlled_activation=controlled_activation_available, audit_required=True)


preflight_profile_change = profile_change_preflight


# Compatibility helpers used by the database service layer.  They intentionally
# return small dictionaries because the service layer also needs to persist the
# operational effects alongside the pure decision object.
class GovernanceContractError(ValueError):
    """Raised when a database mutation does not satisfy a pure contract."""


def validate_channel_transition(
    current: str,
    target: str,
    *,
    legal_hold: bool = False,
    referenced_objects: int = 0,
    deletion_after: Any = None,
    now: Any = None,
    reason: str = "",
    authorized: bool = True,
    active_work: bool = False,
    quiesced: bool = True,
    retention_expired: Optional[bool] = None,
    deletion_approved: bool = True,
    recovery_authorized: bool = True,
    investigation_authorized: bool = True,
) -> Dict[str, Any]:
    """Return the legacy service-layer shape for the full lifecycle contract.

    The v4.3 service passes runtime facts such as active work and recovery
    authorization.  Keeping those arguments here preserves one authoritative
    decision function while allowing older callers to use the compact dict
    returned by this compatibility facade.
    """
    deadline = _as_datetime(deletion_after)
    current_time = _as_datetime(now)
    if retention_expired is None:
        retention_expired = deadline is None or current_time is None or current_time >= deadline
    decision = channel_lifecycle_decision(
        current, target, authorized=authorized, legal_hold=legal_hold,
        reference_count=referenced_objects, active_work=active_work, quiesced=quiesced,
        retention_expired=bool(retention_expired), deletion_approved=deletion_approved,
        deletion_deadline=deletion_after, now=now,
        recovery_authorized=recovery_authorized,
        investigation_authorized=investigation_authorized,
    )
    if not decision.allowed:
        raise GovernanceContractError(decision.message)
    destination = _upper(target)
    return {
        "current": _upper(current), "target": destination,
        "reason": _text(reason)[:2000], "referenced_objects": int(referenced_objects or 0),
        "legal_hold": bool(legal_hold), "effects": {
            "stop_new_work": destination != "ACTIVE",
            "revoke_temporary_access": destination in {"ARCHIVED", "QUARANTINED", "DELETION_PENDING", "DELETED"},
            "block_propagation": destination in {"FROZEN", "QUARANTINED", "DELETION_PENDING", "DELETED"},
            "block_memory_promotion": destination in {"FROZEN", "QUARANTINED", "DELETION_PENDING", "DELETED"},
            "preserve_evidence": bool(legal_hold) or destination in {"FROZEN", "QUARANTINED"},
        },
    }


def validate_bridge_request(
    source_domain: str,
    target_domain: str,
    mode: str,
    classification: str,
    *,
    target_minimum: str = "PUBLIC",
    full_copy_enabled: bool = False,
    recipients: Sequence[str] | None = None,
    purpose: str = "",
    reason: str = "",
    expires_at: Any = None,
    now: Any = None,
) -> Dict[str, Any]:
    levels = CLASSIFICATION_LEVELS
    selected = _upper(mode)
    source_level = levels.get(_upper(classification), -1)
    target_level = levels.get(_upper(target_minimum), -1)
    if source_level < 0 or target_level < 0 or source_level < target_level:
        raise GovernanceContractError("Bridge classification is below the target minimum")
    decision = bridge_transfer_decision(
        source_domain, target_domain, selected, phase="PROPOSE", purpose=purpose,
        reason=reason, classification=classification, recipients=recipients,
        policy_version="1", expires_at=expires_at, now=now,
        proposer_id="human", approver_id="", full_copy_enabled=full_copy_enabled,
        source_body_authorized=False, source_object_id="bridge-proposal",
        provenance={"proposed": True},
    )
    if not decision.allowed:
        raise GovernanceContractError(decision.message)
    return {
        "source_domain_id": str(source_domain), "target_domain_id": str(target_domain),
        "transfer_mode": selected, "classification": _upper(classification),
        "recipients": tuple(sorted({_text(item) for item in (recipients or ()) if _text(item)})),
        "purpose": _text(purpose)[:2000], "reason": _text(reason)[:2000],
        "expires_at": _iso(_as_datetime(expires_at)), "requires_approval": True,
        "source_reauthorization": selected == "REFERENCE",
    }


def build_notification(
    principal_id: str, notification_type: str, level: str, dedupe_key: str,
    payload: Optional[Mapping[str, Any]] = None, *, deadline_at: Any = None,
) -> Dict[str, Any]:
    severity = _upper(level)
    if not _text(principal_id) or not _text(notification_type) or not _text(dedupe_key):
        raise GovernanceContractError("notification identity, type and dedupe key are required")
    if severity not in NOTIFICATION_LEVELS:
        raise GovernanceContractError("notification level is invalid")
    deadline = _as_datetime(deadline_at) if deadline_at is not None else None
    if severity in {"ACTION_REQUIRED", "CRITICAL"} and deadline is None:
        raise GovernanceContractError("required notification deadline is required")
    return {
        "principal_id": _text(principal_id), "notification_type": _text(notification_type)[:64],
        "level": severity, "dedupe_key": _text(dedupe_key)[:256], "payload": dict(payload or {}),
        "deadline_at": _iso(deadline), "required_action": severity in {"ACTION_REQUIRED", "CRITICAL"},
        "externally_suppressible": severity != "CRITICAL",
    }


def owner_disposition(*, owner_type: str, has_responsible_group: bool, agent_environment: str = "DEVELOPMENT", evidence: str = "") -> Dict[str, Any]:
    kind = _upper(owner_type)
    if not _text(evidence):
        raise GovernanceContractError("ownership disposition evidence is required")
    if kind == "SYSTEM_MANAGED":
        disposition = "SYSTEM_MANAGED"
    elif kind == "DEMO":
        disposition = "DEMO_ISOLATED"
    elif has_responsible_group and _upper(agent_environment) in {"PRODUCTION", "PROD"}:
        disposition = "TRANSFER_REQUIRED"
    elif has_responsible_group:
        disposition = "SUSPEND"
    elif _upper(agent_environment) in {"PRODUCTION", "PROD"}:
        disposition = "QUARANTINE"
    else:
        disposition = "UNCLAIMED"
    return {"disposition": disposition, "new_work_allowed": disposition == "SYSTEM_MANAGED", "revoke_credentials": disposition not in {"SYSTEM_MANAGED", "DEMO_ISOLATED"}, "evidence": _text(evidence)[:2000]}


# ---------------------------------------------------------------------------
# Human identity, delegation, and governed content extensions
# ---------------------------------------------------------------------------

IDENTITY_LINK_TYPES = frozenset({"LDAP", "OIDC"})
MFA_METHODS = frozenset({"TOTP", "WEBAUTHN", "RECOVERY_CODE"})
AGENT_RELATIONSHIP_ROLES = frozenset({"PRIMARY_OWNER", "SPONSOR", "OPERATOR", "VIEWER"})
LEGACY_AGENT_STATES = frozenset({
    "PROVEN_OWNED", "SYSTEM_MANAGED", "OWNER_REVIEW_REQUIRED", "UNCLAIMED", "DEMO_ISOLATED",
})
BRIDGE_CONNECTOR_MODES = frozenset({"QUEUE", "WEBHOOK"})


def identity_link_decision(
    identity_type: str,
    provider: str,
    subject_key: str,
    *,
    actor_id: str = "",
    target_principal_id: str = "",
    current_identity_proven: bool = False,
    target_mfa_satisfied: bool = False,
    approval_required: bool = True,
    approval_present: bool = False,
    existing_principal_id: str = "",
    reason: str = "",
) -> ContractDecision:
    """Validate an LDAP/OIDC link without treating email as an identity key."""
    kind = _upper(identity_type)
    if kind not in IDENTITY_LINK_TYPES:
        return _decision(False, "IDENTITY_LINK_TYPE_INVALID", "only LDAP and OIDC identities may be linked")
    if not _text(provider) or not _text(subject_key):
        return _decision(False, "IDENTITY_LINK_SUBJECT_REQUIRED", "provider and immutable subject are required")
    if not _text(actor_id) or not _text(target_principal_id):
        return _decision(False, "IDENTITY_LINK_ACTOR_REQUIRED", "authenticated actor and target Principal are required")
    if existing_principal_id and _text(existing_principal_id) != _text(target_principal_id):
        return _decision(False, "IDENTITY_LINK_ALREADY_BOUND", "the provider subject is already bound to another Principal")
    if not current_identity_proven or not target_mfa_satisfied:
        return _decision(False, "IDENTITY_LINK_PROOF_REQUIRED", "proof of both identities and configured MFA are required")
    if approval_required and not approval_present:
        return _decision(False, "IDENTITY_LINK_APPROVAL_REQUIRED", "identity linking approval is required")
    if not _text(reason):
        return _decision(False, "IDENTITY_LINK_REASON_REQUIRED", "identity linking reason is required")
    return _decision(True, "IDENTITY_LINK_ALLOWED", "identity may be linked", action="LINK", provider=provider[:256], subject_key=subject_key[:512])


def password_recovery_decision(
    *,
    purpose: str,
    principal_active: bool,
    token_valid: bool = False,
    token_consumed: bool = False,
    token_expired: bool = False,
    mfa_satisfied: bool = False,
    recovery_channel_authorized: bool = False,
    replacement_password_valid: bool = False,
) -> ContractDecision:
    """Keep reset/recovery credentials separate from Sessions and enrollment."""
    kind = _upper(purpose)
    if kind not in {"PASSWORD_RESET", "ACCOUNT_RECOVERY"}:
        return _decision(False, "RECOVERY_PURPOSE_INVALID", "recovery purpose is invalid")
    if not principal_active:
        return _decision(False, "RECOVERY_PRINCIPAL_INACTIVE", "account recovery is unavailable")
    if token_consumed or token_expired or not token_valid:
        return _decision(False, "RECOVERY_TOKEN_INVALID", "recovery token is invalid or expired")
    if not recovery_channel_authorized:
        return _decision(False, "RECOVERY_CHANNEL_DENY", "the recovery channel is not authorized")
    if kind == "ACCOUNT_RECOVERY" and not mfa_satisfied:
        return _decision(False, "RECOVERY_MFA_REQUIRED", "account recovery requires an independent MFA or recovery factor")
    if not replacement_password_valid:
        return _decision(False, "RECOVERY_PASSWORD_INVALID", "replacement password does not meet policy")
    return _decision(True, "RECOVERY_ALLOWED", "credential recovery may commit", action="RESET_PASSWORD")


def mfa_admission_decision(
    *,
    principal_active: bool,
    required: bool,
    level: str = "NONE",
    accepted: bool = False,
    method: str = "",
    challenge_expired: bool = False,
) -> ContractDecision:
    """Decide whether a login may create a Session after password auth."""
    if not principal_active:
        return _decision(False, "MFA_PRINCIPAL_INACTIVE", "authentication is unavailable")
    normalized = _upper(level)
    if normalized not in {"NONE", "SINGLE", "STRONG"}:
        return _decision(False, "MFA_LEVEL_INVALID", "MFA level is invalid")
    if not required:
        return _decision(True, "MFA_NOT_REQUIRED", "password authentication is sufficient", action="CREATE_SESSION", level="NONE")
    if challenge_expired or not accepted or _upper(method) not in MFA_METHODS:
        return _decision(False, "MFA_REQUIRED", "a valid MFA challenge is required", action="CHALLENGE")
    return _decision(True, "MFA_ACCEPTED", "MFA admission is satisfied", action="CREATE_SESSION", level="STRONG", method=_upper(method))


def delegation_decision(
    grantor_id: str,
    grantee_id: str,
    permissions: Sequence[str],
    data_scope: str,
    *,
    grantor_permissions: Iterable[str] = (),
    target_scope: str = "NONE",
    valid_until: Any = None,
    now: Any = None,
    reason: str = "",
    self_elevation: bool = False,
    separation_required: bool = False,
    separation_satisfied: bool = False,
) -> ContractDecision:
    """A delegation can only narrow the grantor's current authority."""
    if not _text(grantor_id) or not _text(grantee_id) or _text(grantor_id) == _text(grantee_id):
        return _decision(False, "DELEGATION_PRINCIPAL_INVALID", "grantor and grantee must be distinct")
    if self_elevation:
        return _decision(False, "DELEGATION_SELF_ELEVATION", "delegation cannot be used for self elevation")
    if not _text(reason):
        return _decision(False, "DELEGATION_REASON_REQUIRED", "delegation reason is required")
    requested = {_text(item) for item in permissions if _text(item)}
    available = {_text(item) for item in grantor_permissions if _text(item)}
    if not requested or not all(item in available or "*" in available for item in requested):
        return _decision(False, "DELEGATION_PERMISSION_EXPANSION", "delegation cannot grant an action the grantor lacks")
    scope = _upper(data_scope)
    parent_scope = _upper(target_scope)
    if scope not in SCOPES or parent_scope not in SCOPES:
        return _decision(False, "DELEGATION_SCOPE_INVALID", "delegation data scope is invalid")
    if parent_scope != "NONE" and scope == "ALL" and parent_scope != "ALL":
        return _decision(False, "DELEGATION_SCOPE_EXPANSION", "delegation cannot broaden the parent data scope")
    expiry = _as_datetime(valid_until)
    current = _as_datetime(now) or UTC_EPOCH
    if expiry is not None and expiry <= current:
        return _decision(False, "DELEGATION_EXPIRED", "delegation validity has expired")
    if separation_required and not separation_satisfied:
        return _decision(False, "DELEGATION_SEPARATION_REQUIRED", "separation of duties is required")
    return _decision(True, "DELEGATION_ALLOWED", "delegation may be committed", action="GRANT", permissions=tuple(sorted(requested)), data_scope=scope, valid_until=_iso(expiry))


def agent_relationship_decision(
    role: str,
    *,
    agent_id: str,
    principal_id: str,
    active: bool = True,
    existing_primary_owner: str = "",
    actor_is_new_owner: bool = False,
    reason: str = "",
) -> ContractDecision:
    """Validate explicit Agent relationship roles and owner uniqueness."""
    normalized = _upper(role)
    if normalized not in AGENT_RELATIONSHIP_ROLES:
        return _decision(False, "AGENT_RELATIONSHIP_ROLE_INVALID", "Agent relationship role is invalid")
    if not _text(agent_id) or not _text(principal_id):
        return _decision(False, "AGENT_RELATIONSHIP_ID_REQUIRED", "Agent and Principal are required")
    if not active:
        return _decision(False, "AGENT_RELATIONSHIP_PRINCIPAL_INACTIVE", "relationship Principal is inactive")
    if normalized == "PRIMARY_OWNER" and existing_primary_owner and _text(existing_primary_owner) != _text(principal_id):
        return _decision(False, "AGENT_PRIMARY_OWNER_EXISTS", "an Agent may have only one active primary owner")
    if normalized == "PRIMARY_OWNER" and actor_is_new_owner:
        return _decision(False, "AGENT_OWNER_SELF_APPROVAL", "the new owner cannot approve its own relationship")
    if not _text(reason):
        return _decision(False, "AGENT_RELATIONSHIP_REASON_REQUIRED", "relationship reason is required")
    return _decision(True, "AGENT_RELATIONSHIP_ALLOWED", "Agent relationship may be committed", action="ASSIGN", role=normalized)


def classify_legacy_agent(
    *,
    owner_proof: bool = False,
    system_managed: bool = False,
    demo: bool = False,
    responsible_group: bool = False,
    environment: str = "DEVELOPMENT",
    evidence: str = "",
) -> ContractDecision:
    """Classify legacy ownership without trusting display text or current user."""
    if not _text(evidence):
        return _decision(False, "LEGACY_EVIDENCE_REQUIRED", "legacy ownership evidence is required")
    if demo:
        state = "DEMO_ISOLATED"
    elif system_managed:
        state = "SYSTEM_MANAGED"
    elif owner_proof:
        state = "PROVEN_OWNED"
    elif responsible_group or _upper(environment) in {"PRODUCTION", "PROD"}:
        state = "OWNER_REVIEW_REQUIRED"
    else:
        state = "UNCLAIMED"
    return _decision(True, "LEGACY_AGENT_CLASSIFIED", "legacy Agent was conservatively classified", action="REVIEW", state=state, evidence=_text(evidence)[:2000], new_work_allowed=state == "SYSTEM_MANAGED")


def memory_promotion_decision(
    destination_scope: str,
    *,
    current_scope: str = "CHANNEL",
    source_authorized: bool = False,
    approver_authorized: bool = False,
    classification_allowed: bool = False,
    provenance_present: bool = False,
    reason: str = "",
    supersedes_id: str = "",
) -> ContractDecision:
    """Prevent a Memory Candidate from silently widening its retrieval scope."""
    destinations = {"RUNTIME_CONTEXT", "CHANNEL_MEMORY", "AGENT_MEMORY", "ENTERPRISE_KNOWLEDGE"}
    scope = _upper(destination_scope)
    current = _upper(current_scope)
    if scope not in destinations or current not in destinations:
        return _decision(False, "MEMORY_SCOPE_INVALID", "memory destination scope is invalid")
    order = {"RUNTIME_CONTEXT": 0, "CHANNEL_MEMORY": 1, "AGENT_MEMORY": 2, "ENTERPRISE_KNOWLEDGE": 3}
    if order[scope] > order[current] and not approver_authorized:
        return _decision(False, "MEMORY_SCOPE_EXPANSION", "broader memory scope requires explicit approval")
    if not source_authorized or not approver_authorized:
        return _decision(False, "MEMORY_AUTHORIZATION_REQUIRED", "current source access and approval are required")
    if not classification_allowed:
        return _decision(False, "MEMORY_CLASSIFICATION_DENY", "memory classification is not allowed in the destination")
    if not provenance_present:
        return _decision(False, "MEMORY_PROVENANCE_REQUIRED", "memory provenance is required")
    if not _text(reason):
        return _decision(False, "MEMORY_REASON_REQUIRED", "memory promotion reason is required")
    return _decision(True, "MEMORY_PROMOTION_ALLOWED", "memory candidate may be promoted", action="PROMOTE", destination_scope=scope, supersedes_id=_text(supersedes_id) or None)


def artifact_access_decision(
    *,
    artifact_classification: str,
    principal_clearance: str,
    source_authorized: bool,
    include_content: bool = False,
    legal_hold: bool = False,
    retention_expired: bool = False,
) -> ContractDecision:
    """Return metadata-only access when body access is not currently justified."""
    try:
        artifact_level = CLASSIFICATION_LEVELS[_upper(artifact_classification)]
        principal_level = CLASSIFICATION_LEVELS[_upper(principal_clearance)]
    except KeyError:
        return _decision(False, "ARTIFACT_CLASSIFICATION_INVALID", "Artifact classification is invalid")
    if not source_authorized or principal_level < artifact_level:
        return _decision(False, "ARTIFACT_ACCESS_DENY", "Artifact is outside the current authorization scope", content_allowed=False)
    if include_content and retention_expired and not legal_hold:
        return _decision(False, "ARTIFACT_RETENTION_EXPIRED", "Artifact content retention has expired", content_allowed=False)
    return _decision(True, "ARTIFACT_ACCESS_ALLOWED", "Artifact access is allowed", action="READ", content_allowed=bool(include_content), metadata_allowed=True, legal_hold=legal_hold)


def connector_decision(
    mode: str,
    *,
    enterprise: bool,
    restricted_domain: bool = False,
    metadata_only: bool = True,
    endpoint_authorized: bool = False,
    secret_ref_present: bool = False,
    reason: str = "",
) -> ContractDecision:
    """Gate optional queue/webhook delivery; default to metadata-only."""
    connector = _upper(mode)
    if connector not in BRIDGE_CONNECTOR_MODES:
        return _decision(False, "CONNECTOR_MODE_INVALID", "connector mode is invalid")
    if not enterprise:
        return _decision(False, "CONNECTOR_ENTERPRISE_REQUIRED", "external connectors require Enterprise")
    if restricted_domain and not endpoint_authorized:
        return _decision(False, "CONNECTOR_RESTRICTED_DENY", "restricted domains require explicit endpoint authorization")
    if not metadata_only and not secret_ref_present:
        return _decision(False, "CONNECTOR_SECRET_REF_REQUIRED", "content delivery requires a governed secret reference")
    if not _text(reason):
        return _decision(False, "CONNECTOR_REASON_REQUIRED", "connector reason is required")
    return _decision(True, "CONNECTOR_ALLOWED", "connector may be enabled", action="ENABLE", metadata_only=bool(metadata_only))


__all__ = [
    "AGENT_DISPOSITIONS",
    "BARRIER_STATES",
    "BRIDGE_MODES",
    "CHANNEL_STATUSES",
    "CLASSIFICATION_LEVELS",
    "ContractDecision",
    "ContractInputError",
    "NOTIFICATION_LEVELS",
    "PROFILES",
    "agent_offboarding_disposition",
    "agent_relationship_decision",
    "artifact_access_decision",
    "barrier_recovery_decision",
    "barrier_retry_decision",
    "barrier_transition_decision",
    "bridge_transfer_decision",
    "channel_can_delete",
    "channel_lifecycle_decision",
    "classify_legacy_agent",
    "connector_decision",
    "delegation_decision",
    "identity_link_decision",
    "make_notification_dedupe_key",
    "memory_promotion_decision",
    "mfa_admission_decision",
    "notification_deadline",
    "notification_decision",
    "notification_dedupe_key",
    "owner_offboarding_disposition",
    "owner_transfer_decision",
    "password_recovery_decision",
    "preflight_profile_change",
    "profile_change_impact",
    "profile_change_preflight",
    "resolve_profile_capabilities",
    "validate_bridge_transfer",
    "validate_channel_lifecycle",
    "validate_notification",
]
