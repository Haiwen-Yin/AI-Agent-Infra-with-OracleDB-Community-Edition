"""Source-level and pure boundary checks for the Platform Administration Channel."""

from pathlib import Path

from lib import containment


def test_protected_channel_guards_are_in_the_service_boundary():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "lib" / "identity_api.py").read_text(encoding="utf-8")
    gateway = (root / "lib" / "agent_gateway_api.py").read_text(encoding="utf-8")
    for marker in (
        "protected Platform Administration Channel lifecycle",
        "private and direct threads are disabled in the Platform Administration Channel",
        "requires a PLATFORM_ Action Card",
    ):
        assert marker in identity
    assert "protected Platform Administration Channel role is invalid" in gateway


def test_containment_protocol_does_not_claim_unconfigured_infrastructure_kill():
    assert containment.quarantine_precedes_termination("QUARANTINE", "INFRA_TERMINATE")
    assert not containment.quarantine_precedes_termination("OBSERVE", "INFRA_TERMINATE")
