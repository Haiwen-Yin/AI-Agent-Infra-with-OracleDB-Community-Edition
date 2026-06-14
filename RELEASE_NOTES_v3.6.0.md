# Release Notes — v3.6.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-13

License: Apache License 2.0

---

## Overview

v3.6.0 introduces the Admin/Agent Separation Architecture, enabling Admin Agent and Business Agent to run as independent processes with different privilege levels. Admin Agent runs the Web Portal and holds AIADMIN credentials; Business Agent runs as an independent process with only End User credentials, eliminating the need for AIADMIN access on every Agent node.

---

## Admin/Agent Separation Architecture

### Problem

In previous versions, every Agent process required AIADMIN database credentials (stored in `config.json`) to operate. This meant:
- Every Agent node had full schema owner access to the database
- A compromised Agent could bypass all Data Grant security
- Credential rotation required updating every Agent node

### Solution

v3.6.0 introduces a mode system that separates concerns:

| Mode | Process | DB Credentials | Web Portal | Use Case |
|------|---------|---------------|------------|----------|
| `standalone` | Single process | AIADMIN + End User | Yes | Development, single-node |
| `admin` | Admin Agent | AIADMIN + End User | Yes | Production Admin node |
| `agent` | Business Agent | End User only | No | Production Business Agent |

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Admin Agent                           │
│  Mode: admin                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Web Portal  │  │  AIADMIN     │  │  Admin Token │  │
│  │  (server.py) │  │  Connection  │  │  Generator   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         │                                    │          │
│         │           admin_token               │          │
│         │    ┌──────────────────────┐         │          │
│         │    │  Encrypted Credential │         │          │
│         │    │  Distribution         │         │          │
│         │    └──────────────────────┘         │          │
│         │                                    │          │
└─────────│────────────────────────────────────│──────────┘
          │                                    │
          ▼                                    ▼
┌─────────────────────────────────────────────────────────┐
│                   Business Agent                         │
│  Mode: agent                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Agent       │  │  End User    │  │  agent_      │  │
│  │  Bootstrap   │  │  Connections │  │  config.json │  │
│  │  CLI         │  │  (Deep Sec)  │  │  (encrypted) │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│  ✗ No AIADMIN credentials                              │
│  ✗ No Web Portal                                       │
│  ✓ End User connections only (Data Grant enforced)      │
└─────────────────────────────────────────────────────────┘
```

### Security Benefits

| Aspect | Before v3.6.0 | After v3.6.0 |
|--------|--------------|--------------|
| AIADMIN credentials | On every Agent node | Only on Admin Agent |
| Compromised Business Agent | Full schema owner access | End User access only (Data Grant filtered) |
| Credential rotation | Update every node | Rotate admin_token; Business Agents re-register |
| Blast radius | Entire database | Single Agent's data scope |

---

## New Features

### 1. Admin Token Authentication

| Function | Description |
|----------|-------------|
| `generate_admin_token()` | Generate a time-limited admin registration token; stored in `SYSTEM_CONFIG` as `admin.registration_token` |
| `verify_admin_token(token)` | Verify a registration token; returns True if valid and not expired |

**Token properties:**
- Token format: `AT_` + 32 hex characters (e.g., `AT_a1b2c3d4e5f6...`)
- Persistent token, stored DB_CRYPTO encrypted in `SYSTEM_CONFIG`
- Verified via constant-time comparison (`secrets.compare_digest`)
- Rotatable via `POST /api/admin/token/rotate`

### 2. Encrypted Credential Distribution

| Function | Description |
|----------|-------------|
| `encrypt_credential_for_distribution(credential, admin_token)` | Encrypt an End User credential using PBKDF2-HMAC-SHA512 with admin_token as key material |
| `decrypt_credential_from_distribution(encrypted_credential, admin_token)` | Decrypt a distributed credential using admin_token as key material |

**Encryption parameters:**
- Key derivation: PBKDF2-HMAC-SHA512, 210,000 iterations
- Salt: 16 bytes, randomly generated per encryption
- Algorithm: AES-256-GCM (authenticated encryption)
- Key material: admin_token (not stored, only in transit)

### 3. Agent Bootstrap CLI

```bash
python agent_bootstrap.py --admin-url http://admin-host:18080 \
                          --admin-token <token> \
                          --agent-name "my-agent" \
                          --output-dir /path/to/agent
```

**Steps:**
1. Verify admin_token with Admin Agent
2. Register Business Agent with Admin Agent
3. Receive encrypted End User credentials
4. Decrypt using admin_token as key material
5. Save to encrypted `agent_config.json`

### 4. Agent Config Encryption

| Function | Description |
|----------|-------------|
| `save_agent_config(config, admin_token, path)` | Encrypt and save End User credentials to `agent_config.json` |
| `load_agent_config(admin_token, path)` | Load and decrypt `agent_config.json` |

**Config file structure (encrypted at rest):**
```json
{
  "mode": "agent",
  "agent_id": "AGENT_XXX",
  "end_user": {
    "username": "AGENT_XXX",
    "password": "<encrypted>",
    "dsn": "<encrypted>"
  },
  "schema": "AIADMIN",
  "_encrypted": true,
  "_salt": "<base64>",
  "_nonce": "<base64>"
}
```

### 5. Mode-Aware connection.py

| Mode | AIADMIN Pool | End User Pool | agent_config.json |
|------|-------------|---------------|-------------------|
| standalone | Yes | Yes | No |
| admin | Yes | Yes | No |
| agent | No | Yes (from config) | Yes |

**Agent mode connection flow:**
1. `load_agent_config()` decrypts local `agent_config.json`
2. `get_connection()` returns End User connection directly
3. No AIADMIN pool initialized — zero schema owner exposure
4. `set_agent_context()` is a no-op (always End User)

### 6. Admin API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/agent/register` | POST | Register a Business Agent with admin token; returns encrypted End User credentials + 8 recovery codes |
| `/api/admin/agent/recover` | POST | Recover agent with one-time recovery code; resets End User password to prevent dual-active |
| `/api/admin/token/generate` | POST | Generate a new admin registration token (requires AIADMIN session) |
| `/api/admin/token/rotate` | POST | Rotate the admin token; existing Business Agents must re-register |
| `/api/admin/skill/list` | GET | List available skills (admin_token + optional agent_id/visibility filters) |
| `/api/admin/skill/{id}/acquire` | GET | Acquire skill content (admin_token, optional resource=1 for ZIP) |
| `/api/admin/skill/create` | POST | Create new skill (admin_token + metadata) |
| `/api/admin/skill/update` | POST | Update skill metadata (admin_token + skill_id + fields) |
| `/api/admin/skill/delete` | POST | Delete skill (admin_token + skill_id) |
| `/api/admin/skill/upload` | POST | Upload resource file (admin_token + skill_id + base64 content) |

**Registration request:**
```json
{
  "admin_token": "<token>",
  "agent_name": "my-business-agent",
  "capabilities": {"type": "research", "skills": ["search", "memory"]}
}
```

**Registration response:**
```json
{
  "agent_id": "AGENT_XXX",
  "end_user": {
    "credential_encrypted": "<base64-encrypted-blob>",
    "salt": "<pbkdf2-salt>"
  },
  "recovery_codes": ["RC-XXXX-XXXX-XXXX", "... (8 codes)"]
}
```

### 7. Recovery Codes

Agent registration returns 8 one-time recovery codes (`RC-XXXX-XXXX-XXXX` format):
- SHA-256 hashed, DB_CRYPTO encrypted in `SYSTEM_CONFIG` (`recovery_codes.{agent_id}`)
- One-time use — consumed on verification via `verify_recovery_code()`
- **Save securely — shown only once during registration**

### 8. Agent Recovery

`POST /api/admin/agent/recover` enables re-registering an agent when the original process/host is lost:
1. Verify admin_token + recovery_code
2. Check LAST_SEEN_AT (5-minute window — reject if agent may still be active)
3. **Reset End User password** — old password invalidated immediately
4. Return new encrypted credentials

**Dual-active prevention**: Old process cannot reconnect (password changed). Functionally dead even if still running.

### 9. Private Skill Backup

Skills with `visibility=PRIVATE` + `owned_by_agent=agent_id` are only visible to the owning agent:
- Data Grant predicate enforces isolation at DB level
- Admin Skill API `list` endpoint supports `agent_id` + `visibility` filters
- Business Agent can safely backup sensitive skills to the platform

### 10. Skill Distribution & Management via Admin API

Business Agents manage skills entirely through Admin API — no direct SKILL_META table access needed:
- **Distribution**: `GET /api/admin/skill/list`, `GET /api/admin/skill/{id}/acquire`
- **Management**: `POST /api/admin/skill/create`, `update`, `delete`, `upload`
- All endpoints require `admin_token` authentication

### 11. Graph Node Highlight

Clicking a node in the Knowledge, Memory, or Graph Explorer pages highlights all connected nodes and edges; non-connected elements are dimmed. Clicking blank area resets the view.

---

## Schema Changes

### SYSTEM_CONFIG Seeds

| Key | Value | Description |
|-----|-------|-------------|
| `admin.registration_token` | `<auto-generated>` | Admin token for Business Agent registration |
| `schema_version` | `3.6.0` | Updated from 3.5.0 |

---

## Deployment

### Fresh Deployment

No special steps needed — deploy as usual. `1_schema.sql` now includes `admin.registration_token` seed.

### Migration from v3.5.0

```sql
-- Step 1: Add admin.registration_token seed
INSERT INTO SYSTEM_CONFIG (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION)
VALUES ('admin.registration_token', '<generated-token>', 'Admin token for Business Agent registration');

-- Step 2: Update schema version
UPDATE SYSTEM_CONFIG SET CONFIG_VALUE = '3.6.0' WHERE CONFIG_KEY = 'schema_version';
COMMIT;
```

### Setting Up Admin/Agent Separation

**Admin Agent node:**
```bash
# config.json
{
  "mode": "admin",
  "database": {"user": "aiadmin", "password": "...", "dsn": "//db:1521/service"},
  "server": {"host": "0.0.0.0", "port": 18080}
}

# Generate admin token
curl -X POST http://localhost:18080/api/admin/token/generate \
  -H "Cookie: session=<admin-session>"
```

**Business Agent node:**
```bash
# Bootstrap the agent
python agent_bootstrap.py --admin-url http://admin-host:18080 \
                          --admin-token <token> \
                          --agent-name "business-agent-1" \
                          --output-dir /opt/agent

# Start agent (no Web Portal, no AIADMIN credentials)
python -m scripts.lib.agent_runner --config /opt/agent/agent_config.json
```

---

## Backward Compatibility

- `standalone` mode (default) preserves existing behavior exactly
- No breaking changes to existing APIs
- `admin.registration_token` is optional for standalone mode
- Existing `config.json` files work without modification (mode defaults to `standalone`)

---

## System Requirements

Unchanged from v3.5.0:
- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+
