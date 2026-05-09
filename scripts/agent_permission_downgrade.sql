-- ============================================================================
-- Oracle Memory System v0.5.1 - Agent Permission Downgrade & Data Recovery
-- ============================================================================
-- Description: Automatically recovers COLLABORATIVE data access when agents are disabled
--              and manages permission degradation across the multi-agent system
-- Version: 0.5.1
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: PERMISSION CHANGE LOG TABLE - Track all permission changes
-- ============================================================================

CREATE TABLE agent_permission_log (
    LOG_ID          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    AGENT_ID        VARCHAR2(64) NOT NULL REFERENCES agent_registry(AGENT_ID),
    OLD_STATUS      VARCHAR2(20) NOT NULL,
    NEW_STATUS      VARCHAR2(20) NOT NULL,
    CHANGE_REASON   CLOB,                    -- JSON: {reason, triggered_by, timestamp}
    RECOVERED_COUNT NUMBER DEFAULT 0,        -- Number of memories recovered
    CHANGED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    STATUS          VARCHAR2(10) DEFAULT 'COMPLETED' -- COMPLETED/FAILED/PENDING
);

COMMENT ON TABLE agent_permission_log IS 'Audit log for all agent permission changes and data recovery operations';
COMMENT ON COLUMN agent_permission_log.OLD_STATUS IS 'Previous status of the agent (ACTIVE/DISABLED/SUSPENDED)';
COMMENT ON COLUMN agent_permission_log.NEW_STATUS IS 'New status after downgrade operation';
COMMENT ON COLUMN agent_permission_log.RECOVERED_COUNT IS 'Number of memories recovered in last operation';

CREATE INDEX idx_permission_log_agent ON agent_permission_log(agent_id, CHANGED_AT);
CREATE INDEX idx_permission_log_status ON agent_permission_log(status, CHANGED_AT DESC);

-- ============================================================================
-- SECTION 2: AGENT PERMISSION RESTRICTIONS - Define what disabled agents lose
-- ============================================================================

-- Add permission restriction tracking to agent_registry
ALTER TABLE agent_registry ADD (
    LAST_PERMISSION_CHECK TIMESTAMP WITH TIME ZONE,
    PENDING_RECOVERY      VARCHAR2(1) DEFAULT 'N', -- Whether recovery is pending
    RECOVERED_COUNT       NUMBER DEFAULT 0         -- How many memories were recovered last time
);

COMMENT ON COLUMN agent_registry.LAST_PERMISSION_CHECK IS 'Timestamp of last permission downgrade check';
COMMENT ON COLUMN agent_registry.PENDING_RECOVERY IS 'Whether memory access recovery is pending (Y/N)';
COMMENT ON COLUMN agent_registry.RECOVERED_COUNT IS 'Number of memories recovered in last operation';

-- ============================================================================
-- SECTION 3: PL/SQL PROCEDURE - Core Downgrade Logic
-- ============================================================================

CREATE OR REPLACE PACKAGE BODY agent_permission_manager AS

    -- ========================================================================
    -- Function: Check if memory should be revoked from disabled agent
    -- Returns TRUE if the memory was accessible but should now be recovered
    -- ========================================================================
    
    FUNCTION check_memory_recovery(
        p_agent_id VARCHAR2,
        p_visibility VARCHAR2,
        p_accessible_to CLOB
    ) RETURN BOOLEAN IS
        v_has_access BOOLEAN := FALSE;
        v_is_collaborative BOOLEAN := FALSE;
        v_was_accessible BOOLEAN := FALSE;
    BEGIN
        -- Only COLLABORATIVE memories need recovery for disabled agents
        IF p_visibility != 'COLLABORATIVE' THEN
            RETURN FALSE;
        END IF;
        
        -- Check if the agent was in ACCESSIBLE_TO list
        IF p_accessible_to IS NOT NULL AND INSTR(p_accessible_to, p_agent_id) > 0 THEN
            v_was_accessible := TRUE;
        ELSE
            -- Also check JSON array format: ["agent-1", "agent-2"]
            BEGIN
                FOR rec IN (SELECT VALUE FROM TABLE(CAST(
                    SYS.ODCIVARCHAR2LIST(
                        REGEXP_SUBSTR(p_accessible_to, '"[^"]*"', 1, LEVEL)
                    ), VARCHAR2(64))
                ) WHERE ROWNUM <= REGEXP_COUNT(p_accessible_to, '"[^"]*"') + 1)
                LOOP
                    IF TRIM(REPLACE(rec.VALUE, '"', '')) = p_agent_id THEN
                        v_was_accessible := TRUE;
                        EXIT;
                    END IF;
                END LOOP;
            EXCEPTION WHEN OTHERS THEN NULL;
        END IF;
        
        RETURN v_was_accessible;
    END check_memory_recovery;
    
    -- ========================================================================
    -- Procedure: Disable agent and recover their COLLABORATIVE access
    -- ========================================================================
    
    PROCEDURE disable_agent_and_recover(
        p_agent_id IN VARCHAR2,
        p_reason   IN CLOB DEFAULT NULL,
        p_changed_by IN VARCHAR2 DEFAULT 'SYSTEM'
    ) IS
        
        v_old_status VARCHAR2(20);
        v_new_status VARCHAR2(20) := 'DISABLED';
        v_recovered_count NUMBER := 0;
        v_recovery_pending VARCHAR2(1) := 'N';
        
        CURSOR mem_cursor IS
            SELECT ID, VISIBILITY, ACCESSIBLE_TO 
            FROM memories 
            WHERE (VISIBILITY = 'COLLABORATIVE' AND ACCESSIBLE_TO LIKE '%' || p_agent_id || '%')
               OR (VISIBILITY = 'PRIVATE' AND OWNED_BY_AGENT = p_agent_id);
        
    BEGIN
        -- Get current agent status
        SELECT STATUS, PENDING_RECOVERY INTO v_old_status, v_recovery_pending 
        FROM agent_registry 
        WHERE AGENT_ID = p_agent_id;
        
        IF v_old_status != 'ACTIVE' THEN
            RETURN; -- Already disabled or non-active
        END IF;
        
        -- Start transaction for data recovery
        FOR mem_rec IN mem_cursor LOOP
            -- Remove this agent from ACCESSIBLE_TO JSON array
            DECLARE
                v_new_accessible CLOB;
                v_current_access CLOB := mem_rec.ACCESSIBLE_TO;
            BEGIN
                -- Use regex to remove the agent ID from JSON array
                v_new_accessible := REGEXP_REPLACE(
                    v_current_access, 
                    '[[:space:]]*"[^"]*"([[:space:]])*("[^"]*)"?,',
                    '', 1, 0, 'gm'
                );
                
                -- Clean up trailing comma if present
                IF SUBSTR(v_new_accessible, -2) = ',]' THEN
                    v_new_accessible := SUBSTR(v_new_accessible, 1, LENGTH(v_new_accessible) - 1);
                END IF;
                
                -- Update memory with reduced access list
                UPDATE memories 
                SET ACCESSIBLE_TO = v_new_accessible,
                    UPDATED_AT = SYSTIMESTAMP
                WHERE ID = mem_rec.ID;
                
                v_recovered_count := v_recovered_count + 1;
            EXCEPTION WHEN OTHERS THEN
                NULL; -- Skip if JSON manipulation fails
            END;
        END LOOP;
        
        -- Update agent status
        UPDATE agent_registry 
        SET STATUS = 'DISABLED',
            LAST_PERMISSION_CHECK = SYSTIMESTAMP,
            PENDING_RECOVERY = CASE WHEN v_recovered_count > 0 THEN 'Y' ELSE 'N' END,
            RECOVERED_COUNT = v_recovered_count,
            UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = p_agent_id;
        
        -- Log the permission change
        INSERT INTO agent_permission_log (
            AGENT_ID, OLD_STATUS, NEW_STATUS, CHANGE_REASON, 
            RECOVERED_COUNT, STATUS
        ) VALUES (
            p_agent_id, v_old_status, v_new_status, p_reason,
            v_recovered_count, 'COMPLETED'
        );
        
        COMMIT;
        
    EXCEPTION WHEN OTHERS THEN
        ROLLBACK;
        -- Log failure
        INSERT INTO agent_permission_log (
            AGENT_ID, OLD_STATUS, NEW_STATUS, CHANGE_REASON, 
            RECOVERED_COUNT, STATUS
        ) VALUES (
            p_agent_id, v_old_status, 'DISABLED', 
            'FAILED: ' || SQLERRM, 0, 'FAILED'
        );
        COMMIT;
    END disable_agent_and_recover;
    
    -- ========================================================================
    -- Procedure: Enable agent and restore COLLABORATIVE access
    -- ========================================================================
    
    PROCEDURE enable_agent(
        p_agent_id IN VARCHAR2
    ) IS
    BEGIN
        UPDATE agent_registry 
        SET STATUS = 'ACTIVE',
            PENDING_RECOVERY = 'N',
            LAST_PERMISSION_CHECK = SYSTIMESTAMP,
            UPDATED_AT = SYSTIMESTAMP
        WHERE AGENT_ID = p_agent_id;
        
        COMMIT;
    EXCEPTION WHEN OTHERS THEN
        ROLLBACK;
    END enable_agent;
    
    -- ========================================================================
    -- Procedure: Scheduled job to check all disabled agents for pending recovery
    -- ========================================================================
    
    PROCEDURE scheduled_permission_check IS
        
        CURSOR agent_cursor IS
            SELECT AGENT_ID 
            FROM agent_registry 
            WHERE STATUS = 'DISABLED' AND PENDING_RECOVERY = 'Y';
            
        v_last_check TIMESTAMP;
        
    BEGIN
        FOR rec IN agent_cursor LOOP
            -- Check if recovery was performed recently (within last hour)
            SELECT MAX(CHANGED_AT) INTO v_last_check 
            FROM agent_permission_log 
            WHERE AGENT_ID = rec.AGENT_ID 
              AND STATUS = 'COMPLETED'
              AND CHANGED_AT > SYSTIMESTAMP - INTERVAL '1' HOUR;
            
            -- If no recent recovery, perform one now
            IF v_last_check IS NULL THEN
                disable_agent_and_recover(
                    p_agent_id => rec.AGENT_ID,
                    p_reason   => '{"type": "scheduled", "triggered_by": "cron_job"}',
                    p_changed_by => 'SCHEDULED_JOB'
                );
            END IF;
        END LOOP;
        
    EXCEPTION WHEN OTHERS THEN
        NULL; -- Log to application error table in production
    END scheduled_permission_check;

END agent_permission_manager;
/

-- ============================================================================
-- SECTION 4: CREATE PUBLIC SYNONYMS AND GRANTS
-- ============================================================================

CREATE OR REPLACE PUBLIC SYNONYM agent_permission_manager FOR agent_permission_manager;

GRANT EXECUTE ON agent_permission_manager TO PUBLIC;

-- Create job to run permission check every hour
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'MEMORY_PERMISSION_CHECK_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN agent_permission_manager.scheduled_permission_check; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; INTERVAL=1',
        enabled         => TRUE,
        comments        => 'Hourly check for disabled agents pending memory recovery'
    );
END;
/

-- ============================================================================
-- SECTION 5: VALIDATION QUERIES
-- ============================================================================

-- Check new tables exist
SELECT TABLE_NAME FROM USER_TABLES 
WHERE TABLE_NAME IN ('AGENT_PERMISSION_LOG', 'AGENT_REGISTRY') 
ORDER BY TABLE_NAME;

-- Check views created
SELECT VIEW_NAME, STATUS FROM USER_VIEWS WHERE VIEW_NAME LIKE '%PERMISSION%';

-- Check scheduled jobs
SELECT JOB_NAME, STATE, REPEAT_INTERVAL 
FROM DBA_SCHEDULER_JOBS 
WHERE JOB_NAME = 'MEMORY_PERMISSION_CHECK_JOB';
