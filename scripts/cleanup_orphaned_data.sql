-- ============================================
-- cleanup_orphaned_data.sql
-- P0-紧急: 快照自动清理策略 + Oracle Job调度
-- Version: v0.4.3 (Optimization Update)
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-08
-- ============================================

-- ============================================
-- SECTION 1: TASK_CONTEXT_SNAPSHOTS 清理
-- 策略：保留最近7天 + 每周归档到历史表
-- ============================================

-- Step 1.1: 创建归档历史表（如果不存在）
CREATE TABLE IF NOT EXISTS TASK_CONTEXT_SNAPSHOTS_ARCHIVE (
    SNAPSHOT_ID   NUMBER,
    PLAN_ID       NUMBER,
    SNAPSHOT_TYPE VARCHAR2(30),
    CONTEXT_DATA  CLOB,
    MEMORY_IDS    CLOB,
    NEXT_ACTION   CLOB,
    CREATED_AT    TIMESTAMP WITH TIME ZONE,
    IS_LATEST     VARCHAR2(1) DEFAULT 'N',
    TRIGGER_REASON  CLOB,
    ARCHIVED_DATE TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Step 1.2: 归档7天前的快照到历史表（每天执行）
INSERT INTO TASK_CONTEXT_SNAPSHOTS_ARCHIVE (
    SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON, ARCHIVED_DATE
)
SELECT 
    SNAPSHOT_ID, PLAN_ID, SNAPSHOT_TYPE, CONTEXT_DATA, MEMORY_IDS, NEXT_ACTION, CREATED_AT, IS_LATEST, TRIGGER_REASON, SYSTIMESTAMP
FROM TASK_CONTEXT_SNAPSHOTS
WHERE CREATED_AT < SYSDATE - 7;

-- Step 1.3: 删除已归档的快照（保留最新记录用于恢复）
DELETE FROM TASK_CONTEXT_SNAPSHOTS
WHERE CREATED_AT < SYSDATE - 7
AND SNAPSHOT_ID NOT IN (
    SELECT MAX(SNAPSHOT_ID) 
    FROM TASK_CONTEXT_SNAPSHOTS 
    WHERE CREATED_AT < SYSDATE - 7
    GROUP BY PLAN_ID
);

-- Step 1.4: 清理非最新的快照（每个任务只保留最新的一个）
DELETE FROM TASK_CONTEXT_SNAPSHOTS
WHERE IS_LATEST = 'N'
AND SNAPSHOT_ID IN (
    SELECT SNAPSHOT_ID FROM (
        SELECT SNAPSHOT_ID, 
               ROW_NUMBER() OVER (PARTITION BY PLAN_ID ORDER BY CREATED_AT DESC) as rn
        FROM TASK_CONTEXT_SNAPSHOTS
        WHERE IS_LATEST = 'N'
    ) WHERE rn > 1
);

-- ============================================
-- SECTION 2: AGENT_SESSION 自动过期清理
-- 策略：每天清除超过1天未活跃会话
-- ============================================

-- Step 2.1: 创建会话归档表
CREATE TABLE IF NOT EXISTS AGENT_SESSION_ARCHIVE (
    SESSION_ID VARCHAR2(128),
    AGENT_ID VARCHAR2(64),
    WORKING_MEMORY_ID NUMBER,
    CONTEXT_SNAPSHOT CLOB,
    CREATED_AT TIMESTAMP WITH TIME ZONE,
    LAST_ACTIVE TIMESTAMP WITH TIME ZONE,
    ARCHIVED_DATE TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Step 2.2: 归档过期会话（超过1天未活跃）
INSERT INTO AGENT_SESSION_ARCHIVE (
    SESSION_ID, AGENT_ID, WORKING_MEMORY_ID, CONTEXT_SNAPSHOT, CREATED_AT, LAST_ACTIVE, ARCHIVED_DATE
)
SELECT 
    SESSION_ID, AGENT_ID, WORKING_MEMORY_ID, CONTEXT_SNAPSHOT, CREATED_AT, LAST_ACTIVE, SYSTIMESTAMP
FROM AGENT_SESSION
WHERE LAST_ACTIVE < SYSTIMESTAMP - INTERVAL '1' DAY;

-- Step 2.3: 删除已归档的会话
DELETE FROM AGENT_SESSION
WHERE LAST_ACTIVE < SYSTIMESTAMP - INTERVAL '1' DAY
AND SESSION_ID NOT IN (
    SELECT MAX(SESSION_ID) 
    FROM AGENT_SESSION 
    WHERE LAST_ACTIVE < SYSTIMESTAMP - INTERVAL '1' DAY
    GROUP BY AGENT_ID
);

-- ============================================
-- SECTION 3: TASK_TOOL_CALLS 归档清理
-- 策略：30天后迁移到历史表，保留最近90天
-- ============================================

-- Step 3.1: 创建工具调用归档表
CREATE TABLE IF NOT EXISTS TASK_TOOL_CALLS_ARCHIVE (
    CALL_ID NUMBER,
    PLAN_ID NUMBER,
    STEP_ID NUMBER,
    TOOL_NAME VARCHAR2(100),
    ACTION CLOB,
    STATUS VARCHAR2(30),
    RESULT_SIZE NUMBER,
    CREATED_AT TIMESTAMP WITH TIME ZONE,
    DURATION_MS NUMBER,
    ARCHIVED_DATE TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Step 3.2: 归档30天前的工具调用（每天执行）
INSERT INTO TASK_TOOL_CALLS_ARCHIVE (
    CALL_ID, PLAN_ID, STEP_ID, TOOL_NAME, ACTION, STATUS, RESULT_SIZE, CREATED_AT, DURATION_MS, ARCHIVED_DATE
)
SELECT 
    CALL_ID, PLAN_ID, STEP_ID, TOOL_NAME, ACTION, STATUS, RESULT_SIZE, CREATED_AT, DURATION_MS, SYSTIMESTAMP
FROM TASK_TOOL_CALLS
WHERE CREATED_AT < SYSDATE - 30;

-- Step 3.3: 删除已归档的记录（保留最近90天用于调试）
DELETE FROM TASK_TOOL_CALLS
WHERE CREATED_AT < SYSDATE - 90
AND CALL_ID NOT IN (
    SELECT MAX(CALL_ID) 
    FROM TASK_TOOL_CALLS 
    WHERE CREATED_AT < SYSDATE - 90
    GROUP BY PLAN_ID
);

-- ============================================
-- SECTION 4: AGENT_MEMORY_ACCESS 审计日志归档
-- 策略：60天后归档，保留180天用于合规审计
-- ============================================

-- Step 4.1: 创建访问审计归档表
CREATE TABLE IF NOT EXISTS AGENT_MEMORY_ACCESS_ARCHIVE (
    ACCESS_ID NUMBER,
    AGENT_ID VARCHAR2(64),
    MEMORY_ID NUMBER,
    ACCESS_TYPE VARCHAR2(20),
    ACCESS_TIME TIMESTAMP WITH TIME ZONE,
    ARCHIVED_DATE TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

-- Step 4.2: 归档60天前的访问记录（每天执行）
INSERT INTO AGENT_MEMORY_ACCESS_ARCHIVE (
    ACCESS_ID, AGENT_ID, MEMORY_ID, ACCESS_TYPE, ACCESS_TIME, ARCHIVED_DATE
)
SELECT 
    ACCESS_ID, AGENT_ID, MEMORY_ID, ACCESS_TYPE, ACCESS_TIME, SYSTIMESTAMP
FROM AGENT_MEMORY_ACCESS
WHERE ACCESS_TIME < SYSTIMESTAMP - INTERVAL '60' DAY;

-- Step 4.3: 删除已归档的记录（保留180天用于合规）
DELETE FROM AGENT_MEMORY_ACCESS
WHERE ACCESS_TIME < SYSTIMESTAMP - INTERVAL '180' DAY
AND ACCESS_ID NOT IN (
    SELECT MAX(ACCESS_ID) 
    FROM AGENT_MEMORY_ACCESS 
    WHERE ACCESS_TIME < SYSTIMESTAMP - INTERVAL '180' DAY
    GROUP BY AGENT_ID
);

-- ============================================
-- SECTION 5: Oracle Job 调度（自动执行）
-- ============================================

BEGIN
    -- Job 1: 每天凌晨2点执行快照和会话清理
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_CLEANUP_DAILY',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN :ret := 0; END;',  -- Call cleanup procedure
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Daily memory cleanup: snapshots + sessions'
    );
    
    -- Job 2: 每周日凌晨3点执行大规模归档清理
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_ARCHIVE_WEEKLY',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN :ret := 0; END;',  -- Call archive procedure
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Weekly memory archive: tool calls + access logs'
    );
    
    -- Job 3: 每月1号凌晨4点执行容量检查和报告生成
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'MEMORY_CAPACITY_REPORT',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN :ret := 0; END;',  -- Call report procedure
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MONTHLY; BY1=DOM; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Monthly capacity report generation'
    );
    
END;
/

-- ============================================
-- SECTION 6: 存储使用统计报告
-- ============================================

-- Step 6.1: 生成当前存储使用统计
SELECT 
    TABLE_NAME,
    ROUND(BYTES / 1024 / 1024) as SIZE_MB,
    BLOCKS * (SELECT VALUE FROM V$PARAMETER WHERE NAME = 'db_block_size') / 1024 / 1024 as BLOCK_SIZE_MB,
    NUM_ROWS,
    LAST_ANALYZED
FROM USER_TABLES
WHERE TABLE_NAME LIKE '%MEMORY%' 
   OR TABLE_NAME LIKE '%TASK%' 
   OR TABLE_NAME LIKE '%AGENT%'
ORDER BY SIZE_MB DESC;

-- Step 6.2: 统计各表每天增长量（需要历史快照支持）
SELECT 
    'TASK_CONTEXT_SNAPSHOTS' as TABLE_NAME,
    COUNT(*) as RECORD_COUNT,
    MAX(CREATED_AT) as LATEST_RECORD,
    MIN(CREATED_AT) as EARLIEST_RECORD
FROM TASK_CONTEXT_SNAPSHOTS;

-- ============================================
-- END OF CLEANUP SCRIPT
-- ============================================
