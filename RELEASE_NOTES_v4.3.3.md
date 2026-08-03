# Chuanxu AI Agent Infra v4.3.3

Release date: 2026-08-03

## Graph Engineering Trustworthy Runtime

v4.3.3 is the current Production Profile. It hardens the database-authoritative Graph Runtime while preserving the
v4.3.2 organization, Channel, Memory, Portal, Dashboard, Skill, MCP,
governance, and audit contracts.

- Adds an additive Graph assurance evidence ledger, test-only bounded
  failpoints, invariant scans, and local Agent Runtime recovery records.
- Adds a signed Graph Definition exchange envelope with canonical digests,
  dependency locks, import scanning, provenance, and an untrusted-Draft gate.
- Adds Dynamic Graph v1 preview. Changes create immutable Draft child versions,
  compile the complete target topology, compare risk, and require governed
  approval before a high-risk proposal can be published.
- Adds isolated A2A 1.0.1 and OpenTelemetry GenAI preview adapters. Both are
  disabled by default and project existing Graph facts; neither is an
  authorization authority or a second execution engine.

## Operational Boundary

The release validates local Agent Runtime recovery against database-authoritative
leases, fencing, Runs, Checkpoints, and events. It does not claim database
cluster failover, standby promotion, database-level RPO/RTO, or exactly-once
effects in arbitrary external systems. Production database HA remains the
responsibility of the tested database topology operated by each deployment.

## Upgrade

Apply `28_v4_3_3_graph_assurance.sql` through `migration_runner.py` after
recording recoverable backup evidence. The migration is additive and retains
all prior Graph, Memory, organization, Channel, identity, governance, audit,
and artifact facts.
