# Oracle AI Database Memory System v2.0.0 Release Notes

**Release Date**: 2026-05-15
**Version**: v2.0.0
**Status**: Production Release
**Author**: Haiwen Yin
**License**: Apache License 2.0

---

## Overview

**v2.0.0 is a complete ground-up rewrite.** It cannot be upgraded from any v1.x version. The entire database schema, Python API, deployment pipeline, and documentation structure have been redesigned from scratch.

This release addresses fundamental architectural problems in v1.x: table fragmentation, SQLcl subprocess bottlenecks, scattered deployment scripts, and an unmaintainable 934-line SKILL.md.

---

## Why a Complete Rewrite?

### Problems in v1.x

| Problem | Impact |
|---------|--------|
| 5 separate entity tables | Data duplication, inconsistent queries, no cross-type relationships |
| 3 separate edge/relationship tables | Same concept represented 3 different ways |
| SQLcl subprocess for every DB operation | 90+ second timeouts, 4500x slower than direct driver |
| 15+ scattered SQL scripts | No deployment order, broken dependencies, no idempotency |
| 934-line SKILL.md + 12 markdown files | Impossible to navigate, outdated, duplicated content |
| Separate property graphs for knowledge and memory | Cannot traverse cross-type relationships |
| memory_system_users table | Non-standard schema, no role-based access |

### v2.0 Solutions

| Solution | Result |
|----------|--------|
| Single ENTITIES table with ENTITY_TYPE discriminator | One source of truth for all entity types |
| Single ENTITY_EDGES table with unified edge type namespace | Consistent relationships across all entity types |
| Python oracledb driver with connection pooling | 20ms queries (was 90s), 4500x speedup |
| 3 ordered deployment scripts (schema -> API -> jobs) | Idempotent, ordered, reproducible deployments |
| Concise SKILL.md (200 lines) + 6 topic docs | Navigable, maintainable documentation |
| Single ORACLE_MEMORY_GRAPH property graph | Cross-type graph traversal |
| SYSTEM_USERS table with roles (USER/ADMIN/SYSTEM) | Standard role-based access control |

---

## Breaking Changes

**This is NOT an upgrade.** There is no migration path from v1.x to v2.0. You must deploy on a fresh database or coexist with v1.x tables.

### Incompatible Schema

v2.0 introduces 10 new tables:

| New Table | Replaces |
|-----------|----------|
| ENTITIES | MEMORIES + MEMORY_NODES + KNOWLEDGE_CONCEPTS |
| ENTITY_EDGES | MEMORY_EDGES + MEMORY_RELATIONSHIPS + KNOWLEDGE_GRAPH |
| KNOWLEDGE_META | Columns from KNOWLEDGE_CONCEPTS |
| ENTITY_EMBEDDINGS | KNOWLEDGE_CONCEPTS.EMBEDDING + MEMORIES_VECTORS |
| ENTITY_ACCESS_LOG | AGENT_MEMORY_ACCESS |
| HARNESS_META | New - Harness template versioning and lifecycle |
| SYSTEM_CONFIG | FUSION_CONFIG + SESSION_CONFIG + CLEANUP_CONFIG |
| SYSTEM_USERS | MEMORY_SYSTEM_USERS |
| TAGS | KNOWLEDGE_TAGS |
| ENTITY_TAGS | KNOWLEDGE_CONCEPT_TAGS |

v1.x tables NOT part of v2.0: MEMORIES, MEMORY_NODES, MEMORY_EDGES, MEMORY_RELATIONSHIPS, MEMORY_NODE_PROPERTIES, MEMORY_EDGE_PROPERTIES, MEMORY_NODE_TAGS, MEMORY_TAG_ITEMS, MEMORY_METADATA_FIELDS, MEMORY_CONTENT_FIELDS, KNOWLEDGE_CONCEPTS, KNOWLEDGE_GRAPH, KNOWLEDGE_VERSIONS, KNOWLEDGE_TAGS, KNOWLEDGE_CONCEPT_TAGS, KNOWLEDGE_DISTILLATION_LOG, KNOWLEDGE_SEARCH_HISTORY, MEMORY_SYSTEM_USERS, MEMORIES_VECTORS, FUSION_CONFIG, SESSION_CONFIG, CLEANUP_CONFIG, RELATIONSHIP_TYPES, VIZ_USERS, VIZ_PERMISSIONS, VIZ_SESSIONS, VIZ_ACCESS_LOGS, VIZ_CONFIG, DESENSITIZE_LEVELS

### Python API Changes

v1.x (SQLcl subprocess):
```python
import subprocess
result = subprocess.run(['/path/to/sql', 'user/pass@dsn', '@script.sql'], capture_output=True)
```

v2.0 (oracledb driver):
```python
from scripts.lib.memory_api import create_memory
entity_id = create_memory("Title", "content", category="meeting")
```

All v1.x Python scripts are archived to `archive/legacy_scripts/`. None work with v2.0.

### Configuration Changes

v2.0 adds `embedding` and `security` sections to config.json, plus connection pool settings. See [docs/migration.md](docs/migration.md) for details.

---

## New Features in Detail

### 1. Unified Entity Architecture

ENTITIES uses a single `ENTITY_TYPE` column as discriminator:

| ENTITY_TYPE | Description | Replaces |
|-------------|-------------|----------|
| MEMORY | Short-term agent memories | MEMORIES + MEMORY_NODES |
| KNOWLEDGE | Long-term validated knowledge | KNOWLEDGE_CONCEPTS |
| TASK_OUTPUT | Task execution results | New |
| EXPERIENCE | Learned patterns and heuristics | New |
| HARNESS_TEMPLATE | Reusable agent execution blueprints | New |

Benefits:
- Cross-type relationships (memory -> knowledge derivation)
- Single query for all entity types or filtered by type
- Consistent visibility, tagging, and metadata across all types
- No data duplication between MEMORIES and MEMORY_NODES

### 2. Unified Edge Architecture

ENTITY_EDGES replaces three separate relationship tables with 10 unified edge types: DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS. Each edge carries `STRENGTH` (0-2) and `CONFIDENCE` (0-1) for weighted graph traversal.

### 3. oracledb Driver with Connection Pooling

| Metric | v1.x (SQLcl) | v2.0 (oracledb) | Improvement |
|--------|-------------|-----------------|-------------|
| Query latency | 90+ seconds | ~20ms | 4500x |
| Connection model | New process per query | Pool (min=2, max=5) | Reuse |
| Error handling | Parse stdout | Python exceptions | Type-safe |
| Bind variables | String concatenation | `:param` bind syntax | Injection-safe |
| Fetch LOBs | Manual | `fetch_lobs = False` | Automatic |

### 4. 3-Phase SQL Deployment

**Phase 1: `1_schema.sql`** - 16 tables, 25+ indexes, 1 property graph, 2 duality views
- `safe_ddl`/`safe_idx` helpers for idempotent re-runs
- `GENERATED BY DEFAULT AS IDENTITY` for auto-increment PKs
- JSON columns for TAGS, METADATA, ACCESSIBLE_TO, PROPERTIES
- CHECK constraints on all enum-like columns
- ON DELETE CASCADE on all FKs referencing ENTITIES

**Phase 2: `2_api.sql`** - 4 PL/SQL packages:
- `MEMORY_FUSION_ENGINE` - Merge similar memories, extract knowledge, decay priorities
- `KNOWLEDGE_BASE_API` - Validate, deprecate, version concepts; lineage queries
- `AGENT_PERMISSION_MANAGER` - Access control, session cleanup, collaboration
- `SESSION_CLEANUP` - Purge logs, archive entities, update tag counts

**Phase 3: `3_jobs.sql`** - 7 scheduler jobs:

| Job | Schedule | Action |
|-----|----------|--------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + priority decay |
| KNOWLEDGE_EXTRACTION_JOB | Daily 03:00 | Extract knowledge from patterns |
| SESSION_CLEANUP_JOB | Every 30 min | Cleanup expired sessions |
| ACCESS_LOG_PURGE_JOB | Weekly Sun 04:00 | Purge logs >90 days |
| TAG_COUNT_UPDATE_JOB | Daily 01:00 | Update tag usage counts |
| COLLAB_EXPIRY_JOB | Daily 00:30 | Expire stale collaboration requests |
| ENTITY_ARCHIVE_JOB | Weekly Sun 05:00 | Archive low-priority memories >180 days |

### 5. Python API Library (scripts/lib/)

8 modules with consistent patterns:
- Bind variables for all queries (no SQL injection)
- `execute_insert_returning_id` for INSERT...RETURNING
- `execute_query` returns `List[Dict[str, Any]]` with column names as keys
- `fetch_lobs = False` to avoid CLOB fetch issues
- Thread-safe connection pool with lazy initialization
- MERGE INTO for idempotent agent registration

### 6. Security Module

**DataMaskingService** - Context-aware sensitive data masking:
- 7 pattern types: email, phone, credit_card, ssn, api_key, ip_address, jwt_token
- 4 context levels: LOGGING, DEBUGGING, ANALYTICS, SHARING
- Deterministic pattern matching order (credit_card before phone to prevent overlap)
- Fallback `***MASKED***` for sensitive dict keys that don't match regex

**ReversibleEncryption** - Length-prefixed XOR encryption with PBKDF2 key derivation:
- Safe key rotation (decrypt all with old key, then re-encrypt with new key)
- Length-prefix encoding instead of zero-byte padding

**Password hashing** - PBKDF2-HMAC-SHA256 with configurable iterations (default: 100,000).

### 7. Unified Property Graph

ORACLE_MEMORY_GRAPH replaces v1's separate KNOWLEDGE_PROPERTY_GRAPH and MEMORY_PROPERTY_GRAPH. Enables cross-type graph traversal via SQL PGQ syntax.

### 8. JSON-Relational Duality Views

| View | Entity Type | Includes |
|------|-------------|----------|
| MEMORY_DV | MEMORY | Entity + edges |
| KNOWLEDGE_DV | KNOWLEDGE | Entity + knowledge_meta + edges |

### 9. Web Visualization Server (Refactored for v2.0)

- Knowledge page queries `ENTITIES WHERE ENTITY_TYPE='KNOWLEDGE'` instead of KNOWLEDGE_CONCEPTS
- Memory page queries `ENTITIES WHERE ENTITY_TYPE='MEMORY'` instead of MEMORY_NODES
- Edge queries use ENTITY_EDGES instead of MEMORY_EDGES/KNOWLEDGE_GRAPH
- Authentication uses SYSTEM_USERS instead of memory_system_users
- Node colors based on CATEGORY instead of NODE_TYPE/CONCEPT_TYPE
- **Agent Collaboration page** (`/agents`) — 3-tab dashboard: Agent Registry (status/permission badges), Active Sessions, Collaboration Requests
- **Task Plans page** (`/tasks`) — Status filter dropdown, keyword search, accordion-style plan list with expandable step tables, progress bars, summary stat badges
- 4-page navigation (Knowledge/Memory/Agents/Tasks) on all pages with active-state highlighting
- UTF-8 encoding fix via `_fix_encoding()` — auto-detects and corrects double-encoded Chinese characters returned by oracledb thin mode (AL32UTF8 double-encoding issue)
- `_sanitize_val()` helper for Decimal/datetime JSON serialization
- `_q()` generic query helper with automatic type sanitization and encoding correction
- Request exception handling (`do_GET` → `_do_GET` wrapper) prevents server crash on individual request failures

### 10. Documentation Restructure

| v1.x | v2.0 |
|------|------|
| SKILL.md (934 lines) | SKILL.md (~200 lines) |
| 12+ scattered .md files | 8 focused docs in docs/ |
| No privilege analysis | docs/minimum-privileges.md |
| No API reference | docs/api-reference.md |
| No migration guide | docs/migration.md |
| No harness guide | docs/harness.md |

### 11. Harness Template System

A new `ENTITY_TYPE='HARNESS_TEMPLATE'` enables reusable agent execution blueprints. Each template is stored as an ENTITY with configuration in the METADATA JSON column and lifecycle tracking in the HARNESS_META table.

**Template structure** (stored in ENTITIES.METADATA):
- `prompt_templates` — Parameterized prompt skeletons with `{variable}` slot substitution
- `tool_bindings` — Tool name + access permission pairs (resolved from 5 built-in tool sets)
- `memory_access` — short_term, long_term, compaction, access_policy flags
- `guardrails` — max_iterations, max_execution_time, context_window_strategy, content_moderation, pii_filtering, max_retry_limit
- `evaluation` — output_format, quality_threshold
- `variables` — Default values for slot substitution

**Key capabilities:**
- **Variable substitution**: `{role}`, `{domain}`, etc. in prompts → resolved at instantiation
- **Template inheritance**: Child templates `DERIVES_FROM` parent via ENTITY_EDGES, deep-merge override
- **Built-in tool sets**: memory_tools, knowledge_tools, agent_tools, security_tools, task_tools
- **Guardrail presets**: conservative (5 iterations/60s), balanced (15/300s), aggressive (50/900s)
- **Lifecycle**: DRAFT → PUBLISHED → DEPRECATED → ARCHIVED (tracked in HARNESS_META)
- **Validation**: `validate_template()` checks prompt completeness, variable consistency, tool duplicates, guardrail sanity

**5 built-in templates** (seeded by `4_harness_templates.sql`):

| Template | Category | Tool Sets | Guardrail Preset |
|----------|----------|-----------|-----------------|
| Research Analyst | research | knowledge_tools + memory_tools | balanced |
| Code Assistant | development | knowledge_tools + task_tools | balanced |
| Data Analyst | analytics | knowledge_tools + memory_tools | conservative |
| Task Planner | orchestration | task_tools + agent_tools | balanced |
| Security Auditor | security | security_tools + knowledge_tools | conservative |

**Python API** (12 functions in `scripts/lib/harness_api.py`):

| Function | Purpose |
|----------|---------|
| `create_template()` | Create template with prompts, tools, guardrails, variables |
| `get_template()` | Get template with full metadata and HARNESS_META |
| `list_templates()` | List templates with optional category/status filters |
| `update_template()` | Update entity fields and template status |
| `delete_template()` | Delete template + HARNESS_META + edges |
| `resolve_template()` | Recursively resolve inheritance chain (deep merge) |
| `instantiate_template()` | Resolve + substitute variables + apply overrides → runtime config |
| `derive_template()` | Create child template from parent with overrides |
| `validate_template()` | Check completeness and consistency |
| `get_template_lineage()` | Get parent/child templates via DERIVES_FROM edges |
| `publish_template()` | Set template_status to PUBLISHED |
| `deprecate_template()` | Set template_status to DEPRECATED with reason |

**New deployment phase**: `4_harness_templates.sql` — creates HARNESS_META table, extends CK_ENTITY_TYPE constraint, seeds 5 templates.

**Bug fix**: Oracle `oracledb` driver returns `decimal.Decimal` for NUMBER columns. Added `_sanitize_decimals()` to convert Decimal → int/float throughout the harness API for JSON serialization compatibility.

---

## File Changes

### New Files (31)

```
scripts/deploy/1_schema.sql
scripts/deploy/2_api.sql
scripts/deploy/3_jobs.sql
scripts/deploy/4_harness_templates.sql
scripts/lib/__init__.py, config.py, connection.py
scripts/lib/memory_api.py, knowledge_api.py, agent_api.py
scripts/lib.task_plan_api.py, security.py
scripts/lib/harness_api.py
scripts/tests/test_connection.py, test_memory.py
scripts/tests/test_knowledge.py, test_agent.py
scripts/tests/test_security.py, test_harness.py, test_all.py
docs/architecture.md, api-reference.md, deployment.md
docs/migration.md, security.md, visualization.md
docs/minimum-privileges.md, harness.md
RELEASE_NOTES_v2.0.0.md
README.md (rewritten), SKILL.md (rewritten), config.json (updated)
start_web_server.sh (rewritten: start/stop/restart/status/config/log)
```
scripts/deploy/1_schema.sql
scripts/deploy/2_api.sql
scripts/deploy/3_jobs.sql
scripts/lib/__init__.py, config.py, connection.py
scripts/lib/memory_api.py, knowledge_api.py, agent_api.py
scripts/lib/task_plan_api.py, security.py
scripts/tests/test_connection.py, test_memory.py
scripts/tests/test_knowledge.py, test_agent.py
scripts/tests/test_security.py, test_all.py
docs/architecture.md, api-reference.md, deployment.md
docs/migration.md, security.md, visualization.md
docs/minimum-privileges.md
RELEASE_NOTES_v2.0.0.md
README.md (rewritten), SKILL.md (rewritten), config.json (updated)
```

### Archived Files

- 5 release notes -> `archive/release_notes/`
- 2 test reports -> `archive/test_reports/`
- 8 legacy docs -> `archive/legacy_docs/`
- 13 legacy Python scripts + 15 legacy SQL scripts -> `archive/legacy_scripts/`

### Modified Files

- `viz_server_local_js.py` - Queries updated for ENTITIES/ENTITY_EDGES/SYSTEM_USERS; fixed f-string `{SESS_TTL}` NameError; added request exception handling; added Agent/Tasks pages, `_fix_encoding()` UTF-8 fix, `_sanitize_val()`/`_q()` helpers
- `start_web_server.sh` - Rewritten as control script: `start/stop/restart/status/config/log` commands; auto-detects Python 3.14; reads `config.json`; PID file management; daemon mode with log file
- `config.json` - Added embedding and security sections

---

## Bug Fixes During v2.0 Development

| Bug | Fix |
|-----|-----|
| `oracledb.NUMBER.getvalue()` returns list | Handle both list and scalar in connection.py |
| `SYSTIMESTAMP` passed as bind variable | Use SQL literal in SET clause |
| Oracle reserved word `:desc` as bind variable | Renamed to `:adesc` in agent_api.py |
| Phone regex matching credit card numbers | Reordered pattern matching order |
| Short sensitive strings not masked | Removed `len(text) < 10` guard |
| Sensitive dict values not masked when no regex match | Added `***MASKED***` fallback |
| Key rotation corrupts ciphertext | Decrypt all first, then re-encrypt |
| ReversibleEncryption zero-byte padding | Replaced with length-prefix encoding |
| AGENT_PERMISSION_LOG.CREATED_AT doesn't exist | Use CHANGED_AT (v1 column name) |
| viz_server f-string `{sess_ttl}` NameError | Fixed to `{SESS_TTL}` (correct variable name) |
| viz_server crashes on any request | Added `do_GET` → `_do_GET` exception wrapper to prevent server death |
| `decimal.Decimal` not JSON serializable | Added `_sanitize_decimals()` in harness_api.py, `_sanitize_val()` in viz_server for Oracle NUMBER columns |
| oracledb thin mode double-encodes UTF-8 Chinese | Added `_fix_encoding()` — detects CJK vs Latin-1 range, applies `bytes([ord(c)]).decode('utf-8')` fix |
| viz_server tasks page missing `<script>` tag | JS code rendered as text — added `<script>` wrapper around i18n/loadTasks code |
| viz_server agents/tasks API returns 500 on datetime | Added `default=str` to `json.dumps()` and `_sanitize_val()` for datetime/date types |

---

## Deployment Guide

### Fresh Install (Required)

```bash
# 1. Clone
git clone https://github.com/Haiwen-Yin/oracle-memory-system.git
cd oracle-memory-system

# 2. Deploy schema (4 phases)
sql user/pass@//host:port/service @scripts/deploy/1_schema.sql
sql user/pass@//host:port/service @scripts/deploy/2_api.sql
sql user/pass@//host:port/service @scripts/deploy/3_jobs.sql
sql user/pass@//host:port/service @scripts/deploy/4_harness_templates.sql

# 3. Install Python dependencies
pip install oracledb

# 4. Configure
# Edit config.json with your database credentials

# 5. Test
cd scripts && python -m tests.test_all

# 6. Start visualization
./start_web_server.sh start   # daemon mode
# Other commands: stop, restart, status, config, log
```

### Minimum Database Privileges

See [docs/minimum-privileges.md](docs/minimum-privileges.md). Required:
- CREATE SESSION, TABLE, SEQUENCE, PROCEDURE, VIEW, TYPE, JOB, PROPERTY GRAPH
- QUOTA UNLIMITED ON tablespace (not UNLIMITED TABLESPACE)
- **Remove DBA role** for production

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

## License

Apache License 2.0 - Copyright (c) 2026 Haiwen Yin
