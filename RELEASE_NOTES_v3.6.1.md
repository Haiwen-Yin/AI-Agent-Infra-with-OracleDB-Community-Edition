# Release Notes — v3.6.1

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-14

License: Apache License 2.0

---

## Overview

v3.6.1 is a bug fix release addressing Portal login issues and documentation inconsistencies discovered after v3.6.0 deployment.

---

## Bug Fixes

### Portal Login

**Problem**: Portal login returned `AttributeError: 'VisHandler' object has no attribute '_handle_portal_login'`.

**Fix**: Added missing `_handle_portal_login()` method. Portal login now authenticates local system users and automatically assigns a Pool Agent to the session. Both login and register responses now include `has_agent` field for consistent frontend handling.

### Graph Interaction

**Fix**: Detail panel changed to `position:fixed` overlay to prevent graph resize/pan when toggling details. Click blank area now closes detail panel and resets highlight. View position and scale preserved on all node interactions.

### Documentation Corrections

- Deep Sec introduction version: "v3.5.0" → "v3.4.0" in SKILL.md
- PBKDF2 description: "SHA256/100K" → "SHA512/210K" in RELEASE_NOTES
- Admin Token format: corrected to `AT_` + 32hex (persistent, rotatable)
- Data Grant count: fixed "22" → "23" in architecture.md
- Test counts: updated stale "183" → 105 in SKILL.md, "61" → 105 in deployment.md
- Port numbers: corrected all `localhost:8000` references to 18080/18090
- ENT feature matrix: "Encrypted DB Credentials | No | Yes" → "Yes | Yes"; added Recovery Codes + Private Skill rows
- ENT api-reference: title corrected to "Enterprise Edition"; added 9 missing Admin API endpoints
- Version display: all page titles updated to v3.6.1

---

## Backward Compatibility

No breaking changes. Existing v3.6.0 deployments can upgrade by updating files only — no schema migration required (schema_version remains compatible).

---

## System Requirements

Unchanged from v3.6.0:
- Oracle AI Database 26ai version 23.26.2.0.0 or later
- Python 3.8+ with oracledb 4.0.1+
