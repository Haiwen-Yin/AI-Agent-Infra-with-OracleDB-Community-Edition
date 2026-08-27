-- v4.4.10: refresh Deep Security data grants for external Gateway flows.
-- `agent_data_role` is an Oracle AI Database DATA ROLE created by the SYS
-- prerequisite. Regular object GRANT statements are invalid for DATA ROLEs.
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
CREATE OR REPLACE DATA GRANT gw_agent_postures
  AS SELECT, INSERT, UPDATE ON CX_AGENT_POSTURES
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_agent_evidence
  AS SELECT, INSERT ON CX_AGENT_POSTURE_EVIDENCE
  WHERE AGENT_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_security_events
  AS INSERT ON CX_SECURITY_EVENTS
  WHERE PRINCIPAL_ID = ORA_END_USER_CONTEXT.username TO agent_data_role;
/
CREATE OR REPLACE DATA GRANT gw_external_endpoint
  AS SELECT ON CX_EXTERNAL_DB_ENDPOINTS TO agent_data_role;
/
