# Architecture - AI Agent Infra v4.0.1

## v4.0.1 Control Planes

The database is the durable source of truth for entities, knowledge, memory,
tasks, complete Skill packages, Agent identity mappings, execution policy,
approvals, attempts, leases, results, and audit records. The web process
authenticates and queues side effects; workers claim durable jobs and perform
bounded execution outside the request thread.

Core behavior is equivalent across Oracle AI Database, PostgreSQL, and
YashanDB, while native SQL, graph/search facilities, migrations, and identity
provisioning remain in adapters. Community and Enterprise are build-time
allowlists rather than runtime branding flags.

Each Business Agent has an independent database identity and cannot use the
schema owner: Oracle End User plus Data Grants, PostgreSQL LOGIN role plus RLS
identity, or YashanDB user plus object grants. The authenticated request Agent
must match the configured database identity, otherwise access fails closed.

Execution jobs progress through approval, pending, running, retry, and terminal
states. Claims use a lease token; completion is accepted only for the active
lease. At-least-once delivery is paired with idempotency keys. URL validation
and command policy are applied before a worker performs a side effect.

Skill ZIP files are parsed into immutable package versions. `SKILL.md` and all
normalized nested files retain hashes; acquisition verifies visibility and
integrity before creating a read-only materialized tree.

## Unified Entity Model

## Unified Entity Model

v3.7.0 extends the unified model with workspace management, context continuity, JRD updatable views, and Deep Data Security.

### ENTITIES

Single table with `ENTITY_TYPE` discriminator, composite PK `(ENTITY_ID, ENTITY_TYPE)`:

- **MEMORY**: Short-term agent memories. Fields: title, content, summary, category, importance, status, visibility, source_agent
- **KNOWLEDGE**: Long-term validated knowledge. Extended by KNOWLEDGE_META for domain, topic, difficulty, spaced review
- **TASK_OUTPUT**: Task execution results
- **EXPERIENCE**: Learned patterns and heuristics
- **HARNESS_TEMPLATE**: Reusable agent execution blueprints. Extended by HARNESS_META for input_schema, output_schema, execution_mode
- **OTHER**: Catch-all for future entity types

**v3.4.0 column changes from v2.0**:

| v2.0 Column | v2.1 Column | Notes |
|-------------|-------------|-------|
| NAME | TITLE | Renamed |
| PRIORITY | IMPORTANCE | Renamed, range 1-10 |
| TAGS (JSON) | ENTITY_TAGS + TAGS tables | Normalized into separate tables |
| METADATA (JSON) | *(removed)* | Only on ENTITY_EDGES now |
| ACCESSIBLE_TO (JSON) | *(removed)* | Visibility simplified to PRIVATE/SHARED/PUBLIC |
| DESCRIPTION | *(removed)* | SUMMARY replaces it on ENTITIES; DESCRIPTION lives on TASK_STEPS |
| *(new)* | SUMMARY | VARCHAR2(2000) entity summary |
| *(new)* | SOURCE_AGENT | VARCHAR2(64) creating agent |
| *(new)* | RETRIEVAL_COUNT | NUMBER(10,0) access counter |
| *(new)* | IMPORTANCE | NUMBER(3,0) 1-10, replaces PRIORITY |

### ENTITY_EDGES

Unified directed edge table with composite PK `(EDGE_ID, SOURCE_ID)`:

- **SOURCE_TYPE**: Denormalized ENTITY_TYPE of the source entity (required for composite FK)
- FK: `(SOURCE_ID, SOURCE_TYPE)` references `ENTITIES(ENTITY_ID, ENTITY_TYPE)`
- Edge types: DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS
- METADATA (JSON) column on edges only

## Composite Primary Keys & Denormalized ENTITY_TYPE

v2.1 uses composite PKs to enable partition-by-reference on child tables. The `ENTITY_TYPE` column is denormalized onto every child table that references ENTITIES:

| Table | PK | FK to ENTITIES | Denormalized Column |
|-------|----|----------------|-------------------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | — | — |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | (SOURCE_ID, SOURCE_TYPE) | SOURCE_TYPE |
| KNOWLEDGE_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_EMBEDDINGS | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| HARNESS_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_TAGS | (ENTITY_ID, ENTITY_TYPE, TAG_ID) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |

TASK_PLANS and TASK_STEPS also use composite PKs:

| Table | PK | UK |
|-------|----|----|
| TASK_PLANS | (PLAN_ID, STATUS) | UK_TASK_PLANS_ID (PLAN_ID) |
| TASK_STEPS | (STEP_ID, PLAN_ID) | UK_TASK_STEPS_ID (STEP_ID) |
| ENTITY_ACCESS_LOG | (LOG_ID) via UK | UK_ACCESS_LOG_ID (LOG_ID) |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | UK_EDGES_ID (EDGE_ID) |
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | UK_ENTITIES_ID (ENTITY_ID) |

Global unique constraints (UK_*) ensure ID uniqueness across partitions when the PK is composite.

## Partitioning Architecture

### ENTITIES — LIST + RANGE (6 partitions × 7 subpartitions = 42 subpartitions)

```
PARTITION BY LIST (ENTITY_TYPE)
  P_MEMORY, P_KNOWLEDGE, P_TASK_OUTPUT, P_EXPERIENCE, P_HARNESS, P_OTHERS

SUBPARTITION BY RANGE (CREATED_AT)
  SP_2026Q1 .. SP_2027Q2, SP_FUTURE
```

Benefits: Queries filtering by ENTITY_TYPE prune to a single partition; time-range queries further prune to subpartitions.

### Reference Partitioned Tables (5 tables)

ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, and ENTITY_TAGS inherit their partitioning from the parent ENTITIES table via `PARTITION BY REFERENCE (FK_...)`. This ensures child rows co-locate with their parent entity partition.

### AGENT_SESSION — LIST + RANGE

```
PARTITION BY LIST (IS_ACTIVE): P_ACTIVE('Y'), P_INACTIVE('N')
SUBPARTITION BY RANGE (START_TIME): quarterly subpartitions
```

ROW MOVEMENT enabled — when a session transitions from active to inactive, the row physically moves to the inactive partition.

### TASK_PLANS — LIST + RANGE

```
PARTITION BY LIST (STATUS): P_ACTIVE(PENDING/RUNNING/BLOCKED), P_TERMINAL(SUCCESS/FAILED/CANCELLED)
SUBPARTITION BY RANGE (CREATED_AT): quarterly subpartitions
```

ROW MOVEMENT enabled — plan status changes cause row movement between active/terminal partitions.

TASK_STEPS inherits partitioning via reference to TASK_PLANS.

### ENTITY_ACCESS_LOG — RANGE + HASH

```
PARTITION BY RANGE (ACCESS_TIME): monthly partitions
SUBPARTITION BY HASH (AGENT_ID) SUBPARTITIONS 4
```

Optimized for time-range access log queries with hash-based subpartitioning for concurrent agent access patterns.

### Non-Partitioned Tables

AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS, SYSTEM_CONFIG, SYSTEM_USERS.

## Visibility Model

| Level | Behavior |
|-------|----------|
| PRIVATE | Only owner agent can access |
| SHARED | All registered agents can access |
| PUBLIC | Unrestricted access (v2.1 addition, replaces COLLABORATIVE) |

The COLLABORATIVE level and ACCESSIBLE_TO JSON array from v2.0 have been removed. AGENT_COLLABORATION handles cross-agent sharing.

## Property Graph

### ORACLE_MEMORY_GRAPH

Single property graph using composite vertex key `(ENTITY_ID, ENTITY_TYPE)`:

```sql
CREATE PROPERTY GRAPH ORACLE_MEMORY_GRAPH
  VERTEX TABLES (
    ENTITIES KEY (ENTITY_ID, ENTITY_TYPE)
      PROPERTIES (ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                  OWNED_BY_AGENT, VISIBILITY, IMPORTANCE, CREATED_AT, UPDATED_AT)
  )
  EDGE TABLES (
    ENTITY_EDGES KEY (EDGE_ID, SOURCE_ID)
      SOURCE KEY (SOURCE_ID, SOURCE_TYPE) REFERENCES ENTITIES(ENTITY_ID, ENTITY_TYPE)
      DESTINATION KEY (TARGET_ID) REFERENCES ENTITIES(ENTITY_ID)
      PROPERTIES (EDGE_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, CREATED_AT)
  );
```

### Property Graph API (graph_api.py)

9 Python functions using the `GRAPH_TABLE` SQL operator:

| Function | Description |
|----------|-------------|
| `get_neighbors(entity_id, direction, edge_type, min_strength, limit)` | Get adjacent entities with direction filtering |
| `get_reachable(entity_id, max_hops, edge_type, limit)` | Multi-hop reachability via `{1,max_hops}` pattern |
| `get_shortest_path(source_id, target_id, max_hops)` | Shortest path between two entities (up to 6 hops) |
| `find_similar_entities(entity_id, max_hops, limit)` | Find structurally similar entities via graph proximity |
| `get_entity_context(entity_id, depth)` | Full entity context with neighbors grouped by type/edge |
| `get_graph_stats()` | Graph statistics: vertex/edge counts, degree distribution |
| `get_subgraph(entity_ids, include_intermediate)` | Extract subgraph by entity ID list |
| `find_communities(entity_type, min_connections, limit)` | Find highly-connected entity clusters |
| `graph_search(keyword, entity_type, category, min_importance, limit)` | Graph-aware search via GRAPH_TABLE |

## JSON Duality Views

- **MEMORY_DV**: JSON read/write view for MEMORY-type entities with edges and tags. Uses composite `_id: {entity_id, entity_type}`
- **KNOWLEDGE_DV**: JSON read/write view for KNOWLEDGE-type entities with metadata, edges, and tags

Both views join ENTITY_EDGES on `(SOURCE_ID = ENTITY_ID AND SOURCE_TYPE = ENTITY_TYPE)` and ENTITY_TAGS on `(ENTITY_ID, ENTITY_TYPE)`.

## ID Generation

All IDs are `VARCHAR2(64)`, generated via `RAWTOHEX(SYS_GUID())` producing 32-character hex strings. Prefix conventions: `E_` for edges, `SES_` for sessions, `LOG_` for access logs, `COL_` for collaborations, `PLAN_` for plans, `STEP_` for steps, `SNAP_` for snapshots, `CALL_` for tool calls, `DEP_` for dependencies, `HARNESS_` for templates.

## Design Decisions

1. **Composite PKs** enable partition-by-reference and co-location of parent/child rows
2. **Denormalized ENTITY_TYPE** on child tables required for composite FKs and reference partitioning
3. **ROW MOVEMENT** on AGENT_SESSION, TASK_PLANS, TASK_STEPS allows physical row migration when partition key changes
4. **LIST + RANGE partitioning** on ENTITIES enables type-based pruning + time-based archival
5. **RANGE + HASH** on ENTITY_ACCESS_LOG optimizes for time-range scans with concurrent agent access
6. **Global UK constraints** ensure logical ID uniqueness when PK is composite
7. **Normalized tags** (TAGS + ENTITY_TAGS) replace JSON TAGS column for indexable tag queries
8. **CLOB** for CONTENT fields (large text storage)
9. **VECTOR** for embeddings (compatible with BGE-M3 model)
10. **ON DELETE CASCADE** not used — explicit child-table deletes in Python APIs for safety with partitioned tables

## Workspace & Context Continuity

v3.4.0 adds workspace-based session management with context chains for agent handoff and recovery.

### WORKSPACES Table

Top-level container for grouping entities, sessions, and tasks:

| Column | Type | Description |
|--------|------|-------------|
| WORKSPACE_ID | VARCHAR2(64) | PK, `'WS_' \|\| RAWTOHEX(SYS_GUID())` |
| OWNER_USER_ID | VARCHAR2(64) | User who owns the workspace |
| WORKSPACE_NAME | VARCHAR2(200) | Human-readable name |
| WORKSPACE_TYPE | VARCHAR2(30) | CONVERSATION, PROJECT, ANALYSIS |
| ISOLATION_MODE | VARCHAR2(20) | SHARED (default) or ISOLATED |
| CURRENT_AGENT_ID | VARCHAR2(64) | Agent currently controlling the workspace |
| CURRENT_SESSION_ID | VARCHAR2(64) | Active session in the workspace |
| SUMMARY | VARCHAR2(4000) | Current workspace summary |
| METADATA | JSON | Arbitrary workspace metadata |
| STATUS | VARCHAR2(20) | ACTIVE, PAUSED, ARCHIVED |
| CREATED_AT / UPDATED_AT | TIMESTAMP | Lifecycle timestamps |

Lifecycle: `ACTIVE → PAUSED → ARCHIVED`. In ISOLATED mode, entities created within the workspace are scoped by `ENTITIES.WORKSPACE_ID`.

### WORKSPACE_CONTEXT Table

Version chain of context entries enabling continuity across sessions and agent handoffs:

| Column | Type | Description |
|--------|------|-------------|
| CONTEXT_ID | VARCHAR2(64) | PK, `'CTX_' \|\| RAWTOHEX(SYS_GUID())` |
| WORKSPACE_ID | VARCHAR2(64) | FK to WORKSPACES |
| AGENT_ID | VARCHAR2(64) | Agent that created this context |
| SESSION_ID | VARCHAR2(64) | Session during which context was created |
| CONTEXT_TYPE | VARCHAR2(30) | SNAPSHOT, CHECKPOINT, HANDOFF, SUMMARY, RECOVERY |
| CONTEXT_DATA | JSON | Structured context payload |
| PARENT_CONTEXT_ID | VARCHAR2(64) | FK to parent context (version chain) |
| VISIBILITY | VARCHAR2(16) | PRIVATE/SHARED/PUBLIC (default SHARED). Controls cross-agent visibility in collab workspaces: PRIVATE blocks other agents, SHARED visible to collab group members, PUBLIC visible to all |
| CREATED_AT | TIMESTAMP | Creation timestamp |

The `PARENT_CONTEXT_ID` column forms a linked list (version chain) — each context entry points to its predecessor, enabling full history traversal. CONTEXT_TYPE determines the structure of CONTEXT_DATA:

- **SNAPSHOT**: Full workspace state at a point in time
- **CHECKPOINT**: Intermediate save during a session
- **HANDOFF**: Context transferred between agents during handoff
- **SUMMARY**: Condensed summary of session activity
- **RECOVERY**: Context used to restore a workspace after interruption

### WORKSPACE_TASKS Table

Links task plans to workspaces:

| Column | Type | Description |
|--------|------|-------------|
| WORKSPACE_ID | VARCHAR2(64) | FK to WORKSPACES |
| PLAN_ID | VARCHAR2(64) | FK to TASK_PLANS |
| ASSIGNED_AT | TIMESTAMP | When the task was linked |

Composite PK: `(WORKSPACE_ID, PLAN_ID)`.

### AGENT_SESSION New Columns

v3.4.0 adds three columns to AGENT_SESSION for workspace integration and session chaining:

| Column | Type | Description |
|--------|------|-------------|
| OWNER_USER_ID | VARCHAR2(64) | User who owns/started the session |
| WORKSPACE_ID | VARCHAR2(64) | Workspace the session belongs to |
| PREDECESSOR_SESSION_ID | VARCHAR2(64) | Previous session in the handoff chain |

`PREDECESSOR_SESSION_ID` creates a linked list of sessions — when an agent hands off to another agent, the new session points back to the predecessor. `get_session_chain()` traverses this chain backwards.

### ENTITIES.WORKSPACE_ID

New column `WORKSPACE_ID VARCHAR2(64)` on ENTITIES, nullable FK to WORKSPACES. When a workspace has `ISOLATION_MODE = 'ISOLATED'`, entities created within it are tagged with WORKSPACE_ID for scope isolation. In SHARED mode, WORKSPACE_ID is optional.

### JRD Views

v3.4.0 updates and adds JSON Relational Duality views:

| View | Mode | Description |
|------|------|-------------|
| WORKSPACE_DV | Updatable | Full workspace with nested context chain and tasks |
| CONTEXT_DV | Read-only | Context entries with workspace and agent details |
| MEMORY_DV | Updatable | Now updatable (was read/write in v2.1; confirmed updatable with JSON_TRANSFORM) |
| KNOWLEDGE_DV | Updatable | Now updatable (was read/write in v2.1; confirmed updatable with JSON_TRANSFORM) |

WORKSPACE_DV nests WORKSPACE_CONTEXT and WORKSPACE_TASKS as sub-documents, enabling atomic workspace updates via a single JSON document. CONTEXT_DV is read-only to prevent direct context manipulation — context changes go through `save_context()` to maintain the version chain integrity.

### JSON Strategy

v3.4.0 uses a layered JSON approach:

1. **Native JSON columns** for storage — `WORKSPACES.METADATA`, `WORKSPACE_CONTEXT.CONTEXT_DATA`, `AGENT_SESSION.CONTEXT` use Oracle's native JSON type for schemaless, queryable data
2. **JRD (JSON Relational Duality)** for document API — WORKSPACE_DV, CONTEXT_DV, MEMORY_DV, KNOWLEDGE_DV provide REST-friendly JSON document access over the relational schema
3. **JSON_TRANSFORM for partial updates** — Updatable JRD views use `JSON_TRANSFORM` under the hood for atomic partial JSON updates without full document replacement

This strategy balances: (a) relational integrity for FK constraints and partitioning, (b) document convenience for API consumers, and (c) partial update efficiency for large JSON payloads.

## Deep Data Security Architecture (Oracle Adapter)

### Direct Logon with Local End Users

Deep Sec uses Oracle's Direct Logon with Local End Users model for per-agent data isolation:

- Each agent gets a dedicated End User account
- End User name mapping: `UPPER(REPLACE(agent_id, '-', '_'))`
  - Example: `agent-001` → End User `AGENT_001`
- End Users connect directly to the database with filtered access via Data Grants

### Data Roles

Three Data Roles control access levels:

| Role | Purpose | Access Level |
|------|---------|--------------|
| `admin_data_role` | Full administrative access | All tables, no filtering |
| `agent_data_role` | Standard agent access | Filtered by workspace/agent context |
| `pool_agent_data_role` | Connection pool agents | Minimum required access |

### Data Grants (23 total)

Data Grants enforce row-level security with MAC (Mandatory Access Control), including `collab_member_own` (COLLAB_GROUP_MEMBERS) and `collab_group_member_access` (COLLAB_GROUPS) for collaboration group access:

| Table | Privilege | Predicate | Role |
|-------|-----------|-----------|------|
| AGENT_REGISTRY | SELECT | 1=1 | admin_data_role |
| AGENT_REGISTRY | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | SELECT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC' | agent_data_role |
| ENTITIES | INSERT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | UPDATE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | DELETE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_EDGES | SELECT | SOURCE_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| KNOWLEDGE_META | SELECT | ENTITY_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC') | agent_data_role |
| WORKSPACES | SELECT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACES | INSERT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACE_CONTEXT | SELECT | WORKSPACE_ID IN (SELECT WORKSPACE_ID FROM WORKSPACES WHERE OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID')) | agent_data_role |
| AGENT_SESSION | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| AGENT_SESSION | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_STEPS | SELECT | PLAN_ID IN (SELECT PLAN_ID FROM TASK_PLANS WHERE AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| ENTITY_ACCESS_LOG | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_ACCESS_LOG | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| SYSTEM_CONFIG | SELECT | 1=0 | agent_data_role |
| TAGS | SELECT | 1=1 | agent_data_role |

### MAC Enforcement

MAC (Mandatory Access Control) is enforced on 7 critical tables:

- ENTITIES
- ENTITY_EDGES
- KNOWLEDGE_META
- WORKSPACES
- WORKSPACE_CONTEXT
- AGENT_SESSION
- TASK_PLANS

MAC prevents bypass of Data Grant predicates even with direct DML.

### DEEP_SEC_SESSION_ROLE

End Users require `CREATE SESSION` to connect. This is granted via `DEEP_SEC_SESSION_ROLE`:

```sql
CREATE ROLE DEEP_SEC_SESSION_ROLE;
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO AIADMIN WITH ADMIN OPTION;
```

Data Roles grant `DEEP_SEC_SESSION_ROLE` to End Users, enabling them to create sessions.

### END_USER_MANAGER Package

The `END_USER_MANAGER` PL/SQL package manages the End User lifecycle:

- `create_end_user(agent_id)` — Creates End User with name `UPPER(REPLACE(agent_id, '-', '_'))`
- `get_end_user_name(agent_id)` — Returns mapped End User name
- `drop_end_user(agent_id)` — Drops End User
- `list_end_users()` — Lists all agent End Users
- `grant_data_role(end_user_name, role_name)` — Grants Data Role to End User
- `revoke_data_role(end_user_name, role_name)` — Revokes Data Role from End User

### Per-Request Context Switching

Each request sets the agent identity via `_set_context_from_session()`:

1. Application receives request with agent context
2. `_set_context_from_session()` sets `END_USER_CTX` namespace with AGENT_ID, USER_ID
3. Data Grant predicates reference `SYS_CONTEXT('END_USER_CTX', 'AGENT_ID')` for filtering
4. After request completes, context is cleared

### Dual Access Paths

| Path | User | Connection | Access |
|------|------|------------|--------|
| Portal | End User | Direct logon | Filtered by Data Grants |
| Admin | AIADMIN | Pool connection | Unrestricted (no Data Grants) |

Portal requests use End User connections with Data Grant filtering. Admin/management operations use the AIADMIN pool connection with unrestricted access.

Business/Portal requests remain on the End User connection for their complete
lifetime and fail closed if it is unavailable. Schema Owner access is confined
to separately authenticated Admin operations; Business requests never switch
to AIADMIN as a fallback.
