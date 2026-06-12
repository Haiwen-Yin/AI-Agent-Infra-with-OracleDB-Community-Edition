# Security - AI Agent Infra v3.5.0 (2026-06-11) - Community Edition

## Data Masking

`DataMaskingService` automatically detects and masks sensitive data:

| Pattern | Example Input | Masked Output |
|---------|--------------|---------------|
| email | user@example.com | ****@example.com |
| phone | 555-123-4567 | 555***-4567 |
| credit_card | 4111111111111111 | ****-****-****-1111 |
| ssn | 123-45-6789 | ***-**-6789 |
| api_key | secretAbcDefGhi... | secr...Ghi |
| ip_address | 192.168.1.1 | ***.***.***.1 |
| jwt_token | eyJhbG... | eyJ...+last16 |

### Context-Aware Masking

| Context | Patterns Masked |
|---------|----------------|
| LOGGING | email, phone, credit_card, ssn, api_key, jwt_token |
| DEBUGGING | All LOGGING + ip_address |
| ANALYTICS | credit_card, ssn, api_key, jwt_token |
| SHARING | All LOGGING + ip_address |

```python
from scripts.lib.security import DataMaskingService
svc = DataMaskingService("SHARING")
safe_text = svc.mask_text("admin@company.com called from 10.0.0.1")
safe_dict = svc.mask_dict({"password": "secret", "name": "John"})
```

## Reversible Encryption

AES-like XOR encryption with PBKDF2 key derivation for storing sensitive values that need later retrieval.

```python
from scripts.lib.security import ReversibleEncryption
enc = ReversibleEncryption()
ciphertext = enc.encrypt("sensitive data")
plaintext = enc.decrypt(ciphertext)

# Key rotation
new_key = os.urandom(32)
rotated = enc.rotate_key(new_key, [ciphertext1, ciphertext2])
```

## Password Hashing

PBKDF2-HMAC-SHA256 with configurable iterations (default: 100,000).

```python
from scripts.lib.security import hash_password, verify_password
hash_val, salt = hash_password("MyPassword123!")
is_valid = verify_password("MyPassword123!", hash_val, salt)
```

## Entity Visibility

| Level | Access |
|-------|--------|
| PRIVATE | Only OWNED_BY_AGENT |
| SHARED | All registered agents |
| PUBLIC | Unrestricted (v2.1 replaces v2.0 COLLABORATIVE) |

Cross-agent sharing is managed via the AGENT_COLLABORATION table, which tracks source/target agents, collaboration type, associated entity, context, and strength.

## Access Auditing

All entity access is logged to ENTITY_ACCESS_LOG (RANGE+HASH partitioned by ACCESS_TIME and AGENT_ID):
- LOG_ID (VARCHAR2(64)), Entity ID, Agent ID, Access Type (READ/WRITE/DELETE/SEARCH/EMBED), Access Time, Session ID, Context

## Permission Auditing

Permission changes logged to AGENT_PERMISSION_LOG:
- LOG_ID (VARCHAR2(64)), Agent ID, Granted By, Permission, Resource Type, Resource ID, Action (GRANT/REVOKE/DENY), Timestamp

## Agent Collaboration

AGENT_COLLABORATION tracks cross-agent sharing requests:
- COL_ID (VARCHAR2(64)), Source Agent ID, Target Agent ID, Collaboration Type, Entity ID, Context (JSON), Strength (0-1), Created/Updated timestamps
- Foreign keys to AGENT_REGISTRY and ENTITIES

## PL/SQL Security Functions

`AGENT_PERMISSION_MANAGER.check_entity_access(agent_id, entity_id)`:
- Returns 'GRANTED' if entity is SHARED/PUBLIC or owner matches
- Returns 'DENIED' for PRIVATE entities not owned by the requesting agent

## Deep Data Security (v3.5.0)

v3.5.0 replaces VPD with Oracle Deep Data Security:

- **22 Data Grants** enforce row-level, column-level, and cell-level access control (including `collab_member_own` for COLLAB_GROUP_MEMBERS and `collab_group_member_access` for COLLAB_GROUPS)
- **MAC** on 7 tables prevents view-based bypass of row-level policies
- **End User Context** with `o:onFirstRead` callback for zero-trust agent identification
- **3 Data Roles**: `admin_data_role` (full), `agent_data_role` (filtered by agent), `pool_agent_data_role` (minimum)
- **Per-agent End Users** with Direct Logon — Data Grants auto-filter via `ORA_END_USER_CONTEXT.username`
- **SYSTEM_CONFIG** fully restricted to `admin_data_role` only

**Portal API Context Switching**: Portal APIs that access WORKSPACES or SYSTEM_USERS tables temporarily use `connection.set_agent_context(None)` to switch to the AIADMIN connection, because WORKSPACES.CURRENT_AGENT_ID is NULL for most workspaces, causing Data Grant predicates to reject all rows for End Users. After the operation completes, the End User context is restored.

### WORKSPACE_CONTEXT VISIBILITY

WORKSPACE_CONTEXT has a VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED) that controls cross-agent context visibility in collaboration group workspaces:

| VISIBILITY | Agent sees own context? | Other agents in collab group see it? |
|------------|------------------------|--------------------------------------|
| PRIVATE | Yes (always) | No — blocked by Data Grant predicate |
| SHARED | Yes (always) | Yes — visible to collab group members |
| PUBLIC | Yes (always) | Yes — visible to all |

The `WS_CTX_AGENT_ACCESS` Data Grant predicate enforces these rules:
- Agent always sees its own context (AGENT_ID matches own End User) regardless of VISIBILITY
- Agent sees other agents' SHARED/PUBLIC context only in collab group workspaces (via COLLAB_GROUPS + COLLAB_GROUP_MEMBERS subquery)
- Agent CANNOT see other agents' PRIVATE context even in the same collab group workspace

This prevents one agent's private thoughts, internal reasoning, or sensitive intermediate results from being exposed to other agents sharing the same workspace.
