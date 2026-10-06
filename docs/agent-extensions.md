# Agent extensions — Chuanxu v4.5.2

This guide applies to both editions. Database entities retain identity,
authorization, exact revisions, source lineage, attempts, leases and audit facts.
An integration setting does not grant permissions. Install the complete additive
migration chain through 99 and verify deployment before starting the new workers.
The package's generated baseline manifest determines the actual migration list.

## Model support and answer quality

In Dashboard **Platform → Agent extensions**, select an existing Provider Profile
and run each capability probe independently. Text, streaming, structured output,
Tool proposals, reasoning parameters, usage, image input and client cancellation
are bound to the exact profile revision. Approve supported parameters only from
the matching probe; changing the profile requires new evidence. Hidden Provider
reasoning is never used as the visible answer. Client cancellation records local
stream closure separately from Provider-confirmed cancellation.

Portal and Channels share knowledge retrieval and answer preparation. General
model answers and partial knowledge supplements carry their own source labels.
Ambiguous vendor/company/database questions request clarification. Answer-quality
cases and results preserve the entry kind, case/profile revision, policy digest
and authorized citations. A result cannot be carried over to a changed profile.

## Tools, Skills and context

Use the directory to search authorized Tool/Skill metadata, then load the selected
exact version and content digest. Search results contain no execution grant.
Use `GET /api/agent-extensions/directory` and `POST .../directory/load` for the
authenticated API workflow. Skill text and Tool schemas load only after current
domain, credential and resource checks.

Use the context budget operation before deriving an existing continuity assembly.
The conservative UTF-8 upper bound reserves output and instructions. Extractive
derivations retain constraints, decisions and incomplete work verbatim; a budget
too small for those obligations is rejected. Reading a derivation rechecks every
original source, digest, domain and assembly expiry.

## Graph operations

The SLO view supports authorized cursor pagination and status filters. Manifest
preview validates size, depth, schemas and known executors, and returns a preview
digest. Import that exact preview to create a draft; it does not publish or run it.
A checkpoint fork requires the exact current checkpoint, reason and idempotency
key. It preserves lineage and budgets; uncertain external effects require review.

Offline replay reconstructs committed state and compares event/checkpoint hashes.
Migration preflight compares exact source/target versions, stable node mappings,
pending nodes, leases, schemas, budgets and compensation requirements. Both return
diagnostics without dispatching an executor or changing an active Run.

## Registered integrations

Register each endpoint with its Security Domain, protocol, exact version, bounded
timeout/response size and reason. Use HTTPS and dedicated credentials for remote
services. Credential values are encrypted; discovery, execution and revocation
recheck current domain authority. Protocol and SDK versions are separate facts.

| Integration | Supported workflow |
|---|---|
| MCP | Streamable HTTP 2025-06-18 / 2025-11-25; bounded paginated discovery, independent approval of an exact read-only Tool/schema, authenticated calls, cancellation and uncertain-send reconciliation. |
| A2A | Bounded HTTP JSON 1.0.1 tasks bound to an authorized Graph Version and compiled Plan; submit, inspect, page, resume and cancel with durable task/run mapping. |
| OTLP | Registered OTLP/HTTP JSON 1.9.0 collector; committed trace metadata only, durable delivery attempts, bounded retries and collector receipts. Prompts and output bodies are excluded. |
| Framework | LangGraph 1.2.12 only, using the packaged hash-pinned wheel closure and verified immutable Linux rootfs. Outcomes require independently observed isolated-worker evidence. |

MCP discovery never approves execution. A newly observed contract closes existing
approval; approve it again after review. Uncertain sends are reconciled rather than
automatically repeated. The A2A entry preserves original credentials and Graph
authorization; DB4A2A remains a separate database dispatch mechanism.

Start `scripts/agent_integration_worker.py` under the operator's service manager
to deliver registered telemetry and reconcile uncertain calls. Prepare a new
framework rootfs with `scripts/prepare_framework_rootfs.py --rootfs
/var/lib/chuanxu/framework-v4.5.2`, then configure its verified Linux
sandbox target. The framework receives bounded messages; platform entities remain
the source of execution and authorization facts. Generic framework execution,
live effect replay, live migration and global autonomy remain disabled.

## Managed inputs, progress and diagnosis

Upload an owned image or document in an authorized Security Domain. The bounded
parser accepts PNG/JPEG, UTF-8 plain text/Markdown and text-extractable PDF; the upload
limit is 4 MiB. Images additionally require a current verified `IMAGE_INPUT` probe.
Queries use the authorized active model and store input/output digests and status.
Revocation prevents subsequent reads/use. Documents are untrusted data, not Tool
instructions or grants; scanned PDF OCR and arbitrary audio/video are unsupported.

Execution progress exposes durable state, queue/first-token latency and cancellation
outcome. Read-only diagnostics run only on an explicit request and store redacted
results for capability, Agent or Provider checks. They never repair configuration
or trigger global autonomous actions. Keep the distinction between `FAILED`,
`CANCELLED` and `UNOBSERVED` when a remote outcome has not been confirmed.
