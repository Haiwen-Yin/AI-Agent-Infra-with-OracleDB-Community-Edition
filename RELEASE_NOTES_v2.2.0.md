# Oracle Memory System v2.2.0 Release Notes

**Release Date**: 2026-05-20
**Author**: Haiwen Yin (胖头鱼 🐟)
**License**: Apache License 2.0
**Compatibility**: Not backward-compatible with v2.1.0 — requires clean deployment

---

## Highlights

### 3 New Tables: WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS

Workspace-based session management with context chains for agent handoff and recovery:

| Table | Purpose | PK |
|-------|---------|-----|
| WORKSPACES | Workspace lifecycle, isolation, ownership | WORKSPACE_ID |
| WORKSPACE_CONTEXT | Version chain for context continuity (SNAPSHOT/CHECKPOINT/HANDOFF/SUMMARY/RECOVERY) | CONTEXT_ID |
| WORKSPACE_TASKS | Task-to-workspace linking | (WORKSPACE_ID, PLAN_ID) |

### JRD Updatable Views

| View | Mode | Description |
|------|------|-------------|
| WORKSPACE_DV | Updatable | Full workspace with nested context chain and tasks |
| CONTEXT_DV | Read-only | Context entries with workspace and agent details |
| MEMORY_DV | Updatable | Now confirmed updatable with JSON_TRANSFORM |
| KNOWLEDGE_DV | Updatable | Now confirmed updatable with JSON_TRANSFORM |

### Workspace API (workspace_api.py)

11 Python functions for workspace lifecycle, context chains, agent handoff, and recovery:

| Function | Description |
|----------|-------------|
| `create_workspace()` | Create a new workspace |
| `get_workspace()` | Retrieve workspace by ID |
| `get_user_workspaces()` | List workspaces for a user |
| `update_workspace()` | Update workspace fields |
| `save_context()` | Save context entry to version chain |
| `get_context_chain()` | Retrieve context history |
| `get_latest_context()` | Get most recent context |
| `create_handoff_session()` | Transfer workspace to a new agent |
| `recover_workspace()` | Get full recoverable workspace state |
| `link_task_to_workspace()` | Link a task plan to a workspace |
| `get_workspace_tasks()` | List workspace tasks |

### Context Continuity

Session chaining via `PREDECESSOR_SESSION_ID` enables agent handoff with full session history. Context entries form a version chain via `PARENT_CONTEXT_ID`, supporting SNAPSHOT, CHECKPOINT, HANDOFF, SUMMARY, and RECOVERY types.

---

## Breaking Changes from v2.1.0

### Schema

| Change | Impact |
|--------|--------|
| AGENT_SESSION: new `OWNER_USER_ID` column | Existing sessions have NULL; new sessions require it |
| AGENT_SESSION: new `WORKSPACE_ID` column | Nullable; links sessions to workspaces |
| AGENT_SESSION: new `PREDECESSOR_SESSION_ID` column | Nullable; chains sessions for handoff |
| ENTITIES: new `WORKSPACE_ID` column | Nullable; scopes entities to workspaces in ISOLATED mode |
| `ON DELETE CASCADE` on WORKSPACE_CONTEXT, WORKSPACE_TASKS | Child rows auto-deleted when parent workspace is deleted |

### Python API

- `create_session()` now accepts `owner_user_id`, `workspace_id`, `predecessor_session_id` parameters (all optional)
- New module: `workspace_api.py` (11 functions)
- New functions in `agent_api.py`: `checkpoint_session()`, `get_session_chain()`

---

## New Features

- **workspace_api.py** — 11 Python functions for workspace CRUD, context chains, handoff, recovery, and task linking
- **checkpoint_session()** — Save a CHECKPOINT context for the session's workspace
- **get_session_chain()** — Traverse PREDECESSOR_SESSION_ID backwards to return full session handoff chain
- **WORKSPACE_MANAGER PL/SQL package** — Server-side workspace management procedures
- **WORKSPACE_CLEANUP_JOB** — Scheduler job for workspace maintenance (daily 01:00)
- **CONTEXT_ARCHIVE_JOB** — Scheduler job for archiving old context entries (weekly Sun 03:00)
- **WORKSPACE_DV** — Updatable JRD view for workspace document API
- **CONTEXT_DV** — Read-only JRD view for context document API
- **3 new tables** — WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS
- **3 new AGENT_SESSION columns** — OWNER_USER_ID, WORKSPACE_ID, PREDECESSOR_SESSION_ID
- **ENTITIES.WORKSPACE_ID** — Entity scoping for ISOLATED workspaces

---

## Bug Fixes

- **MEMORY_DV now updatable** — Fixed JRD view definition to support INSERT/UPDATE/DELETE via JSON_TRANSFORM
- **KNOWLEDGE_DV now updatable** — Fixed JRD view definition to support INSERT/UPDATE/DELETE via JSON_TRANSFORM

---

## Test Results

```
Oracle Memory System v2.2.0 - Full Test Suite
============================================================
  Connection:  6/6 PASS
  Memory:      8/8 PASS
  Knowledge:   8/8 PASS
  Agent:       8/8 PASS
  Graph:       8/8 PASS
  Harness:     6/6 PASS
  Security:    5/5 PASS
  Workspace:  12/12 PASS

Overall: 61/61 ALL PASSED
```

---

## File Inventory

```
├── CHANGELOG.md
├── LICENSE
├── NOTICE
├── README.md
├── RELEASE_NOTES_v2.2.0.md
├── RELEASE_NOTES_v2.1.0.md
├── SKILL.md
├── config.json
├── start_web_server.sh
├── vis-network.min.js
├── viz_server_local_js.py
├── docs/
│   ├── architecture.md
│   ├── api-reference.md
│   ├── deployment.md
│   ├── harness.md
│   ├── introduction_v2.1.0_zh.md
│   ├── migration.md
│   ├── minimum-privileges.md
│   ├── security.md
│   ├── visualization.md
│   └── workspace.md
└── scripts/
    ├── deploy/
    │   ├── 1_schema.sql    (22 tables, indexes, 1 graph, 4 duality views)
    │   ├── 2_api.sql       (5 PL/SQL packages)
    │   ├── 3_jobs.sql      (9 scheduler jobs)
    │   └── 4_harness_templates.sql (5 built-in templates)
    ├── lib/
    │   ├── __init__.py
    │   ├── agent_api.py
    │   ├── config.py
    │   ├── connection.py
    │   ├── graph_api.py
    │   ├── harness_api.py
    │   ├── knowledge_api.py
    │   ├── memory_api.py
    │   ├── security.py
    │   ├── task_plan_api.py
    │   └── workspace_api.py
    └── tests/
        ├── __init__.py
        ├── test_all.py
        ├── test_agent.py
        ├── test_connection.py
        ├── test_graph.py
        ├── test_harness.py
        ├── test_knowledge.py
        ├── test_memory.py
        ├── test_security.py
        └── test_workspace.py
```

---

## Upgrade from v2.1.0

No migration path. This is a clean re-deploy (same approach as v2.1.0). Drop all tables and redeploy:

```bash
sql openclaw/hermes@//host:1521/service @scripts/deploy/1_schema.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/2_api.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/3_jobs.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/4_harness_templates.sql
```

All v2.1.0 data will be lost. Export before upgrading if needed.
