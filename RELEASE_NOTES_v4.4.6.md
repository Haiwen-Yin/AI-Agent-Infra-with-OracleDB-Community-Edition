# AI Agent Infra with DB v4.4.6

Release date: 2026-08-16

## Highlights

v4.4.6 adds a database-authoritative Human registration contract. Display
name, email, and mobile fields are normalized and validated under versioned
`REQUIRED`, `OPTIONAL`, or `DISABLED` policies. Portal and Dashboard direct
users to one independent registration surface. Existing active identities are
preserved during the additive migration.

Administrators can require purpose-separated, one-use Human Registration
Tokens. Only a keyed digest is persisted; the raw Token is returned once at
issue time. Expiry, revocation, replay prevention, authorization, and audit
boundaries are independent from Agent Enrollment Tokens.

Portal admission now has a database-backed per-user connection limit and one
exclusive operation-page lease per Session. A copied or reused Session can be
rendered for inspection but cannot perform mutations while another page owns
the current lease. Dashboard Sessions remain independently scoped.

The release adds a provider-neutral external identity transaction contract for
future WeCom, DingTalk, Feishu, OIDC, and customer-specific adapters. Provider
claims are identity evidence only: they do not grant roles, entry access,
organization membership, Security Domain access, or automatic email/mobile
account linking. Unvalidated provider adapters remain unavailable.

Graph Engineering capabilities expose explicit `PRODUCTION`, `CONTROLLED`,
`DISABLED`, or `UNAVAILABLE` posture. Protocol metadata, Agent Cards, MCP
descriptions, Skills, and prompts are never authorization boundaries. A
capability is not labeled Production without current database, edition,
security, and release-package evidence.

Equivalent additive migrations `46_v4_4_6_identity_portal_graph.sql` and
`47_v4_4_6_portable_contract_alignment.sql` are provided for Oracle,
PostgreSQL, and YashanDB. The second step preserves an immutable migration
ledger while aligning PostgreSQL physical names with the common runtime
contract.

