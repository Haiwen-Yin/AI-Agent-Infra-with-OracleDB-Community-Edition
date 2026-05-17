-- ============================================================
-- Oracle Memory System v2.0.0 - Phase 2: PL/SQL API Packages
-- ============================================================

WHENEVER SQLERROR CONTINUE;
WHENEVER OSERROR CONTINUE;

-- ============================================================
-- Package: MEMORY_FUSION_ENGINE
-- Merges similar memories, extracts knowledge from patterns
-- ============================================================

CREATE OR REPLACE PACKAGE MEMORY_FUSION_ENGINE AS
    PROCEDURE fuse_similar_memories(
        p_category     IN VARCHAR2 DEFAULT NULL,
        p_min_similarity IN NUMBER DEFAULT 0.85,
        p_dry_run      IN VARCHAR2 DEFAULT 'Y'
    );
    PROCEDURE extract_knowledge_from_memories(
        p_category     IN VARCHAR2 DEFAULT NULL,
        p_min_count    IN NUMBER DEFAULT 3
    );
    PROCEDURE decay_old_memories(
        p_days_threshold IN NUMBER DEFAULT 90,
        p_decay_factor   IN NUMBER DEFAULT 0.5
    );
    FUNCTION get_fusion_stats RETURN JSON;
END MEMORY_FUSION_ENGINE;
/

CREATE OR REPLACE PACKAGE BODY MEMORY_FUSION_ENGINE AS

    PROCEDURE fuse_similar_memories(
        p_category     IN VARCHAR2 DEFAULT NULL,
        p_min_similarity IN NUMBER DEFAULT 0.85,
        p_dry_run      IN VARCHAR2 DEFAULT 'Y'
    ) IS
        v_fused_count NUMBER := 0;
    BEGIN
        FOR pair IN (
            SELECT
                e1.ENTITY_ID AS id1, e2.ENTITY_ID AS id2,
                e1.NAME AS name1, e2.NAME AS name2,
                e1.CATEGORY AS cat
            FROM ENTITIES e1
            JOIN ENTITIES e2 ON e1.ENTITY_TYPE = 'MEMORY'
                AND e2.ENTITY_TYPE = 'MEMORY'
                AND e1.ENTITY_ID < e2.ENTITY_ID
                AND (p_category IS NULL OR e1.CATEGORY = p_category)
                AND e1.CATEGORY = e2.CATEGORY
                AND e1.STATUS = 'ACTIVE' AND e2.STATUS = 'ACTIVE'
            WHERE DBMS_LOB.SUBSTR(e1.CONTENT, 4000) LIKE '%' || SUBSTR(e2.NAME, 1, 20) || '%'
               OR DBMS_LOB.SUBSTR(e2.CONTENT, 4000) LIKE '%' || SUBSTR(e1.NAME, 1, 20) || '%'
        ) LOOP
            IF p_dry_run = 'N' THEN
                INSERT INTO ENTITY_EDGES (SOURCE_ID, TARGET_ID, EDGE_TYPE, STRENGTH, CONFIDENCE, PROPERTIES)
                VALUES (pair.id1, pair.id2, 'SIMILAR_TO', p_min_similarity, 0.9,
                        JSON_OBJECT('fusion_candidate' : 'Y', 'category' : pair.cat));

                UPDATE ENTITIES SET STATUS = 'ARCHIVED', UPDATED_AT = SYSTIMESTAMP
                WHERE ENTITY_ID = pair.id2;

                v_fused_count := v_fused_count + 1;
            END IF;
        END LOOP;

        INSERT INTO SYSTEM_CONFIG (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
        VALUES ('fusion.last_run', TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                'Last fusion run: ' || v_fused_count || ' memories fused')
        ON DUPLICATE KEY UPDATE CONFIG_VALUE = TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                DESCRIPTION = 'Last fusion run: ' || v_fused_count || ' memories fused';

        COMMIT;
    END fuse_similar_memories;

    PROCEDURE extract_knowledge_from_memories(
        p_category     IN VARCHAR2 DEFAULT NULL,
        p_min_count    IN NUMBER DEFAULT 3
    ) IS
        v_extracted NUMBER := 0;
    BEGIN
        FOR grp IN (
            SELECT CATEGORY, COUNT(*) AS cnt,
                   LISTAGG(ENTITY_ID, ',') WITHIN GROUP (ORDER BY ENTITY_ID) AS entity_ids
            FROM ENTITIES
            WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ACTIVE'
              AND (p_category IS NULL OR CATEGORY = p_category)
            GROUP BY CATEGORY
            HAVING COUNT(*) >= p_min_count
        ) LOOP
            INSERT INTO ENTITIES (ENTITY_TYPE, NAME, DESCRIPTION, CATEGORY, PRIORITY, STATUS,
                                  TAGS, METADATA, OWNED_BY_AGENT, VISIBILITY)
            VALUES ('KNOWLEDGE',
                    'Extracted: ' || grp.CATEGORY || ' patterns',
                    'Auto-extracted knowledge from ' || grp.cnt || ' memories in category ' || grp.CATEGORY,
                    grp.CATEGORY, 1, 'ACTIVE',
                    '[]', JSON_OBJECT('source_type' : 'FUSION', 'source_entity_count' : grp.cnt),
                    'SYSTEM', 'SHARED');

            v_extracted := v_extracted + 1;
        END LOOP;
        COMMIT;
    END extract_knowledge_from_memories;

    PROCEDURE decay_old_memories(
        p_days_threshold IN NUMBER DEFAULT 90,
        p_decay_factor   IN NUMBER DEFAULT 0.5
    ) IS
    BEGIN
        UPDATE ENTITIES
        SET PRIORITY = GREATEST(1, ROUND(PRIORITY * p_decay_factor)),
            UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_TYPE = 'MEMORY'
          AND STATUS = 'ACTIVE'
          AND CREATED_AT < SYSTIMESTAMP - p_days_threshold;

        COMMIT;
    END decay_old_memories;

    FUNCTION get_fusion_stats RETURN JSON IS
        v_stats JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'total_memories' : (SELECT COUNT(*) FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ACTIVE'),
            'total_knowledge' : (SELECT COUNT(*) FROM ENTITIES WHERE ENTITY_TYPE = 'KNOWLEDGE' AND STATUS = 'ACTIVE'),
            'total_edges' : (SELECT COUNT(*) FROM ENTITY_EDGES),
            'similar_pairs' : (SELECT COUNT(*) FROM ENTITY_EDGES WHERE EDGE_TYPE = 'SIMILAR_TO'),
            'archived_memories' : (SELECT COUNT(*) FROM ENTITIES WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ARCHIVED')
        ) INTO v_stats FROM DUAL;
        RETURN v_stats;
    END get_fusion_stats;

END MEMORY_FUSION_ENGINE;
/

-- ============================================================
-- Package: KNOWLEDGE_BASE_API
-- Knowledge concept CRUD, validation, versioning
-- ============================================================

CREATE OR REPLACE PACKAGE KNOWLEDGE_BASE_API AS
    PROCEDURE validate_concept(p_entity_id IN NUMBER, p_validator IN VARCHAR2 DEFAULT 'SYSTEM');
    PROCEDURE deprecate_concept(p_entity_id IN NUMBER, p_reason IN VARCHAR2 DEFAULT NULL);
    PROCEDURE create_concept_version(p_entity_id IN NUMBER, p_new_content IN CLOB);
    FUNCTION get_unvalidated RETURN SYS_REFCURSOR;
    FUNCTION get_concept_lineage(p_entity_id IN NUMBER) RETURN JSON;
END KNOWLEDGE_BASE_API;
/

CREATE OR REPLACE PACKAGE BODY KNOWLEDGE_BASE_API AS

    PROCEDURE validate_concept(p_entity_id IN NUMBER, p_validator IN VARCHAR2 DEFAULT 'SYSTEM') IS
    BEGIN
        UPDATE KNOWLEDGE_META
        SET VALIDATION_STATUS = 'VALIDATED',
            VALIDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id;

        UPDATE ENTITIES SET STATUS = 'ACTIVE', UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id AND ENTITY_TYPE = 'KNOWLEDGE';

        INSERT INTO ENTITY_ACCESS_LOG (AGENT_ID, ENTITY_ID, ACCESS_TYPE, ACCESS_TIME)
        VALUES (p_validator, p_entity_id, 'WRITE', SYSTIMESTAMP);

        COMMIT;
    END validate_concept;

    PROCEDURE deprecate_concept(p_entity_id IN NUMBER, p_reason IN VARCHAR2 DEFAULT NULL) IS
    BEGIN
        UPDATE KNOWLEDGE_META
        SET IS_CURRENT = 'N',
            DEPRECATED_AT = SYSTIMESTAMP,
            VALIDATION_STATUS = 'DEPRECATED'
        WHERE ENTITY_ID = p_entity_id;

        UPDATE ENTITIES SET STATUS = 'DEPRECATED', UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id;

        IF p_reason IS NOT NULL THEN
            UPDATE ENTITIES SET METADATA = JSON_TRANSFORM(METADATA, SET '$.deprecation_reason' = p_reason)
            WHERE ENTITY_ID = p_entity_id;
        END IF;

        COMMIT;
    END deprecate_concept;

    PROCEDURE create_concept_version(p_entity_id IN NUMBER, p_new_content IN CLOB) IS
        v_old_version NUMBER;
    BEGIN
        SELECT VERSION INTO v_old_version FROM KNOWLEDGE_META WHERE ENTITY_ID = p_entity_id;

        UPDATE KNOWLEDGE_META SET IS_CURRENT = 'N' WHERE ENTITY_ID = p_entity_id;

        INSERT INTO KNOWLEDGE_META (ENTITY_ID, SOURCE_TYPE, SOURCE_ENTITY_IDS,
                                     VALIDATION_STATUS, CONFIDENCE, VERSION, IS_CURRENT)
        VALUES (p_entity_id, 'VERSIONING', JSON_ARRAY(p_entity_id),
                'PENDING', 0.8, v_old_version + 1, 'Y');

        UPDATE ENTITIES SET CONTENT = p_new_content, UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id;

        COMMIT;
    END create_concept_version;

    FUNCTION get_unvalidated RETURN SYS_REFCURSOR IS
        v_cur SYS_REFCURSOR;
    BEGIN
        OPEN v_cur FOR
            SELECT e.ENTITY_ID, e.NAME, e.CATEGORY, e.DESCRIPTION,
                   km.VALIDATION_STATUS, km.CONFIDENCE, km.VERSION
            FROM ENTITIES e
            JOIN KNOWLEDGE_META km ON km.ENTITY_ID = e.ENTITY_ID
            WHERE e.ENTITY_TYPE = 'KNOWLEDGE' AND km.VALIDATION_STATUS = 'PENDING'
            ORDER BY e.CREATED_AT;
        RETURN v_cur;
    END get_unvalidated;

    FUNCTION get_concept_lineage(p_entity_id IN NUMBER) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'entity_id' : p_entity_id,
            'ancestors' : (
                SELECT JSON_ARRAYAGG(
                    JSON_OBJECT('id' : e.ENTITY_ID, 'name' : e.NAME, 'edge' : eg.EDGE_TYPE)
                    ORDER BY eg.STRENGTH DESC
                )
                FROM ENTITY_EDGES eg
                JOIN ENTITIES e ON e.ENTITY_ID = eg.SOURCE_ID
                WHERE eg.TARGET_ID = p_entity_id
                  AND eg.EDGE_TYPE IN ('DERIVED_FROM', 'EVOLVED_FROM')
            ),
            'descendants' : (
                SELECT JSON_ARRAYAGG(
                    JSON_OBJECT('id' : e.ENTITY_ID, 'name' : e.NAME, 'edge' : eg.EDGE_TYPE)
                    ORDER BY eg.STRENGTH DESC
                )
                FROM ENTITY_EDGES eg
                JOIN ENTITIES e ON e.ENTITY_ID = eg.TARGET_ID
                WHERE eg.SOURCE_ID = p_entity_id
                  AND eg.EDGE_TYPE IN ('DERIVED_FROM', 'EVOLVED_FROM')
            )
        ) INTO v_result FROM DUAL;
        RETURN v_result;
    END get_concept_lineage;

END KNOWLEDGE_BASE_API;
/

-- ============================================================
-- Package: AGENT_PERMISSION_MANAGER
-- Agent access control, session cleanup, collaboration
-- ============================================================

CREATE OR REPLACE PACKAGE AGENT_PERMISSION_MANAGER AS
    FUNCTION check_entity_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER, p_access_type IN VARCHAR2)
        RETURN VARCHAR2;
    PROCEDURE grant_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER, p_granted_by IN VARCHAR2);
    PROCEDURE revoke_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER);
    PROCEDURE cleanup_expired_sessions;
    PROCEDURE process_collaboration_requests;
END AGENT_PERMISSION_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY AGENT_PERMISSION_MANAGER AS

    FUNCTION check_entity_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER, p_access_type IN VARCHAR2)
        RETURN VARCHAR2 IS
        v_visibility VARCHAR2(32);
        v_owner      VARCHAR2(64);
        v_accessible JSON;
    BEGIN
        SELECT VISIBILITY, OWNED_BY_AGENT, ACCESSIBLE_TO
        INTO v_visibility, v_owner, v_accessible
        FROM ENTITIES WHERE ENTITY_ID = p_entity_id;

        IF v_visibility = 'SHARED' THEN
            RETURN 'GRANTED';
        ELSIF v_visibility = 'PRIVATE' AND v_owner = p_agent_id THEN
            RETURN 'GRANTED';
        ELSIF v_visibility = 'COLLABORATIVE' THEN
            IF v_owner = p_agent_id THEN
                RETURN 'GRANTED';
            END IF;
            FOR rec IN (
                SELECT VALUE jt_val
                FROM JSON_TABLE(v_accessible, '$[*]' COLUMNS(VALUE VARCHAR2(64) PATH '$')) jt
            ) LOOP
                IF rec.jt_val = p_agent_id THEN
                    RETURN 'GRANTED';
                END IF;
            END LOOP;
            RETURN 'DENIED';
        END IF;
        RETURN 'DENIED';
    END check_entity_access;

    PROCEDURE grant_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER, p_granted_by IN VARCHAR2) IS
        v_accessible JSON;
    BEGIN
        SELECT ACCESSIBLE_TO INTO v_accessible FROM ENTITIES WHERE ENTITY_ID = p_entity_id;

        UPDATE ENTITIES
        SET ACCESSIBLE_TO = JSON_TRANSFORM(v_accessible, APPEND '$' = p_agent_id),
            VISIBILITY = 'COLLABORATIVE',
            UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id;

        INSERT INTO ENTITY_ACCESS_LOG (AGENT_ID, ENTITY_ID, ACCESS_TYPE, ACCESS_TIME)
        VALUES (p_agent_id, p_entity_id, 'SHARE', SYSTIMESTAMP);

        COMMIT;
    END grant_access;

    PROCEDURE revoke_access(p_agent_id IN VARCHAR2, p_entity_id IN NUMBER) IS
    BEGIN
        UPDATE ENTITIES
        SET ACCESSIBLE_TO = JSON_TRANSFORM(ACCESSIBLE_TO, REMOVE '$[' ||
                (SELECT idx FROM JSON_TABLE(ACCESSIBLE_TO, '$[*]' COLUMNS(
                    idx NUMBER PATH '$.ordinality',
                    val VARCHAR2(64) PATH '$'
                )) WHERE val = p_agent_id) || ']'),
            UPDATED_AT = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id;

        COMMIT;
    END revoke_access;

    PROCEDURE cleanup_expired_sessions IS
    BEGIN
        UPDATE AGENT_SESSION
        SET IS_ACTIVE = 'N', END_TIME = SYSTIMESTAMP
        WHERE IS_ACTIVE = 'Y'
          AND LAST_ACTIVITY < SYSTIMESTAMP - INTERVAL '300' MINUTE;

        COMMIT;
    END cleanup_expired_sessions;

    PROCEDURE process_collaboration_requests IS
    BEGIN
        UPDATE AGENT_COLLABORATION
        SET STATUS = 'EXPIRED'
        WHERE STATUS = 'PENDING'
          AND CREATED_AT < SYSTIMESTAMP - INTERVAL '7' DAY;

        COMMIT;
    END process_collaboration_requests;

END AGENT_PERMISSION_MANAGER;
/

-- ============================================================
-- Package: SESSION_CLEANUP
-- Session and access log maintenance
-- ============================================================

CREATE OR REPLACE PACKAGE SESSION_CLEANUP AS
    PROCEDURE purge_access_logs(p_days_to_keep IN NUMBER DEFAULT 90);
    PROCEDURE purge_inactive_sessions(p_days_to_keep IN NUMBER DEFAULT 30);
    PROCEDURE archive_old_entities(p_days_threshold IN NUMBER DEFAULT 180);
    PROCEDURE update_tag_counts;
END SESSION_CLEANUP;
/

CREATE OR REPLACE PACKAGE BODY SESSION_CLEANUP AS

    PROCEDURE purge_access_logs(p_days_to_keep IN NUMBER DEFAULT 90) IS
    BEGIN
        DELETE FROM ENTITY_ACCESS_LOG
        WHERE ACCESS_TIME < SYSTIMESTAMP - p_days_to_keep;

        DELETE FROM AGENT_PERMISSION_LOG
        WHERE CHANGED_AT < SYSTIMESTAMP - p_days_to_keep;

        COMMIT;
    END purge_access_logs;

    PROCEDURE purge_inactive_sessions(p_days_to_keep IN NUMBER DEFAULT 30) IS
    BEGIN
        DELETE FROM AGENT_SESSION
        WHERE IS_ACTIVE = 'N'
          AND END_TIME < SYSTIMESTAMP - p_days_to_keep;

        COMMIT;
    END purge_inactive_sessions;

    PROCEDURE archive_old_entities(p_days_threshold IN NUMBER DEFAULT 180) IS
    BEGIN
        UPDATE ENTITIES
        SET STATUS = 'ARCHIVED', UPDATED_AT = SYSTIMESTAMP
        WHERE STATUS = 'ACTIVE'
          AND ENTITY_TYPE = 'MEMORY'
          AND CREATED_AT < SYSTIMESTAMP - p_days_threshold
          AND PRIORITY <= 1;

        COMMIT;
    END archive_old_entities;

    PROCEDURE update_tag_counts IS
    BEGIN
        MERGE INTO TAGS t
        USING (
            SELECT TAG_ID, COUNT(*) AS cnt
            FROM ENTITY_TAGS
            GROUP BY TAG_ID
        ) src
        ON (t.TAG_ID = src.TAG_ID)
        WHEN MATCHED THEN UPDATE SET USAGE_COUNT = src.cnt;

        DELETE FROM TAGS WHERE USAGE_COUNT = 0;

        COMMIT;
    END update_tag_counts;

END SESSION_CLEANUP;
/

-- ============================================================
-- End Phase 2: API
-- ============================================================
