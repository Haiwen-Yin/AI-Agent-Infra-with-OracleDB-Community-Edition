# AI Agent Infra with DB v4.1.0 Release Notes (2026-07-24)

Product brand: **Chuanxu (川序)** · Product: **AI Agent Management Platform**

The technical project name remains **AI Agent Infra with DB**. These release
notes apply to the applicable database adapter and edition package.

v4.1.0 evolves the infrastructure into a governed AI Agent management platform
and applies the Chuanxu visual system across the product UI. Agents may be
created by the platform or supplied by external runtimes such as OpenClaw,
Hermes Agent, or any other runtime capable of using `SKILL.md`. Every Agent
must register and authenticate before entering the managed boundary.

## Core Changes

- **Registered identity boundary:** Every Agent uses a stable platform
  identity with administrator registration, credential digests, heartbeat,
  lifecycle status, expiry, disablement, revocation, and node metadata.
  Unknown or invalid identities fail closed.
- **Enterprise resource governance:** Enterprise adds a resource catalog for
  database data, APIs, Skills, Tools, knowledge, workspaces, and data extracts.
  Policy decisions evaluate subject, resource, action, classification,
  purpose, environment, and validity period and return `ALLOW`, `DENY`, or
  `APPROVAL_REQUIRED`.
- **Multi-party approval and separation of duties:** Enterprise supports
  configurable N-of-M approval, server-owned approver eligibility, requester
  exclusion, prohibited duty combinations, mandatory reasons, bounded
  exceptions, emergency controls, and optional post-event review.
- **Risk-based audit:** The default audit path stores metadata and decision
  evidence rather than complete request and response payloads. High-risk
  events may retain bounded masked detail, payload hashes, or encrypted
  references. Enterprise adds retention policy, legal hold, integrity
  manifests, and scoped evidence export.
- **Emergency control:** Retryable durable operations coordinate Agent
  disablement, grant revocation, session termination, pool release, task
  cancellation, and credential-rotation boundaries. Partial failures remain
  visible as explicit operation state.
- **Community boundary:** Community retains registered identities, the basic
  Agent inventory, and lifecycle visibility. Resource policy, multi-party
  approval, governance audit, and evidence export remain Enterprise-only;
  Enterprise modules and governance SQL are physically absent from Community
  packages.
- **Chuanxu product UI:** All 17 product pages use local brand assets, a light
  gray first-run theme, Chinese as the initial UI language, persistent language
  and theme preferences, a compact Dashboard layout, and offline icon assets.
- **Enterprise page consistency:** Approval and Audit now share the Enterprise
  navigation divider, labels, language controls, and row-detail behavior.
  Expandable lists identify row-level detail access, while Audit no longer
  carries a redundant detail column. The platform identity is located in the
  sidebar brand area; graph labels use theme-aware contrast; and common status
  and type values expose bilingual filters. Legal hold explicitly supports
  audit-ID, resource-ID, and global scope. Dynamic status, action, decision,
  audit-level, resource, emergency-step, Skill, Agent, Workspace, Spec, Branch,
  Collaboration, and Loop values are localized only in the display layer;
  stored/API enum values, identifiers, and raw audit evidence remain unchanged.
- **Release consistency:** Generated packages retain only
  `RELEASE_NOTES_v4.1.0.md` for the current release. Version, database,
  edition, and license labels are generated from package metadata.

## Database Adaptation

The governance object model, state machines, and API decision contract remain
consistent across the supported adapters. Each adapter implements table types,
indexes, transaction locking, and security controls with the native features
of its selected database. v4.1.0 does not add another database adapter.

## Deployment

For a clean deployment, run `1_schema.sql`, `7_v4_0_1_migration.sql`,
`2_api.sql`, `3_jobs.sql`, `4_harness_templates.sql`, and
`8_v4_1_0_registration.sql`. Enterprise deployments additionally run
`8_v4_1_0_governance.sql` and the adapter's Enterprise security scripts.

Existing v4.0.1 deployments use `migration_runner.py` to apply the v4.1.0
governance migration with the verified migration ledger.

## Compatibility Boundaries

- Deployment remains scoped to private-network, single-tenant environments.
  Public Internet exposure and shared-database tenant isolation are excluded.
- Model selection, model-output correctness, and exactly-once guarantees for
  external side effects are outside the v4.1.0 contract.
- Audit does not store complete sensitive request and response payloads by
  default.
