-- Oracle Memory System v2.2.0 - Phase 3: Scheduler Jobs

WHENEVER SQLERROR CONTINUE;

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
        job_action      => 'BEGIN MEMORY_FUSION_ENGINE.fuse_similar_memories; MEMORY_FUSION_ENGINE.decay_old_memories; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

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
        job_action      => 'BEGIN MEMORY_FUSION_ENGINE.extract_knowledge_from_memories; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

BEGIN
    DBMS_SCHEDULER.DROP_JOB('KNOWLEDGE_REVIEW_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'KNOWLEDGE_REVIEW_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'DECLARE CURSOR c_entities IS SELECT entity_id FROM knowledge_entities; BEGIN FOR r IN c_entities LOOP KNOWLEDGE_BASE_API.schedule_review(r.entity_id); END LOOP; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=6; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

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
        enabled         => TRUE
    );
END;
/

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
        job_action      => 'BEGIN SESSION_CLEANUP.purge_access_logs(90); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

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
        job_action      => 'BEGIN SESSION_CLEANUP.archive_old_entities(180); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=5; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

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
        enabled         => TRUE
    );
END;
/

BEGIN
    DBMS_SCHEDULER.DROP_JOB('WORKSPACE_CLEANUP_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'WORKSPACE_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN WORKSPACE_MANAGER.cleanup_abandoned(30); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

BEGIN
    DBMS_SCHEDULER.DROP_JOB('STALE_WORKSPACE_DETECT_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'STALE_WORKSPACE_DETECT_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN UPDATE WORKSPACES SET STATUS = ''PAUSED'', UPDATED_AT = SYSTIMESTAMP WHERE STATUS = ''ACTIVE'' AND CURRENT_SESSION_ID IS NOT NULL AND NOT EXISTS (SELECT 1 FROM AGENT_SESSION s WHERE s.SESSION_ID = WORKSPACES.CURRENT_SESSION_ID AND s.IS_ACTIVE = ''Y''); COMMIT; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

SELECT JOB_NAME, STATE, REPEAT_INTERVAL
FROM USER_SCHEDULER_JOBS
WHERE JOB_NAME IN (
    'MEMORY_FUSION_JOB', 'KNOWLEDGE_EXTRACTION_JOB', 'KNOWLEDGE_REVIEW_JOB',
    'SESSION_CLEANUP_JOB', 'ACCESS_LOG_PURGE_JOB', 'ENTITY_ARCHIVE_JOB', 'COLLAB_EXPIRY_JOB',
    'WORKSPACE_CLEANUP_JOB', 'STALE_WORKSPACE_DETECT_JOB'
)
ORDER BY JOB_NAME;
