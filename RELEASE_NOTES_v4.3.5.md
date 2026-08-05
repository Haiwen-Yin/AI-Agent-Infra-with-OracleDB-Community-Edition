# Chuanxu AI Agent Management Platform v4.3.5

Release date: 2026-08-05

## Database-Authoritative Platform Capability Configuration

v4.3.5 adds an installation-level capability layer. A capability is usable
only when the package contains the feature, the database registry enables it,
and the current Principal is authorized for the requested action. Frontend
visibility is therefore only a convenience; every mapped API boundary is
enforced by the backend.

The Dashboard adds a bilingual protected **Capability Configuration** page.
Administrators can enable or disable optional product areas, while identity,
authorization, security controls, audit writing, Agent identity, user
management, and capability configuration remain mandatory. Dependencies must
be enabled before a dependent capability can be enabled, and an enabled
dependent capability prevents its prerequisite from being disabled.

Every change requires `platform.manage`, CSRF validation, a non-empty reason,
and the expected database row version. The state row, immutable history row,
and `CX_SECURITY_EVENTS` audit record are committed in one database
transaction. Existing data and running work are retained when a capability is
disabled; only new entry points and capability-specific background work are
blocked.

## Database And Security Contract

Oracle AI Database 26ai, PostgreSQL 18, and YashanDB 23.5.4 each receive the
same logical objects:

- `CX_PLATFORM_CAPABILITIES`
- `CX_PLATFORM_CAPABILITY_DEPENDENCIES`
- `CX_PLATFORM_CAPABILITY_HISTORY`

The Community build physically excludes Enterprise modules and migrations;
the runtime registry cannot expand that build boundary. Cross-Admin Skill
acquisition now sends its admin token in `X-Admin-Token` instead of a URL query
parameter. Oracle End User provisioning rejects unsafe identifiers before
dynamic DDL. Secrets are not stored in the capability registry.

## Upgrade

Create recoverable backup evidence and run the v4.3.5 migration with
`migration_runner.py --version 4.3.5`. The migration is additive and
idempotent. Enterprise packages apply the v4.3.4 compliance overlay before
step 31; Community packages retain their physical edition boundary. Existing
v4.3.4 behavior is preserved because all capabilities seed enabled by default.

Use `live_db_validator.py --version 4.3.5` and the generated package test suite
for release verification against the target database.
