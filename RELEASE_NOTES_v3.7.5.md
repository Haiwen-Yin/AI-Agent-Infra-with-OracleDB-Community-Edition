# Release Notes — v3.7.5

**Version**: v3.7.5 | **Date**: 2026-06-28

## Overview

v3.7.5 is a bug fix and code quality release for Oracle editions. Fixes issues found during v3.7.4 code review.

## Bug Fixes

### 1. orchestrator.py execute_step_with_retry stub
- Now queries actual TASK_STEPS before marking SUCCESS
- Checks for active LOOP_RUNS bound to the step before completing
- No longer blindly marks steps as SUCCESS without execution

### 2. event_bus.py webhook/script execution
- Webhook: added retry with exponential backoff, configurable timeout, custom headers
- Script: replaced `shell=True` with safe `shlex.split()` + argument list execution
- Both: proper error handling with TimeoutExpired and CalledProcessError

### 3. message_api.py delete_message status
- Changed soft-delete from `STATUS='FAILED'` to `STATUS='DELETED'`
- Updated CK_CM_STATUS constraint in schema to include 'DELETED' instead of 'FAILED'
- Updated all query filters to exclude 'DELETED' instead of 'FAILED'



## Upgrade Notes

- No database migration required for existing v3.7.4 deployments
- Replace code files (orchestrator.py, event_bus.py, message_api.py)

