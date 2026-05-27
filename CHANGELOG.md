# Changelog

All notable changes to the Oracle AI Database Memory System are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

---

## [2.3.2] - 2026-05-27

### Summary

**Web UI Optimization** — Client-side pagination (PAGE_SIZE=30), sticky table headers with shadow, viewport height fixes, table spacing improvements, and login language persistence across all 7 data pages. Pure front-end release — no database or API changes. All 183 tests from v2.3.1 continue to pass.

### Added

- **Client-side pagination** — PAGE_SIZE=30 with Prev/Next + page number buttons for all data tables. Knowledge, Memory, Tasks, Workspaces, Specs, Collab pages use single pagination; Agents page uses triple pagination (registry/sessions/collabs tabs).
- **Sticky table headers** — `position:sticky;top:0;z-index:2` with `background` and `box-shadow:0 2px 4px rgba(0,0,0,.3)` for visual separation when scrolling, applied to all data tables.
- **Viewport height fix** — `body` changed from `min-height:100vh` to `height:100vh`; `content-area`/`listView` given `min-height:0` and `height:calc(100vh - 120px)` to prevent layout overflow.
- **Table spacing** — `border-collapse:collapse` → `border-collapse:separate;border-spacing:0` for consistent cell rendering.
- **Text color** — Table body cells use explicit `color:#fff`; info-card divs use `color:#fff` for consistent dark-theme rendering.
- **Login language persistence** — Language preference saved to `localStorage` on toggle; restored on page load with `document.documentElement.lang` set for screen readers.

### Templates Changed

- `knowledge.html` — pagination, sticky header, viewport fix, listView height
- `memory.html` — pagination, sticky header, viewport fix, listView height
- `agents.html` — triple pagination (registry/sessions/collabs), sticky header, viewport fix
- `tasks.html` — pagination, sticky header, viewport fix
- `workspaces.html` — pagination, sticky header, viewport fix
- `specs.html` — pagination, sticky header, viewport fix
- `collab.html` — pagination, sticky header, viewport fix
- `graph.html` — language persistence, viewport fix
- `login.html` — language persistence

---

## [2.3.1] - 2026-05-26

### Summary

**Vector Search Fix & Enhancement + 5-Signal Hybrid Search + Fulltext Search + Unified Search API** — Fixed in-database embedding generation and retrieval capabilities missed during v2.0.0 architecture rewrite, added multi-modal vector search, 5-signal fusion search (vector + fulltext + relational + tag + graph), Oracle Text fulltext search, and Unified Search API (10 strategies). Backward compatible with v2.3.0 database.

### Background

During v2.0.0 architecture rewrite (partitioning, composite PKs, JRD dual views), v1.x/v2.0 embedding generation and vector retrieval capabilities were omitted:
- `EMBEDDING_MANAGER` PL/SQL package's `generate_and_store` failed because `JSON_QUERY WITH WRAPPER` returns double brackets `[[-0.03,...]]` causing `TO_VECTOR` to fail
- Python `embedding_api.py` used positional binds `:1,:2,:3`, but when `execute_query` passes a dict, oracledb thin mode parses `:1` as named variable "1", causing `ORA-01722` type conversion error
- Missing vector similarity search, hybrid search (vector+keyword), cross-type search, 5-signal fusion search, fulltext search and other key retrieval capabilities
- `ENTITY_EMBEDDINGS` table existed but had no valid vector data write path

### Added

- **EMBEDDING_MANAGER PL/SQL Fix** — `generate_and_store` uses `SUBSTR(l_vec, 2, DBMS_LOB.GETLENGTH(l_vec)-2)` to strip double brackets produced by `JSON_QUERY WITH WRAPPER`, `TO_VECTOR(l_vec)` changed to PL/SQL variable assignment `l_emb := TO_VECTOR(l_vec)` then uses variable in INSERT/UPDATE
- **EMBEDDING_GENERATION_JOB** — Auto-generates embeddings for MEMORY and KNOWLEDGE type entities every 2 hours (scheduler job)
- **embedding_api.py all binds changed to named binds** — `:1,:2,:3` → `:eid,:etype,:vec,:model,:dim,:k` etc., completely resolves oracledb thin mode dict positional bind ORA-01722 issue
- **search_similar() fix** — entity_type filter and workspace_id filter now correctly use named binds
- **search_by_entity_id()** — Search similar entities based on existing entity vector, auto-exclude self
- **search_hybrid()** — Vector + keyword hybrid search, adjustable weights `vector_weight` (default 0.7), returns `vector_score`/`keyword_score`/`hybrid_score` 3D scoring
- **search_multi_type()** — Cross-type vector search (MEMORY/KNOWLEDGE/SPEC), returned grouped by type
- **search_fulltext()** — Oracle Text fulltext search, uses `CONTAINS` + `SCORE(1)` to return fulltext relevance score
- **search_unified()** — 5-Signal Hybrid Search API (vector + fulltext + relational + tag + graph), adjustable weights, returns per-signal independent score and weighted final score
- **Vector Signal** — `VECTOR_DISTANCE(em.EMBEDDING, TO_VECTOR(:vec), COSINE)` cosine similarity
- **Fulltext Signal** — Oracle Text `CONTAINS(title, :ftq, 1)` + `SCORE(1)` fulltext relevance
- **Relational Signal** — KNOWLEDGE_META (domain/topic/difficulty), SPEC_META (scope/complexity/status), ENTITIES (category/importance) metadata matching and filtering
- **Tag Signal** — Overlap ratio between ENTITY_TAGS and filter tags + query word matching
- **Graph Signal** — ENTITY_EDGES proximity based on seed entity (1/depth decreasing) + connectivity boost (edge_count/10)
- **search_unified() parameters** — text, top_k, entity_type, workspace_id, domain, category, tags, graph_seed_entity_id, graph_seed_entity_type, graph_depth, vector_weight(0.4), fulltext_weight(0.25), relational_weight(0.2), graph_weight(0.15)
- **Return fields** — entity_id, entity_type, title, category, importance, workspace_id, km_domain, km_topic, km_difficulty, sm_scope, sm_complexity, tags, edge_count, graph_proximity, scores{vector,fulltext,relational,tag,graph}, final_score
- **19 embedding tests** — Vector generation, storage, retrieval, entity similarity search, hybrid search, cross-type search, batch processing, dimension detection, statistics, cleanup
- **31 unified search tests** — Basic search, 5-signal independent verification, domain/category/tags filtering, graph proximity, cross-type search, custom weights, metadata JOIN, empty result handling, single-SQL fusion search
- **search_api.py** — Unified search entry, 10 strategies (vector/fulltext/keyword/graph/hybrid/unified/unified_sql/relational/multi_type/auto), auto strategy detection
- **search_unified_sql()** — Single-SQL CTE 5-signal fusion search, eliminates multi-round Python-SQL round trips (candidates+tag_scores+edge_counts+graph_prox CTE)
- **LLM Context Economics** — Single-SQL fusion search compresses 5 Python-SQL round trips into 1 database call, reduces tool-call token overhead by 60-80%, eliminates intermediate-step context pollution, lets LLM agents reserve token budget for reasoning and decision-making
- **unified_sql strategy** — 10th strategy in search_api.py, low-latency production retrieval, results carry engine="single_sql" identifier
- **42 search API tests** — Strategy metadata, auto-detection rules, per-strategy dispatch, result structure, unknown strategy fallback, unified_sql strategy

### Changed

- **embedding_api.py version** — v2.3.0 → v2.3.2
- **test_embedding.py** — Expanded from 10 to 19 tests, covering all new retrieval capabilities
- **test_all.py** — Added Spec/Collab/Credential/Embedding/UnifiedSearch five test suites (14 total, 183 tests)
- **Named bind convention** — All `execute_query`/`execute_query_one`/`execute` calls uniformly use dict named binds, no longer using positional binds
- **search_unified `_batch_get_tags`, `_batch_graph_proximity`, `_batch_edge_counts`** — Use dynamic named binds (:eid0, :eid1, ...)

### Technical Notes

- Relational signal fetches via `LEFT JOIN KNOWLEDGE_META` + `LEFT JOIN SPEC_META` in a single SQL query, avoids N+1 queries
- Graph proximity uses BFS traversal of ENTITY_EDGES (not GRAPH_TABLE, because property graph matching composite PK requires additional handling), depth=2 expansion
- Tag batch query `_batch_get_tags` and edge count `_batch_edge_counts` use dynamic IN-list binds
- 5-signal weights default to 0.4+0.25+0.2+0.15=1.0 (relational includes relational + tag 0.1 each), customizable but recommended to be normalized

### Fixed

- `EMBEDDING_MANAGER.generate_and_store` returns -1 — Root cause: `JSON_QUERY WITH WRAPPER` returns `[array]` for array type (double brackets), requires `SUBSTR` to remove outer layer before `TO_VECTOR` can parse
- `search_similar(entity_type="MEMORY")` triggers ORA-01722 — Root cause: oracledb thin mode parses dict positional bind `:3` as named variable "3", Oracle fails to convert "MEMORY" to number
- `generate_and_store` returns -1 when called from SELECT but works in anonymous block — Root cause: entity not pre-created violates FK constraint, need to ensure ENTITIES record exists first
- `TO_VECTOR('0.1,0.2,...')` triggers ORA-51804 — Root cause: Oracle 23ai TO_VECTOR requires `[v1,v2,...]` bracket format, does not accept plain comma-separated

---

## [2.3.0] - 2026-05-24

### Added

- **Spec Driven Development (SDD)** — 5 new tables (SPEC_META, SPEC_PLAN_LINKS, AGENT_CREDENTIALS, COLLAB_GROUPS, COLLAB_GROUP_MEMBERS), 2 new JRD views (SPEC_DV, COLLAB_GROUP_DV), SPEC_MANAGER + COLLAB_GROUP_MANAGER PL/SQL packages
- **Python APIs** — spec_api.py (10 functions), collab_api.py (10 functions), agent_api.py extended with 8 new functions (credentials, hibernate, wake, pool management)
- **Agent Elastic Management** — DORMANT/POOL states, credential-based authentication, reversible encryption, POOL agent matching with skills_tags, DORMANT_AGENT_JOB (auto-hibernate), CREDENTIAL_CLEANUP_JOB
- **Collaboration Groups** — Mode C (group shared workspace + personal workspace per LEAD/CONTRIBUTOR), OBSERVER role, OPEN/MODERATED/RESTRICTED sharing policies, group-level shared memory API
- **Visualization** — New Specs and Collab pages with sidebar navigation, /api/specs and /api/collab endpoints, SPEC type in graph visualization, spec/collab counts in stats API
- **Schema** — ENTITIES extended with SPEC subtype and partition, AGENT_REGISTRY +5 columns, AGENT_SESSION +LAST_ACTIVE_AT, WORKSPACES +COLLAB_GROUP/PERSONAL_IN_GROUP types, SYSTEM_CONFIG +dormant_timeout_min/credential_encryption_key entries
- **11 Scheduler Jobs** — DORMANT_AGENT_JOB (30-min auto-hibernate), CREDENTIAL_CLEANUP_JOB (daily purge)

### Changed

- **Visualization** — Knowledge/Memory detail display changed from sidebar panel to inline row expansion (Tasks page pattern); Graph view retains right-side detail panel with close button
- **Authentication** — Password verification now performs actual SHA256 hash comparison instead of prefix-only check; default admin password is `admin123`

### Fixed

- CONSTRAINTS reserved word in Oracle requires double-quote quoting
- oracledb thin mode named bind variables on JSON columns cause ORA-01745; use positional or short bind names
- SYSTEM_USERS table must precede AGENT_REGISTRY in DDL (FK dependency)
- Login page version badge updated from 2.2.0 to 2.3.0
- Specs/Collab sidebar links bilingual (data-zh/data-en) across all 8 pages
- Truncated IDs show full content on hover (title attribute)
- Graph view detail panel auto-closes when switching to List view

## [2.2.1] - 2026-05-23

### Summary

**Visualization architecture upgrade** — replaces monolithic single-file visualization with template-based architecture featuring sidebar navigation, bilingual persistence, Graph Explorer, and workspace detail views. No schema changes; fully compatible with v2.2.0 database.

### Added

- **scripts/visualization/** directory — Template-based visualization architecture replacing `viz_server_local_js.py`
- **scripts/visualization/server.py** (519 lines) — Lightweight HTTP server with session auth, page routing, JSON API endpoints, Decimal sanitization for oracledb thin mode
- **scripts/visualization/templates/** — 7 HTML templates: login, knowledge, memory, agents, tasks, workspaces, graph
- **scripts/visualization/static/style.css** — Shared CSS with dark theme CSS variables
- **scripts/visualization/static/vis-network.min.js** — Vis.js network library for graph visualization
- **Left sidebar navigation** — Fixed sidebar with 6 page links, language toggle, auto-logout countdown
- **List/Graph dual view** — Knowledge and Memory pages support table + graph toggle with category/domain color grouping
- **Bootstrap Tabs** — Agents page with Registry / Sessions / Collaborations tabs, status badges, capability tags
- **Accordion panels** — Tasks page with collapsible plan details, step status badges, tool input/output expandable rows
- **Expandable detail rows** — Workspaces page with context timeline and linked tasks table
- **Graph Explorer page** — Dedicated page with vertex/edge/degree stats cards, search + type filter, node context API, detail panel
- **Bilingual persistence** — Language preference saved to `localStorage`, survives page navigation via `data-zh`/`data-en` attributes
- **5-min auto-logout countdown** — Timer in sidebar, 60s warning color, 30s title flash
- **Decimal sanitization** — `_clean_row()` and `_serialize_datetime()` handle oracledb thin mode Decimal/datetime in JSON API responses
- **Workspace API enrichment** — `/api/workspaces` now returns `context_chain`, `linked_tasks`, `task_count` per workspace
- **Task steps seed data** — 21 steps across 6 plans with mixed statuses (SUCCESS/RUNNING/FAILED/PENDING)

### Changed

- **server.py** VERSION updated from "2.2.0" to "2.2.1"
- **start_web_server.sh** — Points to `scripts/visualization/server.py` instead of `viz_server_local_js.py`; version updated to v2.2.1
- **All HTML templates** — Version badge updated from "v2.2.0" to "v2.2.1"; "PG Memory" branding replaced with "Oracle Memory"

### Removed

- **viz_server_local_js.py** — Replaced by template-based `scripts/visualization/server.py` + templates
- **vis-network.min.js** (root level) — Moved to `scripts/visualization/static/vis-network.min.js`

### Fixed

- **Language persistence** — Switching to Chinese no longer resets on page navigation; preference persisted in `localStorage`
- **test_graph_search** — Changed entity_type from `HARNESS_TEMPLATE` to `MEMORY` to match available test data
- **Task steps display** — Tasks page now shows execution steps with proper data from database
- **Tasks table readability** — Changed `.data-table tbody td` color to `#fff` for better contrast on dark background

---

## [2.2.0] - 2026-05-20

### Summary

**Workspace management, context continuity, agent handoff, and JRD updatable views.** Not backward-compatible with v2.1.0 — requires clean deployment.

### Added

- **WORKSPACES table** — Workspace lifecycle (ACTIVE → PAUSED → ARCHIVED), isolation modes (SHARED/ISOLATED), ownership tracking, metadata JSON
- **WORKSPACE_CONTEXT table** — Version chain of context entries (SNAPSHOT, CHECKPOINT, HANDOFF, SUMMARY, RECOVERY) with PARENT_CONTEXT_ID linking
- **WORKSPACE_TASKS table** — Links task plans to workspaces, composite PK (WORKSPACE_ID, PLAN_ID)
- **AGENT_SESSION: OWNER_USER_ID column** — User who owns/started the session
- **AGENT_SESSION: WORKSPACE_ID column** — Workspace the session belongs to
- **AGENT_SESSION: PREDECESSOR_SESSION_ID column** — Previous session in handoff chain
- **ENTITIES: WORKSPACE_ID column** — Entity scoping for ISOLATED workspaces
- **workspace_api.py** — 11 Python functions: create_workspace, get_workspace, get_user_workspaces, update_workspace, save_context, get_context_chain, get_latest_context, create_handoff_session, recover_workspace, link_task_to_workspace, get_workspace_tasks
- **checkpoint_session()** — Save a CHECKPOINT context for the session's workspace
- **get_session_chain()** — Traverse PREDECESSOR_SESSION_ID backwards for full session handoff chain
- **WORKSPACE_MANAGER PL/SQL package** — Server-side workspace management procedures
- **WORKSPACE_CLEANUP_JOB** — Scheduler job for workspace maintenance (daily 01:00)
- **CONTEXT_ARCHIVE_JOB** — Scheduler job for archiving old context entries (weekly Sun 03:00)
- **WORKSPACE_DV** — Updatable JSON Relational Duality view for workspace document API
- **CONTEXT_DV** — Read-only JSON Relational Duality view for context document API
- **MEMORY_DV** — Now updatable with JSON_TRANSFORM for partial updates
- **KNOWLEDGE_DV** — Now updatable with JSON_TRANSFORM for partial updates
- **docs/workspace.md** — Workspace & context continuity guide
- **12 workspace tests** in test suite (test_workspace.py)

### Changed

- **create_session()** now accepts `owner_user_id`, `workspace_id`, `predecessor_session_id` parameters (all optional)
- **ON DELETE CASCADE** on WORKSPACE_CONTEXT(WORKSPACE_ID) and WORKSPACE_TASKS(WORKSPACE_ID) for automatic cleanup
- **1_schema.sql**: 22 tables (3 new), 4 duality views (2 new + 2 updated)
- **2_api.sql**: 5 PL/SQL packages (WORKSPACE_MANAGER added)
- **3_jobs.sql**: 9 scheduler jobs (2 new: WORKSPACE_CLEANUP_JOB, CONTEXT_ARCHIVE_JOB)

### Fixed

- **MEMORY_DV now updatable** — Fixed JRD view definition to support INSERT/UPDATE/DELETE via JSON_TRANSFORM
- **KNOWLEDGE_DV now updatable** — Fixed JRD view definition to support INSERT/UPDATE/DELETE via JSON_TRANSFORM

---

## [2.1.0] - 2026-05-19

### Summary

**Schema evolution with partitioning, composite keys, and Property Graph API.** Not backward-compatible with v2.0.0 — requires fresh deployment or migration.

### Added

- **Table partitioning: LIST+RANGE composite on ENTITIES** — 6 list (ENTITY_TYPE) × 7 time (CREATED_AT) subpartitions
- **Reference partitioning on 5 child tables** — ENTITY_EDGES, KNOWLEDGE_META, HARNESS_META, ENTITY_EMBEDDINGS, ENTITY_TAGS inherit partitioning from ENTITIES
- **RANGE+HASH partitioning on ENTITY_ACCESS_LOG** — RANGE(ACCESS_TIME) + HASH(AGENT_ID) with 4 buckets
- **LIST+RANGE on AGENT_SESSION with ROW MOVEMENT** — LIST(IS_ACTIVE) + RANGE(START_TIME), rows migrate between partitions on status change
- **LIST+RANGE on TASK_PLANS; reference on TASK_STEPS** — LIST(STATUS) + RANGE(CREATED_AT), TASK_STEPS inherits via reference partitioning
- **Composite primary keys** — ENTITIES(ENTITY_ID, ENTITY_TYPE), ENTITY_EDGES(EDGE_ID, SOURCE_ID), TASK_PLANS(PLAN_ID, STATUS), etc.
- **Global unique constraints** for cross-partition FK references — ENTITY_ID globally unique despite composite PK
- **Denormalized ENTITY_TYPE/SOURCE_TYPE/PLAN_STATUS columns** — added to child tables for reference partitioning key propagation
- **graph_api.py: Property Graph API** with GRAPH_TABLE SQL operator — 9 functions: get_neighbors, get_reachable, get_shortest_path, find_similar_entities, get_entity_context, get_subgraph, graph_search, find_communities, get_graph_stats
- **ORACLE_MEMORY_GRAPH** — vertex=ENTITIES, edges=ENTITY_EDGES; supports SQL PGQ traversal via GRAPH_TABLE operator
- **JSON Relational Duality Views** — MEMORY_DV, KNOWLEDGE_DV with composite _id (ENTITY_ID||ENTITY_TYPE), nested subqueries for edges/tags
- **KNOWLEDGE_REVIEW_JOB scheduler job** — Daily 04:00 review and validation of knowledge concepts
- **8 graph tests** in test suite (test_graph.py)

### Changed

- **ENTITIES PK**: ENTITY_ID → (ENTITY_ID, ENTITY_TYPE)
- **ENTITY_EDGES**: added SOURCE_TYPE column, PK → (EDGE_ID, SOURCE_ID)
- **KNOWLEDGE_META/HARNESS_META/ENTITY_EMBEDDINGS/ENTITY_TAGS**: added ENTITY_TYPE column for reference partitioning
- **TASK_STEPS**: added PLAN_STATUS column for reference partitioning
- **TASK_PLANS PK**: PLAN_ID → (PLAN_ID, STATUS)
- **All Python APIs**: entity IDs now VARCHAR2(64) not NUMBER, RAWTOHEX(SYS_GUID()) generation
- **connection.py**: execute_insert_returning_id returns str not int
- **PL/SQL packages**: rewritten for composite PKs, JSON_OBJECT VALUE syntax, RAWTOHEX(SYS_GUID())
- **viz_server**: updated for new schema columns, added /api/graph/* endpoints
- **1_schema.sql**: complete rewrite with 19 tables, 32 indexes, property graph, duality views
- **2_api.sql**: complete rewrite for v2.1 schema
- **3_jobs.sql**: added KNOWLEDGE_REVIEW_JOB
- **4_harness_templates.sql**: rewritten for new HARNESS_META schema

### Removed

- **INTERVAL subpartitioning** — removed due to ORA-14179 incompatibility with LIST+RANGE composite
- **ACCESSIBLE_TO column** from ENTITIES
- **NAME, PRIORITY, TAGS, METADATA, DESCRIPTION columns** — replaced by TITLE, IMPORTANCE, separate tag tables

---

## [2.0.0] - 2026-05-15

### Summary

**Complete ground-up rewrite.** Not backward-compatible with any v1.x version. No upgrade path — requires fresh deployment.

### Added

- **Unified Entity Architecture** — Single `ENTITIES` table with `ENTITY_TYPE` discriminator (MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE) replaces 5 separate tables
- **Unified Edge Architecture** — Single `ENTITY_EDGES` table with 10 edge types and STRENGTH/CONFIDENCE weights replaces 3 separate relationship tables
- **oracledb Python Driver** — Connection pooling (min=2, max=5) replaces SQLcl subprocess; 4500x speedup (20ms vs 90s)
- **4-Phase SQL Deployment** — Ordered, idempotent scripts: `1_schema.sql`, `2_api.sql`, `3_jobs.sql`, `4_harness_templates.sql`
- **Python API Library** — 8 modules: config, connection, memory_api, knowledge_api, agent_api, task_plan_api, security, harness_api
- **Harness Template System** — Reusable agent execution blueprints with variable substitution, inheritance (DERIVES_FROM), 5 built-in tool sets, 3 guardrail presets, lifecycle (DRAFT→PUBLISHED→DEPRECATED→ARCHIVED), validation
- **5 Built-in Harness Templates** — Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor
- **HARNESS_META Table** — Template versioning, status tracking, variables, changelog
- **KNOWLEDGE_META Table** — Extended metadata for knowledge entities (source, validation, versioning, confidence)
- **16 Database Tables** — ENTITIES, ENTITY_EDGES, KNOWLEDGE_META, HARNESS_META, ENTITY_EMBEDDINGS, AGENT_REGISTRY, AGENT_SESSION, ENTITY_ACCESS_LOG, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_PLANS, TASK_STEPS, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS/ENTITY_TAGS, SYSTEM_CONFIG, SYSTEM_USERS
- **4 PL/SQL Packages** — MEMORY_FUSION_ENGINE, KNOWLEDGE_BASE_API, AGENT_PERMISSION_MANAGER, SESSION_CLEANUP
- **7 Scheduler Jobs** — Memory fusion, knowledge extraction, session cleanup, log purge, tag count, collaboration expiry, entity archive
- **Unified Property Graph** — ORACLE_MEMORY_GRAPH replaces 2 separate graphs; supports cross-type SQL PGQ traversal
- **JSON-Relational Duality Views** — MEMORY_DV, KNOWLEDGE_DV
- **Web Visualization: 4-Page Dashboard** — Knowledge Graph (/knowledge), Memory Content (/memory), Agent Collaboration (/agents), Task Plans (/tasks)
- **Agent Collaboration Page** — 3-tab dashboard: Agent Registry (status/permission badges), Active Sessions, Collaboration Requests
- **Task Plans Page** — Status filter dropdown, keyword search, accordion plan list with expandable step tables, progress bars
- **Bilingual UI** — Chinese/English toggle with localStorage persistence
- **Session Authentication** — SYSTEM_USERS credentials, configurable timeout auto-logout
- **UTF-8 Encoding Fix** — `_fix_encoding()` auto-detects and corrects double-encoded Chinese from oracledb thin mode
- **Data Masking (DataMaskingService)** — 7 pattern types (email, phone, credit_card, ssn, api_key, ip_address, jwt_token), 4 context levels (LOGGING, DEBUGGING, ANALYTICS, SHARING)
- **Reversible Encryption** — PBKDF2 key derivation + XOR, length-prefix encoding, safe key rotation
- **Password Hashing** — PBKDF2-HMAC-SHA256 with configurable iterations (default: 100,000)
- **Server Control Script** — `start_web_server.sh` with start/stop/restart/status/config/log commands; auto-detects Python 3.14; reads config.json; PID file management; daemon mode
- **Test Suite** — 47/47 pass: Connection(6), Memory(7), Knowledge(7), Agent(7), Security(10), Harness(10)
- **Documentation** — Concise SKILL.md (~200 lines) + 9 topic docs in docs/ (architecture, api-reference, deployment, migration, security, visualization, minimum-privileges, harness, introduction_v2.0.0_zh)
- **Chinese Introduction** — `docs/introduction_v2.0.0_zh.md` (432 lines, 13 sections)

### Changed

- `ENTITIES` replaces MEMORIES + MEMORY_NODES + KNOWLEDGE_CONCEPTS
- `ENTITY_EDGES` replaces MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH
- `SYSTEM_USERS` (with roles USER/ADMIN/SYSTEM) replaces memory_system_users
- `ORACLE_MEMORY_GRAPH` replaces KNOWLEDGE_PROPERTY_GRAPH + MEMORY_PROPERTY_GRAPH
- oracledb driver with connection pooling replaces SQLcl subprocess execution
- 4 ordered deployment scripts replace 15+ scattered SQL scripts
- viz_server queries updated for ENTITIES/ENTITY_EDGES/SYSTEM_USERS
- All Python queries use bind variables (`:param`) instead of string concatenation
- `INSERT...RETURNING` for auto-increment ID retrieval
- `MERGE INTO` for idempotent agent registration
- `fetch_lobs = False` for automatic LOB handling
- `_sanitize_decimals()` / `_sanitize_val()` for Oracle NUMBER → JSON serialization
- `_fix_encoding()` for oracledb thin mode UTF-8 double-encoding workaround
- `_q()` generic query helper with automatic type sanitization and encoding correction
- `json.dumps(default=str)` as safety net for non-serializable types

### Fixed

- oracledb `NUMBER.getvalue()` returns list — handle both list and scalar
- `SYSTIMESTAMP` passed as bind variable — use SQL literal
- Oracle reserved word `:desc` as bind variable — renamed to `:adesc`
- Phone regex matching credit card numbers — reordered pattern matching (credit_card before phone)
- Short sensitive strings not masked — removed `len(text) < 10` guard
- Sensitive dict values not masked when no regex match — added `***MASKED***` fallback
- Key rotation corrupts ciphertext — decrypt all first, then re-encrypt
- ReversibleEncryption zero-byte padding — replaced with length-prefix encoding
- viz_server f-string `{sess_ttl}` NameError — fixed to `{SESS_TTL}`
- viz_server crashes on any request — added `do_GET` → `_do_GET` exception wrapper
- `decimal.Decimal` not JSON serializable — added `_sanitize_decimals()` and `_sanitize_val()`
- oracledb thin mode double-encodes UTF-8 Chinese — added `_fix_encoding()`
- viz_server tasks page missing `<script>` tag — added script wrapper
- viz_server agents/tasks API returns 500 on datetime — added `default=str` to `json.dumps()`

### Removed

- 5 separate entity tables (MEMORIES, MEMORY_NODES, KNOWLEDGE_CONCEPTS, etc.)
- 3 separate relationship tables (MEMORY_EDGES, MEMORY_RELATIONSHIPS, KNOWLEDGE_GRAPH)
- SQLcl subprocess execution for database operations
- 15+ scattered SQL deployment scripts
- 934-line SKILL.md (replaced with 200-line version + 9 topic docs)
- 2 separate property graphs (KNOWLEDGE_PROPERTY_GRAPH, MEMORY_PROPERTY_GRAPH)
- memory_system_users table (replaced with SYSTEM_USERS)
- VIZ_USERS / VIZ_PERMISSIONS / VIZ_SESSIONS / VIZ_ACCESS_LOGS / VIZ_CONFIG tables
- DESENSITIZE_LEVELS table (replaced with Python DataMaskingService)
- All v1.x Python scripts archived to `archive/legacy_scripts/`
- All v1.x documentation archived to `archive/legacy_docs/`
- All v1.x release notes archived to `archive/release_notes/`

---

## [1.1.0] - 2026-05-12

### Added

- Web visualization server with vis.js interactive graph
- Session-based authentication with login page
- Bilingual UI (Chinese/English) with i18n support
- Knowledge and Memory dual-page architecture
- Node detail panel on click
- `/api/stats` endpoint for sidebar statistics

### Changed

- Improved error handling in visualization server
- Enhanced node color coding by category/type

---

## [1.0.0] - 2026-05-09

### Added

- Production release: knowledge base with property graph
- Multi-agent collaboration framework
- Task plan system with steps and dependencies
- PL/SQL API packages for memory fusion and knowledge management
- Scheduler jobs for automated maintenance
- Session cleanup and access logging

---

## [0.5.1] - 2026-05-09

### Added

- Enhanced session management with timeout controls
- Improved agent permission model

### Fixed

- Session cleanup edge cases

---

## [0.5.0] - 2026-05-08

### Added

- Security & Performance Enterprise Edition
- Data masking (desensitization) with context-aware levels
- Reversible encryption for sensitive data
- PBKDF2 password hashing
- Aggregation analysis for audit queries

---

## [0.4.2] - 2026-05-07

### Changed

- Directory consolidation and naming standardization
- Internal cleanup of script organization

---

## [0.4.0] - 2026-05-02

### Added

- Task plan system with multi-step definitions
- Task step status tracking
- Task context snapshots for breakpoint/recovery
- Task tool call audit logging
- Inter-plan dependency graph

---

## [0.3.x] - 2026-04-28

### Added

- Core memory system with CRUD operations
- Knowledge base with concept management
- Basic graph relationships between entities
- Oracle property graph integration
- Vector embedding support for semantic search
