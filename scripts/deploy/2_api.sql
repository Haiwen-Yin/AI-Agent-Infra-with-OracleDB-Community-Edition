-- ============================================================
-- Oracle Memory System v2.3.0 - Phase 2: PL/SQL API Packages
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
            'total_memories' VALUE (
                SELECT COUNT(*) FROM ENTITIES
                WHERE ENTITY_TYPE = 'MEMORY' AND STATUS = 'ACTIVE'
            ),
            'total_knowledge' VALUE (
                SELECT COUNT(*) FROM ENTITIES
                WHERE ENTITY_TYPE = 'KNOWLEDGE' AND STATUS = 'ACTIVE'
            ),
            'total_edges' VALUE (
                SELECT COUNT(*) FROM ENTITY_EDGES
            ),
            'similar_pairs' VALUE (
                SELECT COUNT(*) FROM ENTITY_EDGES
                WHERE EDGE_TYPE = 'SIMILAR_TO'
            ),
            'archived_memories' VALUE (
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
    FUNCTION check_workspace_access(
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

    FUNCTION check_workspace_access(
        p_agent_id  IN VARCHAR2,
        p_entity_id IN VARCHAR2
    ) RETURN VARCHAR2 IS
        v_workspace_id  VARCHAR2(64);
        v_session_count NUMBER;
    BEGIN
        SELECT WORKSPACE_ID
        INTO v_workspace_id
        FROM ENTITIES
        WHERE ENTITY_ID = p_entity_id;

        SELECT COUNT(*)
        INTO v_session_count
        FROM AGENT_SESSION
        WHERE AGENT_ID = p_agent_id
          AND WORKSPACE_ID = v_workspace_id
          AND IS_ACTIVE = 'Y';

        IF v_session_count > 0 THEN
            RETURN 'GRANTED';
        ELSE
            RETURN 'DENIED';
        END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN 'DENIED';
    END check_workspace_access;

    FUNCTION check_entity_access(
        p_agent_id  IN VARCHAR2,
        p_entity_id IN VARCHAR2
    ) RETURN VARCHAR2 IS
        v_visibility    VARCHAR2(16);
        v_owner         VARCHAR2(64);
        v_workspace_id  VARCHAR2(64);
    BEGIN
        SELECT VISIBILITY, OWNED_BY_AGENT, WORKSPACE_ID
        INTO v_visibility, v_owner, v_workspace_id
        FROM ENTITIES
        WHERE ENTITY_ID = p_entity_id;

        IF v_visibility = 'PRIVATE' AND v_owner = p_agent_id THEN
            IF v_workspace_id IS NOT NULL THEN
                RETURN check_workspace_access(p_agent_id, p_entity_id);
            END IF;
            RETURN 'GRANTED';
        ELSIF v_visibility = 'SHARED' THEN
            IF v_workspace_id IS NOT NULL THEN
                RETURN check_workspace_access(p_agent_id, p_entity_id);
            END IF;
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

CREATE OR REPLACE PACKAGE WORKSPACE_MANAGER AS
    PROCEDURE create_workspace(
        p_workspace_id   IN VARCHAR2,
        p_owner_user_id  IN VARCHAR2,
        p_workspace_name IN VARCHAR2,
        p_workspace_type IN VARCHAR2 DEFAULT 'CONVERSATION',
        p_isolation_mode IN VARCHAR2 DEFAULT 'SHARED',
        p_metadata       IN JSON DEFAULT NULL
    );
    PROCEDURE update_workspace(
        p_workspace_id   IN VARCHAR2,
        p_workspace_name IN VARCHAR2 DEFAULT NULL,
        p_status         IN VARCHAR2 DEFAULT NULL,
        p_isolation_mode IN VARCHAR2 DEFAULT NULL,
        p_current_agent  IN VARCHAR2 DEFAULT NULL,
        p_summary        IN VARCHAR2 DEFAULT NULL,
        p_metadata       IN JSON DEFAULT NULL
    );
    PROCEDURE pause_workspace(p_workspace_id IN VARCHAR2);
    PROCEDURE complete_workspace(p_workspace_id IN VARCHAR2);
    PROCEDURE save_context(
        p_context_id   IN VARCHAR2,
        p_workspace_id IN VARCHAR2,
        p_agent_id     IN VARCHAR2,
        p_context_type IN VARCHAR2,
        p_context_data IN JSON,
        p_session_id   IN VARCHAR2 DEFAULT NULL,
        p_parent_ctx   IN VARCHAR2 DEFAULT NULL
    );
    FUNCTION get_latest_context(p_workspace_id IN VARCHAR2) RETURN JSON;
    FUNCTION get_context_chain(p_workspace_id IN VARCHAR2, p_limit IN NUMBER DEFAULT 10) RETURN JSON;
    PROCEDURE link_task(
        p_workspace_id IN VARCHAR2,
        p_plan_id      IN VARCHAR2
    );
    PROCEDURE unlink_task(
        p_workspace_id IN VARCHAR2,
        p_plan_id      IN VARCHAR2
    );
    PROCEDURE cleanup_abandoned(p_days_threshold IN NUMBER DEFAULT 30);
END WORKSPACE_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY WORKSPACE_MANAGER AS

    PROCEDURE create_workspace(
        p_workspace_id   IN VARCHAR2,
        p_owner_user_id  IN VARCHAR2,
        p_workspace_name IN VARCHAR2,
        p_workspace_type IN VARCHAR2 DEFAULT 'CONVERSATION',
        p_isolation_mode IN VARCHAR2 DEFAULT 'SHARED',
        p_metadata       IN JSON DEFAULT NULL
    ) IS
    BEGIN
        INSERT INTO WORKSPACES (
            WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME,
            WORKSPACE_TYPE, ISOLATION_MODE, METADATA
        ) VALUES (
            p_workspace_id, p_owner_user_id, p_workspace_name,
            p_workspace_type, p_isolation_mode, p_metadata
        );

        COMMIT;
    END create_workspace;

    PROCEDURE update_workspace(
        p_workspace_id   IN VARCHAR2,
        p_workspace_name IN VARCHAR2 DEFAULT NULL,
        p_status         IN VARCHAR2 DEFAULT NULL,
        p_isolation_mode IN VARCHAR2 DEFAULT NULL,
        p_current_agent  IN VARCHAR2 DEFAULT NULL,
        p_summary        IN VARCHAR2 DEFAULT NULL,
        p_metadata       IN JSON DEFAULT NULL
    ) IS
    BEGIN
        UPDATE WORKSPACES
        SET WORKSPACE_NAME   = COALESCE(p_workspace_name, WORKSPACE_NAME),
            STATUS           = COALESCE(p_status, STATUS),
            ISOLATION_MODE   = COALESCE(p_isolation_mode, ISOLATION_MODE),
            CURRENT_AGENT_ID = COALESCE(p_current_agent, CURRENT_AGENT_ID),
            SUMMARY          = COALESCE(p_summary, SUMMARY),
            METADATA         = COALESCE(p_metadata, METADATA),
            UPDATED_AT       = SYSTIMESTAMP
        WHERE WORKSPACE_ID = p_workspace_id;

        COMMIT;
    END update_workspace;

    PROCEDURE pause_workspace(p_workspace_id IN VARCHAR2) IS
    BEGIN
        UPDATE WORKSPACES
        SET STATUS    = 'PAUSED',
            UPDATED_AT = SYSTIMESTAMP
        WHERE WORKSPACE_ID = p_workspace_id;

        COMMIT;
    END pause_workspace;

    PROCEDURE complete_workspace(p_workspace_id IN VARCHAR2) IS
    BEGIN
        UPDATE WORKSPACES
        SET STATUS    = 'COMPLETED',
            UPDATED_AT = SYSTIMESTAMP
        WHERE WORKSPACE_ID = p_workspace_id;

        COMMIT;
    END complete_workspace;

    PROCEDURE save_context(
        p_context_id   IN VARCHAR2,
        p_workspace_id IN VARCHAR2,
        p_agent_id     IN VARCHAR2,
        p_context_type IN VARCHAR2,
        p_context_data IN JSON,
        p_session_id   IN VARCHAR2 DEFAULT NULL,
        p_parent_ctx   IN VARCHAR2 DEFAULT NULL
    ) IS
    BEGIN
        INSERT INTO WORKSPACE_CONTEXT (
            CONTEXT_ID, WORKSPACE_ID, AGENT_ID,
            SESSION_ID, CONTEXT_TYPE, CONTEXT_DATA, PARENT_CONTEXT_ID
        ) VALUES (
            p_context_id, p_workspace_id, p_agent_id,
            p_session_id, p_context_type, p_context_data, p_parent_ctx
        );

        COMMIT;
    END save_context;

    FUNCTION get_latest_context(p_workspace_id IN VARCHAR2) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'context_id'   VALUE CONTEXT_ID,
            'workspace_id' VALUE WORKSPACE_ID,
            'agent_id'     VALUE AGENT_ID,
            'session_id'   VALUE SESSION_ID,
            'context_type' VALUE CONTEXT_TYPE,
            'context_data' VALUE CONTEXT_DATA,
            'parent_ctx'   VALUE PARENT_CONTEXT_ID,
            'created_at'   VALUE TO_CHAR(CREATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS.FF3')
        )
        INTO v_result
        FROM WORKSPACE_CONTEXT
        WHERE WORKSPACE_ID = p_workspace_id
        ORDER BY CREATED_AT DESC
        FETCH FIRST 1 ROW ONLY;

        RETURN v_result;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN NULL;
    END get_latest_context;

    FUNCTION get_context_chain(
        p_workspace_id IN VARCHAR2,
        p_limit        IN NUMBER DEFAULT 10
    ) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT COALESCE(
            JSON_ARRAYAGG(
                JSON_OBJECT(
                    'context_id'   VALUE CONTEXT_ID,
                    'workspace_id' VALUE WORKSPACE_ID,
                    'agent_id'     VALUE AGENT_ID,
                    'session_id'   VALUE SESSION_ID,
                    'context_type' VALUE CONTEXT_TYPE,
                    'context_data' VALUE CONTEXT_DATA,
                    'parent_ctx'   VALUE PARENT_CONTEXT_ID,
                    'created_at'   VALUE TO_CHAR(CREATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS.FF3')
                )
                ORDER BY CREATED_AT DESC
            ),
            JSON_ARRAY()
        )
        INTO v_result
        FROM (
            SELECT *
            FROM WORKSPACE_CONTEXT
            WHERE WORKSPACE_ID = p_workspace_id
            ORDER BY CREATED_AT DESC
            FETCH FIRST p_limit ROWS ONLY
        );

        RETURN v_result;
    END get_context_chain;

    PROCEDURE link_task(
        p_workspace_id IN VARCHAR2,
        p_plan_id      IN VARCHAR2
    ) IS
    BEGIN
        MERGE INTO WORKSPACE_TASKS t
        USING (SELECT p_workspace_id AS WORKSPACE_ID, p_plan_id AS PLAN_ID FROM DUAL) s
        ON (t.WORKSPACE_ID = s.WORKSPACE_ID AND t.PLAN_ID = s.PLAN_ID)
        WHEN NOT MATCHED THEN INSERT
            (WORKSPACE_ID, PLAN_ID, ASSIGNED_AT)
            VALUES (s.WORKSPACE_ID, s.PLAN_ID, SYSTIMESTAMP);

        COMMIT;
    END link_task;

    PROCEDURE unlink_task(
        p_workspace_id IN VARCHAR2,
        p_plan_id      IN VARCHAR2
    ) IS
    BEGIN
        DELETE FROM WORKSPACE_TASKS
        WHERE WORKSPACE_ID = p_workspace_id
          AND PLAN_ID = p_plan_id;

        COMMIT;
    END unlink_task;

    PROCEDURE cleanup_abandoned(p_days_threshold IN NUMBER DEFAULT 30) IS
    BEGIN
        DELETE FROM WORKSPACES
        WHERE STATUS = 'ABANDONED'
          AND UPDATED_AT < SYSTIMESTAMP - p_days_threshold;

        COMMIT;
    END cleanup_abandoned;

END WORKSPACE_MANAGER;
/


CREATE OR REPLACE PACKAGE SPEC_MANAGER AS
    FUNCTION create_spec(p_title VARCHAR2, p_content CLOB DEFAULT NULL, 
        p_summary VARCHAR2 DEFAULT NULL, p_category VARCHAR2 DEFAULT NULL,
        p_importance NUMBER DEFAULT 5, p_owned_by_agent VARCHAR2 DEFAULT NULL,
        p_visibility VARCHAR2 DEFAULT 'SHARED', p_workspace_id VARCHAR2 DEFAULT NULL,
        p_spec_scope VARCHAR2 DEFAULT NULL, p_complexity VARCHAR2 DEFAULT 'MEDIUM',
        p_acceptance_criteria JSON DEFAULT NULL, p_constraints JSON DEFAULT NULL,
        p_parent_spec_id VARCHAR2 DEFAULT NULL) RETURN VARCHAR2;
    
    FUNCTION update_spec(p_entity_id VARCHAR2, p_title VARCHAR2 DEFAULT NULL,
        p_content CLOB DEFAULT NULL, p_summary VARCHAR2 DEFAULT NULL,
        p_category VARCHAR2 DEFAULT NULL, p_importance NUMBER DEFAULT NULL,
        p_visibility VARCHAR2 DEFAULT NULL, p_spec_status VARCHAR2 DEFAULT NULL,
        p_spec_scope VARCHAR2 DEFAULT NULL, p_complexity VARCHAR2 DEFAULT NULL,
        p_acceptance_criteria JSON DEFAULT NULL, p_constraints JSON DEFAULT NULL) RETURN NUMBER;
    
    FUNCTION get_spec(p_entity_id VARCHAR2) RETURN JSON;
    
    FUNCTION list_specs(p_spec_scope VARCHAR2 DEFAULT NULL, 
        p_spec_status VARCHAR2 DEFAULT NULL, p_limit NUMBER DEFAULT 50) RETURN SYS_REFCURSOR;
    
    FUNCTION link_spec_to_plan(p_spec_id VARCHAR2, p_plan_id VARCHAR2,
        p_link_type VARCHAR2, p_link_strength NUMBER DEFAULT 1.0) RETURN VARCHAR2;
    
    FUNCTION validate_spec(p_spec_id VARCHAR2, p_plan_id VARCHAR2 DEFAULT NULL) RETURN VARCHAR2;
    
    FUNCTION derive_spec(p_parent_spec_id VARCHAR2, p_title VARCHAR2,
        p_content CLOB DEFAULT NULL, p_summary VARCHAR2 DEFAULT NULL) RETURN VARCHAR2;
    
    PROCEDURE delete_spec(p_entity_id VARCHAR2);
END SPEC_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY SPEC_MANAGER AS

    FUNCTION create_spec(p_title VARCHAR2, p_content CLOB DEFAULT NULL, 
        p_summary VARCHAR2 DEFAULT NULL, p_category VARCHAR2 DEFAULT NULL,
        p_importance NUMBER DEFAULT 5, p_owned_by_agent VARCHAR2 DEFAULT NULL,
        p_visibility VARCHAR2 DEFAULT 'SHARED', p_workspace_id VARCHAR2 DEFAULT NULL,
        p_spec_scope VARCHAR2 DEFAULT NULL, p_complexity VARCHAR2 DEFAULT 'MEDIUM',
        p_acceptance_criteria JSON DEFAULT NULL, p_constraints JSON DEFAULT NULL,
        p_parent_spec_id VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
        v_entity_id VARCHAR2(64);
    BEGIN
        v_entity_id := RAWTOHEX(SYS_GUID());

        INSERT INTO ENTITIES (
            ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
            STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
            IMPORTANCE, RETRIEVAL_COUNT, WORKSPACE_ID, CREATED_AT, UPDATED_AT
        ) VALUES (
            v_entity_id, 'SPEC', p_title, p_content, p_summary, p_category,
            'DRAFT', p_owned_by_agent, p_owned_by_agent, p_visibility,
            p_importance, 0, p_workspace_id, SYSTIMESTAMP, SYSTIMESTAMP
        );

        INSERT INTO SPEC_META (
            ENTITY_ID, ENTITY_TYPE, SPEC_VERSION, SPEC_STATUS,
            ACCEPTANCE_CRITERIA, "CONSTRAINTS", SPEC_SCOPE,
            COMPLEXITY, PARENT_SPEC_ID
        ) VALUES (
            v_entity_id, 'SPEC', 1, 'DRAFT',
            p_acceptance_criteria, p_constraints, p_spec_scope,
            p_complexity, p_parent_spec_id
        );

        COMMIT;
        RETURN v_entity_id;
    END create_spec;

    FUNCTION update_spec(p_entity_id VARCHAR2, p_title VARCHAR2 DEFAULT NULL,
        p_content CLOB DEFAULT NULL, p_summary VARCHAR2 DEFAULT NULL,
        p_category VARCHAR2 DEFAULT NULL, p_importance NUMBER DEFAULT NULL,
        p_visibility VARCHAR2 DEFAULT NULL, p_spec_status VARCHAR2 DEFAULT NULL,
        p_spec_scope VARCHAR2 DEFAULT NULL, p_complexity VARCHAR2 DEFAULT NULL,
        p_acceptance_criteria JSON DEFAULT NULL, p_constraints JSON DEFAULT NULL) RETURN NUMBER IS
        v_rows NUMBER;
    BEGIN
        UPDATE ENTITIES
        SET TITLE       = COALESCE(p_title, TITLE),
            CONTENT     = COALESCE(p_content, CONTENT),
            SUMMARY     = COALESCE(p_summary, SUMMARY),
            CATEGORY    = COALESCE(p_category, CATEGORY),
            IMPORTANCE  = COALESCE(p_importance, IMPORTANCE),
            VISIBILITY  = COALESCE(p_visibility, VISIBILITY),
            UPDATED_AT  = SYSTIMESTAMP
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = 'SPEC';

        v_rows := SQL%ROWCOUNT;

        UPDATE SPEC_META
        SET SPEC_STATUS         = COALESCE(p_spec_status, SPEC_STATUS),
            SPEC_SCOPE          = COALESCE(p_spec_scope, SPEC_SCOPE),
            COMPLEXITY          = COALESCE(p_complexity, COMPLEXITY),
            ACCEPTANCE_CRITERIA = COALESCE(p_acceptance_criteria, ACCEPTANCE_CRITERIA),
            "CONSTRAINTS"         = COALESCE(p_constraints, "CONSTRAINTS")
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = 'SPEC';

        COMMIT;
        RETURN v_rows;
    END update_spec;

    FUNCTION get_spec(p_entity_id VARCHAR2) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'entity_id'    VALUE e.ENTITY_ID,
            'entity_type'  VALUE e.ENTITY_TYPE,
            'title'        VALUE e.TITLE,
            'summary'      VALUE e.SUMMARY,
            'category'     VALUE e.CATEGORY,
            'status'       VALUE e.STATUS,
            'owned_by'     VALUE e.OWNED_BY_AGENT,
            'visibility'   VALUE e.VISIBILITY,
            'importance'   VALUE e.IMPORTANCE,
            'workspace_id' VALUE e.WORKSPACE_ID,
            'spec_meta'    VALUE JSON_OBJECT(
                'spec_version'        VALUE sm.SPEC_VERSION,
                'spec_status'         VALUE sm.SPEC_STATUS,
                'spec_scope'          VALUE sm.SPEC_SCOPE,
                'complexity'          VALUE sm.COMPLEXITY,
                'acceptance_criteria' VALUE sm.ACCEPTANCE_CRITERIA,
                'constraints'         VALUE sm."CONSTRAINTS",
                'parent_spec_id'      VALUE sm.PARENT_SPEC_ID
            ),
            'plan_links'   VALUE COALESCE(
                (SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'link_id'       VALUE spl.LINK_ID,
                        'plan_id'       VALUE spl.PLAN_ID,
                        'link_type'     VALUE spl.LINK_TYPE,
                        'link_strength' VALUE spl.LINK_STRENGTH,
                        'created_at'    VALUE TO_CHAR(spl.CREATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
                    )
                )
                FROM SPEC_PLAN_LINKS spl
                WHERE spl.SPEC_ID = p_entity_id),
                JSON_ARRAY()
            ),
            'created_at'   VALUE TO_CHAR(e.CREATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS'),
            'updated_at'   VALUE TO_CHAR(e.UPDATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
        ) INTO v_result
        FROM ENTITIES e
        JOIN SPEC_META sm
            ON sm.ENTITY_ID = e.ENTITY_ID
           AND sm.ENTITY_TYPE = e.ENTITY_TYPE
        WHERE e.ENTITY_ID = p_entity_id
          AND e.ENTITY_TYPE = 'SPEC';

        RETURN v_result;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN NULL;
    END get_spec;

    FUNCTION list_specs(p_spec_scope VARCHAR2 DEFAULT NULL, 
        p_spec_status VARCHAR2 DEFAULT NULL, p_limit NUMBER DEFAULT 50) RETURN SYS_REFCURSOR IS
        v_cur SYS_REFCURSOR;
    BEGIN
        OPEN v_cur FOR
            SELECT
                e.ENTITY_ID, e.TITLE, e.SUMMARY, e.CATEGORY,
                e.STATUS, e.OWNED_BY_AGENT, e.IMPORTANCE,
                sm.SPEC_VERSION, sm.SPEC_STATUS, sm.SPEC_SCOPE,
                sm.COMPLEXITY, sm.PARENT_SPEC_ID,
                e.CREATED_AT, e.UPDATED_AT
            FROM ENTITIES e
            JOIN SPEC_META sm
                ON sm.ENTITY_ID = e.ENTITY_ID
               AND sm.ENTITY_TYPE = e.ENTITY_TYPE
            WHERE e.ENTITY_TYPE = 'SPEC'
              AND (p_spec_scope IS NULL OR sm.SPEC_SCOPE = p_spec_scope)
              AND (p_spec_status IS NULL OR sm.SPEC_STATUS = p_spec_status)
            ORDER BY e.UPDATED_AT DESC
            FETCH FIRST p_limit ROWS ONLY;

        RETURN v_cur;
    END list_specs;

    FUNCTION link_spec_to_plan(p_spec_id VARCHAR2, p_plan_id VARCHAR2,
        p_link_type VARCHAR2, p_link_strength NUMBER DEFAULT 1.0) RETURN VARCHAR2 IS
        v_link_id VARCHAR2(64);
    BEGIN
        v_link_id := RAWTOHEX(SYS_GUID());

        INSERT INTO SPEC_PLAN_LINKS (
            LINK_ID, SPEC_ID, PLAN_ID, LINK_TYPE, LINK_STRENGTH
        ) VALUES (
            v_link_id, p_spec_id, p_plan_id, p_link_type, p_link_strength
        );

        COMMIT;
        RETURN v_link_id;
    END link_spec_to_plan;

    FUNCTION validate_spec(p_spec_id VARCHAR2, p_plan_id VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
        v_criteria    JSON;
        v_spec_title  VARCHAR2(512);
        v_total       NUMBER := 0;
        v_passed      NUMBER := 0;
        v_rate        NUMBER := 0;
        v_status_str  VARCHAR2(16) := 'FAIL';
    BEGIN
        SELECT sm.ACCEPTANCE_CRITERIA, e.TITLE
        INTO v_criteria, v_spec_title
        FROM SPEC_META sm
        JOIN ENTITIES e ON e.ENTITY_ID = sm.ENTITY_ID AND e.ENTITY_TYPE = sm.ENTITY_TYPE
        WHERE sm.ENTITY_ID = p_spec_id
          AND sm.ENTITY_TYPE = 'SPEC';

        SELECT COUNT(*), COUNT(CASE WHEN ts.STATUS = 'SUCCESS' THEN 1 END)
        INTO v_total, v_passed
        FROM TASK_STEPS ts
        WHERE ts.PLAN_ID = COALESCE(p_plan_id, (
            SELECT spl.PLAN_ID FROM SPEC_PLAN_LINKS spl
            WHERE spl.SPEC_ID = p_spec_id AND spl.LINK_TYPE = 'VALIDATES'
            FETCH FIRST 1 ROW ONLY
        ));

        IF v_total > 0 THEN
            v_rate := ROUND(v_passed / v_total, 4);
            IF v_passed = v_total THEN
                v_status_str := 'PASS';
            END IF;
        END IF;

        RETURN JSON_OBJECT(
            'spec_id'       VALUE p_spec_id,
            'spec_title'    VALUE v_spec_title,
            'plan_id'       VALUE p_plan_id,
            'total_steps'   VALUE v_total,
            'passed_steps'  VALUE v_passed,
            'pass_rate'     VALUE v_rate,
            'status'        VALUE v_status_str
        );
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN JSON_OBJECT(
                'spec_id' VALUE p_spec_id,
                'status'  VALUE 'NOT_FOUND'
            );
    END validate_spec;

    FUNCTION derive_spec(p_parent_spec_id VARCHAR2, p_title VARCHAR2,
        p_content CLOB DEFAULT NULL, p_summary VARCHAR2 DEFAULT NULL) RETURN VARCHAR2 IS
        v_entity_id    VARCHAR2(64);
        v_parent_scope VARCHAR2(64);
        v_new_version  NUMBER;
    BEGIN
        SELECT sm.SPEC_SCOPE, sm.SPEC_VERSION + 1
        INTO v_parent_scope, v_new_version
        FROM SPEC_META sm
        WHERE sm.ENTITY_ID = p_parent_spec_id
          AND sm.ENTITY_TYPE = 'SPEC';

        v_entity_id := RAWTOHEX(SYS_GUID());

        INSERT INTO ENTITIES (
            ENTITY_ID, ENTITY_TYPE, TITLE, CONTENT, SUMMARY, CATEGORY,
            STATUS, OWNED_BY_AGENT, SOURCE_AGENT, VISIBILITY,
            IMPORTANCE, RETRIEVAL_COUNT, CREATED_AT, UPDATED_AT
        ) SELECT
            v_entity_id, 'SPEC', p_title, COALESCE(p_content, e.CONTENT),
            COALESCE(p_summary, e.SUMMARY), e.CATEGORY,
            'DRAFT', e.OWNED_BY_AGENT, e.OWNED_BY_AGENT, e.VISIBILITY,
            e.IMPORTANCE, 0, SYSTIMESTAMP, SYSTIMESTAMP
        FROM ENTITIES e
        WHERE e.ENTITY_ID = p_parent_spec_id
          AND e.ENTITY_TYPE = 'SPEC';

        INSERT INTO SPEC_META (
            ENTITY_ID, ENTITY_TYPE, SPEC_VERSION, SPEC_STATUS,
            ACCEPTANCE_CRITERIA, "CONSTRAINTS", SPEC_SCOPE,
            COMPLEXITY, PARENT_SPEC_ID
        ) SELECT
            v_entity_id, 'SPEC', v_new_version, 'DRAFT',
            sm.ACCEPTANCE_CRITERIA, sm."CONSTRAINTS", v_parent_scope,
            sm.COMPLEXITY, p_parent_spec_id
        FROM SPEC_META sm
        WHERE sm.ENTITY_ID = p_parent_spec_id
          AND sm.ENTITY_TYPE = 'SPEC';

        COMMIT;
        RETURN v_entity_id;
    END derive_spec;

    PROCEDURE delete_spec(p_entity_id VARCHAR2) IS
    BEGIN
        DELETE FROM SPEC_PLAN_LINKS
        WHERE SPEC_ID = p_entity_id;

        DELETE FROM SPEC_META
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = 'SPEC';

        DELETE FROM ENTITIES
        WHERE ENTITY_ID = p_entity_id
          AND ENTITY_TYPE = 'SPEC';

        COMMIT;
    END delete_spec;

END SPEC_MANAGER;
/


CREATE OR REPLACE PACKAGE COLLAB_GROUP_MANAGER AS
    FUNCTION create_group(p_group_name VARCHAR2, p_group_type VARCHAR2,
        p_description VARCHAR2 DEFAULT NULL, p_coordinator_agent_id VARCHAR2 DEFAULT NULL,
        p_sharing_policy VARCHAR2 DEFAULT 'OPEN', p_metadata JSON DEFAULT NULL) RETURN VARCHAR2;
    
    FUNCTION update_group(p_group_id VARCHAR2, p_group_name VARCHAR2 DEFAULT NULL,
        p_description VARCHAR2 DEFAULT NULL, p_coordinator_agent_id VARCHAR2 DEFAULT NULL,
        p_sharing_policy VARCHAR2 DEFAULT NULL, p_status VARCHAR2 DEFAULT NULL,
        p_metadata JSON DEFAULT NULL) RETURN NUMBER;
    
    FUNCTION get_group(p_group_id VARCHAR2) RETURN JSON;
    
    FUNCTION add_member(p_group_id VARCHAR2, p_agent_id VARCHAR2,
        p_role VARCHAR2 DEFAULT 'MEMBER') RETURN VARCHAR2;
    
    FUNCTION remove_member(p_group_id VARCHAR2, p_agent_id VARCHAR2) RETURN NUMBER;
    
    PROCEDURE archive_group(p_group_id VARCHAR2);
END COLLAB_GROUP_MANAGER;
/

CREATE OR REPLACE PACKAGE BODY COLLAB_GROUP_MANAGER AS

    FUNCTION create_group(p_group_name VARCHAR2, p_group_type VARCHAR2,
        p_description VARCHAR2 DEFAULT NULL, p_coordinator_agent_id VARCHAR2 DEFAULT NULL,
        p_sharing_policy VARCHAR2 DEFAULT 'OPEN', p_metadata JSON DEFAULT NULL) RETURN VARCHAR2 IS
        v_group_id     VARCHAR2(64);
        v_workspace_id VARCHAR2(64);
    BEGIN
        v_group_id := RAWTOHEX(SYS_GUID());
        v_workspace_id := 'WS_CG_' || RAWTOHEX(SYS_GUID());

        INSERT INTO WORKSPACES (
            WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME,
            WORKSPACE_TYPE, ISOLATION_MODE, METADATA
        ) VALUES (
            v_workspace_id, p_coordinator_agent_id,
            'Collab: ' || p_group_name,
            'COLLAB_GROUP', 'SHARED', p_metadata
        );

        INSERT INTO COLLAB_GROUPS (
            GROUP_ID, GROUP_NAME, GROUP_TYPE, DESCRIPTION,
            WORKSPACE_ID, COORDINATOR_AGENT_ID, SHARING_POLICY,
            STATUS, METADATA
        ) VALUES (
            v_group_id, p_group_name, p_group_type, p_description,
            v_workspace_id, p_coordinator_agent_id, p_sharing_policy,
            'ACTIVE', p_metadata
        );

        COMMIT;
        RETURN v_group_id;
    END create_group;

    FUNCTION update_group(p_group_id VARCHAR2, p_group_name VARCHAR2 DEFAULT NULL,
        p_description VARCHAR2 DEFAULT NULL, p_coordinator_agent_id VARCHAR2 DEFAULT NULL,
        p_sharing_policy VARCHAR2 DEFAULT NULL, p_status VARCHAR2 DEFAULT NULL,
        p_metadata JSON DEFAULT NULL) RETURN NUMBER IS
        v_rows NUMBER;
    BEGIN
        UPDATE COLLAB_GROUPS
        SET GROUP_NAME           = COALESCE(p_group_name, GROUP_NAME),
            DESCRIPTION          = COALESCE(p_description, DESCRIPTION),
            COORDINATOR_AGENT_ID = COALESCE(p_coordinator_agent_id, COORDINATOR_AGENT_ID),
            SHARING_POLICY       = COALESCE(p_sharing_policy, SHARING_POLICY),
            STATUS               = COALESCE(p_status, STATUS),
            METADATA             = COALESCE(p_metadata, METADATA),
            UPDATED_AT           = SYSTIMESTAMP
        WHERE GROUP_ID = p_group_id;

        v_rows := SQL%ROWCOUNT;
        COMMIT;
        RETURN v_rows;
    END update_group;

    FUNCTION get_group(p_group_id VARCHAR2) RETURN JSON IS
        v_result JSON;
    BEGIN
        SELECT JSON_OBJECT(
            'group_id'       VALUE g.GROUP_ID,
            'group_name'     VALUE g.GROUP_NAME,
            'group_type'     VALUE g.GROUP_TYPE,
            'description'    VALUE g.DESCRIPTION,
            'workspace_id'   VALUE g.WORKSPACE_ID,
            'coordinator'    VALUE g.COORDINATOR_AGENT_ID,
            'sharing_policy' VALUE g.SHARING_POLICY,
            'status'         VALUE g.STATUS,
            'metadata'       VALUE g.METADATA,
            'members'        VALUE COALESCE(
                (SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'member_id'       VALUE m.MEMBER_ID,
                        'agent_id'        VALUE m.AGENT_ID,
                        'role'            VALUE m.ROLE,
                        'personal_workspace_id' VALUE m.PERSONAL_WORKSPACE_ID,
                        'joined_at'       VALUE TO_CHAR(m.JOINED_AT, 'YYYY-MM-DD"T"HH24:MI:SS'),
                        'status'          VALUE m.STATUS
                    )
                    ORDER BY m.JOINED_AT
                )
                FROM COLLAB_GROUP_MEMBERS m
                WHERE m.GROUP_ID = p_group_id
                  AND m.STATUS = 'ACTIVE'),
                JSON_ARRAY()
            ),
            'created_at'     VALUE TO_CHAR(g.CREATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS'),
            'updated_at'     VALUE TO_CHAR(g.UPDATED_AT, 'YYYY-MM-DD"T"HH24:MI:SS')
        ) INTO v_result
        FROM COLLAB_GROUPS g
        WHERE g.GROUP_ID = p_group_id;

        RETURN v_result;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            RETURN NULL;
    END get_group;

    FUNCTION add_member(p_group_id VARCHAR2, p_agent_id VARCHAR2,
        p_role VARCHAR2 DEFAULT 'MEMBER') RETURN VARCHAR2 IS
        v_member_id         VARCHAR2(64);
        v_personal_ws_id    VARCHAR2(64);
    BEGIN
        v_member_id := RAWTOHEX(SYS_GUID());

        IF p_role IN ('LEAD', 'CONTRIBUTOR') THEN
            v_personal_ws_id := 'WS_PG_' || RAWTOHEX(SYS_GUID());

            INSERT INTO WORKSPACES (
                WORKSPACE_ID, OWNER_USER_ID, WORKSPACE_NAME,
                WORKSPACE_TYPE, ISOLATION_MODE, METADATA
            ) VALUES (
                v_personal_ws_id, p_agent_id,
                'Personal: ' || p_agent_id || ' in ' || p_group_id,
                'PERSONAL_IN_GROUP', 'ISOLATED', NULL
            );
        END IF;

        INSERT INTO COLLAB_GROUP_MEMBERS (
            MEMBER_ID, GROUP_ID, AGENT_ID, ROLE,
            PERSONAL_WORKSPACE_ID, STATUS
        ) VALUES (
            v_member_id, p_group_id, p_agent_id, p_role,
            v_personal_ws_id, 'ACTIVE'
        );

        COMMIT;
        RETURN v_member_id;
    END add_member;

    FUNCTION remove_member(p_group_id VARCHAR2, p_agent_id VARCHAR2) RETURN NUMBER IS
    BEGIN
        UPDATE COLLAB_GROUP_MEMBERS
        SET STATUS = 'LEFT'
        WHERE GROUP_ID = p_group_id
          AND AGENT_ID = p_agent_id
          AND STATUS = 'ACTIVE';

        COMMIT;
        RETURN SQL%ROWCOUNT;
    END remove_member;

    PROCEDURE archive_group(p_group_id VARCHAR2) IS
    BEGIN
        UPDATE COLLAB_GROUPS
        SET STATUS    = 'ARCHIVED',
            UPDATED_AT = SYSTIMESTAMP
        WHERE GROUP_ID = p_group_id;

        UPDATE COLLAB_GROUP_MEMBERS
        SET STATUS = 'REMOVED'
        WHERE GROUP_ID = p_group_id
          AND STATUS = 'ACTIVE';

        COMMIT;
    END archive_group;

END COLLAB_GROUP_MANAGER;
/

COMMIT;

PROMPT ============================================================
PROMPT Oracle Memory System v2.3.0 API Deployment Complete
PROMPT ============================================================
