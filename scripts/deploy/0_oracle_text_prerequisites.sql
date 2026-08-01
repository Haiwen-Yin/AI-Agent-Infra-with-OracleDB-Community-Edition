-- ============================================================
-- 0_oracle_text_prerequisites.sql - Oracle Text prerequisites
-- AI Agent Infra with OracleDB v4.3.0
-- ============================================================
--
-- Run this script as SYSDBA in the target PDB before 1_schema.sql.
-- The schema creates an Oracle Text CONTEXT index with a
-- MULTI_COLUMN_DATASTORE preference. Oracle Text does not expose the
-- required CTX_DDL package to a new schema owner by default.
--
-- This script is intentionally separate from 4_grants.sql because the
-- privilege is needed while 1_schema.sql is creating the preference and
-- index. It grants no runtime data access and is not needed by Business
-- Agent End Users.
--
-- ============================================================

DEFINE SCHEMA_OWNER = 'AIADMIN'

PROMPT ============================================================
PROMPT Granting Oracle Text schema-creation prerequisites
PROMPT ============================================================

GRANT CTXAPP TO &&SCHEMA_OWNER;
GRANT EXECUTE ON CTXSYS.CTX_DDL TO &&SCHEMA_OWNER;

PROMPT Oracle Text prerequisites granted.
