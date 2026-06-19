# Release Notes — v3.7.1

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-19

License: Apache License 2.0

Official Website: https://db4agent.top

---

## Overview

v3.7.1 introduces **Loop Engineering Collaborative Integration** — connecting Loop Engineering with Spec, Task, Branch, Collab, and Skill modules. Building on v3.7.0 which introduced Loop Engineering as the 4th generation AI engineering methodology (after Prompt Engineering, Context Engineering, and Harness Engineering), proposed by Peter Steinberger in June 2026. This release adds a complete loop lifecycle management system with evaluation engine, lifecycle hooks, and scheduler integration.

---

## New Feature: Loop Engineering

### What is Loop Engineering?

> Introduced in v3.7.0. Extended in v3.7.1 with Collaborative Integration.

Loop Engineering is the 4th generation AI engineering methodology, proposed by Peter Steinberger in June 2026. It treats the iterative refinement loop — where an AI agent repeatedly evaluates its output against stop conditions and feeds results back for the next iteration — as a first-class, observable, and manageable engineering artifact.

After Prompt Engineering (crafting the right prompt), Context Engineering (managing what the LLM sees), and Harness Engineering (orchestrating tool calls and execution), Loop Engineering focuses on the **iteration loop itself**: defining when to stop, how to evaluate progress, and how to hook into the lifecycle for observability and control.

### New Tables (4)

| Table | Purpose |
|-------|---------|
| `LOOP_META` | Loop definitions: name, stop conditions (max_iterations, max_tokens, max_duration_seconds), evaluation config |
| `LOOP_RUNS` | Loop execution instances: status, start/end time, token usage, iteration count |
| `LOOP_ITERATIONS` | Per-iteration records: input, output, evaluation result, tokens consumed, duration |
| `LOOP_HOOKS` | Lifecycle hook definitions: hook type, target function, configuration |

### LOOP_MANAGER PL/SQL Package (~33 functions)

The `LOOP_MANAGER` PL/SQL package provides ~33 functions for complete loop lifecycle management:

- **Definition**: create_loop, get_loop, update_loop, delete_loop, list_loops
- **Execution**: start_run, get_run, update_run, stop_run, list_runs
- **Iterations**: add_iteration, get_iteration, list_iterations, get_iteration_count
- **Evaluation**: evaluate_iteration, get_evaluation_result
- **Hooks**: register_hook, get_hooks, trigger_hook, unregister_hook
- **Monitoring**: get_loop_stats, get_stuck_loops, cleanup_finished_loops

### loop_api.py Python Module (33 functions)

The `loop_api.py` Python module provides 33 functions including the evaluation engine and collaborative integration:

- **Loop definition CRUD**: create_loop, get_loop, update_loop, delete_loop, list_loops
- **Run management**: start_run, get_run, stop_run, list_runs, get_run_status
- **Iteration management**: add_iteration, get_iteration, list_iterations
- **Evaluation engine**: evaluate_test, evaluate_diff, evaluate_llm_judge, evaluate_manual, evaluate_iteration
- **Hooks**: register_hook, list_hooks, trigger_hook, unregister_hook
- **Monitoring**: get_loop_stats, get_stuck_loops, cleanup_loops
- **Collaborative Integration** (v3.7.1): create_loop_from_spec, create_collab_loop, create_sub_loops_for_group, aggregate_child_runs, bind_loop_to_step, get_step_loop, on_loop_run_completed, create_validation_loop_for_skill

### Evaluation Engine (6 Types)

| Type | Description | Use Case |
|------|-------------|----------|
| `TEST` | Run a shell command; pass if exit code is 0 | Automated test suites, linting, compilation |
| `DIFF` | Check git diff for changes | Detecting whether code changes were made |
| `LLM_JUDGE` | LLM-based scoring of output quality | Subjective quality assessment via LLM |
| `MANUAL` | Human review required | Human-in-the-loop validation |
| `SPEC_VALIDATION` | Validate iteration against spec acceptance criteria | Spec-driven loop verification |
| `AGGREGATE` | Aggregate child loop run results | Collaborative loop parent evaluation |

### Stop Conditions

Loops terminate when any of these conditions are met:
- `max_iterations` — maximum number of iterations reached
- `max_tokens` — cumulative token budget exhausted
- `max_duration_seconds` — wall-clock time limit exceeded

### Lifecycle Hooks

| Hook | When | Use Case |
|------|------|----------|
| `ON_START` | When a loop run starts | Run initialization, notification |
| `PRE_RUN` | Before a loop run starts | Setup, context initialization |
| `POST_ITERATION` | After each iteration completes | Logging, progress tracking |
| `ON_STOP` | When a loop stops normally | Cleanup, result persistence |
| `ON_FAIL` | When an iteration fails | Error handling, retry logic |
| `ON_TIMEOUT` | When a loop times out | Cleanup, alerting |

### Scheduler Jobs (3 new)

| Job | Schedule | Description |
|-----|----------|-------------|
| `LOOP_TRIGGER_JOB` | Every 1 min | Triggers pending loop runs that are ready to execute |
| `LOOP_STUCK_CHECK_JOB` | Every 5 min | Detects and handles stuck loop runs (no iteration beyond threshold) |
| `LOOP_CLEANUP_JOB` | Daily 03:00 | Cleans up finished/failed loop runs older than retention period |

### Configuration

The `llm_judge` section in `config.json` configures the LLM evaluation (disabled by default):

```json
{
  "llm_judge": {
    "enabled": false,
    "model": "gpt-4",
    "threshold": 0.8,
    "api_url": "https://api.openai.com/v1/chat/completions"
  }
}
```

### Visualization

- `loops.html` template — Loop management dashboard with run status, iteration history, and evaluation results

### Documentation

- `docs/loop-engineering.md` — Comprehensive Loop Engineering documentation

---

## Migration Notes

Existing v3.6.2 deployments can upgrade to v3.7.1 by running the updated deploy scripts:

```bash
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
```

These scripts add the 4 new loop tables, LOOP_MANAGER package, loop_api.py module, and 3 new scheduler jobs. Existing data is preserved — the scripts use `safe_ddl` helpers to avoid re-creating existing objects.

> **Note**: The `1_schema.sql` script auto-aborts if `SYSTEM_CONFIG.schema_version` already exists. To upgrade, temporarily update the schema_version or use the migration script.

---

## Updated Counts

| Metric | v3.6.2 | v3.7.1 |
|--------|--------|--------|
| Tables | 30 | 35 |
| PL/SQL Packages | 13 | 14 |
| Python Modules | 23 | 24 |
| Scheduler Jobs | 13 | 16 |
| Tests | 105 | 121 |

---

## Backward Compatibility

No breaking changes. The Loop Engineering feature is additive — existing functionality is unchanged. The `llm_judge` config section is disabled by default.

---

## System Requirements

Unchanged from v3.6.2:
- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+

### Bug Fixes

- **Loop API import path** — Fixed `from scripts.lib.loop_api` to `from lib.loop_api` causing HTTP 500 on /api/loops endpoints
- **Missing handler methods** — Added missing `_api_loops_stats`, `_api_loops_hooks`, `_api_loops_run_get` methods; fixed route-method name mismatches
- **Loops navigation** — Added loops link to Community Edition sidebar (loops is a core feature available in all editions)
- **Loop detail close button** — Added ❌ close button to loop detail panel header for quick dismiss
- **Server startup** — Fixed startup script using `nohup` instead of `setsid` to prevent shell timeout deadlocks
- **Loop seed data** — Added 5 realistic loop definitions with runs, iterations, and hooks (Code Review, Security Scan, Performance Optimization, Documentation Update, Data Pipeline Validation)

## v3.7.1 — Loop Engineering Collaborative Integration (2026-06-19)

### Spec-Driven Loop
- Create loops from Spec acceptance criteria via POST /api/loops/from-spec
- SPEC_VALIDATION evaluation type validates each criterion against iteration results
- derive_loop_from_spec() auto-generates goal, stop conditions, and evaluation config

### Task-Loop Binding
- Bind loops to task steps via POST /api/tasks/steps/{id}/bind-loop
- STEP_COMPLETION_TYPE: MANUAL (default), LOOP, SPEC
- WAITING_LOOP status: step waits for loop completion
- Auto-completion: on_loop_run_completed() updates bound step to SUCCESS

### Collaborative Loop
- Create parent/child loops for collaboration groups via POST /api/loops/collab
- AGGREGATE evaluation type collects and summarizes child loop results
- 2-level nesting limit enforced (no sub-sub-loops)
- GET /api/loops/{id}/children and /api/loops/{id}/aggregation endpoints

### Branch-Isolated Loop
- Loops with branch_id automatically run in that branch's context

### Skill-Triggered Loop
- Skills with validation_loop in metadata auto-start verification loops on acquire

### Session & Auth Fixes
- Session cookie now has Max-Age=3600 (persists across tab switches)
- Session timeout changed to 5-minute sliding window (was 5-hour fixed)
- Fixed PG loop API method name mismatches causing HTTP 500
- Fixed PG ENT edition label showing "Community" instead of "Enterprise"

### New Database Objects
- LOOP_META: +SPEC_ID, +PARENT_LOOP_ID, +COLLAB_GROUP_ID
- LOOP_RUNS: +PARENT_RUN_ID
- TASK_STEPS: +LOOP_ID, +STEP_COMPLETION_TYPE
- TASK_LOOP_BINDING: new table
- [ENT] LOOP_AUDIT: +COLLAB_GROUP_ID
