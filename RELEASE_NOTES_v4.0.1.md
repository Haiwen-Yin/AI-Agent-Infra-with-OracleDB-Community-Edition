# AI Agent Infra v4.0.1 Release Notes (2026-07-22)

v4.0.1 is a security and release-integrity update for all six Oracle AI
Database, PostgreSQL, and YashanDB Community/Enterprise packages.

## Operational Contract

- Admin Agent is the only component allowed to hold schema-owner credentials.
- Every Business Agent uses an independent database identity. Connection,
  decryption, or identity mismatch fails closed and never falls back to Admin.
- Configuration secrets use versioned AES-256-GCM envelopes. Legacy envelopes
  are accepted only by the explicit migration path.
- Encrypted configuration covers database credentials, LLM and model-routing
  API keys, and the session-signing `security.secret_key`. Runtime config and
  master-key files are forced to owner-only (`0600`) permissions.
- Side-effect requests become durable jobs with policy, approval, lease,
  attempt, retry, cancellation, idempotency, and audit state in the database.
- Skill packages preserve the complete ZIP tree and `SKILL.md`, are immutable
  by version/hash, and materialize only after hash and permission verification.

## Database Identity

| Database | Business Agent identity | Isolation mechanism |
|---|---|---|
| Oracle AI Database 26ai | Native End User | End User Context and Data Grants |
| PostgreSQL 18 | Dedicated LOGIN role | Role mapping plus transaction RLS identity |
| YashanDB 23.5.4+ | Dedicated database user | Object grants and request identity checks |

## Editions

Community contains the complete core runtime under Apache-2.0. Enterprise adds
approvals, compliance audit, LDAP, Skill Token distribution, and orchestrator
features under BSL-1.1. The build physically removes Enterprise-only Python,
routes, templates, and dedicated SQL from Community artifacts.

## Upgrade

Back up the schema, configuration, master key, and v4.0.0 package. Run
`scripts/deploy/7_v4_0_1_migration.sql` through the provided migration runner,
then require passing capability and mode evidence before starting Business
Agents. See `docs/migration.md` and `docs/security.md`.

## Evidence

Release status requires unit/security tests, six package checks, migration
ledger evidence, live capability probes against all three databases, and all
18 edition/mode targets. Numeric token claims are published only from the
reproducible benchmark report and describe prompt-input size only.

The final encrypted-config migration regression completed all six generated
package suites with 141 passing tests per package. Each suite's three
environment-dependent live contracts were conditionally skipped by default;
Oracle, PostgreSQL, and YashanDB were then configured explicitly and each live
contract passed. All three Enterprise health endpoints returned v4.0.1 after
restart.

## Regression Coverage

- All six generated Community/Enterprise packages run their complete pytest
  suite directly from the release directory against the configured database.
- Cross-database generated IDs preserve their native contract: PostgreSQL
  BIGINT identities return positive integers; Oracle and YashanDB return
  non-empty string IDs.
- PostgreSQL compatibility covers deployed Spec, Session, Workspace, Loop, and
  polymorphic graph-edge schemas rather than relying on Oracle column names.
- YashanDB coverage includes reusable pool lifecycle, independent user
  registration, and password recovery using the same deterministic username.

## Web Console Corrections

- All dashboard titles and sidebar brands display v4.0.1.
- Protected pages consistently display and enforce the configured five-minute
  session timeout, including Graph, Monitor, and Audit.
- Audit uses native Dashboard tabs and a responsive statistics grid instead of
  page-specific Bootstrap globals, keeping its overall scale consistent across
  Oracle, PostgreSQL, and YashanDB Enterprise editions.
- Dashboard sidebar navigation uses one compact spacing contract on every page.
- Monitor performance averages use deployed database columns and expose sample
  counts so zero values and absent samples are rendered correctly.
- Portal Agent allocation now consumes and recycles the database-backed Agent
  pool instead of relying on an Agent ID naming convention.
- Portal chat restores complete, sanitized GFM rendering for tables, task
  lists, nested lists, links, blockquotes, and fenced code blocks.
- PostgreSQL history switching now uses a normalized string user identity.
- Portal Exit waits for confirmed Agent release before redirecting. Web startup
  reclaims only Agents persisted with the current Admin node ID; other Admin
  nodes remain untouched, and concurrent Pool claims use conditional updates.
