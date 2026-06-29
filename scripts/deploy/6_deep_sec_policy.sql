-- ============================================================
-- 6_deep_sec_policy.sql — Oracle Deep Data Security (Deep Sec)
-- AI Agent Infra with OracleDB v3.7.5
-- ============================================================
--
-- Deep Sec enforcement via Direct Logon with Local End Users.
-- No external IAM, no TCPS, no tokens required.
--
-- Architecture:
--   - Each Pool Agent has a corresponding Deep Sec End User
--   - End User name = UPPER(REPLACE(agent_id, '-', '_'))
--   - Portal users connect as End User → Data Grants auto-filter
--   - Admin Dashboard connects as AIADMIN (schema owner, unrestricted)
--   - Data Grants use ORA_END_USER_CONTEXT.username for predicates
--   - MAC (SET USE DATA GRANTS ONLY) enforces on all access paths
--
-- Prerequisites:
--   - Oracle AI Database 26ai (23.26.2+)
--   - COMPATIBLE >= 20.0
--   - DEEP_SEC_SESSION_ROLE created by SYS with CREATE SESSION
--   - Run as AIADMIN (objects created in AIADMIN schema)
--
-- ============================================================

-- ============================================================
-- Schema owner configuration (adjust if not using default AIADMIN)
-- ============================================================
DEFINE SCHEMA_OWNER = 'AIADMIN'
DEFINE AGENT_USER = 'AGENT_API'

PROMPT ============================================================
PROMPT Step 1: Creating application context (AGENT_CTX)
PROMPT ============================================================

CREATE OR REPLACE CONTEXT AGENT_CTX USING &&SCHEMA_OWNER..SET_AGENT_CONTEXT;
/

PROMPT ============================================================
PROMPT Step 2: Creating SET_AGENT_CONTEXT package
PROMPT ============================================================

CREATE OR REPLACE PACKAGE SET_AGENT_CONTEXT AS
    PROCEDURE set_agent_id(p_agent_id VARCHAR2);
    PROCEDURE clear_context;
END SET_AGENT_CONTEXT;
/

CREATE OR REPLACE PACKAGE BODY SET_AGENT_CONTEXT AS
    PROCEDURE set_agent_id(p_agent_id VARCHAR2) IS
    BEGIN
        DBMS_SESSION.SET_CONTEXT('AGENT_CTX', 'AGENT_ID', p_agent_id);
    END set_agent_id;

    PROCEDURE clear_context IS
    BEGIN
        DBMS_SESSION.CLEAR_CONTEXT('AGENT_CTX', NULL, 'AGENT_ID');
    END clear_context;
END SET_AGENT_CONTEXT;
/

PROMPT ============================================================
PROMPT Step 3: Creating End User Context (agent_context)
PROMPT ============================================================

CREATE OR REPLACE END USER CONTEXT agent_context USING JSON SCHEMA '{
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "o:onFirstRead": "aiadmin.agent_auth_pkg.init_agent_context"
        },
        "workspace_id": {
            "type": "string",
            "default": ""
        },
        "agent_type": {
            "type": "string",
            "default": "BUSINESS"
        }
    }
}';
/

PROMPT ============================================================
PROMPT Step 4: Creating agent_auth_pkg (o:onFirstRead callback)
PROMPT ============================================================

CREATE OR REPLACE PACKAGE agent_auth_pkg AS
    FUNCTION init_agent_context RETURN VARCHAR2;
END agent_auth_pkg;
/

CREATE OR REPLACE PACKAGE BODY agent_auth_pkg AS
    FUNCTION init_agent_context RETURN VARCHAR2 IS
    BEGIN
        RETURN SYS_CONTEXT('AGENT_CTX', 'AGENT_ID');
    END init_agent_context;
END agent_auth_pkg;
/

PROMPT ============================================================
PROMPT Step 5: Creating Data Roles
PROMPT ============================================================

CREATE DATA ROLE admin_data_role;
/

CREATE DATA ROLE agent_data_role;
/

CREATE DATA ROLE pool_agent_data_role;
/

PROMPT ============================================================
PROMPT Step 6: Granting CREATE SESSION to Data Roles
PROMPT ============================================================
-- DEEP_SEC_SESSION_ROLE must be created by SYS first:
--   CREATE ROLE DEEP_SEC_SESSION_ROLE;
--   GRANT CREATE SESSION TO DEEP_SEC_SESSION_ROLE;
--   GRANT DEEP_SEC_SESSION_ROLE TO &&SCHEMA_OWNER WITH ADMIN OPTION;

BEGIN
  EXECUTE IMMEDIATE 'GRANT DEEP_SEC_SESSION_ROLE TO agent_data_role';
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'GRANT DEEP_SEC_SESSION_ROLE TO admin_data_role';
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'GRANT DEEP_SEC_SESSION_ROLE TO pool_agent_data_role';
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

PROMPT ============================================================
PROMPT Step 7: Creating Data Grants — WORKSPACE_CONTEXT + WORKSPACES
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT ws_ctx_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..WORKSPACE_CONTEXT
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT ws_ctx_agent_access
  AS SELECT
  ON &&SCHEMA_OWNER..WORKSPACE_CONTEXT
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
         OR (VISIBILITY = 'PUBLIC')
         OR (VISIBILITY = 'SHARED' AND WORKSPACE_ID IN (
             SELECT WORKSPACE_ID FROM &&SCHEMA_OWNER..WORKSPACES
             WHERE UPPER(REPLACE(CURRENT_AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
             UNION
             SELECT cg.WORKSPACE_ID FROM &&SCHEMA_OWNER..COLLAB_GROUPS cg
             JOIN &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
             WHERE UPPER(REPLACE(cgm.AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
               AND cgm.STATUS = 'ACTIVE'
         ))
  TO agent_data_role;
/

CREATE OR REPLACE DATA GRANT ws_ctx_agent_insert
  AS INSERT
  ON &&SCHEMA_OWNER..WORKSPACE_CONTEXT
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
         OR VISIBILITY IN ('SHARED', 'PUBLIC')
  TO agent_data_role;
/

CREATE OR REPLACE DATA GRANT ws_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..WORKSPACES
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT ws_agent_access
  AS SELECT
  ON &&SCHEMA_OWNER..WORKSPACES
  WHERE UPPER(REPLACE(CURRENT_AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
     OR WORKSPACE_ID IN (
         SELECT cg.WORKSPACE_ID FROM &&SCHEMA_OWNER..COLLAB_GROUPS cg
         JOIN &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
         WHERE UPPER(REPLACE(cgm.AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
           AND cgm.STATUS = 'ACTIVE'
     )
  TO agent_data_role;
/

CREATE OR REPLACE DATA GRANT ws_agent_update
  AS UPDATE
  ON &&SCHEMA_OWNER..WORKSPACES
  WHERE 1=1
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 8: Creating Data Grants — ENTITIES (row + column level)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT entities_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..ENTITIES
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT entities_agent_own
  AS SELECT, UPDATE
  ON &&SCHEMA_OWNER..ENTITIES
  WHERE VISIBILITY = 'PUBLIC'
     OR (VISIBILITY = 'PRIVATE' AND UPPER(REPLACE(OWNED_BY_AGENT, '-', '_')) = ORA_END_USER_CONTEXT.username)
     OR (VISIBILITY = 'SHARED' AND WORKSPACE_ID IN (
         SELECT WORKSPACE_ID FROM &&SCHEMA_OWNER..WORKSPACES
         WHERE UPPER(REPLACE(CURRENT_AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
         UNION
         SELECT cg.WORKSPACE_ID FROM &&SCHEMA_OWNER..COLLAB_GROUPS cg
         JOIN &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
         WHERE UPPER(REPLACE(cgm.AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
           AND cgm.STATUS = 'ACTIVE'
     ))
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 9: Creating Data Grants — AGENT_CREDENTIALS (column masking)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT cred_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..AGENT_CREDENTIALS
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT cred_agent_own
  AS SELECT (ALL COLUMNS EXCEPT CREDENTIAL_VALUE)
  ON &&SCHEMA_OWNER..AGENT_CREDENTIALS
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 10: Creating Data Grants — SYSTEM_CONFIG (admin only)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT config_admin_only
  AS SELECT, UPDATE
  ON &&SCHEMA_OWNER..SYSTEM_CONFIG
  TO admin_data_role;
/

PROMPT ============================================================
PROMPT Step 11: Creating Data Grants — AGENT_REGISTRY (row + column)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT registry_admin_access
  AS SELECT, UPDATE
  ON &&SCHEMA_OWNER..AGENT_REGISTRY
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT registry_agent_own
  AS SELECT
  ON &&SCHEMA_OWNER..AGENT_REGISTRY
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 12: Creating Data Grants — SKILL_META (public read)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT skill_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..SKILL_META
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT skill_agent_read
  AS SELECT
  ON &&SCHEMA_OWNER..SKILL_META
  TO agent_data_role;
/

CREATE OR REPLACE DATA GRANT skill_pool_read
  AS SELECT
  ON &&SCHEMA_OWNER..SKILL_META
  TO pool_agent_data_role;
/

PROMPT ============================================================
PROMPT Step 13: Creating Data Grants — POOL Agent minimum access
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT registry_pool_own
  AS SELECT
  ON &&SCHEMA_OWNER..AGENT_REGISTRY
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
  TO pool_agent_data_role;
/

PROMPT ============================================================
PROMPT Step 14: Creating Data Grants — CONTEXT_BRANCHES
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT branch_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..CONTEXT_BRANCHES
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT branch_agent_access
  AS SELECT
  ON &&SCHEMA_OWNER..CONTEXT_BRANCHES
  WHERE WORKSPACE_ID IN (
      SELECT WORKSPACE_ID FROM &&SCHEMA_OWNER..WORKSPACES
      WHERE UPPER(REPLACE(CURRENT_AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
      UNION
      SELECT cg.WORKSPACE_ID FROM &&SCHEMA_OWNER..COLLAB_GROUPS cg
      JOIN &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
      WHERE UPPER(REPLACE(cgm.AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
        AND cgm.STATUS = 'ACTIVE'
  )
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 15: Creating Data Grants — TASK_PLANS (collab access)
PROMPT ============================================================

CREATE OR REPLACE DATA GRANT task_admin_access
  AS SELECT, UPDATE, INSERT, DELETE
  ON &&SCHEMA_OWNER..TASK_PLANS
  TO admin_data_role;
/

CREATE OR REPLACE DATA GRANT task_agent_access
  AS SELECT, UPDATE
  ON &&SCHEMA_OWNER..TASK_PLANS
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
     OR BRANCH_ID IN (
         SELECT BRANCH_ID FROM &&SCHEMA_OWNER..CONTEXT_BRANCHES
         WHERE WORKSPACE_ID IN (
             SELECT WORKSPACE_ID FROM &&SCHEMA_OWNER..WORKSPACES
             WHERE UPPER(REPLACE(CURRENT_AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
             UNION
             SELECT cg.WORKSPACE_ID FROM &&SCHEMA_OWNER..COLLAB_GROUPS cg
             JOIN &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
             WHERE UPPER(REPLACE(cgm.AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
               AND cgm.STATUS = 'ACTIVE'
         )
     )
   TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 16: Creating Data Grants — COLLAB_GROUPS + COLLAB_GROUP_MEMBERS
PROMPT ============================================================
-- Required for Data Grant predicates that reference COLLAB tables in subqueries.
-- Without these, End Users cannot access COLLAB tables, causing predicates to
-- silently fail and SHARED entities to become invisible.

CREATE OR REPLACE DATA GRANT collab_member_own
  AS SELECT
  ON &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS
  WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
  TO agent_data_role;
/

CREATE OR REPLACE DATA GRANT collab_group_member_access
  AS SELECT
  ON &&SCHEMA_OWNER..COLLAB_GROUPS
  WHERE GROUP_ID IN (
      SELECT GROUP_ID FROM &&SCHEMA_OWNER..COLLAB_GROUP_MEMBERS
      WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
        AND STATUS = 'ACTIVE'
  )
  TO agent_data_role;
/

PROMPT ============================================================
PROMPT Step 18: Enabling MAC (Mandatory Access Control)
PROMPT ============================================================

BEGIN
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..WORKSPACE_CONTEXT ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..ENTITIES ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..AGENT_CREDENTIALS ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..SYSTEM_CONFIG ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..AGENT_REGISTRY ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..CONTEXT_BRANCHES ENABLED';
  EXECUTE IMMEDIATE 'SET USE DATA GRANTS ONLY ON &&SCHEMA_OWNER..TASK_PLANS ENABLED';
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

PROMPT ============================================================
PROMPT Step 19: Creating END_USER_MANAGER package
PROMPT ============================================================
-- Manages Deep Sec End User lifecycle: create, drop, get password
-- Key: ensure_end_user(agent_id) handles name mapping automatically

CREATE OR REPLACE PACKAGE END_USER_MANAGER AS
    FUNCTION create_end_user(p_agent_id VARCHAR2, p_eu_name VARCHAR2, p_password VARCHAR2 DEFAULT NULL) RETURN VARCHAR2;
    PROCEDURE drop_end_user(p_agent_id VARCHAR2, p_eu_name VARCHAR2);
    FUNCTION get_password(p_agent_id VARCHAR2) RETURN VARCHAR2;
    FUNCTION ensure_end_user(p_agent_id VARCHAR2) RETURN VARCHAR2;
END END_USER_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY END_USER_MANAGER AS
    FUNCTION generate_password RETURN VARCHAR2 IS
        chars VARCHAR2(62) := 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        pwd VARCHAR2(16);
    BEGIN
        FOR i IN 1..16 LOOP
            pwd := pwd || SUBSTR(chars, FLOOR(DBMS_RANDOM.VALUE(1, 63)), 1);
        END LOOP;
        RETURN pwd;
    END;

    FUNCTION create_end_user(p_agent_id VARCHAR2, p_eu_name VARCHAR2, p_password VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
        v_pwd VARCHAR2(100);
        v_existing VARCHAR2(100);
    BEGIN
        BEGIN
            SELECT config_value INTO v_existing
            FROM SYSTEM_CONFIG
            WHERE config_key = 'end_user_pwd.' || p_agent_id;
            IF v_existing IS NOT NULL THEN
                RETURN v_existing;
            END IF;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN NULL;
        END;

        v_pwd := COALESCE(p_password, generate_password());

        BEGIN
            EXECUTE IMMEDIATE 'CREATE END USER "' || p_eu_name || '" IDENTIFIED BY "' || v_pwd || '"';
        EXCEPTION
            WHEN OTHERS THEN
                IF SQLCODE != -52514 AND SQLCODE != -52513 THEN
                    RETURN 'ERROR:' || SQLERRM;
                END IF;
        END;

        BEGIN
            EXECUTE IMMEDIATE 'GRANT DATA ROLE agent_data_role TO "' || p_eu_name || '"';
        EXCEPTION WHEN OTHERS THEN NULL;
        END;

        BEGIN
            EXECUTE IMMEDIATE 'GRANT DATA ROLE pool_agent_data_role TO "' || p_eu_name || '"';
        EXCEPTION WHEN OTHERS THEN NULL;
        END;

        MERGE INTO SYSTEM_CONFIG sc
        USING (SELECT 'end_user_pwd.' || p_agent_id AS k, v_pwd AS v FROM DUAL) d
        ON (sc.CONFIG_KEY = d.k)
        WHEN MATCHED THEN UPDATE SET CONFIG_VALUE = d.v
        WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
            VALUES (d.k, d.v, 'Deep Sec End User for ' || p_agent_id || ' (EU: ' || p_eu_name || ')');

        RETURN v_pwd;
    EXCEPTION
        WHEN OTHERS THEN RETURN 'ERROR:' || SQLERRM;
    END;

    PROCEDURE drop_end_user(p_agent_id VARCHAR2, p_eu_name VARCHAR2) IS
    BEGIN
        EXECUTE IMMEDIATE 'DROP END USER "' || p_eu_name || '"';
        DELETE FROM SYSTEM_CONFIG WHERE CONFIG_KEY = 'end_user_pwd.' || p_agent_id;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;

    FUNCTION get_password(p_agent_id VARCHAR2) RETURN VARCHAR2 IS
        v_pwd VARCHAR2(100);
    BEGIN
        SELECT config_value INTO v_pwd
        FROM SYSTEM_CONFIG
        WHERE config_key = 'end_user_pwd.' || p_agent_id;
        RETURN v_pwd;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN RETURN NULL;
    END;

    FUNCTION ensure_end_user(p_agent_id VARCHAR2) RETURN VARCHAR2 IS
        v_eu_name VARCHAR2(100);
        v_pwd VARCHAR2(100);
    BEGIN
        v_pwd := get_password(p_agent_id);
        IF v_pwd IS NOT NULL THEN
            RETURN v_pwd;
        END IF;

        v_eu_name := UPPER(REPLACE(p_agent_id, '-', '_'));
        RETURN create_end_user(p_agent_id, v_eu_name);
    END;
END END_USER_MANAGER;
/

PROMPT ============================================================
PROMPT Step 20: Creating End Users for existing agents
PROMPT ============================================================

DECLARE
    v_pwd VARCHAR2(100);
    CURSOR c_agents IS SELECT AGENT_ID FROM &&SCHEMA_OWNER..AGENT_REGISTRY;
BEGIN
    FOR r IN c_agents LOOP
        v_pwd := &&SCHEMA_OWNER..END_USER_MANAGER.ensure_end_user(r.AGENT_ID);
        IF v_pwd LIKE 'ERROR:%' THEN
            DBMS_OUTPUT.PUT_LINE('  Warning: ' || r.AGENT_ID || ': ' || v_pwd);
        ELSE
            DBMS_OUTPUT.PUT_LINE('  Created: ' || r.AGENT_ID);
        END IF;
    END LOOP;
    COMMIT;
END;
/

PROMPT ============================================================
PROMPT Step 19: Granting SET_AGENT_CONTEXT to AGENT_API
PROMPT ============================================================

BEGIN
  EXECUTE IMMEDIATE 'GRANT EXECUTE ON &&SCHEMA_OWNER..SET_AGENT_CONTEXT TO AGENT_API';
EXCEPTION
  WHEN OTHERS THEN NULL;
END;
/

PROMPT ============================================================
PROMPT Deep Data Security policies are now active
PROMPT ============================================================
PROMPT
PROMPT Summary of created objects:
PROMPT   Context:          AGENT_CTX
PROMPT   Package:          SET_AGENT_CONTEXT
PROMPT   End User Context: agent_context (o:onFirstRead callback)
PROMPT   Package:          agent_auth_pkg (callback)
PROMPT   Package:          END_USER_MANAGER (End User lifecycle)
PROMPT   Data Roles:       admin_data_role, agent_data_role, pool_agent_data_role
PROMPT   Session Role:     DEEP_SEC_SESSION_ROLE (CREATE SESSION)
PROMPT   Data Grants:      23 grants (row, column, cell level, collab access)
PROMPT   MAC:              7 tables protected
PROMPT   End Users:        One per agent (Direct Logon mode)
PROMPT
PROMPT ENFORCEMENT ARCHITECTURE:
PROMPT   - Portal users → connect as Deep Sec End User
PROMPT   - End User name = UPPER(REPLACE(agent_id, '-', '_'))
PROMPT   - Data Grants auto-filter using ORA_END_USER_CONTEXT.username
PROMPT   - Admin Dashboard → AIADMIN connection pool (unrestricted)
PROMPT   - No IAM, no TCPS, no tokens required (Direct Logon mode)
PROMPT
PROMPT KEY SECURITY IMPROVEMENTS OVER VPD:
PROMPT   1. Database-level enforcement (not application-level)
PROMPT   2. Zero trust: no context = no data
PROMPT   3. Column masking: CREDENTIAL_VALUE hidden from agents
PROMPT   4. MAC: prevents view bypass of row-level policies
PROMPT   5. Declarative: policies visible in USER_DATA_GRANTS
PROMPT   6. Direct Logon: no IAM dependency for local deployment
PROMPT ============================================================

PROMPT ============================================================
PROMPT Data Grant: COLLAB_MESSAGES [NEW v3.7.4]
PROMPT ============================================================

BEGIN
    DBMS_OUTPUT.PUT_LINE('Creating Data Grant: collab_message_access...');

    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT collab_message_access AS SELECT
        ON COLLAB_MESSAGES
        WHERE SENDER_AGENT_ID = ORA_END_USER_CONTEXT.username
           OR RECEIVER_AGENT_ID = ORA_END_USER_CONTEXT.username
           OR (RECEIVER_AGENT_ID IS NULL AND GROUP_ID IN (
               SELECT GROUP_ID FROM COLLAB_GROUP_MEMBERS
               WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
                 AND STATUS = 'ACTIVE'))
        TO agent_data_role]';

    DBMS_OUTPUT.PUT_LINE('  collab_message_access created');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('  collab_message_access: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Data Grant: EVENT_LOG (read-only to agents) [NEW v3.7.4]
PROMPT ============================================================

BEGIN
    DBMS_OUTPUT.PUT_LINE('Creating Data Grant: event_log_access...');

    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT event_log_access AS SELECT
        ON EVENT_LOG
        WHERE SOURCE_ID = ORA_END_USER_CONTEXT.username
           OR EVENT_TYPE IN (
               SELECT EVENT_TYPE FROM EVENT_SUBSCRIPTIONS
               WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
                 AND ENABLED = 'Y'
           )
        TO agent_data_role]';

    DBMS_OUTPUT.PUT_LINE('  event_log_access created');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('  event_log_access: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Data Grant: EVENT_SUBSCRIPTIONS [NEW v3.7.4]
PROMPT ============================================================

BEGIN
    DBMS_OUTPUT.PUT_LINE('Creating Data Grant: event_sub_own...');

    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT event_sub_own AS SELECT
        ON EVENT_SUBSCRIPTIONS
        WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
        TO agent_data_role]';

    DBMS_OUTPUT.PUT_LINE('  event_sub_own created');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('  event_sub_own: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT Data Grant: AGENT_CAPABILITY_INDEX [NEW v3.7.4]
PROMPT ============================================================

BEGIN
    DBMS_OUTPUT.PUT_LINE('Creating Data Grant: capability_own...');

    EXECUTE IMMEDIATE q'[CREATE OR REPLACE DATA GRANT capability_own AS SELECT
        ON AGENT_CAPABILITY_INDEX
        WHERE UPPER(REPLACE(AGENT_ID, '-', '_')) = ORA_END_USER_CONTEXT.username
        TO agent_data_role]';

    DBMS_OUTPUT.PUT_LINE('  capability_own created');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('  capability_own: ' || SQLERRM);
END;
/

PROMPT ============================================================
PROMPT v3.7.5 Deep Sec Policy Deployment Complete
PROMPT ============================================================
