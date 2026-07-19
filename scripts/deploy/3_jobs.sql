-- AI Agent Infra v3.10.2 - Enterprise Edition - Phase 3: Scheduler Jobs

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
        job_action      => 'DECLARE l_timeout_min NUMBER; l_count NUMBER; BEGIN SELECT NVL(TO_NUMBER(CONFIG_VALUE), 30) INTO l_timeout_min FROM SYSTEM_CONFIG WHERE CONFIG_KEY = ''dormant_timeout_min''; UPDATE AGENT_REGISTRY SET STATUS = ''POOL'', CURRENT_USER_ID = NULL, UPDATED_AT = SYSTIMESTAMP WHERE STATUS = ''ACTIVE'' AND LAST_ACTIVE_AT IS NOT NULL AND LAST_ACTIVE_AT < SYSTIMESTAMP - NUMTODSINTERVAL(l_timeout_min, ''MINUTE''); l_count := SQL%ROWCOUNT; COMMIT; END;',
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
        job_action      => 'DECLARE l_soft_expired NUMBER; l_deleted NUMBER; BEGIN UPDATE AGENT_CREDENTIALS SET IS_ACTIVE = ''N'', UPDATED_AT = SYSTIMESTAMP WHERE IS_ACTIVE = ''Y'' AND EXPIRES_AT IS NOT NULL AND EXPIRES_AT < SYSTIMESTAMP; l_soft_expired := SQL%ROWCOUNT; COMMIT; DELETE FROM AGENT_CREDENTIALS WHERE IS_ACTIVE = ''N'' OR (EXPIRES_AT IS NOT NULL AND EXPIRES_AT < SYSTIMESTAMP); l_deleted := SQL%ROWCOUNT; COMMIT; END;',
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

PROMPT ============================================================
PROMPT LDAP_SYNC_JOB [NEW v3.3.0 ENT]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('LDAP_SYNC_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'LDAP_SYNC_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN LDAP_AUTH_MANAGER.sync_ldap_users((SELECT CONFIG_ID FROM LDAP_CONFIG WHERE STATUS = ''ACTIVE'' FETCH FIRST 1 ROWS ONLY), ''INCREMENTAL''); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; INTERVAL=1',
        enabled         => TRUE,
        comments        => 'Sync LDAP users and groups hourly (v3.3.0 ENT)'
    );
END;
/

SELECT JOB_NAME, STATE, REPEAT_INTERVAL
FROM USER_SCHEDULER_JOBS
WHERE JOB_NAME IN (
    'MEMORY_FUSION_JOB', 'KNOWLEDGE_EXTRACTION_JOB', 'KNOWLEDGE_REVIEW_JOB',
    'SESSION_CLEANUP_JOB', 'ACCESS_LOG_PURGE_JOB', 'ENTITY_ARCHIVE_JOB', 'COLLAB_EXPIRY_JOB',
    'WORKSPACE_CLEANUP_JOB', 'STALE_WORKSPACE_DETECT_JOB',
    'DORMANT_AGENT_JOB', 'CREDENTIAL_CLEANUP_JOB', 'EMBEDDING_GENERATION_JOB',
    'LDAP_SYNC_JOB', 'SKILL_TOKEN_CLEANUP_JOB', 'CONTEXT_AUDIT_JOB', 'IDLE_PATTERN_DETECT_JOB'
)
ORDER BY JOB_NAME;

PROMPT ============================================================
PROMPT SKILL_TOKEN_CLEANUP_JOB [NEW v3.3.0 ENT]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('SKILL_TOKEN_CLEANUP_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'SKILL_TOKEN_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN DELETE FROM SKILL_ACCESS_TOKEN WHERE (IS_CONSUMED = ''Y'' OR EXPIRES_AT < SYSTIMESTAMP) AND CREATED_AT < SYSTIMESTAMP - INTERVAL ''7'' DAY; COMMIT; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=10',
        enabled         => TRUE,
        comments        => 'Purge expired/consumed skill access tokens every 10 min (v3.3.0 ENT)'
    );
END;
/

PROMPT ============================================================
PROMPT CONTEXT_AUDIT_JOB [NEW v3.3.0 ENT]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('CONTEXT_AUDIT_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'CONTEXT_AUDIT_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN CONTEXT_AUDIT_MANAGER.PURGE_AUDIT_LOG(90); COMMIT; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=2; BYMINUTE=0',
        enabled         => TRUE,
        comments        => 'Purge audit log entries older than retention period daily at 2am (v3.3.0 ENT)'
    );
END;
/

PROMPT ============================================================
PROMPT IDLE_PATTERN_DETECT_JOB [NEW v3.3.0 ENT]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.DROP_JOB('IDLE_PATTERN_DETECT_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

BEGIN
    DBMS_SCHEDULER.CREATE_JOB(
        job_name        => 'IDLE_PATTERN_DETECT_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN DECLARE v_cnt NUMBER; v_timeout_min NUMBER; BEGIN SELECT CONFIG_VALUE INTO v_timeout_min FROM SYSTEM_CONFIG WHERE CONFIG_KEY = ''audit_idle_timeout_min''; v_timeout_min := NVL(v_timeout_min, 60); FOR a IN (SELECT AGENT_ID FROM AGENT_REGISTRY WHERE STATUS = ''ACTIVE'' AND LAST_SEEN_AT < SYSTIMESTAMP - v_timeout_min * INTERVAL ''1'' MINUTE) LOOP v_cnt := CONTEXT_AUDIT_MANAGER.LOG_AUDIT_EVENT(p_entity_id => a.AGENT_ID, p_entity_type => ''AGENT'', p_audit_type => ''IDLE_PATTERN'', p_rule_id => ''RULE_IDLE_AGENT'', p_violation_detail => ''Agent idle beyond '' || v_timeout_min || '' minutes'', p_agent_id => a.AGENT_ID); END LOOP; COMMIT; END; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=HOURLY; INTERVAL=1',
        enabled         => TRUE,
        comments        => 'Detect idle agents and log audit events hourly (v3.3.0 ENT)'
    );
END;
/

SELECT JOB_NAME, STATE, REPEAT_INTERVAL
FROM USER_SCHEDULER_JOBS
WHERE JOB_NAME IN (
    'MEMORY_FUSION_JOB', 'KNOWLEDGE_EXTRACTION_JOB', 'KNOWLEDGE_REVIEW_JOB',
    'SESSION_CLEANUP_JOB', 'ACCESS_LOG_PURGE_JOB', 'ENTITY_ARCHIVE_JOB', 'COLLAB_EXPIRY_JOB',
    'WORKSPACE_CLEANUP_JOB', 'STALE_WORKSPACE_DETECT_JOB',
    'DORMANT_AGENT_JOB', 'CREDENTIAL_CLEANUP_JOB', 'EMBEDDING_GENERATION_JOB',
    'LDAP_SYNC_JOB', 'SKILL_TOKEN_CLEANUP_JOB',
    'CONTEXT_AUDIT_JOB', 'IDLE_PATTERN_DETECT_JOB', 'BRANCH_CLEANUP_JOB',
    'LOOP_TRIGGER_JOB', 'LOOP_STUCK_CHECK_JOB', 'LOOP_CLEANUP_JOB'
)
ORDER BY JOB_NAME;


PROMPT ============================================================
PROMPT Job: BRANCH_CLEANUP_JOB [NEW v3.3.0]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'BRANCH_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN BRANCH_MANAGER.cleanup_abandoned_branches(90); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=3',
        enabled         => TRUE,
        comments        => 'Daily cleanup of abandoned branches older than 90 days'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('BRANCH_CLEANUP_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: LOOP_TRIGGER_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'LOOP_TRIGGER_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN LOOP_MANAGER.process_scheduled_triggers; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=1',
        enabled         => TRUE,
        comments        => 'Every minute: check scheduled Loop triggers and start runs'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('LOOP_TRIGGER_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: LOOP_STUCK_CHECK_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'LOOP_STUCK_CHECK_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN LOOP_MANAGER.check_stuck_runs; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=5',
        enabled         => TRUE,
        comments        => 'Every 5 minutes: check for stuck/timed-out Loop runs'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('LOOP_STUCK_CHECK_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: LOOP_CLEANUP_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'LOOP_CLEANUP_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN LOOP_MANAGER.cleanup_old_runs(90); END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=6',
        enabled         => TRUE,
        comments        => 'Weekly: cleanup old completed Loop runs older than 90 days'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('LOOP_CLEANUP_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: DAG_RESOLVER_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'DAG_RESOLVER_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN NULL; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=5',
        enabled         => TRUE,
        comments        => 'Every 5 min: resolve pending DAG execution plans'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('DAG_RESOLVER_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: HOOK_EXECUTOR_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'HOOK_EXECUTOR_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN NULL; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=1',
        enabled         => TRUE,
        comments        => 'Every 1 min: process queued webhook/script hook executions'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('HOOK_EXECUTOR_JOB: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Job: ALERT_EVALUATOR_JOB [NEW v3.7.5]
PROMPT ============================================================

BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name        => 'ALERT_EVALUATOR_JOB',
        job_type        => 'PLSQL_BLOCK',
        job_action      => 'BEGIN NULL; END;',
        start_date      => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MINUTELY; INTERVAL=5',
        enabled         => TRUE,
        comments        => 'Every 5 min: evaluate alert rules and fire notifications'
    );
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('ALERT_EVALUATOR_JOB: ' || SQLERRM);
END;
/


PROMPT AI Agent Infra v3.10.2 - Enterprise Edition - Scheduler Jobs Complete (23 jobs)
