-- ============================================================
-- 5_audit_policy.sql — Unified Auditing for Direct DML Detection
-- AI Agent Infra with OracleDB v3.5.0
-- ============================================================
--
-- This script creates audit policies that detect direct DML
-- operations on critical tables, bypassing the PL/SQL API layer.
-- When an Agent executes INSERT/UPDATE/DELETE directly on tables
-- (instead of through PL/SQL packages), the action is logged.
--
-- Prerequisites:
--   - Unified Auditing must be enabled (default in 26ai)
--   - Run as SYSDBA
--
-- ============================================================

PROMPT ============================================================
PROMPT Creating audit policy: DIRECT_DML_BYPASS_DETECTION
PROMPT ============================================================
-- This policy audits direct DML on critical tables when the
-- connected user is NOT AIADMIN (schema owner), which indicates
-- a bypass of the PL/SQL API layer.

BEGIN
    DBMS_AUDIT_MGMT.CREATE_AUDIT_POLICY(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        condition_expr    => 'SYS_CONTEXT(''USERENV'', ''CURRENT_USER'') != ''AIADMIN''',
        evaluation        => DBMS_AUDIT_MGMT.EVALUATE_PER_STATEMENT
    );
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -47003 THEN  -- policy already exists
            RAISE;
        END IF;
END;
/

PROMPT Adding actions for critical tables...

-- Workspace Context (should only be modified via save_context / WORKSPACE_MANAGER)
BEGIN
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_INSERT,
        object_schema     => 'AIADMIN',
        object_name       => 'WORKSPACE_CONTEXT'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_UPDATE,
        object_schema     => 'AIADMIN',
        object_name       => 'WORKSPACE_CONTEXT'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_DELETE,
        object_schema     => 'AIADMIN',
        object_name       => 'WORKSPACE_CONTEXT'
    );
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

-- Agent Registry (should only be modified via agent_api / AGENT_PERMISSION_MANAGER)
BEGIN
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_INSERT,
        object_schema     => 'AIADMIN',
        object_name       => 'AGENT_REGISTRY'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_UPDATE,
        object_schema     => 'AIADMIN',
        object_name       => 'AGENT_REGISTRY'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_DELETE,
        object_schema     => 'AIADMIN',
        object_name       => 'AGENT_REGISTRY'
    );
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

-- Context Branches (should only be modified via BRANCH_MANAGER)
BEGIN
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_INSERT,
        object_schema     => 'AIADMIN',
        object_name       => 'CONTEXT_BRANCHES'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_UPDATE,
        object_schema     => 'AIADMIN',
        object_name       => 'CONTEXT_BRANCHES'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_DELETE,
        object_schema     => 'AIADMIN',
        object_name       => 'CONTEXT_BRANCHES'
    );
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

-- System Config (contains encryption keys - should never be modified directly)
BEGIN
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_INSERT,
        object_schema     => 'AIADMIN',
        object_name       => 'SYSTEM_CONFIG'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_UPDATE,
        object_schema     => 'AIADMIN',
        object_name       => 'SYSTEM_CONFIG'
    );
    DBMS_AUDIT_MGMT.ADD_POLICY_CONDITION(
        audit_policy_name => 'DIRECT_DML_BYPASS_DETECTION',
        action_code       => DBMS_AUDIT_MGMT.ACTION_DELETE,
        object_schema     => 'AIADMIN',
        object_name       => 'SYSTEM_CONFIG'
    );
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

PROMPT Enabling audit policy...

ALTER AUDIT POLICY DIRECT_DML_BYPASS_DETECTION ENABLE;

PROMPT ============================================================
PROMPT Audit policy DIRECT_DML_BYPASS_DETECTION is now active
PROMPT ============================================================
PROMPT
PROMPT To check for bypass attempts:
PROMPT   SELECT * FROM UNIFIED_AUDIT_TRAIL 
PROMPT   WHERE AUDIT_POLICY_NAME = 'DIRECT_DML_BYPASS_DETECTION'
PROMPT   ORDER BY EVENT_TIMESTAMP DESC;
PROMPT ============================================================

PROMPT ============================================================
PROMPT Network ACL for EMBEDDING_MANAGER (requires SYSDBA)
PROMPT ============================================================
PROMPT
PROMPT The EMBEDDING_MANAGER package uses UTL_HTTP to call the
PROMPT embedding API. Run the following as SYSDBA to grant access:
PROMPT
PROMPT   BEGIN
PROMPT     DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
PROMPT       host => '<embedding_host>',
PROMPT       lower_port => <embedding_port>,
PROMPT       upper_port => <embedding_port>,
PROMPT       ace => xs$ace_type(
PROMPT         privilege_list => xs$name_list('http'),
PROMPT         principal_name => 'AIADMIN',
PROMPT         principal_type => xs_acl.ptype_db
PROMPT       )
PROMPT     );
PROMPT   END;
PROMPT /
PROMPT
PROMPT Default values (from SYSTEM_CONFIG embedding_url):
PROMPT   host: 10.10.10.1, port: 12345
PROMPT ============================================================
