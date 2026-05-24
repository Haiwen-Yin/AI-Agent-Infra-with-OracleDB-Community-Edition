# Oracle Memory System v2.3.0 Release Notes

**Release Date**: 2026-05-24  
**Author**: Haiwen Yin  
**License**: Apache License 2.0

---

## Overview

v2.3.0 is a **major feature release** adding three new subsystems: Spec Driven Development (SDD), Agent Elastic Management, and Collaboration Groups. It extends the schema with 5 new tables, 2 new JRD views, 2 new PL/SQL packages, 2 new scheduler jobs, 3 new Python modules, and 2 new visualization pages.

**Backward-compatible with v2.2.x** — uses ADD PARTITION + ADD COLUMN; no breaking changes.

---

## New Features

### 1. Spec Driven Development (SDD)

Specifications as first-class entities stored as ENTITIES subtype `SPEC`:

| Component | Description |
|-----------|-------------|
| SPEC_META table | Reference-partitioned from ENTITIES; stores version, status, acceptance_criteria, `"CONSTRAINTS"` |
| SPEC_PLAN_LINKS table | Many-to-many spec↔plan with LINK_TYPE: DRIVES, VALIDATES, CONSTRAINS, EXTENDS |
| SPEC_DV view | JRD updatable duality view for spec entities |
| SPEC_MANAGER package | 8 PL/SQL subprograms: create_spec, get_spec, update_spec, validate_spec, derive_spec, create_plan_from_spec, link_spec_to_plan, get_spec_plan_links |
| spec_api.py | 10 Python functions for full SDD lifecycle |

**Spec lifecycle**: DRAFT → PROPOSED → ACCEPTED → IMPLEMENTED → DEPRECATED

### 2. Agent Elastic Management

Two new agent states for resource optimization:

| State | Description | Context | Use Case |
|-------|-------------|---------|----------|
| DORMANT | Temporary hibernate | Preserved (agent identity + session data retained) | Agent on break, cost optimization |
| POOL | Stateless idle | Follows user via credentials | On-demand agent assignment |

| Component | Description |
|-----------|-------------|
| AGENT_CREDENTIALS table | Encrypted credential storage with ReversibleEncryption; auto-expiry; SCOPE JSON |
| AGENT_REGISTRY +5 columns | CREATED_BY_AGENT_ID, AGENT_ROLE, CURRENT_USER_ID, POOL_CONFIG, LAST_ACTIVE_AT |
| AGENT_SESSION +1 column | LAST_ACTIVE_AT for dormant timeout tracking |
| DORMANT_AGENT_JOB | Every 30 min; auto-hibernates agents inactive beyond dormant_timeout_min |
| CREDENTIAL_CLEANUP_JOB | Daily 02:00; purges expired/revoked credentials |
| agent_api.py +8 functions | issue_credential, verify_credential, get_credentials_for_user, revoke_credential, hibernate_agent, wake_agent, register_pool_agent, assign_pool_agent |

**Credential SCOPE format**: `{"access_level": "FULL|READ_ONLY|RESTRICTED", "restricted_domains": [...], "max_clearance": "PUBLIC|CONFIDENTIAL|SECRET|TOP_SECRET"}`

**POOL agent matching**: `skills_tags` intersection between agent capabilities and user requirements; best match selected.

### 3. Collaboration Groups

Mode C collaboration model with group-level shared workspace:

| Component | Description |
|-----------|-------------|
| COLLAB_GROUPS table | Group definitions with GROUP_TYPE, SHARING_POLICY (OPEN/MODERATED/RESTRICTED), STATUS |
| COLLAB_GROUP_MEMBERS table | Membership with ROLE (LEAD/CONTRIBUTOR/OBSERVER) |
| COLLAB_GROUP_DV view | JRD updatable duality view |
| COLLAB_GROUP_MANAGER package | 6 PL/SQL subprograms |
| collab_api.py | 10 Python functions |

**Workspace model**: Each group gets a shared Workspace (TYPE=COLLAB_GROUP). LEAD and CONTRIBUTOR members also get auto-created personal Workspaces (TYPE=PERSONAL_IN_GROUP). OBSERVER members do not.

---

## Schema Changes

### New Tables (5)

| Table | Partitioning | Key Columns |
|-------|-------------|-------------|
| SPEC_META | REFERENCE from ENTITIES | SPEC_ID, ENTITY_TYPE, SPEC_VERSION, STATUS, ACCEPTANCE_CRITERIA (JSON), "CONSTRAINTS" (JSON) |
| SPEC_PLAN_LINKS | Non-partitioned | SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH; UK=(SPEC_ID,PLAN_ID,LINK_TYPE) |
| AGENT_CREDENTIALS | Non-partitioned | CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE, CREDENTIAL_VALUE, SCOPE (JSON), EXPIRES_AT |
| COLLAB_GROUPS | Non-partitioned | GROUP_ID, GROUP_NAME, GROUP_TYPE, WORKSPACE_ID, SHARING_POLICY, STATUS |
| COLLAB_GROUP_MEMBERS | Non-partitioned | MEMBER_ID, GROUP_ID, AGENT_ID, ROLE, PERSONAL_WORKSPACE_ID |

### Extended Tables (3)

| Table | New Columns |
|-------|------------|
| AGENT_REGISTRY | CREATED_BY_AGENT_ID, AGENT_ROLE, CURRENT_USER_ID, POOL_CONFIG (JSON), LAST_ACTIVE_AT |
| AGENT_SESSION | LAST_ACTIVE_AT |
| WORKSPACES | +COLLAB_GROUP and PERSONAL_IN_GROUP workspace types |

### New JRD Views (2)

- **SPEC_DV** — updatable; root=ENTITIES(SPEC), nested=SPEC_META, SPEC_PLAN_LINKS
- **COLLAB_GROUP_DV** — updatable; root=COLLAB_GROUPS, nested=COLLAB_GROUP_MEMBERS

### New Partitions

- ENTITIES gets SPEC partition (LIST by ENTITY_TYPE)
- SPEC_META gets reference partition from ENTITIES

### New System Config Entries

- `dormant_timeout_min` = 60 (minutes before auto-hibernate)
- `credential_encryption_key` = auto-generated (for ReversibleEncryption)

---

## PL/SQL Changes

### New Packages (2)

| Package | Subprograms |
|---------|------------|
| SPEC_MANAGER | create_spec, get_spec, update_spec, validate_spec, derive_spec, create_plan_from_spec, link_spec_to_plan, get_spec_plan_links |
| COLLAB_GROUP_MANAGER | create_group, get_group, update_group, add_member, remove_member, get_group_members |

### New Scheduler Jobs (2)

| Job | Schedule | Description |
|-----|----------|-------------|
| DORMANT_AGENT_JOB | Every 30 min | Auto-hibernate agents past dormant_timeout_min |
| CREDENTIAL_CLEANUP_JOB | Daily 02:00 | Purge expired/revoked credentials |

---

## Python API Changes

### New Modules (2)

- **spec_api.py** (10 functions, 344 lines)
- **collab_api.py** (10 functions, 229 lines)

### Extended Module (1)

- **agent_api.py** +8 functions (credentials, hibernate/wake, pool management)

### New Test Files (3)

- **test_spec.py** (9 tests)
- **test_collab.py** (12 tests)
- **test_credential.py** (9 tests)

---

## Visualization Changes

### New Pages (2)

- **Specs** (`/specs`) — Spec list with detail tabs, plan linkage display
- **Collab** (`/collab`) — Group list, members, shared memory

### Enhanced Pages

- **Knowledge/Memory** — Inline row expansion for List view detail (replaces sidebar detail panel); Graph view retains right-side detail panel with close button
- **All 8 pages** — Bilingual sidebar with data-zh/data-en on all nav links including Specs/Collab
- **Login** — Version badge updated to v2.3.0

### New API Endpoints

- `GET /api/specs` — List specs with optional status filter
- `GET /api/collab` — List collaboration groups
- Stats API now includes `spec_count` and `collab_count`

---

## Bug Fixes

- Password verification now performs actual SHA256 hash comparison (was prefix-only check)
- CONSTRAINTS reserved word properly double-quoted in all SQL references
- oracledb thin mode named bind variables on JSON columns cause ORA-01745; switched to positional/short bind names
- SYSTEM_USERS table now precedes AGENT_REGISTRY in DDL (FK dependency)
- Truncated IDs show full content on hover (title attribute)
- Graph view detail panel auto-closes when switching to List view

---

## Known Issues & Workarounds

| Issue | Workaround |
|-------|-----------|
| `CONSTRAINTS` is Oracle reserved word | Use double-quote `"CONSTRAINTS"` in all SQL |
| Named binds (`:uid`, `:aid`) cause ORA-01745 on AGENT_CREDENTIALS | Use positional (`:1`,`:2`) or short names (`:b1`,`:b2`) |
| PL/SQL `JSON_OBJECT` VALUE does not support `FORMAT JSON` | Use `RETURN VARCHAR2` instead of `RETURN JSON` |
| `JSON_MERGEPATCH` causes OSON v2 error | Use `JSON_TRANSFORM` instead |
| Reference-partitioned tables cannot DISABLE constraints | Constraints always enforced (ORA-14650) |

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
  Spec:         9/9 PASS
  Collab:      12/12 PASS
  Credential:   9/9 PASS
Overall: 99/99 ALL PASSED
```

---

## Upgrade from v2.2.x

v2.3.0 is backward-compatible. Upgrade steps:

1. Run `1_schema.sql` — adds new tables, partitions, columns (uses `safe_ddl` helpers)
2. Run `2_api.sql` — creates new PL/SQL packages
3. Run `3_jobs.sql` — adds new scheduler jobs
4. Update Python files — copy new `spec_api.py`, `collab_api.py`, updated `agent_api.py`
5. Update visualization — copy new `server.py`, `specs.html`, `collab.html`

No data migration needed. Existing v2.2.x data is fully compatible.

---

## Statistics

| Metric | v2.2.1 | v2.3.0 | Delta |
|--------|--------|--------|-------|
| Tables | 22 | 27 | +5 |
| JRD Views | 4 | 6 | +2 |
| PL/SQL Packages | 5 | 7 | +2 |
| Scheduler Jobs | 9 | 11 | +2 |
| Python Modules | 10 | 12 | +2 |
| API Functions | ~80 | ~99 | +19 |
| Test Files | 9 | 12 | +3 |
| Tests | 61 | 99 | +38 |
| Visualization Pages | 6 | 8 | +2 |
