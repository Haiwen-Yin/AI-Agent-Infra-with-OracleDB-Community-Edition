# Database Authentication Quick Reference

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-12  
**Version**: v1.0.0

---

## Overview

Oracle Memory System v1.0.0 uses Oracle Database tables for authentication instead of JSON files. This provides enterprise-grade security with RBAC, session management, and audit logging.

## Database Schema

### Core Tables



-- User accounts
VIZ_USERS (
    USER_ID       NUMBER PRIMARY KEY,
    USERNAME       VARCHAR2(50) UNIQUE NOT NULL,
    PASSWORD_HASH  VARCHAR2(200) NOT NULL,  -- salt:hash format
    ROLE           VARCHARra2(20) DEFAULT 'viewer',
    ENABLED        CHAR(1) DEFAULT 'Y',
    CREATED_AT     TIMESTAMP DEFAULT SYSTIMESTAMP
)

-- Active sessions
VIZ_SESSIONS (
    SESSION_ID     VARCHAR2(100) PRIMARY KEY,
    USER_ID        NUMBER REFERENCES VIZ_USERS(USER_ID),
    CREATED_AT     TIMESTAMP DEFAULT SYSTIMESTAMP,
    EXPIRES_AT     TIMESTAMP
)

-- Access audit logs
VIZ_ACCESS_LOGS (
    LOG_ID         NUMBER PRIMARY KEY,
    USER_ID        NUMBER REFERENCES VIZ_USERS(USER_ID),
    ACTION         VARCHAR2(50),
    IP_ADDRESS     VARCHAR2(50),
    SUCCESS        CHAR(1),
    ACCESS_TIME    TIMESTAMP DEFAULT SYSTIMESTAMP
)

-- System configuration
VIZ_CONFIG (
    KEY            VARCHAR2(50) PRIMARY KEY,
    VALUE          CLOB
)

-- RBAC permissions
VIZIZ_PERMISSIONS (
    ROLE           VARCHAR2(20),
    PERMISSION     VARCHAR2(50),
    PRIMARY KEY (ROLE, PERMISSION)
)
```

## Default Credentials

⚠️ **CHANGE IMMEDIATELY IN PRODUCTION**

```
Username: admin
Password: admin123
Role: admin
```

## Quick Commands

### Check User Status

```bash
cd /root/.hermes/skills/oracle-memory-by-yhw/security
python3 auth_db_working.py list-users
```

### Change Password

```bash
python3 auth_db_working.py change-password admin admin123 <new_password>
```

### View Access Logs

```bash
python3 auth_db_working.py list-logs 20
```

### Create New User

```bash
python3 auth_db_working.py create-user editor password123 editor
```

### Test Authentication

```bash
python3 auth_db_working.py test-auth admin admin123
```

## Password Hashing Format

```
salt:hash
```

**Example**: `a1b2c3d4e5f6:e96ecdfd3911b4ce1404b1de8286ef41db2836a2f38e86046a3d296a80d66476`

**Algorithm**:
```
hashhash = SHA-256(password + salt)
```

## Roles and Permissions

| Role | Description | Permissions |
|------|-------------|--------------|
| **admin** | Full access | view, export, edit, delete, manage_users |
| **editor** | Can view and export | view, exportation |
| **viewer** | Read-only | view only |

## Integration with Visualization Scripts

### Using Authenticated Export

```python
from security.auth_db_working import authenticate

# Authenticate user
user_info = authenticate(username, password)

if user_info and user_info['role'] in ['admin', 'editor']:
    # Allow export
    export_graph()
else:
    # Deny access
    raise PermissionError("Insufficient permissions")
```

### Using Authenticated Visualization

```bash
# Interactive visualization with auth
python3 scripts/interactive_viz_authenticated.py

# Web visualization server (uses db auth)
python3 start_web_server.py
```

## Troubleshooting

### Issue: Authentication Failed

**Symptom**: `❌ Authentication failed`

**Diagnosis**:
```sql
SELECT USERNAME, PASSWORD_HASH, ENABLED, ROLE 
FROM VIZ_USERS 
WHERE USERNAME = 'admin';
```

**Common Causes**:
1. Wrong password
2. Account disabled (ENABLED = 'N')
3. Password hash format incorrect

**Solution**:
```bash
# Reset to known hash
python3 auth_db_working.py change-password admin <old> <new>
```

### Issue: Database Tables Not Found

**Error**: `ORA-00942: table or view does not exist`

**Solution**: Deploy schema:
```bash
/root/sqlcl/bin/sql openclaw/hermes@//10.10.10.130:1521/openclaw @security/auth_schema.sql
```

## Security Best Practices

1. ✅ **Change default password immediately**
2. ✅ **Use strong passwords** (12+ chars, mixed case, numbers, symbols)
3. ✅ **Review access logs regularly**
4. ✅ **Set appropriate session timeout** (default: 60 minutes)
5. ✅ **Enable authentication in production**

---

**Last Updated**: 2026-05-12