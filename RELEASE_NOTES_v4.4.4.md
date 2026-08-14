# v4.4.4 Release Notes

## Product

v4.4.4 extends Chuanxu (川序) as a governed AI Agent management platform
with Portal Agent Pool model governance and basic cloud demonstration
environment management.

## Highlights

- Portal Agent Pool now uses an administrator-defined default LLM and an
  explicit allowlist. Portal users can switch only among healthy allowlisted
  profiles; provider secrets are never returned to the Portal.
- The Platform Administration Channel stores typed read commands and governed
  mutation proposals with scope, reason, expiry, approval state, and audit
  evidence. Chat text is not an authorization or SQL execution boundary.
- Added managed-node inventory for Admin, Compliance, and Agent Pool roles.
  Mutual SSH trust and bounded one-use validation are supported without
  persisting reusable SSH passwords.
- Added shared-storage profiles. Local directories and mount points are the
  first executable backend; NFS, object storage, and unified storage are
  explicit adapter states rather than misleading ready states.
- Added external-Agent database endpoint metadata and scoped discovery
  foundations. Endpoint profiles can be bound to an enrollment grant through
  its policy snapshot; expired or unbound Agents retain the initialization
  endpoint fallback, and discovery is rate limited.
- Added native templates for code planning, code programming, code review,
  Office text, and presentation design. General-purpose templates can be
  exposed as bounded Portal enhancement components after authorization.
- Added explicit `/platform` Administration Channel commands. Read commands
  return credential-free control-plane results; mutation commands create
  governed Action Cards and cannot be executed by chat text or model output.
- Added bounded managed-node reachability and local shared-storage validation
  actions with localized result feedback.
- Added a dedicated Agent Pool configuration page, fixed globally stretched
  checkbox and multiline-field controls, and added the additive node-storage
  binding migration. Admin Agent runtime shared directories are now explicitly
  bound to a managed node and role scope with an audited mount reference.

## Security boundaries

Database identity, authorization, Security Domains, approval, containment, and
audit remain authoritative. LLM output, prompts, Skills, shared storage, and
Channel membership do not grant access independently.

## Compatibility

The release contains additive migrations for Oracle AI Database 26ai,
PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4. Existing v4.4.3 data and
configuration are preserved.
