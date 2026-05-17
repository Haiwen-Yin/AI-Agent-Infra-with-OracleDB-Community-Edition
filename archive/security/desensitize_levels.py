-- ============================================
-- desensitize_levels.sql
-- P1-紧急: 分层脱敏策略配置表
-- Version: v0.4.3 (Desensitization Levels)
-- Author: Haiwen Yin (胖头鱼 🐟)
-- Date: 2026-05-08
-- ============================================

CREATE TABLE DESENSITIZE_LEVELS (
    LEVEL_ID NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    LEVEL_NAME VARCHAR2(50) NOT NULL UNIQUE,
    DESCRIPTION CLOB,
    IS_ACTIVE VARCHAR2(1) CHECK (IS_ACTIVE IN ('Y', 'N')) DEFAULT 'Y',
    CREATED_AT TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP,
    
    UNIQUE (LEVEL_NAME, IS_ACTIVE)
);

-- Insert default levels
INSERT INTO DESENSITIZE_LEVELS (LEVEL_NAME, DESCRIPTION, IS_ACTIVE) 
VALUES ('LOGGING', 'HIGH - Complete masking for logs and monitoring', 'Y');

INSERT INTO DESENSITIZE_LEVELS (LEVEL_NAME, DESCRIPTION, IS_ACTIVE) 
VALUES ('DEBUGGING', 'MEDIUM - Partial masking to preserve debugging capability', 'Y');

INSERT INTO DESENSITIZE_LEVELS (LEVEL_NAME, DESCRIPTION, IS_ACTIVE) 
VALUES ('ANALYTICS', 'LOW - Aggregated data for analysis purposes', 'N');

INSERT INTO DESENSITIZE_LEVELS (LEVEL_NAME, DESCRIPTION, IS_ACTIVE) 
VALUES ('SHARING', 'FULL - Complete masking for external sharing', 'Y');

-- Create view to check available levels
CREATE OR REPLACE VIEW AVAILABLE_DESENSITIZATION_LEVELS AS
SELECT LEVEL_ID, LEVEL_NAME, DESCRIPTION, IS_ACTIVE, CREATED_AT
FROM DESENSITIZE_LEVELS
WHERE IS_ACTIVE = 'Y'
ORDER BY LEVEL_NAME;
