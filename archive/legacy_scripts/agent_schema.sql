-- ============================================================================
-- Oracle Memory System v0.4.2 - Multi-Agent Architecture Extensions
-- ============================================================================
-- Description: Schema extensions for multi-agent memory system with shared
--              and private memories, access control, and collaboration features
-- Version: 0.4.2
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-07
-- ============================================================================

-- ============================================================================
-- SECTION 1: AGENT REGISTRY - Agent Registration & Discovery
-- ============================================================================

CREATE TABLE agent_registry (
    AGENT_ID          VARCHAR2(64) PRIMARY KEY,
    AGENT_NAME        VARCHAR2(100) NOT NULL,
    AGENT_TYPE        VARCHAR2(50),  -- 'analysis', 'writing', 'deployment', 'research'...
    DESCRIPTION       CLOB,
    STATUS            VARCHAR2(20) DEFAULT 'ACTIVE',
    CAPABILITIES      CLOB,          -- JSON: ["text-analysis", "code-review", "db-admin"]
    PERMISSION_LEVEL  VARCHAR2(20) DEFAULT 'READ_WRITE',
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    UPDATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

COMMENT ON TABLE agent_registry IS 'Registry of registered agents with capabilities and permissions';
COMMENT ON COLUMN agent_registry.AGENT_ID IS 'Unique identifier for the agent';
COMMENT ON COLUMN agent_registry.CAPABILITIES IS 'JSON array of agent capabilities';

-- Index for fast agent lookup by type/capability
CREATE INDEX idx_agent_registry_type ON agent_registry(agent_type);
CREATE INDEX idx_agent_registry_status ON agent_registry(status);

-- ============================================================================
-- SECTION 2: MEMORY SCOPE EXTENSION - Add visibility fields to existing table
-- ============================================================================

ALTER TABLE memories ADD (
    OWNED_BY_AGENT   VARCHAR2(64),        -- NULL = shared across all agents, otherwise private to agent
    VISIBILITY       VARCHAR2(20) DEFAULT 'SHARED',  -- SHARED / PRIVATE / COLLABORATIVE
    ACCESSIBLE_TO    CLOB,                -- JSON array: ['agent-1', 'agent-2'] for COLLABORATIVE type
    SCOPE_CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

COMMENT ON TABLE memories IS 'Extended with multi-agent visibility support';
COMMENT ON COLUMN memories.OWNED_BY_AGENT IS 'Agent ID that owns this memory (NULL = shared)';
COMMENT ON COLUMN memories.VISIBILITY IS 'Memory visibility: SHARED, PRIVATE, or COLLABORATIVE';
COMMENT ON COLUMN memories.ACCESSIBLE_TO IS 'JSON array of agent IDs for collaborative access';

-- Add indexes for efficient scope-based queries
CREATE INDEX idx_memories_scope_visibility ON memories(visibility);
CREATE INDEX idx_memories_owner_agent      ON memories(owned_by_agent);
CREATE INDEX idx_memories_scope_created    ON memories(scope_created_at);

-- ============================================================================
-- SECTION 3: AGENT MEMORY ACCESS - Access Audit Trail
-- ============================================================================

CREATE TABLE agent_memory_access (
    ACCESS_ID       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    AGENT_ID        VARCHAR2(64) NOT NULL REFERENCES agent_registry(AGENT_ID),
    MEMORY_ID       NUMBER NOT NULL,  -- References memories.ID
    ACCESS_TYPE     VARCHAR2(20),      -- 'READ', 'WRITE', 'DELETE'
    ACCESS_TIME     TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    IP_ADDRESS      VARCHAR2(45),
    SESSION_TOKEN   VARCHAR2(128)
);

COMMENT ON TABLE agent_memory_access IS 'Audit trail for all memory access operations';
COMMENT ON COLUMN agent_memory_access.ACCESS_TYPE IS 'Type of access: READ, WRITE, DELETE';

CREATE INDEX idx_access_audit_agent ON agent_memory_access(agent_id, access_time);
CREATE INDEX idx_access_audit_memory ON agent_memory_access(memory_id, access_time);

-- ============================================================================
-- SECTION 4: AGENT COLLABORATION - Agent-to-Agent Knowledge Sharing
-- ============================================================================

CREATE TABLE agent_collaboration (
    COLLAB_ID       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    SHARING_AGENT   VARCHAR2(64) NOT NULL REFERENCES agent_registry(AGENT_ID),
    RECEIVING_AGENT VARCHAR2(64) NOT NULL REFERENCES agent_registry(AGENT_ID),
    MEMORY_ID       NUMBER NOT NULL,  -- References memories.ID
    SHARE_REASON    VARCHAR2(200),
    STATUS          VARCHAR2(20) DEFAULT 'PENDING',  -- PENDING / ACCEPTED / REJECTED
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    APPROVED_AT     TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE agent_collaboration IS 'Tracks collaboration requests between agents';
COMMENT ON COLUMN agent_collaboration.STATUS IS 'Request status: PENDING, ACCEPTED, REJECTED';

CREATE INDEX idx_collab_status ON agent_collaboration(status);
CREATE INDEX idx_collab_sharing_agent ON agent_collaboration(sharing_agent);
CREATE INDEX idx_collab_receiving_agent ON agent_collaboration(receiving_agent);

-- ============================================================================
-- SECTION 5: AGENT SESSION - Agent Session Management
-- ============================================================================

CREATE TABLE agent_session (
    SESSION_ID        VARCHAR2(128) PRIMARY KEY,
    AGENT_ID          VARCHAR2(64) NOT NULL REFERENCES agent_registry(AGENT_ID),
    START_TIME        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    END_TIME          TIMESTAMP WITH TIME ZONE,
    IS_ACTIVE         VARCHAR2(1) DEFAULT 'Y',
    CONTEXT_SNAPSHOT  CLOB,              -- JSON: current working context
    WORKING_MEMORY_ID NUMBER             -- Memory ID currently being worked on
);

COMMENT ON TABLE agent_session IS 'Active session tracking for agents';
COMMENT ON COLUMN agent_session.IS_ACTIVE IS 'Whether the session is still active (Y/N)';
COMMENT ON COLUMN agent_session.WORKING_MEMORY_ID IS 'Currently processed memory ID';

CREATE INDEX idx_agent_session_agent ON agent_session(agent_id, is_active);
CREATE INDEX idx_agent_session_active ON agent_session(is_active, start_time);

-- ============================================================================
-- SECTION 6: VIEWS FOR COMMON QUERY PATTERNS
-- ============================================================================

-- View: Agent's accessible memories (SHARED + PRIVATE + COLLABORATIVE)
CREATE OR REPLACE VIEW v_agent_accessible_memories AS
SELECT 
    m.ID as memory_id,
    m.VISIBILITY,
    m.OWNED_BY_AGENT,
    m.ACCESSIBLE_TO,
    CASE 
        WHEN m.VISIBILITY = 'SHARED' THEN 100
        WHEN m.VISIBILITY = 'PRIVATE' AND m.OWNED_BY_AGENT IS NOT NULL THEN 50
        WHEN m.VISIBILITY = 'COLLABORATIVE' THEN 75
        ELSE 0
    END as access_level,
    m.CREATED_AT as memory_created_at
FROM memories m
WHERE 
    -- SHARED: visible to everyone
    m.VISIBILITY = 'SHARED' OR
    -- PRIVATE: only owner can see
    (m.VISIBILITY = 'PRIVATE' AND m.OWNED_BY_AGENT IS NOT NULL) OR
    -- COLLABORATIVE: check ACCESSIBLE_TO JSON array
    (m.VISIBILITY = 'COLLABORATIVE');

-- View: Agent registry with capabilities parsed as readable format
CREATE OR REPLACE VIEW v_agent_capabilities AS
SELECT 
    ar.AGENT_ID,
    ar.AGENT_NAME,
    ar.AGENT_TYPE,
    ar.DESCRIPTION,
    ar.STATUS,
    ar.PERMISSION_LEVEL,
    ar.CAPABILITIES,
    -- Parse JSON array for display
    CASE 
        WHEN ar.CAPABILITIES IS NOT NULL THEN 
            REPLACE(REPLACE(ar.CAPABILITIES, '[', ''), ']', '')
        ELSE ''
    END as capabilities_list,
    ar.CREATED_AT,
    ar.UPDATED_AT
FROM agent_registry ar;

-- View: Active sessions with memory context
CREATE OR REPLACE VIEW v_active_sessions AS
SELECT 
    s.SESSION_ID,
    s.AGENT_ID,
    a.AGENT_NAME,
    s.START_TIME,
    s.END_TIME,
    CASE WHEN s.IS_ACTIVE = 'Y' THEN 'ACTIVE' ELSE 'INACTIVE' END as session_status,
    s.CONTEXT_SNAPSHOT,
    s.WORKING_MEMORY_ID,
    m.VISIBILITY as working_memory_visibility
FROM agent_session s
LEFT JOIN agent_registry a ON s.AGENT_ID = a.AGENT_ID
LEFT JOIN memories m ON s.WORKING_MEMORY_ID = m.ID
WHERE s.IS_ACTIVE = 'Y';

-- ============================================================================
-- SECTION 7: SEED DATA - Sample Agent Registration (Optional)
-- ============================================================================

INSERT INTO agent_registry (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION, CAPABILITIES, STATUS, PERMISSION_LEVEL) 
VALUES ('agent-analysis-01', 'Analysis Agent', 'analysis', 'AI agent for data analysis and pattern recognition', '["data-analysis", "pattern-recognition", "statistics"]', 'ACTIVE', 'READ_WRITE');

INSERT INTO agent_registry (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION, CAPABILITIES, STATUS, PERMISSION_LEVEL) 
VALUES ('agent-writing-01', 'Writing Agent', 'writing', 'AI agent for content generation and documentation', '["content-generation", "documentation", "translation"]', 'ACTIVE', 'READ_WRITE');

INSERT INTO agent_registry (AGENT_ID, AGENT_NAME, AGENT_TYPE, DESCRIPTION, CAPABILITIES, STATUS, PERMISSION_LEVEL) 
VALUES ('agent-deployment-01', 'Deployment Agent', 'deployment', 'AI agent for system deployment and configuration management', '["deployment", "configuration-management", "monitoring"]', 'ACTIVE', 'READ_WRITE');

-- ============================================================================
-- SECTION 8: VALIDATION QUERIES - Verify Schema Integrity
-- ============================================================================

-- Check all new tables exist
SELECT TABLE_NAME FROM USER_TABLES 
WHERE TABLE_NAME IN (
    'AGENT_REGISTRY', 'AGENT_MEMORY_ACCESS', 'AGENT_COLLABORATION', 
    'AGENT_SESSION'
) OR TABLE_NAME LIKE '%MEMORIES%' AND TABLE_NAME NOT LIKE 'V_%';

-- Check memory table extensions
SELECT COLUMN_NAME, DATA_TYPE, DEFAULT_VALUE 
FROM USER_TAB_COLUMNS 
WHERE TABLE_NAME = 'MEMORIES' AND COLUMN_NAME IN ('OWNED_BY_AGENT', 'VISIBILITY', 'ACCESSIBLE_TO');

-- Verify views created
SELECT VIEW_NAME FROM USER_VIEWS WHERE VIEW_NAME LIKE 'V_AGENT%';

-- ============================================================================
-- END OF DDL SCRIPT
-- ============================================================================
