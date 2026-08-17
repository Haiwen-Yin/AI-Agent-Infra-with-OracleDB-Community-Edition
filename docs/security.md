# Security - AI Agent Infra with DB v4.4.7

## v4.4.3 Security Domain Boundary

`CX_SECURITY_DOMAINS` and `CX_DOMAIN_MEMBERS` are the authorization facts for
project collaboration. `CX_DOMAIN_GOVERNANCE` records the accountable Human
owner, purpose, classification, reason, and administrative change context.
Channels and legacy `COLLAB_GROUPS` are collaboration surfaces only. A message,
prompt, thread, workspace, graph relation, Skill, Tool, API declaration, or
historic group member never grants or expands Security Domain access.

Production setup is ordered: create a dedicated Security Domain, record its
purpose and classification, confirm the owner and each Human or Agent member,
then create a Channel or bind one legacy collaboration group. `DEFAULT` is
reserved for bootstrap and constrained proof-of-concept use; it is never the
implicit selection for a production project. A legacy group conversion creates
a review draft only. Its active Agents are candidates, `SHARING_POLICY` remains
non-authoritative review context, and only individually confirmed candidates
are inserted atomically when the draft is applied.

Current Domain membership is rechecked at Channel listing, history reads,
message and thread access, Gateway admission, and guarded work operations.
Expired, suspended, or revoked membership fails closed without deleting
historical evidence. One legacy collaboration group has at most one active
Security Domain binding in this initial production contract, so an operator
must use a governed rebinding/migration rather than rely on ambiguous union or
intersection semantics.

## v4.4.1 Platform Administration Boundary

The Platform Administration Channel is not a broadly shared Agent chat room.
Its membership is limited to the protected local administrator, enabled
management identities, and separately approved voting Admin Agents. Business
and unapproved Agents are rejected at Channel, Gateway, and instance
boundaries. Human invitations require an administrator, a reason, expiry, and
audit; self-invitation is denied.

Admin Agent election is database-authoritative. Weights must be positive and
different. Decisions require both a strict member-count majority and a strict
weight majority from one recorded snapshot. Leader terms, leases, and fencing
tokens reject stale recovery or split-brain writes. A single healthy Admin
Agent is usable for bootstrap but is reported as not high-availability-ready;
production recommends three healthy members.

Containment is ordered: observe, drain, quarantine, terminate, and optional
infrastructure terminate. Before quarantine or termination, the platform
revokes the instance and its access tokens. The authenticated Agent may then
acknowledge memory cleanup and stop. Without a configured infrastructure
adapter, the platform reports that remote process termination is not
configured; it never claims an OS process was killed.

Uploaded upgrade packages stay in owner-only staging until manifest, file
digest, edition, and operator signature verification succeeds. Human approval
cannot be supplied by the submitter, and Admin Agent votes are bound to an
authenticated live instance, current term, and fencing token. API keys and
private signing keys are not stored in the management artifact catalog.

## v4.3.7 Bootstrap And Embedding Boundary

The Bootstrap Deployment Agent is an execution mechanism, not a privileged
reasoning Agent. Its manifest is local and checksum-bound; LLM output, prompt
text, remote callbacks, and logs cannot select SQL, commands, privileges, or
deployment state transitions. Pre-control-plane journals are owner-only,
integrity-checked, encrypted where secrets are present, and retain sanitized
evidence only. Oracle/YashanDB infrastructure creation is outside the default
installer and needs explicit operator action.

Embedding API keys are encrypted after protected storage exists and are never
returned by Dashboard APIs, audits, jobs, probes, or support evidence. A
Contract is immutable once published. Every governed vector write and search
checks the effective Space, Contract, dimension, numeric validity, source
mode, and scoped Agent binding. Different Contract versions never enter the
same similarity or multi-modal fusion calculation. `LEGACY_DEFAULT` is
read-only until an authorized migration validates a separate Space and
performs explicit read/write cutover.

## v4.3.6 Native Agent Boundary

Platform Admin and Enterprise Compliance Admin Agents are independent
Principals created by idempotent bootstrap. The human `admin` account manages
them but is not merged with them. Business Agent creation requires a human
request, a different approver, an owner in the authorized scope, a locked
template isolation level, a deployment target, a classification, and a
reason. Activation requires an active LLM Provider Profile and does not grant
any database privilege.

LLM prompts, responses, Skills, Tools, API descriptions, and remote adapter
callbacks are untrusted inputs. Database authorization, Gateway admission,
short-lived credentials, execution isolation, approval, and audit remain the
enforcement boundary. A shared Worker Pool cannot reuse context, workspace,
database session, token, secret reference, or model conversation state across
Agents. Database fencing prevents a stale Worker from completing a reclaimed
execution.

The external registration policy has `ENABLED`, `APPROVAL_ONLY`, and
`DISABLED` states. `DISABLED` rejects new Skill-first enrollment only; existing
external Agents retain their stored lifecycle and can be separately revoked.

## v4.3.5 Capability Boundary

Feature visibility in the Dashboard is not an authorization boundary. The
effective state of a product capability is the conjunction of package
availability, database registry state, and the current Principal's action
permission. Mapped API routes enforce the registry before their handlers run;
disabled pages cannot be reached by calling the API directly.

Capability changes require `platform.manage`, CSRF, an explicit reason, and an
optimistic database version. The state update, immutable history row, and
`CX_SECURITY_EVENTS` record use one transaction so a failed audit write cannot
produce an apparently successful state change. Dependencies are validated in
both directions. Mandatory control-plane capabilities cannot be disabled. No
password, token, private key, or arbitrary configuration secret is stored in
the registry. Cross-Admin Skill tokens use `X-Admin-Token`, not URL query
strings, and Oracle End User names are validated before dynamic DDL.

## v4.3.4 Agent Compliance Boundary

Agent registration, runtime, compliance posture, and control state are
independent database-authoritative facts. A missing Skill invocation, idle or
offline runtime, incomplete declaration, advisory model output, or ordinary
chat message is not evidence of a policy breach. Those facts can result in
`UNKNOWN`, a freshness warning, or operator review, but cannot automatically
quarantine an Agent.

New production and restricted Agents must first be confirmed by the existing
admission flow and then prove possession of their registered Gateway
credential while in `PENDING_ACTIVATION`. The activation service derives the
Security Domain, runtime, environment, and assigned Profile from stored
authority; it never accepts an Agent-supplied expansion. Normal work tokens
are unavailable before activation. `CLIENT_SECRET` proves a boundary-only
external integration; a validated Ed25519 adapter can be recorded as
`SIGNED_ADAPTER`. Neither claim proves unobserved internal behavior.

Profiles never grant a Principal, database, Tool, API, model, secret, or
network permission. They constrain separately authorized operations. Published
versions are immutable, parent locks cannot be relaxed by a child, and
profiles reject secret-like content. The five supplied Enterprise Profile
families are unassigned templates, not default grants.

The deterministic Compliance Controller is leased and fenced in the database
and makes no model calls. It may mark stale validated evidence as `DEGRADED`.
Only explicit high-confidence rules such as credential reuse, identity-binding
conflict, Profile digest mismatch, or fencing bypass are eligible for an
automatic action. The Controller, not a dashboard user or LLM, is the only
automatic-quarantine authority. `RESTRICTED` retains only bounded heartbeat,
evidence, remediation, and recovery paths; `QUARANTINED`
and `DISABLED` revoke Gateway tokens and fence platform instances. The
platform cannot terminate arbitrary external OS processes.

The Compliance Controller has a separate `SERVICE` identity and seeds a
separate Compliance Admin `AGENT` identity with the General Restricted Profile.
The seeded Agent has no Schema Owner, Human, Admin Agent, or Gateway
credential and remains pending activation. It cannot approve exceptions,
mutate Profiles, suppress evidence, grant access, or change authoritative
posture. Controller evaluation remains deterministic and continues without
any advisory Agent or model endpoint.

## v4.3.3 Graph Trust Boundary

Graph Runtime facts in the database remain the only execution and audit
authority. Recovery evidence, A2A Task records, telemetry delivery metadata,
and imported Graph Definition metadata are bounded supporting facts; none can
grant a Principal, Agent, Skill, Tool, model, or database access.

Imported definitions are canonicalized and scanned before use. A missing or
unverifiable Ed25519 signature produces an `UNTRUSTED_DRAFT`; publication is
blocked until governed review produces a trusted definition. Private signing
keys are never written to platform tables, exports, audits, or logs. Import
scanning rejects arbitrary-code markers and records findings without executing
the import.

Dynamic Graph is a preview-only Draft workflow. It requires an authenticated
actor and reason, creates a child Version rather than mutating the source, and
rechecks approval when publishing high-risk topology, scope, or side-effect
changes. A2A and OpenTelemetry previews are disabled in `production`; A2A
advertised capabilities do not expand authorization, while OpenTelemetry is a
metadata-only redacted projection. Prompts, outputs, state, memory, artifacts,
credentials, tokens, secrets, and protected policy data are excluded by
default.

## v4.3.2 Memory Boundary

### v4.4.5 Graph Run Admission Boundary

Run admission stores the immutable Definition and Plan digests plus the
compatibility, State schema, and budget schema versions used by that Run. A
Plan is accepted only when it belongs to the requested Version and its digest
matches the Version digest. A fork that could replay a non-repeatable external
effect starts paused before any Worker claim; resuming it requires a governed
approval bound to the child Run or bounded compensation evidence. Protocol
metadata, Agent Cards, and URL state cannot satisfy this boundary.

Memory bodies, summaries, graph labels, representations, candidates, model
output, and feedback are untrusted data. They cannot grant a Principal access,
invoke a Tool, widen a Security Domain, or override current authorization.
Authorization is applied before retrieval, score, count, chain traversal,
history, snapshot, export, Artifact, model, Skill, or Tool serialization.

Operational forgetting is logical: `UNAVAILABLE`, archival, and index removal
stop ordinary Agent retrieval while preserving minimal evidence. It is not
physical deletion, model unlearning, or revocation of content already consumed
or exported. Quarantine and permission revocation take effect immediately,
including against a previously pinned Run snapshot.

## v4.3.1 Organization Scope

Organization diagrams do not grant authority. `ORG_SUBTREE` uses the
database-maintained closure table and active primary membership; secondary
membership and dotted/project reporting never widen it. Direct reports use
canonical active direct-manager facts. Security Domain scope intersects
organization scope when both apply. Results are filtered before leaving the
database-backed service.

Organization publication invalidates affected permission versions and active
credentials in the same transaction as current facts and history. Prompt
instructions, UI visibility, and client-side filtering are not boundaries.

### Human Entry Surfaces And Bootstrap Authority

Human entry admission is separate from role and data scope. `PORTAL_ACCESS`
permits the Portal surface; `APP_ACCESS` additionally permits the Dashboard and
App APIs. Existing active users receive both during migration for compatibility.
New registrations approved by an administrator start as Portal-only until App
access is explicitly enabled in User Management with a required reason.

The server evaluates the entry policy after password verification and before
MFA Session creation, and repeats it for every protected request. A policy
change increments `PERMISSION_VERSION`, revokes the target Human's active
Sessions, and records an audit event. Hiding an App link is never treated as an
authorization boundary.

The local bootstrap `admin` Principal is a protected recovery authority. Its
Portal and App admission and active `SYSTEM_ADMIN` role cannot be revoked by
the application APIs, and a DENY override cannot be assigned to it. Direct
database emergency changes remain outside the application contract and must
follow the deployment's audited break-glass procedure.

### Human Account And Organization Identity

One ordinary platform account, one Human Principal, and one organization
person are the same governed subject. An active ordinary Human must have at
least one proven login identity and exactly one active primary organization
membership. Registration approval selects that organization and commits the
account and membership together. Organization changes reject Principals that
do not have an active login identity; the database membership trigger repeats
that check against direct writes.

The protected bootstrap `admin` is the sole exception. It is a system-recovery
account, not a natural person, and cannot be assigned to the organization
hierarchy or used as a responsible person. Multiple local, LDAP, or OIDC login
identities may still bind to one Human Principal after proof and authorization;
they do not create additional people.

> This is a technical document for **Chuanxu (川序)**, the **AI Agent
> Management Platform**. `AI Agent Infra with DB` is the unified technical project
> name; database-specific package names identify the adapter and edition.

## v4.1.0 Security Boundary

Only the Admin Agent may hold a schema-owner credential. A Business Agent uses
an independent database identity and a server-derived authenticated Agent ID.
Oracle uses native End Users, PostgreSQL uses dedicated LOGIN roles plus RLS,
and YashanDB uses dedicated users with least-privilege object grants. Identity
creation, credential decryption, request identity matching, and connection
setup all fail closed; none may fall back to the Admin pool.

HTTP routes are centrally classified as public, authenticated, admin, or
side-effecting. Unclassified API routes require authentication by default.
Mutation authorization never trusts an `agent_id` supplied only in a request.

Enterprise authorization is evaluated against the catalogued resource rather
than a caller's classification claim. The catalog classification is copied to
the decision and audit record, so an `INTERNAL` request cannot make a
`SENSITIVE` resource match an internal-only policy. Unknown resources and
missing policies fail closed.

Approval actors, roles, and groups come from the authenticated server
principal. The requester cannot approve its own request under the ordinary
flow. Configured prohibited rules may match a role, a group, or a combined
`ROLE:<role>+GROUP:<group>` claim; duplicate and late decisions are recorded as
idempotent terminal outcomes without changing quorum.

The Enterprise audit plane stores metadata and policy evidence by default, not
complete request or response payloads. Bounded masked detail and a SHA-256
payload hash are optional risk controls. Retention jobs honor active legal
holds, and evidence export records filters, ordering, redaction policy, and a
content hash in `GOV_EVIDENCE_EXPORTS`.

Configuration credentials use versioned AES-256-GCM envelopes with a random
salt and nonce, a derived 256-bit key, and authenticated format metadata.
Master-key files are mode `0600`. Legacy ciphertext is read only by the
explicit migration path, which writes and verifies the new envelope before the
old value is retired. Tampering or a wrong key returns no plaintext.

Outbound HTTP jobs validate scheme, hostname, DNS results, and every redirect.
Loopback, link-local, metadata, and non-allowlisted private addresses are
denied. Commands use an argument allowlist, normalized workspace, timeout,
output bounds, and no implicit shell.

## Data Masking

`DataMaskingService` automatically detects and masks sensitive data:

| Pattern | Example Input | Masked Output |
|---------|--------------|---------------|
| email | user@example.com | ****@example.com |
| phone | 555-123-4567 | 555***-4567 |
| credit_card | 4111111111111111 | ****-****-****-1111 |
| ssn | 123-45-6789 | ***-**-6789 |
| api_key | secretAbcDefGhi... | secr...Ghi |
| ip_address | 192.168.1.1 | ***.***.***.1 |
| jwt_token | eyJhbG... | eyJ...+last16 |

### Context-Aware Masking

| Context | Patterns Masked |
|---------|----------------|
| LOGGING | email, phone, credit_card, ssn, api_key, jwt_token |
| DEBUGGING | All LOGGING + ip_address |
| ANALYTICS | credit_card, ssn, api_key, jwt_token |
| SHARING | All LOGGING + ip_address |

```python
from scripts.lib.security import DataMaskingService
svc = DataMaskingService("SHARING")
safe_text = svc.mask_text("admin@company.com called from 10.0.0.1")
safe_dict = svc.mask_dict({"password": "secret", "name": "John"})
```

## Legacy Reversible Encryption

`ReversibleEncryption` remains only for compatibility with historical data. It
MUST NOT be used for v4.1.0 credentials or configuration; those use the
AES-256-GCM envelope in `connection_crypto.py`.

```python
from scripts.lib.security import ReversibleEncryption
enc = ReversibleEncryption()
ciphertext = enc.encrypt("sensitive data")
plaintext = enc.decrypt(ciphertext)

# Key rotation
new_key = os.urandom(32)
rotated = enc.rotate_key(new_key, [ciphertext1, ciphertext2])
```

## Password Hashing

PBKDF2-HMAC-SHA256 with configurable iterations (default: 100,000).

```python
from scripts.lib.security import hash_password, verify_password
hash_val, salt = hash_password("MyPassword123!")
is_valid = verify_password("MyPassword123!", hash_val, salt)
```

## Entity Visibility

| Level | Access |
|-------|--------|
| PRIVATE | Only OWNED_BY_AGENT |
| SHARED | All registered agents |
| PUBLIC | Unrestricted (v2.1 replaces v2.0 COLLABORATIVE) |

Cross-agent sharing is managed via the AGENT_COLLABORATION table, which tracks source/target agents, collaboration type, associated entity, context, and strength.

## Access Auditing

All entity access is logged to ENTITY_ACCESS_LOG (RANGE+HASH partitioned by ACCESS_TIME and AGENT_ID):
- LOG_ID (VARCHAR2(64)), Entity ID, Agent ID, Access Type (READ/WRITE/DELETE/SEARCH/EMBED), Access Time, Session ID, Context

## Permission Auditing

Permission changes logged to AGENT_PERMISSION_LOG:
- LOG_ID (VARCHAR2(64)), Agent ID, Granted By, Permission, Resource Type, Resource ID, Action (GRANT/REVOKE/DENY), Timestamp

## Agent Collaboration

AGENT_COLLABORATION tracks cross-agent sharing requests:
- COL_ID (VARCHAR2(64)), Source Agent ID, Target Agent ID, Collaboration Type, Entity ID, Context (JSON), Strength (0-1), Created/Updated timestamps
- Foreign keys to AGENT_REGISTRY and ENTITIES

## PL/SQL Security Functions

`AGENT_PERMISSION_MANAGER.check_entity_access(agent_id, entity_id)`:
- Returns 'GRANTED' if entity is SHARED/PUBLIC or owner matches
- Returns 'DENIED' for PRIVATE entities not owned by the requesting agent

## Deep Data Security (v3.7.0)

v3.7.0 replaces VPD with Oracle Deep Data Security:

- **23 Data Grants** enforce row-level, column-level, and cell-level access control (including `collab_member_own` for COLLAB_GROUP_MEMBERS and `collab_group_member_access` for COLLAB_GROUPS)

### 23 Data Grants Summary

| Table | Privilege | Predicate | Role |
|-------|-----------|-----------|------|
| AGENT_REGISTRY | SELECT | 1=1 | admin_data_role |
| AGENT_REGISTRY | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | SELECT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC' | agent_data_role |
| ENTITIES | INSERT | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | UPDATE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITIES | DELETE | OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_EDGES | SELECT | SOURCE_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| KNOWLEDGE_META | SELECT | ENTITY_ID IN (SELECT ENTITY_ID FROM ENTITIES WHERE OWNED_BY_AGENT = SYS_CONTEXT('END_USER_CTX','AGENT_ID') OR VISIBILITY = 'PUBLIC') | agent_data_role |
| WORKSPACES | SELECT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACES | INSERT | OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID') | agent_data_role |
| WORKSPACE_CONTEXT | SELECT | WORKSPACE_ID IN (SELECT WORKSPACE_ID FROM WORKSPACES WHERE OWNER_USER_ID = SYS_CONTEXT('END_USER_CTX','USER_ID')) | agent_data_role |
| AGENT_SESSION | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| AGENT_SESSION | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_PLANS | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| TASK_STEPS | SELECT | PLAN_ID IN (SELECT PLAN_ID FROM TASK_PLANS WHERE AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID')) | agent_data_role |
| ENTITY_ACCESS_LOG | SELECT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| ENTITY_ACCESS_LOG | INSERT | AGENT_ID = SYS_CONTEXT('END_USER_CTX','AGENT_ID') | agent_data_role |
| SYSTEM_CONFIG | SELECT | 1=0 | agent_data_role |
| TAGS | SELECT | 1=1 | agent_data_role |

### MAC Enforcement

MAC (Mandatory Access Control) is enforced on 7 critical tables, preventing predicate bypass even by schema owners:

1. ENTITIES
2. ENTITY_EDGES
3. KNOWLEDGE_META
4. WORKSPACES
5. WORKSPACE_CONTEXT
6. AGENT_SESSION
7. TASK_PLANS

### End User Lifecycle

Agent registration automatically creates a Deep Sec End User:

1. `register_agent()` calls `_ensure_end_user(agent_id)`
2. `_ensure_end_user()` calls `END_USER_MANAGER.create_end_user(agent_id)`
3. End User is created with name `UPPER(REPLACE(agent_id, '-', '_'))`
4. `agent_data_role` is granted to the End User
5. `DEEP_SEC_SESSION_ROLE` is granted via the Data Role (enables CREATE SESSION)

On decommission, `END_USER_MANAGER.drop_end_user(agent_id)` removes the End User.

### WORKSPACE_CONTEXT VISIBILITY

WORKSPACE_CONTEXT has a VISIBILITY column (PRIVATE/SHARED/PUBLIC, default SHARED) that controls cross-agent context visibility in collaboration group workspaces:

| VISIBILITY | Agent sees own context? | Other agents in collab group see it? |
|------------|------------------------|--------------------------------------|
| PRIVATE | Yes (always) | No — blocked by Data Grant predicate |
| SHARED | Yes (always) | Yes — visible to collab group members |
| PUBLIC | Yes (always) | Yes — visible to all |

The `WS_CTX_AGENT_ACCESS` Data Grant predicate enforces these rules:
- Agent always sees its own context (AGENT_ID matches own End User) regardless of VISIBILITY
- Agent sees other agents' SHARED/PUBLIC context only in collab group workspaces (via COLLAB_GROUPS + COLLAB_GROUP_MEMBERS subquery)
- Agent CANNOT see other agents' PRIVATE context even in the same collab group workspace

This prevents one agent's private thoughts, internal reasoning, or sensitive intermediate results from being exposed to other agents sharing the same workspace.

### Per-Request Context Switching

Each request sets agent identity for Data Grant predicates:

1. Application receives request with agent context
2. `set_agent_context(agent_id)` sets `END_USER_CTX` namespace with AGENT_ID, USER_ID
3. Data Grant predicates reference `SYS_CONTEXT('END_USER_CTX', 'AGENT_ID')` for filtering
4. After request completes, `clear_agent_context()` clears the context

**Portal identity rule**: Portal APIs retain the authenticated Business
Agent's independent connection. Authorization or connection failures fail
closed; Portal code never switches to AIADMIN or another Schema Owner
connection.

### Verification Data

Testing with AGENT_001 End User confirms Data Grant filtering:

| Table | Total Rows | AGENT_001 Visible | Notes |
|-------|-----------|-------------------|-------|
| AGENT_REGISTRY | 14 | 1 | Only own agent row visible |
| ENTITIES | 210 | 40 | Own entities + PUBLIC entities |
| SYSTEM_CONFIG | 1 | 0 | Blocked by `1=0` predicate |


## Per-Agent Encryption Keys (v3.10.2)

**Added 2026-07-16** — Each Business Agent receives its own independent 256-bit encryption key at registration time.

### Architecture

- **Key Storage**:  table, key = 
- **Key Distribution**: Encrypted with admin_token as key material via 
- **Key Version**: Tracked via  for rotation detection
- **Key Rotation**:  (global) and  (per-Agent)

### Config.json Auto-Encryption

On server startup,  transparently encrypts:

-  section: user, password, DSN
-  section: api_key
-  section: simple_api_key, standard_api_key, complex_api_key

Uses PBKDF2-HMAC-SHA512 key derivation with 210,000 iterations, AES-like stream cipher with HMAC authentication. Master key stored in  (chmod 600).

### CLI Tool



### Per-Agent Key Lifecycle

1. **Registration**: Agent receives its crypto key encrypted with admin_token
2. **Storage**: Key stored in SYSTEM_CONFIG (not in agent config files)
3. **Usage**: Agent uses key to encrypt/decrypt local config and session data
4. **Rotation**: Admin triggers rotation via API, affected credentials re-encrypted
5. **Detection**: Agent heartbeat checks key version, triggers local re-encryption on change

## v4.3.0 Graph, Principal, And Collaboration Security Boundary

Graph ownership does not grant access to every resource connected to a graph.
Each Node declares an execution subject, capability, resource/action,
State/Secret scope, environment, purpose, and side-effect class. The Compiler
performs a preflight check; the Runtime repeats registration, grant, policy,
and revocation checks before a Worker can claim or complete the Node.

Dynamic versions and subgraphs inherit a maximum permission and budget envelope
and cannot silently expand it. A topology change that adds data/API/Skill/Tool
access, increases a hard budget, introduces an untrusted extension, or adds a
non-idempotent effect is high risk and uses the existing Enterprise policy and
approval boundary.

State Events are recovery authority, Trace is operational control-flow
evidence, and Compliance Audit is the security/governance record. Large or
sensitive content is stored once as a classified Artifact and referenced by
hash. Export is redacted by default; retention and legal hold prevent expiry
or purge until an authorized release operation with a reason.

Graph triggers are registered against an immutable published Graph Version and
carry an explicit actor and reason. The common trigger contract covers manual,
API, scheduled, database, external, and internal sources; delivery enters the
authenticated, idempotent Event Inbox before an optional Run is created. The
registration table is an additive migration step
(`14_v4_2_0_graph_triggers.sql`) so trigger history remains intact when an
earlier v4.2 draft is upgraded.

Workers use short-lived Lease Tokens with fencing. A stale or expired token
cannot commit a checkpoint or result. An exact replay of a committed
completion is identified by its digest and cannot create a second checkpoint
or Transition. Event Inbox/Outbox operations require idempotency keys;
unauthenticated events may be received for later inspection but cannot activate
waiting work. Non-idempotent external effects are never retried blindly after
an uncertain outcome. Idempotent external effects receive a stable logical
Run/Node Run key in `GRAPH_ATTEMPTS.EFFECT_IDEMPOTENCY_KEY` so the compatible
remote system can deduplicate a lease retry; the key is deliberately absent for
non-idempotent effects.

Trigger registration is also governed: the target Graph Version must be
published, the caller and reason are mandatory, and the trigger configuration
is validated before it is stored. Trigger delivery uses the same authenticated
Inbox and idempotency boundary as direct events. The database trigger table is
created by the additive `14_v4_2_0_graph_triggers.sql` step.

In v4.3.0, executable Nodes also resolve a versioned Executor manifest before
claim and completion. The registry is not an execution plug-in channel:
manifests are declarative, arbitrary callbacks are rejected, and a disabled or
deprecated custom Executor cannot be selected for new work. Registry status
changes and dead-letter replay are recorded with an authenticated actor and a
non-empty reason in `GRAPH_GOVERNANCE_EVENTS`. Event retry metadata is bounded
by `MAX_ATTEMPTS`; an uncertain non-idempotent external effect is held for
review rather than automatically repeated.

Human and Agent requests first resolve to an active database Principal. Unknown,
inactive, pending, expired, or permission-version-stale identities are denied
before role fallback. Human registration uses an approval boundary by default;
Agent registration uses a one-time Enrollment Token bound to owner, sponsor,
runtime, environment, risk tier, quota, and Security Domain. Token digests and
credential digests are stored instead of reusable plaintext secrets.

Channel membership is deliberately weaker than data authorization. A Channel
can show attributable collaboration messages and structured control cards, but
it never expands database, API, Skill, Tool, model, memory, Artifact, or export
scope. Every Channel, Barrier, and Gateway query rechecks active membership,
validity, classification, Principal status, instance fencing, and token expiry.
PostgreSQL RLS applies the same Channel membership predicate to Barrier arrivals
so an Agent cannot read an arrival merely because it is the arrival's author.

Administrative registration policy changes use optimistic version checks and
require an authenticated reason. Provider profiles store only a secret-manager
reference; configuration alone never enables a provider, and provider tests do
not fetch arbitrary administrator-supplied URLs. Every authenticated mutation
is also subject to the session's database authorization and CSRF boundary.


Gateway restart recovery is node-scoped. Web startup or shutdown revokes and
fences only Portal assignments and Agent instances recorded with the local node
identity. Other nodes in the same Admin Agent collaboration group retain their
leases. Claimed deliveries from the local node return to `PENDING` for bounded
reclaim rather than remaining invisibly stuck.

### v4.4.4 Agent Pool Endpoint and Administration Command Boundaries

External database endpoint discovery is bound to the registered Agent's active
Enrollment Grant. The grant policy snapshot carries only the endpoint
reference and Security Domain reference; it never carries a database password
or API key. Expired, revoked, or unbound grants fall back to the initialization
endpoint, and repeated discovery requests are rate limited per Agent identity.

The protected Administration Channel accepts typed `/platform` commands only
when a human administrator explicitly mentions a management Agent. Read-only
commands return credential-free control-plane summaries. Mutating commands are
converted to Action Cards and require the existing separated approval path.
Neither ordinary prose, prompts, Skills, Tools, nor an LLM response can execute
a database mutation.

Node draining and retirement are separate from emergency containment.
`/platform AGENT_DRAIN` is a typed, scope-checked proposal and cannot be
activated merely because an Agent or model emitted that text. Its Action Card
records source, destination, reason, expected version and expiry, and must be
approved by the configured human/Admin policy. Execution fences new work on
the source and retries only expired retryable claims. It does not terminate a
task already running; a separate containment incident is required for that
higher-impact action. Retired nodes and LLM profiles remain auditable but are
excluded from active discovery, and LLM retirement revokes stored encrypted
API-key ciphertext.

## v4.4.7 LLM Health and Authorization Manifest

An active LLM Provider Profile is healthy only after a bounded saved-profile
probe receives a valid completion from the configured model. A provider
namespace prefix is accepted, but an endpoint that serves another model is
marked `DEGRADED`. Probe responses and audit facts never include the API key,
ciphertext, prompt body, or completion body.

LLM retirement remains logical and fail-closed. Portal default and allowlist
references, active native Agents, and pending Business Agent requests must be
removed or replaced before retirement. Successful retirement revokes the
stored encrypted secret while preserving auditable history.

The Dashboard capability manifest evaluates all requested actions from one
current database authorization snapshot. This is a query optimization, not an
authorization cache: principal status, active roles, explicit overrides,
delegation validity, read-only state, and platform capability state are checked
on every manifest request.

## v4.4.6 Human and Portal Admission

Registration field requirements are read from versioned database policy and
are enforced again by the service. Browser-required markers are not a security
boundary. Human Registration Tokens use a purpose-separated keyed digest,
expire, can be revoked before use, and are consumed once. They cannot be used
as Agent Enrollment, password-reset, or external-login credentials.

Portal and Dashboard cookies remain entry-scoped. Portal connection slots and
exclusive page-operation leases are database-backed and fenced by Session and
page-instance digests. A reused Session cannot mutate through chat, streaming,
bulk, keyboard, hidden-menu, or direct API paths while another page owns the
lease. Provider claims and QR/OIDC metadata are identity evidence only; role,
scope, organization, entry access, MFA, and approval remain separate checks.
