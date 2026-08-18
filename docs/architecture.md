# Architecture - AI Agent Infra with DB v4.4.8

## v4.4.8 Platform Control Plane

The Administration Channel resolves command discovery from the database
registry `CX_PLATFORM_COMMANDS`; the frontend does not own an independent
command catalog. Maintenance work uses `CX_PLATFORM_MAINTENANCE_TASKS` and
attempts with leases, fencing, postflight, and evidence. Long-running work may
bind `GRAPH_RUN_ID` so the existing Graph Run admission and recovery contract
remains the only durable execution contract.

Compliance remains a proposal-only control plane. `SYSTEM_COMPLIANCE` has only
`compliance.read` and `compliance.propose`; `SYSTEM_COMPLIANCE_ADMIN_AGENT`
creates remediation cases and `PLATFORM_COMPLIANCE_REMEDIATION` Action Cards
without `platform.manage`. Platform and Compliance private runbooks use
different audience, scope, classification, digest, and signature records.

## v4.4.3 Governed Collaboration Boundary

The collaboration hierarchy is **Security Domain -> Channel -> collaboration
group**. The Security Domain is the durable zero-trust authorization and data
boundary. Channels provide attributable Human/Agent conversation within that
boundary. Legacy collaboration groups remain task-coordination records for
Agents, branches, SDD, and workspaces. Their relationship to a Security Domain
is an explicit, auditable binding, never an authorization shortcut.

A conversion draft snapshots an existing group's review context and lists its
active Agents as pending candidates. It does not change `CX_DOMAIN_MEMBERS`.
Applying a reviewed draft validates its accountable Human owner, creates the
new Domain, writes only confirmed members, and creates one active group binding
in one transaction. Runtime authorization continues to resolve current Domain
membership, so a later suspension or revocation closes future Channel and
Gateway access without rewriting retained collaboration history.

## v4.4.1 Platform Administration And Availability Plane

The Platform Administration Channel is a restricted system Channel for the
protected local administrator, enabled platform management Agents, and only
approved Admin Agents. Ordinary production Agents cannot create an instance,
join, read events, use private/direct threads, or send free-form management
messages in this Channel. Management conversation is advisory context only;
every state change remains a structured, authorized, auditable database action.

Admin Agent membership has two separate admission paths: a platform-deployed
candidate using the Platform Admin template and an externally deployed Admin
candidate with an independent package and Ed25519 public-key proof. Both pass
candidate observation and separated human approval before voting or Channel
membership. The group records distinct positive weights, count-and-weight
majority snapshots, deterministic succession, Leader terms, a database lease,
and fencing tokens. A stale Leader cannot commit after replacement.

The controlled upgrade plane stores package digest/signature state, human and
Admin Agent approval evidence, node drain/migration/health state, and Skill
distribution acknowledgements. The deployment adapter or node performs the
actual maintenance action only after the database plan enters its permitted
state. An Agent retains its old Skill snapshot until it declares a safe point;
failed or unreachable recipients remain explicitly marked as drift.

Managed-node lifecycle is database-authoritative. Retirement is a logical
state transition that removes a node or LLM profile from active inventory
while retaining history and evidence. The protected Channel can create an
approved drain plan: the source stops accepting new claims, expired retryable
work may move to an active destination, and running work is left to finish.
This operational drain is not incident containment and never force-kills
active tasks.

## v4.4.0 Governed Software Delivery Graph

The v4.4.0 control plane stores structured SDD Changes, Requirements,
Scenarios, Acceptance Criteria, Tasks, Reviews, Evidence, Resource Leases,
Run Nodes, Amendments and immutable Approved Baselines in the database.
Relational facts are authorization truth; the existing Graph Runtime is the
execution projection and is compiled from an approved baseline.

OpenSpec is an optional authoring interoperability boundary. Chuanxu preserves
an immutable source snapshot, normalizes the content, blocks unresolved
security/interface/data/migration fragments, and then executes from database
state. OpenSpec CLI and local Markdown are not required after handoff.

The Software Delivery Profile uses registered, hardened roles and minimum
context projections. Workers claim isolated worktrees, branches, containers or
customer-equivalent resources with short-lived fencing leases. SCM credentials
remain references to a controlled provider. Artifact digest changes make
dependent evidence stale, and an Agent completion claim is never sufficient
for independent acceptance.

## v4.3.7 Bootstrap And Embedding Governance Plane

For a prepared target, the package-local Bootstrap Deployment Agent validates
the checksum-bound manifest, persists sanitized run, step, evidence, and lease
facts, and executes only package SQL. It never turns LLM output into SQL,
shell, privilege, manifest, or state authority. After the identity plane
exists, it creates an attributable temporary Principal, hands off to protected
human `admin`, Platform Admin Agent, and (Enterprise only) Compliance Admin
Agent identities, releases the lease, and retires.

Embedding Profiles describe provider and model identity while immutable
Contracts freeze dimension, metric, normalization, preprocessing, modalities,
and source mode. Logical Spaces and scoped Bindings select the only compatible
contract for vector writes and retrieval. `PLATFORM_MANAGED`,
`ENTERPRISE_DIRECT`, `ENTERPRISE_PROXY`, `PRECOMPUTED_IMPORT`, and `NONE` are
explicit modes. Legacy vectors remain isolated in read-only `LEGACY_DEFAULT`.
Managed bulk work is claimed outside HTTP requests by a leased, fenced worker.

## v4.3.6 Native Provisioning Plane

The v4.3.6 plane is: Human request -> approval -> Agent Principal ->
DeploymentTarget -> isolated execution -> database evidence. Platform Admin
and Enterprise Compliance Admin are seeded by software bootstrap; external
Skill-first Agents remain a separate admission source. LLM Provider Profiles
are versioned database records with encrypted optional keys and redacted reads.
Reference adapters define customer integration without importing vendor
authority into the platform. The database remains the source of truth for
identity, ownership, status, lease, fencing, audit, and recovery.

## v4.3.3 Trustworthy Runtime Extensions

The v4.3.3 extension adds supporting relational records around the existing
database-authoritative Graph execution plane: `GRAPH_ASSURANCE_EVIDENCE`, Graph
Definition provenance/dependency/signature/scan records, immutable Dynamic
Graph proposals, A2A Task-to-Run mappings, and redacted telemetry delivery
metadata. None replaces Graph Runs, Attempts, State Events, Checkpoints,
Transitions, Trace, Audit, or governance as the authority for execution.

The assurance layer observes recovery through database lease and fencing facts
and detects selected integrity anomalies. It supports replacing application
processes while the database remains reachable. Database replication, standby
promotion, and failover stay outside the application contract. Dynamic Graph,
A2A, and OpenTelemetry are isolated, disabled-by-default preview adapters;
they share identity and authorization checks but cannot create a second
execution kernel or authorization channel.

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## v4.3.0 Core Control Planes

The database is the durable source of truth for entities, knowledge, memory,
tasks, complete Skill packages, Agent identity mappings, execution policy,
approvals, attempts, leases, results, and audit records. The web process
authenticates and queues side effects; workers claim durable jobs and perform
bounded execution outside the request thread.

Core behavior is equivalent across Oracle AI Database, PostgreSQL, and
YashanDB, while native SQL, graph/search facilities, migrations, and identity
provisioning remain in adapters. Community and Enterprise are build-time
allowlists rather than runtime branding flags.

Each Business Agent has an independent database identity and cannot use the
schema owner: Oracle End User plus Data Grants, PostgreSQL LOGIN role plus RLS
identity, or YashanDB user plus object grants. The authenticated request Agent
must match the configured database identity, otherwise access fails closed.

Execution jobs progress through approval, pending, running, retry, and terminal
states. Claims use a lease token; completion is accepted only for the active
lease. At-least-once delivery is paired with idempotency keys. URL validation
and command policy are applied before a worker performs a side effect.

Skill ZIP files are parsed into immutable package versions. `SKILL.md` and all
normalized nested files retain hashes; acquisition verifies visibility and
integrity before creating a read-only materialized tree.

The release package is a Skill-first, framework-neutral integration boundary.
Any Agent runtime that can consume `SKILL.md` and execute the packaged HTTP,
MCP, or CLI workflows can use the platform; OpenClaw and Hermes Agent are
confirmed examples. Such runtimes are managed only after registration and
authentication. Skill compatibility does not provide automatic discovery of
unregistered Agents or control calls that bypass the platform.

## v4.3.0 Governance Plane

The registered-Agent boundary is common to Community and Enterprise. An Agent
hosted by this project or an external runtime using `SKILL.md` must first have
an active registration and authenticate with its issued credential. Unknown,
disabled, revoked, expired, or credential-mismatched identities fail closed.
The registration record keeps owner, runtime, environment, node, capabilities,
credential version, status, expiry, and last-seen metadata; it never returns a
stored credential digest.

Enterprise adds a durable governance plane for `DATABASE_DATA`, `API`,
`SKILL`, `TOOL`, `KNOWLEDGE`, `WORKSPACE`, and `DATA_EXTRACT` resources. The
resource catalog is authoritative for classification. A request-side
classification cannot downgrade a catalog resource, and sensitive, restricted,
or unknown resources require an explicit matching policy. Decisions are
`ALLOW`, `DENY`, or `APPROVAL_REQUIRED` and carry a policy version, reason,
validity, correlation ID, and immutable decision record.

High-risk decisions can create an N-of-M approval request. Decisions are
attributed to the authenticated principal, exclude the requester by default,
enforce configured role/group separation rules, and remain append-only. A
duplicate decision or a submission after a terminal transition returns an
explicit idempotent terminal result and cannot increase the quorum.

Emergency disable is a durable operation with per-step outcomes. It disables
the registration, revokes grants, terminates platform sessions, releases pool
ownership, requests eligible job cancellation, rotates credentials, and keeps
partial failures retryable. Governed audit stores metadata by default; bounded
masked detail, hashes, encrypted references, retention, legal hold, and
scoped evidence export are enabled only by Enterprise policy.

## Human, Agent, Channel, And Instance Boundaries

v4.3.0 resolves every Dashboard, Portal, Skill, MCP, and Gateway request to a
database-backed Human or Agent Principal. A session carries a permission
version and CSRF binding; changing a role, scope, or Principal status invalidates
the affected sessions. Unknown, inactive, pending, or expired Principals fail
closed before role fallback is considered.

Agents enter the managed boundary through a one-time Enrollment Token created
by an authorized Human. The grant binds sponsor, owner, runtime, environment,
Security Domain, risk tier, quota, and policy snapshot. A redeemed Agent gets
its own credential metadata and can be placed in an isolated instance with a
short-lived access token. Business Agents never receive or fall back to the
schema-owner credential.

Channel is a first-level collaboration surface for humans and Agents. It is a
coordination and evidence boundary, not a permission amplifier: membership
does not grant database rows, APIs, Skills, Tools, models, memory, artifacts,
or exports. A cross-domain transfer requires an explicit Bridge policy and
classification check. Channel messages are attributable, redaction-aware, and
delivered to the exact active instance that is a valid Channel member.

Barrier is the governed wait point used by a Graph Run. It stores an immutable
participant snapshot, role requirements, arrivals, idempotency evidence, and a
one-winner release decision. A waiting Agent does not hold a Worker lease. The
Gateway fences instance tokens and durable deliveries, retries bounded failures,
releases only local-node instances during restart recovery, and leaves other
collaborating nodes untouched.

## v4.3.0 Maturity Boundary

The v4.3.0 production-profile replacement gate has passed, including the
failure-recovery and capacity evidence. v4.1.x remains available as the prior
downloadable baseline and is limited to critical security or data-loss fixes.
The integrated Graph implementation is governed by the database-authoritative
capability matrix. Graph Runtime core and authorized inspection are Production
capabilities; manifest draft import, read-only SLO views, and checkpoint fork
are `CONTROLLED`; replay, Dynamic Graph migration, framework-adapter execution,
A2A, and OTLP are `DISABLED`. The internal v4.2.1 closure is a traceability
milestone, not a public release or a second maintained code line.

The `production` profile is the integrated stable-core runtime surface selected
during packaging and is the recommended production profile for v4.3.0. It does
not enable a controlled or disabled capability merely because its tables and
code are present; capability state and subject authorization are rechecked by
the service and database.

## Canonical And Legacy Entry Points

The canonical v4.3.0 service is the authenticated FastAPI application
(`web_app:app`). Its `/api/auth/*`, Principal-aware resource, Graph, Channel,
Barrier, Gateway, and governance routes, together with the `/app/{page}` shell
and the documented HTTP/MCP/Skill workflows, are the integration boundary for
new clients. Authorization is derived from the authenticated Principal and
database policy, not from an `agent_id` supplied by a request body.

The established Dashboard, Portal, and Agent routes are retained through the
request-local compatibility bridge to `visualization/server.py`. The bridge
does not open a second listener or own a second session, scheduler, or database
connection. Legacy callers remain subject to the same session, CSRF, Agent
identity, and coarse permission gates; they are compatibility entry points, not
direct database APIs or authorization bypasses.

## Unified Entity Model

v3.7.0 extends the unified model with workspace management, context continuity, JRD updatable views, and Deep Data Security.

### ENTITIES

Single table with `ENTITY_TYPE` discriminator, composite PK `(ENTITY_ID, ENTITY_TYPE)`:

- **MEMORY**: Short-term agent memories. Fields: title, content, summary, category, importance, status, visibility, source_agent
- **KNOWLEDGE**: Long-term validated knowledge. Extended by KNOWLEDGE_META for domain, topic, difficulty, spaced review
- **TASK_OUTPUT**: Task execution results
- **EXPERIENCE**: Learned patterns and heuristics
- **HARNESS_TEMPLATE**: Reusable agent execution blueprints. Extended by HARNESS_META for input_schema, output_schema, execution_mode
- **OTHER**: Catch-all for future entity types

**v3.4.0 column changes from v2.0**:

| v2.0 Column | v2.1 Column | Notes |
|-------------|-------------|-------|
| NAME | TITLE | Renamed |
| PRIORITY | IMPORTANCE | Renamed, range 1-10 |
| TAGS (JSON) | ENTITY_TAGS + TAGS tables | Normalized into separate tables |
| METADATA (JSON) | *(removed)* | Only on ENTITY_EDGES now |
| ACCESSIBLE_TO (JSON) | *(removed)* | Visibility simplified to PRIVATE/SHARED/PUBLIC |
| DESCRIPTION | *(removed)* | SUMMARY replaces it on ENTITIES; DESCRIPTION lives on TASK_STEPS |
| *(new)* | SUMMARY | VARCHAR2(2000) entity summary |
| *(new)* | SOURCE_AGENT | VARCHAR2(64) creating agent |
| *(new)* | RETRIEVAL_COUNT | NUMBER(10,0) access counter |
| *(new)* | IMPORTANCE | NUMBER(3,0) 1-10, replaces PRIORITY |

### ENTITY_EDGES

Unified directed edge table with composite PK `(EDGE_ID, SOURCE_ID)`:

- **SOURCE_TYPE**: Denormalized ENTITY_TYPE of the source entity (required for composite FK)
- FK: `(SOURCE_ID, SOURCE_TYPE)` references `ENTITIES(ENTITY_ID, ENTITY_TYPE)`
- Edge types: DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS
- METADATA (JSON) column on edges only

## Composite Primary Keys & Denormalized ENTITY_TYPE

v2.1 uses composite PKs to enable partition-by-reference on child tables. The `ENTITY_TYPE` column is denormalized onto every child table that references ENTITIES:

| Table | PK | FK to ENTITIES | Denormalized Column |
|-------|----|----------------|-------------------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | — | — |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | (SOURCE_ID, SOURCE_TYPE) | SOURCE_TYPE |
| KNOWLEDGE_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_EMBEDDINGS | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| HARNESS_META | (ENTITY_ID, ENTITY_TYPE) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |
| ENTITY_TAGS | (ENTITY_ID, ENTITY_TYPE, TAG_ID) | (ENTITY_ID, ENTITY_TYPE) | ENTITY_TYPE |

TASK_PLANS and TASK_STEPS also use composite PKs:

| Table | PK | UK |
|-------|----|----|
| TASK_PLANS | (PLAN_ID, STATUS) | UK_TASK_PLANS_ID (PLAN_ID) |
| TASK_STEPS | (STEP_ID, PLAN_ID) | UK_TASK_STEPS_ID (STEP_ID) |
| ENTITY_ACCESS_LOG | (LOG_ID) via UK | UK_ACCESS_LOG_ID (LOG_ID) |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | UK_EDGES_ID (EDGE_ID) |
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | UK_ENTITIES_ID (ENTITY_ID) |

Global unique constraints (UK_*) ensure ID uniqueness across partitions when the PK is composite.

## Partitioning Architecture

### ENTITIES — LIST + RANGE (6 partitions × 7 subpartitions = 42 subpartitions)

```
PARTITION BY LIST (ENTITY_TYPE)
  P_MEMORY, P_KNOWLEDGE, P_TASK_OUTPUT, P_EXPERIENCE, P_HARNESS, P_OTHERS

SUBPARTITION BY RANGE (CREATED_AT)
  SP_2026Q1 .. SP_2027Q2, SP_FUTURE
```

Benefits: Queries filtering by ENTITY_TYPE prune to a single partition; time-range queries further prune to subpartitions.

### Reference Partitioned Tables (5 tables)

ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, HARNESS_META, and ENTITY_TAGS inherit their partitioning from the parent ENTITIES table via `PARTITION BY REFERENCE (FK_...)`. This ensures child rows co-locate with their parent entity partition.

### AGENT_SESSION — LIST + RANGE

```
PARTITION BY LIST (IS_ACTIVE): P_ACTIVE('Y'), P_INACTIVE('N')
SUBPARTITION BY RANGE (START_TIME): quarterly subpartitions
```

ROW MOVEMENT enabled — when a session transitions from active to inactive, the row physically moves to the inactive partition.

### TASK_PLANS — LIST + RANGE

```
PARTITION BY LIST (STATUS): P_ACTIVE(PENDING/RUNNING/BLOCKED), P_TERMINAL(SUCCESS/FAILED/CANCELLED)
SUBPARTITION BY RANGE (CREATED_AT): quarterly subpartitions
```

ROW MOVEMENT enabled — plan status changes cause row movement between active/terminal partitions.

TASK_STEPS inherits partitioning via reference to TASK_PLANS.

### ENTITY_ACCESS_LOG — RANGE + HASH

```
PARTITION BY RANGE (ACCESS_TIME): monthly partitions
SUBPARTITION BY HASH (AGENT_ID) SUBPARTITIONS 4
```

Optimized for time-range access log queries with hash-based subpartitioning for concurrent agent access patterns.

### Non-Partitioned Tables

AGENT_REGISTRY, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS, SYSTEM_CONFIG, SYSTEM_USERS.

## Visibility Model

| Level | Behavior |
|-------|----------|
| PRIVATE | Only owner agent can access |
| SHARED | All registered agents can access |
| PUBLIC | Unrestricted access (v2.1 addition, replaces COLLABORATIVE) |

The COLLABORATIVE level and ACCESSIBLE_TO JSON array from v2.0 have been removed. AGENT_COLLABORATION handles cross-agent sharing.

## Property Graph

### ORACLE_MEMORY_GRAPH

Single property graph using composite vertex key `(ENTITY_ID, ENTITY_TYPE)`:

```sql
CREATE PROPERTY GRAPH ORACLE_MEMORY_GRAPH
  VERTEX TABLES (
    ENTITIES KEY (ENTITY_ID, ENTITY_TYPE)
      PROPERTIES (ENTITY_ID, ENTITY_TYPE, TITLE, CATEGORY, STATUS,
                  OWNED_BY_AGENT, VISIBILITY, IMPORTANCE, CREATED_AT, UPDATED_AT)
  )
  EDGE TABLES (
    ENTITY_EDGES KEY (EDGE_ID, SOURCE_ID)
      SOURCE KEY (SOURCE_ID, SOURCE_TYPE) REFERENCES ENTITIES(ENTITY_ID, ENTITY_TYPE)
      DESTINATION KEY (TARGET_ID) REFERENCES ENTITIES(ENTITY_ID)
      PROPERTIES (EDGE_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, CREATED_AT)
  );
```

### Property Graph API (graph_api.py)

9 Python functions using the `GRAPH_TABLE` SQL operator:

| Function | Description |
|----------|-------------|
| `get_neighbors(entity_id, direction, edge_type, min_strength, limit)` | Get adjacent entities with direction filtering |
| `get_reachable(entity_id, max_hops, edge_type, limit)` | Multi-hop reachability via `{1,max_hops}` pattern |
| `get_shortest_path(source_id, target_id, max_hops)` | Shortest path between two entities (up to 6 hops) |
| `find_similar_entities(entity_id, max_hops, limit)` | Find structurally similar entities via graph proximity |
| `get_entity_context(entity_id, depth)` | Full entity context with neighbors grouped by type/edge |
| `get_graph_stats()` | Graph statistics: vertex/edge counts, degree distribution |
| `get_subgraph(entity_ids, include_intermediate)` | Extract subgraph by entity ID list |
| `find_communities(entity_type, min_connections, limit)` | Find highly-connected entity clusters |
| `graph_search(keyword, entity_type, category, min_importance, limit)` | Graph-aware search via GRAPH_TABLE |

## JSON Duality Views

- **MEMORY_DV**: JSON read/write view for MEMORY-type entities with edges and tags. Uses composite `_id: {entity_id, entity_type}`
- **KNOWLEDGE_DV**: JSON read/write view for KNOWLEDGE-type entities with metadata, edges, and tags

Both views join ENTITY_EDGES on `(SOURCE_ID = ENTITY_ID AND SOURCE_TYPE = ENTITY_TYPE)` and ENTITY_TAGS on `(ENTITY_ID, ENTITY_TYPE)`.

## ID Generation

All IDs are `VARCHAR2(64)`, generated via `RAWTOHEX(SYS_GUID())` producing 32-character hex strings. Prefix conventions: `E_` for edges, `SES_` for sessions, `LOG_` for access logs, `COL_` for collaborations, `PLAN_` for plans, `STEP_` for steps, `SNAP_` for snapshots, `CALL_` for tool calls, `DEP_` for dependencies, `HARNESS_` for templates.

## Design Decisions

1. **Composite PKs** enable partition-by-reference and co-location of parent/child rows
2. **Denormalized ENTITY_TYPE** on child tables required for composite FKs and reference partitioning
3. **ROW MOVEMENT** on AGENT_SESSION, TASK_PLANS, TASK_STEPS allows physical row migration when partition key changes
4. **LIST + RANGE partitioning** on ENTITIES enables type-based pruning + time-based archival
5. **RANGE + HASH** on ENTITY_ACCESS_LOG optimizes for time-range scans with concurrent agent access
6. **Global UK constraints** ensure logical ID uniqueness when PK is composite
7. **Normalized tags** (TAGS + ENTITY_TAGS) replace JSON TAGS column for indexable tag queries
8. **CLOB** for CONTENT fields (large text storage)
9. **VECTOR** for embeddings (compatible with BGE-M3 model)
10. **ON DELETE CASCADE** not used — explicit child-table deletes in Python APIs for safety with partitioned tables

## Workspace & Context Continuity

v3.4.0 adds workspace-based session management with context chains for agent handoff and recovery.

### WORKSPACES Table

Top-level container for grouping entities, sessions, and tasks:

| Column | Type | Description |
|--------|------|-------------|
| WORKSPACE_ID | VARCHAR2(64) | PK, `'WS_' \|\| RAWTOHEX(SYS_GUID())` |
| OWNER_USER_ID | VARCHAR2(64) | User who owns the workspace |
| WORKSPACE_NAME | VARCHAR2(200) | Human-readable name |
| WORKSPACE_TYPE | VARCHAR2(30) | CONVERSATION, PROJECT, ANALYSIS |
| ISOLATION_MODE | VARCHAR2(20) | SHARED (default) or ISOLATED |
| CURRENT_AGENT_ID | VARCHAR2(64) | Agent currently controlling the workspace |
| CURRENT_SESSION_ID | VARCHAR2(64) | Active session in the workspace |
| SUMMARY | VARCHAR2(4000) | Current workspace summary |
| METADATA | JSON | Arbitrary workspace metadata |
| STATUS | VARCHAR2(20) | ACTIVE, PAUSED, ARCHIVED |
| CREATED_AT / UPDATED_AT | TIMESTAMP | Lifecycle timestamps |

Lifecycle: `ACTIVE → PAUSED → ARCHIVED`. In ISOLATED mode, entities created within the workspace are scoped by `ENTITIES.WORKSPACE_ID`.

### WORKSPACE_CONTEXT Table

Version chain of context entries enabling continuity across sessions and agent handoffs:

| Column | Type | Description |
|--------|------|-------------|
| CONTEXT_ID | VARCHAR2(64) | PK, `'CTX_' \|\| RAWTOHEX(SYS_GUID())` |
| WORKSPACE_ID | VARCHAR2(64) | FK to WORKSPACES |
| AGENT_ID | VARCHAR2(64) | Agent that created this context |
| SESSION_ID | VARCHAR2(64) | Session during which context was created |
| CONTEXT_TYPE | VARCHAR2(30) | SNAPSHOT, CHECKPOINT, HANDOFF, SUMMARY, RECOVERY |
| CONTEXT_DATA | JSON | Structured context payload |
| PARENT_CONTEXT_ID | VARCHAR2(64) | FK to parent context (version chain) |
| VISIBILITY | VARCHAR2(16) | PRIVATE/SHARED/PUBLIC (default SHARED). Controls cross-agent visibility in collab workspaces: PRIVATE blocks other agents, SHARED visible to collab group members, PUBLIC visible to all |
| CREATED_AT | TIMESTAMP | Creation timestamp |

The `PARENT_CONTEXT_ID` column forms a linked list (version chain) — each context entry points to its predecessor, enabling full history traversal. CONTEXT_TYPE determines the structure of CONTEXT_DATA:

- **SNAPSHOT**: Full workspace state at a point in time
- **CHECKPOINT**: Intermediate save during a session
- **HANDOFF**: Context transferred between agents during handoff
- **SUMMARY**: Condensed summary of session activity
- **RECOVERY**: Context used to restore a workspace after interruption

### WORKSPACE_TASKS Table

Links task plans to workspaces:

| Column | Type | Description |
|--------|------|-------------|
| WORKSPACE_ID | VARCHAR2(64) | FK to WORKSPACES |
| PLAN_ID | VARCHAR2(64) | FK to TASK_PLANS |
| ASSIGNED_AT | TIMESTAMP | When the task was linked |

Composite PK: `(WORKSPACE_ID, PLAN_ID)`.

### AGENT_SESSION New Columns

v3.4.0 adds three columns to AGENT_SESSION for workspace integration and session chaining:

| Column | Type | Description |
|--------|------|-------------|
| OWNER_USER_ID | VARCHAR2(64) | User who owns/started the session |
| WORKSPACE_ID | VARCHAR2(64) | Workspace the session belongs to |
| PREDECESSOR_SESSION_ID | VARCHAR2(64) | Previous session in the handoff chain |

`PREDECESSOR_SESSION_ID` creates a linked list of sessions — when an agent hands off to another agent, the new session points back to the predecessor. `get_session_chain()` traverses this chain backwards.

### ENTITIES.WORKSPACE_ID

New column `WORKSPACE_ID VARCHAR2(64)` on ENTITIES, nullable FK to WORKSPACES. When a workspace has `ISOLATION_MODE = 'ISOLATED'`, entities created within it are tagged with WORKSPACE_ID for scope isolation. In SHARED mode, WORKSPACE_ID is optional.

### JRD Views

v3.4.0 updates and adds JSON Relational Duality views:

| View | Mode | Description |
|------|------|-------------|
| WORKSPACE_DV | Updatable | Full workspace with nested context chain and tasks |
| CONTEXT_DV | Read-only | Context entries with workspace and agent details |
| MEMORY_DV | Updatable | Now updatable (was read/write in v2.1; confirmed updatable with JSON_TRANSFORM) |
| KNOWLEDGE_DV | Updatable | Now updatable (was read/write in v2.1; confirmed updatable with JSON_TRANSFORM) |

WORKSPACE_DV nests WORKSPACE_CONTEXT and WORKSPACE_TASKS as sub-documents, enabling atomic workspace updates via a single JSON document. CONTEXT_DV is read-only to prevent direct context manipulation — context changes go through `save_context()` to maintain the version chain integrity.

### JSON Strategy

v3.4.0 uses a layered JSON approach:

1. **Native JSON columns** for storage — `WORKSPACES.METADATA`, `WORKSPACE_CONTEXT.CONTEXT_DATA`, `AGENT_SESSION.CONTEXT` use Oracle's native JSON type for schemaless, queryable data
2. **JRD (JSON Relational Duality)** for document API — WORKSPACE_DV, CONTEXT_DV, MEMORY_DV, KNOWLEDGE_DV provide REST-friendly JSON document access over the relational schema
3. **JSON_TRANSFORM for partial updates** — Updatable JRD views use `JSON_TRANSFORM` under the hood for atomic partial JSON updates without full document replacement

This strategy balances: (a) relational integrity for FK constraints and partitioning, (b) document convenience for API consumers, and (c) partial update efficiency for large JSON payloads.

## Deep Data Security Architecture (Oracle Adapter)

### Direct Logon with Local End Users

Deep Sec uses Oracle's Direct Logon with Local End Users model for per-agent data isolation:

- Each agent gets a dedicated End User account
- End User name mapping: `UPPER(REPLACE(agent_id, '-', '_'))`
  - Example: `agent-001` → End User `AGENT_001`
- End Users connect directly to the database with filtered access via Data Grants

### Data Roles

Three Data Roles control access levels:

| Role | Purpose | Access Level |
|------|---------|--------------|
| `admin_data_role` | Full administrative access | All tables, no filtering |
| `agent_data_role` | Standard agent access | Filtered by workspace/agent context |
| `pool_agent_data_role` | Connection pool agents | Minimum required access |

### Data Grants (23 total)

Data Grants enforce row-level security with MAC (Mandatory Access Control), including `collab_member_own` (COLLAB_GROUP_MEMBERS) and `collab_group_member_access` (COLLAB_GROUPS) for collaboration group access:

| Table | Privilege | Predicate | Role |
|-------|-----------|-----------|------|
| AGENT_REGISTRY | SELECT | 1=1 | admin_data_role |
| AGENT_REGISTRY | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | SELECT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC' | agent_data_role |
| ENTITIES | INSERT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | UPDATE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | DELETE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_EDGES | SELECT | SOURCE_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| KNOWLEDGE_META | SELECT | ENTITY_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC') | agent_data_role |
| WORKSPACES | SELECT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACES | INSERT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACE_CONTEXT | SELECT | WORKSPACE_ID IN (SELECT WORKSPACE_ID FROM WORKSPACES WHERE OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID')) | agent_data_role |
| AGENT_SESSION | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| AGENT_SESSION | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_STEPS | SELECT | PLAN_ID IN (SELECT PLAN_ID FROM TASK_PLANS WHERE AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| ENTITY_ACCESS_LOG | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_ACCESS_LOG | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| SYSTEM_CONFIG | SELECT | 1=0 | agent_data_role |
| TAGS | SELECT | 1=1 | agent_data_role |

### MAC Enforcement

MAC (Mandatory Access Control) is enforced on 7 critical tables:

- ENTITIES
- ENTITY_EDGES
- KNOWLEDGE_META
- WORKSPACES
- WORKSPACE_CONTEXT
- AGENT_SESSION
- TASK_PLANS

MAC prevents bypass of Data Grant predicates even with direct DML.

### DEEP_SEC_SESSION_ROLE

End Users require `CREATE SESSION` to connect. This is granted via `DEEP_SEC_SESSION_ROLE`:

```sql
CREATE ROLE DEEP_SEC_SESSION_ROLE;
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO AIADMIN WITH ADMIN OPTION;
```

Data Roles grant `DEEP_SEC_SESSION_ROLE` to End Users, enabling them to create sessions.

### END_USER_MANAGER Package

The `END_USER_MANAGER` PL/SQL package manages the End User lifecycle:

- `create_end_user(agent_id)` — Creates End User with name `UPPER(REPLACE(agent_id, '-', '_'))`
- `get_end_user_name(agent_id)` — Returns mapped End User name
- `drop_end_user(agent_id)` — Drops End User
- `list_end_users()` — Lists all agent End Users
- `grant_data_role(end_user_name, role_name)` — Grants Data Role to End User
- `revoke_data_role(end_user_name, role_name)` — Revokes Data Role from End User

### Per-Request Context Switching

Each request sets the agent identity via `_set_context_from_session()`:

1. Application receives request with agent context
2. `_set_context_from_session()` sets `END_USER_CTX` namespace with AGENT_ID, USER_ID
3. Data Grant predicates reference `SYS_CONTEXT('END_USER_CTX', 'AGENT_ID')` for filtering
4. After request completes, context is cleared

### Dual Access Paths

| Path | User | Connection | Access |
|------|------|------------|--------|
| Portal | End User | Direct logon | Filtered by Data Grants |
| Admin | AIADMIN | Pool connection | Unrestricted (no Data Grants) |

Portal requests use End User connections with Data Grant filtering. Admin/management operations use the AIADMIN pool connection with unrestricted access.

Business/Portal requests remain on the End User connection for their complete
lifetime and fail closed if it is unavailable. Schema Owner access is confined
to separately authenticated Admin operations; Business requests never switch
to AIADMIN as a fallback.

## v4.3.0 Integrated Graph Engineering Plane

The v4.3.0 profile adds a versioned execution graph without replacing the
v4.1.x domain graph. The existing `ENTITIES` and `ENTITY_EDGES`
tables continue to represent knowledge, memory, and provenance relationships.
The new `GRAPH_*` tables represent executable topology and runtime evidence:

```text
Graph Definition -> Graph Version -> Compiler Plan -> Graph Run

At Run admission, the database also stores the Version definition digest,
compiled Plan digest, compatibility level, State schema version, and budget
schema version. The Plan must reference the requested Version and its
definition digest must match; a mismatch fails closed before a Ready node is
inserted. A fork whose plan contains a `NON_IDEMPOTENT` side effect is created
with `PAUSED` Run state and `WAITING` entry work. Resume requires an approved
`GRAPH_FORK_REPLAY` request bound to that child Run or a bounded compensation
evidence reference. Agent Cards and protocol metadata remain descriptive and
cannot create any of these grants.
                                              |-> Node Run -> Attempt -> Worker lease
                                              |-> State Event -> Checkpoint
                                              |-> Transition -> Trace / Evaluation
                                              |-> Artifact / Event Inbox / Outbox
```

Definitions are canonical JSON at the service boundary. A Draft may be
edited; a Published version is immutable. The Compiler validates registered
node and edge types, dependencies, typed condition ASTs, side-effect classes,
join strategies, cycle bounds, capabilities, resource scopes, and hard
budgets. It never evaluates arbitrary Python, SQL, shell, network, credential,
or secret expressions.

The Runtime is database-authoritative. A Transition commits the accepted
result reference, State Event, Checkpoint, selected edge evidence, budget
accounting, and downstream activation as one controlled transaction. Workers
receive scoped input and a short Lease Token. Heartbeats and completion compare
the fencing token, so a late or expired Worker cannot overwrite a newer
Attempt. A successful completion records a request digest; an exact replay
returns the original checkpoint without repeating downstream activation. A
Worker never receives Schema Owner credentials.

Community uses a simple priority/concurrency scheduler. Enterprise adds
governed quotas, weighted fairness, multi-Scheduler coordination, advanced
evaluation, retention/legal hold, and evidence export. Both profiles keep
identity admission and Business Agent fail-closed behavior from v4.1.0.

## Database Graph Projection Boundary

The portable runtime tables are the execution authority. Each adapter may
project the same versioned topology into its native Property Graph for query
and visualization:

| Adapter | Projection | v4.3.0 boundary |
|---|---|---|
| Oracle | Oracle Property Graph / SQL PGQ | Native graph queries are used for graph capabilities while state commits remain relational. |
| PostgreSQL 18 | Apache AGE | AGE/Cypher projection is used where available; relational metadata and runtime operations remain portable. |
| YashanDB | Native Property Graph projection | Native graph capability is exposed; relational edge operations remain the fallback for supported runtime queries. |

PostgreSQL 19 native Property Graph is intentionally a future adapter target.
It is not required for the PostgreSQL 18 v4.3.0 release and does not change
the shared service contract.

## Profile Boundary

Profiles and capability flags are generated from one source line. The
database-authoritative matrix supersedes the older `graph-preview`,
`development`, and `experimental-4.2` capability labels: Graph Runtime core
and authorized inspection are Production; manifest draft import, read-only SLO
views, and checkpoint fork are `CONTROLLED`; replay, Dynamic Graph migration,
framework-adapter execution, A2A, and OTLP remain `DISABLED`. The stable
v4.1.x line remains the prior compatibility baseline.
Profiles do not weaken database, API, Skill, Tool, model, memory, Artifact, or
export authorization, and there is no long-lived source fork.
