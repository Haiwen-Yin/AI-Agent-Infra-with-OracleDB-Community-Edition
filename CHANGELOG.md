# Oracle Memory System - Change Log

## v1.0.0 (2026-05-09) Production Release - Knowledge Base Edition

**🎯 MAJOR RELEASE**: First production-ready version for AI Agent deployments. Integrates complete Knowledge Base system with knowledge graph capabilities, experience distillation, and semantic search.

### 📚 Knowledge Base System (NEW in v1.0.0)

**Complete Knowledge Management Solution**
- ✅ Knowledge Concepts - Stable knowledge entities (FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE)
- ✅ Knowledge Graph - Property Graph-based relationship management (IS_A/PART_OF/CAUSES/ENABLES/CONTRADICTS/SUPPORTS)
- ✅ Experience Distillation - Automatic memory-to-knowledge transformation
- ✅ Hybrid Search - Semantic search + graph traversal combination
- ✅ Version Control - Complete version history for knowledge concepts
- ✅ Automated Jobs - 6 scheduled jobs for knowledge lifecycle management

### 🗄️ Knowledge Base Schema (NEW in v1.0.0)

**Six Core Tables**
- KNOWLEDGE_CONCEPTS - Core knowledge entities with semantic embeddings
- KNOWLEDGE_GRAPH - Knowledge relationships for graph traversal
- KNOWLEDGE_VERSIONS - Version history for knowledge concepts
- KNOWLEDGE_TAGS - Tag-based categorization
- KNOWLEDGE_DISTILLATION_LOG - Audit trail for memory-to-knowledge distillation
- KNOWLEDGE_SEARCH_HISTORY - Search analytics

### 🔧 Knowledge Base API (NEW in v1.0.0)

**PL/SQL API Package**
- create_concept() - Create new knowledge concept
- update_concept() - Update knowledge concept with versioning
- validate_concept() - Validate knowledge concept
- deprecate_concept() - Deprecate knowledge concept
- get_concept() - Get knowledge concept by ID
- create_relationship() - Create relationship between concepts
- get_relationships() - Get concept relationships
- traverse_graph() - Traverse knowledge graph
- find_path() - Find shortest path between concepts
- semantic_search() - Semantic search for knowledge
- distill_experience() - Distill experience from memories
- get_statistics() - Get knowledge base statistics
- get_graph_metrics() - Get knowledge graph metrics

**Python API Client**
- Full implementation of all PL/SQL API functions
- Automatic embedding generation using BGE-M3
- Comprehensive error handling

### 📊 Knowledge Property Graph (NEW in v1.0.0)

**Oracle 26ai Property Graph Integration**
- KNOWLEDGE_PROPERTY_GRAPH - Vertex and edge tables for graph traversal
- SQL/PGQ query support
- Relationship strength and confidence tracking

### ⏰ Automated Knowledge Management (NEW in v1.0.0)

**Six Scheduled Jobs**
- KNOWLEDGE_PATTERN_DETECTION - Daily 3:00 AM
- KNOWLEDGE_EXPERIENCE_EXTRACTION - Weekly Sunday 4:00 AM
- KNOWLEDGE_GRAPH_MAINTENANCE - Monthly 1st 5:00 AM
- KNOWLEDGE_STATS_COLLECTION - Daily 6:00 AM
- KNOWLEDGE_SEARCH_ANALYTICS - Weekly Saturday 2:00 AM
- KNOWLEDGE_HEALTH_MONITOR - Weekly Monday 7:00 AM

### 📋 New Files Added in v1.0.0

- `scripts/knowledge_base_schema_v2.sql` - Complete database schema (8.5 KB)
- `scripts/knowledge_base_api.sql` - PL/SQL API implementation (32.8 KB)
- `scripts/knowledge_property_graph.sql` - Property Graph definition (8.8 KB)
- `scripts/knowledge_jobs.sql` - Scheduled jobs and procedures (12.2 KB)
- `scripts/knowledge_base_api.py` - Python client library (23.8 KB)
- `scripts/test_knowledge_base.py` - Test suite (10.2 KB)
- `references/knowledge-base-design.md` - Detailed design document (27.5 KB)
- `README_KNOWLEDGE_BASE.md` - Usage documentation (13.3 KB)
- `RELEASE_NOTES_v1.0.0.md` - Release notes (11.5 KB)

### 🔧 Bug Fixes & Improvements

- Fixed execute_sql error detection logic for better accuracy
- Improved concept ID extraction using database queries
- Enhanced JSON parsing with error handling
- Updated version numbers across all files to v1.0.0

### 📊 Test Coverage

- Knowledge Concept CRUD operations: ✅ Verified
- Knowledge Graph relationship management: ✅ Verified
- Semantic search functionality: ✅ Verified
- Experience distillation: ✅ Verified
- Version control: ✅ Verified
- Statistics and monitoring: ✅ Verified

### 🎯 Production Readiness

**This version is production-ready for AI Agent deployments with:**
- Complete Knowledge Base system
- Knowledge Graph capabilities
- Experience Distillation
- Semantic Search
- Automated Knowledge Management
- Full Test Coverage
- Comprehensive Documentation

---

## v0.5.1 (2026-05-09) Official Release - Core Functionality Enhancement Edition

**✅ OFFICIAL RELEASE**: This is the first public release based on the v0.5.1 codebase. This version includes all features from v0.5.0 plus new functionality. Ready for production deployment.

### 🏗️ Multi-Agent Permission Management (NEW in v0.5.1)

**Agent Permission Downgrade & Data Recovery**
- ✅ Agent registry status tracking with PENDING_RECOVERY flag
- ✅ Automatic COLLABORATIVE data access recovery when agents are disabled
- ✅ JSON ACCESSIBLE_TO array manipulation to remove disabled agent permissions
- ✅ agent_permission_log audit table for all permission changes
- ✅ Hourly scheduled job (MEMORY_PERMISSION_CHECK_JOB) for pending recovery checks
- ✅ PL/SQL package `agent_permission_manager` with disable_agent_and_recover() and enable_agent() APIs

### ⚡ Enhanced Cleanup Framework (v0.5.1 Improvements)

**Snapshot Auto-Cleanup Enhancement**
- ✅ Centralized cleanup_config table with configurable retention policies
- ✅ snapshot_cleanup_manager PL/SQL package with intelligent batch processing
- ✅ Dual-tier cleanup: daily archival + weekly full cycle
- ✅ Added get_cleanup_stats() function for monitoring
- ✅ Improved error handling and retry logic

**Session Expiry Enhancement**
- ✅ session_config table with TTL (24h), warning threshold (18h), grace period (30min)
- ✅ agent_session.LAST_ACTIVITY tracking for accurate idle detection
- ✅ SESSION_TYPE classification: INTERACTIVE/BATCH/BACKGROUND
- ✅ session_manager PL/SQL package with should_extend_session() logic
- ✅ 30-minute cleanup job + daily expiry notification
- ✅ v_sessions_needing_attention view for monitoring

### 🧠 Memory Fusion Engine (NEW in v0.5.1)

**Semantic Deduplication & Merging**
- ✅ memory_fusion_history table tracking all fusion operations
- ✅ fUSION_ENGINE PL/SQL package with vector similarity detection
- ✅ find_similar_memories() using VECTOR_DISTANCE for semantic matching
- ✅ merge_similar_memories() with PREFER_NEWEST/PREFER_LONGER strategies
- ✅ enrich_memory() to combine related content across conversations
- ✅ Daily fusion cycle job (4 AM off-peak) + weekly statistics report

### 📋 New Files Added in v0.5.1
- `scripts/agent_permission_downgrade.sql` - Permission downgrade & recovery logic (338 lines)
- `scripts/enhanced_snapshot_cleanup_job.sql` - Enhanced snapshot cleanup framework (296 lines)
- `scripts/enhanced_session_cleanup.sql` - Session expiry management with job scheduling (274 lines)
- `scripts/memory_fusion_engine.sql` - Memory fusion deduplication & merging engine (385 lines)

### 🔧 Bug Fixes & Improvements
- Fixed agent_permission_downgrade.sql JSON array manipulation for ACCESSIBLE_TO fields
- Improved cleanup_batch logic in snapshot_cleanup with proper commit frequency
- Added session_config table to complement existing AGENT_SESSION schema
- Enhanced error handling across all PL/SQL packages with proper rollback behavior

---

## v0.5.0 (2026-05-08) - Security & Performance Enterprise Edition

### 🛡️ Enterprise Security Module (NEW in v0.5.0)

**Enterprise Data Masking Service**
- ✅ 4-Tier Desensitization Strategy: LOGGING(HIGH) / DEBUGGING(MEDIUM) / ANALYTICS(LOW) / SHARING(FULL)
- ✅ DESENSITIZE_LEVELS table for dynamic configuration
- ✅ Automatic PII detection: Email, IP address, API key, JWT token, and 10+ sensitive types
- ✅ Context-aware masking logic with scenario-based level selection

**Reversible Encryption (Fernet AES-128-CBC)**
- ✅ security/reversible_masking.py - Fernet-based encryption for internal debugging
- ✅ HMAC-SHA256 authentication integration
- ✅ Use case: Development/production parity testing, incident response

**Context-Aware Masking Logic**
- ✅ security/context_aware_masking.py - Automatic level selection based on usage scenario
- ✅ Integration with existing data masking service
- ✅ Scenario detection and automatic routing to appropriate masking tier

**Privacy-Preserving Aggregation Views**
- ✅ MEMORY_AGGREGATE_STATS view - Summary statistics without exposing individual records
- ✅ MEMORY_TYPE_STATS view - Distribution analysis across memory types
- ✅ SECURITY_MONITORING_V view - Audit trail aggregation views

### ⚡ Performance Optimizations (v0.5.0)

**Vector Storage Migration to Native VECTOR(1024)**
- ✅ Migrated from CLOB + TO_VECTOR() method to Oracle 26ai native VECTOR type
- ✅ Automatic indexing for similarity search queries
- ✅ Reduced storage overhead (~40% improvement)
- ✅ Query performance optimization via native vector operators

**Automated Cleanup Jobs**
- ✅ scripts/cleanup_orphaned_data.sql - Oracle Job scheduling for orphan cleanup
- ✅ scripts/session_cleanup_job.sql - Agent session expiration management (30-day TTL)
- ✅ Configurable retention policies for snapshots and audit logs

### 🏗️ Architecture Improvements

**Multi-Agent Consolidation**
- Removed "NEW in v0.4.2" status markers (feature was already stable)
- Updated documentation with production deployment recommendations
- Improved collaboration workflow documentation

**Task Plan System Maturity**
- Verified breakpoint recovery across all supported interruption scenarios
- Optimized snapshot compression and retrieval performance
- Enhanced pattern learning queries for historical task analysis

### 📋 New Files Added in v0.5.0
- `RELEASE_NOTES_v0.5.0.md` - Comprehensive release notes document
- `security/context_aware_masking.py` - Scenario-aware masking logic (199 lines)
- `security/reversible_masking.py` - Fernet AES-128-CBC encryption module (234 lines)
- `security/desensitize_levels.sql` - Layered strategy DDL with configuration table
- `security/aggregation_analysis.sql` - Aggregation views for privacy-preserving analytics

### 🔧 Bug Fixes & Improvements
- Fixed aggregation_analysis.sql to match existing MEMORIES table schema
- Resolved COLLECT_MEMORY_STATISTICS PL/SQL procedure compilation error
- Updated SKILL.md version references throughout (v0.4.x → v0.5.0)
- Removed redundant vector_migration_26ai.sql and shared_memory_cache.sql files

---

## v0.4.2 (2026-05-07) - Directory Consolidation & Naming Standardization

**Upgrade Level**: Patch - Internal Cleanup (No Functional Changes)

### 🔧 Changes in v0.4.2

**1. Directory Structure Consolidation**
- **Directory Rename**: `oracle-memory-by-yhw-v0.4.1/` → `oracle-memory-by-yhw/` (version removed from directory name)
- **SKILL.md Name Field**: Updated frontmatter: `name: oracle-memory-by-yhw`

**2. Independent Sub-skill Removal**
Removed redundant standalone sub-skills that duplicated content from the main skill:
- `oracle-26ai-memory-system-deployment-sop` - Deployment SOP now documented in main SKILL.md
- `oracle-memory-schema-design` - Schema design already integrated into main skill
- `oracle-memory-version-upgrade-sop` - Version upgrade procedures consolidated into v0.4.1+
- `oracle-memory-python-script-dependency-fix` - Content merged into main skill's reference docs

**3. Reference Documentation Integration**
- Merged into: `references/script-deployment-troubleshooting.md`
- Consolidates Python script dependency troubleshooting guide previously available as standalone sub-skill
- Covers hermes_tools import error resolution, Oracle connection format standards, and corruption detection criteria

### 📋 Version Migration Note

> **Note for v0.4.1 → v0.4.2 migration**: No database or code changes required. Only internal directory structure adjustments.

---

## v0.4.1 (2026-05-04) - Task Plan Persistence Integration Edition

### 🆕 New Features: Task Plan System

**Task Plan Management**
- ✅ TASK_PLANS table - Core task planning with status tracking (PENDING/RUNNING/SUCCESS/FAILED/CANCELLED/PAUSED)
- ✅ TASK_STEPS table - Step-by-step execution recording with unique constraints
- ✅ TASK_TOOL_CALLS table - Complete audit trail of all agent tool invocations
- ✅ TASK_DEPENDENCIES table - Task relationship graph for complex workflows

**Breakpoint Recovery System (Core Feature)**
- ✅ TASK_CONTEXT_SNAPSHOTS table - Full state preservation during task execution
- ✅ IS_LATEST flag mechanism - Automatic snapshot versioning for resume capability
- ✅ Auto-snapshot on progress updates - Context preserved every status change
- ✅ Resume API function - Complete agent context restoration after failures

**Historical Learning & Pattern Recognition**
- ✅ search_completed_tasks() API - Query historical task patterns and outcomes
- ✅ Success/failure pattern analysis - Learn from past execution results
- ✅ Task dependency tracking - Identify recurring workflow patterns

### 🔧 API Functions (Python Integration)

| Function | Purpose | Key Features |
|----------|---------|--------------|
| `create_task_plan()` | Create new task with initial snapshot | Auto-saves agent state + conversation history |
| `update_task_progress()` | Update status during execution | Creates auto snapshots on every change |
| `resume_task()` | Restore after interruption | Loads latest snapshot, finds incomplete steps |
| `search_completed_tasks()` | Learn from historical patterns | Returns success metrics and task statistics |

### 📊 Indexing & Performance Optimizations (v0.4.1)

- ✅ 5 database sequences for auto-increment primary keys
- ✅ 9 Task Plan specific indexes for optimal query performance:
  - IDX_TASK_PLANS_STATUS, IDX_TASK_PLANS_TYPE, IDX_TASK_PLANS_CREATED
  - IDX_TASK_STEPS_PLAN, IDX_TASK_STEPS_STATUS
  - IDX_CONTEXT_SNAPSHOT_PLAN (IS_LATEST filter optimization)
  - IDX_TOOL_CALLS_PLAN, IDX_TOOL_CALLS_TIME

### 🔧 Improvements

- **TRIGGER column fix**: Renamed to TRIGGER_REASON in TASK_CONTEXT_SNAPSHOTS table
  - Reason: Oracle reserved word conflict resolution
  - Impact: All references updated for consistency
  
- **Documentation completeness**: SKILL.md fully aligned with database deployment

### ⚠️ Known Limitations

- Same as v0.4.0 (JRD, Vector Index, Oracle Text issues documented)
- TRIGGER column renamed to TRIGGER_REASON - update any external scripts accordingly

---

## v0.4.0 (2026-04-29) - JRD + Property Graph + Oracle Text Integration

### 🆕 New Features

- **Oracle Text Full-Text Search**
  - ✅ CTX CONTEXT index created on MEMORIES.CONTENT
  - ✅ CTX CONTEXT index created on MEMORY_NODES.LABEL
  - ✅ CONTAINS() keyword search with relevance scoring (SCORE())
  - ✅ Chinese character search works (basic lexer)
  - ✅ Boolean operators: AND, OR, NOT
  - ✅ Wildcard search with prefix matching (%pattern%)
  - ✅ Combined text + vector + graph queries verified

- **Three-Layer Search Architecture**
  - ✅ Text Search (Oracle Text CONTAINS)
  - ✅ Vector Search (VECTOR_DISTANCE)
  - ✅ Graph Search (SQL/PGQ + Relationship Traversal)

### 🔧 Improvements

- Updated SKILL.md with Oracle Text integration section
- Added search capabilities matrix and architecture diagram

### ⚠️ Known Limitations

- **DBMS_SEARCH.FIND()**: Has DRG-13600 bug in Oracle 23.26.1.0.0
  - Workaround: Use traditional CTX CONTAINS() approach
- **CHINESE_VGRAM_LEXER**: Not available in this Oracle build
  - Basic lexer handles Chinese at character level
  - For better tokenization, wait for Oracle Text patch

---
