-- ============================================================================
-- Oracle Memory System v1.0.0 - Knowledge Base Scheduled Jobs
-- ============================================================================
-- Description: Scheduled jobs for knowledge base operations
-- Version: 1.0.0-KB-JOBS
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: Job for automatic pattern detection
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_PATTERN_DETECTION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN detect_memory_patterns(NULL, 3); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Daily pattern detection for memory distillation - identifies repeated memory patterns'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_PATTERN_DETECTION');
END;
/

-- ============================================================================
-- SECTION 2: Job for experience extraction
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_EXPERIENCE_EXTRACTION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN extract_experience(NULL, 60); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Weekly experience extraction from mature memories (older than 60 days)'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_EXPERIENCE_EXTRACTION');
END;
/

-- ============================================================================
-- SECTION 3: Job for knowledge graph maintenance
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_GRAPH_MAINTENANCE',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN knowledge_base_api.cleanup_deprecated(90); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MONTHLY; BYMONTHDAY=1; BYHOUR=5; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Monthly cleanup of deprecated knowledge older than 90 days'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_GRAPH_MAINTENANCE');
END;
/

-- ============================================================================
-- SECTION 4: Job for knowledge statistics collection
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_STATS_COLLECTION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'DECLARE v_stats CLOB; BEGIN v_stats := knowledge_base_api.get_kb_statistics; DBMS_OUTPUT.PUT_LINE(v_stats); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=6; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Daily knowledge base statistics collection'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_STATS_COLLECTION');
END;
/

-- ============================================================================
-- SECTION 5: Job for search analytics
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_SEARCH_ANALYTICS',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN 
            -- Clean up old search history (older than 90 days)
            DELETE FROM KNOWLEDGE_SEARCH_HISTORY 
            WHERE SEARCHED_AT < SYSTIMESTAMP - 90;
            COMMIT;
            DBMS_OUTPUT.PUT_LINE(''Cleaned up old search history'');
        END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SAT; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Weekly cleanup of old search history'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_SEARCH_ANALYTICS');
END;
/

-- ============================================================================
-- SECTION 6: Job for knowledge health monitoring
-- ============================================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_HEALTH_MONITOR',
        job_type => 'PLSQL_BLOCK',
        job_action => 'DECLARE 
            v_total_concepts NUMBER;
            v_pending_count NUMBER;
            v_isolated_count NUMBER;
        BEGIN 
            SELECT COUNT(*) INTO v_total_concepts FROM KNOWLEDGE_CONCEPTS;
            SELECT COUNT(*) INTO v_pending_count FROM KNOWLEDGE_CONCEPTS WHERE VALIDATION_STATUS = ''PENDING'';
            
            SELECT COUNT(*) INTO v_isolated_count
            FROM KNOWLEDGE_CONCEPTS kc
            WHERE NOT EXISTS (
                SELECT 1 FROM KNOWLEDGE_GRAPH kg
                WHERE kg.SOURCE_CONCEPT_ID = kc.CONCEPT_ID
                   OR kg.TARGET_CONCEPT_ID = kc.CONCEPT_ID
            );
            
            DBMS_OUTPUT.PUT_LINE(''Knowledge Health Report:'');
            DBMS_OUTPUT.PUT_LINE(''  Total concepts: '' || v_total_concepts);
            DBMS_OUTPUT.PUT_LINE(''  Pending validation: '' || v_pending_count);
            DBMS_OUTPUT.PUT_LINE(''  Isolated concepts: '' || v_isolated_count);
            
            -- Alert if too many pending validations
            IF v_pending_count > v_total_concepts * 0.3 THEN
                DBMS_OUTPUT.PUT_LINE(''WARNING: High number of pending validations!'');
            END IF;
        END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=MON; BYHOUR=7; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Weekly knowledge base health monitoring and reporting'
    );
    DBMS_OUTPUT.PUT_LINE('Created job: KNOWLEDGE_HEALTH_MONITOR');
END;
/

-- ============================================================================
-- SECTION 7: Verify all jobs are created
-- ============================================================================

SELECT 
    JOB_NAME,
    STATE,
    NEXT_RUN_DATE,
    REPEAT_INTERVAL,
    COMMENTS
FROM DBA_SCHEDULER_JOBS
WHERE JOB_NAME LIKE 'KNOWLEDGE_%'
ORDER BY JOB_NAME;

-- ============================================================================
-- SECTION 8: Job management procedures
-- ============================================================================

-- Enable/Disable job example
/*
BEGIN
    DBMS_SCHEDULER.ENABLE('KNOWLEDGE_PATTERN_DETECTION');
    -- or
    DBMS_SCHEDULER.DISABLE('KNOWLEDGE_PATTERN_DETECTION');
END;
*/

-- Run job immediately
/*
BEGIN
    DBMS_SCHEDULER.RUN_JOB('KNOWLEDGE_PATTERN_DETECTION');
END;
*/

-- Check job run history
/*
SELECT 
    JOB_NAME,
    STATUS,
    RUN_DURATION,
    ACTUAL_START_DATE
FROM DBA_SCHEDULER_JOB_RUN_DETAILS
WHERE JOB_NAME LIKE 'KNOWLEDGE_%'
ORDER BY ACTUAL_START_DATE DESC
FETCH FIRST 10 ROWS ONLY;
*/

-- ============================================================================
-- SECTION 9: Helper procedures for job execution
-- ============================================================================

CREATE OR REPLACE PROCEDURE detect_memory_patterns(
    p_category VARCHAR2 DEFAULT NULL,
    p_min_occurrences NUMBER DEFAULT 3
) AS
    CURSOR memory_patterns IS
        SELECT 
            m.CATEGORY,
            SUBSTR(m.CONTENT, 1, 500) as CONTENT_SUMMARY,
            COUNT(*) as occurrence_count,
            MIN(m.CREATED_AT) as first_seen,
            MAX(m.CREATED_AT) as last_seen
        FROM MEMORIES m
        WHERE m.CATEGORY = NVL(p_category, m.CATEGORY)
          AND m.CREATED_AT < SYSTIMESTAMP - 30
        GROUP BY m.CATEGORY, SUBSTR(m.CONTENT, 1, 500)
        HAVING COUNT(*) >= p_min_occurrences;
    
    v_knowledge_id NUMBER;
    v_concept_count NUMBER := 0;
BEGIN
    FOR pattern IN memory_patterns LOOP
        -- Create knowledge concept from pattern
        v_knowledge_id := knowledge_base_api.create_concept(
            p_concept_name => 'Pattern: ' || SUBSTR(pattern.CONTENT_SUMMARY, 1, 100),
            p_concept_type => 'PATTERN',
            p_category     => pattern.CATEGORY,
            p_title        => 'Learned Pattern from ' || pattern.occurrence_count || ' occurrences',
            p_description  => 'Pattern detected from repeated memories between ' || 
                             TO_CHAR(pattern.first_seen, 'YYYY-MM-DD') || ' and ' ||
                             TO_CHAR(pattern.last_seen, 'YYYY-MM-DD'),
            p_content      => pattern.CONTENT_SUMMARY,
            p_source_type  => 'DISTILLED',
            p_tags         => '["auto-distilled", "pattern"]',
            p_confidence   => LEAST(1.0, pattern.occurrence_count / 10)
        );
        
        v_concept_count := v_concept_count + 1;
        
        DBMS_OUTPUT.PUT_LINE('Distilled pattern: ' || SUBSTR(pattern.CONTENT_SUMMARY, 1, 50) || '...');
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('Total patterns distilled: ' || v_concept_count);
    
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error in detect_memory_patterns: ' || SQLERRM);
        ROLLBACK;
END detect_memory_patterns;
/

CREATE OR REPLACE PROCEDURE extract_experience(
    p_memory_category VARCHAR2 DEFAULT NULL,
    p_min_age_days NUMBER DEFAULT 60
) AS
    CURSOR experience_candidates IS
        SELECT 
            m.ID as memory_id,
            SUBSTR(m.CONTENT, 1, 1000) as content_summary,
            m.CATEGORY,
            m.ACCESS_COUNT,
            m.CREATED_AT
        FROM MEMORIES m
        WHERE m.CATEGORY = NVL(p_memory_category, m.CATEGORY)
          AND m.CREATED_AT < SYSTIMESTAMP - p_min_age_days
          AND m.ACCESS_COUNT > 5
        ORDER BY m.ACCESS_COUNT DESC
        FETCH FIRST 20 ROWS ONLY;
    
    v_experience_content CLOB;
    v_knowledge_id NUMBER;
    v_memory_count NUMBER := 0;
BEGIN
    FOR rec IN experience_candidates LOOP
        v_experience_content := v_experience_content || 
            'Experience from ' || TO_CHAR(rec.CREATED_AT, 'YYYY-MM-DD') || 
            ' (accessed ' || rec.ACCESS_COUNT || ' times): ' ||
            rec.content_summary || CHR(10) || CHR(10);
        v_memory_count := v_memory_count + 1;
    END LOOP;
    
    IF v_experience_content IS NOT NULL AND v_memory_count >= 3 THEN
        -- Create experience knowledge
        v_knowledge_id := knowledge_base_api.create_concept(
            p_concept_name => 'Experience: ' || NVL(p_memory_category, 'General'),
            p_concept_type => 'EXPERIENCE',
            p_category     => NVL(p_memory_category, 'General'),
            p_title        => 'Accumulated experience in ' || NVL(p_memory_category, 'General'),
            p_description  => 'Experience distilled from ' || v_memory_count || ' high-value memories',
            p_content      => v_experience_content,
            p_source_type  => 'DISTILLED',
            p_tags         => '["auto-distilled", "experience"]',
            p_confidence   => 0.9
        );
        
        DBMS_OUTPUT.PUT_LINE('Extracted experience for category: ' || NVL(p_memory_category, 'General'));
        DBMS_OUTPUT.PUT_LINE('  Memories used: ' || v_memory_count);
    ELSE
        DBMS_OUTPUT.PUT_LINE('Insufficient high-value memories for experience extraction');
    END IF;
    
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error in extract_experience: ' || SQLERRM);
        ROLLBACK;
END extract_experience;
/

-- ============================================================================
-- SCHEDULED JOBS DEPLOYMENT COMPLETE
-- ============================================================================
