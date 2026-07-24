"""AI Agent Infra v4.1.0 - Spec API Tests"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.spec_api import (
    create_spec, get_spec, update_spec, list_specs,
    create_plan_from_spec, link_spec_to_plan,
    get_spec_plan_links, validate_plan_against_spec,
    derive_spec, delete_spec
)
from lib.connection import close_pool

AC = ["All items processed", "Error rate < 1%", "Throughput > 100/s"]
_entity_id = None
_plan_id = None


def test_create_spec():
    global _entity_id
    _entity_id = create_spec(
        title="Test Spec v2.3",
        summary="A test specification",
        content="Process all items with low error rate",
        category="test-spec",
        importance=8,
        owned_by_agent="test-agent",
        visibility="SHARED",
        spec_scope="processing",
        complexity="HIGH",
        acceptance_criteria=AC,
        constraints={"max_latency_ms": 500, "min_accuracy": 0.99},
    )
    assert isinstance(_entity_id, (int, str))
    assert _entity_id > 0 if isinstance(_entity_id, int) else len(_entity_id) > 0
    print(f"PASS: test_create_spec (id={_entity_id})")


def test_get_spec():
    spec = get_spec(_entity_id)
    assert spec is not None
    assert spec["title"] == "Test Spec v2.3"
    assert spec["entity_type"] == "SPEC"
    print(f"PASS: test_get_spec (title={spec['title']})")


def test_update_spec():
    ok = update_spec(_entity_id, title="Updated Spec v2.3", spec_status="APPROVED")
    assert ok
    spec = get_spec(_entity_id)
    assert spec["title"] == "Updated Spec v2.3"
    print("PASS: test_update_spec")


def test_list_specs():
    results = list_specs(spec_scope="processing")
    assert len(results) >= 1
    print(f"PASS: test_list_specs (found={len(results)})")


def test_link_spec_to_plan():
    global _plan_id
    from lib.agent_api import register_agent
    try:
        register_agent("spec-test-agent", "Spec Test Agent", agent_type="test")
    except Exception:
        pass
    _plan_id = create_plan_from_spec(_entity_id, "spec-test-agent")
    assert isinstance(_plan_id, (int, str))
    assert _plan_id > 0 if isinstance(_plan_id, int) else len(_plan_id) > 0
    print(f"PASS: test_link_spec_to_plan (plan_id={_plan_id})")


def test_get_spec_plan_links():
    links = get_spec_plan_links(_entity_id)
    assert len(links) >= 1
    assert links[0]["link_type"] == "DRIVES"
    print(f"PASS: test_get_spec_plan_links (found={len(links)})")


def test_validate_spec():
    report = validate_plan_against_spec(_entity_id, _plan_id)
    assert "spec_id" in report
    assert "validations" in report
    print(f"PASS: test_validate_spec (validations={len(report['validations'])})")


def test_derive_spec():
    derived_id = derive_spec(_entity_id, "Derived Spec v2.3")
    assert isinstance(derived_id, (int, str))
    assert derived_id > 0 if isinstance(derived_id, int) else len(derived_id) > 0
    derived = get_spec(derived_id)
    assert derived is not None
    assert derived["title"] == "Derived Spec v2.3"
    print(f"PASS: test_derive_spec (id={derived_id})")
    delete_spec(derived_id)


def test_delete_spec():
    ok = delete_spec(_entity_id)
    assert ok
    spec = get_spec(_entity_id)
    assert spec is None
    print("PASS: test_delete_spec")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_create_spec,
        test_get_spec,
        test_update_spec,
        test_list_specs,
        test_link_spec_to_plan,
        test_get_spec_plan_links,
        test_validate_spec,
        test_derive_spec,
        test_delete_spec,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nSpec Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
