"""AI Agent Infra v4.0.1 - Community Edition - Skill Tests"""

import sys
import os
import json
import uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.skill_api import (
    register_skill, get_skill, list_skills, update_skill,
    delete_skill, validate_skill, deprecate_skill,
)
from lib.connection import DATABASE_DIALECT, execute, close_pool

SUFFIX = f"sktest_{uuid.uuid4().hex[:8]}"


def test_register_skill():
    eid = register_skill("Skill Test", f"test_skill_{SUFFIX}", skill_type="CUSTOM", runtime="PYTHON")
    assert eid > 0 if isinstance(eid, int) else eid.startswith("ENT_")
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_register_skill (id={eid})")


def test_register_skill_minimal():
    eid = register_skill("Minimal Skill", f"minimal_skill_{SUFFIX}")
    assert eid > 0 if isinstance(eid, int) else eid.startswith("ENT_")
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_register_skill_minimal (id={eid})")


def test_get_skill():
    eid = register_skill("Get Skill Test", f"get_skill_{SUFFIX}", skill_type="CUSTOM", runtime="PYTHON",
                         resource_uri="s3://skills/test", text_content="hello")
    skill = get_skill(eid)
    assert skill is not None
    assert skill["title"] == "Get Skill Test"
    assert skill["skill_name"] == f"get_skill_{SUFFIX}"
    assert "skill_type" in skill
    assert "skill_version" in skill
    assert "skill_status" in skill
    assert "created_at" in skill
    assert "updated_at" in skill
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_get_skill (id={eid})")


def test_list_skills():
    eid1 = register_skill("List Skill 1", f"list_skill_1_{SUFFIX}", skill_type="CUSTOM")
    eid2 = register_skill("List Skill 2", f"list_skill_2_{SUFFIX}", skill_type="CUSTOM")
    skills = list_skills(skill_status="ACTIVE")
    count_before = len(skills)
    assert count_before >= 2
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid1})
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid2})
    print(f"PASS: test_list_skills (count={count_before})")


def test_list_skills_filter_type():
    eid1 = register_skill("Builtin Skill", f"builtin_skill_{SUFFIX}", skill_type="BUILTIN")
    eid2 = register_skill("Custom Skill", f"custom_skill_{SUFFIX}", skill_type="CUSTOM")
    builtin_skills = list_skills(skill_type="BUILTIN", skill_status="ACTIVE")
    assert all(s["skill_type"] == "BUILTIN" for s in builtin_skills)
    custom_skills = list_skills(skill_type="CUSTOM", skill_status="ACTIVE")
    assert all(s["skill_type"] == "CUSTOM" for s in custom_skills)
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid1})
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid2})
    print("PASS: test_list_skills_filter_type")


def test_update_skill():
    eid = register_skill("Update Skill", f"update_skill_{SUFFIX}")
    ok = update_skill(eid, skill_name=f"updated_skill_{SUFFIX}")
    assert ok
    skill = get_skill(eid)
    assert skill["skill_name"] == f"updated_skill_{SUFFIX}"
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_update_skill (id={eid})")


def test_delete_skill():
    eid = register_skill("Delete Skill", f"delete_skill_{SUFFIX}")
    ok = delete_skill(eid)
    assert ok
    skill = get_skill(eid)
    assert skill is None
    print("PASS: test_delete_skill")


def test_validate_skill_valid():
    eid = register_skill("Valid Skill", f"valid_skill_{SUFFIX}")
    result = validate_skill(eid)
    assert result["valid"] is True
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_validate_skill_valid (valid={result['valid']})")


def test_validate_skill_not_found():
    missing_id = 9223372036854775807 if DATABASE_DIALECT == "postgresql" else "ENT_NONEXISTENT12345"
    result = validate_skill(missing_id)
    assert result["valid"] is False
    print("PASS: test_validate_skill_not_found")


def test_deprecate_skill():
    eid = register_skill("Deprecate Skill", f"deprecate_skill_{SUFFIX}")
    ok = deprecate_skill(eid)
    assert ok
    skill = get_skill(eid)
    assert skill["skill_status"] == "DEPRECATED"
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_deprecate_skill (status={skill['skill_status']})")


def test_skill_with_dependencies():
    deps = ["ENT_DEP001", "ENT_DEP002"]
    eid = register_skill("Dep Skill", f"dep_skill_{SUFFIX}", dependencies=deps)
    skill = get_skill(eid)
    assert skill["dependencies"] == deps
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_skill_with_dependencies (deps={skill['dependencies']})")


def test_skill_with_parameters():
    params = {"temperature": 0.7, "max_tokens": 1024}
    eid = register_skill("Param Skill", f"param_skill_{SUFFIX}", parameters=params)
    skill = get_skill(eid)
    assert skill["parameters"] == params
    execute("DELETE FROM ENTITIES WHERE ENTITY_ID = :eid", {"eid": eid})
    print(f"PASS: test_skill_with_parameters (params={skill['parameters']})")


def run_all():
    passed = 0
    failed = 0
    for test_fn in [
        test_register_skill,
        test_register_skill_minimal,
        test_get_skill,
        test_list_skills,
        test_list_skills_filter_type,
        test_update_skill,
        test_delete_skill,
        test_validate_skill_valid,
        test_validate_skill_not_found,
        test_deprecate_skill,
        test_skill_with_dependencies,
        test_skill_with_parameters,
    ]:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test_fn.__name__} - {e}")
            failed += 1

    close_pool()
    print(f"\nSkill Tests: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
