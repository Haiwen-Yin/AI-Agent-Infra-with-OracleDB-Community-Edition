# Framework-Neutral Agent Gateway Adapter - AI Agent Infra with DB v4.3.1

`shared/lib/agent_framework_adapters.py` is a pure conversion boundary for
external runtimes such as OpenClaw and Hermes Agent. It does not implement a
second Channel, Barrier, Action, identity, or execution engine. It only builds
the existing Gateway route descriptors and validates the responses returned by
those routes.

The adapter is stateless. It performs no database, filesystem, environment, or
network operation and stores no credential, token, event, or framework client
object. The `OpenClawGatewayAdapter` and `HermesGatewayAdapter` classes are
small facades over the same `FrameworkGatewayAdapter` contract; they do not
change authorization behavior.

## Trust Boundary

The Gateway, rather than the framework payload, is the authority for identity:

- Enrollment binds a new Agent through a one-time user-issued Enrollment Token.
- Instance creation resolves the Agent from the authenticated bearer-token
  context. The instance request intentionally has no `agent_id` field.
- Pull, acknowledgement, Barrier Arrival, and Action calls resolve Agent and
  Instance from the access-token context. Their request bodies contain no
  client-supplied Agent or Instance identity.
- Response validators require the caller to provide the Agent, Instance,
  delivery, Barrier, or Channel identity it already trusts. A response that
  does not match that binding is rejected before it is handed to a framework.
- Identity claims in an incoming framework message or acknowledgement are
  validated when present, but discarded from the Gateway body. They are never
  an authorization input.

An ordinary Channel message is not an Action, and a message that resembles an
Arrival Report does not change a Barrier. Structured Arrival and Action
requests must use their dedicated operations below.

## Request Descriptor

Each `build_*_request` function returns a transport-neutral descriptor:

```json
{
  "schema": "agent-gateway/1",
  "method": "POST",
  "path": "/api/gateway/events/claim",
  "query": {"limit": 50},
  "body": {}
}
```

`body` is the exact JSON body for the existing HTTP route. An MCP or Skill
client can use the same body and operation mapping without depending on a
Python web client. `schema` is adapter metadata and is not a database command.

## Operations

| Adapter function | Existing route | Boundary |
|---|---|---|
| `build_registration_request` | `POST /api/enrollment/redeem` | One-time Enrollment Token; optional public key; no client secret input |
| `build_token_request` | `POST /api/gateway/token` | One-time compatibility secret or Ed25519 proof; returns an instance-scoped token |
| `build_instance_request` | `POST /api/gateway/instances` | Channel or Security Domain binding; Agent comes from bearer context |
| `build_pull_request` | `POST /api/gateway/events/claim` | Bounded pull limit; the server selects eligible leased deliveries |
| `build_ack_request` | `POST /api/gateway/events/{delivery_id}/ack` | Claim token, success flag, and optional failure reason |
| `build_arrival_request` | `POST /api/gateway/barriers/{barrier_id}/arrivals` | Structured report, participant role, and required idempotency key |
| `build_action_request` | `POST /api/gateway/channels/{channel_id}/actions` | Structured proposal, reason, and required idempotency key |

The matching `validate_*_response` functions reject unknown fields, malformed
IDs, inconsistent counts, non-success transport status, identity mismatches,
non-finite JSON, and invalid state/digest values. Pull responses are converted
to framework envelopes with lease metadata hidden; the claim token is retained
only in the acknowledgement envelope needed for that delivery.

## Credential Handling

The Gateway never gives an external runtime a database or Schema Owner
credential. A compatibility client secret may be returned by registration once
when the deployment policy uses `CLIENT_SECRET`; an Ed25519 registration has
no returned client secret. A caller must use that value only for the token
exchange and remove it from its own memory according to its runtime policy.

The adapter does not write or cache that value. It rejects credential-like
fields in event, message, Arrival, and Action JSON, including passwords, API
keys, access/refresh tokens, private keys, and secret digests. `claim_token` and
the short-lived `access_token` are allowed only in the dedicated transient
request/response positions required by the Gateway contract.

## Compatibility Evidence

The corresponding unit suite is
`shared/tests/test_agent_framework_adapters.py`. It covers the common contract
for generic, OpenClaw, and Hermes labels, request construction, response
binding, identity-claim rejection, credential-field rejection, structured JSON
validation, and failure cases. These tests verify the adapter boundary only;
they are not a claim that a particular OpenClaw or Hermes release has passed a
live end-to-end test against a deployed database.
