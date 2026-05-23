# Deployment Guide - Oracle Memory System v2.2.1

## Prerequisites

- Oracle Database 23ai+ (tested on 23.26.1.0.0)
- Python 3.8+ with oracledb package
- SQLcl 26.1+ (for SQL script deployment)

**Important**: v2.2.0 is NOT backward-compatible with v2.1.0. Requires clean re-deploy (same approach as v2.1.0).

## 4-Phase Deployment

### Phase 1: Schema (1_schema.sql)
Creates all tables, partitions, indexes, property graph, and JSON duality views.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/1_schema.sql
```
- **Destructive**: Drops all existing tables before creating new ones (`CASCADE CONSTRAINTS PURGE`)
- Creates 22 tables (6 partitioned, 5 reference-partitioned, 11 non-partitioned)
- Composite primary keys on ENTITIES, ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, ENTITY_TAGS, TASK_PLANS, TASK_STEPS, AGENT_SESSION, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS
- Partitioning: LIST+RANGE on ENTITIES (6×7), AGENT_SESSION (2×7), TASK_PLANS (2×7); RANGE+HASH on ENTITY_ACCESS_LOG; REFERENCE on 5 child tables
- ROW MOVEMENT enabled on AGENT_SESSION, TASK_PLANS, TASK_STEPS
- Global unique constraints: UK_ENTITIES_ID, UK_EDGES_ID, UK_TASK_PLANS_ID, UK_TASK_STEPS_ID, UK_ACCESS_LOG_ID
- ~25 local indexes + global indexes on non-partitioned tables
- 1 property graph, 4 duality views
- Seeds SYSTEM_CONFIG with version 2.2.0

### Phase 2: API Packages (2_api.sql)
Creates 5 PL/SQL packages.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/2_api.sql
```
- MEMORY_FUSION_ENGINE (uses RAWTOHEX(SYS_GUID()), JSON_OBJECT VALUE syntax, composite FKs)
- KNOWLEDGE_BASE_API (spaced review, concept lineage with composite key joins)
- AGENT_PERMISSION_MANAGER (access control, session cleanup with ROW MOVEMENT)
- SESSION_CLEANUP (purge logs, archive entities, tag counts)
- WORKSPACE_MANAGER (workspace lifecycle, context chain management, cleanup)

### Phase 3: Scheduler Jobs (3_jobs.sql)
Creates 9 automated scheduler jobs.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/3_jobs.sql
```

| Job | Schedule | Action |
|-----|----------|--------|
| MEMORY_FUSION_JOB | Daily 02:00 | Fuse similar memories + decay importance |
| KNOWLEDGE_EXTRACTION_JOB | Daily 03:00 | Extract knowledge from memory patterns |
| KNOWLEDGE_REVIEW_JOB | Daily 06:00 | Schedule spaced reviews for knowledge entities |
| SESSION_CLEANUP_JOB | Every 30 min | Clean expired sessions + purge inactive |
| ACCESS_LOG_PURGE_JOB | Weekly Sun 04:00 | Purge access logs older than 90 days |
| ENTITY_ARCHIVE_JOB | Weekly Sun 05:00 | Archive low-importance memories older than 180 days |
| COLLAB_EXPIRY_JOB | Daily 00:30 | Process collaboration requests |
| WORKSPACE_CLEANUP_JOB | Daily 01:00 | Clean stale workspaces and paused sessions |
| CONTEXT_ARCHIVE_JOB | Weekly Sun 03:00 | Archive old context entries |

### Phase 4: Harness Templates (4_harness_templates.sql)
Seeds 5 built-in harness templates with HARNESS_META (INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE).
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/4_harness_templates.sql
```
Uses MERGE for idempotent re-runs. Templates: Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor.

## Python Setup

```bash
pip install oracledb
```

## Configuration

Edit `config.json`:
```json
{
  "database": {"user": "openclaw", "password": "hermes", "dsn": "10.10.10.130:1521/openclaw"},
  "server": {"host": "0.0.0.0", "port": 8000, "session_timeout": 300},
  "embedding": {"api_url": "http://10.10.10.1:12345/v1/embeddings", "model": "text-embedding-bge-m3", "dimension": 1024},
  "security": {"masking_enabled": true, "pbkdf2_iterations": 100000, "max_login_attempts": 5, "lockout_minutes": 15}
}
```

Environment variable overrides: `MEMORY_DB_USER`, `MEMORY_DB_PASSWORD`, `MEMORY_DB_DSN`, `MEMORY_SERVER_PORT`, `MEMORY_SERVER_HOST`, `MEMORY_SESSION_TIMEOUT`, `MEMORY_EMBEDDING_API`

## Running Tests

```bash
cd /root/oracle-memory-by-yhw/scripts
python -m tests.test_all
```

v2.2.0 test suite: 61 tests across 8 modules (connection: 6, memory: 8, knowledge: 8, agent: 8, security: 5, harness: 6, graph: 8, workspace: 12 — new).

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
- **Connection refused**: Check DSN, ensure listener is running on 10.10.10.130:1521
- **Pool exhausted**: Increase pool_max in config.json (default: 5)
- **CLOB fetch**: `oracledb.defaults.fetch_lobs = False` set in connection.py
- **Chinese garbled text**: oracledb thin mode double-encodes UTF-8; `_fix_encoding()` auto-corrects in viz_server
- **Server crash on request**: `do_GET` → `_do_GET` wrapper catches exceptions per-request
- **Port not listening**: Server may take 10-20s to initialize pool; `start_web_server.sh` waits up to 45s
