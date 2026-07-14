# Release Notes - v3.10.1 (2026-07-14)

## Overview

**v3.10.1** is an enterprise deployment enhancement release. Adds offline dependency bundling (vendor/ directory with 30 Python wheels), pure Python Oracle schema deployment tool (deploy_oracle.py - replaces SQLcl/Java dependency), and dependency verification script.

## New Features

### Offline Deployment Support

- **vendor/ directory**: 30 pre-downloaded Python wheels (cp314, manylinux x86_64) bundled in each edition
- **requirements.txt**: Locked dependency versions per edition (Oracle: oracledb + MCP deps; PG: psycopg2-binary + MCP deps)
- **install_offline.sh**: One-command offline installation: `pip install --no-index --find-links vendor/ -r requirements.txt`
- **verify_deps.py**: Verifies vendor/ wheels match requirements.txt with version and platform compatibility checks

### Pure Python Oracle Deployment (deploy_oracle.py)

- **Replaces SQLcl** (125MB + Java dependency) with a 200-line Python script using oracledb driver
- Handles SQLcl-specific syntax: PROMPT removal, DEFINE/&& variable substitution, / block terminator, PL/SQL block detection
- Usage: `python3.14 deploy_oracle.py <user> <password> <dsn> <sql_file> [sql_file...]`
- Tested: 100% success on 2_api.sql, 3_jobs.sql, 4_harness_templates.sql, 6_deep_sec_policy.sql
- Expected "already exists" errors on re-deployment (same as SQLcl behavior)

## Files Added

- `requirements.txt` - Locked Python dependencies (per edition)
- `vendor/` - 30 Python wheel files (~12MB Oracle, ~14MB PG)
- `scripts/install_offline.sh` - Offline dependency installer
- `scripts/verify_deps.py` - Dependency verification tool
- `scripts/deploy_oracle.py` - Pure Python Oracle schema deployer (Oracle editions only)

## Enterprise Air-Gapped Deployment

1. Copy the edition ZIP to the isolated network
2. Extract and run: `bash scripts/install_offline.sh`
3. Verify: `python3.14 scripts/verify_deps.py`
4. Deploy Oracle schema: `python3.14 scripts/deploy_oracle.py <user> <pass> <dsn> scripts/deploy/1_schema.sql scripts/deploy/2_api.sql scripts/deploy/3_jobs.sql scripts/deploy/4_harness_templates.sql`
5. Configure `config.json` with local Embedding/LLM API endpoints
6. Start server: `python3.14 scripts/visualization/server.py`

No internet connection, SQLcl, or Java required.

## Upgrade Notes

- No schema changes from v3.10.0
- No API changes
- No data migration required
- Replace `vendor/` directory if updating from a custom build
