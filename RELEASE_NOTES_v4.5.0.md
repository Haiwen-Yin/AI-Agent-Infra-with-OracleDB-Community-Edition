# Chuanxu v4.5.0

Date: 2026-09-27

## Changes

- Prevent compound Agent selectors from overlapping hints and adjacent fields in
  containment, external access grants, Channel/Domain membership and Branch forms;
  allow wrapped labels and resized textareas to expand their form rows.
- Prevent desktop navigation from overlapping the brand and session controls;
  use a separate navigation row at constrained widths.
- Commit Compliance Controller posture evaluation and completion atomically with
  lease fencing, including natural lease expiry during PostgreSQL transactions.
- Renew only live owned leases, reconcile concurrent job scheduling, and persist
  remediation state, audit and notification atomically. Repair missing legacy
  notices from stored case facts rather than changed retry parameters.
- Return diagnostics for invalid Graph retry policies and detect all cycle
  members without recursive traversal limits.
- Make Join thresholds independent of branch arrival and normalize plan digests
  across input ordering; reject non-finite timeouts and invalid budgets.
- Require clause-specific historical contract acceptance before release approval;
  an aggregate passing result or specification title is insufficient.
- Recover Space validation after a successful Embedding Profile probe, preserving
  write policy and bindings and rejecting results for a changed Profile version.
- Align effective capability checks with database-owned state and authorization.
- Reconcile specification indexes and historical changes. Build and validation
  tools support explicit target dates and independent evidence output paths.
- Refresh bilingual screenshots, website and customer/investor materials.

## Deployment boundary

Packages retain the reviewed relational schema chain
through migration 97. Historical SQL and checksums are unchanged. Later schema
changes require additive migrations and new native verification evidence.
No production feature is enabled by changing a version label. OCI is excluded
from this development and acceptance cycle.

## Capability and validation boundaries

Controlled and disabled capabilities retain their explicit gates. Evaluation of
new MCP behavior, Graph operations or telemetry does not itself enable them.
Local Oracle, PostgreSQL and YashanDB COM/ENT validation includes fresh database
initialization, native verification, actual model workflows and authorization
checks. The final release manifest identifies exact artifacts and remaining
gates; these notes alone do not certify release readiness, customer capacity,
database high availability or external protocol interoperability.
