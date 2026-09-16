# v4.4.15 Release Notes

Release scope: Oracle, PostgreSQL and YashanDB, Community and Enterprise editions.

## Implemented Changes

- Fixes Memory graph tag lookup when native versioned families coexist with legacy entities. Family IDs are no longer used as legacy entity keys, preventing PostgreSQL numeric-ID errors; bound queries and normalized tag keys preserve adopted Memory tags across adapters.

- Adds migrations 95–96 for immutable execution/assembly relationships, Worker input attempts and original Gateway credentials. The real Worker rechecks requester and target source authority before sending, rejects revoked/fenced credentials and never automatically repeats an uncertain send. Result reads enforce the same source boundary.
- Adds shared Dashboard/Portal contextual Agent execution, current target discovery and result/input-receipt views, with typed Gateway and MCP operations. Fixes continuity form nesting and field layout; standalone migration verification uses the selected package version explicitly.
- Adds recipient-authorized signed Skill archive download and an independent verifier using a locally pinned public key. Acknowledgements require the matching transport digest and current server trust, commit atomically with audit, preserve deferred updates in pending inventory and reject stale attempts to revert activation. Safe-point reports remain Agent attestations, separate from observed external runtime switching.
- Repairs release signing with an exact file-manifest signature, immutable transport digest checks and operator signing tooling. Metadata-only trust claims, duplicate archive paths and tampering are rejected; bilingual signing instructions are included.
- Allows continuity workspace scopes through public Agent token exchange and rejects unsupported scopes before creating an instance. Fresh HTTP enrollment and native-login checks cover Community and Enterprise on all three databases.
- Checks historical execution queue dependencies during deployment verification. Corrects Oracle reserved bind names, native JSON numeric digest round trips and nested MCP authentication context; audit failures roll back Tool proposals atomically.

- Adds the database-entity specification for context continuity and work handoff.
- Defines Work Contracts, Handoffs, Context Assemblies, candidate review, immutable Revisions, explicit publications, and unified diagnostics.
- Reuses the existing Agent, organization, Security Domain, task, branch, Graph Run, database-mediated collaboration, and audit entities.
- Preserves the released v4.4.14 migration terminal. The v4.4.15 chain adds task foreign-key repair, resumable owner-only online copying and stable HASH partitioning in migration 85, followed by continuity entities in migrations 86 through 88.
- Adds 45 continuity tables, native immutable-history triggers, strict column/default/key/check validation and direct Agent SQL denial. Authenticated service operations retain independent current resource authorization.
- Pins Handoff evidence to its original publication grant and binds recipient operations to the actual Gateway instance and fencing token; immutable credential history stores digests only.
- Adds explicit outcome-to-Experience proposals with exact result provenance, current participant authorization and independent review before promotion.
- Adds migration 88 with immutable, typed Workspace/Task/Graph Run links. Original resource ownership and permissions are rechecked; changing a Task status does not change the relationship key.
- Adds explicit, audited dynamic MCP exposure controls, filtered read-only discovery for independent Agent logins, native mutation protection and cached-name revocation checks. Reimport closes exposure. The current migration terminal is 97 on all three databases; applied migration checksums remain unchanged.
- Adds migration 97 with seven typed immutable native-source relations and Dashboard, Portal, Gateway and MCP/CLI capture entrypoints. Task steps, Graph node progress, DB4A2A dispatch contracts and own security-event summaries retain exact capture times and digests. Original-domain and current native-source authority remain required on every use.
- Adds an explicit cooperative Linux Skill runtime adapter: independently verified installation, process-held turn locks, atomic activation, retained prior versions and retry after an uncertain final acknowledgement. Local runtime observations remain distinct from server-side Agent attestations.
- Adds immutable per-revision handoff policies in migration 94. Serial remains the default; explicit capacities 2–16 retain coordinator ownership with independent recipient outcomes. Dashboard and Portal share policy controls, current-owner authorization, conflict checks and historical policy reads.
- Adds context assembly and publication/revocation forms with exact source evidence, bounded inventories and stable expiry/idempotency payloads after uncertain delivery. Long identifiers wrap on mobile screens.
- Routes dynamic MCP invocation through the authenticated Gateway. Migration 93 adds immutable Tool-request provenance alongside the 45 continuity tables; jobs require approval and revalidate Agent/Worker authority, exposure and payload integrity before execution.
- Adds shared Portal and Dashboard Work continuity, read-only revision previews, offered-handoff revision forms, and typed candidate creation, revision, independent review and promotion. Portal retains its separate session, CSRF and page lease. Bounded domain/recipient/candidate inventories expose authorized metadata only. All database adapters expose the typed continuity MCP tool by default; explicitly configured tool allowlists remain authoritative.
- Resolves the physical web asset directory at startup so removal of a temporary compatibility symlink cannot make a running server return missing-asset errors.
- Adds real bearer/instance Gateway routes, a typed MCP client, and setup/doctor/capabilities/verify-context CLI commands with server-persisted diagnostic observations.
- Corrects instance diagnostics to compare leases against the database issuance clock and keeps deployment postflight bound to the selected installation directory.
- Restores journaled migration execution and strict terminal-step/failed-step verification for v4.4.15.
- Combines consecutive leading system messages for compatible model requests, preserving instruction order, user roles and content-security checks.
- Corrects frontend package metadata to v4.4.15 and adds explicit isolated database, runtime and real-model regression gates.
- Distinguishes missing YashanDB native clients from database connectivity failures, with package-local installation guidance and sanitized diagnostics.
- Restores task terminal-state Graph synchronization and Oracle/YashanDB completion timestamps; success, failure and cancellation paths are covered by expanded lifecycle gates.
- Releases Portal connection slots when login cannot assign an Agent or acquire a page lease. Per-principal locking enforces connection limits under concurrent login.
- Uses the issuance clock consistently for Portal lease expiration and heartbeat checks across database session timezones. Expired pages reuse their unique lease row with an incremented fencing token.
- Fixes Community Portal language initialization when Enterprise-only authentication options have been removed.

## Verification Boundary

The four continuity phases include typed database entities, exact source snapshots, product Worker input, independent review, signed Skill delivery and persistent diagnostics. Acceptance covers the six editions, authenticated product entrypoints, real-model execution, native permissions, concurrency and recovery. Check the release evidence against the exact package hash before deployment; a historical test report or successful health response alone is not release evidence. Customer capacity, database HA/RPO/RTO, arbitrary external-process cancellation and unobserved direct traffic require separate environment-specific evidence. The cooperative Skill client is not an independent process-isolation system. See the [operations guide](docs/continuity-operations.md), [Chinese operations guide](docs/continuity-operations_zh.md) and [Chinese deployment and operations](docs/operations_zh.md).
