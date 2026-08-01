-- v4.3.1 Human entry-access policy and protected bootstrap administrator.

DECLARE
    PROCEDURE add_column(p_table VARCHAR2, p_column VARCHAR2, p_definition VARCHAR2) IS
        l_count NUMBER;
    BEGIN
        SELECT COUNT(*) INTO l_count FROM USER_TAB_COLUMNS
         WHERE TABLE_NAME = UPPER(p_table) AND COLUMN_NAME = UPPER(p_column);
        IF l_count = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE ' || p_table || ' ADD (' || p_column || ' ' || p_definition || ')';
        END IF;
    END;
BEGIN
    add_column('CX_PRINCIPALS', 'PORTAL_ACCESS', 'CHAR(1) DEFAULT ''Y'' NOT NULL');
    add_column('CX_PRINCIPALS', 'APP_ACCESS', 'CHAR(1) DEFAULT ''Y'' NOT NULL');
END;
/

UPDATE CX_PRINCIPALS p
   SET PORTAL_ACCESS = 'Y', APP_ACCESS = 'Y'
 WHERE EXISTS (
       SELECT 1 FROM CX_HUMAN_IDENTITIES i
        WHERE i.PRINCIPAL_ID = p.PRINCIPAL_ID
          AND i.IDENTITY_TYPE = 'LOCAL'
          AND i.SUBJECT_KEY = 'admin'
 );

UPDATE CX_USER_ROLES r
   SET SOURCE = 'BOOTSTRAP_ADMIN'
 WHERE r.ROLE_CODE = 'SYSTEM_ADMIN'
   AND r.STATUS = 'ACTIVE'
   AND EXISTS (
       SELECT 1 FROM CX_HUMAN_IDENTITIES i
        WHERE i.PRINCIPAL_ID = r.PRINCIPAL_ID
          AND i.IDENTITY_TYPE = 'LOCAL'
          AND i.SUBJECT_KEY = 'admin'
   );
