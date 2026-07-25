# AI Agent Infra with DB v4.2.0

## Experimental Graph Engineering Release

Release date: 2026-07-25

v4.2.0 is the first **Experimental Graph Engineering** release of the
Chuanxu (川序) AI Agent Management Platform. It adds a database-backed
execution graph above the existing v4.1.0 Task, Loop, Skill, Tool, Agent, and
governance capabilities. The experimental label is intentional: v4.2.x may
evolve while Graph Engineering contracts are validated in real deployments.

The v4.1.x Stable line remains independently buildable from the same source
line. Stable packages retain the v4.1.0 Graph Explorer and exclude the new
execution-graph modules, Graph migrations, and experimental Dashboard views.
When Graph Engineering contracts become stable, the latest validated v4.2.x
baseline can graduate directly to the next Stable release without maintaining
a second long-lived implementation.

## Highlights

- **Versioned Graph Definitions:** canonical JSON definitions with registered
  node and edge types, immutable published versions, aliases, lineage,
  digests, signatures, lifecycle transitions, and import/export redaction.
- **Deterministic Compiler:** typed condition ASTs, dependency validation,
  bounded cycles, fan-out/fan-in, joins, subgraphs, side-effect classes,
  capability declarations, and online budget validation without evaluating
  arbitrary Python, SQL, shell, or network expressions.
- **Durable Graph Runtime:** database-persisted Runs, Node Runs, Attempts,
  Ready work, Transitions, State Events, Checkpoints, Branches, Joins, Trace,
  Evaluations, Waits, Artifacts, and migration history.
- **Worker protocol:** external or platform Workers advertise capabilities,
  claim work with a short lease, renew with a fencing token, checkpoint
  progress, complete or fail work, and never receive database credentials.
- **Events and effects:** authenticated Event Inbox/Outbox handling,
  idempotency, bounded artifact content, retention, legal hold, and explicit
  uncertainty for non-idempotent external effects.
- **Graph triggers:** governed registration and delivery for MANUAL, API,
  SCHEDULE, DATABASE, EXTERNAL, and INTERNAL trigger families. Registration is
  bound to a published Graph Version and requires an actor and reason; delivery
  enters the authenticated, idempotent Event Inbox before an optional Run.
- **Governed control:** pause, resume, cancel, retry, reassign, compensate,
  skip, force-route, fork, and version migration append immutable evidence and
  require an actor and reason. Enterprise policy and approval controls remain
  authoritative for high-risk operations.
- **Evaluator contract:** the six v4.1 Loop evaluator types now share a
  versioned Graph registry/observation contract with bounded route and metric
  output. External command and LLM execution remains outside this pure
  contract and requires a governed Worker/Node Executor.
- **v4.1 compatibility:** Task Plans and Loops can create versioned Graph
  compatibility wrappers. Existing v4.1 APIs, identity isolation, Portal
  lifecycle, encryption, approvals, audit, and emergency controls remain
  supported.
- **Database-native adaptation:** Oracle uses native Property Graph/SQL PGQ;
  PostgreSQL 18 uses Apache AGE with the relational contract as the portable
  authority; YashanDB uses its native Property Graph projection and shared
  relational runtime. PostgreSQL 19 native Property Graph is a future adapter
  target, not a v4.2.0 prerequisite.
- **Chuanxu Dashboard:** the experimental Graph page adds Definition,
  Run Monitor, Artifact, worker, state, trace, and evidence views while the
  existing Graph Explorer remains available.

## Database and Edition Scope

All six packages implement the same Graph contract. Community includes the
core definition, compiler, runtime, worker, event, state, checkpoint, artifact,
compatibility, and basic evaluation surfaces. Enterprise additionally applies
resource policy, multi-party approval, advanced governance, retention/legal
hold, evidence export, and multi-Scheduler controls from the v4.1.x
Enterprise boundary.

| Database | v4.2.0 implementation | Notes |
|---|---|---|
| Oracle AI Database 26ai | Native Property Graph / SQL PGQ projection | Relational runtime tables remain authoritative for execution state. |
| PostgreSQL 18 | Apache AGE projection | AGE is required for the v4.2.0 PostgreSQL package; native PostgreSQL 19 support is future work. |
| YashanDB 23.5.4+ | Native Property Graph projection | Portable relational edge operations remain available for runtime behavior. |

## Upgrade and Recovery

The v4.2.0 migrations are additive and idempotent. Run preflight and Dry Run
with a verified backup evidence record before applying the five core Graph
migration scripts in order. Enterprise packages insert the scheduler HA
overlay between the edge-scope and trigger scripts. A retry continues from the migration ledger and does not
repeat an applied statement. Existing v4.1 history is retained; active legacy
work is migrated only when a safe compatibility mapping exists, otherwise it
is placed in an explicit review state.

Database replication, backup, and failover remain deployment responsibilities.
The Graph Runtime additionally recovers leases and state from the database
after a Worker or Scheduler restart, so an Agent process can be replaced
without losing the managed execution history.

## Compatibility and Experimental Policy

- Graph Definition, Compiler, Runtime, Worker, and event contracts are versioned
  and may receive compatible or explicitly deprecated changes in v4.2.x.
- A breaking contract change requires a new schema/definition version,
  migration or review state, release-note entry, and repeated three-database
  evidence.
- Graph-only behavior is not advertised as part of v4.1.x Stable packages.
- v4.2.x does not imply universal exactly-once delivery for remote
  non-idempotent side effects; compensation or human resolution is required
  when the outcome is uncertain.

## Verification

The release gate covers Graph unit and runtime contracts, adapter migrations,
Apache AGE availability, stable-profile exclusion, experimental-profile
inclusion, package purity, encrypted configuration, UI/Skill/API contracts,
and the applicable v4.1.0 regression suites. Performance figures are reported
only when the identical-hardware benchmark evidence is complete; they are not
part of the Graph correctness claim.
