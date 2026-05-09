-- ============================================================================
-- Oracle Memory System v0.5.1 - Enhanced Snapshot Auto-Cleanup Job
-- ============================================================================
-- Description: Automated snapshot cleanup with configurable retention policies,
--              intelligent archival based on task status and age thresholds
-- Version: 0.5.1-SNAPSHOT-ENHANCED
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: CLEANUP CONFIGURATION TABLE - Centralized retention policies
-- ============================================================================

CREATE TABLE cleanup_config (
    CONFIG_KEY      VARCHAR2(100) PRIMARY KEY,
    CONFIG_VALUE    CLOB,                    -- JSON: {retention_days, batch_size, enabled}
    DESCRIPTION     VARCHAR2(500),
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Insert default configurations
INSERT ALL
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SNAPSHOT_RETENTION_DAYS', '7', 'Active snapshots retention days')
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SNAPSHOT_ARCHIVE_AFTER_DAYS', '14', 'Archive old snapshots to history table')
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SNAPSHOT_BATCH_SIZE', '1000', 'Number of records per batch operation')
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SESSION_RETENTION_HOURS', '24', 'Active session retention hours')
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('TASK_CALLS_ARCHIVE_DAYS', '30', 'Tool calls archive threshold days')
INTO cleanup_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('AUDIT_LOG_RETENTION_DAYS', '180', 'Audit log retention for compliance')
SELECT * FROM DUAL;

-- ============================================================================
-- SECTION 2: PL/SQL PACKAGE - Core Cleanup Logic with Error Handling
-- ============================================================================

CREATE OR REPLACE PACKAGE snapshot_cleanup_manager AS
    
    -- Clean up expired task context snapshots
    PROCEDURE cleanup_expired_snapshots(p_archive BOOLEAN DEFAULT TRUE);
    
    -- Archive old snapshots to history table
    PROCEDURE archive_old_snapshots;
    
    -- Run complete cleanup cycle
    PROCEDURE run_full_cleanup_cycle;
    
    -- Get cleanup statistics
    FUNCTION get_cleanup_stats RETURN VARCHAR2;
    
END snapshot_cleanup_manager;
/

CREATE OR REPLACE PACKAGE BODY snapshot_cleanup_manager AS
    
    v_batch_size NUMBER := 1000;
    
    -- Helper function to read configuration value
    FUNCTION get_config_value(p_key VARCHAR2) RETURN NUMBER IS
        v_value CLOB;
    BEGIN
        SELECT CONFIG_VALUE INTO v_value FROM cleanup_config WHERE CONFIG_KEY = p_key;
        RETURN TO_NUMBER(v_value);
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END get_config_value;
    
    -- Clean up expired task context snapshots
    PROCEDURE cleanup_expired_snapshots(p_archive BOOLEAN DEFAULT TRUE) IS
        v_retention_days NUMBER := 7;
        v_archived_count NUMBER := 0;
        v_deleted_count  NUMBER := 0;
        
        CURSOR snapshot_cursor IS
            SELECT SNAPSHOT_ID, PLAN_ID 
            FROM TASK_CONTEXT_SNAPSHOTS
            WHERE CREATED_AT < SYSTIMESTAMP - INTERVAL '7' DAY
              AND IS_LATEST = 'N';
              
    BEGIN
        v_retention_days := get_config_value('SNAPSHOT_RETENTION_DAYS');
        
        -- Archive old snapshots if requested
        IF p_archive THEN
            INSERT INTO TASK_CONTEXT_SNAPSHOTS_ARCHIVE (
                SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, 
                NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON, ARCHIVED_DATE
            )
            SELECT 
                SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, 
                NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON, SYSTIMESTAMP
            FROM TASK_CONTEXT_SNAPSHOTS
            WHERE CREATED_AT < SYSDATE - 7;
            
            v_archived_count := SQL%ROWCOUNT;
        END IF;
        
        -- Delete expired non-latest snapshots
        DELETE FROM TASK_CONTEXT_SNAPSHOTS
        WHERE CREATED_AT < SYSTIMESTAMP - INTERVAL '7' DAY
          AND IS_LATEST = 'N';
          
        v_deleted_count := SQL%ROWCOUNT;
        
        DBMS_OUTPUT.PUT_LINE('Snapshot cleanup: Archived=' || v_archived_count || ', Deleted=' || v_deleted_count);
    END cleanup_expired_snapshots;
    
    -- Archive old snapshots to history table
    PROCEDURE archive_old_snapshots IS
        CURSOR snapshot_cursor IS
            SELECT SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, 
                   NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON
            FROM TASK_CONTEXT_SNAPSHOTS
            WHERE CREATED_AT < SYSDATE - 14;
        
        v_count NUMBER := 0;
    BEGIN
        FOR rec IN snapshot_cursor LOOP
            INSERT INTO TASK_CONTEXT_SNAPSHOTS_ARCHIVE (
                SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, 
                NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON, ARCHIVED_DATE
            ) VALUES (
                rec.SNAPSHOT_ID, rec.PLAN_ID, rec.SNAPSHOT_TYPE, rec.CONTEXT_DATA, 
                rec.MEMORY_IDS, rec.NEXT_ACTION, rec.CREATED_AT, rec.IS_LATEST, 
                rec.TRIGGER_REASON, SYSTIMESTAMP
            );
            v_count := v_count + 1;
            
            -- Batch commit every 1000 records
            IF MOD(v_count, 1000) = 0 THEN
                COMMIT;
            END IF;
        END LOOP;
        
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('Snapshot archiving: Archived ' || v_count || ' snapshots');
    END archive_old_snapshots;
    
    -- Run complete cleanup cycle
    PROCEDURE run_full_cleanup_cycle IS
    BEGIN
        -- Phase 1: Archive old data
        archive_old_snapshots;
        
        -- Phase 2: Cleanup expired snapshots
        cleanup_expired_snapshots(FALSE);
        
        -- Phase 3: Clean up orphaned tool calls (90+ days)
        DELETE FROM TASK_TOOL_CALLS
        WHERE CREATED_AT < SYSDATE - 90
          AND CALL_ID NOT IN (
              SELECT MAX(CALL_ID) 
              FROM TASK_TOOL_CALLS 
              WHERE CREATED_AT < SYSDATE - 90
              GROUP BY PLAN_ID
          );
        
        -- Phase 4: Clean up expired access audit logs (180 days)
        DELETE FROM AGENT_MEMORY_ACCESS
        WHERE ACCESS_TIME < SYSTIMESTAMP - INTERVAL '180' DAY
          AND ACCESS_ID NOT IN (
              SELECT MAX(ACCESS_ID) 
              FROM AGENT_MEMORY_ACCESS 
              WHERE ACCESS_TIME < SYSTIMESTAMP - INTERVAL '180' DAY
              GROUP BY AGENT_ID
          );
        
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('Full cleanup cycle completed');
    END run_full_cleanup_cycle;
    
    -- Get cleanup statistics
    FUNCTION get_cleanup_stats RETURN VARCHAR2 IS
        v_snapshot_count NUMBER;
        v_archive_count  NUMBER;
        v_session_count  NUMBER;
        v_tool_call_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_snapshot_count FROM TASK_CONTEXT_SNAPSHOTS;
        SELECT COUNT(*) INTO v_archive_count FROM TASK_CONTEXT_SNAPSHOTS_ARCHIVE;
        SELECT COUNT(*) INTO v_session_count FROM AGENT_SESSION WHERE IS_ACTIVE = 'Y';
        SELECT COUNT(*) INTO v_tool_call_count FROM TASK_TOOL_CALLS;
        
        RETURN 'Snapshots: ' || v_snapshot_count || ', Archived: ' || v_archive_count || 
               ', Active Sessions: ' || v_session_count || ', Tool Calls: ' || v_tool_call_count;
    END get_cleanup_stats;

END snapshot_cleanup_manager;
/

-- ============================================================================
-- SECTION 3: CREATE SCHEDULER JOBS FOR AUTOMATED CLEANUP
-- ============================================================================

-- Daily cleanup job (runs at 2 AM)
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'SNAPSHOT_CLEANUP_DAILY',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN snapshot_cleanup_manager.cleanup_expired_snapshots(TRUE); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Daily snapshot cleanup and archival'
    );
END;
/

-- Weekly full cleanup (runs Sunday at 3 AM)
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'SNAPSHOT_CLEANUP_WEEKLY',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN snapshot_cleanup_manager.run_full_cleanup_cycle; END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Weekly comprehensive cleanup cycle'
    );
END;
/

-- Monthly archive report (runs on 1st of month at 4 AM)
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'SNAPSHOT_ARCHIVE_REPORT',
        job_type => 'PLSQL_BLOCK',
        job_action => 'DBMS_OUTPUT.PUT_LINE(snapshot_cleanup_manager.get_cleanup_stats); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MONTHLY; BY1=DOM; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Monthly archive statistics report'
    );
END;
/

-- ============================================================================
-- SECTION 4: VALIDATION QUERIES
-- ============================================================================

-- Verify cleanup configuration
SELECT CONFIG_KEY, CONFIG_VALUE FROM cleanup_config ORDER BY CONFIG_KEY;

-- Check scheduler jobs status
SELECT JOB_NAME, STATE, REPEAT_INTERVAL 
FROM DBA_SCHEDULER_JOBS 
WHERE JOB_NAME LIKE 'SNAPSHOT_CLEANUP%' OR JOB_NAME LIKE 'SNAPSHOT_ARCHIVE%';
