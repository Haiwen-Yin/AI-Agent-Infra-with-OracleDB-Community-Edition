# AI-Agent-Infra-with-OracleDB-Community-Edition

> **v4.0.1 · Community Edition · Oracle**
>
> Database-backed AI Agent infrastructure for Oracle.

![License](https://img.shields.io/badge/License-Apache_2.0-green)

---

## Product Overview

AI Agent Infra with Oracle is a database-backed infrastructure layer for operating AI Agents on Oracle AI Database 26ai. It persists Agent identities, memory, knowledge, graph relationships, workspaces, specifications, task plans, Skills, and execution state in the database so that Agents can share governed context across sessions.

The runtime combines Oracle vector search, full-text search, property graph queries, JSON-relational data, PL/SQL APIs, and database scheduling. Admin and Business Agent identities are separated, and Business Agent requests fail closed instead of falling back to schema-owner access.

This Community Edition provides the complete core runtime, including memory and knowledge management, hybrid search, Agent lifecycle management, workspaces and branches, specification and Loop workflows, collaboration, Harness templates, MCP integration, Portal chat, and the management Dashboard.

## 1. Package Contents

```
AI-Agent-Infra-with-OracleDB-Community-Edition/
├── config.example.json       # placeholder template (safe to commit)
├── requirements.txt          # pinned Python deps incl. driver
├── start_web_server.sh       # one-shot launcher (invokes wizard on first run)
├── SKILL.md                  # project identity reference
├── CHANGELOG.md              # full version history (v1.0.0 → current)
├── RELEASE_NOTES_v4.0.1.md   # release notes for this version
├── LICENSE
├── NOTICE
├── docs/                     # architecture, api-reference, security, deployment, ...
└── scripts/
    ├── agent_bootstrap.py    # Business Agent registration CLI
    ├── config_wizard.sh      # first-run interactive config prompt
    ├── verify_deps.py        # pre-flight dependency checker
    ├── install_offline.sh    # offline install from vendor/
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
    │   └── 4_harness_templates.sql
    ├── tests/                # pytest suite
    ├── tools/                # encrypt_config.py
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
python3 scripts/tools/encrypt_config.py encrypt config.json
python3 scripts/tools/encrypt_config.py decrypt config.json
```

Environment variables override `config.json` values (see `config.py`).

## 4. Deployment

### Database schema

```bash
python3.14 scripts/deploy_oracle.py <user> <pass> <dsn> scripts/deploy/1_schema.sql
```

This runs the deploy scripts in `scripts/deploy/`:
`1_schema.sql` → `7_v4_0_1_migration.sql` → `2_api.sql` → `3_jobs.sql` → `4_harness_templates.sql`.

### Start the server

```bash
./start_web_server.sh
# or
python3.14 scripts/visualization/server.py
```

The portal is served at `http://<host>:8001/`. Default admin login:
`admin` / `admin`.

## 5. API Surface

The primary management and Portal endpoints are listed below.

| Endpoint                      | Method | Description                       |
|-------------------------------|--------|-----------------------------------|
| `/api/health`                 | GET    | Liveness probe, returns version   |
| `/api/login`                  | POST   | Admin login, returns session_id   |
| `/api/knowledge`              | GET    | Knowledge entity list             |
| `/api/memory`                 | GET    | Memory nodes and edges            |
| `/api/agents`                 | GET    | Registered agents & sessions      |
| `/api/graph/all`              | GET    | All graph nodes and edges         |
| `/api/graph/stats`            | GET    | Graph statistics                  |
| `/api/graph/search?q=...`     | GET    | Entity search                     |
| `/api/tasks`                  | GET    | Task plans                        |
| `/api/monitor/overview`       | GET    | Agent overview                    |
| `/api/monitor/agents`         | GET    | Agent status list                 |
| `/api/monitor/metrics`        | GET    | Performance metrics               |
| `/portal/api/login`           | POST   | End-user portal login             |
| `/portal/api/chat/send`       | POST   | Portal chat (stream or non-stream)|

## 6. Testing

```bash
python3.14 -m pytest scripts/tests/ -q --tb=no
```

## 7. Community Edition Features

- Full memory/knowledge/graph APIs
- Loop Engineering (6 eval types)
- MCP Server (10+ tools)
- Portal chat with LLM
- Offline deployment

## 8. Documentation

See `docs/` for in-depth material: `architecture.md`, `api-reference.md`,
`security.md`, `deployment.md`, `minimum-privileges.md`, `migration.md`,
`visualization.md`, `workspace.md`, `harness.md`, `loop-engineering.md`.

For AI agents working on this codebase, see `docs/AGENTS.md`.

---
