# Versioned Memory Lifecycle - AI Agent Infra with DB v4.4.3

## Purpose

v4.3.2 makes memory optimization safe for Agent operation without treating
memory text, model output, prompts, graph visibility, or retrieval history as
authority. A Memory Family is the stable logical identity. A Memory Version is
immutable content and interpretation state. Each Family points to one current
Version, published only with the expected current Version in one database
transaction.

Types are `EPISODIC`, `FACT`, `PREFERENCE`, `DECISION`, `PROCEDURAL`, and
`EXPERIENCE`. Scope is independent: `RUNTIME_CONTEXT`, `CHANNEL_MEMORY`,
`AGENT_MEMORY`, `WORKSPACE_MEMORY`, or `ENTERPRISE_KNOWLEDGE`. Scope never
grants access by itself; every read still applies Principal, Agent, purpose,
Security Domain, organization, ownership, classification, validity, and
resource checks.

## Lifecycle And Forgetting

Versions may be `CANDIDATE`, `ACTIVE`, `STALE`, `CONFLICTED`, `SUPERSEDED`,
`EXPIRED`, `MIGRATED`, `ARCHIVED`, `QUARANTINED`, or `UNAVAILABLE`. A normal
delete request creates a reasoned logical-unavailability successor instead of
physically deleting evidence. Ordinary search excludes unavailable, archived,
and quarantined versions; authorized history retains the family, version,
digest, relation, actor, and reason.

Physical erasure is a separate compliance workflow. It must assess retention,
legal hold, dependent versions, Artifacts, backups, exports, and evidence. It
cannot claim to recall content already consumed by a model or exported outside
the platform.

## Representations, Chains, And Jobs

One governed source representation can have atomic-fact, short, standard,
topic, and chain summaries. Each records source versions, digest, generation
method, validation state, and Token count. Deterministic extraction works with
no LLM configured. An approved model may propose structured output only after
endpoint, transfer, classification, purpose, and schema checks; it produces a
candidate, never direct truth or activation. An approved semantic candidate is
activated only by a second, reasoned operation that creates an immutable
successor Version.

Source, summary, migration, use, outcome, scope, and temporal relations are
recorded as relational facts. Similarity, overlap, replacement, conflict, and
promotion store method, evidence, confidence, and review state. Traversal,
degree, candidates, and chain size are bounded. Oracle and YashanDB native
Property Graph and PostgreSQL AGE are rebuildable projections; the relational
fallback remains authoritative and works while a projection is delayed.

Memory Jobs use database records, bounded Job Items, leases, fencing tokens,
checkpoints, cancellation, retry, and idempotency. Creating a Job freezes a
bounded input partition; only the current lease holder with the matching
fencing token can finish its Job or Item. Start consolidation in dry-run mode,
inspect impact and candidates, then use approval/review where policy requires
it. Usage and feedback are immutable attributed events; access frequency cannot
rewrite base importance or independently promote shared knowledge.

An explicit snapshot refresh selects its members, persists the replacement,
conditionally marks the prior snapshot refreshed, and writes its Outbox event
in one database transaction; ordinary Version activation never rewrites an
existing Run context. Snapshot resolution fails closed for `QUARANTINED`,
`UNAVAILABLE`, `ARCHIVED`, and `EXPIRED` versions even when they were pinned.
When a Run supplies its Principal and Agent-instance context, the snapshot also
stores the Principal permission version and instance fencing token. Resolution
rechecks both values, the Principal status, and every selected security-domain
membership before returning any pinned member. Revocation, offboarding, domain
removal, instance replacement, or token fencing therefore fails closed without
waiting for a normal snapshot refresh.
Ordinary expiry instead returns a governed `PAUSE`, `HUMAN_DECISION`, or
explicit `RISK_CONTINUE` boundary and never silently extends validity.

Projection events use a separate database Outbox with conditional claims,
leases, fencing, delayed retry, backlog metrics, and bounded rebuild requests.
Oracle/YashanDB native Property Graph and PostgreSQL AGE workers may consume
that Outbox, but their projections are caches only: relational facts remain the
authorization and correctness source and are used when projection work lags or
is unavailable.

## Agent Skill And MCP Boundary

The authenticated MCP surface exposes `memory_lifecycle_create`,
`memory_lifecycle_chain`, `memory_lifecycle_feedback`, and
`memory_lifecycle_candidate`. The transport identity is resolved from the
registered Agent token, never from a tool argument. Creation is limited to the
Agent's `AGENT_MEMORY` or `RUNTIME_CONTEXT` scope. Chain reads, feedback, and
candidate submission require that the source Version is owned by that same
Agent. Candidate submission never publishes a Version; an authorized reviewer
must approve it and a separate governed activation must provide a reason.

The HTTP API provides the corresponding Dashboard and automation paths:
`/api/memory`, `/api/memory/{family_id}/versions`,
`/api/memory/{family_id}/chain`, `/api/memory/{family_id}/candidates`,
`/api/memory/snapshots`, `/api/memory/snapshots/{snapshot_id}/refresh`,
`/api/memory/snapshots/{snapshot_id}/resolve`, `/api/memory/jobs`,
`/api/memory/jobs/{job_id}/cancel`, `/api/memory/jobs/{job_id}/retry`, and
`/api/memory/projections/metrics`. Authentication, current Principal authorization, and
edition capability checks remain server-side; a Skill document, MCP tool name,
or hidden Dashboard control does not grant access.

## Upgrade

Run the journaled upgrade with a recoverable backup record:

```bash
python3.14 scripts/migration_runner.py --version 4.3.2 --edition enterprise \
  --database <oracle|pg|yashandb> --<database>-config config.json \
  --backup-evidence backup-evidence.json
```

Step `23_v4_3_2_memory_lifecycle.sql` adopts existing `MEMORY` entities as
version one without changing their external IDs. Step
`24_v4_3_2_memory_digest_alignment.sql` then converts legacy adoption digests
to SHA-256 without changing Family or Version identity. Step
`25_v4_3_2_disable_legacy_memory_fusion.sql` removes the obsolete direct-
mutation scheduler; all future organization uses governed durable jobs and
review candidates. If interrupted, rerun the same command. Do not edit a
journal checksum or use direct table deletion as a rollback method.
