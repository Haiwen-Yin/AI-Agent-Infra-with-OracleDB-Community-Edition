# Changelog

## v4.5.2 - 2026-10-06

- Unify standard A2A and database-mediated DB4A2A admissions on the existing
  database Task Plan root; opaque protocol identifiers remain available for
  interoperability while each new admission has one canonical task link.
- Add durable idempotency, fenced attempt leases, explicit state transitions,
  unknown-send reconciliation and immutable continuity history.
- Bind continuity to exact context/source revisions and classify historical
  DB4A2A dispatches as exact matches or legacy-unmapped records without
  inventing task identity.
- Add additive migration 101 for Oracle, PostgreSQL and YashanDB. PostgreSQL
  retains service-side stable-plan validation because its historical
  LIST(status)-partitioned Task Plans expose only the composite
  `(PLAN_ID, STATUS)` key; Oracle and YashanDB retain their existing stable-ID
  foreign-key constraint.
- Make v4.5.2 successor-schema validation reuse the already applied v4.4.15
  continuity contract, so upgrades do not mistake an unchanged historical
  structure for schema drift.
- Preserve the existing database scheduler, authorization, graph and audit
  authorities; continuity records are a relationship and execution ledger,
  not a second scheduler or in-memory authority store.

## v4.5.1 - 2026-10-06

- Unify database-authoritative capability checks and exact Provider revision probes; share answer-quality evaluation between Portal and Channels.
- Add authorized metadata-first Tool/Skill discovery, source-bound context budgets, durable progress and cancellation diagnostics.
- Complete bounded graph draft import, paginated SLO inspection, checkpoint forks, offline integrity replay and migration preflight.
- Add registered MCP discovery and approved read-only calls, durable metadata-only OTLP delivery, bounded standard A2A tasks and a pinned isolated LangGraph adapter.
- Add managed image/document inputs and explicitly requested read-only diagnostics; preserve live replay, live migration and global autonomy restrictions.
- Improve desktop navigation, channel form sections, searchable Principal selection, responsive Knowledge details, bilingual status labels and the original Chuanxu wordmark.
- Widen Principal dialogs and form selection rows; preserve candidate content height while scrolling so long names, usernames and immutable IDs wrap without overlap.
- Render Principal candidates in an anchored, bounded overlay so opening, paging or refreshing the list does not reflow following form fields; retain keyboard, pagination and exact-ID behavior.
- Add migrations 98–100 without changing previously applied migration digests; migration 100 widens framework rootfs evidence for algorithm-qualified digests; maintain independent Oracle, PostgreSQL and YashanDB COM/ENT packages.
- Resolve the active upgrade version before verifying historical successor migrations, preserving existing handoff structures while rejecting failed or mismatched newer evidence.

## v4.5.0 - 2026-09-27

- Let compound Agent selectors, wrapped labels and expanded textareas determine form height; prevent overlap in containment, external access grants, Channel/Domain membership and Branch forms.
- Keep the desktop navigation clear of the brand and session controls, using a separate navigation row at constrained widths.
- Commit Compliance Controller evaluation and job completion atomically under the persisted lease and fencing token; PostgreSQL completion uses wall-clock time so a lease expiring during the transaction cannot commit posture changes.
- Add owner/token-checked Controller lease renewal, reconcile concurrent scheduling through durable job identity, and commit remediation, audit and notification together with safe repair of missing legacy notices.
- Reject malformed Graph retry policies with diagnostics; replace recursive cycle detection with iterative strongly connected components to handle deep graphs and identify every cycle member.
- Compile one validated Join threshold independent of arrival order, normalize incoming-edge ordering for reproducible plan digests, and reject non-finite timeout/budget values. Existing persisted plans retain their recorded execution contracts.
- Block release approval for unresolved historical contracts or missing, failed, skipped, stale or aggregate-only acceptance evidence.
- Recover Embedding Space validation after a successful provider probe without changing write policy or bindings; reject stale results after a Profile version change and audit the transition.
- Align effective capability checks with database-owned state and authorization, retaining controlled and disabled capability boundaries.
- Reconcile specification indexes and historical changes, and support isolated target dates and manifest outputs during build and release validation.
- Refresh bilingual product captures and website, customer presentation and business-plan materials.
- Preserve the migration chain through 97 and the published v4.4.16 baseline; local acceptance uses isolated Oracle/PostgreSQL/YashanDB Community and Enterprise targets. OCI is excluded.

## v4.4.16 - 2026-09-23

- Require all retained query terms in authorized source titles/content, enforce English word boundaries, escape literal underscores and reject oversized term sets without truncation; summary-only candidates do not suppress model supplementation.
- Preserve complete Chinese retrieval subjects after removing common question wrappers; shared fragments such as “公司” no longer match unrelated Knowledge for “甲骨文公司”.
- Added separate bilingual general-model source notices in Portal and Channels, including authorized historical replies; Channel provenance comes from persisted executions rather than caller or model claims.
- Fixed English conversational filler causing unrelated Knowledge matches, retaining knowledge-first policy, model-disclosure controls and failure handling.
- Added explicit, audited repair of missing Principal identities for idle local Portal Agents without reclaiming occupied Agents or reactivating disabled identities.
- Connected ordinary Channel Business Agent mentions to isolated managed execution and governed Knowledge retrieval with current reader, policy and source revalidation.
- Fixed native Agent provisioning to preserve the requested readable name in the Agent principal and inventory while retaining the generated technical ID.
- Accepted globally unique owner usernames with legacy principal-ID compatibility; Community administrators may approve their own requests, while Enterprise retains separation of duties.
- Added template-aware isolation controls, actionable provisioning errors, and OCI regression/spec coverage.
- Added searchable Human/Agent selection for Channel membership and other operator workflows, preserving Domain admission checks and distinguishing identical display names.
- Fixed v4.4.16 bootstrap-chain selection and verification of unchanged v4.4.15 successor migrations.


## v4.4.15 - 2026-09-16

- Added migration 97 with seven typed native source snapshot relations. Preserve exact Task/Graph/DB4A2A/security-event projections, original-domain authority and immutable history; normalize capture time across native drivers and verify string defaults and numeric precision.
- Added a cooperative Linux Skill runtime client with pinned-key installation verification, process-held turn locks, atomic activation, preserved old versions and recovery after uncertain acknowledgements. Server-side activation remains an authenticated Agent attestation.

- Added migrations 95–96 for immutable native execution/context, Worker attempt and original Gateway credential relationships. Recheck both requester and recipient source authority before model dispatch and result reads; uncertain sends cannot be retried automatically.
- Added shared Dashboard/Portal contextual Agent execution controls and typed Gateway/MCP operations. Corrected nested form placement, continuity field sizing and standalone deployment verification against the selected package version.
- Added per-revision parallel handoff policies in migration 94, coordinator-preserving acknowledgements, shared Portal/Dashboard controls and checksum-bound recovery after interrupted DDL. Expanded post-registration native history-denial checks to the current migration manifests.
- Added recipient-authorized signed Skill downloads and independent client verification. Bound acknowledgements to current server trust and transport digest with atomic audit, retained deferred updates in pending inventory and rejected stale activation reversals.
- Repaired release signing to bind the exact payload manifest without a circular ZIP digest; rejected client-asserted trust, duplicate paths and staged-file tampering. Added operator signing tooling and bilingual guidance.
- Added migration 93 for immutable dynamic Tool request provenance and atomic queue/audit writes. Fixed Oracle reserved bind names, native JSON numeric digests and nested MCP authentication context.
- Enabled continuity scopes through public Agent token exchange and rejected unsupported scopes before instance creation. Added fresh HTTP enrollment/activation and native-login acceptance across all six editions.
- Extended deployment verification to historical execution queue dependencies so terminal migration records cannot mask missing tables or fields.

- Added explicit dynamic MCP exposure controls, filtered independent-Agent discovery, database mutation protection and revocation checks before queuing. Reimport closes exposure. Corrected Tool statistics across all registry groups.
- Added context assembly and exact publication/revocation forms; preserved full retry payloads after uncertain delivery and wrapped long identifiers on mobile screens.

- Added migration 87 for Handoff evidence, instance bindings and credential-use history, bringing continuity to 44 relational tables. Explicit outcome proposals retain exact result sources and remain pending independent review.
- Added migration 88 for immutable native execution links, bringing continuity to 45 relational tables. Resource ownership and permissions are rechecked without coupling links to changing Task status.
- Added Portal continuity with separate session, CSRF and page leases; Work/Handoff historical previews; and four-family candidate editing, independent review and explicit promotion forms. Historical previews never replace the current revision being edited or approved.
- Fixed web asset resolution when a temporary generated-package compatibility symlink is removed while the service remains running.
- Added Dashboard Work continuity forms, participant metadata pagination and domain/recipient selection using current workspace authority. Fixed all three adapters' default MCP tool exposure and verified actual stdio calls with separate registration and Gateway credentials.
- Added migration 86 for 41 continuity entities, native immutable history, current-schema verification and direct Agent SQL denial. Authenticated Gateway routes share resource authorization with session HTTP; typed MCP and CLI clients use instance-bound bearer credentials.
- Added server-persisted CLI diagnostics and authorized capability discovery, preserving UNOBSERVED for unverified entrypoints and unsent context. Fixed instance lease clock alignment and selected-installation postflight paths.
- Prevented PostgreSQL Agent registration from reopening continuity control-plane table grants; native protected-table discovery and independent-login regression cover the post-registration boundary.
- Fixed Portal failed-admission connection leaks, concurrent connection-limit checks, database-timezone-dependent lease expiration, and expired-page takeover. Community login no longer accesses removed LDAP elements.
- Added the database-entity specification for context continuity, Work Contracts, Handoffs, Context Assemblies, candidate review, immutable Revisions, explicit publications, and unified diagnostics.
- Kept the v4.4.14 production contract and migration baseline unchanged while defining the next implementation surface for Oracle, PostgreSQL, and YashanDB.
- Restored journaled v4.4.15 migration execution and strict terminal-step/failed-step deployment verification; aggregate version rows cannot substitute for migration evidence.
- Combined consecutive leading system messages for model-provider compatibility while preserving user roles, instruction order and content-security checks.
- Kept Task Step Graph synchronization on the parent Task Plan's Agent identity and preserved structured tool output; restored task terminal synchronization and completion timestamps.
- Added migration 85: Oracle transactional shadow copying, task-only write fencing, stable-ID HASH partitioning and checkpoint recovery; PostgreSQL deferrable task references and YashanDB stable task references. Six isolated editions passed migration repetition, lifecycle and concurrency tests.
- Locked parent tasks before step insertion, rejected stale status and preserved PostgreSQL identity IDs. Missing YashanDB native clients now have a distinct sanitized preflight diagnostic.
- Extended isolated six-edition acceptance to committed dispatch, rollback, native authorization, standalone Graph Runtime, real-model Channel replies and Portal knowledge responses. Context-continuity implementation and full release acceptance remain incomplete.

## v4.4.14 - 2026-09-13

- Added migration 82 and a database-authoritative model, MCP, A2A, and governed-execution capability registry for Oracle, PostgreSQL, and YashanDB.
- Added normalized provider evidence for structured output, tool calls, usage, timeout, cancellation, retry, and finish state without exposing hidden reasoning content.
- Kept external capabilities fail-closed by default and required trusted source/schema/domain/resource metadata plus Human approval for high-impact governed execution.
- Verified the migration on three existing baselines and six isolated Community/Enterprise targets, including idempotent replay and live Portal/LLM/Agent/Knowledge gates.

## v4.4.13 - 2026-09-08

- Added governed bilingual Portal Knowledge retrieval, Human/Agent authorization intersection, citations, and explicit no-model/no-match behavior.
- Added platform Admin/Compliance Agent management commands, protected Channel mention dispatch, Skill/Tool administration, and content-security checks.
- Added migrations 80-81 for six bilingual product-Knowledge topics and completed cross-database Portal, Agent, and recovery verification.

## v4.4.12 - 2026-09-06

- Repaired YashanDB external-role credential boundaries and native-client loading checks.
- Bound legacy session cookies to the request port, hardened DB4A2A context and branch authorization, and separated cached Agent sessions across concurrent callers.
- Rewrote the six Chinese adapter introductions and added generated-edition README links.

## v4.4.11 - 2026-08-31

- Added verifiable Runtime isolation contracts and DB4A2A database-mediated collaboration.
- Added migration 66 for all three database adapters and corresponding API/test contracts.

## v4.4.10 - 2026-08-27

- Validates all three Enterprise editions from dedicated zero-object targets:
  a new Oracle PDB, PostgreSQL database, and YashanDB PDB each reach migration
  65, native management-Agent bootstrap, scoped Knowledge migration, and
  standalone postflight verification.
- Adds a consolidated PostgreSQL DBA prerequisite and blocking preflight for
  bounded Apache AGE access, graph namespace creation, per-Agent role creation,
  and `ADMIN OPTION` on the shared NOLOGIN runtime role.
- Removes the hidden PostgreSQL superuser-owner dependency: migration 50 seeds
  only after installing a trusted actual-owner policy, and migration 65 closes
  that policy over every forced-RLS table before native handoff while retaining
  Agent-specific RLS.

- Completes the real external-Agent full-capability gate on Oracle,
  PostgreSQL, and YashanDB Enterprise, including Memory Candidate submission,
  Human promotion, Agent-private Knowledge write/read, and company-wide
  publication denial. The redacted combined result contains no reusable
  credential.
- Adds `memory.propose`, `knowledge.read`, and `knowledge.write` Gateway scopes
  and routes. Agent knowledge is owned by the producing Agent, defaults to
  private visibility, and resolves organization scope from the authoritative
  owner hierarchy.
- Adds migration 65 to close external-Agent Security Domain context, including
  forced PostgreSQL Agent-self RLS. Also fixes SSE native timestamp encoding,
  reusable-thread Agent-context cleanup, Oracle bind naming, Oracle/YashanDB
  native timestamp binds, and service-name preservation in external endpoint
  discovery.

- Added direct Oracle `CREATE TRIGGER` to the consolidated owner prerequisite
  and blocking preflight contract, preventing migration 22 from failing after
  partial schema creation with `ORA-01031`.

- Fixed generated-package migration preflight to use the current
  `~/.ai-agent-infra/master.key` resolver instead of directly requiring the
  retired `~/.oracle-infra/master.key` path.
- Fixed withdrawn-schema detection so an applied v4.4.10 fresh-baseline ledger
  is not rejected solely because a retained table also existed in v4.4.8;
  explicit v4.4.8 ledger evidence remains blocked.

- Closes organization application governance end to end: submission creates a
  unique unified approval item; self-decision is denied; approval atomically
  publishes facts, closure, typed history, subtree authority invalidation and
  audit; rejection atomically terminates both records. Migration 60 carries the
  portable database contract.
- Completes the single-administrator organization workflow with low-risk direct
  publication, auditable request withdrawal, actionable separation messages,
  and a reasoned break-glass self-decision reserved for the database-protected
  bootstrap `admin` with dedicated audit evidence.
- Recovers historical orphaned organization submissions through author-only
  audited withdrawal and clarifies child-organization creation with a new
  change-set action and separate child/parent fields.
- Makes unified STEP approval apply its paused-plan effect in the same
  transaction and makes confirmed platform Action Cards recoverable after an
  interrupted command handoff.
- Blocks Oracle initialization unless the active Oracle Home proves that
  Partitioning is enabled, removes three fresh-baseline SQL errors found during
  an Oracle AI Database 26ai deployment, and stops foundational execution at
  the first non-idempotent error instead of producing cascaded ORA output.
- Preserves multi-line Oracle/YashanDB anonymous blocks containing local
  functions and procedures until their SQL*Plus slash terminator, preventing
  governance-lifecycle migrations from being split at an inner `END;`.
- Completes real Oracle Enterprise fresh-install validation through migration
  59, native Agent postflight, `RETIRED`, and `verify`. The runner now preserves
  first-line local subprogram declarations, uses grant-independent SHA-256 for
  Memory adoption, and removes hard-coded `AIADMIN` references from the active
  security-boundary migration.
- Makes Oracle Enterprise preflight verify the complete Deep Data Security
  owner privilege set, creates `admin_data_role` idempotently, and treats an
  absent legacy `AGENT_API` role as an already-revoked boundary only within the
  bounded revoke operation.
- Fixes strict Oracle bind failures in isolation-inventory seeding and final
  deployment-state updates; derived shape and inheritance are retained in one
  normalized inventory field.
- Removes client-side backup manifests from initialization and upgrade.
  Initialization remains restricted to a verified empty target; an existing-
  target upgrade requires interactive `UPGRADE` confirmation, or
  `--confirm-database-backup` for automation, and journals the database-managed,
  not-client-verifiable recovery boundary.
- Makes the first-run LLM model ID explicit and always visible; optional LLM
  setup now requires API URL and model ID to be configured as a pair and pass a
  bounded one-Token model-identity probe before persistence. The probe accepts
  constrained numeric/date alias resolution without accepting arbitrary model
  suffixes.
- Repairs executive-wallboard runtime integrity by seeding one coherent Agent
  population across Principal ownership, organization, registry, Session, Task
  Plan, and Loop records on all three supported databases.
- Distinguishes a successfully queried empty runtime from a failed runtime
  source: failures now return degraded freshness, `partial=true`, bounded source
  status, and unavailable values instead of current-looking zeros.
- Resolves organization-scoped wallboard Agents through their active primary
  Human owners and organization closure, matching the organization governance
  model without creating invalid Agent-as-person memberships.
- Strengthens v4.4.10 full-flow and benchmark gates with non-zero representative
  data and `busy <= online <= total` invariants.
- Makes v4.4.10 the fresh-deployment baseline. Historical migrations remain
  for checksum, ordering, reproducibility, and audit, not as a customer
  in-place upgrade promise; v4.4.8 remains withdrawn.
- Closes the legacy collaboration authorization gap by making Security Domain
  binding and current membership mandatory for execution-group compatibility
  routes; historical groups remain internal compatibility relations only.
- Adds company-public, organization-subtree, organization-level, Human-private,
  and Agent-private Knowledge policies enforced across list, item, graph, and
  retrieval paths.
- Widens Knowledge and Branch detail drawers, makes compact controls responsive,
  and covers all 22 primary management views in the three-database browser gate.

- Completes atomic hard/warn Token and monetary quotas, encrypted exact
  non-streaming replay, and the public correlation/retryability error contract.
- Adds Provider invoice import, append-only reconciliation and correction,
  Enterprise balanced allocation, and governed Ed25519 external evidence.
- Adds immutable allow-listed wallboard definition versions with governed
  publish/rollback while preserving a read-only viewer.
- Adds migration 57, three-database live full-flow evidence, and bounded
  performance tooling; local measurements remain bounded and are not a capacity certification.

- Adds an optional OpenAI-compatible model gateway and immutable usage facts
  for provider-reported Token dimensions, decimal cost, provenance, request
  correlation, and incomplete streaming outcomes without retaining prompts or
  model responses.
- Adds per-LLM-Provider-Profile routing controls. Direct and platform-gateway
  modes may be enabled independently or together; changes require an explicit
  compliance reason and the forwarding address is generated by the platform.
- Adds an authenticated read-only executive wallboard with Agent, Session,
  Task Plan, Loop, and stalled-runtime state plus 14-day Token and cost curves,
  bounded usage detail, coverage, and freshness states.
- Adds equivalent v4.4.10 schema migrations and representative usage data for
  Oracle, PostgreSQL, and YashanDB.

## v4.4.9 - 2026-08-19

- First public release after v4.4.7; v4.4.8 is withdrawn and retained only
  as historical evidence.
- Adds fail-closed v4.4.8 schema detection so v4.4.9 cannot be applied to a
  withdrawn-version database.
- Repairs database identity and row-security boundaries across Oracle,
  PostgreSQL, and YashanDB, including filtered legacy collaboration reads.
- Prevents PostgreSQL Agent provisioning from restoring control-plane table
  grants and resolves SECURITY DEFINER identity from the authenticated login.
- Adds typed Agent and Graph execution evidence, package/source-commit
  integrity checks, incremental Channel delivery, and frontend vendor
  splitting, a dynamic Graph route, and bounded slow-database, long-history,
  and terminal-stream browser gates.
- Restores or reinitializes all validation targets from approved pre-v4.4.8
  baselines and retains publication as an evidence-consistency decision.

## v4.4.8 - 2026-08-18 (withdrawn)

- Added a database-authoritative platform command registry, command
  completion, deterministic help, and governed maintenance-task lifecycle.
- Added deterministic observation proposals and explicit Graph Run binding for
  long-running maintenance without a second execution kernel.
- Kept Compliance Agent proposal-only and isolated Compliance/Admin private
  knowledge by audience, scope, classification, digest, and signature.
- Added platform private knowledge, command, maintenance, safe-autonomy, and
  isolation-inventory migrations for Oracle, PostgreSQL, and YashanDB.
- Enforced Oracle Data Grants, PostgreSQL forced RLS with trusted role mapping,
  and YashanDB fail-closed privilege revocation.
- Restricted Oracle application-context identity to the matching End User and
  removed PostgreSQL custom-GUC identity fallback for mapped runtime roles.
- Added cross-domain classification ceilings, LLM management-boundary checks,
  source-only private-knowledge projection, and focused negative isolation
  tests.
- Verified idempotent v4.4.8 migrations and read-only live validation across
  Oracle, PostgreSQL, and YashanDB Enterprise baselines.

## v4.4.7 - 2026-08-17

- Hardened LLM Provider Profile save, reference-safe logical retirement,
  saved-profile probing, returned-model identity checks, and health writeback.
- Reduced Dashboard startup latency by calculating the complete capability
  manifest from one current authorization snapshot and loading authentication
  and capability data in parallel.
- Standardized configuration panel width, grouping, and spacing across the
  Dashboard. This maintenance release adds no database migration.
- Fixed the protected management Channel's final SSE delta flush so short
  provider responses are delivered incrementally instead of appearing only at
  completion.
- Added private signed management knowledge for the native Agent-template
  workflow, including required security and approval controls and an explicit
  statement of the current template-editing API boundary.
- Added immutable management knowledge v2 with complete Dashboard navigation,
  Business Agent template semantics, and request-language-aligned Chinese or
  English management responses; retained v1 as audit history.
- Stacked the managed Skill / Tool manifest and deployment adapter contract
  panels vertically at full content width.
- Clarified the release maturity boundary: Graph Runtime core and authorized
  inspection are Production Profile capabilities; controlled Graph items and
  protocol/GraphRAG research remain evidence-gated and are not promoted by
  metadata alone.

## v4.4.6 - 2026-08-16

- Added database-authoritative Human registration with configurable display
  name, email, mobile, and one-use Human Registration Token policies.
- Unified Portal and Dashboard registration through an independent
  registration surface while preserving separate Agent Enrollment Tokens.
- Added exclusive Portal operation-page leases and configurable per-user
  connection limits; reused sessions can be inspected but cannot mutate.
- Added provider-neutral external identity transaction and callback contracts
  for future WeCom, DingTalk, Feishu, OIDC, and customer adapters. Claims never
  grant roles or access by themselves.
- Added explicit Graph Engineering capability posture: `PRODUCTION`,
  `CONTROLLED`, `DISABLED`, or `UNAVAILABLE`.
- Added additive identity, Portal, Graph posture, and portable contract
  alignment migrations for Oracle, PostgreSQL, and YashanDB.

## v4.4.5 - 2026-08-15

- Preserved Dashboard child-view state in bounded URL deep links across refresh,
  re-login, direct navigation, and browser history without placing secrets or
  message bodies in URLs.
- Added immutable Graph Run admission contracts for Definition and Plan
  digests, compatibility, State schema, and budget schema versions. A Plan
  from another Graph Version or with a mismatched digest fails closed.
- Governed Agent Card projection by explicit platform Skill grants; protocol
  metadata remains descriptive and cannot grant authority.
- Paused forks before the first Worker claim when replay could reach a
  non-repeatable external effect. Resume requires an approved
  `GRAPH_FORK_REPLAY` decision or bounded compensation evidence.
- Added equivalent additive Graph Run contract migrations for Oracle,
  PostgreSQL, and YashanDB.

## v4.4.4 - 2026-08-14

- Completed the Agent Pool host-node lifecycle: bounded reachability
  verification, one-time bootstrap receipt, dedicated runtime-storage binding,
  administrator activation, and authenticated heartbeat. The bootstrap token
  is displayed once and only its digest is stored.
- Moved Agent Pool Configuration to Platform Operations immediately after
  Admin Agent admission. MaaS, SaaS, and virtualization remain explicit
  deployment-adapter integration boundaries.

- Added administrator-governed Portal Agent Pool LLM defaults and allowlists,
  with a Portal selector restricted to healthy approved profiles.
- Added typed Platform Administration Channel commands, read result cards,
  governed mutation proposals, expiry, and audit records.
- Added managed-node inventory and shared-storage profiles for Admin,
  Compliance, and Agent Pool cloud demonstration nodes. SSH passwords are
  never persisted.
- Added external-Agent database endpoint metadata and five native Agent
  templates for code, Office, and presentation work.
- Added additive v4.4.4 migrations for all three supported databases.

## v4.4.3 - 2026-08-13

- Unified Dashboard inventory paging: task, Memory Library, Skill, Knowledge,
  Spec, Agent, Channel, user, monitoring, approval, audit, and compliance
  inventories now share synchronized controls above and below each list.
  Cursor-backed endpoints return authorized totals so page indicators never
  report an unknown total.
- Added governed Security Domain administration, responsible-owner records,
  explicit Human and Agent membership, lifecycle evidence, and discoverable
  Channel and legacy collaboration-group binding records.
- Added a controlled collaboration-group conversion draft. Existing group
  Agents are candidates only; each membership must be reviewed explicitly
  before an atomic Domain creation and single active group binding.
- Revalidated current Security Domain membership on Channel admission, history
  reads, messages, threads, gateway delivery, and membership changes. A
  Channel, prompt, message, workspace, Skill, Tool, or group relationship
  cannot grant Domain authority.
- Added the additive v4.4.3 migration and release contracts for Oracle AI
  Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4.

## v4.4.2 - 2026-08-13

- Replaced manual platform-wide Embedding assembly with a verified test-and-activate workflow that derives vector dimensions and automatically maintains the Contract, default Space, Binding, and governed migration state.
- Enforced encrypted API-key storage and the platform-wide normalization rule; automated Embedding results are read-only in the standard Dashboard workflow.
- Added the capability-level Graph Production Profile boundary and repaired authenticated Knowledge inventory queries across all adapters.
- Completed form invariants for empty business inputs, external-registration state loading, single-line pagination, and localized protected configuration views.
- Added audited Channel pinning: pinned Channels are prioritized while both
  pinned and ordinary groups remain ordered by their latest persisted activity.

## v4.4.1 - 2026-08-12

- Added the protected Platform Administration Channel, separated Admin Agent
  enrollment paths, weighted count-and-weight quorum, Leader lease, term, and
  fencing evidence.
- Added independent Dashboard and Portal idle/absolute session policies,
  opaque server-side pagination, staged verified upgrade protocol, safe-point
  Skill distribution, and ordered Agent containment evidence.
- Kept infrastructure termination and NFS/object/unified storage explicitly
  adapter-bound; the platform does not claim remote process termination.

## v4.4.0 - 2026-08-11

- Added the native database-backed SDD control plane with structured
  requirements, scenarios, acceptance criteria, tasks, reviews, evidence,
  revisions, immutable approved baselines, amendments and source snapshots.
- Added OpenSpec import/export interoperability. OpenSpec CLI and local
  Markdown are optional after execution-baseline handoff and never control
  task, code, test, review or release state.
- Added governed SDD Graph compilation, risk-driven checkpoints, local/global
  pause, resource leases, isolated execution boundaries and independent
  evidence requirements.
- Added the Software Delivery Profile, hardened delivery roles, local Git and
  GitHub SCM adapter boundary, credential references, protected-branch rules
  and digest-bound artifacts.
- Added the Specifications and Delivery Workbench while retaining compatible
  legacy SPEC API reads and non-destructive retirement.
- Added additive v4.4.0 migrations and static/live validation contracts for
  Oracle AI Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4.

## v4.3.7 - 2026-08-10

- Added a package-local Bootstrap Deployment Agent for checksum-bound,
  resumable initialization, upgrade, status, verification, evidence capture,
  and native management-Agent handoff without an external Agent, Skill runtime,
  `psql`, or LLM-derived execution authority.
- Added database-authoritative Embedding Profiles, immutable Contracts,
  Spaces, bindings, probes, legacy-space isolation, and five execution modes:
  `PLATFORM_MANAGED`, `ENTERPRISE_DIRECT`, `ENTERPRISE_PROXY`,
  `PRECOMPUTED_IMPORT`, and `NONE`.
- Added protected Dashboard deployment/model administration, Agent-side
  compatibility evidence for enterprise-direct use, and a bounded
  lease-protected managed Embedding Worker outside the Dashboard request path.
- Added a first-party PostgreSQL 18 Python deployer that handles package SQL,
  dollar-quoted routines and `COPY` data without requiring `psql` or `pg_cron`.

## v4.3.6 - 2026-08-07

- Added database-authoritative platform-native Agent bootstrap. Platform Admin
  Agent is created by the software without requiring an external Agent;
  Enterprise editions additionally provision the governed Compliance Admin
  Agent while keeping both identities separate from the human `admin` user.
- Added LLM Provider Profiles with encrypted API-key envelopes, built-in and
  sensitive-domain Agent templates, activation prerequisites, and a reference
  local Runtime Worker with lease-fenced execution records.
- Added governed business Agent requests, separation-of-duties approval,
  restricted identity provisioning, runtime isolation levels, and deployment
  target/adapter contracts for customer-specific infrastructure integration.
- Added `external_agent_registration` policy control with disabled,
  approval-only, and enabled states. It controls only new external
  Skill-first enrollment and does not alter existing or platform-created Agents.
- Added additive v4.3.6 migration contracts for Oracle AI Database 26ai,
  PostgreSQL 18, and YashanDB 23.5.4 across Community and Enterprise editions.

## v4.3.5 - 2026-08-05

- Added database-authoritative Platform Capability Configuration for selecting
  the enabled product surface per installation. Mandatory identity,
  authorization, security, audit-writing, Agent, user, and configuration
  boundaries remain protected.
- Added dependency-aware capability switches, optimistic concurrency,
  reason-required changes, immutable history, and transactionally coupled
  security audit records across Oracle AI Database 26ai, PostgreSQL 18, and
  YashanDB 23.5.4.
- Added backend enforcement for disabled capabilities and a bilingual
  protected Dashboard configuration page. Package capabilities remain bounded
  by the Community/Enterprise build boundary.
- Hardened cross-Admin Skill acquisition so the admin token is sent in a
  request header, and rejected unsafe Oracle End User identifiers before DDL.

## v4.3.4 - 2026-08-04

- Added Enterprise Agent Compliance Posture, credential-proven Gateway
  activation, governed Profile templates, bounded evidence, deterministic
  findings, remediation, exceptions, controls, Controller diagnostics, and
  Gateway/MCP integration.
- Added the additive v4.3.4 compliance migration and live-schema validator
  contract for Oracle AI Database 26ai, PostgreSQL 18, and YashanDB 23.5.4.
- Corrected identity and Gateway expiry clock handling for databases using
  local naive `TIMESTAMP` values, and aligned Gateway Client Secret lookup
  with the registration credential digest contract.

## v4.3.3 - 2026-08-03

- Added Graph Runtime assurance evidence, bounded test-only failpoints, and
  selected invariant scans around database-authoritative Graph recovery.
- Added canonical Graph Definition supply-chain envelopes with dependency
  locks, Ed25519 verification, import scanning, provenance, and untrusted Draft
  publication gates.
- Added disabled-by-default Dynamic Graph, A2A 1.0.1, and OpenTelemetry GenAI
  preview boundaries. They reuse existing authorization and Graph Runtime
  authority rather than adding a second execution engine.
- Local Agent Runtime recovery evidence is distinct from database HA: this
  release does not claim database-cluster failover, RPO/RTO,
  independent A2A conformance, or real OTLP Collector delivery.

## v4.3.2 - 2026-08-01

- Added governed, versioned Memory Families, immutable Versions, current-version
  compatibility, representations, typed relations, snapshots, candidates,
  reviews, durable jobs, usage evidence, and bounded relationship traversal.
- Replaced routine destructive memory deletion with reasoned logical
  unavailability while retaining authorized lineage and audit evidence.
- Added the independent, checksum-preserving memory digest-alignment migration
  so legacy installations can adopt SHA-256 without rewriting step 23 history.

## v4.3.1 - 2026-07-31

- Added database-authoritative graphical organization governance, canonical
  memberships and reporting, organization versions/history, semantic change
  sets, directory staging, closure-backed authorization, and the Organization
  Dashboard workspace across all database adapters and editions.
- Added reasoned Portal-only or Portal-and-App admission in User Management,
  enforced at login and per request, and protected the bootstrap `admin`
  Principal's App admission and `SYSTEM_ADMIN` assignment from removal.

All notable changes to the AI Agent Infra unified repository are documented in
this file. Each released edition (Oracle/PG/YashanDB × Community/Enterprise)
inherits the entries below; per-edition release notes live in
`RELEASE_NOTES_v<VERSION>.md` shipped with each build.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the rules in `openspec/specs/documentation-format/spec.md`.

The released technical packages are distributions of **Chuanxu (川序)**, the
**AI Agent Management Platform**. `AI Agent Infra with DB` remains the unified
technical project name.

## [4.3.0] - 2026-07-29

See `shared/RELEASE_NOTES_v4.3.0.md` for the integrated release contract. The
internal v4.2.1 Graph closure is included in v4.3.0 and is not a separate
public archive.

- Added database-backed Human and Agent Principals, registration approval,
  permissions, scopes, one-time Agent Enrollment Tokens, Channels, Barriers,
  and node-isolated Agent Gateway recovery.
- Integrated Graph Engineering runtime, durable execution, event delivery,
  evidence, retry, fencing, and v4.1 compatibility into one shared code line.
- v4.3.0 Production Profile is the current production recommendation. The
  v4.1.x line remains available as the compatibility baseline and receives
  only critical security or data-loss fixes.
- Added multi-platform offline wheel selection. `cryptography==49.0.0` may
  ship with a source-built `manylinux_2_28` RHEL 8 wheel alongside the
  upstream `manylinux_2_34` wheel for newer systems.
- Added release-time wheel integrity checks for METADATA identity,
  Requires-Python, platform tags, and dist-info/RECORD hashes; the default
  build now fails closed when the offline dependency closure is incomplete.
- Documented the PostgreSQL Schema Owner prerequisites for provisioning
  independent Business Agent LOGIN roles without widening runtime privileges.
- Fixed PostgreSQL Graph traversal predicates for legacy text edge endpoints:
  numeric entity IDs and historical values such as `PG_AGENT_001` now share a
  text comparison boundary, so invalid numeric casts cannot abort Graph
  queries while valid numeric edges continue to resolve.
- Redirected the legacy Dashboard login route to the Principal-aware
  application shell so authentication cannot fall into a legacy
  password-session loop.
- Changed MFA enforcement to an explicit User Management policy. Administrator
  roles no longer force MFA before the first Dashboard login, while enabling
  enforcement requires an already confirmed factor and revokes existing
  Sessions.
- Fixed Portal SSE buffering across both the FastAPI compatibility bridge and
  the upstream LLM reader; token chunks now remain incremental end to end.
- Fixed unrestricted user-list and Principal-visibility queries on Oracle and
  YashanDB by omitting bind values that are absent after `ALL`-scope SQL
  simplification.
- Changed Dashboard page navigation to SPA history transitions and a persistent
  header containing the slogan, theme/language controls, logout, and the real
  database Session countdown; added animated global and local loading states.
- Restored Knowledge, Memory, and Graph Explorer network visualization,
  operational Agent Monitor data and metrics, and the principal Skill, Branch,
  and Loop administration actions in the React application.
- Fixed administrator-wide Agent and Barrier visibility while retaining scoped
  access for non-administrators, and removed large-value `DISTINCT` queries
  that failed on Oracle and YashanDB.
- Fixed FastAPI compatibility Session-cookie port selection for PostgreSQL and
  YashanDB editions and added generated-asset Dashboard regression coverage.
- Added list/Graph view switching for Knowledge and Memory, deterministic
  per-Branch detail graphs, focused Graph Explorer subviews, existing Skill
  resource and metadata controls, and complete Loop run controls in the React
  Dashboard.
- Renamed the Graph data surface to entity relationships, retained returned
  edge endpoints, covered every persisted entity type, and added node and
  relationship filters with edge counts.
- Added Channel creation and `SYSTEM_ADMIN` all-Channel inventory while keeping
  private thread participation explicit; restored legacy collaboration-group
  data as a separate compatibility view.
- Split Channel chat from Channel administration and localized browser file
  selection plus remaining visible Chinese-mode technical labels.
- Fixed approval and audit adapter field mappings, animated database loading,
  and click-outside/Escape detail dismissal.
- Fixed approval creation against early YashanDB databases that retain the
  required legacy `APPROVAL_TYPE` column.
- Changed Web Session expiry to a five-minute sliding inactivity lease and
  made existing legacy `ADMIN` adoption idempotently assign `SYSTEM_ADMIN`.

## [4.0.1] - 2026-07-22

### Security And Identity

- Added versioned AES-256-GCM configuration envelopes, authenticated metadata,
  explicit legacy migration, key rotation, and restrictive master-key files.
- Extended encrypted-at-rest configuration to `security.secret_key`, enforced
  owner-only (`0600`) runtime config permissions on every startup, and masked
  signing secrets in verification output.
- Added centralized HTTP session, role, and route authorization. Unknown API
  routes require authentication; administrative and side-effect routes enforce
  stronger policies.
- Business Agents now fail closed with independent database identities: Oracle
  End Users, PostgreSQL LOGIN roles with RLS identity, and YashanDB users.
  Schema-owner credential fallback is prohibited.

### Runtime

- Added durable execution jobs, attempts, leases, retries, cancellation,
  approval decisions, bounded command execution, audit rows, and outbound URL
  validation across redirects and DNS results.
- Skill ZIP ingestion now preserves complete `SKILL.md` content and nested
  resources, rejects unsafe archives, stores immutable package/file hashes,
  exposes HTTP and MCP acquisition, and materializes verified read-only trees.
- Completed shared Graph API behavior and removed database-specific SQL from
  shared runtime paths covered by the compatibility gate.
- Added persisted Portal node ownership. Exit returns the current Agent to the
  Pool, startup reclaims only the current Admin node's assignments, and
  concurrent Admin nodes cannot claim the same Pool Agent.

### Packaging And Release

- Community packages physically exclude five Enterprise feature groups;
  Enterprise manifests include approvals, audit, LDAP, Skill Token, and
  orchestrator modules under BSL-1.1.
- Added three-database migration ledger, capability probes, an 18-target
  edition/mode matrix, reproducible archives, secret scanning, and executable
  release evidence.
- Added a reproducible `cl100k_base` prompt-input benchmark. Its result compares
  full-file context with SQLite FTS5 Top-K retrieval and does not claim latency
  or answer-quality improvement.
- Release-package tests now exclude source-only harnesses and execute without
  depending on the unified `shared/` or `adapters/` source directories.
- Completed live regression of all six generated packages against Oracle,
  PostgreSQL, and YashanDB, including cross-database ID and SQL dialect paths.
- Final post-migration regression ran 141 passing tests in each of the six
  packages; the three conditionally skipped live contracts were then supplied
  explicit encrypted configs and passed once per database.
- Corrected generated Skill/introduction release metadata and website metrics,
  made `RELEASE_DATE` authoritative, and isolated pool lifecycle tests so they
  always return their own claimed Agent.

### Web Console

- Standardized compact sidebar spacing across every Dashboard page.
- Removed Bootstrap globals from Audit and replaced them with native tabs,
  responsive statistics, and table layout at the shared Dashboard scale.
- Corrected PostgreSQL Monitor session-duration calculations and added metric
  sample counts with explicit no-sample rendering.
- Corrected the React Monitor overview to render nested Agent, Session, Task,
  and stalled-Agent metrics from all database adapters, and added a dedicated
  controlled experimental-profile view. Performance metrics and the Agent
  inventory remain exclusive to the runtime overview.
- Removed the duplicate compatibility theme control from React pages and
  renamed the user-facing Barrier concept to Collaboration gate while keeping
  API and persistence identifiers compatible.
- Moved the three product pillars into the header brand lockup, restored the
  React database-loader animation, and removed Workspace-list N+1 detail
  loading through a backward-compatible summary mode.

## [4.0.0] - 2026-07-19

### Summary

Ground-up restructure of AI Agent Infra from six independent per-edition
repositories into a single unified source tree that generates all six release
editions (Oracle / PostgreSQL / YashanDB, each in Community and Enterprise
tiers) via one build script. This release introduces the adapter-overlay
layout, a single `VERSION` source of truth, a shared OpenSpec store, and a
spec-driven validator that gates releases on the OpenSpec contracts.

### Added

- **Unified repository layout** (`shared/` + `adapters/<db>/`) replacing six
  divergent per-edition trees.
- **`build.py`** — generates `build_output/<edition>/` plus a release zip per
  edition, overlays adapter code on top of shared code, injects the version
  string, and emits per-edition `config.json` / `requirements.txt`.
- **`VERSION`** as the single source of truth for the version string, read by
  `build.py` and `spec_validator.py`.
- **`editions/*.json`** — six per-edition configuration files driving
  `build.py` (license, web port, DB connection, `extra_features`).
- **`spec_validator.py`** — validates each built edition against the OpenSpec
  specs (required files, minimum test counts, API endpoint surface); supports
  `--edition`, `--live --base-url`, and `--json` modes.
- **`openspec/config.yaml`** pointing at the shared store at
  `/root/AI-Agent-Infra-Specs`.
- **`shared/tests/conftest.py`** — pytest parameterization over
  `oracle` / `pg` / `yashandb` with auto-skip of unreachable backends and
  environment-variable overrides (`AIAGENT_TEST_DB`, `AIAGENT_SKIP_DB`,
  `AIAGENT_*_DSN` / `_HOST` / `_USER` / `_PASSWORD`).
- **`shared/docs/AGENTS.md`** — guide for the unified repo covering the build
  system, version management, edition configs, OpenSpec store, and test
  infrastructure.
- **`shared/README_TEMPLATE.md`** — per-edition README template consumed by
  `build.py`.
- **OpenSpec store** with four initial specs: `api-contract`,
  `database-adaptation`, `documentation-format`, `test-requirements`.

### Changed

- **Build pipeline**: releases now produced by `python3.14 build.py` from one
  source tree, replacing the prior per-edition copy-and-patch workflow.
- **Version injection**: `build.py:inject_version()` rewrites `VERSION = "..."`
  in Python and `vX.Y.Z` literals in `.py`/`.sql`/`.md`/`.html`/`.sh` for
  every file in each built edition; no source file may hardcode a version.
- **Directory shape of built editions**: loose `.py`/`.sh` files and `lib/`,
  `tests/`, `tools/`, `visualization/` subdirectories now live under
  `scripts/` in every built edition.
- **`config.py`**: each edition now derives from `adapters/<db>/config_db.py`
  instead of carrying its own copy.
- **Test runner**: `pytest` is now the canonical runner via the parameterized
  `conftest.py`; the legacy `test_all.py` master runner remains for
  non-pytest environments.

### Fixed

- Eliminated cross-edition drift in shared business logic (loop_api,
  memory_api, graph_api, etc.) — there is now exactly one copy in `shared/lib/`.
- Eliminated version-string skew across files within an edition — every build
  rewrites all of them from `VERSION`.
- Eliminated the "forgot YashanDB" class of release mistakes by building all
  six editions from one command and validating them against one spec set.

### Notes

- **Minimum test counts** per edition (from `test-requirements/spec.md`):
  Oracle COM/ENT 121, PG COM/ENT 103, YashanDB COM 109 / ENT 113.
- **API contract**: all editions must serve the common endpoints listed in
  `api-contract/spec.md`; Enterprise editions additionally serve
  `/api/admin/crypto/rotate`, `/api/approvals`, `/api/audit`.
- **Database drivers**: Oracle uses `oracledb>=4.0.1`, PG uses
  `psycopg2-binary>=2.9`, YashanDB uses `yaspy>=1.2.1`.
