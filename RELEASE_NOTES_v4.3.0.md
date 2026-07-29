# AI Agent Infra with DB v4.3.0

Release date: 2026-07-29

v4.3.0 is the integrated Chuanxu (川序) release. It keeps one shared code
line for the Oracle AI Database 26ai, PostgreSQL 18 with Apache AGE, and
YashanDB 23.5.4 adapters, with Community and Enterprise edition boundaries
enforced during packaging.

## Stable Core

- Added the `production`, `graph-preview`, and `development` runtime profiles.
  `production` is a runtime configuration that exposes the integrated v4.3.0
  surface and the stable core. The v4.3.0 production-profile release gate is
  now PASS; preview controls remain explicitly opt-in and are not represented
  as production-ready capabilities.
- Completed the internal v4.2.1 Graph Engineering closure without publishing a
  separate v4.2.1 archive. Graph definitions, deterministic compilation,
  durable runs, checkpoints, lease fencing, event delivery, executor
  admission, idempotency, bounded retry, evidence, and v4.1 compatibility
  remain in the common implementation.
- Added a unified Human/Agent Principal boundary and database-backed sessions.
  New local passwords use versioned Argon2id. Valid legacy SHA-256 credentials
  are upgraded during the authenticated login flow.
- Added approval-controlled human registration, role templates, operation
  permissions, explicit denies, data scopes, organizations, security domains,
  permission versions, CSRF validation, and effective-access simulation.
- Added one-time user-sponsored Agent Enrollment Tokens. Grants bind sponsor,
  owner, runtime, environment, security domain, risk tier, and policy snapshot;
  token digests are stored instead of raw tokens.
- Added explicit Agent sponsor/owner/operator/viewer relationships, credential
  metadata, pending activation, and short-lived session boundaries.
- Added governed Channels, mixed human/Agent messages, structured Action Cards,
  notifications, Barrier participant snapshots, arrival reports, quorum and
  required-role evaluation, one-winner release, and checkpoint references.
- Added Bridge metadata for explicit cross-domain transfer modes. Channel
  membership is not treated as a confidentiality guarantee; enforcement stays
  at the database, API, Skill, Tool, model, memory, artifact, and export
  boundaries.
- Added the FastAPI/Uvicorn Web entrypoint and the offline Chuanxu application
  shell. Dashboard and Portal share the same Principal and database Session;
  Node.js is a build-time dependency only.
- Corrected Oracle Text deployment ordering. Oracle packages now include an
  explicit SYSDBA prerequisite script for `CTXAPP` and `CTXSYS.CTX_DDL`, and
  Schema deployment verifies the `ENTITIES_MCD` preference and operational
  `ENTITIES_SEARCH_CTX` domain index.

## Database Scope

- Oracle uses native security and Property Graph capabilities where available.
- PostgreSQL uses relational enforcement, RLS-compatible boundaries, and
  Apache AGE for the Graph projection.
- YashanDB uses its supported native security, JSON, and Graph capabilities.
- The integrated migration tail is additive and is applied through the
  migration runner. All non-`stable-4.1` packages share these nine scripts,
  in order:

  ```text
  9_v4_2_0_graph_engineering.sql
  10_v4_2_0_graph_runtime.sql
  11_v4_2_0_graph_control.sql
  12_v4_2_0_graph_edge_scope.sql
  14_v4_2_0_graph_triggers.sql
  15_v4_2_1_executor_registry.sql       # internal v4.2.1 closure
  16_v4_3_0_identity_channels.sql
  17_v4_3_0_governance_lifecycle.sql
  18_v4_3_0_security_lifecycle.sql
  ```

  Enterprise packages additionally apply the one scheduler overlay
  `13_v4_2_0_scheduler_ha.sql` between scripts 12 and 14. The count is
  therefore nine scripts for Community and ten for Enterprise; it excludes
  base schema, v4.1 registration/governance, and adapter security scripts.

## Security and Compatibility

- Business Agents remain forbidden from falling back to Schema Owner access.
- Documented the PostgreSQL DBA prerequisites for Business Agent role
  provisioning: Schema Owner `CREATEROLE` and `ADMIN OPTION` on the shared
  `ai_agent_runtime` role when that role is pre-created.
- Existing v4.1.0 collaboration and registration facades remain available
  while callers migrate to Principal-aware endpoints.
- Enterprise controls remain physically excluded from Community archives.
- Only `RELEASE_NOTES_v4.3.0.md` is included in a v4.3.0 release archive.
- Offline packaging carries two platform builds of pinned
  `cryptography==49.0.0`: a source-built `manylinux_2_28` wheel for this
  server's RHEL 8/glibc 2.28 baseline and the upstream `manylinux_2_34` wheel
  for newer operating systems. `verify_deps.py` selects the compatible wheel
  and rejects a missing or incompatible glibc floor. The reproducible build
  procedure is documented in `docs/cryptography-build.md`.
- The locked Web dependency set uses `fastapi==0.120.4` with
  `starlette==0.49.3`, `mcp==1.28.1`, and `sse-starlette==3.4.5`; this is the
  compatible closure required by the current Web and MCP surfaces.
- `verify_deps.py` also traverses mandatory `Requires-Dist` metadata from the
  selected wheels, evaluates platform markers, and rejects missing or
  incompatible transitive wheels. Optional extras are excluded from the base
  offline installation.
- The dependency gate cross-checks wheel filenames with `METADATA`, enforces
  `Requires-Python`, rejects foreign OS/architecture tags, and validates
  `dist-info/RECORD` hashes and sizes. The build runs this gate by default;
  `--skip-dependency-validate` is diagnostic only.

## Fixed

- Reworked Dashboard navigation as an in-shell SPA transition so changing
  pages no longer replaces the application with a database-connection screen.
  The persistent header now owns the product slogan, language and theme
  controls, logout, and the database-backed five-minute Session countdown.
- Added a global animated request-progress indicator while retaining local
  loading states for data regions, so background and page-level work remain
  visible without blocking navigation.
- Restored the Knowledge, Memory, and Graph Explorer network views, including
  search, type filtering, zoom, node inspection, and contrast-aware labels in
  both themes.
- Restored the operational Agent Monitor inventory and metrics, Skill package
  creation and deletion, Branch lifecycle actions, and Loop creation, run, and
  deletion in the React Dashboard. Legacy Pool Agents are visible to
  administrators through the Monitor inventory and remain read-only at the
  new governed-Principal boundary.
- Corrected administrator visibility so `agents.read.all` is evaluated before
  delegated scope construction, and Barrier queries use unrestricted scope for
  administrators while preserving membership scope for other users.
- Replaced Oracle and YashanDB Barrier `DISTINCT` queries over large JSON/text
  values with membership `EXISTS` predicates, avoiding database errors without
  widening non-administrator access.
- Bound the FastAPI compatibility Session cookie to each edition's configured
  Web port. PostgreSQL and YashanDB Dashboard requests now use the same Session
  cookie as their legacy compatibility handlers.
- Extended frontend regression contracts to validate both source checkouts and
  generated packages containing only compiled `web/dist` assets.
- Added switchable list and Graph views for Knowledge and Memory. Branch
  relationships now appear inside each Branch detail with a deterministic
  Workspace, parent, child, and Agent hierarchy instead of a separate global
  toggle. Graph Explorer definitions, types, runs, and entity relationships
  use focused internal views instead of one continuously stacked page.
- Made the entity relationship view retain both endpoints of returned edges,
  include representative nodes from every persisted entity type, and expose
  complete node-type and relationship-type filters with visible edge counts.
- Restored existing Skill metadata, resource upload/download, and deletion
  controls, and exposed Loop run start, pause, resume, stop, and deletion
  controls before long database inventories.
- Restored the legacy collaboration-group inventory while retaining governed
  Channels as the canonical new collaboration boundary. Added Channel creation
  and unrestricted Channel inventory for `SYSTEM_ADMIN`; private thread access
  remains explicit and is not bypassed by global Channel inventory rights.
- Separated Channel chat from Channel administration. Creation, selection,
  members, threads, lifecycle, legal hold, Action Cards, memory candidates,
  and cross-domain Bridges now share a focused administration view.
- Replaced browser-native Skill file inputs with application-localized file
  controls and completed Chinese labels for visible identity, Agent, Channel,
  Barrier, Graph, Tool, Token, and Bridge terminology.
- Removed the legacy compatibility theme control from the React Dashboard,
  corrected Monitor summary cards to consume the nested Agent, Session, Task,
  and stalled-Agent metrics returned by all three adapters, and made runtime
  experimental profiles discoverable through a dedicated Monitor view with
  impact preflight, governed activation, and controlled-restart guidance.
- Kept performance metrics and the Agent inventory exclusively in the runtime
  overview so the experimental-profile view contains only governed profile
  status and change controls.
- Moved the observable, schedulable, and operable product pillars beside the
  Chuanxu lockup to reduce navigation height, restored the animated React data
  loader under the compatibility stylesheet, and added a Workspace summary
  query mode that returns only list columns and avoids four detail queries per
  listed Workspace.
- Renamed the user-facing Barrier concept to `Collaboration gate` to describe
  multi-Agent arrival, review, decision, and release semantics without
  changing the compatible Barrier API and database identifiers.
- Corrected legacy approval and audit field mappings so pending approval
  actions and context-audit event details render from all three adapters.
- Added approval-write compatibility for early YashanDB deployments whose
  `APPROVAL_REQUESTS` table requires the legacy `APPROVAL_TYPE` column, while
  retaining the unified schema used by new deployments.
- Changed the five-minute Web Session to an inactivity lease. Each successful
  authenticated API operation atomically renews database expiry, refreshes the
  HttpOnly cookie, and updates the visible countdown; idle Sessions still
  expire after five minutes.
- Made adoption of an existing active legacy `ADMIN` idempotently assign the
  highest built-in `SYSTEM_ADMIN` role, including installations where the
  Human Principal was created by an earlier migration.
- Added a visible animated database loader and dismissible detail backdrops;
  clicking outside a detail panel or pressing Escape now closes it.
- Redirected the legacy Dashboard `/login` entry to the Principal-aware `/app`
  shell. Password-only legacy Sessions can no longer enter a login loop.
- Made MFA enforcement an explicit account policy configured in User
  Management instead of inferring it from an administrator role. A confirmed
  factor is required before enforcement can be enabled, and factor enrollment
  promotes the verified current Session without silently changing policy.
  Starting a new enrollment revokes obsolete unconfirmed TOTP factors.
- Preserved incremental Portal chat delivery through the FastAPI compatibility
  bridge. SSE response chunks are forwarded with bounded backpressure, LLM
  event lines are consumed as they arrive, and disconnected clients release
  their streaming worker context.
- Removed unused Principal bind values from unrestricted user-visibility
  queries. Oracle and YashanDB user administration no longer rejects an `ALL`
  scope query when its simplified SQL contains no Principal placeholder.
- PostgreSQL Graph traversal now compares `ENTITY_EDGES` endpoint IDs in a
  shared text domain. Existing numeric IDs remain searchable, while legacy
  non-numeric endpoints such as `PG_AGENT_001` no longer trigger a `BIGINT`
  cast error; unmatched historical endpoints are ignored by the relational
  join.
- Package test guidance now distinguishes the adapter runtime's `config.json`
  from shared pytest fixture overrides. A real generated-package suite must
  use a local owner-only (`0600`) `config.json` (or a temporary package copy
  containing one), so it cannot silently fall back to localhost defaults.

## Validation Database Lifecycle

- Release validation uses explicitly named temporary databases or PDBs and a
  separately declared baseline inventory.
- Temporary test objects are removed and database inventories are checked
  before the next version upgrade. An unproven cleanup blocks the upgrade.
- Baseline databases are protected; ambiguous names must be resolved before
  destructive cleanup. Test-only roles, scheduler jobs, sessions, and data
  files are cleaned where the target database supports it.

The canonical v4.3.0 service contract is the authenticated Principal-aware
FastAPI, REST, MCP, and Skill surface documented in `docs/api-reference.md`.
The existing v4.1 route and Python facades remain available as compatibility
entry points while callers migrate; they do not authorize direct database
access or replace the canonical identity and policy checks.

## Release Maturity

The current v4.3.0 release evidence manifest is `release_status: PASS` and
`passed: true`; its associated closure manifest reports `releasable: true`.
The six-edition clean deployment and 18-mode matrix pass, the three database
contracts pass, the six-edition failure-recovery matrix passes 54 checks, and
the capacity observation passes all three databases at 5,000/10,000/50,000/
100,000 records and 10/50/100/500 logical Workers. The v4.3.0 token benchmark
is current evidence: SQLite FTS5 Top-3 retrieval measured 96.75% fewer
cl100k_base prompt-input tokens for the recorded corpus. It is an efficiency
observation, not a latency or answer-quality claim. Production deployment now
uses the v4.3.0 `production` profile; `graph-preview` and other experimental
capabilities remain explicitly gated.

## Positioning

The production message remains: make Agent operation observable, controllable,
and traceable. Chuanxu is the product brand; `AI Agent Infra with DB` remains
the technical project name.
