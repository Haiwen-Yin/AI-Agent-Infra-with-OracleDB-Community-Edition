# AGENTS.md - AI Agent Infra with DB v4.1.0 Unified Repository Guide

> **v4.1.0** - The unified single-source repository that generates all 6 release
> editions (Oracle/PG/YashanDB × Community/Enterprise) via `build.py`.

> This is the technical guide for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## 1. Repository Layout

```
/root/ai-agent-infra/
├── VERSION                  # SINGLE source of truth for the version string
├── build.py                 # generates build_output/<edition>/ + .zip
├── spec_validator.py        # validates build output against openspec specs
├── CHANGELOG.md             # project-wide changelog (English, reverse chrono)
├── openspec/
│   └── config.yaml          # store pointer to AI-Agent-Infra-Specs
├── editions/                # 6 per-edition JSON configs (one per release)
│   ├── oracle-community.json
│   ├── oracle-enterprise.json
│   ├── pg-community.json
│   ├── pg-enterprise.json
│   ├── yashandb-community.json
│   └── yashandb-enterprise.json
├── shared/                  # code COMMON to every edition (copied as-is)
│   ├── agent_bootstrap.py
│   ├── verify_deps.py
│   ├── install_offline.sh
│   ├── requirements.txt
│   ├── docs/                # markdown shipped with every edition
│   ├── lib/                 # DB-agnostic business modules (loop_api, etc.)
│   ├── tests/               # shared test suite (incl. conftest.py)
│   ├── tools/               # encrypt_config.py
│   ├── data/                # seed data
│   └── visualization/       # web server (server.py + templates + static)
├── adapters/                # DB-SPECIFIC overrides, layered ON TOP of shared/
│   ├── oracle/              # connection.py, config_db.py, agent_api.py, deploy/, deploy_oracle.py
│   ├── pg/                  # connection.py, config_db.py, agent_api.py, deploy/
│   └── yashandb/            # connection.py, config_db.py, agent_api.py, deploy_yaspy.sh, vendor/, deploy_yashandb.py
└── build_output/            # generated; one subdir + one .zip per edition
```

### What gets copied where

For each edition, `build.py`:

1. Copies `shared/` verbatim into `build_output/<edition>/`.
2. Restructures loose `*.py`/`*.sh` and `lib/`, `tests/`, `tools/`, `visualization/`
   under `build_output/<edition>/scripts/`.
3. Overlays the matching `adapters/<db>/` files on top:
   - `adapters/<db>/connection.py`  → `scripts/lib/connection.py`
   - `adapters/<db>/config_db.py`   → `scripts/lib/config.py`
   - `adapters/<db>/agent_api.py`   → `scripts/lib/agent_api.py`
   - `adapters/<db>/deploy/`        → `scripts/deploy/`
   - `adapters/<db>/deploy_<db>.py` → `scripts/deploy_<db>.py`
4. Generates `config.json`, `requirements.txt`, `LICENSE*`, and `NOTICE`.
5. Injects the version string into every `.py`, `.sql`, `.md`, `.html`, `.sh`.
6. Zips the directory to `build_output/<edition>-v<VERSION>.zip`.

## 2. The 6 Editions

| Edition key            | Output directory                                         | DB Driver    | Web Port | License     | Edition JSON                        |
|------------------------|----------------------------------------------------------|--------------|----------|-------------|-------------------------------------|
| `oracle-com`           | `AI-Agent-Infra-with-OracleDB-Community-Edition`         | oracledb     | 8001     | Apache-2.0  | `editions/oracle-community.json`    |
| `oracle-ent`           | `AI-Agent-Infra-with-OracleDB-Enterprise-Edition`        | oracledb     | 8000     | BSL-1.1     | `editions/oracle-enterprise.json`   |
| `pg-com`               | `AI-Agent-Infra-with-PG-Community-Edition`               | psycopg2     | 18080    | Apache-2.0  | `editions/pg-community.json`        |
| `pg-ent`               | `AI-Agent-Infra-with-PG-Enterprise-Edition`              | psycopg2     | 18090    | BSL-1.1     | `editions/pg-enterprise.json`       |
| `yashandb-com`         | `AI-Agent-Infra-with-YashanDB-Community-Edition`         | yaspy        | 8002     | Apache-2.0  | `editions/yashandb-community.json`  |
| `yashandb-ent`         | `AI-Agent-Infra-with-YashanDB-Enterprise-Edition`        | yaspy        | 8003     | BSL-1.1     | `editions/yashandb-enterprise.json` |

Each edition JSON declares: `edition` (Community/Enterprise), `license`,
`license_file`, `web_port`, `db` connection block, and `extra_features`
(which triggers Enterprise modules: approvals, audit, ldap, skill_token,
orchestrator).

## 3. Version Management

**`VERSION` is the single source of truth.** Read by:

- `build.py` (`--version` flag falls back to `VERSION`)
- `spec_validator.py` (parsed and reported)
- Generated `config.json` → `security.secret_key`
- All injected docstrings/markdown headers via `inject_version()`

To cut a new release:

```bash
echo "4.1.0" > VERSION
python3.14 build.py            # rebuilds all 6 editions at v4.1.0
python3.14 spec_validator.py   # confirm all still pass
```

Never hardcode version numbers in source — `build.py` rewrites them.

## 4. Build System

### Build all editions

```bash
python3.14 build.py [--version X.Y.Z] [--edition <key>] [--skip-zip]
```

- Without flags: rebuilds every edition listed in `build.py:EDITIONS`.
- `--edition oracle-ent`: build only that edition.
- `--skip-zip`: skip the zip step (faster iteration).
- Output: `build_output/AI-Agent-Infra-with-<DB>-<Tier>-Edition/` and a sibling
  `.zip` per edition.

### Validate the build

```bash
python3.14 spec_validator.py                          # all editions, static
python3.14 spec_validator.py --edition oracle-ent     # one edition
python3.14 spec_validator.py --live --base-url http://127.0.0.1:8000
python3.14 spec_validator.py --json                   # machine-readable
```

The validator checks three things per edition (per the OpenSpec specs):

1. **Required files exist** — `connection.py`, `config.py`, `agent_api.py`,
   `server.py`, deploy SQL (`1_schema.sql`, `2_api.sql`, `3_jobs.sql`,
   `4_harness_templates.sql`), `verify_deps.py`, `install_offline.sh`,
   `start_web_server.sh`, `LICENSE*`.
2. **Test count meets minimum** — parses `def test_*` under
   `scripts/tests/` and compares to the table in
   `test-requirements/spec.md` (Oracle 121, PG 103, YashanDB COM 109 / ENT 113).
3. **API endpoints exist** — every route in `api-contract/spec.md` must appear
   in the bundled Python source (Community + Enterprise routes).

Exit code is non-zero on any failure, so it can gate CI.

## 5. OpenSpec Store

The shared specs live in a separate store, not inside this repo:

```
/root/AI-Agent-Infra-Specs/openspec/specs/
├── api-contract/spec.md            # REST endpoints every edition must serve
├── database-adaptation/spec.md     # connection.py public API + per-DB schema
├── documentation-format/spec.md    # CHANGELOG/RELEASE_NOTES/SKILL.md rules
└── test-requirements/spec.md       # minimum test counts + per-DB quirks
```

`openspec/config.yaml` in this repo points at that store (`store: ai-agent-infra`).
Proposals that affect all 6 editions must be made there; the build then has to
satisfy them. Use `spec_validator.py` as the bridge between the specs and the
built artifacts.

## 6. Test Infrastructure

### Shared pytest suite

`shared/tests/` ships every edition's test modules plus a parameterized
`conftest.py`:

| Fixture         | Scope   | Behavior                                                       |
|-----------------|---------|----------------------------------------------------------------|
| `db_type`       | function | Parameterized over `["oracle", "pg", "yashandb"]`.            |
| `db_connection` | function | Yields a live DB-API connection for the current `db_type`.    |
|                 |         | Auto-skips the test if the backend is unreachable.            |

Env overrides:

- `AIAGENT_TEST_DB=pg` — restrict parameterization to one backend.
- `AIAGENT_SKIP_DB=oracle,yashandb` — skip specific backends.
- `AIAGENT_ORACLE_DSN`, `AIAGENT_PG_HOST/PORT/DBNAME`,
  `AIAGENT_YASHANDB_DSN`, plus matching `_USER`/`_PASSWORD` vars.

Example:

```bash
AIAGENT_TEST_DB=oracle python3.14 -m pytest scripts/tests/ -q
```

### Running the full suite post-build

```bash
cd build_output/AI-Agent-Infra-with-OracleDB-Enterprise-Edition
python3.14 -m pytest scripts/tests/ -q --tb=no
```

The release bar is defined in `test-requirements/spec.md`: zero failures and
the test count must meet or exceed the edition's minimum.

## 7. Edition Config Reference

The 6 JSONs in `editions/` are the **only** per-edition inputs to `build.py`.
Changing a port, license, feature flag, or DB connection means editing one
file and rebuilding. Example (`editions/oracle-enterprise.json`):

```json
{
    "edition": "Enterprise",
    "license": "BSL-1.1",
    "license_file": "LICENSE_ENTERPRISE",
    "web_port": 8000,
    "db": {
        "user": "aiadmin", "password": "<DB_PASSWORD>",
        "dsn": "<DB_HOST>:1521/ai_agent_ee",
        "pool_min": 2, "pool_max": 5
    },
    "extra_features": ["approvals", "audit", "ldap", "skill_token", "orchestrator"]
}
```

`extra_features` controls which Enterprise-only modules are wired in.

## 8. Common Workflows

| Task                                        | Command                                                         |
|---------------------------------------------|-----------------------------------------------------------------|
| Cut a release (all editions)                | `python3.14 build.py`                                           |
| Iterate on one edition (no zip)             | `python3.14 build.py --edition oracle-ent --skip-zip`           |
| Validate against specs                      | `python3.14 spec_validator.py`                                  |
| Probe a running server                      | `python3.14 spec_validator.py --live --base-url http://host:8000` |
| Run generated Oracle package tests           | `cd build_output/AI-Agent-Infra-with-OracleDB-Enterprise-Edition && AIAGENT_TEST_DB=oracle python3.14 -m pytest scripts/tests/` |
| Inspect what changed in a build             | `diff -r build_output/<edition> <previous>`                     |

## 9. Rules of Engagement

- **Never edit `build_output/` directly** — it is regenerated. Edit `shared/`
  or `adapters/` and rebuild.
- **Never hardcode versions** — `build.py:inject_version()` rewrites them
  from `VERSION`.
- **Database-specific changes go in `adapters/<db>/`**, never in `shared/`.
- **Spec changes go in the store** (`/root/AI-Agent-Infra-Specs/openspec`),
  then re-run `spec_validator.py`.
- **Community vs Enterprise divergence** is driven by `extra_features` in the
  edition JSON and the `inject_version()` edition-label rewrite of
  `agent_api.py`.

## v4.0.0 Lessons Learned (CRITICAL - Read Before Any Code Change)

### SQL Compatibility Rules (shared/ code)
1. **No `FROM DUAL`** -> Use bare `SELECT 1` or `SELECT count(*) FROM table`
2. **No `SYSTIMESTAMP`** -> Use `CURRENT_TIMESTAMP` (works in all 3 DBs)
3. **No `SYS_GUID()` / `RAWTOHEX()`** -> Use Python `uuid.uuid4().hex`
4. **No `ROWNUM`** -> Remove (execute_query_one returns first row)
5. **No `FETCH FIRST`** -> Same as above
6. **No `NVL()`** -> Use `COALESCE()`
7. **`RETURNING col INTO :ret_id`** -> Keep in SQL. Oracle/YashanDB use it natively. PG adapter strips it.
8. **Named binds `:param`** -> Use in SQL. PG `_convert_params` converts to `%s`.

### JavaScript Type Safety
- PG returns BIGINT as `int`, Oracle/YashanDB return VARCHAR as `str`
- All `.substring()` calls MUST wrap with `String()`: `String(id).substring(0, 8)`
- All `typeof` checks MUST handle both: `typeof id === 'string' || typeof id === 'number'`

### Session Cookie Isolation
- Each server MUST use `session_id_{port}` as cookie name
- Cookie MUST include `SameSite=Lax` attribute
- Auto-logout JS timer (`_aloSec`) MUST equal `config.server.session_timeout` (300 seconds by default)

### Template Version Injection
- build.py MUST handle `v3.10.2<` and `v3.10.2"` patterns (no trailing space)
- HTML placeholders: `{{EDITION_LABEL}}`, `{{DB_DISPLAY}}`, `4.1.0`
- Login badge: `{DB} {Edition} Edition v{VERSION}` (Admin), `{DB} {Edition} v{VERSION}` (Portal)

### LLM Configuration
- Empty `api_key` SHALL NOT block LLM calls
- Add `reasoning_effort: "none"` for reasoning models
- Streaming: only yield `content` tokens, skip `reasoning_content`
- Non-streaming: fall back to `reasoning_content` if `content` empty

### PG Schema Differences
- `skill_meta`: PG has `skill_id`/`status`, Oracle has `entity_id`/`skill_status`
- `compliance_log`: PG has `severity` (INFO/WARNING/ERROR/CRITICAL), `policy_violation` (boolean)
- `context_audit_log`: MUST be created manually in PG (not in 1_schema.sql)
- `workspace_context.context_id`: PG is BIGINT IDENTITY, Oracle/YashanDB is VARCHAR

### YashanDB Limitations
- No `GRAPH_ALGORITHMS` PL/SQL package (implement in Python)
- `yaspy` driver: no connection pooling, fresh connection per query
- VECTOR type: returns `array.array`, convert to string immediately (GC segfault)
- Use systemd `Restart=always` due to yaspy instability
