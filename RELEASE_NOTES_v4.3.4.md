# Chuanxu AI Agent Infra v4.3.4

Release date: 2026-08-04

## Agent Compliance Posture And Governed Profiles

v4.3.4 adds an Enterprise compliance plane for database-authoritative Agent
admission, evidence, posture, controlled recovery, and governed Profiles.
Registration, runtime, compliance, and control state remain independent:
missing Skill activity, an idle Agent, or an unavailable model does not by
itself create a violation.

The release also fixes Portal authentication when a prior request has entered
an Agent database context. Human session and entry-access checks now execute
as the Schema Owner, while the Agent context is restored only after the check;
Oracle pool cleanup is guaranteed and transient pool contention uses a bounded
wait. This prevents valid Portal logins from being reported as unavailable
because Oracle row security hid identity tables from a Business Agent.

- New Agents complete a registered-credential Gateway activation proof before
  receiving normal work tokens. A management-page action cannot fabricate the
  proof for a pending Agent.
- Adds immutable published Governed Profile versions, unassigned restricted
  seed families, bounded inheritance validation, assignment history, and
  material reactivation posture reset.
- Adds append-only evidence, posture projections, deterministic findings,
  remediation cases, scoped time-bounded exceptions, control states, and a
  database-leased deterministic Compliance Controller.
- Adds Enterprise Compliance Dashboard inventory, Findings, Profiles,
  Remediation, Exceptions, and Controller diagnostics. MCP exposes only the
  authenticated Agent's own reduced posture and bounded boundary evidence.

## Security Boundary

Prompt instructions, Skill declarations, API descriptions, self-reports, and
model analysis are not authorization boundaries. The enforcement points are
database identity and permissions, Gateway credentials and fencing, current
control state, scoped tokens, resource authorization, approval, and audited
state transitions. External Agent compatibility is truthfully represented as
`BOUNDARY_ONLY` unless a validated signed adapter proves otherwise.

`RESTRICTED` permits only bounded heartbeat, governed evidence, remediation,
and recovery paths. `QUARANTINED` and `DISABLED` revoke active tokens and fence
instances; they do not terminate arbitrary external operating-system
processes. Automatic quarantine is reserved for explicit high-confidence,
deterministic Controller rules, never inactivity or missing Skill calls.

## Upgrade

Record recoverable backup evidence and apply the v4.3.4 migration set
(`29_v4_3_4_agent_compliance.sql` and
`30_v4_3_4_compliance_hardening.sql`) with `migration_runner.py`. The
migrations are additive. Legacy Agents are backfilled as `UNKNOWN` and `BOUNDARY_ONLY`; no
historical runtime, Skill, or signature proof is fabricated. Enterprise seed
Profiles are unassigned and do not widen an Agent's authority on upgrade.
