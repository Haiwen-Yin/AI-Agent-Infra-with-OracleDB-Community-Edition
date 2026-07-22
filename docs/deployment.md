# Deployment Guide - AI Agent Infra v4.0.1

## Supported Targets

| Adapter | Validated database | Business Agent account |
|---|---|---|
| Oracle | Oracle AI Database 26ai | Native End User |
| PostgreSQL | PostgreSQL 18 | Dedicated LOGIN role |
| YashanDB | YashanDB 23.5.4+ | Dedicated database user |

Use Linuxbrew Python 3.14. For a clean v4.0.1 installation, deploy
`1_schema.sql`, then `7_v4_0_1_migration.sql`, followed by the remaining phase
scripts. For an existing schema, run the versioned migration only through the
migration runner so its checksum and ledger record are verified. Then run the
application with the minimum documented privileges.
Business Agent configuration must contain only its independent login and must
never contain a fallback schema-owner credential.

For upgrades, use `7_v4_0_1_migration.sql` through the migration runner. A
release is ready only when unit/security tests, package validation, live
capability probes, and the three operating modes pass. Multi-tenant deployment
and public Internet exposure are outside the v4.0.1 deployment contract.

Existing v4.0.1 installations must then apply
`8_portal_node_ownership.sql` before deploying or restarting the web service.
Fresh schemas already contain the Portal node ownership column and index.

## Historical Oracle Deployment Detail

## Prerequisites

- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+
- SQLcl 26.1+ (for SQL script deployment)

**Important**: v3.4.0 is NOT backward-compatible with v3.3.0. Requires clean re-deploy.

## 6-Phase Deployment

### Phase 1: Schema (1_schema.sql)
Creates all tables, partitions, indexes, property graph, and JSON duality views.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/1_schema.sql
```
- **Destructive**: Drops all existing tables before creating new ones (`CASCADE CONSTRAINTS PURGE`)
- Creates 35 tables (6 partitioned, 5 reference-partitioned, 24 non-partitioned)
- Composite primary keys on ENTITIES, ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, ENTITY_TAGS, TASK_PLANS, TASK_STEPS, AGENT_SESSION, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS
- WORKSPACE_CONTEXT includes VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED) for cross-agent context isolation in collab workspaces
- Partitioning: LIST+RANGE on ENTITIES (6×7), AGENT_SESSION (2×7), TASK_PLANS (2×7); RANGE+HASH on ENTITY_ACCESS_LOG; REFERENCE on 5 child tables
- ROW MOVEMENT enabled on AGENT_SESSION, TASK_PLANS, TASK_STEPS
- Global unique constraints: UK_ENTITIES_ID, UK_EDGES_ID, UK_TASK_PLANS_ID, UK_TASK_STEPS_ID, UK_ACCESS_LOG_ID
- ~25 local indexes + global indexes on non-partitioned tables
- 1 property graph, 4 duality views
- Seeds SYSTEM_CONFIG with version 3.7.3

### Phase 2: API Packages (2_api.sql)
Creates 16 PL/SQL packages (13 in 2_api.sql + 3 in 6_deep_sec_policy.sql).
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/2_api.sql
```
- MEMORY_FUSION_ENGINE (uses RAWTOHEX(SYS_GUID()), JSON_OBJECT VALUE syntax, composite FKs)
- KNOWLEDGE_BASE_API (spaced review, concept lineage with composite key joins)
- AGENT_PERMISSION_MANAGER (access control, session cleanup with ROW MOVEMENT)
- SESSION_CLEANUP (purge logs, archive entities, tag counts)
- WORKSPACE_MANAGER (workspace lifecycle, context chain management, cleanup)

### Phase 3: Scheduler Jobs (3_jobs.sql)
Creates 17 automated scheduler jobs.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/3_jobs.sql
```

| Job | Schedule | Action |
|-----|----------|--------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + decay importance |
| KNOWLEDGE_EXTRACTION_JOB | Weekly Sunday 06:00 | Extract knowledge from memory patterns |
| KNOWLEDGE_REVIEW_JOB | Daily 06:00 | Schedule spaced reviews for knowledge entities |
| SESSION_CLEANUP_JOB | Every 30 min | Clean expired sessions + purge inactive |
| ACCESS_LOG_PURGE_JOB | Weekly Sun 04:00 | Purge access logs older than 90 days |
| ENTITY_ARCHIVE_JOB | Weekly Sun 05:00 | Archive low-importance memories older than 180 days |
| COLLAB_EXPIRY_JOB | Daily 00:30 | Process collaboration requests |
| WORKSPACE_CLEANUP_JOB | Daily 01:00 | Clean stale workspaces and paused sessions |
| CONTEXT_ARCHIVE_JOB | Weekly Sun 03:00 | Archive old context entries |
| STALE_WORKSPACE_DETECT_JOB | Daily 04:00 | Detect stale workspaces |
| DORMANT_AGENT_JOB | Daily 05:00 | Hibernate dormant agents |
| CREDENTIAL_CLEANUP_JOB | Daily 06:30 | Clean expired credentials |
| EMBEDDING_GENERATION_JOB | Daily 03:30 | Generate embeddings for entities |
| LDAP_SYNC_JOB | Daily 01:30 | Sync LDAP users and groups |
| SKILL_TOKEN_CLEANUP_JOB | Daily 07:00 | Clean expired skill tokens |
| CONTEXT_AUDIT_JOB | Daily 00:00 | Audit context access patterns |
| BRANCH_CLEANUP_JOB | Weekly Sat 02:00 | Archive abandoned branches |

### Phase 4: Grants (4_grants.sql)
Grants required privileges to schema roles and users.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/4_grants.sql
```
- Grants SELECT, INSERT, UPDATE, DELETE on all tables to application role
- Grants EXECUTE on all PL/SQL packages to application role
- Idempotent: re-run is safe

### Phase 5: Harness Templates (4_harness_templates.sql)
Seeds 5 built-in harness templates with HARNESS_META (INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE).
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/4_harness_templates.sql
```
Uses MERGE for idempotent re-runs. Templates: Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor.

### Phase 6: Deep Sec Policy (6_deep_sec_policy.sql)
Applies Deep Security policies for row-level access control and data masking.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/6_deep_sec_policy.sql
```
- Requires Oracle AI Database 26ai version 23.26.2+ (minimum version for Deep Sec)
- 23 Data Grants, MAC on 7 tables, 3 PL/SQL packages (SET_AGENT_CONTEXT, agent_auth_pkg, END_USER_MANAGER)
- End User Context with `o:onFirstRead` callback, Data Roles (admin_data_role, agent_data_role, pool_agent_data_role)
- DEEP_SEC_SESSION_ROLE (CREATE SESSION) for End User login
- Idempotent: re-run is safe

**v4.0.1 requirement**: Portal APIs use the authenticated Business Agent's
independent database identity for the entire request. Missing grants or an
unavailable Business connection fail closed and never fall back to the Schema
Owner.

## Python Setup

```bash
pip install oracledb
```

## Configuration

Edit `config.json`:
```json
{
  "database": {"user": "aiadmin", "password": "your_password", "dsn": "host:port/service"},
  "server": {"host": "0.0.0.0", "port": 18090, "session_timeout": 300},
  "embedding": {"api_url": "http://host:port/v1/embeddings", "model": "text-embedding-bge-m3", "dimension": 1024},
  "security": {"masking_enabled": true, "pbkdf2_iterations": 100000, "max_login_attempts": 5, "lockout_minutes": 15}
}
```

Environment variable overrides: `MEMORY_DB_USER`, `MEMORY_DB_PASSWORD`, `MEMORY_DB_DSN`, `MEMORY_SERVER_PORT`, `MEMORY_SERVER_HOST`, `MEMORY_SESSION_TIMEOUT`, `MEMORY_EMBEDDING_API`

## Running Tests

```bash
cd /root/oracle-memory-by-yhw/scripts
python -m tests.test_all
```

v3.8.0 test suite: 151 tests across 21 modules (connection: 6, memory: 8, knowledge: 8, agent: 8, security: 5, harness: 6, graph: 8, workspace: 12 — new).

## Starting the Web Server

```bash
# Control script (recommended)
./start_web_server.sh start    # Start (daemon mode)
./start_web_server.sh status    # Status + config
./start_web_server.sh stop      # Stop
./start_web_server.sh restart   # Restart
./start_web_server.sh config    # Show configuration
./start_web_server.sh log       # View log

# Or run directly
python3.14 viz_server_local_js.py
```

## Partitioning Maintenance

### Adding Future Quarterly Subpartitions

When new quarters approach, add subpartitions to LIST+RANGE partitioned tables:

```sql
-- Add Q3 2027 subpartition to ENTITIES (applies to all 6 list partitions)
ALTER TABLE ENTITIES SPLIT SUBPARTITION SP_FUTURE
  AT (TO_DATE('2027-10-01','YYYY-MM-DD'))
  INTO (SUBPARTITION SP_2027Q3, SUBPARTITION SP_FUTURE);

-- Same for AGENT_SESSION, TASK_PLANS
ALTER TABLE AGENT_SESSION SPLIT SUBPARTITION SP_FUTURE
  AT (TO_DATE('2027-10-01','YYYY-MM-DD'))
  INTO (SUBPARTITION SP_2027Q3, SUBPARTITION SP_FUTURE);

ALTER TABLE TASK_PLANS SPLIT SUBPARTITION SP_FUTURE
  AT (TO_DATE('2027-10-01','YYYY-MM-DD'))
  INTO (SUBPARTITION SP_2027Q3, SUBPARTITION SP_FUTURE);
```

### Adding Monthly Partitions to ENTITY_ACCESS_LOG

```sql
ALTER TABLE ENTITY_ACCESS_LOG SPLIT PARTITION P_MAX
  AT (TO_DATE('2026-08-01','YYYY-MM-DD'))
  INTO (PARTITION P_202607, PARTITION P_MAX);
```

## Troubleshooting

- **ORA-14402**: Updating partition key column causes row movement — ensure ROW MOVEMENT is enabled on AGENT_SESSION, TASK_PLANS, TASK_STEPS. If not: `ALTER TABLE <table> ENABLE ROW MOVEMENT;`
- **ORA-14650**: Foreign key constraint not compatible with reference partitioning — child table FK must reference the composite PK of the parent, including the partition key column
- **ORA-00955**: Name already in use — safe_idx/safe_ddl handles this; re-run is safe
- **ORA-14300**: Partitioning key maps to a partition outside maximum permitted number of partitions — add new subpartitions using SPLIT SUBPARTITION
- **Connection refused**: Check DSN, ensure listener is running on configured host:port
- **Pool exhausted**: Increase pool_max in config.json (default: 5)
- **CLOB fetch**: `oracledb.defaults.fetch_lobs = False` set in connection.py
- **Chinese garbled text**: oracledb thin mode double-encodes UTF-8; `_fix_encoding()` auto-corrects in viz_server
- **Server crash on request**: `do_GET` → `_do_GET` wrapper catches exceptions per-request
- **Port not listening**: Server may take 10-20s to initialize pool; `start_web_server.sh` waits up to 45s

## Pure Python Deployment (deploy_oracle.py)

For Oracle editions, a pure Python deployment tool is available as an alternative to SQLcl. It replaces SQLcl (125MB + Java dependency) with a Python script using the oracledb driver.

Usage:
```bash
python3.14 scripts/deploy_oracle.py aiadmin oracle <DB_HOST>:1521/ai_agent_ee \
    scripts/deploy/1_schema.sql scripts/deploy/7_v4_0_1_migration.sql \
    scripts/deploy/2_api.sql scripts/deploy/3_jobs.sql
```

For SYSDBA scripts:
```bash
python3.14 scripts/deploy_oracle.py --sysdba sys oracle <DB_HOST>:1521/ai_agent_ee \
    scripts/deploy/4_grants.sql
```

Handles SQLcl syntax: PROMPT removal, DEFINE/&& variable substitution, / block terminator for PL/SQL blocks.
