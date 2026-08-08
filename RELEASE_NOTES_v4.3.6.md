# Chuanxu AI Agent Management Platform v4.3.6

Release date: 2026-08-07

## Platform-Native Agents

v4.3.6 adds a complete platform-native Agent supply path. During initialization
the software can create the Platform Admin Agent without depending on another
Agent or on an available LLM. Enterprise editions additionally create the
Compliance Admin Agent. Both are independent system Principals and are not the
human `admin` user, an external Skill runtime, or a Schema Owner fallback.

When an approved LLM Provider Profile is not configured, the identities and
their locked baseline policies are still initialized and remain
`ACTIVATION_PENDING`. Model availability is an activation prerequisite, not a
reason to skip the authoritative database bootstrap.

## Business Agent Provisioning

Authorized humans can submit a business Agent request with an owner, purpose,
template, data classification, LLM profile, runtime target, isolation level,
requested capabilities, and reason. The applicant cannot approve the request.
After approval the platform creates an independent restricted Agent identity
and deployment record. Business Agents never fall back to Schema Owner
credentials.

Built-in templates include General Restricted, Code Development, Production
Operations, and the platform management profiles. Template locked fields keep
database, secrets, approval, network, export, and command restrictions outside
ordinary Agent self-configuration.

## Runtime And Customer Integration

The reference local Runtime Worker uses database leases and fencing. A reused
Worker Pool shares scheduling capacity only; execution context, temporary
workspace, database session, short-lived token, secrets, and model conversation
state are isolated per execution unit. High-risk templates can require a
dedicated container or runtime.

v4.3.6 publishes DeploymentTarget and RuntimeAdapter contracts covering local,
remote-worker, container, webhook, health, cancellation, revocation, and
evidence operations. Customer-specific virtualization, SaaS, MaaS, or Agent
platform connectors remain delivery extensions and are not claimed as built-in
vendor integrations.

## External Skill-First Compatibility

Existing external Agents continue to read `SKILL.md` and use the registered
Agent enrollment, authentication, Gateway, Skill, Tool, and audit boundaries.
The new database-authoritative `external_agent_registration` policy controls
only new external enrollment and supports `DISABLED`, `APPROVAL_ONLY`, and
`ENABLED`. Existing external Agents are not changed by this setting.

## Database And Release Boundary

Oracle AI Database 26ai, PostgreSQL 18 with Apache AGE where enabled, and
YashanDB 23.5.4+ receive the same v4.3.6 logical contract through additive
migration `32_v4_3_6_native_agents.sql`. Community packages do not expose
Enterprise compliance behavior; Enterprise packages retain the full governed
compliance plane.

Apply the migration through `migration_runner.py --version 4.3.6`, then run
the generated package tests and the live database contract checks. This
release does not claim database-cluster failover or customer-specific external
platform integration merely because a DeploymentTarget exists.
