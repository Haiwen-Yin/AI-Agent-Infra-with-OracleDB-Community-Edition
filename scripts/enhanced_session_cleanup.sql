-- ============================================================================
-- Oracle Memory System v0.5.1 - Enhanced Session Expiry Cleanup with Job Scheduling
-- ============================================================================
-- Description: Enhanced session management with intelligent expiry detection,
--              automatic cleanup jobs, and configurable TTL policies
-- Version: 0.5.1-SESSION-ENHANCED
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: SESSION CONFIGURATION TABLE - TTL policies and thresholds
-- ============================================================================

CREATE TABLE session_config (
    CONFIG_KEY      VARCHAR2(100) PRIMARY KEY,
    CONFIG_VALUE    CLOB,                    -- JSON: {ttl_hours, warning_threshold}
    DESCRIPTION     VARCHAR2(500),
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Insert session configuration defaults
INSERT ALL
INTO session_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SESSION_TTL_HOURS', '24', 'Default session TTL in hours')
INTO session_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SESSION_WARNING_THRESHOLD', '18', 'Warning threshold before expiry (hours)')
INTO session_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SESSION_GRACE_PERIOD_MINUTES', '30', 'Grace period after TTL expiry (minutes)')
INTO session_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SESSION_CLEANUP_BATCH_SIZE', '500', 'Cleanup batch size per iteration')
SELECT * FROM DUAL;

-- ============================================================================
-- SECTION 2: SESSION ACTIVITY TRACKING - Track last activity timestamps
-- ============================================================================

ALTER TABLE agent_session ADD (
    LAST_ACTIVITY   TIMESTAMP WITH TIME ZONE,  -- Track actual last use
    SESSION_TYPE    VARCHAR2(30) DEFAULT 'INTERACTIVE',  -- INTERACTIVE/BATCH/BACKGROUND
    MAX_IDLE_TIME   INTERVAL DAY TO SECOND     -- Configurable idle timeout
);

COMMENT ON COLUMN agent_session.LAST_ACTIVITY IS 'Timestamp of last user activity';
COMMENT ON COLUMN agent_session.SESSION_TYPE IS 'Session classification: INTERACTIVE, BATCH, or BACKGROUND';
COMMENT ON COLUMN agent_session.MAX_IDLE_TIME IS 'Maximum allowed idle time before auto-expiry';

CREATE INDEX idx_session_last_activity ON agent_session(LAST_ACTIVITY);
CREATE INDEX idx_session_type ON agent_session(SESSION_TYPE);

-- ============================================================================
-- SECTION 3: PL/SQL PACKAGE - Session Management Logic
-- ============================================================================

CREATE OR REPLACE PACKAGE session_manager AS
    
    -- Update last activity timestamp (call on each user interaction)
    PROCEDURE update_activity(p_session_id VARCHAR2);
    
    -- Check and cleanup expired sessions
    PROCEDURE cleanup_expired_sessions;
    
    -- Gracefully extend session if needed
    FUNCTION should_extend_session(p_session_id VARCHAR2) RETURN BOOLEAN;
    
    -- Get active session warnings (approaching TTL expiry)
    FUNCTION get_expiring_sessions RETURN CLOB;
    
    END session_manager;
/

CREATE OR REPLACE PACKAGE BODY session_manager AS
    
    v_ttl_hours NUMBER := 24;
    v_warning_threshold NUMBER := 18;
    v_grace_minutes NUMBER := 30;
    
    -- Helper function to read configuration value
    FUNCTION get_session_config(p_key VARCHAR2) RETURN NUMBER IS
        v_value CLOB;
    BEGIN
        SELECT CONFIG_VALUE INTO v_value FROM session_config WHERE CONFIG_KEY = p_key;
        RETURN TO_NUMBER(v_value);
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END get_session_config;
    
    -- Update last activity timestamp (call on each user interaction)
    PROCEDURE update_activity(p_session_id VARCHAR2) IS
    BEGIN
        UPDATE agent_session 
        SET LAST_ACTIVITY = SYSTIMESTAMP,
            IS_ACTIVE = 'Y'  -- Reactivate if was inactive
        WHERE SESSION_ID = p_session_id;
        
        COMMIT;
    EXCEPTION WHEN OTHERS THEN
        NULL;
    END update_activity;
    
    -- Check and cleanup expired sessions
    PROCEDURE cleanup_expired_sessions IS
        v_ttl_hours NUMBER := 24;
        v_grace_minutes NUMBER := 30;
        v_deleted_count NUMBER := 0;
        
        CURSOR session_cursor IS
            SELECT SESSION_ID, AGENT_ID, START_TIME, CONTEXT_SNAPSHOT, 
                   WORKING_MEMORY_ID
            FROM agent_session
            WHERE (IS_ACTIVE = 'Y' OR END_TIME IS NULL)
              AND LAST_ACTIVITY < SYSTIMESTAMP - INTERVAL ':ttl_hours' HOUR + 
                                        INTERVAL ':grace_minutes' MINUTE;
        
    BEGIN
        v_ttl_hours := get_session_config('SESSION_TTL_HOURS');
        v_grace_minutes := get_session_config('SESSION_GRACE_PERIOD_MINUTES');
        
        -- Archive expired sessions before deletion
        INSERT INTO AGENT_SESSION_ARCHIVE (
            SESSION_ID, AGENT_ID, CONTEXT_SNAPSHOT, WORKING_MEMORY_ID, 
            CREATED_AT, LAST_ACTIVE, ARCHIVED_DATE
        )
        SELECT SESSION_ID, AGENT_ID, CONTEXT_SNAPSHOT, WORKING_MEMORY_ID,
               START_TIME, LAST_ACTIVITY, SYSTIMESTAMP
        FROM agent_session
        WHERE (IS_ACTIVE = 'Y' OR END_TIME IS NULL)
          AND LAST_ACTIVITY < SYSTIMESTAMP - INTERVAL ':ttl_hours' HOUR + 
                                    INTERVAL ':grace_minutes' MINUTE;
        
        v_deleted_count := SQL%ROWCOUNT;
        
        -- Update or delete expired sessions
        UPDATE agent_session 
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP, SESSION_TYPE = 'EXPIRED'
        WHERE (IS_ACTIVE = 'Y' OR END_TIME IS NULL)
          AND LAST_ACTIVITY < SYSTIMESTAMP - INTERVAL ':ttl_hours' HOUR + 
                                    INTERVAL ':grace_minutes' MINUTE;
        
        -- Hard delete sessions older than 7 days from archive
        DELETE FROM AGENT_SESSION_ARCHIVE
        WHERE ARCHIVED_DATE < SYSDATE - 7;
        
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('Session cleanup: Archived and expired ' || v_deleted_count || ' sessions');
    END cleanup_expired_sessions;
    
    -- Check if session should be extended (based on activity patterns)
    FUNCTION should_extend_session(p_session_id VARCHAR2) RETURN BOOLEAN IS
        v_last_activity TIMESTAMP;
        v_ttl_hours NUMBER := 24;
    BEGIN
        SELECT LAST_ACTIVITY INTO v_last_activity 
        FROM agent_session 
        WHERE SESSION_ID = p_session_id AND IS_ACTIVE = 'Y';
        
        -- Extend if session is within warning threshold and recently active
        RETURN (SYSTIMESTAMP - v_last_activity) < INTERVAL ':warning_threshold' HOUR;
    END should_extend_session;
    
    -- Get warnings for sessions approaching TTL expiry
    FUNCTION get_expiring_sessions RETURN CLOB IS
        CURSOR expiring_cursor IS
            SELECT SESSION_ID, AGENT_ID, LAST_ACTIVITY, 
                   ROUND((SYSTIMESTAMP - LAST_ACTIVITY) * 24) as HOURS_ELAPSED
            FROM agent_session
            WHERE IS_ACTIVE = 'Y'
              AND LAST_ACTIVITY > SYSTIMESTAMP - INTERVAL ':ttl_hours' HOUR
              AND LAST_ACTIVITY < SYSTIMESTAMP - INTERVAL ':warning_threshold' HOUR;
        
        v_result CLOB := '{"expiring_sessions": [';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN expiring_cursor LOOP
            IF NOT v_first THEN
                v_result := v_result || ',';
            END IF;
            
            v_result := v_result || '{"session_id":"' || rec.SESSION_ID || 
                       '","agent_id":"' || rec.AGENT_ID || 
                       '","hours_elapsed":' || rec.HOURS_ELAPSED || '}';
            v_first := FALSE;
        END LOOP;
        
        v_result := v_result || ']}';
        RETURN v_result;
    END get_expiring_sessions;

END session_manager;
/

-- ============================================================================
-- SECTION 4: CREATE SCHEDULER JOBS FOR SESSION MANAGEMENT
-- ============================================================================

-- Session cleanup job - runs every 30 minutes
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'SESSION_CLEANUP_JOB',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN session_manager.cleanup_expired_sessions; END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=30',
        enabled => TRUE,
        comments => 'Session cleanup every 30 minutes'
    );
END;
/

-- Session expiry notification - runs daily at 9 AM
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'SESSION_EXPIRY_NOTIFICATION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'DBMS_OUTPUT.PUT_LINE(session_manager.get_expiring_sessions); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=9; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Daily session expiry notification'
    );
END;
/

-- ============================================================================
-- SECTION 5: HELPER VIEW - Identify sessions needing attention
-- ============================================================================

CREATE OR REPLACE VIEW v_sessions_needing_attention AS
SELECT 
    a.SESSION_ID,
    a.AGENT_ID,
    a.LAST_ACTIVITY,
    ROUND((SYSTIMESTAMP - a.LAST_ACTIVITY) * 24, 1) as HOURS_IDLE,
    CASE 
        WHEN (SYSTIMESTAMP - a.LAST_ACTIVITY) > INTERVAL '20' HOUR THEN 'CRITICAL'
        WHEN (SYSTIMESTAMP - a.LAST_ACTIVITY) > INTERVAL '18' HOUR THEN 'WARNING'
        ELSE 'OK'
    END as STATUS,
    s.AGENT_NAME
FROM agent_session a
LEFT JOIN agent_registry s ON a.AGENT_ID = s.AGENT_ID
WHERE a.IS_ACTIVE = 'Y'
  AND (SYSTIMESTAMP - a.LAST_ACTIVITY) > INTERVAL '18' HOUR;

-- ============================================================================
-- SECTION 6: VALIDATION QUERIES
-- ============================================================================

-- Verify session configuration
SELECT CONFIG_KEY, CONFIG_VALUE FROM session_config ORDER BY CONFIG_KEY;

-- Check active sessions needing attention
SELECT * FROM v_sessions_needing_attention ORDER BY HOURS_IDLE DESC;

-- Check scheduler jobs status
SELECT JOB_NAME, STATE, REPEAT_INTERVAL 
FROM DBA_SCHEDULER_JOBS 
WHERE JOB_NAME LIKE 'SESSION_%';
