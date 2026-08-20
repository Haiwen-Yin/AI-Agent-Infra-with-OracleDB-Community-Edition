# AI Agent Infra with DB v4.4.9

Security repair and runtime reliability release over the approved v4.4.7
baseline. v4.4.8 is withdrawn and is not a supported upgrade source.

## Release boundary

- v4.4.9 is the first public release after v4.4.7.
- Deployments that already contain v4.4.8 schema objects or journal rows are
  rejected before any v4.4.9 migration runs. Operators must restore an
  approved pre-v4.4.8 baseline or reinitialize the target under an approved
  recovery procedure.
- No v4.4.8-to-v4.4.9 in-place repair path is provided.

## Database security

- Repairs identity and row-security boundaries for Oracle, PostgreSQL, and
  YashanDB.
- PostgreSQL no longer accepts unmapped-role identity from a custom GUC and
  applies forced RLS plus explicit deny policies to maintenance state. The
  authenticated Agent login, rather than a SECURITY DEFINER owner, is used for
  role mapping; later Agent provisioning cannot restore control-plane grants.
- Legacy collaboration reads use filtered, versioned compatibility contracts
  and do not restore broad database grants.

## Runtime and evidence

- Adds typed execution evidence for Agent, Task, Loop, Maintenance, and
  Compliance remediation runs, including capability proof, budgets, leases,
  fencing, side effects, compensation, takeover, and output provenance.
- Binds maintenance Graph Runs to execution evidence and records the source
  commit in generated build manifests.
- Enforces package guards against credentials, runtime databases, caches,
  logs, and unapproved generated files.

## UI performance

- Splits frontend vendor bundles and the Graph route into a dynamic capability
  chunk while keeping initial JavaScript within the v4.4.9 budget.
- Replaces Channel full-surface polling with incremental cursor reads and
  pauses background refresh while the page is hidden.
- Refreshes the bounded recent Channel window while a streaming response row
  is updated in place, so accepted deltas expand visibly before completion.

## Management Channel and compliance clarity

- Expands `/platform HEALTH_READ` into a credential-free control-plane report
  covering managed nodes, native Agents, LLM and Embedding profiles, runtime
  executions, database dialect, and check time. The common `HEATH_READ` input
  typo is normalized to the canonical audited command.
- Platform command help now includes localized summary, syntax, required
  parameters, risk, execution mode, and executor state. Governed proposals
  report their Action Card and approval status without claiming execution.
- Recognized platform and product introduction questions use verified scoped
  management knowledge and do not require an LLM profile.
- Compliance overview cards identify evidence assessment, visible Agent count,
  and platform enforcement as distinct dimensions. Known combinations have
  business titles, and `UNKNOWN` is explicitly insufficient evidence rather
  than a violation.

## Verification boundary

The Oracle, PostgreSQL, and YashanDB Enterprise validation targets were
restored or reinitialized from approved pre-v4.4.8 baselines, migrated through
the journaled v4.4.9 chain, and populated with deterministic test data. Release
publication remains fail-closed unless the final source-commit, archive,
three-database, browser, and evidence-consistency gates all pass together.

## Enterprise validation fixtures

- Restores the entity-relationship graph and organization graph projections.
- Shows compliance posture state and control-state summaries in the Enterprise
  UI, including compliant, unknown, and non-compliant/isolated fixtures.
- Seeds Chinese organization names, five governed people, four subordinate
  Agents, and deterministic reporting/ownership relationships in all three
  Enterprise validation databases.
- The `yhw1809/oracle` account is a local validation fixture only; it is not a
  default credential and must not be used as a customer production account.
