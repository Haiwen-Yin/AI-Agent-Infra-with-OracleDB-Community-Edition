-- ============================================================
-- Oracle Memory System v2.0.0 - Phase 4: Harness Templates
-- ============================================================
-- Idempotent: safe to re-run. Uses safe_ddl/safe_idx helpers.
-- Adds HARNESS_TEMPLATE entity type, HARNESS_META table,
-- and seeds 5 built-in harness templates.
-- ============================================================

WHENEVER SQLERROR CONTINUE;
WHENEVER OSERROR CONTINUE;

-- Helper procedures for idempotent DDL
CREATE OR REPLACE PROCEDURE safe_ddl(p_sql IN VARCHAR2) IS
BEGIN
    EXECUTE IMMEDIATE p_sql;
EXCEPTION
    WHEN OTHERS THEN NULL;
END safe_ddl;
/

CREATE OR REPLACE PROCEDURE safe_idx(p_sql IN VARCHAR2) IS
BEGIN
    EXECUTE IMMEDIATE p_sql;
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -955 THEN NULL; END IF;
END safe_idx;
/

-- ============================================================
-- 1. Extend ENTITIES.CK_ENTITY_TYPE to include HARNESS_TEMPLATE
-- ============================================================

CALL safe_ddl('ALTER TABLE ENTITIES DROP CONSTRAINT CK_ENTITY_TYPE');
CALL safe_ddl('ALTER TABLE ENTITIES ADD CONSTRAINT CK_ENTITY_TYPE CHECK (ENTITY_TYPE IN (''MEMORY'',''KNOWLEDGE'',''TASK_OUTPUT'',''EXPERIENCE'',''HARNESS_TEMPLATE''))');

-- ============================================================
-- 2. Create HARNESS_META table
-- ============================================================

BEGIN
    EXECUTE IMMEDIATE 'CREATE TABLE HARNESS_META (
        ENTITY_ID        NUMBER PRIMARY KEY,
        TEMPLATE_VERSION NUMBER DEFAULT 1,
        TEMPLATE_STATUS  VARCHAR2(32) DEFAULT ''DRAFT'',
        VARIABLES        JSON,
        CHANGELOG        JSON,
        CONSTRAINT FK_HM_ENTITY FOREIGN KEY (ENTITY_ID) REFERENCES ENTITIES(ENTITY_ID) ON DELETE CASCADE,
        CONSTRAINT CK_HM_STATUS CHECK (TEMPLATE_STATUS IN (''DRAFT'',''PUBLISHED'',''DEPRECATED'',''ARCHIVED''))
    )';
EXCEPTION
    WHEN OTHERS THEN NULL;
END;
/

COMMENT ON TABLE HARNESS_META IS 'Extended metadata for HARNESS_TEMPLATE-type entities';
COMMENT ON COLUMN HARNESS_META.ENTITY_ID IS 'FK to ENTITIES.ENTITY_ID for the harness template';
COMMENT ON COLUMN HARNESS_META.TEMPLATE_VERSION IS 'Version number of the template, incremented on each publish';
COMMENT ON COLUMN HARNESS_META.TEMPLATE_STATUS IS 'Lifecycle status: DRAFT, PUBLISHED, DEPRECATED, ARCHIVED';
COMMENT ON COLUMN HARNESS_META.VARIABLES IS 'JSON object defining template variables and their default values';
COMMENT ON COLUMN HARNESS_META.CHANGELOG IS 'JSON array of version change records';

-- ============================================================
-- 3. Index on HARNESS_META
-- ============================================================

CALL safe_idx('CREATE INDEX IDX_HM_STATUS ON HARNESS_META(TEMPLATE_STATUS)');

-- ============================================================
-- 4. Update ENTITY_EDGES.EDGE_TYPE comment
-- ============================================================

COMMENT ON COLUMN ENTITY_EDGES.EDGE_TYPE IS 'Edge types: DEPENDS_ON, RELATED_TO, DERIVED_FROM, CAUSES, ENABLES, PREVENTS, SIMILAR_TO, EVOLVED_FROM, CONTRADICTS, SUPPORTS, DERIVES_FROM, USES_HARNESS';

-- ============================================================
-- 5. Seed built-in harness templates
-- ============================================================

-- 5a. Research Analyst
MERGE INTO ENTITIES e
USING (SELECT 'Research Analyst' AS NAME FROM DUAL) s
ON (e.NAME = s.NAME AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE')
WHEN NOT MATCHED THEN
    INSERT (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS, VISIBILITY, METADATA)
    VALUES (
        'HARNESS_TEMPLATE',
        'Research Analyst',
        'Harness template for research and analysis tasks',
        'research',
        2,
        'ACTIVE',
        'SHARED',
        JSON {
            'category': 'research',
            'prompt_templates': {
                'system': 'You are a {role} specializing in {domain}. Your objective is to {objective}. Use the memory system to retrieve relevant knowledge and store findings.',
                'user': '{query}',
                'response': '## Findings\n{findings}\n## Sources\n{sources}'
            },
            'tool_bindings': ['knowledge_tools', 'memory_tools'],
            'variables': {
                'role': 'Research Analyst',
                'domain': 'general',
                'objective': 'find patterns and insights',
                'query': '',
                'findings': '',
                'sources': ''
            },
            'guardrails': {
                'preset': 'balanced'
            },
            'memory_access': {
                'short_term': true,
                'long_term': true,
                'compaction': true,
                'access_policy': 'read_write'
            },
            'evaluation': {
                'output_format': 'structured',
                'quality_threshold': 0.8
            }
        }
    );

-- 5b. Code Assistant
MERGE INTO ENTITIES e
USING (SELECT 'Code Assistant' AS NAME FROM DUAL) s
ON (e.NAME = s.NAME AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE')
WHEN NOT MATCHED THEN
    INSERT (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS, VISIBILITY, METADATA)
    VALUES (
        'HARNESS_TEMPLATE',
        'Code Assistant',
        'Harness template for code generation and development tasks',
        'development',
        2,
        'ACTIVE',
        'SHARED',
        JSON {
            'category': 'development',
            'prompt_templates': {
                'system': 'You are a {role} with expertise in {language}. {guidelines}',
                'user': '{task}',
                'response': '## Solution\n{solution}\n## Explanation\n{explanation}'
            },
            'tool_bindings': ['knowledge_tools', 'task_tools'],
            'variables': {
                'role': 'Code Assistant',
                'language': 'Python',
                'guidelines': 'Follow clean code principles',
                'task': '',
                'solution': '',
                'explanation': ''
            },
            'guardrails': {
                'preset': 'balanced'
            },
            'evaluation': {
                'output_format': 'code_block',
                'quality_threshold': 0.9
            }
        }
    );

-- 5c. Data Analyst
MERGE INTO ENTITIES e
USING (SELECT 'Data Analyst' AS NAME FROM DUAL) s
ON (e.NAME = s.NAME AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE')
WHEN NOT MATCHED THEN
    INSERT (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS, VISIBILITY, METADATA)
    VALUES (
        'HARNESS_TEMPLATE',
        'Data Analyst',
        'Harness template for data analysis and reporting tasks',
        'analytics',
        2,
        'ACTIVE',
        'SHARED',
        JSON {
            'category': 'analytics',
            'prompt_templates': {
                'system': 'You are a {role} focused on {focus_area}. Analyze data and provide insights.',
                'user': '{data_query}',
                'response': '## Analysis\n{analysis}\n## Recommendations\n{recommendations}'
            },
            'tool_bindings': ['knowledge_tools', 'memory_tools'],
            'variables': {
                'role': 'Data Analyst',
                'focus_area': 'business metrics',
                'data_query': '',
                'analysis': '',
                'recommendations': ''
            },
            'guardrails': {
                'preset': 'conservative'
            },
            'evaluation': {
                'output_format': 'report',
                'quality_threshold': 0.85
            }
        }
    );

-- 5d. Task Planner
MERGE INTO ENTITIES e
USING (SELECT 'Task Planner' AS NAME FROM DUAL) s
ON (e.NAME = s.NAME AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE')
WHEN NOT MATCHED THEN
    INSERT (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS, VISIBILITY, METADATA)
    VALUES (
        'HARNESS_TEMPLATE',
        'Task Planner',
        'Harness template for task decomposition and planning',
        'orchestration',
        2,
        'ACTIVE',
        'SHARED',
        JSON {
            'category': 'orchestration',
            'prompt_templates': {
                'system': 'You are a {role} that breaks down objectives into executable steps. {constraints}',
                'user': '{objective}',
                'response': '## Plan\n{plan}\n## Dependencies\n{dependencies}'
            },
            'tool_bindings': ['task_tools', 'agent_tools'],
            'variables': {
                'role': 'Task Planner',
                'constraints': 'Maximum 10 steps per plan',
                'objective': '',
                'plan': '',
                'dependencies': ''
            },
            'guardrails': {
                'preset': 'balanced'
            },
            'evaluation': {
                'output_format': 'structured_plan',
                'quality_threshold': 0.8
            }
        }
    );

-- 5e. Security Auditor
MERGE INTO ENTITIES e
USING (SELECT 'Security Auditor' AS NAME FROM DUAL) s
ON (e.NAME = s.NAME AND e.ENTITY_TYPE = 'HARNESS_TEMPLATE')
WHEN NOT MATCHED THEN
    INSERT (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS, VISIBILITY, METADATA)
    VALUES (
        'HARNESS_TEMPLATE',
        'Security Auditor',
        'Harness template for security review and compliance auditing',
        'security',
        2,
        'ACTIVE',
        'SHARED',
        JSON {
            'category': 'security',
            'prompt_templates': {
                'system': 'You are a {role} that reviews actions for compliance. {policies}',
                'user': '{action}',
                'response': '## Assessment\n{assessment}\n## Risks\n{risks}\n## Mitigations\n{mitigations}'
            },
            'tool_bindings': ['security_tools', 'knowledge_tools'],
            'variables': {
                'role': 'Security Auditor',
                'policies': 'Enforce data masking and access control',
                'action': '',
                'assessment': '',
                'risks': '',
                'mitigations': ''
            },
            'guardrails': {
                'preset': 'conservative'
            },
            'evaluation': {
                'output_format': 'audit_report',
                'quality_threshold': 0.95
            }
        }
    );

-- ============================================================
-- 6. Seed HARNESS_META rows and set to PUBLISHED
-- ============================================================

INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG)
SELECT e.ENTITY_ID, 1, 'PUBLISHED',
       e.METADATA.VARIABLES,
       JSON [{'version': 1, 'status': 'PUBLISHED', 'timestamp': TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')}]
FROM ENTITIES e
WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
  AND e.NAME = 'Research Analyst'
  AND NOT EXISTS (
      SELECT 1 FROM HARNESS_META hm WHERE hm.ENTITY_ID = e.ENTITY_ID
  );

INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG)
SELECT e.ENTITY_ID, 1, 'PUBLISHED',
       e.METADATA.VARIABLES,
       JSON [{'version': 1, 'status': 'PUBLISHED', 'timestamp': TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')}]
FROM ENTITIES e
WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
  AND e.NAME = 'Code Assistant'
  AND NOT EXISTS (
      SELECT 1 FROM HARNESS_META hm WHERE hm.ENTITY_ID = e.ENTITY_ID
  );

INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG)
SELECT e.ENTITY_ID, 1, 'PUBLISHED',
       e.METADATA.VARIABLES,
       JSON [{'version': 1, 'status': 'PUBLISHED', 'timestamp': TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')}]
FROM ENTITIES e
WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
  AND e.NAME = 'Data Analyst'
  AND NOT EXISTS (
      SELECT 1 FROM HARNESS_META hm WHERE hm.ENTITY_ID = e.ENTITY_ID
  );

INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG)
SELECT e.ENTITY_ID, 1, 'PUBLISHED',
       e.METADATA.VARIABLES,
       JSON [{'version': 1, 'status': 'PUBLISHED', 'timestamp': TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')}]
FROM ENTITIES e
WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
  AND e.NAME = 'Task Planner'
  AND NOT EXISTS (
      SELECT 1 FROM HARNESS_META hm WHERE hm.ENTITY_ID = e.ENTITY_ID
  );

INSERT INTO HARNESS_META (ENTITY_ID, TEMPLATE_VERSION, TEMPLATE_STATUS, VARIABLES, CHANGELOG)
SELECT e.ENTITY_ID, 1, 'PUBLISHED',
       e.METADATA.VARIABLES,
       JSON [{'version': 1, 'status': 'PUBLISHED', 'timestamp': TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS')}]
FROM ENTITIES e
WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
  AND e.NAME = 'Security Auditor'
  AND NOT EXISTS (
      SELECT 1 FROM HARNESS_META hm WHERE hm.ENTITY_ID = e.ENTITY_ID
  );

-- Ensure all seeded templates are set to PUBLISHED (idempotent update)
UPDATE HARNESS_META hm
SET hm.TEMPLATE_STATUS = 'PUBLISHED'
WHERE hm.ENTITY_ID IN (
    SELECT e.ENTITY_ID FROM ENTITIES e
    WHERE e.ENTITY_TYPE = 'HARNESS_TEMPLATE'
      AND e.NAME IN ('Research Analyst','Code Assistant','Data Analyst','Task Planner','Security Auditor')
);

-- ============================================================
-- 7. System config entry
-- ============================================================

MERGE INTO SYSTEM_CONFIG t
USING (SELECT 'harness.builtin_templates' AS CONFIG_KEY FROM DUAL) s
ON (t.CONFIG_KEY = s.CONFIG_KEY)
WHEN NOT MATCHED THEN
    INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
    VALUES ('harness.builtin_templates', '5', 'Number of built-in harness templates')
WHEN MATCHED THEN
    UPDATE SET CONFIG_VALUE = '5';

COMMIT;

-- Cleanup helpers
DROP PROCEDURE IF EXISTS safe_ddl;
DROP PROCEDURE IF EXISTS safe_idx;

-- ============================================================
-- End Phase 4: Harness Templates
-- ============================================================
