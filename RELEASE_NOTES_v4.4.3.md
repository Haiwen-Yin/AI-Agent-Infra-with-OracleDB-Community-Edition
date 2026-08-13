# AI Agent Infra with DB v4.4.3

## Governed Security Domains

- Adds Security Domain inventory, accountable ownership, purpose,
  classification, lifecycle, explicit Human/Agent membership, validity, and
  reasoned audit records.
- Treats `CX_SECURITY_DOMAINS` and `CX_DOMAIN_MEMBERS` as the only
  authorization facts for project collaboration. A Channel, message, prompt,
  thread, workspace, graph relationship, Skill, Tool, API declaration, or
  collaboration-group record does not grant access.
- Rechecks active Domain membership at Channel listing, history read, message
  and thread access, Gateway delivery, and Channel member admission. Expiry,
  suspension, or revocation fails closed while retained evidence stays under
  the applicable authorization and retention policy.

## Channel And Collaboration Group Binding

- Normal Channel creation selects an accessible active Security Domain and
  records an atomic Channel binding. `DEFAULT` remains a bootstrap or
  constrained proof-of-concept boundary and is not an implicit production
  selection.
- Ensures built-in management Agents are explicitly admitted to the protected
  administration Channel's Security Domain during initialization. Explicit
  `@` mentions are dispatched through the managed runtime and write one
  auditable Markdown response back to the Channel; opening a Channel starts
  from its latest activity.
- Adds auditable legacy collaboration-group bindings. One group may have at
  most one active Security Domain binding in this release, avoiding ambiguous
  multi-domain union or intersection semantics.
- Adds controlled conversion drafts for existing groups. Active group Agents
  are candidates only; `SHARING_POLICY` is retained solely as review context.
  The platform writes no new Domain membership until an authorized operator
  confirms each candidate and applies the draft with a confirmed accountable
  Human owner.

## Compatibility And Validation

- Adds additive migration `39_v4_4_3_security_domain_binding.sql` for Oracle
  AI Database 26ai, PostgreSQL 18 with Apache AGE, and YashanDB 23.5.4.
  Existing Domains, Channels, groups, workspaces, messages, SDD records, and
  audit history are retained.
- Requires Python 3.14 or later.
- The release package contains only `RELEASE_NOTES_v4.4.3.md`.
