# Release Notes — v3.3.0

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-05

License: Apache License 2.0

---

## Overview

v3.3.0 introduces **Database Access Security** — a multi-layer security framework preventing Agents from bypassing the API layer to directly operate on the database. When an Agent obtains database connection credentials, the restricted user and auditing policies ensure it cannot perform unauthorized operations.

---

## New Features

### 1. Database Access Policy (SKILL.md)

Explicit 4-rule policy documented in SKILL.md:

1. **Never bypass the API layer** — All data operations MUST go through Python API or PL/SQL packages. Direct SQL/DML/DDL is strictly prohibited except during initial deployment.
2. **No credential injection** — Database connection credentials must not be stored in Agent context.
3. **Use AGENT_API restricted user** — Runtime connections should use the restricted database user, not the schema owner.
4. **Deployment scripts are the only exception** — `scripts/deploy/*.sql` are the only authorized direct SQL operations.

### 2. Restricted AGENT_API Database User (`4_grants.sql`)

New deployment script that creates a restricted database user for Agent runtime connections:

| Privilege | AIADMIN (deployment) | AGENT_API (runtime) |
|-----------|---------------------|---------------------|
| CREATE SESSION | Yes | Yes |
| EXECUTE PL/SQL packages | Yes | Yes (AUTHID DEFINER) |
| SELECT tables | Yes | Yes (read-only) |
| INSERT/UPDATE/DELETE | Yes | **No** |
| CREATE/ALTER/DROP | Yes | **No** |

### 3. Credential Sanitization (`_sanitize_context_data()`)

`save_context()` automatically redacts sensitive fields (password, token, credential, dsn, api_key, secret, private_key, etc.) before storing. Supports nested dict detection. Redacted values replaced with `[REDACTED]`.

### 4. Unified Auditing (`5_audit_policy.sql`)

New `DIRECT_DML_BYPASS_DETECTION` audit policy that logs direct DML on critical tables (WORKSPACE_CONTEXT, AGENT_REGISTRY, CONTEXT_BRANCHES, SYSTEM_CONFIG) by non-schema-owner users.

### 5. AUTHID DEFINER Verification

All 13 PL/SQL packages verified to use AUTHID DEFINER (Oracle default), ensuring restricted users cannot bypass package-level business rules.

---

## Security Layers Summary

| Layer | Mechanism | Protection Target | Implementation |
|-------|-----------|-------------------|---------------|
| L1 | SKILL.md policy | Normative prohibition | Documentation |
| L2 | AGENT_API restricted user | Technical DDL/DML restriction | `4_grants.sql` |
| L3 | AUTHID DEFINER packages | Enforce business logic | PL/SQL default |
| L5 | Unified Auditing | Detect bypass attempts | `5_audit_policy.sql` |
| L6 | Credential sanitization | Prevent credential leakage | `workspace_api.py` |

---

## Deployment

### New Scripts

```bash
# Create restricted user (run as SYSDBA)
sql sys/password@//host:port/service as sysdba @scripts/deploy/4_grants.sql

# Enable audit policy (run as SYSDBA)
sql sys/password@//host:port/service as sysdba @scripts/deploy/5_audit_policy.sql
```

### Update Agent Configuration

Update `config.json` to use `AGENT_API` credentials for runtime connections. Keep `AIADMIN` credentials for deployment only.

---

## System Requirements

- Oracle Database 23ai+ (tested on 26ai)
- `GRANT EXECUTE ON SYS.DBMS_CRYPTO` (carried from v3.1.0)
- Python 3.8+ with `oracledb` package
- SQLcl 26.1+ (for SQL script deployment)
- SYSDBA access (for creating restricted user and audit policy)
