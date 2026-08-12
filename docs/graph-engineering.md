# Graph Engineering - AI Agent Infra with DB v4.4.1

> Integrated contract guide for Chuanxu (川序), the AI Agent Management
> Platform.

## Scope

Graph Engineering is the execution and coordination layer above individual
Agent, Skill, Tool, Model, data, and human resources. In this project it is
implemented as a database-backed, versioned, governed execution graph. It is
not a claim that the older relationship graph or a visual DAG alone is the
complete methodology.

The integrated v4.3.0 contract covers definition, compiler, durable runtime,
Worker protocol, versioned Node Executors, event delivery, State and Checkpoint
recovery, Artifact references, the versioned evaluator registry, intervention,
governance, database projections, UI, Skill, migration, and release evidence.
The external Graph
Engineering field is still new, so contracts are versioned and may change
within the v4.3.x maturity cycle. Capacity baselines, failure-injection/restore measurements,
Enterprise multi-Scheduler HA, and complete evaluator migration remain
evidence-gated follow-up work and are not implied by an unverified build.

## Concepts

| Concept | Meaning |
|---|---|
| Graph Definition | Stable identity and ownership boundary. |
| Graph Version | Immutable published topology and schemas. |
| Node | A typed unit such as Agent, Model, Skill, Tool, Database, Human, Event, or Subgraph. |
| Edge | A typed route with condition, branch, join, cycle, error, timeout, or compensation semantics. |
| Run | One execution of one published version. |
| State Event | Append-only state delta used for recovery and replay. |
| Checkpoint | Materialized state snapshot or branch point. |
| Trace | Operational control-flow record, separate from compliance Audit. |
| Artifact | Content stored once and referenced by hash, classification, retention, and hold. |
| Lease Token | Short Worker authority protected by fencing. |
| Evaluator | Versioned observation contract for Node, Edge, Trajectory, Outcome, or Reliability evidence. |

## Runtime Guarantees

The Runtime guarantees durable state transitions, idempotent claim/completion
boundaries for exact request replays, stale/expired-lease rejection, bounded cycles and budgets, and recovery
from database-persisted Checkpoints. It does not promise exactly-once effects
for arbitrary remote systems. `NON_IDEMPOTENT` work requires compensation,
external status confirmation, or human resolution after an uncertain result.
`IDEMPOTENT_EXTERNAL` work receives a stable logical Run/Node Run effect key;
the key is persisted with each Attempt so a compatible remote system can
deduplicate lease retries. It is not issued for non-idempotent effects.

The evaluator registry currently preserves the six v4.1 Loop types: `MANUAL`,
`TEST`, `DIFF`, `LLM_JUDGE`, `SPEC_VALIDATION`, and `AGGREGATE`. The Graph
contract normalizes their version, level, pending state, route decision, and
sanitized observation result. It does not execute shell commands or make LLM
requests itself; those effects remain governed Worker/Node Executor work.
The integrated closure also exposes deterministic Event Inbox/Outbox retry scheduling,
attempt-bounded delivery, `DEAD_LETTER` state, and reason-required replay.
Every executable node resolves to a built-in or database-registered declarative
Executor before claim and completion; arbitrary code fields are rejected.
Basic metrics expose committed transitions, retry count, reliability,
interventions, path efficiency when a planned-node denominator is supplied,
and budget utilization. These metrics are evidence inputs, not universal
industry benchmarks.

## Database Strategy

The same relational runtime contract is implemented on all three databases.
Native Property Graph projections provide graph traversal and inspection:

- Oracle AI Database 26ai uses native Property Graph and SQL PGQ.
- PostgreSQL 18 uses Apache AGE; PostgreSQL 19 native Property Graph is a
  later adapter target.
- YashanDB 23.5.4+ uses its native Property Graph projection and relational
  runtime operations where a native query is not available.

This design uses relational transaction and recovery capabilities as the
foundation while leaving vendor syntax inside adapters.

PostgreSQL historical edge compatibility is explicit: older deployments may
contain text endpoints such as `PG_AGENT_001` in `ENTITY_EDGES`, while current
entity IDs are numeric. Relational traversal compares both sides as text,
preserving numeric matches and safely excluding orphaned non-numeric endpoints
instead of attempting an unsafe `BIGINT` cast.

## Compatibility with v4.1

Task Plans and Loops retain their public behavior. The compatibility bridge
can create a Graph wrapper with legacy IDs and explicit status mappings. It
does not infer missing edges from old history. Completed history stays
read-only; active work is migrated only at a quiescence barrier with a
pre-migration Checkpoint and a recorded mapping.

## Maturity And Graduation

Each v4.3.x change records a contract version, compatibility impact,
migration/review behavior, and database evidence. The v4.3.0 production
replacement gate established the stable core. The v4.3.3 release reinforces
that core without creating a second execution kernel.

`production` is the stable runtime profile. `development` and
`experimental-4.2` explicitly enable preview controls. A profile boundary lets
stable and preview controls share one source line without making preview
behavior a production claim.

## v4.3.3 Trustworthy Runtime

v4.3.3 adds a bounded assurance layer to the database-authoritative Runtime.
It records recovery evidence, scans for runtime invariants, and provides
test-only failpoints around claim, completion, checkpoint, and lease-reaping
boundaries. The failpoints have no HTTP, Skill, MCP, Agent, A2A, or Web entry
point and require the in-process `CX_GRAPH_TEST_MODE=1` test boundary.

The verified recovery scope is replacement of an Agent, Worker, Scheduler,
Web, or stream process while its existing local database remains the authority.
Replacement processes revalidate their identity and lease authority; expired
leases become eligible for recovery and stale fencing tokens cannot commit.
This is Agent Runtime recovery, not database-cluster high availability. v4.3.3
does not configure or measure database failover, standby promotion, RPO, or
RTO.

### Governed Dynamic Graph Preview

Dynamic Graph is a disabled-by-default preview. A proposal applies canonical
topology operations to a new immutable Draft child Version. It does not mutate
the source Version or move an active Run. The resulting topology is compiled
before it can be considered, and scope, side-effect, removal, and budget
changes receive deterministic risk classification. High-risk proposals remain
blocked until the existing Enterprise approval service records the required
approval. Run migration, reverse migration, and compensation orchestration are
not completed by this preview and remain explicit follow-up work.

### Definition Supply Chain

Graph exports carry a canonical supply-chain envelope: schema and compiler
versions, publisher and source metadata, parent digest, dependency locks,
compatibility level, document digest, and optionally an Ed25519 signature.
Imports are always new Drafts. Unsigned, unverifiable, or scanned imports may
be retained as `UNTRUSTED_DRAFT` for review but cannot be published. Private
signing material is local publisher input and is never persisted or exported.

### A2A And OpenTelemetry Previews

The A2A 1.0.1 adapter maps a bounded Agent Card and Task identity to the
existing Graph Run. The OpenTelemetry adapter creates a metadata-only,
redacted projection with the pinned mapping version
`otel-genai-preview-2026-08-03`. Both adapters are independent, default off,
and are enabled only by `development` or `experimental-4.2`. They cannot grant
authority or replace Graph, Trace, Audit, or governance evidence.

v4.3.3 provides the internal mapping and contract tests. It has not yet
completed independent A2A client conformance, durable A2A streaming, or a real
OTLP Collector delivery/retry/dead-letter validation. Do not enable either
preview in a production profile until those deployment-specific controls are
validated.
