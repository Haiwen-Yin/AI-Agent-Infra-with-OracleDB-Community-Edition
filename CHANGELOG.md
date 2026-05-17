# Changelog

All notable changes to the Oracle AI Database Memory System are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
