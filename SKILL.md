---
name: oracle-memory-by-yhw
version: v2.1.0
author: Haiwen Yin
description: Oracle AI Database Memory System v2.1.0 - Table partitioning, composite PKs, reference partitioning, Property Graph API, oracledb driver, 4-phase SQL deployment
tags: [oracle, memory-system, knowledge-base, vector-search, oracledb, property-graph, multi-agent, partitioning, composite-pk]
related_skills: [oracle-26ai, oracle-sqlcl-execution-methodology]
---

# Oracle AI Database Memory System v2.1.0

**Author**: Haiwen Yin
**Version**: v2.1.0 - 2026-05-19
**License**: Apache License 2.0

---

## Architecture Overview

```
ENTITIES (unified, partitioned) ──┬── MEMORY (replaces MEMORIES + MEMORY_NODES)
                                  ├── KNOWLEDGE (replaces KNOWLEDGE_CONCEPTS)
                                  ├── TASK_OUTPUT
                                  ├── EXPERIENCE
                                  └── HARNESS_TEMPLATE (reusable agent execution blueprints)

ENTITY_EDGES (unified, reference-partitioned) ── replaces MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH

KNOWLEDGE_META ── extended metadata for KNOWLEDGE entities (reference-partitioned)
HARNESS_META ── versioning, status, variables for HARNESS_TEMPLATE entities (reference-partitioned)
ENTITY_EMBEDDINGS ── VECTOR(1024, FLOAT32) for semantic search (reference-partitioned)
ENTITY_TAGS ── normalized tag associations (reference-partitioned)
```

### Partitioning Scheme

| Table | Strategy | Details |
|-------|----------|---------|
| ENTITIES | LIST(ENTITY_TYPE) + RANGE(CREATED_AT) | 6 list × 7 time subpartitions |
| ENTITY_EDGES | REFERENCE | Inherits from ENTITIES |
| KNOWLEDGE_META | REFERENCE | Inherits from ENTITIES |
| HARNESS_META | REFERENCE | Inherits from ENTITIES |
| ENTITY_EMBEDDINGS | REFERENCE | Inherits from ENTITIES |
| ENTITY_TAGS | REFERENCE | Inherits from ENTITIES |
| AGENT_SESSION | LIST(IS_ACTIVE) + RANGE(START_TIME) | ROW MOVEMENT enabled |
| ENTITY_ACCESS_LOG | RANGE(ACCESS_TIME) + HASH(AGENT_ID) | 4 hash buckets |
| TASK_PLANS | LIST(STATUS) + RANGE(CREATED_AT) | Composite PK(PLAN_ID, STATUS) |
| TASK_STEPS | REFERENCE | Inherits from TASK_PLANS |

- **5 reference-partitioned child tables** inherit partitioning from ENTITIES automatically
- **9 non-partitioned tables**: AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS, SYSTEM_CONFIG, SYSTEM_USERS

### Composite Primary Keys

| Table | Primary Key | Rationale |
|-------|-------------|-----------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | Partition key inclusion |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | Reference partitioning key |
| TASK_PLANS | (PLAN_ID, STATUS) | Partition key inclusion |

- **Global unique constraints** enforce single-column uniqueness for FK references (e.g., ENTITY_ID globally unique despite composite PK)

## Quick Start

### 1. Deploy Schema (4 phases)
```bash
# Phase 1: Tables, indexes, graph, duality views
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/1_schema.sql

# Phase 2: PL/SQL API packages
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/2_api.sql

# Phase 3: Scheduler jobs
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/3_jobs.sql

# Phase 4: Harness templates (HARNESS_META table + 5 built-in templates)
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/4_harness_templates.sql
```

### 2. Install Python Dependencies
```bash
pip install oracledb
```

### 3. Configure
Edit `config.json` or set environment variables:
- `MEMORY_DB_USER`, `MEMORY_DB_PASSWORD`, `MEMORY_DB_DSN`
- `MEMORY_EMBEDDING_API`, `MEMORY_SERVER_PORT`

### 4. Run Tests
```bash
cd scripts && python -m tests.test_all
```

### 5. Start Web Server
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
    1_schema.sql    # Tables, indexes, property graph, duality views (19 tables, 32 indexes)
    2_api.sql       # PL/SQL packages (fusion, knowledge, permissions, cleanup)
    3_jobs.sql      # Scheduler jobs (8 automated jobs)
    4_harness_templates.sql  # HARNESS_META + 5 built-in harness templates
  lib/
    config.py       # Unified Config dataclass with env var overrides
    connection.py   # oracledb connection pool (no SQLcl subprocess)
    memory_api.py   # Memory CRUD on ENTITIES (ENTITY_TYPE='MEMORY')
    knowledge_api.py # Knowledge CRUD + graph on ENTITIES+KNOWLEDGE_META+ENTITY_EDGES
    agent_api.py    # Agent registration, sessions, collaboration, access log
    task_plan_api.py # Task plans, steps, snapshots, tool calls, dependencies
    security.py     # DataMaskingService, ReversibleEncryption, password hashing
    harness_api.py  # Harness template CRUD, instantiate, derive, validate
    graph_api.py    # Property Graph API with GRAPH_TABLE SQL operator (9 functions)
  tests/
    test_connection.py
    test_memory.py
    test_knowledge.py
    test_agent.py
    test_security.py
    test_harness.py
    test_graph.py
    test_all.py
docs/
  architecture.md   # Detailed architecture and design decisions
  api-reference.md  # Python and PL/SQL API documentation
  deployment.md     # Deployment guide and troubleshooting
  migration.md      # v1.x → v2.1 migration guide
  security.md       # Security features and configuration
  visualization.md  # Web visualization server guide
  harness.md        # Harness template system guide
config.json         # Database, server, embedding, security config
viz_server_local_js.py  # Web visualization (updated for v2.1 schema)
```

## Key Tables (19 total)

| Table | Partitioned | Purpose |
|-------|-------------|---------|
| ENTITIES | LIST+RANGE | Unified store: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE |
| ENTITY_EDGES | REFERENCE | Unified directed edges with strength/confidence |
| KNOWLEDGE_META | REFERENCE | Source type, validation, versioning, confidence |
| HARNESS_META | REFERENCE | Harness template versioning, status, variables, changelog |
| ENTITY_EMBEDDINGS | REFERENCE | VECTOR(1024, FLOAT32) embeddings |
| ENTITY_TAGS | REFERENCE | Normalized tag associations |
| AGENT_SESSION | LIST+RANGE | Session tracking with context snapshots, ROW MOVEMENT |
| ENTITY_ACCESS_LOG | RANGE+HASH | Audit trail for all entity access |
| TASK_PLANS | LIST+RANGE | Multi-step task definitions |
| TASK_STEPS | REFERENCE | Plan steps with status tracking |
| AGENT_REGISTRY | No | Agent identity, capabilities, permissions |
| AGENT_PERMISSION_LOG | No | Permission change audit |
| AGENT_COLLABORATION | No | Cross-agent sharing requests |
| TASK_CONTEXT_SNAPSHOTS | No | Breakpoint/recovery snapshots |
| TASK_TOOL_CALLS | No | Tool invocation audit |
| TASK_DEPENDENCIES | No | Inter-plan dependency graph |
| TAGS | No | Normalized tag definitions |
| SYSTEM_CONFIG | No | System configuration key-value |
| SYSTEM_USERS | No | User accounts with roles |

## PL/SQL Packages

| Package | Purpose |
|---------|---------|
| MEMORY_FUSION_ENGINE | Merge similar memories, extract knowledge, decay priorities |
| KNOWLEDGE_BASE_API | Validate, deprecate, version concepts, lineage queries |
| AGENT_PERMISSION_MANAGER | Access control, session cleanup, collaboration processing |
| SESSION_CLEANUP | Purge logs, archive entities, update tag counts |

## Scheduler Jobs (8)

| Job | Schedule | Action |
|-----|----------|--------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + decay priorities |
| KNOWLEDGE_EXTRACTION_JOB | Daily 03:00 | Extract knowledge from memory patterns |
| KNOWLEDGE_REVIEW_JOB | Daily 04:00 | Review and validate knowledge concepts |
| SESSION_CLEANUP_JOB | Every 30 min | Cleanup expired sessions |
| ACCESS_LOG_PURGE_JOB | Weekly Sun 04:00 | Purge logs >90 days |
| TAG_COUNT_UPDATE_JOB | Daily 01:00 | Update tag usage counts |
| COLLAB_EXPIRY_JOB | Daily 00:30 | Expire stale collaboration requests |
| ENTITY_ARCHIVE_JOB | Weekly Sun 05:00 | Archive low-priority memories >180 days |

## Python API Quick Reference

```python
from scripts.lib.memory_api import create_memory, get_memory, search_memories
from scripts.lib.knowledge_api import create_concept, create_relationship
from scripts.lib.agent_api import register_agent, create_session
from scripts.lib.harness_api import create_template, instantiate_template, derive_template
from scripts.lib.graph_api import get_neighbors, get_reachable, get_shortest_path

# Create a memory
entity_id = create_memory("Meeting Notes", "Discussed v2.1 architecture", category="meeting")

# Create a knowledge concept
concept_id = create_concept("Architecture Pattern", "principle", description="Unified entity model")

# Link them
edge_id = create_relationship(entity_id, concept_id, "DERIVED_FROM", strength=0.9)

# Register an agent
register_agent("agent-1", "Research Agent", capabilities=["read", "write"])

# Create and instantiate a harness template
tpl_id = create_template("Analyst", prompt_templates={"system": "You are a {role}..."},
                         tool_sets=["knowledge_tools", "memory_tools"], variables={"role": "Analyst"})
config = instantiate_template(tpl_id, variables={"role": "Data Scientist"})

# Property Graph API
neighbors = get_neighbors(entity_id, entity_type="MEMORY", depth=2)
reachable = get_reachable(entity_id, entity_type="KNOWLEDGE", max_depth=3)
path = get_shortest_path(entity_id, concept_id, source_type="MEMORY", target_type="KNOWLEDGE")
similar = find_similar_entities(entity_id, entity_type="MEMORY", top_k=5)
context = get_entity_context(entity_id, entity_type="KNOWLEDGE", depth=2)
subgraph = get_subgraph(entity_ids, entity_types=["MEMORY", "KNOWLEDGE"])
results = graph_search("architecture patterns", entity_type="KNOWLEDGE", max_depth=2)
communities = find_communities(entity_type="KNOWLEDGE", algorithm="louvain")
stats = get_graph_stats()
```

## Property Graph

`ORACLE_MEMORY_GRAPH` is defined in `1_schema.sql` with:
- **Vertices**: `ENTITIES` (all entity types: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE)
- **Edges**: `ENTITY_EDGES` (all 10 edge types)

### SQL PGQ Queries via GRAPH_TABLE

```sql
-- Find neighbors of a specific entity
SELECT v.entity_id, v.title, v.entity_type
FROM GRAPH_TABLE(ORACLE_MEMORY_GRAPH
  MATCH (v) -[e]-> (t)
  WHERE v.entity_id = :id AND v.entity_type = :type
  COLUMNS (v.entity_id, v.title, v.entity_type)
) gt;

-- Shortest path between two entities
SELECT *
FROM GRAPH_TABLE(ORACLE_MEMORY_GRAPH
  SHORTEST (src) -[e]->+ (dst)
  WHERE src.entity_id = :src_id AND dst.entity_id = :dst_id
  COLUMNS (src.entity_id AS source, dst.entity_id AS target, e.edge_type)
);
```

### graph_api.py Functions (9)

| Function | Description |
|----------|-------------|
| `get_neighbors(entity_id, entity_type, depth)` | Get neighboring entities within N hops |
| `get_reachable(entity_id, entity_type, max_depth)` | Get all reachable entities within depth limit |
| `get_shortest_path(src_id, dst_id, source_type, target_type)` | Find shortest path between two entities |
| `find_similar_entities(entity_id, entity_type, top_k)` | Find structurally similar entities via graph proximity |
| `get_entity_context(entity_id, entity_type, depth)` | Get full context graph around an entity |
| `get_subgraph(entity_ids, entity_types)` | Extract subgraph for specified entities |
| `graph_search(query, entity_type, max_depth)` | Natural language graph traversal search |
| `find_communities(entity_type, algorithm)` | Detect communities in the graph |
| `get_graph_stats()` | Return graph statistics (vertices, edges, density) |

## Web Visualization (4 pages)

| Page | Route | Features |
|------|-------|----------|
| Knowledge Graph | `/knowledge` | vis.js interactive graph, node details on click |
| Memory Content | `/memory` | vis.js interactive graph, node details on click |
| Agent Collaboration | `/agents` | Agent registry table, active sessions, collaboration requests |
| Task Plans | `/tasks` | Status filter, keyword search, accordion plan list, step tables |

All pages: bilingual (zh/en), session auth with auto-logout, `/api/stats` sidebar, `/api/graph/*` endpoints, UTF-8 encoding fix for oracledb double-encoding.

## Test Suite (49 tests)

| Module | Count | Coverage |
|--------|-------|----------|
| test_connection.py | 6 | Pool creation, ping, error handling |
| test_memory.py | 8 | Create, read, update, delete, search, list |
| test_knowledge.py | 8 | Concepts, relationships, graph queries |
| test_agent.py | 8 | Registration, sessions, collaboration, access log |
| test_graph.py | 8 | Neighbors, paths, subgraph, communities, stats |
| test_harness.py | 6 | CRUD, instantiate, derive, validate |
| test_security.py | 5 | Masking, encryption, hashing |

## v1.x → v2.1 Key Changes

- MEMORIES + MEMORY_NODES → ENTITIES (ENTITY_TYPE='MEMORY')
- KNOWLEDGE_CONCEPTS → ENTITIES (ENTITY_TYPE='KNOWLEDGE')
- MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH → ENTITY_EDGES
- SQLcl subprocess → oracledb driver with connection pooling
- 12+ SQL scripts → 4-phase deployment (schema → API → jobs → harness templates)
- 934-line SKILL.md → concise + 8 topic docs
- 2 property graphs → 1 unified ORACLE_MEMORY_GRAPH
- AGENT_MEMORY_ACCESS → ENTITY_ACCESS_LOG (all entity types)
- No agent/task dashboard → 4-page web UI with Agent Collaboration and Task Plans
- Single-column PKs → composite PKs for partition key compliance
- Unpartitioned → LIST+RANGE, REFERENCE, RANGE+HASH partitioning
- No graph API → graph_api.py with 9 GRAPH_TABLE functions
