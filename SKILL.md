---
name: oracle-memory-by-yhw
version: v2.2.1
author: Haiwen Yin
description: "Oracle AI Database Memory System v2.2.1 - Template-based visualization, sidebar navigation, bilingual persistence, Graph Explorer, workspace detail view"
tags: [oracle, memory-system, knowledge-base, vector-search, oracledb, property-graph, multi-agent, partitioning, composite-pk, workspace, context-continuity, jrd, duality-view]
related_skills: [oracle-26ai, oracle-sqlcl-execution-methodology]
---

# Oracle AI Database Memory System v2.2.1

**Author:** Haiwen Yin
**Version:** v2.2.1 - 2026-05-23
**License:** Apache License 2.0

## Architecture Overview

```
+------------------------------------------------------------------+
|                        Oracle AI Memory System                   |
+------------------------------------------------------------------+
|                                                                  |
|  +-----------------------------------------------------------+   |
|  |           ENTITIES (unified, RANGE partitioned)           |   |
|  |  +----------+----------+----------+--------+--------------+   |
|  |  | MEMORY   | KNOWLEDGE|TASK_OUT  |EXPERI- | HARNESS_     |   |
|  |  |          |          |PUT       |ENCE    | TEMPLATE     |   |
|  |  +----------+----------+----------+--------+--------------+   |
|  |  PK: (ENTITY_ID, ENTITY_TYPE)                             |   |
|  |  COL: WORKSPACE_ID -> WORKSPACES                          |   |
|  +-----------------------------------------------------------+   |
|                         |                                        |
|  +----------------------------------------------+                |
|  |  ENTITY_EDGES (REFERENCE partitioned)        |                |
|  |  PK: (EDGE_ID, SOURCE_ID)                    |                |
|  |  FK: -> ENTITIES(ENTITY_ID, ENTITY_TYPE)     |                |
|  |  + 4 other reference-partitioned children    |                |
|  +----------------------------------------------+                |
|                                                                  |
|  +----------------------------------------------+                |
|  |  WORKSPACES                                  |                |
|  |  |-- WORKSPACE_CONTEXT (append-only JSON)    |                |
|  |  +-- WORKSPACE_TASKS (JRD updatable)         |                |
|  +----------------------------------------------+                |
|                                                                  |
|  +----------------------------------------------+                |
|  |  AGENT_SESSION (handoff chain)               |                |
|  |  PREDECESSOR_SESSION_ID -> self (chain)      |                |
|  +----------------------------------------------+                |
|                                                                  |
+------------------------------------------------------------------+
```

## v2.2.0 Key Addition: Workspace & Context Continuity

| Feature | Description |
|---------|-------------|
| WORKSPACES | Isolated execution environments for agents with shared/isolated modes |
| ISOLATION_MODE | SHARED (cross-workspace visibility) or ISOLATED (strict boundary) |
| WORKSPACE_CONTEXT | Append-only context chain (CHECKPOINT, HANDOFF, SUMMARY, ERROR_STATE, AUTO_SAVE) |
| Agent Handoff | Session chain via PREDECESSOR_SESSION_ID; context auto-loaded on create_session |
| JRD Updatable Views | WORKSPACE_DV, MEMORY_DV, KNOWLEDGE_DV support INSERT/UPDATE via Document API |
| ENTITIES.WORKSPACE_ID | FK to WORKSPACES; all entity queries scoped by workspace when ISOLATED |

## JSON Strategy

| Aspect | Strategy |
|--------|----------|
| Storage | Native JSON/OSON columns (ENTITY_DATA, CONTEXT_DATA, etc.) |
| Write | `json.dumps()` -> string bind variable (avoids DPY-3002) |
| Read | oracledb returns `dict` for JSON columns; `str` for JSON expressions |
| Modify | `JSON_TRANSFORM` (not `JSON_MERGEPATCH` -- causes OSON v2 DPY-3021) |
| Document API | JRD (JSON Relational Duality) for updatable views: WORKSPACE_DV, MEMORY_DV, KNOWLEDGE_DV |
| Context Chain | Raw SQL INSERT/SELECT (not JRD); append-only CONTEXT_DATA in WORKSPACE_CONTEXT |

## Partitioning Scheme

| Table | Partitioning Strategy |
|-------|-----------------------|
| ENTITIES | RANGE by ENTITY_TYPE (5 partitions: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE) |
| ENTITY_EDGES | REFERENCE from ENTITIES |
| ENTITY_EMBEDDINGS | REFERENCE from ENTITIES |
| ENTITY_TAGS | REFERENCE from ENTITIES |
| ENTITY_RELATIONSHIPS | REFERENCE from ENTITIES |
| ENTITY_VERSIONS | REFERENCE from ENTITIES |
| TASK_PLANS | RANGE by STATUS |
| TASK_STEPS | REFERENCE from TASK_PLANS |
| AGENT_SESSION | RANGE by IS_ACTIVE |
| AGENT_ACCESS_LOG | RANGE by CREATED_AT (monthly) |

**Note:** 5 reference-partitioned children (ENTITY_EDGES, ENTITY_EMBEDDINGS, ENTITY_TAGS, ENTITY_RELATIONSHIPS, ENTITY_VERSIONS). 12 non-partitioned tables: AGENTS, AGENT_PERMISSIONS, KNOWLEDGE_VALIDATIONS, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS, HARNESS_TEMPLATES, HARNESS_INSTANCES, GRAPH_METADATA, SYSTEM_CONFIG, SYSTEM_AUDIT_LOG, EMBEDDING_CACHE.

## Composite Primary Keys

| Table | Composite PK | Notes |
|-------|-------------|-------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | Unified table; ENTITY_TYPE is partition key |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | SOURCE_ID is part of PK for reference partitioning |
| TASK_PLANS | (PLAN_ID, STATUS) | STATUS is partition key; included in PK |
| AGENT_SESSION | (SESSION_ID, IS_ACTIVE) | IS_ACTIVE is partition key; included in PK |
| WORKSPACE_TASKS | (WORKSPACE_ID, PLAN_ID) | Junction table; FK to both WORKSPACES and TASK_PLANS |

**Note:** Global unique constraints (UK_ENTITY_ID, UK_EDGE_ID, etc.) enforce uniqueness across partitions. ON DELETE CASCADE on all child tables (required for JRD updatable views).

## JRD Duality Views (4 Views)

| View | Mode | Root Table | Nested Objects |
|------|------|------------|----------------|
| WORKSPACE_DV | updatable | WORKSPACES | WORKSPACE_TASKS (via FK) |
| CONTEXT_DV | read-only | WORKSPACE_CONTEXT | -- (flat view) |
| MEMORY_DV | updatable | ENTITIES (ENTITY_TYPE=MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | updatable | ENTITIES (ENTITY_TYPE=KNOWLEDGE) | ENTITY_TAGS, ENTITY_EDGES |

**Notes:**
- 26ai annotations (`@insert`, `@update`, `@delete`) required on columns for write operations
- JRD does not support JOINs in nested subqueries; use FK-based nesting only
- WORKSPACE_CONTEXT is excluded from WORKSPACE_DV because it is append-only (use raw SQL)
- JRD views must include all PK columns of root table
- CONTEXT_DV is read-only (no 26ai write annotations)

## Quick Start

### Deploy Schema (4 Phases)

```sql
-- Phase 1: Core tables (ENTITIES, ENTITY_EDGES, ENTITY_EMBEDDINGS, ENTITY_TAGS, etc.)
@scripts/deploy/01_core_tables.sql

-- Phase 2: Agent & Task tables (AGENTS, AGENT_SESSION, TASK_PLANS, TASK_STEPS, etc.)
@scripts/deploy/02_agent_task_tables.sql

-- Phase 3: Workspace & System tables (WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS, etc.)
@scripts/deploy/03_workspace_system_tables.sql

-- Phase 4: Views, Packages, Jobs, Graph (JRD views, PL/SQL, scheduler, property graph)
@scripts/deploy/04_views_packages_jobs.sql
```

### Install Python

```bash
pip install oracledb
```

### Configure

```bash
export ORACLE_DSN="//10.10.10.130:1521/openclaw"
export ORACLE_USER="openclaw"
export ORACLE_PASSWORD="hermes"
```

### Run Tests

```bash
cd scripts && python -m tests.test_all
```

### Start Web Server

```bash
./start_web_server.sh start    # Start (daemon)
./start_web_server.sh status   # Status + config
./start_web_server.sh stop     # Stop
./start_web_server.sh restart  # Restart
```

## Project Structure

```
scripts/
  deploy/
    1_schema.sql              # Tables, indexes, property graph, JRD views (22 tables, 4 views)
    2_api.sql                 # PL/SQL packages (fusion, knowledge, permissions, cleanup, workspace)
    3_jobs.sql                # Scheduler jobs (9 automated jobs)
    4_harness_templates.sql   # HARNESS_META + 5 built-in harness templates
  lib/
    config.py                 # Unified Config dataclass with env var overrides
    connection.py             # oracledb connection pool + Decimal sanitization helpers
    memory_api.py             # Memory CRUD on ENTITIES, workspace_id support
    knowledge_api.py          # Knowledge CRUD + graph + edges, workspace_id support
    agent_api.py              # Agent registration, sessions, handoff, collaboration
    task_plan_api.py          # Task plans, steps, snapshots, tool calls, dependencies
    security.py               # DataMaskingService, ReversibleEncryption, password hashing
    harness_api.py            # Harness template CRUD, instantiate, derive, validate
    graph_api.py              # Property Graph API with GRAPH_TABLE SQL operator (9 functions)
    workspace_api.py          # Workspace lifecycle, context chains, handoff, recovery (11 functions)
  tests/
    test_connection.py        # Connection pool tests (6)
    test_memory.py            # Memory CRUD tests (8)
    test_knowledge.py         # Knowledge CRUD tests (8)
    test_agent.py             # Agent registration/session tests (8)
    test_security.py          # Security feature tests (5)
    test_harness.py           # Harness template tests (6)
    test_graph.py             # Property Graph tests (8)
    test_workspace.py         # Workspace & context tests (12)
    test_all.py               # Master runner (61 total)
  visualization/
    server.py                 # HTTP server (session auth, page routing, JSON API)
    templates/
      login.html              # Card-style login page
      knowledge.html          # Knowledge: list/graph dual view + detail panel
      memory.html             # Memory: list/graph dual view + category filter
      agents.html             # Agents: Bootstrap tabs (registry/sessions/collabs)
      tasks.html              # Tasks: Accordion with step details + tool I/O
      workspaces.html         # Workspaces: expandable detail rows + context timeline
      graph.html              # Graph Explorer: stats + search + vis-network + detail
    static/
      style.css               # Dark theme CSS variables + sidebar styles
      vis-network.min.js      # Vis.js network visualization library
docs/
  architecture.md             # Detailed architecture and design decisions
  api-reference.md            # Python and PL/SQL API documentation
  deployment.md               # Deployment guide and troubleshooting
  migration.md                # v1.x -> v2.2 migration guide
  security.md                 # Security features and configuration
  visualization.md            # Web visualization server guide
  harness.md                  # Harness template system guide
  workspace.md                # Workspace & context continuity design
  minimum-privileges.md       # Minimum database user privileges
  introduction_v2.2.1_zh.md   # v2.2.1 Chinese introduction
```

## Database Schema (22 Tables)

### Core Tables (8)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| ENTITIES | Unified entity store (MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE) | ENTITY_ID, ENTITY_TYPE, WORKSPACE_ID, ENTITY_DATA (JSON), CREATED_AT, UPDATED_AT, IMPORTANCE, ACCESS_COUNT |
| ENTITY_EDGES | Directed relationships between entities | EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID, TARGET_TYPE, EDGE_TYPE, RELATIONSHIP_STRENGTH |
| ENTITY_EMBEDDINGS | Vector embeddings for semantic search | ENTITY_ID, ENTITY_TYPE, EMBEDDING_VECTOR, EMBEDDING_MODEL |
| ENTITY_TAGS | Tags for categorization and filtering | ENTITY_ID, ENTITY_TYPE, TAG_NAME, TAG_CATEGORY |
| ENTITY_RELATIONSHIPS | Rich relationship metadata | RELATIONSHIP_ID, ENTITY_ID, ENTITY_TYPE, RELATED_ENTITY_ID, RELATIONSHIP_TYPE, METADATA (JSON) |
| ENTITY_VERSIONS | Version history for entities | ENTITY_ID, ENTITY_TYPE, VERSION_NUMBER, ENTITY_DATA (JSON), CHANGE_DESCRIPTION |
| KNOWLEDGE_VALIDATIONS | Validation records for knowledge entities | VALIDATION_ID, ENTITY_ID, VALIDATED_BY, VALIDATION_STATUS, VALIDATION_NOTES |
| GRAPH_METADATA | Property Graph metadata | GRAPH_ID, GRAPH_NAME, GRAPH_TYPE, METADATA (JSON) |

### Agent Tables (4)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| AGENTS | Registered agent definitions | AGENT_ID, AGENT_NAME, AGENT_TYPE, CAPABILITIES (JSON), CREATED_AT |
| AGENT_SESSION | Agent session with handoff chain | SESSION_ID, IS_ACTIVE, AGENT_ID, OWNER_USER_ID, WORKSPACE_ID, PREDECESSOR_SESSION_ID, SESSION_DATA (JSON) |
| AGENT_PERMISSIONS | Agent access control rules | PERMISSION_ID, AGENT_ID, RESOURCE_TYPE, ACCESS_LEVEL, CONSTRAINTS (JSON) |
| AGENT_ACCESS_LOG | Audit trail of agent actions | LOG_ID, SESSION_ID, ACTION_TYPE, RESOURCE_TYPE, RESOURCE_ID, ACCESSED_AT |

### Task Tables (5)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| TASK_PLANS | Task plan definitions | PLAN_ID, STATUS, TITLE, DESCRIPTION, OWNER_AGENT_ID, CREATED_AT |
| TASK_STEPS | Individual steps within plans | STEP_ID, PLAN_ID, STATUS, STEP_ORDER, STEP_TYPE, STEP_DATA (JSON) |
| HARNESS_TEMPLATES | Reusable agent harness templates | TEMPLATE_ID, TEMPLATE_NAME, TEMPLATE_TYPE, INPUT_SCHEMA (JSON), OUTPUT_SCHEMA (JSON), TEMPLATE_DATA (JSON) |
| HARNESS_INSTANCES | Instantiated harness instances | INSTANCE_ID, TEMPLATE_ID, AGENT_ID, INSTANCE_DATA (JSON), STATUS |
| EMBEDDING_CACHE | Cached embedding results | CACHE_KEY, EMBEDDING_VECTOR, EMBEDDING_MODEL, CREATED_AT |

### Workspace Tables (3 NEW)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| WORKSPACES | Isolated agent execution environments | WORKSPACE_ID, WORKSPACE_NAME, ISOLATION_MODE, OWNER_USER_ID, DESCRIPTION, CREATED_AT |
| WORKSPACE_CONTEXT | Append-only context chain (CHECKPOINT, HANDOFF, SUMMARY, ERROR_STATE, AUTO_SAVE) | CONTEXT_ID, WORKSPACE_ID, CONTEXT_TYPE, CONTEXT_DATA (JSON), CREATED_BY, CREATED_AT |
| WORKSPACE_TASKS | Junction: workspace <-> task plans | WORKSPACE_ID, PLAN_ID, ASSIGNED_AT |

### System Tables (2)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| SYSTEM_CONFIG | Global configuration key-value store | CONFIG_KEY, CONFIG_VALUE (JSON), DESCRIPTION, UPDATED_AT |
| SYSTEM_AUDIT_LOG | System-level audit trail | AUDIT_ID, EVENT_TYPE, EVENT_DATA (JSON), EVENT_TIMESTAMP |

## PL/SQL Packages (5 Packages)

| Package | Function Count | Key Functions |
|---------|---------------|---------------|
| MEMORY_FUSION | 7 | fuse_similar_memories, decay_memories, reinforce_memory, search_memories, get_memory_stats, consolidate_memories, archive_old_memories |
| KNOWLEDGE_MANAGER | 5 | validate_knowledge, link_knowledge, get_knowledge_graph, find_contradictions, resolve_contradiction |
| AGENT_PERMISSION_MANAGER | 5 | check_permission, grant_permission, revoke_permission, get_agent_permissions, audit_permissions |
| SYSTEM_CLEANUP | 4 | cleanup_expired_sessions, cleanup_orphaned_entities, vacuum_embeddings, purge_audit_log |
| WORKSPACE_MANAGER | 10 | create_workspace, get_workspace, update_workspace, save_context, get_context_chain, get_latest_context, create_handoff_session, recover_workspace, link_task_to_workspace, cleanup_workspace |

## Python API (10 Modules, 80+ Functions)

### connection.py

```python
def get_connection() -> oracledb.Connection
def release_connection(conn: oracledb.Connection) -> None
def _sanitize_json(obj: Any) -> Any
def sanitize_row(row: dict) -> dict
```

### memory_api.py

```python
def create_memory(entity_data: dict, workspace_id: str = None, isolation_mode: str = "SHARED") -> str
def get_memory(entity_id: str, entity_type: str = "MEMORY") -> dict | None
def search_memories(query: str, top_k: int = 10, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def update_memory(entity_id: str, entity_data: dict, entity_type: str = "MEMORY") -> bool
def delete_memory(entity_id: str, entity_type: str = "MEMORY") -> bool
def reinforce_memory(entity_id: str, entity_type: str = "MEMORY") -> bool
def get_agent_memories(agent_id: str, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def decay_memories(threshold: float = 0.1) -> int
```

### knowledge_api.py

```python
def create_knowledge(entity_data: dict, workspace_id: str = None, isolation_mode: str = "SHARED", owned_by_agent: str = None) -> str
def get_knowledge(entity_id: str) -> dict | None
def search_knowledge(query: str, top_k: int = 10, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def validate_knowledge(entity_id: str, validated_by: str, status: str, notes: str = None) -> bool
def link_knowledge(source_id: str, target_id: str, edge_type: str, strength: float = 1.0) -> str
def add_edge(source_id: str, source_type: str, target_id: str, target_type: str, edge_type: str, strength: float = 1.0) -> str
def get_edges(entity_id: str, entity_type: str, direction: str = "outgoing") -> list[dict]
```

### agent_api.py

```python
def register_agent(agent_name: str, agent_type: str, capabilities: dict) -> str
def get_agent(agent_id: str) -> dict | None
def create_session(agent_id: str, owner_user_id: str = None, workspace_id: str = None, predecessor_session_id: str = None) -> str
def end_session(session_id: str) -> bool
def get_active_sessions(workspace_id: str = None) -> list[dict]
def log_access(session_id: str, action_type: str, resource_type: str, resource_id: str) -> str
def request_collaboration(session_id: str, target_agent_id: str, message: str) -> str
def checkpoint_session(session_id: str, checkpoint_data: dict) -> bool
def get_session_chain(session_id: str) -> list[dict]
```

### task_plan_api.py

```python
def create_plan(title: str, description: str, owner_agent_id: str) -> str
def get_plan(plan_id: str, status: str = "ACTIVE") -> dict | None
def update_plan_status(plan_id: str, status: str) -> bool
def add_step(plan_id: str, step_type: str, step_data: dict, step_order: int = None) -> str
def update_step_status(plan_id: str, step_id: str, status: str) -> bool
def get_plan_steps(plan_id: str, status: str = "ACTIVE") -> list[dict]
```

### harness_api.py

```python
def create_template(template_name: str, template_type: str, template_data: dict, input_schema: dict = None, output_schema: dict = None) -> str
def get_template(template_id: str) -> dict | None
def list_templates(template_type: str = None) -> list[dict]
def instantiate_template(template_id: str, agent_id: str, instance_data: dict = None) -> str
def derive_template(parent_id: str, template_name: str, modifications: dict) -> str
def validate_template(template_id: str) -> dict
```

### graph_api.py

```python
def create_entity_graph(entity_id: str, entity_type: str, depth: int = 3) -> dict
def shortest_path(source_id: str, target_id: str, max_depth: int = 10) -> list[str]
def get_neighbors(entity_id: str, entity_type: str, edge_type: str = None) -> list[dict]
def get_community(entity_id: str, entity_type: str) -> list[dict]
def graph_stats() -> dict
def search_by_structure(pattern: dict) -> list[dict]
def get_entity_timeline(entity_id: str, entity_type: str) -> list[dict]
def get_strongest_path(source_id: str, target_id: str, min_strength: float = 0.5) -> list[dict]
def export_graph(entity_id: str, entity_type: str, format: str = "json") -> str
```

### workspace_api.py

```python
def create_workspace(name: str, description: str = None, isolation_mode: str = "SHARED", owner_user_id: str = None) -> str
def get_workspace(workspace_id: str) -> dict | None
def update_workspace(workspace_id: str, **kwargs) -> bool
def list_workspaces(owner_user_id: str = None) -> list[dict]
def save_context(workspace_id: str, context_type: str, context_data: dict, created_by: str) -> str
def get_context(workspace_id: str, context_type: str = None, limit: int = 10) -> list[dict]
def get_context_chain(workspace_id: str, context_type: str = None) -> list[dict]
def get_latest_context(workspace_id: str, context_type: str = None) -> dict | None
def create_handoff_session(agent_id: str, workspace_id: str, predecessor_session_id: str, owner_user_id: str = None) -> str
def recover_workspace(workspace_id: str) -> dict
def link_task_to_workspace(workspace_id: str, plan_id: str) -> bool
def get_workspace_tasks(workspace_id: str) -> list[dict]
def get_user_workspaces(user_id: str) -> list[dict]
```

### security.py

```python
class DataMaskingService:
    def mask(self, data: str, mask_type: str = "full") -> str
    def unmask(self, masked_data: str, key: str) -> str

class ReversibleEncryption:
    def encrypt(self, plaintext: str) -> tuple[str, str]
    def decrypt(self, ciphertext: str, key: str) -> str

def hash_password(password: str) -> str
def verify_password(password: str, password_hash: str) -> bool
```

## Scheduler Jobs (9 Jobs)

| Job | Schedule | Description |
|-----|----------|-------------|
| MEMORY_DECAY_JOB | Daily 03:00 | Decays memory importance scores over time; archives below threshold |
| KNOWLEDGE_VALIDATION_JOB | Daily 05:00 | Re-validates knowledge entities past validation period |
| SESSION_CLEANUP_JOB | Hourly | Ends stale active sessions past timeout threshold |
| ORPHAN_CLEANUP_JOB | Daily 02:00 | Removes entities with no edges and no references |
| EMBEDDING_VACUUM_JOB | Weekly Sunday 01:00 | Rebuilds embedding index and purges stale cache |
| AGENT_HEALTH_CHECK_JOB | Every 30 min | Checks agent heartbeats; marks unresponsive agents |
| PERMISSION_AUDIT_JOB | Daily 06:00 | Audits agent permissions for compliance violations |
| WORKSPACE_CLEANUP_JOB | Daily 04:00 | Archives completed workspaces and their context chains |
| STALE_WORKSPACE_DETECT_JOB | Hourly | Detects workspaces with no active sessions for N hours |

## Harness Templates (5 Built-in)

| Template | Description |
|----------|-------------|
| RESEARCH_AGENT | Multi-step research workflow: gather sources, synthesize findings, produce structured report |
| CODE_REVIEW_AGENT | Code analysis workflow: parse code, identify issues, suggest improvements, generate review summary |
| DATA_ANALYSIS_AGENT | Data pipeline: load data, compute statistics, generate visualizations, produce insights report |
| CONVERSATION_AGENT | Multi-turn dialogue: maintain context, track intent, manage dialogue state, generate responses |
| TASK_EXECUTION_AGENT | General task execution: plan steps, execute sequentially, handle errors, report outcomes |

## CONTEXT_DATA Structures (v2.2.0)

### CHECKPOINT
```json
{
  "session_state": "<serialized agent state>",
  "working_memory": "<current working memory snapshot>",
  "active_goals": ["<goal_id>", ...],
  "tool_state": "<tool-specific state data>"
}
```

### HANDOFF
```json
{
  "summary": "<handoff summary text>",
  "pending_items": ["<item>", ...],
  "decisions": ["<decision>", ...],
  "recommendations": ["<recommendation>", ...]
}
```

### SUMMARY
```json
{
  "key_findings": ["<finding>", ...],
  "decisions_made": ["<decision>", ...],
  "outcomes": ["<outcome>", ...],
  "metrics": {"<key>": "<value>", ...}
}
```

### ERROR_STATE
```json
{
  "error_type": "<exception class>",
  "error_message": "<human-readable message>",
  "stack_trace": "<traceback string>",
  "recovery_hints": ["<hint>", ...]
}
```

### AUTO_SAVE
```json
{
  "incremental_state": "<partial state delta>",
  "last_operation": "<operation description>",
  "timestamp": "<ISO 8601>"
}
```

## Critical oracledb Quirks

- **JSON column reads**: `dict`; **JSON expression reads**: `str`; **PL/SQL JSON return**: `dict`; **JSON_VALUE**: `str`; **JSON_QUERY**: `dict`/`list`; **NULL**: `None`
- **JSON writes**: `json.dumps()` string bind works; dict direct bind fails (DPY-3002); `oracledb.DB_TYPE_JSON` typed var works
- **JSON_MERGEPATCH** -> OSON v2 error (DPY-3021); use **JSON_TRANSFORM** instead
- **JRD etag**: oracledb returns `bytes`; update without `_metadata` succeeds; wrong etag -> ORA-42699
- **JRD INSERT via Python**: pass JSON string as bind to `INSERT INTO VIEW (DATA) VALUES (:data)`
- **Decimal**: oracledb thin returns `decimal.Decimal` for NUMBER in JSON; use `_sanitize_json`/`sanitize_row`

## Key Design Decisions

- **JRD vs native JSON**: WORKSPACE_CONTEXT uses native JSON (append-only); WORKSPACES + WORKSPACE_TASKS use JRD
- **26ai JRD annotations** required for write operations (`@insert`, `@update`, `@delete`)
- **JRD no JOINs** in nested subqueries; use FK-based nesting only
- **JRD must include all PK columns** of root table in the view definition
- **ON DELETE CASCADE** on child tables (required for JRD updatable views to handle parent deletion)
- **AGENT_SESSION self-ref FK** via `UK_SESSION_ID` (unique constraint on SESSION_ID for predecessor reference)
- **WORKSPACE_TASKS created after TASK_PLANS** (FK dependency on TASK_PLANS.PLAN_ID)
- **OWNER_USER_ID nullable** on WORKSPACES (system workspaces may have no owner)
- **ISOLATION_MODE**: `SHARED` (entities visible across workspaces) vs `ISOLATED` (strict workspace boundary)
- **Context checkpoint**: agent-initiated only; no automatic checkpointing on session end

## Deployment Notes

- Use `safe_ddl` / `safe_idx` helpers in deploy scripts to avoid re-creating existing objects
- Drop tables with retry loop (reference-partitioned children must be dropped before parents; order matters)
- `add_edge` requires `source_type` parameter (part of composite PK on ENTITY_EDGES)
- `create_knowledge` uses `owned_by_agent` parameter to set ownership on knowledge entities

## Database Connection

| Parameter | Value |
|-----------|-------|
| DSN | `//10.10.10.130:1521/openclaw` |
| User | `openclaw` / `hermes` |
| Python | `/home/linuxbrew/.linuxbrew/bin/python3.14` (3.14.5, oracledb 4.0.0) |
| Server | `10.10.10.136:8000` (admin/admin) |
