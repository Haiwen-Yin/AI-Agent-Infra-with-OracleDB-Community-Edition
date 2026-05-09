-- ============================================================================
-- Oracle Memory System v1.0.0 - Knowledge Property Graph Definition
-- ============================================================================
-- Description: Property Graph definition for Knowledge Base
-- Version: 1.0.0-KB-PG
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: Drop existing Property Graph (if exists)
-- ============================================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP PROPERTY GRAPH knowledge_property_graph';
    DBMS_OUTPUT.PUT_LINE('Dropped existing knowledge_property_graph');
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE = -40983 THEN  -- ORA-40983: property graph does not exist
            DBMS_OUTPUT.PUT_LINE('No existing knowledge_property_graph to drop');
        ELSE
            RAISE;
        END IF;
END;
/

-- ============================================================================
-- SECTION 2: Create Knowledge Property Graph
-- ============================================================================

CREATE PROPERTY GRAPH knowledge_property_graph
  VERTEX TABLES (
    KNOWLEDGE_CONCEPTS AS knowledge_vertex
    KEY (CONCEPT_ID)
    PROPERTIES (
        CONCEPT_ID,
        CONCEPT_NAME,
        CONCEPT_TYPE,
        CATEGORY,
        TITLE,
        CONFIDENCE,
        VALIDATION_STATUS
    )
  )
  EDGE TABLES (
    KNOWLEDGE_GRAPH AS knowledge_edge
    KEY (RELATIONSHIP_ID)
    SOURCE KEY (SOURCE_CONCEPT_ID) REFERENCES knowledge_vertex (CONCEPT_ID)
    DESTINATION KEY (TARGET_CONCEPT_ID) REFERENCES knowledge_vertex (CONCEPT_ID)
    PROPERTIES (
        RELATIONSHIP_ID,
        RELATIONSHIP_TYPE,
        RELATIONSHIP_STRENGTH,
        CONFIDENCE
    )
  );

-- ============================================================================
-- SECTION 3: Create Graph-related Indexes
-- ============================================================================

-- Additional indexes for graph traversal performance
CREATE INDEX IDX_KNOWLEDGE_GRAPH_STRENGTH ON KNOWLEDGE_GRAPH(RELATIONSHIP_STRENGTH DESC);
CREATE INDEX IDX_KNOWLEDGE_GRAPH_CONFIDENCE ON KNOWLEDGE_GRAPH(CONFIDENCE DESC);

-- ============================================================================
-- SECTION 4: Create Graph Views for Common Queries
-- ============================================================================

-- View: All relationships with full details
CREATE OR REPLACE VIEW V_KNOWLEDGE_GRAPH_FULL AS
SELECT 
    kg.RELATIONSHIP_ID,
    kc_s.CONCEPT_ID as SOURCE_ID,
    kc_s.CONCEPT_NAME as SOURCE_NAME,
    kc_s.CONCEPT_TYPE as SOURCE_TYPE,
    kg.RELATIONSHIP_TYPE,
    kg.RELATIONSHIP_STRENGTH,
    kc_t.CONCEPT_ID as TARGET_ID,
    kc_t.CONCEPT_NAME as TARGET_NAME,
    kc_t.CONCEPT_TYPE as TARGET_TYPE,
    kg.CONFIDENCE,
    kg.CREATED_AT
FROM KNOWLEDGE_GRAPH kg
JOIN KNOWLEDGE_CONCEPTS kc_s ON kg.SOURCE_CONCEPT_ID = kc_s.CONCEPT_ID
JOIN KNOWLEDGE_CONCEPTS kc_t ON kg.TARGET_CONCEPT_ID = kc_t.CONCEPT_ID;

-- View: Graph statistics by relationship type
CREATE OR REPLACE VIEW V_KNOWLEDGE_GRAPH_STATS AS
SELECT 
    RELATIONSHIP_TYPE,
    COUNT(*) as RELATIONSHIP_COUNT,
    AVG(RELATIONSHIP_STRENGTH) as AVG_STRENGTH,
    AVG(CONFIDENCE) as AVG_CONFIDENCE,
    MIN(CREATED_AT) as OLDEST_RELATIONSHIP,
    MAX(CREATED_AT) as NEWEST_RELATIONSHIP
FROM KNOWLEDGE_GRAPH
GROUP BY RELATIONSHIP_TYPE;

-- View: Concept connectivity metrics
CREATE OR REPLACE VIEW V_CONCEPT_CONNECTIVITY AS
SELECT 
    kc.CONCEPT_ID,
    kc.CONCEPT_NAME,
    kc.CONCEPT_TYPE,
    COUNT(DISTINCT kg_out.RELATIONSHIP_ID) as OUTGOING_COUNT,
    COUNT(DISTINCT kg_in.RELATIONSHIP_ID) as INCOMING_COUNT,
    COUNT(DISTINCT kg_out.RELATIONSHIP_ID) + COUNT(DISTINCT kg_in.RELATIONSHIP_ID) as TOTAL_CONNECTIONS
FROM KNOWLEDGE_CONCEPTS kc
LEFT JOIN KNOWLEDGE_GRAPH kg_out ON kc.CONCEPT_ID = kg_out.SOURCE_CONCEPT_ID
LEFT JOIN KNOWLEDGE_GRAPH kg_in ON kc.CONCEPT_ID = kg_in.TARGET_CONCEPT_ID
GROUP BY kc.CONCEPT_ID, kc.CONCEPT_NAME, kc.CONCEPT_TYPE;

-- ============================================================================
-- SECTION 5: Graph Query Examples
-- ============================================================================

-- Example 1: Single-hop traversal (1-hop)
-- Find all direct relationships from a concept
/*
SELECT * FROM GRAPH_TABLE (knowledge_property_graph
    MATCH (a IS knowledge_vertex) -[e IS knowledge_edge]-> (b IS knowledge_vertex)
    COLUMNS (
        a.CONCEPT_ID as source_id,
        a.CONCEPT_NAME as source_name,
        e.RELATIONSHIP_TYPE,
        b.CONCEPT_ID as target_id,
        b.CONCEPT_NAME as target_name
    )
) WHERE source_id = :start_concept_id;
*/

-- Example 2: Two-hop traversal
-- Find all concepts 2 hops away
/*
SELECT * FROM GRAPH_TABLE (knowledge_property_graph
    MATCH (a IS knowledge_vertex) -[e1 IS knowledge_edge]-> (b IS knowledge_vertex) 
                                  -[e2 IS knowledge_edge]-> (c IS knowledge_vertex)
    COLUMNS (
        a.CONCEPT_ID,
        a.CONCEPT_NAME,
        e1.RELATIONSHIP_TYPE,
        b.CONCEPT_NAME,
        e2.RELATIONSHIP_TYPE,
        c.CONCEPT_NAME
    )
) WHERE a.CONCEPT_ID = :start_concept_id;
*/

-- Example 3: Path finding
-- Find path between two concepts
/*
SELECT * FROM GRAPH_TABLE (knowledge_property_graph
    MATCH (a IS knowledge_vertex) -[e IS knowledge_edge]-> (b IS knowledge_vertex)
    COLUMNS (
        a.CONCEPT_NAME as from_concept,
        e.RELATIONSHIP_TYPE,
        b.CONCEPT_NAME as to_concept
    )
) WHERE a.CONCEPT_ID = :source_id AND b.CONCEPT_ID = :target_id;
*/

-- Example 4: Relationship strength filtering
-- Find strong relationships only
/*
SELECT * FROM GRAPH_TABLE (knowledge_property_graph
    MATCH (a IS knowledge_vertex) -[e IS knowledge_edge]-> (b IS knowledge_vertex)
    COLUMNS (
        a.CONCEPT_NAME,
        e.RELATIONSHIP_TYPE,
        e.RELATIONSHIP_STRENGTH,
        b.CONCEPT_NAME
    )
) WHERE e.RELATIONSHIP_STRENGTH >= 0.8;
*/

-- Example 5: Concept type filtering
-- Find all FACT concepts and their relationships
/*
SELECT * FROM GRAPH_TABLE (knowledge_property_graph
    MATCH (a IS knowledge_vertex) -[e IS knowledge_edge]-> (b IS knowledge_vertex)
    COLUMNS (
        a.CONCEPT_ID,
        a.CONCEPT_NAME,
        a.CONCEPT_TYPE,
        e.RELATIONSHIP_TYPE,
        b.CONCEPT_NAME,
        b.CONCEPT_TYPE
    )
) WHERE a.CONCEPT_TYPE = 'FACT';
*/

-- ============================================================================
-- SECTION 6: Graph Validation Queries
-- ============================================================================

-- Verify Property Graph creation
SELECT OBJECT_NAME, OBJECT_TYPE
FROM USER_OBJECTS
WHERE OBJECT_NAME = 'KNOWLEDGE_PROPERTY_GRAPH'
  AND OBJECT_TYPE = 'PROPERTY GRAPH';

-- Verify vertex tables
SELECT TABLE_NAME, KEY_COLUMN
FROM USER_PROPERTY_GRAPH_VERTEX_TABLES
WHERE GRAPH_NAME = 'KNOWLEDGE_PROPERTY_GRAPH';

-- Verify edge tables
SELECT TABLE_NAME, KEY_COLUMN, SOURCE_TABLE, SOURCE_KEY, DESTINATION_TABLE, DESTINATION_KEY
FROM USER_PROPERTY_GRAPH_EDGE_TABLES
WHERE GRAPH_NAME = 'KNOWLEDGE_PROPERTY_GRAPH';

-- Test query: Count concepts by type
SELECT 
    CONCEPT_TYPE,
    COUNT(*) as CONCEPT_COUNT
FROM KNOWLEDGE_CONCEPTS
GROUP BY CONCEPT_TYPE
ORDER BY CONCEPT_COUNT DESC;

-- Test query: Count relationships by type
SELECT 
    RELATIONSHIP_TYPE,
    COUNT(*) as RELATIONSHIP_COUNT
FROM KNOWLEDGE_GRAPH
GROUP BY RELATIONSHIP_TYPE
ORDER BY RELATIONSHIP_COUNT DESC;

-- ============================================================================
-- SECTION 7: Graph Performance Statistics
-- ============================================================================

-- Graph density (actual relationships / possible relationships)
SELECT 
    (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) as ACTUAL_RELATIONSHIPS,
    (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) as TOTAL_CONCEPTS,
    ROUND(
        (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) / 
        GREATEST(
            (SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) * 
            ((SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS) - 1) / 2,
            1
        ) * 100,
        2
    ) as GRAPH_DENSITY_PERCENT
FROM DUAL;

-- Average degree (relationships per concept)
SELECT 
    ROUND(
        (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH) * 2.0 / 
        GREATEST((SELECT COUNT(*) FROM KNOWLEDGE_CONCEPTS), 1),
        2
    ) as AVG_DEGREE
FROM DUAL;

-- ============================================================================
-- PROPERTY GRAPH DEPLOYMENT COMPLETE
-- ============================================================================
