# Oracle AI Database Memory System v2.3.2

[![Version](https://img.shields.io/badge/version-v2.3.2-blue.svg)](RELEASE_NOTES_v2.3.2.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-red.svg)](https://www.oracle.com/database/)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-183%2F183-brightgreen.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Partitioned AI Agent Memory System with Embedding Generation & Vector Search, 5-Signal Unified Hybrid Search + Fulltext Search + Search API, Spec Driven Development, Agent Elastic Management, Collaboration Groups, Property Graph API, Knowledge Graph, Multi-Agent Collaboration, Task Planning, Harness Templates, Workspace & Context Continuity, and Web Visualization — built on Oracle 26ai.**

> **v2.3.2: Web UI optimization — client-side pagination, sticky headers, viewport fixes. v2.3.1: Embedding fix, 5-signal unified hybrid search, fulltext search, unified search API (10 strategies), single-SQL CTE fusion search. v2.3.0 added SDD, Agent Elastic Management, and Collaboration Groups.** See [CHANGELOG.md](CHANGELOG.md) for details.

**[中文说明 / Chinese Introduction](docs/introduction_v2.3.2_zh.md)**

---

## What's New in v2.3.2

### Web UI Optimization

Pure front-end improvements — no database or API changes. All 183 tests from v2.3.1 continue to pass.

| Feature | Description |
|---------|-------------|
| **Client-side pagination** | PAGE_SIZE=30 with Prev/Next + page number buttons for all data tables. Agents page has triple pagination (registry/sessions/collabs). |
| **Sticky table headers** | Headers stay visible while scrolling with `position:sticky` + shadow effect |
| **Viewport height fix** | `height:100vh` prevents layout overflow; content areas use `calc(100vh - 120px)` |
| **Table spacing** | `border-collapse:separate;border-spacing:0` for consistent cell rendering |
| **Login language persistence** | Language preference saved and restored across sessions |

## What's New in v2.3.1

### 5-Signal Unified Hybrid Search + Fulltext Search (v2.3.1)

Multi-signal retrieval combining vector similarity, fulltext (Oracle Text), relational metadata, tag overlap, and graph proximity:

| Signal | Weight | Source | Scoring |
|--------|--------|--------|---------|
| Vector | 0.4 | ENTITY_EMBEDDINGS via VECTOR_DISTANCE(COSINE) | 1 - cosine_distance |
| Fulltext | 0.25 | Oracle Text CONTAINS(title) + SCORE(1) | ft_score / 100 |
| Relational | 0.2 | KNOWLEDGE_META(domain,topic) + SPEC_META(scope,complexity) + ENTITIES(category,importance) | Domain/scope match + importance |
| Tag | (included in relational) | ENTITY_TAGS | Tag overlap + query match |
| Graph | 0.15 | ENTITY_EDGES BFS from seed entity | 1/depth proximity + connectivity boost |

```python
from scripts.lib.embedding_api import search_unified

# Basic unified search
results = search_unified("database partitioning", top_k=5)

# With domain/category/tag filters
results = search_unified("encryption", top_k=5, domain="security", tags=["encryption"])

# With graph seed for proximity boost
results = search_unified("architecture", top_k=5, graph_seed_entity_id=some_entity_id)

# Custom weights
results = search_unified("search", top_k=5,
    vector_weight=0.3, fulltext_weight=0.3,
    relational_weight=0.2, graph_weight=0.2)

# Each result has per-signal scores
for r in results:
    print(f"{r['title']:40s} final={r['final_score']:.3f} "
          f"vec={r['scores']['vector']:.3f} ft={r['scores']['fulltext']:.3f} "
          f"rel={r['scores']['relational']:.3f} graph={r['scores']['graph']:.3f}")
```

### Fulltext Search (Oracle Text) (v2.3.1)

```python
from scripts.lib.embedding_api import search_fulltext

# Oracle Text full-text search
results = search_fulltext("database partitioning", top_k=10)
for r in results:
    print(f"{r['title']:40s} ft_score={r['ft_score']:.3f}")
```

### Embedding Generation & Vector Search (v2.3.1 RESTORED + ENHANCED)

The architecture rewrite in v2.0.0 (partitioning, composite PKs, JRD dual views) missed the embedding generation and vector search capabilities from v1.x/v2.0. v2.3.1 fully fixes and enhances:

- **EMBEDDING_MANAGER PL/SQL** — `generate_and_store` fix: `JSON_QUERY WITH WRAPPER` returns double brackets `[[-0.03,...]]` for arrays, requiring SUBSTR to remove outer layer + VECTOR variable assignment
- **embedding_api.py** — All binds changed to named binds (`:1,:2,:3` → `:eid,:etype,:vec`), fixing oracledb thin mode ORA-01722
- **search_similar()** — Vector similarity search (supports entity_type/workspace_id filtering)
- **search_by_entity_id()** — Search similar entities based on existing entity vector
- **search_hybrid()** — Vector + keyword hybrid search with adjustable weights vector_weight (default 0.7), 3D scoring
- **search_multi_type()** — Cross-type vector search (MEMORY/KNOWLEDGE/SPEC)
- **EMBEDDING_GENERATION_JOB** — Scheduler job that auto-generates embeddings for MEMORY/KNOWLEDGE entities every 2 hours
- **19 embedding tests** — All passed

### Spec Driven Development (SDD) (v2.3.0)

Specifications as first-class citizens stored as ENTITIES subtype `SPEC`, with reference-partitioned SPEC_META and many-to-many SPEC_PLAN_LINKS:

- **SPEC_META** — Version, status, acceptance_criteria, constraints (reference-partitioned from ENTITIES)
- **SPEC_PLAN_LINKS** — Many-to-many with LINK_TYPE: DRIVES / VALIDATES / CONSTRAINS / EXTENDS
- **spec_api.py** — 10 Python functions: create, get, update, list, create_plan_from_spec, link_spec_to_plan, validate_plan_against_spec, derive_spec, delete
- **SPEC_MANAGER** PL/SQL package — 8 subprograms including validate_spec and derive_spec
- **SPEC_DV** — JRD updatable view for spec entities

### Agent Elastic Management

Two new agent states for resource optimization and credential-based authentication:

- **DORMANT** — Temporary hibernate; preserves agent identity and context; wake on demand
- **POOL** — Stateless idle agents; context follows user via credentials; matched by skills_tags intersection
- **AGENT_CREDENTIALS** — Encrypted with ReversibleEncryption; auto-expiry; SCOPE = {access_level, restricted_domains, max_clearance}
- **agent_api.py +8** — issue_credential, verify_credential, get_credentials_for_user, revoke_credential, hibernate_agent, wake_agent, register_pool_agent, assign_pool_agent
- **DORMANT_AGENT_JOB** — Auto-hibernates agents inactive beyond `dormant_timeout_min` (default 60 min)
- **CREDENTIAL_CLEANUP_JOB** — Daily purge of expired/revoked credentials

### Collaboration Groups

Mode C collaboration model with group-level shared workspace and optional personal workspace:

- **COLLAB_GROUPS** — Group definitions with SHARING_POLICY: OPEN / MODERATED / RESTRICTED
- **COLLAB_GROUP_MEMBERS** — Roles: LEAD / CONTRIBUTOR / OBSERVER; LEAD/CONTRIBUTOR get auto-created personal Workspace
- **COLLAB_GROUP_DV** — JRD updatable view
- **COLLAB_GROUP_MANAGER** PL/SQL package — 6 subprograms
- **collab_api.py** — 10 Python functions including share_memory_to_group, get_group_shared_memories

### Visualization Enhancements

- **Specs page** (`/specs`) — List/detail tabs, plan linkage display
- **Collab page** (`/collab`) — Groups, members, shared memory
- **Inline detail expansion** — Knowledge/Memory List view uses row expansion (Tasks pattern); Graph view retains right-side detail panel
- **Bilingual sidebar** — All 8 pages have data-zh/data-en navigation links
- **Truncated IDs** — Full content on hover via title attribute

---

## What's New in v2.2.0

### Workspace & Context Continuity

- **WORKSPACES** — Lifecycle (ACTIVE → PAUSED → ARCHIVED), isolation modes (SHARED/ISOLATED), ownership tracking
- **WORKSPACE_CONTEXT** — Version chain of context entries (CHECKPOINT, HANDOFF, SUMMARY, ERROR_STATE, AUTO_SAVE)
- **WORKSPACE_TASKS** — Links task plans to workspaces
- **Agent Handoff** — `PREDECESSOR_SESSION_ID` chains sessions; `OWNER_USER_ID` and `WORKSPACE_ID` on AGENT_SESSION
- **JRD Updatable Views** — `WORKSPACE_DV` (updatable), `CONTEXT_DV` (read-only), `MEMORY_DV`/`KNOWLEDGE_DV` updatable

---

## Project Structure

```
oracle-memory-by-yhw/
  scripts/
    deploy/
      1_schema.sql              # 27 tables, 6 JRD views, indexes, property graph, seed data
      2_api.sql                 # 8 PL/SQL packages
      3_jobs.sql                # 12 scheduler jobs
      4_harness_templates.sql   # HARNESS_META + 5 built-in templates
    lib/
      config.py                 # Unified Config with env var overrides
      connection.py             # oracledb connection pool manager
      memory_api.py             # Memory CRUD (8 functions)
      knowledge_api.py          # Knowledge CRUD + graph operations (7 functions)
      agent_api.py              # Agent, sessions, credentials, elastic (17 functions)
      task_plan_api.py          # Task plans, steps, dependencies (6 functions)
      security.py               # Data masking, encryption, password hashing
      harness_api.py            # Harness template CRUD (6 functions)
      graph_api.py              # Property Graph API (9 functions)
      workspace_api.py          # Workspace lifecycle, context, handoff (14 functions)
      spec_api.py               # Spec CRUD + plan linkage (10 functions) [NEW]
      collab_api.py             # Collaboration groups (10 functions) [NEW]
      embedding_api.py          # Vector embedding generation, storage, 5-signal+fulltext search (14 functions) [NEW]
      search_api.py             # Unified search entry point, 10 strategies with auto-detection (3 functions) [NEW]
    tests/
      test_connection.py        # 6 tests
      test_memory.py            # 8 tests
      test_knowledge.py         # 8 tests
      test_agent.py             # 8 tests
      test_security.py          # 5 tests
      test_harness.py           # 6 tests
      test_graph.py             # 8 tests
      test_workspace.py         # 12 tests
      test_spec.py              # 9 tests [NEW]
      test_collab.py            # 12 tests [NEW]
      test_credential.py        # 9 tests [NEW]
      test_embedding.py         # 19 tests [NEW]
      test_unified_search.py    # 31 tests [NEW]
      test_search_api.py        # 42 tests [NEW]
      test_all.py               # Master runner (171 total)
    visualization/
      server.py                 # HTTP server v2.3.2
      templates/                # 9 HTML templates (login, knowledge, memory, agents, tasks, workspaces, graph, specs, collab)
      static/                   # style.css + vis-network.min.js
  docs/
    architecture.md             # Design decisions and entity model
    api-reference.md            # Python + PL/SQL API reference
    deployment.md               # Deployment guide
    security.md                 # Security features
    visualization.md            # Web visualization guide
    harness.md                  # Harness template system guide
    workspace.md                # Workspace & context continuity
    minimum-privileges.md       # Database user privileges
    introduction_v2.3.2_zh.md   # v2.3.2 Chinese introduction
  CHANGELOG.md
  SKILL.md
  README.md
```

---

## Quick Start

### Prerequisites

- Oracle Database 23ai+ (tested on 26ai)
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

```bash
export MEMORY_DB_USER=<db_user>
export MEMORY_DB_PASSWORD=<db_password>
export MEMORY_DB_DSN=<db_host>:<db_port>/<db_service>
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
# Open http://<web_host>:<web_port> — Login: admin / admin123
```

---

## Architecture

```
ENTITIES (LIST partitioned by ENTITY_TYPE)
  ├── MEMORY              Short-term episodic memory
  ├── KNOWLEDGE           Validated knowledge concepts
  ├── TASK_OUTPUT         Task execution results
  ├── EXPERIENCE          Learned patterns
  ├── HARNESS_TEMPLATE    Reusable agent execution blueprints
  ├── SPEC [NEW v2.3.0]  Specifications for SDD
  └── OTHER               Unclassified

6 REFERENCE-partitioned children:
  ENTITY_EDGES, KNOWLEDGE_META, SPEC_META [NEW], HARNESS_META,
  ENTITY_EMBEDDINGS, ENTITY_TAGS

27 tables total | 6 JRD views | 8 PL/SQL packages | 12 scheduler jobs
15 Python modules | 131+ API functions | 183/183 tests pass
```

### Key Tables (27)
| Key | Tables' Names |
|----------|--------|
| Core | ENTITIES, ENTITY_EDGES, KNOWLEDGE_META, SPEC_META [NEW], HARNESS_META, ENTITY_EMBEDDINGS, ENTITY_TAGS |
| System | SYSTEM_USERS, SYSTEM_CONFIG, TAGS |
| Agent | AGENT_REGISTRY, AGENT_CREDENTIALS [NEW], AGENT_SESSION, ENTITY_ACCESS_LOG, AGENT_PERMISSION_LOG |
| Collaboration | AGENT_COLLABORATION, COLLAB_GROUPS [NEW], COLLAB_GROUP_MEMBERS [NEW] |
| Workspace | WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS |
| Task | TASK_PLANS, TASK_STEPS, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES |
| Spec | SPEC_PLAN_LINKS [NEW] |

---

## Python API Quick Reference

```python
from scripts.lib.memory_api import create_memory, get_memory, search_memories
from scripts.lib.knowledge_api import create_knowledge, add_edge, get_edges
from scripts.lib.agent_api import register_agent, create_session, issue_credential, hibernate_agent, wake_agent, assign_pool_agent
from scripts.lib.workspace_api import create_workspace, create_handoff_session, recover_workspace
from scripts.lib.spec_api import create_spec, create_plan_from_spec, link_spec_to_plan, validate_plan_against_spec
from scripts.lib.collab_api import create_collab_group, add_group_member, share_memory_to_group
from scripts.lib.embedding_api import store_embedding, search_similar, search_hybrid, search_multi_type, search_unified, search_fulltext
from scripts.lib.search_api import search, list_search_strategies, describe_search_strategy

# Memory
mid = create_memory({"title": "Meeting Notes", "content": "Discussed v2.3"})

# Knowledge
kid = create_knowledge({"title": "SDD Pattern", "domain": "architecture"})

# Spec [NEW v2.3.0]
sid = create_spec({"title": "API Auth Spec"}, {"version": "1.0", "acceptance_criteria": [...]})
pid = create_plan_from_spec(sid, "Implement API Auth", "Add authentication layer")
link_spec_to_plan(sid, pid, "DRIVES")

# Agent + Credentials [NEW v2.3.0]
aid = register_agent("agent-1", "Research", {"skills": ["search"]})
cred_id = issue_credential(aid, "user-1", "API_KEY", {"access_level": "FULL"})
hibernate_agent(aid)
wake_agent(aid)
pool_id = register_pool_agent("worker-1", {"skills": ["analyze"]}, ["analyze", "search"])
assigned = assign_pool_agent("user-1", ["analyze"])

# Collaboration [NEW v2.3.0]
gid = create_collab_group("Security Board", "PROJECT", "MODERATED")
add_group_member(gid, "agent-1", "LEAD")
share_memory_to_group(gid, mid, "agent-1")

# Embedding & Vector Search [NEW v2.3.2]
store_embedding(mid, "MEMORY", "meeting notes about v2.3")
results = search_similar("database architecture", top_k=5, entity_type="MEMORY")
hybrid = search_hybrid("security patterns", keyword="encryption", top_k=5)
multi = search_multi_type("distributed systems", entity_types=["MEMORY", "KNOWLEDGE"])

# Unified Search API - single entry, 10 strategies [NEW v2.3.2]
unified = search("database partitioning", strategy="unified", top_k=5)
sql_fusion = search("encryption", strategy="unified_sql", domain="security", top_k=5)
auto = search("security", strategy="auto")
strats = list_search_strategies()
desc = describe_search_strategy("unified")
```

**LLM Context Economics**: `unified_sql` executes 5-signal fusion as a single CTE SQL statement, reducing 4-5 Python-SQL round trips to 1. This saves 60-80% of tool-call token overhead and eliminates intermediate-result context pollution — critical for LLM agents with limited context windows.

Full API: [SKILL.md](SKILL.md)

---

## Web Visualization

8-page dashboard with dark theme, bilingual UI, and 5-min auto-logout:

| Page | URL | Features |
|------|-----|----------|
| Knowledge | `/knowledge` | List/Graph dual view, inline detail expansion |
| Memory | `/memory` | List/Graph dual view, category filter |
| Agents | `/agents` | Registry/Sessions/Collaborations tabs |
| Tasks | `/tasks` | Accordion plans, step details, tool I/O |
| Workspaces | `/workspaces` | Expandable detail rows, context timeline |
| Graph Explorer | `/graph` | Stats cards, search, vis-network, detail panel |
| Specs [NEW] | `/specs` | Spec list, plan linkage, detail view |
| Collab [NEW] | `/collab` | Groups, members, shared memory |

Login: `admin` / `admin123`

---

## Test Results

```
Oracle Memory System v2.3.2 - Full Test Suite
============================================================
  Connection:   6/6 PASS
  Memory:       8/8 PASS
  Knowledge:    8/8 PASS
  Agent:        8/8 PASS
  Graph:        8/8 PASS
  Harness:      6/6 PASS
  Security:     5/5 PASS
  Workspace:   12/12 PASS
  Spec:         9/9 PASS
  Collab:      12/12 PASS
  Credential:   9/9 PASS
  Embedding:   19/19 PASS
  UnifiedSearch: 20/20 PASS
  SearchAPI:   36/36 PASS
Overall: 183/183 ALL PASSED
```

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| **v2.3.2** | 2026-05-27 | Web UI optimization — pagination, sticky headers, viewport fixes |
| **v2.3.1** | 2026-05-26 | Embedding fix, 5-signal unified hybrid search, fulltext search, search API (10 strategies), single-SQL CTE fusion |
| **v2.3.0** | 2026-05-24 | Spec Driven Development, Agent Elastic Management, Collaboration Groups |
| v2.2.1 | 2026-05-23 | Template-based visualization, sidebar navigation, Graph Explorer |
| v2.2.0 | 2026-05-20 | Workspace & context continuity, JRD updatable views |
| v2.1.0 | 2026-05-19 | Table partitioning, composite PKs, Property Graph API |
| v2.0.0 | 2026-05-15 | Complete rewrite: unified architecture, oracledb driver |
| v1.x | 2026-04–05 | Initial releases: knowledge base, multi-agent, task planning |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)

## Author

**Haiwen Yin** — [GitHub](https://github.com/Haiwen-Yin) | [Blog](https://blog.csdn.net/yhw1809)
