# Release Notes — v3.7.2

**AI Agent Infra with OracleDB — Community Edition**

Release Date: 2026-06-19

License: Apache License 2.0

Official Website: https://db4agent.top

---

## Overview

v3.7.2 is a documentation consistency release. No code changes — all fixes are documentation corrections to align with actual codebase counts and behavior.

---

## Documentation Corrections

### LOOP_MANAGER Function Count
- **Corrected**: ~33 → ~22 (actual subprogram count from package/schema specification)
- Affected files: RELEASE_NOTES, loop-engineering.md, SKILL.md

### loop_api.py Function Description
- **Corrected**: "32 public API functions" → "32 public API functions + private evaluation helpers"
- Oracle editions: 32 public + 7 private (39 total `def` statements)
- PG editions: 32 public + 5 private (37 total `def` statements)
- Affected files: RELEASE_NOTES, loop-engineering.md, SKILL.md, README.md

### LOOP_CLEANUP_JOB Schedule
- **Corrected**: "Weekly Sunday 06:00" → "Weekly Sunday 06:00" (matches actual SQL scheduler definition)
- Actual schedule: `FREQ=WEEKLY; BYDAY=SUN; BYHOUR=6` (Oracle) / `0 6 * * 0` (PG cron)
- Affected files: RELEASE_NOTES, loop-engineering.md, SKILL.md, README.md

### ENTITIES Partition Count
- **Corrected**: 7 → 8 partitions (includes SKILL partition)
- Actual partitions: MEMORY, KNOWLEDGE, TASK_OUTPUT, EXPERIENCE, HARNESS_TEMPLATE, SPEC, SKILL, OTHERS
- Affected files: SKILL.md, introduction_zh, README.md

### Reference-Partitioned Children Count
- **Corrected**: 6 → 8 (includes SKILL_META and LOOP_META)
- Affected files: SKILL.md, loop-engineering.md

### ON_START Lifecycle Hook
- **Added**: ON_START to v3.7.0 CHANGELOG hooks list (was present in code but omitted from changelog)
- Actual hook events in DB constraint: PRE_RUN, ON_START, POST_ITERATION, ON_STOP, ON_FAIL, ON_TIMEOUT

### Evaluation Types Description
- **Corrected**: "four evaluation types" → "six evaluation types" in loop-engineering.md body text
- Header already said 6; body text was stale from v3.7.0

### RELEASE_NOTES v3.7.0/v3.7.1 Bug Fixes Boundary
- Bug fixes in RELEASE_NOTES now labeled with originating version: **[v3.7.0]** or **[v3.7.1]**
- v3.7.0 fixes: loop API import, missing handlers, loops nav, close button, server startup, seed data, audit page
- v3.7.1 fixes: session persistence, session timeout, PG loop API, PG runs API, PG auth, route order, PG ENT label

### SKILL_MANAGER Package (Oracle Community Edition Only)
- **Removed**: SKILL_MANAGER PL/SQL package from Community Edition SKILL.md
- This package exists only in Enterprise Edition (2_api.sql), not in Community Edition

### Python Module Count (Oracle Enterprise Edition)
- **Corrected**: 25 → 26 (includes ldap_auth_api.py)

---

## Updated Counts (v3.7.2)

| Metric | Count |
|--------|-------|
| Tables | 35 |
| PL/SQL Packages | 14 |
| Python Modules | 23 |
| Scheduler Jobs | 16 |
| Loop API Public Functions | 32 |
| LOOP_MANAGER Subprograms | ~22 |
| Evaluation Types | 6 |
| ENTITIES Partitions | 8 |

---

## Backward Compatibility

No breaking changes. This release contains documentation corrections only — no code, schema, or API changes.
