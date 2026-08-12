from datetime import datetime, timedelta, timezone

import pytest

from lib import admin_ha, containment


def members(weights):
    return [{"member_id": f"a{index}", "weight": weight, "status": "HEALTHY"} for index, weight in enumerate(weights)]


def test_three_member_defaults_are_valid():
    result = admin_ha.validate_weights(members([5, 4, 3]))
    assert result.valid


def test_dominant_weight_is_rejected():
    result = admin_ha.validate_weights(members([100, 2, 1]))
    assert not result.valid and result.code == "DOMINANT_WEIGHT"


def test_duplicate_weight_is_rejected():
    result = admin_ha.validate_weights(members([5, 5, 3]))
    assert not result.valid and result.code == "DUPLICATE_WEIGHT"


def test_quorum_requires_count_and_weight_and_excludes_proposer():
    snapshot = members([5, 4, 3])
    assert admin_ha.quorum(snapshot, [{"member_id": "a0", "decision": "APPROVE"}, {"member_id": "a1", "decision": "APPROVE"}], "a0")["allowed"] is False
    result = admin_ha.quorum(snapshot, [{"member_id": "a1", "decision": "APPROVE"}, {"member_id": "a2", "decision": "APPROVE"}], "a0")
    assert result["allowed"] is True


def test_old_term_and_fencing_are_rejected():
    assert not admin_ha.accept_write(current_term=3, current_fencing=8, write_term=2, write_fencing=8, lease_valid=True)
    assert not admin_ha.accept_write(current_term=3, current_fencing=8, write_term=3, write_fencing=7, lease_valid=True)
    assert admin_ha.accept_write(current_term=3, current_fencing=8, write_term=3, write_fencing=8, lease_valid=True)


def test_containment_requires_new_signed_generation_and_expiry():
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    payload = containment.command_payload("instance-1", 2, "nonce-1", "admin", "credential abuse", expiry, "QUARANTINE")
    command = {"instance_id": "instance-1", "generation": 2, "nonce": "nonce-1", "issuer": "admin", "reason": "credential abuse", "expires_at": expiry, "action": "QUARANTINE", "signature": containment.sign_command(payload, b"secret")}
    assert containment.verify_command(command, current_generation=1, current_state="OBSERVE", secret=b"secret")[0]
    assert containment.verify_command(command, current_generation=2, current_state="OBSERVE", secret=b"secret")[1] == "STALE_GENERATION"


def test_termination_requires_prior_quarantine():
    assert not containment.quarantine_precedes_termination("OBSERVE", "TERMINATE")
    assert containment.quarantine_precedes_termination("QUARANTINE", "TERMINATE")
