# Model Usage Gateway And Executive Wallboard - v4.4.10

## Purpose And Boundary

v4.4.10 adds an optional platform forwarding path for model calls and a
login-protected, read-only management wallboard. The gateway is not mandatory:
an LLM Provider Profile may allow direct mode, platform-gateway mode, or both.
Gateway evidence improves Token and cost attribution but does not prove that no
direct calls occurred. Direct traffic is unknown unless a verified adapter
reports it.

Gateway and Compliance Agent evidence never grants authority. Identity,
Security Domain membership, provider/model allowance, and platform operations
remain subject to their existing database-authoritative controls.

## Configure Model Routing

1. Open **Platform Configuration**, then **Platform Runtime** and the LLM
   Provider Profile section.
2. Save and probe the Provider Profile before using it for forwarding.
3. Select **Direct**, **Platform Gateway**, or both on the profile row.
4. Select **Confirm change** and enter the compliance reason.

The confirm action remains disabled until the row differs from its saved state.
The forwarding address is read-only and is produced by the platform:

```text
<platform-public-base>/api/model-gateway/completions
```

When a reverse proxy, public DNS name, or HTTPS terminator changes the address
seen by the application, configure the externally reachable base URL before
starting the service:

```bash
export CX_PUBLIC_BASE_URL="https://platform.example.com"
```

Do not include the completion path in `CX_PUBLIC_BASE_URL`. The platform appends
it. A client cannot replace this address through the routing API.

## Usage And Cost Facts

For successful provider responses the ledger records the provider/model,
Principal and optional Agent, prompt/completion/cached/reasoning/total Token
dimensions when supplied, provenance, fixed-precision cost, currency, pricing
version, status, latency, and bounded correlation identifiers. Missing terminal
usage is labeled `INCOMPLETE`; it is not silently estimated as provider truth.

Prompts, model responses, provider authorization headers, plaintext provider
keys, plaintext gateway credentials, and unrestricted provider payloads are not
stored in the usage ledger. Pricing is effective-dated. The displayed cost is a
platform calculation from the matching pricing record, not a provider invoice.

## Quota, Replay, Finance, And External Evidence

Enterprise administrators can define effective-dated Token or monetary quota
policies for global, Human, Agent, credential, Provider Profile, model,
organization, Security Domain, or cost-center scope. `HARD` policies reserve
capacity atomically and reject before Provider dispatch. `WARN` policies retain
the warning and continue. Completion settles the reservation; interruption uses
the selected release or charge-reserved policy; abandoned reservations expire.

Successful non-streaming responses may be replayed for the same actor,
idempotency key, and input digest. The bounded snapshot is AES-GCM encrypted.
The snapshot and terminal request status commit in one transaction, and a retry
never dispatches the Provider again. Prompts are not copied into the snapshot.

Provider invoices are separate from platform-calculated cost. Imports are
digest-bound and idempotent; invoice corrections and reconciliations are
append-only facts. Enterprise allocation rules are effective-dated and must
total exactly 100 percent. Allocation facts are immutable, idempotent, and
balanced to the source line or usage amount. Community returns an explicit
entitlement error for chargeback operations.

Trusted external adapters use Ed25519 public keys, versioned rotation, explicit
revocation, bounded scopes, ordered sequence numbers, and nonce replay
protection. Verified facts use `EXTERNALLY_VERIFIED` provenance. This does not
make calls outside the gateway automatically observable: activity without
gateway facts or signed adapter evidence remains unknown.

## Executive Wallboard

`/app/wallboard` requires a normal authenticated session and authorized read
scope. It shows:

- total, online, busy, and stalled Agents;
- active Sessions, running Task Plans, and running Loops;
- 14-day Token consumption and cost curves;
- bounded provider/model usage and provenance;
- gateway coverage, generation time, freshness, and stale/error states.

Total, online, and busy use the same authorized `AGENT_REGISTRY` population.
The API may also return `native_total` and `native_active` as a platform-native
breakdown; those values are not the overall Agent total.

Organization-scoped definitions resolve an Agent through its active primary
Human owner and that Human's current organization membership/closure. Do not
create an organization-person membership for an Agent Principal. If the runtime
aggregate cannot be queried, the response uses `partial=true`,
`freshness=DEGRADED`, `sources.runtime.status=UNAVAILABLE`, and null runtime
values. Only a successful query may report zero as current data.

When an Agent creates knowledge, the same current relationship facts are
captured in `CX_KNOWLEDGE_CONTEXTS`: one upward organization chain, governed
responsible groups, legacy execution groups, selected sharing scope, and a
snapshot digest. The Knowledge Graph projection exposes these as context
nodes/edges for explanation. They are provenance and navigation facts only;
Security Domain and organization policy checks remain the authorization
boundary.

The wallboard does not acknowledge notifications, approve work, export data,
test providers, invoke Agents, save preferences, or change configuration. Its
data route is GET-only. On authorization loss, protected values must no longer
remain available as an interactive view.

Administrators configure wallboards on the management surface. Widgets,
dimensions, layouts, refresh intervals, and scope selectors use allowlists.
Definition versions are immutable; publish and rollback append governed
publication facts. The viewer can read only the currently published authorized
version and contains no mutation controls.

Every v4.4.10 API error exposes `code`, `message`, `correlation_id`, and
`retryable`; the same correlation identifier is returned in
`X-Correlation-ID`. Clients must not infer retryability from message text.

## Operations And Troubleshooting

- Run `scripts/tools/seed_v410_enterprise_demo_data.py` only in an approved
  Enterprise demonstration or release-test database when representative data
  is needed. It is idempotent and aligns Agent identity, ownership, registry,
  Sessions, Plans, and Loops; do not run it in a customer production database.
- A dash in runtime cards with a partial/degraded banner means the runtime
  source failed. It is not equivalent to a current zero.
- An empty curve is valid when no authorized usage exists in the 14-day window.
- `INCOMPLETE` means the provider or stream did not supply terminal usage.
- Direct calls do not appear merely because direct mode is enabled.
- A wrong displayed gateway host usually means `CX_PUBLIC_BASE_URL` is missing
  or the reverse proxy is not forwarding the original scheme and host.
- Provider failures return a bounded error; internal response bodies and
  credentials are not relayed to clients.
- Preserve usage and request rows during rollback or routing disablement so
  accounting and audit evidence remain internally consistent.

v4.4.10 is the fresh-deployment baseline. Historical migration steps remain in
the package for deterministic ordering, checksum evidence, and source audit;
they are not a promise of in-place customer upgrades from an earlier v4.4.x
package. v4.4.8 is withdrawn and must not be used as a source.
