# AI Agent Infra with DB v4.4.8

Harden built-in platform Agents, Administration Channel commands, and
database-authoritative isolation across Oracle, PostgreSQL, and YashanDB.

## Platform command and governed autonomy

- Adds a versioned database command registry with immutable command metadata,
  risk classification, execution mode, parameter schema, localized help,
  approval policy, expiry, idempotency, compensation, and evidence contracts.
- Adds `/`, `/platform`, command-name, parameter-template, and
  authorized-resource completion in the protected Administration Channel.
- Adds deterministic `/platform HELP` and command-specific help without an LLM.
- Adds stable localized errors for unknown, unauthorized, malformed, expired,
  disabled, proposal-only, and executor-unavailable commands.
- Adds a governed maintenance-task lifecycle with attempts, leases, fencing,
  cancellation, postflight verification, idempotency, and evidence.
- Keeps safe autonomy disabled by default and requires final human approval
  for `HIGH_RISK_CHANGE`. Emergency containment remains a separately modeled
  incident action with mandatory reason, scope, and review.
- Adds deterministic daily observation proposals for health, expired command
  cleanup, LLM status, and Embedding status.
- Adds an explicit `GRAPH_RUN_ID` binding for maintenance work that reuses the
  existing Graph Run admission, lease, fencing, checkpoint, and cancellation
  contract instead of introducing a second durable execution kernel.

## Compliance Agent boundary

- Keeps the Enterprise Compliance Agent advisory and proposal-only.
- Generates remediation cases and `PLATFORM_COMPLIANCE_REMEDIATION` Action
  Cards without granting `platform.manage` or platform-execution authority.
- Adds a dedicated `SYSTEM_COMPLIANCE` service principal with only
  `compliance.read` and `compliance.propose`.
- Seeds Compliance-only private knowledge with a distinct audience, scope,
  classification, digest, and signature. Platform Admin and Compliance Admin
  runbooks cannot read one another.

## Private knowledge and isolation

- Adds `CX_PLATFORM_KNOWLEDGE`, `CX_PLATFORM_KNOWLEDGE_CHUNKS`,
  `CX_PLATFORM_KNOWLEDGE_GRANTS`, platform commands, maintenance task state,
  safe-autonomy policy, and the database isolation inventory.
- Uses Oracle Data Grants, PostgreSQL dedicated roles plus forced RLS, and
  YashanDB fail-closed table-privilege revocation for platform private data.
- Removes the PostgreSQL client-set `app.current_agent_id` fallback when a
  trusted database-role mapping exists. A spoofed setting no longer changes
  security-critical identity resolution.
- Restricts the Oracle application-context setter so ordinary Agent sessions
  must match the current Deep Data Security End User. The deployment Owner
  remains the only administrative exception.
- Narrows legacy collaboration-group runtime grants and revalidates current
  Security Domain membership for governed Channel resources.
- Adds cross-domain Bridge transfer classification-ceiling checks.
- Adds a source-only private-knowledge projection. Chunk, vector, full-text,
  and Graph projections are reported `UNAVAILABLE` until an equivalent
  adapter predicate exists; no unfiltered fallback is used.
- Extends the LLM management boundary so only `platform.manage` principals can
  list LLM profiles, and API-key ciphertext is never selected by that path.
- Fixes the legacy Portal LLM selector to clear the active Agent database
  context before reading the administrator-allowlisted Portal policy and
  provider secret record, so a Portal session with an assigned Agent no longer
  receives an empty or adapter-specific unavailable list.
- Localizes Portal connection-limit and connection-service failures so a
  Chinese Portal does not display the English identity-policy exception text.
- Fixes Oracle command-registry initialization by avoiding the reserved
  `:mode` bind name, so Administration Channel command completion and
  `/platform HELP` receive the seeded registry.
- Fixes the Dashboard Monitor heading and Platform Operations governance-graph
  route, which previously displayed an Admin Agent title and returned an
  unavailable-service error.
- Clears Channel send feedback automatically instead of leaving it visible
  after completion, ends the visible send state immediately after the durable
  message POST while refreshing Channel details in the background, renders the
  Administration Channel command catalog in a closable dialog, and passes the
  active Portal/Dashboard language so `/platform HELP` returns localized
  Chinese or English content.
- Fixes an `UnboundLocalError` in management Channel dispatch caused by the
  new response-language parameter, which previously surfaced to users as a
  generic operation-incomplete error.
- Reduces Channel send latency by reusing request-local authorization and
  session resolution and by avoiding a redundant Oracle/YashanDB Agent-context
  clear call on ordinary human Dashboard sessions.
- Fixes a stale client-side `feedbackTimerRef` unmount cleanup in the Agents
  view, which could surface while switching Dashboard tabs.
- Returns deterministic `DIRECT_READ` platform commands such as
  `/platform HEALTH_READ` directly from the database control plane instead of
  requiring an LLM Profile and model completion.

## Verification

- Shared source suite: `659 passed, 122 skipped`.
- v4.4.8 Enterprise migrations applied idempotently against Oracle,
  PostgreSQL, and YashanDB baselines.
- Read-only live validators passed for all three Enterprise baselines.
- PostgreSQL strict identity function and Oracle End User context-setter
  boundary are verified by live postflight checks.

This release changes the database contract. Apply migration scripts `48` and,
for PostgreSQL, `49` only through the packaged migration runner with a
recoverable backup-evidence manifest.
