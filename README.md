# Oracle AI Database Memory System v2.0.0

[![Version](https://img.shields.io/badge/version-v2.0.0-blue.svg)](RELEASE_NOTES_v2.0.0.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-red.svg)](https://www.oracle.com/database/)
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Unified AI Agent Memory System with Knowledge Graph, Multi-Agent Collaboration, Task Planning, Harness Templates, and Web Visualization — built on Oracle 23ai.**

> **v2.0.0 is a complete rewrite.** It is not backward-compatible with v1.x. See [RELEASE_NOTES_v2.0.0.md](RELEASE_NOTES_v2.0.0.md) for details.

---

## What's New in v2.0.0

### Unified Entity Architecture

v1.x used 5 separate tables (MEMORIES, MEMORY_NODES, MEMORY_EDGES, MEMORY_RELATIONSHIPS, KNOWLEDGE_CONCEPTS) with fragmented relationships. v2.0 consolidates everything into a single **ENTITIES** table with an `ENTITY_TYPE` discriminator, and a single **ENTITY_EDGES** table for all relationships.

```
v1.x:  MEMORIES + MEMORY_NODES + MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_CONCEPTS + KNOWLEDGE_GRAPH
v2.0:  ENTITIES (ENTITY_TYPE IN 'MEMORY','KNOWLEDGE','TASK_OUTPUT','EXPERIENCE','HARNESS_TEMPLATE') + ENTITY_EDGES
```

### oracledb Driver (No SQLcl Subprocess)

v1.x spawned SQLcl subprocess for every database operation (90+ second timeouts). v2.0 uses the Python `oracledb` driver with connection pooling — **4500x faster**.

### 3-Phase + Harness SQL Deployment

v1.x had 15+ scattered SQL scripts. v2.0 consolidates into 4 ordered deployment scripts:
1. `1_schema.sql` — Tables, indexes, property graph, duality views
2. `2_api.sql` — PL/SQL packages (fusion, knowledge, permissions, cleanup)
3. `3_jobs.sql` — Scheduler jobs (7 automated maintenance jobs)
4. `4_harness_templates.sql` — HARNESS_META table + 5 built-in harness templates

### Restructured Documentation

v1.x had a 934-line SKILL.md and 12+ scattered markdown files. v2.0 has a concise SKILL.md + 7 topic-focused docs in `docs/`.

### Harness Template System

Reusable agent execution blueprints stored as ENTITIES (`ENTITY_TYPE='HARNESS_TEMPLATE'`). Each template defines:
- **prompt_templates** — Parameterized prompt skeletons with `{variable}` slots
- **tool_bindings** — Which tools the agent can use and with what permissions
- **memory_access** — Read/write policies for short-term and long-term memory
- **guardrails** — Execution limits, content moderation, PII filtering
- **evaluation** — Output format, quality thresholds

Templates support variable substitution, inheritance (child `DERIVES_FROM` parent), instantiation, validation, and a DRAFT → PUBLISHED → DEPRECATED lifecycle. 5 built-in templates are included (Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor). See [docs/harness.md](docs/harness.md).

---

## Project Structure

```
scripts/
  deploy/
    1_schema.sql          # Phase 1: Schema (tables, indexes, graph, views)
    2_api.sql             # Phase 2: PL/SQL API packages
    3_jobs.sql            # Phase 3: Scheduler jobs
    4_harness_templates.sql  # Phase 4: HARNESS_META + 5 built-in templates
  lib/
    config.py             # Unified Config with env var overrides
    connection.py         # oracledb connection pool manager
    memory_api.py         # Memory CRUD (ENTITIES, ENTITY_TYPE='MEMORY')
    knowledge_api.py      # Knowledge CRUD + graph operations
    agent_api.py          # Agent registration, sessions, collaboration
    task_plan_api.py      # Task plans, steps, snapshots, dependencies
    security.py           # Data masking, encryption, password hashing
    harness_api.py        # Harness template CRUD, instantiate, derive, validate
  tests/
    test_connection.py    # Connection pool tests
    test_memory.py        # Memory API tests
    test_knowledge.py     # Knowledge API tests
    test_agent.py         # Agent API tests
    test_security.py      # Security module tests
    test_harness.py       # Harness template tests
    test_all.py           # Master test runner
docs/
  architecture.md         # Design decisions and entity model
  api-reference.md        # Python + PL/SQL API documentation
  deployment.md           # Deployment guide and troubleshooting
  migration.md            # v1.x to v2.0 migration guide
  security.md             # Security features and configuration
  visualization.md        # Web visualization server guide
  minimum-privileges.md   # Database user minimum privilege analysis
  harness.md              # Harness template system guide
config.json               # Database, server, embedding, security config
viz_server_local_js.py    # Web visualization server
start_web_server.sh       # Server control script (start/stop/restart/status/config/log)
SKILL.md                  # Concise skill documentation
```

---

## Quick Start

### Prerequisites

- Oracle Database 23ai+ (tested on 23.26.1.0.0)
- Python 3.8+ with `oracledb` package
- SQLcl 26.1+ (for SQL script deployment)

### 1. Deploy Schema

```bash
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
sql user/password@//host:port/service @scripts/deploy/4_harness_templates.sql
```

### 2. Install Python Dependencies

```bash
pip install oracledb
```

### 3. Configure

Edit `config.json` or set environment variables:

```bash
export MEMORY_DB_USER=openclaw
export MEMORY_DB_PASSWORD=hermes
export MEMORY_DB_DSN=10.10.10.130:1521/openclaw
```

### 4. Run Tests

```bash
cd scripts && python -m tests.test_all
```

### 5. Start Visualization Server

```bash
./start_web_server.sh start    # Start (daemon mode)
./start_web_server.sh status   # Check status
./start_web_server.sh stop     # Stop
./start_web_server.sh restart  # Restart
./start_web_server.sh config   # Show configuration
./start_web_server.sh log      # View log
# Open http://localhost:8000
```

---

## Architecture

```
ENTITIES (unified)
  ├── MEMORY        (replaces MEMORIES + MEMORY_NODES)
  ├── KNOWLEDGE     (replaces KNOWLEDGE_CONCEPTS)
  ├── TASK_OUTPUT
  ├── EXPERIENCE
  └── HARNESS_TEMPLATE (reusable agent execution blueprints)

ENTITY_EDGES (unified)
  └── Replaces MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH
  └── Supports DERIVES_FROM for template inheritance

KNOWLEDGE_META      Extended metadata for KNOWLEDGE entities
HARNESS_META        Versioning, status, variables for HARNESS_TEMPLATE entities
ENTITY_EMBEDDINGS   VECTOR(1024, FLOAT32) for semantic search
ORACLE_MEMORY_GRAPH Single property graph (replaces 2 separate graphs)
```

### Key Tables (17)

| Table | Purpose |
|-------|---------|
| ENTITIES | Unified store with ENTITY_TYPE discriminator (incl. HARNESS_TEMPLATE) |
| ENTITY_EDGES | Directed edges with strength, confidence, and DERIVES_FROM inheritance |
| KNOWLEDGE_META | Source, validation, versioning for knowledge |
| HARNESS_META | Template versioning, status, variables, changelog |
| ENTITY_EMBEDDINGS | Vector embeddings for semantic search |
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
| SYSTEM_CONFIG / SYSTEM_USERS | System configuration and accounts |

---

## Python API Quick Reference

```python
from scripts.lib.memory_api import create_memory, get_memory, search_memories
from scripts.lib.knowledge_api import create_concept, create_relationship
from scripts.lib.agent_api import register_agent, create_session
from scripts.lib.harness_api import create_template, instantiate_template, derive_template

# Memory
mid = create_memory("Meeting Notes", "Discussed v2.0", category="meeting")

# Knowledge
kid = create_concept("Unified Architecture", "principle",
                     description="Single ENTITIES table", confidence=0.95)

# Relationship
eid = create_relationship(mid, kid, "DERIVED_FROM", strength=0.9)

# Agent
register_agent("agent-1", "Research Agent", capabilities=["read", "write"])

# Harness Template
tpl_id = create_template("Analyst", prompt_templates={"system": "You are a {role}..."},
                         tool_sets=["knowledge_tools", "memory_tools"],
                         variables={"role": "Analyst"})
config = instantiate_template(tpl_id, variables={"role": "Data Scientist"})
```

Full API: [docs/api-reference.md](docs/api-reference.md)

---

## Web Visualization

Built-in web server with interactive graph visualization and dashboards:

- **Knowledge Graph** (`/knowledge`) — Browse KNOWLEDGE entities and their relationships
- **Memory Content** (`/memory`) — Browse MEMORY entities and their connections
- **Agent Collaboration** (`/agents`) — Agent registry, active sessions, collaboration requests
- **Task Plans** (`/tasks`) — Plan list with status filter, search, expandable step details
- **Bilingual UI** — Chinese/English toggle with localStorage persistence
- **Session Auth** — Login with SYSTEM_USERS credentials, configurable timeout
- **UTF-8 Encoding Fix** — Auto-detects and corrects double-encoded Chinese from oracledb

```bash
./start_web_server.sh start
# http://localhost:8000
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [SKILL.md](SKILL.md) | Concise skill overview |
| [docs/architecture.md](docs/architecture.md) | Design decisions and entity model |
| [docs/api-reference.md](docs/api-reference.md) | Python and PL/SQL API reference |
| [docs/deployment.md](docs/deployment.md) | Deployment and troubleshooting |
| [docs/migration.md](docs/migration.md) | v1.x to v2.0 migration guide |
| [docs/security.md](docs/security.md) | Security features and configuration |
| [docs/visualization.md](docs/visualization.md) | Web visualization server guide |
| [docs/harness.md](docs/harness.md) | Harness template system guide |
| [docs/minimum-privileges.md](docs/minimum-privileges.md) | Minimum database user privileges |
| [docs/introduction_v2.0.0_zh.md](docs/introduction_v2.0.0_zh.md) | v2.0.0 中文完整介绍 |
| [RELEASE_NOTES_v2.0.0.md](RELEASE_NOTES_v2.0.0.md) | v2.0.0 release notes |

---

## Test Results

```
Oracle Memory System v2.0.0 - Full Test Suite
============================================================
  Connection:  6/6 PASS
  Memory:      7/7 PASS
  Knowledge:   7/7 PASS
  Agent:       7/7 PASS
  Security:   10/10 PASS
  Harness:    10/10 PASS
Overall: ALL PASSED
```

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| **v2.0.0** | 2026-05-15 | Complete rewrite: unified architecture, oracledb driver, 3-phase deployment |
| v1.1.0 | 2026-05-12 | Web visualization, session security, bilingual UI |
| v1.0.0 | 2026-05-10 | Production release: knowledge base, property graph, multi-agent |
| v0.5.1 | 2026-05-08 | Enhanced session management |
| v0.5.0 | 2026-05-06 | Multi-agent collaboration framework |
| v0.4.2 | 2026-05-04 | Bug fixes and stability |
| v0.4.0 | 2026-05-02 | Task plan system |
| v0.3.x | 2026-04-28 | Core memory system |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)

## Author

**Haiwen Yin** — [GitHub](https://github.com/Haiwen-Yin) | [Blog](https://blog.csdn.net/yhw1809)
