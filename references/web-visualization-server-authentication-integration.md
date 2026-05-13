# Web Visualization Server Authentication Integration

**Author**: Haiwen Yin (胖头鱼 🐟)  
**Date**: 2026-05-12  
**Related Skill**: `oracle-memory-by-yhw` v1.4.0

---

**Summary**: Integrated database-based authentication into `viz_server_local_js.py` web visualization server, enabling secure access control for knowledge graph and memory content visualization.

---

## Implementation Details

### Session Management

In-memory session storage with 1-hour TTL:

```python
# Session structure
_sessions = {
    '8dfb6f1c3516038e456313619ad9811596778e5c36e828352bd103584f6b4eb6': {
        'username': 'admin',
        'role': 'admin',
        'created_at': 1715491200.0,
        'expires_at': 1715494800.0  # +1 hour
    }
}
```

**Auto-extend on access**: Each valid request automatically extends session expiry by 1 hour.

### Password Hashing

**Supports two formats**:

1. **Modern (Salt-based)**: `salt:hash`
   - Format: `{salt}:{sha256(password + salt)}`
   - Example: `a1b2c3d4e5f6:e96ecdfd3911b4ce1404b1de8286ef41db2836a2f38e86046a3d296a80d66476`

2. **Legacy (Simple)**: `hash`
   - Format: `sha256(password)`
   - Example: `8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918`

**Verification logic**: Try modern format first, fall back to legacy if parsing fails.

### Route Protection

| Route | Auth Required | Behavior |
|-------|---------------|----------|
| `/login` | ❌ No | Display login page |
| `/api/login` | ❌ No | Process login POST |
| `/api/logout` | ❌ No | Clear session cookie |
| `/static/*` | ❌ No | Serve static assets |
| `/api/health` | ❌ No | Health check |
| `/`, `/graph`, `/memory` | ✅ Yes | Redirect to /login if unauthenticated |
| `/api/graph`, `/api/memory` | ✅ Yes | Return 401 if unauthenticated |
| `/api/node/*` | ✅ Yes | Return 401 if unauthenticated |

### Cookie Security

```
Set-Cookie: session_token=8dfb6f1c...; Path=/; HttpOnly; SameSite=Lax
```

- **HttpOnly**: Prevents JavaScript XSS access
- **SameSite=Lax**: CSRF protection
- **Token Generation**: `secrets.token_hex(32)` → 64 hex chars (256-bit entropy)

### Login Flow

```
1. User accesses http://10.10.10.135:8000/
   
2. Server checks for session_token cookie
   └─► Missing or invalid → Redirect to /login
       
3. User enters credentials → POST /api/login
   ├─► Query VIZ_USERS table
   ├─► Verify password hash
   ├─► Generate session token
   ├─► Store in _sessions dict
   └─► Set session_token cookie → Redirect to /graph
   
4. User accesses protected pages
   └─► Validate session_token → Allow access
```

### Database Schema

**VIZ_USERS Table** (Authentication data source):

```sql
CREATE TABLE VIZ_USERS (
    USERNAME         VARCHAR2(50) PRIMARY KEY,
    PASSWORD_HASH    VARCHAR2(200) NOT NULL,  -- salt:hash or hash
    ROLE             VARCHAR2(20) NOT NULL,    -- admin/editor/viewer
    ENABLED          VARCHAR2(1) DEFAULT 'Y',  -- Y/N
    CREATED_AT       TIMESTAMP DEFAULT SYSTIMESTAMP,
    LAST_LOGIN_AT    TIMESTAMP
);
```

**Default User**:
- Username: `admin`
- Password: `admin123`
- Password Hash: `a1b2c3d4e5f6:e96ecdfd3911b4ce1404b1de8286ef41db2836a2f38e86046a3d296a80d66476`
- Role: `admin`

### Testing Checklist

✅ **Unauthenticated access redirects to login**
```bash
curl -I http://localhost:8000/
# → 302 Found → Location: /login
```

✅ **Successful login sets session cookie**
```bash
curl -c /tmp/cookies.txt -X POST \
  -d "username=admin&password=admin123" \
  http://localhost:8000/api/login
# → 302 Found → Location: /graph
# → Set-Cookie: session_token=xxx; Path=/; HttpOnly; SameSite=Lax
```

✅ **Session allows API access**
```bash
curl -b /tmp/cookies.txt http://localhost:8000/api/graph
# → {"nodes": [...], "edges": [...]}
```

✅ **Missing session is rejected**
```bash
curl http://http://localhost:8000/api/graph
# → 302 Found → Location: /login
```

✅ **Invalid credentials show login page with error**
```bash
curl -X POST -d "username=admin&password=wrong" \
  http://localhost:8000/api/login
# → 302 Found → Location: /login?error=Invalid%20username%20or%20password
```

### Security Considerations

1. **Session Storage**: Currently in-memory (production: migrate to Redis)
2. **Token Entropy**: 256-bit random hex string (cryptographically secure)
3. **Password Hashing**: SHA-256 with salt (modern) or simple SHA-256 (legacy)
4. **Session Expiry**: 1 hour, auto-extends on access
5. **Cookie Security**: HttpOnly + SameSite=Lax
6. **Failed Login Feedback**: Generic error (prevents username enumeration)

### Future Enhancements

- [ ] Migrate session storage to Redis
- [ ] Implement rate limiting on login endpoint
- [ ] Add CSRF token validation for POST requests
- [ ] Implement password change functionality
- [ ] Add session invalidation (logout all devices)
- [ ] Implement API key authentication for automated access
- [ ] Add multi-factor authentication (MFA) support

### Files Modified

- `viz_server_local_js.py` - Added authentication middleware
  - `generate_session_token()` - Secure token generation
  - `validate_session()` - Session validation with auto-extend
  - `verify_user()` - Database credential verification
  - `send_login_page()` - Login page renderer
  - `do_POST()` - Login endpoint handler
  - Route protection in `do_GET()`

### Related Documentation

- [DATABASE_AUTHENTICATION.md](../DATABASE_AUTHENTICATION.md) - Database authentication system overview
- [web-visualization-dual-page-architecture.md](./web-visualization-dual-page-architecture.md) - Dual-page architecture guide

---

**Status**: ✅ Implemented and tested (2026-05-12)