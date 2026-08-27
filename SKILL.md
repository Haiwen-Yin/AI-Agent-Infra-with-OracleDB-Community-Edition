# SKILL.md - AI Agent Infra with OracleDB

> **Version:** 4.4.10 | **Driver:** oracledb 4.0.1 | **DB:** Oracle AI Database 26ai 23.26.2+

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

v4.3.3 adds Graph Runtime assurance records, selected invariant checks, and
canonical Graph Definition provenance, dependency locks, optional Ed25519
signatures, import scanning, and an untrusted-Draft publication gate. Dynamic
Graph, A2A 1.0.1, and OpenTelemetry mapping are preview controls and remain
disabled in `production`. They reuse the existing Principal, policy, Graph
Run, Trace, and Audit authority; they never create a second execution engine
or a new credential path. Local runtime replacement is recoverable from the
reachable database's leases, fencing, Runs, and Checkpoints. This is not an
Oracle HA, Data Guard, RAC, RPO, or RTO claim.

v4.3.4 adds the Enterprise Agent Compliance plane. A registered Agent must
complete its own Gateway credential activation proof before receiving normal
work tokens. Immutable Governed Profile versions, verified evidence, posture
projections, findings, remediation, time-bounded exceptions, and deterministic
restricted or quarantine controls are database-authoritative. Prompt text,
Skill/API descriptions, and Agent self-reports are not authorization
boundaries. The seeded Compliance Admin identity has no credential and is not
an autonomous model runtime.

The Organization workspace is a governed query and change interface. Agents
may discover only organization facts allowed by their authenticated Principal
and `organizations.*` scope. Reading this Skill does not grant graphical edit,
Human administration, directory synchronization, or publication authority.
Relational facts remain authoritative; Oracle SQL/PGQ is a projection only.

v4.4.1 adds a protected Platform Administration Channel and an Admin Agent
availability control plane. Only the protected local administrator, enabled
management Agents, and separately approved Admin Agents may use that Channel;
Business Agents cannot join or read it. Platform-deployed and external Admin
Agents follow different identity-proof, observation, and human-approval paths.
Production should use three healthy Admin Agents with different positive
weights; machine decisions require both member-count and weight majorities,
and Leader term/lease/fencing rejects stale writes. Dashboard and Portal idle
and absolute session policies are independently database-authoritative.

Dashboard upgrades use one signed ZIP upload. The platform validates the
manifest, file digests, database, edition, and version, then discovers governed
nodes and active Agents and records their controlled rollout and Skill update
notifications automatically. Running work remains on its pinned version until
the authenticated Agent reports a safe point. High-risk compatibility routes
retain separated human approval, Admin Agent quorum, and recorded node drain/
migration/health transitions. The Web service does not execute uploaded packages.
Agents poll `/api/gateway/upgrades/skill-pending` through their instance token;
the endpoint returns metadata only. Containment revokes platform access before
asking an Agent to clear memory and stop; NFS, object storage, unified storage,
and infrastructure process termination require customer-specific adapters.

v4.4.2 adds one verified platform-wide Embedding activation workflow. Test the
configured provider first; the platform derives the vector dimension and then
atomically records the active Profile, Contract, writable default Space,
`PLATFORM/DEFAULT` Binding, activation evidence, and audit records. Platform
default normalization is mandatory. When immutable vector-space properties
change, the old Space is archived for readable history and governed
re-embedding, while a new Space becomes the write target. API keys are AES-GCM
encrypted at rest and never returned in evidence or API responses.

The database-authoritative Graph Production Profile is resolved before both
FastAPI and legacy visualization requests. Graph Runtime core and authorized
inspection are production-profile capabilities. A2A, OTLP, Dynamic Graph
migration, replay, and framework execution adapters remain explicitly gated
until independent production evidence is available.

v4.4.3 adds governed Security Domain administration for project collaboration.
Create a dedicated Domain with a purpose, classification, accountable Human
owner, and reason; then confirm each Human or Agent explicitly before Channel
admission or domain-scoped runtime use. A Channel, message, prompt, workspace,
Skill, Tool, API, or legacy collaboration group is not an authorization grant.
Existing collaboration groups may create a conversion draft whose Agents are
pending candidates only. Their historical membership and `SHARING_POLICY` are
review context, never automatic authorization. One group can have one active
Domain binding; `DEFAULT` is reserved for bootstrap or constrained proof of
concept work and is not an implicit production selection.

v4.4.5 adds the immutable Graph Run admission contract. Every new Run
captures the Definition digest, compiled Plan digest, compatibility level,
State schema version, and budget schema version. The service rejects a Plan
that belongs to another Graph Version or has a mismatched digest before it
creates Ready work. A fork containing a non-repeatable external effect starts
paused and requires an approved `GRAPH_FORK_REPLAY` decision bound to the child
Run, or bounded compensation evidence, before resume. Agent Card and protocol
metadata remain descriptive and cannot grant Skills or Tools.

v4.4.6 adds governed Human registration and Portal admission. v4.4.7 is a
small maintenance release that adds saved LLM model-identity probing,
health-state writeback, reference-safe logical retirement, and a batched
real-time capability manifest calculation. Portal and
Dashboard link to one independent registration surface. Display name, email,
and mobile requirements come from a versioned database policy; an optional
purpose-separated Human Registration Token is one-use and is not an Agent
Enrollment Token. Portal connection limits and page-operation leases prevent
one Session from being operated concurrently in copied pages. External
identity providers remain unavailable until a validated customer adapter is
installed; provider claims never grant roles, organization membership, or
Security Domain access. Graph capability posture is explicit and evidence
bound rather than inferred from an Agent Card, prompt, Skill, or protocol
description.

For v4.4.7, Graph Runtime core and authorized inspection are Production
Profile capabilities. Manifest draft import, SLO read-only views, and
checkpoint fork are controlled and require current authorization and evidence.
MCP 2026-07-28 negotiation and `server/discover`, independent A2A 1.0.1
conformance, replacement-Worker resume/de-duplication, sandbox and approval
replay, tool-result compaction, OTLP Collector delivery, and authorization-
filtered GraphRAG projections remain deferred research. An Agent must not
infer support or authority from source modules, protocol metadata, or this
Skill.

## 2. Package Contents

After extracting the release zip, you have:

```
AI-Agent-Infra-with-OracleDB-{Community,Enterprise}-Edition/
├── SKILL.md                        # this file
├── CHANGELOG.md                    # full version history
├── RELEASE_NOTES_v4.4.10.md   # this release's notes
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
    │   ├── 0_oracle_database_prerequisites.sql # consolidated v4.4.10 SYSDBA owner grants
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
    │   ├── 19_v4_3_1_organization_governance.sql
    │   ├── ...                     # journaled additive release steps
    │   ├── 45_v4_4_5_graph_run_contract.sql
    │   ├── 46_v4_4_6_identity_portal_graph.sql
    │   └── 47_v4_4_6_portable_contract_alignment.sql
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
| Python | 3.14+ | selected through `scripts/python_runtime.sh`; oracledb thin mode needs no Oracle Client |
| oracledb driver | 4.0.1+ | bundled in `vendor/` |
| DBMS_CRYPTO grant | required | `GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <user>;` |
| Oracle Text grants | required before `1_schema.sql` | `CTXAPP` + `EXECUTE ON CTXSYS.CTX_DDL` |
| Deep Data Security owner grants | Enterprise required before initialize | Apply the End User, Data Role, Data Grant, context, and mandatory-enforcement grants in `scripts/deploy/4_grants.sql`; preflight reports every missing privilege |
| Partitioning | required by the v4.4.10 Oracle baseline | `V$OPTION` must report `Partitioning=TRUE` |
| Memory | 2 GB free | for connection pool + vector search |

## 4. Installation (offline-capable runtime)

The compiled Web assets run without Node.js, npm, or network access. Python
installation is offline only when every requirement in `requirements.txt` has
an exact compatible wheel in `vendor/`; `verify_deps.py` is the release gate
and must pass before using `install_offline.sh`.

```bash
# 1. Extract the zip
unzip AI-Agent-Infra-with-OracleDB-Enterprise-Edition-v4.4.10.zip
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
The current release archive includes the verified glibc 2.28 wheel; do not
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
#     server:   listen address / Web port
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

Use the checksum-journaled migration runner for every additive release step;
do not select or reorder individual migration files manually:

```bash
"$PYTHON_BIN" scripts/migration_runner.py --preflight --version 4.4.10 \
  --database oracle --edition <community|enterprise> --oracle-config config.json
"$PYTHON_BIN" scripts/migration_runner.py --version 4.4.10 \
  --database oracle --edition <community|enterprise> --oracle-config config.json \
  --confirm-database-backup
```

The runner applies the edition-aware chain through steps `46` and `47`,
checks immutable digests and prerequisites, resumes only journaled incomplete
work, and treats an already applied step as a read-only no-op. The internal
step `15` is part of the integrated release line, not a separate v4.2.1
package.

## 7. Start the Server

```bash
./start_web_server.sh start     # start (daemon mode, calls wizard if needed)
./start_web_server.sh status    # check status
./start_web_server.sh stop      # stop
./start_web_server.sh restart   # restart
./start_web_server.sh config    # print resolved config
```

Access the dashboard at `http://<host>:<port>`. The initial local
administrator is configured by the controlled initialization or deployment
workflow; Dashboard passwords are not stored in or displayed by `config.json`.
Change the initial credential before production use and manage it through the
protected local identity flow.

## 8. Business Agent Registration

The preferred Skill-first path is a user-sponsored, one-use Agent Enrollment
Token. An authorized Human creates it in Dashboard **Agents -> External Agent
registration** (`POST /api/enrollment/grants`). The external Agent redeems it
once at `POST /api/enrollment/redeem` with its Agent ID, runtime, node identity,
and proof material. The Token fixes owner, environment, risk, and optional
Security Domain; it does not grant Skills, Tools, model access, or platform
administration. The Agent then authenticates through the Gateway and uses
instance-scoped short-lived tokens. Never place the Token in a prompt, log,
URL, repository, or long-lived configuration.

The CLI below is the retained Admin-managed bootstrap path for deployments
that explicitly issue an Admin registration token. It is not interchangeable
with Human Registration Tokens or user-sponsored Agent Enrollment Tokens:

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
| **Human registration** | `/api/auth/registration-policy` | GET | Read public registration requirements |
| **Human registration** | `/api/auth/register` | POST | Submit one independent Human registration request |
| **Agent enrollment** | `/api/enrollment/grants` | GET/POST | List or issue governed one-use Agent Enrollment Tokens |
| **Agent enrollment** | `/api/enrollment/redeem` | POST | Redeem one Agent Enrollment Token |
| **Agents** | `/api/agents` | GET/POST | List / register agents |
| **Agents** | `/api/agents/discover` | GET | Discover pool agents |
| **Memory** | `/api/memory` | GET/POST | Memory search / store |
| **Knowledge** | `/api/knowledge` | GET/POST | Knowledge base CRUD |
| **Graph** | `/api/graph/all` | GET | Full graph |
| **Graph** | `/api/graph/search` | POST | Graph search |
| **Graph** | `/api/graph/neighbors` | POST | Neighbor traversal |
| **Graph** | `/api/graph/causal` | GET | Causal subgraph |
| **Tasks** | `/api/tasks` | GET/POST | Task management |
| **SDD** | `/api/sdd/changes` | GET/POST | List or create database-native software-delivery Changes |
| **SDD** | `/api/sdd/revisions/{id}/baseline` | POST | Approve an immutable execution baseline after required review |
| **SDD** | `/api/sdd/revisions/{id}/runs` | POST | Compile an approved revision and create a bounded SDD Run |
| **SDD** | `/api/sdd/evidence` | POST | Record independent Worker/CI evidence and artifact digest |
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
The database-authoritative Graph capability profile labels each capability as
`PRODUCTION`, `CONTROLLED`, `DISABLED`, or `UNAVAILABLE`. Graph Runtime core,
recovery, and governed inspection are production capabilities. Dynamic Graph,
A2A, OTLP, replay, and other interoperability operations are available only
when their explicit capability, edition, authorization, dependency, and
evidence gates allow them. Metadata availability never implies mutation
authority or production conformance.

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
| `DPY-3001` reports Native Network Encryption | the database requires native encryption that the packaged pure-Python connection cannot negotiate | do not weaken encryption silently; use a DBA-approved compatible connection policy or a separately validated Oracle Client deployment path before retrying |
| `ORACLE_PARTITIONING` is blocked | Partitioning is disabled in the active Oracle Home, or `V$OPTION` is not visible | the DBA enables Partitioning and restarts the database, then grants only the read access required for preflight evidence |
| `OWNER_PRIVILEGES` lists Data Grant or End User privileges | the Enterprise owner has only ordinary schema DDL rights | the DBA applies the complete owner privilege set in `scripts/deploy/4_grants.sql`; do not continue with a partial set |
| `ORA-52551` for `ADMIN_DATA_ROLE` | the administrative Data Role was absent in an older or partial package | use the current v4.4.10 package; its security-boundary migration creates the Data Role idempotently |
| `ORA-00942` names another schema owner | an older migration hard-coded `AIADMIN` | use the current v4.4.10 package; active fresh-baseline migrations resolve the configured owner |
| `DPY-4008` reports an unknown bind | package code and Oracle's strict bind set are out of sync | use the current v4.4.10 package; isolation inventory and deployment-state updates now bind exact parameters |
| Server starts but `import yaspy` fails | wrong adapter - this is the Oracle edition | use the YashanDB release zip instead |
| `config.json` has `_encrypted` but server can't decrypt | configured master key does not match | restore the matching `MASTER_DB_KEY` or `~/.ai-agent-infra/master.key` backup |
| Migration preflight reports `FileNotFoundError` for `~/.oracle-infra/master.key` | obsolete package has a migration-only hard-coded legacy key path | replace the complete package with the current v4.4.10 artifact; do not duplicate the key into the retired directory |
| Fresh v4.4.10 baseline is reported as withdrawn v4.4.8 | obsolete preflight ignores current-version migration ledger before object-shape fallback | replace the complete package and rerun preflight; never edit ledger rows or remove retained platform tables manually |
| Portal chat returns 500 | LLM `api_url` not configured | edit `config.json` -> `llm.api_url` |
| Deployment reports an existing or partial schema | target is not a verified empty baseline | never force initialization; use supported `upgrade`/`resume`, or have the DBA restore or precisely clean the target after preserving required data |
| `Deep Data Security` not filtering rows | Oracle version < 23.26.2 | upgrade to 26ai 23.26.2+ |

Server log: `viz_server.log` in the project directory.

### v4.4.10 Oracle fresh-install field validation (2026-08-25)

The release was exercised against an empty Oracle AI Database 26ai Enterprise
schema through terminal migration 65, native Platform/Compliance Agent
postflight, retirement of the Bootstrap Deployment Agent, and a separate
`verify` call. The successful boundary was `RETIRED`, with zero failed
migration steps.

The validation fixed six failure classes that an older package could expose:

1. Foundational schema SQL referenced `SYSTEM_CONFIG` before creation, called
   an unavailable configuration function, and declared a duplicate index.
2. The migration parser truncated anonymous PL/SQL at an inner `END;`, including
   files whose first line declared a local procedure.
3. Memory adoption required `DBMS_CRYPTO` before prerequisite grants. It now
   uses Oracle `STANDARD_HASH` for SHA-256 during baseline migration.
4. The security repair hard-coded `AIADMIN`, assumed `admin_data_role` and
   `AGENT_API` existed, and therefore failed for a configured owner or a clean
   target. The current migration is owner-independent and narrowly idempotent.
5. Enterprise preflight checked too few Deep Data Security privileges. It now
   reports the complete missing owner privilege set before creating tables.
6. Native postflight supplied extra bind values rejected by Oracle. Inventory
   and deployment-state writes now use exact bind sets.

After any failed older attempt, do not run `resume` merely because a local
journal exists. First inspect the database migration ledger and object
inventory. A fresh v4.4.10 initialization is valid only when preflight proves
`TARGET_EMPTY=PASS`; otherwise use an explicitly supported upgrade or a
database-operator-controlled restore/cleanup boundary.

## 13. v4.3.0 Integrated Graph Engineering

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
and new release evidence. v4.3.3 retains the production Graph Runtime baseline
while its Dynamic Graph, A2A, and OpenTelemetry controls remain preview-only.
The Graph implementation is graduated by configuration and evidence, not by a
second long-lived implementation.

## 14. Offline Deployment

The release zip contains the compiled Web runtime and the bundled dependency
set. The Web assets require no Node.js, npm, or network access. Python is
offline-installable only after `scripts/verify_deps.py` reports PASS; the
installer fails closed when a required wheel is absent or incompatible.
- `vendor/` - bundled Python wheels
- `scripts/install_offline.sh` - installs verified wheels
- `scripts/verify_deps.py` - integrity check
- `scripts/deploy_oracle.py` - SQL deployment (no SQLcl, no Java)
- `docs/deployment.md` - detailed deployment guide
## v4.3.6 Native Agent Provisioning

After migration `32_v4_3_6_native_agents.sql`, the platform can bootstrap its
own Platform Admin Agent without an external Agent. Enterprise additionally
seeds a separate Compliance Admin Agent. Business Agents require a human
request, separated approval, an LLM profile, deployment target, isolation
level, and audit reason. External Skill-first enrollment remains available
and is controlled for new registrations by `ENABLED`, `APPROVAL_ONLY`, or
`DISABLED` policy. Use `migration_runner.py --version 4.3.6` and do not put
Schema Owner credentials in a Business Agent configuration.

## v4.3.7 Bootstrap Deployment And Embedding Contracts

For a prepared target, run the package-local Bootstrap Deployment Agent:

```bash
bash scripts/install_platform.sh initialize --database oracle \
  --edition <community|enterprise> --version 4.4.10 --config config.json
```

It verifies a checksum-bound package manifest, executes only packaged SQL, and
executes through the manifest's terminal migration. It requires a verified
empty target, records a database-managed recovery boundary, and does not
require client-side backup evidence. Interactive initialization
prompts twice for the first `admin` password; automation must use a current-user-
owned `0600` regular file with `--admin-password-file`. Only the Argon2id hash
is stored. The command records sanitized deployment evidence before retiring
its temporary identity.
It does not create PDBs, tablespaces, or privileged Oracle infrastructure.
Use `status`, `verify`, `resume`, or `upgrade` with the same command wrapper.
An interactive upgrade explains the database-native recovery boundary and
requires `UPGRADE`; automation passes `--confirm-database-backup`. The accepted
responsibility is journaled, but this client never claims to verify an Oracle
backup or requires a client-side evidence file.
Embedding Profiles, immutable Contracts, Spaces, and bindings govern every
vector write and retrieval. Choose exactly one mode: `PLATFORM_MANAGED`,
`ENTERPRISE_DIRECT`, `ENTERPRISE_PROXY`, `PRECOMPUTED_IMPORT`, or `NONE`.
Run bounded managed ingestion separately with
`scripts/embedding_worker.py --limit 10`; LLM output never controls SQL or
deployment authority.

## v4.4.0 Database-Native SDD And Governed Delivery

Use the database-native SDD control plane for multi-Agent software delivery.
Create a Change with `POST /api/sdd/changes`, add typed requirement, scenario,
acceptance-criterion and task clauses with
`POST /api/sdd/revisions/{id}/clauses`, and use
`POST /api/sdd/clauses/{id}/patch` only with the current `expected_version`.
An authorized reviewer approves the immutable execution baseline with
`POST /api/sdd/revisions/{id}/baseline`; only then may an authorized operator
compile and start a bounded run through `POST /api/sdd/revisions/{id}/runs`.

The database is the execution authority for Change, Working Revision,
Approved Baseline, Task, Review, Gate, Resource Lease, SCM connection, and
evidence. Record independent Worker or CI results, commit references, and
artifact digests with `/api/sdd/evidence`; register only a controlled SCM
credential reference through `/api/sdd/scm`. Do not put secrets, unrestricted
source payloads, or model reasoning in task text or evidence.

OpenSpec may create, import, export, or validate proposal/design/task/spec
material before handoff. After a baseline is approved, OpenSpec CLI and local
Markdown are not execution state and must not control code changes, tests,
reviews, gates, or release decisions. Conflict, missing evidence, or high-risk
Graph changes pause the affected run for governed review; do not bypass a gate
by editing database tables or calling adapter SQL directly.

## v4.4.4-v4.4.7 Current Operations

v4.4.4 adds governed Admin Agent and Agent Pool node/storage configuration,
external database endpoints, Portal LLM allowlists, platform templates, and
logical retirement for nodes and LLM profiles. Local Agent information paths
are configured per node; Admin runtime sharing and Agent Pool runtime sharing
remain separate purposes. Platform Administration Channel requests may create
typed inspection or preparation proposals, but mutations still require an
authorized Action Card, reason, and applicable approval.

v4.4.5 admits Graph Runs only when Definition, compiled Plan, runtime profile,
state schema, budget schema, and capability contracts match. Non-repeatable
forks start paused until governed approval or compensation evidence exists.

v4.4.6 adds one Human registration page, versioned field and Token policies,
provider-neutral external identity transactions, Portal connection limits,
exclusive page-operation leases, and explicit Graph capability posture. Apply
steps `46` and `47` only through the migration runner. An Agent consuming this
Skill must fail closed on unknown registration fields, unavailable providers,
lease conflicts, missing capability evidence, or authorization failures.

v4.4.7 adds saved LLM probing and lifecycle safety without changing the
database authorization boundary.

v4.4.8 hardens the platform command and maintenance control plane. Command
discovery and help come from the database registry, not from an Agent Card or
prompt. Safe autonomy is disabled by default; high-impact work always needs a
final human approval. The Enterprise Compliance Agent remains proposal-only.
Platform private knowledge is isolated with Oracle Data Grants, and the
application-context setter requires the current Deep Data Security End User
unless the deployment Owner is performing an administrative bootstrap.
Apply step `48` only through the migration runner after explicitly confirming
database-side backup responsibility.
