# SKILL.md - AI Agent Infra with OracleDB

> **Version:** 4.2.0 | **Driver:** oracledb 4.0.1 | **DB:** Oracle AI Database 26ai 23.26.2+

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

v4.1.0 requires every external or platform-hosted Agent to register and
authenticate before using non-bootstrap APIs. The Enterprise resource catalog
is authoritative for classification; unknown or sensitive resources without an
explicit policy are denied. Approval, emergency, audit, retention, legal-hold,
and evidence-export controls are enforced by the server and database rather
than by Dashboard visibility.

## 2. Package Contents

After extracting the release zip, you have:

```
AI-Agent-Infra-with-OracleDB-{Community,Enterprise}-Edition/
├── SKILL.md                        # this file
├── CHANGELOG.md                    # full version history
├── RELEASE_NOTES_v4.2.0.md   # this release's notes
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
├── vendor/                         # 30 pre-downloaded wheels (offline)
└── scripts/
    ├── config_wizard.sh            # first-run interactive config prompt
    ├── install_offline.sh          # install vendor/ wheels (no PyPI)
    ├── verify_deps.py              # pre-flight dependency checker
    ├── deploy_oracle.py            # pure-Python SQL deploy (no SQLcl)
    ├── agent_bootstrap.py          # Business Agent registration CLI
    ├── deploy/                     # SQL scripts (run in order)
    │   ├── 1_schema.sql            #   tables, indexes, partitions
    │   ├── 2_api.sql               #   PL/SQL packages (API layer)
    │   ├── 3_jobs.sql              #   scheduler jobs
    │   ├── 4_harness_templates.sql #   agent harness templates
    │   ├── 4_grants.sql            #   Deep Data Security grants
    │   ├── 5_audit_policy.sql      #   unified audit (Enterprise)
    │   ├── 6_deep_sec_policy.sql   #   Deep Sec policies (Enterprise)
    │   ├── 8_v4_1_0_registration.sql # registered-Agent boundary
    │   └── 8_v4_1_0_governance.sql   # Enterprise governance objects
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
| Memory | 2 GB free | for connection pool + vector search |

## 4. Installation (offline-friendly)

The release zip is self-contained - no PyPI access needed.

```bash
# 1. Extract the zip
unzip AI-Agent-Infra-with-OracleDB-Enterprise-Edition-v4.2.0.zip
cd AI-Agent-Infra-with-OracleDB-Enterprise-Edition

# 2. Install Python dependencies from the bundled wheels
bash scripts/install_offline.sh

# 3. Verify all dependencies are present
python3 scripts/verify_deps.py
```

The `install_offline.sh` script installs all 30 wheels from `vendor/`
into the active Python's site-packages, including `oracledb-4.0.1`.

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
python3 scripts/tools/encrypt_config.py encrypt config.json
python3 scripts/tools/encrypt_config.py decrypt config.json
```

## 6. Database Schema Deployment

The release includes `scripts/deploy_oracle.py` - a pure-Python SQL
deployment tool (no SQLcl, no Java required). It runs the SQL scripts
in `scripts/deploy/` in order.

```bash
# Deploy schema + API packages + jobs + grants (Enterprise)
python3 scripts/deploy_oracle.py <user> <password> <host>:1521/<service> \
    scripts/deploy/1_schema.sql \
    scripts/deploy/2_api.sql \
    scripts/deploy/3_jobs.sql \
    scripts/deploy/4_harness_templates.sql \
    scripts/deploy/4_grants.sql \
    scripts/deploy/5_audit_policy.sql \
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
`SYSTEM_CONFIG.schema_version` already exists.

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
python3 scripts/agent_bootstrap.py register \
    --agent-id MY_AGENT \
    --agent-name "My Business Agent" \
    --admin-token AT_xxx \
    --admin-url http://<admin-host>:<port>

# Test the resulting connection
python3 scripts/agent_bootstrap.py test

# Recover if the agent crashed and lost credentials
python3 scripts/agent_bootstrap.py recover \
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
python3 -m pytest scripts/tests/ -v

# Or the legacy runner
cd scripts && python -m tests.test_all
```

Tests use the configured `config.json` connection. Set
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

## 14. v4.2.0 Experimental Graph Engineering

This package uses the `experimental-4.2` profile. In addition to the v4.1
runtime, it provides versioned Graph Definitions, deterministic compilation,
durable Graph Runs, State Events, Checkpoints, Workers, Event Inbox/Outbox,
Artifacts, evaluators, and reason-required interventions. The existing Graph
Explorer remains available in the Dashboard.

Oracle AI Database 26ai exposes the execution topology through the native
Property Graph / SQL PGQ adapter. Relational `GRAPH_*` runtime tables remain
the transaction and recovery authority. This is not a direct-DML workflow.

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

The v4.2.x Graph contract is experimental and may evolve. Breaking changes
require a new definition/schema version, migration or review state, and new
release evidence. The latest validated v4.2.x release can graduate to the next
Stable line without maintaining a second implementation.

## 13. Offline Deployment

The release zip is fully self-contained:
- `vendor/` - 30 wheels (no PyPI access needed)
- `scripts/install_offline.sh` - installs all wheels
- `scripts/verify_deps.py` - integrity check
- `scripts/deploy_oracle.py` - SQL deployment (no SQLcl, no Java)
- `docs/deployment.md` - detailed deployment guide
