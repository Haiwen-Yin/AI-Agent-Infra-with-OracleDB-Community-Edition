"""Pure contract tests for the v4.3 governed Channel boundary."""

from datetime import datetime, timezone

import pytest

from lib.governed_contracts import (
    ContractInputError,
    agent_offboarding_disposition,
    barrier_recovery_decision,
    barrier_transition_decision,
    bridge_transfer_decision,
    channel_lifecycle_decision,
    make_notification_dedupe_key,
    notification_deadline,
    notification_decision,
    owner_transfer_decision,
    profile_change_impact,
    profile_change_preflight,
    resolve_profile_capabilities,
)


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def test_channel_deletion_is_delayed_and_reference_aware():
    pending = channel_lifecycle_decision(
        "ACTIVE",
        "DELETION_PENDING",
        authorized=True,
        quiesced=True,
        reference_count=2,
    )
    assert pending.allowed
    assert pending.action == "SCHEDULE_DELETION"
    assert pending["deletion_blocked_by_references"] is True

    blocked = channel_lifecycle_decision(
        "DELETION_PENDING",
        "DELETED",
        authorized=True,
        quiesced=True,
        reference_count=1,
        retention_expired=True,
        deletion_approved=True,
        now=NOW,
    )
    assert not blocked
    assert blocked.code == "CHANNEL_REFERENCES_REMAIN"

    allowed = channel_lifecycle_decision(
        "DELETION_PENDING",
        "DELETED",
        authorized=True,
        quiesced=True,
        retention_expired=True,
        deletion_approved=True,
        deletion_deadline=NOW,
        now=NOW,
    )
    assert allowed.allowed
    assert allowed.state == "DELETED"


def test_channel_hold_work_and_transition_boundaries_fail_closed():
    held = channel_lifecycle_decision(
        "FROZEN",
        "DELETED",
        authorized=True,
        legal_hold=True,
        quiesced=True,
        retention_expired=True,
        deletion_approved=True,
        now=LATER,
    )
    assert held.code == "CHANNEL_LEGAL_HOLD"

    pending_hold = channel_lifecycle_decision(
        "ACTIVE",
        "DELETION_PENDING",
        authorized=True,
        legal_hold=True,
        quiesced=True,
    )
    assert pending_hold.code == "CHANNEL_LEGAL_HOLD"

    work = channel_lifecycle_decision(
        "ACTIVE",
        "ARCHIVED",
        authorized=True,
        active_work=True,
        quiesced=False,
    )
    assert work.code == "CHANNEL_WORK_NOT_QUIESCED"

    unauthorized = channel_lifecycle_decision("ACTIVE", "READ_ONLY")
    assert unauthorized.code == "CHANNEL_AUTHORIZATION_REQUIRED"
    assert not channel_lifecycle_decision("ACTIVE", "DELETED", authorized=True)
    assert channel_lifecycle_decision("DELETED", "DELETED").allowed


def test_channel_quarantine_requires_controlled_recovery():
    quarantine = channel_lifecycle_decision("ACTIVE", "QUARANTINED", authorized=True)
    assert quarantine.allowed

    denied = channel_lifecycle_decision(
        "QUARANTINED", "ACTIVE", authorized=True, recovery_authorized=True,
    )
    assert denied.code == "CHANNEL_QUARANTINE_RECOVERY_REQUIRED"

    recovered = channel_lifecycle_decision(
        "QUARANTINED",
        "READ_ONLY",
        authorized=True,
        recovery_authorized=True,
        investigation_authorized=True,
    )
    assert recovered.allowed


def _bridge_kwargs():
    return {
        "purpose": "controlled review",
        "reason": "approved incident analysis",
        "classification": "CONFIDENTIAL",
        "recipients": ["reviewer-1"],
        "policy_version": "policy-7",
        "expires_at": LATER,
        "now": NOW,
        "proposer_id": "agent-1",
        "source_object_id": "message-1",
        "provenance": {"channel_id": "channel-1", "digest": "abc"},
    }


def test_bridge_proposal_and_approved_delivery_have_distinct_gates():
    proposal = bridge_transfer_decision("domain-a", "domain-b", "SUMMARY", **_bridge_kwargs())
    assert proposal.allowed
    assert proposal.state == "PENDING"
    assert proposal["content_allowed"] is False
    assert proposal["risk_level"] == "MEDIUM"

    not_approved = bridge_transfer_decision(
        "domain-a", "domain-b", "SUMMARY", phase="DELIVER", source_body_authorized=True,
        summary_confirmed=True, **_bridge_kwargs(),
    )
    assert not not_approved
    assert not_approved.code == "BRIDGE_APPROVAL_REQUIRED"

    approved = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "SUMMARY",
        phase="DELIVER",
        approval_status="APPROVED",
        approver_id="human-1",
        source_body_authorized=True,
        summary_confirmed=True,
        **_bridge_kwargs(),
    )
    assert approved.allowed
    assert approved["content_allowed"] is True


def test_bridge_rejects_same_domain_full_copy_self_approval_and_bad_expiry():
    same_domain = bridge_transfer_decision("domain-a", "domain-a", "REFERENCE", **_bridge_kwargs())
    assert same_domain.code == "BRIDGE_DOMAIN_INVALID"

    full_copy = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "FULL_COPY",
        approval_status="APPROVED",
        approver_id="human-1",
        full_copy_enabled=False,
        source_body_authorized=True,
        **_bridge_kwargs(),
    )
    assert full_copy.code == "BRIDGE_FULL_COPY_DISABLED"

    self_approval = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "REFERENCE",
        approval_status="APPROVED",
        approver_id="agent-1",
        source_body_authorized=True,
        **_bridge_kwargs(),
    )
    assert self_approval.code == "BRIDGE_SELF_APPROVAL"

    expiry = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "REFERENCE",
        expires_at=NOW,
        now=NOW,
        **{key: value for key, value in _bridge_kwargs().items() if key not in {"expires_at", "now"}},
    )
    assert expiry.code == "BRIDGE_EXPIRY_INVALID"


def test_bridge_read_reauthorizes_reference_and_preserves_provenance_contract():
    denied = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "REFERENCE",
        phase="READ",
        approval_status="APPROVED",
        approver_id="human-1",
        source_body_authorized=False,
        **_bridge_kwargs(),
    )
    assert denied.code == "BRIDGE_SOURCE_REAUTH_REQUIRED"
    assert denied["content_allowed"] is False

    authorized = bridge_transfer_decision(
        "domain-a",
        "domain-b",
        "REFERENCE",
        phase="READ",
        approval_status="APPROVED",
        approver_id="human-1",
        source_body_authorized=True,
        **_bridge_kwargs(),
    )
    assert authorized.allowed
    assert authorized["content_allowed"] is True


def test_notification_key_is_stable_and_required_levels_are_durable():
    first = make_notification_dedupe_key("user-1", "BARRIER", "barrier-1", "decision-1", policy_version="p1")
    second = make_notification_dedupe_key("user-1", "barrier", "barrier-1", "decision-1", policy_version="p1")
    assert first == second
    assert first != make_notification_dedupe_key("user-2", "BARRIER", "barrier-1", "decision-1", policy_version="p1")
    with pytest.raises(ContractInputError):
        make_notification_dedupe_key("", "BARRIER", "barrier-1", "decision-1")

    notification = notification_decision(
        "ACTION_REQUIRED",
        "user-1",
        "BARRIER",
        "barrier-1",
        "decision-1",
        created_at=NOW,
        now=NOW,
    )
    assert notification.allowed
    assert notification["durable"] is True
    assert notification["suppressible"] is False
    assert notification["deadline_at"].endswith("Z")

    duplicate = notification_decision(
        "ACTION_REQUIRED", "user-1", "BARRIER", "barrier-1", "decision-1",
        created_at=NOW, now=NOW, already_exists=True,
    )
    assert duplicate.code == "NOTIFICATION_DUPLICATE"
    assert duplicate["idempotent"] is True


def test_notification_suppression_external_and_deadline_boundaries():
    suppressed = notification_decision(
        "CRITICAL", "user-1", "INCIDENT", "channel-1", "event-1",
        created_at=NOW, now=NOW, suppress_requested=True,
    )
    assert suppressed.code == "NOTIFICATION_SUPPRESSION_FORBIDDEN"

    protected_external = notification_decision(
        "WARNING", "user-1", "INCIDENT", "channel-1", "event-1",
        created_at=NOW, now=NOW, external_requested=True,
        channel_classification="CONFIDENTIAL",
    )
    assert protected_external.code == "NOTIFICATION_EXTERNAL_CONTENT_DENY"

    expired = notification_decision(
        "ACTION_REQUIRED", "user-1", "BARRIER", "barrier-1", "event-1",
        created_at=NOW, now=LATER, deadline_at=LATER,
    )
    assert expired.code == "NOTIFICATION_DEADLINE_EXPIRED"
    assert notification_deadline("INFO", NOW) is None
    assert notification_deadline("ACTION_REQUIRED", NOW, deadline_seconds=0) is None


def test_agent_offboarding_is_tiered_and_does_not_start_new_high_risk_work():
    personal = agent_offboarding_disposition("PERSONAL", "PRODUCTION", "INTERNAL")
    assert personal.action == "SUSPEND"
    assert personal["allow_new_work"] is False

    restricted = agent_offboarding_disposition("GROUP", "PRODUCTION", "RESTRICTED", responsible_group=True)
    assert restricted.action == "PAUSE"

    group = agent_offboarding_disposition(
        "GROUP", "PRODUCTION", "CONFIDENTIAL", responsible_group=True,
        approved_work=True, continuity_authorized=True,
    )
    assert group.action == "OWNER_TRANSFER_REQUIRED"
    assert group["allow_approved_work"] is True
    assert group["allow_new_high_risk_work"] is False

    incident = agent_offboarding_disposition("PERSONAL", "DEVELOPMENT", "PUBLIC", security_incident=True)
    assert incident.action == "QUARANTINE"


def test_owner_transfer_requires_distinct_owner_and_all_controls():
    incomplete = owner_transfer_decision(
        "owner-1", "owner-2", new_owner_active=True, policy_approved=True,
    )
    assert incomplete.code == "AGENT_TRANSFER_CONTROLS_INCOMPLETE"
    assert set(incomplete["missing_controls"]) == {"credential_rotation", "grant_reevaluation"}

    complete = owner_transfer_decision(
        "owner-1", "owner-2", new_owner_active=True, policy_approved=True,
        credentials_rotated=True, grants_reevaluated=True,
    )
    assert complete.allowed

    self_transfer = owner_transfer_decision(
        "owner-1", "owner-2", new_owner_active=True, policy_approved=True,
        credentials_rotated=True, grants_reevaluated=True, actor_is_new_owner=True,
    )
    assert self_transfer.code == "AGENT_TRANSFER_SELF_APPROVAL"


def test_barrier_recovery_uses_retry_checkpoint_substitute_then_escalation():
    retry = barrier_recovery_decision(
        "ARRIVING", 0, 2, failed_roles=["REVIEWER"], required_roles=["REVIEWER"],
    )
    assert retry.action == "RETRY"
    assert retry["next_attempt"] == 1

    checkpoint = barrier_recovery_decision(
        "ARRIVING", 2, 2, failed_roles=["REVIEWER"], required_roles=["REVIEWER"],
        checkpoint_available=True, checkpoint_authorized=True,
    )
    assert checkpoint.action == "RESTORE_CHECKPOINT"

    substitute = barrier_recovery_decision(
        "ARRIVING", 2, 2, failed_roles=["REVIEWER"], required_roles=["REVIEWER"],
        substitute_available=True, substitute_authorized=True, quorum=1,
    )
    assert substitute.action == "SUBSTITUTE"
    assert substitute["preserves_required_roles"] is True

    escalation = barrier_recovery_decision(
        "ARRIVING", 2, 2, failed_roles=["REVIEWER"], required_roles=["REVIEWER"],
        substitute_available=True, substitute_authorized=False, escalation_available=True,
    )
    assert escalation.action == "HUMAN_DECISION_REQUIRED"


def test_barrier_protected_quorum_and_deadline_boundaries():
    lowered = barrier_recovery_decision(
        "ARRIVING", 1, 1, security_tier="RESTRICTED", quorum=2,
        candidate_quorum=1, failed_roles=["reviewer"],
    )
    assert lowered.code == "BARRIER_QUORUM_LOWERING_FORBIDDEN"

    waiting = barrier_recovery_decision("ARRIVING", 0, 0, quorum=2, arrived_count=1)
    assert waiting.action == "WAIT"
    ready = barrier_recovery_decision("ARRIVING", 0, 0, quorum=2, arrived_count=2)
    assert ready.action == "REVIEW"

    timeout = barrier_recovery_decision(
        "ARRIVING", 0, 0, deadline_at=NOW, now=NOW,
        security_tier="RESTRICTED", required_roles=["human"],
    )
    assert timeout.action == "HUMAN_DECISION_REQUIRED"

    blocked = barrier_recovery_decision(
        "ARRIVING", 1, 1, failed_roles=["human"], required_roles=["human"],
    )
    assert blocked.code == "BARRIER_RECOVERY_BLOCKED"


def test_barrier_transition_requires_fencing_reason_and_evidence():
    stale = barrier_transition_decision("DECIDED", "RELEASED", authorized=True, expected_version_matches=False)
    assert stale.code == "BARRIER_VERSION_CONFLICT"
    no_evidence = barrier_transition_decision("DECIDED", "RELEASED", authorized=True, reason="ship")
    assert no_evidence.code == "BARRIER_EVIDENCE_REQUIRED"
    allowed = barrier_transition_decision("DECIDED", "RELEASED", authorized=True, reason="ship", evidence_present=True)
    assert allowed.allowed


def test_profile_impact_reports_removed_capability_and_active_work():
    impact = profile_change_impact(
        "GRAPH-PREVIEW",
        "PRODUCTION",
        active_work=[{"id": "run-1", "capabilities": ["graph_migration"]}],
    )
    assert "graph_migration" in impact["removed_capabilities"]
    assert impact["impacted_work"] == [{"id": "run-1", "lost_capabilities": ["graph_migration"], "status": "ACTIVE"}]
    assert impact["risk"] == "HIGH"


def test_profile_preflight_requires_authority_reason_dependencies_and_safe_activation():
    unauthorized = profile_change_preflight("PRODUCTION", "GRAPH-PREVIEW")
    assert unauthorized.code == "PROFILE_AUTHORIZATION_REQUIRED"

    no_reason = profile_change_preflight("PRODUCTION", "GRAPH-PREVIEW", authorized=True)
    assert no_reason.code == "PROFILE_REASON_REQUIRED"

    active = profile_change_preflight(
        "GRAPH-PREVIEW",
        "PRODUCTION",
        authorized=True,
        reason="production cutover",
        active_work=[{"id": "run-1", "capabilities": ["graph_migration"]}],
    )
    assert active.code == "PROFILE_PREFLIGHT_BLOCKED"
    assert "ACTIVE_WORK_DEPENDENCY" in active["blockers"]

    unavailable = profile_change_preflight(
        "PRODUCTION",
        "GRAPH-PREVIEW",
        authorized=True,
        reason="enable graph preview",
        dependency_status={"graph_preview": False},
        restart_available=False,
        controlled_activation_available=False,
    )
    assert not unavailable
    assert "DEPENDENCY_NOT_READY:graph_preview" in unavailable["blockers"]

    incompatible = profile_change_preflight(
        "PRODUCTION",
        "GRAPH-PREVIEW",
        authorized=True,
        reason="enable graph preview",
        incompatible_capabilities=[("graph_preview", "graph_migration")],
    )
    assert "INCOMPATIBLE_CAPABILITIES:graph_preview:graph_migration" in incompatible["blockers"]

    allowed = profile_change_preflight(
        "PRODUCTION",
        "GRAPH-PREVIEW",
        authorized=True,
        reason="enable graph preview",
        restart_available=False,
        controlled_activation_available=True,
    )
    assert allowed.allowed
    assert allowed.action == "ACTIVATE"


def test_profile_capabilities_are_server_side_and_no_change_is_idempotent():
    assert "graph_preview" not in resolve_profile_capabilities("production")
    assert "graph_preview" in resolve_profile_capabilities("graph-preview")
    no_change = profile_change_preflight("production", "production")
    assert no_change.allowed
    assert no_change.code == "PROFILE_NO_CHANGE"
