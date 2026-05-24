# Oracle AI Database Memory System v2.3.0

[![Version](https://img.shields.io/badge/version-v2.3.0-blue.svg)](RELEASE_NOTES_v2.3.0.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-red.svg)](https://www.oracle.com/database/)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-99%2F99-brightgreen.svg)]()
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Partitioned AI Agent Memory System with Spec Driven Development, Agent Elastic Management, Collaboration Groups, Property Graph API, Knowledge Graph, Multi-Agent Collaboration, Task Planning, Harness Templates, Workspace & Context Continuity, and Web Visualization — built on Oracle 26ai.**

> **v2.3.0 adds Spec Driven Development (SDD), Agent Elastic Management (DORMANT/POOL + credentials), and Collaboration Groups.** See [CHANGELOG.md](CHANGELOG.md) for details.

**[中文说明 / Chinese Introduction](docs/introduction_v2.3.0_zh.md)**

---

## What's New in v2.3.0

### Spec Driven Development (SDD)

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
      2_api.sql                 # 7 PL/SQL packages
      3_jobs.sql                # 11 scheduler jobs
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
      test_all.py               # Master runner (99 total)
    visualization/
      server.py                 # HTTP server v2.3.0
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
    introduction_v2.3.0_zh.md   # v2.3.0 中文完整介绍
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
# Open http://localhost:8000 — Login: admin / admin123
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

27 tables total | 6 JRD views | 7 PL/SQL packages | 11 scheduler jobs
12 Python modules | 99+ API functions | 99/99 tests pass
```

### Key Tables (27)

| Category | Tables |
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
```

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
Oracle Memory System v2.3.0 - Full Test Suite
============================================================
  Connection:   6/6 PASS
  Memory:       8/8 PASS
  Knowledge:    8/8 PASS
  Agent:        8/8 PASS
  Graph:        8/8 PASS
  Harness:      6/6 PASS
  Security:     5/5 PASS
  Workspace:   12/12 PASS
  Spec:         9/9 PASS [NEW]
  Collab:      12/12 PASS [NEW]
  Credential:   9/9 PASS [NEW]
Overall: 99/99 ALL PASSED
```

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
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
