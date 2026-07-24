"""AI Agent Infra v4.1.0 - Loop Engineering API Tests"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
from lib.loop_api import (
    create_loop, get_loop, update_loop, delete_loop, list_loops,
    start_run, get_run, list_runs, pause_run, resume_run, stop_run, fail_run,
    record_iteration, get_iteration, list_iterations,
    get_loop_stats, check_stop_conditions, cleanup_old_runs,
    add_hook, remove_hook, list_hooks,
    evaluate_iteration, execute_loop_iteration,
)
from lib.connection import close_pool
from lib.agent_api import register_agent

TEST_AGENT = "AGENT_001"


def _goal():
    return {"success_criteria": "all tests pass", "constraints": ["no breaking changes"]}

def _stop(max_iter=10):
    return {"max_iterations": max_iter, "max_tokens": 100000, "max_duration_seconds": 3600}

def _eval(etype="TEST"):
    return {"eval_type": etype, "eval_command": "echo ok", "success_exit_code": 0}

def _trigger():
    return {"trigger_type": "MANUAL"}


def _create_test_loop():
    register_agent(TEST_AGENT, "Loop Test Agent", agent_type="test")
    loop_id = create_loop(
        title="Test Loop",
        goal_definition=_goal(),
        stop_conditions=_stop(),
        evaluation_config=_eval(),
        summary="A test loop",
        owned_by_agent=TEST_AGENT,
        visibility="PRIVATE",
    )
    assert isinstance(loop_id, (int, str))
    assert loop_id > 0 if isinstance(loop_id, int) else len(loop_id) > 0
    print(f"PASS: test_create_loop (id={str(loop_id)[:8]}...)")
    return loop_id


def test_create_loop():
    loop_id = _create_test_loop()
    delete_loop(loop_id)


def test_get_loop():
    loop_id = _create_test_loop()
    loop = get_loop(loop_id)
    assert loop is not None
    assert loop["title"] == "Test Loop"
    assert loop["status"] == "ACTIVE"
    assert "goal_definition" in loop
    print(f"PASS: test_get_loop (title={loop['title']})")
    delete_loop(loop_id)


def test_update_loop():
    loop_id = _create_test_loop()
    ok = update_loop(loop_id, title="Updated Loop", summary="Updated summary")
    assert ok
    loop = get_loop(loop_id)
    assert loop["title"] == "Updated Loop"
    assert loop["summary"] == "Updated summary"
    print("PASS: test_update_loop")
    delete_loop(loop_id)


def test_delete_loop():
    loop_id = _create_test_loop()
    ok = delete_loop(loop_id)
    assert ok
    loop = get_loop(loop_id)
    assert loop is None
    print("PASS: test_delete_loop")


def test_list_loops():
    ids = []
    for i in range(3):
        ids.append(create_loop(
            title=f"List Test Loop {i}",
            goal_definition=_goal(), stop_conditions=_stop(), evaluation_config=_eval(),
            owned_by_agent=TEST_AGENT,
        ))
    loops = list_loops(agent_id=TEST_AGENT, limit=50)
    assert len(loops) >= 3
    print(f"PASS: test_list_loops (found {len(loops)} loops)")
    for lid in ids:
        delete_loop(lid)


def test_start_run():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT, "MANUAL", "test")
    assert isinstance(run_id, (int, str))
    run = get_run(run_id)
    assert run is not None
    assert run["status"] == "RUNNING"
    assert run["iteration_count"] == 0
    print(f"PASS: test_start_run (run_id={str(run_id)[:8]}...)")
    delete_loop(loop_id)


def test_get_run():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    run = get_run(run_id)
    assert run is not None
    assert run["loop_id"] == loop_id
    assert run["agent_id"] == TEST_AGENT
    print("PASS: test_get_run")
    delete_loop(loop_id)


def test_list_runs():
    loop_id = _create_test_loop()
    rids = [start_run(loop_id, TEST_AGENT) for _ in range(3)]
    runs = list_runs(loop_id=loop_id)
    assert len(runs) >= 3
    print(f"PASS: test_list_runs (found {len(runs)} runs)")
    delete_loop(loop_id)


def test_pause_resume_run():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    ok = pause_run(run_id)
    assert ok
    run = get_run(run_id)
    assert run["status"] == "PAUSED"
    ok = resume_run(run_id)
    assert ok
    run = get_run(run_id)
    assert run["status"] == "RUNNING"
    print("PASS: test_pause_resume_run")
    delete_loop(loop_id)


def test_stop_run():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    ok = stop_run(run_id, "test stop")
    assert ok
    run = get_run(run_id)
    assert run["status"] == "STOPPED"
    assert run["final_result"] == "test stop"
    print("PASS: test_stop_run")
    delete_loop(loop_id)


def test_record_iteration():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    iter_id = record_iteration(
        run_id=run_id,
        plan_data={"step": "fix test"},
        actions={"tool": "editor", "file": "test.py"},
        observations={"result": "fixed"},
        evaluation_result={"passed": False, "score": 0.5},
        evaluation_passed=False,
        token_usage=500,
    )
    assert isinstance(iter_id, (int, str))
    run = get_run(run_id)
    assert run["iteration_count"] == 1
    assert run["total_tokens"] == 500
    print(f"PASS: test_record_iteration (iter_id={str(iter_id)[:8]}...)")
    delete_loop(loop_id)


def test_list_iterations():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    for i in range(3):
        record_iteration(run_id=run_id, token_usage=100, evaluation_passed=False)
    iters = list_iterations(run_id)
    assert len(iters) == 3
    assert iters[0]["iteration_order"] == 1
    assert iters[2]["iteration_order"] == 3
    print(f"PASS: test_list_iterations (found {len(iters)} iterations)")
    delete_loop(loop_id)


def test_get_loop_stats():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    record_iteration(run_id=run_id, token_usage=300, evaluation_passed=False)
    record_iteration(run_id=run_id, token_usage=200, evaluation_passed=False)
    stats = get_loop_stats(loop_id)
    assert stats["total_runs"] >= 1
    assert stats["total_iterations"] >= 2
    assert stats["total_tokens"] >= 500
    print(f"PASS: test_get_loop_stats (runs={stats['total_runs']}, iters={stats['total_iterations']})")
    delete_loop(loop_id)


def test_check_stop_conditions():
    register_agent(TEST_AGENT, "Loop Test Agent", agent_type="test")
    loop_id = create_loop(
        title="Stop Test",
        goal_definition=_goal(),
        stop_conditions={"max_iterations": 2},
        evaluation_config=_eval(),
        owned_by_agent=TEST_AGENT,
    )
    run_id = start_run(loop_id, TEST_AGENT)
    record_iteration(run_id=run_id, evaluation_passed=False)
    status = check_stop_conditions(run_id)
    assert status == "CONTINUE"
    record_iteration(run_id=run_id, evaluation_passed=False)
    status = check_stop_conditions(run_id)
    assert status == "STOP"
    print("PASS: test_check_stop_conditions")
    delete_loop(loop_id)


def test_add_remove_hook():
    loop_id = _create_test_loop()
    hook_id = add_hook(loop_id, "POST_ITERATION", "LOG", {"message": "iter done"}, 3)
    assert isinstance(hook_id, (int, str))
    hooks = list_hooks(loop_id)
    assert len(hooks) >= 1
    assert hooks[0]["hook_event"] == "POST_ITERATION"
    ok = remove_hook(hook_id)
    assert ok
    hooks = list_hooks(loop_id)
    assert len(hooks) == 0
    print("PASS: test_add_remove_hook")
    delete_loop(loop_id)


def test_evaluation_passed_completes_run():
    loop_id = _create_test_loop()
    run_id = start_run(loop_id, TEST_AGENT)
    record_iteration(
        run_id=run_id,
        evaluation_passed=True,
        token_usage=200,
    )
    run = get_run(run_id)
    assert run["status"] == "COMPLETED"
    assert "Goal achieved" in (run["final_result"] or "")
    print("PASS: test_evaluation_passed_completes_run")
    delete_loop(loop_id)


if __name__ == "__main__":
    test_create_loop()
    test_get_loop()
    test_update_loop()
    test_delete_loop()
    test_list_loops()
    test_start_run()
    test_get_run()
    test_list_runs()
    test_pause_resume_run()
    test_stop_run()
    test_record_iteration()
    test_list_iterations()
    test_get_loop_stats()
    test_check_stop_conditions()
    test_add_remove_hook()
    test_evaluation_passed_completes_run()
    close_pool()
    print("\n✓ All Loop Engineering tests passed!")
