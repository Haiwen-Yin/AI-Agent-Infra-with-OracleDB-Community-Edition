---
name: oracle-memory-by-yhw
version: v2.0.0
author: Haiwen Yin
description: Oracle AI Database Memory System v2.0.0 - Unified architecture with ENTITIES, ENTITY_EDGES, oracledb driver, 3-phase SQL deployment, property graph, and multi-agent collaboration
tags: [oracle, memory-system, knowledge-base, vector-search, oracledb, property-graph, multi-agent]
related_skills: [oracle-26ai, oracle-sqlcl-execution-methodology]
---

# Oracle AI Database Memory System v2.0.0

**Author**: Haiwen Yin
**Version**: v2.0.0 - 2026-05-15
**License**: Apache License 2.0

---

## Architecture Overview

```
ENTITIES (unified) ──┬── MEMORY (replaces MEMORIES + MEMORY_NODES)
                      ├── KNOWLEDGE (replaces KNOWLEDGE_CONCEPTS)
                      ├── TASK_OUTPUT
                      ├── EXPERIENCE
                      └── HARNESS_TEMPLATE (reusable agent execution blueprints)

ENTITY_EDGES (unified) ── replaces MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH

KNOWLEDGE_META ── extended metadata for KNOWLEDGE entities
HARNESS_META ── versioning, status, variables for HARNESS_TEMPLATE entities
ENTITY_EMBEDDINGS ── VECTOR(1024, FLOAT32) for semantic search
```

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
    1_schema.sql    # Tables, indexes, property graph, duality views
    2_api.sql       # PL/SQL packages (fusion, knowledge, permissions, cleanup)
    3_jobs.sql      # Scheduler jobs (7 automated jobs)
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
  tests/
    test_connection.py
    test_memory.py
    test_knowledge.py
    test_agent.py
    test_security.py
    test_harness.py
    test_all.py
docs/
  architecture.md   # Detailed architecture and design decisions
  api-reference.md  # Python and PL/SQL API documentation
  deployment.md     # Deployment guide and troubleshooting
  migration.md      # v1.x → v2.0 migration guide
  security.md       # Security features and configuration
  visualization.md  # Web visualization server guide
  harness.md        # Harness template system guide
config.json         # Database, server, embedding, security config
viz_server_local_js.py  # Web visualization (needs v2.0 schema update)
```

## Key Tables (16 total)

| Table | Purpose |
|-------|---------|
| ENTITIES | Unified store: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE |
| ENTITY_EDGES | Unified directed edges with strength/confidence |
| KNOWLEDGE_META | Source type, validation, versioning, confidence |
| HARNESS_META | Harness template versioning, status, variables, changelog |
| ENTITY_EMBEDDINGS | VECTOR(1024, FLOAT32) embeddings |
| AGENT_REGISTRY | Agent identity, capabilities, permissions |
| AGENT_SESSION | Session tracking with context snapshots |
| ENTITY_ACCESS_LOG | Audit trail for all entity access |
| AGENT_PERMISSION_LOG | Permission change audit |
| AGENT_COLLABORATION | Cross-agent sharing requests |
| TASK_PLANS | Multi-step task definitions |
| TASK_STEPS | Plan steps with status tracking |
| TASK_CONTEXT_SNAPSHOTS | Breakpoint/recovery snapshots |
| TASK_TOOL_CALLS | Tool invocation audit |
| TASK_DEPENDENCIES | Inter-plan dependency graph |
| TAGS / ENTITY_TAGS | Normalized tag system |
| SYSTEM_CONFIG / SYSTEM_USERS | System configuration and user accounts |

## PL/SQL Packages

| Package | Purpose |
|---------|---------|
| MEMORY_FUSION_ENGINE | Merge similar memories, extract knowledge, decay priorities |
| KNOWLEDGE_BASE_API | Validate, deprecate, version concepts, lineage queries |
| AGENT_PERMISSION_MANAGER | Access control, session cleanup, collaboration processing |
| SESSION_CLEANUP | Purge logs, archive entities, update tag counts |

## Scheduler Jobs (7)

| Job | Schedule | Action |
|-----|----------|--------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + decay priorities |
| KNOWLEDGE_EXTRACTION_JOB | Daily 03:00 | Extract knowledge from memory patterns |
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

# Create a memory
entity_id = create_memory("Meeting Notes", "Discussed v2.0 architecture", category="meeting")

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
```

## Web Visualization (4 pages)

| Page | Route | Features |
|------|-------|----------|
| Knowledge Graph | `/knowledge` | vis.js interactive graph, node details on click |
| Memory Content | `/memory` | vis.js interactive graph, node details on click |
| Agent Collaboration | `/agents` | Agent registry table, active sessions, collaboration requests |
| Task Plans | `/tasks` | Status filter, keyword search, accordion plan list, step tables |

All pages: bilingual (zh/en), session auth with auto-logout, `/api/stats` sidebar, UTF-8 encoding fix for oracledb double-encoding.

## v1.x → v2.0 Key Changes

- MEMORIES + MEMORY_NODES → ENTITIES (ENTITY_TYPE='MEMORY')
- KNOWLEDGE_CONCEPTS → ENTITIES (ENTITY_TYPE='KNOWLEDGE')
- MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH → ENTITY_EDGES
- SQLcl subprocess → oracledb driver with connection pooling
- 12+ SQL scripts → 4-phase deployment (schema → API → jobs → harness templates)
- 934-line SKILL.md → 200 lines + 8 topic docs
- 2 property graphs → 1 unified ORACLE_MEMORY_GRAPH
- AGENT_MEMORY_ACCESS → ENTITY_ACCESS_LOG (all entity types)
- No agent/task dashboard → 4-page web UI with Agent Collaboration and Task Plans
