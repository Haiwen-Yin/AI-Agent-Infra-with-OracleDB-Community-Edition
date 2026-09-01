# AI Agent Infra v4.4.11

v4.4.11 adds an evidence-bound runtime isolation contract and
database-mediated Agent collaboration over the v4.4.10 fresh-deployment
baseline.

## Runtime Isolation

- Adds ordered `SHARED`, `DOMAIN_ISOLATED`, `DEDICATED_RUNTIME`,
  `DEDICATED_CONTAINER`, and `DEDICATED_VM` levels.
- A container or VM claim requires verified process, filesystem, IPC, network,
  resource, and credential evidence. Reference lifecycle adapters remain
  `UNVERIFIED` and cannot satisfy this admission gate.
- External or untrusted Agents require a verified container or VM boundary.
- The local Linux adapter uses transient systemd services, per-Agent UID/GID,
  cgroup v2 limits, bubblewrap namespaces, read-only rootfs, private
  work/secrets, zero capabilities, no-new-privileges, and libseccomp. It reports
  `VERIFIED` only from complete host evidence for the actual sandbox process.
- Oracle Linux 9.8 testing verified same-host and cross-Agent process,
  filesystem, credential, network, ptrace, resource, and revoke negatives.
  Default-deny network is supported; non-empty egress allowlists fail closed
  until a firewall backend is configured.
- Identity, policy, or rootfs drift enters `DRAIN` and stops new work.
- Database authorization remains independent of runtime isolation. RLS, Data
  Grant, Principal, Organization, and Security Domain checks still apply.

## DB4A2A

- Adds reference-oriented Agent dispatch with task, Context, snapshot digest,
  expected version, scope, transport, and branch policy facts.
- A Context reference never grants authority. The receiver authenticates with
  its own Principal and all existing database authorization remains active.
- Shared Context is read-only by default. `CHILD_BRANCH_WRITE` invokes the
  existing Branch service and records immutable source Context provenance.
- Standard A2A remains the cross-organization or database-inaccessible
  fallback. Agent Cards and protocol metadata remain descriptive.

## Database And API

- Migration 66 adds `CX_RUNTIME_ISOLATION_CONTRACTS` and
  `CX_DB4A2A_DISPATCHES` on Oracle AI Database 26ai, PostgreSQL, and YashanDB.
- Migration 67 adds durable isolation admission evidence to native runtime
  executions before any model or Tool work is invoked.
- Adds authenticated isolation-contract, DB4A2A dispatch inventory, and child
  branch endpoints. Existing `agents.manage`, `agents.operate`, and
  `tasks.read` actions remain the authorization boundary.

## Boundaries

- v4.4.11 does not claim that host root or an infrastructure administrator
  cannot inspect a workload.
- Reference adapters do not create namespaces, containers, VMs, or remote
  termination capability.
- The verified Linux result does not cover host root, selective egress,
  container/VM escape, or MaaS/SaaS tenant isolation.
- Oracle Linux 9.8 x86_64 is the currently verified local strong-isolation
  baseline. RHEL-compatible, international, and domestic Linux distributions
  are candidates only until their exact image passes the packaged gate. RHEL
  8.10 remains usable for the control plane but its legacy cgroup v1 baseline
  cannot satisfy the current verified local-Agent boundary.
- Dynamic Graph Migration, arbitrary Framework Adapter Execution, unrestricted
  Replay, A2A production interoperability, and OTLP production export remain
  closed pending independent evidence.
