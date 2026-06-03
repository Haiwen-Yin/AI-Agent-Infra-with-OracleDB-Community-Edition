# Release Notes — v3.1.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-02

License: Apache License 2.0

---

## Overview

v3.1.0 introduces **database-native encryption** via the `DB_CRYPTO` PL/SQL package, which uses Oracle `DBMS_CRYPTO` (AES-256-CBC) for all in-database encryption. This replaces the previous approach of encrypting database-stored data (LDAP bind credentials, agent credentials) with Python-side `encrypt_section()`/`decrypt_section()` that depended on a local `master.key` file. With `DB_CRYPTO`, encryption keys are stored in the `SYSTEM_CONFIG` table and fully managed by the database — making encrypted data portable across server migrations and automatically shared among all agents connecting to the same database.

---

## New Features

### 1. DB_CRYPTO PL/SQL Package

A new PL/SQL package `DB_CRYPTO` provides AES-256-CBC encryption/decryption using Oracle's native `DBMS_CRYPTO`:

| Function | Description |
|----------|-------------|
| `encrypt(p_plaintext)` | Encrypts VARCHAR2 → hex-encoded ciphertext |
| `decrypt(p_ciphertext)` | Decrypts hex-encoded ciphertext → VARCHAR2 |
| `encrypt_raw(p_plaintext)` | Encrypts RAW → RAW |
| `decrypt_raw(p_ciphertext)` | Decrypts RAW → RAW |
| `rotate_key()` | Generates new encryption key |

**Key management:**
- Keys auto-generated on first use and stored in `SYSTEM_CONFIG` (`db_crypto_master_key`, `db_crypto_key_salt`)
- Concurrent-safe: `DUP_VAL_ON_INDEX` exception handler prevents key overwrite on parallel first-use
- No dependency on local filesystem — fully self-contained within the database

### 2. Dual-Track Encryption Architecture

| Data | Encryption Track | Key Location | Shared Across Agents? |
|------|-----------------|--------------|---------------------|
| `config.json` DB credentials | `connection_crypto.py` (AES-256-GCM) | `~/.oracle-infra/master.key` or `MASTER_DB_KEY` env | No (per-server) |
| LDAP `BIND_CREDENTIAL` | `DB_CRYPTO` (DBMS_CRYPTO AES-256-CBC) | `SYSTEM_CONFIG` table | **Yes** |
| `AGENT_CREDENTIALS.CREDENTIAL_VALUE` | `DB_CRYPTO` (DBMS_CRYPTO AES-256-CBC) | `SYSTEM_CONFIG` table | **Yes** |
| `SYSTEM_USERS` password | PBKDF2-HMAC-SHA256 (one-way hash) | Salt in row | N/A (verify only) |

### 3. Data Isolation Model

Three-layer isolation ensures proper data separation between agents:

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Physical | `ENTITY_TYPE` LIST partitioning | Type isolation, partition pruning |
| Access | `VISIBILITY` (PRIVATE/SHARED/PUBLIC) + `OWNED_BY_AGENT` | Cross-agent visibility control |
| Workspace | `WORKSPACE_ID` + `OWNER_USER_ID` | User-level isolation |

Visibility query pattern: `WHERE VISIBILITY='SHARED' OR VISIBILITY='PUBLIC' OR OWNED_BY_AGENT=:agent`

---

## Changes

- `ldap_auth_api.py` — Uses `DB_CRYPTO.encrypt/decrypt` instead of `connection_crypto.encrypt_section/decrypt_section` for `BIND_CREDENTIAL`
- `agent_api.py` — Uses `DB_CRYPTO.encrypt/decrypt` instead of Python-side encryption for `CREDENTIAL_VALUE`
- `2_api.sql` — Added `DB_CRYPTO` PL/SQL package definition (concurrent-safe `get_db_key()` with `DUP_VAL_ON_INDEX` handler)
- Deployment prerequisite: `GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <db_user>`
- `server.py` — SHA256 password comparison now case-insensitive (`actual.upper() == expected.upper()`) to handle DB hex case differences
- `introduction_zh_v3.0.0.md` → `introduction_zh_v3.1.0.md` — renamed to match version
- Removed `skill_token_api.py` (Enterprise-only one-time token flow)
- Removed audit/LDAP/skill-token routes from `server.py` (`/api/audit`, `/audit`, `/api/skill/dl/`, `/api/skill/token/`, `request-access` action)
- Removed `context_audit_log` query and `audit_open_count` from `_api_stats()`
- Removed LDAP auth mode from `portal_login.html` (no `authMode`, `switchAuthMode()`, LDAP dropdown)
- Removed `requestAccess()` from `skills.html`, added `directDownload()` for direct resource download

---

## Security Impact

**Before v3.1.0**: Database encrypted data depended on local `~/.oracle-infra/master.key`. If the file was lost (server migration, disk failure), all encrypted data in the database became unrecoverable. Multi-instance deployments required key file synchronization.

**After v3.1.0**: All database-side encryption uses `DBMS_CRYPTO` with keys stored in `SYSTEM_CONFIG`. Fully self-contained within the database. Portable across migrations. Automatically shared among all agents connecting to the same database.

**Note**: `config.json` encryption (`connection_crypto.py`) remains unchanged — this is for local file encryption only, which correctly depends on the local master key since the file itself is local.

---

## Upgrade from v3.0.0

1. Grant DBMS_CRYPTO:
   ```sql
   -- As SYSDBA:
   GRANT EXECUTE ON SYS.DBMS_CRYPTO TO <db_user>;
   ```
2. Deploy the new API package:
   ```bash
   sql user/password@//host:port/service @scripts/deploy/2_api.sql
   ```
3. Re-encrypt existing data (if any was encrypted with the old Python-side method):
   - LDAP `BIND_CREDENTIAL`: Decrypt with old method, re-encrypt with `DB_CRYPTO.encrypt()`
   - `AGENT_CREDENTIALS.CREDENTIAL_VALUE`: Decrypt with old method, re-encrypt with `DB_CRYPTO.encrypt()`

---

## System Requirements

- Oracle Database 23ai+ (tested on 26ai)
- `GRANT EXECUTE ON SYS.DBMS_CRYPTO` (new prerequisite)
- Python 3.8+ with `oracledb` package
- SQLcl 26.1+ (for SQL script deployment)
