# Security - Oracle Memory System v2.0.0

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
| COLLABORATIVE | Owner + agents in ACCESSIBLE_TO JSON array |

## Access Auditing

All entity access is logged to ENTITY_ACCESS_LOG:
- Agent ID, Entity ID, Access Type (READ/WRITE/DELETE/SHARE/SEARCH), Timestamp

Permission changes logged to AGENT_PERMISSION_LOG:
- Agent ID, Old Status, New Status, Change Reason, Timestamp
