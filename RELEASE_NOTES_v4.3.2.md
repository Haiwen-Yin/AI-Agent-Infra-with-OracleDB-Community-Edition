# AI Agent Infra with DB v4.3.2

Release date: 2026-08-01

v4.3.2 is the Chuanxu (川序) Versioned Memory Lifecycle release for Oracle AI
Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4.

## Versioned Memory Lifecycle

- Added stable Memory Families, immutable Memory Versions, current-version
  pointers, source representations, typed relations, snapshots, policies,
  durable jobs, usage events, candidates, reviews, and graph-projection
  outbox facts through additive migration step 23.
- Existing `MEMORY` entities are adopted as version one without changing their
  entity IDs, bodies, tags, embeddings, ownership, workspace, or timestamps.
- Replaced normal memory deletion with reasoned logical unavailability. The
  current version is removed from ordinary retrieval while minimal lineage and
  audit evidence remain available to authorized review.
- Added bounded relational memory-chain traversal. Native Oracle/YashanDB
  Property Graph and PostgreSQL AGE remain rebuildable projections; relational
  facts remain the authorization and correctness source of truth.
- Added deterministic no-LLM representations and organization work. Model
  output is candidate-only and never directly changes the current version.
- Snapshot refresh now performs member selection, replacement creation,
  conditional prior-snapshot transition, and Outbox evidence in one database
  transaction. Pinned security-restricted content fails closed immediately;
  ordinary expiry returns an explicit governed continuation outcome.
- Durable work now freezes bounded Job Items and applies per-job and per-item
  leases, fencing, cancellation, retry, and checkpointed completion. Projection
  Outbox workers expose claims, delayed retry, backlog metrics, and bounded
  rebuild requests without treating a graph projection as an authority.

## Product Interface

- Extended the Dashboard Memory route with Overview, Library, Chain,
  Consolidation Workbench, and Policies and Jobs internal views.
- Added current-version-only compatibility behavior for `/api/memory` and
  version, relation, candidate, job, representation, usage, and logical
  unavailability endpoints for authenticated clients.
- Added governed organization preview/execution, bounded relation discovery,
  cold archival, representation selection, and fenced external-worker result
  service contracts. These operations retain evidence and require a reason
  for restrictive transitions; they never turn model output or memory text
  into an authorization decision.
- Preserved Chuanxu bilingual, light/dark, protected-view, loading, session,
  and responsive Dashboard behavior.

## Upgrade And Evidence

- `migration_runner.py --version 4.3.2` selects v4.3.1 prerequisites, the
  journaled, retryable `23_v4_3_2_memory_lifecycle.sql` step, and the
  checksum-preserving `24_v4_3_2_memory_digest_alignment.sql` correction for
  legacy adopted rows. It also applies
  `25_v4_3_2_disable_legacy_memory_fusion.sql`, which removes the obsolete
  direct-mutating fusion/importance-decay scheduler rather than allowing it
  to bypass immutable versions, review, snapshots, and audit.
- `26_v4_3_2_snapshot_subject_fencing.sql` adds optional Principal permission
  and Agent-instance fencing bindings to Runtime Memory Snapshots. When a
  caller supplies that context, revocation, offboarding, domain removal, or
  instance replacement fails closed before pinned content is returned.
- `27_v4_3_2_memory_governance_completion.sql` adds content-addressed Artifact
  links, immutable ingestion findings, fenced external-worker result evidence,
  representation cold-tier state, and expiry/security review metadata.  Stored
  memory remains untrusted data: deterministic safety signals quarantine
  ordinary access pending governed review; approved model output remains a
  structured candidate and cannot directly mutate a Version or authorization.
- Live baseline upgrades completed for Oracle, PostgreSQL/AGE, and YashanDB.
  The release does not claim unmeasured capacity, compression, or Token gains.
- A v4.3.2 archive contains only `RELEASE_NOTES_v4.3.2.md`.

See `docs/memory-lifecycle.md`, `docs/api-reference.md`, `docs/security.md`,
and `docs/migration.md` for lifecycle and compliance boundaries.
