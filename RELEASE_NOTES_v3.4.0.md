# Release Notes — v3.4.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-08

License: Apache License 2.0

---

## Overview

v3.4.0 replaces Oracle VPD (Virtual Private Database) with **Oracle Deep Data Security (Deep Sec)** — a declarative, zero-trust security framework using Data Grants, Mandatory Access Control (MAC), and End User Context. This eliminates three critical security vulnerabilities found in the v3.3.0 VPD implementation.

---

## Security Vulnerabilities Fixed

| # | Vulnerability | VPD Behavior | Deep Sec Fix |
|---|--------------|-------------|--------------|
| 1 | NULL context = full exposure | VPD predicate returns `1=1` when `SYS_CONTEXT` is NULL | Zero trust: no Data Grant match = no data |
| 2 | Python never calls SET_AGENT_CONTEXT | `apply_agent_context()` was a no-op | Now calls `SET_AGENT_CONTEXT.set_agent_id()` via PL/SQL per connection |
| 3 | SYSTEM_CONFIG exposed to AGENT_API | `GRANT SELECT ON SYSTEM_CONFIG TO AGENT_API` | Removed; Data Grant restricts to `admin_data_role` only |

---

## New Features

### 1. Oracle Deep Data Security (`6_deep_sec_policy.sql`)

Replaces `6_vpd_policy.sql` with a comprehensive Deep Sec policy:

| Component | Count | Description |
|-----------|-------|-------------|
| Application Context | 1 | `AGENT_CTX` with `SET_AGENT_CONTEXT` package |
| End User Context | 1 | `agent_context` with `o:onFirstRead` lazy-load callback |
| Data Roles | 3 | `admin_data_role`, `agent_data_role`, `pool_agent_data_role` |
| Data Grants | 20 | Row-level, column masking, admin-only, public-read, pool minimum |
| MAC Tables | 7 | `SET USE DATA GRANTS ONLY` prevents view bypass |
| End Users | Per-agent | Deep Sec End Users for Direct Logon (auto-created via `END_USER_MANAGER`) |
| Session Role | 1 | `DEEP_SEC_SESSION_ROLE` (CREATE SESSION for End Users) |
| END_USER_MANAGER | 1 | PL/SQL package for End User lifecycle management |

### 2. Data Grants Architecture

| Grant | Table | Level | Role | Description |
|-------|-------|-------|------|-------------|
| ws_ctx_admin_access | WORKSPACE_CONTEXT | Full | admin_data_role | Admin full access |
| ws_ctx_agent_access | WORKSPACE_CONTEXT | Row | agent_data_role | Own workspace + collab groups |
| entities_admin_access | ENTITIES | Full | admin_data_role | Admin full access |
| entities_agent_own | ENTITIES | Row | agent_data_role | Public + own private + shared in workspace |
| cred_admin_access | AGENT_CREDENTIALS | Full | admin_data_role | Admin full access |
| cred_agent_own | AGENT_CREDENTIALS | Cell | agent_data_role | Own rows, CREDENTIAL_VALUE masked |
| config_admin_only | SYSTEM_CONFIG | Full | admin_data_role | Admin only (no agent access) |
| registry_admin_access | AGENT_REGISTRY | Full | admin_data_role | Admin full access |
| registry_agent_own | AGENT_REGISTRY | Row | agent_data_role | Own agent row only |
| skill_admin_access | SKILL_META | Full | admin_data_role | Admin full access |
| skill_agent_read | SKILL_META | Table | agent_data_role | All skills read |
| skill_pool_read | SKILL_META | Table | pool_agent_data_role | All skills read |
| registry_pool_own | AGENT_REGISTRY | Row | pool_agent_data_role | Own agent row only |
| branch_admin_access | CONTEXT_BRANCHES | Full | admin_data_role | Admin full access |
| branch_agent_access | CONTEXT_BRANCHES | Row | agent_data_role | Own workspace + collab groups |
| task_admin_access | TASK_PLANS | Full | admin_data_role | Admin full access |
| task_agent_access | TASK_PLANS | Row | agent_data_role | Own tasks + collab branches |
| ws_ctx_agent_insert | WORKSPACE_CONTEXT | INSERT | agent_data_role | WHERE 1=1 |
| ws_agent_access | WORKSPACES | SELECT | agent_data_role | WHERE CURRENT_AGENT_ID or collab group matches |
| ws_agent_update | WORKSPACES | UPDATE | agent_data_role | WHERE 1=1 |

### 3. Connection Context Management (`connection.py`)

- `get_connection_for_agent()` — auto-selects End User connection (Deep Sec) or AIADMIN pool (admin)
- `get_end_user_connection(agent_id)` — connects as Deep Sec End User with Data Grant enforcement
- `_agent_id_to_end_user_name(agent_id)` — maps agent_id to End User name (`UPPER(REPLACE(agent_id, '-', '_'))`)
- `apply_agent_context(conn, agent_id)` — calls `SET_AGENT_CONTEXT.set_agent_id()` (fallback for AIADMIN connections)
- `clear_agent_context(conn)` — clears context on connection release
- `execute()`/`execute_query()`/etc. — now use `get_connection_for_agent()` for automatic Deep Sec routing

### 4. Agent Registration with Deep Sec (`agent_api.py`)

- `register_agent()` — now calls `_ensure_end_user(agent_id)` after MERGE into AGENT_REGISTRY
- `_ensure_end_user(agent_id)` — calls `END_USER_MANAGER.ensure_end_user()` to auto-create Deep Sec End User
- End User password stored in `SYSTEM_CONFIG` key `end_user_pwd.{agent_id}`

### 4. Updated Grants (`4_grants.sql`)

- Removed `GRANT SELECT ON SYSTEM_CONFIG TO AGENT_API`
- Removed `CREATE SYNONYM AGENT_API.SYSTEM_CONFIG`
- Added 14 Deep Sec system privileges to AIADMIN
- Added `CREATE ANY CONTEXT` to AIADMIN

---

## Key Architecture Decision: Direct Logon with Local End Users

Deep Sec enforcement is implemented via Oracle's Direct Logon mode with locally managed End Users:

| Method | Description | IAM Required | Status |
|--------|-------------|-------------|--------|
| **Direct Logon** | End User connects directly with password | No | **Chosen** |
| Application-mediated | `set_end_user_security_context()` API | Yes (OCI_IAM/Azure AD) | Not needed |
| PL/SQL callback (Method A) | `o:onFirstRead` + `SYS_CONTEXT` | No | Retained as fallback |

Direct Logon was chosen because:
- No external IAM (OCI IAM or Azure AD) required — works with local passwords
- No TCPS required — works on standard TCP port 1521
- `ORA_END_USER_CONTEXT.username` automatically returns End User name for Data Grant predicates
- Each agent gets its own End User identity for strict data isolation
- `register_agent()` auto-creates End User — zero additional setup for new agents

---

## Breaking Changes

- **v3.3.0 VPD (Virtual Private Database / DBMS_RLS) is DEPRECATED and removed**. The entire VPD security layer has been replaced by Oracle Deep Data Security (Deep Sec). The old `6_vpd_policy.sql` script **no longer exists** and must not be used.
- `6_vpd_policy.sql` is **removed** — replaced by `6_deep_sec_policy.sql`
- `SYSTEM_CONFIG` is no longer directly accessible to `AGENT_API` — must use PL/SQL API
- VPD policy functions (`agent_workspace_pred`, `agent_entity_pred`, `vpd_ws_ctx_agent`, `vpd_entities_visibility`) are removed
- `DBMS_RLS.ADD_POLICY` / `DBMS_RLS.DROP_POLICY` calls are removed
- VPD context package `SET_AGENT_CONTEXT` is retained but now serves Deep Sec End User Context (via `SYS_CONTEXT` + `DBMS_SESSION.SET_CONTEXT`)

### Deep Sec Enforcement Status

**Deep Sec is fully enforcing at the database level** via Direct Logon with Local End Users:

- Each Pool Agent has a corresponding Deep Sec End User (name = `UPPER(REPLACE(agent_id, '-', '_'))`)
- Portal users connect as End User → Data Grants auto-filter via `ORA_END_USER_CONTEXT.username`
- Admin Dashboard uses AIADMIN connection pool (schema owner, unrestricted by Data Grants)
- No external IAM, no TCPS, no tokens required — uses Oracle's Direct Logon mode
- `connection.py` auto-routes: `set_agent_context()` → End User connection with Data Grant filtering; no context → AIADMIN pool
- `END_USER_MANAGER` PL/SQL package manages End User lifecycle (create/drop/get password)
- `DEEP_SEC_SESSION_ROLE` (CREATE SESSION) granted to Data Roles for End User login
- `agent_api.register_agent()` automatically creates End User via `_ensure_end_user()`
- Per-request context switching: `_set_context_from_session()` ensures Admin and Portal requests use correct DB identity

Verified enforcement (AGENT_001 vs AIADMIN):
| Table | AIADMIN (all) | AGENT_001 (Deep Sec) | Filter |
|-------|---------------|---------------------|--------|
| AGENT_REGISTRY | 17 | 1 | 94% |
| ENTITIES | 182 | 41 | 77% |
| TASK_PLANS | 18 | 5 | 72% |
| SYSTEM_CONFIG | 43 | BLOCKED | 100% |

### Bug Fixes (E2E Testing)

- **Portal login context timing** — `_set_portal_agent_context()` moved after AIADMIN operations (create_session, create_workspace) to avoid End User connection for admin-level operations
- **Missing WORKSPACE_CONTEXT INSERT Data Grant** — Portal chat inserts messages into WORKSPACE_CONTEXT, but End Users lacked INSERT privilege. Added `ws_ctx_agent_insert` Data Grant (WHERE 1=1) for `agent_data_role`
- **WORKSPACE_CONTEXT SELECT predicate fix** — Added `OR UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username` to allow INSERT "with check" validation for new rows
- **Missing WORKSPACES Data Grants** — `ws_agent_access` (SELECT) + `ws_agent_update` (UPDATE) for `agent_data_role` on WORKSPACES table
- **Per-request context isolation** — `_set_context_from_session()` called at start of each HTTP request prevents Admin/Portal context interference
- **COM server.py referencing ENT-only table** — `CONTEXT_AUDIT_LOG` query in stats API caused ORA-00942 on Community Edition. Fixed: wrapped in try/except
- **Portal API End User context blocking** — Portal APIs (user/profile, chat/sessions, chat/history, chat/new, chat/send, chat/rename, chat/delete, chat/switch, agent/release, user/workspaces, user/memories) were routed through End User connections, but WORKSPACES.CURRENT_AGENT_ID is NULL for most workspaces, causing Data Grant predicates to reject all rows. Fixed: Portal APIs now use `connection.set_agent_context(None)` to temporarily switch to AIADMIN for operations requiring access to WORKSPACES/SYSTEM_USERS tables

---

## Deployment

### New Scripts

```bash
# Step 1: Grant Deep Sec system privileges (run as SYSDBA)
sql sys/password@//host:port/service as sysdba @scripts/deploy/4_grants.sql

# Step 2: Create DEEP_SEC_SESSION_ROLE (run as SYSDBA)
sql sys/password@//host:port/service as sysdba
CREATE ROLE DEEP_SEC_SESSION_ROLE;
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO AIADMIN WITH ADMIN OPTION;

# Step 3: Deploy Deep Sec policy (run as AIADMIN)
sql aiadmin/password@//host:port/service @scripts/deploy/6_deep_sec_policy.sql
```

### Migration from v3.3.0

1. Drop existing VPD policies: `EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'table_name', 'policy_name');`
2. Run `4_grants.sql` as SYSDBA (adds Deep Sec privileges, removes SYSTEM_CONFIG grant)
3. Create `DEEP_SEC_SESSION_ROLE` with CREATE SESSION (as SYSDBA)
4. Run `6_deep_sec_policy.sql` as AIADMIN (creates Data Grants + End Users for all existing agents)
5. Restart application server (connection.py now uses Deep Sec End User routing)

---

## System Requirements

- **Oracle AI Database 26ai version 23.26.2.0.0 or later** — Earlier versions (23.26.1) have incomplete Deep Data Security support. Verify with: `SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle%';`
- COMPATIBLE >= 20.0 (for ORA_END_USER_CONTEXT)
- Deep Sec system privileges granted to AIADMIN (via 4_grants.sql)
- **Python 3.8+ with `oracledb` 4.0.1 or later** — Version 4.0.0 has TCPS protocol incompatibility (ORA-29019) with Oracle 26ai and lacks `create_end_user_security_context` API. Install: `pip install oracledb>=4.0.1`. Full TCPS/Deep Sec driver support expected in oracledb 4.1.0+.
- SQLcl 26.1+ (for SQL script deployment)
- SYSDBA access (for granting Deep Sec privileges)
