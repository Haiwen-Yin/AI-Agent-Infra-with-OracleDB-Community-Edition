-- v4.4.10: refresh Deep Security data grants for external Gateway flows.
-- Community does not execute the Enterprise Deep Security overlay, so this
-- portable migration owns the two external-Agent Data Roles.
BEGIN
  EXECUTE IMMEDIATE 'CREATE DATA ROLE agent_data_role';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -52514 THEN RAISE; END IF;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'CREATE DATA ROLE pool_agent_data_role';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -52514 THEN RAISE; END IF;
END;
/
GRANT DEEP_SEC_SESSION_ROLE TO agent_data_role;
GRANT DEEP_SEC_SESSION_ROLE TO pool_agent_data_role;

-- Regular object GRANT statements are invalid for DATA ROLEs.
CREATE OR REPLACE DATA GRANT gw_agent_credentials
  AS SELECT ON CX_AGENT_CREDENTIALS
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_agent_principals
  AS SELECT ON CX_PRINCIPALS
  WHERE PRINCIPAL_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_agent_instances
  AS SELECT ON CX_AGENT_INSTANCES
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_agent_instances_update
  AS UPDATE ON CX_AGENT_INSTANCES
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_agent_tokens
  AS SELECT, INSERT ON CX_AGENT_ACCESS_TOKENS
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
DECLARE
  l_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO l_count FROM USER_TABLES WHERE TABLE_NAME='CX_AGENT_POSTURES';
  IF l_count > 0 THEN
    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT gw_agent_postures
      AS SELECT, INSERT, UPDATE ON CX_AGENT_POSTURES
      WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role]';
  END IF;
  SELECT COUNT(*) INTO l_count FROM USER_TABLES WHERE TABLE_NAME='CX_AGENT_POSTURE_EVIDENCE';
  IF l_count > 0 THEN
    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT gw_agent_evidence
      AS SELECT, INSERT ON CX_AGENT_POSTURE_EVIDENCE
      WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role]';
  END IF;
END;
/
CREATE OR REPLACE DATA GRANT gw_security_events
  AS INSERT ON CX_SECURITY_EVENTS
  WHERE PRINCIPAL_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_external_endpoint
  AS SELECT ON CX_EXTERNAL_DB_ENDPOINTS TO agent_data_role;
/
