from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not (ROOT / "live_mode_validator.py").is_file(),
    reason="unified-source validator inspection is not part of generated packages",
)


def test_yashandb_business_probe_uses_security_filtered_entity_view():
    source = (ROOT / "live_mode_validator.py").read_text(encoding="utf-8")

    assert '"CX_AGENT_ENTITY_READ" if database == "yashandb" else "ENTITIES"' in source


def test_release_validator_honors_live_probe_required_counts():
    source = (ROOT / "spec_validator.py").read_text(encoding="utf-8")

    assert 'item.get("v401_tables_present", 0) >= item.get("v401_tables_required", 0)' in source
