# Loop Engineering - AI Agent Infra v3.7.0 (2026-06-18) - Community Edition

## Overview

**Loop Engineering** is the fourth generation of AI engineering methodology, succeeding Prompt Engineering, Context Engineering, and Harness Engineering. It was proposed by **Peter Steinberger in June 2026** as a model for building *self-correcting, goal-directed* agents that iterate toward an objective rather than producing a single-shot response.

### Evolution of AI Engineering

| Generation | Methodology | Core Idea |
|------------|-------------|-----------|
| 1st | Prompt Engineering | Craft the best single instruction for one-shot output |
| 2nd | Context Engineering | Curate and inject the right context window for the model |
| 3rd | Harness Engineering | Package reusable execution blueprints (input/output schemas, modes) |
| 4th | **Loop Engineering** | Define a goal, evaluate each step, and iterate until stop conditions are met |

### What is a Loop?

A **Loop** is a persistent, observable, self-evaluating execution unit. Instead of asking an agent to "fix the bug" once, a Loop:

1. Declares a **goal** (`goal_definition`) and **stop conditions** (max iterations, tokens, duration)
2. Runs **iterations**, each following the cycle: **Intent -> Context -> Action -> Observation -> Adjustment**
3. **Evaluates** every iteration via a pluggable engine (TEST, DIFF, LLM_JUDGE, MANUAL)
4. Fires **lifecycle hooks** at key points (PRE_RUN, POST_ITERATION, ON_STOP, ON_FAIL, ON_TIMEOUT, ON_START)
5. **Stops** automatically when a stop condition is met or the evaluation passes

Loops are durable: a run can be paused, resumed, monitored, and audited. All state lives in Oracle Database tables, so a loop survives agent restarts and can be inspected by humans or other agents.

---

## Architecture

Loop Engineering is implemented as a sidecar to the Unified Entity Model. A Loop Definition is an `ENTITY` with `ENTITY_TYPE='LOOP_DEFINITION'`, extended by `LOOP_META`. Execution state is tracked in three dedicated tables, and behavior is exposed through a PL/SQL package and a Python module.

```
ENTITIES (ENTITY_TYPE='LOOP_DEFINITION')
  PK: (ENTITY_ID, ENTITY_TYPE)

LOOP_META (Reference Partitioned from ENTITIES)
  PK: (ENTITY_ID, ENTITY_TYPE)
  Columns: GOAL_DEFINITION, STOP_CONDITIONS (JSON),
           EVALUATION_CONFIG (JSON), TRIGGER_CONFIG (JSON)

LOOP_RUNS (List Partitioned by STATUS)
  PK: RUN_ID
  FK: LOOP_ID -> ENTITIES(ENTITY_ID, ENTITY_TYPE)

LOOP_ITERATIONS (Reference Partitioned from LOOP_RUNS)
  PK: ITERATION_ID
  FK: RUN_ID -> LOOP_RUNS(RUN_ID)
  Records: plan -> action -> observe -> evaluate -> adjust

LOOP_HOOKS
  PK: HOOK_ID
  FK: LOOP_ID -> ENTITIES(ENTITY_ID, ENTITY_TYPE)
```

| Component | Type | Purpose |
|-----------|------|---------|
| `LOOP_META` | Sidecar table to `ENTITIES` | Stores the loop definition: goal, stop conditions, evaluation config, trigger config |
| `LOOP_RUNS` | Partitioned by `STATUS` | Tracks each execution instance of a loop (one per start) |
| `LOOP_ITERATIONS` | Reference partitioned from `LOOP_RUNS` | Records each iteration's plan/action/observation/evaluation/adjustment |
| `LOOP_HOOKS` | Standalone with FK to loop | Lifecycle hooks fired at defined events |
| `LOOP_MANAGER` | PL/SQL package (~22 functions) | Server-side loop orchestration, evaluation, and stop-condition logic |
| `loop_api.py` | Python module (25 functions) | Application-side API, including the 4 evaluation types |

### LOOP_META Schema

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| ENTITY_ID | VARCHAR2(64) | — | FK to ENTITIES (the loop definition entity) |
| ENTITY_TYPE | VARCHAR2(32) | 'LOOP_DEFINITION' | Denormalized for composite FK |
| GOAL_DEFINITION | CLOB | — | Natural-language or structured statement of the loop's objective |
| STOP_CONDITIONS | JSON | NULL | Conditions that end the loop (see Stop Conditions) |
| EVALUATION_CONFIG | JSON | NULL | Configuration for the evaluation engine (see Evaluation Engine) |
| TRIGGER_CONFIG | JSON | NULL | How the loop is started: manual, scheduled, webhook, event |

### LOOP_RUNS Schema (partitioned by STATUS)

| Column | Type | Description |
|--------|------|-------------|
| RUN_ID | VARCHAR2(64) | Primary key |
| LOOP_ID | VARCHAR2(64) | FK to loop definition entity |
| AGENT_ID | VARCHAR2(64) | Agent executing the run |
| STATUS | VARCHAR2(32) | Partition key: PENDING, RUNNING, PAUSED, COMPLETED, FAILED, TIMEOUT, CANCELLED |
| TRIGGER_TYPE | VARCHAR2(32) | MANUAL, SCHEDULED, WEBHOOK, EVENT |
| TRIGGER_SOURCE | VARCHAR2(256) | Origin of the trigger (e.g., job name, webhook URL) |
| STARTED_AT | TIMESTAMP | Run start time |
| ENDED_AT | TIMESTAMP | Run end time |
| ITERATION_COUNT | NUMBER(10,0) | Number of iterations completed |
| TOKENS_USED | NUMBER(12,0) | Cumulative tokens consumed |
| ERROR_MESSAGE | VARCHAR2(4000) | Failure details if STATUS=FAILED |

### LOOP_ITERATIONS Schema (reference partitioned from LOOP_RUNS)

| Column | Type | Description |
|--------|------|-------------|
| ITERATION_ID | VARCHAR2(64) | Primary key |
| RUN_ID | VARCHAR2(64) | FK to LOOP_RUNS (partition key) |
| ITERATION_NUMBER | NUMBER(10,0) | 1-based sequence within the run |
| PLAN_DATA | JSON | The intent/context assembled for this iteration |
| ACTIONS | JSON | Actions taken (tool calls, SQL, shell) |
| OBSERVATIONS | JSON | Results observed from the actions |
| EVALUATION_RESULT | JSON | Output of the evaluation engine for this iteration |
| ADJUSTMENT | JSON | Adjustments derived for the next iteration |
| STATUS | VARCHAR2(32) | PLANNED, EXECUTING, EVALUATED, PASSED, FAILED |
| TOKENS_USED | NUMBER(12,0) | Tokens consumed by this iteration |
| CREATED_AT | TIMESTAMP | Iteration creation time |

### LOOP_HOOKS Schema

| Column | Type | Description |
|--------|------|-------------|
| HOOK_ID | VARCHAR2(64) | Primary key |
| LOOP_ID | VARCHAR2(64) | FK to loop definition entity |
| HOOK_EVENT | VARCHAR2(32) | Lifecycle event (see Hooks) |
| HOOK_TYPE | VARCHAR2(32) | WEBHOOK, SCRIPT, NOTIFICATION, LOG, MCP_CALL |
| CONFIG | JSON | Type-specific configuration |
| ENABLED | NUMBER(1,0) | 1 = active, 0 = disabled |
| EXECUTION_ORDER | NUMBER(3,0) | Ordering when multiple hooks share an event |

---

## The 5-Stage Loop Cycle

Every iteration of a loop follows a five-stage cycle, then repeats until a stop condition is met or the evaluation passes.

```
       +---------------------------------------------+
       |                                             v
   Intent --> Context --> Action --> Observation --> Adjustment
                                                       |
                                       (next iteration)-+
```

| Stage | Description | Stored As |
|-------|-------------|-----------|
| 1. Intent | Interpret the goal and the current state to decide what this iteration must achieve | `PLAN_DATA` |
| 2. Context | Assemble the relevant context (entities, workspace, prior iterations, harness template) | `PLAN_DATA` |
| 3. Action | Execute the planned actions: tool calls, SQL, shell commands, agent invocations | `ACTIONS` |
| 4. Observation | Capture the results and side effects of the actions | `OBSERVATIONS` |
| 5. Adjustment | Evaluate the outcome and compute adjustments to apply on the next iteration | `EVALUATION_RESULT` + `ADJUSTMENT` |

The cycle mirrors the classic **plan -> act -> observe -> reflect** agent loop, with two distinctions: every stage is **persisted** to the database, and the Adjustment stage is driven by a **pluggable evaluation engine** rather than ad-hoc reasoning.

## Evaluation Engine

The evaluation engine determines whether an iteration's outcome satisfies the goal, and what adjustment to carry forward. It is configured per loop via `EVALUATION_CONFIG` and supports four evaluation types.

| Type | Mechanism | Typical Use Case | Default |
|------|-----------|------------------|---------|
| `TEST` | Run a shell command; pass if exit code is 0 | Code-fix loops (e.g., "make the test suite green") | — |
| `DIFF` | Analyze the git diff produced by the iteration | Refactoring loops (e.g., "reduce complexity without changing behavior") | — |
| `LLM_JUDGE` | Call an LLM API to score the output against a rubric | Open-ended quality loops (e.g., "improve documentation clarity") | Disabled |
| `MANUAL` | Mark the iteration for human review; a human marks pass/fail | High-stakes or subjective loops | — |

### TEST

Runs a configured shell command and interprets the exit code. A zero exit code passes; non-zero fails and feeds stdout/stderr back as the adjustment signal.

```json
{
  "type": "TEST",
  "command": "pytest tests/ -q",
  "pass_exit_code": 0,
  "timeout_seconds": 120
}
```

Best for **code-fix loops** where success is objective: the test suite passes, the build succeeds, or a linter is clean.

### DIFF

Inspects the git diff generated by the iteration's actions. Useful for **refactoring loops** where the goal is a structural change with behavioral preservation.

```json
{
  "type": "DIFF",
  "repository": "/repo",
  "checks": ["no_test_files_removed", "diff_within_scope"],
  "scope": "src/**"
}
```

### LLM_JUDGE

Calls an LLM API to score the iteration's output against a rubric. The model, endpoint, timeout, and minimum passing score are configurable. **Disabled by default** — enable it explicitly in `config.json` (see Configuration).

```json
{
  "type": "LLM_JUDGE",
  "rubric": "Does the response directly answer the user's question with correct, cited facts?",
  "min_score": 7,
  "max_score": 10
}
```

### MANUAL

Marks the iteration for human review. The loop pauses until a human marks it as passed or failed via `evaluate_iteration` or a review UI. Suitable for high-stakes or subjective goals.

```json
{
  "type": "MANUAL",
  "reviewer": "agent-lead",
  "instructions": "Verify the migration plan preserves all constraints."
}
```

---

## Stop Conditions

A loop stops when **any** of its stop conditions is met, or when the evaluation engine reports a passing result. Stop conditions are stored in `LOOP_META.STOP_CONDITIONS` as JSON.

| Condition | Description |
|-----------|-------------|
| `max_iterations` | Maximum number of iterations before the loop must stop |
| `max_tokens` | Maximum cumulative tokens consumed across all iterations |
| `max_duration_seconds` | Maximum wall-clock duration of the run |

```json
{
  "max_iterations": 10,
  "max_tokens": 200000,
  "max_duration_seconds": 3600
}
```

`check_stop_conditions(run_id)` evaluates the current run against these bounds and returns one of:

| Result | Meaning |
|--------|---------|
| `CONTINUE` | No stop condition met; loop may proceed |
| `STOP` | A stop condition was met (e.g., max iterations reached, or evaluation passed) |
| `TIMEOUT` | `max_duration_seconds` was exceeded |

---

## Hooks

Hooks are user-defined actions fired at defined lifecycle events. They are stored in `LOOP_HOOKS` and dispatched by `LOOP_MANAGER`. Multiple hooks can subscribe to the same event, ordered by `EXECUTION_ORDER`.

### Lifecycle Events

| Event | Fires |
|-------|-------|
| `PRE_RUN` | Before a run starts, after the run row is created |
| `POST_ITERATION` | After each iteration is recorded and evaluated |
| `ON_STOP` | When the loop stops normally (evaluation passed or stop condition met) |
| `ON_FAIL` | When an iteration or run fails |
| `ON_TIMEOUT` | When `max_duration_seconds` is exceeded |

### Hook Types

| Type | Behavior |
|------|----------|
| `WEBHOOK` | POST a JSON payload to a configured URL |
| `SCRIPT` | Execute a local shell script, passing context via env vars/stdin |
| `NOTIFICATION` | Emit a notification to a channel (e.g., email, Slack, in-app) |
| `LOG` | Append a structured record to the application/audit log |
| `MCP_CALL` | Invoke an MCP (Model Context Protocol) tool with the hook payload |

Hooks are best-effort and non-blocking by default: a failing hook logs an error but does not abort the loop unless its config sets `blocking: true`.

```json
{
  "event": "ON_STOP",
  "type": "WEBHOOK",
  "config": { "url": "https://hooks.example.com/loop-done", "blocking": false }
}
```

## API Reference

The Python module `scripts/lib/loop_api.py` exposes 25 functions (including the 4 evaluation handlers). The most important are listed below. The PL/SQL package `LOOP_MANAGER` mirrors the orchestration logic server-side with ~22 functions.

### Definition & Runs

| Function | Description |
|----------|-------------|
| `create_loop(title, goal_definition, stop_conditions, evaluation_config, trigger_config=None, category=None, importance=5, owned_by_agent=None, visibility='SHARED')` | Create a Loop Definition: an `ENTITIES` row (`ENTITY_TYPE='LOOP_DEFINITION'`) plus a `LOOP_META` row. Returns `loop_id` (str) |
| `get_loop(loop_id)` | Retrieve a loop definition with its `LOOP_META`. Returns dict or `None` |
| `update_loop(loop_id, **kwargs)` | Update goal, stop conditions, evaluation config, or trigger config |
| `delete_loop(loop_id)` | Delete the loop's `LOOP_META` and `ENTITIES` rows. Returns `bool` |
| `list_loops(category=None, limit=100, offset=0)` | List loop definitions with optional filters |
| `start_run(loop_id, agent_id, trigger_type='MANUAL', trigger_source=None)` | Create a `LOOP_RUNS` row (STATUS='RUNNING'), fire `PRE_RUN` hooks, and return `run_id` (str) |
| `get_run(run_id)` | Retrieve a run with its current status and counters |
| `pause_run(run_id)` / `resume_run(run_id)` | Transition a run between RUNNING and PAUSED |
| `cancel_run(run_id, reason=None)` | Mark a run CANCELLED and fire `ON_STOP`/`ON_FAIL` as appropriate |

### Iterations & Evaluation

| Function | Description |
|----------|-------------|
| `record_iteration(run_id, plan_data, actions, observations, evaluation_result=None, adjustment=None, tokens_used=0)` | Append a `LOOP_ITERATIONS` row with the five-stage payload. Returns `iteration_id` (str) |
| `evaluate_iteration(run_id, iteration_id)` | Run the evaluation engine configured for the loop (TEST/DIFF/LLM_JUDGE/MANUAL), persist `EVALUATION_RESULT`, and fire `POST_ITERATION` hooks. Returns the evaluation result dict |
| `execute_loop_iteration(run_id, agent_id, plan_fn=None, action_fn=None)` | Execute a full iteration cycle (Intent -> Context -> Action -> Observation -> Adjustment), record it, evaluate it, and check stop conditions. Returns a dict with `iteration_id`, `evaluation`, and `stop_status` |
| `check_stop_conditions(run_id)` | Evaluate the run against `STOP_CONDITIONS` and the latest evaluation. Returns `CONTINUE`, `STOP`, or `TIMEOUT` |
| `get_iteration(run_id, iteration_number)` | Retrieve a single iteration by number |
| `list_iterations(run_id, limit=100, offset=0)` | List iterations for a run in order |

### Statistics & Hooks

| Function | Description |
|----------|-------------|
| `get_loop_stats(loop_id)` | Aggregate statistics for a loop: total runs, iterations, tokens, average iterations per run, pass/fail counts, and duration stats. Returns dict |
| `get_run_stats(run_id)` | Per-run statistics: iterations, tokens, elapsed time, evaluation pass rate |
| `add_hook(loop_id, hook_event, hook_type, config, execution_order=100, enabled=True)` | Register a lifecycle hook. Returns `hook_id` (str) |
| `remove_hook(hook_id)` | Delete a hook. Returns `bool` |
| `list_hooks(loop_id=None, hook_event=None)` | List hooks, optionally filtered by loop or event |
| `enable_hook(hook_id)` / `disable_hook(hook_id)` | Toggle a hook's `ENABLED` flag |

### PL/SQL `LOOP_MANAGER` (highlights)

| Procedure/Function | Description |
|--------------------|-------------|
| `START_RUN(p_loop_id, p_agent_id, p_trigger_type, p_trigger_source)` | Server-side run creation |
| `RECORD_ITERATION(p_run_id, p_plan, p_actions, p_obs)` | Server-side iteration recording |
| `EVALUATE_ITERATION(p_run_id, p_iteration_id)` | Server-side evaluation dispatch |
| `CHECK_STOP_CONDITIONS(p_run_id)` | Returns `CONTINUE`/`STOP`/`TIMEOUT` |
| `FIRE_HOOKS(p_loop_id, p_event, p_payload)` | Dispatches matching hooks |
| `CLEANUP_OLD_RUNS(p_days)` | Removes completed runs older than `p_days` |

---

## Scheduler Jobs

Three Oracle Scheduler jobs maintain and drive loops. They are created during deployment and run as the application schema owner.

| Job | Schedule | Purpose |
|-----|----------|---------|
| `LOOP_TRIGGER_JOB` | Every minute | Picks up loops with a due `TRIGGER_CONFIG` (scheduled/webhook/event) and starts their runs |
| `LOOP_STUCK_CHECK_JOB` | Every 5 minutes | Detects runs stuck in RUNNING beyond `max_duration_seconds` and transitions them to TIMEOUT, firing `ON_TIMEOUT` hooks |
| `LOOP_CLEANUP_JOB` | Weekly | Purges old completed/failed runs and their iterations via `LOOP_MANAGER.CLEANUP_OLD_RUNS` |

```sql
-- Example: inspect scheduler jobs
SELECT job_name, enabled, repeat_interval, last_run_duration
FROM   user_scheduler_jobs
WHERE  job_name LIKE 'LOOP_%';
```

---

## Configuration

Loop runtime configuration lives in `config.json`. The `llm_judge` section controls the `LLM_JUDGE` evaluation type. It is **disabled by default**; when enabled, every `LLM_JUDGE` evaluation calls the configured API endpoint and compares the returned score against `min_score`.

```json
"llm_judge": {
  "enabled": false,
  "api_url": "http://10.10.10.1:12345/v1/chat/completions",
  "model": "gpt-4o",
  "timeout": 60,
  "min_score": 7
}
```

| Field | Description |
|-------|-------------|
| `enabled` | Master switch for the LLM_JUDGE evaluation type |
| `api_url` | OpenAI-compatible chat completions endpoint |
| `model` | Model name to use for judging |
| `timeout` | Per-request timeout in seconds |
| `min_score` | Minimum passing score (iterations scoring below this fail and feed back an adjustment) |

## Usage Examples

### Creating a Loop

```python
from scripts.lib.loop_api import create_loop, add_hook

loop_id = create_loop(
    title="Fix failing tests",
    goal_definition="Make `pytest tests/` exit 0 without removing any tests.",
    stop_conditions={
        "max_iterations": 10,
        "max_tokens": 200000,
        "max_duration_seconds": 3600,
    },
    evaluation_config={
        "type": "TEST",
        "command": "pytest tests/ -q",
        "pass_exit_code": 0,
        "timeout_seconds": 120,
    },
    trigger_config={"type": "MANUAL"},
    category="development",
    importance=8,
    owned_by_agent="agent-1",
    visibility="SHARED",
)

# Notify a channel when the loop stops
add_hook(
    loop_id=loop_id,
    hook_event="ON_STOP",
    hook_type="WEBHOOK",
    config={"url": "https://hooks.example.com/loop-done"},
)
```

### Starting a Run

```python
from scripts.lib.loop_api import start_run

run_id = start_run(
    loop_id=loop_id,
    agent_id="agent-1",
    trigger_type="MANUAL",
    trigger_source="cli",
)
```

### Executing Iterations

The simplest path is `execute_loop_iteration`, which runs the full five-stage cycle, records the iteration, evaluates it, and checks stop conditions:

```python
from scripts.lib.loop_api import execute_loop_iteration, check_stop_conditions

while True:
    result = execute_loop_iteration(
        run_id=run_id,
        agent_id="agent-1",
    )
    if result["stop_status"] != "CONTINUE":
        break

print("Loop ended:", result["stop_status"])
```

For finer control, drive the stages manually with `record_iteration` and `evaluate_iteration`:

```python
from scripts.lib.loop_api import record_iteration, evaluate_iteration, check_stop_conditions

iteration_id = record_iteration(
    run_id=run_id,
    plan_data={"intent": "Fix off-by-one in parser.py", "context_ids": ["ENTITY_ctx1"]},
    actions=[{"tool": "shell", "command": "sed -i 's/< 10/<= 10/' src/parser.py"}],
    observations=[{"exit_code": 0, "stdout": "", "stderr": ""}],
    tokens_used=512,
)

evaluation = evaluate_iteration(run_id, iteration_id)
print("Passed?" if evaluation["passed"] else "Failed, adjusting...")

status = check_stop_conditions(run_id)  # CONTINUE | STOP | TIMEOUT
```

### Inspecting Statistics

```python
from scripts.lib.loop_api import get_loop_stats

stats = get_loop_stats(loop_id)
# {'total_runs': 4, 'total_iterations': 23, 'total_tokens': 48211,
#  'avg_iterations_per_run': 5.75, 'pass_count': 3, 'fail_count': 1}
```

---

## Relationship to Existing Features

Loop Engineering composes with the platform's other subsystems rather than replacing them.

| Feature | Interaction with Loops |
|---------|------------------------|
| **Harness Templates** | A Loop can reference a Harness Template as its execution blueprint. The template's `INPUT_SCHEMA`/`OUTPUT_SCHEMA` and `EXECUTION_MODE` shape each iteration's Intent and Action stages, so a single template can power many loops. |
| **Context Branches** | A Loop can run in an isolated context branch, enabling parallel execution of multiple loops (or multiple runs of one loop) without cross-contamination. Each run's state is scoped to its branch. |
| **Task Plans** | Loop iterations can create and update Task Plans (`TASK_PLANS`/`TASK_STEPS`). An iteration's Action stage may emit a plan; subsequent iterations execute and check off its steps, giving a loop a durable, inspectable sub-task structure. |
| **Workspace Context** | Loop iterations save context to `WORKSPACE_CONTEXT` for continuity. A paused or recovered run rehydrates from the latest CHECKPOINT/HANDOFF, so loops integrate cleanly with workspace handoff and recovery flows. |

```
Harness Template ──(blueprint)──► Loop Definition ──► Loop Run
                                        │
                                        ├── runs in ──► Context Branch (isolation)
                                        ├── emits ────► Task Plans (sub-tasks)
                                        └── saves ───► Workspace Context (continuity)
```

Together these features let a Loop be both **executable** (via a Harness Template), **isolated** (via Context Branches), **structured** (via Task Plans), and **resumable** (via Workspace Context) — turning a single-shot agent call into a durable, self-correcting engineering process.



