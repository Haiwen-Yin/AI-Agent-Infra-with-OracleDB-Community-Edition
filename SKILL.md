---
name: oracle-memory-by-yhw
version: v0.4.2 (Directory Consolidation Update)
author: Haiwen Yin (胖头鱼 🐟)
category: mlops
description: Oracle AI Database Memory System v0.4.1 - Universal memory system with JRD, Property Graph, Task Plan management, and optimized indexing
---

# Oracle AI Database Memory System v0.4.1 Task Plan Integration Edition

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Version**: v0.4.2 (Multi-Agent Architecture Update) - 2026-05-07  
**Status**: Production Ready ✅  
**License**: Apache License 2.0

---

## 🎯 System Overview

This is a **universal memory system for all AI Agents**, built on Oracle AI Database 26ai. Provides complete semantic search, knowledge graph relationship management, vector similarity retrieval, JRD (JSON Relational Duality) views, native Property Graph capabilities, and **Task Plan persistence** with breakpoint recovery using the `oracle-sqlcl` MCP Server as the primary interface.

### ✨ Core Features (v0.4.1)

| Feature | v0.3.0 | v0.3.1 | v0.4.0 | **v0.4.1** |
|---------|--------|--------|--------|-----------|
| **Target Users** | All AI Agents | ✅ All AI Agents | ✅ All AI Agents | ✅ All AI Agents |
| **Task Plan Storage** | ❌ Not included | ❌ Not included | ❌ Not included | ✅ **Complete Task Plan System** |
| **Breakpoint Recovery** | ❌ None | ❌ None | ❌ None | ✅ **Auto Snapshot + Resume API** |
| **Historical Learning** | ❌ Limited | ❌ Limited | ❌ Limited | ✅ **Task Pattern Recognition** |
| **Status Tracking** | ❌ Basic | ⚠️ Partial | ⚠️ Partial | ✅ **Detailed Step-by-Step Audit** |
| **Embedding Models** | Multi-model | ✅ Multi-model | ✅ Multi-model | ✅ Multi-model |
| **Production Deployment** | ADG HA | ✅ ADG HA | ✅ ADG HA | ✅ ADG HA |
| **Vector Import** | CLOB + TO_VECTOR() | ✅ CLOB + TO_VECTOR() | ✅ CLOB + TO_VECTOR() | ✅ CLOB + TO_VECTOR() |
| **Property Graph** | ❌ Not tested | ✅ Integration verified | ✅ **CREATE PROPERTY GRAPH + SQL/PGQ** | ✅ **CREATE PROPERTY GRAPH + SQL/PGQ** |
| **JRD Implementation** | ❌ Plan only | ⚠️ Plan documented | ✅ **Full implementation + nested views** | ✅ **Full implementation + nested views** |
| **JSON Decomposition** | ❌ CLOB storage | ⚠️ Design documented | ✅ **6 relationship tables** | ✅ **6 relationship tables** |
| **Graph Traversal Views** | ❌ | ❌ | ✅ **MEMORY_GRAPH_V + MEMORY_GRAPH_JSON_V** | ✅ **MEMORY_GRAPH_V + MEMORY_GRAPH_JSON_V** |
| **Auxiliary Indexes** | ❌ | ⚠️ Partial | ✅ **Complete index coverage** | ✅ **Complete index coverage** |
| **Partition Strategy** | ❌ | ✅ Tested & verified | ✅ **Multi-table unified strategy** | ✅ **Multi-table unified strategy** |

---

## 🆕 v0.4.1 New: Task Plan Persistence System

### Overview

The Task Plan system provides AI Agents with durable task execution tracking, enabling **breakpoint recovery after failures**, **historical pattern learning from completed tasks**, and **detailed status auditing**. This is critical for long-running agent operations that may encounter network issues, timeouts, or other disruptions.

**Key Benefits:**
- ✅ **Breakpoint Recovery** - Resume exactly where interrupted with full context
- ✅ **Historical Learning** - Learn from past task patterns and success/failure modes  
- ✅ **Status Tracking** - Complete audit trail of all agent actions

---

## 🗄️ v0.4.1 Database Schema (Task Plan Tables)

### Task Plan Core Tables (v0.4.1 New)

```sql
-- ============================================
-- 1. TASK_PLANS - Core task plan table
-- ============================================
CREATE TABLE TASK_PLANS (
    PLAN_ID       NUMBER PRIMARY KEY,
    PLAN_NAME     VARCHAR2(200),                    -- Task name
    PLAN_TYPE     VARCHAR2(50) NOT NULL,            -- task/deployment/research/analysis
    STATUS        VARCHAR2(30) DEFAULT 'PENDING',   -- PENDING/RUNNING/SUCCESS/FAILED/CANCELLED/PAUSED
    DESCRIPTION   CLOB,                             -- Task description and intent
    GOAL          CLOB,                             -- Final goal (structured)
    
    -- Priority and time management
    PRIORITY      NUMBER DEFAULT 2 CHECK (PRIORITY BETWEEN 1 AND 5),
    CREATED_AT    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    STARTED_AT    TIMESTAMP WITH TIME ZONE,         -- Start execution time
    UPDATED_AT    TIMESTAMP WITH TIME ZONE,         -- Last update status
    COMPLETED_AT  TIMESTAMP WITH TIME ZONE,         -- Completion time
    EXPIRES_AT    TIMESTAMP WITH TIME ZONE,         -- Expiration time
    
    -- Metadata (JSON)
    METADATA      CLOB,                             -- JSON: session_id, agent_context etc.
    TAGS          CLOB                              -- JSON: tag array
);

-- ============================================
-- 2. TASK_STEPS - Task step execution table
-- ============================================
CREATE TABLE TASK_STEPS (
    STEP_ID       NUMBER PRIMARY KEY,
    PLAN_ID       NUMBER NOT NULL REFERENCES TASK_PLANS(PLAN_ID),
    STEP_ORDER    NUMBER NOT NULL,                  -- Step sequence (1,2,3...)
    STEP_NAME     VARCHAR2(200),                    -- Step name
    ACTION        CLOB,                             -- Action description to execute
    TOOLS_USED    CLOB,                             -- JSON: tools used list
    
    -- Execution status
    STATUS        VARCHAR2(30) DEFAULT 'PENDING',   -- PENDING/IN_PROGRESS/SUCCESS/FAILED/BLOCKED
    RESULT        CLOB,                             -- Step execution result
    ERROR_MSG     CLOB,                             -- Error message (if any)
    
    -- Timestamps
    CREATED_AT    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    STARTED_AT    TIMESTAMP WITH TIME ZONE,
    COMPLETED_AT  TIMESTAMP WITH TIME ZONE,
    
    UNIQUE (PLAN_ID, STEP_ORDER)
);

-- ============================================
-- 3. TASK_CONTEXT_SNAPSHOTS - Task context snapshot (critical for breakpoint recovery)
-- ============================================
CREATE TABLE TASK_CONTEXT_SNAPSHOTS (
    SNAPSHOT_ID   NUMBER PRIMARY KEY,
    PLAN_ID       NUMBER NOT NULL REFERENCES TASK_PLANS(PLAN_ID),
    
    -- Snapshot type
    SNAPSHOT_TYPE VARCHAR2(30) DEFAULT 'AUTO',      -- AUTO/MANUAL/ON_ERROR
    
    -- Context content (complete state)
    CONTEXT_DATA  CLOB,                             -- JSON: agent_state, conversation_history etc.
    MEMORY_IDS    CLOB,                             -- JSON: associated memory node ID list
    NEXT_ACTION   CLOB,                             -- Next action to execute description
    
    -- Snapshot information
    CREATED_AT    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    IS_LATEST     VARCHAR2(1) CHECK (IS_LATEST IN ('Y','N')) DEFAULT 'N',
    
    -- Trigger reason (Oracle TRIGGER is a reserved word, use TRIGGER_REASON instead)
    TRIGGER_REASON  CLOB                            -- JSON: trigger_reason
);

-- ============================================
-- 4. TASK_TOOL_CALLS - Tool call records (audit trail)
-- ============================================
CREATE TABLE TASK_TOOL_CALLS (
    CALL_ID       NUMBER PRIMARY KEY,
    PLAN_ID       NUMBER NOT NULL REFERENCES TASK_PLANS(PLAN_ID),
    STEP_ID       NUMBER REFERENCES TASK_STEPS(STEP_ID),
    
    -- Tool information
    TOOL_NAME     VARCHAR2(100) NOT NULL,           -- tool name (terminal/browser/memory etc.)
    ACTION        CLOB NOT NULL,                    -- Executed operation description
    
    -- Call result
    STATUS        VARCHAR2(30) DEFAULT 'SUCCESS',   -- SUCCESS/FAILED/TIMEOUT
    RESULT_SIZE   NUMBER,                           -- Return result size (bytes)
    
    -- Time information
    CREATED_AT    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    DURATION_MS   NUMBER                            -- Execution duration milliseconds
);

-- ============================================
-- 5. TASK_DEPENDENCIES - Task dependency graph
-- ============================================
CREATE TABLE TASK_DEPENDENCIES (
    DEPENDENCY_ID NUMBER PRIMARY KEY,
    SOURCE_PLAN_ID NUMBER NOT NULL REFERENCES TASK_PLANS(PLAN_ID),
    TARGET_PLAN_ID NUMBER NOT NULL REFERENCES TASK_PLANS(PLAN_ID),
    
    -- Dependency type
    DEPENDENCY_TYPE VARCHAR2(30) DEFAULT 'HARD',    -- HARD/SOFT/EXCLUSIVE/RECOMMENDED
    CONDITION     CLOB,                             -- JSON: trigger condition description
    
    CREATED_AT    TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);
```

---

## 🔧 v0.4.1 API Functions (Python Integration)

### create_task_plan() - Create task plan and automatically save initial context snapshot

```python
def create_task_plan(plan_name, plan_type, description, steps):
    """
    Create a new task plan and automatically save initial context
    
    Args:
        plan_name (str): Task name
        plan_type (str): task/deployment/research/analysis
        description (str): Task description
        steps (list[dict]): Step list [{order, name, action}, ...]
    
    Returns:
        dict: Created plan information
    """
    # 1. Generate UUID
    plan_id = generate_uuid()
    
    # 2. Insert into TASK_PLANS
    sql_insert_plan = """
        INSERT INTO TASK_PLANS (PLAN_ID, PLAN_NAME, PLAN_TYPE, DESCRIPTION, STATUS)
        VALUES (:id, :name, :type, :desc, 'PENDING')
    """
    execute_sql(sql_insert_plan, plan_id, ...)
    
    # 3. Insert all steps
    for step in steps:
        sql_insert_step = """
            INSERT INTO TASK_STEPS (STEP_ID, PLAN_ID, STEP_ORDER, STEP_NAME, ACTION)
            VALUES (:step_id, :plan_id, :order, :name, :action)
        """
        execute_sql(sql_insert_step, ...)
    
    # 4. Create initial context snapshot (for breakpoint recovery)
    initial_context = {
        "agent_state": get_current_agent_state(),
        "conversation_history": get_recent_messages(limit=50),
        "memory_ids": [],
        "next_action": steps[0]["action"] if steps else None,
        "created_at": now()
    }
    
    save_context_snapshot(plan_id, initial_context)
    
    return {"plan_id": plan_id, ...}
```

### update_task_progress() - Update task status and automatically create context snapshot

```python
def update_task_progress(plan_id, step_id=None, status=None, result=None):
    """
    Update task execution status and automatically create context snapshot
    
    Args:
        plan_id (str): Plan ID
        step_id (str): Step ID (optional)
        status (str): New status
        result (str): Execution result
    """
    
    # 1. Update task or step status
    if step_id:
        update_sql = "UPDATE TASK_STEPS SET STATUS = :status, RESULT = :result, COMPLETED_AT = SYSTIMESTAMP WHERE STEP_ID = :step_id"
    else:
        update_sql = "UPDATE TASK_PLANS SET STATUS = :status, UPDATED_AT = SYSTIMESTAMP WHERE PLAN_ID = :plan_id"
    
    execute_sql(update_sql, ...)
    
    # 2. Automatically create context snapshot (critical!)
    context = {
        "agent_state": get_current_agent_state(),
        "conversation_history": get_recent_messages(limit=100),
        "memory_ids": get_related_memory_ids(plan_id),
        "next_action": determine_next_action(plan_id, step_id),
        "trigger_reason": f"progress_update_{status}",
        "is_latest": "Y" if is_largest_snapshot(plan_id) else "N"
    }
    
    save_context_snapshot(plan_id, context, snapshot_type="AUTO")
```

### resume_task() - Resume task execution from breakpoint (core feature)

```python
def resume_task(plan_id):
    """
    Resume task execution from breakpoint
    
    Args:
        plan_id (str): Plan ID
    
    Returns:
        dict: Restored context information
    """
    
    # 1. Get latest snapshot (LATEST = 'Y')
    snapshot_sql = """
        SELECT CONTEXT_DATA, NEXT_ACTION, SNAPSHOT_TYPE, CREATED_AT
        FROM TASK_CONTEXT_SNAPSHOTS
        WHERE PLAN_ID = :plan_id AND IS_LATEST = 'Y'
        ORDER BY CREATED_AT DESC FETCH FIRST 1 ROWS ONLY
    """
    
    snapshot = execute_query(snapshot_sql, plan_id)
    
    # 2. Restore Agent state
    context_data = json.loads(snapshot["CONTEXT_DATA"])
    
    # 3. Get incomplete steps
    incomplete_steps = get_incomplete_steps(plan_id)
    
    # 4. Return recovery information
    return {
        "context": context_data,
        "next_action": snapshot["NEXT_ACTION"],
        "incomplete_steps": incomplete_steps,
        "snapshot_time": snapshot["CREATED_AT"]
    }
```

### search_completed_tasks() - Search completed tasks for learning and pattern reuse

```python
def search_completed_tasks(query_params):
    """
    Search completed tasks for learning and pattern reuse
    
    Args:
        query_params (dict): {type, status, tags, keywords, date_range}
    
    Returns:
        list[dict]: Matching task list (includes execution statistics)
    """
    
    # Build query conditions
    conditions = ["STATUS IN ('SUCCESS', 'FAILED')"]
    if query_params.get("type"):
        conditions.append("PLAN_TYPE = :type")
    if query_params.get("tags"):
        conditions.append("CONTAINS(TAGS, :tag) > 0")
    
    # Main query - get task information + execution statistics
    query_sql = """
        SELECT 
            t.PLAN_ID, t.PLAN_NAME, t.PLAN_TYPE, t.STATUS,
            t.CREATED_AT, t.COMPLETED_AT,
            (SELECT COUNT(*) FROM TASK_STEPS s WHERE s.PLAN_ID = t.PLAN_ID) as total_steps,
            (SELECT COUNT(*) FROM TASK_STEPS s WHERE s.PLAN_ID = t.PLAN_ID AND s.STATUS = 'SUCCESS') as success_steps,
            (SELECT AVG(DURATION_MS) FROM TASK_TOOL_CALLS c WHERE c.PLAN_ID = t.PLAN_ID) as avg_tool_duration_ms,
            t.METADATA
        FROM TASK_PLANS t
        WHERE """ + " AND ".join(conditions)
    
    return execute_query(query_sql, ...)
```

---

## 📊 Data Flow Architecture (Task Plan System)

```
┌──────────────────────────────────────────────────────────────┐
│                   AI Agent Task Execution                    │
└──────────────────────────────────────────────────────────────┘

[Agent] ──Start Task──► [create_task_plan()]
                           │
                    ┌──────▼───────┐
                    │ TASK_PLANS   │ ← Task plan (status, goals)
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ TASK_STEPS   │ ← Execution steps and results
                    └──────┬───────┘
                           │
              [Executing...] ──► [update_task_progress()]
                              │
                       ┌──────▼──────────┐
                       │ CONTEXT_SNAPSHOTS│ ← **Critical for breakpoint recovery**
                       └──────┬──────────┘
                              │
                    ┌─────────▼─────────┐
                    │  AGENT_STATE      │ ← Agent current state
                    │  CONVERSATION     │ ← Conversation history
                    │  NEXT_ACTION      │ ← Next action
                    │  MEMORY_IDS       │ ← Associated memory nodes
                    └───────────────────┘

[Exception/Interruption] ◄──► [resume_task()] ──► [Load latest snapshot to continue execution]

[Task Completed] ──► [search_completed_tasks()] ──► [Pattern learning and reuse]
```

---

## 📊 v0.4.1 Indexing Strategy (Task Plan Tables)

### Task Plan Specific Indexes

```sql
-- TASK_PLANS indexes
CREATE INDEX IDX_TASK_PLANS_STATUS ON TASK_PLANS(STATUS);
CREATE INDEX IDX_TASK_PLANS_TYPE ON TASK_PLANS(PLAN_TYPE);
CREATE INDEX IDX_TASK_PLANS_CREATED ON TASK_PLANS(CREATED_AT DESC);
CREATE INDEX IDX_TASK_PLANS_PRIORITY ON TASK_PLANS(PRIORITY, CREATED_AT);

-- TASK_STEPS indexes
CREATE INDEX IDX_TASK_STEPS_PLAN ON TASK_STEPS(PLAN_ID, STEP_ORDER);
CREATE INDEX IDX_TASK_STEPS_STATUS ON TASK_STEPS(STATUS);

-- TASK_CONTEXT_SNAPSHOTS index (Oracle does not support WHERE on index, use regular index instead)
CREATE INDEX IDX_CONTEXT_SNAPSHOT_PLAN ON TASK_CONTEXT_SNAPSHOTS(PLAN_ID);

-- TASK_TOOL_CALLS indexes
CREATE INDEX IDX_TOOL_CALLS_PLAN ON TASK_TOOL_CALLS(PLAN_ID);
CREATE INDEX IDX_TOOL_CALLS_TIME ON TASK_TOOL_CALLS(CREATED_AT DESC);

-- Sequences (for auto-increment primary keys)
CREATE SEQUENCE SEQ_TASK_PLANS START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE SEQ_TASK_STEPS START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE SEQ_CONTEXT_SNAPSHOTS START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE SEQ_TOOL_CALLS START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE SEQ_TASK_DEPS START WITH 1 INCREMENT BY 1;
```

---

## 📚 Documentation

- [CHANGELOG.md](./CHANGELOG.md) - Complete version history and changes (v0.2.0 through v0.4.1)
- [RELEASE_NOTES_v0.4.2.md](./RELEASE_NOTES_v0.4.2.md) - Detailed release notes for v0.4.2

---

## 🏗️ Multi-Agent Architecture (NEW in v0.4.2)

Oracle Memory System now supports **multi-agent deployment** with shared and private memory isolation. This enables multiple AI agents to collaborate while maintaining appropriate access boundaries.

### Core Features
- **Agent Registry**: Centralized registration and discovery of all agents
- **Memory Visibility Control**: Three visibility levels (SHARED/PRIVATE/COLLABORATIVE)  
- **Session Management**: Track active sessions with working context preservation
- **Access Audit Trail**: Complete logging of all memory access operations
- **Collaboration Workflow**: Request/approve mechanism for agent-to-agent knowledge sharing

### Quick Start

#### 1. Execute Schema Extensions
```bash
echo "SQL" | sql openclaw/hermes@//10.10.10.130:1521/openclaw << 'EOF'
@scripts/agent_schema.sql
EXIT;
EOF
```

#### 2. Register an Agent
```python
from scripts.agent_api import AgentRegistryAPI

AgentRegistryAPI.register_agent(
    agent_id="my-agent-01",
    agent_name="My Analysis Agent", 
    agent_type="analysis",
    capabilities=["data-analysis", "pattern-recognition"],
    description="AI agent for data analysis"
)
```

#### 3. Create Memory with Visibility Control
```python
from scripts.agent_api import MemoryVisibilityAPI

# SHARED - accessible to all agents
MemoryVisibilityAPI.create_memory(
    memory_data={'content': 'System Documentation', 'category': 'doc'},
    visibility="SHARED"
)

# PRIVATE - only this agent can access  
MemoryVisibilityAPI.create_memory(
    memory_data={'content': 'My Private Config', 'category': 'config'},
    agent_id="my-agent-01",
    visibility="PRIVATE"
)

# COLLABORATIVE - specific agents only
MemoryVisibilityAPI.create_memory(
    memory_data={'content': 'Team Notes', 'category': 'team'},
    visibility="COLLABORATIVE",
    accessible_to=["agent-1", "agent-2"]
)
```

### Memory Visibility Matrix

| Visibility | Description | Who Can Access |
|------------|-------------|----------------|
| **SHARED** | Global knowledge (API docs, schemas) | All registered agents ✅ |
| **PRIVATE** | Agent-specific context and preferences | Only the owner agent ✅ |
| **COLLABORATIVE** | Team/project shared space | Agents in ACCESSIBLE_TO list ✅ |

### Schema Files
- `scripts/agent_schema.sql` - Complete DDL for all new tables, views, and indexes
- `scripts/agent_api.py` - High-level Python API for multi-agent operations
- `scripts/test_agent_architecture.py` - Integration test suite (run to verify setup)

### Design Document
See [references/multi-agent-design.md](./references/multi-agent-design.md) for detailed architecture explanation.

---

## 👨‍💻 Author & Maintainer

**Haiwen Yin (胖头鱼 🐟)**  
Oracle/PostgreSQL/MySQL ACE Database Expert

- **Blog**: https://blog.csdn.net/yhw1809
- **GitHub**: https://github.com/Haiwen-Yin

---

## 📄 License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.

**Last Updated**: 2026-05-04 v0.4.1