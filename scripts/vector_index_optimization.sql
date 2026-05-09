-- Oracle AI Database Memory System v1.0.0
-- Vector Index Optimization Script
-- Author: 胖头鱼 🐟 (Haiwen Yin)
-- Version: v1.0.0 Production Release
-- Last Updated: 2024-12-19

-- ============================================================================
-- TABLE OF CONTENTS
-- ============================================================================
-- 1. Vector Index Analysis
-- 2. HNSW Index Optimization
-- 3. IVF Index Configuration
-- 4. Index Maintenance
-- 5. Performance Monitoring
-- 6. Recommended Configurations

-- ============================================================================
-- 1. VECTOR INDEX ANALYSIS
-- ============================================================================

-- Analyze current vector index status
SELECT 
    i.index_name,
    i.table_name,
    i.num_rows,
    i.leaf_blocks,
    i.clustering_factor,
    i.last_analyzed,
    CASE 
        WHEN i.clustering_factor < i.num_rows * 0.1 THEN 'EXCELLENT'
        WHEN i.clustering_factor < i.num_rows * 0.3 THEN 'GOOD'
        WHEN i.clustering_factor < i.num_rows * 0.5 THEN 'FAIR'
        ELSE 'POOR'
    END AS clustering_quality
FROM user_indexes i
WHERE i.index_name LIKE '%EMBEDDING%'
   OR i.index_name LIKE '%VECTOR%';

-- Check vector column dimensions
SELECT 
    t.table_name,
    t.column_name,
    c.data_type,
    c.data_length,
    c.data_precision,
    c.data_scale
FROM user_tab_columns c
JOIN user_tables t ON c.table_name = t.table_name
WHERE c.data_type = 'VECTOR'
ORDER BY t.table_name;

-- Analyze vector data distribution
SELECT 
    'memories' AS table_name,
    COUNT(*) AS total_rows,
    COUNT(CASE WHEN embedding_vector IS NOT NULL THEN 1 END) AS vectors_count,
    COUNT(CASE WHEN embedding_vector IS NULL THEN 1 END) AS null_vectors,
    ROUND(COUNT(CASE WHEN embedding_vector IS NOT NULL THEN 1 END) / COUNT(*) * 100, 2) AS vector_coverage_pct
FROM memories
UNION ALL
SELECT 
    'knowledge_concepts' AS table_name,
    COUNT(*) AS total_rows,
    COUNT(CASE WHEN embedding_vector IS NOT NULL THEN 1 END) AS vectors_count,
    COUNT(CASE WHEN embedding_vector IS NULL THEN 1 END) AS null_vectors,
    ROUND(COUNT(CASE WHEN embedding_vector IS NOT NULL THEN 1 END) / COUNT(*) * 100, 2) AS vector_coverage_pct
FROM knowledge_concepts;

-- ============================================================================
-- 2. HNSW INDEX OPTIMIZATION
-- ============================================================================

-- Drop existing index if needed
-- DROP INDEX idx_memories_embedding;

-- Create optimized HNSW index for memories table
CREATE VECTOR INDEX idx_memories_embedding_hnsw 
ON memories (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 32
  WITH TARGET ACCURACY 98
}
PARAMETERS (
  TYPE HNSW,
  EF_SEARCH 128,
  EF_CONSTRUCTION 200,
  MAX_SIMILARITY_SEARCH_RADIUS 0.9
);

-- Create optimized HNSW index for knowledge_concepts table
CREATE VECTOR INDEX idx_concepts_embedding_hnsw 
ON knowledge_concepts (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 32
  WITH TARGET ACCURACY 98
}
PARAMETERS (
  TYPE HNSW,
  EF_SEARCH 128,
  EF_CONSTRUCTION 200,
  MAX_SIMILARITY_SEARCH_RADIUS 0.9
);

-- Set maintenance parameters for HNSW index
ALTER INDEX idx_memories_embedding_hnsw PARAMETERS (
  SET MAX_INDEX_SIZE 10GB,
  SET INDEX_BUILD_PARALLELISM 8
);

ALTER INDEX idx_concepts_embedding_hnsw PARAMETERS (
  SET MAX_INDEX_SIZE 10GB,
  SET INDEX_BUILD_PARALLELISM 8
);

-- ============================================================================
-- 3. IVF INDEX CONFIGURATION
-- ============================================================================

-- Create IVF index for write-heavy workloads
-- DROP INDEX idx_memories_embedding_ivf;

CREATE VECTOR INDEX idx_memories_embedding_ivf 
ON memories (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 100
  WITH TARGET ACCURACY 90
}
PARAMETERS (
  TYPE IVF,
  NUMBER_LISTS 1024,
  MAX_LIST_SIZE 1000
);

-- Create IVF index for knowledge_concepts
CREATE VECTOR INDEX idx_concepts_embedding_ivf 
ON knowledge_concepts (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 100
  WITH TARGET ACCURACY 90
}
PARAMETERS (
  TYPE IVF,
  NUMBER_LISTS 1024,
  MAX_LIST_SIZE 1000
);

-- ============================================================================
-- 4. INDEX MAINTENANCE
-- ============================================================================

-- Rebuild fragmented indexes
ALTER INDEX idx_memories_embedding_hnsw REBUILD ONLINE;
ALTER INDEX idx_concepts_embedding_hnsw REBUILD ONLINE;

-- Update index statistics
EXEC DBMS_STATS.GATHER_INDEX_STATS('OPENCLAW', 'IDX_MEMEMBEDDING_HNSW');
EXEC DBMS_STATS.GATHER_INDEX_STATS('OPENCLAW', 'IDX_CONCEPTS_EMBEDDING_HNSW');

-- Check index usage
SELECT 
    index_name,
    table_name,
    used,
    last_used
FROM user_objects_usage
WHERE object_name LIKE 'IDX_%EMBEDDING%'
ORDER BY last_used DESC;

-- Monitor index health
SELECT 
    index_name,
    num_rows,
    leaf_blocks,
    clustering_factor,
    ROUND(leaf_blocks / num_rows * 100, 2) AS leaf_per_row_pct,
    CASE 
        WHEN clustering_factor < num_rows * 0.1 THEN 'HEALTHY'
        WHEN clustering_factor < num_rows * 0.3 THEN 'WARNING'
        ELSE 'CRITICAL'
    END AS health_status
FROM user_indexes
WHERE index_name LIKE 'IDX_%EMBEDDING%';

-- ============================================================================
-- 5. PERFORMANCE MONITORING
-- ============================================================================

-- Monitor vector search performance
SELECT 
    sql_id,
    sql_text,
    elapsed_time/1000000 AS elapsed_sec,
    cpu_time/1000000 AS cpu_sec,
    buffer_gets,
    disk_reads,
    executions,
    ROUND(elapsed_time / NULLIF(executions, 0) / 1000000, 3) AS avg_elapsed_sec
FROM V$SQL
WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
   OR sql_text LIKE '%embedding%'
ORDER BY elapsed_time DESC
FETCH FIRST 20 ROWS ONLY;

-- Check vector memory usage
SELECT 
    name,
    value/1024/1024 AS size_mb
FROM V$PARAMETER
WHERE name LIKE '%vector%'
   OR name LIKE '%vector_memory%';

-- Monitor I/O for vector operations
SELECT 
    event,
    total_waits,
    total_timeouts,
    time_waited_micro/1000000 AS time_waited_sec,
    ROUND(time_waited_micro / NULLIF(total_waits, 0) / 1000000, 3) AS avg_wait_sec
FROM V$SYSTEM_EVENT
WHERE event LIKE '%vector%'
   OR event LIKE '%embedding%'
ORDER BY time_waited_micro DESC;

-- ============================================================================
-- 6. RECOMMENDED CONFIGURATIONS
-- ============================================================================

-- Configuration for small datasets (< 100K vectors)
-- Use HNSW with lower parameters
/*
CREATE VECTOR INDEX idx_small_embedding 
ON table_name (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 16
  WITH TARGET ACCURACY 95
}
PARAMETERS (
  TYPE HNSW,
  EF_SEARCH 64,
  EF_CONSTRUCTION 100,
  MAX_SIMILARITY_SEARCH_RADIUS 0.8
);
*/

-- Configuration for medium datasets (100K - 1M vectors)
-- Use HNSW with moderate parameters
/*
CREATE VECTOR INDEX idx_medium_embedding 
ON table_name (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 32
  WITH TARGET ACCURACY 98
}
PARAMETERS (
  TYPE HNSW,
  EF_SEARCH 128,
  EF_CONSTRUCTION 200,
  MAX_SIMILARITY_SEARCH_RADIUS 0.9
);
*/

-- Configuration for large datasets (> 1M vectors)
-- Use IVF for better write performance
/*
CREATE VECTOR INDEX idx_large_embedding 
ON table_name (embedding_vector)
ORGANIZATION { NEIGHBORHOODS 
  DISTANCE TYPE cosine
  NEIGHBORS COUNT 100
  WITH TARGET ACCURACY 90
}
PARAMETERS (
  TYPE IVF,
  NUMBER_LISTS 4096,
  MAX_LIST_SIZE 2000
);
*/

-- ============================================================================
-- EXECUTION SCRIPT
-- ============================================================================

-- Run this to apply all optimizations
SET SERVEROUTPUT ON;
DECLARE
    l_count NUMBER;
BEGIN
    -- Check if indexes exist
    SELECT COUNT(*) INTO l_count
    FROM user_indexes
    WHERE index_name = 'IDX_MEMEMBEDDING_HNSW';
    
    IF l_count > 0 THEN
        DBMS_OUTPUT.PUT_LINE('HNSW index exists, rebuilding...');
        EXECUTE IMMEDIATE 'ALTER INDEX idx_memories_embedding_hnsw REBUILD ONLINE';
    ELSE
        DBMS_OUTPUT.PUT_LINE('Creating HNSW index...');
        EXECUTE IMMEDIATE '
            CREATE VECTOR INDEX idx_memories_embedding_hnsw 
            ON memories (embedding_vector)
            ORGANIZATION { NEIGHBORHOODS 
              DISTANCE TYPE cosine
              NEIGHBORS COUNT 32
              WITH TARGET ACCURACY 98
            }
            PARAMETERS (
              TYPE HNSW,
              EF_SEARCH 128,
              EF_CONSTRUCTION 200,
              MAX_SIMILARITY_SEARCH_RADIUS 0.9
            )';
    END IF;
    
    -- Gather statistics
    DBMS_OUTPUT.PUT_LINE('Gathering statistics...');
    EXECUTE IMMEDIATE 'EXEC DBMS_STATS.GATHER_INDEX_STATS(''OPENCLAW'', ''IDX_MEMEMBEDDING_HNSW'')';
    
    DBMS_OUTPUT.PUT_LINE('Vector index optimization completed successfully!');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error: ' || SQLERRM);
        RAISE;
END;
/

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify index creation
SELECT 
    index_name,
    index_type,
    table_name,
    status
FROM user_indexes
WHERE index_name LIKE 'IDX_%EMBEDDING%';

-- Test vector search performance
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
1. HNSW is recommended for most use cases (better query performance)
2. IVF is better for write-heavy workloads (faster updates)
3. Monitor clustering_factor regularly - rebuild if it degrades
4. Adjust EF_SEARCH based on your accuracy requirements
5. Use INDEX_BUILD_PARALLELISM for faster index creation
6. Monitor vector memory usage in V$PARAMETER
7. Test different configurations in staging before production
*/
