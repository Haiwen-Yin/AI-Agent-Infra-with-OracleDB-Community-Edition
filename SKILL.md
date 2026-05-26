---
name: oracle-memory-by-yhw
version: v2.3.1
author: Haiwen Yin
description: "Oracle AI Database Memory System v2.3.1 - 5-Signal Unified Hybrid Search + Fulltext Search + Search API, Spec Driven Development, Agent Elastic Management, Collaboration Groups, JRD Duality Views"
tags: [oracle, memory-system, knowledge-base, vector-search, hybrid-search, fulltext-search, search-api, oracledb, property-graph, multi-agent, partitioning, composite-pk, workspace, context-continuity, jrd, duality-view, spec-driven, elastic-agent, collaboration]
related_skills: [oracle-26ai, oracle-sqlcl-execution-methodology]
---

# Oracle AI Database Memory System v2.3.1

**Author:** Haiwen Yin
**Version:** v2.3.1 - 2026-05-26
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

## v2.3.1 Key Features: Embedding Fix, Unified Search, Fulltext Search & Search API

**Vector Search Fix** — Fix embedding generation and vector search capabilities omitted during v2.0.0 architecture rewrite

**5-Signal Unified Search** — vector + fulltext + relational + tag + graph multi-signal fusion `search_unified` API:

| Signal | Weight | Source | Scoring |
|--------|--------|--------|---------|
| Vector | 0.4 | ENTITY_EMBEDDINGS via VECTOR_DISTANCE(COSINE) | 1 - cosine_distance |
| Fulltext | 0.25 | Oracle Text CONTAINS(title) + SCORE(1) | ft_score / 100 |
| Relational | 0.2 | KNOWLEDGE_META(domain,topic) + SPEC_META(scope,complexity) + ENTITIES(category,importance) | Domain/scope match + importance |
| Tag | 0.15 (included in relational) | ENTITY_TAGS | Tag overlap + query match |
| Graph | 0.15 | ENTITY_EDGES BFS from seed entity | 1/depth proximity + edge_count/10 connectivity boost |

`search_unified(text, top_k, domain, category, tags, graph_seed_entity_id, ...)` returns `scores{vector,fulltext,relational,tag,graph}` + `final_score`.

**Single-SQL Fusion Search** — `search_unified_sql()` has the exact same 5-signal fusion as `search_unified`, but completes via a single CTE SQL statement, eliminating multi-round Python-SQL round trips:
- candidates CTE: vector+fulltext+metadata main query
- tag_scores CTE: tag overlap scoring (GROUP BY)
- edge_counts CTE: edge count (GROUP BY)
- graph_prox CTE: graph proximity (UNION ALL depth=1+2)
- Final SELECT: weighted scoring + ORDER BY final_score DESC

**LLM Context Economics** — Multi-round tool calls during retrieval are a hidden cost for LLM agents: each call's request/response consumes tokens, intermediate step noise pollutes the context window, and cumulative overhead may squeeze reasoning space or cause context overflow. Single-SQL fusion search compresses 5 Python-SQL round trips into 1 database call, reduces tool-call token overhead by 60-80%, eliminates intermediate-step context pollution, and lets agents reserve token budget for reasoning and decision-making.

**Fulltext Search** — `search_fulltext()` uses Oracle Text CONTAINS + SCORE for fulltext relevance search

**Embedding Fix** — EMBEDDING_MANAGER PL/SQL SUBSTR strips double brackets + named binds fix for ORA-01722 + search_similar/search_hybrid/search_multi_type/search_by_entity_id

In-db embedding generation and vector search capabilities were omitted during the v2.0.0 architecture rewrite. v2.3.1 fixes and enhances:

| Feature | Description |
|---------|-------------|
| EMBEDDING_MANAGER PL/SQL | `generate_and_store` fix: SUBSTR strips double brackets + VECTOR variable assignment; `cosine_similarity`/`batch_embed_entities`/`get_stats` |
| embedding_api.py named binds | All `:1,:2,:3` changed to `:eid,:etype,:vec` etc., resolving oracledb thin mode ORA-01722 |
| search_by_entity_id() | Search similar entities based on existing entity vector, auto-exclude self |
| search_hybrid() | Vector+keyword hybrid search, adjustable weights, returns 3D scoring (vector/keyword/hybrid) |
| search_multi_type() | Cross-type vector search (MEMORY/KNOWLEDGE/SPEC), returned grouped by type |
| EMBEDDING_GENERATION_JOB | Auto-generates embeddings for MEMORY/KNOWLEDGE entities every 2 hours |
| search_fulltext() | Oracle Text CONTAINS + SCORE fulltext search, supports boolean/fuzzy/stem |
| search_unified() | 5-Signal Unified Search, adjustable weights, returns per-signal independent score + final score |
| search_api.py | Unified search entry point, 10 strategies (vector/fulltext/keyword/graph/hybrid/unified/unified_sql/relational/multi_type/auto), automatic strategy detection |
| 19 embedding tests | Covering generation, storage, retrieval, similarity search, hybrid search, cross-type, batch processing, dimension detection |
| 31 unified search tests | Covering 5-signal independent verification, domain/category/tags filtering, graph proximity, custom weights, Single-SQL fusion search |
| 42 search API tests | Covering strategy metadata, auto-detection, per-strategy invocation, result structure, unified_sql strategy |

## v2.3.0 Key Additions: SDD, Elastic Agents, Collaboration

| Feature | Description |
|---------|-------------|
| Spec Driven Development | SPEC_META (reference-partitioned), SPEC_PLAN_LINKS (many-to-many with LINK_TYPE), SPEC_DV (JRD updatable) |
| Agent Elastic Management | DORMANT (hibernate, preserve context) / POOL (stateless, skills_tags matching), AGENT_CREDENTIALS (encrypted, auto-expiry) |
| Collaboration Groups | COLLAB_GROUPS + COLLAB_GROUP_MEMBERS, shared Workspace (COLLAB_GROUP) + personal Workspace (PERSONAL_IN_GROUP) |
| Agent Credentials | ReversibleEncryption, SCOPE={access_level, restricted_domains, max_clearance}, auto-revocation on DORMANT |
| Scheduler Jobs | DORMANT_AGENT_JOB (30-min timeout), CREDENTIAL_CLEANUP_JOB (daily purge) |
| Visualization | Specs + Collab pages, /api/specs + /api/collab, inline detail expansion (Tasks pattern), bilingual sidebar |
| Auth Security | SHA256 password hash verification (was prefix-only), admin default password: admin123 |

## v2.2.0 Key Additions: Workspace & Context Continuity

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
| ENTITIES | LIST by ENTITY_TYPE (7 partitions: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE, SPEC, OTHER) |
| ENTITY_EDGES | REFERENCE from ENTITIES |
| KNOWLEDGE_META | REFERENCE from ENTITIES |
| ENTITY_EMBEDDINGS | REFERENCE from ENTITIES |
| SPEC_META | REFERENCE from ENTITIES [NEW v2.3.0] |
| HARNESS_META | REFERENCE from ENTITIES |
| ENTITY_TAGS | REFERENCE from ENTITIES |
| TASK_PLANS | RANGE by STATUS |
| TASK_STEPS | REFERENCE from TASK_PLANS |
| AGENT_SESSION | RANGE by IS_ACTIVE |
| AGENT_ACCESS_LOG | RANGE by CREATED_AT (monthly) |

**Note:** 6 reference-partitioned children (ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, SPEC_META, HARNESS_META, ENTITY_TAGS). Non-partitioned tables: AGENT_REGISTRY, AGENT_CREDENTIALS, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, COLLAB_GROUPS, COLLAB_GROUP_MEMBERS, SPEC_PLAN_LINKS, SYSTEM_USERS, SYSTEM_CONFIG, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS.

## Composite Primary Keys

| Table | Composite PK | Notes |
|-------|-------------|-------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | Unified table; ENTITY_TYPE is partition key |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | SOURCE_ID is part of PK for reference partitioning |
| TASK_PLANS | (PLAN_ID, STATUS) | STATUS is partition key; included in PK |
| TASK_STEPS | (STEP_ID, PLAN_ID, PLAN_STATUS) | Composite PK includes parent PK columns for reference partitioning |
| AGENT_SESSION | (SESSION_ID, IS_ACTIVE) | IS_ACTIVE is partition key; included in PK |
| WORKSPACE_TASKS | (WORKSPACE_ID, PLAN_ID) | Junction table; FK to both WORKSPACES and TASK_PLANS |

**Note:** Global unique constraints (UK_ENTITY_ID, UK_EDGE_ID, etc.) enforce uniqueness across partitions. ON DELETE CASCADE on all child tables (required for JRD updatable views).

## JRD Duality Views (6 Views)

| View | Mode | Root Table | Nested Objects |
|------|------|------------|----------------|
| WORKSPACE_DV | updatable | WORKSPACES | WORKSPACE_TASKS (via FK) |
| CONTEXT_DV | read-only | WORKSPACE_CONTEXT | -- (flat view) |
| MEMORY_DV | updatable | ENTITIES (ENTITY_TYPE=MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | updatable | ENTITIES (ENTITY_TYPE=KNOWLEDGE) | ENTITY_TAGS, ENTITY_EDGES |
| SPEC_DV | updatable | ENTITIES (ENTITY_TYPE=SPEC) [NEW v2.3.0] | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV | updatable | COLLAB_GROUPS [NEW v2.3.0] | COLLAB_GROUP_MEMBERS |

**Notes:**
- 26ai annotations (`@insert`, `@update`, `@delete`) required on columns for write operations
- JRD does not support JOINs in nested subqueries; use FK-based nesting only
- WORKSPACE_CONTEXT is excluded from WORKSPACE_DV because it is append-only (use raw SQL)
- JRD views must include all PK columns of root table
- CONTEXT_DV is read-only (no 26ai write annotations)

## Quick Start

### Deploy Schema (3 Phases)

```sql
-- Phase 1: Schema (27 tables, 6 JRD views, indexes, property graph, seed data)
@scripts/deploy/1_schema.sql

-- Phase 2: PL/SQL Packages (8 packages: MEMORY_FUSION_ENGINE, KNOWLEDGE_BASE_API, AGENT_PERMISSION_MANAGER, SESSION_CLEANUP, WORKSPACE_MANAGER, SPEC_MANAGER, COLLAB_GROUP_MANAGER, EMBEDDING_MANAGER)
@scripts/deploy/2_api.sql

-- Phase 3: Scheduler Jobs (12 jobs including DORMANT_AGENT_JOB, CREDENTIAL_CLEANUP_JOB, EMBEDDING_GENERATION_JOB)
@scripts/deploy/3_jobs.sql
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
oracle-memory-by-yhw/
  scripts/
    deploy/
      1_schema.sql              # 27 tables, 6 JRD views, indexes, property graph, seed data
      2_api.sql                 # 8 PL/SQL packages (MEMORY_FUSION_ENGINE, KNOWLEDGE_BASE_API, AGENT_PERMISSION_MANAGER, SESSION_CLEANUP, WORKSPACE_MANAGER, SPEC_MANAGER, COLLAB_GROUP_MANAGER, EMBEDDING_MANAGER)
      3_jobs.sql                # 12 scheduler jobs
      4_harness_templates.sql   # HARNESS_META + 5 built-in harness templates
    lib/
      config.py                 # Unified Config dataclass with env var overrides
      connection.py             # oracledb connection pool + Decimal sanitization helpers
      memory_api.py             # Memory CRUD on ENTITIES, workspace_id support
      knowledge_api.py          # Knowledge CRUD + graph + edges, workspace_id support
      agent_api.py              # Agent registration, sessions, handoff, collaboration, credentials, hibernate/wake, pool
      task_plan_api.py          # Task plans, steps, snapshots, tool calls, dependencies
      security.py              # DataMaskingService, ReversibleEncryption, password hashing
      harness_api.py            # Harness template CRUD, instantiate, derive, validate
      graph_api.py              # Property Graph API with GRAPH_TABLE SQL operator (9 functions)
      workspace_api.py          # Workspace lifecycle, context chains, handoff, recovery (11 functions)
      spec_api.py              # Spec CRUD, plan linkage, validation, derivation (10 functions) [NEW v2.3.0]
      collab_api.py             # Collaboration groups, members, shared memory (10 functions) [NEW v2.3.0]
      embedding_api.py          # Vector embedding generation, storage, search (15 functions) [NEW v2.3.1]
      search_api.py             # Unified search entry point, 10 strategies with auto-detection (3 functions) [NEW v2.3.1]
    tests/
      test_connection.py        # Connection pool tests (6)
      test_memory.py            # Memory CRUD tests (8)
      test_knowledge.py         # Knowledge CRUD tests (8)
      test_agent.py             # Agent registration/session tests (8)
      test_security.py          # Security feature tests (5)
      test_harness.py           # Harness template tests (6)
      test_graph.py             # Property Graph tests (8)
      test_workspace.py         # Workspace & context tests (12)
      test_spec.py              # Spec CRUD + plan linkage tests (9) [NEW v2.3.0]
      test_collab.py            # Collab group + shared memory tests (12) [NEW v2.3.0]
      test_credential.py        # Credential + hibernate/wake/pool tests (9) [NEW v2.3.0]
      test_embedding.py         # Embedding generation, search, hybrid, multi-type tests (19) [NEW v2.3.1]
      test_unified_search.py     # 5-signal unified hybrid search tests (20) [NEW v2.3.1]
      test_search_api.py          # Search API strategy tests (42) [NEW v2.3.1]
      test_all.py               # Master runner (14 suites, 183 total)
    visualization/
      server.py                 # HTTP server (session auth, page routing, JSON API, bilingual)
      templates/
        login.html              # Card-style login page
        knowledge.html          # Knowledge: list/graph dual view + inline detail
        memory.html             # Memory: list/graph dual view + inline detail + category filter
        agents.html             # Agents: Bootstrap tabs (registry/sessions/collabs)
        tasks.html              # Tasks: Accordion with step details + tool I/O
        workspaces.html         # Workspaces: expandable detail rows + context timeline
        graph.html              # Graph Explorer: stats + search + vis-network + detail panel
        specs.html              # Specs: list/detail tabs + plan linkage [NEW v2.3.0]
        collab.html             # Collab: groups/members/shared memory [NEW v2.3.0]
      static/
        style.css               # Dark theme CSS variables + sidebar styles
        vis-network.min.js      # Vis.js network visualization library
```

## Database Schema (27 Tables)

### Core Tables (7)

| Table | Purpose | Partitioning |
|-------|---------|-------------|
| ENTITIES | Unified entity store (MEMORY,KNOWLEDGE,TASK_OUTPUT,EXPERIENCE,HARNESS_TEMPLATE,SPEC,OTHER) | LIST by ENTITY_TYPE |
| ENTITY_EDGES | Directed relationships between entities | REFERENCE from ENTITIES |
| KNOWLEDGE_META | Knowledge metadata (domain,topic,difficulty) | REFERENCE from ENTITIES |
| ENTITY_EMBEDDINGS | Vector embeddings for semantic search | REFERENCE from ENTITIES |
| SPEC_META | Specification metadata (version,status,acceptance_criteria,constraints) [NEW v2.3.0] | REFERENCE from ENTITIES |
| HARNESS_META | Harness template metadata | REFERENCE from ENTITIES |
| ENTITY_TAGS | Tags for categorization and filtering | REFERENCE from ENTITIES |

### System Tables (3)

| Table | Purpose |
|-------|---------|
| SYSTEM_USERS | User accounts with SHA256 password hashes |
| SYSTEM_CONFIG | Key-value configuration store |
| TAGS | Tag definitions |

### Agent Tables (5)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| AGENT_REGISTRY | Agent definitions + elastic management | +5 cols: CREATED_BY_AGENT_ID, AGENT_ROLE, CURRENT_USER_ID, POOL_CONFIG, LAST_ACTIVE_AT |
| AGENT_CREDENTIALS | Encrypted credential storage [NEW v2.3.0] | CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE, CREDENTIAL_VALUE (encrypted), SCOPE (JSON), EXPIRES_AT |
| AGENT_SESSION | Session with handoff chain | SESSION_ID, AGENT_ID, CONTEXT (JSON), LAST_ACTIVE_AT [NEW v2.3.0] |
| ENTITY_ACCESS_LOG | Audit trail of entity access | LOG_ID, SESSION_ID, ACTION_TYPE, RESOURCE_TYPE, RESOURCE_ID |
| AGENT_PERMISSION_LOG | Agent action audit trail | LOG_ID, AGENT_ID, ACTION, STATUS_CODE, DETAILS |

### Collaboration Tables (2)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| AGENT_COLLABORATION | Inter-agent collaboration records | COL_ID, SOURCE_AGENT_ID, TARGET_AGENT_ID, COL_TYPE, ENTITY_ID, CONTEXT |
| COLLAB_GROUPS | Collaboration group definitions [NEW v2.3.0] | GROUP_ID, GROUP_NAME, GROUP_TYPE, WORKSPACE_ID, SHARING_POLICY, STATUS |
| COLLAB_GROUP_MEMBERS | Group membership [NEW v2.3.0] | MEMBER_ID, GROUP_ID, AGENT_ID, ROLE, PERSONAL_WORKSPACE_ID |

### Workspace Tables (3)

| Table | Purpose |
|-------|---------|
| WORKSPACES | Isolated environments (CONVERSATION,PROJECT,TASK_CHAIN,AUTONOMOUS,COLLAB_GROUP,PERSONAL_IN_GROUP) |
| WORKSPACE_CONTEXT | Append-only context chain (CHECKPOINT,HANDOFF,SUMMARY,ERROR_STATE,AUTO_SAVE) |
| WORKSPACE_TASKS | Junction: workspaces ↔ task plans |

### Task Tables (5)

| Table | Purpose |
|-------|---------|
| TASK_PLANS | Plan definitions |
| TASK_STEPS | Plan steps (composite PK: STEP_ID, PLAN_ID, PLAN_STATUS) |
| TASK_CONTEXT_SNAPSHOTS | Step execution context |
| TASK_TOOL_CALLS | Tool invocation records |
| TASK_DEPENDENCIES | Step dependency graph |

### Spec Tables (1)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| SPEC_PLAN_LINKS | Spec↔Plan many-to-many [NEW v2.3.0] | SPEC_ID, PLAN_ID, LINK_TYPE (DRIVES/VALIDATES/CONSTRAINS/EXTENDS), LINK_STRENGTH, UK=(SPEC_ID,PLAN_ID,LINK_TYPE) |

## PL/SQL Packages (8 Packages)

| Package | Function Count | Key Functions |
|---------|---------------|---------------|
| MEMORY_FUSION_ENGINE | 7 | fuse_similar_memories, decay_memories, reinforce_memory, search_memories, get_memory_stats, consolidate_memories, archive_old_memories |
| KNOWLEDGE_BASE_API | 5 | validate_knowledge, link_knowledge, get_knowledge_graph, find_contradictions, resolve_contradiction |
| AGENT_PERMISSION_MANAGER | 5 | check_permission, grant_permission, revoke_permission, get_agent_permissions, audit_permissions |
| SESSION_CLEANUP | 4 | cleanup_expired_sessions, cleanup_orphaned_entities, vacuum_embeddings, purge_audit_log |
| WORKSPACE_MANAGER | 10 | create_workspace, get_workspace, update_workspace, save_context, get_context_chain, get_latest_context, create_handoff_session, recover_workspace, link_task_to_workspace, cleanup_workspace |
| SPEC_MANAGER [NEW v2.3.0] | 8 | create_spec, get_spec, update_spec, validate_spec, derive_spec, create_plan_from_spec, link_spec_to_plan, get_spec_plan_links |
| COLLAB_GROUP_MANAGER [NEW v2.3.0] | 6 | create_group, get_group, update_group, add_member, remove_member, get_group_members |
| EMBEDDING_MANAGER [NEW v2.3.1] | 5 | generate_embedding, generate_and_store, cosine_similarity, batch_embed_entities, get_stats |

## Python API (15 Modules, 131+ Functions)

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
def add_edge(source_id: str, source_type: str, target_id: str, edge_type: str, strength: float = 1.0) -> str
def get_edges(entity_id: str, entity_type: str, direction: str = "outgoing") -> list[dict]
```

### agent_api.py

```python
# Original functions
def register_agent(agent_name: str, agent_type: str, capabilities: dict) -> str
def get_agent(agent_id: str) -> dict | None
def create_session(agent_id: str, owner_user_id: str = None, workspace_id: str = None, predecessor_session_id: str = None) -> str
def end_session(session_id: str) -> bool
def get_active_sessions(workspace_id: str = None) -> list[dict]
def log_access(session_id: str, action_type: str, resource_type: str, resource_id: str) -> str
def request_collaboration(session_id: str, target_agent_id: str, message: str) -> str
def checkpoint_session(session_id: str, checkpoint_data: dict) -> bool
def get_session_chain(session_id: str) -> list[dict]
# NEW v2.3.0
def issue_credential(agent_id: str, user_id: str, cred_type: str, scope: dict, expires_hours: int = 24) -> str
def verify_credential(credential_id: str) -> dict | None
def get_credentials_for_user(user_id: str) -> list[dict]
def revoke_credential(credential_id: str) -> bool
def hibernate_agent(agent_id: str) -> bool
def wake_agent(agent_id: str) -> bool
def register_pool_agent(agent_name: str, capabilities: dict, skills_tags: list[str]) -> str
def assign_pool_agent(user_id: str, required_skills: list[str]) -> str | None
```

### task_plan_api.py

```python
def create_plan(title: str, description: str, owner_agent_id: str) -> str
def get_plan(plan_id: str, status: str = "ACTIVE") -> dict | None
def update_plan_status(plan_id: str, status: str) -> bool
def add_step(plan_id: str, step_type: str, step_data: dict, step_order: int = None, plan_status: str = "ACTIVE") -> str
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

### spec_api.py [NEW v2.3.0]

```python
def create_spec(entity_data: dict, spec_meta: dict, workspace_id: str = None) -> str
def get_spec(spec_id: str) -> dict | None
def update_spec(spec_id: str, entity_data: dict = None, spec_meta: dict = None) -> bool
def list_specs(status: str = None, workspace_id: str = None) -> list[dict]
def create_plan_from_spec(spec_id: str, plan_title: str, plan_description: str) -> str
def link_spec_to_plan(spec_id: str, plan_id: str, link_type: str = "DRIVES", strength: float = 1.0) -> str
def get_spec_plan_links(spec_id: str) -> list[dict]
def validate_plan_against_spec(spec_id: str, plan_id: str) -> dict
def derive_spec(parent_spec_id: str, entity_data: dict, spec_meta: dict) -> str
def delete_spec(spec_id: str) -> bool
```

### collab_api.py [NEW v2.3.0]

```python
def create_collab_group(group_name: str, group_type: str, sharing_policy: str = "OPEN", created_by: str = None) -> str
def get_collab_group(group_id: str) -> dict | None
def update_collab_group(group_id: str, **kwargs) -> bool
def add_group_member(group_id: str, agent_id: str, role: str = "CONTRIBUTOR") -> str
def remove_group_member(group_id: str, agent_id: str) -> bool
def list_group_members(group_id: str) -> list[dict]
def get_agent_groups(agent_id: str) -> list[dict]
def share_memory_to_group(group_id: str, memory_id: str, shared_by: str) -> str
def get_group_shared_memories(group_id: str) -> list[dict]
def delete_collab_group(group_id: str) -> bool
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

### embedding_api.py [NEW v2.3.1]

```python
def generate_embedding(text: str, api_url: str = None, model: str = None, timeout: int = 30) -> list[float]
def store_embedding(entity_id: str, entity_type: str, text: str, api_url: str = None, model: str = None) -> bool
def store_embedding_vector(entity_id: str, entity_type: str, embedding: list[float], model: str = None) -> bool
def get_embedding(entity_id: str, entity_type: str = "MEMORY") -> dict | None
def delete_embedding(entity_id: str, entity_type: str = "MEMORY") -> bool
def search_similar(text: str, top_k: int = 10, entity_type: str = None, workspace_id: str = None, api_url: str = None, model: str = None) -> list[dict]
def search_by_entity_id(entity_id: str, entity_type: str = "MEMORY", top_k: int = 10, workspace_id: str = None) -> list[dict]
def search_hybrid(text: str, keyword: str = None, top_k: int = 10, entity_type: str = None, workspace_id: str = None, vector_weight: float = 0.7, api_url: str = None, model: str = None) -> list[dict]
def search_multi_type(text: str, entity_types: list[str] = None, top_k: int = 10, workspace_id: str = None, api_url: str = None, model: str = None) -> dict[str, list[dict]]
def search_unified(text: str, top_k: int = 20, entity_type: str = None, workspace_id: str = None, domain: str = None, category: str = None, tags: list[str] = None, graph_seed_entity_id: str = None, graph_seed_entity_type: str = None, graph_depth: int = 2, vector_weight: float = 0.4, fulltext_weight: float = 0.25, relational_weight: float = 0.2, graph_weight: float = 0.15, api_url: str = None, model: str = None) -> list[dict]
def search_unified_sql(text: str, top_k: int = 20, entity_type: str = None, workspace_id: str = None, domain: str = None, category: str = None, tags: list[str] = None, graph_seed_entity_id: str = None, graph_seed_entity_type: str = None, graph_depth: int = 2, vector_weight: float = 0.4, fulltext_weight: float = 0.25, relational_weight: float = 0.2, graph_weight: float = 0.15, api_url: str = None, model: str = None) -> list[dict]
def search_fulltext(query: str, top_k: int = 20, entity_type: str = None, category: str = None, workspace_id: str = None) -> list[dict]
def generate_embeddings_batch(entity_type: str = "MEMORY", limit: int = 100, api_url: str = None, model: str = None) -> dict
def get_embedding_stats() -> dict
def get_model_dimension(model: str = None) -> int
```

### search_api.py [NEW v2.3.1]

Unified search entry point for AI agents. 10 strategies with auto-detection:

```python
def search(text: str, strategy: str = "auto", top_k: int = 10, entity_type: str = None,
           workspace_id: str = None, domain: str = None, category: str = None,
           tags: list[str] = None, graph_seed_entity_id: str = None,
           entity_id: str = None, entity_types: list[str] = None,
           min_importance: int = None, vector_weight: float = None,
           fulltext_weight: float = None, relational_weight: float = None,
           graph_weight: float = None, **kwargs) -> dict
def list_search_strategies() -> list[dict]
def describe_search_strategy(strategy: str) -> dict | None
```

| Strategy | Signals | Best For | Requires Embedding |
|----------|---------|----------|-------------------|
| vector | vector | Semantic/concept search | Yes |
| fulltext | fulltext | Exact keyword/boolean/fuzzy | No |
| keyword | keyword | Wildcard/LIKE patterns | No |
| graph | graph | Relationship/neighborhood | No |
| hybrid | vector+fulltext | Semantic+lexical balanced | Yes |
| unified | vector+fulltext+relational+tag+graph | Comprehensive multi-dimensional | Yes |
| unified_sql | vector+fulltext+relational+tag+graph | Single-SQL CTE fusion (low-latency) | Yes |
| relational | relational | Domain/category/importance filter | No |
| multi_type | vector+multi_type | Cross-type (MEMORY/KNOWLEDGE/SPEC) | Yes |
| auto | auto-detected | Unknown query type / convenience | Varies |

Auto-detection rules: boolean operators (AND/OR/NOT) → fulltext; `$`/`~` → fulltext; `%`/`_` → keyword; domain/tags kwargs → unified; graph_seed_entity_id → unified; ≤2 words → fulltext; ≥5 words → unified; else → hybrid.

## Scheduler Jobs (12 Jobs)

| Job | Schedule | Description |
|-----|----------|-------------|
| MEMORY_FUSION_JOB | Daily 03:00 | Fuses similar memories, decays importance scores, archives below threshold |
| MEMORY_FUSION_CYCLE | Daily 04:00 | Runs full fusion cycle (decay + consolidate + archive) |
| MEMORY_FUSION_STATS | Daily 05:00 | Computes and logs memory fusion statistics |
| SESSION_CLEANUP_JOB | Hourly | Ends stale active sessions past timeout threshold |
| SESSION_EXPIRY_NOTIFICATION | Hourly | Notifies agents of upcoming session expiry |
| KNOWLEDGE_EXTRACTION_JOB | Daily 06:00 | Extracts knowledge from high-importance memories |
| KNOWLEDGE_GRAPH_MAINTENANCE | Weekly Sunday 01:00 | Rebuilds knowledge graph edges and consistency checks |
| WORKSPACE_CLEANUP_JOB | Daily 04:00 | Archives completed workspaces and their context chains |
| STALE_WORKSPACE_DETECT_JOB | Every 30 min | Detects workspaces with no active sessions for N hours |
| DORMANT_AGENT_JOB [NEW v2.3.0] | Every 30 min | Auto-hibernates agents inactive beyond dormant_timeout_min |
| CREDENTIAL_CLEANUP_JOB [NEW v2.3.0] | Daily 02:00 | Purges expired and revoked credentials |
| EMBEDDING_GENERATION_JOB [NEW v2.3.1] | Every 2 hours | Auto-generates embeddings for new MEMORY/KNOWLEDGE entities |

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
- **Named bind variables** (`:uid`, `:aid`) cause ORA-01745 on tables with JSON columns; use positional (`:1`,`:2`) or short names (`:b1`,`:b2`)
- **CONSTRAINTS reserved word**: Oracle reserved; must use double-quote `"CONSTRAINTS"` in all SQL references
- **PL/SQL JSON_OBJECT**: VALUE clause does not support `FORMAT JSON` in 23ai/26ai; use `RETURN VARCHAR2` instead of `RETURN JSON`
- **Reference-partitioned tables**: Cannot DISABLE constraints (ORA-14650); constraints always enforced
- **JSON_QUERY WITH WRAPPER on arrays**: Returns `[array]` (double-bracketed); must `SUBSTR(l_vec, 2, DBMS_LOB.GETLENGTH(l_vec)-2)` before `TO_VECTOR()`
- **TO_VECTOR format**: Requires `[v1,v2,...]` bracketed format; plain comma-separated `v1,v2,...` triggers ORA-51804
- **Named bind variables with execute_query**: Must use dict `{"eid": "X"}` with named binds `:eid`, NOT list `["X"]` with positional `:1`; oracledb thin mode interprets dict + `:1` as named bind "1" causing ORA-01722
- **EMBEDDING_MANAGER.generate_and_store**: Only works from anonymous PL/SQL block (not SELECT function call) due to UTL_HTTP context; also requires ENTITIES row to exist first (FK constraint)

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
- **Spec storage**: ENTITIES subtype `SPEC`, reuses unified storage+partitioning+JRD; SPEC_META reference-partitioned like HARNESS_META
- **Spec↔Plan**: Many-to-many via SPEC_PLAN_LINKS; LINK_TYPE: DRIVES/VALIDATES/CONSTRAINS/EXTENDS
- **Agent states**: ACTIVE/INACTIVE/SUSPENDED/DECOMMISSIONED/DORMANT/POOL; DORMANT preserves identity, POOL is stateless
- **POOL Agent**: Stateless — context follows user via credentials; matching by skills_tags intersection
- **Collaboration Groups**: Mode C — group-level shared Workspace + optional personal Workspace per member; LEAD/CONTRIBUTOR get personal WS, OBSERVER does not
- **SYSTEM_USERS precedes AGENT_REGISTRY** in DDL (FK dependency)
- **SHA256 password prefix**: `SHA256:` is 7 chars; use `stored_hash[7:]` for comparison

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
