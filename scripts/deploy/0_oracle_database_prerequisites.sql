-- Oracle AI Database 26ai pre-deployment owner prerequisites.
-- Run as SYSDBA in the target PDB, never in CDB$ROOT.
-- Review all definitions before execution. The quota must be sized by the DBA.
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET VERIFY OFF
DEFINE SCHEMA_OWNER = 'AIADMIN'
-- Replace this with a writable application tablespace that actually exists in
-- the target PDB. A newly created PDB is not required to contain USERS.
DEFINE APP_TABLESPACE = 'USERS'
DEFINE APP_QUOTA = '20G'

PROMPT Verifying the target container and recording database evidence...
DECLARE
  l_container VARCHAR2(128);
BEGIN
  SELECT SYS_CONTEXT('USERENV', 'CON_NAME') INTO l_container FROM dual;
  IF UPPER(l_container) = 'CDB$ROOT' THEN
    RAISE_APPLICATION_ERROR(-20001,
      'Run prerequisites in the dedicated application PDB, not CDB$ROOT');
  END IF;
END;
/

SELECT SYS_CONTEXT('USERENV', 'CON_NAME') AS target_container FROM dual;
SELECT banner_full FROM v$version FETCH FIRST 1 ROW ONLY;
SELECT value AS partitioning_enabled
  FROM v$option WHERE parameter = 'Partitioning';
SELECT comp_id, status, version
  FROM dba_registry WHERE comp_id = 'CONTEXT';
SELECT value AS database_character_set
  FROM nls_database_parameters WHERE parameter = 'NLS_CHARACTERSET';
SELECT username, account_status, default_tablespace, temporary_tablespace
  FROM dba_users WHERE username = UPPER('&&SCHEMA_OWNER');

PROMPT Granting base schema creation privileges...
GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW,
      CREATE PROCEDURE, CREATE TRIGGER, CREATE TYPE, CREATE JOB,
      CREATE PROPERTY GRAPH
  TO &&SCHEMA_OWNER;
ALTER USER &&SCHEMA_OWNER QUOTA &&APP_QUOTA ON &&APP_TABLESPACE;

PROMPT Granting direct package and Oracle Text prerequisites...
GRANT CTXAPP TO &&SCHEMA_OWNER;
GRANT EXECUTE ON CTXSYS.CTX_DDL TO &&SCHEMA_OWNER;
GRANT EXECUTE ON SYS.DBMS_CRYPTO TO &&SCHEMA_OWNER;
GRANT EXECUTE ON SYS.UTL_HTTP TO &&SCHEMA_OWNER;
GRANT SELECT ON SYS.V_$INSTANCE TO &&SCHEMA_OWNER;
GRANT SELECT ON SYS.V_$OPTION TO &&SCHEMA_OWNER;

PROMPT Creating the bounded End User login role required by Deep Data Security...
BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE DEEP_SEC_SESSION_ROLE';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1921 THEN
      RAISE;
    END IF;
END;
/
GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
GRANT DEEP_SEC_SESSION_ROLE TO &&SCHEMA_OWNER WITH ADMIN OPTION;

PROMPT Granting Oracle 26ai Deep Data Security owner privileges...
GRANT CREATE DATA GRANT, CREATE ANY DATA GRANT, ADMINISTER ANY DATA GRANT,
      CREATE DATA ROLE, DROP DATA ROLE, GRANT ANY DATA ROLE,
      SET USE DATA GRANTS ONLY,
      CREATE END USER, ALTER END USER, DROP END USER,
      CREATE END USER CONTEXT, CREATE ANY END USER CONTEXT,
      CREATE END USER SECURITY CONTEXT, CREATE ANY CONTEXT
  TO &&SCHEMA_OWNER;

PROMPT Owner prerequisites applied. Configure UTL_HTTP network ACLs separately
PROMPT for the approved model/Embedding destinations only.
SELECT tablespace_name, bytes, max_bytes
  FROM dba_ts_quotas WHERE username = UPPER('&&SCHEMA_OWNER');
SELECT granted_role, admin_option
  FROM dba_role_privs
  WHERE grantee = UPPER('&&SCHEMA_OWNER')
    AND granted_role = 'DEEP_SEC_SESSION_ROLE';
PROMPT Next: run migration_runner.py --preflight from the platform host.
