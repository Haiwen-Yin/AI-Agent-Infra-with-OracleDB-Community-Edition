# Web Visualization Server Login Page Specification

**Version**: v1.1.0+  
**Date**: 2026-05-12  
**Author**: Haiwen Yin (yhw)

---

## Overview

The login page for the Oracle Memory System Web Visualization Server is **English-only** with simplified labels. Unlike the main application pages which support bilingual switching, the login page uses fixed English labels for clarity and security.

---

## Login Page Requirements

### Language Specification

**FIXED: English Only**

The login page must:
- ✅ Use English labels: Username, Password, Login
- ❌ NOT display Chinese labels: 用户名, 密码, 登录
- ❌ NOT include language switching functionality
- ❌ NOT respond to session language preferences

### Required Labels

```
Username
Password
Login (button)
```

### Error Messages

English-only error messages:
- "Invalid username or password. Please try again."
- No bilingual or Chinese error messages

---

## Implementation Details

### HTML Structure

```html
<form method="POST" action="/api/login">
    <div class="form-group">
        <label for="username">Username</label>
        <input type="text" id="username" name="username" 
               required autocomplete="username" autofocus>
    </div>
    <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" 
               required autocomplete="current-password">
    </div>
    <button type="submit">Login</button>
</form>
```

### send_login_page() Function

The `send_login_page()` method should:
1. Accept optional `error_message` parameter
2. Generate English-only HTML
3. Not use I18N text dictionary for login page
4. Not include language switching button

### Do Not Include

- ❌ Language switching button (`🌐 切换语言` / `🌐 Switch Language`)
- ❌ I18N text dictionary references for login labels
- ❌ Session-based language preference loading
- ❌ Chinese language support in any form

---

## Authentication Flow

```
User Request → Check Session
    ↓
No Session → Redirect to /login
    ↓
Display English Login Page
    ↓
User enters Username/Password
    ↓
POST to /api/login
    ↓
Database Validation (memory_system_users table)
    ↓
If Invalid → Show Error Message (English)
    ↓
If Valid → Create Session → Redirect to /graph
```

---

## Error Handling

### Invalid Credentials

When authentication fails:
```
Display error message: "Invalid username or password. Please try again."
```

### Session Timeout

When session expires:
```
Display auto-logout countdown → Redirect to /login
Login page shows no previous context
```

---

## Why English-Only Login Page?

### Security Considerations

1. **Reduced Attack Surface**: Single-language login page reduces complexity
2. **Consistency**: English is the universal language for technical systems
3. **Simplified Validation**: No language-dependent validation logic

### User Experience

1. **Clear Intent**: Users expect English labels in authentication interfaces
2. **Professional Standard**: Enterprise systems typically use English for login
3. **Familiar Pattern**: Username/Password/Login is a universal pattern

### Implementation Simplicity

1. **No Session State**: Login page doesn't need to read language preferences
2. **Static Content**: HTML generation is simpler without I18N lookups
3. **Easier Maintenance**: Single set of labels to maintain

---

## Verification Checklist

Before finalizing v1.1.0+ release:

- [ ] Login page displays "Username" label (English)
- [ ] Login page displays "Password" label (English)
- [ ] Login button displays "Login" (English)
- [ ] No language switching button visible on login page
- [ ] Error messages are in English only
- [ ] Chinese labels are NOT present (用户名, 密码, 登录)
- [ ] I18N text dictionary is NOT used for login labels
- [ ] Login page HTML does not reference `I18N_TEXT` dictionary

---

## Common Pitfalls

### ❌ Pitfall 1: Using I18N Dictionary

**Wrong**:
```python
html = f"""<label for="username">{I18N_TEXT[language]['username']}</label>"""
```

**Correct**:
```python
html = f"""<label for="username">Username</label>"""
```

### ❌ Pitfall 2: Including Language Switch Button

**Wrong**:
```html
<button onclick="switchLanguage()">🌐 切换语言</button>
```

**Correct**:
```html
<!-- No language switch button on login page -->
```

### ❌ Pitfall 3: Chinese Error Messages

**Wrong**:
```python
error_html = "用户名或密码错误，请重试"
```

**Correct**:
```python
error_html = "Invalid username or password. Please try again."
```

---

## Related Documentation

- **[README_VIZ_SERVER.md](../../README_VIZ_SERVER.md)** - Full Web Visualization Server documentation
- **[DATABASE_AUTHENTICATION.md](../../DATABASE_AUTHENTICATION.md)** - Database-backed authentication implementation
- **[Web Visualization Server v1.1.0 Release Notes](../../RELEASE_NOTES_v1.1.0.md)** - v1.1.0 features and enhancements

---

## Change History

| Version | Date | Change |
|---------|------|--------|
| v1.1.0 | 2026-05-12 | Initial specification - English-only login page |

---

**Documented by**: yhw (Haiwen Yin)  
**Review Date**: 2026-05-12
