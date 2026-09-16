-- v4.4.15 task status transition marker. Oracle reference partitioning is
-- retained; task_plan_api updates child PLAN_STATUS before parent STATUS in one
-- transaction, preserving the partition and composite constraint.
BEGIN
  EXECUTE IMMEDIATE 'COMMENT ON TABLE TASK_STEPS IS ''v4.4.15 task status transition contract''';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
