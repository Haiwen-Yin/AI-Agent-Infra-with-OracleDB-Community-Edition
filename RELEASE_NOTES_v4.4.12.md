# AI Agent Infra v4.4.12

Status: candidate release with constrained claims. Updated: 2026-09-06.

## Implemented Changes

- Migration 78 removes historical YashanDB external-role writes to gateway
  credentials and access tokens. Independent cross-Agent update probes cover
  these authentication records as well as principals and the Agent registry.
  This targeted repair does not certify every native object or privilege path.

- Installs YashanDB native-client links from ELF SONAME instead of inferring
  ABI versions from filenames. Requires `binutils` and verifies actual
  `libyascli.so` loading, not merely a successful `import yaspy`.

- Binds legacy Dashboard/Portal cookies to the actual request port, with
  request-local context restored after success, exceptions and streaming.
  Direct Uvicorn on a port different from config no longer causes legacy
  monitor, memory, branch and graph APIs to return spurious 401 responses.

- Recursively sanitizes secrets inside context lists as well as dictionaries.
- Verifies DB4A2A receiver reads through independent database credentials;
  branch source Agent IDs now reference context authors, not Human senders.
- Keeps Oracle/YashanDB cached Agent sessions separate across threads and
  verifies concurrent callers hold distinct database connections.
- Adds YashanDB migration 69 with a database-enforced context reader view and
  explicit shared-context grants, revokes unsafe base-table/package access,
  and checks the missing ALTER SESSION prerequisite. Native direct context
  DML is not granted; other business-table isolation remains under audit.

- Rewrites the Chinese introduction for each database adapter and adds a
  prominent README link in all six generated editions.
- Normalizes nested chat-completion cache and reasoning usage. Detail rates
  replace ordinary rates for those subsets, avoiding double charging. Missing
  totals or inconsistent details leave cost unknown instead of reporting zero.
- Restricts DB4A2A branch lookup and creation to dispatch participants with
  operation permission, including idempotent responses. Inactive and read-only
  dispatches cannot expose or create child branches through this endpoint.
- Propagates failed branch insertions instead of returning an identifier for
  a nonexistent branch. PostgreSQL no longer tries an Oracle procedure merely
  because the Oracle driver is installed.
- DB-mediated branch creation now locks and verifies the canonical context
  digest, workspace scope and source branch, then inserts a native PARALLEL
  branch and records linkage/audit in one transaction. Snapshot format version
  1 is explicit; legacy unverified reference envelopes fail closed.
- Adds regression tests for authorization negatives and release evidence.
  Customer-material validation requires an approved, releasable manifest and
  matching hashes for six distinct edition archives.
- Generates deployment baseline manifests from the actual build version and
  reviewed terminal migration, preventing a v4.4.12 package from inheriting a
  v4.4.10 initialization contract. Unknown release mappings fail the build.
- Makes failed standalone Bootstrap verification return FAILED and a nonzero
  CLI exit code. JSON output alone is no longer interpreted as success.
- Corrects the developer guide's local OpenSpec location, configuration and
  session-cookie contracts, edition governance boundaries, and test database
  cleanup rules.
- Lets knowledge visibility form rows fit actual control and hint heights;
  adds desktop/mobile geometry assertions to catch text/control overlap.

## Verification Boundaries

Source tests and development builds do not establish live database isolation,
protocol interoperability, browser correctness, or production readiness.
Database authorization and concurrent-client behavior remain under audit.
Service authorization supplements database policies; it is not a
replacement for database-enforced isolation.

The research audit withdraws synthetic end-to-end Token savings claims. Real
provider usage, equivalent task outputs and separately measured transport
bytes are required before publishing new DB4A2A/A2A cost comparisons.

## Pending Release Gates

All six isolated COM/ENT databases completed initialization and independent
verification through migration 68 on 2026-09-05. This does not establish
production capacity or complete authorization coverage. External-Agent and
desktop/mobile navigation evidence is tracked separately per edition.
Subsequent security tests required Oracle/YashanDB migration 69. Four separate
second-round PDBs completed clean initialization and independent verification
through this migration; the first-round results are retained separately.

Current-artifact package regression and the tested authorization and browser
gates are recorded in the release evidence manifest. This release is limited
to the tested local six-edition baseline and does not claim production
capacity, certification, universal interoperability, or complete mutation
coverage. Existing deployments are not changed by building this candidate.
# Additional Native Control-Plane Repair (2026-09-05)

Migration 72 removes external runtime INSERT/UPDATE/DELETE privileges on
principal and Agent registry tables for PostgreSQL and YashanDB. Lifecycle
changes must use authenticated platform APIs; raw external SQL must not mutate
another Agent's control records. PostgreSQL enrollment reapplies this boundary
after legacy broad grants. Oracle retains its existing Data Grant enforcement.
This is a targeted repair, not a certification of all native objects.

Migration 73 makes YashanDB privilege cleanup safe for partially granted roles.
Migration 74 enforces explicit knowledge policies on Oracle/PG native reads,
including revocation despite legacy PUBLIC flags. Migration 75 separates PG
public reading from owner-bound native insert/update/delete authorization.
Organization-owner inheritance and the complete native-object matrix remain
under validation; these targeted fixes do not establish production readiness.

Migrations 76/77 resolve native organization knowledge access through the active
Human PRIMARY_OWNER, with membership, relationship, principal and organization
validity checked at read time. Oracle adds narrowly scoped read-only Data Grants
for the Agent's owner and ancestor chain. The platform knowledge predicate uses
the same owner mapping; a legacy SHARED marker alone no longer grants reading.
Knowledge provenance snapshots select the owner's PRIMARY membership for the
single organization chain; explicit SECONDARY memberships remain valid scoped
access facts and are re-evaluated when revoked.
