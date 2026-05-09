# Oracle Memory System v0.5.1 Release Notes

## Version Information
- **Version**: 0.5.1 (Core Functionality Enhancement Edition)
- **Release Date**: May 9, 2026
- **Author**: Haiwen Yin (胖头鱼 🐟)
- **Previous Version**: 0.5.0

## Executive Summary

The v0.5.1 release delivers critical core functionality enhancements to make the Oracle Memory System production-ready for multi-agent deployments. This version addresses four key operational gaps identified in v0.5.0: agent permission management, enhanced cleanup framework, session expiry tracking, and memory deduplication capabilities.

## New Features

### 1. Agent Permission Downgrade & Data Recovery (NEW)
**File**: `scripts/agent_permission_downgrade.sql`

When agents are disabled in the system, their access to COLLABORATIVE memories must be automatically revoked to prevent unauthorized data exposure.

**Key Components:**
- `agent_permission_log` table - Comprehensive audit trail for all permission changes
- PL/SQL package `agent_permission_manager` with core downgrade logic
- `MEMORY_PERMISSION_CHECK_JOB` scheduler job running hourly
- Automatic JSON ACCESSIBLE_TO array manipulation to remove disabled agent permissions

**API Functions:**
```sql
-- Disable agent and automatically recover their COLLABORATIVE data
EXECUTE IMMEDIATE 'BEGIN agent_permission_manager.disable_agent_and_recover(:p1, :p2); END;' USING p_agent_id, p_reason;

-- Re-enable agent when appropriate  
EXECUTE IMMEDIATE 'BEGIN agent_permission_manager.enable_agent(:p1); END;' USING p_agent_id;
```

### 2. Enhanced Snapshot Cleanup Framework (ENHANCED)
**File**: `scripts/enhanced_snapshot_cleanup_job.sql`

The cleanup framework has been enhanced from basic SQL scripts to a production-ready system with centralized configuration and improved scheduling.

**Key Components:**
- `cleanup_config` table - Centralized retention policy management
- PL/SQL package `snapshot_cleanup_manager` with intelligent batch processing
- Dual-tier cleanup: daily archival + weekly full cycle operations
- Added `get_cleanup_stats()` monitoring function

### 3. Session Expiry Management Enhancement (ENHANCED)  
**File**: `scripts/enhanced_session_cleanup.sql`

Session management now includes intelligent classification, configurable TTL policies, and grace period handling for graceful session termination.

**Key Components:**
- `session_config` table - TTL configuration (24h default), warning threshold (18h), grace period (30min)
- Enhanced `agent_session` table with LAST_ACTIVITY tracking and SESSION_TYPE classification
- PL/SQL package `session_manager` with should_extend_session() logic
- 30-minute cleanup job + daily expiry notification

### 4. Memory Fusion Engine (NEW)
**File**: `scripts/memory_fusion_engine.sql`

The Memory Fusion Engine provides semantic deduplication and content merging using Oracle's native vector similarity capabilities.

**Key Components:**
- `memory_fusion_history` table - Comprehensive operation tracking
- PL/SQL package `memory_fusion_engine` with vector-based similarity detection
- Support for multiple merge strategies (PREFER_NEWEST, PREFER_LONGER)
- Content enrichment by combining related memories across conversations

## Bug Fixes & Improvements

1. Fixed agent_permission_downgrade.sql JSON array manipulation for ACCESSIBLE_TO fields
2. Improved cleanup_batch logic in snapshot_cleanup with proper commit frequency
3. Added session_config table to complement existing AGENT_SESSION schema
4. Enhanced error handling across all PL/SQL packages with proper rollback behavior

## Database Schema Changes

### New Tables Created:
- `agent_permission_log` - Permission change audit trail
- `memory_fusion_history` - Fusion operation history  
- `cleanup_config` - Centralized cleanup configuration
- `session_config` - Session TTL management configuration
- `v_sessions_needing_attention` - Monitoring view for sessions requiring attention
- `v_pending_fusions` - View showing pending fusion operations

### Schema Extensions:
- `agent_registry` - Added LAST_PERMISSION_CHECK, PENDING_RECOVERY, RECOVERED_COUNT columns
- `agent_session` - Added LAST_ACTIVITY, SESSION_TYPE, MAX_IDLE_TIME columns

## Scheduled Jobs Created

| Job Name | Schedule | Description |
|----------|----------|-------------|
| MEMORY_PERMISSION_CHECK_JOB | Hourly | Check disabled agents for pending recovery |
| SNAPSHOT_CLEANUP_DAILY | Daily 2:00 AM | Clean expired snapshots and archive old ones |
| SNAPSHOT_CLEANUP_WEEKLY | Sunday 3:00 AM | Full cleanup cycle including all data types |
| SESSION_CLEANUP_JOB | Every 30 minutes | Expire idle sessions based on TTL policies |
| MEMORY_FUSION_CYCLE | Daily 4:00 AM | Run memory deduplication and merging operations |

## Migration Notes

### From v0.5.0 to v0.5.1:
1. Execute all four new SQL scripts in order:
   - `agent_permission_downgrade.sql` (required first due to schema extensions)
   - `enhanced_snapshot_cleanup_job.sql`
   - `enhanced_session_cleanup.sql` 
   - `memory_fusion_engine.sql`

2. No data migration required - all changes are additive only

3. Verify scheduled jobs are running:
```sql
SELECT JOB_NAME, STATE, REPEAT_INTERVAL 
FROM DBA_SCHEDULER_JOBS 
WHERE JOB_NAME LIKE 'MEMORY%' OR JOB_NAME LIKE 'SNAPSHOT%' OR JOB_NAME LIKE 'SESSION%';
```

## Testing Recommendations

1. Test agent disable/enable workflow with COLLABORATIVE memory access
2. Verify cleanup jobs execute at expected intervals
3. Validate session expiry behavior under various load conditions
4. Confirm memory fusion operations complete without data loss

---
**Status**: Production Ready ✅
