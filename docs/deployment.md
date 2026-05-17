# Deployment Guide - Oracle Memory System v2.0.0

## Prerequisites

- Oracle Database 23ai+ (tested on 23.26.1.0.0)
- Python 3.8+ with oracledb package
- SQLcl 26.1+ (for SQL script deployment)

## 4-Phase Deployment

### Phase 1: Schema (1_schema.sql)
Creates all tables, indexes, property graph, and JSON duality views.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/1_schema.sql
```
- Idempotent: uses safe_ddl/safe_idx helpers
- Creates 16 tables, ~25 indexes, 1 property graph, 2 duality views
- Seeds SYSTEM_CONFIG with version 2.0.0

### Phase 2: API Packages (2_api.sql)
Creates 4 PL/SQL packages.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/2_api.sql
```
- MEMORY_FUSION_ENGINE
- KNOWLEDGE_BASE_API
- AGENT_PERMISSION_MANAGER
- SESSION_CLEANUP

### Phase 3: Scheduler Jobs (3_jobs.sql)
Creates 7 automated scheduler jobs.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/3_jobs.sql
```

### Phase 4: Harness Templates (4_harness_templates.sql)
Creates HARNESS_META table, extends ENTITY_TYPE constraint, seeds 5 built-in templates.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/4_harness_templates.sql
```

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

## Troubleshooting

- **ORA-00955**: Name already in use - safe_idx/safe_ddl handles this; re-run is safe
- **Connection refused**: Check DSN, ensure listener is running on 10.10.10.130:1521
- **Pool exhausted**: Increase pool_max in config.json (default: 5)
- **CLOB fetch**: `oracledb.defaults.fetch_lobs = False` set in connection.py
- **Chinese garbled text**: oracledb thin mode double-encodes UTF-8; `_fix_encoding()` auto-corrects in viz_server
- **Server crash on request**: `do_GET` → `_do_GET` wrapper catches exceptions per-request
- **Port not listening**: Server may take 10-20s to initialize pool; `start_web_server.sh` waits up to 45s
