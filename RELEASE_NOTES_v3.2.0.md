# Release Notes — v3.2.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-03

License: Apache License 2.0

---

## Overview

v3.2.0 introduces **Context Branching & Multi-Agent Collaboration** — the ability to fork, merge, abandon, and resume conversation context branches within a workspace. This enables two core scenarios: (1) single-agent rollback exploration where an agent forks from a prior context point to try alternative approaches, and (2) multi-agent collaboration branching where different agents work on parallel branches of the same workspace context. Abandoned branches are preserved as read-only lesson references, supporting both manual marking (`mark_as_lesson`) and automatic extraction (`extract_lessons`).

Multi-Agent Collaboration integration connects Branches with Collaboration Groups, SDD (Spec), Task Plans, and Harness: collaboration groups can be associated with branches and specs; task plan steps can be assigned to specific agents; parallel branches can be forked for multiple agents simultaneously; harness templates can be shared across group members; and group-level spec validation ensures the entire team's work meets acceptance criteria.

---

## New Features

### 1. CONTEXT_BRANCHES Table

New table `CONTEXT_BRANCHES` stores branch metadata and lifecycle:

| Column | Type | Description |
|--------|------|-------------|
| BRANCH_ID | VARCHAR2(64) | Branch unique identifier |
| WORKSPACE_ID | VARCHAR2(64) | Parent workspace |
| PARENT_BRANCH_ID | VARCHAR2(64) | Branch this was forked from |
| FORK_CONTEXT_ID | VARCHAR2(64) | Context entry at fork point |
| BRANCH_TYPE | VARCHAR2(32) | EXPLORATION/ROLLBACK/HANDOFF/PARALLEL |
| STATUS | VARCHAR2(16) | ACTIVE/MERGED/ABANDONED/PAUSED |
| BRANCH_NAME | VARCHAR2(256) | Human-readable branch name |
| CREATED_BY | VARCHAR2(64) | Agent or user who created the branch |
| MERGED_INTO | VARCHAR2(64) | Target branch after merge |
| CREATED_AT / UPDATED_AT | TIMESTAMP | Timestamps |

### 2. BRANCH_MERGE_LOG Table

New table `BRANCH_MERGE_LOG` records merge history and conflict details:

| Column | Type | Description |
|--------|------|-------------|
| MERGE_ID | VARCHAR2(64) | Merge operation unique identifier |
| SOURCE_BRANCH_ID | VARCHAR2(64) | Branch being merged |
| TARGET_BRANCH_ID | VARCHAR2(64) | Branch receiving the merge |
| MERGE_STATUS | VARCHAR2(16) | COMPLETED/CONFLICT/ROLLED_BACK |
| CONFLICTS | CLOB | JSON array of conflict details |
| MERGED_BY | VARCHAR2(64) | Agent or user who performed the merge |
| MERGED_AT | TIMESTAMP | Merge timestamp |

### 3. BRANCH_MANAGER PL/SQL Package

New PL/SQL package `BRANCH_MANAGER` with 11 subprograms:

| Subprogram | Description |
|------------|-------------|
| `fork_branch` | Create a new branch from an existing context point |
| `merge_branch` | Merge a source branch into a target branch |
| `abandon_branch` | Mark a branch as ABANDONED (read-only, preserved as lesson) |
| `pause_branch` | Temporarily suspend work on a branch |
| `resume_branch` | Resume a paused branch |
| `diff_branches` | Compare two branches and return differences |
| `detect_conflicts` | Auto-detect entity conflicts between branches |
| `mark_as_lesson` | Manually mark a branch as a lesson reference |
| `extract_lessons` | Automatically extract learnings from abandoned branches |
| `fork_branch_for_spec` | Fork a branch specifically for implementing a spec |
| `validate_branch_for_spec` | Validate a branch's context against a spec's acceptance criteria |
| `fork_parallel_branches` | Return active PARALLEL branches for a workspace |

### 4. BRANCH_COMPARISON View

New view `BRANCH_COMPARISON` provides a unified comparison of two branches, showing context differences, entity divergences, and conflict indicators.

### 5. Schema Extensions

- **WORKSPACE_CONTEXT.BRANCH_ID** — New column linking context entries to branches
- **AGENT_SESSION.BRANCH_ID** — New column linking sessions to branches
- **TASK_PLANS.BRANCH_ID** — New column linking task plans to branches
- **SPEC_META.BRANCH_ID** — New column linking spec metadata to branches
- **COLLAB_GROUPS.BRANCH_ID** — New column linking collaboration groups to branches
- **COLLAB_GROUPS.SPEC_ID** — New column linking collaboration groups to specs
- **COLLAB_GROUP_MEMBERS.BRANCH_ID** — New column linking group members to their branch
- **TASK_STEPS.ASSIGNED_AGENT_ID** — New column assigning plan steps to specific agents
- **CONTEXT_TYPE** new value: `BRANCH_POINT` — Marks the context entry where a branch was forked

### 6. branch_api.py Python API

New Python module `branch_api.py` providing the full branch lifecycle API:

| Function | Description |
|----------|-------------|
| `fork_branch()` | Fork a new branch from a context point |
| `merge_branch()` | Merge source branch into target |
| `abandon_branch()` | Abandon a branch (preserved as lesson) |
| `pause_branch()` | Pause a branch |
| `resume_branch()` | Resume a paused branch |
| `diff_branches()` | Compare two branches |
| `detect_conflicts()` | Detect entity conflicts between branches |
| `mark_as_lesson()` | Mark a branch as a lesson reference |
| `extract_lessons()` | Extract learnings from abandoned branches |
| `fork_branch_for_spec()` | Fork a branch for implementing a spec |
| `merge_branch_with_validation()` | Merge with optional spec validation |
| `fork_parallel_branches()` | Create PARALLEL branches for multiple agents |
| `merge_parallel_branches()` | Merge multiple parallel branches with conflict detection |
| `get_parallel_diff()` | Pairwise diff of multiple parallel branches |

### 7. Multi-Agent Collaboration Integration

New functions connecting Collaboration Groups with Branches, SDD, Task Plans, and Harness:

| Module | Function | Description |
|--------|----------|-------------|
| `collab_api.py` | `create_collab_group(branch_id, spec_id)` | Create group associated with a branch and spec |
| `collab_api.py` | `add_group_member(branch_id)` | Add member with their branch |
| `collab_api.py` | `get_member_branches()` | Get all members' branch info |
| `collab_api.py` | `validate_group_against_spec()` | Validate group progress against spec |
| `collab_api.py` | `sync_group_context()` | Sync member branch summaries to shared workspace |
| `task_plan_api.py` | `add_step(assigned_agent_id)` | Assign a plan step to a specific agent |
| `task_plan_api.py` | `distribute_plan_to_group()` | Distribute steps to group members round-robin |
| `spec_api.py` | `create_spec_for_group()` | Create a spec for a collaboration group |
| `spec_api.py` | `validate_group_progress()` | Validate group's overall spec progress |
| `harness_api.py` | `share_harness_to_group()` | Share a harness template to a group |
| `harness_api.py` | `instantiate_harness_for_member()` | Instantiate harness for a group member in their branch |

### 7. /api/branch/* HTTP Routes

New HTTP endpoints for branch operations:

| Route | Method | Description |
|-------|--------|-------------|
| `/api/branch/fork` | POST | Fork a new branch |
| `/api/branch/merge` | POST | Merge branches |
| `/api/branch/abandon` | POST | Abandon a branch |
| `/api/branch/pause` | POST | Pause a branch |
| `/api/branch/resume` | POST | Resume a branch |
| `/api/branch/diff` | GET | Compare two branches |
| `/api/branch/conflicts` | GET | Detect conflicts |
| `/api/branch/lesson` | POST | Mark as lesson |
| `/api/branch/lessons/extract` | POST | Extract lessons |
| `/api/branch/fork-for-spec` | POST | Fork a branch for a spec |
| `/api/branch/merge-with-validation` | POST | Merge with spec validation |
| `/api/branch/fork-parallel` | POST | Create parallel branches for multiple agents |
| `/api/branch/merge-parallel` | POST | Merge multiple parallel branches |
| `/api/branch/{id}/plans` | GET | Get plans for a branch |
| `/api/branch/{id}/validate-spec/{spec_id}` | GET | Validate branch against spec |
| `/api/collab/group-branches` | GET | Get member branches for a group |
| `/api/collab/group-spec-validation` | GET | Validate group against spec |
| `/api/collab/distribute-plan` | POST | Distribute plan steps to group |
| `/api/collab/sync-context` | POST | Sync group context |

### 8. Dashboard Branches Page

New `/branches` page in the Dashboard for branch management: list branches, view branch details, compare branches, resolve conflicts, and mark branches as lessons.

### 9. Portal "Restart from here" Button

Portal chat page now includes a "Restart from here" button on each message, allowing users to fork a new branch from any prior message in the conversation.

### 10. BRANCH_CLEANUP_JOB Scheduler Job

New daily scheduler job `BRANCH_CLEANUP_JOB` that:
- Archives abandoned branches older than 30 days
- Cleans up orphaned branch references
- Purges expired merge logs

---

## Changes

- **workspace_api.py** — `save_context()` now accepts optional `branch_id` parameter; `create_handoff_session()` uses `fork_branch` to create a branch on handoff
- **agent_api.py** — `checkpoint_session()` now returns `context_id`; `create_session()` accepts optional `branch_id` parameter
- **collab_api.py** — `create_collab_group()` now accepts `branch_id` and `spec_id` params; `add_group_member()` accepts `branch_id`; `list_group_members()` returns `BRANCH_ID`
- **task_plan_api.py** — `add_step()` now accepts `assigned_agent_id`; `get_plan_steps()` returns `ASSIGNED_AGENT_ID`; `create_plan()` accepts `branch_id`
- **spec_api.py** — `create_spec()` accepts `branch_id`
- **2_api.sql** — Added `BRANCH_MANAGER` PL/SQL package with `fork_branch_for_spec`, `validate_branch_for_spec`, `fork_parallel_branches`; fixed `DB_CRYPTO` duplicate variable declarations
- **3_jobs.sql** — Added `BRANCH_CLEANUP_JOB`; removed invalid `SYSTEM_LOGS` references from `DORMANT_AGENT_JOB` and `CREDENTIAL_CLEANUP_JOB`
- **1_schema.sql** — Added `CONTEXT_BRANCHES`, `BRANCH_MERGE_LOG`, `BRANCH_COMPARISON`; added `BRANCH_ID` to `TASK_PLANS`, `SPEC_META`, `WORKSPACE_CONTEXT`, `AGENT_SESSION`, `COLLAB_GROUPS`, `COLLAB_GROUP_MEMBERS`; added `SPEC_ID` to `COLLAB_GROUPS`; added `ASSIGNED_AGENT_ID` to `TASK_STEPS`; moved `CONTEXT_BRANCHES` before referencing tables

---

## Upgrade from v3.1.0

For existing deployments, apply the following ALTER TABLE statements:

```sql
-- Add BRANCH_ID column to WORKSPACE_CONTEXT
ALTER TABLE WORKSPACE_CONTEXT ADD BRANCH_ID VARCHAR2(64);
CREATE INDEX IDX_WC_BRANCH ON WORKSPACE_CONTEXT(BRANCH_ID);

-- Add BRANCH_ID column to AGENT_SESSION
ALTER TABLE AGENT_SESSION ADD BRANCH_ID VARCHAR2(64);
CREATE INDEX IDX_AS_BRANCH ON AGENT_SESSION(BRANCH_ID);

-- Add BRANCH_ID column to TASK_PLANS
ALTER TABLE TASK_PLANS ADD BRANCH_ID VARCHAR2(64);
ALTER TABLE TASK_PLANS ADD CONSTRAINT FK_TP_BRANCH FOREIGN KEY (BRANCH_ID) REFERENCES CONTEXT_BRANCHES(BRANCH_ID) ON DELETE SET NULL;
CREATE INDEX IDX_TP_BRANCH ON TASK_PLANS(BRANCH_ID);

-- Add BRANCH_ID column to SPEC_META
ALTER TABLE SPEC_META ADD BRANCH_ID VARCHAR2(64);
ALTER TABLE SPEC_META ADD CONSTRAINT FK_SM_BRANCH FOREIGN KEY (BRANCH_ID) REFERENCES CONTEXT_BRANCHES(BRANCH_ID) ON DELETE SET NULL;

-- Add BRANCH_ID and SPEC_ID to COLLAB_GROUPS
ALTER TABLE COLLAB_GROUPS ADD BRANCH_ID VARCHAR2(64);
ALTER TABLE COLLAB_GROUPS ADD SPEC_ID VARCHAR2(64);
ALTER TABLE COLLAB_GROUPS ADD CONSTRAINT FK_CG_BRANCH FOREIGN KEY (BRANCH_ID) REFERENCES CONTEXT_BRANCHES(BRANCH_ID) ON DELETE SET NULL;
ALTER TABLE COLLAB_GROUPS ADD CONSTRAINT FK_CG_SPEC FOREIGN KEY (SPEC_ID) REFERENCES ENTITIES(ENTITY_ID) ON DELETE SET NULL;
CREATE INDEX IDX_CG_BRANCH ON COLLAB_GROUPS(BRANCH_ID);
CREATE INDEX IDX_CG_SPEC ON COLLAB_GROUPS(SPEC_ID);

-- Add BRANCH_ID to COLLAB_GROUP_MEMBERS
ALTER TABLE COLLAB_GROUP_MEMBERS ADD BRANCH_ID VARCHAR2(64);

-- Add ASSIGNED_AGENT_ID to TASK_STEPS
ALTER TABLE TASK_STEPS ADD ASSIGNED_AGENT_ID VARCHAR2(64);
ALTER TABLE TASK_STEPS ADD CONSTRAINT FK_TS_ASSIGNED_AGENT FOREIGN KEY (ASSIGNED_AGENT_ID) REFERENCES AGENT_REGISTRY(AGENT_ID);
CREATE INDEX IDX_TS_ASSIGNED_AGENT ON TASK_STEPS(ASSIGNED_AGENT_ID);

-- Add BRANCH_POINT to CONTEXT_TYPE CHECK constraint
-- (requires dropping and recreating the constraint with the new value)
```

Then deploy the new objects:

```bash
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
```

---

## System Requirements

- Oracle Database 23ai+ (tested on 26ai)
- `GRANT EXECUTE ON SYS.DBMS_CRYPTO` (carried from v3.1.0)
- Python 3.8+ with `oracledb` and `ldap3` packages
- SQLcl 26.1+ (for SQL script deployment)
