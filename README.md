# Oracle AI Database Memory System v0.5.1 (Official Release)

[![Version](https://img.shields.io/badge/version-v0.5.1-green.svg)](CHANGELOG.md)
[![Oracle AI DB](https://img.shields.io/badge/Oracle-26ai-green.svg)](https://www.oracle.com/database/technologies/oracle-database-software-downloads.html)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Universal memory system for all AI Agents with JRD, Property Graph, Multi-Agent Architecture, Task Plan management, enterprise-grade security, Memory Fusion Engine, and optimized indexing strategy.**

---

## 🎯 Executive Summary

This is the **v0.5.1 Core Functionality Enhancement Edition (Official Release)** - production-ready version with Agent Permission Management, Memory Fusion Engine, and enhanced cleanup framework.
- ✅ **Task Plan Persistence** - Durable task tracking across sessions
- ✅ **Breakpoint Recovery** - Resume exactly where interrupted after failures
- ✅ **Historical Learning** - Learn from past task patterns and outcomes

---

## 📊 Version History & Comparison

| Feature | v0.3.x | v0.4.0 | v0.4.1 | v0.5.0 | **v0.5.1** |
|---------|--------|--------|--------|-----------|
| **Memory System** | ✅ Core | ✅ Enhanced | ✅ Optimized | ✅ Production Ready | ✅ **Production Ready + Memory Fusion** |
| **JRD Implementation** | ✅ Full | ✅ Full | ✅ Full | ✅ **Production Optimized** |
| **Property Graph** | ✅ Verified | ✅ Native SQL/PGQ | ✅ SQL/PGQ | ✅ **SQL/PGQ + Multi-Agent Access** |
| **Task Plan System** | ❌ None | ❌ None | ✅ Complete | ✅ **Enhanced with Agent Tracking** | ✅ **Enhanced with Permission Management** |
| **Breakpoint Recovery** | ❌ None | ❌ None | ✅ Auto Snapshot | ✅ **Auto Snapshot + Resume API** |
| **Multi-Agent Arch** | ❌ N/A | ❌ N/A | ❌ Not included | ✅ **Agent Registry + Session Mgmt** | ✅ **Full Collaboration Framework** |

---

## 🆕 v0.4.2 New: Multi-Agent Architecture & Enhanced Task Plans

### Overview

The Multi-Agent Architecture provides a structured framework for managing multiple AI agents with centralized memory access control, session management, and collaboration capabilities.

This edition introduces four new components:
- **Agent Registry (AGENT_REGISTRY)** - Centralized agent lifecycle management
- **Memory Access Control (AGENT_MEMORY_ACCESS)** - Fine-grained visibility policies  
- **Collaboration Framework (AGENT_COLLABORATION)** - Agent-to-agent communication channels
- **Session Management (AGENT_SESSION)** - Active session tracking and monitoring

### Architecture Diagram (Multi-Agent System)

```
┌───────────────────────────────────────────────────┐
│              Multi-Agent Memory System            │
│                v0.4.2 Edition                     │
├───────────────────────────────────────────────────┤
│                                                   │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐  │
│  │ Agent A   │    │ Agent B   │    │ Agent C   │  │
│  │ (Analyzer)│    │(Writer)   │    │(Deployer) │  │
│  └─────┬─────┘    └─────┬─────┘    └─────┬─────┘  │
│        │                │                │        │
│        ▼                ▼                ▼        │
│  ┌─────────────────────────────────────────────┐  │
│  │    AGENT_REGISTRY (Central)                 │  │
│  │  • Registration & Lifecycle                 │  │
│  │  • Capability Discovery                     │  │
│  │  • Health Monitoring                        │  │
│  └───────────────┬─────────────────────────────┘  │
│                  │                                │
│  ┌───────────────▼───────────────┐                │
│  │    AGENT_MEMORY_ACCESS        │                │
│  │  • Visibility Policies        │                │
│  │  • Data Access Control        │                │
│  └───────────────────────────────┘                │
│                  │                                │
│  ┌───────────────▼───────────────┐                │
│  │    AGENT_COLLABORATION        │                │
│  │  • Communication Channels     │                │
│  │  • Cross-Agent Sharing        │                │
│  └───────────────────────────────┘                │
│                  │                                │
│  ┌───────────────▼───────────────┐                │
│  │    AGENT_SESSION              │                │
│  │  • Session Tracking           │                │
│  │  • State Management           │                │
│  └───────────────────────────────┘                │
│                  │                                │
│  ┌───────────────▼───────────────┐                │
│  │       MEMORIES TABLE          │                │
│  │    (Memory Storage Layer)     │                │
│  └───────────────────────────────┘                │
│                                                   │
│    Benefits:                                      │
│    ✅ Centralized Agent Management	            │
│    ✅ Fine-Grained Memory Access Control	        │
│    ✅ Built-in Collaboration Framework	        │
│    ✅ Session State Persistence	                │
│    ✅ Multi-Agent Scalability	                    │
│                                                   │
└───────────────────────────────────────────────────┘
```

---

## 🆕 v0.4.2 New: Enhanced Task Plans

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

## 🔧 API Functions (Python Integration)

### create_task_plan() - Create task plan and automatically save initial context snapshot

```python
def create_task_plan(plan_name, plan_type, description, steps):
    \"\"\"
    Create a new task plan and automatically save initial context
    
    Args:
        plan_name (str): Task name
        plan_type (str): task/deployment/research/analysis
        description (str): Task description
        steps (list[dict]): Step list [{order, name, action}, ...]
    
    Returns:
        dict: Created plan information
    \"\"\"
```

### resume_task() - Resume task execution from breakpoint (core feature)

```python
def resume_task(plan_id):
    \"\"\"
    Resume task execution from breakpoint
    
    Args:
        plan_id (str): Plan ID
    
    Returns:
        dict: Restored context information including next_action, incomplete_steps
    \"\"\"
    # 1. Get latest snapshot (IS_LATEST = 'Y')
    # 2. Restore agent_state and conversation_history from CONTEXT_DATA
    # 3. Identify incomplete steps by checking STEP status
    # 4. Resume execution with NEXT_ACTION as starting point
```

### search_completed_tasks() - Search completed tasks for learning and pattern reuse

```python
def search_completed_tasks(query_params):
    \"\"\"
    Search completed tasks for learning and pattern reuse
    
    Args:
        query_params (dict): {type, status, tags, keywords, date_range}
    
    Returns:
        list[dict]: Matching task list with success metrics and statistics
    \"\"\"
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


### Step 1: Clone or Download Skill Files

The skill files are located in `/root/.hermes/skills/oracle-memory-by-yhw/`

```bash
ls -la /root/.hermes/skills/oracle-memory-by-yhw/
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

## 🆕 v0.5.1 Official Release - Core Functionality Enhancement

### ✨ Features in Official Release v0.5.1

This official release focuses on **core operational functionality** to make the system production-ready:

| Feature | Description | Status |
|---------|-------------|--------|
| **Agent Permission Downgrade** | Automatic COLLABORATIVE data access recovery when agents are disabled | ✅ Implemented |
| **Enhanced Snapshot Cleanup** | Centralized config table with dual-tier cleanup (daily archival + weekly full cycle) | ✅ Enhanced |
| **Session Expiry Management** | Intelligent session classification with TTL, warning threshold, and grace period | ✅ Enhanced |
| **Memory Fusion Engine** | Semantic deduplication and merging using vector similarity detection | ✅ New Feature |

### 🏗️ Agent Permission Downgrade Details

When an agent is disabled in the system, this feature ensures that:
1. The `PENDING_RECOVERY` flag is set to track recovery operations
2. All COLLABORATIVE memories accessible to the disabled agent are identified
3. The agent ID is removed from JSON ACCESSIBLE_TO arrays
4. Changes are logged in `agent_permission_log` for audit purposes
5. An hourly scheduled job checks and processes any pending recoveries

**API Functions:**
- `disable_agent_and_recover(agent_id, reason)` - Disable agent with automatic data recovery
- `enable_agent(agent_id)` - Re-enable agent and restore access
- `scheduled_permission_check()` - Cron-triggered pending recovery check

### ⚡ Enhanced Cleanup Framework

The cleanup framework has been enhanced from basic SQL scripts to a production-ready system:

**Centralized Configuration:**
- `cleanup_config` table with configurable retention policies
- `session_config` table for TTL management (24h default, 18h warning threshold)

**Improved Scheduling:**
- Daily snapshot cleanup at 2 AM
- Weekly full cycle cleanup on Sundays at 3 AM  
- Session expiry monitoring every 30 minutes
- Monthly archive statistics reports

### 🧠 Memory Fusion Engine

The new Memory Fusion Engine provides semantic deduplication and content merging:

**Core Capabilities:**
- Vector similarity detection using Oracle's VECTOR_DISTANCE function
- Intelligent merge strategies (PREFER_NEWEST, PREFER_LONGER)
- Content enrichment by combining related memories
- Comprehensive fusion operation history tracking

**API Functions:**
- `find_similar_memories(memory_id, threshold)` - Find semantically similar memories
- `deduplicate_batch(batch_size)` - Process a batch for deduplication
- `merge_similar_memories(memory_ids, strategy)` - Merge similar memories
- `enrich_memory(target_id)` - Combine related content into target memory


---

## 📊 System Architecture Overview

### High-Level Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     Oracle AI Database Memory System               │
│                    (Multi-Agent Architecture Edition)              │
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
│  │              Enhanced Task Plans                            │   │
│  │  TASK_PLANS / TASK_STEPS / CONTEXT_SNAPSHOTS                │   │
│  │  TASK_TOOL_CALLS / TASK_DEPENDENCIES                        │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │              Property Graph (SQL/PGQ)                       │   │
│  │  MEMORY_PROPERTY_GRAPH (26ai native)                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│    Benefits:                                                       │
│    ✅ Zero Data Loss Protection (RPO ≈ 0)	                         │
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

### Enhanced Task Plan Tables

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

### Task Plan Indexes

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

- [CHANGELOG.md](./CHANGELOG.md) - Complete version history and changes (v0.2.0 through v0.5.1)
- [RELEASE_NOTES_v0.4.2.md](./RELEASE_NOTES_v0.4.2.md) - Detailed release notes
- [RELEASE_NOTES_v0.5.1.md](./RELEASE_NOTES_v0.5.1.md) - Official Release documentation
- [references/multi-agent-design.md](./references/multi-agent-design.md) - Multi-Agent Architecture design document

---

## 👨‍💻 Author & Maintainer

**Haiwen Yin (胖头鱼 🐟)**  
Oracle/PostgreSQL/MySQL ACE Database Expert

- **Blog**: https://blog.csdn.net/yhw1809
- **GitHub**: https://github.com/Haiwen-Yin

---

## 📄 License

This project is licensed under the Apache License, Version 2.0 - see the [LICENSE](LICENSE) file for details.

**Last Updated**: 2026-05-09 v0.5.1