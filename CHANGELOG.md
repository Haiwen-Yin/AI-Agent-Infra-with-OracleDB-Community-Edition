# Changelog

All notable changes to the AI Agent Infra unified repository are documented in
this file. Each released edition (Oracle/PG/YashanDB × Community/Enterprise)
inherits the entries below; per-edition release notes live in
`RELEASE_NOTES_v<VERSION>.md` shipped with each build.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the rules in `openspec/specs/documentation-format/spec.md`.

## [4.0.0] - 2026-07-19

### Summary

Ground-up restructure of AI Agent Infra from six independent per-edition
repositories into a single unified source tree that generates all six release
editions (Oracle / PostgreSQL / YashanDB, each in Community and Enterprise
tiers) via one build script. This release introduces the adapter-overlay
layout, a single `VERSION` source of truth, a shared OpenSpec store, and a
spec-driven validator that gates releases on the OpenSpec contracts.

### Added

- **Unified repository layout** (`shared/` + `adapters/<db>/`) replacing six
  divergent per-edition trees.
- **`build.py`** — generates `build_output/<edition>/` plus a release zip per
  edition, overlays adapter code on top of shared code, injects the version
  string, and emits per-edition `config.json` / `requirements.txt`.
- **`VERSION`** as the single source of truth for the version string, read by
  `build.py` and `spec_validator.py`.
- **`editions/*.json`** — six per-edition configuration files driving
  `build.py` (license, web port, DB connection, `extra_features`).
- **`spec_validator.py`** — validates each built edition against the OpenSpec
  specs (required files, minimum test counts, API endpoint surface); supports
  `--edition`, `--live --base-url`, and `--json` modes.
- **`openspec/config.yaml`** pointing at the shared store at
  `/root/AI-Agent-Infra-Specs`.
- **`shared/tests/conftest.py`** — pytest parameterization over
  `oracle` / `pg` / `yashandb` with auto-skip of unreachable backends and
  environment-variable overrides (`AIAGENT_TEST_DB`, `AIAGENT_SKIP_DB`,
  `AIAGENT_*_DSN` / `_HOST` / `_USER` / `_PASSWORD`).
- **`shared/docs/AGENTS.md`** — guide for the unified repo covering the build
  system, version management, edition configs, OpenSpec store, and test
  infrastructure.
- **`shared/README_TEMPLATE.md`** — per-edition README template consumed by
  `build.py`.
- **OpenSpec store** with four initial specs: `api-contract`,
  `database-adaptation`, `documentation-format`, `test-requirements`.

### Changed

- **Build pipeline**: releases now produced by `python3.14 build.py` from one
  source tree, replacing the prior per-edition copy-and-patch workflow.
- **Version injection**: `build.py:inject_version()` rewrites `VERSION = "4.0.0"`
  in Python and `vX.Y.Z` literals in `.py`/`.sql`/`.md`/`.html`/`.sh` for
  every file in each built edition; no source file may hardcode a version.
- **Directory shape of built editions**: loose `.py`/`.sh` files and `lib/`,
  `tests/`, `tools/`, `visualization/` subdirectories now live under
  `scripts/` in every built edition.
- **`config.py`**: each edition now derives from `adapters/<db>/config_db.py`
  instead of carrying its own copy.
- **Test runner**: `pytest` is now the canonical runner via the parameterized
  `conftest.py`; the legacy `test_all.py` master runner remains for
  non-pytest environments.

### Fixed

- Eliminated cross-edition drift in shared business logic (loop_api,
  memory_api, graph_api, etc.) — there is now exactly one copy in `shared/lib/`.
- Eliminated version-string skew across files within an edition — every build
  rewrites all of them from `VERSION`.
- Eliminated the "forgot YashanDB" class of release mistakes by building all
  six editions from one command and validating them against one spec set.

### Notes

- **Minimum test counts** per edition (from `test-requirements/spec.md`):
  Oracle COM/ENT 121, PG COM/ENT 103, YashanDB COM 109 / ENT 113.
- **API contract**: all editions must serve the common endpoints listed in
  `api-contract/spec.md`; Enterprise editions additionally serve
  `/api/admin/crypto/rotate`, `/api/approvals`, `/api/audit`.
- **Database drivers**: Oracle uses `oracledb>=4.0.1`, PG uses
  `psycopg2-binary>=2.9`, YashanDB uses `yaspy>=1.2.1`.

## [3.10.2] - 2026-07-17

### Summary
YashanDB adaptation — full support for YashanDB 23.5+ with the yaspy driver,
expanding the edition matrix to 6 (2 Oracle + 2 PG + 2 YashanDB). 670 tests
pass across all editions.

### Added
- **YashanDB adapter** — `adapters/yashandb/` (connection.py, config_db.py,
  agent_api.py, deploy_yashandb.py) with yaspy 1.2.1 driver.
- **YashanDB schema** — `1_schema.sql` adapted (no reference partitioning, no
  JSON_OBJECT, no inline FK, no LOCAL index) for YashanDB compatibility.
- **`install_yaspy.sh`** — installs yaspy `.so` + client libs and recreates
  `.so` / `.so.MAJOR` symlinks under `~/.yashandb/client/lib/`.
- **`vendor/yaspy/`** — bundled yaspy driver + YashanDB client libraries
  (deduplicated: only `*.so.MAJOR.MINOR.PATCH` shipped, symlinks recreated at
  install time).
- YashanDB connection.py converts yaspy VECTOR `array.array` returns to string
  to avoid GC-time segfaults.

## [3.10.2] - 2026-07-16

### Summary
Enterprise encryption enhancement — per-Agent independent crypto keys (DB
storage + admin_token distribution), config.json auto-encryption on startup
(database + LLM + model_routing), key rotation API, encrypt_config.py CLI
tool, Portal Markdown rendering. 544/544 tests pass.

### Added
- **Per-Agent crypto keys** — each agent gets an independent encryption key
  stored in DB and distributed via admin_token.
- **config.json auto-encryption** — on startup, sensitive fields (database
  password, LLM api_key, model_routing credentials) are encrypted in place
  using PBKDF2-derived keys.
- **Key rotation API** — `/api/admin/crypto/rotate` for Enterprise editions.
- **`encrypt_config.py`** — CLI tool to manually encrypt/decrypt config.json.
- **Portal Markdown rendering** — portal chat now renders Markdown responses.

## [3.10.1] - 2026-07-14

### Summary
Offline deployment — vendor/ directory with 30 pre-downloaded cp314 wheels,
install_offline.sh for air-gapped installation, verify_deps.py for integrity
check. Pure-Python deploy_oracle.py replaces SQLcl (125 MB + Java) with a
state-machine SQL parser handling PROMPT/DEFINE/&&// syntax. Zero external
runtime dependencies.

### Added
- **`vendor/` directory** — 30 pre-downloaded cp314 wheels for air-gapped
  installation.
- **`install_offline.sh`** — installs all wheels into the active Python.
- **`verify_deps.py`** — verifies wheel integrity and Python version.
- **`deploy_oracle.py`** — pure-Python SQL deployment script replacing SQLcl;
  state-machine parser handles PROMPT, DEFINE, &&, //, BEGIN/END blocks.

## [3.10.0] - 2026-07-09

### Summary
Universal Property Graph — 30+ graph functions across 8 domains: knowledge
causal (CAUSES/CONTRADICTS), agent collaboration (group-scoped TRUSTS), task
orchestration (FEEDS_INTO/PRODUCED_ARTIFACT), skill dependency, approval
propagation (BLOCKS with cascade reject), data flow (DERIVED_FROM_DATA),
memory evolution (PROMOTED_TO/MERGED_INTO), loop iteration
(BUILDS_ON/INFORMS/CORRECTS). 23 new edge types. Dynamic trust via
SYSTEM_CONFIG.

### Added
- **30+ graph functions** in 8 domains with 23 new edge types.
- **Dynamic trust configuration** via SYSTEM_CONFIG table.
- **Cascade approval rejection** via BLOCKS edge propagation.

## [3.9.0] - 2026-07-05

### Summary
Ecosystem connectivity — MCP Server (10 tools, stdio + SSE), SSE streaming
output, Human-in-the-Loop approval (step/loop/tool), Agent Protocol
compatibility, multi-model routing.

### Added
- **MCP Server** — 10 tools exposed via stdio and SSE transports.
- **SSE streaming** — real-time token streaming for portal chat.
- **Human-in-the-Loop approval** — step/loop/tool level approval gates.
- **Agent Protocol compatibility** — `/ap/v1/agent/tasks` endpoint.
- **Multi-model routing** — per-task model selection via model_routing config.

## [3.8.0] - 2026-07-02

### Summary
Multi-Agent integration testing — 5-phase deployment, 15/15 functional tests
passed. Oracle: LOOP_MANAGER, DB_CRYPTO, schema prefix fixes. PG:
_convert_params rewrite, policy double-ON, authenticate v_salt fixes. ENT:
LOOP_AUDIT, audit routing.

### Fixed
- Oracle LOOP_MANAGER package body compilation.
- Oracle DB_CRYPTO package integration with config encryption.
- Oracle schema prefix collision in ENT deployments.
- PG `_convert_params` rewrite for RETURNING INTO clause handling.
- PG policy double-ON trigger for RLS + audit.
- PG authenticate v_salt verification logic.
- ENT LOOP_AUDIT routing and audit trail completeness.

## [3.7.5] - 2026-06-28

### Summary
Bug fixes: orchestrator, event_bus security, message_api DELETED status, ENT
missing Data Grants. PG: connection.py rewrite, 10 modules Oracle-to-PG
migration.

### Fixed
- Orchestrator deadlock on concurrent task assignment.
- event_bus security check bypass via crafted payload.
- message_api DELETED status not propagating to collab_api.
- ENT missing Data Grants policy on knowledge_entities table.
- PG connection.py rewrite for connection pooling stability.
- 10 modules migrated from Oracle-specific syntax to cross-DB compatible SQL.

## [3.7.4] - 2026-06-26

### Summary
6 expansions: Agent Communication Protocol, Multi-Agent Orchestration (DAG),
Event-Driven, Advanced Memory, Observability, Tool Ecosystem.

### Added
- **Agent Communication Protocol** — inter-agent messaging with typed channels.
- **Multi-Agent Orchestration (DAG)** — dependency graph for multi-agent tasks.
- **Event-Driven** — event_bus with pub/sub and dead letter queue.
- **Advanced Memory** — episodic + semantic + procedural memory types.
- **Observability** — OpenTelemetry-compatible tracing and metrics.
- **Tool Ecosystem** — tool registry with versioning and access control.

## [3.7.3] - 2026-06-23

### Summary
Deployment fixes: schema FK ordering, DEFINE SCHEMA_OWNER, config priority,
embedding model prompt.

### Fixed
- Schema foreign key creation ordering for clean-slate deployment.
- DEFINE SCHEMA_OWNER directive not resolving on PG.
- Config priority: config.json now overrides environment variables correctly.
- Embedding model prompt template for bge-m3.

## [3.7.2] - 2026-06-19

### Summary
Documentation consistency: corrected function counts, job schedules, partition
counts, PG terminology, evaluation types.

### Fixed
- Function count discrepancies across docs (126 Oracle / 103 PG / 109 YashanDB).
- Job schedule descriptions (DBMS_SCHEDULER vs pg_cron).
- Partition count inconsistencies in deployment guide.
- PG terminology ("schema" vs "database" vs "tablespace").
- Evaluation type enumeration (THRESHOLD/SPEC_VALIDATION/AGGREGATE/HUMAN/LLM_JUDGE/CUMULATIVE).

## [3.7.1] - 2026-06-19

### Summary
Loop Engineering collaborative integration: Spec-Driven Loop, Task-Loop
Binding, Collaborative Loop. SPEC_VALIDATION & AGGREGATE evaluation types.

### Added
- **Spec-Driven Loop** — loops driven by spec validation results.
- **Task-Loop Binding** — loops bound to tasks via task_id FK.
- **Collaborative Loop** — multi-agent loops with role-based iteration.
- **SPEC_VALIDATION evaluation type** — evaluates against spec contracts.
- **AGGREGATE evaluation type** — aggregates multi-agent evaluation results.

## [3.7.0] - 2026-06-18

### Summary
Loop Engineering (4th gen AI methodology): 4 loop tables, LOOP_MANAGER package,
4 evaluation types, lifecycle hooks. ENT: LOOP_AUDIT.

### Added
- **4 loop tables** — LOOPS, LOOP_ITERATIONS, LOOP_RESULTS, LOOP_FEEDBACK.
- **LOOP_MANAGER package** — PL/SQL package for loop lifecycle management.
- **4 evaluation types** — THRESHOLD, HUMAN, LLM_JUDGE, CUMULATIVE.
- **Lifecycle hooks** — pre/post iteration hooks for custom logic.
- **ENT LOOP_AUDIT** — audit trail for loop decisions and iterations.

## [3.6.2] - 2026-06-18

### Summary
Portal chat fix, 15 PG bug fixes. ENT: audit trail, LDAP auth, skill tokens,
compliance logs.

### Fixed
- Portal chat SSE streaming buffer issue.
- 15 PG-specific bugs (connection pooling, type coercion, RLS policy).
### Added
- **ENT Audit trail** — immutable audit log for all data modifications.
- **ENT LDAP auth** — bind DN + bind password with connection pooling.
- **ENT Skill tokens** — time-limited tokens for skill invocation.
- **ENT Compliance logs** — structured logs for regulatory compliance.

## [3.6.1] - 2026-06-16

### Summary
PG Community & Enterprise Editions initial release, full feature parity with
Oracle.

### Added
- **PG adapter** — connection.py, config_db.py with psycopg2 2.9 driver.
- **PG schema** — 1_schema.sql with RLS policies replacing Data Grants.
- **Full feature parity** with Oracle edition (knowledge, graph, memory, loops).

## [3.6.0] - 2026-06-13

### Summary
Admin/Agent separation, Recovery Codes, Private Skill, row-level isolation fix.

### Added
- **Admin/Agent role separation** — distinct permission sets and UI.
- **Recovery Codes** — 10 one-time codes for admin account recovery.
- **Private Skill** — skills with `is_private=true` visible only to creator.
### Fixed
- Row-level isolation bypass via collab_api cross-agent query.

## [3.4.0] - 2026-06-11

### Summary
Deep Data Security, Row-Level Isolation (Data Grants / RLS), MAC, zero-trust
architecture.

### Added
- **Data Grants (Oracle)** — row-level security via DBMS_DATA_GRANTS.
- **RLS (PG)** — row-level security via pg_rowsecurity.
- **Mandatory Access Control (MAC)** — security classification labels.
- **Zero-trust architecture** — every request verified, no implicit trust.

## [3.1.0] - 2026-06-02

### Summary
Full rewrite, dual-edition strategy, database-native encryption.

### Added
- **Dual-edition strategy** — Community (Apache 2.0) vs Enterprise (BSL 1.1).
- **Database-native encryption** — DBMS_CRYPTO for column-level encryption.
- **Full rewrite** — modular architecture with clear separation of concerns.

## [2.0.0] - 2026-05-15

### Summary
Unified architecture rewrite, oracledb driver.

### Added
- **oracledb driver** — migration from cx_Oracle to python-oracledb thin mode.
- **Unified architecture** — consolidated modules into cohesive service layer.

## [1.0.0] - 2026-05-09

### Summary
Initial release: knowledge base & property graph.

### Added
- **Knowledge base** — document ingestion, chunking, embedding, vector search.
- **Property graph** — entities, relationships, graph traversal queries.
