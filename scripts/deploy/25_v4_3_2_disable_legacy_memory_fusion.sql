-- v4.3.2 lifecycle safety correction.
-- The pre-v4.3.2 scheduler mutates legacy Memory rows directly, bypassing
-- immutable versions, review candidates, snapshots, and lifecycle audit.
-- Remove it rather than silently changing its action; governed durable jobs
-- are the only supported automation path after this migration.
BEGIN
    DBMS_SCHEDULER.DROP_JOB('MEMORY_FUSION_JOB', FALSE);
EXCEPTION
    WHEN OTHERS THEN
        -- ORA-27475: the job does not exist. Re-running this step is safe.
        IF SQLCODE != -27475 THEN
            RAISE;
        END IF;
END;
/
