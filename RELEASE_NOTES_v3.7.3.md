# Release Notes — v3.7.3

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-23

License: Apache License 2.0

Official Website: https://db4agent.top

---

## Overview

v3.7.3 is a deployment fix release. Resolves issues discovered during fresh initialization deployment that prevented successful setup.

---

## Bug Fixes

### 1. Schema Creation Order (Oracle COM/ENT)

- **CONTEXT_BRANCHES** — Removed inline FOREIGN KEY constraints referencing tables not yet created (WORKSPACES, WORKSPACE_CONTEXT, AGENT_REGISTRY). FK constraints now added via ALTER TABLE after all parent tables exist.
- **LOOP_RUNS** — Moved UK_LOOP_RUNS_ID UNIQUE(RUN_ID) constraint inline to CREATE TABLE. Previously added via ALTER TABLE after creation, causing ORA-02270 on the FK_LR_PARENT_RUN self-referencing foreign key (RUN_ID was only part of composite PK, not independently unique at CREATE TABLE time).
- **LOOP_ITERATIONS** — Changed partitioning from PARTITION BY REFERENCE (FK_LI_RUN) to PARTITION BY RANGE (STARTED_AT). The parent table LOOP_RUNS uses composite LIST+RANGE subpartitioning which is incompatible with reference partitioning for child tables (ORA-14661).

### 2. Hardcoded Schema Owner (All Editions)

- **4_grants.sql** — Replaced all literal AIADMIN with ``DEFINE SCHEMA_OWNER`` substitution variable. Schema owner can now be customized at deployment time.
- **6_deep_sec_policy.sql** — Same treatment; all AIADMIN references replaced with ``&&SCHEMA_OWNER``.
- **connection.py** — `ALTER SESSION SET CURRENT_SCHEMA` and `SET_AGENT_CONTEXT` calls now read schema name from config.database.user instead of hardcoded AIADMIN.
- **PG 1_schema.sql** — Replaced hardcoded `'aiadmin'` in RLS policies with psql variable ``:'schema_owner'``.
- **PG agent_bootstrap.py** — Changed `SET search_path TO aiadmin` to `SET search_path TO public`.

### 3. Configuration Priority (All Editions)

- **config.py** — Changed priority from "Environment Variables > config.json > Defaults" to "config.json (encrypted) > Environment Variables > Defaults". Encrypted local config now takes precedence over environment variables.
- Removed hardcoded default credentials (openclaw/hermes/10.10.10.130) from DatabaseConfig defaults.
- EmbeddingConfig defaults changed to empty strings, forcing explicit configuration.
- SecurityConfig.pbkdf2_iterations default corrected from 100000 to 210000.

### 4. Embedding Model Configuration (All Editions)

- **embedding_api.py** — When embedding model is not configured, raises ValueError with list of supported models instead of silently auto-detecting from environment.
- **server.py** — Added embedding configuration check on startup; prints WARNING if embedding model is not configured.

---

## Upgrade Notes

### Fresh Deployment

1. Edit `config.json` with your database credentials (supports encrypted storage via connection_crypto.py)
2. Configure `embedding.api_url` and `embedding.model` (see supported models in embedding_api.py)
3. Deploy schema: `1_schema.sql → 2_api.sql → 3_jobs.sql → 4_harness_templates.sql`
4. Oracle only: Deploy `4_grants.sql` (adjust `DEFINE SCHEMA_OWNER` if not using default AIADMIN) and `6_deep_sec_policy.sql`

### Upgrading from v3.7.2

- No database migration required
- Replace code files (config.py, connection.py, embedding_api.py, server.py)
- Replace deploy scripts (1_schema.sql, 4_grants.sql, 6_deep_sec_policy.sql)
- Oracle only: Re-run 4_grants.sql if schema owner is not AIADMIN
