# Release Notes - v3.10.2 (2026-07-16)

## Overview

**v3.10.2** is an enterprise encryption enhancement release. Introduces per-Agent independent crypto keys with DB storage, config.json auto-encryption on startup (database + LLM + model_routing), key rotation API, and Portal Markdown rendering.

## New Features

### Per-Agent Independent Crypto Keys

- Each Business Agent receives its own 256-bit encryption key at registration time
- Key stored in SYSTEM_CONFIG table (key = `agent_crypto_key:{agent_id}`)
- Distributed via admin_token-authenticated channel using `encrypt_credential_for_distribution()`
- Key version tracking via `agent_crypto_key_version:{agent_id}` for rotation detection

### Config.json Auto-Encryption on Startup

- `server.py` now calls `auto_encrypt_config()` on startup
- Encrypts `database` section (user, password, dsn)
- Encrypts `llm.api_key`
- Encrypts `model_routing.*_api_key` (simple/standard/complex)
- PBKDF2-HMAC-SHA512 key derivation + authenticated encryption with HMAC
- Master key stored in `~/.oracle-infra/master.key` (chmod 600)

### Key Rotation API

- `POST /api/admin/crypto/rotate` — rotate keys for ALL active Agents
- `POST /api/admin/crypto/rotate/{agent_id}` — rotate key for a single Agent
- Automatic re-encryption of affected credentials with new key
- Agent heartbeat detects version change and triggers local re-encryption

### encrypt_config.py CLI Tool

- Unified across all 4 editions (was Oracle ENT only)
- Commands: `encrypt`, `decrypt`, `rotate`, `verify`, `auto`
- Usage: `python3.14 -m tools.encrypt_config <command> [--config PATH]`

### Portal Chat Enhancements

- Markdown rendering for LLM responses (headers, code blocks, lists, bold/italic, links)
- Auto-scroll during streaming output
- Exit button clears session cookie and redirects to login
- Auto-detection of expired sessions

## Bug Fixes

### Critical: PG Credential Encryption

- **`_get_crypto_key()` in `agent_api.py`**: Was returning `os.urandom(32)` on every call — different key each time, making encryption irreversible. Now reads `credential_encryption_key` from `system_config` table.
- **`_get_encryption_key()` in `security.py`**: Same random-key bug, now reads from DB.
- **`_convert_params()` empty tuple bug**: Returning `()` on no params caused psycopg2 to parse LIKE patterns as placeholders, crashing with `IndexError: tuple index out of range`. Changed to return `None`.

### PG Business Agent Mode

- `connection.py` now supports `mode='agent'` with encrypted `agent_config.json` loading
- Added `_load_agent_eu_creds()` and `_get_agent_mode_connection()` functions

### PG Oracle SQL Syntax Fixes

- `FETCH FIRST 1 ROWS ONLY` → `LIMIT 1` (3 occurrences in `server.py`)
- `SYSTIMESTAMP` → `CURRENT_TIMESTAMP` (2 occurrences)
- These caused silent failures in portal login workspace creation

## Template Fixes

- **Monitor sticky thead**: Changed to `position:sticky` on `<thead>` with solid `#0f3460` background, removed `overflow:hidden` from `.content-area`
- **Memory filter**: Removed filter badge complexity, restored original `<select>` dropdown with `filterByCategory()` → `applyFilter()` fix for list+graph view consistency
- **Branches filter**: Added status filter bar with Active/Draft/Archived badges
- **Approvals loading**: Fixed `loading-overlay` initially hidden, removed stale `filterType` references
- **Filter badge border**: Thickened from 1px to 2px with box-shadow glow on active state
- **Filter badges**: Converted `<select>` dropdowns to badge pills on tasks/approvals/memory pages

## Files Changed

- `scripts/lib/connection_crypto.py` — Per-Agent key functions, expanded auto-encrypt, CLI tool
- `scripts/lib/config.py` — LLM/model_routing decryption in load_config()
- `scripts/lib/agent_api.py` — Key generation, storage, rotation functions
- `scripts/lib/connection.py` (PG) — Agent mode, empty tuple fix
- `scripts/lib/security.py` (PG) — _get_encryption_key() fix
- `scripts/visualization/server.py` — auto_encrypt_config(), crypto rotation endpoints
- `scripts/tools/encrypt_config.py` — Unified CLI tool (all editions)
- `scripts/visualization/templates/portal_chat.html` — Markdown, scroll, exit, session
- `scripts/visualization/templates/monitor.html` — Sticky thead fix
- `scripts/visualization/templates/memory.html` — Filter restoration
- `scripts/visualization/templates/branches.html` — Filter bar addition
- `scripts/visualization/templates/approvals.html` — Loading fix, filterType removal

## Upgrade Notes

- No schema changes from v3.10.1
- No data migration required
- After upgrading, run `python3.14 scripts/verify_deps.py` to verify dependencies
- config.json will be auto-encrypted on first server startup
- Existing agents will have crypto keys generated on next heartbeat