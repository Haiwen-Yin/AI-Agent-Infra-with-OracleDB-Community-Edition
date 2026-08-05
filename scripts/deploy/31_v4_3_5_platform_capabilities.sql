-- v4.3.5 database-authoritative platform capability switches.
DECLARE
  PROCEDURE ddl(s VARCHAR2) IS BEGIN EXECUTE IMMEDIATE s; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;
BEGIN
  ddl('CREATE TABLE CX_PLATFORM_CAPABILITIES (CAPABILITY_KEY VARCHAR2(64) PRIMARY KEY, ENABLED CHAR(1) DEFAULT ''Y'' NOT NULL CHECK (ENABLED IN (''Y'',''N'')), MANDATORY CHAR(1) DEFAULT ''N'' NOT NULL CHECK (MANDATORY IN (''Y'',''N'')), VERSION NUMBER(10,0) DEFAULT 1 NOT NULL CHECK (VERSION > 0), UPDATED_BY VARCHAR2(128), UPDATE_REASON VARCHAR2(2000), CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL, UPDATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)');
  ddl('CREATE TABLE CX_PLATFORM_CAPABILITY_DEPENDENCIES (CAPABILITY_KEY VARCHAR2(64) NOT NULL REFERENCES CX_PLATFORM_CAPABILITIES(CAPABILITY_KEY), DEPENDS_ON_KEY VARCHAR2(64) NOT NULL REFERENCES CX_PLATFORM_CAPABILITIES(CAPABILITY_KEY), PRIMARY KEY (CAPABILITY_KEY,DEPENDS_ON_KEY), CHECK (CAPABILITY_KEY <> DEPENDS_ON_KEY))');
  ddl('CREATE TABLE CX_PLATFORM_CAPABILITY_HISTORY (HISTORY_ID VARCHAR2(128) PRIMARY KEY, CAPABILITY_KEY VARCHAR2(64) NOT NULL REFERENCES CX_PLATFORM_CAPABILITIES(CAPABILITY_KEY), FROM_ENABLED CHAR(1) NOT NULL CHECK (FROM_ENABLED IN (''Y'',''N'')), TO_ENABLED CHAR(1) NOT NULL CHECK (TO_ENABLED IN (''Y'',''N'')), RESULT_VERSION NUMBER(10,0) NOT NULL CHECK (RESULT_VERSION > 1), CHANGED_BY VARCHAR2(128) NOT NULL, REASON VARCHAR2(2000) NOT NULL, CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)');
  ddl('CREATE INDEX IDX_CX_PLATFORM_CAP_ENABLED ON CX_PLATFORM_CAPABILITIES(ENABLED,MANDATORY)');
  ddl('CREATE INDEX IDX_CX_PLATFORM_CAP_HISTORY ON CX_PLATFORM_CAPABILITY_HISTORY(CAPABILITY_KEY,CREATED_AT)');
END;
/
DECLARE
  PROCEDURE seed_cap(k VARCHAR2, m CHAR) IS BEGIN MERGE INTO CX_PLATFORM_CAPABILITIES d USING (SELECT k CAPABILITY_KEY, m MANDATORY FROM DUAL) s ON (d.CAPABILITY_KEY=s.CAPABILITY_KEY) WHEN NOT MATCHED THEN INSERT (CAPABILITY_KEY,MANDATORY) VALUES (s.CAPABILITY_KEY,s.MANDATORY); END;
  PROCEDURE seed_dep(k VARCHAR2, dep VARCHAR2) IS BEGIN MERGE INTO CX_PLATFORM_CAPABILITY_DEPENDENCIES t USING (SELECT k CAPABILITY_KEY,dep DEPENDS_ON_KEY FROM DUAL) s ON (t.CAPABILITY_KEY=s.CAPABILITY_KEY AND t.DEPENDS_ON_KEY=s.DEPENDS_ON_KEY) WHEN NOT MATCHED THEN INSERT (CAPABILITY_KEY,DEPENDS_ON_KEY) VALUES (s.CAPABILITY_KEY,s.DEPENDS_ON_KEY); END;
BEGIN
  seed_cap('identity','Y'); seed_cap('authorization','Y'); seed_cap('security','Y'); seed_cap('audit_write','Y'); seed_cap('agents','Y'); seed_cap('users','Y'); seed_cap('platform_config','Y');
  seed_cap('portal','N'); seed_cap('monitor','N'); seed_cap('tasks','N'); seed_cap('workspaces','N'); seed_cap('knowledge','N'); seed_cap('memory','N'); seed_cap('skills','N'); seed_cap('specs','N'); seed_cap('branches','N'); seed_cap('collaboration','N'); seed_cap('loops','N'); seed_cap('graph','N'); seed_cap('channels','N'); seed_cap('barriers','N'); seed_cap('approvals','N'); seed_cap('compliance','N'); seed_cap('audit_view','N'); seed_cap('organization','N');
  seed_dep('branches','tasks'); seed_dep('branches','workspaces'); seed_dep('collaboration','agents'); seed_dep('loops','tasks'); seed_dep('graph','tasks'); seed_dep('channels','agents'); seed_dep('barriers','channels'); seed_dep('approvals','audit_write'); seed_dep('compliance','agents'); seed_dep('compliance','audit_write'); seed_dep('audit_view','audit_write'); seed_dep('organization','users'); seed_dep('organization','agents');
END;
/
