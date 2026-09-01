# DB4A2A Database-Mediated Collaboration v4.4.11

DB4A2A is the project's reference-oriented Agent collaboration pattern. It is
not a replacement for standard A2A. A2A or Agent Protocol carries discovery,
delegation, status, and small events; the database context plane carries
authorized Knowledge, Memory, Context, Artifact, Graph, and Branch facts.

## Dispatch contract

A dispatch contains `task_id`, `context_ref`, `snapshot_digest`,
`expected_version`, `scope_ref`, and `branch_policy`. It should not copy a
large context into the message. The receiving Agent authenticates with its own
Principal and the platform rechecks Agent Instance, Security Domain,
organization, classification, expiry, fencing, and data policy before every
read.

Shared context is read-only by default. A permitted write creates a child
Branch bound to the source reference, snapshot digest, Graph Version, and
expected version. The source context is changed only by a separate governed
merge.

When a peer cannot reach the database, standard A2A payload or Artifact
exchange remains the fallback. Agent Cards, protocol metadata, and context
references never grant database, Tool, Skill, Model, or export authority.

## Expected benefit and boundary

Reference-oriented dispatch can reduce repeated context transfer, input Token
duplication, sensitive-data copies, and version drift for same-platform or
same-tenant Agents. It is not automatically faster for cross-organization
peers, small messages, or database-inaccessible runtimes. Database contention,
snapshot conflicts, and temporary unavailability remain explicit failure modes.
