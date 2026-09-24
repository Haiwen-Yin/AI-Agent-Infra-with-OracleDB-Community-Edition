# Work continuity operations v4.4.16

[完整中文说明](continuity-operations_zh.md)

The shared Dashboard/Portal diagnostics panel shows available source contracts
and observed database-server version metadata. Hidden version metadata is
reported as unavailable without widening database privileges. The form can
also check a named instance, assembly input receipt or Skill distribution;
cross-entrypoint parity remains unobserved without independent evidence.
Worker failures retain bounded categories such as `LLM_REQUEST_TIMEOUT`,
`LLM_EMPTY_RESPONSE` and `LLM_HTTP_503`, without recording provider bodies or
credentials in the failure reason.

Public Agent token exchange accepts `workspaces.read` and `workspaces.write`
for continuity reads and writes. Scope selection does not grant domain or
resource access. For signed upgrade and Skill package preparation, see
[release signing](release-signing.md).

## Installation and authority

The current implementation uses migrations 86 through 88 for 45 relational continuity
tables. Deploy the release-bound migration chain, including
`86_v4_4_15_continuity_entities.schema.json` and
`87_v4_4_15_continuity_bindings.schema.json` and
`88_v4_4_15_execution_links.schema.json` verification manifests. The
deployment verifier checks columns, defaults, constraints, immutable-history
triggers and native grants. An APPLIED ledger entry alone is insufficient.

The current v4.4.16 deployment terminal is migration 97 on all three databases.
Migrations 95 and 96 add three immutable relations for native executions,
context input attempts and original Gateway credentials. Keep both SQL files
and schema manifests. Install them before starting the context-aware Worker.

Migration 97 adds seven typed immutable relations for exact native source
snapshots. The Work continuity page can capture TASK (plan and steps), GRAPH
(run and node progress), DB4A2A (dispatch contract), or AUDIT (the caller's own
security-event summary). It adds the returned version reference to the selected
sources. Each capture includes its UTC time and digest; it does not claim the
original execution is still in that state. Original-object deletion, ownership
changes or current permission loss block later reads without erasing history.
Snapshots stay in their original Security Domain. Arbitrary workspace bodies
and Enterprise audit payloads are not included. Capture is bounded to 1000 child
records and 256 KiB including metadata.

Use `POST .../context/native-sources` with `family`, `entity_id`,
`security_domain_id`, `reason`, and `idempotency_key`, under the same Dashboard,
Portal or Gateway prefixes as runtime execution. MCP/CLI uses
`context_native_capture`. The caller needs workspace write and the original
source's read permission; DB4A2A requires sender/recipient responsibility and
AUDIT requires ownership of the security event plus `audit.read`. A reference
does not grant the target Agent permission to consume it.

`POST /api/context/runtime-executions` (Dashboard),
`POST /portal/api/continuity/context/runtime-executions` (Portal), and
`POST /api/agent-gateway/continuity/context/runtime-executions` (Agent) enqueue
an explicit native Agent execution and prepare its context in one transaction.
The MCP/CLI operation is `context_runtime_enqueue`. Submit `agent_id`,
`messages`, an assembly request in `context`, `reason`, and `idempotency_key`.
The requester needs current `agents.operate` and workspace write authority;
the target Agent must be active and authorized to read the domain and sources.
Gateway bearers additionally need the `agents.operate` scope. An enqueue
receipt means PENDING, not model completion. The Worker records the actual
input receipt and its own claim fence before sending. An expired or revoked
original credential blocks dispatch even if a new token is issued. An uncertain
send after Worker loss becomes UNOBSERVED and is not automatically repeated.
The Dashboard and Portal Work continuity pages provide the same execution
form: load available native Agents, select one, describe the task and purpose,
then submit and refresh the result. The selected Work and explicitly entered
sources use a 15-minute assembly lifetime. Both the requester and target Agent
must retain source read authority, including when reading a source-derived
result. Results become unavailable when the assembly expires. The read endpoint
is `GET .../context/runtime-executions/{execution_id}`; Agent inventory is
`GET .../context/runtime-agents?security_domain_id=...`, with cursor pagination.
MCP/CLI operations are `context_runtime_read` and `context_runtime_agents`.
Migrations 89–93 protect dynamic MCP exposure; they do
not change the count of continuity tables. In the Tool details panel, an
authorized operator explicitly exposes or revokes an active tool, with a reason.
Independent Agents discover only active exposed contracts through the read-only
CX_MCP_EXPOSED_TOOLS view. Native SQL cannot expose a tool or change/delete an
exposed contract. Reimport or refresh closes exposure until another explicit
decision. A cached tool name is rechecked before queuing an approval-gated call;
discovery does not constitute execution approval.

Migration 94 adds the immutable `CX_WORK_HANDOFF_POLICIES` relation, bringing
the continuity table count to 46. Retain its SQL and schema manifest alongside
the earlier manifests. Every Work revision has an exact policy; historical
revisions default to serial capacity one. Migration 86 accepts only the
checksum-verified, APPLIED migration-94 successor for the retired serial key.
If a journaled migration-94 attempt is interrupted, deployment resumes that
exact successor before verifying the old constraint, provided migrations 85–93
have matching APPLIED checksums (92 is YashanDB-only). The entire chain is then
verified again. A changed migration or incomplete prerequisite blocks recovery.
Do not run an older continuity writer after the policy backfill: it cannot
create policy rows for new Work revisions. Runtime cutover must drain those
writers and verify policy coverage before enabling the replacement.

## Cooperative Skill installation and switching

For a Linux Agent that explicitly uses the managed turn wrapper, run
`python scripts/tools/skill_runtime.py --root <private-runtime-dir> --public-key-file <operator-pinned-key> sync --upgrade-id <assigned-upgrade> --database <oracle|pg|yashandb> --edition <community|enterprise>`.
Configure `CX_AGENT_GATEWAY_URL` with the `/api/agent-gateway` base path,
`AI_AGENT_ID`, `CX_AGENT_INSTANCE_ID`, and `CX_AGENT_ACCESS_TOKEN` through the
Agent's private environment. The public key is a separately trusted URL-safe
Base64 Ed25519 key; never take it from the downloaded package.

The client downloads the assigned signed archive, verifies all bytes, installs
plain files in a dedicated private directory, and rechecks current server trust
before switching. It acknowledges receipt separately from activation. An active
managed turn returns `RUNTIME_BUSY`; retry after that turn finishes. The atomic
active pointer always identifies a complete installation. Previous versions
remain available; no automatic deletion or rollback is performed. A failed
final acknowledgement reports `LOCAL_ACTIVE_SERVER_ACK_PENDING`; repeat the
same sync command to reconcile the exact local version with the server.

Run each complete Agent turn through
`python scripts/tools/skill_runtime.py --root <private-runtime-dir> --public-key-file <operator-pinned-key> run -- <your-agent-command>`.
The command must read `CX_ACTIVE_SKILL_PATH` and keep the turn within that
process lifetime, without detaching a background runtime. The shared lock is
inherited by the launched process, so wrapper failure cannot unlock a live
turn. `status` verifies the current installed bytes and reports their digest.
Verification reads the full retained archive and installed files; budget disk
space for the archive and extracted files of each retained version.

This adapter coordinates participating local processes; it does not isolate
processes that bypass it. Local verification is labeled
`LOCAL_COOPERATIVE_RUNTIME`. The server's Skill delivery diagnostic remains
`UNOBSERVED` for external process activation, since the server cannot independently
observe an arbitrary external runtime's switch.

## Serial and parallel handoffs

In either Dashboard or Portal, the current Work owner can set **Handoff policy**
with a maximum of 1–16 active recipients and a reason. Capacity one transfers
responsibility on acceptance. Capacities 2–16 retain the coordinator and allow
recipients to accept, start execution and submit outcomes independently.
Start execution before reporting a completed outcome. Duplicate active
recipients are rejected. Finish, reject, cancel or expire all active handoffs
before changing policy; the change creates a new immutable Work revision.

HTTP uses `POST /api/work-contracts/{work_id}/handoff-policy`; Portal and Agent
Gateway use their existing continuity prefixes. MCP/CLI operation
`work_handoff_policy` takes a `request` containing `work_id`, `expected_version`,
`max_active_recipients`, `reason` and `idempotency_key`. Current owner, domain and
resource authorization still apply. Stale versions and active handoffs return
conflicts. Read an earlier Work revision to inspect its original policy.

Dynamic MCP calls require a Security Domain, an arguments object, a reason and
an idempotency key. Configure the same instance-bound Gateway transport used by
continuity calls. The bearer needs actions.propose; the Agent also needs current
workspace-read, tool-read and proposal permissions in that domain. Migration 93
adds a separate immutable Tool-request relation to the existing execution queue.
Calls remain WAITING_APPROVAL. Before dispatch the Worker rechecks its lease,
the original Agent credential/instance, current domain permissions, exposure,
contract digest and queued payload digest. Expired or revoked authority requires
a new authorized proposal; it is not automatically revived by later approval.

Agent SQL logins cannot read or write these control-plane tables directly.
Use the authenticated HTTP Gateway, MCP tool or CLI. Each operation checks
current principal, domain and resource authority. Instance leases, token
scopes, revocation and fencing apply at the Gateway. Restoring a domain does
not revive credentials revoked during containment.

Dashboard HTTP routes use the existing session and CSRF controls. Portal
uses its own session under `/portal/api/continuity`; mutations also require
the current exclusive page lease. Neither a Dashboard session nor another
page's lease can substitute for these controls. Agent
routes have the base path `/api/agent-gateway/continuity`. Reading a locator
or possessing another participant's identifiers never grants access.

## Configure an Agent client

Supply these environment variables through the existing private runtime
configuration; do not place secrets in command arguments or project files:

| Variable | Value |
| --- | --- |
| `AI_AGENT_ID` | Registered Agent ID (`MCP_AGENT_ID` is a fallback) |
| `CX_CONTINUITY_GATEWAY_URL` | Full Gateway group URL, such as `http://127.0.0.1:8000/api/agent-gateway/continuity` |
| `CX_AGENT_INSTANCE_ID` | Current active instance belonging to that Agent |
| `CX_AGENT_ACCESS_TOKEN` | Current instance-bound Gateway bearer token with the required workspace scopes |

MCP additionally requires the existing registration credential in
`AI_AGENT_TOKEN` (or `MCP_AGENT_TOKEN`) and `continuity` in
`mcp.exposed_tools`. A registration credential is not a Gateway bearer token.
Existing configurations that explicitly list tools must add the tool to
enable it. The MCP tool accepts the typed operation envelope below; identity
and Gateway URL overrides in tool arguments are rejected.

## CLI checks

Run from the generated package with its Python environment:

```bash
.venv/bin/python scripts/continuity.py setup --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py doctor --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py capabilities --domain DOMAIN_ID
.venv/bin/python scripts/continuity.py verify-context --domain DOMAIN_ID --assembly-id ASSEMBLY_ID --purpose "Verify actual context input"
```

`setup` checks an existing configuration against the server and persists a
diagnostic run; it does not provision an identity, grant permissions or save
credentials. `doctor` also requests entrypoint parity, which remains
UNOBSERVED until that check has an integrated observation. `capabilities`
reports available contracts in the caller's domain, separately from their
runtime verification. It does not certify database engine versions or all
operations as healthy.

`verify-context` requires an assembly ID and/or `--sources-file`. The source
file is a JSON array of exact references containing `family`, `entity_id`,
`revision_id` and `content_digest`. Sources are reauthorized for the supplied
purpose. An assembly only counts as delivered when the server has a matching
completed model-input receipt. Merely preparing an assembly is UNOBSERVED.

Diagnostic commands exit 0 only for PASS. FAIL, UNAVAILABLE and UNOBSERVED
exit 1 and retain their distinct JSON status. Client errors return sanitized
codes without remote driver details. Clients do not follow redirects or
automatically replay requests after uncertain delivery.

## Typed operations

Use `call --request-file request.json`, or pipe a JSON envelope to `call`.
For example, an exact Work revision read is:

```json
{"operation":"work_read","request":{"work_id":"WORK_ID","revision":2}}
```

Available operations cover Work creation/revision/status; Handoff offer,
read/revision/decision; outcome submission/read; context assembly/read;
typed candidate creation/revision/review/promotion; artifact retirement;
publication/revocation; and diagnostics. The authenticated capabilities
response lists operation names; MCP discovery provides the full typed schema.
Mutations require a reason and an idempotency key, and versioned updates
require the expected version. Reusing a key with changed content is a conflict.

## Current delivery boundary

Dashboard's Workspaces page has a Work continuity view, and the Portal toolbar
links to `/portal/continuity`. Both reuse the same forms and server authority
for Work creation and
revision, Handoff offers and responses, outcome submission and explicit
experience proposals, and persisted diagnostics. Domain and recipient choices
use current work permissions and memberships, without requiring channel access.
Metadata lists are paginated and do not expose source bodies.

Work and Handoff history appear in separate read-only previews, without
replacing the current edit. A sender may revise an unexpired offered Handoff.
The form shows the Work revision and acceptance criteria it will link, and
submission checks the observed Work version, Handoff version and body revision.
Concurrent changes produce a conflict rather than silently selecting new work.

Candidate review provides typed Memory, Knowledge, Experience and Skill forms.
Every source requires its entity ID, exact revision and SHA-256 digest. A
replacement may explicitly identify an existing formal revision. Saving keeps
the candidate pending; the proposer can revise it before review. An independent
reviewer approves or rejects the observed version and digest, then explicitly
creates a formal revision. Self-review and self-promotion are rejected.
Historical previews remain read-only; promotion displays the formal entity and
revision IDs. Candidate inventories expose metadata only to proposers or
currently authorized family reviewers who administer the domain. Body reads
still reauthorize every exact source.

Work creation accepts optional `workspace_id`, `task_id` and `graph_run_id`.
Immutable typed links retain the native locator and original responsible
principal, with foreign keys to the Work and Principal records. Every use
reauthorizes the original resource and current domain membership. Task status
is deliberately excluded from the link key; status changes do not block.
Resource deletion, revoked access or changed responsibility invalidate use of
the link without deleting its history. A link is not a captured Task or Graph
content revision and does not itself implement those exact source resolvers.

Handoff evidence pins its original publication grant. Revocation cannot be
bypassed by an equivalent new grant. Bound recipient operations check the actual
Gateway instance and fencing token. Replacement instances keep the same Agent
principal; credential history stores token digests only.

`outcome_propose_experience` requires the observed `expected_outcome_id` and
`expected_digest`, a typed Experience proposal, reason and idempotency key.
It creates a PENDING candidate with an exact HANDOFF_OUTCOME source; it never
automatically promotes knowledge. The independent reviewer must currently be
authorized to read that outcome and its evidence. Outcome sources remain within
their original domain and participants; cross-domain publication is unavailable.

Exact sources include Memory, Handoff and Handoff Outcome, plus Knowledge,
Experience and Skill created through the candidate promotion flow. Task, Graph,
DB4A2A and own security events use migration 97 native snapshots: explicitly
capture a version before use, rather than treating current state as history.
Executions bind the original Gateway credential, source-authority intersection
and input receipt. Parallel handoff policy, Dashboard / Portal, HTTP / MCP / CLI
and the cooperative Skill client are part of this version's delivery scope.
Capability discovery grants no permission over individual records; consult the
selected release package's acceptance records for verified behavior.
