# Release Notes — v3.8.0 (2026-07-02)

## Overview

**v3.8.0** is a multi-Agent integration testing release. This version completes a full 5-phase deployment and functional test suite, validating the entire AI Agent Infrastructure stack from schema deployment through Admin Agent startup, Business Agent registration, and 15-module functional testing.

All 15 functional tests pass with zero failures. All database objects compile successfully with zero invalid objects.

## Bugs Fixed

### LOOP_MANAGER Package Body — Missing Procedure (PLS-00323)

The `LOOP_MANAGER` package specification declared a `log_loop_audit` procedure, but the package body did not include its implementation. This caused `PLS-00323: subprogram or cursor 'LOG_LOOP_AUDIT' is declared in a package specification and must be defined in the package body`.

**Fix**: Added the `log_loop_audit` procedure implementation to the LOOP_MANAGER package body in `2_api.sql`:

```sql
PROCEDURE log_loop_audit(
    p_loop_id       VARCHAR2,
    p_run_id        VARCHAR2,
    p_action_type   VARCHAR2,
    p_action_by     VARCHAR2 DEFAULT NULL,
    p_action_detail JSON DEFAULT NULL
) IS
BEGIN
    INSERT INTO LOOP_AUDIT (AUDIT_ID, LOOP_ID, RUN_ID, ACTION_TYPE, ACTION_BY, ACTION_DETAIL, CREATED_AT)
    VALUES (RAWTOHEX(SYS_GUID()), p_loop_id, p_run_id, p_action_type, p_action_by, p_action_detail, SYSTIMESTAMP);
END log_loop_audit;
```

### DB_CRYPTO Runtime — ORA-14551 DML Inside Query

The `DB_CRYPTO.get_db_key()` function lazily initializes the encryption key by performing an `INSERT INTO SYSTEM_CONFIG` when the key is not found. When `DB_CRYPTO.encrypt()` or `DB_CRYPTO.decrypt()` is called from a `SELECT` statement (e.g., `SELECT DB_CRYPTO.encrypt(:plain) FROM DUAL`), this triggers `ORA-14551: cannot perform a DML operation inside a query`.

**Fix**: Pre-seed the `db_crypto_master_key` and `db_crypto_key_salt` entries in `SYSTEM_CONFIG` during schema deployment. This ensures `get_db_key()` always finds the key via `SELECT` and never needs to perform `INSERT`.

### agent_api.py — Hardcoded Schema Prefix

The `_ensure_end_user()` function called `AIADMIN.END_USER_MANAGER.ensure_end_user()`, which hardcoded the `AIADMIN` schema name. When deploying to a database with a different schema owner, this call fails.

**Fix**: Removed the `AIADMIN.` prefix, allowing Oracle to resolve the package against the connected user's schema.

### 4_grants.sql — Hardcoded USERS Tablespace

The `AGENT_API` user creation used `DEFAULT TABLESPACE USERS`, but the `USERS` tablespace does not exist in all Oracle environments (e.g., some use `SYSTEM` or a custom tablespace).

**Fix**: Changed to dynamically retrieve the schema owner's default tablespace via `SELECT DEFAULT_TABLESPACE FROM DBA_USERS WHERE USERNAME = UPPER('&&SCHEMA_OWNER')` in a PL/SQL block, instead of hardcoding any tablespace name.

## Test Results

### 15-Module Functional Test Suite — All Passed

| # | Module | Operations Tested |
|---|--------|-------------------|
| 1 | Memory API | create → get → search → update → delete |
| 2 | Knowledge API | create → get → search → delete |
| 3 | Message API | send → get_messages → mark_read → delete |
| 4 | Collaboration API | create_group → add_member → list_members → delete |
| 5 | Loop API | create_loop → start_run → record_iteration → list_runs → stop_run |
| 6 | Graph API | knowledge nodes + edges → get_neighbors → get_graph_stats |
| 7 | Workspace API | create → save_context → get_latest_context → list_branches |
| 8 | Spec API | create → get → list → delete |
| 9 | Tool Registry | import_openapi → list → get → delete |
| 10 | Monitor API | get_agent_health → get_system_overview → get_active_alerts |
| 11 | Event Bus | subscribe_agent → publish_event → get_pending → unsubscribe |
| 12 | Task Plan API | create_plan → add_step → get_plan_steps → list_plans → delete |
| 13 | Skill API | register_skill → list_skills → delete_skill |
| 14 | Agent API | get_agent → update_agent → heartbeat → get_active_sessions |
| 15 | LLM Integration | server health endpoint + config verification |

### Existing Test Suites — All Passed

- `test_loop_api.py`: 16 tests passed
- `test_admin_agent.py`: 18 tests passed

### Database Integrity

- 50 tables deployed
- 19 PL/SQL packages (all VALID)
- 19 package bodies (all VALID)
- 23 scheduler jobs
- 0 invalid database objects

## Upgrade Notes

This is a bug-fix release with no schema changes. To upgrade:

1. Redeploy `2_api.sql` to pick up the LOOP_MANAGER body fix
2. Redeploy `4_grants.sql` if using the AGENT_API restricted user
3. If DB_CRYPTO encounters ORA-14551, manually insert the master key:
   ```sql
   INSERT INTO SYSTEM_CONFIG (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
   VALUES ('db_crypto_master_key', '<64-char-hex>', 'AES-256 master key');
   ```
4. No data migration required
