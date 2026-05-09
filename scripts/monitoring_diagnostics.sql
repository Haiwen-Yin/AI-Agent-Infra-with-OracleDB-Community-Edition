-- Oracle AI Database Memory System v1.0.0
-- Monitoring and Diagnostics Script
-- Author: 胖头鱼 🐟 (Haiwen Yin)
-- Version: v1.0.0 Production Release
-- Last Updated: 2024-12-19

-- ============================================================================
-- TABLE OF CONTENTS
-- ============================================================================
-- 1. System Health Check
-- 2. Memory System Statistics
-- 3. Vector Performance Monitoring
-- 4. Connection Monitoring
-- 5. I/O and Storage Monitoring
-- 6. Alert Thresholds
-- 7. Diagnostic Reports

-- ============================================================================
-- 1. SYSTEM HEALTH CHECK
-- ============================================================================

-- Overall database health
SELECT 
    instance_name,
    status,
    database_status,
    active_state
FROM v$instance;

-- Check database availability
SELECT 
    name,
    open_mode,
    log_mode,
    platform_name
FROM v$database;

-- Check resource usage
SELECT 
    resource_name,
    current_utilization,
    max_utilization,
    limit_value,
    ROUND(current_utilization / NULLIF(TO_NUMBER(limit_value), 0) * 100, 2) AS usage_pct
FROM v$instance_resource_usage
WHERE resource_name IN ('sessions', 'processes', 'ursors')
ORDER BY usage_pct DESC;

-- ============================================================================
-- 2. MEMORY SYSTEM STATISTICS
-- ============================================================================

-- Total memories and concepts
SELECT 
    'Total Memories' AS metric,
    COUNT(*) AS value
FROM memories
UNION ALL
SELECT 
    'Active Memories' AS metric,
    COUNT(*) AS value
FROM memories
WHERE status = 'active'
UNION ALL
SELECT 
    'Archived Memories' AS metric,
    COUNT(*) AS value
FROM memories
WHERE status = 'archived'
UNION ALL
SELECT 
    'Total Concepts' AS metric,
    COUNT(*) AS value
FROM knowledge_concepts
UNION ALL
SELECT 
    'Active Concepts' AS metric,
    COUNT(*) AS value
FROM knowledge_concepts
WHERE status = 'active'
UNION ALL
SELECT 
    'Total Relationships' AS metric,
    COUNT(*) AS value
FROM knowledge_relationships
UNION ALL
SELECT 
    'Active Relationships' AS metric,
    COUNT(*) AS value
FROM knowledge_relationships
WHERE status = 'active';

-- Memory type distribution
SELECT 
    memory_type,
    COUNT(*) AS cnt,
    ROUND(COUNT(*) / (SELECT COUNT(*) FROM memories) * 100, 2) AS percentage,
    MIN(created_at) AS earliest,
    MAX(created_at) AS latest
FROM memories
WHERE status = 'active'
GROUP BY memory_type
ORDER BY cnt DESC;

-- Concept type distribution
SELECT 
    concept_type,
    COUNT(*) AS cnt,
    ROUND(COUNT(*) / (SELECT COUNT(*) FROM knowledge_concepts) * 100, 2) AS percentage,
    MIN(created_at) AS earliest,
    MAX(created_at) AS latest
FROM knowledge_concepts
WHERE status = 'active'
GROUP BY concept_type
ORDER BY cnt DESC;

-- Relationship type distribution
SELECT 
    relationship_type,
    COUNT(*) AS cnt,
    ROUND(COUNT(*) / (SELECT COUNT(*) FROM knowledge_relationships) * 100, 2) AS percentage,
    AVG(strength) AS avg_strength
FROM knowledge_relationships
WHERE status = 'active'
GROUP BY relationship_type
ORDER BY cnt DESC;

-- ============================================================================
-- 3. VECTOR PERFORMANCE MONITORING
-- ============================================================================

-- Vector search performance statistics
SELECT 
    sql_id,
    sql_text,
    COUNT(*) AS execution_count,
    AVG(elapsed_time/1000000) AS avg_elapsed_sec,
    MAX(elapsed_time/1000000) AS max_elapsed_sec,
    SUM(elapsed_time/1000000) AS total_elapsed_sec,
    AVG(buffer_gets) AS avg_buffer_gets,
    MAX(buffer_gets) AS max_buffer_gets
FROM V$SQL
WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
GROUP BY sql_id, sql_text
ORDER BY total_elapsed_sec DESC
FETCH FIRST 20 ROWS ONLY;

-- Vector index statistics
SELECT 
    index_name,
    table_name,
    num_rows,
    leaf_blocks,
    clustering_factor,
    ROUND(leaf_blocks / NULLIF(num_rows, 0) * 100, 4) AS leaf_per_row_pct,
    CASE 
        WHEN clustering_factor < num_rows * 0.1 THEN 'EXCELLENT'
        WHEN clustering_factor < num_rows * 0.3 THEN 'GOOD'
        WHEN clustering_factor < num_rows * 0.5 THEN 'FAIR'
        ELSE 'POOR'
    END AS index_health
FROM user_indexes
WHERE index_name LIKE 'IDX_%EMBEDDING%'
ORDER BY index_name;

-- Vector memory usage
SELECT 
    name,
    value/1024/1024 AS size_mb,
    description
FROM V$PARAMETER
WHERE name LIKE '%vector%'
   OR name LIKE '%embedding%'
ORDER BY name;

-- ============================================================================
-- 4. CONNECTION MONITORING
-- ============================================================================

-- Active connections by user
SELECT 
    username,
    status,
    COUNT(*) AS session_count,
    MIN(logon_time) AS earliest_logon,
    MAX(last_active_time) AS latest_active
FROM V$SESSION
WHERE type = 'USER'
GROUP BY username, status
ORDER BY session_count DESC;

-- Connection pool status (for application servers)
SELECT 
    machine,
    program,
    COUNT(*) AS connection_count,
    SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) AS active_count,
    SUM(CASE WHEN status = 'INACTIVE' THEN 1 ELSE 0 END) AS inactive_count,
    MIN(logon_time) AS earliest_logon,
    MAX(last_active_time) AS latest_active
FROM V$SESSION
WHERE username = 'OPENCLAW'
GROUP BY machine, program
ORDER BY connection_count DESC;

-- Long-running sessions
SELECT 
    sid,
    serial#,
    username,
    machine,
    program,
    status,
    logon_time,
    last_active_time,
    ROUND((SYSDATE - logon_time) * 24 * 60, 2) AS logon_duration_min,
    ROUND((SYSDATE - last_active_time) * 24 * 60, 2) AS idle_duration_min,
    sql_id,
    event
FROM V$SESSION
WHERE username = 'OPENCLAW'
AND status = 'ACTIVE'
AND (SYSDATE - last_active_time) * 24 * 60 > 30  -- Idle for more than 30 minutes
ORDER BY idle_duration_min DESC;

-- Session resource usage
SELECT 
    s.sid,
    s.serial#,
    s.username,
    s.sql_id,
    t.name AS tablespace,
    s.temp_space_size/1024/1024 AS temp_used_mb,
    s PGA_USED_MEM/1024/1024 AS pga_used_mb,
    s PGA_ALLOC_MEM/1024/1024 AS pga_alloc_mb
FROM V$SESSION s
LEFT JOIN V$TABLESPACE t ON 1=1
WHERE s.username = 'OPENCLAW'
AND s.status = 'ACTIVE'
ORDER BY s.PGA_USED_MEM DESC
FETCH FIRST 10 ROWS ONLY;

-- ============================================================================
-- 5. I/O AND STORAGE MONITORING
-- ============================================================================

-- Tablespace usage
SELECT 
    df.tablespace_name,
    ROUND(df.total_bytes / 1024 / 1024 / 1024, 2) AS total_gb,
    ROUND((df.total_bytes - NVL(fs.free_bytes, 0)) / 1024 / 1024 / 1024, 2) AS used_gb,
    ROUND(NVL(fs.free_bytes, 0) / 1024 / 1024 / 1024, 2) AS free_gb,
    ROUND((df.total_bytes - NVL(fs.free_bytes, 0)) / df.total_bytes * 100, 2) AS used_pct
FROM (
    SELECT tablespace_name, SUM(bytes) AS total_bytes
    FROM dba_data_files
    GROUP BY tablespace_name
) df
LEFT JOIN (
    SELECT tablespace_name, SUM(bytes) AS free_bytes
    FROM dba_free_space
    GROUP BY tablespace_name
) fs ON df.tablespace_name = fs.tablespace_name
WHERE df.tablespace_name LIKE '%MEMORY%'
   OR df.tablespace_name LIKE '%DATA%'
ORDER BY used_pct DESC;

-- I/O statistics
SELECT 
    f.file_name,
    f.tablespace_name,
    s.phyrds AS physical_reads,
    s.phywrts AS physical_writes,
    s.readtim/100 AS read_time_sec,
    s.writetim/100 AS write_time_sec,
    ROUND(s.phyrds / NULLIF(s.readtim/100, 0), 2) AS reads_per_sec,
    ROUND(s.phywrts / NULLIF(s.writetim/100, 0), 2) AS writes_per_sec
FROM V$FILESTAT s
JOIN dba_data_files f ON s.file# = f.file_id
WHERE f.tablespace_name LIKE '%MEMORY%'
ORDER BY s.phyrds DESC;

-- Slow I/O operations
SELECT 
    event,
    total_waits,
    total_timeouts,
    time_waited_micro/1000000 AS time_waited_sec,
    ROUND(time_waited_micro / NULLIF(total_waits, 0) / 1000000, 3) AS avg_wait_sec
FROM V$SYSTEM_EVENT
WHERE event LIKE '%db file%'
   OR event LIKE '%log file%'
   OR event LIKE '%control file%'
ORDER BY time_waited_micro DESC
FETCH FIRST 10 ROWS ONLY;

-- ============================================================================
-- 6. ALERT THRESHOLDS
-- ============================================================================

-- Check for critical conditions
DECLARE
    l_memory_count NUMBER;
    l_concept_count NUMBER;
    l_relationship_count NUMBER;
    l_slow_queries NUMBER;
    l_high_connections NUMBER;
BEGIN
    -- Memory system thresholds
    SELECT COUNT(*) INTO l_memory_count FROM memories WHERE status = 'active';
    SELECT COUNT(*) INTO l_concept_count FROM knowledge_concepts WHERE status = 'active';
    SELECT COUNT(*) INTO l_relationship_count FROM knowledge_relationships WHERE status = 'active';
    
    -- Performance thresholds
    SELECT COUNT(*) INTO l_slow_queries
    FROM V$SQL
    WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
    AND elapsed_time > 10000000;  -- > 10 seconds
    
    -- Connection thresholds
    SELECT COUNT(*) INTO l_high_connections
    FROM V$SESSION
    WHERE username = 'OPENCLAW'
    AND status = 'ACTIVE';
    
    -- Output alerts
    DBMS_OUTPUT.PUT_LINE('=== MEMORY SYSTEM ALERTS ===');
    
    IF l_memory_count < 100 THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: Low memory count (' || l_memory_count || ')');
    END IF;
    
    IF l_slow_queries > 10 THEN
        DBMS_OUTPUT.PUT_LINE('CRITICAL: High number of slow queries (' || l_slow_queries || ')');
    END IF;
    
    IF l_high_connections > 50 THEN
        DBMS_OUTPUT.PUT_LINE('WARNING: High connection count (' || l_high_connections || ')');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('=== SUMMARY ===');
    DBMS_OUTPUT.PUT_LINE('Memories: ' || l_memory_count);
    DBMS_OUTPUT.PUT_LINE('Concepts: ' || l_concept_count);
    DBMS_OUTPUT.PUT_LINE('Relationships: ' || l_relationship_count);
    DBMS_OUTPUT.PUT_LINE('Slow Queries: ' || l_slow_queries);
    DBMS_OUTPUT.PUT_LINE('Active Connections: ' || l_high_connections);
END;
/

-- ============================================================================
-- 7. DIAGNOSTIC REPORTS
-- ============================================================================

-- Generate comprehensive diagnostic report
SELECT 
    '=== MEMORY SYSTEM DIAGNOSTIC REPORT ===' AS report_title,
    TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS') AS report_time
FROM DUAL;

-- Table statistics
SELECT 
    'TABLE STATISTICS' AS section,
    table_name,
    num_rows,
    blocks,
    last_analyzed,
    ROUND(AVG_ROW_LEN, 2) AS avg_row_len
FROM user_tables
WHERE table_name IN ('MEMORIES', 'KNOWLEDGE_CONCEPTS', 'KNOWLEDGE_RELATIONSHIPS')
ORDER BY table_name;

-- Index statistics
SELECT 
    'INDEX STATISTICS' AS section,
    index_name,
    table_name,
    num_rows,
    leaf_blocks,
    clustering_factor,
    last_analyzed
FROM user_indexes
WHERE table_name IN ('MEMORIES', 'KNOWLEDGE_CONCEPTS', 'KNOWLEDGE_RELATIONSHIPS')
ORDER BY table_name, index_name;

-- Constraint statistics
SELECT 
    'CONSTRAINT STATISTICS' AS section,
    constraint_name,
    table_name,
    constraint_type,
    status,
    validated
FROM user_constraints
WHERE table_name IN ('MEMORIES', 'KNOWLEDGE_CONCEPTS', 'KNOWLEDGE_RELATIONSHIPS')
ORDER BY table_name, constraint_name;

-- Object statistics
SELECT 
    'OBJECT STATISTICS' AS section,
    object_type,
    COUNT(*) AS object_count,
    MAX(last_ddl_time) AS latest_ddl
FROM user_objects
WHERE object_name LIKE '%MEMORY%'
   OR object_name LIKE '%KNOWLEDGE%'
GROUP BY object_type
ORDER BY object_type;

-- ============================================================================
-- PERFORMANCE BASELINE
-- ============================================================================

-- Capture current performance baseline
CREATE TABLE IF NOT EXISTS performance_baseline (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    capture_date TIMESTAMP DEFAULT SYSTIMESTAMP,
    metric_name VARCHAR2(100),
    metric_value NUMBER,
    description VARCHAR2(500)
);

-- Insert baseline metrics
INSERT INTO performance_baseline (metric_name, metric_value, description)
SELECT 'total_memories', COUNT(*), 'Total active memories'
FROM memories WHERE status = 'active';

INSERT INTO performance_baseline (metric_name, metric_value, description)
SELECT 'total_concepts', COUNT(*), 'Total active concepts'
FROM knowledge_concepts WHERE status = 'active';

INSERT INTO performance_baseline (metric_name, metric_value, description)
SELECT 'total_relationships', COUNT(*), 'Total active relationships'
FROM knowledge_relationships WHERE status = 'active';

INSERT INTO performance_baseline (metric_name, metric_value, description)
SELECT 'slow_queries', COUNT(*), 'Queries taking > 10 seconds'
FROM V$SQL
WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
AND elapsed_time > 10000000;

INSERT INTO performance_baseline (metric_name, metric_value, description)
SELECT 'active_connections', COUNT(*), 'Active sessions'
FROM V$SESSION
WHERE username = 'OPENCLAW'
AND status = 'ACTIVE';

COMMIT;

-- ============================================================================
-- ALERT NOTIFICATION
-- ============================================================================

-- Create alert procedure
CREATE OR REPLACE PROCEDURE check_memory_system_alerts AS
    l_memory_count NUMBER;
    l_slow_queries NUMBER;
    l_high_connections NUMBER;
    l_alert_message VARCHAR2(4000);
BEGIN
    -- Check memory count
    SELECT COUNT(*) INTO l_memory_count 
    FROM memories WHERE status = 'active';
    
    -- Check slow queries
    SELECT COUNT(*) INTO l_slow_queries
    FROM V$SQL
    WHERE sql_text LIKE '%VECTOR_SIMILARITY%'
    AND elapsed_time > 10000000;
    
    -- Check connections
    SELECT COUNT(*) INTO l_high_connections
    FROM V$SESSION
    WHERE username = 'OPENCLAW'
    AND status = 'ACTIVE';
    
    -- Build alert message
    l_alert_message := 'Memory System Alert: ' || 
        'Memories=' || l_memory_count || 
        ', SlowQueries=' || l_slow_queries ||
        ', Connections=' || l_high_connections;
    
    -- Log alert (you can extend this to send emails/notifications)
    INSERT INTO alert_log (alert_time, alert_message, severity)
    VALUES (SYSTIMESTAMP, l_alert_message, 
        CASE 
            WHEN l_slow_queries > 10 THEN 'CRITICAL'
            WHEN l_high_connections > 50 THEN 'WARNING'
            ELSE 'INFO'
        END);
    
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error in alert check: ' || SQLERRM);
END;
/

-- Create alert log table
CREATE TABLE IF NOT EXISTS alert_log (
    id NUMBER GENERATED ALWAYS AS IDENTITY,
    alert_time TIMESTAMP DEFAULT SYSTIMESTAMP,
    alert_message VARCHAR2(4000),
    severity VARCHAR2(20),
    acknowledged VARCHAR2(1) DEFAULT 'N'
);

-- ============================================================================
-- SCHEDULED MONITORING
-- ============================================================================

-- Create monitoring job
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_SYSTEM_MONITOR',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN check_memory_system_alerts; END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY;INTERVAL=5',
        enabled => TRUE,
        auto_drop => FALSE,
        comments => 'Monitor memory system health every 5 minutes'
    );
END;
/

-- ============================================================================
-- END OF SCRIPT
-- ============================================================================

/*
NOTES:
1. Run this script during maintenance windows
2. Review alert thresholds based on your environment
3. Customize notification methods (email, SMS, etc.)
4. Archive old performance baseline data regularly
5. Adjust monitoring frequency based on workload
6. Test monitoring procedures in staging first
*/
