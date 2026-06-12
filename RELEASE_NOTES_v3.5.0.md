# Release Notes — v3.5.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-11

License: Apache License 2.0

---

## Overview

v3.5.0 fixes three critical Deep Sec bugs that made SHARED entities invisible to End Users, prevented End Users from accessing COLLAB_GROUPS/COLLAB_GROUP_MEMBERS tables, and exposed other agents' private context in collaboration workspaces.

---

## Deep Sec Collaboration Fix

v3.4.0 introduced Deep Data Security with 20 Data Grants, but three issues prevented collaboration group members from accessing shared data and isolated private context:

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | ENTITIES_AGENT_OWN predicate missing COLLAB subquery | SHARED entities invisible to End Users — only PUBLIC and own PRIVATE entities were visible | Added UNION with COLLAB_GROUPS + COLLAB_GROUP_MEMBERS subquery |
| 2 | No Data Grants on COLLAB_GROUPS / COLLAB_GROUP_MEMBERS | End User subqueries referencing these tables failed with ORA-00942, causing entire predicates to return FALSE | Added `collab_member_own` and `collab_group_member_access` Data Grants |
| 3 | WORKSPACE_CONTEXT missing VISIBILITY column | All context in collab workspaces visible to all members, including other agents' private thoughts | Added VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED); updated WS_CTX_AGENT_ACCESS and WS_CTX_AGENT_INSERT predicates to enforce visibility-aware filtering |

---

## Bug Fixes

### 1. SHARED entities invisible to End Users

**Root cause**: The `entities_agent_own` Data Grant predicate checked `WORKSPACES.CURRENT_AGENT_ID` for SHARED visibility, but CURRENT_AGENT_ID is NULL for most workspaces. The predicate ignored collaboration group membership entirely.

**Fix**: Added UNION with COLLAB_GROUPS + COLLAB_GROUP_MEMBERS subquery to the ENTITIES_AGENT_OWN predicate, matching the pattern already used by BRANCH_AGENT_ACCESS, WS_AGENT_ACCESS, WS_CTX_AGENT_ACCESS, and TASK_AGENT_ACCESS.

### 2. End Users cannot access COLLAB tables

**Root cause**: Data Grant predicates on WORKSPACES, WORKSPACE_CONTEXT, CONTEXT_BRANCHES, and TASK_PLANS all reference COLLAB_GROUPS and COLLAB_GROUP_MEMBERS in subqueries. Without Data Grants on these tables, End User subquery execution failed silently (ORA-00942), causing the entire predicate to evaluate to FALSE.

**Fix**: Added 2 new Data Grants:
- `collab_member_own` — SELECT on COLLAB_GROUP_MEMBERS WHERE agent matches (matches End User via `ORA_END_USER_CONTEXT.username`)
- `collab_group_member_access` — SELECT on COLLAB_GROUPS WHERE group_id is in the agent's member groups

---

## Data Grant Changes (20 → 22)

| Grant | Table | Level | Role | Description |
|-------|-------|-------|------|-------------|
| collab_member_own | COLLAB_GROUP_MEMBERS | Row | agent_data_role | SELECT where agent matches End User |
| collab_group_member_access | COLLAB_GROUPS | Row | agent_data_role | SELECT where group_id in member's groups |

### 3. WORKSPACE_CONTEXT collaboration isolation

**Root cause**: WORKSPACE_CONTEXT had no VISIBILITY column. In collaboration group workspaces, all context entries were equally visible to all group members, meaning one agent's private reasoning/thoughts were exposed to other agents in the same workspace.

**Fix**: Added `VISIBILITY` column (VARCHAR2(16), default 'SHARED', CHECK constraint: PRIVATE/SHARED/PUBLIC) to WORKSPACE_CONTEXT. Updated WS_CTX_AGENT_ACCESS Data Grant predicate to enforce:
- Agent always sees its own context (AGENT_ID matches) regardless of VISIBILITY
- Agent sees other agents' SHARED/PUBLIC context in collab group workspaces
- Agent CANNOT see other agents' PRIVATE context even in the same collab group

Updated WS_CTX_AGENT_INSERT predicate to ensure new inserts have a valid VISIBILITY value. Existing rows default to SHARED (backward compatible — previously all context was implicitly shared).

---

## Deployment

### Fresh Deployment

No special steps needed — deploy `6_deep_sec_policy.sql` as usual. It now includes the 2 new Data Grants.

### Migration from v3.4.0

```sql
-- Step 1: Add VISIBILITY column to WORKSPACE_CONTEXT
ALTER TABLE WORKSPACE_CONTEXT ADD VISIBILITY VARCHAR2(16) DEFAULT 'SHARED';
UPDATE WORKSPACE_CONTEXT SET VISIBILITY = 'SHARED' WHERE VISIBILITY IS NULL;
ALTER TABLE WORKSPACE_CONTEXT ADD CONSTRAINT CK_WC_VISIBILITY CHECK (VISIBILITY IN ('PRIVATE','SHARED','PUBLIC'));

-- Step 2: Drop old ENTITIES_AGENT_OWN Data Grant (predicate will be recreated)
DROP DATA GRANT entities_agent_own;

-- Step 3: Drop old WS_CTX_AGENT_ACCESS and WS_CTX_AGENT_INSERT Data Grants (predicates updated for visibility)
DROP DATA GRANT ws_ctx_agent_access;
DROP DATA GRANT ws_ctx_agent_insert;

-- Step 4: Re-run 6_deep_sec_policy.sql (idempotent — recreates all 22 Data Grants with updated predicates)
@scripts/deploy/6_deep_sec_policy.sql
```

---

## System Requirements

Unchanged from v3.4.0:
- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+
