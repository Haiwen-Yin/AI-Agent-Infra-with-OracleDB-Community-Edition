# Graph Engineering - AI Agent Infra with DB v4.2.x

> Experimental contract guide for Chuanxu (川序), the AI Agent Management
> Platform.

## Scope

Graph Engineering is the execution and coordination layer above individual
Agent, Skill, Tool, Model, data, and human resources. In this project it is
implemented as a database-backed, versioned, governed execution graph. It is
not a claim that the older relationship graph or a visual DAG alone is the
complete methodology.

The v4.2.0 core contract covers definition, compiler, durable runtime, Worker
protocol, event delivery, State and Checkpoint recovery, Artifact references,
the versioned evaluator registry, intervention, governance, database
projections, UI, Skill, migration, and release evidence. The external Graph
Engineering field is still new, so contracts are versioned and may change
within v4.2.x. Capacity baselines, failure-injection/restore measurements,
Enterprise multi-Scheduler HA, and complete evaluator migration remain
experimental follow-up work and are not implied by this release.

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
boundaries, stale-lease rejection, bounded cycles and budgets, and recovery
from database-persisted Checkpoints. It does not promise exactly-once effects
for arbitrary remote systems. `NON_IDEMPOTENT` work requires compensation,
external status confirmation, or human resolution after an uncertain result.

The evaluator registry currently preserves the six v4.1 Loop types: `MANUAL`,
`TEST`, `DIFF`, `LLM_JUDGE`, `SPEC_VALIDATION`, and `AGGREGATE`. The Graph
contract normalizes their version, level, pending state, route decision, and
sanitized observation result. It does not execute shell commands or make LLM
requests itself; those effects remain governed Worker/Node Executor work.
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

## Compatibility with v4.1

Task Plans and Loops retain their public behavior. The compatibility bridge
can create a Graph wrapper with legacy IDs and explicit status mappings. It
does not infer missing edges from old history. Completed history stays
read-only; active work is migrated only at a quiescence barrier with a
pre-migration Checkpoint and a recorded mapping.

## Experimental Graduation

Each v4.2.x change must record a contract version, compatibility impact,
migration/review behavior, and three-database evidence. When the external
Graph Engineering requirements and this project's contracts are stable, the
latest validated v4.2.N code and schema become the basis of the next Stable
release. The runtime is graduated, not reimplemented.
