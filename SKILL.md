# SKILL.md - AI Agent Infra with OracleDB

> **Version:** 4.3.2 | **Driver:** oracledb 4.0.1 | **DB:** Oracle AI Database 26ai 23.26.2+

This is the operations guide for the AI Agent Infra with OracleDB release
package. It covers everything an operator (human or AI Agent) needs to
deploy, configure, start, register against, and operate this edition.

> **Product brand:** Chuanxu (川序) · **Product:** AI Agent Management Platform
>
> **Technical project:** AI Agent Infra with DB. The database-specific package name
> identifies the OracleDB adapter and edition; it is not a separate product
> brand.

This package is **Skill-first and framework-neutral**. Any Agent runtime that
can install or read `SKILL.md` and execute the packaged HTTP, MCP, or CLI
workflows can use the platform; OpenClaw and Hermes Agent are confirmed
integration examples. The runtime does not need to be created by this
platform. Registration and authentication are still required before an Agent
enters the managed inventory, identity, permission, and audit scope.

## 1. Overview

AI Agent Infra with DB is the technical foundation of the **Chuanxu AI Agent
Management Platform**, built on **Oracle AI Database 26ai**. It collapses the
conventional
"Redis + vector DB + graph DB + object store" stack into a single Oracle
database kernel - leveraging reference partitioning, JSON-Relational
Duality Views, property graph (SQL PGQ), in-database vector search, and
Deep Data Security.

| Edition             | Port | License          |
|---------------------|------|------------------|
| Community           | 8001 (default, configurable) | Apache 2.0       |
| Enterprise          | 8000 (default, configurable) | BSL 1.1          |

Enterprise adds: registered-Agent governance, resource policies and bounded
grants, server-attributed N-of-M approvals, emergency control, risk-based audit
and evidence export, per-agent encryption keys, LDAP auth, compliance logs,
skill tokens, and orchestrator approvals.

v4.3.1 requires every human and external or platform-hosted Agent to resolve to
an active database Principal before using non-bootstrap APIs. Agent enrollment
uses a one-time user-sponsored token; Business Agents receive neither database
credentials nor a Schema Owner fallback. The Enterprise resource catalog
is authoritative for classification; unknown or sensitive resources without an
explicit policy are denied. Approval, emergency, audit, retention, legal-hold,
and evidence-export controls are enforced by the server and database rather
than by Dashboard visibility.

v4.3.2 adds versioned Memory lifecycle controls. Existing Memory is adopted
without changing its external entity ID; ordinary delete becomes reasoned
logical unavailability, while authorized history remains available. Agents may
read current authorized Memory, request bounded chains, submit attributed
feedback or governed candidates, and start only permitted dry-run or managed
jobs. Approved semantic candidates require a separate reasoned activation that
creates a successor Version; snapshot refresh and job completion are fenced.
Memory content and model output are untrusted data and never authority.
MCP exposes `memory_lifecycle_create`, `memory_lifecycle_chain`,
`memory_lifecycle_feedback`, and `memory_lifecycle_candidate` only for the
authenticated Agent's own Memory Versions; candidates still require governed
review and separate activation.

The Organization workspace is a governed query and change interface. Agents
may discover only organization facts allowed by their authenticated Principal
and `organizations.*` scope. Reading this Skill does not grant graphical edit,
Human administration, directory synchronization, or publication authority.
Relational facts remain authoritative; Oracle SQL/PGQ is a projection only.

## 2. Package Contents

After extracting the release zip, you have:

```
AI-Agent-Infra-with-OracleDB-{Community,Enterprise}-Edition/
├── SKILL.md                        # this file
├── CHANGELOG.md                    # full version history
├── RELEASE_NOTES_v4.3.2.md   # this release's notes
├── NOTICE                          # third-party attributions
├── LICENSE  /  LICENSE_ENTERPRISE  # edition-specific license
├── requirements.txt                # pinned Python deps
├── config.example.json             # placeholder config template
├── start_web_server.sh             # server control script
├── docs/                           # deep-dive docs
│   ├── introduction_zh.md          # Chinese project introduction
│   ├── architecture.md
│   ├── api-reference.md
│   ├── security.md
│   ├── deployment.md
│   └── ...
├── vendor/                         # bundled Python wheels; verify before offline install
└── scripts/
    ├── config_wizard.sh            # first-run interactive config prompt
    ├── install_offline.sh          # install vendor/ wheels (no PyPI)
    ├── verify_deps.py              # pre-flight dependency checker
    ├── deploy_oracle.py            # pure-Python SQL deploy (no SQLcl)
    ├── agent_bootstrap.py          # Business Agent registration CLI
    ├── deploy/                     # SQL scripts (run in order)
    │   ├── 0_oracle_text_prerequisites.sql # SYSDBA Oracle Text grants
    │   ├── 1_schema.sql            #   tables, indexes, partitions
    │   ├── 2_api.sql               #   PL/SQL packages (API layer)
    │   ├── 3_jobs.sql              #   scheduler jobs
    │   ├── 4_harness_templates.sql #   agent harness templates
    │   ├── 4_grants.sql            #   Deep Data Security grants
    │   ├── 5_audit_policy.sql      #   unified audit (Enterprise)
    │   ├── 6_deep_sec_policy.sql   #   Deep Sec policies (Enterprise)
    │   ├── 8_v4_1_0_registration.sql # registered-Agent boundary (Community)
    │   ├── 8_v4_1_0_governance.sql   # registration + governance (Enterprise)
    │   ├── 9_v4_2_0_graph_engineering.sql
    │   ├── 10_v4_2_0_graph_runtime.sql
    │   ├── 11_v4_2_0_graph_control.sql
    │   ├── 12_v4_2_0_graph_edge_scope.sql
    │   ├── 13_v4_2_0_scheduler_ha.sql # Enterprise overlay only
    │   ├── 14_v4_2_0_graph_triggers.sql
    │   ├── 15_v4_2_1_executor_registry.sql # internal closure
    │   ├── 16_v4_3_0_identity_channels.sql
    │   ├── 17_v4_3_0_governance_lifecycle.sql
    │   ├── 18_v4_3_0_security_lifecycle.sql
    │   └── 19_v4_3_1_organization_governance.sql
    ├── lib/                        # business modules
    │   ├── connection.py           #   oracledb thin-mode pool
    │   ├── config.py               #   config loader (auto-decrypts)
    │   ├── connection_crypto.py    #   PBKDF2 + AES-256-GCM
    │   ├── agent_api.py            #   End User management
    │   └── ...                     #   knowledge/graph/memory/loop/...
    ├── tools/
    │   └── encrypt_config.py       # manual encrypt/decrypt CLI
    ├── tests/                      # pytest suite
    └── visualization/
        ├── server.py               # HTTP server (single source of VERSION)
        ├── static/                 # CSS, JS
        └── templates/              # HTML pages
```

## 3. Prerequisites

| Component | Minimum | Notes |
|-----------|---------|-------|
| Oracle AI Database | 26ai (23.26.2+) | Deep Data Security requires 23.26.2+ |
| Python | 3.8+ (3.14 recommended) | oracledb thin mode - no Oracle Client needed |
| oracledb driver | 4.0.1+ | bundled in `vendor/` |
| DBMS_CRYPTO grant | required | `GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <user>;` |
| Oracle Text grants | required before `1_schema.sql` | `CTXAPP` + `EXECUTE ON CTXSYS.CTX_DDL` |
| Memory | 2 GB free | for connection pool + vector search |

## 4. Installation (offline-capable runtime)

The compiled Web assets run without Node.js, npm, or network access. Python
installation is offline only when every requirement in `requirements.txt` has
an exact compatible wheel in `vendor/`; `verify_deps.py` is the release gate
and must pass before using `install_offline.sh`.

```bash
# 1. Extract the zip
unzip AI-Agent-Infra-with-OracleDB-Enterprise-Edition-v4.3.2.zip
cd AI-Agent-Infra-with-OracleDB-Enterprise-Edition

# Select any accessible Python 3.14+ runtime; no vendor-specific path is required.
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"

# 2. Install Python dependencies from the bundled wheels
bash scripts/install_offline.sh

# 3. Verify all dependencies are present
"$PYTHON_BIN" scripts/verify_deps.py
```

The `install_offline.sh` script installs the verified wheels from `vendor/`
into the active Python's site-packages, including `oracledb-4.0.1`. It fails
closed when a required wheel is missing or incompatible; obtain the missing
release dependencies from the approved internal mirror before retrying.

`vendor/` may contain both the upstream `cryptography==49.0.0` wheel for
glibc 2.34+ and the RHEL 8/glibc 2.28 source-built wheel. The installer and
`verify_deps.py` select the compatible one automatically. Customers on newer
systems do not need to rebuild cryptography; the reproducible source-build
procedure is documented in `docs/cryptography-build.md`.
The current v4.3.2 archive includes the verified glibc 2.28 wheel; do not
rename the `manylinux_2_34` wheel or substitute an older cryptography release.

## 5. Configuration

The zip ships **`config.example.json`** with `<PLACEHOLDER>` values only -
real credentials are NEVER bundled. Two ways to produce a runnable
`config.json`:

### Path A: Interactive wizard (recommended for first run)
```bash
./start_web_server.sh start
# -> wizard auto-detects <PLACEHOLDER> tokens and prompts for:
#     database: user / password / dsn (host:port/service)
#     llm:      api_url / model / api_key
#     embedding: api_url / model / dimension
# -> writes config.json
# -> server then auto-encrypts sensitive sections on first boot
```
Standalone invocation:
```bash
bash scripts/config_wizard.sh
```

### Path B: Manual edit
```bash
cp config.example.json config.json
vim config.json   # replace every <PLACEHOLDER> with a real value
./start_web_server.sh start
```

### Auto-encryption
On first startup, `auto_encrypt_config()` encrypts sensitive fields in the
`database`, `security`, `llm`, and `model_routing` sections of `config.json`
as AES-256-GCM `_encrypted` blobs. This includes database credentials, API
keys, and `security.secret_key`; non-sensitive policy remains readable. The
server enforces owner-only (`0600`) permissions and decrypts transparently.

Manual encrypt / decrypt:
```bash
"$PYTHON_BIN" scripts/tools/encrypt_config.py encrypt config.json
"$PYTHON_BIN" scripts/tools/encrypt_config.py decrypt config.json
```

## 6. Database Schema Deployment

The release includes `scripts/deploy_oracle.py` - a pure-Python SQL
deployment tool (no SQLcl, no Java required). It runs the SQL scripts
in `scripts/deploy/` in order.

```bash
# Oracle Text must be prepared in the target PDB by a DBA before the schema
# owner creates the CONTEXT index and MULTI_COLUMN_DATASTORE preference.
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys <sys_password> <host>:1521/<service> \
    scripts/deploy/0_oracle_text_prerequisites.sql

# Deploy schema + API packages + jobs (Enterprise)
"$PYTHON_BIN" scripts/deploy_oracle.py <user> <password> <host>:1521/<service> \
    scripts/deploy/1_schema.sql \
    scripts/deploy/7_v4_0_1_migration.sql \
    scripts/deploy/2_api.sql \
    scripts/deploy/3_jobs.sql \
    scripts/deploy/4_harness_templates.sql

# Grants and Enterprise security scripts run as SYSDBA or with their
# documented administrative privileges.
"$PYTHON_BIN" scripts/deploy_oracle.py --sysdba sys <sys_password> <host>:1521/<service> \
    scripts/deploy/4_grants.sql \
    scripts/deploy/5_audit_policy.sql
"$PYTHON_BIN" scripts/deploy_oracle.py <user> <password> <host>:1521/<service> \
    scripts/deploy/6_deep_sec_policy.sql
```

For Community Edition, skip `5_audit_policy.sql`, `6_deep_sec_policy.sql`, and
`8_v4_1_0_governance.sql`; deploy `8_v4_1_0_registration.sql` after the common
schema scripts. Enterprise deploys the governance script instead of the
registration overlay because it creates both registration and governance
objects.

Verify deployment:
```bash
curl http://localhost:<port>/api/agent/deployment-check
```

The schema script `1_schema.sql` is idempotent - it auto-aborts if
`SYSTEM_CONFIG.schema_version` already exists. It also verifies that the
`ENTITIES_MCD` preference exists and that `ENTITIES_SEARCH_CTX` has
`DOMIDX_STATUS=VALID` and `DOMIDX_OPSTATUS=VALID`; missing Oracle Text
prerequisites fail the deployment instead of leaving a broken search index.

For the integrated v4.3.0 profile, use `scripts/migration_runner.py` for the
additive migration tail. Community applies these nine scripts in order:
`9_v4_2_0_graph_engineering.sql`, `10_v4_2_0_graph_runtime.sql`,
`11_v4_2_0_graph_control.sql`, `12_v4_2_0_graph_edge_scope.sql`,
`14_v4_2_0_graph_triggers.sql`, `15_v4_2_1_executor_registry.sql`,
`16_v4_3_0_identity_channels.sql`, and
`17_v4_3_0_governance_lifecycle.sql`, and
`18_v4_3_0_security_lifecycle.sql`. Enterprise inserts
`13_v4_2_0_scheduler_ha.sql` between `12` and `14`, for ten scripts total.
The internal `15` step is part of v4.3.0 and is not a public v4.2.1 release.

## 7. Start the Server

```bash
./start_web_server.sh start     # start (daemon mode, calls wizard if needed)
./start_web_server.sh status    # check status
./start_web_server.sh stop      # stop
./start_web_server.sh restart   # restart
./start_web_server.sh config    # print resolved config
```

Access the dashboard at `http://<host>:<port>` - login: `admin / <password>`
(the password is set in `config.json` under `security.admin_password`).

## 8. Business Agent Registration

Business Agents register against the Admin Agent to obtain encrypted
database credentials:

```bash
# Register a new Business Agent
"$PYTHON_BIN" scripts/agent_bootstrap.py register \
    --agent-id MY_AGENT \
    --agent-name "My Business Agent" \
    --admin-token AT_xxx \
    --admin-url http://<admin-host>:<port>

# Test the resulting connection
"$PYTHON_BIN" scripts/agent_bootstrap.py test

# Recover if the agent crashed and lost credentials
"$PYTHON_BIN" scripts/agent_bootstrap.py recover \
    --agent-id MY_AGENT \
    --recovery-code RC-XXXX-XXXX-XXXX \
    --admin-token AT_xxx \
    --admin-url http://<admin-host>:<port>
```

The bootstrap CLI auto-detects the driver from `agent_config.json`'s
`db_type` field (set to `"oracle"` by this adapter) and imports `oracledb`.

The End User password is created via `END_USER_MANAGER.ensure_end_user`
and distributed encrypted with `admin_token` as the PBKDF2 salt source.

## 9. API Reference

Once the server is running, these endpoints are available:

| Category | Endpoint | Method | Description |
|----------|----------|--------|-------------|
| **System** | `/api/health` | GET | Health check |
| **Auth** | `/api/login` | POST | Admin login |
| **Agents** | `/api/agents` | GET/POST | List / register agents |
| **Agents** | `/api/agents/discover` | GET | Discover pool agents |
| **Memory** | `/api/memory` | GET/POST | Memory search / store |
| **Knowledge** | `/api/knowledge` | GET/POST | Knowledge base CRUD |
| **Graph** | `/api/graph/all` | GET | Full graph |
| **Graph** | `/api/graph/search` | POST | Graph search |
| **Graph** | `/api/graph/neighbors` | POST | Neighbor traversal |
| **Graph** | `/api/graph/causal` | GET | Causal subgraph |
| **Tasks** | `/api/tasks` | GET/POST | Task management |
| **Branches** | `/api/branches` | GET/POST | Context branches |
| **Monitor** | `/api/monitor/overview` | GET | System overview |
| **Monitor** | `/api/monitor/agents` | GET | Agent status |
| **Monitor** | `/api/monitor/metrics` | GET | Performance metrics |
| **Portal** | `/portal/api/login` | POST | Portal user login |
| **Portal** | `/portal/api/chat/send` | POST | Portal chat (SSE) |
| **Enterprise** | `/api/admin/crypto/rotate` | POST | Rotate encryption keys |
| **Enterprise** | `/api/approvals` | GET/POST | Approval requests |
| **Enterprise** | `/api/audit` | GET | Audit trail |
| **Enterprise** | `/api/governance/resources` | GET/POST | Governed resource catalog |
| **Enterprise** | `/api/governance/decide` | POST | Server-side policy decision |
| **Enterprise** | `/api/governance/approvals/{id}/decision` | POST | N-of-M approval decision |
| **Enterprise** | `/api/governance/emergency` | GET/POST | Emergency disable and retry |
| **Enterprise** | `/api/governance/evidence/export` | GET | Scoped evidence export |
| **Agent Protocol** | `/ap/v1/agent/tasks` | POST | Agent Protocol compat |

Full API details: `docs/api-reference.md`.

### Canonical And Legacy Entry Points

New integrations use the authenticated FastAPI service (`web_app:app`) and
its Principal-aware `/api/auth/*`, resource, Graph, Channel, Barrier, Gateway,
and governance routes, or the equivalent HTTP/MCP/Skill workflow. The
established Dashboard, Portal, and Agent paths are retained through the
request-local compatibility bridge to `visualization/server.py`; the bridge
does not open a second listener or grant direct database access. Legacy callers
remain subject to session, CSRF, Agent identity, and permission checks. The
`production` runtime profile exposes the integrated v4.3.2 stable core and is
the current production recommendation; the v4.3.2 release and closure evidence
are PASS. `graph-preview` and `development` remain explicitly controlled
profiles for experimental capabilities.

## 10. Security Model

| Layer | Mechanism |
|-------|-----------|
| Row-level isolation | **Deep Data Security** (Data Grants + MAC + End Users) |
| Column encryption | `DBMS_CRYPTO` (AES-256-GCM) |
| Auth | Local users + LDAP (Enterprise) |
| Audit | Unified Audit + `audit_api` (Enterprise) |
| Governance | Resource policy, bounded grants, approvals, emergency control (Enterprise) |

Each Business Agent gets its own Oracle END_USER. The End User password
is stored encrypted in `SYSTEM_CONFIG` and distributed via the
registration API (encrypted with `admin_token`). The Schema Owner credential is
Admin-only; Business Agent authentication and failed policy checks never fall
back to the Admin pool.

## 11. Testing

```bash
# Run the full test suite
"$PYTHON_BIN" -m pytest scripts/tests/ -v

# Or the legacy runner
cd scripts && "$PYTHON_BIN" -m tests.test_all
```

Tests use the configured owner-only (`0600`) `config.json` connection. Set
`AIAGENT_SKIP_DB=pg,yashandb` to skip unreachable backends.

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `import oracledb` fails | driver not installed | `bash scripts/install_offline.sh` |
| `ORA-01017: invalid credentials` | wrong DB user/password | re-run `bash scripts/config_wizard.sh` |
| `DBMS_CRYPTO` not found | missing grant | `GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <user>;` |
| Server starts but `import yaspy` fails | wrong adapter - this is the Oracle edition | use the YashanDB release zip instead |
| `config.json` has `_encrypted` but server can't decrypt | configured master key does not match | restore the matching `MASTER_DB_KEY` or `~/.ai-agent-infra/master.key` backup |
| Portal chat returns 500 | LLM `api_url` not configured | edit `config.json` -> `llm.api_url` |
| Deployment fails with "schema_version exists" | DB already has schema | use `--force` flag or drop schema first |
| `Deep Data Security` not filtering rows | Oracle version < 23.26.2 | upgrade to 26ai 23.26.2+ |

Server log: `viz_server.log` in the project directory.

## 14. v4.3.0 Integrated Graph Engineering

This package uses the integrated v4.3.0 profile. In addition to the v4.1
runtime, it provides versioned Graph Definitions, deterministic compilation,
durable Graph Runs, State Events, Checkpoints, Workers, Event Inbox/Outbox,
Artifacts, evaluators, reason-required interventions, a versioned Node Executor
registry, bounded delivery attempts, dead-letter replay, and operator
governance events. The existing Graph Explorer remains available in the
Dashboard. The internal v4.2.1 closure is included here and is not a public
package or separate release line.

The migration tail above is part of the same profile and must be applied
through the checksum ledger before using the new Graph, Channel, Barrier, or
governance lifecycle objects.

Oracle AI Database 26ai exposes the execution topology through the native
Property Graph / SQL PGQ adapter. Relational `GRAPH_*` runtime tables remain
the transaction and recovery authority. This is not a direct-DML workflow.

### Principal, Channel, Barrier, And Gateway

Every human and external Agent first resolves to an active database Principal.
An authorized Human creates a one-time Enrollment Token that binds owner,
sponsor, runtime, environment, risk tier, quota, and Security Domain. Channel
membership is a collaboration boundary only; it never grants database, API,
Skill, Tool, model, memory, Artifact, or export access. Barrier participant
snapshots, arrivals, decisions, and Action Cards are durable and attributable.
The Gateway issues short-lived instance tokens, fences deliveries, and on web
restart reclaims only instances belonging to the local node. Business Agents
never receive or fall back to the schema-owner credential.

### Agent Skill Workflow

After registration and authentication, an external Agent can use the common
HTTP or MCP contract:

```bash
# Discover the adapter and registered Graph types
curl -b cookies.txt http://localhost:<port>/api/graph/capabilities
curl -b cookies.txt http://localhost:<port>/api/graph-types

# Create a definition, then create a Draft version
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"name":"support-flow"}' \
  http://localhost:<port>/api/graphs
curl -b cookies.txt -H 'Content-Type: application/json' -d @graph-version.json \
  http://localhost:<port>/api/graphs/<graph_id>/versions

# Compile and publish with an explicit reason, then start a Run
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"reason":"validated POC topology"}' \
  http://localhost:<port>/api/graph-versions/<version_id>/compile
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"reason":"approved for test execution"}' \
  http://localhost:<port>/api/graph-versions/<version_id>/publish
```

Workers claim only scoped work and receive a short Lease Token. They must
heartbeat, checkpoint, and complete/fail with that token; stale fencing tokens
are rejected. A Worker never receives the Schema Owner credential. Use
`/api/graph-runs/<run_id>/state` and `/snapshot` to recover after a process
restart. Existing Task Plan and Loop behavior remains available through the
v4.1 compatibility bridge.

### Executor and delivery operations

Executors are declarative manifests, not arbitrary Python, SQL, shell, or
network callbacks. Built-in `CONTROL`, `WORKER`, and `WAIT` Executors are
resolved for every node before claim and completion. Custom manifests require
an authenticated registration actor; disabling or deprecating one requires a
reason and affects new claims only.

```bash
# Inspect the active and inactive registry rows
curl -b cookies.txt 'http://localhost:<port>/api/graph-executors?include_inactive=true'

# Inspect pending delivery and dead letters
curl -b cookies.txt http://localhost:<port>/api/graph/events/inbox
curl -b cookies.txt http://localhost:<port>/api/graph/events/dead-letter
curl -b cookies.txt http://localhost:<port>/api/graph/events/outbox

# Replay requires an authenticated actor and a non-empty reason
curl -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"reason":"verified downstream availability"}' \
  http://localhost:<port>/api/graph/events/inbox/<inbox_id>/replay
```

The database stores attempt counters, next-available time, maximum attempts,
and terminal `DEAD_LETTER` state. Non-idempotent external work is not blindly
replayed after an uncertain outcome.

The Graph contract may evolve within the v4.3.x maturity cycle. Breaking
changes require a new definition/schema version, migration or review state,
and new release evidence. The v4.3.2 production profile is the current
production baseline; v4.1.x remains available as the prior baseline. The Graph
implementation is graduated by configuration and evidence, not by a second
long-lived implementation.

## 13. Offline Deployment

The release zip contains the compiled Web runtime and the bundled dependency
set. The Web assets require no Node.js, npm, or network access. Python is
offline-installable only after `scripts/verify_deps.py` reports PASS; the
installer fails closed when a required wheel is absent or incompatible.
- `vendor/` - bundled Python wheels
- `scripts/install_offline.sh` - installs verified wheels
- `scripts/verify_deps.py` - integrity check
- `scripts/deploy_oracle.py` - SQL deployment (no SQLcl, no Java)
- `docs/deployment.md` - detailed deployment guide
