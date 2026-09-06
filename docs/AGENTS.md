# AGENTS.md - AI Agent Infra with DB v4.4.12 Unified Repository Guide

> **v4.4.12** - The unified single-source repository that generates all 6 release
> editions (Oracle/PG/YashanDB × Community/Enterprise) via `build.py`.

> This is the technical guide for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## 1. Repository Layout

## Fresh Baseline And Current Product Boundaries

Use the generated package's sole `scripts/deploy/baseline_v*.json` as the
deployment contract, not the historical source template filename. The build
must align its version, adapter and terminal migration with the package:
v4.4.10 ends at 65; v4.4.11 ends at 68; v4.4.12 ends at 78.
Oracle/YashanDB include context-read migration 69; PG goes from 68 to 70.
Historical scripts remain for
journal/checksum reproducibility, not as a customer upgrade promise.
v4.4.8 is withdrawn. v4.4.12 includes entity isolation, organization knowledge
policies and native credential write restrictions through migration 78.
Release acceptance is determined by the current package-bound evidence;
the migration terminal alone does not establish production readiness.

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
LLM. Business Agents are requested by an authorized human, follow the edition's
governance flow (separate approval in Enterprise, authorized direct execution
in Community), are deployed through a selected target, and remain pending
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
│   ├── config.yaml          # local spec-driven workflow
│   ├── specs/               # accepted requirements
│   └── changes/             # proposals, designs, tasks and spec deltas
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
4. Generates `config.example.json`, `requirements.txt`, `LICENSE*`, and `NOTICE`.
   Runtime secrets belong to the operator's private configuration, not the package.
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
- Generated package and deployment manifests (never used to derive secrets)
- All injected docstrings/markdown headers via `inject_version()`

To cut a new release:

```bash
# Update VERSION only after the current release gates are satisfied.
source shared/scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
"$PYTHON_BIN" build.py --profile production  # builds and gates all six editions
"$PYTHON_BIN" spec_validator.py --build-output "build_output/v$(tr -d '[:space:]' < VERSION)" --release
```

## Integrated Profiles

The default build version comes from `VERSION`; explicit development builds
may use `--version` without declaring a release. The final package date and
approval must refer to the actual validated artifacts. Historical release
evidence does not prove the current version is ready. The v4.2.1 milestone
remains internal history, not a separately published release.

`production` contains the integrated stable-core release surface and is the
recommended runtime profile for production. Current capability availability is
defined by the database-authoritative Graph capability matrix, not by profile
labels: Graph Runtime core and authorized inspection are Production; manifest
draft import, read-only SLO views, and checkpoint fork are `CONTROLLED`; replay,
Dynamic Graph migration, framework-adapter execution, A2A, and OTLP are
`DISABLED`. No capability label changes database, API, Skill, Tool, model, or
export authorization boundaries.
Inspect the current database capability matrix before exposing a controlled
operation. DB4A2A is a database-mediated dispatch mechanism, not proof of
standard A2A interoperability.

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

The authoritative specs live inside this repository:

```
/root/ai-agent-infra/openspec/specs/
├── api-contract/spec.md            # REST endpoints every edition must serve
├── database-adaptation/spec.md     # connection.py public API + per-DB schema
├── documentation-format/spec.md    # CHANGELOG/RELEASE_NOTES/SKILL.md rules
└── test-requirements/spec.md       # minimum test counts + per-DB quirks
```

Put proposals and deltas in `openspec/changes/`, and validate them with
`openspec validate <change> --strict`. Accepted requirements are in
`openspec/specs/`. Do not edit a historical external clone and assume this
repository or its builds have been updated. Use `spec_validator.py` to check
the generated artifacts as well.

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

The adapter runtime reads `CX_CONFIG_PATH` when provided, otherwise the
package configuration. Test-fixture overrides alone do not replace runtime
configuration. Use a temporary owner-only (`0600`) config, run from the
generated package directory, and set its `scripts` on PYTHONPATH. Never commit
that config or include it in a release archive. Source/offline skips are not
live database test passes.

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
- **Spec changes go in this repository** (`openspec/changes` and `openspec/specs`),
  then re-run `spec_validator.py`.
- **Community vs Enterprise divergence** is driven by `extra_features` in the
  edition JSON and the `inject_version()` edition-label rewrite of
  `agent_api.py`.

### Temporary Test Database Rule

Every release validation database or PDB must be explicitly classified as
`baseline` or `temporary` before it is used. Clean-install, migration, mode,
browser, recovery, and capacity tests use temporary objects only. Their names
and sanitized lifecycle evidence are recorded outside the release archive.

Before cleanup, obtain operator authorization and resolve exact targets.
Stop their validation services, retire only confirmed obsolete test objects,
and re-query inventories. Preserve baseline/system databases and explicitly
protected TEST PDBs; ambiguous names remain untouched pending clarification.
Current-version test databases may remain for ongoing validation. Do not
drop cluster-wide roles merely because one database was retired.

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
- In-process legacy handlers bind the actual request port with a ContextVar
  and reset it in `finally`. Never fix a request by changing process-wide
  `MEMORY_SERVER_PORT`; direct Uvicorn and proxy ports may differ from config.
- Use the implemented `dashboard_session_id_{request_port}` and
  `portal_session_id_{request_port}` names; request ports may differ from defaults.
- Cookie MUST include `SameSite=Lax` attribute
- Session expiry must follow the server-issued lease and leave without a
  manual logout confirmation; dashboard and portal sessions remain distinct.

### Template Version Injection
- build.py MUST handle `v3.10.2<` and `v3.10.2"` patterns (no trailing space)
- HTML placeholders: `{{EDITION_LABEL}}`, `{{DB_DISPLAY}}`, `4.4.12`
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
- Provider-specific reasoning parameters must be supported by that provider;
  do not inject an arbitrary value into every model request.
- Streaming: only yield `content` tokens, skip `reasoning_content`
- Non-streaming: fall back to `reasoning_content` if `content` empty

### PG Schema Differences
- Parent RLS does not protect direct leaf-partition queries. Entity partitions
  must not receive direct business-role grants, including during registration
  after historical GRANT ON ALL TABLES. Test parent and partition paths with
  actual independent logins; preserve migration 53's SESSION_USER binding.
- `skill_meta`: PG has `skill_id`/`status`, Oracle has `entity_id`/`skill_status`
- `compliance_log`: PG has `severity` (INFO/WARNING/ERROR/CRITICAL), `policy_violation` (boolean)
- `context_audit_log`: MUST be created manually in PG (not in 1_schema.sql)
- `workspace_context.context_id`: PG is BIGINT IDENTITY, Oracle/YashanDB is VARCHAR

### YashanDB Limitations
- Migration 70 replaces raw entity/metadata/embedding/edge access with
  SESSION_USER-bound views and a minimal private-write package. Legacy definer
  packages are not business-Agent APIs. See the adapter's native-data-security
  document; never fall back to Owner or broaden SHARED to bypass denied SQL.
- No `GRAPH_ALGORITHMS` PL/SQL package (implement in Python)
- The adapter owns its connection lifecycle; inspect `connection.py` rather
  than assuming native pooling semantics from its facade name.
- Normalize native VECTOR values at the adapter boundary and test the actual
  driver version. Do not treat historical driver failures as a universal limit.
- Service restart policy does not substitute for transaction recovery,
  database readiness or driver fault investigation.
