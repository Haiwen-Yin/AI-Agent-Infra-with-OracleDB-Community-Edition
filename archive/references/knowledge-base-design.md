# Oracle Memory System v1.0.0 - Knowledge Base System Design

**Version**: v1.0.0 (Production Release)  
**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-09  
**Status**: Production Release ✅  

---

## 🎯 Design Goals

### Primary Objectives
1. **Separate Knowledge from Memory** - Knowledge is stable, long-term; Memory is dynamic, ephemeral
2. **Knowledge Graph Capabilities** - Enable relationship-based reasoning and traversal
3. **Experience Distillation** - Accumulated memories can be distilled into reusable knowledge
4. **Hybrid Retrieval** - Combine semantic search (vector) + structural traversal (graph)

### Design Principles
1. **Knowledge > Memory**: Knowledge is curated, validated, and stable
2. **Graph-First**: Relationships are first-class citizens in knowledge representation
3. **Incremental Learning**: System improves over time as memories become knowledge
4. **Schema Separation**: Knowledge tables are independent from Memory tables

---

## 📊 Conceptual Model

### Memory vs Knowledge Comparison

```
┌─────────────────────────────────────────────────────────────┐
│                    System Overview                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────┐      ┌─────────────────────┐       │
│  │     MEMORY LAYER    │      │   KNOWLEDGE LAYER    │       │
│  │   (Dynamic/Short)   │      │  (Stable/Long-term)  │       │
│  ├─────────────────────┤      ├─────────────────────┤       │
│  │ • Conversation history│    │ • Facts & Concepts   │       │
│  │ • Working context    │     │ • Relationships      │       │
│  │ • Temporary notes    │     │ • Rules & Patterns   │       │
│  │ • Session state      │     │ • Experiences        │       │
│  └──────────┬──────────┘      └──────────┬──────────┘       │
│             │                             │                  │
│             │    ┌─────────────────┐      │                  │
│             │    │   DISTILLATION  │      │                  │
│             └───►│     PROCESS     │◄─────┘                  │
│                  │ (Memory → Knowledge)                      │
│                  └─────────────────┘                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Knowledge Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                   Knowledge Lifecycle                        │
└─────────────────────────────────────────────────────────────┘

[Memory Created] ──► [Repeats Multiple Times] ──► [Pattern Recognized]
                                                        │
                                                        ▼
                                        [Experience Extracted] ──► [Validated by Expert]
                                                        │
                                                        ▼
                                        [Knowledge Distilled] ──► [Knowledge Base]
                                                        │
                                                        ▼
                                        [Knowledge Evolves] ◄─── [New Memories Support/Challenge]
```

---

## 🗄️ Database Schema Design

### Knowledge Base Core Tables

#### 1. KNOWLEDGE_CONCEPTS - Core knowledge entities

```sql
CREATE TABLE KNOWLEDGE_CONCEPTS (
    CONCEPT_ID      NUMBER PRIMARY KEY,
    CONCEPT_NAME    VARCHAR2(200) NOT NULL,            -- Human-readable name
    CONCEPT_TYPE    VARCHAR2(50) NOT NULL,             -- FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE
    CATEGORY        VARCHAR2(100),                     -- Domain category (tech/science/business/etc)
    
    -- Content
    TITLE           VARCHAR2(500),                     -- Short title
    DESCRIPTION     CLOB,                              -- Detailed description
    CONTENT         CLOB,                              -- Full knowledge content (Markdown)
    
    -- Source & Provenance
    SOURCE_TYPE     VARCHAR2(50),                      -- MANUAL/DISTILLED/IMPORTED/VERIFIED
    SOURCE_MEMORY_IDS CLOB,                            -- JSON: [memory_id1, memory_id2, ...] - Source memories
    CONFIDENCE      NUMBER(3,2) CHECK (CONFIDENCE BETWEEN 0 AND 1),  -- 0.00 - 1.00
    VALIDATION_STATUS VARCHAR2(30) DEFAULT 'PENDING',  -- PENDING/VALIDATED/REJECTED/DEPRECATED
    
    -- Embedding for semantic search
    EMBEDDING       VECTOR(1024),                      -- BGE-M3 embedding
    
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
```

#### 2. KNOWLEDGE_GRAPH - Knowledge relationships (Property Graph)

```sql
CREATE TABLE KNOWLEDGE_GRAPH (
    RELATIONSHIP_ID   NUMBER PRIMARY KEY,
    SOURCE_CONCEPT_ID NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    TARGET_CONCEPT_ID NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    
    -- Relationship type
    RELATIONSHIP_TYPE VARCHAR2(100) NOT NULL,           -- IS_A/PART_OF/CAUSES/ENABLES/CONTRADICTS/SUPPORTS
    RELATIONSHIP_STRENGTH NUMBER(3,2) DEFAULT 1.0,      -- 0.0 - 1.0 (strength of relationship)
    
    -- Properties
    PROPERTIES        CLOB,                             -- JSON: relationship metadata
    
    -- Timestamps
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    UPDATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    
    -- Source
    SOURCE_TYPE       VARCHAR2(50),                     -- MANUAL/DISTILLED/INFERRED
    CONFIDENCE        NUMBER(3,2) DEFAULT 0.8
);

-- Indexes
CREATE INDEX IDX_KNOWLEDGE_GRAPH_SOURCE ON KNOWLEDGE_GRAPH(SOURCE_CONCEPT_ID);
CREATE INDEX IDX_KNOWLEDGE_GRAPH_TARGET ON KNOWLEDGE_GRAPH(TARGET_CONCEPT_ID);
CREATE INDEX IDX_KNOWLEDGE_GRAPH_TYPE ON KNOWLEDGE_GRAPH(RELATIONSHIP_TYPE);
```

#### 3. KNOWLEDGE_VERSIONS - Version history for knowledge

```sql
CREATE TABLE KNOWLEDGE_VERSIONS (
    VERSION_ID        NUMBER PRIMARY KEY,
    CONCEPT_ID        NUMBER NOT NULL REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    
    -- Version content
    TITLE             VARCHAR2(500),
    DESCRIPTION       CLOB,
    CONTENT           CLOB,
    
    -- Change tracking
    CHANGE_SUMMARY    CLOB,                             -- What changed in this version
    CHANGE_REASON     VARCHAR2(500),                    -- Why the change was made
    
    -- Timestamps
    VERSIONED_AT      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    VERSIONED_BY      VARCHAR2(64),                     -- Who created this version
);

CREATE INDEX IDX_KNOWLEDGE_VERSIONS_CONCEPT ON KNOWLEDGE_VERSIONS(CONCEPT_ID, VERSIONED_AT DESC);
```

#### 4. KNOWLEDGE_TAGS - Tag-based categorization

```sql
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
```

#### 5. KNOWLEDGE_DISTILLATION_LOG - Track memory-to-knowledge distillation

```sql
CREATE TABLE KNOWLEDGE_DISTILLATION_LOG (
    DISTILLATION_ID   NUMBER PRIMARY KEY,
    
    -- Source memories
    MEMORY_IDS        CLOB,                             -- JSON: [memory_id1, memory_id2, ...]
    MEMORY_COUNT      NUMBER,
    MEMORY_TIME_RANGE VARCHAR2(100),                    -- e.g., "2026-01-01 to 2026-05-09"
    
    -- Distillation result
    KNOWLEDGE_TYPE    VARCHAR2(50),                     -- FACT/RULE/PATTERN/EXPERIENCE
    KNOWLEDGE_TITLE   VARCHAR2(500),
    CONFIDENCE        NUMBER(3,2),
    
    -- Process
    DISTILLATION_METHOD VARCHAR2(50),                   -- AUTOMATIC/MANUAL/HYBRID
    TRIGGERED_BY      VARCHAR2(100),                    -- What triggered distillation
    PATTERN_DETECTED  CLOB,                             -- JSON: detected patterns
    
    -- Result
    KNOWLEDGE_ID      NUMBER REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    STATUS            VARCHAR2(30) DEFAULT 'PENDING',   -- PENDING/COMPLETED/FAILED
    
    -- Timestamps
    CREATED_AT        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    COMPLETED_AT      TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IDX_DISTILLATION_LOG_CREATED ON KNOWLEDGE_DISTILLATION_LOG(CREATED_AT DESC);
```

#### 6. KNOWLEDGE_SEARCH_HISTORY - Track knowledge usage for learning

```sql
CREATE TABLE KNOWLEDGE_SEARCH_HISTORY (
    SEARCH_ID         NUMBER PRIMARY KEY,
    QUERY_TEXT        CLOB,                             -- Search query
    QUERY_EMBEDDING   VECTOR(1024),                     -- Query embedding
    
    -- Results
    RESULT_COUNT      NUMBER,
    TOP_RESULT_ID     NUMBER REFERENCES KNOWLEDGE_CONCEPTS(CONCEPT_ID),
    RELEVANCE_SCORE   NUMBER(3,2),
    
    -- User feedback
    USER_CLICKED      VARCHAR2(1) DEFAULT 'N',
    USER_HELPFUL      VARCHAR2(1),                      -- NULL/Y/N
    
    -- Context
    SEARCH_CONTEXT    VARCHAR2(50),                     -- CONVERSATION/RESEARCH/AUTOMATED
    SESSION_ID        NUMBER,
    
    -- Timestamps
    SEARCHED_AT       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP
);

CREATE INDEX IDX_KNOWLEDGE_SEARCH_HISTORY ON KNOWLEDGE_SEARCH_HISTORY(SEARCHED_AT DESC);
```

### Knowledge Graph Property Graph Definition

```sql
CREATE PROPERTY GRAPH knowledge_property_graph
  VERTEX TABLES (
    KNOWLEDGE_CONCEPTS AS knowledge_vertex
    KEY (CONCEPT_ID)
    PROPERTIES (CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, CATEGORY, TITLE)
  )
  EDGE TABLES (
    KNOWLEDGE_GRAPH AS knowledge_edge
    KEY (RELATIONSHIP_ID)
    SOURCE KEY (SOURCE_CONCEPT_ID) REFERENCES knowledge_vertex (CONCEPT_ID)
    DESTINATION KEY (TARGET_CONCEPT_ID) REFERENCES knowledge_vertex (CONCEPT_ID)
    PROPERTIES (RELATIONSHIP_ID, RELATIONSHIP_TYPE, RELATIONSHIP_STRENGTH)
  );
```

---

## 🔧 PL/SQL Package Design

### KNOWLEDGE_BASE_API - Main API Package

```sql
CREATE OR REPLACE PACKAGE knowledge_base_api AS
    
    -- ============================================
    -- KNOWLEDGE CONCEPT OPERATIONS
    -- ============================================
    
    -- Create new knowledge concept
    FUNCTION create_concept(
        p_concept_name    VARCHAR2,
        p_concept_type    VARCHAR2,  -- FACT/RULE/PATTERN/EXPERIENCE/PRINCIPLE
        p_category        VARCHAR2,
        p_title           VARCHAR2,
        p_description     CLOB,
        p_content         CLOB,
        p_source_type     VARCHAR2 DEFAULT 'MANUAL',
        p_tags            CLOB DEFAULT '[]'
    ) RETURN NUMBER;
    
    -- Update knowledge concept
    PROCEDURE update_concept(
        p_concept_id      NUMBER,
        p_title           VARCHAR2 DEFAULT NULL,
        p_description     CLOB DEFAULT NULL,
        p_content         CLOB DEFAULT NULL,
        p_change_summary  CLOB DEFAULT NULL
    );
    
    -- Validate knowledge concept
    PROCEDURE validate_concept(
        p_concept_id      NUMBER,
        p_validation_status VARCHAR2,  -- VALIDATED/REJECTED
        p_confidence      NUMBER DEFAULT 1.0
    );
    
    -- Deprecate knowledge concept
    PROCEDURE deprecate_concept(
        p_concept_id      NUMBER,
        p_reason          VARCHAR2
    );
    
    -- ============================================
    -- KNOWLEDGE GRAPH OPERATIONS
    -- ============================================
    
    -- Create relationship between concepts
    FUNCTION create_relationship(
        p_source_concept_id  NUMBER,
        p_target_concept_id  NUMBER,
        p_relationship_type  VARCHAR2,
        p_strength           NUMBER DEFAULT 1.0,
        p_properties         CLOB DEFAULT '{}'
    ) RETURN NUMBER;
    
    -- Get concept relationships
    FUNCTION get_relationships(
        p_concept_id    NUMBER,
        p_direction     VARCHAR2 DEFAULT 'BOTH',  -- OUTGOING/INCOMING/BOTH
        p_filter_types  CLOB DEFAULT NULL          -- JSON: ["IS_A", "PART_OF", ...]
    ) RETURN CLOB;
    
    -- Traverse knowledge graph (multi-hop)
    FUNCTION traverse_graph(
        p_start_concept_id  NUMBER,
        p_max_hops          NUMBER DEFAULT 3,
        p_relationship_filter CLOB DEFAULT NULL
    ) RETURN CLOB;
    
    -- Find shortest path between concepts
    FUNCTION find_path(
        p_source_concept_id  NUMBER,
        p_target_concept_id  NUMBER,
        p_max_hops           NUMBER DEFAULT 5
    ) RETURN CLOB;
    
    -- ============================================
    -- SEMANTIC SEARCH OPERATIONS
    -- ============================================
    
    -- Semantic search for knowledge
    FUNCTION semantic_search(
        p_query_text     VARCHAR2,
        p_limit          NUMBER DEFAULT 10,
        p_min_confidence NUMBER DEFAULT 0.5,
        p_category       VARCHAR2 DEFAULT NULL,
        p_concept_type   VARCHAR2 DEFAULT NULL
    ) RETURN CLOB;
    
    -- Hybrid search (semantic + structural)
    FUNCTION hybrid_search(
        p_query_text        VARCHAR2,
        p_relationship_types CLOB DEFAULT NULL,  -- JSON: ["IS_A", "PART_OF"]
        p_limit             NUMBER DEFAULT 10
    ) RETURN CLOB;
    
    -- ============================================
    -- KNOWLEDGE DISTILLATION OPERATIONS
    -- ============================================
    
    -- Distill experience from memories
    FUNCTION distill_experience(
        p_memory_ids     CLOB,           -- JSON: [memory_id1, memory_id2, ...]
        p_knowledge_type VARCHAR2 DEFAULT 'EXPERIENCE',
        p_min_pattern_count NUMBER DEFAULT 3  -- Minimum memories to form pattern
    ) RETURN NUMBER;
    
    -- Check if memories should be distilled
    FUNCTION should_distill(p_memory_category VARCHAR2) RETURN BOOLEAN;
    
    -- Get distillation candidates
    FUNCTION get_distillation_candidates(
        p_category     VARCHAR2 DEFAULT NULL,
        p_min_age_days NUMBER DEFAULT 30
    ) RETURN CLOB;
    
    -- ============================================
    -- VERSION MANAGEMENT
    -- ============================================
    
    -- Get concept version history
    FUNCTION get_version_history(p_concept_id NUMBER) RETURN CLOB;
    
    -- Restore concept to specific version
    PROCEDURE restore_version(
        p_concept_id  NUMBER,
        p_version_id  NUMBER
    );
    
    -- ============================================
    -- STATISTICS AND MONITORING
    -- ============================================
    
    -- Get knowledge base statistics
    FUNCTION get_kb_statistics RETURN CLOB;
    
    -- Get knowledge graph metrics
    FUNCTION get_graph_metrics RETURN CLOB;
    
    -- Get recent distillation activity
    FUNCTION get_distillation_activity(
        p_days NUMBER DEFAULT 7
    ) RETURN CLOB;
    
END knowledge_base_api;
/

CREATE OR REPLACE PACKAGE BODY knowledge_base_api AS
    
    -- ... Implementation ...
    
END knowledge_base_api;
/
```

---

## 🧠 Experience Distillation Algorithm

### Pattern Detection

```sql
CREATE OR REPLACE PROCEDURE detect_memory_patterns(
    p_category VARCHAR2 DEFAULT NULL,
    p_min_occurrences NUMBER DEFAULT 3
) AS
    -- Cursor to find repeated memory patterns
    CURSOR memory_patterns IS
        SELECT 
            m.CATEGORY,
            m.CONTENT,
            COUNT(*) as occurrence_count,
            MIN(m.CREATED_AT) as first_seen,
            MAX(m.CREATED_AT) as last_seen
        FROM MEMORIES m
        WHERE m.CATEGORY = NVL(p_category, m.CATEGORY)
          AND m.CREATED_AT < SYSTIMESTAMP - 30  -- At least 30 days old
        GROUP BY m.CATEGORY, m.CONTENT
        HAVING COUNT(*) >= p_min_occurrences;
    
    v_knowledge_id NUMBER;
BEGIN
    FOR pattern IN memory_patterns LOOP
        -- Create knowledge concept from pattern
        v_knowledge_id := knowledge_base_api.create_concept(
            p_concept_name => 'Pattern: ' || SUBSTR(pattern.CONTENT, 1, 100),
            p_concept_type => 'PATTERN',
            p_category     => pattern.CATEGORY,
            p_title        => 'Learned Pattern from ' || pattern.occurrence_count || ' occurrences',
            p_description  => 'Pattern detected from repeated memories',
            p_content      => pattern.CONTENT,
            p_source_type  => 'DISTILLED',
            p_tags         => '["auto-distilled", "pattern"]'
        );
        
        -- Log distillation
        INSERT INTO KNOWLEDGE_DISTILLATION_LOG (
            MEMORY_IDS, MEMORY_COUNT, KNOWLEDGE_TYPE, 
            KNOWLEDGE_TITLE, CONFIDENCE, DISTILLATION_METHOD,
            TRIGGERED_BY, KNOWLEDGE_ID, STATUS
        ) VALUES (
            '[]', pattern.occurrence_count, 'PATTERN',
            'Auto-distilled pattern', 
            LEAST(1.0, pattern.occurrence_count / 10),  -- Confidence increases with occurrences
            'AUTOMATIC',
            'Pattern detection procedure',
            v_knowledge_id,
            'COMPLETED'
        );
        
        DBMS_OUTPUT.PUT_LINE('Distilled pattern: ' || SUBSTR(pattern.CONTENT, 1, 50) || '...');
    END LOOP;
    
    COMMIT;
END detect_memory_patterns;
/
```

### Experience Extraction

```sql
CREATE OR REPLACE PROCEDURE extract_experience(
    p_memory_category VARCHAR2,
    p_min_age_days NUMBER DEFAULT 60
) AS
    CURSOR experience_candidates IS
        SELECT 
            m.ID as memory_id,
            m.CONTENT,
            m.CATEGORY,
            m.TAGS,
            m.ACCESS_COUNT,
            m.CREATED_AT
        FROM MEMORIES m
        WHERE m.CATEGORY = p_memory_category
          AND m.CREATED_AT < SYSTIMESTAMP - p_min_age_days
          AND m.ACCESS_COUNT > 5  -- Frequently accessed memories
        ORDER BY m.ACCESS_COUNT DESC;
    
    v_experience_content CLOB;
    v_knowledge_id NUMBER;
BEGIN
    -- Aggregate experience from high-value memories
    FOR rec IN experience_candidates LOOP
        v_experience_content := v_experience_content || 
            'Experience from ' || TO_CHAR(rec.CREATED_AT, 'YYYY-MM-DD') || ': ' ||
            rec.CONTENT || CHR(10) || CHR(10);
    END LOOP;
    
    IF v_experience_content IS NOT NULL THEN
        -- Create experience knowledge
        v_knowledge_id := knowledge_base_api.create_concept(
            p_concept_name => 'Experience: ' || p_memory_category,
            p_concept_type => 'EXPERIENCE',
            p_category     => p_memory_category,
            p_title        => 'Accumulated experience in ' || p_memory_category,
            p_description  => 'Experience distilled from ' || experience_candidates%ROWCOUNT || ' high-value memories',
            p_content      => v_experience_content,
            p_source_type  => 'DISTILLED',
            p_tags         => '["auto-distilled", "experience"]'
        );
        
        DBMS_OUTPUT.PUT_LINE('Extracted experience for category: ' || p_memory_category);
    END IF;
    
    COMMIT;
END extract_experience;
/
```

---

## 📊 Query Patterns

### 1. Semantic Knowledge Search

```sql
-- Search for knowledge similar to a query
SELECT 
    kc.CONCEPT_ID,
    kc.CONCEPT_NAME,
    kc.TITLE,
    kc.CONCEPT_TYPE,
    kc.CATEGORY,
    VECTOR_DISTANCE(kc.EMBEDDING, 
        (SELECT EMBEDDING FROM KNOWLEDGE_CONCEPTS WHERE CONCEPT_ID = :query_concept_id),
        COSINE) as RELEVANCE_SCORE
FROM KNOWLEDGE_CONCEPTS kc
WHERE kc.VALIDATION_STATUS = 'VALIDATED'
  AND kc.EMBEDDING IS NOT NULL
ORDER BY RELEVANCE_SCORE ASC
FETCH FIRST :limit ROWS ONLY;
```

### 2. Graph Traversal (SQL/PGQ)

```sql
-- Find all concepts related to a given concept (2 hops)
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
```

### 3. Hybrid Search (Semantic + Graph)

```sql
-- Find concepts that are semantically similar AND graph-connected
WITH semantic_matches AS (
    SELECT 
        kc.CONCEPT_ID,
        kc.CONCEPT_NAME,
        VECTOR_DISTANCE(kc.EMBEDDING,
            (SELECT EMBEDDING FROM KNOWLEDGE_CONCEPTS WHERE CONCEPT_ID = :query_id),
            COSINE) as similarity
    FROM KNOWLEDGE_CONCEPTS kc
    WHERE kc.VALIDATION_STATUS = 'VALIDATED'
),
graph_matches AS (
    SELECT 
        TARGET_CONCEPT_ID as CONCEPT_ID,
        COUNT(*) as connection_count
    FROM KNOWLEDGE_GRAPH
    WHERE SOURCE_CONCEPT_ID = :query_id
    GROUP BY TARGET_CONCEPT_ID
)
SELECT 
    sm.CONCEPT_ID,
    sm.CONCEPT_NAME,
    sm.similarity,
    NVL(gm.connection_count, 0) as graph_connections
FROM semantic_matches sm
LEFT JOIN graph_matches gm ON sm.CONCEPT_ID = gm.CONCEPT_ID
WHERE sm.similarity < 0.3  -- Cosine distance < 0.3 = similarity > 0.7
ORDER BY sm.similarity ASC
FETCH FIRST 10 ROWS ONLY;
```

### 4. Experience Recommendation

```sql
-- Recommend experiences for a given context
SELECT 
    kc.CONCEPT_ID,
    kc.TITLE,
    kc.CONTENT,
    kc.CONFIDENCE,
    VECTOR_DISTANCE(kc.EMBEDDING,
        (SELECT EMBEDDING FROM KNOWLEDGE_CONCEPTS WHERE CONCEPT_ID = :context_id),
        COSINE) as relevance
FROM KNOWLEDGE_CONCEPTS kc
WHERE kc.CONCEPT_TYPE = 'EXPERIENCE'
  AND kc.VALIDATION_STATUS = 'VALIDATED'
  AND kc.EMBEDDING IS NOT NULL
ORDER BY relevance ASC
FETCH FIRST 5 ROWS ONLY;
```

---

## 🔧 Scheduled Jobs

```sql
-- Daily pattern detection
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_PATTERN_DETECTION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN detect_memory_patterns(NULL, 3); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=DAILY; BYHOUR=3; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Daily pattern detection for memory distillation'
    );
END;
/

-- Weekly experience extraction
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_EXPERIENCE_EXTRACTION',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN extract_experience(NULL, 60); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=WEEKLY; BYDAY=SUN; BYHOUR=4; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Weekly experience extraction from mature memories'
    );
END;
/

-- Monthly knowledge graph cleanup
BEGIN
    DBMS_SCHEDULER.CREATE_JOB (
        job_name => 'KNOWLEDGE_GRAPH_CLEANUP',
        job_type => 'PLSQL_BLOCK',
        job_action => 'BEGIN knowledge_base_api.cleanup_deprecated(); END;',
        start_date => SYSTIMESTAMP,
        repeat_interval => 'FREQ=MONTHLY; BYMONTHDAY=1; BYHOUR=5; BYMINUTE=0; BYSECOND=0',
        enabled => TRUE,
        comments => 'Monthly cleanup of deprecated knowledge'
    );
END;
/
```

---

## 📈 Performance Considerations

### Vector Index Strategy

```sql
-- HNSW index for semantic search
CREATE INDEX idx_knowledge_embedding_hnsw 
ON KNOWLEDGE_CONCEPTS(EMBEDDING) 
ORGANIZATION INVECTOR NEIGHBOR GRAPH
DISTANCE COSINE
WITH TARGET ACCURACY 95;
```

### Graph Traversal Optimization

```sql
-- Materialized view for frequently accessed graph traversals
CREATE MATERIALIZED VIEW mv_knowledge_graph_summary
BUILD IMMEDIATE
REFRESH COMPLETE ON DEMAND
AS
SELECT 
    kc.CONCEPT_ID,
    kc.CONCEPT_TYPE,
    COUNT(kg.RELATIONSHIP_ID) as total_relationships,
    LISTAGG(kg.RELATIONSHIP_TYPE, ', ') WITHIN GROUP (ORDER BY kg.RELATIONSHIP_TYPE) as relationship_types
FROM KNOWLEDGE_CONCEPTS kc
LEFT JOIN KNOWLEDGE_GRAPH kg ON kc.CONCEPT_ID = kg.SOURCE_CONCEPT_ID
GROUP BY kc.CONCEPT_ID, kc.CONCEPT_TYPE;
```

---

## 📋 Migration Plan

### From v0.5.1 to v0.6.0

1. **Deploy Knowledge Schema**
   ```bash
   sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_base_schema.sql
   ```

2. **Create Property Graph**
   ```bash
   sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_property_graph.sql
   ```

3. **Deploy PL/SQL Packages**
   ```bash
   sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_base_api.sql
   ```

4. **Deploy Scheduled Jobs**
   ```bash
   sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_jobs.sql
   ```

5. **Initialize Initial Knowledge** (optional)
   ```bash
   sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_init.sql
   ```

### Rollback Plan

```bash
# Drop knowledge tables
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_drop.sql

# Drop property graph
sql openclaw/hermes@//10.10.10.130:1521/openclaw @scripts/knowledge_graph_drop.sql
```

---

## 🎯 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Knowledge Coverage | > 100 validated concepts | COUNT(*) WHERE VALIDATION_STATUS='VALIDATED' |
| Distillation Rate | > 10 experiences/month | Monthly KNOWLEDGE_DISTILLATION_LOG entries |
| Search Accuracy | > 80% relevance | User feedback on search results |
| Graph Connectivity | Average 3+ relationships/concept | AVG(relationship_count) |
| System Performance | < 100ms semantic search | Query execution time |

---

**Document Version**: v0.1.0  
**Status**: Design Phase  
**Next Steps**: Implement Schema and API  
