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

## Dashboard performance and layout

- Builds the Dashboard capability manifest from one current database
  authorization snapshot instead of repeating the same principal, role,
  override, and delegation reads for every action. This is not a permission
  cache and does not weaken revocation or explicit-deny behavior.
- Loads the authenticated profile and capability manifest in parallel. In the
  current Oracle ENT verification environment, the capability endpoint was
  reduced from approximately 2.54 seconds to 0.25 seconds.
- Standardizes configuration-panel spacing, keeps Business Agent requests at
  full page width, and groups managed Skill/Tool manifests with deployment
  adapter contracts.

## Protocol and Graph Engineering review

The release planning baseline records MCP `2026-07-28`, A2A `1.0.1`, and the
current checkpoint, sandbox, approval-recovery, and GraphRAG trends as
compatibility candidates. This review does not enable an external protocol or
promote MCP, A2A, OTLP, replay, Dynamic Graph migration, framework adapters, or
GraphRAG projections to Production without independent conformance, security,
and database-adapter evidence.

## Verification scope

- The shared source suite completed with 611 passed and 122 skipped tests. The
  skipped tests require a generated database edition or a reachable live
  Oracle, PostgreSQL, or YashanDB target; they are not recorded as passes.
- All 44 OpenSpec items passed strict validation. The React production build,
  six-edition static release gate, six archive builds, and offline dependency
  gates passed.
- Oracle Enterprise v4.4.7 was exercised as the live Dashboard source for the
  current bilingual website captures. LLM health-state behavior and the
  capability-manifest latency change were verified in that environment.
- This maintenance release has no database migration. Existing three-database
  migration evidence remains historical baseline evidence and is not relabeled
  as a new v4.4.7 online database result.
