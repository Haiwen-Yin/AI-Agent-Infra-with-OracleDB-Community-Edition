# Security - AI Agent Infra v3.10.2 (2026-07-16) - Enterprise Edition

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

## Deep Data Security (v3.7.0)

v3.7.0 replaces VPD with Oracle Deep Data Security:

- **23 Data Grants** enforce row-level, column-level, and cell-level access control (including `collab_member_own` for COLLAB_GROUP_MEMBERS and `collab_group_member_access` for COLLAB_GROUPS)

### 23 Data Grants Summary

| Table | Privilege | Predicate | Role |
|-------|-----------|-----------|------|
| AGENT_REGISTRY | SELECT | 1=1 | admin_data_role |
| AGENT_REGISTRY | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | SELECT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC' | agent_data_role |
| ENTITIES | INSERT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | UPDATE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | DELETE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_EDGES | SELECT | SOURCE_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| KNOWLEDGE_META | SELECT | ENTITY_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC') | agent_data_role |
| WORKSPACES | SELECT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACES | INSERT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACE_CONTEXT | SELECT | WORKSPACE_ID IN (SELECT WORKSPACE_ID FROM WORKSPACES WHERE OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID')) | agent_data_role |
| AGENT_SESSION | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| AGENT_SESSION | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_STEPS | SELECT | PLAN_ID IN (SELECT PLAN_ID FROM TASK_PLANS WHERE AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| ENTITY_ACCESS_LOG | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_ACCESS_LOG | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| SYSTEM_CONFIG | SELECT | 1=0 | agent_data_role |
| TAGS | SELECT | 1=1 | agent_data_role |

### MAC Enforcement

MAC (Mandatory Access Control) is enforced on 7 critical tables, preventing predicate bypass even by schema owners:

1. ENTITIES
2. ENTITY_EDGES
3. KNOWLEDGE_META
4. WORKSPACES
5. WORKSPACE_CONTEXT
6. AGENT_SESSION
7. TASK_PLANS

### End User Lifecycle

Agent registration automatically creates a Deep Sec End User:

1. `register_agent()` calls `_ensure_end_user(agent_id)`
2. `_ensure_end_user()` calls `END_USER_MANAGER.create_end_user(agent_id)`
3. End User is created with name `UPPER(REPLACE(agent_id, '-', '_'))`
4. `agent_data_role` is granted to the End User
5. `DEEP_SEC_SESSION_ROLE` is granted via the Data Role (enables CREATE SESSION)

On decommission, `END_USER_MANAGER.drop_end_user(agent_id)` removes the End User.

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

### Per-Request Context Switching

Each request sets agent identity for Data Grant predicates:

1. Application receives request with agent context
2. `set_agent_context(agent_id)` sets `END_USER_CTX` namespace with AGENT_ID, USER_ID
3. Data Grant predicates reference `SYS_CONTEXT('END_USER_CTX', 'AGENT_ID')` for filtering
4. After request completes, `clear_agent_context()` clears the context

**Portal API Context Switching**: Portal APIs that access WORKSPACES or SYSTEM_USERS tables temporarily use `connection.set_agent_context(None)` to switch to the AIADMIN connection, because WORKSPACES.CURRENT_AGENT_ID is NULL for most workspaces, causing Data Grant predicates to reject all rows for End Users. After the operation completes, the End User context is restored.

### Verification Data

Testing with AGENT_001 End User confirms Data Grant filtering:

| Table | Total Rows | AGENT_001 Visible | Notes |
|-------|-----------|-------------------|-------|
| AGENT_REGISTRY | 14 | 1 | Only own agent row visible |
| ENTITIES | 210 | 40 | Own entities + PUBLIC entities |
| SYSTEM_CONFIG | 1 | 0 | Blocked by `1=0` predicate |


## Per-Agent Encryption Keys (v3.10.2)

**Added 2026-07-16** — Each Business Agent receives its own independent 256-bit encryption key at registration time.

### Architecture

- **Key Storage**:  table, key = 
- **Key Distribution**: Encrypted with admin_token as key material via 
- **Key Version**: Tracked via  for rotation detection
- **Key Rotation**:  (global) and  (per-Agent)

### Config.json Auto-Encryption

On server startup,  transparently encrypts:

-  section: user, password, DSN
-  section: api_key
-  section: simple_api_key, standard_api_key, complex_api_key

Uses PBKDF2-HMAC-SHA512 key derivation with 210,000 iterations, AES-like stream cipher with HMAC authentication. Master key stored in  (chmod 600).

### CLI Tool



### Per-Agent Key Lifecycle

1. **Registration**: Agent receives its crypto key encrypted with admin_token
2. **Storage**: Key stored in SYSTEM_CONFIG (not in agent config files)
3. **Usage**: Agent uses key to encrypt/decrypt local config and session data
4. **Rotation**: Admin triggers rotation via API, affected credentials re-encrypted
5. **Detection**: Agent heartbeat checks key version, triggers local re-encryption on change
