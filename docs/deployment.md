# Deployment Guide - AI Agent Infra v3.7.5 (2026-06-18) - Community Edition

## Prerequisites

- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+
- SQLcl 26.1+ (for SQL script deployment)

**Important**: v3.4.0 is NOT backward-compatible with v3.3.0. Requires clean re-deploy.

## 4-Phase Deployment

### Phase 1: Schema (1_schema.sql)
Creates all tables, partitions, indexes, property graph, and JSON duality views.
```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/deploy/1_schema.sql
```
Admin Agent (mode=admin)
├── Web Portal
├── AIADMIN Connection Pool
└── Admin Token Generator
        │
        │ admin_token (secure)
        ▼
Encrypted Credential Distribution
        │
        ▼
Business Agent (mode=agent)
├── Agent Bootstrap CLI
├── End User Connection Pool
└── agent_config.json (encrypted)
    ✓ Data Grants enforced    ✗ No AIADMIN access
```json
{
  "mode": "admin",
  "database": {"user": "aiadmin", "password": "...", "dsn": "//db:1521/service"},
  "server": {"host": "0.0.0.0", "port": 18080}
}
```

**2. Start Admin Agent:**

```bash
./start_web_server.sh start
```

**3. Generate admin token for Business Agent registration:**

```bash
curl -X POST http://localhost:18080/api/admin/token/generate \
  -H "Cookie: session=<admin-session>"
```

**4. Share admin_token with Business Agent operator over secure out-of-band channel.**

### Business Agent Deployment (mode=agent)

**1. Bootstrap the Business Agent:**

```bash
python agent_bootstrap.py --admin-url http://admin-host:18080 \
                          --admin-token <token> \
                          --agent-name "business-agent-1" \
                          --output-dir /opt/agent
```

This creates `/opt/agent/agent_config.json` with encrypted End User credentials.

**2. Start Business Agent:**

```bash
python -m scripts.lib.agent_runner --config /opt/agent/agent_config.json
```

The Business Agent:
- Does NOT have AIADMIN credentials
- Connects only as End User (Data Grant enforced)
- Does NOT run Web Portal
- Reads connection info from encrypted `agent_config.json`

### Standalone Mode (default)

No configuration changes needed. `mode` defaults to `standalone`, preserving existing single-process behavior with both AIADMIN and End User connection pools.

### Admin Token Rotation

```bash
# Rotate admin token (existing Business Agents must re-register)
curl -X POST http://localhost:18080/api/admin/token/rotate \
  -H "Cookie: session=<admin-session>"
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
