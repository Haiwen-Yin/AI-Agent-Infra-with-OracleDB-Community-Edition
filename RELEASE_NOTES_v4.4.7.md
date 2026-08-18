# AI Agent Infra with DB v4.4.7

Small maintenance and optimization release over the v4.4.6 Production Profile.
It has no database migration and does not change the authorization boundary.

## LLM Provider Profile lifecycle

- Fixes Dashboard form handling that could report a `reset` error after an LLM
  Provider Profile had already been committed. The UI now retains a stable form
  reference across the asynchronous request, refreshes the inventory, and
  reports the committed result.
- Applies the same asynchronous form-safety rule to the other affected
  Dashboard mutation forms.
- Returns an actionable conflict when an LLM Provider Profile is still used as
  the Portal default, remains in the Portal allowlist, is bound to an active
  platform-native Agent, or is referenced by a pending Business Agent request.
- Keeps retirement fail-closed. An unreferenced profile is logically retired,
  its encrypted API key is revoked, and the operation is audited; a referenced
  profile is not partially modified.
- Adds bounded probing for saved profiles. A successful probe writes
  `HEALTHY`, a failed probe writes `DEGRADED`, and `UNKNOWN` is no longer
  presented as a successful health result. The probe also verifies the
  provider-returned model identity, allowing only a provider namespace prefix;
  a reachable endpoint serving a different model is `DEGRADED`. The Dashboard
  probes a newly saved profile, refreshes active profiles in the background,
  and provides a per-profile probe action.

## Protected management Channel

- Flushes the final bounded SSE delta when an LLM provider completes, so a
  short final chunk is streamed before the durable completed response is
  written. The durable response remains the reconnect and recovery source.
- Adds a signed, database-backed private management knowledge manifest for
  built-in Agent-template questions. The management Channel now states the
  actual workflow and its security controls deterministically rather than
  allowing an LLM to guess product capabilities.
- Adds immutable knowledge version 2 while retaining version 1 as audit
  history. Version 2 contains the complete Dashboard hierarchy, defines
  built-in BUSINESS templates as selectable capability tendencies and security
  baselines, and makes clear that templates do not grant authority.
- Carries the current request language through model-backed and deterministic
  management responses. Chinese questions receive Chinese answers and English
  questions receive English answers, apart from product keys and proper names.
- Fresh deployment and upgrade both seed this manifest through the native
  bootstrap. Postflight verifies its managed state, content digest, built-in
  signature, and publication status before reporting deployment completion.
- The current workflow is bootstrap seed -> business Agent request -> separated
  approval -> deployment -> LLM/Embedding and runtime checks -> activation.
  The current release does not provide a direct Agent-template edit/publish
  page or API; Compliance control-template drafts are a different governance
  object and must not be presented as Agent-template editing.

## Dashboard performance and layout

- Builds the Dashboard capability manifest from one current database
  authorization snapshot instead of repeating the same principal, role,
  override, and delegation reads for every action. This is not a permission
  cache and does not weaken revocation or explicit-deny behavior.
- Loads the authenticated profile and capability manifest in parallel. In the
  current Oracle ENT verification environment, the capability endpoint was
  reduced from approximately 2.54 seconds to 0.25 seconds.
- Standardizes configuration-panel spacing, keeps Business Agent requests at
  full page width, and stacks managed Skill/Tool manifests above deployment
  adapter contracts with both panels at full page width.

## Protocol and Graph Engineering review

The release planning baseline records MCP `2026-07-28`, A2A `1.0.1`, and the
current checkpoint, sandbox, approval-recovery, and GraphRAG trends as
compatibility candidates. This review does not enable an external protocol or
promote MCP, A2A, OTLP, replay, Dynamic Graph migration, framework adapters, or
GraphRAG projections to Production without independent conformance, security,
and database-adapter evidence.

The released Production capability matrix enables Graph Runtime core and
authorized inspection. Manifest draft import, SLO read-only views, and
checkpoint fork remain `CONTROLLED`; replay, Dynamic Graph migration,
framework-adapter execution, A2A, and OTLP remain `DISABLED`. These states are
database-authoritative and cannot be promoted by a client, prompt, Skill, or
protocol metadata.

## Verification scope

- The shared source suite completed with 623 passed and 122 skipped tests.
- Final generated Enterprise suites completed with Oracle `691 passed, 7
  skipped`, PostgreSQL `693 passed, 5 skipped`, and YashanDB `691 passed, 7
  skipped`. Skips are adapter-isolation or unified-source ledger checks.
- All 44 OpenSpec items passed strict validation. The React production build,
  six-edition static release gate, six archive builds, and offline dependency
  gates passed.
- Read-only live validators passed for all three baselines. Graph Runtime
  passed 13 database-backed scenarios per database, and memory lifecycle passed
  2 scenarios per database.
- PostgreSQL clean-install validation created a unique temporary database,
  enabled `age` and `vector`, initialized 249 tables from the final package,
  verified the package, and removed the database; post-cleanup inventory was
  zero. Oracle and YashanDB baseline application-schema validation passed; the
  application accounts do not expose approved isolated PDB-creation services.
- The three final Enterprise package directories were started with their
  packaged Python 3.14 runtimes. Oracle, PostgreSQL, and YashanDB each passed
  administrator authentication plus protected Agent, Channel, LLM-profile,
  and runtime-profile reads against the corresponding baseline database.
- This maintenance release has no new database migration. The latest database
  contract remains v4.4.6; v4.4.7 changes application behavior and tests only.
