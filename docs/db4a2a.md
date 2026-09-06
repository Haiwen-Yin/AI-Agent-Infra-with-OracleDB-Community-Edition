# DB4A2A Database-Mediated Collaboration v4.4.12

DB4A2A is the project's reference-oriented Agent collaboration pattern. It is
not a replacement for standard A2A. A2A or Agent Protocol carries discovery,
delegation, status, and small events; the database context plane carries
authorized Knowledge, Memory, Context, Artifact, Graph, and Branch facts.

## Dispatch contract

A dispatch contains `task_id`, `context_ref`, `snapshot_digest`,
`expected_version`, `scope_ref`, and `branch_policy`. It should not copy a
large context into the message. The receiving Agent must authenticate with its
own Principal. Agent Instance, Security Domain, organization, classification,
expiry, fencing, and database policy are independent authorization concerns;
the presence of a reference or digest does not prove they were checked.

Shared context is read-only by default. A permitted write creates a child
Branch whose dispatch records the source reference, snapshot digest and
expected version. For DB-mediated dispatch, version 1 identifies the canonical
JSON digest format, not a mutable row counter. The digest is `sha256:` followed
by SHA-256 of a typed canonical JSON tree encoded with ASCII escaping and no
whitespace separators. Object keys are sorted; arrays preserve order. Numbers
use exact decimal coefficient/exponent normalization, so 1 and 1.00 agree,
without rounding native Oracle Decimal values to floats. Strings, booleans,
nulls, numbers, arrays and objects have distinct tags; non-finite or non-JSON
values are rejected. `context_snapshot()` is the reference encoder. Scope is
`workspace:<workspace_id>`; source branch must match the context row. Creation
and forking validate these facts against the database. The source context is
changed only by a separate governed merge.

When a peer cannot reach the database, standard A2A payload or Artifact
exchange remains the fallback. Agent Cards, protocol metadata, and context
references never grant database, Tool, Skill, Model, or export authority.

## Current verification boundaries

The branch endpoint requires operation permission and sender/receiver
membership before creating a branch or returning an existing branch ID.
Inactive and read-only dispatches are rejected. Failed branch insertions
propagate errors rather than reporting a generated ID as success.

The dispatch branch implementation locks the dispatch and context, verifies
the reference, inserts a native `PARALLEL` branch, links the dispatch and writes
its audit in one transaction. It does not invoke a separately committing
branch procedure. Failures roll back the branch and linkage together. A second
request waits for the dispatch row lock and returns the existing branch after
rechecking the reference. This is not immutable snapshot replay: changed
context is rejected, not reconstructed. Historical envelopes with arbitrary
digests or scopes must be recreated from the stored context.

Participant checks in the service supplement database isolation. Database
owner/control-plane access and restricted external-Agent access require
separate negative tests; service unit tests cannot establish database policy
coverage. Standard A2A interoperability also requires its own protocol tests.

The sender is checked independently: an Agent must read the context using its
own database identity; an active Human must own the workspace or hold
`agents.manage.all`, in addition to operation permission. The original sender
is rechecked on branch retries. Seeing the receiver is not a context grant.

Transactions lock participant principals, the canonical context and, on
YashanDB, existing explicit context grants before independent identity reads.
A share deletion racing an authorized locked operation waits for that operation;
once deletion commits, subsequent branch retries are denied. This is bounded
serialization, not cancellation of already committed branches or previously
read data. Organization, delegation and native privilege changes still require
separate concurrency validation. The current YashanDB context view does not
prove isolation of legacy entity tables or definer-rights packages.

## Expected benefit and boundary

Reference-oriented dispatch can reduce repeated context transfer, input Token
duplication, sensitive-data copies, and version drift for same-platform or
same-tenant Agents. It is not automatically faster for cross-organization
peers, small messages, or database-inaccessible runtimes. Database contention,
snapshot conflicts, and temporary unavailability remain explicit failure modes.
