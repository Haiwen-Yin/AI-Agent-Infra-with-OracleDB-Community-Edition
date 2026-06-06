-- ============================================================
-- 6_vpd_policy.sql — Virtual Private Database (Row-Level Security)
-- AI Agent Infra with OracleDB v3.3.0
-- ============================================================
--
-- This script creates VPD (DBMS_RLS) policies that enforce row-level
-- security on critical tables. Agents can only access data in
-- workspaces they are members of, preventing cross-agent data leakage.
--
-- Prerequisites:
--   - DBMS_RLS must be available (standard in Oracle 23ai/26ai)
--   - Run as SYSDBA or user with EXECUTE on DBMS_RLS
--
-- ============================================================

PROMPT ============================================================
PROMPT Creating VPD policy function: workspace_context_agent_policy
PROMPT ============================================================
-- Restricts WORKSPACE_CONTEXT rows to workspaces the Agent has access to

CREATE OR REPLACE FUNCTION vpd_ws_ctx_agent(
    p_schema VARCHAR2, p_table VARCHAR2
) RETURN VARCHAR2 AS
    v_agent_id VARCHAR2(64);
BEGIN
    v_agent_id := SYS_CONTEXT('AGENT_CTX', 'AGENT_ID');
    IF v_agent_id IS NULL THEN
        RETURN '1=1';  -- Internal/admin connections see all
    END IF;
    RETURN 'WORKSPACE_ID IN (
        SELECT WORKSPACE_ID FROM WORKSPACES WHERE CURRENT_AGENT_ID = ''' || v_agent_id || '''
        UNION
        SELECT WORKSPACE_ID FROM COLLAB_GROUP_MEMBERS WHERE AGENT_ID = ''' || v_agent_id || ''' AND STATUS = ''ACTIVE''
        UNION
        SELECT cg.WORKSPACE_ID FROM COLLAB_GROUPS cg
        JOIN COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
        WHERE cgm.AGENT_ID = ''' || v_agent_id || ''' AND cgm.STATUS = ''ACTIVE''
    )';
END vpd_ws_ctx_agent;
/

PROMPT ============================================================
PROMPT Creating VPD policy function: entities_visibility_policy
PROMPT ============================================================
-- Restricts ENTITIES rows based on visibility rules:
-- PRIVATE: only owner agent
-- SHARED: agents in same workspace
-- PUBLIC: all agents

CREATE OR REPLACE FUNCTION vpd_entities_visibility(
    p_schema VARCHAR2, p_table VARCHAR2
) RETURN VARCHAR2 AS
    v_agent_id VARCHAR2(64);
BEGIN
    v_agent_id := SYS_CONTEXT('AGENT_CTX', 'AGENT_ID');
    IF v_agent_id IS NULL THEN
        RETURN '1=1';
    END IF;
    RETURN 'VISIBILITY = ''PUBLIC''
        OR (VISIBILITY = ''PRIVATE'' AND OWNED_BY_AGENT = ''' || v_agent_id || ''')
        OR (VISIBILITY = ''SHARED'' AND WORKSPACE_ID IN (
            SELECT WORKSPACE_ID FROM WORKSPACES WHERE CURRENT_AGENT_ID = ''' || v_agent_id || '''
            UNION
            SELECT cg.WORKSPACE_ID FROM COLLAB_GROUPS cg
            JOIN COLLAB_GROUP_MEMBERS cgm ON cg.GROUP_ID = cgm.GROUP_ID
            WHERE cgm.AGENT_ID = ''' || v_agent_id || ''' AND cgm.STATUS = ''ACTIVE''
        ))';
END vpd_entities_visibility;
/

PROMPT ============================================================
PROMPT Applying VPD policies to tables
PROMPT ============================================================

BEGIN
    DBMS_RLS.ADD_POLICY(
        OBJECT_SCHEMA   => 'AIADMIN',
        OBJECT_NAME     => 'WORKSPACE_CONTEXT',
        POLICY_NAME     => 'WS_CTX_AGENT_VPD',
        FUNCTION_SCHEMA => 'AIADMIN',
        POLICY_FUNCTION => 'vpd_ws_ctx_agent',
        STATEMENT_TYPES => 'SELECT,UPDATE,DELETE'
    );
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -28613 THEN  -- policy already exists
            RAISE;
        END IF;
END;
/

BEGIN
    DBMS_RLS.ADD_POLICY(
        OBJECT_SCHEMA   => 'AIADMIN',
        OBJECT_NAME     => 'ENTITIES',
        POLICY_NAME     => 'ENTITIES_VISIBILITY_VPD',
        FUNCTION_SCHEMA => 'AIADMIN',
        POLICY_FUNCTION => 'vpd_entities_visibility',
        STATEMENT_TYPES => 'SELECT,UPDATE,DELETE'
    );
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -28613 THEN
            RAISE;
        END IF;
END;
/

PROMPT ============================================================
PROMPT Creating application context for VPD (AGENT_CTX)
PROMPT ============================================================
-- This context is set by the Python API layer when establishing
-- a connection, identifying the connected Agent.

CREATE OR REPLACE CONTEXT AGENT_CTX USING AIADMIN.SET_AGENT_CONTEXT;
/

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
PROMPT Granting SET_AGENT_CONTEXT to AGENT_API
PROMPT ============================================================

GRANT EXECUTE ON AIADMIN.SET_AGENT_CONTEXT TO AGENT_API;

PROMPT ============================================================
PROMPT VPD policies are now active
PROMPT ============================================================
PROMPT
PROMPT IMPORTANT: The Python API layer must call SET_AGENT_CONTEXT
PROMPT           at the start of each session to identify the Agent:
PROMPT           CALL AIADMIN.SET_AGENT_CONTEXT.set_agent_id('AGENT_XXX');
PROMPT ============================================================
