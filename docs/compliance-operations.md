# Chuanxu v4.5.2 Compliance and Profile Operations

[中文说明](compliance-operations_zh.md)

## Capability and evidence boundaries

Check effective edition capabilities before operating with an authorized identity.
Community basic activation, posture and manual controls do not imply Enterprise
Compliance workspace, Controller, Governed Profiles, exceptions or remediation
automation. Buttons, prompts, Skills and switches never grant permission.

MANAGED_RUNTIME describes evidence within managed execution; SIGNED_ADAPTER
describes verified signed-adapter evidence; BOUNDARY_ONLY proves only an
authenticated interface boundary. External Skill/API integration cannot prove
control of Agent internals. Self-report and model analysis are not independent
security evidence.

## Four state dimensions

| Dimension | States and meaning |
|---|---|
| Registration | PENDING_CONFIRMATION: confirmation needed; PENDING_ACTIVATION: activation needed; ACTIVE: activated; DISABLED: disabled |
| Runtime | NEVER_SEEN: no runtime evidence; ONLINE: online; IDLE: idle; STALE: expired evidence; OFFLINE: offline |
| Compliance | UNKNOWN: insufficient evidence; COMPLIANT: current rules satisfied; DEGRADED: reduced evidence or assurance; NON_COMPLIANT: confirmed violation |
| Control | NORMAL: normal authorized access; RESTRICTED: bounded remediation/recovery only; QUARANTINED: isolated; DISABLED: disabled |

Idle/offline status, absent Skill calls and model advice are not violations.
Inspect evidence time, rule and Profile versions. UNKNOWN is not NON_COMPLIANT;
ONLINE does not authorize access. Expired evidence may cause DEGRADED but does
not alone trigger automatic quarantine.

## Profile operation sequence

A Profile is a database-owned versioned constraint; a Harness organizes execution.
Neither replaces identity, resource grants or isolation. Seed Profiles are
unassigned templates, not default grants.

The five seed families are General Restricted (`general-restricted`), Code
Development (`code-development`), Production Operations (`production-operations`),
Sensitive Data Analysis (`sensitive-data-analysis`) and Security Review
(`security-review`). For sensitive production work, start from the corresponding
published family, retain its locked approval/data/export controls and review a
child or successor. A family name alone does not establish isolation or access.

1. Inspect an authorized Profile's version, digest, parent and field origins.
2. Create a child draft from a published parent or create a successor. Do not edit published versions in place.
3. Edit and validate. Unpublished parents, inheritance cycles or excessive depth, digest mismatch, unknown fields and weakened locked fields are rejected. Keep secrets in protected credential configuration, never Profile content.
4. Request publication and complete applicable approval. Read the published version and digest to confirm.
5. Before assignment, review affected Agents, environments, Security Domains, instances and independent resource grants. Publication does not assign every Agent or grant database, model, network or Tool permissions.
6. Request assignment and complete approval. Activate against the current binding and check the persisted activation, Profile digest and evidence class. Old activation does not prove a new version is effective.

Invalid old drafts remain inspectable and repairable, never effective policy.
Review drift after changes. Restoring earlier behavior requires governed
reassignment of a published version with history retained.

## Findings, remediation and exceptions

Inspect the Finding's subject, rule, severity, evidence and last-observed time.
Acknowledge, resolve or reopen with a reason; resolution also requires an evidence
reference. Reload and review when state or observation changes concurrently.

The target Agent submits structured remediation responses through authorized
interfaces. Receipt is not successful remediation. An authorized Human verifies
evidence and resolves the Finding; its open cases then become resolved. Overdue
notifications grant nothing and do not restore access.

Case creation, finding state, audit and the durable notification commit together.
After an interrupted request, retry against the same Finding and inspect the
existing case. A missing legacy notice is repaired from the stored action and
deadline, not the retry payload. A legacy case with no deadline receives an
informational notice; the system does not invent a due date.

Exceptions require a bounded subject, policy, reason and expiry, with approval
by an active Human distinct from the requester. Approval, rejection, revocation
and expiry retain audit; expiry never restores revoked authority. The Compliance
Agent may propose work but cannot approve its own exception, change authoritative
posture or grant access.

## Quarantine and recovery

Manual control checks current permission and version. Deterministic Controller
actions and approval-based paths differ; model advice cannot directly trigger
automatic quarantine. Quarantine/disablement revoke platform tokens and fence
instances without deleting history or guaranteeing termination of external processes.

Review remediation before an authorized manager explicitly restores access.
Open remediation blocks restoration to NORMAL. Restoration does not reactivate
old tokens; use the current authorized admission flow.

Controller leases, fences and state persist in the database. A stale Worker
cannot mutate posture. Evaluation and completion commit together; expiry before
completion rolls changes back. Restart from durable state without deleting audit
or resetting another node's valid lease.

Renewal checks the live owner and fencing token; an expired lease cannot be
revived. Duplicate scheduling resolves the existing logical job. PostgreSQL
completion checks wall-clock time, including time spent inside the transaction.

Back up the database and configuration before deployment; verify dependencies and
checksums against the current package installation contract. Historical migration
29 and old upgrade scenarios do not promise current in-place upgrades. Preserve
failure logs/journals and verify recovery before continuing. Single-host recovery
does not establish database-cluster HA or RPO/RTO.

Treat legacy Agents without historical evidence as UNKNOWN. During the recorded
grace period, collect current activation/evidence and review scope before staged
enforcement; missing history alone is not grounds for immediate quarantine.
If installation or verification fails, stop that deployment and preserve its
journal. Restore only from a verified backup under an explicit recovery plan;
do not reset checksums, replay old tokens or silently reactivate Agents. No
backup/restore or multi-node database HA certification is implied by these
single-instance tests.
