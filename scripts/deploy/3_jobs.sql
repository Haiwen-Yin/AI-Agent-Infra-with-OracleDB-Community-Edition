-- Oracle Memory System v2.3.2 - Phase 3: Scheduler Jobs

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

BEGIN
    DBMS_SCHEDULER.DROP_JOB('DORMANT_AGENT_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'DORMANT_AGENT_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'DECLARE l_timeout_min NUMBER; l_count NUMBER; BEGIN SELECT NVL(TO_NUMBER(CONFIG_VALUE), 30) INTO l_timeout_min FROM SYSTEM_CONFIG WHERE CONFIG_KEY = ''dormant_timeout_min''; UPDATE AGENT_REGISTRY SET STATUS = ''DORMANT'', CURRENT_USER_ID = NULL, UPDATED_AT = SYSTIMESTAMP WHERE STATUS = ''ACTIVE'' AND LAST_ACTIVE_AT IS NOT NULL AND LAST_ACTIVE_AT < SYSTIMESTAMP - NUMTODSINTERVAL(l_timeout_min, ''MINUTE''); l_count := SQL%ROWCOUNT; COMMIT; IF l_count > 0 THEN INSERT INTO SYSTEM_LOGS (LOG_ID, LOG_LEVEL, SOURCE, MESSAGE, CREATED_AT) VALUES (SYSTEM_LOGS_SEQ.NEXTVAL, ''INFO'', ''DORMANT_AGENT_JOB'', ''Marked '' || l_count || '' agent(s) as dormant (timeout: '' || l_timeout_min || '' min)'', SYSTIMESTAMP); COMMIT; END IF; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=30',
        enabled         => TRUE
    );
END;
/

BEGIN
    DBMS_SCHEDULER.DROP_JOB('CREDENTIAL_CLEANUP_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'CREDENTIAL_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'DECLARE l_soft_expired NUMBER; l_deleted NUMBER; BEGIN UPDATE AGENT_CREDENTIALS SET IS_ACTIVE = ''N'', UPDATED_AT = SYSTIMESTAMP WHERE IS_ACTIVE = ''Y'' AND EXPIRES_AT IS NOT NULL AND EXPIRES_AT < SYSTIMESTAMP; l_soft_expired := SQL%ROWCOUNT; COMMIT; DELETE FROM AGENT_CREDENTIALS WHERE IS_ACTIVE = ''N'' OR (EXPIRES_AT IS NOT NULL AND EXPIRES_AT < SYSTIMESTAMP); l_deleted := SQL%ROWCOUNT; COMMIT; IF l_soft_expired > 0 OR l_deleted > 0 THEN INSERT INTO SYSTEM_LOGS (LOG_ID, LOG_LEVEL, SOURCE, MESSAGE, CREATED_AT) VALUES (SYSTEM_LOGS_SEQ.NEXTVAL, ''INFO'', ''CREDENTIAL_CLEANUP_JOB'', ''Soft-expired: '' || l_soft_expired || '', Deleted: '' || l_deleted, SYSTIMESTAMP); COMMIT; END IF; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0; BYSECOND=0',
        enabled         => TRUE
    );
END;
/

-- EMBEDDING_GENERATION_JOB [NEW v2.3.2]
BEGIN
    DBMS_SCHEDULER.DROP_JOB('EMBEDDING_GENERATION_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'EMBEDDING_GENERATION_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN EMBEDDING_MANAGER.batch_embed_entities(''MEMORY'', 50); EMBEDDING_MANAGER.batch_embed_entities(''KNOWLEDGE'', 50); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; INTERVAL=2',
        enabled         => TRUE,
        comments        => 'Auto-embed new MEMORY and KNOWLEDGE entities (v2.3.2)'
    );
END;
/

SELECT JOB_NAME, STATE, REPEAT_INTERVAL
FROM USER_SCHEDULER_JOBS
WHERE JOB_NAME IN (
    'MEMORY_FUSION_JOB', 'KNOWLEDGE_EXTRACTION_JOB', 'KNOWLEDGE_REVIEW_JOB',
    'SESSION_CLEANUP_JOB', 'ACCESS_LOG_PURGE_JOB', 'ENTITY_ARCHIVE_JOB', 'COLLAB_EXPIRY_JOB',
    'WORKSPACE_CLEANUP_JOB', 'STALE_WORKSPACE_DETECT_JOB',
    'DORMANT_AGENT_JOB', 'CREDENTIAL_CLEANUP_JOB', 'EMBEDDING_GENERATION_JOB'
)
ORDER BY JOB_NAME;

PROMPT Oracle Memory System v2.3.2 - Phase 3: Scheduler Jobs Complete (12 jobs)
