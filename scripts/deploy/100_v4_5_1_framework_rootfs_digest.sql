-- v4.5.1 compatibility repair for framework isolation evidence.
-- Migration 98 originally accepted the digest column at VARCHAR2(64). The
-- runtime records an algorithm-qualified value (for example sha256:<hex>),
-- so existing databases must widen the column before an isolated execution.

DECLARE
  n NUMBER;
BEGIN
  SELECT COUNT(*) INTO n
    FROM USER_TAB_COLUMNS
   WHERE TABLE_NAME = 'CX_FRAMEWORK_EXECUTIONS'
     AND COLUMN_NAME = 'ROOTFS_DIGEST'
     AND DATA_LENGTH < 128;
  IF n > 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE CX_FRAMEWORK_EXECUTIONS MODIFY (ROOTFS_DIGEST VARCHAR2(128))';
  END IF;
END;
/

-- Recompile the immutable extension trigger after the column-width change.
-- Oracle may retain an INVALID status for a dependent trigger after an
-- online ALTER TABLE even though the source remains unchanged.
DECLARE
  n NUMBER;
BEGIN
  SELECT COUNT(*) INTO n FROM USER_TRIGGERS
   WHERE TRIGGER_NAME = 'CX86_61CC3DF1F0728A5A';
  IF n = 1 THEN
    EXECUTE IMMEDIATE 'ALTER TRIGGER CX86_61CC3DF1F0728A5A COMPILE';
  END IF;
END;
/
