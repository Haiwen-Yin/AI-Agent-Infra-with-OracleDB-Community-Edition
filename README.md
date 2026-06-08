# AI Agent Infra with OracleDB - Community Edition v3.4.0

[![Version](https://img.shields.io/badge/version-v3.4.0-blue.svg)](CHANGELOG.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-red.svg)](https://www.oracle.com/database/)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)

**AI Agent的基础设施架构 — Community Edition with Context Branching, Multi-Agent Collaboration, Database Access Security (5+1 layers), Portal user system, and Agent pool management — built on Oracle 26ai.**

> **v3.4.0: Deep Data Security — fully enforcing via Direct Logon with Local End Users; 5+1-layer security model (Constraint, Restricted User, AUTHID DEFINER, Deep Data Security (Data Grants + MAC), Sanitization) replacing VPD; Portal agent context integration for data isolation.** See [CHANGELOG.md](CHANGELOG.md) for details.

📄 **[中文完整介绍 / Full Chinese Introduction](docs/introduction_zh_v3.4.0.md)**

---

## 5-Signal Unified Hybrid Search

The project provides a 10-strategy unified search API (`search_api.py`) for AI agents to retrieve across all data types. The **recommended production strategy** is `unified_sql` — a single-SQL CTE that fuses 5 signals in one database call:

| Signal | Default Weight | Source |
|--------|---------------|--------|
| Vector | 0.40 | `VECTOR_DISTANCE(EMBEDDING, TO_VECTOR(:vec), COSINE)` |
| Fulltext | 0.25 | Oracle Text `CONTAINS + SCORE(1)` |
| Relational | 0.20 | `KNOWLEDGE_META` / `SPEC_META` / `ENTITIES` metadata |
| Tag | (included in relational) | `ENTITY_TAGS` overlap ratio |
| Graph | 0.15 | `ENTITY_EDGES` BFS proximity (1/depth decay) |

**Why `unified_sql` is recommended**:
- Eliminates 5 Python-SQL round trips → single database call
- Server-side scoring → no data transfer overhead
- 70-85% lower latency in production
- Returns `engine: "single_sql"` for identification

```python
from lib.search_api import search

# Recommended: single-SQL 5-signal fusion
results = search("database partitioning", strategy="unified_sql", top_k=10)

# Alternative: multi-round fusion (for debugging individual signal scores)
results = search("database partitioning", strategy="unified", top_k=10)

# Auto-detect best strategy
results = search("encryption", strategy="auto")
```

All 10 strategies: `vector`, `fulltext`, `keyword`, `graph`, `hybrid`, `unified`, `unified_sql`, `relational`, `multi_type`, `auto`

---

## Portal User System

Two independent page systems: **Portal** (user-facing: register/login/chat) and **Dashboard** (admin-facing: data management). Root `/` redirects to Portal.

### Portal Login (`/portal/login`)

- Register/login with local system user authentication
- Registration checks SYSTEM_USERS (case-insensitive) for duplicates
- "进入管理页面" button in top-right corner

### Portal Chat (`/portal/chat`)

- **Sidebar**: user info (name + auth type), session list with rename/delete, new chat button
- **Main area**: chat messages, input box, simulated keyword-based replies
- **Session management**: create/switch/rename/delete chat sessions
- **Auto-naming**: new sessions named "New Chat"; auto-renamed to first 60 chars of first message via `WORKSPACE_ALIAS`
- **Agent lifecycle**: POOL → ACTIVE (assigned) → POOL (released)

#### Agent Timeout Auto-Recall

| Config Key | Default | Description |
|------------|---------|-------------|
| `dormant_timeout_min` | 30 min | Agent idle beyond this → auto-recalled to POOL via `DORMANT_AGENT_JOB` |
| `session_timeout_min` | 60 min | Portal session timeout |

Core logic: `LAST_ACTIVE_AT` older than `dormant_timeout_min` → `STATUS='POOL'`, `CURRENT_USER_ID=NULL`.

Change timeout:
```sql
UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = '10' WHERE CONFIG_KEY = 'dormant_timeout_min';
COMMIT;
```

### Admin Dashboard (`/login`)

- Only LOCAL users can access admin Dashboard
- All existing data management pages unchanged

### Encrypted Credentials

- `config.json`: DB `user`/`password`/`dsn` encrypted as `_encrypted` blob
- `AGENT_CREDENTIALS.CREDENTIAL_VALUE`: encrypted with master key (fixed from broken random-key encryption)
- Master key: env `MASTER_DB_KEY` > `~/.oracle-infra/master.key` > auto-generate

> **For Enterprise Edition features (LDAP, Skill Tokens, Encrypted Config CLI, Context Audit), see the [Enterprise Edition](https://github.com/Haiwen-Yin/AI-Agent-Infra-with-OracleDB-Enterprise-Edition).**

---

## Editions

| Feature | Community Edition | Enterprise Edition |
|---------|------------------|-------------------|
| **Core Infrastructure** | | |
| Memory System & Knowledge Graph | Yes | Yes |
| 5-Signal Unified Hybrid Search | Yes | Yes |
| Spec Driven Development | Yes | Yes |
| Agent Elastic Management | Yes | Yes |
| Collaboration Groups | Yes | Yes |
| Multi-Agent Collaboration (Branch+Spec+Plan+Harness) | Yes | Yes |
| Workspace & Context Continuity | Yes | Yes |
| Context Branching | Yes | Yes |
| Property Graph API | Yes | Yes |
| Harness Templates | Yes | Yes |
| Web Visualization Dashboard | Yes | Yes |
| **Portal User System** | | |
| Portal Login / Register | Yes (System User only) | Yes (System User + LDAP) |
| Portal Chat with Sessions | Yes | Yes |
| Session Rename / Delete | Yes | Yes |
| Agent Pool Assignment | Yes | Yes |
| **Identity & Authentication** | | |
| Local System User Auth | Yes | Yes |
| LDAP Unified Authentication | No | Yes |
| LDAP Auto-Registration | No | Yes |
| LDAP Sync Job | No | Yes |
| Admin Dashboard Isolation (LOCAL only) | Yes | Yes |
| **Skill System** | | |
| Skill CRUD (skill_api.py) | Yes | Yes |
| Secure Token Distribution (skill_token_api.py) | No | Yes |
| **Security & Encryption** | | |
| Encrypted config.json (DB credentials) | Yes | Yes |
| Encrypted AGENT_CREDENTIALS | Yes | Yes |
| Master Key Management | Yes | Yes |
| Data Masking | Yes | Yes |
| **Database** | | |
| Tables | 30 | 35 |
| PL/SQL Packages | 10 | 13 |
| Scheduler Jobs | 13 | 17 |
| **License** | Apache 2.0 | BSL 1.1 |

---

## Quick Start

### ⚠️ Pre-Deployment Safety Check (REQUIRED)

**Before running ANY deploy script, check whether the database already has an existing deployment. Re-running deploy scripts on an existing database will DESTROY all data.**

```python
from lib.deploy_api import check_deployment
result = check_deployment()
if result["deployed"]:
    # DO NOT deploy! Only register this Skill.
    pass
else:
    # Safe to deploy from scratch
    pass
```

HTTP endpoint (public, no auth):
```bash
curl http://localhost:8000/api/agent/deployment-check
```

The `1_schema.sql` script now includes built-in protection: it auto-aborts if `SYSTEM_CONFIG.schema_version` exists.

### Prerequisites

- **Oracle AI Database 26ai version 23.26.2.0.0 or later** (required for Deep Data Security)
- **Python 3.8+ with `oracledb 4.0.1+`** (4.0.0 has TCPS/Deep Sec issues; 4.1.0+ recommended when available)
- SQLcl 26.1+ (for SQL script deployment)
- `GRANT EXECUTE ON SYS.DBMS_CRYPTO` (required for DB_CRYPTO in-database encryption)

> ⚠️ **Critical**: Oracle AI Database 26ai must be version **23.26.2** or later. Earlier versions (23.26.1) have incomplete Deep Data Security support. Check with: `SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle%';`

> ⚠️ **Critical**: Python `oracledb` must be version **4.0.1** or later. Install with: `pip install oracledb>=4.0.1`

### 1. Deploy Schema

```bash
sql user/password@//host:port/service @scripts/deploy/1_schema.sql
sql user/password@//host:port/service @scripts/deploy/2_api.sql
sql user/password@//host:port/service @scripts/deploy/3_jobs.sql
sql user/password@//host:port/service @scripts/deploy/4_harness_templates.sql
```

### 2. Install Python Dependencies

```bash
pip install oracledb>=4.0.1
```

### 3. Configure

Edit `config.json` — database credentials will be auto-encrypted on first run:

```bash
# Option A: Environment variable (recommended)
export MASTER_DB_KEY=$(python3 -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())")
export MEMORY_DB_USER=<db_user>
export MEMORY_DB_PASSWORD=<db_password>
export MEMORY_DB_DSN=<db_host>:<db_port>/<db_service>

# Option B: Edit config.json (will auto-encrypt on first run)
```

### 4. Run Tests

```bash
cd scripts && python -m tests.test_all
```

### 5. Start Visualization Server

```bash
./start_web_server.sh start    # Start (daemon mode)
./start_web_server.sh status   # Check status
./start_web_server.sh stop     # Stop
# Open http://<web_host>:<web_port> — Login: admin / admin123
```

---

## Project Structure

```
ai-agent-infra-community/
  scripts/
    deploy/
      1_schema.sql              # 27+ tables, JRD views, indexes, property graph, seed data
      2_api.sql                 # 8+ PL/SQL packages
      3_jobs.sql                # 12+ scheduler jobs
      4_harness_templates.sql   # HARNESS_META + 5 built-in templates
    lib/
      config.py                 # Unified Config with encrypted DB credentials
      connection.py             # oracledb connection pool (decrypts config)
      connection_crypto.py      # Config encryption/decryption/key rotation
      memory_api.py             # Memory CRUD (8 functions)
      knowledge_api.py          # Knowledge CRUD + graph (7 functions)
      agent_api.py              # Agent, sessions, credentials (17+ functions)
      task_plan_api.py          # Task plans, steps (6 functions)
      security.py               # Data masking, encryption, ConfigEncryption
      harness_api.py            # Harness template CRUD (6 functions)
      graph_api.py              # Property Graph API (9 functions)
      workspace_api.py          # Workspace lifecycle (14 functions)
      spec_api.py               # Spec CRUD + plan linkage (10 functions)
      collab_api.py             # Collaboration groups (10 functions)
      embedding_api.py          # Vector embedding + search (14 functions)
      search_api.py             # Unified search (3 functions)
      skill_api.py              # Skill CRUD [shared] (Phase 3)
      skill_acquire_api.py   # Agent skill discovery & acquisition [shared] (Phase 3)
      branch_api.py            # Context branching lifecycle (9 functions)
    tests/
      test_all.py               # Master runner
      ... (14+ suites)
    visualization/
      server.py                 # HTTP server v3.4.0
      templates/                # 9+ HTML templates
      static/                   # style.css + vis-network.min.js
  docs/
  config.json                  # Database connection config (auto-encrypted)
  LICENSE           # Apache 2.0
  SKILL.md
  README.md
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE)

Non-production use is free.

## Author

**Haiwen Yin** — [GitHub](https://github.com/Haiwen-Yin) | [Blog](https://blog.csdn.net/yhw1809)