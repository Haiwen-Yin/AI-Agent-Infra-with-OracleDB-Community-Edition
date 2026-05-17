-- ============================================================================
-- Oracle Memory System v1.0.0 - Knowledge Base API
-- ============================================================================
-- Description: PL/SQL API package for Knowledge Base operations
-- Version: 1.0.0-KB-API
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-09
-- ============================================================================

-- ============================================================================
-- SECTION 1: Package Specification
-- ============================================================================

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
        p_source_memory_ids CLOB DEFAULT '[]',
        p_tags            CLOB DEFAULT '[]',
        p_confidence      NUMBER DEFAULT 0.8
    ) RETURN NUMBER;
    
    -- Update knowledge concept
    PROCEDURE update_concept(
        p_concept_id      NUMBER,
        p_title           VARCHAR2 DEFAULT NULL,
        p_description     CLOB DEFAULT NULL,
        p_content         CLOB DEFAULT NULL,
        p_change_summary  CLOB DEFAULT NULL,
        p_change_reason   VARCHAR2 DEFAULT NULL
    );
    
    -- Validate knowledge concept
    PROCEDURE validate_concept(
        p_concept_id      NUMBER,
        p_validation_status VARCHAR2,
        p_confidence      NUMBER DEFAULT 1.0
    );
    
    -- Deprecate knowledge concept
    PROCEDURE deprecate_concept(
        p_concept_id      NUMBER,
        p_reason          VARCHAR2
    );
    
    -- Get knowledge concept
    FUNCTION get_concept(p_concept_id NUMBER) RETURN CLOB;
    
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
        p_direction     VARCHAR2 DEFAULT 'BOTH',
        p_filter_types  CLOB DEFAULT NULL
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
        p_relationship_types CLOB DEFAULT NULL,
        p_limit             NUMBER DEFAULT 10
    ) RETURN CLOB;
    
    -- ============================================
    -- KNOWLEDGE DISTILLATION OPERATIONS
    -- ============================================
    
    -- Distill experience from memories
    FUNCTION distill_experience(
        p_memory_ids     CLOB,
        p_knowledge_type VARCHAR2 DEFAULT 'EXPERIENCE',
        p_min_pattern_count NUMBER DEFAULT 3
    ) RETURN NUMBER;
    
    -- Check if memories should be distilled
    FUNCTION should_distill(p_memory_category VARCHAR2) RETURN NUMBER;  -- 1=TRUE, 0=FALSE
    
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
    
    -- ============================================
    -- CLEANUP OPERATIONS
    -- ============================================
    
    -- Clean up deprecated knowledge
    PROCEDURE cleanup_deprecated(
        p_days_old NUMBER DEFAULT 90
    );
    
END knowledge_base_api;
/

-- ============================================================================
-- SECTION 2: Package Body Implementation
-- ============================================================================

CREATE OR REPLACE PACKAGE BODY knowledge_base_api AS
    
    -- ============================================
    -- Helper: Generate JSON response
    -- ============================================
    FUNCTION json_response(
        p_success VARCHAR2,
        p_data    CLOB DEFAULT NULL,
        p_message VARCHAR2 DEFAULT NULL
    ) RETURN CLOB IS
    BEGIN
        RETURN '{"success": "' || p_success || 
               '", "data": ' || NVL(p_data, 'null') || 
               '", "message": "' || NVL(p_message, '') || '"}';
    END json_response;
    
    -- ============================================
    -- KNOWLEDGE CONCEPT OPERATIONS
    -- ============================================
    
    FUNCTION create_concept(
        p_concept_name    VARCHAR2,
        p_concept_type    VARCHAR2,
        p_category        VARCHAR2,
        p_title           VARCHAR2,
        p_description     CLOB,
        p_content         CLOB,
        p_source_type     VARCHAR2 DEFAULT 'MANUAL',
        p_source_memory_ids CLOB DEFAULT '[]',
        p_tags            CLOB DEFAULT '[]',
        p_confidence      NUMBER DEFAULT 0.8
    ) RETURN NUMBER IS
        v_concept_id NUMBER;
    BEGIN
        -- Generate next ID
        SELECT SEQ_KNOWLEDGE_CONCEPTS.NEXTVAL INTO v_concept_id FROM DUAL;
        
        -- Insert concept
        INSERT INTO KNOWLEDGE_CONCEPTS (
            CONCEPT_ID, CONCEPT_NAME, CONCEPT_TYPE, CATEGORY,
            TITLE, DESCRIPTION, CONTENT,
            SOURCE_TYPE, SOURCE_MEMORY_IDS, TAGS, CONFIDENCE,
            VALIDATION_STATUS, CREATED_AT, UPDATED_AT, VERSION, IS_CURRENT
        ) VALUES (
            v_concept_id, p_concept_name, p_concept_type, p_category,
            p_title, p_description, p_content,
            p_source_type, p_source_memory_ids, p_tags, p_confidence,
            'PENDING', SYSTIMESTAMP, SYSTIMESTAMP, 1, 'Y'
        );
        
        COMMIT;
        RETURN v_concept_id;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END create_concept;
    
    PROCEDURE update_concept(
        p_concept_id      NUMBER,
        p_title           VARCHAR2 DEFAULT NULL,
        p_description     CLOB DEFAULT NULL,
        p_content         CLOB DEFAULT NULL,
        p_change_summary  CLOB DEFAULT NULL,
        p_change_reason   VARCHAR2 DEFAULT NULL
    ) IS
        v_current_version NUMBER;
    BEGIN
        -- Get current version
        SELECT VERSION INTO v_current_version 
        FROM KNOWLEDGE_CONCEPTS 
        WHERE CONCEPT_ID = p_concept_id;
        
        -- Save current version to history
        INSERT INTO KNOWLEDGE_VERSIONS (
            VERSION_ID, CONCEPT_ID, TITLE, DESCRIPTION, CONTENT,
            CHANGE_SUMMARY, CHANGE_REASON, VERSIONED_AT
        )
        SELECT 
            SEQ_KNOWLEDGE_VERSIONS.NEXTVAL, CONCEPT_ID, TITLE, DESCRIPTION, CONTENT,
            p_change_summary, p_change_reason, SYSTIMESTAMP
        FROM KNOWLEDGE_CONCEPTS
        WHERE CONCEPT_ID = p_concept_id;
        
        -- Update concept
        UPDATE KNOWLEDGE_CONCEPTS
        SET TITLE = NVL(p_title, TITLE),
            DESCRIPTION = NVL(p_description, DESCRIPTION),
            CONTENT = NVL(p_content, CONTENT),
            VERSION = v_current_version + 1,
            UPDATED_AT = SYSTIMESTAMP
        WHERE CONCEPT_ID = p_concept_id;
        
        COMMIT;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END update_concept;
    
    PROCEDURE validate_concept(
        p_concept_id      NUMBER,
        p_validation_status VARCHAR2,
        p_confidence      NUMBER DEFAULT 1.0
    ) IS
    BEGIN
        UPDATE KNOWLEDGE_CONCEPTS
        SET VALIDATION_STATUS = p_validation_status,
            CONFIDENCE = p_confidence,
            VALIDATED_AT = CASE WHEN p_validation_status = 'VALIDATED' THEN SYSTIMESTAMP ELSE VALIDATED_AT END,
            UPDATED_AT = SYSTIMESTAMP
        WHERE CONCEPT_ID = p_concept_id;
        
        COMMIT;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END validate_concept;
    
    PROCEDURE deprecate_concept(
        p_concept_id      NUMBER,
        p_reason          VARCHAR2
    ) IS
    BEGIN
        UPDATE KNOWLEDGE_CONCEPTS
        SET VALIDATION_STATUS = 'DEPRECATED',
            DEPRECATED_AT = SYSTIMESTAMP,
            IS_CURRENT = 'N',
            METADATA = '{"deprecated_reason": "' || p_reason || '"}',
            UPDATED_AT = SYSTIMESTAMP
        WHERE CONCEPT_ID = p_concept_id;
        
        COMMIT;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END deprecate_concept;
    
    FUNCTION get_concept(p_concept_id NUMBER) RETURN CLOB IS
        v_result CLOB;
        v_concept KNOWLEDGE_CONCEPTS%ROWTYPE;
    BEGIN
        SELECT * INTO v_concept
        FROM KNOWLEDGE_CONCEPTS
        WHERE CONCEPT_ID = p_concept_id;
        
        v_result := '{' ||
            '"concept_id": ' || v_concept.CONCEPT_ID || ', ' ||
            '"concept_name": "' || v_concept.CONCEPT_NAME || '", ' ||
            '"concept_type": "' || v_concept.CONCEPT_TYPE || '", ' ||
            '"category": "' || NVL(v_concept.CATEGORY, 'null') || '", ' ||
            '"title": "' || NVL(v_concept.TITLE, 'null') || '", ' ||
            '"validation_status": "' || v_concept.VALIDATION_STATUS || '", ' ||
            '"confidence": ' || v_concept.CONFIDENCE || ', ' ||
            '"version": ' || v_concept.VERSION || ', ' ||
            '"source_type": "' || v_concept.SOURCE_TYPE || '", ' ||
            '"tags": ' || NVL(v_concept.TAGS, '[]') || ', ' ||
            '"created_at": "' || TO_CHAR(v_concept.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') || '", ' ||
            '"updated_at": "' || TO_CHAR(v_concept.UPDATED_AT, 'YYYY-MM-DD HH24:MI:SS') || '"' ||
        '}';
        
        RETURN v_result;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN '{"error": "Concept not found"}';
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_concept;
    
    -- ============================================
    -- KNOWLEDGE GRAPH OPERATIONS
    -- ============================================
    
    FUNCTION create_relationship(
        p_source_concept_id  NUMBER,
        p_target_concept_id  NUMBER,
        p_relationship_type  VARCHAR2,
        p_strength           NUMBER DEFAULT 1.0,
        p_properties         CLOB DEFAULT '{}'
    ) RETURN NUMBER IS
        v_relationship_id NUMBER;
    BEGIN
        -- Check for self-reference
        IF p_source_concept_id = p_target_concept_id THEN
            RAISE_APPLICATION_ERROR(-20001, 'Self-referencing relationships are not allowed');
        END IF;
        
        -- Generate next ID
        SELECT SEQ_KNOWLEDGE_GRAPH.NEXTVAL INTO v_relationship_id FROM DUAL;
        
        -- Insert relationship
        INSERT INTO KNOWLEDGE_GRAPH (
            RELATIONSHIP_ID, SOURCE_CONCEPT_ID, TARGET_CONCEPT_ID,
            RELATIONSHIP_TYPE, RELATIONSHIP_STRENGTH, PROPERTIES,
            CREATED_AT, UPDATED_AT, SOURCE_TYPE, CONFIDENCE
        ) VALUES (
            v_relationship_id, p_source_concept_id, p_target_concept_id,
            p_relationship_type, p_strength, p_properties,
            SYSTIMESTAMP, SYSTIMESTAMP, 'MANUAL', 0.8
        );
        
        COMMIT;
        RETURN v_relationship_id;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END create_relationship;
    
    FUNCTION get_relationships(
        p_concept_id    NUMBER,
        p_direction     VARCHAR2 DEFAULT 'BOTH',
        p_filter_types  CLOB DEFAULT NULL
    ) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN (
            SELECT 
                kg.RELATIONSHIP_ID,
                kg.SOURCE_CONCEPT_ID,
                kg.TARGET_CONCEPT_ID,
                kg.RELATIONSHIP_TYPE,
                kg.RELATIONSHIP_STRENGTH,
                kc_s.CONCEPT_NAME as SOURCE_NAME,
                kc_t.CONCEPT_NAME as TARGET_NAME
            FROM KNOWLEDGE_GRAPH kg
            JOIN KNOWLEDGE_CONCEPTS kc_s ON kg.SOURCE_CONCEPT_ID = kc_s.CONCEPT_ID
            JOIN KNOWLEDGE_CONCEPTS kc_t ON kg.TARGET_CONCEPT_ID = kc_t.CONCEPT_ID
            WHERE (p_direction = 'OUTGOING' AND kg.SOURCE_CONCEPT_ID = p_concept_id)
               OR (p_direction = 'INCOMING' AND kg.TARGET_CONCEPT_ID = p_concept_id)
               OR (p_direction = 'BOTH' AND (kg.SOURCE_CONCEPT_ID = p_concept_id OR kg.TARGET_CONCEPT_ID = p_concept_id))
            ORDER BY kg.RELATIONSHIP_STRENGTH DESC
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"relationship_id": ' || rec.RELATIONSHIP_ID || ', ' ||
                '"source_id": ' || rec.SOURCE_CONCEPT_ID || ', ' ||
                '"source_name": "' || rec.SOURCE_NAME || '", ' ||
                '"target_id": ' || rec.TARGET_CONCEPT_ID || ', ' ||
                '"target_name": "' || rec.TARGET_NAME || '", ' ||
                '"relationship_type": "' || rec.RELATIONSHIP_TYPE || '", ' ||
                '"strength": ' || rec.RELATIONSHIP_STRENGTH ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_relationships;
    
    FUNCTION traverse_graph(
        p_start_concept_id  NUMBER,
        p_max_hops          NUMBER DEFAULT 3,
        p_relationship_filter CLOB DEFAULT NULL
    ) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
    BEGIN
        -- Simple 1-hop traversal (expandable to multi-hop with recursive CTE)
        FOR rec IN (
            SELECT DISTINCT
                kg.RELATIONSHIP_ID,
                kc_s.CONCEPT_ID as SOURCE_ID,
                kc_s.CONCEPT_NAME as SOURCE_NAME,
                kg.RELATIONSHIP_TYPE,
                kc_t.CONCEPT_ID as TARGET_ID,
                kc_t.CONCEPT_NAME as TARGET_NAME
            FROM KNOWLEDGE_GRAPH kg
            JOIN KNOWLEDGE_CONCEPTS kc_s ON kg.SOURCE_CONCEPT_ID = kc_s.CONCEPT_ID
            JOIN KNOWLEDGE_CONCEPTS kc_t ON kg.TARGET_CONCEPT_ID = kc_t.CONCEPT_ID
            WHERE kc_s.CONCEPT_ID = p_start_concept_id
            ORDER BY kg.RELATIONSHIP_STRENGTH DESC
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"source": "' || rec.SOURCE_NAME || '", ' ||
                '"relationship": "' || rec.RELATIONSHIP_TYPE || '", ' ||
                '"target": "' || rec.TARGET_NAME || '"' ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END traverse_graph;
    
    FUNCTION find_path(
        p_source_concept_id  NUMBER,
        p_target_concept_id  NUMBER,
        p_max_hops           NUMBER DEFAULT 5
    ) RETURN CLOB IS
        v_result CLOB;
    BEGIN
        -- Simple path finding (1-hop for now)
        FOR rec IN (
            SELECT 
                kg.RELATIONSHIP_TYPE,
                kc_t.CONCEPT_NAME as TARGET_NAME
            FROM KNOWLEDGE_GRAPH kg
            JOIN KNOWLEDGE_CONCEPTS kc_t ON kg.TARGET_CONCEPT_ID = kc_t.CONCEPT_ID
            WHERE kg.SOURCE_CONCEPT_ID = p_source_concept_id
              AND kg.TARGET_CONCEPT_ID = p_target_concept_id
        ) LOOP
            v_result := '{"path_found": true, "relationship": "' || rec.RELATIONSHIP_TYPE || '", "target": "' || rec.TARGET_NAME || '"}';
            RETURN v_result;
        END LOOP;
        
        RETURN '{"path_found": false, "message": "No direct path found"}';
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END find_path;
    
    -- ============================================
    -- SEMANTIC SEARCH OPERATIONS
    -- ============================================
    
    FUNCTION semantic_search(
        p_query_text     VARCHAR2,
        p_limit          NUMBER DEFAULT 10,
        p_min_confidence NUMBER DEFAULT 0.5,
        p_category       VARCHAR2 DEFAULT NULL,
        p_concept_type   VARCHAR2 DEFAULT NULL
    ) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
        v_search_id NUMBER;
    BEGIN
        -- Log search history
        SELECT SEQ_SEARCH_HISTORY.NEXTVAL INTO v_search_id FROM DUAL;
        
        INSERT INTO KNOWLEDGE_SEARCH_HISTORY (
            SEARCH_ID, QUERY_TEXT, RESULT_COUNT, SEARCH_CONTEXT, SEARCHED_AT
        ) VALUES (
            v_search_id, p_query_text, 0, 'API', SYSTIMESTAMP
        );
        
        -- Semantic search (requires embedding generation in Python)
        FOR rec IN (
            SELECT 
                CONCEPT_ID,
                CONCEPT_NAME,
                CONCEPT_TYPE,
                CATEGORY,
                TITLE,
                CONFIDENCE,
                VALIDATION_STATUS
            FROM KNOWLEDGE_CONCEPTS
            WHERE VALIDATION_STATUS = 'VALIDATED'
              AND CONFIDENCE >= p_min_confidence
              AND (p_category IS NULL OR CATEGORY = p_category)
              AND (p_concept_type IS NULL OR CONCEPT_TYPE = p_concept_type)
            ORDER BY CONFIDENCE DESC
            FETCH FIRST p_limit ROWS ONLY
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"concept_id": ' || rec.CONCEPT_ID || ', ' ||
                '"concept_name": "' || rec.CONCEPT_NAME || '", ' ||
                '"concept_type": "' || rec.CONCEPT_TYPE || '", ' ||
                '"category": "' || NVL(rec.CATEGORY, 'null') || '", ' ||
                '"title": "' || NVL(rec.TITLE, 'null') || '", ' ||
                '"confidence": ' || rec.CONFIDENCE ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        
        -- Update search result count
        UPDATE KNOWLEDGE_SEARCH_HISTORY
        SET RESULT_COUNT = CASE WHEN v_first THEN 0 ELSE 1 END
        WHERE SEARCH_ID = v_search_id;
        
        COMMIT;
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END semantic_search;
    
    FUNCTION hybrid_search(
        p_query_text        VARCHAR2,
        p_relationship_types CLOB DEFAULT NULL,
        p_limit             NUMBER DEFAULT 10
    ) RETURN CLOB IS
    BEGIN
        -- For now, delegate to semantic search
        RETURN semantic_search(p_query_text, p_limit);
    END hybrid_search;
    
    -- ============================================
    -- KNOWLEDGE DISTILLATION OPERATIONS
    -- ============================================
    
    FUNCTION distill_experience(
        p_memory_ids     CLOB,
        p_knowledge_type VARCHAR2 DEFAULT 'EXPERIENCE',
        p_min_pattern_count NUMBER DEFAULT 3
    ) RETURN NUMBER IS
        v_knowledge_id NUMBER;
        v_memory_count NUMBER;
    BEGIN
        -- Count source memories
        SELECT COUNT(*) INTO v_memory_count
        FROM MEMORIES
        WHERE ID IN (
            SELECT TO_NUMBER(REGEXP_SUBSTR(p_memory_ids, '[0-9]+', 1, LEVEL))
            FROM DUAL
            CONNECT BY LEVEL <= REGEXP_COUNT(p_memory_ids, '[0-9]+')
        );
        
        -- Check minimum pattern count
        IF v_memory_count < p_min_pattern_count THEN
            RAISE_APPLICATION_ERROR(-20002, 'Insufficient memories for distillation: ' || v_memory_count || ' < ' || p_min_pattern_count);
        END IF;
        
        -- Create knowledge concept
        v_knowledge_id := create_concept(
            p_concept_name => 'Distilled ' || p_knowledge_type || ' from ' || v_memory_count || ' memories',
            p_concept_type => p_knowledge_type,
            p_category     => 'Auto-distilled',
            p_title        => 'Experience distilled from ' || v_memory_count || ' source memories',
            p_description  => 'Automatically distilled from repeated memory patterns',
            p_content      => 'Distilled from memories: ' || p_memory_ids,
            p_source_type  => 'DISTILLED',
            p_source_memory_ids => p_memory_ids,
            p_tags         => '["auto-distilled", "' || LOWER(p_knowledge_type) || '"]',
            p_confidence   => LEAST(1.0, v_memory_count / 10)
        );
        
        -- Log distillation
        INSERT INTO KNOWLEDGE_DISTILLATION_LOG (
            DISTILLATION_ID, MEMORY_IDS, MEMORY_COUNT,
            KNOWLEDGE_TYPE, KNOWLEDGE_TITLE, CONFIDENCE,
            DISTILLATION_METHOD, TRIGGERED_BY, KNOWLEDGE_ID, STATUS,
            CREATED_AT, COMPLETED_AT
        ) VALUES (
            SEQ_DISTILLATION_LOG.NEXTVAL, p_memory_ids, v_memory_count,
            p_knowledge_type, 'Auto-distilled ' || LOWER(p_knowledge_type), LEAST(1.0, v_memory_count / 10),
            'AUTOMATIC', 'Manual distillation request', v_knowledge_id, 'COMPLETED',
            SYSTIMESTAMP, SYSTIMESTAMP
        );
        
        COMMIT;
        RETURN v_knowledge_id;
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END distill_experience;
    
    FUNCTION should_distill(p_memory_category VARCHAR2) RETURN NUMBER IS
        v_count NUMBER;
    BEGIN
        -- Check if there are enough memories in this category to distill
        SELECT COUNT(*) INTO v_count
        FROM MEMORIES
        WHERE CATEGORY = p_memory_category
          AND CREATED_AT < SYSTIMESTAMP - 30;  -- At least 30 days old
        
        IF v_count >= 3 THEN
            RETURN 1;  -- TRUE
        ELSE
            RETURN 0;  -- FALSE
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN 0;
    END should_distill;
    
    FUNCTION get_distillation_candidates(
        p_category     VARCHAR2 DEFAULT NULL,
        p_min_age_days NUMBER DEFAULT 30
    ) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN (
            SELECT 
                CATEGORY,
                COUNT(*) as MEMORY_COUNT,
                MIN(CREATED_AT) as OLDEST_MEMORY,
                MAX(CREATED_AT) as NEWEST_MEMORY
            FROM MEMORIES
            WHERE CATEGORY = NVL(p_category, CATEGORY)
              AND CREATED_AT < SYSTIMESTAMP - p_min_age_days
            GROUP BY CATEGORY
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"category": "' || rec.CATEGORY || '", ' ||
                '"memory_count": ' || rec.MEMORY_COUNT || ', ' ||
                '"oldest": "' || TO_CHAR(rec.OLDEST_MEMORY, 'YYYY-MM-DD') || '", ' ||
                '"newest": "' || TO_CHAR(rec.NEWEST_MEMORY, 'YYYY-MM-DD') || '"' ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_distillation_candidates;
    
    -- ============================================
    -- VERSION MANAGEMENT
    -- ============================================
    
    FUNCTION get_version_history(p_concept_id NUMBER) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN (
            SELECT 
                VERSION_ID,
                TITLE,
                CHANGE_SUMMARY,
                CHANGE_REASON,
                VERSIONED_AT,
                VERSIONED_BY
            FROM KNOWLEDGE_VERSIONS
            WHERE CONCEPT_ID = p_concept_id
            ORDER BY VERSIONED_AT DESC
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"version_id": ' || rec.VERSION_ID || ', ' ||
                '"title": "' || NVL(rec.TITLE, 'null') || '", ' ||
                '"change_summary": "' || NVL(rec.CHANGE_SUMMARY, 'null') || '", ' ||
                '"versioned_at": "' || TO_CHAR(rec.VERSIONED_AT, 'YYYY-MM-DD HH24:MI:SS') || '"' ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_version_history;
    
    PROCEDURE restore_version(
        p_concept_id  NUMBER,
        p_version_id  NUMBER
    ) IS
        v_version KNOWLEDGE_VERSIONS%ROWTYPE;
    BEGIN
        -- Get the version to restore
        SELECT * INTO v_version
        FROM KNOWLEDGE_VERSIONS
        WHERE VERSION_ID = p_version_id
          AND CONCEPT_ID = p_concept_id;
        
        -- Update concept with version data
        UPDATE KNOWLEDGE_CONCEPTS
        SET TITLE = v_version.TITLE,
            DESCRIPTION = v_version.DESCRIPTION,
            CONTENT = v_version.CONTENT,
            VERSION = VERSION + 1,
            UPDATED_AT = SYSTIMESTAMP
        WHERE CONCEPT_ID = p_concept_id;
        
        COMMIT;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RAISE_APPLICATION_ERROR(-20003, 'Version not found');
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END restore_version;
    
    -- ============================================
    -- STATISTICS AND MONITORING
    -- ============================================
    
    FUNCTION get_kb_statistics RETURN CLOB IS
        v_total_concepts NUMBER;
        v_validated_concepts NUMBER;
        v_pending_concepts NUMBER;
        v_total_relationships NUMBER;
        v_total_distillations NUMBER;
    BEGIN
        SELECT COUNT(*) INTO v_total_concepts FROM KNOWLEDGE_CONCEPTS;
        SELECT COUNT(*) INTO v_validated_concepts FROM KNOWLEDGE_CONCEPTS WHERE VALIDATION_STATUS = 'VALIDATED';
        SELECT COUNT(*) INTO v_pending_concepts FROM KNOWLEDGE_CONCEPTS WHERE VALIDATION_STATUS = 'PENDING';
        SELECT COUNT(*) INTO v_total_relationships FROM KNOWLEDGE_GRAPH;
        SELECT COUNT(*) INTO v_total_distillations FROM KNOWLEDGE_DISTILLATION_LOG WHERE STATUS = 'COMPLETED';
        
        RETURN '{' ||
            '"total_concepts": ' || v_total_concepts || ', ' ||
            '"validated_concepts": ' || v_validated_concepts || ', ' ||
            '"pending_concepts": ' || v_pending_concepts || ', ' ||
            '"total_relationships": ' || v_total_relationships || ', ' ||
            '"total_distillations": ' || v_total_distillations ||
        '}';
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_kb_statistics;
    
    FUNCTION get_graph_metrics RETURN CLOB IS
        v_avg_relationships_per_concept NUMBER;
        v_max_relationships_concept NUMBER;
        v_isolated_concepts NUMBER;
    BEGIN
        SELECT AVG(rel_count) INTO v_avg_relationships_per_concept
        FROM (
            SELECT COUNT(*) as rel_count
            FROM KNOWLEDGE_GRAPH
            GROUP BY SOURCE_CONCEPT_ID
        );
        
        SELECT MAX(rel_count) INTO v_max_relationships_concept
        FROM (
            SELECT COUNT(*) as rel_count
            FROM KNOWLEDGE_GRAPH
            GROUP BY SOURCE_CONCEPT_ID
        );
        
        SELECT COUNT(*) INTO v_isolated_concepts
        FROM KNOWLEDGE_CONCEPTS kc
        WHERE NOT EXISTS (
            SELECT 1 FROM KNOWLEDGE_GRAPH kg
            WHERE kg.SOURCE_CONCEPT_ID = kc.CONCEPT_ID
               OR kg.TARGET_CONCEPT_ID = kc.CONCEPT_ID
        );
        
        RETURN '{' ||
            '"avg_relationships_per_concept": ' || NVL(v_avg_relationships_per_concept, 0) || ', ' ||
            '"max_relationships_concept": ' || NVL(v_max_relationships_concept, 0) || ', ' ||
            '"isolated_concepts": ' || v_isolated_concepts ||
        '}';
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_graph_metrics;
    
    FUNCTION get_distillation_activity(
        p_days NUMBER DEFAULT 7
    ) RETURN CLOB IS
        v_result CLOB := '[';
        v_first BOOLEAN := TRUE;
    BEGIN
        FOR rec IN (
            SELECT 
                DISTILLATION_ID,
                KNOWLEDGE_TYPE,
                KNOWLEDGE_TITLE,
                MEMORY_COUNT,
                CONFIDENCE,
                STATUS,
                CREATED_AT
            FROM KNOWLEDGE_DISTILLATION_LOG
            WHERE CREATED_AT > SYSTIMESTAMP - p_days
            ORDER BY CREATED_AT DESC
        ) LOOP
            IF NOT v_first THEN
                v_result := v_result || ', ';
            ELSE
                v_first := FALSE;
            END IF;
            
            v_result := v_result || '{' ||
                '"distillation_id": ' || rec.DISTILLATION_ID || ', ' ||
                '"knowledge_type": "' || rec.KNOWLEDGE_TYPE || '", ' ||
                '"title": "' || NVL(rec.KNOWLEDGE_TITLE, 'null') || '", ' ||
                '"memory_count": ' || NVL(rec.MEMORY_COUNT, 0) || ', ' ||
                '"confidence": ' || NVL(rec.CONFIDENCE, 0) || ', ' ||
                '"status": "' || rec.STATUS || '", ' ||
                '"created_at": "' || TO_CHAR(rec.CREATED_AT, 'YYYY-MM-DD HH24:MI:SS') || '"' ||
            '}';
        END LOOP;
        
        v_result := v_result || ']';
        RETURN v_result;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN '{"error": "' || SQLERRM || '"}';
    END get_distillation_activity;
    
    -- ============================================
    -- CLEANUP OPERATIONS
    -- ============================================
    
    PROCEDURE cleanup_deprecated(
        p_days_old NUMBER DEFAULT 90
    ) IS
        v_deleted_count NUMBER;
    BEGIN
        -- Delete old deprecated knowledge
        DELETE FROM KNOWLEDGE_CONCEPTS
        WHERE VALIDATION_STATUS = 'DEPRECATED'
          AND DEPRECATED_AT < SYSTIMESTAMP - p_days_old;
        
        v_deleted_count := SQL%ROWCOUNT;
        
        COMMIT;
        
        DBMS_OUTPUT.PUT_LINE('Cleaned up ' || v_deleted_count || ' deprecated knowledge concepts');
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;
            RAISE;
    END cleanup_deprecated;
    
END knowledge_base_api;
/
