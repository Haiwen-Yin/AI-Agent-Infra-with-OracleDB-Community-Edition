-- Executed by the journaled runner after lib.oracle_task_migration completes.
-- Never treat the control metadata alone as evidence of a switched schema.
DECLARE
  v_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO v_count FROM USER_PART_TABLES
    WHERE TABLE_NAME='TASK_STEPS' AND PARTITIONING_TYPE='HASH';
  IF v_count<>1 THEN RAISE_APPLICATION_ERROR(-20076,'Task stable partition migration is incomplete'); END IF;
  SELECT COUNT(*) INTO v_count FROM CX415_TASK_SWITCH
    WHERE MIGRATION_KEY='TASK_STEPS' AND STATE='VERIFIED';
  IF v_count<>1 THEN RAISE_APPLICATION_ERROR(-20076,'Task migration requires recovery'); END IF;
  SELECT COUNT(*) INTO v_count FROM USER_TABLES WHERE TABLE_NAME='CX415_TASK_STEPS_OLD';
  IF v_count<>0 THEN RAISE_APPLICATION_ERROR(-20076,'Obsolete reference child still exists'); END IF;
END;
/
