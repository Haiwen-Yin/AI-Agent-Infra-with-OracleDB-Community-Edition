# AI Agent Infra v4.4.10

## Fresh Initialization Closure

- Oracle, PostgreSQL, and YashanDB Enterprise were initialized on dedicated
  empty PDB/database targets through migration 65 and independently passed
  native bootstrap and `verify` on 2026-08-27.
- PostgreSQL now ships one DBA prerequisite for AGE graph access and isolated
  Agent role administration; preflight blocks incomplete grants before DDL.
- PostgreSQL no longer depends on a superuser Schema Owner to bypass forced
  RLS. Trusted policies are scoped to each table's actual Owner and are closed
  before bootstrap audit writes; Business Agent roles retain explicit RLS.

## External Agent Full-Capability Closure

- Oracle, PostgreSQL, and YashanDB Enterprise pass one real-database external
  Agent gate covering enrollment, identity, Gateway, Channel/Event/SSE,
  compliance, Embedding, model forwarding, containment, and negative access
  paths.
- External Agents can submit Channel Memory Candidates; only an authorized
  Human can promote them to durable Memory Artifacts.
- External Agents can create and read Agent-private Knowledge with explicit
  `knowledge.write` and `knowledge.read` scopes. Organization sharing follows
  the Human owner's authoritative organization chain; direct company-wide
  publication by an Agent is denied.
- Migration 65 closes external-Agent Security Domain context and PostgreSQL
  Agent-self forced RLS. Gateway request context is cleared in `finally`, SSE
  encodes native database values before streaming, Oracle/YashanDB use native
  timestamp binds, and external Oracle-compatible endpoints preserve the
  initialized service name.

## Approval And Organization Closure

- Organization submission creates one durable unified approval item. The
  ordinary requester cannot approve or reject their own change. Approval rows
  now explain this separation before an action is attempted.
- The database-protected bootstrap `admin` can perform a reasoned emergency
  self-decision, with dedicated audit evidence; ordinary `SYSTEM_ADMIN` users
  do not receive this break-glass exception.
- Validated low-risk changes can be published directly, and an author can
  atomically withdraw a pending request back to `VALIDATED`.
- Author-only withdrawal now repairs pre-closure orphaned pending changes with
  dedicated audit evidence. The organization editor adds a new-change-set
  action and explicit child ID, parent, name, code, and type fields.
- Approval atomically applies semantic organization operations, closure,
  immutable typed history, subtree permission and Token invalidation, terminal
  states, and audit evidence. Rejection atomically closes both records.
- Migration 60 extends the portable approval entity contract and immutable
  Agent-relationship history on Oracle, PostgreSQL, and YashanDB.
- Unified STEP decisions now change the paused execution plan in the same
  transaction. Confirmed platform Action Cards can resume an interrupted
  command handoff, while proposal-only commands end as confirmed proposals.

## Execution-Group Boundary Closure

- Legacy collaboration groups remain historical Agent execution records, not
  authorization boundaries. External compatibility reads now use
  `execution-group-scope/v1` and require an active Security Domain binding and
  current Domain membership.
- Branch inspection, plan distribution, context synchronization, and
  collaboration Loop creation re-check execution-group scope. An Agent must be
  an active member of the group; `SHARING_POLICY` never grants access.

## Product Surface And Session Behavior

- The standalone Collaboration Dashboard destination and new collaboration-
  group workflow are removed. Security Domains and Channels are the customer-
  facing collaboration model; legacy group records remain only for controlled
  execution compatibility and audit history.
- Branches remain a first-class engineering surface. Branch detail projects
  Workspace, parent/child lineage, source Context, executing Agent, and
  lifecycle evidence for graph-based traceability.
- Session expiry now returns directly to the login screen. Only an explicit
  user sign-out opens the confirmation dialog; automatic timeout never asks for
  confirmation. Session cookie suffixes use the actual request port so custom
  listener ports remain consistent across FastAPI and compatibility APIs.

v4.4.10 is the fresh-deployment baseline for governed model usage,
organization-aware knowledge, and an authenticated executive wallboard.
Historical migrations remain for reproducibility; earlier v4.4.x packages are
not presented as customer upgrade sources. v4.4.8 remains withdrawn.

The final deployment gate also unifies encrypted migration configuration with
the runtime master-key resolver and recognizes an applied v4.4.10 baseline
before using withdrawn-version object-shape fallback. Explicit v4.4.8 journal
evidence remains a hard block.

The first-run configuration wizard now prompts for the Web listen address and
port, preserves each package's defaults, validates the port range, and prints
the resolved binding after writing the configuration. It always displays the
LLM model ID field and requires the optional LLM API URL and model ID to be
configured together. When configured, the wizard performs a bounded one-Token
completion probe and persists the values only when the provider returns the
same model identity. Provider namespaces and bounded numeric/date alias
resolutions are accepted, including `deepseek-v4-flash` resolving to
`deepseek-v4-flash-0731`; arbitrary suffixes remain rejected.

Fresh initialization does not require a backup-evidence file on the client.
It proceeds only after strict empty-target verification and records
`DATABASE_MANAGED`, `NO_PREEXISTING_PLATFORM_DATA`, and
`VERIFIED_EMPTY_TARGET`; database backup policy remains the database
operator's responsibility. Existing-target upgrades require an explicit
interactive confirmation, or `--confirm-database-backup` for automation. The
confirmation is journaled as `DATABASE_MANAGED` and
`NOT_CLIENT_VERIFIABLE`; the client does not claim to verify database-native
backup state.

## Model Gateway And Accounting

- Adds OpenAI-compatible non-streaming and streaming model forwarding.
- Records provider-reported Token usage, incomplete usage, pricing snapshots,
  decimal cost, request correlation, and authorized aggregate summaries.
- Keeps provider credentials server-side and does not retain prompts or model
  responses in the usage ledger.
- Adds hashed gateway credentials and revocation support.

## Optional Routing

Gateway routing is configurable on each LLM Provider Profile. Direct and
platform-gateway modes are independent and may be enabled together. Existing
profiles remain direct-capable by default; enabling the gateway for one profile
does not force every Agent through it. A routing change requires an explicit
confirmation and compliance reason.

The forwarding address is generated by the running platform and displayed
read-only. Set `CX_PUBLIC_BASE_URL` when the externally reachable scheme, host,
or reverse-proxy prefix differs from the request URL. Direct activity remains
unobserved unless verified usage evidence is supplied.

## Executive Wallboard

- Adds authenticated `/app/wallboard` and read-only aggregate API access.
- Shows Agent inventory and online/busy/stalled state, active Sessions, running
  Task Plans and Loops, 14-day Token and cost curves, bounded model usage,
  coverage, freshness, stale, and error states.
- Uses one registered-Agent population for total, online, and busy metrics;
  platform-native Agent counts remain a separate breakdown.
- Uses the Agent's active primary Human owner and organization closure for
  organization-scoped definitions; Agents are not inserted as organization
  people merely to satisfy an aggregate.
- Returns `partial=true`, degraded freshness, a bounded runtime source code,
  and unavailable values when runtime aggregation fails. A successful empty
  query remains a current response containing real zeros.
- Wallboard reads do not acknowledge, approve, export, configure, or invoke
  platform operations.

The packaged Enterprise demo-data utility creates coherent non-zero wallboard
facts across identity, registry, Sessions, Task Plans, and Loops. Release flows
for all three databases assert `busy <= online <= total` and require
representative active runtime data; field deployments are not required to keep
demo data.

## Database And Release

- Adds journaled v4.4.10 migrations for Oracle AI Database, PostgreSQL, and
  YashanDB.
- Oracle preflight now requires direct Owner grants on `SYS.DBMS_CRYPTO` and
  `SYS.UTL_HTTP`. The Enterprise base manifest executes the Deep Data Security
  policy automatically, initializes database-local crypto keys, applies the
  hardened context setter afterward, and refuses READY when executable PL/SQL,
  crypto, Agent context, or Data Grant postflight is incomplete.
- Preserves repaired database-authoritative security boundaries while making
  v4.4.10 the new-install baseline; v4.4.8 remains withdrawn.
- All six packages must be built with Python 3.14 and verified against the
  supported migration and packaging gates.

## Complete Governance Closure

- Adds atomic hard and warn-only Token/monetary quotas, bounded encrypted
  non-streaming replay, and a uniform correlation/retryability error contract.
- Adds idempotent provider invoices, append-only corrections and
  reconciliations, Enterprise balanced chargeback, and signed external model
  evidence with key rotation and revocation.
- Adds allow-listed immutable wallboard definition versions with governed
  publication and rollback while preserving a mutation-free viewer.
- Migration 57 completes the new governance objects. PostgreSQL forces RLS on
  every new table. Oracle, PostgreSQL, and YashanDB live flows are verified with
  Python 3.14; local performance evidence remains bounded and is not a capacity
  certification.

## Organization-aware Knowledge And Product Reliability

- Knowledge policies support company-public, organization-subtree,
  organization-level, and Human/Agent-private visibility. Organization closure
  is evaluated at read time for list, item, graph, and retrieval paths.
- Security Domains and Channels remain the customer-facing collaboration and
  authorization model. Legacy collaboration groups are compatibility execution
  records and never grant knowledge or resource scope.
- Knowledge and other governed record details use responsive drawers: 960 CSS
  pixels on wide desktop where required and a bounded single-column treatment
  on narrow screens. Browser gates verify every operation control remains
  inside the drawer on Oracle, PostgreSQL, and YashanDB.
- Agent-created knowledge records the current organization chain, responsible
  groups, execution groups, selected sharing scope, and graph snapshot digest
  in `CX_KNOWLEDGE_CONTEXTS`. The Graph view exposes this context for
  explanation only; group membership never grants authorization.

## User-management and graph UI refinement

- The entity relationship view now renders topology without unreadable edge
  descriptions or a duplicate relationship-detail table.
- User Management's effective-access simulator uses an explicit localized
  action picker. It evaluates one selected action read-only and never changes
  roles or permissions; the action list shows Chinese, English, and stable
  action codes.
