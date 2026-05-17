# Minimum Database Privileges - Oracle Memory System v2.0.0

## Current State (openclaw user)

| Role/Privilege | Status | Needed? |
|----------------|--------|---------|
| DBA | Granted | **NO - over-privileged** |
| DB_DEVELOPER_ROLE | Granted | Partially (missing several) |
| MEMORY_ADMIN (custom) | Granted (ADMIN_OPTION=YES) | Optional, app-level |
| MEMORY_READER (custom) | Granted (ADMIN_OPTION=YES) | Optional, app-level |
| MEMORY_WRITER (custom) | Granted (ADMIN_OPTION=YES) | Optional, app-level |
| SELECT ANY DICTIONARY | Granted | **NO - not needed** |
| UNLIMITED TABLESPACE | Granted | Yes (or use quota) |

## Required System Privileges

### Phase 1: Schema Deployment (1_schema.sql)
| Privilege | Reason |
|-----------|--------|
| CREATE SESSION | Connect to database |
| CREATE TABLE | Create 16 tables |
| CREATE SEQUENCE | Create sequences (IDENTITY columns auto-create, but explicit seqs in script) |
| CREATE VIEW | Create JSON Duality Views (MEMORY_DV, KNOWLEDGE_DV) |
| CREATE PROCEDURE | Create safe_ddl, safe_idx helper procedures |
| CREATE PROPERTY GRAPH | Create ORACLE_MEMORY_GRAPH |
| CREATE TRIGGER | Not required by v2.0 (v1 had triggers, v2 uses IDENTITY) |
| UNLIMITED TABLESPACE | Or: QUOTA UNLIMITED ON <tablespace_name> |

### Phase 2: API Packages (2_api.sql)
| Privilege | Reason |
|-----------|--------|
| CREATE PROCEDURE | Create 4 PL/SQL packages |
| CREATE TYPE | JSON_OBJECT, JSON_ARRAYAGG etc. (usually available by default in 23ai) |

### Phase 3: Scheduler Jobs (3_jobs.sql)
| Privilege | Reason |
|-----------|--------|
| CREATE JOB | Create 7 DBMS_SCHEDULER jobs |

### Runtime (Python oracledb driver)
| Privilege | Reason |
|-----------|--------|
| CREATE SESSION | Connect to database |
| SELECT, INSERT, UPDATE, DELETE on own schema tables | DML operations (auto-granted to schema owner) |

### Optional: UTL_HTTP (for GET_EMBEDDING function)
| Privilege | Reason |
|-----------|--------|
| EXECUTE on UTL_HTTP | Call external embedding API |
| Network ACL | Allow HTTP connections to embedding server |

## Minimum Privilege Set

### Option A: Custom Role (Recommended for Production)

```sql
-- 1. Create a dedicated role
CREATE ROLE MEMORY_SYSTEM_ROLE;

-- 2. Grant system privileges
GRANT CREATE SESSION TO MEMORY_SYSTEM_ROLE;
GRANT CREATE TABLE TO MEMORY_SYSTEM_ROLE;
GRANT CREATE SEQUENCE TO MEMORY_SYSTEM_ROLE;
GRANT CREATE PROCEDURE TO MEMORY_SYSTEM_ROLE;
GRANT CREATE VIEW TO MEMORY_SYSTEM_ROLE;
GRANT CREATE TYPE TO MEMORY_SYSTEM_ROLE;
GRANT CREATE JOB TO MEMORY_SYSTEM_ROLE;
GRANT CREATE PROPERTY GRAPH TO MEMORY_SYSTEM_ROLE;

-- 3. Grant tablespace quota (instead of UNLIMITED TABLESPACE)
-- ALTER USER openclaw QUOTA UNLIMITED ON USERS;

-- 4. Grant the role to user
GRANT MEMORY_SYSTEM_ROLE TO openclaw;

-- 5. (Optional) Network ACL for UTL_HTTP
BEGIN
    DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
        host => '10.10.10.1',
        ace  => xs$ace_type(
            privilege_list => xs$name_list('http'),
            principal_name => 'OPENCLAW',
            principal_type => xs_acl.ptype_db
        )
    );
END;
/
```

### Option B: DB_DEVELOPER_ROLE + Supplement (Simpler)

```sql
-- DB_DEVELOPER_ROLE already provides:
--   CREATE SESSION, CREATE JOB, and some others

-- Supplement with missing privileges:
GRANT CREATE TABLE TO openclaw;
GRANT CREATE SEQUENCE TO openclaw;
GRANT CREATE PROCEDURE TO openclaw;
GRANT CREATE VIEW TO openclaw;
GRANT CREATE TYPE TO openclaw;
GRANT CREATE PROPERTY GRAPH TO openclaw;
GRANT CREATE TRIGGER TO openclaw;
ALTER USER openclaw QUOTA UNLIMITED ON USERS;
```

## Privileges to REVOKE (Security Hardening)

```sql
-- Remove excessive privileges
REVOKE DBA FROM openclaw;
REVOKE SELECT ANY DICTIONARY FROM openclaw;
REVOKE UNLIMITED TABLESPACE FROM openclaw;
-- Then set explicit quota:
ALTER USER openclaw QUOTA UNLIMITED ON USERS;
```

## Verification Script

```sql
-- After hardening, verify minimum set is intact
SELECT PRIVILEGE FROM USER_SYS_PRIVS ORDER BY PRIVILEGE;
SELECT GRANTED_ROLE FROM USER_ROLE_PRIVS ORDER BY GRANTED_ROLE;

-- Test: can we still create a table?
CREATE TABLE _priv_test (id NUMBER);
DROP TABLE _priv_test;

-- Test: can we still create a procedure?
CREATE OR REPLACE PROCEDURE _priv_test_proc IS BEGIN NULL; END;
/
DROP PROCEDURE _priv_test_proc;
```

## Risk Summary

| Current Risk | Severity | Fix |
|-------------|----------|-----|
| DBA role granted | **CRITICAL** | Revoke DBA, use custom role |
| SELECT ANY DICTIONARY | HIGH | Revoke, not needed |
| UNLIMITED TABLESPACE | MEDIUM | Replace with explicit QUOTA |
| No network ACL control | MEDIUM | Configure ACL for UTL_HTTP |
| Custom roles empty (MEMORY_ADMIN/READER/WRITER) | LOW | Populate or drop |
