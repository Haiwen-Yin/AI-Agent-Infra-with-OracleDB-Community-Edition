"""Oracle Memory System v2.0.0 - Harness Template API Tests"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.harness_api import (
    create_template, get_template, list_templates, update_template,
    delete_template, validate_template, instantiate_template,
    derive_template, publish_template, deprecate_template,
    get_template_lineage,
)
from lib.connection import close_pool

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

_ts = int(time.time())
TEMPLATE_NAME = f"Test Harness {_ts}"
CHILD_NAME = f"Test Harness Child {_ts}"
PROMPT_TEMPLATES = {
    "system": "You are a {role} specializing in {domain}.",
    "user": "Analyze the following {domain} data: {input}",
}
VARIABLES = {
    "role": {"type": "string", "default": "Analyst"},
    "domain": {"type": "string", "default": "general"},
    "input": {"type": "string", "default": ""},
}
CATEGORY = "test-harness"

_entity_id = None
_child_id = None


def test_create_template():
    global _entity_id
    print("Testing: create_template")
    entity_id = create_template(
        name=TEMPLATE_NAME,
        description="A test harness template",
        prompt_templates=PROMPT_TEMPLATES,
        tool_sets=["memory_tools"],
        category=CATEGORY,
        variables=VARIABLES,
        tags=["unit-test", "harness"],
        owned_by_agent="test-agent",
    )
    assert entity_id > 0, f"Expected entity_id > 0, got {entity_id}"
    _entity_id = entity_id
    print(f"  {GREEN}PASS{RESET}: test_create_template (id={entity_id})")
    return True


def test_get_template():
    print("Testing: get_template")
    tpl = get_template(_entity_id)
    assert tpl is not None, "Template not found"
    assert tpl["name"] == TEMPLATE_NAME, f"Name mismatch: {tpl['name']}"
    assert tpl.get("prompt_templates") is not None, "prompt_templates missing"
    assert tpl["prompt_templates"]["system"] == PROMPT_TEMPLATES["system"], "system prompt mismatch"
    guardrails = tpl.get("guardrails", {})
    assert "max_iterations" in guardrails, "guardrails missing max_iterations"
    assert guardrails["max_iterations"] > 0, "max_iterations must be > 0"
    print(f"  {GREEN}PASS{RESET}: test_get_template (name={tpl['name']})")
    return True


def test_list_templates():
    print("Testing: list_templates")
    results = list_templates(category=CATEGORY)
    assert len(results) >= 1, f"Expected at least 1, got {len(results)}"
    print(f"  {GREEN}PASS{RESET}: test_list_templates (found={len(results)})")
    return True


def test_update_template():
    print("Testing: update_template")
    new_name = f"{TEMPLATE_NAME} Updated"
    ok = update_template(_entity_id, name=new_name)
    assert ok, "update_template returned False"
    tpl = get_template(_entity_id)
    assert tpl["name"] == new_name, f"Name not updated: {tpl['name']}"
    print(f"  {GREEN}PASS{RESET}: test_update_template (new_name={new_name})")
    return True


def test_validate_template():
    print("Testing: validate_template")
    result = validate_template(_entity_id)
    assert result["valid"], f"Template invalid: errors={result['errors']}"
    assert len(result["errors"]) == 0, f"Unexpected errors: {result['errors']}"
    print(f"  {GREEN}PASS{RESET}: test_validate_template (valid={result['valid']}, warnings={len(result['warnings'])})")
    return True


def test_instantiate_template():
    print("Testing: instantiate_template")
    instance = instantiate_template(
        _entity_id,
        variables={"role": "Test Analyst", "domain": "testing", "input": "sample data"},
        agent_id="test-agent-001",
    )
    assert instance is not None, "instantiate_template returned None"
    prompts = instance.get("prompt_templates", {})
    system_prompt = prompts.get("system", "")
    assert "{role}" not in system_prompt, f"Variable not substituted in system prompt: {system_prompt}"
    assert "{domain}" not in system_prompt, f"Variable not substituted in system prompt: {system_prompt}"
    assert "Test Analyst" in system_prompt, "Substituted value missing from prompt"
    assert "testing" in system_prompt, "Substituted value missing from prompt"
    assert "instance_meta" in instance, "instance_meta missing"
    assert instance["instance_meta"]["source_template_id"] == _entity_id, "source_template_id mismatch"
    print(f"  {GREEN}PASS{RESET}: test_instantiate_template (system_prompt={system_prompt[:60]}...)")
    return True


def test_derive_template():
    global _child_id
    print("Testing: derive_template")
    child_id = derive_template(
        parent_id=_entity_id,
        name=CHILD_NAME,
        description="Derived test template",
    )
    assert child_id is not None and child_id > 0, f"Expected child_id > 0, got {child_id}"
    _child_id = child_id
    lineage = get_template_lineage(_child_id)
    derives_edges = [e for e in lineage if e.get("edge_type") == "DERIVES_FROM"]
    assert len(derives_edges) >= 1, "No DERIVES_FROM edge found for child"
    parent_found = any(e.get("target_id") == _entity_id for e in derives_edges)
    assert parent_found, f"DERIVES_FROM edge does not point to parent {_entity_id}"
    print(f"  {GREEN}PASS{RESET}: test_derive_template (child_id={child_id}, edges={len(derives_edges)})")
    return True


def test_publish_template():
    print("Testing: publish_template")
    ok = publish_template(_entity_id)
    assert ok, "publish_template returned False"
    tpl = get_template(_entity_id)
    assert tpl["template_status"] == "PUBLISHED", f"Expected PUBLISHED, got {tpl['template_status']}"
    print(f"  {GREEN}PASS{RESET}: test_publish_template (status={tpl['template_status']})")
    return True


def test_deprecate_template():
    print("Testing: deprecate_template")
    ok = deprecate_template(_entity_id, reason="End of test lifecycle")
    assert ok, "deprecate_template returned False"
    tpl = get_template(_entity_id)
    assert tpl["template_status"] == "DEPRECATED", f"Expected DEPRECATED, got {tpl['template_status']}"
    print(f"  {GREEN}PASS{RESET}: test_deprecate_template (status={tpl['template_status']})")
    return True


def test_delete_template():
    print("Testing: delete_template")
    if _child_id:
        ok = delete_template(_child_id)
        assert ok, f"delete_template for child {_child_id} returned False"
        assert get_template(_child_id) is None, "Child template still exists after delete"
    if _entity_id:
        ok = delete_template(_entity_id)
        assert ok, f"delete_template for parent {_entity_id} returned False"
        assert get_template(_entity_id) is None, "Parent template still exists after delete"
    print(f"  {GREEN}PASS{RESET}: test_delete_template")
    return True


def run_all():
    passed = 0
    failed = 0

    tests = [
        test_create_template,
        test_get_template,
        test_list_templates,
        test_update_template,
        test_validate_template,
        test_instantiate_template,
        test_derive_template,
        test_publish_template,
        test_deprecate_template,
        test_delete_template,
    ]

    for test_fn in tests:
        try:
            result = test_fn()
            if result:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  {RED}FAIL{RESET}: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nHarness API Tests: {GREEN}{passed} passed{RESET}, {RED}{failed} failed{RESET}")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
