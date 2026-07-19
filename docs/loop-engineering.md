# Loop Engineering - AI Agent Infra v3.10.2 (2026-07-16) - Enterprise Edition

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
Harness Template ──(blueprint)──▸ Loop Definition ──▸ Loop Run
                                        │
                                        ├── Intent → Define goal
                                        ├── Context → Gather information
                                        ├── Action → Execute tools
                                        ├── Observe → Get results
                                        └── Adjust → Refine and repeat
```
Harness Template ──(blueprint)──► Loop Definition ──► Loop Run
                                        │
                                        ├── runs in ──► Context Branch (isolation)
                                        ├── emits ────► Task Plans (sub-tasks)
                                        └── saves ───► Workspace Context (continuity)
```

Together these features let a Loop be both **executable** (via a Harness Template), **isolated** (via Context Branches), **structured** (via Task Plans), and **resumable** (via Workspace Context) — turning a single-shot agent call into a durable, self-correcting engineering process.




## v3.7.4 — Collaborative Integration

### Spec-Driven Loop
- `create_loop_from_spec(spec_id, agent_id)` derives goal from Spec acceptance_criteria
- `derive_loop_from_spec()` in spec_api.py returns derived loop parameters
- SPEC_VALIDATION evaluation type: validates each criterion against iteration observations
- POST /api/loops/from-spec endpoint

### Task-Loop Binding
- `bind_loop_to_step(step_id, loop_id)` creates TASK_LOOP_BINDING entry
- Step STEP_COMPLETION_TYPE: MANUAL (default), LOOP (auto-complete on loop success), SPEC
- WAITING_LOOP status added to TASK_STEPS
- `on_loop_run_completed()` auto-updates bound step status
- POST /api/tasks/steps/{id}/bind-loop endpoint

### Collaborative Loop
- `create_collab_loop(group_id, parent_loop_id)` creates loop with COLLAB_GROUP_ID
- `create_sub_loops_for_group()` creates child loops for each group member
- 2-level nesting limit enforced (parent_loop_id cannot point to a sub-loop)
- AGGREGATE evaluation type: collects child run results
- `aggregate_child_runs(parent_run_id)` returns aggregation summary
- GET /api/loops/{id}/children and /api/loops/{id}/aggregation endpoints

### Branch-Isolated Loop
- Loops with branch_id set automatically run in branch context

### Skill-Triggered Loop
- `create_validation_loop_for_skill(skill_id, agent_id)` checks skill metadata
- Auto-triggered on skill acquire if validation_loop defined in skill properties
