-- Oracle AI Database Memory System v1.0.0
-- Query Optimization Script
-- Author: 胖头鱼 🐟 (Haiwen Yin)
-- Version: v1.0.0 Production Release
-- Last Updated: 2024-12-19

-- ============================================================================
-- TABLE OF CONTENTS
-- ============================================================================
-- 1. Query Analysis
-- 2. Execution Plan Optimization
-- 3. Index Hints and Usage
-- 4. Partition Pruning
-- 5. Result Cache Optimization
-- 6. Parallel Query Optimization
-- 7. Common Anti-Patterns

-- ============================================================================
-- 1. QUERY ANALYSIS
-- ============================================================================

-- Find slow vector queries
SELECT 
    sql_id,
    sql_text,
    elapsed_time/1000000 AS elapsed_sec,
    cpu_time/1000000 AS cpu_sec,
    buffer_gets,
    disk_reads,
    executions,
    ROUND(elapsed_time / NULLIF(executions, 0) / 1000000, 3) AS avg_elapsed_sec,
    CASE 
        WHEN elapsed_time / NULLIF(executions, 0) > 1000000 THEN 'SLOW'
        WHEN elapsed_time / NULLIF(executions, 0) > 100000 THEN 'MODERATE'
        ELSE 'FAST'
    END AS performance_rating
FROM V$SQL
WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
   OR sql_text LIKE '%memories%'
   OR sql_text LIKE '%knowledge_concepts%'
ORDER BY elapsed_time DESC
FETCH FIRST 50 ROWS ONLY;

-- Identify full table scans on vector tables
SELECT 
    sql_id,
    sql_text,
    elapsed_time/1000000 AS elapsed_sec,
    buffer_gets,
    disk_reads,
    'FULL TABLE SCAN DETECTED' AS issue
FROM V$SQL
WHERE (sql_text LIKE '%FROM memories%WHERE%' 
   OR sql_text LIKE '%FROM knowledge_concepts%WHERE%')
AND buffer_gets > 100000
ORDER BY buffer_gets DESC;

-- Check for missing indexes
SELECT 
    t.table_name,
    t.num_rows,
    t.last_analyzed,
    CASE 
        WHEN i.index_name IS NULL THEN 'NO INDEX'
        ELSE 'INDEX EXISTS'
    END AS index_status
FROM user_tables t
LEFT JOIN user_indexes i ON t.table_name = i.table_name
WHERE t.table_name IN ('MEMORIES', 'KNOWLEDGE_CONCEPTS', 'KNOWLEDGE_RELATIONSHIPS')
ORDER BY t.table_name;

-- ============================================================================
-- 2. EXECUTION PLAN OPTIMIZATION
-- ============================================================================

-- Enable statistics gathering
ALTER SESSION SET STATISTICS_LEVEL = 'ALL';

-- Example: Analyze vector search query
EXPLAIN PLAN FOR
SELECT /*+ INDEX(memories IDX_MEMEMBEDDING_HNSW) */
    memory_id,
    content,
    tags,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        10
    ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
AND status = 'active'
ORDER BY similarity_score DESC;

-- Display execution plan
SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY(format => 'ALL'));

-- Check for full table scans in execution plan
SELECT 
    operation,
    options,
    object_name,
    cost,
    cardinality,
    bytes
FROM PLAN_TABLE
WHERE operation = 'TABLE ACCESS'
AND options = 'FULL'
ORDER BY cost DESC;

-- ============================================================================
-- 3. INDEX HINTS AND USAGE
-- ============================================================================

-- Use INDEX hint for vector search
SELECT /*+ INDEX(memories IDX_MEMEMBEDDING_HNSW) */
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        10
    ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
ORDER BY similarity_score DESC
FETCH FIRST 10 ROWS ONLY;

-- Use FULL hint when appropriate (for analytical queries)
SELECT /*+ FULL(memories) */
    memory_type,
    COUNT(*) AS cnt
FROM memories
GROUP BY memory_type;

-- Check index usage statistics
SELECT 
    index_name,
    table_name,
    used,
    last_used,
    start_tracking_date,
    end_tracking_date
FROM user_objects_usage
WHERE object_name LIKE 'IDX_%'
AND table_name IN ('MEMORIES', 'KNOWLEDGE_CONCEPTS')
ORDER BY last_used DESC;

-- ============================================================================
-- 4. PARTITION PRUNING
-- ============================================================================

-- Create partitioned table for better performance
CREATE TABLE memories_partitioned (
    memory_id NUMBER GENERATED ALWAYS AS IDENTITY,
    content CLOB NOT NULL,
    memory_type VARCHAR2(50) NOT NULL,
    tags CLOB,
    metadata CLOB,
    embedding_vector VECTOR(1024, FLOAT32),
    embedding_model VARCHAR2(50) DEFAULT 'bge-m3',
    status VARCHAR2(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    updated_at TIMESTAMP DEFAULT SYSTIMESTAMP,
    partition_date DATE DEFAULT TRUNC(SYSDATE)
)
PARTITION BY RANGE (partition_date) (
    PARTITION p_current VALUES LESS THAN (TRUNC(SYSDATE) + 1),
    PARTITION p_week1 VALUES LESS THAN (TRUNC(SYSDATE) + 8),
    PARTITION p_week2 VALUES LESS THAN (TRUNC(SYSDATE) + 15),
    PARTITION p_month1 VALUES LESS THAN (ADD_MONTHS(TRUNC(SYSDATE), 1)),
    PARTITION p_future VALUES LESS THAN (MAXVALUE)
);

-- Query with partition pruning
SELECT /*+ ORDERED USE_HASH(memories) */
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        10
    ) AS similarity_score
FROM memories_partitioned
WHERE partition_date >= TRUNC(SYSDATE) - 30  -- Partition pruning
AND memory_type = 'experience'
AND status = 'active'
ORDER BY similarity_score DESC
FETCH FIRST 10 ROWS ONLY;

-- Verify partition pruning in execution plan
EXPLAIN PLAN FOR
SELECT * FROM memories_partitioned
WHERE partition_date = TRUNC(SYSDATE);

SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY(format => 'PARTITION'));

-- ============================================================================
-- 5. RESULT CACHE OPTIMIZATION
-- ============================================================================

-- Enable result cache
ALTER SYSTEM SET RESULT_CACHE_MODE = 'FORCE';

-- Use result cache hint for repeated queries
SELECT /*+ RESULT_CACHE */
    memory_type,
    COUNT(*) AS cnt
FROM memories
WHERE status = 'active'
GROUP BY memory_type;

-- Monitor cache usage
SELECT 
    name,
    count,
    bytes,
    hits,
    ROUND(hits / NULLIF(count, 0) * 100, 2) AS hit_ratio_pct
FROM V$RESULT_CACHE_STATISTICS
WHERE name LIKE '%result_cache%';

-- Check cached objects
SELECT 
    name,
    type,
    namespace,
    blocks,
    bytes,
    status
FROM V$RESULT_CACHE_OBJECTS
WHERE name LIKE '%MEMORIES%'
ORDER BY bytes DESC;

-- Invalidate cache when needed
BEGIN
    DBMS_RESULT_CACHE.INVALIDATE(
        'OPENCLAW',
        'MEMORIES'
    );
END;
/

-- ============================================================================
-- 6. PARALLEL QUERY OPTIMIZATION
-- ============================================================================

-- Enable parallel query
ALTER SESSION ENABLE PARALLEL QUERY;
ALTER SESSION FORCE PARALLEL QUERY PARALLEL 8;

-- Use parallel hint for vector operations
SELECT /*+ PARALLEL(memories, 8) */
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        10
    ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
ORDER BY similarity_score DESC
FETCH FIRST 100 ROWS ONLY;

-- Check parallel execution statistics
SELECT 
    qcinst_id,
    servers_allocated,
    servers_used,
    servers_waiting,
    servers_highwater
FROM V$PQ_SESSTAT
WHERE statistic = 'DFO Tree Proc Count';

-- Monitor parallel query performance
SELECT 
    sql_id,
    sql_text,
    elapsed_time/1000000 AS elapsed_sec,
    px_servers_connected,
    px_servers_used
FROM V$SQL
WHERE sql_text LIKE '%PARALLEL%'
AND elapsed_time > 1000000
ORDER BY elapsed_time DESC;

-- ============================================================================
-- 7. COMMON ANTI-PATTERNS
-- ============================================================================

-- ❌ BAD: Full table scan with vector similarity
-- This will scan entire table before applying vector search
SELECT 
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        100  -- Too large limit
    ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
AND status = 'active';

-- ✅ GOOD: Use index hint and reasonable limit
SELECT /*+ INDEX(memories IDX_MEMEMBEDDING_HNSW) */
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        TO_VECTOR('[0.1, 0.2, 0.3]', 1024, 32, 'FLOAT32'),
        'COSINE',
        10  -- Reasonable limit
    ) AS similarity_score
FROM memories
WHERE memory_type = 'experience'
AND status = 'active'
ORDER BY similarity_score DESC
FETCH FIRST 10 ROWS ONLY;

-- ❌ BAD: Using LIKE on CLOB columns
SELECT *
FROM memories
WHERE content LIKE '%Oracle%'
AND memory_type = 'experience';

-- ✅ GOOD: Use Oracle Text for full-text search
CREATE INDEX idx_memories_content ON memories (content)
INDEXTYPE IS CTXSYS.CONTEXT;

SELECT *
FROM memories
WHERE CONTAINS(content, 'Oracle', 1) > 0
AND memory_type = 'experience';

-- ❌ BAD: Selecting all columns when not needed
SELECT *
FROM memories
WHERE memory_type = 'experience';

-- ✅ GOOD: Select only needed columns
SELECT 
    memory_id,
    content,
    memory_type,
    tags
FROM memories
WHERE memory_type = 'experience';

-- ❌ BAD: Using OR conditions that prevent index usage
SELECT *
FROM memories
WHERE memory_type = 'experience'
OR memory_type = 'observation';

-- ✅ GOOD: Use IN clause
SELECT *
FROM memories
WHERE memory_type IN ('experience', 'observation');

-- ============================================================================
-- OPTIMIZATION CHECKLIST
-- ============================================================================

/*
□ 1. Vector Indexes
  □ Create HNSW index on embedding_vector columns
  □ Set appropriate NEIGHBORS COUNT (16-64)
  □ Configure EF_SEARCH for accuracy requirements
  □ Monitor and rebuild indexes regularly

□ 2. Query Optimization
  □ Use INDEX hints for vector searches
  □ Filter before vector similarity (WHERE clause first)
  □ Use FETCH FIRST instead of large limits
  □ Avoid SELECT * - only select needed columns

□ 3. Partitioning
  □ Partition large tables by date or type
  □ Use partition pruning in queries
  □ Manage partitions with interval partitioning

□ 4. Caching
  □ Enable result cache for repeated queries
  □ Use RESULT_CACHE hint for static data
  □ Monitor cache hit ratio
  □ Invalidate cache when data changes

□ 5. Parallel Execution
  □ Enable parallel query for large datasets
  □ Use PARALLEL hint for complex queries
  □ Monitor parallel execution statistics
  □ Adjust degree based on workload

□ 6. Statistics
  □ Gather statistics regularly
  □ Use DBMS_STATS for accurate statistics
  □ Monitor table and index statistics
  □ Update statistics after bulk operations

□ 7. Memory
  □ Allocate sufficient PGA for sort operations
  □ Increase SGA for buffer cache
  □ Monitor vector memory usage
  □ Adjust memory parameters based on workload
*/

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify index effectiveness
SELECT 
    index_name,
    num_rows,
    leaf_blocks,
    clustering_factor,
    ROUND(leaf_blocks / NULLIF(num_rows, 0) * 100, 4) AS leaf_per_row_pct,
    CASE 
        WHEN clustering_factor < num_rows * 0.1 THEN 'EXCELLENT'
        WHEN clustering_factor < num_rows * 0.3 THEN 'GOOD'
        WHEN clustering_factor < num_rows * 0.5 THEN 'FAIR'
        ELSE 'POOR'
    END AS effectiveness
FROM user_indexes
WHERE index_name LIKE 'IDX_%EMBEDDING%'
ORDER BY index_name;

-- Verify query performance
SET TIMING ON;
SELECT 
    memory_id,
    content,
    VECTOR_SIMILARITY(embedding_vector, 
        (SELECT embedding_vector FROM memories WHERE memory_id = 1),
        'COSINE',
        10
    ) AS similarity_score
FROM memories
WHERE memory_id != 1
ORDER BY similarity_score DESC
FETCH FIRST 10 ROWS ONLY;

-- ============================================================================
-- END OF SCRIPT
-- ============================================================================

/*
NOTES:
1. Always test query optimizations in staging first
2. Monitor execution plans after changes
3. Use AWR/ASH for historical performance analysis
4. Adjust parameters based on specific workload
5. Document all optimization changes
6. Revert changes if performance degrades
*/
