-- Both editions need bounded receiver reads; do not silently ignore failures.
CREATE OR REPLACE DATA GRANT gw_context_read
  AS SELECT ON WORKSPACE_CONTEXT
  WHERE (UPPER(REPLACE(AGENT_ID, '-', '_'))=ORA_END_USER_CONTEXT.username OR VISIBILITY='PUBLIC')
  TO agent_data_role;
