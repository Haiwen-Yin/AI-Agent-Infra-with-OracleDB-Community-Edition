# Multi-Agent Architecture Design Document

**Version**: 0.4.2  
**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-07

---

## Problem Statement

When deploying Oracle Memory System with multiple AI agents, we face these challenges:

1. **Shared Knowledge**: All agents need access to common resources (API docs, schemas, best practices)
2. **Private Context**: Each agent needs isolated workspace for its own state and preferences
3. **Collaboration**: Specific agents may need to share project-specific information
4. **Security**: Agents should not accidentally read or modify each other's private data

---

## Architecture Overview

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐
│  Agent A     │   │  Agent B      │   │  Agent C     │
│ (Analysis)   │   │ (Writing)     │   │ (Deployment) │
└──────┬──────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
              ┌───────────▼────────────┐
              │    MEMORY ACCESS LAYER  │
              │  (Visibility Filter)   │
              └───────────┬────────────┘
                          │
           ┌──────────────▼──────────────┐
           │      AGENT REGISTRY          │
           │  (Registration/Discovery)    │
           └──────────────┬──────────────┘
                          │
     ┌────────────────────▼─────────────────────┐
     │         MEMORY STORE (Oracle DB)          │
     │                                            │
     │  memories (with visibility field)        │
     │  ├── SHARED: System documentation       │
     │  ├── PRIVATE-A: Agent A's private data  │
     │  ├── PRIVATE-B: Agent B's private data  │
     │  └── COLLAB-1: Shared team project      │
     └──────────────────────────────────────────┘
```

---

## Component Design

### 1. AGENT_REGISTRY Table

**Purpose**: Centralized registry for all agents with capability declaration and permission levels.

| Field | Type | Purpose |
|-------|------|---------|
| AGENT_ID | VARCHAR2(64) | Unique identifier (primary key) |
| AGENT_NAME | VARCHAR2(100) | Human-readable name |
| AGENT_TYPE | VARCHAR2(50) | Role classification: analysis, writing, deployment, research |
| CAPABILITIES | CLOB | JSON array of capabilities: `["text-analysis", "code-review"]` |
| PERMISSION_LEVEL | VARCHAR2(20) | Access permission: READ_ONLY or READ_WRITE |

**Query Patterns**:
- Find agents by type: `SELECT * FROM agent_registry WHERE AGENT_TYPE = 'analysis'`
- Find agents by capability: `SELECT * FROM agent_registry WHERE CAPABILITIES LIKE '%data-analysis%'`

### 2. Memory Visibility Extension (MEMORIES Table)

**Extension Fields Added**:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| OWNED_BY_AGENT | VARCHAR2(64) | NULL | Agent that owns this memory (NULL = shared) |
| VISIBILITY | VARCHAR2(20) | SHARED | Visibility level: SHARED, PRIVATE, COLLABORATIVE |
| ACCESSIBLE_TO | CLOB | [] | JSON array for collaborative access list |

**Visibility Rules**:

```sql
-- Agent can see memory if ANY of these are true:
1. visibility = 'SHARED'  (visible to everyone)
2. visibility = 'PRIVATE' AND owned_by_agent = :agent_id  (owner only)  
3. visibility = 'COLLABORATIVE' AND :agent_id IN ACCESSIBLE_TO JSON array
```

### 3. AGENT_SESSION Table

**Purpose**: Track active agent sessions with working context preservation for breakpoint recovery.

| Field | Type | Purpose |
|-------|------|---------|
| SESSION_ID | VARCHAR2(128) | Unique session identifier |
| WORKING_MEMORY_ID | NUMBER | Memory ID currently being processed |
| CONTEXT_SNAPSHOT | CLOB | JSON: current working context for resume capability |

**Session Lifecycle**:
```
CREATE → UPDATE_CONTEXT (during work) → CLOSE/EXPIRE
                    ↓
            AUTO-SNAPSHOT every progress update
```

### 4. AGENT_MEMORY_ACCESS Table

**Purpose**: Complete audit trail of all memory access operations.

| Field | Type | Purpose |
|-------|------|---------|
| ACCESS_ID | NUMBER (IDENTITY) | Unique access record ID |
| AGENT_ID | VARCHAR2(64) | Agent that performed the action |
| MEMORY_ID | NUMBER | Memory accessed |
| ACCESS_TYPE | VARCHAR2(20) | Operation type: READ, WRITE, DELETE |
| ACCESS_TIME | TIMESTAMP | When access occurred |

**Use Cases**:
- Compliance auditing
- Security investigation
- Usage analytics and monitoring

### 5. AGENT_COLLABORATION Table

**Purpose**: Manage agent-to-agent knowledge sharing requests with approval workflow.

| Field | Type | Purpose |
|-------|------|---------|
| COLLAB_ID | NUMBER (IDENTITY) | Unique collaboration request ID |
| SHARING_AGENT | VARCHAR2(64) | Agent requesting to share memory |
| RECEIVING_AGENT | VARCHAR2(64) | Target agent for sharing |
| STATUS | VARCHAR2(20) | Request state: PENDING, ACCEPTED, REJECTED |

**Workflow**:
```
1. Agent A creates collaboration request → Status: PENDING
2. Receiving agent or admin approves → Status: ACCEPTED  
3. Memory becomes accessible to receiving agent via COLLABORATIVE visibility
4. If rejected → Status: REJECTED (no access granted)
```

---

## Security Considerations

### 1. Access Control Layer
All memory queries must pass through an access control layer that validates:
- Agent session is active and valid
- Visibility rules are enforced before returning results
- All accesses are logged to audit trail

### 2. Data Isolation Guarantees

| Scenario | Guarantee |
|----------|-----------|
| Private Memory | Never visible outside owner unless explicitly shared via collaboration |
| Collaborative Memory | Only agents in ACCESSIBLE_TO list can access |
| Shared Memory | Always accessible (by design) but audit trail tracks who reads it |

### 3. Session Security
- Sessions have TTL (24 hours default, configurable)
- Inactive sessions auto-expire and are cleaned up
- Working context snapshots preserve agent state securely

---

## Performance Optimization Recommendations

### 1. Caching Strategy
```python
# Cache SHARED memories in application layer (Redis/Memcached)
SHARED_MEMORY_CACHE_TTL = 3600  # 1 hour

# PRIVATE memories should NOT be cached across sessions
PRIVATE_MEMORY_CACHE_ENABLED = False
```

### 2. Query Optimization
- Use composite indexes on `(visibility, owned_by_agent)` for frequent patterns
- Consider materialized views for read-heavy workloads with COLLABORATIVE access
- Partition AGENT_SESSION by date range (monthly) if high volume expected

### 3. Batch Operations
For bulk memory operations across agents:
```sql
-- Efficient batch update of collaborative visibility
UPDATE memories 
SET ACCESSIBLE_TO = JSON_ARRAY_APPEND(ACCESSIBLE_TO, '$', :new_agent_id)
WHERE VISIBILITY = 'COLLABORATIVE' AND AGENT_ID IN (:existing_agents);
```

---

## Migration Path (for existing deployments)

### Phase 1: Schema Extension (Zero Downtime)
1. Run `agent_schema.sql` to add new tables and extend MEMORIES table
2. No data migration needed - old memories default to SHARED visibility

### Phase 2: Agent Registration
1. Register all existing agents in AGENT_REGISTRY
2. Migrate any private context from file-based storage to MEMORY table with PRIVATE visibility

### Phase 3: Application Layer Update
1. Update agent clients to use new API (`agent_api.py`)
2. Implement access control layer in application code
3. Enable audit logging for all operations

---

## Testing Recommendations

Run the integration test suite after deployment:
```bash
cd /root/.hermes/skills/oracle-memory-by-yhw/scripts/
python3 test_agent_architecture.py
```

Tests verify:
- ✅ Schema integrity (all tables/views exist)
- ✅ Agent registration and discovery
- ✅ SHARED memory accessibility to all agents
- ✅ PRIVATE memory isolation (owner-only access)
- ✅ COLLABORATIVE memory access control
- ✅ Session management functionality
- ✅ Access audit trail accuracy
- ✅ Collaboration workflow correctness

---

## Future Enhancements

1. **Agent Capability Scoring**: Rate agents based on historical performance for intelligent routing
2. **Dynamic Visibility**: Auto-promote memories to SHARED after TTL or approval threshold
3. **Cross-Agent Search**: Federated search across all agent memories (with permission checks)
4. **Memory Ownership Transfer**: Allow agents to transfer ownership of memories

---

*Document Version: 0.4.2 | Last Updated: 2026-05-07*
