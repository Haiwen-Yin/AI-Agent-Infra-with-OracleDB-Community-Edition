# AI Agent Infra with DB v4.4.1

## Platform Administration And Availability

- Adds the protected Platform Administration Channel for administrators and
  approved management Agents.
- Adds database-authoritative Admin Agent membership, distinct voting weights,
  majority-by-count and majority-by-weight decisions, Leader terms, leases,
  and fencing tokens.
- Adds separate Dashboard and Portal idle and absolute session policies.

## Controlled Operations

- Adds signed-package staging and preflight, human approval, authenticated
  Admin Agent quorum votes, serialized node rollout evidence, and safe-point
  Skill distribution acknowledgements.
- Dashboard release operations now use one ZIP upload workflow. After server-
  side validation, the platform discovers governed nodes and active Agent
  principals, creates the controlled rollout and Skill notification records,
  and keeps running work on its pinned version until a safe-point acknowledgement.
- Adds an authenticated Gateway endpoint for Agents to poll pending verified
  Skill update metadata without receiving package contents or secrets.
- Adds ordered Agent containment commands. Platform permissions are revoked
  before quarantine or termination requests. Infrastructure termination
  requires a separately configured adapter and is not implied by this release.
- Adds bounded opaque cursor pagination for Agent, native-Agent, user,
  Channel, task, Memory, Knowledge, Skill, Spec, approval, audit, monitoring,
  and Enterprise compliance inventories. Page cursors remain bound to the
  current authenticated Principal, filters, sort order, and page size.

## Compatibility

- Requires Python 3.14 or later.
- The v4.4.1 migration is additive. Existing v4.4.0 data remains in place.
- Storage adapters for NFS, object storage, and unified storage remain
  integration contracts; only peer receipt evidence is implemented in-core.
