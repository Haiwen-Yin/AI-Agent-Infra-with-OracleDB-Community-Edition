# v4.4.16 Release Notes

Scope: Oracle, PostgreSQL and YashanDB; Community and Enterprise editions.

## Changes

- Require all retained query terms in authorized source titles/content, apply English word boundaries and literal underscore matching, and avoid truncated-query matches. Summary-only candidates no longer count as answer evidence.
- Preserve complete Chinese search subjects instead of accepting arbitrary two-character fragments. Common question wrappers are removed; a generic company reference no longer matches an unrelated company-name query.
- Show a separate bilingual notice for general-model answers after a knowledge miss in Portal and Channels. Portal history restores answer provenance; Channel labels derive from the persisted, authorized execution rather than model text or caller-supplied references.

- Add an audited, explicit-ID repair command for idle local Portal-managed Agents whose legacy registration lacks a unified Agent Principal. Occupied, external, disabled and revoked identities are never reclaimed or reactivated by this command.
- Ignore English conversational filler in knowledge retrieval so unrelated enterprise records do not suppress configured general-model answers. Both Channels and Portal retain knowledge-first policy and disclosure controls; policy configuration now describes automatic no-match supplementation explicitly.

- Preserve the requested native Agent name in the existing Principal display name; inventory and cursor responses expose the readable name while retaining the technical ID.
- Resolve provisioning owners by globally unique username, with backward compatibility for Principal IDs.
- Allow authorized Community administrators to approve their own native Agent requests. Enterprise retains separation of applicant and approver.
- Enforce template isolation requirements on the server and disable insufficient isolation choices in the form.
- Display actionable provisioning validation errors without exposing internal provider details.
- Select Channel members and other Human/Agent references by readable name, with subject types and stable IDs distinguishing duplicate names. Channel selection respects existing Security Domain membership and protected administration roles.
- Correct application-only bootstrap selection and checksum-bound historical schema verification.
- Connect explicit Human mentions of platform-created Business Agents in ordinary Channels to managed execution and same-thread replies, with idempotency and current membership checks before dispatch and response writes.
- Run dedicated business Channel workers in a verified non-root Linux sandbox with no direct network or credentials; a single bound model-gateway request preserves the configured model while enforcing process identity, current authority, resource limits and cleanup.
- Register v4.4.16 in the six-edition build. This application-only update retains migration terminal 97 and existing database entities; it adds no schema migration.
- Resolve supplemental PostgreSQL migration checks from the generated package layout. Read YashanDB version metadata through the application-accessible version view without requiring instance-view privileges.
- Accept v4.4.16 in the standalone migration CLI while retaining the reviewed v4.4.15 schema chain and checksums.

## Validation

Release readiness requires generated-package checks, live tests on all six database/edition combinations, and actual browser workflows. Historical v4.4.15 evidence and source-only tests do not substitute for v4.4.16 acceptance. OCI readiness checks alone do not certify functional completeness.

Channel knowledge replies now apply model-disclosure policy, current conversation
reader intersection and source/policy revalidation before model dispatch and
publication. Historical Dashboard, Gateway and execution-result reads recheck
source access. Unapproved models receive no Knowledge text; authorized extracts
remain available. Legacy unbound queued answers require a new explicit request.

Restore migration 17 without rewriting applied checksums. Provide authenticated,
digest-bound Knowledge repair with transactional audit and additive role updates
that preserve custom permissions. Fix YashanDB driver installation to use the
selected interpreter's platform-library directory, including virtual environments.
Acceptance remains bound to the exact tested package; see current evidence.

The release evidence manifest records the tested package hashes and current
acceptance status separately from these product change notes.
