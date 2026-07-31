# AI Agent Infra with DB v4.3.1

Release date: 2026-07-31

v4.3.1 is the Chuanxu (川序) graphical organization-governance release for
Oracle AI Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4.
Community and Enterprise packages continue to share one implementation with
edition capabilities enforced during packaging and at the server boundary.

## Organization Governance

- Added a capability-driven Organization page with Chinese and English text,
  light and dark themes, bounded search, progressive expansion, breadcrumbs,
  deterministic vertical or horizontal hierarchy, and desktop semantic drag.
- Added organization, people assignment, Agent responsibility, and anomaly
  views. Mobile intentionally supports focused inspection and approval rather
  than complex drag editing.
- Added canonical primary/secondary memberships, direct/dotted/project
  reporting, closure, organization versions, immutable history, directory
  staging and conflicts, and lifecycle disposition objects.
- Unified each ordinary platform account, Human Principal, and organization
  person. Registration approval now selects and atomically assigns the active
  primary organization; organization membership rejects Principals without an
  active login identity. The protected bootstrap `admin` remains the sole
  system-account exception and is not represented as a natural person.
- Preserved one active Human `PRIMARY_OWNER` per Agent while allowing multiple
  operators and viewers and an accountable organization or group.
- Added semantic change-set creation, ordered operations, undo, redo,
  validation, impact analysis, approval submission, optimistic concurrency,
  and low-risk atomic publication. Canvas coordinates are never persisted.

## Security

- Replaced fixed-depth organization authorization with closure-backed
  `ORG_SUBTREE` evaluation based only on active primary membership.
- Added canonical `DIRECT_REPORTS` evaluation and corrected Agent visibility
  predicate composition. Security Domain scope intersects organization scope
  instead of widening it.
- Kept relational facts as the authorization source of truth. Property Graph
  and Web diagrams are bounded post-authorization projections and cannot grant
  access.
- Publication increments affected permission versions and revokes affected
  Human Sessions and Agent tokens in the authoritative transaction.
- Added `ORG_MANAGER` and organization action permissions across all three
  database role templates. Protected platform authority fields are removed
  from staged directory records.
- Added independently governed Human entry surfaces. Existing users retain
  Portal and App access during migration; newly approved registrations default
  to Portal-only until an administrator enables App access with a reason.
- Protected the local bootstrap `admin` Principal from App admission disable,
  `SYSTEM_ADMIN` role revocation, and DENY permission overrides. Entry changes
  revoke active Sessions and are enforced at login and per protected request.

## Database And Packaging

- Added v4.3.1 migration steps 19 through 22 to all six packages without
  modifying prior release migration files. Step 20 adds Human display names;
  step 21 adds Human entry admission and bootstrap-admin normalization; step
  22 enforces identity-to-organization alignment and removes bootstrap-admin
  organization relationships.
- Added v4.3.1 migration selection, static and live readiness probes, generated
  package guards, and the organization Web assets.
- Python 3.14+ remains required. Offline packages retain compatible
  `cryptography==49.0.0` wheels for glibc 2.28 and newer supported hosts.
- A v4.3.1 archive contains only `RELEASE_NOTES_v4.3.1.md`.

See `docs/organization-governance.md`, `docs/api-reference.md`,
`docs/security.md`, and `docs/migration.md` for operational boundaries.
