# Migration Guide - AI Agent Infra with DB v4.3.2

## v4.3.2 Versioned Memory Step

`23_v4_3_2_memory_lifecycle.sql` is additive and journaled. It adopts every
existing `MEMORY` entity as version one of a stable Family without changing the
existing entity ID, payload, tags, embeddings, ownership, workspace, or
timestamps. It adds Families, Versions, Representations, Relations, Snapshots,
Policies, Jobs, Usage Events, Candidates, Reviews, and projection Outbox
facts. Use `migration_runner.py --version 4.3.2`; an interrupted step must be
retried through the same command, not repaired by deleting migration rows.

`24_v4_3_2_memory_digest_alignment.sql` is a separate idempotent journaled
step. It changes only the digest of legacy-adopted version-one rows to SHA-256.
It exists separately so installations that already recorded step 23 never face
a prior-checksum mismatch; it does not change Family or Version IDs, payloads,
ownership, scope, or lifecycle state.

`25_v4_3_2_disable_legacy_memory_fusion.sql` is a separate idempotent
journaled safety correction. It removes the pre-v4.3.2 scheduler task that
directly fused legacy rows and decayed their importance. That task must not be
recreated: governed lifecycle jobs create bounded candidates, preserve
versions, and retain snapshot and audit evidence instead of mutating memory
outside the shared service.

`26_v4_3_2_snapshot_subject_fencing.sql` adds optional Principal permission
version and Agent-instance fencing fields to snapshots. Existing snapshots and
legacy callers remain compatible. New runtime callers should supply these
identifiers so authorization, offboarding, domain removal, and instance
replacement are rechecked before a pinned member is returned.

The migration is a logical-forgetting upgrade. It does not physically erase
old Memory content and does not assert model unlearning. Before an upgrade,
record a recoverable backup/evidence manifest and verify current authorization,
history, chain, candidate, and job behavior after the journal reports applied.

## v4.3.1 Organization Step

`19_v4_3_1_organization_governance.sql` follows the v4.3.0 identity,
governance, and security steps. It adds canonical reporting, closure, versions,
history, semantic change sets, directory staging, conflicts, and lifecycle
disposition objects. It refuses ambiguous active primary memberships, direct
managers, Agent primary owners, or organization cycles rather than inventing
authority.

`20_v4_3_1_human_display_name.sql` normalizes Human display-name support.
`21_v4_3_1_entry_access.sql` adds independent Portal and App admission flags,
preserves both surfaces for migrated users, and marks the active local
`admin` system role as `BOOTSTRAP_ADMIN`. New registrations approved after the
upgrade default to Portal-only in application code. Verify that the bootstrap
administrator has `PORTAL_ACCESS='Y'`, `APP_ACCESS='Y'`, and one active
`SYSTEM_ADMIN` assignment sourced from `BOOTSTRAP_ADMIN` before accepting
traffic.

`22_v4_3_1_identity_organization_alignment.sql` marks ordinary Human
Principals as organization-required, ends any legacy organization membership
held by the protected bootstrap `admin`, clears that system account from
organization responsibility fields, and adds a database trigger that rejects
an organization member without an active platform login identity. After the
step, verify every active ordinary Human has one active primary organization
membership and at least one active login identity. Resolve any legacy anomaly
in User Management before enabling Portal or App admission.

Do not edit or re-checksum prior migration files. Run `migration_runner.py
--version 4.3.1` and then `live_db_validator.py`; interrupted execution must be
retried through the journaled runner.

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## Temporary Test Database Lifecycle

Clean-install, migration, mode, browser, recovery, and capacity validation must
use explicitly named temporary databases or PDBs. A temporary test object is
not a baseline database and must not be reused silently by the next release.

Before starting the next version upgrade:

1. Stop the validation Web and Worker processes and wait for active test
   sessions to finish.
2. Record the final temporary-object inventory and the protected baseline
   inventory without recording credentials, DSNs, or internal host details.
3. Drop every temporary PostgreSQL database and every temporary Oracle or
   YashanDB PDB using the database-specific administrative procedure. Verify
   that dependent sessions, data files, roles, and test-only scheduler jobs
   are removed where the database supports them.
4. Re-query the database inventory and require zero temporary objects before
   applying the next version's migration.

The upgrade is blocked when cleanup cannot be proven. Only the declared
baseline databases may remain. Never remove a baseline object or the Oracle
`TEST` PDB as part of routine test cleanup; resolve an ambiguous name before
performing a destructive operation.

## v4.0.1 to v4.1.0

1. Stop web and worker processes. Back up the database/schema, encrypted
   `config.json`, master-key file, and the exact v4.0.1 archive.
2. Run `scripts/migration_runner.py` in a generated package (or
   `migration_runner.py` from the unified source root) with the encrypted local configuration. It uses
   the v4.1.0 checksum ledger and refuses a changed script for an applied
   version.
3. Verify the eight execution tables, thirteen governance tables, and the
   Skill Entity contract with `live_db_validator.py`.
4. Fresh Community deployments execute `8_v4_1_0_registration.sql`;
   Enterprise deployments execute `8_v4_1_0_governance.sql` instead. The
   Enterprise script includes the registered-Agent boundary and adds the
   governance overlay.
5. Register or explicitly re-register Business Agents. Their configuration
   must contain only the independent Oracle End User, PostgreSQL LOGIN role,
   or YashanDB user; Schema Owner credentials remain Admin-only.
6. Validate registration lifecycle, policy/grant expiry and revocation,
   approval quorum, emergency retry, bounded audit, and evidence export before
   accepting traffic.

The migration preserves the existing v4.0.1 execution control plane and adds
registered identities, governed resources and policies, bounded grants,
decision evidence, N-of-M approvals, emergency operations, audit retention,
legal holds, and evidence exports. PostgreSQL continues to use dedicated
LOGIN roles plus RLS; Oracle and YashanDB use their native independent user
boundaries.

Apply `8_portal_node_ownership.sql` to an existing v4.0.1 schema before
restarting Portal services if it has not already been applied. It reclaims
only active Portal assignments carrying the local node ID; other nodes remain
untouched.

### Rollback

Stop v4.1.0 processes and restore the database/schema, configuration, and
master key from the coordinated v4.0.1 backup. Database rollback does not undo
external side effects already completed by workers. Do not edit or delete a
successful migration ledger row to simulate rollback.

## Historical Migrations

## Version Compatibility

| From | To | Path |
|------|----|------|
| v1.x | v2.1.0 | **Not supported** — clean deploy only |
| v2.0.0 | v2.1.0 | **Drop and redeploy** — no in-place upgrade |

## Breaking Changes from v2.0 to v2.1

### Primary Keys: Single → Composite

| Table | v2.0 PK | v2.1 PK |
|-------|---------|---------|
| ENTITIES | ENTITY_ID | (ENTITY_ID, ENTITY_TYPE) |
| ENTITY_EDGES | EDGE_ID | (EDGE_ID, SOURCE_ID) |
| KNOWLEDGE_META | ENTITY_ID | (ENTITY_ID, ENTITY_TYPE) |
| ENTITY_EMBEDDINGS | ENTITY_ID | (ENTITY_ID, ENTITY_TYPE) |
| HARNESS_META | ENTITY_ID | (ENTITY_ID, ENTITY_TYPE) |
| ENTITY_TAGS | (ENTITY_ID, TAG_ID) | (ENTITY_ID, ENTITY_TYPE, TAG_ID) |
| TASK_PLANS | PLAN_ID | (PLAN_ID, STATUS) |
| TASK_STEPS | (STEP_ID, PLAN_ID) | (STEP_ID, PLAN_ID) — PLAN_STATUS added |
| AGENT_SESSION | SESSION_ID | (SESSION_ID, IS_ACTIVE) |

### ID Type: NUMBER → VARCHAR2(64)

All entity and edge IDs changed from `NUMBER GENERATED BY DEFAULT AS IDENTITY` to `VARCHAR2(64)` generated via `RAWTOHEX(SYS_GUID())`. All foreign keys and references updated accordingly.

### Column Renames and Removals

| Table | v2.0 Column | v2.1 Column | Change |
|-------|-------------|-------------|--------|
| ENTITIES | NAME | TITLE | Renamed |
| ENTITIES | PRIORITY | IMPORTANCE | Renamed, range 1-10 |
| ENTITIES | TAGS (JSON) | *(removed)* | Replaced by TAGS + ENTITY_TAGS tables |
| ENTITIES | METADATA (JSON) | *(removed)* | Only on ENTITY_EDGES now |
| ENTITIES | ACCESSIBLE_TO (JSON) | *(removed)* | Visibility simplified |
| ENTITIES | DESCRIPTION | *(removed)* | SUMMARY replaces it |
| ENTITIES | *(new)* | SUMMARY | VARCHAR2(2000) |
| ENTITIES | *(new)* | SOURCE_AGENT | VARCHAR2(64) |
| ENTITIES | *(new)* | RETRIEVAL_COUNT | NUMBER(10,0) |
| ENTITIES | *(new)* | IMPORTANCE | NUMBER(3,0) 1-10 |
| ENTITY_EDGES | *(new)* | SOURCE_TYPE | Denormalized for composite FK |
| TASK_STEPS | *(new)* | PLAN_STATUS | Denormalized for composite FK |
| HARNESS_META | VARIABLES (JSON) | *(removed)* | Replaced by INPUT_SCHEMA |
| HARNESS_META | TEMPLATE_STATUS | *(removed)* | Use ENTITIES.STATUS |
| HARNESS_META | CHANGELOG (JSON) | *(removed)* | Removed |
| HARNESS_META | *(new)* | INPUT_SCHEMA | JSON |
| HARNESS_META | *(new)* | OUTPUT_SCHEMA | JSON |
| HARNESS_META | *(new)* | EXECUTION_MODE | SEQUENTIAL/PARALLEL/CONDITIONAL |

### Visibility Model Change

| v2.0 | v2.1 |
|------|------|
| PRIVATE | PRIVATE (unchanged) |
| SHARED | SHARED (unchanged) |
| COLLABORATIVE | **Removed** — replaced by PUBLIC + AGENT_COLLABORATION |

### New Tables

- **TAGS**: Normalized tag definitions (TAG_ID, TAG_NAME, TAG_GROUP)
- **ENTITY_TAGS**: Junction table (ENTITY_ID, ENTITY_TYPE, TAG_ID) — reference partitioned

### Partitioning (New in v2.1)

All partitioning is new in v2.1. No v2.0 tables were partitioned:

| Table | Strategy | Key |
|-------|----------|-----|
| ENTITIES | LIST + RANGE | ENTITY_TYPE, CREATED_AT |
| ENTITY_EDGES | REFERENCE | FK_EDGE_SOURCE |
| KNOWLEDGE_META | REFERENCE | FK_KM_ENTITY |
| ENTITY_EMBEDDINGS | REFERENCE | FK_EE_ENTITY |
| HARNESS_META | REFERENCE | FK_HM_ENTITY |
| ENTITY_TAGS | REFERENCE | FK_ET_ENTITY |
| AGENT_SESSION | LIST + RANGE | IS_ACTIVE, START_TIME |
| TASK_PLANS | LIST + RANGE | STATUS, CREATED_AT |
| TASK_STEPS | REFERENCE | FK_STEP_PLAN |
| ENTITY_ACCESS_LOG | RANGE + HASH | ACCESS_TIME, AGENT_ID |

### Global Unique Constraints (New)

| Constraint | Table | Column |
|------------|-------|--------|
| UK_ENTITIES_ID | ENTITIES | ENTITY_ID |
| UK_EDGES_ID | ENTITY_EDGES | EDGE_ID |
| UK_TASK_PLANS_ID | TASK_PLANS | PLAN_ID |
| UK_TASK_STEPS_ID | TASK_STEPS | STEP_ID |
| UK_ACCESS_LOG_ID | ENTITY_ACCESS_LOG | LOG_ID |

### Property Graph API (New)

9 new Python functions in `graph_api.py` using `GRAPH_TABLE` SQL operator.

### Scheduler Jobs

7 jobs (v2.0 had 6, added `KNOWLEDGE_REVIEW_JOB` at daily 06:00).

### Test Suite

49 tests (v2.0 had 41, added 8 graph tests in `test_graph.py`).

## v2.0 → v2.1 Migration: Drop and Redeploy

There is no in-place upgrade path from v2.0 to v2.1 due to:

1. Composite PKs cannot be added via ALTER TABLE (requires rebuild)
2. Partitioning cannot be added to existing tables
3. ID type change from NUMBER to VARCHAR2(64) is incompatible
4. Column renames and removals break existing data shapes

### Migration Steps

```bash
# 1. Export v2.0 data if needed
# Use Data Pump or custom export scripts to preserve data

# 2. Deploy v2.1 schema (Phase 1 drops all tables automatically)
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql your_user/your_password@//host:port/service @scripts/deploy/1_schema.sql

# 3. Deploy v2.1 API packages
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql your_user/your_password@//host:port/service @scripts/deploy/2_api.sql

# 4. Deploy v2.1 scheduler jobs
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql your_user/your_password@//host:port/service @scripts/deploy/3_jobs.sql

# 5. Deploy v2.1 harness templates
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql your_user/your_password@//host:port/service @scripts/deploy/4_harness_templates.sql
```

### Data Migration (if preserving v2.0 data)

Custom ETL required. Key transformations:

| v2.0 Data | v2.1 Transformation |
|-----------|-------------------|
| ENTITIES.NAME | → ENTITIES.TITLE |
| ENTITIES.PRIORITY | → ENTITIES.IMPORTANCE |
| ENTITIES.TAGS (JSON) | Parse JSON array → INSERT into TAGS + ENTITY_TAGS |
| ENTITIES.METADATA (JSON) | Dropped (not migrated) |
| ENTITIES.ACCESSIBLE_TO (JSON) | Dropped (not migrated) |
| ENTITIES.DESCRIPTION | → ENTITIES.SUMMARY (if applicable) |
| ENTITIES.ENTITY_ID (NUMBER) | Generate new VARCHAR2(64) via RAWTOHEX(SYS_GUID()) |
| ENTITY_EDGES.EDGE_ID (NUMBER) | Generate new 'E_' + RAWTOHEX(SYS_GUID()) |
| ENTITY_EDGES | Add SOURCE_TYPE = source entity's ENTITY_TYPE |
| HARNESS_META.VARIABLES | → HARNESS_META.INPUT_SCHEMA (JSON schema format) |
| HARNESS_META.TEMPLATE_STATUS | → ENTITIES.STATUS |
| HARNESS_META.CHANGELOG | Dropped |
| TASK_STEPS | Add PLAN_STATUS = parent plan's STATUS |
| Visibility 'COLLABORATIVE' | → 'SHARED' or 'PUBLIC' |

## Python Code Migration

### ID Type Changes

```python
# v2.0: IDs were int
entity_id = create_memory("test", "content")  # returns int

# v2.1: IDs are str (VARCHAR2(64))
entity_id = create_memory("test", "content")  # returns str like "A1B2C3D4..."
```

### API Signature Changes

```python
# v2.0
create_memory(name, content, category, memory_type, priority, tags, metadata, ...)
create_relationship(source_id, target_id, edge_type, ...)
add_step(plan_id, description, step_order, ...)

# v2.1
create_memory(title, content, category, importance, summary, source_agent, ...)
add_edge(source_id, source_type, target_id, edge_type, ...)  # source_type required
add_step(plan_id, plan_status, description, step_order, ...)  # plan_status required
```

### Tag Handling

```python
# v2.0: Tags passed as JSON in create calls
create_memory(..., tags=["tag1", "tag2"])

# v2.1: Tags managed via separate functions
mid = create_memory(title="test", content="content")
add_memory_tags(mid, ["tag1", "tag2"])
tags = get_memory_tags(mid)
```

## v3.3.0 → v3.4.0 Migration

This migration replaces VPD policies with Deep Data Security (Data Grants + MAC + End User Context).

### Step 1: Drop VPD Policies

Remove existing VPD policies that are replaced by Data Grants:

```sql
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'WORKSPACE_CONTEXT', 'WS_CTX_AGENT_VPD');
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'ENTITIES', 'ENTITIES_AGENT_VPD');
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'AGENT_SESSION', 'SESSION_AGENT_VPD');
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'TASK_PLANS', 'PLANS_AGENT_VPD');
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'ENTITY_ACCESS_LOG', 'ACCESS_LOG_AGENT_VPD');
```

### Step 2: Run 4_grants.sql as SYSDBA

This script adds Deep Sec system privileges, removes the SYSTEM_CONFIG grant, and creates DEEP_SEC_SESSION_ROLE:

```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql sys/your_sys_password@//host:port/service AS SYSDBA @scripts/deploy/4_grants.sql
```

### Step 3: Create DEEP_SEC_SESSION_ROLE

If not already created by 4_grants.sql:

```sql
CREATE ROLE DEEP_SEC_SESSION_ROLE;
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO AIADMIN WITH ADMIN OPTION;
```

### Step 4: Run 6_deep_sec_policy.sql as AIADMIN

This script creates Data Grants, Data Roles, MAC policies, End User Context, END_USER_MANAGER package, and End Users for existing agents:

```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql your_user/your_password@//host:port/service @scripts/deploy/6_deep_sec_policy.sql
```

### Step 5: Restart Application Server

Restart the application server to pick up the new connection routing logic.
This historical migration originally used owner context switching; v4.0.1
supersedes that behavior. Business/Portal requests now remain on independent
database identities and fail closed without Schema Owner fallback.

```bash
systemctl restart aiagent-infra
```

### Step 6: Verify Deep Sec

Connect as an End User and confirm Data Grant filtering works:

```sql
-- Connect as an End User (e.g., AGENT_001)
CONNECT <BUSINESS_AGENT_USER>/<BUSINESS_AGENT_PASSWORD>@//<DB_HOST>:1521/<DB_SERVICE>

-- Should see only own agents
SELECT COUNT(*) FROM AGENT_REGISTRY;
-- Expected: 1 (own agent only)

-- Should see only own/public entities
SELECT COUNT(*) FROM ENTITIES;
-- Expected: filtered by ownership + visibility

-- Should NOT see SYSTEM_CONFIG
SELECT COUNT(*) FROM SYSTEM_CONFIG;
-- Expected: 0 (blocked by Data Grant predicate 1=0)
```

## v3.4.0 → v3.8.0 Migration

This migration fixes three Deep Sec bugs: ENTITIES_AGENT_OWN predicate missing COLLAB subquery (SHARED entities invisible), missing Data Grants for COLLAB_GROUPS/COLLAB_GROUP_MEMBERS (End Users cannot access COLLAB tables), and missing WORKSPACE_CONTEXT VISIBILITY column (no isolation for private context in collab workspaces).

### Step 1: Add VISIBILITY Column to WORKSPACE_CONTEXT

The WORKSPACE_CONTEXT table needs a VISIBILITY column for collaboration isolation. Existing rows default to SHARED (backward compatible):

```sql
ALTER TABLE WORKSPACE_CONTEXT ADD VISIBILITY VARCHAR2(16) DEFAULT 'SHARED';
UPDATE WORKSPACE_CONTEXT SET VISIBILITY = 'SHARED' WHERE VISIBILITY IS NULL;
ALTER TABLE WORKSPACE_CONTEXT ADD CONSTRAINT CK_WC_VISIBILITY CHECK (VISIBILITY IN ('PRIVATE','SHARED','PUBLIC'));
```

### Step 2: Drop Old ENTITIES_AGENT_OWN Data Grant

The old predicate is missing the COLLAB subquery. It must be dropped and recreated:

```sql
DROP DATA GRANT entities_agent_own;
```

### Step 3: Drop Old WS_CTX Data Grants

The WS_CTX_AGENT_ACCESS and WS_CTX_AGENT_INSERT predicates must be updated for visibility-aware filtering:

```sql
DROP DATA GRANT ws_ctx_agent_access;
DROP DATA GRANT ws_ctx_agent_insert;
```

### Step 4: Re-run 6_deep_sec_policy.sql

The script is idempotent — it recreates all 23 Data Grants including the fixed `entities_agent_own`, 2 new COLLAB Data Grants (`collab_member_own`, `collab_group_member_access`), and updated `ws_ctx_agent_access`/`ws_ctx_agent_insert` with visibility-aware predicates:

```bash
JAVA_HOME=/usr/lib/jvm/jdk-26.0.1-oracle-x64 /root/sqlcl/bin/sql aiadmin/your_password@//host:port/service @scripts/deploy/6_deep_sec_policy.sql
```

### Verification

Connect as an End User and confirm SHARED entities and COLLAB tables are now accessible:

```sql
-- Connect as an End User
CONNECT AGENT_001/password@//host:port/service
ALTER SESSION SET CURRENT_SCHEMA = AIADMIN;

-- SHARED entities should now be visible (were invisible in v3.4.0)
SELECT COUNT(*) FROM ENTITIES WHERE VISIBILITY = 'SHARED';
-- Expected: > 0 (if SHARED entities exist)

-- COLLAB tables should be accessible (were ORA-00942 in v3.4.0)
SELECT COUNT(*) FROM COLLAB_GROUP_MEMBERS;
-- Expected: own membership rows

SELECT COUNT(*) FROM COLLAB_GROUPS;
-- Expected: groups where agent is a member

-- Count Data Grants (should be 23)
SELECT COUNT(*) FROM USER_DATA_GRANTS;

-- Verify COLLAB Data Grants exist
SELECT GRANT_NAME FROM USER_DATA_GRANTS WHERE GRANT_NAME LIKE 'COLLAB%';
```

## v4.3.0 Additive Graph And Governance Migration

The v4.3.0 migration tail starts from the v4.1.x baseline. It is additive: it
does not rewrite the v4.1.0 entity graph or remove Task/Loop history. Before
applying it, create a recoverable database backup and record the backup
reference in the migration evidence file.

### Preflight and Dry Run

Run the migration tool in preflight/Dry Run mode first. It verifies database
identity, required v4.1 objects, migration checksums, capacity tier, and the
database-specific graph capability. A Dry Run without verified backup evidence
is intentionally blocked and must not be described as a successful migration.

### Apply Order

Apply the nine common scripts in numeric order:

```text
9_v4_2_0_graph_engineering.sql
10_v4_2_0_graph_runtime.sql
11_v4_2_0_graph_control.sql
12_v4_2_0_graph_edge_scope.sql
14_v4_2_0_graph_triggers.sql
15_v4_2_1_executor_registry.sql
16_v4_3_0_identity_channels.sql
17_v4_3_0_governance_lifecycle.sql
18_v4_3_0_security_lifecycle.sql
```

Enterprise packages insert `13_v4_2_0_scheduler_ha.sql` between the edge-scope
and trigger scripts as an additional Enterprise-only overlay. Community
packages exclude it. The migration tail therefore contains nine scripts for
Community and ten for Enterprise. The trigger objects were deliberately split
from the base definition migration: a database that already contains
`GRAPH_TRIGGERS` from an earlier v4.2 draft can apply the new trigger step
without changing existing rows.

The migration ledger records script checksum, statement progress, backup
verification, and terminal status. Re-running after interruption is safe and
does not repeat an applied statement. The final check must verify Graph
Definition, Runtime, Worker, Event, Checkpoint, Artifact, control,
version-scoped edge objects, Channel/Barrier objects, and governance lifecycle
objects.

### Legacy Compatibility

Completed v4.1 Task Plans and Loops remain readable. New or explicitly
migrated work may receive a versioned compatibility wrapper through
`graph_compat`; the wrapper records the legacy ID and mapping. Unknown or
ambiguous topology is not inferred: it is placed in a review-required state.
An active migration requires a quiescence barrier, no active attempts, a
pre-migration Checkpoint, a mapping, and an immutable migration Transition.

### Rollback and Recovery

Application rollback means stopping the v4.3.0 services and restoring the prior
application/profile against the pre-upgrade database backup. Direct destructive
schema downgrade is not required. Worker and Scheduler crashes recover from
leases and Checkpoints; database outage pauses new side effects until
authorization and fencing are revalidated after reconnect.

## Internal Graph Closure And v4.3.0 Integration

The former v4.2.1 work is an additive internal closure step consumed by
v4.3.0. It preserves every Graph Definition, Run, Checkpoint, Event, Worker,
and governance row. Existing Graph deployments apply only
`15_v4_2_1_executor_registry.sql`; the runner adopts a known,
schema-complete baseline step in its journal instead of replaying it. There is
no public v4.2.1 package or release-history entry.

The step creates the versioned Node Executor registry and Graph governance
event table, adds retry metadata to Event Inbox/Outbox, and adds the completion
digest and external effect idempotency key used by the Worker boundary. Built-in control,
Worker, and wait Executors are immutable service contracts. Custom manifests
are stored only after validation, require an actor and reason for status
changes, and are resolved again before Worker claim and completion.

The migration runner checks the additive column contract before adopting an
existing internal closure step record: `GRAPH_ATTEMPTS.COMPLETION_DIGEST`,
`GRAPH_ATTEMPTS.EFFECT_IDEMPOTENCY_KEY`,
`GRAPH_INBOX.ATTEMPTS`, `GRAPH_INBOX.AVAILABLE_AT`,
`GRAPH_OUTBOX.MAX_ATTEMPTS`, and the Executor status-audit columns must all be
present. A table-only or stale ledger observation remains incomplete and is
retryable.

For an existing v4.2 deployment, the historical Executor step can be run with
a verified recoverable backup evidence record:

```bash
source scripts/python_runtime.sh
export PYTHON_BIN="$(cx_resolve_python)"
cx_prepare_python_environment "$PYTHON_BIN"
"$PYTHON_BIN" scripts/migration_runner.py --version 4.3.1 --edition enterprise \
  --oracle-config /path/to/oracle-config.json \
  --pg-config /path/to/pg-config.json \
  --yashandb-config /path/to/yashandb-config.json \
  --backup-evidence /path/to/backup-evidence.json \
  --output release_evidence/migrations-v4.3.0.json
```

For a clean v4.1.x deployment, `--version 4.3.1` detects the installed schema
and applies the nine common scripts in numeric order, the Enterprise scheduler
overlay where applicable, the internal Executor closure, and the v4.3 identity,
Channel, and governance lifecycle steps. A failed statement remains in the step
journal and is retried only after the transaction has been rolled back.
Re-running an `APPLIED` step is a read-only no-op; changed checksums are
rejected.

Application rollback restores the coordinated pre-v4.3.0 backup and uses the
previous application profile. A schema downgrade is not performed. Remote
non-idempotent effects that reached an uncertain outcome require confirmation,
compensation, or human review and are never blindly replayed.
