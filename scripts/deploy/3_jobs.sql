-- ============================================================
-- Oracle Memory System v2.0.0 - Phase 3: Scheduler Jobs
-- ============================================================

WHENEVER SQLERROR CONTINUE;
WHENEVER OSERROR CONTINUE;

-- ============================================================
-- Job 1: Memory Fusion - runs daily at 02:00
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('MEMORY_FUSION_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'MEMORY_FUSION_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN MEMORY_FUSION_ENGINE.fuse_similar_memories(p_category=>NULL, p_min_similarity=>0.85, p_dry_run=>''N''); MEMORY_FUSION_ENGINE.decay_old_memories(p_days_threshold=>90, p_decay_factor=>0.5); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Daily memory fusion and priority decay'
    );
END;
/

-- ============================================================
-- Job 2: Knowledge Extraction - runs daily at 03:00
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('KNOWLEDGE_EXTRACTION_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'KNOWLEDGE_EXTRACTION_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN MEMORY_FUSION_ENGINE.extract_knowledge_from_memories(p_category=>NULL, p_min_count=>3); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Daily knowledge extraction from memory patterns'
    );
END;
/

-- ============================================================
-- Job 3: Session Cleanup - runs every 30 minutes
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('SESSION_CLEANUP_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'SESSION_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN AGENT_PERMISSION_MANAGER.cleanup_expired_sessions; SESSION_CLEANUP.purge_inactive_sessions; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=30',
        enabled         => TRUE,
        comments        => 'Cleanup expired sessions every 30 minutes'
    );
END;
/

-- ============================================================
-- Job 4: Access Log Purge - runs weekly Sunday 04:00
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('ACCESS_LOG_PURGE_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'ACCESS_LOG_PURGE_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN SESSION_CLEANUP.purge_access_logs(p_days_to_keep=>90); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Weekly purge of access logs older than 90 days'
    );
END;
/

-- ============================================================
-- Job 5: Tag Count Update - runs daily at 01:00
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('TAG_COUNT_UPDATE_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'TAG_COUNT_UPDATE_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN SESSION_CLEANUP.update_tag_counts; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=1; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Daily update of tag usage counts'
    );
END;
/

-- ============================================================
-- Job 6: Collaboration Expiry - runs daily at 00:30
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('COLLAB_EXPIRY_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'COLLAB_EXPIRY_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN AGENT_PERMISSION_MANAGER.process_collaboration_requests; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=0; BYMINUTE=30; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Daily expiry of stale collaboration requests'
    );
END;
/

-- ============================================================
-- Job 7: Entity Archival - runs weekly Sunday 05:00
-- ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('ENTITY_ARCHIVE_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'ENTITY_ARCHIVE_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN SESSION_CLEANUP.archive_old_entities(p_days_threshold=>180); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=5; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE,
        comments        => 'Weekly archival of low-priority memories older than 180 days'
    );
END;
/

-- ============================================================
-- Verify all jobs
-- ============================================================

SELECT JOB_NAME, STATE, REPEAT_INTERVAL, LAST_START_DATE, NEXT_RUN_DATE
FROM USER_SCHEDULER_JOBS
WHERE JOB_NAME IN (
    'MEMORY_FUSION_JOB', 'KNOWLEDGE_EXTRACTION_JOB', 'SESSION_CLEANUP_JOB',
    'ACCESS_LOG_PURGE_JOB', 'TAG_COUNT_UPDATE_JOB', 'COLLAB_EXPIRY_JOB', 'ENTITY_ARCHIVE_JOB'
)
ORDER BY JOB_NAME;

-- ============================================================
-- End Phase 3: Jobs
-- ============================================================
