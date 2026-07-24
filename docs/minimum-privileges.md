# Minimum Database Privileges - AI Agent Infra with DB v4.1.0

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## Legacy Oracle Privilege Audit Example

The table below is retained as a historical Oracle audit example, not as the
v4.1.0 runtime grant set. Current deployments must use the adapter-specific
least-privilege contract: only Admin may hold Schema Owner credentials;
Business Agents use independent identities and cannot fall back to the owner.

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
| CREATE TABLE | Create the core schema and the edition-specific tables declared by the deployment scripts |
| CREATE SEQUENCE | Create sequences (IDENTITY columns on TAGS, TASK_CONTEXT_SNAPSHOTS, etc.) |
| CREATE VIEW | Create JSON Duality Views (MEMORY_DV, KNOWLEDGE_DV) |
| CREATE PROCEDURE | Create safe_ddl, safe_idx helper procedures |
| CREATE PROPERTY GRAPH | Create ORACLE_MEMORY_GRAPH |
| UNLIMITED TABLESPACE | Or: QUOTA UNLIMITED ON <tablespace_name> |

**Partitioning-specific requirements**:
- No additional privilege needed for partitioned DDL — `CREATE TABLE` covers it
- Reference partitioning, LIST+RANGE, and RANGE+HASH are all covered by `CREATE TABLE`
- ROW MOVEMENT (`ALTER TABLE ... ENABLE ROW MOVEMENT`) requires `ALTER` on the table (auto-granted to schema owner)

### Phase 2: API Packages (2_api.sql)
| Privilege | Reason |
|-----------|--------|
| CREATE PROCEDURE | Create the adapter API packages and migration procedures declared by the deployment scripts |
| CREATE TYPE | JSON_OBJECT, JSON_ARRAYAGG etc. (usually available by default in Oracle AI Database 26ai) |

### Phase 3: Scheduler Jobs (3_jobs.sql)
| Privilege | Reason |
|-----------|--------|
| CREATE JOB | Create the DBMS_SCHEDULER jobs declared by the current adapter |

### Phase 4: Harness Templates (4_harness_templates.sql)
| Privilege | Reason |
|-----------|--------|
| *(none beyond Phase 1)* | MERGE and INSERT on existing tables |

### Runtime (Python oracledb driver)
| Privilege | Reason |
|-----------|--------|
| CREATE SESSION | Connect to database |
| SELECT, INSERT, UPDATE, DELETE on own schema tables | DML operations (auto-granted to schema owner) |

### Partition Maintenance (operational)
| Privilege | Reason |
|-----------|--------|
| ALTER on own schema tables | SPLIT SUBPARTITION, ADD PARTITION for future quarters (auto-granted to schema owner) |

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
        host => '<DB_HOST>',
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

## Partitioned Tables Requiring Maintenance Access

| Table | Partition Strategy | Maintenance Operations |
|-------|-------------------|----------------------|
| ENTITIES | LIST + RANGE (6×7) | SPLIT SUBPARTITION for new quarters |
| AGENT_SESSION | LIST + RANGE (2×7) | SPLIT SUBPARTITION for new quarters |
| TASK_PLANS | LIST + RANGE (2×7) | SPLIT SUBPARTITION for new quarters |
| ENTITY_ACCESS_LOG | RANGE + HASH | SPLIT PARTITION for new months |
| ENTITY_EDGES | REFERENCE | Auto-maintained with parent |
| KNOWLEDGE_META | REFERENCE | Auto-maintained with parent |
| ENTITY_EMBEDDINGS | REFERENCE | Auto-maintained with parent |
| HARNESS_META | REFERENCE | Auto-maintained with parent |
| ENTITY_TAGS | REFERENCE | Auto-maintained with parent |
| TASK_STEPS | REFERENCE | Auto-maintained with parent |

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

-- Test: can we still create a partitioned table?
CREATE TABLE _priv_test (id VARCHAR2(64), type VARCHAR2(32), PRIMARY KEY (id, type))
  PARTITION BY LIST (type) (PARTITION p1 VALUES ('A'), PARTITION p2 VALUES (DEFAULT));
DROP TABLE _priv_test;

-- Test: can we enable row movement?
CREATE TABLE _priv_test2 (id VARCHAR2(64), status VARCHAR2(16), PRIMARY KEY (id, status))
  PARTITION BY LIST (status) (PARTITION p_a VALUES ('A'), PARTITION p_b VALUES (DEFAULT));
ALTER TABLE _priv_test2 ENABLE ROW MOVEMENT;
DROP TABLE _priv_test2;

-- Test: can we still create a procedure?
CREATE OR REPLACE PROCEDURE _priv_test_proc IS BEGIN NULL; END;
/
DROP PROCEDURE _priv_test_proc;

-- Test: can we create a property graph?
CREATE PROPERTY GRAPH _priv_test_pg
  VERTEX TABLES (_priv_test KEY (id));
DROP PROPERTY GRAPH _priv_test_pg;
```

## Risk Summary

| Current Risk | Severity | Fix |
|-------------|----------|-----|
| DBA role granted | **CRITICAL** | Revoke DBA, use custom role |
| SELECT ANY DICTIONARY | HIGH | Revoke, not needed |
| UNLIMITED TABLESPACE | MEDIUM | Replace with explicit QUOTA |
| No network ACL control | MEDIUM | Configure ACL for UTL_HTTP |
| Custom roles empty (MEMORY_ADMIN/READER/WRITER) | LOW | Populate or drop |

## Deep Sec Privileges (AIADMIN)

Required for Deep Data Security deployment and management:

| Privilege | Reason |
|-----------|--------|
| CREATE DATA ROLE | Create admin_data_role, agent_data_role, pool_agent_data_role |
| CREATE DATA GRANT | Create 23 Data Grants with predicates |
| CREATE END USER | Create End User per agent |
| ALTER END USER | Modify End User properties |
| DROP END USER | Remove End User on agent decommission |
| GRANT DATA ROLE | Assign Data Roles to End Users |
| SET USE DATA GRANTS ONLY | Enable Data Grant enforcement on schema |
| CREATE CONTEXT | Create END_USER_CTX namespace for context switching |
| CREATE PROCEDURE | Create END_USER_MANAGER and other Deep Sec packages |

### DEEP_SEC_SESSION_ROLE

| Privilege | Reason |
|-----------|--------|
| CREATE SESSION | Granted to End Users via Data Roles for direct logon |

```sql
CREATE ROLE DEEP_SEC_SESSION_ROLE;
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO AIADMIN WITH ADMIN OPTION;
```

**Current boundary**: AIADMIN is available only to authenticated Admin
operations. Portal and Business Agent requests use End User credentials and
fail closed instead of switching to AIADMIN.
