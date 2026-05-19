# Oracle Memory System v2.1.0 Release Notes

**Release Date**: 2026-05-19
**Author**: Haiwen Yin (胖头鱼 🐟)
**License**: Apache License 2.0
**Compatibility**: Not backward-compatible with v2.0.0 — requires clean deployment

---

## Highlights

### Table Partitioning

Enterprise-grade partitioning for scalability and maintenance:

| Table | Partitioning | Details |
|-------|-------------|---------|
| ENTITIES | LIST(ENTITY_TYPE) + RANGE(CREATED_AT) | 6 list × 7 time = 42 subpartitions |
| ENTITY_EDGES | REFERENCE | Inherits ENTITIES layout via FK |
| KNOWLEDGE_META | REFERENCE | Inherits ENTITIES layout via FK |
| HARNESS_META | REFERENCE | Inherits ENTITIES layout via FK |
| ENTITY_EMBEDDINGS | REFERENCE | Inherits ENTITIES layout via FK |
| ENTITY_TAGS | REFERENCE | Inherits ENTITIES layout via FK |
| AGENT_SESSION | LIST(IS_ACTIVE) + RANGE(START_TIME) | ROW MOVEMENT enabled |
| ENTITY_ACCESS_LOG | RANGE(ACCESS_TIME) + HASH(AGENT_ID) | 4 hash buckets |
| TASK_PLANS | LIST(STATUS) + RANGE(CREATED_AT) | ROW MOVEMENT enabled |
| TASK_STEPS | REFERENCE | Inherits TASK_PLANS layout via FK |

9 non-partitioned tables: AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TAGS, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, SYSTEM_CONFIG, SYSTEM_USERS.

### Composite Primary Keys & Reference Partitioning

ENTITIES PK changed from `(ENTITY_ID)` to `(ENTITY_ID, ENTITY_TYPE)`, enabling reference partitioning on all child tables. Denormalized columns added for FK alignment:

- `ENTITY_EDGES.SOURCE_TYPE` — matches source entity's ENTITY_TYPE
- `KNOWLEDGE_META.ENTITY_TYPE` — defaults to 'KNOWLEDGE'
- `HARNESS_META.ENTITY_TYPE` — defaults to 'HARNESS_TEMPLATE'
- `ENTITY_EMBEDDINGS.ENTITY_TYPE` — matches parent entity
- `ENTITY_TAGS.ENTITY_TYPE` — matches parent entity
- `TASK_STEPS.PLAN_STATUS` — matches parent TASK_PLANS.STATUS

Global unique constraints (`UK_ENTITIES_ID`, `UK_EDGES_ID`, `UK_TASK_PLANS_ID`, `UK_TASK_STEPS_ID`, `UK_ACCESS_LOG_ID`) allow single-column FK references from non-partitioned tables.

### Property Graph API

Full `graph_api.py` module powered by Oracle `GRAPH_TABLE` SQL operator against `ORACLE_MEMORY_GRAPH`:

| Function | Description |
|----------|-------------|
| `get_neighbors()` | Outgoing/incoming/both neighbor traversal with edge filtering |
| `get_reachable()` | Multi-hop reachability (1-N hops) |
| `get_shortest_path()` | Shortest path between two entities |
| `find_similar_entities()` | Graph-structure-based similarity |
| `get_entity_context()` | Full entity neighborhood with type/edge breakdown |
| `get_subgraph()` | Extract subgraph for visualization (with intermediate nodes) |
| `graph_search()` | GRAPH_TABLE-powered entity search |
| `find_communities()` | Hub detection by connection count |
| `get_graph_stats()` | Graph analytics (vertices, edges, degree distribution) |

---

## Breaking Changes from v2.0.0

### Schema

| v2.0.0 | v2.1.0 | Impact |
|--------|--------|--------|
| `ENTITIES` PK `(ENTITY_ID)` | `(ENTITY_ID, ENTITY_TYPE)` | All FK references updated |
| `ENTITY_EDGES` PK `(EDGE_ID)` | `(EDGE_ID, SOURCE_ID)` | Added `SOURCE_TYPE` column |
| `TASK_PLANS` PK `(PLAN_ID)` | `(PLAN_ID, STATUS)` | Added `PLAN_STATUS` to TASK_STEPS |
| Column `NAME` | `TITLE` | All entity tables |
| Column `PRIORITY` | `IMPORTANCE` | ENTITIES, TASK_PLANS |
| Column `TAGS` (JSON) | Separate `ENTITY_TAGS` + `TAGS` tables | Normalized |
| Column `METADATA` (JSON) | Removed | Use extension tables |
| Column `ACCESSIBLE_TO` (JSON) | Removed | Access by VISIBILITY only |
| `ENTITY_ID` type `NUMBER` | `VARCHAR2(64)` | Generated via `RAWTOHEX(SYS_GUID())` |

### Python API

- All `entity_id` parameters changed from `int` to `str`
- `execute_insert_returning_id()` returns `str` not `int`
- `create_memory()`: `name` → `title`, `priority` → `importance`, `tags`/`metadata`/`accessible_to` removed; added `summary`, `source_agent`
- `create_knowledge()`: added `domain`, `topic`, `difficulty`; tag/edge functions added
- `add_step()`: now requires `plan_status` parameter
- New module: `graph_api.py`

### PL/SQL

- `JSON_OBJECT` uses `VALUE` keyword instead of `:` (bind variable conflict in PL/SQL)
- ID generation: `RAWTOHEX(SYS_GUID())` instead of sequences
- `AGENT_SESSION`, `TASK_PLANS`, `TASK_STEPS`: ROW MOVEMENT enabled for partition key updates

---

## New Features

- **Property Graph API** — 9 Python functions for graph traversal and analytics
- **Reference Partitioning** — Child tables automatically co-located with parent entities
- **GRAPH_TABLE SQL** — Standard SQL interface to property graph queries
- **JSON Relational Duality Views** — `MEMORY_DV`, `KNOWLEDGE_DV` with composite `_id` and nested subqueries
- **KNOWLEDGE_REVIEW_JOB** — Daily spaced-repetition review scheduling
- **Viz Server Graph Endpoints** — `/api/graph/stats`, `/api/graph/neighbors`, `/api/graph/context`

---

## Bug Fixes

- Fixed `ORA-14402` on AGENT_SESSION status update (ROW MOVEMENT)
- Fixed `ORA-02270` on FK references to partitioned tables (global unique constraints)
- Fixed `ORA-40607` in Duality Views (composite PK columns must all be selected)
- Fixed `ORA-40983` in GRAPH_TABLE COLUMNS (only declared graph properties allowed)
- Fixed `ORA-40611` in Duality Views (single table per FROM clause; use scalar subqueries for joins)
- Fixed login page `Network error` (fetch credentials + JSON response instead of 302)
- Fixed `RAWTOHEX(SYS_GUID())` vs `TO_CHAR(SYS_GUID(),...)` (BINARY type incompatibility)

---

## Test Results

```
Oracle Memory System v2.1.0 - Full Test Suite
============================================================
  Connection:  6/6 PASS
  Memory:      8/8 PASS
  Knowledge:   8/8 PASS
  Agent:       8/8 PASS
  Graph:       8/8 PASS
  Harness:     6/6 PASS
  Security:    5/5 PASS

Overall: 49/49 ALL PASSED
```

---

## File Inventory

```
├── CHANGELOG.md
├── LICENSE
├── NOTICE
├── README.md
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
│   └── visualization.md
└── scripts/
    ├── deploy/
    │   ├── 1_schema.sql    (19 tables, 32 indexes, 1 graph, 2 duality views)
    │   ├── 2_api.sql       (4 PL/SQL packages)
    │   ├── 3_jobs.sql      (7 scheduler jobs)
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
    │   └── task_plan_api.py
    └── tests/
        ├── __init__.py
        ├── test_all.py
        ├── test_agent.py
        ├── test_connection.py
        ├── test_graph.py
        ├── test_harness.py
        ├── test_knowledge.py
        ├── test_memory.py
        └── test_security.py
```

---

## Upgrade from v2.0.0

No migration path. Drop all tables and redeploy:

```bash
sql openclaw/hermes@//host:1521/service @scripts/deploy/1_schema.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/2_api.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/3_jobs.sql
sql openclaw/hermes@//host:1521/service @scripts/deploy/4_harness_templates.sql
```

All v2.0.0 data will be lost. Export before upgrading if needed.
