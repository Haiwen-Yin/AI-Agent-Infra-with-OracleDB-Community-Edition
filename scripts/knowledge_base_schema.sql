-- ============================================================================
-- Oracle Memory System v1.0.0 - Knowledge Base Schema
-- ============================================================================
-- Description: Database schema for Knowledge Base with Knowledge Graph support
-- Version: 0.6.0-KB
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: KNOWLEDGE CONCEPTS - Core knowledge entities
-- ============================================================================

CREATE TABLE KNOWLEDGE_CONCEPTS (
    CONCEPT_ID      NUMBER PRIMARY KEY,
    CONCEPT_NAME    VARCHAR2(200) NOT NULL,
    CONCEPT_TYPE    VARCHAR2(50) NOT NULL,              -- FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE
    CATEGORY        VARCHAR2(100),
    
    -- Content
    TITLE           VARCHAR2(500),
    DESCRIPTION     CLOB,
    CONTENT         CLOB,
    
    -- Source & Provenance
    SOURCE_TYPE     VARCHAR2(50) DEFAULT 'MANUAL',     -- MANUAL/DISTILLED/IMPORTED/VERIFIED
    SOURCE_MEMORY_IDS CLOB,                            -- JSON: [memory_id1, memory_id2, ...]
    CONFIDENCE      NUMBER(3,2) CHECK (CONFIDENCE BETWEEN 0 AND 1) DEFAULT 0.8,
    VALIDATION_STATUS VARCHAR2(30) DEFAULT 'PENDING',  -- PENDING/VALIDATED/REJECTED/DEPRECATED
    
    -- Embedding for semantic search
    EMBEDDING       VECTOR(1024),
    
    -- Metadata
    TAGS            CLOB,                              -- JSON: ["tag1", "tag2", ...]
    METADATA        CLOB,                              -- JSON: additional metadata
    
    -- Timestamps
    CREATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    UPDATED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    VALIDATED_AT    TIMESTAMP WITH TIME ZONE,
    DEPRECATED_AT   TIMESTAMP WITH TIME ZONE,
    
    -- Versioning
    VERSION         NUMBER DEFAULT 1,
    IS_CURRENT      VARCHAR2(1) DEFAULT 'Y' CHECK (IS_CURRENT IN ('Y','N'))
);

-- Indexes
CREATE INDEX IDX_KNOWLEDGE_CONCEPTS_TYPE ON KNOWLEDGE_CONCEPTS(CONCEPT_TYPE);
CREATE INDEX IDX_KNOWLEDGE_CONCEPTS_CATEGORY ON KNOWLEDGE_CONCEPTS(CATEGORY);
CREATE INDEX IDX_KNOWLEDGE_CONCEPTS_VALIDATION ON KNOWLEDGE_CONCEPTS(VALIDATION_STATUS);
CREATE INDEX IDX_KNOWLEDGE_CONCEPTS_CREATED ON KNOWLEDGE_CONCEPTS(CREATED_AT DESC);

-- Comments
COMMENT ON TABLE KNOWLEDGE_CONCEPTS IS 'Core knowledge entities with semantic embeddings';
COMMENT ON COLUMN KNOWLEDGE_CONCEPTS.CONCEPT_TYPE IS 'Knowledge type: FACT, RULE, PATTERN, EXPERIENCE, PRINCIPLE';
COMMENT ON COLUMN KNOWLEDGE_CONCEPTS.VALIDATION_STATUS IS 'Validation state: PENDING, VALIDATED, REJECTED, DEPRECATED';
COMMENT ON COLUMN KNOWLEDGE_CONCEPTS.CONFIDENCE IS 'Knowledge confidence score (0.00 - 1.00)';

-- Sequence
CREATE SEQUENCE SEQ_KNOWLEDGE_CONCEPTS START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 2: KNOWLEDGE GRAPH - Knowledge relationships
-- ============================================================================

CREATE TABLE KNOWLEDGE_GRAPH (
    RELATIONSHIP_ID   NUMBER PRIMARY KEY,
    SOURCE_CONCEPT_ID NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    TARGET_CONCEPT_ID NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    
    -- Relationship type
    RELATIONSHIP_TYPE VARCHAR2(100) NOT NULL,           -- IS_A/PART_OF/CAUSES/ENABLES/CONTRADICTS/SUPPORTS
    RELATIONSHIP_STRENGTH NUMBER(3,2) DEFAULT 1.0,
    
    -- Properties
    PROPERTIES        CLOB,
    
    -- Timestamps
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    UPDATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    
    -- Source
    SOURCE_TYPE       VARCHAR2(50) DEFAULT 'MANUAL',
    CONFIDENCE        NUMBER(3,2) DEFAULT 0.8,
    
    -- Ensure no self-references
    CONSTRAINT CHECK_NO_SELF_REF CHECK (SOURCE_CONCEPT_ID != TARGET_CONCEPT_ID)
);

-- Indexes
CREATE INDEX IDX_KNOWLEDGE_GRAPH_SOURCE ON KNOWLEDGE_GRAPH(SOURCE_CONCEPT_ID);
CREATE INDEX IDX_KNOWLEDGE_GRAPH_TARGET ON KNOWLEDGE_GRAPH(TARGET_CONCEPT_ID);
CREATE INDEX IDX_KNOWLEDGE_GRAPH_TYPE ON KNOWLEDGE_GRAPH(RELATIONSHIP_TYPE);

-- Comments
COMMENT ON TABLE KNOWLEDGE_GRAPH IS 'Knowledge relationships for graph traversal';
COMMENT ON COLUMN KNOWLEDGE_GRAPH.RELATIONSHIP_TYPE IS 'Relationship type: IS_A, PART_OF, CAUSES, ENABLES, etc.';

-- Sequence
CREATE SEQUENCE SEQ_KNOWLEDGE_GRAPH START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 3: KNOWLEDGE_VERSIONS - Version history
-- ============================================================================

CREATE TABLE KNOWLEDGE_VERSIONS (
    VERSION_ID        NUMBER PRIMARY KEY,
    CONCEPT_ID        NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    
    -- Version content
    TITLE             VARCHAR2(500),
    DESCRIPTION       CLOB,
    CONTENT           CLOB,
    
    -- Change tracking
    CHANGE_SUMMARY    CLOB,
    CHANGE_REASON     VARCHAR2(500),
    
    -- Timestamps
    VERSIONED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    VERSIONED_BY      VARCHAR2(64)
);

CREATE INDEX IDX_KNOWLEDGE_VERSIONS_CONCEPT ON KNOWLEDGE_VERSIONS(CONCEPT_ID, VERSIONED_AT DESC);

-- Comments
COMMENT ON TABLE KNOWLEDGE_VERSIONS IS 'Version history for knowledge concepts';

-- Sequence
CREATE SEQUENCE SEQ_KNOWLEDGE_VERSIONS START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 4: KNOWLEDGE_TAGS - Tag-based categorization
-- ============================================================================

CREATE TABLE KNOWLEDGE_TAGS (
    TAG_ID            NUMBER PRIMARY KEY,
    TAG_NAME          VARCHAR2(100) NOT NULL UNIQUE,
    TAG_CATEGORY      VARCHAR2(50),                     -- DOMAIN/TECHNOLOGY/TOPIC
    USAGE_COUNT       NUMBER DEFAULT 0,
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

CREATE TABLE KNOWLEDGE_CONCEPT_TAGS (
    CONCEPT_ID        NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    TAG_ID            NUMBER NOT NULL REFERENCES KNOWLEDGE_TAGS(TAG_ID),
    PRIMARY KEY (CONCEPT_ID, TAG_ID)
);

-- Comments
COMMENT ON TABLE KNOWLEDGE_TAGS IS 'Tags for knowledge categorization';
COMMENT ON TABLE KNOWLEDGE_CONCEPT_TAGS IS 'Many-to-many relationship between concepts and tags';

-- Sequence
CREATE SEQUENCE SEQ_KNOWLEDGE_TAGS START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 5: KNOWLEDGE_DISTILLATION_LOG - Track memory-to-knowledge distillation
-- ============================================================================

CREATE TABLE KNOWLEDGE_DISTILLATION_LOG (
    DISTILLATION_ID   NUMBER PRIMARY KEY,
    
    -- Source memories
    MEMORY_IDS        CLOB,                             -- JSON: [memory_id1, memory_id2, ...]
    MEMORY_COUNT      NUMBER,
    MEMORY_TIME_RANGE VARCHAR2(100),
    
    -- Distillation result
    KNOWLEDGE_TYPE    VARCHAR2(50),
    KNOWLEDGE_TITLE   VARCHAR2(500),
    CONFIDENCE        NUMBER(3,2),
    
    -- Process
    DISTILLATION_METHOD VARCHAR2(50),                   -- AUTOMATIC/MANUAL/HYBRID
    TRIGGERED_BY      VARCHAR2(100),
    PATTERN_DETECTED  CLOB,
    
    -- Result
    KNOWLEDGE_ID      NUMBER REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    STATUS            VARCHAR2(30) DEFAULT 'PENDING',   -- PENDING/COMPLETED/FAILED
    
    -- Timestamps
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    COMPLETED_AT      TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IDX_DISTILLATION_LOG_CREATED ON KNOWLEDGE_DISTILLATION_LOG(CREATED_AT DESC);

-- Comments
COMMENT ON TABLE KNOWLEDGE_DISTILLATION_LOG IS 'Audit trail for memory-to-knowledge distillation';

-- Sequence
CREATE SEQUENCE SEQ_DISTILLATION_LOG START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 6: KNOWLEDGE_SEARCH_HISTORY - Track knowledge usage
-- ============================================================================

CREATE TABLE KNOWLEDGE_SEARCH_HISTORY (
    SEARCH_ID         NUMBER PRIMARY KEY,
    QUERY_TEXT        CLOB,
    QUERY_EMBEDDING   VECTOR(1024),
    
    -- Results
    RESULT_COUNT      NUMBER,
    TOP_RESULT_ID     NUMBER REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    RELEVANCE_SCORE   NUMBER(3,2),
    
    -- User feedback
    USER_CLICKED      VARCHAR2(1) DEFAULT 'N',
    USER_HELPFUL      VARCHAR2(1),
    
    -- Context
    SEARCH_CONTEXT    VARCHAR2(50),
    SESSION_ID        NUMBER,
    
    -- Timestamps
    SEARCHED_AT       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

CREATE INDEX IDX_KNOWLEDGE_SEARCH_HISTORY ON KNOWLEDGE_SEARCH_HISTORY(SEARCHED_AT DESC);

-- Comments
COMMENT ON TABLE KNOWLEDGE_SEARCH_HISTORY IS 'Search history for knowledge retrieval analytics';

-- Sequence
CREATE SEQUENCE SEQ_SEARCH_HISTORY START WITH 1 INCREMENT BY 1;

-- ============================================================================
-- SECTION 7: VIEWS - Useful views for knowledge management
-- ============================================================================

-- View: Knowledge statistics by type
CREATE OR REPLACE VIEW V_KNOWLEDGE_STATS_BY_TYPE AS
SELECT 
    CONCEPT_TYPE,
    COUNT(*) as TOTAL_COUNT,
    COUNT(CASE WHEN VALIDATION_STATUS = 'VALIDATED' THEN 1 END) as VALIDATED_COUNT,
    COUNT(CASE WHEN VALIDATION_STATUS = 'PENDING' THEN 1 END) as PENDING_COUNT,
    AVG(CONFIDENCE) as AVG_CONFIDENCE,
    MIN(CREATED_AT) as OLDEST_KNOWLEDGE,
    MAX(CREATED_AT) as NEWEST_KNOWLEDGE
FROM KNOWLEDGE_CONCEPTS
GROUP BY CONCEPT_TYPE;

-- View: Knowledge statistics by category
CREATE OR REPLACE VIEW V_KNOWLEDGE_STATS_BY_CATEGORY AS
SELECT 
    CATEGORY,
    COUNT(*) as TOTAL_COUNT,
    COUNT(CASE WHEN VALIDATION_STATUS = 'VALIDATED' THEN 1 END) as VALIDATED_COUNT,
    AVG(CONFIDENCE) as AVG_CONFIDENCE
FROM KNOWLEDGE_CONCEPTS
WHERE CATEGORY IS NOT NULL
GROUP BY CATEGORY;

-- View: Recently validated knowledge
CREATE OR REPLACE VIEW V_RECENTLY_VALIDATED AS
SELECT 
    CONCEPT_ID,
    CONCEPT_NAME,
    CONCEPT_TYPE,
    CATEGORY,
    TITLE,
    CONFIDENCE,
    VALIDATED_AT
FROM KNOWLEDGE_CONCEPTS
WHERE VALIDATION_STATUS = 'VALIDATED'
  AND VALIDATED_AT IS NOT NULL
ORDER BY VALIDATED_AT DESC
FETCH FIRST 20 ROWS ONLY;

-- View: Knowledge requiring attention
CREATE OR REPLACE VIEW V_KNOWLEDGE_NEEDING_ATTENTION AS
SELECT 
    CONCEPT_ID,
    CONCEPT_NAME,
    CONCEPT_TYPE,
    CATEGORY,
    TITLE,
    VALIDATION_STATUS,
    CONFIDENCE,
    CREATED_AT
FROM KNOWLEDGE_CONCEPTS
WHERE VALIDATION_STATUS IN ('PENDING', 'REJECTED')
   OR CONFIDENCE < 0.5
ORDER BY CREATED_AT DESC;

-- ============================================================================
-- SECTION 8: TRIGGERS - Automatic timestamp updates
-- ============================================================================

CREATE OR REPLACE TRIGGER TRG_KNOWLEDGE_CONCEPTS_UPDATED
BEFORE UPDATE ON KNOWLEDGE_CONCEPTS
FOR EACH ROW
BEGIN
    :NEW.UPDATED_AT := SYSTIMESTAMP;
END;
/

CREATE OR REPLACE TRIGGER TRG_KNOWLEDGE_GRAPH_UPDATED
BEFORE UPDATE ON KNOWLEDGE_GRAPH
FOR EACH ROW
BEGIN
    :NEW.UPDATED_AT := SYSTIMESTAMP;
END;
/

-- ============================================================================
-- SECTION 9: COMMENTS - Table and column documentation
-- ============================================================================

-- Additional table comments
COMMENT ON TABLE KNOWLEDGE_CONCEPTS IS 'Core knowledge entities - FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE';
COMMENT ON TABLE KNOWLEDGE_GRAPH IS 'Knowledge relationships for graph-based reasoning';
COMMENT ON TABLE KNOWLEDGE_VERSIONS IS 'Version history for knowledge concepts';
COMMENT ON TABLE KNOWLEDGE_TAGS IS 'Tags for knowledge categorization';
COMMENT ON TABLE KNOWLEDGE_CONCEPT_TAGS IS 'Many-to-many relationship between concepts and tags';
COMMENT ON TABLE KNOWLEDGE_DISTILLATION_LOG IS 'Audit trail for memory-to-knowledge distillation';
COMMENT ON TABLE KNOWLEDGE_SEARCH_HISTORY IS 'Search history for knowledge retrieval analytics';

-- ============================================================================
-- SECTION 10: VALIDATION - Verify schema creation
-- ============================================================================

-- Verify tables created
SELECT TABLE_NAME, NUM_ROWS 
FROM USER_TABLES 
WHERE TABLE_NAME LIKE 'KNOWLEDGE%'
ORDER BY TABLE_NAME;

-- Verify indexes created
SELECT INDEX_NAME, TABLE_NAME, UNIQUENESS
FROM USER_INDEXES
WHERE TABLE_NAME LIKE 'KNOWLEDGE%'
ORDER BY TABLE_NAME, INDEX_NAME;

-- Verify sequences created
SELECT SEQUENCE_NAME, LAST_NUMBER
FROM USER_SEQUENCES
WHERE SEQUENCE_NAME LIKE 'SEQ_KNOWLEDGE%'
   OR SEQUENCE_NAME LIKE 'SEQ_DISTILLATION%'
   OR SEQUENCE_NAME LIKE 'SEQ_SEARCH%'
ORDER BY SEQUENCE_NAME;

-- Verify views created
SELECT VIEW_NAME
FROM USER_VIEWS
WHERE VIEW_NAME LIKE 'V_KNOWLEDGE%'
   OR VIEW_NAME LIKE 'V_RECENTLY%'
ORDER BY VIEW_NAME;

-- ============================================================================
-- SCHEMA DEPLOYMENT COMPLETE
-- ============================================================================
