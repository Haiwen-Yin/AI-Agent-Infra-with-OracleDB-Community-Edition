# Changelog

All notable changes to AI Agent Infra with OracleDB are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.10.2] - 2026-07-16

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Enterprise encryption enhancement: per-Agent independent crypto keys, config.json auto-encryption on startup, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.

### Added

- **Per-Agent independent crypto keys**: Each Agent gets its own 32-byte encryption key stored in SYSTEM_CONFIG (key=agent_crypto_key:{agent_id}), distributed via admin_token at registration
- **Key rotation API**: POST /api/admin/crypto/rotate (global) and POST /api/admin/crypto/rotate/{agent_id} (per-Agent), with automatic re-encryption of affected credentials
- **Config.json auto-encryption on startup**: server.py now calls auto_encrypt_config() which encrypts database, llm.api_key, and model_routing.*_api_key sections transparently
- **encrypt_config.py CLI tool**: Unified across all 4 editions (was Oracle ENT only)
- **Portal Markdown rendering**: portal_chat.html now renders LLM responses with Markdown (headers, code blocks, lists, bold/italic, links), auto-scroll during streaming, exit button with session cleanup, auto-detection of expired sessions

### Fixed


### Changed

- config.json now encrypts database + llm + model_routing sections (was database only)
- Agent heartbeat checks crypto key version for rotation detection

---

## [3.10.1] - 2026-07-14

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Enterprise deployment enhancement: offline dependency bundling + pure Python Oracle schema deployment tool.

### Added

- **vendor/ directory**: 30 pre-downloaded Python wheels (cp314, ~12-14MB) for air-gapped deployment
- **requirements.txt**: Locked dependency versions per edition
- **install_offline.sh**: One-command offline installation (pip install --no-index --find-links vendor/)
- **verify_deps.py**: Dependency verification (version + platform compatibility checks)
- **deploy_oracle.py** (Oracle only): Pure Python schema deployer replacing SQLcl (125MB + Java). Handles PROMPT/DEFINE/&&/block terminator syntax. 200 lines, zero external dependencies beyond oracledb

### Enterprise Air-Gapped Deployment

No internet, SQLcl, or Java required. Copy ZIP to isolated network, run install_offline.sh, deploy with deploy_oracle.py.

---

## [3.10.0] - 2026-07-09

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Universal Property Graph release. Extends the graph model from entity-level adjacency to 8 functional domains, adding 30+ graph functions and 23 new edge types: knowledge causality, agent collaboration (group-scoped dynamic trust), task orchestration, skill dependencies, approval propagation, data flow, memory evolution, and loop iteration.

### Added

- **30+ graph functions** in graph_api.py across 8 domains (knowledge causal, agent collaboration, task orchestration, skill dependency, approval propagation, data flow, memory evolution, loop iteration)
- **23 new edge types**: CAUSES, CONTRADICTS, SUPERSEDES, DERIVED_FROM, DERIVED_FROM_DATA, TRUSTS, DELEGATED_TO, COMPLEMENTS_SKILL, COMMUNICATED_WITH, FEEDS_INTO, PRODUCED_ARTIFACT, CONSUMED_ARTIFACT, REQUIRES_OUTPUT_OF, REQUIRES, ENHANCES, BLOCKS, DEPENDS_ON, PROMOTED_TO, MERGED_INTO, SUPERSEDED_BY, INFORMS, CORRECTS, BUILDS_ON
- **Dynamic trust configuration** via SYSTEM_CONFIG (6 configurable values)
- **3 new API endpoints**: /api/graph/causal, /api/graph/collaboration, /api/graph/lineage
- **3 new MCP tools**: graph_causal, graph_lineage, graph_collaboration
- **Memory promotion** now writes PROMOTED_TO graph edge
- **Collab group join** now initializes TRUSTS edges

### Fixed

- Oracle ENT: memory_api.py and knowledge_api.py edition label (Community -> Enterprise)
- graph_api.py version string (v3.5.0 -> v3.10.0)

---

## [3.9.0] - 2026-07-05

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
AI Agent ecosystem connectivity release. Adds MCP Server, SSE streaming output, Human-in-the-Loop approval, Agent Protocol compatibility, and multi-model routing — connecting the system's capabilities to external AI clients and frameworks.

### Added - All Editions

- **MCP Server** (`mcp_server.py`, `mcp_server_main.py`): Exposes 10 tools (search, memory_create/search, knowledge_create/search, tool_list/invoke, graph_neighbors, loop_status, agent_list) via Model Context Protocol with stdio + SSE dual transport
- **Tool invocation** (`tool_registry.invoke_tool()`): Executes registered tools by reading INPUT_SCHEMA and making HTTP calls
- **SSE streaming output**: Web Portal chat supports token-by-token streaming via Server-Sent Events
- **Approval API** (`approval_api.py`): Unified approval queue for Human-in-the-Loop workflows
- **Approval web page** (`approvals.html`): Approval queue UI with stats and filter
- **Agent Protocol endpoints**: `POST/GET /ap/v1/agent/tasks` for benchmark tool interoperability
- **Multi-model routing** (`ModelRoutingConfig`): Configurable simple/standard/complex model selection
- **LLM configuration** (`LLMConfig`): api_url, api_key, model, max_context, stream_enabled
- **MCP configuration** (`MCPConfig`): enabled, transport, sse_port, exposed_tools
- **event_bus `_execute_mcp_call()`**: MCP call hook implementation

### Added - Database

- `APPROVAL_REQUESTS` table: Unified approval queue
- `STEP_EXECUTION_PLAN`: REQUIRES_APPROVAL, APPROVED_BY, APPROVED_AT columns
- `LOOP_META`: REQUIRE_APPROVAL column
- `TOOL_REGISTRY`: REQUIRES_APPROVAL column
- `CK_SEP_STATUS`: Added 'PAUSED' value

### Fixed - All Editions

- **ThreadingHTTPServer**: Replaced single-threaded HTTPServer with ThreadingHTTPServer — SSE streaming was blocking all other requests, causing server freeze on portal exit
- **HTTP/1.1 protocol**: Set protocol_version = HTTP/1.1 — HTTP/1.0 didn't support chunked transfer, browser buffered entire SSE response until connection closed
- **Session heartbeat**: Added /api/session/heartbeat endpoint (requires auth, updates last_access) — /api/health was public and didn't refresh session; added 120-second periodic heartbeat in all 14 HTML templates via setInterval + visibilitychange
- **_authenticate_local salt support**: Now queries salt column and computes SHA256(password + salt) when salt exists, SHA256(password) when not — Oracle SYSTEM_USERS table has no salt column, handled via try/except
- **_handle_portal_agent_release**: Added missing method that was called on portal exit but never defined, causing AttributeError crash
- **Portal auto-session on login**: Login now auto-loads most recent conversation workspace or creates a new one — previously user saw empty chat with no active session
- **Portal auto-naming**: First message in a "New Chat" workspace auto-renames it to the first 40 characters of the message
- **Portal is_current comparison**: Fixed int == str comparison — workspace_id is int in DB but str in session, wrapped with str() comparison
- **appendMessage return value**: Fixed appendMessage() not returning the bubble element — SSE pump assigned undefined.textContent causing JS error that interrupted token rendering and loadSessions()
- **SSE pump robustness**: Added finishStream() helper and .catch() error handler — ensured loadSessions() is always called even if pump fails
- **LLM streaming performance**: Changed resp.read(1) to resp.read(4096) (4KB chunks); increased max_tokens from 4096 to 8192 for reasoning-heavy models
- **Non-streaming LLM fallback**: Added reasoning_content fallback when content is empty (some models put all output in reasoning_content)
- **Approvals page JS**: Rewrote approvals.html with correct timer JS (previous sed corruption broke the entire script block with invalid variable names _alo_m/_alo_s)
- **Approvals sidebar link**: Fixed broken HTML in all 14 templates where sed inserted an unclosed <a> tag inside the icon span
- **Approvals API filter**: Fixed no-filter case returning only pending items; now always returns all items, filtered by entity_type in Python

### Fixed - Oracle only

- **4_grants.sql tablespace**: Dynamically retrieve schema owner's default tablespace via DBA_USERS.DEFAULT_TABLESPACE instead of hardcoding


---

## [3.8.0] - 2026-07-02

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Multi-Agent integration testing release. Completed full 5-phase deployment and 15-module functional test suite with zero failures. Multiple runtime bugs discovered and fixed during testing.

### Fixed - Oracle COM/ENT

- **LOOP_MANAGER package body**: Added missing `log_loop_audit` procedure implementation that was declared in the package specification but never defined in the body, causing PLS-00323 compilation error
- **DB_CRYPTO runtime**: Fixed ORA-14551 (cannot perform DML inside a query) by pre-seeding `db_crypto_master_key` and `db_crypto_key_salt` in SYSTEM_CONFIG during schema deployment instead of lazy-initializing inside a function called from SELECT
- **agent_api.py `_ensure_end_user`**: Removed hardcoded `AIADMIN.` schema prefix from `END_USER_MANAGER.ensure_end_user` call, allowing the function to resolve against the actual schema owner at runtime
- **4_grants.sql**: Fixed `AGENT_API` user creation to dynamically retrieve the schema owner's default tablespace via `DBA_USERS.DEFAULT_TABLESPACE` instead of hardcoding `USERS` (which may not exist in all environments)

### Tested - Oracle COM/ENT

- **15-module functional test suite**: All 15 tests passed (Memory CRUD, Knowledge Base, Agent Messaging, Collaboration Group, Loop Lifecycle, Graph Operations, Branch & Workspace, Spec Management, Tool Registry, Monitor API, Event Bus, Task Plan API, Skill API, Agent API, LLM Integration)
- **4 registered Business Agents**: AGENT_001–004 registered, collaboration group created with coordinator and members
- **0 invalid database objects**: All PL/SQL packages, package bodies, and views compile successfully
- **Existing test suites**: `test_loop_api.py` (16 tests) and `test_admin_agent.py` (18 tests) all pass

---

## [3.7.5] - 2026-06-28

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Bug fix and code quality release for Oracle editions. Fixes 5 issues found during v3.7.4 code review.

### Fixed - Oracle COM/ENT

- **orchestrator.py**: `execute_step_with_retry` now queries actual TASK_STEPS and checks LOOP_RUNS status before marking SUCCESS
- **event_bus.py**: Webhook execution adds retry with exponential backoff and configurable timeout; Script execution replaces `shell=True` with safe `shlex.split()` argument list
- **message_api.py**: Soft-delete changed from `STATUS='FAILED'` to `STATUS='DELETED'`; CK_CM_STATUS constraint updated in schema

### Fixed - Oracle ENT only

- **Data Grants**: Added missing `event_log_access`, `event_sub_own`, `capability_own` to `6_deep_sec_policy.sql`
- **Data Grant syntax**: Fixed `CREATE DATA GRANT` to `CREATE OR REPLACE DATA GRANT AS SELECT` for Oracle 23.26.2 compatibility
- **CK_CM_STATUS**: Fixed constraint in deployed database from `FAILED` to `DELETED`

---

## [3.7.4] - 2026-06-26

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
6 expansion directions: Agent Communication Protocol, Multi-Agent Orchestration, Event-Driven Architecture, Advanced Memory Management, Observability, and Tool Ecosystem.

### Added - All Editions

- **Agent Communication Protocol** — COLLAB_MESSAGES table + message_api.py (15 functions): send/reply/broadcast/thread messages with priority levels, attachment references, and unread tracking. COLLAB_MESSAGE_MANAGER PL/SQL package.
- **Multi-Agent Orchestration** — orchestrator.py: DAG resolution (topological sort), sequential/parallel execution groups, fan-out (distribute to multiple agents) and fan-in (CONSENSUS/BEST_OF_N/CONCATENATE/FIRST strategies). STEP_RETRY_POLICY (exponential backoff, fallback actions). STEP_EXECUTION_PLAN table.
- **Event-Driven Architecture** — EVENT_LOG + EVENT_SUBSCRIPTIONS tables. event_bus.py: publish/subscribe, agent capability discovery via AGENT_CAPABILITY_INDEX, match_skill_to_agents, recommend_agents. LOOP_HOOKS execution engine: WEBHOOK/SCRIPT/NOTIFICATION/MCP_CALL hook types.
- **Advanced Memory Management** — consolidate_branch_memories(), promote_to_semantic(), merge_knowledge() (OVERWRITE/UNION/WEIGHTED), detect_knowledge_conflicts(), reindex_entity(), queue_reindex().
- **Observability** — Distributed tracing (TRACE_ID on 6 tables). trace_api.py: init_trace, get_trace_tree, get_trace_summary. monitor_api.py: get_system_overview, get_agent_health, get_stalled_agents. monitor.html dashboard page. TRACE_MANAGER and MONITOR_MANAGER PL/SQL packages. ALERT_EVALUATOR_JOB for rule evaluation.
- **Tool Ecosystem** — OpenAPI spec auto-import into harness templates. TOOL_REGISTRY table (versioned, typed tool definitions). TOOL_CHAINS + TOOL_CHAIN_STEPS for DAG tool composition. tool_registry.py (14 functions).
- 25 new API endpoints for messages, monitoring, traces, tools, events, orchestration.
- 3 new scheduler jobs: DAG_RESOLVER_JOB (5 min), HOOK_EXECUTOR_JOB (1 min), ALERT_EVALUATOR_JOB (5 min).

### Changed - All Editions

- Schema: +9 tables, +6 TRACE_ID columns

---

## [3.7.3] - 2026-06-23

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Deployment fix release — resolves schema creation order issues, hardcoded schema owner names, configuration priority, and embedding model auto-detection discovered during fresh deployment testing.

### Fixed - Oracle COM/ENT

- **CONTEXT_BRANCHES FK ordering** — Removed inline FK constraints referencing not-yet-created tables (WORKSPACES, WORKSPACE_CONTEXT, AGENT_REGISTRY); added via ALTER TABLE after parent tables exist
- **LOOP_RUNS self-reference** — Moved UK_LOOP_RUNS_ID UNIQUE(RUN_ID) inline to CREATE TABLE (was added via ALTER TABLE after, causing ORA-02270 on FK_LR_PARENT_RUN self-reference)
- **LOOP_ITERATIONS partitioning** — Changed from PARTITION BY REFERENCE to PARTITION BY RANGE(STARTED_AT) to resolve incompatibility with parent table's composite subpartitioning (ORA-14661)

### Fixed - All Editions

- **Hardcoded schema owner** — 4_grants.sql and 6_deep_sec_policy.sql: replaced literal AIADMIN with `DEFINE SCHEMA_OWNER` substitution variable; connection.py: `ALTER SESSION SET CURRENT_SCHEMA` and `SET_AGENT_CONTEXT` calls now read schema name from config
- **PG RLS policy** — Replaced hardcoded `'aiadmin'` in RLS policies with psql variable `:'schema_owner'`
- **PG agent_bootstrap.py** — Changed `SET search_path TO aiadmin` to `SET search_path TO public`
- **Config priority** — Changed from Environment Variables > config.json > Defaults to config.json (encrypted) > Environment Variables > Defaults; removed hardcoded default credentials (openclaw/hermes/10.10.10.130)
- **EmbeddingConfig defaults** — Changed from hardcoded model/dimension to empty strings, forcing explicit configuration
- **SecurityConfig** — pbkdf2_iterations default 100000 → 210000
- **Embedding model auto-detection** — embedding_api.py now raises ValueError with supported model list when embedding model is not configured, instead of silently using default
- **server.py startup** — Added embedding configuration check with WARNING message on startup

---
## [3.7.2] - 2026-06-19

### Fixed — Documentation Consistency

- LOOP_MANAGER function count corrected: ~33 → ~22 (actual package spec count)
- loop_api.py description corrected: "33 functions" → "32 public API functions + private evaluation helpers"
- LOOP_CLEANUP_JOB schedule corrected: "Weekly Sunday 06:00" → "Weekly Sunday 06:00" (matches actual SQL)
- ENTITIES partition count corrected: 7 → 8 (includes SKILL partition)
- Reference-partitioned children count corrected: 6 → 8 (includes SKILL_META, LOOP_META)
- ON_START lifecycle hook added to v3.7.0 entry (was previously omitted)
- loop-engineering.md body text corrected: "four evaluation types" → "six evaluation types"
- RELEASE_NOTES v3.7.0/v3.7.1 bug fixes boundary clarified
- README project structure updated: all Python modules listed, template count corrected
- SKILL_MANAGER PL/SQL package removed from docs (not present in Community Edition 2_api.sql)

---
## [3.7.1] - 2026-06-19

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Loop Engineering Collaborative Integration** — Connects Loop Engineering with Spec, Task, Branch, Collab, and Skill modules, enabling Spec-driven loops, Task-Loop bindings, and Collaborative Loops. Also fixes session persistence, PG loop API compatibility, and adds SPEC_VALIDATION and AGGREGATE evaluation types.

### Added - Both Editions

- **Spec-Driven Loop** — Create loops from Spec acceptance criteria; SPEC_VALIDATION evaluation type validates against spec criteria
- **Task-Loop Binding** — Bind loops to task steps; step auto-completes when loop succeeds; new TASK_LOOP_BINDING table
- **Collaborative Loop** — Create parent/child loops for collaboration groups; AGGREGATE evaluation type collects child results; 2-level nesting limit
- **Branch-Isolated Loop** — Loops bound to a branch_id automatically run in branch context
- **Skill-Triggered Loop** — Skills with validation_loop metadata auto-start verification loops on acquire
- LOOP_META new columns: SPEC_ID, PARENT_LOOP_ID, COLLAB_GROUP_ID
- LOOP_RUNS new column: PARENT_RUN_ID
- TASK_STEPS new columns: LOOP_ID, STEP_COMPLETION_TYPE (MANUAL/LOOP/SPEC + WAITING_LOOP status)
- TASK_LOOP_BINDING table (BINDING_ID, STEP_ID, LOOP_ID, BINDING_TYPE, AUTO_START)
- SPEC_VALIDATION evaluation type — validates iteration against spec acceptance_criteria
- AGGREGATE evaluation type — aggregates child loop run results
- 7 new API endpoints: /api/loops/from-spec, /api/loops/collab, /api/loops/{id}/children, /api/loops/{id}/aggregation, /api/tasks/steps/{id}/bind-loop, /api/tasks/steps/{id}/loop, /api/collab/{id}/loop
- 8 new loop_api.py functions: create_loop_from_spec, create_collab_loop, create_sub_loops_for_group, aggregate_child_runs, bind_loop_to_step, get_step_loop, on_loop_run_completed, create_validation_loop_for_skill
- derive_loop_from_spec() in spec_api.py
- bind_loop_to_step(), get_step_loop() in task_plan_api.py
- create_group_loop(), get_group_loop_status() in collab_api.py
- loops.html: From Spec creation, Collab Group selector, Child Loops panel, SPEC_VALIDATION/AGGREGATE badges
- [ENT only] LOOP_AUDIT COLLAB_GROUP_ID column for collaborative audit trail
- [ENT only] log_loop_audit() enhanced with collaborative action types: SUB_LOOP_CREATED, SUB_LOOP_COMPLETED, AGGREGATION_DONE

### Fixed - Both Editions

- **Session persistence** — Added Max-Age=3600 to session cookie; session survives tab switches
- **Session timeout** — Changed from 5-hour (300*60) to 5-minute sliding window using last_access
- **PG loop API compatibility** — Fixed method name mismatches (_api_loop_get → _api_loops_get etc.)
- **PG runs API** — Fixed _api_loops_runs() signature to accept qs parameter
- **Oracle COM loop API imports** — Fixed from scripts.lib.loop_api to from lib.loop_api
- **Oracle COM missing handlers** — Added _api_loops_stats, _api_loops_hooks, _api_loops_run_get methods
- **COM navigation** — Added loops link to Community Edition sidebar
- **Loop detail close button** — Added ❌ close button to detail panel header
- **Oracle ENT audit** — Added missing /audit route and /api/audit endpoint
- **PG ENT audit** — Created audit_api.py, audit.html, routes, and endpoints
- **PG authentication** — Fixed user_manager.authenticate() hash comparison with upper()
- **Route order** — /api/loops/{id}/children and /aggregation now match before catch-all /api/loops/{id}
- **Server startup** — Fixed startup script using nohup instead of setsid
- **PG ENT edition label** — Fixed templates showing "Community Edition" instead of "Enterprise Edition"

---
## [3.7.0] - 2026-06-18

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Loop Engineering** — Introduces Loop Engineering as the 4th generation AI engineering methodology (after Prompt Engineering, Context Engineering, and Harness Engineering), proposed by Peter Steinberger in June 2026. Adds 4 new tables, LOOP_MANAGER PL/SQL package, loop_api.py Python module, evaluation engine with 4 evaluation types, lifecycle hooks, and 3 scheduler jobs.

### Added - Both Editions

- **Loop Engineering methodology** — The 4th generation AI engineering methodology (after Prompt/Context/Harness Engineering), proposed by Peter Steinberger in June 2026
- 4 new tables: LOOP_META, LOOP_RUNS, LOOP_ITERATIONS, LOOP_HOOKS
- LOOP_MANAGER package/schema with ~22 functions for loop lifecycle management
- loop_api.py Python module with 25 functions including evaluation engine
- 4 evaluation types: TEST (command), DIFF (git diff), LLM_JUDGE (LLM scoring), MANUAL (human review)
- Stop conditions: max_iterations, max_tokens, max_duration_seconds
- Lifecycle hooks: PRE_RUN, POST_ITERATION, ON_STOP, ON_FAIL, ON_TIMEOUT
- 3 new scheduler jobs: LOOP_TRIGGER_JOB, LOOP_STUCK_CHECK_JOB, LOOP_CLEANUP_JOB
- loops.html template with loop management dashboard
- docs/loop-engineering.md documentation
- config.json llm_judge section (disabled by default)
- [ENT only] LOOP_AUDIT table for audit trail

### Changed - Both Editions

- **Test suite** — Community Edition: 121 tests; Enterprise Edition: 121 tests
- **Schema** — COM: 30 → 34 tables, 13 → 14 PL/SQL packages, 13 → 16 scheduler jobs; ENT: 35 → 40 tables, 16 → 17 PL/SQL packages, 17 → 20 scheduler jobs
- **Python modules** — COM: 23 → 24 modules; ENT: 24 → 25 modules

### Fixed - Both Editions

- **Oracle COM loop API imports** — Fixed `from scripts.lib.loop_api` to `from lib.loop_api` causing HTTP 500 on /api/loops endpoints
- **Oracle COM missing handler methods** — Added missing `_api_loops_stats`, `_api_loops_hooks`, `_api_loops_run_get` methods; fixed route-method name mismatches
- **COM navigation** — Added loops link back to Community Edition sidebar (loops is a core feature available in all editions)
- **Loop detail close button** — Added ❌ close button to loop detail panel header
- **Oracle ENT audit** — Added missing /audit route and /api/audit endpoint with handler methods
- **Server startup** — Fixed server startup script using `nohup` instead of `setsid` to prevent shell timeout deadlocks
- **Loop seed data** — Added realistic loop definitions with runs, iterations, and hooks to all editions


---
## [3.6.2] - 2026-06-18

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Bug fix release — adds missing Portal chat send handler, fixes session switching error handling, updates version and website references.

### Fixed - Both Editions

- **Portal Chat Send** — Added missing `_handle_portal_chat_send()` method; Portal users can now send chat messages
- **Session Switching** — Fixed `switchSession()` JS to handle errors properly with console logging and session list refresh on failure
- **Version** — Updated all version references from v3.6.1 to v3.6.2
- **Website** — Added official website reference https://db4agent.top

---
## [3.6.1] - 2026-06-14

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
Bug fix release — fixes Portal login error (`_handle_portal_login` method missing), corrects documentation inconsistencies, and adds graph node highlight interaction improvements.

### Fixed - Both Editions

- **Portal Login** — Added missing `_handle_portal_login()` method; Portal users can now log in and be automatically assigned a Pool Agent
- **Portal Register** — Added `has_agent` field to registration response for consistent frontend handling
- **Deep Sec version reference** — Corrected "v3.5.0 introduced Deep Data Security" → "v3.4.0" in SKILL.md
- **PBKDF2 description** — Fixed incorrect "SHA256/100K iterations" → "SHA512/210K iterations" in RELEASE_NOTES
- **Admin Token description** — Fixed token format description to `AT_` + 32hex (persistent, rotatable)
- **Port numbers** — Corrected all `localhost:8000` references to COM=18080/ENT=18090 in deployment.md, visualization.md, migration.md, introduction_zh, SKILL.md, RELEASE_NOTES
- **Data Grant count** — Fixed incorrect "22" → "23" references in ENT architecture.md
- **Test counts** — Updated stale "183" → COM 105 / ENT 135 in SKILL.md; "61" → COM 105 / ENT 135 in deployment.md
- **ENT feature matrix** — Fixed "Encrypted DB Credentials | No | Yes" → "Yes | Yes" in SKILL.md; added missing Recovery Codes and Private Skill rows
- **ENT api-reference** — Fixed title "Community Edition" → "Enterprise Edition"; added missing 9 Admin API endpoints
- **ENT RELEASE_NOTES** — Added missing Skill Token API section
- **Version display** — All page titles and sidebar version badges updated from v3.4.0 to v3.6.2

### Changed - Both Editions

- **Graph detail panel** — Changed to `position:fixed` overlay to prevent graph resize/pan when showing details
- **Graph click behavior** — Click blank area now closes detail panel and resets highlight; view position preserved on all interactions

---


## [3.6.0] - 2026-06-13

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Admin/Agent Separation Architecture** — New mode system (standalone/admin/agent) that separates Admin Agent (runs Web Portal, holds AIADMIN credentials) from Business Agent (independent process, only holds End User credentials). Introduces Admin Token authentication, encrypted credential distribution, Agent Bootstrap CLI, mode-aware connection management, Recovery Codes, Agent Recovery, Private Skill Backup, Skill Distribution & Management API.

### Added - Both Editions

- **Mode system** (standalone/admin/agent) — `config.json` `mode` field determines runtime behavior: `standalone` (default, single-process), `admin` (Admin Agent, runs Web Portal, holds AIADMIN credentials), `agent` (Business Agent, independent process, only holds End User credentials)
- **Admin Token Authentication** — `generate_admin_token()` and `verify_admin_token()` for secure Business Agent registration; tokens are `AT_` + 32hex, stored DB_CRYPTO encrypted in `SYSTEM_CONFIG` as `admin.registration_token`; constant-time verification via `secrets.compare_digest`
- **Encrypted Credential Distribution** — `encrypt_credential_for_distribution()` and `decrypt_credential_from_distribution()` using admin_token as key material via PBKDF2-HMAC-SHA512 (210000 iterations); each registration uses unique salt
- **Agent Bootstrap CLI** — `agent_bootstrap.py` command-line tool with commands: `register`, `recover`, `test`, `skill-list`, `skill-acquire`, `skill-create`, `skill-update`, `skill-delete`
- **Agent Config Encryption** — `save_agent_config()` and `load_agent_config()` for encrypted local storage of End User credentials in `agent_config.json`; uses existing master.key mechanism
- **Mode-aware connection.py** — Agent mode does not initialize AIADMIN connection pool; only uses End User connections from local `agent_config.json`; Admin mode initializes both AIADMIN and End User pools
- **Recovery Codes** — Agent registration returns 8 one-time `RC-XXXX-XXXX-XXXX` codes; SHA-256 hashed, DB_CRYPTO encrypted in `SYSTEM_CONFIG` (`recovery_codes.{agent_id}`); one-time use, verified via `verify_recovery_code()`
- **Agent Recovery** — `POST /api/admin/agent/recover` endpoint; verifies admin_token + recovery_code; checks LAST_SEEN_AT (5-minute window); **resets End User password** to prevent dual-active; returns new encrypted credentials
- **Private Skill Backup** — Skills with `visibility=PRIVATE` + `owned_by_agent=agent_id` are only visible to the owning agent; Data Grant predicate enforces isolation at DB level; Admin Skill API `list` endpoint supports `agent_id` + `visibility` filters
- **Skill Distribution API** — Admin API endpoints: `GET /api/admin/skill/list` (list available skills), `GET /api/admin/skill/{id}/acquire` (acquire skill content, optional resource=1 for ZIP)
- **Skill Management API** — Admin API endpoints: `POST /api/admin/skill/create`, `POST /api/admin/skill/update`, `POST /api/admin/skill/delete`, `POST /api/admin/skill/upload` (all with admin_token auth)
- **Admin API Endpoints** — `POST /api/admin/agent/register` (register Business Agent + return recovery codes), `POST /api/admin/agent/recover` (recover with recovery code), `POST /api/admin/token/generate`, `POST /api/admin/token/rotate`
- **Schema changes** — `admin.registration_token` seed in `SYSTEM_CONFIG`, `schema_version` updated to 3.6.0
- **Test suite** — Community Edition: 105 tests; Enterprise Edition: 135 tests

### Changed - Both Editions

- **config.json** — New `mode` field (default: `standalone` for backward compatibility)
- **connection.py** — `get_connection()` behavior varies by mode: standalone (AIADMIN pool + End User), admin (AIADMIN pool + End User pool), agent (End User connections only from agent_config.json)
- **1_schema.sql** — `schema_version` updated to 3.6.0, `admin.registration_token` seed added to SYSTEM_CONFIG

---
---


## [3.5.0] - 2026-06-11

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Deep Sec Multi-Agent Collaboration Fix** — SHARED entities and collaboration group data now correctly visible to End Users via Data Grant predicate fix and 2 new Data Grants for COLLAB_GROUPS/COLLAB_GROUP_MEMBERS access.

### Bug Fixes

- **SHARED entities invisible to End Users** — ENTITIES_AGENT_OWN Data Grant predicate was missing COLLAB subquery. SHARED visibility condition only checked WORKSPACES.CURRENT_AGENT_ID (which is NULL for most workspaces), ignoring collaboration group membership. Fixed: added UNION with COLLAB_GROUPS + COLLAB_GROUP_MEMBERS subquery to match the pattern used by BRANCH_AGENT_ACCESS, WS_AGENT_ACCESS, WS_CTX_AGENT_ACCESS, and TASK_AGENT_ACCESS.
- **End Users cannot access COLLAB tables** — Data Grant predicates for WORKSPACES, WORKSPACE_CONTEXT, CONTEXT_BRANCHES, and TASK_PLANS reference COLLAB_GROUPS and COLLAB_GROUP_MEMBERS in subqueries, but these tables had no Data Grants. End User subquery execution failed silently (ORA-00942), causing the entire predicate to return FALSE. Fixed: added `collab_member_own` (SELECT on COLLAB_GROUP_MEMBERS WHERE agent matches) and `collab_group_member_access` (SELECT on COLLAB_GROUPS WHERE group_id in member's groups).
- **WORKSPACE_CONTEXT collaboration isolation** — Added VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED) to WORKSPACE_CONTEXT. Previously, all context in a shared workspace was visible to all members, including other agents' private thoughts. Now agents see: (1) own context always, (2) other agents' SHARED/PUBLIC context in collab group workspaces, (3) other agents' PRIVATE context is blocked. Updated WS_CTX_AGENT_ACCESS and WS_CTX_AGENT_INSERT Data Grant predicates to enforce visibility-aware filtering.

### Data Grant Changes

- Data Grant count: 22 → 23
- New Data Grants: `collab_member_own` (COLLAB_GROUP_MEMBERS), `collab_group_member_access` (COLLAB_GROUPS)

---
---


## [3.4.0] - 2026-06-11

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Oracle Deep Data Security (Deep Sec)** — Replaces VPD (DBMS_RLS) with Oracle 26ai Deep Data Security: declarative Data Grants for row/column/cell-level access control, Mandatory Access Control (MAC) preventing view bypass, End User Context with `o:onFirstRead` callback for zero-trust agent identification. Fixes critical VPD vulnerability where unset context exposed all data (`1=1` → zero trust). Column-level masking hides sensitive fields (CREDENTIAL_VALUE) from non-admin users. SYSTEM_CONFIG fully restricted to admin role only.

### ⚠️ Critical Requirements

- **Oracle AI Database 26ai version 23.26.2.0.0 or later** — Earlier versions (23.26.1) have incomplete Deep Data Security support. Verify: `SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle%';`
- **Python oracledb 4.0.1 or later** — Version 4.0.0 has TCPS protocol incompatibility (ORA-29019) with Oracle 26ai and lacks `create_end_user_security_context` API. Install: `pip install oracledb>=4.0.1`. Full TCPS/Deep Sec driver support expected in oracledb 4.1.0+.

### Deep Data Security - Both Editions

- **`6_deep_sec_policy.sql`** — New deployment script replacing `6_vpd_policy.sql`:
  - **Data Roles**: `admin_data_role`, `agent_data_role`, `pool_agent_data_role`
  - **End User Context**: `agent_context` with `o:onFirstRead` callback from `SYS_CONTEXT('AGENT_CTX', 'AGENT_ID')`
  - **agent_auth_pkg**: PL/SQL callback package for lazy-loading agent identity into Deep Sec context
  - **Data Grants**: 20 declarative policies covering row-level (WORKSPACE_CONTEXT, ENTITIES, TASK_PLANS, CONTEXT_BRANCHES), column-level (AGENT_CREDENTIALS hides CREDENTIAL_VALUE), admin-only (SYSTEM_CONFIG), public-read (SKILL_META), and pool minimum (AGENT_REGISTRY, SKILL_META)
  - **MAC**: `SET USE DATA GRANTS ONLY` on 7 tables — prevents view-based bypass of row-level policies
  - **End User**: `deep_sec_agent` created for Deep Sec testing
- **`4_grants.sql`** — SYSTEM_CONFIG SELECT grant removed (protected by Data Grant, admin_data_role only). Deep Sec system privileges granted to AIADMIN (13 privileges)
- **`connection.py`** — Fixed critical bug: `set_agent_context()` now actually calls PL/SQL `SET_AGENT_CONTEXT.set_agent_id()` per connection. Added `apply_agent_context()` / `clear_agent_context()` for automatic session context management in `get_connection()`. Added `try/except` with `_logger.debug()` for graceful fallback when Deep Sec not deployed.
- **`server.py`** — Portal agent context integration: `_set_portal_agent_context()` / `_clear_portal_agent_context()` automatically set agent identity during Portal operations (login, chat, new chat) and clear on agent release. Admin Dashboard operates without agent context (schema owner full access). All Portal users follow the same context flow.
- **`2_api.sql`** — EMBEDDING_MANAGER now reads `embedding_url`, `embedding_model`, `embedding_dim` from SYSTEM_CONFIG instead of hardcoding values. Added `get_config()` helper function.
- **`1_schema.sql`** — Added `embedding_url` and `embedding_model` to SYSTEM_CONFIG defaults. Changed `embedding_dim` from 1536 to 1024 (matching actual model). Updated `schema_version` to 3.4.0.
- **`5_audit_policy.sql`** — Added ACL setup instructions for EMBEDDING_MANAGER UTL_HTTP access (requires SYSDBA execution).
- **`embedding_api.py`** — Fixed `compute_context_similarity()`: changed column reference from `EMBEDDING_VECTOR` (non-existent) to `EMBEDDING`, fixed bind variable syntax from positional `:1` to named `:eid`.
- **`agent_api.py`** — Fixed `issue_credential()`: changed bind variables from positional `:1,:2,:3...` to named `:cid,:aid,:uid...` (oracledb thin mode does not support numeric bind names).
- **`server.py`** — Fixed 5 positional bind variables `:1` → named `:wsid`/`:gid` in workspace/collab detail queries (oracledb thin mode incompatible with numeric binds).
- **SQL deploy scripts** — Updated all file headers and completion banners from v3.3.0 to v3.4.0 (1_schema.sql, 2_api.sql, 3_jobs.sql, 4_harness_templates.sql).
- **`start_web_server.sh`** — Updated from v3.2.0 to v3.4.0 (was two versions behind).
- **`docs/*.md`** — Updated all doc titles from "Oracle Memory System v2.1.0/v2.2.1" to "AI Agent Infra v3.4.0".
- **`test_skill.py`/`test_credential.py`** — Fixed positional bind variables `:1,:2,:3` → named `:eid,:uid,:uname,:aid` (oracledb thin mode compatibility).

### Deep Sec Enforcement Status (v3.4.0)

**Deep Sec is fully enforcing at the database level** via Direct Logon with Local End Users:

- Each Pool Agent has a corresponding Deep Sec End User (name = `UPPER(REPLACE(agent_id, '-', '_'))`)
- Portal users connect as End User → Data Grants auto-filter via `ORA_END_USER_CONTEXT.username`
- Admin Dashboard uses AIADMIN connection pool (schema owner, unrestricted by Data Grants)
- No external IAM, no TCPS, no tokens required — uses Oracle's Direct Logon mode
- `connection.py` automatically routes: `set_agent_context()` → End User connection with Data Grant filtering; no context → AIADMIN pool with full access
- `END_USER_MANAGER` PL/SQL package manages End User lifecycle (create/drop/get password)
- `DEEP_SEC_SESSION_ROLE` (CREATE SESSION) granted to Data Roles for End User login

Verified enforcement (Community DB):
| Table | AIADMIN (all) | AGENT_001 (Deep Sec) | Filter |
|-------|---------------|---------------------|--------|
| AGENT_REGISTRY | 17 | 1 | 94% |
| ENTITIES | 182 | 41 | 77% |
| TASK_PLANS | 18 | 5 | 72% |
| SYSTEM_CONFIG | 43 | BLOCKED | 100% |

### Bug Fixes (E2E Testing) - Both Editions

- **Portal login context timing** — `_set_portal_agent_context()` was called before `create_session()`/`create_workspace()`, causing these operations to use End User connection (no INSERT permission). Fixed: moved context setting after all AIADMIN-requiring operations.
- **Missing WORKSPACE_CONTEXT INSERT Data Grant** — Portal chat inserts messages into WORKSPACE_CONTEXT, but End Users lacked INSERT privilege. Added `ws_ctx_agent_insert` Data Grant (WHERE 1=1) for `agent_data_role`.
- **WORKSPACE_CONTEXT SELECT predicate incompatible with INSERT** — MAC "with check" requires new rows to satisfy SELECT predicate, but new rows' workspaces may not have CURRENT_AGENT_ID set. Fixed: added `OR UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username` to SELECT predicate.
- **Missing WORKSPACES SELECT Data Grant** — End Users could not read WORKSPACES table. Added `ws_agent_access` (SELECT) and `ws_agent_update` (UPDATE) Data Grants for `agent_data_role`.
- **Global agent context causing request interference** — Portal login set global `_current_agent_id`, affecting subsequent Admin Dashboard requests (using wrong connection). Fixed: added `_set_context_from_session()` called at start of each HTTP request to set context based on session's agent_id. Public APIs (register/login) force AIADMIN context.
- **`_current_agent_id` thread safety** — Global variable `_current_agent_id` caused cross-thread interference in multi-threaded HTTP server (e.g. Portal user's agent context leaking into concurrent register request, causing ORA-00942 on SYSTEM_USERS). Fixed: changed to `threading.local()` so each thread has its own agent context.
- **COM server.py referencing ENT-only table** — `CONTEXT_AUDIT_LOG` query in stats API caused ORA-00942 on Community Edition. Fixed: wrapped in try/except.
- **Portal API End User context blocking** — Portal GET APIs (user/profile, chat/sessions, chat/history, user/workspaces, user/memories) and POST APIs (chat/new, chat/send, chat/rename, chat/delete, chat/switch, agent/release) were routed through End User connections with Data Grant filtering, but WORKSPACES.CURRENT_AGENT_ID is NULL for most workspaces, causing Data Grant predicates to reject all rows. Fixed: Portal APIs now use `connection.set_agent_context(None)` to switch to AIADMIN connection for operations requiring access to WORKSPACES/SYSTEM_USERS tables, then restore End User context after completion.

### Security Fixes - Both Editions

- **VPD NULL context vulnerability (CRITICAL)** — Old VPD policy returned `1=1` (expose all) when `SYS_CONTEXT('AGENT_CTX', 'AGENT_ID')` was NULL. Deep Sec replaces this with zero-trust: no context = no data
- **SYSTEM_CONFIG exposure** — `GRANT SELECT ON SYSTEM_CONFIG TO AGENT_API` removed; Data Grant restricts to `admin_data_role` only
- **Python VPD bypass** — `set_agent_context()` only set Python global variable, never called PL/SQL. Now calls `SET_AGENT_CONTEXT.set_agent_id()` on every connection

### Removed - Both Editions

- **`6_vpd_policy.sql`** — Replaced by `6_deep_sec_policy.sql`. VPD functions `vpd_ws_ctx_agent` and `vpd_entities_visibility` no longer needed

---
---


## [3.3.0] - 2026-06-05

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Database Access Security & UI Visualization** — Five-plus-one-layer database access security model (Skill Policy, Restricted DB User, AUTHID DEFINER, VPD Row-Level Security, Unified Auditing, Credential Sanitization). Enhanced UI visualization with linked Spec/Plan/Branch info across Branches, Specs, and Collab pages. Multi-Agent Collaboration model completed with full integration across Spec, Collab Group, Branch, Task Plan, and Harness layers.

### Security - Both Editions

- **SKILL.md Database Access Policy** — Explicit policy prohibiting direct SQL/DML/DDL operations except during initial deployment; all data operations must go through Python API or PL/SQL packages
- **`_sanitize_context_data()`** — `save_context()` now automatically redacts sensitive fields (password, token, credential, dsn, api_key, secret, private_key, etc.) from context_data before storing in WORKSPACE_CONTEXT; supports nested dicts
- **`4_grants.sql`** — New deployment script creating restricted `AGENT_API` database user with EXECUTE-only on PL/SQL packages and SELECT-only on tables (no direct DML/DDL)
- **`5_audit_policy.sql`** — New deployment script creating Unified Auditing policy `DIRECT_DML_BYPASS_DETECTION` that audits direct DML on critical tables by non-schema-owner users
- **`6_vpd_policy.sql`** — New deployment script creating VPD (DBMS_RLS) row-level security policies: `WS_CTX_AGENT_VPD` restricts WORKSPACE_CONTEXT to agent's workspaces; `ENTITIES_VISIBILITY_VPD` enforces PRIVATE/SHARED/PUBLIC visibility; includes `SET_AGENT_CONTEXT` package for session-level agent identification
- **All PL/SQL packages verified AUTHID DEFINER** — Ensures restricted users execute package logic with schema owner privileges, enforcing business rules
- **`connection.py`** — Added `set_agent_context()`/`get_current_agent_id()` for VPD session context

### UI Visualization - Both Editions

- **Branches page** — Detail rows show linked Spec and Plan info (fetched via `/api/branch/{id}/spec` and `/api/branch/{id}/plans`); `loadBranchSpecPlan()` auto-loads on detail expand
- **Specs page** — New Branch column showing linked branch ID for specs with branch context
- **Collab page** — New Branch/Spec columns showing group's associated branch and spec
- **`/api/branch/{id}/spec`** — New GET endpoint returning specs linked to a branch (JOINs ENTITIES for TITLE)

### Fixed - Both Editions

- **`loadBranches()` missing `async`** — Function used `await` but was not declared `async`, causing JS error and infinite spinner
- **`buildDetail()` undefined `i` variable** — Changed to `buildDetail(b,idx)` with explicit index parameter
- **`/api/branch/{id}/spec` SQL error ORA-00904** — TITLE column does not exist in SPEC_META; changed to JOIN ENTITIES table
- **4_grants.sql** — Removed bogus `GRANT EXECUTE ON AIADMIN.BODY` and `CREATE SYNONYM AGENT_API.BODY` lines (BODY is not a valid package)
- **DB_CRYPTO PL/SQL** — Removed duplicate variable declarations (CK_KEY, CK_SALT, C_ALG) that would cause PLS-00371 compilation error
- **3_jobs.sql** — Removed INSERT INTO SYSTEM_LOGS references (table doesn't exist) from DORMANT_AGENT_JOB and CREDENTIAL_CLEANUP_JOB
- **1_schema.sql** — Moved CONTEXT_BRANCHES table definition before SPEC_META and WORKSPACE_CONTEXT (was causing ORA-00942 on FK references)
- **SPEC_META** — Added missing BRANCH_ID column (FK constraint existed but column was missing)
- **TASK_STEPS** — Added missing ASSIGNED_AGENT_ID column (FK constraint existed but column was missing)
- **COM agent_api.py** — Restored DB_CRYPTO.encrypt/decrypt (was incorrectly removed)
- **COM config.py/security.py** — Restored connection_crypto imports (shared between editions)
- **COM connection_crypto.py** — Restored (shared between editions, NOT ENT-only)
- **COM 2_api.sql** — Restored DB_CRYPTO package (shared between editions)

### Removed - Both Editions

- **__pycache__ and .pyc files** — Cleaned from all directories

---
---


## [3.2.0] - 2026-06-03

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Context Branching & Multi-Agent Collaboration** — Fork, merge, abandon, and resume conversation context branches within a workspace. Enables single-agent rollback exploration and multi-agent collaboration branching. Abandoned branches preserved as read-only lesson references with manual marking and automatic extraction. Collaboration groups now integrate with Branches, SDD (Spec), Task Plans, and Harness for coordinated multi-agent workflows: parallel exploration, pipeline handoff, task distribution, and group-level spec validation.

### Added - Both Editions

- **CONTEXT_BRANCHES table** — Branch metadata and lifecycle (EXPLORATION/ROLLBACK/HANDOFF/PARALLEL types, ACTIVE/MERGED/ABANDONED/PAUSED statuses)
- **BRANCH_MERGE_LOG table** — Merge history with conflict details (COMPLETED/CONFLICT/ROLLED_BACK statuses)
- **BRANCH_MANAGER PL/SQL package** — 11 subprograms: fork_branch, merge_branch, abandon_branch, pause_branch, resume_branch, diff_branches, detect_conflicts, mark_as_lesson, extract_lessons, fork_branch_for_spec, validate_branch_for_spec, fork_parallel_branches
- **BRANCH_COMPARISON view** — Unified comparison of two branches showing context differences, entity divergences, and conflict indicators
- **WORKSPACE_CONTEXT.BRANCH_ID column** — Links context entries to branches
- **AGENT_SESSION.BRANCH_ID column** — Links sessions to branches
- **CONTEXT_TYPE new value: BRANCH_POINT** — Marks context entry where a branch was forked
- **branch_api.py** — Python API for full branch lifecycle: fork/merge/abandon/pause/resume/diff/detect_conflicts/mark_as_lesson/extract_lessons/fork_branch_for_spec/merge_branch_with_validation/fork_parallel_branches/merge_parallel_branches/get_parallel_diff
- **/api/branch/* HTTP routes** — 17+ endpoints for branch operations (fork, merge, abandon, pause, resume, diff, conflicts, lesson, lessons/extract, fork-for-spec, merge-with-validation, fork-parallel, merge-parallel, plans, validate-spec)
- **Dashboard Branches page** — `/branches` page for branch management, comparison, conflict resolution, and lesson marking
- **Portal "Restart from here" button** — Fork a new branch from any prior chat message
- **TASK_PLANS.BRANCH_ID column** — Links task plans to branches
- **SPEC_META.BRANCH_ID column** — Links spec metadata to branches
- **COLLAB_GROUPS.BRANCH_ID column** — Links collaboration groups to branches
- **COLLAB_GROUPS.SPEC_ID column** — Links collaboration groups to specs
- **COLLAB_GROUP_MEMBERS.BRANCH_ID column** — Links group members to their branch
- **TASK_STEPS.ASSIGNED_AGENT_ID column** — Assigns plan steps to specific agents
- **spec_api.py** — Added create_spec() branch_id param, create_plan_from_spec_in_branch(), validate_branch_against_spec(), create_spec_for_group(), validate_group_progress()
- **task_plan_api.py** — Added create_plan() branch_id param, get_branch_plans(), add_step() assigned_agent_id param, distribute_plan_to_group()
- **harness_api.py** — Added instantiate_harness_in_branch(), share_harness_to_group(), instantiate_harness_for_member()
- **collab_api.py** — Added create_collab_group() branch_id/spec_id params, add_group_member() branch_id param, get_member_branches(), validate_group_against_spec(), sync_group_context()
- **/api/collab/* HTTP routes** — 6 new endpoints (group-branches, group-spec-validation, distribute-plan, sync-context)
- **BRANCH_CLEANUP_JOB** — Daily scheduler job for archiving abandoned branches and cleaning orphaned references

### Changed - Both Editions

- **workspace_api.py: save_context()** — Now accepts optional `branch_id` parameter
- **workspace_api.py: create_handoff_session()** — Uses `fork_branch` to create a branch on handoff
- **agent_api.py: checkpoint_session()** — Now returns `context_id`
- **agent_api.py: create_session()** — Now accepts optional `branch_id` parameter

### Fixed - Both Editions

- **DB_CRYPTO PL/SQL** — Removed duplicate variable declarations (CK_KEY, CK_SALT, C_ALG) that would cause PLS-00371 compilation error
- **3_jobs.sql** — Removed INSERT INTO SYSTEM_LOGS references (table doesn't exist) from DORMANT_AGENT_JOB and CREDENTIAL_CLEANUP_JOB
- **1_schema.sql** — Moved CONTEXT_BRANCHES table definition before SPEC_META and WORKSPACE_CONTEXT (was causing ORA-00942 on FK references)
- **SPEC_META** — Added missing BRANCH_ID column (FK constraint existed but column was missing)
- **TASK_STEPS** — Added missing ASSIGNED_AGENT_ID column (FK constraint existed but column was missing)
- **RELEASE_NOTES_v3.0.0.md** — Fixed header showing v3.1.0 instead of v3.0.0
- **Branch Overview stats bar** — Changed background to transparent to visually separate from table header

### Removed - Both Editions

- **Old v3.1.0 documentation** — Removed docs/introduction_zh_v3.1.0.md (superseded by v3.2.0 version)

### Removed - Community Edition Only

- **SKILL_ACCESS_TOKEN reference** — Removed from COM skill_api.py (table doesn't exist in COM schema)

---
---


## [3.1.0] - 2026-06-02

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Database-Side Encryption with DB_CRYPTO** — Moved all in-database encryption (LDAP BIND_CREDENTIAL, AGENT CREDENTIALS) from Python-side `encrypt_section()`/`decrypt_section()` (which depended on a local `master.key` file) to Oracle `DBMS_CRYPTO` via a new `DB_CRYPTO` PL/SQL package. Database-side encryption keys are stored in `SYSTEM_CONFIG` and fully managed by the database — no dependency on external files.

### Added - Both Editions

- **DB_CRYPTO PL/SQL package** — AES-256-CBC encryption/decryption using `DBMS_CRYPTO`, with keys auto-generated and stored in `SYSTEM_CONFIG`. Functions: `encrypt()`, `decrypt()`, `encrypt_raw()`, `decrypt_raw()`, `rotate_key()`
- **DBMS_CRYPTO grant** — `GRANT EXECUTE ON SYS.DBMS_CRYPTO` added to deployment prerequisites
- **DB_CRYPTO key auto-generation** — First call to `encrypt()` auto-generates a 256-bit key + salt and stores in `SYSTEM_CONFIG` with `db_crypto_master_key` / `db_crypto_key_salt` keys
- **DB_CRYPTO.rotate_key()** — Re-generates the encryption key (note: existing encrypted data must be re-encrypted after rotation)

### Changed - Both Editions

- **agent_api.py:issue_credential()** — Now uses `DB_CRYPTO.encrypt()` instead of Python-side encryption (was `encrypt_section` in ENT, broken `ReversibleEncryption` in COM)
- **agent_api.py:verify_credential()** — Now uses `DB_CRYPTO.decrypt()` instead of Python-side decryption
- **DB_CRYPTO.get_db_key()** — Concurrent-safe: uses `SELECT → NO_DATA_FOUND → INSERT → DUP_VAL_ON_INDEX` pattern instead of `COUNT + INSERT`, preventing key overwrite on parallel first-use

### Deployment Prerequisites - Both Editions

- **`GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <db_user>`** — Required by `DB_CRYPTO` package (new prerequisite, must be granted by SYSDBA before running `2_api.sql`)

### Documentation - Both Editions

- **Data Isolation Model** — Documented three-layer isolation: physical (ENTITY_TYPE LIST partition), access (VISIBILITY + OWNED_BY_AGENT), workspace (WORKSPACE_ID + OWNER_USER_ID)
- **Dual-Track Encryption** — Documented split between `connection_crypto` (local file encryption) and `DB_CRYPTO` (database-side encryption)
- **Multi-Agent Key Sharing** — Documented how agents sharing the same database automatically share `DB_CRYPTO` keys

### Changed - Enterprise Edition Only

- **ldap_auth_api.py:configure_ldap()** — Now uses `DB_CRYPTO.encrypt()` for BIND_CREDENTIAL instead of `encrypt_section()`
- **ldap_auth_api.py:_get_active_config()** — Now uses `DB_CRYPTO.decrypt()` instead of `decrypt_section()`
- **ldap_auth_api.py** — Removed `connection_crypto` import dependency for database-side encryption

### Fixed - Both Editions

- **SHA256 password comparison** — `actual == expected` changed to `actual.upper() == expected.upper()` in `_authenticate_local()` to handle hex case mismatch between Python `hexdigest()` (lowercase) and Oracle `RAWTOHEX()` (uppercase)

### Fixed - Community Edition Only

- **Removed enterprise-only code** — Deleted `skill_token_api.py`, audit/LDAP/skill-token routes from `server.py`, `context_audit_log` query from `_api_stats()`, LDAP mode from `portal_login.html`, `requestAccess()` from `skills.html`
- **Added `directDownload()`** to COM `skills.html` for direct resource download (no token flow)

### Other Changes - Both Editions

- **`introduction_zh_v3.0.0.md` → `introduction_zh_v3.1.0.md`** — Renamed to match current version

### Security Impact

- **Before v3.1.0**: Database encrypted data (LDAP bind credentials, agent credentials) depended on local `~/.oracle-infra/master.key` — if the file was lost or the server migrated, encrypted data became unrecoverable
- **After v3.1.0**: All database-side encryption uses `DBMS_CRYPTO` with keys stored in `SYSTEM_CONFIG` — fully self-contained within the database, portable across server migrations
- **config.json encryption** (`connection_crypto.py`) remains unchanged — this is for local file encryption only, which correctly depends on the local master key

---
---


## [3.0.0] - 2026-05-30

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
**Enterprise Edition Launch + Portal User System & Security Hardening** — The project formerly known as "Oracle AI Database Memory System" (oracle-memory-by-yhw) has been renamed to **AI Agent Infra with OracleDB**, reflecting its evolution from a pure memory system to a comprehensive AI Agent infrastructure architecture. The project now offers two editions: Community Edition (Apache 2.0) and Enterprise Edition (BSL 1.1). This release also adds a full user-facing Portal system (register/login/chat) separate from admin Dashboard, Agent lifecycle with POOL state, LDAP login with auto-registration, encrypted credential storage at rest, and inline detail expansion across all list pages.

### Added - Both Editions

- **Portal login page** (`/portal/login`) — register/login dual-tab with auth mode selector; root `/` redirects to Portal; "Admin Dashboard" link in top-right corner
- **Portal chat page** (`/portal/chat`) — sidebar with user info (larger username + auth type label), session list with rename/delete buttons, new chat button; main chat area with simulated replies
- **Session management** — new chat creates AGENT_SESSION + CONVERSATION WORKSPACE; switch between sessions; rename via WORKSPACE_ALIAS; delete with cascading WORKSPACE_CONTEXT + WORKSPACES cleanup
- **Auto-naming** — new sessions default to "New Chat"; first user message auto-renames to first 60 chars of message content
- **user_api.py** — `register_user()`, `register_ldap_user()`, `get_user_profile()`, `update_last_login()`, `get_user_sessions()`
- **Agent pool management** — `assign_random_pool_agent()` random selection from POOL; `hibernate_agent()` sets STATUS='POOL' (was DORMANT)
- **WORKSPACES.WORKSPACE_ALIAS** column + IDX_WS_ALIAS index
- **WORKSPACE_CONTEXT.CK_WC_TYPE** — added 'CHAT_MESSAGE' to CHECK constraint
- **SYSTEM_USERS.AUTH_SOURCE** + **LDAP_DN** columns + indexes (Community Edition sync)
- **Encrypted config.json** — DB credentials stored as `_encrypted` blob; plaintext keys removed; auto-encrypt on first run
- **connection_crypto.py** — Master key resolution (env > keyfile > auto-generate); encrypt/decrypt sections; auto_encrypt_config()
- **config.py** — `_decrypt_database_section()` for transparent credential decryption
- **LDAP Unified Identity Authentication** — Agent Pool users can authenticate against LDAP directories in addition to local SYSTEM_USERS. New `LDAP_CONFIG` table, `LDAP_SYNC_LOG` table, `SYSTEM_USERS.AUTH_SOURCE`/`LDAP_DN` columns, `ldap_auth_api.py` (8 functions), `LDAP_AUTH_MANAGER` PL/SQL (6 subprograms), `LDAP_SYNC_JOB` (hourly)
- **Skill Storage & Distribution** — Database-backed Skill registry with secure one-time-token resource distribution. New `SKILL_META` table (reference-partitioned, with `SKILL_DESCRIPTION`, `RESOURCE_SERVER_HOST` columns), `SKILL_DV` JRD view, `skill_api.py` (9 functions, update_skill supports title + description), `skill_acquire_api.py` (4 functions: discover, acquire_text, acquire_resource, acquire_full — no auth required), `skill_parser.py` (ZIP package parser with `_meta.json`/YAML frontmatter/`## Metadata` priority), `skill_storage.py` (file storage with server hostname+IP tracking), `SKILL_ACCESS_TOKEN` table (enterprise-only, with `DOWNLOAD_TOKEN`/`DOWNLOAD_EXPIRES_AT`), `skill_token_api.py` (4 functions, enterprise-only, one-time download token flow), `SKILL_MANAGER` PL/SQL (6 subprograms with `RESOURCE_SERVER_HOST`/`SKILL_DESCRIPTION` params). Two-step skill creation: upload ZIP → auto-parse → editable form → confirm. Dashboard resource download (repack as ZIP with `{skill_name}-{version}.zip` naming).
- **Encrypted Database Credentials** — Database connection info encrypted at rest in config.json. New `connection_crypto.py` (5 functions), `ConfigEncryption` class in security.py, `encrypt_config.py` CLI tool, auto-encrypt on first run, master key from env var/keyfile/auto-generate
- **Workspace Context Audit** — Rule engine + embedding semantic analysis for idle patterns, context similarity, data leaks, access anomalies, cross-boundary breaches. New `CONTEXT_AUDIT_LOG` table (RANGE yearly), `CONTEXT_AUDIT_RULES` table (5 seed rules), `audit_api.py` (7 functions), `CONTEXT_AUDIT_MANAGER` PL/SQL (7 subprograms), `compute_context_similarity` in embedding_api.py, `CONTEXT_AUDIT_JOB` (daily purge), `IDLE_PATTERN_DETECT_JOB` (hourly), `/audit` web page with overview stats + event list + detail view
- **Enterprise Configuration** — `config.json` now supports `ldap` section (LDAP server config), `enterprise` section (license_type, skill_token_ttl_min, audit_threshold_score, presigned_url_ttl_sec), and encrypted `database._encrypted` field
- **BSL 1.1 License** — Enterprise Edition uses Business Source License 1.1; Community Edition remains Apache 2.0

### Added - Enterprise Edition Only

- **Portal LDAP login** — auth mode dropdown with "LDAP 统一认证" option; authenticates via LDAP bind; auto-registers new users to SYSTEM_USERS with AUTH_SOURCE='LDAP'; syncs LDAP_DN on re-login
- **LDAP BIND_CREDENTIAL encryption** — `configure_ldap()` encrypts before DB write; `_get_active_config()` decrypts on read
- **AGENT_CREDENTIALS encryption** — `issue_credential()` / `verify_credential()` now use `encrypt_section()`/`decrypt_section()` with master key (was broken `ReversibleEncryption` with random key)
- **Registration duplicate check** — Checks SYSTEM_USERS (case-insensitive) then LDAP directory; distinct error messages for each case
- **LDAP test user passwords** — zhangsan:zhangsan123, lisi:lisi123, wangwu:wangwu123, agent_ops:agent_ops123, dev_engineer:dev_engineer123

### Changed - Both Editions

- **Product rename** — All references updated from "Oracle Memory System" / "oracle-memory-by-yhw" to "AI Agent Infra with OracleDB"
- **SKILL.md** — Enterprise: name=`ai-agent-infra-enterprise`; Community: name=`ai-agent-infra-community`
- **hibernate_agent()** — STATUS='DORMANT' → STATUS='POOL'; released agents immediately available for reassignment
- **DORMANT_AGENT_JOB** — Sets STATUS='POOL' instead of DORMANT
- **Inline detail expansion** — All list pages (agents, tasks, workspaces, specs, collab, skills, audit) converted from right-side panel to inline row expansion; `toggleDetail()` correctly collapses when clicking same row
- **Graph explorer** — `navigationButtons:false`, `.vis-navigation{display:none!important}`
- **Portal chat user info** — Username displayed at 1rem bold; auth type shown below ("系统用户" / "LDAP 用户")
- **Portal login i18n** — Auth mode dropdown options switch zh/en via JS `_langTexts` dict + `updateLangTexts()`
- **Register tab** — Shows "注册为本地系统用户" hint text; no auth mode dropdown in register panel
- **test_credential.py** — DORMANT → POOL assertion updated
- **config.py** — Rewritten with `LdapConfig`, `EnterpriseConfig` dataclasses; encrypted database credential support via `_decrypt_database_section()`
- **security.py** — New `ConfigEncryption` class with PBKDF2-HMAC-SHA512 key derivation + authenticated encryption
- **connection.py** — Transparent decryption of database credentials from config
- **NOTICE** — Updated product name for both editions

### Changed - Enterprise Edition Only

- **Admin Dashboard auth** — `/api/login` uses `_authenticate_local()` — only LOCAL users; LDAP users rejected
- **Portal login** — System User mode uses `_authenticate_local()`; LDAP mode uses `_authenticate_portal_ldap()`

### Fixed

- oracledb returns lowercase column names; `workspace_alias`/`workspace_name` key access fixed in auto-rename logic
- `toggleDetail()` now checks if row already expanded before calling `closeDetail()`, preventing double-toggle bug
- `ReversibleEncryption` used random key per instance — credential encryption was irreversible; replaced with `encrypt_section()`/`decrypt_section()` using stable master key

---
---


## [2.3.2] - 2026-05-27

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
---


## [2.3.1] - 2026-05-26

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
---


## [2.2.0] - 2026-05-20

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
---


## [2.1.0] - 2026-05-19

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
---


## [2.0.0] - 2026-05-15

### Summary
Enterprise encryption enhancement: per-Agent independent crypto keys with SYSTEM_CONFIG storage, config.json auto-encryption, key rotation API, encrypt_config.py CLI, Portal Markdown rendering.
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
---


## [0.5.1] - 2026-05-09

### Added

- Enhanced session management with timeout controls
- Improved agent permission model

### Fixed

- Session cleanup edge cases

---
---


## [0.5.0] - 2026-05-08

### Added

- Security & Performance Enterprise Edition
- Data masking (desensitization) with context-aware levels
- Reversible encryption for sensitive data
- PBKDF2 password hashing
- Aggregation analysis for audit queries

---
---


## [0.4.2] - 2026-05-07

### Changed

- Directory consolidation and naming standardization
- Internal cleanup of script organization

---
---


## [0.4.0] - 2026-05-02

### Added

- Task plan system with multi-step definitions
- Task step status tracking
- Task context snapshots for breakpoint/recovery
- Task tool call audit logging
- Inter-plan dependency graph

---
---


## [0.3.x] - 2026-04-28

### Added

- Core memory system with CRUD operations
- Knowledge base with concept management
- Basic graph relationships between entities
- Oracle property graph integration
- Vector embedding support for semantic search
