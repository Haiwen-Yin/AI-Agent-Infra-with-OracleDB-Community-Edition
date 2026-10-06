# Chuanxu v4.5.2

Date: 2026-10-06

## Changes

- Unify A2A and DB4A2A admission under the existing database Task Plan model;
  opaque protocol task keys are retained while each dispatch is bound to one
  canonical Task Plan.
- Add durable idempotency, attempt leases and fencing tokens, explicit
  `UNOBSERVED` recovery, exact context-source binding and immutable transition
  history.
- Classify historical DB4A2A dispatches as exact matches or legacy-unmapped
  records without inventing task identity during migration.

## Deployment

Migration 101 is additive for Oracle, PostgreSQL and YashanDB. Historical
migrations and their checksums remain unchanged. Existing Task Plans,
protocol records, context authorization and database-owned scheduling remain
authoritative; the continuity tables are a relationship and execution ledger,
not a second scheduler or authorization store.

PostgreSQL keeps the stable canonical-plan locator as a service-validated
relationship because its existing status-partitioned `TASK_PLANS` table only
offers the composite `(PLAN_ID, STATUS)` key. Oracle and YashanDB use their
existing unique `PLAN_ID` constraint for the physical foreign-key path. The
service performs the same locked canonical-plan check on all three adapters.

## Operations

An expired or unknown send is not retried automatically. Operators must
reconcile the persisted business key and original request digest before a
terminal outcome is recorded. A stale worker cannot complete an attempt after
its fencing token or lease has been superseded.
