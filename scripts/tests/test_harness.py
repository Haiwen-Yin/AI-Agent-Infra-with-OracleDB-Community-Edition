"""AI Agent Infra v4.0.1 - Harness Template API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.harness_api import (
    create_harness_template, get_harness_template,
    list_harness_templates, update_harness_template,
    delete_harness_template, instantiate_harness_template,
    count_harness_templates
)
from lib.connection import close_pool

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "default": "Analyst"},
        "domain": {"type": "string", "default": "general"},
        "input": {"type": "string", "default": ""},
    },
    "required": ["role", "domain"],
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "result": {"type": "string"},
        "confidence": {"type": "number"},
    },
}

_entity_id = None


def test_create_template():
    global _entity_id
    entity_id = create_harness_template(
        title="Test Harness v2.1",
        summary="A test harness template",
        content="You are a {role} specializing in {domain}. Analyze: {input}",
        category="test-harness",
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        execution_mode="SEQUENTIAL",
        importance=7,
        owned_by_agent="test-agent",
        visibility="SHARED",
    )
    assert isinstance(entity_id, (int, str))
    assert entity_id > 0 if isinstance(entity_id, int) else len(entity_id) > 0
    _entity_id = entity_id
    print(f"PASS: test_create_template (id={entity_id})")


def test_get_template():
    tpl = get_harness_template(_entity_id)
    assert tpl is not None
    assert tpl["title"] == "Test Harness v2.1"
    assert tpl["category"] == "test-harness"
    assert tpl["execution_mode"] == "SEQUENTIAL"
    print(f"PASS: test_get_template (title={tpl['title']})")


def test_list_templates():
    results = list_harness_templates(category="test-harness")
    assert len(results) >= 1
    print(f"PASS: test_list_templates (found={len(results)})")


def test_instantiate_template():
    instance_id = instantiate_harness_template(
        _entity_id,
        variable_values={"role": "Engineer", "domain": "testing", "input": "sample data"},
        agent_id="test-agent",
    )
    assert isinstance(instance_id, (int, str))
    assert instance_id > 0 if isinstance(instance_id, int) else len(instance_id) > 0
    print(f"PASS: test_instantiate_template (instance_id={instance_id})")


def test_delete_template():
    ok = delete_harness_template(_entity_id)
    assert ok
    tpl = get_harness_template(_entity_id)
    assert tpl is None
    print("PASS: test_delete_template")


def test_count_templates():
    count = count_harness_templates(category="test-harness")
    assert isinstance(count, int)
    print(f"PASS: test_count_templates (count={count})")


def run_all():
    global _entity_id
    passed = 0
    failed = 0

    tests = [
        test_create_template,
        test_get_template,
        test_list_templates,
        test_instantiate_template,
        test_delete_template,
        test_count_templates,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nHarness Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
