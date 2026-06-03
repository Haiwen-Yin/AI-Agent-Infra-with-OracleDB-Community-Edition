# Release Notes — v3.1.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-05-30

License: Apache License 2.0

---

## Overview

The project formerly known as "Oracle AI Database Memory System" (oracle-memory-by-yhw) has been renamed to **AI Agent Infra with OracleDB**, reflecting its evolution from a pure memory system to a comprehensive AI Agent infrastructure architecture. This is the inaugural release of the **Community Edition** (Apache 2.0), shipping alongside the Enterprise Edition (BSL 1.1).

v3.1.0 introduces three major subsystems: **Portal User System**, **Skill Storage & Distribution** (with direct download), and **Encrypted Database Credentials** — all built on Oracle 26ai with JSON Relational Duality Views, reference partitioning, and PL/SQL packages.

> **Note**: The Community Edition does not include LDAP authentication, Skill one-time-token distribution, or Workspace Context Audit. These are Enterprise Edition features.

---

## New Features

### 1. Portal User System

A complete user-facing Portal, fully independent from the admin Dashboard:

- **Portal Login** (`/portal/login`) — Register/Login dual-tab. Root `/` redirects to Portal. "Admin Dashboard" link in top-right corner.
- **Portal Chat** (`/portal/chat`) — Sidebar with user info (username + auth type label), session list with rename/delete, new chat button. Main chat area with simulated replies.
- **Session Management** — New chat creates `AGENT_SESSION` + `CONVERSATION` workspace. Switch between sessions. Rename via `WORKSPACE_ALIAS`. Delete with cascading cleanup.
- **Auto-Naming** — New sessions default to "New Chat"; first user message auto-renames to first 60 chars.
- **Agent Pool** — `assign_random_pool_agent()` randomly selects from POOL; `hibernate_agent()` returns agent to POOL state.
- **Agent Timeout Auto-Recall** — `DORMANT_AGENT_JOB` (every 30 min) checks `LAST_ACTIVE_AT` against `dormant_timeout_min` (default 30 min) in `SYSTEM_CONFIG`. Idle agents auto-recalled to POOL. Configurable via SQL:
  ```sql
  UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = '10' WHERE CONFIG_KEY = 'dormant_timeout_min';
  COMMIT;
  ```

### 2. Skill Storage & Distribution

Database-backed Skill registry with direct resource download (no token flow):

- **Skill Registry** — `SKILL_META` table (reference-partitioned, with `SKILL_DESCRIPTION`, `RESOURCE_SERVER_HOST` columns), `SKILL_DV` JRD view.
- **Skill API** — `skill_api.py` (9 functions: register, get, list, update, delete, upload_resource, get_resource_info, delete_resource, resolve_dependencies, validate, deprecate). Update supports title + description.
- **Skill Parser** — `skill_parser.py` — ZIP package parser with `_meta.json` > YAML frontmatter > `## Metadata` section priority.
- **Skill Storage** — `skill_storage.py` — File storage with server hostname+IP tracking, `read_resource_content()` returns ZIP bytes.
- **Agent-Facing API** — `skill_acquire_api.py` (4 functions: discover_skills, acquire_skill_text, acquire_skill_resource, acquire_skill_full). Public, no auth required. Routes: `/api/agent/skills`, `/api/agent/skill/{id}/acquire`.
- **Two-Step Skill Creation** — Upload ZIP → auto-parse metadata → editable form → confirm create.
- **Dashboard Resource Download** — Direct download (no token), repacked as `{skill_name}-{version}.zip`.

> **Note**: Community Edition does not include `SKILL_ACCESS_TOKEN` table, `skill_token_api.py`, or `SKILL_MANAGER` PL/SQL package. Skill resource download is direct without token authentication.

### 3. Encrypted Database Credentials

- **connection_crypto.py** — Master key resolution (`MASTER_DB_KEY` env > `~/.oracle-infra/master.key` > auto-generate). AES-256-GCM encryption.
- **Auto-Encrypt** — `config.json` database credentials encrypted on first run; plaintext keys removed.
- **Transparent Decryption** — `config.py` `_decrypt_database_section()` decrypts at runtime.

### 4. Community Configuration

`config.json` now supports:
- `enterprise` section — license_type: community (for API compatibility)
- Encrypted `database._encrypted` field

---

## Database Schema

### Tables (28)

| Group | Table | Partitioning |
|-------|-------|-------------|
| Core | ENTITIES | RANGE(YEAR) |
| | ENTITY_TAGS | REF(ENTITIES) |
| | ENTITY_EDGES | REF(ENTITIES) |
| | ENTITY_EMBEDDINGS | REF(ENTITIES) |
| Agent | AGENT_REGISTRY | HASH(AGENT_ID) |
| | AGENT_SESSIONS | HASH(SESSION_ID) |
| | AGENT_CREDENTIALS | HASH(CREDENTIAL_ID) |
| | AGENT_COLLABORATIONS | HASH(COLLAB_ID) |
| Workspace | WORKSPACES | HASH(WORKSPACE_ID) |
| | WORKSPACE_TASKS | REF(WORKSPACES) |
| | WORKSPACE_CONTEXT | HASH(WORKSPACE_ID) |
| Knowledge | KNOWLEDGE_META | REF(ENTITIES) |
| | KNOWLEDGE_REVIEWS | RANGE(CREATED_AT) |
| Spec | SPEC_META | REF(ENTITIES) |
| | SPEC_PLAN_LINKS | — |
| Harness | HARNESS_META | REF(ENTITIES) |
| System | SYSTEM_CONFIG | — |
| | SYSTEM_USERS | HASH(USER_ID) |
| | ACCESS_LOG | RANGE(ACCESS_TIME) |
| Skill | SKILL_META | REF(ENTITIES) |

> **Note**: Community Edition does not include `SKILL_ACCESS_TOKEN`, `LDAP_CONFIG`, `LDAP_SYNC_LOG`, `CONTEXT_AUDIT_LOG`, or `CONTEXT_AUDIT_RULES` tables.

### PL/SQL Packages (9)

| Package | Subprograms | Description |
|---------|-------------|-------------|
| MEMORY_FUSION_ENGINE | 7 | Memory fusion, knowledge extraction, decay |
| KNOWLEDGE_BASE_API | 5 | Knowledge management, review scheduling |
| AGENT_PERMISSION_MANAGER | 5 | Permission management, session cleanup |
| SESSION_CLEANUP | 4 | Session cleanup, log archiving |
| WORKSPACE_MANAGER | 10 | Workspace management, context maintenance |
| SPEC_MANAGER | 8 | Spec management, plan association |
| COLLAB_GROUP_MANAGER | 6 | Collaboration group management |
| EMBEDDING_MANAGER | 5 | Embedding generation, query, cosine similarity |
| CREDENTIAL_MANAGER | 4 | Credential issuance, verification, cleanup |

> **Note**: Community Edition does not include `LDAP_AUTH_MANAGER`, `SKILL_MANAGER`, or `CONTEXT_AUDIT_MANAGER` PL/SQL packages.

### Scheduler Jobs (12)

| Job | Schedule | Description |
|-----|----------|-------------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + decay old |
| KNOWLEDGE_EXTRACTION_JOB | Daily 03:00 | Extract knowledge from memory |
| KNOWLEDGE_REVIEW_JOB | Daily 06:00 | Knowledge review & validation |
| SESSION_CLEANUP_JOB | Every 30 min | Clean expired sessions |
| ACCESS_LOG_PURGE_JOB | Sunday 04:00 | Purge access logs (90 days) |
| ENTITY_ARCHIVE_JOB | Sunday 05:00 | Archive old entities (180 days) |
| COLLAB_EXPIRY_JOB | Daily 00:30 | Process collaboration requests |
| WORKSPACE_CLEANUP_JOB | Daily 04:00 | Archive abandoned workspaces (30 days) |
| STALE_WORKSPACE_DETECT_JOB | Hourly | Detect workspaces with no active sessions |
| DORMANT_AGENT_JOB | Every 30 min | Auto-recall idle agents to POOL |
| CREDENTIAL_CLEANUP_JOB | Daily 02:00 | Clean expired credentials |
| EMBEDDING_GENERATION_JOB | Every 2 hours | Auto-generate missing embeddings |

> **Note**: Community Edition does not include `LDAP_SYNC_JOB`, `SKILL_TOKEN_CLEANUP_JOB`, `CONTEXT_AUDIT_JOB`, or `IDLE_PATTERN_DETECT_JOB`.

### JRD Duality Views (7)

| View | Mode | Root Table | Nested Objects |
|------|------|------------|----------------|
| MEMORY_DV | Updatable | ENTITIES(MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | Updatable | ENTITIES(KNOWLEDGE) | KNOWLEDGE_META, ENTITY_TAGS, ENTITY_EDGES |
| WORKSPACE_DV | Updatable | WORKSPACES | WORKSPACE_TASKS |
| CONTEXT_DV | Read-only | WORKSPACE_CONTEXT | — |
| SPEC_DV | Updatable | ENTITIES(SPEC) | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV | Updatable | COLLAB_GROUPS | COLLAB_GROUP_MEMBERS |
| SKILL_DV | Updatable | ENTITIES(SKILL) | SKILL_META |

---

## Changes

- **Product rename** — All references updated from "Oracle Memory System" / "oracle-memory-by-yhw" to "AI Agent Infra with OracleDB"
- **SKILL.md** — name=`ai-agent-infra-community`
- **hibernate_agent()** — STATUS='DORMANT' → STATUS='POOL'; released agents immediately available for reassignment
- **DORMANT_AGENT_JOB** — Sets STATUS='POOL' instead of DORMANT
- **Inline detail expansion** — All list pages converted from right-side panel to inline row expansion
- **Graph explorer** — Navigation buttons hidden
- **Portal chat user info** — Username at 1rem bold; auth type shown below
- **Portal login i18n** — Auth mode dropdown options switch zh/en
- **config.py** — Rewritten with `EnterpriseConfig` dataclass
- **security.py** — New `ConfigEncryption` class with PBKDF2-HMAC-SHA512 + authenticated encryption
- **connection.py** — Transparent decryption of database credentials
- **NOTICE** — Updated product name

---

## Bug Fixes

- oracledb returns lowercase column names; `workspace_alias`/`workspace_name` key access fixed in auto-rename logic
- `toggleDetail()` now checks if row already expanded before calling `closeDetail()`, preventing double-toggle bug

---

## Breaking Changes

- Root `/` now redirects to Portal login (was Dashboard login)
- Agent STATUS 'DORMANT' replaced by 'POOL'
- `config.json` database section auto-encrypted on first run; plaintext keys removed

---

## Upgrade from v2.x

1. Deploy new schema objects:
   ```bash
   sql user/password@//host:port/service @scripts/deploy/1_schema.sql
   sql user/password@//host:port/service @scripts/deploy/2_api.sql
   sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
   ```
2. Update `config.json` with `enterprise` section (license_type: community)
3. First server run auto-encrypts database credentials
4. Existing agents with STATUS='DORMANT' should be updated:
   ```sql
   UPDATE AGENT_REGISTRY SET STATUS = 'POOL' WHERE STATUS = 'DORMANT';
   COMMIT;
   ```

---

## System Requirements

- Oracle Database 23ai+ (tested on 26ai)
- Python 3.8+ with `oracledb` package
- SQLcl 26.1+ (for SQL script deployment)
