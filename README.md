# Oracle AI Database Memory System v0.4.1 Task Plan Integration Edition

[![Version](https://img.shields.io/badge/version-0.4.1-blue.svg)](CHANGELOG.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-green.svg)](https://www.oracle.com/database/technologies/oracle-database-software-downloads.html)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Universal memory system for all AI Agents with JRD, Property Graph, Oracle Text full-text search, Task Plan persistence with breakpoint recovery, and optimized indexing strategy.**

---

## 🎯 Executive Summary

This is the **v0.4.1 Task Plan Integration Edition** - an upgrade from v0.4.0 that introduces critical AI Agent capabilities:
- ✅ **Task Plan Persistence** - Durable task tracking across sessions
- ✅ **Breakpoint Recovery** - Resume exactly where interrupted after failures
- ✅ **Historical Learning** - Learn from past task patterns and outcomes

---

## 📊 v0.4.1 Feature Comparison

| Feature | v0.3.0 | v0.3.1 | v0.4.0 | **v0.4.1** |
|---------|--------|--------|--------|-----------|
| **Target Users** | All AI Agents | ✅ All AI Agents | ✅ All AI Agents | ✅ All AI Agents |
| **Task Plan Storage** | ❌ Not included | ❌ Not included | ❌ Not included | ✅ **Complete Task Plan System** |
| **Breakpoint Recovery** | ❌ None | ❌ None | ❌ None | ✅ **Auto Snapshot + Resume API** |
| **Historical Learning** | ❌ Limited | ❌ Limited | ❌ Limited | ✅ **Task Pattern Recognition** |
| **Status Tracking** | ❌ Basic | ⚠️ Partial | ⚠️ Partial | ✅ **Detailed Step-by-Step Audit** |
| **JRD Implementation** | ❌ Plan only | ⚠️ Plan documented | ✅ **Full implementation** | ✅ **Full implementation** |
| **Property Graph** | ❌ Not tested | ✅ Integration verified | ✅ **CREATE PROPERTY GRAPH + SQL/PGQ** | ✅ **CREATE PROPERTY GRAPH + SQL/PGQ** |

---

## 🆕 v0.4.1 New: Task Plan Persistence System

### Overview

The Task Plan system provides AI Agents with durable task execution tracking, enabling:
- **Breakpoint recovery after failures** - Resume exactly where interrupted with full context
- **Historical pattern learning from completed tasks** - Learn from past success/failure modes
- **Detailed status auditing** - Complete audit trail of all agent actions

### Architecture Diagram (Task Plan System)

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
                       │CONTEXT_SNAPSHOTS│ ← **Critical for breakpoint recovery**
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

## 📋 Quick Start

### Prerequisites

1. **Oracle AI Database 23ai/26ai** (Required)
   - Must have `VECTOR` type support (23ai 23.6+ or 26ai)
   - Download from [Oracle AI Database](https://www.oracle.com/database/technologies/oracle-database-software-downloads.html)

2. **Java Runtime** (Required for SQLcl)
   ```bash
   java -version  # Verify Java installation
   # Install if needed: sudo apt install openjdk-21-jdk
   ```

3. **SQLcl v26.1** (Recommended)
   - Download from [Oracle SQLcl](https://www.oracle.com/database/sqldeveloper/technologies/sqlcl/download/)
   - Extract to `/root/sqlcl/`
   - **Important**: Path is `/root/sqlcl/sqlcl/bin/sql` (double `sqlcl` directory!)

---

## 🚀 Installation

### Step 1: Clone or Download Skill Files

The skill files are located in `/root/.hermes/skills/oracle-memory-by-yhw-v0.4.1/`

```bash
ls -la /root/.hermes/skills/oracle-memory-by-yhw-v0.4.1/
```

### Step 2: Configure Database Connection

Create `~/.oracle-memory/config.env`:

```bash
# Primary database (for writes)
export PRIMARY_CONN="openclaw@//10.10.10.130:1521/openclaw"

# Standby database (for reads - optional, enables ADG)
export STANDBY_CONN="openclaw@//10.10.10.131:1521/openclaw_standby"

# Embedding model configuration
export EMBEDDING_MODEL="bge-m3"  # or text-embedding-3-small/large
export LMSTUDIO_ENDPOINT="http://10.10.10.1/v1/embeddings"
```

### Step 3: Initialize Memory Schema

```bash
# Run the schema initialization script
/root/sqlcl/sqlcl/bin/sql $PRIMARY_CONN @scripts/init_schema.sql
```

---

## 📊 System Architecture Overview

### High-Level Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     Oracle AI Database Memory System               │
│                        (v0.4.1 Task Plan Integration)              │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────┐                                              │
│  │   All AI Agents  │                                              │
│  │ (via MCP Server) │                                              │
│  └────────┬─────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌──────────────────┐         ┌──────────────────┐                 │
│  │   SQLcl MCP      │◄────────│  Memory System   │                 │
│  │   (Primary       │         │  Interface Layer │                 │
│  │    Interface)    │         └────────┬─────────┘                 │
│  └──────────────────┘                  │                           │
│                                        ▼                           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    JRD View Layer                           │   │
│  │  memory_nodes_jdv / memory_edges_jdv / memories_jdv         │   │
│  │  memory_graph_v / memory_graph_json_v                       │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │               Relationship Tables (Structured)              │   │
│  │  memory_node_properties / memory_edge_properties            │   │
│  │  memory_content_fields / memory_tag_items                   │   │
│  │  memory_metadata_fields / memory_node_tags                  │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                    Core Tables                              │   │
│  │  memory_nodes / memory_edges / memories                     │   │
│  │  memories_vectors / memory_relationships                    │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │              Task Plan System (v0.4.1 New)                  │   │
│  │  TASK_PLANS / TASK_STEPS / CONTEXT_SNAPSHOTS                │   │
│  │  TASK_TOOL_CALLS / TASK_DEPENDENCIES                        │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │              Property Graph (SQL/PGQ)                       │   │
│  │  MEMORY_PROPERTY_GRAPH (26ai native)                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│    Benefits:                                                       │
│    ✅ Zero Data Loss Protection (RPO ≈ 0)							 │
│    ✅ Read-Write Separation (3-5x query performance improvement)	 │
│    ✅ JRD views for JSON format output	                         │
│    ✅ Property Graph for SQL/PGQ graph queries	                 │
│    ✅ Structured storage (no JSON redundancy)	                     │
│    ✅ Task Plan persistence with breakpoint recovery	             │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 🗄️ Database Schema

### v0.4.1 New: Task Plan Tables

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

### Task Plan Indexes (v0.4.1)

```sql
-- TASK_PLANS indexes
CREATE INDEX IDX_TASK_PLANS_STATUS ON TASK_PLANS(STATUS);
CREATE INDEX IDX_TASK_PLANS_TYPE ON TASK_PLANS(PLAN_TYPE);
CREATE INDEX IDX_TASK_PLANS_CREATED ON TASK_PLANS(CREATED_AT DESC);
CREATE INDEX IDX_TASK_PLANS_PRIORITY ON TASK_PLANS(PRIORITY, CREATED_AT);

-- TASK_STEPS indexes
CREATE INDEX IDX_TASK_STEPS_PLAN ON TASK_STEPS(PLAN_ID, STEP_ORDER);
CREATE INDEX IDX_TASK_STEPS_STATUS ON TASK_STEPS(STATUS);

-- TASK_CONTEXT_SNAPSHOTS index (Oracle does not support WHERE on index)
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

## 🔧 API Functions (Python Integration)

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
```

### resume_task() - Resume task execution from breakpoint (core feature)

```python
def resume_task(plan_id):
    """
    Resume task execution from breakpoint
    
    Args:
        plan_id (str): Plan ID
    
    Returns:
        dict: Restored context information including next_action, incomplete_steps
    """
    # 1. Get latest snapshot (IS_LATEST = 'Y')
    # 2. Restore agent_state and conversation_history from CONTEXT_DATA
    # 3. Identify incomplete steps by checking STEP status
    # 4. Resume execution with NEXT_ACTION as starting point
```

### search_completed_tasks() - Search completed tasks for learning and pattern reuse

```python
def search_completed_tasks(query_params):
    """
    Search completed tasks for learning and pattern reuse
    
    Args:
        query_params (dict): {type, status, tags, keywords, date_range}
    
    Returns:
        list[dict]: Matching task list with success metrics and statistics
    """
```

---

## 📚 Documentation

- [CHANGELOG.md](./CHANGELOG.md) - Complete version history and changes (v0.2.0 through v0.4.1)
- [RELEASE_NOTES_v0.4.1.md](../RELEASE_NOTES_v0.4.1.md) - Detailed release notes for v0.4.1

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