-- ============================================
-- aggregation_analysis.sql (Final Fixed Version)
-- P3-优化: 聚合分析功能 - 替代精确查询降低隐私风险
-- Version: v0.4.3 (Aggregation Analysis - Final Fix for Existing Schema)
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-08
-- ============================================

-- ============================================
-- Section 1: 聚合统计视图（适配现有MEMORIES表结构）
-- ============================================

-- 按时间范围统计内存数量（不暴露具体内容）
CREATE OR REPLACE VIEW MEMORY_AGGREGATE_STATS AS
SELECT 
    TO_CHAR(CREATED_AT, 'YYYY-MM') AS month,
    COUNT(*) AS total_memories,
    MIN(CREATED_AT) AS earliest_memory,
    MAX(CREATED_AT) AS latest_memory,
    AVG(LENGTH(CONTENT)) AS avg_content_size
FROM MEMORIES
GROUP BY TO_CHAR(CREATED_AT, 'YYYY-MM')
ORDER BY month DESC;

-- 按内存类型统计（用于容量规划）
CREATE OR REPLACE VIEW MEMORY_TYPE_STATS AS
SELECT 
    DECODE(MEMORY_TYPE,
        'TASK_PLAN', '任务计划',
        'SESSION_SNAPSHOT', '会话快照',
        'CONTEXT_DATA', '上下文数据',
        'MEMORY', '内存存储',
        'VECTOR', '向量存储',
        'OTHER', '其他'
    ) AS type_cn,
    COUNT(*) AS count
FROM MEMORIES
GROUP BY DECODE(MEMORY_TYPE,
        'TASK_PLAN', '任务计划',
        'SESSION_SNAPSHOT', '会话快照',
        'CONTEXT_DATA', '上下文数据',
        'MEMORY', '内存存储',
        'VECTOR', '向量存储',
        'OTHER', '其他'
    )
ORDER BY count DESC;

-- ============================================
-- Section 2: 模糊匹配搜索（不精确暴露）- 适配现有表结构
-- ============================================

CREATE OR REPLACE VIEW MEMORY_SEARCH_SUMMARY AS
SELECT 
    ID,
    NVL(CATEGORY || ': ', '(N/A)') || '...' AS subject_preview,
    SUBSTR(CONTENT, 1, 100) || CASE WHEN LENGTH(CONTENT) > 100 THEN '...[TRUNCATED]' END AS content_snippet,
    CREATED_AT,
    MEMORY_TYPE,
    DBMS_LOB.GETLENGTH(CONTENT) AS content_size_bytes,
    CASE 
        WHEN DBMS_LOB.GETLENGTH(CONTENT) > 5000 THEN 'HIGH_SENSITIVITY_FULL_ACCESS_REQUIRED'
        ELSE 'NORMAL_ACCESS'
    END AS access_level
FROM MEMORIES
ORDER BY CREATED_AT DESC;

-- ============================================
-- Section 3: 隐私保护存储过程（适配现有表结构）
-- ============================================

CREATE OR REPLACE PROCEDURE GET_MEMORY_ANALYTICS(
    p_start_date IN TIMESTAMP WITH TIME ZONE,
    p_end_date   IN TIMESTAMP WITH TIME ZONE,
    p_output_type IN VARCHAR2 DEFAULT 'STATISTICS', -- STATISTICS or SUMMARY
    p_cursor     OUT SYS_REFCURSOR
)
AS
BEGIN
    IF UPPER(p_output_type) = 'SUMMARY' THEN
        OPEN p_cursor FOR
            SELECT * FROM MEMORY_SEARCH_SUMMARY;
    ELSE
        OPEN p_cursor FOR
            SELECT * FROM MEMORY_AGGREGATE_STATS 
            WHERE CREATED_AT BETWEEN p_start_date AND p_end_date;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('Analytics query executed successfully');
END GET_MEMORY_ANALYTICS;
/

-- ============================================
-- Section 4: 数据保留策略视图（适配现有表结构）
-- ============================================

CREATE OR REPLACE VIEW DATA_RETENTION_POLICY AS
SELECT 
    'MEMORY' AS entity_type,
    '90 days for content, 1 year for metadata' AS retention_policy,
    CASE 
        WHEN CREATED_AT < SYSTIMESTAMP - INTERVAL '90' DAY THEN 'CONTENT_ELIGIBLE_FOR_DELETION'
        ELSE 'CONTENT_RETAINED'
    END AS content_status,
    CASE 
        WHEN CREATED_AT < SYSTIMESTAMP - INTERVAL '365' DAY THEN 'METADATA_ELIGIBLE_FOR_CLEANUP'
        ELSE 'METADATA_ACTIVE'
    END AS metadata_status,
    RETENTION_ACTION_DATE
FROM (
    SELECT 
        ID,
        CREATED_AT,
        CASE 
            WHEN CREATED_AT < SYSTIMESTAMP - INTERVAL '90' DAY THEN SYSTIMESTAMP - INTERVAL '90' DAY
            ELSE NULL
        END AS RETENTION_ACTION_DATE
    FROM MEMORIES
);

-- ============================================
-- Section 5: 统计信息收集过程（定期执行）- 适配现有表结构
-- ============================================

CREATE OR REPLACE PROCEDURE COLLECT_MEMORY_STATISTICS()
IS
    v_memories_stats VARCHAR2(100);
BEGIN
    -- Collect MEMORIES statistics with error handling using anonymous block
    BEGIN
        EXECUTE IMMEDIATE 'ANALYZE TABLE MEMORIES COMPUTE STATISTICS';
        v_memories_stats := 'OK';
        DBMS_OUTPUT.PUT_LINE('MEMORIES table analyzed successfully');
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Warning: Could not collect MEMORIES stats - ' || SQLERRM);
            v_memories_stats := 'FAILED';
    END;
    
    -- Summary output
    DBMS_OUTPUT.PUT_LINE('MEMORIES statistics status: ' || v_memories_stats);
    DBMS_OUTPUT.PUT_LINE('Collection completed at ' || 
                         TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'));
END COLLECT_MEMORY_STATISTICS;
/

-- ============================================
-- Section 6: 权限控制视图（限制敏感数据访问）- 适配现有表结构
-- ============================================

CREATE OR REPLACE VIEW SECURE_MEMORY_ACCESS AS
SELECT 
    ID,
    CASE 
        WHEN USER NOT IN ('MEMORY_ADMIN', 'SYSTEM') THEN 'ACCESS_DENIED'
        ELSE 'ACCESS_GRANTED'
    END AS access_status
FROM MEMORIES;
