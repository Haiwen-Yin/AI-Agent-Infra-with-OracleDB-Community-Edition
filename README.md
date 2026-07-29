# AI-Agent-Infra-with-OracleDB-Community-Edition

> **v4.3.0 · Community Edition · Oracle**
>
> Database-backed AI Agent infrastructure for Oracle.

![License](https://img.shields.io/badge/License-Apache_2.0-green)

---

## Product and Technical Naming

This technical release package belongs to **Chuanxu (川序)**, the **AI Agent
Management Platform**. `AI Agent Infra with DB` remains the unified technical
project and source-repository name; per-database names such as `AI Agent Infra
with OracleDB` identify the adapter and edition of this package. Use **Chuanxu / 川序** for
user-facing product references and the technical names for repository,
package, and implementation references.

## Product Overview

Chuanxu (川序) is an AI Agent Management Platform whose technical project name is AI Agent Infra with DB. It makes Agent operation observable, controllable, and traceable by keeping identity, memory, knowledge, workspaces, Skills, execution state, and governance facts in a database. This package provides the Oracle adapter and its Community or Enterprise edition boundary.

This release is a **Skill-first, framework-neutral integration package**.
Any Agent runtime that can install or read `SKILL.md` and execute the packaged
HTTP, MCP, or CLI workflows can use the platform; OpenClaw and Hermes Agent
are confirmed integration examples. The runtime does not need to be created
by this platform. Registration and authentication are still required before
an Agent enters the managed inventory, identity, permission, and audit scope.

The platform is designed to make Agent operation observable, controllable, and
traceable. The database is the durable source of truth for Agent identity,
memory, knowledge, workspaces, task plans, Skills, execution state, and, in
Enterprise, governed resources, authorization decisions, multi-party approval,
emergency control, bounded audit, and evidence export.

This Community Edition provides the complete core runtime, including memory and knowledge management, hybrid search, Agent lifecycle management, workspaces and branches, specification and Loop workflows, collaboration, Harness templates, MCP integration, Portal chat, the management Dashboard, Channels, Barriers, and the registered-Agent admission boundary for external Skill-first runtimes.

## Graph Engineering and Runtime Profiles

This package uses the `production` profile in v4.3.0. The shared code line provides versioned Graph Definitions, deterministic compilation, durable Runs and Checkpoints, lease/fencing Worker execution, Event Inbox/Outbox, bounded retry and dead-letter delivery, the versioned Node Executor registry, Barriers, Channels, Artifacts, governed intervention, and v4.1 Task/Loop compatibility. The database-specific Property Graph projection is an implementation boundary; relational runtime tables remain the transaction and recovery authority. `production` enables the validated stable core, `graph-preview` exposes preview Graph controls, and `development` enables diagnostics.

## 1. Package Contents

```
AI-Agent-Infra-with-OracleDB-Community-Edition/
├── config.example.json       # placeholder template (safe to commit)
├── requirements.txt          # pinned Python deps incl. driver
├── start_web_server.sh       # one-shot launcher (invokes wizard on first run)
├── SKILL.md                  # project identity reference
├── CHANGELOG.md              # full version history (v1.0.0 → current)
├── RELEASE_NOTES_v4.3.0.md   # release notes for this version
├── LICENSE
├── NOTICE
├── docs/                     # architecture, api-reference, security, deployment, ...
└── scripts/
    ├── agent_bootstrap.py    # Business Agent registration CLI
    ├── config_wizard.sh      # first-run interactive config prompt
    ├── verify_deps.py        # pre-flight dependency checker
    ├── install_offline.sh    # offline install from vendor/
    ├── poc_readiness.py      # non-destructive POC prerequisite check
    ├── poc_evidence.py       # four-week acceptance evidence assembly
    ├── support_bundle.py     # bounded, redacted support archive
    ├── migration_runner.py   # additive migration, retry, and ledger runner
    ├── live_db_validator.py  # read-only database capability probe
    ├── deploy_oracle.py
    ├── lib/                  # business modules
    │   ├── connection.py     # oracledb connection layer (adapter)
    │   ├── config.py         # reads config.json (adapter, auto-decrypts)
    │   ├── connection_crypto.py  # auto-encrypt / decrypt config sections
    │   ├── agent_api.py      # Community Edition API surface (adapter)
    │   ├── loop_api.py
    │   └── ...               # memory_api, graph_api, knowledge_api, ...
    ├── deploy/               # SQL deploy scripts
    │   ├── 1_schema.sql
    │   ├── 2_api.sql
    │   ├── 3_jobs.sql
    │   ├── 4_harness_templates.sql
    │   ├── 7_v4_0_1_migration.sql
    │   ├── 8_v4_1_0_registration.sql # registered-Agent identity (all editions)
    │   └── 8_v4_1_0_governance.sql  # Enterprise governance only
    │   ├── 9_v4_2_0_graph_engineering.sql
    │   ├── 10_v4_2_0_graph_runtime.sql
    │   ├── 11_v4_2_0_graph_control.sql
    │   ├── 12_v4_2_0_graph_edge_scope.sql
    │   ├── 13_v4_2_0_scheduler_ha.sql # Enterprise overlay only
    │   ├── 14_v4_2_0_graph_triggers.sql
    │   ├── 15_v4_2_1_executor_registry.sql # internal closure
    │   ├── 16_v4_3_0_identity_channels.sql
    │   ├── 17_v4_3_0_governance_lifecycle.sql
    │   └── 18_v4_3_0_security_lifecycle.sql
    ├── tests/                # pytest suite
    ├── tools/                # runtime encryption and release build helpers
    │   ├── encrypt_config.py
    │   └── build_cryptography_wheel.sh # optional RHEL 8 wheel build
    └── visualization/
        ├── server.py         # HTTP server
        ├── static/
        └── templates/
```

## 2. Requirements

| Component     | Version                                       |
|---------------|-----------------------------------------------|
| Python        | 3.14+                                         |
| Oracle | Oracle AI Database 26ai 23.26.2+                              |
| Driver        | `oracledb>= 4.0.1`       |

Install Python dependencies:

```bash
pip install -r requirements.txt
```

For offline environments, use the bundled `vendor/` wheels:

```bash
./scripts/install_offline.sh
```

The release may carry two `cryptography==49.0.0` wheels: a source-built
`manylinux_2_28` wheel for RHEL 8/glibc 2.28 and the upstream `manylinux_2_34`
wheel for newer systems. `pip` and `scripts/verify_deps.py` select the wheel
that matches the host. See `docs/cryptography-build.md` for the reproducible
RHEL 8 build procedure; customers on newer systems do not need to rebuild it.
The verifier also walks the mandatory `Requires-Dist` metadata of selected
wheels. Any transitive wheel required by the base installation must therefore
be present and compatible, even when it is not repeated as a direct pin in
`requirements.txt`; optional extras are excluded.
The current v4.3.0 package contains the verified glibc 2.28 compatibility
wheel, so it is offline-complete on this baseline; `verify_deps.py` still
fails closed rather than using an incompatible newer-host wheel.

## 3. Configuration

The release ships **`config.example.json`** (placeholder template — safe for
public distribution). Real credentials are NEVER bundled in the zip. Two paths
to produce a runnable `config.json`:

### Path A — Interactive wizard (recommended)

```bash
./start_web_server.sh start
```
On first run, the script detects unresolved `<PLACEHOLDER>` tokens in
`config.json` (or copies the template if missing) and interactively prompts
for:

- **database**: `user`, `password`, `dsn`
- **llm**: `api_url`, `model`, `api_key`
- **embedding**: `api_url`, `model`, `dimension`

You can also run the wizard standalone:
```bash
bash scripts/config_wizard.sh
```

### Path B — Manual edit

```bash
cp config.example.json config.json
vim config.json   # replace every <PLACEHOLDER> with a real value
```

### Auto-encryption on first startup

`config.json` (once filled) is **plaintext on disk only between the wizard
finishing and the server's first boot**. As soon as the web server starts,
`auto_encrypt_config()` rewrites sensitive fields in the `database`,
`security`, `llm`, and `model_routing` sections in place, replacing them with
AES-256-GCM `_encrypted` blobs derived through PBKDF2-HMAC-SHA512. This covers
database credentials, the session-signing secret, and all configured API keys.
Non-sensitive policy fields remain readable, while `config.json` and the local
master key are always restricted to owner-only (`0600`) access.

Manual encrypt / decrypt is also available:
```bash
"$PYTHON_BIN" scripts/tools/encrypt_config.py encrypt config.json
"$PYTHON_BIN" scripts/tools/encrypt_config.py decrypt config.json
```

Environment variables override `config.json` values (see `config.py`).

## 4. Deployment

### Database schema

```bash
"$PYTHON_BIN" scripts/deploy_oracle.py <user> <pass> <dsn> scripts/deploy/1_schema.sql
```

This runs the deploy scripts in `scripts/deploy/`:
`1_schema.sql` → `7_v4_0_1_migration.sql` → `2_api.sql` → `3_jobs.sql` →
`4_harness_templates.sql`. Community packages then run
`8_v4_1_0_registration.sql`; Enterprise packages run
`8_v4_1_0_governance.sql` (which includes the registered-Agent table) and the
database-specific Enterprise security scripts. For the integrated v4.3.0
profile, the migration runner then applies the nine common Graph/lifecycle
scripts `9`, `10`, `11`, `12`, `14`, `15`, `16`, `17`, and `18` in numeric dependency
order. Enterprise packages additionally apply
`13_v4_2_0_scheduler_ha.sql` between `12` and `14`; this makes the total nine
scripts for Community and ten for Enterprise in this migration tail.

### Start the server

```bash
./start_web_server.sh
# or, after selecting any Python 3.14+ runtime
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
PYTHONPATH=scripts "$PYTHON_BIN" -m uvicorn web_app:app --host 0.0.0.0 --port 8001
```

The Chuanxu application is served at `http://<host>:8001/app/monitor`.
There is no universal default password. Create or approve the first
administrator through the deployment bootstrap procedure, then use the
registration and role workflow documented in `docs/api-reference.md`.

## 5. Using the package

1. Fill `config.json` with the target database and model endpoint settings.
2. Deploy the database schema with the adapter-specific command above.
3. Start the server, complete human login, and create a one-time Agent
   Enrollment Token before registering an external Agent.

The complete HTTP, MCP, Skill, Channel, Barrier, Gateway, and governance
contracts are documented in `SKILL.md` and `docs/api-reference.md`. The package
does not require Node.js at runtime; the offline Web assets are already built.

New integrations should use the canonical Principal-aware v4.3.0 API and its
REST, MCP, or Skill credentials. Established v4.1 routes and Python facades are
legacy compatibility entry points; they remain available during migration but
must not be treated as an authorization bypass or as direct database APIs.

## 6. Testing

```bash
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
"$PYTHON_BIN" -m pytest scripts/tests/ -q --tb=no
```

The generated adapter loads the database connection from a local
owner-only (`0600`) `config.json` in the package root. The shared pytest
fixture environment variables do not replace that runtime file; use the
config wizard or a temporary package copy for database-backed tests, and do
not commit or package the real configuration.

## 7. Community Edition Features

- Full memory/knowledge/graph APIs
- Loop Engineering and Task Plan workflows
- MCP Server and Skill-first external Agent integration
- Portal chat with LLM
- Registered-Agent inventory and lifecycle admission
- Offline deployment

## 8. Documentation

See `docs/` for in-depth material: `architecture.md`, `api-reference.md`,
`security.md`, `deployment.md`, `minimum-privileges.md`, `migration.md`,
`visualization.md`, `workspace.md`, `harness.md`, `loop-engineering.md`,
`poc-readiness.md`, `cryptography-build.md`, `python-runtime.md`.

For AI agents working on this codebase, see `docs/AGENTS.md`.

---
