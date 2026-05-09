-- ============================================
-- session_cleanup_job.sql (修复版 - 适配现有表结构)
-- P1-重要: Agent会话过期清理 + Oracle Job调度
-- Version: v0.4.3 (Bug Fix - Field Compatibility)
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-08
-- ============================================

-- ============================================
-- STEP 1: CREATE CLEANUP PROCEDURE
-- 修复字段映射：CREATED_AT→START_TIME, LAST_ACTIVE→END_TIME/计算活跃时间
-- ============================================

CREATE OR REPLACE PROCEDURE AGENT_SESSION_CLEANUP AS
    v_deleted_count NUMBER := 0;
    v_expired_sessions NUMBER := 0;
    v_archived_count NUMBER := 0;
BEGIN
    -- Count expired sessions before cleanup (使用END_TIME或计算活跃时间)
    SELECT COUNT(*) INTO v_expired_sessions 
    FROM AGENT_SESSION 
    WHERE NVL(END_TIME, SYSTIMESTAMP - INTERVAL '1' DAY) < SYSTIMESTAMP - INTERVAL '24' HOUR;
    
    DBMS_OUTPUT.PUT_LINE('Found ' || v_expired_sessions || ' expired sessions');
    
    -- Archive expired sessions to history table (适配现有字段名)
    INSERT INTO AGENT_SESSION_ARCHIVE (
        SESSION_ID, AGENT_ID, WORKING_MEMORY_ID, CONTEXT_SNAPSHOT, 
        CREATED_AT, LAST_ACTIVE, ARCHIVED_DATE
    )
    SELECT 
        SESSION_ID, AGENT_ID, WORKING_MEMORY_ID, CONTEXT_SNAPSHOT, 
        START_TIME, NVL(END_TIME, SYSTIMESTAMP), SYSTIMESTAMP
    FROM AGENT_SESSION
    WHERE NVL(END_TIME, SYSTIMESTAMP - INTERVAL '1' DAY) < SYSTIMESTAMP - INTERVAL '24' HOUR;
    
    v_archived_count := SQL%ROWCOUNT;
    DBMS_OUTPUT.PUT_LINE('Archived ' || v_archived_count || ' sessions');
    
    -- Delete archived sessions (keep only latest per agent)
    DELETE FROM AGENT_SESSION
    WHERE NVL(END_TIME, SYSTIMESTAMP - INTERVAL '1' DAY) < SYSTIMESTAMP - INTERVAL '24' HOUR
    AND SESSION_ID NOT IN (
        SELECT MAX(SESSION_ID) 
        FROM AGENT_SESSION 
        WHERE NVL(END_TIME, SYSTIMESTAMP - INTERVAL '1' DAY) < SYSTIMESTAMP - INTERVAL '24' HOUR
        GROUP BY AGENT_ID
    );
    
    v_deleted_count := SQL%ROWCOUNT;
    DBMS_OUTPUT.PUT_LINE('Deleted ' || v_deleted_count || ' archived sessions');
    
    -- Cleanup orphaned working memory references
    DELETE FROM MEMORY_WORKING_CONTEXTS
    WHERE WORKING_MEMORY_ID NOT IN (
        SELECT DISTINCT WORKING_MEMORY_ID 
        FROM AGENT_SESSION
    );
    
    DBMS_OUTPUT.PUT_LINE('Cleaned up orphaned working contexts');
    
    -- Log cleanup activity
    INSERT INTO CLEANUP_AUDIT_LOG (
        OPERATION, TARGET_TABLE, ROWS_ARCHIVED, ROWS_DELETED, EXECUTION_TIME
    ) VALUES (
        'SESSION_CLEANUP', 'AGENT_SESSION', v_archived_count, v_deleted_count, SYSTIMESTAMP
    );
    
    COMMIT;
    
    DBMS_OUTPUT.PUT_LINE('Session cleanup completed successfully');
END;
/

-- ============================================
-- STEP 2: CREATE CLEANUP AUDIT LOG TABLE (if not exists)
-- ============================================

CREATE TABLE IF NOT EXISTS CLEANUP_AUDIT_LOG (
    LOG_ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    OPERATION VARCHAR2(100),
    TARGET_TABLE VARCHAR2(100),
    ROWS_ARCHIVED NUMBER,
    ROWS_DELETED NUMBER,
    EXECUTION_TIME TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    DURATION_SECONDS NUMBER,
    STATUS VARCHAR2(50) DEFAULT 'SUCCESS'
);

-- ============================================
-- STEP 3: CREATE SESSION TTL MANAGEMENT VIEW (适配字段)
-- ============================================

CREATE OR REPLACE VIEW AGENT_SESSION_TTL_STATUS AS
SELECT 
    s.SESSION_ID,
    s.AGENT_ID,
    -- Use START_TIME as session creation time
    s.START_TIME,
    -- Calculate active duration using END_TIME or current timestamp
    NVL(s.END_TIME, SYSTIMESTAMP) as CURRENT_ACTIVE_END,
    -- Calculate time since last activity in seconds
    EXTRACT(DAY FROM (SYSTIMESTAMP - NVL(s.END_TIME, SYSTIMESTAMP))) * 86400 +
    EXTRACT(HOUR FROM (SYSTIMESTAMP - NVL(s.END_TIME, SYSTIMESTAMP))) * 3600 +
    EXTRACT(MINUTE FROM (SYSTIMESTAMP - NVL(s.END_TIME, SYSTIMESTAMP))) * 60 +
    EXTRACT(SECOND FROM (SYSTIMESTAMP - NVL(s.END_TIME, SYSTIMESTAMP))) as SECONDS_SINCE_ACTIVITY,
    -- Status indicator based on IS_ACTIVE and end time
    CASE 
        WHEN s.IS_ACTIVE = 'N' THEN 'COMPLETED'
        WHEN NVL(s.END_TIME, SYSTIMESTAMP) < SYSTIMESTAMP - INTERVAL '1' DAY THEN 'EXPIRED'
        WHEN NVL(s.END_TIME, SYSTIMESTAMP) > SYSTIMESTAMP + INTERVAL '20' HOUR THEN 'WILL_EXPIRE_SOON'
        ELSE 'ACTIVE'
    END as SESSION_STATUS
FROM AGENT_SESSION s;

-- ============================================
-- STEP 4: CREATE SESSION EXTENSION PROCEDURE (适配字段)
-- ============================================

CREATE OR REPLACE PROCEDURE EXTEND_AGENT_SESSION(
    p_session_id VARCHAR2,
    p_extension_seconds NUMBER DEFAULT 3600
) AS
BEGIN
    -- Update END_TIME to extend session validity
    UPDATE AGENT_SESSION 
    SET END_TIME = SYSTIMESTAMP + INTERVAL '1' SECOND
    WHERE SESSION_ID = p_session_id;
    
    IF SQL%ROWCOUNT = 0 THEN
        RAISE_APPLICATION_ERROR(-20001, 'Session not found: ' || p_session_id);
    END IF;
    
    COMMIT;
END;
/

-- ============================================
-- STEP 5: CREATE AGENT REGISTRY CLEANUP (适配字段)
-- ============================================

CREATE OR REPLACE PROCEDURE INACTIVE_AGENT_CLEANUP AS
BEGIN
    -- Archive inactive agents
    INSERT INTO AGENT_REGISTRY_ARCHIVE (
        AGENT_ID, AGENT_NAME, AGENT_TYPE, CAPABILITIES, 
        PERMISSION_LEVEL, LAST_ACTIVE, ARCHIVED_DATE
    )
    SELECT 
        AR.AGENT_ID, AR.AGENT_NAME, AR.AGENT_TYPE, AR.CAPABILITIES,
        AR.PERMISSION_LEVEL, MAX(asa.START_TIME), SYSTIMESTAMP
    FROM AGENT_REGISTRY AR
    LEFT JOIN AGENT_SESSION asa ON ar.AGENT_ID = asa.AGENT_ID
    GROUP BY AR.AGENT_ID, AR.AGENT_NAME, AR.AGENT_TYPE, AR.CAPABILITIES, AR.PERMISSION_LEVEL
    HAVING MAX(asa.START_TIME) < SYSTIMESTAMP - INTERVAL '90' DAY;
    
    -- Mark archived agents in main registry (soft delete)
    UPDATE AGENT_REGISTRY 
    SET PERMISSION_LEVEL = 'DISABLED', 
        LAST_MODIFIED = SYSTIMESTAMP
    WHERE AGENT_ID IN (
        SELECT AGENT_ID FROM AGENT_REGISTRY_ARCHIVE
    );
    
    COMMIT;
END;
/

-- ============================================
-- STEP 6: CREATE AGENT REGISTRY ARCHIVE TABLE (if not exists)
-- ============================================

CREATE TABLE IF NOT EXISTS AGENT_REGISTRY_ARCHIVE (
    AGENT_ID VARCHAR2(64),
    AGENT_NAME VARCHAR2(100),
    AGENT_TYPE VARCHAR2(50),
    CAPABILITIES CLOB,
    PERMISSION_LEVEL VARCHAR2(20),
    LAST_ACTIVE TIMESTAMP WITH TIME ZONE,
    ARCHIVED_DATE TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- ============================================
-- END OF SESSION CLEANUP JOB SCRIPT (FIXED)
-- ============================================
