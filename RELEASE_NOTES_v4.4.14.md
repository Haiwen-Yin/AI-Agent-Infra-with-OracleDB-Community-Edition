# v4.4.14 Release Notes

Status: released and publishable. All mandatory release gates passed.

## Implemented Changes

- Adds a database-authoritative capability posture for model reasoning,
  structured output, model tool calls, MCP discovery and execution, A2A
  exchange, and governed execution.
- Defines the portable `OFF`, `READ_ONLY`, `PROPOSAL_ONLY`, and
  `GOVERNED_EXECUTOR` states with optimistic concurrency and immutable change
  history.
- Keeps external MCP and A2A capabilities disabled by default. Model-generated
  writes, policy changes, Agent control, external contact, and publication
  remain proposal-only unless current trust metadata and Human approval permit
  the governed executor.
- Adds a normalized, secret-free provider evidence envelope for model identity,
  visible content, structured-output validation, tool calls, usage, latency,
  timeout, cancellation, retry, and finish state. Hidden reasoning content is
  not included.
- Adds migration 82 with equivalent additive control-plane objects for Oracle,
  PostgreSQL, and YashanDB.

## Verification Status

Source, generated-package, migration, live database, UI, dependency, POC, and
support-bundle results are recorded in `release_evidence/manifest.json`.
The manifest is authoritative for this release; this note does not replace
the underlying evidence.
