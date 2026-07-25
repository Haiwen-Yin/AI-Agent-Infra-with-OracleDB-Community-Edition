# Recovery and High Availability - AI Agent Infra with DB v4.2.x

## Recovery Authority

The database is the source of truth for Graph Definitions, published Compiler
plans, Runs, Attempts, State Events, Checkpoints, Transitions, Leases, Events,
Artifacts, and audit/governance evidence. Web processes, Schedulers, Workers,
and Agents may restart without becoming the owner of the only copy of state.

## Worker and Scheduler Restart

1. Stop accepting new side effects when the database is unavailable.
2. Reconnect and revalidate registration, grants, policy, and current Graph
   version.
3. Let expired leases return Ready work to the claim queue.
4. Reject late completion or checkpoint writes with a stale fencing token.
5. Recover State by applying State Events after the latest valid Checkpoint.
6. Resume only after the Runtime has restored a legal state and budget.

Enterprise may run multiple Scheduler nodes. Atomic database claims and fencing
provide local ownership; no remote node is reclaimed merely because a local
web process restarted.

## Database High Availability

Database replication, backup, failover, and storage durability are deployment
responsibilities. Configure them using the supported database architecture:

- Oracle Data Guard/RAC or the organization's approved Oracle HA design.
- PostgreSQL streaming replication, failover manager, and tested backups.
- YashanDB's approved primary/standby or cluster HA design.

After a database failover, restart or reconnect the application nodes, verify
the database identity and migration ledger, and run the Graph capability and
lease-recovery probes. The platform cannot recover state from an unavailable
or unrecoverable database; database backup and restore are therefore a
required production control.

## Backup and Migration

The v4.2 migration gate requires a verifiable backup reference before Apply.
Dry Run without that evidence is blocked. The additive migration ledger makes
retries idempotent. Application rollback uses the v4.1 profile with a restored
pre-upgrade backup; direct destructive downgrade is not required.

## Artifact and Evidence Recovery

Artifacts are content-addressed and retained by policy. Legal hold blocks
purge, and evidence export includes scope, hashes, and integrity metadata.
Large payloads are not copied into every Trace or Audit row. If a referenced
Artifact is unavailable, the Run remains diagnosable through its hashes and
transition metadata and must not silently substitute a different payload.
