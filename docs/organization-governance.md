# Organization Governance - AI Agent Infra with DB v4.4.10

v4.3.1 introduces a database-authoritative organization model and a graphical
workspace for controlled search, inspection, and change preparation. It is a
stable production capability and does not require the Graph Engineering
preview profile.

## Authority Model

- An ordinary platform account, Human Principal, and organization person are
  one subject. It has exactly one active primary organization and may have
  multiple effective-dated secondary memberships.
- Registration approval selects the primary organization and creates both the
  account and membership in one transaction. A Principal without an active
  login identity cannot become an organization member.
- The protected bootstrap `admin` is a system-recovery account and remains
  outside the natural-person organization hierarchy.
- A Human has at most one active direct manager. Dotted-line managers and
  project leads are effective-dated relationships and do not widen authority.
- Every managed Agent retains one active Human `PRIMARY_OWNER`. Responsible
  organizations, groups, operators, and viewers add accountability without
  replacing that owner.
- `ORG_SUBTREE` is evaluated from `CX_ORGANIZATION_CLOSURE` and primary
  membership. `DIRECT_REPORTS` is evaluated from canonical direct-reporting
  facts. Security Domain scope intersects organization scope when both apply.
- Relational facts are the authorization source of truth. A Property Graph or
  Web canvas is a replaceable, post-authorization projection.

## Graphical Workspace

The Organization page provides deterministic hierarchical layout, progressive
subtree loading, bounded search, vertical or horizontal orientation, and four
authorized views: organization, people assignment, Agent responsibility, and
anomalies. Dragging an organization proposes a semantic parent change in a
draft. Coordinates are never persisted and no authoritative row changes until
governed publication succeeds.

Mobile clients are intended for search, focused inspection, history, and
approval. Complex drag editing remains a desktop workflow.

## Change Lifecycle

Changes use `CX_ORG_CHANGESETS` and ordered semantic operations. Each draft has
a reason, idempotency key, base organization version, row-version checks, risk
classification, validation result, and impact summary. Undo and redo change
operation state only. Validation checks stale versions, missing parents,
cycles, scope, and target visibility. Submission freezes the validated draft
for approval; publication remains a separate permission and transaction.

Low-risk publication atomically updates current facts, rebuilds closure when
needed, writes immutable version history, increments affected permission
versions, and revokes affected Human sessions and Agent access tokens. High
risk changes require the approval path and cannot use low-risk publication.

## Directory Staging

Manual, CSV, and JSON records are normalized into bounded staging batches.
Protected platform authority fields such as roles, permissions, Security
Domains, Agent relationships, passwords, and secrets are discarded from
incoming records. LDAP is an Enterprise connector boundary. OIDC and SCIM are
reserved schema values and must not be advertised as active connectors.

Unresolved synchronization conflicts remain visible governance work and never
overwrite current authority merely because a source record arrived.

## Operational Checks

Before enabling organization editing, run the packaged migration runner and
`live_db_validator.py`. The v4.3.1 probe verifies the migration journal,
required columns, closure and history tables, uniqueness indexes, role
templates, and adapter-specific database controls. A missing organization
object fails readiness rather than silently hiding the page.

All API requests require a database-backed Human Session, CSRF protection for
mutations, an action permission, and database-side scope filtering. Clients
must not load enterprise-wide facts and filter them locally.
