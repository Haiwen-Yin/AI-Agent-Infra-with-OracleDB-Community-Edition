# Recovery and High Availability - AI Agent Infra with DB v4.4.1

## v4.4.1 Management Plane Recovery

The protected management Channel, Admin Agent group, quorum snapshots, Leader
terms, fencing tokens, staged package facts, node rollout state, Skill
distribution state, containment commands, and session-policy history are
durable database facts. Repeating initialization does not duplicate Channel
members, platform Admin membership, or default policies.

On Leader failure or lease expiry, the eligible member with the deterministic
highest distinct weight may acquire a new term and fencing token. The previous
Leader can reconnect but cannot write using its old term or fence. This is
application-control-plane availability, not a claim that a single database
instance has been made highly available. Database replication, backup,
promotion, RPO, and RTO remain customer deployment responsibilities.

During upgrade recovery, a node in `DRAINING` retains existing active work and
stops new claims. It cannot move to `MIGRATING` while active work remains.
After a node health acknowledgement, Skill distribution still leaves each
Agent on its old pinned version until a verified safe-point acknowledgement.
Missing acknowledgements are recorded as drift rather than force-switching a
running task.

## Recovery Authority

## v4.3.7 Deployment And Embedding Recovery

Bootstrap runs, deployment steps, evidence, and leases are durable database
facts after the control plane is available. A resumed deployment verifies the
same manifest, target identity, prior evidence, and retry classification before
continuing; it never guesses an unknown partial schema. Completion retires the
temporary Deployment Agent rather than retaining a standing bootstrap
credential.

Embedding jobs are independently leased and fenced. A worker crash leaves
bounded work for retry after lease expiry; a stale worker cannot commit after a
replacement claim. Re-embedding writes to a new Space and keeps the previous
Space read-only until an authorized cutover, so failed migrations do not
silently corrupt the active retrieval set.

## v4.3.6 Native Runtime Recovery

Native executions are durable database rows. A Worker claims a pending row
with a node-scoped lease and increments its fencing token. Completion requires
the same Worker, node, lease fence, and `CLAIMED` state, so a process that
resumes after lease expiry cannot overwrite the replacement Worker's result.
On Web restart, only local Portal, Gateway, and runtime leases are reclaimed;
leases belonging to other Admin nodes are not touched. A database outage
blocks new side effects rather than using an in-memory fallback.

The database is the source of truth for Graph Definitions, published Compiler
plans, Runs, Attempts, State Events, Checkpoints, Transitions, Leases, Events,
Artifacts, and audit/governance evidence. Web processes, Schedulers, Workers,
and Agents may restart without becoming the owner of the only copy of state.

## v4.3.4 Compliance Controller Recovery

The Enterprise Compliance Controller claims bounded evaluation jobs with a
database lease and fencing token. A web or Controller restart leaves an
unexpired lease with its current node; a replacement may only reclaim it after
expiry and must match the new fence to complete it. Repeated evaluation updates
the existing logical finding rather than creating a new finding or duplicate
overdue notification. Approved exceptions expire deterministically and enqueue
re-evaluation; expiry never restores authority. A stale heartbeat or evidence
only degrades posture and never triggers automatic quarantine.

The seeded Compliance Admin identity is an inactive credentialless system
subject, not a recovery credential. It cannot be used to recover the Admin
Agent, Schema Owner, or Human account. Recovering a quarantined Agent requires
the existing governed remediation and authorized control path; evidence and
the triggering finding remain retained.

## Worker and Scheduler Restart

1. Stop accepting new side effects when the database is unavailable.
2. Reconnect and revalidate registration, grants, policy, and current Graph
   version.
3. Let expired leases return Ready work to the claim queue.
4. Reject late completion or checkpoint writes with a stale or expired fencing
   token. An exact replay of an already committed completion returns its
   original result without creating another checkpoint or Transition.
5. Recover State by applying State Events after the latest valid Checkpoint.
6. Resume only after the Runtime has restored a legal state and budget.

Enterprise may run multiple Scheduler nodes. Atomic database claims and fencing
provide local ownership; no remote node is reclaimed merely because a local
web process restarted.

## v4.3.3 Observed Runtime Recovery Boundary

The v4.3.3 validation used the existing Oracle AI Database 26ai, PostgreSQL
18 with Apache AGE, and YashanDB 23.5.4 baseline databases. It exercised
lease expiry and fencing, concurrent claims, a test-only failure before and
after Runtime transaction boundaries, recovery evidence, and invariant scans.
The observed result is that eligible work can be resumed from the existing
database facts without a duplicate committed completion.

The tests do not establish exactly-once execution in arbitrary external
systems. An uncertain `NON_IDEMPOTENT` side effect must be externally
confirmed, compensated, or resolved by an authorized human; it must not be
silently replayed.

## Database High Availability

Database replication, backup, failover, and storage durability are deployment
responsibilities. Configure them using the supported database architecture:

- Oracle Data Guard/RAC or the organization's approved Oracle HA design.
- PostgreSQL streaming replication, failover manager, and tested backups.
- YashanDB's approved primary/standby or cluster HA design.

These are deployment recommendations, not v4.3.3 test evidence. No database
cluster failover, standby promotion, RPO, or RTO test is configured or claimed
by this release. After a customer-managed database failover, restart or
reconnect application nodes, verify database identity and the migration ledger,
and run the Graph capability and lease-recovery probes. The platform cannot
recover state from an unavailable or unrecoverable database; tested backup and
restore remain required production controls.

## Backup and Migration

The v4.3.0 additive migration gate requires a verifiable backup reference
before Apply. Dry Run without that evidence is blocked. The migration ledger
makes retries idempotent. Application rollback uses the v4.1.x profile with a
restored pre-upgrade backup; direct destructive downgrade is not required.

## Artifact and Evidence Recovery

Artifacts are content-addressed and retained by policy. Legal hold blocks
purge, and evidence export includes scope, hashes, and integrity metadata.
Large payloads are not copied into every Trace or Audit row. If a referenced
Artifact is unavailable, the Run remains diagnosable through its hashes and
transition metadata and must not silently substitute a different payload.
