-- Both editions need native own/public reads. Public read is not public write.
CREATE OR REPLACE DATA GRANT entities_agent_own
  AS SELECT ON ENTITIES
  WHERE VISIBILITY='PUBLIC'
     OR UPPER(REPLACE(OWNED_BY_AGENT,'-','_'))=ORA_END_USER_CONTEXT.username
  TO agent_data_role;
CREATE OR REPLACE DATA GRANT entities_agent_update_own
  AS UPDATE ON ENTITIES
  WHERE UPPER(REPLACE(OWNED_BY_AGENT,'-','_'))=ORA_END_USER_CONTEXT.username
  TO agent_data_role;
