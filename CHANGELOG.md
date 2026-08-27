# Changelog

## v4.4.10 - 2026-08-27

- Validates all three Enterprise editions from dedicated zero-object targets:
  Oracle and YashanDB PDBs plus a PostgreSQL database reach migration 65,
  native management-Agent bootstrap, scoped Knowledge, and `verify`.
- Adds bounded PostgreSQL AGE and Agent-role prerequisites and closes trusted
  actual-owner policies on forced-RLS tables without granting SUPERUSER.

- Completes the real external-Agent full-capability gate on Oracle,
  PostgreSQL, and YashanDB Enterprise, including Memory Candidate submission,
  Human promotion, Agent-private Knowledge write/read, and company-wide
  publication denial. The redacted combined result contains no reusable
  credential.
- Adds `memory.propose`, `knowledge.read`, and `knowledge.write` Gateway scopes
  and routes. Agent knowledge is owned by the producing Agent, defaults to
  private visibility, and resolves organization scope from the authoritative
  owner hierarchy.
- Adds migration 65 to close external-Agent Security Domain context, including
  forced PostgreSQL Agent-self RLS. Also fixes SSE native timestamp encoding,
  reusable-thread Agent-context cleanup, Oracle bind naming, Oracle/YashanDB
  native timestamp binds, and service-name preservation in external endpoint
  discovery.

- Added direct Oracle `CREATE TRIGGER` to the consolidated owner prerequisite
  and blocking preflight contract, preventing migration 22 from failing after
  partial schema creation with `ORA-01031`.

- Closes organization application governance end to end: submission creates a
  unique unified approval item; self-decision is denied; approval atomically
  publishes facts, closure, typed history, subtree authority invalidation and
  audit; rejection atomically terminates both records. Migration 60 carries the
  portable database contract.
- Makes unified STEP approval apply its paused-plan effect in the same
  transaction and makes confirmed platform Action Cards recoverable after an
  interrupted command handoff.
- Blocks Oracle initialization unless the active Oracle Home proves that
  Partitioning is enabled. The Oracle fresh baseline no longer compiles against
  a not-yet-created table, calls an unavailable configuration function, or
  creates a duplicate index; foundational execution stops at the first genuine
  SQL failure instead of continuing into dependent ORA errors.
- Keeps Oracle/YashanDB anonymous blocks with local functions or procedures
  intact through their slash terminator so lifecycle migrations cannot be
  truncated at an inner `END;`.
- Passes a real Oracle Enterprise empty-schema initialization through terminal
  migration 59, native Agent postflight, `RETIRED`, and `verify`; first-line
  local procedure declarations are no longer split from their outer block.
- Removes pre-grant `DBMS_CRYPTO` dependency from Oracle Memory adoption,
  removes active-migration `AIADMIN` hard-coding, validates the complete Deep
  Data Security owner privilege set, and creates the administrative Data Role
  idempotently.
- Uses exact Oracle bind sets for isolation-inventory and deployment-state
  writes while preserving both derived shape and inheritance semantics.
- Removes the client-side backup-manifest requirement from verified empty-target
  initialization. The bootstrap records a database-managed, no-pre-existing-data
  recovery boundary. Existing-target upgrades explain the database-managed
  recovery boundary and require interactive `UPGRADE` confirmation, or
  `--confirm-database-backup` for automation; the journal explicitly records
  that backup state is not client-verifiable.
- Adds explicit listen-address and Web-port prompts to the first-run wizard,
  validates the port range, persists the resolved binding, and reports it at
  completion without exposing secrets.
- Always displays the LLM model ID in the first-run wizard and rejects partial
  LLM configuration where only the API URL or only the model ID is supplied.
  A bounded one-Token probe must verify the returned model identity before the
  wizard persists configured LLM values. Stable aliases may resolve to the same
  model basename with a bounded numeric/date version suffix, while arbitrary
  suffixes remain rejected.
- Repairs executive-wallboard runtime integrity by using one coherent Agent
  identity across ownership, registry, Session, Task Plan, and Loop facts.
- Runtime-source failures now produce degraded partial responses with
  unavailable values instead of indistinguishable current-looking zeros.
- Organization-scoped Agent aggregates follow active primary Human ownership
  and organization closure.
- Makes v4.4.10 the fresh-deployment baseline. Historical migrations remain
  for checksum, ordering, reproducibility, and audit, not as a customer
  in-place upgrade promise; v4.4.8 remains withdrawn.
- Closes the legacy collaboration authorization gap by making Security Domain
  binding and current membership mandatory for execution-group compatibility
  routes; historical groups remain internal compatibility relations only.
- Adds company-public, organization-subtree, organization-level, Human-private,
  and Agent-private Knowledge policies enforced across list, item, graph, and
  retrieval paths.
- Widens Knowledge and Branch detail drawers, makes compact controls responsive,
  and covers all 22 primary management views in the three-database browser gate.

- Completes atomic hard/warn Token and monetary quotas, encrypted exact
  non-streaming replay, and the public correlation/retryability error contract.
- Adds Provider invoice import, append-only reconciliation and correction,
  Enterprise balanced allocation, and governed Ed25519 external evidence.
- Adds immutable allow-listed wallboard definition versions with governed
  publish/rollback while preserving a read-only viewer.
- Adds migration 57, three-database live full-flow evidence, and bounded
  performance tooling; local measurements remain bounded and are not a capacity certification.

- Adds an optional OpenAI-compatible model gateway and immutable usage facts
  for provider-reported Token dimensions, decimal cost, provenance, request
  correlation, and incomplete streaming outcomes without retaining prompts or
  model responses.
- Adds per-LLM-Provider-Profile routing controls. Direct and platform-gateway
  modes may be enabled independently or together; changes require an explicit
  compliance reason and the forwarding address is generated by the platform.
- Adds an authenticated read-only executive wallboard with Agent, Session,
  Task Plan, Loop, and stalled-runtime state plus 14-day Token and cost curves,
  bounded usage detail, coverage, and freshness states.
- Adds equivalent v4.4.10 schema migrations and representative usage data for
  Oracle, PostgreSQL, and YashanDB.

## v4.4.9 - 2026-08-19

- First public release after v4.4.7; v4.4.8 is withdrawn and retained only
  as historical evidence.
- Adds fail-closed v4.4.8 schema detection so v4.4.9 cannot be applied to a
  withdrawn-version database.
- Repairs database identity and row-security boundaries across Oracle,
  PostgreSQL, and YashanDB, including filtered legacy collaboration reads.
- Prevents PostgreSQL Agent provisioning from restoring control-plane table
  grants and resolves SECURITY DEFINER identity from the authenticated login.
- Adds typed Agent and Graph execution evidence, package/source-commit
  integrity checks, incremental Channel delivery, and frontend vendor
  splitting, a dynamic Graph route, and bounded slow-database, long-history,
  and terminal-stream browser gates.
- Restores or reinitializes all validation targets from approved pre-v4.4.8
  baselines and retains publication as an evidence-consistency decision.
- Fixes in-place management Channel streaming updates so intermediate content
  remains visible instead of appearing only with the terminal response.
- Expands platform command help/results, adds verified deterministic product
  overview responses, and clarifies titled compliance posture/enforcement
  combinations in the Enterprise overview.

## v4.4.8 - 2026-08-18 (withdrawn)

- Added a database-authoritative platform command registry, command
  completion, deterministic help, and governed maintenance-task lifecycle.
- Added deterministic observation proposals and explicit Graph Run binding for
  long-running maintenance without a second execution kernel.
- Kept Compliance Agent proposal-only and isolated Compliance/Admin private
  knowledge by audience, scope, classification, digest, and signature.
- Added platform private knowledge, command, maintenance, safe-autonomy, and
  isolation-inventory migrations for Oracle, PostgreSQL, and YashanDB.
- Enforced Oracle Data Grants, PostgreSQL forced RLS with trusted role mapping,
  and YashanDB fail-closed privilege revocation.
- Restricted Oracle application-context identity to the matching End User and
  removed PostgreSQL custom-GUC identity fallback for mapped runtime roles.
- Added cross-domain classification ceilings, LLM management-boundary checks,
  source-only private-knowledge projection, and focused negative isolation
  tests.
- Verified idempotent v4.4.8 migrations and read-only live validation across
  Oracle, PostgreSQL, and YashanDB Enterprise baselines.

## v4.4.7 - 2026-08-17

- Hardened LLM Provider Profile save, reference-safe logical retirement,
  saved-profile probing, returned-model identity checks, and health writeback.
- Reduced Dashboard startup latency by calculating the complete capability
  manifest from one current authorization snapshot and loading authentication
  and capability data in parallel.
- Standardized configuration panel width, grouping, and spacing across the
  Dashboard. This maintenance release adds no database migration.
- Fixed the protected management Channel's final SSE delta flush so short
  provider responses are delivered incrementally instead of appearing only at
  completion.
- Added private signed management knowledge for the native Agent-template
  workflow, including required security and approval controls and an explicit
  statement of the current template-editing API boundary.
- Added immutable management knowledge v2 with complete Dashboard navigation,
  Business Agent template semantics, and request-language-aligned Chinese or
  English management responses; retained v1 as audit history.
- Stacked the managed Skill / Tool manifest and deployment adapter contract
  panels vertically at full content width.
- Clarified the release maturity boundary: Graph Runtime core and authorized
  inspection are Production Profile capabilities; controlled Graph items and
  protocol/GraphRAG research remain evidence-gated and are not promoted by
  metadata alone.

## v4.4.6 - 2026-08-16

- Added database-authoritative Human registration with configurable display
  name, email, mobile, and one-use Human Registration Token policies.
- Unified Portal and Dashboard registration through an independent
  registration surface while preserving separate Agent Enrollment Tokens.
- Added exclusive Portal operation-page leases and configurable per-user
  connection limits; reused sessions can be inspected but cannot mutate.
- Added provider-neutral external identity transaction and callback contracts
  for future WeCom, DingTalk, Feishu, OIDC, and customer adapters. Claims never
  grant roles or access by themselves.
- Added explicit Graph Engineering capability posture: `PRODUCTION`,
  `CONTROLLED`, `DISABLED`, or `UNAVAILABLE`.
- Added additive identity, Portal, Graph posture, and portable contract
  alignment migrations for Oracle, PostgreSQL, and YashanDB.

## v4.4.5 - 2026-08-15

- Preserved Dashboard child-view state through bounded URL deep links across
  refresh, re-login, direct navigation, and browser history without exposing
  credentials, tokens, message bodies, or model secrets.
- Added immutable Graph Run admission contracts for Definition and Plan
  digests, compatibility, State schema, and budget schema versions. Plans from
  another Graph Version or with a mismatched digest fail closed.
- Governed Agent Card projection by explicit platform Skill grants; protocol
  metadata remains descriptive and cannot grant authority.
- Paused forks before the first Worker claim when replay could reach a
  non-repeatable external effect. Resume requires an approved
  `GRAPH_FORK_REPLAY` decision or bounded compensation evidence.
- Added equivalent additive Graph Run contract migrations for Oracle,
  PostgreSQL, and YashanDB.

## v4.4.4 - 2026-08-14

- Added governed Portal Agent Pool LLM policy and Portal-side profile
  switching among administrator-allowlisted healthy profiles.
- Added typed Platform Administration commands and foundational managed-node,
  shared-storage, external-endpoint, and native-template contracts.
- Added additive migrations for Oracle, PostgreSQL, and YashanDB.
- Moved Agent Pool and cloud-environment controls to a dedicated Dashboard
  configuration page and added audited managed-node/shared-storage bindings
  for Admin Agent runtime directories.
- Completed Agent Pool Host onboarding with bounded reachability verification,
  one-time bootstrap receipt, dedicated runtime-storage binding, administrator
  activation, and authenticated heartbeat. Raw bootstrap tokens, SSH
  passwords, database keys, and private keys are never persisted.
- Moved Agent Pool Configuration under Platform Operations after Admin Agent
  admission. MaaS, SaaS, and virtualization stay explicit deployment-adapter
  boundaries.

## v4.4.3 - 2026-08-13

- Unified Dashboard inventory paging above and below each cursor-backed list.
  Authorized totals are returned for task, Memory, Skill, Knowledge, and Spec
  inventories so the page indicator does not show an unknown total.
- Added governed Security Domain inventory, accountable ownership, explicit
  Human/Agent membership, lifecycle records, and audited bindings for Channels
  and legacy collaboration groups.
- Added reviewed conversion drafts: legacy collaboration-group Agents remain
  candidates until individually confirmed; no sharing policy or historic group
  membership is converted into authorization.
- Revalidated active Domain membership for Channel discovery, reads, writes,
  threads and Gateway membership admission. Revoked or expired access fails
  closed while retained evidence remains governed.

## v4.4.2 - 2026-08-13

- Added verified Embedding test-and-activate with automatic dimension discovery and database-authoritative Contract, default Space, Binding, and migration maintenance.
- Enforced encrypted API-key storage, platform normalization, Graph Production Profile capability gates, and authenticated Knowledge inventory visibility.
- Corrected configuration forms, empty business inputs, single-line cursor pagination, and bilingual protected configuration views.

## v4.4.1 - 2026-08-12

- Added the protected Platform Administration Channel, separate Admin Agent
  enrollment paths, distinct weighted quorum, Leader lease/term/fencing, and
  explicit high-availability readiness.
- Added independent Dashboard/Portal idle and absolute session policies,
  bounded opaque cursors for all high-frequency inventories, verified upgrade
  protocol, safe-point Skill distribution, and ordered containment acknowledgements.
- Kept NFS, object storage, unified storage, and infrastructure termination as
  explicit customer adapter contracts rather than in-core claims.

## v4.4.0 - 2026-08-11

- Added database-native governed SDD revisions, immutable baselines,
  structured clauses, task graphs, leases, reviews, evidence and amendments.
- Added OpenSpec source snapshots and normalized import interoperability;
  execution continues from the Chuanxu database after handoff.
- Added governed software delivery roles, isolated task resources, SCM
  credential references and digest-bound independent evidence.
- Added the Specifications and Delivery Workbench and six-edition v4.4.0
  migration and validation gates.

## v4.3.7 - 2026-08-10

- Added the local Bootstrap Deployment Agent, prepared-target preflight,
  encrypted owner-only journal, durable deployment evidence, and retirement
  handoff to platform-native management Agents.
- Added governed Embedding Profiles, immutable Contracts, Spaces, bindings,
  platform/Agent probes, `LEGACY_DEFAULT` isolation, and all five supported
  execution modes.
- Added the protected Deployment & Models dashboard and a bounded,
  lease-protected local Embedding Worker for asynchronous ingestion and
  re-embedding outside HTTP request handling.

## v4.3.6 - 2026-08-07

- Added platform-native Agent bootstrap and separated Platform Admin and
  Enterprise Compliance Admin identities from the human `admin` account.
- Added encrypted LLM Provider Profiles, governed business Agent requests and
  approvals, built-in sensitive-domain templates, runtime isolation levels,
  lease-fenced local execution, and customer deployment adapter contracts.
- Added the database-authoritative external Agent registration policy with
  `DISABLED`, `APPROVAL_ONLY`, and `ENABLED` states while preserving existing
  Skill-first registrations.

## v4.3.5 - 2026-08-05

- Added a database-authoritative Platform Capability Configuration page with
  protected mandatory capabilities, dependency checks, required reasons,
  optimistic concurrency, immutable history, and audited transactions.
- Added request-level backend enforcement so hiding a Dashboard page cannot
  bypass a disabled capability. Community packages cannot enable Enterprise
  capabilities through the runtime registry.
- Optimized capability page-state loading to one authoritative database read.
- Removed admin Skill tokens from cross-Admin acquisition URLs and hardened
  Oracle End User identifier validation before dynamic DDL.

## v4.3.4 - 2026-08-04

- Added Enterprise Agent Compliance Posture, credential-proven Gateway
  activation, governed Profile templates, bounded evidence, deterministic
  findings, remediation, exceptions, controls, Controller diagnostics, and
  Gateway/MCP integration.
- Added the additive v4.3.4 compliance migration and live-schema validator
  contract for Oracle AI Database 26ai, PostgreSQL 18, and YashanDB 23.5.4.
- Corrected identity and Gateway expiry clock handling for databases using
  local naive `TIMESTAMP` values, and aligned Gateway Client Secret lookup
  with the registration credential digest contract.
- Fixed Portal human-session authorization after Agent-context requests by
  enforcing Schema Owner identity checks, guaranteed Oracle connection return,
  and bounded connection-pool waiting during short request bursts.

## v4.3.3 - 2026-08-03

- Hardened the database-authoritative Graph Runtime with additive assurance
  evidence, bounded test-only failpoints, invariant scans, and local Agent
  Runtime recovery records.
- Added canonical Graph Definition supply-chain envelopes with dependency
  locks, Ed25519 verification, import scanning, provenance, and untrusted
  Draft publication gates.
- Added disabled-by-default Dynamic Graph, A2A 1.0.1, and OpenTelemetry GenAI
  preview boundaries. They project existing governed Graph facts and do not
  introduce a second authorization or execution engine.
- Local Agent Runtime recovery is not database HA. This release does not claim
  database-cluster failover, database RPO/RTO, independent A2A conformance, or
  real OTLP Collector delivery.

## v4.3.2 - 2026-08-01

- Added database-authoritative versioned Memory Families, immutable Versions,
  current pointers, representations, relationships, snapshots, candidates,
  reviews, jobs, usage events, and projection outbox facts across all three
  adapters.
- Made normal Memory deletion a reasoned logical-unavailability transition;
  physical erasure remains a separate compliance workflow.
- Added the Dashboard Memory lifecycle workspace and bounded current-version
  Library/Chain, Consolidation Workbench, and Policies and Jobs views.

## v4.3.1 - 2026-07-31

- Added database-authoritative graphical organization governance, canonical
  memberships and reporting, organization versions/history, semantic change
  sets, directory staging, closure-backed authorization, and the Organization
  Dashboard workspace across all database adapters and editions.

All notable changes to the AI Agent Infra unified repository are documented in
this file. Each released edition (Oracle/PG/YashanDB × Community/Enterprise)
inherits the entries below; per-edition release notes live in
`RELEASE_NOTES_v<VERSION>.md` shipped with each build.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the rules in `openspec/specs/documentation-format/spec.md`.

The released technical packages are distributions of **Chuanxu (川序)**, the
**AI Agent Management Platform**. `AI Agent Infra with DB` remains the unified
technical project name.

## [4.3.0] - 2026-07-29

See `RELEASE_NOTES_v4.3.0.md` for the integrated release contract. The former
v4.2.1 Graph closure is an internal milestone consumed by this release and is
not published as a separate edition or archive.

### Identity, enrollment, and controlled collaboration

- Added database-backed Human and Agent Principals, Sessions, CSRF, Argon2id
  password handling, registration approval, organizations, Security Domains,
  delegated roles, scopes, permission versions, and fail-closed access checks.
- Added one-time user-sponsored Enrollment Tokens that bind Agent owner,
  sponsor, runtime, environment, domain, risk tier, quota, and credential
  metadata without storing reusable plaintext secrets.
- Added Channel, mixed human/Agent messages, Action Cards, Barrier arrivals,
  participant snapshots, and node-scoped Agent Gateway instance fencing.
- Added local-node restart recovery that never revokes another Dashboard node's
  active Agent instances.

### Graph integration and packaging

- Integrated the internal Graph Executor, durable runtime, event delivery,
  evidence, retry, fencing, and v4.1 Task/Loop compatibility work into the
  shared v4.3.0 source line.
- Added the configurable Graph maturity boundary: the v4.3.0 production
  profile is the current production recommendation after the complete live
  evidence gate passed; Graph preview controls require explicit enablement.
- Builds contain only `RELEASE_NOTES_v4.3.0.md`, with six edition-specific
  license and feature boundaries checked by the release gate.
- Offline dependency packaging now accepts multiple platform wheels for one
  pinned version. `cryptography==49.0.0` is documented with a source-built
  `manylinux_2_28` RHEL 8 wheel alongside the upstream `manylinux_2_34` wheel;
  the installer and verifier select the compatible artifact. `verify_deps.py`
  also walks mandatory wheel metadata recursively, including platform markers,
  so an incomplete transitive wheelhouse fails closed.
- Fixed PostgreSQL Graph traversal predicates for legacy text edge endpoints:
  numeric entity IDs and historical values such as `PG_AGENT_001` now share a
  text comparison boundary, so invalid numeric casts cannot abort Graph
  queries while valid numeric edges continue to resolve.
- Redirected the legacy Dashboard login route to the Principal-aware
  application shell so authentication cannot fall into a legacy
  password-session loop.
- Changed MFA enforcement to an explicit User Management policy. Administrator
  roles no longer force MFA before the first Dashboard login, while enabling
  enforcement requires an already confirmed factor and revokes existing
  Sessions.
- Fixed Portal SSE buffering across both the FastAPI compatibility bridge and
  the upstream LLM reader; token chunks now remain incremental end to end.
- Fixed unrestricted user-list and Principal-visibility queries on Oracle and
  YashanDB by omitting bind values that are absent after `ALL`-scope SQL
  simplification.

## [4.2.0] - 2026-07-25

See `RELEASE_NOTES_v4.2.0.md` for the current Experimental Graph Engineering
release contract.

### Experimental Graph Engineering

- Added versioned Graph Definitions, deterministic compilation, durable Runs,
  Node Runs, Attempts, Transitions, Checkpoints, Artifacts, and evaluations.
- Added leased and fenced Worker execution, authenticated Event Inbox/Outbox,
  compatibility wrappers for v4.1 Task/Loop workflows, and governed runtime
  intervention with immutable evidence.
- Added five additive core Graph migrations for Oracle AI Database 26ai,
  PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4+ native Property Graph
  projection; Enterprise adds a separate scheduler HA overlay.
- Added governed manual, API, schedule, database, external, and internal Graph
  trigger registration and idempotent Event Inbox delivery.
- Kept v4.1.x as an independently buildable Stable line; the latest validated
  v4.2.x baseline may graduate to the next Stable release when Graph contracts
  stabilize.

### Release packaging

- v4.2.0 is built with the `experimental-4.2` profile and dated 2026-07-25.
- Each archive contains only `RELEASE_NOTES_v4.2.0.md`.

## [4.1.0] - 2026-07-24

See `RELEASE_NOTES_v4.1.0.md` for the current release contract.

### Enterprise governance

- Added registered-Agent admission with stable identity, credential digest,
  heartbeat, lifecycle status, expiry, and administrator import.
- Added Enterprise resource catalog, policy decisions, bounded grants,
  multi-party approvals, separation of duties, emergency controls, retention,
  legal hold, masking, integrity evidence, and scoped export.
- Added three-database v4.1.0 governance migrations and capability evidence.

### Product UI

- Applied the Chuanxu brand system to all 17 product templates.
- Added local light-first Chinese defaults, persisted language/theme preferences,
  local logo and line-icon assets, and offline UI resources.
- Unified the Enterprise Approval/Audit navigation labels, language controls,
  feature divider, and row-detail interaction. Expandable Dashboard lists now
  explain the row interaction, while Audit uses the full row instead of a
  redundant detail column.
- Moved the management-platform identity into the sidebar brand, normalized
  footer geometry, unified graph-label contrast, and added bilingual filter
  chips for Agent status, graph type, approval status, audit level, and task
  status. Approval empty states now follow the selected status, and Audit
  documents the exact legal-hold scope behavior.
- Localized dynamic status, action, decision, audit, resource, emergency, and
  Skill enum values without changing their stored/API representations. Chinese
  navigation now consistently labels Skills as `技能`, while raw audit evidence
  and identifiers remain unchanged.
- Extended display-only enum localization to Agents, Workspaces, Specs,
  Branches, Collaboration, and Loops, including detail badges and Branch/Loop
  form choices. Language switching refreshes rendered values without changing
  API payloads or stored state.
- Unified the Enterprise Approval/Audit sidebar footer geometry with every
  other Dashboard page, including language, logout, and countdown spacing.
- Community packages physically exclude Enterprise governance modules, routes,
  templates, tests, documentation overlays, and SQL overlays.

### Release packaging

- Builds contain only the current release notes file.
- Version, database, edition, and license labels are generated from package
  metadata and the v4.1.0 release date is 2026-07-24.

## [4.0.1] - 2026-07-22

See `RELEASE_NOTES_v4.0.1.md` for the complete release contract. This version
adds fail-closed per-Agent database identities, AES-256-GCM configuration
envelopes, durable side-effect jobs, lossless Skill packages, strict edition
allowlists, three-database migrations, and executable release evidence.

Configuration encryption now covers database credentials, LLM and routing API
keys, and `security.secret_key`. Runtime `config.json` and master-key files are
enforced as owner-only (`0600`), including already-encrypted configurations;
verification output never prints the session-signing secret.

### Fixed

- Web dashboards now render the release version instead of stale v3.10.2 labels.
- Frontend countdowns, backend sessions, and cookies use the configured
  five-minute default timeout consistently on every protected page.
- Audit no longer loads Bootstrap into the Dashboard. Its native tabs,
  responsive statistics grid, typography, and overall scale now match the
  other Dashboard pages across all three Enterprise editions.
- Dashboard sidebars use one compact navigation spacing contract, with
  visualization regression tests covering version, timeout, and layout.
- Monitor performance metrics use each database's deployed session columns,
  include sample counts, preserve numeric zeroes, and label absent samples.
- Portal now assigns Agents from the actual POOL state, reuses a user's active
  assignment, and returns released Agents to the pool.
- Portal Markdown rendering now uses a bundled GFM parser and HTML sanitizer
  for history, non-streaming replies, and streaming replies.
- Portal session identities are normalized across databases. Exit waits for
  confirmed release, while Web startup reclaims only Agents persisted with
  the current Admin node ID and leaves other nodes unchanged.
- Concurrent Admin nodes claim Pool Agents through conditional status updates.
- PostgreSQL numeric Workspace IDs are normalized at every Portal history
  operation, including switch, rename, and delete.
- PostgreSQL shared APIs now honor BIGINT identity IDs, deployed Spec/Session/
  Workspace columns, interval arithmetic, and polymorphic graph edge IDs.
- YashanDB now reuses pooled connections correctly and recovers the same
  deterministic independent database user created during registration.
- Cross-database tests now validate integer and string ID contracts without
  string-only operations, use unique Skill names, and remain repeatable after
  an interrupted run.
- Final post-migration evidence records 141 passing tests in each generated
  package plus explicit passing live contracts for all three databases.
- Pool lifecycle tests now use an isolated capability tag and return their
  claimed test Agent in a `finally` block, preventing shared demo pools from
  being exhausted by release regression.

## [4.0.0] - 2026-07-19

### Summary

Ground-up restructure of AI Agent Infra from six independent per-edition
repositories into a single unified source tree that generates all six release
editions (Oracle / PostgreSQL / YashanDB, each in Community and Enterprise
tiers) via one build script. This release introduces the adapter-overlay
layout, a single `VERSION` source of truth, a shared OpenSpec store, and a
spec-driven validator that gates releases on the OpenSpec contracts.

### Added

- **Unified repository layout** (`shared/` + `adapters/<db>/`) replacing six
  divergent per-edition trees.
- **`build.py`** — generates `build_output/<edition>/` plus a release zip per
  edition, overlays adapter code on top of shared code, injects the version
  string, and emits per-edition `config.json` / `requirements.txt`.
- **`VERSION`** as the single source of truth for the version string, read by
  `build.py` and `spec_validator.py`.
- **`editions/*.json`** — six per-edition configuration files driving
  `build.py` (license, web port, DB connection, `extra_features`).
- **`spec_validator.py`** — validates each built edition against the OpenSpec
  specs (required files, minimum test counts, API endpoint surface); supports
  `--edition`, `--live --base-url`, and `--json` modes.
- **`openspec/config.yaml`** pointing at the shared store at
  `/root/AI-Agent-Infra-Specs`.
- **`shared/tests/conftest.py`** — pytest parameterization over
  `oracle` / `pg` / `yashandb` with auto-skip of unreachable backends and
  environment-variable overrides (`AIAGENT_TEST_DB`, `AIAGENT_SKIP_DB`,
  `AIAGENT_*_DSN` / `_HOST` / `_USER` / `_PASSWORD`).
- **`shared/docs/AGENTS.md`** — guide for the unified repo covering the build
  system, version management, edition configs, OpenSpec store, and test
  infrastructure.
- **`shared/README_TEMPLATE.md`** — per-edition README template consumed by
  `build.py`.
- **OpenSpec store** with four initial specs: `api-contract`,
  `database-adaptation`, `documentation-format`, `test-requirements`.

### Changed

- **Build pipeline**: releases now produced by `python3.14 build.py` from one
  source tree, replacing the prior per-edition copy-and-patch workflow.
- **Version injection**: `build.py:inject_version()` rewrites `VERSION = "..."`
  in Python and `vX.Y.Z` literals in `.py`/`.sql`/`.md`/`.html`/`.sh` for
  every file in each built edition; no source file may hardcode a version.
- **Directory shape of built editions**: loose `.py`/`.sh` files and `lib/`,
  `tests/`, `tools/`, `visualization/` subdirectories now live under
  `scripts/` in every built edition.
- **`config.py`**: each edition now derives from `adapters/<db>/config_db.py`
  instead of carrying its own copy.
- **Test runner**: `pytest` is now the canonical runner via the parameterized
  `conftest.py`; the legacy `test_all.py` master runner remains for
  non-pytest environments.

### Fixed

- Eliminated cross-edition drift in shared business logic (loop_api,
  memory_api, graph_api, etc.) — there is now exactly one copy in `shared/lib/`.
- Eliminated version-string skew across files within an edition — every build
  rewrites all of them from `VERSION`.
- Eliminated the "forgot YashanDB" class of release mistakes by building all
  six editions from one command and validating them against one spec set.

### Notes

- **Minimum test counts** per edition (from `test-requirements/spec.md`):
  Oracle COM/ENT 121, PG COM/ENT 103, YashanDB COM 109 / ENT 113.
- **API contract**: all editions must serve the common endpoints listed in
  `api-contract/spec.md`; Enterprise editions additionally serve
  `/api/admin/crypto/rotate`, `/api/approvals`, `/api/audit`.
- **Database drivers**: Oracle uses `oracledb>=4.0.1`, PG uses
  `psycopg2-binary>=2.9`, YashanDB uses `yaspy>=1.2.1`.

## [3.10.2] - 2026-07-17

### Summary
YashanDB adaptation — full support for YashanDB 23.5+ with the yaspy driver,
expanding the edition matrix to 6 (2 Oracle + 2 PG + 2 YashanDB). 670 tests
pass across all editions.

### Added
- **YashanDB adapter** — `adapters/yashandb/` (connection.py, config_db.py,
  agent_api.py, deploy_yashandb.py) with yaspy 1.2.1 driver.
- **YashanDB schema** — `1_schema.sql` adapted (no reference partitioning, no
  JSON_OBJECT, no inline FK, no LOCAL index) for YashanDB compatibility.
- **`install_yaspy.sh`** — installs yaspy `.so` + client libs and recreates
  `.so` / `.so.MAJOR` symlinks under `~/.yashandb/client/lib/`.
- **`vendor/yaspy/`** — bundled yaspy driver + YashanDB client libraries
  (deduplicated: only `*.so.MAJOR.MINOR.PATCH` shipped, symlinks recreated at
  install time).
- YashanDB connection.py converts yaspy VECTOR `array.array` returns to string
  to avoid GC-time segfaults.

## [3.10.2] - 2026-07-16

### Summary
Enterprise encryption enhancement — per-Agent independent crypto keys (DB
storage + admin_token distribution), config.json auto-encryption on startup
(database + LLM + model_routing), key rotation API, encrypt_config.py CLI
tool, Portal Markdown rendering. 544/544 tests pass.

### Added
- **Per-Agent crypto keys** — each agent gets an independent encryption key
  stored in DB and distributed via admin_token.
- **config.json auto-encryption** — on startup, sensitive fields (database
  password, LLM api_key, model_routing credentials) are encrypted in place
  using PBKDF2-derived keys.
- **Key rotation API** — `/api/admin/crypto/rotate` for Enterprise editions.
- **`encrypt_config.py`** — CLI tool to manually encrypt/decrypt config.json.
- **Portal Markdown rendering** — portal chat now renders Markdown responses.

## [3.10.1] - 2026-07-14

### Summary
Offline deployment — vendor/ directory with 30 pre-downloaded cp314 wheels,
install_offline.sh for air-gapped installation, verify_deps.py for integrity
check. Pure-Python deploy_oracle.py replaces SQLcl (125 MB + Java) with a
state-machine SQL parser handling PROMPT/DEFINE/&&// syntax. Zero external
runtime dependencies.

### Added
- **`vendor/` directory** — 30 pre-downloaded cp314 wheels for air-gapped
  installation.
- **`install_offline.sh`** — installs all wheels into the active Python.
- **`verify_deps.py`** — verifies wheel integrity and Python version.
- **`deploy_oracle.py`** — pure-Python SQL deployment script replacing SQLcl;
  state-machine parser handles PROMPT, DEFINE, &&, //, BEGIN/END blocks.

## [3.10.0] - 2026-07-09

### Summary
Universal Property Graph — 30+ graph functions across 8 domains: knowledge
causal (CAUSES/CONTRADICTS), agent collaboration (group-scoped TRUSTS), task
orchestration (FEEDS_INTO/PRODUCED_ARTIFACT), skill dependency, approval
propagation (BLOCKS with cascade reject), data flow (DERIVED_FROM_DATA),
memory evolution (PROMOTED_TO/MERGED_INTO), loop iteration
(BUILDS_ON/INFORMS/CORRECTS). 23 new edge types. Dynamic trust via
SYSTEM_CONFIG.

### Added
- **30+ graph functions** in 8 domains with 23 new edge types.
- **Dynamic trust configuration** via SYSTEM_CONFIG table.
- **Cascade approval rejection** via BLOCKS edge propagation.

## [3.9.0] - 2026-07-05

### Summary
Ecosystem connectivity — MCP Server (10 tools, stdio + SSE), SSE streaming
output, Human-in-the-Loop approval (step/loop/tool), Agent Protocol
compatibility, multi-model routing.

### Added
- **MCP Server** — 10 tools exposed via stdio and SSE transports.
- **SSE streaming** — real-time token streaming for portal chat.
- **Human-in-the-Loop approval** — step/loop/tool level approval gates.
- **Agent Protocol compatibility** — `/ap/v1/agent/tasks` endpoint.
- **Multi-model routing** — per-task model selection via model_routing config.

## [3.8.0] - 2026-07-02

### Summary
Multi-Agent integration testing — 5-phase deployment, 15/15 functional tests
passed. Oracle: LOOP_MANAGER, DB_CRYPTO, schema prefix fixes. PG:
_convert_params rewrite, policy double-ON, authenticate v_salt fixes. ENT:
LOOP_AUDIT, audit routing.

### Fixed
- Oracle LOOP_MANAGER package body compilation.
- Oracle DB_CRYPTO package integration with config encryption.
- Oracle schema prefix collision in ENT deployments.
- PG `_convert_params` rewrite for RETURNING INTO clause handling.
- PG policy double-ON trigger for RLS + audit.
- PG authenticate v_salt verification logic.
- ENT LOOP_AUDIT routing and audit trail completeness.

## [3.7.5] - 2026-06-28

### Summary
Bug fixes: orchestrator, event_bus security, message_api DELETED status, ENT
missing Data Grants. PG: connection.py rewrite, 10 modules Oracle-to-PG
migration.

### Fixed
- Orchestrator deadlock on concurrent task assignment.
- event_bus security check bypass via crafted payload.
- message_api DELETED status not propagating to collab_api.
- ENT missing Data Grants policy on knowledge_entities table.
- PG connection.py rewrite for connection pooling stability.
- 10 modules migrated from Oracle-specific syntax to cross-DB compatible SQL.

## [3.7.4] - 2026-06-26

### Summary
6 expansions: Agent Communication Protocol, Multi-Agent Orchestration (DAG),
Event-Driven, Advanced Memory, Observability, Tool Ecosystem.

### Added
- **Agent Communication Protocol** — inter-agent messaging with typed channels.
- **Multi-Agent Orchestration (DAG)** — dependency graph for multi-agent tasks.
- **Event-Driven** — event_bus with pub/sub and dead letter queue.
- **Advanced Memory** — episodic + semantic + procedural memory types.
- **Observability** — OpenTelemetry-compatible tracing and metrics.
- **Tool Ecosystem** — tool registry with versioning and access control.

## [3.7.3] - 2026-06-23

### Summary
Deployment fixes: schema FK ordering, DEFINE SCHEMA_OWNER, config priority,
embedding model prompt.

### Fixed
- Schema foreign key creation ordering for clean-slate deployment.
- DEFINE SCHEMA_OWNER directive not resolving on PG.
- Config priority: config.json now overrides environment variables correctly.
- Embedding model prompt template for bge-m3.

## [3.7.2] - 2026-06-19

### Summary
Documentation consistency: corrected function counts, job schedules, partition
counts, PG terminology, evaluation types.

### Fixed
- Function count discrepancies across docs (126 Oracle / 103 PG / 109 YashanDB).
- Job schedule descriptions (DBMS_SCHEDULER vs pg_cron).
- Partition count inconsistencies in deployment guide.
- PG terminology ("schema" vs "database" vs "tablespace").
- Evaluation type enumeration (THRESHOLD/SPEC_VALIDATION/AGGREGATE/HUMAN/LLM_JUDGE/CUMULATIVE).

## [3.7.1] - 2026-06-19

### Summary
Loop Engineering collaborative integration: Spec-Driven Loop, Task-Loop
Binding, Collaborative Loop. SPEC_VALIDATION & AGGREGATE evaluation types.

### Added
- **Spec-Driven Loop** — loops driven by spec validation results.
- **Task-Loop Binding** — loops bound to tasks via task_id FK.
- **Collaborative Loop** — multi-agent loops with role-based iteration.
- **SPEC_VALIDATION evaluation type** — evaluates against spec contracts.
- **AGGREGATE evaluation type** — aggregates multi-agent evaluation results.

## [3.7.0] - 2026-06-18

### Summary
Loop Engineering (4th gen AI methodology): 4 loop tables, LOOP_MANAGER package,
4 evaluation types, lifecycle hooks. ENT: LOOP_AUDIT.

### Added
- **4 loop tables** — LOOPS, LOOP_ITERATIONS, LOOP_RESULTS, LOOP_FEEDBACK.
- **LOOP_MANAGER package** — PL/SQL package for loop lifecycle management.
- **4 evaluation types** — THRESHOLD, HUMAN, LLM_JUDGE, CUMULATIVE.
- **Lifecycle hooks** — pre/post iteration hooks for custom logic.
- **ENT LOOP_AUDIT** — audit trail for loop decisions and iterations.

## [3.6.2] - 2026-06-18

### Summary
Portal chat fix, 15 PG bug fixes. ENT: audit trail, LDAP auth, skill tokens,
compliance logs.

### Fixed
- Portal chat SSE streaming buffer issue.
- 15 PG-specific bugs (connection pooling, type coercion, RLS policy).
### Added
- **ENT Audit trail** — immutable audit log for all data modifications.
- **ENT LDAP auth** — bind DN + bind password with connection pooling.
- **ENT Skill tokens** — time-limited tokens for skill invocation.
- **ENT Compliance logs** — structured logs for regulatory compliance.

## [3.6.1] - 2026-06-16

### Summary
PG Community & Enterprise Editions initial release, full feature parity with
Oracle.

### Added
- **PG adapter** — connection.py, config_db.py with psycopg2 2.9 driver.
- **PG schema** — 1_schema.sql with RLS policies replacing Data Grants.
- **Full feature parity** with Oracle edition (knowledge, graph, memory, loops).

## [3.6.0] - 2026-06-13

### Summary
Admin/Agent separation, Recovery Codes, Private Skill, row-level isolation fix.

### Added
- **Admin/Agent role separation** — distinct permission sets and UI.
- **Recovery Codes** — 10 one-time codes for admin account recovery.
- **Private Skill** — skills with `is_private=true` visible only to creator.
### Fixed
- Row-level isolation bypass via collab_api cross-agent query.

## [3.4.0] - 2026-06-11

### Summary
Deep Data Security, Row-Level Isolation (Data Grants / RLS), MAC, zero-trust
architecture.

### Added
- **Data Grants (Oracle)** — row-level security via DBMS_DATA_GRANTS.
- **RLS (PG)** — row-level security via pg_rowsecurity.
- **Mandatory Access Control (MAC)** — security classification labels.
- **Zero-trust architecture** — every request verified, no implicit trust.

## [3.1.0] - 2026-06-02

### Summary
Full rewrite, dual-edition strategy, database-native encryption.

### Added
- **Dual-edition strategy** — Community (Apache 2.0) vs Enterprise (BSL 1.1).
- **Database-native encryption** — DBMS_CRYPTO for column-level encryption.
- **Full rewrite** — modular architecture with clear separation of concerns.

## [2.0.0] - 2026-05-15

### Summary
Unified architecture rewrite, oracledb driver.

### Added
- **oracledb driver** — migration from cx_Oracle to python-oracledb thin mode.
- **Unified architecture** — consolidated modules into cohesive service layer.

## [1.0.0] - 2026-05-09

### Summary
Initial release: knowledge base & property graph.

### Added
- **Knowledge base** — document ingestion, chunking, embedding, vector search.
- **Property graph** — entities, relationships, graph traversal queries.
