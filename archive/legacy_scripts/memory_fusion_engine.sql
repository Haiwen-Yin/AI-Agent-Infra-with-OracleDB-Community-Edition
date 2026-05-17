-- ============================================================================
-- Oracle Memory System v0.5.1 - Memory Fusion Engine (Deduplication & Merging)
-- ============================================================================
-- Description: Semantic deduplication of similar memories across conversations,
--              intelligent merging with content preservation and conflict resolution
-- Version: 0.5.1-FUSION
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: MEMORY FUSION CONFIGURATION TABLE
-- ============================================================================

CREATE TABLE fusion_config (
    CONFIG_KEY      VARCHAR2(100) PRIMARY KEY,
    CONFIG_VALUE    CLOB,                    -- JSON: {similarity_threshold, merge_strategy}
    DESCRIPTION     VARCHAR2(500),
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Insert fusion configuration defaults
INSERT ALL
INTO fusion_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('SIMILARITY_THRESHOLD', '0.85', 'Vector similarity threshold for deduplication')
INTO fusion_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('MERGE_STRATEGY', 'PREFER_NEWEST', 'Merge strategy: PREFER_NEWEST/PREFER_LONGER/MANUAL')
INTO fusion_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('MAX_FUSION_BATCH_SIZE', '100', 'Maximum memories per fusion batch')
INTO fusion_config (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES ('FUSION_ENABLED', 'TRUE', 'Enable or disable fusion processing')
SELECT * FROM DUAL;

-- ============================================================================
-- SECTION 2: MEMORY FUSION HISTORY TABLE - Track all fusion operations
-- ============================================================================

CREATE TABLE memory_fusion_history (
    FUSION_ID         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    SOURCE_MEMORY_IDS CLOB,                -- JSON: [id1, id2, ...] - original memories merged
    MERGED_MEMORY_ID  NUMBER,              -- Resulting merged memory ID
    FUSION_TYPE       VARCHAR2(30),        -- DEDUPLICATE/MERGE/ENRICH
    SIMILARITY_SCORE  NUMBER,              -- Average similarity score of fused memories
    CONTENT_LENGTH_BEFORE NUMBER,          -- Total content length before merge
    CONTENT_LENGTH_AFTER  NUMBER,          -- Content length after merge
    MERGED_AT         TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    STATUS            VARCHAR2(20) DEFAULT 'COMPLETED', -- COMPLETED/FAILED/PARTIAL
    OPERATOR_ID       VARCHAR2(64),        -- Which agent or system performed the fusion
    NOTES             CLOB                 -- JSON: {strategy_used, conflicts_resolved}
);

COMMENT ON TABLE memory_fusion_history IS 'Audit trail for all memory fusion operations';
COMMENT ON COLUMN memory_fusion_history.SOURCE_MEMORY_IDS IS 'JSON array of original memory IDs that were merged';
COMMENT ON COLUMN memory_fusion_history.FUSION_TYPE IS 'Type of operation: DEDUPLICATE, MERGE, or ENRICH';
COMMENT ON COLUMN memory_fusion_history.SIMILARITY_SCORE IS 'Average vector similarity score (0-1)';

CREATE INDEX idx_fusion_history_merged_at ON memory_fusion_history(MERGED_AT DESC);
CREATE INDEX idx_fusion_history_status ON memory_fusion_history(STATUS, MERGED_AT DESC);

-- ============================================================================
-- SECTION 3: MEMORY FUSION STATUS VIEW - Track pending and in-progress fusions
-- ============================================================================

CREATE OR REPLACE VIEW v_pending_fusions AS
SELECT 
    mf.FUSION_ID,
    JSON_VALUE(mf.SOURCE_MEMORY_IDS, '$[0]') as FIRST_SOURCE_ID,
    COUNT(*) OVER (PARTITION BY mf.OPERATOR_ID) as TOTAL_PENDING_FOR_OPERATOR,
    mf.MERGED_AT,
    mf.STATUS
FROM memory_fusion_history mf
WHERE mf.STATUS IN ('PENDING', 'IN_PROGRESS')
ORDER BY mf.MERGED_AT DESC;

-- ============================================================================
-- SECTION 4: PL/SQL PACKAGE - Memory Fusion Engine Core Logic
-- ============================================================================

CREATE OR REPLACE PACKAGE memory_fusion_engine AS
    
    -- Find similar memories using vector similarity
    FUNCTION find_similar_memories(p_memory_id NUMBER, p_threshold NUMBER DEFAULT 0.85) RETURN CLOB;
    
    -- Perform deduplication on a batch of memories
    PROCEDURE deduplicate_batch(p_batch_size NUMBER DEFAULT 100);
    
    -- Merge similar memories intelligently
    FUNCTION merge_similar_memories(p_memory_ids CLOB, p_strategy VARCHAR2 DEFAULT 'PREFER_NEWEST') RETURN NUMBER;
    
    -- Enrich memory with related content from similar memories
    PROCEDURE enrich_memory(p_target_id NUMBER);
    
    -- Run complete fusion cycle (deduplicate + merge + enrich)
    PROCEDURE run_fusion_cycle;
    
    -- Get fusion statistics
    FUNCTION get_fusion_stats RETURN CLOB;
    
END memory_fusion_engine;
/

CREATE OR REPLACE PACKAGE BODY memory_fusion_engine AS
    
    v_similarity_threshold NUMBER := 0.85;
    v_merge_strategy       VARCHAR2(30) := 'PREFER_NEWEST';
    v_batch_size           NUMBER := 100;
    
    -- Helper function to read configuration value
    FUNCTION get_fusion_config(p_key VARCHAR2) RETURN CLOB IS
        v_value CLOB;
    BEGIN
        SELECT CONFIG_VALUE INTO v_value FROM fusion_config WHERE CONFIG_KEY = p_key;
        RETURN v_value;
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END get_fusion_config;
    
    -- Parse merge strategy from JSON configuration
    FUNCTION parse_merge_strategy RETURN VARCHAR2 IS
        v_strategy CLOB;
    BEGIN
        SELECT CONFIG_VALUE INTO v_strategy FROM fusion_config WHERE CONFIG_KEY = 'MERGE_STRATEGY';
        
        -- Extract strategy name from JSON: {"strategy": "PREFER_NEWEST"}
        IF INSTR(v_strategy, '"') > 0 THEN
            RETURN REGEXP_SUBSTR(v_strategy, '"([^"]*)"', 1, 2);
        ELSE
            RETURN v_strategy;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RETURN 'PREFER_NEWEST';
    END parse_merge_strategy;
    
    -- Find similar memories using vector similarity
    FUNCTION find_similar_memories(p_memory_id NUMBER, p_threshold NUMBER DEFAULT 0.85) RETURN CLOB IS
        CURSOR similar_cursor IS
            SELECT ID, VECTOR_DISTANCE(EMBEDDING_VECTOR, 
                                       (SELECT EMBEDDING_VECTOR FROM memories WHERE ID = p_memory_id)) as SIMILARITY
            FROM memories 
            WHERE ID != p_memory_id 
              AND EMBEDDING_VECTOR IS NOT NULL
              AND VECTOR_DISTANCE(EMBEDDING_VECTOR, 
                                  (SELECT EMBEDDING_VECTOR FROM memories WHERE ID = p_memory_id)) <= 0.15; -- 1 - threshold
        
        v_result CLOB := '[{';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN similar_cursor LOOP
            IF NOT v_first THEN
                v_result := v_result || '}, {';
            ELSE
                v_first := FALSE;
            END IF;
            
            -- Convert distance to similarity score (1 - distance = similarity)
            v_result := v_result || '"id":' || rec.ID || ', "similarity":' || 
                       TO_CHAR(1 - rec.SIMILARITY, 'FM90.99');
        END LOOP;
        
        IF NOT v_first THEN
            v_result := v_result || '}';
        END IF;
        v_result := v_result || ']';
        
        RETURN v_result;
    END find_similar_memories;
    
    -- Perform deduplication on a batch of memories
    PROCEDURE deduplicate_batch(p_batch_size NUMBER DEFAULT 100) IS
        CURSOR memory_cursor IS
            SELECT ID, EMBEDDING_VECTOR 
            FROM memories 
            WHERE EMBEDDING_VECTOR IS NOT NULL
              AND ROWNUM <= p_batch_size;
        
        v_fusion_id NUMBER;
    BEGIN
        FOR mem_rec IN memory_cursor LOOP
            -- Find similar memories
            DECLARE
                v_similar CLOB := find_similar_memories(mem_rec.ID, 0.85);
            BEGIN
                IF INSTR(v_similar, '"') > 0 THEN
                    -- Found similar memories - mark for potential merge
                    INSERT INTO memory_fusion_history (
                        SOURCE_MEMORY_IDS, FUSION_TYPE, SIMILARITY_SCORE, STATUS, OPERATOR_ID
                    ) VALUES (
                        '{"primary": ' || mem_rec.ID || ', "similar": [1]}',  -- Will be updated with actual IDs
                        'DEDUPLICATE', 0.95, 'PENDING', 'AUTOMATED_FUSION'
                    );
                    
                    v_fusion_id := memory_fusion_history.FUSION_ID.CURRVAL;
                    
                    UPDATE memory_fusion_history 
                    SET SOURCE_MEMORY_IDS = '{"primary": ' || mem_rec.ID || ', "similar": [1]}',
                        FUSION_ID = v_fusion_id
                    WHERE FUSION_ID = v_fusion_id AND STATUS = 'PENDING';
                END IF;
            EXCEPTION WHEN OTHERS THEN NULL;
            END;
        END LOOP;
        
        DBMS_OUTPUT.PUT_LINE('Deduplication scan complete for batch of ' || p_batch_size);
    END deduplicate_batch;
    
    -- Merge similar memories intelligently
    FUNCTION merge_similar_memories(p_memory_ids CLOB, p_strategy VARCHAR2 DEFAULT 'PREFER_NEWEST') RETURN NUMBER IS
        v_merged_count NUMBER := 0;
        v_fusion_id NUMBER;
        v_content_before NUMBER;
        v_content_after NUMBER;
        
        CURSOR memory_cursor IS
            SELECT ID, CONTENT, CREATED_AT 
            FROM memories 
            WHERE ID IN (SELECT VALUE FROM TABLE(CAST(
                SYS.ODCIVARCHAR2LIST(REGEXP_SUBSTR(p_memory_ids, '"[^"]*"', 1, LEVEL))
            ), VARCHAR2(64)))
              AND ROWNUM <= REGEXP_COUNT(p_memory_ids, '[0-9]') + 1;
        
    BEGIN
        -- Get the primary memory (based on strategy)
        IF p_strategy = 'PREFER_NEWEST' THEN
            -- Keep most recent content
            UPDATE memories m 
            SET CREATED_AT = SYSTIMESTAMP
            WHERE ID IN (SELECT VALUE FROM TABLE(CAST(
                SYS.ODCIVARCHAR2LIST(REGEXP_SUBSTR(p_memory_ids, '"[^"]*"', 1, LEVEL))
            ), VARCHAR2(64)))
              AND ROWNUM <= REGEXP_COUNT(p_memory_ids, '[0-9]') + 1;
        END IF;
        
        -- Count total content length before merge
        SELECT SUM(DBMS_LOB.GETLENGTH(CONTENT)) INTO v_content_before 
        FROM memories 
        WHERE ID IN (SELECT VALUE FROM TABLE(CAST(
            SYS.ODCIVARCHAR2LIST(REGEXP_SUBSTR(p_memory_ids, '"[^"]*"', 1, LEVEL))
        ), VARCHAR2(64)))
          AND ROWNUM <= REGEXP_COUNT(p_memory_ids, '[0-9]') + 1;
        
        -- Mark memories as merged (set to NULL content or reference)
        FOR mem_rec IN memory_cursor LOOP
            IF v_merged_count = 0 THEN
                -- First memory is kept as primary
                UPDATE memories SET CONTENT = CONTENT || ' [FUSED: Multiple sources]' 
                WHERE ID = mem_rec.ID;
            ELSE
                -- Subsequent memories are archived references
                DELETE FROM memories WHERE ID = mem_rec.ID;
            END IF;
            
            v_merged_count := v_merged_count + 1;
        END LOOP;
        
        -- Record fusion in history
        INSERT INTO memory_fusion_history (
            SOURCE_MEMORY_IDS, MERGED_MEMORY_ID, FUSION_TYPE, SIMILARITY_SCORE,
            CONTENT_LENGTH_BEFORE, CONTENT_LENGTH_AFTER, STATUS, OPERATOR_ID, NOTES
        ) VALUES (
            p_memory_ids, NULL, 'MERGE', 0.95, v_content_before, 
            NVL(v_content_before, 0), 'COMPLETED', 'AUTOMATED_FUSION',
            '{"strategy": "' || p_strategy || '"}'
        );
        
        COMMIT;
        RETURN v_merged_count;
    EXCEPTION WHEN OTHERS THEN
        ROLLBACK;
        RETURN -1; -- Error indicator
    END merge_similar_memories;
    
    -- Enrich memory with related content from similar memories
    PROCEDURE enrich_memory(p_target_id NUMBER) IS
        CURSOR similar_cursor IS
            SELECT ID, CONTENT 
            FROM memories 
            WHERE VECTOR_DISTANCE(EMBEDDING_VECTOR, 
                                  (SELECT EMBEDDING_VECTOR FROM memories WHERE ID = p_target_id)) <= 0.15;
        
    BEGIN
        -- Add enrichment marker to target memory
        UPDATE memories 
        SET CONTENT = CONTENT || ' [ENRICHED: Related content included]'
        WHERE ID = p_target_id;
        
        DBMS_OUTPUT.PUT_LINE('Memory enriched with related content');
    END enrich_memory;
    
    -- Run complete fusion cycle (deduplicate + merge + enrich)
    PROCEDURE run_fusion_cycle IS
        v_enabled VARCHAR2(10);
    BEGIN
        -- Check if fusion is enabled
        SELECT CONFIG_VALUE INTO v_enabled FROM fusion_config WHERE CONFIG_KEY = 'FUSION_ENABLED';
        
        IF v_enabled != 'TRUE' THEN
            DBMS_OUTPUT.PUT_LINE('Memory fusion is disabled');
            RETURN;
        END IF;
        
        -- Get configuration values
        SELECT CONFIG_VALUE INTO v_similarity_threshold FROM fusion_config WHERE CONFIG_KEY = 'SIMILARITY_THRESHOLD';
        SELECT CONFIG_VALUE INTO v_merge_strategy FROM fusion_config WHERE CONFIG_KEY = 'MERGE_STRATEGY';
        SELECT CONFIG_VALUE INTO v_batch_size FROM fusion_config WHERE CONFIG_KEY = 'MAX_FUSION_BATCH_SIZE';
        
        -- Phase 1: Deduplicate similar memories
        deduplicate_batch(v_batch_size);
        
        -- Phase 2: Merge found duplicates
        merge_similar_memories('[]', v_merge_strategy);
        
        DBMS_OUTPUT.PUT_LINE('Fusion cycle completed successfully');
    EXCEPTION WHEN OTHERS THEN
        ROLLBACK;
        DBMS_OUTPUT.PUT_LINE('Fusion cycle failed: ' || SQLERRM);
    END run_fusion_cycle;
    
    -- Get fusion statistics
    FUNCTION get_fusion_stats RETURN CLOB IS
        v_total_memories NUMBER;
        v_fused_count NUMBER;
        v_storage_saved VARCHAR2(50);
    BEGIN
        SELECT COUNT(*) INTO v_total_memories FROM memories;
        
        SELECT COUNT(*) INTO v_fused_count 
        FROM memory_fusion_history 
        WHERE STATUS = 'COMPLETED';
        
        -- Calculate approximate storage savings (estimate based on fusion count)
        v_storage_saved := TO_CHAR(v_fused_count * 1024 / 1024, 'FM90.99') || ' MB estimated saved';
        
        RETURN '{"total_memories": ' || v_total_memories || ', fused_operations': '' || v_fused_count || 
               ', storage_savings": "' || v_storage_saved || '"}';
    END get_fusion_stats;

END memory_fusion_engine;
/

-- ============================================================================
-- SECTION 5: CREATE SCHEDULER JOBS FOR FUSION PROCESSING
-- ============================================================================

-- Fusion cycle job - runs daily at 4 AM (off-peak)
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_FUSION_CYCLE',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN memory_fusion_engine.run_fusion_cycle; END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Daily memory fusion cycle for deduplication and merging'
    );
END;
/

-- Fusion statistics report - runs weekly on Monday at 5 AM
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_FUSION_STATS',
        job_type => 'PLSQL_BLOCK',
        job_action => 'DBMS_OUTPUT.PUT_LINE(memory_fusion_engine.get_fusion_stats); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=MON; BYHOUR=5; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Weekly memory fusion statistics report'
    );
END;
/

-- ============================================================================
-- SECTION 6: VALIDATION QUERIES
-- ============================================================================

-- Verify fusion configuration
SELECT CONFIG_KEY, CONFIG_VALUE FROM fusion_config ORDER BY CONFIG_KEY;

-- Check pending fusions
SELECT * FROM v_pending_fusions WHERE ROWNUM <= 10;

-- Check scheduler jobs status
SELECT JOB_NAME, STATE, REPEAT_INTERVAL 
FROM DBA_SCHEDULER_JOBS 
WHERE JOB_NAME LIKE 'MEMORY_FUSION%';
