---
name: ai-agent-infra-community
version: v3.10.1
author: Haiwen Yin
description: "AI Agent Infra with OracleDB - Community Edition v3.10.1 - AI Agent的基础设施架构"
tags: [oracle, ai-agent, infrastructure, community, knowledge-base, vector-search, hybrid-search, fulltext-search, search-api, oracledb, property-graph, multi-agent, partitioning, composite-pk, workspace, context-continuity, context-branching, jrd, duality-view, spec-driven, elastic-agent, collaboration, admin-agent-separation, loop-engineering]
related_skills: [oracle-26ai, oracle-sqlcl-execution-methodology]
---

# AI Agent Infra with OracleDB - Community Edition v3.10.1

**Author:** Haiwen Yin
**Version:** v3.10.1 - 2026-07-14
**License:** Apache License 2.0 (Community Edition)
**Official Website:** [https://db4agent.top](https://db4agent.top)

## ⚠️ CRITICAL: Database & Driver Requirements

### Oracle AI Database 26ai Version

**Minimum required version: 23.26.2.0.0**

This system uses Oracle Deep Data Security (Deep Sec) features that require Oracle AI Database 26ai version **23.26.2 or later**. Earlier versions (including 23.26.1) have incomplete Deep Sec support. Introduced in v3.4.0 and extended through v3.7.5.

```sql
-- Check your database version
SELECT VERSION FROM PRODUCT_COMPONENT_VERSION WHERE PRODUCT LIKE 'Oracle%';
-- Must return: 23.26.2.0.0 or higher
```

### Python oracledb Driver

**Required version: oracledb 4.0.1**

v3.7.5 requires `oracledb` version **4.0.1** or later. Earlier versions (4.0.0) lack the `create_end_user_security_context` API and have TCPS protocol incompatibilities with Oracle 26ai.

```bash
pip install oracledb>=4.0.1
```

**Known limitations (awaiting upstream fixes):**
- **Thin mode TCPS**: oracledb thin mode has ORA-29019 protocol version incompatibility with Oracle 26ai on TCPS connections. Use TCP port 1521 instead.
- **Thick mode `set_end_user_security_context`**: Not yet implemented in thick mode. Use Method A (PL/SQL callback) instead.

**Future driver updates**: Oracle plans to release oracledb 4.1.0+ with full Deep Sec TCPS support. Monitor the [oracledb releases](https://github.com/oracle/python-oracledb/releases) for updates.

## Architecture Overview

```
AI Agent Infra with OracleDB — Community Edition v3.10.1
│
├── ENTITIES (LIST partitioned by ENTITY_TYPE, 8 partitions)
│   ├── P_MEMORY      — MEMORY
│   ├── P_KNOWLEDGE   — KNOWLEDGE
│   ├── P_TASK_OUTPUT — TASK_OUTPUT
│   ├── P_EXPERIENCE  — EXPERIENCE
│   ├── P_HARNESS     — HARNESS_TEMPLATE
│   ├── P_SPEC        — SPEC
│   ├── P_SKILL       — SKILL
│   └── P_OTHERS      — DEFAULT
│   PK: (ENTITY_ID, ENTITY_TYPE)  |  COL: WORKSPACE_ID -> WORKSPACES
│   8 reference-partitioned children:
│     ENTITY_EDGES, KNOWLEDGE_META, SPEC_META, HARNESS_META,
│     ENTITY_EMBEDDINGS, ENTITY_TAGS, SKILL_META, LOOP_META
│
├── WORKSPACES
│   ├── WORKSPACE_CONTEXT (append-only JSON)
│   └── WORKSPACE_TASKS (JRD updatable)
│
└── AGENT_SESSION (handoff chain)
    └── PREDECESSOR_SESSION_ID -> self (chain)
```

## Edition Comparison (v3.10.1)

### 1. Skill Storage & Distribution

Database-backed Skill registry with resource distribution.

| Component | Description |
|-----------|-------------|
| **SKILL_META** | Reference-partitioned from ENTITIES subtype `SKILL`; stores text content, resource URI, runtime, parameters, dependencies |
| **SKILL_DV** | JRD updatable duality view for Skill entities |
| **skill_api.py** | 12 functions: register, get, list, update, delete, resolve dependencies, validate, deprecate, + 4 admin-mode functions (register_via_admin, update_via_admin, delete_via_admin, upload_skill_resource_via_admin) |
| **skill_acquire_api.py** | 7 functions: discover, acquire_text, acquire_resource, acquire_full, + 3 admin-mode functions (discover_via_admin, acquire_via_admin) |

**Skill Access Flow (Community Edition):**
1. `discover_skills()` or `discover_skills_via_admin()` -> list available skills
2. `acquire_skill_text(skill_id)` or `acquire_skill_via_admin()` -> text content + metadata
3. `acquire_skill_resource(skill_id)` or `acquire_skill_via_admin(..., include_resource=True)` -> resource ZIP

**Skill Access Flow (Enterprise Edition only):**
1. `request_skill_access(agent_id, session_id, skill_id)` -> one-time TKN_xxx token
2. `consume_skill_token(token_id)` -> HTTP download URL (single use)
3. `GET /api/admin/skill/dl/{download_token}` -> download resource

**Private Skill Backup:** Skills with `visibility=PRIVATE` + `owned_by_agent=agent_id` are only visible to the owning agent. Data Grant predicate enforces isolation at DB level.

**Recovery Codes:** Agent registration returns 8 one-time `RC-XXXX-XXXX-XXXX` codes (SHA-256 hashed, DB_CRYPTO encrypted). Used for agent recovery when process/host fails.

### 2. Encrypted Database Credentials

Local database connection information is encrypted at rest in config.json.

| Component | Description |
|-----------|-------------|
| **connection_crypto.py** | 5 functions: encrypt/decrypt section, rotate key, auto-encrypt, get master key |
| **ConfigEncryption** class | PBKDF2-HMAC-SHA512 key derivation + AES-256-GCM authenticated encryption |
| **config.py** | Auto-detects encrypted `_encrypted` field; decrypts transparently; auto-upgrades plaintext |
| **Master key source** | `MASTER_DB_KEY` env var > `~/.oracle-infra/master.key` file > auto-generate on first run |

### 3. Database Access Security

Five-plus-one-layer database access security model with Deep Data Security:

| Layer | Component | Description |
|-------|-----------|-------------|
| L1 | **SKILL.md Policy** | Prohibits direct SQL/DML/DDL except during initial deployment |
| L2 | **4_grants.sql** | Restricted `AGENT_API` user: EXECUTE on packages + SELECT on tables only |
| L3 | **AUTHID DEFINER** | All PL/SQL packages execute with schema owner privileges |
| L4 | **6_deep_sec_policy.sql** | Deep Data Security (Data Grants + MAC): declarative row/column/cell-level access control, Mandatory Access Control, zero-trust (no context = no data) |
| L5 | **5_audit_policy.sql** | Unified Auditing `DIRECT_DML_BYPASS_DETECTION` for direct DML bypass |
| L6 | **`_sanitize_context_data()`** | Auto-redacts sensitive fields in `save_context()` |

### 3b. Deep Data Security — Agent Usage Guide

v3.4.0 introduced Deep Data Security. **The v3.3.0 VPD (Virtual Private Database / DBMS_RLS) security policy is DEPRECATED and has been removed.** The old `6_vpd_policy.sql` script no longer exists. All VPD policies (`WS_CTX_AGENT_VPD`, `ENTITIES_VISIBILITY_VPD`) and VPD predicate functions (`vpd_ws_ctx_agent`, `vpd_entities_visibility`) are superseded by Deep Sec Data Grants. Agents MUST understand how Deep Sec works to operate correctly.

#### How Deep Sec Works

Deep Sec uses **Data Grants** (declarative access policies) + **MAC** (Mandatory Access Control) + **End User Context** to enforce row-level, column-level, and cell-level security. When an Agent connects, the Python API layer automatically sets the agent's identity via `SET_AGENT_CONTEXT.set_agent_id()`, which populates `ORA_END_USER_CONTEXT` through an `o:onFirstRead` callback. Data Grants then filter query results based on this context.

**Zero trust**: If no agent context is set, Data Grants return **no data** (unlike old VPD which returned `1=1` = full exposure).

#### Current Enforcement Status (v3.10.1)

**Deep Sec is fully enforcing at the database level** via Direct Logon with Local End Users:

| Security Mechanism | Deployed? | Enforcing? | Details |
|---|---|---|---|
| 23 Data Grants | ✅ Yes | ✅ Yes | End User queries filtered by `ORA_END_USER_CONTEXT.username` predicates (includes collab_member_own and collab_group_member_access for COLLAB table access) |
| MAC (7 tables) | ✅ Yes | ✅ Yes | `SET USE DATA GRANTS ONLY` prevents view bypass for End Users |
| 3 Data Roles | ✅ Yes | ✅ Yes | Each End User has `agent_data_role` + `pool_agent_data_role` |
| End User Context + o:onFirstRead | ✅ Yes | ✅ Yes | Callback available for fallback AIADMIN path |
| Direct Logon End Users | ✅ Yes | ✅ Yes | One End User per agent; `ORA_END_USER_CONTEXT.username` = mapped agent ID |
| DEEP_SEC_SESSION_ROLE | ✅ Yes | ✅ Yes | CREATE SESSION granted to Data Roles for End User login |
| END_USER_MANAGER package | ✅ Yes | ✅ Yes | PL/SQL manages End User lifecycle (create/drop/get password) |
| Portal End User routing | ✅ Yes | ✅ Yes | `connection.py` auto-routes: agent context → End User; no context → AIADMIN |
| AUTHID DEFINER (AGENT_API) | ✅ Yes | ✅ Yes | AGENT_API can only access data through PL/SQL packages |
| Minimum-privilege user (AGENT_API) | ✅ Yes | ✅ Yes | No DML/DDL, EXECUTE-only on packages |
| Unified Audit | ✅ Yes | ✅ Yes | Audits direct DML on protected tables |

**Architecture**:
- Portal users connect as Deep Sec End User (Direct Logon, no IAM/TCPS/tokens)
- End User name = `UPPER(REPLACE(agent_id, '-', '_'))` (hyphens → underscores, uppercase)
- `connection.py`: `set_agent_context(agent_id)` → `get_end_user_connection()` → Data Grant auto-filtering
- Admin Dashboard uses AIADMIN pool (schema owner, unrestricted by Data Grants — correct Oracle behavior)
- Passwords stored in `SYSTEM_CONFIG` with key `end_user_pwd.{agent_id}` (readable only by AIADMIN)

#### What Agents Need to Know

1. **Agent identity is automatic**: `connection.py` calls `SET_AGENT_CONTEXT.set_agent_id()` on every connection acquired via `get_connection()`. Agents do NOT need to call this manually.

2. **Data visibility is scoped**: Each agent can only see:
   - Its own row in `AGENT_REGISTRY`
   - Workspaces where it is the current agent OR a collaboration group member
   - Entities that are PUBLIC, or PRIVATE/SHARED owned by the agent
   - Its own credentials (CREDENTIAL_VALUE column is **masked** — returns NULL)
   - Task plans owned by the agent or in collaboration branches
   - All skills (read-only for agents)
   - `SYSTEM_CONFIG` is **admin-only** — agents cannot SELECT it directly

3. **Column masking**: `AGENT_CREDENTIALS.CREDENTIAL_VALUE` is hidden from `agent_data_role`. Use `verify_credential()` or `issue_credential()` API functions instead.

4. **MAC prevents bypass**: `SET USE DATA GRANTS ONLY` is enabled on 7 tables. Even creating a view cannot bypass Data Grant policies.

5. **WORKSPACE_CONTEXT VISIBILITY**: The WORKSPACE_CONTEXT table has a VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED). The `WS_CTX_AGENT_ACCESS` Data Grant predicate enforces: (1) agent always sees own context regardless of VISIBILITY, (2) agent sees other agents' SHARED/PUBLIC context in collab group workspaces, (3) agent cannot see other agents' PRIVATE context even in the same collab group. This prevents one agent's private thoughts from being exposed to other agents in shared workspaces.

6. **Admin role has full access**: `admin_data_role` sees all data. The admin dashboard login uses this role.

#### Data Grant Summary for Agents

| Table | Agent Can See | Agent Cannot See |
|-------|--------------|-----------------|
| AGENT_REGISTRY | Own row only | Other agents' rows |
| WORKSPACE_CONTEXT | Own workspaces + collab groups; own context always visible; other agents' SHARED/PUBLIC context visible in collab workspaces; other agents' PRIVATE context blocked | Other agents' PRIVATE context in collab workspaces |
| ENTITIES | PUBLIC + own PRIVATE + shared in workspace | Other agents' PRIVATE entities |
| AGENT_CREDENTIALS | Own rows (CREDENTIAL_VALUE masked) | Other agents' credentials |
| SYSTEM_CONFIG | Nothing (admin only) | All rows |
| SKILL_META | All skills (read-only) | Cannot modify |
| CONTEXT_BRANCHES | Own workspaces + collab groups | Other agents' branches |
| TASK_PLANS | Own tasks + collab branches | Other agents' tasks |
| COLLAB_GROUP_MEMBERS | Own membership rows | Other agents' membership rows |
| COLLAB_GROUPS | Groups where member belongs | Groups without membership |

#### Deploying Deep Sec

```sql
-- Step 1: Grant Deep Sec privileges (as SYSDBA on DB server via sqlplus)
-- See 4_grants.sql for full list; key privileges:
GRANT CREATE DATA ROLE TO AIADMIN;
GRANT CREATE DATA GRANT TO AIADMIN;
GRANT CREATE ANY DATA GRANT TO AIADMIN;
GRANT ADMINISTER ANY DATA GRANT TO AIADMIN;
GRANT GRANT ANY DATA ROLE TO AIADMIN;
GRANT SET USE DATA GRANTS ONLY TO AIADMIN;
GRANT CREATE END USER TO AIADMIN;
GRANT CREATE END USER CONTEXT TO AIADMIN;
GRANT CREATE ANY END USER CONTEXT TO AIADMIN;
GRANT CREATE END USER SECURITY CONTEXT TO AIADMIN;
GRANT CREATE ANY CONTEXT TO AIADMIN;

-- Step 2: Deploy Deep Sec policy (as AIADMIN)
@scripts/deploy/6_deep_sec_policy.sql
```

#### Portal Agent Context — Data Isolation

The server has two access paths with different Deep Sec behavior:

| Path | DB Identity | Data Scope | Mechanism |
|------|-------------|------------|-----------|
| **Admin Dashboard** (`/login`) | AIADMIN (schema owner) | All data | Schema owner bypasses Data Grants |
| **Portal** (`/portal/login`) | Deep Sec End User | Agent-specific only | Data Grants + MAC auto-filter |

**How Portal isolation works:**
1. Each HTTP request calls `_set_context_from_session()` — sets agent context from session data
2. Portal session with `agent_id` → `connection.set_agent_context(agent_id)` → `get_end_user_connection()` → Data Grant auto-filtering
3. Admin session (no `agent_id`) → `connection.set_agent_context(None)` → AIADMIN pool → full access
4. Portal login: AIADMIN operations (create_session, create_workspace) run BEFORE setting agent context, then `_set_context_from_session()` switches to End User
5. Portal API operations that access WORKSPACES/SYSTEM_USERS tables temporarily use `connection.set_agent_context(None)` to switch to AIADMIN (Data Grant predicates on WORKSPACES use CURRENT_AGENT_ID which is NULL for most workspaces), then restore End User context after completion
6. This ensures Admin and Portal requests never interfere even on the same server process

**How new agents get Deep Sec:**
1. `agent_api.register_agent(agent_id, ...)` → inserts into `AGENT_REGISTRY` + calls `_ensure_end_user(agent_id)`
2. `_ensure_end_user` → `END_USER_MANAGER.ensure_end_user(agent_id)` → creates End User + grants data roles + stores password
3. End User name = `UPPER(REPLACE(agent_id, '-', '_'))` (hyphens → underscores, uppercase)
4. Password stored in `SYSTEM_CONFIG` key `end_user_pwd.{agent_id}` (readable only by AIADMIN)
5. Next Portal login with this agent → `get_end_user_connection()` → Deep Sec auto-filtering

#### Migrating from v3.3.0 VPD

```sql
-- Drop old VPD policies first
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'WORKSPACE_CONTEXT', 'WS_CTX_AGENT_VPD');
EXEC DBMS_RLS.DROP_POLICY('AIADMIN', 'ENTITIES', 'ENTITIES_VISIBILITY_VPD');
-- ... drop all VPD policies ...

-- Then deploy 4_grants.sql (adds Deep Sec privileges, removes SYSTEM_CONFIG grant)
-- Then deploy 6_deep_sec_policy.sql
-- Restart application server
```

## Admin/Agent Separation Architecture

v3.7.5+ introduces a mode system that separates Admin Agent (runs Web Portal, holds AIADMIN credentials) from Business Agent (independent process, only holds End User credentials).

### Modes

| Mode | Process | AIADMIN Credentials | Web Portal | Use Case |
|------|---------|-------------------|------------|----------|
| `standalone` | Single process | Yes | Yes | Development, single-node (default, backward compatible) |
| `admin` | Admin Agent | Yes | Yes | Production Admin node |
| `agent` | Business Agent | No (End User only) | No | Production Business Agent |

### Architecture

```
Admin Agent (mode=admin)
├── Web Portal
├── AIADMIN Connection Pool
└── Admin Token Generator
        │
        │ admin_token (secure)
        ▼
Encrypted Credential Distribution
        │
        ▼
Business Agent (mode=agent)
├── Agent Bootstrap CLI
├── End User Connection Pool
└── agent_config.json (encrypted)
    ✓ Data Grants enforced    ✗ No AIADMIN access
```

### Key APIs

| API | Module | Description |
|-----|--------|-------------|
| `generate_admin_token()` | agent_api | Generate admin registration token (AT_ + 32hex) |
| `verify_admin_token(token)` | agent_api | Constant-time verify admin token |
| `register_agent_via_admin(agent_id, name, token)` | agent_api | Register agent + return encrypted credentials + recovery codes |
| `recover_agent_via_admin(agent_id, code, token)` | agent_api | Recover agent with recovery code; resets End User password |
| `generate_recovery_codes(agent_id)` | agent_api | Generate 8 one-time RC-XXXX-XXXX-XXXX codes |
| `verify_recovery_code(agent_id, code)` | agent_api | Verify + consume one-time recovery code |
| `encrypt_credential_for_distribution(cred, token)` | connection_crypto | Encrypt End User credential using admin_token via PBKDF2 |
| `decrypt_credential_from_distribution(enc_cred, token)` | connection_crypto | Decrypt distributed credential using admin_token |
| `save_agent_config(config, path)` | connection_crypto | Encrypt and save agent config to local file |
| `load_agent_config(path)` | connection_crypto | Load and decrypt agent config |

### Admin API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/agent/register` | POST | Register Business Agent with admin token; returns encrypted End User credentials + recovery codes |
| `/api/admin/agent/recover` | POST | Recover agent with recovery code; resets End User password; returns new encrypted credentials |
| `/api/admin/token/generate` | POST | Generate new admin registration token (AIADMIN session required) |
| `/api/admin/token/rotate` | POST | Rotate admin token; Business Agents must re-register |
| `/api/admin/skill/list` | GET | List available skills (admin_token + optional agent_id/visibility filters) |
| `/api/admin/skill/{id}/acquire` | GET | Acquire skill content (admin_token, optional resource=1 for ZIP) |
| `/api/admin/skill/create` | POST | Create new skill (admin_token + metadata) |
| `/api/admin/skill/update` | POST | Update skill metadata (admin_token + skill_id + fields) |
| `/api/admin/skill/delete` | POST | Delete skill (admin_token + skill_id) |
| `/api/admin/skill/upload` | POST | Upload resource file (admin_token + skill_id + base64 content) |

### Agent Bootstrap CLI

```bash
# Register a new Business Agent
python agent_bootstrap.py register \
    --agent-id my-agent --agent-name "My Agent" \
    --admin-token AT_xxx --admin-url http://admin-host:18080

# Recover an agent using recovery code
python agent_bootstrap.py recover \
    --agent-id my-agent --recovery-code RC-XXXX-XXXX-XXXX \
    --admin-token AT_xxx --admin-url http://admin-host:18080

# Test agent connection
python agent_bootstrap.py test --config agent_config.json

# List available skills
python agent_bootstrap.py skill-list \
    --admin-token AT_xxx --admin-url http://admin-host:18080

# Acquire a skill
python agent_bootstrap.py skill-acquire \
    --skill-id ENT_xxx --admin-token AT_xxx --admin-url http://admin-host:18080

# Create a private skill (owned by agent)
python agent_bootstrap.py skill-create \
    --title "My Skill" --skill-name my_skill \
    --admin-token AT_xxx --admin-url http://admin-host:18080 \
    --visibility PRIVATE --owned-by-agent my-agent
```

### Mode-Aware connection.py

| Mode | AIADMIN Pool | End User Pool | agent_config.json |
|------|-------------|---------------|-------------------|
| standalone | Yes | Yes | No |
| admin | Yes | Yes | No |
| agent | No | Yes (from config) | Yes |

Agent mode: `get_connection()` returns End User connections from local encrypted `agent_config.json`. No AIADMIN pool initialized. `set_agent_context()` is a no-op (always End User). Skills acquired via Admin API (`skill_acquire_api.acquire_skill_via_admin()`) rather than direct DB access.

## Context Branching

Context Branching enables forking, merging, abandoning, and resuming conversation context branches within a workspace. This supports two core scenarios:

### Branch Lifecycle

```
fork → work → merge (success) → branch merged into target
fork → work → abandon (failure) → branch preserved as lesson reference
fork → work → pause → resume → continue work
```

### Key APIs

| API | Description |
|-----|-------------|
| `fork_branch(workspace_id, fork_context_id, branch_type, branch_name)` | Create a new branch from an existing context point |
| `merge_branch(source_branch_id, target_branch_id)` | Merge source branch into target; auto-detect conflicts |
| `abandon_branch(branch_id)` | Mark branch as ABANDONED (read-only, preserved as lesson) |
| `pause_branch(branch_id)` | Temporarily suspend work on a branch |
| `resume_branch(branch_id)` | Resume a paused branch |
| `diff_branches(branch_id_1, branch_id_2)` | Compare two branches and return differences |
| `detect_conflicts(source_branch_id, target_branch_id)` | Auto-detect entity conflicts between branches |
| `mark_as_lesson(branch_id)` | Manually mark a branch as a lesson reference |
| `extract_lessons(workspace_id)` | Automatically extract learnings from abandoned branches |

### Branch Types

| Type | Use Case |
|------|----------|
| EXPLORATION | Try a new approach or direction |
| ROLLBACK | Roll back to a prior context point and try again |
| HANDOFF | Hand off work from one agent to another |
| PARALLEL | Multiple agents working on different branches simultaneously |

### BRANCH_POINT Context Type

When a branch is forked, a `BRANCH_POINT` context entry is created in `WORKSPACE_CONTEXT` at the fork point. This marks the exact position where the branch diverged from the parent. The `WORKSPACE_CONTEXT.BRANCH_ID` column links all subsequent context entries to their branch.

### Usage: Single-Agent Rollback

```python
from lib.branch_api import fork_branch, merge_branch, abandon_branch, mark_as_lesson

# Agent hits a dead end — fork from a prior checkpoint
branch = fork_branch(
    workspace_id="WS_001",
    fork_context_id="CTX_042",  # The checkpoint to fork from
    branch_type="ROLLBACK",
    branch_name="try-alternative-approach"
)

# ... agent works on the branch ...

# If successful, merge back
merge_branch(source_branch_id=branch["branch_id"], target_branch_id="main")

# If failed, abandon and preserve as lesson
abandon_branch(branch_id=branch["branch_id"])
mark_as_lesson(branch_id=branch["branch_id"])
```

### Usage: Multi-Agent Handoff

```python
from lib.branch_api import fork_branch, merge_branch

# Agent A forks a branch for Agent B
branch_b = fork_branch(
    workspace_id="WS_001",
    fork_context_id="CTX_050",
    branch_type="HANDOFF",
    branch_name="agent-b-task"
)

# Agent B works on branch_b, Agent A continues on main
# ... later, Agent B completes and merges back
merge_branch(source_branch_id=branch_b["branch_id"], target_branch_id="main")
```

### Lesson Extraction from Abandoned Branches

```python
from lib.branch_api import extract_lessons

# Automatically extract learnings from all abandoned branches in a workspace
lessons = extract_lessons(workspace_id="WS_001")
# Returns: list of lesson objects with failure reasons, attempted paths, key decision points
```

### Components

| Component | Description |
|-----------|-------------|
| **CONTEXT_BRANCHES** table | Branch metadata and lifecycle (type, status, fork point, parent relationship) |
| **BRANCH_MERGE_LOG** table | Merge history with conflict details (COMPLETED/CONFLICT/ROLLED_BACK) |
| **BRANCH_COMPARISON** view | Unified comparison of two branches |
| **BRANCH_MANAGER** PL/SQL | 11 subprograms: fork/merge/abandon/pause/resume/diff/conflicts/lesson/fork-for-spec/validate-for-spec/fork-parallel |
| **branch_api.py** | Python API for full branch lifecycle + parallel branch operations |
| **/api/branch/*** | 17+ HTTP endpoints for branch operations |
| **/branches** | Dashboard page for branch management |
| **Portal "Restart from here"** | Fork from any chat message |
| **BRANCH_CLEANUP_JOB** | Daily cleanup of abandoned branches and orphaned references |

## Multi-Agent Collaboration

Multi-Agent Collaboration integrates Collaboration Groups with Branches, SDD (Spec), Task Plans, and Harness for coordinated multi-agent workflows. Five layers work together: **Spec** defines the goal, **Collaboration Group** organizes agents, **Branch** isolates exploration, **Task Plan** distributes execution, and **Harness** provides tools.

### Key APIs

| API | Module | Description |
|-----|--------|-------------|
| `create_collab_group(branch_id, spec_id)` | collab_api | Create group associated with a branch and spec |
| `add_group_member(branch_id)` | collab_api | Add member with their branch |
| `get_member_branches(group_id)` | collab_api | Get all members' branch info |
| `validate_group_against_spec(group_id)` | collab_api | Validate group progress against spec |
| `sync_group_context(group_id)` | collab_api | Sync member branch summaries to shared workspace |
| `fork_parallel_branches(workspace_id, agent_ids)` | branch_api | Create PARALLEL branches for multiple agents |
| `merge_parallel_branches(source_branch_ids, target_branch_id)` | branch_api | Merge multiple parallel branches with conflict detection |
| `get_parallel_diff(branch_ids)` | branch_api | Pairwise diff of parallel branches |
| `add_step(assigned_agent_id)` | task_plan_api | Assign a plan step to a specific agent |
| `distribute_plan_to_group(plan_id, group_id)` | task_plan_api | Distribute steps to group members round-robin |
| `create_spec_for_group(title, group_id)` | spec_api | Create a spec for a collaboration group |
| `validate_group_progress(spec_id, group_id)` | spec_api | Validate group's overall spec progress |
| `share_harness_to_group(entity_id, group_id)` | harness_api | Share a harness template to a group |
| `instantiate_harness_for_member(entity_id, member_agent_id, group_id)` | harness_api | Instantiate harness for a group member |

### Schema Additions

| Table | Column | Description |
|-------|--------|-------------|
| COLLAB_GROUPS | BRANCH_ID | Links group to its branch context |
| COLLAB_GROUPS | SPEC_ID | Links group to its spec |
| COLLAB_GROUP_MEMBERS | BRANCH_ID | Links member to their branch |
| TASK_STEPS | ASSIGNED_AGENT_ID | Assigns step to specific agent |
| TASK_PLANS | BRANCH_ID | Links plan to its branch |
| SPEC_META | BRANCH_ID | Links spec to its branch |

### Usage: Multi-Agent Parallel Exploration

```python
from lib import branch_api, collab_api, spec_api, task_plan_api

# 1. Create spec defining the goal
spec_id = spec_api.create_spec(title="API Design", acceptance_criteria=["design","implement","test"])

# 2. Create collaboration group (coordinator + spec)
group_id = collab_api.create_collab_group(
    name="API Team", group_type="TEAM",
    coordinator_agent_id="agent_lead", spec_id=spec_id
)

# 3. Fork parallel branches for each agent
result = branch_api.fork_parallel_branches(
    workspace_id="WS_001",
    agent_ids=["agent_a", "agent_b", "agent_c"],
    spec_id=spec_id
)

# 4. Add members with their branches
for b in result["branches"]:
    collab_api.add_group_member(group_id, b["agent_id"], branch_id=b["branch_id"])

# 5. Create plan and distribute to group
plan_id = task_plan_api.create_plan(agent_id="agent_lead", goal="Implement API")
status = task_plan_api.get_plan(plan_id)["status"]
task_plan_api.add_step(plan_id, status, "Design", 1, assigned_agent_id="agent_a")
task_plan_api.add_step(plan_id, status, "Implement", 2, assigned_agent_id="agent_b")
task_plan_api.add_step(plan_id, status, "Test", 3, assigned_agent_id="agent_c")

# 6. Monitor: validate group against spec
validation = collab_api.validate_group_against_spec(group_id)
print(f"Pass rate: {validation['pass_rate']}")

# 7. Merge successful branches
branch_ids = [b["branch_id"] for b in result["branches"]]
merge_result = branch_api.merge_parallel_branches(
    source_branch_ids=branch_ids,
    target_branch_id="trunk_branch_id"
)
```

## Community vs Enterprise Feature Matrix

| Feature | Community | Enterprise |
|---------|-----------|------------|
| Memory & Knowledge System | Yes | Yes |
| 5-Signal Unified Search | Yes | Yes |
| Spec Driven Development | Yes | Yes |
| Agent Elastic Management | Yes | Yes |
| Collaboration Groups | Yes | Yes |
| Multi-Agent Collaboration (Branch+Spec+Plan+Harness) | Yes | Yes |
| Workspace & Context | Yes | Yes |
| Admin/Agent Separation | Yes | Yes |
| Recovery Codes + Agent Recovery | Yes | Yes |
| Private Skill Backup | Yes | Yes |
| Skill Storage & Distribution | Yes (basic) | Yes (secure token) |
| Encrypted DB Credentials | Yes | Yes |
| Workspace Context Audit | No | Yes |
| License | Apache 2.0 | BSL 1.1 |

---

## v2.3.2 Key Addition: Web UI Optimization

| Feature | Description |
|---------|-------------|
| **Client-side pagination** | PAGE_SIZE=30 with Prev/Next + page number buttons. 7 data pages have single pagination; Agents page has triple pagination (registry/sessions/collabs tabs). |
| **Sticky table headers** | `position:sticky;top:0;z-index:2;background:var(--bg-card);box-shadow:0 2px 4px rgba(0,0,0,.3)` for all data tables |
| **Viewport height fix** | `body` from `min-height:100vh` to `height:100vh`; content areas get `min-height:0;height:calc(100vh - 120px)` |
| **Table spacing** | `border-collapse:separate;border-spacing:0` for consistent cell rendering |
| **Text color** | `color:#fff` for table cells and info-card divs on dark theme |
| **Login language persistence** | `localStorage` save on toggle; restore with `document.documentElement.lang` on load |

## v2.3.1 Key Features: Embedding Fix, Unified Search, Fulltext Search & Search API

**Vector Search Fix** — Fix embedding generation and vector search capabilities omitted during v2.0.0 architecture rewrite

**5-Signal Unified Search** — vector + fulltext + relational + tag + graph multi-signal fusion `search_unified` API:

| Signal | Weight | Source | Scoring |
|--------|--------|--------|---------|
| Vector | 0.4 | ENTITY_EMBEDDINGS via VECTOR_DISTANCE(COSINE) | 1 - cosine_distance |
| Fulltext | 0.25 | Oracle Text CONTAINS(title) + SCORE(1) | ft_score / 100 |
| Relational | 0.2 | KNOWLEDGE_META(domain,topic) + SPEC_META(scope,complexity) + ENTITIES(category,importance) | Domain/scope match + importance |
| Tag | 0.15 (included in relational) | ENTITY_TAGS | Tag overlap + query match |
| Graph | 0.15 | ENTITY_EDGES BFS from seed entity | 1/depth proximity + edge_count/10 connectivity boost |

`search_unified(text, top_k, domain, category, tags, graph_seed_entity_id, ...)` returns `scores{vector,fulltext,relational,tag,graph}` + `final_score`.

**Single-SQL Fusion Search** — `search_unified_sql()` has the exact same 5-signal fusion as `search_unified`, but completes via a single CTE SQL statement, eliminating multi-round Python-SQL round trips:
- candidates CTE: vector+fulltext+metadata main query
- tag_scores CTE: tag overlap scoring (GROUP BY)
- edge_counts CTE: edge count (GROUP BY)
- graph_prox CTE: graph proximity (UNION ALL depth=1+2)
- Final SELECT: weighted scoring + ORDER BY final_score DESC

**LLM Context Economics** — Multi-round tool calls during retrieval are a hidden cost for LLM agents: each call's request/response consumes tokens, intermediate step noise pollutes the context window, and cumulative overhead may squeeze reasoning space or cause context overflow. Single-SQL fusion search compresses 5 Python-SQL round trips into 1 database call, reduces tool-call token overhead by 60-80%, eliminates intermediate-step context pollution, and lets agents reserve token budget for reasoning and decision-making.

**Fulltext Search** — `search_fulltext()` uses Oracle Text CONTAINS + SCORE for fulltext relevance search

**Embedding Fix** — EMBEDDING_MANAGER PL/SQL SUBSTR strips double brackets + named binds fix for ORA-01722 + search_similar/search_hybrid/search_multi_type/search_by_entity_id

In-db embedding generation and vector search capabilities were omitted during the v2.0.0 architecture rewrite. v2.3.1 fixes and enhances:

| Feature | Description |
|---------|-------------|
| EMBEDDING_MANAGER PL/SQL | `generate_and_store` fix: SUBSTR strips double brackets + VECTOR variable assignment; `cosine_similarity`/`batch_embed_entities`/`get_stats` |
| embedding_api.py named binds | All `:1,:2,:3` changed to `:eid,:etype,:vec` etc., resolving oracledb thin mode ORA-01722 |
| search_by_entity_id() | Search similar entities based on existing entity vector, auto-exclude self |
| search_hybrid() | Vector+keyword hybrid search, adjustable weights, returns 3D scoring (vector/keyword/hybrid) |
| search_multi_type() | Cross-type vector search (MEMORY/KNOWLEDGE/SPEC), returned grouped by type |
| EMBEDDING_GENERATION_JOB | Auto-generates embeddings for MEMORY/KNOWLEDGE entities every 2 hours |
| search_fulltext() | Oracle Text CONTAINS + SCORE fulltext search, supports boolean/fuzzy/stem |
| search_unified() | 5-Signal Unified Search, adjustable weights, returns per-signal independent score + final score |
| search_api.py | Unified search entry point, 10 strategies (vector/fulltext/keyword/graph/hybrid/unified/unified_sql/relational/multi_type/auto), automatic strategy detection |
| 19 embedding tests | Covering generation, storage, retrieval, similarity search, hybrid search, cross-type, batch processing, dimension detection |
| 31 unified search tests | Covering 5-signal independent verification, domain/category/tags filtering, graph proximity, custom weights, Single-SQL fusion search |
| 42 search API tests | Covering strategy metadata, auto-detection, per-strategy invocation, result structure, unified_sql strategy |


## Multi-Agent Encryption & Key Sharing

### How DB_CRYPTO Works with Multiple Agents

All agents connecting to the **same database** automatically share the same `DB_CRYPTO` encryption key (stored in `SYSTEM_CONFIG`). This means:

| **Agent A** encrypts agent credential → `DB_CRYPTO.encrypt('agent_api_key')`
- **Agent B** on a different server can decrypt it → `DB_CRYPTO.decrypt(ciphertext)`
- No key files to copy, no environment variables to sync

### Key Safety Guarantees

| Scenario | Behavior |
|----------|----------|
| New Agent connects to existing DB | Key already exists in `SYSTEM_CONFIG` → reuses it, no data loss |
| Multiple Agents call `encrypt()` simultaneously | `DUP_VAL_ON_INDEX` exception handler prevents key overwrite |
| Agent loses local `master.key` | Only affects `config.json` decryption; DB_CRYPTO is unaffected |
| Database migration (expdp/impdp) | `SYSTEM_CONFIG` rows including `db_crypto_master_key` are migrated → all encrypted data works |

### What Depends on Local Master Key vs DB_CRYPTO

| Data | Encryption | Key Location | Shared? |
|------|-----------|--------------|---------|
| `config.json` database credentials | `connection_crypto.py` | `~/.oracle-infra/master.key` or `MASTER_DB_KEY` env | No (per-server) |
| `AGENT_CREDENTIALS.CREDENTIAL_VALUE` | `DB_CRYPTO` | `SYSTEM_CONFIG` table | Yes (all DB connections) |
| `SYSTEM_USERS` password hash | PBKDF2-HMAC-SHA256 (one-way) | Salt stored in `SYSTEM_USERS` row | N/A (verify only) |

### Key Rotation

```sql
-- WARNING: Re-encrypt all data after rotation!
-- 1. Decrypt all encrypted data
-- 2. EXEC DB_CRYPTO.rotate_key();
-- 3. Re-encrypt all data with new key

-- Example: Rotate and re-encrypt agent credential
DECLARE
    v_plain VARCHAR2(4000);
    v_new_cipher VARCHAR2(4000);
BEGIN
    SELECT DB_CRYPTO.decrypt(CREDENTIAL_VALUE) INTO v_plain FROM AGENT_CREDENTIALS WHERE CREDENTIAL_ID = 'CRED_001';
    DB_CRYPTO.rotate_key();
    SELECT DB_CRYPTO.encrypt(v_plain) INTO v_new_cipher FROM DUAL;
    UPDATE AGENT_CREDENTIALS SET CREDENTIAL_VALUE = v_new_cipher WHERE CREDENTIAL_ID = 'CRED_001';
    COMMIT;
END;
/
```

### Agent First-Use Checklist

When a new Agent acquires this Skill and connects to a database:

1. **Call `check_deployment()`** first → if deployed, do NOT re-run deploy scripts
2. **If deploying fresh** → `DBMS_CRYPTO` grant is required (in prerequisites)
3. **If connecting to existing DB** → `DB_CRYPTO` key already exists, all encrypted data is accessible
4. **If migrating to new DB** → export `SYSTEM_CONFIG` rows with `db_crypto_*` keys alongside encrypted data

## Agent Retrieval Guide

When an AI Agent needs to search for information, **always prefer `unified_sql` strategy** — it fuses all 5 signals in a single database call:

```python
from lib.search_api import search

# RECOMMENDED: Single-SQL 5-signal fusion (production)
results = search("database partitioning", strategy="unified_sql", top_k=10)
# Returns: scores{vector, fulltext, relational, tag, graph} + final_score + engine="single_sql"

# With filters
results = search("encryption", strategy="unified_sql", domain="security", category="database")

# With graph proximity from a seed entity
results = search("memory fusion", strategy="unified_sql", graph_seed_entity_id="ABC123")

# DEBUGGING ONLY: Multi-round fusion (observe individual signal scores)
results = search("database partitioning", strategy="unified", top_k=10)

# CONVENIENCE: Auto-detect best strategy
results = search("partition*", strategy="auto")
```

**Why `unified_sql` is the default recommendation**:

| Aspect | `unified_sql` (recommended) | `unified` (debug only) |
|--------|---------------------------|----------------------|
| Database calls | **1** | 5+ |
| Scoring location | Server-side (database kernel) | Client-side (Python) |
| Latency | Low (70-85% reduction) | High (5 round trips) |
| Token overhead | Minimal | 60-80% more tool-call tokens |
| Context pollution | None | Intermediate results pollute LLM context |
| Use case | **Production retrieval** | Debugging individual signal scores |

**Strategy selection guide**:

| Scenario | Strategy | Why |
|----------|----------|-----|
| General information retrieval | `unified_sql` | Best relevance, lowest latency |
| Domain-specific search | `unified_sql` + `domain=` | Filters applied server-side |
| Cross-type search (MEMORY+KNOWLEDGE+SPEC) | `unified_sql` | Single query across all types |
| Exact keyword/phrase | `fulltext` | Oracle Text boolean operators |
| Pure semantic similarity | `vector` | No fulltext overhead |
| Relationship/neighborhood | `graph` | BFS traversal from seed entity |
| Unknown query type | `auto` | Auto-detects best strategy |

## v2.3.0 Key Additions: SDD, Elastic Agents, Collaboration

| Feature | Description |
|---------|-------------|
| Spec Driven Development | SPEC_META (reference-partitioned), SPEC_PLAN_LINKS (many-to-many with LINK_TYPE), SPEC_DV (JRD updatable) |
| Agent Elastic Management | DORMANT (hibernate, preserve context) / POOL (stateless, skills_tags matching), AGENT_CREDENTIALS (encrypted, auto-expiry) |
| Collaboration Groups | COLLAB_GROUPS + COLLAB_GROUP_MEMBERS, shared Workspace (COLLAB_GROUP) + personal Workspace (PERSONAL_IN_GROUP) |
| Agent Credentials | ReversibleEncryption, SCOPE={access_level, restricted_domains, max_clearance}, auto-revocation on DORMANT |
| Scheduler Jobs | DORMANT_AGENT_JOB (30-min timeout), CREDENTIAL_CLEANUP_JOB (daily purge) |
| Visualization | Specs + Collab pages, /api/specs + /api/collab, inline detail expansion (Tasks pattern), bilingual sidebar |
| Auth Security | SHA256 password hash verification (was prefix-only), admin default password: admin123 |

## v2.2.0 Key Additions: Workspace & Context Continuity

| Feature | Description |
|---------|-------------|
| WORKSPACES | Isolated execution environments for agents with shared/isolated modes |
| ISOLATION_MODE | SHARED (cross-workspace visibility) or ISOLATED (strict boundary) |
| WORKSPACE_CONTEXT | Append-only context chain (CHECKPOINT, HANDOFF, SUMMARY, ERROR_STATE, AUTO_SAVE) |
| Agent Handoff | Session chain via PREDECESSOR_SESSION_ID; context auto-loaded on create_session |
| JRD Updatable Views | WORKSPACE_DV, MEMORY_DV, KNOWLEDGE_DV support INSERT/UPDATE via Document API |
| ENTITIES.WORKSPACE_ID | FK to WORKSPACES; all entity queries scoped by workspace when ISOLATED |

## JSON Strategy

| Aspect | Strategy |
|--------|----------|
| Storage | Native JSON/OSON columns (ENTITY_DATA, CONTEXT_DATA, etc.) |
| Write | `json.dumps()` -> string bind variable (avoids DPY-3002) |
| Read | oracledb returns `dict` for JSON columns; `str` for JSON expressions |
| Modify | `JSON_TRANSFORM` (not `JSON_MERGEPATCH` -- causes OSON v2 DPY-3021) |
| Document API | JRD (JSON Relational Duality) for updatable views: WORKSPACE_DV, MEMORY_DV, KNOWLEDGE_DV |
| Context Chain | Raw SQL INSERT/SELECT (not JRD); append-only CONTEXT_DATA in WORKSPACE_CONTEXT |

## Partitioning Scheme

| Table | Partitioning Strategy |
|-------|-----------------------|
| ENTITIES | LIST by ENTITY_TYPE (8 partitions: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE, SPEC, SKILL, OTHERS) |
| ENTITY_EDGES | REFERENCE from ENTITIES |
| KNOWLEDGE_META | REFERENCE from ENTITIES |
| ENTITY_EMBEDDINGS | REFERENCE from ENTITIES |
| SPEC_META | REFERENCE from ENTITIES [NEW v2.3.0] |
| HARNESS_META | REFERENCE from ENTITIES |
| ENTITY_TAGS | REFERENCE from ENTITIES |
| TASK_PLANS | RANGE by STATUS |
| TASK_STEPS | REFERENCE from TASK_PLANS |
| AGENT_SESSION | RANGE by IS_ACTIVE |
| ENTITY_ACCESS_LOG | RANGE by CREATED_AT (monthly) |

**Note:** 8 reference-partitioned children (ENTITY_EDGES, KNOWLEDGE_META, ENTITY_EMBEDDINGS, SPEC_META, HARNESS_META, ENTITY_TAGS). Non-partitioned tables: AGENT_REGISTRY, AGENT_CREDENTIALS, AGENT_PERMISSION_LOG, AGENT_COLLABORATION, COLLAB_GROUPS, COLLAB_GROUP_MEMBERS, SPEC_PLAN_LINKS, SYSTEM_USERS, SYSTEM_CONFIG, WORKSPACES, WORKSPACE_CONTEXT, WORKSPACE_TASKS, TASK_CONTEXT_SNAPSHOTS, TASK_TOOL_CALLS, TASK_DEPENDENCIES, TAGS.

## Composite Primary Keys

| Table | Composite PK | Notes |
|-------|-------------|-------|
| ENTITIES | (ENTITY_ID, ENTITY_TYPE) | Unified table; ENTITY_TYPE is partition key |
| ENTITY_EDGES | (EDGE_ID, SOURCE_ID) | SOURCE_ID is part of PK for reference partitioning |
| TASK_PLANS | (PLAN_ID, STATUS) | STATUS is partition key; included in PK |
| TASK_STEPS | (STEP_ID, PLAN_ID, PLAN_STATUS) | Composite PK includes parent PK columns for reference partitioning |
| AGENT_SESSION | (SESSION_ID, IS_ACTIVE) | IS_ACTIVE is partition key; included in PK |
| WORKSPACE_TASKS | (WORKSPACE_ID, PLAN_ID) | Junction table; FK to both WORKSPACES and TASK_PLANS |

**Note:** Global unique constraints (UK_ENTITY_ID, UK_EDGE_ID, etc.) enforce uniqueness across partitions. ON DELETE CASCADE on all child tables (required for JRD updatable views).

## JRD Duality Views (6 Views)

| View | Mode | Root Table | Nested Objects |
|------|------|------------|----------------|
| WORKSPACE_DV | updatable | WORKSPACES | WORKSPACE_TASKS (via FK) |
| CONTEXT_DV | read-only | WORKSPACE_CONTEXT | -- (flat view) |
| MEMORY_DV | updatable | ENTITIES (ENTITY_TYPE=MEMORY) | ENTITY_TAGS, ENTITY_EDGES |
| KNOWLEDGE_DV | updatable | ENTITIES (ENTITY_TYPE=KNOWLEDGE) | ENTITY_TAGS, ENTITY_EDGES |
| SPEC_DV | updatable | ENTITIES (ENTITY_TYPE=SPEC) [NEW v2.3.0] | SPEC_META, SPEC_PLAN_LINKS |
| COLLAB_GROUP_DV | updatable | COLLAB_GROUPS [NEW v2.3.0] | COLLAB_GROUP_MEMBERS |

**Notes:**
- 26ai annotations (`@insert`, `@update`, `@delete`) required on columns for write operations
- JRD does not support JOINs in nested subqueries; use FK-based nesting only
- WORKSPACE_CONTEXT is excluded from WORKSPACE_DV because it is append-only (use raw SQL)
- JRD views must include all PK columns of root table
- CONTEXT_DV is read-only (no 26ai write annotations)

## ⚠️ CRITICAL: Database Access Policy

### 1. NEVER Bypass the API Layer

**All data operations MUST go through the Python API layer (`scripts/lib/*.py`) or PL/SQL packages. Direct SQL/DML/DDL operations on database tables are STRICTLY PROHIBITED except during initial schema deployment (`scripts/deploy/*.sql`).**

Why this matters:
- **Business logic bypass**: Direct INSERT/UPDATE/DELETE skips permission checks, audit logging, branch context tracking, and data validation enforced by the API layer
- **Data corruption**: The API layer maintains invariants (e.g., WORKSPACE_CONTEXT append-only, ENTITY_EDGES referential integrity, BRANCH_MERGE_LOG consistency) that direct SQL would violate
- **Security breach**: AGENT_PERMISSION_MANAGER.check_entity_access() is bypassed by direct SELECT, exposing PRIVATE memories from other agents
- **Audit gap**: Direct operations bypass CONTEXT_AUDIT logging, making actions untraceable

### 2. Database Connection Credentials Must Not Be Injected into Agent Context

When saving context via `save_context()`, any context_data containing keys like `password`, `dsn`, `connection`, `credential`, `secret`, `key`, or `token` will be automatically masked by `DataMaskingService`. Agents MUST NOT store database connection strings or credentials in WORKSPACE_CONTEXT.

### 3. Use the Restricted Database User for Agent Connections

A restricted `agent_api` database user should be used for runtime connections. This user:
- Has **EXECUTE only** on PL/SQL API packages (no direct table DML)
- Has **SELECT only** on tables needed for read operations
- **Cannot** CREATE TABLE, CREATE VIEW, ALTER, DROP, INSERT, UPDATE, DELETE directly on tables
- All writes go through `AUTHID DEFINER` PL/SQL packages which execute with schema owner privileges while enforcing business rules

See `scripts/deploy/4_grants.sql` for the restricted user setup.

### 4. Deployment Scripts Are the Only Exception

The `scripts/deploy/*.sql` scripts are the ONLY authorized direct SQL operations, and they MUST only be run:
- During initial deployment on an empty schema
- By a human administrator (not by an Agent)
- After verifying no existing deployment exists (see Pre-Deployment Safety Check below)

---

## ⚠️ CRITICAL: Pre-Deployment Safety Check

**Before running ANY deploy script, an Agent MUST check whether the database already has an existing deployment. Re-running deploy scripts on an existing database will DESTROY all data (agents, sessions, knowledge, workspaces, skills).**

### Python API Check

```python
from lib.deploy_api import check_deployment

result = check_deployment()
# result = {
#   "deployed": True/False,
#   "schema_version": "3.7.3" or None,
#   "table_count": 34,
#   "agent_count": 5,
#   "user_count": 3,
#   "recommendation": "..."
# }

if result["deployed"]:
    # DO NOT run deploy scripts! Database already has data.
    # Only register this Skill if needed:
    from lib.skill_api import register_skill
    skill_id = register_skill(name="my-skill", ...)
else:
    # Safe to deploy from scratch
    pass
```

### HTTP Endpoint Check

```bash
# Public API — no authentication required
curl http://localhost:18080/api/agent/deployment-check
```

Response:
```json
{
  "deployed": true,
  "schema_version": "3.7.3",
  "table_count": 34,
  "agent_count": 5,
  "user_count": 3,
  "recommendation": "EXISTING DEPLOYMENT DETECTED (v3.7.5, 35 tables, 5 agents, 3 users). DO NOT re-run deploy scripts..."
}
```

### SQL-Level Protection

The deploy script `1_schema.sql` now includes an automatic check. If `SYSTEM_CONFIG` table exists with a `schema_version` key, the script will **abort** with an error:

```
EXISTING DEPLOYMENT DETECTED: schema_version = 3.7.3
Deployment aborted: existing deployment found. Schema version: 3.7.3
```

To force reinitialize (DESTRUCTIVE — requires human admin approval):
```sql
BEGIN
    FOR r IN (SELECT table_name FROM user_tables WHERE table_name != 'DBTOOLS$MCP_LOG') LOOP
        EXECUTE IMMEDIATE 'DROP TABLE "' || r.table_name || '" CASCADE CONSTRAINTS PURGE';
    END LOOP;
END;
/
```

### Agent Decision Flow

```
Agent receives Skill → check_deployment() → deployed?
├── YES → Register skill only, DO NOT deploy
└── NO  → Run full deployment (1_schema → 2_api → 3_jobs → 4_harness)
```

---

## Quick Start

### Prerequisites: Database User Authorization

**CRITICAL: Database user authorization must be completed BEFORE deploying schema. Connect to the database as SYSDBA using sqlplus on the database server directly. DO NOT use SQLcl MCP or any remote client to connect as SYS — doing so can corrupt the PDB process state and cause ORA-00600 errors.**

```sql
-- Run on the database server as SYSDBA via sqlplus:
-- sqlplus / as sysdba
-- ALTER SESSION SET CONTAINER=<PDB_NAME>;

GRANT CREATE JOB TO <db_user>;
GRANT UNLIMITED TABLESPACE TO <db_user>;
GRANT EXECUTE ON CTXSYS.CTX_DDL TO <db_user>;
GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <db_user>;
```

| Privilege | Purpose |
|-----------|---------|
| `CREATE JOB` | Required by `3_jobs.sql` to create scheduler jobs |
| `UNLIMITED TABLESPACE` | Required for partitioned tables and LOB storage |
| `EXECUTE ON CTXSYS.CTX_DDL` | Required by `1_schema.sql` for Oracle Text CONTEXT index |

**WARNING:**
- Never use SQLcl MCP to connect as SYS or execute GRANT statements. This has been empirically shown to cause PDB process corruption (ORA-00600 [13272]).
- All SYS-level operations must be performed via sqlplus on the database server.
- SQLcl MCP is safe for schema deployment (`1_schema.sql`, `2_api.sql`, `3_jobs.sql`) and query/DML operations under the application user.

### Deploy Schema (3 Phases)

```sql
-- Phase 1: Schema (tables, views, indexes, property graph, seed data)
@scripts/deploy/1_schema.sql

-- Phase 2: PL/SQL Packages
@scripts/deploy/2_api.sql

-- Phase 3: Scheduler Jobs
@scripts/deploy/3_jobs.sql
```

### Install Python

```bash
pip install oracledb
```

### Configure

```bash
export ORACLE_DSN="//<db_host>:<db_port>/<db_service>"
export ORACLE_USER="<db_user>"
export ORACLE_PASSWORD="<db_password>"
```

### Run Tests

```bash
cd scripts && python -m tests.test_all
```

### Start Web Server

```bash
./start_web_server.sh start    # Start (daemon)
./start_web_server.sh status   # Status + config
./start_web_server.sh stop     # Stop
./start_web_server.sh restart  # Restart
```

## Project Structure

```
ai-agent-infra-community/
  scripts/
    deploy/
      1_schema.sql              # 35 tables, 6 JRD views, indexes, property graph, seed data
      2_api.sql                 # 14 PL/SQL packages
      3_jobs.sql                # 16 scheduler jobs
      4_harness_templates.sql   # HARNESS_META + 5 built-in harness templates
    lib/
      config.py                 # Unified Config dataclass with env var overrides
      connection.py             # oracledb connection pool + Decimal sanitization helpers
      memory_api.py             # Memory CRUD on ENTITIES, workspace_id support
      knowledge_api.py          # Knowledge CRUD + graph + edges, workspace_id support
      agent_api.py              # Agent registration, sessions, handoff, collaboration, credentials, hibernate/wake, pool
      task_plan_api.py          # Task plans, steps, snapshots, tool calls, dependencies
      security.py              # DataMaskingService, ReversibleEncryption, password hashing
      harness_api.py            # Harness template CRUD, instantiate, derive, validate
      graph_api.py              # Property Graph API with GRAPH_TABLE SQL operator (9 functions)
      workspace_api.py          # Workspace lifecycle, context chains, handoff, recovery (11 functions)
      spec_api.py              # Spec CRUD, plan linkage, validation, derivation (10 functions) [NEW v2.3.0]
      collab_api.py             # Collaboration groups, members, shared memory (10 functions) [NEW v2.3.0]
      embedding_api.py          # Vector embedding generation, storage, search (15 functions) [NEW v2.3.2]
      search_api.py             # Unified search entry point, 10 strategies with auto-detection (3 functions) [NEW v2.3.2]
    tests/
      test_connection.py        # Connection pool tests (6)
      test_memory.py            # Memory CRUD tests (8)
      test_knowledge.py         # Knowledge CRUD tests (8)
      test_agent.py             # Agent registration/session tests (8)
      test_security.py          # Security feature tests (5)
      test_harness.py           # Harness template tests (6)
      test_graph.py             # Property Graph tests (8)
      test_workspace.py         # Workspace & context tests (12)
      test_spec.py              # Spec CRUD + plan linkage tests (9) [NEW v2.3.0]
      test_collab.py            # Collab group + shared memory tests (12) [NEW v2.3.0]
      test_credential.py        # Credential + hibernate/wake/pool tests (9) [NEW v2.3.0]
      test_embedding.py         # Embedding generation, search, hybrid, multi-type tests (19) [NEW v2.3.2]
      test_unified_search.py     # 5-signal unified hybrid search tests (20) [NEW v2.3.2]
      test_search_api.py          # Search API strategy tests (42) [NEW v2.3.2]
      test_all.py               # Master runner (16 suites, 121 total)
    visualization/
      server.py                 # HTTP server (session auth, page routing, JSON API, bilingual, pagination)
      templates/
        login.html              # Card-style login page
        knowledge.html          # Knowledge: list/graph dual view + inline detail + pagination
        memory.html             # Memory: list/graph dual view + inline detail + category filter + pagination
        agents.html             # Agents: Bootstrap tabs (registry/sessions/collabs) + triple pagination
        tasks.html              # Tasks: Accordion with step details + tool I/O + pagination
        workspaces.html         # Workspaces: expandable detail rows + context timeline + pagination
        graph.html              # Graph Explorer: stats + search + vis-network + detail panel
        specs.html              # Specs: list/detail tabs + plan linkage + pagination [NEW v2.3.0]
        collab.html             # Collab: groups/members/shared memory + pagination [NEW v2.3.0]
      static/
        style.css               # Dark theme CSS variables + sidebar styles
        vis-network.min.js      # Vis.js network visualization library
```

## Database Schema (35 Tables)

### Core Tables (7)

| Table | Purpose | Partitioning |
|-------|---------|-------------|
| ENTITIES | Unified entity store (MEMORY,KNOWLEDGE,TASK_OUTPUT,EXPERIENCE,HARNESS_TEMPLATE,SPEC,OTHER) | LIST by ENTITY_TYPE |
| ENTITY_EDGES | Directed relationships between entities | REFERENCE from ENTITIES |
| KNOWLEDGE_META | Knowledge metadata (domain,topic,difficulty) | REFERENCE from ENTITIES |
| ENTITY_EMBEDDINGS | Vector embeddings for semantic search | REFERENCE from ENTITIES |
| SPEC_META | Specification metadata (version,status,acceptance_criteria,constraints) [NEW v2.3.0] | REFERENCE from ENTITIES |
| HARNESS_META | Harness template metadata | REFERENCE from ENTITIES |
| ENTITY_TAGS | Tags for categorization and filtering | REFERENCE from ENTITIES |

### System Tables (3)

| Table | Purpose |
|-------|---------|
| SYSTEM_USERS | User accounts with SHA256 password hashes |
| SYSTEM_CONFIG | Key-value configuration store |
| TAGS | Tag definitions |

### Agent Tables (5)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| AGENT_REGISTRY | Agent definitions + elastic management | +5 cols: CREATED_BY_AGENT_ID, AGENT_ROLE, CURRENT_USER_ID, POOL_CONFIG, LAST_ACTIVE_AT |
| AGENT_CREDENTIALS | Encrypted credential storage [NEW v2.3.0] | CREDENTIAL_ID, AGENT_ID, USER_ID, CREDENTIAL_TYPE, CREDENTIAL_VALUE (encrypted), SCOPE (JSON), EXPIRES_AT |
| AGENT_SESSION | Session with handoff chain | SESSION_ID, AGENT_ID, CONTEXT (JSON), LAST_ACTIVE_AT [NEW v2.3.0] |
| ENTITY_ACCESS_LOG | Audit trail of entity access | LOG_ID, SESSION_ID, ACTION_TYPE, RESOURCE_TYPE, RESOURCE_ID |
| AGENT_PERMISSION_LOG | Agent action audit trail | LOG_ID, AGENT_ID, ACTION, STATUS_CODE, DETAILS |

### Collaboration Tables (3)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| AGENT_COLLABORATION | Inter-agent collaboration records | COL_ID, SOURCE_AGENT_ID, TARGET_AGENT_ID, COL_TYPE, ENTITY_ID, CONTEXT |
| COLLAB_GROUPS | Collaboration group definitions [NEW v2.3.0] | GROUP_ID, GROUP_NAME, GROUP_TYPE, WORKSPACE_ID, SHARING_POLICY, STATUS |
| COLLAB_GROUP_MEMBERS | Group membership [NEW v2.3.0] | MEMBER_ID, GROUP_ID, AGENT_ID, ROLE, PERSONAL_WORKSPACE_ID |

### Workspace Tables (3)

| Table | Purpose |
|-------|---------|
| WORKSPACES | Isolated environments (CONVERSATION,PROJECT,TASK_CHAIN,AUTONOMOUS,COLLAB_GROUP,PERSONAL_IN_GROUP) |
| WORKSPACE_CONTEXT | Append-only context chain (CHECKPOINT,HANDOFF,SUMMARY,ERROR_STATE,AUTO_SAVE) |
| WORKSPACE_TASKS | Junction: workspaces ↔ task plans |

### Task Tables (5)

| Table | Purpose |
|-------|---------|
| TASK_PLANS | Plan definitions |
| TASK_STEPS | Plan steps (composite PK: STEP_ID, PLAN_ID, PLAN_STATUS) |
| TASK_CONTEXT_SNAPSHOTS | Step execution context |
| TASK_TOOL_CALLS | Tool invocation records |
| TASK_DEPENDENCIES | Step dependency graph |

### Spec Tables (1)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| SPEC_PLAN_LINKS | Spec↔Plan many-to-many [NEW v2.3.0] | SPEC_ID, PLAN_ID, LINK_TYPE (DRIVES/VALIDATES/CONSTRAINS/EXTENDS), LINK_STRENGTH, UK=(SPEC_ID,PLAN_ID,LINK_TYPE) |

### Loop Tables (5) [NEW v3.7.0, extended v3.7.5]

| Table | Purpose |
|-------|---------|
| LOOP_META | Loop definitions: name, stop conditions (max_iterations, max_tokens, max_duration_seconds), evaluation config |
| LOOP_RUNS | Loop execution instances: status, start/end time, token usage, iteration count |
| LOOP_ITERATIONS | Per-iteration records: input, output, evaluation result, tokens consumed, duration |
| LOOP_HOOKS | Lifecycle hook definitions: hook type, target function, configuration |
| TASK_LOOP_BINDING | Task-step to loop binding: BINDING_ID, STEP_ID, LOOP_ID, BINDING_TYPE, AUTO_START |

## PL/SQL Packages (14 Packages)

| Package | Function Count | Key Functions |
|---------|---------------|---------------|
| MEMORY_FUSION_ENGINE | 7 | fuse_similar_memories, decay_memories, reinforce_memory, search_memories, get_memory_stats, consolidate_memories, archive_old_memories |
| KNOWLEDGE_BASE_API | 5 | validate_knowledge, link_knowledge, get_knowledge_graph, find_contradictions, resolve_contradiction |
| AGENT_PERMISSION_MANAGER | 5 | check_permission, grant_permission, revoke_permission, get_agent_permissions, audit_permissions |
| SESSION_CLEANUP | 4 | cleanup_expired_sessions, cleanup_orphaned_entities, vacuum_embeddings, purge_audit_log |
| WORKSPACE_MANAGER | 10 | create_workspace, get_workspace, update_workspace, save_context, get_context_chain, get_latest_context, create_handoff_session, recover_workspace, link_task_to_workspace, cleanup_workspace |
| SPEC_MANAGER [NEW v2.3.0] | 8 | create_spec, get_spec, update_spec, validate_spec, derive_spec, create_plan_from_spec, link_spec_to_plan, get_spec_plan_links |
| COLLAB_GROUP_MANAGER [NEW v2.3.0] | 6 | create_group, get_group, update_group, add_member, remove_member, get_group_members |
| EMBEDDING_MANAGER [NEW v2.3.2] | 5 | generate_embedding, generate_and_store, cosine_similarity, batch_embed_entities, get_stats |
| LOOP_MANAGER [NEW v3.7.0, extended v3.7.5] | ~22 | 6 evaluation types via loop_api.py | create_loop, get_loop, update_loop, delete_loop, list_loops, start_run, get_run, stop_run, list_runs, add_iteration, get_iteration, list_iterations, evaluate_iteration, register_hook, get_hooks, trigger_hook, unregister_hook, get_loop_stats, get_stuck_loops, cleanup_finished_loops |

## Python API (24 Modules, 131+ Functions)

### connection.py

```python
def get_connection() -> oracledb.Connection
def release_connection(conn: oracledb.Connection) -> None
def _sanitize_json(obj: Any) -> Any
def sanitize_row(row: dict) -> dict
```

### memory_api.py

```python
def create_memory(entity_data: dict, workspace_id: str = None, isolation_mode: str = "SHARED") -> str
def get_memory(entity_id: str, entity_type: str = "MEMORY") -> dict | None
def search_memories(query: str, top_k: int = 10, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def update_memory(entity_id: str, entity_data: dict, entity_type: str = "MEMORY") -> bool
def delete_memory(entity_id: str, entity_type: str = "MEMORY") -> bool
def reinforce_memory(entity_id: str, entity_type: str = "MEMORY") -> bool
def get_agent_memories(agent_id: str, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def decay_memories(threshold: float = 0.1) -> int
```

### knowledge_api.py

```python
def create_knowledge(entity_data: dict, workspace_id: str = None, isolation_mode: str = "SHARED", owned_by_agent: str = None) -> str
def get_knowledge(entity_id: str) -> dict | None
def search_knowledge(query: str, top_k: int = 10, workspace_id: str = None, isolation_mode: str = "SHARED") -> list[dict]
def validate_knowledge(entity_id: str, validated_by: str, status: str, notes: str = None) -> bool
def link_knowledge(source_id: str, target_id: str, edge_type: str, strength: float = 1.0) -> str
def add_edge(source_id: str, source_type: str, target_id: str, edge_type: str, strength: float = 1.0) -> str
def get_edges(entity_id: str, entity_type: str, direction: str = "outgoing") -> list[dict]
```

### agent_api.py

```python
# Original functions
def register_agent(agent_name: str, agent_type: str, capabilities: dict) -> str
def get_agent(agent_id: str) -> dict | None
def create_session(agent_id: str, owner_user_id: str = None, workspace_id: str = None, predecessor_session_id: str = None) -> str
def end_session(session_id: str) -> bool
def get_active_sessions(workspace_id: str = None) -> list[dict]
def log_access(session_id: str, action_type: str, resource_type: str, resource_id: str) -> str
def request_collaboration(session_id: str, target_agent_id: str, message: str) -> str
def checkpoint_session(session_id: str, checkpoint_data: dict) -> bool
def get_session_chain(session_id: str) -> list[dict]
# NEW v2.3.0
def issue_credential(agent_id: str, user_id: str, cred_type: str, scope: dict, expires_hours: int = 24) -> str
def verify_credential(credential_id: str) -> dict | None
def get_credentials_for_user(user_id: str) -> list[dict]
def revoke_credential(credential_id: str) -> bool
def hibernate_agent(agent_id: str) -> bool
def wake_agent(agent_id: str) -> bool
def register_pool_agent(agent_name: str, capabilities: dict, skills_tags: list[str]) -> str
def assign_pool_agent(user_id: str, required_skills: list[str]) -> str | None
```

### task_plan_api.py

```python
def create_plan(title: str, description: str, owner_agent_id: str) -> str
def get_plan(plan_id: str, status: str = "ACTIVE") -> dict | None
def update_plan_status(plan_id: str, status: str) -> bool
def add_step(plan_id: str, step_type: str, step_data: dict, step_order: int = None, plan_status: str = "ACTIVE") -> str
def update_step_status(plan_id: str, step_id: str, status: str) -> bool
def get_plan_steps(plan_id: str, status: str = "ACTIVE") -> list[dict]
```

### harness_api.py

```python
def create_template(template_name: str, template_type: str, template_data: dict, input_schema: dict = None, output_schema: dict = None) -> str
def get_template(template_id: str) -> dict | None
def list_templates(template_type: str = None) -> list[dict]
def instantiate_template(template_id: str, agent_id: str, instance_data: dict = None) -> str
def derive_template(parent_id: str, template_name: str, modifications: dict) -> str
def validate_template(template_id: str) -> dict
```

### graph_api.py

```python
def create_entity_graph(entity_id: str, entity_type: str, depth: int = 3) -> dict
def shortest_path(source_id: str, target_id: str, max_depth: int = 10) -> list[str]
def get_neighbors(entity_id: str, entity_type: str, edge_type: str = None) -> list[dict]
def get_community(entity_id: str, entity_type: str) -> list[dict]
def graph_stats() -> dict
def search_by_structure(pattern: dict) -> list[dict]
def get_entity_timeline(entity_id: str, entity_type: str) -> list[dict]
def get_strongest_path(source_id: str, target_id: str, min_strength: float = 0.5) -> list[dict]
def export_graph(entity_id: str, entity_type: str, format: str = "json") -> str
```

### workspace_api.py

```python
def create_workspace(name: str, description: str = None, isolation_mode: str = "SHARED", owner_user_id: str = None) -> str
def get_workspace(workspace_id: str) -> dict | None
def update_workspace(workspace_id: str, **kwargs) -> bool
def list_workspaces(owner_user_id: str = None) -> list[dict]
def save_context(workspace_id: str, context_type: str, context_data: dict, created_by: str) -> str
def get_context(workspace_id: str, context_type: str = None, limit: int = 10) -> list[dict]
def get_context_chain(workspace_id: str, context_type: str = None) -> list[dict]
def get_latest_context(workspace_id: str, context_type: str = None) -> dict | None
def create_handoff_session(agent_id: str, workspace_id: str, predecessor_session_id: str, owner_user_id: str = None) -> str
def recover_workspace(workspace_id: str) -> dict
def link_task_to_workspace(workspace_id: str, plan_id: str) -> bool
def get_workspace_tasks(workspace_id: str) -> list[dict]
def get_user_workspaces(user_id: str) -> list[dict]
```

### spec_api.py [NEW v2.3.0]

```python
def create_spec(entity_data: dict, spec_meta: dict, workspace_id: str = None) -> str
def get_spec(spec_id: str) -> dict | None
def update_spec(spec_id: str, entity_data: dict = None, spec_meta: dict = None) -> bool
def list_specs(status: str = None, workspace_id: str = None) -> list[dict]
def create_plan_from_spec(spec_id: str, plan_title: str, plan_description: str) -> str
def link_spec_to_plan(spec_id: str, plan_id: str, link_type: str = "DRIVES", strength: float = 1.0) -> str
def get_spec_plan_links(spec_id: str) -> list[dict]
def validate_plan_against_spec(spec_id: str, plan_id: str) -> dict
def derive_spec(parent_spec_id: str, entity_data: dict, spec_meta: dict) -> str
def delete_spec(spec_id: str) -> bool
```

### collab_api.py [NEW v2.3.0]

```python
def create_collab_group(group_name: str, group_type: str, sharing_policy: str = "OPEN", created_by: str = None) -> str
def get_collab_group(group_id: str) -> dict | None
def update_collab_group(group_id: str, **kwargs) -> bool
def add_group_member(group_id: str, agent_id: str, role: str = "CONTRIBUTOR") -> str
def remove_group_member(group_id: str, agent_id: str) -> bool
def list_group_members(group_id: str) -> list[dict]
def get_agent_groups(agent_id: str) -> list[dict]
def share_memory_to_group(group_id: str, memory_id: str, shared_by: str) -> str
def get_group_shared_memories(group_id: str) -> list[dict]
def delete_collab_group(group_id: str) -> bool
```

### security.py

```python
class DataMaskingService:
    def mask(self, data: str, mask_type: str = "full") -> str
    def unmask(self, masked_data: str, key: str) -> str

class ReversibleEncryption:
    def encrypt(self, plaintext: str) -> tuple[str, str]
    def decrypt(self, ciphertext: str, key: str) -> str

def hash_password(password: str) -> str
def verify_password(password: str, password_hash: str) -> bool
```

### embedding_api.py [NEW v2.3.2]

```python
def generate_embedding(text: str, api_url: str = None, model: str = None, timeout: int = 30) -> list[float]
def store_embedding(entity_id: str, entity_type: str, text: str, api_url: str = None, model: str = None) -> bool
def store_embedding_vector(entity_id: str, entity_type: str, embedding: list[float], model: str = None) -> bool
def get_embedding(entity_id: str, entity_type: str = "MEMORY") -> dict | None
def delete_embedding(entity_id: str, entity_type: str = "MEMORY") -> bool
def search_similar(text: str, top_k: int = 10, entity_type: str = None, workspace_id: str = None, api_url: str = None, model: str = None) -> list[dict]
def search_by_entity_id(entity_id: str, entity_type: str = "MEMORY", top_k: int = 10, workspace_id: str = None) -> list[dict]
def search_hybrid(text: str, keyword: str = None, top_k: int = 10, entity_type: str = None, workspace_id: str = None, vector_weight: float = 0.7, api_url: str = None, model: str = None) -> list[dict]
def search_multi_type(text: str, entity_types: list[str] = None, top_k: int = 10, workspace_id: str = None, api_url: str = None, model: str = None) -> dict[str, list[dict]]
def search_unified(text: str, top_k: int = 20, entity_type: str = None, workspace_id: str = None, domain: str = None, category: str = None, tags: list[str] = None, graph_seed_entity_id: str = None, graph_seed_entity_type: str = None, graph_depth: int = 2, vector_weight: float = 0.4, fulltext_weight: float = 0.25, relational_weight: float = 0.2, graph_weight: float = 0.15, api_url: str = None, model: str = None) -> list[dict]
def search_unified_sql(text: str, top_k: int = 20, entity_type: str = None, workspace_id: str = None, domain: str = None, category: str = None, tags: list[str] = None, graph_seed_entity_id: str = None, graph_seed_entity_type: str = None, graph_depth: int = 2, vector_weight: float = 0.4, fulltext_weight: float = 0.25, relational_weight: float = 0.2, graph_weight: float = 0.15, api_url: str = None, model: str = None) -> list[dict]
def search_fulltext(query: str, top_k: int = 20, entity_type: str = None, category: str = None, workspace_id: str = None) -> list[dict]
def generate_embeddings_batch(entity_type: str = "MEMORY", limit: int = 100, api_url: str = None, model: str = None) -> dict
def get_embedding_stats() -> dict
def get_model_dimension(model: str = None) -> int
```

### search_api.py [NEW v2.3.2]

Unified search entry point for AI agents. 10 strategies with auto-detection:

```python
def search(text: str, strategy: str = "auto", top_k: int = 10, entity_type: str = None,
           workspace_id: str = None, domain: str = None, category: str = None,
           tags: list[str] = None, graph_seed_entity_id: str = None,
           entity_id: str = None, entity_types: list[str] = None,
           min_importance: int = None, vector_weight: float = None,
           fulltext_weight: float = None, relational_weight: float = None,
           graph_weight: float = None, **kwargs) -> dict
def list_search_strategies() -> list[dict]
def describe_search_strategy(strategy: str) -> dict | None
```

| Strategy | Signals | Best For | Requires Embedding |
|----------|---------|----------|-------------------|
| vector | vector | Semantic/concept search | Yes |
| fulltext | fulltext | Exact keyword/boolean/fuzzy | No |
| keyword | keyword | Wildcard/LIKE patterns | No |
| graph | graph | Relationship/neighborhood | No |
| hybrid | vector+fulltext | Semantic+lexical balanced | Yes |
| unified | vector+fulltext+relational+tag+graph | Comprehensive multi-dimensional | Yes |
| unified_sql | vector+fulltext+relational+tag+graph | Single-SQL CTE fusion (low-latency) | Yes |
| relational | relational | Domain/category/importance filter | No |
| multi_type | vector+multi_type | Cross-type (MEMORY/KNOWLEDGE/SPEC) | Yes |
| auto | auto-detected | Unknown query type / convenience | Varies |

Auto-detection rules: boolean operators (AND/OR/NOT) → fulltext; `$`/`~` → fulltext; `%`/`_` → keyword; domain/tags kwargs → unified; graph_seed_entity_id → unified; ≤2 words → fulltext; ≥5 words → unified; else → hybrid.

## Scheduler Jobs (16 Jobs)

| Job | Schedule | Description |
|-----|----------|-------------|
| MEMORY_FUSION_JOB | Weekly Sunday 06:00 | Fuses similar memories, decays importance scores, archives below threshold |
| MEMORY_FUSION_CYCLE | Daily 04:00 | Runs full fusion cycle (decay + consolidate + archive) |
| MEMORY_FUSION_STATS | Daily 05:00 | Computes and logs memory fusion statistics |
| SESSION_CLEANUP_JOB | Hourly | Ends stale active sessions past timeout threshold |
| SESSION_EXPIRY_NOTIFICATION | Hourly | Notifies agents of upcoming session expiry |
| KNOWLEDGE_EXTRACTION_JOB | Daily 06:00 | Extracts knowledge from high-importance memories |
| KNOWLEDGE_GRAPH_MAINTENANCE | Weekly Sunday 01:00 | Rebuilds knowledge graph edges and consistency checks |
| WORKSPACE_CLEANUP_JOB | Daily 04:00 | Archives completed workspaces and their context chains |
| STALE_WORKSPACE_DETECT_JOB | Every 30 min | Detects workspaces with no active sessions for N hours |
| DORMANT_AGENT_JOB [NEW v2.3.0] | Every 30 min | Auto-hibernates agents inactive beyond dormant_timeout_min |
| CREDENTIAL_CLEANUP_JOB [NEW v2.3.0] | Daily 02:00 | Purges expired and revoked credentials |
| EMBEDDING_GENERATION_JOB [NEW v2.3.2] | Every 2 hours | Auto-generates embeddings for new MEMORY/KNOWLEDGE entities |
| LOOP_TRIGGER_JOB [NEW v3.7.3] | Every minute | Triggers pending loop runs that are ready to execute |
| LOOP_STUCK_CHECK_JOB [NEW v3.7.3] | Every 5 min | Detects and handles stuck/timed-out loop runs (no iteration beyond threshold) |
| LOOP_CLEANUP_JOB [NEW v3.7.3] | Weekly Sunday 06:00 | Cleans up completed/failed loop runs older than retention period |

## Harness Templates (5 Built-in)

| Template | Description |
|----------|-------------|
| RESEARCH_AGENT | Multi-step research workflow: gather sources, synthesize findings, produce structured report |
| CODE_REVIEW_AGENT | Code analysis workflow: parse code, identify issues, suggest improvements, generate review summary |
| DATA_ANALYSIS_AGENT | Data pipeline: load data, compute statistics, generate visualizations, produce insights report |
| CONVERSATION_AGENT | Multi-turn dialogue: maintain context, track intent, manage dialogue state, generate responses |
| TASK_EXECUTION_AGENT | General task execution: plan steps, execute sequentially, handle errors, report outcomes |

## CONTEXT_DATA Structures (v2.2.0)

### CHECKPOINT
```json
{
  "session_state": "<serialized agent state>",
  "working_memory": "<current working memory snapshot>",
  "active_goals": ["<goal_id>", ...],
  "tool_state": "<tool-specific state data>"
}
```

### HANDOFF
```json
{
  "summary": "<handoff summary text>",
  "pending_items": ["<item>", ...],
  "decisions": ["<decision>", ...],
  "recommendations": ["<recommendation>", ...]
}
```

### SUMMARY
```json
{
  "key_findings": ["<finding>", ...],
  "decisions_made": ["<decision>", ...],
  "outcomes": ["<outcome>", ...],
  "metrics": {"<key>": "<value>", ...}
}
```

### ERROR_STATE
```json
{
  "error_type": "<exception class>",
  "error_message": "<human-readable message>",
  "stack_trace": "<traceback string>",
  "recovery_hints": ["<hint>", ...]
}
```

### AUTO_SAVE
```json
{
  "incremental_state": "<partial state delta>",
  "last_operation": "<operation description>",
  "timestamp": "<ISO 8601>"
}
```

## Critical oracledb Quirks

- **JSON column reads**: `dict`; **JSON expression reads**: `str`; **PL/SQL JSON return**: `dict`; **JSON_VALUE**: `str`; **JSON_QUERY**: `dict`/`list`; **NULL**: `None`
- **JSON writes**: `json.dumps()` string bind works; dict direct bind fails (DPY-3002); `oracledb.DB_TYPE_JSON` typed var works
- **JSON_MERGEPATCH** -> OSON v2 error (DPY-3021); use **JSON_TRANSFORM** instead
- **JRD etag**: oracledb returns `bytes`; update without `_metadata` succeeds; wrong etag -> ORA-42699
- **JRD INSERT via Python**: pass JSON string as bind to `INSERT INTO VIEW (DATA) VALUES (:data)`
- **Decimal**: oracledb thin returns `decimal.Decimal` for NUMBER in JSON; use `_sanitize_json`/`sanitize_row`
- **Named bind variables** (`:uid`, `:aid`) cause ORA-01745 on tables with JSON columns; use positional (`:1`,`:2`) or short names (`:b1`,`:b2`)
- **CONSTRAINTS reserved word**: Oracle reserved; must use double-quote `"CONSTRAINTS"` in all SQL references
- **PL/SQL JSON_OBJECT**: VALUE clause does not support `FORMAT JSON` in 23ai/26ai; use `RETURN VARCHAR2` instead of `RETURN JSON`
- **Reference-partitioned tables**: Cannot DISABLE constraints (ORA-14650); constraints always enforced
- **JSON_QUERY WITH WRAPPER on arrays**: Returns `[array]` (double-bracketed); must `SUBSTR(l_vec, 2, DBMS_LOB.GETLENGTH(l_vec)-2)` before `TO_VECTOR()`
- **TO_VECTOR format**: Requires `[v1,v2,...]` bracketed format; plain comma-separated `v1,v2,...` triggers ORA-51804
- **Named bind variables with execute_query**: Must use dict `{"eid": "X"}` with named binds `:eid`, NOT list `["X"]` with positional `:1`; oracledb thin mode interprets dict + `:1` as named bind "1" causing ORA-01722
- **EMBEDDING_MANAGER.generate_and_store**: Only works from anonymous PL/SQL block (not SELECT function call) due to UTL_HTTP context; also requires ENTITIES row to exist first (FK constraint)

## Key Design Decisions

- **JRD vs native JSON**: WORKSPACE_CONTEXT uses native JSON (append-only); WORKSPACES + WORKSPACE_TASKS use JRD
- **26ai JRD annotations** required for write operations (`@insert`, `@update`, `@delete`)
- **JRD no JOINs** in nested subqueries; use FK-based nesting only
- **JRD must include all PK columns** of root table in the view definition
- **ON DELETE CASCADE** on child tables (required for JRD updatable views to handle parent deletion)
- **AGENT_SESSION self-ref FK** via `UK_SESSION_ID` (unique constraint on SESSION_ID for predecessor reference)
- **WORKSPACE_TASKS created after TASK_PLANS** (FK dependency on TASK_PLANS.PLAN_ID)
- **OWNER_USER_ID nullable** on WORKSPACES (system workspaces may have no owner)
- **ISOLATION_MODE**: `SHARED` (entities visible across workspaces) vs `ISOLATED` (strict workspace boundary)
- **Context checkpoint**: agent-initiated only; no automatic checkpointing on session end
- **Spec storage**: ENTITIES subtype `SPEC`, reuses unified storage+partitioning+JRD; SPEC_META reference-partitioned like HARNESS_META
- **Spec↔Plan**: Many-to-many via SPEC_PLAN_LINKS; LINK_TYPE: DRIVES/VALIDATES/CONSTRAINS/EXTENDS
- **Agent states**: ACTIVE/INACTIVE/SUSPENDED/DECOMMISSIONED/DORMANT/POOL; DORMANT preserves identity, POOL is stateless
- **POOL Agent**: Stateless — context follows user via credentials; matching by skills_tags intersection
- **Collaboration Groups**: Mode C — group-level shared Workspace + optional personal Workspace per member; LEAD/CONTRIBUTOR get personal WS, OBSERVER does not
- **SYSTEM_USERS precedes AGENT_REGISTRY** in DDL (FK dependency)
- **SHA256 password prefix**: `SHA256:` is 7 chars; use `stored_hash[7:]` for comparison

## Deployment Notes

- Use `safe_ddl` / `safe_idx` helpers in deploy scripts to avoid re-creating existing objects
- Drop tables with retry loop (reference-partitioned children must be dropped before parents; order matters)
- `add_edge` requires `source_type` parameter (part of composite PK on ENTITY_EDGES)
- `create_knowledge` uses `owned_by_agent` parameter to set ownership on knowledge entities

## Database Connection

| Parameter | Value |
|-----------|-------|
| DSN | `//<db_host>:<db_port>/<db_service>` |
| User | `<db_user>` / `<db_password>` |
| Python | 3.14+ / oracledb 4.0.1+ thin mode (4.0.0 has TCPS/Deep Sec issues; 4.1.0+ recommended when available) |
| Server | `http://<web_host>:<web_port>` |

### Collaborative Integration (v3.7.3)
- **Spec-Driven Loop** | Create loops from Spec acceptance_criteria; SPEC_VALIDATION eval type |
- **Task-Loop Binding** | Bind loops to task steps; auto-complete on loop success; TASK_LOOP_BINDING table |
- **Collaborative Loop** | Parent/child loops for collab groups; AGGREGATE eval type; 2-level nesting |
- **Branch-Isolated Loop** | Loops bound to branch_id run in branch context |
- **Skill-Triggered Loop** | Skills with validation_loop metadata auto-start verification |
- **ON_START lifecycle hook** | Added to hook event types |
- **7 new API endpoints** | /api/loops/from-spec, /api/loops/collab, /api/loops/{id}/children, /api/loops/{id}/aggregation, /api/tasks/steps/{id}/bind-loop, /api/tasks/steps/{id}/loop, /api/collab/{id}/loop |
