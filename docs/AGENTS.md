# AGENTS.md - AI Agent Infra with DB v4.4.11 Unified Repository Guide

> **v4.4.11** - The unified single-source repository that generates all 6 release
> editions (Oracle/PG/YashanDB × Community/Enterprise) via `build.py`.

> This is the technical guide for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## 1. Repository Layout

## v4.4.10 Fresh Baseline And Current Product Boundaries

v4.4.10 is the current fresh-deployment baseline. Use each adapter's
`deploy/baseline_v4_4_10.json` ordered chain through migration 65; earlier
numbered scripts remain for journal/checksum reproducibility, not as a customer
upgrade promise. v4.4.8 is withdrawn.

The model gateway is optional. Direct and gateway routes can coexist per LLM
Provider Profile. The gateway provides bounded streaming/non-streaming
forwarding, atomic hard/warn quotas, encrypted non-streaming replay, immutable
usage/pricing facts, Provider invoice reconciliation, Enterprise allocation,
signed external evidence, and a versioned authenticated read-only wallboard.
Never claim visibility for unobserved direct traffic or retain model payloads in
the usage ledger.

Knowledge is company-public, organization-subtree, organization-level, or
Human/Agent-private. Database policy and current organization closure govern
inventory, item, graph, and retrieval reads. Security Domains and Channels are
the product-facing collaboration model. The standalone Collaboration page and
new collaboration-group workflow are removed in v4.4.10. Legacy collaboration
groups remain only as internal execution compatibility records and never grant
authorization or knowledge scope.

## v4.4.3 Governed Security Domains

The durable product collaboration order is **Security Domain -> Channel**.
`CX_SECURITY_DOMAINS` and `CX_DOMAIN_MEMBERS` are the only authorization
records. `CX_DOMAIN_GOVERNANCE` adds accountable ownership,
purpose, classification, and reason, while `CX_DOMAIN_BINDINGS` records
traceable Channel and internal execution relationships without granting access.

When adapting an existing collaboration group, create a conversion draft. Its
active Agents remain pending candidates and its `SHARING_POLICY` is review
context only. An authorized operator must confirm each candidate, verify the
accountable Human owner, and apply the draft before the transaction creates
the Domain, confirmed memberships, and one active group binding. Do not infer
authorization from old group membership, messages, workspace sharing, Skills,
or prompts. `DEFAULT` is for bootstrap or constrained PoC use and must not be
selected implicitly for a production project.

## v4.3.6 Native Agent Lifecycle

Initialization creates `SYSTEM_PLATFORM_ADMIN_AGENT` in every edition and
`SYSTEM_COMPLIANCE_ADMIN_AGENT` only in Enterprise. These are separate Agent
Principals and never reuse the human `admin` session or a Schema Owner
credential. Bootstrap is idempotent and does not call an external Agent or
LLM. Business Agents are requested by an authorized human, approved by a
different Principal, deployed through a selected target, and remain pending
until an approved LLM profile and runtime health are available.

External Agents remain Skill-first: `SKILL.md` enrollment, Gateway
authentication, authorization, revocation, and audit are unchanged. The
database policy `external_agent_registration` controls only new external
registrations. A shared Worker Pool may share scheduling capacity only; every
execution receives separate context, workspace, database session, token,
secret references, and model conversation state.

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
echo "4.3.5" > VERSION
source shared/scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
"$PYTHON_BIN" build.py --profile production  # builds and gates all six editions
"$PYTHON_BIN" spec_validator.py --build-output "build_output/v$(tr -d '[:space:]' < VERSION)" --release
```

## v4.3.0 Integrated Profiles

The working source targets the version in `VERSION`; the final package date is assigned only
when the final archives are built. The prior published baseline is `v4.3.4`
dated `2026-08-04`.
Graph Engineering work from the internal v4.2.1 closure is integrated into this
release and is not published as a separate v4.2.1 archive. The stable v4.1.x
line remains available as a downloadable compatibility baseline and receives
only critical security or data-loss fixes. The complete v4.3.0 production
replacement evidence gate has passed.

`production` contains the integrated stable-core release surface and is the
recommended runtime profile for production. Current capability availability is
defined by the database-authoritative Graph capability matrix, not by profile
labels: Graph Runtime core and authorized inspection are Production; manifest
draft import, read-only SLO views, and checkpoint fork are `CONTROLLED`; replay,
Dynamic Graph migration, framework-adapter execution, A2A, and OTLP are
`DISABLED`. No capability label changes database, API, Skill, Tool, model, or
export authorization boundaries.
The v4.3.0 release evidence manifest reports `PASS` and `passed: true`; its
associated closure manifest reports `releasable: true`. v4.1.x remains
downloadable as the previous baseline, not the current production
recommendation.

The non-`stable-4.1` migration tail contains nine common scripts:
`9_v4_2_0_graph_engineering.sql`, `10_v4_2_0_graph_runtime.sql`,
`11_v4_2_0_graph_control.sql`, `12_v4_2_0_graph_edge_scope.sql`,
`14_v4_2_0_graph_triggers.sql`, `15_v4_2_1_executor_registry.sql`,
`16_v4_3_0_identity_channels.sql`, and
`17_v4_3_0_governance_lifecycle.sql`, and
`18_v4_3_0_security_lifecycle.sql`. Enterprise adds
`13_v4_2_0_scheduler_ha.sql` between 12 and 14, for ten scripts in that
package. These counts exclude base, registration, and security scripts.
The source tree remains one line, so the v4.2 internal milestone does not
create a second long-lived codebase.

Never hardcode version numbers in source — `build.py` rewrites them.

## 4. Build System

### Build all editions

```bash
"$PYTHON_BIN" build.py [--version X.Y.Z] [--edition <key>] [--skip-zip]
```

- Without flags: rebuilds every edition listed in `build.py:EDITIONS`.
- `--edition oracle-ent`: build only that edition.
- `--skip-zip`: skip the zip step (faster iteration).
- Output: `build_output/AI-Agent-Infra-with-<DB>-<Tier>-Edition/` and a sibling
  `.zip` per edition.

### Validate the build

```bash
"$PYTHON_BIN" spec_validator.py                          # all editions, static
"$PYTHON_BIN" spec_validator.py --edition oracle-ent     # one edition
"$PYTHON_BIN" spec_validator.py --live --base-url http://127.0.0.1:8000
"$PYTHON_BIN" spec_validator.py --json                   # machine-readable
```

The dependency wheelhouse carries one current platform wheel per pinned
package. `cryptography==49.0.0` uses the upstream `manylinux_2_34` wheel.
Release validation requires RHEL 9.8+ (Oracle Linux 9.8+) or an equivalent glibc 2.34+ host; the
retired RHEL 8 wheel must not be restored. Run `scripts/verify_deps.py` before
packaging.

Linux control-plane compatibility and verified local-Agent isolation are
separate release claims. Use `docs/linux-platform-compatibility.md` and require
the packaged host gate before marking an exact distribution image as suitable
for strong same-host isolation. A vendor family name or newer version number is
not evidence.
The build runs this gate by default and also verifies wheel METADATA,
Requires-Python, platform tags, and RECORD hashes. Use
`--skip-dependency-validate` only for a diagnostic build with an intentionally
incomplete wheelhouse; that output is not releasable.

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
AIAGENT_TEST_DB=oracle "$PYTHON_BIN" -m pytest scripts/tests/ -q
```

The adapter runtime reads its database connection from `config.json` in the
generated package root. `AIAGENT_*_CONFIG` only feeds the shared pytest
fixture and does not replace that runtime file. For a real package run, first
complete the config wizard or place a temporary owner-only (`0600`) config in
the package root; never commit that file or include it in a release archive.

### Running the full suite post-build

```bash
cd build_output/AI-Agent-Infra-with-OracleDB-Enterprise-Edition
PYTHONPATH="$PWD/scripts" "$PYTHON_BIN" -m pytest scripts/tests/ -q --tb=no
```

The package root is a release-test isolation boundary. Do not launch this
command from the unified repository root with a package test path: Python can
then import `shared.lib` from the source checkout and combine it with the
generated package's edition metadata. Treat any such mixed-module result as
invalid evidence and rerun it from the generated package root.

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
        "user": "<DB_USER>", "password": "<DB_PASSWORD>",
        "dsn": "<DB_HOST>:1521/<DB_SERVICE>",
        "pool_min": 2, "pool_max": 5
    },
    "extra_features": ["approvals", "audit", "ldap", "skill_token", "orchestrator"]
}
```

For PostgreSQL, `pool_min` and `pool_max` are the supported configuration
names as well. The adapter accepts them from existing encrypted configurations
and bounds short request bursts by the configured maximum; sustained overload
must be handled by an operator capacity decision.

`extra_features` controls which Enterprise-only modules are wired in.

## 8. Common Workflows

| Task                                        | Command                                                         |
|---------------------------------------------|-----------------------------------------------------------------|
| Cut a release (all editions)                | `$PYTHON_BIN build.py`                                           |
| Iterate on one edition (no zip)             | `$PYTHON_BIN build.py --edition oracle-ent --skip-zip`           |
| Validate against specs                      | `$PYTHON_BIN spec_validator.py`                                  |
| Probe a running server                      | `$PYTHON_BIN spec_validator.py --live --base-url http://host:8000` |
| Run generated Oracle package tests           | `cd build_output/AI-Agent-Infra-with-OracleDB-Enterprise-Edition && AIAGENT_TEST_DB=oracle "$PYTHON_BIN" -m pytest scripts/tests/` |
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

### Temporary Test Database Rule

Every release validation database or PDB must be explicitly classified as
`baseline` or `temporary` before it is used. Clean-install, migration, mode,
browser, recovery, and capacity tests use temporary objects only. Their names
and sanitized lifecycle evidence are recorded outside the release archive.

Before the next version upgrade, stop validation services, remove all
temporary PostgreSQL databases and Oracle/YashanDB PDBs, clean associated
test-only roles/jobs where applicable, and re-query all inventories. A zero
temporary-object result is a release prerequisite. If an object cannot be
classified confidently, the upgrade is blocked; do not guess and do not drop
the protected baseline database.

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
- HTML placeholders: `{{EDITION_LABEL}}`, `{{DB_DISPLAY}}`, `4.4.11`
- Login badge: `{DB} {Edition} Edition v{VERSION}` (Admin), `{DB} {Edition} v{VERSION}` (Portal)

### LLM Configuration
- Empty `api_key` SHALL NOT block LLM calls
- A saved profile is `HEALTHY` only when a bounded probe returns a completion
  from the configured model. A reachable endpoint serving another model is
  `DEGRADED`; provider namespaces may prefix an otherwise matching model ID.
  A stable alias may resolve to the same basename plus a bounded numeric or
  ISO-date version suffix (`deepseek-v4-flash` to
  `deepseek-v4-flash-0731`), but arbitrary suffixes remain a mismatch.
- Retiring an LLM profile is blocked while it remains referenced by Portal,
  an active native Agent, or a pending Business Agent request.
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
