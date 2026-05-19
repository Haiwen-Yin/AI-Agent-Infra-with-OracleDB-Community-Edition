-- ============================================================
-- Oracle Memory System v2.1.0 - Phase 2: PL/SQL API Packages
-- ============================================================

WHENEVER SQLERROR CONTINUE;
WHENEVER OSERROR CONTINUE;

CREATE OR REPLACE PACKAGE MEMORY_FUSION_ENGINE AS
    PROCEDURE fuse_similar_memories(
        p_category       IN VARCHAR2 DEFAULT NULL,
        p_min_similarity IN NUMBER   DEFAULT 0.85,
        p_dry_run        IN VARCHAR2 DEFAULT 'Y'
    );
    PROCEDURE extract_knowledge_from_memories(
        p_category  IN VARCHAR2 DEFAULT NULL,
        p_min_count IN NUMBER   DEFAULT 3
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
        p_category       IN VARCHAR2 DEFAULT NULL,
        p_min_similarity IN NUMBER   DEFAULT 0.85,
        p_dry_run        IN VARCHAR2 DEFAULT 'Y'
    ) IS
        v_fused_count NUMBER := 0;
    BEGIN
        FOR pair IN (
            SELECT
                e1.ENTITY_ID AS id1, e1.ENTITY_TYPE AS type1,
                e2.ENTITY_ID AS id2, e2.ENTITY_TYPE AS type2,
                e1.CATEGORY AS cat
            FROM ENTITIES e1
            JOIN ENTITIES e2
                ON e1.ENTITY_TYPE = 'MEMORY'
               AND e2.ENTITY_TYPE = 'MEMORY'
               AND e1.ENTITY_ID < e2.ENTITY_ID
               AND (p_category IS NULL OR e1.CATEGORY = p_category)
               AND e1.CATEGORY = e2.CATEGORY
               AND e1.STATUS = 'ACTIVE'
               AND e2.STATUS = 'ACTIVE'
            WHERE DBMS_LOB.SUBSTR(e1.CONTENT, 4000) LIKE '%' || SUBSTR(e2.TITLE, 1, 20) || '%'
               OR DBMS_LOB.SUBSTR(e2.CONTENT, 4000) LIKE '%' || SUBSTR(e1.TITLE, 1, 20) || '%'
        ) LOOP
            IF p_dry_run = 'N' THEN
                INSERT INTO ENTITY_EDGES (
                    EDGE_ID, SOURCE_ID, SOURCE_TYPE, TARGET_ID,
                    EDGE_TYPE, STRENGTH, CONFIDENCE, METADATA, CREATED_AT
                ) VALUES (
                    'E_' || RAWTOHEX(SYS_GUID()),
                    pair.id1, pair.type1, pair.id2,
                    'SIMILAR_TO', p_min_similarity, 0.9,
                    JSON_OBJECT('fusion_candidate' VALUE 'Y', 'category' VALUE pair.cat),
                    SYSTIMESTAMP
                );

                UPDATE ENTITIES
                SET STATUS = 'ARCHIVED', UPDATED_AT = SYSTIMESTAMP
                WHERE ENTITY_ID = pair.id2
                  AND ENTITY_TYPE = pair.type2;

                v_fused_count := v_fused_count + 1;
            END IF;
        END LOOP;

        MERGE INTO SYSTEM_CONFIG t
        USING (SELECT 'fusion.last_run' AS CONFIG_KEY FROM DUAL) s
        ON (t.CONFIG_KEY = s.CONFIG_KEY)
        WHEN MATCHED THEN UPDATE
            SET CONFIG_VALUE = TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                DESCRIPTION  = 'Last fusion run: ' || v_fused_count || ' memories fused',
                UPDATED_AT   = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT
            (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION, UPDATED_AT)
            VALUES (
                'fusion.last_run',
                TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                'Last fusion run: ' || v_fused_count || ' memories fused',
                SYSTIMESTAMP
            );

        COMMIT;
    END fuse_similar_memories;

    PROCEDURE extract_knowledge_from_memories(
        p_category  IN VARCHAR2 DEFAULT NULL,
        p_min_count IN NUMBER   DEFAULT 3
    ) IS
        v_new_id    VARCHAR2(64);
        v_extracted NUMBER := 0;
    BEGIN
        FOR grp IN (
            SELECT CATEGORY, COUNT(*) AS cnt
            FROM ENTITIES
            WHERE ENTITY_TYPE = 'MEMORY'
              AND STATUS = 'ACTIVE'
              AND (p_category IS NULL OR CATEGORY = p_category)
            GROUP BY CATEGORY
            HAVING COUNT(*) >= p_min_count
        ) LOOP
            v_new_id := RAWTOHEX(SYS_GUID());

            INSERT INTO ENTITIES (
                ENTITY_ID, ENTITY_TYPE, TITLE, SUMMARY, CATEGORY,
                STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
                IMPORTANCE, RETRIEVAL_COUNT, CREATED_AT, UPDATED_AT
            ) VALUES (
                v_new_id, 'KNOWLEDGE',
                'Extracted: ' || grp.CATEGORY || ' patterns',
                'Auto-extracted knowledge from ' || grp.cnt || ' memories in category ' || grp.CATEGORY,
                grp.CATEGORY,
                'ACTIVE', 'SYSTEM', 'SYSTEM', 'SHARED',
                5, 0, SYSTIMESTAMP, SYSTIMESTAMP
            );

            INSERT INTO KNOWLEDGE_META (
                ENTITY_ID, ENTITY_TYPE, DOMAIN, TOPIC,
                DIFFICULTY, REVIEW_COUNT, NEXT_REVIEW
            ) VALUES (
                v_new_id, 'KNOWLEDGE',
                grp.CATEGORY, grp.CATEGORY,
                'INTERMEDIATE', 0,
                SYSTIMESTAMP + NUMTODSINTERVAL(7, 'DAY')
            );

            v_extracted := v_extracted + 1;
        END LOOP;

        MERGE INTO SYSTEM_CONFIG t
        USING (SELECT 'knowledge.last_extraction' AS CONFIG_KEY FROM DUAL) s
        ON (t.CONFIG_KEY = s.CONFIG_KEY)
        WHEN MATCHED THEN UPDATE
            SET CONFIG_VALUE = TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                DESCRIPTION  = 'Last extraction: ' || v_extracted || ' knowledge items created',
                UPDATED_AT   = SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT
            (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION, UPDATED_AT)
            VALUES (
                'knowledge.last_extraction',
                TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
                'Last extraction: ' || v_extracted || ' knowledge items created',
                SYSTIMESTAMP
            );

        COMMIT;
    END extract_knowledge_from_memories;

    PROCEDURE decay_old_memories(
        p_days_threshold IN NUMBER DEFAULT 90,
        p_decay_factor   IN NUMBER DEFAULT 0.5
    ) IS
    BEGIN
        UPDATE ENTITIES
        SET IMPORTANCE = GREATEST(1, ROUND(IMPORTANCE * p_decay_factor)),
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
            'total_memories' : (
                SELECT COUNT(*) FROM ENTITIES
                WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ACTIVE'
            ),
            'total_knowledge' : (
                SELECT COUNT(*) FROM ENTITIES
                WHERE ENTITY_TYPE = 'KNOWLEDGE' AND STATUS = 'ACTIVE'
            ),
            'total_edges' : (
                SELECT COUNT(*) FROM ENTITY_EDGES
            ),
            'similar_pairs' : (
                SELECT COUNT(*) FROM ENTITY_EDGES
                WHERE EDGE_TYPE = 'SIMILAR_TO'
            ),
            'archived_memories' : (
                SELECT COUNT(*) FROM ENTITIES
                WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ARCHIVED'
            )
        ) INTO v_stats FROM DUAL;
        RETURN v_stats;
    END get_fusion_stats;

END MEMORY_FUSION_ENGINE;
/

CREATE OR REPLACE PACKAGE KNOWLEDGE_BASE_API AS
    PROCEDURE schedule_review(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    );
    PROCEDURE record_review(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    );
    FUNCTION get_due_reviews RETURN SYS_REFCURSOR;
    FUNCTION get_concept_lineage(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    ) RETURN JSON;
END KNOWLEDGE_BASE_API;
/

CREATE OR REPLACE PACKAGE BODY KNOWLEDGE_BASE_API AS

    PROCEDURE schedule_review(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    ) IS
    BEGIN
        UPDATE KNOWLEDGE_META
        SET NEXT_REVIEW = SYSTIMESTAMP +
            NUMTODSINTERVAL(LEAST(POWER(2, NVL(REVIEW_COUNT, 0)), 30), 'DAY')
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = p_entity_type;

        COMMIT;
    END schedule_review;

    PROCEDURE record_review(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    ) IS
    BEGIN
        UPDATE KNOWLEDGE_META
        SET REVIEW_COUNT  = REVIEW_COUNT + 1,
            LAST_REVIEWED = SYSTIMESTAMP,
            NEXT_REVIEW   = SYSTIMESTAMP +
                NUMTODSINTERVAL(LEAST(POWER(2, REVIEW_COUNT + 1), 30), 'DAY')
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = p_entity_type;

        COMMIT;
    END record_review;

    FUNCTION get_due_reviews RETURN SYS_REFCURSOR IS
        v_cur SYS_REFCURSOR;
    BEGIN
        OPEN v_cur FOR
            SELECT
                e.ENTITY_ID, e.ENTITY_TYPE, e.TITLE, e.CATEGORY,
                km.DOMAIN, km.TOPIC, km.DIFFICULTY,
                km.REVIEW_COUNT, km.LAST_REVIEWED, km.NEXT_REVIEW
            FROM ENTITIES e
            JOIN KNOWLEDGE_META km
                ON km.ENTITY_ID = e.ENTITY_ID
               AND km.ENTITY_TYPE = e.ENTITY_TYPE
            WHERE e.STATUS = 'ACTIVE'
              AND km.NEXT_REVIEW <= SYSTIMESTAMP
            ORDER BY km.NEXT_REVIEW;

        RETURN v_cur;
    END get_due_reviews;

    FUNCTION get_concept_lineage(
        p_entity_id   IN VARCHAR2,
        p_entity_type IN VARCHAR2
    ) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'entity_id'   VALUE p_entity_id,
            'entity_type' VALUE p_entity_type,
            'ancestors'   VALUE COALESCE(
                (SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'entity_id'   VALUE e.ENTITY_ID,
                        'entity_type' VALUE e.ENTITY_TYPE,
                        'title'       VALUE e.TITLE,
                        'edge_type'   VALUE eg.EDGE_TYPE,
                        'strength'    VALUE eg.STRENGTH
                    )
                    ORDER BY eg.STRENGTH DESC
                )
                FROM ENTITY_EDGES eg
                JOIN ENTITIES e
                    ON e.ENTITY_ID = eg.SOURCE_ID
                   AND e.ENTITY_TYPE = eg.SOURCE_TYPE
                WHERE eg.TARGET_ID = p_entity_id),
                JSON_ARRAY()
            ),
            'descendants' VALUE COALESCE(
                (SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'entity_id'   VALUE e.ENTITY_ID,
                        'entity_type' VALUE e.ENTITY_TYPE,
                        'title'       VALUE e.TITLE,
                        'edge_type'   VALUE eg.EDGE_TYPE,
                        'strength'    VALUE eg.STRENGTH
                    )
                    ORDER BY eg.STRENGTH DESC
                )
                FROM ENTITY_EDGES eg
                JOIN ENTITIES e
                    ON e.ENTITY_ID = eg.TARGET_ID
                WHERE eg.SOURCE_ID = p_entity_id
                  AND eg.SOURCE_TYPE = p_entity_type),
                JSON_ARRAY()
            )
        ) INTO v_result FROM DUAL;

        RETURN v_result;
    END get_concept_lineage;

END KNOWLEDGE_BASE_API;
/

CREATE OR REPLACE PACKAGE AGENT_PERMISSION_MANAGER AS
    FUNCTION check_entity_access(
        p_agent_id  IN VARCHAR2,
        p_entity_id IN VARCHAR2
    ) RETURN VARCHAR2;
    PROCEDURE log_access(
        p_agent_id    IN VARCHAR2,
        p_entity_id   IN VARCHAR2,
        p_access_type IN VARCHAR2,
        p_session_id  IN VARCHAR2 DEFAULT NULL
    );
    PROCEDURE cleanup_expired_sessions;
    PROCEDURE process_collaboration_requests;
END AGENT_PERMISSION_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY AGENT_PERMISSION_MANAGER AS

    FUNCTION check_entity_access(
        p_agent_id  IN VARCHAR2,
        p_entity_id IN VARCHAR2
    ) RETURN VARCHAR2 IS
        v_visibility VARCHAR2(16);
        v_owner      VARCHAR2(64);
    BEGIN
        SELECT VISIBILITY, OWNED_BY_AGENT
        INTO v_visibility, v_owner
        FROM ENTITIES
        WHERE ENTITY_ID = p_entity_id;

        IF v_visibility = 'PRIVATE' AND v_owner = p_agent_id THEN
            RETURN 'GRANTED';
        ELSIF v_visibility = 'SHARED' THEN
            RETURN 'GRANTED';
        ELSE
            RETURN 'DENIED';
        END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN 'DENIED';
    END check_entity_access;

    PROCEDURE log_access(
        p_agent_id    IN VARCHAR2,
        p_entity_id   IN VARCHAR2,
        p_access_type IN VARCHAR2,
        p_session_id  IN VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        INSERT INTO ENTITY_ACCESS_LOG (
            LOG_ID, ENTITY_ID, AGENT_ID,
            ACCESS_TYPE, ACCESS_TIME, SESSION_ID, CONTEXT
        ) VALUES (
            'LOG_' || RAWTOHEX(SYS_GUID()),
            p_entity_id, p_agent_id,
            p_access_type, SYSTIMESTAMP, p_session_id, NULL
        );

        COMMIT;
    END log_access;

    PROCEDURE cleanup_expired_sessions IS
    BEGIN
        UPDATE AGENT_SESSION
        SET IS_ACTIVE = 'N',
            END_TIME  = SYSTIMESTAMP
        WHERE IS_ACTIVE = 'Y'
          AND START_TIME < SYSTIMESTAMP - NUMTODSINTERVAL(300, 'MINUTE');

        COMMIT;
    END cleanup_expired_sessions;

    PROCEDURE process_collaboration_requests IS
    BEGIN
        NULL;
    END process_collaboration_requests;

END AGENT_PERMISSION_MANAGER;
/

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
        WHERE ENTITY_TYPE = 'MEMORY'
          AND STATUS = 'ACTIVE'
          AND CREATED_AT < SYSTIMESTAMP - p_days_threshold
          AND IMPORTANCE <= 1;

        COMMIT;
    END archive_old_entities;

    PROCEDURE update_tag_counts IS
    BEGIN
        NULL;
    END update_tag_counts;

END SESSION_CLEANUP;
/
