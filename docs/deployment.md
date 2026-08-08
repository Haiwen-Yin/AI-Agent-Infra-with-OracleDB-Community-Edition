# Deployment Guide - AI Agent Infra with DB v4.3.6

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## Supported Targets

| Adapter | Validated database | Business Agent account |
|---|---|---|
| Oracle | Oracle AI Database 26ai | Native End User |
| PostgreSQL | PostgreSQL 18 | Dedicated LOGIN role |
| YashanDB | YashanDB 23.5.4+ | Dedicated database user |

Use any accessible Python 3.14+ runtime. Set `PYTHON_BIN` when the chosen
interpreter is not on `PATH`. Run `bash scripts/install_offline.sh` from the
package root before starting the service. It creates a package-local `.venv`
from the selected interpreter and installs only the verified local `vendor/`
wheelhouse; `start_web_server.sh` automatically prefers that `.venv`. This
avoids global pip writes on PEP 668 managed installations. For a clean installation, deploy the base schema
and phase scripts, then apply the required versioned Graph/lifecycle migrations
through the migration runner. For an existing schema, run each versioned
migration only through the runner so its checksum and ledger record are
verified. Then run the application with the minimum documented privileges.
Business Agent configuration must contain only its independent login and must
never contain a fallback schema-owner credential.

## v4.3.6 Native Agent Deployment

After the v4.3.5 chain, apply the additive v4.3.6 migration and repeat it
through the runner for idempotency:

```bash
"$PYTHON_BIN" scripts/migration_runner.py --version 4.3.6 \
  --database <oracle|pg|yashandb> --edition <community|enterprise> \
  --<adapter>-config config.json --backup-evidence release_evidence/backup.json
```

The migration creates the native bootstrap, templates, Agent inventory, LLM
profiles, provisioning requests, deployment targets, runtime leases and
external-registration policy. The application startup then performs the
database-authoritative bootstrap. Without an LLM profile the built-in Agents
remain `ACTIVATION_PENDING`; no external Agent is required for initialization.
Configure an OpenAI-compatible URL and model in the protected Dashboard. API
keys are encrypted at rest and are never returned by ordinary reads.

`LOCAL_MANAGED`, `REMOTE_WORKER`, `CONTAINER_MANAGED`, and `WEBHOOK_MANAGED`
are reference lifecycle contracts. They do not provide customer-specific
virtualization, SaaS, MaaS, or Agent-platform connectors. Such connectors must
implement prepare, activate, health, cancel, revoke, and evidence without
granting authority from a remote callback.

YashanDB packages additionally install the bundled CPython-native `yaspy`
module into the same `.venv` and place the bundled client libraries under
`.runtime/yashandb-client/lib` by default. The start script exports this path
only for the service process; it does not change `~/.bashrc`. Set
`CX_YASHAN_LIB_DIR` only when an approved shared client-library location is
required.

The offline dependency set may contain both the upstream
`cryptography==49.0.0` `manylinux_2_34` wheel and a source-built
`manylinux_2_28` wheel for this server's RHEL 8/glibc 2.28 baseline. `pip` and
`scripts/verify_deps.py` select the compatible file automatically. The source
build is only required when producing the RHEL 8 compatibility wheel; customers
on newer operating systems use the upstream wheel. See
`cryptography-build.md` for the build and auditwheel requirements.
The same wheelhouse must include `argon2-cffi==25.1.0`, its mandatory
`argon2-cffi-bindings` wheel, `annotated-doc==0.0.4`, and `fastapi==0.120.4`.
The verifier checks wheel metadata, Python/platform compatibility, and RECORD
integrity before install. The current v4.3.5 artifact includes the verified
glibc 2.28 compatibility wheel; `verify_deps.py` still fails closed if no
compatible wheel is available.

For upgrades, preserve the v4.1.x core and apply the complete additive chain
through `migration_runner.py --version 4.3.5`. The v4.3.5 `production` profile
retains the stable Graph Runtime and keeps Dynamic Graph, A2A, and OpenTelemetry
previews disabled. The validated local recovery boundary covers replacement
runtime processes using database leases, fencing, Runs, and Checkpoints; it
does not claim database failover, RPO, or RTO. Multi-tenant deployment and
public Internet exposure remain outside this private single-tenant contract.

### v4.3.4 Compliance Activation

Enterprise deployments add a database-authoritative compliance plane after the
normal identity and Gateway migration chain. Apply it only with a recoverable
backup manifest:

```bash
"$PYTHON_BIN" scripts/migration_runner.py --version 4.3.4 --edition enterprise \
  --database <oracle|pg|yashandb> --<adapter>-config config.json \
  --backup-evidence release_evidence/backup.json
```

New production or restricted Agents remain `PENDING_ACTIVATION` until they
prove a registered Gateway credential. Dashboard activation does not replace
that proof. The Controller marks stale validated evidence as `DEGRADED`; it
does not infer a violation from idleness, a missing Skill call, a model
opinion, or an offline external process. Exceptions require a reason,
compensating controls, expiry, and a distinct active Human approver.

### v4.3.3 Preview Controls

Do not enable a preview merely to expose an endpoint. `development` and
`experimental-4.2` enable the isolated Dynamic Graph, A2A 1.0.1, and OTLP
mapping surfaces for controlled validation. `production` denies these controls
by design. A2A currently maps Tasks to existing Graph Runs but does not provide
independent-client conformance or durable stream delivery. OTLP currently
persists redacted projection metadata but does not deliver to a real Collector.
Neither preview changes database authority, identity, policy, or audit rules.

Existing v4.0.1 installations must then apply
`8_portal_node_ownership.sql` before deploying or restarting the web service.
Fresh schemas already contain the Portal node ownership column and index.

### v4.3.0 Identity And Governance Deployment

Community editions deploy `8_v4_1_0_registration.sql` for the common
registered-Agent boundary. Enterprise editions deploy
`8_v4_1_0_governance.sql`, which includes that registration boundary and adds
the resource, policy, grant, decision, approval, emergency, retention,
legal-hold, and evidence-export objects. The three adapters expose the same
observable decisions while using native SQL types, indexes, identity
mechanisms, RLS or database users, and transaction behavior.

Before enabling a high-risk policy, verify an explicit catalog classification,
an active policy version, a bounded grant where required, and an approval
request when the policy requires human approval. Unknown, expired, revoked,
disabled, or unregistered identities must remain denied.

## Oracle Adapter Deployment Details

## Prerequisites

- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.14+ with the bundled `oracledb` wheel
- Oracle credentials with the privileges documented in `minimum-privileges.md`

## 6-Phase Deployment

At the release root, select the runtime once and reuse it for every command:

```bash
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
```

### Phase 0: Oracle Text prerequisites (0_oracle_text_prerequisites.sql)
Oracle editions use an Oracle Text `CONTEXT` index with a
`MULTI_COLUMN_DATASTORE` preference. A DBA must grant the schema owner the
creation-only privileges before the schema script runs:

```bash
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys your_sys_password host:port/service \
    scripts/deploy/0_oracle_text_prerequisites.sql
```

This grants `CTXAPP` and `EXECUTE ON CTXSYS.CTX_DDL`. It does not grant runtime
data access to Business Agents.

### Phase 1: Schema (1_schema.sql)
Creates all tables, partitions, indexes, property graph, and JSON duality views.
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py aiadmin your_password host:port/service \
    scripts/deploy/1_schema.sql scripts/deploy/7_v4_0_1_migration.sql \
    scripts/deploy/8_v4_1_0_registration.sql
```
- **Destructive**: Drops all existing tables before creating new ones (`CASCADE CONSTRAINTS PURGE`)
- Creates the current core schema and the edition-specific objects declared by the deployment scripts
- Composite primary keys on ENTITIES, ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, ENTITY_TAGS, TASK_PLANS, TASK_STEPS, AGENT_SESSION, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS
- WORKSPACE_CONTEXT includes VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED) for cross-agent context isolation in collab workspaces
- Partitioning: LIST+RANGE on ENTITIES (6×7), AGENT_SESSION (2×7), TASK_PLANS (2×7); RANGE+HASH on ENTITY_ACCESS_LOG; REFERENCE on 5 child tables
- ROW MOVEMENT enabled on AGENT_SESSION, TASK_PLANS, TASK_STEPS
- Global unique constraints: UK_ENTITIES_ID, UK_EDGES_ID, UK_TASK_PLANS_ID, UK_TASK_STEPS_ID, UK_ACCESS_LOG_ID
- ~25 local indexes + global indexes on non-partitioned tables
- 1 property graph, 4 duality views
- Seeds `SYSTEM_CONFIG` with the current release metadata
- Verifies that `ENTITIES_MCD` exists and `ENTITIES_SEARCH_CTX` reports both
  `DOMIDX_STATUS=VALID` and `DOMIDX_OPSTATUS=VALID`

### Phase 2: API Packages (2_api.sql)
Creates the shared PL/SQL API packages required by the current adapter.
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py aiadmin your_password host:port/service \
    scripts/deploy/2_api.sql
```
- MEMORY_FUSION_ENGINE (uses RAWTOHEX(SYS_GUID()), JSON_OBJECT VALUE syntax, composite FKs)
- KNOWLEDGE_BASE_API (spaced review, concept lineage with composite key joins)
- AGENT_PERMISSION_MANAGER (access control, session cleanup with ROW MOVEMENT)
- SESSION_CLEANUP (purge logs, archive entities, tag counts)
- WORKSPACE_MANAGER (workspace lifecycle, context chain management, cleanup)

### Phase 3: Scheduler Jobs (3_jobs.sql)
Creates the scheduler jobs declared by the current adapter.
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py aiadmin your_password host:port/service \
    scripts/deploy/3_jobs.sql
```

| Job | Schedule | Action |
|-----|----------|--------|
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

`MEMORY_FUSION_JOB` is a pre-v4.3.2 legacy task and is removed by migration
`25_v4_3_2_disable_legacy_memory_fusion.sql`. It must not be recreated: direct
fusion and importance decay bypass immutable Memory versions, review, snapshots,
and lifecycle audit. Use governed `CX_MEMORY_JOBS` workflows instead.

### Phase 4: Grants (4_grants.sql)
Grants required privileges to schema roles and users.
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys your_password host:port/service \
    scripts/deploy/4_grants.sql
```
- Grants SELECT, INSERT, UPDATE, DELETE on all tables to application role
- Grants EXECUTE on all PL/SQL packages to application role
- Idempotent: re-run is safe

### Phase 5: Harness Templates (4_harness_templates.sql)
Seeds 5 built-in harness templates with HARNESS_META (INPUT_SCHEMA, OUTPUT_SCHEMA, EXECUTION_MODE).
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py aiadmin your_password host:port/service \
    scripts/deploy/4_harness_templates.sql
```
Uses MERGE for idempotent re-runs. Templates: Research Analyst, Code Assistant, Data Analyst, Task Planner, Security Auditor.

### Phase 6: Deep Sec Policy (6_deep_sec_policy.sql)
Applies Deep Security policies for row-level access control and data masking.
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py aiadmin your_password host:port/service \
    scripts/deploy/6_deep_sec_policy.sql
```
- Requires Oracle AI Database 26ai version 23.26.2+ (minimum version for Deep Sec)
- 23 Data Grants, MAC on 7 tables, 3 PL/SQL packages (SET_AGENT_CONTEXT, agent_auth_pkg, END_USER_MANAGER)
- End User Context with `o:onFirstRead` callback, Data Roles (admin_data_role, agent_data_role, pool_agent_data_role)
- DEEP_SEC_SESSION_ROLE (CREATE SESSION) for End User login
- Idempotent: re-run is safe

**v4.1.0 requirement**: Portal APIs use the authenticated Business Agent's
independent database identity for the entire request. Missing grants or an
unavailable Business connection fail closed and never fall back to the Schema
Owner.

### v4.1.0 Registration and Governance

Run `8_v4_1_0_registration.sql` for Community editions. Enterprise editions
run `8_v4_1_0_governance.sql` instead; it includes the registered-Agent tables
and adds the resource catalog, policy, grant, approval, emergency, retention,
legal-hold, and evidence-export objects.

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
cd <release-root>
"$PYTHON_BIN" -m pytest scripts/tests/ -q
```

To target a reusable live test database, set `AIAGENT_TEST_DB` and the
adapter-specific connection environment variables documented in
`AGENTS.md`. The release gate requires zero test failures; live database
contract and governance checks are run separately by the release validators.

## Starting the Web Server

```bash
# Control script (recommended)
./start_web_server.sh start    # Start the FastAPI/Uvicorn service (daemon mode)
./start_web_server.sh status    # Status + config
./start_web_server.sh stop      # Stop
./start_web_server.sh restart   # Restart
./start_web_server.sh config    # Show configuration
./start_web_server.sh log       # View log

# Or run directly from the release root
PYTHONPATH=scripts "$PYTHON_BIN" -m uvicorn web_app:app --host 0.0.0.0 --port <WEB_PORT>
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
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba <SYS_USER> <SYS_PASSWORD> <DB_HOST>:1521/<DB_SERVICE> \
    scripts/deploy/0_oracle_text_prerequisites.sql

"$PYTHON_BIN" scripts/deploy_oracle.py <DB_USER> <DB_PASSWORD> <DB_HOST>:1521/<DB_SERVICE> \
    scripts/deploy/1_schema.sql scripts/deploy/7_v4_0_1_migration.sql \
    scripts/deploy/2_api.sql scripts/deploy/3_jobs.sql
```

For SYSDBA scripts:
```bash
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba <SYS_USER> <SYS_PASSWORD> <DB_HOST>:1521/<DB_SERVICE> \
    scripts/deploy/4_grants.sql
```

Handles SQLcl syntax: PROMPT removal, DEFINE/&& variable substitution, / block terminator for PL/SQL blocks.

## v4.3.0 Graph And Collaboration Migration

The integrated v4.3.0 migration is additive. It preserves v4.1.x identity,
Task/Loop, memory, knowledge, and audit data, while the Graph executor closure
and governed Channel/Barrier/Gateway objects remain in the same shared release
line. The internal v4.2.1 step is retained only as a historical migration name;
there is no public v4.2.1 package.

After the v4.1 schema is available, apply the nine common Graph/lifecycle
scripts in numeric order, inserting the Enterprise scheduler overlay where
applicable:

```text
9_v4_2_0_graph_engineering.sql
10_v4_2_0_graph_runtime.sql
11_v4_2_0_graph_control.sql
12_v4_2_0_graph_edge_scope.sql
13_v4_2_0_scheduler_ha.sql       # Enterprise only
14_v4_2_0_graph_triggers.sql
15_v4_2_1_executor_registry.sql  # internal closure migration
16_v4_3_0_identity_channels.sql
17_v4_3_0_governance_lifecycle.sql
18_v4_3_0_security_lifecycle.sql
```

Community packages therefore apply nine scripts in this migration tail.
Enterprise packages apply the same nine plus
`13_v4_2_0_scheduler_ha.sql` between `12` and `14`, for ten scripts. The
internal `15` step is included in the v4.3.0 package and is not a public
v4.2.1 release.

```bash
"$PYTHON_BIN" scripts/migration_runner.py --version 4.3.1 --edition enterprise \
    --oracle-config /path/to/oracle-config.json \
    --pg-config /path/to/pg-config.json \
    --yashandb-config /path/to/yashandb-config.json \
    --backup-evidence /path/to/backup-evidence.json \
    --preflight

# Replace --preflight with --dry-run or omit it to apply the migration.
```

Use the adapter-specific deploy command documented in the package when the
database requires a client wrapper. PostgreSQL 18 with Apache AGE is the
current supported Graph adapter; PostgreSQL 19 native Property Graph is a
future adapter target and is not required by this release.

For PostgreSQL, Apache AGE must be installed by a privileged PostgreSQL
operator before the application migration runs. The restricted runtime role
must receive only the projection permissions it needs:

```sql
GRANT USAGE ON SCHEMA ag_catalog TO <APP_ROLE>;
GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog TO <APP_ROLE>;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ag_catalog TO <APP_ROLE>;
GRANT USAGE ON TYPE ag_catalog.agtype TO <APP_ROLE>;
```

The migration intentionally does not call `LOAD 'age'`, because hardened
PostgreSQL installations reserve that command for superusers. An installed
AGE extension plus the grants above is sufficient for the PostgreSQL adapter.

### PostgreSQL Agent role provisioning

The Admin Agent uses the configured Schema Owner connection to provision each
Business Agent's independent PostgreSQL login. Before the first registration,
a PostgreSQL DBA must grant the Schema Owner `CREATEROLE` and, when the shared
runtime role was created by the DBA, `ADMIN OPTION` on that role:

```sql
ALTER ROLE <SCHEMA_OWNER> CREATEROLE;
GRANT ai_agent_runtime TO <SCHEMA_OWNER> WITH ADMIN OPTION;
```

Do not grant either privilege to a Business Agent or to `ai_agent_runtime`.
The generated login remains `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`.
If the provisioning prerequisites are absent, registration fails closed and
does not fall back to Schema Owner access.

### Runtime Roles

Run the web process with the Admin identity only for management operations.
Business Agents and external Workers use registered identities, independent
database users/roles, and scoped HTTP or MCP credentials. A Worker receives a
Lease Token and bounded input, not a Schema Owner password. Multiple Enterprise
Schedulers may run concurrently; the database claim/fencing protocol is the
authority for ownership.

### Health Checks

Verify `/api/health`, `/api/graph/capabilities`, registered Worker status,
pending Event Inbox/Outbox rows, current Checkpoints, the assurance invariant
view, and the migration ledger after deployment. Keep database replication,
backup, and failover configured according to the database vendor's production
guidance and validate that topology separately from application runtime
recovery.
